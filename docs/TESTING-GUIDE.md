# Atelierr 测试与验收指南

**版本**: v1.0  
**日期**: 2026-08-28  
**状态**: 🔒 已锁定

---

## 📋 快速开始

### 开发前验证

```bash
# 1. 验证安装
python3 tools/verify_installation.py

期望结果:
  ✅ Python 版本: 3.8+
  ✅ 目录结构: 完整
  ✅ 配置文件: 齐全
  ⚠️  依赖包: 待安装
  ⚠️  模块导入: 待开发

# 2. 安装依赖
python3 -m venv .venv-atelierr  # 独立环境，勿用 .venv（Atelier 框架专用）
source .venv-atelierr/bin/activate
pip install -r requirements.txt

# 3. 再次验证
python3 tools/verify_installation.py

期望结果:
  ✅ 所有基础检查通过
```

### 开发中验证

```bash
# 每完成一个模块后运行

# 1. 单元测试
pytest tests/unit/test_memory/ -v

# 2. 代码格式
black scripts/memory/
isort scripts/memory/

# 3. 类型检查
mypy scripts/memory/

# 4. 代码质量
pylint scripts/memory/
```

### MVP 验收（Week 1 结束）

```bash
# 1. 完整测试套件
pytest --cov=scripts --cov-report=html --cov-report=term

期望:
  ✅ 测试通过率 = 100%
  ✅ 覆盖率 ≥ 80%

# 2. 运行验收测试
python3 tools/acceptance_test.py

期望:
  ✅ 所有模块验收通过

# 3. 启动系统
docker-compose up -d

期望:
  ✅ Flatnotes 可访问: http://localhost:8080
  ✅ 所有服务正常
```

---

## 🧪 测试分层

### 1. 单元测试（Unit Tests）

**位置**: `tests/unit/`

**目的**: 测试单个函数/类的行为

**示例**:

```python
# tests/unit/test_memory/test_core.py

import pytest
from scripts.memory.core import MemoryTree

def test_memory_tree_init(tmp_path):
    """测试 MemoryTree 初始化"""
    tree = MemoryTree(str(tmp_path))
    
    assert tree.root_path == tmp_path
    assert tree.short_term.exists()
    assert tree.mid_term.exists()
    assert tree.long_term.exists()

def test_create_note(tmp_path):
    """测试创建笔记"""
    tree = MemoryTree(str(tmp_path))
    note_path = tree.create_note("test.md", "内容")
    
    assert note_path.exists()
    assert note_path.parent == tree.short_term
    assert note_path.read_text() == "内容"
```

**运行**:

```bash
# 运行所有单元测试
pytest tests/unit/ -v

# 运行特定模块
pytest tests/unit/test_memory/ -v

# 运行特定测试
pytest tests/unit/test_memory/test_core.py::test_memory_tree_init -v

# 带覆盖率
pytest tests/unit/ --cov=scripts/memory --cov-report=term
```

### 2. 集成测试（Integration Tests）

**位置**: `tests/integration/`

**目的**: 测试模块间的交互

**示例**:

```python
# tests/integration/test_memory_web.py

import pytest
from scripts.memory.core import MemoryTree
from scripts.web.integration import FlatnotesIntegration

def test_note_sync(tmp_path):
    """测试笔记同步"""
    # 初始化
    memory = MemoryTree(str(tmp_path / "memory"))
    flatnotes = FlatnotesIntegration(str(tmp_path / "flatnotes"))
    
    # 在 Flatnotes 创建笔记
    flatnotes.create_note("test.md", "内容")
    
    # 触发同步
    flatnotes.sync_to_memory(memory)
    
    # 验证笔记出现在记忆模块
    assert memory.note_exists("test.md")
```

**运行**:

```bash
pytest tests/integration/ -v
```

### 3. 端到端测试（E2E Tests）

**位置**: `tests/e2e/`

**目的**: 测试完整用户场景

**示例**:

