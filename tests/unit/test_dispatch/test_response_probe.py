"""推送响应率观测（实验 0）单元测试：注册 / 结案 / 统计 / 状态纪律。"""

from __future__ import annotations

import json
import os
from datetime import datetime, timedelta

from scripts.dispatch.response_probe import ResponseProbe


def _set_mtime(path, when: datetime) -> None:
    """把文件 mtime 设定到指定时刻（模拟用户编辑）。"""
    ns = int(when.timestamp() * 1e9)
    os.utime(path, ns=(ns, ns))


def _item(note_id: str, filename: str):
    return {"id": note_id, "filename": filename}


def test_register_creates_pending(memory_tree, make_note):
    """register 建立 pending 观测，base_mtime 为推送时刻的文件快照。"""
    path = make_note(memory_tree, "due.md", "内容", idle_days=20)
    note_id = memory_tree._find_entry_id(path)

    ResponseProbe(memory_tree).register([_item(note_id, "due.md")])

    state = json.loads(
        (memory_tree.state_dir / "response_probe.json").read_text(
            encoding="utf-8"
        )
    )
    assert state["pending"][note_id]["filename"] == "due.md"
    assert state["pending"][note_id]["base_mtime"] == path.stat().st_mtime


def test_edit_within_window_counts_responded(memory_tree, make_note):
    """推送后 48h 内 mtime 变化 → 响应（edited），记录延迟小时数。"""
    path = make_note(memory_tree, "due.md", "内容", idle_days=20)
    note_id = memory_tree._find_entry_id(path)
    probe = ResponseProbe(memory_tree)
    now0 = datetime.now().astimezone()
    probe.register([_item(note_id, "due.md")], now=now0)

    _set_mtime(path, now0 + timedelta(hours=12))
    result = probe.check_pending(now=now0 + timedelta(hours=24))

    assert result == {"resolved": 1, "responded": 1}
    summary = probe.summary(now=now0 + timedelta(hours=24))
    assert summary["total"] == 1
    assert summary["responded"] == 1
    assert summary["rate"] == 1.0
    assert summary["pending"] == 0
    state = json.loads(probe.state_path.read_text(encoding="utf-8"))
    assert state["resolved"][0]["reason"] == "edited"
    assert state["resolved"][0]["delay_hours"] == 12.0


def test_no_response_expires_after_48h(memory_tree, make_note):
    """满 48h 无变化 → 未响应（expired）；未满窗不结案。"""
    path = make_note(memory_tree, "due.md", "内容", idle_days=20)
    note_id = memory_tree._find_entry_id(path)
    probe = ResponseProbe(memory_tree)
    now0 = datetime.now().astimezone()
    probe.register([_item(note_id, "due.md")], now=now0)

    assert probe.check_pending(now=now0 + timedelta(hours=47))["resolved"] == 0
    result = probe.check_pending(now=now0 + timedelta(hours=49))

    assert result == {"resolved": 1, "responded": 0}
    state = json.loads(probe.state_path.read_text(encoding="utf-8"))
    assert state["resolved"][0]["reason"] == "expired"
    assert state["resolved"][0]["responded"] is False


def test_removed_file_counts_responded(memory_tree, make_note):
    """观察期内文件消失（被 purge）→ 响应（removed）。"""
    path = make_note(memory_tree, "due.md", "内容", idle_days=20)
    note_id = memory_tree._find_entry_id(path)
    probe = ResponseProbe(memory_tree)
    probe.register([_item(note_id, "due.md")])

    path.unlink()
    result = probe.check_pending()

    assert result == {"resolved": 1, "responded": 1}
    state = json.loads(probe.state_path.read_text(encoding="utf-8"))
    assert state["resolved"][0]["reason"] == "removed"


def test_repush_supersedes_old_observation(memory_tree, make_note):
    """未结案时被再次推送 → 旧观测按未响应（superseded）结案并重计时。"""
    path = make_note(memory_tree, "due.md", "内容", idle_days=20)
    note_id = memory_tree._find_entry_id(path)
    probe = ResponseProbe(memory_tree)
    now0 = datetime.now().astimezone()
    probe.register([_item(note_id, "due.md")], now=now0)

    probe.register([_item(note_id, "due.md")], now=now0 + timedelta(days=3))

    state = json.loads(probe.state_path.read_text(encoding="utf-8"))
    assert state["resolved"][0]["reason"] == "superseded"
    assert state["resolved"][0]["responded"] is False
    assert note_id in state["pending"]
    assert state["pending"][note_id]["pushed_at"] > state["resolved"][0][
        "pushed_at"
    ]


def test_summary_last7_filter(memory_tree, make_note):
    """近 7 天统计只含 7 天内的结案观测。"""
    path_a = make_note(memory_tree, "a.md", "内容", idle_days=20)
    path_b = make_note(memory_tree, "b.md", "内容", idle_days=20)
    probe = ResponseProbe(memory_tree)
    now0 = datetime.now().astimezone()
    probe.register(
        [_item(memory_tree._find_entry_id(path_a), "a.md")], now=now0
    )
    probe.check_pending(now=now0 + timedelta(hours=49))  # a 结案于 ~2 天后
    probe.register(
        [_item(memory_tree._find_entry_id(path_b), "b.md")],
        now=now0 + timedelta(days=7),
    )
    probe.check_pending(now=now0 + timedelta(days=10))  # b 结案于 10 天后

    summary = probe.summary(now=now0 + timedelta(days=10))

    assert summary["total"] == 2
    assert summary["last7_total"] == 1  # 只有 b 的结案在近 7 天内
    assert summary["last7_rate"] == 0.0


def test_summary_empty(memory_tree):
    """无结案观测：rate 为 None，不除零。"""
    summary = ResponseProbe(memory_tree).summary()

    assert summary["total"] == 0
    assert summary["rate"] is None
    assert summary["pending"] == 0


def test_corrupt_state_tolerated(memory_tree, make_note):
    """状态文件损坏 → 从空态重来，不崩溃。"""
    path = make_note(memory_tree, "due.md", "内容", idle_days=20)
    (memory_tree.state_dir / "response_probe.json").write_text(
        "not-json{", encoding="utf-8"
    )
    probe = ResponseProbe(memory_tree)

    assert probe.summary()["total"] == 0
    probe.register([_item(memory_tree._find_entry_id(path), "due.md")])
    assert probe.summary()["pending"] == 1


def test_probe_never_touches_notes(memory_tree, make_note):
    """register + check_pending 全程不改笔记内容与 mtime。"""
    path = make_note(memory_tree, "due.md", "内容", idle_days=20)
    before_bytes = path.read_bytes()
    before_mtime = path.stat().st_mtime_ns
    probe = ResponseProbe(memory_tree)

    probe.register([_item(memory_tree._find_entry_id(path), "due.md")])
    probe.check_pending()

    assert path.read_bytes() == before_bytes
    assert path.stat().st_mtime_ns == before_mtime
