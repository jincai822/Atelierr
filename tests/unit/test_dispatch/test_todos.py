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
    return frontmatter.loads((tree.notes_dir / filename).read_text(encoding="utf-8"))


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


def test_dry_run_creates_nothing(memory_tree, llm_ok):
    """dry-run：不建笔记、不写状态、不发 LLM 请求。"""
    memory_tree.create_note("daily.md", "- [ ] 买牛奶\n", source="test")

    report = TodoDispatcher(memory_tree).run(dry_run=True)

    assert report["candidates"] == 2  # 1 条显式 + 1 次 LLM 预判
    assert report["created"] == []
    assert llm_ok == []
    assert not (memory_tree.state_dir / "processed_todos.json").exists()
    assert list(memory_tree.notes_dir.glob("todo-*.md")) == []


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
    assert list(memory_tree.notes_dir.glob("todo-*.md"))


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
