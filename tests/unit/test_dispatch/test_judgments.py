"""判断直收通道单元测试（2026-09-16 回路三启用）。

覆盖：飞书前缀解析、Obsidian 行标记解析、类型判定、直收（字段纪律）、
重复防护、证据引用、库扫描幂等、晨报计数、飞书桥文本分支接线。
"""

from __future__ import annotations

import json
from datetime import datetime

from scripts.dispatch.judgments import (
    parse_feishu_judgment,
    parse_line,
    register_statement,
    registered_since,
    scan_vault,
)
from scripts.dispatch.feishu import FeishuBridge


# ---------- 解析 ----------


def test_parse_feishu_prefixes():
    """「判断：/记为判断：/#判断 」前缀剥离出陈述；普通消息为 None。"""
    assert parse_feishu_judgment("判断：每天早起对我有用") == "每天早起对我有用"
    assert parse_feishu_judgment("判断: 半角冒号也行") == "半角冒号也行"
    assert parse_feishu_judgment("记为判断：这本书值得一读") == "这本书值得一读"
    assert parse_feishu_judgment("#判断 带标签的写法") == "带标签的写法"
    assert parse_feishu_judgment("#判断：带标签加冒号") == "带标签加冒号"
    assert parse_feishu_judgment("普通消息") is None
    assert parse_feishu_judgment("判断：") is None
    assert parse_feishu_judgment("") is None


def test_parse_line_variants():
    """Obsidian 行内标记：裸行/列表行/带冒号都认；非标记行不认。"""
    assert parse_line("#判断 读书比刷视频值") == "读书比刷视频值"
    assert parse_line("- #判断 列表里的判断") == "列表里的判断"
    assert parse_line("#判断：带冒号") == "带冒号"
    assert parse_line("  #判断 前面有空格") == "前面有空格"
    assert parse_line("正文里提到#判断这个词不算") is None
    assert parse_line("#判断") is None
    assert parse_line("# todo 别的标签") is None


# ---------- 直收 ----------


def test_register_belief_defaults(memory_tree):
    """陈述句 → belief：active、缺省确信度 0.7、origin=manual、
    approval.source=human_assessment（用户显式标记=人已批准）。"""
    entry_id, msg = register_statement(memory_tree, "每天早起对我有用")

    assert entry_id
    assert "确信度 0.7" in msg
    cog_dir = memory_tree.notes_dir.parent / "memory" / "wiki" / "cognition"
    files = list(cog_dir.rglob("*.md"))
    assert len(files) == 1
    text = files[0].read_text(encoding="utf-8")
    assert "type: belief" in text
    assert "status: active" in text
    assert "certainty: 0.7" in text
    assert "kind: manual" in text
    assert "human_assessment" in text
    assert "每天早起对我有用" in text


def test_register_question_has_no_certainty(memory_tree):
    """疑问句 → question：open、省略 certainty（spec：question 必填省略）。"""
    entry_id, msg = register_statement(memory_tree, "这个方法到底有没有用？")

    assert entry_id
    assert "疑问" in msg
    cog_dir = memory_tree.notes_dir.parent / "memory" / "wiki" / "cognition"
    files = list(cog_dir.rglob("*.md"))
    assert len(files) == 1
    text = files[0].read_text(encoding="utf-8")
    assert "type: question" in text
    assert "status: open" in text
    assert "certainty" not in text


def test_register_duplicate_skipped(memory_tree):
    """同 statement 的活动条目已存在 → 不重复收，回执说明。"""
    register_statement(memory_tree, "重复的判断")
    entry_id, msg = register_statement(memory_tree, "重复的判断")

    assert entry_id is None
    assert "已有同内容条目" in msg
    cog_dir = memory_tree.notes_dir.parent / "memory" / "wiki" / "cognition"
    assert len(list(cog_dir.rglob("*.md"))) == 1


def test_register_with_memory_evidence(memory_tree):
    """Obsidian 通道：来源笔记作为 memory 证据（id+path+relation=context）。"""
    note = memory_tree.create_note("日记.md", "内容", source="manual")
    note_id = memory_tree._find_entry_id(note)
    entry_id, _ = register_statement(
        memory_tree,
        "带证据的判断",
        evidence_memory_id=(note_id, "日记.md"),
        origin_note="用户 #判断 标记（日记.md）",
    )

    assert entry_id
    cog_dir = memory_tree.notes_dir.parent / "memory" / "wiki" / "cognition"
    text = next(cog_dir.rglob("*.md")).read_text(encoding="utf-8")
    assert "kind: memory" in text
    assert "relation: context" in text
    assert note_id in text


# ---------- 库扫描 ----------


