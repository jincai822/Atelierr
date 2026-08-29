"""记忆模块端到端生命周期测试（CLI 全流程：create → show → search →
stats → decay → review → purge）。"""

from __future__ import annotations

import time

from click.testing import CliRunner

from scripts.cli.memory_cli import MemoryCLI


def _invoke(cli, runner, args):
    result = runner.invoke(cli, args)
    assert result.exit_code == 0, f"exit={result.exit_code}\n{result.output}"
    return result


def test_memory_lifecycle(memory_config, tmp_path):
    """CLI 全流程端到端：创建、展示、搜索、统计、衰减、审核、清理。"""
    runner = CliRunner()
    cli = MemoryCLI(config_path=str(memory_config)).cli
    notes_dir = tmp_path / "memory"
    state_dir = tmp_path / "state"

    # create
    _invoke(
        cli,
        runner,
        ["create", "hello.md", "--content", "你好世界", "--tags", "测试,笔记"],
    )
    assert (notes_dir / "hello.md").exists()

    # show（含 live confidence / layer / tags）
    result = _invoke(cli, runner, ["show", "hello.md"])
    assert "hello.md" in result.output
    assert "short-term" in result.output
    assert "confidence" in result.output

    # search
    result = _invoke(cli, runner, ["search", "你好"])
    assert "hello.md" in result.output

    # stats
    result = _invoke(cli, runner, ["stats"])
    assert "总数: 1" in result.output

    # decay --dry-run（不写报告）
    _invoke(cli, runner, ["decay", "--dry-run"])
    assert not (state_dir / "reports").exists()

    # decay（真实执行，生成报告）
    _invoke(cli, runner, ["decay"])
    assert list((state_dir / "reports").glob("decay-*.md"))

    # 制造一条 60 天未动的笔记 → 下一次 decay 置 pending_delete
    _invoke(cli, runner, ["create", "old.md", "--content", "旧笔记内容"])
    old_path = notes_dir / "old.md"
    old_ns = int((time.time() - 60 * 86400) * 1e9)
    import os

    os.utime(old_path, ns=(old_ns, old_ns))
    result = _invoke(cli, runner, ["decay"])
    assert "old.md" in result.output  # 待删除清单出现 old.md

    # review 显示待删
    result = _invoke(cli, runner, ["review"])
    assert "old.md" in result.output

    # purge --yes：文件进 trash、sidecar 清除
    _invoke(cli, runner, ["purge", "--yes"])
    assert not old_path.exists()
    assert (state_dir / "trash" / "old.md").exists()

    # search 找不到已 purge 的笔记
    result = _invoke(cli, runner, ["search", "旧笔记"])
    assert "old.md" not in result.output

    # stats 只统计存活笔记
    result = _invoke(cli, runner, ["stats"])
    assert "总数: 1" in result.output


def test_review_empty_prompt(memory_config):
    """无待删笔记时 review 提示而不是报错。"""
    runner = CliRunner()
    cli = MemoryCLI(config_path=str(memory_config)).cli
    _invoke(cli, runner, ["create", "a.md", "--content", "a"])
    result = _invoke(cli, runner, ["review"])
    assert "没有待删除的笔记" in result.output


def test_purge_requires_confirmation(memory_config, tmp_path):
    """不带 --yes 时 purge 需确认（非交互输入则中止）。"""
    import os
    import time

    runner = CliRunner()
    cli = MemoryCLI(config_path=str(memory_config)).cli
    _invoke(cli, runner, ["create", "old.md", "--content", "旧"])
    old_path = tmp_path / "memory" / "old.md"
    old_ns = int((time.time() - 60 * 86400) * 1e9)
    os.utime(old_path, ns=(old_ns, old_ns))
    _invoke(cli, runner, ["decay"])

    # 无 --yes 且无输入 → click 中止（exit code 非 0），文件保留
    result = runner.invoke(cli, ["purge"], input="n\n")
    assert result.exit_code != 0
    assert old_path.exists()
