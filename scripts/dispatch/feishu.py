"""飞书机器人桥：长连接收消息进库 + 卡片推送（双向通道）。

接收（飞书 → 系统）：
- 消息事件经 lark-oapi websocket 长连接送达（家里电脑主动连云，
  免公网暴露，与 ntfy 同等安全模型）；
- 文本消息 → memory/ 笔记（``source: lark``；正文含 URL 时由 links
  分发下一轮自动捡起，与 Obsidian 贴链接同路）；``搜 xxx``/``搜索 xxx``
  是搜索指令：查库回前 5 条结果卡（带「打开」按钮），不捕获为笔记；
- 图片/文件/语音消息 → 下载存入 attachments/（media 分发自动捡起
  OCR/转写；语音存 .ogg 走 Whisper，与截图同路）；
- 捕获成功给原消息加 ✅ 表情回执（不占气泡的轻确认；回执失败只
  log，绝不影响捕获）；捕获失败才发文字反馈；
- 幂等：message_id 登记 ``<state_dir>/feishu_messages.json``。

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
from urllib.parse import quote

import frontmatter

from scripts.dispatch.prompt import CLOSE_WORDS, PromptStore

from scripts.dispatch.archive import derive_archive_dir
from scripts.dispatch.media import ATTACHMENTS_DIR
from scripts.memory.core import NOTE_EXCLUDED_DIRS, SYSTEM_DIRNAME, MemoryTree

#: 环境变量名（凭证与推送目标）
ENV_APP_ID = "FEISHU_APP_ID"
ENV_APP_SECRET = "FEISHU_APP_SECRET"
ENV_CHAT_ID = "FEISHU_CHAT_ID"
ENV_CONSOLE_URL = "FEISHU_CONSOLE_URL"
#: Obsidian 库名（obsidian://open?vault=…；可用 FEISHU_VAULT_NAME 覆盖）
ENV_VAULT_NAME = "FEISHU_VAULT_NAME"
DEFAULT_VAULT_NAME = "atelierr-data"
#: 库内笔记路径前缀（FEISHU_NOTE_PREFIX 覆盖；库根=atelierr-data 时
#: 缺省 "memory/"，自定义库名（如手机端库根即 memory/ 文件夹）缺省空）
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

#: 问答表单卡的问题数上限（卡片长度护栏；周回顾四问远未触及）
PROMPT_FORM_MAX_QUESTIONS = 8

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


def _import_lark() -> Any:
    """惰性导入 lark-oapi（可选依赖；缺失时报清晰错误）。"""
    try:
        import lark_oapi as lark  # type: ignore[import-not-found]
    except ImportError as exc:  # pragma: no cover - 依赖缺失路径
        raise RuntimeError(
            "飞书桥需要 lark-oapi：pip install lark-oapi"
        ) from exc
    return lark


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

    def handle_event(self, data: Any) -> None:
        """处理一条消息事件；任何解析失败都只跳过，绝不中断守护。"""
        try:
            message = data.event.message
            message_id = str(message.message_id)
            msg_type = str(message.message_type)
            content = json.loads(message.content or "{}")
        except (AttributeError, json.JSONDecodeError, TypeError):
            return
        # 顺带识别用户 open_id（任务/日历等 API 需要；零额外权限）
        from scripts.dispatch.task_sync import record_user_open_id, sender_open_id

        open_id = sender_open_id(getattr(data.event, "sender", None))
        if open_id:
            record_user_open_id(self.tree.state_dir, open_id)
        if self._seen(message_id):
            return
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
            elif msg_type in ("image", "file", "audio"):
                self._receive_resource(message_id, msg_type, content)
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
        chat_id = self._event_chat_id(data)
        # 顺带识别用户 open_id（回调 operator 带身份，零额外权限）
        from scripts.dispatch.task_sync import record_user_open_id, sender_open_id

        open_id = sender_open_id(getattr(data.event, "operator", None))
        if open_id:
            record_user_open_id(self.tree.state_dir, open_id)
        if action_name == CONFIRM_ACTION:
            return self._handle_confirm(filename, chat_id)
        if action_name == ARCHIVE_PICK_ACTION:
            return self._handle_archive_pick(filename, chat_id)
        if action_name == ARCHIVE_CANCEL_ACTION:
            return self._handle_archive_cancel(filename, chat_id)
        if action_name == ARCHIVE_ACTION:
            target_dir = str(value.get("dir") or "").strip() or None
            return self._handle_archive(filename, chat_id, target_dir)
        if action_name == TODO_DONE_ACTION:
            return self._handle_todo_done(filename, chat_id)
        if action_name == PROMPT_SUBMIT_ACTION:
            return self._handle_prompt_submit(action, chat_id)
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

    def _handle_confirm(self, filename: str, chat_id: Optional[str] = None) -> Dict[str, Any]:
        """「✅ 确认」：只删待确认标签；失败只 toast，不中断守护。"""
        try:
            ok, detail = self._confirm_note(filename)
        except Exception as exc:  # noqa: BLE001 - 回调失败只 toast，不中断守护
            print(f"[feishu] confirm note={filename} fail: {exc}", flush=True)
            self._send_feedback(chat_id, f"⚠️ 处理失败，请稍后重试：{filename}")
            return {"toast": {"type": "error", "content": "处理失败，请稍后重试"}}
        print(f"[feishu] confirm note={filename} {'ok' if ok else 'fail'}", flush=True)
        if not ok:
            reason = self._error_reason(detail)
            self._send_feedback(chat_id, f"⚠️ {reason}：{filename}")
            return {"toast": {"type": "error", "content": reason}}
        title = self._feedback_title(filename)
        self._send_feedback(chat_id, f"✅ 已确认：{title}")
        return {
            "toast": {"type": "success", "content": "已确认"},
            "card": {"type": "raw", "data": self._confirmed_card(filename)},
        }

    def _handle_archive_pick(self, filename: str, chat_id: Optional[str] = None) -> Dict[str, Any]:
        """「📁 归档…」：弹目录选择卡（不移动文件；点定目录才移）。

        候选 = 机器推导（标「推荐」）+ memory/ 现有一级目录（排除
        wiki/系统/attachments 等机器目录），每目录一个按钮 +
        「取消」还原确认卡。笔记不存在只 toast，不出选择卡。
        """
        note_path, err = self._locate_note(filename)
        if err:
            reason = self._error_reason(err)
            self._send_feedback(chat_id, f"⚠️ {reason}：{filename}")
            return {"toast": {"type": "error", "content": reason}}
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
                        target_dir: Optional[str] = None) -> Dict[str, Any]:
        """「📁 确认并归档」：归档移动 + 删待确认标签；失败只 toast。"""
        try:
            ok, detail = self._archive_note(filename, target_dir)
        except Exception as exc:  # noqa: BLE001 - 回调失败只 toast，不中断守护
            print(f"[feishu] archive note={filename} fail: {exc}", flush=True)
            self._send_feedback(chat_id, f"⚠️ 处理失败，请稍后重试：{filename}")
            return {"toast": {"type": "error", "content": "处理失败，请稍后重试"}}
        print(f"[feishu] archive note={filename} {'ok' if ok else 'fail'}", flush=True)
        if not ok:
            reason = self._error_reason(detail)
            self._send_feedback(chat_id, f"⚠️ {reason}：{filename}")
            return {"toast": {"type": "error", "content": reason}}
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
                    "data": self._confirmed_card(
                        filename, note_line="已归档；「待确认」标签请手动摘除"
                    ),
                },
            }
        title = self._feedback_title(filename)
        self._send_feedback(chat_id, f"📁 已确认并归档到 {detail}/：{title}")
        card = {
            "type": "raw",
            "data": self._confirmed_card(
                filename, note_line=f"已归档到 {detail}/ 并移除「待确认」标签"
            ),
        }
        return {
            "toast": {"type": "success", "content": f"已确认并归档到 {detail}/"},
            "card": card,
        }

    def _handle_todo_done(self, filename: str, chat_id: Optional[str] = None) -> Dict[str, Any]:
        """「✅ 已完成」待办：只删待办标签；失败只 toast，不中断守护。"""
        try:
            ok, detail = self._todo_done(filename)
        except Exception as exc:  # noqa: BLE001 - 回调失败只 toast，不中断守护
            print(f"[feishu] todo done note={filename} fail: {exc}", flush=True)
            self._send_feedback(chat_id, f"⚠️ 处理失败，请稍后重试：{filename}")
            return {"toast": {"type": "error", "content": "处理失败，请稍后重试"}}
        print(f"[feishu] todo done note={filename} {'ok' if ok else 'fail'}", flush=True)
        if not ok:
            reason = self._error_reason(detail)
            self._send_feedback(chat_id, f"⚠️ {reason}：{filename}")
            return {"toast": {"type": "error", "content": reason}}
        # 回写飞书任务完成（单向同步；失败只 log，绝不影响标签操作）
        try:
            from scripts.dispatch.task_sync import complete_task_for_todo

            complete_task_for_todo(self.tree.state_dir, filename)
        except Exception as exc:  # noqa: BLE001 - 回写失败不影响回调
            print(f"[feishu] task complete hook fail: {exc}", flush=True)
        title = self._feedback_title(filename)
        self._send_feedback(chat_id, f"✅ 待办已完成：{title}")
        return {
            "toast": {"type": "success", "content": "已完成"},
            "card": {
                "type": "raw",
                "data": self._confirmed_card(
                    filename,
                    note_line="已移除「待办」标签",
                    header="✅ 已完成",
                ),
            },
        }

    def _todo_done(self, filename: str) -> Tuple[bool, str]:
        """「✅ 已完成」核心：定位笔记 + 移除待办标签（与确认同构）。"""
        note_path, err = self._locate_note(filename)
        if err:
            return False, err
        stripped = self._strip_tag(note_path, TODO_TAG)
        return True, "ok" if stripped else "noop"

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
        store.close()
        print(f"[feishu] prompt form submit: {len(answers)} answers", flush=True)
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

    @staticmethod
    def _valid_archive_dir(target_dir: str) -> bool:
        """归档目标目录校验：1-2 级纯相对路径，一级目录非机器专用目录。

        目录来自卡片回调（外部输入）：拒绝绝对路径、``..``、反斜杠、
        非法字符、三级及以上、wiki/系统/attachments/trash/templates
        （NOTE_EXCLUDED_DIRS 成员，归档进去等于藏进机器区）。
        """
        if (
            not target_dir
            or "\\" in target_dir
            or target_dir.startswith("/")
            or _ILLEGAL_RE.search(target_dir)
        ):
            return False
        parts = target_dir.split("/")
        if len(parts) > 2 or any(part in ("", ".", "..") for part in parts):
            return False
        return parts[0] not in NOTE_EXCLUDED_DIRS

    @staticmethod
    def _error_reason(detail: str) -> str:
        """把失败详情串映射成给用户看的原因短语（toast 与反馈消息共用）。"""
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
                            f"{lines}\n\n周日挑 1 条提炼进 wiki"
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
        """
        if (
            not filename
            or "/" in filename
            or "\\" in filename
            or ".." in filename
            or not filename.endswith(".md")
        ):
            return None, "非法路径"
        from scripts.memory.core import iter_note_files

        matches = [
            path
            for path in iter_note_files(self.tree.notes_dir)
            if path.name == filename
        ]
        if not matches:
            return None, "笔记不存在"
        if len(matches) > 1:
            return None, "歧义"
        return matches[0], None

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
        scripts/dispatch/archive.py；平台推不出落 媒体/）→ 已在目标
        目录则只删标签（幂等，不移动）→ 否则：目标重名检查（绝不
        覆盖）→ mkdir → rename → sidecar 按 id 即时迁移 path
        （MemoryTree.relocate_entry，动态状态原样保留，不等 watcher
        班次）→ 删「待确认」标签。移动成功但删标签失败：log 警告并
        返回 (True, "tag_fail")（提示手动摘除，绝不回滚）。

        Returns:
            Tuple[bool, str]: 成功返回 (True, 目标相对目录) 或
                (True, "tag_fail")；失败返回 (False, 错误详情串)。
        """
        note_path, err = self._locate_note(filename)
        if err:
            return False, err
        if target_dir is None:
            post = frontmatter.loads(note_path.read_text(encoding="utf-8"))
            platform, category = derive_archive_dir(post)
            platform = platform or FALLBACK_ARCHIVE_DIR
            target_dir = platform if not category else f"{platform}/{category}"
        elif not self._valid_archive_dir(target_dir):
            return False, "非法目录"
        current_rel = self.tree._rel_key(note_path)
        if "/" in current_rel and current_rel.rsplit("/", 1)[0] == target_dir:
            # 已在目标目录：幂等，只删标签不移动
            self._strip_review_tag(note_path)
            return True, target_dir
        target = Path(self.tree.notes_dir) / target_dir / filename
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
        """文本消息 → memory/ 笔记（source: lark；空文本忽略）。

        待答问题会话 open 期间（scripts/dispatch/prompt.py），文本视为
        周回顾等仪式的**回答**：追加进会话状态、回执条数，不捕获为
        笔记；回答「跳过」/「完成」关闭会话。会话关闭后恢复捕获。
        「摘要/待办/提炼候选/周回顾/菜单」是快捷菜单指令（拉取式交互；
        整词精确匹配，会话期间也优先按指令处理——查进度不会被误计为
        回答）；「搜 xxx」/「搜索 xxx」是搜索指令（会话期间让位仪式，
        前缀匹配的内容仍计为回答）。
        捕获成功给原消息加 ✅ 表情回执；失败发文字反馈。
        """
        text = text.strip()
        if not text:
            return None
        if text in MENU_COMMANDS or text.lower() == "help":
            self._answer_menu(chat_id, text)
            return None
        store = PromptStore(Path(self.tree.state_dir))
        if store.is_open():
            if text.lower() in CLOSE_WORDS:
                store.close()
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
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        suffix = hashlib.sha1(message_id.encode("utf-8")).hexdigest()[:6]
        try:
            note = self.tree.create_note(
                f"feishu-{stamp}-{suffix}.md", text + "\n", source="lark"
            )
        except Exception as exc:  # noqa: BLE001 - 捕获失败文字回执，不中断守护
            print(f"[feishu] capture fail: {exc}", flush=True)
            self._send_feedback(chat_id, "⚠️ 捕获失败，请稍后重发")
            return None
        self._add_reaction(message_id)
        return note

    def _receive_resource(
        self, message_id: str, msg_type: str, content: Dict[str, Any]
    ) -> Optional[Path]:
        """图片/文件/语音消息 → 下载进 attachments/（media 分发自动接手）。

        语音（msg_type=audio）是飞书按住说话入口：存 .ogg（AudioProcessor
        支持），下一轮 media 分发走 Whisper 转写 → 转写确认卡，与截图
        同路。资源 API 的 type 只有 image/file 两类：语音按 file 拉取。
        """
        key = content.get("image_key") or content.get("file_key")
        if not key:
            return None
        resource_type = "image" if msg_type == "image" else "file"
        blob = self._download_resource(message_id, str(key), resource_type)
        if blob is None:
            return None
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        suffix = hashlib.sha1(message_id.encode("utf-8")).hexdigest()[:6]
        if msg_type == "image":
            filename = f"feishu-{stamp}-{suffix}.png"
        elif msg_type == "audio":
            filename = f"feishu-{stamp}-{suffix}.ogg"
        else:
            original = _ILLEGAL_RE.sub(
                "-", str(content.get("file_name") or "file")
            ).strip(". ")
            filename = f"feishu-{stamp}-{original}"
        attach_dir = Path(self.tree.notes_dir) / ATTACHMENTS_DIR
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
        fd, tmp_path = tempfile.mkstemp(
            dir=str(self.state_path.parent), suffix=".tmp"
        )
        try:
            self.state_path.parent.mkdir(parents=True, exist_ok=True)
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump({"seen": seen}, fh, ensure_ascii=False)
            os.replace(tmp_path, self.state_path)
        except OSError:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise

    def _load_seen(self) -> List[str]:
        """读取登记表；缺失/损坏返回空表（不抛异常）。"""
        if not self.state_path.exists():
            return []
        try:
            data = json.loads(self.state_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return []
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


def _console_url(confirm_note: Optional[str]) -> str:
    """「在 Obsidian 中打开」按钮 URL。

    ``FEISHU_CONSOLE_URL`` 环境变量优先（自定义控制台地址）；否则
    生成 ``obsidian://open?vault=<库名>&file=<前缀><笔记去后缀>``
    直达本条笔记（percent-encode 防中文/井号/空格截断）。库名用
    ``FEISHU_VAULT_NAME`` 覆盖（缺省 atelierr-data=桌面端库）；路径
    前缀用 ``FEISHU_NOTE_PREFIX`` 覆盖，缺省跟随库名：库根是
    atelierr-data 时为 ``memory/``，自定义库名时为空。无目标笔记
    （digest 等汇总通知）时落到控制台门面页（系统/控制台）——bare
    ``obsidian://`` 只开应用不定位，属反人机交互，任何按钮都不再用
    裸 scheme。注意库名必须与设备实际库名完全一致（本机手机端为
    ``atelierr-memory``）：库名不匹配时 Obsidian 静默退回最近打开页，
    表现为"链接指错笔记"。
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
    return f"obsidian://open?vault={quote(vault)}&file={quote(prefix + stem)}"


def send_feishu(
    title: str,
    message: str,
    chat_id: Optional[str] = None,
    confirm_note: Optional[str] = None,
    pin: bool = False,
    pin_state: Optional[Path] = None,
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

    Args:
        title: 通知标题。
        message: 通知正文（只放数量等非敏感信息）。
        chat_id: 目标会话；缺省读 ``FEISHU_CHAT_ID`` 环境变量。
        confirm_note: 待确认笔记文件名；None 不加确认/归档按钮。
        pin: 发送成功后是否置顶该卡片。
        pin_state: 置顶登记表（存上一条 message_id）；None 只置顶不替换。

    Returns:
        bool: 发送成功且服务端 success 返回 True。
    """
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
    """确认卡 JSON：打开（URI）+ 可选「✅ 确认」「📁 归档…」callback 按钮。

    「📁 归档…」先弹目录选择卡（archive_pick）——机器推导只作推荐项，
    去处由人点定后才移动（archive_note 带 dir）；取消还原本卡。
    send_feishu 推送与归档取消回调共用本组装器，避免两处卡片漂移。
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
                "text": {"tag": "plain_text", "content": "✅ 确认"},
                "type": "primary",
                # 新版卡片 callback：value 直接放 JSON 对象（若放字符串，
                # 回调时平台原样回传，SDK 校验 action.value 必须是 dict
                # 会直接报错丢弃，回调永远到不了处理器）
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
                "text": {"tag": "plain_text", "content": "📁 归档…"},
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
    return {
        "config": {"wide_screen_mode": True},
        "header": {
            "title": {"tag": "plain_text", "content": title},
            "template": "blue",
        },
        "elements": [
            {"tag": "div", "text": {"tag": "lark_md", "content": message}},
            {"tag": "action", "actions": actions},
        ],
    }


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


def send_feishu_card(
    card: Dict[str, Any],
    chat_id: Optional[str] = None,
    app_id: Optional[str] = None,
    app_secret: Optional[str] = None,
) -> bool:
    """发一张自定义交互卡片；未配置或失败返回 False（绝不抛异常）。

    卡片发送失败时降级为纯文本（取卡片头标题）再试一次。

    Args:
        card: 卡片 JSON（legacy schema：header + elements）。
        chat_id: 目标会话；缺省读 ``FEISHU_CHAT_ID`` 环境变量。
        app_id / app_secret: 凭据覆盖；缺省读环境变量（桥实例传入自身凭据）。

    Returns:
        bool: 发送成功且服务端 success 返回 True。
    """
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
            return True
        title = card.get("header", {}).get("title", {}).get("content", "")
        text = str(title) if title else "（卡片发送失败）"
        return _send(client, target, "text", json.dumps({"text": text})) is not None
    except Exception:  # noqa: BLE001 - 发卡失败不影响主流程
        return False


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


def _pin_card(
    client: Any, message_id: str, pin_state: Optional[Path]
) -> None:
    """置顶一条卡片消息；先摘下登记表里的上一条。任何失败只 log。

    登记表 JSON：{"message_id": <上一条置顶>}，用来每日替换不堆积。
    """
    lark = _import_lark()
    previous = ""
    if pin_state is not None and pin_state.exists():
        try:
            data = json.loads(pin_state.read_text(encoding="utf-8"))
            previous = str(data.get("message_id") or "")
        except (json.JSONDecodeError, OSError):
            previous = ""
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
            pin_state.parent.mkdir(parents=True, exist_ok=True)
            pin_state.write_text(
                json.dumps({"message_id": message_id}, ensure_ascii=False),
                encoding="utf-8",
            )
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
