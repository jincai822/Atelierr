"""Atelierr 记忆模块 CLI。

子命令：create / show / search / stats / decay / review / purge / sync。
配置解析顺序：--config 显式参数 > 环境变量 ATELIERR_CONFIG >
./config/memory.yaml（若存在）> 内置默认 ~/atelierr-data/{memory,state}。

用法:
    python -m scripts.cli.memory_cli create note.md --content "正文"
    python -m scripts.cli.memory_cli decay --dry-run
    python -m scripts.cli.memory_cli sync
"""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path
from typing import List, Optional

import click

from scripts.memory.core import MemoryTree

DEFAULT_CONFIG = Path("config/memory.yaml")
DEFAULT_ROOT = "~/atelierr-data/memory"
DEFAULT_STATE_DIR = "~/atelierr-data/state"


def resolve_config_path(config_path: Optional[str]) -> Optional[str]:
    """解析配置文件路径：显式 > 环境变量 > ./config/memory.yaml > None。"""
    if config_path:
        return config_path
    env_path = os.environ.get("ATELIERR_CONFIG")
    if env_path:
        return env_path
    if DEFAULT_CONFIG.exists():
        return str(DEFAULT_CONFIG)
    return None


def _cognition_dependencies(tree: MemoryTree, note_id: str) -> List:
    """查询引用该 memory 的在研 cognition（active/testing/questioned）。

    COG-PROMOTION-05：仅显示依赖警告，不阻止 purge、不恢复 memory、
    不改变 confidence。memory-only 部署（cognition 目录不存在）直接跳过，
    绝不因查询而创建 cognition 目录。
    """
    if not note_id:
        return []
    ov_path = tree.notes_dir.parent
    if not (ov_path / "cognition").is_dir():
        return []
    from scripts.memory.cognition import CognitionManager

    manager = CognitionManager(ov_path, state_dir=tree.state_dir)
    return manager.memory_dependencies(note_id)


