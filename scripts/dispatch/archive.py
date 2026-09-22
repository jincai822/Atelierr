"""归档目录推导：飞书卡片「📁 确认并归档」按钮与通知「建议归档」行共用。

规则（2026-09-21 原教旨改造第 4 条，用户拍板并放权）：
- 一级目录 = **领域**：取 frontmatter tags 里第一个中图法标签
  （``^[A-Z]{1,3}\\d*-``，如 B84-心理学），按 CLC_TO_DOMAIN 映射成
  领域目录（health/work/career/finance/personal/...）；前缀逐级
  回退——先缩数字（B849→B84 命中 health 特例），再缩字母（TN→T；
  TP 命中 career 优先于 T→work）；推导不出 → 默认 personal/
  （兜底，同裁决：分不出的一律有固定格子）；
- 2026-09-22 方案 C（用户拍板）：中图法全字母覆盖——B 拆出
  philosophy/（B84 心理学例外留 health），A/C/D/E/H/N/O/P/Q/S/V/X
  各有主题格子，目录按需创建，不再挤进 personal；
- 平台（抖音/小红书/书籍）与中图法分类号**降级为标签**，不再做
  文件夹——找东西按主题（领域）找，不按来源找；
- 二级目录取消（中图法只做映射依据，不再做文件夹）。

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

#: 中图法分类标签（如 B84-心理学 / TP311.5-软件测试）→ 领域映射依据
CCLASS_RE = re.compile(r"^[A-Z]{1,3}\d*-")

#: 待确认标签（与 dispatch/links.py、dispatch/media.py 的 REVIEW_TAG、
#: dispatch/feishu.py 的 CONFIRM_TAG 同值）
REVIEW_TAG = "待确认"

#: 中图法字母前缀 → 领域目录。
#: 2026-09-21 用户拍板的既有领域（career/work/health/finance/personal）
#: 沿用；2026-09-22 方案 C（用户拍板）：全字母覆盖，B 拆 philosophy
#: （B84 心理学特例留 health），其余字母各有主题格子，目录按需创建。
#: 匹配时前缀逐级回退：先缩数字（B849→B84），再缩字母（TN→T）。
CLC_TO_DOMAIN = {
    "B84": "health",  # 心理学 → 稳定内核（B 下唯一特例，数字回退命中）
    "B": "philosophy",  # 哲学·宗教（2026-09-22 从 health 拆出）
    "R": "health",   # 医药卫生
    "TP": "career",  # 计算机/AI → 搞懂 Agent
    "G": "career",   # 教育/自我提升
    "U": "work",     # 交通/汽车 → 汽车零部件
    "T": "work",     # 工业技术兜底（TP 优先命中 career）
    "F": "finance",  # 经济
    "I": "personal", "J": "personal", "K": "personal",  # 文艺史
    "Z": "personal",  # 综合
    "A": "theory",       # 马列毛邓理论
    "C": "society",      # 社会科学
    "D": "politics",     # 政治·法律
    "E": "military",     # 军事
    "H": "language",     # 语言·文字
    "N": "science",      # 自然科学
    "O": "math",         # 数理科学·化学
    "P": "earth",        # 天文·地球科学
    "Q": "biology",      # 生物科学
    "S": "agriculture",  # 农业科学
    "V": "aerospace",    # 航空·航天
    "X": "environment",  # 环境·安全
}

#: 领域推不出时的默认一级目录（手写/无来源/无中图法标签的固定格子，
#: 2026-09-21 裁决；飞书 FALLBACK_ARCHIVE_DIR 同值）
HANDWRITTEN_ARCHIVE_DIR = "personal"


def _clc_domain(tag: str) -> Optional[str]:
    """中图法标签 → 领域：前缀逐级回退查 CLC_TO_DOMAIN。

    回退顺序：先连字母带数字逐级缩数字（B849→B84→B8→B，让
    B84→health 特例能命中，2026-09-22 方案 C），再缩字母
    （TP→T；TN→T）。
    """
    m = re.match(r"^([A-Z]+)(\d*)", tag)
    if not m:
        return None
    letters, digits = m.group(1), m.group(2)
    candidates = [letters + digits[:i] for i in range(len(digits), -1, -1)]
    candidates += [letters[:j] for j in range(len(letters) - 1, 0, -1)]
    for cand in candidates:
        domain = CLC_TO_DOMAIN.get(cand)
        if domain:
            return domain
    return None


def clc_to_domain(tag: str) -> Optional[str]:
    """中图法标签（如 B84-心理学）→ 领域目录的公开门脸；推不出返回 None。

    与 derive_archive_dir 的区别：本函数直接吃分类字符串，不经
    frontmatter——剪藏放权（2026-09-21）的归档依据来自卡片管道的 LLM
    摘要（category 字段），剪藏笔记本身不改写、不补中图法标签。
    """
    if not CCLASS_RE.match(tag or ""):
        return None
    return _clc_domain(tag)


def derive_archive_dir(post) -> Tuple[Optional[str], Optional[str]]:
    """从一篇笔记的 frontmatter Post 推导归档目录 (领域, None)。

    Args:
        post: python-frontmatter 的 Post 对象（metadata 含 source/tags）。

    Returns:
        Tuple[Optional[str], Optional[str]]: (领域目录名, None)；领域
        推不出为 None（兜底在 archive_note 与飞书目录选择卡）。第二
        位保留只为兼容旧调用形状——二级目录已取消（2026-09-21）。
    """
    tags = [str(tag) for tag in (post.metadata.get("tags") or [])]
    clc = next((tag for tag in tags if CCLASS_RE.match(tag)), None)
    if clc is None:
        return None, None
    return _clc_domain(clc), None


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
    或机器推导（领域，规则见 derive_archive_dir；领域推不出 = 手写/
    无来源笔记 → 默认 personal/，2026-09-21 用户裁决）→ 已在目标目录
    则只删标签（幂等，
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
        domain, _none = derive_archive_dir(post)
        if domain is None:
            # 领域推不出 = 手写/无来源/无中图法标签：落默认 personal/
            #（2026-09-21 用户裁决，兜底）
            domain = HANDWRITTEN_ARCHIVE_DIR
        target_dir = domain
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


def auto_archive(tree: MemoryTree, filename: str) -> Optional[str]:
    """放权自动归档（2026-09-21 用户裁决：机器产出的新笔记产出即归档，
    不再逐条人工审批）。

    就是 archive_note 的"不问人"包装：成功返回领域目录名（通知文案
    用）；任何失败返回 None——笔记留在 inbox 带「待确认」，照旧走
    人工确认卡（放权只放顺利路径，异常一律留人兜底，绝不硬搬）。

    Args:
        tree: MemoryTree。
        filename: 刚产出的笔记文件名（可带 inbox/ 虚拟前缀）。
    """
    ok, detail = archive_note(tree, filename)
    if not ok:
        return None
    if detail == "tag_fail":
        # 移动成功仅标签摘除失败：按已归档算（标签人工后补），
        # 目录名 archive_note 没带回，重推一次
        note_path, _err = locate_note(tree, filename)
        if note_path is None:
            return None
        try:
            post = frontmatter.loads(note_path.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001 - 读不出按未归档降级
            return None
        domain, _none = derive_archive_dir(post)
        return domain or HANDWRITTEN_ARCHIVE_DIR
    return detail
