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


def test_parse_feishu_space_and_false_positives():
    """空格写法认（用户真实输入习惯）；「判断力/判断一下」正文不误命中。"""
    assert parse_feishu_judgment("判断  每天少吃一点，特别是晚上") == "每天少吃一点，特别是晚上"
    assert parse_feishu_judgment("记为判断 空格写法") == "空格写法"
    assert parse_feishu_judgment("判断力很重要") is None
    assert parse_feishu_judgment("判断一下这个") is None


# ---------- 机器提名（只提名不批准）+ 批量审批 + 晨报小节 ----------


def _note_with_viewpoints(tree, *, inbox=False, tags=None):
    """造一篇带观点总结的链接笔记（与生产格式一致）。"""
    content = (
        "---\ntitle: 测试链接\n---\n\n# 测试链接\n\n"
        "## 观点总结\n\n"
        "作者认为早起是效率的根基。\n\n"
        "## 分观点论述\n\n"
        "1. 早起让一天有掌控感。\n"
        "2. 晚起的人更容易焦虑。\n"
        "3. 睡眠时长比入睡时间更关键。\n\n"
        "## 转写全文\n\n原始转写。\n"
    )
    return tree.create_note(
        "链接-测试.md", content, source="link", inbox=inbox, tags=tags
    )


def test_split_viewpoints_prefers_numbered(memory_tree):
    from scripts.dispatch.judgments import _split_viewpoints

    note = _note_with_viewpoints(memory_tree)
    items = _split_viewpoints(note.read_text(encoding="utf-8"))
    assert items == [
        "早起让一天有掌控感。",
        "晚起的人更容易焦虑。",
        "睡眠时长比入睡时间更关键。",
    ]


def test_split_viewpoints_summary_fallback(memory_tree):
    from scripts.dispatch.judgments import _split_viewpoints

    note = memory_tree.create_note(
        "只有总结.md", "## 观点总结\n\n整段总结只有一个观点。\n\n## 转写全文\n\nx\n",
        source="link",
    )
    assert _split_viewpoints(note.read_text(encoding="utf-8")) == ["整段总结只有一个观点。"]


def test_nominate_from_note_creates_pending_proposals(memory_tree):
    from scripts.dispatch.judgments import nominate_from_note, pending_proposals

    note = _note_with_viewpoints(memory_tree)
    nominated = nominate_from_note(memory_tree, note)

    assert len(nominated) == 2  # 单篇上限 2 条
    pending = pending_proposals(memory_tree)
    assert [p["statement"] for p in pending] == [
        "早起让一天有掌控感。",
        "晚起的人更容易焦虑。",
    ]
    # cognition 目录里还没有正式条目（只提名不批准）
    cog_dir = memory_tree.notes_dir.parent / "memory" / "wiki" / "cognition"
    assert not cog_dir.exists() or not list(cog_dir.rglob("*.md"))


def test_nominate_dedupes_pending_and_existing(memory_tree):
    from scripts.dispatch.judgments import nominate_from_note

    register_statement(memory_tree, "早起让一天有掌控感。")
    note = _note_with_viewpoints(memory_tree)
    nominated = nominate_from_note(memory_tree, note)
    # 第 1 条已是活动条目跳过；第 2 条提名成功
    assert [s for _, s in nominated] == ["晚起的人更容易焦虑。"]
    # 再跑一遍：待批里的也跳过，不重复提名
    assert nominate_from_note(memory_tree, note) == []


def test_nominate_skips_notes_without_viewpoints(memory_tree):
    from scripts.dispatch.judgments import nominate_from_note

    note = memory_tree.create_note("日记.md", "今天天气好", source="manual")
    assert nominate_from_note(memory_tree, note) == []


class _NomLLMResponse:
    """假 httpx 响应：json 返回固定负载（机器提名 LLM 用）。"""

    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


def _nom_llm_payload(judgments):
    return {
        "choices": [
            {"message": {"content": json.dumps({"judgments": judgments}, ensure_ascii=False)}}
        ]
    }


