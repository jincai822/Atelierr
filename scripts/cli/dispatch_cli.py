"""Atelierr 自动分发 CLI（通道产物 → 处理器 → 入库）。

用法:
    python -m scripts.cli.dispatch_cli links            # 扫描并处理抖音链接
    python -m scripts.cli.dispatch_cli links --dry-run  # 只报告不处理
    python -m scripts.cli.dispatch_cli todos            # 扫描并抽取待办事项
    python -m scripts.cli.dispatch_cli todos --dry-run  # 只报告不建笔记

配置解析顺序与 memory_cli 一致：--config > 环境变量 ATELIERR_CONFIG >
./config/memory.yaml > 内置默认 ~/atelierr-data/{memory,state}。

定时部署见 docker/systemd/atelierr-links.service / .timer。
单条链接/单篇笔记的失败不影响退出码（记入状态文件，下次自动重试，
3 次熔断）；仅当整体无法运行（如配置缺失）时 exit 1。
"""

from __future__ import annotations

import sys
from typing import List, Optional

import click

from scripts.cli.memory_cli import _resolve_config_path
from scripts.dispatch.links import LinkDispatcher
from scripts.dispatch.todos import TodoDispatcher
from scripts.memory.core import MemoryTree

DEFAULT_ROOT = "~/atelierr-data/memory"
DEFAULT_STATE_DIR = "~/atelierr-data/state"


class DispatchCLI:
    """自动分发 CLI（click 组）。"""

    def __init__(self, config_path: Optional[str] = None) -> None:
        """初始化。

        Args:
            config_path: memory.yaml 路径（None 时按解析顺序自动查找）。
        """
        self.config_path = config_path
        self.cli = self._build_cli()

    def _build_cli(self) -> click.Group:
        """构造 click group 与子命令。"""

        @click.group()
        def cli() -> None:
            """Atelierr 通道产物自动分发（links / todos）。"""

        @cli.command(name="links")
        @click.option(
            "--dry-run",
            "dry_run",
            is_flag=True,
            help="只扫描报告，不处理、不建笔记、不写状态",
        )
        def links_command(dry_run: bool) -> None:
            """扫描笔记中的抖音链接并自动抓取转写。"""
            tree = self._build_tree()
            report = LinkDispatcher(tree).run(dry_run=dry_run)
            click.echo(
                f"扫描 {report['scanned']} 篇笔记，"
                f"新发现 {report['found']} 条链接，"
                f"跳过已处理 {report['skipped']} 条"
            )
            for filename in report["created"]:
                click.echo(f"  已创建: {filename}（待确认）")
            for failure in report["failed"]:
                click.echo(f"  失败: {failure['url']} — {failure['error']}")
            if dry_run:
                click.echo("（dry-run：未做处理）")

        @cli.command(name="todos")
        @click.option(
            "--dry-run",
            "dry_run",
            is_flag=True,
            help="只扫描报告，不建待办笔记、不写状态",
        )
        def todos_command(dry_run: bool) -> None:
            """扫描笔记中的行动意图（- [ ] / #todo 直转，其余 LLM 判定）。"""
            tree = self._build_tree()
            report = TodoDispatcher(tree).run(dry_run=dry_run)
            click.echo(
                f"扫描 {report['scanned']} 篇笔记，"
                f"行动项 {report['candidates']} 条，"
                f"跳过 {report['skipped']} 篇"
            )
            for filename in report["created"]:
                click.echo(f"  已创建待办: {filename}")
            for failure in report["failed"]:
                click.echo(f"  失败: {failure['note']} — {failure['error']}")
            if dry_run:
                click.echo("（dry-run：未做处理）")

        return cli

    def _build_tree(self) -> MemoryTree:
        """按解析顺序构造 MemoryTree；配置损坏时抛 ClickException。"""
        resolved = _resolve_config_path(self.config_path)
        if resolved:
            try:
                return MemoryTree.from_config(resolved)
            except (OSError, ValueError) as exc:
                raise click.ClickException(f"配置加载失败: {resolved}: {exc}")
        return MemoryTree(DEFAULT_ROOT, state_dir=DEFAULT_STATE_DIR)

    def main(self, args: Optional[List[str]] = None) -> int:
        """命令行入口；整体失败（ClickException）时返回 1。

        Args:
            args: 命令行参数列表；None 时用 sys.argv[1:]。

        Returns:
            int: 退出码（0 成功，1 整体失败）。
        """
        try:
            return self.cli.main(args=args, standalone_mode=False) or 0
        except click.ClickException as exc:
            click.echo(f"错误: {exc.format_message()}", err=True)
            return 1


if __name__ == "__main__":
    sys.exit(DispatchCLI().main())
