# 记忆模块技术方案调研

**日期:** 2026-08-27  
**目的:** 调研 GitHub 上的 AI Agent 记忆方案，选择适合 Atelierr 的实现  
**调研范围:** 开源记忆管理库

---

## 🔍 GitHub 调研结果

### Top 10 AI Agent 记忆方案（按 Stars 排序）

| 项目 | Stars | 语言 | 描述 |
|------|-------|------|------|
| **mem0ai/mem0** | 64,153 | Python | Universal memory layer for AI Agents |
| **agentscope-ai/ReMe** | 3,357 | Python | Memory Management Kit for Agents |
| **RichmondAlake/memorizz** | 762 | Python | Memory layer for AI applications |
| bytedance/deer-flow | 80,978 | - | Long-horizon SuperAgent with memories |
| ruvnet/ruflo | 69,505 | - | Agent meta-harness with adaptive memory |
| HKUDS/nanobot | 47,448 | Python | Personal AI agent with memory |
| zhayujie/CowAgent | 46,696 | - | Self-evolves with memory and knowledge |
| volcengine/OpenViking | 33,693 | - | Context Database for AI Agents |
| topoteretes/cognee | 30,289 | - | Persistent long-term memory with knowledge graph |
| rohitg00/agentmemory | 27,557 | - | Persistent memory for AI coding agents |

---

## 📊 重点方案对比

### 1. mem0ai/mem0 ⭐⭐⭐⭐⭐（最推荐）

```
GitHub: https://github.com/mem0ai/mem0
Stars: 64,153 ⭐（最高）
语言: Python
官网: https://mem0.ai

关键特性：
  ✅ Universal memory layer（通用记忆层）
  ✅ 支持多种后端（Vector DB, Graph DB, Local）
  ✅ Long-term memory（长期记忆）
  ✅ RAG 集成
  ✅ State management（状态管理）
  ✅ 成熟度高（64K stars）

Topics:
  • agents, ai-agents, chatbots, llm
  • long-term-memory, memory-management
  • rag, state-management
  • python, genai, application

适合场景：
  ✅ 需要通用记忆层
  ✅ 需要多后端支持
  ✅ 成熟项目，社区活跃
```

### 2. agentscope-ai/ReMe ⭐⭐⭐⭐

```
GitHub: https://github.com/agentscope-ai/ReMe
Stars: 3,357 ⭐
语言: Python

关键特性：
  ✅ Memory Management Kit（记忆管理工具包）
  ✅ "Remember Me, Refine Me"（记住我，优化我）
  ✅ DSH-plugin（插件化设计）
  ✅ MemoryScope 概念
  ✅ RAG 集成

适合场景：
  ✅ 需要记忆优化功能
  ✅ 需要插件化设计
  ✅ 中等成熟度
```

### 3. RichmondAlake/memorizz ⭐⭐⭐

```
GitHub: https://github.com/RichmondAlake/memorizz
Stars: 762 ⭐
语言: Python

关键特性：
  ✅ Memory layer for AI applications
  ✅ Leverages popular databases
  ✅ Utility classes and methods
  ✅ Efficient data management

适合场景：
  ✅ 简单轻量
  ✅ 需要基础记忆功能
```

---

## 🎯 推荐方案

### 方案 1：使用 mem0ai/mem0 ⭐⭐⭐⭐⭐（最推荐）

#### 为什么选 mem0？

```
1. 成熟度最高（64K stars）
   • 社区活跃
   • 文档完善
   • bug 少
   • 持续维护

2. 功能完整
   • Universal memory layer（通用）
   • Long-term memory（长期记忆）
   • 多种后端（灵活）
   • RAG 集成（知识检索）

3. Python 原生
   • Atelierr 是 Python
   • 集成简单
   • 性能好

4. 可扩展
   • 支持多种存储后端
   • 可以从简单开始（本地文件）
   • 后期升级到 Vector DB
```

#### mem0 使用示例（推测）

