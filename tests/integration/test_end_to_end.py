"""端到端：输入处理器输出直接进入记忆系统（MVP1 + MVP3 集成闭环）。

图片 OCR → MemoryTree 入库 → 按 OCR 文本搜索命中 → 访问后重算
confidence ≈ 1.0。验证"处理器输出直接进入记忆系统"的完整链路。
"""
from __future__ import annotations

from pathlib import Path

from scripts.processors.image import ImageProcessor

FIXTURES_DIR = Path(__file__).resolve().parents[2] / "tests" / "fixtures"


def test_ocr_into_memory_and_search(memory_tree):
    """图片 OCR → 入库 → 按 OCR 文本搜到 → 访问后 confidence ≈ 1.0。"""
    image = FIXTURES_DIR / "test_image.jpg"
    assert image.exists(), "夹具缺失：请先运行 tools/generate_test_data.py"

    result = ImageProcessor().process(str(image))
    assert result.success, result.error
    assert "Atelierr" in result.text

    # 处理器输出直接进入记忆系统
    note = memory_tree.create_note("ocr-import.md", result.markdown)

    # 搜索能按 OCR 文本命中
    hits = memory_tree.search("Atelierr")
    assert any(hit.path == note for hit in hits), "按 OCR 文本搜索未命中"

    # on_note_accessed 后重算 confidence ≈ 1.0
    memory_tree.on_note_accessed(note)
    info = memory_tree.note_info(note)
    assert info["confidence"] >= 0.99, (
        f"访问后 confidence 应为 ≈1.0，得到 {info['confidence']}"
    )
