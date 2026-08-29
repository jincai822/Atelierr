# 基于 Markdown 的记忆模块方案（补充调研）

**日期:** 2026-08-27  
**目的:** 调研基于 Markdown 文件的 AI Agent 记忆方案  
**用户需求:** 希望使用 MD 格式的记忆模块，而不是数据库方案

---

## 🎯 用户需求分析

```
你的需求：
  ✅ Markdown 格式存储（人类可读）
  ✅ 文件系统（不用数据库）
  ✅ 与 Obsidian 兼容
  ✅ 简单、透明、可控

为什么不满意之前的方案？
  ❌ mem0：黑盒，数据库，不透明
  ❌ SQLite 方案：还是数据库
  ❌ 想要纯文件系统 + Markdown
```

---

## 🔍 基于 Markdown 的记忆方案（GitHub 调研）

### Top 10 Markdown/文件系统记忆方案

| 项目 | Stars | 语言 | 描述 |
|------|-------|------|------|
| **jaredrhod/ai-memory-vault** | 590 ⭐ | - | Obsidian vault as AI working memory, no vector DB, just markdown |
| **mindmuxai/brain.md** | 509 ⭐ | JavaScript | File-based memory layer, zero-dependency CLI |
| **loryoncloud/Memory-Like-A-Tree** | 124 ⭐ | Python | 树状记忆，Confidence-based lifecycle，Obsidian sync |
| **Sibyl-Labs/Sibyl-Memory** | 104 ⭐ | Python | File-based long-term memory, no vector DB, no embeddings |
| basicmachines-co/basic-memory | 3,773 ⭐ | - | AI conversations that remember |
| breferrari/obsidian-mind | 4,563 ⭐ | - | Self-organizing Obsidian vault for AI agents |
| Ar9av/obsidian-wiki | 3,289 ⭐ | - | AI agents build digital brain through Obsidian |
| swarmclawai/swarmvault | 672 ⭐ | - | Local-first LLM Wiki, knowledge graph |
| zoubingwu/memory-skill | 26 ⭐ | - | File-based long-term memory agent skill |
| jzOcb/ai-agent-memory | 21 ⭐ | - | File-based with automatic TTL, LLM compression |

---

## 📊 重点方案深度分析

### 1. jaredrhod/ai-memory-vault ⭐⭐⭐⭐⭐（最推荐）

```
GitHub: https://github.com/jaredrhod/ai-memory-vault
Stars: 590 ⭐
语言: 纯模板（无代码）
描述: Obsidian vault 作为 AI 工作记忆，无向量数据库，纯 Markdown

核心理念：
  ✅ 纯 Markdown 文件
  ✅ Obsidian 兼容
  ✅ 人类可读
  ✅ No vector database
  ✅ 模板驱动

文件结构（推测）：
  memory-vault/
  ├── daily/
  │   ├── 2026-08-27.md
  │   └── 2026-08-26.md
  ├── entities/
  │   ├── people/
  │   ├── concepts/
  │   └── projects/
  ├── episodes/
  │   ├── 2026-08-27-asyncio-research.md
  │   └── 2026-05-20-asyncio-failure.md
  └── patterns/
      ├── work-habits.md
      └── decision-patterns.md

优点：
  ✅ 纯文件系统
  ✅ 人类可读（Markdown）
  ✅ Obsidian 兼容
  ✅ 简单透明
  ✅ 无外部依赖
  ✅ Git 友好

缺点：
  ⚠️ 搜索性能（大规模时）
  ⚠️ 需要手动组织
```

### 2. mindmuxai/brain.md ⭐⭐⭐⭐⭐（专业级）

```
GitHub: https://github.com/mindmuxai/brain.md
Stars: 509 ⭐
语言: JavaScript
官网: https://projectbrain.md
描述: 文件系统记忆层，零依赖 CLI

核心特性：
  ✅ File-based memory（文件系统）
  ✅ Zero-dependency CLI（无依赖）
  ✅ Durable decisions（持久化决策）
  ✅ Requirements tracking（需求跟踪）
  ✅ Constraints（约束管理）

CLI 使用（推测）：
  # 添加决策
  brain decision add "项目 X 用 threading"
  
  # 添加需求
  brain requirement add "必须支持 10K 并发"
  
  # 搜索记忆
  brain search "asyncio"
  
  # 查看模式
  brain patterns

文件结构（推测）：
  brain/
  ├── decisions/
  │   ├── 001-threading-choice.md
  │   └── 002-database-selection.md
  ├── requirements/
  │   └── functional.md
  ├── constraints/
  │   └── technical.md
  └── patterns/
      └── architecture-patterns.md

优点：
  ✅ CLI 工具（方便）
  ✅ 专注项目记忆（decisions, requirements）
  ✅ 零依赖
  ✅ 文件系统
  ✅ 成熟（509 stars）

缺点：
  ⚠️ JavaScript（你的项目是 Python）
  ⚠️ 专注项目管理（可能功能范围不同）
```

