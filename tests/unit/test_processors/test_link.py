"""链接抓取处理器单元测试（无真实网络与模型下载）。

yt_dlp.YoutubeDL 与 VideoProcessor 均 monkeypatch 为假实现；
URL 提取、分享文本解析、错误路径与临时目录清理为真实代码路径。
"""

from __future__ import annotations

from pathlib import Path

import frontmatter
import pytest
import yt_dlp

import scripts.processors.link as link_module
from scripts.processors.base import ProcessResult
from scripts.processors.link import (
    LinkProcessor,
    _extract_url,
    _parse_share_text,
    detect_platform,
)

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
    """替换下载与转写为假实现，返回记录下载目录的列表。

    同时摘除 LLM key 环境变量：缺省测试路径不打真实 API。
    """
    made_dirs = []

    class _RecordingYT(_FakeYoutubeDL):
        def __init__(self, opts):
            super().__init__(opts)
            made_dirs.append(Path(opts["outtmpl"]).parent)

    monkeypatch.setattr(link_module.yt_dlp, "YoutubeDL", _RecordingYT)
    monkeypatch.setattr(link_module, "VideoProcessor", _FakeVideoProcessor)
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    return made_dirs


class _FakeLLMResponse:
    """假 httpx 响应：raise_for_status 通过，json 返回固定负载。"""

    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


def _llm_payload(summary="核心观点总结。", points=("观点一。", "观点二。"), extra=None):
    import json as _json

    content = _json.dumps(
        {"summary": summary, "points": list(points), **(extra or {})},
        ensure_ascii=False,
    )
    return {"choices": [{"message": {"content": content}}]}


def _branching_llm(monkeypatch, format_text="", format_error=False):
    """假 LLM：按提示词分流——含"整理为易读"是整理调用，否则是摘要调用。

    format_text 缺省为空串（触发 empty-format 拒绝，正文走机械分段）。
    """

    def _post(url, headers=None, json=None, timeout=None):
        prompt = json["messages"][0]["content"]
        if "整理为易读" in prompt:
            if format_error:
                raise RuntimeError("format api down")
            return _FakeLLMResponse({"choices": [{"message": {"content": format_text}}]})
        return _FakeLLMResponse(_llm_payload())

    monkeypatch.setattr(link_module.httpx, "post", _post)


def _fixed_llm(monkeypatch, payload, format_text=""):
    """假 LLM：摘要调用返回固定 payload，整理调用按 format_text 返回。

    与 _branching_llm 相同分流规则，但摘要响应内容可控（新字段用例）。
    """

    def _post(url, headers=None, json=None, timeout=None):
        prompt = json["messages"][0]["content"]
        if "整理为易读" in prompt:
            return _FakeLLMResponse({"choices": [{"message": {"content": format_text}}]})
        return _FakeLLMResponse(payload)

    monkeypatch.setattr(link_module.httpx, "post", _post)


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
    assert result.metadata["title"] == "信息标题"
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
    """无标点转写（未带标点提示的旧产物）兜底按字数硬切段。"""
    raw = "- [00:00] " + "啊" * 100 + "\n- [00:05] " + "嗯" * 100

    body = link_module._transcript_to_paragraphs(raw, width=80)

    assert "\n\n" in body
    assert "。" not in body


def test_transcript_paragraphs_break_on_sentence_end():
    """有标点时按句界分段：除末段外每段以句末标点收尾。"""
    raw = "- [00:00] " + "短句。" * 10 + "\n- [00:05] " + "短句。" * 10

    body = link_module._transcript_to_paragraphs(raw, width=30)

    paragraphs = body.split("\n\n")
    assert len(paragraphs) >= 2
    for paragraph in paragraphs[:-1]:
        assert paragraph.endswith("。")
    assert all(len(p) <= 30 for p in paragraphs)


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


def test_llm_summary_inserted(fake_pipeline, monkeypatch):
    """LLM 正常返回：摘要两节插入来源行与转写全文之间，metadata 记 ok。"""
    monkeypatch.setenv("DEEPSEEK_API_KEY", "fake-key")
    _branching_llm(monkeypatch)

    result = LinkProcessor().process(SHARE_TEXT)

    assert result.success, result.error
    assert "## 观点总结\n\n核心观点总结。" in result.markdown
    assert "## 分观点论述\n\n1. 观点一。\n2. 观点二。" in result.markdown
    assert result.markdown.index("## 观点总结") < result.markdown.index("## 转写全文")
    assert result.metadata["llm"]["status"] == "ok"


