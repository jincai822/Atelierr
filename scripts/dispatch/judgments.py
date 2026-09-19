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
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from scripts.cognition.manager import ApprovalRecord, CognitionManager
from scripts.memory.core import MemoryTree
from scripts.processors.base import CONFIG_FILES
from scripts.utils.state_store import read_json, write_json

import httpx
import yaml

#: 飞书判断消息统一匹配：「判断」或「记为判断」（可带 #）后必须跟
#: 冒号或空白再跟陈述——「判断力很重要」这类正文不会误命中
_FEISHU_JUDGMENT_RE = re.compile(r"^#?(?:判断|记为判断)[:：\s]+\s*(\S.*)$", re.S)

#: Obsidian 行内标记：#判断（可带冒号）后同一行即陈述
_LINE_RE = re.compile(r"^\s*(?:[-*]\s*)?#判断[:：]?\s*(\S.*?)\s*$")

#: belief 直收的缺省确信度（spec 要求 belief/hypothesis 必填；
#: 用户没给时取「比较确信」，轻通知里注明可改）
DEFAULT_BELIEF_CERTAINTY = 0.7

_SEEN_FILENAME = "judgments_seen.json"


def parse_feishu_judgment(text: str) -> Optional[str]:
    """飞书消息剥离判断前缀，返回陈述；非判断消息返回 None。

    认「判断：xxx」「判断 xxx」（空格写法）「记为判断：」「#判断 」；
    「判断」后必须跟冒号或空白——「判断力」「判断一下」不命中。
    """
    m = _FEISHU_JUDGMENT_RE.match(text.strip())
    return m.group(1).strip() if m else None


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


#: 最近一条判断的暂存（等「场景：」追问补登；有效期 60 分钟）
_LAST_FILE = "judgments_last.json"
#: 场景注记层（entry_id -> scenario；cognition schema 不动，注记平铺）
_SCENARIOS_FILE = "judgments_scenarios.json"
_SCENARIO_TTL_SECONDS = 3600


def attach_scenario(tree: MemoryTree, scenario: str) -> str:
    """给最近一条判断补「如果-那么」场景（实施意图，2026-09-18 C4）。

    Args:
        tree: MemoryTree。
        scenario: 场景原文（如「晚饭时」）。

    Returns:
        str: 人类可读回执；超过 60 分钟没有新判断时回提示语。
    """
    scenario = scenario.strip()
    last = read_json(Path(tree.state_dir) / _LAST_FILE, None)
    if not isinstance(last, dict) or not last.get("entry_id"):
        return "最近没有新登记的判断——先发「判断：xxx」登记一条"
    try:
        age = (
            datetime.now(timezone.utc) - datetime.fromisoformat(str(last["at"]))
        ).total_seconds()
    except ValueError:
        age = _SCENARIO_TTL_SECONDS + 1
    if age > _SCENARIO_TTL_SECONDS:
        return "这条追问过期了——重新发「判断：xxx」登记后再补场景"
    path = Path(tree.state_dir) / _SCENARIOS_FILE
    data = read_json(path, {})
    if not isinstance(data, dict):
        data = {}
    data[str(last["entry_id"])] = {
        "scenario": scenario,
        "title": last.get("title") or "",
        "at": datetime.now(timezone.utc).isoformat(),
    }
    write_json(path, data, indent=2)
    return f"记下了：「{scenario}」用它——到点想起来，就算赢一次"


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
    # 实施意图追问（2026-09-18 脑科学评审 C4）：登记只是意图，
    # 「如果-那么」的场景才是行为——记下最近一条，等用户回「场景：」
    write_json(
        Path(tree.state_dir) / _LAST_FILE,
        {"entry_id": str(entry.id), "title": title,
         "at": datetime.now(timezone.utc).isoformat()},
        indent=2,
    )
    kind_text = "疑问" if entry_type == "question" else f"判断（确信度 {certainty}，可改）"
    return (
        str(entry.id),
        f"已收进判断登记处：{kind_text}「{title}」\n"
        "想让它真落地？回「场景：xxx」告诉我什么场景用它（比如：晚饭时）",
    )


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


# ---------- 机器提名（只提名，绝不批准；攒晨报安静小节等你批）----------

