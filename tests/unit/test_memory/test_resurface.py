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


def test_machine_sources_excluded(memory_tree):
    """滞留中转站的机器搬运来源（link/media/webclip）不进复习队列
    （2026-09-12 药2：复习位只留给人写与被引用的笔记；2026-09-16
    修订：该排除只针对**未确认归档**（inbox/ 内）的机器笔记）。

    闲置 8 天：方案 C（v1.4）3 倍速后 confidence ≈ 0.29 仍在复习窗口
    内——排除只能来自机器来源规则，而非窗口过滤。"""
    for i, src in enumerate(("link", "media", "webclip")):
        path = memory_tree.create_note(
            f"m{i}.md", "机器全文", source=src, inbox=True
        )
        _age(path, 8)

    assert ResurfaceManager(memory_tree).candidates() == []


def test_archived_machine_source_included(memory_tree):
    """已确认归档出 inbox/ 的机器笔记恢复复习资格（2026-09-16 用户裁决：
    点 ✅ = 人认可要吸收的内容，与人写笔记同权；无需反链）。"""
    path = memory_tree.create_note("dump.md", "转写全文", source="link")
    _age(path, 8)  # 机器 3 倍速：confidence ≈ 0.29 ∈ 窗口

    picked = ResurfaceManager(memory_tree).candidates()

    assert [item["filename"] for item in picked] == ["dump.md"]


def test_machine_source_with_backlink_included(memory_tree, make_note):
    """例外：滞留中转站的机器全文被 [[引用]] ≥1 次恢复复习资格
    （反链与每日衰减同源）。

    闲置 10 天 + 1 次引用：方案 C（v1.4）下 confidence = 0.95^(30/1.2)
    ≈ 0.28，仍在复习窗口内—— exemption 生效可见。"""
    dump = memory_tree.create_note(
        "dump.md", "转写全文", source="link", inbox=True
    )
    _age(dump, 10)
    make_note(memory_tree, "mine.md", "参见 [[dump]] 的观点", idle_days=5)

    picked = ResurfaceManager(memory_tree).candidates()

    assert [item["filename"] for item in picked] == ["dump.md"]


def test_record_outcome_spacing(memory_tree):
    """间隔重复（简化 SM-2）：想起来 间隔×2（封顶 60）、没想起来 ÷2
    （下限 1 天）、streak 计数；只写 resurface.json，不进 confidence。"""
    manager = ResurfaceManager(memory_tree)
    manager.mark_pushed(["n1"])

    state = manager.record_outcome("n1", remembered=True)
    assert state["interval"] == 6.0  # 3 × 2
    assert state["streak"] == 1

    state = manager.record_outcome("n1", remembered=True)
    assert state["interval"] == 12.0
    state = manager.record_outcome("n1", remembered=False)
    assert state["interval"] == 6.0
    assert state["streak"] == 0


def test_outcome_drives_cooldown(memory_tree, make_note):
    """没想起来 → 间隔缩短 → 更快再推；想起来两次 → 间隔拉长不再天天推。"""
    note = make_note(memory_tree, filename="old.md", content="内容", idle_days=20)
    manager = ResurfaceManager(memory_tree)
    note_id = memory_tree._find_entry_id(note)

    manager.mark_pushed([note_id])
    manager.record_outcome(note_id, remembered=False)  # interval 3 → 1.5
    # 2 天后：间隔 1.5 天已过 → 可再推
    later = datetime.now().astimezone() + timedelta(days=2)
    pushed = manager._load_state()
    assert not manager._in_cooldown(pushed[note_id], later)

    manager.record_outcome(note_id, remembered=True)   # 1.5 → 3
    manager.record_outcome(note_id, remembered=True)   # 3 → 6
    pushed = manager._load_state()
    assert manager._in_cooldown(pushed[note_id], later)  # 2 天 < 6 天间隔


def test_old_stamp_format_still_works(memory_tree):
    """旧格式（纯时间戳）状态兼容：按 cooldown_days 判定。"""
    manager = ResurfaceManager(memory_tree)
    now = datetime.now().astimezone()
    manager._save_state({"n1": now.isoformat(timespec="seconds")})
    assert manager._in_cooldown(manager._load_state()["n1"], now)
    assert not manager._in_cooldown(
        manager._load_state()["n1"], now + timedelta(days=4)
    )


def test_resurface_feedback_bridge(memory_tree, make_note, monkeypatch):
    """桥回调：点「想起来了」→ 间隔翻倍 + 记访问；批次重建剩余卡。"""
    from types import SimpleNamespace
    from scripts.dispatch.feishu import FeishuBridge

    note = make_note(memory_tree, filename="old.md", content="内容", idle_days=20)
    bridge = FeishuBridge(memory_tree, app_id="x", app_secret="y")
    monkeypatch.setattr(bridge, "_send_feedback", lambda chat_id, text: None)

    event = SimpleNamespace(
        event=SimpleNamespace(
            action=SimpleNamespace(
                value={
                    "action": "resurface_feedback",
                    "note": "old.md",
                    "outcome": "good",
                    "batch": ["old.md", "other.md"],
                }
            ),
            context=None,
            operator=None,
        )
    )
    resp = bridge.handle_card_action(event)

    assert resp["toast"]["type"] == "success"
    # 批次重建：剩余 other.md 的复习卡
    card = resp["card"]["data"]
    assert "1" in card["header"]["title"]["content"]
    # 访问时钟已重置
    assert memory_tree._entry(note)["last_accessed"] is not None


def test_exile_skips_candidates(memory_tree, make_note):
    """流放（🚫 不再推）：candidates 永久跳过（2026-09-18 脑科学 C3）。"""
    from scripts.memory.resurface import ResurfaceManager

    note = make_note(memory_tree, filename="a.md", content="内容", idle_days=10)
    manager = ResurfaceManager(memory_tree)
    note_id = memory_tree._find_entry_id(note) or note.stem

    manager.exile(note_id)

    assert all(item["id"] != note_id for item in manager.candidates())


def test_two_consecutive_forgets_auto_exile(memory_tree, make_note):
    """水蛭处理：连续 2 次「没想起来」自动流放；想起来清零连败。"""
    from scripts.memory.resurface import ResurfaceManager

    note = make_note(memory_tree, filename="b.md", content="内容", idle_days=10)
    manager = ResurfaceManager(memory_tree)
    note_id = memory_tree._find_entry_id(note) or note.stem

    first = manager.record_outcome(note_id, remembered=False)
    assert first.get("fail_streak") == 1 and not first.get("exiled")
    second = manager.record_outcome(note_id, remembered=False)
    assert second.get("exiled") is True
    assert all(item["id"] != note_id for item in manager.candidates())

    # 想起来一次：连败清零（不流放）
    note2 = make_note(memory_tree, filename="c.md", content="内容", idle_days=10)
    id2 = memory_tree._find_entry_id(note2) or note2.stem
    manager.record_outcome(id2, remembered=False)
    good = manager.record_outcome(id2, remembered=True)
    assert good.get("fail_streak") == 0
