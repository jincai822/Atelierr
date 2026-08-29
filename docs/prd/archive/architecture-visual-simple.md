# Atelierr 完整架构 - 可视化图解

## 总览：三个独立模块

```
┌─────────────────────────────────────────────────────────────┐
│                     完整系统                                 │
│                                                              │
│  ┌────────────────────────────────────────────────────┐    │
│  │  模块 1: Web 交互界面 (Flatnotes)                  │    │
│  │  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━  │    │
│  │  • Vue.js 前端                                      │    │
│  │  • Flask 后端                                       │    │
│  │  • 提供网页访问                                     │    │
│  │  📍 在哪？Docker 容器 (独立部署)                   │    │
│  └──────────────────────┬─────────────────────────────┘    │
│                         │                                   │
│                         ↓ (读写文件)                        │
│                                                              │
│  ┌────────────────────────────────────────────────────┐    │
│  │  模块 2: 记忆模块 (Memory-Like-A-Tree)             │    │
│  │  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━  │    │
│  │  • 管理记忆文件                                     │    │
│  │  • Confidence 计算                                  │    │
│  │  • 自动衰减                                         │    │
│  │  📍 在哪？scripts/memory.py (Python 代码)          │    │
│  └──────────────────────┬─────────────────────────────┘    │
│                         │                                   │
│                         ↓ (被调用)                          │
│                                                              │
│  ┌────────────────────────────────────────────────────┐    │
│  │  模块 3: Atelierr 核心 (现有系统)                  │    │
│  │  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━  │    │
│  │  • 15 个 Agents                                     │    │
│  │  • 反思流程                                         │    │
│  │  • 语义搜索                                         │    │
│  │  📍 在哪？.claude/agents/ (现有代码)               │    │
│  └────────────────────────────────────────────────────┘    │
│                                                              │
└─────────────────────────────────────────────────────────────┘
```

---

## 详细架构图

```
                        用户
                         │
        ┌────────────────┼────────────────┐
        │                │                │
        ↓                ↓                ↓
   ┌─────────┐     ┌─────────┐     ┌─────────┐
   │ Obsidian│     │Flatnotes│     │  飞书   │
   │ (本地)  │     │ (网页)  │     │ (手机)  │
   └────┬────┘     └────┬────┘     └────┬────┘
        │               │               │
        └───────────────┼───────────────┘
                        ↓
            ┌───────────────────────┐
            │   $OV/memory/         │  ← 所有记忆文件都存这里
            │   (Markdown 文件)     │
            │                       │
            │   long-term/          │  ← 高信心记忆
            │   mid-term/           │  ← 中等记忆
            │   short-term/         │  ← 临时记忆
            └───────────┬───────────┘
                        ↓
            ┌───────────────────────┐
            │  scripts/memory.py    │  ← 记忆模块 (新增)
            │                       │
            │  • add_memory()       │
            │  • search_memory()    │
            │  • decay_memory()     │
            │  • move_to_layer()    │
            └───────────┬───────────┘
                        ↓
            ┌───────────────────────┐
            │  .claude/agents/      │  ← Atelierr Agents
            │                       │
            │  • researcher.md      │
            │  • synthesizer.md     │
            │  • forgetter.md       │
            └───────────────────────┘
```

---

## 模块 1: Web 交互界面

### 📍 在哪里？

```
位置: Docker 容器 (独立部署)

文件结构:
  flatnotes/  (独立项目，不在 Atelierr 代码库)
  ├── frontend/   (Vue.js)
  ├── backend/    (Flask)
  └── docker-compose.yml

部署命令:
  docker run -d \
    --name flatnotes \
    -p 5000:5000 \
    -v /path/to/$OV/memory:/data \
    dullage/flatnotes
```

### 功能

```
┌─────────────────────────────────┐
│      Flatnotes Web 界面         │
├─────────────────────────────────┤
│                                 │
│  📝 创建笔记                    │
│  🔍 搜索笔记                    │
│  ✏️  编辑笔记                    │
│  📱 移动端访问                  │
│                                 │
│  ↓ (保存)                       │
│                                 │
│  $OV/memory/xxx.md              │
│                                 │
└─────────────────────────────────┘
```

---

## 模块 2: 记忆模块

### 📍 在哪里？

```
位置: Atelierr/scripts/memory.py (新增文件)

文件结构:
  Atelierr/
  └── scripts/
      ├── memory.py          ← 记忆模块 (新增)
      ├── attention.py       ← 注意力模块 (新增)
      ├── cognition.py       ← 认知模块 (新增)
      ├── semantic.py        (现有)
      └── context_bundle.py  (现有)
```

