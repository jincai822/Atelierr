"""认知模块容量正确性测试：COG-SCALE-01（验收 §4.7）。

10,000 条 cognition 下验证 list/reindex/validate 结果完整且无数据丢失，
并记录三项耗时与测试硬件（v1.1 暂不设硬性能时限，实测值供后续锁定
回归阈值参考）。
"""

from __future__ import annotations

import json
import platform
import time

import frontmatter
import pytest

from scripts.memory.cognition import CognitionManager

COUNT = 10_000


def _bulk_create(manager: CognitionManager, count: int) -> set:
    """直接批量写合法 cognition 文件（绕开逐条 index 写盘的 O(n²)）。"""
    now = "2026-08-29T12:00:00+08:00"
    expected_ids = set()
    for i in range(count):
        entry_id = f"cog_bulk{i:020d}"
        expected_ids.add(entry_id)
        meta = {
            "schema_version": 1,
            "id": entry_id,
            "title": f"批量条目 {i}",
            "type": "belief",
            "statement": f"第 {i} 条批量陈述。",
            "status": "active" if i % 2 == 0 else "draft",
            "certainty": round((i % 100) / 100, 4),
            "certainty_updated_at": now,
            "certainty_source": "human_assessment",
            "created": now,
            "updated": now,
            "revision": 1,
            "tags": ["bulk"],
            "origin": {"kind": "manual"},
            "evidence": [],
            "related": [],
            "supersedes": None,
        }
        path = manager.cognition_dir / f"bulk-{i:05d}--{i:08x}.md"
        path.write_text(
            frontmatter.dumps(frontmatter.Post("批量正文\n", **meta)),
            encoding="utf-8",
        )
    return expected_ids


@pytest.fixture
def manager(tmp_path):
    """临时 $OV 布局下的 CognitionManager。"""
    return CognitionManager(tmp_path, state_dir=tmp_path / "state")


def test_cognition_capacity_correctness_at_10000_entries(manager, capsys):
    """COG-SCALE-01：1 万条下 list/reindex/validate 完整无丢失。"""
    expected_ids = _bulk_create(manager, COUNT)

    start = time.perf_counter()
    entries = manager.list_entries(include_inactive=True)
    list_seconds = time.perf_counter() - start
    assert len(entries) == COUNT
    assert {entry.id for entry in entries} == expected_ids  # 无数据丢失

    start = time.perf_counter()
    index_report = manager.rebuild_index()
    reindex_seconds = time.perf_counter() - start
    assert index_report.scanned == COUNT
    assert index_report.rebuilt == COUNT
    assert not index_report.errors
    index = json.loads(manager.index_path.read_text(encoding="utf-8"))
    assert set(index) == expected_ids

    start = time.perf_counter()
    validation = manager.validate()
    validate_seconds = time.perf_counter() - start
    assert validation.checked == COUNT
    assert validation.ok, validation.errors[:5]

    cpu = platform.processor() or "unknown CPU"
    print(
        "\nCOG-SCALE-01 实测"
        f"（{platform.machine()} / {cpu}，Python {platform.python_version()}）：\n"
        f"  数据规模: {COUNT} 条 cognition\n"
        f"  list:    {list_seconds:.2f}s\n"
        f"  reindex: {reindex_seconds:.2f}s\n"
        f"  validate: {validate_seconds:.2f}s"
    )
    # 防死代码：capsys 仅确保输出被收集，不断言内容
    assert capsys is not None