class MemoryCLI:
    """记忆模块 CLI（点击组）。"""

    def __init__(self, config_path: Optional[str] = None) -> None:
        """初始化。

        Args:
            config_path: 配置文件路径；None 时按解析顺序寻找。
        """
        self.config_path = config_path
        self.tree = self._build_tree(config_path)
        self.cli = self._build_cli()

    def _build_tree(self, config_path: Optional[str]) -> MemoryTree:
        """按配置构造 MemoryTree；无配置时用内置默认路径。"""
        resolved = resolve_config_path(config_path)
        if resolved is not None:
            return MemoryTree.from_config(resolved)
        return MemoryTree(DEFAULT_ROOT, state_dir=DEFAULT_STATE_DIR)

    def _build_cli(self) -> click.Group:
        """构造 click group 与各子命令。"""

        @click.group()
        @click.option(
            "--config",
            "config_path",
            type=click.Path(dir_okay=False),
            default=None,
            help="配置文件路径（覆盖环境变量与默认值）",
        )
        @click.pass_context
        def cli(ctx: click.Context, config_path: Optional[str]) -> None:
            """Atelierr 记忆模块（create/show/search/stats/decay/review/purge/sync）。"""
            # --config 选项 > 构造参数 self.config_path > 默认解析链
            resolved = resolve_config_path(config_path or self.config_path)
            ctx.obj = (
                MemoryTree.from_config(resolved)
                if resolved is not None
                else MemoryTree(DEFAULT_ROOT, state_dir=DEFAULT_STATE_DIR)
            )

        def _parse_tags(tags: Optional[str]) -> Optional[List[str]]:
            """把逗号分隔的标签串解析为列表。"""
            if not tags:
                return None
            return [tag.strip() for tag in tags.split(",") if tag.strip()]

        @cli.command()
        @click.argument("filename")
        @click.option("--content", required=True, help="笔记正文内容")
        @click.option(
            "--source",
            default="unknown",
            show_default=True,
            help="来源（web/obsidian/lark/agent/reflection 等）",
        )
        @click.option("--tags", default=None, help="逗号分隔的标签列表")
        @click.pass_context
        def create(
            ctx: click.Context,
            filename: str,
            content: str,
            source: str,
            tags: Optional[str],
        ) -> None:
            """创建新笔记（平面根层 + 一次性 frontmatter + sidecar 登记）。"""
            tree: MemoryTree = ctx.obj
            path = tree.create_note(
                filename, content, source=source, tags=_parse_tags(tags)
            )
            click.echo(f"已创建: {path}")

        @cli.command()
        @click.argument("filename")
        @click.pass_context
        def show(ctx: click.Context, filename: str) -> None:
            """展示笔记元数据与 live confidence。"""
            from rich.console import Console
            from rich.table import Table

            tree: MemoryTree = ctx.obj
            info = tree.note_info(tree.notes_dir / filename)
            table = Table(title=filename)
            table.add_column("字段")
            table.add_column("值")
            for key, value in info.items():
                table.add_row(key, str(value))
            Console().print(table)

        @cli.command()
        @click.argument("query", required=False, default="")
        @click.option("--tags", default=None, help="逗号分隔的标签（任一命中）")
        @click.option("--date-from", default=None, help="起始日期 YYYY-MM-DD")
        @click.option("--date-to", default=None, help="结束日期 YYYY-MM-DD")
        @click.option(
            "--layer",
            type=click.Choice(["short-term", "mid-term", "long-term"]),
            default=None,
            help="逻辑层级过滤",
        )
        @click.option(
            "--limit", default=10, show_default=True, type=int, help="返回条数上限"
        )
        @click.pass_context
        def search(
            ctx: click.Context,
            query: str,
            tags: Optional[str],
            date_from: Optional[str],
            date_to: Optional[str],
            layer: Optional[str],
            limit: int,
        ) -> None:
            """全文/标签/日期/层级搜索（按 confidence 降序）。"""
            tree: MemoryTree = ctx.obj
            results = tree.search(
                query=query,
                tags=_parse_tags(tags),
                date_from=date_from,
                date_to=date_to,
                layer=layer,
                limit=limit,
            )
            if not results:
                click.echo("无匹配笔记")
                return
            for memory in results:
                click.echo(
                    f"[{memory.layer}] conf={memory.confidence:.3f} "
                    f"{memory.path.name} — {memory.title}"
                )

        @cli.command()
        @click.pass_context
        def stats(ctx: click.Context) -> None:
            """统计信息（总数/分层/待删/平均 confidence）。"""
            tree: MemoryTree = ctx.obj
            data = tree.get_stats()
            click.echo(f"总数: {data['total']}")
            for layer, count in data["layers"].items():
                click.echo(f"  {layer}: {count}")
            click.echo(f"待删除: {data['pending_delete']}")
            click.echo(f"平均 confidence: {data['avg_confidence']:.3f}")

        @cli.command()
        @click.option("--dry-run", is_flag=True, help="只报告不写入")
        @click.pass_context
        def decay(ctx: click.Context, dry_run: bool) -> None:
            """执行衰减：反链扫描 → 重算 → 分层/待删标记 → 报告。"""
            from scripts.memory.decay import DecayManager

            tree: MemoryTree = ctx.obj
            report = DecayManager(tree).run(dry_run=dry_run)
            click.echo(
                f"总数: {report['total_notes']} | short-term: {report['short_term']} "
                f"| mid-term: {report['mid_term']} | long-term: {report['long_term']}"
            )
            key = "would_relayer" if dry_run else "relayered"
            label = "将迁移" if dry_run else "已迁移"
            click.echo(f"{label}: {report[key]} 条")
            if report["pending"]:
                click.echo("待删除:")
                for path in report["pending"]:
                    click.echo(f"  - {path}")
            if report.get("report_path"):
                click.echo(f"报告: {report['report_path']}")

        @cli.command()
        @click.pass_context
        def review(ctx: click.Context) -> None:
            """列出 pending_delete 笔记供人工确认（含 cognition 依赖警告）。"""
            tree: MemoryTree = ctx.obj
            pending = tree.list_pending_delete()
            if not pending:
                click.echo("没有待删除的笔记")
                return
            click.echo(f"{len(pending)} 条待删除笔记（确认后 purge 移入回收站）:")
            for path in pending:
                click.echo(f"  - {path}")
                note_id = tree._find_entry_id(path) or ""
                for dep in _cognition_dependencies(tree, note_id):
                    click.echo(
                        f"    ⚠ 被在研 cognition 引用: {dep.id}"
                        f"（{dep.entry_type}/{dep.status}）；purge 后其证据将悬空"
                    )

        @cli.command()
        @click.option("--yes", "assume_yes", is_flag=True, help="跳过确认直接执行")
        @click.pass_context
        def purge(ctx: click.Context, assume_yes: bool) -> None:
            """把 pending_delete 笔记移入 <state_dir>/trash/ 并清除 sidecar 条目。"""
            tree: MemoryTree = ctx.obj
            pending = tree.list_pending_delete()
            if not pending:
                click.echo("没有待删除的笔记")
                return
            for path in pending:
                note_id = tree._find_entry_id(path) or ""
                for dep in _cognition_dependencies(tree, note_id):
                    click.echo(
                        f"⚠ {path.name} 被在研 cognition 引用: {dep.id}"
                        f"（{dep.entry_type}/{dep.status}）"
                    )
            if not assume_yes:
                click.confirm(f"确认把 {len(pending)} 条笔记移入回收站?", abort=True)
            trash_dir = tree.state_dir / "trash"
            trash_dir.mkdir(parents=True, exist_ok=True)
            for path in pending:
                note_id = tree._find_entry_id(path)
                dest = trash_dir / path.name
                if dest.exists():
                    dest = trash_dir / f"{note_id or 'note'}-{path.name}"
                shutil.move(str(path), str(dest))
                tree._remove_entry(path)
                click.echo(f"已移入回收站: {path.name} -> {dest.name}")

        @cli.command()
        @click.option(
            "--source",
            default="web",
            show_default=True,
            help="新文件归一化时写入 frontmatter 的默认来源",
        )
        @click.pass_context
        def sync(ctx: click.Context, source: str) -> None:
            """对齐笔记目录与索引：新文件归一化登记、外部删除注销。"""
            from scripts.memory.watcher import MemoryWatcher

            tree: MemoryTree = ctx.obj
            result = MemoryWatcher(tree, source=source).process_pending()
            click.echo(f"归一化: {len(result['normalized'])}")
            click.echo(f"新登记: {len(result['registered'])}")
            click.echo(f"注销: {len(result['deregistered'])}")
            click.echo(f"跳过: {len(result['skipped'])}")

        return cli

    def main(self, args: Optional[List[str]] = None) -> int:
        """命令行入口；直接运行时以进程退出码结束。

        Args:
            args: 命令行参数列表；None 时用 sys.argv[1:]。

        Returns:
            int: 退出码（0 成功）。
        """
        return self.cli.main(args=args, standalone_mode=False) or 0


if __name__ == "__main__":
    sys.exit(MemoryCLI().main())
