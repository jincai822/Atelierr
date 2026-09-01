#!/usr/bin/env python3
"""
Atelierr MVP 分阶段验收测试（架构 v1.2：平面存储 + sidecar 索引）。

用法:
    python tools/acceptance_test.py [--phase {1,2,3,all}]

- phase 1: 记忆模块（init/create/read/search/move/list/access/decay/stats）
          + 复习队列（resurface 窗口/冷却/摘要集成）
          + CLI（MemoryCLI + CliRunner）+ 工具函数冒烟
- phase 2: 追加 Web 集成（scripts/web.integration.FlatnotesIntegration）
- phase 3: 追加输入处理器（scripts/processors 导入 + fixtures 冒烟）
- all:    全部（默认）
- 示例:   子进程逐个运行 examples/*.py 断言 exit 0（所有 phase 都运行，
          示例只依赖 MVP1，零外部服务）

未选中的节打印 "⏳ 跳过（后续阶段）" 不算失败。
退出码：选中节全部通过 → 0，否则 1。
"""

from __future__ import annotations

import argparse
import subprocess
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


def run_resurface_section() -> bool:
    """复习队列验收：窗口筛选 / 推送冷却 / 摘要集成 / 绝不改笔记。"""
    print("🧪 复习队列...")
    try:
        import os
        import time

        from scripts.dispatch.digest import DigestDispatcher
        from scripts.memory.core import MemoryTree
        from scripts.memory.resurface import ResurfaceManager

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            tree = MemoryTree(str(root / "memory"), state_dir=str(root / "state"))
            tree.create_note("fresh.md", "新笔记")
            old = tree.create_note("old.md", "旧笔记")
            old_ns = int((time.time() - 20 * 86400) * 1e9)
            os.utime(old, ns=(old_ns, old_ns))

            manager = ResurfaceManager(tree)
            picked = manager.candidates()
            assert [c["filename"] for c in picked] == ["old.md"], "窗口筛选失败"

            before = old.read_bytes()
            manager.mark_pushed([picked[0]["id"]])
            assert old.read_bytes() == before, "笔记被改写"
            assert (tree.state_dir / "resurface.json").exists(), "状态未落 state_dir"
            assert not manager.candidates(), "冷却未生效"

            # 实验 0：推送响应率观测（推送后被编辑 → 响应）
            from scripts.dispatch.response_probe import ResponseProbe

            probe = ResponseProbe(tree)
            probe.register([{"id": picked[0]["id"], "filename": "old.md"}])
            new_ns = int(time.time() * 1e9)
            os.utime(old, ns=(new_ns, new_ns))
            assert probe.check_pending()["responded"] == 1, "响应观测失败"
            assert probe.summary()["rate"] == 1.0, "响应率统计失败"

            report = DigestDispatcher(tree).run(today="2026-09-01")
            assert "今日复习" in report["markdown"], "摘要缺复习节"

            print("  ✅ 复习队列验收通过")
            return True
    except Exception as exc:  # noqa: BLE001
        print(f"  ❌ 失败: {exc}")
        return False


