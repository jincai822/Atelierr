"""飞书机器人桥单元测试（lark SDK 全部打桩，无真实网络）。

事件解析、幂等登记、附件落盘、卡片发送与降级均为真实代码路径；
lark_oapi 模块经 monkeypatch 替换为内存假实现。
"""

from __future__ import annotations

import io
import json
from types import SimpleNamespace
from unittest.mock import MagicMock

import frontmatter
import pytest

import scripts.dispatch.feishu as feishu_module
from scripts.dispatch.feishu import FeishuBridge, send_feishu


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
    """把 lark_oapi 换成假模块：所有 builder 链自动成立。"""
    fake_lark = MagicMock()
    fake_lark.Client.builder.return_value.app_id.return_value.app_secret.return_value.build.return_value = (
        client
    )
    monkeypatch.setattr(feishu_module, "_import_lark", lambda: fake_lark)
    return fake_lark


def test_text_message_creates_lark_note(memory_tree, capsys):
    """文本消息 → memory/ 笔记：source=lark、正文原样、sidecar 登记。"""
    bridge = _bridge(memory_tree)
    event = _event("m1", "text", {"text": "今天想到：\n好点子"})
    event.event.message.chat_id = "oc_demo_chat"
    bridge.handle_event(event)

    notes = list(memory_tree.notes_dir.glob("feishu-*.md"))
    assert len(notes) == 1
    text = notes[0].read_text(encoding="utf-8")
    assert "source: lark" in text
    assert "好点子" in text
    index_text = (memory_tree.state_dir / "index.json").read_text(encoding="utf-8")
    assert notes[0].stem in index_text
    # 日志带 chat_id（供用户抄进 FEISHU_CHAT_ID）
    assert "chat=oc_demo_chat" in capsys.readouterr().out


def test_text_with_url_kept_verbatim(memory_tree):
    """含 URL 的消息正文原样保留（links 分发下一轮自动捡起）。"""
    bridge = _bridge(memory_tree)
    bridge.handle_event(_event("m2", "text", {"text": "看这个 https://v.douyin.com/abc/"}))

    notes = list(memory_tree.notes_dir.glob("feishu-*.md"))
    assert len(notes) == 1
    assert "https://v.douyin.com/abc/" in notes[0].read_text(encoding="utf-8")


def test_duplicate_message_id_skipped(memory_tree):
    """同一 message_id 重复投递：只建一条笔记。"""
    bridge = _bridge(memory_tree)
    event = _event("m3", "text", {"text": "重复投递"})
    bridge.handle_event(event)
    bridge.handle_event(event)

    assert len(list(memory_tree.notes_dir.glob("feishu-*.md"))) == 1


def test_empty_text_ignored(memory_tree):
    """空白文本：不建笔记（但仍登记防重试风暴）。"""
    bridge = _bridge(memory_tree)
    bridge.handle_event(_event("m4", "text", {"text": "  "}))
    bridge.handle_event(_event("m4", "text", {"text": "  "}))

    assert not list(memory_tree.notes_dir.glob("feishu-*.md"))


def test_malformed_event_skipped(memory_tree):
    """损坏事件（缺字段/坏 JSON）：跳过不抛异常。"""
    bridge = _bridge(memory_tree)
    bridge.handle_event(SimpleNamespace(event=SimpleNamespace()))
    bridge.handle_event(
        _event("m5", "text", {})  # content JSON 里没有 text 字段
    )
    bridge.handle_event(SimpleNamespace(event=None))

    assert not list(memory_tree.notes_dir.glob("feishu-*.md"))


