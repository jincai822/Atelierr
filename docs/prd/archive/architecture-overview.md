# Atelierr 系统架构详解 — 现有 vs 计划扩展

**日期:** 2026-08-26  
**文档类型:** 架构说明

---

## 📚 现有 Atelierr 系统架构

Atelierr 是一个 **local-first 的个人反思与知识管理系统**，由以下核心模块组成：

---

### 1️⃣ **知识分层模型 (L1-L5)**

这是整个系统的基础架构，按照"结晶深度"将知识分为 5 层：

```
L5 — Foundation (保留)
     教科书级别的普遍认证知识
────────────────────────────────────
L4 — Wiki (本地认证层)
     $OV/wiki/
     - 结构化、有锚点、TrustRank 评分
     - 每个 Wiki 条目包含 Claims [C1], [C2]...
     - trust.py 计算信任分数
────────────────────────────────────
L3 — Papers & Preprints (外部认证层)
     $OV/papers/, $OV/preprints/
     - 同行评审论文、高引用文献
     - Wiki Claims 的锚点来源
────────────────────────────────────
L2 — Working Notes (工作层)
     $OV/daily-notes/, $OV/reflections/,
     $OV/research/, $OV/wip/, $OV/gtd/
     - 日常思考、会话反思、研究笔记
     - "合金"(alloy)，未经验证但可搜索
────────────────────────────────────
L1 — Raw Capture (原始捕获层)
     $OV/inbox/, $OV/cache/, Readwise
     - 快速、粗糙、短暂
     - 等待向上提升
```

**核心原则：**
- **向上提升 (Opportunistic Promotion):** L1 → L2 → L4
- **目录即认证:** 一个文件是 Wiki 条目，是因为它在 `$OV/wiki/` 下
- **无降级流程:** 失效是增量式的（bi-temporal 标记），不删除

---

### 2️⃣ **Le Cercle（15 个专业 Agent 团队）**

这是执行具体任务的 Agent 层，在 `harness/agents.toml` 中定义：

| Agent | 角色 | 职责 |
|-------|------|------|
| **Researcher** | 研究员 | 从 `$OV/` 搜集原始上下文（daily notes, wiki） |
| **Scout** | 侦察兵 | 从外部网络搜集信息 |
| **Reader** | 读者 | 通过 4 个视角深度阅读文章（Critical, Structural, Practical, Dialectical） |
| **Scholar** | 学者 | Reader 的深度认知版本，处理密集理论 |
| **Synthesizer** | 综合员 | 读取上下文并产生结构化反思、总结、洞察 |
| **Thinker** | 思考者 | 使用结构化框架独立思考 |
| **Curator** | 策展人 | 起草笔记操作（压缩、合并、新笔记、wiki 条目） |
| **Challenger** | 挑战者 | 提出尖锐问题，肯定或反驳用户想法 |
| **Librarian** | 图书管理员 | 推荐相关阅读、资源、思想家 |
| **Meeting** | 会议记录员 | 处理会议转录成结构化笔记 |
| **Scribe** | 抄写员 | 记录用户口述内容（verbatim） |
| **Reviewer** | 审查员 | 质量检查反思输出和系统演化变更 |
| **Evolver** | 进化者 | 改进反思系统本身（agents, commands, frameworks） |
| **Forgetter** | 遗忘者 | 主动衰减扫描，找出不再有价值的内容 |
| **Privacy Reviewer** | 隐私审查员 | 语义隐私扫描，捕捉泄露 |

**定义位置:**
- `harness/agents.toml` — 跨平台注册表
- `.claude/agents/*.md` — Claude Code 原生规范
- `.codex/agents/*.toml` — Codex CLI 适配器

---

### 3️⃣ **命令系统 (Commands)**

用户通过命令触发工作流，在 `harness/commands.toml` 中定义：

