# 需求明确 — 少部分功能改制方案

**日期:** 2026-08-27  
**状态:** 方案确定  
**核心原则:** 少部分功能改制（最小改动）

---

## 🎯 最终明确的需求

基于你的回答：**"少部分功能改制"**

### 核心理解

你想要的是：
- ✅ **保留 Atelierr 大部分能力**
- ✅ **只改制少部分功能**（新增 Cognition Layer）
- ✅ **最小改动**
- ✅ **可解耦**（如果不需要，可以删除新增部分）

---

## 📊 Atelierr 能力清单与改制方案

### 保留的能力（不改动）

**知识管理核心：**
- ✅ L1-L5 知识分层架构
- ✅ TrustRank 引擎（`scripts/trust.py`）
- ✅ Wiki Schema（`protocols/wiki-schema.md`）
- ✅ 语义搜索（`scripts/semantic.py`）
- ✅ Lint 检查（`scripts/lint.py`）
- ✅ Privacy 检查（`scripts/privacy_check.py`）

**15 个 AI 智能体（完整保留）：**
- ✅ Researcher（Observer）— 搜索笔记
- ✅ Synthesizer（Colorist）— 综合洞察
- ✅ Challenger（Critic）— 挑战假设
- ✅ Curator（Collector）— 整理笔记
- ✅ Librarian（Cataloguer）— 推荐阅读
- ✅ Scout（Flâneur）— 外部搜索
- ✅ Reader — 深度阅读
- ✅ Scholar — 学术阅读
- ✅ Thinker — 独立思考
- ✅ Scribe（Typewriter）— 记录捕获
- ✅ Evolver（Master）— 系统进化
- ✅ Reviewer（Arbiter）— 质量审查
- ✅ Privacy Reviewer（Steward）— 隐私审查
- ✅ Forgetter（Conservator）— 主动遗忘
- ✅ Meeting Processor（Stenographer）— 会议记录

**反思工作流（完整保留）：**
- ✅ `/hi` — 会话菜单
- ✅ `/daily-reflection` — 每日反思
- ✅ `/weekly` — 周度回顾
- ✅ `/decision` — 决策日志
- ✅ `/energy-audit` — 能量审计
- ✅ `/explore` — 探索连接
- ✅ `/read` — 深度阅读
- ✅ `/curate` — 整理收件箱
- ✅ `/promote` — 提升到 Wiki
- ✅ `/lint` — 质量检查
- ✅ `/system-review` — 系统审查

**工具脚本（完整保留）：**
- ✅ `scripts/context_bundle.py` — 上下文加载
- ✅ `scripts/cues.py` — 健康检查
- ✅ `scripts/autoevo_*.py` — 自动进化
- ✅ `scripts/dining_audit.py` — 饮食审计
- ✅ 其他 30+ 脚本

---

### 改制部分（新增 L3.5 Cognition Layer）

**只改制这些功能：**

**1. 新增 Cognition Layer（L3.5 层）**

```
Atelierr 层次（保持不变）
├── L5 — Foundation (reserved)
├── L4 — Wiki (不变)
├── L3.5 — Cognition (新增) ← 只加这一层
│   ├── Beliefs
│   ├── Questions
│   └── Decisions
├── L3 — Papers (不变)
├── L2 — Working notes (不变)
└── L1 — Raw capture (不变)
```

**2. 新增 3 个命令**

```bash
/belief    # Belief 管理
/question  # Question 追踪
/decision  # Decision 追踪（增强现有的 /decision）
```

**3. 新增 1 个 Agent**

```
Cognition Manager（Le Analyste）
- 管理 Beliefs/Questions/Decisions
- 计算 Confidence（基于 TrustRank）
```

**4. 新增 3 个脚本**

```
scripts/belief.py        # Belief 管理
scripts/question.py      # Question 追踪
scripts/cognition.py     # Confidence 计算
```

**5. 增强 2 个现有命令**

```
/daily-reflection  # 增加认知健康检查
/decision          # 集成 Cognition Layer
```

