"""PDF 处理性能测试（验收标准：10 页 < 30s，真实 PyMuPDF）。"""
from __future__ import annotations

import time
from pathlib import Path

from scripts.processors.pdf import PDFProcessor

FIXTURES_DIR = Path(__file__).resolve().parents[2] / "tests" / "fixtures"


def test_pdf_processing_performance():
    """10 页 PDF 处理 < 30s。"""
    pdf = FIXTURES_DIR / "test.pdf"
    assert pdf.exists(), "夹具缺失：请先运行 tools/generate_test_data.py"

    processor = PDFProcessor()
    start = time.monotonic()
    result = processor.process(str(pdf))
    elapsed = time.monotonic() - start

    assert result.success, result.error
    assert elapsed < 30.0, f"10 页 PDF 耗时 {elapsed:.2f}s >= 30s"
