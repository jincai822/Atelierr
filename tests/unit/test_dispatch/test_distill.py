"""深加工链路（机器辅助提炼）单元测试（无真实网络）。

LLM 调用 monkeypatch ``scripts.dispatch.distill.httpx.post``；
推送 monkeypatch ``send_dispatch_notice``；候选资格靠
``_seed_probe``（推送 ≥2 次）或回拨 created（沉满 3 天）取得。
"""

from __future__ import annotations

import json
import re

import frontmatter
import pytest

import scripts.dispatch.distill as distill_module
from scripts.dispatch.distill import decide_by_index, pending_drafts, run


def _backdate_created(tree, filename: str, day: str) -> None:
    """把测试笔记 frontmatter 的 created 改为指定日期（YYYY-MM-DD）。"""
    path = tree.notes_dir / filename
    text = path.read_text(encoding="utf-8")
    text = re.sub(
        r"^created: .*$", f"created: '{day}T09:00:00+08:00'", text, count=1, flags=re.M
    )
    path.write_text(text, encoding="utf-8")


def _seed_probe(tree, pushes: dict) -> None:
    """直接铺 response_probe.json：{文件名: 已推送次数}（均已结案）。"""
    from scripts.utils.state_store import write_json

    state = {"pending": {}, "resolved": []}
    for filename, count in pushes.items():
        for _ in range(count):
            state["resolved"].append(
                {"note_id": filename, "filename": filename, "status": "resolved"}
            )
    write_json(tree.state_dir / "response_probe.json", state)


class _DraftLLMResponse:
    """假 httpx 响应：json 返回固定负载。"""

    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


def _draft_payload(**overrides):
    data = {
        "title": "内核稳定",
        "description": "讲情绪稳定的来源与练习方法。",
        "points": ["内核稳定来自对事实的尊重。", "焦虑源于对失控的想象。", "练习从记录情绪开始。"],
        "quotes": ["这是内容"],
    }
    data.update(overrides)
    return {
        "choices": [
            {"message": {"content": json.dumps(data, ensure_ascii=False)}}
        ]
    }




def _fake_bm_write(monkeypatch):
    """P4 测试双身：bm 写入改为按 metadata 直写 tmp 库（不碰真实 vault）。"""

    def _write(rel_path, title, content, *, note_type=None, tags=None, metadata=None, overwrite=True):
        import frontmatter as fm

        for base in _fake_bm_write.bases:
            target = base / rel_path
            if target.parent.exists() or rel_path.startswith("distilled/"):
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(
                    fm.dumps(fm.Post(content, **(metadata or {}))), encoding="utf-8"
                )
                return "atelierr/" + rel_path[:-3]
        raise RuntimeError("no base")

    monkeypatch.setattr("scripts.memory.bm_bridge.write_note", _write)
    return _write


_fake_bm_write.bases = []

@pytest.fixture
def llm_ok(memory_tree, monkeypatch):
    """配好 key + 假 LLM 起草 + 假推送（记录推送文本）。"""
    monkeypatch.setenv("DEEPSEEK_API_KEY", "fake-key")
    monkeypatch.setattr(
        distill_module.httpx,
        "post",
        lambda *a, **k: _DraftLLMResponse(_draft_payload()),
    )
    pushed = []
    monkeypatch.setattr(
        distill_module,
        "send_dispatch_notice",
        lambda title, message: pushed.append(message) or {"feishu": True},
    )
    _fake_bm_write.bases = [memory_tree.notes_dir]
    _fake_bm_write(monkeypatch)
    return pushed


def _settled_note(tree, filename="old.md", content=None, day="2026-09-10"):
    """造一篇沉满 3 天的已确认笔记（无待确认/待办标签）。"""
    note = tree.create_note(
        filename, content or "这是内容。内核稳定来自对事实的尊重。", source="link"
    )
    _backdate_created(tree, filename, day)
    return note


def test_run_drafts_top_candidate(memory_tree, llm_ok):
    """正常路径：取到候选 → 起草落 state → 推送全文 → 当日配额记账。"""
    _settled_note(memory_tree)

    report = run(memory_tree, today="2026-09-18")

    assert report["drafted"] == "old"
    assert report["pushed"] is True
    drafts = pending_drafts(memory_tree)
    assert len(drafts) == 1
    assert drafts[0]["source_stem"] == "old"
    assert drafts[0]["title"] == "内核稳定"
    assert "内核稳定来自对事实的尊重" in llm_ok[0]  # 推送卡带金句
    assert "提 1" in llm_ok[0]


