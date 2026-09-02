"""Atelierr 认知模块（Phase 5，独立包）。

COGNITION-SPEC v1.1：belief/question/hypothesis 生命周期与人工审批工作流；
certainty 确信度与 memory confidence 新鲜度字段级隔离。数据目录为
$OV/memory/wiki/cognition/（wiki 总库内的 cognition 房间，同库分间），
本包与 scripts/memory 解耦，仅复用其 generate_id 工具函数。

主要类 re-export：
- CognitionManager / CognitionEntry（条目与生命周期）
- EvidenceRef / ApprovalRecord / WritePlan / ChallengeResolution（工作流）
- CognitionError / RevisionConflictError（异常）
- COGNITION_TYPES / DEFAULT_STATUS / CognitionType（枚举与常量）
"""

from __future__ import annotations

from scripts.cognition.manager import (
    COGNITION_TYPES,
    DEFAULT_STATUS,
    ApprovalRecord,
    ChallengeResolution,
    CognitionEntry,
    CognitionError,
    CognitionManager,
    CognitionType,
    EvidenceRef,
    RevisionConflictError,
    WritePlan,
)

__all__ = [
    "COGNITION_TYPES",
    "DEFAULT_STATUS",
    "ApprovalRecord",
    "ChallengeResolution",
    "CognitionEntry",
    "CognitionError",
    "CognitionManager",
    "CognitionType",
    "EvidenceRef",
    "RevisionConflictError",
    "WritePlan",
]
