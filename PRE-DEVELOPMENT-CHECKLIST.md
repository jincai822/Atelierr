# Atelierr 开发前检查清单

**日期**: 2026-08-27  
**检查人**: 开发负责人  
**状态**: 🔍 检查中

---

## 📋 检查目标

1. 确保所有 PRD 文档完整且一致
2. 确保项目结构与开发计划对齐
3. 隔离不相关的 Atelier 框架文件
4. 确保开发路径清晰

---

## 🎯 检查项目

### 1. PRD 文档检查

#### ✅ 核心文档

- [ ] `docs/prd/ARCHITECTURE-LOCKED-V1.md` - 核心架构（锁定版）
- [ ] `docs/prd/IMPLEMENTATION-PLAN-PARALLEL.md` - 并行实施计划
- [ ] `docs/PROJECT-STRUCTURE.md` - 项目结构规范
- [ ] `PROJECT-SUMMARY.md` - 项目总结

#### ✅ 支持文档

- [ ] `docs/prd/multimodal-input-processing.md` - 多模态输入
- [ ] `docs/prd/large-file-handling.md` - 大文件处理
- [ ] `docs/prd/README.md` - PRD 索引
- [ ] `docs/README.md` - 文档导航
- [ ] `docs/DOCUMENTATION-STRUCTURE.md` - 文档规范

#### ✅ 用户文档

- [ ] `README.md` - 项目总览
- [ ] `QUICK-START.md` - 快速开始

#### ⚠️ 需要隔离的文档

这些是 Atelier 反思系统的文档，不是 Atelierr 记忆系统的：

- [ ] `AGENTS.md` - Atelier Codex 适配器（保留，但不相关）
- [ ] `CLAUDE.md` - Atelier 核心规则（保留，但不相关）
- [ ] `frameworks/` - Atelier 框架（保留，但不相关）
- [ ] `protocols/` - Atelier 协议（保留，但不相关）
- [ ] `harness/` - Atelier 运行时（保留，但不相关）

### 2. 目录结构检查

#### ✅ 核心开发目录（需要的）

```
检查这些目录是否存在且结构正确:

scripts/
├── memory/           ← 模块 1: 记忆管理
│   ├── __init__.py
│   ├── core.py
│   ├── confidence.py
│   ├── decay.py
│   ├── search.py
│   ├── watcher.py
│   └── scheduler.py
│
├── web/             ← 模块 2: Web 集成
│   ├── __init__.py
│   ├── flatnotes_config.py
│   └── integration.py
│
├── processors/      ← 模块 3: 输入处理
│   ├── __init__.py
│   ├── base.py
│   ├── image.py
│   ├── video.py
│   ├── pdf.py
│   ├── audio.py
│   └── wechat.py
│
├── cli/            ← CLI 工具
│   ├── __init__.py
│   ├── memory_cli.py
│   ├── process_cli.py
│   └── batch_cli.py
│
└── utils/          ← 工具函数
    ├── __init__.py
    ├── config.py
    ├── file_utils.py
    ├── text_utils.py
    └── date_utils.py

config/
├── memory.yaml.example
├── storage.yaml.example
├── processors.yaml.example
└── logging.yaml.example

docker/
├── docker-compose.yml
└── .env.example

tests/
├── unit/
│   ├── test_memory/
│   ├── test_processors/
│   └── test_utils/
├── integration/
└── fixtures/

examples/
├── basic_usage.py
├── batch_processing.py
└── custom_processor.py

tools/
├── init_project.py
├── init_memory.py
├── verify_installation.py
└── generate_test_data.py
```

- [ ] scripts/memory/ 存在且完整
- [ ] scripts/web/ 存在且完整
- [ ] scripts/processors/ 存在且完整
- [ ] scripts/cli/ 存在且完整
- [ ] scripts/utils/ 存在且完整
- [ ] config/ 存在且完整
- [ ] docker/ 存在且完整
- [ ] tests/ 存在且完整
- [ ] examples/ 存在且完整
- [ ] tools/ 存在且完整

#### ⚠️ Atelier 框架目录（需要隔离）

这些是现有的 Atelier 反思系统，不是 Atelierr 记忆系统的开发目录：

```
scripts/ 下的 Atelier 脚本:
- aggregate_freshness.py
- atelier_runtime.py
- autoevo_*.py
- chat_completion.py
- context_bundle.py
- semantic*.py
- session*.py
- ... 等 50+ 个 Atelier 脚本

这些文件应该:
- [ ] 移动到 scripts/atelier/ 子目录
- [ ] 或创建 .atelierrignore 标记
```

### 3. 依赖文件检查

#### ✅ 需要的配置文件

- [ ] `requirements.txt` - Python 依赖
- [ ] `.gitignore` - Git 忽略规则
- [ ] `pytest.ini` - 测试配置

#### ⚠️ Atelier 框架配置（不相关）

- [ ] `pyproject.toml` - Atelier 项目配置（保留）
- [ ] `uv.lock` - Atelier 依赖锁（保留）
- [ ] `semantic.toml.example` - Atelier 语义搜索（保留）

### 4. 文档一致性检查

#### 架构设计对齐

检查以下文档描述的架构是否一致:

