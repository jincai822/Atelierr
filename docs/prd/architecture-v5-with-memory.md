# 架构设计 v5 — 添加记忆模块（完整版）

**版本:** v5.0  
**日期:** 2026-08-27  
**状态:** 添加记忆模块（关键补充）  
**核心原则:** 最小改动 + 完全解耦 + 独立模块

---

## ⚠️ v4 的重大遗漏

### 我漏掉了什么？记忆模块！

```
v4 有：
  • 注意力机制（知道该关注什么）
  • 认知升级（越用越聪明）
  • 完整循环（6 阶段）

但缺少：
  ❌ 记忆模块（Memory）

问题：
  • 系统不记得"你刚才在做什么"
  • 系统不记得"你的习惯和偏好"
  • 系统不记得"上次对话的上下文"
  • 每次都像"失忆"，从零开始
```

### 为什么记忆模块重要？

```
例子 1：工作记忆缺失
  上午 10 点：你在研究 asyncio
  下午 3 点：系统问你"今天想做什么？"
  
  没有记忆 → 系统不知道你上午在做什么
  有记忆 → 系统："继续研究 asyncio？还是切换任务？"

例子 2：长期记忆缺失
  你已经多次尝试晨跑，都失败了
  
  没有记忆 → 系统每次都建议"尝试晨跑"
  有记忆 → 系统："你之前晨跑失败了 3 次，要不试晚跑？"

例子 3：上下文缺失
  你和 AI 对话 10 轮，讨论 asyncio
  第 11 轮，你说"那个问题怎么解决？"
  
  没有记忆 → 系统："哪个问题？"
  有记忆 → 系统："你是说 asyncio 的上下文切换问题吧？"
```

---

## 🧠 记忆模块设计（核心）

### 记忆的 4 个层次

```
┌─────────────────────────────────────────────────────────┐
│                  记忆模块（4 层）                        │
├─────────────────────────────────────────────────────────┤
│                                                          │
│  L1: Working Memory（工作记忆）                          │
│      当前任务、当前会话、最近 1 小时的操作                │
│      存储：内存（RAM）+ 临时文件                          │
│      保留：1-2 小时                                       │
│                                                          │
│  L2: Short-term Memory（短期记忆）                       │
│      最近 7 天的活动、决策、思考                          │
│      存储：$OV/memory/short_term/                        │
│      保留：7 天                                           │
│                                                          │
│  L3: Long-term Memory（长期记忆）                        │
│      重要经验、模式、习惯、偏好                           │
│      存储：$OV/memory/long_term/                         │
│      保留：永久（或用户主动删除）                         │
│                                                          │
│  L4: Episodic Memory（情景记忆）                         │
│      具体事件："2026-08-27 研究 asyncio 失败"            │
│      存储：$OV/memory/episodes/                          │
│      保留：永久，可压缩                                   │
│                                                          │
└─────────────────────────────────────────────────────────┘
```

### 每层详细说明

#### L1: Working Memory（工作记忆）

```
作用：
  记住"你现在在做什么"

内容：
  • 当前任务：正在研究 asyncio
  • 当前会话：和 AI 的对话上下文（最近 10 轮）
  • 最近操作：打开的文件、运行的命令
  • 当前状态：阅读 Paper_123 第 15 页

存储：
  • 内存（RAM）：当前会话
  • $OV/memory/working/current_session.json

保留时间：
  • 1-2 小时
  • 会话结束后自动清理

例子：
  {
    "session_id": "2026-08-27-10:30",
    "current_task": "研究 asyncio vs threading",
    "context": {
      "reading": "papers/asyncio_performance.md",
      "page": 15,
      "recent_questions": [
        "什么时候用 asyncio？",
        "context switch 成本多少？"
      ]
    },
    "recent_operations": [
      {"time": "10:25", "action": "read", "target": "Paper_123"},
      {"time": "10:28", "action": "create_belief", "content": "..."}
    ]
  }
```

#### L2: Short-term Memory（短期记忆）

```
作用：
  记住"最近一周在做什么"

内容：
  • 最近 7 天的任务
  • 最近的决策
  • 最近的反思
  • 最近的注意力焦点

存储：
  $OV/memory/short_term/
    2026-08-27.jsonl
    2026-08-26.jsonl
    ...

保留时间：
  • 7 天
  • 7 天后自动归档到 Long-term Memory（如果重要）

例子：
  # 2026-08-27.jsonl
  {"time": "10:30", "type": "task", "content": "研究 asyncio"}
  {"time": "14:00", "type": "decision", "id": "Decision_003"}
  {"time": "18:00", "type": "reflection", "satisfaction": 0.7}
```

