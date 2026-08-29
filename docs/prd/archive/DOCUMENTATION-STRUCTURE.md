# Atelierr 项目文档结构规范

**版本**: v1.0  
**状态**: 🔒 已锁定  
**日期**: 2026-08-27

---

## 📋 总体原则

### 文档分层

```
1. 顶层文档（根目录）
   → 快速了解项目
   → 如何开始使用

2. PRD 文档（docs/prd/）
   → 产品需求和架构
   → 仅在设计阶段编写
   → 锁定后不再修改

3. 开发文档（docs/dev/）
   → 开发过程中的文档
   → API 参考、技术细节
   → 持续更新

4. 用户文档（docs/user/）
   → 最终用户文档
   → 安装、使用、FAQ
   → 面向非技术用户

5. 代码文档（代码内）
   → Docstring
   → 类型注解
   → 内联注释
```

### 文档原则

```
✅ 单一职责: 每个文档只讲一件事
✅ 易于查找: 清晰的目录结构
✅ 及时更新: 代码变化 → 文档同步
✅ 分离关注: PRD vs 开发文档 vs 用户文档
✅ 版本控制: 所有文档纳入 Git
```

---

## 📁 完整目录结构

```
Atelierr/
├── README.md                          ← 项目总览（必读）
├── QUICK-START.md                     ← 5分钟快速开始
├── CHANGELOG.md                       ← 版本变更历史
├── LICENSE                            ← 开源协议
├── .gitignore                         ← Git 忽略规则
│
├── docs/                              ← 所有文档
│   ├── README.md                      ← 文档导航
│   │
│   ├── prd/                           ← 产品需求文档（已锁定）
│   │   ├── README.md                  ← PRD 总索引
│   │   ├── ARCHITECTURE-LOCKED-V1.md  ← 核心架构
│   │   ├── IMPLEMENTATION-PLAN.md     ← 串行实施计划
│   │   ├── IMPLEMENTATION-PLAN-PARALLEL.md ← 并行实施计划
│   │   ├── *.png                      ← 架构图
│   │   └── ...                        ← 其他 PRD 文档
│   │
│   ├── dev/                           ← 开发文档（持续更新）
│   │   ├── README.md                  ← 开发文档索引
│   │   ├── setup.md                   ← 开发环境设置
│   │   ├── architecture.md            ← 架构说明（技术视角）
│   │   ├── api-reference.md           ← API 完整参考
│   │   ├── testing.md                 ← 测试指南
│   │   ├── contributing.md            ← 贡献指南
│   │   ├── code-style.md              ← 代码规范
│   │   └── troubleshooting.md         ← 常见问题排查
│   │
│   ├── user/                          ← 用户文档（面向使用者）
│   │   ├── README.md                  ← 用户文档索引
│   │   ├── installation.md            ← 安装指南
│   │   ├── getting-started.md         ← 入门教程
│   │   ├── user-guide.md              ← 完整使用手册
│   │   ├── web-interface.md           ← Web 界面使用
│   │   ├── input-processing.md        ← 输入处理指南
│   │   ├── memory-management.md       ← 记忆管理说明
│   │   ├── faq.md                     ← 常见问题
│   │   └── examples/                  ← 使用示例
│   │       ├── basic-workflow.md
│   │       ├── video-processing.md
│   │       └── advanced-usage.md
│   │
│   └── design/                        ← 设计文档（可选）
│       ├── memory-decay-algorithm.md  ← 算法设计
│       ├── confidence-calculation.md  ← Confidence 计算
│       └── file-format.md             ← 文件格式规范
│
├── scripts/                           ← 核心代码
│   ├── __init__.py
│   ├── memory.py                      ← 记忆模块核心
│   ├── memory_watcher.py              ← 文件监控
│   ├── memory_scheduler.py            ← 定时任务
│   ├── input_processor.py             ← 输入处理入口
│   │
│   ├── processors/                    ← 各类处理器
│   │   ├── __init__.py
│   │   ├── base.py                    ← 基类
│   │   ├── image.py                   ← 图片处理
│   │   ├── video.py                   ← 视频处理
│   │   ├── pdf.py                     ← PDF 处理
│   │   ├── audio.py                   ← 音频处理
│   │   └── wechat.py                  ← 微信处理
│   │
│   └── utils/                         ← 工具函数
│       ├── __init__.py
│       ├── file_utils.py
│       ├── text_utils.py
│       └── date_utils.py
│
├── config/                            ← 配置文件
│   ├── memory.yaml                    ← 记忆模块配置
│   ├── storage.yaml                   ← 存储配置
│   ├── processors.yaml                ← 处理器配置
│   └── example.env                    ← 环境变量示例
│
├── tests/                             ← 测试
│   ├── __init__.py
│   ├── conftest.py                    ← pytest 配置
│   ├── test_memory.py                 ← 记忆模块测试
│   ├── test_processors/               ← 处理器测试
│   │   ├── test_image.py
│   │   ├── test_video.py
│   │   └── test_pdf.py
│   ├── test_integration/              ← 集成测试
│   │   └── test_end_to_end.py
│   └── fixtures/                      ← 测试数据
│       ├── sample.md
│       ├── sample.jpg
│       └── sample.pdf
│
├── docker/                            ← Docker 相关
│   ├── docker-compose.yml             ← Flatnotes 部署
│   ├── Dockerfile                     ← 自定义镜像（可选）
│   └── nginx.conf                     ← Nginx 配置（可选）
│
├── examples/                          ← 示例和演示
│   ├── basic_usage.py                 ← 基础使用
│   ├── batch_processing.py            ← 批量处理
│   └── custom_processor.py            ← 自定义处理器
│
├── tools/                             ← 开发工具
│   ├── generate_test_data.py          ← 生成测试数据
│   ├── validate_config.py             ← 验证配置
│   └── migration/                     ← 数据迁移脚本
│
└── .github/                           ← GitHub 配置
    ├── workflows/                     ← CI/CD
    │   ├── test.yml
    │   └── release.yml
    └── ISSUE_TEMPLATE/                ← Issue 模板
        ├── bug_report.md
        └── feature_request.md
```

