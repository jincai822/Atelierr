"""回顾仪式（review_ritual）单元测试：问题由当期数据生成、表单推送、
答案机械落盘（零自动 LLM）。"""

from __future__ import annotations

import os
import time
from datetime import datetime, timedelta

import frontmatter

from scripts.dispatch import review_ritual
from scripts.dispatch.prompt import PromptStore


def test_weekly_questions_from_data(memory_tree, make_note):
    """周回顾问题含本周捕获统计；有滞留/待删时点名为问。"""
    make_note(memory_tree, filename="a.md", content="想法", idle_days=0)
    memory_tree.create_note(
        "old.md", "旧卡\n", source="link", tags=["待确认"]
    )
    old_ns = int((time.time() - 10 * 86400) * 1e9)
    os.utime(memory_tree.notes_dir / "old.md", ns=(old_ns, old_ns))
    # 手动把旧卡的 created 回拨（滞留按 created 判）
    stale = (datetime.now().astimezone() - timedelta(days=10)).isoformat(timespec="seconds")
    path = memory_tree.notes_dir / "old.md"
    post = frontmatter.loads(path.read_text(encoding="utf-8"))
    post.metadata["created"] = stale
    path.write_text(frontmatter.dumps(post), encoding="utf-8")

    questions = review_ritual.build_questions(memory_tree, review_ritual.KIND_WEEKLY)
    intro = review_ritual.build_intro(memory_tree, review_ritual.KIND_WEEKLY)

    # 数据在正文摘要（卡片 markdown），问题是短句（手机可点）
    assert "本周数据" in intro and "捕获" in intro
    assert "滞留待确认超 7 天：1 条" in intro
    assert any("最值得留" in q for q in questions)
    assert any("留还是扔" in q for q in questions)


def test_monthly_questions_are_light(memory_tree):
    """月末轻脉冲：节奏统计 + 两个开放问题，共 3 问。"""
    questions = review_ritual.build_questions(memory_tree, review_ritual.KIND_MONTHLY)
    assert len(questions) == 3
    intro = review_ritual.build_intro(memory_tree, review_ritual.KIND_MONTHLY)
    assert "本月数据" in intro and "捕获" in intro


def test_open_pushes_form_and_registers_session(memory_tree, monkeypatch):
    """open：开会话 + 推 schema 2.0 表单卡；已有会话时跳过不覆盖。"""
    cards = []
    monkeypatch.setattr(
        review_ritual,
        "send_feishu_card",
        lambda card: cards.append(card) or True,
    )

    report = review_ritual.open_ritual(memory_tree, review_ritual.KIND_WEEKLY)

    assert report["opened"] is True
    assert PromptStore(memory_tree.state_dir).is_open()
    assert cards and cards[0]["schema"] == "2.0"
    assert cards[0]["body"]["elements"][1]["tag"] == "form"

    again = review_ritual.open_ritual(memory_tree, review_ritual.KIND_WEEKLY)
    assert again["opened"] is False  # 已有会话不覆盖


def test_write_answers_mechanical_dump(memory_tree):
    """答案原样落盘 reflections/（带问带答）；无答案/重名跳过。"""
    store = PromptStore(memory_tree.state_dir)
    store.open(review_ritual.KIND_WEEKLY, ["问一", "问二"])
    store.append("答一")
    data = store.close()

    path = review_ritual.write_answers(memory_tree, data)

    assert path is not None
    assert path.parent.name == "reflections"
    text = path.read_text(encoding="utf-8")
    assert "## 问：问一" in text
    assert "答一" in text
    post = frontmatter.loads(text)
    assert post.metadata["source"] == "reflection"
    # 幂等：同名不再写
    assert review_ritual.write_answers(memory_tree, data) is None


def test_collect_without_session_noop(memory_tree):
    """无会话 collect 静默。"""
    assert review_ritual.collect_ritual(memory_tree)["collected"] is False


def test_bridge_submit_writes_review_answers(memory_tree, monkeypatch):
    """桥钩子：review-* 会话表单提交后答案自动落盘 reflections/。"""
    from types import SimpleNamespace

    from scripts.dispatch.feishu import FeishuBridge

    bridge = FeishuBridge(memory_tree, app_id="x", app_secret="y")
    monkeypatch.setattr(bridge, "_send_feedback", lambda chat_id, text: None)
    store = PromptStore(memory_tree.state_dir)
    store.open(review_ritual.KIND_WEEKLY, ["本周如何？"])

    event = SimpleNamespace(
        event=SimpleNamespace(
            action=SimpleNamespace(
                value={"action": "prompt_submit"}, form_value={"q1": "挺好"}
            ),
            context=None,
            operator=None,
        )
    )
    resp = bridge.handle_card_action(event)

    assert resp["toast"]["type"] == "success"
    refl = memory_tree.notes_dir / "wiki" / "reflections"
    files = list(refl.glob("*-weekly.md"))
    assert len(files) == 1
    assert "挺好" in files[0].read_text(encoding="utf-8")