#### L3: Long-term Memory（长期记忆）

```
作用：
  记住"你的习惯、模式、重要经验"

内容：
  • 习惯模式：
    "我是晚间型人格，晚上效率高"
  • 偏好：
    "我喜欢深度工作，不喜欢碎片化任务"
  • 重要经验：
    "asyncio 不适合混合计算 + I/O 的场景"
  • 失败模式：
    "晨跑尝试过 3 次，都失败了"

存储：
  $OV/memory/long_term/
    patterns.jsonl       # 模式
    preferences.jsonl    # 偏好
    lessons.jsonl        # 经验教训
    failures.jsonl       # 失败记录

保留时间：
  • 永久（或用户主动删除）

例子：
  # patterns.jsonl
  {
    "pattern_id": "P001",
    "type": "work_habit",
    "content": "晚间型人格，20:00-23:00 效率最高",
    "evidence": ["Decision_001", "Decision_005", "Decision_010"],
    "confidence": 0.85,
    "created_at": "2026-06-01",
    "last_confirmed": "2026-08-25"
  }

  # failures.jsonl
  {
    "failure_id": "F001",
    "type": "habit_formation",
    "content": "晨跑习惯建立失败",
    "attempts": 3,
    "dates": ["2026-05-01", "2026-06-15", "2026-08-01"],
    "reasons": ["起不来", "效率提升不明显"],
    "lesson": "不适合早起运动，应尝试晚跑"
  }
```

#### L4: Episodic Memory（情景记忆）

```
作用：
  记住"具体事件"

内容：
  • 具体日期 + 具体事件
  • 完整上下文
  • 可回溯

存储：
  $OV/memory/episodes/
    2026-08/
      episode_001.md
      episode_002.md

保留时间：
  • 永久
  • 可压缩（保留摘要，删除细节）

例子：
  # episode_001.md
  ---
  episode_id: EP001
  date: 2026-08-27
  type: research_failure
  ---
  
  # 研究 asyncio 性能，发现假设错误
  
  ## 上下文
  - 目标：选择项目 X 的并发方案
  - 假设：asyncio 比 threading 快 2 倍
  - 信心：0.85
  
  ## 过程
  1. 阅读 3 篇论文
  2. 创建 Belief_001
  3. 做决策 Decision_003
  4. 实际测试
  
  ## 结果
  - asyncio 反而慢 1.5 倍
  - 原因：没考虑 context switch 成本
  
  ## 教训
  - 假设过于简单
  - 应该先做小规模测试
  - 混合计算 + I/O 时，threading 更好
```

---

## 🔄 完整循环（v5 — 7 阶段，含记忆）

```
┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓
┃         完整循环（7 阶段，含记忆 + 注意力 + 认知升级）            ┃
┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┛

   MEMORY      ATTENTION     KNOW        THINK       ACT        LEARN      UPGRADE
┌──────────┐ ┌──────────┐ ┌────────┐  ┌────────┐  ┌────────┐  ┌────────┐  ┌────────┐
│ 加载记忆  │→│ 计算注意力│→│ 存知识  │→│ 思考   │→│ 行动   │→│ 反思   │→│ 升级   │
│          │ │          │ │        │  │        │  │        │  │        │  │        │
│上次做什么│ │Top 3-5  │ │读书    │  │信念    │  │决策    │  │结果    │  │调整    │
│习惯偏好  │ │值得关注  │ │论文    │  │问题    │  │执行    │  │经验    │  │信念    │
└──────────┘ └──────────┘ └────────┘  └────────┘  └────────┘  └────────┘  └────────┘
     ↑                                                                           │
     │                                                                           │
     │                                    写回记忆                                │
     └───────────────────────────────────────────────────────────────────────────┘
```

### 每个阶段与记忆的交互

| 阶段 | 读取记忆 | 写入记忆 |
|------|---------|---------|
| **MEMORY** | ✅ 加载 Working + Short-term | - |
| **ATTENTION** | ✅ 参考 Long-term（习惯、偏好）| ✅ 更新 Working（当前焦点）|
| **KNOW** | ✅ 参考 Long-term（已知领域）| ✅ 更新 Short-term（今日学习）|
| **THINK** | ✅ 参考 Long-term（模式）| ✅ 更新 Working（当前思考）|
| **ACT** | ✅ 参考 Long-term（失败记录）| ✅ 更新 Short-term（今日行动）|
| **LEARN** | ✅ 参考 Episodic（类似经历）| ✅ 创建 Episodic（新事件）|
| **UPGRADE** | ✅ 参考 Long-term（模式）| ✅ 更新 Long-term（新模式）|

