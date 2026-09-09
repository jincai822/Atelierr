"""memory_cli 单元测试：CliRunner 冒烟 create/search/stats/resurface + sync 对齐。"""

from __future__ import annotations

import os
import time

import frontmatter
from click.testing import CliRunner

from scripts.cli.memory_cli import MemoryCLI
from scripts.memory.core import MemoryTree


def _make_cli(tmp_path):
    """在临时目录写配置并构造 CLI（笔记目录 + 显式 state_dir）。"""
    config = tmp_path / "memory.yaml"
    config.write_text(
        f"memory:\n" f"  root: {tmp_path}/memory\n" f"  state_dir: {tmp_path}/state\n",
        encoding="utf-8",
    )
    cli = MemoryCLI(config_path=str(config)).cli
    return cli, config, tmp_path / "memory"


def test_sync_normalizes_bare_notes(tmp_path):
    """两个裸 .md → sync 归一化登记，layer == short-term。"""
    cli, config, notes_dir = _make_cli(tmp_path)
    notes_dir.mkdir(parents=True, exist_ok=True)
    (notes_dir / "a.md").write_text("笔记 A 内容", encoding="utf-8")
    (notes_dir / "b.md").write_text("笔记 B 内容", encoding="utf-8")

    result = CliRunner().invoke(cli, ["sync"])
    assert result.exit_code == 0, result.output
    assert "归一化: 2" in result.output
    assert "新登记: 0" in result.output
    assert "注销: 0" in result.output

    tree = MemoryTree.from_config(str(config))
    assert tree.layer_of(notes_dir / "a.md") == "short-term"
    assert tree.layer_of(notes_dir / "b.md") == "short-term"


def test_sync_deregisters_deleted_file(tmp_path):
    """登记后外部删除文件 → 再次 sync 注销计数 >= 1。"""
    cli, config, notes_dir = _make_cli(tmp_path)
    notes_dir.mkdir(parents=True, exist_ok=True)
    (notes_dir / "a.md").write_text("笔记 A", encoding="utf-8")
    (notes_dir / "b.md").write_text("笔记 B", encoding="utf-8")
    assert CliRunner().invoke(cli, ["sync"]).exit_code == 0

    (notes_dir / "a.md").unlink()
    result = CliRunner().invoke(cli, ["sync"])
    assert result.exit_code == 0, result.output
    assert "注销: 1" in result.output
    assert MemoryTree.from_config(str(config)).get_stats()["total"] == 1


def test_sync_source_option(tmp_path):
    """--source 自定义来源写入 frontmatter。"""
    cli, config, notes_dir = _make_cli(tmp_path)
    notes_dir.mkdir(parents=True, exist_ok=True)
    (notes_dir / "x.md").write_text("内容", encoding="utf-8")
    result = CliRunner().invoke(cli, ["sync", "--source", "obsidian"])
    assert result.exit_code == 0, result.output
    post = frontmatter.loads((notes_dir / "x.md").read_text(encoding="utf-8"))
    assert post.metadata.get("source") == "obsidian"


def test_cli_create_search_stats_smoke(tmp_path):
    """create/search/stats 冒烟：走 CliRunner，覆盖 scripts/cli 主要路径。"""
    cli, config, _ = _make_cli(tmp_path)
    runner = CliRunner()

    result = runner.invoke(
        cli, ["create", "smoke.md", "--content", "冒烟内容", "--tags", "测试"]
    )
    assert result.exit_code == 0, result.output
    assert "已创建" in result.output

    result = runner.invoke(cli, ["search", "冒烟"])
    assert result.exit_code == 0, result.output
    assert "smoke.md" in result.output

    result = runner.invoke(cli, ["stats"])
    assert result.exit_code == 0, result.output
    assert "总数: 1" in result.output


def test_cli_resurface_empty(tmp_path):
    """resurface：全新库 → 空队列提示。"""
    cli, _, _ = _make_cli(tmp_path)

    result = CliRunner().invoke(cli, ["resurface"])

    assert result.exit_code == 0, result.output
    assert "今日复习队列为空" in result.output


def test_cli_resurface_lists_old_note(tmp_path):
    """resurface：闲置 20 天的笔记入队并展示置信度与闲置天数。"""
    cli, _, notes_dir = _make_cli(tmp_path)
    runner = CliRunner()
    result = runner.invoke(cli, ["create", "old.md", "--content", "旧内容"])
    assert result.exit_code == 0, result.output
    old_ns = int((time.time() - 20 * 86400) * 1e9)
    os.utime(notes_dir / "old.md", ns=(old_ns, old_ns))

    result = runner.invoke(cli, ["resurface"])

    assert result.exit_code == 0, result.output
    assert "old.md" in result.output
    assert "闲置20天" in result.output


def test_cli_resurface_stats_empty(tmp_path):
    """resurface --stats：无结案观测 → 明确提示。"""
    cli, _, _ = _make_cli(tmp_path)

    result = CliRunner().invoke(cli, ["resurface", "--stats"])

    assert result.exit_code == 0, result.output
    assert "暂无响应率数据" in result.output


