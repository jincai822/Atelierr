"""附件自动路由单元测试（无真实 OCR/Whisper，处理器以工厂注入假实现）。

附件扫描、状态幂等、失败熔断、mtime 防半文件守卫、直发视频路由
（仅 媒体/ 目录）与 480p 替换原件均为真实代码路径；压缩以
monkeypatch 替换 ``scripts.dispatch.media.compress_to_480p``。
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

import frontmatter
import pytest

from scripts.dispatch import media as media_module
from scripts.dispatch.media import MediaDispatcher
from scripts.processors.base import ProcessResult


class _FakeImageProcessor:
    """假图片处理器：记录调用，返回固定 OCR 结果。"""

    calls = []
    fail_with = None

    def process(self, path):
        type(self).calls.append(str(path))
        if type(self).fail_with:
            return ProcessResult(success=False, error=type(self).fail_with)
        return ProcessResult(
            success=True, text="OCR 识别文本", markdown="", confidence=0.9,
        )


class _FakeAudioProcessor:
    """假音频处理器：记录调用，返回固定转写结果。"""

    calls = []
    fail_with = None

    def process(self, path):
        type(self).calls.append(str(path))
        if type(self).fail_with:
            return ProcessResult(success=False, error=type(self).fail_with)
        return ProcessResult(
            success=True, text="转写文本。", markdown="", confidence=0.8,
        )


class _FakeVideoProcessor:
    """假视频处理器：记录调用，返回固定转写结果。"""

    calls = []
    fail_with = None

    def process(self, path):
        type(self).calls.append(str(path))
        if type(self).fail_with:
            return ProcessResult(success=False, error=type(self).fail_with)
        return ProcessResult(
            success=True, text="视频转写文本。", markdown="", confidence=0.8,
        )


def _fake_compress_ok(src, dst, ffmpeg="ffmpeg"):
    """假压缩成功：写出更小的"480p"字节并返回 True。"""
    Path(dst).write_bytes(b"480p-bytes")
    return True


@pytest.fixture(autouse=True)
def _reset_fakes():
    """每个用例重置假处理器的调用记录与失败开关。"""
    for fake in (_FakeImageProcessor, _FakeAudioProcessor, _FakeVideoProcessor):
        fake.calls = []
        fake.fail_with = None
    yield


def _dispatcher(tree):
    return MediaDispatcher(
        tree,
        image_factory=_FakeImageProcessor,
        audio_factory=_FakeAudioProcessor,
        video_factory=_FakeVideoProcessor,
    )


def _add_attachment(tree, name="IMG_001.png", age_seconds=60, subdir=""):
    """在 attachments/ 落一个假附件并回拨 mtime（避开 30s 防半文件守卫）。

    attachments/ 2026-09-13 起在数据根平级（tree.attachments_dir）。"""
    attach = Path(tree.attachments_dir)
    if subdir:
        attach = attach / subdir
    attach.mkdir(parents=True, exist_ok=True)
    path = attach / name
    path.write_bytes(b"\x89PNG fake-bytes")
    old = time.time() - age_seconds
    os.utime(path, (old, old))
    return path


def _created_note(tree):
    # 产出卡落中转站（2026-09-13 拆分：memory/ 只存真记忆）
    notes = list(Path(tree.inbox_dir).glob("media-*.md"))
    assert len(notes) == 1
    return notes[0]


def test_image_creates_note(memory_tree):
    """截图 → OCR → 建带"待确认/截图"标签的笔记，内嵌原图。"""
    _add_attachment(memory_tree, "IMG_001.png")

    report = _dispatcher(memory_tree).run()

    assert report["found"] == 1
    assert len(report["created"]) == 1
    note = _created_note(memory_tree)
    post = frontmatter.loads(note.read_text(encoding="utf-8"))
    assert post["tags"] == ["待确认", "截图"]
    assert post["source"] == "media"
    assert "![[attachments/IMG_001.png]]" in post.content
    assert "## OCR 全文" in post.content
    assert "OCR 识别文本" in post.content
    state = json.loads(
        (memory_tree.state_dir / "processed_media.json").read_text()
    )
    assert state["attachments/IMG_001.png"]["status"] == "done"


def test_audio_creates_note(memory_tree):
    """录音 → Whisper → 建带"待确认/录音"标签的笔记，内嵌音频。"""
    _add_attachment(memory_tree, "voice_001.m4a")

    report = _dispatcher(memory_tree).run()

    assert report["found"] == 1
    note = _created_note(memory_tree)
    post = frontmatter.loads(note.read_text(encoding="utf-8"))
    assert post["tags"] == ["待确认", "录音"]
    assert "![[attachments/voice_001.m4a]]" in post.content
    assert "## 转写全文" in post.content
    assert "转写文本。" in post.content
    assert _FakeImageProcessor.calls == []
    assert len(_FakeAudioProcessor.calls) == 1


def test_idempotent_second_run(memory_tree):
    """同一附件第二轮扫描跳过，不重复建笔记、不再调处理器。"""
    _add_attachment(memory_tree, "IMG_001.png")
    dispatcher = _dispatcher(memory_tree)
    dispatcher.run()

    report = dispatcher.run()

    assert report["created"] == []
    assert report["skipped"] == 1
    assert len(_FakeImageProcessor.calls) == 1


def test_unsupported_files_ignored(memory_tree):
    """非图片/音频文件与隐藏文件不进入扫描。"""
    _add_attachment(memory_tree, "notes.txt")
    _add_attachment(memory_tree, "anim.gif")
    _add_attachment(memory_tree, ".hidden.png")

    report = _dispatcher(memory_tree).run()

    assert report["scanned"] == 0
    assert report["found"] == 0
    assert _FakeImageProcessor.calls == []


def test_too_new_file_skipped(memory_tree):
    """mtime 距今不足 30 秒的文件本轮跳过（可能仍在写入）。"""
    _add_attachment(memory_tree, "IMG_fresh.png", age_seconds=0)

    report = _dispatcher(memory_tree).run()

    assert report["scanned"] == 1
    assert report["found"] == 0
    assert _FakeImageProcessor.calls == []
    state_path = memory_tree.state_dir / "processed_media.json"
    if state_path.exists():
        state = json.loads(state_path.read_text())
        assert "attachments/IMG_fresh.png" not in state


def test_missing_attachments_dir_noop(memory_tree):
    """attachments/ 不存在：空报告，不报错。"""
    report = _dispatcher(memory_tree).run()

    assert report == {
        "scanned": 0, "found": 0, "created": [], "failed": [], "skipped": 0,
        "imported": 0,
    }


def test_failure_retries_then_circuit_breaks(memory_tree):
    """失败重试：3 次后熔断，第 4 轮不再调用处理器。"""
    _FakeImageProcessor.fail_with = "OCR 失败: 引擎崩溃"
    _add_attachment(memory_tree, "IMG_001.png")
    dispatcher = _dispatcher(memory_tree)

    for _ in range(3):
        report = dispatcher.run()
        assert report["created"] == []
        assert len(report["failed"]) == 1

    state = json.loads(
        (memory_tree.state_dir / "processed_media.json").read_text()
    )
    assert state["attachments/IMG_001.png"]["attempts"] == 3
    assert state["attachments/IMG_001.png"]["status"] == "failed"

    report = dispatcher.run()
    assert report["skipped"] == 1
    assert len(_FakeImageProcessor.calls) == 3


def test_dry_run_creates_nothing(memory_tree):
    """dry-run 只报告：不建笔记、不写状态、不构造引擎。"""
    constructed = []
    _add_attachment(memory_tree, "IMG_001.png")

    def _spy_factory():
        constructed.append(1)
        return _FakeImageProcessor()

    dispatcher = MediaDispatcher(memory_tree, image_factory=_spy_factory)
    report = dispatcher.run(dry_run=True)

    assert report["found"] == 1
    assert report["created"] == []
    assert constructed == []
    assert not list(Path(memory_tree.inbox_dir).glob("media-*.md"))
    assert not (memory_tree.state_dir / "processed_media.json").exists()


def test_attachment_file_untouched(memory_tree):
    """原附件绝不改写：内容与 mtime 处理后保持不变。"""
    path = _add_attachment(memory_tree, "IMG_001.png")
    before = (path.read_bytes(), path.stat().st_mtime_ns)

    _dispatcher(memory_tree).run()

    assert path.read_bytes() == before[0]
    assert path.stat().st_mtime_ns == before[1]


def test_duplicate_note_tolerated(memory_tree):
    """状态丢失后重跑：同名笔记已存在时不抛异常，标记 done。"""
    path = _add_attachment(memory_tree, "IMG_001.png")
    from scripts.dispatch.media import MediaDispatcher as _md

    filename = _md(memory_tree)._note_filename(path)
    memory_tree.create_note(filename, "已存在的产出", source="media")

    report = _dispatcher(memory_tree).run()

    assert report["created"] == [filename]
    state = json.loads(
        (memory_tree.state_dir / "processed_media.json").read_text()
    )
    assert state["attachments/IMG_001.png"]["status"] == "done"


def test_media_subdir_processed(memory_tree):
    """平台子目录（媒体/）里的附件照常处理：状态键与内嵌用相对路径。"""
    _add_attachment(memory_tree, "IMG_002.png", subdir="媒体")

    report = _dispatcher(memory_tree).run()

    assert report["found"] == 1
    note = _created_note(memory_tree)
    post = frontmatter.loads(note.read_text(encoding="utf-8"))
    assert "![[attachments/媒体/IMG_002.png]]" in post.content
    state = json.loads(
        (memory_tree.state_dir / "processed_media.json").read_text()
    )
    assert state["attachments/媒体/IMG_002.png"]["status"] == "done"


def test_same_name_in_two_subdirs_both_processed(memory_tree):
    """不同子目录的同名附件不撞笔记名（状态键/笔记哈希都按相对路径）。"""
    _add_attachment(memory_tree, "IMG_003.png", subdir="媒体")
    _add_attachment(memory_tree, "IMG_003.png")

    report = _dispatcher(memory_tree).run()

    assert report["found"] == 2
    assert len(report["created"]) == 2
    assert len(list(Path(memory_tree.inbox_dir).glob("media-*.md"))) == 2


def test_video_in_platform_dir_referenced_skipped(memory_tree):
    """抖音/ 里**已被产出卡引用**的 .mp4（links 管线保存的原视频）跳过——
    防自产自吃（2026-09-13 起由引用判定替代目录限定）。"""
    _add_attachment(memory_tree, "抖音-健脑-vid123.mp4", subdir="抖音")
    memory_tree.create_note(
        "抖音-健脑.md",
        "# x\n\n![[attachments/抖音/抖音-健脑-vid123.mp4]]\n",
        source="link",
        tags=["待确认", "抖音"],
    )

    report = _dispatcher(memory_tree).run()

    assert report["found"] == 0
    assert _FakeVideoProcessor.calls == []


def test_video_in_platform_dir_unreferenced_processed(memory_tree, monkeypatch):
    """抖音/ 里**未被引用**的 .mp4（用户手动投错目录的视频）照常处理——
    "投错子目录也认得"覆盖视频（2026-09-13 裁决）。"""
    monkeypatch.setattr(media_module, "compress_to_480p", _fake_compress_ok)
    _add_attachment(memory_tree, "manual.mp4", subdir="抖音")

    report = _dispatcher(memory_tree).run()

    assert report["found"] == 1
    assert len(report["created"]) == 1
    note = _created_note(memory_tree)
    assert "![[attachments/抖音/manual.mp4]]" in note.read_text(encoding="utf-8")


# ----------------------------------------------------------------------
# 截图专用文件夹导入（2026-09-10 用户裁决 E4：只认专用夹，复制不移动）
# ----------------------------------------------------------------------


def _make_inbox(tmp_path, files=("shot_a.png",)):
    """造一个截图专用文件夹，放入指定文件并回拨 mtime。"""
    inbox = tmp_path / "进系统"
    inbox.mkdir()
    for name in files:
        path = inbox / name
        path.write_bytes(b"\x89PNG inbox-bytes")
        old = time.time() - 120
        os.utime(path, (old, old))
    return inbox


def test_inbox_imports_images(memory_tree, tmp_path):
    """专用夹里的截图：复制进 attachments/媒体/ 并同轮 OCR；原图留原地。"""
    inbox = _make_inbox(tmp_path)
    dispatcher = MediaDispatcher(
        memory_tree,
        image_factory=_FakeImageProcessor,
        audio_factory=_FakeAudioProcessor,
        screenshot_inbox=str(inbox),
    )

    report = dispatcher.run()

    assert report["imported"] == 1
    assert report["found"] == 1
    copied = memory_tree.attachments_dir / "媒体" / "shot_a.png"
    assert copied.read_bytes() == b"\x89PNG inbox-bytes"
    assert (inbox / "shot_a.png").exists()  # 复制不移动
    note = _created_note(memory_tree)
    post = frontmatter.loads(note.read_text(encoding="utf-8"))
    assert "![[attachments/媒体/shot_a.png]]" in post.content


def test_inbox_only_images_and_no_overwrite(memory_tree, tmp_path):
    """非图片不导入；目标已存在绝不覆盖（同内容重跑幂等）。"""
    inbox = _make_inbox(tmp_path, files=("shot_b.png", "notes.txt", ".hidden.png"))
    dest = memory_tree.attachments_dir / "媒体" / "shot_b.png"
    dest.parent.mkdir(parents=True)
    dest.write_bytes(b"existing")
    dispatcher = MediaDispatcher(
        memory_tree,
        image_factory=_FakeImageProcessor,
        audio_factory=_FakeAudioProcessor,
        screenshot_inbox=str(inbox),
    )

    report = dispatcher.run()

    assert report["imported"] == 0
    assert dest.read_bytes() == b"existing"


def test_inbox_missing_dir_noop(memory_tree):
    """专用夹不存在：静默跳过（不报错、不导入）。"""
    dispatcher = MediaDispatcher(
        memory_tree,
        image_factory=_FakeImageProcessor,
        audio_factory=_FakeAudioProcessor,
        screenshot_inbox="/nonexistent/进系统",
    )

    report = dispatcher.run()

    assert report["imported"] == 0
    assert report["found"] == 0


def test_inbox_dry_run_no_copy(memory_tree, tmp_path):
    """dry-run：报告将导入的数量但不复制、不处理。"""
    inbox = _make_inbox(tmp_path)
    dispatcher = MediaDispatcher(
        memory_tree,
        image_factory=_FakeImageProcessor,
        audio_factory=_FakeAudioProcessor,
        screenshot_inbox=str(inbox),
    )

    report = dispatcher.run(dry_run=True)

    assert report["imported"] == 1
    assert not (memory_tree.attachments_dir / "媒体").exists()


def test_inbox_disabled_by_default(memory_tree, tmp_path):
    """未配置专用夹：不导入（默认行为不变）。"""
    _make_inbox(tmp_path)  # 与 memory_tree 无关的目录，不应被读到

    report = _dispatcher(memory_tree).run()

    assert report["imported"] == 0


# ----------------------------------------------------------------------
# 直发视频（2026-09-11 用户裁决：飞书直接发视频 → 转写 + 压 480p 替换原件）
# ----------------------------------------------------------------------


def test_video_creates_note_and_replaces_with_480p(memory_tree, monkeypatch):
    """媒体/ 里的视频：转写建「待确认/视频」笔记 + 压 480p 替换原件（裁决 B）。"""
    monkeypatch.setattr(media_module, "compress_to_480p", _fake_compress_ok)
    path = _add_attachment(memory_tree, "clip.mp4", subdir="媒体")

    report = _dispatcher(memory_tree).run()

    assert report["found"] == 1
    assert len(report["created"]) == 1
    note = _created_note(memory_tree)
    post = frontmatter.loads(note.read_text(encoding="utf-8"))
    assert post["tags"] == ["待确认", "视频"]
    assert post["source"] == "media"
    assert "![[attachments/媒体/clip.mp4]]" in post.content
    assert "## 转写全文" in post.content
    assert "视频转写文本。" in post.content
    # 原件已被 480p 同路径替换
    assert path.read_bytes() == b"480p-bytes"
    state = json.loads(
        (memory_tree.state_dir / "processed_media.json").read_text()
    )
    assert state["attachments/媒体/clip.mp4"]["status"] == "done"


def test_video_outside_media_subdir_also_processed(memory_tree, monkeypatch):
    """顶层散放与书籍/ 里的 mp4 同样认得（2026-09-13 起视频全目录认；
    防自产自吃靠引用判定，见上两条用例）。"""
    monkeypatch.setattr(media_module, "compress_to_480p", _fake_compress_ok)
    _add_attachment(memory_tree, "loose.mp4")
    _add_attachment(memory_tree, "odd.mp4", subdir="书籍")

    report = _dispatcher(memory_tree).run()

    assert report["found"] == 2
    assert len(report["created"]) == 2


def test_video_compress_failure_keeps_original(memory_tree, monkeypatch):
    """压缩失败：保留原件保底（绝不压坏了还丢原件），笔记照常创建。"""
    monkeypatch.setattr(
        media_module, "compress_to_480p", lambda *a, **k: False
    )
    path = _add_attachment(memory_tree, "clip.mp4", subdir="媒体")
    original = path.read_bytes()

    report = _dispatcher(memory_tree).run()

    assert len(report["created"]) == 1
    assert path.read_bytes() == original
    note = _created_note(memory_tree)
    assert "![[attachments/媒体/clip.mp4]]" in note.read_text(encoding="utf-8")


def test_video_transcribe_failure_no_compress(memory_tree, monkeypatch):
    """转写失败：不压缩、原件不动、计入失败熔断。"""
    calls = []

    def _spy_compress(src, dst, ffmpeg="ffmpeg"):
        calls.append(1)
        return True

    monkeypatch.setattr(media_module, "compress_to_480p", _spy_compress)
    _FakeVideoProcessor.fail_with = "Whisper 失败"
    path = _add_attachment(memory_tree, "clip.mp4", subdir="媒体")
    original = path.read_bytes()

    report = _dispatcher(memory_tree).run()

    assert report["created"] == []
    assert len(report["failed"]) == 1
    assert calls == []
    assert path.read_bytes() == original


def test_video_idempotent_second_run(memory_tree, monkeypatch):
    """同一视频第二轮不重处理：产出卡已内嵌引用该附件，第二轮在引用
    过滤阶段就跳过（比状态表幂等更早一层，2026-09-13 引用判定）。"""
    monkeypatch.setattr(media_module, "compress_to_480p", _fake_compress_ok)
    path = _add_attachment(memory_tree, "clip.mp4", subdir="媒体")
    dispatcher = _dispatcher(memory_tree)
    dispatcher.run()
    # 替换后 mtime 是当下（正中 30s 防半文件守卫）——回拨模拟下一轮班次
    old = time.time() - 60
    os.utime(path, (old, old))

    report = dispatcher.run()

    assert report["created"] == []
    assert report["found"] == 0
    assert len(_FakeVideoProcessor.calls) == 1


def test_long_text_externalized_to_attachments(memory_tree):
    """方案 B（2026-09-12）：全文 >800 字符外置 attachments/媒体/<同名>.md，
    卡上只留「## 全文」链接节；内嵌原件不变；同名再调不覆盖。"""
    long_text = "长文本。" * 400  # 1600 字符

    class _LongImage(_FakeImageProcessor):
        def process(self, path):
            return ProcessResult(
                success=True, text=long_text, markdown="", confidence=0.9
            )

    _add_attachment(memory_tree, "IMG_001.png")
    dispatcher = MediaDispatcher(
        memory_tree,
        image_factory=_LongImage,
        audio_factory=_FakeAudioProcessor,
        video_factory=_FakeVideoProcessor,
    )
    report = dispatcher.run()

    assert report["found"] == 1
    note = _created_note(memory_tree)
    post = frontmatter.loads(note.read_text(encoding="utf-8"))
    assert "## OCR 全文" not in post.content
    assert "![[attachments/IMG_001.png]]" in post.content
    rel = f"attachments/媒体/{note.stem}.md"
    assert f"## 全文\n\n[[{rel}|查看OCR 全文]]" in post.content
    full = memory_tree.attachments_dir.parent / rel
    assert full.exists()
    assert full.read_text(encoding="utf-8") == long_text
    # 同名跳过（幂等）：再调一次不改写既有全文
    dispatcher._build_note(
        memory_tree.attachments_dir / "IMG_001.png",
        "截图",
        "另一份全文",
        note.stem,
    )
    assert full.read_text(encoding="utf-8") == long_text


