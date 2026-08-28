# 架构规范 — Personal Intelligence System with Cognition Layer

**版本:** v1.0  
**日期:** 2026-08-27  
**状态:** Architecture Specification（架构设计）  
**改动原则:** 最小改动（5-7%）+ 完全可解耦

---

## 📋 目录

1. [架构概览](#1-架构概览)
2. [现有 Atelierr 架构](#2-现有-atelierr-架构)
3. [新增 Cognition Layer 架构](#3-新增-cognition-layer-架构)
4. [数据模型](#4-数据模型)
5. [模块职责](#5-模块职责)
6. [接口契约](#6-接口契约)
7. [存储方案](#7-存储方案)
8. [集成方案](#8-集成方案)
9. [改动清单](#9-改动清单)
10. [可解耦性验证](#10-可解耦性验证)

---

## 1. 架构概览

### 1.1 系统定位

**Personal Intelligence System = Atelierr (95%) + Cognition Layer (5%)**

```
┌─────────────────────────────────────────────────────────────┐
│           Personal Intelligence System                       │
│                                                              │
│  ┌────────────────────────────────────────────────────┐    │
│  │         Atelierr (现有系统，保持不变)                 │    │
│  │                                                      │    │
│  │  - 15 个 AI 智能体                                   │    │
│  │  - L1-L5 知识分层                                    │    │
│  │  - TrustRank 引擎                                    │    │
│  │  - Wiki Schema                                       │    │
│  │  - 语义搜索                                           │    │
│  │  - 所有反思工作流                                     │    │
│  │  - 57 个工具脚本                                      │    │
│  └────────────────────────────────────────────────────┘    │
│                          ↑                                   │
│                          │ 使用 TrustRank + 语义搜索         │
│                          ↓                                   │
│  ┌────────────────────────────────────────────────────┐    │
│  │    Cognition Layer (新增，L3.5 层，可解耦)           │    │
│  │                                                      │    │
│  │  - Belief 管理                                       │    │
│  │  - Question 追踪                                     │    │
│  │  - Decision 追踪                                     │    │
│  │  - Confidence 计算                                   │    │
│  └────────────────────────────────────────────────────┘    │
│                          ↑                                   │
│                          │ 摄入知识                          │
│                          ↓                                   │
│  ┌────────────────────────────────────────────────────┐    │
│  │      nashsu/llm_wiki (外部，知识生产)                │    │
│  │                                                      │    │
│  │  - PDF/Office/EPUB → Markdown                       │    │
│  │  - Web Clipper                                       │    │
│  │  - 向量检索                                           │    │
│  └────────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────────┘
```

### 1.2 核心原则

1. **最小改动** — 改动代码量 < 10%
2. **完全可解耦** — Cognition Layer 可以完全删除，Atelierr 100% 恢复
3. **Local-first** — 所有数据存储在本地 Markdown
4. **复用优先** — 最大化复用 Atelierr 现有能力

---

## 2. 现有 Atelierr 架构

### 2.1 L1-L5 知识分层（完整保留）

```
┌─────────────────────────────────────────────────────────────┐
│  L5 — Foundation (reserved)                                  │
│       universally certified                                  │
├─────────────────────────────────────────────────────────────┤
│  L4 — Wiki ($OV/wiki/)                                      │
│       locally certified, TrustRank-scored                   │
│       - Wiki Schema (protocols/wiki-schema.md)              │
│       - Claims with [C1], [C2] markers                      │
│       - @anchor, @cite, @pass markers                       │
│       - scripts/trust.py 计算 TrustRank                     │
├─────────────────────────────────────────────────────────────┤
│  L3 — Papers ($OV/papers/, $OV/preprints/)                  │
│       peer-reviewed, externally certified                   │
├─────────────────────────────────────────────────────────────┤
│  L2 — Working notes                                          │
│       $OV/daily-notes/, $OV/reflections/,                   │
│       $OV/research/, $OV/agent-findings/                    │
│       alloy by default                                      │
├─────────────────────────────────────────────────────────────┤
│  L1 — Raw capture                                            │
│       $OV/inbox/, $OV/cache/, Readwise                      │
│       fast, sloppy, ephemeral                               │
└─────────────────────────────────────────────────────────────┘
```

### 2.2 15 个 AI 智能体（完整保留）

| Agent | Le Cercle 原型 | 职责 |
|-------|---------------|------|
| **Researcher** | Observer | 搜索笔记，收集上下文 |
| **Synthesizer** | Colorist | 综合洞察，形成整体画面 |
| **Challenger** | Critic | 挑战假设，提出反例 |
| **Curator** | Collector | 整理笔记，压实内容 |
| **Librarian** | Cataloguer | 推荐阅读材料 |
| **Scout** | Flâneur | 外部搜索，获取最新信息 |
| **Reader** | — | 深度阅读（单镜头） |
| **Scholar** | — | 学术阅读（深度认知） |
| **Thinker** | — | 独立思考，提供全新视角 |
| **Scribe** | Typewriter | 记录捕获，逐字记录 |
| **Evolver** | Master | 系统进化，改进 Atelier |
| **Reviewer** | Arbiter | 质量审查 |
| **Privacy Reviewer** | Steward | 隐私审查 |
| **Forgetter** | Conservator | 主动遗忘，清理过时内容 |
| **Meeting Processor** | Stenographer | 会议记录处理 |

### 2.3 核心命令（完整保留）

```bash
/hi                  # 会话菜单（意图路由器）
/daily-reflection    # 每日反思
/weekly              # 周度回顾
/decision            # 决策日志
/energy-audit        # 能量审计
/explore             # 探索连接
/read                # 深度阅读
/curate              # 整理收件箱
/promote             # 提升到 Wiki
/lint                # 质量检查
/system-review       # 系统审查
/sync                # 同步捕获
/prm                 # PRM 验证
```

### 2.4 核心脚本（完整保留）

```python
scripts/trust.py              # TrustRank 引擎
scripts/semantic.py           # 语义搜索（LanceDB + BGE-M3）
scripts/lint.py               # 结构检查
scripts/context_bundle.py     # 上下文加载
scripts/cues.py               # 健康检查
scripts/privacy_check.py      # 隐私检查
# ... 其他 50+ 脚本
```

---

## 3. 新增 Cognition Layer 架构

### 3.1 L3.5 层定位

```
L4 — Wiki (locally certified)
     ↑ 引用 Claims
     │
────────────────────────────────
L3.5 — Cognition (新增)          ← 插入这一层
       structured thinking
       - Beliefs (基于 Wiki Claims)
       - Questions (待解决问题)
       - Decisions (决策追踪)
────────────────────────────────
     ↓ 证据来源
L3 — Papers (externally certified)
```

**为什么是 L3.5？**
- **比 L4 更动态** — Beliefs 的 Confidence 会变化
- **比 L3 更结构化** — 不是原始论文，而是基于证据的信念
- **比 L2 更可靠** — 不是随意的想法，而是经过验证的认知

### 3.2 Cognition Layer 组件

```
Cognition Layer (L3.5)
├── Beliefs（信念）
│   ├── Statement（陈述）
│   ├── Confidence（置信度，0-1）
│   ├── Claims（引用 L4 Wiki 的 [C1], [C2]）
│   └── Status（DRAFT → ACTIVE → QUESTIONED → REFUTED）
│
├── Questions（问题）
│   ├── Question Text（问题文本）
│   ├── Priority（优先级，自动计算）
│   ├── Importance（重要性，用户输入）
│   ├── Urgency（紧急性，用户输入）
│   └── Status（OPEN → ANSWERED → ARCHIVED）
│
└── Decisions（决策）
    ├── Title（决策标题）
    ├── Question（关联的 Question）
    ├── Chosen Option（选中的方案）
    ├── Alternatives（备选方案）
    ├── Rationale（决策理由，引用 Beliefs）
    ├── Status（DRAFT → EXECUTED → EVALUATED）
    └── Satisfaction（执行满意度，0-1）
```

### 3.3 新增 Agent（第 16 个）

```
Cognition Manager（Le Analyste）
├── 职责
│   ├── 计算 Belief Confidence（基于 TrustRank）
│   ├── 计算 Question Priority（混合用户输入 + 系统计算）
│   ├── 追踪 Decision 执行结果
│   └── 检测认知健康异常
│
├── 输入
│   ├── Beliefs/Questions/Decisions Markdown 文件
│   ├── Wiki Claims（通过 trust.py）
│   └── TrustRank 分数
│
└── 输出
    ├── 更新后的 Confidence
    ├── 计算后的 Priority
    └── 认知健康报告
```

### 3.4 新增命令（2 个 + 2 个微调）

**新增命令：**
```bash
/belief              # Belief 管理
/question            # Question 追踪
```

**微调命令：**
```bash
/decision            # 增强：集成 Cognition Layer
/daily-reflection    # 增强：增加认知健康检查
```

### 3.5 新增脚本（3 个）

```python
scripts/belief.py        # Belief CRUD + Confidence 计算
scripts/question.py      # Question CRUD + Priority 计算
scripts/cognition.py     # 健康检查 + 批量操作
```

---

## 4. 数据模型

### 4.1 Belief（信念）

**文件位置:** `$OV/cognition/beliefs/<id>.md`

**Markdown 格式：**
```yaml
---
type: belief
id: belief_20260827_001
statement: "Python asyncio 适合 I/O 密集型任务"
confidence: 0.85
status: ACTIVE
created: 2026-08-27T10:00:00Z
updated: 2026-08-27T15:00:00Z
tags: [python, asyncio, performance]

# 引用 Wiki Claims
claims:
  - source: "wiki/python_asyncio.md"
    claim_id: C1
    trust_rank: 0.92
  - source: "wiki/concurrency_patterns.md"
    claim_id: C3
    trust_rank: 0.88

# 关联
related_questions:
  - question_20260820_001
related_decisions:
  - decision_20260827_001
---

## Statement

Python asyncio 适合 I/O 密集型任务。

## 论证

基于以下证据：

1. **Wiki Claim:** [wiki/python_asyncio.md [C1]](wiki/python_asyncio.md#^c1)
   - TrustRank: 0.92
   - 内容：asyncio 通过事件循环实现高并发 I/O

2. **Wiki Claim:** [wiki/concurrency_patterns.md [C3]](wiki/concurrency_patterns.md#^c3)
   - TrustRank: 0.88
   - 内容：asyncio 在网络 I/O 场景下性能优于 threading

## Confidence 计算

```
Base Confidence = avg(0.92, 0.88) = 0.90
Diversity Bonus = 2 sources * 0.05 = 0.10
但 max Diversity Bonus = 0.20，实际 = 0.10

但两个来源都来自同一个 Wiki，降低到 0.05
Final Confidence = min(0.90 + 0.05, 1.0) = 0.85
```

## 状态历史

- 2026-08-27 15:00: Confidence 从 0.80 更新为 0.85（新增 Claim C3）
- 2026-08-27 10:00: 创建（DRAFT → ACTIVE）
```

**状态机：**
```
DRAFT → ACTIVE → QUESTIONED → REFUTED/ARCHIVED
  ↓       ↓          ↓
创建    激活      发现反例
```

### 4.2 Question（问题）

**文件位置:** `$OV/cognition/questions/<id>.md`

**Markdown 格式：**
```yaml
---
type: question
id: question_20260820_001
question: "什么时候应该使用 asyncio 而不是 threading？"
priority: 0.78
importance: 0.8        # 用户输入
urgency: 0.6           # 用户输入
status: OPEN
created: 2026-08-20T10:00:00Z
updated: 2026-08-27T14:00:00Z
tags: [python, concurrency]

# 关联
related_beliefs:
  - belief_20260827_001
blocking_decisions:
  - decision_20260827_001

# 系统计算的因子
system_factors:
  dependent_beliefs: 2
  blocking_decisions: 1
  open_days: 7
---

## 背景

在设计新的 Web 爬虫时，需要选择并发模型。

## 当前理解

- [[Belief belief_20260827_001]]: asyncio 适合 I/O 密集型
- threading 适合需要并行的场景

## 待验证

- [ ] 性能对比测试
- [ ] 生产环境案例调研
- [ ] CPU 密集型场景对比

## Priority 计算

```
User Score = importance * 0.6 + urgency * 0.4
           = 0.8 * 0.6 + 0.6 * 0.4 = 0.72

System Score = (2 beliefs * 0.4 + 1 decision * 0.5 + 7 days * 0.01)
             = 0.8 + 0.5 + 0.07 = 1.37
             = min(1.37, 1.0) = 1.0

Final Priority = user_score * 0.6 + system_score * 0.4
               = 0.72 * 0.6 + 1.0 * 0.4 = 0.78
```
```

### 4.3 Decision（决策）

**文件位置:** `$OV/cognition/decisions/<id>.md`

**Markdown 格式：**
```yaml
---
type: decision
id: decision_20260827_001
title: "使用 asyncio 实现 Web Crawler"
question_id: question_20260820_001
chosen_option: "asyncio"
alternatives: ["threading", "multiprocessing"]
decided_at: 2026-08-27T14:00:00Z
status: EXECUTED
executed_at: 2026-09-01T10:00:00Z
satisfaction: 0.9
tags: [python, asyncio, crawler]

# 基于的信念
based_on_beliefs:
  - belief_20260827_001
---

## 决策背景

项目需要高并发 Web 爬虫，基于 [[Belief belief_20260827_001]]。

## 备选方案

### 方案 1: asyncio ✅

**优点:**
- 高性能，单线程可达 1000+ req/s
- 内存占用低
- 基于 [[Belief belief_20260827_001]]（Confidence: 0.85）

**缺点:**
- 不适合 CPU 密集型任务
- 调试相对复杂

### 方案 2: threading

**优点:**
- 简单，库支持好
- 适合混合 I/O + CPU 任务

**缺点:**
- GIL 限制，性能较低
- 高并发时线程开销大

### 方案 3: multiprocessing

**优点:**
- 真正的并行
- CPU 密集型性能好

**缺点:**
- 进程开销大
- 进程间通信复杂

## 决策理由

选择 asyncio，因为：
1. 项目是纯 I/O 密集型（网络请求）
2. 基于 [[Belief belief_20260827_001]]（Confidence: 0.85）
3. 预期性能满足需求（1000 req/s）

## 执行结果

**预期:**
- 性能: 1000 req/s
- 并发: 100 连接

**实际:**
- 性能: 1200 req/s ✅
- 并发: 100 连接 ✅
- 问题: CPU 密集型任务（JSON 解析）会阻塞事件循环

**满意度:** 0.9

## 经验教训

- asyncio 适合纯 I/O 场景，符合预期
- 需要配合 `ProcessPoolExecutor` 处理 CPU 密集型任务
- 建议更新 [[Belief belief_20260827_001]]，增加"需要与 ProcessPoolExecutor 配合"的说明
```

---

## 5. 模块职责

### 5.1 Atelierr 核心（保持不变）

| 模块 | 职责 | 不变 |
|------|------|------|
| **Trust Engine** | 计算 Wiki TrustRank | ✅ |
| **Semantic Search** | 语义检索（LanceDB + BGE-M3） | ✅ |
| **Wiki Layer (L4)** | 结构化知识存储 | ✅ |
| **15 Agents** | 反思、综合、阅读、搜索... | ✅ |
| **Workflows** | /hi, /daily-reflection, /weekly... | ✅ |
| **Lint** | 结构检查、隐私检查 | ✅ |

### 5.2 Cognition Layer（新增）

| 模块 | 职责 | 依赖 Atelierr 的能力 |
|------|------|---------------------|
| **Belief Manager** | CRUD Beliefs | trust.py (TrustRank) |
| **Question Tracker** | CRUD Questions | semantic.py (检索) |
| **Decision Tracker** | CRUD Decisions | — |
| **Cognition Manager Agent** | 自动计算 Confidence/Priority | trust.py, semantic.py |
| **Health Checker** | 检测认知异常 | cues.py (健康检查框架) |

---

## 6. 接口契约

### 6.1 Cognition Layer → Atelierr Trust Engine

**调用:** `scripts/trust.py`

**输入:**
```python
# Cognition Layer 读取 Wiki Claims 的 TrustRank
from scripts.trust import TrustRank

trust_engine = TrustRank()
claim_trust = trust_engine.get_claim_trust(
    wiki_file="wiki/python_asyncio.md",
    claim_id="C1"
)
# 返回: 0.92
```

**契约:**
- ✅ Atelierr 的 `trust.py` 不感知 Cognition Layer
- ✅ Cognition Layer 只读取 TrustRank 结果，不修改
- ✅ 如果 Wiki Claim 不存在，返回 0.0

### 6.2 Cognition Layer → Atelierr Semantic Search

**调用:** `scripts/semantic.py`

**输入:**
```python
# Cognition Layer 使用语义搜索查找相关 Beliefs
from scripts.semantic import SemanticSearch

search = SemanticSearch()
results = search.query(
    query="asyncio performance",
    top_k=5,
    filter_paths=["cognition/beliefs/"]
)
# 返回: [(belief_001.md, 0.92), (belief_003.md, 0.85), ...]
```

**契约:**
- ✅ Atelierr 的 `semantic.py` 不感知 Cognition Layer
- ✅ Cognition Layer 的 Markdown 文件自动被 semantic.py 索引
- ✅ 通过 `filter_paths` 参数过滤到 `cognition/` 目录

### 6.3 Cognition Layer → Wiki Schema

**契约:**
```yaml
# Belief 引用 Wiki Claim
claims:
  - source: "wiki/python_asyncio.md"  # Wiki 文件路径
    claim_id: C1                       # Claim ID
    trust_rank: 0.92                   # 从 trust.py 读取

# Wiki 文件格式（不变）
## Claims
### [C1] Asyncio 适合 I/O 密集型任务 ^c1
```

**关键点:**
- ✅ Cognition Layer 引用 Wiki Claims，但不修改 Wiki 文件
- ✅ Wiki Schema 保持不变
- ✅ 单向依赖：Cognition → Wiki，Wiki 不感知 Cognition

---

## 7. 存储方案

### 7.1 Markdown 为源真相

**目录结构:**
```
$OV/
├── wiki/                          # L4 (不变)
│   ├── python_asyncio.md
│   └── concurrency_patterns.md
│
├── cognition/                     # L3.5 (新增)
│   ├── beliefs/
│   │   ├── belief_20260827_001.md
│   │   └── belief_20260827_002.md
│   ├── questions/
│   │   └── question_20260820_001.md
│   └── decisions/
│       └── decision_20260827_001.md
│
└── .index/                        # SQLite 索引 (新增)
    └── cognition.db
```

### 7.2 SQLite 作为索引

**Schema:**
```sql
-- Beliefs 表
CREATE TABLE beliefs (
    id TEXT PRIMARY KEY,
    statement TEXT NOT NULL,
    confidence REAL,
    status TEXT,
    created_at TIMESTAMP,
    updated_at TIMESTAMP,
    markdown_path TEXT NOT NULL
);

CREATE INDEX idx_beliefs_status ON beliefs(status);
CREATE INDEX idx_beliefs_confidence ON beliefs(confidence);

-- Claims 关联表
CREATE TABLE belief_claims (
    belief_id TEXT,
    wiki_file TEXT,
    claim_id TEXT,
    trust_rank REAL,
    FOREIGN KEY (belief_id) REFERENCES beliefs(id)
);

-- Questions 表
CREATE TABLE questions (
    id TEXT PRIMARY KEY,
    question TEXT NOT NULL,
    priority REAL,
    importance REAL,
    urgency REAL,
    status TEXT,
    created_at TIMESTAMP,
    updated_at TIMESTAMP,
    markdown_path TEXT NOT NULL
);

CREATE INDEX idx_questions_priority ON questions(priority DESC);
CREATE INDEX idx_questions_status ON questions(status);

-- Decisions 表
CREATE TABLE decisions (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    question_id TEXT,
    chosen_option TEXT,
    status TEXT,
    satisfaction REAL,
    decided_at TIMESTAMP,
    executed_at TIMESTAMP,
    markdown_path TEXT NOT NULL,
    FOREIGN KEY (question_id) REFERENCES questions(id)
);

CREATE INDEX idx_decisions_status ON decisions(status);
```

**同步策略:**
- ✅ Markdown 是源真相
- ✅ SQLite 自动同步（File Watcher）
- ✅ 冲突时以 Markdown 为准

---

## 8. 集成方案

### 8.1 与 nashsu/llm_wiki 集成

```
nashsu/llm_wiki (外部，独立运行)
    ↓
  生成 wiki/ 目录（Markdown 文件）
    ↓
  软链接 → $OV/wiki/
    ↓
Atelierr trust.py 计算 TrustRank
    ↓
Cognition Layer 读取 TrustRank
    ↓
计算 Belief Confidence
```

**关键点:**
- ✅ llm_wiki 独立运行，不感知 Atelierr
- ✅ 通过软链接零侵入集成
- ✅ Atelierr 正常处理 wiki/ 文件
- ✅ Cognition Layer 使用 TrustRank 结果

### 8.2 命令集成

**增强 `/daily-reflection`:**
```bash
# 现有输出（不变）
## 今日回顾
...

## 能量审计
...

# 新增输出
## 认知健康检查

⚠️ 需要关注:
1. Belief belief_003: "MySQL 比 PostgreSQL 快"
   Confidence: 0.9 → 0.6 (-33%)
   原因: 新增反例 wiki/database_benchmarks.md#[C7]
   建议: 标记为 QUESTIONED

2. Question question_008: "如何优化 GraphQL 查询？"
   已开放 14 天未解决
   Priority: 0.85 (高)
   建议: 安排本周处理

[1] 标记 Belief belief_003 为 QUESTIONED
[2] 查看详情
[3] 跳过
```

**增强 `/decision`:**
```bash
# 现有流程（不变）
User: /decision "使用 Redis 还是 Memcached？"

# 新增：自动关联 Beliefs
System: 
找到相关 Beliefs:
- [[Belief belief_005]]: Redis 支持持久化 (Confidence: 0.90)
- [[Belief belief_012]]: Memcached 性能略高 (Confidence: 0.75)

是否基于这些 Beliefs 做决策？[y/N]

# 决策完成后，自动创建 Decision 文件
System: ✅ 已创建 Decision decision_20260827_002
  文件: $OV/cognition/decisions/decision_20260827_002.md
```

---

## 9. 改动清单

### 9.1 新增文件

**Agent:**
```
.claude/agents/cognition-manager.md    # 第 16 个 Agent
```

**Commands:**
```
.claude/commands/belief.md
.claude/commands/question.md
```

**Scripts:**
```
scripts/belief.py                      # ~400 行
scripts/question.py                    # ~300 行
scripts/cognition.py                   # ~400 行
```

**Data:**
```
$OV/cognition/beliefs/
$OV/cognition/questions/
$OV/cognition/decisions/
$OV/.index/cognition.db
```

**总计:** 6 个文件 + 3 个目录 + ~1,500 行代码

### 9.2 微调文件

**Commands:**
```
.claude/commands/daily-reflection.md   # 增加认知健康检查（~30 行）
.claude/commands/decision.md           # 集成 Cognition Layer（~50 行）
```

**Protocols:**
```
protocols/local-first-architecture.md  # 增加 L3.5 说明（~20 行）
```

**Registry:**
```
harness/agents.toml                    # 新增 cognition-manager 条目（~15 行）
harness/commands.toml                  # 新增 belief/question 条目（~20 行）
```

**总计:** 5 个文件 + ~135 行代码

### 9.3 改动统计

| 类型 | 保留 | 新增 | 微调 |
|------|------|------|------|
| **Agent** | 15 个 | 1 个 | 0 个 |
| **Command** | 13 个 | 2 个 | 2 个 |
| **Script** | 54 个 | 3 个 | 0 个 |
| **Protocol** | 10 个 | 0 个 | 1 个 |
| **代码行数** | ~20,000 行 | ~1,500 行 | ~135 行 |
| **改动比例** | 95% | 7.5% | 0.7% |

**总改动比例:** ~8%

---

## 10. 可解耦性验证

### 10.1 删除步骤

```bash
# Step 1: 删除数据
rm -rf $OV/cognition/
rm -rf $OV/.index/cognition.db

# Step 2: 删除脚本
rm scripts/belief.py
rm scripts/question.py
rm scripts/cognition.py

# Step 3: 删除命令
rm .claude/commands/belief.md
rm .claude/commands/question.md

# Step 4: 删除 Agent
rm .claude/agents/cognition-manager.md

# Step 5: 回退微调
git revert <commit-hash>  # daily-reflection 微调
git revert <commit-hash>  # decision 微调
git revert <commit-hash>  # local-first-architecture 微调
git revert <commit-hash>  # agents.toml 微调
git revert <commit-hash>  # commands.toml 微调
```

### 10.2 验证结果

**删除后 Atelierr 状态:**
- ✅ 15 个 Agent 正常工作
- ✅ 所有命令正常工作
- ✅ TrustRank 引擎正常工作
- ✅ 语义搜索正常工作
- ✅ Wiki Schema 正常工作
- ✅ 所有脚本正常工作

**验证命令:**
```bash
# 验证 trust.py
uv run scripts/trust.py --check

# 验证 semantic.py
uv run scripts/semantic.py --test

# 验证 lint.py
uv run scripts/lint.py

# 验证 harness
python3 scripts/harness_lint.py
python3 scripts/harness_smoke.py
```

**预期结果:** 所有测试通过，Atelierr 100% 恢复

---

## 总结

### ✅ 架构特点

1. **最小改动** — 8% 代码改动
2. **完全可解耦** — 5 步删除，100% 恢复
3. **单向依赖** — Cognition → Atelierr，Atelierr 不感知 Cognition
4. **Local-first** — Markdown 源真相
5. **复用优先** — TrustRank、语义搜索、Wiki Schema

### 📊 改动清单

- **新增:** 6 个文件 + 3 个目录 + 1,500 行代码
- **微调:** 5 个文件 + 135 行代码
- **总改动:** 8%

### 🎯 下一步

1. ✅ 架构已梳理清楚
2. ⏭️ 等待你确认架构
3. ⏭️ 开始实施阶段 1（数据层）

---

**创建时间:** 2026-08-27 13:10  
**文档版本:** v1.0  
**改动比例:** 8%  
**可解耦性:** 100%
