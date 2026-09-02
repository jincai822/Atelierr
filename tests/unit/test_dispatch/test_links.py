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


XHS_URL = "https://xhslink.cn/o/2Vhl2blNpHM"


class _FakeXhsProcessor:
    """假小红书处理器：返回带 note_id 的成功结果。"""

    def process(self, url):
        return ProcessResult(
            success=True,
            text="正文",
            markdown="# 小红书标题\n\n## 笔记正文\n\n内容",
            confidence=1.0,
            metadata={"note_id": "n123", "platform": "xhs"},
        )


def test_processes_xhs_link(memory_tree):
    """含小红书链接的笔记 → 自动建带"待确认"标签的 xhs-<id>.md。"""
    memory_tree.create_note("daily.md", f"看看这个 {XHS_URL}", source="test")

    report = LinkDispatcher(memory_tree, processor_factory=_FakeXhsProcessor).run()

    assert report["found"] == 1
    assert report["created"] == ["xhs-n123.md"]
    created = memory_tree.notes_dir / "xhs-n123.md"
    assert created.exists()
    post = frontmatter.loads(created.read_text(encoding="utf-8"))
    assert post["tags"] == ["待确认", "小红书"]
    assert post["source"] == "link"
    # 源笔记不被改写
    assert memory_tree.read_note(memory_tree.notes_dir / "daily.md").startswith("看看这个")
    state = json.loads((memory_tree.state_dir / "processed_links.json").read_text())
    assert state[XHS_URL]["status"] == "done"


def test_mixed_platform_links(memory_tree):
    """抖音与小红书链接同一轮都能被收集处理。"""
    memory_tree.create_note(
        "daily.md", f"抖音 {DOUYIN_URL} 和小红书 {XHS_URL}", source="test"
    )

    class _MixedProcessor:
        def process(self, url):
            if "xhslink" in url:
                return ProcessResult(
                    success=True,
                    text="正文",
                    markdown="# t",
                    confidence=1.0,
                    metadata={"note_id": "n9"},
                )
            return ProcessResult(
                success=True,
                text="转写",
                markdown="# t",
                confidence=0.9,
                metadata={"video_id": "v9"},
            )

    report = LinkDispatcher(memory_tree, processor_factory=_MixedProcessor).run()

    assert sorted(report["created"]) == ["douyin-v9.md", "xhs-n9.md"]


def test_auto_note_links_not_recycled(memory_tree):
    """自动产出笔记（source: link）里的链接不回收——防自我循环回归。

    复现 2026-09-02 真实事故：小红书短链处理后，产出笔记来源行里的
    落地页 URL 与原短链字符串不同，被下一轮当成新链接重复下载转写。
    """
    memory_tree.create_note(
        "xhs-abc123.md",
        f"# 标题\n\n> 来源：小红书 @某人 {XHS_URL}\n\n正文",
        source="link",
        tags=["待确认", "小红书"],
    )

    report = _dispatcher(memory_tree).run()

    assert report["found"] == 0
    assert report["created"] == []
    # 人工笔记里的同一链接仍会被收集（跳过只针对自动产出）
    memory_tree.create_note("daily.md", f"再看一次 {XHS_URL}", source="test")
    report2 = _dispatcher(memory_tree).run()
    assert report2["found"] == 1
    assert report2["created"] == ["xhs-vid123.md"]
