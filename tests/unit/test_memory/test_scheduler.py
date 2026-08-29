"""DecayScheduler 单元测试。"""
from __future__ import annotations

import threading

from scripts.memory.scheduler import DecayScheduler


def test_run_once(memory_tree, make_note):
    """run_once 返回报告 dict 且 sidecar 已更新。"""
    make_note(memory_tree, filename="a.md", idle_days=10)
    scheduler = DecayScheduler(memory_tree)
    report = scheduler.run_once()
    assert report["total_notes"] == 1
    assert memory_tree.layer_of(memory_tree.notes_dir / "a.md") == "mid-term"


def test_run_forever_stops_on_event(memory_tree, make_note):
    """run_forever 循环执行，stop_event 置位即退出。"""
    make_note(memory_tree, filename="a.md")
    scheduler = DecayScheduler(memory_tree, interval_hours=1e-6)
    stop = threading.Event()
    timer = threading.Timer(0.05, stop.set)
    timer.start()
    try:
        scheduler.run_forever(stop_event=stop)
    finally:
        timer.cancel()
    assert stop.is_set()
    # 循环期间至少执行过一次衰减
    assert memory_tree._entry(memory_tree.notes_dir / "a.md") is not None
