# Personal Intelligence System - 架构深度对齐文档

**创建日期:** 2026-08-26 20:01  
**对齐方式:** 自顶向下，逐层细化  
**目标:** 确保架构的每个细节都清晰可实施

---

## 🏗️ 第一层：系统总体架构

### 1.1 系统定位

```
┌─────────────────────────────────────────────────────────────┐
│                        Human User                           │
│                  (提供意图、审批决策、消费洞察)                │
└───────────────────┬─────────────────────────────────────────┘
                    │
                    │ 交互
                    ↓
┌─────────────────────────────────────────────────────────────┐
│         Personal Intelligence System (本系统)               │
│                                                             │
│  核心能力：KNOW → THINK → ACT → LEARN 认知循环              │
│                                                             │
│  ┌─────────────────────────────────────────────────────┐   │
│  │ Module 1: Cognition Core (认知核心)                  │   │
│  │ - Belief Management (信念管理)                       │   │
│  │ - Question Tracking (问题追踪)                       │   │
│  │ - Decision Tracking (决策追踪)                       │   │
│  │ - Learning Agenda (学习议程)                         │   │
│  └──────────────┬──────────────────────────────────────┘   │
│                 │                                           │
│                 │ 依赖                                      │
│                 ↓                                           │
│  ┌─────────────────────────────────────────────────────┐   │
│  │ Module 4: Knowledge Vault (知识库)                   │   │
│  │ - Knowledge Ingestion (知识摄入)                     │   │
│  │ - Claim Management (断言管理)                        │   │
│  │ - Source Management (来源管理)                       │   │
│  │ - TrustRank Calculation (信任度计算)                 │   │
│  └──────────────┬──────────────────────────────────────┘   │
│                 │                                           │
│                 │ 依赖                                      │
│                 ↓                                           │
│  ┌─────────────────────────────────────────────────────┐   │
│  │ Storage Layer (存储层)                               │   │
│  │ - Markdown Files (源真相)                            │   │
│  │ - SQLite Index (查询索引)                            │   │
│  └─────────────────────────────────────────────────────┘   │
│                                                             │
│  ┌─────────────────────────────────────────────────────┐   │
│  │ Module 7: Human Interface (人机交互)                 │   │
│  │ - Obsidian Integration (Markdown 编辑)               │   │
│  │ - CLI (命令行工具)                                    │   │
│  └─────────────────────────────────────────────────────┘   │
│                                                             │
│  ┌─────────────────────────────────────────────────────┐   │
│  │ Support Tools (辅助工具，可选失败)                    │   │
│  │ - scripts/semantic.py (语义搜索)                     │   │
│  │ - scripts/trustrank.py (TrustRank 计算)              │   │
│  │ - scripts/context_bundle.py (上下文加载)             │   │
│  │ - scripts/cues.py (健康检查)                         │   │
│  │ - scripts/pricing.py (成本分析)                      │   │
│  └─────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────┘
                    │
                    │ 集成
                    ↓
┌─────────────────────────────────────────────────────────────┐
│              Published Knowledge Layer                      │
│              (已发布知识层，外部系统)                         │
│                                                             │
│  来源：nashsu/llm_wiki                                       │
│  格式：Markdown Wiki 页面                                    │
│  位置：llm_wiki/wiki/ 目录                                   │
└─────────────────────────────────────────────────────────────┘
```

### 1.2 关键原则

**架构原则：**
1. ✅ **简洁性** — 3 个核心模块，职责清晰
2. ✅ **依赖单向** — 上层依赖下层，避免循环依赖
3. ✅ **Markdown 优先** — Markdown 是源真相，SQLite 是索引
4. ✅ **工具可选** — Support Tools 失败不影响核心流程
5. ✅ **人在环中** — 关键决策需要用户确认

**数据流原则：**
1. ✅ **写入路径** — User → Cognition Core → Knowledge Vault → Storage
2. ✅ **查询路径** — User → Cognition Core → Knowledge Vault → Storage
3. ✅ **摄入路径** — llm_wiki → File Watcher → Knowledge Vault → Storage

---

## 🎯 对齐检查点 1：系统总体架构

**请确认以下问题：**

### Q1.1: 系统边界是否清晰？

**我的理解：**
- ✅ **在系统内：** Cognition Core, Knowledge Vault, Storage, Human Interface
- ❌ **在系统外：** 知识生产（由 llm_wiki 负责）

**你的确认：**
- [ ] 同意这个边界划分
- [ ] 有异议（请说明）

---

### Q1.2: 三层依赖关系是否合理？

**依赖链：**
```
Cognition Core (业务逻辑)
    ↓ 依赖
Knowledge Vault (数据访问)
    ↓ 依赖
Storage Layer (持久化)
```

**具体例子：**
- Cognition Core 创建 Belief 时，需要调用 Knowledge Vault 获取 Claims
- Knowledge Vault 查询 Claims 时，需要调用 Storage Layer 读取数据
- Storage Layer 不依赖上层，只提供 CRUD 接口

**你的确认：**
- [ ] 同意这个依赖关系
- [ ] 有异议（请说明）

---

### Q1.3: Support Tools 的定位是否清晰？

**我的理解：**
- Support Tools 是"可选增强"，不是"核心依赖"
- 例如：semantic.py 失败 → 降级到关键词搜索
- 例如：trustrank.py 失败 → 使用默认 trust 值

**你的确认：**
- [ ] 同意 Support Tools 是可选的
- [ ] 不同意，Support Tools 应该是必需的

---

### Q1.4: 与 llm_wiki 的集成边界是否清晰？

**我的理解：**
- llm_wiki 负责：原始资料 → 结构化知识（Wiki 页面）
- 本系统负责：Wiki 页面 → Claims/Sources → Beliefs/Decisions

**集成方式：**
- File Watcher 监听 llm_wiki 的 wiki/ 目录
- HTTP API 查询和检索（可选，可降级）

**你的确认：**
- [ ] 同意这个集成方式
- [ ] 有异议（请说明）

---

## 📋 下一步

**请回答以上 4 个问题，然后我们进入：**

**第二层：Module 1 (Cognition Core) 详细设计**
- 内部组件
- 接口定义
- 数据流
- 与其他模块的交互

**进度：**
```
✅ 第一层：系统总体架构（当前）
⬜ 第二层：Module 1 (Cognition Core)
⬜ 第三层：Module 4 (Knowledge Vault)
⬜ 第四层：Storage Layer
⬜ 第五层：Module 7 (Human Interface)
⬜ 第六层：Support Tools
⬜ 第七层：集成层（llm_wiki, Obsidian）
⬜ 第八层：数据流和用例
```

---

**对齐方式：**
- 每一层我会提出 3-5 个具体问题
- 你确认或提出异议
- 确认无误后进入下一层
- 有异议时我们深入讨论直到对齐

**预计总时间：** 2-3 小时（完整对齐所有 8 层）

你准备好了吗？请回答上面的 4 个问题，我们开始！