def test_cli_resurface_stats_with_data(tmp_path):
    """resurface --stats：有结案观测 → 显示响应率。"""
    cli, config, _ = _make_cli(tmp_path)
    from scripts.dispatch.response_probe import ResponseProbe

    tree = MemoryTree.from_config(str(config))
    path = tree.create_note("old.md", "旧内容")
    old_ns = int((time.time() - 20 * 86400) * 1e9)
    os.utime(path, ns=(old_ns, old_ns))
    probe = ResponseProbe(tree)
    probe.register([{"id": tree._find_entry_id(path), "filename": "old.md"}])
    new_ns = int(time.time() * 1e9)
    os.utime(path, ns=(new_ns, new_ns))  # 模拟推送后被编辑
    probe.check_pending()

    result = CliRunner().invoke(cli, ["resurface", "--stats"])

    assert result.exit_code == 0, result.output
    assert "响应率 100%" in result.output


# ----------------------------------------------------------------------
# decay 月度清理提醒（每月 1 日 + 有待删 → 系统/ 清单 + 飞书卡；purge 留 CLI）
# ----------------------------------------------------------------------


def _reminder_setup(tmp_path):
    """构造 MemoryTree + 两条真实笔记（清单 wikilink 指向它们）。"""
    notes_dir = tmp_path / "memory"
    state_dir = tmp_path / "state"
    notes_dir.mkdir(parents=True)
    tree = MemoryTree(str(notes_dir), state_dir=str(state_dir))
    tree.create_note("old-a.md", "旧笔记 A", source="test")
    tree.create_note("old-b.md", "旧笔记 B", source="test")
    return tree, notes_dir


def test_monthly_reminder_first_day_sends_card(tmp_path, monkeypatch):
    """每月 1 日 + 有待删 → 清单进 系统/，提醒卡带「查看待清理清单」按钮。"""
    from datetime import datetime

    import scripts.cli.memory_cli as cli_module
    import scripts.dispatch.feishu as feishu_module

    tree, notes_dir = _reminder_setup(tmp_path)
    cards = []
    monkeypatch.setattr(
        feishu_module,
        "send_feishu_card",
        lambda card, chat_id=None, **kw: cards.append(card) or True,
    )
    pending = [str(notes_dir / "old-a.md"), str(notes_dir / "old-b.md")]

    assert cli_module._monthly_purge_reminder(
        tree, pending, today=datetime(2026, 9, 1)
    ) is True

    listing = notes_dir / "系统" / "待清理清单-2026-09.md"
    assert listing.exists()
    text = listing.read_text(encoding="utf-8")
    assert "[[old-a]]" in text and "[[old-b]]" in text
    assert "memory_cli purge" in text  # 卡片与清单都只提醒，purge 留 CLI
    assert len(cards) == 1
    card = cards[0]
    assert "2 条笔记冷却到期" in card["elements"][0]["text"]["content"]
    button = card["elements"][1]["actions"][0]
    assert button["text"]["content"] == "查看待清理清单"
    assert button["url"].startswith("obsidian://open?vault=")


def test_monthly_reminder_other_days_silent(tmp_path, monkeypatch):
    """非 1 日：不出清单不推卡。"""
    from datetime import datetime

    import scripts.cli.memory_cli as cli_module
    import scripts.dispatch.feishu as feishu_module

    tree, notes_dir = _reminder_setup(tmp_path)
    cards = []
    monkeypatch.setattr(
        feishu_module,
        "send_feishu_card",
        lambda card, chat_id=None, **kw: cards.append(card) or True,
    )

    assert cli_module._monthly_purge_reminder(
        tree, ["x.md"], today=datetime(2026, 9, 2)
    ) is False
    assert cards == []
    assert not (notes_dir / "系统").exists()


def test_monthly_reminder_empty_pending_silent(tmp_path, monkeypatch):
    """1 日但无待删：不打扰（零打扰原则）。"""
    from datetime import datetime

    import scripts.cli.memory_cli as cli_module
    import scripts.dispatch.feishu as feishu_module

    tree, notes_dir = _reminder_setup(tmp_path)
    cards = []
    monkeypatch.setattr(
        feishu_module,
        "send_feishu_card",
        lambda card, chat_id=None, **kw: cards.append(card) or True,
    )

    assert cli_module._monthly_purge_reminder(
        tree, [], today=datetime(2026, 9, 1)
    ) is False
    assert cards == []
    assert not (notes_dir / "系统").exists()


def test_monthly_reminder_rerun_idempotent(tmp_path, monkeypatch):
    """同月重跑：清单不重建（FileExistsError 吞掉），提醒卡照发不崩。"""
    from datetime import datetime

    import scripts.cli.memory_cli as cli_module
    import scripts.dispatch.feishu as feishu_module

    tree, notes_dir = _reminder_setup(tmp_path)
    cards = []
    monkeypatch.setattr(
        feishu_module,
        "send_feishu_card",
        lambda card, chat_id=None, **kw: cards.append(card) or True,
    )
    pending = [str(notes_dir / "old-a.md")]
    day = datetime(2026, 9, 1)

    assert cli_module._monthly_purge_reminder(tree, pending, today=day) is True
    assert cli_module._monthly_purge_reminder(tree, pending, today=day) is True

    assert len(list((notes_dir / "系统").glob("待清理清单-*.md"))) == 1
    assert len(cards) == 2
