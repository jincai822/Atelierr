"""链接自动分发单元测试（无真实网络与模型）。

LinkProcessor 以 processor_factory 注入假实现；笔记扫描、状态幂等、
失败熔断、pending_delete 跳过均为真实代码路径。
"""

from __future__ import annotations

import json

import frontmatter
import pytest

import scripts.dispatch.links as links_module
from scripts.dispatch.links import LinkDispatcher
from scripts.processors.base import ProcessResult

DOUYIN_URL = "https://v.douyin.com/eQOGBXJdlwQ/"


class _FakeLinkProcessor:
    """假链接处理器：记录调用，返回固定成功结果。"""

    calls = []
    fail_with = None

    def __init__(self):
        pass

    def process(self, url):
        type(self).calls.append(url)
        if type(self).fail_with:
            return ProcessResult(success=False, error=type(self).fail_with)
        return ProcessResult(
            success=True,
            text="转写全文",
            markdown="# 视频标题\n\n## 转写全文\n\n你好",
            confidence=0.9,
            metadata={"video_id": "vid123", "segments": 1},
        )


@pytest.fixture(autouse=True)
def _reset_fake():
    """每个用例重置假处理器的调用记录与失败开关。"""
    _FakeLinkProcessor.calls = []
    _FakeLinkProcessor.fail_with = None
    yield


@pytest.fixture(autouse=True)
def _no_probe_network(monkeypatch):
    """单测不触网：同内容查重的元数据解析默认查无此证（None）。"""
    monkeypatch.setattr(links_module, "probe_video_id", lambda url: None)


def _dispatcher(tree):
    return LinkDispatcher(tree, processor_factory=_FakeLinkProcessor)


def test_processes_douyin_link(memory_tree):
    """含抖音链接的笔记 → 自动建带"待确认"标签的 douyin-<id>.md。"""
    memory_tree.create_note("daily.md", f"今天看到 {DOUYIN_URL} 不错", source="test")

    report = _dispatcher(memory_tree).run()

    assert report["found"] == 1
    assert report["created"] == ["douyin-vid123.md"]
    created = memory_tree.inbox_dir / "douyin-vid123.md"
    assert created.exists()
    post = frontmatter.loads(created.read_text(encoding="utf-8"))
    assert post["tags"] == ["待确认", "抖音"]
    assert post["source"] == "link"
    assert "## 转写全文" in post.content
    # 源笔记不被改写
    assert memory_tree.read_note(memory_tree.notes_dir / "daily.md").startswith("今天看到")
    state = json.loads((memory_tree.state_dir / "processed_links.json").read_text())
    assert state[DOUYIN_URL]["status"] == "done"


def test_idempotent_second_run(memory_tree):
    """同一链接第二轮扫描跳过，不重复建笔记。"""
    memory_tree.create_note("daily.md", f"链接 {DOUYIN_URL}", source="test")
    dispatcher = _dispatcher(memory_tree)
    dispatcher.run()

    report = dispatcher.run()

    assert report["created"] == []
    assert report["skipped"] == 1
    assert len(_FakeLinkProcessor.calls) == 1


def test_no_links_noop(memory_tree):
    """无链接笔记 → 什么都不做。"""
    memory_tree.create_note("plain.md", "没有链接的内容", source="test")

    report = _dispatcher(memory_tree).run()

    assert report["found"] == 0
    assert report["created"] == []


def test_pending_delete_skipped(memory_tree, make_note):
    """pending_delete 笔记里的链接不处理。"""
    make_note(memory_tree, filename="old.md", content=f"旧链接 {DOUYIN_URL}", idle_days=60)
    from scripts.memory.decay import DecayManager

    DecayManager(memory_tree).run()
    assert memory_tree.is_pending_delete(memory_tree.notes_dir / "old.md")

    report = _dispatcher(memory_tree).run()

    assert report["found"] == 0
    assert _FakeLinkProcessor.calls == []


def test_failure_retries_then_circuit_breaks(memory_tree):
    """失败重试：3 次后熔断，第 4 轮不再调用处理器。"""
    _FakeLinkProcessor.fail_with = "视频下载失败: 403"
    memory_tree.create_note("daily.md", f"链接 {DOUYIN_URL}", source="test")
    dispatcher = _dispatcher(memory_tree)

    for _ in range(3):
        report = dispatcher.run()
        assert report["created"] == []
        assert len(report["failed"]) == 1

    state = json.loads((memory_tree.state_dir / "processed_links.json").read_text())
    assert state[DOUYIN_URL]["attempts"] == 3
    assert state[DOUYIN_URL]["status"] == "failed"

    report = dispatcher.run()
    assert report["skipped"] == 1
    assert len(_FakeLinkProcessor.calls) == 3


