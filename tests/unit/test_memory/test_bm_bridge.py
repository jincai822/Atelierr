"""Basic Memory 桥接层（bm_bridge）单元测试：permalink 换算 + 调用归一化。"""

from __future__ import annotations

import scripts.memory.bm_bridge as bridge


def test_permalink_roundtrip():
    """permalink 与相对路径确定性互转（无映射表，2026-09-19 方案三 P2）。"""
    assert bridge.rel_to_permalink("飞书/feishu-x.md") == "atelierr/飞书/feishu-x"
    assert bridge.rel_to_permalink("主页.md") == "atelierr/主页"
    assert bridge.rel_to_permalink("a\\b.md") == "atelierr/a/b"
    assert bridge.permalink_to_rel("atelierr/飞书/feishu-x") == "飞书/feishu-x.md"
    assert bridge.permalink_to_rel("atelierr/主页") == "主页.md"
    assert bridge.permalink_to_rel("other/x") == "other/x.md"


def test_search_normalizes_hits(monkeypatch):
    """search：调 search_notes 并把结果归一化为 title/rel_path/score/snippet。"""
    calls = {}

    class _FakeTools:
        def search_notes(self, **kwargs):
            calls.update(kwargs)
            return {
                "results": [
                    {
                        "title": "内核稳定",
                        "permalink": "atelierr/抖音/抖音-内核稳定",
                        "score": 1.5,
                        "matched_chunk": "……内核稳定……",
                    }
                ]
            }

    monkeypatch.setattr(bridge, "_run", lambda coro: coro)
    monkeypatch.setattr(
        "basic_memory.mcp.tools.search_notes", _FakeTools().search_notes
    )

    hits = bridge.search("内核", limit=5, note_types=["Excerpt"], tags=["B站"])

    assert calls["project"] == "atelierr"
    assert calls["page_size"] == 5
    assert calls["note_types"] == ["Excerpt"]
    assert hits == [
        {
            "title": "内核稳定",
            "permalink": "atelierr/抖音/抖音-内核稳定",
            "rel_path": "抖音/抖音-内核稳定.md",
            "score": 1.5,
            "snippet": "……内核稳定……",
        }
    ]


def test_search_error_text_raises(monkeypatch):
    """search_notes 返回错误文本时抛 RuntimeError（调用方据此降级）。"""
    monkeypatch.setattr(bridge, "_run", lambda coro: coro)
    monkeypatch.setattr(
        "basic_memory.mcp.tools.search_notes", lambda **kwargs: "project not found"
    )
    import pytest

    with pytest.raises(RuntimeError, match="project not found"):
        bridge.search("x")


def test_semantic_search_fuses_confidence(memory_tree, make_note, monkeypatch):
    """semantic_search（方案三 P3）：bm 召回 × live confidence 融合排序。"""
    from scripts.memory.search import MemorySearcher

    note = make_note(memory_tree, filename="a.md", content="内核稳定的内容", idle_days=0)
    monkeypatch.setattr(
        "scripts.memory.bm_bridge.search",
        lambda query, limit: [
            {"title": "a", "permalink": "atelierr/a", "rel_path": "a.md", "score": 2.0, "snippet": "x"}
        ],
    )
    results = MemorySearcher(memory_tree).semantic_search("内核", limit=5)
    assert len(results) == 1
    assert results[0].path.name == "a.md"


def test_semantic_search_falls_back_on_bridge_failure(memory_tree, monkeypatch):
    """语义层失败/无召回 → 空列表（调用方退回全文，降级是设计的一部分）。"""
    from scripts.memory.search import MemorySearcher

    def _boom(query, limit):
        raise RuntimeError("basic-memory down")

    monkeypatch.setattr("scripts.memory.bm_bridge.search", _boom)
    assert MemorySearcher(memory_tree).semantic_search("x") == []

    monkeypatch.setattr("scripts.memory.bm_bridge.search", lambda query, limit: [])
    assert MemorySearcher(memory_tree).semantic_search("x") == []
