"""飞书收发基元与卡片协议常量（自 feishu.py 拆出，2026-09-10）。

内容：环境变量与 action 协议常量、lark 惰性导入、Obsidian 深链
（``_console_url``）、消息发送（``_send`` / ``send_feishu`` /
``send_feishu_card``）、确认卡组装（``_confirm_action_card``）、
卡片置顶（``_pin_card``）。桥（接收+回调+菜单）在 feishu.py；
更多卡片组装器在 feishu_cards.py。纪律与 feishu.py 模块 docstring 同源。
"""

from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional
from urllib.parse import quote

from scripts.memory.core import SYSTEM_DIRNAME
from scripts.utils.state_store import read_json, write_json

#: 环境变量名（凭证与推送目标）
ENV_APP_ID = "FEISHU_APP_ID"
ENV_APP_SECRET = "FEISHU_APP_SECRET"
ENV_CHAT_ID = "FEISHU_CHAT_ID"
ENV_CONSOLE_URL = "FEISHU_CONSOLE_URL"
#: Obsidian 库名（obsidian://open?vault=…；可用 FEISHU_VAULT_NAME 覆盖）
ENV_VAULT_NAME = "FEISHU_VAULT_NAME"
DEFAULT_VAULT_NAME = "atelierr-data"
#: 库内笔记路径前缀（FEISHU_NOTE_PREFIX 覆盖；库根=atelierr-data 时
#: 缺省 "memory/"，自定义库名缺省空——该缺省只适用于"库根即 memory/
#: 文件夹"的旧布局。本机实际布局（2026-09-14 核实）：手机端库名
#: atelierr-memory，库根与桌面同为数据根（memory/ 是其子目录），故
#: 本机 env 必须显式设 FEISHU_NOTE_PREFIX=memory/，不能用缺省空）
ENV_NOTE_PREFIX = "FEISHU_NOTE_PREFIX"

DEFAULT_CONSOLE_URL = "obsidian://"

#: 卡片按钮 action 值里的动作名与「确认」标签（后者与
#: dispatch/links.py、dispatch/media.py 的 REVIEW_TAG 同值）
CONFIRM_ACTION = "confirm_note"
ARCHIVE_ACTION = "archive_note"
CONFIRM_TAG = "待确认"
#: 「✅ 已完成」待办按钮动作名与「待办」标签（后者与
#: dispatch/todos.py 的 TODO_TAG 同值）
TODO_DONE_ACTION = "todo_done"
TODO_TAG = "待办"
#: 「📁 归档…」先弹目录选择卡（人工确认去处再移，机器推导只作推荐）；
#: 「取消」还原确认卡
ARCHIVE_PICK_ACTION = "archive_pick"
ARCHIVE_CANCEL_ACTION = "archive_cancel"
#: 问答表单卡「提交回答」（schema 2.0 form 容器；答案在回调 form_value）
PROMPT_SUBMIT_ACTION = "prompt_submit"
#: 「🗑 不要了」按钮（2026-09-13 环节三评审毛病 1）：只标 pending_delete
#: （不动文件），仍走 review → purge → trash/ 人工链路，安全绳一层不少
DISCARD_ACTION = "discard_note"
#: 确认完成卡上的「💾 记下」可选表单（2026-09-13 环节三评审毛病 2：
#: 确认时刻顺手记一句收获；答案在回调 form_value 的 q1，可空）
NOTE_REMARK_ACTION = "note_remark"
#: 复习卡「想起来了/没想起来」反馈（2026-09-13 间隔重复升级：
#: 驱动每篇笔记的独立复习间隔；value 带 outcome=good/bad）
RESURFACE_FEEDBACK_ACTION = "resurface_feedback"
#: 判断复盘卡「仍成立/不成立/要调整」（2026-09-19 backlog⑤ 生命周期
#: 闭环：登记→复盘→销账；value 带 entry=cognition id + outcome）
JUDGMENT_REVIEW_ACTION = "judgment_review"

#: 问答表单卡的问题数上限（卡片长度护栏；周回顾四问远未触及）
PROMPT_FORM_MAX_QUESTIONS = 8

