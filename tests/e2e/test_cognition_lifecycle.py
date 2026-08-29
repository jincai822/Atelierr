"""认知生命周期端到端测试：COG-CHALLENGE-01..05（验收 §4.4）。

覆盖挑战提案无副作用、三种处理结果、获批修订的审计历史、
证伪/归档/继任的保留语义与 question 回答约束。
"""

from __future__ import annotations

import pytest

from scripts.memory.cognition import (
    ApprovalRecord,
    CognitionError,
    CognitionManager,
    EvidenceRef,
)

APPROVAL = ApprovalRecord(action="test", reason="测试批准")
CHALLENGE_EVIDENCE = (
    EvidenceRef(kind="manual", relation="challenges", note="新基准显示相反结论"),
)


@pytest.fixture
def manager(tmp_path):
    """临时 $OV 布局下的 CognitionManager。"""
    return CognitionManager(tmp_path, state_dir=tmp_path / "state")


@pytest.fixture
def belief(manager):
    """一条 active 的 belief（确信度 0.8）。"""
    return manager.create_entry(
        entry_type="belief",
        title="asyncio 更适合 I/O",
        statement="在 I/O 密集场景 asyncio 优于线程池。",
        status="active",
        certainty=0.8,
        approval=APPROVAL,
    )


def _challenge(manager: CognitionManager, entry_id: str, certainty=0.4):
    """发起一条标准挑战提案。"""
    return manager.propose_challenge(
        entry_id,
        evidence=CHALLENGE_EVIDENCE,
        rationale="出现反例",
        proposed_certainty=certainty,
    )


def test_challenge_proposal_does_not_mutate_entry(manager, belief):
    """COG-CHALLENGE-01：challenge proposal 批准前不改变 cognition。"""
    before_bytes = belief.path.read_bytes()
    before_mtime = belief.path.stat().st_mtime_ns
    proposal = _challenge(manager, belief.id)
    assert belief.path.read_bytes() == before_bytes
    assert belief.path.stat().st_mtime_ns == before_mtime
    assert proposal.status == "pending"
    assert manager.get_entry(belief.id).revision == 1


def test_all_challenge_resolutions_record_reason(manager, belief):
    """COG-CHALLENGE-02：reject/defer/accept 都记录理由与处理结果。"""
    p1 = _challenge(manager, belief.id)
    unchanged = manager.resolve_challenge(
        p1.id,
        resolution="reject",
        certainty=None,
        status=None,
        rationale="证据不充分",
        approval=APPROVAL,
    )
    assert unchanged.revision == 1  # reject 不动条目

    p2 = _challenge(manager, belief.id)
    deferred = manager.resolve_challenge(
        p2.id,
        resolution="defer",
        certainty=None,
        status="questioned",
        rationale="需要更多数据",
        approval=APPROVAL,
    )
    assert deferred.status == "questioned" and deferred.revision == 2

    p3 = _challenge(manager, belief.id)
    accepted = manager.resolve_challenge(
        p3.id,
        resolution="accept",
        certainty=0.4,
        status=None,
        rationale="接受反例",
        approval=APPROVAL,
    )
    assert accepted.certainty == 0.4 and accepted.revision == 3

    data = manager._load_proposals()
    for pid, resolution, reason in (
        (p1.id, "reject", "证据不充分"),
        (p2.id, "defer", "需要更多数据"),
        (p3.id, "accept", "接受反例"),
    ):
        assert data[pid]["status"] == "resolved"
        assert data[pid]["resolution"] == resolution
        assert data[pid]["decision_reason"] == reason


def test_accepted_challenge_updates_revision_history(manager, belief):
    """COG-CHALLENGE-02：accept 递增 revision、刷新 updated、追加证据与历史。"""
    proposal = _challenge(manager, belief.id)
    updated = manager.resolve_challenge(
        proposal.id,
        resolution="accept",
        certainty=0.4,
        status=None,
        rationale="接受反例",
        approval=ApprovalRecord(action="challenge-accept", reason="接受反例"),
    )
    assert updated.revision == belief.revision + 1
    assert updated.updated >= belief.updated
    assert len(updated.evidence) == len(belief.evidence) + 1
    assert updated.evidence[-1].relation == "challenges"
    assert "修订历史" in updated.content
    assert "0.8000 → 0.4000" in updated.content
    assert "接受反例" in updated.content
    assert updated.certainty_updated_at >= belief.certainty_updated_at


def test_refutation_never_deletes_or_moves_entry(manager, belief):
    """COG-CHALLENGE-03：refuted 条目不删除、不移动，可显式查询。"""
    refuted = manager.reassess_entry(
        belief.id,
        evidence=CHALLENGE_EVIDENCE,
        certainty=0.1,
        status="refuted",
        rationale="被新证据证伪",
        approval=APPROVAL,
    )
    assert refuted.path == belief.path
    assert refuted.path.exists()
    assert belief.id not in [e.id for e in manager.list_entries()]
    assert [e.id for e in manager.list_entries(status="refuted")] == [belief.id]
    assert belief.id in [e.id for e in manager.list_entries(include_inactive=True)]
    assert manager.get_entry(belief.id).status == "refuted"


def test_material_revision_creates_successor(manager, belief):
    """COG-CHALLENGE-04：实质修订创建 successor 并建立 supersedes 关系。"""
    successor = manager.supersede_entry(
        belief.id,
        replacement_statement="asyncio 只在单核 I/O 密集场景优于线程池。",
        replacement_certainty=0.65,
        rationale="适用范围收窄",
        approval=APPROVAL,
    )
    assert successor.id != belief.id
    assert successor.supersedes == belief.id
    assert successor.revision == 1
    assert successor.path.exists()
    old = manager.get_entry(belief.id)
    assert old.status == "superseded"
    assert old.revision == 2
    assert old.path.exists()  # 旧条目保留原路径
    assert successor.id in old.content  # 旧条目历史记录继任者
    assert manager.validate().ok
    # 默认列表只显示 successor；旧条目显式可查
    assert [e.id for e in manager.list_entries()] == [successor.id]


def test_question_answer_requires_summary_or_relation(manager):
    """COG-CHALLENGE-05：answered 必须记录答案摘要或关联 cognition id。"""
    question = manager.create_entry(
        entry_type="question",
        title="RapidOCR 够快吗",
        statement="RapidOCR 整页扫描能否稳定 <5s？",
        status="open",
        certainty=None,
        approval=APPROVAL,
    )
    with pytest.raises(CognitionError, match="答案摘要或关联"):
        manager.answer_question(
            question.id, answer="", related_entries=(), approval=APPROVAL
        )
    answered = manager.answer_question(
        question.id,
        answer="实测 0.77s，可以。",
        related_entries=(),
        approval=APPROVAL,
    )
    assert answered.status == "answered"
    assert answered.revision == 2
    assert "## 答案" in answered.content
    assert "实测 0.77s" in answered.content

    # 关联条目路径：相关 id 必须存在
    other = manager.create_entry(
        entry_type="question",
        title="q2",
        statement="另一个问题？",
        status="open",
        certainty=None,
        approval=APPROVAL,
    )
    with pytest.raises(KeyError):
        manager.answer_question(
            other.id,
            answer="",
            related_entries=("cog_missing",),
            approval=APPROVAL,
        )
