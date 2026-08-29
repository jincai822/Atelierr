"""输入处理器单元测试共享 fixture。"""
from __future__ import annotations

from pathlib import Path

import pytest

from tools.generate_test_data import generate_all

#: 测试夹具目录（tests/fixtures）
FIXTURES_DIR = (
    Path(__file__).resolve().parents[3] / "tests" / "fixtures"
)


@pytest.fixture(scope="session", autouse=True)
def ensure_fixtures() -> None:
    """session 级：保证处理器测试夹具存在（幂等生成）。"""
    generate_all(FIXTURES_DIR)


@pytest.fixture(scope="session")
def fixtures_dir() -> Path:
    """夹具目录路径。"""
    return FIXTURES_DIR


@pytest.fixture(scope="session")
def image_jpg(fixtures_dir: Path) -> Path:
    """test_image.jpg 路径。"""
    return fixtures_dir / "test_image.jpg"


@pytest.fixture(scope="session")
def image_png(fixtures_dir: Path) -> Path:
    """test_image.png 路径。"""
    return fixtures_dir / "test_image.png"


@pytest.fixture(scope="session")
def image_webp(fixtures_dir: Path) -> Path:
    """test_image.webp 路径。"""
    return fixtures_dir / "test_image.webp"


@pytest.fixture(scope="session")
def pdf_text(fixtures_dir: Path) -> Path:
    """test.pdf（10 页文字版）路径。"""
    return fixtures_dir / "test.pdf"


@pytest.fixture(scope="session")
def pdf_scanned(fixtures_dir: Path) -> Path:
    """test_scanned.pdf（扫描版）路径。"""
    return fixtures_dir / "test_scanned.pdf"


@pytest.fixture(scope="session")
def pdf_with_images(fixtures_dir: Path) -> Path:
    """test_with_images.pdf（文字 + 内嵌图片）路径。"""
    return fixtures_dir / "test_with_images.pdf"


@pytest.fixture(scope="session")
def audio_wav(fixtures_dir: Path) -> Path:
    """test_audio.wav 路径。"""
    return fixtures_dir / "test_audio.wav"


@pytest.fixture(scope="session")
def video_mp4(fixtures_dir: Path) -> Path:
    """test_video.mp4 路径。"""
    return fixtures_dir / "test_video.mp4"