def test_externalize_write_failure_falls_back_inline(memory_tree, monkeypatch):
    """全文落盘失败：降级卡内联保底，卡不丢内容。"""
    long_text = "长文本。" * 400

    class _LongImage(_FakeImageProcessor):
        def process(self, path):
            return ProcessResult(
                success=True, text=long_text, markdown="", confidence=0.9
            )

    monkeypatch.setattr(
        media_module, "write_text_skip_existing", lambda target, text: False
    )
    _add_attachment(memory_tree, "IMG_001.png")
    dispatcher = MediaDispatcher(
        memory_tree,
        image_factory=_LongImage,
        audio_factory=_FakeAudioProcessor,
        video_factory=_FakeVideoProcessor,
    )
    report = dispatcher.run()

    assert report["found"] == 1
    note = _created_note(memory_tree)
    post = frontmatter.loads(note.read_text(encoding="utf-8"))
    assert "## OCR 全文" in post.content
    assert long_text in post.content


def test_build_note_low_confidence_warning(memory_tree):
    """转写置信度偏低：视频/录音卡面加警告行；截图（OCR）与正常置信不加。"""
    import os
    import time

    dispatcher = MediaDispatcher(memory_tree)
    attach = Path(memory_tree.attachments_dir) / "媒体"
    attach.mkdir(parents=True, exist_ok=True)
    path = attach / "clip.mp4"
    path.write_bytes(b"fake")
    old = time.time() - 60
    os.utime(path, (old, old))

    low = dispatcher._build_note(path, "视频", "转写内容", "stem-x", confidence=0.5)
    assert "转写置信度 50% 偏低" in low

    normal = dispatcher._build_note(path, "视频", "转写内容", "stem-x", confidence=0.9)
    assert "偏低" not in normal

    no_signal = dispatcher._build_note(path, "录音", "转写内容", "stem-x", confidence=0.0)
    assert "偏低" not in no_signal

    ocr = dispatcher._build_note(path, "截图", "OCR内容", "stem-x", confidence=0.5)
    assert "偏低" not in ocr


