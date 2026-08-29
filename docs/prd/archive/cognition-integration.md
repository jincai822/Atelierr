# Cognition Management Integration — Atelierr 扩展方案

**创建日期:** 2026-08-26  
**类型:** 架构扩展  
**状态:** 设计阶段

---

## 目标

在 Atelierr 现有的反思系统中，增加**认知管理**功能，用于管理：
- **Beliefs（信念）** — 你相信的陈述，基于证据
- **Questions（问题）** — 待解决的问题，智能优先级排序
- **Decisions（决策）** — 做出的决策，追踪执行结果

形成完整的 **KNOW → THINK → ACT → LEARN** 循环。

---

## 与现有架构的关系

### 在 L1-L5 层次中的定位

```
L5 — Foundation (reserved)
────────────────────────────
L4 — Wiki (现有)                     ← Claims & Sources (现有)
     authoritative knowledge
────────────────────────────
L3.5 — Cognition Layer (新增)       ← Beliefs, Questions, Decisions (新增)
       structured thinking
────────────────────────────
L3 — Papers & Preprints (现有)
────────────────────────────
L2 — Working notes (现有)
────────────────────────────
L1 — Raw capture (现有)
```

**新增 L3.5 层：Cognition Layer**
- 位于 L4 Wiki 和 L2 Working notes 之间
- 比 L2 更结构化，但比 L4 更动态
- 目录：`$OV/cognition/`
  - `$OV/cognition/beliefs/`
  - `$OV/cognition/questions/`
  - `$OV/cognition/decisions/`

---

## 数据模型（融入现有架构）

### Belief（信念）

**文件位置:** `$OV/cognition/beliefs/<id>.md`

**Markdown 格式（符合 Atelierr 风格）:**
```yaml
---
type: belief
id: belief_20260826_001
statement: "Python asyncio 适合 I/O 密集型任务"
confidence: 0.85
status: ACTIVE
created: 2026-08-26T14:00:00Z
updated: 2026-08-26T20:00:00Z
tags: [python, asyncio, performance]

# 关联到现有 Wiki
wiki_entries:
  - [[Python Asyncio]]
  - [[Concurrency Patterns]]

# 证据来源（引用 L3 Papers 或 L4 Wiki）
claims:
  - source: "wiki/python_asyncio.md"
    claim_id: C1
  - source: "papers/fluent_python_2022.pdf"
    page: 347

# 关联的 Questions 和 Decisions
related_questions:
  - question_20260820_001
related_decisions:
  - decision_20260826_001
---

## Statement

Python asyncio 适合 I/O 密集型任务。

## 论证

基于多个来源的证据：
1. [[Python Asyncio#性能特点]] 明确指出...
2. @cite(papers/fluent_python_2022.pdf, p347) 提到...

## 反例

暂无

## 状态历史

- 2026-08-26 14:00: 创建 (DRAFT)
- 2026-08-26 15:30: 激活 (ACTIVE)
- 2026-08-26 20:00: Confidence 从 0.8 更新为 0.85
```

**状态机:**
```
DRAFT → ACTIVE → QUESTIONED → REFUTED/ARCHIVED
```

---

### Question（问题）

**文件位置:** `$OV/cognition/questions/<id>.md`

**Markdown 格式:**
```yaml
---
type: question
id: question_20260820_001
question: "什么时候应该使用 asyncio 而不是 threading？"
priority: high
importance: 0.8
urgency: 0.6
status: OPEN
created: 2026-08-20T10:00:00Z
updated: 2026-08-26T14:00:00Z
tags: [python, concurrency]

# 关联
related_beliefs:
  - belief_001
blocking_decisions:
  - decision_001
---

## 背景

在设计新的 Web 爬虫时，需要选择并发模型...

## 当前理解

- [[Belief belief_001]]: asyncio 适合 I/O 密集型
- threading 适合需要并行的场景

## 待验证

- [ ] 性能对比测试
- [ ] 生产环境案例调研
```

---

### Decision（决策）

**文件位置:** `$OV/cognition/decisions/<id>.md`

