# Atelierr 认知模块规格

**版本**: v1.0

**状态**: 🔒 已锁定

**日期**: 2026-08-29

**目标实现**: Phase 5，`scripts/cognition/manager.py`

---

## 📋 文档说明

本文档是 Atelierr Phase 5 认知模块的正式规格，与以下现行契约共同生效：

1. 架构：`docs/prd/ARCHITECTURE-LOCKED-V1.md` v1.3
2. 认知模块：`docs/prd/COGNITION-SPEC.md` v1.0（本文档）
3. 验收：`docs/ACCEPTANCE-CRITERIA.md` v1.1
4. 应用层边界：`docs/AGENT-ONBOARDING.md`

发生冲突时，系统级不变量以架构 v1.3 为准；认知模块的数据模型和状态流转以
本文档为准；可执行验收以验收标准 v1.1 为准。

历史存档不构成实现依据。本规格不采用存档中的旧物理分层、旧 API、TrustRank
自动计分、贝叶斯自动更新、自动写回 Wiki 或 harness/Agent 扩展。

### 规范用语

- **必须**：属于验收硬条件。
- **应该**：有明确理由时才可偏离，且需记录理由。
- **可以**：可选能力，不影响核心验收。

---

## 🎯 目标与边界

认知模块管理的不是“更重要的笔记”，而是从记忆、观察或人工输入中提炼出的、
可以被证据支持或挑战的**原子化认知条目**。

模块必须满足以下目标：

```text
✅ 将 belief / question / hypothesis 存为人类可读的 Markdown
✅ 清楚区分记忆新鲜度与认知确信度
✅ 支持 memory → cognition 的提名、人工批准和来源追踪
✅ 支持挑战、复核、证伪、归档和继任关系
✅ 保留原始记忆与认知演进轨迹
✅ 提供可测试的 Python API 与 CLI 边界
```

以下约束继承自架构 v1.3：

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

### 1.1 类型集合

Phase 5 只实现 `belief`、`question`、`hypothesis` 三种核心类型。`decision` 和
outcome 不属于本版本；如需引入，必须另行制定生命周期与验收规格。

正式定义：

- `belief`：当前被用户接受、可用于解释或行动的陈述；必须能被证据支持或挑战。
- `question`：尚未回答的信息需求；其完成条件是得到可接受答案，而不是达到某个
  certainty。
- `hypothesis`：尚未被接受、但具有验证方法或证伪条件的陈述；验证后可以经人工
  批准生成或继任一个 belief。

每个条目必须只表达一个主要陈述或问题。一个 memory 笔记可以产生多个认知条目；
认知类型也不能仅由数值阈值自动转换。

### 1.2 Schema 组织方式

三种类型共享一个版本化 schema，并按类型执行条件字段和状态校验。`question`
必须省略 `certainty`、`certainty_updated_at`、`certainty_source`，避免把问题重要度、
解决进度或答案质量误写成确信度。

### 1.3 Frontmatter

```yaml
---
schema_version: 1
id: "cog_01K3Y8M6Q4J7V2T9N5P0A1B3C4"
title: "asyncio 更适合 I/O 密集型工作负载"
type: "belief"                 # belief | question | hypothesis
statement: "在主要等待 I/O 的工作负载中，asyncio 通常比线程池更合适。"
status: "active"               # 按类型校验，见下表

# 仅 belief / hypothesis 必填；question 必须省略
certainty: 0.78
certainty_updated_at: "2026-08-29T14:30:00+08:00"
certainty_source: "human_approved_agent_assessment"

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
✅ created/updated/certainty_updated_at: 带时区 ISO 8601
✅ certainty_source: human_assessment | human_approved_agent_assessment
✅ origin.memory_id: 升级时必填；memory_path 只作可读路径快照
✅ relation: belief/hypothesis 使用 supports/challenges/context；
   question 通常只使用 context
✅ supersedes: 只指向已存在的 cognition id，禁止形成环
```

`evidence[].kind` 只允许 `memory | url | manual`，且所有 evidence 都必须包含
`relation` 和带时区的 `added_at`。各 kind 的字段规则如下：

| kind | 必填字段 | 可选字段 | 禁止字段 |
|---|---|---|---|
| `memory` | `id`、`path`、`relation`、`added_at` | `note` | `url`、`accessed_at` |
| `url` | `url`、`accessed_at`、`relation`、`added_at` | `note` | `id`、`path` |
| `manual` | `note`、`relation`、`added_at` | 无 | `id`、`path`、`url`、`accessed_at` |

附加校验：

