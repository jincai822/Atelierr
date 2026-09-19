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
    """search：走 CLI 子进程（2026-09-19 改，进程内调用泄漏 anyio 线程）
    并把 stdout JSON 归一化为 title/rel_path/score/snippet。"""
    import json

    calls = {}

    def _fake_cli(args, *, input_text=None, timeout):
        calls["args"] = args
        return json.dumps(
            {
                "results": [
                    {
                        "title": "内核稳定",
                        "permalink": "atelierr/抖音/抖音-内核稳定",
                        "score": 1.5,
                        "matched_chunk": "……内核稳定……",
                    }
                ]
            }
        )

    monkeypatch.setattr(bridge, "_run_cli", _fake_cli)

    hits = bridge.search("内核", limit=5, note_types=["Excerpt"], tags=["B站"])

    args = calls["args"]
    assert args[:2] == ["tool", "search-notes"]
    assert "--project" in args and args[args.index("--project") + 1] == "atelierr"
    assert "--page-size" in args and args[args.index("--page-size") + 1] == "5"
    assert "--type" in args and args[args.index("--type") + 1] == "Excerpt"
    assert "--tag" in args and args[args.index("--tag") + 1] == "B站"
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
    """CLI 返回非 JSON（错误文本）时抛 RuntimeError（调用方据此降级）。"""
    monkeypatch.setattr(
        bridge, "_run_cli", lambda args, *, input_text=None, timeout: "project not found"
    )
    import pytest

    with pytest.raises(RuntimeError, match="project not found"):
        bridge.search("x")


def test_run_cli_nonzero_exit_raises(monkeypatch):
    """_run_cli：子进程非零退出抛 RuntimeError（带 stderr 尾部）。"""
    import subprocess

    def _boom(cmd, **kwargs):
        return subprocess.CompletedProcess(cmd, 1, "", "boom: db locked")

    monkeypatch.setattr(bridge.subprocess, "run", _boom)
    import pytest

    with pytest.raises(RuntimeError, match="db locked"):
        bridge._run_cli(["reindex"], timeout=1)


def test_semantic_search_fuses_confidence(memory_tree, make_note, monkeypatch):
    """semantic_search（方案三 P3）：bm 召回 × live confidence 融合排序。"""
    from scripts.memory.search import MemorySearcher

    make_note(memory_tree, filename="a.md", content="内核稳定的内容", idle_days=0)
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
