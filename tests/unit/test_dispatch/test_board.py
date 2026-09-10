"""知识库看板（多维表格同步）单元测试（lark SDK 全部打桩，无真实网络）。"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import scripts.dispatch.board as board_module
import scripts.dispatch.task_sync as task_sync_module
from scripts.dispatch.board import BoardSync, _chunks, _to_ms


def _fake_lark(monkeypatch, client):
    """换假 lark：board 模块自身与 task_sync._client 的引用都要换。"""
    fake_lark = MagicMock()
    fake_lark.Client.builder.return_value.app_id.return_value.app_secret.return_value.build.return_value = (
        client
    )
    monkeypatch.setattr(board_module, "_import_lark", lambda: fake_lark)
    monkeypatch.setattr(task_sync_module, "_import_lark", lambda: fake_lark)
    return fake_lark


def _creds(monkeypatch):
    monkeypatch.setenv("FEISHU_APP_ID", "cli_x")
    monkeypatch.setenv("FEISHU_APP_SECRET", "secret")
    monkeypatch.setenv("FEISHU_USER_ID", "ou_me")


def _client_ok(created_ids):
    """构造一个全链路成功的假 client。"""
    client = MagicMock()
    client.bitable.v1.app.create.return_value.success.return_value = True
    client.bitable.v1.app.create.return_value.data.app.app_token = "app-1"
    client.drive.v1.permission_member.create.return_value.success.return_value = True
    client.bitable.v1.app_table.create.return_value.success.return_value = True
    client.bitable.v1.app_table.create.return_value.data.table_id = "tbl-1"
    batch = client.bitable.v1.app_table_record.batch_create
    batch.return_value.success.return_value = True
    batch.return_value.data.records = [
        SimpleNamespace(record_id=rid) for rid in created_ids
    ]
    client.bitable.v1.app_table_record.batch_update.return_value.success.return_value = True
    return client


def test_sync_first_run_creates_everything(memory_tree, monkeypatch):
    """首次同步：建应用 → 共享 → 建表 → 批量新增；报告与状态登记正确。"""
    _creds(monkeypatch)
    memory_tree.create_note("a.md", "# 笔记A\n\n内容\n", tags=["想法"])
    memory_tree.create_note("b.md", "# 笔记B\n\n内容\n", tags=["待办"])
    client = _client_ok(["rec-a", "rec-b"])
    _fake_lark(monkeypatch, client)

    report = BoardSync(memory_tree).sync()

    assert report is not None
    assert report["created"] == 2 and report["updated"] == 0
    assert report["total"] == 2
    assert report["url"] == "https://feishu.cn/base/app-1"
    client.drive.v1.permission_member.create.assert_called_once()
    state = BoardSync(memory_tree)._load_state()
    assert state["app_token"] == "app-1" and state["table_id"] == "tbl-1"
    assert state["records"] == {"a.md": "rec-a", "b.md": "rec-b"}


def test_sync_second_run_updates_only(memory_tree, monkeypatch):
    """二次同步：已有记录走 batch_update，不重建应用/表。"""
    _creds(monkeypatch)
    memory_tree.create_note("a.md", "# 笔记A\n\n内容\n")
    client = _client_ok(["rec-a"])
    _fake_lark(monkeypatch, client)
    assert BoardSync(memory_tree).sync()["created"] == 1

    report = BoardSync(memory_tree).sync()

    assert report["created"] == 0 and report["updated"] == 1
    client.bitable.v1.app.create.assert_called_once()  # 没再建
    client.bitable.v1.app_table_record.batch_update.assert_called_once()


def test_sync_new_note_after_first_run(memory_tree, monkeypatch):
    """增量：第二次多出一条新笔记 → 只新增那一条。"""
    _creds(monkeypatch)
    memory_tree.create_note("a.md", "# A\n")
    client = _client_ok(["rec-a"])
    _fake_lark(monkeypatch, client)
    BoardSync(memory_tree).sync()

    memory_tree.create_note("b.md", "# B\n")
    client.bitable.v1.app_table_record.batch_create.return_value.data.records = [
        SimpleNamespace(record_id="rec-b")
    ]
    report = BoardSync(memory_tree).sync()

    assert report["created"] == 1 and report["updated"] == 1
    state = BoardSync(memory_tree)._load_state()
    assert state["records"]["b.md"] == "rec-b"


def test_sync_missing_creds(memory_tree, monkeypatch):
    """凭证缺失：返回 None（绝不抛异常）。"""
    monkeypatch.delenv("FEISHU_APP_ID", raising=False)
    monkeypatch.delenv("FEISHU_APP_SECRET", raising=False)
    _fake_lark(monkeypatch, MagicMock())

    assert BoardSync(memory_tree).sync() is None


def test_sync_app_create_failure(memory_tree, monkeypatch):
    """建应用失败（权限未开）：返回 None 且不写状态。"""
    _creds(monkeypatch)
    client = _client_ok([])
    client.bitable.v1.app.create.return_value.success.return_value = False
    _fake_lark(monkeypatch, client)

    assert BoardSync(memory_tree).sync() is None
    assert BoardSync(memory_tree)._load_state() == {}


def test_collect_rows_skips_pending_delete_and_trash(memory_tree, monkeypatch):
    """行收集：跳过 pending_delete 与 trash/ 路径；字段映射正确。"""
    memory_tree.create_note(
        "keep.md",
        "---\ntitle: 留下\ntags: [想法, B84-心理学]\n---\n正文\n",
    )
    memory_tree.create_note("doomed.md", "# 待删\n")
    index = memory_tree._load_index()
    for entry in index.values():
        if entry["path"] == "doomed.md":
            entry["pending_delete"] = True
    memory_tree._save_index()

    rows = BoardSync(memory_tree)._collect_rows()

    assert [row["路径"] for row in rows] == ["keep.md"]
    row = rows[0]
    assert row["标题"] == "留下"
    assert row["目录"] == "（根）"
    assert row["标签"] == "想法, B84-心理学"
    assert row["层级"] == "short-term"
    assert row["confidence"] == 1.0
    assert isinstance(row["创建"], int)


def test_to_ms_and_chunks():
    """工具函数：日期转毫秒 / 分批。"""
    from datetime import datetime

    assert _to_ms(None) is None
    assert _to_ms(datetime(2026, 9, 1)) > 0
    assert _to_ms("2026-09-01T08:00:00") > 0
    assert _to_ms("垃圾") is None
    assert _chunks([], 2) == []
    assert _chunks([1, 2, 3, 4, 5], 2) == [[1, 2], [3, 4], [5]]


def test_cli_board_command(memory_tree, tmp_path, monkeypatch, capsys):
    """dispatch_cli board：成功打印报告与地址；失败打印原因。"""
    from scripts.cli.dispatch_cli import DispatchCLI

    config = tmp_path / "memory.yaml"
    config.write_text(
        f"memory:\n  root: {memory_tree.notes_dir}\n"
        f"  state_dir: {memory_tree.state_dir}\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "scripts.dispatch.board.sync_board",
        lambda tree: {"created": 1, "updated": 2, "total": 3, "url": "https://x"},
    )
    assert DispatchCLI(str(config)).main(args=["board"]) == 0
    out = capsys.readouterr().out
    assert "新增 1" in out and "https://x" in out

    monkeypatch.setattr("scripts.dispatch.board.sync_board", lambda tree: None)
    assert DispatchCLI(str(config)).main(args=["board"]) == 0
    assert "失败" in capsys.readouterr().out


def test_menu_board_command(memory_tree, monkeypatch):
    """飞书「同步看板」菜单指令：触发同步并反馈计数。"""
    from scripts.dispatch.feishu import FeishuBridge

    bridge = FeishuBridge(memory_tree, app_id="cli_x", app_secret="secret")
    sent = []
    monkeypatch.setattr(
        bridge, "_send_feedback", lambda chat, text: sent.append(text)
    )
    monkeypatch.setattr(
        "scripts.dispatch.board.sync_board",
        lambda tree: {"created": 0, "updated": 5, "total": 5, "url": "https://x"},
    )
    event = SimpleNamespace(
        event=SimpleNamespace(
            message=SimpleNamespace(
                message_id="m-board",
                message_type="text",
                content='{"text": "同步看板"}',
            )
        )
    )
    bridge.handle_event(event)

    assert sent and "共 5 条" in sent[-1] and "https://x" in sent[-1]
EOF_MARKER_NOT_USED = None


def test_sync_reshares_when_identity_appears(memory_tree, monkeypatch):
    """建看板时没认出你（未共享）；后来认出 → 下次同步自动补共享。"""
    _creds(monkeypatch)
    monkeypatch.delenv("FEISHU_USER_ID", raising=False)
    memory_tree.create_note("a.md", "# A\n")
    client = _client_ok(["rec-a"])
    _fake_lark(monkeypatch, client)

    assert BoardSync(memory_tree).sync()["created"] == 1
    client.drive.v1.permission_member.create.assert_not_called()
    assert BoardSync(memory_tree)._load_state()["shared"] is False

    monkeypatch.setenv("FEISHU_USER_ID", "ou_me")
    assert BoardSync(memory_tree).sync() is not None
    client.drive.v1.permission_member.create.assert_called_once()
    assert BoardSync(memory_tree)._load_state()["shared"] is True
