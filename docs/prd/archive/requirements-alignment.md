# 需求对齐文档 — Personal Intelligence System

**日期:** 2026-08-26  
**状态:** 需求对齐阶段  
**目标:** 明确需求，避免重复造轮子

---

## 🎯 你的核心需求（原话）

> "Atelierr 改制（尽量改动小并单独作为一个可以拆解解耦的模块）与其他模块和起来形成一套完整的个人认知与智能系统，要求系统每个模块之间运行可靠，相互之间可以解耦，最好有独立开源软件支持，减少开发量，另外希望可以支持前端页面，方便我在异地使用。"

---

## 📊 需求拆解与理解

### 1. Atelierr 的定位

**Atelierr 现状（已读取）:**
- ✅ 已有完整的反思系统
- ✅ Local-first，基于 Markdown
- ✅ L1-L5 知识分层架构
- ✅ TrustRank 信任引擎
- ✅ 15 个专业 AI 智能体（le cercle）
- ✅ 完整的脚本工具集（`scripts/`）
- ✅ 支持 Codex 和 Claude Code

**你的要求:**
- ✅ **Atelierr 改制** — 尽量改动小
- ✅ **作为独立模块** — 可拆解、可解耦
- ✅ **与其他模块组合** — 形成完整系统

---

### 2. "完整的个人认知与智能系统" 的构成

根据之前的 PRD v0.2，你想要的是：

**核心闭环:** KNOW → THINK → ACT → LEARN

**管理的实体:**
- **Beliefs（信念）** — 基于证据的信念
- **Questions（问题）** — 待解决的问题
- **Decisions（决策）** — 决策记录与追踪

**Atelierr 已有的能力（可直接复用）:**
- ✅ L1-L5 知识分层
- ✅ TrustRank 引擎（信任传播）
- ✅ `scripts/semantic.py`（语义搜索）
- ✅ `scripts/context_bundle.py`（上下文加载）
- ✅ `scripts/cues.py`（健康检查）
- ✅ Wiki Schema（结构化知识）

**Atelierr 缺失的能力（需要新增）:**
- ❌ Belief Management（信念管理）
- ❌ Question Tracking（问题追踪）
- ❌ Decision Tracking（决策追踪）
- ❌ 基于 Belief 的 Confidence 计算

---

### 3. 模块化与解耦要求

你要求：
- ✅ **模块之间运行可靠**
- ✅ **相互之间可以解耦**
- ✅ **最好有独立开源软件支持**

**我的理解:**

```
┌─────────────────────────────────────────────────────────┐
│              Personal Intelligence System                │
│           (完整的个人认知与智能系统)                      │
└───────────────────┬─────────────────────────────────────┘
                    │
        ┌───────────┴───────────┬─────────────────────┬───────────────────┐
        │                       │                     │                   │
┌───────▼───────┐     ┌─────────▼─────────┐  ┌───────▼───────┐  ┌───────▼───────┐
│  Module 1:    │     │   Module 2:       │  │  Module 3:    │  │  Module 4:    │
│  Atelierr     │     │   Cognition Core  │  │  llm_wiki     │  │  Web Frontend │
│  (改制版)      │     │   (新增)          │  │  (开源)        │  │  (新增)        │
└───────┬───────┘     └─────────┬─────────┘  └───────┬───────┘  └───────┬───────┘
        │                       │                     │                   │
        │   提供:                │   提供:             │   提供:            │   提供:
        │   - L1-L5 分层        │   - Belief 管理     │   - 知识生产       │   - 可视化界面
        │   - TrustRank        │   - Question 追踪   │   - PDF/Office    │   - 异地访问
        │   - Wiki Schema      │   - Decision 追踪   │   - Web Clipper   │   - API 接口
        │   - 语义搜索          │   - Confidence 计算 │   - 向量检索      │
        │   - 15 个 AI 智能体   │                     │                   │
        └───────────────────────┴─────────────────────┴───────────────────┘
```

---

### 4. 独立开源软件支持

**已确定可用的开源软件:**

