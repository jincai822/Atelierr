"""视频处理器单元测试。

ffmpeg 抽音频走真实命令（对 test_video.mp4），Whisper 转写用
monkeypatch 注入假模型（返回 dict 形态结果），不下载真实模型。
"""
from __future__ import annotations

import pytest

import scripts.processors.video as video_module
from scripts.processors.video import VideoProcessor


class _FakeWhisperModel:
    """假 whisper 模型：返回固定 dict 形态的转写结果。"""

    def transcribe(self, audio_path, **kwargs):
        return {
            "text": "fake transcription text",
            "segments": [
                {"start": 0.0, "end": 1.5, "text": "fake transcription text"},
                {"start": 1.5, "end": 2.0, "text": "second segment"},
            ],
        }


@pytest.fixture
def fake_whisper(monkeypatch):
    """替换 whisper.load_model 为假模型并清空模型缓存。"""
    video_module._model_cache.clear()
    monkeypatch.setattr(
        video_module.whisper, "load_model", lambda name: _FakeWhisperModel()
    )
    return _FakeWhisperModel


def test_video_success(fake_whisper, video_mp4):
    """真实 ffmpeg 抽音频 + 假模型转写：success、text、时间戳。"""
    result = VideoProcessor().process(str(video_mp4))

    assert result.success, result.error
    assert result.text == "fake transcription text"
    assert "- [00:00]" in result.markdown
    assert result.metadata["segments"] == 2


def test_video_supports():
    """按扩展名判断支持（大小写不敏感）。"""
    processor = VideoProcessor()

    assert processor.supports("clip.mp4")
    assert processor.supports("CLIP.MKV")
    assert not processor.supports("notes.txt")
    assert not processor.supports("photo.jpg")


def test_video_missing_file(fake_whisper, tmp_path):
    """文件不存在 → success=False（不抛异常）。"""
    result = VideoProcessor().process(str(tmp_path / "nope.mp4"))

    assert not result.success
    assert result.error


def test_video_ffmpeg_failure(fake_whisper, tmp_path):
    """ffmpeg 无法解析的输入 → success=False（不抛异常）。"""
    invalid = tmp_path / "not_a_video.mp4"
    invalid.write_text("this is not a video", encoding="utf-8")

    result = VideoProcessor().process(str(invalid))

    assert not result.success
    assert "ffmpeg" in (result.error or "")
