# Atelierr 开发计划最终对齐

**版本**: v3.0 (最终对齐版)  
**日期**: 2026-08-28  
**状态**: 🔒 已对齐，准备开始

---

## 📋 对齐总结

### 当前状态

```
✅ PRD 文档: 15+ 个文档完整
✅ 项目结构: 10 个目录就绪
✅ 验收标准: 每个模块都有明确标准
✅ 测试规范: 4 层测试体系
✅ 自动化工具: 验证和验收脚本
✅ 代码隔离: Atelier 框架已隔离
✅ 质量保证: 完整的检查体系

准备就绪度: 💯
```

### 文档体系

```
设计文档:
  ✅ docs/prd/ARCHITECTURE-LOCKED-V1.md           (核心架构，已锁定)
  ✅ docs/prd/IMPLEMENTATION-PLAN-PARALLEL.md     (4-6周并行计划)
  ✅ docs/prd/multimodal-input-processing.md      (多模态方案)
  ✅ docs/prd/large-file-handling.md              (大文件方案)
  ✅ 8 张架构图

项目文档:
  ✅ docs/PROJECT-STRUCTURE.md                    (项目结构)
  ✅ PROJECT-SUMMARY.md                           (项目概述)
  ✅ README.md                                    (项目总览)
  ✅ QUICK-START.md                               (快速开始)

质量文档:
  ✅ docs/ACCEPTANCE-CRITERIA.md                  (验收标准) ⭐
  ✅ docs/TESTING-GUIDE.md                        (测试指南) ⭐
  ✅ DEVELOPMENT-READY.md                         (开发就绪)
  ✅ PRE-DEVELOPMENT-CHECK-REPORT.md              (检查报告)

工具脚本:
  ✅ tools/verify_installation.py                 (安装验证)
  ✅ tools/acceptance_test.py                     (验收测试)
  ✅ tools/pre_dev_check.py                       (开发前检查)
  ✅ tools/isolate_atelier.sh                     (隔离脚本)
```

---

## 🎯 开发计划对齐

### 核心目标

```
MVP (Week 1):
  ✅ 记忆模块核心功能可用
  ✅ Web 界面可访问 (Flatnotes)
  ✅ 至少 2 种输入格式 (图片 + PDF)
  ✅ 测试覆盖率 ≥ 80%
  ✅ Docker Compose 一键启动

完整版 (Week 2，可选):
  ✅ 所有输入格式 (图片/视频/音频/PDF/微信)
  ✅ CLI 工具完整
  ✅ 批量处理可用
  ✅ 测试覆盖率 ≥ 85%
  ✅ 性能达标
```

### 开发策略

```
方案选择: 稳健并行（6周）⭐ 推荐

理由:
  ✅ 平衡速度和质量
  ✅ 有缓冲时间
  ✅ 测试充分
  ✅ 适合单人开发
  ✅ AI 辅助并行

时间分配:
  Week 1-2: 核心功能并行开发 → MVP
  Week 3-4: 扩展功能并行开发
  Week 5:   集成测试和优化
  Week 6:   文档和发布准备
```

---

## 📅 详细开发计划

### Week 1: MVP 核心（Day 1-7）

#### 流水线 A: 记忆模块（你自己）

```python
Day 1: MemoryTree 核心类
  ✅ 初始化三层目录结构
  ✅ 基础路径管理
  ✅ 目录创建和验证
  ✅ 编写单元测试
  
  交付:
    - scripts/memory/core.py (框架)
    - tests/unit/test_memory/test_core.py
    - 测试通过

  验收:
    $ pytest tests/unit/test_memory/test_core.py -v
    期望: test_memory_tree_init PASSED
```

```python
Day 2: Confidence 计算
  ✅ 实现 calculate_confidence()
  ✅ 考虑时间因素
  ✅ 考虑引用因素
  ✅ 考虑修改因素
  ✅ 编写测试用例
  
  交付:
    - scripts/memory/confidence.py
    - tests/unit/test_memory/test_confidence.py
    - 覆盖率 ≥ 90%

  验收:
    $ pytest tests/unit/test_memory/test_confidence.py -v
    期望: 所有测试通过
    $ python -c "from scripts.memory.confidence import ConfidenceCalculator; print('✅')"
```

```python
Day 3: 衰减机制
  ✅ 实现 DecayManager
  ✅ 扫描所有笔记
  ✅ 根据 confidence 移动层级
  ✅ 生成衰减报告
  ✅ 支持 dry-run 模式
  
  交付:
    - scripts/memory/decay.py
    - tests/unit/test_memory/test_decay.py
    - dry-run 功能可用

  验收:
    $ pytest tests/unit/test_memory/test_decay.py -v
    期望: 所有测试通过
```