---

## 📄 关键文档说明

### 1. 根目录文档

#### README.md（项目总览）

```markdown
目的: 5分钟了解项目

内容:
  1. 项目简介（1段话）
  2. 核心特性（3-5个亮点）
  3. 快速开始（3个命令）
  4. 架构概览（简图）
  5. 文档导航
  6. 许可证

受众: 所有人（首次接触）
更新: 重大变化时
```

#### QUICK-START.md（快速开始）

```markdown
目的: 10分钟跑起来

内容:
  1. 环境要求
  2. 安装步骤（复制粘贴即可）
  3. 第一个例子
  4. 验证成功
  5. 下一步建议

受众: 想快速试用的人
更新: 安装方式变化时
```

#### CHANGELOG.md（变更历史）

```markdown
目的: 跟踪版本变化

格式:
  ## [v1.0.0] - 2026-09-30
  ### Added
  - 新功能
  
  ### Changed
  - 修改的功能
  
  ### Fixed
  - Bug 修复

受众: 所有用户
更新: 每次发布
```

---

### 2. PRD 文档（docs/prd/）

#### 特点

```
✅ 锁定状态: 设计阶段完成后不再修改
✅ 历史记录: 保留设计过程和决策
✅ 参考价值: 开发时回顾设计意图
✅ 归档性质: 不是活文档
```

#### 核心文档

```
ARCHITECTURE-LOCKED-V1.md
  - 核心架构设计
  - 三模块详解
  - 技术选型理由

IMPLEMENTATION-PLAN-PARALLEL.md
  - 并行开发计划
  - 6周路线图
  - 任务清单

*.png
  - 架构图解
  - 流程图
  - 对比图
```

---

### 3. 开发文档（docs/dev/）

#### 特点

```
✅ 活文档: 代码变化 → 立即更新
✅ 技术视角: 面向开发者
✅ 深入细节: API、算法、实现
✅ 持续维护: 整个项目生命周期
```

#### setup.md（开发环境设置）

```markdown
内容:
  1. 系统要求
  2. 依赖安装
  3. 开发工具推荐
  4. 环境变量配置
  5. 验证安装
  6. 常见问题

命令:
  # 可直接复制执行的命令
  python3 -m venv .venv
  source .venv/bin/activate
  pip install -r requirements-dev.txt

更新: 依赖或工具变化时
```

#### architecture.md（架构说明）

```markdown
内容:
  1. 系统架构（从技术视角）
  2. 模块依赖关系
  3. 数据流向
  4. 关键设计决策
  5. 扩展点

vs PRD:
  - PRD: 为什么这样设计（需求驱动）
  - 这个: 怎么实现的（技术细节）

更新: 架构变化时
```

#### api-reference.md（API 参考）

```markdown
格式:

## MemoryTree

### `__init__(root_path: str)`

初始化记忆树。

**参数:**
- `root_path` (str): $OV/memory/ 的根路径

**返回:**
- MemoryTree 实例

**示例:**
```python
tree = MemoryTree("/path/to/memory")
```

**异常:**
- `ValueError`: 路径不存在

---

自动生成:
  - 从代码 docstring 生成
  - 保持同步

更新: 每次 API 变化
```

