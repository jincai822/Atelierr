"""飞书机器人桥单元测试（lark SDK 全部打桩，无真实网络）。

事件解析、幂等登记、附件落盘、卡片发送与降级均为真实代码路径；
lark_oapi 模块经 monkeypatch 替换为内存假实现。
"""

from __future__ import annotations

import io
import json
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import MagicMock

import frontmatter
import pytest

import scripts.dispatch.feishu as feishu_module
import scripts.dispatch.feishu_cards as feishu_cards_module
import scripts.dispatch.feishu_io as feishu_io_module
from scripts.dispatch.feishu import FeishuBridge, send_feishu
from scripts.utils.date_utils import local_timezone


def _today() -> str:
    """当天日记文件名主干（本地时区，与 _append_diary 同口径）。"""
    return datetime.now(local_timezone()).strftime("%Y-%m-%d")


def _event(message_id: str, msg_type: str, content: dict):
    """构造一条假 im.message.receive_v1 事件。"""
    return SimpleNamespace(
        event=SimpleNamespace(
            message=SimpleNamespace(
                message_id=message_id,
                message_type=msg_type,
                content=json.dumps(content),
            )
        )
    )


def _bridge(memory_tree):
    return FeishuBridge(memory_tree, app_id="cli_x", app_secret="secret")


def _fake_lark(monkeypatch, client):
    """把 lark_oapi 换成假模块：所有 builder 链自动成立。

    桥（feishu 模块）与收发基元（feishu_io 模块）各自的 _import_lark
    引用都要换——拆分后两处独立绑定。
    """
    fake_lark = MagicMock()
    fake_lark.Client.builder.return_value.app_id.return_value.app_secret.return_value.build.return_value = (
        client
    )
    monkeypatch.setattr(feishu_module, "_import_lark", lambda: fake_lark)
    monkeypatch.setattr(feishu_io_module, "_import_lark", lambda: fake_lark)
    return fake_lark


def test_text_message_appends_to_diary(memory_tree, capsys):
    """文本消息 → 当天日记（2026-09-12 碎片治理裁决）：source=lark、
    ``- HH:MM 内容`` 列表行（多行缩进续行）、sidecar 登记；
    不再建 feishu-哈希.md 碎片。"""
    bridge = _bridge(memory_tree)
    event = _event("m1", "text", {"text": "今天想到：\n好点子"})
    event.event.message.chat_id = "oc_demo_chat"
    bridge.handle_event(event)

    notes = list(memory_tree.notes_dir.glob(f"{_today()}.md"))
    assert len(notes) == 1
    text = notes[0].read_text(encoding="utf-8")
    assert "source: lark" in text
    assert "  好点子" in text  # 第二行两格缩进续行
    assert not list(memory_tree.notes_dir.glob("feishu-*.md"))
    index_text = (memory_tree.state_dir / "index.json").read_text(encoding="utf-8")
    assert notes[0].stem in index_text
    # 日志带 chat_id（供用户抄进 FEISHU_CHAT_ID）
    assert "chat=oc_demo_chat" in capsys.readouterr().out


def test_text_appends_to_existing_diary(memory_tree):
    """当天日记已存在（QuickAdd 速记写过）：追加列表行，frontmatter 不动。"""
    memory_tree.create_note(f"{_today()}.md", "- 09:00 早上速记\n", source="sync")
    bridge = _bridge(memory_tree)

    bridge.handle_event(_event("m-d1", "text", {"text": "飞书补充"}))

    content = (memory_tree.notes_dir / f"{_today()}.md").read_text(encoding="utf-8")
    assert "- 09:00 早上速记" in content
    assert "飞书补充" in content
    assert "source: sync" in content  # frontmatter 未被改写
    assert not list(memory_tree.notes_dir.glob("feishu-*.md"))


def test_text_with_url_kept_verbatim(memory_tree):
    """含 URL 的消息原样进日记（links 分发下一轮从正文自动捡起）。"""
    bridge = _bridge(memory_tree)
    bridge.handle_event(_event("m2", "text", {"text": "看这个 https://v.douyin.com/abc/"}))

    notes = list(memory_tree.notes_dir.glob(f"{_today()}.md"))
    assert len(notes) == 1
    assert "https://v.douyin.com/abc/" in notes[0].read_text(encoding="utf-8")


def test_duplicate_message_id_skipped(memory_tree):
    """同一 message_id 重复投递：日记只追加一次。"""
    bridge = _bridge(memory_tree)
    event = _event("m3", "text", {"text": "重复投递"})
    bridge.handle_event(event)
    bridge.handle_event(event)

    notes = list(memory_tree.notes_dir.glob(f"{_today()}.md"))
    assert len(notes) == 1
    assert notes[0].read_text(encoding="utf-8").count("重复投递") == 1


def test_empty_text_ignored(memory_tree):
    """空白文本：不建日记（但仍登记防重试风暴）。"""
    bridge = _bridge(memory_tree)
    bridge.handle_event(_event("m4", "text", {"text": "  "}))
    bridge.handle_event(_event("m4", "text", {"text": "  "}))

    assert not list(memory_tree.notes_dir.glob("feishu-*.md"))
    assert not list(memory_tree.notes_dir.glob(f"{_today()}.md"))


def test_malformed_event_skipped(memory_tree):
    """损坏事件（缺字段/坏 JSON）：跳过不抛异常。"""
    bridge = _bridge(memory_tree)
    bridge.handle_event(SimpleNamespace(event=SimpleNamespace()))
    bridge.handle_event(
        _event("m5", "text", {})  # content JSON 里没有 text 字段
    )
    bridge.handle_event(SimpleNamespace(event=None))

    assert not list(memory_tree.notes_dir.glob("feishu-*.md"))
    assert not list(memory_tree.notes_dir.glob(f"{_today()}.md"))


def test_image_message_saved_to_attachments(memory_tree, monkeypatch):
    """图片消息：下载二进制进 attachments/，media 分发可接手。"""
    client = MagicMock()
    resp = client.im.v1.message_resource.get.return_value
    resp.success.return_value = True
    resp.file = io.BytesIO(b"\x89PNG fake")
    _fake_lark(monkeypatch, client)

    bridge = _bridge(memory_tree)
    bridge.handle_event(_event("m6", "image", {"image_key": "img_v3_1"}))

    files = list((memory_tree.attachments_dir / "媒体").glob("feishu-*.png"))
    assert len(files) == 1
    assert files[0].read_bytes() == b"\x89PNG fake"


def test_file_message_keeps_sanitized_name(memory_tree, monkeypatch):
    """文件消息：保留（净化后的）原文件名。"""
    client = MagicMock()
    resp = client.im.v1.message_resource.get.return_value
    resp.success.return_value = True
    resp.file = io.BytesIO(b"%PDF-1.4 fake")
    _fake_lark(monkeypatch, client)

    bridge = _bridge(memory_tree)
    bridge.handle_event(
        _event("m7", "file", {"file_key": "fk1", "file_name": "季度报告: 9月.pdf"})
    )

    files = list((memory_tree.attachments_dir / "书籍").glob("feishu-*.pdf"))
    assert len(files) == 1
    assert "季度报告- 9月" in files[0].name
    assert files[0].read_bytes() == b"%PDF-1.4 fake"


def test_resource_download_failure_skips(memory_tree, monkeypatch):
    """附件下载失败：不落盘、不抛异常（仍登记防重试风暴）。"""
    client = MagicMock()
    client.im.v1.message_resource.get.return_value.success.return_value = False
    _fake_lark(monkeypatch, client)

    bridge = _bridge(memory_tree)
    bridge.handle_event(_event("m8", "image", {"image_key": "img_bad"}))
    bridge.handle_event(_event("m8", "image", {"image_key": "img_bad"}))

    assert not (memory_tree.attachments_dir).exists()


def test_from_env_missing_credentials(memory_tree, monkeypatch):
    """凭证缺失：from_env 抛 RuntimeError 并指明要配什么。"""
    monkeypatch.delenv("FEISHU_APP_ID", raising=False)
    monkeypatch.delenv("FEISHU_APP_SECRET", raising=False)

    with pytest.raises(RuntimeError, match="FEISHU_APP_ID"):
        FeishuBridge.from_env(memory_tree)


def test_send_feishu_without_env_returns_false(monkeypatch):
    """未配置凭证/目标：静默 False。"""
    monkeypatch.delenv("FEISHU_APP_ID", raising=False)
    monkeypatch.delenv("FEISHU_APP_SECRET", raising=False)
    monkeypatch.delenv("FEISHU_CHAT_ID", raising=False)

    assert send_feishu("标题", "正文") is False


def test_send_feishu_card_success(monkeypatch):
    """卡片发送成功：一次 create 即返回 True。"""
    monkeypatch.setenv("FEISHU_APP_ID", "cli_x")
    monkeypatch.setenv("FEISHU_APP_SECRET", "secret")
    monkeypatch.setenv("FEISHU_CHAT_ID", "oc_chat")
    client = MagicMock()
    client.im.v1.message.create.return_value.success.return_value = True
    _fake_lark(monkeypatch, client)

    assert send_feishu("Atelierr 今日摘要", "待确认 2") is True
    assert client.im.v1.message.create.call_count == 1


def test_send_feishu_card_failure_falls_back_to_text(monkeypatch):
    """卡片被拒：降级纯文本再试一次。"""
    monkeypatch.setenv("FEISHU_APP_ID", "cli_x")
    monkeypatch.setenv("FEISHU_APP_SECRET", "secret")
    monkeypatch.setenv("FEISHU_CHAT_ID", "oc_chat")
    client = MagicMock()
    client.im.v1.message.create.side_effect = [
        SimpleNamespace(success=lambda: False),
        SimpleNamespace(success=lambda: True),
    ]
    _fake_lark(monkeypatch, client)

    assert send_feishu("标题", "正文") is True
    assert client.im.v1.message.create.call_count == 2


def test_send_feishu_exception_returns_false(monkeypatch):
    """SDK 异常：返回 False 绝不抛（推送失败不影响主流程）。"""
    monkeypatch.setenv("FEISHU_APP_ID", "cli_x")
    monkeypatch.setenv("FEISHU_APP_SECRET", "secret")
    monkeypatch.setenv("FEISHU_CHAT_ID", "oc_chat")
    client = MagicMock()
    client.im.v1.message.create.side_effect = RuntimeError("network down")
    _fake_lark(monkeypatch, client)

    assert send_feishu("标题", "正文") is False


def test_dispatch_notice_fires_both_channels(monkeypatch):
    """双通道通知：ntfy 与飞书各自调用，单通道失败不影响另一通道。"""
    import scripts.dispatch.notify as notify_module

    calls = []
    monkeypatch.setattr(
        notify_module, "send_ntfy", lambda t, m: calls.append(("ntfy", t)) or True
    )
    monkeypatch.setattr(
        feishu_module,
        "send_feishu",
        lambda t, m, **kwargs: calls.append(("feishu", t)) or False,
    )

    result = notify_module.send_dispatch_notice("Atelierr 今日摘要", "待确认 1")

    assert result == {"ntfy": True, "feishu": False}
    assert [channel for channel, _ in calls] == ["ntfy", "feishu"]


def test_feishu_cli_without_credentials_exits_one(monkeypatch, tmp_path, capsys):
    """dispatch_cli feishu：凭证缺失时 exit 1 并提示配置位置。"""
    from scripts.cli.dispatch_cli import DispatchCLI

    monkeypatch.delenv("FEISHU_APP_ID", raising=False)
    monkeypatch.delenv("FEISHU_APP_SECRET", raising=False)
    config = tmp_path / "memory.yaml"
    config.write_text(
        f"memory:\n  root: {tmp_path / 'memory'}\n  state_dir: {tmp_path / 'state'}\n",
        encoding="utf-8",
    )

    code = DispatchCLI(str(config)).main(args=["feishu"])

    assert code == 1
    assert "FEISHU_APP_ID" in capsys.readouterr().err


