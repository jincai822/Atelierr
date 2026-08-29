# PRD v0.2 变更说明

**文档版本:** v0.2  
**创建日期:** 2026-08-26  
**基于:** v0.1 + P0 问题解决方案  
**状态:** 草稿

---

## 变更摘要

基于 P0 问题解决方案，对 PRD v0.1 进行以下**重大调整**：

### 1. ✅ nashsu/llm_wiki 能力验证（P0-1）

**发现：** nashsu/llm_wiki 完全满足需求

**影响：**
- ✅ 多模态处理方案 **100% 可行**
- ✅ Web Clipper 集成 **无需自建**
- ✅ HTTP API 完整可用

**结论：** Section 2.4（多模态资料来源处理方案）**无需修改**，方案可行。

---

### 2. 🔄 V0 范围大幅简化（P0-2）

**原设计问题：**
- 8 个核心模块太多
- 工作量约 40 天
- 风险高

**新 V0 范围：**

#### 保留模块（3 个核心 + 工具集）

✅ **Module 1: Cognition Core**
- Belief Management
- Model Management  
- Open Question Management
- Decision Tracking
- Learning Agenda

✅ **Module 4: Knowledge Vault**
- Published Knowledge Ingestion
- Wiki Schema
- TrustRank
- Claim/Evidence 查询

✅ **Module 7: Human Interface**
- Obsidian 编辑
- CLI 命令
- 基础查询

✅ **Support Tools**（现有脚本）
- scripts/context_bundle.py
- scripts/semantic.py
- scripts/cues.py
- scripts/pricing.py
- scripts/trustrank.py

#### 延后到 V1（5 个模块）

⏸️ **Module 2: Agent Runtime** → V1
- V0 替代：手工调用 Atelier Agents

⏸️ **Module 3: Workflow Engine** → V1
- V0 替代：简单的 Intent Router

⏸️ **Module 5: Model Gateway** → V1
- V0 替代：直接调用 Claude API

⏸️ **Module 6: Feedback Loop** → V1
- V0 替代：手工记录反馈

⏸️ **Module 8: Memory System 独立模块** → V1
- V0 替代：继续使用脚本工具

**工作量对比：**
| 版本 | 模块数 | 代码量 | 工期 | 风险 |
|------|--------|--------|------|------|
| v0.1 设计 | 8 | 10000 行 | 40 天 | 高 |
| v0.2 设计 | 3 + 工具 | 3500 行 | 18 天 | 中 |
| **减少** | **-62%** | **-65%** | **-55%** | **降低** |

---

### 3. 🆕 存储方案定义（P0-3）

**问题：** PRD v0.1 未明确数据存储方案

**解决方案：** Markdown + SQLite 混合存储

#### 架构

```
$OV/
├── beliefs/               # Beliefs（Markdown，源真相）
├── decisions/             # Decisions（Markdown）
├── questions/             # Open Questions（Markdown）
├── learning/              # Learning Agenda（Markdown）
├── wiki/                  # llm_wiki 输出（Markdown）
└── .index/                # 索引层（SQLite）
    ├── cognition.db       # Beliefs/Decisions/Questions 索引
    ├── knowledge.db       # Claims/Sources/TrustRank 索引
    └── metadata.db        # 文件元数据
```

#### 设计原则

1. **Markdown 是源真相** — Obsidian 兼容，人可读
2. **SQLite 是索引** — 复杂查询高性能
3. **双写机制** — 写操作同时更新 Markdown 和 SQLite
4. **索引可重建** — SQLite 损坏时可从 Markdown 重建

#### 示例：Belief 存储

**Markdown 文件：** `$OV/beliefs/belief_001.md`
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
tags: [programming, python, concurrency]
---

# Python asyncio 适合 I/O 密集型任务

## 支持证据
...
```

**SQLite 记录：** `$OV/.index/cognition.db`
```sql
INSERT INTO beliefs (id, statement, confidence, created, updated, file_path)
VALUES ('belief_20260826_001', 
        'Python asyncio 适合 I/O 密集型任务', 
        0.9, 
        '2026-08-26T10:30:00Z', 
        '2026-08-26T12:00:00Z', 
        '$OV/beliefs/belief_001.md');
