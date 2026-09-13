"""MemoryTree 单元测试（验收 1.1 全部 5 条 + 扩展）。"""

from __future__ import annotations

import os
import time
from datetime import datetime
from pathlib import Path

import frontmatter
import pytest

from scripts.memory.confidence import ConfidenceCalculator
from scripts.memory.core import MemoryTree, generate_id


def test_memory_tree_init(memory_tree):
    """初始化：平面笔记目录 + sidecar 状态目录自动创建。"""
    assert memory_tree.notes_dir.exists()
    assert memory_tree.state_dir.exists()


def test_default_state_dir_is_sibling(tmp_path):
    """未显式传 state_dir 时默认 notes_dir.parent / "state"。"""
    tree = MemoryTree(tmp_path / "memory")
    assert tree.state_dir == tmp_path / "state"
    assert tree.state_dir.exists()


def test_create_note(memory_tree):
    """创建笔记：文件在平面根层，sidecar 登记 short-term/conf 1.0。"""
    note_path = memory_tree.create_note("测试笔记.md", "这是内容")
    assert note_path.exists()
    assert note_path.parent == memory_tree.notes_dir
    assert memory_tree.layer_of(note_path) == "short-term"
    entry = memory_tree._entry(note_path)
    assert entry["confidence"] == 1.0
    assert entry["last_accessed"] is None
    assert entry["references"] == 0
    assert entry["pending_delete"] is False
    post = frontmatter.loads(note_path.read_text(encoding="utf-8"))
    assert post.metadata.get("id")
    assert len(str(post.metadata["id"])) == 26
    assert post.metadata.get("title") == "测试笔记"
    assert post.metadata.get("created")
    assert post.metadata.get("source") == "unknown"
    assert post.metadata.get("tags") == []


def test_generate_id_shape():
    """ULID：26 字符 Crockford base32（0-9 A-Z 去掉 I/L/O/U）。"""
    note_id = generate_id()
    assert len(note_id) == 26
    assert set(note_id) <= set("0123456789ABCDEFGHJKMNPQRSTVWXYZ")
    assert generate_id() != generate_id()


def test_create_note_with_tags_and_source(memory_tree):
    note = memory_tree.create_note(
        "tagged.md", "内容", source="obsidian", tags=["编程", "AI"]
    )
    post = frontmatter.loads(note.read_text(encoding="utf-8"))
    assert post.metadata["source"] == "obsidian"
    assert post.metadata["tags"] == ["编程", "AI"]


def test_create_note_reuses_existing_frontmatter(memory_tree):
    """content 自带合法 frontmatter 时复用元数据并补 id。"""
    note = memory_tree.create_note(
        "fm.md",
        "---\ntitle: 自定义标题\ncreated: '2026-01-01T10:00:00'\nsource: obsidian\ntags: [a]\n---\n正文",
    )
    post = frontmatter.loads(note.read_text(encoding="utf-8"))
    assert post.metadata["title"] == "自定义标题"
    assert post.metadata["created"] == "2026-01-01T10:00:00"
    assert post.metadata["source"] == "obsidian"
    assert post.metadata["tags"] == ["a"]
    assert post.metadata.get("id")


def test_move_note(memory_tree):
    """层级覆写：sidecar 变化，文件（内容与 mtime）完全不动。"""
    note = memory_tree.create_note("test.md", "content")
    before = (note.read_bytes(), note.stat().st_mtime_ns)
    memory_tree.move_note(note, "mid-term")
    assert memory_tree.layer_of(note) == "mid-term"
    assert note.exists()
    assert (note.read_bytes(), note.stat().st_mtime_ns) == before


def test_move_note_invalid_layer(memory_tree):
    note = memory_tree.create_note("test.md", "content")
    with pytest.raises(ValueError):
        memory_tree.move_note(note, "archive")


def test_move_note_missing_file(memory_tree):
    with pytest.raises(FileNotFoundError):
        memory_tree.move_note(memory_tree.notes_dir / "ghost.md", "long-term")


def test_list_notes(memory_tree):
    """按 sidecar 层级列出笔记。"""
    memory_tree.create_note("note1.md", "content1")
    memory_tree.create_note("note2.md", "content2")
    notes = memory_tree.list_notes("short-term")
    assert len(notes) == 2
    assert all(note.parent == memory_tree.notes_dir for note in notes)


def test_list_notes_filters_by_layer(memory_tree):
    memory_tree.create_note("a.md", "a")
    b = memory_tree.create_note("b.md", "b")
    memory_tree.move_note(b, "long-term")
    assert memory_tree.list_notes("short-term") == [memory_tree.notes_dir / "a.md"]
    assert memory_tree.list_notes("long-term") == [b]


def test_invalid_path(memory_tree):
    """无效路径：读取不存在的文件抛 FileNotFoundError。"""
    with pytest.raises(FileNotFoundError):
        memory_tree.read_note("/non/existent/path.md")


def test_duplicate_filename_raises(memory_tree):
    """重复文件名：FileExistsError，绝不覆盖。"""
    memory_tree.create_note("dup.md", "a")
    with pytest.raises(FileExistsError):
        memory_tree.create_note("dup.md", "b")
    assert memory_tree.read_note(memory_tree.notes_dir / "dup.md") == "a"


