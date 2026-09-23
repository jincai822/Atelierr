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
    assert "1 张旧卡还没确认" in intro
    assert any("最值得留" in q for q in questions)
    assert any("哪些值得留" in q for q in questions)


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
    assert post.metadata["type"] == "Reflection"  # OKF 最小字段（2026-09-23）
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
    wiki = Path(memory_tree.notes_dir) / "distilled"
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


def test_daily_questions_fixed_four(memory_tree):
    """每日四问（2026-09-18 脑科学处方 P0）：睡眠仪表 + 小胜 + 注意力 + 内耗。"""
    questions = review_ritual.build_questions(memory_tree, review_ritual.KIND_DAILY)
    assert len(questions) == 4
    assert any("睡了" in q for q in questions)
    assert any("小事" in q for q in questions)
    assert any("注意力" in q for q in questions)
    assert any("内耗" in q for q in questions)
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
    assert len(report["questions"]) == 4
    assert cards and "今日四问" in str(cards[0]["header"]["title"]["content"])

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
    assert "每日四问" in text  # 标题/标签用每日四问
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
    assert "每日四问" in str(post.metadata["tags"])


# ---------- 盲测小节（2026-09-19 脑科学建议①：先自由回忆后对照） ----------


def _make_recent_note(memory_tree, name="fresh.md", title="健脑新知", days=2):
    """造一条 days 天前入库的普通笔记（盲测候选）。"""
    memory_tree.create_note(name, "正文：保护大脑的三件事。\n", source="link")
    path = memory_tree.notes_dir / name
    post = frontmatter.loads(path.read_text(encoding="utf-8"))
    post.metadata["created"] = (
        datetime.now().astimezone() - timedelta(days=days)
    ).isoformat(timespec="seconds")
    post.metadata["title"] = title
    path.write_text(frontmatter.dumps(post), encoding="utf-8")
    return path


def test_blind_recall_items_selects_recent_only(memory_tree):
    """候选口径：本周新入库入选；超窗/日报/todo/待确认/知识层全部排除。"""
    _make_recent_note(memory_tree, "fresh.md", "健脑新知", days=2)
    _make_recent_note(memory_tree, "old.md", "旧笔记", days=30)
    _make_recent_note(memory_tree, "2026-09-19.md", "日记", days=1)
    _make_recent_note(memory_tree, "todo-2026-x.md", "待办", days=1)
    memory_tree.create_note("pend.md", "未确认\n", source="link", tags=["待确认"])
    wiki_dir = memory_tree.notes_dir / "wiki"
    wiki_dir.mkdir(parents=True, exist_ok=True)
    (wiki_dir / "card.md").write_text(
        "---\ntitle: 知识卡\ncreated: '2026-09-19T10:00:00+08:00'\n---\n\n# 卡\n",
        encoding="utf-8",
    )

    items = review_ritual.blind_recall_items(memory_tree)

    assert [item["rel"] for item in items] == ["fresh.md"]
    assert items[0]["title"] == "健脑新知"


def test_weekly_questions_include_blind(memory_tree):
    """周回顾问题含盲测题（在标准问题之后、上限 6 截断）。"""
    _make_recent_note(memory_tree, "fresh.md", "健脑新知", days=2)

    questions = review_ritual.build_questions(memory_tree, review_ritual.KIND_WEEKLY)

    blind = [q for q in questions if q.startswith("盲测")]
    assert len(blind) == 1
    assert "健脑新知" in blind[0]
    assert "不看笔记" in blind[0]
    assert len(questions) <= 6


def test_open_weekly_stores_blind_payload(memory_tree):
    """开启周回顾：blind 负载随会话存档（答案提交后对照用）。"""
    _make_recent_note(memory_tree, "fresh.md", "健脑新知", days=2)

    report = review_ritual.open_ritual(
        memory_tree, review_ritual.KIND_WEEKLY, send=False
    )

    assert report["opened"] is True
    data = PromptStore(memory_tree.state_dir).load()
    assert data["blind"] == [{"title": "健脑新知", "rel": "fresh.md"}]


def test_blind_comparison_reads_excerpt(memory_tree):
    """对照文本：读原文开头（无 blind 负载返回 None）。"""
    _make_recent_note(memory_tree, "fresh.md", "健脑新知", days=2)
    closed = {"blind": [{"title": "健脑新知", "rel": "fresh.md"}]}

    text = review_ritual.blind_comparison(memory_tree, closed)

    assert "健脑新知" in text
    assert "保护大脑的三件事" in text
    assert review_ritual.blind_comparison(memory_tree, {}) is None


