"""Web 集成测试共享 fixture。"""
from __future__ import annotations

import pytest

from scripts.memory.core import MemoryTree
from scripts.web.integration import FlatnotesIntegration


@pytest.fixture
def memory_tree(tmp_path):
    """临时目录下的 MemoryTree（笔记目录 + 显式 state_dir）。"""
    return MemoryTree(tmp_path / "memory", state_dir=tmp_path / "state")


@pytest.fixture
def integration(memory_tree):
    """FlatnotesIntegration 门面（共享平面目录 + 归一化）。"""
    return FlatnotesIntegration(memory_tree)
