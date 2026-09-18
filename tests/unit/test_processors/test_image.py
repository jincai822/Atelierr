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


def test_default_engine_is_mineru():
    """未配置时默认引擎为 mineru（2026-09-19 用户裁决：OCR 换 MinerU）。"""
    assert ImageProcessor().engine == "mineru"


def test_unknown_engine_raises():
    """未知引擎 → 构造期 ValueError（快速失败）。"""
    import pytest

    with pytest.raises(ValueError, match="未知 OCR 引擎"):
        ImageProcessor(config={"engine": "tesseract"})


def test_mineru_engine(image_jpg):
    """mineru 引擎：识别出文字、置信度 > 0、metadata 记录引擎名。"""
    processor = ImageProcessor(config={"engine": "mineru"})
    result = processor.process(str(image_jpg))

    assert result.success, result.error
    assert "Atelierr" in result.text
    assert result.confidence > 0.0
    assert result.metadata["engine"] == "mineru"
    assert result.markdown.startswith("# ")



def test_feishu_engine_accepted():
    """engine=feishu 合法且不加载本地模型（构造秒回）。"""
    processor = ImageProcessor({"engine": "feishu"})
    assert processor.engine == "feishu"
    assert processor._ocr is None


def test_feishu_engine_process(image_jpg, monkeypatch):
    """feishu 引擎：识别走 feishu_ocr.recognize_texts（打桩），置信度 1.0。"""
    monkeypatch.setattr(
        "scripts.processors.feishu_ocr.recognize_texts",
        lambda path, timeout=30.0: ["第一行", "第二行"],
    )
    processor = ImageProcessor({"engine": "feishu"})
    result = processor.process(str(image_jpg))

    assert result.success, result.error
    assert result.text == "第一行\n第二行"
    assert result.confidence == 1.0
    assert result.metadata["engine"] == "feishu"


def test_feishu_engine_failure(image_jpg, monkeypatch):
    """云端识别失败 → success=False（不抛异常）。"""
    def _boom(path, timeout=30.0):
        raise RuntimeError("飞书 OCR 失败: 凭证缺失")

    monkeypatch.setattr("scripts.processors.feishu_ocr.recognize_texts", _boom)
    result = ImageProcessor({"engine": "feishu"}).process(str(image_jpg))

    assert not result.success
    assert "凭证缺失" in result.error


def test_feishu_ocr_flow(image_jpg, monkeypatch):
    """token 获取 + OCR 调用 + 文本提取（httpx 打桩）；token 有缓存。"""
    import scripts.processors.feishu_ocr as ocr_module

    calls = []

    class _Resp:
        def __init__(self, payload, status=200):
            self._payload = payload
            self.status_code = status

        def json(self):
            return self._payload

    def _post(url, **kwargs):
        calls.append(url)
        if "tenant_access_token" in url:
            return _Resp({"tenant_access_token": "t-1", "expire": 7200})
        return _Resp({"code": 0, "data": {"text_list": ["你好", "世界"]}})

    monkeypatch.setattr(ocr_module.httpx, "post", _post)
    monkeypatch.setenv("FEISHU_APP_ID", "cli_x")
    monkeypatch.setenv("FEISHU_APP_SECRET", "secret")
    ocr_module._TOKEN_CACHE.update({"token": "", "expires_at": 0.0})

    texts = ocr_module.recognize_texts(str(image_jpg))
    assert texts == ["你好", "世界"]
    # 第二次用缓存，不再请求 token
    texts = ocr_module.recognize_texts(str(image_jpg))
    assert texts == ["你好", "世界"]
    assert sum("tenant_access_token" in url for url in calls) == 1