def test_dry_run_creates_nothing(memory_tree):
    """dry-run 只报告：不建笔记、不写状态、不调处理器。"""
    memory_tree.create_note("daily.md", f"链接 {DOUYIN_URL}", source="test")

    report = _dispatcher(memory_tree).run(dry_run=True)

    assert report["found"] == 1
    assert report["created"] == []
    assert _FakeLinkProcessor.calls == []
    assert not (memory_tree.state_dir / "processed_links.json").exists()


def test_duplicate_note_tolerated(memory_tree):
    """状态丢失后重跑：同名笔记已存在时不抛异常，标记 done。"""
    memory_tree.create_note("daily.md", f"链接 {DOUYIN_URL}", source="test")
    memory_tree.create_note("douyin-vid123.md", "已存在的产出", source="link")

    report = _dispatcher(memory_tree).run()

    assert report["created"] == ["douyin-vid123.md"]
    state = json.loads((memory_tree.state_dir / "processed_links.json").read_text())
    assert state[DOUYIN_URL]["status"] == "done"


def test_cli_links_command(memory_tree, tmp_path, monkeypatch):
    """CLI 层：--config 指定配置，成功 exit 0。"""
    monkeypatch.setattr(links_module, "LinkProcessor", _FakeLinkProcessor)
    memory_tree.create_note("daily.md", f"链接 {DOUYIN_URL}", source="test")
    config = tmp_path / "memory.yaml"
    config.write_text(
        f"memory:\n  root: {memory_tree.notes_dir}\n"
        f"  state_dir: {memory_tree.state_dir}\n",
        encoding="utf-8",
    )
    from scripts.cli.dispatch_cli import DispatchCLI

    code = DispatchCLI(config_path=str(config)).main(["links"])

    assert code == 0
    assert (memory_tree.inbox_dir / "douyin-vid123.md").exists()


XHS_URL = "https://xhslink.cn/o/2Vhl2blNpHM"


class _FakeXhsProcessor:
    """假小红书处理器：返回带 note_id 的成功结果。"""

    def process(self, url):
        return ProcessResult(
            success=True,
            text="正文",
            markdown="# 小红书标题\n\n## 笔记正文\n\n内容",
            confidence=1.0,
            metadata={"note_id": "n123", "platform": "xhs"},
        )


def test_processes_xhs_link(memory_tree):
    """含小红书链接的笔记 → 自动建带"待确认"标签的 xhs-<id>.md。"""
    memory_tree.create_note("daily.md", f"看看这个 {XHS_URL}", source="test")

    report = LinkDispatcher(memory_tree, processor_factory=_FakeXhsProcessor).run()

    assert report["found"] == 1
    assert report["created"] == ["xhs-n123.md"]
    created = memory_tree.inbox_dir / "xhs-n123.md"
    assert created.exists()
    post = frontmatter.loads(created.read_text(encoding="utf-8"))
    assert post["tags"] == ["待确认", "小红书"]
    assert post["source"] == "link"
    # 源笔记不被改写
    assert memory_tree.read_note(memory_tree.notes_dir / "daily.md").startswith("看看这个")
    state = json.loads((memory_tree.state_dir / "processed_links.json").read_text())
    assert state[XHS_URL]["status"] == "done"


def test_mixed_platform_links(memory_tree):
    """抖音与小红书链接同一轮都能被收集处理。"""
    memory_tree.create_note(
        "daily.md", f"抖音 {DOUYIN_URL} 和小红书 {XHS_URL}", source="test"
    )

    class _MixedProcessor:
        def process(self, url):
            if "xhslink" in url:
                return ProcessResult(
                    success=True,
                    text="正文",
                    markdown="# t",
                    confidence=1.0,
                    metadata={"note_id": "n9"},
                )
            return ProcessResult(
                success=True,
                text="转写",
                markdown="# t",
                confidence=0.9,
                metadata={"video_id": "v9"},
            )

    report = LinkDispatcher(memory_tree, processor_factory=_MixedProcessor).run()

    assert sorted(report["created"]) == ["douyin-v9.md", "xhs-n9.md"]