def test_scan_vault_registers_and_idempotent(memory_tree):
    """扫描 memory+inbox 的「#判断」行：直收 + 已见登记防重复；
    笔记文件字节不动（红线）。"""
    note = memory_tree.create_note(
        "日记.md", "今天不错\n#判断 扫描收的判断\n- #判断 列表里的\n", source="manual"
    )
    before = note.read_bytes()
    inbox_note = memory_tree.create_note(
        "卡.md", "#判断 inbox 里的也行", source="link", inbox=True
    )

    report = scan_vault(memory_tree)

    statements = [s for s, _ in report["registered"]]
    assert "扫描收的判断" in statements
    assert "列表里的" in statements
    assert "inbox 里的也行" in statements
    assert note.read_bytes() == before  # 笔记不改写
    assert inbox_note.read_bytes()  # inbox 文件也在

    second = scan_vault(memory_tree)
    assert second["registered"] == []
    assert second["seen_before"] == 3


def test_scan_vault_duplicate_counts(memory_tree):
    """扫描遇到登记处已有同 statement 时计入 duplicates（不重复建）。"""
    register_statement(memory_tree, "已有的判断")
    memory_tree.create_note("日记.md", "#判断 已有的判断", source="manual")

    report = scan_vault(memory_tree)

    assert report["registered"] == []
    assert report["duplicates"] == ["已有的判断"]
    cog_dir = memory_tree.notes_dir.parent / "memory" / "wiki" / "cognition"
    assert len(list(cog_dir.rglob("*.md"))) == 1


def test_registered_since_counts(memory_tree):
    """晨报计数：registered_since 按天统计已收条数。"""
    today = datetime.now().strftime("%Y-%m-%d")
    assert registered_since(memory_tree, today) == 0
    memory_tree.create_note("日记.md", "#判断 计数用", source="manual")
    scan_vault(memory_tree)
    assert registered_since(memory_tree, today) == 1
    assert registered_since(memory_tree, "1999-01-01") == 0


# ---------- 飞书桥接线 ----------


def _event(message_id: str, msg_type: str, content: dict):
    from types import SimpleNamespace

    return SimpleNamespace(
        event=SimpleNamespace(
            message=SimpleNamespace(
                message_id=message_id,
                message_type=msg_type,
                content=json.dumps(content),
            )
        )
    )


def test_feishu_judgment_prefix_registers_and_keeps_diary(
    memory_tree, monkeypatch
):
    """飞书「判断：」消息：直收登记处 + 照常追加日记 + 文字轻通知。"""
    bridge = FeishuBridge(memory_tree, app_id="cli_x", app_secret="secret")
    feedback = []
    monkeypatch.setattr(
        bridge, "_send_feedback", lambda chat_id, text: feedback.append(text)
    )
    event = _event("mj1", "text", {"text": "判断：飞书通道的判断"})
    event.event.message.chat_id = "oc_demo"

    bridge.handle_event(event)

    cog_dir = memory_tree.notes_dir.parent / "memory" / "wiki" / "cognition"
    files = list(cog_dir.rglob("*.md"))
    assert len(files) == 1
    assert "飞书通道的判断" in files[0].read_text(encoding="utf-8")
    today = datetime.now().strftime("%Y-%m-%d")
    diary = memory_tree.notes_dir / f"{today}.md"
    assert diary.exists()
    assert "判断：飞书通道的判断" in diary.read_text(encoding="utf-8")
    assert feedback and "已收进判断登记处" in feedback[0]


def test_feishu_normal_text_not_judgment(memory_tree, monkeypatch):
    """普通飞书文本：不进登记处，只追加日记。"""
    bridge = FeishuBridge(memory_tree, app_id="cli_x", app_secret="secret")
    monkeypatch.setattr(bridge, "_send_feedback", lambda chat_id, text: None)
    monkeypatch.setattr(bridge, "_add_reaction", lambda mid: None)
    event = _event("mn1", "text", {"text": "今天想到判断这个词"})
    event.event.message.chat_id = "oc_demo"

    bridge.handle_event(event)

    cog_dir = memory_tree.notes_dir.parent / "memory" / "wiki" / "cognition"
    assert not cog_dir.exists() or not list(cog_dir.rglob("*.md"))


def test_feishu_judgment_wins_over_open_session(memory_tree, monkeypatch):
    """周回顾会话期间回复「判断：xxx」：按登记指令处理（不进回答）。"""
    from pathlib import Path

    from scripts.dispatch.prompt import PromptStore

    store = PromptStore(Path(memory_tree.state_dir))
    store.open(kind="review-weekly", questions=["q1"])
    bridge = FeishuBridge(memory_tree, app_id="cli_x", app_secret="secret")
    monkeypatch.setattr(bridge, "_send_feedback", lambda chat_id, text: None)
    event = _event("mj2", "text", {"text": "判断：会话期间的判断"})
    event.event.message.chat_id = "oc_demo"

    bridge.handle_event(event)

    cog_dir = memory_tree.notes_dir.parent / "memory" / "wiki" / "cognition"
    assert len(list(cog_dir.rglob("*.md"))) == 1
    # 回答会话没被这条占用（仍是 0 条回答）
    assert store.load().get("answers", []) == []