### 功能

```
┌──────────────────────────────────────────┐
│      scripts/memory.py (记忆模块)        │
├──────────────────────────────────────────┤
│                                          │
│  class MemoryTree:                       │
│                                          │
│    def add_memory():                     │
│      • 创建新记忆                        │
│      • 计算 Confidence                   │
│      • 分配到 long/mid/short-term        │
│                                          │
│    def search_memory():                  │
│      • 搜索记忆                          │
│      • 返回相关记忆                      │
│                                          │
│    def decay_memory():                   │
│      • 降低 Confidence                   │
│      • 删除低信心记忆                    │
│                                          │
│    def move_between_layers():            │
│      • 根据 Confidence 移动记忆          │
│      • short → mid → long                │
│                                          │
└──────────────────────────────────────────┘
```

### 示例代码

```python
# scripts/memory.py (新增文件)

from pathlib import Path
import frontmatter
from datetime import datetime

class MemoryTree:
    """记忆模块"""
    
    def __init__(self, ov_path: str):
        self.memory_path = Path(ov_path) / "memory"
        self.long_term = self.memory_path / "long-term"
        self.mid_term = self.memory_path / "mid-term"
        self.short_term = self.memory_path / "short-term"
    
    def add_memory(self, title: str, content: str, confidence: float):
        """添加记忆"""
        # 根据 confidence 决定层级
        if confidence > 0.8:
            layer = self.long_term / "beliefs"
        elif confidence > 0.5:
            layer = self.mid_term / "learnings"
        else:
            layer = self.short_term / "observations"
        
        # 保存文件
        filepath = layer / f"{title}.md"
        post = frontmatter.Post(content)
        post.metadata = {
            'confidence': confidence,
            'created': datetime.now().isoformat()
        }
        
        with open(filepath, 'w') as f:
            f.write(frontmatter.dumps(post))
    
    def decay_memories(self):
        """衰减记忆"""
        for md_file in self.memory_path.rglob("*.md"):
            post = frontmatter.load(md_file)
            confidence = post.metadata.get('confidence', 0.5)
            
            # 降低 confidence
            new_confidence = confidence * 0.95
            
            if new_confidence < 0.3:
                md_file.unlink()  # 删除
            else:
                post.metadata['confidence'] = new_confidence
                with open(md_file, 'w') as f:
                    f.write(frontmatter.dumps(post))
```

---

## 模块 3: Atelierr 核心

### 📍 在哪里？

```
位置: .claude/agents/ (现有代码)

文件结构:
  Atelierr/
  └── .claude/
      └── agents/
          ├── researcher.md       (现有)
          ├── synthesizer.md      (现有)
          ├── reader.md           (现有)
          ├── forgetter.md        (新增)
          └── ... (15+ agents)
```

### 如何调用记忆模块

```python
# .claude/agents/forgetter.md 的实现

from scripts.memory import MemoryTree

def run_forgetter():
    """遗忘者 Agent - 定期清理低信心记忆"""
    
    # 初始化记忆模块
    memory = MemoryTree(ov_path="/path/to/$OV")
    
    # 执行衰减
    memory.decay_memories()
    
    print("✅ 记忆衰减完成")
```

---

## 完整数据流（带文件路径）

### 场景: 用户在网页创建笔记

```
步骤 1: 用户操作
  用户打开浏览器
  → https://memory.yourdomain.com (Flatnotes)
  → 创建笔记: "asyncio 测试失败"

步骤 2: Flatnotes 保存文件
  📁 $OV/memory/short-term/observations/asyncio-test-fail.md
  
  内容:
  ---
  title: asyncio 测试失败
  created: 2026-08-27T16:00:00
  source: web
  ---
  
  今天测试 asyncio 时发现性能问题...

步骤 3: 记忆模块处理 (定时任务)
  scripts/memory.py 检测到新文件
  → 读取文件
  → 计算 Confidence (基于内容、来源等)
  → Confidence = 0.6 (中等)
  
  → 添加 Confidence 到文件:
  ---
  title: asyncio 测试失败
  created: 2026-08-27T16:00:00
  confidence: 0.6  ← 新增
  source: web
  ---

步骤 4: 随时间衰减 (每天运行)
  Day 1: confidence = 0.6
  Day 7: confidence = 0.6 * 0.95^7 = 0.42
  Day 14: confidence = 0.6 * 0.95^14 = 0.29
  
  → confidence < 0.3 → 删除文件

步骤 5: 如果被访问 (信心增强)
  用户/Agent 访问这个记忆
  → confidence += 0.1
  → confidence = 0.52
  → 保留更久

步骤 6: Atelierr Agent 调用
  # Agent 需要搜索记忆
  from scripts.memory import MemoryTree
  
  memory = MemoryTree(ov_path="$OV")
  results = memory.search("asyncio")
  
  → 返回: asyncio-test-fail.md
```