**Markdown 格式:**
```yaml
---
type: decision
id: decision_20260826_001
title: "使用 asyncio 实现 Web Crawler"
question_id: question_20260820_001
chosen_option: "asyncio"
alternatives: ["threading", "multiprocessing"]
decided_at: 2026-08-26T14:00:00Z
status: EXECUTED
executed_at: 2026-09-01T10:00:00Z
satisfaction: 0.9
tags: [python, asyncio, crawler]
---

## 决策背景

项目需要高并发 Web 爬虫，基于 [[Belief belief_001]]...

## 备选方案

### 方案 1: asyncio ✅
- 优点: 高性能，内存占用低
- 缺点: 不适合 CPU 密集型

### 方案 2: threading
- 优点: 简单，库支持好
- 缺点: GIL 限制，性能较低

### 方案 3: multiprocessing
- 优点: 真并行
- 缺点: 进程开销大

## 执行结果

- **预期性能:** 1000 req/s
- **实际性能:** 1200 req/s ✅
- **问题:** CPU 密集型任务会阻塞事件循环
- **经验教训:** 需要配合 ProcessPoolExecutor 处理 CPU 任务
```

---

## 与现有模块的集成

### 1. 与 Wiki Layer (L4) 的关系

**Beliefs 引用 Wiki Claims:**
```yaml
# Belief 文件中
claims:
  - source: "wiki/python_asyncio.md"
    claim_id: C1  # 引用 Wiki 中的 [C1] 标记
```

**Wiki 反向引用 Beliefs:**
```markdown
<!-- wiki/python_asyncio.md -->
## 性能特点 [C1]

asyncio 适合 I/O 密集型任务。

**引用此 Claim 的 Beliefs:**
- [[Belief belief_001]]
```

**trust.py 扩展:**
- 现有的 `scripts/trust.py` 计算 Wiki 的 TrustRank
- 扩展支持 Belief Confidence 计算（基于引用的 Claims 的 TrustRank）

---

### 2. 与 Daily Notes (L2) 的关系

**从 Daily Notes 提取 Questions:**
```markdown
<!-- $OV/daily-notes/2026/08/2026-08-26.md -->

今天遇到一个问题：什么时候用 asyncio 而不是 threading？
需要研究一下。
```

**通过命令提取:**
```bash
# 用户: /hi extract question from today's note
# 系统识别出问题，建议创建 Question
```

---

### 3. 与 Decision Command (现有) 的关系

**现有的 `/decision` 命令:**
- 当前：生成结构化决策日志到 `$OV/reflections/` 或 `$OV/research/`
- 增强：同时创建 `$OV/cognition/decisions/<id>.md`
- 增强：追踪执行结果

---

### 4. 与 Reflection System 的关系

**Daily Reflection 增强:**
```yaml
# /daily-reflection 输出中增加

## 认知健康检查

⚠️  需要关注:
- Belief belief_003: Confidence 从 0.9 降至 0.6
- Question question_008: 已开放 14 天未解决
- Decision decision_005: 执行结果待记录
```

---

## 新增命令（Commands）

### /cognition

**描述:** 认知管理总入口（类似 `/hi` 的路由器）

**子命令:**
```bash
# Belief 管理
/cognition belief create "statement" --claims claim_001,claim_002
/cognition belief list --status ACTIVE
/cognition belief update belief_001 --confidence 0.9

# Question 管理
/cognition question create "question text" --importance 0.8
/cognition question list --priority high
/cognition question resolve question_001

# Decision 管理
/cognition decision create --question question_001 --option asyncio
/cognition decision record-outcome decision_001 --satisfaction 0.9

# 健康检查
/cognition health check
```

---

### /belief, /question, /decision

**描述:** 独立的快捷命令（类似现有的 `/reflect`, `/read`）

**注册到 `harness/commands.toml`:**
```toml
[commands.belief]
source = ".claude/commands/belief.md"
category = "cognition"
status = "portable-adapted"
description = "Belief management — create, update, track confidence."
codex_prompt = "Execute the $belief skill..."

[commands.question]
source = ".claude/commands/question.md"
category = "cognition"
status = "portable-adapted"
description = "Question management — track, prioritize, resolve."
codex_prompt = "Execute the $question skill..."

[commands.decision]
source = ".claude/commands/decision.md"
category = "cognition"
status = "portable-adapted"
description = "Decision management — record choices, track outcomes."
codex_prompt = "Execute the $decision skill..."
```

---

## 新增 Agents（Le Cercle 扩展）

### Cognition Manager

