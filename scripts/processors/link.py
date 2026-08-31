"""链接抓取处理器（抖音：分享文本 → 视频下载 → Whisper 转写）。

与其他处理器不同，``process()`` 的 ``input_path`` 形参承载的是**一段
分享文本或 URL**，不是文件路径。流程：提取 URL → 识别平台 →
yt-dlp 下载视频到临时目录 → 复用 :class:`VideoProcessor` 转写 →
组装带来源行的 Markdown → 清理临时文件。

输出格式（v2）：标题 + 来源行 + ``## 转写全文``——转写去除逐句
时间戳、按标点合并为自然段、繁体转简体（OpenCC）。"观点总结 /
分观点论述"两节依赖 LLM，待 API key 配置后补入（暂不留占位）。

反爬约束（2026-08-31 真实样本实测）：抖音详情 API 对匿名请求 403，
但 yt-dlp 借浏览器 cookie（``cookiesfrombrowser``）可拿到视频流地址
完成下载；标题/作者优先取 yt-dlp 元数据，缺失时回退解析分享文本
（``【作者的作品】标题 https://...`` 结构）。cookie 过期时在对应
浏览器打开一次 douyin.com 即可刷新。

触发方式：dispatch 定时器自动分发（scripts/dispatch/links.py）或
人工执行 CLI（process_cli link 子命令）。

单元测试 monkeypatch ``yt_dlp.YoutubeDL`` 与 ``VideoProcessor``，
无真实网络与模型下载。
"""

from __future__ import annotations

import re
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

import opencc
import yt_dlp

from scripts.processors.base import BaseProcessor, ProcessResult
from scripts.processors.video import VideoProcessor

#: 抖音域名（短链 / 视频页 / 分享页）
_DOUYIN_HOSTS: Tuple[str, ...] = (
    "v.douyin.com",
    "www.douyin.com",
    "www.iesdouyin.com",
)

#: 分享文本中作者的结构（"看看【武世红的作品】..."）
_AUTHOR_RE = re.compile(r"【(?P<author>.+?)的作品】")

#: URL 提取（到第一个空白字符为止）
_URL_RE = re.compile(r"https?://[^\s]+")

#: URL 首尾可能粘附的中文标点
_URL_TRAILING = "。，、！？；：）》\"'…"

#: 视频下载后按扩展名在临时目录里定位产物
_VIDEO_EXTS: Tuple[str, ...] = (".mp4", ".mkv", ".webm", ".mov", ".flv")

#: 视频处理器输出里的逐句时间戳行（"- [00:00] 文本"）
_SEGMENT_LINE_RE = re.compile(r"^- \[\d{2}:\d{2}\]\s*", re.M)

#: 繁体 → 简体转换器（模块级单例）
_T2S = opencc.OpenCC("t2s")


def _transcript_to_paragraphs(transcript_markdown: str, width: int = 160) -> str:
    """把视频处理器的逐句时间戳转写合并为自然段（简体）。

    剥掉 ``- [mm:ss]`` 前缀 → 拼成整段文本 → 在句号/问号/感叹号等
    句读处、累积超过 width 字处分段；无标点时整段返回。

    Args:
        transcript_markdown: 视频处理器的 markdown（含时间戳行）。
        width: 分段的目标字数下限（到句读才切）。

    Returns:
        str: 简体、无时间戳、空行分段的转写全文。
    """
    joined = _SEGMENT_LINE_RE.sub("", transcript_markdown)
    text = _T2S.convert("".join(joined.split()))
    paragraphs: List[str] = []
    buf = ""
    for ch in text:
        buf += ch
        if len(buf) >= width and ch in "。！？；…":
            paragraphs.append(buf)
            buf = ""
    if buf:
        paragraphs.append(buf)
    return "\n\n".join(paragraphs)


def _extract_url(text: str) -> Optional[str]:
    """从分享文本中提取第一个 http(s) URL。

    Args:
        text: 分享文本或纯 URL。

    Returns:
        Optional[str]: 清理过首尾标点的 URL；找不到返回 None。
    """
    match = _URL_RE.search(text)
    if not match:
        return None
    return match.group(0).strip(_URL_TRAILING)


