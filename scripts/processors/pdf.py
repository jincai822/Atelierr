"""PDF 文字提取处理器（PyMuPDF）。

逐页流式提取文字（不整文件读入内存，支持大文件）；生成标题 + 目录 +
分页正文的 Markdown。``ocr_images=True`` 时提取内嵌图片并逐张 OCR
（复用 :class:`scripts.processors.image.ImageProcessor`，最多前 20 张，
计入 metadata）。
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

from scripts.processors.base import BaseProcessor, ExtractedImage, ProcessResult
from scripts.processors.image import ImageProcessor

#: 内嵌图片 OCR 数量上限（控制耗时；超出部分计入 metadata）
MAX_OCR_IMAGES = 20


class PDFProcessor(BaseProcessor):
    """基于 PyMuPDF 的 PDF 处理器。

    Examples:
        >>> result = PDFProcessor().process("document.pdf")
        >>> result.page_count
        10
    """

    name = "pdf"
    supported_extensions: Tuple[str, ...] = (".pdf",)

    def __init__(self, config: Optional[dict] = None) -> None:
        """初始化。

        Args:
            config: processors.pdf 配置节；缺省按配置文件加载。
        """
        super().__init__(config)
        self.ocr_images = bool(self.config.get("ocr_images", True))
        self.generate_toc = bool(self.config.get("generate_toc", True))
        self.ocr_engine = str(self.config.get("ocr_engine", "paddleocr"))
        self._image_processor: Optional[ImageProcessor] = None

    def _get_image_processor(self) -> ImageProcessor:
        """惰性创建图片处理器（首个内嵌图片出现时才触发模型加载）。"""
        if self._image_processor is None:
            self._image_processor = ImageProcessor(config={"engine": self.ocr_engine})
        return self._image_processor

    def process(self, input_path: Union[str, Path]) -> ProcessResult:
        """处理 PDF：逐页文字提取 + 可选内嵌图片 OCR。

        Args:
            input_path: PDF 文件路径。

        Returns:
            ProcessResult: 含 text/markdown/images/page_count 的结果；
            打开失败或处理异常时 success=False。
        """
        path = Path(input_path)
        invalid = self._check_input(path)
        if invalid is not None:
            return invalid
        try:
            import fitz

            document = fitz.open(str(path))
        except Exception as exc:  # noqa: BLE001 - 损坏/无法解析
            return self._fail(f"PDF 打开失败: {exc}")
        try:
            return self._process_document(document, path)
        except Exception as exc:  # noqa: BLE001 - 处理中途异常
            return self._fail(f"PDF 处理失败: {exc}")
        finally:
            document.close()

    def _process_document(self, document: Any, path: Path) -> ProcessResult:
        """逐页提取文字与内嵌图片（流式，不一次读入全文）。"""
        pages_text: List[str] = []
        images: List[ExtractedImage] = []
        image_index = 0
        images_total = 0
        page_count = document.page_count

        for page_no in range(page_count):
            page = document[page_no]
            pages_text.append(page.get_text("text") or "")
            if not self.ocr_images:
                continue
            for image_info in page.get_images(full=True):
                images_total += 1
                if len(images) >= MAX_OCR_IMAGES:
                    continue
                ocr_text, _conf = self._ocr_embedded_image(document, image_info)
                images.append(
                    ExtractedImage(
                        page=page_no + 1, index=image_index, ocr_text=ocr_text
                    )
                )
                image_index += 1

        text = "\n".join(pages_text)
        markdown = self._build_markdown(path, pages_text, document, images)
        images_processed = len(images)
        metadata: Dict[str, Any] = {
            "engine": "pymupdf",
            "page_count": page_count,
            "ocr_images": self.ocr_images,
            "images_total": images_total,
            "images_processed": images_processed,
            "images_skipped": max(0, images_total - images_processed),
        }
        return ProcessResult(
            success=True,
            text=text,
            markdown=markdown,
            page_count=page_count,
            images=images,
            metadata=metadata,
        )

    def _ocr_embedded_image(
        self, document: Any, image_info: Tuple[Any, ...]
    ) -> Tuple[str, float]:
        """抽取内嵌图片字节到临时文件并交给 ImageProcessor OCR。

        Args:
            document: PyMuPDF 文档对象。
            image_info: page.get_images(full=True) 的单个条目
                （xref 在首位）。

        Returns:
            Tuple[str, float]: (OCR 文本, 置信度)。
        """
        xref = int(image_info[0])
        try:
            extracted = document.extract_image(xref)
        except Exception:  # noqa: BLE001 - 单张图损坏不影响整份文档
            return "", 0.0
        if not extracted or not extracted.get("image"):
            return "", 0.0
        ext = str(extracted.get("ext", "png")).lower()
        if ext == "jpeg":
            ext = "jpg"
        if ext not in ("jpg", "png", "bmp"):
            ext = "png"
        fd, tmp_path = tempfile.mkstemp(suffix=f".{ext}")
        os.close(fd)
        try:
            with open(tmp_path, "wb") as handle:
                handle.write(extracted["image"])
            result = self._get_image_processor().process(tmp_path)
            return result.text, result.confidence
        finally:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass

    def _build_markdown(
        self,
        path: Path,
        pages_text: List[str],
        document: Any,
        images: List[ExtractedImage],  # pylint: disable=unused-argument
    ) -> str:
        """组装 Markdown：标题 + 目录 + 分页正文。"""
        lines: List[str] = [f"# {path.stem}", ""]
        if self.generate_toc:
            toc = document.get_toc()
            if toc:
                lines.append("## 目录")
                lines.append("")
                for level, title, page_no in toc:
                    indent = "  " * max(int(level) - 1, 0)
                    lines.append(f"{indent}- {title}（第 {page_no} 页）")
                lines.append("")
        for page_no, page_text in enumerate(pages_text, start=1):
            lines.append(f"## 第 {page_no} 页")
            lines.append("")
            if page_text.strip():
                lines.append(page_text.strip())
            else:
                lines.append("_（本页无文字层）_")
            lines.append("")
        return "\n".join(lines)
