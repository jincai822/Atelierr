"""文档防失修月检：机器核对"文档说的"与"盘上实际"是否一致。

思想来源 Cognitive OS「文档健康」月审（文档防失修规矩）：失修的文档
就是技术债务——机器每月核对一次，有异常才提醒人，无异常零打扰。

检查项（全部为可机械核验的事实）：
1. 数据区目录在位：memory/、wiki/ 及房间（cognition、reflections、
   _cognitive-os 归档）；
2. systemd 用户级定时器在位（decay/digest/links/dochealth）且 enabled；
3. 关键文档中反引号标注的仓库相对路径真实存在
   （DEVELOPMENT-PLAN-3MVP.md / docs/architecture/README.md /
   docs/AGENT-ONBOARDING.md）；
4. config/memory.yaml 可解析、notes_dir/state_dir 可定位。

输出：
- 每次运行写报告 ``<state_dir>/reports/doc-health-YYYY-MM-DD.md``；
- 有异常才建"待确认"笔记（``文档健康-YYYY-MM-DD.md``，当天去重）并
  发 ntfy 推送；无异常只留报告文件；
- 退出码恒 0（月检本身失败不该惊动定时器；异常经笔记/推送告知人）。

部署：docker/systemd/atelierr-dochealth.*（每月 2 日 04:17）。
人工运行：``python -m scripts.utils.doc_health [--dry-run]``。
"""

from __future__ import annotations

import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Tuple

from scripts.cli.memory_cli import resolve_config_path
from scripts.dispatch.notify import send_dispatch_notice
from scripts.memory.core import MemoryTree

#: 数据区必查目录（相对 $OV = notes_dir 的父目录）
DATA_DIRS = (
    "memory",
    "memory/wiki",
    "memory/wiki/cognition",
    "memory/wiki/reflections",
    "memory/wiki/_cognitive-os",
)

#: systemd 用户级必查定时器
TIMERS = (
    "atelierr-decay.timer",
    "atelierr-digest.timer",
    "atelierr-links.timer",
    "atelierr-dochealth.timer",
)

#: 路径引用抽查的文档（相对仓库根）
DOC_FILES = (
    "DEVELOPMENT-PLAN-3MVP.md",
    "docs/architecture/README.md",
    "docs/AGENT-ONBOARDING.md",
)

#: 文档中反引号标注的仓库相对路径（scripts/docs/config/docker/tools 开头）
_PATH_REF_RE = re.compile(r"`((?:scripts|docs|config|docker|tools)/[^`\s|]+)`")

#: 路径引用抽查上限（防巨型文档拖慢）
MAX_PATH_REFS = 80

#: 路径引用尾部允许的标点（文档里路径后常跟中文标点）
_TRAILING_PUNCT = "，。；：、）)》】…—-. "


def _expand_ref(ref: str) -> List[str]:
    """展开一层花括号记法（``scripts/{a,b,c}`` → 三条具体路径）。"""
    match = re.match(r"^(?P<pre>[^{}]*)\{(?P<items>[^{}]+)\}(?P<post>[^{}]*)$", ref)
    if not match:
        return [ref]
    return [
        f"{match.group('pre')}{item.strip()}{match.group('post')}"
        for item in match.group("items").split(",")
        if item.strip()
    ]


def run_checks(
    repo_root: Path,
    notes_dir: Path,
    home: Optional[Path] = None,
) -> Tuple[List[str], List[str]]:
    """执行全部检查，返回 (异常清单, 已检事实清单)。"""
    home = home or Path.home()
    problems: List[str] = []
    facts: List[str] = []
    ov = notes_dir.parent

    # 1. 数据区目录
    for rel in DATA_DIRS:
        if (ov / rel).is_dir():
            facts.append(f"数据区目录在位: {rel}/")
        else:
            problems.append(f"数据区目录缺失: {ov / rel}")

    # 2. systemd 定时器
    unit_dir = home / ".config" / "systemd" / "user"
    for timer in TIMERS:
        if not (unit_dir / timer).is_file():
            problems.append(f"systemd 单元缺失: {unit_dir / timer}")
            continue
        enabled = _is_enabled(timer)
        if enabled is True:
            facts.append(f"定时器在位且 enabled: {timer}")
        elif enabled is False:
            problems.append(f"定时器在位但未 enable: {timer}")
        else:
            facts.append(f"定时器在位（enabled 状态未能查验）: {timer}")

    # 3. 文档中的路径引用
    for doc in DOC_FILES:
        doc_path = repo_root / doc
        if not doc_path.is_file():
            problems.append(f"文档缺失: {doc}")
            continue
        refs = _extract_path_refs(doc_path)[:MAX_PATH_REFS]
        concrete = [item for ref in refs for item in _expand_ref(ref)]
        missing = [ref for ref in concrete if not (repo_root / ref).exists()]
        facts.append(f"{doc}: 抽查路径引用 {len(concrete)} 条，缺失 {len(missing)} 条")
        for ref in missing:
            problems.append(f"{doc} 引用了不存在的路径: {ref}")

    # 4. 配置文件可解析
    config_path = repo_root / "config" / "memory.yaml"
    if config_path.is_file():
        facts.append("config/memory.yaml 在位且已被本进程成功解析")
    else:
        problems.append("config/memory.yaml 缺失")

    return problems, facts


