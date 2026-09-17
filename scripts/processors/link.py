"""链接抓取处理器（抖音/小红书/B站：分享文本 → 视频下载 → Whisper 转写）。

与其他处理器不同，``process()`` 的 ``input_path`` 形参承载的是**一段
分享文本或 URL**，不是文件路径。流程：提取 URL → 识别平台 →
下载视频到临时目录（B站长视频限高 480p 防大文件）→ 复用
:class:`VideoProcessor` 转写 → 组装带来源行的 Markdown → 清理临时文件。

输出格式（v4，2026-09-12 方案 B 用户裁决·卡形态）：标题 + 来源行 +
（视频笔记内嵌 480p 原视频）+ 观点总结 /
分观点论述 / 金句摘录 / 提到的人·书·概念（LLM 生成，附中图法分类与主题词，
经笔记 frontmatter ``tags`` 追加到"待确认"与平台标签之后）+ 正文——
正文 ≤ INLINE_BODY_MAX（base.py，800 字符）内联 ``## 转写全文``；
超过则**外置**：卡上只留 ``## 全文`` 链接节，全文经
``metadata["transcript_rel"]/["transcript_text"]`` 交回，由 dispatch
落盘 ``attachments/<平台>/<同名>.md``（与 480p 视频同主名成对）。
正文优先经 LLM 整理（按语义分段、补全标点、逐字不改写）；LLM 不可用/
失败时降级为机械分段（去除逐句时间戳、按句界合并自然段、繁体转简体
OpenCC），不带分类标签。LLM 摘要与整理经配置 ``processors.link.llm`` 启用：
API key 从环境变量读取（默认 DEEPSEEK_API_KEY，不落盘到 config）；
key 缺失、转写超长（成本护栏）或调用失败时自动降级，绝不阻塞入库管线。

原视频保存（2026-09-10 用户裁决 G2）：转写完成后 ffmpeg 压成 480p
（H.264 crf30 + AAC 96k，小片源不放大），以 bytes 经 ``metadata
["video_blob"]`` 交回——本处理器不感知存储，由 dispatch/links.py 落盘
``attachments/<平台>/`` 并嵌入笔记（``metadata["video_rel"]`` 为相对
路径，markdown 里的 ``![[...]]`` 与之同串）；下载原件随临时目录删除。
**压缩失败保留原件字节保底**（绝不能压坏了还丢原件）；读取也失败则
不附带视频，笔记照出（来源行 URL 仍可回溯）。

反爬约束（2026-08-31/09-01 真实样本实测）：抖音详情 API 对匿名请求
403，yt-dlp 借浏览器 cookie（``cookiesfrombrowser``）可拿到视频流
地址完成下载；cookie 失效时用无头 Chrome 访问视频页自动刷新
（专用 profile，见配置 chrome_profile_dir），再携新 cookie 重试一次，
无需人工打开浏览器。标题/作者优先取 yt-dlp 元数据，缺失时回退解析
分享文本（``【作者的作品】标题 https://...`` 结构）。

小红书（2026-09-02 真实样本实测）：短链 xhslink.cn 302 跳转到
xiaohongshu.com 详情页（须手机 UA）；页面内嵌 ``__INITIAL_STATE__``
JSON（``noteData.data.noteData``）给出标题/正文/作者/视频流地址，
yt-dlp 的 XiaoHongShu 提取器已失效（No video formats found），故
直接解析页面并用 httpx 带 Referer 下载视频流；图文笔记（无视频流）
直接以正文入库，不走 Whisper。

触发方式：dispatch 定时器自动分发（scripts/dispatch/links.py）或
人工执行 CLI（process_cli link 子命令）。

单元测试 monkeypatch ``yt_dlp.YoutubeDL``、``VideoProcessor`` 与
httpx 页面获取，无真实网络与模型下载。
"""

from __future__ import annotations

import json
import logging
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

import httpx
import opencc
import yt_dlp

from scripts.processors.base import INLINE_BODY_MAX, BaseProcessor, ProcessResult
from scripts.processors.image import ImageProcessor
from scripts.processors.video import VideoProcessor, compress_to_480p

logger = logging.getLogger(__name__)

#: 抖音域名（短链 / 视频页 / 分享页）
_DOUYIN_HOSTS: Tuple[str, ...] = (
    "v.douyin.com",
    "www.douyin.com",
    "www.iesdouyin.com",
)

#: 小红书域名（短链 / 详情页）
_XHS_HOSTS: Tuple[str, ...] = (
    "xhslink.cn",
    "www.xiaohongshu.com",
    "xiaohongshu.com",
)

#: B站域名（视频页 / b23 短链；2026-09-10 用户裁决：只做 B站，YouTube 进 backlog）
_BILIBILI_HOSTS: Tuple[str, ...] = (
    "bilibili.com",
    "b23.tv",
)

#: B站下载限高（长视频防大下载；480p 与保存规格一致，够 Whisper 用）
_BILIBILI_MAX_HEIGHT = 480

#: 小红书页面抓取用的手机 UA（桌面 UA 会被短链 404 / 详情页风控）
_XHS_UA = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1"
)

#: 详情页内嵌数据块 ``window.__INITIAL_STATE__ = {...}``
_XHS_STATE_RE = re.compile(
    r"window\.__INITIAL_STATE__\s*=\s*(\{.*?\})\s*</script>", re.S
)

#: 分享文本中作者的结构（"看看【武世红的作品】..."）
_AUTHOR_RE = re.compile(r"【(?P<author>.+?)的作品】")

#: URL 提取（到第一个空白字符为止）
URL_RE = re.compile(r"https?://[^\s]+")

#: URL 首尾可能粘附的中文标点
URL_TRAILING = "。，、！？；：）》\"'…"

#: 视频下载后按扩展名在临时目录里定位产物
_VIDEO_EXTS: Tuple[str, ...] = (".mp4", ".mkv", ".webm", ".mov", ".flv")

#: LLM 摘要默认接入点（OpenAI 兼容接口）与模型
_LLM_DEFAULT_BASE_URL = "https://api.deepseek.com"
_LLM_DEFAULT_MODEL = "deepseek-v4-flash"

#: 产出笔记的"人工确认"标签（与 dispatch/links.py REVIEW_TAG 同值；
#: 笔记经该标签进入晨报待确认清单，人在 Obsidian 阅读后自行移除）
_REVIEW_TAG = "待确认"

#: 链接整理（_summarize）的 v4 提示词，末尾拼转写全文。
#: 输出：summary / points / insights / entities / category / topics / title；
#: category 取自中图法两级分类表（二级优先，大类兜底，Z 综合收尾）；
#: title 是语义标题，供平台占位标题（「Douyin video #id」）兜底用。
_SUMMARIZE_V4_PROMPT = """请阅读以下视频转写全文，为个人知识库生成结构化笔记元数据，只输出 JSON：
{"summary": "...", "points": ["..."], "insights": ["..."], "entities": ["..."], "category": "...", "topics": ["..."], "title": "..."}。
要求：
- title：10-20 字语义标题，一句话概括核心内容（如"经济危机是社会关系的危机"），可直接作笔记文件名；不带平台名、不带 #、不带书名号。
- summary：150-250 字，一段话讲清核心论点和论证脉络。
- points：分观点论述，覆盖原文全部独立论点，合并同义反复，5-8 条；每条独立成句、不依赖上下文，不超过 60 字，按论述顺序排列。
- insights：金句摘录，原文中最有价值的原话（关键判断/反常识观点），3-5 条。**必须逐字照抄原文，含标点符号**——禁止改写、禁止删标点（2026-09-14 实测：丢标点的"金句"是转述不是摘录）；原话过长可截取连续片段，字词与标点一个都不许动。
- entities：原文提到的书籍/人物/概念，格式"名称（谁的作品/什么人/什么意思）"；没有则空数组。
- category：从下方分类表选 1 个最贴切的类目，优先选二级类（如 B84-心理学）；二级无合适的用大类（如 B-哲学）；无法归类用 Z-综合。**类目必须带类名**（照抄表内条目如 G79自学·自我提升），禁止只给裸编号（如 G79）——裸编号无法归档，等于没分类。禁止编造表外编号，拿不准就选更宽的类。
- topics：3-6 个自由主题词，短语，覆盖跨领域内容。
只依据原文，不得补充原文没有的内容。不要输出 JSON 以外的任何内容。

分类表：
B 哲学·宗教：B80思维科学 B81逻辑学 B82伦理·价值观 B83美学 B84心理学
C 社会科学：C91社会学 C93管理·领导 C96职业·人才
D 政治·法律：D6政治 D9法律
F 经济：F0经济学原理 F27企业·创业 F83金融·投资
G 文化·教育·体育：G2传媒·传播 G4教育·学习方法 G61幼儿教育 G63中小学教育 G78家庭教育 G79自学·自我提升 G8体育·运动
H 语言·文字：H1汉语·写作 H3外语学习
I 文学：I1外国文学 I2中国文学
J 艺术：J2绘画·书法 J6音乐 J9影视
K 历史·地理：K1世界史 K2中国史 K81人物传记 K9地理·旅行
N 自然科学：N49科普
Q 生物：Q生物·进化
R 医药·卫生：R15营养·饮食 R16保健·运动 R2中医 R4疾病·医疗
S 农业：S种植·宠物
T 工业技术：TP18人工智能 TP3计算机·软件 TN91通信·数码 TS97美食·烹饪 TU建筑·家装
U 交通：U46汽车
X 环境·安全：X环境·安全
Z 综合：Z综合

转写全文："""

