"""DecayManager 单元测试（验收 1.3 全部 5 条 + 扩展）。"""

from __future__ import annotations

import os
import time
from pathlib import Path

import frontmatter
import pytest

from scripts.memory.decay import DecayManager


def test_decay_scan(memory_tree, make_note):
    """scan 返回分层统计报告（不写状态）。"""
    make_note(memory_tree)
    report = DecayManager(memory_tree).scan()
    assert "total_notes" in report
    assert "short_term" in report
    assert "mid_term" in report
    assert "long_term" in report
    assert report["total_notes"] == 1
    assert report["short_term"] == 1


def test_decay_relayer(memory_tree, make_note):
    """idle 10 天：重算后 conf≈0.6 → mid-term，文件仍在平面根层。"""
    note = make_note(memory_tree, idle_days=10)
    DecayManager(memory_tree).run()
    assert note in memory_tree.list_notes("mid-term")
    assert note.exists()


def test_decay_never_touches_files(memory_tree, make_note):
    """衰减前后笔记内容与 mtime 完全不变。"""
    note = make_note(memory_tree, idle_days=30)
    before = (note.read_bytes(), note.stat().st_mtime_ns)
    DecayManager(memory_tree).run()
    assert (note.read_bytes(), note.stat().st_mtime_ns) == before


def test_decay_dry_run(memory_tree, make_note):
    """dry-run：sidecar 未变（仍 short-term）、would_relayer>0、无报告文件。"""
    note = make_note(memory_tree, idle_days=10)
    report = DecayManager(memory_tree).run(dry_run=True)
    assert note in memory_tree.list_notes("short-term")
    assert report["would_relayer"] > 0
    assert report["relayered"] == 0
    assert not (memory_tree.state_dir / "reports").exists()


def test_pending_delete_is_mark_only(memory_tree, make_note):
    """conf < 0.1 只打标记，文件仍存在。"""
    note = make_note(memory_tree, idle_days=60)
    DecayManager(memory_tree).run()
    assert note.exists()
    assert memory_tree.is_pending_delete(note)


def test_manual_pending_delete_survives_decay(memory_tree, make_note):
    """人工标记粘性（2026-09-20 用户裁决）：高置信笔记人工标
    pending_delete 后跑衰减班次，标记不被重算冲掉，只有 review 能摘。"""
    note = make_note(memory_tree, idle_days=0)  # 新鲜笔记，conf 远高于阈值
    assert memory_tree.set_pending_delete(note) is True

    DecayManager(memory_tree).run()

    assert memory_tree.is_pending_delete(note)
    assert note.exists()


def test_backlinks_boost_confidence(memory_tree, make_note):
    """反链：B 引用 [[A-stem]] → A 的 references>=1 且同龄时比无引用者 conf 高。"""
    target = make_note(
        memory_tree, filename="asyncio.md", content="关于 asyncio 的笔记", idle_days=50
    )
    other = make_note(
        memory_tree, filename="other.md", content="普通笔记", idle_days=50
    )
    make_note(
        memory_tree,
        filename="reader.md",
        content="引用了 [[asyncio]] 的笔记",
        idle_days=0,
    )

    DecayManager(memory_tree).run()

    target_entry = memory_tree._entry(target)
    assert target_entry["references"] >= 1
    assert target_entry["confidence"] > memory_tree._entry(other)["confidence"]


def test_backlink_alias_and_heading(memory_tree, make_note):
    """[[target|alias]] 与 [[target#heading]] 按 target 部分匹配。"""
    target = make_note(memory_tree, filename="python.md", content="python 笔记")
    make_note(memory_tree, filename="l1.md", content="链接 [[python|教程]]")
    make_note(memory_tree, filename="l2.md", content="链接 [[python#性能]]")
    DecayManager(memory_tree).run()
    assert memory_tree._entry(target)["references"] == 2


def test_backlink_by_title(memory_tree, make_note):
    """按 frontmatter title 精确匹配。"""
    target = make_note(
        memory_tree, filename="titled.md", content="---\ntitle: 中文标题\n---\n正文"
    )
    make_note(memory_tree, filename="linker.md", content="引用 [[中文标题]]")
    DecayManager(memory_tree).run()
    assert memory_tree._entry(target)["references"] == 1


