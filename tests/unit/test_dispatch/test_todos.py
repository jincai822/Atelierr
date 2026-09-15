"""待办自动分发单元测试（无真实网络）。

LLM 调用 monkeypatch ``httpx.post``；显式通道（- [ ] / #todo）、
幂等、防自循环、熔断、pending_delete 跳过均为真实代码路径。
"""

from __future__ import annotations

import json

import frontmatter
import pytest

import scripts.dispatch.todos as todos_module
from scripts.dispatch.todos import TodoDispatcher


class _FakeLLMResponse:
    """假 httpx 响应：json 返回固定负载。"""

    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


def _todos_payload(todos):
    return {
        "choices": [
            {"message": {"content": json.dumps({"todos": todos}, ensure_ascii=False)}}
        ]
    }


@pytest.fixture(autouse=True)
def _no_llm_key(monkeypatch):
    """默认摘除 key 环境变量：需要 LLM 的用例用 llm_ok 显式打开。"""
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)


@pytest.fixture
def llm_ok(monkeypatch):
    """配好 key 环境变量 + 假 LLM 返回两条行动项，返回请求记录表。"""
    calls = []
    monkeypatch.setenv("DEEPSEEK_API_KEY", "fake-key")

    def _post(url, **kwargs):
        calls.append(kwargs["json"]["messages"][0]["content"])
        return _FakeLLMResponse(
            _todos_payload(
                [
                    {"text": "买牛奶", "due": "2026-09-05"},
                    {"text": "回邮件给张三", "due": None},
                ]
            )
        )

    monkeypatch.setattr(todos_module.httpx, "post", _post)
    return calls


def _read_note(tree, filename):
    # 待办卡落中转站（2026-09-13 拆分）
    return frontmatter.loads((tree._abs(filename)).read_text(encoding="utf-8"))


def _state(tree):
    return json.loads((tree.state_dir / "processed_todos.json").read_text())


def test_explicit_task_lines_create_todos(memory_tree):
    """- [ ] 任务行直转：不带待确认标签，含任务行与来源双链，源笔记不动。"""
    memory_tree.create_note(
        "daily.md", "随想\n\n- [ ] 买牛奶\n- [ ] 回邮件给张三\n", source="test"
    )

    report = TodoDispatcher(memory_tree).run()

    assert report["candidates"] == 2
    assert len(report["created"]) == 2
    created = _read_note(memory_tree, report["created"][0])
    assert created["tags"] == ["待办"]  # 显式通道：不带待确认
    assert created["source"] == "todo"
    assert "- [ ] 买牛奶" in created.content
    assert "> 来源：[[daily]]" in created.content
    assert memory_tree.read_note(memory_tree.notes_dir / "daily.md").startswith("随想")
    assert _state(memory_tree)["daily.md"]["status"] == "done"


def test_inline_todo_tag_creates_todo(memory_tree):
    """行内 #todo 标记：该行内容转待办（标记本身不进文本）。"""
    memory_tree.create_note("n.md", "明天记得买牛奶 #todo\n", source="test")

    report = TodoDispatcher(memory_tree).run()

    assert len(report["created"]) == 1
    created = _read_note(memory_tree, report["created"][0])
    assert "明天记得买牛奶" in created.content
    assert "#todo" not in created.content


def test_llm_path_creates_with_review_tag(memory_tree, llm_ok):
    """LLM 通道：产出带 待确认+待办 标签，due 进 Tasks 插件 📅 格式。"""
    memory_tree.create_note("idea.md", "今天想到几件事要做", source="test")

    report = TodoDispatcher(memory_tree).run()

    assert len(report["created"]) == 2
    first = _read_note(memory_tree, report["created"][0])
    assert first["tags"] == ["待办", "待确认"]
    assert "- [ ] 买牛奶 📅 2026-09-05" in first.content
    assert _state(memory_tree)["idea.md"]["llm_done"] is True


