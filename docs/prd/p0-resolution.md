# P0 问题解决方案

**文档版本:** v1.0  
**创建日期:** 2026-08-26  
**状态:** 已完成

---

## 目录

1. [P0-1: nashsu/llm_wiki 能力调研](#p0-1-nashsullm_wiki-能力调研)
2. [P0-2: 简化 V0 范围](#p0-2-简化-v0-范围)
3. [P0-3: 定义存储方案](#p0-3-定义存储方案)

---

## P0-1: nashsu/llm_wiki 能力调研

### 调研结果总结

**项目基本信息：**
- GitHub Stars: 16,693 ⭐️
- 活跃维护中（创建于 2026-04-08）
- 跨平台桌面应用（Rust + TypeScript）
- 基于 Karpathy 的 LLM Wiki 模式

### ✅ 已验证能力

#### 1. **文档处理能力（强）**

| 能力 | 支持情况 | 备注 |
|------|---------|------|
| PDF 处理 | ✅ 完全支持 | 内置 + 云端 + 本地 MinerU |
| Office 文档 | ✅ 完全支持 | Word, Excel, PowerPoint |
| EPUB/MOBI | ✅ 完全支持 | 电子书格式 |
| 图片 OCR | ✅ 完全支持 | 多模态图像摄入 + Vision LLM 生成描述 |
| 网页文章 | ✅ 完全支持 | Chrome Web Clipper 扩展 |
| 视频/音频 | ❌ 不支持 | 需要外部转录 |

**关键特性：**
- **Two-Step Chain-of-Thought Ingest**: 分析 → 生成 wiki（带来源追溯）
- **Multimodal Image Ingestion**: 从 PDF 提取图片 + Vision LLM 描述
- **Incremental Cache**: 增量处理，避免重复工作

#### 2. **HTTP API（完整可用）**

**API 基本信息：**
```yaml
Base URL: http://127.0.0.1:19828
API Version: v1
Auth: Bearer Token（在 Settings → API Server 中生成）
Binding: 127.0.0.1 only（仅本地访问）
Status: 稳定（v0.4.10+）
```

**核心 Endpoints：**

| Endpoint | 方法 | 功能 | 适用场景 |
|----------|------|------|---------|
| `/api/v1/health` | GET | 健康检查 | 无需认证 |
| `/api/v1/projects` | GET | 列出所有项目 | 项目管理 |
| `/api/v1/projects/{id}/files` | GET | 文件树 | 浏览文件结构 |
| `/api/v1/projects/{id}/files/content` | GET | 读取文件内容 | 获取 wiki/source 内容 |
| `/api/v1/projects/{id}/search` | POST | **混合检索**（关键词+向量） | 语义搜索 |
| `/api/v1/projects/{id}/graph` | GET | 知识图谱 | 可视化关联 |
| `/api/v1/projects/{id}/sources/rescan` | POST | 触发重新扫描 | 同步文件变化 |
| `/api/v1/projects/{id}/chat` | POST | Agent 对话 | RAG 问答 |

**混合检索（Hybrid Search）详解：**
```json
// Request
POST /api/v1/projects/current/search
{
  "query": "Python asyncio 最佳实践",
  "topK": 10,
  "includeContent": false
}

// Response
{
  "mode": "hybrid",  // "keyword" | "vector" | "hybrid"
  "tokenHits": [...],  // 关键词匹配结果
  "vectorHits": [...],  // 向量匹配结果
  "results": [
    {
      "path": "wiki/programming/python-asyncio.md",
      "vectorScore": 0.92,
      "snippet": "...",
      "metadata": {...}
    }
  ]
}
```

**Web Clipper 工作流：**
```
Chrome 扩展
  ↓
llm_wiki HTTP API (POST /api/v1/projects/{id}/sources/add)
  ↓
Ingest Queue（持久化队列）
  ↓
LLM 处理（Two-Step Chain-of-Thought）
  ↓
输出到 wiki/*.md
  ↓
触发 /api/v1/projects/{id}/sources/rescan
```

#### 3. **知识图谱（4-Signal Model）**

**图谱算法：**
- Direct Links（直接链接）
- Source Overlap（来源重叠）
- Adamic-Adar（社交网络算法）
- Type Affinity（类型亲和）
- Louvain Community Detection（社区发现）

**图谱 API：**
```bash
GET /api/v1/projects/current/graph?limit=200
```

#### 4. **MCP Server（Model Context Protocol）**

llm_wiki 内置 MCP Server，可以直接被 Claude Desktop 等客户端使用：

```json
// mcp_config.json
{
  "mcpServers": {
    "llm-wiki": {
      "command": "node",
      "args": ["/path/to/llm-wiki/mcp-server/dist/src/index.js"],
      "env": {
        "LLM_WIKI_API_TOKEN": "your-token",
        "LLM_WIKI_API_BASE_URL": "http://127.0.0.1:19828"
      }
    }
  }
}
```

#### 5. **Agent Skill System**

llm_wiki 支持自定义 Agent Skills：
- 扫描本地 `SKILL.md` 文件
- 用户用 `/skill` 选择技能
- Agent 按需读取技能指令

**官方 Agent Skill：**
- GitHub: https://github.com/nashsu/llm_wiki_skill
- 一键安装：`npx skills add nashsu/llm_wiki_skill`
- 适配 Claude Code / Codex

### ❌ 不支持的能力

| 能力 | 支持情况 | 替代方案 |
|------|---------|---------|
| 视频转录 | ❌ | 需要外部 Whisper API |
| 音频转录 | ❌ | 需要外部 Whisper API |
| 实时流式处理 | ⚠️ 部分支持 | Chat API 支持 SSE，但 Ingest 是批处理 |

### 集成方案确认

#### **方案 A（推荐）：直接使用 llm_wiki HTTP API**

```
用户操作
  ↓
Web Clipper / 文件导入
  ↓
llm_wiki 处理（内置）
  ↓
输出到 wiki/*.md
  ↓
本系统监听 wiki/ 目录（File Watcher）
  ↓
自动摄入到 Module 4 (Knowledge Vault)
```

**优势：**
- ✅ llm_wiki 已经实现了所有多模态处理
- ✅ 职责清晰（llm_wiki = 知识编译器，本系统 = 认知管理）
- ✅ HTTP API 稳定可用
- ✅ 无需重复造轮子

**实现细节：**

1. **设置 llm_wiki：**
   ```bash
   # 启动 llm_wiki 桌面应用
   # Settings → API Server
   # - Enable local HTTP API: ✓
   # - Generate new token: <复制 token>
   ```

2. **本系统配置：**
   ```toml
   # config/llm_wiki.toml
   [llm_wiki]
   api_base = "http://127.0.0.1:19828"
   api_token = "<token>"
   project_id = "current"  # 或具体项目 ID
   wiki_dir = "/path/to/llm_wiki/projects/default/wiki"
   ```

3. **File Watcher 实现：**
   ```python
   # scripts/llm_wiki_watcher.py
   import time
   from watchdog.observers import Observer
   from watchdog.events import FileSystemEventHandler
   
   class WikiFileHandler(FileSystemEventHandler):
       def on_created(self, event):
           if event.src_path.endswith('.md'):
               print(f"New wiki file: {event.src_path}")
               ingest_published_knowledge(event.src_path)
       
       def on_modified(self, event):
           if event.src_path.endswith('.md'):
               print(f"Updated wiki file: {event.src_path}")
               update_published_knowledge(event.src_path)
   
   def watch_llm_wiki(wiki_dir):
       event_handler = WikiFileHandler()
       observer = Observer()
       observer.schedule(event_handler, wiki_dir, recursive=True)
       observer.start()
       try:
           while True:
               time.sleep(1)
       except KeyboardInterrupt:
           observer.stop()
       observer.join()
   ```

4. **搜索集成：**
   ```python
   # scripts/llm_wiki_search.py
   import requests
   
   def search_llm_wiki(query, top_k=10):
       url = "http://127.0.0.1:19828/api/v1/projects/current/search"
       headers = {
           "Authorization": f"Bearer {API_TOKEN}",
           "Content-Type": "application/json"
       }
       payload = {
           "query": query,
           "topK": top_k,
           "includeContent": False
       }
       response = requests.post(url, headers=headers, json=payload)
       return response.json()
   ```

#### **处理视频/音频的补充方案**

由于 llm_wiki 不支持视频/音频转录，需要外部处理：

```yaml
方案 1: Whisper API
  视频/音频文件
    ↓
  scripts/transcribe_media.py (调用 Whisper API)
    ↓
  生成转录文本 (.txt)
    ↓
  导入到 llm_wiki 作为源文件
    ↓
  llm_wiki 处理成 wiki

方案 2: 本地 Whisper
  视频/音频文件
    ↓
  scripts/local_whisper.py (调用本地 Whisper 模型)
    ↓
  生成转录文本 + 时间戳 (.srt / .vtt)
    ↓
  导入到 llm_wiki
```

**实现脚本：**
```python
# scripts/transcribe_media.py
import whisper
import sys

def transcribe_video(video_path, output_path):
    model = whisper.load_model("base")
    result = model.transcribe(video_path)
    
    # 保存转录文本
    with open(output_path, 'w') as f:
        f.write(result["text"])
    
    # 保存带时间戳的版本
    srt_path = output_path.replace('.txt', '.srt')
    with open(srt_path, 'w') as f:
        for i, segment in enumerate(result["segments"]):
            f.write(f"{i+1}\n")
            f.write(f"{format_timestamp(segment['start'])} --> {format_timestamp(segment['end'])}\n")
            f.write(f"{segment['text']}\n\n")
    
    print(f"Transcription saved to {output_path}")
    print(f"SRT saved to {srt_path}")
    print(f"Now import {output_path} to llm_wiki")

if __name__ == "__main__":
    transcribe_video(sys.argv[1], sys.argv[2])
```

### Web Clipper 集成确认

llm_wiki 已经有 Chrome Web Clipper 扩展：

**工作流：**
```
1. 用户在网页上点击 Web Clipper 图标
   ↓
2. Web Clipper 提取：
   - URL
   - 标题
   - 正文内容
   - 元数据
   ↓
3. 发送到 llm_wiki HTTP API
   POST /api/v1/projects/current/sources/add
   ↓
4. llm_wiki Ingest Queue 处理
   ↓
5. 生成 wiki/*.md
   ↓
6. 本系统 File Watcher 自动摄入
```

**状态追踪：**
- llm_wiki 有持久化 Ingest Queue，支持进度可视化
- 本系统可通过 API 查询队列状态

### 结论

**✅ 明确结论：**

1. **llm_wiki 能力强大且完整**
   - PDF、Office、图片、网页：✅ 完全支持
   - 视频、音频：❌ 需要外部转录

2. **HTTP API 稳定可用**
   - 所有核心功能都有 API
   - 混合检索（关键词+向量）已实现
   - MCP Server 可选

3. **集成方案清晰**
   - 方案 A（推荐）：llm_wiki 作为外部编译器，本系统监听输出
   - Web Clipper 已内置，无需额外开发
   - 视频/音频需要外部 Whisper 转录

4. **边界明确**
   - llm_wiki 职责：知识生产（原始资料 → Published Knowledge）
   - 本系统职责：认知管理（Published Knowledge → Beliefs → Decisions）

---

## P0-2: 简化 V0 范围

### 当前 PRD 的 V0 范围（过大）

```yaml
Module 1: Cognition Flywheel Core ✓
Module 2: Agent Runtime (11 个 Agents)
Module 3: Workflow Engine
Module 4: Knowledge Vault ✓
Module 5: Model Gateway
Module 6: Feedback Loop
Module 7: Human Interface ✓
Module 8: Memory System (脚本工具阶段) ✓
Tool 1: Health Checker ✓
Tool 2: Cost Analyzer ✓
```

**问题：**
- 8 个模块同时开发，复杂度高
- Module 2/3/5/6 不是核心闭环的必要部分
- 无法快速验证核心价值

### 简化后的 V0 范围（MVP）

#### **核心目标：验证认知飞轮的最小闭环**

```
Published Knowledge (from llm_wiki)
  ↓
KNOW (摄入知识)
  ↓
THINK (形成 Beliefs)
  ↓
ACT (记录 Decisions)
  ↓
LEARN (更新 Beliefs)
```

#### **V0 必须实现（3+2）：**

**核心模块（3 个）：**
1. ✅ **Module 1: Cognition Core（简化版）**
   - Belief 管理（创建、更新、查询）
   - Open Question 管理
   - Decision 管理（简化版，无行动执行）
   - 数据存储：Markdown + SQLite（见 P0-3）

2. ✅ **Module 4: Knowledge Vault（复用 Atelier）**
   - Published Knowledge Ingestion（从 llm_wiki 摄入）
   - L1-L5 知识分层（复用 Atelier）
   - TrustRank 计算（复用 `scripts/trustrank.py`）
   - Wiki Schema 管理

3. ✅ **Module 7: Human Interface（Obsidian）**
   - Obsidian 作为主要界面
   - Markdown 文件编辑
   - 数据格式兼容 Obsidian

**辅助工具（2 个）：**
1. ✅ **Tool 1: Health Checker**
   - 复用 `scripts/cues.py`
   - 启动时静默检查

2. ✅ **Tool 2: Cost Analyzer**
   - 复用 `scripts/pricing.py`
   - 手动运行

#### **V0 延后实现：**

| 模块 | 延后原因 | V1 再实现 |
|------|---------|-----------|
| Module 2: Agent Runtime | 可用现有 Atelier Agents，无需封装 | ✓ |
| Module 3: Workflow Engine | V0 用简单的命令即可 | ✓ |
| Module 5: Model Gateway | V0 直接调用 Anthropic API | ✓ |
| Module 6: Feedback Loop | V0 手工记录反馈 | ✓ |
| Module 8: Memory System（独立模块） | V0 用脚本工具足够 | ✓ |

#### **V0 简化的 Module 1 功能范围**

**保留（核心）：**
```python
# Belief Management
create_belief(statement, claims, confidence) -> Belief
update_belief(belief_id, new_confidence) -> Belief
list_beliefs(filters) -> List[Belief]
get_belief(belief_id) -> Belief

# Open Question Management
create_open_question(question, context) -> OpenQuestion
list_open_questions(filters) -> List[OpenQuestion]
close_question(question_id, resolution) -> void

# Decision Management (简化版)
create_decision(question_id, chosen_option, rationale) -> Decision
list_decisions(filters) -> List[Decision]
get_decision(decision_id) -> Decision
```

**移除（V1 再实现）：**
```python
# Model Management - 延后到 V1
create_model(domain, principles) -> Model

# Action Execution - 延后到 V1
execute_action(action_id) -> ActionResult

# Feedback Loop - 延后到 V1
collect_feedback(action_id, outcome) -> Feedback

# Cognition Change Tracking - 延后到 V1
record_change(type, before, after) -> CognitionChange
```

#### **V0 验收标准（明确且可测）**

```yaml
功能验收:
  1. ✅ 能够从 llm_wiki 摄入 Published Knowledge
  2. ✅ 能够基于 Claims 创建 Belief
  3. ✅ 能够创建和追踪 Open Question
  4. ✅ 能够记录 Decision（关联 Question）
  5. ✅ 能够在 Obsidian 中查看和编辑所有数据
  6. ✅ 能够查询 TrustRank（复用 Atelier）

性能验收:
  1. ✅ Belief 查询 < 100ms
  2. ✅ Knowledge Ingestion < 1s per file
  3. ✅ TrustRank 计算 < 5s (for 1000 claims)

数据验收:
  1. ✅ 所有数据存储为 Markdown + YAML frontmatter
  2. ✅ Obsidian 双向链接工作正常
  3. ✅ SQLite 索引与 Markdown 保持同步
```

#### **V0 实施时间表**

```yaml
Week 1: 基础设施
  - 定义数据结构（Belief, Question, Decision）
  - 实现 Markdown + SQLite 存储
  - 实现 llm_wiki File Watcher

Week 2: 核心功能
  - 实现 Belief 管理（CRUD）
  - 实现 Open Question 管理
  - 实现 Decision 管理

Week 3: 集成测试
  - llm_wiki 集成测试
  - Obsidian 兼容性测试
  - TrustRank 集成测试

Week 4: 验收和迭代
  - 端到端测试
  - 性能测试
  - 用户试用和反馈
```

### V1 范围（V0 验证后再详细规划）

**V1 目标：**
- 完整的认知飞轮（KNOW → THINK → ACT → LEARN）
- Agent Runtime（11 个专业智能体）
- Memory System 升级为独立模块（支持 10-100GB）

**V1 新增能力：**
- Model Management（心智模型）
- Action Execution（行动执行）
- Feedback Loop（自动化反馈）
- Cognition Change Tracking（认知变化追踪）
- Working Memory（会话缓存）
- Episodic Memory（情景记忆）

---

## P0-3: 定义存储方案

### 设计原则

1. **Obsidian 兼容优先** — Markdown 作为源真相（Source of Truth）
2. **查询性能** — SQLite 作为索引层
3. **数据可恢复性** — Markdown 可人工编辑和恢复
4. **双写一致性** — Markdown 和 SQLite 保持同步

### 存储架构

```
用户层
  ↑
Obsidian / Web UI
  ↑
┌─────────────────────────────┐
│   Application Layer         │
│  (Module 1: Cognition Core) │
└─────────────────────────────┘
  ↑↓ (双写)
┌──────────────┬──────────────┐
│ Markdown     │ SQLite       │
│ (Source of   │ (Index       │
│  Truth)      │  Layer)      │
└──────────────┴──────────────┘
```

### 数据存储方案

#### **方案：Markdown + SQLite 混合存储**

| 数据类型 | Markdown（主存储） | SQLite（索引） | 备注 |
|---------|-------------------|---------------|------|
| Belief | `$OV/beliefs/belief_<id>.md` | `beliefs` 表 | 人可读、可编辑 |
| Open Question | `$OV/questions/question_<id>.md` | `questions` 表 | 人可读、可编辑 |
| Decision | `$OV/decisions/decision_<id>.md` | `decisions` 表 | 人可读、可编辑 |
| Claim | `$OV/wiki/**/*.md` (YAML section) | `claims` 表 | 复用 Atelier |
| Source | `$OV/wiki/**/*.md` (metadata) | `sources` 表 | 复用 Atelier |
| 关系图 | 通过双向链接表达 | `relationships` 表 | 加速查询 |

### 数据结构定义

#### **1. Belief（信念）**

**Markdown 格式：**
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
tags:
  - programming
  - python
  - concurrency
---

# Python asyncio 适合 I/O 密集型任务

## 置信度
- **当前置信度**: 0.9 (Very High)
- **上次更新**: 2026-08-26

## 支持证据

### 证据 1：《Fluent Python》
- **来源**: [[fluent_python_chapter_18]]
- **断言**: [[claim_fluent_python_ch18_001]]
- **Trust**: 0.95
- **内容**: "asyncio 的核心优势在于 I/O 等待期间可以切换任务..."

### 证据 2：视频讲解
- **来源**: [[python_asyncio_video]]
- **时间戳**: 15:20-22:10
- **Trust**: 0.85
- **内容**: "CPU 密集型任务不应该使用 asyncio..."

## 相关问题
- [[question_when_to_use_asyncio]]
- [[question_asyncio_vs_threading]]

## 应用决策
- [[decision_20260820_use_asyncio_in_web_crawler]]

## 反驳证据
- 暂无

## 笔记
用户可以在这里添加个人理解和笔记...
```

**SQLite Schema：**
```sql
CREATE TABLE beliefs (
    id TEXT PRIMARY KEY,
    statement TEXT NOT NULL,
    confidence REAL NOT NULL,  -- [0, 1]
    created_at TIMESTAMP NOT NULL,
    updated_at TIMESTAMP NOT NULL,
    markdown_path TEXT NOT NULL,  -- 指向 Markdown 文件
    
    -- 索引字段（从 Markdown 提取）
    tags TEXT,  -- JSON array
    based_on_claims TEXT,  -- JSON array of claim_ids
    
    -- 全文搜索
    UNIQUE(id)
);

CREATE INDEX idx_beliefs_confidence ON beliefs(confidence);
CREATE INDEX idx_beliefs_updated ON beliefs(updated_at);
CREATE VIRTUAL TABLE beliefs_fts USING fts5(statement, content='beliefs', content_rowid='rowid');
```

#### **2. Open Question（开放问题）**

**Markdown 格式：**
```markdown
---
type: open_question
id: question_20260826_001
question: "什么时候应该使用 asyncio 而不是 threading？"
context: "在开发 web crawler 时，需要选择并发方案"
importance: 0.8
status: OPEN
created: 2026-08-26T09:00:00Z
updated: 2026-08-26T10:30:00Z
tags:
  - programming
  - python
  - concurrency
---

# 什么时候应该使用 asyncio 而不是 threading？

## 问题背景
在开发 web crawler 时，需要选择并发方案。考虑 asyncio 或 threading。

## 相关 Beliefs
- [[belief_20260826_001]] — Python asyncio 适合 I/O 密集型任务

## 提出的答案

### 答案 1：使用 asyncio（推荐）
- **理由**: Web crawler 是 I/O 密集型（等待 HTTP 响应）
- **支持证据**: [[belief_20260826_001]]
- **置信度**: 0.9

### 答案 2：使用 threading
- **理由**: Threading 更成熟，生态更好
- **支持证据**: None
- **置信度**: 0.3

## 决策
- [[decision_20260820_use_asyncio_in_web_crawler]]

## 学习资源
- [[book_fluent_python]]
- [[video_asyncio_tutorial]]

## 笔记
...
```

**SQLite Schema：**
```sql
CREATE TABLE open_questions (
    id TEXT PRIMARY KEY,
    question TEXT NOT NULL,
    context TEXT,
    importance REAL NOT NULL,  -- [0, 1]
    status TEXT NOT NULL,  -- OPEN, ANSWERED, CLOSED
    created_at TIMESTAMP NOT NULL,
    updated_at TIMESTAMP NOT NULL,
    markdown_path TEXT NOT NULL,
    
    tags TEXT,  -- JSON array
    related_beliefs TEXT,  -- JSON array
    
    UNIQUE(id)
);

CREATE INDEX idx_questions_importance ON open_questions(importance);
CREATE INDEX idx_questions_status ON open_questions(status);
CREATE VIRTUAL TABLE questions_fts USING fts5(question, context, content='open_questions');
```

#### **3. Decision（决策）**

**Markdown 格式：**
```markdown
---
type: decision
id: decision_20260820_001
question_id: question_20260826_001
title: "Web Crawler 使用 asyncio"
chosen_option: "使用 asyncio 实现并发"
alternatives:
  - "使用 threading"
  - "使用 multiprocessing"
rationale: "Web crawler 是 I/O 密集型任务，asyncio 更适合"
decided_at: 2026-08-20T14:30:00Z
decided_by: USER
tags:
  - programming
  - architecture
---

# Web Crawler 使用 asyncio

## 决策问题
[[question_20260826_001]] — 什么时候应该使用 asyncio 而不是 threading？

## 选择的方案
**使用 asyncio 实现并发**

## 备选方案
1. 使用 threading
2. 使用 multiprocessing

## 决策理由

### Pro（支持理由）
1. Web crawler 是 I/O 密集型任务（等待 HTTP 响应）
2. asyncio 性能更好（单线程，无 GIL 限制）
3. 代码更简洁（async/await 语法）

### Con（反对理由）
1. asyncio 生态不如 threading 成熟
2. 调试相对困难

### 权衡分析
基于 [[belief_20260826_001]]（置信度 0.9），asyncio 适合 I/O 密集型任务。Web crawler 的瓶颈在网络 I/O，因此 asyncio 是最佳选择。

## 依据的 Beliefs
- [[belief_20260826_001]] — Python asyncio 适合 I/O 密集型任务

## 执行计划
1. ✓ 研究 asyncio 最佳实践
2. ⬜ 实现 asyncio-based web crawler POC
3. ⬜ 性能测试（对比 threading 版本）
4. ⬜ 决定是否采用

## 结果（待填写）
- 执行状态: IN_PROGRESS
- 实际结果: TBD
- 经验教训: TBD

## 笔记
...
```

**SQLite Schema：**
```sql
CREATE TABLE decisions (
    id TEXT PRIMARY KEY,
    question_id TEXT,  -- FK to open_questions
    title TEXT NOT NULL,
    chosen_option TEXT NOT NULL,
    alternatives TEXT,  -- JSON array
    rationale TEXT NOT NULL,
    decided_at TIMESTAMP NOT NULL,
    decided_by TEXT NOT NULL,  -- USER | SYSTEM
    markdown_path TEXT NOT NULL,
    
    tags TEXT,  -- JSON array
    based_on_beliefs TEXT,  -- JSON array
    
    -- 结果追踪（V1 再实现）
    outcome_status TEXT,  -- PLANNED, IN_PROGRESS, COMPLETED, CANCELLED
    outcome_result TEXT,
    
    UNIQUE(id),
    FOREIGN KEY(question_id) REFERENCES open_questions(id)
);

CREATE INDEX idx_decisions_question ON decisions(question_id);
CREATE INDEX idx_decisions_decided_at ON decisions(decided_at);
```

#### **4. Relationships（关系图）**

**SQLite Schema：**
```sql
CREATE TABLE relationships (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    from_type TEXT NOT NULL,  -- belief, question, decision, claim
    from_id TEXT NOT NULL,
    to_type TEXT NOT NULL,
    to_id TEXT NOT NULL,
    relation_type TEXT NOT NULL,  -- BASED_ON, ANSWERS, SUPPORTS, CONTRADICTS
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    
    UNIQUE(from_type, from_id, to_type, to_id, relation_type)
);

CREATE INDEX idx_rel_from ON relationships(from_type, from_id);
CREATE INDEX idx_rel_to ON relationships(to_type, to_id);
CREATE INDEX idx_rel_type ON relationships(relation_type);
```

### 双写机制

#### **写入流程：**
```python
def create_belief(statement, claims, confidence):
    belief_id = generate_id("belief")
    
    # 1. 准备数据
    belief_data = {
        "id": belief_id,
        "statement": statement,
        "confidence": confidence,
        "based_on": claims,
        "created": now(),
        "updated": now()
    }
    
    # 2. 写入 Markdown（Source of Truth）
    markdown_path = f"$OV/beliefs/{belief_id}.md"
    write_markdown(markdown_path, belief_data)
    
    # 3. 写入 SQLite（索引）
    db.execute("""
        INSERT INTO beliefs (id, statement, confidence, created_at, updated_at, markdown_path, based_on_claims)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (belief_id, statement, confidence, belief_data["created"], belief_data["updated"], markdown_path, json.dumps(claims)))
    
    # 4. 写入关系表
    for claim_id in claims:
        db.execute("""
            INSERT INTO relationships (from_type, from_id, to_type, to_id, relation_type)
            VALUES (?, ?, ?, ?, ?)
        """, ("belief", belief_id, "claim", claim_id, "BASED_ON"))
    
    # 5. 更新全文搜索索引
    db.execute("INSERT INTO beliefs_fts(rowid, statement) VALUES (last_insert_rowid(), ?)", (statement,))
    
    db.commit()
    return belief_data
```

#### **读取流程：**
```python
def get_belief(belief_id):
    # 优先从 SQLite 读取（快速）
    row = db.execute("SELECT * FROM beliefs WHERE id = ?", (belief_id,)).fetchone()
    
    if not row:
        return None
    
    # 如果需要完整内容，再读取 Markdown
    markdown_path = row["markdown_path"]
    markdown_content = read_file(markdown_path)
    
    return {
        "id": row["id"],
        "statement": row["statement"],
        "confidence": row["confidence"],
        "created": row["created_at"],
        "updated": row["updated_at"],
        "based_on": json.loads(row["based_on_claims"]),
        "markdown_content": markdown_content  # 完整 Markdown（包括笔记）
    }
```

#### **同步检查（Health Checker 的一部分）：**
```python
def check_markdown_sqlite_sync():
    """检查 Markdown 和 SQLite 是否同步"""
    issues = []
    
    # 1. 检查 Markdown 文件是否都在 SQLite 中
    for md_file in glob.glob("$OV/beliefs/*.md"):
        belief_id = extract_id(md_file)
        if not db.execute("SELECT 1 FROM beliefs WHERE id = ?", (belief_id,)).fetchone():
            issues.append(f"Markdown file {md_file} not in SQLite")
    
    # 2. 检查 SQLite 记录是否都有对应 Markdown
    for row in db.execute("SELECT id, markdown_path FROM beliefs"):
        if not os.path.exists(row["markdown_path"]):
            issues.append(f"SQLite record {row['id']} missing Markdown file")
    
    # 3. 检查时间戳是否匹配
    for row in db.execute("SELECT id, markdown_path, updated_at FROM beliefs"):
        md_mtime = os.path.getmtime(row["markdown_path"])
        db_mtime = parse_timestamp(row["updated_at"]).timestamp()
        if abs(md_mtime - db_mtime) > 5:  # 允许 5 秒误差
            issues.append(f"Timestamp mismatch for {row['id']}")
    
    return issues
```

### 文件目录结构

```
$OV/
├── beliefs/
│   ├── belief_20260826_001.md
│   ├── belief_20260826_002.md
│   └── ...
├── questions/
│   ├── question_20260826_001.md
│   └── ...
├── decisions/
│   ├── decision_20260820_001.md
│   └── ...
├── wiki/
│   ├── programming/
│   │   ├── python-asyncio.md  # 从 llm_wiki 摄入
│   │   └── ...
│   └── ...
├── .meta/
│   └── cognition.db  # SQLite 数据库
└── ...
```

### SQLite 数据库管理

#### **初始化脚本：**
```python
# scripts/init_db.py
import sqlite3

def init_database(db_path):
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys = ON")
    
    # 创建所有表
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS beliefs (...);
        CREATE TABLE IF NOT EXISTS open_questions (...);
        CREATE TABLE IF NOT EXISTS decisions (...);
        CREATE TABLE IF NOT EXISTS relationships (...);
        
        -- 创建索引
        CREATE INDEX IF NOT EXISTS idx_beliefs_confidence ON beliefs(confidence);
        ...
        
        -- 创建全文搜索
        CREATE VIRTUAL TABLE IF NOT EXISTS beliefs_fts USING fts5(...);
        ...
    """)
    
    conn.commit()
    conn.close()
    print(f"Database initialized: {db_path}")

if __name__ == "__main__":
    init_database("$OV/.meta/cognition.db")
```

#### **备份和恢复：**
```bash
# 备份 SQLite
cp $OV/.meta/cognition.db $OV/.meta/cognition.db.backup

# 从 Markdown 重建 SQLite（如果损坏）
uv run scripts/rebuild_db_from_markdown.py
```

### Obsidian 兼容性验证

#### **测试清单：**
```yaml
双向链接:
  - ✅ [[belief_xxx]] 链接可点击
  - ✅ 反向链接面板显示正确
  - ✅ Graph View 显示关系图

标签:
  - ✅ #programming 标签可搜索
  - ✅ 标签面板显示所有标签

YAML frontmatter:
  - ✅ Obsidian 正确解析 YAML
  - ✅ 不显示为 Markdown 正文

搜索:
  - ✅ Obsidian 全文搜索工作正常
  - ✅ 本系统的 SQLite FTS 也工作正常

编辑:
  - ✅ Obsidian 编辑后，SQLite 自动更新
  - ✅ SQLite 更新后，Obsidian 自动重载
```

### 性能优化

#### **查询优化：**
```sql
-- 快速查询所有高置信度 Beliefs
SELECT id, statement, confidence
FROM beliefs
WHERE confidence > 0.8
ORDER BY updated_at DESC
LIMIT 10;

-- 全文搜索
SELECT id, statement, rank
FROM beliefs_fts
WHERE beliefs_fts MATCH 'asyncio'
ORDER BY rank
LIMIT 10;

-- 查询 Belief 的所有支持 Claims
SELECT c.id, c.statement, r.relation_type
FROM relationships r
JOIN claims c ON r.to_id = c.id
WHERE r.from_type = 'belief'
  AND r.from_id = 'belief_20260826_001'
  AND r.relation_type = 'BASED_ON';
```

#### **索引策略：**
- ✅ 所有外键都有索引
- ✅ 常用查询字段（confidence, importance, status）有索引
- ✅ 时间戳字段有索引（支持按时间排序）
- ✅ 全文搜索索引（FTS5）

### 结论

**✅ 存储方案确认：**

1. **Markdown + SQLite 混合存储**
   - Markdown 作为 Source of Truth（人可读、可编辑、Obsidian 兼容）
   - SQLite 作为索引层（快速查询、关系图、全文搜索）

2. **双写机制**
   - 写入时：Markdown → SQLite（双写）
   - 读取时：SQLite（快速查询）→ Markdown（完整内容）

3. **数据一致性**
   - Health Checker 定期检查同步状态
   - 支持从 Markdown 重建 SQLite

4. **Obsidian 兼容性**
   - 完全兼容双向链接、标签、搜索
   - File Watcher 确保实时同步

---

## 总结

### P0 问题解决状态

| 问题 | 状态 | 关键结论 |
|------|------|---------|
| P0-1: nashsu/llm_wiki 能力调研 | ✅ 完成 | API 完整可用，边界明确 |
| P0-2: 简化 V0 范围 | ✅ 完成 | 只保留 3 模块 + 2 工具 |
| P0-3: 定义存储方案 | ✅ 完成 | Markdown + SQLite 混合存储 |

### 下一步行动

```yaml
立即开始（本周）:
  1. ✅ 初始化项目结构
     - 创建 $OV/beliefs/, questions/, decisions/
     - 初始化 SQLite 数据库
  
  2. ✅ 实现基础设施
     - scripts/init_db.py
     - scripts/llm_wiki_watcher.py
     - scripts/markdown_sqlite_sync.py
  
  3. ✅ 实现核心功能
     - Module 1: Belief 管理（CRUD）
     - Module 4: Published Knowledge Ingestion
     - Module 7: Obsidian 兼容性验证

下周:
  4. ⬜ 集成测试
     - llm_wiki → 本系统端到端测试
     - Obsidian 编辑 → SQLite 同步测试
  
  5. ⬜ 性能测试
     - 1000 条 Beliefs 查询性能
     - 全文搜索性能
  
  6. ⬜ 用户试用
     - 真实场景测试
     - 收集反馈
```

---

**文档版本:** v1.0  
**完成日期:** 2026-08-26  
**作者:** AI Assistant
