"""回顾仪式（review_ritual）单元测试：问题由当期数据生成、表单推送、
答案机械落盘（零自动 LLM）。"""

from __future__ import annotations

import os
import time
from datetime import datetime, timedelta
from pathlib import Path

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


def test_write_answers_appends_new_answers(memory_tree):
    """当天文件已存在：新答案追加（分次作答不丢）；完全相同的答案不重复落。"""
    store = PromptStore(memory_tree.state_dir)
    store.open(review_ritual.KIND_WEEKLY, ["问一", "问二"])
    store.append("答一")
    data = store.close()
    first = review_ritual.write_answers(memory_tree, data)
    assert first is not None

    # 完全相同的内容：幂等跳过
    assert review_ritual.write_answers(memory_tree, data) is None

    store.open(review_ritual.KIND_WEEKLY, ["问一", "问二"])
    store.append("答一")
    store.append("答二（后补）")
    data2 = store.close()
    second = review_ritual.write_answers(memory_tree, data2)
    assert second is not None
    text = second.read_text(encoding="utf-8")
    assert text.count("答一") == 1  # 不重复落
    assert "答二（后补）" in text


def test_weekly_intro_names_new_excerpt_cards(memory_tree):
    """周回顾摘要点名本期新勾摘录卡（KM 评审 P1① 防收藏谬误）；老卡不出现。"""
    wiki = Path(memory_tree.notes_dir) / "wiki"
    wiki.mkdir()
    now_iso = datetime.now().astimezone().isoformat(timespec="seconds")
    old_iso = (datetime.now().astimezone() - timedelta(days=30)).isoformat(timespec="seconds")
    (wiki / "摘录-概念甲-abc123.md").write_text(
        frontmatter.dumps(frontmatter.Post("正文\n", title="概念甲", created=now_iso)),
        encoding="utf-8",
    )
    (wiki / "摘录-老卡-def456.md").write_text(
        frontmatter.dumps(frontmatter.Post("正文\n", title="老卡", created=old_iso)),
        encoding="utf-8",
    )

    intro = review_ritual.build_intro(memory_tree, review_ritual.KIND_WEEKLY)

    assert "新勾摘录卡 1 张" in intro
    assert "概念甲" in intro
    assert "老卡" not in intro


def _rewind_asked_at(state_dir, days: int = 2) -> None:
    """把 open 会话的 asked_at 回拨（模拟前一天没答的残留会话）。"""
    from scripts.utils.state_store import read_json, write_json

    path = Path(state_dir) / "pending_prompt.json"
    data = read_json(path, None)
    data["asked_at"] = (
        datetime.now().astimezone() - timedelta(days=days)
    ).isoformat()
    write_json(path, data, indent=2)


def _daily_state(state_dir):
    from scripts.utils.state_store import read_json

    return read_json(Path(state_dir) / "review_daily.json", None)


def test_daily_questions_fixed_three(memory_tree):
    """每日三问：固定 3 个短问，含内耗留痕（周回顾下周动作的落地）。"""
    questions = review_ritual.build_questions(memory_tree, review_ritual.KIND_DAILY)
    assert len(questions) == 3
    assert any("内耗" in q for q in questions)
    assert any("状态" in q for q in questions)
    intro = review_ritual.build_intro(memory_tree, review_ritual.KIND_DAILY)
    assert "今天捕获" in intro
    assert "判断：xxx" in intro
    assert "连续 3 天" in intro  # 暂停规则说在明处


def test_daily_open_pushes_form_and_idempotent(memory_tree, monkeypatch):
    """每日三问：开会话 + 推表单卡；当天重复触发幂等跳过。"""
    cards = []
    monkeypatch.setattr(
        review_ritual, "send_feishu_card", lambda card: cards.append(card) or True
    )
    report = review_ritual.open_ritual(memory_tree, review_ritual.KIND_DAILY)
    assert report["opened"] is True
    assert len(report["questions"]) == 3
    assert cards and "今日三问" in str(cards[0]["header"]["title"]["content"])

    again = review_ritual.open_ritual(memory_tree, review_ritual.KIND_DAILY)
    assert again["opened"] is False
    assert len(cards) == 1  # 当天不重复推


