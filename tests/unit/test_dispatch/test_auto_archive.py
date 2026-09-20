"""放权自动归档（auto_archive）与中图法→领域映射（CLC_TO_DOMAIN）测试。

2026-09-21 原教旨改造第 4 条：归档一级目录从「平台」改为「领域」，
机器产出的新笔记产出即归档，不再逐条人工审批。
"""

from __future__ import annotations

from scripts.dispatch.archive import (
    HANDWRITTEN_ARCHIVE_DIR,
    auto_archive,
    derive_archive_dir,
    _clc_domain,
)


class _FakePost:
    def __init__(self, tags):
        self.metadata = {"tags": tags}


def test_clc_domain_prefix_fallback():
    """前缀逐级回退：TP 直接命中 career；TN 回退 T→work；B/R→health。"""
    assert _clc_domain("TP391-自然语言处理") == "career"
    assert _clc_domain("TN3-无线电") == "work"
    assert _clc_domain("U46-汽车工程") == "work"
    assert _clc_domain("B84-心理学") == "health"
    assert _clc_domain("R16-保健·运动") == "health"
    assert _clc_domain("F830-金融") == "finance"
    assert _clc_domain("I267-散文") == "personal"
    assert _clc_domain("Z89-文摘") == "personal"
    assert _clc_domain("无中图法") is None


def test_derive_archive_dir_domain_rules():
    """derive：第一个中图法标签定领域；无中图法 → (None, None)。"""
    assert derive_archive_dir(_FakePost(["待确认", "抖音", "B84-心理学"])) == (
        "health",
        None,
    )
    assert derive_archive_dir(_FakePost(["待确认", "书籍", "TP391-NLP"])) == (
        "career",
        None,
    )
    assert derive_archive_dir(_FakePost(["待确认", "抖音"])) == (None, None)


def test_auto_archive_moves_and_strips(memory_tree):
    """放权主路径：产出即归档进领域目录，「待确认」摘除。"""
    memory_tree.create_note(
        "douyin-psy.md",
        "---\nsource: link\ntags: [待确认, 抖音, B84-心理学]\n---\n正文\n",
        inbox=True,
    )
    domain = auto_archive(memory_tree, "douyin-psy.md")
    assert domain == "health"
    moved = memory_tree.notes_dir / "health" / "douyin-psy.md"
    assert moved.is_file()
    assert "待确认" not in moved.read_text(encoding="utf-8")


def test_auto_archive_fallback_personal(memory_tree):
    """无中图法标签：兜底 personal/（HANDWRITTEN_ARCHIVE_DIR）。"""
    memory_tree.create_note(
        "速记.md", "---\nsource: link\ntags: [待确认]\n---\n一句话\n", inbox=True
    )
    domain = auto_archive(memory_tree, "速记.md")
    assert domain == HANDWRITTEN_ARCHIVE_DIR == "personal"
    assert (memory_tree.notes_dir / "personal" / "速记.md").is_file()


def test_auto_archive_failure_returns_none_and_stays(memory_tree):
    """归档失败（目标重名）：返回 None，笔记留 inbox 带「待确认」（人工兜底）。"""
    memory_tree.create_note(
        "douyin-x.md", "---\nsource: link\ntags: [待确认, 抖音]\n---\n正文\n",
        inbox=True,
    )
    blocker = memory_tree.notes_dir / "personal" / "douyin-x.md"
    blocker.parent.mkdir(parents=True)
    blocker.write_text("占位", encoding="utf-8")

    domain = auto_archive(memory_tree, "douyin-x.md")
    assert domain is None
    assert (memory_tree.inbox_dir / "douyin-x.md").is_file()
    assert blocker.read_text(encoding="utf-8") == "占位"  # 绝不覆盖
