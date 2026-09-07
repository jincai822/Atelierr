"""子目录归档：递归扫描 / 移动迁移 / 特殊目录排除（跨模块场景）。

约定：用户在 Obsidian 里手动把已确认笔记拖进一级平台目录（抖音/、
小红书/…），机器永不移动笔记，但 search/decay/watcher 递归可见；
wiki/、attachments/、trash/ 与隐藏目录永不参与扫描。
"""

from __future__ import annotations

import os
import time

from scripts.memory.decay import DecayManager
from scripts.memory.search import MemorySearcher
from scripts.memory.watcher import MemoryWatcher


def _move_into_subdir(memory_tree, note_path, subdir: str):
    """把笔记文件移到 memory/<subdir>/ 下（模拟 Obsidian 手动拖动）。"""
    target_dir = memory_tree.notes_dir / subdir
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / note_path.name
    os.rename(note_path, target)
    return target


def _write_excluded_md(memory_tree, rel: str, content: str):
    """在特殊/隐藏目录下写一个 .md（不应被当笔记）。"""
    path = memory_tree.notes_dir / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


# ----------------------------------------------------------------------
# search：递归可见 + 特殊目录排除
# ----------------------------------------------------------------------

def test_search_finds_note_in_subdir(memory_tree, make_note):
    """归档子目录里的笔记能被全文/标签搜索命中，路径指向子目录。"""
    note = make_note(memory_tree, filename="python.md", content="asyncio 协程实战")
    target = _move_into_subdir(memory_tree, note, "抖音")
    searcher = MemorySearcher(memory_tree)

    by_text = searcher.search("协程")
    assert [r.path for r in by_text] == [target]

    memory_tree.move_note(target, "mid-term")
    by_layer = searcher.search(layer="mid-term")
    assert [r.path for r in by_layer] == [target]
    assert by_layer[0].path == target
    assert by_layer[0].id  # frontmatter id 正常物化


def test_search_ignores_special_dirs(memory_tree, make_note):
    """wiki/attachments/trash/隐藏目录下的 md 永远不算笔记。"""
    make_note(memory_tree, filename="real.md", content="真笔记的独特词")
    for rel in ("wiki/摘录-概念.md", "attachments/x.md", "trash/旧.md", ".sync/隐藏.md"):
        _write_excluded_md(memory_tree, rel, "特殊目录独特词")

    results = MemorySearcher(memory_tree).search("特殊目录独特词")
    assert results == []
    assert [r.path.name for r in MemorySearcher(memory_tree).search()] == ["real.md"]


def test_search_subdir_sorted_stable(memory_tree, make_note):
    """跨目录搜索结果排序稳定（相对路径次级序）。"""
    a = make_note(memory_tree, filename="a.md", content="同词")
    b = make_note(memory_tree, filename="b.md", content="同词")
    moved_b = _move_into_subdir(memory_tree, b, "抖音")
    results = MemorySearcher(memory_tree).search("同词")
    assert {r.path for r in results} == {a, moved_b}


# ----------------------------------------------------------------------
# decay：递归分层 + 特殊目录不计
# ----------------------------------------------------------------------

def test_decay_run_covers_subdir_note(memory_tree, make_note):
    """子目录笔记参与衰减：登记/分层/标记走完整链路。"""
    note = make_note(memory_tree, filename="old.md", content="内容")
    target = _move_into_subdir(memory_tree, note, "抖音")
    old_ns = int((time.time() - 60 * 86400) * 1e9)
    os.utime(target, ns=(old_ns, old_ns))

    MemoryWatcher(memory_tree).process_pending()  # 迁移条目到子目录路径
    report = DecayManager(memory_tree).run()

    assert report["total_notes"] == 1
    assert target in memory_tree.list_notes("long-term")  # 60 天 idle → long-term
    assert memory_tree.is_pending_delete(target) is True  # 60 天 conf < 0.1
    entry = memory_tree._entry(target)
    assert entry is not None
    assert entry["path"] == "抖音/old.md"


def test_decay_backlinks_across_subdirs(memory_tree, make_note):
    """子目录笔记可被别的笔记 [[引用]]：反链统计与索引一致。"""
    target = make_note(memory_tree, filename="asyncio.md", content="协程笔记")
    moved = _move_into_subdir(memory_tree, target, "小红书")
    make_note(memory_tree, filename="reader.md", content="引用 [[asyncio]]")

    MemoryWatcher(memory_tree).process_pending()
    DecayManager(memory_tree).run()

    entry = memory_tree._entry(moved)
    assert entry is not None
    assert entry["references"] == 1


def test_decay_ignores_special_dir_md(memory_tree, make_note):
    """特殊目录/隐藏目录的 md 不计入衰减，也不产生反链 key。"""
    make_note(memory_tree, filename="real.md", content="正文")
    for rel in ("wiki/w.md", "attachments/a.md", "trash/t.md", ".h/hidden.md"):
        _write_excluded_md(memory_tree, rel, "---\ntitle: 特殊\n---\n正文")

    report = DecayManager(memory_tree).run()
    assert report["total_notes"] == 1
    assert report["skipped"] == []


# ----------------------------------------------------------------------
# watcher：移动迁移（状态保留）与递归登记
# ----------------------------------------------------------------------

