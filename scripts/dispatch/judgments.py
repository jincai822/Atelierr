"""判断直收通道（2026-09-16 用户裁决：零摩擦登记进 cognition 判断登记处）。

两条通道，同一个 ``register_statement`` 入口：

- **Obsidian**：笔记里写「#判断 陈述」（标签后同一行即陈述），
  light 班次（``dispatch_cli judgments``）扫描 memory+inbox 直收；
- **飞书**：发「判断：xxx」（或「记为判断：」「#判断 」前缀），
  飞书桥直收并回文字轻通知。

纪律：

- 用户主动标记 = 人已完成批准（COGNITION-SPEC §3.1 保留的用户直接创建
  入口：origin.kind=manual、approval.source=human_assessment）——
  不再二次确认（同日裁决：减少人机交互摩擦）；
- 本模块只直收**用户显式标记**，绝不从正文自动提炼判断（机器提名走
  cognition proposals，攒晨报安静小节，不在本模块）；
- 重复防护：同 statement 的活动条目已存在则跳过并告知；Obsidian 通道
  用 ``<state_dir>/judgments_seen.json`` 记「笔记路径+行内容」哈希防
  重复收（笔记红线不改写，扫描行原样保留在笔记里）；
- 类型判定：陈述以「？/?」结尾 → question（省略 certainty）；否则
  belief（active，缺省 certainty=0.7——通知里注明可改）。
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from scripts.cognition.manager import ApprovalRecord, CognitionManager
from scripts.memory.core import MemoryTree

#: 飞书消息的判断前缀（「判断：」「记为判断：」「#判断 」）
FEISHU_PREFIXES: Tuple[str, ...] = ("判断：", "判断:", "记为判断：", "记为判断:")

#: Obsidian 行内标记：#判断（可带冒号）后同一行即陈述
_LINE_RE = re.compile(r"^\s*(?:[-*]\s*)?#判断[:：]?\s*(\S.*?)\s*$")

#: belief 直收的缺省确信度（spec 要求 belief/hypothesis 必填；
#: 用户没给时取「比较确信」，轻通知里注明可改）
DEFAULT_BELIEF_CERTAINTY = 0.7

_SEEN_FILENAME = "judgments_seen.json"


def parse_feishu_judgment(text: str) -> Optional[str]:
    """飞书消息剥离判断前缀，返回陈述；非判断消息返回 None。"""
    stripped = text.strip()
    for prefix in FEISHU_PREFIXES:
        if stripped.startswith(prefix):
            return stripped[len(prefix):].strip() or None
    if stripped.startswith("#判断"):
        return stripped[len("#判断"):].lstrip(" :：").strip() or None
    return None


def parse_line(line: str) -> Optional[str]:
    """Obsidian 行内标记解析：「#判断 陈述」（可选列表符/冒号）。"""
    m = _LINE_RE.match(line)
    return m.group(1) if m else None


def _classify(statement: str) -> Tuple[str, Optional[float]]:
    """类型判定：疑问句 → question；否则 belief（缺省确信度）。"""
    if statement.rstrip().endswith(("？", "?")):
        return "question", None
    return "belief", DEFAULT_BELIEF_CERTAINTY


def _duplicate_of(manager: CognitionManager, statement: str) -> Optional[str]:
    """活动条目里已有同 statement（去首尾空白）→ 返回其标题；否则 None。"""
    for entry in manager.list_entries():
        if str(entry.statement).strip() == statement.strip():
            return entry.title
    return None