```python
Day 4: 搜索功能
  ✅ 全文搜索（标题 + 内容）
  ✅ 标签搜索
  ✅ 日期范围搜索
  ✅ 按 confidence 排序
  ✅ 性能优化 (<100ms)
  
  交付:
    - scripts/memory/search.py
    - tests/unit/test_memory/test_search.py
    - 性能测试通过

  验收:
    $ pytest tests/unit/test_memory/test_search.py -v
    $ pytest tests/performance/test_search_performance.py -v
    期望: 1000笔记搜索 < 100ms
```

```python
Day 5: 记忆模块集成
  ✅ 整合所有子模块
  ✅ 统一接口
  ✅ 集成测试
  ✅ 文档完善
  
  交付:
    - 记忆模块 MVP 完成 ✅
    - 集成测试通过
    - API 文档完整

  验收:
    $ pytest tests/integration/test_memory_integration.py -v
    $ python tools/acceptance_test.py
    期望: 记忆模块验收通过
```

#### 流水线 B: Web 界面（AI 辅助 / 晚上）

```bash
Day 1-2: Flatnotes 部署
  ✅ 编写 docker-compose.yml
  ✅ 配置挂载目录
  ✅ 测试基本功能
  ✅ 编写部署文档
  
  命令:
    docker-compose up -d
  
  交付:
    - docker/docker-compose.yml
    - docker/flatnotes.env
    - docs/flatnotes-deployment.md
  
  验收:
    浏览器访问: http://localhost:8080
    期望: Flatnotes 界面可访问
```

```python
Day 3-4: 文件监控
  ✅ 实现 FlatnotesIntegration 类
  ✅ 使用 watchdog 监控文件
  ✅ 自动同步新笔记
  ✅ 自动更新 metadata
  ✅ 双向同步
  
  交付:
    - scripts/web/integration.py
    - tests/integration/test_web_integration.py
    - 同步功能可用

  验收:
    $ pytest tests/integration/test_web_integration.py -v
    期望: 双向同步测试通过
```

```python
Day 5: Web 集成完成
  ✅ 连接记忆模块
  ✅ 实时显示 confidence
  ✅ 测试完整流程
  
  交付:
    - Web 界面完全可用 ✅
    - 端到端测试通过

  验收:
    $ pytest tests/e2e/test_web_memory_flow.py -v
    期望: E2E 测试通过
```

#### 流水线 C: 输入处理（AI 辅助 / 晚上）

```python
Day 1-2: 处理器框架
  ✅ 设计 BaseProcessor 接口
  ✅ 实现类型检测
  ✅ 实现处理器路由
  ✅ 标准化输出格式
  
  交付:
    - scripts/processors/base.py
    - tests/unit/test_processors/test_base.py
    - 框架可扩展

  验收:
    $ pytest tests/unit/test_processors/test_base.py -v
    期望: 框架测试通过
```

```python
Day 3-4: 图片处理器
  ✅ 安装 PaddleOCR
  ✅ 实现图片 OCR
  ✅ 生成 Markdown 输出
  ✅ 保留原图链接
  ✅ 性能测试 (<5s)
  
  交付:
    - scripts/processors/image.py
    - tests/unit/test_processors/test_image.py
    - 图片处理可用

  验收:
    $ pytest tests/unit/test_processors/test_image.py -v
    $ pytest tests/performance/test_image_performance.py -v
    期望: 单张图片 < 5s
```

```python
Day 5: PDF 处理器
  ✅ 安装 PyMuPDF
  ✅ 实现文字提取
  ✅ 实现图片提取并 OCR
  ✅ 保留文档结构
  ✅ 性能测试 (10页 <30s)
  
  交付:
    - scripts/processors/pdf.py
    - tests/unit/test_processors/test_pdf.py
    - PDF 处理可用

  验收:
    $ pytest tests/unit/test_processors/test_pdf.py -v
    $ pytest tests/performance/test_pdf_performance.py -v
    期望: 10页 PDF < 30s
```

### Week 1 里程碑验收

```bash
Day 7: MVP 验收

验收清单:
  1. 安装验证
     $ python3 tools/verify_installation.py
     期望: ✅ 所有检查通过

  2. 单元测试
     $ pytest tests/unit/ -v
     期望: ✅ 通过率 100%

  3. 测试覆盖率
     $ pytest --cov=scripts --cov-report=term
     期望: ✅ 覆盖率 ≥ 80%

  4. 代码质量
     $ black --check scripts/
     $ mypy scripts/
     $ pylint scripts/
     期望: ✅ 无错误

  5. 验收测试
     $ python3 tools/acceptance_test.py
     期望: ✅ 所有模块通过

  6. 系统部署
     $ docker-compose up -d
     期望: ✅ 所有服务启动

  7. 功能演示
     - 创建笔记
     - 计算 confidence
     - 搜索笔记
     - 图片 OCR
     - PDF 处理
     期望: ✅ 核心功能可用

结论:
  ✅ MVP 验收通过 → 进入 Week 2
  ❌ MVP 验收失败 → 修复问题
```