def test_auto_note_links_not_recycled(memory_tree):
    """自动产出笔记（source: link）里的链接不回收——防自我循环回归。

    复现 2026-09-02 真实事故：小红书短链处理后，产出笔记来源行里的
    落地页 URL 与原短链字符串不同，被下一轮当成新链接重复下载转写。
    """
    memory_tree.create_note(
        "xhs-abc123.md",
        f"# 标题\n\n> 来源：小红书 @某人 {XHS_URL}\n\n正文",
        source="link",
        tags=["待确认", "小红书"],
    )

    report = _dispatcher(memory_tree).run()

    assert report["found"] == 0
    assert report["created"] == []
    # 人工笔记里的同一链接仍会被收集（跳过只针对自动产出）
    memory_tree.create_note("daily.md", f"再看一次 {XHS_URL}", source="test")
    report2 = _dispatcher(memory_tree).run()
    assert report2["found"] == 1
    assert report2["created"] == ["xhs-vid123.md"]


def test_title_based_filename(memory_tree):
    """产出文件名用 平台-标题（人读）；文件系统非法字符净化为 -。"""
    memory_tree.create_note("daily.md", f"链接 {DOUYIN_URL}", source="test")

    class _TitledProcessor:
        def process(self, url):
            return ProcessResult(
                success=True,
                text="t",
                markdown="# t",
                confidence=0.9,
                metadata={"video_id": "v1", "title": "健脑小课堂/运动篇"},
            )

    report = LinkDispatcher(memory_tree, processor_factory=_TitledProcessor).run()

    assert report["created"] == ["抖音-健脑小课堂-运动篇.md"]
    assert (memory_tree.inbox_dir / "抖音-健脑小课堂-运动篇.md").exists()


def test_title_fallback_to_id(memory_tree):
    """无标题时回退 平台-内容id 命名（现状兼容）。"""
    memory_tree.create_note("daily.md", f"链接 {DOUYIN_URL}", source="test")

    report = _dispatcher(memory_tree).run()

    assert report["created"] == ["douyin-vid123.md"]


def test_title_collision_appends_doc_id(memory_tree):
    """同名不同内容：追加内容 id 短码，不静默丢弃。"""
    memory_tree.create_note("daily.md", f"链接 {DOUYIN_URL}", source="test")
    memory_tree.create_note("抖音-撞名.md", "别人已占用的同名笔记", source="test")

    class _CollisionProcessor:
        def process(self, url):
            return ProcessResult(
                success=True,
                text="t",
                markdown="# t",
                confidence=0.9,
                metadata={"video_id": "v789", "title": "撞名"},
            )

    report = LinkDispatcher(memory_tree, processor_factory=_CollisionProcessor).run()

    assert report["created"] == ["抖音-撞名-v789.md"]
    assert (memory_tree.inbox_dir / "抖音-撞名-v789.md").exists()


def test_video_blob_saved_to_platform_dir(memory_tree):
    """处理器交回 video_blob/video_rel：dispatch 原子落盘 attachments/抖音/。"""
    memory_tree.create_note("daily.md", f"链接 {DOUYIN_URL}", source="test")

    class _VideoProcessor:
        def process(self, url):
            return ProcessResult(
                success=True,
                text="转写",
                markdown="# t\n\n![[attachments/抖音/抖音-t-v1.mp4]]\n",
                confidence=0.9,
                metadata={
                    "video_id": "v1",
                    "video_rel": "attachments/抖音/抖音-t-v1.mp4",
                    "video_blob": b"480p-bytes",
                },
            )

    report = LinkDispatcher(memory_tree, processor_factory=_VideoProcessor).run()

    assert report["created"]
    saved = memory_tree.attachments_dir / "抖音" / "抖音-t-v1.mp4"
    assert saved.read_bytes() == b"480p-bytes"
    # metadata 里的 blob 不泄漏进状态文件（bytes 不可 JSON 序列化）
    state = json.loads((memory_tree.state_dir / "processed_links.json").read_text())
    assert state[DOUYIN_URL]["status"] == "done"


