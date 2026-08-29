"""Web 集成测试共享 fixture。"""
from __future__ import annotations

from pathlib import Path

import pytest

from scripts.memory.core import MemoryTree
from scripts.web.integration import FlatnotesIntegration
from tools.generate_test_data import generate_all


@pytest.fixture(scope="session", autouse=True)
def ensure_fixtures() -> None:
    """session 级：保证端到端测试夹具存在（幂等生成）。"""
    fixtures_dir = Path(__file__).resolve().parents[2] / "tests" / "fixtures"
    generate_all(fixtures_dir)


@pytest.fixture
def memory_tree(tmp_path):
    """临时目录下的 MemoryTree（笔记目录 + 显式 state_dir）。"""
    return MemoryTree(tmp_path / "memory", state_dir=tmp_path / "state")


@pytest.fixture
def integration(memory_tree):
    """FlatnotesIntegration 门面（共享平面目录 + 归一化）。"""
    return FlatnotesIntegration(memory_tree)