---

### Week 2: 扩展功能（Day 8-14，可选）

#### 流水线 A: CLI 工具

```python
Day 8-9: Memory CLI
  ✅ 实现 memory_cli.py
  ✅ 命令: create, search, decay, stats
  ✅ 参数解析和验证
  ✅ 输出格式化
  
  命令示例:
    $ python -m scripts.cli.memory_cli create "笔记标题"
    $ python -m scripts.cli.memory_cli search "关键词"
    $ python -m scripts.cli.memory_cli decay --dry-run
    $ python -m scripts.cli.memory_cli stats

  交付:
    - scripts/cli/memory_cli.py
    - tests/integration/test_memory_cli.py
    - 使用文档

  验收:
    $ python -m scripts.cli.memory_cli --help
    期望: 显示帮助信息
```

```python
Day 10: Process CLI
  ✅ 实现 process_cli.py
  ✅ 命令: image, pdf, video, audio, wechat
  ✅ 批量处理支持
  
  命令示例:
    $ python -m scripts.cli.process_cli image screenshot.jpg
    $ python -m scripts.cli.process_cli pdf document.pdf
    $ python -m scripts.cli.process_cli --batch ~/Downloads/

  交付:
    - scripts/cli/process_cli.py
    - tests/integration/test_process_cli.py

  验收:
    $ python -m scripts.cli.process_cli --help
    期望: 显示帮助信息
```

#### 流水线 B: 批量处理

```python
Day 11-12: 批量处理器
  ✅ 实现 batch_cli.py
  ✅ 并发处理
  ✅ 进度跟踪
  ✅ 错误恢复
  ✅ 结果报告
  
  命令示例:
    $ python -m scripts.cli.batch_cli \
        --input-dir ~/Downloads/ \
        --workers 4 \
        --output-dir $OV/memory/short-term/

  交付:
    - scripts/cli/batch_cli.py
    - tests/integration/test_batch_processing.py

  验收:
    $ python -m scripts.cli.batch_cli --help
    期望: 批量处理成功
```

#### 流水线 C: 剩余输入格式

```python
Day 13: 视频处理器
  ✅ 安装 ffmpeg + whisper
  ✅ 实现音频提取
  ✅ 实现语音转文字
  ✅ 实现关键帧提取
  
  交付:
    - scripts/processors/video.py
    - tests/unit/test_processors/test_video.py

  验收:
    $ pytest tests/unit/test_processors/test_video.py -v
    期望: 视频处理测试通过
```

```python
Day 14: 音频 + 微信处理器
  ✅ 实现 audio.py (复用 whisper)
  ✅ 实现 wechat.py (解析导出格式)
  
  交付:
    - scripts/processors/audio.py
    - scripts/processors/wechat.py
    - 对应测试

  验收:
    $ pytest tests/unit/test_processors/ -v
    期望: 所有处理器测试通过
```

### Week 2 里程碑验收

```bash
Day 14: 完整版验收

验收清单:
  1-6. 同 Week 1

  7. 集成测试
     $ pytest tests/integration/ -v
     期望: ✅ 通过率 100%

  8. 端到端测试
     $ pytest tests/e2e/ -v
     期望: ✅ 通过率 100%

  9. 性能测试
     $ pytest tests/performance/ -v
     期望: ✅ 所有性能指标达标

  10. 完整功能演示
      - 所有输入格式处理
      - CLI 工具可用
      - 批量处理成功
      期望: ✅ 所有功能可用

结论:
  ✅ 完整版验收通过 → 进入优化阶段
```

---

### Week 3-4: 优化和文档（可选）

```
Week 3: 性能优化和自动化
  Day 15-17: 性能优化
    - 搜索速度提升
    - 内存优化
    - 并发处理

  Day 18-19: 自动化
    - 文件夹监控
    - 定时任务
    - 后台运行

  Day 20-21: 多模态补充
    - 链接处理器
    - 优化现有处理器

Week 4: 测试和文档
  Day 22-24: 测试完善
    - 补充边界测试
    - 压力测试
    - 安全测试

  Day 25-27: 文档完善
    - 用户文档
    - API 文档
    - 故障排除文档

  Day 28: 发布准备
    - 最终验收
    - 版本打包
    - Release notes
```

---

## 🔧 开发工具和流程

### 开发前验证

```bash
# 1. 验证安装
python3 tools/verify_installation.py

期望结果:
  ✅ Python 版本: 3.8+
  ✅ 依赖包: 已安装
  ✅ 目录结构: 完整
  ✅ 模块导入: 成功
```