#: 安静时段（本地时间 23:00–07:00）：主动推送一律静音
#: （2026-09-19 脑科学建议③：睡眠是记忆固化主战场，夜间推送是
#: 固化杀手+注意力残留；用户主动操作的交互回执经 respect_quiet=False
#: 旁路——交互不是打扰。现有定时班次本就在窗外，这是防未来回归的硬闸）
QUIET_START_HOUR = 23
QUIET_END_HOUR = 7


def quiet_hours_active(now: Optional[datetime] = None) -> bool:
    """当前是否安静时段（本地 23:00–07:00；注入 now 供测试）。"""
    moment = now or datetime.now()
    return moment.hour >= QUIET_START_HOUR or moment.hour < QUIET_END_HOUR

def _import_lark() -> Any:
    """惰性导入 lark-oapi（可选依赖；缺失时报清晰错误）。"""
    try:
        import lark_oapi as lark  # type: ignore[import-not-found]
    except ImportError as exc:  # pragma: no cover - 依赖缺失路径
        raise RuntimeError(
            "飞书桥需要 lark-oapi：pip install lark-oapi"
        ) from exc
    return lark



def _console_url(confirm_note: Optional[str]) -> str:
    """「在 Obsidian 中打开」按钮 URL。

    ``FEISHU_CONSOLE_URL`` 环境变量优先（自定义控制台地址）；否则
    生成 ``obsidian://open?vault=<库名>&file=<前缀><笔记去后缀>``
    直达本条笔记（percent-encode 防中文/井号/空格截断）。库名用
    ``FEISHU_VAULT_NAME`` 覆盖（缺省 atelierr-data=桌面端库）；路径
    前缀用 ``FEISHU_NOTE_PREFIX`` 覆盖，缺省跟随库名：库根是
    atelierr-data 时为 ``memory/``，自定义库名时为空。**前缀必须与
    该设备库的真实结构一致**：本机手机端库名 ``atelierr-memory``、
    库根与桌面同为数据根（memory/ 是其子目录，2026-09-14 按真机
    截图核实），故本机 env 显式设 ``FEISHU_NOTE_PREFIX=memory/``——
    2026-09-14 曾误判"手机库根即 memory/ 文件夹"把前缀置空，导致
    手机端全部按钮静默打不开，当天改回。双根（契约 v1.5）：
    ``inbox/`` 与 memory/ 平级，带 ``inbox/`` 虚拟前缀的路径一律
    不再加 memory/ 前缀。无目标笔记（digest 等汇总通知）时落到
    控制台门面页（系统/控制台）——bare ``obsidian://`` 只开应用
    不定位，属反人机交互，任何按钮都不再用裸 scheme。注意库名必须
    与设备实际库名完全一致（本机手机端为 ``atelierr-memory``）：
    库名不匹配时 Obsidian 静默退回最近打开页，表现为"链接指错笔记"。
    路径三档规则：① 裸文件名（无 ``/``）只会是机器刚产出的中转站
    笔记（链接/媒体/待办产出卡一律 ``create_note(inbox=True)``），
    一律按 ``inbox/`` 解析——2026-09-14 实证：待办卡按
    ``memory/<裸名>`` 指空、Obsidian 静默退回控制台页；② 带
    ``inbox/`` 虚拟前缀的路径不再加前缀（inbox/ 与 memory/ 平级）；
    ③ 其余带目录的路径（系统/控制台、抖音/B-哲学/x 等 memory/ 内
    路径）加库前缀。
    """
    console_url = os.environ.get(ENV_CONSOLE_URL, "").strip()
    if console_url:
        return console_url
    vault = os.environ.get(ENV_VAULT_NAME, DEFAULT_VAULT_NAME)
    prefix = os.environ.get(ENV_NOTE_PREFIX)
    if prefix is None:
        prefix = "memory/" if vault == DEFAULT_VAULT_NAME else ""
    if confirm_note:
        stem = confirm_note[:-3] if confirm_note.endswith(".md") else confirm_note
    else:
        # 汇总通知无对应笔记：落控制台门面（精确子目录路径 系统/控制台；
        # 库名必须与实际一致——库名错了 Obsidian 静默退回最近打开页）
        stem = f"{SYSTEM_DIRNAME}/控制台"
    if "/" not in stem:
        # 裸文件名只会是机器刚产出的中转站笔记（链接/媒体/待办产出卡
        # 一律 create_note(inbox=True)）——按中转站解析。2026-09-14 实证：
        # 待办卡曾按 memory/<裸名> 指空，Obsidian 静默退回最近打开页
        # （控制台）。memory/ 根层散文件没有任何卡片会指过来。
        stem = f"inbox/{stem}"
        prefix = ""
    elif stem.startswith("inbox/"):
        # 双根（契约 v1.5）：inbox/ 是 memory/ 的平级目录，不是其子目录
        prefix = ""
    return f"obsidian://open?vault={quote(vault)}&file={quote(prefix + stem)}"