def _detect_platform(url: str) -> Optional[str]:
    """按域名识别平台。

    Args:
        url: 完整 URL。

    Returns:
        Optional[str]: "douyin" 或 None（不支持的平台）。
    """
    for host in _DOUYIN_HOSTS:
        if host in url:
            return "douyin"
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
    url_match = _URL_RE.search(rest)
    if url_match:
        title = rest[: url_match.start()]
    title = title.strip().rstrip(".… ").strip()
    return title, author


class LinkProcessor(BaseProcessor):
    """链接抓取处理器（当前支持抖音分享文本/链接）。

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
            config: processors.link 配置节（model / cookies_browser）；
            缺省按配置文件加载。
        """
        super().__init__(config)
        self.model = str(self.config.get("model", "medium"))
        self.cookies_browser = str(self.config.get("cookies_browser", "chrome"))

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
        platform = _detect_platform(url)
        if platform != "douyin":
            return self._fail(f"暂不支持的平台（已支持: 抖音）: {url}")

        share_title, share_author = _parse_share_text(text)
        download_dir = tempfile.mkdtemp(prefix="atelierr-link-")
        try:
            video_path, info, error = self._download(url, download_dir)
            if error is not None:
                return self._fail(error)
            video_result = VideoProcessor({"model": self.model}).process(video_path)
            if not video_result.success:
                return self._fail(video_result.error or "视频转写失败")
            title = str(info.get("title") or "").strip() or share_title
            author = str(info.get("uploader") or "").strip() or share_author
            markdown = self._build_markdown(
                title or (video_path.stem if video_path else "link"),
                author,
                url,
                video_result.markdown,
            )
            metadata = {
                "engine": "yt-dlp+whisper",
                "platform": platform,
                "model": self.model,
                "url": url,
                "video_id": str(info.get("id") or ""),
                "segments": video_result.metadata.get("segments", 0),
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

    def _download(
        self, url: str, download_dir: str
    ) -> Tuple[Optional[Path], Dict[str, Any], Optional[str]]:
        """用 yt-dlp 下载视频到临时目录。

        Args:
            url: 视频 URL。
            download_dir: 临时目录路径。

        Returns:
            Tuple[Optional[Path], Dict[str, Any], Optional[str]]:
            (视频路径, yt-dlp info 字典, 错误信息)；成功时 error 为 None。
        """
        options: Dict[str, Any] = {
            "outtmpl": str(Path(download_dir) / "%(id)s.%(ext)s"),
            "quiet": True,
            "no_warnings": True,
            "socket_timeout": 30,
        }
        if self.cookies_browser:
            options["cookiesfrombrowser"] = (self.cookies_browser,)
        try:
            with yt_dlp.YoutubeDL(options) as ydl:
                info = ydl.extract_info(url, download=True)
        except yt_dlp.utils.DownloadError as exc:
            detail = str(exc).splitlines()[0][:200] if str(exc) else "未知错误"
            hint = ""
            if "cookie" in str(exc).lower():
                hint = f"（cookie 失效？在 {self.cookies_browser} 打开一次 douyin.com 后重试）"
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

    @staticmethod
    def _build_markdown(
        title: str, author: str, url: str, transcript_markdown: str
    ) -> str:
        """组装最终 Markdown：标题 + 来源行 + 转写全文（分段简体，无时间戳）。

        Args:
            title: 笔记标题。
            author: 作者（可为空串）。
            url: 来源链接。
            transcript_markdown: 视频处理器的输出（逐句时间戳格式，
            在此转换，原标题行丢弃）。

        Returns:
            str: 完整 Markdown。
        """
        source = f"> 来源：抖音 @{author} {url}" if author else f"> 来源：抖音 {url}"
        body = _transcript_to_paragraphs(transcript_markdown)
        return f"# {_T2S.convert(title)}\n\n{source}\n\n## 转写全文\n\n{body}\n"

    @staticmethod
    def _cleanup(download_dir: str) -> None:
        """尽力清理下载临时目录（含其中的视频文件）。"""
        try:
            for path in Path(download_dir).iterdir():
                path.unlink()
            Path(download_dir).rmdir()
        except OSError:
            pass