def test_filename_with_subdir_raises(memory_tree):
    """带目录分量的文件名：ValueError。"""
    with pytest.raises(ValueError):
        memory_tree.create_note("sub/x.md", "content")


def test_non_md_filename_raises(memory_tree):
    """非 .md 文件名：ValueError。"""
    with pytest.raises(ValueError):
        memory_tree.create_note("x.txt", "content")


def test_read_note_returns_body(memory_tree):
    """read_note 返回去掉 frontmatter 的正文（.strip()）。"""
    note = memory_tree.create_note("body.md", "# 标题\n\n正文内容\n")
    assert memory_tree.read_note(note) == "# 标题\n\n正文内容"


def test_on_note_accessed_resets_clock(memory_tree):
    """访问后 last_accessed 写入，live 重算 confidence == 1.0。"""
    note = memory_tree.create_note("acc.md", "content")
    old_ns = int((time.time() - 30 * 86400) * 1e9)
    os.utime(note, ns=(old_ns, old_ns))
    memory_tree.on_note_accessed(note)
    entry = memory_tree._entry(note)
    assert entry["last_accessed"] is not None
    calc = ConfidenceCalculator()
    conf = calc.calculate(
        {
            "accessed": entry["last_accessed"],
            "modified": datetime.fromtimestamp(note.stat().st_mtime),
            "references": 0,
        }
    )
    assert conf == 1.0


def test_on_note_accessed_missing_file(memory_tree):
    with pytest.raises(FileNotFoundError):
        memory_tree.on_note_accessed(memory_tree.notes_dir / "ghost.md")


def test_on_note_accessed_registers_unregistered(memory_tree, make_note):
    """sidecar 无条目但文件存在：先登记默认条目再更新。"""
    note = make_note(memory_tree)
    memory_tree._remove_entry(note)
    assert memory_tree._entry(note) is None
    memory_tree.on_note_accessed(note)
    assert memory_tree.layer_of(note) == "short-term"
    assert memory_tree._entry(note)["last_accessed"] is not None


def test_is_pending_delete(memory_tree, make_note):
    note = make_note(memory_tree, idle_days=60)
    assert memory_tree.is_pending_delete(note) is False
    from scripts.memory.decay import DecayManager

    DecayManager(memory_tree).run()
    assert memory_tree.is_pending_delete(note) is True


def test_get_stats(memory_tree):
    """get_stats 字段完整且计数正确。"""
    memory_tree.create_note("a.md", "a")
    b = memory_tree.create_note("b.md", "b", tags=["x"])
    memory_tree.move_note(b, "mid-term")
    stats = memory_tree.get_stats()
    assert stats["total"] == 2
    assert stats["layers"] == {"short-term": 1, "mid-term": 1, "long-term": 0}
    assert stats["pending_delete"] == 0
    assert stats["avg_confidence"] == 1.0
    assert stats["notes_dir"] == str(memory_tree.notes_dir)
    assert stats["state_dir"] == str(memory_tree.state_dir)


def test_corrupt_index_recovers_without_losing_notes(memory_tree, make_note):
    """index.json 损坏：改名 .bak 并从空索引重建，笔记文件不受影响。"""
    note = make_note(memory_tree)
    memory_tree.index_path.write_text("{invalid json", encoding="utf-8")
    tree2 = MemoryTree(memory_tree.notes_dir, state_dir=memory_tree.state_dir)
    assert tree2.get_stats()["total"] == 0
    assert note.exists()
    bak = memory_tree.index_path.with_name(memory_tree.index_path.name + ".bak")
    assert bak.exists()
    # 新登记仍可正常工作
    tree2.create_note("after.md", "内容")
    assert tree2.layer_of(tree2.notes_dir / "after.md") == "short-term"


def test_from_config(memory_tree, tmp_path):
    """from_config 用配置覆盖 MemorySettings 默认值。"""
    config = tmp_path / "memory.yaml"
    config.write_text(
        f"memory:\n"
        f"  root: {tmp_path}/mem\n"
        f"  state_dir: {tmp_path}/st\n"
        f"  layers:\n"
        f"    short_term_min: 0.8\n"
        f"    mid_term_min: 0.5\n"
        f"  decay:\n"
        f"    rate: 0.9\n"
        f"    ref_coefficient: 0.3\n"
        f"    ref_cap: 5\n"
        f"    delete_threshold: 0.2\n",
        encoding="utf-8",
    )
    tree = MemoryTree.from_config(config)
    assert tree.settings.short_term_min == 0.8
    assert tree.settings.mid_term_min == 0.5
    assert tree.settings.decay_rate == 0.9
    assert tree.settings.ref_coefficient == 0.3
    assert tree.settings.ref_cap == 5
    assert tree.settings.delete_threshold == 0.2
    assert tree.notes_dir == Path(tmp_path / "mem")
    assert tree.state_dir == Path(tmp_path / "st")