```python
from mem0 import Memory

# 初始化记忆层
memory = Memory(
    storage_backend="local",  # 本地文件（或 redis, qdrant, pinecone）
    embedding_model="sentence-transformers",
    config={
        "memory_ttl": 7,  # Short-term 保留 7 天
        "enable_episodic": True,
        "enable_semantic_search": True
    }
)

# 添加记忆
memory.add(
    content="asyncio 研究失败，慢 1.5 倍",
    metadata={
        "type": "episodic",
        "date": "2026-08-27",
        "tags": ["asyncio", "failure"]
    }
)

# 搜索记忆（语义搜索）
results = memory.search(
    query="asyncio 失败",
    filter={"type": "episodic"},
    limit=5
)

# 获取长期记忆
patterns = memory.get_long_term(
    category="patterns",
    confidence_threshold=0.8
)
```

#### 集成到 Atelierr

```python
# scripts/memory.py（基于 mem0）

from mem0 import Memory
import json
from pathlib import Path

class AtelierrMemory:
    def __init__(self, ov_path: str):
        self.ov_path = Path(ov_path)
        self.memory_path = self.ov_path / "memory"
        
        # 使用 mem0 作为底层
        self.mem0 = Memory(
            storage_backend="local",
            storage_path=str(self.memory_path),
            embedding_model="sentence-transformers"
        )
    
    # Working Memory（当前会话）
    def get_working(self) -> dict:
        return self.mem0.get_session_memory()
    
    def update_working(self, data: dict):
        self.mem0.add_session(data)
    
    # Short-term Memory（最近 7 天）
    def get_short_term(self, days: int = 7) -> list:
        return self.mem0.search(
            filter={
                "created_within_days": days
            }
        )
    
    # Long-term Memory（习惯、模式）
    def get_long_term(self, category: str) -> list:
        return self.mem0.search(
            filter={
                "type": "long_term",
                "category": category
            }
        )
    
    def update_pattern(self, pattern: dict):
        self.mem0.add(
            content=pattern["content"],
            metadata={
                "type": "long_term",
                "category": "pattern",
                "confidence": pattern["confidence"]
            }
        )
    
    # Episodic Memory（具体事件）
    def get_episodes(self, query: str) -> list:
        return self.mem0.search(
            query=query,
            filter={"type": "episodic"},
            limit=10
        )
    
    def create_episode(self, event: dict):
        self.mem0.add(
            content=event["summary"],
            metadata={
                "type": "episodic",
                "date": event["date"],
                "tags": event["tags"]
            }
        )
```

#### 优点

```
✅ 成熟稳定（64K stars）
✅ 功能完整（4 层记忆）
✅ 开箱即用（快速集成）
✅ 性能好（优化过的）
✅ 社区支持（问题能快速解决）
✅ 可扩展（后端可替换）
✅ 语义搜索（相似度搜索）
```

#### 缺点

```
⚠️ 依赖外部库（但是成熟库，可接受）
⚠️ 可能有学习成本（需要读文档）
⚠️ 可能有一些不需要的功能（可以不用）
```

---

### 方案 2：自己实现（SQLite + 文件） ⭐⭐⭐⭐

#### 为什么自己实现？

```
1. 完全控制
   • 不依赖外部库
   • 完全符合 Atelierr 设计
   • 代码完全自己掌控

2. 轻量
   • SQLite（Python 内置）
   • 文件存储（简单）
   • 无需额外依赖

3. 学习成本低
   • 已经熟悉 SQLite
   • 代码简单易懂
   • 符合 Atelierr 哲学（最小依赖）
```

#### 实现（简化版）