def send_feishu(
    title: str,
    message: str,
    chat_id: Optional[str] = None,
    confirm_note: Optional[str] = None,
    pin: bool = False,
    pin_state: Optional[Path] = None,
    respect_quiet: bool = True,
) -> bool:
    """发一条飞书卡片推送；未配置或失败返回 False（绝不抛异常）。

    卡片带「在 Obsidian 中打开」URI 按钮（纯客户端跳转，无回调）；
    ``confirm_note`` 给定时追加两个 callback 按钮（value 均为 dict）：
    「✅ 确认」（confirm_note：只删「待确认」标签）与「📁 归档…」
    （archive_pick：先弹目录选择卡，点定后 archive_note 归档移动 +
    删标签，见 FeishuBridge.handle_card_action）；
    卡片发送失败时降级为纯文本消息再试一次。
    ``pin=True`` 时发送成功把卡片置顶（晨报盘面第一眼可见），并先摘下
    ``pin_state`` 登记表里的上一条（每日替换不堆积）；置顶失败只 log，
    不影响发送结果。
    ``respect_quiet=True``（默认）时安静时段（23:00–07:00）直接返回
    False 不发送——主动推送静音；交互回执传 False 旁路。

    Args:
        title: 通知标题。
        message: 通知正文（只放数量等非敏感信息）。
        chat_id: 目标会话；缺省读 ``FEISHU_CHAT_ID`` 环境变量。
        confirm_note: 待确认笔记文件名；None 不加确认/归档按钮。
        pin: 发送成功后是否置顶该卡片。
        pin_state: 置顶登记表（存上一条 message_id）；None 只置顶不替换。
        respect_quiet: 是否遵守安静时段（主动推送默认遵守）。

    Returns:
        bool: 发送成功且服务端 success 返回 True。
    """
    if respect_quiet and quiet_hours_active():
        return False
    app_id = os.environ.get(ENV_APP_ID, "").strip()
    app_secret = os.environ.get(ENV_APP_SECRET, "").strip()
    target = (chat_id or os.environ.get(ENV_CHAT_ID, "")).strip()
    if not app_id or not app_secret or not target:
        return False
    try:
        lark = _import_lark()
        client = (
            lark.Client.builder()
            .app_id(app_id)
            .app_secret(app_secret)
            .build()
        )
        card = _confirm_action_card(title, message, confirm_note)
        message_id = _send(client, target, "interactive", json.dumps(card))
        if message_id is not None:
            if pin and message_id:
                _pin_card(client, message_id, pin_state)
            return True
        return _send(
            client, target, "text", json.dumps({"text": f"{title}\n{message}"})
        ) is not None
    except Exception:  # noqa: BLE001 - 推送失败不影响主流程
        return False