def test_llm_v4_full_fields_rendered_with_tags(fake_pipeline, monkeypatch):
    """v4 JSON 全字段：金句/实体两节按序渲染，frontmatter tags 含分类与主题词。"""
    monkeypatch.setenv("DEEPSEEK_API_KEY", "fake-key")

    class _RichTranscriptVideo(_FakeVideoProcessor):
        """转写全文包含金句原文（金句回溯机检要求逐字出自原文）。"""

        def process(self, path):
            assert Path(path).exists()
            return ProcessResult(
                success=True,
                text="开场白。这句话是最反常识的判断。结束语。",
                markdown="# vid123\n\n## 转写文字\n\n- [00:00] 你好",
                confidence=0.9,
                metadata={"segments": 1},
            )

    monkeypatch.setattr(link_module, "VideoProcessor", _RichTranscriptVideo)
    payload = _llm_payload(
        summary="核心观点总结。",
        points=("观点一。", "观点二。"),
        extra={
            "insights": ["这句话是最反常识的判断。"],
            "entities": [
                "叔本华（德国哲学家）",
                "《作为意志和表象的世界》（叔本华著作）",
            ],
            "category": "B84-心理学",
            "topics": ["唯意志论", "人生哲学"],
        },
    )
    _fixed_llm(monkeypatch, payload)

    result = LinkProcessor().process(SHARE_TEXT)

    assert result.success, result.error
    markdown = result.markdown
    order = [
        markdown.index(head)
        for head in ("## 观点总结", "## 分观点论述", "## 金句摘录",
                     "## 提到的人·书·概念", "## 转写全文")
    ]
    assert order == sorted(order)
    assert "## 金句摘录\n\n> 这句话是最反常识的判断。" in markdown
    assert (
        "## 提到的人·书·概念\n\n"
        "- 叔本华（德国哲学家）\n"
        "- 《作为意志和表象的世界》（叔本华著作）" in markdown
    )
    post = frontmatter.loads(markdown)
    assert post.metadata["tags"] == [
        "待确认", "抖音", "B84-心理学", "唯意志论", "人生哲学",
    ]


def test_llm_old_format_backward_compatible(fake_pipeline, monkeypatch):
    """旧格式 JSON（只有 summary/points）：无新节、无分类 tags，照常渲染。"""
    monkeypatch.setenv("DEEPSEEK_API_KEY", "fake-key")
    _branching_llm(monkeypatch)

    result = LinkProcessor().process(SHARE_TEXT)

    assert result.success, result.error
    assert result.markdown.startswith("# 信息标题\n")
    assert "## 观点总结\n\n核心观点总结。" in result.markdown
    assert "## 分观点论述" in result.markdown
    assert "## 金句摘录" not in result.markdown
    assert "## 提到的人·书·概念" not in result.markdown


def test_llm_points_over_five_not_truncated(fake_pipeline, monkeypatch):
    """points 超过 5 条不再截断（v3 硬截断 [:5]）：8 条全保留并按序编号。"""
    monkeypatch.setenv("DEEPSEEK_API_KEY", "fake-key")
    points = tuple(f"观点 {i}。" for i in range(1, 9))
    _fixed_llm(monkeypatch, _llm_payload(points=points))

    result = LinkProcessor().process(SHARE_TEXT)

    assert result.success, result.error
    block = result.markdown.split("## 分观点论述", 1)[1]
    for i in range(1, 9):
        assert f"{i}. 观点 {i}。" in block
    assert "9. 观点" not in block


def test_llm_topics_category_whitespace_cleaned(fake_pipeline, monkeypatch):
    """category/topics 含空白：内部空白替换为 -，空项过滤（Obsidian 标签禁空格）。"""
    monkeypatch.setenv("DEEPSEEK_API_KEY", "fake-key")
    payload = _llm_payload(
        extra={
            "category": " B 哲学·宗教 ",
            "topics": ["认知 科学", "  ", "自我 提升", ""],
        }
    )
    _fixed_llm(monkeypatch, payload)

    result = LinkProcessor().process(SHARE_TEXT)

    assert result.success, result.error
    post = frontmatter.loads(result.markdown)
    assert post.metadata["tags"] == [
        "待确认", "抖音", "B-哲学·宗教", "认知-科学", "自我-提升",
    ]


def test_llm_format_replaces_body(fake_pipeline, monkeypatch):
    """LLM 整理成功：转写全文用整理后文本（带分段），metadata 记 format ok。"""
    monkeypatch.setenv("DEEPSEEK_API_KEY", "fake-key")
    _branching_llm(monkeypatch, format_text="整理后第一段。\n\n整理后第二段。")

    result = LinkProcessor().process(SHARE_TEXT)

    assert result.success, result.error
    assert "## 转写全文\n\n整理后第一段。\n\n整理后第二段。" in result.markdown
    assert result.metadata["llm"]["format"] == "ok"
    assert result.metadata["llm"]["status"] == "ok"


def test_llm_format_failure_falls_back(fake_pipeline, monkeypatch):
    """整理调用失败：摘要照常，正文降级为机械分段。"""
    monkeypatch.setenv("DEEPSEEK_API_KEY", "fake-key")
    _branching_llm(monkeypatch, format_error=True)

    result = LinkProcessor().process(SHARE_TEXT)

    assert result.success, result.error
    assert "## 观点总结" in result.markdown
    assert "你好" in result.markdown  # 机械分段来自假转写
    assert result.metadata["llm"]["format"].startswith("failed:")


def test_llm_format_short_output_rejected(fake_pipeline, monkeypatch):
    """整理结果不足原文一半（疑似被写成摘要）：拒绝，回退机械分段。"""
    monkeypatch.setenv("DEEPSEEK_API_KEY", "fake-key")
    _branching_llm(monkeypatch, format_text="短")

    result = LinkProcessor().process(SHARE_TEXT)

    assert result.success, result.error
    assert result.metadata["llm"]["format"] == "failed:suspiciously-short"
    assert "你好" in result.markdown


