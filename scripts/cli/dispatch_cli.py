"""Atelierr 自动分发 CLI（通道产物 → 处理器 → 入库）。

用法:
    python -m scripts.cli.dispatch_cli links            # 扫描并处理抖音链接
    python -m scripts.cli.dispatch_cli links --dry-run  # 只报告不处理
    python -m scripts.cli.dispatch_cli todos            # 扫描并抽取待办事项
    python -m scripts.cli.dispatch_cli todos --dry-run  # 只报告不建笔记
    python -m scripts.cli.dispatch_cli media            # 扫描 attachments/ 截图录音并 OCR/转写
    python -m scripts.cli.dispatch_cli media --dry-run  # 只报告不处理
    python -m scripts.cli.dispatch_cli highlights       # 划重点清单勾中项转 wiki 摘录卡
    python -m scripts.cli.dispatch_cli digest           # 创建今日摘要笔记
    python -m scripts.cli.dispatch_cli feishu           # 飞书机器人长连接守护（收消息进库）

配置解析顺序与 memory_cli 一致：--config > 环境变量 ATELIERR_CONFIG >
./config/memory.yaml > 内置默认 ~/atelierr-data/{memory,state}。

定时部署见 docker/systemd/atelierr-links.service / .timer。
单条链接/单篇笔记/单个附件的失败不影响退出码（记入状态文件，下次自动
重试，3 次熔断）；仅当整体无法运行（如配置缺失）时 exit 1。
"""

from __future__ import annotations

import fcntl
import os
import sys
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional

import click

from scripts.cli.memory_cli import resolve_config_path
from scripts.dispatch.digest import DigestDispatcher
from scripts.dispatch.highlights import HighlightsDispatcher
from scripts.dispatch.links import LinkDispatcher
from scripts.dispatch.media import MediaDispatcher
from scripts.dispatch.notify import send_dispatch_notice
from scripts.dispatch.todos import TodoDispatcher
from scripts.memory.core import MemoryTree
from scripts.memory.resurface import ResurfaceManager

DEFAULT_ROOT = "~/atelierr-data/memory"
DEFAULT_STATE_DIR = "~/atelierr-data/state"


def _notify_failures(failures: List[Dict[str, Any]]) -> None:
    """有抓取失败时双通道推送（未配置/失败静默，不影响主流程）。

    处理成功不推送（用户自己贴的链接，无需马后炮）；失败必须推，
    否则用户无从知晓系统没抓到。
    """
    if failures:
        send_dispatch_notice(
            "Atelierr 抓取失败",
            f"{len(failures)} 条链接抓取失败，请检查后重新粘贴",
        )


def _notify_media_failures(failures: List[Dict[str, Any]]) -> None:
    """附件处理失败时推送（同上：成功不推，失败必推）。"""
    if failures:
        send_dispatch_notice(
            "Atelierr 处理失败",
            f"{len(failures)} 个附件处理失败，请检查文件后重新放入",
        )


def _feishu_ready() -> bool:
    """飞书通道是否可用（凭证齐备才发确认卡片）。

    链接/OCR 笔记的逐条「待确认」推送只在飞书可用时发出（确认按钮只
    存在于飞书卡片；ntfy 无按钮，文本推送保持原规则）；测试与
    ntfy-only 环境没有 FEISHU_* 变量，走原行为不推送。
    """
    from scripts.dispatch.feishu import ENV_APP_ID, ENV_APP_SECRET, ENV_CHAT_ID

    return all(
        os.environ.get(var, "").strip()
        for var in (ENV_APP_ID, ENV_APP_SECRET, ENV_CHAT_ID)
    )


def _notify_created_notes(
    title: str,
    message: str,
    created: List[str],
    *,
    skip_prefix: str = "",
) -> None:
    """新产出笔记逐条推送带「✅ 确认」按钮的卡片（confirm_note=文件名）。

    仅当飞书通道可用时推送；skip_prefix 命中的文件名（如划重点清单，
    不带「待确认」标签）不推。todos/dochealth 等汇总通知不走此路径。
    """
    if not _feishu_ready():
        return
    for filename in created:
        if skip_prefix and filename.startswith(skip_prefix):
            continue
        send_dispatch_notice(title, f"{message}：{filename}", confirm_note=filename)


def _notify_digest(counts: Dict[str, int]) -> None:
    """今日摘要创建成功后推送五节计数（未配置/失败静默）。"""
    send_dispatch_notice(
        "Atelierr 今日摘要",
        f"待确认 {counts['pending']}，提炼候选 {counts['undistilled']}，"
        f"待办 {counts['todos']}，今日复习 {counts['resurface']}，"
        f"昨日新入库 {counts['yesterday_new']}",
    )


