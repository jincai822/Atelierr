"""捕获统计单元测试（只读聚合，无网络/LLM）。

统计口径、确认率、wiki 沉淀数、晨报简数行、周日摘要详细节、
stats 子命令均为真实代码路径。
"""

from __future__ import annotations

import json

from scripts.dispatch.digest import DigestDispatcher
from scripts.dispatch.stats import (
    capture_stats,
    render_capture_line,
    render_weekly_stats,
)

TODAY = "2026-09-13"  # 周日
YESTERDAY = "2026-09-12"


def _note(tree, name, source, created, tags=None):
    """造一篇指定 source/created 的笔记（frontmatter 直给）。"""
    content = f"---\ncreated: {created}\nsource: {source}\n"
    if tags:
        content += f"tags: {json.dumps(tags, ensure_ascii=False)}\n"
    content += "---\n\n正文\n"
    return tree.create_note(name, content)


def _wiki_card(tree, name, created):
    """造一张 wiki 卡（wiki/ 目录 + created）。"""
    wiki_dir = tree.notes_dir / "wiki"
    wiki_dir.mkdir(exist_ok=True)
    (wiki_dir / name).write_text(
        f"---\ncreated: {created}\ntype: Excerpt\n---\n\n卡\n", encoding="utf-8"
    )


def test_by_source_and_total(memory_tree):
    """各入口分桶计数；机器产物（digest/highlights）不算捕获。"""
    _note(memory_tree, "a.md", "lark", TODAY)
    _note(memory_tree, "b.md", "link", TODAY, tags=["待确认", "抖音"])
    _note(memory_tree, "c.md", "webclip", TODAY, tags=["剪藏", "待确认"])
    _note(memory_tree, "d.md", "sync", TODAY)
    _note(memory_tree, "e.md", "digest", TODAY)  # 机器产物不计
    _note(memory_tree, "f.md", "unknown-src", TODAY)  # 未知 → 其他

    stats = capture_stats(memory_tree, days=7, today=TODAY)

    assert stats["total"] == 5
    assert stats["by_source"] == {
        "飞书": 1,
        "链接转写": 1,
        "剪藏": 1,
        "速记直写": 1,
        "其他": 1,
    }


def test_window_boundary(memory_tree):
    """窗口边界：created > start 且 <= end 才计入（days=7 含今天）。"""
    _note(memory_tree, "in.md", "lark", "2026-09-07")
    _note(memory_tree, "edge-out.md", "lark", "2026-09-06")  # 恰在界外
    _note(memory_tree, "old.md", "lark", "2026-08-01")

    stats = capture_stats(memory_tree, days=7, today=TODAY)

    assert stats["total"] == 1


def test_confirm_rate(memory_tree):
    """确认率只算机器产出（link/media/webclip）：摘除待确认的比例。"""
    _note(memory_tree, "done.md", "link", TODAY, tags=["抖音"])
    _note(memory_tree, "wait.md", "link", TODAY, tags=["待确认", "抖音"])
    _note(memory_tree, "clip.md", "webclip", TODAY, tags=["剪藏"])
    _note(memory_tree, "human.md", "lark", TODAY)  # 人工笔记不进分母

    stats = capture_stats(memory_tree, days=7, today=TODAY)

    assert stats["auto_total"] == 3
    assert stats["confirmed"] == 2
    assert abs(stats["confirm_rate"] - 2 / 3) < 1e-6


def test_confirm_rate_none_without_auto(memory_tree):
    """窗口内无机器产出：confirm_rate 为 None（显示 —）。"""
    _note(memory_tree, "human.md", "lark", TODAY)

    stats = capture_stats(memory_tree, days=7, today=TODAY)

    assert stats["confirm_rate"] is None
    lines = render_weekly_stats(stats)
    assert any("确认率：—" in line for line in lines)


def test_wiki_new_count(memory_tree):
    """沉淀数：wiki/ 中 created 落在窗口内的卡片。"""
    _wiki_card(memory_tree, "卡-新.md", TODAY)
    _wiki_card(memory_tree, "卡-旧.md", "2026-08-01")

    stats = capture_stats(memory_tree, days=7, today=TODAY)

    assert stats["wiki_new"] == 1


def test_render_capture_line(memory_tree):
    """晨报简数一行：总数 + 入口分布（按数量降序）。"""
    _note(memory_tree, "a.md", "lark", YESTERDAY)
    _note(memory_tree, "b.md", "lark", YESTERDAY)
    _note(memory_tree, "c.md", "webclip", YESTERDAY, tags=["剪藏", "待确认"])

    stats = capture_stats(memory_tree, days=1, today=YESTERDAY)
    line = render_capture_line(stats)

    assert line == "昨日捕获 3 条：飞书 2、剪藏 1"


def test_digest_has_capture_line(memory_tree):
    """摘要昨日节附入口分布一行。"""
    _note(memory_tree, "a.md", "lark", YESTERDAY)

    report = DigestDispatcher(memory_tree).run(today=TODAY)

    assert "> 昨日捕获 1 条：飞书 1" in report["markdown"]


def test_digest_weekly_section_only_on_sunday(memory_tree):
    """本周捕获统计节：周日有、非周日无。"""
    _note(memory_tree, "a.md", "link", YESTERDAY, tags=["抖音"])

    sunday = DigestDispatcher(memory_tree).run(today=TODAY)
    assert "## 📊 本周捕获统计" in sunday["markdown"]
    assert "确认率：100%" in sunday["markdown"]
    assert "沉淀进 wiki：0 张卡" in sunday["markdown"]

    saturday = DigestDispatcher(memory_tree).run(today="2026-09-12")
    assert "## 📊 本周捕获统计" not in saturday["markdown"]


def test_cli_stats_command(memory_tree, tmp_path):
    """stats 子命令：打印详细节，exit 0。"""
    _note(memory_tree, "a.md", "link", TODAY, tags=["抖音"])
    config = tmp_path / "memory.yaml"
    config.write_text(
        f"memory:\n  root: {memory_tree.notes_dir}\n"
        f"  state_dir: {memory_tree.state_dir}\n",
        encoding="utf-8",
    )
    import scripts.cli.dispatch_cli as cli_module

    code = cli_module.DispatchCLI(config_path=str(config)).main(["stats"])

    assert code == 0
