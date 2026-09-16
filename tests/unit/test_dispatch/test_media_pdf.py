"""media 附件路由的 PDF 分支单元测试（划重点路由，无真实 LLM/PDF 引擎）。

PDF → HighlightsProcessor 路由、清单笔记格式（不带"待确认"）、
失败熔断、幂等均为真实代码路径，处理器以工厂注入假实现。
"""

from __future__ import annotations

import os
import time
from pathlib import Path

import frontmatter
import pytest

from scripts.dispatch.media import MediaDispatcher
from scripts.processors.base import ProcessResult


class _FakeHighlightsProcessor:
    """假划重点处理器：记录调用，返回固定清单结果。"""

    calls = []
    fail_with = None

    def process(self, path):
        type(self).calls.append(str(path))
        if type(self).fail_with:
            return ProcessResult(success=False, error=type(self).fail_with)
        return ProcessResult(
            success=True,
            markdown="# 划重点清单：测试书\n\n- [ ] **概念甲**（第 3 页）\n",
            metadata={"candidates": 1},
        )


@pytest.fixture(autouse=True)
def _reset_fake():
    _FakeHighlightsProcessor.calls = []
    _FakeHighlightsProcessor.fail_with = None
    yield


def _dispatcher(tree):
    return MediaDispatcher(tree, highlights_factory=_FakeHighlightsProcessor)


def _add_pdf(tree, name="测试书.pdf", age_seconds=60, content=None):
    attach = Path(tree.attachments_dir)
    attach.mkdir(parents=True, exist_ok=True)
    path = attach / name
    # content 缺省固定字节——同字节文件会被内容级查重判为重复件，
    # 模拟"不同版本/不同书"的用例必须传不同 content
    path.write_bytes(content if content is not None else b"%PDF fake-bytes")
    old = time.time() - age_seconds
    os.utime(path, (old, old))
    return path


def test_pdf_routes_to_highlights(memory_tree):
    """PDF → 划重点清单笔记：source/tags 正确，不带"待确认"。"""
    _add_pdf(memory_tree)

    report = _dispatcher(memory_tree).run()

    assert report["found"] == 1
    assert len(report["created"]) == 1
    filename = report["created"][0]
    assert filename.startswith("系统/划重点-测试书-")  # 清单进机器产物区
    post = frontmatter.loads(
        (memory_tree.notes_dir / filename).read_text(encoding="utf-8")
    )
    assert post["source"] == "highlights"
    assert post["tags"] == ["划重点"]
    assert "待确认" not in post["tags"]
    assert "- [ ] **概念甲**（第 3 页）" in post.content
    assert len(_FakeHighlightsProcessor.calls) == 1


def test_pdf_failure_circuit_breaks(memory_tree):
    """PDF 处理连续失败：3 次熔断，第 4 轮不再调处理器。"""
    _FakeHighlightsProcessor.fail_with = "未设置 DEEPSEEK_API_KEY"
    _add_pdf(memory_tree)
    dispatcher = _dispatcher(memory_tree)

    for _ in range(3):
        report = dispatcher.run()
        assert len(report["failed"]) == 1

    assert not list(Path(memory_tree.notes_dir).rglob("划重点-*.md"))  # 根层与系统/ 都无
    dispatcher.run()
    assert len(_FakeHighlightsProcessor.calls) == 3


def test_pdf_idempotent_second_run(memory_tree):
    """同一 PDF 第二轮跳过，不重复建清单。"""
    _add_pdf(memory_tree)
    dispatcher = _dispatcher(memory_tree)
    dispatcher.run()

    report = dispatcher.run()

    assert report["created"] == []
    assert report["skipped"] == 1
    assert len(_FakeHighlightsProcessor.calls) == 1


# ----------------------------------------------------------------------
# 书籍档案卡（2026-09-14 裁决：建档 + 查重 + 归档路由到 书籍/[中图法/]）
# ----------------------------------------------------------------------


class _FakeBookProcessor:
    """假划重点处理器：返回带书籍档案元数据的结果。"""

    def __init__(self, book=None):
        self._book = book if book is not None else {
            "title": "认知觉醒",
            "author": "周岭",
            "edition": "第1版",
            "isbn": "",
            "clc": "B84-心理学",
            "level": "L2",
            "level_reason": "方法论可复用",
            "mainline": "用认知科学解释成长",
            "chapter_advice": [{"chapter": "第三章 专注力", "why": "对着目标"}],
        }

    def process(self, path):
        return ProcessResult(
            success=True,
            markdown="# 《认知觉醒》导读与筛查清单\n\n- [ ] **概念甲**（第 3 页）\n",
            metadata={"candidates": 1, "book": self._book},
        )


def _book_card_paths(tree):
    return sorted(Path(tree.inbox_dir).glob("书籍-*.md"))


