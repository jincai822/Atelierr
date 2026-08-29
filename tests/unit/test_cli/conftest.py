"""test_cli 共享 fixture：保证处理器测试夹具存在。"""
from __future__ import annotations

from pathlib import Path

import pytest

from tools.generate_test_data import generate_all

#: tests/fixtures 目录（本文件位于 tests/unit/test_cli/，上三级是仓库根）
FIXTURES_DIR = Path(__file__).resolve().parents[3] / "tests" / "fixtures"


@pytest.fixture(scope="session", autouse=True)
def ensure_processor_fixtures() -> None:
    """session 级：幂等生成 tests/fixtures 下的测试夹具。"""
    generate_all(FIXTURES_DIR)


@pytest.fixture(scope="session")
def fixtures_dir() -> Path:
    """tests/fixtures 目录路径。"""
    return FIXTURES_DIR
