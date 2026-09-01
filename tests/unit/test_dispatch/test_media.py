"""附件自动路由单元测试（无真实 OCR/Whisper，处理器以工厂注入假实现）。

附件扫描、状态幂等、失败熔断、mtime 防半文件守卫均为真实代码路径。
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

import frontmatter
import pytest

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


@pytest.fixture(autouse=True)
def _reset_fakes():
    """每个用例重置假处理器的调用记录与失败开关。"""
    for fake in (_FakeImageProcessor, _FakeAudioProcessor):
        fake.calls = []
        fake.fail_with = None
    yield


def _dispatcher(tree):
    return MediaDispatcher(
        tree, image_factory=_FakeImageProcessor, audio_factory=_FakeAudioProcessor
    )


def _add_attachment(tree, name="IMG_001.png", age_seconds=60):
    """在 attachments/ 落一个假附件并回拨 mtime（避开 30s 防半文件守卫）。"""
    attach = Path(tree.notes_dir) / "attachments"
    attach.mkdir(parents=True, exist_ok=True)
    path = attach / name
    path.write_bytes(b"\x89PNG fake-bytes")
    old = time.time() - age_seconds
    os.utime(path, (old, old))
    return path


def _created_note(tree):
    notes = list(Path(tree.notes_dir).glob("media-*.md"))
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
    assert not list(Path(memory_tree.notes_dir).glob("media-*.md"))
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

    filename = _md._note_filename(path)
    memory_tree.create_note(filename, "已存在的产出", source="media")

    report = _dispatcher(memory_tree).run()

    assert report["created"] == [filename]
    state = json.loads(
        (memory_tree.state_dir / "processed_media.json").read_text()
    )
    assert state["attachments/IMG_001.png"]["status"] == "done"
