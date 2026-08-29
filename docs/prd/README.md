# Atelierr 记忆管理系统 - PRD 文档索引

**版本**: v1.0  
**状态**: 🔒 已锁定  
**日期**: 2026-08-27

> **当前生效契约**：架构 `ARCHITECTURE-LOCKED-V1.md`（**v1.2**：平面存储 +
> sidecar 索引 + 无状态 confidence）、验收 `../ACCEPTANCE-CRITERIA.md`、
> 实施 `IMPLEMENTATION-PLAN-PARALLEL.md`。
> 设计过程的历史文档已移入 `archive/`（见 `archive/README.md` 的过时项清单），
> 本索引其余内容如与上述契约冲突，以契约为准。

---

## 📚 文档导航

### 🔒 核心架构（已锁定）

这是系统的核心设计，已经过充分讨论和验证，作为实施的基础。

```
📄 ARCHITECTURE-LOCKED-V1.md
   - 三模块架构定义
   - 技术栈选择
   - 数据结构设计
   - API 接口规范
   - 🔒 已锁定，开始实施
```

**快速链接**: [ARCHITECTURE-LOCKED-V1.md](./ARCHITECTURE-LOCKED-V1.md)

---

### 📊 架构可视化

帮助理解系统设计的图解。

| 图解 | 说明 | 文件 |
|------|------|------|
| **三模块架构** | 系统整体架构，三个模块的位置和关系 | [architecture-diagram.png](./architecture-diagram.png) |
| **数据流程** | 用户创建笔记的完整数据流 | [dataflow-diagram.png](./dataflow-diagram.png) |
| **文件结构** | $OV/ 和 Atelierr/ 的目录组织 | [file-structure-diagram.png](./file-structure-diagram.png) |

**快速参考**: [README-visual.md](./README-visual.md)

---

### 🎨 扩展方案

在核心架构基础上的功能扩展。

#### 多模态输入处理

支持微信、视频、图片、PDF、音频等多种输入类型。

```
📄 multimodal-input-processing.md (21KB)
   - 5种输入类型的处理策略
   - 预处理层设计
   - 技术栈和实现路径
   
📊 multimodal-flow-diagram.png
   - 从输入到系统的完整流程
   
📄 multimodal-examples.md (25KB)
   - 5个详细实际案例
   - 完整的输入/输出示例
```

**核心思想**: 任何输入 → 预处理 → Markdown + 附件 → 现有系统

---

#### 大文件处理

智能处理 1GB+ 视频和 200MB+ PDF。

```
📄 large-file-handling.md (28KB)
   - 三种处理策略（提取、归档、云备份）
   - 详细配置方案
   - 成本分析
   
📊 large-file-strategy-diagram.png
   - 大文件处理可视化
   
📄 large-file-examples.md (20KB)
   - 1GB 视频处理完整流程
   - 200MB PDF 处理示例
   - 真实用户反馈
```

**核心优势**: 99% 空间节省，0% 信息损失

---

### 🚀 实施计划（已锁定）

详细的 8-10 周实施路线图。

```
📄 IMPLEMENTATION-PLAN-PARALLEL.md (32KB)
   - 6个阶段，每周任务清单
   - 详细的验收标准
   - 风险识别和应对
   - 立即可执行的下一步行动
   
📊 implementation-timeline.png
   - 可视化时间线
   - 里程碑和交付物
```

**第一步**: Week 1 - 实现 `scripts/memory.py` 核心模块

---

## 🎯 快速开始

### 1. 理解核心架构

```
推荐阅读顺序:
  1. README-visual.md (5分钟快速了解)
  2. ARCHITECTURE-LOCKED-V1.md (30分钟详细理解)
  3. 查看三个架构图
```

### 2. 了解扩展能力

```
根据需求选择:
  - 需要处理多种输入? → multimodal-input-processing.md
  - 有大文件问题? → large-file-handling.md
```

### 3. 开始实施

```
follow IMPLEMENTATION-PLAN-PARALLEL.md:
  - Week 1: 记忆模块核心
  - Week 2: 衰减和搜索
  - Week 3: Web 界面
  - ...
```

---

## 📁 完整文件清单

```
docs/prd/
├── README.md                              (本文件)
│
├── 🔒 核心架构
│   └── ARCHITECTURE-LOCKED-V1.md          (25KB, 已锁定)
│
├── 📊 架构图解
│   ├── architecture-diagram.png           (65KB)
│   ├── dataflow-diagram.png               (36KB)
│   ├── file-structure-diagram.png         (73KB)
│   └── README-visual.md                   (5KB, 图解索引)
│
├── 🎨 多模态输入
│   ├── multimodal-input-processing.md     (21KB, 方案)
│   ├── multimodal-flow-diagram.png        (图解)
│   └── multimodal-examples.md             (25KB, 案例)
│
├── 💾 大文件处理
│   ├── large-file-handling.md             (28KB, 方案)
│   ├── large-file-strategy-diagram.png    (图解)
│   └── large-file-examples.md             (20KB, 案例)
│
├── 🚀 实施计划
│   ├── IMPLEMENTATION-PLAN-PARALLEL.md             (32KB, 已锁定)
│   └── implementation-timeline.png        (时间线图)
│
└── 📖 其他文档
    ├── architecture-v4-final-summary.md   (早期版本)
    ├── architecture-specification.md       (早期版本)
    ├── minimal-modification-plan.md       (早期讨论)
    ├── requirements-summary.md            (需求总结)
    └── ... (其他历史文档)
```

---

## 🎉 方案总览

### 核心架构（三模块）