def test_pdf_book_creates_card_in_inbox(memory_tree):
    """书籍模式：清单照进 系统/，档案卡进 inbox 带 待确认/书籍/中图法 标签。"""
    _add_pdf(memory_tree, name="认知觉醒.pdf")

    report = MediaDispatcher(
        memory_tree, highlights_factory=_FakeBookProcessor
    ).run()

    created = report["created"]
    assert any(name.startswith("系统/划重点-") for name in created)
    card_rel = next(name for name in created if name.startswith("inbox/书籍-认知觉醒-"))
    cards = _book_card_paths(memory_tree)
    assert len(cards) == 1
    post = frontmatter.loads(cards[0].read_text(encoding="utf-8"))
    assert post["type"] == "Book"
    assert post["title"] == "《认知觉醒》"
    assert post["source"] == "book"
    assert post["reading_status"] == "想读"
    assert post["level_suggestion"] == "L2"
    assert post["tags"] == ["待确认", "书籍", "B84-心理学"]
    assert post["book_key"]
    assert "[[attachments/书籍/认知觉醒.pdf]]" not in post.content  # 附件在顶层
    assert "[[attachments/认知觉醒.pdf]]" in post.content
    assert "[[划重点-认知觉醒-" in post.content  # 清单双链
    # 归档路由：书籍/[中图法/]（derive_archive_dir 单一规则源）
    from scripts.dispatch.archive import derive_archive_dir
    assert derive_archive_dir(post) == ("书籍", "B84-心理学")
    assert (memory_tree.notes_dir / card_rel[len("inbox/"):]).exists() is False  # 在 inbox 不在 memory


def test_pdf_book_card_dedupes_same_book(memory_tree):
    """同书名+作者+版次（同 book_key）：不重复建卡。"""
    _add_pdf(memory_tree, name="认知觉醒.pdf")
    dispatcher = MediaDispatcher(memory_tree, highlights_factory=_FakeBookProcessor)
    dispatcher.run()
    # 抹掉处理状态逼它重跑同一 PDF（档案卡仍在 inbox）
    dispatcher.state_path.unlink()
    _FakeBookProcessor  # noqa: B018 - 保持引用
    dispatcher2 = MediaDispatcher(
        memory_tree,
        highlights_factory=_FakeBookProcessor,
    )
    dispatcher2.run()

    assert len(_book_card_paths(memory_tree)) == 1


def test_pdf_book_card_warns_on_different_edition(memory_tree):
    """同名不同版：建新卡，但正文带「疑似不同版本」警示行交人工定夺。"""
    first = _FakeBookProcessor()
    _add_pdf(memory_tree, name="认知觉醒.pdf")
    MediaDispatcher(memory_tree, highlights_factory=lambda: first).run()
    assert len(_book_card_paths(memory_tree)) == 1

    # 第二版进来（不同版次 → 不同 book_key；真实不同版字节必不同，
    # 绕开内容级查重）
    second_book = dict(first._book, edition="第2版")
    _add_pdf(memory_tree, name="认知觉醒-第2版.pdf", content=b"%PDF 2nd-edition")
    MediaDispatcher(
        memory_tree, highlights_factory=lambda: _FakeBookProcessor(second_book)
    ).run()

    cards = _book_card_paths(memory_tree)
    assert len(cards) == 2
    posts = [frontmatter.loads(c.read_text(encoding="utf-8")) for c in cards]
    second = next(p for p in posts if p.get("book_edition") == "第2版")
    assert "已有同名书的不同版本档案" in second.content


def test_reader_context_reads_goals_and_todos(memory_tree):
    """「对着什么」素材：读 目标/ 与 待办/ 笔记标题（frontmatter title 优先）。"""
    goals = Path(memory_tree.notes_dir) / "目标"
    goals.mkdir(parents=True)
    (goals / "今年减重十斤.md").write_text(
        "---\ntitle: 今年减重十斤\n---\n正文\n", encoding="utf-8"
    )
    todos = Path(memory_tree.notes_dir) / "待办"
    todos.mkdir(parents=True)
    (todos / "todo-001.md").write_text(
        "---\ntitle: 写九月月报\n---\n正文\n", encoding="utf-8"
    )

    lines = MediaDispatcher(memory_tree)._reader_context()

    assert "目标：今年减重十斤" in lines
    assert "待办：写九月月报" in lines


def test_pdf_book_card_dedupes_after_archival(memory_tree):
    """档案卡归档进 书籍/中图法/ 子目录后，查重仍命中（递归扫描）+报人工。"""
    _add_pdf(memory_tree, name="认知觉醒.pdf")
    dispatcher = MediaDispatcher(memory_tree, highlights_factory=_FakeBookProcessor)
    dispatcher.run()
    card = _book_card_paths(memory_tree)[0]
    # 模拟 ✅ 确认归档：移进 memory/书籍/B84-心理学/
    target_dir = Path(memory_tree.notes_dir) / "书籍" / "B84-心理学"
    target_dir.mkdir(parents=True)
    card.rename(target_dir / card.name)

    # 状态丢失重跑同一 PDF：查重必须命中已归档的卡，不再建、且报人工
    dispatcher2 = MediaDispatcher(memory_tree, highlights_factory=_FakeBookProcessor)
    dispatcher2.state_path.unlink()
    report = dispatcher2.run()

    assert _book_card_paths(memory_tree) == []  # inbox 没有新卡
    assert report.get("deduped") == ["认知觉醒"]
    assert len(list(target_dir.glob("书籍-*.md"))) == 1  # 原卡原地不动