def test_mixed_note_both_channels(memory_tree, monkeypatch):
    """混合笔记：显式行直转（无待确认）+ LLM 补充判定其余内容（带待确认）。"""
    monkeypatch.setenv("DEEPSEEK_API_KEY", "fake-key")
    monkeypatch.setattr(
        todos_module.httpx,
        "post",
        lambda *a, **k: _FakeLLMResponse(
            _todos_payload([{"text": "周五前交报销单", "due": None}])
        ),
    )
    memory_tree.create_note(
        "daily.md", "- [ ] 买牛奶\n\n今天想到周五前得交报销了。\n", source="test"
    )

    report = TodoDispatcher(memory_tree).run()

    assert len(report["created"]) == 2
    notes = [_read_note(memory_tree, f) for f in report["created"]]
    explicit = next(n for n in notes if "买牛奶" in n.content)
    judged = next(n for n in notes if "周五前交报销单" in n.content)
    assert explicit["tags"] == ["待办"]
    assert judged["tags"] == ["待办", "待确认"]


def test_llm_empty_means_no_todo(memory_tree, monkeypatch):
    """LLM 判无行动项：不建笔记，状态 no-todo。"""
    monkeypatch.setenv("DEEPSEEK_API_KEY", "fake-key")
    monkeypatch.setattr(
        todos_module.httpx,
        "post",
        lambda *a, **k: _FakeLLMResponse(_todos_payload([])),
    )
    memory_tree.create_note("plain.md", "纯粹的感慨，没有行动", source="test")

    report = TodoDispatcher(memory_tree).run()

    assert report["created"] == []
    assert _state(memory_tree)["plain.md"]["status"] == "no-todo"


def test_llm_skipped_without_key(memory_tree, monkeypatch):
    """无 key：跳过且不记状态（补 key 后下轮自动补判）、不发请求。"""
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    called = []
    monkeypatch.setattr(
        todos_module.httpx, "post", lambda *a, **k: called.append(1) or None
    )
    memory_tree.create_note("plain.md", "一些没有显式标记的内容", source="test")

    report = TodoDispatcher(memory_tree).run()

    assert report["created"] == []
    assert not called
    assert not (memory_tree.state_dir / "processed_todos.json").exists() or (
        "plain.md" not in _state(memory_tree)
    )


def test_link_source_feeds_only_summary_sections(memory_tree, monkeypatch):
    """source=link 笔记：LLM 只收到摘要两节，转写全文不进 prompt。"""
    calls = []
    monkeypatch.setenv("DEEPSEEK_API_KEY", "fake-key")

    def _post(url, **kwargs):
        calls.append(kwargs["json"]["messages"][0]["content"])
        return _FakeLLMResponse(_todos_payload([]))

    monkeypatch.setattr(todos_module.httpx, "post", _post)
    memory_tree.create_note(
        "douyin-x.md",
        "# 标题\n\n> 来源：抖音\n\n## 观点总结\n\n要点在此。\n\n"
        "## 分观点论述\n\n1. 论述。\n\n## 转写全文\n\n转写原文不应进prompt\n",
        source="link",
        tags=["待确认", "抖音"],
    )

    TodoDispatcher(memory_tree).run()

    assert calls and "要点在此" in calls[0]
    assert "转写原文不应进prompt" not in calls[0]


def test_idempotent_unchanged(memory_tree):
    """内容未变：第二轮直接跳过，不重复建。"""
    memory_tree.create_note("daily.md", "- [ ] 买牛奶\n", source="test")
    dispatcher = TodoDispatcher(memory_tree)
    first = dispatcher.run()

    second = dispatcher.run()

    assert len(first["created"]) == 1
    assert second["created"] == []
    assert second["skipped"] >= 1


def test_edited_note_rejudged_without_duplicates(memory_tree):
    """日记追加新任务行后重判：旧任务靠文件名去重，只新建新任务。"""
    daily = memory_tree.notes_dir / "daily.md"
    memory_tree.create_note("daily.md", "- [ ] 买牛奶\n", source="test")
    dispatcher = TodoDispatcher(memory_tree)
    first = dispatcher.run()
    assert len(first["created"]) == 1

    with open(daily, "a", encoding="utf-8") as fh:
        fh.write("- [ ] 回邮件给张三\n")
    second = dispatcher.run()

    assert len(second["created"]) == 1
    new_note = _read_note(memory_tree, second["created"][0])
    assert "回邮件给张三" in new_note.content


