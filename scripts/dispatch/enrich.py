"""晚间日记 enrichment（2026-09-21 第 9 条②③：车间 $sync 的 Challenger
prompts 与 Curator 轻量批改的应用层版）。

每晚随复盘班次（``dispatch_cli review open daily``，21:30）做两件事：

1. **今日三问**（Challenger 同例）：读今天的日记 + memory/目标/ 的
   目标标题，LLM 生成 3 个一行问题，日记尾追加
   ``## 今日三问（YYYY-MM-DD）`` 块——车间 sync 的 prompts footer
   同例，按自然日幂等（已有该块不再追加）。
2. **错别字批改**（Curator light hand 同例）：今天日记里的
   ``- HH:MM`` 人写行（不含机器指路行/回链行/含 URL 行），LLM 只修
   明显错别字（漏字/错字/拼音错位），逐行 old→new 返回，精确匹配
   替换（对不上原文的修正整条放弃）；一天最多 ``MAX_FIXES`` 处。

纪律（日记红线例外的第三、四条批准路径，2026-09-21 用户拍板——
错别字批改一项是用户驳回"机器不动你的字"建议后的明确选择）：

- 机器触碰只限当天日记；两处写入都原子替换并还原 mtime（机器加工
  不算用户活跃，不进 confidence 时钟）；
- 无 API key / LLM 失败 → 跳过记日志，绝不伪造输出、绝不阻塞复盘
  主流程（未成功的工序不标完成，下一班次重试）；
- 批改可由当天 git 快照回滚（vault 每日快照，见 DECAY-SCHEDULING.md）；
- 状态写 ``<state_dir>/enrich.json``（按日期记 prompts/fixes），
  一天一轮，复盘班次多次触发不重复加工。
"""

from __future__ import annotations

import json
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import frontmatter
import httpx
import yaml

from scripts.dispatch.diary import resolve_diary_path
from scripts.processors.base import CONFIG_FILES
from scripts.utils.date_utils import local_timezone
from scripts.utils.state_store import read_json, write_json

_LLM_DEFAULT_BASE_URL = "https://api.deepseek.com"
_LLM_DEFAULT_MODEL = "deepseek-v4-flash"

#: 状态文件名（<state_dir>/enrich.json）
STATE_FILENAME = "enrich.json"
#: 一天最多批改几处（防 LLM 抽风大面积改写）
MAX_FIXES = 5
#: 三问条数（车间 Challenger 同数）
PROMPT_COUNT = 3
#: 目标目录（三问的立意来源之一）
GOALS_SUBDIR = "目标"

_HUMAN_LINE_RE = re.compile(r"^- \d{2}:\d{2} ")


def _load_llm_config() -> Dict[str, Any]:
    """配置文件 ``dispatch.enrich.llm`` 节（缺失/损坏返回空表走默认）。"""
    for config_file in CONFIG_FILES:
        path = Path(config_file)
        if not path.exists():
            continue
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8"))
        except yaml.YAMLError:
            continue
        if isinstance(data, dict):
            dispatch = data.get("dispatch")
            if isinstance(dispatch, dict):
                enrich = dispatch.get("enrich")
                if isinstance(enrich, dict) and isinstance(enrich.get("llm"), dict):
                    return dict(enrich["llm"])
    return {}


def _chat(prompt: str, cfg: Dict[str, Any]) -> str:
    """OpenAI 兼容 chat 调用（JSON 模式）；失败抛异常由调用方降级。"""
    api_key = os.environ.get(
        str(cfg.get("api_key_env", "DEEPSEEK_API_KEY")), ""
    ).strip()
    if not api_key:
        raise RuntimeError("no llm api key")
    response = httpx.post(
        f"{str(cfg.get('base_url', _LLM_DEFAULT_BASE_URL)).rstrip('/')}/chat/completions",
        headers={"Authorization": f"Bearer {api_key}"},
        json={
            "model": str(cfg.get("model", _LLM_DEFAULT_MODEL)),
            "messages": [{"role": "user", "content": prompt}],
            "response_format": {"type": "json_object"},
            # 与 todos 同源：推理模型的 reasoning_content 会吃 token，
            # 给足 4000 防 finish=length 空答案（2026-09-17 实测）
            "max_tokens": int(cfg.get("max_tokens", 4000)),
            "temperature": 0.1,
        },
        timeout=float(cfg.get("timeout", 60)),
    )
    response.raise_for_status()
    return response.json()["choices"][0]["message"]["content"]


def _goals_text(tree) -> str:
    """memory/目标/ 下全部目标标题（顿号连接；无目标目录返回空串）。"""
    goals_dir = Path(tree.notes_dir) / GOALS_SUBDIR
    if not goals_dir.is_dir():
        return ""
    titles: List[str] = []
    for path in sorted(goals_dir.glob("*.md")):
        try:
            post = frontmatter.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        titles.append(str(post.get("title") or path.stem))
    return "、".join(titles)


def _human_lines(text: str) -> List[str]:
    """人写行：``- HH:MM`` 开头、无回链、无 URL（机器指路行/附件行不沾）。"""
    lines = []
    for line in text.splitlines():
        if not _HUMAN_LINE_RE.match(line):
            continue
        if "[[" in line or "http" in line:
            continue
        lines.append(line)
    return lines


def _append_block(diary: Path, block: str) -> None:
    """日记尾追加一个块；原子写入并还原 mtime（机器加工不算用户活跃）。"""
    stat = diary.stat()
    content = diary.read_text(encoding="utf-8")
    sep = "" if content.endswith("\n") else "\n"
    tmp = diary.with_name(diary.name + ".tmp")
    tmp.write_text(f"{content}{sep}{block}", encoding="utf-8")
    tmp.replace(diary)
    os.utime(diary, ns=(stat.st_atime_ns, stat.st_mtime_ns))