def _card_action(value: dict):
    """构造一条假的 p2.card.action.trigger 回调事件。"""
    return SimpleNamespace(event=SimpleNamespace(action=SimpleNamespace(value=value)))


def test_card_action_confirm_removes_review_tag(memory_tree):
    """点「✅ 确认」：只删 tags 里的「待确认」，其余字段与正文原样保留。"""
    bridge = _bridge(memory_tree)
    memory_tree.create_note(
        "douyin-x.md", "正文行\n", source="link", tags=["待确认", "抖音"]
    )
    path = memory_tree.notes_dir / "douyin-x.md"
    before = frontmatter.loads(path.read_text(encoding="utf-8"))

    resp = bridge.handle_card_action(
        _card_action({"action": "confirm_note", "note": "douyin-x.md"})
    )

    assert resp["toast"] == {"type": "success", "content": "已确认"}
    assert resp["card"]["type"] == "raw"
    data = resp["card"]["data"]
    assert data["header"]["template"] == "green"
    assert "已移除「待确认」标签" in data["elements"][0]["text"]["content"]
    after = frontmatter.loads(path.read_text(encoding="utf-8"))
    assert after.metadata == {**before.metadata, "tags": ["抖音"]}
    assert after.content == before.content


def test_card_action_confirm_noop_without_review_tag(memory_tree):
    """无「待确认」标签：不改写（幂等），toast 仍报成功。"""
    bridge = _bridge(memory_tree)
    memory_tree.create_note("ready.md", "已确认的笔记\n", source="link", tags=["抖音"])
    path = memory_tree.notes_dir / "ready.md"
    before_bytes = path.read_bytes()
    before_mtime = path.stat().st_mtime_ns

    resp = bridge.handle_card_action(
        _card_action({"action": "confirm_note", "note": "ready.md"})
    )

    assert resp["toast"] == {"type": "success", "content": "已确认"}
    assert path.read_bytes() == before_bytes
    assert path.stat().st_mtime_ns == before_mtime


def test_card_action_unknown_action_ignored(memory_tree):
    """非 confirm_note 动作：返回空表（卡片不变），不动笔记。"""
    bridge = _bridge(memory_tree)
    memory_tree.create_note("x.md", "正文\n", source="link", tags=["待确认"])
    path = memory_tree.notes_dir / "x.md"
    before = path.read_bytes()

    assert (
        bridge.handle_card_action(_card_action({"action": "other", "note": "x.md"}))
        == {}
    )
    assert path.read_bytes() == before


def test_card_action_invalid_path_refused(memory_tree):
    """路径注入（.. / 子目录 / 空）：error toast，绝不写文件。"""
    bridge = _bridge(memory_tree)
    for note in ("../evil.md", "sub/x.md", ""):
        resp = bridge.handle_card_action(
            _card_action({"action": "confirm_note", "note": note})
        )
        assert resp["toast"]["type"] == "error"
        assert resp["toast"]["content"] == "笔记不存在或路径非法"
    assert not (memory_tree.notes_dir.parent / "evil.md").exists()
    assert not (memory_tree.notes_dir / "sub").exists()


def test_card_action_missing_note_returns_error(memory_tree):
    """笔记不存在：error toast，不抛异常。"""
    bridge = _bridge(memory_tree)
    resp = bridge.handle_card_action(
        _card_action({"action": "confirm_note", "note": "nope.md"})
    )

    assert resp["toast"] == {"type": "error", "content": "笔记不存在或路径非法"}


def _archive_note(memory_tree, filename, subdir):
    """创建顶层笔记后模拟 Obsidian 手动拖进归档子目录，返回新路径。"""
    note = memory_tree.create_note(
        filename, "正文行\n", source="link", tags=["待确认", "抖音"]
    )
    target_dir = memory_tree.notes_dir / subdir
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / filename
    note.replace(target)
    return target


def test_card_action_confirm_note_in_subdir(memory_tree):
    """笔记已归档进子目录（用户先拖再点确认）：全树查找命中并删标签。"""
    bridge = _bridge(memory_tree)
    target = _archive_note(memory_tree, "douyin-x.md", "抖音")
    before = frontmatter.loads(target.read_text(encoding="utf-8"))

    resp = bridge.handle_card_action(
        _card_action({"action": "confirm_note", "note": "douyin-x.md"})
    )

    assert resp["toast"] == {"type": "success", "content": "已确认"}
    after = frontmatter.loads(target.read_text(encoding="utf-8"))
    assert after.metadata == {**before.metadata, "tags": ["抖音"]}
    assert after.content == before.content


def test_card_action_same_name_in_trash_ignored(memory_tree):
    """trash/ 里的同名文件不算：唯一匹配归档树内的那份。"""
    bridge = _bridge(memory_tree)
    target = _archive_note(memory_tree, "douyin-x.md", "抖音")
    trash = memory_tree.notes_dir / "trash"
    trash.mkdir(parents=True, exist_ok=True)
    (trash / "douyin-x.md").write_text(
        "---\ntags: [待确认]\n---\n回收站内容", encoding="utf-8"
    )

    resp = bridge.handle_card_action(
        _card_action({"action": "confirm_note", "note": "douyin-x.md"})
    )

    assert resp["toast"] == {"type": "success", "content": "已确认"}
    assert "待确认" not in frontmatter.loads(
        target.read_text(encoding="utf-8")
    ).metadata.get("tags", [])
    assert "待确认" in frontmatter.loads(
        (trash / "douyin-x.md").read_text(encoding="utf-8")
    ).metadata["tags"]  # 回收站那份不动


def test_card_action_duplicate_name_ambiguous(memory_tree):
    """不同归档目录出现同名笔记：歧义 error toast，两份都不改写。"""
    bridge = _bridge(memory_tree)
    first = _archive_note(memory_tree, "douyin-x.md", "抖音")
    second = _archive_note(memory_tree, "douyin-x.md", "小红书")

    resp = bridge.handle_card_action(
        _card_action({"action": "confirm_note", "note": "douyin-x.md"})
    )

    assert resp["toast"] == {
        "type": "error",
        "content": "存在多篇同名笔记，请到 Obsidian 处理",
    }
    assert "card" not in resp
    for path in (first, second):
        assert "待确认" in frontmatter.loads(
            path.read_text(encoding="utf-8")
        ).metadata["tags"]


def test_card_action_file_only_in_trash_not_found(memory_tree):
    """文件只存在于 trash/：按"笔记不存在"处理，绝不触碰回收站。"""
    bridge = _bridge(memory_tree)
    trash = memory_tree.notes_dir / "trash"
    trash.mkdir(parents=True, exist_ok=True)
    (trash / "gone.md").write_text(
        "---\ntags: [待确认]\n---\n内容", encoding="utf-8"
    )

    resp = bridge.handle_card_action(
        _card_action({"action": "confirm_note", "note": "gone.md"})
    )

    assert resp["toast"] == {"type": "error", "content": "笔记不存在或路径非法"}
    assert "待确认" in frontmatter.loads(
        (trash / "gone.md").read_text(encoding="utf-8")
    ).metadata["tags"]


def test_send_feishu_confirm_note_adds_callback_button(monkeypatch):
    """带 confirm_note 的卡片：打开 + 确认并归档/选目录/仅确认 callback 按钮。"""
    monkeypatch.setenv("FEISHU_APP_ID", "cli_x")
    monkeypatch.setenv("FEISHU_APP_SECRET", "secret")
    monkeypatch.setenv("FEISHU_CHAT_ID", "oc_chat")
    sent = []
    _fake_lark(monkeypatch, MagicMock())
    monkeypatch.setattr(
        feishu_io_module,
        "_send",
        lambda client, chat_id, msg_type, content: sent.append(
            (chat_id, msg_type, content)
        )
        or True,
    )

    assert (
        send_feishu(
            "Atelierr 链接笔记待确认",
            "链接笔记已转写入库：douyin-x.md",
            confirm_note="douyin-x.md",
        )
        is True
    )

    chat_id, msg_type, content = sent[0]
    assert chat_id == "oc_chat"
    assert msg_type == "interactive"
    card = json.loads(content)
    actions = card["elements"][1]["actions"]
    # 2026-09-12 归档默认化：主按钮一步到位确认并归档；
    # 2026-09-13 环节三评审：补「🗑 不要了」（标 pending_delete）
    assert [a["text"]["content"] for a in actions] == [
        "在 Obsidian 中打开",
        "✅ 确认并归档",
        "📁 选目录…",
        "仅确认",
        "🗑 不要了",
    ]
    for button in actions[1:]:
        behavior = button["behaviors"][0]
        assert behavior["type"] == "callback"
        # value 必须是 dict 而非 JSON 字符串：平台回传字符串会被 SDK 校验丢弃
        assert isinstance(behavior["value"], dict)
    assert actions[1]["behaviors"][0]["value"] == {
        "action": feishu_module.ARCHIVE_ACTION,
        "note": "douyin-x.md",
    }
    # 「📁 选目录…」先弹目录选择卡（archive_pick），点定目录才移动
    assert actions[2]["behaviors"][0]["value"] == {
        "action": feishu_module.ARCHIVE_PICK_ACTION,
        "note": "douyin-x.md",
    }
    assert actions[3]["behaviors"][0]["value"] == {
        "action": feishu_module.CONFIRM_ACTION,
        "note": "douyin-x.md",
    }
    # 「🗑 不要了」只标 pending_delete（不动文件）
    assert actions[4]["behaviors"][0]["value"] == {
        "action": "discard_note",
        "note": "douyin-x.md",
    }


def test_dispatch_notice_passes_confirm_note_to_feishu(monkeypatch):
    """confirm_note 只透传给飞书通道（ntfy 无按钮，文本照发）。"""
    import scripts.dispatch.notify as notify_module

    calls = []
    monkeypatch.setattr(notify_module, "send_ntfy", lambda t, m: True)
    monkeypatch.setattr(
        feishu_module,
        "send_feishu",
        lambda t, m, **kwargs: calls.append((t, kwargs)) or False,
    )

    result = notify_module.send_dispatch_notice(
        "Atelierr 链接笔记待确认",
        "链接笔记已转写入库：douyin-x.md",
        confirm_note="douyin-x.md",
    )

    assert result == {"ntfy": True, "feishu": False}
    assert calls == [
        (
            "Atelierr 链接笔记待确认",
            {"confirm_note": "douyin-x.md", "pin": False, "pin_state": None},
        )
    ]


def test_dispatch_notice_passes_pin_to_feishu(monkeypatch, tmp_path):
    """pin/pin_state 只透传给飞书通道（晨报置顶；ntfy 无置顶概念）。"""
    import scripts.dispatch.notify as notify_module

    calls = []
    monkeypatch.setattr(notify_module, "send_ntfy", lambda t, m: True)
    monkeypatch.setattr(
        feishu_module,
        "send_feishu",
        lambda t, m, **kwargs: calls.append(kwargs) or True,
    )
    state = tmp_path / "feishu_pins.json"

    result = notify_module.send_dispatch_notice(
        "Atelierr 今日摘要", "待确认 1", pin=True, pin_state=state
    )

    assert result == {"ntfy": True, "feishu": True}
    assert calls == [{"pin": True, "pin_state": state}]


def _card_archive(filename):
    """构造一条 archive_note 回调事件。"""
    return _card_action({"action": "archive_note", "note": filename})