def test_llm_failure_degrades(fake_pipeline, monkeypatch):
    """LLM 调用异常：笔记仍建成，无摘要节，状态 failed（降级不阻塞）。"""
    monkeypatch.setenv("DEEPSEEK_API_KEY", "fake-key")

    def _boom(*args, **kwargs):
        raise RuntimeError("api down")

    monkeypatch.setattr(link_module.httpx, "post", _boom)

    result = LinkProcessor().process(SHARE_TEXT)

    assert result.success, result.error
    assert "## 观点总结" not in result.markdown
    assert "## 转写全文" in result.markdown
    assert result.metadata["llm"]["status"].startswith("failed:")


def test_llm_skipped_without_key(fake_pipeline):
    """无 key 环境变量：跳过摘要，状态 skipped（不算失败）。"""
    result = LinkProcessor().process(SHARE_TEXT)

    assert result.success, result.error
    assert "## 观点总结" not in result.markdown
    assert result.metadata["llm"]["status"] == "skipped:no-DEEPSEEK_API_KEY"


def test_llm_skipped_too_long(fake_pipeline, monkeypatch):
    """转写超过 max_transcript_chars（成本护栏）：跳过，不发请求。"""
    monkeypatch.setenv("DEEPSEEK_API_KEY", "fake-key")
    called = []
    monkeypatch.setattr(
        link_module.httpx, "post", lambda *a, **k: called.append(1) or None
    )

    result = LinkProcessor({"llm": {"max_transcript_chars": 2}}).process(SHARE_TEXT)

    assert result.success, result.error
    assert result.metadata["llm"]["status"] == "skipped:too-long"
    assert not called


def test_llm_bad_json_degrades(fake_pipeline, monkeypatch):
    """LLM 返回非 JSON：降级为无摘要笔记，不抛异常。"""
    monkeypatch.setenv("DEEPSEEK_API_KEY", "fake-key")
    payload = {"choices": [{"message": {"content": "这不是 JSON"}}]}
    monkeypatch.setattr(
        link_module.httpx, "post", lambda *a, **k: _FakeLLMResponse(payload)
    )

    result = LinkProcessor().process(SHARE_TEXT)

    assert result.success, result.error
    assert "## 观点总结" not in result.markdown
    assert result.metadata["llm"]["status"].startswith("failed:")


# ---- 小红书 ----

XHS_SHARE_TEXT = (
    '健脑小课堂｜"英年早呆"？别怕还有救 出门用导航，... '
    "https://xhslink.cn/o/2Vhl2blNpHM 【小红书】里的笔记已备好，复制后快来~"
)

_XHS_FINAL_URL = "https://www.xiaohongshu.com/discovery/item/abc123"

_XHS_NOTE_VIDEO = {
    "title": "健脑小课堂",
    "desc": "出门用导航，遇事问AI",
    "type": "video",
    "noteId": "abc123",
    "user": {"nickName": "Olga姐姐"},
    "video": {
        "media": {"stream": {"h264": [{"masterUrl": "http://cdn.example/v.mp4"}]}}
    },
}

_XHS_NOTE_TEXT = {
    "title": "图文笔记标题",
    "desc": "这是图文笔记的正文内容。",
    "type": "normal",
    "noteId": "txt456",
    "user": {"nickName": "某人"},
}


@pytest.fixture
def fake_xhs_page(monkeypatch):
    """替换小红书页面抓取与视频下载为假实现；摘除 LLM key。

    返回可控状态字典：note（页面解析结果）/ error（抓取错误）/
    downloaded（下载调用记录）。
    """
    state = {"note": _XHS_NOTE_VIDEO, "error": None, "downloaded": []}

    def _fake_fetch(url):
        return state["note"], _XHS_FINAL_URL, state["error"]

    def _fake_download(video_url, dest):
        state["downloaded"].append((video_url, Path(dest)))
        Path(dest).write_bytes(b"fake video bytes")
        return None

    monkeypatch.setattr(
        LinkProcessor, "_fetch_xhs_note", staticmethod(_fake_fetch)
    )
    monkeypatch.setattr(
        LinkProcessor, "_download_xhs_video", staticmethod(_fake_download)
    )
    monkeypatch.setattr(link_module, "VideoProcessor", _FakeVideoProcessor)
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    return state


def test_detect_platform_xhs():
    """xhslink.cn 短链与 xiaohongshu.com 详情页都识别为 xhs。"""
    assert detect_platform("https://xhslink.cn/o/2Vhl2blNpHM") == "xhs"
    assert detect_platform("https://www.xiaohongshu.com/explore/abc123") == "xhs"
    assert detect_platform("https://example.com/x") is None


def test_xhs_video_success(fake_xhs_page):
    """视频笔记：下载视频走 Whisper，markdown 含小红书来源行。"""
    result = LinkProcessor().process(XHS_SHARE_TEXT)

    assert result.success, result.error
    assert result.metadata["platform"] == "xhs"
    assert result.metadata["note_id"] == "abc123"
    assert result.metadata["title"] == "健脑小课堂"
    assert result.metadata["engine"] == "xhs-page+whisper"
    assert result.metadata["url"] == _XHS_FINAL_URL
    assert fake_xhs_page["downloaded"][0][0] == "http://cdn.example/v.mp4"
    assert result.markdown.startswith("# 健脑小课堂")
    assert f"> 来源：小红书 @Olga姐姐 {_XHS_FINAL_URL}" in result.markdown
    assert "## 转写全文" in result.markdown


