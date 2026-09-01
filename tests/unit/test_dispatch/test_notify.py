"""ntfy 推送单元测试（httpx.post 全部 monkeypatch，无真实网络）。"""

from __future__ import annotations

import scripts.dispatch.notify as notify_module
from scripts.dispatch.notify import send_ntfy


class _FakeResponse:
    def __init__(self, status_code=200):
        self.status_code = status_code


def test_send_success(monkeypatch):
    """配置齐全：POST 到 {url}/{topic}，带标题头，2xx 返回 True。"""
    calls = []
    monkeypatch.setattr(
        notify_module.httpx,
        "post",
        lambda url, **kwargs: calls.append((url, kwargs)) or _FakeResponse(),
    )
    cfg = {"ntfy_url": "https://ntfy.sh", "topic": "secret-topic"}

    assert send_ntfy("标题", "2 条新内容待确认", config=cfg) is True
    url, kwargs = calls[0]
    assert url == "https://ntfy.sh/secret-topic"
    # 中文标题按 RFC 2047 编码进头（HTTP 头只支持 latin-1）
    from email.header import decode_header

    decoded = decode_header(kwargs["headers"]["Title"])
    assert decoded[0][0].decode(decoded[0][1] or "ascii") == "标题"
    assert kwargs["content"].decode("utf-8") == "2 条新内容待确认"


def test_send_not_configured(monkeypatch):
    """未配置 topic/url：不发请求，返回 False。"""
    calls = []
    monkeypatch.setattr(
        notify_module.httpx, "post", lambda *a, **k: calls.append(1) or None
    )

    assert send_ntfy("t", "m", config={}) is False
    assert send_ntfy("t", "m", config={"ntfy_url": "", "topic": ""}) is False
    assert calls == []


def test_send_failure_tolerated(monkeypatch):
    """网络异常/非 2xx：返回 False，绝不抛异常。"""
    def _boom(*args, **kwargs):
        raise RuntimeError("network down")

    monkeypatch.setattr(notify_module.httpx, "post", _boom)
    cfg = {"ntfy_url": "https://ntfy.sh", "topic": "t"}
    assert send_ntfy("t", "m", config=cfg) is False

    monkeypatch.setattr(
        notify_module.httpx, "post", lambda *a, **k: _FakeResponse(500)
    )
    assert send_ntfy("t", "m", config=cfg) is False
