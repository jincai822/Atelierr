"""Atelierr 认知模块 CLI（COGNITION-SPEC v1.0 §6.3）。

独立入口：python -m scripts.cli.cognition_cli <command>。
cognition 不挂入 memory_cli；配置解析顺序与 memory_cli 一致：
--config 显式参数 > 环境变量 ATELIERR_CONFIG > ./config/memory.yaml >
内置默认 ~/atelierr-data（$OV 根，含 memory/ cognition/ state/）。

交互约束：
- create/promote/challenge resolve/reassess/answer/supersede/archive
  默认显示完整 diff 并要求确认；--dry-run 只预览不写盘。
- 不提供 --yes：确认代表用户在当前调用中的明确授权。
- 稳定退出码：0 成功；2 用法错误（click 内建）；3 对象不存在；
  4 schema/校验错误；5 revision 并发冲突。
- 术语隔离：cognition 显示“确信度”，memory 信号显示“新鲜度”。

用法:
    python -m scripts.cli.cognition_cli create --type belief --title "t" \
        --statement "s" --certainty 0.8
    python -m scripts.cli.cognition_cli list --type belief
    python -m scripts.cli.cognition_cli validate --json
"""

from __future__ import annotations

import difflib
import functools
import json
import os
import sys
from pathlib import Path
from typing import List, Optional, cast

import click

from scripts.cognition import (
    COGNITION_TYPES,
    DEFAULT_STATUS,
    ApprovalRecord,
    ChallengeResolution,
    CognitionError,
    CognitionManager,
    CognitionType,
    EvidenceRef,
    RevisionConflictError,
    WritePlan,
)

DEFAULT_CONFIG = Path("config/memory.yaml")
DEFAULT_OV = "~/atelierr-data"
DEFAULT_STATE_DIR = "~/atelierr-data/state"

#: 稳定退出码
EXIT_NOT_FOUND = 3
EXIT_INVALID = 4
EXIT_CONFLICT = 5


def _resolve_config_path(config_path: Optional[str]) -> Optional[str]:
    """解析配置文件路径：显式 > 环境变量 > ./config/memory.yaml > None。"""
    if config_path:
        return config_path
    env_path = os.environ.get("ATELIERR_CONFIG")
    if env_path:
        return env_path
    if DEFAULT_CONFIG.exists():
        return str(DEFAULT_CONFIG)
    return None


def _fail(code: int, message: str) -> None:
    """打印错误到 stderr 并以稳定退出码结束。"""
    click.echo(f"错误: {message}", err=True)
    raise click.exceptions.Exit(code)


def _guarded(fn):
    """把领域异常映射为稳定退出码的装饰器。"""

    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except RevisionConflictError as exc:
            _fail(EXIT_CONFLICT, str(exc))
        except FileExistsError as exc:
            _fail(EXIT_INVALID, str(exc))
        except CognitionError as exc:
            _fail(EXIT_INVALID, str(exc))
        except (KeyError, FileNotFoundError) as exc:
            _fail(EXIT_NOT_FOUND, exc.args[0] if exc.args else str(exc))
        except ValueError as exc:
            _fail(EXIT_INVALID, str(exc))

    return wrapper


def _certainty_text(certainty: Optional[float]) -> str:
    """确信度显示：默认两位小数（--json 走存储值）。"""
    return "（无）" if certainty is None else f"{certainty:.2f}"


