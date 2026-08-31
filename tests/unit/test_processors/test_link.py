"""链接抓取处理器单元测试（无真实网络与模型下载）。

yt_dlp.YoutubeDL 与 VideoProcessor 均 monkeypatch 为假实现；
URL 提取、分享文本解析、错误路径与临时目录清理为真实代码路径。
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yt_dlp

import scripts.processors.link as link_module
from scripts.processors.base import ProcessResult
from scripts.processors.link import LinkProcessor, _extract_url, _parse_share_text

SHARE_TEXT = (
    "1.58 复制打开抖音，看看【武世红的作品】德国著名哲学家叔本华写了两本书，"
    "其中之一是《作为意... https://v.douyin.com/eQOGBXJdlwQ/ :1pm TLW:/"
)


class _FakeYoutubeDL:
    """假 yt_dlp.YoutubeDL：在下载目录造一个 mp4 并返回元数据。"""

    def __init__(self, opts):
        self.opts = opts

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def extract_info(self, url, download=True):
        outtmpl = self.opts["outtmpl"]
        video = Path(outtmpl.replace("%(id)s", "vid123").replace("%(ext)s", "mp4"))
        video.write_bytes(b"fake video bytes")
        return {"id": "vid123", "title": "信息标题", "uploader": "信息作者"}


class _FakeVideoProcessor:
    """假 VideoProcessor：返回固定转写结果，记录传入配置。"""

    last_config = None

    def __init__(self, config=None):
        _FakeVideoProcessor.last_config = config

    def process(self, path):
        assert Path(path).exists()
        return ProcessResult(
            success=True,
            text="转写全文",
            markdown="# vid123\n\n## 转写文字\n\n- [00:00] 你好",
            confidence=0.9,
            metadata={"segments": 1},
        )


@pytest.fixture
def fake_pipeline(monkeypatch):
    """替换下载与转写为假实现，返回记录下载目录的列表。"""
    made_dirs = []

    class _RecordingYT(_FakeYoutubeDL):
        def __init__(self, opts):
            super().__init__(opts)
            made_dirs.append(Path(opts["outtmpl"]).parent)

    monkeypatch.setattr(link_module.yt_dlp, "YoutubeDL", _RecordingYT)
    monkeypatch.setattr(link_module, "VideoProcessor", _FakeVideoProcessor)
    return made_dirs


def test_extract_url_from_share_text():
    """从整段分享文本中提取短链（去掉后随内容）。"""
    assert _extract_url(SHARE_TEXT) == "https://v.douyin.com/eQOGBXJdlwQ/"


def test_extract_url_strips_trailing_punctuation():
    """URL 后粘附的中文标点被清理。"""
    assert _extract_url("看这个 https://v.douyin.com/abc/。") == "https://v.douyin.com/abc/"


def test_extract_url_none():
    """没有 URL 时返回 None。"""
    assert _extract_url("纯文字没有链接") is None


def test_parse_share_text_author_and_title():
    """解析【作者的作品】结构与 】 到 URL 之间的标题。"""
    title, author = _parse_share_text(SHARE_TEXT)

    assert author == "武世红"
    assert title == "德国著名哲学家叔本华写了两本书，其中之一是《作为意"


def test_parse_share_text_without_author():
    """无【】结构时作者为空、标题为空（回退由 process 处理）。"""
    title, author = _parse_share_text("https://v.douyin.com/abc/")

    assert author == ""


def test_process_no_url_fails():
    """无链接 → success=False（不抛异常）。"""
    result = LinkProcessor().process("随便一段文字")

    assert not result.success
    assert "链接" in (result.error or "")


def test_process_unsupported_platform_fails():
    """非抖音链接 → success=False。"""
    result = LinkProcessor().process("https://example.com/video/1")

    assert not result.success
    assert "平台" in (result.error or "")


def test_process_success(fake_pipeline):
    """成功路径：markdown 含标题/来源/分段简体转写，元数据齐全，临时目录已清理。"""
    result = LinkProcessor().process(SHARE_TEXT)

    assert result.success, result.error
    assert result.markdown.startswith("# 信息标题\n")
    assert "> 来源：抖音 @信息作者 https://v.douyin.com/eQOGBXJdlwQ/" in result.markdown
    assert "## 转写全文" in result.markdown
    assert "你好" in result.markdown
    assert "[00:00]" not in result.markdown
    assert result.metadata["platform"] == "douyin"
    assert result.metadata["model"] == "large-v3"
    assert result.confidence == 0.9
    assert fake_pipeline and not fake_pipeline[0].exists()


def test_transcript_to_paragraphs():
    """时间戳剥离 + 繁转简 + 按字数分段；标题/小节头不得混入正文。"""
    raw = "# 视频标题\n\n## 转写文字\n\n- [00:00] 著名的哲學家舒本花寫過兩本書。\n- [00:04] 其中之一是作為意志和表現的世界。\n"

    body = link_module._transcript_to_paragraphs(raw, width=10)

    assert "[00:" not in body
    assert "视频标题" not in body
    assert "转写文字" not in body
    assert "著名的哲学家舒本花写过两本书。" in body
    assert "其中之一是作为意志和表现的世界。" in body
    assert "\n\n" in body


def test_transcript_no_punctuation_still_paragraphs():
    """无标点转写（Whisper 常见）也按字数强制分段。"""
    raw = "- [00:00] " + "啊" * 100 + "\n- [00:05] " + "嗯" * 100

    body = link_module._transcript_to_paragraphs(raw, width=80)

    assert "\n\n" in body
    assert "。" not in body


def test_title_fallback_to_share_text(fake_pipeline, monkeypatch):
    """yt-dlp 元数据缺标题/作者时回退到分享文本解析。"""

    class _NoMetaYT(_FakeYoutubeDL):
        def extract_info(self, url, download=True):
            super().extract_info(url, download)
            return {"id": "vid123"}

    monkeypatch.setattr(link_module.yt_dlp, "YoutubeDL", _NoMetaYT)

    result = LinkProcessor().process(SHARE_TEXT)

    assert result.success, result.error
    assert result.markdown.startswith("# 德国著名哲学家叔本华写了两本书")
    assert "@武世红" in result.markdown


def test_download_failure(monkeypatch):
    """下载抛 DownloadError → success=False，cookie 类错误带提示。"""
    monkeypatch.setattr(LinkProcessor, "_refresh_cookies", lambda self, url: False)

    class _FailYT:
        def __init__(self, opts):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def extract_info(self, url, download=True):
            raise yt_dlp.utils.DownloadError("Fresh cookies are needed")

    monkeypatch.setattr(link_module.yt_dlp, "YoutubeDL", _FailYT)

    result = LinkProcessor().process(SHARE_TEXT)

    assert not result.success
    assert "下载失败" in (result.error or "")
    assert "douyin.com" in (result.error or "")


def test_transcribe_failure(fake_pipeline, monkeypatch):
    """转写失败 → success=False 且错误透传。"""

    class _FailVideo(_FakeVideoProcessor):
        def process(self, path):
            return ProcessResult(success=False, error="ffmpeg 抽取音频失败: boom")

    monkeypatch.setattr(link_module, "VideoProcessor", _FailVideo)

    result = LinkProcessor().process(SHARE_TEXT)

    assert not result.success
    assert "ffmpeg" in (result.error or "")


def test_link_model_forwarded_to_video(fake_pipeline):
    """processors.link.model 透传给 VideoProcessor（默认 large-v3）。"""
    result = LinkProcessor().process(SHARE_TEXT)

    assert result.success, result.error
    assert _FakeVideoProcessor.last_config == {"model": "large-v3"}


def test_config_defaults():
    """内置默认配置：model=large-v3、cookies_browser=chrome、profile/二进制默认。"""
    processor = LinkProcessor()

    assert processor.model == "large-v3"
    assert processor.cookies_browser == "chrome"
    assert "douyin-chrome-profile" in processor.chrome_profile_dir
    assert processor.chrome_binary == ""


def test_cookie_refresh_retry_success(fake_pipeline, monkeypatch):
    """cookie 失效 → 自动无头刷新 → 携专用 profile 重试成功。"""
    calls = []

    class _CookieAwareYT:
        def __init__(self, opts):
            self.opts = opts

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def extract_info(self, url, download=True):
            cookies = self.opts.get("cookiesfrombrowser")
            calls.append(cookies)
            if cookies and len(cookies) == 1:
                raise yt_dlp.utils.DownloadError("Fresh cookies are needed")
            out = Path(
                self.opts["outtmpl"].replace("%(id)s", "vid123").replace(
                    "%(ext)s", "mp4"
                )
            )
            out.write_bytes(b"fake video bytes")
            return {"id": "vid123", "title": "自愈标题", "uploader": "作者"}

    monkeypatch.setattr(link_module.yt_dlp, "YoutubeDL", _CookieAwareYT)
    refresh_calls = []
    monkeypatch.setattr(
        LinkProcessor, "_refresh_cookies", lambda self, url: refresh_calls.append(url) or True
    )

    result = LinkProcessor().process(SHARE_TEXT)

    assert result.success, result.error
    assert result.markdown.startswith("# 自愈标题\n")
    assert len(refresh_calls) == 1
    assert len(calls) == 2
    assert calls[1][1].endswith("Default")


def test_cookie_refresh_failure_keeps_error(fake_pipeline, monkeypatch):
    """无头刷新失败 → 返回带提示的 cookie 错误（不静默重试）。"""
    monkeypatch.setattr(LinkProcessor, "_refresh_cookies", lambda self, url: False)

    class _AlwaysCookieFailYT:
        def __init__(self, opts):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def extract_info(self, url, download=True):
            raise yt_dlp.utils.DownloadError("Fresh cookies are needed")

    monkeypatch.setattr(link_module.yt_dlp, "YoutubeDL", _AlwaysCookieFailYT)

    result = LinkProcessor().process(SHARE_TEXT)

    assert not result.success
    assert "douyin.com" in (result.error or "")


def test_cli_link_command(fake_pipeline):
    """CLI 层：link 子命令成功 exit 0 并打印 markdown。"""
    from scripts.cli.process_cli import ProcessCLI

    code = ProcessCLI().main(["link", SHARE_TEXT])

    assert code == 0