def test_todo_tagged_notes_skipped(memory_tree, llm_ok):
    """带 待办 标签的笔记（含本模块产出）不扫描，防自循环。"""
    memory_tree.create_note(
        "todo-x.md", "- [ ] 已建立的待办\n", source="todo", tags=["待办"]
    )

    report = TodoDispatcher(memory_tree).run()

    assert report["created"] == []
    assert llm_ok == []


def test_highlights_checklist_skipped(memory_tree, llm_ok):
    """划重点清单（source: highlights）不喂显式通道也不喂 LLM：
    候选勾选框是知识向内容，整清单进待办是噪音。"""
    memory_tree.create_note(
        "划重点-x.md",
        "- [ ] **概念甲**（第 3 页）\n  - 内容：甲是什么\n",
        source="highlights",
        tags=["划重点"],
    )

    report = TodoDispatcher(memory_tree).run()

    assert report["created"] == []
    assert llm_ok == []


def test_pending_delete_skipped(memory_tree, make_note, llm_ok):
    """pending_delete 笔记不判定。"""
    from scripts.memory.decay import DecayManager

    make_note(memory_tree, filename="old.md", content="旧内容", idle_days=60)
    DecayManager(memory_tree).run()
    assert memory_tree.is_pending_delete(memory_tree.notes_dir / "old.md")

    report = TodoDispatcher(memory_tree).run()

    assert report["created"] == []
    assert llm_ok == []


def test_failure_retries_then_circuit_breaks(memory_tree, monkeypatch):
    """LLM 连续失败：3 次熔断，第 4 轮不再发请求。"""
    monkeypatch.setenv("DEEPSEEK_API_KEY", "fake-key")
    calls = []

    def _boom(*args, **kwargs):
        calls.append(1)
        raise RuntimeError("api down")

    monkeypatch.setattr(todos_module.httpx, "post", _boom)
    memory_tree.create_note("idea.md", "要做的事", source="test")
    dispatcher = TodoDispatcher(memory_tree)

    for _ in range(3):
        report = dispatcher.run()
        assert report["created"] == []
        assert len(report["failed"]) == 1

    assert _state(memory_tree)["idea.md"]["status"] == "failed"

    dispatcher.run()
    assert len(calls) == 3


def test_success_clears_stale_last_error(memory_tree, monkeypatch):
    """首次失败留下 last_error；重试成功后必须清除，避免误导排查。"""
    monkeypatch.setenv("DEEPSEEK_API_KEY", "fake-key")
    calls = []

    def _flaky(url, **kwargs):
        calls.append(1)
        if len(calls) == 1:
            raise json.JSONDecodeError("bad", "doc", 0)
        return _FakeLLMResponse(_todos_payload([]))

    monkeypatch.setattr(todos_module.httpx, "post", _flaky)
    memory_tree.create_note("idea.md", "一些想法", source="test")
    dispatcher = TodoDispatcher(memory_tree)

    dispatcher.run()
    assert _state(memory_tree)["idea.md"]["last_error"] == "JSONDecodeError"

    dispatcher.run()
    entry = _state(memory_tree)["idea.md"]
    assert entry["llm_done"] is True
    assert "last_error" not in entry


def test_dry_run_creates_nothing(memory_tree, llm_ok):
    """dry-run：不建笔记、不写状态、不发 LLM 请求。"""
    memory_tree.create_note("daily.md", "- [ ] 买牛奶\n", source="test")

    report = TodoDispatcher(memory_tree).run(dry_run=True)

    assert report["candidates"] == 2  # 1 条显式 + 1 次 LLM 预判
    assert report["created"] == []
    assert llm_ok == []
    assert not (memory_tree.state_dir / "processed_todos.json").exists()
    assert list(memory_tree.inbox_dir.glob("todo-*.md")) == []


