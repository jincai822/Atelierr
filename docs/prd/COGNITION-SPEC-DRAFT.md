# Atelierr 认知模块规格草案

**版本**: v0.1-draft

**状态**: 🟡 待裁决，不构成锁定契约

**日期**: 2026-08-29

**目标实现**: Phase 5，`scripts/memory/cognition.py`（候选路径，见 D12）

**裁决后去向**: 可整理为架构规范增补，并在另一次变更中补充验收标准

---

## 📋 文档说明

本文档为 Atelierr Phase 5 认知模块提供一份**可锁定的候选规格**。它不修改、
不覆盖以下现行契约：

1. 架构：`docs/prd/ARCHITECTURE-LOCKED-V1.md` v1.2
2. 验收：`docs/ACCEPTANCE-CRITERIA.md`
3. 应用层边界：`docs/AGENT-ONBOARDING.md`

本文档中的“推荐”均是供用户裁决的方案，**不等于已决定**。所有需要裁决的
内容均以 D1–D13 标识，并在文末“待裁决问题清单”中再次列出。裁决前不得据此
实施。

历史存档只用于识别“证据驱动、保留认知演进轨迹、语义变更需人工批准”的设计
意图。本草案不采用存档中的旧物理分层、旧 API、TrustRank 自动计分、贝叶斯自动
更新、自动写回 Wiki 或 harness/Agent 扩展。

### 规范用语

- **必须**：锁定后属于验收硬条件。
- **应该**：有明确理由时才可偏离，且需记录理由。
- **可以**：可选能力，不影响核心验收。
- **候选规范**：仅在对应 D 项获批后转为正式规范。

---

## 🎯 目标与边界

认知模块管理的不是“更重要的笔记”，而是从记忆、观察或人工输入中提炼出的、
可以被证据支持或挑战的**原子化认知条目**。

候选模块应满足以下目标：

```text
✅ 将 belief / question / hypothesis 存为人类可读的 Markdown
✅ 清楚区分记忆新鲜度与认知确信度
✅ 支持 memory → cognition 的提名、人工批准和来源追踪
✅ 支持挑战、复核、证伪、归档和继任关系
✅ 保留原始记忆与认知演进轨迹
✅ 提供可测试的 Python API 与 CLI 边界
```

无论 D1–D13 如何裁决，以下约束继承自 v1.2，不在本草案中重新表决：

```text
1. $OV/memory/ 仍是平面 Markdown 目录，不新增记忆子目录。
2. 机器不移动、不改写已创建的 memory 笔记。
3. memory 的 confidence/layer/last_accessed/references/pending_delete
   仍只存于既有 sidecar，并沿用无状态新鲜度公式。
4. 认知升级不得绕过 pending_delete → review → purge → trash 流程。
5. 任何流程都不得静默删除 memory 或 cognition 文件。
6. 本模块通过文件系统集成，不引入服务间 API 或数据库作为源真相。
```

---

## 1. 认知条目的定义、类型与文件格式

### 1.1 类型集合（D1）

| 方案 | 内容 | 优点 | 代价 / 风险 |
|---|---|---|---|
| A. 三种核心类型 | `belief`、`question`、`hypothesis` | 与 v1.2 唯一现行线索一致；足以覆盖接受、求解、验证三种认知动作 | 暂不承载 decision/outcome |
| B. 四种类型 | 在 A 上增加 `decision` | KNOW→THINK→ACT 的记录更完整 | 决策有选项、结果和执行状态，生命周期明显不同，会扩大 Phase 5 |
| C. 仅 belief | question/hypothesis 退化为标签或状态 | 模型最小 | 丢失开放问题和可证伪假设的独立语义，后续迁移成本高 |

**推荐（待裁决）**：选择 A。Phase 5 只实现三种核心类型；`decision` 留给后续
独立规格，不从历史存档直接带入。

候选定义：

- `belief`：当前被用户接受、可用于解释或行动的陈述；必须能被证据支持或挑战。
- `question`：尚未回答的信息需求；其完成条件是得到可接受答案，而不是达到某个
  confidence。
- `hypothesis`：尚未被接受、但具有验证方法或证伪条件的陈述；验证后可以经人工
  批准生成或继任一个 belief。

每个条目必须只表达一个主要陈述或问题。一个 memory 笔记可以产生多个认知条目；
认知类型也不能仅由数值阈值自动转换。

### 1.2 Schema 组织方式（D2）

| 方案 | 内容 | 优点 | 代价 / 风险 |
|---|---|---|---|
| A. 公共 schema + 类型校验 | 三类共享身份、来源、证据和关系字段；按类型增加必填规则 | 统一索引和 API；仍保留类型语义 | 校验器需要处理条件必填字段 |
| B. 三套独立 schema | belief/question/hypothesis 各自定义 frontmatter | 每类最直观 | 字段漂移、跨类型查询和迁移更复杂 |
| C. 最小 frontmatter，语义写正文 | 仅保留 `id/type/title` | 手工写作自由 | 机器无法可靠验证、索引或执行状态流转 |

