"""认知模块单元测试：COG-SCHEMA / COG-CERTAINTY / COG-INDEX / COG-API。

断言以 docs/ACCEPTANCE-CRITERIA.md v1.1 §4.1/4.2/4.5/4.8 与
docs/prd/COGNITION-SPEC.md v1.0 为准。
"""

from __future__ import annotations

import inspect
import json
import os
import re
import time
from datetime import datetime
from pathlib import Path

import frontmatter
import pytest

from scripts.cognition import (
    ApprovalRecord,
    CognitionEntry,
    CognitionError,
    CognitionManager,
    EvidenceRef,
    RevisionConflictError,
)

APPROVAL = ApprovalRecord(action="test", reason="测试批准")


@pytest.fixture
def manager(tmp_path):
    """临时 $OV 布局下的 CognitionManager（memory/ cognition/ state/）。"""
    return CognitionManager(tmp_path, state_dir=tmp_path / "state")


def _belief(mgr: CognitionManager, **kwargs) -> CognitionEntry:
    """创建一条合法 belief 的工厂（参数可覆写）。"""
    params = {
        "entry_type": "belief",
        "title": "测试信念",
        "statement": "共享可变状态需要同步边界。",
        "status": "active",
        "certainty": 0.8,
        "approval": APPROVAL,
    }
    params.update(kwargs)
    return mgr.create_entry(**params)


def _hand_file(mgr: CognitionManager, name: str, meta_overrides: dict) -> Path:
    """手工写一份 cognition 文件（默认合法 belief 元数据 + 覆写项）。"""
    now = datetime.now().astimezone().isoformat(timespec="seconds")
    meta = {
        "schema_version": 1,
        "id": f"cog_hand{int(time.time() * 1000) % 10**10:010d}{len(name):04d}",
        "title": "手工条目",
        "type": "belief",
        "statement": "手工陈述。",
        "status": "active",
        "certainty": 0.5,
        "certainty_updated_at": now,
        "certainty_source": "human_assessment",
        "created": now,
        "updated": now,
        "revision": 1,
        "tags": [],
        "origin": {"kind": "manual"},
        "evidence": [],
        "related": [],
        "supersedes": None,
    }
    meta.update(meta_overrides)
    path = mgr.cognition_dir / name
    path.write_text(
        frontmatter.dumps(frontmatter.Post("正文\n", **meta)), encoding="utf-8"
    )
    return path


# ---------------------------------------------------------------------
# COG-SCHEMA（验收 §4.1）
# ---------------------------------------------------------------------


def test_create_belief_in_flat_cognition_root(manager):
    """COG-SCHEMA-01：只创建在 $OV/cognition/ 根层，文件名 <slug>--<short-id>.md。"""
    entry = _belief(manager)
    assert entry.path.parent == manager.cognition_dir
    assert re.match(r"^.+--[0-9a-z]{8}\.md$", entry.path.name)
    assert entry.id.startswith("cog_")
    assert entry.path.exists()
    # 平面：cognition 目录下不得有子目录
    assert not any(p.is_dir() for p in manager.cognition_dir.iterdir())


def test_id_stable_when_title_type_or_status_changes(manager):
    """COG-SCHEMA-01：标题/状态变化不改变 id，也不重命名文件。"""
    entry = _belief(manager)
    original_id, original_name = entry.id, entry.path.name
    updated = manager.reassess_entry(
        entry.id,
        evidence=[],
        certainty=0.6,
        status="questioned",
        rationale="复核",
        approval=APPROVAL,
    )
    assert updated.id == original_id
    assert updated.path.name == original_name
    # 手工改标题后身份仍来自 frontmatter id
    post = frontmatter.loads(updated.path.read_text(encoding="utf-8"))
    post.metadata["title"] = "改过标题"
    updated.path.write_text(frontmatter.dumps(post), encoding="utf-8")
    reloaded = manager.get_entry(original_id)
    assert reloaded.id == original_id
    assert reloaded.path.name == original_name
    assert reloaded.title == "改过标题"