---

## 🏗️ 最终架构（最小改动方案）

### 文件结构

```
Atelierr/                          (现有仓库，保持不变)
├── CLAUDE.md                       (不变)
├── AGENTS.md                       (不变)
├── .claude/
│   ├── agents/                     (保留 15 个智能体)
│   │   ├── researcher.md           (不变)
│   │   ├── synthesizer.md          (不变)
│   │   ├── ...                     (不变)
│   │   └── cognition-manager.md    (新增) ← 第 16 个智能体
│   ├── commands/                   (保留所有命令)
│   │   ├── hi.md                   (不变)
│   │   ├── daily-reflection.md     (微调 — 增加认知健康检查)
│   │   ├── decision.md             (微调 — 集成 Cognition Layer)
│   │   ├── belief.md               (新增) ← 新命令
│   │   ├── question.md             (新增) ← 新命令
│   │   └── ...                     (其他不变)
│   └── skills/                     (不变)
│
├── scripts/                        (保留所有脚本)
│   ├── trust.py                    (不变)
│   ├── semantic.py                 (不变)
│   ├── lint.py                     (不变)
│   ├── belief.py                   (新增) ← 新脚本
│   ├── question.py                 (新增) ← 新脚本
│   ├── cognition.py                (新增) ← 新脚本
│   └── ...                         (其他 30+ 脚本不变)
│
├── protocols/                      (保留所有协议)
│   ├── local-first-architecture.md (微调 — 增加 L3.5 说明)
│   ├── wiki-schema.md              (不变)
│   └── ...                         (其他不变)
│
├── harness/
│   ├── agents.toml                 (微调 — 新增 cognition-manager)
│   ├── commands.toml               (微调 — 新增 belief/question 命令)
│   └── ...                         (其他不变)
│
└── frameworks/                     (不变)

$OV/                               (数据目录)
├── wiki/                           (不变)
├── papers/                         (不变)
├── daily-notes/                    (不变)
├── reflections/                    (不变)
├── cognition/                      (新增) ← 只加这个目录
│   ├── beliefs/
│   ├── questions/
│   └── decisions/
└── .index/                         (新增 — SQLite 索引)
    └── cognition.db
```

---

## 📏 改动量评估

### 统计

| 类型 | 保留（不变） | 新增 | 微调 |
|------|------------|------|------|
| **AI 智能体** | 15 个 | 1 个 | 0 个 |
| **命令** | 13 个 | 2 个 | 2 个 |
| **脚本** | 30+ 个 | 3 个 | 0 个 |
| **协议** | 10+ 个 | 0 个 | 1 个 |
| **数据目录** | 8 个 | 1 个 | 0 个 |

**改动比例：**
- 保留：~95%
- 新增：~5%

**代码量评估：**
- 现有代码：~20,000 行
- 新增代码：~1,500 行（3 个脚本 + 1 个 Agent + 2 个命令）
- 改动比例：7.5%

---

## ✅ 可解耦性验证

### 如果你不需要 Cognition Layer，删除这些即可：

```bash
# 删除数据
rm -rf $OV/cognition/
rm -rf $OV/.index/cognition.db

# 删除脚本
rm scripts/belief.py
rm scripts/question.py
rm scripts/cognition.py

# 删除命令
rm .claude/commands/belief.md
rm .claude/commands/question.md

# 删除 Agent
rm .claude/agents/cognition-manager.md

# 回退微调（git revert）
git revert <commit-hash>  # /daily-reflection 的微调
git revert <commit-hash>  # /decision 的微调
```

**结果：** Atelierr 恢复到原始状态，完全不受影响。

---

## 🔄 与 nashsu/llm_wiki 的集成（不影响 Atelierr）

**集成方式：**

```
llm_wiki (外部软件，独立运行)
    ↓
  wiki/ 目录（Markdown 文件）
    ↓
  软链接 → $OV/wiki/
    ↓
Atelierr 的 TrustRank（正常运行）
    ↓
Cognition Layer（使用 TrustRank 结果）
```