def test_nominate_llm_path_prefers_grounded_judgments(memory_tree, monkeypatch):
    """有 key 时走 LLM 提炼：真判断留下，机械行不用；书名录类被 LLM 拒。"""
    import scripts.dispatch.judgments as judgments_module
    from scripts.dispatch.judgments import nominate_from_note

    monkeypatch.setenv("DEEPSEEK_API_KEY", "fake-key")
    monkeypatch.setattr(
        judgments_module.httpx,
        "post",
        lambda *a, **k: _NomLLMResponse(
            _nom_llm_payload(["早起是效率的根基。", "晚起的人更容易焦虑。"])
        ),
    )
    note = _note_with_viewpoints(memory_tree)
    nominated = nominate_from_note(memory_tree, note)

    assert [s for _, s in nominated] == ["早起是效率的根基。", "晚起的人更容易焦虑。"]


def test_nominate_llm_empty_means_no_nomination(memory_tree, monkeypatch):
    """LLM 判定观点节无合格判断 → 一条都不提（不退回机械摘录）。

    与 None（LLM 没上班，退回机械）严格区分：空表是质量闸门的结论。
    """
    import scripts.dispatch.judgments as judgments_module
    from scripts.dispatch.judgments import nominate_from_note

    monkeypatch.setenv("DEEPSEEK_API_KEY", "fake-key")
    monkeypatch.setattr(
        judgments_module.httpx,
        "post",
        lambda *a, **k: _NomLLMResponse(_nom_llm_payload([])),
    )
    note = _note_with_viewpoints(memory_tree)
    assert nominate_from_note(memory_tree, note) == []


def test_nominate_llm_ungrounded_falls_back_to_mechanical(memory_tree, monkeypatch):
    """LLM 候选全不落地（编造）→ 视同失败，退回机械摘录保底。"""
    import scripts.dispatch.judgments as judgments_module
    from scripts.dispatch.judgments import nominate_from_note

    monkeypatch.setenv("DEEPSEEK_API_KEY", "fake-key")
    monkeypatch.setattr(
        judgments_module.httpx,
        "post",
        lambda *a, **k: _NomLLMResponse(_nom_llm_payload(["量子波动速读改变命运。"])),
    )
    note = _note_with_viewpoints(memory_tree)
    nominated = nominate_from_note(memory_tree, note)

    assert [s for _, s in nominated] == ["早起让一天有掌控感。", "晚起的人更容易焦虑。"]


def test_nominate_llm_http_failure_falls_back(memory_tree, monkeypatch):
    """LLM 请求异常 → 退回机械摘录，不阻塞提名。"""
    import scripts.dispatch.judgments as judgments_module
    from scripts.dispatch.judgments import nominate_from_note

    monkeypatch.setenv("DEEPSEEK_API_KEY", "fake-key")

    def _boom(*a, **k):
        raise RuntimeError("network down")

    monkeypatch.setattr(judgments_module.httpx, "post", _boom)
    note = _note_with_viewpoints(memory_tree)
    nominated = nominate_from_note(memory_tree, note)

    assert len(nominated) == 2


def test_decide_by_index_accept_creates_entry(memory_tree):
    from scripts.dispatch.judgments import (
        decide_by_index, nominate_from_note, pending_proposals,
    )

    note = _note_with_viewpoints(memory_tree)
    nominate_from_note(memory_tree, note)

    ok, msg = decide_by_index(memory_tree, 1, accept=True)
    assert ok
    assert "已收进判断登记处" in msg
    # 条目已创建、提案已批、待批少一条
    cog_dir = memory_tree.notes_dir.parent / "memory" / "wiki" / "cognition"
    assert len(list(cog_dir.rglob("*.md"))) == 1
    text = next(cog_dir.rglob("*.md")).read_text(encoding="utf-8")
    assert "早起让一天有掌控感。" in text
    assert "human_approved_agent_assessment" in text
    assert len(pending_proposals(memory_tree)) == 1


