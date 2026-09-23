"""飞书决策向导（2026-09-21 第 13 条：车间 $decision 的异步替代形态——
不开会也能做结构化决策）。

流程（车间 decision.md 的飞书版）：

1. 飞书发「决策：<话题>」开店：PromptStore 开 kind=decision 会话，
   车间 Step 1 框定三问（选项/期限/难处与怕）挂在问答里，碎片时间
   逐条答，回「完成」收摊（复用 review 仪式的同一台状态机）；
2. 收摊即后台线程跑框架分析（DeepSeek 直连腿 deepseek-v4-pro——
   车间 Step 4 的单模型降级版：异步向导没有原生腿，要双模型交叉
   验证的重决策仍去会话里 $decision）：Cynefin 定性 + 按
   cross-validation 表选两个框架应用 + 四个扎心问题；
3. 分析推回飞书 + 存 ``<state_dir>/decision_pending.json``；
   回「存」按车间模板落盘 reflections/YYYY-MM-DD-decision-<slug>.md，
   回「算了」丢弃，失败可回「重试」。

纪律（与 dispatch 模块同源）：

- 状态只写 state 文件；落盘是唯一写笔记的动作，且需用户明示「存」；
- 后台线程是 daemon（不挡守护退出）；分析期间守护重启则 stage 停
  在 analyzing 超过 10 分钟视为失败，回「重试」即可；
- LLM 一切失败：推送可见错误、状态标 failed，绝不静默、绝不伪造分析。
"""

from __future__ import annotations

import json
import os
import re
import threading
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

import httpx
import yaml

from scripts.processors.base import CONFIG_FILES
from scripts.utils.date_utils import local_timezone
from scripts.utils.state_store import read_json, write_json

#: 会话类型标记（PromptStore kind）
KIND = "decision"
#: 待落盘状态文件（<state_dir>/decision_pending.json）
PENDING_FILENAME = "decision_pending.json"
#: analyzing 超过此时长视为失败（守护重启等情况），可「重试」
STALE_ANALYZING_SECONDS = 600
#: 落盘slug长度上限
SLUG_MAX = 30

#: 框定三问（车间 Step 1 的飞书版：话题已在开店消息里）
FRAMING_QUESTIONS = [
    "有哪些选项？（尽量凑够 3 个——二元选择往往藏着更好的第三选项）",
    "什么时候必须定？",
    "难在哪？你在怕什么？",
]

_LLM_DEFAULT_BASE_URL = "https://api.deepseek.com"
#: 默认 pro：决策是低频重场景，值得深思模型（每次几分钱；配置可覆盖）
_LLM_DEFAULT_MODEL = "deepseek-v4-pro"
_LLM_DEFAULT_TIMEOUT = 180.0

#: 车间 cross-validation.md 的对照表（浓缩进 prompt；直连腿没有文件系统）
_FRAMEWORK_TABLE = (
    "职业/方向 → Ikigai（热爱/擅长/市场/世界需要四环交集） + 遗憾最小化（80 岁回望）\n"
    "风险评估 → 事前验尸（假设已失败，倒推原因） + 逆向思考（想成功先想怎么搞砸）\n"
    "资源分配 → 帕累托（20% 产 80%） + 艾森豪威尔矩阵（重要/紧急四象限）\n"
    "卡住/僵局 → 免疫改变（隐性承诺与 competing commitment） + 五问法（连问五个为什么）\n"
    "建造/投资 → 第一性原理（拆到物理事实重建） + 沃德利地图（价值链与演化阶段）\n"
    "二元选择 → 辩证思考（正-反-合） + 二阶后果（然后会怎样）"
)


def _load_llm_config() -> Dict[str, Any]:
    """配置文件 ``dispatch.decision.llm`` 节（缺失/损坏返回空表走默认）。"""
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
                section = dispatch.get("decision")
                if isinstance(section, dict) and isinstance(section.get("llm"), dict):
                    return dict(section["llm"])
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
            # pro 是推理模型，reasoning 会吃掉约 1300+ token（同 todos 实测）
            "max_tokens": int(cfg.get("max_tokens", 4000)),
            "temperature": 0.2,
        },
        timeout=float(cfg.get("timeout", _LLM_DEFAULT_TIMEOUT)),
    )
    response.raise_for_status()
    return response.json()["choices"][0]["message"]["content"]


def _pending_path(tree) -> Path:
    return Path(tree.state_dir) / PENDING_FILENAME


def load_pending(tree) -> Optional[Dict[str, Any]]:
    """读待落盘状态；没有或损坏返回 None。"""
    data = read_json(_pending_path(tree), None)
    return data if isinstance(data, dict) else None


def _save_pending(tree, data: Dict[str, Any]) -> None:
    write_json(_pending_path(tree), data, indent=2)