def test_card_archive_moves_note_and_strips_tag(memory_tree):
    """📁 确认并归档：文件到 抖音/、标签删、index path 即时迁移。"""
    bridge = _bridge(memory_tree)
    note = memory_tree.create_note(
        "douyin-x.md", "正文行\n", source="link", tags=["待确认", "抖音"]
    )
    memory_tree.move_note(note, "mid-term")
    memory_tree.on_note_accessed(note)
    entry_before = memory_tree._entry(note)
    note_id = memory_tree._find_entry_id(note)
    assert entry_before["layer"] == "mid-term"

    resp = bridge.handle_card_action(_card_archive("douyin-x.md"))

    assert resp["toast"] == {"type": "success", "content": "已确认并归档到 抖音/"}
    assert resp["card"]["type"] == "raw"
    assert "已归档到 抖音/" in resp["card"]["data"]["elements"][0]["text"]["content"]
    target = memory_tree.notes_dir / "抖音" / "douyin-x.md"
    assert target.exists()
    assert not note.exists()
    post = frontmatter.loads(target.read_text(encoding="utf-8"))
    assert post.metadata["tags"] == ["抖音"]
    assert post.metadata["source"] == "link"
    # sidecar 已即时迁移（不等 watcher），动态状态原样保留
    entry = memory_tree._load_index().get(str(note_id))
    assert entry is not None
    assert entry["path"] == "抖音/douyin-x.md"
    assert entry["layer"] == "mid-term"
    assert entry["last_accessed"] == entry_before["last_accessed"]


def test_card_archive_uses_cclass_subdir(memory_tree):
    """带中图法分类标签：归档进 平台/分类/ 二级目录。"""
    bridge = _bridge(memory_tree)
    memory_tree.create_note(
        "douyin-psy.md",
        "正文\n",
        source="link",
        tags=["待确认", "抖音", "B84-心理学"],
    )

    resp = bridge.handle_card_action(_card_archive("douyin-psy.md"))

    assert resp["toast"]["content"] == "已确认并归档到 抖音/B84-心理学/"
    target = memory_tree.notes_dir / "抖音" / "B84-心理学" / "douyin-psy.md"
    assert target.exists()
    assert not (memory_tree.notes_dir / "douyin-psy.md").exists()
    assert "待确认" not in frontmatter.loads(
        target.read_text(encoding="utf-8")
    ).metadata["tags"]


def test_card_archive_lark_and_fallback_media_dirs(memory_tree):
    """source=lark → 飞书/；media（媒体类附件）→ 媒体/。"""
    bridge = _bridge(memory_tree)
    memory_tree.create_note("fl-想法.md", "正文\n", source="lark", tags=["待确认"])
    memory_tree.create_note("ocr-截图.md", "正文\n", source="media", tags=["待确认", "截图"])

    resp = bridge.handle_card_action(_card_archive("fl-想法.md"))
    assert resp["toast"]["content"] == "已确认并归档到 飞书/"
    assert (memory_tree.notes_dir / "飞书" / "fl-想法.md").exists()

    resp = bridge.handle_card_action(_card_archive("ocr-截图.md"))
    assert resp["toast"]["content"] == "已确认并归档到 媒体/"
    assert (memory_tree.notes_dir / "媒体" / "ocr-截图.md").exists()


def test_card_archive_underivable_confirm_only(memory_tree):
    """推导不出平台（无 source 映射、无平台标签）：退化为仅确认不移动
    （2026-09-12 裁决；防兜底乱移 媒体/）。"""
    bridge = _bridge(memory_tree)
    memory_tree.create_note("速记碎片.md", "正文\n", source="sync", tags=["待确认"])

    resp = bridge.handle_card_action(_card_archive("速记碎片.md"))

    assert resp["toast"]["content"] == "已确认（留在收件箱）"
    note = memory_tree.notes_dir / "速记碎片.md"
    assert note.exists()  # 没移动
    assert not (memory_tree.notes_dir / "媒体" / "速记碎片.md").exists()
    assert "待确认" not in frontmatter.loads(
        note.read_text(encoding="utf-8")
    ).metadata["tags"]


def test_card_archive_idempotent_when_already_in_target(memory_tree):
    """已在目标目录：只删标签不移动（幂等，可重复点）。"""
    bridge = _bridge(memory_tree)
    memory_tree.create_note(
        "douyin-x.md", "正文行\n", source="link", tags=["待确认", "抖音"]
    )
    bridge.handle_card_action(_card_archive("douyin-x.md"))
    target = memory_tree.notes_dir / "抖音" / "douyin-x.md"
    before = (target.read_bytes(), target.stat().st_mtime_ns)

    resp = bridge.handle_card_action(_card_archive("douyin-x.md"))

    assert resp["toast"] == {"type": "success", "content": "已确认并归档到 抖音/"}
    assert (target.read_bytes(), target.stat().st_mtime_ns) == before  # 文件未再动
    assert target.exists()


def test_card_archive_target_collision_no_overwrite(memory_tree):
    """目标位置被占用（同名目录/竞态文件）：冲突 toast，绝不覆盖。"""
    bridge = _bridge(memory_tree)
    top = memory_tree.create_note(
        "douyin-x.md", "顶层待归档\n", source="link", tags=["待确认", "抖音"]
    )
    # 同名 .md 会被定位歧义前置拦截；此处用同名目录占位目标路径，
    # 命中"目标重名"防御分支（不覆盖目录/文件）
    collide_dir = memory_tree.notes_dir / "抖音"
    collide_dir.mkdir(parents=True)
    (collide_dir / "douyin-x.md").mkdir()
    collide_marker = collide_dir / "douyin-x.md" / "占位.txt"
    collide_marker.write_text("别覆盖我", encoding="utf-8")

    resp = bridge.handle_card_action(_card_archive("douyin-x.md"))

    assert resp["toast"] == {
        "type": "error",
        "content": "目标文件夹已有同名笔记，请到 Obsidian 处理",
    }
    assert "card" not in resp
    assert top.exists()  # 顶层笔记原样（未移动未改标签）
    assert "待确认" in frontmatter.loads(top.read_text(encoding="utf-8")).metadata["tags"]
    assert collide_marker.read_text(encoding="utf-8") == "别覆盖我"  # 占位未被覆盖


def test_card_archive_missing_and_ambiguous(memory_tree):
    """0 匹配 → 笔记不存在；多匹配（跨目录同名）→ 歧义，绝不乱动。"""
    bridge = _bridge(memory_tree)
    resp = bridge.handle_card_action(_card_archive("nope.md"))
    assert resp["toast"] == {"type": "error", "content": "笔记不存在或路径非法"}

    top = memory_tree.create_note(
        "douyin-x.md", "甲\n", source="link", tags=["待确认", "抖音"]
    )
    other_dir = memory_tree.notes_dir / "小红书"
    other_dir.mkdir(parents=True)
    other = other_dir / "douyin-x.md"
    other.write_text(
        "---\nsource: link\ntags: [待确认, 小红书]\n---\n乙", encoding="utf-8"
    )
    resp = bridge.handle_card_action(_card_archive("douyin-x.md"))

    assert resp["toast"]["content"] == "存在多篇同名笔记，请到 Obsidian 处理"
    # 两份都原样未动
    for path in (top, other):
        assert path.exists()
        assert "待确认" in frontmatter.loads(
            path.read_text(encoding="utf-8")
        ).metadata["tags"]
    assert not (memory_tree.notes_dir / "小红书").exists() or sorted(
        (memory_tree.notes_dir / "小红书").iterdir()
    ) == [other]


def _card_action_ctx(value: dict, open_chat_id: str):
    """构造带 context（含 open_chat_id）的卡片回调事件。"""
    return SimpleNamespace(
        event=SimpleNamespace(
            action=SimpleNamespace(value=value),
            context=SimpleNamespace(open_chat_id=open_chat_id),
        )
    )


def _record_send(monkeypatch, sent):
    """把模块级 _send 换成记录 (chat_id, msg_type, content) 的成功实现。"""
    monkeypatch.setattr(
        feishu_module,
        "_send",
        lambda client, chat_id, msg_type, content: sent.append(
            (chat_id, msg_type, content)
        )
        or True,
    )
    _fake_lark(monkeypatch, MagicMock())


def _sent_text(sent, index=0):
    """第 index 条反馈消息的纯文本内容。"""
    return json.loads(sent[index][2])["text"]


def test_card_feedback_confirm_success_title_from_frontmatter(memory_tree, monkeypatch):
    """确认成功：向会话主动补一条文字反馈，标题用 frontmatter title。"""
    monkeypatch.setenv("FEISHU_CHAT_ID", "oc_env")
    sent = []
    _record_send(monkeypatch, sent)
    bridge = _bridge(memory_tree)
    memory_tree.create_note(
        "douyin-x.md",
        "---\ntitle: 跑步教学合集\nsource: link\ntags: [待确认, 抖音]\n---\n正文\n",
    )

    resp = bridge.handle_card_action(
        _card_action({"action": "confirm_note", "note": "douyin-x.md"})
    )

    # 反馈文字与 toast/卡片更新并存，互不替代
    assert resp["toast"] == {"type": "success", "content": "已确认"}
    assert resp["card"]["type"] == "raw"
    assert len(sent) == 1
    chat_id, msg_type, content = sent[0]
    assert chat_id == "oc_env"  # 事件无 context → 回退 FEISHU_CHAT_ID
    assert msg_type == "text"
    assert json.loads(content) == {"text": "✅ 已确认：跑步教学合集"}


def test_card_feedback_archive_success_uses_filename_without_title(memory_tree, monkeypatch):
    """归档成功：文字反馈带目标目录；frontmatter 无 title 时退回文件名。"""
    monkeypatch.setenv("FEISHU_CHAT_ID", "oc_env")
    sent = []
    _record_send(monkeypatch, sent)
    bridge = _bridge(memory_tree)
    # 直接手写（无 title、无 id 的 frontmatter）：_feedback_title 须退回文件名
    (memory_tree.notes_dir / "plain-x.md").write_text(
        "---\nsource: link\ntags: [待确认, 抖音]\n---\n正文", encoding="utf-8"
    )

    resp = bridge.handle_card_action(_card_action({"action": "archive_note", "note": "plain-x.md"}))

    assert resp["toast"]["content"] == "已确认并归档到 抖音/"
    target = memory_tree.notes_dir / "抖音" / "plain-x.md"
    assert target.exists()
    assert len(sent) == 1
    assert sent[0][1] == "text"
    assert _sent_text(sent) == "📁 已确认并归档到 抖音/：plain-x.md"


def test_card_feedback_confirm_failure_reason_and_toast(memory_tree, monkeypatch):
    """确认失败：文字反馈带原因与文件名，error toast 原样保留。"""
    monkeypatch.setenv("FEISHU_CHAT_ID", "oc_env")
    sent = []
    _record_send(monkeypatch, sent)
    bridge = _bridge(memory_tree)

    resp = bridge.handle_card_action(
        _card_action({"action": "confirm_note", "note": "nope.md"})
    )

    assert resp["toast"] == {"type": "error", "content": "笔记不存在或路径非法"}
    assert "card" not in resp
    assert len(sent) == 1
    assert _sent_text(sent) == "⚠️ 笔记不存在或路径非法：nope.md"


def test_card_feedback_send_exception_swallowed(memory_tree, monkeypatch):
    """反馈发送抛异常：只 log，回调照常返回成功结果，不中断守护。"""
    monkeypatch.setenv("FEISHU_CHAT_ID", "oc_env")
    _fake_lark(monkeypatch, MagicMock())

    def boom(client, chat_id, msg_type, content):
        raise RuntimeError("net down")

    monkeypatch.setattr(feishu_module, "_send", boom)
    bridge = _bridge(memory_tree)
    memory_tree.create_note("ok-x.md", "正文\n", source="link", tags=["待确认"])

    resp = bridge.handle_card_action(
        _card_action({"action": "confirm_note", "note": "ok-x.md"})
    )

    assert resp["toast"] == {"type": "success", "content": "已确认"}
    assert resp["card"]["type"] == "raw"


