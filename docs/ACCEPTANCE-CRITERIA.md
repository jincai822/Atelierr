# Atelierr 验收标准与测试规范

**版本**: v1.0  
**状态**: 🔒 已锁定  
**日期**: 2026-08-28

---

## 📋 文档说明

本文档定义了 Atelierr 系统的**完整验收标准**，包括：

1. **功能验收标准** - 每个模块必须实现的功能
2. **测试要求** - 单元测试、集成测试、端到端测试
3. **性能标准** - 响应时间、吞吐量、资源使用
4. **代码质量标准** - 代码规范、文档、可维护性
5. **验收流程** - 如何验证系统是否符合要求

---

## 🎯 总体验收标准

### MVP 验收条件（Week 1结束时）

```
✅ 功能完整性
  - 记忆模块核心功能可用
  - Web 界面可访问
  - 至少支持 2 种输入格式（图片 + PDF）
  
✅ 测试覆盖率
  - 单元测试覆盖率 ≥ 80%
  - 核心功能有集成测试
  - 至少 1 个端到端测试通过
  
✅ 文档完整性
  - README 有快速开始指南
  - 核心 API 有文档
  - 配置文件有注释
  
✅ 可部署性
  - Docker Compose 一键启动
  - 初始化脚本可执行
  - 示例数据可运行
```

### 完整版验收条件（Week 2结束时，可选）

```
✅ 功能完整性
  - 输入格式支持：图片/视频/音频/PDF
    （微信处理器移入 backlog：导出格式不稳定且无官方规范，
     不作为任何版本的验收条件）
  - CLI 工具完整
  - 批量处理可用
  
✅ 测试覆盖率
  - 单元测试覆盖率 ≥ 85%
  - 集成测试覆盖核心流程
  - 端到端测试覆盖主要场景
  
✅ 性能达标
  - 满足全部性能指标
  - 通过负载测试
  - 资源使用合理
  
✅ 代码质量（完整版才作为硬门槛）
  - mypy / pylint / flake8 无错误
  - Black + isort 格式一致
  
✅ 生产就绪
  - 日志完善
  - 错误处理健全
  - 配置灵活
```

> **验收分级说明**：MVP 门槛 = 功能完整 + 核心测试 + 性能冒烟
> （创建/搜索/衰减三项即可）+ 可部署。本文档"代码质量标准"一节的
> mypy/pylint 全绿与完整性能矩阵属于**完整版**门槛，MVP 阶段仅作参考。

---

## 📦 模块验收标准

### 模块 1: 记忆模块 (scripts/memory/)

#### 1.1 MemoryTree (core.py)

**功能要求**:

```python
✅ 必须实现（架构 v1.2：平面存储 + sidecar 索引）:
  - 初始化平面笔记目录与 sidecar 状态目录
  - 创建新笔记（平面根层，写一次性 frontmatter，登记 sidecar）
  - 读取笔记内容
  - 覆写笔记的逻辑层级（只写 sidecar，不移动文件）
  - 按逻辑层级列出笔记
  
✅ 错误处理:
  - 目录不存在时自动创建
  - 文件不存在时抛出明确异常
  - 无效路径时给出清晰提示
```

**测试要求**:

```python
# tests/unit/test_memory/test_core.py

def test_memory_tree_init():
    """测试初始化：平面笔记目录 + sidecar 状态目录"""
    tree = MemoryTree("/tmp/test")
    assert tree.notes_dir.exists()
    assert tree.state_dir.exists()

def test_create_note():
    """测试创建笔记：文件在平面根层，sidecar 登记为 short-term"""
    tree = MemoryTree("/tmp/test")
    note_path = tree.create_note("测试笔记.md", "这是内容")
    assert note_path.exists()
    assert note_path.parent == tree.notes_dir
    assert tree.layer_of(note_path) == "short-term"

def test_move_note():
    """测试层级覆写：sidecar 变化，文件不动"""
    tree = MemoryTree("/tmp/test")
    note = tree.create_note("test.md", "content")
    tree.move_note(note, "mid-term")
    assert tree.layer_of(note) == "mid-term"
    assert note.exists()  # 文件位置不变

def test_list_notes():
    """测试按层级列出笔记"""
    tree = MemoryTree("/tmp/test")
    tree.create_note("note1.md", "content1")
    tree.create_note("note2.md", "content2")
    notes = tree.list_notes("short-term")
    assert len(notes) == 2

def test_invalid_path():
    """测试无效路径"""
    tree = MemoryTree("/tmp/test")
    with pytest.raises(FileNotFoundError):
        tree.read_note("/non/existent/path.md")
```

