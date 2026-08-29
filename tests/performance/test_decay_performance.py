"""衰减性能测试：1000 条笔记全量衰减 < 5s（架构性能目标）。"""

from __future__ import annotations

import time

from scripts.memory.decay import DecayManager

NOTE_COUNT = 1000


def test_decay_performance(memory_tree, make_note):
    """1000 条笔记的 DecayManager.run() 必须 < 5s。"""
    for i in range(NOTE_COUNT):
        make_note(
            memory_tree,
            filename=f"note-{i:04d}.md",
            content=f"衰减性能测试 {i}",
            idle_days=i % 30,
        )

    manager = DecayManager(memory_tree)
    start = time.perf_counter()
    report = manager.run()
    elapsed = time.perf_counter() - start

    assert elapsed < 5.0, f"衰减耗时 {elapsed:.3f}s，超过 5s 上限"
    assert report["total_notes"] == NOTE_COUNT
    assert report["report_path"]
