"""待办 → 飞书任务同步单元测试（lark SDK 全部打桩，无真实网络）。"""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

import scripts.dispatch.task_sync as task_sync
from scripts.dispatch.task_sync import (
    complete_task_for_todo,
    create_task_for_todo,
    load_user_open_id,
    record_user_open_id,
    sender_open_id,
)


@pytest.fixture
def state_dir(tmp_path):
    path = tmp_path / "state"
    path.mkdir()
    return path


def _fake_lark(monkeypatch, client):
    """把 lark_oapi 换成假模块：builder 链自动成立。"""
    fake_lark = MagicMock()
    fake_lark.Client.builder.return_value.app_id.return_value.app_secret.return_value.build.return_value = (
        client
    )
    monkeypatch.setattr(task_sync, "_import_lark", lambda: fake_lark)
    return fake_lark


def _creds(monkeypatch):
    monkeypatch.setenv("FEISHU_APP_ID", "cli_x")
    monkeypatch.setenv("FEISHU_APP_SECRET", "secret")


# ---- open_id 识别 ----------------------------------------------------------


def test_record_and_load_open_id(state_dir):
    """缓存写入后可读；同值重写不写盘（幂等）。"""
    record_user_open_id(state_dir, "ou_abc")
    assert load_user_open_id(state_dir) == "ou_abc"
    record_user_open_id(state_dir, "ou_abc")
    record_user_open_id(state_dir, "")  # 空值不写
    assert load_user_open_id(state_dir) == "ou_abc"


def test_load_open_id_env_priority(state_dir, monkeypatch):
    """FEISHU_USER_ID 环境变量优先于缓存。"""
    record_user_open_id(state_dir, "ou_cached")
    monkeypatch.setenv("FEISHU_USER_ID", "ou_env")
    assert load_user_open_id(state_dir) == "ou_env"
    assert load_user_open_id(state_dir, use_env=False) == "ou_cached"


def test_load_open_id_corrupt_file(state_dir):
    """状态文件损坏按无身份处理。"""
    (state_dir / "feishu_account.json").write_text("not json", encoding="utf-8")
    assert load_user_open_id(state_dir) is None


def test_sender_open_id_duck_typing():
    """sender/operator 三种形态都能取到 open_id。"""
    msg_sender = SimpleNamespace(sender_id=SimpleNamespace(open_id="ou_1"))
    assert sender_open_id(msg_sender) == "ou_1"
    operator = SimpleNamespace(open_id="ou_2")
    assert sender_open_id(operator) == "ou_2"
    assert sender_open_id({"sender_id": {"open_id": "ou_3"}}) == "ou_3"
    assert sender_open_id({"open_id": "ou_4"}) == "ou_4"
    assert sender_open_id(None) is None
    assert sender_open_id(SimpleNamespace()) is None


# ---- 建任务 ----------------------------------------------------------------


def test_create_task_success(state_dir, monkeypatch):
    """建任务成功：登记 文件名 → guid，幂等不重复建。"""
    _creds(monkeypatch)
    monkeypatch.setenv("FEISHU_USER_ID", "ou_me")
    client = MagicMock()
    resp = client.task.v2.task.create.return_value
    resp.success.return_value = True
    resp.data.task.guid = "guid-1"
    _fake_lark(monkeypatch, client)

    assert create_task_for_todo(state_dir, "todo-a.md", "读《XX》", "2026-09-20")
    tasks = json.loads(
        (state_dir / "feishu_tasks.json").read_text(encoding="utf-8")
    )["tasks"]
    assert tasks == {"todo-a.md": "guid-1"}
    # 幂等：再建不再调 API
    client.task.v2.task.create.reset_mock()
    assert create_task_for_todo(state_dir, "todo-a.md", "读《XX》")
    client.task.v2.task.create.assert_not_called()


def test_create_task_without_open_id_skips(state_dir, monkeypatch):
    """未识别用户身份：跳过建任务（不建不可见任务），不碰 API。"""
    _creds(monkeypatch)
    monkeypatch.delenv("FEISHU_USER_ID", raising=False)
    client = MagicMock()
    _fake_lark(monkeypatch, client)

    assert not create_task_for_todo(state_dir, "todo-a.md", "读《XX》")
    client.task.v2.task.create.assert_not_called()
    assert not (state_dir / "feishu_tasks.json").exists()


def test_create_task_api_failure(state_dir, monkeypatch):
    """API 失败返回 False 且不登记。"""
    _creds(monkeypatch)
    monkeypatch.setenv("FEISHU_USER_ID", "ou_me")
    client = MagicMock()
    client.task.v2.task.create.return_value.success.return_value = False
    _fake_lark(monkeypatch, client)

    assert not create_task_for_todo(state_dir, "todo-a.md", "读《XX》")
    assert not (state_dir / "feishu_tasks.json").exists()