### 3. loryoncloud/Memory-Like-A-Tree ⭐⭐⭐⭐⭐（最符合需求！）

```
GitHub: https://github.com/loryoncloud/Memory-Like-A-Tree
Stars: 124 ⭐
语言: Python ✅
描述: 树状记忆管理系统，让知识像树一样生长

核心特性：
  ✅ Confidence-based lifecycle（基于置信度的生命周期）
  ✅ Auto-decay（自动衰减）— 你需要的！
  ✅ Cross-agent search（跨 Agent 搜索）
  ✅ Obsidian sync（Obsidian 同步）
  ✅ Python 实现 ✅

树状记忆概念：
  记忆像树一样生长：
    • 根：长期记忆（高置信度）
    • 枝：中期记忆（中等置信度）
    • 叶：短期记忆（低置信度，会凋落）
  
  自动衰减：
    • 不常用的记忆 → 置信度下降
    • 置信度低 → 自动删除（像树叶凋落）

文件结构（推测）：
  memory-tree/
  ├── long-term/        # 高置信度（根）
  │   ├── patterns.md
  │   └── core-beliefs.md
  ├── mid-term/         # 中等置信度（枝）
  │   └── recent-learnings.md
  ├── short-term/       # 低置信度（叶）
  │   └── current-tasks.md
  └── metadata/
      └── confidence-tracking.json

优点：
  ✅ Python 实现（与 Atelierr 一致）
  ✅ Confidence-based（与你的设计一致！）
  ✅ Auto-decay（自动衰减，你需要的）
  ✅ Obsidian 兼容
  ✅ 树状隐喻（优雅）
  ✅ 文件系统

缺点：
  ⚠️ Stars 较少（124）
  ⚠️ 可能需要调整
```

### 4. Sibyl-Labs/Sibyl-Memory ⭐⭐⭐⭐

```
GitHub: https://github.com/Sibyl-Labs/Sibyl-Memory
Stars: 104 ⭐
语言: Python ✅
描述: 文件系统长期记忆，无向量数据库，无 embeddings

核心特性：
  ✅ File-based（文件系统）
  ✅ No vector database
  ✅ No embeddings（无嵌入）
  ✅ Five-package plugin family
  ✅ MCP server（可选）

组件：
  • SDK
  • CLI
  • MCP server
  • Hermes adapter
  • LangGraph BaseStore

优点：
  ✅ Python
  ✅ 纯文件系统
  ✅ 无复杂依赖
  ✅ 模块化

缺点：
  ⚠️ 多包（可能复杂）
  ⚠️ Stars 较少（104）
```

---

## 🎯 最终推荐（基于你的需求）

### 方案 1：Memory-Like-A-Tree ⭐⭐⭐⭐⭐（最推荐）

#### 为什么最适合你？

```
完美匹配你的需求：

1. Markdown 文件系统 ✅
   • 纯文件，无数据库
   • 人类可读
   • Git 友好

2. Confidence-based ✅
   • 与你的 Cognition 设计完全一致！
   • 置信度驱动生命周期
   • 自动衰减（你需要的 decay）

3. Python 实现 ✅
   • 与 Atelierr 技术栈一致
   • 易于集成

4. Obsidian 兼容 ✅
   • 可以用 Obsidian 查看
   • 双向链接支持

5. 树状隐喻 ✅
   • 优雅的概念模型
   • 根（长期）→ 枝（中期）→ 叶（短期）
```

#### 集成到 Atelierr