# ---- 图集合并（2026-09-15 裁决 A）与直发视频/录音总结（裁决 B）----


def _add_feishu_image(tree, stamp, hash6):
    """落一个飞书命名的假图片（到达时间取自文件名 UTC 时间戳）。"""
    attach = Path(tree.attachments_dir) / "媒体"
    attach.mkdir(parents=True, exist_ok=True)
    path = attach / f"feishu-{stamp}-{hash6}.png"
    path.write_bytes(b"\x89PNG fake-bytes")
    old = time.time() - 600  # mtime 只需过 30s 守卫；间隔靠文件名时间戳
    os.utime(path, (old, old))
    return path


def test_rapid_images_merge_into_one_batch_card(memory_tree):
    """连发多图（间隔 ≤60s）合并为一张图集卡；间隔超窗的单独成卡。"""
    for stamp, h in (("20260915-104900", "aaaa01"), ("20260915-104905", "aaaa02"),
                     ("20260915-104910", "aaaa03")):
        _add_feishu_image(memory_tree, stamp, h)
    lone = _add_feishu_image(memory_tree, "20260915-105200", "aaaa04")  # +3 分钟

    report = _dispatcher(memory_tree).run()

    assert report["found"] == 4
    assert len(report["created"]) == 2
    notes = sorted(Path(memory_tree.inbox_dir).glob("media-*.md"))
    assert len(notes) == 2
    batch = max(notes, key=lambda p: p.stat().st_size)
    post = frontmatter.loads(batch.read_text(encoding="utf-8"))
    assert post["tags"] == ["待确认", "截图"]
    assert "（3 张）" in post.content
    assert post.content.count("![[attachments/媒体/") == 3
    assert "—— 第 1 页 ——" in post.content
    assert "—— 第 3 页 ——" in post.content
    # 每张图逐文件登记，指向同一张图集卡（幂等粒度不变）
    state = json.loads(
        (memory_tree.state_dir / "processed_media.json").read_text()
    )
    assert state["attachments/媒体/feishu-20260915-104900-aaaa01.png"]["note"] == batch.name
    assert state["attachments/媒体/feishu-20260915-104910-aaaa03.png"]["note"] == batch.name
    lone_key = f"attachments/媒体/{lone.name}"
    assert state[lone_key]["note"] != batch.name


