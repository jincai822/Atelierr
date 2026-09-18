"""机器辅助提炼（深加工链路）：提炼候选 → LLM 起草 wiki 摘录卡 → 人批落库。

定位（2026-09-18 用户裁决，采纳 Google OKF v0.2 格式骨架）：
- 机器起草（每天 ≤1 张，防刷屏）→ 飞书送审 → 人「提」落压缩层
  ``memory/distilled/``（2026-09-18 三层结构裁决：原料/压缩/知识分层，
  机器压缩品不进知识层 wiki/）转
  stable、「弃」永久跳过；机器绝不自动落卡——压缩层进门也必须
  过人（"人类策展，LLM 维护"的 OKF 分工）；
- 卡片 schema 采纳 OKF v0.2 轻量层：type/title/description/tags/
  status(draft→stable)/stale_after(默认 +180 天，到期进晨报复查)/
  generated/verified/sources，另保留兼容字段 from/created/source
  （现有 WikiManager 校验与 distilled_stems 机制不动）；
  distilled/index.md（导航）、distilled/log.md（变更日志）、
  distilled/topics/<主题>.md（主题页）是 OKF 约定的机器自留地，
  统一由 scripts/wiki/curation.py 维护；
- 候选来源与晨报同源（digest.compute_distill_candidates：反复推送/
  被引用/沉一沉三路汇合，全库只此一份口径）；
- 草稿与弃稿名单记 ``<state_dir>/distill_drafts.json``。

纪律（与 dispatch 各模块一致）：
- 只新增卡片与 state，绝不改写/移动/删除既有笔记（distilled/index.md、
  log.md、topics/ 除外——OKF 约定的机器自留地）；
- 幂等：同一 stem 同时只有一张待批草稿；已提炼（wiki 有 from 回链）
  自然退出候选；LLM 失败当日跳过（不补不炸，次日再来）；
- 金句逐字校验（processors/link._verify_insights 同源）：编造的剔除，
  全剔光降级为无金句卡片，不阻塞起草。

触发：systemd 定时器（atelierr-light，接在 judgments 之后）或人工
``dispatch_cli distill``。
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import frontmatter
import httpx
import yaml

from scripts.dispatch.digest import compute_distill_candidates
from scripts.dispatch.notify import send_dispatch_notice
from scripts.dispatch.response_probe import ResponseProbe
from scripts.memory.core import LAYERS, MemoryTree
from scripts.processors.base import CONFIG_FILES
from scripts.processors.link import _verify_insights
from scripts.utils.state_store import read_json, write_json
from scripts.wiki import curation
from scripts.wiki.manager import WikiManager

#: LLM 默认接入点（配置节 dispatch.distill.llm；缺省与 todos 同规格）
_LLM_DEFAULT_BASE_URL = "https://api.deepseek.com"
_LLM_DEFAULT_MODEL = "deepseek-v4-flash"
_LLM_KEY_ENV = "DEEPSEEK_API_KEY"

#: 摘录卡文件名非法字符（与飞书归档校验同源）
_ILLEGAL_NAME_RE = re.compile(r'[\\/:*?"<>|]')

#: 喂给 LLM 的笔记正文上限（书籍类长文截断，摘要通常已含骨架）
_MAX_NOTE_CHARS = 8000

#: OKF Freshness：卡片默认保鲜期（天），到期进晨报「到期复查」节
_STALE_AFTER_DAYS = 180

#: 起草提示词：产出 OKF 轻量层字段（title/description/points/quotes）。
#: 金句必须逐字（机器会回溯校验）；核心主张是提炼不是照抄（人来审）。
_DRAFT_PROMPT = (
    "以下是一篇个人知识库笔记。请为它起草一张 wiki 摘录卡，输出 JSON："
    "{\"title\": \"...\", \"description\": \"...\", \"points\": [...], "
    "\"quotes\": [...]}。要求：\n"
    "- title：不超过 12 字的知识性标题（讲什么概念/主题），不带平台名、"
    "不带书名号；\n"
    "- description：一句话（不超过 40 字）说清这张卡讲什么、为什么值得读，"
    "给 AI 和人做快速判断用；\n"
    "- points：3-5 条核心主张，每条独立成句、不超过 50 字，是提炼不是照抄，"
    "覆盖笔记的主要论点；\n"
    "- quotes：2-3 条原文金句，**必须逐字照抄笔记原文含标点**（机器会逐条"
    "回查，找不到的会被剔除）；\n"
    "不要输出 JSON 以外的任何内容。\n\n笔记正文：\n"
)


def _load_config() -> Dict[str, Any]:
    """读取配置文件 ``dispatch.distill`` 节（缺失/损坏返回空表）。"""
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
            if isinstance(section, dict) and isinstance(section.get("distill"), dict):
                return dict(section["distill"])
    return {}


def _state_path(tree: MemoryTree) -> Path:
    return Path(tree.state_dir) / "distill_drafts.json"


def _load_state(tree: MemoryTree) -> Dict[str, Any]:
    data = read_json(_state_path(tree), {})
    if not isinstance(data, dict):
        return {}
    data.setdefault("drafts", {})
    data.setdefault("rejected_stems", [])
    return data


def _save_state(tree: MemoryTree, state: Dict[str, Any]) -> None:
    write_json(_state_path(tree), state, indent=2)


def pending_drafts(tree: MemoryTree) -> List[Dict[str, Any]]:
    """当前待批草稿（按起草时间序，与飞书「提 N/弃 N」序号同源）。"""
    state = _load_state(tree)
    drafts = list(state.get("drafts", {}).values())
    return sorted(drafts, key=lambda d: str(d.get("created") or ""))


def _find_note_by_stem(tree: MemoryTree, stem: str) -> Optional[Path]:
    """按 stem 全库定位笔记（含已归档子目录；取首个命中）。"""
    for layer in LAYERS:
        for path in tree.list_notes(layer):
            if path.stem == stem:
                return path
    return None


def _llm_draft(note_text: str, cfg: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """调 LLM 起草卡片字段；不可用/失败/坏 JSON 返回 None（当日跳过）。

    机械起草任务禁用思考链（与 link/todos 的 800-token 熔断同源教训）；
    json_mode 输出经 link._llm_chat 同款围栏/散文容错？——不，本函数
    自带容错（剥围栏 + 抽大括号块），与 judgments 提名同一份纪律。
    """
    api_key = os.environ.get(_LLM_KEY_ENV, "").strip()
    if not api_key or not note_text.strip():
        return None
    llm_cfg = cfg.get("llm") or {}
    base_url = str(llm_cfg.get("base_url", _LLM_DEFAULT_BASE_URL)).rstrip("/")
    payload = {
        "model": str(llm_cfg.get("model", _LLM_DEFAULT_MODEL)),
        "messages": [{"role": "user", "content": _DRAFT_PROMPT + note_text}],
        "max_tokens": int(llm_cfg.get("max_tokens", 3000)),
        "temperature": 0.3,
        "thinking": {"type": "disabled"},
        "response_format": {"type": "json_object"},
    }
    try:
        response = httpx.post(
            f"{base_url}/chat/completions",
            headers={"Authorization": f"Bearer {api_key}"},
            json=payload,
            timeout=float(llm_cfg.get("timeout", 60)),
        )
        response.raise_for_status()
        content = response.json()["choices"][0]["message"]["content"]
        content = re.sub(r"^```(?:json)?\s*|\s*```$", "", (content or "").strip())
        data = json.loads(content)
    except Exception:  # noqa: BLE001 - 起草是增强工序，任何失败当日跳过
        return None
    title = str(data.get("title") or "").strip()
    description = str(data.get("description") or "").strip()
    points = [str(p).strip() for p in (data.get("points") or []) if str(p).strip()][:5]
    quotes = [str(q).strip() for q in (data.get("quotes") or []) if str(q).strip()][:3]
    if not title or not points:
        return None
    return {
        "title": title,
        "description": description,
        "points": points,
        "quotes": quotes,
    }


def run(
    tree: MemoryTree, *, dry_run: bool = False, today: Optional[str] = None
) -> Dict[str, Any]:
    """每日起草主流程：配额闸 → 取候选 → LLM 起草 → 落 state → 推送。

    Args:
        tree: MemoryTree。
        dry_run: 只报告不起草/不推送/不写 state。
        today: YYYY-MM-DD（测试注入；缺省取本机当日）。

    Returns:
        Dict[str, Any]: 运行报告（candidates/drafted/skipped/pushed）。
    """
    today = today or datetime.now().strftime("%Y-%m-%d")
    state = _load_state(tree)
    report: Dict[str, Any] = {
        "candidates": 0,
        "drafted": None,
        "skipped": [],
        "pushed": False,
    }
    if state.get("last_draft_date") == today:
        report["skipped"].append("quota:今日已起草")
        return report
    cfg = _load_config()
    wiki = WikiManager(tree)
    candidates = compute_distill_candidates(tree, ResponseProbe(tree), wiki, today)
    report["candidates"] = len(candidates)
    rejected = set(state.get("rejected_stems") or [])
    pending_stems = {
        str(d.get("source_stem")) for d in (state.get("drafts") or {}).values()
    }
    stem = next(
        (s for s in candidates if s not in rejected and s not in pending_stems), None
    )
    if stem is None:
        report["skipped"].append("no-candidate")
        return report
    note_path = _find_note_by_stem(tree, stem)
    if note_path is None:
        report["skipped"].append("note-missing")
        return report
    if dry_run:
        report["drafted"] = stem
        return report
    try:
        note_text = note_path.read_text(encoding="utf-8")[:_MAX_NOTE_CHARS]
    except (OSError, UnicodeDecodeError):
        report["skipped"].append("note-unreadable")
        return report
    draft = _llm_draft(note_text, cfg)
    if draft is None:
        report["skipped"].append("llm-failed")
        return report
    # 金句逐字回溯机检：编造的剔除，全剔光降级为无金句卡（不阻塞）
    quotes, _dropped = _verify_insights(draft["quotes"], note_text)
    draft["quotes"] = quotes
    draft_id = hashlib.sha1(
        f"{stem}{datetime.now(timezone.utc).isoformat()}".encode("utf-8")
    ).hexdigest()[:8]
    post = frontmatter.loads(note_text)
    draft.update(
        {
            "id": draft_id,
            "source_stem": stem,
            "source_path": str(note_path.relative_to(tree.notes_dir)),
            "source_title": str(post.get("title") or stem),
            "source_id": str(post.get("id") or ""),
            "source_tags": [str(t) for t in (post.get("tags") or [])],
            "created": datetime.now(timezone.utc).isoformat(),
        }
    )
    state["drafts"][draft_id] = draft
    state["last_draft_date"] = today
    _save_state(tree, state)
    report["drafted"] = stem
    seq = len(pending_drafts(tree))
    message = (
        f"✍️ 提炼草稿（第 {seq} 号）\n\n标题：{draft['title']}\n"
        f"摘要：{draft['description']}\n\n核心主张：\n"
        + "\n".join(f"{i}. {p}" for i, p in enumerate(draft["points"], 1))
        + ("\n\n原文金句：\n" + "\n".join(f"「{q}」" for q in quotes) if quotes else "")
        + f"\n\n来源：[[{stem}]]\n回复「提 {seq}」收进压缩层、「弃 {seq}」跳过"
    )
    result = send_dispatch_notice("✍️ 提炼草稿待审", message)
    report["pushed"] = result.get("feishu", False)
    return report


# ---------- 审批（「提 N」落压缩层 /「弃 N」跳过）----------


def _safe_filename(title: str, wiki_dir: Path) -> str:
    """标题转安全文件名（剥非法字符；撞名加数字后缀，绝不覆盖）。"""
    base = _ILLEGAL_NAME_RE.sub("", title).strip() or "未命名"
    candidate = f"{base}.md"
    seq = 2
    while (wiki_dir / candidate).exists():
        candidate = f"{base}-{seq}.md"
        seq += 1
    return candidate


def _compose_card(draft: Dict[str, Any], actor: str) -> Tuple[Dict[str, Any], str]:
    """按 OKF v0.2 轻量层 schema 拆出卡片（metadata dict, 正文）。

    2026-09-19 方案三 P4：卡片经 bm_bridge 写入（文件+实体+关系一体），
    frontmatter 以 metadata 传递（bm 合并落盘并注入 permalink 字段）。
    """
    now = datetime.now(timezone.utc).isoformat()
    metadata: Dict[str, Any] = {
        "type": "Excerpt",
        "title": draft["title"],
        "description": draft["description"],
        "tags": draft.get("source_tags") or [],
        "status": "stable",  # 人批即正式版（draft 态只存在于送审期间）
        # OKF Freshness（2026-09-18 全量采纳）：半年后到期复查，
        # 晨报「到期复查」节点名，人复查后自行顺延
        "stale_after": (datetime.now() + timedelta(days=_STALE_AFTER_DAYS)).strftime(
            "%Y-%m-%d"
        ),
        "generated": {"by": "atelierr-distill/1.0", "at": draft["created"]},
        "verified": [{"by": actor, "at": now}],
        "sources": [
            {
                "id": draft.get("source_id") or draft["source_stem"],
                "resource": draft["source_path"],
                "title": draft.get("source_title") or draft["source_stem"],
            }
        ],
        "from": f"[[{draft['source_stem']}]]",
        "created": now,
        "source": "distill",
    }
    lines = [f"# {draft['title']}", ""]
    if draft["description"]:
        lines += [f"> {draft['description']}", ""]
    lines += ["## 核心主张", ""]
    lines += [f"{i}. {p}" for i, p in enumerate(draft["points"], 1)]
    if draft.get("quotes"):
        lines += ["", "## 原文金句", ""]
        lines += [f"「{q}」" for q in draft["quotes"]]
    lines += ["", "## 来源", "", f"- [[{draft['source_stem']}]]", ""]
    return metadata, "\n".join(lines)


def _update_index(wiki_dir: Path, filename: str, title: str, description: str) -> None:
    """（兼容包装）实现已提升为 :func:`scripts.wiki.curation.update_index`。"""
    curation.update_index(wiki_dir, filename, title, description)


def _append_log(wiki_dir: Path, filename: str, title: str) -> None:
    """（兼容包装）实现已提升为 :func:`scripts.wiki.curation.append_log`。"""
    curation.append_log(wiki_dir, filename, title)


def decide_by_index(
    tree: MemoryTree, index: int, accept: bool, actor: str = "human:cj1024"
) -> Tuple[bool, str]:
    """按当前待批列表序号审批提炼草稿（飞书「提 N」「弃 N」指令）。

    「提」：在压缩层 distilled/ 根层落 OKF 摘录卡（status: stable +
    verified 记操作人），维护 index.md/log.md/主题页，草稿出队——
    压缩层有保鲜期（stale_after），进门必须过人（本函数是唯一入口）。
    「弃」：草稿出队并把来源 stem 记入弃稿名单（不再提名）；来源
    笔记本身不动。

    序号基于调用时刻的待批列表（与飞书送审卡、晨报计数同源同序）。
    """
    state = _load_state(tree)
    drafts = pending_drafts(tree)
    if not drafts:
        return False, "现在没有待审的提炼草稿"
    if index < 1 or index > len(drafts):
        return False, f"待审草稿共 {len(drafts)} 张，序号取 1..{len(drafts)}"
    draft = drafts[index - 1]
    title = draft["title"]
    if not accept:
        state["drafts"].pop(draft["id"], None)
        rejected = state.setdefault("rejected_stems", [])
        if draft["source_stem"] not in rejected:
            rejected.append(draft["source_stem"])
        _save_state(tree, state)
        return True, f"已跳过这张草稿：「{title}」（来源不再提名）"
    distilled_dir = Path(tree.notes_dir) / curation.DISTILLED_DIRNAME
    distilled_dir.mkdir(parents=True, exist_ok=True)
    filename = _safe_filename(title, distilled_dir)
    card_metadata, card_body = _compose_card(draft, actor)
    try:
        # 方案三 P4：卡片经 basic-memory 写入（文件+实体+关系一体，
        # 图谱从新卡开始生长）；桥失败退回直写文件（落卡不阻塞）
        from scripts.memory.bm_bridge import write_note as bm_write

        bm_write(
            f"distilled/{filename}",
            title,
            card_body,
            note_type="Excerpt",
            tags=[str(t) for t in (draft.get("source_tags") or [])],
            metadata=card_metadata,
        )
    except Exception as exc:  # noqa: BLE001 - 桥失败退回直写（绝不影响审批）
        print(f"[distill] bm write fail, fallback to file: {exc}", flush=True)
        (distilled_dir / filename).write_text(
            frontmatter.dumps(frontmatter.Post(card_body, **card_metadata)),
            encoding="utf-8",
        )
    _update_index(distilled_dir, filename, title, str(draft.get("description") or ""))
    _append_log(distilled_dir, filename, title)
    try:
        # OKF 主题页（2026-09-18 全量采纳）：收录进 topics/<主题>.md 并
        # 刷新导读——增强工序，失败不阻塞审批回执
        curation.update_topic_page(
            distilled_dir,
            card_stem=Path(filename).stem,
            card_title=title,
            description=str(draft.get("description") or ""),
            tags=[str(t) for t in (draft.get("source_tags") or [])],
        )
    except Exception as exc:  # noqa: BLE001 - 主题页是增强工序
        print(f"[distill] topic page fail: {exc}", flush=True)
    state["drafts"].pop(draft["id"], None)
    _save_state(tree, state)
    return True, f"已收进压缩层：「{title}」（distilled/{filename}）"