def test_xhs_text_note_success(fake_xhs_page):
    """图文笔记：不下载不转写，正文直入库。"""
    fake_xhs_page["note"] = _XHS_NOTE_TEXT

    result = LinkProcessor().process(XHS_SHARE_TEXT)

    assert result.success, result.error
    assert fake_xhs_page["downloaded"] == []
    assert result.metadata["engine"] == "xhs-page"
    assert "## 笔记正文" in result.markdown
    assert "这是图文笔记的正文内容。" in result.markdown
    assert "## 转写全文" not in result.markdown


def test_xhs_fetch_failure(fake_xhs_page):
    """页面获取失败 → success=False（不抛异常）。"""
    fake_xhs_page["note"] = None
    fake_xhs_page["error"] = "小红书页面获取失败: 403"

    result = LinkProcessor().process(XHS_SHARE_TEXT)

    assert not result.success
    assert "小红书页面获取失败" in (result.error or "")


def test_xhs_empty_note_fails(fake_xhs_page):
    """无标题无正文无视频的笔记 → success=False。"""
    fake_xhs_page["note"] = {"noteId": "x", "type": "normal"}

    result = LinkProcessor().process(XHS_SHARE_TEXT)

    assert not result.success
    assert "无有效内容" in (result.error or "")


def test_fetch_xhs_note_parses_initial_state(monkeypatch):
    """真实解析路径：内嵌 JSON 含 undefined 字面量也能解析。"""
    html = (
        "<html><script>window.__INITIAL_STATE__="
        '{"noteData":{"data":{"noteData":'
        '{"noteId":"n1","title":"标题","desc":undefined,'
        '"user":{"nickName":"作者"}}}}}'
        "</script></html>"
    )

    class _Resp:
        text = html
        url = _XHS_FINAL_URL

        def raise_for_status(self):
            return None

    monkeypatch.setattr(link_module.httpx, "get", lambda *a, **k: _Resp())

    note, final_url, error = LinkProcessor._fetch_xhs_note("https://xhslink.cn/o/xyz")

    assert error is None
    assert note is not None
    assert note["noteId"] == "n1"
    assert note["desc"] is None
    assert final_url == _XHS_FINAL_URL


def test_fetch_xhs_note_bad_structure(monkeypatch):
    """页面结构不符 → 返回解析错误（不抛异常）。"""

    class _Resp:
        text = "<html><script>window.__INITIAL_STATE__={\"a\":1}</script></html>"
        url = _XHS_FINAL_URL

        def raise_for_status(self):
            return None

    monkeypatch.setattr(link_module.httpx, "get", lambda *a, **k: _Resp())

    note, _, error = LinkProcessor._fetch_xhs_note("https://xhslink.cn/o/xyz")

    assert note is None
    assert error is not None and "解析失败" in error


def test_summarize_custom_prompt(monkeypatch):
    """_summarize 接受自定义提示词（网页剪藏复用同一 LLM 管道）。"""
    import json as _json

    monkeypatch.setenv("DEEPSEEK_API_KEY", "fake-key")
    processor = LinkProcessor(config={})
    captured = {}

    def _fake_chat(prompt, max_tokens, json_mode=False):
        captured["prompt"] = prompt
        return _json.dumps({"summary": "摘要。", "points": []})

    monkeypatch.setattr(processor, "_llm_chat", _fake_chat)

    data, status = processor._summarize("文章全文", prompt="自定义提示词：")

    assert status == "ok"
    assert data["summary"] == "摘要。"
    assert captured["prompt"] == "自定义提示词：\n文章全文"


def test_clip_prompt_derives_from_v4():
    """网页剪藏提示词与 V4 逐字同源：只换主语，中图法分类表保持一致。"""
    assert link_module._SUMMARIZE_CLIP_PROMPT.startswith("请阅读以下网页文章全文")
    assert link_module._SUMMARIZE_CLIP_PROMPT.endswith("文章全文：")
    assert "B84-心理学" in link_module._SUMMARIZE_CLIP_PROMPT
    assert "视频转写" not in link_module._SUMMARIZE_CLIP_PROMPT


# ----------------------------------------------------------------------
# 原视频 480p 保存（2026-09-10 用户裁决 G2：只存压缩版，压失败原件保底）
# ----------------------------------------------------------------------


def test_video_preserved_compressed(fake_pipeline, monkeypatch):
    """压缩成功：metadata 带 480p 字节与库内相对路径，markdown 内嵌同串。"""
    monkeypatch.setattr(
        LinkProcessor,
        "_compress_to_480p",
        staticmethod(lambda src, dst: dst.write_bytes(b"480p-bytes") or True),
    )

    result = LinkProcessor().process(SHARE_TEXT)

    assert result.success, result.error
    assert result.metadata["video_blob"] == b"480p-bytes"
    rel = result.metadata["video_rel"]
    assert rel == "attachments/抖音/抖音-信息标题-vid123.mp4"
    assert f"![[{rel}]]" in result.markdown
    # 内嵌在来源行之后、摘要之前
    assert result.markdown.index("> 来源：") < result.markdown.index(f"![[{rel}]]")