def test_batch_partial_ocr_failure_still_one_card(memory_tree):
    """图集里单页 OCR 失败：卡照建（图是原件全内嵌），失败页标 ocr=failed
    不再重试（重试只会再造一张重复卡）。"""

    class _FlakyImage:
        def process(self, path):
            if "aaaa02" in str(path):
                return ProcessResult(success=False, error="ocr boom")
            return ProcessResult(
                success=True, text="OCR 文本", markdown="", confidence=0.9
            )

    _add_feishu_image(memory_tree, "20260915-104900", "aaaa01")
    _add_feishu_image(memory_tree, "20260915-104905", "aaaa02")
    _add_feishu_image(memory_tree, "20260915-104910", "aaaa03")

    dispatcher = MediaDispatcher(memory_tree, image_factory=_FlakyImage)
    report = dispatcher.run()

    assert len(report["created"]) == 1
    note = _created_note(memory_tree)
    content = note.read_text(encoding="utf-8")
    assert content.count("![[attachments/媒体/") == 3  # 三张原件全在
    assert "—— 第 2 页 ——" not in content  # 失败页无 OCR 节
    state = json.loads(
        (memory_tree.state_dir / "processed_media.json").read_text()
    )
    failed = state["attachments/媒体/feishu-20260915-104905-aaaa02.png"]
    assert failed["status"] == "done"
    assert failed["ocr"] == "failed"


