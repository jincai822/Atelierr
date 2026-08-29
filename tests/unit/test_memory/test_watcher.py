"""MemoryWatcher.process_pending 单元测试。"""

from __future__ import annotations

import frontmatter

from scripts.memory.watcher import MemoryWatcher


def test_normalize_bare_markdown(memory_tree):
    """裸 markdown → 归一化补 frontmatter（id/source=web）并登记 short-term。"""
    note = memory_tree.notes_dir / "raw.md"
    note.write_text("裸内容", encoding="utf-8")
    result = MemoryWatcher(memory_tree).process_pending()
    assert result["normalized"] == [note]
    assert memory_tree.layer_of(note) == "short-term"
    post = frontmatter.loads(note.read_text(encoding="utf-8"))
    assert post.metadata.get("id")
    assert len(str(post.metadata["id"])) == 26
    assert post.metadata.get("source") == "web"
    assert post.metadata.get("title") == "raw"
    assert post.metadata.get("tags") == []
    assert memory_tree.read_note(note) == "裸内容"


def test_normalize_preserves_mtime(memory_tree):
    """归一化补写 frontmatter 后 mtime 完全不变。"""
    note = memory_tree.notes_dir / "raw.md"
    note.write_text("content", encoding="utf-8")
    before = note.stat().st_mtime_ns
    MemoryWatcher(memory_tree).process_pending()
    assert note.stat().st_mtime_ns == before


def test_existing_frontmatter_only_registered(memory_tree, make_note):
    """已有合法 frontmatter+id 的文件：只登记，文件一字节不动。"""
    path = memory_tree.notes_dir / "ready.md"
    path.write_text("---\ntitle: 就绪\n---\n内容", encoding="utf-8")
    post = frontmatter.loads(path.read_text(encoding="utf-8"))
    post.metadata["id"] = "01J6" + "0" * 22
    path.write_text(frontmatter.dumps(post), encoding="utf-8")
    before = (path.read_bytes(), path.stat().st_mtime_ns)

    result = MemoryWatcher(memory_tree).process_pending()
    assert result["registered"] == [path]
    assert result["normalized"] == []
    assert (path.read_bytes(), path.stat().st_mtime_ns) == before
    assert memory_tree.layer_of(path) == "short-term"


def test_deregister_deleted_file(memory_tree):
    """外部删除文件 → 对应 sidecar 条目移除。"""
    note = memory_tree.create_note("gone.md", "content")
    assert memory_tree.layer_of(note) == "short-term"
    note.unlink()
    result = MemoryWatcher(memory_tree).process_pending()
    assert result["deregistered"] == ["gone.md"]
    assert memory_tree.get_stats()["total"] == 0


def test_corrupt_frontmatter_skipped(memory_tree):
    """损坏 frontmatter：跳过不抛异常，计入 skipped，不登记。"""
    note = memory_tree.notes_dir / "bad.md"
    note.write_text("---\n: bad: [\n---\n内容", encoding="utf-8")
    result = MemoryWatcher(memory_tree).process_pending()
    assert result["skipped"] == [note]
    assert memory_tree._entry(note) is None
    assert note.exists()  # 文件保留


def test_hidden_and_non_md_ignored(memory_tree):
    """点开头隐藏文件与非 .md 文件被忽略。"""
    (memory_tree.notes_dir / ".hidden.md").write_text("隐藏", encoding="utf-8")
    (memory_tree.notes_dir / "notes.txt").write_text("文本", encoding="utf-8")
    result = MemoryWatcher(memory_tree).process_pending()
    assert result["normalized"] == []
    assert result["registered"] == []
    assert memory_tree.get_stats()["total"] == 0


def test_start_stop(memory_tree):
    """start/stop 常驻监听可正常启停。"""
    watcher = MemoryWatcher(memory_tree)
    watcher.start()
    watcher.start()  # 重复 start 不重复启动
    watcher.stop()
    watcher.stop()  # 重复 stop 幂等
    assert watcher._observer is None
