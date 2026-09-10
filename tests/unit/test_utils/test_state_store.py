"""state_store 原子 JSON 读写单元测试。"""

from __future__ import annotations

from scripts.utils.state_store import read_json, write_json


def test_write_then_read_roundtrip(tmp_path):
    """写入后可读回；父目录自动创建。"""
    path = tmp_path / "sub" / "state.json"
    write_json(path, {"a": 1, "中文": "值"}, indent=2)
    assert read_json(path) == {"a": 1, "中文": "值"}


def test_read_missing_returns_default(tmp_path):
    """文件缺失返回 default（不抛异常）。"""
    assert read_json(tmp_path / "nope.json") is None
    assert read_json(tmp_path / "nope.json", {}) == {}
    assert read_json(tmp_path / "nope.json", []) == []


def test_read_corrupt_returns_default(tmp_path):
    """损坏文件返回 default（状态损坏按无状态处理）。"""
    path = tmp_path / "bad.json"
    path.write_text("not json{", encoding="utf-8")
    assert read_json(path, {}) == {}


def test_write_is_atomic_no_tmp_left(tmp_path):
    """写完后目录无临时文件残留。"""
    path = tmp_path / "s.json"
    write_json(path, [1, 2, 3])
    assert [p.name for p in tmp_path.iterdir()] == ["s.json"]


def test_write_compact_by_default(tmp_path):
    """缺省紧凑单行；indent=2 时格式化。"""
    path = tmp_path / "s.json"
    write_json(path, {"a": 1})
    assert "\n" not in path.read_text(encoding="utf-8")
    write_json(path, {"a": 1}, indent=2)
    assert "\n" in path.read_text(encoding="utf-8")
