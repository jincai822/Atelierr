"""记忆模块单元测试共享 fixture。"""
from __future__ import annotations

import os
import time
from typing import List, Optional

import pytest

from scripts.memory.core import MemoryTree


@pytest.fixture
def memory_tree(tmp_path):
    """临时目录下的 MemoryTree（笔记目录 + 显式 state_dir）。"""
    return MemoryTree(tmp_path / "memory", state_dir=tmp_path / "state")


@pytest.fixture
def make_note():
    """创建笔记并可（可选）回拨 mtime 的工厂。

    用法: make_note(tree, filename="x.md", content="...", idle_days=0,
    tags=None)。sidecar last_accessed 保持 None，让 mtime 成为主信号。
    """

    def _make(
        tree: MemoryTree,
        filename: str = "x.md",
        content: str = "这是内容",
        idle_days: int = 0,
        tags: Optional[List[str]] = None,
    ):
        path = tree.create_note(filename, content, tags=tags)
        if idle_days:
            old_ns = int((time.time() - idle_days * 86400) * 1e9)
            os.utime(path, ns=(old_ns, old_ns))
        return path

    return _make