#### testing.md（测试指南）

```markdown
内容:
  1. 测试策略
  2. 如何运行测试
  3. 如何写测试
  4. 测试覆盖率要求
  5. Mock 和 Fixture
  6. CI/CD 集成

命令:
  # 运行所有测试
  pytest
  
  # 运行特定测试
  pytest tests/test_memory.py
  
  # 测试覆盖率
  pytest --cov=scripts

更新: 测试方法变化时
```

---

### 4. 用户文档（docs/user/）

#### 特点

```
✅ 面向使用者: 非技术背景也能懂
✅ 任务导向: 如何完成某个任务
✅ 循序渐进: 从简单到复杂
✅ 大量示例: 实际场景演示
```

#### installation.md（安装指南）

```markdown
内容:
  1. 系统要求
  2. 一键安装脚本
  3. 手动安装步骤
  4. Docker 部署
  5. 验证安装
  6. 卸载方法

风格:
  - 命令可复制
  - 截图辅助
  - 故障排查

受众: 所有用户
```

#### getting-started.md（入门教程）

```markdown
内容:
  1. 创建第一个笔记
  2. 查看笔记列表
  3. 搜索笔记
  4. 处理第一个图片
  5. 查看 confidence 变化
  6. 下一步学习

风格:
  - 手把手教学
  - 每步都有截图
  - 预期结果明确

受众: 新用户
```

#### user-guide.md（完整使用手册）

```markdown
结构:
  ## 1. 基础概念
     - 记忆三层
     - Confidence
     - 衰减机制
  
  ## 2. 日常使用
     - 创建笔记
     - 组织笔记
     - 搜索笔记
  
  ## 3. 多模态输入
     - 图片处理
     - 视频处理
     - PDF 处理
     - 微信记录
  
  ## 4. 高级功能
     - 批量处理
     - 自动化工作流
     - 自定义配置
  
  ## 5. 最佳实践
     - 笔记组织建议
     - 标签使用技巧
     - 衰减参数调优

受众: 所有用户（参考手册）
```

#### faq.md（常见问题）

```markdown
格式:

### Q: Confidence 是什么？

A: Confidence 表示笔记的可信度和重要性...

### Q: 为什么我的笔记消失了？

A: 笔记不会真正消失，只是因为 confidence 降低...

组织:
  - 按主题分类
  - 高频问题在前
  - 链接到详细文档

更新: 发现新的常见问题
```

---

### 5. 设计文档（docs/design/）

#### 特点

```
✅ 算法细节: 深入的技术说明
✅ 数学公式: 如何计算的
✅ 权衡分析: 为什么这样设计
✅ 可选阅读: 不影响使用
```

#### memory-decay-algorithm.md

```markdown
内容:
  1. 衰减算法背景
  2. 数学模型
  3. 参数说明
  4. 实现细节
  5. 性能分析
  6. 参考文献

受众: 
  - 想深入理解的开发者
  - 想调优参数的高级用户
  - 想改进算法的贡献者
```

---

## 🔄 文档维护流程

### 文档生命周期

```
1. PRD 阶段（设计时）
   docs/prd/ → 编写 → 锁定 → 归档
   
2. 开发阶段（实现时）
   docs/dev/ → 创建 → 持续更新
   
3. 发布前（准备时）
   docs/user/ → 完善 → 用户测试 → 定稿
   
4. 发布后（维护时）
   所有文档 → 根据反馈 → 持续改进
```

### 更新触发条件

```
立即更新:
  ✅ API 变化 → api-reference.md
  ✅ 配置变化 → setup.md, installation.md
  ✅ Bug 修复 → CHANGELOG.md, troubleshooting.md

每周更新:
  ✅ 新功能完成 → user-guide.md
  ✅ 测试增加 → testing.md

发布时更新:
  ✅ README.md
  ✅ CHANGELOG.md
  ✅ 所有用户文档
```

### 文档审查

```
代码提交时:
  - pre-commit hook 检查 docstring
  - CI 生成 API 文档
  - 检查文档链接有效性

每周审查:
  - 文档完整性
  - 示例代码可运行
  - 截图是否过期

发布前审查:
  - 用户文档完整
  - 所有链接有效
  - 无错别字
```

---

## 📝 文档编写规范

### Markdown 规范

```markdown
# 一级标题（文档标题，仅一个）

## 二级标题（主要章节）

### 三级标题（小节）

正文段落。

代码块:
```python
def example():
    pass
```

命令:
```bash
python script.py
```

引用:
> 重要提示

列表:
- 项目 1
- 项目 2

表格:
| 列1 | 列2 |
|-----|-----|
| 值1 | 值2 |

链接:
[文字](相对路径.md)

图片:
![说明](相对路径.png)
```