**推荐（待裁决）**：选择 A。所有条目共享一个版本化 schema；`question` 不写
`confidence`，避免把“问题重要度/解决进度”误写成“确信度”。

### 1.3 候选 frontmatter

```yaml
---
schema_version: 1
id: "cog_01K3Y8M6Q4J7V2T9N5P0A1B3C4"
title: "asyncio 更适合 I/O 密集型工作负载"
type: "belief"                 # belief | question | hypothesis
statement: "在主要等待 I/O 的工作负载中，asyncio 通常比线程池更合适。"
status: "active"               # 按类型校验，见下表

# 仅 belief / hypothesis 必填；question 必须省略
confidence: 0.78
confidence_updated_at: "2026-08-29T14:30:00+08:00"
confidence_source: "human_approved_agent_assessment"

created: "2026-08-29T14:00:00+08:00"
updated: "2026-08-29T14:30:00+08:00"
revision: 2
tags: [python, concurrency]

# 手工创建时 origin.kind = manual，其余字段省略
origin:
  kind: "memory"               # memory | manual
  memory_id: "01J6ABCDEF"
  memory_path: "asyncio-not-for-cpu.md"  # 创建时路径快照，非身份
  promoted_at: "2026-08-29T14:00:00+08:00"

evidence:
  - kind: "memory"
    id: "01J6ABCDEF"
    path: "asyncio-not-for-cpu.md"
    relation: "supports"       # supports | challenges | context
    added_at: "2026-08-29T14:00:00+08:00"
    note: "包含项目基准测试与适用边界"

related: []                     # cognition id 列表
supersedes: null                # 新条目继任旧陈述时填写旧 cognition id
---
```

字段约束：

```text
✅ schema_version: 正整数；未知主版本必须拒绝写入
✅ id: 全局稳定、创建后不可变；路径和标题不是身份
✅ title: 人类可读摘要
✅ statement: 单一主张或问题；question 应使用问句
✅ revision: 每次获批的语义更新递增 1
✅ created/updated/confidence_updated_at: 带时区 ISO 8601
✅ origin.memory_id: 升级时必填；memory_path 只作可读路径快照
✅ evidence[].id: 优先使用稳定 ID；path 只作快照
✅ relation: belief/hypothesis 使用 supports/challenges/context；
   question 通常只使用 context
✅ supersedes: 只指向已存在的 cognition id，禁止形成环
```

类型状态候选：

| 类型 | 允许状态 | 说明 |
|---|---|---|
| belief | `draft`、`active`、`questioned`、`refuted`、`superseded`、`archived` | `refuted` 保留被证伪记录；陈述实质变化用 `superseded` |
| hypothesis | `draft`、`testing`、`supported`、`refuted`、`superseded`、`archived` | `supported` 不自动变成 belief |
| question | `open`、`answered`、`superseded`、`archived` | 回答问题可以另建 belief，但不得自动转换 |

正文使用统一骨架；不适用的章节可以省略：

```markdown
# <title>

## 认知陈述

## 理由与适用边界

## 支持证据

## 挑战证据

## 验证 / 证伪条件

## 修订历史
```

`## 修订历史` 必须记录每次获批的 confidence、status、evidence 或继任关系变化，
至少包含时间、旧值、新值和理由。它是面向人的审计摘要，Git 历史仍是完整差异记录。

---

## 2. Confidence 语义与共存规则

### 2.1 字段命名（D3）

| 方案 | 内容 | 优点 | 代价 / 风险 |
|---|---|---|---|
| A. 两处都叫 `confidence`，按对象限定 | memory sidecar 与 cognition frontmatter 沿用现有名称 | 与 v1.2 两处线索兼容；迁移最少 | 脱离上下文展示时容易误解 |
| B. cognition 改叫 `certainty` | memory 保持 `confidence` | 语义区分最强 | 偏离 v1.2 的“认知文件格式”线索；用户仍需理解 certainty 的来源 |
| C. cognition 使用 `epistemic_confidence` | 名称自解释 | API/导出最清晰 | frontmatter 冗长，也偏离现有线索 |

**推荐（待裁决）**：选择 A，但强制使用类型限定的术语、模型和界面标签。
任何跨模块输出必须显示“memory freshness confidence”或“cognition certainty
confidence”，不得只显示裸 `confidence`。

### 2.2 两种 confidence 的正式语义

| 属性 | Memory confidence | Cognition confidence |
|---|---|---|
| 中文术语 | 新鲜度 / 活跃度 | 确信度 / 认知置信度 |
| 存储 | `<state_dir>/index.json` | cognition Markdown frontmatter（D10 推荐） |
| 时间影响 | 按 v1.2 纯函数自然衰减 | **不随时间衰减** |
| 更新输入 | idle days、mtime、last_accessed、引用数 | 新证据、反例、验证结果、人工判断 |
| 更新权限 | 机器可幂等重算 | 机器只可提议；语义变更需人工批准 |
| 分层作用 | 决定 short/mid/long 逻辑层 | 不映射 memory layer |
| 删除作用 | `<0.1` 只触发 pending_delete | 任何值都不触发删除 |