def _confirm_action_card(
    title: str, message: str, confirm_note: Optional[str]
) -> Dict[str, Any]:
    """确认卡 JSON：打开（URI）+ 确认/归档三按钮（callback）。

    2026-09-12 裁决（归档默认化）：主按钮「✅ 确认并归档」一步到位
    （机器推导目录直接移动+删标签；2026-09-21 起推导不出领域的手写/
    无来源笔记落默认 personal/，见 archive.HANDWRITTEN_ARCHIVE_DIR）；
    「📁 选目录…」弹目录选择卡（想换去处时用，取消还原本卡）；
    「仅确认」留在收件箱（根目录）显式选择。滞留根目录由晨报
    「滞留提醒」兜底点名。
    """
    actions = [
        {
            "tag": "button",
            "text": {
                "tag": "plain_text",
                "content": "在 Obsidian 中打开",
            },
            "type": "primary",
            "url": _console_url(confirm_note),
        }
    ]
    if confirm_note:
        actions.append(
            {
                "tag": "button",
                "text": {"tag": "plain_text", "content": "✅ 确认并归档"},
                "type": "primary",
                # 新版卡片 callback：value 直接放 JSON 对象（若放字符串，
                # 回调时平台原样回传，SDK 校验 action.value 必须是 dict
                # 会直接报错丢弃，回调永远到不了处理器）
                # 不带 dir：归档目标由 _archive_note 推导（推不出→仅确认）
                "behaviors": [
                    {
                        "type": "callback",
                        "value": {"action": ARCHIVE_ACTION, "note": confirm_note},
                    }
                ],
            }
        )
        actions.append(
            {
                "tag": "button",
                "text": {"tag": "plain_text", "content": "📁 选目录…"},
                "type": "primary",
                # 同上：value 必须是 dict（回调进 handle_card_action 的
                # archive_pick 分支：先弹目录选择卡，点定才移动）
                "behaviors": [
                    {
                        "type": "callback",
                        "value": {
                            "action": ARCHIVE_PICK_ACTION,
                            "note": confirm_note,
                        },
                    }
                ],
            }
        )
        actions.append(
            {
                "tag": "button",
                "text": {"tag": "plain_text", "content": "仅确认"},
                "type": "default",
                "behaviors": [
                    {
                        "type": "callback",
                        "value": {"action": CONFIRM_ACTION, "note": confirm_note},
                    }
                ],
            }
        )
        actions.append(
            {
                "tag": "button",
                "text": {"tag": "plain_text", "content": "🗑 不要了"},
                "type": "danger",
                # 只标 pending_delete（不动文件），仍走 review → purge
                # 人工链路——丢弃有缓冲，误点可捞回
                "behaviors": [
                    {
                        "type": "callback",
                        "value": {"action": DISCARD_ACTION, "note": confirm_note},
                    }
                ],
            }
        )
    return {
        "config": {"wide_screen_mode": True},
        "header": {
            "title": {"tag": "plain_text", "content": title},
            "template": "blue",
        },
        "elements": [
            {"tag": "div", "text": {"tag": "lark_md", "content": message}},
            *(
                [
                    {
                        "tag": "div",
                        "text": {
                            "tag": "lark_md",
                            # 2026-09-18 脑科学评审 C5：把确认从反射变回决策
                            "content": "—— 问一句：这条值得留下吗？留就 ✅，不值就 🗑。",
                        },
                    }
                ]
                if confirm_note
                else []
            ),
            {"tag": "action", "actions": actions},
        ],
    }





def _bump_push_counter() -> None:
    """推卡计数（2026-09-18 「打扰账单」）：每张成功发出的卡 +1。

    只写 ``<state>/push_log.json``（{"YYYY-MM-DD": N}），状态目录取
    ``ATELIERR_STATE_DIR`` 环境变量（缺省 ~/atelierr-data/state）。
    任何失败静默——计数是观测工序，绝不影响发卡主流程。
    """
    try:
        state_dir = Path(
            os.environ.get("ATELIERR_STATE_DIR")
            or str(Path.home() / "atelierr-data" / "state")
        )
        path = state_dir / "push_log.json"
        today = datetime.now().strftime("%Y-%m-%d")
        data = read_json(path, {})
        if not isinstance(data, dict):
            data = {}
        data[today] = int(data.get(today) or 0) + 1
        write_json(path, data, indent=0)
    except Exception:  # noqa: BLE001 - 观测工序静默
        pass


