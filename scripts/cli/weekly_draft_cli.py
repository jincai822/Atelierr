"""周日 $weekly 初稿自动产出（第二刀，2026-09-20 用户拍板）。

每周日 08:47（atelier-weekly-draft.timer）先于 09:13 表单卡：
车间司机（pi 非交互）按 .claude/commands/weekly.md 自动综合
成文，落 memory/wiki/reflections/<today>-weekly-draft.md 并
推飞书。人起床后读初稿、答 09:13 四问，答案机械落盘
<date>-weekly.md——机器初稿与人工定稿同名错开，各司其职。

红线：
- pi 口令里唯一允许的写入目标是 <date>-weekly-draft.md，其余
  任何既有文件一个字节都不许动（车间「✍️向下写 → memory/wiki/」
  接口之内）；
- 推送只含文件名与开头数行（卡片长度与隐私双重考虑）；
- pi 失败/产出缺失 → 推送失败通知并留日志，绝不静默。
"""

from __future__ import annotations

import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional, Tuple

import click

from scripts.cli.memory_cli import DEFAULT_ROOT, DEFAULT_STATE_DIR, resolve_config_path
from scripts.memory.core import MemoryTree

#: pi CLI 绝对路径（systemd user service 默认 PATH 不含 ~/.local/bin）；
#: 环境变量 ATELIERR_PI_BIN 可覆盖（测试注入假 pi 用）
PI_BIN_DEFAULT = "/home/cj1024/.local/bin/pi"

#: pi 非交互超时（秒）：读 7 天素材 + 综合成文，给足余量
PI_TIMEOUT = 1200

#: 车间说明书（$weekly 流程的唯一事实源）
WEEKLY_SPEC = "/srv/workspaces/Atelierr/.claude/commands/weekly.md"

#: 路径注册表（口令里交给 pi 查 $OV 各 tier）
PATHS_REGISTRY = "/srv/workspaces/Atelierr/harness/paths.toml"


def build_prompt(
    draft_path: Path, vault_root: Path, kit_path: Optional[Path] = None
) -> str:
    """构造车间口令：流程唯一事实源是 weekly.md，口令只做边界约束。

    Args:
        draft_path: 初稿落盘绝对路径（唯一允许写入的文件）。
        vault_root: vault 根（$OV），口令里交给 pi 查各 tier。
        kit_path: 本周素材包路径（2026-09-22 系统级优化①：应用层预聚合，
            车间读一个文件拿全本周数据——省 token、素材固定、质量稳）；
            None 时口令不含素材包行（预聚合失败不阻塞班次）。
    """
    kit_line = (
        f"本周素材包已预生成在 {kit_path}（捕获统计/新入库清单/待办/"
        f"默写记录/最近反思都在里面），先读它拿全本周数据；"
        if kit_path is not None
        else ""
    )
    return f"""你是 Atelierr 的车间管家，现在自动执行车间口令 $weekly（周日初稿班次）。

步骤：
1. 读 {WEEKLY_SPEC}，严格按其中的 Weekly Review 流程收集素材并综合成文。
   路径注册表在 {PATHS_REGISTRY}，$OV 指 {vault_root}。
2. 先续前情再动笔（2026-09-22 问题 3 裁决：车间无跨会话记忆，传承
   全靠文件）：{kit_line}再读 memory/wiki/reflections/ 里最近一次周回顾
   初稿/定稿与最新几条反思（存在才读）——上周「下周建议」的跟进情况
   要写进本周概览；profile/ 画像（存在才读）把握长期目标。
3. 只读收集：memory/、inbox/、memory/wiki/cognition/、profile/
   （存在才读），绝不改写任何既有文件。
4. 把周回顾初稿写入 {draft_path}（这是唯一允许写入的文件，已存在则覆盖；
   其余任何文件一个字节都不许动）。初稿用中文，结构：本周概览 → 进展与
   亮点 → 卡点与内耗信号 → 知识沉淀（wiki 链接到相关笔记）→ 升华候选 →
   下周建议。末尾附一行「本稿由车间自动产出（$weekly 周日班次），待人工修订」。
5. 「升华候选」必填，回答一个问题：本周哪条值得升华？从本周新确认归档
   进 memory/ 各领域的笔记里挑 1~3 条最值得提炼进 wiki/ 的，每条一句
   理由并用 [[wikilink]] 指回原笔记；只提名不执行提炼。本周没有就照实
   写「无——积累不足，继续沉淀」，不许硬凑。
6. 全程不问人（非交互班次，没有可问的人）；素材缺如就照实写缺如。
7. 完成后 stdout 只打印初稿文件的绝对路径，别的什么都别打印。"""