def test_decide_by_index_reject_and_bad_index(memory_tree):
    from scripts.dispatch.judgments import (
        decide_by_index, nominate_from_note, pending_proposals,
    )

    note = _note_with_viewpoints(memory_tree)
    nominate_from_note(memory_tree, note)

    ok, msg = decide_by_index(memory_tree, 9, accept=True)
    assert not ok and "1..2" in msg
    ok, msg = decide_by_index(memory_tree, 1, accept=False)
    assert ok and "已略过" in msg
    assert len(pending_proposals(memory_tree)) == 1
    # 略过不建条目
    cog_dir = memory_tree.notes_dir.parent / "memory" / "wiki" / "cognition"
    assert not cog_dir.exists() or not list(cog_dir.rglob("*.md"))


def test_feishu_decide_command(memory_tree, monkeypatch):
    """飞书发「批 1」：待批第 1 条收进登记处并回执。"""
    from scripts.dispatch.judgments import nominate_from_note

    note = _note_with_viewpoints(memory_tree)
    nominate_from_note(memory_tree, note)
    bridge = FeishuBridge(memory_tree, app_id="cli_x", app_secret="secret")
    feedback = []
    monkeypatch.setattr(
        bridge, "_send_feedback", lambda chat_id, text: feedback.append(text)
    )
    event = _event("md1", "text", {"text": "批 1"})
    event.event.message.chat_id = "oc_demo"

    bridge.handle_event(event)

    assert feedback and "已收进判断登记处" in feedback[0]
    cog_dir = memory_tree.notes_dir.parent / "memory" / "wiki" / "cognition"
    assert len(list(cog_dir.rglob("*.md"))) == 1


def test_feishu_decide_multi_index_one_message(memory_tree, monkeypatch):
    """一条消息批多条（「批1批2」）：按序号从大到小裁决防位移——
    2026-09-17 实测「批 1」后「批 2」扑空（原 2 号已变 1 号）。"""
    from scripts.dispatch.judgments import nominate_from_note

    note = _note_with_viewpoints(memory_tree)
    nominated = nominate_from_note(memory_tree, note)
    assert len(nominated) == 2
    bridge = FeishuBridge(memory_tree, app_id="cli_x", app_secret="secret")
    feedback = []
    monkeypatch.setattr(
        bridge, "_send_feedback", lambda chat_id, text: feedback.append(text)
    )
    event = _event("md2", "text", {"text": "批1批2"})
    event.event.message.chat_id = "oc_demo"

    bridge.handle_event(event)

    assert feedback and feedback[0].count("已收进判断登记处") == 2
    cog_dir = memory_tree.notes_dir.parent / "memory" / "wiki" / "cognition"
    assert len(list(cog_dir.rglob("*.md"))) == 2


def test_feishu_decide_mixed_verdicts(memory_tree, monkeypatch):
    """「批 1、略 2」混合裁决：1 号收进登记处，2 号拒掉。"""
    from scripts.dispatch.judgments import nominate_from_note

    note = _note_with_viewpoints(memory_tree)
    nominate_from_note(memory_tree, note)
    bridge = FeishuBridge(memory_tree, app_id="cli_x", app_secret="secret")
    feedback = []
    monkeypatch.setattr(
        bridge, "_send_feedback", lambda chat_id, text: feedback.append(text)
    )
    event = _event("md3", "text", {"text": "批 1、略 2"})
    event.event.message.chat_id = "oc_demo"

    bridge.handle_event(event)

    assert feedback and "已收进判断登记处" in feedback[0] and "已略过" in feedback[0]
    cog_dir = memory_tree.notes_dir.parent / "memory" / "wiki" / "cognition"
    assert len(list(cog_dir.rglob("*.md"))) == 1


