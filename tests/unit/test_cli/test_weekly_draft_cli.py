"""weekly_draft_cli 单元测试（pi 与飞书推送全 mock，不烧 token）。

与真实 vault 的隔离方式同 test_confirm_cli：临时目录写 config，
经 ``--config`` 显式传入（不走 ATELIERR_CONFIG/默认配置的解析）。
"""

from __future__ import annotations

from pathlib import Path

import pytest
from click.testing import CliRunner

from scripts.cli import weekly_draft_cli
from scripts.cli.weekly_draft_cli import build_prompt, collect_excerpt, main


def _make_config(tmp_path):
    """临时配置（笔记目录 + 显式 state_dir），返回 (config_path, notes_dir)。"""
    config = tmp_path / "memory.yaml"
    config.write_text(
        f"memory:\n  root: {tmp_path}/memory\n  state_dir: {tmp_path}/state\n",
        encoding="utf-8",
    )
    (tmp_path / "memory" / "wiki" / "reflections").mkdir(parents=True)
    return config, tmp_path / "memory"


def test_build_prompt_pins_single_writable_file(tmp_path):
    """口令必须钉死唯一写入目标 + 只读约束 + 不问人。"""
    draft = tmp_path / "memory" / "wiki" / "reflections" / "2026-09-20-weekly-draft.md"
    prompt = build_prompt(draft, tmp_path)
    assert str(draft) in prompt
    assert "唯一允许写入" in prompt
    assert "绝不改写任何既有文件" in prompt
    assert "不问人" in prompt
    assert weekly_draft_cli.WEEKLY_SPEC in prompt
    assert "-weekly-draft.md" in prompt
    # 升华候选固定节（2026-09-21 脑科学评审：治「收而不化」）
    assert "升华候选" in prompt
    assert "只提名不执行提炼" in prompt
    # 传承做厚（2026-09-22 问题 3 裁决）：上岗先续前情
    assert "先续前情再动笔" in prompt
    assert "reflections/" in prompt


def test_collect_excerpt_skips_frontmatter(tmp_path):
    """摘要跳过 frontmatter 键值行，从正文标题开始，限量截断。"""
    note = tmp_path / "draft.md"
    note.write_text(
        "---\ntitle: 周回顾\ntags:\n- 反思\n---\n\n# 本周概览\n\n干了三件大事。\n",
        encoding="utf-8",
    )
    excerpt = collect_excerpt(note)
    assert "title:" not in excerpt
    assert "# 本周概览" in excerpt
    assert "干了三件大事。" in excerpt
    assert len(excerpt) <= 300


def test_collect_excerpt_missing_file_returns_empty(tmp_path):
    assert collect_excerpt(tmp_path / "nope.md") == ""


@pytest.fixture
def sent(monkeypatch):
    """拦截飞书/ntfy 推送。"""
    box = []
    monkeypatch.setattr(
        weekly_draft_cli, "_notify", lambda title, msg: box.append((title, msg))
    )
    return box


def test_main_success_pushes_excerpt(tmp_path, sent, monkeypatch):
    """pi 成功且初稿落盘 → 推成功通知，文案含文件名与摘要。"""
    config, notes_dir = _make_config(tmp_path)

    def fake_run(prompt, *, pi_bin, timeout=0):
        draft = Path(prompt.split("写入 ")[1].split("（")[0])
        draft.write_text("# 本周概览\n\n读完半本书。\n", encoding="utf-8")
        return True, str(draft)

    monkeypatch.setattr(weekly_draft_cli, "run_workshop", fake_run)
    result = CliRunner().invoke(main, ["--config", str(config)])
    assert result.exit_code == 0, result.output
    assert len(sent) == 1
    title, message = sent[0]
    assert "初稿已产出" in title
    assert "-weekly-draft.md" in message
    assert "读完半本书。" in message
    # 初稿落在临时 vault，真实 vault 零接触
    assert list((notes_dir / "wiki" / "reflections").glob("*-weekly-draft.md"))


def test_main_pi_failure_pushes_warning(tmp_path, sent, monkeypatch):
    """pi 失败 → 推失败通知，退出码 1。"""
    config, _notes_dir = _make_config(tmp_path)
    monkeypatch.setattr(
        weekly_draft_cli,
        "run_workshop",
        lambda prompt, *, pi_bin, timeout=0: (False, "pi 退出码 2: boom"),
    )
    result = CliRunner().invoke(main, ["--config", str(config)])
    assert result.exit_code == 1
    assert "班次失败" in sent[0][0]
    assert "boom" in sent[0][1]


def test_main_missing_draft_treated_as_failure(tmp_path, sent, monkeypatch):
    """pi 报成功但文件缺失 → 同样按失败推送（绝不静默）。"""
    config, _notes_dir = _make_config(tmp_path)
    monkeypatch.setattr(
        weekly_draft_cli,
        "run_workshop",
        lambda prompt, *, pi_bin, timeout=0: (True, "done"),
    )
    result = CliRunner().invoke(main, ["--config", str(config)])
    assert result.exit_code == 1
    assert "初稿文件缺失" in sent[0][1]


def test_main_stale_draft_same_day_treated_as_failure(tmp_path, sent, monkeypatch):
    """同日重跑、pi 报成功但没动文件（旧稿 mtime 未变）→ 按失败处理。"""
    import os
    import time
    from datetime import datetime

    config, notes_dir = _make_config(tmp_path)
    today = datetime.now().strftime("%Y-%m-%d")
    stale = notes_dir / "wiki" / "reflections" / f"{today}-weekly-draft.md"
    stale.write_text("# 旧稿\n", encoding="utf-8")
    old = time.time() - 3600
    os.utime(stale, (old, old))
    monkeypatch.setattr(
        weekly_draft_cli,
        "run_workshop",
        lambda prompt, *, pi_bin, timeout=0: (True, "done"),  # 不动文件
    )
    result = CliRunner().invoke(main, ["--config", str(config)])
    assert result.exit_code == 1
    assert "缺失/未更新" in sent[0][1]
    assert "班次失败" in sent[0][0]


def test_dry_run_prints_prompt_without_side_effects(tmp_path, sent):
    """--dry-run 只打印，不调 pi 不推送。"""
    config, _notes_dir = _make_config(tmp_path)
    result = CliRunner().invoke(main, ["--config", str(config), "--dry-run"])
    assert result.exit_code == 0
    assert "唯一允许写入" in result.output
    assert sent == []


def test_build_prompt_includes_kit(tmp_path):
    """口令含素材包指引（2026-09-22 系统级优化①）；无素材包不含该行。"""
    draft = tmp_path / "memory" / "wiki" / "reflections" / "2026-09-27-weekly-draft.md"
    kit = tmp_path / "state" / "weekly-kit-2026-09-27.md"
    prompt = build_prompt(draft, tmp_path, kit)
    assert str(kit) in prompt
    assert "素材包" in prompt
    assert "素材包" not in build_prompt(draft, tmp_path)


def test_build_weekly_kit(memory_tree):
    """素材包五节齐全（捕获统计/新入库/待办/最近反思/默写记录），落 state/。"""
    from scripts.cli.weekly_draft_cli import build_weekly_kit

    memory_tree.create_note("本周新笔记.md", "内容", source="test")
    kit = build_weekly_kit(memory_tree, "2026-09-27")

    assert kit.parent == memory_tree.state_dir
    body = kit.read_text(encoding="utf-8")
    assert "## 捕获统计" in body
    assert "## 新入库清单" in body
    assert "本周新笔记" in body
    assert "## 待办进行中" in body
    assert "## 最近反思" in body
    assert "## 本周默写记录" in body
