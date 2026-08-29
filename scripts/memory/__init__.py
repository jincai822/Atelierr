"""Atelierr 记忆模块（MVP1 + Phase 5）。

架构 v1.3：平面存储 + sidecar 索引 + 无状态 confidence；Phase 5 认知模块
（COGNITION-SPEC v1.0：belief/question/hypothesis，certainty 确信度与
memory confidence 新鲜度字段级隔离）。
模块构成：core（MemoryTree）/ confidence（纯函数计算）/ decay（衰减与
报告）/ search（全文搜索）/ watcher（归一化与监听）/ scheduler（定时）/
cognition（认知生命周期与人工审批工作流）。

主要类 re-export：
- MemoryTree / MemorySettings（core）
- ConfidenceCalculator（confidence）
- DecayManager（decay）
- MemorySearcher / Memory（search）
- MemoryWatcher（watcher）
- DecayScheduler（scheduler）
- CognitionManager / CognitionEntry / EvidenceRef / ApprovalRecord（cognition）
"""

from __future__ import annotations

from scripts.memory.cognition import (
    ApprovalRecord,
    CognitionEntry,
    CognitionManager,
    EvidenceRef,
)
from scripts.memory.confidence import ConfidenceCalculator
from scripts.memory.core import MemorySettings, MemoryTree
from scripts.memory.decay import DecayManager
from scripts.memory.scheduler import DecayScheduler
from scripts.memory.search import Memory, MemorySearcher
from scripts.memory.watcher import MemoryWatcher

__all__ = [
    "ApprovalRecord",
    "CognitionEntry",
    "CognitionManager",
    "ConfidenceCalculator",
    "DecayManager",
    "DecayScheduler",
    "EvidenceRef",
    "Memory",
    "MemorySearcher",
    "MemorySettings",
    "MemoryTree",
    "MemoryWatcher",
]