def register_statement(
    tree: MemoryTree,
    statement: str,
    *,
    evidence_memory_id: Optional[Tuple[str, str]] = None,
    origin_note: str = "用户主动标记",
) -> Tuple[Optional[str], str]:
    """直收一条判断进 cognition 登记处（origin.kind=manual）。

    Args:
        tree: MemoryTree（借它的库根/state_dir 构造 CognitionManager）。
        statement: 判断陈述原文。
        evidence_memory_id: 来源笔记的 (memory id, 相对路径) 元组
            （Obsidian 通道）；None 表示无笔记来源（飞书通道）。
        origin_note: 写入 approval.reason 的来源说明。

    Returns:
        Tuple[Optional[str], str]: (新条目 id 或 None, 人类可读回执)。
        重复/非法时不创建，回执说明原因。
    """
    statement = statement.strip()
    if not statement:
        return None, "⚠️ 判断内容为空"
    # MemoryTree 的 ov_path 形参即 memory/ 目录本身；cognition 的 $OV
    # 根是 memory/ 的父目录（wiki/cognition/ 在库内）
    manager = CognitionManager(tree.notes_dir.parent, state_dir=tree.state_dir)
    dup = _duplicate_of(manager, statement)
    if dup:
        return None, f"判断登记处已有同内容条目「{dup}」，本次未重复收"
    entry_type, certainty = _classify(statement)
    title = statement if len(statement) <= 30 else statement[:30] + "…"
    evidence: List[Any] = []
    if evidence_memory_id:
        from scripts.cognition.manager import EvidenceRef

        mem_id, mem_rel = evidence_memory_id
        evidence = [
            EvidenceRef(kind="memory", relation="context", id=mem_id, path=mem_rel)
        ]
    entry = manager.create_entry(
        entry_type=entry_type,  # type: ignore[arg-type]
        title=title,
        statement=statement,
        status="active" if entry_type != "question" else "open",
        certainty=certainty,
        evidence=evidence,
        approval=ApprovalRecord(
            action="create", reason=origin_note, source="human_assessment"
        ),
    )
    kind_text = "疑问" if entry_type == "question" else f"判断（确信度 {certainty}，可改）"
    return str(entry.id), f"已收进判断登记处：{kind_text}「{title}」"


def _evidence_for(tree: MemoryTree, note_path: Path) -> Optional[Tuple[str, str]]:
    """取笔记的 (sidecar id, 相对路径) 作证据引用；未登记返回 None。"""
    try:
        note_id = tree._find_entry_id(note_path)
    except Exception:  # noqa: BLE001 - 证据缺失不阻塞直收
        return None
    if not note_id:
        return None
    return str(note_id), tree._rel_key(note_path)


def scan_vault(tree: MemoryTree) -> Dict[str, Any]:
    """扫描 memory+inbox 的「#判断」标记行并直收（幂等）。

    已收过的行按「笔记相对路径+行内容」哈希登记在
    ``<state_dir>/judgments_seen.json``，笔记不改写、行原样保留，
    下次扫描同一行跳过。

    Returns:
        Dict: {registered: [(statement, entry_id)], duplicates: [...],
               seen_before: int}——registered 供调用方发轻通知。
    """
    state_path = tree.state_dir / _SEEN_FILENAME
    seen: Dict[str, str] = {}
    if state_path.exists():
        try:
            data = json.loads(state_path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                seen = {str(k): str(v) for k, v in data.items()}
        except (OSError, ValueError, UnicodeDecodeError):
            seen = {}

    registered: List[Tuple[str, str]] = []
    duplicates: List[str] = []
    skipped_seen = 0
    roots = [tree.notes_dir, tree.inbox_dir]
    for root in roots:
        if not root.is_dir():
            continue
        for path in sorted(root.rglob("*.md")):
            try:
                text = path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue
            for line in text.splitlines():
                statement = parse_line(line)
                if not statement:
                    continue
                key = hashlib.sha1(
                    f"{tree._rel_key(path)}::{statement}".encode("utf-8")
                ).hexdigest()
                if key in seen:
                    skipped_seen += 1
                    continue
                entry_id, _msg = register_statement(
                    tree,
                    statement,
                    evidence_memory_id=_evidence_for(tree, path),
                    origin_note=f"用户 #判断 标记（{tree._rel_key(path)}）",
                )
                seen[key] = datetime.now().isoformat(timespec="seconds")
                if entry_id:
                    registered.append((statement, entry_id))
                else:
                    duplicates.append(statement)
    tmp = state_path.with_name(state_path.name + ".tmp")
    tmp.write_text(json.dumps(seen, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, state_path)
    return {
        "registered": registered,
        "duplicates": duplicates,
        "seen_before": skipped_seen,
    }


def registered_since(tree: MemoryTree, date: str) -> int:
    """指定日期（YYYY-MM-DD）以来直收的判断条数（晨报计数用）。"""
    state_path = tree.state_dir / _SEEN_FILENAME
    if not state_path.exists():
        return 0
    try:
        data = json.loads(state_path.read_text(encoding="utf-8"))
    except (OSError, ValueError, UnicodeDecodeError):
        return 0
    if not isinstance(data, dict):
        return 0
    day = datetime.strptime(date, "%Y-%m-%d")
    nxt = day + timedelta(days=1)
    count = 0
    for stamp in data.values():
        try:
            ts = datetime.fromisoformat(str(stamp))
        except ValueError:
            continue
        if day <= ts.replace(tzinfo=None) < nxt:
            count += 1
    return count
