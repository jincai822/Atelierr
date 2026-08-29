"""音频转文字处理器（Whisper 直接转写）。

与 :mod:`scripts.processors.video` 共享 Whisper 模型缓存与转写结果
解析/ Markdown 组装辅助函数，输出结构与视频处理器一致（标题 +
按 segment 的时间戳小节）。
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional, Union

import whisper  # noqa: F401 - 模块级导入；单元测试 monkeypatch 此处的 load_model

from scripts.processors.base import BaseProcessor, ProcessResult
from scripts.processors.video import (
    _build_transcript_markdown,
    _extract_transcript,
    _load_model,
    _segment_confidence,
)

#: 支持的扩展名（大小写不敏感）
SUPPORTED_EXTENSIONS: tuple = (".wav", ".mp3", ".flac", ".m4a", ".ogg", ".aac")


class AudioProcessor(BaseProcessor):
    """基于 Whisper 的音频转写处理器。

    Examples:
        >>> result = AudioProcessor().process("recording.wav")
        >>> result.success
        True
    """

    name = "audio"
    supported_extensions = SUPPORTED_EXTENSIONS

    def __init__(self, config: Optional[dict] = None) -> None:
        """初始化。

        Args:
            config: processors.audio 配置节；缺省按配置文件加载。
        """
        super().__init__(config)
        self.model_name = str(self.config.get("model", "base"))

    def process(self, input_path: Union[str, Path]) -> ProcessResult:
        """直接转写音频文件（Whisper 自带音频解码）。

        Args:
            input_path: 音频文件路径。

        Returns:
            ProcessResult: 含 text/markdown/confidence 的结果；
            转写失败时 success=False。
        """
        path = Path(input_path)
        invalid = self._check_input(path)
        if invalid is not None:
            return invalid
        try:
            model = _load_model(self.model_name)
            raw = model.transcribe(str(path))
            text, segments = _extract_transcript(raw)
        except Exception as exc:  # noqa: BLE001 - 转写失败转为失败结果
            return self._fail(f"音频转写失败: {exc}")
        markdown = _build_transcript_markdown(path.stem, segments)
        metadata = {
            "engine": "whisper",
            "model": self.model_name,
            "segments": len(segments),
        }
        return ProcessResult(
            success=True,
            text=text,
            markdown=markdown,
            confidence=_segment_confidence(segments),
            metadata=metadata,
        )