def _is_enabled(timer: str) -> Optional[bool]:
    """查验定时器 enabled 状态；systemctl 不可用/异常返回 None。"""
    try:
        proc = subprocess.run(
            ["systemctl", "--user", "is-enabled", timer],
            capture_output=True,
            timeout=15,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    out = proc.stdout.decode("utf-8", errors="replace").strip()
    if proc.returncode == 0 and out == "enabled":
        return True
    if out in ("disabled", "masked", "static", "indirect"):
        return False
    return None


def _extract_path_refs(doc_path: Path) -> List[str]:
    """从文档中提取去重后的仓库相对路径引用（剥掉尾部标点与省略号）。"""
    try:
        text = doc_path.read_text(encoding="utf-8")
    except OSError:
        return []
    refs: List[str] = []
    for match in _PATH_REF_RE.finditer(text):
        ref = match.group(1).rstrip(_TRAILING_PUNCT).rstrip("/")
        if ref and "…" not in ref and "*" not in ref and ref not in refs:
            refs.append(ref)
    return refs


def _build_report(
    problems: List[str], facts: List[str], now: datetime
) -> str:
    """组装报告正文（同时用于报告文件与异常笔记）。"""
    stamp = now.strftime("%Y-%m-%d %H:%M")
    lines = [
        f"# 文档健康月检 {now.strftime('%Y-%m-%d')}",
        "",
        f"> 运行时间：{stamp}；异常 {len(problems)} 条，已检事实 {len(facts)} 条。",
        "",
        "## 异常",
        "",
    ]
    lines += [f"- {item}" for item in problems] or ["- 无"]
    lines += ["", "## 已检事实", ""]
    lines += [f"- {item}" for item in facts]
    return "\n".join(lines) + "\n"


def main(argv: Optional[List[str]] = None) -> int:
    """CLI 入口：``python -m scripts.utils.doc_health [--dry-run]``。"""
    args = list(sys.argv[1:] if argv is None else argv)
    dry_run = "--dry-run" in args
    repo_root = Path(__file__).resolve().parents[2]

    resolved = resolve_config_path(None)
    if resolved:
        tree = MemoryTree.from_config(resolved)
    else:
        tree = MemoryTree(
            "~/atelierr-data/memory", state_dir="~/atelierr-data/state"
        )

    problems, facts = run_checks(repo_root, Path(tree.notes_dir))
    now = datetime.now()
    report = _build_report(problems, facts, now)
    print(report)

    if dry_run:
        print("（dry-run：未写报告、未建笔记）")
        return 0

    report_dir = Path(tree.state_dir) / "reports"
    report_dir.mkdir(parents=True, exist_ok=True)
    report_path = report_dir / f"doc-health-{now.strftime('%Y-%m-%d')}.md"
    report_path.write_text(report, encoding="utf-8")
    print(f"报告: {report_path}")

    if problems:
        filename = f"文档健康-{now.strftime('%Y-%m-%d')}.md"
        try:
            tree.create_note(
                filename,
                report,
                source="doc-health",
                tags=["待确认", "系统"],
            )
            print(f"已创建异常笔记: {filename}（待确认）")
        except (ValueError, FileExistsError):
            print(f"异常笔记当天已存在，跳过: {filename}")
        send_dispatch_notice(
            "Atelierr 文档健康月检",
            f"发现 {len(problems)} 条文档与盘面不一致，请查看异常笔记",
        )
    else:
        print("无异常：不建笔记、不推送（零打扰）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