#: 原子观点提取：优先「## 分观点论述」编号行，缺失退回「## 观点总结」整段
_VIEWPOINTS_RE = re.compile(r"^## 分观点论述\s*\n(?P<body>.*?)(?=^## |\Z)", re.M | re.S)
_NUMBERED_RE = re.compile(r"^\s*\d+[.、)]\s*(\S.+?)\s*$")
_SUMMARY_RE = re.compile(r"^## 观点总结\s*\n+(?P<body>[^#].*?)(?=^## |\Z)", re.M | re.S)

#: 单篇笔记最多提名条数（防一篇长文刷屏候选区）
MAX_NOMINATE_PER_NOTE = 2


def _split_viewpoints(text: str) -> List[str]:
    """从笔记正文提取原子观点（分观点论述编号行 → 观点总结整段兜底）。"""
    m = _VIEWPOINTS_RE.search(text)
    if m:
        items = [
            mm.group(1)
            for line in m.group("body").splitlines()
            if (mm := _NUMBERED_RE.match(line))
        ]
        if items:
            return items
    m = _SUMMARY_RE.search(text)
    if m:
        para = " ".join(m.group("body").split())
        if para:
            return [para]
    return []


#: LLM 提名默认接入点（配置节 dispatch.judgments.llm；缺省与 todos 同规格）
_LLM_DEFAULT_BASE_URL = "https://api.deepseek.com"
_LLM_DEFAULT_MODEL = "deepseek-v4-flash"
_LLM_KEY_ENV = "DEEPSEEK_API_KEY"

#: 提名提示词：判断 = 对世界运行方式/行动取舍的主张（因果、规律、方法论、
#: 价值观断言），人可以选择认同或反对；书名录、生平事实、内容复述、
#: 修辞感慨都不是判断（2026-09-17 实证：机械摘录把"叔本华著有《作为
#: 意志和表象的世界》"这类书名录提成了判断候选——质量问题的根）
_NOMINATE_PROMPT = (
    "以下是一篇笔记的观点节。请提炼最多 2 条值得收入「个人判断登记处」的"
    "原子断言。判断的标准：关于世界运行方式或行动取舍的主张（因果、规律、"
    "方法论、价值观断言），读者可以选择认同或反对。以下都不是判断，绝不"
    "提炼：书名录/作品信息、人物生平事实、情节或内容复述、修辞性感慨。"
    "要求：每条一句话，脱离原文也能读懂，不超过 40 字，尽量沿用原文用词。"
    "没有合格的就一条都不输出。只输出 JSON：{\"judgments\": [...]}。\n\n"
    "观点节原文：\n"
)

#: 落地校验最低连续覆盖率（规范化后）：防 LLM 编造来源里不存在的断言
_GROUNDING_MIN = 0.5


def _load_llm_config() -> Dict[str, Any]:
    """读取配置文件 ``dispatch.judgments.llm`` 节（缺失/损坏返回空表）。"""
    for config_file in CONFIG_FILES:
        path = Path(config_file)
        if not path.exists():
            continue
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8"))
        except yaml.YAMLError:
            continue
        if isinstance(data, dict):
            section = data.get("dispatch")
            if isinstance(section, dict):
                judgments = section.get("judgments")
                if isinstance(judgments, dict) and isinstance(
                    judgments.get("llm"), dict
                ):
                    return dict(judgments["llm"])
    return {}


def _sections_text(text: str) -> str:
    """取观点总结 + 分观点论述两节原文作 LLM 输入（都没有返回空串）。"""
    parts = []
    for pattern in (_SUMMARY_RE, _VIEWPOINTS_RE):
        m = pattern.search(text)
        if m:
            parts.append(m.group("body").strip())
    return "\n\n".join(parts)


def _grounded(statement: str, source_text: str) -> bool:
    """候选断言规范化后与来源文字的连续覆盖率 ≥ 阈值才算落地（防编造）。"""
    import difflib

    def _norm(value: str) -> str:
        return re.sub(r"[^\w]", "", value, flags=re.UNICODE)

    needle, corpus = _norm(statement), _norm(source_text)
    if not needle or not corpus:
        return False
    match = difflib.SequenceMatcher(None, needle, corpus).find_longest_match(
        0, len(needle), 0, len(corpus)
    )
    return match.size / len(needle) >= _GROUNDING_MIN