def test_run_quota_one_per_day(memory_tree, llm_ok):
    """每天最多 1 张草稿：同日第二次运行直接配额跳过。"""
    _settled_note(memory_tree)
    run(memory_tree, today="2026-09-18")

    report = run(memory_tree, today="2026-09-18")

    assert report["drafted"] is None
    assert report["skipped"] == ["quota:今日已起草"]
    assert len(pending_drafts(memory_tree)) == 1  # 没有第二张


def test_run_no_candidate(memory_tree, llm_ok):
    """无候选（空库）：no-candidate，不调用 LLM。"""
    report = run(memory_tree, today="2026-09-18")

    assert report["drafted"] is None
    assert report["skipped"] == ["no-candidate"]


def test_run_llm_failure_retries_next_day(memory_tree, monkeypatch):
    """LLM 失败：当日跳过但不记配额日期（次日可重试），不落草稿。"""
    monkeypatch.setenv("DEEPSEEK_API_KEY", "fake-key")

    def _boom(*a, **k):
        raise RuntimeError("network down")

    monkeypatch.setattr(distill_module.httpx, "post", _boom)
    _settled_note(memory_tree)

    report = run(memory_tree, today="2026-09-18")

    assert report["skipped"] == ["llm-failed"]
    assert pending_drafts(memory_tree) == []
    state = distill_module._load_state(memory_tree)
    assert "last_draft_date" not in state  # 不记日期，次日可重试


def test_run_quotes_grounding_drops_fabrication(memory_tree, monkeypatch):
    """LLM 编造的金句被机器回溯校验剔除（原文里找不到）。"""
    monkeypatch.setenv("DEEPSEEK_API_KEY", "fake-key")
    monkeypatch.setattr(
        distill_module.httpx,
        "post",
        lambda *a, **k: _DraftLLMResponse(
            _draft_payload(quotes=["量子波动速读改变命运。", "这是内容。内核稳定来自对事实的尊重。"])
        ),
    )
    monkeypatch.setattr(
        distill_module, "send_dispatch_notice", lambda t, m: {"feishu": True}
    )
    _settled_note(memory_tree)

    run(memory_tree, today="2026-09-18")

    draft = pending_drafts(memory_tree)[0]
    assert draft["quotes"] == ["这是内容。内核稳定来自对事实的尊重。"]


def test_run_skips_pending_and_rejected_stems(memory_tree, llm_ok):
    """已有待批草稿的 stem 不重复起草；弃稿名单里的 stem 不再提名。"""
    _settled_note(memory_tree, "old.md")
    run(memory_tree, today="2026-09-18")
    # 弃掉第一张：old 进入弃稿名单
    ok, _msg = decide_by_index(memory_tree, 1, accept=False)
    assert ok

    report = run(memory_tree, today="2026-09-19")

    assert report["drafted"] is None  # old 已弃，无别的候选
    assert report["skipped"] == ["no-candidate"]


