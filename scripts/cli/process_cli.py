"""Atelierr 输入处理 CLI（image/pdf/video/audio 单文件处理）。

用法:
    python -m scripts.cli.process_cli image screenshot.jpg --output out.md
    python -m scripts.cli.process_cli pdf document.pdf --output out.md
    python -m scripts.cli.process_cli video lecture.mp4 --output out.md
    python -m scripts.cli.process_cli audio note.wav --model base

无 --output 时 Markdown 打印到 stdout；处理失败 exit code 1 并打印错误。
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Dict, List, Optional, Type

import click

from scripts.processors.audio import AudioProcessor
from scripts.processors.base import BaseProcessor
from scripts.processors.image import ImageProcessor
from scripts.processors.pdf import PDFProcessor
from scripts.processors.video import VideoProcessor

#: 子命令名 → 处理器类
PROCESSORS: Dict[str, Type[BaseProcessor]] = {
    "image": ImageProcessor,
    "pdf": PDFProcessor,
    "video": VideoProcessor,
    "audio": AudioProcessor,
}

#: --model 选项实际生效的处理器
MODEL_AWARE: tuple = ("video", "audio")


class ProcessCLI:
    """输入处理 CLI（click 组）。

    Attributes:
        cli: click group；子命令 image|pdf|video|audio。
    """

    def __init__(self, config: Optional[dict] = None) -> None:
        """初始化。

        Args:
            config: 传给各处理器的配置字典（缺省按配置文件加载）。
        """
        self.config = config
        self.cli = self._build_cli()

    def _build_cli(self) -> click.Group:
        """构造 click group 与各子命令。"""

        @click.group()
        def cli() -> None:
            """Atelierr 输入处理（image/pdf/video/audio）。"""

        for name, processor_cls in PROCESSORS.items():

            @cli.command(name=name)
            @click.argument(
                "input",
                type=click.Path(dir_okay=False, path_type=Path),
            )
            @click.option(
                "--output",
                "output",
                type=click.Path(dir_okay=False, path_type=Path),
                default=None,
                help="输出 Markdown 文件路径（缺省打印到 stdout）",
            )
            @click.option(
                "--model",
                "model",
                default=None,
                help="转写模型（仅 video/audio 生效，默认 base）",
            )
            def command(
                input: Path,
                output: Optional[Path],
                model: Optional[str],
                _name: str = name,
                _processor_cls: Type[BaseProcessor] = processor_cls,
            ) -> None:
                """处理单个输入文件。"""
                self._run(_name, _processor_cls, input, output, model)

        return cli

    def _run(
        self,
        name: str,
        processor_cls: Type[BaseProcessor],
        input: Path,
        output: Optional[Path],
        model: Optional[str],
    ) -> None:
        """执行一次处理并写输出/打印。失败时抛 ClickException（exit 1）。"""
        config = dict(self.config) if self.config else None
        if model and name in MODEL_AWARE:
            config = dict(config or {})
            config["model"] = model
        result = processor_cls(config).process(input)
        if not result.success:
            raise click.ClickException(
                result.error or f"{name} 处理失败: {input}"
            )
        if output is None:
            click.echo(result.markdown)
        else:
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(result.markdown, encoding="utf-8")
            click.echo(f"已写入: {output}")

    def main(self, args: Optional[List[str]] = None) -> int:
        """命令行入口；失败（ClickException）时返回 1。

        Args:
            args: 命令行参数列表；None 时用 sys.argv[1:]。

        Returns:
            int: 退出码（0 成功，1 处理失败）。
        """
        try:
            return self.cli.main(args=args, standalone_mode=False) or 0
        except click.ClickException as exc:
            click.echo(f"错误: {exc.format_message()}", err=True)
            return 1


if __name__ == "__main__":
    sys.exit(ProcessCLI().main())
