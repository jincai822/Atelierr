"""认知 × 记忆集成测试：COG-PROMOTION-01..05（验收 §4.3）。

覆盖 memory → cognition 提名的无副作用、人工批准、来源不变、
边界状态（pending_delete/trash）与 purge 依赖警告。
"""

from __future__ import annotations

import os
import shutil
import time
from pathlib import Path

import frontmatter
import pytest
from click.testing import CliRunner

from scripts.cli.memory_cli import MemoryCLI
from scripts.cognition import (
    ApprovalRecord,
    CognitionError,
    CognitionManager,
)
from scripts.memory.core import MemoryTree
from scripts.memory.decay import DecayManager

APPROVAL = ApprovalRecord(action="test", reason="测试批准")


@pytest.fixture
def tree(tmp_path):
    """临时目录下的 MemoryTree（笔记目录 + 显式 state_dir）。"""
    return MemoryTree(tmp_path / "memory", state_dir=tmp_path / "state")


@pytest.fixture
def manager(tmp_path):
    """与 tree 共享 $OV/state 的 CognitionManager。"""
    return CognitionManager(tmp_path, state_dir=tmp_path / "state")


def _memory_id(path: Path) -> str:
    """读取笔记 frontmatter 的稳定 id。"""
    return str(frontmatter.loads(path.read_text(encoding="utf-8")).metadata["id"])


def _nominate(manager: CognitionManager, memory_id: str):
    """标准提名（belief/active/0.6 建议值）。"""
    return manager.nominate_memory(
        memory_id,
        entry_type="belief",
        title="提名条目",
        statement="从记忆里提炼的原子陈述。",
        rationale="包含项目基准测试",
        proposed_status="active",
        proposed_certainty=0.6,
    )


def _mark_pending_delete(tree: MemoryTree, path: Path) -> None:
    """通过真实衰减把笔记置为 pending_delete（闲置 60 天）。"""
    old_ns = int((time.time() - 60 * 86400) * 1e9)
    os.utime(path, ns=(old_ns, old_ns))
    DecayManager(tree).run()
    assert tree.is_pending_delete(path)


def test_nomination_has_no_cognition_side_effect(tree, manager):
    """COG-PROMOTION-01：nominate 只创建 proposal，不创建/修改任何文件。"""
    note = tree.create_note("src.md", "来源内容")
    before_bytes = note.read_bytes()
    before_mtime = note.stat().st_mtime_ns

    proposal = _nominate(manager, _memory_id(note))

    assert list(manager.cognition_dir.glob("*.md")) == []
    assert note.read_bytes() == before_bytes
    assert note.stat().st_mtime_ns == before_mtime
    pending = manager.list_promotion_proposals()
    assert [p.id for p in pending] == [proposal.id]


def test_reference_threshold_never_auto_promotes(tree, manager):
    """COG-PROMOTION-01：高引用数/confidence/layer 不会自动创建 cognition。"""
    note = tree.create_note("hot.md", "高引用笔记")
    memory_id = _memory_id(note)
    index = tree._load_index()
    index[memory_id]["references"] = 10
    index[memory_id]["confidence"] = 0.99
    index[memory_id]["layer"] = "short-term"
    tree._save_index()
    DecayManager(tree).run()  # 衰减也不应触发任何升级
    assert list(manager.cognition_dir.glob("*.md")) == []
    assert manager.list_promotion_proposals() == []


def test_approval_creates_exactly_one_entry(tree, manager):
    """COG-PROMOTION-02：一次 approve 只创建一个 cognition；不可重复批准。"""
    note = tree.create_note("src.md", "来源内容")
    proposal = _nominate(manager, _memory_id(note))

    entry = manager.approve_promotion(
        proposal.id, status="active", certainty=0.7, approval=APPROVAL
    )
    files = list(manager.cognition_dir.glob("*.md"))
    assert len(files) == 1
    assert entry.origin["memory_id"] == _memory_id(note)
    assert entry.origin["memory_path"] == "src.md"
    assert entry.revision == 1
    with pytest.raises(CognitionError, match="已处理"):
        manager.approve_promotion(
            proposal.id, status="active", certainty=0.7, approval=APPROVAL
        )
    assert len(list(manager.cognition_dir.glob("*.md"))) == 1


def test_rejection_records_reason_without_mutation(tree, manager):
    """COG-PROMOTION-02：reject 记录理由，不创建 cognition、不改 memory。"""
    note = tree.create_note("src.md", "来源内容")
    before_bytes = note.read_bytes()
    proposal = _nominate(manager, _memory_id(note))

    manager.reject_promotion(proposal.id, reason="陈述不够原子", approval=APPROVAL)
    data = manager._load_proposals()[proposal.id]
    assert data["status"] == "rejected"
    assert data["decision_reason"] == "陈述不够原子"
    assert list(manager.cognition_dir.glob("*.md")) == []
    assert note.read_bytes() == before_bytes


def test_promotion_never_touches_source_memory(tree, manager, tmp_path):
    """COG-PROMOTION-03：approve 前后 memory 的 bytes/mtime/path/sidecar 不变。"""
    note = tree.create_note("src.md", "来源内容")
    sidecar_path = tree.state_dir / "index.json"
    snapshot = (
        note.read_bytes(),
        note.stat().st_mtime_ns,
        str(note),
        sidecar_path.read_bytes(),
    )
    proposal = _nominate(manager, _memory_id(note))
    manager.approve_promotion(
        proposal.id, status="active", certainty=0.7, approval=APPROVAL
    )
    assert (
        note.read_bytes(),
        note.stat().st_mtime_ns,
        str(note),
        sidecar_path.read_bytes(),
    ) == snapshot


def test_pending_delete_source_requires_warning(tree, manager):
    """COG-PROMOTION-04：pending_delete 来源的提名必须带 purge 风险警告。"""
    note = tree.create_note("stale.md", "闲置笔记")
    _mark_pending_delete(tree, note)
    proposal = _nominate(manager, _memory_id(note))
    assert proposal.warnings
    assert any(
        "pending_delete" in warning and "purge" in warning
        for warning in proposal.warnings
    )


def test_trash_source_must_be_restored(tree, manager):
    """COG-PROMOTION-04：回收站中的来源不能直接升级，必须先恢复。"""
    note = tree.create_note("gone.md", "待删笔记")
    memory_id = _memory_id(note)
    trash_dir = tree.state_dir / "trash"
    trash_dir.mkdir(parents=True, exist_ok=True)
    shutil.move(str(note), str(trash_dir / note.name))

    with pytest.raises(CognitionError, match="恢复"):
        _nominate(manager, memory_id)


def test_purge_review_reports_cognition_dependency(tree, manager, tmp_path):
    """COG-PROMOTION-05：review/purge 显示在研 cognition 的依赖警告。"""
    note = tree.create_note("dep.md", "被引用的来源")
    memory_id = _memory_id(note)
    proposal = _nominate(manager, memory_id)
    entry = manager.approve_promotion(
        proposal.id, status="active", certainty=0.7, approval=APPROVAL
    )

    _mark_pending_delete(tree, note)
    config = tmp_path / "memory.yaml"
    config.write_text(
        f"memory:\n  root: {tmp_path}/memory\n  state_dir: {tmp_path}/state\n",
        encoding="utf-8",
    )
    cli = MemoryCLI(config_path=str(config)).cli
    result = CliRunner().invoke(cli, ["review"])
    assert result.exit_code == 0, result.output
    assert entry.id in result.output
    assert "⚠" in result.output
    # 警告不自动阻止 purge、不改变 memory 状态
    assert tree.is_pending_delete(note)