def test_watcher_migrates_entry_on_manual_move(memory_tree):
    """顶层 → 子目录移动：同一 frontmatter id 迁移，动态状态原样保留。"""
    note = memory_tree.create_note("douyin-x.md", "正文\n", source="link", tags=["待确认", "抖音"])
    memory_tree.move_note(note, "mid-term")
    memory_tree.on_note_accessed(note)
    entry_before = memory_tree._entry(note)
    assert entry_before["layer"] == "mid-term"
    assert entry_before["last_accessed"] is not None
    assert entry_before["references"] == 0
    note_id = memory_tree._find_entry_id(note)

    target = _move_into_subdir(memory_tree, note, "抖音")
    result = MemoryWatcher(memory_tree).process_pending()

    assert result["migrated"] == [target]
    assert result["registered"] == []
    assert result["normalized"] == []
    assert result["deregistered"] == []
    entry = memory_tree._entry(target)
    assert entry is not None
    assert entry["path"] == "抖音/douyin-x.md"
    # 动态状态保留：created/layer/last_accessed 未因迁移被重置
    assert entry["layer"] == "mid-term"
    assert entry["last_accessed"] == entry_before["last_accessed"]
    assert memory_tree._entry(note) is None  # 旧路径条目已不存在
    index = memory_tree._load_index()
    assert list(index.values())[0]["path"] == "抖音/douyin-x.md"
    assert str(note_id) in index
    # 迁移后文件 mtime 未被改写（机器不碰文件）
    assert target.read_text(encoding="utf-8") != ""  # 内容仍在


def test_watcher_registers_note_placed_directly_in_subdir(memory_tree):
    """用户直接把新文件放进子目录（未走顶层）：递归登记，不丢状态语义。"""
    subdir = memory_tree.notes_dir / "小红书"
    subdir.mkdir(parents=True)
    note = subdir / "xhs-x.md"
    note.write_text(
        "---\nid: 01J6" + "0" * 22 + "\nsource: link\ntags: [待确认, 小红书]\n---\n正文",
        encoding="utf-8",
    )

    result = MemoryWatcher(memory_tree).process_pending()

    assert result["registered"] == [note]
    entry = memory_tree._entry(note)
    assert entry is not None
    assert entry["path"] == "小红书/xhs-x.md"
    assert MemorySearcher(memory_tree).search("正文")


def test_watcher_ignores_special_dir_md(memory_tree):
    """特殊目录/隐藏目录里的 md 永不登记、永不注销既有条目。"""
    keep = memory_tree.create_note("keep.md", "内容")
    for rel in ("wiki/w.md", "attachments/a.md", "trash/t.md", ".h/hidden.md"):
        _write_excluded_md(memory_tree, rel, "裸内容")

    result = MemoryWatcher(memory_tree).process_pending()

    assert result["registered"] == []
    assert result["normalized"] == []
    for rel in ("wiki/w.md", "attachments/a.md", "trash/t.md", ".h/hidden.md"):
        assert memory_tree._entry(memory_tree.notes_dir / rel) is None
    assert memory_tree._entry(keep) is not None


def test_watcher_move_then_delete_old_path_deregisters_once(memory_tree, make_note):
    """移动并触发多轮 process_pending：第二轮回稳（无 migrated/无注销抖动）。"""
    note = make_note(memory_tree, filename="m.md", content="内容")
    _move_into_subdir(memory_tree, note, "抖音")
    MemoryWatcher(memory_tree).process_pending()

    again = MemoryWatcher(memory_tree).process_pending()
    assert again["migrated"] == []
    assert again["deregistered"] == []
    assert memory_tree.get_stats()["total"] == 1


def test_decay_migrates_entry_when_watcher_not_run(memory_tree):
    """移动后 decay 先于 watcher 跑：按 id 找回旧条目，状态不丢、path 顺带迁移。"""
    note = memory_tree.create_note("old.md", "内容", source="link")
    memory_tree.move_note(note, "mid-term")
    memory_tree.on_note_accessed(note)
    entry_before = memory_tree._entry(note)
    accessed_before = entry_before["last_accessed"]
    assert entry_before["layer"] == "mid-term"

    target = _move_into_subdir(memory_tree, note, "抖音")
    report = DecayManager(memory_tree).run()  # 不先跑 watcher

    entry = memory_tree._entry(target)
    assert entry is not None
    assert entry["path"] == "抖音/old.md"
    assert entry["layer"] == entry_before["layer"]  # 不是默认 short-term
    assert entry["last_accessed"] == accessed_before  # 访问历史未重置
    assert report["total_notes"] == 1


def test_watcher_moves_out_of_trash_restores_index(memory_tree):
    """从 trash/ 移回笔记树（用户在 Obsidian 回收站还原）：条目重新登记。"""
    trash = memory_tree.notes_dir / "trash"
    trash.mkdir(parents=True)
    gone = memory_tree.create_note("revive.md", "---\nid: 01J6" + "0" * 22 + "\n---\n正文")
    os.rename(gone, trash / "revive.md")
    MemoryWatcher(memory_tree).process_pending()  # 旧条目注销
    assert memory_tree.get_stats()["total"] == 0

    target = memory_tree.notes_dir / "抖音"
    target.mkdir()
    os.rename(trash / "revive.md", target / "revive.md")
    result = MemoryWatcher(memory_tree).process_pending()
    assert result["registered"] == [target / "revive.md"]
    assert memory_tree._entry(target / "revive.md")["path"] == "抖音/revive.md"