共存不变量：

```text
1. CognitionManager 不得调用 ConfidenceCalculator 计算认知确信度。
2. 认知 confidence 不得读取文件年龄、mtime、last_accessed 或 idle_days。
3. memory confidence 不得被认知 confidence 覆盖、同步或取平均。
4. 不得跨 memory 与 cognition 对 confidence 数值做排序或阈值比较。
5. cognition confidence 不得触发自动类型转换、状态转换、归档或删除。
6. 同一证据集若没有新的人工作出评估，时间经过不得改变认知 confidence。
```

### 2.3 更新权限与算法（D4）

| 方案 | 内容 | 优点 | 代价 / 风险 |
|---|---|---|---|
| A. 人工定值，Agent 可提议 | Agent 给出证据摘要和建议值，用户批准最终值 | 可解释、可审计；Phase 5 不伪装客观概率 | 需要人工参与；不同人的标尺可能不完全一致 |
| B. 规则加减分 | 支持证据 +x，挑战证据 -y | 实现简单、看似一致 | 权重武断；重复证据和相关来源会导致虚假精度 |
| C. TrustRank / 贝叶斯自动更新 | 依据来源与先验计算 | 理论上更系统 | 当前没有锁定的来源独立性、似然或校准模型，超出 Phase 5 |

**推荐（待裁决）**：选择 A。Phase 5 只校验 `[0.0, 1.0]` 范围和审计字段，
不定义自动公式。Agent 可以提出“建议新值 + 理由 + 支持/挑战证据”，但在用户批准前
不得写 cognition 文件。

对 `question`，`confidence`、`confidence_updated_at` 和 `confidence_source` 必须
全部省略。问题的重要度、紧迫度和解决进度若未来需要，应另行定义，不复用 confidence。

### 2.4 存储与显示精度（D5）

| 方案 | 内容 | 优点 | 代价 / 风险 |
|---|---|---|---|
| A. 最多存四位小数，CLI 默认显示两位 | 兼顾导入值与可读性 | 避免界面制造过度精确感；仍可保留少量计算/迁移余量 | 写入时存在一次舍入 |
| B. 存储和显示都固定两位小数 | 最简单、最符合人工估计 | 多次迁移或未来校准时精度有限 |
| C. 原样保存任意合法浮点值 | 不丢输入精度 | YAML/JSON 浮点表示和长小数会制造虚假精度，diff 噪音更大 |

**推荐（待裁决）**：选择 A。范围校验后使用十进制定点规则四舍五入到最多四位；
CLI 默认显示两位，并允许 `--json` 输出存储值。精度只表示记录格式，不宣称概率模型
具有同等测量精度。

---

## 3. Memory → Cognition 升级机制

### 3.1 升级门槛（D6）

| 方案 | 内容 | 优点 | 代价 / 风险 |
|---|---|---|---|
| A. 引用数阈值自动升级 | 例如 references ≥ N 即升级 | 自动化程度高 | 引用数表示使用频率，不表示真实性；会把热门笔记误当认知 |
| B. 只允许人工手工创建 | 用户直接从 memory 创建 cognition | 控制最强 | 难发现候选；重复机械整理 |
| C. Agent 提名 + 人工批准 | 引用、重复出现、证据结构等只作提名信号 | 兼顾发现能力与最终控制；可审计 | 需要 proposal 状态和批准流程 |

**推荐（待裁决）**：选择 C，同时保留用户直接创建的入口。任何引用数、memory
confidence 或 layer 都只能影响候选排序，不能成为自动升级门槛。

提名必须满足：

```text
✅ 来源是 $OV/memory/ 根层的现存 Markdown，且具有稳定 memory id
✅ 提名包含一个原子 statement、目标 type 和提名理由
✅ belief/hypothesis 提名包含至少一个证据引用或明确“目前仅有来源记忆”
✅ hypothesis 提名包含验证或证伪条件
✅ 系统执行 id/statement 相似性检查，并对可能重复项给出警告
✅ 来源若 pending_delete，必须显示警告并在批准界面同时展示 purge 风险
❌ memory confidence、layer、references 不能单独证明可升级
❌ trash 中的来源必须先恢复，不能直接升级
```

候选流程：

```text
1. nominate：生成 proposal；不创建 cognition，不修改 memory。
2. review：展示来源、原子陈述、类型、证据、重复项和建议 confidence。
3. approve：用户确认类型、陈述、初始状态与 confidence 后创建 cognition。
4. reject：记录拒绝理由；不修改 memory。
5. reindex：将新条目加入可重建的 cognition 索引。
```

一次批准必须只创建一个 cognition 文件。一个 memory 可以被多次提名为不同的原子
条目；相同 statement 的重复升级应警告，但是否继续由用户决定。

### 3.2 来源 memory 的处置（D7）