**验收检查**:

```bash
# 运行测试
pytest tests/unit/test_memory/test_core.py -v

# 期望输出:
test_memory_tree_init PASSED
test_create_note PASSED
test_move_note PASSED
test_list_notes PASSED
test_invalid_path PASSED

✅ 5/5 tests passed
```

#### 1.2 Confidence 计算 (confidence.py)

**功能要求**:

```python
✅ 必须实现（架构 v1.2：无状态纯函数）:
  - conf = decay_rate ** (idle_days / ref_factor)，范围 [0.0, 1.0]
  - idle_days 取最后访问与最后修改的较新者
  - 引用因素为乘性：ref_factor = 1 + 0.2 * min(references, 10)
  - 幂等：同一元数据任何时刻重算结果一致
  - 衰减率与引用系数可配置（config/memory.yaml）
  
✅ 边界条件:
  - 新创建的笔记: confidence = 1.0
  - 从未访问/修改的笔记: confidence 单调下降
  - 返回值必须在 [0.0, 1.0] 范围内
```

**测试要求**:

```python
# tests/unit/test_memory/test_confidence.py

def test_new_note_confidence():
    """新笔记 confidence = 1.0"""
    calc = ConfidenceCalculator()
    conf = calc.calculate(metadata={
        "created": datetime.now(),
        "accessed": datetime.now(),
        "modified": datetime.now(),
    })
    assert conf == 1.0

def test_old_note_confidence():
    """旧笔记 confidence 下降"""
    calc = ConfidenceCalculator()
    old_date = datetime.now() - timedelta(days=100)
    conf = calc.calculate(metadata={
        "created": old_date,
        "accessed": old_date,
        "modified": old_date,
    })
    assert 0.0 <= conf < 0.5

def test_referenced_note_decays_slower():
    """被引用的笔记比同龄未引用笔记衰减慢（相对断言）"""
    calc = ConfidenceCalculator()
    old_date = datetime.now() - timedelta(days=50)
    base = {"created": old_date, "accessed": old_date, "modified": old_date}
    conf_plain = calc.calculate(metadata=base)
    conf_referenced = calc.calculate(metadata={**base, "references": 10})
    assert conf_referenced > conf_plain
    # ref_factor=3 ⇒ 等效闲置 50/3 天，应仍在 mid-term 以上
    assert conf_referenced > 0.4

def test_idempotent():
    """纯函数：重复计算结果一致"""
    calc = ConfidenceCalculator()
    meta = {"created": datetime.now() - timedelta(days=10),
            "accessed": datetime.now() - timedelta(days=10),
            "modified": datetime.now() - timedelta(days=10)}
    assert calc.calculate(metadata=meta) == calc.calculate(metadata=meta)

def test_confidence_range():
    """Confidence 必须在 [0, 1] 范围"""
    calc = ConfidenceCalculator()
    for _ in range(100):
        random_metadata = generate_random_metadata()
        conf = calc.calculate(metadata=random_metadata)
        assert 0.0 <= conf <= 1.0
```

**验收检查**:

```bash
pytest tests/unit/test_memory/test_confidence.py -v
✅ 所有测试通过
```

#### 1.3 自动衰减 (decay.py)

**功能要求**:

```python
✅ 必须实现（架构 v1.2：只写 sidecar，绝不改动笔记文件）:
  - 全量扫描 [[wikilink]] 反链，更新 references
  - 无状态重算所有笔记的 confidence
  - 根据 confidence 更新 sidecar 中的逻辑层级
  - 生成衰减报告（层级迁移 + 待删除清单，写入 <state_dir>/reports/）
  - 支持 dry-run 模式（只报告，不写 sidecar）
  
✅ 分层/标记规则:
  - confidence ≥ 0.7: short-term
  - 0.4 ≤ confidence < 0.7: mid-term
  - confidence < 0.4: long-term
  - confidence < 0.1: 置 pending_delete（不自动删除；
    由 memory_cli review → purge 移入 <state_dir>/trash/）
```

**测试要求**:

