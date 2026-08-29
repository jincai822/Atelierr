"""图片 OCR 性能测试（验收标准：单张 < 5s，真实 PaddleOCR）。

模型构造在计时之外（构造期加载），计时只含单张推理。
"""
from __future__ import annotations

import time
from pathlib import Path

from scripts.processors.image import ImageProcessor

FIXTURES_DIR = Path(__file__).resolve().parents[2] / "tests" / "fixtures"


def test_image_ocr_performance():
    """图片 OCR 单张 < 5s。"""
    image = FIXTURES_DIR / "test_image.jpg"
    assert image.exists(), "夹具缺失：请先运行 tools/generate_test_data.py"

    processor = ImageProcessor()  # 构造（模型加载）在计时外
    start = time.monotonic()
    result = processor.process(str(image))
    elapsed = time.monotonic() - start

    assert result.success, result.error
    assert elapsed < 5.0, f"单张 OCR 耗时 {elapsed:.2f}s >= 5s"