def test_image_message_saved_to_attachments(memory_tree, monkeypatch):
    """图片消息：下载二进制进 attachments/，media 分发可接手。"""
    client = MagicMock()
    resp = client.im.v1.message_resource.get.return_value
    resp.success.return_value = True
    resp.file = io.BytesIO(b"\x89PNG fake")
    _fake_lark(monkeypatch, client)

    bridge = _bridge(memory_tree)
    bridge.handle_event(_event("m6", "image", {"image_key": "img_v3_1"}))

    files = list((memory_tree.notes_dir / "attachments").glob("feishu-*.png"))
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

    files = list((memory_tree.notes_dir / "attachments").glob("feishu-*.pdf"))
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

    assert not (memory_tree.notes_dir / "attachments").exists()


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
        lambda t, m: calls.append(("feishu", t)) or False,
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
    """带 confirm_note 的卡片：追加「✅ 确认」「📁 确认并归档」两 callback 按钮。"""
    monkeypatch.setenv("FEISHU_APP_ID", "cli_x")
    monkeypatch.setenv("FEISHU_APP_SECRET", "secret")
    monkeypatch.setenv("FEISHU_CHAT_ID", "oc_chat")
    sent = []
    _fake_lark(monkeypatch, MagicMock())
    monkeypatch.setattr(
        feishu_module,
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
    assert [a["text"]["content"] for a in actions] == [
        "在 Obsidian 中打开",
        "✅ 确认",
        "📁 确认并归档",
    ]
    for button in actions[1:]:
        behavior = button["behaviors"][0]
        assert behavior["type"] == "callback"
        # value 必须是 dict 而非 JSON 字符串：平台回传字符串会被 SDK 校验丢弃
        assert isinstance(behavior["value"], dict)
    assert actions[1]["behaviors"][0]["value"] == {
        "action": feishu_module.CONFIRM_ACTION,
        "note": "douyin-x.md",
    }
    assert actions[2]["behaviors"][0]["value"] == {
        "action": feishu_module.ARCHIVE_ACTION,
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
        ("Atelierr 链接笔记待确认", {"confirm_note": "douyin-x.md"})
    ]


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
    """source=lark → 飞书/；平台推不出（media 无平台标签）→ 媒体/。"""
    bridge = _bridge(memory_tree)
    memory_tree.create_note("fl-想法.md", "正文\n", source="lark", tags=["待确认"])
    memory_tree.create_note("ocr-截图.md", "正文\n", source="media", tags=["待确认", "截图"])

    resp = bridge.handle_card_action(_card_archive("fl-想法.md"))
    assert resp["toast"]["content"] == "已确认并归档到 飞书/"
    assert (memory_tree.notes_dir / "飞书" / "fl-想法.md").exists()

    resp = bridge.handle_card_action(_card_archive("ocr-截图.md"))
    assert resp["toast"]["content"] == "已确认并归档到 媒体/"
    assert (memory_tree.notes_dir / "媒体" / "ocr-截图.md").exists()


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
    """「在 Obsidian 中打开」缺省直达本条笔记（percent-encode + 库内路径）。"""
    monkeypatch.delenv("FEISHU_CONSOLE_URL", raising=False)
    monkeypatch.delenv("FEISHU_VAULT_NAME", raising=False)

    url = feishu_module._console_url("抖音-内核稳定 #标签.md")

    assert url.startswith("obsidian://open?vault=atelierr-data&file=memory%2F") or (
        "file=memory/" in url
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
    """自定义库名（手机端库根=memory/ 文件夹）：不带 memory/ 前缀。"""
    monkeypatch.delenv("FEISHU_CONSOLE_URL", raising=False)
    monkeypatch.delenv("FEISHU_NOTE_PREFIX", raising=False)
    monkeypatch.setenv("FEISHU_VAULT_NAME", "memory")

    url = feishu_module._console_url("抖音-x.md")

    assert "vault=memory" in url
    assert "file=%E6%8A%96" in url  # file 直接是笔记名（编码后），无前缀
    assert "memory%2F" not in url and "file=memory/" not in url


def test_console_url_note_prefix_env_override(monkeypatch):
    """FEISHU_NOTE_PREFIX 显式覆盖前缀（含覆盖为空串）。"""
    monkeypatch.delenv("FEISHU_CONSOLE_URL", raising=False)
    monkeypatch.delenv("FEISHU_VAULT_NAME", raising=False)
    monkeypatch.setenv("FEISHU_NOTE_PREFIX", "notes/")
    assert feishu_module._console_url("x.md").endswith("file=notes/x")
