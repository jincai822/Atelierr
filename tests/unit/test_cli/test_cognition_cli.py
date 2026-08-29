"""cognition_cli 单元测试：COG-CLI-01..04（验收 §4.8）。

断言以 docs/ACCEPTANCE-CRITERIA.md v1.1 与 COGNITION-SPEC v1.0 §6.3 为准。
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import frontmatter
from click.testing import CliRunner

from scripts.cli.cognition_cli import CognitionCLI
from scripts.memory.cognition import ApprovalRecord, CognitionManager
from scripts.memory.core import MemoryTree

REPO_ROOT = Path(__file__).resolve().parents[3]


def _make_cli(tmp_path):
    """临时 $OV 布局 + 配置文件 + CLI；返回 (cli, manager, tree)。"""
    config = tmp_path / "memory.yaml"
    config.write_text(
        f"memory:\n  root: {tmp_path}/memory\n  state_dir: {tmp_path}/state\n",
        encoding="utf-8",
    )
    manager = CognitionManager(tmp_path, state_dir=tmp_path / "state")
    tree = MemoryTree(tmp_path / "memory", state_dir=tmp_path / "state")
    return CognitionCLI(config_path=str(config)).cli, manager, tree


def test_cli_entrypoint():
    """COG-CLI-01：独立入口 python -m scripts.cli.cognition_cli 可用。"""
    result = subprocess.run(
        [sys.executable, "-m", "scripts.cli.cognition_cli", "--help"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0
    for command in ("create", "nominate", "promote", "challenge", "validate"):
        assert command in result.stdout


def test_mutations_require_confirmation(tmp_path):
    """COG-CLI-02：语义变更默认显示 diff 并要求确认；中止则不写盘。"""
    cli, manager, _ = _make_cli(tmp_path)
    runner = CliRunner()
    args = [
        "create",
        "--type",
        "belief",
        "--title",
        "测试",
        "--statement",
        "陈述",
        "--certainty",
        "0.8",
    ]
    # 不确认（输入 n）→ 中止，无文件
    result = runner.invoke(cli, args, input="n\n")
    assert result.exit_code != 0
    assert list(manager.cognition_dir.glob("*.md")) == []
    # 确认 → 创建
    result = runner.invoke(cli, args, input="y\n")
    assert result.exit_code == 0, result.output
    assert "+certainty" in result.output  # 显示了完整 diff
    assert len(list(manager.cognition_dir.glob("*.md"))) == 1


def test_dry_run_is_side_effect_free(tmp_path):
    """COG-CLI-03：--dry-run 不写 cognition、index 或 proposal 终态。"""
    cli, manager, tree = _make_cli(tmp_path)
    runner = CliRunner()

    result = runner.invoke(
        cli,
        [
            "create",
            "--type",
            "question",
            "--title",
            "问题",
            "--statement",
            "这是真的吗？",
            "--dry-run",
        ],
    )
    assert result.exit_code == 0, result.output
    assert "未写入" in result.output
    assert list(manager.cognition_dir.glob("*.md")) == []
    assert not manager.index_path.exists()
    assert not manager.proposals_path.exists()

    # promote --dry-run：proposal 保持 pending，不创建 cognition
    note = tree.create_note("src.md", "来源内容")
    memory_id = frontmatter.loads(note.read_text(encoding="utf-8")).metadata["id"]
    proposal = manager.nominate_memory(
        memory_id,
        entry_type="belief",
        title="提名",
        statement="提名陈述。",
        rationale="理由",
        proposed_status="active",
        proposed_certainty=0.6,
    )
    result = runner.invoke(cli, ["promote", proposal.id, "--dry-run"])
    assert result.exit_code == 0, result.output
    assert "未写入" in result.output
    assert list(manager.cognition_dir.glob("*.md")) == []
    assert manager.list_promotion_proposals()[0].id == proposal.id


def test_cli_terminology(tmp_path):
    """COG-CLI-04：cognition 显示“确信度”，memory 信号显示“新鲜度”。"""
    cli, manager, tree = _make_cli(tmp_path)
    runner = CliRunner()

    result = runner.invoke(
        cli,
        [
            "create",
            "--type",
            "belief",
            "--title",
            "术语",
            "--statement",
            "陈述",
            "--certainty",
            "0.78",
        ],
        input="y\n",
    )
    assert result.exit_code == 0, result.output

    result = runner.invoke(cli, ["list"])
    assert "确信度" in result.output
    assert "新鲜度" not in result.output

    note = tree.create_note("term.md", "术语来源")
    memory_id = frontmatter.loads(note.read_text(encoding="utf-8")).metadata["id"]
    result = runner.invoke(
        cli,
        [
            "nominate",
            memory_id,
            "--type",
            "belief",
            "--statement",
            "新陈述。",
        ],
    )
    assert result.exit_code == 0, result.output
    assert "新鲜度" in result.output  # memory confidence 的显示术语

    # --json 输出存储值（四位精度）且不混交互提示
    entry_id = manager.list_entries()[0].id
    manager.reassess_entry(
        entry_id,
        evidence=[],
        certainty=0.12345,
        status="active",
        rationale="精度",
        approval=ApprovalRecord(action="t", reason="r"),
    )
    result = runner.invoke(cli, ["show", entry_id, "--json"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["certainty"] == 0.1235


def test_cli_full_lifecycle_and_error_codes(tmp_path):
    """CLI 全生命周期覆盖：show/proposals/validate/reindex/challenge/reassess/
    answer/supersede/archive + 稳定错误码 + main() 入口（覆盖率补充）。"""
    cli, manager, tree = _make_cli(tmp_path)
    runner = CliRunner()

    # create question（answer 流程用）与 belief
    result = runner.invoke(
        cli,
        [
            "create",
            "--type",
            "question",
            "--title",
            "问题",
            "--statement",
            "这是真的吗？",
        ],
        input="y\n",
    )
    assert result.exit_code == 0, result.output
    result = runner.invoke(
        cli,
        [
            "create",
            "--type",
            "belief",
            "--title",
            "信念",
            "--statement",
            "初始陈述。",
            "--certainty",
            "0.8",
        ],
        input="y\n",
    )
    assert result.exit_code == 0, result.output
    question, belief = sorted(
        manager.list_entries(), key=lambda e: e.entry_type, reverse=True
    )

    # show（人类可读格式，含修订历史）
    result = runner.invoke(cli, ["show", belief.id])
    assert result.exit_code == 0, result.output
    assert "确信度: 0.80" in result.output
    assert "修订历史" in result.output
    # show 不存在 → 稳定退出码 3
    result = runner.invoke(cli, ["show", "cog_missing"])
    assert result.exit_code == 3

    # list --json / --type 过滤
    result = runner.invoke(cli, ["list", "--type", "belief", "--json"])
    assert result.exit_code == 0
    assert json.loads(result.output)[0]["type"] == "belief"

    # challenge propose → proposals list → resolve accept
    note = tree.create_note("ev.md", "反例来源")
    memory_id = frontmatter.loads(note.read_text(encoding="utf-8")).metadata["id"]
    result = runner.invoke(
        cli,
        [
            "challenge",
            belief.id,
            "--evidence-memory",
            memory_id,
            "--reason",
            "出现反例",
            "--certainty",
            "0.5",
        ],
    )
    assert result.exit_code == 0, result.output
    proposal_id = manager._list_proposals("challenge")[0]["id"]
    result = runner.invoke(cli, ["proposals", "list", "--kind", "challenge"])
    assert result.exit_code == 0 and proposal_id in result.output
    result = runner.invoke(cli, ["proposals", "list", "--json"])
    assert result.exit_code == 0 and json.loads(result.output)
    result = runner.invoke(
        cli,
        [
            "challenge",
            "resolve",
            proposal_id,
            "--resolution",
            "accept",
            "--certainty",
            "0.5",
            "--reason",
            "接受反例",
        ],
        input="y\n",
    )
    assert result.exit_code == 0, result.output
    assert manager.get_entry(belief.id).certainty == 0.5

    # challenge resolve reject（dry-run 后真实执行）
    result = runner.invoke(
        cli,
        ["challenge", belief.id, "--evidence-note", "弱反例", "--reason", "试探"],
    )
    assert result.exit_code == 0, result.output
    weak_id = manager._list_proposals("challenge")[0]["id"]
    result = runner.invoke(
        cli,
        [
            "challenge",
            "resolve",
            weak_id,
            "--resolution",
            "reject",
            "--reason",
            "证据不足",
            "--dry-run",
        ],
    )
    assert result.exit_code == 0 and "未写入" in result.output
    result = runner.invoke(
        cli,
        [
            "challenge",
            "resolve",
            weak_id,
            "--resolution",
            "reject",
            "--reason",
            "证据不足",
        ],
        input="y\n",
    )
    assert result.exit_code == 0, result.output
    # reject 缺 --reason → 用法错误（click 退出码 2）
    result = runner.invoke(cli, ["challenge", "resolve", weak_id])
    assert result.exit_code == 2

    # reassess（附 url 证据）
    result = runner.invoke(
        cli,
        [
            "reassess",
            belief.id,
            "--evidence-url",
            "https://example.com/bench",
            "--certainty",
            "0.7",
            "--status",
            "active",
            "--reason",
            "复核",
        ],
        input="y\n",
    )
    assert result.exit_code == 0, result.output
    assert manager.get_entry(belief.id).certainty == 0.7

    # answer（--related 指回 belief）
    result = runner.invoke(
        cli,
        ["answer", question.id, "--answer", "是真的。", "--related", belief.id],
        input="y\n",
    )
    assert result.exit_code == 0, result.output
    assert manager.get_entry(question.id).status == "answered"

    # supersede → 新条目 + 旧条目 superseded
    result = runner.invoke(
        cli,
        [
            "supersede",
            belief.id,
            "--statement",
            "收窄后的陈述。",
            "--certainty",
            "0.6",
            "--reason",
            "适用范围收窄",
        ],
        input="y\n",
    )
    assert result.exit_code == 0, result.output
    assert manager.get_entry(belief.id).status == "superseded"
    successor = manager.list_entries(entry_type="belief")[0]
    assert successor.supersedes == belief.id

    # proposals reject（promotion 流程）
    note2 = tree.create_note("rej.md", "被拒来源")
    mid2 = frontmatter.loads(note2.read_text(encoding="utf-8")).metadata["id"]
    result = runner.invoke(
        cli, ["nominate", mid2, "--type", "belief", "--statement", "被拒陈述。"]
    )
    assert result.exit_code == 0, result.output
    pending = manager.list_promotion_proposals()
    result = runner.invoke(
        cli, ["proposals", "reject", pending[0].id, "--reason", "不够原子"]
    )
    assert result.exit_code == 0, result.output
    assert not manager.list_promotion_proposals()

    # promote（真实确认）
    note3 = tree.create_note("pro.md", "升级来源")
    mid3 = frontmatter.loads(note3.read_text(encoding="utf-8")).metadata["id"]
    result = runner.invoke(
        cli, ["nominate", mid3, "--type", "hypothesis", "--statement", "假设。"]
    )
    assert result.exit_code == 0, result.output
    pid = manager.list_promotion_proposals()[0].id
    result = runner.invoke(cli, ["promote", pid, "--certainty", "0.5"], input="y\n")
    assert result.exit_code == 0, result.output
    hypothesis = manager.list_entries(entry_type="hypothesis")[0]

    # archive + validate + reindex
    result = runner.invoke(
        cli, ["archive", hypothesis.id, "--reason", "验收归档"], input="y\n"
    )
    assert result.exit_code == 0, result.output
    result = runner.invoke(cli, ["validate"])
    assert result.exit_code == 0 and "校验通过" in result.output
    result = runner.invoke(cli, ["reindex", "--dry-run"])
    assert result.exit_code == 0 and "dry-run" in result.output
    result = runner.invoke(cli, ["reindex", "--json"])
    assert result.exit_code == 0 and json.loads(result.output)["rebuilt"] == 4

    # validate 发现损坏文件 → 退出码 4
    broken = manager.cognition_dir / "broken--ffff0000.md"
    broken.write_text("---\n: bad: [unclosed\n---\n", encoding="utf-8")
    result = runner.invoke(cli, ["validate"])
    assert result.exit_code == 4
    assert "broken--ffff0000.md" in result.output

    # main() 入口（standalone_mode=False 返回退出码）
    from scripts.cli.cognition_cli import CognitionCLI as _CLI

    assert _CLI(config_path=str(tmp_path / "memory.yaml")).main(["list"]) == 0