**角色:** Le Analyste（分析师）

**描述:** 管理 Beliefs、Questions、Decisions 的结构化数据

**职责:**
- 计算 Belief Confidence（基于 Wiki Claims 的 TrustRank）
- 计算 Question 优先级（混合用户判断 + 系统计算）
- 追踪 Decision 执行结果
- 检测 Belief Confidence 异常下降

**注册到 `harness/agents.toml`:**
```toml
[agents.cognition-manager]
source = ".claude/agents/cognition-manager.md"
voices = { native = "opus" }
kinds = ["app"]
dispatch_rationale = ["context-isolation", "tool-isolation"]
status = "portable-adapted"
description = "Manages structured cognition: Beliefs, Questions, Decisions. Le cercle archetype: L'Analyste."
pattern = "orchestrator-subagent"
used_by = ["commands.cognition", "commands.belief", "commands.question", "commands.decision"]
```

---

## 新增 Scripts（Python 工具）

### scripts/cognition.py

**功能:**
```python
# Confidence 计算
def calculate_confidence(belief: Belief) -> float:
    """基于 Wiki Claims 的 TrustRank 计算置信度"""
    claims = load_claims(belief.claim_ids)
    trust_ranks = [get_trust_rank(c.source) for c in claims]
    
    # 按来源分组，取最高
    sources = group_by_source(claims)
    source_trusts = [max(ranks) for src, ranks in sources.items()]
    
    # 基础置信度 + 多样性加成
    base = sum(source_trusts) / len(source_trusts)
    diversity_bonus = min(len(sources) * 0.05, 0.2)
    
    return min(base + diversity_bonus, 1.0)

# Question 优先级
def calculate_priority(question: Question) -> float:
    """混合计算（用户 60% + 系统 40%）"""
    user_score = question.importance * 0.6 + question.urgency * 0.4
    
    system_score = (
        count_dependent_beliefs(question) * 0.4 +
        count_blocking_decisions(question) * 0.5 +
        age_factor(question) * 0.1
    )
    
    return user_score * 0.6 + system_score * 0.4

# 健康检查
def health_check() -> HealthReport:
    """检测异常"""
    issues = []
    
    # Confidence 显著下降
    for belief in load_beliefs():
        if belief.confidence_dropped_by > 0.2:
            issues.append({
                'type': 'belief',
                'id': belief.id,
                'message': f"Confidence 从 {belief.old_confidence} 降至 {belief.confidence}"
            })
    
    # 长期未解决的 Questions
    for question in load_questions(status='OPEN'):
        if question.open_days > 30:
            issues.append({
                'type': 'question',
                'id': question.id,
                'message': f"已开放 {question.open_days} 天"
            })
    
    return HealthReport(issues)
```

**CLI:**
```bash
# 计算 Belief Confidence
uv run scripts/cognition.py belief recalc belief_001

# 计算 Question 优先级
uv run scripts/cognition.py question priority question_001

# 健康检查
uv run scripts/cognition.py health check

# 生成每日报告
uv run scripts/cognition.py daily-report
```

---

### scripts/cognition_lint.py

**功能:** 检查 Cognition Layer 的结构完整性

```bash
# 检查所有 Belief 文件格式
uv run scripts/cognition_lint.py --layer beliefs

# 检查 Claims 引用有效性
uv run scripts/cognition_lint.py --check-claims

# 检查关联完整性（Beliefs ↔ Questions ↔ Decisions）
uv run scripts/cognition_lint.py --check-links
```

---

## 工作流示例

### 场景 1：从 Wiki 创建 Belief

```bash
# 1. 用户阅读 Wiki 条目
User: /read wiki/python_asyncio.md

# 2. 系统识别出可以形成 Belief 的 Claims
System: 发现 2 个 Claims 可以形成 Belief:
  - [C1]: asyncio 适合 I/O 密集型
  - [C2]: asyncio 不适合 CPU 密集型

  建议创建 Belief？[y/N]

# 3. 用户确认
User: y

# 4. 系统创建 Belief
System: ✅ 创建 Belief belief_001
  Statement: "Python asyncio 适合 I/O 密集型任务"
  Confidence: 0.85 (基于 2 个独立来源)
  文件: $OV/cognition/beliefs/belief_001.md
```

---

### 场景 2：Decision 追踪执行结果

