"""process_cli 单元测试：--output/stdout/--model/失败路径/main 入口。"""

from __future__ import annotations

from click.testing import CliRunner

from scripts.cli.process_cli import ProcessCLI


def test_process_image_to_output_file(tmp_path, fixtures_dir):
    """image 子命令 --output：写入 markdown，exit 0。"""
    output = tmp_path / "out" / "shot.md"
    result = CliRunner().invoke(
        ProcessCLI(config={"engine": "rapidocr"}).cli,
        ["image", str(fixtures_dir / "test_image.jpg"), "--output", str(output)],
    )

    assert result.exit_code == 0, result.output
    assert "已写入" in result.output
    assert "Atelierr" in output.read_text(encoding="utf-8")


def test_process_image_to_stdout(fixtures_dir):
    """无 --output：markdown 打印到 stdout。"""
    result = CliRunner().invoke(
        ProcessCLI(config={"engine": "rapidocr"}).cli,
        ["image", str(fixtures_dir / "test_image.jpg")],
    )

    assert result.exit_code == 0, result.output
    assert "## 识别的文字" in result.output


def test_process_missing_file_returns_error(tmp_path):
    """输入文件不存在：ClickException → exit 1。"""
    result = CliRunner().invoke(ProcessCLI().cli, ["image", str(tmp_path / "nope.jpg")])

    assert result.exit_code == 1
    assert "不存在" in result.output or "失败" in result.output


def test_process_audio_with_model_option(tmp_path, monkeypatch, fixtures_dir):
    """audio --model 透传（mock whisper load_model，不下载真实模型）。"""
    calls = {}

    class _FakeModel:
        def transcribe(self, path):
            return {
                "text": "测试转写",
                "segments": [{"start": 0.0, "end": 1.0, "text": "测试转写"}],
            }

    def _fake_load_model(name):
        calls["model"] = name
        return _FakeModel()

    monkeypatch.setattr("scripts.processors.audio._load_model", _fake_load_model)

    result = CliRunner().invoke(
        ProcessCLI().cli,
        ["audio", str(fixtures_dir / "test_audio.wav"), "--model", "tiny"],
    )

    assert result.exit_code == 0, result.output
    assert calls["model"] == "tiny"
    assert "测试转写" in result.output


def test_main_entry_return_codes(tmp_path, fixtures_dir):
    """main()：成功 0 / 失败 1。"""
    ok = ProcessCLI(config={"engine": "rapidocr"}).main(
        [
            "image",
            str(fixtures_dir / "test_image.jpg"),
            "--output",
            str(tmp_path / "x.md"),
        ]
    )
    assert ok == 0

    bad = ProcessCLI().main(["pdf", str(tmp_path / "nope.pdf")])
    assert bad == 1