def test_required_common_frontmatter_fields(manager):
    """COG-SCHEMA-02：公共字段齐全，时间为带时区 ISO 8601。"""
    entry = _belief(manager, tags=["python", "并发"])
    meta = frontmatter.loads(entry.path.read_text(encoding="utf-8")).metadata
    for key in (
        "schema_version",
        "id",
        "title",
        "type",
        "statement",
        "status",
        "created",
        "updated",
        "revision",
        "tags",
        "origin",
        "evidence",
        "related",
        "supersedes",
    ):
        assert key in meta, f"缺少字段 {key}"
    for key in ("created", "updated", "certainty_updated_at"):
        dt = datetime.fromisoformat(str(meta[key]))
        assert dt.tzinfo is not None, f"{key} 必须带时区"
    assert meta["tags"] == ["python", "并发"]
    assert meta["origin"] == {"kind": "manual"}


def test_question_rejects_certainty_fields(manager):
    """COG-SCHEMA-03：question 省略 certainty 三字段；传入即拒绝。"""
    with pytest.raises(ValueError, match="question"):
        manager.create_entry(
            entry_type="question",
            title="问题",
            statement="这是真的吗？",
            status="open",
            certainty=0.5,
            approval=APPROVAL,
        )
    entry = manager.create_entry(
        entry_type="question",
        title="问题",
        statement="这是真的吗？",
        status="open",
        certainty=None,
        approval=APPROVAL,
    )
    meta = frontmatter.loads(entry.path.read_text(encoding="utf-8")).metadata
    assert "certainty" not in meta
    assert "certainty_updated_at" not in meta
    assert "certainty_source" not in meta


def test_certainty_source_enum(manager):
    """COG-SCHEMA-03：certainty_source 只允许两个人工来源枚举。"""
    with pytest.raises(ValueError, match="certainty_source"):
        ApprovalRecord(action="a", reason="r", source="auto_scoring")
    path = _hand_file(
        manager, "bad-source--aaaa0001.md", {"certainty_source": "bayesian"}
    )
    report = manager.validate()
    assert any("certainty_source" in error for error in report.errors)
    with pytest.raises(CognitionError):
        manager.get_entry(
            frontmatter.loads(path.read_text(encoding="utf-8")).metadata["id"]
        )


def test_type_specific_status_validation(manager):
    """COG-SCHEMA-04：未知或跨类型 status/type 拒绝写入。"""
    with pytest.raises(ValueError, match="status"):
        _belief(manager, status="testing")  # testing 属 hypothesis
    with pytest.raises(ValueError, match="type"):
        manager.create_entry(
            entry_type="decision",
            title="d",
            statement="s",
            status="active",
            certainty=0.5,
            approval=APPROVAL,
        )
    path = _hand_file(
        manager, "cross--bbbb0002.md", {"type": "hypothesis", "status": "active"}
    )
    assert any(path.name in error for error in manager.validate().errors)


def test_memory_evidence_field_rules(manager):
    """COG-SCHEMA-05：memory 证据必填 id/path，禁止 url/accessed_at。"""
    with pytest.raises(CognitionError):
        EvidenceRef(kind="memory", relation="supports", path="x.md").validate()
    with pytest.raises(CognitionError):
        EvidenceRef(kind="memory", relation="supports", id="m1").validate()
    with pytest.raises(CognitionError, match="禁止"):
        EvidenceRef(
            kind="memory",
            relation="supports",
            id="m1",
            path="x.md",
            url="https://example.com",
        ).validate()
    ref = EvidenceRef(kind="memory", relation="supports", id="m1", path="x.md")
    assert ref.validate() is ref


def test_url_evidence_field_rules(manager):
    """COG-SCHEMA-05：url 证据必须绝对 http/https + 带时区 accessed_at。"""
    with pytest.raises(CognitionError, match="绝对"):
        EvidenceRef(
            kind="url",
            relation="context",
            url="example.com/a",
            accessed_at="2026-08-29T10:00:00+08:00",
        ).validate()
    with pytest.raises(CognitionError, match="禁止"):
        EvidenceRef(
            kind="url",
            relation="context",
            url="https://example.com",
            accessed_at="2026-08-29T10:00:00+08:00",
            id="m1",
        ).validate()
    with pytest.raises(CognitionError):
        EvidenceRef(
            kind="url",
            relation="context",
            url="https://example.com",
            accessed_at="2026-08-29T10:00:00",  # naive 拒绝
        ).validate()
    EvidenceRef(
        kind="url",
        relation="context",
        url="https://example.com",
        accessed_at="2026-08-29T10:00:00+08:00",
    ).validate()


