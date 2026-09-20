"""网页剪藏确认卡单元测试（无真实网络与 LLM）。

LinkProcessor 以 summarizer_factory 注入假实现；飞书推送以 notify
注入记录器。扫描、幂等、重复检测、降级均为真实代码路径。
"""

from __future__ import annotations

import json

import frontmatter
import pytest

import scripts.cli.dispatch_cli as cli_module
import scripts.dispatch.clips as clips_module
from scripts.dispatch import pending_push
from scripts.dispatch.clips import ClipDispatcher
from scripts.processors.link import _SUMMARIZE_CLIP_PROMPT

URL_A = "https://example.com/article-a"
URL_B = "https://example.com/article-b"


class _FakeSummarizer:
    """假摘要器：记录调用，返回固定 v4 摘要。"""

    calls = []
    fail = False

    def __init__(self):
        self.llm_max_chars = 6000

    def _summarize(self, text, prompt=None):
        type(self).calls.append({"text": text, "prompt": prompt})
        if type(self).fail:
            return None, "failed:Boom"
        return {
            "summary": "核心论点摘要。",
            "points": ["甲一", "乙二", "丙三", "丁四"],
            "insights": [],
            "entities": [],
            "category": "B84-心理学",
            "topics": ["习惯"],
        }, "ok"


class _Notify:
    """假推送：记录 (title, message, confirm_note)。"""

    def __init__(self):
        self.calls = []

    def __call__(self, title, message, confirm_note=None, **_kwargs):
        self.calls.append(
            {"title": title, "message": message, "confirm_note": confirm_note}
        )
        return {"ntfy": False, "feishu": True}


@pytest.fixture(autouse=True)
def _reset_fake():
    """每个用例重置假摘要器的调用记录与失败开关。"""
    _FakeSummarizer.calls = []
    _FakeSummarizer.fail = False
    yield


def _clip(
    tree,
    name="clip-a.md",
    url=URL_A,
    title="文章A",
    tags=("剪藏", "待确认"),
    created="2026-09-10 10:00:00+08:00",
    body="正文内容",
    note="",
):
    """造一篇 webclip 笔记（frontmatter 与 Obsidian 剪藏模板同构）。"""
    note_line = f"备注: {note}\n" if note else ""
    content = (
        "---\n"
        f"created: {created}\n"
        f"title: {title}\n"
        "source: webclip\n"
        f"tags: {json.dumps(list(tags), ensure_ascii=False)}\n"
        f"url: {url}\n"
        f"{note_line}"
        "---\n\n"
        f"{body}\n"
    )
    return tree.create_note(name, content)


def _dispatcher(tree, notify=None):
    return ClipDispatcher(
        tree,
        summarizer_factory=_FakeSummarizer,
        notify=notify if notify is not None else _Notify(),
    )


def _load_state(tree):
    return json.loads((tree.state_dir / "clip_cards.json").read_text())


def test_new_clip_gets_card(memory_tree):
    """新剪藏（带备注）→ 带确认按钮的卡片（含摘要与至多 3 条要点），状态登记。"""
    notify = _Notify()
    _clip(memory_tree, note="对工作有用")

    report = _dispatcher(memory_tree, notify).run()

    assert report["new"] == 1
    assert report["cards"] == ["clip-a.md"]
    assert len(notify.calls) == 1
    call = notify.calls[0]
    assert call["title"] == "Atelierr 剪藏待确认"
    assert call["confirm_note"] == "clip-a.md"
    assert "《文章A》已剪藏入库" in call["message"]
    assert "核心论点摘要。" in call["message"]
    assert "1. 甲一" in call["message"]
    assert "3. 丙三" in call["message"]
    assert "4. 丁四" not in call["message"]  # 卡片至多 3 条要点
    assert "建议归档" not in call["message"]  # tags 无中图法 → 领域推不出，省略
    # LLM 用网页剪藏提示词（与链接同一管道、同一中图法标准）
    assert _FakeSummarizer.calls[0]["prompt"] == _SUMMARIZE_CLIP_PROMPT
    assert "网页文章" in _FakeSummarizer.calls[0]["prompt"]
    state = _load_state(memory_tree)
    assert len(state) == 1
    entry = next(iter(state.values()))
    assert entry["path"] == "clip-a.md"
    assert entry["url"] == URL_A
    assert entry["summary_status"] == "ok"


def test_idempotent_second_run(memory_tree):
    """第二轮：不重复推卡、不重复调 LLM。"""
    notify = _Notify()
    _clip(memory_tree, note="有用")
    dispatcher = _dispatcher(memory_tree, notify)
    dispatcher.run()

    report = dispatcher.run()

    assert report["new"] == 0
    assert report["cards"] == []
    assert len(notify.calls) == 1
    assert len(_FakeSummarizer.calls) == 1


