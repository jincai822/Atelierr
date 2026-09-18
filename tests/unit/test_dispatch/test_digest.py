"""晨间摘要单元测试。

frontmatter 解析与分节为真实代码路径；无网络（摘要不联网）。
"""

from __future__ import annotations

import json
import os
import re
import time

import frontmatter

from scripts.dispatch.digest import DigestDispatcher


def _backdate_created(tree, filename: str, day: str) -> None:
    """把测试笔记 frontmatter 的 created 改为指定日期（YYYY-MM-DD）。"""
    path = tree.notes_dir / filename
    text = path.read_text(encoding="utf-8")
    text = re.sub(
        r"^created: .*$", f"created: '{day}T09:00:00+08:00'", text,
        count=1, flags=re.M,
    )
    path.write_text(text, encoding="utf-8")


def test_digest_created_with_sections(memory_tree):
    """摘要含三节；待确认/待办按标签归位；摘要自身不进列表。"""
    memory_tree.create_note("a.md", "待确认笔记", source="link", tags=["待确认", "抖音"])
    memory_tree.create_note("b.md", "- [ ] 做事", source="todo", tags=["待办", "待确认"])
    memory_tree.create_note("c.md", "- [ ] 已定", source="todo", tags=["待办"])
    memory_tree.create_note("d.md", "普通笔记", source="test")
    _backdate_created(memory_tree, "d.md", "2026-08-31")

    report = DigestDispatcher(memory_tree).run(today="2026-09-01")

    assert report["created"] == "系统/今日摘要-2026-09-01.md"
    post = frontmatter.loads(
        (memory_tree.notes_dir / report["created"]).read_text(encoding="utf-8")
    )
    assert post["source"] == "digest"
    assert post["tags"] == ["摘要"]
    assert post["id"] and post["created"]  # 与 create_note 同源的默认字段
    body = post.content
    assert "## ⏳ 待我确认（2）" in body
    assert "[[a]]" in body and "[[b]]" in body
    assert "## ✅ 待办进行中（2）" in body
    assert "[[c]]" in body
    assert "## 📥 昨日新入库（1）" in body
    assert "[[d]]" in body
    assert "今日摘要" not in body.split("昨日新入库")[1]  # 历史摘要不入列


def test_digest_idempotent_same_day(memory_tree):
    """当天已存在摘要：跳过，不重复建。"""
    dispatcher = DigestDispatcher(memory_tree)
    first = dispatcher.run(today="2026-09-01")

    second = dispatcher.run(today="2026-09-01")

    assert first["created"] == "系统/今日摘要-2026-09-01.md"
    assert second["skipped"] is True
    assert second["created"] is None


def test_digest_dry_run(memory_tree):
    """dry-run：返回内容但不建笔记。"""
    memory_tree.create_note("a.md", "待确认笔记", source="test", tags=["待确认"])

    report = DigestDispatcher(memory_tree).run(dry_run=True, today="2026-09-01")

    assert report["created"] is None
    assert "[[a]]" in report["markdown"]
    assert not (
        memory_tree.notes_dir / "系统" / "今日摘要-2026-09-01.md"
    ).exists()


def test_digest_empty_vault(memory_tree):
    """空库：五节都显示"无"，正常建。"""
    report = DigestDispatcher(memory_tree).run(today="2026-09-01")

    assert report["created"]
    assert report["markdown"].count("- 无") == 5


def test_digest_includes_resurface_section(memory_tree, make_note):
    """遗忘临界区笔记进"今日复习"节；摘要创建成功后写入冷却状态。"""
    make_note(memory_tree, "old.md", "旧笔记", idle_days=20)
    make_note(memory_tree, "fresh.md", "新笔记")

    report = DigestDispatcher(memory_tree).run(today="2026-09-01")

    assert report["counts"]["resurface"] == 1
    body = frontmatter.loads(
        (memory_tree.notes_dir / report["created"]).read_text(encoding="utf-8")
    ).content
    assert "## 🔁 今日复习（1）" in body
    assert "[[old]]" in body
    assert "先想" in body  # 检索式提示：先回忆再点开
    state = json.loads(
        (memory_tree.state_dir / "resurface.json").read_text(encoding="utf-8")
    )
    assert len(state) == 1

    # 冷却生效：次日（若摘要不存在）同一条不再推送
    from scripts.memory.resurface import ResurfaceManager

    assert ResurfaceManager(memory_tree).candidates() == []