@contextmanager
def _dispatch_lock(state_dir: str) -> Iterator[bool]:
    """对 state_dir/dispatch.lock 的 flock 排他互斥（拿不到锁 yield False）。

    links / media / todos / highlights 四个子命令共享这一把锁：手动运行
    与 15 分钟定时班次撞在同一分钟时，后到进程拿不到锁即跳过（对定时器
    而言跳过是正常行为，不算错误）。flock 随进程退出或 fd 关闭自动释放，
    无需清理 stale 锁文件；feishu 常驻守护等不加锁的命令不受影响。

    Args:
        state_dir: 状态目录（MemoryTree.state_dir，已展开 ~）。

    Yields:
        bool: 拿到排他锁为 True；被其他分发进程占用为 False。
    """
    lock_path = Path(state_dir) / "dispatch.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(lock_path, os.O_CREAT | os.O_RDWR)
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            yield False
        else:
            yield True
    finally:
        os.close(fd)


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
            """Atelierr 通道产物自动分发（links / media / todos / highlights / digest）。"""

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
            with _dispatch_lock(tree.state_dir) as locked:
                if not locked:
                    click.echo("已有分发任务在运行，本次跳过")
                    return
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
                if not dry_run:
                    _notify_failures(report["failed"])
                    if report["created"]:
                        _notify_created_notes(
                            "Atelierr 链接笔记待确认",
                            "链接笔记已转写入库",
                            report["created"],
                        )
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
            with _dispatch_lock(tree.state_dir) as locked:
                if not locked:
                    click.echo("已有分发任务在运行，本次跳过")
                    return
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

        @cli.command(name="media")
        @click.option(
            "--dry-run",
            "dry_run",
            is_flag=True,
            help="只扫描报告，不建笔记、不写状态、不加载引擎",
        )
        def media_command(dry_run: bool) -> None:
            """扫描 attachments/ 里的截图/录音并自动 OCR/转写入库。"""
            tree = self._build_tree()
            with _dispatch_lock(tree.state_dir) as locked:
                if not locked:
                    click.echo("已有分发任务在运行，本次跳过")
                    return
                report = MediaDispatcher(tree).run(dry_run=dry_run)
                click.echo(
                    f"扫描 {report['scanned']} 个附件，"
                    f"新发现 {report['found']} 个，"
                    f"跳过已处理 {report['skipped']} 个"
                )
                for filename in report["created"]:
                    # 划重点清单不带"待确认"（确认动作在勾中项转出的笔记上）
                    suffix = "" if filename.startswith("划重点-") else "（待确认）"
                    click.echo(f"  已创建: {filename}{suffix}")
                for failure in report["failed"]:
                    click.echo(f"  失败: {failure['file']} — {failure['error']}")
                if not dry_run:
                    _notify_media_failures(report["failed"])
                    if report["created"]:
                        _notify_created_notes(
                            "Atelierr OCR 笔记待确认",
                            "已识别入库",
                            report["created"],
                            skip_prefix="划重点-",
                        )
                if dry_run:
                    click.echo("（dry-run：未做处理）")

        @cli.command(name="highlights")
        @click.option(
            "--dry-run",
            "dry_run",
            is_flag=True,
            help="只扫描报告，不建卡片、不写状态",
        )
        def highlights_command(dry_run: bool) -> None:
            """扫描划重点清单，把人工勾中的候选转为 wiki 摘录卡。"""
            tree = self._build_tree()
            with _dispatch_lock(tree.state_dir) as locked:
                if not locked:
                    click.echo("已有分发任务在运行，本次跳过")
                    return
                report = HighlightsDispatcher(tree).run(dry_run=dry_run)
                click.echo(
                    f"扫描 {report['scanned']} 份清单，"
                    f"勾中 {report['ticked']} 条，"
                    f"跳过已转记 {report['skipped']} 条"
                )
                for filename in report["created"]:
                    click.echo(f"  已创建摘录卡: wiki/{filename}")
                if dry_run:
                    click.echo("（dry-run：未做处理）")

        @cli.command(name="digest")
        @click.option(
            "--dry-run",
            "dry_run",
            is_flag=True,
            help="只打印摘要内容，不建笔记",
        )
        def digest_command(dry_run: bool) -> None:
            """创建今日摘要笔记（当天已存在则跳过）。"""
            tree = self._build_tree()
            dispatcher = DigestDispatcher(
                tree, resurface=self._build_resurface(tree)
            )
            report = dispatcher.run(dry_run=dry_run)
            if report["skipped"]:
                click.echo("今日摘要已存在，跳过")
                return
            counts = report["counts"]
            click.echo(
                f"待确认 {counts['pending']}，待办 {counts['todos']}，"
                f"今日复习 {counts['resurface']}，"
                f"昨日新入库 {counts['yesterday_new']}"
            )
            if dry_run:
                click.echo(report["markdown"])
                click.echo("（dry-run：未建笔记）")
            else:
                click.echo(f"  已创建: {report['created']}")
                _notify_digest(report["counts"])

        @cli.command(name="feishu")
        def feishu_command() -> None:
            """启动飞书机器人长连接守护（收消息进库；Ctrl+C 停止）。"""
            from scripts.dispatch.feishu import FeishuBridge

            tree = self._build_tree()
            try:
                bridge = FeishuBridge.from_env(tree)
            except RuntimeError as exc:
                raise click.ClickException(str(exc))
            click.echo("飞书长连接已启动（消息 → memory/ 或 attachments/）")
            bridge.run_forever()

        return cli

    def _build_tree(self) -> MemoryTree:
        """按解析顺序构造 MemoryTree；配置损坏时抛 ClickException。"""
        resolved = resolve_config_path(self.config_path)
        if resolved:
            try:
                return MemoryTree.from_config(resolved)
            except (OSError, ValueError) as exc:
                raise click.ClickException(f"配置加载失败: {resolved}: {exc}")
        return MemoryTree(DEFAULT_ROOT, state_dir=DEFAULT_STATE_DIR)

    def _build_resurface(self, tree: MemoryTree) -> ResurfaceManager:
        """按同一配置构造复习队列管理器（无配置用默认窗口）。"""
        resolved = resolve_config_path(self.config_path)
        if resolved:
            try:
                return ResurfaceManager.from_config(resolved, tree=tree)
            except (OSError, ValueError) as exc:
                raise click.ClickException(
                    f"复习队列配置加载失败: {resolved}: {exc}"
                )
        return ResurfaceManager(tree)

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