def open_wizard(store, topic: str) -> str:
    """开店：PromptStore 开 kind=decision 会话 + 记录话题。返回引导文案。

    Args:
        store: PromptStore 实例。
        topic: 决策话题（「决策：」后面的原文）。
    """
    store.open(KIND, FRAMING_QUESTIONS)
    store.set_extra("topic", topic.strip())
    return (
        f"🧭 决策向导已开店：{topic.strip()}\n\n"
        + "\n".join(f"{i}. {q}" for i, q in enumerate(FRAMING_QUESTIONS, 1))
        + "\n\n直接回复作答（一条一条来，碎片时间也行）；答完回「完成」，"
        "我跑双框架分析；回「跳过」取消。"
    )


def _slugify(topic: str) -> str:
    """话题 → 文件名 slug（中文保留，空白/特殊字符转连字符）。"""
    slug = re.sub(r"[\\/:*?\"<>|\s]+", "-", topic.strip()).strip("-")
    return slug[:SLUG_MAX] or "untitled"


def _build_prompt(topic: str, answers: List[str]) -> str:
    return (
        f"今天日期 {datetime.now(local_timezone()).strftime('%Y-%m-%d')}。"
        "用户面临一个决策，请做结构化交叉分析。\n\n"
        f"话题：{topic}\n"
        f"选项：{answers[0] if len(answers) > 0 else '（未答）'}\n"
        f"期限：{answers[1] if len(answers) > 1 else '（未答）'}\n"
        f"难处与担心：{answers[2] if len(answers) > 2 else '（未答）'}\n\n"
        "步骤：\n"
        "1. 按 Cynefin 定性（Clear/Complicated/Complex/Chaotic 之一，"
        "给一句理由）；\n"
        "2. 从对照表选两个最适配的框架并各自真切应用（不许泛泛而谈，"
        "要落到这件事的具体事实上）：\n"
        f"{_FRAMEWORK_TABLE}\n"
        "3. 给出四个扎心问题供用户自己想（明天醒来已被决定感受如何 / "
        "会劝最好的朋友怎么做 / 十年后后悔没做什么 / 最怕的是什么、"
        "这恐惧有证据吗）；\n"
        "4. 一句话倾向结论。\n"
        "只输出 JSON：{\"domain\": \"...\", \"frameworks\": [\"..\", \"..\"], "
        "\"analysis\": \"两个框架各一段的 markdown，末尾点出分歧或共识\", "
        "\"hard_questions\": [\"..\", \"..\", \"..\", \"..\"], "
        "\"verdict\": \"proceed|defer|reject\", \"verdict_reason\": \"一句话\"}。"
    )


def _render_analysis(topic: str, result: Dict[str, Any]) -> str:
    """分析结果 → 飞书推送文案（截断保护）。"""
    questions = "\n".join(
        f"{i}. {q}" for i, q in enumerate(result.get("hard_questions") or [], 1)
    )
    verdict = {
        "proceed": "✅ 倾向行动",
        "defer": "⏸ 倾向暂缓",
        "reject": "🛑 倾向否决",
    }.get(str(result.get("verdict") or ""), "🤔 无明确倾向")
    text = (
        f"🧭 决策分析：{topic}\n\n"
        f"【定性】{result.get('domain') or '（未给出）'}\n"
        f"【框架】{' × '.join(str(f) for f in (result.get('frameworks') or []))}\n"
        f"【倾向】{verdict}——{result.get('verdict_reason') or ''}\n\n"
        f"{result.get('analysis') or '（无分析）'}\n\n"
        f"四个扎心问题（不用回我，自己想）：\n{questions}\n\n"
        "回「存」落盘进 reflections/（90 天后复盘）；回「算了」丢弃。"
    )
    return text[:2800]


def _analyze_and_push(tree, pending: Dict[str, Any], send: Callable[[str], None]) -> None:
    """后台线程：LLM 分析 → 存 pending → 推送。全部异常自吞并可见。"""
    try:
        cfg = _load_llm_config()
        result = json.loads(
            _chat(_build_prompt(pending["topic"], pending.get("answers") or []), cfg)
        )
        if not isinstance(result, dict):
            raise ValueError("llm returned non-dict")
        pending["result"] = {
            k: result.get(k)
            for k in ("domain", "frameworks", "analysis", "hard_questions", "verdict", "verdict_reason")
        }
        pending["stage"] = "done"
        _save_pending(tree, pending)
        send(_render_analysis(pending["topic"], pending["result"]))
    except Exception as exc:  # noqa: BLE001 - 线程内异常绝不外溢
        pending["stage"] = "failed"
        pending["error"] = f"{type(exc).__name__}: {exc}"[:200]
        try:
            _save_pending(tree, pending)
            send(f"⚠️ 决策分析失败：{pending['error']}\n回「重试」再跑一次，或回「算了」丢弃。")
        except Exception:  # noqa: BLE001 - 推送也失败只能留日志
            print(f"[decision] push fail: {pending['error']}", flush=True)


