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
  「✅ 确认」callback 按钮，点击回调 ``card.action.trigger``）；
- 卡片失败降级纯文本。

确认回调（用户点「✅ 确认」，系统内唯一机器改写笔记的路径）：
- 经用户 2026-09-07 批准的人工触发单标签删除例外：仅删除该笔记
  frontmatter ``tags`` 里的「待确认」一项，其他字段与正文一概不动；
- 回调只带纯文件名（含目录分量视为非法，绝不写文件）；笔记可能已被
  手动归档进子目录（如 抖音/），按文件名在整个归档树查找（排除
  trash/ 等特殊目录），0 个报不存在、多个报歧义（同名冲突请到
  Obsidian 处理）；
- 幂等：无「待确认」标签不改写；异常只记日志 + toast，不中断守护。

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

import frontmatter

from scripts.dispatch.media import ATTACHMENTS_DIR
from scripts.memory.core import MemoryTree

#: 环境变量名（凭证与推送目标）
ENV_APP_ID = "FEISHU_APP_ID"
ENV_APP_SECRET = "FEISHU_APP_SECRET"
ENV_CHAT_ID = "FEISHU_CHAT_ID"
ENV_CONSOLE_URL = "FEISHU_CONSOLE_URL"

DEFAULT_CONSOLE_URL = "obsidian://"

#: 卡片确认按钮 action 值里的动作名与「确认」标签（后者与
#: dispatch/links.py、dispatch/media.py 的 REVIEW_TAG 同值）
CONFIRM_ACTION = "confirm_note"
CONFIRM_TAG = "待确认"

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
                self._receive_text(message_id, str(content.get("text") or ""))
            elif msg_type in ("image", "file"):
                self._receive_resource(message_id, msg_type, content)
        finally:
            self._mark_seen(message_id)

    def handle_card_action(self, data: Any) -> Dict[str, Any]:
        """处理卡片按钮回调（用户点「✅ 确认」）；任何异常只 toast，不中断。

        回调负载结构（lark-oapi P2CardActionTrigger）：
        ``data.event.action.value`` = {"action": "confirm_note",
        "note": "<相对 memory/ 的文件名>"}。非 confirm_note 动作原样忽略。

        这是系统内唯一机器改写笔记的路径：经用户 2026-09-07 批准的人工
        触发单标签删除例外——仅删除笔记 frontmatter tags 里的「待确认」
        一项，其他字段与正文一概不动；路径不合法绝不写文件。笔记可能
        已被用户手动归档进子目录（如 抖音/），查找覆盖整个归档树
        （排除 trash/ 等特殊目录）；0 个匹配报"笔记不存在"，多个匹配
        报歧义（同名冲突需人到 Obsidian 处理）。

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
        if str(value.get("action") or "") != CONFIRM_ACTION:
            return {}
        filename = str(value.get("note") or "").strip()
        try:
            ok, detail = self._confirm_note(filename)
        except Exception as exc:  # noqa: BLE001 - 回调失败只 toast，不中断守护
            print(f"[feishu] confirm note={filename} fail: {exc}", flush=True)
            return {"toast": {"type": "error", "content": "处理失败，请稍后重试"}}
        print(f"[feishu] confirm note={filename} {'ok' if ok else 'fail'}", flush=True)
        if not ok:
            if detail == "歧义":
                return {
                    "toast": {
                        "type": "error",
                        "content": "存在多篇同名笔记，请到 Obsidian 处理",
                    }
                }
            return {"toast": {"type": "error", "content": "笔记不存在或路径非法"}}
        return {
            "toast": {"type": "success", "content": "已确认"},
            "card": {"type": "raw", "data": self._confirmed_card(filename)},
        }

    def _confirm_note(self, filename: str) -> Tuple[bool, str]:
        """移除单篇笔记的「待确认」标签（经用户 2026-09-07 批准的例外）。

        校验：value 里的文件名须为纯文件名（无路径分隔、无 ``..``，
        ``*.md``）——用户手拖归档后位置未知，故用文件名在整个归档树
        里查找（排除 wiki/attachments/trash 等特殊目录）。恰好一个
        匹配才操作：0 个返回"笔记不存在"，多个返回"歧义"（同名笔记
        冲突，卡片给不出文件级精确操作，请人到 Obsidian 处理）。仅当
        tags 含「待确认」才改写（幂等：没有不改写）。改写只删该标签
        一项，frontmatter 其余字段与正文经 round-trip 原样保留。

        Args:
            filename: 笔记文件名（不含目录分量）。

        Returns:
            Tuple[bool, str]: (是否成功, 详情串 ok / noop / 歧义 /
            非法路径 / 笔记不存在)。
        """
        if (
            not filename
            or "/" in filename
            or "\\" in filename
            or ".." in filename
            or not filename.endswith(".md")
        ):
            return False, "非法路径"
        from scripts.memory.core import iter_note_files

        matches = [
            path
            for path in iter_note_files(self.tree.notes_dir)
            if path.name == filename
        ]
        if not matches:
            return False, "笔记不存在"
        if len(matches) > 1:
            return False, "歧义"
        note_path = matches[0]
        text = note_path.read_text(encoding="utf-8")
        post = frontmatter.loads(text)
        tags = post.metadata.get("tags")
        if not isinstance(tags, list) or CONFIRM_TAG not in tags:
            return True, "noop"
        post.metadata["tags"] = [tag for tag in tags if tag != CONFIRM_TAG]
        self._atomic_write(note_path, frontmatter.dumps(post).encode("utf-8"))
        return True, "ok"

    @staticmethod
    def _confirmed_card(filename: str) -> Dict[str, Any]:
        """确认后的替换卡片：按钮区已由「✅ 已确认」文本取代（无操作区）。"""
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
                        "content": f"{filename}\n已移除「待确认」标签",
                    },
                }
            ],
        }

    def _receive_text(self, message_id: str, text: str) -> Optional[Path]:
        """文本消息 → memory/ 笔记（source: lark；空文本忽略）。"""
        text = text.strip()
        if not text:
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


def send_feishu(
    title: str,
    message: str,
    chat_id: Optional[str] = None,
    confirm_note: Optional[str] = None,
) -> bool:
    """发一条飞书卡片推送；未配置或失败返回 False（绝不抛异常）。

    卡片带「在 Obsidian 中打开」URI 按钮（纯客户端跳转，无回调）；
    ``confirm_note`` 给定时追加「✅ 确认」callback 按钮（value 携带
    {"action": "confirm_note", "note": <文件名>}，点击回调
    ``card.action.trigger``，由 FeishuBridge.handle_card_action 移除该
    笔记的「待确认」标签）；卡片发送失败时降级为纯文本消息再试一次。

    Args:
        title: 通知标题。
        message: 通知正文（只放数量等非敏感信息）。
        chat_id: 目标会话；缺省读 ``FEISHU_CHAT_ID`` 环境变量。
        confirm_note: 待确认笔记相对 memory/ 的文件名；None 不加确认按钮。

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
        console_url = os.environ.get(ENV_CONSOLE_URL, DEFAULT_CONSOLE_URL)
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