def test_bridge_submit_sends_blind_comparison(memory_tree, monkeypatch):
    """提交答案后：先落盘，随后发盲测原文对照（顺序不可颠倒）。"""
    from types import SimpleNamespace

    from scripts.dispatch.feishu import FeishuBridge

    _make_recent_note(memory_tree, "fresh.md", "健脑新知", days=2)
    bridge = FeishuBridge(memory_tree, app_id="x", app_secret="y")
    sent = []
    monkeypatch.setattr(
        bridge, "_send_feedback", lambda chat_id, text: sent.append(text)
    )
    store = PromptStore(memory_tree.state_dir)
    store.open(review_ritual.KIND_WEEKLY, ["盲测1：「健脑新知」讲了什么？"])
    store.set_extra("blind", [{"title": "健脑新知", "rel": "fresh.md"}])

    event = SimpleNamespace(
        event=SimpleNamespace(
            action=SimpleNamespace(
                value={"action": "prompt_submit"}, form_value={"q1": "讲护脑的"}
            ),
            context=None,
            operator=None,
        )
    )
    resp = bridge.handle_card_action(event)

    assert resp["toast"]["type"] == "success"
    comparison = [t for t in sent if "盲测对照" in t]
    assert len(comparison) == 1
    assert "保护大脑的三件事" in comparison[0]


# ---------- 费曼讲稿（2026-09-19 脑科学建议②：能讲明白才是真懂） ----------


def _make_wiki_card(memory_tree, rel, title, days=5, body="# 概念\n自注意力让词互相看。"):
    """造一张 days 天前的 wiki 卡（rel 相对 memory/ 根）。"""
    path = memory_tree.notes_dir / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    created = (
        datetime.now().astimezone() - timedelta(days=days)
    ).isoformat(timespec="seconds")
    path.write_text(
        f"---\ntitle: {title}\ncreated: '{created}'\ntype: Excerpt\n---\n\n{body}\n",
        encoding="utf-8",
    )
    return path


def test_feynman_candidates_wiki_recent_only(memory_tree):
    """候选口径：当月 wiki 根层卡入选；超窗/cognition/reflections 排除。"""
    _make_wiki_card(memory_tree, "wiki/新卡.md", "自注意力", days=5)
    _make_wiki_card(memory_tree, "wiki/旧卡.md", "旧概念", days=60)
    _make_wiki_card(memory_tree, "wiki/cognition/判断.md", "一条判断", days=5)
    _make_wiki_card(memory_tree, "wiki/reflections/周报.md", "本周回顾", days=5)

    items = review_ritual.feynman_candidates(memory_tree)

    assert [item["rel"] for item in items] == ["wiki/新卡.md"]
    assert items[0]["title"] == "自注意力"
    assert "自注意力让词互相看" in items[0]["body"]


def test_feynman_brief_template_fallback(memory_tree, monkeypatch):
    """无 API key：退回纯模板骨架（含三空），绝不阻塞。"""
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    _make_wiki_card(memory_tree, "wiki/新卡.md", "自注意力", days=5)

    brief = review_ritual.feynman_brief(memory_tree)

    assert "费曼讲稿" in brief
    assert "自注意力" in brief
    assert "① 核心概念" in brief and "② 类比" in brief and "③ 应用" in brief


def test_feynman_brief_llm_drafted(memory_tree, monkeypatch):
    """有 key：LLM 起草（mock httpx）；LLM 异常自动回模板。"""
    _make_wiki_card(memory_tree, "wiki/新卡.md", "自注意力", days=5)
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-test")

    class _Resp:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "choices": [
                    {"message": {"content": "• 「自注意力」\n  ① 核心概念：词互相看\n  ② 类比：饭局\n  ③ 应用：聊天"}}
                ]
            }

    import scripts.dispatch.review_ritual as ritual_module

    monkeypatch.setattr(ritual_module, "feynman_candidates", lambda *a, **k: [
        {"title": "自注意力", "rel": "wiki/新卡.md", "body": "x"}
    ])
    import httpx as _httpx

    monkeypatch.setattr(_httpx, "post", lambda *a, **k: _Resp())
    brief = review_ritual.feynman_brief(memory_tree)
    assert "饭局" in brief

    def _boom(*a, **k):
        raise RuntimeError("api down")

    monkeypatch.setattr(_httpx, "post", _boom)
    brief = review_ritual.feynman_brief(memory_tree)
    assert "① 核心概念" in brief  # 模板兜底


def test_feynman_brief_none_without_candidates(memory_tree):
    """当月无新卡：返回 None（不推空稿）。"""
    assert review_ritual.feynman_brief(memory_tree) is None