- [ ] `docs/prd/ARCHITECTURE-LOCKED-V1.md` 中的三模块架构
- [ ] `docs/PROJECT-STRUCTURE.md` 中的目录结构
- [ ] `PROJECT-SUMMARY.md` 中的实施计划
- [ ] 实际的 `scripts/` 目录结构

#### 关键概念一致性

- [ ] "记忆模块" 在所有文档中指向 `scripts/memory/`
- [ ] "Web 界面" 在所有文档中指向 Flatnotes + `scripts/web/`
- [ ] "输入处理" 在所有文档中指向 `scripts/processors/`
- [ ] "Confidence" 计算方法在各文档中一致
- [ ] "三层记忆" 定义在各文档中一致

#### 实施计划对齐

- [ ] 并行开发计划中的模块划分与目录结构匹配
- [ ] 开发优先级与目录结构的依赖关系匹配
- [ ] 时间估算（1-2周）与实际工作量匹配

### 5. 清理不相关内容

#### 需要隔离的内容

```
问题: scripts/ 目录混杂了两个系统的代码

当前状态:
scripts/
├── memory/              ← Atelierr (新系统)
├── web/                 ← Atelierr (新系统)
├── processors/          ← Atelierr (新系统)
├── aggregate_freshness.py  ← Atelier (旧系统)
├── atelier_runtime.py      ← Atelier (旧系统)
├── autoevo_*.py            ← Atelier (旧系统)
└── ... (50+ Atelier 脚本)

解决方案选项:

方案 A: 移动 Atelier 脚本到子目录
  scripts/
  ├── atelierr/         ← 新系统（记忆管理）
  │   ├── memory/
  │   ├── web/
  │   └── processors/
  └── atelier/          ← 旧系统（反思框架）
      ├── aggregate_freshness.py
      └── ...

方案 B: 创建新的顶层目录
  Atelierr/
  ├── atelierr/         ← 新系统
  │   └── (memory, web, processors)
  └── scripts/          ← 旧系统（保持不变）

方案 C: 创建 .atelierrignore 标记
  - 保持目录结构不变
  - 创建 .atelierrignore 文件
  - 列出所有 Atelier 相关文件
  - Atelierr 开发时忽略这些文件
```

- [ ] 选择隔离方案
- [ ] 执行隔离操作
- [ ] 验证隔离结果

---

## 🔍 检查结果

### 发现的问题

#### ❌ 严重问题

1. **目录混杂**: scripts/ 目录包含了 Atelier 和 Atelierr 两个系统的代码

#### ⚠️ 中等问题

2. **文档混杂**: 根目录有 AGENTS.md, CLAUDE.md 等 Atelier 文档
3. **配置混杂**: pyproject.toml, uv.lock 是 Atelier 的配置

#### ℹ️ 轻微问题

4. **命名冲突**: 需要明确区分 Atelier (旧) vs Atelierr (新)

### 推荐方案

#### 隔离策略

**推荐: 方案 A（移动到子目录）**

理由:
- ✅ 清晰分离两个系统
- ✅ 保持现有 Atelier 功能不变
- ✅ Atelierr 开发路径清晰
- ✅ 避免命名冲突

实施步骤:
1. 创建 scripts/atelierr/ 目录
2. 移动 memory/, web/, processors/, cli/, utils/ 到 scripts/atelierr/
3. 更新导入路径
4. 更新文档引用
5. 测试验证

#### 文档整理

创建清晰的文档分类:
```
docs/
├── atelierr/           ← Atelierr 记忆系统文档
│   ├── prd/
│   ├── dev/
│   └── user/
└── atelier/            ← Atelier 反思系统文档
    └── protocols/
```

---

## ✅ 检查通过条件

### 必须满足

- [ ] 所有 PRD 文档完整且一致
- [ ] 项目结构与开发计划完全对齐
- [ ] Atelier 和 Atelierr 代码清晰分离
- [ ] 开发路径明确，无歧义

### 推荐满足

- [ ] 文档目录清晰分类
- [ ] 配置文件分离
- [ ] README 明确说明两个系统的关系

---

## 📝 检查执行

### 自动检查脚本

```python
# tools/pre_dev_check.py
"""开发前自动检查脚本"""

def check_prd_documents():
    """检查 PRD 文档完整性"""
    pass

def check_directory_structure():
    """检查目录结构对齐"""
    pass

def check_consistency():
    """检查文档一致性"""
    pass

def check_isolation():
    """检查 Atelier/Atelierr 隔离"""
    pass

if __name__ == "__main__":
    print("🔍 开始开发前检查...")
    check_prd_documents()
    check_directory_structure()
    check_consistency()
    check_isolation()
    print("✅ 检查完成！")
```

---

## 🎯 下一步

### 如果检查通过

```bash
# 1. 确认隔离方案
# 2. 执行隔离操作
# 3. 更新文档
# 4. 开始开发 scripts/atelierr/memory/core.py
```

### 如果检查未通过

```bash
# 1. 修复发现的问题
# 2. 重新检查
# 3. 确认通过后再开始开发
```

---

**🔍 请仔细审查此检查清单，确认无误后再开始开发！**