| 组件 | 开源软件 | 状态 | 用途 |
|------|---------|------|------|
| **知识生产** | [nashsu/llm_wiki](https://github.com/nashsu/llm_wiki) | ✅ 已调研 | PDF/Office/EPUB/图片 → 结构化知识 |
| **向量检索** | LanceDB | ✅ Atelierr 已用 | 语义搜索 |
| **嵌入模型** | BGE-M3 | ✅ Atelierr 已用 | 文本向量化 |
| **Web 框架** | FastAPI | 🟡 待选择 | 后端 API |
| **前端框架** | React / Vue | 🟡 待选择 | Web UI |
| **笔记编辑** | Obsidian | ✅ Atelierr 已用 | Markdown 编辑 |

---

### 5. Web 前端支持（异地访问）

你要求：
- ✅ **支持前端页面**
- ✅ **方便在异地使用**

**方案建议:**

```
┌──────────────────────────────────────────┐
│          Web Frontend                     │
│          (React/Vue)                      │
│   - Belief/Question/Decision 可视化      │
│   - 知识图谱展示                           │
│   - TrustRank 可视化                      │
└──────────────┬───────────────────────────┘
               │ HTTP/WebSocket
┌──────────────▼───────────────────────────┐
│          FastAPI Backend                  │
│   - RESTful API                           │
│   - WebSocket (实时更新)                  │
│   - 认证/授权                              │
└──────────────┬───────────────────────────┘
               │
┌──────────────▼───────────────────────────┐
│       Personal Intelligence System        │
│   (Atelierr + Cognition Core)            │
│   - Markdown 文件读写                      │
│   - SQLite 索引查询                        │
└───────────────────────────────────────────┘
```

**部署方案:**
- ✅ **VPS 部署** — 通过 Tailscale 内网访问
- ✅ **本地部署** — 在你的主机上运行，浏览器访问
- ✅ **混合部署** — 核心在本地，Web 服务在 VPS

---

## 🏗️ 架构设计方案（基于你的需求）

### 方案 A: 最小改动方案（推荐）

**核心思路:** Atelierr 保持原样，增加一个 L3.5 Cognition Layer

```
Atelierr (现有)
├── L4 — Wiki (不变)
├── L3.5 — Cognition (新增) ← Beliefs/Questions/Decisions
├── L3 — Papers (不变)
├── L2 — Working notes (不变)
└── L1 — Raw capture (不变)
```

**改动:**
- ✅ **最小** — 只在 `$OV/` 下新增 `cognition/` 目录
- ✅ **解耦** — Cognition Layer 可以独立删除
- ✅ **复用** — 直接使用 Atelierr 的所有能力

**新增文件:**
```
$OV/
├── cognition/           # 新增
│   ├── beliefs/         # 信念
│   ├── questions/       # 问题
│   └── decisions/       # 决策
└── .index/              # 新增（SQLite 索引）
    └── cognition.db
```

**新增脚本:**
```
scripts/
├── belief.py            # 新增 — Belief 管理
├── question.py          # 新增 — Question 追踪
├── decision.py          # 新增 — Decision 追踪
└── cognition_sync.py    # 新增 — 同步 Markdown ↔ SQLite
```

---

### 方案 B: 独立模块方案

**核心思路:** Atelierr 作为一个库被调用

```
personal-intelligence-system/
├── atelierr/            # Git submodule（Atelierr 原仓库）
│   ├── scripts/         # 作为库使用
│   └── protocols/       # 作为库使用
├── cognition_core/      # 新增 — 认知核心
│   ├── belief.py
│   ├── question.py
│   └── decision.py
├── web_api/             # 新增 — FastAPI 后端
│   ├── main.py
│   └── routes/
└── web_frontend/        # 新增 — React 前端
    ├── src/
    └── public/
```

**调用方式:**
```python
# cognition_core/belief.py
from atelierr.scripts import trustrank, semantic

class BeliefManager:
    def __init__(self):
        self.trustrank = trustrank.TrustRank()
        self.semantic = semantic.SemanticSearch()
    
    def calculate_confidence(self, claims):
        # 使用 Atelierr 的 TrustRank
        return self.trustrank.calculate(claims)
```

**改动:**
- ✅ **解耦** — Atelierr 完全独立
- ✅ **灵活** — 可以选择性使用 Atelierr 的能力
- ⚠️ **复杂** — 需要维护 Git submodule

---

## 🔄 与 nashsu/llm_wiki 的集成

根据之前的调研（P0-resolution.md），llm_wiki 的能力：

**已验证:**
- ✅ HTTP API（`http://127.0.0.1:19828/api/v1`）
- ✅ Web Clipper（Chrome Extension）
- ✅ PDF/Office/EPUB/图片处理
- ✅ 向量检索（LanceDB）
- ✅ 知识图谱（Wikilinks）

**集成方式:**

```
llm_wiki (知识生产)
   ↓ File Watcher 监听 wiki/ 目录
Atelierr (知识存储 + 信任传播)
   ↓ 提供 TrustRank 和语义搜索
Cognition Core (认知管理)
   ↓ 提供 Belief/Question/Decision 管理
Web Frontend (可视化)
```

---

## 📋 具体实施建议

### 阶段 1: 最小可用原型（1-2 周）

**目标:** 验证架构可行性

1. ✅ **扩展 Atelierr**（方案 A）
   - 在 `$OV/` 下新增 `cognition/` 目录
   - 新增 `scripts/belief.py`
   - 实现最简单的 Belief CRUD

2. ✅ **集成 llm_wiki**
   - 使用 File Watcher 监听 llm_wiki 的 `wiki/` 目录
   - 自动摄入到 Atelierr 的 L4 Wiki

3. ✅ **简单的 CLI 工具**
   - `python scripts/belief.py create "Python asyncio 适合 I/O 密集型任务"`
   - `python scripts/belief.py list`

**验收标准:**
- ✅ 可以创建 Belief
- ✅ Belief 自动计算 Confidence（基于 TrustRank）
- ✅ llm_wiki 生成的知识自动摄入

---

### 阶段 2: Web 前端（2-3 周）

**目标:** 实现异地访问

1. ✅ **FastAPI 后端**
   - RESTful API（CRUD Beliefs/Questions/Decisions）
   - WebSocket（实时更新）
   - 认证/授权（JWT）

2. ✅ **React 前端**
   - Belief/Question/Decision 列表
   - 知识图谱可视化（使用 D3.js）
   - TrustRank 可视化

3. ✅ **部署**
   - Docker Compose（后端 + 前端）
   - Tailscale 内网访问

**验收标准:**
- ✅ 可以在浏览器中查看 Beliefs
- ✅ 可以在手机上访问
- ✅ 实时同步（编辑 Markdown 文件后前端自动更新）

---

### 阶段 3: 完善功能（3-4 周）

**目标:** 完整的 KNOW → THINK → ACT → LEARN 循环

1. ✅ **Question Tracking**
2. ✅ **Decision Tracking**
3. ✅ **Learning Agenda**
4. ✅ **自动化 Confidence 更新**

---

## ❓ 需要你确认的问题

### Q1: 架构方案选择

**你倾向于哪个方案？**

- **方案 A（最小改动）** — 在 Atelierr 中新增 L3.5 Cognition Layer
- **方案 B（独立模块）** — Atelierr 作为 Git submodule 被调用

**我的推荐:** 方案 A（最小改动），理由：
- ✅ 改动最小
- ✅ 直接复用 Atelierr 的所有能力
- ✅ 实施最快

---

### Q2: 现有 Atelierr 数据

**你现在有没有 `$OV/` 目录？**

- ✅ **有** — 已经在使用 Atelierr
- ❌ **没有** — 这是第一次使用

**如果有，里面有多少数据？**
- 这决定了我们是否需要迁移脚本

---

### Q3: Web 前端优先级

**Web 前端的优先级有多高？**

- **P0（最高）** — 没有 Web 就没法用
- **P1（重要）** — 先做核心功能，Web 可以后做
- **P2（可选）** — 有 CLI 就够了

**我的推荐:** P1（先做核心功能），理由：
- ✅ 先验证 Cognition Layer 的价值
- ✅ Web 前端开发量大，后做更稳妥

---

### Q4: llm_wiki 使用情况

**你现在有没有在用 llm_wiki？**

- ✅ **有** — 已经在用，有数据
- ❌ **没有** — 准备开始用

---

### Q5: 部署环境

**你希望系统部署在哪里？**

- **选项 1:** 本地（你的主机）
- **选项 2:** VPS（云服务器）
- **选项 3:** 混合（核心在本地，Web 在 VPS）

---

### Q6: 数据存储位置

**`$OV/` 目录希望放在哪里？**

- **选项 1:** Google Drive（自动同步）
- **选项 2:** iCloud
- **选项 3:** 本地文件夹（手动备份）
- **选项 4:** Git 仓库（版本控制）

---

## 🎯 下一步行动

**请你回答上面的 6 个问题，然后我会：**

1. ✅ 创建详细的技术规范文档
2. ✅ 搭建项目结构
3. ✅ 开始实施阶段 1（最小可用原型）

---

**创建时间:** 2026-08-26  
**状态:** 等待你的反馈  
**预计阅读时间:** 10 分钟
