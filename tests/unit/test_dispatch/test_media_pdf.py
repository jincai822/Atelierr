"""media 附件路由的 PDF 分支单元测试（划重点路由，无真实 LLM/PDF 引擎）。

PDF → HighlightsProcessor 路由、清单笔记格式（不带"待确认"）、
失败熔断、幂等均为真实代码路径，处理器以工厂注入假实现。
"""

from __future__ import annotations

import os
import time
from pathlib import Path

import frontmatter
import pytest

from scripts.dispatch.media import MediaDispatcher
from scripts.processors.base import ProcessResult


class _FakeHighlightsProcessor:
    """假划重点处理器：记录调用，返回固定清单结果。"""

    calls = []
    fail_with = None

    def process(self, path):
        type(self).calls.append(str(path))
        if type(self).fail_with:
            return ProcessResult(success=False, error=type(self).fail_with)
        return ProcessResult(
            success=True,
            markdown="# 划重点清单：测试书\n\n- [ ] **概念甲**（第 3 页）\n",
            metadata={"candidates": 1},
        )


@pytest.fixture(autouse=True)
def _reset_fake():
    _FakeHighlightsProcessor.calls = []
    _FakeHighlightsProcessor.fail_with = None
    yield


def _dispatcher(tree):
    return MediaDispatcher(tree, highlights_factory=_FakeHighlightsProcessor)


def _add_pdf(tree, name="测试书.pdf", age_seconds=60):
    attach = Path(tree.attachments_dir)
    attach.mkdir(parents=True, exist_ok=True)
    path = attach / name
    path.write_bytes(b"%PDF fake-bytes")
    old = time.time() - age_seconds
    os.utime(path, (old, old))
    return path


def test_pdf_routes_to_highlights(memory_tree):
    """PDF → 划重点清单笔记：source/tags 正确，不带"待确认"。"""
    _add_pdf(memory_tree)

    report = _dispatcher(memory_tree).run()

    assert report["found"] == 1
    assert len(report["created"]) == 1
    filename = report["created"][0]
    assert filename.startswith("系统/划重点-测试书-")  # 清单进机器产物区
    post = frontmatter.loads(
        (memory_tree.notes_dir / filename).read_text(encoding="utf-8")
    )
    assert post["source"] == "highlights"
    assert post["tags"] == ["划重点"]
    assert "待确认" not in post["tags"]
    assert "- [ ] **概念甲**（第 3 页）" in post.content
    assert len(_FakeHighlightsProcessor.calls) == 1


def test_pdf_failure_circuit_breaks(memory_tree):
    """PDF 处理连续失败：3 次熔断，第 4 轮不再调处理器。"""
    _FakeHighlightsProcessor.fail_with = "未设置 DEEPSEEK_API_KEY"
    _add_pdf(memory_tree)
    dispatcher = _dispatcher(memory_tree)

    for _ in range(3):
        report = dispatcher.run()
        assert len(report["failed"]) == 1

    assert not list(Path(memory_tree.notes_dir).rglob("划重点-*.md"))  # 根层与系统/ 都无
    dispatcher.run()
    assert len(_FakeHighlightsProcessor.calls) == 3


def test_pdf_idempotent_second_run(memory_tree):
    """同一 PDF 第二轮跳过，不重复建清单。"""
    _add_pdf(memory_tree)
    dispatcher = _dispatcher(memory_tree)
    dispatcher.run()

    report = dispatcher.run()

    assert report["created"] == []
    assert report["skipped"] == 1
    assert len(_FakeHighlightsProcessor.calls) == 1
