"""归档目录推导：飞书卡片「📁 确认并归档」按钮与通知「建议归档」行共用。

规则（与用户在 Obsidian 的手动归档约定一致）：
- 一级目录 = 平台：source=lark → 飞书；source=media → 媒体；
  source=link 或其它 → 取 frontmatter tags 里第一个平台标签
  （排除「待确认」与中图法类目标签，如 抖音/小红书）；取不到 →
  默认类目 笔记/（2026-09-20 用户裁决：手写/无来源笔记也有固定
  格子，取代 09-12"退化为仅确认留收件箱"；derive 本身仍返回
  None，兜底在 archive_note 与飞书目录选择卡里）；
- 二级目录（可选）= 中图法分类标签：tags 里第一个匹配
  ``^[A-Z]{1,3}\\d*-`` 的标签（如 B84-心理学），没有就只进一级目录。

确认/归档的库级核心逻辑（locate_note / strip_tag / confirm_note /
archive_note 等）也住这里：飞书卡片回调（dispatch/feishu.py）与
Obsidian 中台按钮（cli/confirm_cli.py）共用同一份实现，避免规则漂移。
"""

from __future__ import annotations

import os
import re
import tempfile
from pathlib import Path
from typing import Callable, Optional, Tuple

import frontmatter

from scripts.memory.core import NOTE_EXCLUDED_DIRS, MemoryTree

#: 中图法分类标签（如 B84-心理学 / TP311.5-软件测试）→ 归档二级目录名
CCLASS_RE = re.compile(r"^[A-Z]{1,3}\d*-")

#: 待确认标签（与 dispatch/links.py、dispatch/media.py 的 REVIEW_TAG、
#: dispatch/feishu.py 的 CONFIRM_TAG 同值）；推导平台时不算平台标签
REVIEW_TAG = "待确认"

#: source → 归档一级目录（平台）名
PLATFORM_BY_SOURCE = {"lark": "飞书", "media": "媒体"}

#: 平台推不出时的默认一级目录（手写/无来源笔记的固定格子，
#: 2026-09-20 用户裁决；飞书 FALLBACK_ARCHIVE_DIR 同值）
HANDWRITTEN_ARCHIVE_DIR = "笔记"


def derive_archive_dir(post) -> Tuple[Optional[str], Optional[str]]:
    """从一篇笔记的 frontmatter Post 推导归档目录 (平台, 分类标签)。

    Args:
        post: python-frontmatter 的 Post 对象（metadata 含 source/tags）。

    Returns:
        Tuple[Optional[str], Optional[str]]: (平台目录名, 中图法分类
        标签)；平台推不出为 None，分类没有为 None。目录相对串 =
        ``平台 + ("/" + 分类 if 分类)``。
    """
    metadata = post.metadata
    source = str(metadata.get("source") or "")
    tags = [str(tag) for tag in (metadata.get("tags") or [])]
    if source in PLATFORM_BY_SOURCE:
        platform = PLATFORM_BY_SOURCE[source]
    else:
        platform = next(
            (
                tag
                for tag in tags
                if tag != REVIEW_TAG and not CCLASS_RE.match(tag)
            ),
            None,
        )
    category = next((tag for tag in tags if CCLASS_RE.match(tag)), None)
    return platform, category


#: 文件名/目录段非法字符（与 dispatch/feishu.py 的 _ILLEGAL_RE 同值；
#: archive 不能回引 feishu——feishu 依赖本模块，故各持一份）
_ILLEGAL_RE = re.compile(r'[\\/:*?"<>|]')


