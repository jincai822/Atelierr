"""Atelierr 测试夹具生成器（MVP3 输入处理）。

生成 tests/fixtures/ 下的图片 / PDF / 音频 / 视频夹具，供处理器单元
测试、性能测试与验收脚本复用。幂等：已存在的夹具跳过不覆盖。

用法:
    python tools/generate_test_data.py [--fixtures-dir DIR]
"""

from __future__ import annotations

import argparse
import math
import shutil
import struct
import subprocess
import sys
import wave
from pathlib import Path
from typing import Callable, Dict, Tuple

# 直接运行（python tools/generate_test_data.py）时保证 scripts 包可导入
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

#: 默认夹具目录（仓库 tests/fixtures）
FIXTURES_DIR = Path(__file__).resolve().parent.parent / "tests" / "fixtures"

#: 图片 OCR 目标文本（干净合成文字，保证识别稳定）
OCR_TEXT = "Atelierr OCR test 123"
OCR_TEXT_2 = "Atelierr OCR test 456"

#: 大字号 TTF 字体候选（按存在性选取）
_FONT_CANDIDATES: Tuple[str, ...] = (
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
    "/usr/share/fonts/TTF/DejaVuSans.ttf",
)


def _load_font(size: int):
    """加载可用 TTF 字体；找不到时退回 PIL 默认字体。"""
    from PIL import ImageFont

    for font_path in _FONT_CANDIDATES:
        if Path(font_path).exists():
            try:
                return ImageFont.truetype(font_path, size)
            except OSError:
                continue
    try:
        return ImageFont.load_default(size=size)
    except TypeError:  # Pillow < 10.1 不支持 size 参数
        return ImageFont.load_default()


def _render_text_image(text: str, size: Tuple[int, int] = (800, 200)):
    """渲染白底黑字大图（居中文字）。

    Args:
        text: 要绘制的文字。
        size: 图片尺寸 (宽, 高)。

    Returns:
        PIL.Image: RGB 图像。
    """
    from PIL import Image, ImageDraw

    image = Image.new("RGB", size, "white")
    draw = ImageDraw.Draw(image)
    font = _load_font(48)
    bbox = draw.textbbox((0, 0), text, font=font)
    width = bbox[2] - bbox[0]
    height = bbox[3] - bbox[1]
    x = (size[0] - width) / 2 - bbox[0]
    y = (size[1] - height) / 2 - bbox[1]
    draw.text((x, y), text, fill="black", font=font)
    return image


def _make_text_image(path: Path, text: str) -> None:
    """生成单张测试图片（格式由扩展名决定）。"""
    _render_text_image(text).save(str(path))


def _make_text_pdf(path: Path, pages: int = 10) -> None:
    """生成 N 页文字版 PDF（逐页 insert_text + 目录书签）。"""
    import fitz

    document = fitz.open()
    for page_no in range(pages):
        page = document.new_page()
        y = 100
        page.insert_text(
            (72, y),
            f"Atelierr PDF test document - page {page_no + 1}",
            fontsize=20,
        )
        y += 40
        for line_no in range(1, 6):
            page.insert_text(
                (72, y),
                f"  This is test line {line_no} on page {page_no + 1}.",
                fontsize=12,
            )
            y += 24
    document.set_toc(
        [[1, f"Page {page_no + 1}", page_no + 1] for page_no in range(pages)]
    )
    document.save(str(path))
    document.close()


def _make_scanned_pdf(path: Path, pages: int = 2) -> None:
    """生成扫描版 PDF：整页图片无文字层（1-2 页）。"""
    import fitz

    document = fitz.open()
    for page_no in range(pages):
        page = document.new_page()
        image = _render_text_image(
            f"Scanned Atelierr document page {page_no + 1}",
            size=(1240, 1754),
        )
        from io import BytesIO

        buffer = BytesIO()
        image.save(buffer, format="PNG")
        buffer.seek(0)
        page.insert_image(page.rect, stream=buffer)
    document.save(str(path))
    document.close()