def test_batch_all_ocr_fail_no_card(memory_tree):
    """图集 OCR 全失败：不建卡，逐张计次数（3 次熔断同单图规）。"""
    _FakeImageProcessor.fail_with = "ocr down"
    _add_feishu_image(memory_tree, "20260915-104900", "aaaa01")
    _add_feishu_image(memory_tree, "20260915-104905", "aaaa02")

    report = _dispatcher(memory_tree).run()

    assert report["created"] == []
    assert report["failed"]
    state = json.loads(
        (memory_tree.state_dir / "processed_media.json").read_text()
    )
    assert state["attachments/媒体/feishu-20260915-104900-aaaa01.png"]["attempts"] == 1
    assert "status" not in state["attachments/媒体/feishu-20260915-104900-aaaa01.png"]


def _summary_dict():
    return {
        "summary": "核心观点。",
        "points": ["观点一。", "观点二。"],
        "insights": [],
        "entities": ["某概念"],
        "category": "B84-心理学",
        "topics": ["认知负荷"],
        "title": "t",
    }


def test_video_card_has_summary_and_tags(memory_tree, monkeypatch):
    """直发视频卡带观点总结/分观点/实体，tags 追加中图法+主题词
    （与链接视频同待遇）。"""
    monkeypatch.setattr(media_module, "compress_to_480p", _fake_compress_ok)
    seen = []

    def _fake_summarize(text):
        seen.append(text)
        return _summary_dict(), "ok"

    _add_attachment(memory_tree, "clip.mp4", subdir="媒体")
    dispatcher = MediaDispatcher(
        memory_tree, video_factory=_FakeVideoProcessor, summarize_fn=_fake_summarize
    )
    report = dispatcher.run()

    assert len(report["created"]) == 1
    note = _created_note(memory_tree)
    post = frontmatter.loads(note.read_text(encoding="utf-8"))
    assert post["tags"] == ["待确认", "视频", "B84-心理学", "认知负荷"]
    assert "## 观点总结" in post.content
    assert "1. 观点一。" in post.content
    assert "- 某概念" in post.content
    assert seen == ["视频转写文本。"]  # 总结收到的确实是转写全文