```python
# tests/e2e/test_image_to_memory.py

import pytest
from scripts.processors.image import ImageProcessor
from scripts.memory.core import MemoryTree

def test_image_ocr_to_memory(tmp_path):
    """测试图片 OCR 到记忆模块的完整流程"""
    # 1. 初始化
    processor = ImageProcessor()
    memory = MemoryTree(str(tmp_path))
    
    # 2. 处理图片
    result = processor.process("tests/fixtures/test_image.jpg")
    
    # 3. 保存到记忆模块
    note_path = memory.create_note(
        "ocr_result.md",
        result.to_markdown()
    )
    
    # 4. 验证
    assert note_path.exists()
    content = note_path.read_text()
    assert "# OCR 结果" in content
    assert len(content) > 100
```

**运行**:

```bash
pytest tests/e2e/ -v
```

### 4. 性能测试（Performance Tests）

**位置**: `tests/performance/`

**目的**: 验证性能指标

**示例**:

```python
# tests/performance/test_search_performance.py

import pytest
import time
from scripts.memory.core import MemoryTree
from scripts.memory.search import MemorySearcher

def test_search_1000_notes_performance(tmp_path):
    """测试 1000 个笔记的搜索性能"""
    # 创建 1000 个测试笔记
    memory = MemoryTree(str(tmp_path))
    for i in range(1000):
        memory.create_note(f"note_{i}.md", f"content {i}")
    
    # 测试搜索性能
    searcher = MemorySearcher(memory)
    
    start = time.time()
    results = searcher.search("content")
    elapsed = time.time() - start
    
    # 验证性能要求: < 100ms
    assert elapsed < 0.1, f"搜索耗时 {elapsed:.3f}s，超过 100ms"
    assert len(results) > 0
```

**运行**:

```bash
pytest tests/performance/ -v
```

---

## 📊 测试覆盖率

### 目标

```
总体覆盖率: ≥ 80%

核心模块: ≥ 90%
  - scripts/memory/core.py
  - scripts/memory/confidence.py
  - scripts/memory/decay.py

关键函数: 100%
  - 所有数据写入函数
  - 所有文件移动函数
  - Confidence 计算函数
```

### 查看覆盖率

```bash
# 生成覆盖率报告
pytest --cov=scripts --cov-report=html --cov-report=term

# 查看 HTML 报告
open htmlcov/index.html

# 查看特定模块
pytest --cov=scripts/memory --cov-report=term
```

### 覆盖率报告示例

```
Name                              Stmts   Miss  Cover
-----------------------------------------------------
scripts/__init__.py                   0      0   100%
scripts/memory/__init__.py            2      0   100%
scripts/memory/core.py               85      8    91%
scripts/memory/confidence.py         45      2    96%
scripts/memory/decay.py              67      5    93%
scripts/memory/search.py             52      8    85%
-----------------------------------------------------
TOTAL                               251     23    91%
```

---

## ✅ 验收检查清单

### Week 1 MVP 验收

**Day 7 执行验收**:

```bash
# 1. 安装验证
python3 tools/verify_installation.py
期望: ✅ 所有检查通过

# 2. 单元测试
pytest tests/unit/ -v
期望: ✅ 通过率 100%

# 3. 测试覆盖率
pytest --cov=scripts --cov-report=term
期望: ✅ 覆盖率 ≥ 80%

# 4. 代码质量
black --check scripts/
mypy scripts/
pylint scripts/
期望: ✅ 无错误

# 5. 验收测试
python3 tools/acceptance_test.py
期望: ✅ 所有模块通过

# 6. 系统部署
docker-compose up -d
期望: ✅ 所有服务启动

# 7. 功能演示
# 手动创建笔记、搜索、OCR 测试
期望: ✅ 核心功能可用
```

### Week 2 完整版验收（可选）

```bash
# 1-6 同 Week 1

# 7. 集成测试
pytest tests/integration/ -v
期望: ✅ 通过率 100%

# 8. 端到端测试
pytest tests/e2e/ -v
期望: ✅ 通过率 100%

# 9. 性能测试
pytest tests/performance/ -v
期望: ✅ 所有性能指标达标

# 10. 负载测试
python tools/load_test.py
期望: ✅ 系统稳定
```

---

## 🔧 测试工具使用

### pytest 常用命令

```bash
# 运行所有测试
pytest

# 详细输出
pytest -v

# 只运行失败的测试
pytest --lf

# 停在第一个失败
pytest -x

# 显示打印输出
pytest -s

# 并行运行（需要 pytest-xdist）
pytest -n auto

# 运行特定标记的测试
pytest -m "slow"

# 运行匹配名称的测试
pytest -k "test_create"
```