def atomic_write(target: Path, blob: bytes) -> None:
    """临时文件 + rename 原子落盘（防 Syncthing 抢到半成品）。"""
    fd, tmp_path = tempfile.mkstemp(dir=str(target.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(blob)
        os.replace(tmp_path, target)
    except OSError:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def locate_note(tree: MemoryTree, filename: str) -> Tuple[Optional[Path], Optional[str]]:
    """校验并按文件名定位笔记：返回 (path, None) 或 (None, 错误详情)。

    校验：文件名须为纯文件名（无路径分隔、无 ``..``、``*.md``）——
    用户手拖归档后位置未知，故用文件名在整个归档树里查找（排除
    wiki/attachments/trash 等特殊目录）。恰好一个匹配才操作：0 个
    返回 "笔记不存在"，多个返回 "歧义"（同名冲突，给不出文件级
    精确操作，请人到 Obsidian 处理）。确认与归档共用此定位。

    ``inbox/`` 虚拟前缀豁免（2026-09-16 实证）：卡片/按钮传入可能带
    ``inbox/`` 前缀（供发送侧 Obsidian URI 解析），定位前剥掉按纯
    文件名处理。
    """
    if filename.startswith("inbox/"):
        filename = filename[len("inbox/"):]
    if (
        not filename
        or "/" in filename
        or "\\" in filename
        or ".." in filename
        or not filename.endswith(".md")
    ):
        return None, "非法路径"
    matches = [path for path in tree.iter_all_note_files() if path.name == filename]
    if not matches:
        return None, "笔记不存在"
    if len(matches) > 1:
        return None, "歧义"
    return matches[0], None


def strip_tag(note_path: Path, tag: str) -> bool:
    """移除单篇笔记 frontmatter tags 里的指定一项（其余一概不动）。

    仅当 tags 含该标签才改写（幂等：没有不改写）；改写只删该标签一项，
    frontmatter 其余字段与正文经 round-trip 原样保留。

    Returns:
        bool: 实际改写了返回 True；无标签（noop）返回 False。
    """
    text = note_path.read_text(encoding="utf-8")
    post = frontmatter.loads(text)
    tags = post.metadata.get("tags")
    if not isinstance(tags, list) or tag not in tags:
        return False
    post.metadata["tags"] = [item for item in tags if item != tag]
    atomic_write(note_path, frontmatter.dumps(post).encode("utf-8"))
    return True


def valid_archive_dir(target_dir: str) -> bool:
    """归档目标目录校验：1-2 级纯相对路径，一级目录非机器专用目录。

    目录来自外部输入（卡片回调 / CLI 参数）：拒绝绝对路径、``..``、
    反斜杠、非法字符、三级及以上、wiki/系统/attachments/trash/templates
    （NOTE_EXCLUDED_DIRS 成员，归档进去等于藏进机器区）。非法字符按段
    校验：段分隔符 "/" 本身合法——整串校验会把所有二级目录误杀
    （2026-09-17 实证：目录选择卡的「推荐」项是 平台/分类 二级路径）。
    """
    if not target_dir or "\\" in target_dir or target_dir.startswith("/"):
        return False
    parts = target_dir.split("/")
    if len(parts) > 2 or any(
        part in ("", ".", "..") or _ILLEGAL_RE.search(part) for part in parts
    ):
        return False
    return parts[0] not in NOTE_EXCLUDED_DIRS


def confirm_note(tree: MemoryTree, filename: str) -> Tuple[bool, str]:
    """「✅ 确认」核心：定位笔记 + 移除待确认标签。

    Returns:
        Tuple[bool, str]: (是否成功, 详情串 ok / noop / 歧义 /
        非法路径 / 笔记不存在)。
    """
    note_path, err = locate_note(tree, filename)
    if err:
        return False, err
    stripped = strip_tag(note_path, REVIEW_TAG)
    return True, "ok" if stripped else "noop"


def _strip_review_default(path: Path) -> bool:
    """默认删「待确认」标签实现（archive_note 的可注入缝）。"""
    return strip_tag(path, REVIEW_TAG)


def archive_note(
    tree: MemoryTree,
    filename: str,
    target_dir: Optional[str] = None,
    strip_review_fn: Optional[Callable[[Path], bool]] = None,
) -> Tuple[bool, str]:
    """「📁 确认并归档」核心（2026-09-07 批准的人工例外之二；09-09 起人点目录）。

    定位（与确认同）→ 目标目录：显式给定（先经 valid_archive_dir 校验）
    或机器推导（平台[/分类]，规则见 derive_archive_dir；平台推不出 =
    手写/无来源笔记 → 默认类目 笔记/，2026-09-20 用户裁决，取代
    09-12"退化为仅确认留收件箱"）→ 已在目标目录则只删标签（幂等，
    不移动）→ 否则：目标重名检查（绝不覆盖）→ mkdir → rename →
    sidecar 按 id 即时迁移 path（MemoryTree.relocate_entry，动态状态
    原样保留，不等 watcher 班次）→ 删「待确认」标签。移动成功但删
    标签失败：log 警告并返回 (True, "tag_fail")（提示手动摘除，
    绝不回滚）。

    Args:
        strip_review_fn: 删标签动作的可注入缝（默认 _strip_review_default）。
            FeishuBridge 传入自己的 _strip_review_tag，保持卡片回调的
            既有替换点与日志路径不变。

    Returns:
        Tuple[bool, str]: 成功返回 (True, 目标相对目录) 或
            (True, "tag_fail")；失败返回 (False, 错误详情串)。
    """
    strip = strip_review_fn or _strip_review_default
    note_path, err = locate_note(tree, filename)
    if err:
        return False, err
    if target_dir is None:
        post = frontmatter.loads(note_path.read_text(encoding="utf-8"))
        platform, category = derive_archive_dir(post)
        if platform is None:
            # 平台推不出 = 手写/无来源笔记：落默认类目 笔记/（2026-09-20
            # 用户裁决，取代 09-12"退化为仅确认留收件箱"）
            platform = HANDWRITTEN_ARCHIVE_DIR
        target_dir = platform if not category else f"{platform}/{category}"
    elif not valid_archive_dir(target_dir):
        return False, "非法目录"
    current_rel = tree._rel_key(note_path)
    if "/" in current_rel and current_rel.rsplit("/", 1)[0] == target_dir:
        # 已在目标目录：幂等，只删标签不移动
        strip(note_path)
        return True, target_dir
    # 目标文件名用定位后的实体名（调用方可能带 inbox/ 虚拟前缀，
    # 直接用传入名会拼出 平台/分类/inbox/ 嵌套目录——2026-09-17 实证）
    target = Path(tree.notes_dir) / target_dir / note_path.name
    if target.exists():
        return False, "目标重名"
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        note_path.rename(target)
    except OSError as exc:
        print(f"[archive] archive note={filename} move fail: {exc}", flush=True)
        return False, "移动失败"
    note_id = tree._read_note_id(target)
    if note_id is not None:
        tree.relocate_entry(note_id, tree._rel_key(target))
    try:
        strip(target)
    except Exception as exc:  # noqa: BLE001 - 半截状态提示手动摘除
        print(
            f"[archive] archive note={filename} moved but tag strip fail: {exc}",
            flush=True,
        )
        return True, "tag_fail"
    return True, target_dir