def test_video_blob_existing_not_overwritten(memory_tree):
    """同路径视频已存在：跳过写入（同内容重跑幂等，绝不覆盖原件）。"""
    memory_tree.create_note("daily.md", f"链接 {DOUYIN_URL}", source="test")
    saved = memory_tree.attachments_dir / "抖音" / "抖音-t-v1.mp4"
    saved.parent.mkdir(parents=True)
    saved.write_bytes(b"original")

    class _VideoProcessor:
        def process(self, url):
            return ProcessResult(
                success=True,
                text="t",
                markdown="# t",
                confidence=0.9,
                metadata={
                    "video_id": "v1",
                    "video_rel": "attachments/抖音/抖音-t-v1.mp4",
                    "video_blob": b"new-bytes",
                },
            )

    LinkDispatcher(memory_tree, processor_factory=_VideoProcessor).run()

    assert saved.read_bytes() == b"original"


# ----------------------------------------------------------------------
# 用户评论提取（2026-09-10 裁决 C2：链接评论显示在确认卡）
# ----------------------------------------------------------------------


def test_comment_extracted_to_state_and_report(memory_tree):
    """链接旁的用户评论 → report['comments'] 与 state 双登记；指路词不算。"""
    memory_tree.create_note(
        "daily.md",
        f"{DOUYIN_URL} 这个讲得真好，回头细看",
        source="test",
    )

    report = _dispatcher(memory_tree).run()

    assert report["comments"] == {"douyin-vid123.md": "这个讲得真好，回头细看"}
    state = json.loads((memory_tree.state_dir / "processed_links.json").read_text())
    assert state[DOUYIN_URL]["comment"] == "这个讲得真好，回头细看"


def test_boilerplate_only_no_comment(memory_tree):
    """纯分享文本（抖音样板行）→ 无评论，不硬凑。"""
    memory_tree.create_note(
        "daily.md",
        f"1.58 复制打开抖音，看看【张三的作品】不错 {DOUYIN_URL} :1pm TLW:/",
        source="test",
    )

    report = _dispatcher(memory_tree).run()

    assert report["comments"] == {}
    state = json.loads((memory_tree.state_dir / "processed_links.json").read_text())
    assert "comment" not in state[DOUYIN_URL]


def test_extract_comment_helper():
    """extract_comment 单元：只认链接同一行（2026-09-14 实测：整篇扫描把
    日记里别的文字行误收成评论）；剥 URL、丢样板行、丢指路词、截断。"""
    from scripts.dispatch.links import extract_comment

    # 同一行：链接前的随手话保留
    assert extract_comment(f"值得二刷 {DOUYIN_URL}", DOUYIN_URL) == "值得二刷"
    # 评论在别的行（别的消息行）不算——防日记串行污染
    body = f"值得二刷\n链接 {DOUYIN_URL}\n复制打开抖音，看看【某人的作品】xx"
    assert extract_comment(body, DOUYIN_URL) == ""
    assert extract_comment(f"链接 {DOUYIN_URL}", DOUYIN_URL) == ""
    assert extract_comment("看看这个", "https://x.com") == ""
    # 同行超长截断 200 字
    long_line = f"{'评' * 300} {DOUYIN_URL}"
    assert len(extract_comment(long_line, DOUYIN_URL)) == 200


def test_extract_comment_strips_diary_timestamp():
    """日记行（- HH:MM 前缀，2026-09-12 碎片治理）：纯时间链接行无评论；
    同行带人话的剥掉前缀取干净评论。"""
    from scripts.dispatch.links import extract_comment

    assert extract_comment(f"- 21:04 {DOUYIN_URL}", DOUYIN_URL) == ""
    body = f"- 10:24 {DOUYIN_URL} 我想看里面的书！"
    assert extract_comment(body, DOUYIN_URL) == "我想看里面的书！"


BILIBILI_URL = "https://www.bilibili.com/video/BV1xx411c7mD"


def test_processes_bilibili_link(memory_tree):
    """B站链接 → 产出笔记带「待确认/B站」标签，文件名 B站-标题.md。"""
    memory_tree.create_note("daily.md", f"学习下 {BILIBILI_URL}", source="test")

    class _BiliProcessor:
        def process(self, url):
            return ProcessResult(
                success=True,
                text="转写",
                markdown="# t",
                confidence=0.9,
                metadata={"video_id": "BV1xx", "title": "认知科学入门"},
            )

    report = LinkDispatcher(memory_tree, processor_factory=_BiliProcessor).run()

    assert report["created"] == ["B站-认知科学入门.md"]
    created = memory_tree.inbox_dir / "B站-认知科学入门.md"
    assert created.exists()
    post = frontmatter.loads(created.read_text(encoding="utf-8"))
    assert post["tags"] == ["待确认", "B站"]
    assert post["source"] == "link"


