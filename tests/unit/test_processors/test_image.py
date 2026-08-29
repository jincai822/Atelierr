"""图片处理器单元测试（验收标准 3.1：OCR / 格式 / 性能 / 错误处理）。"""

from __future__ import annotations

import time

from scripts.processors.image import ImageProcessor


def test_image_ocr(image_jpg):
    """测试图片 OCR：提取到文字、置信度 > 0、markdown 以标题开头。"""
    processor = ImageProcessor()
    result = processor.process(str(image_jpg))

    assert result.success, result.error
    assert result.text != ""
    assert result.confidence > 0.0
    assert result.markdown.startswith("# ")


def test_image_formats(image_jpg, image_png, image_webp):
    """测试多种格式：JPG/PNG/WEBP 均处理成功。"""
    processor = ImageProcessor()

    for path in (image_jpg, image_png, image_webp):
        result = processor.process(str(path))
        assert result.success, f"{path.name}: {result.error}"
        assert result.text != "", f"{path.name}: 未提取到文字"


def test_image_performance(image_jpg):
    """测试处理性能：构造后单张 < 5s。"""
    processor = ImageProcessor()

    start = time.monotonic()
    result = processor.process(str(image_jpg))
    elapsed = time.monotonic() - start

    assert result.success, result.error
    assert elapsed < 5.0, f"单张耗时 {elapsed:.2f}s >= 5s"


def test_image_unsupported_extension(tmp_path):
    """不支持的扩展名 → success=False（不抛异常）。"""
    unsupported = tmp_path / "note.txt"
    unsupported.write_text("hello", encoding="utf-8")

    result = ImageProcessor().process(str(unsupported))

    assert not result.success
    assert result.error


def test_image_missing_file(tmp_path):
    """文件不存在 → success=False（不抛异常）。"""
    result = ImageProcessor().process(str(tmp_path / "nope.jpg"))

    assert not result.success
    assert result.error


def test_default_engine_is_paddleocr():
    """未配置时默认引擎为 paddleocr。"""
    assert ImageProcessor().engine == "paddleocr"


def test_unknown_engine_raises():
    """未知引擎 → 构造期 ValueError（快速失败）。"""
    import pytest

    with pytest.raises(ValueError, match="未知 OCR 引擎"):
        ImageProcessor(config={"engine": "tesseract"})


def test_rapidocr_engine(image_jpg):
    """rapidocr 引擎：识别出文字、置信度 > 0、metadata 记录引擎名。"""
    processor = ImageProcessor(config={"engine": "rapidocr"})
    result = processor.process(str(image_jpg))

    assert result.success, result.error
    assert "Atelierr" in result.text
    assert result.confidence > 0.0
    assert result.metadata["engine"] == "rapidocr"
    assert result.markdown.startswith("# ")


def test_parse_ocr_output_shapes():
    """parse_ocr_output 兼容三种引擎输出结构与空结果。"""
    from scripts.processors.image import parse_ocr_output

    # None / 空页
    assert parse_ocr_output(None) == ([], [])
    assert parse_ocr_output([None]) == ([], [])

    # rapidocr: ([lines], elapse)
    rapid = ([[[[0, 0]], "你好", 0.9], [[[1, 1]], "世界", 0.8]], [0.1])
    assert parse_ocr_output(rapid) == (["你好", "世界"], [0.9, 0.8])
    # rapidocr 无检出: (None, elapse)
    assert parse_ocr_output((None, [0.1])) == ([], [])

    # paddleocr 2.x: [[line, ...]]（外层包页）
    paddle2 = [[[[[0, 0]], ("文字", 0.95)]]]
    assert parse_ocr_output(paddle2) == (["文字"], [0.95])

    # paddleocr 3.x dict 形态
    paddle3 = [{"rec_texts": ["甲", "乙"], "rec_scores": [0.7, 0.6]}]
    assert parse_ocr_output(paddle3) == (["甲", "乙"], [0.7, 0.6])
