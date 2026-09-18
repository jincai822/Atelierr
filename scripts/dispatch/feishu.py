"""飞书机器人桥：长连接收消息进库 + 卡片推送（双向通道）。

接收（飞书 → 系统）：
- 消息事件经 lark-oapi websocket 长连接送达（家里电脑主动连云，
  免公网暴露，与 ntfy 同等安全模型）；
- 文本消息 → memory/ 笔记（``source: lark``；正文含 URL 时由 links
  分发下一轮自动捡起，与 Obsidian 贴链接同路）；``搜 xxx``/``搜索 xxx``
  是搜索指令：查库回前 5 条结果卡（带「打开」按钮），不捕获为笔记；
- 图片/文件/语音消息 → 下载存入 attachments/ 平台子目录（图片/语音进
  ``媒体/``，PDF 进 ``书籍/``；media 分发自动捡起 OCR/转写；语音存
  .ogg 走 Whisper，与截图同路）；
- 捕获成功给原消息加 ✅ 表情回执（不占气泡的轻确认；回执失败只
  log，绝不影响捕获）；捕获失败才发文字反馈；
- 幂等：message_id 登记 ``<state_dir>/feishu_messages.json``；
- 单租户加固：首个互动者（或 ``FEISHU_USER_ID``）即主人，已识别
  主人后，其他人的消息与按钮点击一律忽略（先到先得，不换绑）。

发送（系统 → 飞书）：
- 推送规则：只在"用户不知道的事"发生时提醒（链接/OCR
  笔记完成待确认、抓取失败、今日摘要），常规成功不推
  （ntfy 通道 2026-09-09 起配置层停用，全部推送走飞书）；
- 发交互卡片（标题 + 正文 + 「在 Obsidian 中打开」URI 按钮——
  纯客户端跳转，无回调、零写入；带 ``confirm_note`` 时追加
  「✅ 确认」与「📁 归档…」两个 callback 按钮，点击回调
  ``card.action.trigger``，value 为 dict：{"action": confirm_note |
  archive_pick, "note": <文件名>}）；归档是两步：先弹目录选择卡
  （机器推导只作推荐），点定目录才移动（archive_note 带 dir）；
- ``pin=True`` 时把卡片置顶到会话顶部（晨报盘面第一眼可见），
  置顶前先摘下 ``pin_state`` 登记表里的上一条（每日替换不堆积）；
- 卡片失败降级纯文本。

确认/归档回调（用户点卡片按钮；系统内唯二机器改写笔记文件的路径）：
- 经用户 2026-09-07 批准的人工触发例外（两项；归档选目录交互
  2026-09-09 批准）：
  1. 单标签删除——仅删除该笔记 frontmatter ``tags`` 里的「待确认」
     一项，其他字段与正文一概不动；
  2. 按钮触发归档移动——「📁 归档…」先弹目录选择卡（机器推导仅作
     推荐项），人点定目录后把笔记文件移进该目录（推导规则见
     scripts/dispatch/archive.py；目录经合法性校验，机器专用目录
     不可选），随后执行第 1 项的删标签；sidecar 条目按 id 即时迁移
     （不等 watcher 班次）；目标目录已有同名文件绝不覆盖，报冲突
     提示；「取消」还原确认卡。
- 回调只带纯文件名（含目录分量视为非法，绝不写文件）；笔记可能已被
  手动归档进子目录（如 抖音/），按文件名在整个归档树查找（排除
  trash/ 等特殊目录），0 个报不存在、多个报歧义（同名冲突请到
  Obsidian 处理）；
- 幂等：已在目标目录只删标签，无「待确认」标签不改写；移动成功但
  删标签失败只 log + toast 提示手动摘除，绝不回滚；任何异常只记
  日志 + toast，不中断守护。

凭证全部走环境变量（``~/.config/atelierr/env`` 注入，绝不入库）：
- ``FEISHU_APP_ID`` / ``FEISHU_APP_SECRET``（自建应用凭证，收发都要）；
- ``FEISHU_CHAT_ID``（推送目标会话：你与机器人的单聊 chat_id）；
- ``FEISHU_CONSOLE_URL``（卡片按钮跳转地址，缺省 ``obsidian://``）。

触发：常驻守护（systemd ``atelierr-feishu.service``，Restart=always）
或人工 ``dispatch_cli feishu``。

模块拆分（2026-09-10）：收发基元与协议常量在 ``feishu_io.py``，卡片
组装器在 ``feishu_cards.py``；本文件保留桥（接收+回调+菜单），并对旧
导入路径全量 re-export（``from scripts.dispatch.feishu import ...``
的既有调用方与测试打点一律不受影响）。
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import frontmatter

from scripts.dispatch.prompt import CLOSE_WORDS, PromptStore
from scripts.utils.date_utils import local_timezone
from scripts.utils.state_store import read_json, write_json

from scripts.dispatch.archive import derive_archive_dir
from scripts.dispatch.feishu_cards import (
    confirmed_with_remark_card,
    pending_digest_card,
    resurface_card,
    prompt_form_card,
    send_resurface_feishu,
    send_todo_feishu,
)
from scripts.dispatch.feishu_io import (
    ARCHIVE_ACTION,
    ARCHIVE_CANCEL_ACTION,
    ARCHIVE_PICK_ACTION,
    CONFIRM_ACTION,
    CONFIRM_TAG,
    DEFAULT_CONSOLE_URL,
    DEFAULT_VAULT_NAME,
    DISCARD_ACTION,
    ENV_APP_ID,
    ENV_APP_SECRET,
    ENV_CHAT_ID,
    ENV_CONSOLE_URL,
    ENV_NOTE_PREFIX,
    ENV_VAULT_NAME,
    NOTE_REMARK_ACTION,
    RESURFACE_FEEDBACK_ACTION,
    PROMPT_FORM_MAX_QUESTIONS,
    PROMPT_SUBMIT_ACTION,
    TODO_DONE_ACTION,
    TODO_TAG,
    _confirm_action_card,
    _console_url,
    _import_lark,
    _pin_card,
    _send,
    send_feishu,
    send_feishu_card,
)
from scripts.dispatch.media import BOOK_SUBDIR, MEDIA_SUBDIR
from scripts.memory.core import NOTE_EXCLUDED_DIRS, SYSTEM_DIRNAME, MemoryTree

#: re-export 门脸（__all__ 声明即"有意再导出"，ruff F401 不误报）：
#: 既有调用方与测试打点（from scripts.dispatch.feishu import ...）不变。
__all__ = [
    "FeishuBridge",
    "ARCHIVE_ACTION",
    "ARCHIVE_CANCEL_ACTION",
    "ARCHIVE_PICK_ACTION",
    "CONFIRM_ACTION",
    "CONFIRM_TAG",
    "DEFAULT_CONSOLE_URL",
    "DEFAULT_VAULT_NAME",
    "ENV_APP_ID",
    "ENV_APP_SECRET",
    "ENV_CHAT_ID",
    "ENV_CONSOLE_URL",
    "ENV_NOTE_PREFIX",
    "ENV_VAULT_NAME",
    "DISCARD_ACTION",
    "MENU_COMMANDS",
    "NOTE_REMARK_ACTION",
    "PROMPT_FORM_MAX_QUESTIONS",
    "PROMPT_SUBMIT_ACTION",
    "SEARCH_LIMIT",
    "SEARCH_PREFIXES",
    "TODO_DONE_ACTION",
    "TODO_TAG",
    "_confirm_action_card",
    "_console_url",
    "_import_lark",
    "_pin_card",
    "_send",
    "prompt_form_card",
    "send_feishu",
    "send_feishu_card",
    "send_resurface_feishu",
    "send_todo_feishu",
]

#: 平台推不出时归档按钮的兜底一级目录（与建议归档行的"省略"不同：
#: 按钮必须给一个去处）
FALLBACK_ARCHIVE_DIR = "媒体"

#: 已处理 message_id 登记表上限（超出裁掉最旧的，防无限膨胀）
_SEEN_CAP = 2000

#: 搜索指令前缀（发「搜 xxx」/「搜索 xxx」直接查库回卡，不捕获为笔记）
SEARCH_PREFIXES = ("搜索 ", "搜 ")

#: 搜索结果卡条数上限（卡片长度与打开按钮个数权衡）
SEARCH_LIMIT = 5

#: 快捷菜单指令（机器人聊天菜单在飞书开放平台后台配置同款文本，
#: 见 docs/FEISHU-BOT.md；直接手打这些词同样生效）
MENU_COMMANDS = ("摘要", "今日摘要", "待办", "提炼候选", "周回顾", "同步看板", "菜单", "帮助")

#: 文件名非法字符（半角）转 -
_ILLEGAL_RE = re.compile(r'[\\/:*?"<>|]')


class FeishuBridge:
    """飞书 ↔ Atelierr 双向桥。

    Attributes:
        tree: MemoryTree 实例（借它定位 memory/ 与 attachments/）。
        app_id / app_secret: 自建应用凭证。
        state_path: 已处理消息登记表（feishu_messages.json）。
    """

    def __init__(
        self,
        tree: MemoryTree,
        app_id: str,
        app_secret: str,
        state_path: Optional[Path] = None,
    ) -> None:
        """初始化。

        Args:
            tree: MemoryTree 实例。
            app_id: 飞书自建应用 app_id。
            app_secret: 飞书自建应用 app_secret。
            state_path: 登记表路径（缺省 ``<state_dir>/feishu_messages.json``）。
        """
        self.tree = tree
        self.app_id = app_id
        self.app_secret = app_secret
        self.state_path = state_path or (
            Path(tree.state_dir) / "feishu_messages.json"
        )

    @classmethod
    def from_env(cls, tree: MemoryTree) -> "FeishuBridge":
        """按环境变量构造；凭证缺失抛 RuntimeError（给 CLI 翻译成提示）。"""
        app_id = os.environ.get(ENV_APP_ID, "").strip()
        app_secret = os.environ.get(ENV_APP_SECRET, "").strip()
        if not app_id or not app_secret:
            raise RuntimeError(
                f"缺少飞书凭证：请在 ~/.config/atelierr/env 配置 "
                f"{ENV_APP_ID} / {ENV_APP_SECRET}"
            )
        return cls(tree, app_id, app_secret)

    # ---- 接收：长连接守护 ------------------------------------------------

    def run_forever(self) -> None:
        """启动 websocket 长连接监听（阻塞；断线由 SDK 自动重连）。

        事件与卡片回调（card.action.trigger）注册在同一个
        EventDispatcherHandler 上；lark-oapi 1.7.3 对回调类事件
        （p2.*）经 ``_do_without_validation`` 走 callback processor map。
        """
        lark = _import_lark()
        handler = (
            lark.EventDispatcherHandler.builder("", "")
            .register_p2_im_message_receive_v1(self.handle_event)
            .register_p2_im_message_message_read_v1(self.ignore_read_receipt)
            .register_p2_im_message_reaction_created_v1(self.ignore_read_receipt)
            .register_p2_im_message_reaction_deleted_v1(self.ignore_read_receipt)
            .register_p2_card_action_trigger(self.handle_card_action)
            .build()
        )
        client = lark.ws.Client(
            self.app_id,
            self.app_secret,
            event_handler=handler,
            log_level=lark.LogLevel.WARNING,
        )
        client.start()

    @staticmethod
    def ignore_read_receipt(data: Any) -> None:
        """已读回执/表情回执事件（im.message.message_read_v1、
        im.message.reaction_*_v1）：订阅推送会送达（含系统给自己消息
        加 ✅ 触发的回执事件），但系统无需响应——空处理器接住，避免
        SDK 刷 ``processor not found`` 噪音日志。"""
        return

    def handle_event(self, data: Any) -> None:
        """处理一条消息事件；任何解析失败都只跳过，绝不中断守护。"""
        try:
            message = data.event.message
            message_id = str(message.message_id)
            msg_type = str(message.message_type)
            content = json.loads(message.content or "{}")
        except (AttributeError, json.JSONDecodeError, TypeError):
            return
        # 顺带识别用户 open_id（任务/日历等 API 需要；零额外权限）；
        # 已识别主人后，其他人的消息一律忽略（单租户个人机器人加固）
        from scripts.dispatch.task_sync import (
            load_user_open_id,
            record_user_open_id,
            sender_open_id,
        )

        open_id = sender_open_id(getattr(data.event, "sender", None))
        if self._seen(message_id):
            return
        known = load_user_open_id(self.tree.state_dir)
        if known and open_id and open_id != known:
            print(f"[feishu] ignore foreign sender {open_id}", flush=True)
            self._mark_seen(message_id)
            return
        if open_id:
            record_user_open_id(self.tree.state_dir, open_id)
        # 日志带 chat_id：往机器人发一条消息即可从 feishu.log 读到推送目标
        print(
            f"[feishu] {msg_type} chat={getattr(message, 'chat_id', '?')} "
            f"msg={message_id}",
            flush=True,
        )
        try:
            if msg_type == "text":
                self._receive_text(
                    message_id,
                    str(content.get("text") or ""),
                    chat_id=str(getattr(message, "chat_id", "") or "") or None,
                )
            elif msg_type in ("image", "file", "audio", "media"):
                self._receive_resource(
                    message_id,
                    msg_type,
                    content,
                    chat_id=str(getattr(message, "chat_id", "") or "") or None,
                )
            elif msg_type == "post":
                self._receive_post(
                    message_id,
                    content,
                    chat_id=str(getattr(message, "chat_id", "") or "") or None,
                )
        finally:
            self._mark_seen(message_id)

    def handle_card_action(self, data: Any) -> Dict[str, Any]:
        """处理卡片按钮回调（确认 / 确认并归档）；任何异常只 toast，不中断。

        回调负载结构（lark-oapi P2CardActionTrigger）：
        ``data.event.action.value`` = {"action": "confirm_note" |
        "archive_note", "note": "<文件名>"}，``data.event.context`` 的
        ``open_chat_id`` 是卡片所在会话。两个动作都经用户 2026-09-07
        批准的人工触发例外（见模块 docstring）。未知动作原样忽略。

        处理完后额外向会话主动发一条纯文字反馈（ws 长连接下回调响应
        会被平台吞掉，toast/卡片更新不可见；发送失败只 log，绝不影响
        回调返回值与守护）。

        Args:
            data: 卡片回调事件对象（SDK 模型或鸭子类型）。

        Returns:
            Dict[str, Any]: 回调响应（toast + 可选 card 更新 JSON）；
            未知动作返回空表（卡片不变）。
        """
        try:
            action = data.event.action
            value = dict(getattr(action, "value", None) or {})
        except AttributeError:
            return {"toast": {"type": "error", "content": "回调解析失败"}}
        action_name = str(value.get("action") or "")
        filename = str(value.get("note") or "").strip()
        # 清单卡批次（pending_digest_card 注入）：点掉一条后用剩余条目
        # 重建清单卡——平台回调的卡片更新是整卡替换，不重建其余条目
        # 会从视图上"消失"（2026-09-13 真机实测；笔记无损）
        batch_raw = value.get("batch")
        batch = [str(item) for item in batch_raw] if isinstance(batch_raw, list) else None
        chat_id = self._event_chat_id(data)
        # 顺带识别用户 open_id（回调 operator 带身份，零额外权限）；
        # 已识别主人后，其他人的按钮点击一律忽略（单租户加固）
        from scripts.dispatch.task_sync import (
            load_user_open_id,
            record_user_open_id,
            sender_open_id,
        )

        open_id = sender_open_id(getattr(data.event, "operator", None))
        known = load_user_open_id(self.tree.state_dir)
        if known and open_id and open_id != known:
            print(
                f"[feishu] ignore action from foreign operator {open_id}",
                flush=True,
            )
            return {}
        if open_id:
            record_user_open_id(self.tree.state_dir, open_id)
        if action_name == CONFIRM_ACTION:
            return self._handle_confirm(filename, chat_id, batch)
        if action_name == ARCHIVE_PICK_ACTION:
            return self._handle_archive_pick(filename, chat_id)
        if action_name == ARCHIVE_CANCEL_ACTION:
            return self._handle_archive_cancel(filename, chat_id)
        if action_name == ARCHIVE_ACTION:
            target_dir = str(value.get("dir") or "").strip() or None
            return self._handle_archive(filename, chat_id, target_dir, batch)
        if action_name == TODO_DONE_ACTION:
            return self._handle_todo_done(filename, chat_id, batch)
        if action_name == PROMPT_SUBMIT_ACTION:
            return self._handle_prompt_submit(action, chat_id)
        if action_name == DISCARD_ACTION:
            return self._handle_discard(filename, chat_id, batch)
        if action_name == NOTE_REMARK_ACTION:
            return self._handle_note_remark(action, filename, chat_id)
        if action_name == RESURFACE_FEEDBACK_ACTION:
            outcome = str(value.get("outcome") or "")
            return self._handle_resurface_feedback(filename, outcome, chat_id, batch)
        return {}

    @staticmethod
    def _event_chat_id(data: Any) -> Optional[str]:
        """从回调事件 context 取会话 id（SDK CallBackContext.open_chat_id）。

        兼容 dict 与鸭子对象（测试/旧版负载）；取不到返回 None
        （调用方回退 FEISHU_CHAT_ID 环境变量）。
        """
        try:
            context = getattr(data.event, "context", None)
        except AttributeError:
            return None
        if context is None:
            return None
        if isinstance(context, dict):
            value = context.get("open_chat_id") or context.get("chat_id")
            return str(value) if value else None
        for attr in ("open_chat_id", "chat_id"):
            try:
                value = getattr(context, attr)
            except AttributeError:
                continue
            if value:
                return str(value)
        return None

    def _handle_confirm(
        self,
        filename: str,
        chat_id: Optional[str] = None,
        batch: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """「✅ 确认」：只删待确认标签；失败只 toast，不中断守护。"""
        try:
            ok, detail = self._confirm_note(filename)
        except Exception as exc:  # noqa: BLE001 - 回调失败只 toast，不中断守护
            print(f"[feishu] confirm note={filename} fail: {exc}", flush=True)
            self._send_feedback(chat_id, f"⚠️ 处理失败，请稍后重试：{filename}")
            return {"toast": {"type": "error", "content": "处理失败，请稍后重试"}}
        print(f"[feishu] confirm note={filename} {'ok' if ok else 'fail'}", flush=True)
        if not ok:
            return self._fail_response(chat_id, filename, detail)
        title = self._feedback_title(filename)
        self._send_feedback(chat_id, f"✅ 已确认：{title}")
        self._maybe_nominate_judgments(filename, chat_id)
        return {
            "toast": {"type": "success", "content": "已确认"},
            "card": {
                "type": "raw",
                "data": self._completion_card(
                    filename, "已移除「待确认」标签", "✅ 已确认", batch, chat_id
                ),
            },
        }

    def _completion_card(
        self,
        filename: str,
        note_line: str,
        header: str,
        batch: Optional[List[str]],
        chat_id: Optional[str] = None,
        offer_remark: bool = True,
    ) -> Dict[str, Any]:
        """操作完成卡：清单卡批次场景（batch 非空且还有剩余）重建剩余条目
        的清单卡——平台回调的卡片更新是整卡替换，不重建会让其余条目从
        视图上消失（2026-09-13 真机实测）。

        最终完成时给 legacy 完成卡（回调更新只敢用 legacy——schema 2.0
        卡作为回调返回值平台报错，2026-09-13 真机实测）；「顺手记一句」
        表单卡**另发一条新消息**（schema 2.0 走新消息发送是已验证路径，
        与周回顾四问同路）。丢弃（🗑）场景不邀功（offer_remark=False）。
        """
        if batch:
            remaining = [item for item in batch if item != filename]
            if remaining:
                return pending_digest_card(remaining)
        if offer_remark:
            # 另发新消息（失败只 log，绝不影响完成卡更新）
            self._send_card(
                chat_id, confirmed_with_remark_card(filename, note_line, header)
            )
        return self._confirmed_card(filename, note_line=note_line, header=header)

    def _handle_archive_pick(self, filename: str, chat_id: Optional[str] = None) -> Dict[str, Any]:
        """「📁 归档…」：弹目录选择卡（不移动文件；点定目录才移）。

        候选 = 机器推导（标「推荐」）+ memory/ 现有一级目录（排除
        wiki/系统/attachments 等机器目录），每目录一个按钮 +
        「取消」还原确认卡。笔记不存在只 toast，不出选择卡。
        """
        note_path, err = self._locate_note(filename)
        if err:
            return self._fail_response(chat_id, filename, err)
        derived = None
        try:
            post = frontmatter.loads(note_path.read_text(encoding="utf-8"))
            platform, category = derive_archive_dir(post)
            platform = platform or FALLBACK_ARCHIVE_DIR
            derived = platform if not category else f"{platform}/{category}"
        except Exception:  # noqa: BLE001 - 推导失败只少一个推荐项
            print(f"[feishu] archive pick derive fail: {filename}", flush=True)
        try:
            top_dirs = sorted(
                path.name
                for path in Path(self.tree.notes_dir).iterdir()
                if path.is_dir()
                and not path.name.startswith(".")
                and path.name not in NOTE_EXCLUDED_DIRS
            )
        except OSError:
            top_dirs = []
        options: List[Tuple[str, str]] = []
        if derived:
            options.append((derived, f"{derived}（推荐）"))
        for name in top_dirs:
            if name != derived and len(options) < 7:
                options.append((name, name))
        buttons = [
            {
                "tag": "button",
                "text": {"tag": "plain_text", "content": label},
                "type": "primary" if i == 0 else "default",
                "behaviors": [
                    {
                        "type": "callback",
                        "value": {
                            "action": ARCHIVE_ACTION,
                            "note": filename,
                            "dir": target,
                        },
                    }
                ],
            }
            for i, (target, label) in enumerate(options)
        ]
        buttons.append(
            {
                "tag": "button",
                "text": {"tag": "plain_text", "content": "取消"},
                "type": "default",
                "behaviors": [
                    {
                        "type": "callback",
                        "value": {"action": ARCHIVE_CANCEL_ACTION, "note": filename},
                    }
                ],
            }
        )
        rows = [
            {"tag": "action", "actions": buttons[i : i + 4]}
            for i in range(0, len(buttons), 4)
        ]
        card = {
            "config": {"wide_screen_mode": True},
            "header": {
                "title": {"tag": "plain_text", "content": "📁 选择归档目录"},
                "template": "blue",
            },
            "elements": [
                {
                    "tag": "div",
                    "text": {"tag": "plain_text", "content": filename},
                },
                *rows,
            ],
        }
        return {
            "toast": {"type": "info", "content": "选择归档目录"},
            "card": {"type": "raw", "data": card},
        }

    def _handle_archive_cancel(self, filename: str, chat_id: Optional[str] = None) -> Dict[str, Any]:
        """「取消」：还原原始确认卡（不移动、不删标签）。"""
        card = _confirm_action_card("Atelierr 笔记待确认", filename, filename)
        return {
            "toast": {"type": "info", "content": "已取消归档"},
            "card": {"type": "raw", "data": card},
        }

    def _handle_archive(self, filename: str, chat_id: Optional[str] = None,
                        target_dir: Optional[str] = None,
                        batch: Optional[List[str]] = None) -> Dict[str, Any]:
        """「📁 确认并归档」：归档移动 + 删待确认标签；失败只 toast。"""
        try:
            ok, detail = self._archive_note(filename, target_dir)
        except Exception as exc:  # noqa: BLE001 - 回调失败只 toast，不中断守护
            print(f"[feishu] archive note={filename} fail: {exc}", flush=True)
            self._send_feedback(chat_id, f"⚠️ 处理失败，请稍后重试：{filename}")
            return {"toast": {"type": "error", "content": "处理失败，请稍后重试"}}
        print(f"[feishu] archive note={filename} {'ok' if ok else 'fail'}", flush=True)
        if not ok:
            return self._fail_response(chat_id, filename, detail)
        if detail == "confirm_only":
            # 推导不出归档目录：只确认不移动（留在收件箱由人日后归类）
            title = self._feedback_title(filename)
            self._send_feedback(
                chat_id, f"✅ 已确认（推导不出归档目录，留在收件箱）：{title}"
            )
            return {
                "toast": {"type": "success", "content": "已确认（留在收件箱）"},
                "card": {
                    "type": "raw",
                    "data": self._completion_card(
                        filename,
                        "已移除「待确认」标签；推导不出归档目录，留在收件箱",
                        "✅ 已确认",
                        batch,
                        chat_id,
                    ),
                },
            }
        if detail == "tag_fail":
            # 移动成功但删标签失败：不回滚，卡片提示手动摘除
            title = self._feedback_title(filename)
            self._send_feedback(chat_id, f"⚠️ 已归档，标签请到 Obsidian 手动摘除：{title}")
            return {
                "toast": {
                    "type": "warning",
                    "content": "已归档，标签请到 Obsidian 手动摘除",
                },
                "card": {
                    "type": "raw",
                    "data": self._completion_card(
                        filename,
                        "已归档；「待确认」标签请手动摘除",
                        "✅ 已确认",
                        batch,
                        chat_id,
                    ),
                },
            }
        title = self._feedback_title(filename)
        self._send_feedback(chat_id, f"📁 已确认并归档到 {detail}/：{title}")
        self._maybe_nominate_judgments(filename, chat_id)
        card = {
            "type": "raw",
            "data": self._completion_card(
                filename, f"已归档到 {detail}/ 并移除「待确认」标签",
                "✅ 已确认", batch, chat_id
            ),
        }
        return {
            "toast": {"type": "success", "content": f"已确认并归档到 {detail}/"},
            "card": card,
        }

    def _handle_todo_done(
        self,
        filename: str,
        chat_id: Optional[str] = None,
        batch: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """「✅ 已完成」待办：删待办标签 + 收进 待办/；失败只 toast，不中断守护。

        批量卡场景（batch 非空且有剩余）：用剩余条目重建批量卡——平台
        回调的卡片更新是整卡替换，不重建其余条目会从视图上"消失"
        （与清单卡/复习卡同规）。
        """
        try:
            ok, detail = self._todo_done(filename)
        except Exception as exc:  # noqa: BLE001 - 回调失败只 toast，不中断守护
            print(f"[feishu] todo done note={filename} fail: {exc}", flush=True)
            self._send_feedback(chat_id, f"⚠️ 处理失败，请稍后重试：{filename}")
            return {"toast": {"type": "error", "content": "处理失败，请稍后重试"}}
        print(f"[feishu] todo done note={filename} {'ok' if ok else 'fail'}", flush=True)
        if not ok:
            return self._fail_response(chat_id, filename, detail)
        # 回写飞书任务完成（单向同步；失败只 log，绝不影响标签操作）
        try:
            from scripts.dispatch.task_sync import complete_task_for_todo

            complete_task_for_todo(self.tree.state_dir, filename)
        except Exception as exc:  # noqa: BLE001 - 回写失败不影响回调
            print(f"[feishu] task complete hook fail: {exc}", flush=True)
        title = self._feedback_title(filename)
        moved = detail == "ok_moved"
        done_line = "已移除「待办」标签，收进 待办/ 目录" if moved else "已移除「待办」标签"
        self._send_feedback(
            chat_id, f"✅ 待办已完成{'并收进 待办/' if moved else ''}：{title}"
        )
        if batch:
            # 批量卡：重建剩余条目（标题按名定位重读，失败的退回文件名）
            remaining = [item for item in batch if item != filename]
            if remaining:
                from scripts.dispatch.feishu_cards import todo_batch_card

                items = [
                    {"filename": name, "title": self._feedback_title(name)}
                    for name in remaining
                ]
                return {
                    "toast": {"type": "success", "content": "已完成"},
                    "card": {"type": "raw", "data": todo_batch_card(items)},
                }
        return {
            "toast": {"type": "success", "content": "已完成"},
            "card": {
                "type": "raw",
                "data": self._confirmed_card(
                    filename,
                    note_line=done_line,
                    header="✅ 已完成",
                ),
            },
        }

    def _todo_done(self, filename: str) -> Tuple[bool, str]:
        """「✅ 已完成」核心：定位笔记 + 移除待办标签 + 收进 待办/ 目录。

        2026-09-14 审计裁决：此前只摘标签、文件永远滞留 inbox（洗完的
        衣服不叠进衣柜）——点 ✅ 即把 inbox 里的待办归档进
        ``memory/待办/``（与确认归档同属人工点动例外；sidecar 即时迁移
        同 _archive_note）。用户已手动挪走的（不在 inbox）尊重现状只摘
        标签；目标重名/移动失败不回滚（摘标签为主），log 留痕。
        """
        note_path, err = self._locate_note(filename)
        if err:
            return False, err
        stripped = self._strip_tag(note_path, TODO_TAG)
        if not self.tree._rel_key(note_path).startswith("inbox/"):
            return True, "ok" if stripped else "noop"
        target = Path(self.tree.notes_dir) / TODO_TAG / note_path.name
        if target.exists():
            print(f"[feishu] todo done move clash, kept in place: {target}", flush=True)
            return True, "ok"
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            note_path.rename(target)
        except OSError as exc:
            print(f"[feishu] todo done move fail (tag stripped): {exc}", flush=True)
            return True, "ok"
        note_id = self.tree._read_note_id(target)
        if note_id is not None:
            self.tree.relocate_entry(note_id, self.tree._rel_key(target))
        return True, "ok_moved"

    def _handle_prompt_submit(self, action: Any, chat_id: Optional[str]) -> Dict[str, Any]:
        """问答表单卡「提交回答」：form_value 按问题序收进会话并关闭。

        表单答案在回调 ``action.form_value``（dict，键 ``q1..qN``，序 =
        会话 questions 序；兼容 JSON 字符串负载）。空项视为跳过该问；
        全部为空则不动会话（用户可继续文字作答或回「跳过」）；收到至少
        一条即追加并**关闭会话**（表单是一次性作答仪式；prompt-collect
        对已关闭会话照常可读）。
        """
        form_value = getattr(action, "form_value", None)
        if isinstance(form_value, str):
            try:
                form_value = json.loads(form_value)
            except ValueError:
                form_value = None
        if not isinstance(form_value, dict):
            form_value = {}
        store = PromptStore(Path(self.tree.state_dir))
        data = store.load() if store.is_open() else None
        if not data:
            self._send_feedback(chat_id, "当前没有进行中的问答会话")
            return {"toast": {"type": "warning", "content": "没有进行中的问答"}}
        questions = [str(q) for q in (data.get("questions") or [])]
        answers: List[str] = []
        for index, _question in enumerate(questions):
            value = str(form_value.get(f"q{index + 1}") or "").strip()
            if value:
                answers.append(value)
        if not answers:
            self._send_feedback(chat_id, "表单是空的，问答仍在进行（回「跳过」结束）")
            return {"toast": {"type": "info", "content": "未收到内容，问答仍在进行"}}
        for text in answers:
            store.append(text)
        closed = store.close()
        print(f"[feishu] prompt form submit: {len(answers)} answers", flush=True)
        # 回顾仪式（review-* kind）：答案机械落盘 reflections/（方案 A）；
        # 钩子绝不弄砸回调本身（2026-09-13：用户看到报错但后端没日志，
        # 从此钩子成败都打日志）
        if closed and str(closed.get("kind") or "").startswith("review"):
            try:
                from scripts.dispatch import review_ritual

                written = review_ritual.write_answers(self.tree, closed)
                print(f"[feishu] review dump -> {written}", flush=True)
                if written is not None:
                    self._send_feedback(
                        chat_id, f"答案已存进 {written.name}（下次会话综合成文）"
                    )
            except Exception as exc:  # noqa: BLE001 - 钩子是附加动作
                print(f"[feishu] review dump fail: {exc}", flush=True)
        self._send_feedback(chat_id, f"已收到全部 {len(answers)} 条回答，问答结束 ✅")
        return {
            "toast": {"type": "success", "content": f"已提交 {len(answers)} 条回答"},
            "card": {
                "type": "raw",
                "data": self._confirmed_card(
                    "问答表单",
                    note_line=f"已收到 {len(answers)} 条回答，会话已结束",
                    header="✅ 问答已提交",
                ),
            },
        }

    def _handle_discard(
        self,
        filename: str,
        chat_id: Optional[str] = None,
        batch: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """「🗑 不要了」：只标 pending_delete（不动文件），删除仍走
        review → purge → trash/ 人工链路（2026-09-13 环节三评审毛病 1：
        垃圾卡有即时出口，丢弃有缓冲，误点可捞回）。"""
        try:
            note_path, err = self._locate_note(filename)
            if err:
                return self._fail_response(chat_id, filename, err)
            entry = self.tree._entry(note_path)
            if entry is None:
                self._send_feedback(chat_id, f"⚠️ 笔记未登记：{filename}")
                return {"toast": {"type": "error", "content": "笔记未登记"}}
            if entry.get("pending_delete"):
                self._send_feedback(chat_id, f"已在待删清单里：{filename}")
                return {"toast": {"type": "info", "content": "已在待删清单"}}
            # 多进程安全的公共 API（flock 事务；直改条目+缓存回写会丢更新）
            self.tree.set_pending_delete(note_path)
        except Exception as exc:  # noqa: BLE001 - 回调失败只 toast，不中断守护
            print(f"[feishu] discard note={filename} fail: {exc}", flush=True)
            self._send_feedback(chat_id, f"⚠️ 处理失败，请稍后重试：{filename}")
            return {"toast": {"type": "error", "content": "处理失败，请稍后重试"}}
        print(f"[feishu] discard note={filename} ok", flush=True)
        self._send_feedback(
            chat_id,
            f"🗑 已标记待删：{filename}\n不会自动删：review → 你点头 → 回收站"
            "（反悔随时到 Obsidian 摘除标记，或 review 时跳过）",
        )
        return {
            "toast": {"type": "success", "content": "已标记待删"},
            "card": {
                "type": "raw",
                "data": self._completion_card(
                    filename,
                    "不会自动删：review → 你点头 → 回收站（可恢复）",
                    "🗑 已标记待删",
                    batch,
                    chat_id,
                    offer_remark=False,
                ),
            },
        }

    def _handle_note_remark(
        self, action: Any, filename: str, chat_id: Optional[str]
    ) -> Dict[str, Any]:
        """确认完成卡「💾 记下」：把顺手写的一句追加进笔记末尾。

        第四个人工例外（2026-09-13 环节三评审毛病 2，用户批准）：用户
        主动提交的一句话可以追加进笔记（原子写；不回拨 mtime——人碰过
        的东西衰减时钟就该重置，与删标签同规矩）。空提交零成本：不动
        文件、只 toast。
        """
        form_value = getattr(action, "form_value", None)
        if isinstance(form_value, str):
            try:
                form_value = json.loads(form_value)
            except ValueError:
                form_value = None
        remark = str((form_value or {}).get("q1") or "").strip()
        if not remark:
            return {"toast": {"type": "info", "content": "没填就不记，零成本"}}
        try:
            note_path, err = self._locate_note(filename)
            if err:
                self._send_feedback(chat_id, f"⚠️ {err}：{filename}")
                return {"toast": {"type": "error", "content": err}}
            text = note_path.read_text(encoding="utf-8")
            if f"）：{remark}" in text:
                # 幂等：同一句话已记过（客户端报错后用户重试/平台重发
                # 回调都会再进这里——2026-09-14 实证客户端报错但后端
                # 实际成功），不再追加第二遍
                self._send_feedback(chat_id, f"💭 这句已记过，不重复追加：{filename}")
                return {"toast": {"type": "info", "content": "这句已记过"}}
            stamp = datetime.now().strftime("%Y-%m-%d %H:%M")
            addition = f"> 💭 顺手记一句（{stamp}）：{remark}\n"
            self._atomic_write(
                note_path, (text.rstrip("\n") + "\n\n" + addition).encode("utf-8")
            )
        except Exception as exc:  # noqa: BLE001 - 回调失败只 toast，不中断守护
            print(f"[feishu] remark note={filename} fail: {exc}", flush=True)
            self._send_feedback(chat_id, f"⚠️ 记入失败，请稍后重试：{filename}")
            return {"toast": {"type": "error", "content": "记入失败，请稍后重试"}}
        print(f"[feishu] remark note={filename} ok", flush=True)
        self._send_feedback(chat_id, f"💭 已记进笔记末尾：{filename}")
        return {
            "toast": {"type": "success", "content": "已记入"},
            "card": {
                "type": "raw",
                "data": self._confirmed_card(
                    filename,
                    note_line="已把一句记到笔记末尾",
                    header="✅ 已确认",
                ),
            },
        }

    def _handle_resurface_feedback(
        self,
        filename: str,
        outcome: str,
        chat_id: Optional[str] = None,
        batch: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """复习卡「想起来了/没想起来」：记每篇的独立复习间隔
        （想起来 ×2、没想起来 ÷2；简化 SM-2，只写 resurface.json，
        不进 confidence 公式）；想起来了顺带记一次访问（合法重置
        闲置时钟）。批次场景重建剩余复习卡（整卡替换语义）。"""
        from scripts.memory.resurface import ResurfaceManager

        try:
            note_path = self.tree._abs(filename)
            note_id = self.tree._find_entry_id(note_path) or Path(filename).stem
            manager = ResurfaceManager(self.tree)
            state = manager.record_outcome(note_id, remembered=(outcome == "good"))
            if outcome == "good" and note_path.exists():
                self.tree.on_note_accessed(note_path)
        except Exception as exc:  # noqa: BLE001 - 回调失败只 toast，不中断守护
            print(f"[feishu] resurface feedback note={filename} fail: {exc}", flush=True)
            self._send_feedback(chat_id, f"⚠️ 处理失败，请稍后重试：{filename}")
            return {"toast": {"type": "error", "content": "处理失败，请稍后重试"}}
        good = outcome == "good"
        print(
            f"[feishu] resurface feedback note={filename} outcome={outcome} "
            f"interval={state['interval']}",
            flush=True,
        )
        if good:
            msg = f"✅ 好，它{state['interval']:.0f} 天后再来见你"
        else:
            msg = "❌ 收到，近期再来看一眼；值得就提炼进压缩层，不值得留给 decay"
        self._send_feedback(chat_id, f"{msg}：{filename}")
        if batch:
            remaining = [item for item in batch if item != filename]
            if remaining:
                items = [
                    {"relpath": rel, "title": Path(rel).stem, "idle_days": "?"}
                    for rel in remaining
                ]
                return {
                    "toast": {"type": "success", "content": msg},
                    "card": {"type": "raw", "data": resurface_card(items)},
                }
        return {
            "toast": {"type": "success", "content": msg},
            "card": {
                "type": "raw",
                "data": self._confirmed_card(
                    filename, note_line=msg, header="🔁 复习反馈已记录"
                ),
            },
        }


    @staticmethod
    def _valid_archive_dir(target_dir: str) -> bool:
        """归档目标目录校验：1-2 级纯相对路径，一级目录非机器专用目录。

        目录来自卡片回调（外部输入）：拒绝绝对路径、``..``、反斜杠、
        非法字符、三级及以上、wiki/系统/attachments/trash/templates
        （NOTE_EXCLUDED_DIRS 成员，归档进去等于藏进机器区）。
        """
        if not target_dir or "\\" in target_dir or target_dir.startswith("/"):
            return False
        parts = target_dir.split("/")
        # 非法字符按段校验：_ILLEGAL_RE 含 "/"（文件名消毒场景要禁），
        # 目录路径的段分隔符本身合法——整串校验会把所有二级目录误杀
        #（2026-09-17 实证：目录选择卡的「推荐」项是 平台/分类 二级路径，
        # 一点就报"非法目录"）
        if len(parts) > 2 or any(
            part in ("", ".", "..") or _ILLEGAL_RE.search(part) for part in parts
        ):
            return False
        return parts[0] not in NOTE_EXCLUDED_DIRS

    def _fail_response(
        self, chat_id: Optional[str], filename: str, detail: str
    ) -> Dict[str, Any]:
        """操作失败的统一应答（确认/归档/丢弃/选目录四处共用）。

        死卡——笔记已不在库里（已回收/已归档/已在 Obsidian 手移）——是
        正常终态不是错误：给 info 提示，不弹红色报错（2026-09-15 实测：
        复验重跑回收旧卡后，用户点旧卡一片"处理失败"报错）。真错误
        （重名/歧义/移动失败等）保持 error toast。
        """
        reason = self._error_reason(detail)
        if detail == "笔记不存在":
            self._send_feedback(chat_id, f"ℹ️ {reason}：{filename}")
            return {"toast": {"type": "info", "content": reason}}
        self._send_feedback(chat_id, f"⚠️ {reason}：{filename}")
        return {"toast": {"type": "error", "content": reason}}

    @staticmethod
    def _error_reason(detail: str) -> str:
        """把失败详情串映射成给用户看的原因短语（toast 与反馈消息共用）。"""
        if detail == "笔记不存在":
            return "卡片已失效（笔记已回收或归档），无需操作"
        if detail == "歧义":
            return "存在多篇同名笔记，请到 Obsidian 处理"
        if detail == "目标重名":
            return "目标文件夹已有同名笔记，请到 Obsidian 处理"
        if detail == "移动失败":
            return "处理失败，请稍后重试"
        if detail == "非法目录":
            return "归档目录非法"
        return "笔记不存在或路径非法"

    def _feedback_title(self, filename: str) -> str:
        """反馈文案的标题：frontmatter title 优先，取不到用文件名。

        成功路径上文件必然存在（可能在归档子目录），按名定位读取；
        任何读取失败都退回文件名，绝不让反馈文案组装抛异常。
        """
        path, _ = self._locate_note(filename)
        if path is None:
            return filename
        try:
            post = frontmatter.loads(path.read_text(encoding="utf-8"))
            title = post.metadata.get("title")
        except Exception:  # noqa: BLE001 - 标题取不到用文件名
            return filename
        return str(title).strip() if title else filename

    def _send_feedback(self, chat_id: Optional[str], text: str) -> None:
        """向卡片所在会话主动发一条纯文本反馈；失败只 log warning。

        ws 长连接下卡片回调响应（toast/卡片更新）平台会吞掉，用户点完
        按钮看不到结果——用与发卡片相同的 send API 主动补一条文字消息。
        目标会话：回调 context 的 open_chat_id 优先，缺省
        ``FEISHU_CHAT_ID`` 环境变量；都没有则静默跳过（未配置环境）。

        Args:
            chat_id: 回调事件 context 里的会话 id（可为 None）。
            text: 纯文本反馈内容。
        """
        target = (chat_id or os.environ.get(ENV_CHAT_ID, "")).strip()
        if not target:
            return
        try:
            lark = _import_lark()
            client = (
                lark.Client.builder()
                .app_id(self.app_id)
                .app_secret(self.app_secret)
                .build()
            )
            ok = _send(client, target, "text", json.dumps({"text": text}))
            if not ok:
                print(f"[feishu] feedback send fail: {text!r}", flush=True)
        except Exception as exc:  # noqa: BLE001 - 反馈失败不影响回调处理
            print(f"[feishu] feedback fail: {exc}", flush=True)

    def _send_card(self, chat_id: Optional[str], card: Dict[str, Any]) -> bool:
        """向会话发一张交互卡片（模块级 send_feishu_card 的实例凭据版）。"""
        return send_feishu_card(
            card, chat_id, app_id=self.app_id, app_secret=self.app_secret
        )

    def _answer_search(self, chat_id: Optional[str], query: str) -> None:
        """「搜 xxx」指令：回前 5 条匹配卡（标题+confidence+打开按钮）。

        全程只读；无结果/失败用文字反馈（不占用卡片通道）。
        """
        if not query:
            self._send_feedback(chat_id, "用法：发「搜 关键词」，我回前 5 条匹配")
            return
        from scripts.memory.search import MemorySearcher

        try:
            results = MemorySearcher(self.tree).search(query, limit=SEARCH_LIMIT)
        except Exception as exc:  # noqa: BLE001 - 搜索失败文字告知，不中断守护
            print(f"[feishu] search fail: {exc}", flush=True)
            self._send_feedback(chat_id, "⚠️ 搜索失败，请稍后重试")
            return
        print(f"[feishu] search q={query!r} hits={len(results)}", flush=True)
        if not results:
            self._send_feedback(chat_id, f"没有找到匹配「{query}」的笔记")
            return
        elements: List[Dict[str, Any]] = []
        for item in results:
            created = (
                item.created.strftime("%Y-%m-%d") if item.created else "日期未知"
            )
            elements.append(
                {
                    "tag": "div",
                    "text": {
                        "tag": "lark_md",
                        "content": (
                            f"**{item.title}**\n"
                            f"confidence {item.confidence:.2f} · {created}"
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
                            "url": _console_url(self.tree._rel_key(item.path)),
                        }
                    ],
                }
            )
        card = {
            "config": {"wide_screen_mode": True},
            "header": {
                "title": {"tag": "plain_text", "content": f"🔍 搜索：{query}"},
                "template": "blue",
            },
            "elements": elements,
        }
        self._send_card(chat_id, card)

    def _open_daily_review(self, chat_id: Optional[str]) -> None:
        """「复盘」指令：手动开启今日三问（并解除自动暂停）。

        2026-09-18 推送式复盘裁决：三问每晚 21:30 定时推送，连续 3 天
        没答自动暂停；「复盘」是随时重新开始的手动入口（立刻发当日卡）。
        """
        print("[feishu] menu '复盘' -> open daily review", flush=True)
        store = PromptStore(Path(self.tree.state_dir))
        if store.is_open():
            self._send_feedback(
                chat_id, "已有进行中的问答，直接回答即可（回「完成」结束）"
            )
            return
        from scripts.dispatch import review_ritual

        review_ritual.unpause_daily(self.tree)
        try:
            report = review_ritual.open_ritual(self.tree, review_ritual.KIND_DAILY)
        except Exception as exc:  # noqa: BLE001 - 发卡失败回文字，不中断守护
            print(f"[feishu] daily review open fail: {exc}", flush=True)
            self._send_feedback(chat_id, "⚠️ 三问卡片发送失败，请稍后重试")
            return
        if not report["opened"]:
            self._send_feedback(chat_id, "今天的三问已发过了，直接回答即可")

    def _answer_menu(self, chat_id: Optional[str], command: str) -> None:
        """快捷菜单指令分发（拉取式交互：你点菜，我回卡）。"""
        print(f"[feishu] menu {command!r}", flush=True)
        if command in ("菜单", "帮助") or command.lower() == "help":
            self._send_feedback(
                chat_id,
                "可用指令：\n"
                "· 摘要 — 今日摘要卡\n"
                "· 待办 — 进行中的待办（带打开按钮）\n"
                "· 提炼候选 — 今日待提炼清单\n"
                "· 周回顾 — 问答进度/发起指引\n"
                "· 复盘 — 今日三问（手动发起/恢复每晚推送）\n"
                "· 同步看板 — 笔记元数据同步进多维表格（手机看板视图）\n"
                "· 搜 关键词 — 搜笔记（前 5 条带打开按钮）\n"
                "直接发文字=捕获笔记；发链接=转写；发语音=Whisper；发图=OCR",
            )
            return
        if command in ("摘要", "今日摘要"):
            self._menu_digest(chat_id)
            return
        if command == "待办":
            self._menu_todos(chat_id)
            return
        if command == "提炼候选":
            self._menu_undistilled(chat_id)
            return
        if command == "同步看板":
            self._menu_board(chat_id)
            return
        if command == "周回顾":
            self._menu_weekly(chat_id)

    def _menu_board(self, chat_id: Optional[str]) -> None:
        """「同步看板」：手动触发一轮多维表格同步（拉取式，可能耗时数秒）。"""
        from scripts.dispatch.board import sync_board

        try:
            report = sync_board(self.tree)
        except Exception as exc:  # noqa: BLE001 - 同步失败文字告知
            print(f"[feishu] board sync fail: {exc}", flush=True)
            report = None
        if not report:
            self._send_feedback(
                chat_id, "⚠️ 看板同步失败（bitable/drive 权限未开？见 feishu.log）"
            )
            return
        self._send_feedback(
            chat_id,
            f"📊 看板已同步：新增 {report['created']}，更新 {report['updated']}，"
            f"共 {report['total']} 条\n看板地址：{report['url']}",
        )

    def _today_digest_path(self) -> Path:
        """今日摘要机器产物路径（系统/今日摘要-YYYY-MM-DD.md）。"""
        today = datetime.now().strftime("%Y-%m-%d")
        return (
            Path(self.tree.notes_dir)
            / SYSTEM_DIRNAME
            / f"今日摘要-{today}.md"
        )

    def _menu_digest(self, chat_id: Optional[str]) -> None:
        """「摘要」：今日摘要正文卡（截断 3000 字）+ 打开按钮。

        拉取式内容推送：隐私纪律管的是**推**（不请自来上云），用户
        主动点菜要内容属正常使用。
        """
        path = self._today_digest_path()
        if not path.exists():
            self._send_feedback(
                chat_id, "今日摘要还没生成（07:53 定时器跑完才有）"
            )
            return
        try:
            body = frontmatter.loads(
                path.read_text(encoding="utf-8")
            ).content.strip()
        except Exception as exc:  # noqa: BLE001 - 读失败文字告知
            print(f"[feishu] menu digest read fail: {exc}", flush=True)
            self._send_feedback(chat_id, "⚠️ 读取今日摘要失败")
            return
        if len(body) > 3000:
            body = body[:3000] + "\n…（截断，全文点下方按钮）"
        card = {
            "config": {"wide_screen_mode": True},
            "header": {
                "title": {
                    "tag": "plain_text",
                    "content": f"📋 今日摘要（{datetime.now().strftime('%m-%d')}）",
                },
                "template": "blue",
            },
            "elements": [
                {"tag": "div", "text": {"tag": "lark_md", "content": body}},
                {
                    "tag": "action",
                    "actions": [
                        {
                            "tag": "button",
                            "text": {
                                "tag": "plain_text",
                                "content": "在 Obsidian 中打开",
                            },
                            "type": "primary",
                            "url": _console_url(f"{SYSTEM_DIRNAME}/{path.name}"),
                        }
                    ],
                },
            ],
        }
        self._send_card(chat_id, card)

    def _menu_todos(self, chat_id: Optional[str]) -> None:
        """「待办」：进行中待办卡（逐条打开按钮，最多 5 条）。"""
        from scripts.memory.search import MemorySearcher

        try:
            results = MemorySearcher(self.tree).search(tags=[TODO_TAG], limit=5)
        except Exception as exc:  # noqa: BLE001 - 查失败文字告知
            print(f"[feishu] menu todos fail: {exc}", flush=True)
            self._send_feedback(chat_id, "⚠️ 查询待办失败，请稍后重试")
            return
        if not results:
            self._send_feedback(chat_id, "没有进行中的待办 ✅")
            return
        elements: List[Dict[str, Any]] = []
        for item in results:
            elements.append(
                {
                    "tag": "div",
                    "text": {"tag": "lark_md", "content": f"**{item.title}**"},
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
                            "url": _console_url(self.tree._rel_key(item.path)),
                        }
                    ],
                }
            )
        card = {
            "config": {"wide_screen_mode": True},
            "header": {
                "title": {
                    "tag": "plain_text",
                    "content": f"✅ 待办进行中（{len(results)}）",
                },
                "template": "orange",
            },
            "elements": elements,
        }
        self._send_card(chat_id, card)

    def _menu_undistilled(self, chat_id: Optional[str]) -> None:
        """「提炼候选」：今日摘要 frontmatter 的 undistilled 清单卡。"""
        path = self._today_digest_path()
        if not path.exists():
            self._send_feedback(
                chat_id, "今日摘要还没生成（07:53 定时器跑完才有）"
            )
            return
        try:
            meta = frontmatter.loads(
                path.read_text(encoding="utf-8")
            ).metadata
        except Exception as exc:  # noqa: BLE001 - 读失败文字告知
            print(f"[feishu] menu undistilled read fail: {exc}", flush=True)
            self._send_feedback(chat_id, "⚠️ 读取提炼候选失败")
            return
        items = [str(item) for item in (meta.get("undistilled") or [])]
        if not items:
            self._send_feedback(
                chat_id, "今日没有提炼候选（周日提炼仪式见晨报 🧠 节）"
            )
            return
        lines = "\n".join(f"· {item}" for item in items)
        card = {
            "config": {"wide_screen_mode": True},
            "header": {
                "title": {
                    "tag": "plain_text",
                    "content": f"🧠 提炼候选（{len(items)}）",
                },
                "template": "blue",
            },
            "elements": [
                {
                    "tag": "div",
                    "text": {
                        "tag": "lark_md",
                        "content": (
                            f"{lines}\n\n周日挑 1 条提炼进压缩层"
                            "（QuickAdd，五分钟）。"
                        ),
                    },
                },
                {
                    "tag": "action",
                    "actions": [
                        {
                            "tag": "button",
                            "text": {
                                "tag": "plain_text",
                                "content": "打开今日摘要",
                            },
                            "type": "primary",
                            "url": _console_url(f"{SYSTEM_DIRNAME}/{path.name}"),
                        }
                    ],
                },
            ],
        }
        self._send_card(chat_id, card)

    def _menu_weekly(self, chat_id: Optional[str]) -> None:
        """「周回顾」：问答进度或发起指引（模板在 Atelier $weekly 侧维护）。"""
        store = PromptStore(Path(self.tree.state_dir))
        data = store.load() if store.is_open() else None
        if data:
            count = len(data.get("answers") or [])
            self._send_feedback(
                chat_id,
                f"周回顾问答进行中：已收到 {count} 条回答。"
                "直接在飞书回复即可；回「跳过」结束并定稿。",
            )
            return
        self._send_feedback(
            chat_id,
            "当前没有进行中的周回顾问答。\n"
            "周回顾由控制台 $weekly 口令发起（双语模板在 Atelier 侧维护）；"
            "发起后回到飞书直接作答即可。",
        )

    def _add_reaction(self, message_id: str, emoji_type: str = "DONE") -> None:
        """给原消息加表情回执（捕获成功的轻确认，不占气泡）；失败只 log。

        Args:
            message_id: 被回执的消息 id。
            emoji_type: 飞书表情 key（DONE=✅；THUMBSUP=👍 等）。
        """
        try:
            lark = _import_lark()
            client = (
                lark.Client.builder()
                .app_id(self.app_id)
                .app_secret(self.app_secret)
                .build()
            )
            body = (
                lark.api.im.v1.CreateMessageReactionRequestBody.builder()
                .reaction_type(
                    lark.api.im.v1.Emoji.builder()
                    .emoji_type(emoji_type)
                    .build()
                )
                .build()
            )
            request = (
                lark.api.im.v1.CreateMessageReactionRequest.builder()
                .message_id(message_id)
                .request_body(body)
                .build()
            )
            if not client.im.v1.message_reaction.create(request).success():
                print(f"[feishu] reaction fail: {message_id}", flush=True)
        except Exception as exc:  # noqa: BLE001 - 回执失败绝不影响捕获
            print(f"[feishu] reaction fail: {exc}", flush=True)

    def _locate_note(self, filename: str) -> Tuple[Optional[Path], Optional[str]]:
        """校验并按文件名定位笔记：返回 (path, None) 或 (None, 错误详情)。

        校验：value 里的文件名须为纯文件名（无路径分隔、无 ``..``、
        ``*.md``）——用户手拖归档后位置未知，故用文件名在整个归档树
        里查找（排除 wiki/attachments/trash 等特殊目录）。恰好一个
        匹配才操作：0 个返回 "笔记不存在"，多个返回 "歧义"（同名
        冲突，卡片给不出文件级精确操作，请人到 Obsidian 处理）。
        确认与归档两个回调共用此定位。

        ``inbox/`` 虚拟前缀豁免（2026-09-16 实证）：书籍卡等
        confirm_note 带 ``inbox/`` 前缀（供发送侧 Obsidian URI 解析），
        定位前剥掉按纯文件名处理。
        """
        if filename.startswith("inbox/"):
            filename = filename[len("inbox/"):]
        if (
            not filename
            or "/" in filename
            or "\\" in filename
            or ".." in filename
            or not filename.endswith(".md")
        ):
            return None, "非法路径"
        matches = [
            path
            for path in self.tree.iter_all_note_files()
            if path.name == filename
        ]
        if not matches:
            return None, "笔记不存在"
        if len(matches) > 1:
            return None, "歧义"
        return matches[0], None

    def _maybe_nominate_judgments(
        self, filename: str, chat_id: Optional[str] = None
    ) -> None:
        """确认/归档成功后顺手机器提名判断候选（2026-09-16 回路三）。

        **只提名绝不批准**——机器从你刚确认的内容里摘观点节的原子断言
        （``nominate_from_note`` 只认「分观点论述/观点总结」两节，待办/
        日记等无观点节的笔记自然跳过），攒进晨报安静小节等你
        「批 N 收 / 略 N 拒」。提名失败/无可提名只 log，绝不打断确认
        主流程。
        """
        try:
            note_path, _err = self._locate_note(filename)
            if note_path is None:
                return
            from scripts.dispatch.judgments import nominate_from_note

            nominated = nominate_from_note(self.tree, note_path)
            if nominated:
                print(
                    f"[feishu] nominated {len(nominated)} judgment proposals"
                    f" from {filename}",
                    flush=True,
                )
                self._send_feedback(
                    chat_id,
                    f"💡 顺手从这条里挑出 {len(nominated)} 条判断候选，"
                    "明晨报等你批（批 N 收 / 略 N 拒）",
                )
        except Exception as exc:  # noqa: BLE001 - 附加动作不阻塞主流程
            print(f"[feishu] nominate fail {filename}: {exc}", flush=True)

    def _strip_review_tag(self, note_path: Path) -> bool:
        """移除单篇笔记的「待确认」标签（2026-09-07 批准的人工例外之一）。"""
        return self._strip_tag(note_path, CONFIRM_TAG)

    def _strip_tag(self, note_path: Path, tag: str) -> bool:
        """移除单篇笔记 frontmatter tags 里的指定一项（其余一概不动）。

        仅当 tags 含该标签才改写（幂等：没有不改写）；改写只删该
        标签一项，frontmatter 其余字段与正文经 round-trip 原样保留。

        Returns:
            bool: 实际改写了返回 True；无标签（noop）返回 False。
        """
        text = note_path.read_text(encoding="utf-8")
        post = frontmatter.loads(text)
        tags = post.metadata.get("tags")
        if not isinstance(tags, list) or tag not in tags:
            return False
        post.metadata["tags"] = [item for item in tags if item != tag]
        self._atomic_write(note_path, frontmatter.dumps(post).encode("utf-8"))
        return True

    def _confirm_note(self, filename: str) -> Tuple[bool, str]:
        """「✅ 确认」核心：定位笔记 + 移除待确认标签。

        Returns:
            Tuple[bool, str]: (是否成功, 详情串 ok / noop / 歧义 /
            非法路径 / 笔记不存在)。
        """
        note_path, err = self._locate_note(filename)
        if err:
            return False, err
        stripped = self._strip_review_tag(note_path)
        return True, "ok" if stripped else "noop"

    def _archive_note(self, filename: str, target_dir: Optional[str] = None) -> Tuple[bool, str]:
        """「📁 归档」核心（2026-09-07 批准的人工例外之二；09-09 起人点目录）。

        定位（与确认同）→ 目标目录：显式给定（目录选择卡点定，先经
        _valid_archive_dir 校验）或机器推导（平台[/分类]，规则见
        scripts/dispatch/archive.py；**平台推不出时不再兜底移动**——
        2026-09-12 裁决：退化为仅确认（只删标签、留在收件箱），返回
        "confirm_only"；「选目录…」卡片的推荐项仍用 媒体/ 兜底，因为
        那是人显式点目录的场景）→ 已在目标
        目录则只删标签（幂等，不移动）→ 否则：目标重名检查（绝不
        覆盖）→ mkdir → rename → sidecar 按 id 即时迁移 path
        （MemoryTree.relocate_entry，动态状态原样保留，不等 watcher
        班次）→ 删「待确认」标签。移动成功但删标签失败：log 警告并
        返回 (True, "tag_fail")（提示手动摘除，绝不回滚）。

        Returns:
            Tuple[bool, str]: 成功返回 (True, 目标相对目录)、
                (True, "confirm_only")（推导不出平台，仅确认未移动）或
                (True, "tag_fail")；失败返回 (False, 错误详情串)。
        """
        note_path, err = self._locate_note(filename)
        if err:
            return False, err
        if target_dir is None:
            post = frontmatter.loads(note_path.read_text(encoding="utf-8"))
            platform, category = derive_archive_dir(post)
            if platform is None:
                # 推导不出平台：退化为仅确认（留在收件箱），不兜底乱移
                self._strip_review_tag(note_path)
                return True, "confirm_only"
            target_dir = platform if not category else f"{platform}/{category}"
        elif not self._valid_archive_dir(target_dir):
            return False, "非法目录"
        current_rel = self.tree._rel_key(note_path)
        if "/" in current_rel and current_rel.rsplit("/", 1)[0] == target_dir:
            # 已在目标目录：幂等，只删标签不移动
            self._strip_review_tag(note_path)
            return True, target_dir
        # 目标文件名用定位后的实体名（卡片 value 可能带 inbox/ 虚拟前缀，
        # 直接用 filename 会拼出 平台/分类/inbox/ 嵌套目录——2026-09-17 实证）
        target = Path(self.tree.notes_dir) / target_dir / note_path.name
        if target.exists():
            return False, "目标重名"
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            note_path.rename(target)
        except OSError as exc:
            print(f"[feishu] archive note={filename} move fail: {exc}", flush=True)
            return False, "移动失败"
        note_id = self.tree._read_note_id(target)
        if note_id is not None:
            self.tree.relocate_entry(note_id, self.tree._rel_key(target))
        try:
            self._strip_review_tag(target)
        except Exception as exc:  # noqa: BLE001 - 半截状态提示手动摘除
            print(
                f"[feishu] archive note={filename} moved but tag strip fail: {exc}",
                flush=True,
            )
            return True, "tag_fail"
        return True, target_dir

    @staticmethod
    def _confirmed_card(
        filename: str,
        note_line: str = "已移除「待确认」标签",
        header: str = "✅ 已确认",
    ) -> Dict[str, Any]:
        """操作完成后的替换卡片：按钮区已由完成文本取代（无操作区）。

        Args:
            filename: 笔记文件名（展示用）。
            note_line: 卡片正文第二行（归档成功/半截/待办完成时传场景文案）。
            header: 卡片头文案（确认=✅ 已确认；待办完成=✅ 已完成）。
        """
        return {
            "config": {"wide_screen_mode": True},
            "header": {
                "title": {"tag": "plain_text", "content": header},
                "template": "green",
            },
            "elements": [
                {
                    "tag": "div",
                    "text": {
                        "tag": "plain_text",
                        "content": f"{filename}\n{note_line}",
                    },
                }
            ],
        }

    def _receive_text(
        self, message_id: str, text: str, chat_id: Optional[str] = None
    ) -> Optional[Path]:
        """文本消息 → 追加进当天日记（source: lark；空文本忽略）。

        2026-09-12 裁决（碎片治理）：不再逐条建 feishu-哈希.md 碎片，
        见 _append_diary。

        待答问题会话 open 期间（scripts/dispatch/prompt.py），文本视为
        周回顾等仪式的**回答**：追加进会话状态、回执条数，不捕获为
        笔记；回答「跳过」/「完成」关闭会话。会话关闭后恢复捕获。
        「摘要/待办/提炼候选/周回顾/菜单」是快捷菜单指令（拉取式交互；
        整词精确匹配，会话期间也优先按指令处理——查进度不会被误计为
        回答）；「复盘」手动开启今日三问并解除自动暂停（2026-09-18
        推送式复盘裁决；同级优先，会话期间回复它不会被误计为回答）；「判断：/记为判断：/#判断 」前缀是判断直收指令
        （2026-09-16 裁决：直收进 cognition 判断登记处，照常追加日记，
        回文字轻通知；与菜单同级，会话期间也优先——是登记指令不是
        回答）；「搜 xxx」/「搜索 xxx」是搜索指令（会话期间让位仪式，
        前缀匹配的内容仍计为回答）。未命中以上一切命令的文本先过
        自然语言意图分类（2026-09-18 裁决 B：听懂就执行搜索/摘要/
        待办/复盘，决策深谈类回车间指引，听不懂照旧记日记——
        判断登记不走意图分类，只认「判断：」显式前缀）。
        捕获成功给原消息加 ✅ 表情回执；失败发文字反馈。
        """
        text = text.strip()
        if not text:
            return None
        if text in MENU_COMMANDS or text.lower() == "help":
            self._answer_menu(chat_id, text)
            return None
        # 「复盘」（2026-09-18 推送式复盘裁决）：手动开启今日三问并解除
        # 自动暂停——与菜单指令同级，先于判断/审批/问答会话/捕获处理
        if text == "复盘":
            self._open_daily_review(chat_id)
            return None
        # 判断直收（2026-09-16 裁决：零摩擦登记进 cognition 判断登记处）：
        # 「判断：/记为判断：/#判断 」前缀的文本既是日记也是判断条目——
        # 与菜单指令同级、先于问答会话处理（周回顾期间回复「判断：xxx」
        # 是登记指令，不算仪式回答），日记照记（生活流不丢），判断处
        # 直收（用户显式标记=人已批准，不再二次确认），回文字轻通知
        from scripts.dispatch.judgments import parse_feishu_judgment, register_statement

        statement = parse_feishu_judgment(text)
        if statement:
            try:
                _entry_id, reply = register_statement(
                    self.tree, statement, origin_note="飞书直收（用户主动标记）"
                )
            except Exception as exc:  # noqa: BLE001 - 登记失败不丢日记
                print(f"[feishu] judgment fail: {exc}", flush=True)
                self._send_feedback(chat_id, "⚠️ 判断登记失败，请稍后重发")
                return None
            self._append_diary(text)
            self._send_feedback(chat_id, reply)
            return None
        # 机器提名批量审批（2026-09-16 回路三）：「批 N」收第 N 条待批
        # 候选进登记处（certainty 用提名建议值）、「略 N」拒掉——与菜单
        # 指令同级，先于问答会话；序号与晨报安静小节同源同序
        from scripts.dispatch.judgments import decide_by_index

        decides = re.findall(r"(批|略)\s*(\d{1,2})", text)
        if decides and re.fullmatch(r"(?:[批略]\s*\d{1,2}[，,、\s]*)*", text):
            # 支持一条消息批多条（「批 1 2」「批1批2」「批 1、略 2」）：
            # 同序号去重（后者为准），按序号从大到小依次裁决防位移——
            # 2026-09-17 实测：批掉 1 号后原 2 号变 1 号，「批 2」扑空报错
            replies = []
            todo: Dict[int, bool] = {}
            for verdict, num in decides:
                todo[int(num)] = verdict == "批"
            for num in sorted(todo, reverse=True):
                try:
                    _ok, reply = decide_by_index(self.tree, num, todo[num])
                except Exception as exc:  # noqa: BLE001 - 审批失败不中断守护
                    print(f"[feishu] proposal decide fail: {exc}", flush=True)
                    reply = "⚠️ 审批失败，请稍后重试"
                replies.append(reply)
            self._send_feedback(chat_id, "\n".join(replies))
            return None
        distills = re.findall(r"(提|题|弃)\s*(\d{1,2})", text)
        if distills and re.fullmatch(r"(?:[提题弃]\s*\d{1,2}[，,、\s]*)*", text):
            # 提炼草稿审批（2026-09-18 深加工链路）：「提 N」落压缩层、
            # 「弃 N」跳过；与判断「批/略」同款多序号、倒序防位移。
            # 「题」作「提」的同音别名（2026-09-18 实测：用户发「题 1」
            # 被吞进日记、审批丢失——输入法同音字是常态不是手误）
            from scripts.dispatch import distill as distill_module

            replies = []
            todo_distill: Dict[int, bool] = {}
            for verdict, num in distills:
                todo_distill[int(num)] = verdict in ("提", "题")
            for num in sorted(todo_distill, reverse=True):
                try:
                    _ok, reply = distill_module.decide_by_index(
                        self.tree, num, todo_distill[num]
                    )
                except Exception as exc:  # noqa: BLE001 - 审批失败不中断守护
                    print(f"[feishu] distill decide fail: {exc}", flush=True)
                    reply = "⚠️ 审批失败，请稍后重试"
                replies.append(reply)
            self._send_feedback(chat_id, "\n".join(replies))
            return None
        store = PromptStore(Path(self.tree.state_dir))
        if store.is_open():
            if text.lower() in CLOSE_WORDS:
                closed = store.close()
                # 回顾仪式（review-* kind）：答案机械落盘 reflections/
                if closed and str(closed.get("kind") or "").startswith("review"):
                    try:
                        from scripts.dispatch import review_ritual

                        written = review_ritual.write_answers(self.tree, closed)
                        print(f"[feishu] review dump -> {written}", flush=True)
                        if written is not None:
                            self._send_feedback(
                                chat_id, f"答案已存进 {written.name}（下次会话综合成文）"
                            )
                    except Exception as exc:  # noqa: BLE001 - 钩子是附加动作
                        print(f"[feishu] review dump fail: {exc}", flush=True)
                self._send_feedback(chat_id, "好的，本次问答已结束 ✅")
            else:
                count = store.append(text)
                self._send_feedback(chat_id, f"已收到（第 {count} 条回答）")
            return None
        for prefix in SEARCH_PREFIXES:
            if text.startswith(prefix):
                self._answer_search(chat_id, text[len(prefix):].strip())
                return None
        if text in ("搜", "搜索"):
            self._send_feedback(chat_id, "用法：发「搜 关键词」，我回前 5 条匹配")
            return None
        # 自然语言意图（2026-09-18 用户裁决 B：Atelier 意图层上岗 v1）：
        # 未命中一切精确命令的文本过 LLM 意图分类——听懂就执行（搜索/
        # 摘要/待办/复盘），决策深谈类回车间指引，听不懂/失败一律照旧
        # 记日记（零回归）；判断登记不走这里，只认「判断：」显式前缀
        try:
            from scripts.dispatch.intent import classify

            routed = classify(text)
        except Exception as exc:  # noqa: BLE001 - 意图是增强工序，不中断守护
            print(f"[feishu] intent fail: {exc}", flush=True)
            routed = None
        if routed:
            intent = routed["intent"]
            print(f"[feishu] intent -> {intent} ({routed['query']!r})", flush=True)
            if intent == "search":
                self._answer_search(chat_id, routed["query"])
            elif intent == "digest":
                self._menu_digest(chat_id)
            elif intent == "todos":
                self._menu_todos(chat_id)
            elif intent == "reflect":
                self._open_daily_review(chat_id)
            else:  # workshop：决策/深谈/综合类，指引去车间
                self._send_feedback(
                    chat_id,
                    "这件事适合去车间深聊（决策/综合/探索）："
                    "电脑上开 Atelier 会话跟我说，或下次会话提醒我",
                )
            return None
        try:
            note = self._append_diary(text)
        except Exception as exc:  # noqa: BLE001 - 捕获失败文字回执，不中断守护
            print(f"[feishu] capture fail: {exc}", flush=True)
            self._send_feedback(chat_id, "⚠️ 捕获失败，请稍后重发")
            return None
        self._add_reaction(message_id)
        return note

    def _append_diary(self, text: str) -> Optional[Path]:
        """飞书文字追加进当天日记（2026-09-12 用户裁决：碎片治理）。

        不再逐条建 feishu-时间戳-哈希.md 碎片（收件箱乱码名堆积、
        不想点不敢删），统一追加到 memory/ 根目录 ``YYYY-MM-DD.md``
        ——与 QuickAdd 速记同一个文件，格式同为 ``- HH:MM 内容``
        列表行（多行消息后续行缩进两格）。**机器追加日记是"笔记创建
        后绝不改写"红线的用户批准例外，仅此路径**；追加不碰
        frontmatter（id/created 不变），既有日记 bump last_accessed
        （新内容算活跃）；日期用本地时区（日记按自然日）。
        链接消息照常进日记正文——links 管线扫全库正文照样能抓到，
        评论提取见 dispatch/links.py extract_comment 的时间行豁免。
        """
        now = datetime.now(local_timezone())
        diary = Path(self.tree.notes_dir) / f"{now.strftime('%Y-%m-%d')}.md"
        lines = text.splitlines()
        entry = f"- {now.strftime('%H:%M')} {lines[0]}"
        entry += "".join(f"\n  {line}" for line in lines[1:])
        if not diary.exists():
            self.tree.create_note(diary.name, f"{entry}\n", source="lark")
            return diary
        content = diary.read_text(encoding="utf-8")
        sep = "" if content.endswith("\n") else "\n"
        with diary.open("a", encoding="utf-8") as fh:
            fh.write(f"{sep}{entry}\n")
        self.tree.on_note_accessed(diary)
        return diary

    def _receive_post(
        self, message_id: str, content: Dict[str, Any], chat_id: Optional[str] = None
    ) -> None:
        """图文混排消息（msg_type=post）：文字抽出并入日记（含链接照常进
        链接管线），内嵌图片逐张下载进 attachments/媒体/（与单图同路）。

        2026-09-15 评审 P0：post 类型此前被静默吞掉——不报错、不记录、
        不处理。下载失败的配图在日记行尾注明，并在会话里回执，不静默。
        """
        text, images = self._post_text_and_images(content)
        failed = 0
        for key in images:
            blob = self._download_resource(message_id, key, "image")
            if blob is None:
                failed += 1
                continue
            stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
            suffix = hashlib.sha1(f"{message_id}:{key}".encode("utf-8")).hexdigest()[:6]
            target = (
                self.tree.attachments_dir / MEDIA_SUBDIR / f"feishu-{stamp}-{suffix}.png"
            )
            target.parent.mkdir(parents=True, exist_ok=True)
            self._atomic_write(target, blob)
        if text:
            if failed:
                text += f"（{failed} 张配图下载失败）"
            self._receive_text(message_id, text, chat_id=chat_id)
        elif images:
            self._add_reaction(message_id)  # 纯图 post：图已存，给回执
        if failed:
            self._send_feedback(chat_id, f"⚠️ 图文消息里 {failed} 张配图下载失败")

    @staticmethod
    def _post_text_and_images(content: Dict[str, Any]) -> Tuple[str, List[str]]:
        """从 post 消息 content 提取纯文本与内嵌图片 image_key 列表。

        post 结构：``{"title": str, "content": [[{"tag": "text"/"a"/"at"/
        "img", ...}]]}``；兼容本地化包装（zh_cn/en_us）。链接段展开为
        ``文字 URL`` 两段俱全（链接管线扫日记正文能抓到）。
        """
        body = content
        if "content" not in body:
            for locale in ("zh_cn", "en_us", "ja_jp"):
                if isinstance(body.get(locale), dict):
                    body = body[locale]
                    break
        texts: List[str] = []
        images: List[str] = []
        title = str(body.get("title") or "").strip()
        if title:
            texts.append(title)
        for row in body.get("content") or []:
            if not isinstance(row, list):
                continue
            parts: List[str] = []
            for seg in row:
                if not isinstance(seg, dict):
                    continue
                tag = seg.get("tag")
                if tag == "text":
                    parts.append(str(seg.get("text") or ""))
                elif tag == "a":
                    label = str(seg.get("text") or "").strip()
                    href = str(seg.get("href") or "").strip()
                    parts.append(f"{label} {href}".strip())
                elif tag in ("img", "image"):
                    key = str(seg.get("image_key") or "").strip()
                    if key:
                        images.append(key)
            line = "".join(parts).strip()
            if line:
                texts.append(line)
        return "\n".join(texts).strip(), images

    def _receive_resource(
        self,
        message_id: str,
        msg_type: str,
        content: Dict[str, Any],
        chat_id: Optional[str] = None,
    ) -> Optional[Path]:
        """图片/文件/语音消息 → 下载进 attachments/ 平台子目录（media 分发自动接手）。

        归位规则（2026-09-10 用户裁决 G1，与笔记归档同一套目录名）：
        图片/语音与其它文件 → ``attachments/媒体/``；PDF →
        ``attachments/书籍/``（划重点通道）。语音（msg_type=audio）是
        飞书按住说话入口：存 .ogg（AudioProcessor 支持），下一轮 media
        分发走 Whisper 转写 → 转写确认卡，与截图同路。视频消息
        （msg_type=media）同样按 file 拉取、存 .mp4 进 媒体/，由 media
        管线做转写+480p（2026-09-13 实测：飞书直发视频 msg_type 是
        media 而非 file，漏接会被静默吞掉）。资源 API 的
        type 只有 image/file 两类：语音/视频按 file 拉取。

        下载失败（含飞书 234037 文件超限）不再静默：打日志并回执
        用户原因与两条出路（2026-09-12 实测：手机直出视频超限无任何
        反馈；2026-09-13 回执升级为编号出路清单）。
        """
        # 视频消息同时带 image_key（封面）与 file_key（本体）：必须先取
        # file_key，否则会把封面图当视频存（2026-09-13 实测 12KB 假 mp4）
        key = content.get("file_key") or content.get("image_key")
        if not key:
            return None
        resource_type = "image" if msg_type == "image" else "file"
        blob = self._download_resource(message_id, str(key), resource_type)
        if blob is None:
            name = str(content.get("file_name") or "附件").strip() or "附件"
            self._send_feedback(
                chat_id,
                f"⚠️ 附件下载失败：{name}。\n"
                "飞书限制：大文件无法经机器人转发（实测手机直出视频超限）。\n"
                "两条出路：\n"
                "① 发链接——抖音/B站/小红书链接直接发来，视频自动下载入库；\n"
                "② 电脑投递——把文件拖进库的 attachments/媒体/ 目录，自动接手。\n"
                "小视频（30MB 内）可直接重发。",
            )
            return None
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        suffix = hashlib.sha1(message_id.encode("utf-8")).hexdigest()[:6]
        if msg_type == "image":
            filename = f"feishu-{stamp}-{suffix}.png"
        elif msg_type == "audio":
            filename = f"feishu-{stamp}-{suffix}.ogg"
        elif msg_type == "media":
            original = _ILLEGAL_RE.sub(
                "-", str(content.get("file_name") or "video.mp4")
            ).strip(". ")
            if "." not in original:
                original += ".mp4"
            filename = f"feishu-{stamp}-{original}"
        else:
            original = _ILLEGAL_RE.sub(
                "-", str(content.get("file_name") or "file")
            ).strip(". ")
            filename = f"feishu-{stamp}-{original}"
        subdir = BOOK_SUBDIR if filename.lower().endswith(".pdf") else MEDIA_SUBDIR
        attach_dir = self.tree.attachments_dir / subdir
        attach_dir.mkdir(parents=True, exist_ok=True)
        target = attach_dir / filename
        self._atomic_write(target, blob)
        self._add_reaction(message_id)
        return target

    def _download_resource(
        self, message_id: str, key: str, msg_type: str
    ) -> Optional[bytes]:
        """经 API 拉取消息附件二进制；失败返回 None（不中断守护）。"""
        lark = _import_lark()
        client = (
            lark.Client.builder()
            .app_id(self.app_id)
            .app_secret(self.app_secret)
            .build()
        )
        request = (
            lark.api.im.v1.GetMessageResourceRequest.builder()
            .message_id(message_id)
            .file_key(key)
            .type(msg_type)
            .build()
        )
        response = client.im.v1.message_resource.get(request)
        if not response.success():
            print(
                f"[feishu] resource download fail msg={message_id} "
                f"code={response.code} msg={response.msg}",
                flush=True,
            )
            return None
        raw = response.file
        return raw.read() if hasattr(raw, "read") else bytes(raw)

    # ---- 幂等登记 --------------------------------------------------------

    def _seen(self, message_id: str) -> bool:
        return message_id in self._load_seen()

    def _mark_seen(self, message_id: str) -> None:
        seen = self._load_seen()
        seen.append(message_id)
        del seen[:-_SEEN_CAP]
        write_json(self.state_path, {"seen": seen})

    def _load_seen(self) -> List[str]:
        """读取登记表；缺失/损坏返回空表（不抛异常）。"""
        data = read_json(self.state_path, {})
        seen = data.get("seen") if isinstance(data, dict) else None
        return list(seen) if isinstance(seen, list) else []

    @staticmethod
    def _atomic_write(target: Path, blob: bytes) -> None:
        """临时文件 + rename 原子落盘（防 Syncthing 抢到半成品）。"""
        fd, tmp_path = tempfile.mkstemp(
            dir=str(target.parent), suffix=".tmp"
        )
        try:
            with os.fdopen(fd, "wb") as fh:
                fh.write(blob)
            os.replace(tmp_path, target)
        except OSError:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise
