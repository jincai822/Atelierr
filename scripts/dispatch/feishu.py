"""飞书机器人桥：长连接收消息进库 + 卡片推送（双向通道）。

接收（飞书 → 系统）：
- 消息事件经 lark-oapi websocket 长连接送达（家里电脑主动连云，
  免公网暴露，与 ntfy 同等安全模型）；
- 文本消息 → memory/ 笔记（``source: lark``；正文含 URL 时由 links
  分发下一轮自动捡起，与 Obsidian 贴链接同路）；
- 图片/文件消息 → 下载存入 attachments/（media 分发自动捡起
  OCR/转写）；
- 幂等：message_id 登记 ``<state_dir>/feishu_messages.json``。

发送（系统 → 飞书）：
- 推送规则与 ntfy 一致：只在"用户不知道的事"发生时提醒（链接/OCR
  笔记完成待确认、抓取失败、今日摘要），常规成功不推；
- 发交互卡片（标题 + 正文 + 「在 Obsidian 中打开」URI 按钮——
  纯客户端跳转，无回调、零写入；带 ``confirm_note`` 时追加
  「✅ 确认」与「📁 确认并归档」两个 callback 按钮，点击回调
  ``card.action.trigger``，value 为 dict：{"action": confirm_note |
  archive_note, "note": <文件名>}）；
- 卡片失败降级纯文本。

确认/归档回调（用户点卡片按钮；系统内唯二机器改写笔记文件的路径）：
- 经用户 2026-09-07 批准的人工触发例外（两项）：
  1. 单标签删除——仅删除该笔记 frontmatter ``tags`` 里的「待确认」
     一项，其他字段与正文一概不动；
  2. 按钮触发归档移动——把笔记文件移进按平台/分类推导的归档子目录
     （见 scripts/dispatch/archive.py；与通知「建议归档」行同规则），
     随后执行第 1 项的删标签；sidecar 条目按 id 即时迁移（不等
     watcher 班次）；目标目录已有同名文件绝不覆盖，报冲突提示。
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
from scripts.memory.core import MemoryTree

#: 环境变量名（凭证与推送目标）
ENV_APP_ID = "FEISHU_APP_ID"
ENV_APP_SECRET = "FEISHU_APP_SECRET"
ENV_CHAT_ID = "FEISHU_CHAT_ID"
ENV_CONSOLE_URL = "FEISHU_CONSOLE_URL"
#: Obsidian 库名（obsidian://open?vault=…；可用 FEISHU_VAULT_NAME 覆盖）
ENV_VAULT_NAME = "FEISHU_VAULT_NAME"
DEFAULT_VAULT_NAME = "atelierr-data"

DEFAULT_CONSOLE_URL = "obsidian://"

#: 卡片按钮 action 值里的动作名与「确认」标签（后者与
#: dispatch/links.py、dispatch/media.py 的 REVIEW_TAG 同值）
CONFIRM_ACTION = "confirm_note"
ARCHIVE_ACTION = "archive_note"
CONFIRM_TAG = "待确认"

#: 平台推不出时归档按钮的兜底一级目录（与建议归档行的"省略"不同：
#: 按钮必须给一个去处）
FALLBACK_ARCHIVE_DIR = "媒体"

#: 已处理 message_id 登记表上限（超出裁掉最旧的，防无限膨胀）
_SEEN_CAP = 2000

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
            elif msg_type in ("image", "file"):
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
        if action_name == CONFIRM_ACTION:
            return self._handle_confirm(filename, chat_id)
        if action_name == ARCHIVE_ACTION:
            return self._handle_archive(filename, chat_id)
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

    def _handle_archive(self, filename: str, chat_id: Optional[str] = None) -> Dict[str, Any]:
        """「📁 确认并归档」：归档移动 + 删待确认标签；失败只 toast。"""
        try:
            ok, detail = self._archive_note(filename)
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

    @staticmethod
    def _error_reason(detail: str) -> str:
        """把失败详情串映射成给用户看的原因短语（toast 与反馈消息共用）。"""
        if detail == "歧义":
            return "存在多篇同名笔记，请到 Obsidian 处理"
        if detail == "目标重名":
            return "目标文件夹已有同名笔记，请到 Obsidian 处理"
        if detail == "移动失败":
            return "处理失败，请稍后重试"
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
        """移除单篇笔记的「待确认」标签（2026-09-07 批准的人工例外之一）。

        仅当 tags 含「待确认」才改写（幂等：没有不改写）；改写只删该
        标签一项，frontmatter 其余字段与正文经 round-trip 原样保留。

        Returns:
            bool: 实际改写了返回 True；无标签（noop）返回 False。
        """
        text = note_path.read_text(encoding="utf-8")
        post = frontmatter.loads(text)
        tags = post.metadata.get("tags")
        if not isinstance(tags, list) or CONFIRM_TAG not in tags:
            return False
        post.metadata["tags"] = [tag for tag in tags if tag != CONFIRM_TAG]
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

    def _archive_note(self, filename: str) -> Tuple[bool, str]:
        """「📁 确认并归档」核心（2026-09-07 批准的人工例外之二）。

        定位（与确认同）→ 推导目标目录（平台[/分类]，规则见
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
        post = frontmatter.loads(note_path.read_text(encoding="utf-8"))
        platform, category = derive_archive_dir(post)
        platform = platform or FALLBACK_ARCHIVE_DIR
        target_dir = platform if not category else f"{platform}/{category}"
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
        filename: str, note_line: str = "已移除「待确认」标签"
    ) -> Dict[str, Any]:
        """确认后的替换卡片：按钮区已由「✅ 已确认」文本取代（无操作区）。

        Args:
            filename: 笔记文件名（展示用）。
            note_line: 卡片正文第二行（归档成功/半截时传场景文案）。
        """
        return {
            "config": {"wide_screen_mode": True},
            "header": {
                "title": {"tag": "plain_text", "content": "✅ 已确认"},
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
        """
        text = text.strip()
        if not text:
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
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        suffix = hashlib.sha1(message_id.encode("utf-8")).hexdigest()[:6]
        return self.tree.create_note(
            f"feishu-{stamp}-{suffix}.md", text + "\n", source="lark"
        )

    def _receive_resource(
        self, message_id: str, msg_type: str, content: Dict[str, Any]
    ) -> Optional[Path]:
        """图片/文件消息 → 下载进 attachments/（media 分发自动接手）。"""
        key = content.get("image_key") or content.get("file_key")
        if not key:
            return None
        blob = self._download_resource(message_id, str(key), msg_type)
        if blob is None:
            return None
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        suffix = hashlib.sha1(message_id.encode("utf-8")).hexdigest()[:6]
        if msg_type == "image":
            filename = f"feishu-{stamp}-{suffix}.png"
        else:
            original = _ILLEGAL_RE.sub(
                "-", str(content.get("file_name") or "file")
            ).strip(". ")
            filename = f"feishu-{stamp}-{original}"
        attach_dir = Path(self.tree.notes_dir) / ATTACHMENTS_DIR
        attach_dir.mkdir(parents=True, exist_ok=True)
        target = attach_dir / filename
        self._atomic_write(target, blob)
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
    生成 ``obsidian://open?vault=<库名>&file=memory/<笔记去后缀>``
    直达本条笔记（percent-encode 防中文/井号/空格截断；库名可用
    ``FEISHU_VAULT_NAME`` 覆盖）。bare ``obsidian://`` 只开应用不定位，
    手机端落到空白启动页，属反人机交互；无笔记名时才退回 bare scheme。
    """
    console_url = os.environ.get(ENV_CONSOLE_URL, "").strip()
    if console_url:
        return console_url
    if not confirm_note:
        return DEFAULT_CONSOLE_URL
    vault = os.environ.get(ENV_VAULT_NAME, DEFAULT_VAULT_NAME)
    stem = confirm_note[:-3] if confirm_note.endswith(".md") else confirm_note
    return f"obsidian://open?vault={quote(vault)}&file={quote(f'memory/{stem}')}"


def send_feishu(
    title: str,
    message: str,
    chat_id: Optional[str] = None,
    confirm_note: Optional[str] = None,
) -> bool:
    """发一条飞书卡片推送；未配置或失败返回 False（绝不抛异常）。

    卡片带「在 Obsidian 中打开」URI 按钮（纯客户端跳转，无回调）；
    ``confirm_note`` 给定时追加两个 callback 按钮（value 均为 dict）：
    「✅ 确认」（confirm_note：只删「待确认」标签）与「📁 确认并归档」
    （archive_note：归档移动 + 删标签，见 FeishuBridge.handle_card_action）；
    卡片发送失败时降级为纯文本消息再试一次。

    Args:
        title: 通知标题。
        message: 通知正文（只放数量等非敏感信息）。
        chat_id: 目标会话；缺省读 ``FEISHU_CHAT_ID`` 环境变量。
        confirm_note: 待确认笔记文件名；None 不加确认/归档按钮。

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
        console_url = _console_url(confirm_note)
        actions = [
            {
                "tag": "button",
                "text": {
                    "tag": "plain_text",
                    "content": "在 Obsidian 中打开",
                },
                "type": "primary",
                "url": console_url,
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
                    "text": {"tag": "plain_text", "content": "📁 确认并归档"},
                    "type": "primary",
                    # 同上：value 必须是 dict（回调进 handle_card_action 的
                    # archive_note 分支：归档移动 + 删「待确认」标签）
                    "behaviors": [
                        {
                            "type": "callback",
                            "value": {"action": ARCHIVE_ACTION, "note": confirm_note},
                        }
                    ],
                }
            )
        card = {
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
        if _send(client, target, "interactive", json.dumps(card)):
            return True
        return _send(client, target, "text", json.dumps({"text": f"{title}\n{message}"}))
    except Exception:  # noqa: BLE001 - 推送失败不影响主流程
        return False


def _send(client: Any, chat_id: str, msg_type: str, content: str) -> bool:
    """单发一条消息；服务端非 success 返回 False。"""
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
    return bool(client.im.v1.message.create(request).success())