def test_transcript_saved_to_attachments(memory_tree):
    """方案 B（2026-09-12）：处理器交回 transcript_rel/text 时，全文原子
    落盘 attachments/平台/；同名已存在跳过（幂等），落盘失败不阻断建卡。"""

    class _TxProcessor:
        def process(self, url):
            return ProcessResult(
                success=True,
                text="长全文",
                markdown=(
                    "# 视频标题\n\n## 全文\n\n"
                    "[[attachments/抖音/抖音-标题-vid123.md|查看转写全文]]"
                ),
                confidence=0.9,
                metadata={
                    "video_id": "vid123",
                    "title": "标题",
                    "transcript_rel": "attachments/抖音/抖音-标题-vid123.md",
                    "transcript_text": "这是很长的转写全文",
                },
            )

    memory_tree.create_note("daily.md", f"链接 {DOUYIN_URL}", source="test")
    dispatcher = LinkDispatcher(memory_tree, processor_factory=_TxProcessor)

    report = dispatcher.run()

    assert report["created"] == ["抖音-标题.md"]
    full = memory_tree.attachments_dir / "抖音/抖音-标题-vid123.md"
    assert full.exists()
    assert full.read_text(encoding="utf-8") == "这是很长的转写全文"
    # 同名跳过（幂等）：已有内容不被覆盖
    full.write_text("既有内容", encoding="utf-8")
    dispatcher._save_transcript(
        "attachments/抖音/抖音-标题-vid123.md", "新内容"
    )
    assert full.read_text(encoding="utf-8") == "既有内容"


def test_note_filename_strips_hash(memory_tree):
    """笔记文件名剔除「#」（wikilink 标题引用符，晨报 [[...]] 链接会断；
    2026-09-12 抖音通用标题 Douyin video #<id> 实测）。"""
    filename = LinkDispatcher._note_filename(
        DOUYIN_URL, "douyin", "vid123", "Douyin video #7674839354331095781"
    )
    assert "#" not in filename
    assert filename == "抖音-Douyin video 7674839354331095781.md"


def test_daily_note_annotated_with_backlink(memory_tree):
    """处理成功后在源日记行尾追加 → [[卡]] 回链（2026-09-12 用户裁决），
    mtime 还原（不进 confidence 时钟）。"""
    import time

    memory_tree.create_note(
        "2026-09-12.md",
        f"- 20:15 看看 {DOUYIN_URL}\n",
        source="lark",
    )
    diary = memory_tree.notes_dir / "2026-09-12.md"
    old_mtime = diary.stat().st_mtime
    time.sleep(0.02)  # 保证若被改写 mtime 必然变化

    report = _dispatcher(memory_tree).run()

    assert report["created"]
    stem = report["created"][0].removesuffix(".md")
    text = diary.read_text(encoding="utf-8")
    assert f"- 20:15 看看 {DOUYIN_URL} → [[{stem}]]" in text
    assert diary.stat().st_mtime == old_mtime


def test_non_daily_note_not_annotated(memory_tree):
    """非日记源笔记绝不改写（红线）。"""
    memory_tree.create_note("inbox.md", f"链接 {DOUYIN_URL}", source="test")

    _dispatcher(memory_tree).run()

    assert "→" not in (memory_tree.notes_dir / "inbox.md").read_text(
        encoding="utf-8"
    )


def test_annotation_idempotent(memory_tree):
    """行内已含回链不重复追加（重放/手工补链后重跑）。"""
    memory_tree.create_note(
        "2026-09-12.md",
        f"- 20:15 看看 {DOUYIN_URL} → [[douyin-vid123]]\n",
        source="lark",
    )
    dispatcher = _dispatcher(memory_tree)
    # 清掉状态让同一链接重跑一次（回链已在行内）
    dispatcher.run()
    (memory_tree.state_dir / "processed_links.json").unlink()
    before = (memory_tree.notes_dir / "2026-09-12.md").read_text(encoding="utf-8")

    dispatcher.run()

    after = (memory_tree.notes_dir / "2026-09-12.md").read_text(encoding="utf-8")
    assert before == after
    assert after.count("→ [[douyin-vid123]]") == 1