| 方案 | 内容 | 优点 | 代价 / 风险 |
|---|---|---|---|
| A. 原文原地保留、生命周期不变 | cognition 自包含陈述与理由，仅保留来源 ID/路径快照 | 完全符合 v1.2；不把“升级”误解为文件移动 | 以后 purge 来源时，原始上下文可能进入 trash |
| B. 原文保留但在 memory sidecar 标记 promoted | 增加反向追踪 | 扩展既有 sidecar schema，且可能被误用为保护/分层信号 |
| C. 移动、改写或删除来源笔记 | 表面上避免重复 | 直接违反 v1.2，破坏链接、mtime 和审计历史 |

**推荐（待裁决）**：选择 A；C 明确禁止。批准升级前后，来源 memory 的字节、mtime、
路径和既有 sidecar 动态字段必须保持不变。cognition 文件必须包含足以独立理解的
statement、理由和关键证据摘要，不能只做一条易失效的链接。

候选 purge 集成规则：若待 purge memory 被 active/testing/questioned cognition 的
`origin` 或 `evidence` 引用，`memory_cli review/purge` 应显示依赖警告，但仍由用户决定；
系统不得自动阻止、自动恢复或自动提高该 memory 的新鲜度。

“升级”是新增一个有来源的认知条目，不是把 memory 物理搬到 cognition。原 memory
继续遵循自己的新鲜度和 purge 生命周期。

---

## 4. 挑战、降级与证伪机制

### 4.1 演进模型（D8）

| 方案 | 内容 | 优点 | 代价 / 风险 |
|---|---|---|---|
| A. 原文件获批更新 + 实质改写时创建继任条目 | confidence/status/evidence 原地更新并记历史；statement 含义变化则新建 successor | 文件数量可控；保留语义身份与重大修订边界 | 需要明确“何时算实质改写” |
| B. 每次挑战都创建新版本文件 | 旧文件永不改写 | 审计最强 | 文件膨胀；“当前版本”解析复杂 |
| C. 失效后移回 memory 或删除 | 维持 cognition 目录只含当前结论 | 目录表面简洁 | 丢失被证伪过程；与不可静默删除原则冲突 |

**推荐（待裁决）**：选择 A。认知的“降级”只表示 epistemic status 变化，不表示
物理降级或移动。

候选挑战流程：

```text
1. propose-challenge
   - 记录新证据、relation=challenges、理由和建议动作。
   - 仅创建 challenge proposal，不改 cognition。

2. review
   - 并列显示原 statement、全部支持/挑战证据、当前 confidence、建议值。
   - 用户选择 reject / defer / accept。

3. resolve
   - reject：认知不变，proposal 记录拒绝理由。
   - defer：可将 belief 标为 questioned，或保持原状态；必须由用户选择。
   - accept：附加挑战证据，并由用户指定新 confidence 与 status。

4. preserve
   - refuted/archived/superseded 文件保留在原路径。
   - 默认列表可隐藏非活动项，但 show/audit 必须可访问。
```

更新规则：

```text
✅ 新证据到达本身不会自动改 confidence 或 status
✅ 获批更新必须递增 revision、刷新 updated、追加修订历史
✅ belief/hypothesis 被证伪后使用 status=refuted，不删除、不移回 memory
✅ statement 只是措辞澄清时可以原地更新，并在修订历史说明
✅ statement 的适用范围、因果方向或核心含义变化时必须创建新条目，
   新条目 supersedes 旧 id，旧条目标记 superseded
✅ 被 refuted 的条目不得在默认 active 查询中返回，但必须可显式查询
```

Question 的关闭采用同一人工审批原则：设为 `answered` 时必须记录答案摘要或关联的
cognition id；系统不得仅因存在一条相关 belief 就自动关闭问题。

---

## 5. 存储、索引与 Flatnotes

### 5.1 Cognition 目录结构（D9）

| 方案 | 内容 | 优点 | 代价 / 风险 |
|---|---|---|---|
| A. `$OV/cognition/*.md` 平面目录 | 类型由 frontmatter 表达 | 与本地 Markdown 和 Flatnotes 的平面约束一致；跨类型转换无需移动 | 文件多时依赖搜索/索引 |
| B. `$OV/cognition/{beliefs,questions,hypotheses}/` | 物理按类型分组 | 人工浏览直观 | Flatnotes 不支持子目录；类型变化意味着移动；链接更脆弱 |
| C. 与 `$OV/memory/` 混放，用 tag 区分 | 单一界面 | cognition 会被 memory 衰减、搜索和 purge 语义污染 |

**推荐（待裁决）**：选择 A。cognition 与 memory 分离，但 cognition 内部保持平面。
文件名候选为 `<slug>--<short-id>.md`，创建后机器不因标题、类型或状态改变而重命名；
稳定身份始终来自 frontmatter `id`。

候选结构：

```text
$OV/
├── memory/                         # v1.2 平面 memory；保持不变
└── cognition/                      # 平面、批准后的认知源真相
    ├── asyncio-for-io--p0a1b3c4.md
    └── when-to-use-threads--x7y8z9q0.md

<state_dir>/
├── index.json                      # 既有 memory sidecar；保持不变
└── cognition/
    ├── index.json                  # 可从 cognition Markdown 完整重建
    └── proposals.json              # 未批准的 promotion/challenge 工作流状态
```

