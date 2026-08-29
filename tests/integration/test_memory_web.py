"""Flatnotes 集成（scripts/web/integration.py）验收测试。

断言以 docs/ACCEPTANCE-CRITERIA.md 2.1 为准：新文件归一化、
mtime 保持、创建笔记对 Flatnotes 可见；扩展覆盖外部删除注销、
损坏 frontmatter 跳过、自带 frontmatter 只登记。全部走
FlatnotesIntegration 门面，不绕过。
"""
from __future__ import annotations

import pytest

from scripts.web.integration import FlatnotesIntegration


def _read_frontmatter(path):
    """读取文件 frontmatter 元数据。"""
    import frontmatter

    return frontmatter.loads(path.read_text(encoding="utf-8")).metadata


def test_new_file_normalized(integration, memory_tree):
    """外部（Flatnotes/Obsidian）新建的笔记被归一化并登记。"""
    note = memory_tree.notes_dir / "test.md"
    note.write_text("content", encoding="utf-8")

    result = integration.process_pending()

    assert result["normalized"] == [note]
    assert memory_tree.layer_of(note) == "short-term"
    meta = _read_frontmatter(note)
    assert meta.get("id")
    assert meta.get("source") == "web"
    assert memory_tree.read_note(note) == "content"


def test_normalize_preserves_mtime(integration, memory_tree):
    """归一化补写 frontmatter 后 mtime 完全不变。"""
    note = memory_tree.notes_dir / "raw.md"
    note.write_text("content", encoding="utf-8")
    before = note.stat().st_mtime_ns

    integration.process_pending()

    assert note.stat().st_mtime_ns == before


def test_created_note_visible_to_flatnotes(integration, memory_tree):
    """记忆模块创建的笔记就在共享目录根层（Flatnotes 可直接见）。"""
    path = integration.tree.create_note("from_memory.md", "content")
    assert path.parent == memory_tree.notes_dir
    assert path.name == "from_memory.md"


def test_external_deletion_deregisters(integration, memory_tree):
    """外部删除文件 → 对应 sidecar 条目移除。"""
    note = memory_tree.create_note("gone.md", "content")
    assert memory_tree.layer_of(note) == "short-term"
    note.unlink()

    result = integration.process_pending()

    assert result["deregistered"] == ["gone.md"]
    assert memory_tree.get_stats()["total"] == 0
    with pytest.raises(FileNotFoundError):
        memory_tree.layer_of(note)


def test_corrupt_frontmatter_skipped(integration, memory_tree):
    """损坏 frontmatter：跳过不抛异常，不中断 watcher。"""
    note = memory_tree.notes_dir / "bad.md"
    note.write_text("---\n: bad: [\n---\n内容", encoding="utf-8")

    result = integration.process_pending()

    assert result["skipped"] == [note]
    assert memory_tree._entry(note) is None
    assert note.exists()  # 文件保留


def test_existing_frontmatter_only_registered(integration, memory_tree):
    """自带合法 frontmatter（含 id）的外部文件：只登记，文件一字节不动。"""
    import frontmatter

    path = memory_tree.notes_dir / "ready.md"
    path.write_text("---\ntitle: 就绪\n---\n内容", encoding="utf-8")
    post = frontmatter.loads(path.read_text(encoding="utf-8"))
    post.metadata["id"] = "01J6" + "0" * 22
    path.write_text(frontmatter.dumps(post), encoding="utf-8")
    before = (path.read_bytes(), path.stat().st_mtime_ns)

    result = integration.process_pending()

    assert result["registered"] == [path]
    assert result["normalized"] == []
    assert (path.read_bytes(), path.stat().st_mtime_ns) == before
    assert memory_tree.layer_of(path) == "short-term"


def test_from_config(tmp_path):
    """从 YAML 配置构造门面：tree 指向配置的目录，watcher source=web。"""
    config = tmp_path / "memory.yaml"
    config.write_text(
        f"memory:\n"
        f"  root: {tmp_path}/memory\n"
        f"  state_dir: {tmp_path}/state\n",
        encoding="utf-8",
    )

    integration = FlatnotesIntegration.from_config(str(config))

    assert integration.tree.notes_dir == tmp_path / "memory"
    assert integration.tree.state_dir == tmp_path / "state"
    assert integration.watcher.source == "web"
    assert integration.watcher.tree is integration.tree


def test_start_stop_delegates(integration):
    """start/stop 委托 watcher：可正常启停且重复调用幂等。"""
    integration.start()
    integration.start()  # 重复 start 不重复启动
    integration.stop()
    integration.stop()  # 重复 stop 幂等
    assert integration.watcher._observer is None