```python
# scripts/memory.py（基于 Memory-Like-A-Tree 设计）

from pathlib import Path
import json
from datetime import datetime, timedelta

class AtelierrMemoryTree:
    """
    基于 Memory-Like-A-Tree 的记忆模块
    
    记忆像树一样生长：
      • 根（long-term）：高置信度（> 0.8）
      • 枝（mid-term）：中置信度（0.5-0.8）
      • 叶（short-term）：低置信度（< 0.5）
    
    自动衰减：
      • 不常访问 → 置信度下降
      • 置信度低 → 自动删除（叶凋落）
    """
    
    def __init__(self, ov_path: str):
        self.ov_path = Path(ov_path)
        self.memory_path = self.ov_path / "memory"
        
        # 3 层树状结构
        self.long_term = self.memory_path / "long-term"
        self.mid_term = self.memory_path / "mid-term"
        self.short_term = self.memory_path / "short-term"
        
        for path in [self.long_term, self.mid_term, self.short_term]:
            path.mkdir(parents=True, exist_ok=True)
    
    def add_memory(self, content: str, confidence: float, metadata: dict):
        """添加记忆（自动分配到合适的层）"""
        # 根据置信度分配层级
        if confidence > 0.8:
            layer = self.long_term / "beliefs"
        elif confidence > 0.5:
            layer = self.mid_term / "learnings"
        else:
            layer = self.short_term / "observations"
        
        layer.mkdir(exist_ok=True)
        
        # 生成 Markdown 文件
        memory_id = metadata.get("id", f"mem_{datetime.now().timestamp()}")
        filepath = layer / f"{memory_id}.md"
        
        # Markdown 格式
        md_content = f"""---
id: {memory_id}
confidence: {confidence}
created: {datetime.now().isoformat()}
tags: {metadata.get('tags', [])}
---

# {metadata.get('title', 'Untitled Memory')}

{content}

## Metadata

- Confidence: {confidence}
- Source: {metadata.get('source', 'Unknown')}
- References: {metadata.get('references', [])}
"""
        
        filepath.write_text(md_content, encoding='utf-8')
        return memory_id
    
    def search_memory(self, query: str) -> list:
        """搜索记忆（跨所有层）"""
        results = []
        
        for layer in [self.long_term, self.mid_term, self.short_term]:
            for md_file in layer.rglob("*.md"):
                content = md_file.read_text(encoding='utf-8')
                if query.lower() in content.lower():
                    results.append({
                        "path": str(md_file),
                        "layer": layer.name,
                        "content": content[:200]  # 前 200 字符
                    })
        
        return results
    
    def decay_memories(self):
        """自动衰减（叶凋落）"""
        # 扫描所有记忆，更新置信度
        for layer in [self.long_term, self.mid_term, self.short_term]:
            for md_file in layer.rglob("*.md"):
                # 读取元数据
                content = md_file.read_text(encoding='utf-8')
                # TODO: 解析 frontmatter，更新 confidence
                # 如果 confidence < 0.3 → 删除
                pass
    
    def get_long_term_patterns(self) -> list:
        """获取长期模式（根）"""
        patterns = []
        patterns_dir = self.long_term / "patterns"
        
        if patterns_dir.exists():
            for md_file in patterns_dir.glob("*.md"):
                patterns.append({
                    "path": str(md_file),
                    "content": md_file.read_text(encoding='utf-8')
                })
        
        return patterns
```

#### 文件结构设计

```
$OV/memory/                      ← 记忆树根目录
├── long-term/                   ← 根（高置信度 > 0.8）
│   ├── beliefs/
│   │   ├── B001-asyncio-适用边界.md
│   │   └── B002-混合场景用threading.md
│   ├── patterns/
│   │   ├── P001-工作习惯模式.md
│   │   └── P002-决策模式.md
│   └── lessons/
│       └── L001-asyncio失败教训.md
│
├── mid-term/                    ← 枝（中等置信度 0.5-0.8）
│   ├── learnings/
│   │   └── recent-research.md
│   └── questions/
│       └── Q001-混合场景方案.md
│
├── short-term/                  ← 叶（低置信度 < 0.5）
│   ├── observations/
│   │   └── 2026-08-27-notes.md
│   └── working/
│       └── current-task.md
│
└── metadata/
    ├── confidence-tracking.json  ← 置信度跟踪
    └── decay-schedule.json       ← 衰减计划
```

#### Markdown 文件格式

```markdown
---
id: B001
type: belief
confidence: 0.85
created: 2026-08-27T10:30:00
last_accessed: 2026-11-20T14:00:00
access_count: 15
tags: [asyncio, performance, architecture]
references:
  - papers/asyncio_performance.md
  - decisions/Decision_003.md
---

# asyncio 适用边界

asyncio 适合 **纯 I/O 密集型** 场景，不适合混合计算 + I/O。

## 证据

1. [[Decision_003]] — 项目 X 失败（慢 1.5 倍）
2. [[Paper_123]] — 理论分析
3. [[EP001]] — 完整经历

## 相关信念

- [[B002-混合场景用threading]]
- [[L001-asyncio失败教训]]

## 置信度历史

- 2026-08-27: 0.85 (初始)
- 2026-09-26: 0.45 (失败后)
- 2026-11-20: 0.85 (第二次验证)
```

