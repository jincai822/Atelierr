"""复习队列「回响」单元测试：窗口筛选 / 冷却时钟 / 状态纪律。

confidence 锚点（decay_rate=0.95、无引用）：idle 5 天 ≈ 0.774（窗口上），
idle 14/20/25/30 天 ∈ [0.15, 0.5)（窗口内），idle 45 天 ≈ 0.099（窗口下）。
"""

from __future__ import annotations

import json
import os
import time
from datetime import datetime, timedelta

import pytest

from scripts.memory.resurface import ResurfaceManager


def _age(path, idle_days: int) -> None:
    """把笔记 mtime 回拨 idle_days 天（模拟闲置）。"""
    old_ns = int((time.time() - idle_days * 86400) * 1e9)
    os.utime(path, ns=(old_ns, old_ns))


def test_window_filters(memory_tree, make_note):
    """只有 confidence 落在 [0.15, 0.5) 的笔记入队。"""
    make_note(memory_tree, "fresh.md", "新笔记")
    make_note(memory_tree, "hot.md", "还热", idle_days=5)
    make_note(memory_tree, "due.md", "该复习", idle_days=20)
    make_note(memory_tree, "cold.md", "已冷", idle_days=45)

    picked = ResurfaceManager(memory_tree).candidates()

    assert [item["filename"] for item in picked] == ["due.md"]
    assert picked[0]["idle_days"] == 20
    assert 0.15 <= picked[0]["confidence"] < 0.5


def test_sorted_by_confidence_ascending_and_daily_limit(memory_tree, make_note):
    """按 confidence 升序（最该复习的在前）；默认只推 daily_count 条。"""
    make_note(memory_tree, "d14.md", "x", idle_days=14)
    make_note(memory_tree, "d20.md", "x", idle_days=20)
    make_note(memory_tree, "d25.md", "x", idle_days=25)
    make_note(memory_tree, "d30.md", "x", idle_days=30)

    manager = ResurfaceManager(memory_tree)
    picked = manager.candidates()

    assert [item["filename"] for item in picked] == ["d30.md", "d25.md", "d20.md"]
    full = manager.candidates(limit=10)
    assert [item["filename"] for item in full] == [
        "d30.md",
        "d25.md",
        "d20.md",
        "d14.md",
    ]


def test_pending_delete_excluded(memory_tree, make_note):
    """pending_delete 标记的笔记即使 confidence 在窗口内也不入队。"""
    path = make_note(memory_tree, "due.md", "该复习", idle_days=20)
    note_id = memory_tree._find_entry_id(path)
    memory_tree._register(path, note_id, pending_delete=True)

    assert ResurfaceManager(memory_tree).candidates() == []


def test_digest_source_excluded(memory_tree):
    """机器生成的历史摘要（source=digest）不进复习队列。"""
    path = memory_tree.create_note(
        "今日摘要-2026-08-10.md", "摘要", source="digest"
    )
    _age(path, 20)

    assert ResurfaceManager(memory_tree).candidates() == []


def test_system_source_excluded(memory_tree):
    """基础设施笔记（source=system，控制台等）不进复习队列。"""
    path = memory_tree.create_note("控制台.md", "面板", source="system")
    _age(path, 20)

    assert ResurfaceManager(memory_tree).candidates() == []


def test_cooldown_blocks_repush(memory_tree, make_note):
    """推送后 cooldown_days 内不再入队；满期后重新入队。"""
    make_note(memory_tree, "due.md", "该复习", idle_days=20)
    manager = ResurfaceManager(memory_tree)
    now0 = datetime.now().astimezone()

    picked = manager.candidates(now=now0)
    manager.mark_pushed([picked[0]["id"]], now=now0)

    assert manager.candidates(now=now0 + timedelta(days=2)) == []
    assert len(manager.candidates(now=now0 + timedelta(days=3))) == 1