### 代码文档规范

```python
def calculate_confidence(
    note_path: str,
    source_type: str = "manual"
) -> float:
    """计算笔记的 confidence 值。
    
    根据来源类型、验证状态等因素计算笔记的可信度。
    
    Args:
        note_path: 笔记的完整路径
        source_type: 来源类型，可选值:
            - "manual": 手动创建
            - "web": 网页抓取
            - "ocr": OCR 识别
            
    Returns:
        confidence 值，范围 [0.0, 1.0]
        
    Raises:
        FileNotFoundError: 笔记文件不存在
        ValueError: source_type 无效
        
    Example:
        >>> conf = calculate_confidence(
        ...     "/path/to/note.md",
        ...     source_type="manual"
        ... )
        >>> print(conf)
        0.8
        
    Note:
        初始 confidence 会根据 source_type 设置:
        - manual: 0.8
        - web: 0.6
        - ocr: 0.5
    """
    pass
```

### 配置文档规范

```yaml
# config/memory.yaml

# 记忆模块配置
memory:
  # $OV/memory/ 的根路径
  # 必填，绝对路径
  root_path: "/path/to/memory"
  
  # 衰减配置
  decay:
    # 是否启用自动衰减
    # 默认: true
    enabled: true
    
    # 衰减速率（每天）
    # 范围: 0.0-1.0，越小衰减越快
    # 默认: 0.98（每天减少 2%）
    rate: 0.98
```

---

## 🎯 文档优先级

### Phase 1: MVP（Week 1-2）

```
必须:
  ✅ README.md（基础版）
  ✅ QUICK-START.md
  ✅ docs/dev/setup.md
  ✅ docs/dev/api-reference.md（核心 API）

可选:
  ⏳ docs/user/getting-started.md
```

### Phase 2: 功能完善（Week 3-4）

```
必须:
  ✅ docs/dev/architecture.md
  ✅ docs/dev/testing.md
  ✅ docs/user/installation.md
  ✅ docs/user/user-guide.md（基础）

可选:
  ⏳ docs/design/（算法文档）
```

### Phase 3: 发布准备（Week 5-6）

```
必须:
  ✅ README.md（完整版）
  ✅ CHANGELOG.md
  ✅ docs/user/（所有用户文档）
  ✅ docs/user/faq.md
  ✅ docs/dev/contributing.md

可选:
  ⏳ 视频教程
  ⏳ 博客文章
```

---

## 🔧 文档工具

### 自动化工具

```bash
# API 文档生成
pydoc-markdown

# Docstring 检查
pydocstyle scripts/

# 链接检查
markdown-link-check docs/**/*.md

# 拼写检查
aspell check docs/**/*.md

# 文档网站生成（可选）
mkdocs serve
```

### CI/CD 集成

```yaml
# .github/workflows/docs.yml

name: Documentation

on: [push, pull_request]

jobs:
  check-docs:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v2
      
      - name: Check links
        uses: gaurav-nelson/github-action-markdown-link-check@v1
        
      - name: Generate API docs
        run: |
          pip install pydoc-markdown
          pydoc-markdown --generate-api-docs
          
      - name: Check for changes
        run: |
          git diff --exit-code docs/dev/api-reference.md
```

---

## 📊 文档质量指标

### 完整性指标

```
✅ 每个公开 API 都有文档
✅ 每个用户功能都有使用说明
✅ 每个配置项都有说明
✅ 所有链接有效
✅ 所有代码示例可运行
```

### 可读性指标

```
✅ 一级标题清晰
✅ 段落长度适中（<5行）
✅ 代码块有语法高亮
✅ 有足够的示例
✅ 术语有解释
```

### 维护性指标

```
✅ 文档与代码在同一 PR
✅ API 变化自动检测
✅ 过期文档有警告
✅ 定期审查
```

---

## 🎉 总结

### 文档结构清晰

```
根目录/
  → 快速了解和开始

docs/prd/
  → 设计文档（已锁定）

docs/dev/
  → 开发者文档（持续更新）

docs/user/
  → 用户文档（面向使用）

docs/design/
  → 深入设计（可选）
```

### 维护流程明确

```
设计阶段:
  PRD 文档 → 锁定

开发阶段:
  开发文档 → 同步更新

发布前:
  用户文档 → 完善

发布后:
  所有文档 → 持续维护
```

### 质量有保障

```
✅ 自动化检查
✅ CI/CD 集成
✅ 定期审查
✅ 用户反馈
```

---

**📚 文档结构已锁定，现在可以按照这个体系开发了！**
