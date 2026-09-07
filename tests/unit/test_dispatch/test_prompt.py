"""飞书交互式问答（pending prompt）单元测试（无真实网络）。

状态机本身 + 桥接线（open 期间文本算回答不捕获、关闭词结束、
关闭后恢复捕获）均为真实代码路径；飞书发送一律打桩。
"""

from __future__ import annotations

import pytest

from scripts.dispatch.prompt import PromptStore


def test_open_append_close(memory_tree):
    """open → append 两条 → close：状态完整，答案有序。"""
    store = PromptStore(memory_tree.state_dir)
    assert store.is_open() is False
    assert store.append("无主会话") == 0  # 无会话不写盘

    store.open("weekly", ["问题一", "问题二"])
    assert store.is_open() is True
    assert store.append("回答一") == 1
    assert store.append("回答二") == 2

    data = store.close()
    assert data["status"] == "closed"
    assert data["kind"] == "weekly"
    assert [a["text"] for a in data["answers"]] == ["回答一", "回答二"]
    assert store.is_open() is False


def test_corrupt_state_treated_as_no_session(memory_tree):
    """状态文件损坏按无会话处理（不抛异常）。"""
    memory_tree.state_dir.mkdir(parents=True, exist_ok=True)
    (memory_tree.state_dir / "pending_prompt.json").write_text(
        "{broken", encoding="utf-8"
    )
    store = PromptStore(memory_tree.state_dir)
    assert store.is_open() is False
    assert store.load() is None
    assert store.close() is None


def _bridge_with_feedback(memory_tree, monkeypatch):
    """构造桥 + 拦截回执发送，返回 (bridge, 回执记录)。"""
    from scripts.dispatch.feishu import FeishuBridge

    bridge = FeishuBridge(memory_tree, app_id="cli_x", app_secret="secret")
    sent = []
    monkeypatch.setattr(
        bridge, "_send_feedback", lambda chat_id, text: sent.append(text)
    )
    return bridge, sent


def test_open_session_routes_text_to_answers(memory_tree, monkeypatch):
    """会话 open 期间：文本计入答案、有回执、不建笔记。"""
    bridge, sent = _bridge_with_feedback(memory_tree, monkeypatch)
    PromptStore(memory_tree.state_dir).open("weekly", ["问题"])

    result = bridge._receive_text("msg-1", "这周睡眠不错")

    assert result is None
    assert sent == ["已收到（第 1 条回答）"]
    assert not list(memory_tree.notes_dir.glob("feishu-*.md"))
    data = PromptStore(memory_tree.state_dir).load()
    assert data["answers"][0]["text"] == "这周睡眠不错"


def test_close_word_ends_session(memory_tree, monkeypatch):
    """回「跳过」：会话关闭、有回执、之后恢复捕获为笔记。"""
    bridge, sent = _bridge_with_feedback(memory_tree, monkeypatch)
    store = PromptStore(memory_tree.state_dir)
    store.open("weekly", ["问题"])

    bridge._receive_text("msg-1", "跳过")
    assert store.is_open() is False
    assert "结束" in sent[-1]

    note = bridge._receive_text("msg-2", "普通消息")
    assert note is not None and note.exists()


def test_closed_session_captures_normally(memory_tree, monkeypatch):
    """无会话：文本照常捕获为 feishu- 笔记，无回执。"""
    bridge, sent = _bridge_with_feedback(memory_tree, monkeypatch)

    note = bridge._receive_text("msg-1", "随便一条")

    assert note is not None and note.exists()
    assert sent == []


@pytest.fixture
def cli(memory_tree, tmp_path):
    """指向临时库的 DispatchCLI。"""
    from scripts.cli.dispatch_cli import DispatchCLI

    config = tmp_path / "memory.yaml"
    config.write_text(
        f"memory:\n  root: {memory_tree.notes_dir}\n"
        f"  state_dir: {memory_tree.state_dir}\n",
        encoding="utf-8",
    )
    return DispatchCLI(config_path=str(config))


def test_cli_prompt_open_no_send_and_collect(cli, memory_tree):
    """prompt-open --no-send 只登记不推送；prompt-collect 输出并关闭。"""
    assert cli.main(["prompt-open", "weekly", "问题一", "--no-send"]) == 0
    assert PromptStore(memory_tree.state_dir).is_open() is True

    PromptStore(memory_tree.state_dir).append("回答一")
    assert cli.main(["prompt-collect"]) == 0
    assert PromptStore(memory_tree.state_dir).is_open() is False
