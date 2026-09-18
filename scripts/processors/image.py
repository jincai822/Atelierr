"""图片 OCR 处理器（PaddleOCR / RapidOCR / 飞书云端 OCR 三引擎）。

支持 JPG/JPEG/PNG/WEBP；生成含原始图片链接与识别文字的 Markdown。
引擎实例在构造期懒加载（模型下载/初始化发生在构造时），
``process()`` 的计时只含单张推理。配置中的 ``timeout_s`` 是文档化的
验收性能目标（截图类 < 5s，由性能测试验证），不强制中断推理。

引擎通过 ``config["engine"]`` 选择：``mineru``（默认，MinerU 4.0 本机
服务）、``feishu``（云端）、``paddleocr`` / ``rapidocr``（历史引擎，已退役）
（飞书云端 OCR，不占本机算力；**图片会上传飞书云端**，敏感截图
勿用——见 scripts/processors/feishu_ocr.py）。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, List, Optional, Tuple, Union

from scripts.processors.base import BaseProcessor, ProcessResult

#: 支持的扩展名（大小写不敏感）
SUPPORTED_EXTENSIONS: Tuple[str, ...] = (".jpg", ".jpeg", ".png", ".webp")



def _is_ocr_line(item: Any) -> bool:
    """判断 item 是否是一行 OCR 结果（而非一页/多行列表）。"""
    if not isinstance(item, (list, tuple)):
        return False
    # rapidocr 行：[box, text, score]
    if len(item) == 3 and isinstance(item[1], str):
        return True
    # paddleocr 2.x 行：[box, (text, confidence)]
    return (
        len(item) == 2
        and isinstance(item[1], (list, tuple))
        and len(item[1]) == 2
        and isinstance(item[1][0], str)
    )


class ImageProcessor(BaseProcessor):
    """图片文字识别处理器（MinerU 默认 / 飞书云端可选）。

    Examples:
        >>> result = ImageProcessor().process("screenshot.jpg")
        >>> result.success
        True
    """

    name = "image"
    supported_extensions = SUPPORTED_EXTENSIONS

    def __init__(self, config: Optional[dict] = None) -> None:
        """初始化（构造期加载引擎，模型下载发生在此处）。

        Args:
            config: processors.image 配置节；缺省按配置文件加载。
                ``engine`` 支持 ``paddleocr``（默认）与 ``rapidocr``。

        Raises:
            ValueError: 未知的 engine 取值。
        """
        super().__init__(config)
        self.engine = str(self.config.get("engine", "mineru")).lower()
        if self.engine not in ("feishu", "mineru"):
            raise ValueError(f"未知 OCR 引擎: {self.engine}")
        self.lang = str(self.config.get("lang", "ch"))
        self.use_gpu = bool(self.config.get("use_gpu", False))
        self.timeout_s = float(self.config.get("timeout_s", 5.0))
        self._ocr: Any = None
        self._load_engine()

    def _load_engine(self) -> None:
        """构造期懒加载 OCR 引擎实例（按引擎/版本适配参数）。

        feishu：云端引擎无本地模型可加载（凭证在识别时才读取）；
        mineru：走本机 mineru server（模型由 server 管理），无本地加载。
        """
        if self.engine in ("feishu", "mineru"):
            return

    def process(self, input_path: Union[str, Path]) -> ProcessResult:
        """对单张图片执行 OCR。

        推理耗时计入性能验收（构造在外部完成）；引擎错误返回
        success=False。

        Args:
            input_path: 图片路径（.jpg/.jpeg/.png/.webp）。

        Returns:
            ProcessResult: 含 text/confidence/markdown 的识别结果。
        """
        path = Path(input_path)
        invalid = self._check_input(path)
        if invalid is not None:
            return invalid
        try:
            if self.engine == "feishu":
                # 云端 OCR 无逐行置信度，统一按 1.0 计（metadata 标引擎）
                from scripts.processors.feishu_ocr import recognize_texts

                texts = recognize_texts(path)
                scores = [1.0] * len(texts)
            elif self.engine == "mineru":
                texts, scores = self._run_mineru(path)
        except Exception as exc:  # noqa: BLE001 - 引擎失败转为失败结果
            return self._fail(f"OCR 失败: {exc}")

        text = "\n".join(texts)
        confidence = sum(scores) / len(scores) if scores else 0.0
        markdown = (
            f"# {path.stem}\n\n"
            f"![原始图片]({path})\n\n"
            f"## 识别的文字\n\n"
            f"{text}"
        )
        metadata = {
            "engine": self.engine,
            "lang": self.lang,
            "lines": len(texts),
            "timeout_s": self.timeout_s,
        }
        return ProcessResult(
            success=True,
            text=text,
            markdown=markdown,
            confidence=confidence,
            metadata=metadata,
        )

    def _run_mineru(self, path: Path) -> Tuple[List[str], List[float]]:
        """MinerU 4.0 引擎（2026-09-19 用户裁决：OCR 全面换 MinerU，paddle/
        rapidocr 退役）：走共享封装（scripts/processors/mineru_cli.py），
        取其 markdown 输出去标记成行；无逐行置信度，统一按 0.95 计。
        """
        from scripts.processors.mineru_cli import parse_document, strip_markers

        stdout = parse_document(
            path,
            tier=str(self.config.get("mineru_tier", "basic")),
            wait_s=int(self.config.get("mineru_wait_s", 300)),
            timeout_s=float(self.config.get("mineru_timeout_s", 320)),
        )
        texts = strip_markers(stdout)
        return texts, [0.95] * len(texts)