def test_video_preserved_original_on_compress_failure(fake_pipeline, monkeypatch):
    """压缩失败：保留原件字节保底（G2：绝不能压坏了还丢原件）。"""
    monkeypatch.setattr(
        LinkProcessor, "_compress_to_480p", staticmethod(lambda src, dst: False)
    )

    result = LinkProcessor().process(SHARE_TEXT)

    assert result.success, result.error
    assert result.metadata["video_blob"] == b"fake video bytes"
    assert result.metadata["video_rel"].endswith(".mp4")


def test_video_rel_naming_rules():
    """相对路径命名：平台目录 + 标题净化 + id 短码（防撞名/幂等）。"""
    rel = LinkProcessor._video_rel("抖音", "健脑小课堂/运动篇", "vid123456789")
    assert rel == "attachments/抖音/抖音-健脑小课堂-运动篇-vid123.mp4"
    # 无标题回退平台+id；无 id 不带短码
    assert LinkProcessor._video_rel("小红书", "", "n1") == "attachments/小红书/小红书-n1.mp4"
    assert LinkProcessor._video_rel("抖音", "标题", "") == "attachments/抖音/抖音-标题.mp4"


def test_compress_480p_command_and_failure(monkeypatch, tmp_path):
    """ffmpeg 调用形态：480p 限高、faststart；非零返回/无产出 → False。"""
    calls = []

    class _Proc:
        returncode = 0

    def _fake_run(command, **kwargs):
        calls.append(command)
        Path(command[-1]).write_bytes(b"x")
        return _Proc()

    monkeypatch.setattr(link_module.subprocess, "run", _fake_run)
    src = tmp_path / "in.mp4"
    src.write_bytes(b"fake")
    dst = tmp_path / "out.mp4"

    assert LinkProcessor._compress_to_480p(src, dst) is True
    command = calls[0]
    assert command[0] == "ffmpeg"
    assert "480" in command[command.index("-vf") + 1]
    assert "+faststart" in command

    class _BadProc:
        returncode = 1

    monkeypatch.setattr(
        link_module.subprocess, "run", lambda *a, **k: _BadProc()
    )
    dst2 = tmp_path / "out2.mp4"
    assert LinkProcessor._compress_to_480p(src, dst2) is False


# ----------------------------------------------------------------------
# B站平台适配（2026-09-10 用户裁决：只做 B站；yt-dlp 通道 + 限高下载）
# ----------------------------------------------------------------------

BILIBILI_URL = "https://www.bilibili.com/video/BV1xx411c7mD"


def test_detect_platform_bilibili():
    """B站域名识别：视频页 / b23 短链。"""
    assert detect_platform(BILIBILI_URL) == "bilibili"
    assert detect_platform("https://b23.tv/abc123") == "bilibili"
    assert detect_platform("https://www.youtube.com/watch?v=x") is None


def test_bilibili_process_success(fake_pipeline, monkeypatch):
    """B站链接走 yt-dlp 通道：平台标签 B站、限高 480、视频按平台目录保存。"""
    captured = {}

    class _OptsYT(_FakeYoutubeDL):
        def __init__(self, opts):
            super().__init__(opts)
            captured["opts"] = opts

    monkeypatch.setattr(link_module.yt_dlp, "YoutubeDL", _OptsYT)
    monkeypatch.setattr(
        LinkProcessor,
        "_compress_to_480p",
        staticmethod(lambda src, dst: dst.write_bytes(b"480p") or True),
    )

    result = LinkProcessor().process(f"看看这个 {BILIBILI_URL}")

    assert result.success, result.error
    assert result.metadata["platform"] == "bilibili"
    assert "> 来源：B站" in result.markdown
    assert captured["opts"]["format"] == (
        "bestvideo[height<=480]+bestaudio/bestvideo+bestaudio/best"
    )
    assert result.metadata["video_rel"].startswith("attachments/B站/B站-")
    assert result.metadata["video_blob"] == b"480p"


def test_douyin_download_has_no_format_cap(fake_pipeline, monkeypatch):
    """抖音路径不加 format 限高（片源小，行为不变）。"""
    captured = {}

    class _OptsYT(_FakeYoutubeDL):
        def __init__(self, opts):
            super().__init__(opts)
            captured["opts"] = opts

    monkeypatch.setattr(link_module.yt_dlp, "YoutubeDL", _OptsYT)

    result = LinkProcessor().process(SHARE_TEXT)

    assert result.success, result.error
    assert "format" not in captured["opts"]


def test_small_source_kept_original(fake_pipeline, monkeypatch):
    """片源已 ≤480p：跳过重编码直接存原件（省一次有损转码+防胀大）。"""
    monkeypatch.setattr(LinkProcessor, "_probe_height", staticmethod(lambda p: 360))
    compress_calls = []
    monkeypatch.setattr(
        LinkProcessor,
        "_compress_to_480p",
        staticmethod(lambda s, d: compress_calls.append(1) or True),
    )

    result = LinkProcessor().process(SHARE_TEXT)

    assert result.success, result.error
    assert compress_calls == []  # 未调压缩
    assert result.metadata["video_blob"] == b"fake video bytes"  # 原件字节


