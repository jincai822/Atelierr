"""晨间摘要单元测试。

frontmatter 解析与分节为真实代码路径；无网络（摘要不联网）。
"""

from __future__ import annotations

import json
import re

import frontmatter

from scripts.dispatch.digest import DigestDispatcher


def _backdate_created(tree, filename: str, day: str) -> None:
    """把测试笔记 frontmatter 的 created 改为指定日期（YYYY-MM-DD）。"""
    path = tree.notes_dir / filename
    text = path.read_text(encoding="utf-8")
    text = re.sub(
        r"^created: .*$", f"created: '{day}T09:00:00+08:00'", text,
        count=1, flags=re.M,
    )
    path.write_text(text, encoding="utf-8")


def test_digest_created_with_sections(memory_tree):
    """摘要含三节；待确认/待办按标签归位；摘要自身不进列表。"""
    memory_tree.create_note("a.md", "待确认笔记", source="link", tags=["待确认", "抖音"])
    memory_tree.create_note("b.md", "- [ ] 做事", source="todo", tags=["待办", "待确认"])
    memory_tree.create_note("c.md", "- [ ] 已定", source="todo", tags=["待办"])
    memory_tree.create_note("d.md", "普通笔记", source="test")
    _backdate_created(memory_tree, "d.md", "2026-08-31")

    report = DigestDispatcher(memory_tree).run(today="2026-09-01")

    assert report["created"] == "今日摘要-2026-09-01.md"
    post = frontmatter.loads(
        (memory_tree.notes_dir / report["created"]).read_text(encoding="utf-8")
    )
    assert post["source"] == "digest"
    body = post.content
    assert "## ⏳ 待我确认（2）" in body
    assert "[[a]]" in body and "[[b]]" in body
    assert "## ✅ 待办进行中（2）" in body
    assert "[[c]]" in body
    assert "## 📥 昨日新入库（1）" in body
    assert "[[d]]" in body
    assert "今日摘要" not in body.split("昨日新入库")[1]  # 历史摘要不入列


def test_digest_idempotent_same_day(memory_tree):
    """当天已存在摘要：跳过，不重复建。"""
    dispatcher = DigestDispatcher(memory_tree)
    first = dispatcher.run(today="2026-09-01")

    second = dispatcher.run(today="2026-09-01")

    assert first["created"] == "今日摘要-2026-09-01.md"
    assert second["skipped"] is True
    assert second["created"] is None


def test_digest_dry_run(memory_tree):
    """dry-run：返回内容但不建笔记。"""
    memory_tree.create_note("a.md", "待确认笔记", source="test", tags=["待确认"])

    report = DigestDispatcher(memory_tree).run(dry_run=True, today="2026-09-01")

    assert report["created"] is None
    assert "[[a]]" in report["markdown"]
    assert not (memory_tree.notes_dir / "今日摘要-2026-09-01.md").exists()


def test_digest_empty_vault(memory_tree):
    """空库：四节都显示"无"，正常建。"""
    report = DigestDispatcher(memory_tree).run(today="2026-09-01")

    assert report["created"]
    assert report["markdown"].count("- 无") == 4


def test_digest_includes_resurface_section(memory_tree, make_note):
    """遗忘临界区笔记进"今日复习"节；摘要创建成功后写入冷却状态。"""
    make_note(memory_tree, "old.md", "旧笔记", idle_days=20)
    make_note(memory_tree, "fresh.md", "新笔记")

    report = DigestDispatcher(memory_tree).run(today="2026-09-01")

    assert report["counts"]["resurface"] == 1
    body = frontmatter.loads(
        (memory_tree.notes_dir / report["created"]).read_text(encoding="utf-8")
    ).content
    assert "## 🔁 今日复习（1）" in body
    assert "[[old]]" in body
    state = json.loads(
        (memory_tree.state_dir / "resurface.json").read_text(encoding="utf-8")
    )
    assert len(state) == 1

    # 冷却生效：次日（若摘要不存在）同一条不再推送
    from scripts.memory.resurface import ResurfaceManager

    assert ResurfaceManager(memory_tree).candidates() == []


def test_digest_dry_run_does_not_burn_cooldown(memory_tree, make_note):
    """dry-run：复习节照常渲染，但不写冷却状态。"""
    make_note(memory_tree, "old.md", "旧笔记", idle_days=20)

    report = DigestDispatcher(memory_tree).run(dry_run=True, today="2026-09-01")

    assert "今日复习（1）" in report["markdown"]
    assert not (memory_tree.state_dir / "resurface.json").exists()


def test_digest_note_skipped_by_todos_dispatch(memory_tree):
    """摘要笔记不会被待办分发捡去（防摘要内容空转 LLM）。"""
    from scripts.dispatch.todos import TodoDispatcher

    DigestDispatcher(memory_tree).run(today="2026-09-01")

    report = TodoDispatcher(memory_tree).run()

    assert report["created"] == []
    assert report["skipped"] == 1