def test_manual_evidence_field_rules(manager):
    """COG-SCHEMA-05：manual 证据必须非空 note，禁止一切来源字段。"""
    with pytest.raises(CognitionError):
        EvidenceRef(kind="manual", relation="context", note="").validate()
    with pytest.raises(CognitionError, match="禁止"):
        EvidenceRef(
            kind="manual", relation="context", note="人工观察", id="m1"
        ).validate()
    EvidenceRef(kind="manual", relation="context", note="人工观察").validate()


def test_unknown_schema_version_is_rejected(manager):
    """COG-SCHEMA-06：未知 schema_version 拒绝读取/校验通过。"""
    path = _hand_file(manager, "v2--cccc0003.md", {"schema_version": 2})
    report = manager.validate()
    assert any("schema_version" in error for error in report.errors)
    with pytest.raises(CognitionError, match="schema_version"):
        manager.get_entry(
            frontmatter.loads(path.read_text(encoding="utf-8")).metadata["id"]
        )


def test_duplicate_id_is_rejected(manager):
    """COG-SCHEMA-06：两个文件同 id 必须被 validate 报告。"""
    entry = _belief(manager)
    text = entry.path.read_text(encoding="utf-8")
    clone = manager.cognition_dir / f"clone--{entry.id[-8:].lower()}.md"
    clone.write_text(text, encoding="utf-8")
    assert any("重复 id" in error for error in manager.validate().errors)


def test_supersedes_cycle_is_rejected(manager):
    """COG-SCHEMA-06：supersedes 环必须被 validate 报告。"""
    first = _belief(manager, title="甲")
    second = _belief(manager, title="乙")
    for entry, target in ((first, second.id), (second, first.id)):
        post = frontmatter.loads(entry.path.read_text(encoding="utf-8"))
        post.metadata["supersedes"] = target
        entry.path.write_text(frontmatter.dumps(post), encoding="utf-8")
    assert any("环" in error for error in manager.validate().errors)


# ---------------------------------------------------------------------
# COG-CERTAINTY（验收 §4.2）
# ---------------------------------------------------------------------


def test_cognition_rejects_confidence_field(manager):
    """COG-CERTAINTY-01：cognition 文件出现 confidence 字段必须拒绝。"""
    path = _hand_file(manager, "conf--dddd0004.md", {"confidence": 0.9})
    assert any("confidence" in error for error in manager.validate().errors)
    with pytest.raises(CognitionError, match="confidence"):
        manager.get_entry(
            frontmatter.loads(path.read_text(encoding="utf-8")).metadata["id"]
        )
    assert (
        "confidence" not in inspect.signature(CognitionManager.create_entry).parameters
    )


def test_cognition_certainty_does_not_decay_with_time(manager):
    """COG-CERTAINTY-02：时间经过（90 天）不改变 certainty。"""
    entry = _belief(manager, certainty=0.8)
    old_ns = int((time.time() - 90 * 86400) * 1e9)
    os.utime(entry.path, ns=(old_ns, old_ns))
    reloaded = manager.get_entry(entry.id)
    assert reloaded.certainty == 0.8
    assert reloaded.certainty_updated_at == entry.certainty_updated_at


def test_update_requires_approval_record(manager):
    """COG-CERTAINTY-03：所有语义变更必须携带显式 ApprovalRecord。"""
    with pytest.raises(ValueError, match="ApprovalRecord"):
        _belief(manager, approval=None)
    entry = _belief(manager)
    with pytest.raises(ValueError, match="ApprovalRecord"):
        manager.reassess_entry(
            entry.id,
            evidence=[],
            certainty=0.5,
            status="active",
            rationale="r",
            approval=None,
        )
    with pytest.raises(ValueError, match="ApprovalRecord"):
        manager.archive_entry(entry.id, reason="r", approval=None)
    assert manager.get_entry(entry.id).revision == 1  # 未被改动


