"""输入处理器公共基类与数据结构（MVP3 输入处理模块）。

处理器约定：
- 每个处理器继承 :class:`BaseProcessor`，实现 ``process()``；
- ``process()`` 对预期内错误（文件不存在 / 格式损坏 / 引擎失败）
  不抛异常，而是返回 ``ProcessResult(success=False, error=...)``；
- 配置来源：构造函数可显式传入 ``config``（对应 ``processors.<name>``
  节），缺省按 config/processors.yaml > processors.yaml.example >
  内置默认值的顺序合并解析，不硬依赖配置文件存在。
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

import yaml

#: 配置文件查找顺序（前者存在则优先；example 随仓库分发）
CONFIG_FILES: Tuple[str, ...] = (
    "config/processors.yaml",
    "config/processors.yaml.example",
)

#: 内置默认配置（与 config/processors.yaml.example 对齐，作为兜底）
DEFAULT_CONFIGS: Dict[str, Dict[str, Any]] = {
    "image": {
        "engine": "paddleocr",
        "lang": "ch",
        "use_gpu": False,
        "timeout_s": 5,
    },
    "pdf": {
        "engine": "pymupdf",
        "ocr_images": True,
        "generate_toc": True,
    },
    "video": {
        "engine": "whisper",
        "model": "base",
        "extract_keyframes": True,
    },
    "audio": {
        "engine": "whisper",
        "model": "base",
    },
    "link": {
        "model": "medium",
        "cookies_browser": "chrome",
    },
    "wechat": {
        "input_format": "txt",
    },
    "batch": {
        "workers": 4,
    },
}


def load_processor_config(name: str) -> Dict[str, Any]:
    """加载 ``processors.<name>`` 配置节（含内置默认值的合并结果）。

    查找顺序：config/processors.yaml > config/processors.yaml.example >
    内置默认。文件缺失或 YAML 损坏时静默退回下一级。

    Args:
        name: 处理器名（image/pdf/video/audio/wechat/batch）。

    Returns:
        Dict[str, Any]: 配置字典（至少含内置默认值）。
    """
    defaults = dict(DEFAULT_CONFIGS.get(name, {}))
    for config_file in CONFIG_FILES:
        path = Path(config_file)
        if not path.exists():
            continue
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8"))
        except yaml.YAMLError:
            continue
        if isinstance(data, dict) and isinstance(data.get("processors"), dict):
            section = data["processors"].get(name)
            if isinstance(section, dict):
                defaults.update(section)
    return defaults


@dataclass
class ExtractedImage:
    """PDF 内嵌图片及其 OCR 结果。

    Attributes:
        page: 图片所在页码（1 起）。
        index: 文档内图片序号（0 起，仅统计被 OCR 的图片）。
        ocr_text: 该图片 OCR 出的文字（可能为空串）。
    """

    page: int
    index: int
    ocr_text: str = ""


@dataclass
class ProcessResult:
    """处理器统一输出结构。

    Attributes:
        success: 是否处理成功；False 时 error 必有值。
        text: 提取/转写的纯文本。
        markdown: 供入库/展示的 Markdown 输出。
        confidence: [0.0, 1.0] 的识别置信度（无可用信号时为 0.0）。
        metadata: 引擎/耗时/图片统计等附加信息。
        images: PDF 内嵌图片的 OCR 结果列表（非 PDF 处理器为空）。
        page_count: 页数（非 PDF 处理器为 0）。
        error: 失败原因（success=True 时为 None）。
    """

    success: bool
    text: str = ""
    markdown: str = ""
    confidence: float = 0.0
    metadata: Dict[str, Any] = field(default_factory=dict)
    images: List[ExtractedImage] = field(default_factory=list)
    page_count: int = 0
    error: Optional[str] = None


class BaseProcessor(ABC):
    """输入处理器抽象基类。

    子类需声明 ``name`` 与 ``supported_extensions`` 并实现
    :meth:`process`。
    """

    #: 处理器名（对应 config 的 processors.<name> 节）
    name: str = ""
    #: 支持的扩展名（小写、含点），supports() 大小写不敏感
    supported_extensions: Tuple[str, ...] = ()

    def __init__(self, config: Optional[Dict[str, Any]] = None) -> None:
        """初始化：合并配置文件默认值与显式传入的配置。

        Args:
            config: 显式配置字典（对应 processors.<name> 节），
            缺省按 config/processors.yaml(.example) 加载。
        """
        self.config = load_processor_config(self.name)
        if config:
            self.config.update(config)

    @abstractmethod
    def process(self, input_path: Union[str, Path]) -> ProcessResult:
        """处理输入文件，返回结构化结果。

        Args:
            input_path: 输入文件路径。

        Returns:
            ProcessResult: 处理结果；预期内错误返回 success=False。
        """

    def supports(self, path: Union[str, Path]) -> bool:
        """按扩展名判断是否支持（大小写不敏感）。

        Args:
            path: 文件路径。

        Returns:
            bool: 扩展名是否在 supported_extensions 内。
        """
        return Path(path).suffix.lower() in self.supported_extensions

    def _fail(self, error: str) -> ProcessResult:
        """构造失败结果。

        Args:
            error: 失败原因。

        Returns:
            ProcessResult: success=False 且 error 非空。
        """
        return ProcessResult(success=False, error=error)

    def _check_input(self, input_path: Union[str, Path]) -> Optional[ProcessResult]:
        """校验输入文件存在性、类型与扩展名。

        Args:
            input_path: 输入文件路径。

        Returns:
            Optional[ProcessResult]: 校验失败时返回失败结果，否则 None。
        """
        path = Path(input_path)
        if not path.exists():
            return self._fail(f"文件不存在: {path}")
        if not path.is_file():
            return self._fail(f"不是普通文件: {path}")
        if not self.supports(path):
            supported = ", ".join(self.supported_extensions)
            return self._fail(
                f"不支持的扩展名: {path.suffix or '(无扩展名)'}"
                f"（支持: {supported}）"
            )
        return None
