"""端到端测试共享 fixture。"""
from __future__ import annotations

import os
import time
from pathlib import Path

import pytest

from scripts.memory.core import MemoryTree


@pytest.fixture
def memory_tree(tmp_path):
    """临时目录下的 MemoryTree（笔记目录 + 显式 state_dir）。"""
    return MemoryTree(tmp_path / "memory", state_dir=tmp_path / "state")


@pytest.fixture
def memory_config(tmp_path):
    """指向临时目录的 memory.yaml 配置（含完整阈值字段）。"""
    config = tmp_path / "memory.yaml"
    config.write_text(
        f"memory:\n"
        f"  root: {tmp_path / 'memory'}\n"
        f"  state_dir: {tmp_path / 'state'}\n"
        f"  layers:\n"
        f"    short_term_min: 0.7\n"
        f"    mid_term_min: 0.4\n"
        f"  decay:\n"
        f"    rate: 0.95\n"
        f"    ref_coefficient: 0.2\n"
        f"    ref_cap: 10\n"
        f"    delete_threshold: 0.1\n",
        encoding="utf-8",
    )
    return config


def roll_mtime_back(path: Path, idle_days: int) -> None:
    """把文件 mtime 回拨 idle_days 天。"""
    old_ns = int((time.time() - idle_days * 86400) * 1e9)
    os.utime(path, ns=(old_ns, old_ns))