def test_cli_todos_command(memory_tree, tmp_path):
    """CLI 层：--config 指定配置，成功 exit 0。"""
    memory_tree.create_note("daily.md", "- [ ] 买牛奶\n", source="test")
    config = tmp_path / "memory.yaml"
    config.write_text(
        f"memory:\n  root: {memory_tree.notes_dir}\n"
        f"  state_dir: {memory_tree.state_dir}\n",
        encoding="utf-8",
    )
    from scripts.cli.dispatch_cli import DispatchCLI

    code = DispatchCLI(config_path=str(config)).main(["todos"])

    assert code == 0
    assert list(memory_tree.inbox_dir.glob("todo-*.md"))


def test_douyin_link_summary_fed_as_context(memory_tree, monkeypatch):
    """正文含已处理抖音链接：链接笔记的摘要两节作为上下文进 prompt。"""
    calls = []
    monkeypatch.setenv("DEEPSEEK_API_KEY", "fake-key")

    def _post(url, **kwargs):
        calls.append(kwargs["json"]["messages"][0]["content"])
        return _FakeLLMResponse(_todos_payload([]))

    monkeypatch.setattr(todos_module.httpx, "post", _post)
    url = "https://v.douyin.com/eQOGBXJdlwQ/"
    memory_tree.create_note(
        "douyin-vid123.md",
        "# 标题\n\n## 观点总结\n\n叔本华唯意志论，两本书。\n\n## 转写全文\n\n原文\n",
        source="link",
        tags=["待确认", "抖音"],
    )
    memory_tree.create_note("daily.md", f"看看 {url} 我想看里面的书！", source="test")
    (memory_tree.state_dir / "processed_links.json").write_text(
        json.dumps({url: {"status": "done", "note": "douyin-vid123.md"}},
                   ensure_ascii=False),
        encoding="utf-8",
    )

    TodoDispatcher(memory_tree).run()

    prompt = next(c for c in calls if "我想看里面的书" in c)
    assert "链接内容摘要" in prompt
    assert "叔本华唯意志论，两本书。" in prompt


def test_fenced_json_tolerated(memory_tree, monkeypatch):
    """LLM 返回带 ```json 围栏的内容也能解析（真实遇到过）。"""
    monkeypatch.setenv("DEEPSEEK_API_KEY", "fake-key")
    fenced = {"choices": [{"message": {"content": '```json\n{"todos": []}\n```'}}]}
    monkeypatch.setattr(
        todos_module.httpx, "post", lambda *a, **k: _FakeLLMResponse(fenced)
    )
    memory_tree.create_note("plain.md", "没有行动的内容", source="test")

    report = TodoDispatcher(memory_tree).run()

    assert report["created"] == []
    assert report["failed"] == []
    assert _state(memory_tree)["plain.md"]["status"] == "no-todo"


def test_query_block_and_tag_syntax_not_extracted(memory_tree, monkeypatch):
    """Obsidian query 代码块与 tag:#todo 查询语法不触发显式通道。"""
    called = []
    monkeypatch.setenv("DEEPSEEK_API_KEY", "fake-key")
    monkeypatch.setattr(
        todos_module.httpx,
        "post",
        lambda *a, **k: called.append(1) or _FakeLLMResponse(_todos_payload([])),
    )
    memory_tree.create_note(
        "主页.md",
        "# 主页\n\n```query\ntag:#待办\n```\n\n```query\ntag:#待确认\n```\n",
        source="manual",
    )

    report = TodoDispatcher(memory_tree).run()

    assert report["created"] == []
    assert called  # 无显式命中才走 LLM，且 LLM 也判无
    assert _state(memory_tree)["主页.md"]["status"] == "no-todo"