def test_digest_dry_run_does_not_burn_cooldown(memory_tree, make_note):
    """dry-run：复习节照常渲染，但不写冷却状态、不建响应观测。"""
    make_note(memory_tree, "old.md", "旧笔记", idle_days=20)

    report = DigestDispatcher(memory_tree).run(dry_run=True, today="2026-09-01")

    assert "今日复习（1）" in report["markdown"]
    assert not (memory_tree.state_dir / "resurface.json").exists()
    assert not (memory_tree.state_dir / "response_probe.json").exists()


def test_digest_registers_and_resolves_probe(memory_tree, make_note):
    """推送复习笔记后建立响应观测；用户编辑后次日结案为响应。"""
    path = make_note(memory_tree, "old.md", "旧笔记", idle_days=20)

    DigestDispatcher(memory_tree).run(today="2026-09-01")
    state = json.loads(
        (memory_tree.state_dir / "response_probe.json").read_text(
            encoding="utf-8"
        )
    )
    assert len(state["pending"]) == 1

    ns = int(time.time() * 1e9)
    os.utime(path, ns=(ns, ns))  # 模拟用户当天加工了这条笔记
    DigestDispatcher(memory_tree).run(today="2026-09-02")

    state = json.loads(
        (memory_tree.state_dir / "response_probe.json").read_text(
            encoding="utf-8"
        )
    )
    assert state["pending"] == {}
    assert state["resolved"][0]["responded"] is True
    assert state["resolved"][0]["reason"] == "edited"


def test_digest_note_skipped_by_todos_dispatch(memory_tree):
    """摘要落 系统/（不进扫描域）；根层遗留摘要仍按 source 显式跳过。"""
    from scripts.dispatch.todos import TodoDispatcher

    DigestDispatcher(memory_tree).run(today="2026-09-01")

    report = TodoDispatcher(memory_tree).run()

    assert report["created"] == []
    assert report["scanned"] == 0  # 系统/ 里的摘要根本不进记忆扫描域

    # 双保险：根层遗留 source=digest 笔记仍被跳过（防摘要内容空转 LLM）
    memory_tree.create_note("legacy-摘要.md", "- [ ] 旧事", source="digest")
    report = TodoDispatcher(memory_tree).run()
    assert report["created"] == []
    assert report["skipped"] == 1


def test_digest_outside_memory_scan_domain(memory_tree):
    """摘要在 系统/：iter_note_files 扫不到，sidecar 索引也不登记。"""
    from scripts.memory.core import iter_note_files

    report = DigestDispatcher(memory_tree).run(today="2026-09-01")

    assert report["created"].startswith("系统/")
    scanned = [path.name for path in iter_note_files(memory_tree.notes_dir)]
    assert "今日摘要-2026-09-01.md" not in scanned


def _seed_probe(tree, pushes: dict) -> None:
    """直接铺 response_probe.json：{文件名: 已推送次数}（均已结案）。"""
    state = {"pending": {}, "resolved": []}
    for filename, count in pushes.items():
        for _ in range(count):
            state["resolved"].append(
                {
                    "note_id": filename,
                    "filename": filename,
                    "pushed_at": "2026-08-20T07:00:00+08:00",
                    "resolved_at": "2026-08-21T07:00:00+08:00",
                    "responded": False,
                    "reason": "expired",
                    "delay_hours": None,
                }
            )
    tree.state_dir.mkdir(parents=True, exist_ok=True)
    (tree.state_dir / "response_probe.json").write_text(
        json.dumps(state, ensure_ascii=False), encoding="utf-8"
    )


def test_digest_undistilled_section_and_frontmatter_bridge(memory_tree, make_note):
    """推送 ≥2 次且未提炼的笔记进"提炼候选"节，并写进 frontmatter 桥。"""
    make_note(memory_tree, "old.md", "反复被推送", idle_days=30)
    make_note(memory_tree, "once.md", "只推过一次", idle_days=30)
    _seed_probe(memory_tree, {"old.md": 2, "once.md": 1})

    report = DigestDispatcher(memory_tree).run(today="2026-09-01")

    assert report["counts"]["undistilled"] == 1
    assert "## 🧠 提炼候选（1）" in report["markdown"]
    section = report["markdown"].split("## 🧠 提炼候选")[1].split("## ✅")[0]
    assert "[[old]]" in section
    assert "[[once]]" not in section  # 只推过 1 次且创建未满 3 天
    post = frontmatter.loads(
        (memory_tree.notes_dir / report["created"]).read_text(encoding="utf-8")
    )
    assert post["undistilled"] == ["[[old]]"]  # 控制台 Dataview 桥


