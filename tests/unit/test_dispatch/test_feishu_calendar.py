"""飞书日历事件单元测试（lark SDK 全部打桩，无真实网络）。"""

from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest

import scripts.dispatch.feishu_calendar as cal_module
import scripts.dispatch.task_sync as task_sync_module
from scripts.dispatch.feishu_calendar import (
    create_all_day_event,
    ensure_calendar,
)


@pytest.fixture
def state_dir(tmp_path):
    path = tmp_path / "state"
    path.mkdir()
    return path


def _fake_lark(monkeypatch, client):
    """换假 lark：cal 模块自身的引用与 task_sync._client 的引用都要换。"""
    fake_lark = MagicMock()
    fake_lark.Client.builder.return_value.app_id.return_value.app_secret.return_value.build.return_value = (
        client
    )
    monkeypatch.setattr(cal_module, "_import_lark", lambda: fake_lark)
    monkeypatch.setattr(task_sync_module, "_import_lark", lambda: fake_lark)
    return fake_lark


def _creds(monkeypatch):
    monkeypatch.setenv("FEISHU_APP_ID", "cli_x")
    monkeypatch.setenv("FEISHU_APP_SECRET", "secret")


def test_ensure_calendar_creates_and_shares(state_dir, monkeypatch):
    """首次：建日历 → 登记 id → 已知 open_id 时加 ACL。"""
    _creds(monkeypatch)
    monkeypatch.setenv("FEISHU_USER_ID", "ou_me")
    client = MagicMock()
    client.calendar.v4.calendar.create.return_value.success.return_value = True
    client.calendar.v4.calendar.create.return_value.data.calendar.calendar_id = "cal-1"
    client.calendar.v4.calendar_acl.create.return_value.success.return_value = True
    _fake_lark(monkeypatch, client)

    assert ensure_calendar(state_dir) == "cal-1"
    client.calendar.v4.calendar_acl.create.assert_called_once()
    saved = json.loads(
        (state_dir / "feishu_calendar.json").read_text(encoding="utf-8")
    )
    assert saved["calendar_id"] == "cal-1"
    # 幂等：第二次不重建
    client.calendar.v4.calendar.create.reset_mock()
    assert ensure_calendar(state_dir) == "cal-1"
    client.calendar.v4.calendar.create.assert_not_called()


def test_ensure_calendar_without_open_id_still_works(state_dir, monkeypatch):
    """未知用户身份：日历照建照登记，只跳过 ACL（日志提示）。"""
    _creds(monkeypatch)
    monkeypatch.delenv("FEISHU_USER_ID", raising=False)
    client = MagicMock()
    client.calendar.v4.calendar.create.return_value.success.return_value = True
    client.calendar.v4.calendar.create.return_value.data.calendar.calendar_id = "cal-2"
    _fake_lark(monkeypatch, client)

    assert ensure_calendar(state_dir) == "cal-2"
    client.calendar.v4.calendar_acl.create.assert_not_called()


def test_ensure_calendar_create_failure(state_dir, monkeypatch):
    """创建失败返回 None 且不登记。"""
    _creds(monkeypatch)
    client = MagicMock()
    client.calendar.v4.calendar.create.return_value.success.return_value = False
    _fake_lark(monkeypatch, client)

    assert ensure_calendar(state_dir) is None
    assert not (state_dir / "feishu_calendar.json").exists()


def test_create_all_day_event_success(state_dir, monkeypatch):
    """全天事件：起止同日；成功 True。"""
    _creds(monkeypatch)
    client = MagicMock()
    client.calendar.v4.calendar_event.create.return_value.success.return_value = True
    _fake_lark(monkeypatch, client)
    monkeypatch.setattr(cal_module, "ensure_calendar", lambda _sd: "cal-1")

    assert create_all_day_event(state_dir, "待办截止：交周报", "2026-09-12")
    client.calendar.v4.calendar_event.create.assert_called_once()


def test_create_all_day_event_without_calendar(state_dir, monkeypatch):
    """日历不可用（凭证/权限缺）：静默 False。"""
    _creds(monkeypatch)
    _fake_lark(monkeypatch, MagicMock())
    monkeypatch.setattr(cal_module, "ensure_calendar", lambda _sd: None)

    assert not create_all_day_event(state_dir, "x", "2026-09-12")


def test_create_all_day_event_missing_creds(state_dir, monkeypatch):
    """凭证缺失静默 False（绝不抛异常）。"""
    monkeypatch.delenv("FEISHU_APP_ID", raising=False)
    monkeypatch.delenv("FEISHU_APP_SECRET", raising=False)
    _fake_lark(monkeypatch, MagicMock())

    assert not create_all_day_event(state_dir, "x", "2026-09-12")
    assert not create_all_day_event(state_dir, "", "")


def test_monthly_purge_reminder_creates_calendar_event(memory_tree, monkeypatch):
    """每月 1 日清理提醒：发卡之外建全天日历事件（均打桩）。"""
    from datetime import datetime

    from scripts.cli.memory_cli import _monthly_purge_reminder

    monkeypatch.setattr(
        "scripts.dispatch.feishu.send_feishu_card", lambda card, chat_id=None: True
    )
    events = []
    monkeypatch.setattr(
        "scripts.dispatch.feishu_calendar.create_all_day_event",
        lambda state_dir, summary, date_str, description="": events.append(
            (summary, date_str)
        )
        or True,
    )

    ok = _monthly_purge_reminder(
        memory_tree, ["a.md", "b.md"], today=datetime(2026, 10, 1)
    )

    assert ok is True
    assert events == [("Atelierr 月度清理（2 条待删）", "2026-10-01")]


def test_ensure_calendar_reshares_when_identity_appears(state_dir, monkeypatch):
    """建日历时没认出你（未共享）；后来认出 → 下次调用自动补共享。"""
    _creds(monkeypatch)
    monkeypatch.delenv("FEISHU_USER_ID", raising=False)
    client = MagicMock()
    client.calendar.v4.calendar.create.return_value.success.return_value = True
    client.calendar.v4.calendar.create.return_value.data.calendar.calendar_id = "cal-9"
    client.calendar.v4.calendar_acl.create.return_value.success.return_value = True
    _fake_lark(monkeypatch, client)

    assert ensure_calendar(state_dir) == "cal-9"
    client.calendar.v4.calendar_acl.create.assert_not_called()
    saved = json.loads(
        (state_dir / "feishu_calendar.json").read_text(encoding="utf-8")
    )
    assert saved["shared"] is False

    monkeypatch.setenv("FEISHU_USER_ID", "ou_me")
    assert ensure_calendar(state_dir) == "cal-9"
    client.calendar.v4.calendar_acl.create.assert_called_once()
    saved = json.loads(
        (state_dir / "feishu_calendar.json").read_text(encoding="utf-8")
    )
    assert saved["shared"] is True
