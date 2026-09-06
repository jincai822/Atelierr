"""文档健康月检单元测试（无真实 systemd/网络）。

run_checks 用临时目录树跑真实代码路径；main 的笔记创建/报告落盘/
dry-run 用 monkeypatch 隔离配置与推送。
"""

from __future__ import annotations

import frontmatter

import scripts.utils.doc_health as dh


def _make_repo(tmp_path):
    """搭一个最小但齐全的假仓库：三份文档 + 被引用路径。"""
    (tmp_path / "scripts" / "memory").mkdir(parents=True)
    (tmp_path / "scripts" / "memory" / "core.py").write_text("", encoding="utf-8")
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "memory.yaml").write_text(
        "memory:\n  root: x\n", encoding="utf-8"
    )
    for doc in dh.DOC_FILES:
        doc_path = tmp_path / doc
        doc_path.parent.mkdir(parents=True, exist_ok=True)
        doc_path.write_text("见 `scripts/memory/core.py` 与 `config/memory.yaml`。\n", encoding="utf-8")
    return tmp_path


def _make_ov(tmp_path, full=True):
    """搭假数据区（notes_dir 的父目录 = $OV）。"""
    ov = tmp_path / "ov"
    notes = ov / "memory"
    for rel in dh.DATA_DIRS:
        if not full and rel == "memory/wiki/_cognitive-os":
            continue
        (ov / rel).mkdir(parents=True, exist_ok=True)
    return notes


def _make_units(home, enabled_output="enabled"):
    unit_dir = home / ".config" / "systemd" / "user"
    unit_dir.mkdir(parents=True, exist_ok=True)
    for timer in dh.TIMERS:
        (unit_dir / timer).write_text("[Timer]\n", encoding="utf-8")


def test_clean_run_no_problems(tmp_path, monkeypatch):
    """目录/单元/引用/配置全齐：零异常。"""
    repo = _make_repo(tmp_path / "repo")
    notes = _make_ov(tmp_path)
    home = tmp_path / "home"
    _make_units(home)
    monkeypatch.setattr(dh, "_is_enabled", lambda _timer: True)

    problems, facts = dh.run_checks(repo, notes, home=home)

    assert problems == []
    assert any("_cognitive-os" in fact for fact in facts)
    assert any("atelierr-dochealth.timer" in fact for fact in facts)


def test_missing_data_dir_reported(tmp_path, monkeypatch):
    """_cognitive-os/ 缺失：报"数据区目录缺失"。"""
    repo = _make_repo(tmp_path / "repo")
    notes = _make_ov(tmp_path, full=False)
    home = tmp_path / "home"
    _make_units(home)
    monkeypatch.setattr(dh, "_is_enabled", lambda _timer: True)

    problems, _ = dh.run_checks(repo, notes, home=home)

    assert any("_cognitive-os" in problem for problem in problems)


def test_missing_timer_and_disabled_reported(tmp_path, monkeypatch):
    """单元缺失报缺失；在位但未 enable 报未 enable。"""
    repo = _make_repo(tmp_path / "repo")
    notes = _make_ov(tmp_path)
    home = tmp_path / "home"
    _make_units(home)
    (home / ".config" / "systemd" / "user" / "atelierr-decay.timer").unlink()
    monkeypatch.setattr(
        dh, "_is_enabled",
        lambda timer: False if timer == "atelierr-digest.timer" else True,
    )

    problems, _ = dh.run_checks(repo, notes, home=home)

    assert any("atelierr-decay.timer" in p and "缺失" in p for p in problems)
    assert any("atelierr-digest.timer" in p and "未 enable" in p for p in problems)


def test_missing_path_ref_reported(tmp_path):
    """文档引用了不存在的仓库路径：逐条报出。"""
    repo = _make_repo(tmp_path / "repo")
    notes = _make_ov(tmp_path)
    doc = repo / "DEVELOPMENT-PLAN-3MVP.md"
    doc.write_text("见 `scripts/memory/core.py` 和 `scripts/not/exist.py`。", encoding="utf-8")

    problems, _ = dh.run_checks(repo, notes, home=tmp_path / "home")

    assert any("scripts/not/exist.py" in problem for problem in problems)
    assert not any("scripts/memory/core.py" in problem for problem in problems)


