"""DecayManager 单元测试（验收 1.3 全部 5 条 + 扩展）。"""

from __future__ import annotations

import os
import time
from pathlib import Path

import frontmatter

from scripts.memory.decay import DecayManager


def test_decay_scan(memory_tree, make_note):
    """scan 返回分层统计报告（不写状态）。"""
    make_note(memory_tree)
    report = DecayManager(memory_tree).scan()
    assert "total_notes" in report
    assert "short_term" in report
    assert "mid_term" in report
    assert "long_term" in report
    assert report["total_notes"] == 1
    assert report["short_term"] == 1


def test_decay_relayer(memory_tree, make_note):
    """idle 10 天：重算后 conf≈0.6 → mid-term，文件仍在平面根层。"""
    note = make_note(memory_tree, idle_days=10)
    DecayManager(memory_tree).run()
    assert note in memory_tree.list_notes("mid-term")
    assert note.exists()


def test_decay_never_touches_files(memory_tree, make_note):
    """衰减前后笔记内容与 mtime 完全不变。"""
    note = make_note(memory_tree, idle_days=30)
    before = (note.read_bytes(), note.stat().st_mtime_ns)
    DecayManager(memory_tree).run()
    assert (note.read_bytes(), note.stat().st_mtime_ns) == before


def test_decay_dry_run(memory_tree, make_note):
    """dry-run：sidecar 未变（仍 short-term）、would_relayer>0、无报告文件。"""
    note = make_note(memory_tree, idle_days=10)
    report = DecayManager(memory_tree).run(dry_run=True)
    assert note in memory_tree.list_notes("short-term")
    assert report["would_relayer"] > 0
    assert report["relayered"] == 0
    assert not (memory_tree.state_dir / "reports").exists()


def test_pending_delete_is_mark_only(memory_tree, make_note):
    """conf < 0.1 只打标记，文件仍存在。"""
    note = make_note(memory_tree, idle_days=60)
    DecayManager(memory_tree).run()
    assert note.exists()
    assert memory_tree.is_pending_delete(note)


def test_backlinks_boost_confidence(memory_tree, make_note):
    """反链：B 引用 [[A-stem]] → A 的 references>=1 且同龄时比无引用者 conf 高。"""
    target = make_note(
        memory_tree, filename="asyncio.md", content="关于 asyncio 的笔记", idle_days=50
    )
    other = make_note(
        memory_tree, filename="other.md", content="普通笔记", idle_days=50
    )
    make_note(
        memory_tree,
        filename="reader.md",
        content="引用了 [[asyncio]] 的笔记",
        idle_days=0,
    )

    DecayManager(memory_tree).run()

    target_entry = memory_tree._entry(target)
    assert target_entry["references"] >= 1
    assert target_entry["confidence"] > memory_tree._entry(other)["confidence"]


def test_backlink_alias_and_heading(memory_tree, make_note):
    """[[target|alias]] 与 [[target#heading]] 按 target 部分匹配。"""
    target = make_note(memory_tree, filename="python.md", content="python 笔记")
    make_note(memory_tree, filename="l1.md", content="链接 [[python|教程]]")
    make_note(memory_tree, filename="l2.md", content="链接 [[python#性能]]")
    DecayManager(memory_tree).run()
    assert memory_tree._entry(target)["references"] == 2


def test_backlink_by_title(memory_tree, make_note):
    """按 frontmatter title 精确匹配。"""
    target = make_note(
        memory_tree, filename="titled.md", content="---\ntitle: 中文标题\n---\n正文"
    )
    make_note(memory_tree, filename="linker.md", content="引用 [[中文标题]]")
    DecayManager(memory_tree).run()
    assert memory_tree._entry(target)["references"] == 1


def test_report_file_generated(memory_tree, make_note):
    """报告文件生成且含"待删除"相关字样。"""
    make_note(memory_tree, idle_days=60)
    report = DecayManager(memory_tree).run()
    assert report["report_path"]
    report_path = Path(report["report_path"])
    assert report_path.exists()
    assert report_path.parent == memory_tree.state_dir / "reports"
    text = report_path.read_text(encoding="utf-8")
    assert "待删除" in text
    assert "pending_delete" in text
    assert "层级迁移" in text


def test_decay_skips_bare_md(memory_tree, make_note):
    """无 frontmatter 的裸 .md 跳过计入 skipped，不登记不写文件。"""
    make_note(memory_tree, filename="reg.md")
    bare = memory_tree.notes_dir / "bare.md"
    bare.write_text("没有 frontmatter 的裸文件", encoding="utf-8")
    report = DecayManager(memory_tree).run()
    assert str(bare) in report["skipped"]
    assert report["total_notes"] == 1
    assert memory_tree._entry(bare) is None


def test_decay_registers_frontmatter_only_note(memory_tree, make_note):
    """frontmatter 有 id 但 sidecar 无条目：允许纯 sidecar 登记后处理。"""
    make_note(memory_tree, filename="a.md")
    post = frontmatter.loads("---\ntitle: orphan\n---\n内容")
    post.metadata["id"] = "01J6" + "0" * 22
    orphan = memory_tree.notes_dir / "orphan.md"
    orphan.write_text(frontmatter.dumps(post), encoding="utf-8")

    report = DecayManager(memory_tree).run()
    assert report["total_notes"] == 2
    assert memory_tree._entry(orphan) is not None
    # 文件内容未被改写
    post_after = frontmatter.loads(orphan.read_text(encoding="utf-8"))
    assert post_after.metadata["id"] == "01J6" + "0" * 22


def test_decay_skips_system_notes(memory_tree, make_note):
    """source=system 的基础设施笔记（控制台等）：不衰减、不计数、不置待删。"""
    panel = memory_tree.create_note(
        "控制台.md", "面板", source="system", tags=["系统"]
    )
    old_ns = int((time.time() - 60 * 86400) * 1e9)
    os.utime(panel, ns=(old_ns, old_ns))
    make_note(memory_tree, "content.md", "内容", idle_days=60)

    report = DecayManager(memory_tree).run()

    assert report["total_notes"] == 1
    assert report["system"] == [str(panel)]
    entry = memory_tree._entry(panel)
    assert entry["pending_delete"] is False
    assert entry["confidence"] == 1.0
    scan = DecayManager(memory_tree).scan()
    assert scan["total_notes"] == 1
