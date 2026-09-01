"""分发 CLI 推送规则单元测试（send_ntfy 全部 monkeypatch，无真实网络）。

推送规则：链接抓取失败才推；晨间摘要创建成功推三节计数；
常规处理成功一律不推（防"马后炮"噪音）。
"""

from __future__ import annotations

import os
import re
import time
from datetime import datetime, timedelta
from pathlib import Path

import pytest

import scripts.cli.dispatch_cli as cli_module
import scripts.dispatch.links as links_module
import scripts.dispatch.media as media_module
from scripts.cli.dispatch_cli import DispatchCLI
from scripts.processors.base import ProcessResult

DOUYIN_URL = "https://v.douyin.com/eQOGBXJdlwQ/"


class _FakeLinkProcessor:
    """假链接处理器：fail_with 置位时返回失败。"""

    fail_with = None

    def process(self, url):
        if type(self).fail_with:
            return ProcessResult(success=False, error=type(self).fail_with)
        return ProcessResult(
            success=True,
            text="转写全文",
            markdown="# 标题\n\n## 转写全文\n\n你好",
            confidence=0.9,
            metadata={"video_id": "vid123", "segments": 1},
        )


@pytest.fixture(autouse=True)
def _reset_fake():
    """每个用例重置假处理器失败开关。"""
    _FakeLinkProcessor.fail_with = None
    yield


@pytest.fixture
def pushes(monkeypatch):
    """拦截 send_ntfy，返回 [(title, message), ...] 调用记录。"""
    calls = []
    monkeypatch.setattr(
        cli_module, "send_ntfy", lambda title, msg: calls.append((title, msg)) or True
    )
    return calls


@pytest.fixture
def cli(memory_tree, tmp_path):
    """指向临时库的 DispatchCLI。"""
    config = tmp_path / "memory.yaml"
    config.write_text(
        f"memory:\n  root: {memory_tree.notes_dir}\n"
        f"  state_dir: {memory_tree.state_dir}\n",
        encoding="utf-8",
    )
    return DispatchCLI(config_path=str(config))


def test_links_failure_pushes(cli, memory_tree, pushes, monkeypatch):
    """抓取失败 → 推"Atelierr 抓取失败"（不推用户无从知晓）。"""
    monkeypatch.setattr(links_module, "LinkProcessor", _FakeLinkProcessor)
    _FakeLinkProcessor.fail_with = "视频下载失败: 403"
    memory_tree.create_note("daily.md", f"链接 {DOUYIN_URL}", source="test")

    assert cli.main(["links"]) == 0
    assert len(pushes) == 1
    title, message = pushes[0]
    assert title == "Atelierr 抓取失败"
    assert "1 条链接抓取失败" in message


def test_links_success_no_push(cli, memory_tree, pushes, monkeypatch):
    """抓取成功 → 不推（用户自己贴的链接，无需马后炮）。"""
    monkeypatch.setattr(links_module, "LinkProcessor", _FakeLinkProcessor)
    memory_tree.create_note("daily.md", f"链接 {DOUYIN_URL}", source="test")

    assert cli.main(["links"]) == 0
    assert (memory_tree.notes_dir / "douyin-vid123.md").exists()
    assert pushes == []


def test_todos_no_push(cli, memory_tree, pushes):
    """待办分发（显式通道直转，无需 LLM）→ 一律不推。"""
    memory_tree.create_note("plan.md", "- [ ] 明天交报告", source="test")

    assert cli.main(["todos"]) == 0
    assert list(memory_tree.notes_dir.glob("todo-*.md"))
    assert pushes == []


def _backdate_created(tree, filename: str, day: str) -> None:
    """把测试笔记 frontmatter 的 created 改为指定日期（YYYY-MM-DD）。"""
    path = tree.notes_dir / filename
    text = path.read_text(encoding="utf-8")
    text = re.sub(
        r"^created: .*$", f"created: '{day}T09:00:00+08:00'", text,
        count=1, flags=re.M,
    )
    path.write_text(text, encoding="utf-8")


def test_digest_pushes_counts(cli, memory_tree, pushes):
    """摘要创建成功 → 推三节计数。"""
    yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
    memory_tree.create_note("a.md", "待确认笔记", source="link", tags=["待确认"])
    memory_tree.create_note("b.md", "- [ ] 做事", source="todo", tags=["待办"])
    memory_tree.create_note("c.md", "普通笔记", source="test")
    _backdate_created(memory_tree, "c.md", yesterday)

    assert cli.main(["digest"]) == 0
    assert len(pushes) == 1
    title, message = pushes[0]
    assert title == "Atelierr 今日摘要"
    assert "待确认 1" in message
    assert "待办 1" in message
    assert "昨日新入库 1" in message


def test_digest_skipped_no_push(cli, memory_tree, pushes):
    """当天摘要已存在（幂等跳过）→ 不推。"""
    today = datetime.now().strftime("%Y-%m-%d")
    memory_tree.create_note(f"今日摘要-{today}.md", "已有摘要", source="digest")

    assert cli.main(["digest"]) == 0
    assert pushes == []


def test_digest_dry_run_no_push(cli, memory_tree, pushes):
    """digest dry-run：不建笔记也不推。"""
    memory_tree.create_note("a.md", "待确认笔记", source="link", tags=["待确认"])

    assert cli.main(["digest", "--dry-run"]) == 0
    assert pushes == []


class _FakeMediaProcessor:
    """假附件处理器：fail_with 置位时返回失败。"""

    fail_with = None

    def process(self, path):
        if type(self).fail_with:
            return ProcessResult(success=False, error=type(self).fail_with)
        return ProcessResult(
            success=True, text="识别文本", markdown="", confidence=0.9,
        )


def _add_attachment(tree, name="IMG_001.png"):
    """在 attachments/ 落一个假附件并回拨 mtime（避开 30s 守卫）。"""
    attach = Path(tree.notes_dir) / "attachments"
    attach.mkdir(parents=True, exist_ok=True)
    path = attach / name
    path.write_bytes(b"\x89PNG fake-bytes")
    old = time.time() - 60
    os.utime(path, (old, old))
    return path


def test_media_failure_pushes(cli, memory_tree, pushes, monkeypatch):
    """附件处理失败 → 推"Atelierr 处理失败"。"""
    monkeypatch.setattr(media_module, "ImageProcessor", _FakeMediaProcessor)
    _FakeMediaProcessor.fail_with = "OCR 失败: 引擎崩溃"
    _add_attachment(memory_tree)

    assert cli.main(["media"]) == 0
    assert len(pushes) == 1
    title, message = pushes[0]
    assert title == "Atelierr 处理失败"
    assert "1 个附件处理失败" in message


def test_media_success_no_push(cli, memory_tree, pushes, monkeypatch):
    """附件处理成功 → 不推。"""
    monkeypatch.setattr(media_module, "ImageProcessor", _FakeMediaProcessor)
    _FakeMediaProcessor.fail_with = None
    _add_attachment(memory_tree)

    assert cli.main(["media"]) == 0
    assert list(memory_tree.notes_dir.glob("media-*.md"))
    assert pushes == []
