# 🚨 关键澄清：Wiki 软件名称与选择

**创建日期:** 2026-08-26 20:17  
**优先级:** P0（必须立即澄清）  
**状态:** 等待用户确认

---

## 问题描述

用户发现了一个严重的混淆点：

**用户质疑：**
> "你说的 LLMwiki 应该不是那个开源软件 github.com/nashsu/llm_wiki 吧？这样的话，wiki 格式不是会有冲突吧？wiki 软件名称要写清楚不然会出错"

**问题根源：**
- PRD 中大量提到 "nashsu/llm_wiki"
- 但没有明确说明这是否就是 GitHub 上的开源软件
- 也没有说明如果用户不用这个软件，应该怎么办

---

## 三种可能的情况

### 情况 A: 使用 nashsu/llm_wiki 开源软件 ✅

**描述：**
- 用户安装并使用 GitHub 上的 nashsu/llm_wiki
- Personal Intelligence System 集成这个软件

**架构：**
```
┌─────────────────────────────────────┐
│ Personal Intelligence System        │
│ (本次要设计的系统)                   │
└────────────┬────────────────────────┘
             │ 集成（File Watcher + API）
             ↓
┌─────────────────────────────────────┐
│ nashsu/llm_wiki                     │
│ (GitHub 开源软件)                    │
│ https://github.com/nashsu/llm_wiki  │
└────────────┬────────────────────────┘
             │ 生成
             ↓
┌─────────────────────────────────────┐
│ Wiki Pages (Markdown)               │
│ - python_asyncio.md                 │
│ - event_loop.md                     │
└─────────────────────────────────────┘
```

**优点：**
- ✅ nashsu/llm_wiki 已经实现了知识摄入功能
- ✅ 支持 PDF、视频、音频、网页等
- ✅ 有 HTTP API 可以调用
- ✅ PRD 中的集成方案可以直接使用

**缺点：**
- ❌ 依赖外部软件（需要安装和维护）
- ❌ 格式受限于 nashsu/llm_wiki 的输出

**是这种情况吗？**
- [ ] 是，我打算使用 nashsu/llm_wiki

---

### 情况 B: 自己做 Wiki 系统（不用 nashsu/llm_wiki）⚠️

**描述：**
- 用户不使用 nashsu/llm_wiki
- 自己实现一个 Wiki 知识管理系统

**架构：**
```
┌─────────────────────────────────────┐
│ Personal Intelligence System        │
│ (本次要设计的系统)                   │
└────────────┬────────────────────────┘
             │ 集成
             ↓
┌─────────────────────────────────────┐
│ 你自己的 Wiki 系统                   │
│ (名称待定，格式待定)                 │
└────────────┬────────────────────────┘
             │ 生成
             ↓
┌─────────────────────────────────────┐
│ Wiki Pages (格式待定)                │
└─────────────────────────────────────┘
```

**需要重新定义：**
1. Wiki 系统的名称（建议避免 "llm_wiki" 以免混淆）
2. Wiki 页面的格式规范
3. 集成接口（如何从 Wiki 系统获取数据）
4. 知识摄入功能（如何处理 PDF、视频等）

**工作量：**
- 需要实现知识摄入功能（PDF 解析、视频转录等）
- 需要设计 Wiki 格式
- 需要实现 Wiki 管理功能

**是这种情况吗？**
- [ ] 是，我要自己做一个 Wiki 系统

---

### 情况 C: 使用其他 Wiki 工具（Obsidian, Notion 等）⚠️

**描述：**
- 用户使用现有的笔记/Wiki 工具
- Personal Intelligence System 集成这些工具

**常见选择：**
- Obsidian（Markdown，本地）
- Notion（云端）
- Logseq（Markdown，本地）
- Roam Research（云端）

**需要适配：**
- 格式可能不同
- 无法直接处理 PDF、视频等（需要手动或其他工具）

**是这种情况吗？**
- [ ] 是，我要用其他工具（请说明）

---

## 推荐方案对比

| 方案 | 工作量 | 功能完整性 | 维护成本 | 推荐度 |
|------|--------|-----------|---------|--------|
| **使用 nashsu/llm_wiki** | ⭐ 低 | ⭐⭐⭐ 高 | ⭐⭐ 中 | ⭐⭐⭐ |
| **自己做 Wiki 系统** | ⭐⭐⭐ 高 | ⭐⭐⭐ 可定制 | ⭐⭐⭐ 高 | ⭐ |
| **使用其他工具** | ⭐⭐ 中 | ⭐⭐ 中 | ⭐ 低 | ⭐⭐ |

---

## 我的推荐

### 🏆 推荐：使用 nashsu/llm_wiki（情况 A）

**理由：**
1. ✅ 功能完整（PDF、视频、音频、网页）
2. ✅ 有 HTTP API 可以集成
3. ✅ 开源免费
4. ✅ 可以降低 Personal Intelligence System 的复杂度

**实施步骤：**
1. 安装 nashsu/llm_wiki
2. 配置输出目录
3. Personal Intelligence System 监听该目录
4. 提取 Claims 并建立 Beliefs

**名称约定（避免混淆）：**
- **知识生产软件：** nashsu/llm_wiki（开源软件）
- **认知管理系统：** Personal Intelligence System（本次设计的系统）
- **输出格式：** Wiki Pages（Markdown 文件）

---

## 立即需要确认的问题

**请回答以下问题：**

### Q1: 你打算使用哪种方案？

**A. 使用 nashsu/llm_wiki 开源软件** → PRD 基本不需要改

**B. 自己做 Wiki 系统** → 需要重新定义很多东西

**C. 使用其他工具（如 Obsidian）** → 需要设计适配器

**D. 还不确定** → 我们可以继续讨论

---

### Q2: 如果选择 A（使用 nashsu/llm_wiki），格式会冲突吗？

**我的理解：**
- nashsu/llm_wiki 输出的是标准 Markdown 文件
- Personal Intelligence System 读取这些 Markdown 文件
- 提取其中的 Claims（断言）
- **不会冲突**，因为两个系统处理的是不同层次的内容

**数据流：**
```
原始资料（PDF, 视频）
    ↓ nashsu/llm_wiki 处理
Wiki Page (Markdown)
    - 标题
    - 正文
    - 引用
    ↓ Personal Intelligence System 处理
Claims (提取的断言)
    - claim_001: "Python asyncio 适合 I/O 密集型任务"
    - claim_002: "Event Loop 是 asyncio 的核心"
```

**你觉得会冲突吗？如果会，具体是什么冲突？**

---

### Q3: 关于名称规范

**为避免混淆，我建议：**

**在文档中使用全称：**
- ✅ "nashsu/llm_wiki（开源知识管理软件）"
- ❌ "llm_wiki"（容易混淆）

**在代码中使用明确的变量名：**
```python
# ✅ 清晰
NASHSU_LLMWIKI_OUTPUT_DIR = "/path/to/nashsu/llm_wiki/output"
llm_wiki_client = LlmWikiClient()

# ❌ 容易混淆
WIKI_DIR = "/path/to/wiki"
wiki = Wiki()
```

**你同意这个命名规范吗？**

---

## 下一步

**请回答 Q1、Q2、Q3，然后我们：**

1. 如果是情况 A → 继续第二层对齐（Module 1 详细设计）
2. 如果是情况 B → 重新定义 Wiki 系统规范
3. 如果是情况 C → 设计适配器方案

---

**创建时间:** 2026-08-26 20:17  
**状态:** 🔴 阻塞中，等待用户确认  
**紧急程度:** P0（影响整个架构设计）