# ----------------------------------------------------------------------
# 全文落盘（2026-09-16 裁决 KM 规格：原件收专夹 + 全文.md + 清单/档案卡带链）
# ----------------------------------------------------------------------


class _FakeFulltextProcessor:
    """假划重点处理器：返回带全文的清单结果（触发全文落盘）。"""

    ocr = False

    def process(self, path):
        return ProcessResult(
            success=True,
            text="第一页正文。\n\n第二页正文。",
            markdown="# 划重点清单：长文\n\n- [ ] **概念甲**（第 3 页）\n",
            metadata={"candidates": 1, "ocr": type(self).ocr},
        )


def test_pdf_shelves_original_and_fulltext(memory_tree):
    """原件收进专夹、全文.md 落同夹、清单带全文链接（文字层提取）。"""
    _add_pdf(memory_tree, name="长文.pdf")

    report = MediaDispatcher(
        memory_tree, highlights_factory=_FakeFulltextProcessor
    ).run()

    folder = Path(memory_tree.attachments_dir) / "长文"
    assert (folder / "长文.pdf").exists()  # 原件收进专夹
    assert "第二页正文" in (folder / "全文.md").read_text(encoding="utf-8")
    checklist = (memory_tree.notes_dir / report["created"][0]).read_text(
        encoding="utf-8"
    )
    assert "[[attachments/长文/全文.md]]" in checklist
    assert "文字层提取" in checklist


def test_pdf_ocr_fulltext_marked(memory_tree):
    """OCR 重建的全文：清单标注"OCR 重建"。"""
    _FakeFulltextProcessor.ocr = True
    try:
        _add_pdf(memory_tree, name="扫描书.pdf")
        report = MediaDispatcher(
            memory_tree, highlights_factory=_FakeFulltextProcessor
        ).run()
    finally:
        _FakeFulltextProcessor.ocr = False

    checklist = (memory_tree.notes_dir / report["created"][0]).read_text(
        encoding="utf-8"
    )
    assert "OCR 重建" in checklist


def test_pdf_book_fulltext_folder_named_by_title(memory_tree):
    """书籍模式：专夹按书名命名，档案卡带全文链接、原件指专夹新位置。"""

    class _BookWithText(_FakeBookProcessor):
        def process(self, path):
            result = super().process(path)
            result.text = "全书正文"
            return result

    _add_pdf(memory_tree, name="认知觉醒.pdf")
    MediaDispatcher(memory_tree, highlights_factory=_BookWithText).run()

    folder = Path(memory_tree.attachments_dir) / "认知觉醒"
    assert (folder / "认知觉醒.pdf").exists()
    assert "全书正文" in (folder / "全文.md").read_text(encoding="utf-8")
    cards = _book_card_paths(memory_tree)
    post = frontmatter.loads(cards[0].read_text(encoding="utf-8"))
    assert "[[attachments/认知觉醒/认知觉醒.pdf]]" in post.content
    assert "[[attachments/认知觉醒/全文.md]]" in post.content


def test_pdf_shelve_failure_degrades(memory_tree, monkeypatch):
    """全文落盘失败（OSError）：原件原地不动，清单照建、无全文链接。"""
    import shutil

    def _boom(*args, **kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(shutil, "move", _boom)
    _add_pdf(memory_tree, name="长文.pdf")

    report = MediaDispatcher(
        memory_tree, highlights_factory=_FakeFulltextProcessor
    ).run()

    assert len(report["created"]) == 1  # 清单照建
    assert (Path(memory_tree.attachments_dir) / "长文.pdf").exists()  # 原件原地
    checklist = (memory_tree.notes_dir / report["created"][0]).read_text(
        encoding="utf-8"
    )
    assert "全文" not in checklist


def test_pdf_structured_assets_shelved(memory_tree, tmp_path):
    """结构化全文：插图裁切收进专夹 图片/，全文引用改写为库内全路径。"""
    assets = tmp_path / "assets"
    assets.mkdir()
    (assets / "p0001-fig.jpg").write_bytes(b"\xff\xd8fake")

    class _Structured(_FakeFulltextProcessor):
        def process(self, path):
            result = super().process(path)
            result.text = "正文。\n\n![[图片/p0001-fig.jpg]]\n"
            result.metadata["ocr"] = True
            result.metadata["ocr_assets"] = str(assets)
            return result

    _add_pdf(memory_tree, name="长文.pdf")
    MediaDispatcher(memory_tree, highlights_factory=_Structured).run()

    folder = Path(memory_tree.attachments_dir) / "长文"
    assert (folder / "图片" / "p0001-fig.jpg").exists()  # 裁切收进专夹
    fulltext = (folder / "全文.md").read_text(encoding="utf-8")
    assert "![[attachments/长文/图片/p0001-fig.jpg]]" in fulltext  # 全路径改写
    assert not assets.exists()  # 临时目录已清理