def test_non_webclip_ignored(memory_tree):
    """非 webclip 来源的待确认笔记不处理。"""
    notify = _Notify()
    memory_tree.create_note("plain.md", "普通笔记", source="test", tags=["待确认"])

    report = _dispatcher(memory_tree, notify).run()

    assert report["new"] == 0
    assert notify.calls == []
    assert _FakeSummarizer.calls == []


def test_clip_without_review_tag_ignored(memory_tree):
    """无「待确认」标签的剪藏（已确认）不推卡、不摘要。"""
    notify = _Notify()
    _clip(memory_tree, tags=("剪藏",))

    report = _dispatcher(memory_tree, notify).run()

    assert report["new"] == 0
    assert notify.calls == []
    assert _FakeSummarizer.calls == []


def test_pending_delete_clip_ignored(memory_tree):
    """pending_delete 的剪藏不处理。"""
    notify = _Notify()
    path = _clip(memory_tree)
    entry = memory_tree._entry(path)
    entry["pending_delete"] = True
    memory_tree._save_index()

    report = _dispatcher(memory_tree, notify).run()

    assert report["new"] == 0
    assert notify.calls == []


def test_duplicate_url_marks_pending_delete(memory_tree):
    """同 url 剪两次：较新的标 pending_delete + 无按钮信息卡，不做摘要。"""
    notify = _Notify()
    _clip(memory_tree, name="clip-a.md", created="2026-09-09 10:00:00+08:00", note="有用")
    _clip(
        memory_tree,
        name="clip-b.md",
        title="文章A再剪",
        created="2026-09-10 10:00:00+08:00",
    )

    report = _dispatcher(memory_tree, notify).run()

    assert report["cards"] == ["clip-a.md"]  # 较旧的留下
    assert report["duplicates"] == ["clip-b.md"]  # 较新的标待删
    assert memory_tree.is_pending_delete(memory_tree.notes_dir / "clip-b.md")
    assert not memory_tree.is_pending_delete(memory_tree.notes_dir / "clip-a.md")
    # 重复篇只推信息卡（无确认按钮），且不消耗 LLM
    assert len(notify.calls) == 2
    dup_call = notify.calls[1]
    assert dup_call["title"] == "Atelierr 重复剪藏"
    assert dup_call["confirm_note"] is None
    assert "重复" in dup_call["message"]
    assert len(_FakeSummarizer.calls) == 1
    state = _load_state(memory_tree)
    dup_entries = [e for e in state.values() if e.get("duplicate")]
    assert len(dup_entries) == 1 and dup_entries[0]["path"] == "clip-b.md"


def test_duplicate_second_run_noop(memory_tree):
    """重复标删后第二轮：不重复推卡（state + pending_delete 双重幂等）。"""
    notify = _Notify()
    _clip(memory_tree, name="clip-a.md", created="2026-09-09 10:00:00+08:00", note="有用")
    _clip(memory_tree, name="clip-b.md", created="2026-09-10 10:00:00+08:00")
    dispatcher = _dispatcher(memory_tree, notify)
    dispatcher.run()

    report = dispatcher.run()

    assert report["new"] == 0
    assert len(notify.calls) == 2


def test_duplicate_against_previously_confirmed_clip(memory_tree):
    """旧剪藏已确认（标签摘除）后，同 url 再剪仍判重复（state 播种）。"""
    notify = _Notify()
    path = _clip(memory_tree, name="clip-a.md")
    dispatcher = _dispatcher(memory_tree, notify)
    dispatcher.run()
    # 模拟用户在 Obsidian 确认：摘除「待确认」标签（id 保持不变）
    post = frontmatter.loads(path.read_text(encoding="utf-8"))
    post.metadata["tags"] = ["剪藏"]
    path.write_text(frontmatter.dumps(post), encoding="utf-8")

    _clip(memory_tree, name="clip-b.md", created="2026-09-11 10:00:00+08:00")
    report = dispatcher.run()

    assert report["duplicates"] == ["clip-b.md"]
    assert report["cards"] == []
    assert memory_tree.is_pending_delete(memory_tree.notes_dir / "clip-b.md")


def test_summary_failure_still_sends_card(memory_tree):
    """LLM 失败降级：卡片照发（无摘要节），状态照记，第二轮不重试。"""
    _FakeSummarizer.fail = True
    notify = _Notify()
    _clip(memory_tree, note="有用")
    dispatcher = _dispatcher(memory_tree, notify)
    report = dispatcher.run()

    assert report["cards"] == ["clip-a.md"]
    assert len(notify.calls) == 1
    assert "核心论点摘要。" not in notify.calls[0]["message"]
    state = _load_state(memory_tree)
    assert next(iter(state.values()))["summary_status"] == "failed:Boom"

    dispatcher.run()
    assert len(_FakeSummarizer.calls) == 1  # 摘要不重试（成本护栏）
    assert len(notify.calls) == 1