def test_create_task_missing_creds(state_dir, monkeypatch):
    """凭证缺失静默 False（绝不抛异常）。"""
    monkeypatch.delenv("FEISHU_APP_ID", raising=False)
    monkeypatch.delenv("FEISHU_APP_SECRET", raising=False)
    monkeypatch.setenv("FEISHU_USER_ID", "ou_me")
    _fake_lark(monkeypatch, MagicMock())

    assert not create_task_for_todo(state_dir, "todo-a.md", "读《XX》")


def test_create_task_empty_title(state_dir):
    """空标题不建。"""
    assert not create_task_for_todo(state_dir, "todo-a.md", "  ")


# ---- 完成回写 --------------------------------------------------------------


def test_complete_task_success(state_dir, monkeypatch):
    """完成回写：按登记 guid patch completed_at。"""
    _creds(monkeypatch)
    monkeypatch.setenv("FEISHU_USER_ID", "ou_me")
    client = MagicMock()
    client.task.v2.task.patch.return_value.success.return_value = True
    _fake_lark(monkeypatch, client)
    task_sync._save_tasks(state_dir, {"todo-a.md": "guid-1"})

    assert complete_task_for_todo(state_dir, "todo-a.md")
    client.task.v2.task.patch.assert_called_once()


def test_complete_task_without_mapping(state_dir, monkeypatch):
    """无登记（老待办/未同步）：静默 False，不碰 API。"""
    _creds(monkeypatch)
    client = MagicMock()
    _fake_lark(monkeypatch, client)

    assert not complete_task_for_todo(state_dir, "todo-old.md")
    client.task.v2.task.patch.assert_not_called()


def test_complete_task_api_failure(state_dir, monkeypatch):
    """回写 API 失败返回 False（不抛异常）。"""
    _creds(monkeypatch)
    client = MagicMock()
    client.task.v2.task.patch.return_value.success.return_value = False
    _fake_lark(monkeypatch, client)
    task_sync._save_tasks(state_dir, {"todo-a.md": "guid-1"})

    assert not complete_task_for_todo(state_dir, "todo-a.md")


# ---- dispatch_cli 接线 -----------------------------------------------------


def test_parse_todo_task(tmp_path):
    """从待办笔记提取任务文本与截止日。"""
    from scripts.cli.dispatch_cli import _parse_todo_task

    note = tmp_path / "todo-1.md"
    note.write_text(
        "---\ntitle: 读书\n---\n# 读书\n\n- [ ] 读《作为意志和表象的世界》 📅 2026-09-20\n\n> 来源：[[x]]\n",
        encoding="utf-8",
    )
    title, due = _parse_todo_task(note)
    assert title == "读《作为意志和表象的世界》"
    assert due == "2026-09-20"
    assert _parse_todo_task(tmp_path / "gone.md") == (None, None)
    plain = tmp_path / "todo-2.md"
    plain.write_text("# t\n\n- [ ] 无截止任务\n", encoding="utf-8")
    assert _parse_todo_task(plain) == ("无截止任务", None)


def test_cli_todos_creates_feishu_task(memory_tree, tmp_path, monkeypatch):
    """todos 分发产出待办后：推卡片 + 同步建飞书任务（均打桩）。"""
    from scripts.cli.dispatch_cli import DispatchCLI

    memory_tree.create_note("日记.md", "# 日记\n\n- [ ] 交周报 📅 2026-09-12\n")
    config = tmp_path / "memory.yaml"
    config.write_text(
        f"memory:\n  root: {memory_tree.notes_dir}\n"
        f"  state_dir: {memory_tree.state_dir}\n",
        encoding="utf-8",
    )
    monkeypatch.setattr("scripts.cli.dispatch_cli.send_todo_feishu", lambda f: True)
    created = []
    monkeypatch.setattr(
        "scripts.dispatch.task_sync.create_task_for_todo",
        lambda state_dir, filename, title, due=None: created.append(
            (filename, title, due)
        )
        or True,
    )

    code = DispatchCLI(str(config)).main(args=["todos"])

    assert code == 0
    assert len(created) == 1
    filename, title, due = created[0]
    assert filename.startswith("todo-")
    assert title == "交周报"
    assert due == "2026-09-12"


def test_record_open_id_first_writer_wins(state_dir):
    """先到先得：已有主人后，其他身份不覆盖（单租户加固）。"""
    record_user_open_id(state_dir, "ou_owner")
    record_user_open_id(state_dir, "ou_stranger")
    assert load_user_open_id(state_dir) == "ou_owner"
