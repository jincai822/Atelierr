"""安静时段硬闸单元测试（2026-09-19 脑科学建议③）。

23:00–07:00 主动推送一律静音；交互回执（respect_quiet=False）旁路。
"""

from __future__ import annotations

from datetime import datetime

import scripts.dispatch.feishu_io as feishu_io
from scripts.dispatch.feishu_io import quiet_hours_active, send_feishu, send_feishu_card


def test_quiet_hours_boundaries():
    """23:00–07:00 为安静时段；边界精确。"""
    assert quiet_hours_active(datetime(2026, 9, 19, 23, 0)) is True
    assert quiet_hours_active(datetime(2026, 9, 20, 2, 30)) is True
    assert quiet_hours_active(datetime(2026, 9, 20, 6, 59)) is True
    assert quiet_hours_active(datetime(2026, 9, 20, 7, 0)) is False
    assert quiet_hours_active(datetime(2026, 9, 19, 12, 0)) is False
    assert quiet_hours_active(datetime(2026, 9, 19, 22, 59)) is False


def _force_quiet(monkeypatch, active):
    monkeypatch.setattr(feishu_io, "quiet_hours_active", lambda now=None: active)


def _env(monkeypatch):
    monkeypatch.setenv("FEISHU_APP_ID", "cli_x")
    monkeypatch.setenv("FEISHU_APP_SECRET", "s")
    monkeypatch.setenv("FEISHU_CHAT_ID", "oc_x")


def test_proactive_push_muted_in_quiet_hours(monkeypatch):
    """安静时段：send_feishu / send_feishu_card 直接 False，不碰网络。"""
    _force_quiet(monkeypatch, True)
    _env(monkeypatch)

    def _boom():
        raise AssertionError("安静时段不应构造 client")

    monkeypatch.setattr(feishu_io, "_import_lark", _boom)
    assert send_feishu("晨报", "3 条待办") is False
    assert send_feishu_card({"header": {}, "elements": []}) is False


def test_interactive_bypass_reaches_network(monkeypatch):
    """交互回执（respect_quiet=False）：安静时段照样发（交互不是打扰）。"""
    _force_quiet(monkeypatch, True)
    _env(monkeypatch)
    sent = []
    monkeypatch.setattr(
        feishu_io, "_send", lambda client, target, msg_type, content: sent.append(msg_type) or "mid"
    )

    class _FakeLark:
        class Client:
            @staticmethod
            def builder():
                class _B:
                    def app_id(self, v):
                        return self

                    def app_secret(self, v):
                        return self

                    def build(self):
                        return object()

                return _B()

    monkeypatch.setattr(feishu_io, "_import_lark", lambda: _FakeLark)
    assert (
        send_feishu_card({"header": {}, "elements": []}, respect_quiet=False) is True
    )
    assert sent == ["interactive"]


def test_normal_hours_send_attempted(monkeypatch):
    """非安静时段：正常走发送路径。"""
    _force_quiet(monkeypatch, False)
    _env(monkeypatch)
    sent = []
    monkeypatch.setattr(
        feishu_io, "_send", lambda client, target, msg_type, content: sent.append(msg_type) or "mid"
    )

    class _FakeLark:
        class Client:
            @staticmethod
            def builder():
                class _B:
                    def app_id(self, v):
                        return self

                    def app_secret(self, v):
                        return self

                    def build(self):
                        return object()

                return _B()

    monkeypatch.setattr(feishu_io, "_import_lark", lambda: _FakeLark)
    assert send_feishu("晨报", "3 条待办") is True
    assert sent
