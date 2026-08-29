"""三 MVP 集成端到端测试（DEVELOPMENT-PLAN-3MVP.md Week 3 集成清单）。

链路：process_cli 处理图片/PDF → create_note 入库 → decay 分层 →
Flatnotes 可见。只组合现有公共接口，不触碰任何生产代码。

- test_process_to_memory_to_decay_pipeline：纯临时目录，总是能跑。
- test_flatnotes_sees_pipeline_note：live 验证 Flatnotes 可见性，
  docker/.env 缺失或容器未起时 pytest.skip 优雅跳过。
"""
from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

import pytest
from click.testing import CliRunner

from scripts.cli.memory_cli import MemoryCLI
from scripts.cli.process_cli import ProcessCLI
from scripts.memory.core import MemoryTree
from scripts.memory.decay import DecayManager
from scripts.web.integration import FlatnotesIntegration
from tools.generate_test_data import generate_all

FIXTURES_DIR = Path(__file__).resolve().parents[1] / "fixtures"
REPO_ROOT = Path(__file__).resolve().parents[2]
FLATNOTES_BASE = "http://localhost:8080"

#: 夹具中的可识别文本（tools/generate_test_data.py 定义）
OCR_TEXT = "Atelierr OCR test"
PDF_TEXT = "Atelierr PDF test document"


@pytest.fixture(scope="session", autouse=True)
def ensure_fixtures() -> None:
    """session 级：保证端到端夹具存在（幂等生成，复用 generate_all）。"""
    generate_all(FIXTURES_DIR)


def _invoke(cli, runner, args):
    """调用 click 命令并断言成功。"""
    result = runner.invoke(cli, args)
    assert result.exit_code == 0, f"exit={result.exit_code}\n{result.output}"
    return result


def _roll_mtime_back(path: Path, idle_days: int) -> None:
    """把文件 mtime 回拨 idle_days 天（decay 的闲置信号，last_accessed 为空时主信号）。"""
    old_ns = int((time.time() - idle_days * 86400) * 1e9)
    os.utime(path, ns=(old_ns, old_ns))


def _snapshot(path: Path) -> tuple:
    """文件字节与 mtime_ns 快照（衰减不得改动笔记文件）。"""
    return (path.read_bytes(), path.stat().st_mtime_ns)


def test_process_to_memory_to_decay_pipeline(memory_config, tmp_path):
    """process_cli 图片/PDF → create 入库 → search → decay 分层（纯临时目录）。"""
    runner = CliRunner()
    process_cli = ProcessCLI().cli
    notes_dir = tmp_path / "memory"
    state_dir = tmp_path / "state"

    # 1) process_cli 处理图片与 PDF（真实 PaddleOCR / PyMuPDF）
    image_out = tmp_path / "image.md"
    pdf_out = tmp_path / "pdf.md"
    result = _invoke(
        process_cli, runner, ["image", str(FIXTURES_DIR / "test_image.jpg"), "--output", str(image_out)]
    )
    assert "已写入" in result.output
    assert image_out.exists() and image_out.stat().st_size > 0
    image_markdown = image_out.read_text(encoding="utf-8")
    assert OCR_TEXT in image_markdown

    result = _invoke(
        process_cli, runner, ["pdf", str(FIXTURES_DIR / "test.pdf"), "--output", str(pdf_out)]
    )
    assert "已写入" in result.output
    assert pdf_out.exists() and pdf_out.stat().st_size > 0
    pdf_markdown = pdf_out.read_text(encoding="utf-8")
    assert PDF_TEXT in pdf_markdown

    # 2) create 入库（--content 读处理输出文件），断言根层 + short-term
    memory_cli = MemoryCLI(config_path=str(memory_config)).cli
    _invoke(memory_cli, runner, ["create", "img-note.md", "--content", image_markdown])
    _invoke(memory_cli, runner, ["create", "pdf-note.md", "--content", pdf_markdown])
    img_note = notes_dir / "img-note.md"
    pdf_note = notes_dir / "pdf-note.md"
    assert img_note.parent == notes_dir  # Flatnotes 挂载的就是这个平面目录
    assert pdf_note.parent == notes_dir
    tree = MemoryTree(str(notes_dir), state_dir=str(state_dir))
    assert tree.layer_of(img_note) == "short-term"
    assert tree.layer_of(pdf_note) == "short-term"

    # 3) search 按 OCR 文本 / PDF 文本命中
    result = _invoke(memory_cli, runner, ["search", OCR_TEXT])
    assert "img-note.md" in result.output
    result = _invoke(memory_cli, runner, ["search", PDF_TEXT])
    assert "pdf-note.md" in result.output

    # 4) 回拨 mtime：图片 10 天 → mid-term；PDF 60 天 → pending_delete
    _roll_mtime_back(img_note, 10)
    _roll_mtime_back(pdf_note, 60)
    before = {img_note: _snapshot(img_note), pdf_note: _snapshot(pdf_note)}

    result = _invoke(memory_cli, runner, ["decay"])
    assert "pdf-note.md" in result.output  # 待删除清单
    assert "img-note.md" not in result.output  # 图片笔记未进待删

    # 5) 分层断言（新实例避免 sidecar 缓存）
    tree_after = MemoryTree(str(notes_dir), state_dir=str(state_dir))
    assert tree_after.layer_of(img_note) == "mid-term"
    assert tree_after.is_pending_delete(pdf_note)
    assert pdf_note.exists()  # pending_delete 只标记不删文件

    # 6) 衰减绝不改动笔记：bytes 与 mtime_ns 完全不变
    for path in (img_note, pdf_note):
        assert _snapshot(path) == before[path], f"decay 不应改动 {path.name}"

    # 7) 全程笔记始终位于根层
    assert img_note.parent == notes_dir
    assert pdf_note.parent == notes_dir


