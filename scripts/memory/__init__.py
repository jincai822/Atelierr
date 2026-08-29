"""Atelierr 记忆模块（MVP1）。

架构 v1.2：平面存储 + sidecar 索引 + 无状态 confidence。
模块构成：core（MemoryTree）/ confidence（纯函数计算）/ decay（衰减与
报告）/ search（全文搜索）/ watcher（归一化与监听）/ scheduler（定时）。

主要类 re-export：
- MemoryTree / MemorySettings（core）
- ConfidenceCalculator（confidence）
- DecayManager（decay）
- MemorySearcher / Memory（search）
- MemoryWatcher（watcher）
- DecayScheduler（scheduler）
"""
from __future__ import annotations

from scripts.memory.confidence import ConfidenceCalculator
from scripts.memory.core import MemorySettings, MemoryTree
from scripts.memory.decay import DecayManager
from scripts.memory.scheduler import DecayScheduler
from scripts.memory.search import Memory, MemorySearcher
from scripts.memory.watcher import MemoryWatcher

__all__ = [
    "ConfidenceCalculator",
    "DecayManager",
    "DecayScheduler",
    "Memory",
    "MemorySearcher",
    "MemorySettings",
    "MemoryTree",
    "MemoryWatcher",
]