```python
# tests/unit/test_memory/test_decay.py

def test_decay_scan():
    """测试衰减扫描"""
    decay = DecayManager(memory_tree)
    report = decay.scan()
    
    assert "total_notes" in report
    assert "short_term" in report
    assert "mid_term" in report
    assert "long_term" in report

def test_decay_relayer():
    """测试衰减重分层：sidecar 层级变化，文件不动"""
    note = create_test_note(idle_days=10)  # 重算后 conf ≈ 0.6
    
    decay = DecayManager(memory_tree)
    decay.run()
    
    assert note in memory_tree.list_notes("mid-term")
    assert note.exists()  # 文件仍在平面根层

def test_decay_never_touches_files():
    """衰减前后笔记内容与 mtime 完全不变"""
    note = create_test_note(idle_days=30)
    before = (note.read_bytes(), note.stat().st_mtime_ns)
    
    DecayManager(memory_tree).run()
    
    assert (note.read_bytes(), note.stat().st_mtime_ns) == before

def test_decay_dry_run():
    """测试 dry-run 模式"""
    note = create_test_note(idle_days=10)
    
    decay = DecayManager(memory_tree)
    report = decay.run(dry_run=True)
    
    # sidecar 未变化
    assert note in memory_tree.list_notes("short-term")
    # 但报告显示将会重分层
    assert report["would_relayer"] > 0

def test_pending_delete_is_mark_only():
    """conf < 0.1 只打标记，文件仍存在"""
    note = create_test_note(idle_days=60)
    
    DecayManager(memory_tree).run()
    
    assert note.exists()
    assert memory_tree.is_pending_delete(note)
```

**验收检查**:

```bash
pytest tests/unit/test_memory/test_decay.py -v
✅ 所有测试通过
```

#### 1.4 搜索功能 (search.py)

**功能要求**:

```python
✅ 必须实现:
  - 全文搜索（标题 + 内容）
  - 标签搜索
  - 日期范围搜索
  - 组合搜索（AND/OR）
  - 结果按 confidence 排序
  
✅ 性能要求:
  - 1000 个笔记内搜索 < 100ms
  - 支持增量索引
```

**测试要求**:

```python
# tests/unit/test_memory/test_search.py

def test_full_text_search():
    """全文搜索"""
    searcher = MemorySearcher(memory_tree)
    results = searcher.search("Python")
    assert len(results) > 0
    assert all("Python" in r.content or "Python" in r.title 
               for r in results)

def test_tag_search():
    """标签搜索"""
    searcher = MemorySearcher(memory_tree)
    results = searcher.search(tags=["编程", "AI"])
    assert all(any(tag in r.tags for tag in ["编程", "AI"]) 
               for r in results)

def test_date_range_search():
    """日期范围搜索"""
    searcher = MemorySearcher(memory_tree)
    results = searcher.search(
        date_from="2026-01-01",
        date_to="2026-12-31"
    )
    assert all("2026" in str(r.created) for r in results)

def test_search_performance():
    """搜索性能测试"""
    # 创建 1000 个测试笔记
    create_test_notes(count=1000)
    
    searcher = MemorySearcher(memory_tree)
    start = time.time()
    results = searcher.search("test")
    elapsed = time.time() - start
    
    assert elapsed < 0.1  # 必须 < 100ms
```

**验收检查**:

```bash
pytest tests/unit/test_memory/test_search.py -v
pytest tests/performance/test_search_performance.py -v
✅ 所有测试通过 + 性能达标
```

---

### 模块 2: Web 界面 (scripts/web/)

#### 2.1 Flatnotes 集成 (integration.py)

**功能要求**:

```python
✅ 必须实现（架构 v1.2：Flatnotes 与记忆模块共享同一平面目录，
   不存在"同步"，集成的职责是"归一化"）:
  - watcher 监控笔记目录的新文件 / 删除事件
  - 新文件归一化：补写一次性 frontmatter（id/title/created/source）
    并登记 sidecar（confidence = 1.0, layer = short-term）
  - 文件被外部删除时清理对应 sidecar 条目
  - 归一化必须保持文件 mtime 不变（os.utime 还原），
    避免污染衰减的 modified 信号
  
✅ 错误处理:
  - Flatnotes 未启动不影响归一化（纯文件系统操作）
  - frontmatter 损坏的文件跳过并记录日志，不中断 watcher
```

**测试要求**:

```python
# tests/integration/test_web_integration.py

def test_new_file_normalized():
    """外部（Flatnotes/Obsidian）新建的笔记被登记"""
    # 模拟 Flatnotes：直接往共享目录写裸 markdown
    (memory_tree.notes_dir / "test.md").write_text("content")
    
    watcher.process_pending()  # 或等待 watcher 周期
    
    assert memory_tree.layer_of(memory_tree.notes_dir / "test.md") == "short-term"

def test_normalize_preserves_mtime():
    """归一化补写 frontmatter 后 mtime 不变"""
    note = memory_tree.notes_dir / "raw.md"
    note.write_text("content")
    before = note.stat().st_mtime_ns
    
    watcher.process_pending()
    
    assert note.stat().st_mtime_ns == before

def test_created_note_visible_to_flatnotes():
    """记忆模块创建的笔记就在共享目录根层（Flatnotes 可直接见）"""
    path = memory_tree.create_note("from_memory.md", "content")
    assert path.parent == memory_tree.notes_dir
```

**验收检查**:

```bash
# 启动 Flatnotes
docker-compose up -d flatnotes

# 运行集成测试
pytest tests/integration/test_web_integration.py -v

✅ 所有测试通过
```

---

### 模块 3: 输入处理 (scripts/processors/)

#### 3.1 图片处理 (image.py)

**功能要求**:

```python
✅ 必须实现:
  - 支持 JPG, PNG, WEBP 格式
  - OCR 文字提取（PaddleOCR）
  - 生成 Markdown 格式输出
  - 保留原图链接
  
✅ 性能要求:
  - 单张图片处理 < 5s
  - 批量处理支持并行
```

**测试要求**:

```python
# tests/unit/test_processors/test_image.py

def test_image_ocr():
    """测试图片 OCR"""
    processor = ImageProcessor()
    result = processor.process("test_image.jpg")
    
    assert result.text != ""
    assert result.confidence > 0.0
    assert result.markdown.startswith("# ")

def test_image_formats():
    """测试多种格式"""
    processor = ImageProcessor()
    
    for fmt in ["jpg", "png", "webp"]:
        result = processor.process(f"test.{fmt}")
        assert result.success

def test_image_performance():
    """测试处理性能"""
    processor = ImageProcessor()
    
    start = time.time()
    processor.process("test_image.jpg")
    elapsed = time.time() - start
    
    assert elapsed < 5.0  # 必须 < 5s
```

**验收检查**:

```bash
pytest tests/unit/test_processors/test_image.py -v
pytest tests/performance/test_image_performance.py -v
✅ 所有测试通过 + 性能达标
```

#### 3.2 PDF 处理 (pdf.py)

**功能要求**:

```python
✅ 必须实现:
  - 文字提取（PyMuPDF）
  - 图片提取并 OCR
  - 保留文档结构（标题、段落）
  - 生成目录
  
✅ 性能要求:
  - 10 页 PDF < 30s
  - 支持大文件（>100MB）
```

**测试要求**:

```python
# tests/unit/test_processors/test_pdf.py

def test_pdf_text_extraction():
    """测试 PDF 文字提取"""
    processor = PDFProcessor()
    result = processor.process("test.pdf")
    
    assert len(result.text) > 0
    assert result.page_count > 0

def test_pdf_with_images():
    """测试带图片的 PDF"""
    processor = PDFProcessor()
    result = processor.process("test_with_images.pdf")
    
    assert len(result.images) > 0
    assert all(img.ocr_text for img in result.images)

def test_pdf_performance():
    """测试 PDF 处理性能"""
    processor = PDFProcessor()
    
    start = time.time()
    processor.process("10_page.pdf")
    elapsed = time.time() - start
    
    assert elapsed < 30.0  # 10页 < 30s
```

**验收检查**:

```bash
pytest tests/unit/test_processors/test_pdf.py -v
✅ 所有测试通过
```

---

## 🧪 测试要求

### 测试层次

```
1. 单元测试 (Unit Tests)
   位置: tests/unit/
   覆盖率: ≥ 80%
   运行: pytest tests/unit/
   
2. 集成测试 (Integration Tests)
   位置: tests/integration/
   覆盖: 核心流程
   运行: pytest tests/integration/
   
3. 端到端测试 (E2E Tests)
   位置: tests/e2e/
   覆盖: 主要场景
   运行: pytest tests/e2e/
   
4. 性能测试 (Performance Tests)
   位置: tests/performance/
   指标: 响应时间、吞吐量
   运行: pytest tests/performance/
```

