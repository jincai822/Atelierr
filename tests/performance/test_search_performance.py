"""搜索性能测试：1000 条笔记内搜索 < 100ms（验收 1.4 性能条）。"""

from __future__ import annotations

import time

from scripts.memory.search import MemorySearcher

NOTE_COUNT = 1000


def test_search_performance(memory_tree, make_note):
    """1000 条笔记的搜索延迟必须 < 100ms。"""
    for i in range(NOTE_COUNT):
        make_note(
            memory_tree,
            filename=f"note-{i:04d}.md",
            content=f"test note {i} 关于 Python 性能优化",
        )

    searcher = MemorySearcher(memory_tree)
    # 预热：填充增量读缓存
    warm = searcher.search("test")
    assert len(warm) > 0

    start = time.perf_counter()
    results = searcher.search("test")
    elapsed = time.perf_counter() - start

    assert elapsed < 0.1, f"搜索耗时 {elapsed:.3f}s，超过 100ms 上限"
    assert len(results) == 10  # 默认 limit


def test_search_cold_with_cache_invalidation(memory_tree, make_note):
    """mtime 变化后缓存失效并正确重读。"""
    note = make_note(memory_tree, filename="only.md", content="unique keyword alpha")
    searcher = MemorySearcher(memory_tree)
    assert searcher.search("alpha")
    # 改写文件 → 重新搜索应命中新内容
    note.write_text("全新的关键词 beta", encoding="utf-8")
    results = searcher.search("beta")
    assert len(results) == 1
    assert "alpha" not in results[0].content
