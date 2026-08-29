# 架构设计（基于深入理解 Atelierr）

**版本:** v2.0  
**日期:** 2026-08-27  
**状态:** 基于完整项目理解的最终架构  
**核心原则:** 最小改动 + 完全解耦 + 复用现有能力

---

## 🎯 核心理解

### 你的真实需求

1. **保留 Atelierr 完整能力** — 15 个 Agent、21 个命令、57 个脚本全部保留
2. **新增 Cognition Layer** — Beliefs、Questions、Decisions 管理
3. **最小改动** — 改动比例 < 10%
4. **完全解耦** — 删除新增部分后，Atelierr 100% 恢复
5. **与 llm_wiki 集成** — 零侵入集成，通过软链接

### Atelierr 真实架构（我刚读完）

```
Atelierr 核心组件（全部保留）：

1. 知识层次（L1-L5）
   - L5: Foundation (reserved)
   - L4: Wiki ($OV/wiki/) — TrustRank scored
   - L3: Papers ($OV/papers/, preprints/)
   - L2: Working notes (daily-notes/, reflections/, research/)
   - L1: Raw capture (inbox/, cache/, Readwise)

2. 15 个 AI 智能体（Le Cercle）
   - Researcher (Observer) — 搜索笔记
   - Synthesizer (Colorist) — 综合洞察
   - Challenger (Critic) — 挑战假设
   - Curator (Collector) — 整理笔记
   - Librarian (Cataloguer) — 推荐阅读
   - Scout (Flâneur) — 外部搜索
   - Reader — 深度阅读（4 个镜头）
   - Scholar — 学术阅读（深度认知）
   - Thinker (Structuralist) — 结构化思考
   - Scribe (Typewriter) — 记录捕获
   - Evolver (Master) — 系统进化
   - Reviewer (Arbiter) — 质量审查
   - Privacy Reviewer (Steward) — 隐私审查
   - Forgetter (Conservator) — 主动遗忘
   - Meeting (Stenographer) — 会议处理

3. 21 个命令（通过 /hi 路由）
   - /hi — 意图路由器（17 种意图）
   - /daily-reflection — 每日反思
   - /weekly — 周度回顾
   - /read — 深度阅读
   - /decision — 决策日志
   - /energy-audit — 能量审计
   - /explore — 探索连接
   - /review — 目标回顾
   - /curate — 收件箱整理
   - /sync — 移动捕获同步
   - /promote — 提升到 Wiki
   - /lint — 结构检查
   - /introspect — 构建 profile
   - /prm — 人际关系管理
   - /civ — 生活仪表板
   - /dine — 餐厅推荐
   - /system-review — 系统审查
   - /autoevo-nightly — 自动进化（bot-only）
   - /autoevo-review — 进化审查
   - /run-routine — 例行任务（bot-only）
   - /reflect — /hi 的别名

4. 核心引擎
   - scripts/trust.py (953 行) — TrustRank 引擎
   - scripts/semantic.py (1,555 行) — 语义搜索（LanceDB + BGE-M3）
   - scripts/lint.py (629 行) — 结构检查
   - scripts/context_bundle.py (1,482 行) — 上下文加载
   - scripts/cues.py (1,957 行) — 健康检查

5. 协议文档（40 个）
   - protocols/wiki-schema.md — Wiki Schema 定义
   - protocols/local-first-architecture.md — L1-L5 模型
   - protocols/epistemic-hygiene.md — 认识论卫生
   - protocols/hi-menu.md — 意图路由
   - 其他 36 个协议
```

---

## 📐 架构设计（基于真实理解）

### 1. 整体架构图

```
┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓
┃          Personal Intelligence System (完整系统)            ┃
┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┛
                            │
        ┌───────────────────┼───────────────────┐
        │                   │                   │
        ↓                   ↓                   ↓
        
┌─────────────────┐  ┌─────────────────┐  ┌─────────────────┐
│ nashsu/llm_wiki │  │   Atelierr      │  │  Cognition      │
│   (外部独立)     │  │   (95% 保留)    │  │  Layer (5% 新增)│
└─────────────────┘  └─────────────────┘  └─────────────────┘
        │                   │                   │
        │                   │                   │
        └───────────────────┴───────────────────┘
                            │
                            ↓
                    $OV/ (Local Markdown)
                    
关键特性：
✅ llm_wiki 独立运行（不感知 Atelierr）
✅ Atelierr 不感知 Cognition Layer
✅ Cognition Layer 只读访问 Atelierr
✅ 所有数据存储在 $OV/ (Local-first)
```

### 2. Cognition Layer 定位（L3.5 层）

```
L5 — Foundation (reserved)
     ↑
L4 — Wiki ($OV/wiki/)           ← Atelierr 核心，不变
     • TrustRank scored
     • Claims with [C1], [C2]
     ↑
     │ 引用 Claims
     │
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
L3.5 — Cognition ($OV/cognition/)  ← 新增层，可解耦
     • Beliefs (基于 Wiki Claims)
     • Questions (待解决问题)
     • Decisions (决策追踪)
     • Confidence 自动计算
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
     ↑
L3 — Papers ($OV/papers/)       ← Atelierr 核心，不变
     ↑
L2 — Working notes              ← Atelierr 核心，不变
     ↑
L1 — Raw capture                ← Atelierr 核心，不变
```