| 命令 | 功能 | 输出位置 |
|------|------|---------|
| `/hi` | 通用入口 — 意图路由器 | 根据意图调度 |
| `/reflect` | 别名 → `/hi` | - |
| `/daily-reflection` | 每日反思 — 基于 profile、近期笔记 | `$OV/reflections/` |
| `/read` | 阅读与讨论 — 3 种阅读流程 | `$OV/reflections/` |
| `/weekly` | 结构化周回顾 | `$OV/reflections/` |
| `/review` | 目标回顾（季度/月度） | `$OV/reflections/` |
| `/decision` | 结构化决策日志 + 框架交叉验证 | `$OV/reflections/` or `$OV/research/` |
| `/energy-audit` | 体力、精神、情感、社交能量评估 | `$OV/reflections/` |
| `/explore` | 深度探索某主题 | `$OV/reflections/` |
| `/curate` | 压缩/合并笔记，创建 wiki 条目 | 草稿 → 用户批准后写入 |
| `/dine` | 饮食记录与审计 | `$OV/dining/` |
| `/sync` | 同步移动端捕获（zettelm 子模块） | `$OV/daily-notes/` |
| `/introspect` | 重建自我模型（profile） | `profile/` |
| `/lint` | 质量检查（wiki schema, harness health） | 报告输出 |
| `/system-review` | 系统自我审查（周度） | 报告输出 |

**定义位置:**
- `harness/commands.toml` — 跨平台注册表
- `.claude/commands/*.md` — Claude Code 原生规范
- `.agents/skills/<command>/` — Codex CLI 技能

---

### 4️⃣ **信任引擎 (Trust Engine)**

**核心脚本:** `scripts/trust.py`

**功能:**
- 计算 Wiki 条目的 **TrustRank** 分数
- 使用 **Personalized PageRank** 算法
- 以外部锚点（L3 Papers）作为信任种子
- Claim 级别的细粒度信任传播

**输入:**
- `$OV/wiki/` 下的所有 `.md` 文件
- Wiki Schema 定义的 Claims `[C1]`, `[C2]`...
- `@anchor` 标记（指向 L3 Papers）
- `@cite` 标记（wiki 内部引用）

**输出:**
- 每个 Wiki 条目的 TrustRank 分数
- 每个 Claim 的 TrustRank 分数

---

### 5️⃣ **Wiki Schema (结构化知识格式)**

**定义:** `protocols/wiki-schema.md`

**一个 Wiki 条目必须包含:**

```markdown
# Title (必须的 H1)

## Summary
概述，1-3 段

## Claims

### [C1] 一句话陈述

详细论证... ^c1

```anchors
@anchor: s2:paper-id | valid_at: 2026-04-06
@pass: reviewer | status: verified | at: 2026-04-06
```

@cite: [[Other Wiki Entry]] | valid_at: 2026-04-06

### [C2] 另一句话陈述

... ^c2

```anchors
@anchor: arxiv:paper-id | valid_at: 2026-04-06
```

## Revision Log
- 2026-04-12: [C2] 锚点失效 — 论文被撤回
- 2026-04-06: 初始草稿
```

**关键概念:**
- **Claim 级别的细粒度:** 每个 `[Cn]` 是独立的信任单元
- **锚点 (Anchors):** 指向外部权威来源（L3 Papers）
- **Bi-temporal:** `valid_at` / `invalid_at` 标记时间有效性
- **Block ID (`^cn`):** 允许精确引用 `[[Wiki#^c1]]`

---

### 6️⃣ **语义搜索系统**

**核心脚本:** `scripts/semantic.py`

**功能:**
- 嵌入生成（默认：BGE-M3）
- 向量存储（默认：LanceDB）
- 语义检索

**搜索范围:**
- `active` (默认): 当前知识 + 原始聚类定位卡
- `raw`, `archive`, `inbox`, `process`: 显式深度搜索
- `all`: 审计或最大化召回

**排除:**
- `cache/`, `_meta/`, `.trash/`, `_tools/`

