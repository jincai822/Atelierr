"""confirm_cli 单元测试：中台「确认/归档」按钮的 CLI 全流程（临时库）。

与飞书卡片回调同逻辑（dispatch/archive.py），这里锁 CLI 层的
退出码、文案与文件系统结果。
"""

from __future__ import annotations

import frontmatter
from click.testing import CliRunner

from scripts.cli.confirm_cli import main
from scripts.memory.core import MemoryTree


def _make_config(tmp_path):
    """在临时目录写配置（笔记目录 + 显式 state_dir），返回 (config, notes_dir)。"""
    config = tmp_path / "memory.yaml"
    config.write_text(
        f"memory:\n  root: {tmp_path}/memory\n  state_dir: {tmp_path}/state\n",
        encoding="utf-8",
    )
    return config, tmp_path / "memory"


def _invoke(config, *args):
    return CliRunner().invoke(main, [*args, "--config", str(config)])


def test_archive_moves_note_and_strips_tag(tmp_path, memory_tree):
    """推导归档：inbox 待确认卡 → memory/抖音/，摘标签、sidecar 随迁、正文原样。"""
    config, notes_dir = _make_config(tmp_path)
    memory_tree.create_note(
        "douyin-x.md",
        "---\ntitle: 跑步教学合集\nsource: link\ntags: [待确认, 抖音]\n---\n正文行\n",
        inbox=True,
    )

    result = _invoke(config, "inbox/douyin-x.md")
    assert result.exit_code == 0, result.output
    assert "📁 已确认并归档到 抖音/" in result.output
    assert "跑步教学合集" in result.output

    moved = notes_dir / "抖音" / "douyin-x.md"
    assert moved.exists()
    assert not (tmp_path / "inbox" / "douyin-x.md").exists()
    post = frontmatter.loads(moved.read_text(encoding="utf-8"))
    assert post.metadata["tags"] == ["抖音"]
    assert "正文行" in post.content
    # sidecar 已按 id 随迁：新位置能按 path 反查到条目
    assert MemoryTree.from_config(str(config)).layer_of(moved) == "short-term"


def test_archive_fallback_confirm_only_when_no_platform(tmp_path, memory_tree):
    """推导不出平台：退化为仅确认——留原处、摘标签、文案说明。"""
    config, notes_dir = _make_config(tmp_path)
    memory_tree.create_note(
        "闪念.md", "---\nsource: link\ntags: [待确认]\n---\n一句话\n", inbox=True
    )

    result = _invoke(config, "闪念.md")
    assert result.exit_code == 0, result.output
    assert "留在收件箱" in result.output

    stayed = tmp_path / "inbox" / "闪念.md"
    assert stayed.exists()
    post = frontmatter.loads(stayed.read_text(encoding="utf-8"))
    assert post.metadata["tags"] == []


def test_confirm_only_flag_is_idempotent(tmp_path, memory_tree):
    """--confirm-only：只摘标签不移动；再跑一次 → 无需确认（幂等）。"""
    config, _ = _make_config(tmp_path)
    memory_tree.create_note(
        "x.md", "---\nsource: link\ntags: [待确认, 抖音]\n---\n正文\n", inbox=True
    )

    first = _invoke(config, "x.md", "--confirm-only")
    assert first.exit_code == 0, first.output
    assert "✅ 已确认" in first.output
    stayed = tmp_path / "inbox" / "x.md"
    assert stayed.exists()
    assert frontmatter.loads(stayed.read_text(encoding="utf-8")).metadata["tags"] == ["抖音"]

    second = _invoke(config, "x.md", "--confirm-only")
    assert second.exit_code == 0, second.output
    assert "无需确认" in second.output


def test_missing_note_exits_1(tmp_path, memory_tree):
    """笔记不存在：退出码 1 + 文案说明（死卡是正常终态，措辞不吓人）。"""
    config, _ = _make_config(tmp_path)
    result = _invoke(config, "ghost.md")
    assert result.exit_code == 1
    assert "已不在库中" in result.output


def test_invalid_dir_exits_1(tmp_path, memory_tree):
    """显式非法目录：拒绝并退出 1（绝不移动到机器区/逃逸路径）。"""
    config, _ = _make_config(tmp_path)
    memory_tree.create_note("x.md", "---\ntags: [待确认]\n---\n正文\n", inbox=True)
    result = _invoke(config, "x.md", "--dir", "../evil")
    assert result.exit_code == 1
    assert "归档目录非法" in result.output
    assert (tmp_path / "inbox" / "x.md").exists()


def test_explicit_dir_archives(tmp_path, memory_tree):
    """显式合法目录（平台/分类二级）：按人点目录移动 + 摘标签。"""
    config, notes_dir = _make_config(tmp_path)
    memory_tree.create_note(
        "x.md", "---\nsource: link\ntags: [待确认]\n---\n正文\n", inbox=True
    )
    result = _invoke(config, "x.md", "--dir", "抖音/B84-心理学")
    assert result.exit_code == 0, result.output
    assert "抖音/B84-心理学/" in result.output
    assert (notes_dir / "抖音" / "B84-心理学" / "x.md").exists()


def test_ambiguous_name_exits_1(tmp_path, memory_tree):
    """同名两篇：拒绝操作（给不出文件级精确操作），退出 1。"""
    config, notes_dir = _make_config(tmp_path)
    memory_tree.create_note("x.md", "---\ntags: [待确认]\n---\n正文\n", inbox=True)
    subdir = notes_dir / "抖音"
    subdir.mkdir(parents=True)
    (subdir / "x.md").write_text("---\ntags: []\n---\n另一篇\n", encoding="utf-8")

    result = _invoke(config, "x.md")
    assert result.exit_code == 1
    assert "同名" in result.output
