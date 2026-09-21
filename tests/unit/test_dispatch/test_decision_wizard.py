"""飞书决策向导（dispatch/decision_wizard.py）单元测试。

LLM 一律 monkeypatch（无网络）；后台线程用假 Thread 同步执行。
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from scripts.dispatch import decision_wizard
from scripts.dispatch.prompt import PromptStore


class _InlineThread:
    """假 Thread：start() 同步执行（测试确定性）。"""

    def __init__(self, target, args=(), daemon=None):
        self._target, self._args = target, args

    def start(self):
        self._target(*self._args)


@pytest.fixture(autouse=True)
def _inline_threads(monkeypatch):
    monkeypatch.setattr(decision_wizard.threading, "Thread", _InlineThread)


@pytest.fixture
def _fake_llm(monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "fake-test-key")
    monkeypatch.setattr(
        decision_wizard, "_chat",
        lambda prompt, cfg: json.dumps({
            "domain": "Complicated（可分析）",
            "frameworks": ["辩证思考", "二阶后果"],
            "analysis": "正方一段。反方一段。共识：先小步试。",
            "hard_questions": ["q1", "q2", "q3", "q4"],
            "verdict": "defer",
            "verdict_reason": "信息不足",
        }),
    )


def _closed_session(store: PromptStore, topic="要不要换工作", answers=("A 和 B", "月底前", "怕后悔")):
    """造一个已关闭的 decision 会话终态。"""
    store.open(decision_wizard.KIND, decision_wizard.FRAMING_QUESTIONS)
    store.set_extra("topic", topic)
    for text in answers:
        store.append(text)
    return store.close()


def test_open_wizard(memory_tree):
    """开店：PromptStore 开 decision 会话、话题入 extra、引导文案带三问。"""
    store = PromptStore(Path(memory_tree.state_dir))

    reply = decision_wizard.open_wizard(store, "要不要换工作")

    data = store.load()
    assert data["kind"] == "decision" and data["topic"] == "要不要换工作"
    assert "选项" in reply and "什么时候必须定" in reply and "怕什么" in reply


def test_finish_wizard_analyzes_and_pushes(memory_tree, _fake_llm):
    """收摊：分析写 pending（stage=done）+ 推送含倾向与落盘指引。"""
    store = PromptStore(Path(memory_tree.state_dir))
    closed = _closed_session(store)
    sent = []

    decision_wizard.finish_wizard(memory_tree, closed, sent.append)

    pending = decision_wizard.load_pending(memory_tree)
    assert pending["stage"] == "done"
    assert pending["topic"] == "要不要换工作"
    assert pending["result"]["verdict"] == "defer"
    assert any("⏸ 倾向暂缓" in text and "回「存」落盘" in text for text in sent)


def test_store_command_writes_reflection(memory_tree, _fake_llm):
    """「存」：按车间模板落盘 reflections/，stage 转 stored。"""
    store = PromptStore(Path(memory_tree.state_dir))
    decision_wizard.finish_wizard(memory_tree, _closed_session(store), lambda t: None)
    sent = []

    consumed = decision_wizard.handle_pending_command(memory_tree, "存", sent.append)

    assert consumed is True
    files = list(
        (Path(memory_tree.notes_dir) / "wiki" / "reflections").glob(
            "*-decision-要不要换工作.md"
        )
    )
    assert len(files) == 1
    body = files[0].read_text(encoding="utf-8")
    assert "source: decision" in body
    assert "# Decision Journal" in body
    assert "## Options Considered" in body and "A 和 B" in body
    assert "Review Date" in body  # 90 天复盘
    assert "辩证思考" in body
    assert decision_wizard.load_pending(memory_tree)["stage"] == "stored"


def test_discard_command(memory_tree, _fake_llm):
    """「算了」：丢弃，不落盘。"""
    store = PromptStore(Path(memory_tree.state_dir))
    decision_wizard.finish_wizard(memory_tree, _closed_session(store), lambda t: None)
    sent = []

    consumed = decision_wizard.handle_pending_command(memory_tree, "算了", sent.append)

    assert consumed is True
    assert decision_wizard.load_pending(memory_tree)["stage"] == "discarded"
    assert not list((Path(memory_tree.notes_dir) / "wiki" / "reflections").rglob("*decision*"))


def test_llm_failure_marks_failed_and_retry_works(memory_tree, monkeypatch):
    """LLM 失败：stage=failed + 可见错误；「重试」重跑成功。"""
    monkeypatch.setenv("DEEPSEEK_API_KEY", "fake-test-key")

    def boom(prompt, cfg):
        raise RuntimeError("llm down")

    monkeypatch.setattr(decision_wizard, "_chat", boom)
    store = PromptStore(Path(memory_tree.state_dir))
    sent = []
    decision_wizard.finish_wizard(memory_tree, _closed_session(store), sent.append)

    pending = decision_wizard.load_pending(memory_tree)
    assert pending["stage"] == "failed"
    assert any("决策分析失败" in text and "重试" in text for text in sent)

    monkeypatch.setattr(
        decision_wizard, "_chat",
        lambda prompt, cfg: json.dumps({
            "domain": "Complex", "frameworks": ["事前验尸", "逆向思考"],
            "analysis": "重试后的分析", "hard_questions": ["q1", "q2", "q3", "q4"],
            "verdict": "proceed", "verdict_reason": "试就完了",
        }),
    )
    retried = []
    consumed = decision_wizard.handle_pending_command(memory_tree, "重试", retried.append)

    assert consumed is True
    assert decision_wizard.load_pending(memory_tree)["stage"] == "done"
    assert any("倾向行动" in text for text in retried)


def test_pending_commands_noop_without_pending(memory_tree):
    """无 pending：指令不截胡（「存」照常进日记捕获流程）。"""
    sent = []
    assert decision_wizard.handle_pending_command(memory_tree, "存", sent.append) is False
    assert sent == []


def test_stale_analyzing_treated_as_failed(memory_tree, monkeypatch):
    """analyzing 超 10 分钟（守护重启遗留）：按失败处理，可重试。"""
    monkeypatch.setenv("DEEPSEEK_API_KEY", "fake-test-key")
    store = PromptStore(Path(memory_tree.state_dir))
    closed = _closed_session(store)
    stale = (datetime.now() - timedelta(seconds=700)).isoformat()
    decision_wizard._save_pending(memory_tree, {
        "stage": "analyzing", "topic": closed["topic"],
        "answers": [a["text"] for a in closed["answers"]], "closed_at": stale,
    })
    monkeypatch.setattr(
        decision_wizard, "_chat",
        lambda prompt, cfg: json.dumps({
            "domain": "Clear", "frameworks": ["帕累托", "艾森豪威尔矩阵"],
            "analysis": "重跑分析", "hard_questions": ["q1", "q2", "q3", "q4"],
            "verdict": "proceed", "verdict_reason": "干",
        }),
    )
    sent = []

    consumed = decision_wizard.handle_pending_command(memory_tree, "重试", sent.append)

    assert consumed is True
    assert decision_wizard.load_pending(memory_tree)["stage"] == "done"
