"""Atelierr 笔记确认 CLI（Obsidian 中台按钮与终端共用）。

与飞书卡片回调同一份逻辑（dispatch/archive.py 的 confirm_note /
archive_note，2026-09-20 抽取共用）：

- 默认「确认并归档」（同飞书 📁 按钮）：按文件名定位 → 机器推导归档
  目录（平台[/分类]，规则见 dispatch/archive.py）→ 移动 + sidecar
  按 id 迁移 + 摘除「待确认」标签；推导不出平台时退化为仅确认
  （只删标签、留在收件箱）；
- ``--confirm-only`` 只确认不移动（同飞书 ✅ 按钮）。

结果单行打印（Obsidian Shell Commands 插件弹通知可见）；失败写
stderr 并以退出码 1 结束。

用法:
    python -m scripts.cli.confirm_cli douyin-xxx.md
    python -m scripts.cli.confirm_cli douyin-xxx.md --confirm-only
    python -m scripts.cli.confirm_cli douyin-xxx.md --dir 抖音/B84-心理学
"""

from __future__ import annotations

import sys
from typing import Optional

import click
import frontmatter

from scripts.cli.memory_cli import DEFAULT_ROOT, DEFAULT_STATE_DIR, resolve_config_path
from scripts.dispatch.archive import archive_note, confirm_note, locate_note
from scripts.memory.core import MemoryTree


def _build_tree(config_path: Optional[str]) -> MemoryTree:
    """按配置构造 MemoryTree；无配置时用内置默认路径（与 memory_cli 同规则）。"""
    resolved = resolve_config_path(config_path)
    if resolved is not None:
        return MemoryTree.from_config(resolved)
    return MemoryTree(DEFAULT_ROOT, state_dir=DEFAULT_STATE_DIR)


def _display_name(filename: str) -> str:
    """展示用名：剥 inbox/ 虚拟前缀与 .md 后缀。"""
    name = filename[len("inbox/"):] if filename.startswith("inbox/") else filename
    return name[:-3] if name.endswith(".md") else name


def _feedback_title(tree: MemoryTree, filename: str) -> str:
    """反馈文案的标题：frontmatter title 优先，取不到用文件名（任何失败不抛异常）。"""
    try:
        path, _err = locate_note(tree, filename)
        if path is not None:
            post = frontmatter.loads(path.read_text(encoding="utf-8"))
            title = str(post.metadata.get("title") or "").strip()
            if title:
                return title
    except Exception:  # noqa: BLE001 - 文案组装绝不让结果变失败
        pass
    return _display_name(filename)


def _success_line(title: str, detail: str, confirm_only: bool) -> str:
    """成功结果的单行文案（与飞书反馈文案同口径）。"""
    if confirm_only:
        if detail == "ok":
            return f"✅ 已确认：{title}"
        return f"ℹ️ 没有「待确认」标签，无需确认：{title}"
    if detail == "tag_fail":
        return f"⚠️ 已归档，「待确认」标签请到 Obsidian 手动摘除：{title}"
    return f"📁 已确认并归档到 {detail}/：{title}"


def _fail_line(filename: str, detail: str) -> str:
    """失败结果的单行文案（原因短语与 feishu.py _error_reason 同口径）。"""
    reason = {
        "笔记不存在": "ℹ️ 笔记已不在库中（可能已归档或回收），无需操作",
        "歧义": "⚠️ 存在多篇同名笔记，请到 Obsidian 处理",
        "目标重名": "⚠️ 目标文件夹已有同名笔记，请到 Obsidian 处理",
        "非法目录": "⚠️ 归档目录非法（1-2 级相对路径，不能是机器专用目录）",
        "非法路径": "⚠️ 文件名非法",
        "移动失败": "⚠️ 移动失败，请稍后重试",
    }.get(detail, f"⚠️ 处理失败：{detail}")
    return f"{reason}：{_display_name(filename)}"


@click.command()
@click.argument("filename")
@click.option(
    "--dir",
    "target_dir",
    default=None,
    help="显式归档目录（平台[/分类]）；缺省按 frontmatter 机器推导",
)
@click.option("--confirm-only", is_flag=True, help="只摘除「待确认」标签，不移动")
@click.option(
    "--config",
    "config_path",
    type=click.Path(dir_okay=False),
    default=None,
    help="配置文件路径（覆盖环境变量与默认值）",
)
def main(
    filename: str, target_dir: Optional[str], confirm_only: bool, config_path: Optional[str]
) -> None:
    """确认一篇笔记（默认确认并归档，与飞书卡片按钮同逻辑）。"""
    tree = _build_tree(config_path)
    if confirm_only:
        ok, detail = confirm_note(tree, filename)
    else:
        ok, detail = archive_note(tree, filename, target_dir)
    if ok:
        click.echo(_success_line(_feedback_title(tree, filename), detail, confirm_only))
        return
    click.echo(_fail_line(filename, detail), err=True)
    sys.exit(1)


if __name__ == "__main__":
    main()