---

### 7️⃣ **质量门控 (Quality Gates)**

**`scripts/lint.py`:**
- Wiki schema 完整性检查
- Harness 健康检查（commands.toml, agents.toml 一致性）

**`scripts/privacy_check.py`:**
- 扫描私人名称、组织、URL
- 在公共提交前运行

---

### 8️⃣ **系统协调器 (Orchestrator)**

**定义:** `protocols/orchestrator.md`

**职责:**
- 解析用户意图（通过 `harness/intents.toml`）
- 调度 Agents（le cercle）
- 管理工作流状态
- 批准写操作（`$OV/` 写入需用户确认）

---

## 🆕 计划扩展：Cognition Layer (L3.5)

现在我们要在 **L4 Wiki** 和 **L2 Working Notes** 之间，增加一个新的 **L3.5 Cognition Layer**：

---

### 新增模块：Cognition Layer

```
L4 — Wiki (现有)
     ├── Claims [C1], [C2]... (现有)
     └── TrustRank 计算 (现有)
────────────────────────────────────
L3.5 — Cognition (新增) ⭐
       $OV/cognition/
       ├── beliefs/      ← Beliefs (基于 Wiki Claims)
       ├── questions/    ← Questions (待解决问题)
       └── decisions/    ← Decisions (决策追踪)
────────────────────────────────────
L3 — Papers (现有)
```

---

### L3.5 的三个子模块

#### 1. **Beliefs（信念管理）**

**位置:** `$OV/cognition/beliefs/<id>.md`

**关系:**
- **引用 L4 Wiki Claims** — `claims: [wiki/python_asyncio.md#C1]`
- **Confidence 自动计算** — 基于引用的 Claims 的 TrustRank
- **状态机:** DRAFT → ACTIVE → QUESTIONED → REFUTED/ARCHIVED

**示例:**
```yaml
---
type: belief
statement: "Python asyncio 适合 I/O 密集型任务"
confidence: 0.85  # 自动计算
status: ACTIVE
claims:
  - source: "wiki/python_asyncio.md"
    claim_id: C1
---
```

---

#### 2. **Questions（问题管理）**

**位置:** `$OV/cognition/questions/<id>.md`

**关系:**
- **关联 Beliefs** — 哪些 Belief 依赖这个问题？
- **阻塞 Decisions** — 哪些决策在等这个问题？
- **优先级自动计算** — 用户判断 60% + 系统计算 40%

**示例:**
```yaml
---
type: question
question: "什么时候用 asyncio 而不是 threading？"
priority: high  # 自动计算
related_beliefs: [belief_001]
blocking_decisions: [decision_001]
---
```

---

#### 3. **Decisions（决策管理）**

**位置:** `$OV/cognition/decisions/<id>.md`

**关系:**
- **基于 Beliefs** — 引用支持决策的 Belief
- **解决 Questions** — 哪个 Question 触发了这个决策？
- **追踪执行结果** — 实际 vs 预期，经验教训

**示例:**
```yaml
---
type: decision
title: "使用 asyncio 实现 Web Crawler"
question_id: question_001
chosen_option: "asyncio"
status: EXECUTED
outcome:
  actual_performance: "1200 req/s"
  satisfaction: 0.9
---
```

---

### 新增 Agent: Cognition Manager

**角色:** L'Analyste（分析师）

**职责:**
- 计算 Belief Confidence（扩展 `trust.py` 逻辑）
- 计算 Question 优先级（混合算法）
- 检测 Belief Confidence 异常下降
- 生成认知健康报告

**注册位置:**
- `harness/agents.toml` — 新增 `[agents.cognition-manager]`
- `.claude/agents/cognition-manager.md` — Agent 规范

---

### 新增 Commands