def run_workshop(
    prompt: str, *, pi_bin: str = PI_BIN_DEFAULT, timeout: int = PI_TIMEOUT
) -> Tuple[bool, str]:
    """非交互调 pi 执行口令。

    Returns:
        Tuple[bool, str]: (是否成功, stdout 末段或错误描述)。
    """
    try:
        proc = subprocess.run(
            [pi_bin, "-p", "--no-session", prompt],
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd="/srv/workspaces/Atelierr",
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return False, f"pi 调用失败: {exc}"
    tail = (proc.stdout or "").strip()[-400:]
    if proc.returncode != 0:
        err = (proc.stderr or "").strip()[-200:]
        return False, f"pi 退出码 {proc.returncode}: {err or tail}"
    return True, tail


def collect_excerpt(draft_path: Path, max_chars: int = 300) -> str:
    """取初稿开头数行作推送摘要（去 frontmatter，失败返回空串）。"""
    try:
        text = draft_path.read_text(encoding="utf-8")
    except OSError:
        return ""
    lines = [ln.strip() for ln in text.splitlines() if ln.strip() and ln.strip() != "---"]
    # 跳过 frontmatter 键值行（简单判：含 ': ' 且位于首个 '# ' 之前）
    body: list[str] = []
    for ln in lines:
        if ln.startswith("#"):
            body.append(ln)
            continue
        if not body and (": " in ln or ln.endswith(":")):
            continue
        body.append(ln)
    excerpt = "\n".join(body)
    return excerpt[:max_chars]


def build_weekly_kit(tree: MemoryTree, today: str) -> Path:
    """预聚合本周素材包（2026-09-22 系统级优化①）：把车间周回顾需要的
    本周数据写成 ``state/weekly-kit-<today>.md``——车间读一个文件拿全
    本周数据，不用现场翻库（省 token、素材固定、周报质量稳）。

    内容五节：捕获统计（含信息食谱）/ 新入库清单 / 待办进行中 /
    最近反思 / 本周默写记录（提取练习留痕）。全部只读聚合；落 state/
    （机器工作区，不是笔记，不进扫描域）。

    Args:
        tree: MemoryTree 实例。
        today: 本地日期（YYYY-MM-DD）。

    Returns:
        Path: 素材包路径。
    """
    import json
    from datetime import timedelta

    import frontmatter

    from scripts.dispatch.stats import capture_stats, diet_line, render_weekly_stats

    cutoff = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")
    lines: list = [f"# 本周素材包（{today}）", ""]
    lines += ["## 捕获统计", ""]
    lines += render_weekly_stats(capture_stats(tree, days=7))
    lines.append(diet_line(tree, days=7, today=today))

    lines += ["", "## 新入库清单", ""]
    skip_dirs = {"系统", "templates", "distilled", "wiki", "daily-notes"}
    new_notes: list = []
    for path in tree.iter_all_note_files():
        rel = path.relative_to(tree.notes_dir)
        if any(part in skip_dirs for part in rel.parts[:-1]):
            continue
        try:
            post = frontmatter.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if str(post.get("source") or "") in ("digest", "system"):
            continue
        if {str(t) for t in (post.get("tags") or [])} & {"待办", "待确认"}:
            continue
        created = str(post.get("created") or "")[:10]
        if created >= cutoff:
            new_notes.append((created, str(post.get("title") or path.stem)))
    new_notes.sort(reverse=True)
    lines += [f"- [[{title}]]（{stamp}）" for stamp, title in new_notes] or ["- 无"]

    lines += ["", "## 待办进行中", ""]
    todos: list = []
    for path in tree.iter_all_note_files():
        try:
            post = frontmatter.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if "待办" in {str(t) for t in (post.get("tags") or [])}:
            todos.append(str(post.get("title") or path.stem))
    lines += [f"- [[{title}]]" for title in sorted(todos)] or ["- 无"]

    lines += ["", "## 最近反思", ""]
    refl_dir = Path(tree.notes_dir) / "wiki" / "reflections"
    refl = sorted(refl_dir.glob("*.md"), reverse=True)[:3] if refl_dir.is_dir() else []
    lines += [f"- [[{p.stem}]]" for p in refl] or ["- 无"]

    lines += ["", "## 本周默写记录", ""]
    recalls: list = []
    outcomes = Path(tree.state_dir) / "resurface_outcomes.jsonl"
    if outcomes.is_file():
        try:
            for raw in outcomes.read_text(encoding="utf-8").splitlines():
                try:
                    record = json.loads(raw)
                except ValueError:
                    continue
                if not record.get("recall"):
                    continue
                if str(record.get("ts") or "")[:10] >= cutoff:
                    recalls.append(
                        f"- {str(record['ts'])[:10]} {record.get('note_id')}"
                        f"：{record['recall']}"
                    )
        except OSError:
            pass
    lines += recalls or ["- 无"]

    kit = Path(tree.state_dir) / f"weekly-kit-{today}.md"
    kit.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return kit


def _notify(title: str, message: str) -> None:
    """双通道推送（失败隔离，绝不影响主流程退出码）。"""
    try:
        from scripts.dispatch.notify import send_dispatch_notice

        send_dispatch_notice(title, message)
    except Exception as exc:  # noqa: BLE001 - 通知失败只留日志
        print(f"[weekly-draft] notify fail: {exc}", flush=True)


def _build_tree(config_path: Optional[str]) -> MemoryTree:
    resolved = resolve_config_path(config_path)
    if resolved is not None:
        return MemoryTree.from_config(resolved)
    return MemoryTree(DEFAULT_ROOT, state_dir=DEFAULT_STATE_DIR)


@click.command()
@click.option("--config", "config_path", default=None, help="配置文件路径")
@click.option(
    "--dry-run", is_flag=True, help="只打印口令与目标路径，不调 pi 不推送"
)
def main(config_path: Optional[str], dry_run: bool) -> None:
    """周日 $weekly 初稿班次入口（atelier-weekly-draft.service 调用）。"""
    tree = _build_tree(config_path)
    vault_root = Path(tree.notes_dir).parent
    today = datetime.now().strftime("%Y-%m-%d")
    draft = Path(tree.notes_dir) / "wiki" / "reflections" / f"{today}-weekly-draft.md"
    kit: Optional[Path] = None
    try:
        kit = build_weekly_kit(tree, today)
    except Exception as exc:  # noqa: BLE001 - 素材包失败不阻塞班次（车间现场读）
        print(f"[weekly-draft] kit fail（继续无素材包跑）: {exc}", flush=True)
    prompt = build_prompt(draft, vault_root, kit)
    if dry_run:
        print(f"draft: {draft}\n--- prompt ---\n{prompt}")
        return

    import os

    pi_bin = os.environ.get("ATELIERR_PI_BIN", PI_BIN_DEFAULT)
    # 跑前快照：同名文件同日重跑时，只有 mtime 真的更新才算本班次产出
    # （否则 pi 失败而旧稿还在，会把失败误报成成功）。
    mtime_before = draft.stat().st_mtime_ns if draft.is_file() else None
    ok, detail = run_workshop(prompt, pi_bin=pi_bin)
    produced = (
        draft.is_file()
        and (mtime_before is None or draft.stat().st_mtime_ns != mtime_before)
    )
    if ok and produced:
        excerpt = collect_excerpt(draft)
        message = f"已产出 {draft.name}（Obsidian reflections/ 可读全文）"
        if excerpt:
            message += f"\n\n{excerpt}"
        _notify("🌿 周回顾初稿已产出", message)
        print(f"[weekly-draft] ok: {draft}", flush=True)
        return
    reason = detail if not ok else "pi 报告成功但初稿文件缺失/未更新"
    _notify("⚠️ 周回顾初稿班次失败", f"{today} 未产出：{reason}")
    print(f"[weekly-draft] fail: {reason}", file=sys.stderr, flush=True)
    sys.exit(1)


if __name__ == "__main__":
    main()