class CognitionCLI:
    """认知模块 CLI（独立入口，不挂 memory_cli）。"""

    def __init__(self, config_path: Optional[str] = None) -> None:
        """初始化。

        Args:
            config_path: 配置文件路径；None 时按解析顺序寻找。
        """
        self.config_path = config_path
        self.cli = self._build_cli()

    @staticmethod
    def _build_manager(config_path: Optional[str]) -> CognitionManager:
        """按配置构造 CognitionManager；无配置时用内置默认 $OV。"""
        resolved = _resolve_config_path(config_path)
        if resolved is not None:
            return CognitionManager.from_config(resolved)
        return CognitionManager(DEFAULT_OV, state_dir=DEFAULT_STATE_DIR)

    def _build_cli(self) -> click.Group:
        """构造 click group 与各子命令。"""
        # pylint: disable=too-many-statements
        # 16 个子命令按规格 §6.3 内联声明于此；拆分会割裂命令表的单一事实源。

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
            """Atelierr 认知模块（belief/question/hypothesis 生命周期管理）。"""
            ctx.obj = self._build_manager(config_path or self.config_path)

        # --------------------------------------------------------------
        # 只读命令
        # --------------------------------------------------------------

        @cli.command("list")
        @click.option(
            "--type",
            "entry_type",
            type=click.Choice(COGNITION_TYPES),
            default=None,
            help="类型过滤",
        )
        @click.option("--status", default=None, help="状态过滤（显式可查非活动）")
        @click.option("--all", "include_inactive", is_flag=True, help="含非活动条目")
        @click.option("--json", "as_json", is_flag=True, help="JSON 输出存储值")
        @click.pass_context
        @_guarded
        def list_cmd(
            ctx: click.Context,
            entry_type: Optional[str],
            status: Optional[str],
            include_inactive: bool,
            as_json: bool,
        ) -> None:
            """列出认知条目（默认隐藏 refuted/superseded/archived）。"""
            manager: CognitionManager = ctx.obj
            entries = manager.list_entries(
                entry_type=cast(Optional[CognitionType], entry_type),
                status=status,
                include_inactive=include_inactive,
            )
            if as_json:
                click.echo(
                    json.dumps(
                        [
                            {
                                "id": e.id,
                                "type": e.entry_type,
                                "status": e.status,
                                "certainty": e.certainty,
                                "title": e.title,
                                "path": e.path.name,
                            }
                            for e in entries
                        ],
                        ensure_ascii=False,
                        indent=2,
                    )
                )
                return
            if not entries:
                click.echo("无匹配条目")
                return
            for e in entries:
                click.echo(
                    f"[{e.entry_type}/{e.status}] 确信度={_certainty_text(e.certainty)}"
                    f" {e.id[:12]}… {e.title}（{e.path.name}）"
                )

        @cli.command()
        @click.argument("entry_id")
        @click.option("--json", "as_json", is_flag=True, help="JSON 输出存储值")
        @click.pass_context
        @_guarded
        def show(ctx: click.Context, entry_id: str, as_json: bool) -> None:
            """展示单个条目（含证据、来源与修订历史）。"""
            manager: CognitionManager = ctx.obj
            entry = manager.get_entry(entry_id)
            if as_json:
                click.echo(
                    json.dumps(
                        {
                            "id": entry.id,
                            "title": entry.title,
                            "type": entry.entry_type,
                            "statement": entry.statement,
                            "status": entry.status,
                            "certainty": entry.certainty,
                            "certainty_updated_at": entry.certainty_updated_at,
                            "certainty_source": entry.certainty_source,
                            "created": entry.created,
                            "updated": entry.updated,
                            "revision": entry.revision,
                            "tags": list(entry.tags),
                            "origin": entry.origin,
                            "evidence": [ref.to_dict() for ref in entry.evidence],
                            "related": list(entry.related),
                            "supersedes": entry.supersedes,
                            "path": entry.path.name,
                        },
                        ensure_ascii=False,
                        indent=2,
                    )
                )
                return
            click.echo(f"id: {entry.id}")
            click.echo(f"标题: {entry.title}")
            click.echo(f"类型: {entry.entry_type} / 状态: {entry.status}")
            click.echo(f"陈述: {entry.statement}")
            click.echo(f"确信度: {_certainty_text(entry.certainty)}")
            if entry.certainty is not None:
                click.echo(f"确信度更新于: {entry.certainty_updated_at}")
                click.echo(f"确信度来源: {entry.certainty_source}")
            click.echo(
                f"revision: {entry.revision} | 创建: {entry.created} | 更新: {entry.updated}"
            )
            click.echo(f"来源: {entry.origin}")
            if entry.evidence:
                click.echo("证据:")
                for ref in entry.evidence:
                    click.echo(f"  - {ref.to_dict()}")
            if entry.related:
                click.echo(f"关联: {', '.join(entry.related)}")
            if entry.supersedes:
                click.echo(f"继任: {entry.supersedes}")
            click.echo(f"文件: {entry.path.name}")
            click.echo("--- 修订历史 ---")
            in_history = False
            for line in entry.content.splitlines():
                if line.startswith("## 修订历史"):
                    in_history = True
                    continue
                if in_history:
                    click.echo(line)

        @cli.group()
        def proposals() -> None:
            """未批准/已处理的 promotion 与 challenge 提案。"""

        @proposals.command("list")
        @click.option(
            "--kind",
            type=click.Choice(["promotion", "challenge"]),
            default=None,
            help="提案类型过滤",
        )
        @click.option(
            "--status",
            default="pending",
            show_default=True,
            help="状态过滤（pending/approved/rejected/resolved，all 为全部）",
        )
        @click.option("--json", "as_json", is_flag=True, help="JSON 输出")
        @click.pass_context
        @_guarded
        def proposals_list(
            ctx: click.Context, kind: Optional[str], status: str, as_json: bool
        ) -> None:
            """列出提案队列（默认只看待批准）。"""
            manager: CognitionManager = ctx.obj
            rows = [
                data
                for data in manager._load_proposals().values()
                if (kind is None or data.get("kind") == kind)
                and (status == "all" or data.get("status") == status)
            ]
            if as_json:
                click.echo(json.dumps(rows, ensure_ascii=False, indent=2))
                return
            if not rows:
                click.echo("无匹配提案")
                return
            for data in rows:
                click.echo(
                    f"[{data.get('kind')}/{data.get('status')}] {data.get('id')}"
                )
                if data.get("kind") == "promotion":
                    click.echo(
                        f"    来源 memory: {data.get('memory_id')} "
                        f"({data.get('memory_path')})"
                    )
                else:
                    click.echo(f"    目标 cognition: {data.get('entry_id')}")
                click.echo(
                    f"    陈述: {data.get('statement') or data.get('rationale')}"
                )
                for warning in data.get("warnings") or []:
                    click.echo(f"    ⚠ {warning}")

        @proposals.command("reject")
        @click.argument("proposal_id")
        @click.option("--reason", required=True, help="拒绝理由")
        @click.pass_context
        @_guarded
        def proposals_reject(ctx: click.Context, proposal_id: str, reason: str) -> None:
            """拒绝 promotion 提案（记录理由，不改 memory/cognition）。"""
            manager: CognitionManager = ctx.obj
            manager.reject_promotion(
                proposal_id,
                reason=reason,
                approval=ApprovalRecord(action="reject", reason=reason),
            )
            click.echo(f"已拒绝: {proposal_id}")

        @cli.command()
        @click.option("--json", "as_json", is_flag=True, help="JSON 输出")
        @click.pass_context
        @_guarded
        def validate(ctx: click.Context, as_json: bool) -> None:
            """逐文件校验 schema/状态机/引用（只读，不修复）。"""
            manager: CognitionManager = ctx.obj
            report = manager.validate()
            if as_json:
                click.echo(
                    json.dumps(
                        {
                            "checked": report.checked,
                            "ok": report.ok,
                            "errors": list(report.errors),
                            "index_drift": list(report.index_drift),
                        },
                        ensure_ascii=False,
                        indent=2,
                    )
                )
            else:
                click.echo(f"校验文件数: {report.checked}")
                if report.errors:
                    click.echo("错误:")
                    for error in report.errors:
                        click.echo(f"  - {error}")
                if report.index_drift:
                    click.echo("索引漂移（以 Markdown 为准，可 reindex 修复）:")
                    for item in report.index_drift:
                        click.echo(f"  - {item}")
                if report.ok:
                    click.echo("校验通过")
            if not report.ok:
                raise click.exceptions.Exit(EXIT_INVALID)

        @cli.command()
        @click.option("--dry-run", is_flag=True, help="只统计不写盘")
        @click.option("--json", "as_json", is_flag=True, help="JSON 输出")
        @click.pass_context
        @_guarded
        def reindex(ctx: click.Context, dry_run: bool, as_json: bool) -> None:
            """从 Markdown 重建派生索引。"""
            manager: CognitionManager = ctx.obj
            report = manager.rebuild_index(dry_run=dry_run)
            if as_json:
                click.echo(
                    json.dumps(
                        {
                            "scanned": report.scanned,
                            "rebuilt": report.rebuilt,
                            "errors": list(report.errors),
                            "dry_run": report.dry_run,
                        },
                        ensure_ascii=False,
                        indent=2,
                    )
                )
                return
            label = "（dry-run）" if dry_run else ""
            click.echo(f"扫描: {report.scanned} | 重建: {report.rebuilt}{label}")
            for error in report.errors:
                click.echo(f"  - {error}")

        # --------------------------------------------------------------
        # 写入命令（diff 预览 + 人工确认；--dry-run 不写盘）
        # --------------------------------------------------------------

        def _confirm_plan(plan: WritePlan, dry_run: bool) -> None:
            """显示完整 diff，确认后 commit；dry-run 只预览。"""
            for label, before, after in plan.diffs:
                diff = difflib.unified_diff(
                    before.splitlines(keepends=True),
                    after.splitlines(keepends=True),
                    fromfile=f"a/{label}",
                    tofile=f"b/{label}",
                )
                click.echo("".join(diff))
            click.echo(plan.summary)
            if dry_run:
                click.echo("（dry-run：未写入任何内容）")
                return
            click.confirm("确认执行?", abort=True)
            entry = plan.commit()
            click.echo(f"已完成: {entry.id}（r{entry.revision}，{entry.path.name}）")

        def _evidence_from_options(
            manager: CognitionManager,
            memory_ids: tuple,
            urls: tuple,
            notes: tuple,
            relation: str,
        ) -> List[EvidenceRef]:
            """把 --evidence-* 选项组装成证据引用列表（memory 解析真实路径快照）。"""
            from datetime import datetime

            refs: List[EvidenceRef] = []
            for memory_id in memory_ids:
                path, _ = manager._find_memory(memory_id)
                refs.append(
                    EvidenceRef(
                        kind="memory",
                        relation=relation,
                        id=memory_id,
                        path=path.name,
                    )
                )
            for url in urls:
                refs.append(
                    EvidenceRef(
                        kind="url",
                        relation=relation,
                        url=url,
                        accessed_at=datetime.now()
                        .astimezone()
                        .isoformat(timespec="seconds"),
                    )
                )
            for note in notes:
                refs.append(EvidenceRef(kind="manual", relation=relation, note=note))
            return refs

        @cli.command()
        @click.option(
            "--type",
            "entry_type",
            type=click.Choice(COGNITION_TYPES),
            required=True,
            help="认知类型",
        )
        @click.option("--title", required=True, help="人类可读标题")
        @click.option("--statement", required=True, help="原子陈述或问题")
        @click.option(
            "--certainty",
            type=float,
            default=None,
            help="确信度 [0.0, 1.0]（belief/hypothesis 必填）",
        )
        @click.option("--status", default=None, help="初始状态（默认取类型主状态）")
        @click.option("--tags", default=None, help="逗号分隔的标签列表")
        @click.option("--dry-run", is_flag=True, help="只预览 diff 不写盘")
        @click.pass_context
        @_guarded
        def create(
            ctx: click.Context,
            entry_type: str,
            title: str,
            statement: str,
            certainty: Optional[float],
            status: Optional[str],
            tags: Optional[str],
            dry_run: bool,
        ) -> None:
            """手工创建认知条目（origin.kind=manual）。"""
            manager: CognitionManager = ctx.obj
            tag_list = [t.strip() for t in tags.split(",") if t.strip()] if tags else []
            plan = manager.plan_create_entry(
                entry_type=cast(CognitionType, entry_type),
                title=title,
                statement=statement,
                status=status or DEFAULT_STATUS[entry_type],
                certainty=certainty,
                tags=tag_list,
                approval=ApprovalRecord(
                    action="create", reason="CLI 手工创建", source="human_assessment"
                ),
            )
            _confirm_plan(plan, dry_run)

        @cli.command()
        @click.argument("memory_id")
        @click.option(
            "--type",
            "entry_type",
            type=click.Choice(COGNITION_TYPES),
            required=True,
            help="认知类型",
        )
        @click.option("--statement", required=True, help="原子陈述或问题")
        @click.option("--title", default=None, help="标题（默认取陈述前 30 字）")
        @click.option("--rationale", default="", help="提名理由")
        @click.option(
            "--certainty",
            type=float,
            default=None,
            help="建议确信度（question 不得提供）",
        )
        @click.option("--status", default=None, help="建议状态（默认取类型主状态）")
        @click.pass_context
        @_guarded
        def nominate(
            ctx: click.Context,
            memory_id: str,
            entry_type: str,
            statement: str,
            title: Optional[str],
            rationale: str,
            certainty: Optional[float],
            status: Optional[str],
        ) -> None:
            """提名 memory 升级为 cognition（只创建提案，不改任何文件）。"""
            manager: CognitionManager = ctx.obj
            proposal = manager.nominate_memory(
                memory_id,
                entry_type=cast(CognitionType, entry_type),
                title=title or statement[:30],
                statement=statement,
                rationale=rationale,
                proposed_status=status or DEFAULT_STATUS[entry_type],
                proposed_certainty=certainty,
            )
            click.echo(f"已创建提名: {proposal.id}")
            sidecar = manager._memory_sidecar_entry(memory_id)
            if sidecar is not None:
                click.echo(
                    f"来源新鲜度（memory confidence）: "
                    f"{sidecar.get('confidence', 0):.3f}（仅供参考，不构成升级门槛）"
                )
            for warning in proposal.warnings:
                click.echo(f"⚠ {warning}")

        @cli.command()
        @click.argument("proposal_id")
        @click.option(
            "--certainty",
            type=float,
            default=None,
            help="批准的确信度（默认取提案建议值）",
        )
        @click.option("--status", default=None, help="批准的状态（默认取提案建议值）")
        @click.option("--dry-run", is_flag=True, help="只预览 diff 不写盘")
        @click.pass_context
        @_guarded
        def promote(
            ctx: click.Context,
            proposal_id: str,
            certainty: Optional[float],
            status: Optional[str],
            dry_run: bool,
        ) -> None:
            """批准提名：创建恰好一个 cognition（来源 memory 不变）。"""
            manager: CognitionManager = ctx.obj
            data = manager._require_proposal(proposal_id, "promotion")
            plan = manager.plan_approve_promotion(
                proposal_id,
                status=status or str(data["proposed_status"]),
                certainty=(
                    certainty
                    if certainty is not None
                    else data.get("proposed_certainty")
                ),
                approval=ApprovalRecord(
                    action="approve",
                    reason="CLI 批准提名",
                    source="human_approved_agent_assessment",
                ),
            )
            for warning in data.get("warnings") or []:
                click.echo(f"⚠ {warning}")
            _confirm_plan(plan, dry_run)

        class _ChallengeGroup(click.Group):
            """`challenge <id>` 默认走 propose；`challenge resolve ...` 走子命令。"""

            def resolve_command(self, ctx, args):
                if args and args[0] != "resolve" and not args[0].startswith("-"):
                    args = ["propose"] + list(args)
                return super().resolve_command(ctx, args)

        @cli.group(cls=_ChallengeGroup)
        def challenge() -> None:
            """挑战条目：propose（默认）与 resolve 两个动作。"""

        @challenge.command("propose")
        @click.argument("entry_id")
        @click.option(
            "--evidence-memory",
            "memory_ids",
            multiple=True,
            help="挑战证据：memory id（可多次）",
        )
        @click.option(
            "--evidence-url", "urls", multiple=True, help="挑战证据：绝对 URL（可多次）"
        )
        @click.option(
            "--evidence-note",
            "notes",
            multiple=True,
            help="挑战证据：人工摘要（可多次）",
        )
        @click.option("--reason", required=True, help="挑战理由")
        @click.option("--certainty", type=float, default=None, help="建议确信度")
        @click.option("--status", default=None, help="建议状态")
        @click.pass_context
        @_guarded
        def challenge_propose(
            ctx: click.Context,
            entry_id: str,
            memory_ids: tuple,
            urls: tuple,
            notes: tuple,
            reason: str,
            certainty: Optional[float],
            status: Optional[str],
        ) -> None:
            """对条目发起挑战（只创建提案，批准前不改 cognition）。"""
            manager: CognitionManager = ctx.obj
            refs = _evidence_from_options(
                manager, memory_ids, urls, notes, "challenges"
            )
            if not refs:
                _fail(EXIT_INVALID, "挑战必须附至少一条 --evidence-* 证据")
            proposal = manager.propose_challenge(
                entry_id,
                evidence=refs,
                rationale=reason,
                proposed_certainty=certainty,
                proposed_status=status,
            )
            click.echo(f"已创建挑战提案: {proposal.id}（目标 {proposal.entry_id}）")

        @challenge.command("resolve")
        @click.argument("proposal_id")
        @click.option(
            "--resolution",
            type=click.Choice(["reject", "defer", "accept"]),
            required=True,
            help="处理结果",
        )
        @click.option(
            "--certainty",
            type=float,
            default=None,
            help="accept 时由用户指定的新确信度",
        )
        @click.option(
            "--status", default=None, help="defer 可置 questioned；accept 可指定新状态"
        )
        @click.option("--reason", required=True, help="处理理由")
        @click.option("--dry-run", is_flag=True, help="只预览 diff 不写盘")
        @click.pass_context
        @_guarded
        def challenge_resolve(
            ctx: click.Context,
            proposal_id: str,
            resolution: str,
            certainty: Optional[float],
            status: Optional[str],
            reason: str,
            dry_run: bool,
        ) -> None:
            """处理挑战提案（reject/defer/accept）。"""
            manager: CognitionManager = ctx.obj
            plan = manager.plan_resolve_challenge(
                proposal_id,
                resolution=cast(ChallengeResolution, resolution),
                certainty=certainty,
                status=status,
                rationale=reason,
                approval=ApprovalRecord(
                    action=f"challenge-{resolution}",
                    reason=reason,
                    source="human_assessment",
                ),
            )
            _confirm_plan(plan, dry_run)

        @cli.command()
        @click.argument("entry_id")
        @click.option(
            "--evidence-memory",
            "memory_ids",
            multiple=True,
            help="复核证据：memory id（可多次）",
        )
        @click.option(
            "--evidence-url", "urls", multiple=True, help="复核证据：绝对 URL（可多次）"
        )
        @click.option(
            "--evidence-note",
            "notes",
            multiple=True,
            help="复核证据：人工摘要（可多次）",
        )
        @click.option("--certainty", type=float, default=None, help="新确信度")
        @click.option("--status", required=True, help="新状态")
        @click.option("--reason", required=True, help="复核理由")
        @click.option("--dry-run", is_flag=True, help="只预览 diff 不写盘")
        @click.pass_context
        @_guarded
        def reassess(
            ctx: click.Context,
            entry_id: str,
            memory_ids: tuple,
            urls: tuple,
            notes: tuple,
            certainty: Optional[float],
            status: str,
            reason: str,
            dry_run: bool,
        ) -> None:
            """复核条目：附加证据并更新确信度/状态（人工批准）。"""
            manager: CognitionManager = ctx.obj
            refs = _evidence_from_options(manager, memory_ids, urls, notes, "context")
            plan = manager.plan_reassess_entry(
                entry_id,
                evidence=refs,
                certainty=certainty,
                status=status,
                rationale=reason,
                approval=ApprovalRecord(action="reassess", reason=reason),
            )
            _confirm_plan(plan, dry_run)

        @cli.command()
        @click.argument("entry_id")
        @click.option("--answer", default="", help="答案摘要")
        @click.option(
            "--related", "related", multiple=True, help="关联 cognition id（可多次）"
        )
        @click.option("--dry-run", is_flag=True, help="只预览 diff 不写盘")
        @click.pass_context
        @_guarded
        def answer(
            ctx: click.Context,
            entry_id: str,
            answer: str,
            related: tuple,
            dry_run: bool,
        ) -> None:
            """回答 question（必须给答案摘要或关联条目）。"""
            manager: CognitionManager = ctx.obj
            plan = manager.plan_answer_question(
                entry_id,
                answer=answer,
                related_entries=related,
                approval=ApprovalRecord(
                    action="answer", reason=answer.strip()[:80] or "关联条目回答"
                ),
            )
            _confirm_plan(plan, dry_run)

        @cli.command()
        @click.argument("entry_id")
        @click.option("--statement", required=True, help="继任条目的新陈述")
        @click.option(
            "--certainty",
            type=float,
            default=None,
            help="继任条目确信度（belief/hypothesis 必填）",
        )
        @click.option("--reason", required=True, help="实质修订理由")
        @click.option("--dry-run", is_flag=True, help="只预览 diff 不写盘")
        @click.pass_context
        @_guarded
        def supersede(
            ctx: click.Context,
            entry_id: str,
            statement: str,
            certainty: Optional[float],
            reason: str,
            dry_run: bool,
        ) -> None:
            """实质修订：创建继任条目，旧条目标 superseded。"""
            manager: CognitionManager = ctx.obj
            plan = manager.plan_supersede_entry(
                entry_id,
                replacement_statement=statement,
                replacement_certainty=certainty,
                rationale=reason,
                approval=ApprovalRecord(action="supersede", reason=reason),
            )
            _confirm_plan(plan, dry_run)

        @cli.command()
        @click.argument("entry_id")
        @click.option("--reason", required=True, help="归档理由")
        @click.option("--dry-run", is_flag=True, help="只预览 diff 不写盘")
        @click.pass_context
        @_guarded
        def archive(
            ctx: click.Context, entry_id: str, reason: str, dry_run: bool
        ) -> None:
            """归档条目（文件保留原路径，默认列表隐藏）。"""
            manager: CognitionManager = ctx.obj
            plan = manager.plan_archive_entry(
                entry_id,
                reason=reason,
                approval=ApprovalRecord(action="archive", reason=reason),
            )
            _confirm_plan(plan, dry_run)

        return cli

    def main(self, args: Optional[List[str]] = None) -> int:
        """命令行入口；直接运行时以进程退出码结束。

        Args:
            args: 命令行参数列表；None 时用 sys.argv[1:]。

        Returns:
            int: 退出码（0 成功；1 用户取消确认）。
        """
        try:
            return self.cli.main(args=args, standalone_mode=False) or 0
        except click.Abort:
            click.echo("已取消", err=True)
            return 1


if __name__ == "__main__":
    sys.exit(CognitionCLI().main())
