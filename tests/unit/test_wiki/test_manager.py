"""wiki 沉淀层管理器单元测试。

机器只读盘点 + 纪律校验，绝不改写任何笔记；全部在临时目录进行。
"""

from __future__ import annotations

from scripts.wiki.manager import WIKI_DIRNAME, WikiManager


def _write_wiki(tree, filename: str, meta: str, body: str = "正文"):
    """在 wiki/ 下造一条条目（手写 frontmatter + 正文）。"""
    wiki_dir = tree.notes_dir / WIKI_DIRNAME
    wiki_dir.mkdir(parents=True, exist_ok=True)
    path = wiki_dir / filename
    path.write_text(f"---\n{meta}\n---\n\n{body}\n", encoding="utf-8")
    return path


def _valid_meta(from_ref: str) -> str:
    return (
        f"created: '2026-09-01T09:00:00+08:00'\n"
        f"source: distilled\n"
        f"from: \"{from_ref}\""
    )


def test_entries_empty_when_dir_missing(memory_tree):
    """wiki/ 目录不存在：盘点返回空，不报错。"""
    manager = WikiManager(memory_tree)

    assert manager.entries() == []
    assert manager.validate() == []
    assert manager.orphans() == []
    assert manager.distilled_stems() == set()


def test_ensure_dir_creates_once(memory_tree):
    """ensure_dir 是机器唯一写动作：创建目录，幂等。"""
    manager = WikiManager(memory_tree)

    wiki_dir = manager.ensure_dir()

    assert wiki_dir == memory_tree.notes_dir / "wiki"
    assert wiki_dir.is_dir()
    assert manager.ensure_dir() == wiki_dir  # 再次调用无副作用


def test_entry_parses_frontmatter_and_links(memory_tree):
    """frontmatter 字段、from 归一化、正文 wikilink（别名/锚点）解析。"""
    memory_tree.create_note("src.md", "来源笔记", source="link")
    _write_wiki(
        memory_tree, "a.md", _valid_meta("[[src|别名]]"),
        body="关联 [[b|另一条]] 与 [[c#某节]]，以及 [[非wiki笔记]]",
    )

    (entry,) = WikiManager(memory_tree).entries()

    assert entry["stem"] == "a"
    assert entry["from"] == "src"
    assert entry["links"] == ["b", "c", "非wiki笔记"]
    assert entry["broken_frontmatter"] is False


def test_validate_happy_path(memory_tree):
    """两条互链、from 指向存在的 memory 笔记：零问题。"""
    memory_tree.create_note("src.md", "来源笔记", source="link")
    _write_wiki(memory_tree, "a.md", _valid_meta("[[src]]"), body="见 [[b]]")
    _write_wiki(memory_tree, "b.md", _valid_meta("src"), body="见 [[a]]")

    assert WikiManager(memory_tree).validate() == []


def test_validate_missing_frontmatter_fields(memory_tree):
    """缺 created/from：逐字段报出。"""
    memory_tree.create_note("x.md", "来源", source="link")
    _write_wiki(memory_tree, "a.md", "source: distilled", body="见 [[b]]")
    _write_wiki(
        memory_tree, "b.md", _valid_meta("[[x]]"), body="见 [[a]]"
    )

    problems = WikiManager(memory_tree).validate()

    assert len(problems) == 1
    assert problems[0]["stem"] == "a"
    assert any("created" in issue for issue in problems[0]["issues"])
    assert any("from" in issue for issue in problems[0]["issues"])


def test_validate_requires_wiki_outlink(memory_tree):
    """缺互链的三种形态都算违规：无链接/只链不存在的/只链自己。"""
    memory_tree.create_note("src.md", "来源", source="link")
    _write_wiki(memory_tree, "a.md", _valid_meta("[[src]]"), body="没链接")
    _write_wiki(memory_tree, "b.md", _valid_meta("[[src]]"), body="见 [[不存在]]")
    _write_wiki(memory_tree, "c.md", _valid_meta("[[src]]"), body="见 [[c]]")

    problems = WikiManager(memory_tree).validate()

    assert {p["stem"] for p in problems} == {"a", "b", "c"}
    for problem in problems:
        assert any("wikilink" in issue for issue in problem["issues"])