def _extract_judgments_llm(text: str) -> Optional[List[str]]:
    """LLM 提炼判断候选；不可用/失败返回 None（调用方退回机械摘录）。

    三分语义：None = LLM 没上班（退回机械摘录）；[] = LLM 判定观点节
    里没有合格判断（尊重它，一条都不提）；非空列表 = 通过落地校验的
    候选。护栏：key 缺失不调用；输出须为 JSON；每条候选须通过落地校验
    （规范化连续覆盖率 ≥ 0.5，防编造），全不落地视同失败退回。
    """
    api_key = os.environ.get(_LLM_KEY_ENV, "").strip()
    source = _sections_text(text)
    if not api_key or not source:
        return None
    cfg = _load_llm_config()
    base_url = str(cfg.get("base_url", _LLM_DEFAULT_BASE_URL)).rstrip("/")
    payload = {
        "model": str(cfg.get("model", _LLM_DEFAULT_MODEL)),
        "messages": [{"role": "user", "content": _NOMINATE_PROMPT + source}],
        "max_tokens": int(cfg.get("max_tokens", 2000)),
        "temperature": 0.1,
        # 机械提取任务禁用思考链（2026-09-02 实测：推理会吃光 max_tokens
        # 致 content 为空，与 todos 的 800-token 熔断同源）
        "thinking": {"type": "disabled"},
        "response_format": {"type": "json_object"},
    }
    try:
        response = httpx.post(
            f"{base_url}/chat/completions",
            headers={"Authorization": f"Bearer {api_key}"},
            json=payload,
            timeout=float(cfg.get("timeout", 60)),
        )
        response.raise_for_status()
        content = response.json()["choices"][0]["message"]["content"]
        content = re.sub(r"^```(?:json)?\s*|\s*```$", "", content.strip())
        data = json.loads(content)
    except Exception:  # noqa: BLE001 - 提名是增强工序，任何失败退回机械摘录
        return None
    items = [
        str(item).strip()
        for item in (data.get("judgments") or [])
        if str(item).strip()
    ]
    if not items:
        return []  # 模型判定无合格判断：尊重，不提名
    grounded = [item for item in items if _grounded(item, source)]
    return grounded or None


def _manager(tree: MemoryTree) -> CognitionManager:
    """按库的 $OV 根构造 CognitionManager。"""
    return CognitionManager(tree.notes_dir.parent, state_dir=tree.state_dir)


def nominate_from_note(
    tree: MemoryTree, note_path: Path, *, max_items: int = MAX_NOMINATE_PER_NOTE
) -> List[Tuple[str, str]]:
    """机器从已确认笔记的观点节提炼判断候选（**只提名，绝不批准**）。

    与直收同源的去重纪律：同 statement 的活动条目、待批提名已有则跳过
    （确认→归档两步都触发本函数也不会重复提名）。

    Args:
        tree: MemoryTree。
        note_path: 已确认笔记路径。
        max_items: 单篇最多提名条数（默认 2，防刷屏）。

    Returns:
        List[Tuple[str, str]]: [(proposal_id, statement)]；无可提名返回空。
    """
    try:
        text = note_path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return []
    statements = _extract_judgments_llm(text)
    if statements is None:
        # LLM 不可用/失败：退回机械摘录（无 LLM 环境也能运转）
        statements = _split_viewpoints(text)
    if not statements:
        return []
    try:
        memory_id = tree._find_entry_id(note_path)
    except Exception:  # noqa: BLE001 - 未登记无法提名
        return []
    if not memory_id:
        return []
    manager = _manager(tree)
    pending = {
        str(p.statement).strip() for p in manager.list_promotion_proposals()
    }
    nominated: List[Tuple[str, str]] = []
    for statement in statements[:max_items]:
        if statement.strip() in pending or _duplicate_of(manager, statement):
            continue
        title = statement if len(statement) <= 30 else statement[:30] + "…"
        try:
            proposal = manager.nominate_memory(
                str(memory_id),
                entry_type="belief",
                title=title,
                statement=statement,
                rationale="机器提炼自已确认笔记的观点节，待你批准（2026-09-16 回路三）",
                proposed_status="active",
                proposed_certainty=DEFAULT_BELIEF_CERTAINTY,
            )
        except Exception:  # noqa: BLE001 - 单条提名失败不阻塞其余
            continue
        pending.add(statement.strip())
        nominated.append((str(proposal.id), statement))
    return nominated


def pending_proposals(tree: MemoryTree) -> List[Dict[str, Any]]:
    """当前待批的机器提名（晨报安静小节用；按创建顺序）。"""
    return [
        {"id": str(p.id), "statement": p.statement, "title": p.title}
        for p in _manager(tree).list_promotion_proposals()
    ]