### 5.2 是否复用 sidecar（D10）

| 方案 | 内容 | 优点 | 代价 / 风险 |
|---|---|---|---|
| A. 语义在 Markdown；sidecar 只做派生索引与 proposal 队列 | confidence/status/evidence 进入 Git 可审计源文件 | 人类可读；不混淆 memory 的机器动态状态 | 获批更新会改 cognition 文件，需要原子写和冲突检查 |
| B. 完全复用 memory sidecar | cognition 文件静态，所有变化写 index | 避免改 Markdown | 认知确信度和证伪历史变成不可见机器状态；与 memory confidence 混淆 |
| C. 不建任何索引 | 每次扫描全部 Markdown | 最简单 | 查询、重复检测和 CLI 列表性能不稳定 |

**推荐（待裁决）**：选择 A，但不与 `<state_dir>/index.json` 共用 schema 或文件。

`<state_dir>/cognition/index.json` 只能镜像以下可重建字段：`id`、`path`、`type`、
`status`、`confidence`、`updated`、`origin.memory_id` 和关系 ID。Markdown 与索引冲突时，
Markdown 胜出并触发 reindex；索引不得反向覆盖 Markdown。

`proposals.json` 只保存尚未批准的工作流状态，不是认知源真相。其丢失不能影响任何
已批准 cognition；所有写入必须原子替换，损坏时应隔离并报告，不能猜测性修复。

### 5.3 与 Flatnotes 的关系（D11）

| 方案 | 内容 | 优点 | 代价 / 风险 |
|---|---|---|---|
| A. Phase 5 不挂载 cognition | 现有 Flatnotes 继续只看 `$OV/memory/` | 不混合捕获与认知审定；零部署变更 | cognition 通过 CLI/Obsidian/文件访问 |
| B. 第二个 Flatnotes 实例挂载 cognition | 有独立 Web 编辑界面 | 增加部署、认证和并发编辑面 |
| C. 同一 Flatnotes 混合 memory/cognition | 一个入口 | 需要合并目录或改变挂载，破坏边界与搜索语义 |

**推荐（待裁决）**：选择 A。Phase 5 不改 Flatnotes 配置、不引入 Web Dashboard。
以后若需要 Web UI，应单独评审 B，并保持 `$OV/cognition/` 为源真相。

---

## 6. API 草图与 CLI 子命令

### 6.1 模块与 CLI 边界（D12）

| 方案 | 内容 | 优点 | 代价 / 风险 |
|---|---|---|---|
| A. `scripts/memory/cognition.py` + 独立 `scripts/cli/cognition_cli.py` | 数据包内复用路径/索引基础，CLI 语义独立 | 避免把两种 confidence 混在同一命令组；符合 Phase 5 所在模块 | 多一个 CLI 入口 |
| B. `scripts/memory/cognition.py` + `memory_cli cognition ...` | 单一 CLI 入口 | 命令发现简单 | 容易让用户误以为 cognition 是 memory layer |
| C. 顶层 `scripts/cognition.py` | 物理上完全独立 | 边界直观 | 偏离当前五个 Atelierr 包结构和 v1.2 的模块组织 |

**推荐（待裁决）**：选择 A。

### 6.2 Python API 候选

以下只定义公共边界，不规定内部实现：