def test_probe_height_parses_video_stream(monkeypatch, tmp_path):
    """_probe_height：从 ffprobe JSON 取 video 流高度；异常/无流返回 None。"""
    import json as _json

    class _Proc:
        stdout = _json.dumps(
            {"streams": [{"codec_type": "audio"}, {"codec_type": "video", "height": 1080}]}
        )

    monkeypatch.setattr(link_module.subprocess, "run", lambda *a, **k: _Proc())
    assert LinkProcessor._probe_height(tmp_path / "x.mp4") == 1080

    class _BadProc:
        stdout = "not json"

    monkeypatch.setattr(link_module.subprocess, "run", lambda *a, **k: _BadProc())
    assert LinkProcessor._probe_height(tmp_path / "x.mp4") is None


# ---- 方案 B 卡形态（2026-09-12 用户裁决）----


def test_long_body_externalized_to_transcript_rel(fake_pipeline, monkeypatch):
    """正文 >800 字符外置：卡留「## 全文」链接节、无正文小节；
    metadata 交回 transcript_rel/transcript_text（与 480p 视频同主名 .md）。"""
    monkeypatch.setenv("DEEPSEEK_API_KEY", "fake-key")
    long_body = "整理后的长正文。" * 120  # 960 字符
    _branching_llm(monkeypatch, format_text=long_body)

    result = LinkProcessor().process(SHARE_TEXT)

    assert result.success, result.error
    assert "## 转写全文" not in result.markdown
    rel = result.metadata["transcript_rel"]
    assert rel == "attachments/抖音/抖音-信息标题-vid123.md"
    assert f"## 全文\n\n[[{rel}|查看转写全文]]" in result.markdown
    assert result.metadata["transcript_text"] == long_body


def test_short_body_stays_inline(fake_pipeline, monkeypatch):
    """正文 ≤800 字符保持卡内联（卡自含），不交回 transcript。"""
    monkeypatch.setenv("DEEPSEEK_API_KEY", "fake-key")
    _branching_llm(monkeypatch, format_text="整理后第一段。\n\n整理后第二段。")

    result = LinkProcessor().process(SHARE_TEXT)

    assert result.success, result.error
    assert "## 转写全文" in result.markdown
    assert "## 全文" not in result.markdown
    assert result.metadata["transcript_rel"] is None
    assert result.metadata["transcript_text"] is None


def test_body_threshold_boundary(fake_pipeline, monkeypatch):
    """阈值边界：恰好 INLINE_BODY_MAX 内联，+1 外置（阈值单点定义于 base.py）。"""
    from scripts.processors.base import INLINE_BODY_MAX

    monkeypatch.setenv("DEEPSEEK_API_KEY", "fake-key")
    _branching_llm(monkeypatch, format_text="甲" * INLINE_BODY_MAX)
    result = LinkProcessor().process(SHARE_TEXT)
    assert result.metadata["transcript_rel"] is None

    _branching_llm(monkeypatch, format_text="甲" * (INLINE_BODY_MAX + 1))
    result = LinkProcessor().process(SHARE_TEXT)
    assert result.metadata["transcript_rel"] is not None


def test_xhs_long_text_note_externalized(fake_xhs_page, monkeypatch):
    """小红书图文长正文同样外置（body_label=笔记正文），无视频也成立。"""
    long_desc = "长正文。" * 400  # 1600 字符
    fake_xhs_page["note"] = {
        "title": "图文笔记标题",
        "desc": long_desc,
        "type": "normal",
        "noteId": "txt456",
        "user": {"nickName": "某人"},
    }
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)

    result = LinkProcessor().process(XHS_SHARE_TEXT)

    assert result.success, result.error
    assert "## 笔记正文" not in result.markdown
    rel = result.metadata["transcript_rel"]
    assert rel == "attachments/小红书/小红书-图文笔记标题-txt456.md"
    assert f"[[{rel}|查看笔记正文]]" in result.markdown
    assert result.metadata["transcript_text"] == long_desc


# ---- 语义标题兜底与转写去重（2026-09-12） ----


class _MachineTitleYT(_FakeYoutubeDL):
    """假 yt-dlp：返回抖音通用占位标题（2026-09-12 真实样本）。"""

    def extract_info(self, url, download=True):
        super().extract_info(url, download)
        return {
            "id": "vid123",
            "title": "Douyin video #7674839354331095781",
            "uploader": "农人老贾",
        }


def test_machine_title_replaced_by_llm_title(fake_pipeline, monkeypatch):
    """占位标题换 LLM 语义标题；附件主名随新标题（须在 _preserve_video
    之前换）。"""
    monkeypatch.setattr(link_module.yt_dlp, "YoutubeDL", _MachineTitleYT)
    monkeypatch.setenv("DEEPSEEK_API_KEY", "fake-key")
    _fixed_llm(
        monkeypatch, _llm_payload(extra={"title": "经济危机是社会关系的危机"})
    )

    result = LinkProcessor().process(SHARE_TEXT)

    assert result.success, result.error
    assert result.metadata["title"] == "经济危机是社会关系的危机"
    assert result.markdown.startswith("# 经济危机是社会关系的危机\n")
    assert (
        result.metadata["video_rel"]
        == "attachments/抖音/抖音-经济危机是社会关系的危机-vid123.mp4"
    )