def test_extract_comment_no_cross_line_contamination():
    """2026-09-14 实测回归：日记里两条链接 + 一行独立文字——处理任一
    链接时，独立文字行绝不被误收为评论。"""
    from scripts.dispatch.links import extract_comment

    diary = (
        f"- 23:52 复制打开抖音，看看【甲的作品】内容… {DOUYIN_URL} 口令\n"
        "- 23:56 纯测试，不记录\n"
        f"- 23:54 {XHS_URL} 每个家庭不一样，要具体分析"
    )
    assert extract_comment(diary, DOUYIN_URL) == ""  # 抖音行无评论
    assert extract_comment(diary, XHS_URL) == "每个家庭不一样，要具体分析"
    # 独立文字行不属于任何链接
    assert "纯测试" not in extract_comment(diary, DOUYIN_URL)


def test_comment_injected_into_note_body(memory_tree):
    """链接评论注入产出卡正文（2026-09-14 裁决）：紧跟来源行、压在机器
    摘要前——用户原创必须沉淀进笔记，不许只活在通知卡上。"""

    class _SourceLineProcessor(_FakeLinkProcessor):
        def process(self, url):
            return ProcessResult(
                success=True,
                text="转写全文",
                markdown=(
                    "# 视频标题\n\n> 来源：抖音 @作者 "
                    f"{DOUYIN_URL}\n\n## 转写全文\n\n你好"
                ),
                confidence=0.9,
                metadata={"video_id": "vid123", "segments": 1},
            )

    memory_tree.create_note(
        "daily.md",
        f"{DOUYIN_URL} 这个讲得真好，回头细看",
        source="test",
    )

    LinkDispatcher(memory_tree, processor_factory=_SourceLineProcessor).run()

    card = memory_tree.inbox_dir / "douyin-vid123.md"
    text = card.read_text(encoding="utf-8")
    lines = text.splitlines()
    source_idx = next(i for i, ln in enumerate(lines) if ln.startswith("> 来源："))
    assert lines[source_idx + 1] == "> 💬 我的评论：这个讲得真好，回头细看"
    # 评论节压在第一个 ## 摘要/正文节之前
    first_section = next(i for i, ln in enumerate(lines) if ln.startswith("## "))
    assert source_idx + 1 < first_section


def test_inject_comment_edge_cases():
    """无评论原样返回；无来源行（异常形态）不硬凑。"""
    from scripts.dispatch.links import _inject_comment

    md = "# 标题\n\n> 来源：抖音 u\n\n## 正文\n\nx"
    assert _inject_comment(md, "") == md
    assert "> 💬 我的评论：好" in _inject_comment(md, "好")
    no_source = "# 标题\n\n## 正文\n\nx"
    assert _inject_comment(no_source, "好") == no_source


def test_xhs_share_template_stripped_from_comment(memory_tree):
    """小红书分享样板清洗（2026-09-14 真实样本）：条目号/【标题块】/
    😆分享码😆 全剥掉，只留下真评论。"""
    xhs_url = "https://www.xiaohongshu.com/discovery/item/abc123"
    memory_tree.create_note(
        "2026-09-14.md",
        f"- 22:24 18 【头等舱采访：AI是未来必备能力！ - 艾维奇Vic | 小红书 - "
        f"你的生活兴趣社区】 😆 6BATqBI2pevQVyh 😆 {xhs_url}  AI 是必备技能",
        source="test",
    )

    from scripts.dispatch.links import extract_comment

    comment = extract_comment(memory_tree.read_note(
        memory_tree.notes_dir / "2026-09-14.md"
    ), xhs_url)
    assert comment == "AI 是必备技能"


def test_numeric_leading_comment_kept(memory_tree):
    """用户以数字开头的真评论（"3 点感悟"）不被模板清洗误伤。"""
    from scripts.dispatch.links import extract_comment

    body = f"{DOUYIN_URL} 3 点感悟都适用"
    assert extract_comment(body, DOUYIN_URL) == "3 点感悟都适用"


def test_bilibili_nested_share_block_stripped():
    """B站分享模板的嵌套方括号块整块剥掉（2026-09-15 真实样本：
    【【系列】标题-哔哩哔哩】——关键词写作"哔哩哔哩"且括号嵌套，
    旧正则既不认这个词也跨不过内层 】）。"""
    from scripts.dispatch.links import extract_comment

    url = "https://b23.tv/z9jwrj8"
    body = (
        f"- 08:39 【【DFMEA案例分享】DFMEA中的客户需求识别与分解-上-哔哩哔哩】"
        f" {url}  dfmea"
    )
    assert extract_comment(body, url) == "dfmea"