def test_card_feedback_context_chat_id_preferred_over_env(memory_tree, monkeypatch):
    """反馈目标：回调 context 的 open_chat_id 优先，其次 FEISHU_CHAT_ID。"""
    monkeypatch.setenv("FEISHU_CHAT_ID", "oc_env")
    sent = []
    _record_send(monkeypatch, sent)
    bridge = _bridge(memory_tree)
    memory_tree.create_note("x.md", "正文\n", source="link", tags=["待确认"])

    bridge.handle_card_action(
        _card_action_ctx({"action": "confirm_note", "note": "x.md"}, "oc_ctx")
    )
    bridge.handle_card_action(_card_action({"action": "confirm_note", "note": "x.md"}))

    assert [record[0] for record in sent] == ["oc_ctx", "oc_env"]


def test_card_feedback_no_target_skipped_silently(memory_tree, monkeypatch):
    """无 context 且未配 FEISHU_CHAT_ID：不发反馈，其余行为不受影响。"""
    monkeypatch.delenv("FEISHU_CHAT_ID", raising=False)
    sent = []
    _record_send(monkeypatch, sent)
    bridge = _bridge(memory_tree)

    resp = bridge.handle_card_action(
        _card_action({"action": "confirm_note", "note": "nope.md"})
    )

    assert resp["toast"] == {"type": "error", "content": "笔记不存在或路径非法"}
    assert sent == []


def test_card_feedback_archive_tag_fail_hint(memory_tree, monkeypatch):
    """归档移动成功但删标签失败：文字反馈提示手动摘除，warning toast 原样。"""
    monkeypatch.setenv("FEISHU_CHAT_ID", "oc_env")
    sent = []
    _record_send(monkeypatch, sent)
    bridge = _bridge(memory_tree)
    memory_tree.create_note(
        "douyin-x.md",
        "---\ntitle: 跑步教学合集\nsource: link\ntags: [待确认, 抖音]\n---\n正文\n",
    )

    def tag_strip_boom(note_path):
        raise RuntimeError("write fail")

    monkeypatch.setattr(bridge, "_strip_review_tag", tag_strip_boom)
    resp = bridge.handle_card_action(_card_action({"action": "archive_note", "note": "douyin-x.md"}))

    assert resp["toast"]["type"] == "warning"
    assert "已归档" in resp["toast"]["content"]
    assert (memory_tree.notes_dir / "抖音" / "douyin-x.md").exists()  # 移动不回滚
    assert len(sent) == 1
    assert _sent_text(sent) == "⚠️ 已归档，标签请到 Obsidian 手动摘除：跑步教学合集"


def test_console_url_points_at_note(monkeypatch):
    """「在 Obsidian 中打开」缺省直达本条笔记（percent-encode + 库内路径）。

    裸文件名 = 机器刚产出的中转站笔记 → 按 inbox/ 解析（2026-09-14
    待办卡指空实证后的规则，见 feishu_io.py docstring）。
    """
    monkeypatch.delenv("FEISHU_CONSOLE_URL", raising=False)
    monkeypatch.delenv("FEISHU_VAULT_NAME", raising=False)
    monkeypatch.delenv("FEISHU_NOTE_PREFIX", raising=False)

    url = feishu_module._console_url("抖音-内核稳定 #标签.md")

    assert url.startswith("obsidian://open?vault=atelierr-data&file=inbox%2F") or (
        "file=inbox/" in url
    )
    assert "%23" in url  # 井号必须编码，否则 Obsidian 解析截断
    assert url.endswith(".md") is False


def test_console_url_env_override_and_fallback(monkeypatch):
    """FEISHU_CONSOLE_URL 优先；无笔记名退回 bare scheme。"""
    monkeypatch.setenv("FEISHU_CONSOLE_URL", "https://example.com/console")
    assert feishu_module._console_url("x.md") == "https://example.com/console"

    monkeypatch.delenv("FEISHU_CONSOLE_URL")
    monkeypatch.delenv("FEISHU_VAULT_NAME", raising=False)
    monkeypatch.delenv("FEISHU_NOTE_PREFIX", raising=False)
    # 无目标笔记（汇总通知）：落控制台门面页，绝不用裸 scheme
    fallback = feishu_module._console_url(None)
    assert fallback.startswith("obsidian://open?vault=")
    assert "%E6%8E%A7%E5%88%B6%E5%8F%B0" in fallback  # 控制台（编码后）


def test_console_url_custom_vault_drops_memory_prefix(monkeypatch):
    """自定义库名的缺省前缀为空（仅适用库根即 memory/ 的旧布局；

    本机手机端库根=数据根，须显式设 FEISHU_NOTE_PREFIX=memory/，
    见 feishu_io.py ENV_NOTE_PREFIX 注释）。带目录的 memory 内路径
    不加前缀；裸文件名仍按 inbox/ 解析（与库名无关）。"""
    monkeypatch.delenv("FEISHU_CONSOLE_URL", raising=False)
    monkeypatch.delenv("FEISHU_NOTE_PREFIX", raising=False)
    monkeypatch.setenv("FEISHU_VAULT_NAME", "memory")

    url = feishu_module._console_url("日记/2026-09-14.md")

    assert "vault=memory" in url
    assert "file=%E6%97%A5%E8%AE%B0" in url  # file 直接是 日记/…（编码后），无前缀
    assert "memory%2F" not in url and "file=memory/" not in url

    # 裸文件名：机器中转站笔记，即使自定义库也按 inbox/ 解析
    bare = feishu_module._console_url("todo-20260914-x.md")
    assert "file=inbox%2F" in bare or "file=inbox/" in bare


def test_console_url_note_prefix_env_override(monkeypatch):
    """FEISHU_NOTE_PREFIX 显式覆盖前缀（含覆盖为空串）。"""
    monkeypatch.delenv("FEISHU_CONSOLE_URL", raising=False)
    monkeypatch.delenv("FEISHU_VAULT_NAME", raising=False)
    monkeypatch.setenv("FEISHU_NOTE_PREFIX", "notes/")
    assert feishu_module._console_url("sub/x.md").endswith("file=notes%2Fsub%2Fx") or (
        feishu_module._console_url("sub/x.md").endswith("file=notes/sub/x")
    )


def test_console_url_bare_name_resolves_inbox_under_phone_env(monkeypatch):
    """生产配置回归：手机库名 + FEISHU_NOTE_PREFIX=memory/ 时，裸文件名
    （待办/确认卡的产出笔记）必须指到 inbox/——2026-09-14 待办卡指空、
    Obsidian 静默退回控制台页的实证修复。"""
    monkeypatch.delenv("FEISHU_CONSOLE_URL", raising=False)
    monkeypatch.setenv("FEISHU_VAULT_NAME", "atelierr-memory")
    monkeypatch.setenv("FEISHU_NOTE_PREFIX", "memory/")

    url = feishu_module._console_url("todo-20260914-bd9669.md")

    assert "vault=atelierr-memory" in url
    assert "file=inbox%2Ftodo-20260914-bd9669" in url or (
        "file=inbox/todo-20260914-bd9669" in url
    )
    assert "memory" not in url.split("file=")[1]


def test_console_url_inbox_path_skips_memory_prefix(monkeypatch):
    """双根拆分（契约 v1.5）：inbox/ 与 memory/ 平级，inbox 路径不加 memory/ 前缀。"""
    monkeypatch.delenv("FEISHU_CONSOLE_URL", raising=False)
    monkeypatch.delenv("FEISHU_VAULT_NAME", raising=False)
    monkeypatch.delenv("FEISHU_NOTE_PREFIX", raising=False)

    url = feishu_module._console_url("inbox/抖音-x.md")

    assert "file=inbox" in url
    assert "memory" not in url.split("file=")[1]


# ----------------------------------------------------------------------
# 表情回执（捕获成功 ✅ 不占气泡；捕获失败才文字反馈）
# ----------------------------------------------------------------------


def test_capture_text_adds_done_reaction(memory_tree, monkeypatch):
    """文本捕获成功 → 原消息加 ✅ 表情回执。"""
    bridge = _bridge(memory_tree)
    reactions = []
    monkeypatch.setattr(
        bridge, "_add_reaction", lambda mid, **kw: reactions.append(mid)
    )
    event = _event("m-react-1", "text", {"text": "一条想法"})
    event.event.message.chat_id = "oc_demo"
    bridge.handle_event(event)

    assert reactions == ["m-react-1"]
    assert len(list(memory_tree.notes_dir.glob(f"{_today()}.md"))) == 1


def test_capture_resource_adds_done_reaction(memory_tree, monkeypatch):
    """图片/文件捕获成功 → 同样加 ✅ 表情回执。"""
    bridge = _bridge(memory_tree)
    monkeypatch.setattr(bridge, "_download_resource", lambda *a: b"\x89PNG")
    reactions = []
    monkeypatch.setattr(
        bridge, "_add_reaction", lambda mid, **kw: reactions.append(mid)
    )
    bridge.handle_event(_event("m-react-2", "image", {"image_key": "img_x"}))

    assert reactions == ["m-react-2"]


def test_reaction_calls_api_with_done_emoji(memory_tree, monkeypatch):
    """真实 _add_reaction：调 message_reaction.create，emoji_type=DONE。"""
    bridge = _bridge(memory_tree)
    client = MagicMock()
    fake = _fake_lark(monkeypatch, client)

    bridge._add_reaction("m-x")

    client.im.v1.message_reaction.create.assert_called_once()
    fake.api.im.v1.Emoji.builder.return_value.emoji_type.assert_called_with(
        "DONE"
    )


def test_reaction_api_failure_still_captures(memory_tree, monkeypatch):
    """reaction API 异常被吞掉：捕获照常建成笔记。"""
    bridge = _bridge(memory_tree)
    client = MagicMock()
    client.im.v1.message_reaction.create.side_effect = RuntimeError("down")
    _fake_lark(monkeypatch, client)

    bridge.handle_event(_event("m-react-3", "text", {"text": "照进"}))

    assert len(list(memory_tree.notes_dir.glob(f"{_today()}.md"))) == 1
    client.im.v1.message_reaction.create.assert_called_once()


def test_prompt_answer_no_reaction(memory_tree, monkeypatch):
    """问答会话 open 期间：文本是回答（文字回执条数），不加表情。"""
    from scripts.dispatch.prompt import PromptStore

    PromptStore(memory_tree.state_dir).open("weekly", ["Q1"])
    bridge = _bridge(memory_tree)
    reactions = []
    monkeypatch.setattr(
        bridge, "_add_reaction", lambda mid, **kw: reactions.append(mid)
    )
    sent = []
    monkeypatch.setattr(
        bridge, "_send_feedback", lambda chat, text: sent.append(text)
    )
    event = _event("m-react-4", "text", {"text": "答案一"})
    event.event.message.chat_id = "oc_demo"
    bridge.handle_event(event)

    assert reactions == []
    assert sent == ["已收到（第 1 条回答）"]


def test_capture_failure_sends_text_feedback(memory_tree, monkeypatch):
    """建笔记异常 → 文字反馈，不加表情（失败必须让人知道）。"""
    bridge = _bridge(memory_tree)

    def _boom(*a, **kw):
        raise RuntimeError("disk full")

    monkeypatch.setattr(bridge.tree, "create_note", _boom)
    sent = []
    monkeypatch.setattr(
        bridge, "_send_feedback", lambda chat, text: sent.append(text)
    )
    reactions = []
    monkeypatch.setattr(
        bridge, "_add_reaction", lambda mid, **kw: reactions.append(mid)
    )
    event = _event("m-react-5", "text", {"text": "会失败"})
    event.event.message.chat_id = "oc_demo"
    bridge.handle_event(event)

    assert sent == ["⚠️ 捕获失败，请稍后重发"]
    assert reactions == []


# ----------------------------------------------------------------------
# 摘要卡置顶（pin=True：置新卡、摘旧卡、登记表每日替换）
# ----------------------------------------------------------------------


def _send_ok(message_id):
    """生成返回指定 message_id 的假 _send。"""
    return lambda client, chat_id, msg_type, content: message_id


def _pin_env(monkeypatch, client):
    monkeypatch.setenv("FEISHU_APP_ID", "cli_x")
    monkeypatch.setenv("FEISHU_APP_SECRET", "secret")
    monkeypatch.setenv("FEISHU_CHAT_ID", "oc_chat")
    _fake_lark(monkeypatch, client)


