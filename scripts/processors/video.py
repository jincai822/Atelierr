"""视频转文字处理器（ffmpeg 抽音频 + Whisper 转写）。

流程：ffmpeg 从视频抽取 16kHz 单声道 wav 到临时文件 → Whisper 转写 →
按 segment 生成带时间戳的 Markdown；临时文件处理完即清理。
Whisper 模型懒加载并缓存（模块级缓存）；单元测试通过
monkeypatch ``whisper.load_model`` 注入假模型，无需真实下载。

Whisper 共享辅助函数（``_load_model`` / ``_extract_transcript`` /
``_build_transcript_markdown`` 等）集中在本模块，供 audio.py 复用，
避免为两个处理器新增内部模块。
"""

from __future__ import annotations

import os
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

import whisper

from scripts.processors.base import BaseProcessor, ProcessResult

#: ffmpeg 可执行文件（可经配置 ffmpeg_path 覆盖）
FFMPEG_PATH = "/usr/bin/ffmpeg"

#: 支持的扩展名（大小写不敏感）
SUPPORTED_EXTENSIONS: Tuple[str, ...] = (
    ".mp4",
    ".mkv",
    ".avi",
    ".mov",
    ".webm",
    ".m4v",
    ".flv",
    ".wmv",
    ".mpg",
    ".mpeg",
)

#: 模型名 → 实例 的模块级缓存（真实模型只加载一次）
_model_cache: Dict[str, Any] = {}


def _load_model(model_name: str) -> Any:
    """按名称加载 Whisper 模型（懒加载并缓存实例）。

    Args:
        model_name: whisper 模型名（tiny/base/small/medium/large）。

    Returns:
        Any: 加载后的模型对象（带 ``transcribe`` 方法）。
    """
    if model_name not in _model_cache:
        _model_cache[model_name] = whisper.load_model(model_name)
    return _model_cache[model_name]


def _extract_transcript(
    result: Any,
) -> Tuple[str, List[Dict[str, float]]]:
    """从 Whisper 结果提取 text 与 segments（兼容 dict 与对象形态）。

    单测假模型返回纯 dict（{"text": ..., "segments": [...]}）；
    真实 whisper 返回含属性 text/segments 的结果对象。

    Args:
        result: whisper.transcribe() 的返回值。

    Returns:
        Tuple[str, List[Dict[str, float]]]: (全文, 段列表
        [{"start", "end", "text"}]）。
    """
    if result is None:
        return "", []
    if isinstance(result, dict):
        text = str(result.get("text", ""))
        raw_segments = result.get("segments") or []
    else:
        text = str(getattr(result, "text", "") or "")
        raw_segments = getattr(result, "segments", None) or []
    segments: List[Dict[str, Any]] = []
    for segment in raw_segments:
        if isinstance(segment, dict):
            normalized = {
                "start": float(segment.get("start", 0.0)),
                "end": float(segment.get("end", 0.0)),
                "text": str(segment.get("text", "")),
            }
            if "avg_logprob" in segment:
                normalized["avg_logprob"] = float(segment["avg_logprob"])
            segments.append(normalized)
        else:
            normalized = {
                "start": float(getattr(segment, "start", 0.0)),
                "end": float(getattr(segment, "end", 0.0)),
                "text": str(getattr(segment, "text", "")),
            }
            if getattr(segment, "avg_logprob", None) is not None:
                normalized["avg_logprob"] = float(segment.avg_logprob)
            segments.append(normalized)
    return text, segments


def _segment_confidence(segments: List[Dict[str, float]]) -> float:
    """由 segment 的 avg_logprob 估算置信度（无信号时 0.0）。

    Args:
        segments: 段列表（可能含 avg_logprob 键/属性）。

    Returns:
        float: [0.0, 1.0] 的平均置信度。
    """
    import math

    logprobs = [float(s["avg_logprob"]) for s in segments if "avg_logprob" in s]
    if not logprobs:
        return 0.0
    return min(max(math.exp(sum(logprobs) / len(logprobs)), 0.0), 1.0)


def _format_timestamp(seconds: float) -> str:
    """秒 → mm:ss 时间戳。

    Args:
        seconds: 秒数（非负）。

    Returns:
        str: 形如 "01:23" 的时间戳。
    """
    total = max(0, int(seconds))
    return f"{total // 60:02d}:{total % 60:02d}"