def decide_by_index(
    tree: MemoryTree, index: int, accept: bool
) -> Tuple[bool, str]:
    """按当前待批列表序号批准/拒绝（飞书「批 N」「略 N」指令）。

    批准即创建 cognition 条目（certainty 用提名建议值，approval 记
    human_approved_agent_assessment——机器提名、人批准）；拒绝只记
    理由。序号基于调用时刻的待批列表（与晨报展示同源同序）。
    """
    manager = _manager(tree)
    pending = manager.list_promotion_proposals()
    if not pending:
        return False, "判断登记处现在没有待批候选"
    if index < 1 or index > len(pending):
        return False, f"待批候选共 {len(pending)} 条，序号取 1..{len(pending)}"
    proposal = pending[index - 1]
    head = proposal.statement[:40]
    if accept:
        manager.approve_promotion(
            proposal.id,
            status=proposal.proposed_status,
            certainty=proposal.proposed_certainty,
            approval=ApprovalRecord(
                action="approve",
                reason="飞书「批 N」批准",
                source="human_approved_agent_assessment",
            ),
        )
        return True, f"已收进判断登记处：「{head}」"
    manager.reject_promotion(
        proposal.id,
        reason="飞书「略 N」略过",
        approval=ApprovalRecord(action="reject", reason="飞书「略 N」略过"),
    )
    return True, f"已略过这条候选：「{head}」"


# ----------------------------------------------------------------------
# 生命周期闭环（2026-09-19 backlog⑤：登记→复盘→销账）
# ----------------------------------------------------------------------

#: 复盘到期阈值：登记满 N 天提示复盘（天）
BELIEF_REVIEW_DAYS = 30
HYPOTHESIS_REVIEW_DAYS = 14
DECISION_REVIEW_DAYS = 30
#: 提示冷却：同一条目推过卡/点过按钮后 N 天内不再提示（防打扰）
REVIEW_COOLDOWN_DAYS = 30
#: 每天最多推几张复盘卡（与推送纪律同源）
MAX_REVIEW_CARDS = 3

#: 复盘冷却时钟（只写 state，绝不碰笔记/cognition 文件）
_REVIEW_FILE = "judgments_review.json"

#: 复盘三结果（卡片按钮 value 的 outcome）
OUTCOME_STILL_TRUE = "still_true"
OUTCOME_NOT_TRUE = "not_true"
OUTCOME_ADJUST = "adjust"

#: 各类型参与复盘的"在研"状态（question 走 answer 闭环，不在此列）
_REVIEWABLE_STATUS = {"belief": "active", "hypothesis": "testing", "decision": "active"}

#: 各类型到期阈值（天）
_REVIEW_DAYS = {
    "belief": BELIEF_REVIEW_DAYS,
    "hypothesis": HYPOTHESIS_REVIEW_DAYS,
    "decision": DECISION_REVIEW_DAYS,
}


def _parse_iso(value: str) -> Optional[datetime]:
    """解析 ISO 时间（宽容：Z 后缀/缺时区按 UTC）；失败返回 None。"""
    try:
        text = str(value).strip().replace("Z", "+00:00")
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def due_for_review(
    tree: MemoryTree, *, now: Optional[datetime] = None
) -> List[Dict[str, Any]]:
    """到期该复盘的判断（登记→复盘→销账 生命周期的复盘端）。

    对象：active belief 登记满 30 天、testing hypothesis 满 14 天、
    active decision 满 30 天；**decision 带 review_at 时以它为闹钟**
    （到期即提示，不看账龄——2026-09-19 阶段二修复后 review_at 已进
    CognitionEntry 只读视图，电池装上了）；同一条目冷却 30 天内不重复
    提示（冷却时钟只写 ``<state_dir>/judgments_review.json``）。question
    类型走 answer_question 闭环不在此列。

    Args:
        tree: MemoryTree。
        now: 当前时间（测试注入用；缺省 UTC 现在）。

    Returns:
        List[Dict]: [{entry_id, title, statement, entry_type, days}]，
        账龄最长在前，最多 MAX_REVIEW_CARDS 条。
    """
    moment = now or datetime.now(timezone.utc)
    state = read_json(Path(tree.state_dir) / _REVIEW_FILE)
    cooldown: Dict[str, str] = state.get("prompted", {}) if isinstance(state, dict) else {}
    due: List[Dict[str, Any]] = []
    for entry in _manager(tree).list_entries():
        expected = _REVIEWABLE_STATUS.get(entry.entry_type)
        if expected is None or entry.status != expected:
            continue
        created = _parse_iso(entry.created)
        if created is None:
            continue
        age_days = (moment - created).days
        # decision 的 review_at 是显式闹钟：设了就以它为准（到期即提示，
        # 没到就安静），没设才退回账龄阈值
        review_at = _parse_iso(str(getattr(entry, "review_at", "") or ""))
        if entry.entry_type == "decision" and review_at is not None:
            if moment < review_at:
                continue
        elif age_days < _REVIEW_DAYS[entry.entry_type]:
            continue
        last = _parse_iso(str(cooldown.get(entry.id) or ""))
        if last is not None and (moment - last).days < REVIEW_COOLDOWN_DAYS:
            continue
        due.append(
            {
                "entry_id": str(entry.id),
                "title": entry.title,
                "statement": entry.statement,
                "entry_type": entry.entry_type,
                "days": age_days,
            }
        )
    due.sort(key=lambda item: -item["days"])
    return due[:MAX_REVIEW_CARDS]