def test_bilibili_simple_share_block_stripped():
    """B站单层模板同样剥掉；真评论里的书名号/方括号观感词不误伤。"""
    from scripts.dispatch.links import extract_comment

    url = "https://b23.tv/abc123"
    assert (
        extract_comment(f"【认知科学入门-哔哩哔哩】 {url} 值得二刷", url)
        == "值得二刷"
    )
    assert extract_comment(f"{url} 想看《心理学与生活》", url) == "想看《心理学与生活》"


def test_video_id_registered_on_success(memory_tree):
    """处理成功后 state 登记 video_id（同内容幂等的比对依据）。"""
    memory_tree.create_note("daily.md", f"学习 {DOUYIN_URL}", source="test")

    _dispatcher(memory_tree).run()

    state = json.loads((memory_tree.state_dir / "processed_links.json").read_text())
    assert state[DOUYIN_URL]["video_id"] == "vid123"


def test_same_video_new_shortlink_skipped(memory_tree, monkeypatch):
    """同一视频换短链重发：命中已登记 video_id → 跳过，不下载不转写
    不建卡（2026-09-15 实证：同一 BV 视频两个 b23 短链被处理两遍，
    重复下载 39MB+重复转写）。"""
    monkeypatch.setattr(links_module, "probe_video_id", lambda url: "vid123")
    memory_tree.create_note("daily.md", f"学习 {DOUYIN_URL}", source="test")
    first = _dispatcher(memory_tree).run()
    assert first["created"] == ["douyin-vid123.md"]

    other = "https://v.douyin.com/anotherShare/"
    memory_tree.create_note("daily2.md", f"再看 {other}", source="test")
    _FakeLinkProcessor.calls = []
    report = _dispatcher(memory_tree).run()

    assert report["duplicates"] == [other]
    assert report["created"] == []
    assert not _FakeLinkProcessor.calls  # 处理器根本没被调用
    state = json.loads((memory_tree.state_dir / "processed_links.json").read_text())
    assert state[other]["status"] == "done"
    assert state[other]["duplicate"] is True
    assert state[other]["video_id"] == "vid123"


def test_different_video_processes_normally(memory_tree, monkeypatch):
    """内容 id 不同（或解析不到）→ 查重不拦，照常处理。"""
    memory_tree.create_note("daily.md", f"学习 {DOUYIN_URL}", source="test")
    _dispatcher(memory_tree).run()

    other = "https://v.douyin.com/anotherShare/"
    monkeypatch.setattr(links_module, "probe_video_id", lambda url: "vid999")
    memory_tree.create_note("daily2.md", f"再看 {other}", source="test")
    _FakeLinkProcessor.calls = []
    report = _dispatcher(memory_tree).run()

    assert _FakeLinkProcessor.calls == [other]
    assert report["duplicates"] == []
    state = json.loads((memory_tree.state_dir / "processed_links.json").read_text())
    assert state[other]["status"] == "done"


def test_image_blobs_saved_to_attachments(memory_tree):
    """图文图集字节由 dispatch 落盘 attachments/（与视频同规：同名幂等）。"""

    class _ImageNoteProcessor(_FakeLinkProcessor):
        def process(self, url):
            return ProcessResult(
                success=True,
                text="正文",
                markdown="# 图文\n\n> 来源：小红书 u\n\n正文",
                metadata={
                    "video_id": "img1",
                    "image_blobs": [
                        ("attachments/小红书/小红书-t-img1-01.jpg", b"img-a"),
                        ("attachments/小红书/小红书-t-img1-02.jpg", b"img-b"),
                    ],
                },
            )

    memory_tree.create_note("daily.md", f"看看 {DOUYIN_URL}", source="test")

    LinkDispatcher(memory_tree, processor_factory=_ImageNoteProcessor).run()

    base = memory_tree.attachments_dir.parent
    assert (base / "attachments/小红书/小红书-t-img1-01.jpg").read_bytes() == b"img-a"
    assert (base / "attachments/小红书/小红书-t-img1-02.jpg").read_bytes() == b"img-b"
