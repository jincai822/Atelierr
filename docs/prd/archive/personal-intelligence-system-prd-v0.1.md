# Personal Intelligence System - Product Requirements Document v0.1

**Document Version:** v0.1
**Last Updated:** 2026-08-26
**Status:** Draft
**Author:** AI Assistant (based on Atelier)

---

## 文档目的

本 PRD 定义 **Personal Cognition & Intelligence System**（个人认知与智能系统）的产品边界、架构设计、领域模型、模块职责与能力契约。

**核心目标：**
1. 理解产品为什么存在
2. 明确产品边界（什么在系统内，什么在系统外）
3. 分析 Atelier 与目标产品之间的 Gap
4. 定义八模块架构（新增 Memory System）
5. 定义 Domain Model 和 Capability Contract
6. 明确 V0/V1 实现范围
7. 识别风险与延迟决策

**重要约束：**
- 本 PRD 阶段 **不进行大规模代码开发**
- 保持 Atelier 已确认的需求和设计原则
- 优先保证 **高效率、简洁性、鲁棒性**

---

## 目录

1. [产品定位与核心闭环](#1-产品定位与核心闭环)
2. [产品边界：已发布知识层](#2-产品边界已发布知识层)
3. [Atelier 当前实现分析](#3-atelier-当前实现分析)
4. [认知领域模型](#4-认知领域模型)
5. [八模块架构](#5-八模块架构)
6. [能力契约](#6-能力契约)
7. [V0/V1 范围与验收标准](#7-v0v1-范围与验收标准)
8. [风险与开放问题](#8-风险与开放问题)
9. [延迟决策](#9-延迟决策)
10. [实施注意事项](#10-实施注意事项)
11. [下一步行动](#11-下一步行动)

**附录：**
- [Appendix A: 100G 知识库场景分析](#appendix-a-100g-知识库场景分析)
- [Appendix B: 支持工具](#appendix-b-支持工具)
- [Appendix C: 架构决策记录](#appendix-c-架构决策记录)
- [Appendix D: 未来演进路径](#appendix-d-未来演进路径)

---

## 1. 产品定位与核心闭环

### 1.1 业务核心闭环

Personal Intelligence System 的核心业务循环：

```
SESSION START
会话启动
  ↓
HEALTH CHECK (quiet by default)
健康检查（默认静默）
  - Weekly review 过期检查
  - Inbox 待处理检查
  - 结构完整性检查
  ↓
KNOW
知道（世界状态 + 个人认知）
  ↓
MEMORY SYSTEM
记忆系统（新增模块 8）
  - Long-term Memory Retrieval（长期记忆检索）
  - Working Memory Management（工作记忆管理）
  - Episodic Memory Reconstruction（情景记忆重建）
  - Context Budget Control（上下文预算控制）
  ↓
THINK
理解 / 判断 / 建模
  - Cost Estimation（expensive ops）
  ↓
ACT
决策 / 行动
  - Budget Check（执行前成本检查）
  - Cost Logging（API 调用日志）
  ↓
LEARN
反馈 / 证伪 / 纠错 / 更新
  - Cognition Update
  - Memory Update（更新访问频率、重要性评分）
  - Cost Analysis（事后成本分析）
  ↓
KNOW (Updated Cognition)
更新后的认知
  ↓
HEALTH CHECK (on error/completion)
健康检查（异常时触发）
```

**关键特性：**
- ✅ **Memory System 作为第八个核心模块**（支持 100G 知识库）
- ✅ **Health Checker 保持脚本工具**（按需运行，零成本）
- ✅ **Cost Analyzer 保持脚本工具**（事后分析）
- ✅ **人在环中**（Human-in-the-loop）— 所有关键决策需要用户确认
- ✅ **本地优先**（Local-first）— 数据存储在本地，用户拥有完整控制权

### 1.2 产品定位

**Personal Intelligence System = Atelier-derived Cognition Kernel + External Knowledge Compiler**


| 层级 | 组件 | 职责 |
|------|------|------|
| **用户层** | Human User | 提供意图、审批决策、消费洞察 |
| **认知内核层** | Personal Intelligence System | KNOW → THINK → ACT → LEARN 循环 |
| **已发布知识层** | Published Knowledge Layer | 外部编译器生成的结构化知识 |
| **知识生产层** | External Knowledge Compiler (nashsu/llm_wiki) | 从原始资料生成结构化知识 |

**本系统边界：**
- ✅ 在系统内：认知内核、记忆系统、反思循环、决策追踪、智能体编排
- ❌ 在系统外：知识生产（由 nashsu/llm_wiki 等外部工具完成）

### 1.3 架构决策：八模块 + 两工具

**八个核心模块：**
1. Cognition Flywheel Core（认知飞轮核心）
2. Agent Runtime（智能体运行时）
3. Workflow Engine（工作流引擎）
4. Knowledge Vault（知识库）
5. Model Gateway（模型网关）
6. Feedback Loop（反馈循环）
7. Human Interface（人机交互）
8. **Memory System（记忆系统）** ← 新增模块

**两个脚本工具：**
1. Health Checker（健康检查工具）
2. Cost Analyzer（成本分析工具）

**架构原则：**
- **简洁性** — 8 个模块 + 2 个工具，清晰的职责边界
- **鲁棒性** — 工具失败不影响核心，Memory System 具备降级能力
- **效率性** — 工具零成本运行，Memory System 智能预取和缓存
- **可演进性** — V0 使用脚本工具，V1 升级 Memory System，V2 分布式扩展

详细架构决策请参考 [Appendix C: 架构决策记录](#appendix-c-架构决策记录)。

---

## 2. 产品边界：已发布知识层

### 2.1 什么是"已发布知识层"？

**定义：**
已发布知识层（Published Knowledge Layer）是外部知识编译器（如 nashsu/llm_wiki）生成的结构化、高质量知识输出。

**特征：**
- ✅ 结构化格式（Markdown, JSON, YAML）
- ✅ 元数据完整（来源、时间戳、作者、标签）
- ✅ 质量已验证（通过编译器的质量门控）
- ✅ 可直接摄入（符合本系统的知识格式规范）

**示例：**
```yaml
# wiki/programming/python-asyncio.md
---
title: Python asyncio 编程模型
created: 2026-08-20
source: 《Fluent Python》Chapter 18
quality: externally_certified
tags: [programming, python, concurrency]
---

## Claims

### C1: asyncio 基于协程和事件循环
- **Anchor:** 《Fluent Python》p.532
- **Evidence:** "asyncio 的核心是事件循环和协程..."
- **Trust:** 0.95 (权威书籍)

### C2: asyncio.gather() 并发执行多个协程
- **Anchor:** 官方文档 https://docs.python.org/3/library/asyncio-task.html
- **Evidence:** "Run awaitable objects concurrently..."
- **Trust:** 1.0 (官方文档)
```

### 2.2 系统边界

| 职责 | 在系统内 | 在系统外 |
|------|----------|----------|
| 知识生产 | ❌ | ✅ nashsu/llm_wiki |
| 知识摄入 | ✅ Published Knowledge Ingestion | — |
| 知识验证 | ✅ TrustRank 传播 | ✅ 外部编译器质量门控 |
| 知识存储 | ✅ Knowledge Vault | — |
| 知识检索 | ✅ Memory System | — |
| 知识应用 | ✅ Cognition Core | — |

**关键原则：**
1. **单一职责** — 本系统专注于"认知与智能"，不做"知识生产"
2. **清晰接口** — 通过 Published Knowledge Layer 与外部编译器解耦
3. **质量门控** — 外部编译器保证输入质量，本系统信任并使用

### 2.3 与 nashsu/llm_wiki 的集成

**llm_wiki 职责：**
- 从原始资料（PDF、视频、网页、书籍）生成结构化知识
- 质量控制（事实核查、来源追溯、置信度评估）
- 输出符合本系统格式的"已发布知识"

**本系统职责：**
- 摄入"已发布知识"到 Knowledge Vault
- 通过 Memory System 索引和检索
- 在 Cognition Core 中应用这些知识
- 通过 Feedback Loop 更新知识的个人化标注（重要性、相关性）

**集成接口：**
```python
# 已发布知识格式规范
class PublishedKnowledge:
    title: str
    content: str  # Markdown
    metadata: KnowledgeMetadata
    claims: List[Claim]
    sources: List[Source]
    quality_level: QualityLevel  # L1-L5
    
class KnowledgeMetadata:
    created: datetime
    source: str  # URL, 书名, 视频链接
    author: str
    tags: List[str]
    quality: QualityLevel
    
# 摄入接口
def ingest_published_knowledge(knowledge: PublishedKnowledge) -> None:
    """
    将已发布知识摄入系统
    1. 存储到 Knowledge Vault ($OV/wiki/)
    2. 通过 Memory System 建立索引
    3. 更新 TrustRank 图
    """
    pass
```

**质量级别映射：**

| llm_wiki 输出 | 本系统 L1-L5 |
|--------------|-------------|
| 高质量书籍、论文 | L4 (Externally Certified) |
| 权威网站、官方文档 | L3 (Locally Certified Wiki) |
| 博客、视频笔记 | L2 (Working) |
| 原始摘抄 | L1 (Raw) |

---

### 2.4 多模态资料来源处理方案

**你的资料来源场景：**
1. 网站视频（YouTube, Bilibili, 在线课程）
2. 本地视频（手机录制、下载的视频文件）
3. PDF（论文、书籍、报告、扫描文档）
4. 准备看的书（未读书单、购买意向）
5. 其他：音频播客、图片、网页文章

#### 2.4.1 资料来源分类

| 类型 | 示例 | 处理流程 | 负责方 | 进入系统路径 |
|------|------|----------|--------|--------------|
| **网站视频** | YouTube, Bilibili, Coursera | 转录 → 结构化 → 知识提取 | nashsu/llm_wiki | Published Knowledge → Module 4 → Module 8 索引 |
| **本地视频** | 手机录制、会议录像 | 转录 → 结构化 → 知识提取 | nashsu/llm_wiki | Published Knowledge → Module 4 → Module 8 索引 |
| **PDF（论文）** | arXiv论文、学术期刊 | PDF文本提取 → 结构化 → 知识提取 | nashsu/llm_wiki | Published Knowledge → Module 4 → Module 8 索引 |
| **PDF（书籍）** | 技术书籍、电子书 | 章节提取 → 结构化 → 知识提取 | nashsu/llm_wiki | Published Knowledge → Module 4 → Module 8 索引 |
| **PDF（扫描件）** | 收据、合同、证书 | OCR → 文本提取 → 存档 | nashsu/llm_wiki | 直接存储到 `$OV/<domain>/raw/` + Module 8 索引 |
| **准备看的书** | 书单、购买意向 | 元数据录入 | 本系统 (Module 1) | Learning Agenda |
| **音频播客** | Podcast, 讲座录音 | 转录 → 结构化 → 知识提取 | nashsu/llm_wiki | Published Knowledge → Module 4 → Module 8 索引 |
| **网页文章** | 博客、新闻、文档 | 正文提取 → 结构化 | nashsu/llm_wiki | Published Knowledge → Module 4 → Module 8 索引 |
| **图片** | 白板照片、图表截图 | OCR/图像识别 → 文本提取 | nashsu/llm_wiki | `$OV/<domain>/raw/` + Module 8 索引 |

#### 2.4.2 详细处理流程

##### A. 网站视频处理

```yaml
输入:
  - YouTube URL: https://www.youtube.com/watch?v=xxxxx
  - Bilibili URL: https://www.bilibili.com/video/BVxxxxx
  
处理步骤 (nashsu/llm_wiki):
  1. 下载视频元数据（标题、作者、描述、时长）
  2. 提取字幕/转录音频
     - 优先使用官方字幕
     - 无字幕则调用 Whisper API 转录
  3. 结构化内容
     - 按时间戳分段
     - 提取关键概念
     - 识别重要时刻（highlight）
  4. 生成 Published Knowledge
     - 标题：[视频标题]
     - 来源：[视频URL]
     - 内容：转录文本 + 时间戳
     - 关键概念：提取的 Claims
     
输出到本系统:
  - $OV/wiki/[domain]/[topic].md
  - 质量级别：L2 (Working)
  - Module 8 索引：文本embedding + 视频转录标记
```

**示例输出：**
```markdown
---
title: "Python asyncio 深度解析"
source: "https://www.youtube.com/watch?v=xxxxx"
source_type: video
author: "Corey Schafer"
duration: "45:23"
quality: L2
created: 2026-08-20
---

## 转录文本

[00:00] 今天我们来讲 asyncio...
[05:30] 协程的核心概念是...
[15:20] 让我们看一个实际例子...

## 关键概念

### C1: asyncio 基于事件循环
- **Timestamp:** 05:30-08:45
- **Evidence:** "协程的核心概念是非抢占式多任务..."
- **Trust:** 0.85 (专家讲解)

### C2: async/await 语法
- **Timestamp:** 15:20-22:10
- **Code Example:** ...
- **Trust:** 0.90
```

##### B. 本地视频处理

```yaml
输入:
  - 本地视频文件：/path/to/meeting_recording.mp4
  - 元数据（可选）：会议主题、参与人、日期
  
处理步骤 (nashsu/llm_wiki):
  1. 视频元数据提取（分辨率、时长、编码格式）
  2. 音频提取 → Whisper API 转录
  3. 说话人识别（Diarization）
     - 区分不同说话人
     - 标记说话人切换
  4. 结构化内容
     - 按主题分段
     - 提取行动项（Action Items）
     - 提取决策（Decisions）
  5. 生成 Published Knowledge
  
输出到本系统:
  - $OV/meetings/[date]_[topic].md
  - 原始视频存档：$OV/meetings/raw/[date]_[topic].mp4
  - 质量级别：L2 (Working)
  - Module 8 索引：转录文本 + 说话人标记 + 时间戳
```

##### C. PDF 处理（分类处理）

**C1. 学术论文 (arXiv, IEEE, ACM)**

```yaml
处理步骤 (nashsu/llm_wiki):
  1. PDF文本提取 (scripts/paper_cache.py)
     - pdftotext -layout
     - 保留表格、公式结构
  2. 结构识别
     - Abstract, Introduction, Methods, Results, Discussion
     - 参考文献解析
  3. 关键内容提取
     - 核心贡献（Main Contributions）
     - 方法论（Methodology）
     - 实验结果（Results）
     - 局限性（Limitations）
  4. 生成 Published Knowledge
  
输出:
  - $OV/papers/[firstauthor]_[venue]_[year]_[topic].md
  - 原始PDF：$OV/papers/[firstauthor]_[venue]_[year]_[topic].pdf
  - 质量级别：L4 (Externally Certified) - 如果是同行评审
  - Module 8 索引：全文文本 + 章节结构 + 公式/表格引用
```

**C2. 技术书籍**

```yaml
处理步骤 (nashsu/llm_wiki):
  1. PDF文本提取 + OCR（如果是扫描版）
  2. 章节目录解析
  3. 按章节分割
  4. 每章独立处理
     - 提取核心概念
     - 提取代码示例
     - 提取最佳实践
  5. 生成 Published Knowledge（按章节）
  
输出:
  - $OV/books/[author]_[title]/
    - chapter_01.md
    - chapter_02.md
    - ...
    - index.md (书籍总览)
  - 原始PDF：$OV/books/[author]_[title]/[title].pdf
  - 质量级别：L3 (Locally Certified) - 高质量技术书籍
  - Module 8 索引：按章节索引 + 代码示例 + 概念提取
```

**C3. 扫描文档（收据、合同、证书）**

```yaml
处理步骤 (nashsu/llm_wiki):
  1. OCR文本识别
  2. 结构化信息提取
     - 收据：商家、日期、金额、项目
     - 合同：甲乙方、日期、关键条款
     - 证书：颁发机构、日期、证书号
  3. 生成结构化记录
  
输出:
  - $OV/[domain]/raw/[date]_[type]_[slug].pdf (原始PDF)
  - $OV/[domain]/[date]_[type]_[slug].md (结构化提取)
  - 质量级别：L1 (Raw)
  - Module 8 索引：OCR文本 + 结构化字段
```

##### D. 准备看的书（书单管理）

```yaml
输入:
  - 书名、作者、ISBN
  - 购买链接（可选）
  - 阅读动机（为什么要读）
  
处理步骤 (本系统 Module 1):
  1. 创建 Learning Agenda 条目
  2. 关联到相关 Open Question
  3. 优先级评估
  
输出:
  - $OV/learning/reading_list.md
  - Learning Agenda 条目（Module 1）
  
数据结构:
  type: LearningAgenda
  topic: "[书名]"
  motivation: "学习 [主题] 以解决 [Open Question]"
  status: PLANNED
  resources:
    - type: BOOK
      title: "[书名]"
      author: "[作者]"
      isbn: "[ISBN]"
      purchase_url: "[链接]"
  priority: HIGH | MEDIUM | LOW
  
读完后:
  - 如果购买/获得PDF → 按 C2 处理（技术书籍）
  - 生成 Published Knowledge
  - 更新 Learning Agenda 状态为 COMPLETED
```

##### E. 音频播客处理

```yaml
输入:
  - Podcast URL / RSS Feed
  - 本地音频文件（.mp3, .m4a）
  
处理步骤 (nashsu/llm_wiki):
  1. 音频转录（Whisper API）
  2. 说话人识别
  3. 按主题分段
  4. 提取关键观点
  5. 生成 Published Knowledge
  
输出:
  - $OV/podcasts/[show]_[episode]_[date].md
  - 原始音频：$OV/podcasts/raw/[show]_[episode]_[date].m4a
  - 质量级别：L2 (Working)
  - Module 8 索引：转录文本 + 时间戳 + 说话人标记
```

##### F. 网页文章处理

```yaml
输入:
  - URL
  - Readwise 导入
  
处理步骤 (nashsu/llm_wiki):
  1. 正文提取（去除广告、导航栏）
  2. 元数据提取（标题、作者、发布日期）
  3. 图片下载（可选）
  4. 结构化内容
  5. 生成 Published Knowledge
  
输出:
  - $OV/articles/[date]_[title_slug].md
  - 质量级别：根据来源判断
    - 权威网站（MDN, 官方文档）：L3
    - 个人博客：L2
  - Module 8 索引：全文文本 + 元数据
```

##### G. 图片处理（白板、图表）

```yaml
输入:
  - 图片文件（.jpg, .png, .heic）
  - 上下文说明（可选）
  
处理步骤 (nashsu/llm_wiki):
  1. OCR文本识别（如果包含文字）
  2. 图像分类（白板/图表/照片）
  3. 内容描述生成（GPT-4V）
  4. 结构化信息提取
     - 白板：识别列表、流程图、关键词
     - 图表：提取数据和趋势
  5. 生成 Published Knowledge
  
输出:
  - $OV/[domain]/raw/[date]_[slug].jpg (原始图片)
  - $OV/[domain]/[date]_[slug].md (提取的文本和描述)
  - 质量级别：L1 (Raw)
  - Module 8 索引：OCR文本 + 图像embedding (CLIP) + 描述
```

#### 2.4.3 Module 8 (Memory System) 的多模态索引

**索引策略：**

| 内容类型 | 索引方法 | 向量模型 | 特殊处理 |
|----------|----------|----------|----------|
| 文本（文章、笔记） | 语义embedding | Sentence Transformers | 分段索引（512 tokens/段） |
| PDF文本 | 语义embedding + 章节索引 | Sentence Transformers | 按章节/页码索引 |
| 视频转录 | 语义embedding + 时间戳索引 | Sentence Transformers | 时间戳标记，支持跳转 |
| 音频转录 | 语义embedding + 时间戳索引 | Sentence Transformers | 说话人标记 |
| 图片 | 视觉embedding | CLIP | OCR文本单独索引 |
| 代码片段 | 代码语义embedding | CodeBERT | 语言标记、函数名索引 |

**多模态检索示例：**

```python
# 用户查询："Python asyncio 的最佳实践"

# Memory System 检索流程：
results = memory_system.multi_modal_search(
    query="Python asyncio 最佳实践",
    filters={
        "source_types": ["video", "article", "pdf", "book"],
        "quality": ">=L2",
        "created_after": "2024-01-01"
    },
    top_k=10
)

# 返回结果（按相关性排序）：
[
    {
        "type": "book_chapter",
        "title": "《Fluent Python》Chapter 18: Concurrency with asyncio",
        "relevance": 0.95,
        "source": "$OV/books/ramalho_fluent_python/chapter_18.md",
        "quality": "L3"
    },
    {
        "type": "video_transcript",
        "title": "Python asyncio 深度解析",
        "relevance": 0.92,
        "timestamp": "15:20-22:10",  # 相关片段
        "source": "$OV/wiki/programming/python_asyncio_video.md",
        "quality": "L2"
    },
    {
        "type": "article",
        "title": "Asyncio Best Practices - Real Python",
        "relevance": 0.88,
        "source": "$OV/articles/2025-03-15_asyncio_best_practices.md",
        "quality": "L3"
    },
    {
        "type": "paper",
        "title": "Performance Analysis of Python Async Frameworks",
        "relevance": 0.85,
        "source": "$OV/papers/smith_icse_2025_async_perf.md",
        "quality": "L4"
    }
]
```

#### 2.4.4 工作流集成

**完整流程（从原始资料到认知应用）：**

```
1. 资料获取
   ↓
   用户提供：YouTube URL / 本地视频 / PDF / 书单
   ↓
2. 外部编译（nashsu/llm_wiki）
   ↓
   转录/提取 → 结构化 → 质量控制 → Published Knowledge
   ↓
3. 摄入系统（Module 4: Knowledge Vault）
   ↓
   存储到 $OV/ → 分配质量级别 → 更新 TrustRank
   ↓
4. 索引建立（Module 8: Memory System）
   ↓
   文本embedding → 视觉embedding (如有) → 时间戳索引 → 元数据索引
   ↓
5. 认知应用（Module 1: Cognition Core）
   ↓
   语义检索 → 形成 Beliefs → 回答 Open Questions → 做出 Decisions
   ↓
6. 反馈循环（Module 6: Feedback Loop）
   ↓
   使用记录 → 更新重要性评分 → 优化索引
```

#### 2.4.5 V0/V1/V2 实现路线图

**V0 阶段（MVP，< 10GB）：**
- ✅ PDF处理（已有 scripts/paper_cache.py）
- ✅ 文本文章处理
- ⬜ 视频转录（手工转录 → 手工整理）
- ⬜ 书单管理（Learning Agenda 手工维护）

**V1 阶段（10-100GB）：**
- ✅ 自动PDF处理（OCR + 结构化）
- ✅ 视频自动转录（Whisper API）
- ✅ 音频播客转录
- ✅ 图片OCR + CLIP embedding
- ✅ 多模态统一检索
- ✅ 时间戳跳转（视频/音频）

**V2 阶段（> 100GB）：**
- ✅ 分布式多模态索引
- ✅ 视频内容理解（场景识别、关键帧提取）
- ✅ 跨模态检索（用文本查图片、用图片查视频）
- ✅ 自动书籍购买推荐（基于 Learning Agenda）

---

## 3. Atelier 当前实现分析

### 3.1 Atelier 架构概览

Atelier 是一个 **local-first Zettelkasten system**，专注于 **reflective thinking**。

**核心组件：**

| 组件 | 文件/目录 | 职责 |
|------|-----------|------|
| Knowledge Vault | `$OV/` | L1-L5 分层知识存储 |
| Intent Router | `harness/intents.toml` | 路由用户意图到工作流 |
| Specialist Agents | `.claude/agents/` | 11 个专业智能体 |
| Scripts & Tools | `scripts/` | 30+ 工具脚本 |
| Protocols | `protocols/` | 工作流程定义 |
| Wiki Schema | `$OV/wiki/` | 结构化 wiki 条目 |
| TrustRank | `scripts/trustrank.py` | 信任传播引擎 |
| Context Manager | `scripts/context_bundle.py` | 上下文加载 |
| Health Checker | `scripts/cues.py` | 健康检查 |
| Cost Analyzer | `scripts/pricing.py` | 成本分析 |
| Semantic Search | `scripts/semantic.py` | 向量搜索 |
| PDF Processor | `scripts/paper_cache.py` | PDF 提取 |

### 3.2 Atelier 的核心能力

#### 3.2.1 知识分层（L1-L5）

```
L5 Foundation（基础知识）
  ↑
L4 Externally Certified（外部认证）
  ↑
L3 Locally Certified Wiki（本地认证 Wiki）
  ↑
L2 Working（工作笔记）
  ↑
L1 Raw（原始捕获）
```

**验证路径：**
- L1 → L2：人工整理
- L2 → L3：本地验证（TrustRank）
- L3 → L4：外部证据支持
- L4 → L5：多次引用 + 时间验证

#### 3.2.2 Wiki Schema

```yaml
# wiki/topic.md
---
title: Topic Title
created: 2026-08-20
updated: 2026-08-26
tags: [tag1, tag2]
---

## Claims

### C1: Claim Statement
- **Anchor:** Source reference
- **Evidence:** Supporting evidence
- **Trust:** 0.95
- **Passes:** [Test case 1, Test case 2]
- **Fails:** [Known limitation]
- **Since:** 2026-08-20
- **Until:** still-valid
```

#### 3.2.3 TrustRank 引擎

**算法：**
```python
def trustrank(claim: Claim) -> float:
    base_trust = source_trust(claim.anchor)
    evidence_boost = sum(evidence_trust(e) for e in claim.evidence)
    time_decay = age_factor(claim.since)
    contradiction_penalty = contradiction_count(claim)
    
    return base_trust * evidence_boost * time_decay - contradiction_penalty
```

**特性：**
- 确定性（相同输入 → 相同输出）
- 可解释（每个 trust 值都有来源追溯）
- 时间衰减（旧知识降低 trust）
- 证伪机制（反例会降低 trust）

#### 3.2.4 Specialist Agents (Le Cercle)

| Agent | 职责 | 文件 |
|-------|------|------|
| Researcher | 收集证据 | `.claude/agents/researcher.md` |
| Reader | 结构化阅读 | `.claude/agents/reader.md` |
| Scholar | 深度阅读（论文） | `.claude/agents/scholar.md` |
| Challenger | 挑战假设 | `.claude/agents/challenger.md` |
| Curator | 知识整理 | `.claude/agents/curator.md` |
| Synthesizer | 综合洞察 | `.claude/agents/synthesizer.md` |
| Thinker | 独立思考 | `.claude/agents/thinker.md` |
| Reviewer | 质量审查 | `.claude/agents/reviewer.md` |
| Scribe | 记录内容 | `.claude/agents/scribe.md` |
| Librarian | 推荐资源 | `.claude/agents/librarian.md` |
| Meeting | 会议纪要 | `.claude/agents/meeting.md` |

#### 3.2.5 上下文管理

```python
# scripts/context_bundle.py (1482 行)

def build_context(route: str, profile: str, budget: int = 20_000) -> str:
    """
    构建有界上下文
    
    Args:
        route: 意图路由（如 "reflect", "read", "synthesize"）
        profile: 用户配置（如 "pm", "engineer"）
        budget: 字符数预算（默认 20KB）
    
    Returns:
        拼接后的上下文字符串
    """
    context_parts = []
    
    # 1. 加载 profile 配置
    context_parts.append(load_profile(profile))
    
    # 2. 加载最近反思
    context_parts.append(load_recent_reflections(days=7))
    
    # 3. 加载相关笔记（通过语义搜索）
    if query := get_query_from_route(route):
        context_parts.append(semantic_search(query, top_k=5))
    
    # 4. 裁剪到预算
    return truncate_to_budget(context_parts, budget)
```

**特性：**
- 路由感知（不同意图加载不同上下文）
- 预算控制（防止上下文溢出）
- 优先级排序（profile > recent > related）

#### 3.2.6 健康检查

```python
# scripts/cues.py (1957 行)

def check_health() -> List[Cue]:
    """
    健康检查（静默模式）
    
    只在有问题时返回 Cue，无问题则零输出
    """
    cues = []
    
    # 1. Weekly review 过期检查
    if weekly_review_overdue():
        cues.append(Cue("weekly_review_overdue", ...))
    
    # 2. Inbox 待处理检查
    if inbox_overflow():
        cues.append(Cue("inbox_overflow", ...))
    
    # 3. 结构完整性检查
    if broken_links():
        cues.append(Cue("broken_links", ...))
    
    return cues  # 90% 时间返回空列表
```

#### 3.2.7 成本分析

```python
# scripts/pricing.py (240 行)

def calculate_cost(model: str, input_tokens: int, output_tokens: int) -> float:
    """
    计算 API 调用成本
    
    读取 harness/model_costs.toml 获取价格
    """
    pricing = load_pricing()
    input_cost = (input_tokens / 1_000_000) * pricing[model]["input"]
    output_cost = (output_tokens / 1_000_000) * pricing[model]["output"]
    return input_cost + output_cost

def cost_report(days: int = 7) -> str:
    """
    生成成本报告
    
    解析 ~/.cache/atelier/llm_calls/*.jsonl
    按模型、任务、配置聚合
    """
    logs = load_logs(since=days_ago(days))
    grouped = group_by(logs, ["model", "task", "profile"])
    return format_report(grouped)
```

### 3.3 Atelier Gap 分析

**已有能力（可直接复用）：**
- ✅ L1-L5 知识分层
- ✅ Wiki Schema
- ✅ TrustRank 引擎
- ✅ 11 个专业智能体
- ✅ Intent Router
- ✅ 上下文管理（Context Bundle）
- ✅ 健康检查（Cues）
- ✅ 成本分析（Pricing）
- ✅ 语义搜索（Semantic Search）
- ✅ PDF 处理（Paper Cache）

**缺失能力（需要新增）：**

#### Gap 1: Cognition Flywheel（认知飞轮）

**当前：** Atelier 是"工具集"，没有统一的认知循环
**目标：** KNOW → THINK → ACT → LEARN 的完整闭环

#### Gap 2: Decision Tracking（决策追踪）

**当前：** 反思笔记分散，没有结构化决策记录
**目标：** 决策模型（Open Question → Options → Decision → Outcome → Learning）

#### Gap 3: Action Execution（行动执行）

**当前：** Atelier 只记录反思，不执行行动
**目标：** 行动日志、执行追踪、反馈收集

#### Gap 4: Model Gateway（多模型抽象）

**当前：** 直接调用 Claude/GPT
**目标：** 统一接口，支持多模型切换、成本控制、降级策略

#### Gap 5: Workflow Engine（工作流引擎）

**当前：** Intent Router 只是简单的命令分发
**目标：** 复杂工作流编排（条件分支、并行执行、错误处理）

#### Gap 6: Published Knowledge Ingestion（已发布知识摄入）

**当前：** 手工整理笔记到 wiki
**目标：** 自动摄入 nashsu/llm_wiki 生成的结构化知识

#### Gap 7: Memory System（记忆系统）

**当前：** 通过脚本工具实现基础上下文加载和语义搜索
**目标：** 独立模块，支持 100G 知识库、长期记忆、情景记忆、多模态索引

### 3.4 分类：复用（REUSE）vs. 新增（NEW）

#### 3.4.1 复用（REUSE）

| 能力 | Atelier 实现 | 复用方式 |
|------|-------------|----------|
| Knowledge Vault | `$OV/` L1-L5 分层 | 直接复用目录结构 |
| Wiki Schema | `$OV/wiki/*.md` | 复用格式规范 |
| TrustRank | `scripts/trustrank.py` | 封装为 Module 4 子功能 |
| Agents | `.claude/agents/` | 封装为 Module 2 |
| Context Loading | `scripts/context_bundle.py` | 集成到 Module 8 (Memory System) |
| Health Check | `scripts/cues.py` | 保持脚本工具 |
| Cost Analysis | `scripts/pricing.py` | 保持脚本工具 |
| Semantic Search | `scripts/semantic.py` | 集成到 Module 8 (Memory System) |
| PDF Processing | `scripts/paper_cache.py` | 集成到 Module 8 (Memory System) |

#### 3.4.2 新增（NEW）

| 能力 | 目标 | 实现模块 |
|------|------|----------|
| Cognition Flywheel | KNOW → THINK → ACT → LEARN | Module 1 |
| Decision Tracking | Open Question → Decision → Outcome | Module 1 |
| Action Execution | 行动日志、执行追踪 | Module 1 |
| Model Gateway | 多模型抽象、成本控制 | Module 5 |
| Workflow Engine | 复杂工作流编排 | Module 3 |
| Published Knowledge Ingestion | 自动摄入外部知识 | Module 4 |
| **Memory System** | 100G 知识库管理 | **Module 8** ← 新增核心模块 |
| Working Memory | 会话级缓存、预取 | Module 8 |
| Episodic Memory | 情景记忆重建 | Module 8 |
| Multi-modal Index | 文本/图片/视频/PDF 索引 | Module 8 |
| Temporal Anchoring | 时间锚点系统 | Module 8 |

### 3.5 关键 Gap 总结

| Gap # | 能力 | 类型 | 优先级 | 复杂度 |
|-------|------|------|--------|--------|
| Gap 1 | Cognition Flywheel | NEW | P0 | High |
| Gap 2 | Decision Tracking | NEW | P0 | Medium |
| Gap 3 | Action Execution | NEW | P1 | Medium |
| Gap 4 | Model Gateway | NEW | P0 | Medium |
| Gap 5 | Workflow Engine | NEW | P1 | High |
| Gap 6 | Published Knowledge Ingestion | NEW | P0 | Low |
| Gap 7 | **Memory System** | **NEW** | **P0** | **High** |

---

## 4. 认知领域模型

### 4.1 核心实体

#### 4.1.1 Source（来源）

```python
class Source:
    """外部信息来源"""
    id: str
    type: SourceType  # BOOK, PAPER, VIDEO, WEBSITE, CONVERSATION
    title: str
    author: Optional[str]
    url: Optional[str]
    created: datetime
    quality: QualityLevel  # L1-L5
    metadata: Dict[str, Any]
```

#### 4.1.2 Claim（断言）

```python
class Claim:
    """可验证的知识断言"""
    id: str
    statement: str  # 断言内容
    anchor: Source  # 来源
    evidence: List[Evidence]  # 支持证据
    trust: float  # 信任度 [0, 1]
    since: datetime  # 有效起始时间
    until: Optional[datetime]  # 有效结束时间（可能被证伪）
    passes: List[str]  # 通过的测试用例
    fails: List[str]  # 已知失败情况
```

#### 4.1.3 Evidence（证据）

```python
class Evidence:
    """支持或反驳 Claim 的证据"""
    id: str
    claim_id: str
    content: str
    source: Source
    polarity: Polarity  # SUPPORT, CONTRADICT, NEUTRAL
    weight: float  # 证据权重
```

#### 4.1.4 Belief（信念）

```python
class Belief:
    """个人当前持有的信念"""
    id: str
    statement: str
    based_on: List[Claim]  # 基于的断言
    confidence: float  # 置信度
    updated: datetime
    history: List[BeliefUpdate]  # 信念更新历史
```

#### 4.1.5 Model（心智模型）

```python
class Model:
    """领域心智模型"""
    id: str
    domain: str  # 领域（如 "软件架构", "产品管理"）
    beliefs: List[Belief]
    principles: List[str]  # 核心原则
    heuristics: List[str]  # 启发式规则
    updated: datetime
```

#### 4.1.6 Open Question（开放问题）

```python
class OpenQuestion:
    """尚未解决的问题"""
    id: str
    question: str
    context: str
    created: datetime
    importance: float  # [0, 1]
    related_beliefs: List[Belief]
    proposed_answers: List[Answer]
```

#### 4.1.7 Decision（决策）

```python
class Decision:
    """已做出的决策"""
    id: str
    question: OpenQuestion
    chosen_option: str
    alternatives: List[str]  # 未选择的选项
    rationale: str  # 决策理由
    decided_at: datetime
    decided_by: str  # USER | SYSTEM
    outcome: Optional[Outcome]  # 决策结果（可能尚未执行）
```

#### 4.1.8 Action（行动）

```python
class Action:
    """基于决策的行动"""
    id: str
    decision_id: str
    action: str  # 行动描述
    status: ActionStatus  # PLANNED, IN_PROGRESS, COMPLETED, CANCELLED
    started_at: Optional[datetime]
    completed_at: Optional[datetime]
    feedback: Optional[Feedback]
```

#### 4.1.9 Feedback（反馈）

```python
class Feedback:
    """行动的反馈结果"""
    id: str
    action_id: str
    outcome: str  # 实际结果
    expected: str  # 预期结果
    delta: str  # 差异分析
    learning: List[str]  # 学到的教训
    collected_at: datetime
```

#### 4.1.10 Cognition Change（认知变化）

```python
class CognitionChange:
    """认知更新记录"""
    id: str
    type: ChangeType  # NEW_BELIEF, UPDATE_BELIEF, REJECT_BELIEF, UPDATE_MODEL
    before: Optional[Any]  # 变化前状态
    after: Any  # 变化后状态
    trigger: str  # 触发原因（NEW_EVIDENCE, CONTRADICTION, REFLECTION）
    timestamp: datetime
```

#### 4.1.11 Learning Agenda（学习议程）

```python
class LearningAgenda:
    """待学习的主题"""
    id: str
    topic: str
    motivation: str  # 为什么要学
    priority: int
    status: AgendaStatus  # PLANNED, IN_PROGRESS, COMPLETED
    resources: List[Source]  # 学习资源
    progress: float  # [0, 1]
```

#### 4.1.12 Skill（技能）

```python
class Skill:
    """已掌握的技能"""
    id: str
    name: str
    domain: str
    proficiency: float  # [0, 1]
    evidence: List[Action]  # 证明该技能的行动记录
    last_used: datetime
```

#### 4.1.13 Memory（记忆）

```python
class Memory:
    """记忆系统的核心实体"""
    id: str
    type: MemoryType  # WORKING, EPISODIC, SEMANTIC, PROCEDURAL
    content: str
    context: Dict[str, Any]
    importance: float  # [0, 1]
    access_count: int  # 访问次数
    last_accessed: datetime
    created: datetime
    decay_factor: float  # 时间衰减因子
    
class WorkingMemory(Memory):
    """会话级工作记忆"""
    session_id: str
    ttl: int  # Time to live (seconds)
    
class EpisodicMemory(Memory):
    """情景记忆（事件、对话）"""
    episode_id: str
    timestamp: datetime
    participants: List[str]
    location: Optional[str]
    
class SemanticMemory(Memory):
    """语义记忆（事实、概念）"""
    claim_id: str
    trust: float
    
class ProceduralMemory(Memory):
    """程序记忆（技能、流程）"""
    skill_id: str
    steps: List[str]
```

### 4.2 实体关系图

```
Source ──┐
         ├─→ Claim ──→ Evidence
         │      ↓
         │   Belief ──→ Model
         │      ↓
         └─→ Open Question ──→ Decision ──→ Action ──→ Feedback
                                   ↓                      ↓
                            Cognition Change ←───────────┘
                                   ↓
                            Learning Agenda ──→ Skill

Memory System:
  Working Memory ──→ Session Context
  Episodic Memory ──→ Past Events
  Semantic Memory ──→ Claims / Beliefs
  Procedural Memory ──→ Skills / Workflows
```

### 4.3 核心流程

#### 4.3.1 知识摄入流程

```
External Source (nashsu/llm_wiki)
  ↓
Published Knowledge
  ↓
Ingestion (Module 4: Knowledge Vault)
  ↓
Claims + Sources
  ↓
TrustRank Calculation
  ↓
Memory System Indexing (Module 8)
  ↓
Semantic Search Ready
```

#### 4.3.2 认知飞轮流程

```
1. KNOW (感知世界状态)
   ↓
   Memory System 加载上下文
   - Working Memory (热点缓存)
   - Episodic Memory (历史对话)
   - Semantic Memory (相关知识)
   ↓
2. THINK (理解、判断、建模)
   ↓
   查询 Knowledge Vault
   - Claims
   - Evidence
   - TrustRank
   ↓
   更新 Beliefs / Models
   ↓
   识别 Open Questions
   ↓
3. ACT (做出决策和行动)
   ↓
   评估选项 (Decision)
   ↓
   执行行动 (Action)
   ↓
4. LEARN (收集反馈、更新认知)
   ↓
   收集 Feedback
   ↓
   记录 Cognition Change
   ↓
   更新 Learning Agenda
   ↓
   Memory System 更新重要性评分
   ↓
   返回步骤 1 (Updated Cognition)
```

#### 4.3.3 决策流程

```
Open Question
  ↓
列出选项 (Options)
  ↓
评估 Pro/Con
  - 基于 Beliefs
  - 基于 Past Decisions
  - 基于 Expert Advice (Agent)
  ↓
用户审批 (Human-in-the-loop)
  ↓
Decision
  ↓
Action Plan
  ↓
Execution
  ↓
Feedback
  ↓
Cognition Change
  ↓
Learning Agenda Update
```

---

## 5. 八模块架构设计

### 5.1 Module 1: Cognition Flywheel Core

**职责：**
- 实现 KNOW → THINK → ACT → LEARN 循环
- 管理 Beliefs、Models、Open Questions
- 决策支持和追踪
- 认知变化记录

**输入：**
- Published Knowledge (from Module 4)
- User Input (from Module 7)
- Feedback (from Module 6)
- Memory Context (from Module 8)

**输出：**
- Updated Beliefs
- Updated Models
- Decisions
- Learning Agenda

**Capability Contract：**
```python
# Belief Management
create_belief(statement, claims, confidence) -> Belief
update_belief(belief_id, new_confidence, new_claims) -> Belief
deprecate_belief(belief_id, reason) -> void

# Model Management
create_model(domain, principles) -> Model
add_belief_to_model(model_id, belief_id) -> void
update_model_heuristics(model_id, new_heuristics) -> void

# Question Management
create_open_question(question, context, importance) -> OpenQuestion
answer_question(question_id, answer) -> void
close_question(question_id, resolution) -> void

# Decision Support
list_options(question_id) -> List[Option]
evaluate_option(option_id, pros, cons) -> Evaluation
make_decision(question_id, chosen_option, rationale) -> Decision

# Cognition Change
record_change(type, before, after, trigger) -> CognitionChange
get_change_history(entity_id) -> List[CognitionChange]
```

**当前实现：**
- V0: 基于 Markdown 文件 + Python 脚本
- 数据存储：`$OV/beliefs/`, `$OV/decisions/`

---

### 5.2 Module 2: Agent Runtime

**职责：**
- 管理专业智能体（11 个 Atelier Agents）
- Agent 任务分发和执行
- 多 Agent 协作编排

**输入：**
- User Intent (from Module 7)
- Cognition State (from Module 1)

**输出：**
- Agent Execution Results
- Agent Interaction History

**Specialist Agents：**
1. **Researcher** — 收集证据
2. **Reader** — 结构化阅读
3. **Scholar** — 深度阅读（学术论文）
4. **Challenger** — 挑战假设
5. **Curator** — 整理知识
6. **Synthesizer** — 综合洞察
7. **Thinker** — 独立思考
8. **Reviewer** — 质量审查
9. **Scribe** — 记录内容
10. **Librarian** — 推荐资源
11. **Meeting** — 会议纪要

**Capability Contract：**
```python
# Agent Execution
dispatch_agent(agent_name, task, context) -> AgentResult
get_agent_status(agent_id) -> AgentStatus
cancel_agent(agent_id) -> void

# Multi-Agent Orchestration
run_agent_team(agents, task) -> TeamResult
```

**当前实现：**
- V0: 直接复用 Atelier `.claude/agents/`
- 编排：通过 Orchestrator 协调

---

### 5.3 Module 3: Workflow Engine

**职责：**
- 复杂工作流编排
- 条件分支、并行执行
- 错误处理和重试
- 长期任务追踪

**输入：**
- User Intent (from Module 7)
- Workflow Definition (from Config)

**输出：**
- Workflow Status
- Execution Results

**Capability Contract：**
```python
# Workflow Execution
start_workflow(workflow_id, params) -> WorkflowInstance
get_workflow_status(instance_id) -> WorkflowStatus
pause_workflow(instance_id) -> void
resume_workflow(instance_id) -> void
cancel_workflow(instance_id) -> void

# Workflow Definition
define_workflow(name, steps) -> WorkflowDefinition
update_workflow(workflow_id, new_steps) -> void
```

**当前实现：**
- V0: 基于 Intent Router (`harness/intents.toml`)
- V1: 扩展为完整工作流引擎

---

### 5.4 Module 4: Knowledge Vault

**职责：**
- 存储 L1-L5 分层知识
- Wiki Schema 管理
- TrustRank 计算
- 知识摄入（Published Knowledge Ingestion）

**输入：**
- Published Knowledge (from External Compiler)
- User Notes (from Module 7)

**输出：**
- Knowledge Query Results
- Trust Scores

**Capability Contract：**
```python
# Knowledge Storage
ingest_published_knowledge(knowledge) -> void
store_claim(claim) -> void
store_source(source) -> void

# Knowledge Retrieval
query_claims(query, filters) -> List[Claim]
get_claim_trust(claim_id) -> float
get_claim_evidence(claim_id) -> List[Evidence]

# TrustRank
calculate_trustrank(claim_id) -> float
propagate_trust() -> void  # 全图传播
```

**当前实现：**
- V0: 直接复用 Atelier `$OV/` 目录结构
- TrustRank: `scripts/trustrank.py`

---

### 5.5 Module 5: Model Gateway

**职责：**
- 多模型统一接口
- 模型路由和负载均衡
- 成本控制和日志
- 降级策略（Fallback）

**输入：**
- Model Invocation Requests

**输出：**
- Model Responses
- Cost Logs

**Capability Contract：**
```python
# Model Invocation
invoke_model(model, prompt, params) -> Response
batch_invoke(model, prompts) -> List[Response]

# Model Routing
route_to_model(task_type, budget) -> ModelChoice
fallback_model(failed_model) -> AlternativeModel

# Cost Management
get_cost_estimate(model, prompt) -> float
log_invocation(model, usage, cost) -> void
```

**当前实现：**
- V0: 直接调用 Anthropic / OpenAI API
- Cost Logging: `~/.cache/atelier/llm_calls/*.jsonl`

---

### 5.6 Module 6: Feedback Loop

**职责：**
- 行动执行追踪
- 反馈收集
- 认知更新触发

**输入：**
- Actions (from Module 1)
- External Feedback (from Module 7)

**输出：**
- Feedback Records
- Cognition Change Triggers

**Capability Contract：**
```python
# Action Execution
execute_action(action_id) -> ActionResult
get_action_status(action_id) -> ActionStatus

# Feedback Collection
collect_feedback(action_id, outcome, expected) -> Feedback
compare_outcome(feedback_id) -> Delta

# Cognition Update
trigger_cognition_update(feedback_id) -> List[CognitionChange]
```

**当前实现：**
- V0: 手工记录到 `$OV/reflections/`
- V1: 自动化反馈收集

---

### 5.7 Module 7: Human Interface

**职责：**
- 用户输入接收
- 系统状态展示
- 决策审批界面
- 健康和成本仪表盘

**输入：**
- User Commands
- System State (from all modules)

**输出：**
- User Interactions
- Approval Decisions

**Capability Contract：**
```python
# User Input
receive_command(command) -> Intent
get_user_approval(decision_id) -> ApprovalResult

# System Display
show_beliefs() -> BeliefListView
show_open_questions() -> QuestionListView
show_decisions() -> DecisionHistoryView
show_learning_agenda() -> LearningAgendaView

# Dashboards
show_health_status() -> HealthDashboard  # 调用 scripts/cues.py
show_cost_report() -> CostDashboard  # 调用 scripts/pricing.py
```

**当前实现：**
- V0: Obsidian (Markdown 编辑)
- V1: Web UI / CLI

**Obsidian 集成说明：**

本系统完全兼容 Obsidian，数据存储格式采用 **Markdown + YAML frontmatter**，与 Obsidian 原生格式一致。

**集成方式：**

1. **数据层兼容**
   - 所有数据存储在 `$OV/` 目录（Obsidian Vault）
   - 使用标准 Markdown 格式
   - 使用 Obsidian 兼容的 YAML frontmatter
   - 支持 Obsidian 双向链接 `[[page]]`
   - 支持 Obsidian 标签 `#tag`

2. **Obsidian 插件开发**
   - V0: 手工在 Obsidian 中编辑 Markdown
   - V1: 开发 Obsidian Plugin 提供 UI
     - 侧边栏展示 Beliefs / Open Questions / Learning Agenda
     - 快捷命令（Command Palette）
     - 可视化 TrustRank 图
     - 健康和成本仪表盘

3. **Web Clipper 集成（重要）**
   
   **问题：你提到的 nashsu/llm_wiki 内置 Web Clipper，如何与本系统集成？**
   
   **方案 A：Web Clipper → nashsu/llm_wiki → 本系统（推荐）**
   ```
   用户在浏览器使用 Web Clipper
     ↓
   Web Clipper 发送到 nashsu/llm_wiki
     ↓
   llm_wiki 处理（提取正文、结构化、生成 Claims）
     ↓
   输出 Published Knowledge (Markdown)
     ↓
   自动同步到本系统 $OV/wiki/
     ↓
   Module 4 摄入 + Module 8 索引
   ```
   
   **方案 B：Web Clipper → 本系统 → nashsu/llm_wiki（备选）**
   ```
   用户在浏览器使用 Web Clipper
     ↓
   Web Clipper 发送到本系统 Module 7
     ↓
   本系统暂存到 $OV/inbox/
     ↓
   定期批量发送给 nashsu/llm_wiki 处理
     ↓
   处理后的 Published Knowledge 返回
     ↓
   Module 4 摄入 + Module 8 索引
   ```
   
   **推荐方案 A**，原因：
   - Web Clipper 直接对接知识编译器，职责清晰
   - 本系统专注于认知管理，不做内容提取
   - 减少中间环节，提高效率
   
   **Web Clipper 工作流：**
   ```yaml
   # 用户在网页上点击 Web Clipper
   
   1. Web Clipper 提取
      - URL
      - 页面标题
      - 正文内容
      - 元数据（作者、发布日期）
      - 用户标注（高亮、笔记）
   
   2. 发送到 nashsu/llm_wiki API
      POST /api/clip
      {
        "url": "https://example.com/article",
        "title": "Article Title",
        "content": "...",
        "highlights": [...],
        "tags": ["programming", "python"]
      }
   
   3. llm_wiki 处理
      - 正文清理
      - 结构化提取
      - Claims 生成
      - 质量评估
   
   4. 输出 Published Knowledge
      - 写入 nashsu/llm_wiki 的输出目录
      - 该目录被本系统监听（File Watcher）
   
   5. 本系统自动摄入
      - Module 4 检测新文件
      - 自动 ingest_published_knowledge()
      - Module 8 建立索引
      - 用户在 Obsidian 中即可看到新知识
   ```

4. **Obsidian 与 Web UI 双界面**
   
   **Obsidian 适用场景：**
   - 深度编辑 Markdown
   - 浏览双向链接图谱
   - 手工整理笔记
   - 快速搜索（Obsidian 原生搜索）
   
   **Web UI 适用场景：**
   - 可视化 Cognition Flywheel
   - 交互式决策审批
   - 健康和成本仪表盘
   - Agent 任务管理
   - Learning Agenda 优先级排序
   
   **数据同步：**
   - 两个界面共享 `$OV/` 目录
   - 实时文件监听（File Watcher）
   - Obsidian 修改 → Web UI 自动刷新
   - Web UI 修改 → Obsidian 自动重载

5. **Obsidian Community Plugins 复用**
   
   可以直接使用现有 Obsidian 插件：
   - **Dataview**: 查询和展示结构化数据
   - **Templater**: 模板化创建 Beliefs / Decisions
   - **Calendar**: 查看按日期的笔记
   - **Graph View**: 可视化知识图谱
   - **Excalidraw**: 绘制概念图

**数据格式示例（Obsidian 兼容）：**

```markdown
---
type: belief
id: belief_20260826_001
statement: "Python asyncio 适合 I/O 密集型任务"
confidence: 0.9
based_on:
  - claim_fluent_python_ch18_001
  - claim_asyncio_video_001
created: 2026-08-26T10:30:00Z
updated: 2026-08-26T12:00:00Z
tags:
  - programming
  - python
  - concurrency
---

# Python asyncio 适合 I/O 密集型任务

## 置信度
- **当前置信度**: 0.9 (Very High)
- **上次更新**: 2026-08-26

## 支持证据

### 证据 1：《Fluent Python》
- **来源**: [[fluent_python_chapter_18]]
- **断言**: [[claim_fluent_python_ch18_001]]
- **Trust**: 0.95
- **内容**: "asyncio 的核心优势在于 I/O 等待期间可以切换任务..."

### 证据 2：视频讲解
- **来源**: [[python_asyncio_video]]
- **时间戳**: 15:20-22:10
- **Trust**: 0.85
- **内容**: "CPU 密集型任务不应该使用 asyncio..."

## 相关问题
- [[question_when_to_use_asyncio]]
- [[question_asyncio_vs_threading]]

## 应用决策
- [[decision_20260820_use_asyncio_in_web_crawler]]

## 反驳证据
- 暂无

## 笔记
用户可以在这里添加个人理解和笔记...
```

**Obsidian 中的体验：**
- 双向链接跳转
- Graph View 查看关联
- 使用 Dataview 查询所有 Beliefs
- 使用 Templater 快速创建 Decision 条目

---

### 5.8 Module 8: Memory System（新增核心模块）

**职责：**
- Working Memory（会话级缓存）
- Episodic Memory（情景记忆重建）
- Semantic Memory（语义检索）
- Procedural Memory（技能记忆）
- Multi-modal Index（文本/图片/视频/PDF）
- Temporal Anchoring（时间锚点）
- Smart Prefetching（智能预取）
- Memory Importance Scoring（重要性评分）
- Memory Decay & Forgetting（时间衰减和遗忘决策）

**输入：**
- Knowledge Vault Data (from Module 4)
- User Interactions (from Module 7)
- Agent Activity (from Module 2)

**输出：**
- Context Bundle (for Module 1)
- Semantic Search Results
- Episodic Memory (for Agent multi-turn dialogue)

**Capability Contract：**
```python
# Context Loading
load_session_context(intent, profile, budget) -> ContextBundle
refresh_context(session_id, new_budget) -> ContextBundle
get_context_stats(session_id) -> ContextStats

# Semantic Search
semantic_search(query, filters, top_k) -> List[MemorySearchResult]
multi_modal_search(query, modality, filters) -> List[MemorySearchResult]

# Episodic Memory
get_episodic_memory(session_id) -> EpisodicMemory
get_task_memory(task_id) -> TaskMemory
find_similar_episodes(current_context) -> List[EpisodicMemory]

# Temporal Queries
get_memory_at_time(timestamp, context) -> List[Memory]
get_memory_in_range(start_time, end_time, filters) -> List[Memory]

# Memory Management
update_importance(memory_id, score) -> void
mark_as_forgotten(memory_id, reason) -> void
pin_memory(memory_id) -> void  # 永不遗忘
get_decay_candidates(threshold) -> List[Memory]

# Prefetching & Optimization
prefetch_related(memory_ids) -> void
optimize_index() -> IndexOptimizationReport
get_memory_stats() -> MemoryStats

# Multi-modal Support
index_pdf(pdf_path) -> IndexResult
index_video_transcript(video_path, transcript) -> IndexResult
index_image(image_path, caption) -> IndexResult
```

**架构层次：**

```yaml
Memory System
├── Working Memory Layer (会话内，内存中)
│   ├── Hot Cache (LRU Cache)
│   ├── Prefetch Queue
│   └── Context Window Manager
│
├── Long-term Memory Layer (持久化，磁盘/DB)
│   ├── Semantic Index (LanceDB / Faiss)
│   ├── Temporal Index (SQLite)
│   ├── Access Log (JSONL)
│   └── Metadata Store (SQLite)
│
├── Multi-modal Layer
│   ├── Text Embeddings (Sentence Transformers)
│   ├── Image Embeddings (CLIP)
│   ├── Video Transcript Index
│   └── PDF Content Index (paper_cache.py)
│
└── Intelligence Layer
    ├── Importance Scorer
    ├── Decay Calculator
    ├── Prefetch Predictor
    └── Episodic Reconstructor
```

**数据流：**

```
[User Query]
    ↓
[Cognition Core] → load_session_context(intent, budget)
    ↓
[Memory System]
    ↓
  1. Check Working Memory (Hot Cache hit?)
  2. If miss → Query Long-term Memory
     - Semantic Search (embeddings)
     - Temporal Filter (time range)
     - Importance Ranking
  3. Prefetch Related Memories (predictive)
  4. Update Access Logs
  5. Update Importance Scores (based on usage)
    ↓
[Return ContextBundle] → Cognition Core
    ↓
[Cognition Core uses context for THINK]
```

**当前实现：**
- V0 (< 10GB): 脚本工具阶段
  - `scripts/context_bundle.py` (1482 行) — 上下文加载
  - `scripts/semantic.py` (1556 行) — 语义搜索
  - `scripts/paper_cache.py` — PDF 处理
  
- V1 (10-100GB): Memory System 模块
  - Working Memory 缓存层
  - Memory Metadata 和 Importance Scoring
  - Episodic Memory 重建
  - Multi-modal Indexing
  
- V2 (> 100GB): 分布式部署
  - 多机索引
  - Spaced Repetition 遗忘算法
  - 主动记忆推荐

**性能目标：**

| 知识库规模 | 语义检索延迟 | 上下文加载延迟 | 索引更新延迟 |
|------------|--------------|----------------|--------------|
| 1GB | < 100ms | < 200ms | < 1s |
| 10GB | < 200ms | < 500ms | < 5s |
| 100GB | < 500ms | < 1s | < 30s |

**与其他模块的集成：**

- **与 Module 1 (Cognition Core)：**
  - Cognition Core 调用 `load_session_context` 获取上下文
  - Cognition Core 通过 `semantic_search` 检索相关知识
  - Cognition Core 更新 `update_importance` 标记重要记忆

- **与 Module 2 (Agent Runtime)：**
  - Agent 多轮对话时调用 `get_episodic_memory` 重建对话历史
  - Agent 使用 `find_similar_episodes` 检索相似案例

- **与 Module 3 (Workflow Engine)：**
  - 长期任务调用 `get_task_memory` 加载任务脉络
  - 任务完成后更新记忆重要性评分

- **与 Module 4 (Knowledge Vault)：**
  - Memory System 只读 Knowledge Vault 的数据
  - 新知识发布后，Memory System 自动更新索引

- **与 Module 5 (Model Gateway)：**
  - Memory System 提供的 ContextBundle 注入到 Model Gateway 的上下文窗口

---

## 6. Support Tools（辅助工具）

### 6.1 Tool 1: Health Checker

**职责：**
- 会话启动检查（weekly review 过期、inbox 待处理）
- 结构完整性检查（wiki schema、orphan files）
- 记忆审计（stale、dead-link、orphan）
- 系统健康状态扫描

**实现：**
- `scripts/cues.py` (1957 行)
- `scripts/lint.py`
- `scripts/auto_memory_audit.py`

**调用时机：**
- 会话启动时自动检查（由 Module 7 触发）
- 用户手动运行健康检查
- 错误或异常发生后

**设计原则：**
- **静默优先** — 90% 的时间不输出，避免污染上下文
- **按需提示** — 只在需要用户关注时才提示
- **可选深度** — 支持 quick/medium/thorough 三个级别

**示例：**
```bash
# 会话启动检查（默认静默）
uv run scripts/cues.py

# JSON 输出供 UI 消费
uv run scripts/cues.py --json

# 手动运行 lint 检查
uv run scripts/lint.py

# 记忆审计
uv run scripts/auto_memory_audit.py --threshold 90
```

---

### 6.2 Tool 2: Cost Analyzer

**职责：**
- 成本计算和报告
- 日志分析（读取 `~/.cache/atelier/llm_calls/*.jsonl`）
- 价格表维护（`harness/model_costs.toml`）
- 成本趋势分析

**实现：**
- `scripts/pricing.py` (240 行)
- `scripts/shadow.py` (跨提供商成本对比)

**调用时机：**
- 用户手动运行（每周/月查看成本）
- **不需要实时追踪** — 事后分析足够

**设计原则：**
- **事后分析 > 实时监控** — 避免实时监控的复杂度和成本
- **价格表定期维护** — 90 天未更新会警告，强制季度审查
- **简单日志 + 强大分析** — 每次 API 调用写一行 JSONL，事后聚合分析

**示例：**
```bash
# 查看所有模型价格表
uv run scripts/pricing.py list

# 查看单个模型的 blended 价格
uv run scripts/pricing.py blended anthropic flagship

# 估算成本
uv run scripts/pricing.py cost anthropic flagship \
  --input 50000 --output 5000

# 事后成本分析（最常用）
uv run scripts/pricing.py cost-from-log

# 按日期分析
uv run scripts/pricing.py cost-from-log --date 2026-08-26

# 按 profile 分析
uv run scripts/pricing.py cost-from-log --profile deep
```

---

## 7. V0/V1 范围定义

### 7.1 V0 范围（MVP）

**目标：** 验证核心认知飞轮

**必须实现：**
- [x] Module 1: Cognition Core (Beliefs, Models, Questions)
- [x] Module 4: Knowledge Vault (L1-L5, Wiki Schema)
- [x] Module 7: Human Interface (Obsidian / CLI)
- [x] Tool 1: Health Checker (scripts/cues.py)
- [x] Tool 2: Cost Analyzer (scripts/pricing.py)
- [x] Memory System V0: 脚本工具阶段 (context_bundle.py, semantic.py)

**可延后：**
- [ ] Module 2: Agent Runtime (使用现有 Atelier Agents)
- [ ] Module 3: Workflow Engine (使用现有 Intent Router)
- [ ] Module 5: Model Gateway (直接调用 API)
- [ ] Module 6: Feedback Loop (手工记录)
- [ ] Module 8: Memory System V1 (独立模块)

**验收标准：**
- 能够摄入 nashsu/llm_wiki 生成的知识
- 能够基于知识形成 Beliefs
- 能够追踪 Open Questions
- 能够记录 Decisions
- 能够查询知识和 TrustRank

---

### 7.2 V1 范围（完整产品）

**目标：** 完整认知飞轮 + Agent 编排

**必须实现：**
- [ ] Module 1: 完整认知飞轮（含 ACT 和 LEARN）
- [ ] Module 2: Agent Runtime（11 个专业智能体）
- [ ] Module 3: Workflow Engine（复杂工作流）
- [ ] Module 5: Model Gateway（多模型抽象）
- [ ] Module 6: Feedback Loop（自动化反馈）
- [ ] **Module 8: Memory System V1（独立模块，支持 10-100GB 知识库）**

**新增能力：**
- Working Memory 缓存层
- Episodic Memory 重建
- Multi-modal Indexing（文本/图片/视频/PDF）
- Memory Importance Scoring
- Smart Prefetching

**验收标准：**
- 支持 10-100GB 知识库
- 语义检索延迟 < 200ms
- 上下文加载延迟 < 500ms
- 支持多模态检索
- 情景记忆重建功能可用

---

### 7.3 V2 范围（扩展）

**目标：** 分布式 Memory System + 高级特性

**必须实现：**
- [ ] **Memory System V2: 分布式部署**
  - 多机索引
  - Spaced Repetition 遗忘算法
  - 主动记忆推荐

**新增能力：**
- 支持 > 100GB 知识库
- 分布式向量索引
- 更复杂的遗忘决策算法
- 主动推荐相关记忆

**验收标准：**
- 支持 100GB+ 知识库
- 语义检索延迟 < 500ms
- 分布式索引可用
- Spaced Repetition 算法验证有效

---

## 8. 风险与开放问题

### 8.1 技术风险

#### Risk 1: 100GB 知识库的性能挑战

**风险：** 向量检索在 100GB 规模下可能无法满足 < 500ms 的延迟要求

**缓解措施：**
1. 使用 LanceDB / Faiss 等高性能向量数据库
2. 分层索引（热点数据 + 冷数据）
3. 智能预取减少实时查询
4. 分布式部署（V2）

#### Risk 2: TrustRank 计算成本

**风险：** 全图 TrustRank 传播在大规模知识库中可能很慢

**缓解措施：**
1. 增量更新而非全图重算
2. 缓存 TrustRank 结果
3. 异步计算（后台任务）

#### Risk 3: Memory System 的复杂度

**风险：** 新增 Memory System 模块增加了系统复杂度

**缓解措施：**
1. V0 阶段继续使用脚本工具验证需求
2. V1 阶段逐步迁移到 Memory System 模块
3. 提供降级能力（Memory System 不可用时回退到脚本工具）

### 8.2 开放问题

#### Question 1: 记忆遗忘算法

**问题：** 如何决定哪些记忆该被遗忘？

**选项：**
- A: 基于访问频率（最少使用 LRU）
- B: 基于时间衰减（指数衰减）
- C: 基于重要性评分（用户标注 + 系统推断）
- D: Spaced Repetition（间隔重复算法）

**建议：** V1 使用 C (重要性评分)，V2 升级为 D (Spaced Repetition)

#### Question 2: Episodic Memory 的粒度

**问题：** 情景记忆应该以什么粒度存储？

**选项：**
- A: 每个会话一个情景记忆
- B: 每个任务一个情景记忆
- C: 每个决策一个情景记忆

**建议：** V1 使用 B (按任务)，可根据实际使用调整

#### Question 3: Multi-modal Embedding 模型选择

**问题：** 图片、视频应该使用哪个 embedding 模型？

**选项：**
- A: CLIP (OpenAI)
- B: ALIGN (Google)
- C: ImageBind (Meta)

**建议：** V1 使用 A (CLIP)，广泛支持且性能良好

---

## 9. 下一步行动

### 9.1 立即行动（本周）

1. ✅ 完成 PRD v0.1
2. ⬜ 用户评审 PRD
3. ⬜ 确认 V0 范围
4. ⬜ 开始 Module 1 (Cognition Core) 实现

### 9.2 短期行动（1-2 周）

1. ⬜ 实现 Belief/Model/Question 数据结构
2. ⬜ 实现 Published Knowledge Ingestion
3. ⬜ 验证 TrustRank 集成
4. ⬜ 实现 Memory System V0（脚本工具阶段）

### 9.3 中期行动（1-2 月）

1. ⬜ 完成 V0 所有模块
2. ⬜ 端到端测试
3. ⬜ 开始 V1 开发（Memory System 模块）

### 9.4 长期行动（3-6 月）

1. ⬜ 完成 V1
2. ⬜ 100GB 知识库压力测试
3. ⬜ 规划 V2（分布式 Memory System）

---

## Appendix A: 术语表

| 术语 | 英文 | 定义 |
|------|------|------|
| 认知飞轮 | Cognition Flywheel | KNOW → THINK → ACT → LEARN 循环 |
| 信念 | Belief | 个人当前持有的信念 |
| 心智模型 | Mental Model | 领域心智模型 |
| 断言 | Claim | 可验证的知识断言 |
| 证据 | Evidence | 支持或反驳 Claim 的证据 |
| 信任度 | Trust | 对 Claim 的信任度 [0, 1] |
| 开放问题 | Open Question | 尚未解决的问题 |
| 决策 | Decision | 已做出的决策 |
| 行动 | Action | 基于决策的行动 |
| 反馈 | Feedback | 行动的反馈结果 |
| 认知变化 | Cognition Change | 认知更新记录 |
| 学习议程 | Learning Agenda | 待学习的主题 |
| 技能 | Skill | 已掌握的技能 |
| 记忆系统 | Memory System | 管理工作记忆、情景记忆、语义记忆、程序记忆 |
| 工作记忆 | Working Memory | 会话级缓存 |
| 情景记忆 | Episodic Memory | 事件、对话记忆 |
| 语义记忆 | Semantic Memory | 事实、概念记忆 |
| 程序记忆 | Procedural Memory | 技能、流程记忆 |
| 时间锚点 | Temporal Anchor | 记忆的时间标记 |
| 重要性评分 | Importance Score | 记忆的重要性 [0, 1] |
| 时间衰减 | Decay | 记忆随时间降低重要性 |
| 智能预取 | Smart Prefetching | 基于访问模式预取相关记忆 |

---

## Appendix B: 参考资料

1. **Atelier 项目**
   - GitHub: (local repository)
   - 核心文件：`CLAUDE.md`, `AGENTS.md`, `protocols/`, `scripts/`

2. **nashsu/llm_wiki**
   - GitHub: https://github.com/nashsu/llm_wiki
   - 职责：知识生产（PDF/视频 → 结构化知识）

3. **TrustRank 论文**
   - "Combating Web Spam with TrustRank" (2004)
   - 应用：知识图谱的信任传播

4. **Zettelkasten 方法**
   - 《How to Take Smart Notes》by Sönke Ahrens
   - 核心：原子化笔记 + 双向链接

5. **向量数据库**
   - LanceDB: https://lancedb.com/
   - Faiss: https://github.com/facebookresearch/faiss

6. **Multi-modal Embeddings**
   - CLIP: https://github.com/openai/CLIP
   - ImageBind: https://github.com/facebookresearch/ImageBind

---

## Appendix C: 架构决策记录

### ADR-001: Memory System 作为第八个核心模块

**日期：** 2026-08-26

**状态：** Accepted

**背景：**
用户明确指出未来知识库将达到 100G 规模，需要强大的记忆管理能力。

**决策：**
Memory System 升级为第八个核心模块，而健康检查和成本分析保持脚本工具。

**理由：**

|| 维度 | Memory System (模块) | Health Checker (工具) | Cost Analyzer (工具) |
|------|---------------------|----------------------|----------------------|
| 规模驱动 | 100G 知识库 | 扫描文件系统 | 解析日志文件 |
| 业务复杂度 | 时间衰减、情景重建、遗忘决策 | 规则匹配 | 价格计算 |
| 持久化需求 | Working Memory 缓存、访问统计、重要性评分 | 无状态 | 无状态 |
| 集成深度 | 与 Cognition Core/Agent/Workflow 深度集成 | 独立运行 | 独立运行 |
| 运行模式 | 常驻进程（预取、索引、缓存） | 按需运行 | 按需运行 |

**分阶段实现：**
- V0 (< 10GB): 脚本工具阶段
- V1 (10-100GB): Memory System 模块
- V2 (> 100GB): 分布式部署

**后果：**
- ✅ 支持 100G 知识库规模
- ✅ 强大的长期记忆和情景记忆能力
- ⚠️  增加了系统复杂度（从 7 模块到 8 模块）

---

### ADR-002: 事后分析 vs. 实时监控

**日期：** 2026-08-26

**状态：** Accepted

**决策：**
健康检查和成本分析选择事后分析，不实现实时监控。

**理由：**
1. 零成本的默认行为
2. 事后分析足够（用户不需要秒级追踪）
3. 避免污染上下文
4. 简化实现

**后果：**
- ✅ 零成本的默认行为
- ⚠️  用户需要主动查看报告

---

### ADR-003: 上下文预算控制

**日期：** 2026-08-26

**状态：** Accepted

**决策：**
实现上下文预算机制，默认 20KB，支持动态调整。

**理由：**
1. 防止上下文溢出
2. 控制 API 成本
3. 优先级排序（profile > recent > related）

**后果：**
- ✅ 防止成本失控
- ✅ 提高相关性（只加载重要内容）

---

**Document Version:** v0.1  
**Last Updated:** 2026-08-26  
**Status:** Draft  
**Author:** AI Assistant (based on Atelier)

---

## Summary for 100G Knowledge Base

**核心架构变更：**
- 从 7 模块 + 3 工具 → **8 模块 + 2 工具**
- 新增 **Module 8: Memory System** 作为独立核心模块

**Memory System 关键能力：**
1. Working Memory（会话级缓存，避免重复检索）
2. Episodic Memory（情景记忆重建，"当时在做什么"）
3. Semantic Memory（语义检索，支持 100GB 规模）
4. Multi-modal Index（文本/图片/视频/PDF 统一索引）
5. Temporal Anchoring（时间锚点系统）
6. Smart Prefetching（基于访问模式的预取）
7. Memory Importance Scoring（重要性评分，用于保留决策）
8. Memory Decay & Forgetting（时间衰减和遗忘决策）

**分阶段实现：**
- **V0 (< 10GB)**: 继续使用脚本工具验证需求
- **V1 (10-100GB)**: Memory System 模块，支持工作记忆 + 情景记忆 + 多模态索引
- **V2 (> 100GB)**: 分布式部署，支持 Spaced Repetition 遗忘算法

**性能目标：**
- 100GB 知识库：语义检索 < 500ms，上下文加载 < 1s

这个设计确保系统能够高效管理 100G 知识库，同时保持架构简洁和鲁棒性。