```

---

## PRD 各章节的变更

### Section 1: 产品定位与核心闭环

**变更：** 无变更

**说明：** 核心闭环（KNOW → THINK → ACT → LEARN）不变。

---

### Section 2: 产品边界

**变更：** 无变更

**说明：** 
- 2.1-2.3：边界定义不变
- 2.4：多模态处理方案验证可行，无需修改

---

### Section 3: Atelier 当前实现分析

**变更：** 无变更

**说明：** Gap 分析依然有效。

---

### Section 4: 认知领域模型

**变更：** 无变更

**说明：** 实体和关系定义不变。

---

### Section 5: 八模块架构设计

**变更：** ⚠️ **重大变更**

#### 5.1 Module 1: Cognition Flywheel Core

**变更：** 无变更

**V0 实现范围：**
- ✅ Belief Management
- ✅ Model Management
- ✅ Open Question Management
- ✅ Decision Tracking
- ✅ Learning Agenda
- ⏸️ Action Execution → V1

---

#### 5.2 Module 2: Agent Runtime

**变更：** ⏸️ **延后到 V1**

**V0 替代方案：**
- 手工调用 Atelier 的 11 个 Agents
- 通过 CLI 或 Obsidian 触发
- 无需自动化编排

---

#### 5.3 Module 3: Workflow Engine

**变更：** ⏸️ **延后到 V1**

**V0 替代方案：**
- 使用现有的 Intent Router（`harness/intents.toml`）
- 简单的命令分发，无复杂编排

---

#### 5.4 Module 4: Knowledge Vault

**变更：** ✅ **新增存储方案**

**当前实现：**
- V0: Markdown + SQLite 混合存储
- TrustRank: `scripts/trustrank.py`（复用）
- 摄入：File Watcher 监听 llm_wiki 输出

**新增内容：**
- SQLite Schema 定义（详见 p0-resolution.md）
- 双写机制实现
- 索引重建机制

---

#### 5.5 Module 5: Model Gateway

**变更：** ⏸️ **延后到 V1**

**V0 替代方案：**
- 直接调用 Claude API
- 成本日志记录到 `~/.cache/atelier/llm_calls/*.jsonl`
- 事后分析用 `scripts/pricing.py`

---

#### 5.6 Module 6: Feedback Loop

**变更：** ⏸️ **延后到 V1**

**V0 替代方案：**
- 手工记录反馈到 `$OV/reflections/`
- 无自动化反馈收集

---

#### 5.7 Module 7: Human Interface

**变更：** ✅ **确认 Obsidian 兼容性**

**V0 实现：**
- Obsidian 编辑（Markdown + YAML frontmatter）
- CLI 命令（基础查询）
- File Watcher（双向同步）

**验证结果：**
- ✅ Markdown 格式完全兼容
- ✅ 双向链接支持
- ✅ Dataview/Templater 插件可用

---

#### 5.8 Module 8: Memory System

**变更：** ⏸️ **独立模块延后到 V1**

**V0 替代方案：**
- 继续使用脚本工具
  - `scripts/context_bundle.py`（上下文加载）
  - `scripts/semantic.py`（语义搜索）
- 无 Working Memory 缓存层
- 无 Episodic Memory 重建

**V1 升级路径：**
- Working Memory 缓存层
- Episodic Memory 重建
- Multi-modal Index
- Importance Scoring

---

### Section 6: Support Tools

**变更：** 无变更

**说明：** Health Checker 和 Cost Analyzer 保持脚本工具。

---

### Section 7: V0/V1 范围定义

**变更：** ⚠️ **重大变更**

#### 7.1 新 V0 范围（MVP）

**目标：** 验证核心认知飞轮

**必须实现：**
- ✅ Module 1: Cognition Core (Beliefs, Models, Questions, Decisions, Learning Agenda)
- ✅ Module 4: Knowledge Vault (L1-L5, Wiki Schema, TrustRank, Published Knowledge Ingestion)
- ✅ Module 7: Human Interface (Obsidian, CLI)
- ✅ Support Tools (scripts/cues.py, scripts/pricing.py, scripts/context_bundle.py, scripts/semantic.py)

**存储实现：**
- ✅ Markdown + SQLite 混合存储
- ✅ 双写机制
- ✅ 索引重建

**延后到 V1：**
- ⏸️ Module 2: Agent Runtime
- ⏸️ Module 3: Workflow Engine
- ⏸️ Module 5: Model Gateway
- ⏸️ Module 6: Feedback Loop
- ⏸️ Module 8: Memory System（独立模块）

**验收标准：**
1. ✅ 能够通过 File Watcher 摄入 llm_wiki 输出
2. ✅ 能够基于 Claims 创建 Beliefs
3. ✅ 能够追踪 Open Questions
4. ✅ 能够记录 Decisions
5. ✅ 能够查询 Beliefs/Decisions/Questions
6. ✅ TrustRank 计算正常
7. ✅ 在 Obsidian 中可编辑所有实体
8. ✅ CLI 查询功能可用

**工期：** 18 天（3 周）

---

#### 7.2 新 V1 范围（完整产品）

**目标：** 完整认知飞轮 + Agent 编排 + Memory System 独立模块

**新增实现：**
- ✅ Module 2: Agent Runtime（11 个专业智能体 + 编排）
- ✅ Module 3: Workflow Engine（复杂工作流）
- ✅ Module 5: Model Gateway（多模型抽象 + 成本控制）
- ✅ Module 6: Feedback Loop（自动化反馈收集）
- ✅ Module 8: Memory System V1（独立模块，10-100GB 知识库支持）

**工期：** V0 完成后 4-6 周

---

### Section 8: 风险与开放问题

**变更：** ✅ **新增 P0 解决方案缓解的风险**

#### 已缓解的风险

**Risk 1: nashsu/llm_wiki 能力不确定性** → ✅ 已解决
- 完全满足需求
- HTTP API 完整可用
- Web Clipper 内置

**Risk 2: 架构复杂度过高** → ✅ 已缓解
- V0 从 8 模块减少到 3 模块
- 工作量减少 65%
- 风险降低

**Risk 3: 存储方案未定义** → ✅ 已解决
- Markdown + SQLite 混合方案
- Obsidian 兼容性验证通过

#### 仍存在的风险

**Risk 4: TrustRank 计算成本**（保持）
- 缓解措施不变（增量更新、缓存、异步计算）

**Risk 5: 100GB 知识库性能挑战**（保持）
- V0 不需要支持 100GB
- V1 再实施 Memory System 独立模块

---

### Section 9: 下一步行动

**变更：** ⚠️ **完全替换**

#### 9.1 立即行动（本周）

1. ✅ P0 问题已解决
2. ⬜ 用户评审 PRD v0.2
3. ⬜ 确认新 V0 范围
4. ⬜ 开始 Week 1 实施

#### 9.2 Week 1: 基础设施（Day 1-5）

**Day 1-2: 存储层实现**
- Markdown Schema 定义
- SQLite Schema 创建
- 双写机制实现
- 索引重建脚本

**Day 3-4: llm_wiki 集成**
- File Watcher 实现
- HTTP API 客户端实现
- 集成测试

**Day 5: 测试和文档**
- 单元测试
- 集成测试
- API 文档

#### 9.3 Week 2: Cognition Core（Day 6-10）

**Day 6-8: Belief Management**
- Belief CRUD 实现
- Confidence 更新逻辑
- History 追踪
- 查询接口

**Day 9-10: Question & Decision**
- Question CRUD
- Decision CRUD
- 关联关系实现

#### 9.4 Week 3: Knowledge Vault（Day 11-15）

**Day 11-13: Knowledge Ingestion**
- Published Knowledge Ingestion
- Claim 提取
- Source 管理
- TrustRank 集成

**Day 14-15: 查询和检索**
- Claim 查询实现
- 语义搜索集成
- TrustRank 查询

#### 9.5 Week 4: Human Interface & 测试（Day 16-20）

**Day 16-17: Obsidian 集成**
- Markdown 格式验证
- File Watcher 测试
- 双向链接测试

**Day 18: CLI 实现**
- 基础命令实现
  - `cognition belief list`
  - `cognition belief show <id>`
  - `cognition decision list`
  - `cognition question list`

**Day 19-20: 端到端测试**
- 完整流程测试
- 性能测试
- 用户验收测试

**预计完成日期：** 2026-09-16

---

## 附录：集成契约

### A.1 llm_wiki → 本系统

**File Watcher 集成：**
```python
# 监听 llm_wiki 的 wiki/ 目录
watch_directory = "<llm_wiki_project>/wiki/"
events = ["CREATE", "MODIFY", "DELETE"]
handler = WikiFileHandler()
```

**HTTP API 集成：**
```yaml
api:
  base_url: "http://127.0.0.1:19828/api/v1"
  token: "<从 LLM_WIKI_API_TOKEN 环境变量获取>"
  project_id: "current"
```

**关键端点：**
- `POST /projects/{id}/search` — 混合检索
- `GET /projects/{id}/files/content` — 读取文件
- `GET /projects/{id}/graph` — 知识图谱
- `POST /projects/{id}/sources/rescan` — 触发重新扫描

### A.2 本系统 → llm_wiki

**触发摄入：**
```python
# 方式 1: 复制到 raw/sources/
shutil.copy(file_path, f"{llm_wiki_project}/raw/sources/")

# 方式 2: 调用 API 触发重新扫描
POST /api/v1/projects/current/sources/rescan
```

---

## 总结

### 核心变更

1. **✅ V0 范围大幅简化** — 从 8 模块减少到 3 模块，工作量减少 65%
2. **✅ 存储方案明确** — Markdown + SQLite 混合存储，Obsidian 完全兼容
3. **✅ 集成方案验证** — nashsu/llm_wiki 完全满足需求，无需自建

### 风险缓解

- ⬇️ 架构复杂度风险：**大幅降低**（模块减少 62%）
- ⬇️ 实施风险：**大幅降低**（工期减少 55%）
- ⬇️ 集成不确定性：**完全消除**（API 验证通过）

### 下一步

✅ **用户评审 PRD v0.2**  
✅ **确认新 V0 范围**  
✅ **开始 Week 1 实施**

---

**文档版本:** v0.2  
**最后更新:** 2026-08-26  
**状态:** 草稿  
**需要用户确认后进入正式版**