---

## 文件系统结构（实际路径）

```
/path/to/$OV/  (你的 oeuvre 根目录)
│
├── memory/  (新增 - 记忆模块存储)
│   │
│   ├── long-term/  (高信心记忆, confidence > 0.8)
│   │   ├── beliefs/
│   │   │   ├── asyncio-not-for-mixed.md  (confidence: 0.92)
│   │   │   └── threading-better.md       (confidence: 0.88)
│   │   ├── patterns/
│   │   └── lessons/
│   │
│   ├── mid-term/  (中等记忆, 0.5 < confidence < 0.8)
│   │   └── learnings/
│   │       ├── project-x-review.md  (confidence: 0.65)
│   │       └── team-meeting-notes.md (confidence: 0.58)
│   │
│   └── short-term/  (临时记忆, confidence < 0.5)
│       └── observations/
│           ├── daily-thought.md  (confidence: 0.35)
│           └── quick-idea.md     (confidence: 0.42)
│
├── cognition/  (新增 - 认知模块)
│   ├── beliefs/
│   ├── questions/
│   └── hypotheses/
│
├── wiki/  (现有)
├── papers/  (现有)
└── daily/  (现有)


Atelierr/  (代码库)
│
├── scripts/  (Python 脚本)
│   ├── memory.py  ← 记忆模块代码 (新增)
│   ├── attention.py  ← 注意力模块 (新增)
│   ├── cognition.py  ← 认知模块 (新增)
│   ├── semantic.py  (现有)
│   └── context_bundle.py  (现有)
│
└── .claude/
    └── agents/  (Agent 定义)
        ├── researcher.md  (现有)
        ├── synthesizer.md  (现有)
        ├── forgetter.md  (新增)
        └── ...


Docker (独立部署)
│
└── flatnotes/  (Web 界面容器)
    ├── frontend/  (Vue.js)
    ├── backend/  (Flask)
    └── data/  → 挂载到 $OV/memory/
```

---

## 关键问题解答

### Q1: 记忆模块在哪里？

```
✅ 位置: Atelierr/scripts/memory.py (新增文件)

✅ 内容: 
   • MemoryTree 类
   • add_memory() 函数
   • search_memory() 函数  
   • decay_memories() 函数

✅ 作用:
   • 管理 $OV/memory/ 文件夹
   • 计算 Confidence
   • 自动衰减
   • 分配层级
```

### Q2: 认知模块在哪里？

```
✅ 位置: Atelierr/scripts/cognition.py (新增文件)

✅ 内容:
   • upgrade_to_belief() - 升级到信念
   • generate_question() - 生成问题
   • test_hypothesis() - 测试假设

✅ 存储: $OV/cognition/
   • beliefs/
   • questions/
   • hypotheses/
```

### Q3: Web 交互界面在哪里？

```
✅ 位置: Docker 容器 (独立部署)

✅ 项目: dullage/flatnotes (GitHub)

✅ 部署:
   docker run -d \
     -v $OV/memory:/data \
     flatnotes

✅ 访问: https://memory.yourdomain.com
```

---

## 总结: 三个模块的位置

```
┌──────────────────────────────────────────────┐
│  模块 1: Web 交互界面                        │
│  📍 Docker 容器 (独立部署)                   │
│  📦 dullage/flatnotes                        │
└──────────────────────────────────────────────┘
                    ↓ (读写)
┌──────────────────────────────────────────────┐
│  存储: $OV/memory/ (Markdown 文件)           │
│  📁 /path/to/$OV/memory/                     │
└──────────────────────────────────────────────┘
                    ↓ (管理)
┌──────────────────────────────────────────────┐
│  模块 2: 记忆模块                            │
│  📍 Atelierr/scripts/memory.py (新增)        │
│  🐍 Python 代码                              │
└──────────────────────────────────────────────┘
                    ↓ (调用)
┌──────────────────────────────────────────────┐
│  模块 3: Atelierr 核心                       │
│  📍 Atelierr/.claude/agents/ (现有)          │
│  🤖 15+ Agents                               │
└──────────────────────────────────────────────┘
```

这样清楚了吗？😊