def test_validate_from_target_missing(memory_tree):
    """from 指向的 memory 笔记已被 purge：提示但不改写。"""
    _write_wiki(memory_tree, "a.md", _valid_meta("[[已删笔记]]"), body="见 [[b]]")
    _write_wiki(memory_tree, "b.md", _valid_meta("[[已删笔记]]"), body="见 [[a]]")

    problems = WikiManager(memory_tree).validate()

    assert len(problems) == 2
    assert any("不存在" in issue for issue in problems[0]["issues"])


def test_validate_from_unfilled(memory_tree):
    """from 写成空 wikilink（模板未填）：报"未填"。"""
    _write_wiki(memory_tree, "a.md", _valid_meta("[[]]"), body="见 [[b]]")
    _write_wiki(memory_tree, "b.md", _valid_meta("[[]]"), body="见 [[a]]")

    problems = WikiManager(memory_tree).validate()

    assert any("未填" in issue for issue in problems[0]["issues"])


def test_validate_broken_frontmatter(memory_tree):
    """frontmatter 损坏：报告，不崩溃，不改写。"""
    wiki_dir = memory_tree.notes_dir / WIKI_DIRNAME
    wiki_dir.mkdir(parents=True)
    (wiki_dir / "bad.md").write_text(
        "---\n: bad: [unclosed\n---\n\n正文 [[x]]\n", encoding="utf-8"
    )

    problems = WikiManager(memory_tree).validate()

    assert problems[0]["stem"] == "bad"
    assert "frontmatter 损坏" in problems[0]["issues"]


def test_orphans(memory_tree):
    """a 链接 b：b 非孤儿，a 是孤儿；自链不算入链。"""
    _write_wiki(memory_tree, "a.md", _valid_meta("[[s]]"), body="见 [[b]]")
    _write_wiki(memory_tree, "b.md", _valid_meta("[[s]]"), body="见 [[b]]")

    assert WikiManager(memory_tree).orphans() == ["a"]


def test_distilled_stems_and_stats(memory_tree):
    """distilled_stems 汇总所有 from；stats 四项计数。"""
    _write_wiki(memory_tree, "a.md", _valid_meta("[[src1]]"), body="见 [[b]]")
    _write_wiki(memory_tree, "b.md", _valid_meta("src2"), body="见 [[a]]")

    manager = WikiManager(memory_tree)

    assert manager.distilled_stems() == {"src1", "src2"}
    stats = manager.stats()
    assert stats["total"] == 2
    assert stats["orphans"] == 0
    assert stats["distilled_sources"] == 2
    assert stats["invalid"] == 2  # from 目标都不存在


def test_from_config_dirname_override(memory_tree, tmp_path):
    """memory.yaml 的 memory.wiki_dirname 可覆盖默认子目录名。"""
    config = tmp_path / "memory.yaml"
    config.write_text(
        f"memory:\n  root: {memory_tree.notes_dir}\n"
        f"  state_dir: {memory_tree.state_dir}\n"
        f"  wiki_dirname: kb\n",
        encoding="utf-8",
    )

    manager = WikiManager.from_config(str(config))

    assert manager.wiki_dir == memory_tree.notes_dir / "kb"


def test_subdir_rooms_invisible_to_wiki_manager(memory_tree):
    """同库分间（v1.1）：wiki/cognition/、wiki/reflections/ 子目录的
    文件不进 entries/validate/orphans/distilled_stems（各管各的房间）。"""
    _write_wiki(memory_tree, "a.md", _valid_meta("[[x]]"), body="见 [[b]]")
    for room in ("cognition", "reflections"):
        room_dir = memory_tree.notes_dir / WIKI_DIRNAME / room
        room_dir.mkdir(parents=True)
        (room_dir / "房间条目.md").write_text(
            "---\nno-frontmatter-contract: true\n---\n\n房间里随便写\n",
            encoding="utf-8",
        )

    manager = WikiManager(memory_tree)

    assert [e["stem"] for e in manager.entries()] == ["a"]
    assert manager.orphans() == ["a"]  # 房间文件不产生也不接收互链
    assert manager.distilled_stems() == {"x"}
    # a 缺 from 目标（x 不存在于 memory）→ 只有这一条问题，房间零误报
    problems = manager.validate()
    assert [p["stem"] for p in problems] == ["a"]