def _generate_prompts(diary_body: str, goals: str, cfg: Dict[str, Any]) -> List[str]:
    """LLM 生成今日三问（扣住今天的日记内容；失败抛异常）。"""
    prompt = (
        "根据以下今天的日记内容和当前目标，生成 3 个引人想一想的问题。"
        "规则：每个问题一行、不超过 40 字；扣住日记里具体的人/事/物，"
        "可以有一个是发散性的；不要鸡汤套话；只输出 JSON："
        '{"questions": ["...", "...", "..."]}。\n\n'
        f"当前目标：{goals or '（未设置）'}\n\n今天的日记：\n{diary_body}"
    )
    data = json.loads(_chat(prompt, cfg))
    questions = data.get("questions", [])
    if not isinstance(questions, list):
        return []
    return [str(q).strip() for q in questions if str(q).strip()][:PROMPT_COUNT]


def _fix_typos(diary: Path, cfg: Dict[str, Any]) -> int:
    """LLM 错别字批改（light hand）；返回实际批改处数。失败抛异常。

    安全闸：只接精确匹配且全库唯一的原始行；时间前缀丢了的修正不收；
    一天最多 MAX_FIXES 处。
    """
    text = diary.read_text(encoding="utf-8")
    candidates = _human_lines(text)
    if not candidates:
        return 0
    prompt = (
        "下面是今天日记里的原始行（含时间前缀）。只修明显的错别字"
        "（漏字/错字/拼音错位/明显的同音错字），拿不准的一律不动；"
        "不改语义、不改标点风格、不增删内容、不动时间前缀。"
        '只输出 JSON：{"fixes": [{"old": "原始行", "new": "修正行"}]}；'
        "没有要修的输出空表。\n\n" + "\n".join(candidates)
    )
    data = json.loads(_chat(prompt, cfg))
    fixes = data.get("fixes", [])
    if not isinstance(fixes, list):
        return 0
    stat = diary.stat()
    applied = 0
    for fix in fixes:
        if applied >= MAX_FIXES:
            break
        if not isinstance(fix, dict):
            continue
        old = str(fix.get("old") or "")
        new = str(fix.get("new") or "")
        if not old or not new or old == new:
            continue
        if not old.startswith("- ") or not new.startswith("- "):
            continue  # 时间前缀被弄丢的修正不接受
        if text.count(old) != 1:
            continue  # 精确匹配且唯一才换；对不上/多处的整条放弃
        text = text.replace(old, new)
        applied += 1
    if applied:
        tmp = diary.with_name(diary.name + ".tmp")
        tmp.write_text(text, encoding="utf-8")
        tmp.replace(diary)
        os.utime(diary, ns=(stat.st_atime_ns, stat.st_mtime_ns))
    return applied


def run_evening(tree, today: Optional[str] = None) -> Dict[str, Any]:
    """晚间 enrichment 入口：今日三问 + 错别字批改（一天一轮，幂等）。

    Args:
        tree: MemoryTree 实例。
        today: 覆盖"今天"（YYYY-MM-DD，测试用）。

    Returns:
        Dict[str, Any]: {prompts: 本轮是否追加了三问块, fixes: 本轮批改
        处数, skipped: 跳过原因列表}。LLM 失败/无 key 不标完成，下一班次
        重试；当天日记不存在时直接跳过（不标完成，日记稍后被建仍可加工）。
    """
    today = today or datetime.now(local_timezone()).strftime("%Y-%m-%d")
    state_path = Path(tree.state_dir) / STATE_FILENAME
    state = read_json(state_path, {})
    if not isinstance(state, dict):
        state = {}
    done = state.get(today) or {}
    report: Dict[str, Any] = {"prompts": False, "fixes": 0, "skipped": []}
    diary = resolve_diary_path(Path(tree.notes_dir), today)
    if not diary.is_file():
        report["skipped"].append("无当天日记")
        return report
    cfg = _load_llm_config()
    if not os.environ.get(str(cfg.get("api_key_env", "DEEPSEEK_API_KEY")), "").strip():
        report["skipped"].append("无 API key")
        return report
    if not done.get("prompts"):
        try:
            questions = _generate_prompts(
                diary.read_text(encoding="utf-8"), _goals_text(tree), cfg
            )
        except Exception as exc:  # noqa: BLE001 - LLM 失败下一班次重试
            print(f"[enrich] prompts fail: {type(exc).__name__}: {exc}", flush=True)
        else:
            if questions and f"## 今日三问（{today}）" not in diary.read_text(
                encoding="utf-8"
            ):
                block = (
                    f"\n## 今日三问（{today}）\n\n"
                    "> 根据今天的日记与当前目标生成，有空想想，不用回答。\n\n"
                    + "\n".join(f"{i}. {q}" for i, q in enumerate(questions, 1))
                    + "\n"
                )
                _append_block(diary, block)
                report["prompts"] = True
            done["prompts"] = True
    if not done.get("typos"):
        try:
            fixes = _fix_typos(diary, cfg)
        except Exception as exc:  # noqa: BLE001 - LLM 失败下一班次重试
            print(f"[enrich] typos fail: {type(exc).__name__}: {exc}", flush=True)
        else:
            report["fixes"] = fixes
            done["typos"] = True
            done["fixes_total"] = fixes
    if done:
        state[today] = done
        write_json(state_path, state)
    return report