#: 网页剪藏摘要提示词：与 _SUMMARIZE_V4_PROMPT 逐字同源（replace 派生），
#: 只换主语（视频转写 → 网页文章）。刻意不另抄一份——中图法分类表与
#: 各节产出标准全库只有这一份（2026-09-10 用户裁决：统一国家图书分类
#: 标准），改 V4 即同步改剪藏。供 dispatch/clips.py 复用同一
#: _summarize 管道。
_SUMMARIZE_CLIP_PROMPT = _SUMMARIZE_V4_PROMPT.replace(
    "请阅读以下视频转写全文", "请阅读以下网页文章全文"
).replace("转写全文：", "文章全文：")

#: 视频处理器输出里的逐句时间戳行（"- [00:00] 文本"）
_SEGMENT_LINE_RE = re.compile(r"^- \[\d{2}:\d{2}\]\s*", re.M)

#: 句末标点（分段优先落在句界上）
_SENTENCE_END_RE = re.compile(r"(?<=[。！？!?…])")

#: yt-dlp 对无标题抖音作品返回的通用占位标题（2026-09-12 真实样本：
#: 「Douyin video #7674839354331095781」）——这类标题没有语义，
#: 文件名检索/快速切换/回顾全部失效
_MACHINE_TITLE_RE = re.compile(r"\s*douyin\s+video\s*#?\s*\d+\s*", re.I)

#: 断句（折叠连续重复句用）：句末标点后或换行处
_SENTENCE_SPLIT_RE = re.compile(r"(?<=[。！？!?…])\s*|\n+")

#: 句子归一化（重复判定用）：剥掉全部空白与标点
_SENTENCE_NORM_RE = re.compile(r"[\s，。：:；;、！!？?《》<>\"'“”‘’—…·~]+")


def _is_machine_title(title: str) -> bool:
    """平台通用占位标题判定（整串匹配，不误伤真实标题）。"""
    return bool(_MACHINE_TITLE_RE.fullmatch(str(title or "")))


#: 标题里的 #话题 片段（抖音分享文本尾巴常见：「…哲学之路 #人文星闪耀计划
#: #用知识解构社会现实」，2026-09-13 真实样本）
_TITLE_HASHTAG_RE = re.compile(r"\s*#[^#\s]+")

#: 标题硬上限（提示词契约 10-20 字的程序兜底：LLM/平台不守规矩时代码截断）
_TITLE_MAX_LEN = 30


def _sanitize_title(title: str) -> str:
    """标题清洗与限长（2026-09-13 实证：分享文本标题揉入话题尾，
    「遇事的第一反应…哲学之路 人文星闪耀计划 用知识解构社会现实」40 字）。

    - 剥掉 #话题 片段；
    - 含空白的标题按空白切段，首段 ≥8 字时丢弃后续各段（中文真实标题
      极少含空白，空格尾段几乎总是话题/栏目尾巴）；
    - 硬上限 30 字，截断后剥掉尾部标点。

    Args:
        title: 原始标题。

    Returns:
        str: 清洗后的标题（可能为空串）。
    """
    text = _TITLE_HASHTAG_RE.sub("", str(title or "")).strip()
    parts = [seg for seg in re.split(r"\s+", text) if seg]
    if len(parts) > 1 and len(parts[0]) >= 8:
        text = parts[0]
    if len(text) > _TITLE_MAX_LEN:
        text = text[:_TITLE_MAX_LEN]
    return text.rstrip("，。、：:；;,.… ")


def _collapse_consecutive_repeats(text: str) -> str:
    """折叠 Whisper 连续重复句（2026-09-12 真实样本：「所以它更多的就是
    一种资源配置上出了差异」连重复 3 次、「冲突就是一种冲突」4 次——
    不确定音频段的识别假象，不是讲者强调）。

    只折叠归一化后完全相同的**相邻**句，保留第一遍：内容不丢，可读性
    恢复；非相邻的重复（讲者真正的反复）原样保留。无折叠发生时返回
    原文（逐字节不变）。

    Args:
        text: 简体转写全文。

    Returns:
        str: 折叠后的文本。
    """
    sentences = [s for s in _SENTENCE_SPLIT_RE.split(text) if s.strip()]
    if not sentences:
        return text
    kept: List[str] = []
    prev_norm = ""
    for sentence in sentences:
        norm = _SENTENCE_NORM_RE.sub("", sentence)
        if norm and norm == prev_norm:
            continue
        kept.append(sentence.strip())
        prev_norm = norm
    if len(kept) == len(sentences):
        return text
    return " ".join(kept)


def _semantic_title(title: str, summary: Optional[Dict[str, Any]]) -> str:
    """标题兜底（2026-09-12 用户裁决：笔记标题 =「平台-主题」）：平台
    标题为空或是通用占位标题（_is_machine_title）时，换用 LLM 产出的
    语义标题；LLM 也没有则原样返回（下游仍可按 id 兜底命名）。
    两条来源的标题都先过 _sanitize_title（剥话题尾 + 限长）。

    Args:
        title: 平台/分享文本给出的标题（可为空串）。
        summary: _summarize 的产出（可为 None）。

    Returns:
        str: 最终采用的标题。
    """
    raw = str(title or "").strip()
    if raw and not _is_machine_title(raw):
        return _sanitize_title(raw)
    if summary:
        llm_title = _sanitize_title(str(summary.get("title") or ""))
        if llm_title:
            return llm_title
    return raw

#: 繁体 → 简体转换器（模块级单例）
_T2S = opencc.OpenCC("t2s")


def _hard_wrap(text: str, width: int) -> List[str]:
    """无标点长文本按字数硬切段的兜底。

    Args:
        text: 待切文本。
        width: 每段字数。

    Returns:
        List[str]: 分段列表。
    """
    return [text[i : i + width] for i in range(0, len(text), width)] or [""]


