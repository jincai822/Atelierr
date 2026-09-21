"""晚间日记 enrichment（dispatch/enrich.py）单元测试。

LLM 一律 monkeypatch 掉（无网络）；覆盖三问追加、错别字批改、
幂等、安全闸与 mtime 还原纪律。
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

import pytest

from scripts.dispatch import enrich


@pytest.fixture(autouse=True)
def _fake_key(monkeypatch):
    """LLM 路径测试需要 key 过闸（_chat 已被 monkeypatch，不会真联网）。"""
    monkeypatch.setenv("DEEPSEEK_API_KEY", "fake-test-key")


def _make_diary(tree, day: str = "2026-09-21", lines=("- 08:30 今天和张三饭饭\n",)):
    """造当天日记并回拨 mtime（供 mtime 还原断言）。"""
    path = Path(tree.notes_dir) / "daily-notes" / day[:4] / day[5:7] / f"{day}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "---\ncreated: '2026-09-21T08:30:00+08:00'\nid: 01TEST\n"
        "source: lark\ntags: []\ntitle: '2026-09-21'\n---\n\n" + "".join(lines),
        encoding="utf-8",
    )
    old_ns = int((time.time() - 3600) * 1e9)
    os.utime(path, ns=(old_ns, old_ns))
    return path


def test_prompts_appended_and_mtime_restored(memory_tree, monkeypatch):
    """三问块追加到日记尾；mtime 还原（机器加工不算活跃）。"""
    diary = _make_diary(memory_tree)
    before = diary.stat().st_mtime_ns
    monkeypatch.setattr(
        enrich, "_chat",
        lambda prompt, cfg: json.dumps({"questions": ["问一", "问二", "问三"]}),
    )

    report = enrich.run_evening(memory_tree, today="2026-09-21")

    assert report["prompts"] is True
    body = diary.read_text(encoding="utf-8")
    assert "## 今日三问（2026-09-21）" in body
    assert "1. 问一" in body and "3. 问三" in body
    assert diary.stat().st_mtime_ns == before


def test_prompts_idempotent(memory_tree, monkeypatch):
    """一天一轮：第二次运行不再追加。"""
    diary = _make_diary(memory_tree)
    monkeypatch.setattr(
        enrich, "_chat",
        lambda prompt, cfg: json.dumps({"questions": ["问一", "问二", "问三"]}),
    )

    enrich.run_evening(memory_tree, today="2026-09-21")
    second = enrich.run_evening(memory_tree, today="2026-09-21")

    assert second["prompts"] is False
    assert diary.read_text(encoding="utf-8").count("## 今日三问") == 1


def test_typos_fixed_with_safety_gate(memory_tree, monkeypatch):
    """批改只接精确唯一的行；时间前缀丢了的修正不收。"""
    diary = _make_diary(
        memory_tree, lines=("- 08:30 今天和张三饭饭\n", "- 09:00 一切正常\n")
    )
    before = diary.stat().st_mtime_ns

    def fake_chat(prompt, cfg):
        if '"fixes"' in prompt:
            return json.dumps({"fixes": [
                {"old": "- 08:30 今天和张三饭饭", "new": "- 08:30 今天和张三吃饭"},
                {"old": "不存在的行", "new": "- 00:00 无效"},  # 对不上：放弃
                {"old": "- 09:00 一切正常", "new": "09:00 一切正常"},  # 丢前缀：不收
            ]})
        return json.dumps({"questions": ["问一", "问二", "问三"]})

    monkeypatch.setattr(enrich, "_chat", fake_chat)

    report = enrich.run_evening(memory_tree, today="2026-09-21")

    assert report["fixes"] == 1
    body = diary.read_text(encoding="utf-8")
    assert "- 08:30 今天和张三吃饭" in body
    assert "- 09:00 一切正常" in body  # 没被动
    assert diary.stat().st_mtime_ns == before

    # 幂等：当天第二轮不再批改
    second = enrich.run_evening(memory_tree, today="2026-09-21")
    assert second["fixes"] == 0


def test_no_diary_skips_without_marking(memory_tree):
    """无当天日记：跳过且不标完成（日记稍后出现仍可加工）。"""
    report = enrich.run_evening(memory_tree, today="2026-09-21")

    assert report["skipped"] == ["无当天日记"]
    assert not (memory_tree.state_dir / enrich.STATE_FILENAME).exists()


def test_no_api_key_skips(memory_tree, monkeypatch):
    """无 API key：跳过且不标完成。"""
    _make_diary(memory_tree)
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)

    report = enrich.run_evening(memory_tree, today="2026-09-21")

    assert report["skipped"] == ["无 API key"]
    assert not (memory_tree.state_dir / enrich.STATE_FILENAME).exists()


def test_llm_failure_not_marked(memory_tree, monkeypatch):
    """LLM 失败：不标完成，下一班次重试；不阻塞、不伪造输出。"""
    diary = _make_diary(memory_tree)

    def boom(prompt, cfg):
        raise RuntimeError("llm down")

    monkeypatch.setattr(enrich, "_chat", boom)

    report = enrich.run_evening(memory_tree, today="2026-09-21")

    assert report["prompts"] is False and report["fixes"] == 0
    assert "## 今日三问" not in diary.read_text(encoding="utf-8")
    assert not (memory_tree.state_dir / enrich.STATE_FILENAME).exists()