def test_brace_notation_expanded(tmp_path):
    """花括号记法 scripts/{a,b} 展开逐一核验：不漏报也不误报。"""
    repo = _make_repo(tmp_path / "repo")
    notes = _make_ov(tmp_path)
    doc = repo / "DEVELOPMENT-PLAN-3MVP.md"
    doc.write_text("见 `scripts/{memory,notexist}`。", encoding="utf-8")

    problems, _ = dh.run_checks(repo, notes, home=tmp_path / "home")

    assert any("scripts/notexist" in problem for problem in problems)
    assert not any("scripts/memory" in problem for problem in problems)


def test_path_ref_strips_trailing_punct(tmp_path):
    """路径引用剥尾部中文标点与斜杠：不误报。"""
    repo = _make_repo(tmp_path / "repo")
    doc = repo / "DEVELOPMENT-PLAN-3MVP.md"
    doc.write_text("目录 `scripts/memory/`，配置 `config/memory.yaml`。", encoding="utf-8")

    refs = dh._extract_path_refs(doc)

    assert "scripts/memory" in refs
    assert "config/memory.yaml" in refs


def test_main_creates_note_only_on_problems(memory_tree, monkeypatch, tmp_path):
    """有异常：建"待确认"笔记 + 写报告 + 推送；无异常：零打扰。"""
    monkeypatch.setattr(dh, "resolve_config_path", lambda _path: None)
    # 用真实 memory_tree 替换 main 内部构造（避免触碰真实数据目录）
    monkeypatch.setattr(dh, "MemoryTree", lambda *_a, **_kw: memory_tree)
    pushed = []
    monkeypatch.setattr(dh, "send_dispatch_notice", lambda *a: pushed.append(a))

    # 场景 1：有异常 → 建笔记 + 推送 + 报告
    monkeypatch.setattr(
        dh, "run_checks",
        lambda *_a, **_kw: (["数据区目录缺失: /x/memory/wiki/_cognitive-os"], ["事实甲"]),
    )
    assert dh.main([]) == 0
    notes = list(memory_tree.notes_dir.glob("文档健康-*.md"))
    assert len(notes) == 1
    post = frontmatter.loads(notes[0].read_text(encoding="utf-8"))
    assert post["source"] == "doc-health"
    assert "待确认" in post["tags"]
    assert "数据区目录缺失" in post.content
    assert len(pushed) == 1
    assert len(list(memory_tree.state_dir.glob("reports/doc-health-*.md"))) == 1

    # 场景 2：同一天重复运行 → FileExistsError 兜底，不重复建
    assert dh.main([]) == 0
    assert len(list(memory_tree.notes_dir.glob("文档健康-*.md"))) == 1

    # 场景 3：无异常 → 不建笔记、不推送
    pushed.clear()
    monkeypatch.setattr(dh, "run_checks", lambda *_a, **_kw: ([], ["事实甲"]))
    assert dh.main([]) == 0
    assert pushed == []


def test_main_dry_run_writes_nothing(memory_tree, monkeypatch):
    """dry-run：不写报告、不建笔记。"""
    monkeypatch.setattr(dh, "resolve_config_path", lambda _path: None)
    monkeypatch.setattr(dh, "MemoryTree", lambda *_a, **_kw: memory_tree)
    monkeypatch.setattr(
        dh, "run_checks", lambda *_a, **_kw: (["异常甲"], ["事实甲"])
    )
    monkeypatch.setattr(dh, "send_dispatch_notice", lambda *a: None)

    assert dh.main(["--dry-run"]) == 0
    assert not list(memory_tree.notes_dir.glob("文档健康-*.md"))
    assert not list(memory_tree.state_dir.glob("reports/doc-health-*.md"))
