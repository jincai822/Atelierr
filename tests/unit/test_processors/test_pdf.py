"""PDF 处理器单元测试（验收标准 3.2：文字 / 图片 / 性能 / 扫描件 / 目录）。"""

from __future__ import annotations

import time

from scripts.processors.pdf import PDFProcessor


def test_pdf_text_extraction(pdf_text):
    """测试 PDF 文字提取：text 非空、page_count > 0。"""
    processor = PDFProcessor()
    result = processor.process(str(pdf_text))

    assert result.success, result.error
    assert len(result.text) > 0
    assert result.page_count == 10
    assert result.page_count > 0


def test_pdf_with_images(pdf_with_images):
    """测试带图片的 PDF：提取内嵌图片且所有 ocr_text 非空。"""
    processor = PDFProcessor()
    result = processor.process(str(pdf_with_images))

    assert result.success, result.error
    assert len(result.images) > 0
    assert all(img.ocr_text for img in result.images)


def test_pdf_performance(pdf_text):
    """测试处理性能：10 页 PDF < 30s。"""
    processor = PDFProcessor()

    start = time.monotonic()
    result = processor.process(str(pdf_text))
    elapsed = time.monotonic() - start

    assert result.success, result.error
    assert elapsed < 30.0, f"10 页耗时 {elapsed:.2f}s >= 30s"


def test_pdf_scanned(pdf_scanned):
    """扫描版 PDF：无文字层但 success，图片 OCR 路径生效。

    用 rapidocr 引擎（整页扫描 CPU 实测 ~0.8s/页，远快于 paddle 的 12-14s），
    同时覆盖 PDFProcessor 的 ocr_engine 透传；默认 paddle 引擎由
    test_pdf_with_images 覆盖。
    """
    processor = PDFProcessor(config={"ocr_engine": "rapidocr"})
    result = processor.process(str(pdf_scanned))

    assert result.success, result.error
    assert len(result.images) > 0
    assert any("Scanned" in img.ocr_text for img in result.images)


def test_pdf_toc_generated(pdf_text):
    """目录生成：markdown 含 '## 目录' 并列出条目。"""
    result = PDFProcessor().process(str(pdf_text))

    assert result.success, result.error
    assert "## 目录" in result.markdown
    assert "Page 1" in result.markdown


def test_pdf_missing_file(tmp_path):
    """文件不存在 → success=False（不抛异常）。"""
    result = PDFProcessor().process(str(tmp_path / "nope.pdf"))

    assert not result.success
    assert result.error