def run_cli_section(phase: str) -> bool:
    """CLI 验收：MemoryCLI 导入 + CliRunner 跑 create/search/stats。

    phase >= 3 时追加 ProcessCLI/BatchCLI 导入冒烟，并用 CliRunner
    对 test_image.jpg 跑一次 image 子命令（--output 到临时文件）。
    """
    print("🧪 CLI...")
    try:
        from click.testing import CliRunner

        from scripts.cli.memory_cli import MemoryCLI

        with tempfile.TemporaryDirectory() as tmp:
            config = _write_memory_config(Path(tmp))
            cli = MemoryCLI(config_path=str(config)).cli
            runner = CliRunner()

            result = runner.invoke(
                cli, ["create", "cli.md", "--content", "CLI 测试内容"]
            )
            assert result.exit_code == 0, result.output

            result = runner.invoke(cli, ["search", "CLI"])
            assert result.exit_code == 0, result.output
            assert "cli.md" in result.output, "CLI 搜索未命中"

            result = runner.invoke(cli, ["stats"])
            assert result.exit_code == 0, result.output
            assert "总数: 1" in result.output, "CLI stats 异常"

        if phase in ("3", "all"):
            from scripts.cli.batch_cli import BatchCLI
            from scripts.cli.process_cli import ProcessCLI
            from tools.generate_test_data import generate_all

            assert callable(ProcessCLI), "ProcessCLI 不可用"
            assert callable(BatchCLI), "BatchCLI 不可用"

            fixtures = Path(__file__).resolve().parent.parent / "tests" / "fixtures"
            generate_all(fixtures)
            with tempfile.TemporaryDirectory() as tmp:
                out_file = Path(tmp) / "cli-image.md"
                result = CliRunner().invoke(
                    ProcessCLI().cli,
                    [
                        "image",
                        str(fixtures / "test_image.jpg"),
                        "--output",
                        str(out_file),
                    ],
                )
                assert result.exit_code == 0, f"process_cli image 失败: {result.output}"
                assert (
                    out_file.exists() and out_file.stat().st_size > 0
                ), "process_cli image 未写出输出文件"

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
    """Web 集成验收（phase >= 2）：导入 + 归一化冒烟（走 FlatnotesIntegration 门面）。"""
    print("🧪 Web 集成...")
    try:
        from scripts.memory.core import MemoryTree
        from scripts.web.integration import FlatnotesIntegration

        with tempfile.TemporaryDirectory() as tmp:
            tree = MemoryTree(f"{tmp}/memory", state_dir=f"{tmp}/state")
            integration = FlatnotesIntegration(tree)
            note = tree.notes_dir / "raw.md"
            note.write_text("裸内容", encoding="utf-8")
            result = integration.process_pending()
            assert result["normalized"], "归一化失败"
            assert tree.layer_of(note) == "short-term", "登记失败"
            assert integration.tree is tree, "门面未装配 tree"
            assert integration.watcher.source == "web", "门面未装配 source=web"

        print("  ✅ Web 集成验收通过")
        return True
    except Exception as exc:  # noqa: BLE001
        print(f"  ❌ 失败: {exc}")
        return False


def run_processors_section() -> bool:
    """输入处理器验收（phase >= 3）：夹具生成 + 图片 OCR / PDF 处理断言。"""
    print("🧪 输入处理器...")
    try:
        from scripts.processors.base import BaseProcessor
        from scripts.processors.image import ImageProcessor
        from scripts.processors.pdf import PDFProcessor
        from tools.generate_test_data import generate_all

        assert callable(BaseProcessor), "BaseProcessor 不可用"
        assert callable(ImageProcessor), "ImageProcessor 不可用"
        assert callable(PDFProcessor), "PDFProcessor 不可用"

        fixtures = Path(__file__).resolve().parent.parent / "tests" / "fixtures"
        generate_all(fixtures)

        image_result = ImageProcessor().process(str(fixtures / "test_image.jpg"))
        assert image_result.success, f"图片 OCR 失败: {image_result.error}"
        assert image_result.text.strip(), "图片 OCR 未提取到文字"

        pdf_result = PDFProcessor().process(str(fixtures / "test.pdf"))
        assert pdf_result.success, f"PDF 处理失败: {pdf_result.error}"
        assert pdf_result.page_count > 0, "PDF 未检测到页面"

        print("  ✅ 输入处理器验收通过")
        return True
    except Exception as exc:  # noqa: BLE001
        print(f"  ❌ 失败: {exc}")
        return False


def run_examples_section() -> bool:
    """示例验收（所有 phase 运行）：子进程逐个运行 examples/*.py。

    示例只依赖 MVP1 模块，零外部服务；逐个 subprocess 运行并断言 exit 0。
    """
    print("🧪 示例...")
    examples_dir = Path(__file__).resolve().parent.parent / "examples"
    scripts = ["basic_usage.py", "batch_processing.py", "custom_processor.py"]
    ok = True
    for name in scripts:
        result = subprocess.run(
            [sys.executable, str(examples_dir / name)],
            capture_output=True,
            text=True,
            timeout=120,
        )
        if result.returncode == 0:
            print(f"  ✅ {name} 运行成功")
        else:
            print(f"  ❌ {name} 运行失败（exit {result.returncode}）")
            print(f"     stdout: {result.stdout[-500:]}")
            print(f"     stderr: {result.stderr[-500:]}")
            ok = False
    return ok