| 命令 | 功能 | 调用 Agent |
|------|------|-----------|
| `/cognition` | 认知管理总入口 | Cognition Manager |
| `/belief` | Belief CRUD | Cognition Manager |
| `/question` | Question CRUD | Cognition Manager |
| `/decision` (增强) | Decision CRUD + 结果追踪 | Cognition Manager |

---

### 新增 Scripts

| 脚本 | 功能 |
|------|------|
| `scripts/cognition.py` | Confidence 计算、优先级计算、健康检查 |
| `scripts/cognition_lint.py` | Cognition Layer 结构检查 |

---

### 与现有系统的集成点

#### 1. **与 Wiki Layer (L4) 整合**

```python
# scripts/cognition.py 调用 scripts/trust.py

def calculate_belief_confidence(belief):
    claims = load_claims(belief.claim_ids)
    
    # 获取每个 Claim 的 TrustRank（来自 trust.py）
    trust_ranks = [get_trust_rank(claim.source) for claim in claims]
    
    # 计算 Confidence
    ...
```

---

#### 2. **与 Decision Command (现有) 整合**

```toml
# harness/commands.toml 修改

[commands.decision]
source = ".claude/commands/decision.md"
# 增强功能：
# - 同时写入 $OV/reflections/ (现有)
# - 同时写入 $OV/cognition/decisions/ (新增)
# - 追踪执行结果 (新增)
```

---

#### 3. **与 Daily Reflection 整合**

```markdown
<!-- /daily-reflection 输出 -->

## 今日回顾
...

## 认知健康检查 ⭐ 新增

⚠️  需要关注:
- Belief belief_003: Confidence 从 0.9 降至 0.6
- Question question_008: 已开放 14 天未解决
- Decision decision_005: 执行结果待记录
```

---

## 📊 完整架构总览

```
┌─────────────────────────────────────────────────────────────────┐
│                         Atelierr 系统                             │
│                                                                   │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │            用户界面 (User Interface)                       │   │
│  │  - Codex CLI ($command)                                   │   │
│  │  - Claude Code (/command)                                 │   │
│  │  - [可选] Web Dashboard (FastAPI + React) ⭐ 新增         │   │
│  └────────────────────┬─────────────────────────────────────┘   │
│                       │                                           │
│  ┌────────────────────▼─────────────────────────────────────┐   │
│  │            命令层 (Commands)                               │   │
│  │  harness/commands.toml                                    │   │
│  │  - /hi, /reflect, /daily-reflection                       │   │
│  │  - /read, /weekly, /review                                │   │
│  │  - /decision (现有 + 增强) ⭐                             │   │
│  │  - /cognition, /belief, /question (新增) ⭐               │   │
│  └────────────────────┬─────────────────────────────────────┘   │
│                       │                                           │
│  ┌────────────────────▼─────────────────────────────────────┐   │
│  │      系统协调器 (Orchestrator)                             │   │
│  │  protocols/orchestrator.md                                │   │
│  │  - 意图解析 (harness/intents.toml)                        │   │
│  │  - Agent 调度                                             │   │
│  │  - 写操作批准                                              │   │
│  └────────────────────┬─────────────────────────────────────┘   │
│                       │                                           │
│  ┌────────────────────▼─────────────────────────────────────┐   │
│  │      Le Cercle (15 + 1 Agents) ⭐ +1 新增                 │   │
│  │  harness/agents.toml                                      │   │
│  │  - Researcher, Scout, Reader, Scholar                     │   │
│  │  - Synthesizer, Thinker, Curator                          │   │
│  │  - Challenger, Librarian, Meeting                         │   │
│  │  - Scribe, Reviewer, Evolver, Forgetter                   │   │
│  │  - Privacy Reviewer                                       │   │
│  │  - Cognition Manager (新增) ⭐                            │   │
│  └────────────────────┬─────────────────────────────────────┘   │
│                       │                                           │
│  ┌────────────────────▼─────────────────────────────────────┐   │
│  │      核心工具层 (Core Tools)                               │   │
│  │  scripts/                                                 │   │
│  │  - trust.py (TrustRank 计算)                              │   │
│  │  - semantic.py (语义搜索)                                 │   │
│  │  - lint.py (质量检查)                                     │   │
│  │  - privacy_check.py (隐私扫描)                            │   │
│  │  - cognition.py (新增) ⭐                                 │   │
│  │  - cognition_lint.py (新增) ⭐                            │   │
│  └────────────────────┬─────────────────────────────────────┘   │
│                       │                                           │
│  ┌────────────────────▼─────────────────────────────────────┐   │
│  │      知识层 (Knowledge Layers)                             │   │
│  │  $OV/ (用户 vault)                                        │   │
│  │                                                           │   │
│  │  L5 — Foundation (保留)                                   │   │
│  │  ────────────────────────────                             │   │
│  │  L4 — Wiki ($OV/wiki/)                                    │   │
│  │       - Claims [C1], [C2]...                              │   │
│  │       - TrustRank 评分                                    │   │
│  │  ────────────────────────────                             │   │
│  │  L3.5 — Cognition ($OV/cognition/) ⭐ 新增                │   │
│  │         - beliefs/ (基于 Wiki Claims)                     │   │
│  │         - questions/ (问题管理)                           │   │
│  │         - decisions/ (决策追踪)                           │   │
│  │  ────────────────────────────                             │   │
│  │  L3 — Papers ($OV/papers/, preprints/)                    │   │
│  │  ────────────────────────────                             │   │
│  │  L2 — Working ($OV/daily-notes/, reflections/...)        │   │
│  │  ────────────────────────────                             │   │
│  │  L1 — Raw ($OV/inbox/, cache/, Readwise)                 │   │
│  └───────────────────────────────────────────────────────────┘   │
└───────────────────────────────────────────────────────────────────┘
```

