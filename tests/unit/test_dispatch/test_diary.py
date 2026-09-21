"""日记追加共享助手（dispatch/diary.py）单元测试。

覆盖：新结构建日记、纯追加、根目录旧位置兼容、多行缩进、source 口径。
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import frontmatter

from scripts.dispatch.diary import append_diary_line, resolve_diary_path
from scripts.utils.date_utils import local_timezone

NOW = datetime(2026, 9, 21, 7, 53, tzinfo=local_timezone())


def _diary_path(tree, day: str = "2026-09-21") -> Path:
    return Path(tree.notes_dir) / "daily-notes" / "2026" / "09" / f"{day}.md"


def test_append_creates_diary_in_daily_notes(memory_tree):
    """日记不存在：建于 daily-notes/YYYY/MM/，行带时间前缀。"""
    diary = append_diary_line(memory_tree, "第一件事", now=NOW)

    assert diary == _diary_path(memory_tree)
    post = frontmatter.loads(diary.read_text(encoding="utf-8"))
    assert post["source"] == "lark"  # 缺省口径（飞书先例）
    assert "- 07:53 第一件事" in post.content


def test_append_existing_diary_appends_line(memory_tree):
    """日记已存在：纯追加，不改 frontmatter，不建新文件。"""
    append_diary_line(memory_tree, "第一条", now=NOW)
    diary = append_diary_line(memory_tree, "第二条", now=NOW)

    content = diary.read_text(encoding="utf-8")
    assert content.count("- 07:53 第") == 2
    assert content.index("第一条") < content.index("第二条")


def test_append_legacy_root_diary_not_split(memory_tree):
    """根目录旧位置已有日记：续写同一本，不在新结构另建。"""
    legacy = memory_tree.create_note("2026-09-21.md", "- 06:00 早起\n", source="sync")

    diary = append_diary_line(memory_tree, "续写", now=NOW)

    assert diary == legacy
    assert "- 07:53 续写" in legacy.read_text(encoding="utf-8")
    assert not _diary_path(memory_tree).exists()


def test_append_multiline_indented(memory_tree):
    """多行消息：后续行缩进两格（与飞书先例同格式）。"""
    diary = append_diary_line(memory_tree, "首行\n次行", now=NOW)

    content = diary.read_text(encoding="utf-8")
    assert "- 07:53 首行\n  次行" in content


def test_append_source_param_when_creating(memory_tree):
    """新建日记的 source 可指定（digest 指路行用 digest）。"""
    diary = append_diary_line(memory_tree, "指路", now=NOW, source="digest")

    post = frontmatter.loads(diary.read_text(encoding="utf-8"))
    assert post["source"] == "digest"


def test_resolve_prefers_new_structure(memory_tree):
    """两处都有日记：以新结构为准（兼容期只兜"旧有新无"）。"""
    memory_tree.create_note("2026-09-21.md", "旧位置\n", source="sync")
    new_diary = _diary_path(memory_tree)
    new_diary.parent.mkdir(parents=True, exist_ok=True)
    new_diary.write_text("---\ntitle: '2026-09-21'\n---\n\n新位置\n", encoding="utf-8")

    assert resolve_diary_path(memory_tree.notes_dir, "2026-09-21") == new_diary
