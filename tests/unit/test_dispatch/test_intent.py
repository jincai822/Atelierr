"""自然语言意图分类（intent）单元测试：解析容错 + 分类纪律。"""

from __future__ import annotations

import json

import scripts.dispatch.intent as intent_module
from scripts.dispatch.intent import _parse, classify


class _FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


def _llm_payload(data) -> dict:
    return {"choices": [{"message": {"content": json.dumps(data, ensure_ascii=False)}}]}


def test_parse_tolerates_fence_and_prose():
    """剥围栏 + 抽大括号块；坏 JSON/未知意图返回 None。"""
    assert _parse('```json\n{"intent": "search", "query": "叔本华"}\n```') == {
        "intent": "search",
        "query": "叔本华",
    }
    assert _parse('好的，结果是 {"intent": "todos", "query": ""} 这样')["intent"] == "todos"
    assert _parse("不是 JSON") is None
    assert _parse('{"intent": "judgment", "query": "x"}') is None  # 未知意图
    assert _parse('{"foo": 1}') is None


def test_classify_search_with_query(monkeypatch):
    """听懂搜索意图：返回 intent + 关键词。"""
    monkeypatch.setenv("DEEPSEEK_API_KEY", "fake")
    monkeypatch.setattr(
        intent_module.httpx,
        "post",
        lambda *a, **k: _FakeResponse(_llm_payload({"intent": "search", "query": "叔本华"})),
    )
    assert classify("帮我找一下上次那个叔本华的视频") == {
        "intent": "search",
        "query": "叔本华",
    }


def test_classify_fallbacks(monkeypatch):
    """capture / 搜索无关键词 / 短文本 / 无 key / LLM 挂 → 一律 None（照旧记日记）。"""
    monkeypatch.setenv("DEEPSEEK_API_KEY", "fake")
    monkeypatch.setattr(
        intent_module.httpx,
        "post",
        lambda *a, **k: _FakeResponse(_llm_payload({"intent": "capture", "query": ""})),
    )
    assert classify("今天天气不错") is None  # capture

    monkeypatch.setattr(
        intent_module.httpx,
        "post",
        lambda *a, **k: _FakeResponse(_llm_payload({"intent": "search", "query": ""})),
    )
    assert classify("帮我找点东西") is None  # 搜索没关键词 = 没听懂

    assert classify("好的") is None  # 短文本不值得调用

    monkeypatch.delenv("DEEPSEEK_API_KEY")
    assert classify("帮我找一下叔本华") is None  # 无 key 退回

    monkeypatch.setenv("DEEPSEEK_API_KEY", "fake")

    def _boom(*a, **k):
        raise RuntimeError("network down")

    monkeypatch.setattr(intent_module.httpx, "post", _boom)
    assert classify("帮我找一下叔本华") is None  # 失败退回