### 开发中验证（每天）

```bash
# 1. 运行今天写的测试
pytest tests/unit/test_memory/test_core.py -v

# 2. 代码格式化
black scripts/memory/
isort scripts/memory/

# 3. 类型检查
mypy scripts/memory/

# 4. 代码质量
pylint scripts/memory/

期望:
  ✅ 测试通过
  ✅ 无格式问题
  ✅ 无类型错误
  ✅ pylint 评分 ≥ 9.0
```

### 每周验收（Week 1, Week 2）

```bash
# Week 1 结束 (Day 7)
python3 tools/acceptance_test.py

# Week 2 结束 (Day 14)
pytest --cov=scripts --cov-report=html
open htmlcov/index.html

期望:
  ✅ Week 1: MVP 验收通过
  ✅ Week 2: 完整版验收通过
```

---

## 📊 进度跟踪

### 每日检查清单

```
□ 今天的目标是什么？
□ 完成了哪些功能？
□ 写了哪些测试？
□ 代码质量检查通过了吗？
□ 遇到了什么问题？
□ 明天的计划是什么？
```

### 每周检查清单

```
□ 本周目标达成了吗？
□ MVP 功能完整了吗？
□ 测试覆盖率达标了吗？
□ 文档更新了吗？
□ 需要调整计划吗？
```

---

## 🎯 关键成功因素

### 技术层面

```
✅ 清晰的模块边界
  - 记忆模块独立
  - 处理器互不依赖
  - Web 界面解耦

✅ 完善的测试
  - 单元测试 ≥ 80%
  - 集成测试覆盖关键流程
  - 性能测试有明确指标

✅ 自动化工具
  - 验证脚本
  - 验收脚本
  - CI/CD (可选)
```

### 流程层面

```
✅ 测试驱动开发 (TDD)
  - 先写测试
  - 再写实现
  - 持续验证

✅ 增量交付
  - Day 1-5: 核心功能
  - Day 6-7: 集成测试
  - Week 2: 扩展功能

✅ 持续集成
  - 每日代码检查
  - 每周验收测试
  - 问题及时修复
```

### 工具辅助

```
✅ AI 辅助开发
  - 生成测试用例
  - 编写样板代码
  - 文档草稿

✅ 并行开发
  - 白天: 核心逻辑
  - 晚上: 测试和文档
  - AI 帮: 辅助任务
```

---

## 📚 快速参考

### 核心文档

```
设计:
  docs/prd/ARCHITECTURE-LOCKED-V1.md
  docs/prd/IMPLEMENTATION-PLAN-PARALLEL.md

质量:
  docs/ACCEPTANCE-CRITERIA.md
  docs/TESTING-GUIDE.md

当前:
  DEVELOPMENT-PLAN-ALIGNED.md (本文档)
```

### 验收标准

```
MVP (Week 1):
  ✅ 功能: 记忆模块 + Web + 图片/PDF
  ✅ 测试: 覆盖率 ≥ 80%
  ✅ 质量: pylint ≥ 9.0
  ✅ 部署: Docker Compose 可用

完整版 (Week 2):
  ✅ 功能: 所有输入格式 + CLI
  ✅ 测试: 覆盖率 ≥ 85%
  ✅ 性能: 所有指标达标
  ✅ 文档: 完整
```

### 快速命令

```bash
# 安装依赖
pip install -r requirements.txt

# 验证安装
python3 tools/verify_installation.py

# 运行测试
pytest tests/unit/ -v

# 验收测试
python3 tools/acceptance_test.py

# 查看覆盖率
pytest --cov=scripts --cov-report=term

# 启动系统
docker-compose up -d
```

---

## 🎉 最终对齐确认

### 我们对齐了什么

```
✅ 开发目标: MVP (1-2周) + 完整版 (3-4周)
✅ 开发策略: 稳健并行，AI 辅助
✅ 验收标准: 每个模块都有明确标准
✅ 测试要求: 4 层测试，覆盖率 ≥ 80%
✅ 质量标准: Black + mypy + pylint
✅ 验证工具: 自动化脚本
✅ 时间规划: 详细到每天
```

### 开始开发检查清单

```
□ 已阅读核心架构文档
□ 已阅读验收标准
□ 已阅读测试指南
□ 已运行 verify_installation.py
□ 已安装所有依赖
□ 已理解并行开发策略
□ 已准备好 AI 辅助工具
□ 已清楚第一天要做什么

✅ 全部完成 → 开始开发！
```

---

**🚀 一切准备就绪！开发计划已完全对齐！**

**从 scripts/memory/core.py 开始，1-2 周完成 MVP，4-6 周完成完整版！**

**准备好了吗？Let's build! 🎨**
