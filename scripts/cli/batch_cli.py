"""Atelierr 批量输入处理 CLI（多格式并行转换）。

扫描输入目录中所有受支持扩展名的文件（图片/PDF/视频/音频），按扩展名
路由到对应处理器，ThreadPoolExecutor 并行处理（默认 workers 取配置
batch.workers=4），每个成功文件写出 ``{stem}.md`` 到输出目录；单个
失败不中断整体，结束时打印成功/失败汇总，存在失败则 exit code 1。

用法:
    python -m scripts.cli.batch_cli --input-dir ~/Downloads --output-dir ~/Notes
    python -m scripts.cli.batch_cli --input-dir in/ --output-dir out/ --workers 8
"""

from __future__ import annotations

import sys
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Type

import click
from tqdm import tqdm

from scripts.processors.audio import AudioProcessor
from scripts.processors.base import BaseProcessor, load_processor_config
from scripts.processors.image import ImageProcessor
from scripts.processors.pdf import PDFProcessor
from scripts.processors.video import VideoProcessor

#: 处理器名 → 处理器类
PROCESSORS: Dict[str, Type[BaseProcessor]] = {
    "image": ImageProcessor,
    "pdf": PDFProcessor,
    "video": VideoProcessor,
    "audio": AudioProcessor,
}

#: 扩展名（小写）→ 处理器名 的路由表
_EXTENSION_MAP: Dict[str, str] = {}


def _build_extension_map() -> Dict[str, str]:
    """构建 扩展名 → 处理器名 路由表（首次调用后缓存）。"""
    if not _EXTENSION_MAP:
        for kind, processor_cls in PROCESSORS.items():
            for extension in processor_cls.supported_extensions:
                _EXTENSION_MAP[extension] = kind
    return _EXTENSION_MAP


class BatchCLI:
    """批量输入处理 CLI（click 命令）。

    Attributes:
        cli: click 命令（--input-dir/--output-dir/--workers）。
    """

    def __init__(self, config: Optional[dict] = None) -> None:
        """初始化。

        Args:
            config: 传给各处理器的配置字典（缺省按配置文件加载）。
        """
        self.config = config
        self.cli = self._build_cli()

    def _build_cli(self) -> click.Command:
        """构造 click 命令。"""

        @click.command()
        @click.option(
            "--input-dir",
            "input_dir",
            required=True,
            type=click.Path(file_okay=False, path_type=Path),
            help="输入目录（扫描受支持扩展名的文件）",
        )
        @click.option(
            "--output-dir",
            "output_dir",
            required=True,
            type=click.Path(file_okay=False, path_type=Path),
            help="输出目录（每个成功文件写 {stem}.md）",
        )
        @click.option(
            "--workers",
            "workers",
            type=int,
            default=None,
            help="并行数（缺省取配置 batch.workers，默认 4）",
        )
        def cli(input_dir: Path, output_dir: Path, workers: Optional[int]) -> None:
            """批量处理输入目录中的受支持文件。"""
            success, failed, errors = self.run_batch(input_dir, output_dir, workers)
            if errors:
                raise click.ClickException(
                    f"{failed} 个文件处理失败（成功 {success} / 共 "
                    f"{success + failed}）"
                )

        return cli

    def run_batch(
        self,
        input_dir: Path,
        output_dir: Path,
        workers: Optional[int] = None,
    ) -> Tuple[int, int, List[Tuple[str, str]]]:
        """批量处理输入目录。

        Args:
            input_dir: 输入目录。
            output_dir: 输出目录（不存在则创建）。
            workers: 并行数；缺省取配置 batch.workers（默认 4）。

        Returns:
            Tuple[int, int, List[Tuple[str, str]]]:
            (成功数, 失败数, [(文件路径, 错误), ...])。
        """
        input_dir = Path(input_dir)
        output_dir = Path(output_dir)
        if not input_dir.is_dir():
            raise click.ClickException(f"输入目录不存在: {input_dir}")
        output_dir.mkdir(parents=True, exist_ok=True)

        extension_map = _build_extension_map()
        tasks = [
            path
            for path in sorted(input_dir.iterdir())
            if path.is_file() and path.suffix.lower() in extension_map
        ]
        if not tasks:
            click.echo("输入目录中没有受支持的文件")
            return 0, 0, []

        worker_count = workers or int(load_processor_config("batch").get("workers", 4))
        worker_count = max(1, worker_count)

        # 每个线程持有自己的处理器实例（避免 PaddleOCR 跨线程共享）
        local = threading.local()

        def _processor_for(kind: str) -> BaseProcessor:
            processors = getattr(local, "processors", None)
            if processors is None:
                processors = {}
                local.processors = processors
            if kind not in processors:
                processors[kind] = PROCESSORS[kind](self.config)
            return processors[kind]

        def _handle(path: Path) -> Tuple[str, Optional[str]]:
            kind = extension_map[path.suffix.lower()]
            try:
                result = _processor_for(kind).process(path)
                if not result.success:
                    return str(path), result.error or f"{kind} 处理失败"
                target = output_dir / f"{path.stem}.md"
                target.write_text(result.markdown, encoding="utf-8")
                return str(path), None
            except Exception as exc:  # noqa: BLE001 - 单文件异常不中断
                return str(path), f"异常: {exc}"

        errors: List[Tuple[str, str]] = []
        success = 0
        with ThreadPoolExecutor(max_workers=worker_count) as pool:
            futures = {pool.submit(_handle, path): path for path in tasks}
            for future in tqdm(
                as_completed(futures),
                total=len(tasks),
                desc="处理中",
                unit="file",
            ):
                path, error = future.result()
                if error:
                    errors.append((path, error))
                else:
                    success += 1

        if errors:
            click.echo("")
            click.echo(f"失败 {len(errors)} 个文件:")
            for path, error in errors[:20]:
                click.echo(f"  ✗ {path}: {error}")
            if len(errors) > 20:
                click.echo(f"  ... 其余 {len(errors) - 20} 个省略")
        click.echo(f"完成: 成功 {success} / 失败 {len(errors)} / 共 {len(tasks)}")
        return success, len(errors), errors

    def main(self, args: Optional[List[str]] = None) -> int:
        """命令行入口；存在失败（ClickException）时返回 1。

        Args:
            args: 命令行参数列表；None 时用 sys.argv[1:]。

        Returns:
            int: 退出码（0 成功，1 有失败）。
        """
        try:
            return self.cli.main(args=args, standalone_mode=False) or 0
        except click.ClickException as exc:
            click.echo(f"错误: {exc.format_message()}", err=True)
            return 1


if __name__ == "__main__":
    sys.exit(BatchCLI().main())
