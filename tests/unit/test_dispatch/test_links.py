"""链接自动分发单元测试（无真实网络与模型）。

LinkProcessor 以 processor_factory 注入假实现；笔记扫描、状态幂等、
失败熔断、pending_delete 跳过均为真实代码路径。
"""

from __future__ import annotations

import json

import frontmatter
import pytest

import scripts.dispatch.links as links_module
from scripts.dispatch.links import LinkDispatcher
from scripts.processors.base import ProcessResult

DOUYIN_URL = "https://v.douyin.com/eQOGBXJdlwQ/"


class _FakeLinkProcessor:
    """假链接处理器：记录调用，返回固定成功结果。"""

    calls = []
    fail_with = None

    def __init__(self):
        pass

    def process(self, url):
        type(self).calls.append(url)
        if type(self).fail_with:
            return ProcessResult(success=False, error=type(self).fail_with)
        return ProcessResult(
            success=True,
            text="转写全文",
            markdown="# 视频标题\n\n## 转写全文\n\n你好",
            confidence=0.9,
            metadata={"video_id": "vid123", "segments": 1},
        )


@pytest.fixture(autouse=True)
def _reset_fake():
    """每个用例重置假处理器的调用记录与失败开关。"""
    _FakeLinkProcessor.calls = []
    _FakeLinkProcessor.fail_with = None
    yield


def _dispatcher(tree):
    return LinkDispatcher(tree, processor_factory=_FakeLinkProcessor)


def test_processes_douyin_link(memory_tree):
    """含抖音链接的笔记 → 自动建带"待确认"标签的 douyin-<id>.md。"""
    memory_tree.create_note("daily.md", f"今天看到 {DOUYIN_URL} 不错", source="test")

    report = _dispatcher(memory_tree).run()

    assert report["found"] == 1
    assert report["created"] == ["douyin-vid123.md"]
    created = memory_tree.notes_dir / "douyin-vid123.md"
    assert created.exists()
    post = frontmatter.loads(created.read_text(encoding="utf-8"))
    assert post["tags"] == ["待确认", "抖音"]
    assert post["source"] == "link"
    assert "## 转写全文" in post.content
    # 源笔记不被改写
    assert memory_tree.read_note(memory_tree.notes_dir / "daily.md").startswith("今天看到")
    state = json.loads((memory_tree.state_dir / "processed_links.json").read_text())
    assert state[DOUYIN_URL]["status"] == "done"


def test_idempotent_second_run(memory_tree):
    """同一链接第二轮扫描跳过，不重复建笔记。"""
    memory_tree.create_note("daily.md", f"链接 {DOUYIN_URL}", source="test")
    dispatcher = _dispatcher(memory_tree)
    dispatcher.run()

    report = dispatcher.run()

    assert report["created"] == []
    assert report["skipped"] == 1
    assert len(_FakeLinkProcessor.calls) == 1


def test_no_links_noop(memory_tree):
    """无链接笔记 → 什么都不做。"""
    memory_tree.create_note("plain.md", "没有链接的内容", source="test")

    report = _dispatcher(memory_tree).run()

    assert report["found"] == 0
    assert report["created"] == []


def test_pending_delete_skipped(memory_tree, make_note):
    """pending_delete 笔记里的链接不处理。"""
    make_note(memory_tree, filename="old.md", content=f"旧链接 {DOUYIN_URL}", idle_days=60)
    from scripts.memory.decay import DecayManager

    DecayManager(memory_tree).run()
    assert memory_tree.is_pending_delete(memory_tree.notes_dir / "old.md")

    report = _dispatcher(memory_tree).run()

    assert report["found"] == 0
    assert _FakeLinkProcessor.calls == []


def test_failure_retries_then_circuit_breaks(memory_tree):
    """失败重试：3 次后熔断，第 4 轮不再调用处理器。"""
    _FakeLinkProcessor.fail_with = "视频下载失败: 403"
    memory_tree.create_note("daily.md", f"链接 {DOUYIN_URL}", source="test")
    dispatcher = _dispatcher(memory_tree)

    for _ in range(3):
        report = dispatcher.run()
        assert report["created"] == []
        assert len(report["failed"]) == 1

    state = json.loads((memory_tree.state_dir / "processed_links.json").read_text())
    assert state[DOUYIN_URL]["attempts"] == 3
    assert state[DOUYIN_URL]["status"] == "failed"

    report = dispatcher.run()
    assert report["skipped"] == 1
    assert len(_FakeLinkProcessor.calls) == 3


def test_dry_run_creates_nothing(memory_tree):
    """dry-run 只报告：不建笔记、不写状态、不调处理器。"""
    memory_tree.create_note("daily.md", f"链接 {DOUYIN_URL}", source="test")

    report = _dispatcher(memory_tree).run(dry_run=True)

    assert report["found"] == 1
    assert report["created"] == []
    assert _FakeLinkProcessor.calls == []
    assert not (memory_tree.state_dir / "processed_links.json").exists()


def test_duplicate_note_tolerated(memory_tree):
    """状态丢失后重跑：同名笔记已存在时不抛异常，标记 done。"""
    memory_tree.create_note("daily.md", f"链接 {DOUYIN_URL}", source="test")
    memory_tree.create_note("douyin-vid123.md", "已存在的产出", source="link")

    report = _dispatcher(memory_tree).run()

    assert report["created"] == ["douyin-vid123.md"]
    state = json.loads((memory_tree.state_dir / "processed_links.json").read_text())
    assert state[DOUYIN_URL]["status"] == "done"


def test_cli_links_command(memory_tree, tmp_path, monkeypatch):
    """CLI 层：--config 指定配置，成功 exit 0。"""
    monkeypatch.setattr(links_module, "LinkProcessor", _FakeLinkProcessor)
    memory_tree.create_note("daily.md", f"链接 {DOUYIN_URL}", source="test")
    config = tmp_path / "memory.yaml"
    config.write_text(
        f"memory:\n  root: {memory_tree.notes_dir}\n"
        f"  state_dir: {memory_tree.state_dir}\n",
        encoding="utf-8",
    )
    from scripts.cli.dispatch_cli import DispatchCLI

    code = DispatchCLI(config_path=str(config)).main(["links"])

    assert code == 0
    assert (memory_tree.notes_dir / "douyin-vid123.md").exists()