```
模块 1: Web 界面 (Flatnotes)
   📍 Docker 容器
   🎯 提供网页访问
      ↓
      
模块 2: 记忆模块 (Memory-Like-A-Tree)
   📍 scripts/memory.py
   🎯 管理记忆生命周期
   🧠 Confidence-based 衰减
      ↓
      
模块 3: Atelierr Core
   📍 .claude/agents/
   🎯 15+ Agents 协作
   🤖 反思、阅读、综合
```

### 扩展能力

```
输入处理:
  ✅ 微信聊天记录
  ✅ 抖音/YouTube 视频
  ✅ 图片/截图 (OCR)
  ✅ PDF 文档
  ✅ 音频录音

大文件处理:
  ✅ 1GB 视频 → 5MB (99.5% 压缩)
  ✅ 200MB PDF → 3MB (98.5% 压缩)
  ✅ 完整信息保留
  ✅ Git 友好

记忆管理:
  ✅ 三层分级 (短期/中期/长期)
  ✅ 自动衰减
  ✅ 访问增强
  ✅ 智能搜索
```

---

## 📊 关键指标

### 功能指标

```
✅ 支持 5+ 种输入类型
✅ 大文件压缩比 >98%
✅ 自动化程度 >90%
✅ Confidence 计算准确
✅ 衰减机制有效
```

### 性能指标

```
✅ 1000 笔记搜索 <100ms
✅ 1GB 视频处理 <15分钟
✅ 200MB PDF 处理 <5分钟
✅ 内存使用 <2GB
✅ Git 仓库 <1GB
```

### 质量指标

```
✅ 测试覆盖率 >85%
✅ 文档完整度 100%
✅ 零关键 bug
✅ 用户满意度 >90%
```

---

## 🗓️ 实施时间线

```
Week 1-2:  ✅ 记忆模块核心 (MVP)
Week 3:    ✅ Web 界面集成
Week 4:    ✅ 基础输入处理
Week 5-6:  ✅ 大文件处理
Week 7-8:  ✅ 多模态输入
Week 9-10: ✅ 优化和测试
           🎉 v1.0 发布
```

详见: [implementation-timeline.png](./implementation-timeline.png)

---

## 💡 设计亮点

### 1. 架构优雅

```
✅ 三个模块，职责清晰
✅ 松耦合，易扩展
✅ 保持简单，避免过度设计
```

### 2. 实用性强

```
✅ 解决真实问题（信息过载）
✅ 渐进式实现（Week 2 可用 MVP）
✅ 多模态输入（适应各种场景）
```

### 3. 技术合理

```
✅ 成熟技术栈
✅ 开源优先
✅ 性能可靠
```

### 4. 成本可控

```
✅ 本地方案: $0
✅ 云存储方案: ~$2-5/月
✅ 计算资源: 普通笔记本即可
```

---

## 🔑 核心创新

### 1. Confidence-based 记忆管理

不是简单的"创建时间"或"最后修改时间"，而是基于多维度的置信度：

```python
confidence = f(
    source_type,      # 来源可靠性
    validation,       # 验证状态
    access_frequency, # 访问频率
    time_decay       # 时间衰减
)
```

### 2. 智能大文件提取

不保存完整大文件，只提取关键信息：

```
1GB 视频 → 完整转录 + 关键帧 → 5MB
99% 空间节省，0% 信息损失
```

### 3. 统一的 Markdown 输出

所有输入最终都转化为标准 Markdown：

```
任何格式 → 预处理 → Markdown + 附件
→ Git 可追踪
→ 人类可读
→ 易于搜索
```

---

## 🎯 下一步行动

### 立即开始

```bash
# 1. 阅读核心架构
cat docs/prd/ARCHITECTURE-LOCKED-V1.md

# 2. 阅读实施计划
cat docs/prd/IMPLEMENTATION-PLAN-PARALLEL.md

# 3. 创建项目结构
mkdir -p Atelierr/scripts/processors
mkdir -p Atelierr/config
mkdir -p Atelierr/tests

# 4. 初始化 Python 环境
cd Atelierr/
python3 -m venv .venv
source .venv/bin/activate
pip install pyyaml watchdog pytest

# 5. 创建第一个文件
touch scripts/memory.py
```

### 本周目标 (Week 1)

```
Day 1-2: 项目初始化 + MemoryTree 类设计
Day 3-4: Confidence 计算实现
Day 5-7: 衰减机制实现 + 测试

交付物: 可运行的 memory.py + 测试
```

---

## 📞 支持

### 文档问题

如果文档有不清楚的地方：

1. 先查看对应的可视化图解
2. 查看实际案例（examples.md）
3. 查看实施计划的详细任务清单

### 技术问题

实施过程中遇到技术问题：

1. 查看 IMPLEMENTATION-PLAN-PARALLEL.md 的"风险和应对"章节
2. 参考各个 examples.md 中的实际代码示例
3. 查看架构文档的 API 规范

---

## 🎉 总结

### 完整方案

```
✅ 核心架构清晰（三模块）
✅ 扩展能力完整（多模态 + 大文件）
✅ 实施计划详细（8-10 周）
✅ 文档齐全（10+ 文档 + 图解）
```

### 可以开始实施

```
✅ 架构已锁定
✅ 计划已确定
✅ 第一步明确
✅ 风险已识别
```

### 预期成果

```
8-10 周后:
  ✅ 功能完整的记忆管理系统
  ✅ 支持 5+ 种输入类型
  ✅ 99% 空间节省
  ✅ Git 友好 (<1GB)
  ✅ 完整文档和测试
  🎉 v1.0 发布
```

---

**🚀 准备好开始了吗？**

**第一个文件**: `scripts/memory.py`  
**第一个功能**: Confidence 计算  
**第一个里程碑**: Week 2 - MVP 可用

Let's build! 🎨