def finish_wizard(tree, closed: Dict[str, Any], send: Callable[[str], None]) -> None:
    """收摊（回「完成」/表单提交后）：登记 pending + 后台分析。

    Args:
        tree: MemoryTree。
        closed: PromptStore.close() 返回的会话终态（含 topic extra 与答案）。
        send: 飞书文本推送回调（桥注入）。
    """
    topic = str(closed.get("topic") or "（未命名决策）")
    answers = [str(a.get("text") or "") for a in (closed.get("answers") or [])]
    pending = {
        "stage": "analyzing",
        "topic": topic,
        "answers": answers,
        "opened_at": closed.get("asked_at"),
        "closed_at": closed.get("closed_at"),
    }
    _save_pending(tree, pending)
    send("收到，双框架分析中（深思模型，约 1–2 分钟）⏳")
    threading.Thread(
        target=_analyze_and_push, args=(tree, pending, send), daemon=True
    ).start()


def handle_pending_command(tree, text: str, send: Callable[[str], None]) -> bool:
    """「存」/「算了」/「重试」指令处理。命中返回 True（已消费）。

    仅在有待落盘决策时响应；stage=analyzing 超 10 分钟按失败处理
    （守护重启遗留），交「重试」。
    """
    pending = load_pending(tree)
    if not pending:
        return False
    stage = str(pending.get("stage") or "")
    if stage == "analyzing":
        closed_at = pending.get("closed_at") or ""
        try:
            age = datetime.now().timestamp() - datetime.fromisoformat(closed_at).timestamp()
        except ValueError:
            age = STALE_ANALYZING_SECONDS + 1
        if age <= STALE_ANALYZING_SECONDS:
            return False  # 正常分析中，指令不截胡
        stage = "failed"  # 超时按失败
        pending["stage"] = "failed"
        pending["error"] = "分析超时（守护可能重启过）"
        _save_pending(tree, pending)
    if text == "存":
        if stage != "done":
            send("还没有可存的分析（分析失败或已丢弃）——回「重试」或「算了」。")
            return True
        try:
            path = store_decision(tree, pending)
        except Exception as exc:  # noqa: BLE001 - 落盘失败可见，不中断守护
            send(f"⚠️ 落盘失败：{type(exc).__name__}: {exc}")
            return True
        pending["stage"] = "stored"
        _save_pending(tree, pending)
        send(f"✅ 已落盘 {path.name}（reflections/，{pending.get('review_date')} 复盘）")
        return True
    if text == "算了":
        pending["stage"] = "discarded"
        _save_pending(tree, pending)
        send("好的，本次决策分析已丢弃（答案仍留在当天日记里）。")
        return True
    if text == "重试":
        if stage != "failed":
            return False
        pending["stage"] = "analyzing"
        pending.pop("error", None)
        pending["closed_at"] = datetime.now().isoformat()
        _save_pending(tree, pending)
        send("重试中（约 1–2 分钟）⏳")
        threading.Thread(
            target=_analyze_and_push, args=(tree, pending, send), daemon=True
        ).start()
        return True
    return False


def store_decision(tree, pending: Dict[str, Any]) -> Path:
    """按车间 decision.md 模板落盘 reflections/YYYY-MM-DD-decision-<slug>.md。

    Returns:
        Path: 落盘文件路径。
    """
    result = pending.get("result") or {}
    today = datetime.now(local_timezone())
    day = today.strftime("%Y-%m-%d")
    topic = str(pending.get("topic") or "（未命名决策）")
    answers = list(pending.get("answers") or [])
    review_date = (today + timedelta(days=90)).strftime("%Y-%m-%d")
    pending["review_date"] = review_date
    refl_dir = Path(tree.notes_dir) / "wiki" / "reflections"
    refl_dir.mkdir(parents=True, exist_ok=True)
    path = refl_dir / f"{day}-decision-{_slugify(topic)}.md"
    questions = result.get("hard_questions") or []
    frameworks_line = " × ".join(str(f) for f in (result.get("frameworks") or [])) or "（未命名）"
    body = f"""---
created: '{today.isoformat()}'
source: decision
type: Decision
tags:
- 决策
title: 决策日志 {day}：{topic}
---

# Decision Journal — {day}

## Topic: {topic}

## Options Considered

{answers[0] if len(answers) > 0 else "（未答）"}

## Domain Classification

{result.get("domain") or "（未给出）"}（异步向导单模型版——DeepSeek 直连腿；双模型交叉验证请用会话 $decision）

## Framework Analysis

### {frameworks_line}（交叉验证）

{result.get("analysis") or "（无）"}

## Key Questions & Answers

""" + "\n".join(f"- {q}：（留给自己想）" for q in questions) + f"""

## Decision

倾向：{result.get("verdict") or "（无）"}——{result.get("verdict_reason") or ""}
（异步向导不替你拍板；最终决定写在这里，手写改动即可）

## Review Date

{review_date}（90 天后复盘当初选对没）

## Session Meta

- 渠道：飞书决策向导（第 13 条 sitting 替代形态）
- 框定答案：期限「{answers[1] if len(answers) > 1 else "（未答）"}」；难处「{answers[2] if len(answers) > 2 else "（未答）"}」
"""
    path.write_text(body, encoding="utf-8")
    return path
