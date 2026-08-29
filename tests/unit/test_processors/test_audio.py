"""音频处理器单元测试。

Whisper 转写用 monkeypatch 注入假模型（dict 形态结果），不下载真实
模型；假模型与 test_video.py 同构，输出结构断言一致。
"""
from __future__ import annotations

import pytest

import scripts.processors.audio as audio_module
import scripts.processors.video as video_module
from scripts.processors.audio import AudioProcessor


class _FakeWhisperModel:
    """假 whisper 模型：返回固定 dict 形态的转写结果。"""

    def transcribe(self, audio_path, **kwargs):
        return {
            "text": "fake audio transcription",
            "segments": [
                {"start": 0.0, "end": 1.0, "text": "fake audio transcription"},
            ],
        }


@pytest.fixture
def fake_whisper(monkeypatch):
    """替换 whisper.load_model 为假模型并清空共享模型缓存。"""
    video_module._model_cache.clear()
    monkeypatch.setattr(
        audio_module.whisper, "load_model", lambda name: _FakeWhisperModel()
    )
    return _FakeWhisperModel


def test_audio_success(fake_whisper, audio_wav):
    """假模型转写：success、text 来自假模型、markdown 含时间戳。"""
    result = AudioProcessor().process(str(audio_wav))

    assert result.success, result.error
    assert result.text == "fake audio transcription"
    assert "- [00:00]" in result.markdown
    assert result.metadata["segments"] == 1


def test_audio_supports():
    """按扩展名判断支持（大小写不敏感）。"""
    processor = AudioProcessor()

    assert processor.supports("note.wav")
    assert processor.supports("podcast.MP3")
    assert not processor.supports("notes.md")
    assert not processor.supports("video.mp4")


def test_audio_missing_file(fake_whisper, tmp_path):
    """文件不存在 → success=False（不抛异常）。"""
    result = AudioProcessor().process(str(tmp_path / "nope.wav"))

    assert not result.success
    assert result.error