def _build_transcript_markdown(stem: str, segments: List[Dict[str, Any]]) -> str:
    """组装转写 Markdown：标题 + 按 segment 的时间戳小节。

    Args:
        stem: 文件名主干（作标题）。
        segments: 段列表（含 start/text）。

    Returns:
        str: Markdown 文本。
    """
    lines: List[str] = [f"# {stem}", "", "## 转写文字", ""]
    if segments:
        for segment in segments:
            timestamp = _format_timestamp(segment["start"])
            segment_text = segment["text"].strip()
            if segment_text:
                lines.append(f"- [{timestamp}] {segment_text}")
    else:
        lines.append("_（无转写内容）_")
    return "\n".join(lines)


class VideoProcessor(BaseProcessor):
    """视频转文字处理器（ffmpeg 抽音频 + Whisper 转写）。

    Examples:
        >>> result = VideoProcessor().process("lecture.mp4")
        >>> result.success
        True
    """

    name = "video"
    supported_extensions = SUPPORTED_EXTENSIONS

    def __init__(self, config: Optional[dict] = None) -> None:
        """初始化。

        Args:
            config: processors.video 配置节；缺省按配置文件加载。
        """
        super().__init__(config)
        self.model_name = str(self.config.get("model", "base"))
        self.ffmpeg = str(self.config.get("ffmpeg_path", FFMPEG_PATH))

    def process(self, input_path: Union[str, Path]) -> ProcessResult:
        """转写视频：抽音频 → Whisper → 带时间戳 Markdown。

        Args:
            input_path: 视频文件路径。

        Returns:
            ProcessResult: 含 text/markdown/confidence 的结果；
            ffmpeg 或转写失败时 success=False。
        """
        path = Path(input_path)
        invalid = self._check_input(path)
        if invalid is not None:
            return invalid
        wav_path, extract_error = self._extract_audio(str(path))
        if extract_error is not None:
            return self._fail(extract_error)
        try:
            model = _load_model(self.model_name)
            raw = model.transcribe(wav_path)
            text, segments = _extract_transcript(raw)
        except Exception as exc:  # noqa: BLE001 - 转写失败转为失败结果
            return self._fail(f"视频转写失败: {exc}")
        finally:
            if wav_path is not None:
                try:
                    os.unlink(wav_path)
                except OSError:
                    pass
        markdown = _build_transcript_markdown(path.stem, segments)
        metadata = {
            "engine": "whisper",
            "model": self.model_name,
            "segments": len(segments),
            "audio_extraction": "ffmpeg",
        }
        return ProcessResult(
            success=True,
            text=text,
            markdown=markdown,
            confidence=_segment_confidence(segments),
            metadata=metadata,
        )

    def _extract_audio(self, video_path: str) -> Tuple[Optional[str], Optional[str]]:
        """用 ffmpeg 从视频抽取 16kHz 单声道 wav 到临时文件。

        Args:
            video_path: 视频文件路径。

        Returns:
            Tuple[Optional[str], Optional[str]]: (wav 临时路径, 错误信息)；
            成功时 error 为 None，失败时路径为 None。
        """
        if not Path(self.ffmpeg).exists():
            return None, f"ffmpeg 不存在: {self.ffmpeg}"
        fd, wav_path = tempfile.mkstemp(suffix=".wav")
        os.close(fd)
        command = [
            self.ffmpeg,
            "-y",
            "-i",
            video_path,
            "-vn",
            "-ac",
            "1",
            "-ar",
            "16000",
            "-f",
            "wav",
            wav_path,
        ]
        try:
            proc = subprocess.run(
                command, capture_output=True, text=True, timeout=300, check=False
            )
        except Exception as exc:  # noqa: BLE001 - 调用异常
            self._unlink(wav_path)
            return None, f"ffmpeg 调用失败: {exc}"
        if proc.returncode != 0:
            self._unlink(wav_path)
            detail = (proc.stderr or "").strip()[-300:]
            return None, f"ffmpeg 抽取音频失败: {detail}"
        return wav_path, None

    @staticmethod
    def _unlink(path: str) -> None:
        """尽力删除临时文件。"""
        try:
            os.unlink(path)
        except OSError:
            pass
