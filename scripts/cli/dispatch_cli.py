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
import json
import os
import sys
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional

import click
import frontmatter

from scripts.cli.memory_cli import resolve_config_path
from scripts.dispatch.archive import derive_archive_dir
from scripts.dispatch.digest import DigestDispatcher
from scripts.dispatch.feishu import send_resurface_feishu, send_todo_feishu
from scripts.dispatch.highlights import HighlightsDispatcher
from scripts.dispatch.links import LinkDispatcher
from scripts.dispatch.media import MediaDispatcher
from scripts.dispatch.notify import send_dispatch_notice
from scripts.dispatch.prompt import PromptStore
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


def _archive_hint(note_path: Path) -> Optional[str]:
    """产出「建议归档：<平台>/[<中图法标签>/]」提示行；取不到返回 None。

    目录推导与飞书卡片「📁 确认并归档」按钮共用
    ``scripts.dispatch.archive.derive_archive_dir``（单一规则源，防止
    两处漂移）：lark → 飞书，media → 媒体，其它 source 取 tags 里
    第一个平台标签（如 抖音/小红书）；中图法类目（``^[A-Z]{1,3}\\d*-``，
    如 B84-心理学）有则进二级。平台推不出（提示行场景）返回 None——
    建议行只是可选项，绝不影响通知发送；归档按钮场景则兜底 媒体/。

    Args:
        note_path: 笔记文件路径（通常刚产出在 memory/ 根层）。

    Returns:
        Optional[str]: 如 ``建议归档：抖音/B84-心理学/`` 或 None。
    """
    try:
        post = frontmatter.loads(note_path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001 - 提示行失败静默省略
        return None
    platform, category = derive_archive_dir(post)
    if not platform:
        return None
    hint = f"建议归档：{platform}/"
    if category:
        hint += f"{category}/"
    return hint


def _notify_created_notes(
    title: str,
    message: str,
    created: List[str],
    *,
    notes_dir: Path,
    skip_prefix: str = "",
) -> None:
    """新产出笔记逐条推送带「✅ 确认」按钮的卡片（confirm_note=文件名）。

    仅当飞书通道可用时推送；skip_prefix 按文件名（basename）匹配
    （created 可能带 ``系统/`` 前缀——划重点清单落在机器产物区），
    命中者（不带「待确认」标签）不推。正文末尾附「建议归档」提示行
    （读笔记取平台/中图法标签，取不到就省略，绝不影响推送）。
    todos/dochealth 等汇总通知不走此路径。

    Args:
        title: 通知标题。
        message: 通知正文前缀。
        created: 新产出笔记相对路径列表（可能含 ``系统/`` 前缀）。
        notes_dir: 笔记根目录（读 frontmatter 建议归档提示用）。
        skip_prefix: 按 basename 命中该前缀的不推送（如 划重点-）。
    """
    if not _feishu_ready():
        return
    for filename in created:
        if skip_prefix and Path(filename).name.startswith(skip_prefix):
            continue
        body = f"{message}：{filename}"
        hint = _archive_hint(notes_dir / filename)
        if hint:
            body = f"{body}\n{hint}"
        send_dispatch_notice(title, body, confirm_note=filename)


def _notify_todos(created: List[str], tree: MemoryTree, limit: int = 5) -> None:
    """新建待办：逐条推「✅ 已完成」卡片 + 同步建飞书任务（失败均静默）。

    任务同步是单向的（Obsidian → 飞书）：标题/截止取自待办笔记的
    ``- [ ]`` 任务行；点卡片「✅ 已完成」时回写任务完成
    （FeishuBridge._handle_todo_done）。上限防刷屏。
    """
    from scripts.dispatch.task_sync import create_task_for_todo

    for filename in created[:limit]:
        send_todo_feishu(filename)
        title, due = _parse_todo_task(tree.notes_dir / filename)
        if not title:
            continue
        create_task_for_todo(tree.state_dir, filename, title, due)
        if due:
            _add_todo_due_event(tree, title, due)


def _add_todo_due_event(tree: MemoryTree, title: str, due: str) -> None:
    """带截止的待办上「Atelierr」日历（全天事件；失败只 log）。"""
    try:
        from scripts.dispatch.feishu_calendar import create_all_day_event

        create_all_day_event(
            tree.state_dir, f"待办截止：{title}", due,
            description="Atelierr 待办（单向同步，完成请在飞书卡片点 ✅）",
        )
    except Exception as exc:  # noqa: BLE001 - 日历失败绝不影响待办主流程
        print(f"[feishu] todo due event fail: {exc}", flush=True)


def _parse_todo_task(note_path: Path) -> tuple:
    """从待办笔记提取任务文本与截止日（``- [ ] 文本 📅 YYYY-MM-DD``）。

    Returns:
        tuple: (title, due)；文件缺失/无任务行返回 (None, None)。
    """
    import re

    try:
        body = frontmatter.loads(note_path.read_text(encoding="utf-8")).content
    except Exception:  # noqa: BLE001 - 读不到就没有任务可建
        return None, None
    match = re.search(r"^\s*- \[ \] (?P<text>.+?)\s*$", body, re.M)
    if not match:
        return None, None
    text = match.group("text")
    due = None
    due_match = re.search(r"📅\s*(\d{4}-\d{2}-\d{2})\s*$", text)
    if due_match:
        due = due_match.group(1)
        text = text[: due_match.start()].strip()
    return text.strip() or None, due


def _notify_digest(
    counts: Dict[str, int], pin_state: Optional[Path] = None
) -> None:
    """今日摘要创建成功后推送五节计数（未配置/失败静默）。

    飞书侧置顶该摘要卡并自动替换昨日置顶（pin_state 登记表）——
    进会话第一眼就是今天盘面。
    """
    send_dispatch_notice(
        "Atelierr 今日摘要",
        f"待确认 {counts['pending']}，提炼候选 {counts['undistilled']}，"
        f"待办 {counts['todos']}，今日复习 {counts['resurface']}，"
        f"昨日新入库 {counts['yesterday_new']}",
        pin=True,
        pin_state=pin_state,
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
                            notes_dir=tree.notes_dir,
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
                if not dry_run:
                    _notify_todos(report["created"], tree)
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
                    # 划重点清单不带"待确认"（确认动作在勾中项转出的笔记上）；
                    # 清单在 系统/ 下（created 带前缀），按文件名判断
                    suffix = "" if Path(filename).name.startswith("划重点-") else "（待确认）"
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
                            notes_dir=tree.notes_dir,
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

        @cli.command(name="prompt-open")
        @click.argument("kind")
        @click.argument("message")
        @click.option(
            "--form",
            "form_questions",
            multiple=True,
            help="表单模式：每个 --form 是一个问题，推送为可填写的表单卡"
            "（卡片内逐问作答、一次提交收齐）；不传则推送纯文本卡",
        )
        @click.option(
            "--no-send",
            "no_send",
            is_flag=True,
            help="只登记会话，不推送（问题已另行发出时用）",
        )
        def prompt_open_command(kind: str, message: str, no_send: bool, form_questions: tuple) -> None:
            """开启飞书问答会话：推送问题并登记待答状态。

            会话 open 期间，用户在飞书里的文本回复计入答案（不捕获为
            笔记），回「跳过」/「完成」结束。供周回顾等反思仪式使用。
            --form 模式推表单卡（schema 2.0），提交后答案一次收齐并
            自动关闭会话；文本作答路径始终可用。
            """
            tree = self._build_tree()
            store = PromptStore(tree.state_dir)
            if store.is_open():
                click.echo("已有进行中的问答会话，先 prompt-collect 或等用户结束")
                return
            questions = list(form_questions) if form_questions else [message]
            if not no_send:
                if not _feishu_ready():
                    click.echo("飞书未配置，无法推送问题")
                    return
                if form_questions:
                    from scripts.dispatch.feishu import prompt_form_card, send_feishu_card

                    card = prompt_form_card(
                        f"Atelierr 问答（{kind}）", message, questions
                    )
                    sent = send_feishu_card(card)
                else:
                    from scripts.dispatch.feishu import send_feishu

                    sent = send_feishu(f"Atelierr 问答（{kind}）", message)
                if not sent:
                    click.echo("飞书推送失败，会话未登记")
                    return
            store.open(kind, questions)
            mode = "表单卡" if form_questions else "文本卡"
            click.echo(f"问答会话已开启（kind={kind}，{mode}），等待飞书回复")

        @cli.command(name="prompt-collect")
        def prompt_collect_command() -> None:
            """汇总当前问答会话的答案（JSON 输出）并关闭会话。"""
            tree = self._build_tree()
            data = PromptStore(tree.state_dir).close()
            if not data:
                click.echo("无问答会话")
                return
            answers = data.get("answers") or []
            click.echo(json.dumps(data, ensure_ascii=False, indent=2))
            click.echo(f"共 {len(answers)} 条回答，会话已关闭")

        @cli.command(name="prompt-status")
        def prompt_status_command() -> None:
            """查看当前问答会话状态。"""
            tree = self._build_tree()
            data = PromptStore(tree.state_dir).load()
            if not data or data.get("status") != "open":
                click.echo("无进行中的问答会话")
                return
            answers = data.get("answers") or []
            click.echo(
                f"会话 open：kind={data.get('kind')}，"
                f"已收到 {len(answers)} 条回答，"
                f"提问于 {data.get('asked_at')}"
            )

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
                _notify_digest(
                    report["counts"],
                    pin_state=Path(tree.state_dir) / "feishu_pins.json",
                )
                # 今日复习卡：只给标题（先想），按钮才打开原文（再看）
                send_resurface_feishu(report["review"])

        @cli.command(name="board")
        def board_command() -> None:
            """同步知识库看板（飞书多维表格）一轮：全量笔记元数据单向上行。"""
            tree = self._build_tree()
            from scripts.dispatch.board import sync_board

            report = sync_board(tree)
            if not report:
                click.echo("看板同步失败（飞书未配置或 bitable/drive 权限未开，见日志）")
                return
            click.echo(
                f"看板已同步：新增 {report['created']}，"
                f"更新 {report['updated']}，共 {report['total']} 条"
            )
            click.echo(f"看板地址: {report['url']}")

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