```python
from pathlib import Path
from typing import Literal, Sequence

CognitionType = Literal["belief", "question", "hypothesis"]
EvidenceRelation = Literal["supports", "challenges", "context"]
ChallengeResolution = Literal["reject", "defer", "accept"]


class EvidenceRef:
    """带稳定来源 ID、关系、路径快照和摘要的证据引用。"""


class ApprovalRecord:
    """由直接用户确认产生的时间、动作、理由与 revision 记录。"""


class ValidationReport:
    """逐文件 schema、引用和状态机校验结果。"""


class IndexReport:
    """派生索引重建或 dry-run 的统计与错误报告。"""


class CognitionEntry:
    """一个已批准、通过 schema 校验的认知条目只读视图。"""


class PromotionProposal:
    """尚未改变认知源真相的 memory → cognition 提名。"""


class ChallengeProposal:
    """尚未改变认知源真相的挑战提案。"""


class CognitionManager:
    """管理 cognition Markdown、派生索引与人工审批工作流。"""

    def __init__(
        self,
        ov_path: str | Path,
        state_dir: str | Path | None = None,
    ) -> None: ...

    def create_entry(
        self,
        *,
        entry_type: CognitionType,
        title: str,
        statement: str,
        status: str,
        confidence: float | None,
        tags: Sequence[str] = (),
        evidence: Sequence["EvidenceRef"] = (),
        approval: "ApprovalRecord",
    ) -> CognitionEntry: ...

    def get_entry(self, entry_id: str) -> CognitionEntry: ...

    def list_entries(
        self,
        *,
        entry_type: CognitionType | None = None,
        status: str | None = None,
        include_inactive: bool = False,
    ) -> list[CognitionEntry]: ...

    def nominate_memory(
        self,
        memory_id: str,
        *,
        entry_type: CognitionType,
        title: str,
        statement: str,
        rationale: str,
        proposed_status: str,
        proposed_confidence: float | None = None,
    ) -> PromotionProposal: ...

    def list_promotion_proposals(
        self,
        *,
        status: str = "pending",
    ) -> list[PromotionProposal]: ...

    def approve_promotion(
        self,
        proposal_id: str,
        *,
        status: str,
        confidence: float | None,
        approval: "ApprovalRecord",
    ) -> CognitionEntry: ...

    def reject_promotion(
        self,
        proposal_id: str,
        *,
        reason: str,
        approval: "ApprovalRecord",
    ) -> None: ...

    def propose_challenge(
        self,
        entry_id: str,
        *,
        evidence: Sequence["EvidenceRef"],
        rationale: str,
        proposed_confidence: float | None = None,
        proposed_status: str | None = None,
    ) -> ChallengeProposal: ...

    def resolve_challenge(
        self,
        proposal_id: str,
        *,
        resolution: ChallengeResolution,
        confidence: float | None,
        status: str | None,
        rationale: str,
        approval: "ApprovalRecord",
    ) -> CognitionEntry: ...

    def reassess_entry(
        self,
        entry_id: str,
        *,
        evidence: Sequence["EvidenceRef"],
        confidence: float | None,
        status: str,
        rationale: str,
        approval: "ApprovalRecord",
    ) -> CognitionEntry: ...

    def answer_question(
        self,
        entry_id: str,
        *,
        answer: str,
        related_entries: Sequence[str] = (),
        approval: "ApprovalRecord",
    ) -> CognitionEntry: ...

    def supersede_entry(
        self,
        entry_id: str,
        *,
        replacement_statement: str,
        replacement_confidence: float | None,
        rationale: str,
        approval: "ApprovalRecord",
    ) -> CognitionEntry: ...

    def archive_entry(
        self,
        entry_id: str,
        *,
        reason: str,
        approval: "ApprovalRecord",
    ) -> CognitionEntry: ...

    def validate(self) -> "ValidationReport": ...

    def rebuild_index(self) -> "IndexReport": ...
```

API 约束：

```text
✅ 读取方法不得改变文件、mtime 或 proposal 状态
✅ nominate/propose-challenge 只能写 proposal 工作流状态
✅ create/approve/resolve/reassess/answer/supersede/archive 必须携带显式 ApprovalRecord
✅ 获批写入使用原子替换，并以 revision 检测并发修改
✅ 所有路径必须解析并限制在配置的 memory/cognition/state_dir 内
✅ question 传入非 None confidence 必须抛 ValueError
✅ 不提供 delete_entry 公共 API
✅ 不提供接受裸 float、同时操作 memory/cognition confidence 的通用 API
```

### 6.3 CLI 候选

推荐入口：

```bash
python -m scripts.cli.cognition_cli <command>
```

只读命令：

```bash
cognition list [--type belief|question|hypothesis] [--status STATUS]
cognition show <cognition-id>
cognition proposals list [--kind promotion|challenge]
cognition validate [--json]
```

派生索引维护：

```bash
cognition reindex [--dry-run]
```

创建与升级：

```bash
cognition create --type TYPE --title TITLE --statement TEXT [--confidence N]
cognition nominate <memory-id> --type TYPE --statement TEXT [--confidence N]
cognition promote <proposal-id> [--confidence N] [--dry-run]
cognition proposals reject <proposal-id> --reason TEXT
```

挑战与演进：

```bash
cognition challenge <cognition-id> --evidence-memory <memory-id> --reason TEXT
cognition challenge resolve <proposal-id> --resolution reject|defer|accept \
  [--confidence N] [--status STATUS] --reason TEXT [--dry-run]
cognition reassess <cognition-id> --evidence-memory <memory-id> \
  [--confidence N] --status STATUS --reason TEXT
cognition answer <question-id> --answer TEXT [--related <cognition-id>]
cognition supersede <cognition-id> --statement TEXT [--confidence N] --reason TEXT
cognition archive <cognition-id> --reason TEXT
```

交互约束：

```text
1. create/promote/challenge resolve/reassess/answer/supersede/archive 默认显示完整
   diff 并要求确认。
2. --dry-run 不得写 cognition、index 或 proposal 终态。
3. 若未来提供 --yes，只能代表用户已在当前调用中明确授权；Agent 不得自行附加。
4. 所有命令支持稳定的非零错误码；--json 输出不得混入交互提示。
5. CLI 显示 cognition confidence 时必须同时显示“确信度”，memory 候选信号中的
   confidence 必须显示“新鲜度”。
```

---

## 7. 明确非目标

Phase 5 候选规格明确**不做**：

