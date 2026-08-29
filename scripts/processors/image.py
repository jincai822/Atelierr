"""图片 OCR 处理器（PaddleOCR）。

支持 JPG/JPEG/PNG/WEBP；生成含原始图片链接与识别文字的 Markdown。
PaddleOCR 实例在构造期懒加载（模型下载/初始化发生在构造时），
``process()`` 的计时只含单张推理。配置中的 ``timeout_s`` 是文档化的
验收性能目标（单张 < 5s，由性能测试验证），不强制中断推理。
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, List, Optional, Tuple, Union

from scripts.processors.base import BaseProcessor, ProcessResult

#: 支持的扩展名（大小写不敏感）
SUPPORTED_EXTENSIONS: Tuple[str, ...] = (".jpg", ".jpeg", ".png", ".webp")


def parse_ocr_output(output: Any) -> Tuple[List[str], List[float]]:
    """解析 PaddleOCR 结果，兼容 2.x 与 3.x 两种结构。

    2.x: ``ocr.ocr(img, cls=True)`` 返回
        ``[[box, (text, confidence)], ...]``（外层再包一层列表）；
    3.x: ``predict(img)`` 返回含 ``rec_texts`` / ``rec_scores``
        属性的结果对象列表（也可能直接是 dict）。

    Args:
        output: PaddleOCR 原始输出（可能为 None）。

    Returns:
        Tuple[List[str], List[float]]: 识别文本列表与对应置信度列表。
    """
    texts: List[str] = []
    scores: List[float] = []
    if output is None:
        return texts, scores
    items = output if isinstance(output, (list, tuple)) else [output]
    for item in items:
        if hasattr(item, "rec_texts"):
            texts.extend(str(t) for t in (item.rec_texts or []))
            scores.extend(
                float(s) for s in (getattr(item, "rec_scores", None) or [])
            )
        elif isinstance(item, dict):
            texts.extend(str(t) for t in item.get("rec_texts") or [])
            scores.extend(
                float(s) for s in item.get("rec_scores") or []
            )
        elif isinstance(item, (list, tuple)):
            for line in item:
                if not isinstance(line, (list, tuple)) or len(line) != 2:
                    continue
                second = line[1]
                if isinstance(second, (list, tuple)) and len(second) == 2:
                    texts.append(str(second[0]))
                    scores.append(float(second[1]))
    return texts, scores


class ImageProcessor(BaseProcessor):
    """基于 PaddleOCR 的图片文字识别处理器。

    Examples:
        >>> result = ImageProcessor().process("screenshot.jpg")
        >>> result.success
        True
    """

    name = "image"
    supported_extensions = SUPPORTED_EXTENSIONS

    def __init__(self, config: Optional[dict] = None) -> None:
        """初始化（构造期加载 PaddleOCR，模型下载发生在此处）。

        Args:
            config: processors.image 配置节；缺省按配置文件加载。
        """
        super().__init__(config)
        self.lang = str(self.config.get("lang", "ch"))
        self.use_gpu = bool(self.config.get("use_gpu", False))
        self.timeout_s = float(self.config.get("timeout_s", 5.0))
        self._ocr: Any = None
        self._load_engine()

    def _load_engine(self) -> None:
        """构造期懒加载 PaddleOCR 实例（按安装版本适配参数）。

        paddleocr 3.x：后端用 ``device`` 指定，无 ``use_gpu``/``show_log``；
        paddleocr 2.x：接受 ``use_gpu``/``show_log``。
        """
        from paddleocr import PaddleOCR, __version__

        if __version__.split(".")[0] == "3":
            device = "gpu:0" if self.use_gpu else "cpu"
            # paddlepaddle 3.x 的 MKLDNN 推理路径存在已知崩溃
            # （ConvertPirAttribute2RuntimeAttribute 未实现），关闭后走
            # 普通 CPU 推理（性能验收 < 5s 仍满足）
            self._ocr = PaddleOCR(
                lang=self.lang, device=device, enable_mkldnn=False
            )
        else:
            self._ocr = PaddleOCR(
                lang=self.lang, use_gpu=self.use_gpu, show_log=False
            )

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
            raw = self._run_ocr(str(path))
            texts, scores = parse_ocr_output(raw)
        except Exception as exc:  # noqa: BLE001 - 引擎失败转为失败结果
            return self._fail(f"OCR 失败: {exc}")

        text = "\n".join(texts)
        confidence = (
            sum(scores) / len(scores) if scores else 0.0
        )
        markdown = (
            f"# {path.stem}\n\n"
            f"![原始图片]({path})\n\n"
            f"## 识别的文字\n\n"
            f"{text}"
        )
        metadata = {
            "engine": "paddleocr",
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

    def _run_ocr(self, image_path: str) -> Any:
        """调用 PaddleOCR（按安装版本选择 predict 或 ocr 接口）。"""
        if hasattr(self._ocr, "predict"):
            return self._ocr.predict(image_path)
        return self._ocr.ocr(image_path, cls=True)
