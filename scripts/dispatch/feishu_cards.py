"""飞书卡片组装器（自 feishu.py 拆出，2026-09-10）。

问答表单卡（schema 2.0）、新待办卡、今日复习卡；收发基元与协议
常量见 feishu_io.py。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional

from scripts.dispatch.feishu_io import (
    ARCHIVE_ACTION,
    PROMPT_FORM_MAX_QUESTIONS,
    PROMPT_SUBMIT_ACTION,
    TODO_DONE_ACTION,
    _console_url,
    send_feishu_card,
)

def prompt_form_card(title: str, intro: str, questions: List[str]) -> Dict[str, Any]:
    """问答表单卡（schema 2.0 form 容器：逐问输入框，一次提交收齐）。

    旧版卡片 schema 没有表单容器，故本卡用 ``"schema": "2.0"``；input
    组件必须嵌在 form 内（卡片 2.0 约束）。提交按钮
    ``action_type=form_submit``，回调进
    ``FeishuBridge._handle_prompt_submit``：value 固定
    ``{"action": "prompt_submit"}``，各问答案在 ``action.form_value``
    的 ``q1..qN`` 键位（序 = questions 序）。发送与降级走通用的
    send_feishu_card（header 结构与旧版一致，降级取标题不受影响）。

    Args:
        title: 卡片头标题。
        intro: 表单前的说明文字（markdown）。
        questions: 问题列表（最多 PROMPT_FORM_MAX_QUESTIONS 条，超出截断）。

    Returns:
        Dict[str, Any]: 卡片 JSON（schema 2.0）。
    """
    picked = [str(q) for q in questions[:PROMPT_FORM_MAX_QUESTIONS]]
    inputs: List[Dict[str, Any]] = [
        {
            "tag": "input",
            "name": f"q{index + 1}",
            "required": False,
            "width": "default",
            "label": {"tag": "plain_text", "content": f"{index + 1}. {question}"},
            "placeholder": {"tag": "plain_text", "content": "不想答可留空"},
        }
        for index, question in enumerate(picked)
    ]
    inputs.append(
        {
            "tag": "button",
            "name": "submit",
            "text": {"tag": "plain_text", "content": "提交回答"},
            "type": "primary",
            "action_type": "form_submit",
            "behaviors": [
                {"type": "callback", "value": {"action": PROMPT_SUBMIT_ACTION}}
            ],
        }
    )
    elements: List[Dict[str, Any]] = []
    if intro:
        elements.append({"tag": "markdown", "content": intro})
    elements.append(
        {
            "tag": "form",
            "name": "prompt_form",
            "elements": inputs,
        }
    )
    return {
        "schema": "2.0",
        "config": {"update_multi": True},
        "header": {
            "title": {"tag": "plain_text", "content": title},
            "template": "blue",
        },
        "body": {"elements": elements},
    }



def send_todo_feishu(filename: str, chat_id: Optional[str] = None) -> bool:
    """新待办提醒卡：「打开」（URI）+「✅ 已完成」（callback 删待办标签）。

    待办笔记来自 TodoDispatcher 的行动项判定；点「已完成」回调
    FeishuBridge._handle_todo_done（与「确认」同构的人工触发例外：
    只删 frontmatter tags 里的「待办」一项，其余一概不动）。

    Args:
        filename: 待办笔记文件名（相对 memory/ 根）。
        chat_id: 目标会话；缺省读 ``FEISHU_CHAT_ID``。

    Returns:
        bool: 发送成功返回 True（未配置静默 False）。
    """
    card = {
        "config": {"wide_screen_mode": True},
        "header": {
            "title": {"tag": "plain_text", "content": "Atelierr 新待办"},
            "template": "orange",
        },
        "elements": [
            {
                "tag": "div",
                "text": {
                    "tag": "lark_md",
                    "content": f"行动项判定产出：{filename}",
                },
            },
            {
                "tag": "action",
                "actions": [
                    {
                        "tag": "button",
                        "text": {"tag": "plain_text", "content": "在 Obsidian 中打开"},
                        "type": "primary",
                        "url": _console_url(filename),
                    },
                    {
                        "tag": "button",
                        "text": {"tag": "plain_text", "content": "✅ 已完成"},
                        "type": "primary",
                        "behaviors": [
                            {
                                "type": "callback",
                                "value": {
                                    "action": TODO_DONE_ACTION,
                                    "note": filename,
                                },
                            }
                        ],
                    },
                ],
            },
        ],
    }
    return send_feishu_card(card, chat_id)



def send_resurface_feishu(
    items: List[Dict[str, Any]], chat_id: Optional[str] = None
) -> bool:
    """今日复习卡：只给标题（先想），按钮才打开原文（再看）。

    卡片刻意不含笔记内容——「先在心里回想，再点开核对」是间隔重复
    的关键动作；想不起来的：值得就提炼进 wiki，不值得留给
    review→purge。

    Args:
        items: 复习候选（ResurfaceManager.candidates() 的 dict：
            title/relpath/idle_days）；逐条一个「打开」按钮，最多 5 条。
        chat_id: 目标会话；缺省读 ``FEISHU_CHAT_ID``。

    Returns:
        bool: 发送成功返回 True；空队列/未配置静默 False。
    """
    if not items:
        return False
    elements: List[Dict[str, Any]] = [
        {
            "tag": "div",
            "text": {
                "tag": "lark_md",
                "content": "先在心里回想内容，再点「打开」核对。",
            },
        }
    ]
    for item in items[:5]:
        elements.append(
            {
                "tag": "div",
                "text": {
                    "tag": "lark_md",
                    "content": (
                        f"**{item.get('title') or item['relpath']}**"
                        f"（闲置 {item.get('idle_days', '?')} 天）"
                    ),
                },
            }
        )
        elements.append(
            {
                "tag": "action",
                "actions": [
                    {
                        "tag": "button",
                        "text": {"tag": "plain_text", "content": "打开"},
                        "type": "primary",
                        "url": _console_url(item["relpath"]),
                    }
                ],
            }
        )
    card = {
        "config": {"wide_screen_mode": True},
        "header": {
            "title": {"tag": "plain_text", "content": f"🔁 今日复习（{len(items[:5])}）"},
            "template": "blue",
        },
        "elements": elements,
    }
    return send_feishu_card(card, chat_id)



def send_pending_digest_feishu(
    filenames: List[str], chat_id: Optional[str] = None
) -> bool:
    """晚间待确认清单卡（2026-09-13 用户裁决：无评论的捕获不单独推卡，
    攒成一张批量处理——确认端减负）。

    每条笔记一节：标题 + 「✅ 确认并归档」按钮（callback 复用
    FeishuBridge 的 archive_note 分支：推导目录直接移动+删标签，
    推不出平台时退化为仅确认）。想细看/换目录：点标题到 Obsidian。

    Args:
        filenames: 仍带「待确认」的笔记相对路径列表（最多 20 条，
            由 pending_push.MAX_ITEMS 截断）。
        chat_id: 目标会话；缺省读 ``FEISHU_CHAT_ID``。

    Returns:
        bool: 发送成功返回 True；空列表/未配置静默 False。
    """
    if not filenames:
        return False
    elements: List[Dict[str, Any]] = [
        {
            "tag": "div",
            "text": {
                "tag": "lark_md",
                "content": (
                    "今天无评论的捕获攒成这一张（写了评论的已即时单推）。"
                    "逐条点「✅ 确认并归档」，或到 Obsidian 细看再处理。"
                ),
            },
        }
    ]
    for index, rel in enumerate(filenames[:20], 1):
        stem = Path(rel).stem
        elements.append(
            {
                "tag": "div",
                "text": {"tag": "lark_md", "content": f"**{index}. {stem}**"},
            }
        )
        elements.append(
            {
                "tag": "action",
                "actions": [
                    {
                        "tag": "button",
                        "text": {"tag": "plain_text", "content": "✅ 确认并归档"},
                        "type": "primary",
                        "behaviors": [
                            {
                                "type": "callback",
                                "value": {"action": ARCHIVE_ACTION, "note": rel},
                            }
                        ],
                    },
                    {
                        "tag": "button",
                        "text": {"tag": "plain_text", "content": "打开细看"},
                        "type": "default",
                        "url": _console_url(rel),
                    },
                ],
            }
        )
    card = {
        "config": {"wide_screen_mode": True},
        "header": {
            "title": {
                "tag": "plain_text",
                "content": f"📋 今日待确认清单（{len(filenames[:20])} 条）",
            },
            "template": "blue",
        },
        "elements": elements,
    }
    return send_feishu_card(card, chat_id)
