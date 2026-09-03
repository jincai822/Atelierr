"""划重点勾中转笔记单元测试（无真实网络）。

扫描、勾选识别、幂等、dry-run、跨清单撞名均为真实代码路径；
tick/untick 由测试直接改写清单文件（模拟人在 Obsidian 里勾选）。
"""

from __future__ import annotations

import json

import frontmatter

from scripts.dispatch.highlights import HighlightsDispatcher

_CHECKLIST = """# 划重点清单：测试书

> 来源：[[测试书.pdf]]（10 页有文字，LLM 代读生成）

## 候选清单

- [ ] **概念甲**（第 3 页）
  - 内容：甲是什么
  - 对着：既有认知 X
  - 性质：支持
  - 建议：推荐勾——承重
- [ ] **概念乙**（第 7 页）
  - 内容：乙是什么
  - 对着：待读者判断
  - 性质：待验
  - 建议：可不勾——偏例
"""


def _make_checklist(tree, name="划重点-测试书-abc123.md", body=_CHECKLIST):
    return tree.create_note(name, body, source="highlights", tags=["划重点"])


def _tick(tree, path, title):
    """把清单里指定条目的复选框勾上（模拟人工勾选）。"""
    text = path.read_text(encoding="utf-8")
    ticked = text.replace(f"- [ ] **{title}**", f"- [x] **{title}**")
    assert ticked != text
    path.write_text(ticked, encoding="utf-8")


def _state(tree):
    state_file = tree.state_dir / "processed_highlights.json"
    return json.loads(state_file.read_text(encoding="utf-8"))


def test_unticked_item_not_promoted(memory_tree):
    """未勾选的清单：扫描到但零转记。"""
    _make_checklist(memory_tree)

    report = HighlightsDispatcher(memory_tree).run()

    assert report["scanned"] == 1
    assert report["ticked"] == 0
    assert report["created"] == []


def test_ticked_item_promoted(memory_tree):
    """勾中概念甲：转出 hl- 笔记，标签/来源/详情/双链齐全。"""
    path = _make_checklist(memory_tree)
    _tick(memory_tree, path, "概念甲")

    report = HighlightsDispatcher(memory_tree).run()

    assert report["ticked"] == 1
    assert len(report["created"]) == 1
    filename = report["created"][0]
    assert filename.startswith("hl-概念甲-")
    post = frontmatter.loads(
        (memory_tree.notes_dir / filename).read_text(encoding="utf-8")
    )
    assert post["source"] == "highlight"
    assert "待确认" in post["tags"]
    assert "划重点" in post["tags"]
    assert "[[划重点-测试书-abc123]]" in post.content
    assert "第 3 页" in post.content
    assert "- 内容：甲是什么" in post.content
    assert "- 性质：支持" in post.content
    # 未勾中的概念乙不得转出
    assert not list(memory_tree.notes_dir.glob("hl-概念乙-*"))


def test_idempotent_second_run(memory_tree):
    """第二轮运行：已转记的勾项跳过，不重复建笔记。"""
    path = _make_checklist(memory_tree)
    _tick(memory_tree, path, "概念甲")
    dispatcher = HighlightsDispatcher(memory_tree)
    first = dispatcher.run()

    second = dispatcher.run()

    assert len(first["created"]) == 1
    assert second["created"] == []
    assert second["skipped"] == 1
    assert len(list(memory_tree.notes_dir.glob("hl-概念甲-*"))) == 1


def test_untick_after_promotion_keeps_note(memory_tree):
    """勾了又取消：笔记已建不追回（机器绝不删除），也不重复建。"""
    path = _make_checklist(memory_tree)
    _tick(memory_tree, path, "概念甲")
    dispatcher = HighlightsDispatcher(memory_tree)
    dispatcher.run()
    text = path.read_text(encoding="utf-8")
    path.write_text(text.replace("- [x] **概念甲**", "- [ ] **概念甲**"), encoding="utf-8")

    report = dispatcher.run()

    assert report["created"] == []
    assert len(list(memory_tree.notes_dir.glob("hl-概念甲-*"))) == 1


def test_non_checklist_notes_ignored(memory_tree):
    """普通笔记（source 非 highlights）里的勾选项不被处理。"""
    memory_tree.create_note(
        "daily.md", "- [x] **买牛奶**（第 1 页）\n", source="test"
    )

    report = HighlightsDispatcher(memory_tree).run()

    assert report["scanned"] == 0
    assert report["created"] == []


def test_dry_run_creates_nothing(memory_tree):
    """dry-run：不建笔记、不写状态。"""
    path = _make_checklist(memory_tree)
    _tick(memory_tree, path, "概念甲")

    report = HighlightsDispatcher(memory_tree).run(dry_run=True)

    assert report["ticked"] == 1
    assert report["created"] == []
    assert not list(memory_tree.notes_dir.glob("hl-*.md"))
    assert not (memory_tree.state_dir / "processed_highlights.json").exists()


def test_cross_checklist_same_title_no_collision(memory_tree):
    """两份清单勾中同名候选：各转各的，文件名不撞车。"""
    path_a = _make_checklist(memory_tree, name="划重点-书A-aaa111.md")
    path_b = _make_checklist(memory_tree, name="划重点-书B-bbb222.md")
    _tick(memory_tree, path_a, "概念甲")
    _tick(memory_tree, path_b, "概念甲")

    report = HighlightsDispatcher(memory_tree).run()

    assert len(report["created"]) == 2
    assert len(set(report["created"])) == 2
    assert len(list(memory_tree.notes_dir.glob("hl-概念甲-*"))) == 2


def test_state_records_promoted(memory_tree):
    """状态文件登记：清单名 → 勾项键 → 转出文件名。"""
    path = _make_checklist(memory_tree)
    _tick(memory_tree, path, "概念乙")
    HighlightsDispatcher(memory_tree).run()

    state = _state(memory_tree)
    promoted = state["划重点-测试书-abc123.md"]["promoted"]
    assert "概念乙#7" in promoted
    assert promoted["概念乙#7"].startswith("hl-概念乙-")