def test_audio_card_summarize_failure_annotated(memory_tree):
    """总结失败/被护栏跳过：卡面必须标注（不静默降级），无摘要节。"""

    def _fail_summarize(text):
        return None, "failed:RuntimeError"

    _add_attachment(memory_tree, "voice.ogg", age_seconds=60, subdir="媒体")
    dispatcher = MediaDispatcher(
        memory_tree, audio_factory=_FakeAudioProcessor, summarize_fn=_fail_summarize
    )
    dispatcher.run()

    note = _created_note(memory_tree)
    post = frontmatter.loads(note.read_text(encoding="utf-8"))
    assert post["tags"] == ["待确认", "录音"]
    assert "⚠️ 自动总结失败" in post.content
    assert "## 观点总结" not in post.content


def test_screenshot_card_not_summarized(memory_tree):
    """截图卡不走总结（OCR 全文即内容），总结函数不被调用。"""
    called = []

    def _spy_summarize(text):
        called.append(text)
        return _summary_dict(), "ok"

    _add_attachment(memory_tree, "IMG_009.png", subdir="媒体")
    dispatcher = MediaDispatcher(
        memory_tree, image_factory=_FakeImageProcessor, summarize_fn=_spy_summarize
    )
    dispatcher.run()

    assert not called
    note = _created_note(memory_tree)
    assert "## 观点总结" not in note.read_text(encoding="utf-8")
