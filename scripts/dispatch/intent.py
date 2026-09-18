"""飞书自然语言意图分类（2026-09-18 用户裁决 B：Atelier 意图层上岗 v1）。

未命中精确命令的文本先过本分类器（LLM 一次调用，JSON 输出）：

- ``search`` / ``digest`` / ``todos`` / ``reflect`` → 直接执行对应菜单动作；
- ``workshop``（决策/深谈/综合类）→ 回车间指引，不执行；
- ``capture`` / 低置信 / 任何失败 → 返回 None，调用方照旧记日记（零回归）。

纪律（与 dispatch 各模块同源）：
- 判断登记绝不走意图分类——只认「判断：」显式前缀（防随口一句被误记）；
- LLM 是增强工序：无 key / 超时 / 坏 JSON 一律 None（退回 capture）；
- 禁用思考链（机械分类，与 link/todos 的 800-token 熔断同源教训）。
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any, Dict, Optional

import httpx
import yaml

#: LLM 默认接入点（配置节 dispatch.intent.llm；缺省与 distill 同规格）
_LLM_DEFAULT_BASE_URL = "https://api.deepseek.com"
_LLM_DEFAULT_MODEL = "deepseek-v4-flash"
_LLM_KEY_ENV = "DEEPSEEK_API_KEY"

#: 可执行意图（workshop 只指引不执行；capture 表示无意图）
INTENTS = frozenset({"search", "digest", "todos", "reflect", "workshop", "capture"})

#: 低于此长度不值得花一次 LLM 调用（语气词/短回话直接记日记）
MIN_TEXT_LEN = 6

_CLASSIFY_PROMPT = """你是个人知识库助手的意图分类器。把用户消息分成以下一类，输出 JSON：
{"intent": "...", "query": "..."}

类别：
- search：用户想找已保存的笔记/视频/资料（query 填提取的搜索关键词）
- digest：用户想看今日摘要/今天捕获了什么
- todos：用户想看待办清单/有什么事要做
- reflect：用户想复盘/回答今日三问
- workshop：用户想做决策分析、深度讨论、周回顾综合（需要长对话的事）
- capture：其它一切（随口记录、感想、聊天、无明确指令）

规则：拿不准一律 capture；不要输出 JSON 以外的内容。

用户消息："""


def _load_llm_config() -> Dict[str, Any]:
    """读取配置 ``dispatch.intent.llm`` 节（缺失/损坏返回空表）。"""
    for config_file in ("config/processors.yaml", "config/processors.yaml.example"):
        path = Path(config_file)
        if not path.exists():
            continue
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8"))
        except yaml.YAMLError:
            continue
        if isinstance(data, dict):
            section = data.get("dispatch")
            if isinstance(section, dict) and isinstance(section.get("intent"), dict):
                llm = section["intent"].get("llm")
                if isinstance(llm, dict):
                    return dict(llm)
    return {}


def _parse(content: str) -> Optional[Dict[str, str]]:
    """剥围栏/抽大括号块解析分类结果；坏 JSON/未知意图返回 None。"""
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", (content or "").strip())
    match = re.search(r"\{.*\}", text, re.S)
    if not match:
        return None
    try:
        data = json.loads(match.group(0))
    except (json.JSONDecodeError, ValueError):
        return None
    intent = str(data.get("intent") or "").strip()
    if intent not in INTENTS:
        return None
    return {"intent": intent, "query": str(data.get("query") or "").strip()}


def classify(text: str) -> Optional[Dict[str, str]]:
    """分类一条未命中精确命令的文本；应照旧记日记时返回 None。

    Returns:
        Optional[Dict]: {"intent", "query"}；capture/失败/短文本返回 None。
    """
    text = (text or "").strip()
    if len(text) < MIN_TEXT_LEN:
        return None
    api_key = os.environ.get(_LLM_KEY_ENV, "").strip()
    if not api_key:
        return None
    cfg = _load_llm_config()
    base_url = str(cfg.get("base_url", _LLM_DEFAULT_BASE_URL)).rstrip("/")
    payload = {
        "model": str(cfg.get("model", _LLM_DEFAULT_MODEL)),
        "messages": [{"role": "user", "content": _CLASSIFY_PROMPT + text}],
        "max_tokens": int(cfg.get("max_tokens", 150)),
        "temperature": 0,
        "thinking": {"type": "disabled"},
        "response_format": {"type": "json_object"},
    }
    try:
        response = httpx.post(
            f"{base_url}/chat/completions",
            headers={"Authorization": f"Bearer {api_key}"},
            json=payload,
            timeout=float(cfg.get("timeout", 15)),
        )
        response.raise_for_status()
        content = response.json()["choices"][0]["message"]["content"]
    except Exception:  # noqa: BLE001 - 意图是增强工序，失败退回 capture
        return None
    result = _parse(content)
    if result is None or result["intent"] == "capture":
        return None
    if result["intent"] == "search" and not result["query"]:
        return None  # 搜索没有关键词等于没听懂，退回记日记
    return result