### 测试覆盖率要求

```bash
# 运行测试并生成覆盖率报告
pytest --cov=scripts --cov-report=html --cov-report=term

# 最低要求:
✅ 总体覆盖率 ≥ 80%
✅ 核心模块覆盖率 ≥ 90%:
  - scripts/memory/core.py
  - scripts/memory/confidence.py
  - scripts/memory/decay.py
  
✅ 关键函数覆盖率 = 100%:
  - 数据写入函数
  - 文件移动函数
  - Confidence 计算函数
```

### 测试数据

```
位置: tests/fixtures/

必需的测试数据:
  ✅ 示例笔记（10-20个）
  ✅ 示例图片（JPG/PNG/WEBP各2张）
  ✅ 示例 PDF（文字版 + 扫描版各1个）
  ✅ 示例音频（短音频 < 1分钟）
  ✅ Mock 数据生成器
```

---

## ⚡ 性能标准

### 响应时间要求

```
操作                      | 响应时间    | 测试方法
-------------------------|------------|-------------------
创建笔记                  | < 100ms    | test_create_note_performance
读取笔记                  | < 50ms     | test_read_note_performance
搜索（1000笔记）          | < 100ms    | test_search_performance
计算 Confidence          | < 10ms     | test_confidence_performance
衰减扫描（1000笔记）      | < 5s       | test_decay_performance
图片 OCR                 | < 5s       | test_image_ocr_performance
PDF 处理（10页）          | < 30s      | test_pdf_processing_performance
视频转文字（1分钟）       | < 60s      | test_video_transcribe_performance
```

### 吞吐量要求

```
操作                      | 吞吐量           | 测试方法
-------------------------|-----------------|-------------------
批量导入笔记              | ≥ 50 notes/s    | test_bulk_import
批量 OCR                 | ≥ 10 images/s   | test_bulk_ocr
并发搜索                  | ≥ 100 req/s     | test_concurrent_search
```

### 资源使用要求

```
资源        | 限制        | 测试方法
-----------|-----------|-------------------
内存        | < 512MB   | test_memory_usage
CPU         | < 80%     | test_cpu_usage
磁盘 I/O    | < 100MB/s | test_disk_io
```

---

## 📝 代码质量标准

### 代码规范

```python
✅ 风格:
  - 遵循 PEP 8
  - 使用 Black 格式化
  - 使用 isort 排序导入
  
✅ 类型注解:
  - 所有公共函数必须有类型注解
  - 使用 mypy 检查类型
  
✅ 文档字符串:
  - 所有公共类和函数必须有 docstring
  - 使用 Google style docstring
  
✅ 命名:
  - 类名: PascalCase (MemoryTree)
  - 函数名: snake_case (calculate_confidence)
  - 常量: UPPER_CASE (MAX_CONFIDENCE)
  - 私有: _leading_underscore (_internal_method)
```

**验收检查**:

```bash
# 代码格式检查
black --check scripts/
isort --check scripts/

# 类型检查
mypy scripts/

# Linting
pylint scripts/ --rcfile=.pylintrc
flake8 scripts/

✅ 无错误，无警告
```

### 文档要求

```
✅ 每个模块必须有:
  - 模块级 docstring（说明模块用途）
  - 示例代码
  
✅ 每个公共类必须有:
  - 类 docstring（说明类用途）
  - 属性说明
  - 使用示例
  
✅ 每个公共函数必须有:
  - 函数 docstring
  - 参数说明（Args）
  - 返回值说明（Returns）
  - 异常说明（Raises）
  - 使用示例（Examples）
```

**示例**:

```python
def calculate_confidence(note_path: Path, metadata: Dict) -> float:
    """
    计算笔记的 confidence 值
    
    Confidence 综合考虑时间、引用、修改等因素，
    返回 0.0-1.0 的浮点数，表示笔记的重要程度。
    
    Args:
        note_path: 笔记文件路径
        metadata: 笔记元数据，包含:
            - created: 创建时间
            - accessed: 最后访问时间
            - modified: 最后修改时间
            - references: 引用次数
    
    Returns:
        float: Confidence 值，范围 [0.0, 1.0]
        
    Raises:
        ValueError: 如果 metadata 缺少必需字段
        FileNotFoundError: 如果笔记文件不存在
    
    Examples:
        >>> calc = ConfidenceCalculator()
        >>> metadata = {
        ...     "created": datetime.now(),
        ...     "accessed": datetime.now(),
        ...     "references": 5
        ... }
        >>> conf = calc.calculate(note_path, metadata)
        >>> 0.0 <= conf <= 1.0
        True
    """
    pass
```