```bash
# 1. 创建 Decision
User: /decision "使用 asyncio 实现爬虫"

System: 基于 [[Belief belief_001]]，建议选择 asyncio
  是否记录为 Decision？[y/N]

User: y

System: ✅ 创建 Decision decision_001
  文件: $OV/cognition/decisions/decision_001.md

# 2. 几周后，记录执行结果
User: /cognition decision record-outcome decision_001

System: 请提供执行结果

User: 
实际性能 1200 req/s，超出预期。
但 CPU 任务会阻塞。

System: ✅ 已更新 Decision decision_001
  Satisfaction: 0.9
  Lessons: 需要配合 ProcessPoolExecutor
```

---

### 场景 3：Daily Reflection 整合认知健康

```bash
User: /daily-reflection

System: 
## 今日回顾
...

## 认知健康检查

⚠️  需要关注:
1. Belief belief_003: "MySQL 比 PostgreSQL 快"
   Confidence: 0.9 → 0.6 (-33%)
   原因: 新增反例 wiki/database_benchmarks.md#[C7]
   
   建议: 标记为 QUESTIONED
   [1] 标记为 QUESTIONED
   [2] 查看详情
   [3] 跳过
   
User: 1

System: ✅ Belief belief_003 已标记为 QUESTIONED
```

---

## 实施计划

### Phase 1: 核心数据结构（1-2 周）

- [ ] 创建 `$OV/cognition/` 目录结构
- [ ] 定义 Belief/Question/Decision Markdown 模板
- [ ] 实现 `scripts/cognition.py` 基础功能
  - Belief Confidence 计算
  - Question 优先级计算
- [ ] 单元测试

---

### Phase 2: 命令层（1-2 周）

- [ ] 实现 `/cognition` 命令
- [ ] 实现 `/belief`, `/question`, `/decision` 快捷命令
- [ ] 注册到 `harness/commands.toml`
- [ ] 创建 `.claude/commands/*.md` 规范文档

---

### Phase 3: Agent 集成（1 周）

- [ ] 创建 Cognition Manager agent
- [ ] 注册到 `harness/agents.toml`
- [ ] 创建 `.claude/agents/cognition-manager.md`
- [ ] 集成到现有工作流

---

### Phase 4: 与现有系统集成（1-2 周）

- [ ] 扩展 `scripts/trust.py` 支持 Belief Confidence 计算
- [ ] `/daily-reflection` 增加认知健康检查
- [ ] `/decision` 命令集成 Cognition Layer
- [ ] `scripts/cognition_lint.py` 质量检查

---

### Phase 5: 可选增强（V1）

- [ ] Web Dashboard（可选，如你有 VPS 需求）
- [ ] 知识图谱可视化（Beliefs ↔ Claims ↔ Wiki）
- [ ] 自动从 Daily Notes 提取 Questions
- [ ] 定期健康检查（每周报告）

---

## 与你的 Web Dashboard 需求整合

如果你想要 Web UI，可以：

1. **保留 Markdown 为源真相**（符合 Atelierr local-first 原则）
2. **增加 Web Dashboard 作为可选视图**
   - FastAPI 后端读取 `$OV/cognition/` Markdown 文件
   - React 前端显示
   - 通过 Tailscale 内网访问

**架构:**
```
$OV/cognition/  (Markdown 源真相)
      ↕
scripts/cognition.py (Python CLI 工具)
      ↕
FastAPI Backend (可选，Web API)
      ↕
React Frontend (可选，Web UI)
```

---

## 总结

这个方案：

✅ **完全融入 Atelierr 现有架构** — 不是独立项目  
✅ **遵循 local-first 原则** — Markdown 为源真相  
✅ **利用现有基础设施** — trust.py, lint.py, Wiki schema  
✅ **扩展现有命令** — /decision, /daily-reflection  
✅ **新增专门的 Cognition Layer (L3.5)** — 结构化认知管理  
✅ **保留灵活性** — 可选 Web Dashboard（如果需要）

---

**下一步：你希望从哪个 Phase 开始？**
1. Phase 1（核心数据结构）— 最基础
2. Phase 2（命令层）— 快速可用
3. 或者，你想先看到具体的某个文件示例？

---

**创建时间:** 2026-08-26 21:30  
**文档路径:** `docs/prd/cognition-integration.md`