def test_real_title_kept_over_llm_title(fake_pipeline, monkeypatch):
    """真实平台标题不被 LLM 标题覆盖。"""
    monkeypatch.setenv("DEEPSEEK_API_KEY", "fake-key")
    _fixed_llm(monkeypatch, _llm_payload(extra={"title": "另一个标题"}))

    result = LinkProcessor().process(SHARE_TEXT)

    assert result.metadata["title"] == "信息标题"
    assert result.markdown.startswith("# 信息标题\n")


def test_machine_title_without_llm_keeps_original(fake_pipeline, monkeypatch):
    """占位标题 + 无 LLM（无 key）：原样保留，下游仍可按 id 兜底命名。"""
    monkeypatch.setattr(link_module.yt_dlp, "YoutubeDL", _MachineTitleYT)

    result = LinkProcessor().process(SHARE_TEXT)

    assert result.success, result.error
    assert result.metadata["title"] == "Douyin video #7674839354331095781"


def test_xhs_empty_title_filled_by_llm(fake_xhs_page, monkeypatch):
    """小红书空标题：LLM 语义标题兜底（图文路径）。"""
    fake_xhs_page["note"] = {**_XHS_NOTE_TEXT, "title": ""}
    monkeypatch.setenv("DEEPSEEK_API_KEY", "fake-key")
    _fixed_llm(monkeypatch, _llm_payload(extra={"title": "图文笔记的语义标题"}))

    result = LinkProcessor().process(XHS_SHARE_TEXT)

    assert result.success, result.error
    assert result.metadata["title"] == "图文笔记的语义标题"
    assert result.markdown.startswith("# 图文笔记的语义标题\n")


def test_is_machine_title():
    """占位标题整串匹配：带不带 #、大小写都算；真实标题不误伤。"""
    assert link_module._is_machine_title("Douyin video #7674839354331095781")
    assert link_module._is_machine_title("douyin video 12345")
    assert not link_module._is_machine_title("Douyin video 教程：三个方法")
    assert not link_module._is_machine_title("")
    assert not link_module._is_machine_title("经济危机是社会关系的危机")


def test_collapse_consecutive_repeats():
    """Whisper 连续重复句折叠：只留第一遍；无重复逐字节不变；
    非相邻重复（讲者真正的反复）保留。"""
    text = (
        "所以它是一种危机。所以它更多的就是一种资源配置上出了差异。"
        "所以它更多的就是一种资源配置上出了差异。"
        "所以它更多的就是一种资源配置上出了差异。如果看到这一点就不用恐慌。"
    )
    collapsed = link_module._collapse_consecutive_repeats(text)
    assert collapsed.count("所以它更多的就是一种资源配置上出了差异。") == 1
    assert "所以它是一种危机。" in collapsed
    assert "如果看到这一点就不用恐慌。" in collapsed

    clean = "第一句。第二句。\n\n第三句。"
    assert link_module._collapse_consecutive_repeats(clean) == clean

    apart = "甲句。乙句。甲句。"
    assert link_module._collapse_consecutive_repeats(apart) == apart


def test_repeats_collapsed_before_llm(fake_pipeline, monkeypatch):
    """重复句折叠发生在 LLM 摘要之前：摘要输入里重复句只剩一遍。"""

    class _RepeatVideo(_FakeVideoProcessor):
        def process(self, path):
            return ProcessResult(
                success=True,
                text="甲句。乙句。乙句。乙句。丙句。",
                markdown="# vid123\n\n- [00:00] 甲句",
                confidence=0.9,
                metadata={"segments": 1},
            )

    monkeypatch.setattr(link_module, "VideoProcessor", _RepeatVideo)
    monkeypatch.setenv("DEEPSEEK_API_KEY", "fake-key")
    prompts = []

    def _post(url, headers=None, json=None, timeout=None):
        prompts.append(json["messages"][0]["content"])
        return _FakeLLMResponse({"choices": [{"message": {"content": ""}}]})

    monkeypatch.setattr(link_module.httpx, "post", _post)

    result = LinkProcessor().process(SHARE_TEXT)

    assert result.success, result.error
    summarize_prompt = next(p for p in prompts if "结构化笔记元数据" in p)
    assert summarize_prompt.count("乙句。") == 1
    format_prompt = next(p for p in prompts if "整理为易读" in p)
    assert format_prompt.count("乙句。") == 1


def test_sanitize_title_strips_topic_tail():
    """2026-09-13 真实样本：「…哲学之路 人文星闪耀计划 用知识解构社会现实」
    ——空格尾段是话题/栏目尾巴，剥掉。"""
    cleaned = link_module._sanitize_title(
        "遇事的第一反应，会暴露每个人的三观，找寻并认识自己的哲学之路 "
        "人文星闪耀计划 用知识解构社会现实"
    )
    assert cleaned == "遇事的第一反应，会暴露每个人的三观，找寻并认识自己的哲学之路"


def test_sanitize_title_strips_hashtags():
    """#话题 片段整个剥掉（不论中间还是结尾）。"""
    assert (
        link_module._sanitize_title("标题本体 #话题一 #话题二") == "标题本体"
    )


def test_sanitize_title_keeps_short_head_with_tail():
    """首段不足 8 字时不丢尾（防误伤：有些标题本来就有空格）。"""
    assert link_module._sanitize_title("短 尾巴保留") == "短 尾巴保留"