def test_digest_undistilled_excludes_distilled_and_gone(memory_tree, make_note):
    """已提炼（wiki 条目 from 引用）与已删除（purge）的笔记不进待提炼。"""
    make_note(memory_tree, "done.md", "已提炼", idle_days=30)
    _seed_probe(memory_tree, {"done.md": 3, "purged.md": 5})  # purged 无文件
    wiki_dir = memory_tree.notes_dir / "wiki"
    wiki_dir.mkdir(parents=True)
    (wiki_dir / "条目.md").write_text(
        "---\ncreated: '2026-09-01T09:00:00+08:00'\nsource: distilled\n"
        'from: "[[done]]"\n---\n\n正文\n',
        encoding="utf-8",
    )

    report = DigestDispatcher(memory_tree).run(today="2026-09-01")

    assert report["counts"]["undistilled"] == 0
    assert "## 🧠 提炼候选（0）" in report["markdown"]


def test_digest_surfaces_wiki_validate_issues(memory_tree, make_note):
    """wiki 体检：缺互链的条目在待提炼节末尾列出示。"""
    wiki_dir = memory_tree.notes_dir / "wiki"
    wiki_dir.mkdir(parents=True)
    (wiki_dir / "孤岛.md").write_text(
        "---\ncreated: '2026-09-01T09:00:00+08:00'\nsource: distilled\n"
        'from: "[[x]]"\n---\n\n没有互链的正文\n',
        encoding="utf-8",
    )

    report = DigestDispatcher(memory_tree).run(today="2026-09-01")

    assert "wiki 体检（1 条待修）" in report["markdown"]
    assert "[[孤岛]]" in report["markdown"]


def test_digest_distill_candidates_settled_rule(memory_tree):
    """沉一沉规则：已确认且创建满 3 天的笔记，无推送也进提炼候选。"""
    memory_tree.create_note("old.md", "旧内容", source="link")
    _backdate_created(memory_tree, "old.md", "2026-09-01")
    memory_tree.create_note("fresh.md", "新内容", source="link")
    _backdate_created(memory_tree, "fresh.md", "2026-09-09")

    report = DigestDispatcher(memory_tree).run(today="2026-09-10")

    assert report["counts"]["undistilled"] == 1
    section = report["markdown"].split("## 🧠 提炼候选")[1].split("## ✅")[0]
    assert "[[old]]" in section
    assert "[[fresh]]" not in section  # 创建未满 3 天，再沉一沉
    assert "提 N" in section  # CTA：机器起草、人「提/弃」审批（深加工链路）
    post = frontmatter.loads(
        (memory_tree.notes_dir / report["created"]).read_text(encoding="utf-8")
    )
    assert post["undistilled"] == ["[[old]]"]


def test_digest_distill_candidates_exclusions(memory_tree):
    """日报/门面/摘要/划重点清单/待确认/待办：再旧也不进提炼候选。"""
    cases = [
        ("2026-09-01.md", {}),  # 日报
        ("控制台.md", {}),  # 门面
        ("今日摘要-2026-09-01.md", {"source": "digest"}),  # 历史摘要
        ("清单.md", {"source": "highlights"}),  # 划重点清单容器
        ("pending.md", {"tags": ["待确认"]}),  # 未确认
        ("todo.md", {"tags": ["待办"]}),  # 行动项不是知识
    ]
    for name, kwargs in cases:
        memory_tree.create_note(name, "内容", **kwargs)
        _backdate_created(memory_tree, name, "2026-09-01")

    report = DigestDispatcher(memory_tree).run(today="2026-09-10")

    assert report["counts"]["undistilled"] == 0
    assert "## 🧠 提炼候选（0）" in report["markdown"]


def test_digest_distill_candidates_capped_oldest_first(memory_tree):
    """候选超过上限时截断到 5 条，最旧的优先留下。"""
    for i in range(7):
        name = f"n{i}.md"
        memory_tree.create_note(name, "内容")
        _backdate_created(memory_tree, name, f"2026-08-2{i}")

    report = DigestDispatcher(memory_tree).run(today="2026-09-10")

    assert report["counts"]["undistilled"] == 5
    section = report["markdown"].split("## 🧠 提炼候选")[1].split("## ✅")[0]
    assert "[[n0]]" in section  # 最旧
    assert "[[n4]]" in section
    assert "[[n5]]" not in section  # 超出上限被截掉
    assert "[[n6]]" not in section