def _make_pdf_with_images(path: Path, pages: int = 3) -> None:
    """生成文字 + 每页一张内嵌图片的 PDF。"""
    from io import BytesIO

    import fitz

    document = fitz.open()
    for page_no in range(pages):
        page = document.new_page()
        page.insert_text(
            (72, 80),
            f"Atelierr PDF with images - page {page_no + 1}",
            fontsize=16,
        )
        image = _render_text_image(
            f"IMG {chr(65 + page_no)} Atelierr {page_no + 1}",
            size=(500, 120),
        )
        buffer = BytesIO()
        image.save(buffer, format="PNG")
        buffer.seek(0)
        page.insert_image(fitz.Rect(72, 130, 572, 250), stream=buffer)
    document.save(str(path))
    document.close()


def _make_audio_wav(
    path: Path,
    seconds: float = 1.0,
    frequency: float = 440.0,
    rate: int = 44100,
) -> None:
    """生成 1 秒 440Hz 正弦波 wav（stdlib wave + math，16bit 单声道）。"""
    with wave.open(str(path), "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(rate)
        frames = []
        for index in range(int(rate * seconds)):
            value = int(32767 * 0.5 * math.sin(2 * math.pi * frequency * index / rate))
            frames.append(struct.pack("<h", value))
        wav_file.writeframes(b"".join(frames))


def _make_video_mp4(path: Path) -> None:
    """用 ffmpeg 生成 2 秒 testsrc 视频 + sine 音轨。"""
    ffmpeg = shutil.which("ffmpeg") or "/usr/bin/ffmpeg"
    command = [
        ffmpeg,
        "-y",
        "-f",
        "lavfi",
        "-i",
        "testsrc=duration=2:size=640x480:rate=25",
        "-f",
        "lavfi",
        "-i",
        "sine=frequency=440:duration=2",
        "-c:v",
        "libx264",
        "-pix_fmt",
        "yuv420p",
        "-c:a",
        "aac",
        "-shortest",
        str(path),
    ]
    proc = subprocess.run(command, capture_output=True, text=True)
    if proc.returncode != 0:
        detail = (proc.stderr or "").strip()[-400:]
        raise RuntimeError(f"ffmpeg 生成视频失败: {detail}")


def generate_all(fixtures_dir: Path = FIXTURES_DIR) -> Dict[str, Path]:
    """生成全部测试夹具（已存在则跳过）。

    Args:
        fixtures_dir: 夹具输出目录（缺省 tests/fixtures）。

    Returns:
        Dict[str, Path]: 夹具名 → 路径（已存在或新生成的）。
    """
    fixtures_dir = Path(fixtures_dir)
    fixtures_dir.mkdir(parents=True, exist_ok=True)

    plan: Dict[str, Callable[[Path], None]] = {
        "test_image.jpg": lambda p: _make_text_image(p, OCR_TEXT),
        "test_image.png": lambda p: _make_text_image(p, OCR_TEXT),
        "test_image.webp": lambda p: _make_text_image(p, OCR_TEXT),
        "test_image2.jpg": lambda p: _make_text_image(p, OCR_TEXT_2),
        "test_image2.png": lambda p: _make_text_image(p, OCR_TEXT_2),
        "test_image2.webp": lambda p: _make_text_image(p, OCR_TEXT_2),
        "test.pdf": _make_text_pdf,
        "test_scanned.pdf": _make_scanned_pdf,
        "test_with_images.pdf": _make_pdf_with_images,
        "test_audio.wav": _make_audio_wav,
        "test_video.mp4": _make_video_mp4,
    }

    created: Dict[str, Path] = {}
    for name, generator in plan.items():
        target = fixtures_dir / name
        if not target.exists():
            generator(target)
        created[name] = target
    return created


def main(argv=None) -> int:
    """CLI 入口：生成夹具并打印结果。"""
    parser = argparse.ArgumentParser(description="生成 Atelierr 测试夹具")
    parser.add_argument(
        "--fixtures-dir",
        type=Path,
        default=FIXTURES_DIR,
        help="夹具输出目录（默认 tests/fixtures）",
    )
    args = parser.parse_args(argv)

    existing = (
        set(Path(args.fixtures_dir).glob("*"))
        if Path(args.fixtures_dir).is_dir()
        else set()
    )
    created = generate_all(args.fixtures_dir)
    for name, path in created.items():
        status = "已存在" if path in existing else "已生成"
        print(f"  {status}: {path}")
    print(f"共 {len(created)} 个夹具就绪")
    return 0


if __name__ == "__main__":
    sys.exit(main())