```text
❌ 不把 cognition 设计成 memory 的第四层或“永不衰减的 long-term”
❌ 不修改 memory confidence 公式、阈值、sidecar schema 或 purge 原则
❌ 不按引用数、memory confidence、layer 或文件年龄自动升级
❌ 不让 cognition confidence 随时间衰减
❌ 不实现自动加减分、TrustRank、贝叶斯更新或来源权重模型
❌ 不允许 Agent 无人工批准地改变认知确信度、状态或 statement
❌ 不自动把 hypothesis 转成 belief，不自动关闭 question
❌ 不物理移动、改写或删除来源 memory
❌ 不自动删除、移动或覆写被证伪的 cognition
❌ 不在 Phase 5 纳入 decision/outcome、GTD、Wiki promotion 或跨域模式检测
❌ 不修改 Flatnotes 部署，不创建 Web Dashboard，不做移动端 UI
❌ 不引入向量数据库、知识图谱、语义去重或外部服务
❌ 不修改 .claude/、.codex/、harness/、protocols/ 或任何 Agent/命令注册表
```

其中“statement 相似性检查”在 Phase 5 只要求规范化文本或可解释的简单比较；
语义向量去重属于未来增强。

---

## 8. 候选验收标准与测试规范

本节采用现有验收文档的写法，为裁决后的合并提供可执行轮廓。当前不修改锁定的
`docs/ACCEPTANCE-CRITERIA.md`。

### 8.1 文件与 schema

**功能要求**:

```python
✅ 必须实现:
  - cognition 文件只创建在 $OV/cognition/ 根层
  - 每个文件具有稳定 id、schema_version、type、statement、status
  - belief/hypothesis 必须有 [0.0, 1.0] confidence
  - question 必须拒绝 confidence 字段
  - 未知 type/status/schema_version 拒绝写入并给出明确错误
  - 非活动条目保留原路径，可显式查询
```

**测试要求**:

```python
def test_create_belief_in_flat_cognition_root(): ...
def test_question_rejects_confidence(): ...
def test_unknown_schema_version_is_rejected(): ...
def test_refuted_entry_remains_readable(): ...
def test_id_is_stable_when_title_or_status_changes(): ...
```

### 8.2 Confidence 隔离

**功能要求**:

```python
✅ 必须实现:
  - cognition confidence 不读取时间、新鲜度或 memory 分层输入
  - 没有新证据和人工批准时，时间经过不改变 cognition confidence
  - memory ConfidenceCalculator 的行为与 v1.2 完全不变
  - CLI/API 不混用两种 confidence
```

**测试要求**:

```python
def test_cognition_confidence_does_not_decay_with_time(): ...
def test_memory_decay_does_not_change_cognition_confidence(): ...
def test_cognition_update_requires_approval_record(): ...
def test_question_has_no_confidence_semantics(): ...
```

### 8.3 升级流程

**功能要求**:

```python
✅ 必须实现:
  - nominate 只创建 proposal，不创建 cognition
  - 只有 approve 才创建 cognition
  - 引用数、memory confidence 和 layer 不会自动批准
  - approve 前后来源 memory 的 bytes/mtime/path/sidecar 动态状态不变
  - cognition 保存稳定 memory id 与路径快照
  - 重复 statement 给出警告但不自行合并
```

**测试要求**:

```python
def test_nomination_has_no_cognition_side_effect(): ...
def test_approval_creates_exactly_one_cognition_entry(): ...
def test_promotion_never_touches_source_memory(): ...
def test_reference_threshold_never_auto_promotes(): ...
def test_pending_delete_source_requires_warning(): ...
```

### 8.4 挑战与证伪

**功能要求**:

```python
✅ 必须实现:
  - challenge proposal 在批准前不改变 cognition
  - reject/defer/accept 都记录理由
  - accept 递增 revision 并追加证据与修订历史
  - refuted/archived/superseded 条目不删除、不移动
  - 实质改变 statement 时创建 successor 并建立 supersedes 关系
```

**测试要求**:

```python
def test_challenge_proposal_does_not_mutate_entry(): ...
def test_accepted_challenge_updates_revision_and_history(): ...
def test_refutation_never_deletes_or_moves_entry(): ...
def test_material_revision_creates_successor(): ...
def test_supersedes_cycle_is_rejected(): ...
```

### 8.5 索引与故障恢复

**功能要求**:

```python
✅ 必须实现:
  - cognition Markdown 是批准后语义状态的唯一源真相
  - 删除派生 index 后可以从 Markdown 完整重建
  - index 与 Markdown 冲突时以 Markdown 为准
  - 损坏文件被隔离报告，不覆盖、不猜测修复
  - 所有获批更新使用 revision 冲突检查和原子写
```

**测试要求**:

```python
def test_index_can_be_rebuilt_from_markdown(): ...
def test_markdown_wins_over_stale_index(): ...
def test_corrupt_entry_is_reported_without_rewrite(): ...
def test_revision_conflict_prevents_lost_update(): ...
```

### 8.6 红线回归