def test_confirm_hook_nominates(memory_tree, monkeypatch):
    """点 ✅ 确认带观点总结的笔记：顺手机器提名候选（只提名不批准）。"""
    note = _note_with_viewpoints(memory_tree, inbox=True, tags=["待确认"])
    bridge = FeishuBridge(memory_tree, app_id="cli_x", app_secret="secret")
    monkeypatch.setattr(bridge, "_send_feedback", lambda chat_id, text: None)
    monkeypatch.setattr(
        bridge, "_completion_card", lambda *a, **kw: {}
    )

    bridge._handle_confirm(note.name, "oc_demo")

    from scripts.dispatch.judgments import pending_proposals

    pending = pending_proposals(memory_tree)
    assert len(pending) == 2
    cog_dir = memory_tree.notes_dir.parent / "memory" / "wiki" / "cognition"
    assert not cog_dir.exists() or not list(cog_dir.rglob("*.md"))


def test_digest_quiet_section_renders(memory_tree):
    """晨报安静小节：有待批候选时列出编号清单与审批提示。"""
    from scripts.dispatch.digest import DigestDispatcher

    report = DigestDispatcher(memory_tree).run(
        dry_run=True,
        today="2099-01-01",
    )
    assert "判断候选" not in report["markdown"]  # 无候选不出现

    from scripts.dispatch.judgments import nominate_from_note

    note = _note_with_viewpoints(memory_tree)
    nominate_from_note(memory_tree, note)
    report = DigestDispatcher(memory_tree).run(dry_run=True, today="2099-01-01")
    md = report["markdown"]
    assert "## 🧭 判断候选（2）" in md
    assert "1. 早起让一天有掌控感。" in md
    assert "批 1" in md
    assert report["counts"]["judgment_proposals"] == 2


# ---------- 生命周期闭环（2026-09-19 backlog⑤：登记→复盘→销账） ----------


def _backdate_cognition_created(memory_tree, entry_id, days):
    """把 cognition 条目的 created 拨到 days 天前（测试复盘账龄用）。"""
    import re as _re
    from datetime import timedelta as _td
    from datetime import timezone as _tz

    cog_dir = memory_tree.notes_dir.parent / "memory" / "wiki" / "cognition"
    short = entry_id[-8:].lower()  # 文件名规则：<slug>--<id 末 8 位>.md
    path = next(p for p in cog_dir.rglob("*.md") if short in p.name)
    text = path.read_text(encoding="utf-8")
    old = (datetime.now(_tz.utc) - _td(days=days)).isoformat()
    path.write_text(
        _re.sub(r"^created:.*$", f"created: '{old}'", text, count=1, flags=_re.M),
        encoding="utf-8",
    )


def test_due_for_review_age_and_cooldown(memory_tree):
    """复盘到期：active belief 登记满 30 天到期；冷却 30 天内不重复。"""
    from scripts.dispatch.judgments import (
        due_for_review,
        mark_review_prompted,
        register_statement,
    )

    entry_id, _ = register_statement(memory_tree, "每天早起对我有用")
    assert due_for_review(memory_tree) == []  # 新登记不到期

    _backdate_cognition_created(memory_tree, entry_id, 31)
    due = due_for_review(memory_tree)
    assert [item["entry_id"] for item in due] == [entry_id]
    assert due[0]["entry_type"] == "belief" and due[0]["days"] >= 31

    mark_review_prompted(memory_tree, [entry_id])
    assert due_for_review(memory_tree) == []  # 冷却期不重复


def test_due_for_review_skips_non_active(memory_tree):
    """refuted 等非在研状态不到期；question 不走复盘（走 answer 闭环）。"""
    from scripts.dispatch.judgments import (
        apply_review_outcome,
        due_for_review,
        register_statement,
    )

    entry_id, _ = register_statement(memory_tree, "早睡早起身体好")
    _backdate_cognition_created(memory_tree, entry_id, 40)
    apply_review_outcome(memory_tree, entry_id, "not_true")  # → refuted
    assert due_for_review(memory_tree) == []

    qid, _ = register_statement(memory_tree, "这个方法到底有没有用？")
    _backdate_cognition_created(memory_tree, qid, 60)
    assert due_for_review(memory_tree) == []  # question 不参与