def run_cognition_section() -> bool:
    """认知模块验收（Phase 5）：COGNITION-SPEC v1.0 全流程断言。

    覆盖：create / question certainty 拒绝 / 提名-批准升级 / 来源 memory
    不变红线 / 挑战-接受 / 继任 / 归档 / validate / reindex / CLI 冒烟。
    """
    print("🧪 认知模块...")
    try:
        import frontmatter
        from click.testing import CliRunner

        from scripts.cli.cognition_cli import CognitionCLI
        from scripts.cognition import (
            ApprovalRecord,
            CognitionError,
            CognitionManager,
        )
        from scripts.memory.core import MemoryTree

        approval = ApprovalRecord(action="acceptance", reason="验收批准")
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            tree = MemoryTree(str(root / "memory"), state_dir=str(root / "state"))
            manager = CognitionManager(root, state_dir=root / "state")

            # 手工创建 belief；question 拒绝 certainty
            belief = manager.create_entry(
                entry_type="belief",
                title="验收信念",
                statement="认知模块验收陈述。",
                status="active",
                certainty=0.8,
                approval=approval,
            )
            assert belief.path.parent == manager.cognition_dir, "非平面根层"
            try:
                manager.create_entry(
                    entry_type="question",
                    title="q",
                    statement="问题？",
                    status="open",
                    certainty=0.5,
                    approval=approval,
                )
                raise AssertionError("question 接受 certainty 了")
            except CognitionError:
                pass

            # 提名 → 批准：来源 memory 红线（bytes/mtime 不变）
            note = tree.create_note("origin.md", "升级来源内容")
            memory_id = frontmatter.loads(note.read_text(encoding="utf-8")).metadata[
                "id"
            ]
            before = (note.read_bytes(), note.stat().st_mtime_ns)
            proposal = manager.nominate_memory(
                memory_id,
                entry_type="hypothesis",
                title="验收假设",
                statement="假设陈述。",
                rationale="含证伪条件：跑验收",
                proposed_status="testing",
                proposed_certainty=0.5,
            )
            promoted = manager.approve_promotion(
                proposal.id,
                status="testing",
                certainty=0.55,
                approval=approval,
            )
            assert (
                note.read_bytes(),
                note.stat().st_mtime_ns,
            ) == before, "来源 memory 被改动"
            assert promoted.origin["memory_id"] == memory_id, "origin 未记录来源"

            # 挑战 → accept：revision/证据/确信度
            from scripts.cognition import EvidenceRef

            challenge = manager.propose_challenge(
                belief.id,
                evidence=[
                    EvidenceRef(kind="manual", relation="challenges", note="验收反例")
                ],
                rationale="验收挑战",
                proposed_certainty=0.6,
            )
            updated = manager.resolve_challenge(
                challenge.id,
                resolution="accept",
                certainty=0.6,
                status=None,
                rationale="接受验收反例",
                approval=approval,
            )
            assert updated.revision == 2 and updated.certainty == 0.6

            # 继任 + 归档
            successor = manager.supersede_entry(
                promoted.id,
                replacement_statement="收窄后的假设陈述。",
                replacement_certainty=0.5,
                rationale="适用范围收窄",
                approval=approval,
            )
            assert successor.supersedes == promoted.id
            assert manager.get_entry(promoted.id).status == "superseded"
            archived = manager.archive_entry(
                successor.id,
                reason="验收归档",
                approval=approval,
            )
            assert archived.status == "archived" and archived.path.exists()

            # validate / reindex
            report = manager.validate()
            assert report.ok, report.errors
            rebuilt = manager.rebuild_index()
            assert rebuilt.rebuilt == 3 and not rebuilt.errors

            # CLI 冒烟：list / show --json / proposals list
            config = _write_memory_config(root)
            cli = CognitionCLI(config_path=str(config)).cli
            runner = CliRunner()
            result = runner.invoke(cli, ["list", "--all"])
            assert result.exit_code == 0 and "确信度" in result.output
            result = runner.invoke(cli, ["show", belief.id, "--json"])
            assert result.exit_code == 0 and '"certainty": 0.6' in result.output
            result = runner.invoke(cli, ["proposals", "list", "--status", "all"])
            assert result.exit_code == 0 and proposal.id in result.output

            print("  ✅ 认知模块验收通过")
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
        "复习队列": run_resurface_section(),
        "CLI": run_cli_section(args.phase),
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

    if args.phase == "all":
        results["认知模块"] = run_cognition_section()
    else:
        print("⏳ 跳过认知模块（Phase 5，--phase all 时验收）")

    results["示例"] = run_examples_section()

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