def test_decide_accept_creates_okf_card(memory_tree, llm_ok):
    """「提」：落 OKF 摘录卡（schema 字段齐全）+ index.md/log.md 维护。"""
    _settled_note(memory_tree)
    run(memory_tree, today="2026-09-18")

    ok, msg = decide_by_index(memory_tree, 1, accept=True, actor="human:test")

    assert ok and "已收进压缩层" in msg
    wiki_dir = memory_tree.notes_dir / "distilled"
    cards = list(wiki_dir.glob("内核稳定*.md"))
    assert len(cards) == 1
    post = frontmatter.loads(cards[0].read_text(encoding="utf-8"))
    # OKF 轻量层字段
    assert post["type"] == "Excerpt"
    assert post["title"] == "内核稳定"
    assert post["description"] == "讲情绪稳定的来源与练习方法。"
    assert post["status"] == "stable"
    assert post["generated"]["by"] == "atelierr-distill/1.0"
    assert post["verified"][0]["by"] == "human:test"
    assert post["sources"][0]["resource"] == "old.md"
    # OKF Freshness（2026-09-18 全量采纳）：默认 +180 天到期复查
    assert post["stale_after"]
    # 兼容字段（现有校验与 distilled_stems 机制）
    assert post["from"] == "[[old]]"
    assert post["source"] == "distill"
    assert "## 核心主张" in post.content
    # 批准后来源笔记被视为已提炼（退出候选）
    from scripts.wiki.manager import WikiManager

    assert "old" in WikiManager(memory_tree).distilled_stems()
    # index.md / log.md 已维护
    index_text = (wiki_dir / "index.md").read_text(encoding="utf-8")
    assert 'okf_version: "0.2"' in index_text
    assert "[内核稳定](内核稳定.md) - 讲情绪稳定的来源与练习方法。" in index_text
    log_text = (wiki_dir / "log.md").read_text(encoding="utf-8")
    assert "**Creation**: 新增 [内核稳定](内核稳定.md)" in log_text
    # OKF 主题页：卡被收进 topics/（来源无中图法标签 → 未分类）
    topic_page = wiki_dir / "topics" / "未分类.md"
    assert topic_page.exists()
    assert "[[内核稳定]]" in topic_page.read_text(encoding="utf-8")
    assert "## 主题页" in index_text
    # 草稿出队
    assert pending_drafts(memory_tree) == []


def test_decide_reject_marks_stem_permanently(memory_tree, llm_ok):
    """「弃」：不落卡，来源进弃稿名单，待批出队。"""
    _settled_note(memory_tree)
    run(memory_tree, today="2026-09-18")

    ok, msg = decide_by_index(memory_tree, 1, accept=False)

    assert ok and "已跳过" in msg
    assert not (memory_tree.notes_dir / "wiki").exists() or not list(
        (memory_tree.notes_dir / "wiki").glob("*.md")
    )
    state = distill_module._load_state(memory_tree)
    assert state["rejected_stems"] == ["old"]
    assert pending_drafts(memory_tree) == []


def test_decide_bad_index(memory_tree, llm_ok):
    """序号越界与空队列的报错文案。"""
    ok, msg = decide_by_index(memory_tree, 1, accept=True)
    assert not ok and "没有待审" in msg

    _settled_note(memory_tree)
    run(memory_tree, today="2026-09-18")
    ok, msg = decide_by_index(memory_tree, 9, accept=True)
    assert not ok and "序号取 1..1" in msg


def test_safe_filename_collision_suffix(memory_tree, llm_ok):
    """同名卡不覆盖：第二张自动加 -2 后缀。"""
    wiki_dir = memory_tree.notes_dir / "distilled"
    wiki_dir.mkdir(parents=True, exist_ok=True)
    (wiki_dir / "内核稳定.md").write_text("既有卡", encoding="utf-8")

    name = distill_module._safe_filename("内核稳定", wiki_dir)

    assert name == "内核稳定-2.md"


def test_feishu_ti_command_creates_card(memory_tree, llm_ok, monkeypatch):
    """飞书发「提 1」：落卡 + 回执（经 FeishuBridge 文本分支）。"""
    from scripts.dispatch.feishu import FeishuBridge
    from tests.unit.test_dispatch.test_judgments import _event

    _settled_note(memory_tree)
    run(memory_tree, today="2026-09-18")
    bridge = FeishuBridge(memory_tree, app_id="cli_x", app_secret="secret")
    feedback = []
    monkeypatch.setattr(
        bridge, "_send_feedback", lambda chat_id, text: feedback.append(text)
    )
    event = _event("md-ti", "text", {"text": "提 1"})
    event.event.message.chat_id = "oc_demo"

    bridge.handle_event(event)

    assert feedback and "已收进压缩层" in feedback[0]
    assert list((memory_tree.notes_dir / "distilled").glob("内核稳定*.md"))


def test_digest_shows_draft_count_line(memory_tree, llm_ok):
    """晨报提炼候选节带草稿计数行（无草稿不出现）。"""
    from scripts.dispatch.digest import DigestDispatcher

    _settled_note(memory_tree)
    run(memory_tree, today="2026-09-18")

    report = DigestDispatcher(memory_tree).run(today="2026-09-19")

    assert "✍️ 机器已备好 1 张摘录卡草稿" in report["markdown"]