def test_long_body_truncated(memory_tree):
    """长文截到 llm_max_chars 再送 LLM（成本护栏与链接同源）。"""
    _clip(memory_tree, body="字" * 8000, note="有用")

    _dispatcher(memory_tree).run()

    assert len(_FakeSummarizer.calls[0]["text"]) == 6000


def test_dry_run(memory_tree):
    """dry-run 只报告：不推卡、不摘要、不标重复、不写状态。"""
    notify = _Notify()
    _clip(memory_tree, name="clip-a.md", created="2026-09-09 10:00:00+08:00")
    _clip(memory_tree, name="clip-b.md", created="2026-09-10 10:00:00+08:00")

    report = _dispatcher(memory_tree, notify).run(dry_run=True)

    assert report["new"] == 2
    assert report["cards"] == []
    assert report["duplicates"] == []
    assert notify.calls == []
    assert _FakeSummarizer.calls == []
    assert not (memory_tree.state_dir / "clip_cards.json").exists()
    assert not memory_tree.is_pending_delete(memory_tree.notes_dir / "clip-b.md")


def test_damaged_frontmatter_skipped(memory_tree):
    """登记后 frontmatter 被改坏的文件跳过计数，不中断班次。"""
    path = _clip(memory_tree, name="broken.md", url=URL_B)
    _clip(memory_tree, note="有用")
    # 模拟用户在编辑器里改坏 YAML（文件仍在索引中，watcher 不再处理）
    path.write_text("---\ntags: [unclosed\n---\n正文\n", encoding="utf-8")

    report = _dispatcher(memory_tree).run()

    assert report["skipped"] == 1
    assert report["cards"] == ["clip-a.md"]


def test_cli_links_also_dispatches_clips(memory_tree, tmp_path, monkeypatch):
    """CLI 层：links 班次同锁处理剪藏，新剪藏推确认卡，exit 0。"""
    monkeypatch.setattr(clips_module, "LinkProcessor", _FakeSummarizer)
    notify = _Notify()
    monkeypatch.setattr(cli_module, "send_dispatch_notice", notify)
    _clip(memory_tree, note="有用")
    config = tmp_path / "memory.yaml"
    config.write_text(
        f"memory:\n  root: {memory_tree.notes_dir}\n"
        f"  state_dir: {memory_tree.state_dir}\n",
        encoding="utf-8",
    )

    code = cli_module.DispatchCLI(config_path=str(config)).main(["links"])

    assert code == 0
    assert len(notify.calls) == 1
    assert notify.calls[0]["confirm_note"] == "clip-a.md"


def test_card_shows_user_note(memory_tree):
    """剪藏带「备注」（为什么存）：确认卡正文在最显眼处展示（裁决 C1）。"""
    notify = _Notify()
    _clip(memory_tree)
    # 给剪藏补上备注字段（模拟模板新属性，机器不改写——测试直接改文件模拟剪藏产物）
    path = memory_tree.notes_dir / "clip-a.md"
    post = frontmatter.loads(path.read_text(encoding="utf-8"))
    post.metadata["备注"] = "讲 OCR 的那段对工作有用"
    path.write_text(frontmatter.dumps(post), encoding="utf-8")

    report = _dispatcher(memory_tree, notify).run()

    assert report["cards"] == ["clip-a.md"]
    message = notify.calls[0]["message"]
    assert "你的备注：讲 OCR 的那段对工作有用" in message
    # 备注在摘要之前（最显眼）
    assert message.index("你的备注") < message.index("核心论点摘要。")


def test_card_without_note_no_line(memory_tree):
    """无备注（留空/旧模板剪藏）：不即时推卡、不调 LLM，入晚间清单队列
    （2026-09-13 确认卡分级裁决：无评论的攒「今日待确认清单」）。"""
    notify = _Notify()
    _clip(memory_tree)

    report = _dispatcher(memory_tree, notify).run()

    assert notify.calls == []  # 不即时推
    assert report["cards"] == []
    assert report["deferred"] == ["clip-a.md"]
    assert _FakeSummarizer.calls == []  # 推迟=省一次 API（摘要只进卡）
    queued = pending_push._load(memory_tree.state_dir)
    assert [item["file"] for item in queued] == ["clip-a.md"]
    assert queued[0]["kind"] == "clip"
