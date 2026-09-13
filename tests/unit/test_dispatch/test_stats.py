"""捕获统计单元测试（只读聚合，无网络/LLM）。

统计口径、确认率、wiki 沉淀数、遗忘数（回收站 ctime）、晨报简数行、
周日摘要详细节、stats 子命令均为真实代码路径。
"""

from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from unittest import mock

from scripts.dispatch.digest import DigestDispatcher
from scripts.dispatch.stats import (
    capture_stats,
    failure_stats,
    render_capture_line,
    render_failure_line,
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


def _trash_file(tree, name):
    """造一篇回收站文件（模拟 purge 移入；frontmatter 故意用旧日期——
    遗忘数必须按移入时间 ctime 计，而非笔记 created）。"""
    trash_dir = tree.state_dir / "trash"
    trash_dir.mkdir(parents=True, exist_ok=True)
    path = trash_dir / name
    path.write_text(
        "---\ncreated: 2026-01-01\nsource: link\n---\n\n旧笔记\n",
        encoding="utf-8",
    )
    return path


class _pin_ctime:
    """把指定文件的 ctime 钉在窗口内（TODAY 中午）。ctime 无法用 os.utime
    设置，只能 mock Path.stat——2026-09-14 实测：硬编码 TODAY + 真实 ctime
    跨天漂移导致三个用例在午夜后集体失败。"""

    def __init__(self, *paths):
        self._paths = set(paths)

    def __enter__(self):
        real_stat = Path.stat
        pinned = datetime.strptime(TODAY, "%Y-%m-%d").timestamp() + 43200
        paths = self._paths

        def fake_stat(self, *args, **kwargs):
            result = real_stat(self, *args, **kwargs)
            if self in paths:  # 注意：此 self 是 Path 实例，不是本类
                values = list(result)
                values[9] = pinned  # st_ctime
                return os.stat_result(tuple(values))
            return result

        self._ctx = mock.patch.object(Path, "stat", fake_stat)
        self._ctx.__enter__()
        return self

    def __exit__(self, *args):
        self._ctx.__exit__(*args)


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


def test_purged_counts_recent_trash(memory_tree):
    """遗忘数：回收站中 ctime 落在窗口内的文件（不看笔记 created）。"""
    path = _trash_file(memory_tree, "gone.md")

    with _pin_ctime(path):
        stats = capture_stats(memory_tree, days=7, today=TODAY)

    assert stats["purged"] == 1


def test_purged_zero_without_trash_dir(memory_tree):
    """无回收站（从未 purge）：遗忘数 0，不报错。"""
    stats = capture_stats(memory_tree, days=7, today=TODAY)

    assert stats["purged"] == 0


def test_purged_excludes_old_ctime(memory_tree):
    """窗口前移入回收站的文件不计入（ctime 界外）。"""
    old_path = _trash_file(memory_tree, "ancient.md")
    fresh_path = _trash_file(memory_tree, "fresh.md")

    real_stat = Path.stat
    pinned_new = datetime.strptime(TODAY, "%Y-%m-%d").timestamp() + 43200

    def fake_stat(self, *args, **kwargs):
        result = real_stat(self, *args, **kwargs)
        if self == old_path:
            values = list(result)
            values[9] = datetime(2026, 8, 1).timestamp()  # st_ctime 改旧（窗口外）
            return os.stat_result(tuple(values))
        if self == fresh_path:
            values = list(result)
            values[9] = pinned_new  # 窗口内（防真实 ctime 跨天漂移）
            return os.stat_result(tuple(values))
        return result

    with mock.patch.object(Path, "stat", fake_stat):
        stats = capture_stats(memory_tree, days=7, today=TODAY)

    assert stats["purged"] == 1


def test_weekly_render_has_purge_line(memory_tree):
    """周报详细节带「本周遗忘」一行。"""
    path = _trash_file(memory_tree, "gone.md")

    with _pin_ctime(path):
        stats = capture_stats(memory_tree, days=7, today=TODAY)
    lines = render_weekly_stats(stats)

    assert any("本周遗忘（purge 进回收站）：1 条" in line for line in lines)


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


def test_failure_stats_counts_failed_only(tmp_path):
    """熔断条目（status=failed）按渠道计数；done/缺表/损坏表不计。"""
    state = tmp_path / "state"
    state.mkdir()
    (state / "processed_links.json").write_text(
        json.dumps(
            {
                "u1": {"status": "done"},
                "u2": {"status": "failed", "attempts": 3},
                "u3": {"status": "failed", "attempts": 4},
                "u4": {"attempts": 1},
            }
        ),
        encoding="utf-8",
    )
    (state / "processed_todos.json").write_text(
        json.dumps({"n1": {"status": "failed"}}), encoding="utf-8"
    )
    (state / "processed_media.json").write_text("损坏{", encoding="utf-8")

    assert failure_stats(state) == {"链接": 2, "待办": 1}


def test_failure_stats_empty(tmp_path):
    """无状态表 → 空表。"""
    assert failure_stats(tmp_path) == {}


def test_render_failure_line():
    """无失败不占版面；有失败给一行点名+出路。"""
    assert render_failure_line({}) is None
    line = render_failure_line({"链接": 2, "待办": 1})
    assert "3 条" in line
    assert "链接 2" in line and "待办 1" in line
    assert "重发" in line


def test_digest_shows_failure_line(memory_tree, monkeypatch):
    """晨报集成：状态表里有熔断条目时，摘要含失败点名行。"""
    (memory_tree.state_dir / "processed_links.json").write_text(
        json.dumps({"u1": {"status": "failed"}}), encoding="utf-8"
    )
    report = DigestDispatcher(memory_tree).run(dry_run=True, today=TODAY)
    assert "处理失败未恢复 1 条" in report["markdown"]
    assert "链接 1" in report["markdown"]


def test_digest_no_failure_no_line(memory_tree):
    """无熔断：摘要不出现失败行。"""
    report = DigestDispatcher(memory_tree).run(dry_run=True, today=TODAY)
    assert "处理失败" not in report["markdown"]


def test_digest_shows_decay_line(memory_tree, monkeypatch):
    """晨报含昨日 decay 账（decay-last.json 日期=昨天才显示）。"""
    import json as _json
    from datetime import datetime, timedelta

    yesterday = (
        datetime.strptime(TODAY, "%Y-%m-%d") - timedelta(days=1)
    ).strftime("%Y-%m-%d")
    (memory_tree.state_dir / "decay-last.json").write_text(
        _json.dumps(
            {"date": yesterday, "total": 16, "relayered": 2, "pending": 1, "daily_exempt": 5}
        ),
        encoding="utf-8",
    )
    report = DigestDispatcher(memory_tree).run(dry_run=True, today=TODAY)
    assert "昨日 decay：在库 16 篇" in report["markdown"]
    assert "新进待删 1" in report["markdown"]


def test_digest_stale_decay_last_hidden(memory_tree):
    """decay-last.json 过期（非昨天）不显示，避免误导。"""
    import json as _json

    (memory_tree.state_dir / "decay-last.json").write_text(
        _json.dumps({"date": "2026-01-01", "total": 9, "relayered": 0, "pending": 0}),
        encoding="utf-8",
    )
    report = DigestDispatcher(memory_tree).run(dry_run=True, today=TODAY)
    assert "昨日 decay" not in report["markdown"]