def test_certainty_rounding_and_range(manager):
    """COG-CERTAINTY-04：范围 [0,1] 校验在前，写入最多四位小数。"""
    assert _belief(manager, certainty=0.123456).certainty == 0.1235
    assert _belief(manager, title="零", certainty=0.0).certainty == 0.0
    assert _belief(manager, title="一", certainty=1.0).certainty == 1.0
    with pytest.raises(ValueError, match=r"\[0\.0, 1\.0\]"):
        _belief(manager, title="超界", certainty=1.5)
    with pytest.raises(ValueError, match=r"\[0\.0, 1\.0\]"):
        _belief(manager, title="负数", certainty=-0.01)


def test_memory_decay_does_not_change_certainty(manager, tmp_path):
    """COG-CERTAINTY-05：memory 衰减运行不触碰 cognition 文件与数值。"""
    from scripts.memory.core import MemoryTree
    from scripts.memory.decay import DecayManager

    tree = MemoryTree(tmp_path / "memory", state_dir=tmp_path / "state")
    note = tree.create_note("idle.md", "闲置笔记")
    old_ns = int((time.time() - 60 * 86400) * 1e9)
    os.utime(note, ns=(old_ns, old_ns))

    entry = _belief(manager, certainty=0.8)
    before_bytes = entry.path.read_bytes()
    report = DecayManager(tree).run()
    assert report["pending"]  # 衰减确实生效了
    assert entry.path.read_bytes() == before_bytes
    assert manager.get_entry(entry.id).certainty == 0.8


# ---------------------------------------------------------------------
# COG-INDEX（验收 §4.5）
# ---------------------------------------------------------------------


def test_index_can_be_rebuilt_from_markdown(manager):
    """COG-INDEX-01/02：删除派生索引后可从 Markdown 完整重建。"""
    first = _belief(manager, title="甲", certainty=0.7)
    second = _belief(manager, title="乙", certainty=0.9, status="draft")
    manager.index_path.unlink()
    report = manager.rebuild_index()
    assert report.rebuilt == 2 and not report.errors
    index = json.loads(manager.index_path.read_text(encoding="utf-8"))
    assert index[first.id]["status"] == "active"
    assert index[first.id]["certainty"] == 0.7
    assert index[second.id]["status"] == "draft"
    assert set(index[first.id]) == {
        "path",
        "type",
        "status",
        "certainty",
        "updated",
        "memory_id",
        "related",
        "supersedes",
    }


def test_markdown_wins_over_stale_index(manager):
    """COG-INDEX-02：索引与 Markdown 冲突时 Markdown 胜出，reindex 收敛。"""
    entry = _belief(manager)
    post = frontmatter.loads(entry.path.read_text(encoding="utf-8"))
    post.metadata["status"] = "questioned"
    entry.path.write_text(frontmatter.dumps(post), encoding="utf-8")

    assert manager.get_entry(entry.id).status == "questioned"  # Markdown 胜出
    report = manager.validate()
    assert any(entry.id in item for item in report.index_drift)
    manager.rebuild_index()
    assert not manager.validate().index_drift


def test_broken_proposals_do_not_affect_approved_entries(manager):
    """COG-INDEX-03：proposals.json 损坏隔离为 .bak，已批准条目不受影响。"""
    entry = _belief(manager)
    manager.proposals_path.write_text("{broken json", encoding="utf-8")
    assert manager.list_promotion_proposals() == []
    assert manager.proposals_path.with_name("proposals.json.bak").exists()
    assert manager.get_entry(entry.id).certainty == 0.8
    assert manager.validate().ok


def test_corrupt_entry_is_reported_without_rewrite(manager):
    """COG-INDEX-04：损坏文件被报告，绝不覆写或猜测性修复。"""
    bad = manager.cognition_dir / "broken--eeee0005.md"
    bad.write_text("---\n: bad: [unclosed\n---\n正文\n", encoding="utf-8")
    before = bad.read_bytes()
    report = manager.validate()
    assert any("broken--eeee0005.md" in error for error in report.errors)
    assert not report.ok
    assert bad.read_bytes() == before
    manager.rebuild_index()  # 重建也不得修复该文件
    assert bad.read_bytes() == before


