#!/usr/bin/env python3
"""
Atelierr MVP 分阶段验收测试（架构 v1.2：平面存储 + sidecar 索引）。

用法:
    python tools/acceptance_test.py [--phase {1,2,3,all}]

- phase 1: 记忆模块（init/create/read/search/move/list/access/decay/stats）
          + CLI（MemoryCLI + CliRunner）+ 工具函数冒烟
- phase 2: 追加 Web 集成（scripts/web.integration.FlatnotesIntegration）
- phase 3: 追加输入处理器（scripts/processors 导入 + fixtures 冒烟）
- all:    全部（默认）

未选中的节打印 "⏳ 跳过（后续阶段）" 不算失败。
退出码：选中节全部通过 → 0，否则 1。
"""

from __future__ import annotations

import argparse
import sys
import tempfile
from datetime import datetime
from pathlib import Path

# 直接运行（python tools/acceptance_test.py）时保证 scripts 包可导入
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def print_section(title: str) -> None:
    """打印章节标题。"""
    print(f"\n{'=' * 60}")
    print(f"  {title}")
    print(f"{'=' * 60}\n")


def _write_memory_config(directory: Path) -> Path:
    """在临时目录写入指向同目录 memory/state 的配置。"""
    config = directory / "memory.yaml"
    config.write_text(
        f"memory:\n"
        f"  root: {directory}/memory\n"
        f"  state_dir: {directory}/state\n"
        f"  layers:\n"
        f"    short_term_min: 0.7\n"
        f"    mid_term_min: 0.4\n"
        f"  decay:\n"
        f"    rate: 0.95\n"
        f"    ref_coefficient: 0.2\n"
        f"    ref_cap: 10\n"
        f"    delete_threshold: 0.1\n",
        encoding="utf-8",
    )
    return config


def run_memory_section() -> bool:
    """记忆模块验收：核心 API 全流程断言。"""
    print("🧪 记忆模块...")
    try:
        from scripts.memory.core import MemoryTree
        from scripts.memory.decay import DecayManager

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            tree = MemoryTree(str(root / "memory"), state_dir=str(root / "state"))
            assert tree.notes_dir.exists() and tree.state_dir.exists(), "初始化失败"

            note = tree.create_note("acceptance.md", "测试内容", tags=["验收"])
            assert note.exists(), "创建笔记失败"
            assert note.parent == tree.notes_dir, "笔记不在平面根层"

            assert tree.read_note(note) == "测试内容", "读取笔记失败"

            results = tree.search("测试")
            assert results and results[0].path == note, "搜索失败"

            tree.move_note(note, "mid-term")
            assert tree.layer_of(note) == "mid-term", "move_note 失败"
            assert len(tree.list_notes("mid-term")) == 1, "list_notes 失败"

            tree.on_note_accessed(note)
            info = tree.note_info(note)
            assert info["last_accessed"] is not None, "on_note_accessed 失败"

            dry = DecayManager(tree).run(dry_run=True)
            assert dry["dry_run"] is True, "dry-run 失败"

            report = DecayManager(tree).run()
            assert report["total_notes"] >= 1, "decay 失败"
            assert report["report_path"], "衰减报告未生成"

            stats = tree.get_stats()
            assert stats["total"] >= 1, "stats 失败"
            assert set(stats.keys()) >= {"total", "layers", "pending_delete"}

            print("  ✅ 记忆模块验收通过")
            return True
    except Exception as exc:  # noqa: BLE001
        print(f"  ❌ 失败: {exc}")
        return False


def run_cli_section() -> bool:
    """CLI 验收：MemoryCLI 导入 + CliRunner 跑 create/search/stats。"""
    print("🧪 CLI...")
    try:
        from click.testing import CliRunner
        from scripts.cli.memory_cli import MemoryCLI

        with tempfile.TemporaryDirectory() as tmp:
            config = _write_memory_config(Path(tmp))
            cli = MemoryCLI(config_path=str(config)).cli
            runner = CliRunner()

            result = runner.invoke(cli, ["create", "cli.md", "--content", "CLI 测试内容"])
            assert result.exit_code == 0, result.output

            result = runner.invoke(cli, ["search", "CLI"])
            assert result.exit_code == 0, result.output
            assert "cli.md" in result.output, "CLI 搜索未命中"

            result = runner.invoke(cli, ["stats"])
            assert result.exit_code == 0, result.output
            assert "总数: 1" in result.output, "CLI stats 异常"

            print("  ✅ CLI 验收通过")
            return True
    except Exception as exc:  # noqa: BLE001
        print(f"  ❌ 失败: {exc}")
        return False


