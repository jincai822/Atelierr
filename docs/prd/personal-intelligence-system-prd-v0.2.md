# Personal Intelligence System - Product Requirements Document v0.2

**Document Version:** v0.2  
**Last Updated:** 2026-08-26  
**Status:** Active  
**Author:** AI Assistant (based on Atelier + P0 Resolution)  
**Changes from v0.1:** [See CHANGELOG at end of document]

---

## 文档目的

本 PRD 定义 **Personal Cognition & Intelligence System**（个人认知与智能系统）的产品边界、架构设计、领域模型、模块职责与能力契约。

**v0.2 核心改进：**
1. ✅ 验证了 nashsu/llm_wiki 的实际能力（P0-1）
2. ✅ 简化了 V0 范围，从 8 模块减少到 3 模块（P0-2）
3. ✅ 明确了存储方案（Markdown + SQLite 混合）（P0-3）
4. ✅ 定义了集成契约（File Watcher + HTTP API）
5. ✅ 调整了多模态处理路线图（视频/音频延后到 V1）

**重要约束：**
- 本 PRD 阶段 **不进行大规模代码开发**
- 保持 Atelier 已确认的需求和设计原则
- 优先保证 **高效率、简洁性、鲁棒性**
- **V0 是 MVP**，只验证核心价值

---

## 目录