def _transcript_to_paragraphs(transcript_markdown: str, width: int = 160) -> str:
    """把视频处理器的逐句时间戳转写合并为自然段（简体）。

    只取 ``- [mm:ss] 文本`` 行（丢弃标题/小节头等其余内容），剥掉
    时间戳后按句界分段：累积到 width 字且当前句以句末标点收尾即
    另起一段；整段无标点（Whisper 不带标点提示时的旧产物）兜底
    按字数硬切。Whisper 标点由 video 处理器的 initial_prompt 引导。

    Args:
        transcript_markdown: 视频处理器的 markdown（含时间戳行）。
        width: 每段的目标字数（句界分段时允许略超）。

    Returns:
        str: 简体、无时间戳、空行分段的转写全文；无有效行时为空串。
    """
    lines = [
        line for line in transcript_markdown.splitlines() if _SEGMENT_LINE_RE.match(line)
    ]
    texts = [_T2S.convert(_SEGMENT_LINE_RE.sub("", line).strip()) for line in lines]
    full = "".join(texts)
    if not full:
        return ""
    sentences = [s for s in _SENTENCE_END_RE.split(full) if s]
    paragraphs: List[str] = []
    buf = ""
    for sentence in sentences:
        buf += sentence
        if len(buf) >= width and sentence[-1] in "。！？!?…":
            paragraphs.append(buf)
            buf = ""
    if buf:
        paragraphs.append(buf)
    wrapped: List[str] = []
    for paragraph in paragraphs:
        if len(paragraph) > width * 2:
            wrapped.extend(_hard_wrap(paragraph, width))
        else:
            wrapped.append(paragraph)
    return "\n\n".join(wrapped)


def _extract_url(text: str) -> Optional[str]:
    """从分享文本中提取第一个 http(s) URL。

    Args:
        text: 分享文本或纯 URL。

    Returns:
        Optional[str]: 清理过首尾标点的 URL；找不到返回 None。
    """
    match = URL_RE.search(text)
    if not match:
        return None
    return match.group(0).strip(URL_TRAILING)


def detect_platform(url: str) -> Optional[str]:
    """按域名识别平台。

    Args:
        url: 完整 URL。

    Returns:
        Optional[str]: "douyin" / "xhs" / "bilibili" 或 None（不支持的平台）。
    """
    for host in _DOUYIN_HOSTS:
        if host in url:
            return "douyin"
    for host in _XHS_HOSTS:
        if host in url:
            return "xhs"
    for host in _BILIBILI_HOSTS:
        if host in url:
            return "bilibili"
    return None


def probe_video_id(url: str, timeout: float = 20.0) -> Optional[str]:
    """尽力解析链接指向的平台内容 id（只取元数据，不下载），供同内容幂等。

    同一视频的不同分享短链（b23.tv 按次生成）字符串不同，仅靠 URL 去重
    拦不住（2026-09-15 实证：同一 BV 视频两个短链被处理两遍，重复下载
    39MB + 重复转写）。任何解析失败返回 None——调用方按"查无此证"
    继续正常处理，不阻塞管线。

    Args:
        url: 视频链接（短链亦可，yt-dlp 跟随跳转）。
        timeout: 网络超时秒数。

    Returns:
        Optional[str]: 平台内容 id（如 BV 号）；失败为 None。
    """
    options: Dict[str, Any] = {
        "quiet": True,
        "no_warnings": True,
        "socket_timeout": timeout,
        "skip_download": True,
        # B站多分 P 只认当前这一集（与下载同规）
        "noplaylist": True,
    }
    try:
        with yt_dlp.YoutubeDL(options) as ydl:
            info = ydl.extract_info(url, download=False)
    except Exception:  # noqa: BLE001 - 尽力而为，失败不阻塞
        return None
    if not isinstance(info, dict):
        return None
    entries = info.get("entries")
    if isinstance(entries, list):  # 保险：播放列表形态取第一集
        info = next((e for e in entries if isinstance(e, dict)), {})
    vid = str(info.get("id") or "").strip()
    return vid or None


def _llm_skip_note(status: str, chars: int, limit: int) -> Optional[str]:
    """LLM 总结未产出时的卡面说明（2026-09-15 裁决：不许静默降级）。

    只标注 too-long / failed 两类；no-key 是配置态、空转写无内容可
    总结，不噪音。

    Args:
        status: _summarize 的状态串（ok / skipped:* / failed:*）。
        chars: 转写全文字符数。
        limit: 总结护栏（max_transcript_chars）。

    Returns:
        Optional[str]: 卡面警示语；无需标注时返回 None。
    """
    if status == "skipped:too-long":
        return (
            f"⚠️ 转写 {chars} 字超出自动总结上限（{limit} 字），"
            "本卡无观点总结与分类标签；需要时可调高 "
            "processors.link.llm.max_transcript_chars。"
        )
    if status.startswith("failed:"):
        return f"⚠️ 自动总结失败（{status}），本卡无观点总结与分类标签。"
    return None


def _parse_share_text(text: str) -> Tuple[str, str]:
    """从抖音分享文本解析 (标题, 作者)；解析失败返回空串。

    结构样例：``1.58 复制打开抖音，看看【武世红的作品】德国著名哲学家…
    https://v.douyin.com/xxx/ ...``——标题取 】 与 URL 之间的文本，
    去掉被截断的尾缀 "..."/"…"。

    Args:
        text: 分享文本。

    Returns:
        Tuple[str, str]: (标题, 作者)，各自可能为空串。
    """
    author = ""
    title = ""
    author_match = _AUTHOR_RE.search(text)
    if author_match:
        author = author_match.group("author").strip()
        rest = text[author_match.end():]
    else:
        rest = text
    url_match = URL_RE.search(rest)
    if url_match:
        title = rest[: url_match.start()]
    title = title.strip().rstrip(".… ").strip()
    return title, author


def _tag_clean(text: str) -> str:
    """Obsidian 标签清洗：去首尾空白，内部空白替换为 ``-``。

    Obsidian 标签不能含空格；LLM 可能给出带空白的类目/主题词
    （如 ``B 哲学·宗教`` → ``B-哲学·宗教``）。

    Args:
        text: 原始文本。

    Returns:
        str: 清洗后的标签；空串表示无有效内容。
    """
    cleaned = text.strip()
    if re.search(r"\s", cleaned):
        cleaned = re.sub(r"\s+", "-", cleaned)
    return cleaned


#: 金句回溯机检的相似度阈值（去空白与标点后最长公共子串占比）
_QUOTE_MATCH_MIN = 0.85

#: 转写置信度低于该值时在卡片加警告行（avg_logprob 指数均值；
#: 实测正常转写普遍 >0.75）
_LOW_CONFIDENCE = 0.70


def _verify_insights(
    insights: List[str], transcript: str
) -> Tuple[List[str], int]:
    """金句回溯机检（2026-09-14 KM 评审裁决：把"逐字照抄"从 prompt
    请求升级为机器强制校验）。

    每条金句规范化（去掉一切空白与标点，只留文字）后，必须在转写
    原文里找到覆盖率 ≥ 阈值的连续匹配；找不到的剔除（它是 LLM 的
    转述或编造，不是摘录）并计数，供卡片正文如实标注。

    Args:
        insights: LLM 交出的金句列表。
        transcript: 转写原文（或剪藏文章全文）。

    Returns:
        Tuple[List[str], int]:（通过校验的金句，被剔除条数）。
    """
    import difflib

    def _norm(text: str) -> str:
        return re.sub(r"[^\w]", "", text, flags=re.UNICODE)

    corpus = _norm(transcript)
    if not corpus:
        return list(insights), 0
    kept: List[str] = []
    dropped = 0
    for quote in insights:
        needle = _norm(quote)
        if not needle:
            dropped += 1
            continue
        match = difflib.SequenceMatcher(None, needle, corpus).find_longest_match(
            0, len(needle), 0, len(corpus)
        )
        if match.size / len(needle) >= _QUOTE_MATCH_MIN:
            kept.append(quote)
        else:
            dropped += 1
    return kept, dropped


