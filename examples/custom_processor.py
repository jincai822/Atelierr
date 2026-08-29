#!/usr/bin/env python3
"""自定义处理器示例：TxtWordCountProcessor（.txt → Markdown + 词数统计）。

运行: python examples/custom_processor.py
用临时 .txt 文件演示 BaseProcessor 子类的 process() 返回 ProcessResult。
零外部服务依赖，不触碰 ~/atelierr-data。
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path
from typing import Union

# 把仓库根加入 sys.path，保证从任意位置运行都能导入 scripts 包
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.processors.base import BaseProcessor, ProcessResult  # noqa: E402


class TxtWordCountProcessor(BaseProcessor):
    """把 .txt 转成 Markdown，并在 metadata 里统计词数。"""

    name = "txt_word_count"
    supported_extensions = (".txt",)

    def process(self, input_path: Union[str, Path]) -> ProcessResult:
        path = Path(input_path)
        invalid = self._check_input(path)
        if invalid is not None:
            return invalid
        text = path.read_text(encoding="utf-8")
        word_count = len(text.split())
        markdown = f"# {path.stem}\n\n{text}\n\n> 词数: {word_count}\n"
        return ProcessResult(
            success=True,
            text=text,
            markdown=markdown,
            metadata={"word_count": word_count},
        )


def main() -> int:
    with tempfile.NamedTemporaryFile(
        "w", suffix=".txt", encoding="utf-8", delete=False
    ) as fh:
        fh.write("Atelierr custom processor 示例：统计这一行的单词数量。")
        tmp_path = Path(fh.name)
    try:
        processor = TxtWordCountProcessor()
        result = processor.process(tmp_path)
        assert result.success, result.error
        print(
            f"处理器: {processor.name}（支持 {', '.join(processor.supported_extensions)}）"
        )
        print(f"词数: {result.metadata['word_count']}")
        print("markdown 输出:")
        print(result.markdown)
    finally:
        tmp_path.unlink(missing_ok=True)
    print("custom_processor 完成")
    return 0


if __name__ == "__main__":
    sys.exit(main())