def test_from_config_missing_file(tmp_path):
    with pytest.raises(FileNotFoundError):
        MemoryTree.from_config(tmp_path / "nope.yaml")


def test_settings_assign_layer():
    """分层规则：>=0.7 short / >=0.4 mid / else long。"""
    settings = MemoryTree("/tmp/x", state_dir="/tmp/y").settings
    assert settings.assign_layer(0.7) == "short-term"
    assert settings.assign_layer(0.69) == "mid-term"
    assert settings.assign_layer(0.4) == "mid-term"
    assert settings.assign_layer(0.39) == "long-term"


def test_note_info(memory_tree, make_note):
    """note_info 汇总静态元数据与动态状态。"""
    note = make_note(memory_tree, filename="info.md", content="信息", tags=["a"])
    memory_tree.move_note(note, "long-term")
    info = memory_tree.note_info(note)
    assert info["path"] == note
    assert info["id"]
    assert info["title"] == "info"
    assert info["tags"] == ["a"]
    assert info["layer"] == "long-term"
    assert info["confidence"] == 1.0
    assert info["pending_delete"] is False


def test_iter_note_files_excludes_system_dir(memory_tree):
    """系统/ 目录（摘要/控制台等机器产物）不进笔记扫描域。"""
    from scripts.memory.core import iter_note_files

    memory_tree.create_note("real.md", "真笔记")
    system_dir = memory_tree.notes_dir / "系统"
    system_dir.mkdir()
    (system_dir / "今日摘要-2026-09-07.md").write_text("摘要", encoding="utf-8")
    (system_dir / "控制台.md").write_text("控制台", encoding="utf-8")

    names = [path.name for path in iter_note_files(memory_tree.notes_dir)]
    assert names == ["real.md"]


def test_iter_note_files_skips_sync_conflict(memory_tree):
    """Syncthing 冲突副本（*.sync-conflict-*）不是新笔记，一律跳过。"""
    from scripts.memory.core import iter_note_files

    memory_tree.create_note("real.md", "真笔记")
    (memory_tree.notes_dir / "real.sync-conflict-20260907-120000-ABCDE.md").write_text(
        "冲突副本", encoding="utf-8"
    )

    names = [path.name for path in iter_note_files(memory_tree.notes_dir)]
    assert names == ["real.md"]


def test_concurrent_writers_no_lost_updates(tmp_path):
    """多进程写者防丢更新（2026-09-13 实证：飞书守护刚写下的
    pending_delete 被并发班次的旧缓存回写冲掉）：A 持旧缓存，B 写后
    A 再写，B 的更新必须还在。"""
    notes = tmp_path / "memory"
    state = tmp_path / "state"
    tree_a = MemoryTree(notes, state_dir=state)
    tree_b = MemoryTree(notes, state_dir=state)
    note_a = tree_a.create_note("a.md", "内容", source="link")
    note_b = tree_a.create_note("b.md", "内容", source="link")

    # B 标 b 待删（落盘）；A 的内存缓存停留在 create 时刻（无该标记）
    assert tree_b.set_pending_delete(note_b)
    # A 再写 a 的访问记录——若 A 用旧缓存整体回写，B 的标记会丢
    tree_a.on_note_accessed(note_a)

    # 第三方全新读：两个更新都在
    tree_c = MemoryTree(notes, state_dir=state)
    assert tree_c.is_pending_delete(note_b)
    assert tree_c._entry(note_a)["last_accessed"] is not None


def test_attachments_dir_configurable(tmp_path):
    """attachments_dir 可在配置里覆盖；缺省推导 notes_dir 平级。"""
    config = tmp_path / "memory.yaml"
    config.write_text(
        f"memory:\n  root: {tmp_path}/memory\n  state_dir: {tmp_path}/state\n"
        f"  attachments_dir: {tmp_path}/raw\n",
        encoding="utf-8",
    )
    tree = MemoryTree.from_config(str(config))
    assert tree.attachments_dir == tmp_path / "raw"

    config.write_text(
        f"memory:\n  root: {tmp_path}/memory\n  state_dir: {tmp_path}/state\n",
        encoding="utf-8",
    )
    tree = MemoryTree.from_config(str(config))
    assert tree.attachments_dir == tmp_path / "attachments"


def test_abs_inbox_prefix_prefers_inbox(tmp_path):
    """inbox/ 前缀解析到中转站；中转站没有而 memory/inbox/（误建的保留名
    子目录）有，回退 memory/ 侧不丢数据；两侧都没有返回中转站路径。"""
    tree = MemoryTree(tmp_path / "memory", state_dir=tmp_path / "state")
    assert tree._abs("inbox/x.md") == tree.inbox_dir / "x.md"
    (tree.inbox_dir / "x.md").write_text("中转卡", encoding="utf-8")
    assert tree._abs("inbox/x.md") == tree.inbox_dir / "x.md"

    real_subdir = tree.notes_dir / "inbox"
    real_subdir.mkdir()
    (real_subdir / "y.md").write_text("误建目录里的真笔记", encoding="utf-8")
    assert tree._abs("inbox/y.md") == real_subdir / "y.md"