def test_send_returns_message_id_on_success(monkeypatch):
    """_send：success 响应返回 message_id；失败响应返回 None。"""
    client = MagicMock()
    response = client.im.v1.message.create.return_value
    response.success.return_value = True
    response.data.message_id = "om_123"
    _fake_lark(monkeypatch, client)

    assert feishu_module._send(client, "oc", "text", "{}") == "om_123"
    response.success.return_value = False
    assert feishu_module._send(client, "oc", "text", "{}") is None


def test_send_feishu_pin_creates_pin_and_state(monkeypatch, tmp_path):
    """pin=True：发送成功后置顶卡片，message_id 写进登记表。"""
    client = MagicMock()
    _pin_env(monkeypatch, client)
    monkeypatch.setattr(feishu_io_module, "_send", _send_ok("om_new"))
    state = tmp_path / "feishu_pins.json"

    assert send_feishu("t", "m", pin=True, pin_state=state) is True

    client.im.v1.pin.create.assert_called_once()
    client.im.v1.pin.delete.assert_not_called()  # 无旧置顶可摘
    assert json.loads(state.read_text(encoding="utf-8")) == {
        "message_id": "om_new"
    }


def test_send_feishu_pin_replaces_previous(monkeypatch, tmp_path):
    """已有旧置顶：先 DeletePin 摘下再置新，登记表更新为新的。"""
    client = MagicMock()
    _pin_env(monkeypatch, client)
    monkeypatch.setattr(feishu_io_module, "_send", _send_ok("om_new"))
    state = tmp_path / "feishu_pins.json"
    state.write_text(
        json.dumps({"message_id": "om_old"}), encoding="utf-8"
    )

    assert send_feishu("t", "m", pin=True, pin_state=state) is True

    client.im.v1.pin.delete.assert_called_once()
    client.im.v1.pin.create.assert_called_once()
    assert json.loads(state.read_text(encoding="utf-8")) == {
        "message_id": "om_new"
    }


def test_send_feishu_pin_failure_keeps_send_result(monkeypatch, tmp_path):
    """置顶 API 抛异常：只 log，发送结果仍 True，登记表不写。"""
    client = MagicMock()
    client.im.v1.pin.create.side_effect = RuntimeError("pin down")
    _pin_env(monkeypatch, client)
    monkeypatch.setattr(feishu_io_module, "_send", _send_ok("om_new"))
    state = tmp_path / "feishu_pins.json"

    assert send_feishu("t", "m", pin=True, pin_state=state) is True

    assert not state.exists()


# ----------------------------------------------------------------------
# 搜索指令（「搜 xxx」/「搜索 xxx」→ 结果卡；不捕获为笔记）
# ----------------------------------------------------------------------


def test_search_command_returns_result_card(memory_tree, monkeypatch):
    """「搜 内核」→ 结果卡（标题+confidence+打开按钮），不建笔记不加表情。"""
    memory_tree.create_note(
        "n1.md",
        "---\ntitle: 内核稳定\n---\n内核稳定是一种能力\n",
        source="test",
        tags=["内核稳定"],
    )
    bridge = _bridge(memory_tree)
    cards = []
    monkeypatch.setattr(
        bridge, "_send_card", lambda chat, card: cards.append(card) or True
    )
    reactions = []
    monkeypatch.setattr(
        bridge, "_add_reaction", lambda mid, **kw: reactions.append(mid)
    )
    event = _event("m-search-1", "text", {"text": "搜 内核"})
    event.event.message.chat_id = "oc_demo"
    bridge.handle_event(event)

    assert len(cards) == 1
    card = cards[0]
    assert card["header"]["title"]["content"] == "🔍 搜索：内核"
    divs = [e for e in card["elements"] if e["tag"] == "div"]
    actions = [e for e in card["elements"] if e["tag"] == "action"]
    assert len(divs) == 1
    assert "内核稳定" in divs[0]["text"]["content"]
    assert len(actions) == 1
    assert actions[0]["actions"][0]["url"].startswith("obsidian://open?vault=")
    # 搜索不捕获、不加表情回执
    assert reactions == []
    assert list(memory_tree.notes_dir.glob("feishu-*.md")) == []


def test_search_prefix_sousuo_variant(memory_tree, monkeypatch):
    """「搜索 xxx」与「搜 xxx」同效。"""
    memory_tree.create_note("n1.md", "睡眠很重要", source="test")
    bridge = _bridge(memory_tree)
    cards = []
    monkeypatch.setattr(
        bridge, "_send_card", lambda chat, card: cards.append(card) or True
    )
    event = _event("m-search-2", "text", {"text": "搜索 睡眠"})
    event.event.message.chat_id = "oc_demo"
    bridge.handle_event(event)

    assert cards[0]["header"]["title"]["content"] == "🔍 搜索：睡眠"


def test_search_no_results_text_feedback(memory_tree, monkeypatch):
    """无匹配 → 文字反馈（不占卡片通道）。"""
    bridge = _bridge(memory_tree)
    sent = []
    monkeypatch.setattr(
        bridge, "_send_feedback", lambda chat, text: sent.append(text)
    )
    event = _event("m-search-3", "text", {"text": "搜 不存在的东西xyz"})
    event.event.message.chat_id = "oc_demo"
    bridge.handle_event(event)

    assert sent == ["没有找到匹配「不存在的东西xyz」的笔记"]


def test_search_bare_prefix_usage_hint(memory_tree, monkeypatch):
    """只发「搜」→ 用法提示，不查库。"""
    bridge = _bridge(memory_tree)
    sent = []
    monkeypatch.setattr(
        bridge, "_send_feedback", lambda chat, text: sent.append(text)
    )
    event = _event("m-search-4", "text", {"text": "搜"})
    event.event.message.chat_id = "oc_demo"
    bridge.handle_event(event)

    assert sent == ["用法：发「搜 关键词」，我回前 5 条匹配"]


def test_search_prefix_counts_as_answer_when_prompt_open(
    memory_tree, monkeypatch
):
    """问答会话 open 期间：「搜 xxx」计为回答（仪式优先于指令）。"""
    from scripts.dispatch.prompt import PromptStore

    PromptStore(memory_tree.state_dir).open("weekly", ["Q1"])
    bridge = _bridge(memory_tree)
    cards = []
    monkeypatch.setattr(
        bridge, "_send_card", lambda chat, card: cards.append(card) or True
    )
    sent = []
    monkeypatch.setattr(
        bridge, "_send_feedback", lambda chat, text: sent.append(text)
    )
    event = _event("m-search-5", "text", {"text": "搜 内核"})
    event.event.message.chat_id = "oc_demo"
    bridge.handle_event(event)

    assert cards == []
    assert sent == ["已收到（第 1 条回答）"]


# ----------------------------------------------------------------------
# 「✅ 已完成」待办按钮（回调删待办标签）与复习卡
# ----------------------------------------------------------------------


def _card_todo_done(filename):
    """构造一条 todo_done 回调事件。"""
    return _card_action({"action": "todo_done", "note": filename})


def test_card_todo_done_strips_only_todo_tag(memory_tree):
    """「✅ 已完成」：tags 里只删「待办」，其他标签原样保留。"""
    memory_tree.create_note(
        "todo-1.md", "行动项\n", source="todo", tags=["待办", "工作"]
    )
    bridge = _bridge(memory_tree)

    result = bridge.handle_card_action(_card_todo_done("todo-1.md"))

    assert result["toast"]["type"] == "success"
    path = memory_tree.notes_dir / "todo-1.md"
    post = frontmatter.loads(path.read_text(encoding="utf-8"))
    assert post.metadata["tags"] == ["工作"]
    assert (
        result["card"]["data"]["header"]["title"]["content"] == "✅ 已完成"
    )


def test_card_todo_done_feedback_and_idempotent(memory_tree, monkeypatch):
    """完成反馈带 frontmatter 标题；无「待办」标签再点也成功（幂等）。"""
    memory_tree.create_note(
        "todo-2.md", "---\ntitle: 打电话\n---\n行动\n", source="todo",
        tags=["待办"],
    )
    bridge = _bridge(memory_tree)
    sent = []
    monkeypatch.setattr(
        bridge, "_send_feedback", lambda chat, text: sent.append(text)
    )

    bridge.handle_card_action(_card_todo_done("todo-2.md"))
    assert sent == ["✅ 待办已完成：打电话"]

    result = bridge.handle_card_action(_card_todo_done("todo-2.md"))
    assert result["toast"]["type"] == "success"


def test_card_todo_done_missing_note(memory_tree, monkeypatch):
    """笔记不存在 → error toast + 文字反馈（不中断守护）。"""
    bridge = _bridge(memory_tree)
    sent = []
    monkeypatch.setattr(
        bridge, "_send_feedback", lambda chat, text: sent.append(text)
    )

    result = bridge.handle_card_action(_card_todo_done("ghost.md"))

    assert result["toast"]["type"] == "error"
    assert sent and "不存在" in sent[0]


def test_send_todo_feishu_card_buttons(monkeypatch):
    """新待办卡：打开（URI）+ ✅ 已完成（callback todo_done）。"""
    cards = []
    monkeypatch.setattr(
        feishu_cards_module,
        "send_feishu_card",
        lambda card, chat_id=None, **kw: cards.append(card) or True,
    )

    assert feishu_module.send_todo_feishu("todo-x.md") is True

    actions = cards[0]["elements"][1]["actions"]
    assert [a["text"]["content"] for a in actions] == [
        "在 Obsidian 中打开",
        "✅ 已完成",
    ]
    behavior = actions[1]["behaviors"][0]
    assert behavior["type"] == "callback"
    assert behavior["value"] == {
        "action": feishu_module.TODO_DONE_ACTION,
        "note": "todo-x.md",
    }


def test_send_resurface_feishu_card_layout(monkeypatch):
    """复习卡：提示语 + 逐条标题 + 打开/想起来了/没想起来三按钮
    （2026-09-13 间隔重复升级）；空队列不发。"""
    assert feishu_module.send_resurface_feishu([]) is False
    cards = []
    monkeypatch.setattr(
        feishu_cards_module,
        "send_feishu_card",
        lambda card, chat_id=None, **kw: cards.append(card) or True,
    )
    items = [
        {"title": "旧文A", "relpath": "a.md", "idle_days": 20},
        {"title": "旧文B", "relpath": "sub/b.md", "idle_days": 30},
    ]

    assert feishu_module.send_resurface_feishu(items) is True

    card = cards[0]
    assert "今日复习（2）" in card["header"]["title"]["content"]
    buttons = [
        a
        for e in card["elements"]
        if e["tag"] == "action"
        for a in e["actions"]
    ]
    assert len(buttons) == 6  # 每条：打开 + 想起来了 + 没想起来
    uri_buttons = [b for b in buttons if "url" in b]
    assert len(uri_buttons) == 2
    assert all(
        b["url"].startswith("obsidian://open?vault=") for b in uri_buttons
    )
    callbacks = [b for b in buttons if "behaviors" in b]
    assert callbacks[0]["behaviors"][0]["value"]["action"] == "resurface_feedback"
    assert callbacks[0]["behaviors"][0]["value"]["outcome"] == "good"
    assert callbacks[0]["behaviors"][0]["value"]["batch"] == ["a.md", "sub/b.md"]
    texts = " ".join(
        e.get("text", {}).get("content", "")
        for e in card["elements"]
        if e["tag"] == "div"
    )
    assert "旧文A" in texts
    assert "闲置 20 天" in texts


# ----------------------------------------------------------------------
# 语音消息捕获（按住说话 → .ogg 进 attachments/，media 分发走 Whisper）
# ----------------------------------------------------------------------