def mark_review_prompted(tree: MemoryTree, entry_ids: List[str]) -> None:
    """记复盘冷却（推卡成功/按钮闭环后调用；只写 state，幂等）。"""
    if not entry_ids:
        return
    path = Path(tree.state_dir) / _REVIEW_FILE
    state = read_json(path)
    if not isinstance(state, dict):
        state = {}
    prompted = state.setdefault("prompted", {})
    stamp = datetime.now(timezone.utc).isoformat()
    for entry_id in entry_ids:
        prompted[str(entry_id)] = stamp
    write_json(path, state, indent=2)


def apply_review_outcome(
    tree: MemoryTree, entry_id: str, outcome: str
) -> Tuple[bool, str]:
    """复盘结果落账（销账端）：状态迁移 + 历史留痕。

    按钮点击即人工批准（ApprovalRecord source=human_assessment，与直收
    同源）；certainty 不动。迁移表：

    - 仍成立：belief/decision 保持 active（留复盘痕）；hypothesis → supported
    - 不成立：belief/hypothesis → refuted；decision → archived（放弃）
    - 要调整：belief → questioned；hypothesis/decision 原状态留痕，
      回执引导发新判断（supersede 继任留电脑端人工，不在飞书上猜）

    Returns:
        Tuple[bool, str]: (是否落账成功, 人类可读回执)。
    """
    manager = _manager(tree)
    try:
        entry = manager.get_entry(entry_id)
    except Exception:  # noqa: BLE001 - 条目不存在/损坏只回执
        return False, f"判断登记处找不到这条（{entry_id}）——可能已在电脑端处理过"
    stamp = datetime.now().strftime("%Y-%m-%d")
    if outcome == OUTCOME_STILL_TRUE:
        new_status = "supported" if entry.entry_type == "hypothesis" else "active"
        rationale = f"{stamp} 复盘：仍成立"
        receipt = "已记下：这条还成立 ✅"
    elif outcome == OUTCOME_NOT_TRUE:
        new_status = "archived" if entry.entry_type == "decision" else "refuted"
        rationale = f"{stamp} 复盘：不成立"
        receipt = "已销账：这条标记为不成立（登记处保留痕迹，不再进默认列表）"
    elif outcome == OUTCOME_ADJUST:
        new_status = "questioned" if entry.entry_type == "belief" else entry.status
        rationale = f"{stamp} 复盘：要调整"
        receipt = "已标「存疑」。直接发「判断：新表述」我会另收一条；新旧继任关系到电脑端登记处连"
    else:
        return False, f"未知的复盘结果：{outcome}"
    try:
        manager.reassess_entry(
            entry_id,
            evidence=[],
            certainty=None,
            status=new_status,
            rationale=rationale,
            approval=ApprovalRecord(
                action="reassess",
                reason=f"飞书复盘卡「{outcome}」",
                source="human_assessment",
            ),
        )
    except Exception as exc:  # noqa: BLE001 - 迁移失败只回执
        return False, f"落账失败：{exc}"
    mark_review_prompted(tree, [entry_id])
    head = entry.statement[:30]
    return True, f"{receipt}\n（「{head}」）"
