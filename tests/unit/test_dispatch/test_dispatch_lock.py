"""分发 CLI flock 互斥测试（无真实网络/扫描）。

场景：手动运行与 15 分钟定时班次撞在同一分钟——后到进程拿不到
state_dir/dispatch.lock 时应打印提示并以 0 退出，不做实际扫描；
links/media/todos/highlights 共享同一把锁，digest 等不加锁。
"""

from __future__ import annotations

import fcntl
import os
from datetime import datetime
from pathlib import Path

import pytest

import scripts.cli.dispatch_cli as cli_module
import scripts.dispatch.links as links_module
from scripts.cli.dispatch_cli import DispatchCLI
from scripts.processors.base import ProcessResult

DOUYIN_URL = "https://v.douyin.com/eQOGBXJdlwQ/"
SKIP_MESSAGE = "已有分发任务在运行，本次跳过"


class _FakeLinkProcessor:
    """假链接处理器：记录调用并返回成功（测试只关心是否被调用）。"""

    calls: list = []

    def __init__(self):
        pass

    def process(self, url):
        type(self).calls.append(url)
        return ProcessResult(
            success=True,
            text="转写全文",
            markdown="# 标题\n\n## 转写全文\n\n你好",
            confidence=0.9,
            metadata={"video_id": "vid123", "segments": 1},
        )


@pytest.fixture(autouse=True)
def _reset_fake():
    """每个用例重置假处理器的调用记录。"""
    _FakeLinkProcessor.calls = []
    yield


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


@pytest.fixture
def pushes(monkeypatch):
    """拦截 send_dispatch_notice（digest 用例防真实推送）。"""
    calls = []
    monkeypatch.setattr(
        cli_module, "send_dispatch_notice",
        lambda title, msg, **kwargs: calls.append((title, msg))
        or {"ntfy": True, "feishu": True},
    )
    return calls


def _hold_dispatch_lock(tree) -> int:
    """以本进程另一 fd 持有 state_dir/dispatch.lock（模拟并发班次）。

    flock 按 open file description 独立判定，同进程内第二个 fd 也会
    被该锁挡住，可真实模拟另一个进程持锁。
    """
    lock_path = Path(tree.state_dir) / "dispatch.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(lock_path, os.O_CREAT | os.O_RDWR)
    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    return fd


def test_links_skips_when_lock_held(cli, memory_tree, monkeypatch, capsys):
    """锁被其他班次占用：links 打印提示、退出码 0、不扫描不建笔记。"""
    monkeypatch.setattr(links_module, "LinkProcessor", _FakeLinkProcessor)
    memory_tree.create_note("daily.md", f"链接 {DOUYIN_URL}", source="test")
    fd = _hold_dispatch_lock(memory_tree)

    try:
        assert cli.main(["links"]) == 0
    finally:
        os.close(fd)

    assert SKIP_MESSAGE in capsys.readouterr().out
    assert _FakeLinkProcessor.calls == []
    assert not (memory_tree.notes_dir / "douyin-vid123.md").exists()


def test_links_shared_lock_blocks_media(cli, memory_tree, monkeypatch, capsys):
    """同一把锁跨子命令互斥：links 持锁时 media 也跳过。"""
    fd = _hold_dispatch_lock(memory_tree)

    try:
        assert cli.main(["media"]) == 0
    finally:
        os.close(fd)

    assert SKIP_MESSAGE in capsys.readouterr().out
    assert not list(memory_tree.notes_dir.glob("media-*.md"))


def test_links_runs_when_lock_free(cli, memory_tree, monkeypatch, capsys):
    """锁空闲：正常执行扫描并建笔记，不打印跳过提示。"""
    monkeypatch.setattr(links_module, "LinkProcessor", _FakeLinkProcessor)
    memory_tree.create_note("daily.md", f"链接 {DOUYIN_URL}", source="test")

    assert cli.main(["links"]) == 0

    assert _FakeLinkProcessor.calls == [DOUYIN_URL]
    assert (memory_tree.notes_dir / "douyin-vid123.md").exists()
    assert SKIP_MESSAGE not in capsys.readouterr().out


def test_lock_released_after_run_allows_next(cli, memory_tree, monkeypatch):
    """锁随 fd 关闭自动释放：持锁跳过后再跑同一命令可正常执行。"""
    monkeypatch.setattr(links_module, "LinkProcessor", _FakeLinkProcessor)
    memory_tree.create_note("daily.md", f"链接 {DOUYIN_URL}", source="test")
    fd = _hold_dispatch_lock(memory_tree)
    assert cli.main(["links"]) == 0
    os.close(fd)

    assert cli.main(["links"]) == 0

    assert len(_FakeLinkProcessor.calls) == 1
    assert (memory_tree.notes_dir / "douyin-vid123.md").exists()


def test_digest_not_locked(cli, memory_tree, monkeypatch, pushes, capsys):
    """digest 不加锁：分发锁被占时仍正常执行（feishu 等常驻同理）。"""
    fd = _hold_dispatch_lock(memory_tree)

    try:
        assert cli.main(["digest"]) == 0
    finally:
        os.close(fd)

    today = datetime.now().strftime("%Y-%m-%d")
    assert (memory_tree.notes_dir / "系统" / f"今日摘要-{today}.md").exists()
    assert SKIP_MESSAGE not in capsys.readouterr().out
    assert pushes