def test_audio_message_saved_as_ogg(memory_tree, monkeypatch):
    """语音消息：下载（资源 type=file）→ 存 .ogg → 加 ✅ 表情回执。"""
    bridge = _bridge(memory_tree)
    downloads = []
    monkeypatch.setattr(
        bridge,
        "_download_resource",
        lambda mid, key, rtype: downloads.append((key, rtype)) or b"OggS",
    )
    reactions = []
    monkeypatch.setattr(
        bridge, "_add_reaction", lambda mid, **kw: reactions.append(mid)
    )

    bridge.handle_event(
        _event("m-audio-1", "audio", {"file_key": "voice_key", "duration": 3})
    )

    assert downloads == [("voice_key", "file")]
    attach_dir = memory_tree.attachments_dir / "媒体"
    saved = list(attach_dir.glob("feishu-*.ogg"))
    assert len(saved) == 1
    assert saved[0].read_bytes() == b"OggS"
    assert reactions == ["m-audio-1"]


def test_audio_message_without_key_skipped(memory_tree, monkeypatch):
    """语音负载缺 file_key：静默跳过（不建文件、不下载）。"""
    bridge = _bridge(memory_tree)
    downloads = []
    monkeypatch.setattr(
        bridge,
        "_download_resource",
        lambda mid, key, rtype: downloads.append(key) or b"x",
    )

    bridge.handle_event(_event("m-audio-2", "audio", {"duration": 3}))

    assert downloads == []
    ogg_dir = memory_tree.attachments_dir / "媒体"
    assert not ogg_dir.exists() or not list(ogg_dir.glob("feishu-*.ogg"))


# ----------------------------------------------------------------------
# 归档目录选择卡（📁 归档… → 点定目录才移动；取消还原）
# ----------------------------------------------------------------------


def _card_archive_pick(filename):
    """构造一条 archive_pick 回调事件。"""
    return _card_action({"action": "archive_pick", "note": filename})


def _card_archive_to(filename, target_dir):
    """构造一条带 dir 的 archive_note 回调事件（目录选择卡点定）。"""
    return _card_action(
        {"action": "archive_note", "note": filename, "dir": target_dir}
    )


def _card_archive_cancel(filename):
    """构造一条 archive_cancel 回调事件。"""
    return _card_action({"action": "archive_cancel", "note": filename})


def test_archive_pick_shows_dirs_without_moving(memory_tree):
    """「📁 归档…」：弹目录选择卡（推荐+现有目录+取消），文件不动。"""
    memory_tree.create_note(
        "douyin-x.md", "正文\n", source="link", tags=["待确认", "抖音"]
    )
    (memory_tree.notes_dir / "书籍").mkdir()
    (memory_tree.notes_dir / "系统").mkdir()  # 机器目录不可选
    bridge = _bridge(memory_tree)

    result = bridge.handle_card_action(_card_archive_pick("douyin-x.md"))

    card = result["card"]["data"]
    assert card["header"]["title"]["content"] == "📁 选择归档目录"
    buttons = [
        a
        for e in card["elements"]
        if e["tag"] == "action"
        for a in e["actions"]
    ]
    labels = [b["text"]["content"] for b in buttons]
    assert labels[0] == "抖音（推荐）"
    assert "书籍" in labels
    assert "系统" not in labels
    assert labels[-1] == "取消"
    dir_values = [b["behaviors"][0]["value"] for b in buttons[:-1]]
    assert dir_values[0] == {
        "action": "archive_note",
        "note": "douyin-x.md",
        "dir": "抖音",
    }
    assert buttons[-1]["behaviors"][0]["value"] == {
        "action": "archive_cancel",
        "note": "douyin-x.md",
    }
    # 文件未移动、标签未删
    assert (memory_tree.notes_dir / "douyin-x.md").exists()
    post = frontmatter.loads(
        (memory_tree.notes_dir / "douyin-x.md").read_text(encoding="utf-8")
    )
    assert "待确认" in post.metadata["tags"]


def test_archive_to_explicit_dir_moves_note(memory_tree):
    """点目录按钮：文件移进指定目录 + 删待确认标签。"""
    memory_tree.create_note("x.md", "正文\n", source="link", tags=["待确认"])
    bridge = _bridge(memory_tree)

    result = bridge.handle_card_action(_card_archive_to("x.md", "书籍"))

    assert result["toast"]["type"] == "success"
    assert not (memory_tree.notes_dir / "x.md").exists()
    moved = memory_tree.notes_dir / "书籍" / "x.md"
    assert moved.exists()
    post = frontmatter.loads(moved.read_text(encoding="utf-8"))
    assert "待确认" not in (post.metadata.get("tags") or [])


def test_archive_to_invalid_dir_rejected(memory_tree):
    """非法目录（逃逸/机器目录/三级/绝对路径）：拒绝，文件原处不动。"""
    memory_tree.create_note("x.md", "正文\n", source="link", tags=["待确认"])
    bridge = _bridge(memory_tree)

    for bad in ("../escape", "系统", "a/b/c", "/abs"):
        result = bridge.handle_card_action(_card_archive_to("x.md", bad))
        assert result["toast"]["type"] == "error", bad

    assert (memory_tree.notes_dir / "x.md").exists()


def test_archive_cancel_restores_confirm_card(memory_tree):
    """「取消」：还原确认卡（打开/确认并归档/选目录/仅确认/不要了），无文件变动。"""
    memory_tree.create_note("x.md", "正文\n", source="link", tags=["待确认"])
    bridge = _bridge(memory_tree)

    result = bridge.handle_card_action(_card_archive_cancel("x.md"))

    actions = result["card"]["data"]["elements"][1]["actions"]
    assert [a["text"]["content"] for a in actions] == [
        "在 Obsidian 中打开",
        "✅ 确认并归档",
        "📁 选目录…",
        "仅确认",
        "🗑 不要了",
    ]
    assert (memory_tree.notes_dir / "x.md").exists()


def test_archive_pick_missing_note_errors(memory_tree, monkeypatch):
    """笔记不存在：error toast + 文字反馈，不出选择卡。"""
    bridge = _bridge(memory_tree)
    sent = []
    monkeypatch.setattr(
        bridge, "_send_feedback", lambda chat, text: sent.append(text)
    )

    result = bridge.handle_card_action(_card_archive_pick("ghost.md"))

    assert result["toast"]["type"] == "error"
    assert "card" not in result
    assert sent and "不存在" in sent[0]


# ----------------------------------------------------------------------
# 快捷菜单指令（摘要/待办/提炼候选/周回顾/菜单）
# ----------------------------------------------------------------------


def _write_digest(memory_tree, undistilled=()):
    """在 系统/ 写一篇今日摘要机器产物（含 undistilled frontmatter）。"""
    from datetime import datetime

    from scripts.dispatch.sysdir import write_machine_note

    today = datetime.now().strftime("%Y-%m-%d")
    if undistilled:
        fm = "---\nundistilled:\n"
        fm += "\n".join(f'- "[[{stem}]]"' for stem in undistilled)
        fm += "\n---\n\n"
    else:
        fm = "---\nundistilled: []\n---\n\n"
    write_machine_note(
        memory_tree.notes_dir,
        f"今日摘要-{today}.md",
        fm + f"# 今日摘要 {today}\n\n## ⏳ 待我确认（0）\n\n- 无\n",
        source="digest",
        tags=["摘要"],
    )
    return today


def test_menu_digest_card(memory_tree, monkeypatch):
    """「摘要」：回今日摘要正文卡 + 打开按钮（指令不捕获为笔记）。"""
    _write_digest(memory_tree)
    bridge = _bridge(memory_tree)
    cards = []
    monkeypatch.setattr(
        bridge, "_send_card", lambda chat, card: cards.append(card) or True
    )
    event = _event("m-menu-1", "text", {"text": "摘要"})
    event.event.message.chat_id = "oc_demo"
    bridge.handle_event(event)

    assert len(cards) == 1
    card = cards[0]
    assert "今日摘要" in card["header"]["title"]["content"]
    assert "待我确认" in card["elements"][0]["text"]["content"]
    assert card["elements"][1]["actions"][0]["url"].startswith(
        "obsidian://open?vault="
    )
    assert list(memory_tree.notes_dir.glob("feishu-*.md")) == []


def test_menu_digest_not_generated_yet(memory_tree, monkeypatch):
    """今日摘要未生成 → 文字提示（不出卡）。"""
    bridge = _bridge(memory_tree)
    sent = []
    monkeypatch.setattr(
        bridge, "_send_feedback", lambda chat, text: sent.append(text)
    )
    bridge.handle_event(_event("m-menu-2", "text", {"text": "摘要"}))

    assert sent == ["今日摘要还没生成（07:53 定时器跑完才有）"]


def test_menu_todos_card(memory_tree, monkeypatch):
    """「待办」：无待办 → ✅ 提示；有待办 → 逐条打开按钮的卡。"""
    bridge = _bridge(memory_tree)
    sent = []
    monkeypatch.setattr(
        bridge, "_send_feedback", lambda chat, text: sent.append(text)
    )
    bridge.handle_event(_event("m-menu-3", "text", {"text": "待办"}))
    assert sent == ["没有进行中的待办 ✅"]

    memory_tree.create_note(
        "todo-x.md", "---\ntitle: 交报告\n---\n做事\n", source="todo",
        tags=["待办"],
    )
    cards = []
    monkeypatch.setattr(
        bridge, "_send_card", lambda chat, card: cards.append(card) or True
    )
    bridge.handle_event(_event("m-menu-4", "text", {"text": "待办"}))
    assert "待办进行中（1）" in cards[0]["header"]["title"]["content"]


def test_menu_undistilled_card(memory_tree, monkeypatch):
    """「提炼候选」：清单来自今日摘要 frontmatter 的 undistilled。"""
    _write_digest(memory_tree, undistilled=["旧文A"])
    bridge = _bridge(memory_tree)
    cards = []
    monkeypatch.setattr(
        bridge, "_send_card", lambda chat, card: cards.append(card) or True
    )
    bridge.handle_event(_event("m-menu-5", "text", {"text": "提炼候选"}))

    card = cards[0]
    assert "提炼候选（1）" in card["header"]["title"]["content"]
    assert "旧文A" in card["elements"][0]["text"]["content"]


def test_menu_weekly_guides_when_no_session(memory_tree, monkeypatch):
    """「周回顾」：无会话 → 发起指引；会话 open → 报进度。"""
    bridge = _bridge(memory_tree)
    sent = []
    monkeypatch.setattr(
        bridge, "_send_feedback", lambda chat, text: sent.append(text)
    )
    bridge.handle_event(_event("m-menu-6", "text", {"text": "周回顾"}))
    assert "$weekly" in sent[-1]

    from scripts.dispatch.prompt import PromptStore

    PromptStore(memory_tree.state_dir).open("weekly", ["Q1"])
    bridge.handle_event(_event("m-menu-7", "text", {"text": "周回顾"}))
    assert "已收到 0 条回答" in sent[-1]
    # 菜单整词优先于回答收集：没被误计为回答
    data = PromptStore(memory_tree.state_dir).load()
    assert data["answers"] == []


def test_menu_help_lists_commands(memory_tree, monkeypatch):
    """「菜单」：回指令清单（含搜索与语音用法）。"""
    bridge = _bridge(memory_tree)
    sent = []
    monkeypatch.setattr(
        bridge, "_send_feedback", lambda chat, text: sent.append(text)
    )
    bridge.handle_event(_event("m-menu-8", "text", {"text": "菜单"}))

    assert "搜 关键词" in sent[0]
    assert "语音" in sent[0]


def _card_form_action(form_value):
    """构造一条表单提交回调（action.value 带 prompt_submit，答案在 form_value）。"""
    return SimpleNamespace(
        event=SimpleNamespace(
            action=SimpleNamespace(
                value={"action": "prompt_submit"}, form_value=form_value
            )
        )
    )