**为什么是 L3.5？**
- 比 L4 更动态（Confidence 会变化）
- 比 L3 更结构化（不是原始论文）
- 比 L2 更可靠（经过验证的认知）

---

## 🔧 新增内容（Cognition Layer）

### 1. 新增 1 个 Agent（第 16 个）

```
Cognition Manager（Le Analyste）

职责：
  • 计算 Belief Confidence（基于 TrustRank）
  • 计算 Question Priority（用户输入 + 系统计算）
  • 追踪 Decision 执行结果
  • 检测认知健康异常

输入：
  • Beliefs/Questions/Decisions Markdown 文件
  • Wiki Claims（通过 trust.py）
  • TrustRank 分数

输出：
  • 更新后的 Confidence
  • 计算后的 Priority
  • 认知健康报告

Le Cercle 原型：
  The Analyst (Cassatt) — 分析认知结构的数据收集者
```

### 2. 新增 2 个命令

```
/belief
  • 创建/查询 Beliefs
  • 自动计算 Confidence
  • 引用 Wiki Claims
  • 追踪 Belief 状态变化

/question  
  • 创建/查询 Questions
  • 自动计算 Priority
  • 关联 Beliefs 和 Decisions
  • 追踪问题解决状态
```

### 3. 增强 2 个现有命令

```
/decision（增强）
  • 集成 Cognition Layer
  • 自动关联 Beliefs
  • 追踪执行结果
  • 计算 Satisfaction

/daily-reflection（增强）
  • 增加认知健康检查
  • 检测 Belief Confidence 异常变化
  • 提醒高优先级 Questions
  • 建议待处理 Decisions
```

### 4. 新增 3 个脚本

```python
scripts/belief.py (~400 行)
  • Belief CRUD 操作
  • Confidence 计算（基于 TrustRank）
  • 状态机管理（DRAFT → ACTIVE → QUESTIONED → REFUTED）
  • SQLite 索引同步

scripts/question.py (~300 行)
  • Question CRUD 操作
  • Priority 计算（用户输入 60% + 系统计算 40%）
  • 关联 Beliefs 和 Decisions
  • SQLite 索引同步

scripts/cognition.py (~400 行)
  • 健康检查（Confidence 异常、Priority 突变）
  • 批量操作（批量更新、导出）
  • 统计报告
```

### 5. 数据存储

```
$OV/cognition/                    ← 新增目录
├── beliefs/
│   ├── belief_20260827_001.md
│   └── belief_20260827_002.md
├── questions/
│   └── question_20260820_001.md
└── decisions/
    └── decision_20260827_001.md

$OV/.index/cognition.db           ← SQLite 索引（新增）
```

---

## 🔌 接口设计（单向依赖）

### 接口 1: Cognition → Trust Engine

```python
# Cognition Layer 读取 TrustRank
from scripts.trust import TrustRank

trust_engine = TrustRank()
claim_trust = trust_engine.get_claim_trust(
    wiki_file="wiki/python_asyncio.md",
    claim_id="C1"
)
# 返回: 0.92

契约：
✅ trust.py 不感知 Cognition Layer
✅ Cognition 只读取，不修改
✅ Claim 不存在时返回 0.0
```

### 接口 2: Cognition → Semantic Search

```python
# Cognition Layer 使用语义搜索
from scripts.semantic import SemanticSearch

search = SemanticSearch()
results = search.query(
    query="asyncio performance",
    top_k=5,
    filter_paths=["cognition/beliefs/"]
)
# 返回: [(belief_001.md, 0.92), ...]

契约：
✅ semantic.py 不感知 Cognition Layer
✅ Cognition Markdown 自动被索引
✅ 通过 filter_paths 参数过滤
```

### 接口 3: Cognition → Wiki Schema

```yaml
# Belief 引用 Wiki Claim
claims:
  - source: "wiki/python_asyncio.md"
    claim_id: C1
    trust_rank: 0.92

契约：
✅ Cognition 引用 Wiki Claims，不修改 Wiki
✅ Wiki Schema 保持不变
✅ 单向引用：Cognition → Wiki
```

---

## 📊 改动统计

### 保留的内容（95%）

| 类型 | 数量 | 状态 |
|------|------|------|
| **AI 智能体** | 15 个 | ✅ 完整保留 |
| **命令** | 21 个 | ✅ 19 个不变，2 个微调 |
| **脚本** | 57 个 | ✅ 完整保留 |
| **协议** | 40 个 | ✅ 39 个不变，1 个微调 |
| **L1-L5 分层** | 5 层 | ✅ 完整保留 |
| **TrustRank 引擎** | 953 行 | ✅ 完整保留 |
| **语义搜索** | 1,555 行 | ✅ 完整保留 |
| **意图路由** | 17 种意图 | ✅ 完整保留 |

### 新增内容（5%）