def _flatnotes_env_path() -> Path:
    return REPO_ROOT / "docker" / ".env"


def _read_flatnotes_credentials() -> dict:
    """从 docker/.env 解析 Flatnotes 认证配置（值不打印）。"""
    creds = {}
    for line in _flatnotes_env_path().read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            creds[key.strip()] = value.strip().strip('"').strip("'")
    return {
        "username": creds.get("FLATNOTES_USERNAME", "admin"),
        "password": creds.get("FLATNOTES_PASSWORD"),
    }


def _flatnotes_reachable(timeout: float = 3.0) -> bool:
    """Flatnotes 容器是否可达（超时/拒绝 → 视为未运行）。"""
    try:
        with urllib.request.urlopen(FLATNOTES_BASE + "/", timeout=timeout) as response:
            return response.status == 200
    except (urllib.error.URLError, OSError, TimeoutError):
        return False


def _flatnotes_get_json(path: str, token: str):
    """Bearer 认证的 Flatnotes GET，返回 (status, json)。"""
    request = urllib.request.Request(
        FLATNOTES_BASE + path, headers={"Authorization": f"Bearer {token}"}
    )
    with urllib.request.urlopen(request, timeout=10) as response:
        return response.status, json.loads(response.read().decode("utf-8"))


def test_flatnotes_sees_pipeline_note(tmp_path):
    """live：process_cli 图片输出经 create_note 入库后 Flatnotes 可见。

    decay 后仍可见且内容不变（layer 是 sidecar 属性，不影响 Flatnotes）。
    teardown 只删除本测试创建的文件并注销其 sidecar 条目。
    """
    if not _flatnotes_env_path().exists():
        pytest.skip("docker/.env 不存在，跳过 Flatnotes live 验证")
    if not _flatnotes_reachable():
        pytest.skip("Flatnotes 容器未运行（http://localhost:8080 不可达）")

    tree = MemoryTree(
        os.path.expanduser("~/atelierr-data/memory"),
        state_dir=os.path.expanduser("~/atelierr-data/state"),
    )
    integration = FlatnotesIntegration(tree)
    integration.process_pending()  # 先对齐真实数据目录

    unique = f"e2e-pipeline-{time.time_ns()}"
    note_path = tree.notes_dir / f"{unique}.md"
    try:
        # process_cli 图片输出 → create_note 入库（根层）
        image_out = tmp_path / "e2e-image.md"
        result = CliRunner().invoke(
            ProcessCLI().cli,
            ["image", str(FIXTURES_DIR / "test_image.jpg"), "--output", str(image_out)],
        )
        assert result.exit_code == 0, f"exit={result.exit_code}\n{result.output}"
        markdown = image_out.read_text(encoding="utf-8")
        assert OCR_TEXT in markdown
        created = tree.create_note(f"{unique}.md", markdown)
        assert created == note_path
        assert note_path.parent == tree.notes_dir

        # 登录 Flatnotes 拿 token
        creds = _read_flatnotes_credentials()
        assert creds["password"], "docker/.env 缺少 FLATNOTES_PASSWORD"
        login = urllib.request.Request(
            FLATNOTES_BASE + "/api/token",
            data=json.dumps(
                {"username": creds["username"], "password": creds["password"]}
            ).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(login, timeout=10) as response:
            token = json.loads(response.read().decode("utf-8"))["access_token"]

        # GET /api/notes/{title}：200 且内容包含 OCR 文本
        status, body = _flatnotes_get_json(f"/api/notes/{urllib.parse.quote(unique)}", token)
        assert status == 200, f"Flatnotes 应能看到 {unique}，status={status}"
        assert OCR_TEXT in body.get("content", ""), "Flatnotes 内容应包含 OCR 文本"

        # decay 后再查：仍可见且内容不变
        DecayManager(tree).run()
        status_after, body_after = _flatnotes_get_json(
            f"/api/notes/{urllib.parse.quote(unique)}", token
        )
        assert status_after == 200, "decay 后 Flatnotes 仍应可见"
        assert body_after.get("content") == body.get("content"), "decay 不应改变笔记内容"
    finally:
        # 只清理本测试自己的产物：删文件 + process_pending 注销 sidecar 条目
        if note_path.exists():
            note_path.unlink()
        integration.process_pending()