def test_prompt_form_card_shape():
    """表单卡：schema 2.0、form 容器内 q1..qN 输入框 + form_action_type=submit
    提交钮（2026-09-13 实测修正：form_submit 被平台拒收）。"""
    from scripts.dispatch.feishu import prompt_form_card

    card = prompt_form_card("Atelierr 问答（weekly）", "说明", ["问题一", "问题二"])

    assert card["schema"] == "2.0"
    form = card["body"]["elements"][-1]
    assert form["tag"] == "form"
    inputs = form["elements"]
    assert [item["name"] for item in inputs[:2]] == ["q1", "q2"]
    assert "1. 问题一" in inputs[0]["label"]["content"]
    submit = inputs[-1]
    assert submit["form_action_type"] == "submit"
    assert submit["behaviors"][0]["value"] == {"action": "prompt_submit"}
    # 降级取标题兼容（header 结构与旧版一致）
    assert card["header"]["title"]["content"] == "Atelierr 问答（weekly）"


def test_prompt_form_card_caps_questions():
    """问题数超上限截断（卡片长度护栏）。"""
    from scripts.dispatch.feishu import PROMPT_FORM_MAX_QUESTIONS, prompt_form_card

    card = prompt_form_card("t", "", [f"q{i}" for i in range(20)])
    form = card["body"]["elements"][-1]
    assert len(form["elements"]) == PROMPT_FORM_MAX_QUESTIONS + 1  # 含提交钮


def test_prompt_submit_collects_answers_and_closes(memory_tree, monkeypatch):
    """表单提交：非空答案按序追加进会话并关闭；空项跳过。"""
    from scripts.dispatch.prompt import PromptStore

    store = PromptStore(memory_tree.state_dir)
    store.open("weekly", ["问题一", "问题二", "问题三"])
    bridge = _bridge(memory_tree)
    sent = []
    monkeypatch.setattr(
        bridge, "_send_feedback", lambda chat, text: sent.append(text)
    )

    resp = bridge.handle_card_action(
        _card_form_action({"q1": "答一", "q2": "", "q3": "答三"})
    )

    assert resp["toast"]["type"] == "success"
    assert resp["card"]["data"]["header"]["template"] == "green"
    data = store.load()
    assert data["status"] == "closed"
    assert [a["text"] for a in data["answers"]] == ["答一", "答三"]
    assert "2 条回答" in sent[-1]


def test_prompt_submit_all_blank_keeps_open(memory_tree, monkeypatch):
    """全空表单：不动会话，提示仍在进行（用户可文字作答或「跳过」）。"""
    from scripts.dispatch.prompt import PromptStore

    store = PromptStore(memory_tree.state_dir)
    store.open("weekly", ["问题一"])
    bridge = _bridge(memory_tree)
    sent = []
    monkeypatch.setattr(
        bridge, "_send_feedback", lambda chat, text: sent.append(text)
    )

    resp = bridge.handle_card_action(_card_form_action({"q1": "  "}))

    assert resp["toast"]["type"] == "info"
    assert store.is_open() is True
    assert store.load()["answers"] == []
    assert "仍在进行" in sent[-1]


def test_prompt_submit_without_session(memory_tree, monkeypatch):
    """无 open 会话点提交：只提示，不写状态。"""
    bridge = _bridge(memory_tree)
    sent = []
    monkeypatch.setattr(
        bridge, "_send_feedback", lambda chat, text: sent.append(text)
    )

    resp = bridge.handle_card_action(_card_form_action({"q1": "答一"}))

    assert resp["toast"]["type"] == "warning"
    assert "没有进行中的问答" in sent[-1]


def test_prompt_submit_form_value_as_json_string(memory_tree, monkeypatch):
    """form_value 兼容 JSON 字符串负载。"""
    import json as _json

    from scripts.dispatch.prompt import PromptStore

    store = PromptStore(memory_tree.state_dir)
    store.open("daily", ["问题一"])
    bridge = _bridge(memory_tree)
    monkeypatch.setattr(bridge, "_send_feedback", lambda chat, text: None)

    resp = bridge.handle_card_action(_card_form_action(_json.dumps({"q1": "答"})))

    assert resp["toast"]["type"] == "success"
    assert [a["text"] for a in store.load()["answers"]] == ["答"]


def test_message_event_records_sender_open_id(memory_tree):
    """消息事件 sender 里的 open_id 被缓存（供任务/日历 API 用）。"""
    import json as _json

    bridge = _bridge(memory_tree)
    event = _event("m-sender", "text", {"text": "hi"})
    event.event.sender = SimpleNamespace(
        sender_id=SimpleNamespace(open_id="ou_from_msg")
    )
    bridge.handle_event(event)

    account = _json.loads(
        (memory_tree.state_dir / "feishu_account.json").read_text(encoding="utf-8")
    )
    assert account["user_open_id"] == "ou_from_msg"


def test_card_action_records_operator_open_id(memory_tree):
    """卡片回调 operator 里的 open_id 被缓存。"""
    import json as _json

    bridge = _bridge(memory_tree)
    event = _card_action({"action": "other"})
    event.event.operator = SimpleNamespace(open_id="ou_from_card")
    bridge.handle_card_action(event)

    account = _json.loads(
        (memory_tree.state_dir / "feishu_account.json").read_text(encoding="utf-8")
    )
    assert account["user_open_id"] == "ou_from_card"


def test_todo_done_completes_feishu_task(memory_tree, monkeypatch):
    """点「✅ 已完成」：删标签之外回写飞书任务完成（钩子打桩）。"""
    bridge = _bridge(memory_tree)
    memory_tree.create_note("todo-x.md", "# t\n\n- [ ] 做事\n", source="todo", tags=["待办"])
    calls = []
    monkeypatch.setattr(
        "scripts.dispatch.task_sync.complete_task_for_todo",
        lambda state_dir, filename: calls.append(filename) or True,
    )

    resp = bridge.handle_card_action(
        _card_action({"action": "todo_done", "note": "todo-x.md"})
    )

    assert resp["toast"]["type"] == "success"
    assert calls == ["todo-x.md"]


def test_todo_done_task_hook_failure_still_succeeds(memory_tree, monkeypatch):
    """任务回写抛异常不影响回调成功（只 log）。"""
    bridge = _bridge(memory_tree)
    memory_tree.create_note("todo-y.md", "# t\n\n- [ ] 做事\n", source="todo", tags=["待办"])

    def _boom(state_dir, filename):
        raise RuntimeError("api down")

    monkeypatch.setattr(
        "scripts.dispatch.task_sync.complete_task_for_todo", _boom
    )
    resp = bridge.handle_card_action(
        _card_action({"action": "todo_done", "note": "todo-y.md"})
    )
    assert resp["toast"]["type"] == "success"


def test_foreign_sender_message_ignored(memory_tree):
    """已识别主人后：其他人的消息不捕获（登记 seen 防重投）。"""
    from scripts.dispatch.task_sync import record_user_open_id

    record_user_open_id(memory_tree.state_dir, "ou_owner")
    bridge = _bridge(memory_tree)
    event = _event("m-foreign", "text", {"text": "陌生人的消息"})
    event.event.sender = SimpleNamespace(
        sender_id=SimpleNamespace(open_id="ou_stranger")
    )
    bridge.handle_event(event)

    assert not list(memory_tree.notes_dir.glob("feishu-*.md"))


def test_owner_sender_message_accepted(memory_tree):
    """主人本人的消息照常捕获。"""
    from scripts.dispatch.task_sync import record_user_open_id

    record_user_open_id(memory_tree.state_dir, "ou_owner")
    bridge = _bridge(memory_tree)
    event = _event("m-owner", "text", {"text": "主人的消息"})
    event.event.sender = SimpleNamespace(
        sender_id=SimpleNamespace(open_id="ou_owner")
    )
    bridge.handle_event(event)

    assert len(list(memory_tree.notes_dir.glob(f"{_today()}.md"))) == 1


def test_foreign_operator_action_ignored(memory_tree):
    """已识别主人后：其他人点按钮不生效（笔记标签原样保留）。"""
    from scripts.dispatch.task_sync import record_user_open_id

    record_user_open_id(memory_tree.state_dir, "ou_owner")
    bridge = _bridge(memory_tree)
    memory_tree.create_note("x.md", "正文\n", source="link", tags=["待确认"])
    event = _card_action({"action": "confirm_note", "note": "x.md"})
    event.event.operator = SimpleNamespace(open_id="ou_stranger")

    resp = bridge.handle_card_action(event)

    assert resp == {}
    post = frontmatter.loads(
        (memory_tree.notes_dir / "x.md").read_text(encoding="utf-8")
    )
    assert "待确认" in post.metadata["tags"]


def test_owner_operator_action_accepted(memory_tree):
    """主人本人点按钮照常生效。"""
    from scripts.dispatch.task_sync import record_user_open_id

    record_user_open_id(memory_tree.state_dir, "ou_owner")
    bridge = _bridge(memory_tree)
    memory_tree.create_note("y.md", "正文\n", source="link", tags=["待确认"])
    event = _card_action({"action": "confirm_note", "note": "y.md"})
    event.event.operator = SimpleNamespace(open_id="ou_owner")

    resp = bridge.handle_card_action(event)

    assert resp["toast"]["type"] == "success"


def test_resource_download_failure_sends_feedback(memory_tree, monkeypatch):
    """附件下载失败（如飞书 234037 大视频超限）：回执用户原因与出路——
    2026-09-12 实测手机直出视频超限、飞书端毫无反馈。"""
    client = MagicMock()
    fail = client.im.v1.message_resource.get.return_value
    fail.success.return_value = False
    fail.code = 234037
    fail.msg = "Downloaded file size exceeds limit."
    _fake_lark(monkeypatch, client)
    feedback = []
    monkeypatch.setattr(
        FeishuBridge, "_send_feedback", lambda self, chat_id, text: feedback.append(text)
    )

    bridge = _bridge(memory_tree)
    bridge.handle_event(
        _event("m-big", "file", {"file_key": "fk-big", "file_name": "SVID_1.mp4"})
    )

    assert not (memory_tree.attachments_dir).exists()
    assert len(feedback) == 1
    assert "SVID_1.mp4" in feedback[0]
    assert "下载失败" in feedback[0]
    # 回执必须给两条出路（2026-09-13 升级）：发链接 + 电脑投递
    assert "发链接" in feedback[0]
    assert "attachments/媒体" in feedback[0]


def test_media_message_saved_as_mp4(memory_tree, monkeypatch):
    """飞书直发视频消息 msg_type=media（不是 file）：下载（资源 type=file）
    → 存 .mp4 进 attachments/媒体/ → 加 ✅ 表情回执。
    2026-09-13 实测：media 漏接分支导致小视频被静默吞掉。"""
    bridge = _bridge(memory_tree)
    downloads = []
    monkeypatch.setattr(
        bridge,
        "_download_resource",
        lambda mid, key, rtype: downloads.append((key, rtype)) or b"mp4blob",
    )
    reactions = []
    monkeypatch.setattr(
        bridge, "_add_reaction", lambda mid, **kw: reactions.append(mid)
    )

    bridge.handle_event(
        _event(
            "m-media-1",
            "media",
            {
                "file_key": "video_key",
                "image_key": "cover_key",
                "file_name": "clip.mp4",
                "duration": 12,
            },
        )
    )

    # 必须下载视频本体（file_key），不是封面图（image_key）——
    # 2026-09-13 实测：先取 image_key 会把 12KB 封面当视频存成假 mp4
    assert downloads == [("video_key", "file")]
    attach_dir = memory_tree.attachments_dir / "媒体"
    saved = list(attach_dir.glob("feishu-*.mp4"))
    assert len(saved) == 1
    assert "clip.mp4" in saved[0].name
    assert saved[0].read_bytes() == b"mp4blob"
    assert reactions == ["m-media-1"]