---

## 💡 完整例子（含记忆）

### 场景：研究 asyncio（第 2 次）

#### 第 1 次尝试（3 个月前）

```
没有记忆模块时：
  • 研究 asyncio → 失败 → 记录在 Reflections
  • 3 个月后，完全忘了这次失败

有记忆模块：
  • 研究 asyncio → 失败 → 写入 Episodic Memory
  • 提取教训 → 写入 Long-term Memory
```

#### 第 2 次尝试（今天）

```
第 1 步：MEMORY（加载记忆）
  
  系统自动加载：
  • Working Memory: 上次在做什么？
    → 昨天在研究数据库优化
  
  • Short-term Memory: 最近 7 天做了什么？
    → 主要在做项目 X 的架构设计
  
  • Long-term Memory: 有没有相关经验？
    → 找到 Failure_001: "asyncio 研究失败（3 个月前）"
    → 找到 Lesson_001: "asyncio 不适合混合计算 + I/O"
  
  • Episodic Memory: 具体经历？
    → EP001: "2026-05-20 asyncio 测试失败，慢 1.5 倍"

第 2 步：ATTENTION（计算注意力）
  
  系统提示：
  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  📌 今日注意力清单（2026-08-27）
  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  
  🔥 高注意力
    1. Question: "项目 X 用什么并发方案？"
       Score: 0.88 | 明天要决策
  
  ⚠️ 记忆提醒：
    你 3 个月前研究过 asyncio，但失败了（EP001）
    教训：asyncio 不适合混合计算 + I/O
    建议：这次先考虑 threading 或混合方案

第 3 步：THINK（思考，基于记忆）
  
  你看到记忆提醒，想起 3 个月前的失败
  
  新 Belief:
    "对于混合计算 + I/O，threading 可能更好"
    (Confidence: 0.6)
    引用：EP001 + Lesson_001

第 4 步：ACT（决策，避免重复错误）
  
  Decision_010:
    "项目 X 先用 threading，做 benchmark，再决定是否换 asyncio"
    
  而不是：
    "直接用 asyncio"（3 个月前的错误）

第 5 步：LEARN（成功）
  
  30 天后：
    threading 方案成功 ✅
    Satisfaction: 0.85

第 6 步：UPGRADE（更新记忆）
  
  更新 Long-term Memory:
    • Lesson_001 Confidence: 0.6 → 0.85
    • 新 Pattern_002: "我的项目通常是混合计算 + I/O"
  
  创建新 Episodic Memory:
    EP005: "2026-08-27 项目 X 并发方案，threading 成功"

第 7 步：下次遇到类似问题
  
  记忆模块自动提示：
    "你的项目通常是混合计算 + I/O（Pattern_002）"
    "上次用 threading 成功了（EP005）"
    "建议：优先考虑 threading"
```

**关键：有记忆 → 不重复错误 → 越来越聪明 ✅**

---

## 🔧 记忆模块实现（最小改动）

### 策略：独立模块 + 完全解耦

```
你说：
  "记忆模块最好是单独一个模块，和其他模块相互解耦"

v5 设计：
  ✅ 记忆模块完全独立
  ✅ 其他模块可以"读"记忆（只读接口）
  ✅ 记忆模块不依赖其他模块
  ✅ 可以单独删除
```

### 新增内容（v5）

#### 1. 1 个新脚本（独立）

```python
scripts/memory.py (~500 行)

职责：
  • 管理 4 层记忆（Working/Short-term/Long-term/Episodic）
  • 提供只读接口（其他模块调用）
  • 自动归档（Short-term → Long-term）
  • 自动清理（Working Memory）
  • 压缩（Episodic Memory）

API（只读接口）：
  memory.get_working()           # 当前会话
  memory.get_short_term(days=7)  # 最近 7 天
  memory.get_long_term(type)     # 长期记忆（模式/偏好/教训）
  memory.get_episodes(query)     # 情景记忆（搜索）
  
  memory.write_working(data)     # 写入工作记忆
  memory.write_episode(event)    # 创建情景记忆
  memory.update_pattern(pattern) # 更新模式
```

#### 2. 数据存储（独立目录）