```python
# scripts/memory.py（自己实现）

import sqlite3
import json
from pathlib import Path
from datetime import datetime, timedelta

class AtelierrMemory:
    def __init__(self, ov_path: str):
        self.ov_path = Path(ov_path)
        self.memory_path = self.ov_path / "memory"
        self.memory_path.mkdir(exist_ok=True)
        
        # SQLite 存储索引
        self.db = sqlite3.connect(self.memory_path / "memory.db")
        self._init_db()
    
    def _init_db(self):
        self.db.execute("""
            CREATE TABLE IF NOT EXISTS memories (
                id TEXT PRIMARY KEY,
                type TEXT,  -- working, short_term, long_term, episodic
                category TEXT,
                content TEXT,
                metadata TEXT,  -- JSON
                created_at TIMESTAMP,
                expires_at TIMESTAMP
            )
        """)
        self.db.execute("CREATE INDEX IF NOT EXISTS idx_type ON memories(type)")
        self.db.execute("CREATE INDEX IF NOT EXISTS idx_created ON memories(created_at)")
    
    # Working Memory
    def get_working(self) -> list:
        cursor = self.db.execute(
            "SELECT content, metadata FROM memories WHERE type='working' AND expires_at > ?",
            (datetime.now(),)
        )
        rows = cursor.fetchall()
        return [
            {"content": r[0], "metadata": json.loads(r[1])}
            for r in rows
        ]
    
    def update_working(self, data: dict):
        self.db.execute("""
            INSERT INTO memories (id, type, content, metadata, created_at, expires_at)
            VALUES (?, 'working', ?, ?, ?, ?)
        """, (
            f"working_{datetime.now().timestamp()}",
            json.dumps(data),
            json.dumps(data.get("metadata", {})),
            datetime.now(),
            datetime.now() + timedelta(hours=2)  # 2 小时后过期
        ))
        self.db.commit()
    
    # Short-term Memory
    def get_short_term(self, days: int = 7) -> list:
        since = datetime.now() - timedelta(days=days)
        cursor = self.db.execute(
            "SELECT content, metadata FROM memories WHERE type='short_term' AND created_at > ?",
            (since,)
        )
        rows = cursor.fetchall()
        return [
            {"content": r[0], "metadata": json.loads(r[1])}
            for r in rows
        ]
    
    # Long-term Memory
    def get_long_term(self, category: str) -> list:
        cursor = self.db.execute(
            "SELECT content, metadata FROM memories WHERE type='long_term' AND category=?",
            (category,)
        )
        rows = cursor.fetchall()
        return [
            {"content": r[0], "metadata": json.loads(r[1])}
            for r in rows
        ]
    
    # Episodic Memory（简单搜索，基于关键词）
    def get_episodes(self, query: str) -> list:
        cursor = self.db.execute(
            "SELECT content, metadata FROM memories WHERE type='episodic' AND content LIKE ?",
            (f"%{query}%",)
        )
        rows = cursor.fetchall()
        return [
            {"content": r[0], "metadata": json.loads(r[1])}
            for r in rows
        ]
    
    # 自动清理过期记忆
    def cleanup_expired(self):
        self.db.execute(
            "DELETE FROM memories WHERE expires_at IS NOT NULL AND expires_at < ?",
            (datetime.now(),)
        )
        self.db.commit()
```

#### 优点

```
✅ 完全控制
✅ 轻量（SQLite + JSON）
✅ 无外部依赖
✅ 完全符合 Atelierr 设计哲学
✅ 学习成本低
✅ 代码简单（~500 行）
```

#### 缺点

```
⚠️ 功能简单（无语义搜索）
⚠️ 性能一般（大规模数据时）
⚠️ 需要自己维护（bug、优化）
⚠️ 无社区支持
```

---

## 🎯 最终推荐：渐进式方案 ⭐⭐⭐⭐⭐

### 渐进式策略（最优）

```
阶段 1（MVP，Week 1）：自己实现（SQLite + 文件）
  • 快速启动（3-5 天）
  • 验证 4 层记忆设计
  • 无外部依赖
  • 学习成本低
  • 符合 Atelierr 哲学

阶段 2（v1.0，Week 4-5）：评估是否升级到 mem0
  • 如果需要语义搜索 → 升级到 mem0
  • 如果 MVP 够用 → 继续优化 MVP
  • 迁移成本低（API 一致）

理由：
  ✅ 避免过早优化
  ✅ 快速验证设计
  ✅ 保持灵活性
  ✅ 低风险（无外部依赖）
```

### 实施计划

#### Phase 1: MVP（1 周，自己实现）