def test_media_message_without_filename_defaults_mp4(memory_tree, monkeypatch):
    """media 负载缺 file_name：兜底 .mp4 后缀（media 管线按后缀认视频）。"""
    bridge = _bridge(memory_tree)
    monkeypatch.setattr(
        bridge, "_download_resource", lambda mid, key, rtype: b"mp4blob"
    )
    monkeypatch.setattr(bridge, "_add_reaction", lambda mid, **kw: None)

    bridge.handle_event(
        _event("m-media-2", "media", {"file_key": "video_key", "duration": 5})
    )

    attach_dir = memory_tree.attachments_dir / "媒体"
    saved = list(attach_dir.glob("feishu-*.mp4"))
    assert len(saved) == 1


def _card_action_with_form(value: dict, form_value: dict):
    """带表单值的卡片回调（顺手记一句用）。"""
    return SimpleNamespace(
        event=SimpleNamespace(
            action=SimpleNamespace(value=value, form_value=form_value)
        )
    )


def test_discard_marks_pending_delete(memory_tree):
    """点「🗑 不要了」：只标 pending_delete，文件一字节不动。"""
    bridge = _bridge(memory_tree)
    memory_tree.create_note("junk.md", "正文\n", source="link", tags=["待确认"])
    path = memory_tree.notes_dir / "junk.md"
    before = path.read_bytes()

    resp = bridge.handle_card_action(
        _card_action({"action": "discard_note", "note": "junk.md"})
    )

    assert resp["toast"]["type"] == "success"
    assert memory_tree.is_pending_delete(path)
    assert path.read_bytes() == before  # 文件不动
    # 幂等：再点一次提示已在清单
    resp2 = bridge.handle_card_action(
        _card_action({"action": "discard_note", "note": "junk.md"})
    )
    assert resp2["toast"]["type"] == "info"


def test_discard_missing_note_errors(memory_tree):
    """待删目标不存在：toast 报错，不中断。"""
    bridge = _bridge(memory_tree)

    resp = bridge.handle_card_action(
        _card_action({"action": "discard_note", "note": "ghost.md"})
    )

    assert resp["toast"]["type"] == "error"


def test_confirm_card_has_discard_button(memory_tree):
    """确认卡按钮区含「🗑 不要了」（discard_note 回调）。"""
    from scripts.dispatch.feishu_io import _confirm_action_card

    card = _confirm_action_card("标题", "正文", "x.md")
    actions = card["elements"][1]["actions"]
    discard = [a for a in actions if a.get("type") == "danger"]
    assert len(discard) == 1
    assert discard[0]["behaviors"][0]["value"] == {
        "action": "discard_note",
        "note": "x.md",
    }


def test_note_remark_appends_line(memory_tree):
    """确认完成卡「💾 记下」：顺手一句追加到笔记末尾（原子写）。"""
    bridge = _bridge(memory_tree)
    memory_tree.create_note("n1.md", "正文\n", source="link", tags=["抖音"])
    path = memory_tree.notes_dir / "n1.md"

    resp = bridge.handle_card_action(
        _card_action_with_form(
            {"action": "note_remark", "note": "n1.md"},
            {"q1": "这条对我有用，下周试试"},
        )
    )

    assert resp["toast"]["type"] == "success"
    text = path.read_text(encoding="utf-8")
    assert "💭 顺手记一句" in text
    assert "这条对我有用，下周试试" in text
    assert text.startswith("---")  # frontmatter 未动


def test_note_remark_empty_noop(memory_tree):
    """空提交零成本：不动文件。"""
    bridge = _bridge(memory_tree)
    memory_tree.create_note("n2.md", "正文\n", source="link", tags=["抖音"])
    path = memory_tree.notes_dir / "n2.md"
    before = path.read_bytes()

    resp = bridge.handle_card_action(
        _card_action_with_form({"action": "note_remark", "note": "n2.md"}, {"q1": "  "})
    )

    assert resp["toast"]["type"] == "info"
    assert path.read_bytes() == before


def test_confirmed_with_remark_card_shape():
    """确认完成卡（schema 2.0）：含可空输入框 + 提交按钮（note_remark）。"""
    from scripts.dispatch.feishu_cards import confirmed_with_remark_card

    card = confirmed_with_remark_card("x.md", "已移除「待确认」标签")

    assert card["schema"] == "2.0"
    form = card["body"]["elements"][1]
    assert form["tag"] == "form"
    field = form["elements"][0]
    assert field["tag"] == "input" and field["required"] is False
    submit = form["elements"][1]
    assert submit["behaviors"][0]["value"] == {
        "action": "note_remark",
        "note": "x.md",
    }


def test_batch_archive_rebuilds_digest_card(memory_tree):
    """清单卡点一条「✅ 确认并归档」：整卡替换为**剩余条目**的清单卡——
    其余条目不消失（2026-09-13 真机实测缺陷：点一条整卡变完成卡）。"""
    bridge = _bridge(memory_tree)
    memory_tree.create_note("ma.md", "正文\n", source="media", tags=["待确认", "媒体"])
    memory_tree.create_note("mb.md", "正文\n", source="media", tags=["待确认", "媒体"])

    resp = bridge.handle_card_action(
        _card_action(
            {"action": "archive_note", "note": "ma.md", "batch": ["ma.md", "mb.md"]}
        )
    )

    assert resp["toast"]["type"] == "success"
    card = resp["card"]["data"]
    assert "1 条" in card["header"]["title"]["content"]
    texts = [
        el["text"]["content"]
        for el in card["elements"]
        if el["tag"] == "div"
    ]
    assert any("mb" in text for text in texts)  # 剩余条目还在
    assert not any("ma" in text and "💭" not in text for text in texts if "ma" in text)
    # ma.md 本身已归档
    assert (memory_tree.notes_dir / "媒体" / "ma.md").exists()


def test_batch_last_item_gets_remark_completion_card(memory_tree, monkeypatch):
    """批次点到最后一条：回调更新给 legacy 完成卡（schema 2.0 卡不能作
    回调返回值，平台报错——2026-09-13 真机实测），「顺手记一句」表单
    卡另发一条新消息（新消息路径已验证，与周回顾四问同路）。"""
    bridge = _bridge(memory_tree)
    memory_tree.create_note("only.md", "正文\n", source="media", tags=["待确认", "媒体"])
    sent = []
    monkeypatch.setattr(
        bridge, "_send_card", lambda chat_id, card: sent.append(card) or True
    )

    resp = bridge.handle_card_action(
        _card_action({"action": "archive_note", "note": "only.md", "batch": ["only.md"]})
    )

    card = resp["card"]["data"]
    assert card.get("schema") != "2.0"  # 回调更新是 legacy 完成卡
    assert card["elements"][0]["text"]["content"].startswith("only.md")
    # 表单卡另发新消息
    assert len(sent) == 1
    assert sent[0]["schema"] == "2.0"
    assert sent[0]["body"]["elements"][1]["tag"] == "form"


def test_batch_discard_rebuilds_digest_card(memory_tree):
    """清单卡点「🗑」：标记待删 + 重建剩余清单卡。"""
    bridge = _bridge(memory_tree)
    memory_tree.create_note("da.md", "正文\n", source="media", tags=["待确认", "媒体"])
    memory_tree.create_note("db.md", "正文\n", source="media", tags=["待确认", "媒体"])

    resp = bridge.handle_card_action(
        _card_action(
            {"action": "discard_note", "note": "da.md", "batch": ["da.md", "db.md"]}
        )
    )

    assert resp["toast"]["type"] == "success"
    assert memory_tree.is_pending_delete(memory_tree.notes_dir / "da.md")
    card = resp["card"]["data"]
    assert "1 条" in card["header"]["title"]["content"]


def test_note_remark_duplicate_skipped(memory_tree):
    """同一句话重复提交（客户端报错后重试/平台重发）：不追加第二遍。"""
    bridge = _bridge(memory_tree)
    memory_tree.create_note("n3.md", "正文\n", source="link", tags=["抖音"])
    path = memory_tree.notes_dir / "n3.md"
    action = _card_action_with_form(
        {"action": "note_remark", "note": "n3.md"}, {"q1": "同一句话"}
    )

    resp1 = bridge.handle_card_action(action)
    resp2 = bridge.handle_card_action(action)

    assert resp1["toast"]["type"] == "success"
    assert resp2["toast"]["type"] == "info"
    assert path.read_text(encoding="utf-8").count("同一句话") == 1


def test_todo_done_moves_from_inbox_to_todo_dir(memory_tree, monkeypatch):
    """点「✅ 已完成」：inbox 里的待办摘标签 + 收进 memory/待办/（2026-09-14
    审计裁决）；不在 inbox 的（人手动挪过）只摘标签不移动。"""
    # inbox 里的待办：摘标签 + 移动
    memory_tree.create_note(
        "todo-in.md", "---\ntitle: 收件箱里的待办\n---\n行动\n",
        source="todo", tags=["待办"], inbox=True,
    )
    bridge = _bridge(memory_tree)
    monkeypatch.setattr(bridge, "_send_feedback", lambda chat, text: None)

    resp = bridge.handle_card_action(_card_todo_done("todo-in.md"))

    assert resp["toast"]["type"] == "success"
    moved = memory_tree.notes_dir / "待办" / "todo-in.md"
    assert moved.exists()
    assert not (memory_tree.inbox_dir / "todo-in.md").exists()
    assert "待办" not in frontmatter.loads(moved.read_text(encoding="utf-8")).get("tags", [])

    # memory/ 根层（人已挪过/旧布局）：只摘标签不移动
    memory_tree.create_note(
        "todo-root.md", "---\ntitle: 根层待办\n---\n行动\n",
        source="todo", tags=["待办"],
    )
    resp2 = bridge.handle_card_action(_card_todo_done("todo-root.md"))
    assert resp2["toast"]["type"] == "success"
    assert (memory_tree.notes_dir / "todo-root.md").exists()
    assert not (memory_tree.notes_dir / "待办" / "todo-root.md").exists()


def test_todo_batch_card_shape_and_done_rebuild(memory_tree, monkeypatch):
    """批量待办卡（2026-09-15 裁决）：多条一卡；点完成一条→重建剩余。"""
    from scripts.dispatch.feishu_cards import todo_batch_card

    card = todo_batch_card([
        {"filename": "todo-a.md", "title": "任务甲"},
        {"filename": "todo-b.md", "title": "任务乙"},
    ])
    assert card["header"]["title"]["content"] == "Atelierr 新待办 2 条"
    text = json.dumps(card, ensure_ascii=False)
    assert "任务甲" in text and "任务乙" in text
    # 每个完成按钮回调带 batch（供重建）
    for element in card["elements"]:
        if element.get("tag") != "action":
            continue
        for action in element["actions"]:
            if action.get("behaviors"):
                assert action["behaviors"][0]["value"]["batch"] == ["todo-a.md", "todo-b.md"]

    # 点掉任务甲 → 桥重建剩余（任务乙），任务甲从视图消失
    memory_tree.create_note(
        "todo-a.md", "---\ntitle: 任务甲\n---\n- [ ] 任务甲\n",
        source="todo", tags=["待办"], inbox=True,
    )
    memory_tree.create_note(
        "todo-b.md", "---\ntitle: 任务乙\n---\n- [ ] 任务乙\n",
        source="todo", tags=["待办"], inbox=True,
    )
    bridge = _bridge(memory_tree)
    monkeypatch.setattr(bridge, "_send_feedback", lambda chat, text: None)

    resp = bridge.handle_card_action(
        _card_action(
            {"action": "todo_done", "note": "todo-a.md",
             "batch": ["todo-a.md", "todo-b.md"]}
        )
    )

    assert resp["toast"]["type"] == "success"
    rebuilt = resp["card"]["data"]
    assert rebuilt["header"]["title"]["content"] == "Atelierr 新待办 1 条"
    rebuilt_text = json.dumps(rebuilt, ensure_ascii=False)
    assert "任务乙" in rebuilt_text and "任务甲" not in rebuilt_text
    # 完成的待办已收进 待办/（与归档规则闭环）
    assert (memory_tree.notes_dir / "待办" / "todo-a.md").exists()