```text
✅ memory.id 必须是稳定 memory id；memory.path 是创建证据引用时的相对路径快照
✅ url.url 必须是绝对 http/https URL；url.accessed_at 必须是带时区 ISO 8601
✅ manual.note 必须是非空的人工证据摘要，不得伪装成外部可验证来源
✅ kind 对应的禁止字段一旦出现，整个 evidence 项必须拒绝写入
```

类型状态：

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

`## 修订历史` 必须记录每次获批的 certainty、status、evidence 或继任关系变化，
至少包含时间、旧值、新值和理由。它是面向人的审计摘要，Git 历史仍是完整差异记录。

---

## 2. Confidence 与 certainty 的语义边界

### 2.1 字段命名

Memory 侧保留 v1.3 已锁定的 `confidence`；cognition 侧统一使用 `certainty`、
`certainty_updated_at`、`certainty_source`。认知模块不得创建或接受 cognition
`confidence` 字段。

跨模块输出必须明确显示“memory confidence（新鲜度）”或“cognition certainty
（确信度）”。

### 2.2 两种数值的正式语义

| 属性 | Memory confidence | Cognition certainty |
|---|---|---|
| 中文术语 | 新鲜度 / 活跃度 | 确信度 |
| 存储 | `<state_dir>/index.json` | cognition Markdown frontmatter |
| 时间影响 | 按 v1.3 纯函数自然衰减 | **不随时间衰减** |
| 更新输入 | idle days、mtime、last_accessed、引用数 | 新证据、反例、验证结果、人工判断 |
| 更新权限 | 机器可幂等重算 | 机器只可提议；语义变更需人工批准 |
| 分层作用 | 决定 short/mid/long 逻辑层 | 不映射 memory layer |
| 删除作用 | `<0.1` 只触发 pending_delete | 任何值都不触发删除 |

共存不变量：

```text
1. CognitionManager 不得调用 ConfidenceCalculator 计算 certainty。
2. certainty 不得读取文件年龄、mtime、last_accessed 或 idle_days。
3. memory confidence 不得被 certainty 覆盖、同步或取平均。
4. 不得跨 memory confidence 与 cognition certainty 做排序或阈值比较。
5. certainty 不得触发自动类型转换、状态转换、归档或删除。
6. 同一证据集若没有新的人工作出评估，时间经过不得改变 certainty。
```

### 2.3 更新权限与算法

Phase 5 只校验 certainty 的 `[0.0, 1.0]` 范围和审计字段，不定义自动公式。
Agent 可以提出“建议新值 + 理由 + 支持/挑战证据”，最终值必须由用户批准；批准前
不得写 cognition 文件。`certainty_source` 只允许：

- `human_assessment`：用户直接给出或修改数值。
- `human_approved_agent_assessment`：Agent 提议，用户审阅后批准数值。

对 `question`，`certainty`、`certainty_updated_at` 和 `certainty_source` 必须全部
省略。问题的重要度、紧迫度和解决进度若未来需要，应另行定义，不复用 certainty。

### 2.4 存储与显示精度

certainty 通过范围校验后，使用十进制定点规则四舍五入到最多四位；
CLI 默认显示两位，并允许 `--json` 输出存储值。精度只表示记录格式，不宣称概率模型
具有同等测量精度。

---

## 3. Memory → Cognition 升级机制

### 3.1 升级门槛

升级采用“Agent 提名 + 人工批准”，同时保留用户直接创建入口。任何引用数、memory
confidence 或 layer 都只能影响提名排序，不能成为自动升级门槛。

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

升级流程：

```text
1. nominate：生成 proposal；不创建 cognition，不修改 memory。
2. review：展示来源、原子陈述、类型、证据、重复项和建议 certainty。
3. approve：用户确认类型、陈述、初始状态与 certainty 后创建 cognition。
4. reject：记录拒绝理由；不修改 memory。
5. reindex：将新条目加入可重建的 cognition 索引。
```

一次批准必须只创建一个 cognition 文件。一个 memory 可以被多次提名为不同的原子
条目；相同 statement 的重复升级应警告，但是否继续由用户决定。

### 3.2 来源 memory 的处置

批准升级前后，来源 memory 的字节、mtime、
路径和既有 sidecar 动态字段必须保持不变。cognition 文件必须包含足以独立理解的
statement、理由和关键证据摘要，不能只做一条易失效的链接。

若待 purge memory 被 active/testing/questioned cognition 的
`origin` 或 `evidence` 引用，`memory_cli review/purge` 应显示依赖警告，但仍由用户决定；
系统不得自动阻止、自动恢复或自动提高该 memory 的新鲜度。

“升级”是新增一个有来源的认知条目，不是把 memory 物理搬到 cognition。原 memory
继续遵循自己的新鲜度和 purge 生命周期。

---

## 4. 挑战、降级与证伪机制

### 4.1 演进模型

