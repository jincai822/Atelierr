"""wiki 机器自留地（curation）单元测试：index/log/主题页/到期复查。"""

from __future__ import annotations

import frontmatter

from scripts.wiki import curation


def _wiki(memory_tree):
    wiki_dir = memory_tree.notes_dir / "wiki"
    wiki_dir.mkdir(parents=True, exist_ok=True)
    return wiki_dir


def test_update_index_creates_okf_nav(memory_tree):
    """index.md：创建带 okf_version 声明；追加幂等。"""
    wiki = _wiki(memory_tree)
    curation.update_index(wiki, "卡一.md", "卡一", "简介一")
    text = (wiki / "index.md").read_text(encoding="utf-8")
    assert 'okf_version: "0.2"' in text
    assert "* [卡一](卡一.md) - 简介一" in text

    curation.update_index(wiki, "卡一.md", "卡一", "简介一")  # 幂等
    curation.update_index(wiki, "卡二.md", "卡二", "简介二")
    text = (wiki / "index.md").read_text(encoding="utf-8")
    assert text.count("卡一.md") == 1
    assert "* [卡二](卡二.md) - 简介二" in text


def test_append_log_same_day_single_section(memory_tree):
    """log.md：最新日期节在最上，同日追加不建新节。"""
    wiki = _wiki(memory_tree)
    curation.append_log(wiki, "卡一.md", "卡一")
    curation.append_log(wiki, "卡二.md", "卡二")
    text = (wiki / "log.md").read_text(encoding="utf-8")
    assert text.startswith("# Knowledge Update Log")
    assert text.count("**Creation**") == 2
    assert text.count("## 20") == 1  # 同日同一节


def test_topic_page_create_append_idempotent(memory_tree):
    """主题页：按中图法标签定主题；收录幂等；index 主题节计数更新。"""
    wiki = _wiki(memory_tree)
    path = curation.update_topic_page(
        wiki,
        card_stem="卡一",
        card_title="卡一",
        description="讲需求分解",
        tags=["C93-管理·领导", "质量管理"],
        llm=False,
    )
    assert path.name == "C93-管理·领导.md"
    assert path.parent.name == "topics"
    post = frontmatter.loads(path.read_text(encoding="utf-8"))
    assert post["type"] == "Topic"
    assert post["status"] == "stable"
    assert post["generated"]["by"] == "atelierr-wiki/1.0"
    assert "- [[卡一]] — 讲需求分解" in post.content

    curation.update_topic_page(  # 同 stem 不重复收
        wiki, card_stem="卡一", card_title="卡一", tags=["C93-管理·领导"], llm=False
    )
    curation.update_topic_page(
        wiki, card_stem="卡二", card_title="卡二", description="讲 FMEA",
        tags=["C93-管理·领导"], llm=False,
    )
    text = path.read_text(encoding="utf-8")
    assert text.count("[[卡一]]") == 1
    assert "[[卡二]]" in text
    index_text = (wiki / "index.md").read_text(encoding="utf-8")
    assert "## 主题页" in index_text
    assert "* [C93-管理·领导](topics/C93-管理·领导.md) - 2 张卡" in index_text


def test_topic_hint_priority_and_fallback(memory_tree):
    """定主题：显式 hint 优先；无中图法标签归「未分类」。"""
    wiki = _wiki(memory_tree)
    hinted = curation.update_topic_page(
        wiki, card_stem="卡", card_title="卡", tags=["划重点"],
        topic_hint="B84-心理学", llm=False,
    )
    assert hinted.name == "B84-心理学.md"
    fallback = curation.update_topic_page(
        wiki, card_stem="卡2", card_title="卡2", tags=["划重点"], llm=False
    )
    assert fallback.name == "未分类.md"


def test_topic_brief_refreshed_by_llm(memory_tree, monkeypatch):
    """LLM 导读：写入 > 行。"""
    wiki = _wiki(memory_tree)
    monkeypatch.setattr(
        curation, "_llm_brief", lambda topic, items: "这个主题在攒需求分析方法。"
    )
    path = curation.update_topic_page(
        wiki, card_stem="卡一", card_title="卡一", description="讲需求",
        tags=["C93-管理·领导"],
    )
    assert "> 这个主题在攒需求分析方法。" in path.read_text(encoding="utf-8")


def test_topic_brief_llm_failure_keeps_old(memory_tree, monkeypatch):
    """LLM 失败：旧导读保留，收录行照加（导读只是增强工序）。"""
    wiki = _wiki(memory_tree)
    monkeypatch.setattr(curation, "_llm_brief", lambda topic, items: None)
    path = curation.update_topic_page(
        wiki, card_stem="卡一", card_title="卡一", tags=["C93-管理·领导"], llm=True
    )
    text = path.read_text(encoding="utf-8")
    assert "> （导读维护中）" in text
    assert "[[卡一]]" in text


def test_list_stale_cards(memory_tree):
    """到期复查：到期 stable 卡被点名；未到期/已废弃跳过；topics 一并扫。"""
    wiki = _wiki(memory_tree)

    def _card(dirpath, name, stale_after, status="stable"):
        meta = {
            "type": "Excerpt",
            "title": name,
            "status": status,
            "stale_after": stale_after,
        }
        (dirpath / f"{name}.md").write_text(
            frontmatter.dumps(frontmatter.Post("正文\n", **meta)), encoding="utf-8"
        )

    _card(wiki, "到期卡", "2026-09-01")
    _card(wiki, "未到期", "2027-01-01")
    _card(wiki, "已废弃", "2026-09-01", status="deprecated")
    topics_dir = wiki / "topics"
    topics_dir.mkdir()
    _card(topics_dir, "到期主题页", "2026-09-10")

    found = curation.list_stale_cards(wiki, "2026-09-18")
    stems = [stem for stem, _title, _date in found]
    assert stems == ["到期卡", "到期主题页"]  # 按到期日升序


def test_sync_wiki_log_baseline_then_creation(memory_tree):
    """wiki 变更日志（2026-09-23 方案 B）：首次静默建档不补记存量；
    新条目记 Creation；重复运行幂等；index/log 机器文件不登记。"""
    import json

    wiki = _wiki(memory_tree)
    state = memory_tree.state_dir / "wiki_log.json"
    (wiki / "既有卡.md").write_text("---\ntitle: 既有卡\n---\n正文\n", encoding="utf-8")
    (wiki / "index.md").write_text("# nav\n", encoding="utf-8")

    # 首次运行：静默建档——存量不补记，log.md 只有头部
    assert curation.sync_wiki_log(wiki, state) == []
    log = (wiki / "log.md").read_text(encoding="utf-8")
    assert "Knowledge Update Log" in log
    assert "既有卡" not in log

    # 新条目：记一条 Creation（标题取 frontmatter title）
    (wiki / "新卡.md").write_text("---\ntitle: 新卡标题\n---\n正文\n", encoding="utf-8")
    assert curation.sync_wiki_log(wiki, state) == ["新卡.md"]
    log = (wiki / "log.md").read_text(encoding="utf-8")
    assert "新增 [新卡标题](新卡.md)" in log

    # 幂等：再跑不重复记；机器文件不进 known 清单
    assert curation.sync_wiki_log(wiki, state) == []
    log = (wiki / "log.md").read_text(encoding="utf-8")
    assert log.count("新卡.md") == 1
    known = json.loads(state.read_text(encoding="utf-8"))["known"]
    assert "新卡.md" in known and "既有卡.md" in known
    assert "index.md" not in known and "log.md" not in known