def test_report_file_generated(memory_tree, make_note):
    """报告文件生成且含"待删除"相关字样。"""
    make_note(memory_tree, idle_days=60)
    report = DecayManager(memory_tree).run()
    assert report["report_path"]
    report_path = Path(report["report_path"])
    assert report_path.exists()
    assert report_path.parent == memory_tree.state_dir / "reports"
    text = report_path.read_text(encoding="utf-8")
    assert "待删除" in text
    assert "pending_delete" in text
    assert "层级迁移" in text


def test_decay_skips_bare_md(memory_tree, make_note):
    """无 frontmatter 的裸 .md 跳过计入 skipped，不登记不写文件。"""
    make_note(memory_tree, filename="reg.md")
    bare = memory_tree.notes_dir / "bare.md"
    bare.write_text("没有 frontmatter 的裸文件", encoding="utf-8")
    report = DecayManager(memory_tree).run()
    assert str(bare) in report["skipped"]
    assert report["total_notes"] == 1
    assert memory_tree._entry(bare) is None


def test_decay_registers_frontmatter_only_note(memory_tree, make_note):
    """frontmatter 有 id 但 sidecar 无条目：允许纯 sidecar 登记后处理。"""
    make_note(memory_tree, filename="a.md")
    post = frontmatter.loads("---\ntitle: orphan\n---\n内容")
    post.metadata["id"] = "01J6" + "0" * 22
    orphan = memory_tree.notes_dir / "orphan.md"
    orphan.write_text(frontmatter.dumps(post), encoding="utf-8")

    report = DecayManager(memory_tree).run()
    assert report["total_notes"] == 2
    assert memory_tree._entry(orphan) is not None
    # 文件内容未被改写
    post_after = frontmatter.loads(orphan.read_text(encoding="utf-8"))
    assert post_after.metadata["id"] == "01J6" + "0" * 22


def test_decay_skips_system_notes(memory_tree, make_note):
    """source=system 的基础设施笔记（控制台等）：不衰减、不计数、不置待删。"""
    panel = memory_tree.create_note(
        "控制台.md", "面板", source="system", tags=["系统"]
    )
    old_ns = int((time.time() - 60 * 86400) * 1e9)
    os.utime(panel, ns=(old_ns, old_ns))
    make_note(memory_tree, "content.md", "内容", idle_days=60)

    report = DecayManager(memory_tree).run()

    assert report["total_notes"] == 1
    assert report["system"] == [str(panel)]
    entry = memory_tree._entry(panel)
    assert entry["pending_delete"] is False
    assert entry["confidence"] == 1.0
    scan = DecayManager(memory_tree).scan()
    assert scan["total_notes"] == 1


def test_machine_source_decays_faster(memory_tree):
    """方案 C（v1.4）：link/media 来源 3 倍速衰减——同 20 天闲置，
    人写笔记不删、机器转写触及 pending_delete；sidecar 写入真值。"""
    old_ns = int((time.time() - 20 * 86400) * 1e9)
    human = memory_tree.create_note("human.md", "人写", source="manual")
    machine = memory_tree.create_note("machine.md", "转写", source="link")
    for path in (human, machine):
        os.utime(path, ns=(old_ns, old_ns))
    for entry in memory_tree._load_index().values():
        entry["last_accessed"] = None
    memory_tree._save_index()

    report = DecayManager(memory_tree).run()

    human_entry = memory_tree._entry(human)
    machine_entry = memory_tree._entry(machine)
    assert human_entry["confidence"] == pytest.approx(0.95 ** 20, abs=1e-3)
    assert human_entry["pending_delete"] is False
    assert machine_entry["confidence"] == pytest.approx(0.95 ** 60, abs=1e-3)
    assert machine_entry["pending_delete"] is True
    assert str(machine) in report["pending"]
    assert str(human) not in report["pending"]


def test_machine_source_references_still_slow_decay(memory_tree):
    """被引用的机器转写：ref_factor 照旧减缓加速衰减（有人用的卡不消失）。"""
    old_ns = int((time.time() - 20 * 86400) * 1e9)
    machine = memory_tree.create_note("machine.md", "转写", source="link")
    memory_tree.create_note("ref.md", "引用 [[machine]]", source="manual")
    os.utime(machine, ns=(old_ns, old_ns))
    for entry in memory_tree._load_index().values():
        entry["last_accessed"] = None
    memory_tree._save_index()

    DecayManager(memory_tree).run()

    entry = memory_tree._entry(machine)
    # idle 20×3=60，ref_factor=1.2 → 0.95^(60/1.2)=0.95^50
    assert entry["references"] == 1
    assert entry["confidence"] == pytest.approx(0.95 ** 50, abs=1e-3)