def test_revision_conflict_prevents_lost_update(manager, tmp_path):
    """COG-INDEX-04：revision 冲突检测阻止丢失更新。"""
    entry = _belief(manager)
    other = CognitionManager(tmp_path, state_dir=tmp_path / "state")
    other.reassess_entry(
        entry.id,
        evidence=[],
        certainty=0.7,
        status="questioned",
        rationale="另一进程获批修改",
        approval=APPROVAL,
    )
    with pytest.raises(RevisionConflictError):
        manager.reassess_entry(
            entry.id,
            evidence=[],
            certainty=0.5,
            status="active",
            rationale="基于过期视图",
            approval=APPROVAL,
        )
    # 重新读取后可正常获批写入
    manager.get_entry(entry.id)
    updated = manager.reassess_entry(
        entry.id,
        evidence=[],
        certainty=0.5,
        status="active",
        rationale="重新读取后",
        approval=APPROVAL,
    )
    assert updated.revision == 3


# ---------------------------------------------------------------------
# COG-API（验收 §4.8）
# ---------------------------------------------------------------------


def test_public_api_contract(manager):
    """COG-API-01：公共 API 与 COGNITION-SPEC §6.2 签名一致。"""
    expected = {
        "create_entry": {
            "entry_type",
            "title",
            "statement",
            "status",
            "certainty",
            "tags",
            "evidence",
            "approval",
        },
        "get_entry": {"entry_id"},
        "list_entries": {"entry_type", "status", "include_inactive"},
        "nominate_memory": {
            "memory_id",
            "entry_type",
            "title",
            "statement",
            "rationale",
            "proposed_status",
            "proposed_certainty",
        },
        "list_promotion_proposals": {"status"},
        "approve_promotion": {"proposal_id", "status", "certainty", "approval"},
        "reject_promotion": {"proposal_id", "reason", "approval"},
        "propose_challenge": {
            "entry_id",
            "evidence",
            "rationale",
            "proposed_certainty",
            "proposed_status",
        },
        "resolve_challenge": {
            "proposal_id",
            "resolution",
            "certainty",
            "status",
            "rationale",
            "approval",
        },
        "reassess_entry": {
            "entry_id",
            "evidence",
            "certainty",
            "status",
            "rationale",
            "approval",
        },
        "answer_question": {"entry_id", "answer", "related_entries", "approval"},
        "supersede_entry": {
            "entry_id",
            "replacement_statement",
            "replacement_certainty",
            "rationale",
            "approval",
        },
        "archive_entry": {"entry_id", "reason", "approval"},
        "validate": set(),
        "rebuild_index": set(),
    }
    for name, params in expected.items():
        signature = inspect.signature(getattr(CognitionManager, name))
        actual = set(signature.parameters) - {"self"}
        assert params <= actual, f"{name} 缺少参数 {params - actual}"


def test_reads_are_side_effect_free(manager):
    """COG-API-02：读取方法不改变文件、mtime 或 proposal 状态。"""
    entry = _belief(manager)
    cognition_files = {
        path.name: (path.read_bytes(), path.stat().st_mtime_ns)
        for path in manager.cognition_dir.glob("*.md")
    }
    index_bytes = manager.index_path.read_bytes()
    assert not manager.proposals_path.exists()

    manager.get_entry(entry.id)
    manager.list_entries()
    manager.list_entries(include_inactive=True, status="active")
    manager.validate()
    manager.list_promotion_proposals()
    manager.memory_dependencies("nonexistent-memory")

    after = {
        path.name: (path.read_bytes(), path.stat().st_mtime_ns)
        for path in manager.cognition_dir.glob("*.md")
    }
    assert after == cognition_files
    assert manager.index_path.read_bytes() == index_bytes
    assert not manager.proposals_path.exists()


def test_no_delete_api(manager):
    """COG-API-03：无 delete_entry，无跨 confidence/certainty 的通用更新 API。"""
    assert not hasattr(CognitionManager, "delete_entry")
    assert not [name for name in dir(CognitionManager) if "delete" in name.lower()]
    # 所有接受数值的公开写入方法都要求 ApprovalRecord（不存在裸 float 更新）
    for name in ("create_entry", "reassess_entry", "approve_promotion"):
        params = inspect.signature(getattr(CognitionManager, name)).parameters
        assert "approval" in params