def test_daily_stale_unanswered_bumps_streak(memory_tree, monkeypatch):
    """前一天的三问没答：新开时收尸，记一天未答（无答不落盘）。"""
    monkeypatch.setattr(review_ritual, "send_feishu_card", lambda card: True)
    review_ritual.open_ritual(memory_tree, review_ritual.KIND_DAILY)
    _rewind_asked_at(memory_tree.state_dir)

    report = review_ritual.open_ritual(memory_tree, review_ritual.KIND_DAILY)

    assert report["opened"] is True  # 新的一天照开
    state = _daily_state(memory_tree.state_dir)
    assert state["unanswered_streak"] == 1
    assert state["paused"] is False
    # 无答案：reflections 不落任何文件
    refl = Path(memory_tree.notes_dir) / "wiki" / "reflections"
    assert not refl.exists() or not list(refl.glob("*-reflection.md"))


def test_daily_stale_with_answers_filed_and_resets(memory_tree, monkeypatch):
    """前一天的三问有答：收尸时答案照落盘（日期归昨天），连续未答清零。"""
    monkeypatch.setattr(review_ritual, "send_feishu_card", lambda card: True)
    store = PromptStore(memory_tree.state_dir)
    review_ritual.open_ritual(memory_tree, review_ritual.KIND_DAILY)
    store.append("累但充实")
    _rewind_asked_at(memory_tree.state_dir)
    # 人为造一点未答计数，验证落盘后清零
    review_ritual._bump_daily_unanswered(memory_tree)

    report = review_ritual.open_ritual(memory_tree, review_ritual.KIND_DAILY)

    assert report["opened"] is True
    refl = Path(memory_tree.notes_dir) / "wiki" / "reflections"
    files = list(refl.glob("*-reflection.md"))
    assert len(files) == 1
    text = files[0].read_text(encoding="utf-8")
    assert "累但充实" in text
    assert "每日三问" in text  # 标题/标签用每日三问
    state = _daily_state(memory_tree.state_dir)
    assert state["unanswered_streak"] == 0
    assert state["paused"] is False


def test_daily_pause_after_three_and_manual_resume(memory_tree, monkeypatch):
    """连续 3 天未答自动暂停（不再推卡）；unpause_daily 后恢复。"""
    cards = []
    monkeypatch.setattr(
        review_ritual, "send_feishu_card", lambda card: cards.append(card) or True
    )
    for _day in range(3):  # 模拟三天：开 → 回拨 → 次日再开（收尸记未答）
        review_ritual.open_ritual(memory_tree, review_ritual.KIND_DAILY)
        _rewind_asked_at(memory_tree.state_dir)

    report = review_ritual.open_ritual(memory_tree, review_ritual.KIND_DAILY)

    assert report["opened"] is False
    assert report["paused"] is True
    state = _daily_state(memory_tree.state_dir)
    assert state["unanswered_streak"] == 3
    assert state["paused"] is True

    review_ritual.unpause_daily(memory_tree)  # 飞书回「复盘」的效果
    resumed = review_ritual.open_ritual(memory_tree, review_ritual.KIND_DAILY)
    assert resumed["opened"] is True
    assert _daily_state(memory_tree.state_dir)["paused"] is False


def test_daily_yields_to_weekly_session(memory_tree, monkeypatch):
    """周/月回顾会话在跑：每日三问让位，不打扰也不计未答。"""
    monkeypatch.setattr(review_ritual, "send_feishu_card", lambda card: True)
    review_ritual.open_ritual(memory_tree, review_ritual.KIND_WEEKLY)
    _rewind_asked_at(memory_tree.state_dir)  # 就算周回顾挂了很久

    report = review_ritual.open_ritual(memory_tree, review_ritual.KIND_DAILY)

    assert report["opened"] is False
    assert "paused" not in report
    assert _daily_state(memory_tree.state_dir) is None  # 未答不计
    # 周回顾会话原样还在
    assert PromptStore(memory_tree.state_dir).is_open()


def test_daily_answers_file_matches_atelier_glob(memory_tree):
    """每日三问落盘文件名 <日期>-reflection.md——对齐 Atelier /weekly
    的缺日检测 glob（`<date>-reflection*.md`），车间周报认得出日报。"""
    store = PromptStore(memory_tree.state_dir)
    store.open(review_ritual.KIND_DAILY, ["问一"])
    store.append("答一")
    data = store.close()

    path = review_ritual.write_answers(memory_tree, data)

    assert path is not None
    assert path.name.endswith("-reflection.md")
    post = frontmatter.loads(path.read_text(encoding="utf-8"))
    assert post.metadata["source"] == "reflection"
    assert "每日三问" in str(post.metadata["tags"])