---

### 方案 2：自己实现（纯 Markdown + 简单脚本）⭐⭐⭐⭐⭐

#### 最简单的方案

```
如果你想要完全控制，不依赖任何库：

实现：
  • 纯 Markdown 文件
  • 简单的 Python 脚本（读写文件）
  • 文件系统 + frontmatter
  • 无外部依赖

代码量：~300 行
实现时间：2-3 天
```

#### 核心实现

```python
# scripts/memory.py（最简版）

import re
from pathlib import Path
from datetime import datetime

class SimpleMarkdownMemory:
    """
    最简单的 Markdown 记忆模块
    
    存储：纯 Markdown 文件
    元数据：YAML frontmatter
    搜索：简单的文本匹配
    """
    
    def __init__(self, ov_path: str):
        self.memory_path = Path(ov_path) / "memory"
        self.memory_path.mkdir(exist_ok=True)
    
    def add(self, title: str, content: str, metadata: dict):
        """添加记忆"""
        # 生成文件名
        slug = re.sub(r'[^\w\s-]', '', title).strip().replace(' ', '-')
        filepath = self.memory_path / f"{slug}.md"
        
        # Markdown 内容
        md = f"""---
title: {title}
created: {datetime.now().isoformat()}
confidence: {metadata.get('confidence', 0.5)}
tags: {metadata.get('tags', [])}
---

# {title}

{content}
"""
        
        filepath.write_text(md, encoding='utf-8')
        return str(filepath)
    
    def search(self, query: str) -> list:
        """搜索记忆"""
        results = []
        for md_file in self.memory_path.glob("*.md"):
            content = md_file.read_text(encoding='utf-8')
            if query.lower() in content.lower():
                results.append(str(md_file))
        return results
    
    def get_all(self) -> list:
        """获取所有记忆"""
        return [str(f) for f in self.memory_path.glob("*.md")]
```

#### 优点

```
✅ 最简单（~300 行）
✅ 完全控制
✅ 无外部依赖
✅ 纯 Markdown
✅ 人类可读
✅ Git 友好
✅ Obsidian 兼容
✅ 实现快（2-3 天）
```

#### 缺点

```
⚠️ 功能简单
⚠️ 搜索性能一般
⚠️ 无自动衰减（需要手动实现）
```

---

## 📊 方案对比（Markdown 方案）

| 方案 | Stars | 语言 | 复杂度 | 功能 | 推荐度 |
|------|-------|------|--------|------|--------|
| **Memory-Like-A-Tree** | 124 | Python | 中 | Confidence + Decay | ⭐⭐⭐⭐⭐ |
| **ai-memory-vault** | 590 | 模板 | 低 | 纯模板 | ⭐⭐⭐⭐ |
| **brain.md** | 509 | JS | 中 | CLI 工具 | ⭐⭐⭐⭐ |
| **Sibyl-Memory** | 104 | Python | 中 | 多包系统 | ⭐⭐⭐ |
| **自己实现** | - | Python | 低 | 基础功能 | ⭐⭐⭐⭐⭐ |

---

## 🎯 最终推荐

### 推荐：Memory-Like-A-Tree 设计 + 自己实现

```
策略：
  • 借鉴 Memory-Like-A-Tree 的设计理念
  • 自己实现（Python + Markdown）
  • 完全符合 Atelierr 设计哲学

理由：
  ✅ Confidence-based（与你的设计一致）
  ✅ 自动衰减（树叶凋落）
  ✅ 纯 Markdown（人类可读）
  ✅ 完全控制（自己实现）
  ✅ 无外部依赖
  ✅ Python 原生
```

### 实施计划

```
Phase 1（Week 1）：
  • 实现树状记忆结构
  • 3 层：long-term, mid-term, short-term
  • 纯 Markdown + frontmatter
  • 代码量：~400 行

Phase 2（Week 2）：
  • 添加自动衰减
  • 置信度追踪
  • 简单搜索

Phase 3（Week 3）：
  • 集成到 Atelierr
  • 测试
  • 优化
```

---

**总结：推荐借鉴 Memory-Like-A-Tree 的设计，自己实现纯 Markdown 记忆模块。**

这样既符合你的需求（Markdown 文件），又与你的 Cognition 设计完美契合（Confidence-based）！

你觉得这个方案怎么样？😊
