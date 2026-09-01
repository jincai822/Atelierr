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