```bash
pytest                         # Atelierr 测试全绿
python tools/acceptance_test.py

额外人工检查:
  ✅ git diff 不包含锁定架构或验收文档的意外修改
  ✅ git diff 不包含 scripts/atelier/、.claude/、.codex/、harness/、protocols/
  ✅ cognition 流程不改变任一来源 memory 的内容、mtime 或路径
  ✅ 不存在 cognition 自动删除路径
```

### 8.7 目标规模与性能门槛（D13）

| 方案 | 内容 | 优点 | 代价 / 风险 |
|---|---|---|---|
| A. Phase 5 先锁正确性基线 | 用 10,000 条 cognition 验证结果完整、无数据丢失并记录 `list/reindex/validate` 耗时，但暂不设硬时限 | 不复制不相关的 memory 指标；能用实测制定后续门槛 | 首版没有性能回归硬阈值 |
| B. 直接锁 10,000 条性能 | `list < 100ms`，`reindex/validate < 5s` | 验收明确，能及早约束实现 | 未经原型测量，可能过严或过松；硬件差异大 |
| C. 先锁 1,000 条 MVP 性能 | `list < 100ms`，`reindex/validate < 2s` | 容易达到，开发反馈快 | 不能证明目标规模下可用，后续可能重做索引 |

**推荐（待裁决）**：选择 A。以 10,000 条作为容量正确性测试，并在验收报告记录
测试硬件、数据规模和三项耗时；实现完成后再依据实测单独锁定性能阈值。

---

## 9. 待裁决问题清单

以下问题无法由本草案单方面决定。请逐项裁决；在全部回答前，本规格保持 draft。
选择某个 D 项表示同时接受该小节列出的候选规则、字段和验收行为；若只同意高层方案，
请在回复中列出需要修改的细节。

| ID | 待裁决问题 | 备选 | 本草案推荐 |
|---|---|---|---|
| D1 | Phase 5 的认知类型有哪些？ | A. belief/question/hypothesis；B. 加 decision；C. 仅 belief | **A** |
| D2 | 是否整组采用公共 schema、类型状态表和 question 省略 confidence 的候选格式？ | A. 整组采用；B. 三套 schema；C. 最小 frontmatter | **A** |
| D3 | 认知确信度字段叫什么？ | A. `confidence` + 强制上下文标签；B. `certainty`；C. `epistemic_confidence` | **A**（兼容 v1.2 线索） |
| D4 | 认知 confidence 如何更新？ | A. Agent 提议、人工定值；B. 规则加减分；C. TrustRank/贝叶斯自动计算 | **A** |
| D5 | confidence 的存储与显示精度？ | A. 最多存四位、默认显示两位；B. 固定两位；C. 原样浮点 | **A** |
| D6 | memory 如何升级？ | A. 引用阈值自动；B. 仅人工手工；C. Agent 提名 + 人工批准，并保留直接创建 | **C** |
| D7 | 升级后来源 memory 如何处置？ | A. 原地不变、正常生命周期，purge 时警告依赖；B. sidecar 标记 promoted；C. 移动/改写/删除 | **A** |
| D8 | 挑战与证伪如何保存历史？ | A. 小变更原文件获批更新，实质改写建 successor；B. 每次都新建版本；C. 移回 memory/删除 | **A** |
| D9 | cognition 的目录与文件身份方案？ | A. 平面目录 + `<slug>--<short-id>.md` 创建后不重命名；B. 按类型子目录；C. 与 memory 混放 | **A** |
| D10 | 是否复用 sidecar？ | A. Markdown 存语义，独立 sidecar 只做派生索引/proposal；B. 复用 memory sidecar；C. 无索引 | **A** |
| D11 | Phase 5 是否接入 Flatnotes？ | A. 不接入；B. 第二实例；C. 与 memory 共用 | **A** |
| D12 | 是否整组采用列出的模块路径、`CognitionManager` API 与独立 CLI surface？ | A. 整组采用；B. 改为 memory_cli 子命令；C. 改为顶层脚本并重审 API | **A** |
| D13 | Phase 5 的规模/性能验收？ | A. 10,000 条只锁正确性并记录耗时；B. 直接锁 10,000 条硬阈值；C. 锁 1,000 条 MVP 阈值 | **A** |

建议裁决回复格式：

```text
D1=A, D2=A, D3=A, D4=A, D5=A, D6=C,
D7=A, D8=A, D9=A, D10=A, D11=A, D12=A, D13=A。
其他修改：____。
```

---

## 10. 裁决后的锁定动作（不属于本次任务）

用户裁决后，应在独立变更中：

```text
1. 将 D1–D13 的结果合并为无“推荐/候选”措辞的正式规格。
2. 按锁定文档修订流程决定是升级 ARCHITECTURE-LOCKED-V1.md，
   还是新增受其引用的 Phase 5 锁定规格。
3. 将第 8 节转写进 docs/ACCEPTANCE-CRITERIA.md，并建立逐条测试映射。
4. 再制定实现计划；在此之前不创建 cognition.py 或 CLI 代码。
```

---

**本文件是待裁决草案，不是已锁定规格。**