certainty、status 和 evidence 的获批小变更在原文件更新并记录历史；statement 的
核心含义发生变化时创建继任条目。认知的“降级”只表示 epistemic status 变化，
不表示物理降级或移动。

挑战流程：

```text
1. propose-challenge
   - 记录新证据、relation=challenges、理由和建议动作。
   - 仅创建 challenge proposal，不改 cognition。

2. review
   - 并列显示原 statement、全部支持/挑战证据、当前 certainty、建议值。
   - 用户选择 reject / defer / accept。

3. resolve
   - reject：认知不变，proposal 记录拒绝理由。
   - defer：可将 belief 标为 questioned，或保持原状态；必须由用户选择。
   - accept：附加挑战证据，并由用户指定新 certainty 与 status。

4. preserve
   - refuted/archived/superseded 文件保留在原路径。
   - 默认列表可隐藏非活动项，但 show/audit 必须可访问。
```

更新规则：

```text
✅ 新证据到达本身不会自动改 certainty 或 status
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

### 5.1 Cognition 目录结构

cognition 与 memory 分离，且 `$OV/cognition/*.md` 内部保持平面。文件名为
`<slug>--<short-id>.md`，创建后机器不因标题、类型或状态改变而重命名；
稳定身份始终来自 frontmatter `id`。

存储结构：

```text
$OV/
├── memory/                         # v1.3 平面 memory；保持不变
└── cognition/                      # 平面、批准后的认知源真相
    ├── asyncio-for-io--p0a1b3c4.md
    └── when-to-use-threads--x7y8z9q0.md

<state_dir>/
├── index.json                      # 既有 memory sidecar；保持不变
└── cognition/
    ├── index.json                  # 可从 cognition Markdown 完整重建
    └── proposals.json              # 未批准的 promotion/challenge 工作流状态
```

### 5.2 Sidecar 边界

certainty、status 和 evidence 等认知语义存于 cognition Markdown。独立 sidecar 只做
派生索引与 proposal 队列，不与 memory 的 `<state_dir>/index.json` 共用 schema 或文件。

`<state_dir>/cognition/index.json` 只能镜像以下可重建字段：`id`、`path`、`type`、
`status`、`certainty`、`updated`、`origin.memory_id` 和关系 ID。Markdown 与索引冲突时，
Markdown 胜出并触发 reindex；索引不得反向覆盖 Markdown。

`proposals.json` 只保存尚未批准的工作流状态，不是认知源真相。其丢失不能影响任何
已批准 cognition；所有写入必须原子替换，损坏时应隔离并报告，不能猜测性修复。

### 5.3 与 Flatnotes 的关系

Phase 5 不挂载 cognition，不改 Flatnotes 配置，也不引入 Web Dashboard。现有
Flatnotes 继续只访问 `$OV/memory/`；cognition 通过 CLI、Obsidian 或文件系统访问。
以后若需要 Web UI，必须单独评审，并保持 `$OV/cognition/` 为源真相。

---

## 6. API 草图与 CLI 子命令

### 6.1 模块与 CLI 边界

实现模块位于 `scripts/cognition/manager.py`，命令入口位于独立的
`scripts/cli/cognition_cli.py`。cognition 不作为 memory layer，也不挂入
`memory_cli cognition ...`。

### 6.2 Python API

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
        certainty: float | None,
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
        proposed_certainty: float | None = None,
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
        certainty: float | None,
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
        proposed_certainty: float | None = None,
        proposed_status: str | None = None,
    ) -> ChallengeProposal: ...

    def resolve_challenge(
        self,
        proposal_id: str,
        *,
        resolution: ChallengeResolution,
        certainty: float | None,
        status: str | None,
        rationale: str,
        approval: "ApprovalRecord",
    ) -> CognitionEntry: ...

    def reassess_entry(
        self,
        entry_id: str,
        *,
        evidence: Sequence["EvidenceRef"],
        certainty: float | None,
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
        replacement_certainty: float | None,
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
✅ question 传入非 None certainty 必须抛 ValueError
✅ 不提供 delete_entry 公共 API
✅ 不提供接受裸 float、同时操作 memory confidence/cognition certainty 的通用 API
```

### 6.3 CLI

命令入口：

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
cognition create --type TYPE --title TITLE --statement TEXT [--certainty N]
cognition nominate <memory-id> --type TYPE --statement TEXT [--certainty N]
cognition promote <proposal-id> [--certainty N] [--dry-run]
cognition proposals reject <proposal-id> --reason TEXT
```

挑战与演进：

```bash
cognition challenge <cognition-id> --evidence-memory <memory-id> --reason TEXT
cognition challenge resolve <proposal-id> --resolution reject|defer|accept \
  [--certainty N] [--status STATUS] --reason TEXT [--dry-run]
cognition reassess <cognition-id> --evidence-memory <memory-id> \
  [--certainty N] --status STATUS --reason TEXT
cognition answer <question-id> --answer TEXT [--related <cognition-id>]
cognition supersede <cognition-id> --statement TEXT [--certainty N] --reason TEXT
cognition archive <cognition-id> --reason TEXT
```

交互约束：

```text
1. create/promote/challenge resolve/reassess/answer/supersede/archive 默认显示完整
   diff 并要求确认。
2. --dry-run 不得写 cognition、index 或 proposal 终态。
3. 若未来提供 --yes，只能代表用户已在当前调用中明确授权；Agent 不得自行附加。
4. 所有命令支持稳定的非零错误码；--json 输出不得混入交互提示。
5. CLI 显示 cognition certainty 时必须显示“确信度”，memory 提名信号中的
   confidence 必须显示“新鲜度”。
```

---

## 7. 明确非目标

Phase 5 明确**不做**：

```text
❌ 不把 cognition 设计成 memory 的第四层或“永不衰减的 long-term”
❌ 不修改 memory confidence 公式、阈值、sidecar schema 或 purge 原则
❌ 不按引用数、memory confidence、layer 或文件年龄自动升级
❌ 不让 cognition certainty 随时间衰减
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

## 8. 验收标准与测试规范

本节采用现有验收文档的写法，为裁决后的合并提供可执行轮廓。当前不修改锁定的
`docs/ACCEPTANCE-CRITERIA.md`。

### 8.1 文件与 schema（COG-SCHEMA）

**功能要求**:

```python
✅ 必须实现:
  - cognition 文件只创建在 $OV/cognition/ 根层
  - 每个文件具有稳定 id、schema_version、type、statement、status
  - belief/hypothesis 必须有 [0.0, 1.0] certainty
  - question 必须拒绝 certainty 字段
  - 未知 type/status/schema_version 拒绝写入并给出明确错误
  - 非活动条目保留原路径，可显式查询
```

**测试要求**:

```python
def test_create_belief_in_flat_cognition_root(): ...
def test_question_rejects_certainty(): ...
def test_unknown_schema_version_is_rejected(): ...
def test_refuted_entry_remains_readable(): ...
def test_id_is_stable_when_title_or_status_changes(): ...
```

### 8.2 数值语义隔离（COG-CERTAINTY）

**功能要求**:

```python
✅ 必须实现:
  - cognition certainty 不读取时间、新鲜度或 memory 分层输入
  - 没有新证据和人工批准时，时间经过不改变 cognition certainty
  - memory ConfidenceCalculator 的行为与 v1.3 完全不变
  - CLI/API 不混用 memory confidence 与 cognition certainty
```

**测试要求**:

```python
def test_cognition_certainty_does_not_decay_with_time(): ...
def test_memory_decay_does_not_change_cognition_certainty(): ...
def test_cognition_update_requires_approval_record(): ...
def test_question_has_no_certainty_semantics(): ...
```

### 8.3 升级流程（COG-PROMOTION）

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

### 8.4 挑战与证伪（COG-CHALLENGE）

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

### 8.5 索引与故障恢复（COG-INDEX）

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

### 8.6 红线回归（COG-REDLINE）

```bash
pytest                         # Atelierr 测试全绿
python tools/acceptance_test.py
.venv/bin/python scripts/atelier/harness_smoke.py  # exit 0

额外人工检查:
  ✅ git diff 不包含锁定架构或验收文档的意外修改
  ✅ git diff 不包含 scripts/atelier/、.claude/、.codex/、harness/、protocols/
  ✅ cognition 流程不改变任一来源 memory 的内容、mtime 或路径
  ✅ 不存在 cognition 自动删除路径
```

### 8.7 目标规模与性能门槛（COG-SCALE）

Phase 5 使用 10,000 条 cognition 做容量正确性测试，必须验证结果完整且无数据丢失，
并在验收报告记录测试硬件、数据规模以及 `list/reindex/validate` 三项耗时。本版本暂不设
硬性能时限；实现完成后依据实测结果另行锁定性能回归阈值。

---

## 9. 版本历史

### v1.0 (2026-08-29) - 初始锁定

```text
✅ 锁定 belief/question/hypothesis 三种认知类型与公共 schema
✅ cognition 使用 certainty，与 memory confidence 从字段名上隔离
✅ 锁定 Agent 提名 + 人工批准的升级机制
✅ 锁定挑战、证伪、继任和审计历史
✅ 锁定平面 cognition 存储、独立派生索引与 Flatnotes 边界
✅ 锁定 Python API、独立 CLI、验收要求与 10,000 条容量正确性基线
```

---

**🔒 本文档已锁定为 v1.0。**
