"""飞书卡片组装器（自 feishu.py 拆出，2026-09-10）。

问答表单卡（schema 2.0）、新待办卡、今日复习卡；收发基元与协议
常量见 feishu_io.py。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional

from scripts.dispatch.feishu_io import (
    ARCHIVE_ACTION,
    DISCARD_ACTION,
    JUDGMENT_REVIEW_ACTION,
    RESURFACE_FEEDBACK_ACTION,
    NOTE_REMARK_ACTION,
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
    ``form_action_type=submit``（2026-09-13 实测修正：写
    action_type=form_submit 平台直接拒收，230099/300123「form 容器
    没有提交按钮」——此前该卡从未真机渲染成功过），回调进
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
            "form_action_type": "submit",
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


def todo_batch_card(items: List[Dict[str, str]]) -> Dict[str, Any]:
    """新待办批量卡（纯组装）：多条待办合并一张，防逐条刷屏（2026-09-15
    用户裁决，卡片管理评审）。

    每条一节：标题 + 「打开」（URI）+「✅ 已完成」（callback）。回调
    value 带 ``batch``（全部条目）：点掉一条后桥用剩余条目重建本卡
    （与清单卡/复习卡同规——平台回调的卡片更新是整卡替换）。

    Args:
        items: [{"filename": 待办笔记文件名, "title": 任务标题}]。
    """
    batch = [str(item["filename"]) for item in items]
    elements: List[Dict[str, Any]] = [
        {
            "tag": "div",
            "text": {
                "tag": "lark_md",
                "content": "本轮提取出的行动项，逐条「打开」看详情、办完点「✅」。",
            },
        }
    ]
    for index, item in enumerate(items, 1):
        filename = str(item["filename"])
        title = str(item.get("title") or Path(filename).stem)
        elements.append(
            {"tag": "div", "text": {"tag": "lark_md", "content": f"**{index}. {title}**"}}
        )
        elements.append(
            {
                "tag": "action",
                "actions": [
                    {
                        "tag": "button",
                        "text": {"tag": "plain_text", "content": "打开"},
                        "type": "primary",
                        "url": _console_url(filename),
                    },
                    {
                        "tag": "button",
                        "text": {"tag": "plain_text", "content": "✅ 已完成"},
                        "type": "default",
                        "behaviors": [
                            {
                                "type": "callback",
                                "value": {
                                    "action": TODO_DONE_ACTION,
                                    "note": filename,
                                    "batch": batch,
                                },
                            }
                        ],
                    },
                ],
            }
        )
    return {
        "config": {"wide_screen_mode": True},
        "header": {
            "title": {"tag": "plain_text", "content": f"Atelierr 新待办 {len(items)} 条"},
            "template": "orange",
        },
        "elements": elements,
    }


def resurface_card(items: List[Dict[str, Any]]) -> Dict[str, Any]:
    """今日复习卡（纯组装，不发送——回调重建同构卡片也用它）。

    逐条：标题 + 闲置天数 +「✅ 想起来了」（主按钮，先自评）/
    「❌ 没想起来」/「📖 核对原文」（URI，自评后再核对）/「🚫 不再推」
    （callback，value 带 batch——平台回调整卡替换，点掉一条后桥用
    「batch 减去该条」重建本卡，其余条目不消失；与清单卡同规）。
    按钮动线刻意「想 → 自评 → 核对」：主按钮是自评而不是打开原文
    （2026-09-21 检索练习强化，脑科学评审：点开≠掌握）。
    """
    elements: List[Dict[str, Any]] = [
        {
            "tag": "div",
            "text": {
                "tag": "lark_md",
                "content": (
                    "先默想 10 秒：这条讲了什么？它对你今天有什么用？\n"
                    "想完先点 ✅/❌ 自评，再点「核对原文」验证（先回忆后展示）；"
                    "✅/❌ 我按反馈调间隔（连错 2 次自动停推），🚫 这条以后不再推。"
                ),
            },
        }
    ]
    batch = [str(item["relpath"]) for item in items[:5]]
    for item in items[:5]:
        relpath = str(item["relpath"])
        elements.append(
            {
                "tag": "div",
                "text": {
                    "tag": "lark_md",
                    "content": (
                        f"**{item.get('title') or relpath}**"
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
                        "text": {"tag": "plain_text", "content": "✅ 想起来了"},
                        "type": "primary",
                        "behaviors": [
                            {
                                "type": "callback",
                                "value": {
                                    "action": RESURFACE_FEEDBACK_ACTION,
                                    "note": relpath,
                                    "outcome": "good",
                                    "batch": batch,
                                },
                            }
                        ],
                    },
                    {
                        "tag": "button",
                        "text": {"tag": "plain_text", "content": "❌ 没想起来"},
                        "type": "default",
                        "behaviors": [
                            {
                                "type": "callback",
                                "value": {
                                    "action": RESURFACE_FEEDBACK_ACTION,
                                    "note": relpath,
                                    "outcome": "bad",
                                    "batch": batch,
                                },
                            }
                        ],
                    },
                    {
                        "tag": "button",
                        "text": {"tag": "plain_text", "content": "📖 核对原文"},
                        "type": "default",
                        "url": _console_url(relpath),
                    },
                    {
                        "tag": "button",
                        "text": {"tag": "plain_text", "content": "🚫 不再推"},
                        "type": "default",
                        "behaviors": [
                            {
                                "type": "callback",
                                "value": {
                                    "action": RESURFACE_FEEDBACK_ACTION,
                                    "note": relpath,
                                    "outcome": "exile",
                                    "batch": batch,
                                },
                            }
                        ],
                    },
                ],
            }
        )
    return {
        "config": {"wide_screen_mode": True},
        "header": {
            "title": {"tag": "plain_text", "content": f"🔁 今日复习（{len(batch)}）"},
            "template": "blue",
        },
        "elements": elements,
    }


def send_resurface_feishu(
    items: List[Dict[str, Any]], chat_id: Optional[str] = None
) -> bool:
    """今日复习卡：只给标题（先想），自评后才有「核对原文」（再看）。

    卡片刻意不含笔记内容，主按钮是 ✅/❌ 自评而不是打开原文——
    「先在心里回想，再点开核对」是间隔重复的关键动作（2026-09-21
    脑科学评审：点开只是再认，自评才是提取练习）；想不起来的：
    值得就提炼进压缩层，不值得留给 review→purge。反馈按钮
    （想起来/没想起来）驱动每篇的独立间隔（2026-09-13 间隔重复升级）。

    Args:
        items: 复习候选（ResurfaceManager.candidates() 的 dict：
            title/relpath/idle_days）；逐条一组按钮，最多 5 条。
        chat_id: 目标会话；缺省读 ``FEISHU_CHAT_ID``。

    Returns:
        bool: 发送成功返回 True；空队列/未配置静默 False。
    """
    if not items:
        return False
    return send_feishu_card(resurface_card(items), chat_id)


def confirmed_with_remark_card(
    filename: str, note_line: str, header: str = "✅ 已确认"
) -> Dict[str, Any]:
    """确认/归档完成卡（schema 2.0）：完成文案 + 「顺手记一句」可选表单。

    2026-09-13 环节三评审毛病 2（用户批准）：确认时刻是意义建构窗口——
    表单可空（不填零成本），填了经 NOTE_REMARK_ACTION 回调由
    FeishuBridge._handle_note_remark 追加进笔记末尾。
    2026-09-22 脑科学裁决：问句从「记收获」改为「想起什么」——精细加工
    （把新笔记挂到旧笔记/目标上）是最强编码手段；提到的旧笔记名会被
    实体反链自动连上。

    Args:
        filename: 笔记文件名（回调定位用）。
        note_line: 完成场景文案（已确认/已归档到 X 等）。
        header: 卡片头文案。

    Returns:
        Dict[str, Any]: 卡片 JSON（schema 2.0，form 容器）。
    """
    return {
        "schema": "2.0",
        "config": {"update_multi": True},
        "header": {
            "title": {"tag": "plain_text", "content": header},
            "template": "green",
        },
        "body": {
            "elements": [
                {
                    "tag": "markdown",
                    "content": f"**{filename}**\n{note_line}",
                },
                {
                    "tag": "form",
                    "name": "remark_form",
                    "elements": [
                        {
                            "tag": "input",
                            "name": "q1",
                            "required": False,
                            "width": "default",
                            "label": {
                                "tag": "plain_text",
                                "content": "它让你想起什么？（可空）",
                            },
                            "placeholder": {
                                "tag": "plain_text",
                                "content": "和哪条旧笔记/哪个目标有关？提到名字会自动连上",
                            },
                        },
                        {
                            "tag": "button",
                            "name": "submit",
                            "text": {"tag": "plain_text", "content": "💾 记下"},
                            "type": "default",
                            "form_action_type": "submit",
                            "behaviors": [
                                {
                                    "type": "callback",
                                    "value": {
                                        "action": NOTE_REMARK_ACTION,
                                        "note": filename,
                                    },
                                }
                            ],
                        },
                    ],
                },
            ]
        },
    }


def completed_notice_card(
    title: str, note_line: str, header: str = "✅ 已完成"
) -> Dict[str, Any]:
    """操作完成通知卡（schema 2.0，无表单）——**2.0 卡回调的返回值专用**。

    2026-09-19 实证（顺手记/问答表单提交，客户端报错但后端已成功）：
    回调返回的更新卡必须与触发卡**同 schema 版本**——2.0 表单卡的回调
    返回 legacy 卡平台报错；2026-09-13 已实测反向错配（legacy 卡回调
    返回 2.0 卡）同样报错。legacy 卡的回调照旧用
    ``FeishuBridge._confirmed_card``。

    Args:
        title: 完成对象（笔记文件名/「问答表单」等）。
        note_line: 完成场景文案。
        header: 卡片头文案。

    Returns:
        Dict[str, Any]: 卡片 JSON（schema 2.0，纯文案无操作区）。
    """
    return {
        "schema": "2.0",
        "config": {"update_multi": True},
        "header": {
            "title": {"tag": "plain_text", "content": header},
            "template": "green",
        },
        "body": {
            "elements": [
                {"tag": "markdown", "content": f"**{title}**\n{note_line}"},
            ]
        },
    }


def pending_digest_card(filenames: List[str]) -> Dict[str, Any]:
    """待确认清单卡（纯组装，不发送——回调重建同构卡片也用它）。

    每个按钮的回调 value 带 ``batch``（整张卡的条目清单）：点掉一条后
    FeishuBridge 用「batch 减去已处理项」重建本卡——清单卡是单卡多条，
    平台回调的卡片更新是**整卡替换**，不重建会让其余条目"消失"
    （2026-09-13 真机实测：点一条另外两条不见了；笔记无损，仅视图）。
    """
    elements: List[Dict[str, Any]] = [
        {
            "tag": "div",
            "text": {
                "tag": "lark_md",
                "content": (
                    "无评论的捕获攒成这一张（写了评论的已即时单推）。"
                    "逐条问一句：值得留下吗？留就 ✅，不值就 🗑（进待删，周报终审）。"
                ),
            },
        }
    ]
    batch = list(filenames[:20])
    for index, rel in enumerate(batch, 1):
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
                                "value": {
                                    "action": ARCHIVE_ACTION,
                                    "note": rel,
                                    "batch": batch,
                                },
                            }
                        ],
                    },
                    {
                        "tag": "button",
                        "text": {"tag": "plain_text", "content": "打开细看"},
                        "type": "default",
                        "url": _console_url(rel),
                    },
                    {
                        "tag": "button",
                        "text": {"tag": "plain_text", "content": "🗑"},
                        "type": "danger",
                        "behaviors": [
                            {
                                "type": "callback",
                                "value": {
                                    "action": DISCARD_ACTION,
                                    "note": rel,
                                    "batch": batch,
                                },
                            }
                        ],
                    },
                ],
            }
        )
    return {
        "config": {"wide_screen_mode": True},
        "header": {
            "title": {
                "tag": "plain_text",
                "content": f"📋 待确认清单（{len(batch)} 条）",
            },
            "template": "blue",
        },
        "elements": elements,
    }


def send_pending_digest_feishu(
    filenames: List[str], chat_id: Optional[str] = None
) -> bool:
    """晚间待确认清单卡（2026-09-13 用户裁决：无评论的捕获不单独推卡，
    攒成一张批量处理——确认端减负）。

    每条笔记一节：标题 + 「✅ 确认并归档」（archive_note 回调）+
    「打开细看」（URI）+「🗑」（discard_note 标 pending_delete）。

    Args:
        filenames: 仍带「待确认」的笔记相对路径列表（最多 20 条，
            由 pending_push.MAX_ITEMS 截断）。
        chat_id: 目标会话；缺省读 ``FEISHU_CHAT_ID``。

    Returns:
        bool: 发送成功返回 True；空列表/未配置静默 False。
    """
    if not filenames:
        return False
    return send_feishu_card(pending_digest_card(filenames), chat_id)


def judgment_review_card(entry_id: str, statement: str, entry_type: str, days: int) -> Dict[str, Any]:
    """判断复盘卡（legacy）：陈述 + 账龄 + 三按钮（仍成立/不成立/要调整）。

    2026-09-19 backlog⑤ 生命周期闭环（登记→复盘→销账）：按钮回调
    ``FeishuBridge._handle_judgment_review`` 落账（legacy 卡回调配
    legacy 返回，与 2.0 版本错配修复同规）。

    Args:
        entry_id: cognition 条目 id（回调定位用）。
        statement: 判断陈述原文（展示截断 60 字）。
        entry_type: belief/hypothesis/decision（展示用中文名）。
        days: 登记账龄（天）。
    """
    type_name = {"belief": "判断", "hypothesis": "假设", "decision": "决定"}.get(
        entry_type, "判断"
    )
    head = statement if len(statement) <= 60 else statement[:60] + "…"
    buttons = [
        ("✅ 仍成立", "primary", "still_true"),
        ("❌ 不成立", "danger", "not_true"),
        ("🔧 要调整", "default", "adjust"),
    ]
    return {
        "config": {"wide_screen_mode": True},
        "header": {
            "title": {"tag": "plain_text", "content": "🧭 判断复盘"},
            "template": "violet",
        },
        "elements": [
            {
                "tag": "div",
                "text": {
                    "tag": "lark_md",
                    "content": (
                        f"{days} 天前你记下这条{type_name}：\n**{head}**\n"
                        "现在回头看，它还成立吗？"
                    ),
                },
            },
            {
                "tag": "action",
                "actions": [
                    {
                        "tag": "button",
                        "text": {"tag": "plain_text", "content": text},
                        "type": btn_type,
                        "behaviors": [
                            {
                                "type": "callback",
                                "value": {
                                    "action": JUDGMENT_REVIEW_ACTION,
                                    "entry": entry_id,
                                    "outcome": outcome,
                                },
                            }
                        ],
                    }
                    for text, btn_type, outcome in buttons
                ],
            },
        ],
    }


def send_judgment_review_feishu(
    entry_id: str, statement: str, entry_type: str, days: int, chat_id: Optional[str] = None
) -> bool:
    """发送判断复盘卡；未配置/失败静默 False（晨报兜底会在摘要里点名）。"""
    return send_feishu_card(
        judgment_review_card(entry_id, statement, entry_type, days), chat_id
    )