---

## ✅ 验收流程

### Week 1 MVP 验收

**Day 7 检查清单**:

```bash
# 1. 运行完整测试套件
pytest --cov=scripts --cov-report=term

期望:
  ✅ 测试通过率 = 100%
  ✅ 覆盖率 ≥ 80%

# 2. 运行性能测试
pytest tests/performance/ -v

期望:
  ✅ 所有性能指标达标

# 3. 代码质量检查
black --check scripts/
mypy scripts/
pylint scripts/

期望:
  ✅ 无错误

# 4. 部署测试
docker-compose up -d
python tools/verify_installation.py

期望:
  ✅ 所有组件正常启动
  ✅ Web 界面可访问
  ✅ 示例数据可导入

# 5. 功能验收
python tools/acceptance_test.py

期望:
  ✅ 创建笔记成功
  ✅ Confidence 计算正确
  ✅ 搜索功能可用
  ✅ 图片 OCR 成功
  ✅ PDF 处理成功
```

### Week 2 完整版验收（可选）

```bash
# 1-4 同 Week 1

# 5. 完整功能验收
python tools/full_acceptance_test.py

期望:
  ✅ 所有输入格式支持
  ✅ CLI 工具可用
  ✅ 批量处理成功
  ✅ 负载测试通过

# 6. 生产就绪检查
python tools/production_readiness_check.py

期望:
  ✅ 日志配置正确
  ✅ 错误处理完善
  ✅ 配置灵活
  ✅ 监控可用
```

---

## 🔧 验收工具

### tools/acceptance_test.py

```python
#!/usr/bin/env python3
"""
Atelierr MVP 验收测试

执行所有关键功能的端到端测试，验证系统是否满足验收标准。
"""

import sys
from pathlib import Path
from scripts.memory.core import MemoryTree
from scripts.processors.image import ImageProcessor
from scripts.processors.pdf import PDFProcessor


def test_memory_module():
    """测试记忆模块"""
    print("🧪 测试记忆模块...")
    
    # 初始化
    tree = MemoryTree("/tmp/acceptance_test")
    
    # 创建笔记
    note = tree.create_note("test.md", "测试内容")
    assert note.exists(), "❌ 创建笔记失败"
    
    # 读取笔记
    content = tree.read_note(note)
    assert content == "测试内容", "❌ 读取笔记失败"
    
    # 搜索笔记
    results = tree.search("测试")
    assert len(results) > 0, "❌ 搜索失败"
    
    print("  ✅ 记忆模块测试通过")


def test_image_processor():
    """测试图片处理"""
    print("🧪 测试图片处理...")
    
    processor = ImageProcessor()
    result = processor.process("tests/fixtures/test_image.jpg")
    
    assert result.success, "❌ 图片处理失败"
    assert len(result.text) > 0, "❌ OCR 未提取到文字"
    
    print("  ✅ 图片处理测试通过")


def test_pdf_processor():
    """测试 PDF 处理"""
    print("🧪 测试 PDF 处理...")
    
    processor = PDFProcessor()
    result = processor.process("tests/fixtures/test.pdf")
    
    assert result.success, "❌ PDF 处理失败"
    assert result.page_count > 0, "❌ 未检测到页面"
    
    print("  ✅ PDF 处理测试通过")


def main():
    """运行所有验收测试"""
    print("\n" + "="*60)
    print("  Atelierr MVP 验收测试")
    print("="*60 + "\n")
    
    try:
        test_memory_module()
        test_image_processor()
        test_pdf_processor()
        
        print("\n" + "="*60)
        print("  ✅ 所有验收测试通过！")
        print("="*60 + "\n")
        
        return 0
        
    except AssertionError as e:
        print(f"\n❌ 验收测试失败: {e}")
        return 1
    except Exception as e:
        print(f"\n❌ 验收测试出错: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
```

### tools/verify_installation.py

