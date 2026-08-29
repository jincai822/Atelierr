"""batch_cli 单元测试：扩展名路由 / 成功 / 失败不中断 / 空目录 / 缺目录。"""

from __future__ import annotations

import shutil

from click.testing import CliRunner

from scripts.cli.batch_cli import BatchCLI, _build_extension_map


def test_extension_map_routing():
    """扩展名路由表：图片/PDF/视频/音频各归其处理器。"""
    mapping = _build_extension_map()
    assert mapping[".jpg"] == "image"
    assert mapping[".webp"] == "image"
    assert mapping[".pdf"] == "pdf"
    assert mapping[".mp4"] == "video"
    assert mapping[".wav"] == "audio"
    assert ".txt" not in mapping


def _prepare_input(tmp_path, fixtures_dir):
    """输入目录：一张真实图片（rapidocr 引擎，快）。"""
    input_dir = tmp_path / "in"
    input_dir.mkdir()
    shutil.copy(fixtures_dir / "test_image.jpg", input_dir / "shot.jpg")
    return input_dir


def test_batch_success(tmp_path, fixtures_dir):
    """全部成功：输出 {stem}.md 且含 OCR 文本，exit 0。"""
    input_dir = _prepare_input(tmp_path, fixtures_dir)
    output_dir = tmp_path / "out"

    result = CliRunner().invoke(
        BatchCLI(config={"engine": "rapidocr"}).cli,
        ["--input-dir", str(input_dir), "--output-dir", str(output_dir)],
    )

    assert result.exit_code == 0, result.output
    assert "成功 1 / 失败 0 / 共 1" in result.output
    markdown = (output_dir / "shot.md").read_text(encoding="utf-8")
    assert "Atelierr" in markdown


def test_batch_failure_does_not_abort(tmp_path, fixtures_dir):
    """坏文件不中断：1 好图 + 1 坏 PDF → 成功 1 失败 1，exit 1。"""
    input_dir = _prepare_input(tmp_path, fixtures_dir)
    (input_dir / "broken.pdf").write_bytes(b"%PDF-1.4 garbage not a real pdf")
    output_dir = tmp_path / "out"

    result = CliRunner().invoke(
        BatchCLI(config={"engine": "rapidocr"}).cli,
        ["--input-dir", str(input_dir), "--output-dir", str(output_dir)],
    )

    assert result.exit_code == 1, result.output
    assert "成功 1 / 失败 1 / 共 2" in result.output
    assert "broken.pdf" in result.output
    assert (output_dir / "shot.md").exists()
    assert not (output_dir / "broken.md").exists()


def test_batch_empty_dir(tmp_path):
    """输入目录无受支持文件：提示并 exit 0。"""
    input_dir = tmp_path / "in"
    input_dir.mkdir()
    (input_dir / "readme.txt").write_text("不受支持", encoding="utf-8")

    result = CliRunner().invoke(
        BatchCLI().cli,
        ["--input-dir", str(input_dir), "--output-dir", str(tmp_path / "out")],
    )

    assert result.exit_code == 0, result.output
    assert "没有受支持的文件" in result.output


def test_batch_missing_input_dir(tmp_path):
    """输入目录不存在：main() 返回 1。"""
    cli = BatchCLI()
    code = cli.main(
        ["--input-dir", str(tmp_path / "nope"), "--output-dir", str(tmp_path / "o")]
    )
    assert code == 1


def test_batch_workers_option(tmp_path, fixtures_dir):
    """--workers 参数透传（1 个 worker 也能跑完）。"""
    input_dir = _prepare_input(tmp_path, fixtures_dir)
    output_dir = tmp_path / "out"

    result = CliRunner().invoke(
        BatchCLI(config={"engine": "rapidocr"}).cli,
        [
            "--input-dir",
            str(input_dir),
            "--output-dir",
            str(output_dir),
            "--workers",
            "1",
        ],
    )

    assert result.exit_code == 0, result.output
    assert (output_dir / "shot.md").exists()


def test_batch_main_success_returns_zero(tmp_path, fixtures_dir):
    """main() 成功路径返回 0。"""
    input_dir = _prepare_input(tmp_path, fixtures_dir)
    code = BatchCLI(config={"engine": "rapidocr"}).main(
        ["--input-dir", str(input_dir), "--output-dir", str(tmp_path / "out")]
    )
    assert code == 0