| 类型 | 数量 | 代码量 |
|------|------|--------|
| **AI 智能体** | 1 个 (Cognition Manager) | ~100 行 |
| **命令** | 2 个 (/belief, /question) | ~200 行 |
| **微调命令** | 2 个 (/decision, /daily-reflection) | ~100 行 |
| **脚本** | 3 个 | ~1,100 行 |
| **数据目录** | 1 个 ($OV/cognition/) | — |
| **SQLite 索引** | 1 个 (cognition.db) | — |
| **总计** | — | **~1,500 行** |

### 改动比例

```
总代码量: ~21,500 行
  • Atelierr 核心: ~20,000 行 (93%)
  • 新增代码: ~1,500 行 (7%)
  • 微调代码: ~100 行 (0.5%)

改动比例: 7.5%
```

---

## 🗂️ 文件结构

### Atelierr 仓库（保持不变）

```
Atelierr/
├── CLAUDE.md                     ✅ 不变
├── AGENTS.md                     ✅ 不变
├── .claude/
│   ├── agents/
│   │   ├── researcher.md         ✅ 保留 15 个
│   │   ├── ...
│   │   └── cognition-manager.md  🆕 第 16 个
│   ├── commands/
│   │   ├── hi.md                 ✅ 不变
│   │   ├── daily-reflection.md   🔧 微调
│   │   ├── decision.md           🔧 微调
│   │   ├── belief.md             🆕 新增
│   │   ├── question.md           🆕 新增
│   │   └── ... (其他 16 个)      ✅ 不变
│   └── skills/                   ✅ 不变
│
├── scripts/
│   ├── trust.py                  ✅ 不变
│   ├── semantic.py               ✅ 不变
│   ├── lint.py                   ✅ 不变
│   ├── belief.py                 🆕 新增
│   ├── question.py               🆕 新增
│   ├── cognition.py              🆕 新增
│   └── ... (其他 54 个)          ✅ 不变
│
├── protocols/
│   ├── wiki-schema.md            ✅ 不变
│   ├── local-first-architecture.md  🔧 微调（增加 L3.5 说明）
│   └── ... (其他 38 个)          ✅ 不变
│
└── harness/
    ├── agents.toml               🔧 微调（新增 cognition-manager）
    ├── commands.toml             🔧 微调（新增 belief/question）
    └── ... (其他 8 个)           ✅ 不变
```

### $OV/ 数据目录

```
$OV/
├── wiki/                         ✅ Atelierr L4（不变）
├── papers/                       ✅ Atelierr L3（不变）
├── daily-notes/                  ✅ Atelierr L2（不变）
├── reflections/                  ✅ Atelierr L2（不变）
├── cognition/                    🆕 L3.5（新增）
│   ├── beliefs/
│   ├── questions/
│   └── decisions/
└── .index/
    └── cognition.db              🆕 SQLite 索引（新增）
```

---

## 🔗 与 llm_wiki 集成（零侵入）

### 集成方案

```
llm_wiki (外部独立运行)
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

### 操作步骤

```bash
# 1. llm_wiki 生成 wiki 文件
cd /path/to/llm_wiki
python -m llm_wiki.cli build

# 2. 创建软链接
ln -s /path/to/llm_wiki/output/wiki $OV/wiki

# 3. Atelierr 正常运行
cd /srv/workspaces/Atelierr
uv run scripts/trust.py

# 4. Cognition Layer 自动工作
uv run scripts/belief.py --list
```

**关键点：**
- ✅ llm_wiki 不知道 Atelierr 的存在
- ✅ Atelierr 不知道 llm_wiki 的存在
- ✅ Cognition Layer 不知道 llm_wiki 的存在
- ✅ 通过文件系统自然集成

---

## ✅ 解耦验证

### 删除 Cognition Layer 的步骤

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

### 验证 Atelierr 完整性

```bash
# 验证 TrustRank
uv run scripts/trust.py --check

# 验证语义搜索
uv run scripts/semantic.py --test

# 验证 Lint
uv run scripts/lint.py

# 验证 Harness
python3 scripts/harness_lint.py
python3 scripts/harness_smoke.py

# 预期结果：所有测试通过 ✅
```

---

## 🎯 总结

### 核心原则达成

| 原则 | 实现方式 | 状态 |
|------|----------|------|
| **最小改动** | 只改动 7.5% 代码 | ✅ |
| **完全解耦** | 5 步删除，100% 恢复 | ✅ |
| **单向依赖** | Cognition → Atelierr | ✅ |
| **Local-first** | 所有数据在 $OV/ | ✅ |
| **复用优先** | 复用 TrustRank、语义搜索、Wiki Schema | ✅ |

### 关键指标

```
┌──────────────────────────────────────────┐
│           关键指标汇总                    │
├──────────────────────────────────────────┤
│  Atelierr 保留      95%                  │
│  新增代码量         1,500 行             │
│  改动比例           7.5%                 │
│  新增文件           6 个                 │
│  微调文件           5 个                 │
│  解耦步骤           5 步                 │
│  恢复完整性         100%                 │
└──────────────────────────────────────────┘
```

---

**创建时间:** 2026-08-27  
**文档版本:** v2.0（基于完整项目理解）  
**改动比例:** 7.5%  
**解耦性:** 100%
