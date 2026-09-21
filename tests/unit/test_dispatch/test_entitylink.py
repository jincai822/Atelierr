"""实体反链（dispatch/entitylink.py）单元测试。

确定性匹配：无网络、无 LLM。
"""

from __future__ import annotations

from scripts.dispatch.entitylink import load_linkable_titles, wrap_entities


def test_wrap_exact_title(memory_tree):
    """逐字一致的片段包成 [[标题]]，其余不动。"""
    titles = ["叔本华"]
    assert (
        wrap_entities("今天读叔本华的书", titles) == "今天读[[叔本华]]的书"
    )


def test_wrap_longest_first(memory_tree):
    """长标题优先：不被短标题切碎。"""
    titles = ["叔本华", "叔本华哲学"]
    assert wrap_entities("聊叔本华哲学", titles) == "聊[[叔本华哲学]]"


def test_wrap_skips_already_linked(memory_tree):
    """已在 [[...]] 内的片段不重复包。"""
    assert wrap_entities("见 [[张三]] 吃饭", ["张三"]) == "见 [[张三]] 吃饭"


def test_wrap_skips_url_lines(memory_tree):
    """含 URL 的行整行不包（链接管线的行各有各的家）。"""
    text = "看这个 https://example.com 叔本华"
    assert wrap_entities(text, ["叔本华"]) == text


def test_wrap_no_hit_returns_original(memory_tree):
    """无命中 / 空标题集：原样返回。"""
    assert wrap_entities("今天天气好", ["叔本华"]) == "今天天气好"
    assert wrap_entities("今天天气好", []) == "今天天气好"


def test_wrap_multiple_occurrences(memory_tree):
    """同一标题出现多次，每处都包。"""
    assert (
        wrap_entities("张三来了，张三又走了", ["张三"])
        == "[[张三]]来了，[[张三]]又走了"
    )


def test_load_titles_wiki_and_people_only(memory_tree):
    """只收 wiki/ 与 people/ 的标题；frontmatter title 优先于 stem。"""
    memory_tree.create_note("a.md", "知识卡", source="test", tags=[])
    # 造目标层结构：create_note 只建根，手动迁入（同生产路径）
    for name, dirname in (("card.md", "wiki"), ("person.md", "people"), ("other.md", "work")):
        created = memory_tree.create_note(name, "内容", source="test")
        target = memory_tree.notes_dir / dirname / name
        target.parent.mkdir(parents=True, exist_ok=True)
        created.rename(target)
        note_id = memory_tree._read_note_id(target)
        if note_id is not None:
            memory_tree.relocate_entry(note_id, memory_tree._rel_key(target))

    titles = load_linkable_titles(memory_tree)

    assert titles == ["person", "card"]  # 长度降序；work/ 与根层笔记不收


def test_load_titles_filters_dates_and_short(memory_tree):
    """日期标题与单字标题不收。"""
    base = memory_tree.notes_dir / "wiki"
    base.mkdir(parents=True, exist_ok=True)
    (base / "2026-09-01.md").write_text(
        "---\ntitle: '2026-09-01'\n---\n\n日记\n", encoding="utf-8"
    )
    (base / "王.md").write_text("---\ntitle: 王\n---\n\n单字\n", encoding="utf-8")
    (base / "叔本华.md").write_text(
        "---\ntitle: 叔本华\n---\n\n哲学家\n", encoding="utf-8"
    )

    assert load_linkable_titles(memory_tree) == ["叔本华"]


def test_load_titles_excludes_cognition_and_reflections(memory_tree):
    """wiki/cognition 与 wiki/reflections 不是实体目标（2026-09-21 实测：
    判断登记与写日记同进程，不收会把刚登记的判断链成自链）。"""
    for rel, title in (
        ("wiki/cognition/j1.md", "一个判断"),
        ("wiki/reflections/r1.md", "一篇反思"),
        ("wiki/card.md", "知识卡"),
        ("distilled/topics/d1.md", "摘录卡"),
    ):
        path = memory_tree.notes_dir / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"---\ntitle: {title}\n---\n\n正文\n", encoding="utf-8")

    titles = load_linkable_titles(memory_tree)

    assert "知识卡" in titles and "摘录卡" in titles
    assert "一个判断" not in titles and "一篇反思" not in titles

