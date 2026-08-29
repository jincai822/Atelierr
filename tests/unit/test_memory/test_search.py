"""MemorySearcher 单元测试（验收 1.4 功能条 + 扩展）。"""
from __future__ import annotations

import frontmatter

from scripts.memory.search import MemorySearcher


def _seed(memory_tree, make_note):
    make_note(
        memory_tree,
        filename="python.md",
        content="Python 是流行的编程语言，广泛用于 AI 开发",
        tags=["编程", "AI"],
    )
    make_note(memory_tree, filename="cooking.md", content="今晚做番茄炒蛋", tags=["生活"])
    return memory_tree


def test_full_text_search(memory_tree, make_note):
    """全文搜索：结果非空且每个结果的 title 或 content 含关键词。"""
    _seed(memory_tree, make_note)
    results = MemorySearcher(memory_tree).search("Python")
    assert len(results) > 0
    assert all("Python" in r.content or "Python" in r.title for r in results)


def test_full_text_search_case_insensitive(memory_tree, make_note):
    _seed(memory_tree, make_note)
    results = MemorySearcher(memory_tree).search("python")
    assert len(results) > 0
    assert all("Python" in r.content or "Python" in r.title for r in results)


def test_tag_search(memory_tree, make_note):
    """标签搜索：任一命中即算（OR 语义）。"""
    _seed(memory_tree, make_note)
    results = MemorySearcher(memory_tree).search(tags=["编程", "AI"])
    assert len(results) > 0
    assert all(any(tag in r.tags for tag in ["编程", "AI"]) for r in results)


def test_date_range_search(memory_tree, make_note):
    """日期范围：created 日期部分闭区间过滤。"""
    make_note(memory_tree, filename="new.md", content="新笔记")
    old = memory_tree.notes_dir / "old.md"
    post = frontmatter.Post(
        "旧笔记",
        id="01J6" + "0" * 22,
        title="旧笔记",
        created="2025-01-01T00:00:00",
        source="unknown",
        tags=[],
    )
    old.write_text(frontmatter.dumps(post), encoding="utf-8")

    results = MemorySearcher(memory_tree).search(date_from="2026-01-01", date_to="2026-12-31")
    assert len(results) > 0
    assert all("2026" in str(r.created) for r in results)
    assert all(r.path.name != "old.md" for r in results)


def test_sorted_by_confidence_desc(memory_tree, make_note):
    """结果按 confidence 降序。"""
    fresh = make_note(memory_tree, filename="fresh.md", content="stuff fresh")
    old = make_note(memory_tree, filename="old.md", content="stuff old", idle_days=30)
    results = MemorySearcher(memory_tree).search("stuff")
    assert [r.path for r in results] == [fresh, old]
    assert results[0].confidence >= results[1].confidence


def test_limit(memory_tree, make_note):
    for i in range(5):
        make_note(memory_tree, filename=f"n{i}.md", content="批量笔记")
    results = MemorySearcher(memory_tree).search("批量", limit=3)
    assert len(results) == 3


def test_limit_zero_returns_empty(memory_tree, make_note):
    make_note(memory_tree)
    assert MemorySearcher(memory_tree).search(limit=0) == []


def test_layer_filter(memory_tree, make_note):
    a = make_note(memory_tree, filename="a.md", content="layer a")
    b = make_note(memory_tree, filename="b.md", content="layer b")
    memory_tree.move_note(b, "mid-term")
    results = MemorySearcher(memory_tree).search(layer="mid-term")
    assert [r.path for r in results] == [b]
    assert [r.path for r in MemorySearcher(memory_tree).search(layer="short-term")] == [a]


def test_combined_query_and_tags(memory_tree, make_note):
    """组合 query + tags 过滤。"""
    make_note(memory_tree, filename="a.md", content="Python 编程", tags=["编程"])
    make_note(memory_tree, filename="b.md", content="Python 烹饪", tags=["生活"])
    make_note(memory_tree, filename="c.md", content="Ruby 编程", tags=["编程"])
    results = MemorySearcher(memory_tree).search("Python", tags=["编程"])
    assert [r.path.name for r in results] == ["a.md"]


def test_unregistered_note_defaults(memory_tree):
    """未登记文件：layer 视为 short-term、confidence live 重算（references=0）。"""
    raw = memory_tree.notes_dir / "raw.md"
    raw.write_text("这是裸文件内容 Python", encoding="utf-8")
    results = MemorySearcher(memory_tree).search("Python")
    assert len(results) == 1
    assert results[0].layer == "short-term"
    assert results[0].confidence == 1.0


def test_empty_query_returns_all(memory_tree, make_note):
    make_note(memory_tree, filename="a.md", content="a")
    make_note(memory_tree, filename="b.md", content="b")
    results = MemorySearcher(memory_tree).search()
    assert len(results) == 2
