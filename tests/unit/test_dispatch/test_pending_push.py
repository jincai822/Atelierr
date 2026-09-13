"""确认卡分级（pending_push）单元测试。

裁决（2026-09-13）：有评论/备注的捕获即时单推；无评论的入队攒晚间
「今日待确认清单」一张卡批量处理。
"""

from __future__ import annotations

from scripts.dispatch import pending_push


def _note(tree, rel="x.md", tags=("待确认", "抖音")):
    return tree.create_note(rel, "正文\n", source="link", tags=list(tags))


def test_enqueue_idempotent(memory_tree):
    """同一笔记重复入队只占一格。"""
    pending_push.enqueue(memory_tree.state_dir, "a.md")
    pending_push.enqueue(memory_tree.state_dir, "a.md")
    pending_push.enqueue(memory_tree.state_dir, "b.md", kind="clip")

    items = pending_push._load(memory_tree.state_dir)
    assert [item["file"] for item in items] == ["a.md", "b.md"]
    assert items[1]["kind"] == "clip"


def test_flush_empty_queue_silent(memory_tree):
    """空队列：不推卡。"""
    sent = []
    report = pending_push.flush(memory_tree, send_card=sent.append)

    assert report == {"queued": 0, "pending": 0, "resolved": 0, "sent": False}
    assert sent == []


def test_flush_sends_only_still_pending(memory_tree):
    """只推仍带「待确认」的；已确认/已删除的出队不上卡。"""
    _note(memory_tree, "keep.md")
    _note(memory_tree, "confirmed.md", tags=("抖音",))  # 已无待确认
    for rel in ("keep.md", "confirmed.md", "deleted.md"):
        pending_push.enqueue(memory_tree.state_dir, rel)

    sent = []
    report = pending_push.flush(memory_tree, send_card=lambda names: sent.append(names) or True)

    assert sent == [["keep.md"]]
    assert report["pending"] == 1
    assert report["resolved"] == 2
    assert report["sent"] is True
    # 成功推送后整队出清（含已解决条目）
    assert pending_push._load(memory_tree.state_dir) == []


def test_flush_send_failure_keeps_queue(memory_tree):
    """推送失败：整队保留，下轮再试。"""
    _note(memory_tree, "x.md")
    pending_push.enqueue(memory_tree.state_dir, "x.md")

    report = pending_push.flush(memory_tree, send_card=lambda names: False)

    assert report["sent"] is False
    assert [item["file"] for item in pending_push._load(memory_tree.state_dir)] == ["x.md"]


def test_flush_send_exception_keeps_queue(memory_tree):
    """推送抛异常同样留队（不中断班次）。"""

    def _boom(names):
        raise RuntimeError("feishu down")

    _note(memory_tree, "x.md")
    pending_push.enqueue(memory_tree.state_dir, "x.md")

    report = pending_push.flush(memory_tree, send_card=_boom)

    assert report["sent"] is False
    assert len(pending_push._load(memory_tree.state_dir)) == 1


def test_pending_digest_card_shape(memory_tree, monkeypatch):
    """清单卡：每条一节 + 「✅ 确认并归档」callback 按钮（archive_note）。"""
    from scripts.dispatch import feishu_cards

    cards = []
    monkeypatch.setattr(
        feishu_cards, "send_feishu_card", lambda card, chat_id=None: cards.append(card) or True
    )

    ok = feishu_cards.send_pending_digest_feishu(["抖音-a.md", "clip-b.md"])

    assert ok is True
    card = cards[0]
    assert "2 条" in card["header"]["title"]["content"]
    buttons = [
        action
        for el in card["elements"]
        if el["tag"] == "action"
        for action in el["actions"]
    ]
    callbacks = [b for b in buttons if "behaviors" in b]
    # 每条两个回调按钮：✅ 确认并归档 + 🗑 不要了（「打开细看」是 URI 按钮）
    assert len(callbacks) == 4
    assert callbacks[0]["behaviors"][0]["value"] == {
        "action": "archive_note",
        "note": "抖音-a.md",
    }
    assert callbacks[1]["behaviors"][0]["value"] == {
        "action": "discard_note",
        "note": "抖音-a.md",
    }
    texts = [
        el["text"]["content"]
        for el in card["elements"]
        if el["tag"] == "div"
    ]
    assert any("抖音-a" in text for text in texts)


def test_pending_digest_empty_list_no_send():
    """空清单不推。"""
    from scripts.dispatch import feishu_cards

    assert feishu_cards.send_pending_digest_feishu([]) is False