def test_apply_review_outcome_transitions(memory_tree):
    """销账迁移：belief 仍成立保持 active 留痕；不成立 → refuted；要调整 → questioned。"""
    from scripts.dispatch.judgments import (
        apply_review_outcome,
        register_statement,
        _manager,
    )

    bid, _ = register_statement(memory_tree, "运动让我更专注")
    ok, receipt = apply_review_outcome(memory_tree, bid, "still_true")
    assert ok and "还成立" in receipt
    assert _manager(memory_tree).get_entry(bid).status == "active"

    ok, receipt = apply_review_outcome(memory_tree, bid, "adjust")
    assert ok and "存疑" in receipt
    assert _manager(memory_tree).get_entry(bid).status == "questioned"

    ok, receipt = apply_review_outcome(memory_tree, bid, "not_true")
    assert ok and "销账" in receipt
    assert _manager(memory_tree).get_entry(bid).status == "refuted"

    ok, receipt = apply_review_outcome(memory_tree, bid, "bogus")
    assert not ok and "未知" in receipt


def test_apply_review_outcome_hypothesis_supported(memory_tree):
    """hypothesis 仍成立 → supported（销账进非默认列表）。"""
    from scripts.cognition.manager import ApprovalRecord, CognitionManager
    from scripts.dispatch.judgments import apply_review_outcome, _manager

    manager = CognitionManager(
        memory_tree.notes_dir.parent, state_dir=memory_tree.state_dir
    )
    entry = manager.create_entry(
        entry_type="hypothesis",
        title="假设测试",
        statement="每天冥想 10 分钟能降低焦虑",
        status="testing",
        certainty=0.5,
        evidence=[],
        approval=ApprovalRecord(action="create", reason="测试"),
    )
    ok, receipt = apply_review_outcome(memory_tree, str(entry.id), "still_true")
    assert ok
    assert _manager(memory_tree).get_entry(str(entry.id)).status == "supported"


def test_judgment_review_card_shape():
    """复盘卡（legacy）：三按钮带 entry+outcome（回调配 legacy 返回同规）。"""
    from scripts.dispatch.feishu_cards import judgment_review_card

    card = judgment_review_card("cog-abc123", "每天少吃一点", "belief", 31)

    assert card["header"]["template"] == "violet"
    assert "schema" not in card  # legacy（触发卡与回调返回同版本）
    actions = card["elements"][1]["actions"]
    assert [a["text"]["content"] for a in actions] == ["✅ 仍成立", "❌ 不成立", "🔧 要调整"]
    values = [a["behaviors"][0]["value"] for a in actions]
    assert values[0] == {"action": "judgment_review", "entry": "cog-abc123", "outcome": "still_true"}
    assert values[1]["outcome"] == "not_true" and values[2]["outcome"] == "adjust"


def test_feishu_judgment_review_handler(memory_tree, monkeypatch):
    """飞书复盘按钮：落账 + 回执 + legacy 完成卡（不中断守护）。"""
    from scripts.dispatch.judgments import register_statement, _manager

    entry_id, _ = register_statement(memory_tree, "每天早起对我有用")
    bridge = FeishuBridge.__new__(FeishuBridge)
    bridge.tree = memory_tree
    sent = []
    monkeypatch.setattr(
        bridge, "_send_feedback", lambda chat, text: sent.append(text)
    )

    action = type(
        "A",
        (),
        {
            "event": type(
                "E",
                (),
                {
                    "action": type(
                        "Act",
                        (),
                        {
                            "value": {
                                "action": "judgment_review",
                                "entry": entry_id,
                                "outcome": "not_true",
                            }
                        },
                    )(),
                    "context": {},
                    "operator": None,
                },
            )()
        },
    )()
    resp = bridge.handle_card_action(action)

    assert resp["toast"]["type"] == "success"
    assert resp["card"]["data"]["header"]["template"] == "green"
    assert "schema" not in resp["card"]["data"]  # legacy 触发配 legacy 返回
    assert _manager(memory_tree).get_entry(entry_id).status == "refuted"
    assert sent and "销账" in sent[-1]