def test_webclip_not_accelerated(memory_tree):
    """webclip（人主动剪藏）不在方案 C 加速表内：同 idle 按原速。"""
    old_ns = int((time.time() - 20 * 86400) * 1e9)
    clip = memory_tree.create_note("clip.md", "剪藏", source="webclip")
    os.utime(clip, ns=(old_ns, old_ns))
    for entry in memory_tree._load_index().values():
        entry["last_accessed"] = None
    memory_tree._save_index()

    DecayManager(memory_tree).run()

    entry = memory_tree._entry(clip)
    assert entry["confidence"] == pytest.approx(0.95 ** 20, abs=1e-3)
    assert entry["pending_delete"] is False


def test_daily_notes_exempt_from_decay(memory_tree, make_note):
    """日记豁免 decay（2026-09-13 用户裁决：日记是时间档案，保存而非复习）：
    闲置 60 天的日记不重算分层、不置待删、不计入衰减总数；
    同批普通笔记照常衰减。"""
    import os
    import time

    diary = make_note(memory_tree, filename="2026-07-15.md", content="那天的事")
    normal = make_note(memory_tree, filename="普通笔记.md", content="内容")
    old_ns = int((time.time() - 60 * 86400) * 1e9)
    for path in (diary, normal):
        os.utime(path, ns=(old_ns, old_ns))

    report = DecayManager(memory_tree).run()

    entry_diary = memory_tree._entry(diary)
    entry_normal = memory_tree._entry(normal)
    # 日记：豁免（confidence 保持登记初值 1.0，不置待删）
    assert entry_diary["confidence"] == 1.0
    assert entry_diary["pending_delete"] is False
    # 普通笔记：60 天闲置已被衰减到待删区
    assert entry_normal["pending_delete"] is True
    assert report["daily_exempt"] == 1
    assert report["total_notes"] == 1  # 只有普通笔记计入衰减


def test_daily_dir_also_exempt(memory_tree, make_note):
    """日记/ 子目录下的笔记同样豁免（不只看文件名）。"""
    subdir = memory_tree.notes_dir / "日记"
    subdir.mkdir()
    path = subdir / "碎碎念.md"
    path.write_text("---\ntitle: 碎碎念\n---\n\n内容\n", encoding="utf-8")
    import os
    import time
    old_ns = int((time.time() - 60 * 86400) * 1e9)
    os.utime(path, ns=(old_ns, old_ns))
    from scripts.memory.watcher import MemoryWatcher
    MemoryWatcher(memory_tree).process_pending()

    report = DecayManager(memory_tree).run()

    entry = memory_tree._entry(path)
    assert entry["pending_delete"] is False
    assert report["daily_exempt"] == 1


def test_book_cards_exempt_from_decay(memory_tree, make_note):
    """书籍档案卡豁免 decay（2026-09-14 KM 评审 P4：藏书记录是书架不是记忆）：
    闲置 60 天的书籍卡不降权、不置待删；同批普通笔记照常衰减。"""
    import os
    import time

    from scripts.memory.watcher import MemoryWatcher

    book_dir = memory_tree.notes_dir / "书籍" / "B84-心理学"
    book_dir.mkdir(parents=True)
    card = book_dir / "书籍-认知觉醒-abc123.md"
    card.write_text(
        "---\ntitle: 《认知觉醒》\ntype: Book\n---\n\n档案\n", encoding="utf-8"
    )
    normal = make_note(memory_tree, filename="普通笔记-书籍豁免对照.md", content="内容")
    old_ns = int((time.time() - 60 * 86400) * 1e9)
    for path in (card, normal):
        os.utime(path, ns=(old_ns, old_ns))
    MemoryWatcher(memory_tree).process_pending()

    report = DecayManager(memory_tree).run()

    entry_card = memory_tree._entry(card)
    entry_normal = memory_tree._entry(normal)
    assert entry_card["confidence"] == 1.0
    assert entry_card["pending_delete"] is False
    assert entry_normal["pending_delete"] is True
    assert report["book_exempt"] == 1