**关键点：**
- ✅ llm_wiki 独立运行，不影响 Atelierr
- ✅ 通过软链接集成，零侵入
- ✅ Atelierr 的 TrustRank 正常工作
- ✅ Cognition Layer 使用 TrustRank 结果

---

## 🚀 实施计划（4 个阶段）

### 阶段 1: 数据层（1 周）

**目标：** 定义 Cognition Layer 数据格式

**任务：**
1. ✅ 创建 `$OV/cognition/` 目录结构
2. ✅ 定义 Belief/Question/Decision Markdown 模板
3. ✅ 定义 SQLite 索引 Schema

**验收：**
- ✅ 可以手动创建 Belief Markdown 文件
- ✅ SQLite 索引可以查询

**代码量：** ~200 行（SQL Schema + Markdown 模板）

---

### 阶段 2: 脚本层（1 周）

**目标：** 实现核心脚本

**任务：**
1. ✅ 实现 `scripts/belief.py` — CRUD 操作
2. ✅ 实现 `scripts/question.py` — CRUD 操作
3. ✅ 实现 `scripts/cognition.py` — Confidence 计算

**验收：**
- ✅ CLI 可以创建/查询 Beliefs
- ✅ Confidence 自动计算（基于 TrustRank）

**代码量：** ~800 行（3 个脚本）

---

### 阶段 3: 命令层（1 周）

**目标：** 实现用户命令

**任务：**
1. ✅ 创建 `/belief` 命令
2. ✅ 创建 `/question` 命令
3. ✅ 增强 `/decision` 命令（集成 Cognition Layer）
4. ✅ 增强 `/daily-reflection`（增加认知健康检查）

**验收：**
- ✅ 可以通过 `/belief create` 创建信念
- ✅ `/daily-reflection` 输出认知健康报告

**代码量：** ~400 行（2 个新命令 + 2 个微调）

---

### 阶段 4: Agent 层（3 天）

**目标：** 创建 Cognition Manager Agent

**任务：**
1. ✅ 创建 `.claude/agents/cognition-manager.md`
2. ✅ 注册到 `harness/agents.toml`
3. ✅ 集成到命令

**验收：**
- ✅ Cognition Manager 可以自动计算 Confidence
- ✅ 可以检测 Belief 异常变化

**代码量：** ~100 行（Agent 定义）

---

## 📊 总结

### 最小改动原则

| 维度 | 改动量 |
|------|--------|
| **文件数** | 保留 50+ 文件，新增 6 个文件，微调 4 个文件 |
| **代码量** | 保留 20,000 行，新增 1,500 行（7.5%） |
| **目录** | 保留 8 个目录，新增 1 个目录（$OV/cognition/） |
| **命令** | 保留 13 个命令，新增 2 个命令，微调 2 个命令 |
| **Agent** | 保留 15 个 Agent，新增 1 个 Agent |

### 改动比例：~5-7%

---

## ✅ 可解耦性保证

**删除新增部分的步骤：**
1. 删除 `$OV/cognition/` 目录
2. 删除 3 个脚本
3. 删除 2 个命令
4. 删除 1 个 Agent
5. 回退 2 个微调

**结果：** Atelierr 100% 恢复原状

---

## 🎯 下一步行动

### 剩余 2 个问题

**Q1: llm_wiki 的 wiki 文件在哪个目录？**
- 请提供完整路径（如 `/home/user/llm_wiki/projects/kb/wiki/`）

**Q2: 你接受这个"少部分功能改制"方案吗？**
- **选项 A:** 接受，开始实施阶段 1
- **选项 B:** 需要调整（请说明）

---

**一旦你回答，我立即开始实施阶段 1！** 🚀

---

**创建时间:** 2026-08-27 12:57  
**改动比例:** 5-7%（最小改动）  
**预计完成时间:** 3 周  
**验收标准:** 可解耦，删除后 Atelierr 100% 恢复