def test_sanitize_title_caps_at_30():
    """硬上限 30 字，截断后剥尾部标点。"""
    assert link_module._sanitize_title("一" * 40) == "一" * 30
    assert link_module._sanitize_title("一" * 29 + "，") == "一" * 29
    assert link_module._sanitize_title("") == ""


def test_summarize_caps_points_and_insights(fake_pipeline, monkeypatch):
    """LLM 超契约（9 条分观点/7 条金句）：程序兜底截到 8/5。

    金句须过原文回溯机检——假转写全文是「转写全文」，金句取其
    子串（机检只认逐字出自原文的摘录）。
    """
    monkeypatch.setenv("DEEPSEEK_API_KEY", "fake-key")
    _fixed_llm(
        monkeypatch,
        _llm_payload(
            extra={
                "points": [f"观点{i}。" for i in range(1, 10)],
                "insights": ["转", "写", "全", "文", "转写", "写全", "全文"],
            }
        ),
    )

    result = LinkProcessor().process(SHARE_TEXT)

    assert result.success, result.error
    assert "8. 观点8。" in result.markdown
    assert "9. 观点9。" not in result.markdown
    quote_lines = [
        ln
        for ln in result.markdown.split("## 金句摘录")[1].splitlines()
        if ln.startswith("> ") and "（" not in ln
    ]
    assert len(quote_lines) == 5


def test_topic_tail_title_cleaned_end_to_end(fake_pipeline, monkeypatch):
    """端到端：yt-dlp 标题带 #话题尾 → 文件名/ H1 用清洗后标题（无 LLM 也生效）。"""

    class _TopicTailYT(_FakeYoutubeDL):
        def extract_info(self, url, download=True):
            info = super().extract_info(url, download)
            info["title"] = (
                "遇事的第一反应，会暴露每个人的三观，找寻并认识自己的哲学之路 "
                "#人文星闪耀计划 #用知识解构社会现实"
            )
            return info

    monkeypatch.setattr(link_module.yt_dlp, "YoutubeDL", _TopicTailYT)

    result = LinkProcessor().process(SHARE_TEXT)

    assert result.success, result.error
    assert (
        result.metadata["title"]
        == "遇事的第一反应，会暴露每个人的三观，找寻并认识自己的哲学之路"
    )
    assert "人文星闪耀计划" not in result.metadata["title"]
    assert result.metadata["video_rel"].endswith(
        "抖音-遇事的第一反应，会暴露每个人的三观，找寻并认识自己的哲学之路-vid123.mp4"
    )


def test_insights_fabricated_quote_dropped(fake_pipeline, monkeypatch):
    """金句回溯机检：原文不存在的"金句"被剔除，卡面如实标注剔除数。"""
    monkeypatch.setenv("DEEPSEEK_API_KEY", "fake-key")
    _fixed_llm(
        monkeypatch,
        _llm_payload(extra={"insights": ["转写", "这句原文根本没说过"]}),
    )

    result = LinkProcessor().process(SHARE_TEXT)

    assert result.success, result.error
    assert "## 金句摘录\n\n> 转写\n" in result.markdown
    assert "这句原文根本没说过" not in result.markdown
    assert "1 条候选金句未通过原文回溯校验" in result.markdown


def test_insights_punctuation_normalization(fake_pipeline, monkeypatch):
    """机检对标点/空白宽容（规范化后比对）：金句少标点但文字一致仍通过。"""
    monkeypatch.setenv("DEEPSEEK_API_KEY", "fake-key")
    _fixed_llm(
        monkeypatch,
        _llm_payload(extra={"insights": ["转写全文"]}),  # 原文"转写全文"逐字在
    )

    result = LinkProcessor().process(SHARE_TEXT)

    assert result.success, result.error
    assert "> 转写全文" in result.markdown
    assert "未通过原文回溯校验" not in result.markdown


def test_low_confidence_warning_rendered(fake_pipeline, monkeypatch):
    """转写置信度偏低（<0.70）：卡面加人工回放警告行；正常置信不加。"""

    class _LowConfVideo(_FakeVideoProcessor):
        def process(self, path):
            assert Path(path).exists()
            return ProcessResult(
                success=True,
                text="转写全文",
                markdown="# vid123\n\n## 转写文字\n\n- [00:00] 你好",
                confidence=0.5,
                metadata={"segments": 1},
            )

    monkeypatch.setattr(link_module, "VideoProcessor", _LowConfVideo)
    low = LinkProcessor().process(SHARE_TEXT)
    assert low.success, low.error
    assert "转写置信度 50% 偏低" in low.markdown

    monkeypatch.setattr(link_module, "VideoProcessor", _FakeVideoProcessor)
    normal = LinkProcessor().process(SHARE_TEXT)
    assert normal.success, normal.error
    assert "偏低" not in normal.markdown


def test_bare_category_code_dropped(fake_pipeline, monkeypatch):
    """LLM 给裸编号（G79 无类名）：归档推导不认，程序兜底丢弃（2026-09-14 实证）。"""
    monkeypatch.setenv("DEEPSEEK_API_KEY", "fake-key")
    _fixed_llm(monkeypatch, _llm_payload(extra={"category": "G79"}))

    result = LinkProcessor().process(SHARE_TEXT)

    assert result.success, result.error
    post = frontmatter.loads(result.markdown)
    assert "G79" not in (post.metadata.get("tags") or [])