```python
#!/usr/bin/env python3
"""
验证 Atelierr 安装

检查所有依赖和配置是否正确。
"""

import sys
import subprocess
from pathlib import Path


def check_python_version():
    """检查 Python 版本"""
    print("🔍 检查 Python 版本...")
    import sys
    version = sys.version_info
    assert version >= (3, 8), "需要 Python 3.8+"
    print(f"  ✅ Python {version.major}.{version.minor}")


def check_dependencies():
    """检查依赖包"""
    print("🔍 检查依赖包...")
    
    required = [
        "yaml",
        "watchdog",
        "pytest",
    ]
    
    for pkg in required:
        try:
            __import__(pkg)
            print(f"  ✅ {pkg}")
        except ImportError:
            print(f"  ❌ {pkg} 未安装")
            raise


def check_directories():
    """检查目录结构"""
    print("🔍 检查目录结构...")
    
    required_dirs = [
        "scripts/memory",
        "scripts/web",
        "scripts/processors",
        "scripts/cli",
        "scripts/utils",
        "config",
        "docker",
        "tests",
        "examples",
        "tools",
    ]
    
    for dir_path in required_dirs:
        path = Path(dir_path)
        assert path.exists(), f"{dir_path} 不存在"
        print(f"  ✅ {dir_path}")


def check_docker():
    """检查 Docker"""
    print("🔍 检查 Docker...")
    
    try:
        result = subprocess.run(
            ["docker", "--version"],
            capture_output=True,
            text=True
        )
        assert result.returncode == 0
        print(f"  ✅ {result.stdout.strip()}")
    except FileNotFoundError:
        print("  ⚠️  Docker 未安装（可选）")


def main():
    """运行所有检查"""
    print("\n" + "="*60)
    print("  Atelierr 安装验证")
    print("="*60 + "\n")
    
    try:
        check_python_version()
        check_dependencies()
        check_directories()
        check_docker()
        
        print("\n" + "="*60)
        print("  ✅ 安装验证通过！")
        print("="*60 + "\n")
        
        return 0
        
    except AssertionError as e:
        print(f"\n❌ 验证失败: {e}")
        return 1
    except Exception as e:
        print(f"\n❌ 验证出错: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
```

---

## 📊 验收报告模板

### 报告格式

```markdown
# Atelierr MVP 验收报告

**日期**: 2026-XX-XX  
**版本**: MVP v1.0  
**验收人**: XXX

---

## 功能验收

### 记忆模块 ✅
- [x] 创建笔记
- [x] Confidence 计算
- [x] 自动衰减
- [x] 搜索功能

### Web 界面 ✅
- [x] Flatnotes 部署
- [x] 双向同步

### 输入处理 ✅
- [x] 图片 OCR
- [x] PDF 处理

---

## 测试结果

### 单元测试
- 通过率: 100% (85/85)
- 覆盖率: 83%

### 集成测试
- 通过率: 100% (12/12)

### 性能测试
- 通过率: 100% (8/8)
- 所有指标达标

---

## 代码质量

- Black: ✅ 无格式问题
- Mypy: ✅ 无类型错误
- Pylint: ✅ 评分 9.2/10

---

## 部署测试

- Docker Compose: ✅ 正常启动
- Web 访问: ✅ http://localhost:8080
- 示例数据: ✅ 导入成功

---

## 结论

✅ MVP 验收通过，可以进入下一阶段。

建议:
1. 提高 Pylint 评分到 9.5+
2. 增加边界条件测试
3. 完善错误提示

---

验收人签名: _____________
日期: _____________
```

---

## 🎯 总结

### 验收标准总览

```
MVP (Week 1):
  ✅ 功能: 核心功能可用
  ✅ 测试: 覆盖率 ≥ 80%
  ✅ 性能: 关键指标达标
  ✅ 部署: Docker Compose 可用

完整版 (Week 2):
  ✅ 功能: 所有功能完整
  ✅ 测试: 覆盖率 ≥ 85%
  ✅ 性能: 所有指标达标
  ✅ 生产: 生产就绪
```

### 关键验收点

```
1. 所有测试通过 ✅
2. 覆盖率达标 ✅
3. 性能指标达标 ✅
4. 代码质量达标 ✅
5. 部署成功 ✅
6. 功能演示成功 ✅
```

---

**本文档是验收的唯一标准。所有开发必须满足这些标准才算完成。**