def send_feishu_card(
    card: Dict[str, Any],
    chat_id: Optional[str] = None,
    app_id: Optional[str] = None,
    app_secret: Optional[str] = None,
    respect_quiet: bool = True,
) -> bool:
    """发一张自定义交互卡片；未配置或失败返回 False（绝不抛异常）。

    卡片发送失败时降级为纯文本（取卡片头标题）再试一次。
    ``respect_quiet=True``（默认）时安静时段（23:00–07:00）直接返回
    False 不发送——主动推送静音；交互回执（桥 _send_card）传 False 旁路。

    Args:
        card: 卡片 JSON（legacy schema：header + elements）。
        chat_id: 目标会话；缺省读 ``FEISHU_CHAT_ID`` 环境变量。
        app_id / app_secret: 凭据覆盖；缺省读环境变量（桥实例传入自身凭据）。
        respect_quiet: 是否遵守安静时段（主动推送默认遵守）。

    Returns:
        bool: 发送成功且服务端 success 返回 True。
    """
    if respect_quiet and quiet_hours_active():
        return False
    app_id = (app_id or os.environ.get(ENV_APP_ID, "")).strip()
    app_secret = (app_secret or os.environ.get(ENV_APP_SECRET, "")).strip()
    target = (chat_id or os.environ.get(ENV_CHAT_ID, "")).strip()
    if not app_id or not app_secret or not target:
        return False
    try:
        lark = _import_lark()
        client = (
            lark.Client.builder()
            .app_id(app_id)
            .app_secret(app_secret)
            .build()
        )
        if _send(client, target, "interactive", json.dumps(card)) is not None:
            _bump_push_counter()
            return True
        title = card.get("header", {}).get("title", {}).get("content", "")
        text = str(title) if title else "（卡片发送失败）"
        return _send(client, target, "text", json.dumps({"text": text})) is not None
    except Exception:  # noqa: BLE001 - 发卡失败不影响主流程
        return False



def _pin_card(
    client: Any, message_id: str, pin_state: Optional[Path]
) -> None:
    """置顶一条卡片消息；先摘下登记表里的上一条。任何失败只 log。

    登记表 JSON：{"message_id": <上一条置顶>}，用来每日替换不堆积。
    """
    lark = _import_lark()
    previous = ""
    if pin_state is not None:
        data = read_json(pin_state, {})
        if isinstance(data, dict):
            previous = str(data.get("message_id") or "")
    if previous:
        try:
            request = (
                lark.api.im.v1.DeletePinRequest.builder()
                .message_id(previous)
                .build()
            )
            client.im.v1.pin.delete(request)
        except Exception as exc:  # noqa: BLE001 - 摘旧置顶失败不阻塞新置顶
            print(f"[feishu] unpin {previous} fail: {exc}", flush=True)
    try:
        body = (
            lark.api.im.v1.CreatePinRequestBody.builder()
            .message_id(message_id)
            .build()
        )
        request = (
            lark.api.im.v1.CreatePinRequest.builder().request_body(body).build()
        )
        if not client.im.v1.pin.create(request).success():
            print(f"[feishu] pin {message_id} fail", flush=True)
            return
    except Exception as exc:  # noqa: BLE001 - 置顶失败不影响发送结果
        print(f"[feishu] pin fail: {exc}", flush=True)
        return
    if pin_state is not None:
        try:
            write_json(pin_state, {"message_id": message_id})
        except OSError as exc:
            print(f"[feishu] pin state write fail: {exc}", flush=True)



def _send(client: Any, chat_id: str, msg_type: str, content: str) -> Optional[str]:
    """单发一条消息；成功返回 message_id（取不到返回 ""），失败返回 None。"""
    lark = _import_lark()
    body = (
        lark.api.im.v1.CreateMessageRequestBody.builder()
        .receive_id(chat_id)
        .msg_type(msg_type)
        .content(content)
        .build()
    )
    request = (
        lark.api.im.v1.CreateMessageRequest.builder()
        .receive_id_type("chat_id")
        .request_body(body)
        .build()
    )
    response = client.im.v1.message.create(request)
    if not response.success():
        return None
    data = getattr(response, "data", None)
    message_id = getattr(data, "message_id", None) if data is not None else None
    return str(message_id) if message_id else ""