---

## 📝 总结：原有 vs 新增

### 原有的 8 个核心模块

1. ✅ **知识分层模型 (L1-L5)** — 目录即认证
2. ✅ **Le Cercle (15 Agents)** — 专业任务执行
3. ✅ **命令系统 (Commands)** — 用户工作流触发
4. ✅ **信任引擎 (trust.py)** — Wiki TrustRank 计算
5. ✅ **Wiki Schema** — 结构化知识格式（Claim 级别）
6. ✅ **语义搜索 (semantic.py)** — 向量检索
7. ✅ **质量门控 (lint.py, privacy_check.py)** — 结构检查
8. ✅ **系统协调器 (Orchestrator)** — 意图路由 + Agent 调度

---

### 新增的 Cognition Layer 模块

9. ⭐ **Cognition Layer (L3.5)** — 新的知识层
   - `$OV/cognition/beliefs/`
   - `$OV/cognition/questions/`
   - `$OV/cognition/decisions/`

10. ⭐ **Cognition Manager Agent** — 第 16 个 Agent
    - Confidence 计算
    - 优先级计算
    - 健康检查

11. ⭐ **Cognition Commands** — 新命令
    - `/cognition`, `/belief`, `/question`
    - `/decision` (增强)

12. ⭐ **Cognition Scripts** — 新工具
    - `scripts/cognition.py`
    - `scripts/cognition_lint.py`

---

## 🎯 关键整合点

| 现有模块 | 与 Cognition Layer 的关系 |
|---------|--------------------------|
| Wiki Layer (L4) | Beliefs 引用 Wiki Claims，Confidence 基于 TrustRank |
| trust.py | 扩展支持 Belief Confidence 计算 |
| /decision | 增强写入 `cognition/decisions/`，追踪结果 |
| /daily-reflection | 增加认知健康检查输出 |
| lint.py | 新增 cognition_lint.py 检查 L3.5 结构 |

---

**这就是完整的架构！**

**原有 8 个模块 + 新增 4 个 Cognition 模块 = 12 个模块的完整系统**

---

**文档保存位置:** `docs/prd/architecture-overview.md`
