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
    """前缀逐级回退：TP 直接命中 career；TN 回退 T→work；R→health。"""
    assert _clc_domain("TP391-自然语言处理") == "career"
    assert _clc_domain("TN3-无线电") == "work"
    assert _clc_domain("U46-汽车工程") == "work"
    assert _clc_domain("R16-保健·运动") == "health"
    assert _clc_domain("F830-金融") == "finance"
    assert _clc_domain("I267-散文") == "personal"
    assert _clc_domain("Z89-文摘") == "personal"
    assert _clc_domain("无中图法") is None


def test_clc_domain_philosophy_split_and_digit_fallback():
    """2026-09-22 方案 C：B 拆 philosophy；B84 心理学特例留 health，
    数字前缀逐级回退（B849→B84→B）。"""
    assert _clc_domain("B84-心理学") == "health"
    assert _clc_domain("B849-应用心理学") == "health"  # 数字回退命中 B84 特例
    assert _clc_domain("B82-伦理·价值观") == "philosophy"
    assert _clc_domain("B516-德国哲学") == "philosophy"
    assert _clc_domain("B-哲学") == "philosophy"


def test_clc_domain_full_letter_coverage():
    """2026-09-22 方案 C：中图法全字母覆盖，各有主题格子。"""
    assert _clc_domain("A8-邓小平理论") == "theory"
    assert _clc_domain("C93-管理·领导") == "society"
    assert _clc_domain("D9-法律") == "politics"
    assert _clc_domain("E0-军事理论") == "military"
    assert _clc_domain("H3-外语学习") == "language"
    assert _clc_domain("N49-科普") == "science"
    assert _clc_domain("O1-数学") == "math"
    assert _clc_domain("P1-天文学") == "earth"
    assert _clc_domain("Q-生物·进化") == "biology"
    assert _clc_domain("S-种植·宠物") == "agriculture"
    assert _clc_domain("V4-航天") == "aerospace"
    assert _clc_domain("X-环境·安全") == "environment"


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


def test_auto_archive_philosophy(memory_tree):
    """方案 C：B 类（B84 除外）→ philosophy/，目录按需创建。"""
    memory_tree.create_note(
        "xhs-why.md",
        "---\nsource: link\ntags: [待确认, 小红书, B82-伦理·价值观]\n---\n正文\n",
        inbox=True,
    )
    domain = auto_archive(memory_tree, "xhs-why.md")
    assert domain == "philosophy"
    moved = memory_tree.notes_dir / "philosophy" / "xhs-why.md"
    assert moved.is_file()
    assert "待确认" not in moved.read_text(encoding="utf-8")


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