class LinkProcessor(BaseProcessor):
    """链接抓取处理器（支持抖音/小红书的分享文本或链接）。

    Examples:
        >>> result = LinkProcessor().process("看看【张三的作品】... https://v.douyin.com/abc/")
        >>> result.success
        True
    """

    name = "link"
    #: 输入不是文件，扩展名集合为空（不调用 _check_input）
    supported_extensions: Tuple[str, ...] = ()

    def __init__(self, config: Optional[dict] = None) -> None:
        """初始化。

        Args:
            config: processors.link 配置节（model / cookies_browser /
            chrome_profile_dir / chrome_binary）；缺省按配置文件加载。
        """
        super().__init__(config)
        self.model = str(self.config.get("model", "large-v3"))
        self.cookies_browser = str(self.config.get("cookies_browser", "chrome"))
        self.chrome_profile_dir = str(
            self.config.get(
                "chrome_profile_dir", "~/.cache/atelierr/douyin-chrome-profile"
            )
        )
        self.chrome_binary = str(self.config.get("chrome_binary", ""))
        llm_cfg = self.config.get("llm") or {}
        self.llm_base_url = str(llm_cfg.get("base_url", _LLM_DEFAULT_BASE_URL))
        self.llm_model = str(llm_cfg.get("model", _LLM_DEFAULT_MODEL))
        self.llm_api_key_env = str(llm_cfg.get("api_key_env", "DEEPSEEK_API_KEY"))
        self.llm_max_tokens = int(llm_cfg.get("max_tokens", 2500))
        self.llm_timeout = float(llm_cfg.get("timeout", 60))
        # 总结护栏默认 20000 字（约 2 小时视频；2026-09-15 由 6000 上调——
        # B站长视频是常态，6000 会把 B站通道的总结全部静默关掉；DeepSeek
        # 总结一次约一分钱，成本可忽略）
        self.llm_max_chars = int(llm_cfg.get("max_transcript_chars", 20000))
        # 转写整理单独护栏：整理输出受模型 max_tokens 限制，长文会截断，
        # 超出降级为 Whisper 原稿（已有分段标点，可读），不影响总结
        self.llm_format_max_chars = int(llm_cfg.get("format_max_chars", 6000))
        self.llm_format_max_tokens = int(llm_cfg.get("format_max_tokens", 8000))

    def process(self, input_path: Union[str, Path]) -> ProcessResult:
        """抓取链接指向的视频并转写。

        Args:
            input_path: 分享文本或 URL（形参名沿用基类约定）。

        Returns:
            ProcessResult: 含带来源行的 markdown；预期内错误
            （无链接/平台不支持/下载失败/转写失败）返回 success=False。
        """
        text = str(input_path).strip()
        url = _extract_url(text)
        if url is None:
            return self._fail("未找到链接：请粘贴分享文本或 URL")
        platform = detect_platform(url)
        if platform not in ("douyin", "xhs", "bilibili"):
            return self._fail(f"暂不支持的平台（已支持: 抖音、小红书、B站）: {url}")

        share_title, share_author = _parse_share_text(text)
        download_dir = tempfile.mkdtemp(prefix="atelierr-link-")
        try:
            if platform == "xhs":
                return self._process_xhs(url, download_dir)
            # B站长视频限高下载（防大文件）；抖音按原路径（片源小）
            max_height = _BILIBILI_MAX_HEIGHT if platform == "bilibili" else None
            video_path, info, error = self._download(
                url, download_dir, max_height=max_height
            )
            if error is not None:
                return self._fail(error)
            video_result = VideoProcessor({"model": self.model}).process(video_path)
            if not video_result.success:
                return self._fail(video_result.error or "视频转写失败")
            title = str(info.get("title") or "").strip() or share_title
            author = str(info.get("uploader") or "").strip() or share_author
            source_label = "B站" if platform == "bilibili" else "抖音"
            transcript_text = _collapse_consecutive_repeats(
                _T2S.convert(video_result.text).strip()
            )
            summary, llm_status = self._summarize(transcript_text)
            llm_note = _llm_skip_note(llm_status, len(transcript_text), self.llm_max_chars)
            # 平台占位标题（「Douyin video #id」）换 LLM 语义标题——须在
            # _preserve_video/_transcript_rel 之前（附件主名随标题定）
            title = _semantic_title(title, summary)
            formatted, fmt_status = self._format_transcript(transcript_text)
            doc_id = str(info.get("id") or "")
            video_rel, video_blob = self._preserve_video(
                video_path, source_label, title, doc_id
            )
            body = self._compose_body(
                video_result.markdown, body_override=formatted
            )
            transcript_rel = None
            if len(body) > INLINE_BODY_MAX:
                transcript_rel = self._transcript_rel(source_label, title, doc_id)
            markdown = self._build_markdown(
                title or (video_path.stem if video_path else "link"),
                author,
                url,
                body,
                summary,
                source_label=source_label,
                video_rel=video_rel,
                transcript_rel=transcript_rel,
                transcription_confidence=video_result.confidence,
                llm_note=llm_note,
            )
            metadata = {
                "engine": "yt-dlp+whisper",
                "platform": platform,
                "model": self.model,
                "url": url,
                "video_id": doc_id,
                "title": title,
                "segments": video_result.metadata.get("segments", 0),
                "llm": {"status": llm_status, "format": fmt_status, "model": self.llm_model},
                "video_rel": video_rel,
                "video_blob": video_blob,
                "transcript_rel": transcript_rel,
                "transcript_text": body if transcript_rel else None,
            }
            return ProcessResult(
                success=True,
                text=video_result.text,
                markdown=markdown,
                confidence=video_result.confidence,
                metadata=metadata,
            )
        finally:
            self._cleanup(download_dir)

    def _process_xhs(self, url: str, download_dir: str) -> ProcessResult:
        """处理小红书链接：解析详情页内嵌数据，视频走 Whisper，图文直接入库。

        Args:
            url: 小红书短链或详情页 URL。
            download_dir: 视频下载临时目录（由 process() 负责清理）。

        Returns:
            ProcessResult: 含带来源行的 markdown；页面获取/解析失败、
            视频下载/转写失败、笔记无有效内容时 success=False。
        """
        note, final_url, error = self._fetch_xhs_note(url)
        if error is not None:
            return self._fail(error)
        assert note is not None  # error 为 None 时 note 必存在
        title = str(note.get("title") or "").strip()
        author = str((note.get("user") or {}).get("nickName") or "").strip()
        desc = _T2S.convert(str(note.get("desc") or "").strip())
        note_id = str(note.get("noteId") or "").strip()
        video_url = self._xhs_video_url(note)
        metadata: Dict[str, Any] = {
            "platform": "xhs",
            "url": final_url,
            "note_id": note_id,
            "title": title,
        }
        if not video_url:
            # 图文笔记：正文即内容，无转写；图片是原件必须保藏（2026-09-14
            # 用户裁决：图文的图就是内容本体——书单/截图类图文的知识全在
            # 图里，丢了等于没存），并 OCR 出文字参与摘要（可搜索）。
            if not title and not desc:
                return self._fail("小红书笔记无有效内容（无标题无正文）")
            images, ocr_parts = self._fetch_xhs_images(
                note, download_dir, "小红书", title or note_id, note_id
            )
            ocr_text = "\n\n".join(ocr_parts)
            full_text = desc + (f"\n\n图片里的文字：\n\n{ocr_text}" if ocr_text else "")
            summary, llm_status = self._summarize(full_text)
            llm_note = _llm_skip_note(llm_status, len(full_text), self.llm_max_chars)
            title = _semantic_title(title, summary)  # 空标题用 LLM 语义标题兜底
            metadata["title"] = title
            body = self._compose_body(full_text, raw_body=True)
            transcript_rel = None
            if len(body) > INLINE_BODY_MAX:
                transcript_rel = self._transcript_rel("小红书", title, note_id)
            image_rels = [rel for rel, _blob in images]
            markdown = self._build_markdown(
                title or note_id or "小红书笔记",
                author,
                final_url,
                body,
                summary,
                source_label="小红书",
                body_label="笔记正文",
                transcript_rel=transcript_rel,
                image_rels=image_rels,
                llm_note=llm_note,
            )
            metadata["engine"] = "xhs-page"
            metadata["llm"] = {"status": llm_status, "model": self.llm_model}
            metadata["transcript_rel"] = transcript_rel
            metadata["transcript_text"] = body if transcript_rel else None
            metadata["image_blobs"] = images
            metadata["images"] = len(images)
            return ProcessResult(
                success=True,
                text=desc,
                markdown=markdown,
                confidence=1.0,
                metadata=metadata,
            )
        video_path = Path(download_dir) / f"{note_id or 'xhs'}.mp4"
        dl_error = self._download_xhs_video(video_url, video_path)
        if dl_error is not None:
            return self._fail(dl_error)
        video_result = VideoProcessor({"model": self.model}).process(video_path)
        if not video_result.success:
            return self._fail(video_result.error or "视频转写失败")
        transcript_text = _collapse_consecutive_repeats(
            _T2S.convert(video_result.text).strip()
        )
        summary, llm_status = self._summarize(transcript_text)
        llm_note = _llm_skip_note(llm_status, len(transcript_text), self.llm_max_chars)
        title = _semantic_title(title, summary)  # 空标题用 LLM 语义标题兜底
        metadata["title"] = title
        formatted, fmt_status = self._format_transcript(transcript_text)
        video_rel, video_blob = self._preserve_video(
            video_path, "小红书", title, note_id
        )
        body = self._compose_body(
            video_result.markdown, body_override=formatted
        )
        transcript_rel = None
        if len(body) > INLINE_BODY_MAX:
            transcript_rel = self._transcript_rel("小红书", title, note_id)
        markdown = self._build_markdown(
            title or note_id or "小红书笔记",
            author,
            final_url,
            body,
            summary,
            source_label="小红书",
            video_rel=video_rel,
            transcript_rel=transcript_rel,
            transcription_confidence=video_result.confidence,
            llm_note=llm_note,
        )
        metadata["engine"] = "xhs-page+whisper"
        metadata["model"] = self.model
        metadata["segments"] = video_result.metadata.get("segments", 0)
        metadata["llm"] = {"status": llm_status, "format": fmt_status, "model": self.llm_model}
        metadata["video_rel"] = video_rel
        metadata["video_blob"] = video_blob
        metadata["transcript_rel"] = transcript_rel
        metadata["transcript_text"] = body if transcript_rel else None
        return ProcessResult(
            success=True,
            text=video_result.text,
            markdown=markdown,
            confidence=video_result.confidence,
            metadata=metadata,
        )

    @staticmethod
    def _fetch_xhs_note(
        url: str,
    ) -> Tuple[Optional[Dict[str, Any]], str, Optional[str]]:
        """抓取小红书详情页并解析内嵌笔记数据。

        短链经 302 跳到详情页（httpx 自动跟随）；数据在页面内嵌的
        ``window.__INITIAL_STATE__`` JSON 里（``undefined`` 字面量替换为
        null 后可解析），笔记本体在 ``noteData.data.noteData``。

        Args:
            url: 小红书短链或详情页 URL。

        Returns:
            Tuple[Optional[Dict[str, Any]], str, Optional[str]]:
            (note 字典, 最终 URL, 错误信息)；成功时 error 为 None。
        """
        try:
            response = httpx.get(
                url,
                headers={"User-Agent": _XHS_UA},
                timeout=30,
                follow_redirects=True,
            )
            response.raise_for_status()
        except Exception as exc:  # noqa: BLE001 - 网络/状态码错误统一降级
            return None, url, f"小红书页面获取失败: {exc}"
        final_url = str(response.url)
        match = _XHS_STATE_RE.search(response.text)
        if not match:
            return None, final_url, "小红书页面解析失败: 未找到 __INITIAL_STATE__"
        try:
            data = json.loads(match.group(1).replace(":undefined", ":null"))
            note = data["noteData"]["data"]["noteData"]
        except (json.JSONDecodeError, KeyError, TypeError):
            return None, final_url, "小红书页面解析失败: 数据结构不符"
        if not isinstance(note, dict):
            return None, final_url, "小红书页面解析失败: 数据结构不符"
        return note, final_url, None

    @staticmethod
    def _xhs_video_url(note: Dict[str, Any]) -> Optional[str]:
        """从笔记数据里取视频流地址（h264 优先，其余编码兜底）。"""
        streams = ((note.get("video") or {}).get("media") or {}).get("stream") or {}
        for codec in ("h264", "h265", "av1", "h266"):
            for item in streams.get(codec) or []:
                master = str((item or {}).get("masterUrl") or "")
                if master:
                    return master
        return None

    @staticmethod
    def _xhs_image_urls(note: Dict[str, Any]) -> List[str]:
        """图文笔记的图片地址列表（imageList 各项 urlDefault/url 优先，
        infoList 兜底）；去重、保序、封顶 9 张。"""
        urls: List[str] = []
        for item in note.get("imageList") or []:
            if not isinstance(item, dict):
                continue
            url = str(item.get("urlDefault") or item.get("url") or "")
            if not url:
                infos = item.get("infoList") or []
                if infos and isinstance(infos[0], dict):
                    url = str(infos[0].get("url") or "")
            if url and url not in urls:
                urls.append(url)
        return urls[:9]

    @staticmethod
    def _download_xhs_file(file_url: str) -> Optional[bytes]:
        """下载小红书 CDN 文件（图片等）返回字节；cdn 校验 Referer。

        失败返回 None（调用方跳过该件，不阻塞整篇图文）。
        """
        try:
            response = httpx.get(
                file_url,
                headers={"User-Agent": _XHS_UA, "Referer": "https://www.xiaohongshu.com/"},
                timeout=60,
                follow_redirects=True,
            )
            response.raise_for_status()
            return response.content
        except Exception:  # noqa: BLE001 - 单件失败不阻塞
            return None

    def _fetch_xhs_images(
        self,
        note: Dict[str, Any],
        download_dir: str,
        source_label: str,
        title: str,
        doc_id: str,
    ) -> Tuple[List[Tuple[str, bytes]], List[str]]:
        """图文笔记：下载全部图片 + 逐张 OCR（2026-09-14 裁决：图是原件
        必须保藏；图里的文字是知识本体，OCR 才可搜可摘要）。

        单张下载/OCR 失败只跳过该张（记 warning），不阻塞整篇；OCR 引擎
        本方法内懒构造一次（模型加载昂贵）。字节交 dispatch 层落盘
        （分层纪律：处理器不感知存储位置）。

        Returns:
            Tuple[List[Tuple[str, bytes]], List[str]]:（[(rel, blob)]，
            [逐图 OCR 文本（带【图 N】标记）]）。
        """
        images: List[Tuple[str, bytes]] = []
        ocr_parts: List[str] = []
        ocr_engine: Any = None
        stem = self._artifact_stem(source_label, title, doc_id)
        for index, image_url in enumerate(self._xhs_image_urls(note), 1):
            blob = self._download_xhs_file(image_url)
            if blob is None:
                continue
            rel = f"attachments/{source_label}/{stem}/{index:02d}.jpg"
            images.append((rel, blob))
            tmp = Path(download_dir) / f"xhs-img-{doc_id}-{index:02d}.jpg"
            try:
                tmp.write_bytes(blob)
                if ocr_engine is None:
                    ocr_engine = ImageProcessor()
                ocr_result = ocr_engine.process(tmp)
                if ocr_result.success and ocr_result.text.strip():
                    ocr_parts.append(f"【图 {index}】\n{ocr_result.text.strip()}")
            except Exception as exc:  # noqa: BLE001 - 单图 OCR 失败不阻塞
                logger.warning("小红书图片 OCR 失败 %s: %s", rel, exc)
        return images, ocr_parts

    @staticmethod
    def _download_xhs_video(video_url: str, dest: Path) -> Optional[str]:
        """下载小红书视频流到本地（cdn 校验 Referer，须带详情页域）。

        Args:
            video_url: 视频流地址（masterUrl）。
            dest: 目标文件路径。

        Returns:
            Optional[str]: 错误信息；成功为 None。
        """
        try:
            with httpx.stream(
                "GET",
                video_url,
                headers={"User-Agent": _XHS_UA, "Referer": "https://www.xiaohongshu.com/"},
                timeout=120,
                follow_redirects=True,
            ) as response:
                response.raise_for_status()
                with open(dest, "wb") as fh:
                    for chunk in response.iter_bytes(256 * 1024):
                        fh.write(chunk)
        except Exception as exc:  # noqa: BLE001 - 下载异常转为错误信息
            return f"视频下载失败: {exc}"
        return None

    def _download(
        self, url: str, download_dir: str, max_height: Optional[int] = None
    ) -> Tuple[Optional[Path], Dict[str, Any], Optional[str]]:
        """用 yt-dlp 下载视频到临时目录，cookie 失效时自动刷新重试一次。

        两段式：先用日常浏览器默认 profile 的 cookie；若报 cookie 类错误，
        用无头 Chrome 访问目标页刷新专用 profile 的反爬 cookie
        （``__ac_signature`` 等 JS 挑战产物），再携该 profile 重试。

        Args:
            url: 视频 URL。
            download_dir: 临时目录路径。
            max_height: 限高下载（如 B站长视频传 480 防大文件；None 不限制）。

        Returns:
            Tuple[Optional[Path], Dict[str, Any], Optional[str]]:
            (视频路径, yt-dlp info 字典, 错误信息)；成功时 error 为 None。
        """
        cookies: Optional[Tuple[str, ...]] = (
            (self.cookies_browser,) if self.cookies_browser else None
        )
        video_path, info, error = self._download_attempt(
            url, download_dir, cookies, max_height=max_height
        )
        if error and "cookie" in error.lower() and self._refresh_cookies(url):
            profile = str(self._profile_dir() / "Default")
            cookies = (self.cookies_browser or "chrome", profile)
            video_path, info, error = self._download_attempt(
                url, download_dir, cookies, max_height=max_height
            )
        if error:
            return None, {}, error
        return video_path, info, None

    def _download_attempt(
        self,
        url: str,
        download_dir: str,
        cookies: Optional[Tuple[str, ...]],
        max_height: Optional[int] = None,
    ) -> Tuple[Optional[Path], Dict[str, Any], Optional[str]]:
        """单次下载尝试。

        Args:
            url: 视频 URL。
            download_dir: 临时目录路径。
            cookies: yt-dlp cookiesfrombrowser 元组（None 表示不带）。
            max_height: 限高（format 选择 best[height<=N]，片源无高度
                元数据时回退 best）。

        Returns:
            Tuple[Optional[Path], Dict[str, Any], Optional[str]]:
            (视频路径, info 字典, 错误信息)；成功时 error 为 None。
        """
        options: Dict[str, Any] = {
            "outtmpl": str(Path(download_dir) / "%(id)s.%(ext)s"),
            "quiet": True,
            "no_warnings": True,
            "socket_timeout": 30,
            # B站多分 P 视频只取当前这一集（不整季打包）
            "noplaylist": True,
        }
        if max_height:
            # B站音视频 DASH 分离（无合并的 best 单文件），须 video+audio
            # 组合选择；片源无高度元数据时回退不限高组合（2026-09-10 实测）
            options["format"] = (
                f"bestvideo[height<={max_height}]+bestaudio"
                "/bestvideo+bestaudio/best"
            )
        if cookies:
            options["cookiesfrombrowser"] = cookies
        try:
            with yt_dlp.YoutubeDL(options) as ydl:
                info = ydl.extract_info(url, download=True)
        except yt_dlp.utils.DownloadError as exc:
            detail = str(exc).splitlines()[0][:200] if str(exc) else "未知错误"
            hint = ""
            if "cookie" in str(exc).lower():
                hint = f"（cookie 失效且自动刷新未成功？在 {self.cookies_browser} 打开一次 douyin.com 后重试）"
            return None, {}, f"视频下载失败: {detail}{hint}"
        except Exception as exc:  # noqa: BLE001 - 下载异常转为失败结果
            return None, {}, f"视频下载失败: {exc}"
        video_path = self._find_video(download_dir)
        if video_path is None:
            return None, {}, "视频下载失败: 未找到下载产物"
        return video_path, dict(info or {}), None

    @staticmethod
    def _find_video(download_dir: str) -> Optional[Path]:
        """在临时目录中定位下载出的视频文件。"""
        for path in sorted(Path(download_dir).iterdir()):
            if path.suffix.lower() in _VIDEO_EXTS and path.is_file():
                return path
        return None

    def _profile_dir(self) -> Path:
        """专用 Chrome profile 目录（展开 ~）。"""
        return Path(self.chrome_profile_dir).expanduser()

    def _refresh_cookies(self, url: str) -> bool:
        """无头 Chrome 访问目标页，把反爬 cookie 刷进专用 profile。

        真实浏览器内核可执行抖音的 JS 挑战（__ac_signature 等），
        curl 等纯 HTTP 客户端拿不到合格 cookie（2026-09-01 实测）。

        Args:
            url: 要访问的目标页（视频页）。

        Returns:
            bool: 刷新成功（浏览器正常退出）返回 True。
        """
        binary = (
            self.chrome_binary
            or shutil.which("google-chrome")
            or shutil.which("chromium")
        )
        if not binary:
            return False
        profile = self._profile_dir()
        profile.mkdir(parents=True, exist_ok=True)
        command = [
            binary,
            "--headless=new",
            f"--user-data-dir={profile}",
            "--disable-gpu",
            "--no-first-run",
            "--virtual-time-budget=30000",
            "--dump-dom",
            url,
        ]
        try:
            proc = subprocess.run(
                command, capture_output=True, timeout=180, check=False
            )
        except Exception:  # noqa: BLE001 - 刷新失败按未刷新处理
            return False
        return proc.returncode == 0

    def _llm_chat(
        self, prompt: str, max_tokens: int, json_mode: bool = False
    ) -> str:
        """调 LLM chat 接口返回 content 文本；任何失败抛异常（调用方降级）。

        Args:
            prompt: 用户提示词。
            max_tokens: 输出上限。
            json_mode: True 时要求 JSON 对象输出（response_format）。

        Returns:
            str: 模型输出的 content 原文。
        """
        api_key = os.environ.get(self.llm_api_key_env, "").strip()
        payload: Dict[str, Any] = {
            "model": self.llm_model,
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": max_tokens,
            "temperature": 0.3,
            # 摘要/整理是机械任务，禁用思考链：deepseek-v4-flash 默认开
            # 推理，长输出任务会把 max_tokens 全耗在 reasoning 上导致
            # content 为空（2026-09-02 实测 finish_reason=length）
            "thinking": {"type": "disabled"},
        }
        if json_mode:
            payload["response_format"] = {"type": "json_object"}
        response = httpx.post(
            f"{self.llm_base_url.rstrip('/')}/chat/completions",
            headers={"Authorization": f"Bearer {api_key}"},
            json=payload,
            timeout=self.llm_timeout,
        )
        response.raise_for_status()
        return response.json()["choices"][0]["message"]["content"]

    def summarize_transcript(
        self, transcript: str
    ) -> Tuple[Optional[Dict[str, Any]], str]:
        """公开的转写总结入口：复用 _summarize 的护栏与提示词契约。

        供 dispatch/media 等其他管线复用（2026-09-15 裁决：直发视频/录音
        与链接视频同待遇——观点总结/分观点/中图法标签，同一道
        max_transcript_chars 护栏）。

        Args:
            transcript: 简体转写全文。

        Returns:
            Tuple[Optional[Dict[str, Any]], str]: (七键字典或 None, 状态串）。
        """
        return self._summarize(transcript)

    def format_transcript(self, transcript: str) -> Tuple[Optional[str], str]:
        """公开的转写整理入口：复用 _format_transcript 的护栏与提示词契约。

        供 dispatch/media 等其他管线复用（2026-09-17 裁决：直发视频/录音
        的正文与链接视频同待遇——此前只过了总结没过整理，正文是 Whisper
        原稿，无标点分段，与链接卡的阅读体验割裂）。

        Args:
            transcript: 简体转写全文。

        Returns:
            Tuple[Optional[str], str]: (整理后正文 或 None, 状态串)。
        """
        return self._format_transcript(transcript)

    def _summarize(
        self, transcript: str, prompt: Optional[str] = None
    ) -> Tuple[Optional[Dict[str, Any]], str]:
        """调 LLM 生成结构化笔记元数据；任何失败/跳过返回 (None, 状态)。

        跳过条件（不算错误）：API key 环境变量未设置、转写为空、
        转写超过 max_transcript_chars（成本护栏，长视频留给人工）。

        LLM 输出 v4 JSON（summary / points / insights / entities /
        category / topics / title），旧格式（只有 summary / points）
        向后兼容，缺失字段按空处理。points/insights/entities/topics
        上限 8/5/10/6 条（提示词契约 5-8/3-5 条的程序兜底，2026-09-13
        实证 LLM 会超：分观点给过 9 条）；category/topics 清洗为
        Obsidian 标签（内部空白替换为 ``-``），category 为空则不产出
        分类标签；title 过 _sanitize_title（剥话题尾+限 30 字），供
        平台占位标题兜底（_semantic_title）。

        Args:
            transcript: 简体转写全文（网页剪藏复用时为文章全文）。
            prompt: 自定义提示词（缺省 _SUMMARIZE_V4_PROMPT；网页剪藏
                传 _SUMMARIZE_CLIP_PROMPT，见 dispatch/clips.py）。

        Returns:
            Tuple[Optional[Dict[str, Any]], str]: (七键字典或 None,
            状态串 ok / skipped:* / failed:*）。
        """
        if not os.environ.get(self.llm_api_key_env, "").strip():
            return None, f"skipped:no-{self.llm_api_key_env}"
        if not transcript:
            return None, "skipped:empty-transcript"
        if len(transcript) > self.llm_max_chars:
            return None, "skipped:too-long"
        prompt = (prompt or _SUMMARIZE_V4_PROMPT) + "\n" + transcript
        try:
            content = self._llm_chat(prompt, self.llm_max_tokens, json_mode=True)
            data = json.loads(content)
            summary_text = str(data.get("summary") or "").strip()
            points = [
                str(item).strip()
                for item in (data.get("points") or [])
                if str(item).strip()
            ][:8]
            insights = [
                str(item).strip()
                for item in (data.get("insights") or [])
                if str(item).strip()
            ][:5]
            # 金句回溯机检：必须在原文里找得到（2026-09-14 KM 评审裁决）
            insights, insights_dropped = _verify_insights(insights, transcript)
            entities = [
                str(item).strip()
                for item in (data.get("entities") or [])
                if str(item).strip()
            ][:10]
            topics = [
                _tag_clean(str(item).strip())
                for item in (data.get("topics") or [])
                if str(item).strip()
            ][:6]
            category = _tag_clean(str(data.get("category") or ""))
            if category and not re.search(r"[一-鿿]", category):
                # 裸编号（如 G79）无类名：归档推导不认，丢弃视同未分类
                #（2026-09-14 实证：LLM 会截断表内条目；prompt 已加禁令，
                # 此处程序兜底）
                category = ""
            elif category:
                # 表内条目无短横（R15营养·饮食）：归档推导（CCLASS_RE
                # ^[A-Z]{1,3}\d*-）要求字母数字后带短横——统一补上
                #（2026-09-14 第三次形状变种，规范化收敛到一处）
                category = re.sub(r"^([A-Z]{1,3}\d+)(?![-\d])", r"\1-", category)
            llm_title = _sanitize_title(str(data.get("title") or ""))
            if not summary_text:
                return None, "failed:empty-summary"
            return {
                "summary": summary_text,
                "points": points,
                "insights": insights,
                "insights_dropped": insights_dropped,
                "entities": entities,
                "category": category,
                "topics": topics,
                "title": llm_title,
            }, "ok"
        except Exception as exc:  # noqa: BLE001 - LLM 失败降级，不阻塞管线
            return None, f"failed:{type(exc).__name__}"

    def _format_transcript(self, transcript: str) -> Tuple[Optional[str], str]:
        """调 LLM 把口语转写整理为分段书面文本；失败/跳过返回 (None, 状态)。

        跳过条件：API key 环境变量未设置、转写为空、转写超过
        format_max_chars（整理输出受 max_tokens 限制，长文会截断；
        与总结的护栏分开，2026-09-15 拆分）。整理指令要求逐字保留内容、只分段补
        标点；返回为空或不足原文一半（疑似被改写成摘要）视为失败，降级
        为机械分段，绝不阻塞管线。

        Args:
            transcript: 简体转写全文。

        Returns:
            Tuple[Optional[str], str]: (整理后正文 或 None, 状态串）。
        """
        if not os.environ.get(self.llm_api_key_env, "").strip():
            return None, f"skipped:no-{self.llm_api_key_env}"
        if not transcript:
            return None, "skipped:empty-transcript"
        if len(transcript) > self.llm_format_max_chars:
            return None, "skipped:too-long"
        prompt = (
            "以下是一段语音转写的原始文字（无标点、无分段）。"
            "请整理为易读的书面文本："
            "1) 按语义自然分段，每段聚焦一个意思，段间空行；"
            "2) 补全规范标点（含书名号《》）；"
            "3) 逐字保留原内容，不增删、不改写、不总结；"
            "4) 只输出整理后的正文，不要任何解释。\n\n原始文字：\n" + transcript
        )
        try:
            text = self._llm_chat(prompt, self.llm_format_max_tokens).strip()
        except Exception as exc:  # noqa: BLE001 - LLM 失败降级，不阻塞管线
            return None, f"failed:{type(exc).__name__}"
        if not text:
            return None, "failed:empty-format"
        if len(text) < len(transcript) // 2:
            return None, "failed:suspiciously-short"
        return text, "ok"

    @staticmethod
    def _compose_body(
        transcript_markdown: str,
        *,
        raw_body: bool = False,
        body_override: Optional[str] = None,
    ) -> str:
        """组装正文全文：LLM 整理稿优先，否则原文转换/机械分段。

        Args:
            transcript_markdown: 视频处理器的输出（逐句时间戳格式）；
                raw_body=True 时为纯文本正文（小红书图文 desc）。
            raw_body: True 时按原文使用（仅繁简转换），不做时间戳剥离。
            body_override: LLM 整理后的正文（分段+补标点）；提供时优先。

        Returns:
            str: 正文全文；无有效内容为空串。
        """
        if body_override and body_override.strip():
            return body_override.strip()
        if raw_body:
            return _T2S.convert(transcript_markdown.strip())
        return _transcript_to_paragraphs(transcript_markdown)

    @staticmethod
    def _build_markdown(
        title: str,
        author: str,
        url: str,
        body: str,
        summary: Optional[Dict[str, Any]] = None,
        *,
        source_label: str = "抖音",
        body_label: str = "转写全文",
        video_rel: Optional[str] = None,
        transcript_rel: Optional[str] = None,
        transcription_confidence: float = 0.0,
        image_rels: Optional[List[str]] = None,
        llm_note: Optional[str] = None,
    ) -> str:
        """组装最终卡 Markdown：标题 + 来源行 +（可选）内嵌原视频 + 摘要各节 + 正文。

        LLM 给出中图法分类/主题词时，Markdown 顶部带 ``tags``
        frontmatter（[待确认, 平台标签] + category + topics）；无则
        不带 frontmatter（LLM 失败/跳过时 tags 保持原样）。

        Args:
            title: 笔记标题。
            author: 作者（可为空串）。
            url: 来源链接。
            body: 正文全文（_compose_body 的产物）；空串不产正文部分。
            summary: LLM 摘要 {"summary", "points", "insights",
            "entities", "category", "topics"}；None 时不出现摘要节
            （降级形态）。
            source_label: 来源行平台名（抖音/小红书），也作平台标签。
            body_label: 正文小节标题（转写全文/笔记正文）。
            video_rel: 原视频（480p）的库内相对路径；提供时在来源行
            下方内嵌 ``![[...]]``（Obsidian 内可直接播放）。
            transcript_rel: 全文外置的库内相对路径（2026-09-12 方案 B）；
            提供时正文不进卡，只留 ``## 全文`` 链接节。
            llm_note: 总结被跳过/失败时的卡面说明（_llm_skip_note 的产物，
            2026-09-15 裁决：不许静默降级）；None 不渲染。

        Returns:
            str: 完整 Markdown。
        """
        source = (
            f"> 来源：{source_label} @{author} {url}"
            if author
            else f"> 来源：{source_label} {url}"
        )
        classify_tags: List[str] = []
        if summary:
            category = str(summary.get("category") or "").strip()
            topics = [
                str(topic).strip()
                for topic in (summary.get("topics") or [])
                if str(topic).strip()
            ]
            classify_tags = ([category] if category else []) + topics
        sections: List[str] = []
        if classify_tags:
            # MemoryTree.create_note 复用 content 自带 frontmatter 的
            # tags（不覆盖参数 tags），故须带上"待确认"+平台标签，
            # 使落库笔记仍是 [待确认, 平台] + 分类/主题词。
            tags = [_REVIEW_TAG, source_label] + classify_tags
            sections += [
                "---",
                f"tags: {json.dumps(tags, ensure_ascii=False)}",
                "---",
                "",
            ]
        sections += [f"# {_T2S.convert(title)}", "", source, ""]
        if 0.0 < transcription_confidence < _LOW_CONFIDENCE:
            # 转写低置信警告（2026-09-14 KM 评审裁决）：同音错字靠这层
            # 信号 + 人工回放兜底；无信号（0.0）不噪音
            sections += [
                f"> ⚠️ 转写置信度 {transcription_confidence:.0%} 偏低，"
                "关键处建议回放原视频核对。",
                "",
            ]
        if llm_note:
            # 总结被跳过/失败必须明示（2026-09-15 裁决：不许静默降级）
            sections += [f"> {llm_note}", ""]
        if video_rel:
            sections += [f"![[{video_rel}]]", ""]
        if image_rels:
            # 图文笔记图集（2026-09-14 裁决：图是原件，逐张内嵌可翻看）
            sections += [f"![[{rel}]]" for rel in image_rels] + [""]
        if summary:
            sections += ["## 观点总结", "", summary["summary"]]
            if summary.get("points"):
                sections += ["", "## 分观点论述", ""]
                sections += [
                    f"{i}. {point}" for i, point in enumerate(summary["points"], 1)
                ]
            if summary.get("insights"):
                sections += ["", "## 金句摘录", ""]
                sections += [f"> {item}" for item in summary["insights"]]
            if summary.get("insights_dropped"):
                sections += [
                    "",
                    f"> （{summary['insights_dropped']} 条候选金句未通过"
                    "原文回溯校验，已剔除——摘录必须逐字出自原文）",
                ]
            if summary.get("entities"):
                sections += ["", "## 提到的人·书·概念", ""]
                sections += [f"- {item}" for item in summary["entities"]]
            sections.append("")
        if body and transcript_rel:
            sections += ["## 全文", "", f"[[{transcript_rel}|查看{body_label}]]"]
        elif body:
            sections += [f"## {body_label}", "", body]
        return "\n".join(sections) + "\n"

    def _preserve_video(
        self, video_path: Path, source_label: str, title: str, doc_id: str
    ) -> Tuple[Optional[str], Optional[bytes]]:
        """把下载视频压成 480p 交回（rel 路径 + bytes），dispatch 层负责落盘。

        本处理器不感知存储位置（分层纪律：processors 与 memory 互不
        import）；``attachments/<平台>/<名>.mp4`` 只是与 dispatch 约定
        的相对路径串，markdown 内嵌与之同串。**压缩失败保留原件字节
        保底**（用户裁决 G2：绝不能压坏了还丢原件）；连读取都失败返回
        (None, None)——笔记照出不带视频，来源行 URL 仍可回溯。

        Args:
            video_path: 下载原件（临时目录内，随 process() 清理）。
            source_label: 平台中文名（抖音/小红书），兼作子目录名。
            title: 视频标题（用于文件名，人读优先）。
            doc_id: 平台内容 id（文件名短码，防撞名+同内容幂等）。

        Returns:
            Tuple[Optional[str], Optional[bytes]]: (库内相对路径, 文件
            字节)；失败 (None, None)。
        """
        rel = self._video_rel(source_label, title, doc_id)
        payload = video_path
        compressed = video_path.with_name(f"{video_path.stem}-480p.mp4")
        height = self._probe_height(video_path)
        if height is not None and height <= 480:
            # 片源已 ≤480p：保留原件（重编码既胀大文件又多一次有损，2026-09-10
            # B站 480p 实测 10MB→15MB 的教训；G2 的意图是省磁盘不是为压而压）
            payload = video_path
        elif self._compress_to_480p(video_path, compressed):
            payload = compressed
        try:
            return rel, payload.read_bytes()
        except OSError:
            return None, None

    @staticmethod
    def _probe_height(video_path: Path) -> Optional[int]:
        """ffprobe 取视频高度（px）；探测失败返回 None（调用方按未知处理）。"""
        command = [
            "ffprobe",
            "-v",
            "quiet",
            "-print_format",
            "json",
            "-show_streams",
            str(video_path),
        ]
        try:
            proc = subprocess.run(
                command, capture_output=True, timeout=30, check=False
            )
            streams = json.loads(proc.stdout or "{}").get("streams") or []
            for stream in streams:
                if stream.get("codec_type") == "video" and stream.get("height"):
                    return int(stream["height"])
        except Exception:  # noqa: BLE001 - 探测失败按未知高度处理
            return None
        return None

    @staticmethod
    def _artifact_stem(source_label: str, title: str, doc_id: str) -> str:
        """平台-标题-id短码 的文件主名（人读标题优先、净化、60 字截断）。

        命名规则与 dispatch/links.py 的笔记命名同源；id 短码常驻——
        同名不同视频绝不互相覆盖，同内容重跑（状态丢失重放）落盘时
        同名跳过即幂等。
        """
        safe = ""
        if title:
            safe = re.sub(r'[/\\:*?"<>|\x00-\x1f]', "-", title)
            # “#”在 wikilink/嵌入里是标题引用符，出现在文件名会断链，剔除
            safe = safe.replace("#", "")
            safe = re.sub(r"\s+", " ", safe).strip().strip(".")
            if len(safe) > 60:
                safe = safe[:60].rstrip()
        stem = f"{source_label}-{safe}" if safe else source_label
        if doc_id:
            stem = f"{stem}-{doc_id[:6]}"
        return stem

    @classmethod
    def _video_rel(cls, source_label: str, title: str, doc_id: str) -> str:
        """原视频库内相对路径：``attachments/<平台>/<主名>/视频.mp4``。

        2026-09-15 用户裁决：**一条内容一个文件夹**——视频/全文/图集
        都收进以内容主名命名的文件夹，平台目录第一层一行一条内容，
        不再平铺。旧平铺文件机器不搬（只改新内容的落法）。
        """
        return f"attachments/{source_label}/{cls._artifact_stem(source_label, title, doc_id)}/视频.mp4"

    @classmethod
    def _transcript_rel(cls, source_label: str, title: str, doc_id: str) -> str:
        """全文库内相对路径：与视频同文件夹的 ``全文.md``（一条内容一个
        文件夹，2026-09-15 用户裁决）。"""
        return f"attachments/{source_label}/{cls._artifact_stem(source_label, title, doc_id)}/全文.md"

    @staticmethod
    def _compress_to_480p(src: Path, dst: Path) -> bool:
        """ffmpeg 压到 480p（H.264 crf30 + AAC 96k，约为原件 1/10）；失败 False。

        高度大于 480 才缩（小片源不放大，避免越压越大）；faststart 便于
        Obsidian/浏览器边下边播。实现收敛在
        :func:`scripts.processors.video.compress_to_480p`（与直发视频通道
        共用唯一实现，禁止复制参数另起炉灶）。
        """
        return compress_to_480p(src, dst)

    @staticmethod
    def _cleanup(download_dir: str) -> None:
        """尽力清理下载临时目录（含其中的视频文件）。"""
        try:
            for path in Path(download_dir).iterdir():
                path.unlink()
            Path(download_dir).rmdir()
        except OSError:
            pass