def test_llm_item_overlapping_explicit_is_skipped(memory_tree, monkeypatch):
    """同篇笔记：LLM 项与显式项互为子串 → 只建显式那一条（不重复）。"""
    monkeypatch.setenv("DEEPSEEK_API_KEY", "fake-key")
    monkeypatch.setattr(
        todos_module.httpx,
        "post",
        lambda *a, **k: _FakeLLMResponse(
            _todos_payload([{"text": "给系统做体检", "due": None}])
        ),
    )
    memory_tree.create_note(
        "feishu-x.md", "- [ ] 测试任务：给系统做体检 📅 2026-09-12\n"
    )

    report = TodoDispatcher(memory_tree).run()

    assert len(report["created"]) == 1
    note = _read_note(memory_tree, report["created"][0])
    assert "测试任务：给系统做体检" in note.content
    assert "待确认" not in (note.metadata.get("tags") or [])


def test_llm_item_not_overlapping_still_created(memory_tree, monkeypatch):
    """LLM 项与显式项不重叠 → 两条都建（去重不误伤真实新意图）。"""
    monkeypatch.setenv("DEEPSEEK_API_KEY", "fake-key")
    monkeypatch.setattr(
        todos_module.httpx,
        "post",
        lambda *a, **k: _FakeLLMResponse(
            _todos_payload([{"text": "顺便把报告打印了", "due": None}])
        ),
    )
    memory_tree.create_note("feishu-y.md", "- [ ] 测试任务：给系统做体检\n")

    report = TodoDispatcher(memory_tree).run()

    assert len(report["created"]) == 2


def test_overlap_helper_edge_cases():
    """重叠判定：空串/标点差异/双向子串。"""
    from scripts.dispatch.todos import _norm_task_text, _overlaps_explicit

    assert _norm_task_text("给系统 做体检！") == "给系统做体检"
    assert _overlaps_explicit("给系统做体检", ["测试任务给系统做体检"])
    assert _overlaps_explicit("测试任务：给系统做体检", ["给系统做体检"])
    assert not _overlaps_explicit("打印报告", ["给系统做体检"])
    assert not _overlaps_explicit("", ["给系统做体检"])
    assert not _overlaps_explicit("给系统做体检", [])


def test_share_boilerplate_line_dropped_from_llm_input(memory_tree, monkeypatch):
    """平台分享样板行不进 LLM 输入（2026-09-12 真实样本：抖音口令
    「复制打开抖音，看看【农人老贾的作品】」被误提为待办「打开抖音
    看农人老贾的作品」）。"""
    calls = []
    monkeypatch.setenv("DEEPSEEK_API_KEY", "fake-key")

    def _post(url, **kwargs):
        calls.append(kwargs["json"]["messages"][0]["content"])
        return _FakeLLMResponse(_todos_payload([]))

    monkeypatch.setattr(todos_module.httpx, "post", _post)
    memory_tree.create_note(
        "2026-09-12.md",
        "- 20:15 9.46 复制打开抖音，看看【农人老贾的作品】  "
        "https://v.douyin.com/TTQnzBUpaaw/ HVl:/ V@L.Jv 10/23 :5pm\n",
        source="lark",
    )

    report = TodoDispatcher(memory_tree).run()

    assert report["created"] == []
    assert calls  # LLM 确实被调用了
    prompt = calls[-1]
    # 提示词本身带平台样板防御规则（含「复制打开抖音」字样），
    # 断言针对内容部分：样板与口令不得进内容
    content = prompt.split("笔记内容：", 1)[1]
    assert "复制打开抖音" not in content
    assert "HVl" not in content
    assert "农人老贾" not in content
    assert "平台分享模板文字" in prompt


def test_share_line_with_user_comment_keeps_comment():
    """分享行里用户自己的话保留（只剥样板段与口令尾）。"""
    from scripts.dispatch.todos import _strip_share_boilerplate

    body = (
        "- 20:15 这个讲得太好了 9.46 复制打开抖音，看看【农人老贾的作品】 "
        "https://v.douyin.com/TTQnzBUpaaw/ HVl:/\n"
        "明天记得还书\n"
        "笔记标题 https://xhslink.cn/o/abc 【小红书】里的笔记已备好，复制后快来~\n"
    )

    stripped = _strip_share_boilerplate(body)

    lines = stripped.splitlines()
    assert lines[0] == "这个讲得太好了"
    assert lines[1] == "明天记得还书"
    assert lines[2] == "笔记标题"