```python
# scripts/memory.py（MVP 版本）

class AtelierrMemory:
    """
    MVP 版本：SQLite + JSON 文件
    
    存储：
      • SQLite：索引和元数据（快速查询）
      • JSON 文件：完整内容（$OV/memory/episodes/*.json）
    
    功能：
      ✅ 4 层记忆（Working/Short/Long/Episodic）
      ✅ 基本 CRUD
      ✅ 简单搜索（关键词匹配）
      ✅ 自动清理（过期记忆）
      ✅ 自动归档（Short → Long）
      
      ❌ 语义搜索（Phase 2，按需）
      ❌ RAG（Phase 2，按需）
      ❌ Vector DB（Phase 2，按需）
    
    代码量：~500 行
    实现时间：3-5 天
    依赖：0（只用 Python 标准库）
    """
    pass
```

#### Phase 2: 评估与升级（2-3 周后）

```python
# 评估问题：

1. MVP 是否满足需求？
   • 4 层记忆工作正常？
   • 搜索速度可接受？
   • 数据量在可控范围？

2. 是否需要语义搜索？
   • 关键词搜索不够用？
   • 需要"相似记忆"功能？
   • 需要跨语言搜索？

如果 YES → 升级到 mem0：
  • 安装 mem0：pip install mem0ai
  • 替换底层实现（API 不变）
  • 数据迁移（JSON → mem0）
  • 迁移时间：2-3 天

如果 NO → 继续优化 MVP：
  • 添加全文搜索（SQLite FTS）
  • 优化索引
  • 压缩旧数据
```

---

## 📊 方案对比总结

| 方案 | 成熟度 | 功能 | 性能 | 学习成本 | 依赖 | 实现时间 | 推荐度 |
|------|-------|------|------|---------|------|---------|--------|
| **mem0** | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐⭐ | ⭐⭐⭐ | 外部库 | 1-2 周 | ⭐⭐⭐⭐⭐ |
| **ReMe** | ⭐⭐⭐ | ⭐⭐⭐⭐ | ⭐⭐⭐⭐ | ⭐⭐⭐ | 外部库 | 1-2 周 | ⭐⭐⭐⭐ |
| **自己实现** | ⭐⭐ | ⭐⭐⭐ | ⭐⭐⭐ | ⭐⭐⭐⭐⭐ | 无 | 3-5 天 | ⭐⭐⭐⭐ |
| **渐进式** | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐⭐ | 渐进 | 3-5 天 | ⭐⭐⭐⭐⭐ |

---

## 🎯 最终决策

### 推荐：渐进式方案

```
第 1 步（Week 1）：
  • 自己实现 MVP（SQLite + JSON）
  • 验证 4 层记忆设计
  • 集成到 Atelierr
  • 测试基本功能
  • 代码量：~500 行
  • 依赖：0

第 2 步（Week 4-5）：
  • 评估 MVP 效果
  • 收集使用反馈
  • 决定是否需要升级

如果需要升级：
  • 安装 mem0
  • 替换底层（API 不变）
  • 数据迁移
  • 获得：语义搜索、RAG、Vector DB

如果不需要升级：
  • 继续优化 MVP
  • 添加 FTS（全文搜索）
  • 保持轻量
```

### 为什么是渐进式？

```
✅ 快速启动（3-5 天 vs 1-2 周）
✅ 低风险（无外部依赖）
✅ 验证设计（避免过度设计）
✅ 符合 Atelierr 哲学（最小改动）
✅ 可升级（API 一致，迁移简单）
✅ 灵活性（按需决策）
```

---

## 📝 下一步行动

### Phase 1（本周）

```
1. 实现 memory.py（MVP 版本）
   • SQLite + JSON
   • 4 层记忆
   • ~500 行代码
   • 3-5 天完成

2. 补充测试
   • tests/test_memory.py
   • 覆盖率 > 80%

3. 集成到 /daily-reflection
   • 读取今日记忆
   • 写入今日情景

4. 试用
   • 10-20 个记忆
   • 收集反馈
```

### Phase 2（3-4 周后）

```
评估决策点：
  • MVP 满足需求？
  • 需要语义搜索？
  • 数据量多大？

决策：
  • 继续 MVP → 优化
  • 升级 mem0 → 迁移
```

---

**推荐：先用 MVP（SQLite）快速验证，后期按需升级到 mem0。**

这个方案既快速又灵活，你觉得怎么样？😊