def _touch(path, age_s):
    """写入文件并把 mtime 拨到 age_s 秒前。"""
    import os
    import time

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("x", encoding="utf-8")
    old = time.time() - age_s
    os.utime(path, (old, old))


def test_health_lines_all_fresh(memory_tree):
    """状态文件新鲜：全 ✅，异常 0。"""
    from scripts.dispatch.digest import _health_lines

    sd = memory_tree.state_dir
    for name in ("links", "media", "todos", "highlights"):
        _touch(sd / f"processed_{name}.json", 60)
    _touch(sd / "reports" / "decay-2026-09-10.md", 3600)

    lines, stale = _health_lines(sd)

    assert stale == 0
    assert len(lines) == 5
    assert all("✅" in line for line in lines)


def test_health_lines_missing_and_silent(memory_tree):
    """缺文件 / 沉默超阈值：记 ⚠️ 并计数；decay 看 reports/ 最新一份。"""
    from scripts.dispatch.digest import _health_lines

    sd = memory_tree.state_dir
    _touch(sd / "processed_links.json", 60)  # 新鲜
    _touch(sd / "processed_media.json", 3 * 3600)  # 沉默 > 2h
    # todos/highlights 缺文件；decay reports 目录为空
    (sd / "reports").mkdir(exist_ok=True)

    lines, stale = _health_lines(sd)

    assert stale == 4
    assert any("1 分钟前 ✅" in line for line in lines)
    assert any("沉默 3 小时前" in line for line in lines)
    assert sum("无状态文件" in line for line in lines) == 3


def test_age_text_boundaries():
    """沉默时长分档：分钟/小时/天。"""
    from scripts.dispatch.digest import _age_text

    assert _age_text(59) == "0 分钟前"
    assert _age_text(3600) == "1 小时前"
    assert _age_text(47 * 3600) == "47 小时前"
    assert _age_text(48 * 3600) == "2 天前"


def test_digest_markdown_has_health_section(memory_tree):
    """摘要 Markdown 含系统自检节；counts 带 health_stale。"""
    report = DigestDispatcher(memory_tree).run(today="2026-09-10")

    assert "## 🩺 系统自检" in report["markdown"]
    assert "health_stale" in report["counts"]
    assert report["counts"]["health_stale"] == 5  # 临时库全是缺文件


def test_digest_stale_pending_section(memory_tree):
    """滞留提醒（2026-09-12 裁决）：根目录待确认超 7 天逐条点名带天数；
    无「待确认」的已确认/人写旧笔记（超 14 天）进「你的笔记」组；
    新待确认、已归档（子目录）的都不计。"""
    memory_tree.create_note("old.md", "旧待确认", source="link", tags=["待确认"])
    _backdate_created(memory_tree, "old.md", "2026-08-20")
    memory_tree.create_note("new.md", "新待确认", source="link", tags=["待确认"])
    _backdate_created(memory_tree, "new.md", "2026-08-31")  # 未满 7 天
    memory_tree.create_note("done.md", "已确认的旧笔记", source="link", tags=[])
    _backdate_created(memory_tree, "done.md", "2026-08-01")  # 31 天 → 你的笔记组
    # 已归档进子目录的旧待确认：不算根目录滞留
    memory_tree.create_note("arch.md", "归档的待确认", source="link", tags=["待确认"])
    _backdate_created(memory_tree, "arch.md", "2026-08-01")
    subdir = memory_tree.notes_dir / "抖音"
    subdir.mkdir()
    (memory_tree.notes_dir / "arch.md").rename(subdir / "arch.md")

    report = DigestDispatcher(memory_tree).run(today="2026-09-01")

    body = report["markdown"]
    section = body.split("## ⏰")[1].split("## 🧠")[0]
    assert "## ⏰ 滞留提醒（2）" in body
    assert "### 待确认（1）" in body
    assert "[[old]]（滞留 12 天）" in section
    assert "[[new]]（滞留" not in section
    assert "### 你的笔记（1）" in body
    assert "[[done]]（你的笔记 · 滞留 31 天）" in section
    assert "[[arch]]" not in section
    assert report["counts"]["stale"] == 2