### 测试标记（Markers）

```python
# tests/conftest.py

import pytest

def pytest_configure(config):
    config.addinivalue_line("markers", "slow: 慢速测试")
    config.addinivalue_line("markers", "integration: 集成测试")
    config.addinivalue_line("markers", "e2e: 端到端测试")

# 使用标记
@pytest.mark.slow
def test_large_file_processing():
    pass

@pytest.mark.integration
def test_memory_web_sync():
    pass
```

```bash
# 运行除慢速测试外的所有测试
pytest -m "not slow"

# 只运行集成测试
pytest -m integration
```

### Fixtures

```python
# tests/conftest.py

import pytest
from pathlib import Path
from scripts.memory.core import MemoryTree

@pytest.fixture
def temp_memory(tmp_path):
    """提供临时记忆目录"""
    return MemoryTree(str(tmp_path))

@pytest.fixture
def sample_notes(temp_memory):
    """创建示例笔记"""
    notes = []
    for i in range(5):
        note = temp_memory.create_note(
            f"note_{i}.md",
            f"这是笔记 {i} 的内容"
        )
        notes.append(note)
    return notes

# 使用 fixture
def test_with_sample_notes(sample_notes):
    assert len(sample_notes) == 5
```

---

## 📝 测试最佳实践

### 1. 测试命名

```python
# ✅ 好的命名
def test_create_note_saves_to_short_term():
    pass

def test_confidence_decreases_with_time():
    pass

def test_search_returns_empty_list_when_no_matches():
    pass

# ❌ 差的命名
def test_1():
    pass

def test_function():
    pass
```

### 2. 测试结构（AAA 模式）

```python
def test_move_note_to_mid_term():
    # Arrange（准备）
    memory = MemoryTree("/tmp/test")
    note = memory.create_note("test.md", "content")
    
    # Act（执行）
    new_path = memory.move_note(note, "mid-term")
    
    # Assert（断言）
    assert new_path.parent == memory.mid_term
    assert not note.exists()
```

### 3. 一个测试一个断言（推荐）

```python
# ✅ 好的做法
def test_note_saved_to_short_term():
    note = memory.create_note("test.md", "content")
    assert note.parent == memory.short_term

def test_note_has_correct_content():
    note = memory.create_note("test.md", "content")
    assert note.read_text() == "content"

# ⚠️ 可以接受（相关断言）
def test_create_note():
    note = memory.create_note("test.md", "content")
    assert note.exists()
    assert note.parent == memory.short_term
    assert note.read_text() == "content"
```

### 4. 测试边界条件

```python
def test_confidence_edge_cases():
    """测试 Confidence 边界条件"""
    calc = ConfidenceCalculator()
    
    # 最小值
    assert calc.calculate(very_old_note) >= 0.0
    
    # 最大值
    assert calc.calculate(brand_new_note) <= 1.0
    
    # 空笔记
    assert calc.calculate(empty_note) > 0.0
```

### 5. 使用参数化测试

```python
@pytest.mark.parametrize("input_format,expected_ext", [
    ("jpg", ".jpg"),
    ("png", ".png"),
    ("webp", ".webp"),
])
def test_image_formats(input_format, expected_ext):
    processor = ImageProcessor()
    result = processor.process(f"test.{input_format}")
    assert result.success
```

---

## 🎯 验收标准总结

### 必须满足（MVP）

```
✅ 单元测试通过率 = 100%
✅ 测试覆盖率 ≥ 80%
✅ 核心功能可演示
✅ 代码质量检查通过
✅ 系统可部署
```

### 推荐满足（完整版）

```
✅ 集成测试通过
✅ 端到端测试通过
✅ 性能测试达标
✅ 测试覆盖率 ≥ 85%
✅ 文档完整
```

---

## 📚 参考文档

- [pytest 官方文档](https://docs.pytest.org/)
- [测试驱动开发（TDD）](https://en.wikipedia.org/wiki/Test-driven_development)
- [Python 测试最佳实践](https://docs.python-guide.org/writing/tests/)

---

**测试是质量的保证。没有测试，就没有信心。**
