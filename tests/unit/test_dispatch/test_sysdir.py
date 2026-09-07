"""机器产物目录（系统/）写入助手单元测试。"""

from __future__ import annotations

import frontmatter
import pytest

from scripts.dispatch.sysdir import SYSTEM_DIRNAME, write_machine_note


def test_write_machine_note_defaults(memory_tree):
    """frontmatter 默认字段与 create_note 同源；落 系统/ 且不登记索引。"""
    rel = write_machine_note(
        memory_tree.notes_dir, "产物.md", "# 正文\n", source="digest", tags=["摘要"]
    )

    assert rel == f"{SYSTEM_DIRNAME}/产物.md"
    path = memory_tree.notes_dir / rel
    post = frontmatter.loads(path.read_text(encoding="utf-8"))
    assert post["id"] and post["created"]
    assert post["title"] == "产物"
    assert post["source"] == "digest"
    assert post["tags"] == ["摘要"]
    assert post.content.strip() == "# 正文"
    # 不登记 sidecar 索引（该目录不在记忆扫描域）
    assert all("产物" not in e["path"] for e in memory_tree._load_index().values())


def test_write_machine_note_preserves_own_frontmatter(memory_tree):
    """markdown 自带的 frontmatter 字段（如 undistilled）原样保留。"""
    markdown = "---\nundistilled:\n- \"[[x]]\"\n---\n\n正文\n"

    rel = write_machine_note(memory_tree.notes_dir, "m.md", markdown, source="digest")

    post = frontmatter.loads(
        (memory_tree.notes_dir / rel).read_text(encoding="utf-8")
    )
    assert post["undistilled"] == ["[[x]]"]


def test_write_machine_note_never_overwrites(memory_tree):
    """同名文件已存在：FileExistsError，绝不覆盖。"""
    write_machine_note(memory_tree.notes_dir, "m.md", "一", source="digest")
    with pytest.raises(FileExistsError):
        write_machine_note(memory_tree.notes_dir, "m.md", "二", source="digest")
    assert "一" in (memory_tree.notes_dir / SYSTEM_DIRNAME / "m.md").read_text(
        encoding="utf-8"
    )


def test_write_machine_note_rejects_bad_filename(memory_tree):
    """目录分量与非 .md 拒绝。"""
    with pytest.raises(ValueError):
        write_machine_note(memory_tree.notes_dir, "a/b.md", "x", source="digest")
    with pytest.raises(ValueError):
        write_machine_note(memory_tree.notes_dir, "b.txt", "x", source="digest")