def test_digest_stale_human_notes(memory_tree):
    """你的笔记组（2026-09-12 入口收敛裁决⑤）：人写旧笔记被点名；
    日记、机器容器来源、子目录归档、未满 14 天的都不计。"""
    memory_tree.create_note("mine.md", "我的想法", source="web", tags=[])
    _backdate_created(memory_tree, "mine.md", "2026-08-15")  # 17 天
    memory_tree.create_note("young.md", "较新的想法", source="web", tags=[])
    _backdate_created(memory_tree, "young.md", "2026-08-20")  # 12 天，未满
    memory_tree.create_note("2026-08-10.md", "日记", source="web", tags=[])
    _backdate_created(memory_tree, "2026-08-10.md", "2026-08-10")
    memory_tree.create_note("digest_src.md", "机器容器", source="digest", tags=[])
    _backdate_created(memory_tree, "digest_src.md", "2026-08-01")
    # 已归档进子目录的人写旧笔记：不算根目录滞留
    memory_tree.create_note("filed.md", "已归档的想法", source="web", tags=[])
    _backdate_created(memory_tree, "filed.md", "2026-08-01")
    subdir = memory_tree.notes_dir / "想法"
    subdir.mkdir()
    (memory_tree.notes_dir / "filed.md").rename(subdir / "filed.md")

    report = DigestDispatcher(memory_tree).run(today="2026-09-01")

    body = report["markdown"]
    section = body.split("## ⏰")[1].split("## 🧠")[0]
    assert "### 你的笔记（1）" in body
    assert "[[mine]]（你的笔记 · 滞留 17 天）" in section
    assert "[[young]]" not in section
    assert "[[2026-08-10]]" not in section
    assert "[[digest_src]]" not in section
    assert "[[filed]]" not in section
    assert report["counts"]["stale"] == 1


def test_digest_stale_human_threshold(memory_tree):
    """你的笔记组阈值：13 天不点，15 天点（STALE_HUMAN_DAYS=14）。"""
    memory_tree.create_note("d13.md", "x", source="web", tags=[])
    _backdate_created(memory_tree, "d13.md", "2026-08-19")  # 13 天
    memory_tree.create_note("d15.md", "x", source="web", tags=[])
    _backdate_created(memory_tree, "d15.md", "2026-08-17")  # 15 天

    report = DigestDispatcher(memory_tree).run(today="2026-09-01")

    section = report["markdown"].split("## ⏰")[1].split("## 🧠")[0]
    assert "[[d15]]（你的笔记 · 滞留 15 天）" in section
    assert "[[d13]]" not in section


def test_digest_no_stale_no_section(memory_tree):
    """无滞留：不出「滞留提醒」节；counts['stale'] 为 0。"""
    memory_tree.create_note("fresh.md", "新待确认", source="link", tags=["待确认"])

    report = DigestDispatcher(memory_tree).run(today="2026-09-01")

    assert "滞留提醒" not in report["markdown"]
    assert report["counts"]["stale"] == 0


def test_digest_undistilled_backlink_path(memory_tree):
    """被别的笔记 [[引用]] ≥1 次即进提炼候选（2026-09-12 裁决②：
    沉淀从自己笔记里长出来；被引用者已是枢纽）。"""
    memory_tree.create_note("hub.md", "被引用的笔记", source="link", tags=[])
    memory_tree.create_note("ref.md", "详见 [[hub]] 的论述", source="test")

    report = DigestDispatcher(memory_tree).run(today="2026-09-01")

    section = report["markdown"].split("## 🧠 提炼候选")[1].split("## ✅")[0]
    assert "[[hub]]" in section
    assert "[[ref]]" not in section  # 引用别人不等于自己被引用


def test_digest_stale_wiki_recheck_section(memory_tree):
    """OKF Freshness：stale_after 到期的 stable 卡进晨报「到期复查」节（安静点名）。"""
    import frontmatter as fm

    wiki_dir = memory_tree.notes_dir / "wiki"
    wiki_dir.mkdir(parents=True)
    (wiki_dir / "老卡.md").write_text(
        fm.dumps(
            fm.Post(
                "正文\n",
                type="Excerpt",
                title="老卡",
                status="stable",
                stale_after="2026-09-01",
            )
        ),
        encoding="utf-8",
    )
    (wiki_dir / "新卡.md").write_text(
        fm.dumps(
            fm.Post(
                "正文\n",
                type="Excerpt",
                title="新卡",
                status="stable",
                stale_after="2027-01-01",
            )
        ),
        encoding="utf-8",
    )

    report = DigestDispatcher(memory_tree).run(today="2026-09-10")

    assert "wiki 到期复查（1）" in report["markdown"]
    assert "[[老卡]]" in report["markdown"]
    assert "[[新卡]]" not in report["markdown"].split("到期复查")[1]