1. [产品定位与核心闭环](#1-产品定位与核心闭环)
2. [产品边界：已发布知识层](#2-产品边界已发布知识层)
3. [Atelier 当前实现分析](#3-atelier-当前实现分析)
4. [认知领域模型](#4-认知领域模型)
5. [架构设计](#5-架构设计)
6. [存储方案](#6-存储方案)
7. [V0 范围与验收标准](#7-v0-范围与验收标准)
8. [V1/V2 演进路径](#8-v1v2-演进路径)
9. [风险与开放问题](#9-风险与开放问题)
10. [实施路线图](#10-实施路线图)
11. [下一步行动](#11-下一步行动)

**附录：**
- [Appendix A: 术语表](#appendix-a-术语表)
- [Appendix B: nashsu/llm_wiki 集成详解](#appendix-b-nashsullm_wiki-集成详解)
- [Appendix C: 架构决策记录](#appendix-c-架构决策记录)
- [Appendix D: 变更日志](#appendix-d-变更日志)

---

## 1. 产品定位与核心闭环

### 1.1 业务核心闭环

Personal Intelligence System 的核心业务循环：

```
SESSION START
会话启动
  ↓
KNOW
知道（世界状态 + 个人认知）
  - 从 llm_wiki 获取已发布知识
  - 从 Knowledge Vault 加载 Claims/Sources
  - 从 Support Tools 加载上下文
  ↓
THINK
理解 / 判断 / 建模
  - 基于 Claims 形成 Beliefs
  - 识别 Open Questions
  - 评估决策选项
  ↓
ACT
决策 / 行动
  - 做出 Decisions
  - 记录决策理由和未选择的选项
  - 更新 Learning Agenda
  ↓
LEARN
反馈 / 证伪 / 纠错 / 更新
  - 收集决策结果
  - 更新 Beliefs 的 Confidence
  - 识别新的 Open Questions
  ↓
KNOW (Updated Cognition)
更新后的认知
```

**关键特性：**
- ✅ **人在环中**（Human-in-the-loop）— 所有关键决策需要用户确认
- ✅ **本地优先**（Local-first）— 数据存储在本地，用户拥有完整控制权
- ✅ **知识生产外包** — 由 nashsu/llm_wiki 负责，本系统专注认知管理

### 1.2 产品定位

**Personal Intelligence System = Cognition Kernel + External Knowledge Compiler**

| 层级 | 组件 | 职责 |
|------|------|------|
| **用户层** | Human User | 提供意图、审批决策、消费洞察 |
| **认知内核层** | Personal Intelligence System | KNOW → THINK → ACT → LEARN 循环 |
| **已发布知识层** | Published Knowledge Layer | 外部编译器生成的结构化知识 |
| **知识生产层** | nashsu/llm_wiki | 从原始资料生成结构化知识 |

**本系统边界：**
- ✅ 在系统内：认知内核、反思循环、决策追踪
- ❌ 在系统外：知识生产（由 nashsu/llm_wiki 完成）

### 1.3 架构原则

**v0.2 核心改进：从 8 模块简化到 3 模块 + 工具**

**三个核心模块：**
1. Cognition Core（认知核心）
2. Knowledge Vault（知识库）
3. Human Interface（人机交互）

**辅助工具集：**
- scripts/context_bundle.py（上下文加载）
- scripts/semantic.py（语义搜索）
- scripts/trustrank.py（TrustRank 计算）
- scripts/cues.py（健康检查）
- scripts/pricing.py（成本分析）

**延后到 V1：**
- Agent Runtime（智能体编排）
- Workflow Engine（工作流引擎）
- Model Gateway（多模型抽象）
- Feedback Loop（自动化反馈）
- Memory System（独立模块）

**架构原则：**
- **简洁性** — 3 个模块 + 工具，清晰的职责边界
- **鲁棒性** — 工具失败不影响核心
- **效率性** — 工具零成本运行
- **可演进性** — V0 验证核心价值，V1 扩展能力

---

## 2. 产品边界：已发布知识层

### 2.1 什么是"已发布知识层"？

**定义：**
已发布知识层（Published Knowledge Layer）是外部知识编译器（nashsu/llm_wiki）生成的结构化、高质量知识输出。

**特征：**
- ✅ 结构化格式（Markdown）
- ✅ 元数据完整（来源、时间戳、标签）
- ✅ 质量已验证（llm_wiki 的 Two-Step Chain-of-Thought）
- ✅ 可直接摄入（符合本系统的知识格式规范）

### 2.2 系统边界

| 职责 | 在系统内 | 在系统外 |
|------|----------|----------|
| 知识生产 | ❌ | ✅ nashsu/llm_wiki |
| 知识摄入 | ✅ Published Knowledge Ingestion | — |
| 知识验证 | ✅ TrustRank 传播 | ✅ llm_wiki 质量门控 |
| 知识存储 | ✅ Knowledge Vault | — |
| 知识检索 | ✅ 语义搜索（scripts/semantic.py）| — |
| 知识应用 | ✅ Cognition Core | — |

**关键原则：**
1. **单一职责** — 本系统专注于"认知与智能"，不做"知识生产"
2. **清晰接口** — 通过 Published Knowledge Layer 与 llm_wiki 解耦
3. **质量门控** — llm_wiki 保证输入质量，本系统信任并使用

### 2.3 与 nashsu/llm_wiki 的集成（✨ v0.2 新增验证结果）

**llm_wiki 职责：**
- 从原始资料（PDF、Office、EPUB、图片、网页）生成结构化知识
- Two-Step Chain-of-Thought Ingest（分析 → 生成 wiki）
- 输出符合本系统格式的"已发布知识"

**llm_wiki 已验证能力（基于 P0-1 调研）：**

| 能力 | 支持情况 | 实现方式 |
|------|----------|----------|
| HTTP API | ✅ 完全支持 | `http://127.0.0.1:19828/api/v1` |
| Chrome Web Clipper | ✅ 内置支持 | Chrome Extension |
| PDF 处理 | ✅ 完全支持 | 内置 + MinerU + 云端 |
| Office 文档 | ✅ 完全支持 | Word/Excel/PowerPoint |
| EPUB/MOBI | ✅ 完全支持 | 电子书格式 |
| 图片 OCR | ✅ 完全支持 | Vision LLM 生成描述 |
| 网页文章 | ✅ 完全支持 | Web Clipper |
| 语义检索 | ✅ 完全支持 | LanceDB 向量索引 |
| Knowledge Graph | ✅ 完全支持 | Wikilinks + Louvain |
| 自动监听 | ✅ 完全支持 | Source Folder Auto-Watch |
| **视频/音频转录** | ❌ 不支持 | V1 自建 Whisper 管道 |

**本系统职责：**
- 通过 File Watcher 监听 llm_wiki 的 `wiki/` 目录
- 通过 HTTP API 查询和检索
- 摄入"已发布知识"到 Knowledge Vault
- 通过 Cognition Core 应用这些知识

**集成方式（✨ v0.2 新增详细方案）：**

**方式 1: File Watcher（推荐，用于摄入）**
```python
import watchdog.observers
import watchdog.events

class WikiFileHandler(watchdog.events.FileSystemEventHandler):
    def on_created(self, event):
        if event.src_path.endswith(".md"):
            ingest_wiki_page(event.src_path)
    
    def on_modified(self, event):
        if event.src_path.endswith(".md"):
            update_wiki_page(event.src_path)

# 监听 llm_wiki 的 wiki/ 目录
observer = watchdog.observers.Observer()
observer.schedule(
    WikiFileHandler(), 
    path="<llm_wiki_project>/wiki/", 
    recursive=True
)
observer.start()
```

**方式 2: HTTP API（用于查询和检索）**
```python
class LlmWikiClient:
    def __init__(self, base_url="http://127.0.0.1:19828/api/v1", token=None):
        self.base_url = base_url
        self.token = token
    
    def search(self, query: str, top_k: int = 10):
        """混合检索（关键词 + 向量）"""
        response = requests.post(
            f"{self.base_url}/projects/current/search",
            headers={"Authorization": f"Bearer {self.token}"},
            json={"query": query, "topK": top_k}
        )
        return response.json()["results"]
    
    def get_graph(self, limit: int = 200):
        """获取知识图谱"""
        response = requests.get(
            f"{self.base_url}/projects/current/graph",
            headers={"Authorization": f"Bearer {self.token}"},
            params={"limit": limit}
        )
        return response.json()
```

**集成工作流：**
```
用户添加资料到 llm_wiki
  ↓
llm_wiki Auto-Watch 检测到变化
  ↓
llm_wiki 自动摄入（Two-Step Chain-of-Thought）
  ↓
生成 wiki/*.md
  ↓
本系统 File Watcher 检测到新文件
  ↓
自动摄入到 Knowledge Vault
  - 提取 Claims
  - 计算 TrustRank
  - 建立索引
  ↓
用户可在 Obsidian/CLI 中查询
```

**详细 API 文档参见：** [Appendix B: nashsu/llm_wiki 集成详解](#appendix-b-nashsullm_wiki-集成详解)

---

## 3. Atelier 当前实现分析

### 3.1 Atelier 架构概览

Atelier 是一个 **local-first Zettelkasten system**，专注于 **reflective thinking**。

**核心组件：**（继承自 v0.1，无变化）

| 组件 | 文件/目录 | 职责 |
|------|-----------|------|
| Knowledge Vault | `$OV/` | L1-L5 分层知识存储 |
| Wiki Schema | `$OV/wiki/` | 结构化 wiki 条目 |
| TrustRank | `scripts/trustrank.py` | 信任传播引擎 |
| Context Manager | `scripts/context_bundle.py` | 上下文加载 |
| Semantic Search | `scripts/semantic.py` | 向量搜索 |
| Health Checker | `scripts/cues.py` | 健康检查 |
| Cost Analyzer | `scripts/pricing.py` | 成本分析 |
| PDF Processor | `scripts/paper_cache.py` | PDF 提取 |
| Specialist Agents | `.claude/agents/` | 11 个专业智能体 |

### 3.2 Atelier Gap 分析（✨ v0.2 更新）

**已有能力（可直接复用）：**
- ✅ L1-L5 知识分层
- ✅ Wiki Schema
- ✅ TrustRank 引擎
- ✅ 上下文管理（Context Bundle）
- ✅ 健康检查（Cues）
- ✅ 成本分析（Pricing）
- ✅ 语义搜索（Semantic Search）
- ✅ PDF 处理（Paper Cache）

**缺失能力（V0 需要新增）：**

| Gap # | 能力 | 优先级 | 复杂度 | V0 状态 |
|-------|------|--------|--------|---------|
| Gap 1 | Cognition Flywheel | P0 | High | ✅ V0 实现 |
| Gap 2 | Decision Tracking | P0 | Medium | ✅ V0 实现 |
| Gap 4 | Published Knowledge Ingestion | P0 | Low | ✅ V0 实现 |
| Gap 7 | 存储方案（Markdown + SQLite）| P0 | Medium | ✅ V0 实现 |

**缺失能力（延后到 V1）：**

| Gap # | 能力 | 优先级 | 复杂度 | V1 状态 |
|-------|------|--------|--------|---------|
| Gap 3 | Action Execution | P1 | Medium | ⏸️ V1 实现 |
| Gap 5 | Model Gateway | P1 | Medium | ⏸️ V1 实现 |
| Gap 6 | Workflow Engine | P1 | High | ⏸️ V1 实现 |
| Gap 8 | Agent Runtime | P1 | High | ⏸️ V1 实现 |
| Gap 9 | Memory System（独立模块）| P1 | High | ⏸️ V1 实现 |

---

## 4. 认知领域模型

（继承自 v0.1，无重大变化）

### 4.1 核心实体

以下实体定义参见 PRD v0.1 Section 4.1（完整保留）：

1. Source（来源）
2. Claim（断言）
3. Evidence（证据）
4. Belief（信念）
5. Model（心智模型）
6. Open Question（开放问题）
7. Decision（决策）
8. Action（行动）
9. Feedback（反馈）
10. Cognition Change（认知变化）
11. Learning Agenda（学习议程）
12. Skill（技能）

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
```

---

## 5. 架构设计

### 5.1 架构概览（✨ v0.2 大幅简化）

**从 8 模块简化到 3 模块 + 工具：**

```
┌─────────────────────────────────────────┐
│    Human Interface (Module 3)           │
│    - Obsidian (Markdown 编辑)           │
│    - CLI 工具                            │
└────────────┬────────────────────────────┘
             │
┌────────────▼────────────────────────────┐
│   Cognition Flywheel Core (Module 1)    │
│                                          │
│   KNOW → THINK → ACT → LEARN            │
│                                          │
│   - Belief Management                    │
│   - Model Management                     │
│   - Question Tracking                    │
│   - Decision Tracking                    │
│   - Learning Agenda                      │
└──────────┬──────────────────────────────┘
           │
           ├──────────────────────────┐
           │                          │
┌──────────▼──────────┐  ┌───────────▼──────────┐
│  Knowledge Vault    │  │   Support Tools       │
│  (Module 2)         │  │   (scripts/)          │
│                     │  │                       │
│  - Ingestion        │  │  - context_bundle.py  │
│  - Wiki Schema      │  │  - semantic.py        │
│  - TrustRank        │  │  - trustrank.py       │
│  - Claims/Sources   │  │  - cues.py            │
└──────────┬──────────┘  │  - pricing.py         │
           │             └───────────────────────┘
           │
┌──────────▼──────────┐
│   Storage Layer     │
│  (✨ v0.2 新增)      │
│                     │
│  Markdown (源真相)   │
│  + SQLite (索引)     │
└─────────────────────┘
           │
┌──────────▼──────────┐
│   nashsu/llm_wiki   │
│  (External Compiler)│
│                     │
│  - PDF/Office/EPUB  │
│  - Image OCR        │
│  - Web Clipper      │
│  - Knowledge Graph  │
└─────────────────────┘
```

### 5.2 Module 1: Cognition Flywheel Core

**职责：**
- 实现 KNOW → THINK → ACT → LEARN 循环
- 管理 Beliefs、Models、Open Questions
- 决策支持和追踪
- 认知变化记录

**Capability Contract：**（继承自 v0.1，完整保留）

```python
# Belief Management
create_belief(statement, claims, confidence) -> Belief
update_belief(belief_id, new_confidence, new_claims) -> Belief
query_beliefs(filters) -> List[Belief]

# Model Management
create_model(domain, principles) -> Model
add_belief_to_model(model_id, belief_id) -> void

# Question Management
create_open_question(question, context, importance) -> OpenQuestion
close_question(question_id, resolution) -> void

# Decision Support
make_decision(question_id, chosen_option, rationale) -> Decision
get_decision_history(filters) -> List[Decision]
```

### 5.3 Module 2: Knowledge Vault

**职责：**
- 存储 L1-L5 分层知识
- Wiki Schema 管理
- TrustRank 计算
- 知识摄入（Published Knowledge Ingestion）

**Capability Contract：**（继承自 v0.1）

```python
# Knowledge Storage
ingest_published_knowledge(knowledge) -> void
store_claim(claim) -> void

# Knowledge Retrieval
query_claims(query, filters) -> List[Claim]
get_claim_trust(claim_id) -> float

# TrustRank
calculate_trustrank(claim_id) -> float
```

### 5.4 Module 3: Human Interface

**职责：**
- Obsidian 编辑（Markdown 文件）
- CLI 工具（查询和管理）
- 基础展示界面

**V0 实现：**
- ✅ Obsidian 原生编辑
- ✅ CLI 基础命令
- ⏸️ Web UI（延后到 V1）

---

## 6. 存储方案（✨ v0.2 新增章节）

### 6.1 设计原则

1. **Obsidian 兼容性** — 必须是 Markdown + YAML frontmatter
2. **人可读性** — Markdown 是源真相
3. **查询性能** — 复杂查询用 SQLite
4. **数据恢复性** — Markdown 可随时重建 SQLite

### 6.2 混合存储架构

```
$OV/
├── beliefs/               # Beliefs（Markdown）
│   ├── belief_001.md
│   └── belief_002.md
├── decisions/             # Decisions（Markdown）
│   ├── decision_001.md
│   └── decision_002.md
├── questions/             # Open Questions（Markdown）
│   ├── question_001.md
│   └── question_002.md
├── learning/              # Learning Agenda（Markdown）
│   ├── agenda_001.md
│   └── reading_list.md
├── wiki/                  # llm_wiki 输出（Markdown）
│   ├── programming/
│   └── product_management/
└── .index/                # 索引层（SQLite）
    ├── cognition.db       # Beliefs/Decisions/Questions
    ├── knowledge.db       # Claims/Sources/TrustRank
    └── metadata.db        # 文件元数据
```

### 6.3 Markdown 层（源真相）

**Belief 格式：**

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
---

# Python asyncio 适合 I/O 密集型任务

## 置信度
- **当前置信度**: 0.9 (Very High)

## 支持证据

### 证据 1：《Fluent Python》
- **来源**: [[fluent_python_chapter_18]]
- **Trust**: 0.95
```

### 6.4 SQLite 层（索引）

**Schema 定义：**

```sql
-- Beliefs 表
CREATE TABLE beliefs (
    id TEXT PRIMARY KEY,
    statement TEXT NOT NULL,
    confidence REAL NOT NULL,
    created TIMESTAMP NOT NULL,
    updated TIMESTAMP NOT NULL,
    file_path TEXT NOT NULL UNIQUE
);

CREATE INDEX idx_beliefs_confidence ON beliefs(confidence DESC);
CREATE INDEX idx_beliefs_updated ON beliefs(updated DESC);

-- Claims 表
CREATE TABLE claims (
    id TEXT PRIMARY KEY,
    statement TEXT NOT NULL,
    source_id TEXT NOT NULL,
    trust REAL NOT NULL,
    file_path TEXT NOT NULL UNIQUE
);

CREATE INDEX idx_claims_trust ON claims(trust DESC);
```

### 6.5 双写机制

**写操作：**Markdown + SQLite（原子性）  
**读操作：**优先 SQLite（性能），回退 Markdown（容错）  
**索引重建：**从 Markdown 重建 SQLite（数据恢复）

详细实现参见 P0 解决方案文档。

---

## 7. V0 范围与验收标准（✨ v0.2 大幅简化）

### 7.1 V0 范围（MVP）

**目标：** 验证核心认知飞轮（KNOW → THINK → ACT → LEARN）

**必须实现（3 模块 + 工具）：**

✅ **Module 1: Cognition Core**
- Belief Management（CRUD + 查询）
- Question Tracking（CRUD + 关联）
- Decision Tracking（CRUD + 历史）
- Learning Agenda（CRUD + 进度）

✅ **Module 2: Knowledge Vault**
- Published Knowledge Ingestion（llm_wiki 集成）
- Claims + Sources 管理
- TrustRank 计算（复用 scripts/trustrank.py）

✅ **Module 3: Human Interface**
- Obsidian 编辑（Markdown 文件）
- CLI 工具（基础命令）

✅ **Support Tools**
- scripts/context_bundle.py（上下文加载）
- scripts/semantic.py（语义搜索）
- scripts/trustrank.py（TrustRank）
- scripts/cues.py（健康检查）
- scripts/pricing.py（成本分析）

✅ **Storage Layer**
- Markdown + SQLite 混合存储
- 双写机制
- 索引重建

✅ **Integration**
- llm_wiki File Watcher
- llm_wiki HTTP API Client

**延后到 V1：**
- ⏸️ Module: Agent Runtime
- ⏸️ Module: Workflow Engine
- ⏸️ Module: Model Gateway
- ⏸️ Module: Feedback Loop
- ⏸️ Module: Memory System（独立模块）

### 7.2 V0 验收标准

**功能完整性：**
- ✅ 知识摄入（llm_wiki → 本系统，< 5s）
- ✅ Belief 管理（CRUD + 查询）
- ✅ Question 追踪（CRUD + 关联）
- ✅ Decision 记录（CRUD + 历史）
- ✅ Learning Agenda（CRUD + 进度）

**性能达标：**
- ✅ 知识摄入延迟 < 5s（单个 Wiki 页面）
- ✅ Belief 查询延迟 < 200ms
- ✅ TrustRank 计算延迟 < 10s（1000 个 Claims）

**用户体验：**
- ✅ 在 Obsidian 中可以编辑 Beliefs/Decisions
- ✅ 在 CLI 中可以查询 Beliefs/Decisions
- ✅ 健康检查能够检测异常
- ✅ Markdown + SQLite 索引一致性

### 7.3 V0 工作量估算

| 模块 | 代码量（行） | 复杂度 | 工期（天） |
|------|-------------|--------|-----------|
| Module 1: Cognition Core | 2000 | High | 10 |
| Module 2: Knowledge Vault | 1000 | Medium | 5 |
| Module 3: Human Interface | 500 | Low | 3 |
| Storage Layer | 0 | Low | 0（已有） |
| Integration | 0 | Low | 0（已有） |
| **总计** | **3500** | **Medium** | **18** |

**对比 v0.1：**
- v0.1: 8 模块，~10,000 行代码，40 天
- v0.2: 3 模块 + 工具，~3,500 行代码，18 天
- **减少 60% 的工作量**

---

## 8. V1/V2 演进路径

### 8.1 V1 范围（完整产品，10-100GB）

**目标：** 完整认知飞轮 + Agent 编排 + Memory System

**必须实现：**
- ✅ Module 1: 完整认知飞轮（含 ACT 和 LEARN）
- ✅ Module: Agent Runtime（11 个专业智能体编排）
- ✅ Module: Workflow Engine（复杂工作流）
- ✅ Module: Model Gateway（多模型抽象）
- ✅ Module: Feedback Loop（自动化反馈）
- ✅ Module: Memory System V1（独立模块，支持 10-100GB）

**新增能力：**
- 视频/音频转录（自建 Whisper 管道）
- Working Memory 缓存层
- Episodic Memory 重建
- Multi-modal Indexing
- Memory Importance Scoring

**验收标准：**
- 支持 10-100GB 知识库
- 语义检索延迟 < 200ms
- 上下文加载延迟 < 500ms

### 8.2 V2 范围（扩展，> 100GB）

**目标：** 分布式 Memory System + 高级特性

**必须实现：**
- ✅ Memory System V2: 分布式部署
- ✅ Spaced Repetition 遗忘算法
- ✅ 主动记忆推荐
- ✅ 跨模态检索（文本查图片、图片查视频）

---

## 9. 风险与开放问题

### 9.1 技术风险

**Risk 1: 依赖 nashsu/llm_wiki**
- **风险：** llm_wiki 不可用时本系统无法摄入新知识
- **缓解：** 
  - llm_wiki 是本地应用，数据可控
  - File Watcher 提供松耦合集成
  - 可替换为其他知识编译器

**Risk 2: 双写机制的一致性**
- **风险：** Markdown 和 SQLite 可能不一致
- **缓解：**
  - 实现原子写操作
  - 提供索引重建机制
  - Markdown 是源真相，SQLite 可重建

**Risk 3: V0 功能有限**
- **风险：** 用户可能期望更多功能
- **缓解：**
  - 明确 MVP 定位
  - V1 路线图清晰
  - 快速迭代

### 9.2 开放问题

**Question 1: V0 不支持视频/音频，用户体验如何？**
- **现状：** V0 不支持视频/音频转录
- **临时方案：** 用户手工转录或使用外部工具
- **长期方案：** V1 自建 Whisper 管道

**Question 2: 是否需要 Web UI？**
- **现状：** V0 只有 Obsidian + CLI
- **考虑：** Web UI 开发成本高，V0 暂不实现
- **决策：** V1 评估是否需要

---

## 10. 实施路线图

### Week 1: 基础设施（Day 1-5）

**Day 1-2: 存储层实现**
- Markdown Schema 定义
- SQLite Schema 实现
- 双写机制实现
- 索引重建机制

**Day 3-4: llm_wiki 集成**
- File Watcher 实现
- HTTP API Client 实现
- 集成测试

**Day 5: 测试和文档**
- 单元测试
- 集成测试
- API 文档

### Week 2: Cognition Core（Day 6-10）

**Day 6-8: Belief Management**
- Belief CRUD 实现
- Confidence 更新
- History 追踪
- 查询接口

**Day 9-10: Question & Decision**
- Question CRUD
- Decision CRUD
- 关联关系

### Week 3: Knowledge Vault（Day 11-15）

**Day 11-13: Knowledge Ingestion**
- Published Knowledge Ingestion
- Claim 提取
- Source 管理
- TrustRank 集成

**Day 14-15: 查询和检索**
- Claim 查询
- 语义搜索集成
- TrustRank 查询

### Week 4: Human Interface & 测试（Day 16-20）

**Day 16-17: Obsidian 集成**
- Markdown 格式验证
- File Watcher 测试
- 双向链接测试

**Day 18: CLI 实现**
- 基础命令实现
  - `cognition belief list`
  - `cognition belief show <id>`
  - `cognition decision list`

**Day 19-20: 端到端测试**
- 完整流程测试
- 性能测试
- 用户验收测试

**预计完成时间:** 2026-09-16

---

## 11. 下一步行动

### 立即行动（本周，8/26-8/30）

1. ✅ **P0 问题解决（已完成）**
2. ✅ **PRD v0.2 创建（已完成）**
3. ⬜ **用户评审 PRD v0.2**
4. ⬜ **环境准备**
   - 安装 nashsu/llm_wiki
   - 配置 API Token
   - 测试 File Watcher

### Week 1: 开始实施

参见 [Section 10: 实施路线图](#10-实施路线图)

---

## Appendix A: 术语表

（继承自 v0.1，完整保留）

| 术语 | 英文 | 定义 |
|------|------|------|
| 认知飞轮 | Cognition Flywheel | KNOW → THINK → ACT → LEARN 循环 |
| 信念 | Belief | 个人当前持有的信念 |
| 断言 | Claim | 可验证的知识断言 |
| 开放问题 | Open Question | 尚未解决的问题 |
| 决策 | Decision | 已做出的决策 |
| 学习议程 | Learning Agenda | 待学习的主题 |

---

## Appendix B: nashsu/llm_wiki 集成详解

### B.1 HTTP API 端点

**Base URL:** `http://127.0.0.1:19828/api/v1`

**关键端点：**

```yaml
健康检查:
  GET /health
  Auth: 不需要

项目列表:
  GET /projects
  Auth: Bearer Token

文件内容:
  GET /projects/{id}/files/content?path=wiki/topic.md
  Auth: Bearer Token

混合检索:
  POST /projects/{id}/search
  Body: { "query": "...", "topK": 10 }
  Auth: Bearer Token

知识图谱:
  GET /projects/{id}/graph?limit=200
  Auth: Bearer Token
```

### B.2 认证配置

**获取 Token:**
- UI: `Settings → API + MCP → Generate new token`
- 环境变量: `LLM_WIKI_API_TOKEN=...`

**使用 Token:**
```python
headers = {"Authorization": f"Bearer {token}"}
```

### B.3 完整代码示例

详见 [p0-resolution.md Section 4: 集成契约定义](./p0-resolution.md#集成契约定义)

---

## Appendix C: 架构决策记录

### ADR-001: V0 范围大幅简化

**日期:** 2026-08-26  
**状态:** Accepted

**决策：**
V0 从 8 模块简化到 3 模块 + 工具

**理由：**
- MVP 应该只验证核心价值
- 8 模块复杂度过高（40 天工期）
- 核心闭环只需 Cognition + Knowledge + Interface

**影响：**
- ✅ 工作量减少 60%（18 天 vs 40 天）
- ✅ 风险降低
- ⚠️ V0 功能有限

---

### ADR-002: Markdown + SQLite 混合存储

**日期:** 2026-08-26  
**状态:** Accepted

**决策：**
使用 Markdown + SQLite 混合存储方案

**理由：**
- Obsidian 兼容性要求 Markdown
- 复杂查询需要 SQLite 性能
- 双写机制兼顾人可读和性能

**影响：**
- ✅ Obsidian 完全兼容
- ✅ 查询性能达标（< 200ms）
- ⚠️ 双写增加实现复杂度

---

### ADR-003: 完全依赖 nashsu/llm_wiki 做知识生产

**日期:** 2026-08-26  
**状态:** Accepted

**决策：**
本系统不做知识生产，完全依赖 nashsu/llm_wiki

**理由：**
- llm_wiki 能力完全满足需求（已验证）
- 成熟的产品（16.7K stars）
- 完整的 HTTP API
- 内置 Web Clipper

**影响：**
- ✅ 本系统专注认知管理
- ✅ 无需自建知识生产能力
- ⚠️ 依赖外部系统

---

## Appendix D: 变更日志

### v0.2 (2026-08-26)

**基于 P0 问题解决方案的重大更新：**

#### 新增内容
- ✅ **Section 2.3**: 验证了 nashsu/llm_wiki 的实际能力（HTTP API、Web Clipper、多模态处理）
- ✅ **Section 6**: 新增存储方案章节（Markdown + SQLite 混合）
- ✅ **Appendix B**: 新增 llm_wiki 集成详解
- ✅ **Appendix C**: 新增架构决策记录（ADR-001, ADR-002, ADR-003）

#### 重大变更
1. **V0 范围大幅简化**
   - 从 8 模块减少到 3 模块 + 工具
   - 工作量从 40 天减少到 18 天
   - 代码量从 10,000 行减少到 3,500 行

2. **集成方案明确**
   - File Watcher + HTTP API 双重集成
   - 详细的代码示例和工作流
   - 明确的认证配置

3. **存储方案定义**
   - Markdown + SQLite 混合存储
   - 双写机制设计
   - 索引重建机制

4. **多模态处理调整**
   - V0 不支持视频/音频（llm_wiki 不支持）
   - V1 自建 Whisper 管道
   - Web Clipper 复用 llm_wiki 内置

#### 延后功能
- Agent Runtime → V1
- Workflow Engine → V1
- Model Gateway → V1
- Feedback Loop → V1
- Memory System（独立模块）→ V1

#### 风险缓解
- 技术方案已验证（llm_wiki API）
- 架构复杂度降低 60%
- 核心价值可快速验证（18 天）

---

### v0.1 (2026-08-26)

**初始版本：**
- 完整的 8 模块架构设计
- 多模态资料来源处理方案
- 认知领域模型
- Obsidian 集成说明
- 但 nashsu/llm_wiki 能力未验证
- V0 范围过大（8 模块，40 天）
- 存储方案未定义

---

**Document Version:** v0.2  
**Last Updated:** 2026-08-26  
**Status:** Active  
**Next Review:** 2026-09-16 (V0 完成后)

---