def test_pure_share_line_drops_to_empty():
    """纯分享行整体剥为空（时间前缀也剥掉），不再进 LLM。"""
    from scripts.dispatch.todos import _llm_input

    body = (
        "- 20:15 9.46 复制打开抖音，看看【农人老贾的作品】  "
        "https://v.douyin.com/TTQnzBUpaaw/ HVl:/ V@L.Jv 10/23 :5pm"
    )

    assert _llm_input(body, "lark") == ""


def test_notify_todos_batches_multiple(memory_tree, monkeypatch):
    """多条新待办合并一张批量卡；单条仍推单卡（2026-09-15 卡片管理裁决）。"""
    import scripts.cli.dispatch_cli as cli_module
    from scripts.dispatch import feishu_io

    sent = []
    monkeypatch.setattr(
        cli_module, "send_todo_feishu", lambda fn: sent.append(("single", fn))
    )
    monkeypatch.setattr(
        feishu_io,
        "send_feishu_card",
        lambda card, chat_id=None: sent.append(("batch", card)) or True,
    )
    monkeypatch.setattr(
        "scripts.dispatch.task_sync.create_task_for_todo", lambda *a, **k: None
    )
    for name, title in (("todo-a.md", "任务甲"), ("todo-b.md", "任务乙")):
        memory_tree.create_note(
            name, f"---\ntitle: {title}\n---\n- [ ] {title}\n",
            source="todo", tags=["待办"], inbox=True,
        )

    cli_module._notify_todos(["todo-a.md", "todo-b.md"], memory_tree)

    assert len(sent) == 1 and sent[0][0] == "batch"
    assert sent[0][1]["header"]["title"]["content"] == "Atelierr 新待办 2 条"

    sent.clear()
    cli_module._notify_todos(["todo-a.md"], memory_tree)
    assert sent == [("single", "todo-a.md")]


def test_prompt_carries_today_for_due_dates(memory_tree, llm_ok):
    """提示词注入当天日期（2026-09-15 实证：没基准日"明天"推算不出，
    due 必丢空）；LLM 返回的 due 渲染为 📅 行。"""
    from datetime import datetime as _dt

    memory_tree.create_note("daily2.md", "明天 把 B 站 dfmea 看完", source="test")

    report = TodoDispatcher(memory_tree).run()

    assert llm_ok, "LLM 未被调用"
    today = _dt.now().astimezone().strftime("%Y-%m-%d")
    assert f"今天日期 {today}" in llm_ok[0]
    created = _read_note(memory_tree, report["created"][0])
    assert "📅 2026-09-05" in created.content


def test_comment_echo_line_stripped_from_llm_input():
    """卡面「💬 我的评论」复读行不进待办判定（日记行已覆盖该意图；
    不剥会在日记与卡上各判一次，措辞不同哈希去重拦不住）。"""
    from scripts.dispatch.todos import _llm_input

    body = (
        "## 观点总结\n\n不错。\n\n"
        "> 💬 我的评论：明天把 DFMEA 看完\n\n"
        "## 转写全文\n\n正文还在。"
    )
    out = _llm_input(body, "media")
    assert "明天把 DFMEA 看完" not in out
    assert "正文还在" in out


def test_completed_todo_archive_not_rescanned(memory_tree):
    """待办/ 目录（已完成待办的归宿）不再扫描：摘掉待办标签的完成笔记
    里的任务行不重生（2026-09-15 实证：点 ✅ 完成后被显式通道重生）。"""
    done_dir = memory_tree.notes_dir / "待办"
    done_dir.mkdir()
    (done_dir / "todo-x.md").write_text(
        "---\ntags: []\n---\n- [ ] 看完某视频 📅 2026-09-16\n", encoding="utf-8"
    )

    report = TodoDispatcher(memory_tree).run()

    assert report["created"] == []