```
$OV/memory/                    ← 新增（独立）
├── working/
│   └── current_session.json
├── short_term/
│   ├── 2026-08-27.jsonl
│   └── 2026-08-26.jsonl
├── long_term/
│   ├── patterns.jsonl
│   ├── preferences.jsonl
│   ├── lessons.jsonl
│   └── failures.jsonl
└── episodes/
    ├── 2026-08/
    │   ├── episode_001.md
    │   └── episode_002.md
    └── 2026-07/
```

#### 3. 集成点（微调）

```
其他脚本调用 memory.py：

scripts/attention.py
  + import memory
  + long_term_patterns = memory.get_long_term("patterns")
  + # 参考用户习惯，调整 Attention Score

scripts/cognition_upgrade.py
  + import memory
  + similar_episodes = memory.get_episodes(query="asyncio失败")
  + # 参考历史经历，避免重复错误

.claude/commands/daily-reflection.md
  Step 0: 加载今日记忆（memory.get_short_term(days=1)）
  Step 8: 写入今日情景（memory.write_episode(today_event)）
```

---

## 📊 v5 vs v4 对比

| 项目 | v4 | v5 | 变化 |
|------|----|----|------|
| **新功能** | 注意力 + 认知升级 | **+ 记忆模块** | +33% |
| **新脚本** | +3 个（900 行）| **+4 个（1,400 行）** | +1 个（500 行）|
| **改动代码** | < 5% | **< 6%** | +1% |
| **循环阶段** | 6 阶段 | **7 阶段** | +MEMORY |
| **独立模块** | 2 个（Cognition + Attention）| **3 个（+ Memory）** | 完全解耦 |

**v5 = v4 + Memory（独立模块）**

---

## 🎯 记忆模块的关键优势

### 1. 避免重复错误

```
没有记忆：
  错误 1 → 记录 → 忘记 → 错误 1 再次发生

有记忆：
  错误 1 → Episodic Memory → 下次提示 → 避免 ✅
```

### 2. 提供上下文

```
没有记忆：
  每次对话从零开始，AI 不知道上文

有记忆：
  AI："你昨天在研究 asyncio，今天继续？" ✅
```

### 3. 个性化建议

```
没有记忆：
  通用建议："晨跑提高生产力"

有记忆：
  AI："你晨跑失败过 3 次（F001），试试晚跑？" ✅
```

### 4. 沉淀模式

```
没有记忆：
  每次经验都是独立的

有记忆：
  多次经验 → 提取模式 → Pattern Library ✅
```

---

## ✅ 记忆模块完全解耦

### 独立性验证

```
1. 依赖关系：
   Memory → 无依赖（完全独立）
   Cognition → Memory（只读）
   Attention → Memory（只读）
   Atelierr → 不知道 Memory 存在

2. 删除测试：
   rm -rf $OV/memory/
   rm scripts/memory.py
   
   结果：
   • Atelierr 100% 正常
   • Cognition 降级（无记忆提示，但功能正常）
   • Attention 降级（无习惯参考，但功能正常）

3. 接口清晰：
   Memory 提供只读 API
   其他模块通过 API 调用
   没有循环依赖
```

---

## 📊 改动统计（v5 最终）

```
总代码量：~21,900 行
  • Atelierr 核心：20,000 行 (91%)
  • Cognition + Attention：900 行 (4%)
  • Memory：500 行 (2%)
  • 微调代码：500 行 (2%)

改动比例：< 6%

新增文件：
  • 1 个脚本（memory.py）
  • 1 个数据目录（$OV/memory/）
  • 微调 4 个现有脚本（import memory）

新增 Agent：0 个
新增命令：0 个
```

---

## 🎯 v5 最终总结

```
v5 = v4 + Memory（独立模块）

完整循环（7 阶段）：
  MEMORY → ATTENTION → KNOW → THINK → ACT → LEARN → UPGRADE
      ↑                                                      ↓
      └──────────────────────────────────────────────────────┘

核心功能：
  ✅ 记忆模块（避免重复错误，提供上下文）
  ✅ 注意力机制（解决信息过载）
  ✅ 认知升级（越用越聪明）
  ✅ 完整闭环（持续进步）

设计原则：
  ✅ 改动最小（< 6%）
  ✅ 完全解耦（3 个独立模块）
  ✅ 0 新 Agent
  ✅ 0 新命令
  ✅ 稳定性高
```

---

**v5 才是真正完整的"个人认知与智能系统"。**

包含：
1. ✅ 记忆（Memory）— 记住过去
2. ✅ 注意力（Attention）— 聚焦现在
3. ✅ 认知升级（Upgrade）— 改进未来

这次完整了吗？😊