def run_utils_section() -> bool:
    """工具函数验收：四个 utils 模块导入 + 冒烟。"""
    print("🧪 工具函数...")
    try:
        from scripts.utils.config import deep_get, load_config
        from scripts.utils.date_utils import parse_date
        from scripts.utils.file_utils import ensure_dir
        from scripts.utils.text_utils import clean_text

        with tempfile.TemporaryDirectory() as tmp:
            cfg = Path(tmp) / "u.yaml"
            cfg.write_text("k: v\n", encoding="utf-8")
            assert load_config(cfg) == {"k": "v"}, "load_config 异常"
            assert deep_get({"a": {"b": 1}}, "a.b") == 1, "deep_get 异常"
            created = ensure_dir(Path(tmp) / "x" / "y")
            assert created.exists(), "ensure_dir 异常"
            assert clean_text("  a \n\n\n b ") == "a\n\nb", "clean_text 异常"
            assert parse_date("2026-01-01").date().year == 2026, "parse_date 异常"

        print("  ✅ 工具函数验收通过")
        return True
    except Exception as exc:  # noqa: BLE001
        print(f"  ❌ 失败: {exc}")
        return False


def run_web_section() -> bool:
    """Web 集成验收（phase >= 2）：导入 + 基本归一化冒烟。"""
    print("🧪 Web 集成...")
    try:
        from scripts.memory.core import MemoryTree
        from scripts.memory.watcher import MemoryWatcher
        from scripts.web.integration import FlatnotesIntegration

        with tempfile.TemporaryDirectory() as tmp:
            tree = MemoryTree(f"{tmp}/memory", state_dir=f"{tmp}/state")
            watcher = MemoryWatcher(tree, source="web")
            note = tree.notes_dir / "raw.md"
            note.write_text("裸内容", encoding="utf-8")
            result = watcher.process_pending()
            assert result["normalized"], "归一化失败"
            assert tree.layer_of(note) == "short-term", "登记失败"

        print("  ✅ Web 集成验收通过")
        return True
    except Exception as exc:  # noqa: BLE001
        print(f"  ❌ 失败: {exc}")
        return False


def run_processors_section() -> bool:
    """输入处理器验收（phase >= 3）：导入 + 用 tests/fixtures 冒烟。"""
    print("🧪 输入处理器...")
    try:
        from scripts.processors.base import BaseProcessor
        from scripts.processors.image import ImageProcessor
        from scripts.processors.pdf import PDFProcessor

        assert callable(BaseProcessor), "BaseProcessor 不可用"
        assert callable(ImageProcessor), "ImageProcessor 不可用"
        assert callable(PDFProcessor), "PDFProcessor 不可用"

        fixtures = Path(__file__).resolve().parent.parent / "tests" / "fixtures"
        if (fixtures / "sample.md").exists():
            text = (fixtures / "sample.md").read_text(encoding="utf-8")
            assert text.strip(), "fixtures/sample.md 为空"

        print("  ✅ 输入处理器验收通过")
        return True
    except Exception as exc:  # noqa: BLE001
        print(f"  ❌ 失败: {exc}")
        return False


def main() -> int:
    """解析 --phase 并运行对应验收节。"""
    parser = argparse.ArgumentParser(description="Atelierr MVP 分阶段验收测试")
    parser.add_argument(
        "--phase",
        choices=["1", "2", "3", "all"],
        default="all",
        help="要验收的阶段（默认 all）",
    )
    args = parser.parse_args()

    print_section("Atelierr MVP 验收测试")
    print(f"时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"阶段: {args.phase}\n")

    results = {
        "记忆模块": run_memory_section(),
        "CLI": run_cli_section(),
        "工具函数": run_utils_section(),
    }

    if args.phase in ("2", "3", "all"):
        results["Web 集成"] = run_web_section()
    else:
        print("⏳ 跳过 Web 集成（后续阶段）")

    if args.phase in ("3", "all"):
        results["输入处理器"] = run_processors_section()
    else:
        print("⏳ 跳过输入处理器（后续阶段）")

    print_section("验收报告")
    failed = []
    for name, ok in results.items():
        print(f"  {'✅' if ok else '❌'} {name}")
        if not ok:
            failed.append(name)
    print(f"\n通过: {len(results) - len(failed)}/{len(results)}")
    if failed:
        print(f"失败: {', '.join(failed)}")
        return 1
    print("🎉 全部验收通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
