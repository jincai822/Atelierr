"""性能测试共享 fixture。"""
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
    """批量创建笔记的工厂（可选回拨 mtime）。"""

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