def test_state_only_in_state_dir_and_notes_untouched(memory_tree, make_note):
    """冷却状态只写 <state_dir>/resurface.json；笔记内容与 mtime 不变。"""
    path = make_note(memory_tree, "due.md", "该复习", idle_days=20)
    before_bytes = path.read_bytes()
    before_mtime = path.stat().st_mtime_ns
    manager = ResurfaceManager(memory_tree)

    manager.mark_pushed([manager.candidates()[0]["id"]])

    assert (memory_tree.state_dir / "resurface.json").exists()
    assert path.read_bytes() == before_bytes
    assert path.stat().st_mtime_ns == before_mtime


def test_corrupt_state_tolerated(memory_tree, make_note):
    """resurface.json 损坏视为无冷却记录（最多重推一次），不崩溃。"""
    make_note(memory_tree, "due.md", "该复习", idle_days=20)
    (memory_tree.state_dir / "resurface.json").write_text(
        "not-json{", encoding="utf-8"
    )

    picked = ResurfaceManager(memory_tree).candidates()

    assert [item["filename"] for item in picked] == ["due.md"]


def test_access_leaves_queue(memory_tree, make_note):
    """用户点开（on_note_accessed）→ confidence 重置 → 自然离开队列。"""
    path = make_note(memory_tree, "due.md", "该复习", idle_days=20)
    manager = ResurfaceManager(memory_tree)
    assert len(manager.candidates()) == 1

    memory_tree.on_note_accessed(path)

    assert manager.candidates() == []


def test_empty_queue_and_zero_limit(memory_tree, make_note):
    """全新笔记库 → 空队列；limit=0 → 空。"""
    make_note(memory_tree, "fresh.md", "新笔记")
    manager = ResurfaceManager(memory_tree)

    assert manager.candidates() == []
    assert manager.candidates(limit=0) == []


def test_invalid_window_raises(memory_tree):
    """窗口 low >= high 直接拒绝。"""
    with pytest.raises(ValueError):
        ResurfaceManager(memory_tree, window_low=0.6, window_high=0.5)


def test_from_config_defaults_and_custom(tmp_path):
    """from_config：无 resurface 节用默认值；有则按配置生效。"""
    from scripts.memory.core import MemoryTree

    plain = tmp_path / "plain.yaml"
    plain.write_text(
        f"memory:\n  root: {tmp_path}/m1\n  state_dir: {tmp_path}/s1\n",
        encoding="utf-8",
    )
    manager = ResurfaceManager.from_config(str(plain))
    assert manager.window_low == 0.15
    assert manager.window_high == 0.5
    assert manager.daily_count == 3
    assert manager.cooldown_days == 3

    custom = tmp_path / "custom.yaml"
    custom.write_text(
        f"memory:\n"
        f"  root: {tmp_path}/m2\n"
        f"  state_dir: {tmp_path}/s2\n"
        f"  resurface:\n"
        f"    window_low: 0.2\n"
        f"    window_high: 0.6\n"
        f"    daily_count: 5\n"
        f"    cooldown_days: 7\n",
        encoding="utf-8",
    )
    tree = MemoryTree(str(tmp_path / "m2"), state_dir=str(tmp_path / "s2"))
    manager = ResurfaceManager.from_config(str(custom), tree=tree)
    assert manager.tree is tree
    assert manager.window_low == 0.2
    assert manager.window_high == 0.6
    assert manager.daily_count == 5
    assert manager.cooldown_days == 7


def test_mark_pushed_persists_json(memory_tree, make_note):
    """mark_pushed 落盘内容可读且按 id 记录时间戳。"""
    path = make_note(memory_tree, "due.md", "该复习", idle_days=20)
    note_id = memory_tree._find_entry_id(path)

    ResurfaceManager(memory_tree).mark_pushed([note_id])

    state = json.loads(
        (memory_tree.state_dir / "resurface.json").read_text(encoding="utf-8")
    )
    assert note_id in state
