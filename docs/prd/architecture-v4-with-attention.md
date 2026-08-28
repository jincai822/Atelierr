# 架构设计 v4 — 添加注意力机制（最小改动版）

**版本:** v4.0  
**日期:** 2026-08-27  
**状态:** 添加注意力机制 + 减小认知升级改动  
**核心原则:** 最小改动 + 完全解耦 + 系统稳定

---

## ⚠️ v3 的两个问题

你的反馈非常重要：

### 问题 1: 缺少注意力机制

```
v3 有：KNOW → THINK → ACT → LEARN → UPGRADE

但缺少：注意力分配

问题：
  • 不知道该关注什么
  • 不知道什么重要
  • 信息过载时无法筛选
  • 没有"Attention is All You Need"的机制
```

### 问题 2: v3 改动太大（15%）

```
你说：
  "尽量改动少一点，系统稳定性更好"

v3 问题：
  • 改动 15%（太多）
  • 新增 17 个 Agent（太多）
  • 新增 7 个脚本（太多）
  • 系统复杂度↑ → 稳定性↓
```

---

## 🎯 v4 设计目标

### 1. 添加注意力机制

```
Attention Mechanism（注意力机制）

作用：
  • 自动计算"什么值得关注"
  • 动态分配认知资源
  • 过滤噪音，聚焦重点
  • 提示该看什么、该想什么、该做什么
```

### 2. 减小改动（< 5%）

```
v3: 15% 改动（太多）
v4: < 5% 改动（稳定）

策略：
  • 复用 Atelierr 现有 Agents
  • 合并功能，减少新增
  • 用脚本而不是 Agent
  • 用数据流而不是新模块
```

---

## 🧠 注意力机制设计（核心）

### Attention 的本质

```
Attention = Query × Key → Score → Value

翻译成白话：
  1. Query（查询）: "我现在该关注什么？"
  2. Key（键）: 所有可能关注的对象（Beliefs, Questions, Decisions）
  3. Score（得分）: 计算每个对象的注意力权重
  4. Value（值）: 返回最值得关注的对象
```

### 注意力得分计算

```python
Attention Score = 
    0.4 × Urgency（紧急性）
  + 0.3 × Impact（影响力）
  + 0.2 × Novelty（新颖性）
  + 0.1 × Confidence Gap（信心缺口）

例子：

Belief_001: "asyncio 适合 I/O 密集型"
  • Urgency: 0.8（项目 X 要用，很急）
  • Impact: 0.9（影响整个架构）
  • Novelty: 0.3（已知一段时间）
  • Confidence Gap: 0.4（Confidence 0.6，还不够高）
  ↓
  Attention Score = 0.4×0.8 + 0.3×0.9 + 0.2×0.3 + 0.1×0.4
                  = 0.32 + 0.27 + 0.06 + 0.04
                  = 0.69（中等注意力）

Question_002: "什么时候用 asyncio？"
  • Urgency: 0.9（明天要决策）
  • Impact: 0.9（同上）
  • Novelty: 0.8（刚提出的问题）
  • Confidence Gap: 0.9（完全不确定）
  ↓
  Attention Score = 0.4×0.9 + 0.3×0.9 + 0.2×0.8 + 0.1×0.9
                  = 0.36 + 0.27 + 0.16 + 0.09
                  = 0.88（高注意力，优先处理）
```

### 注意力流（工作方式）

```
每天/每周，系统自动：

1. 扫描所有 Beliefs/Questions/Decisions
2. 计算每个的 Attention Score
3. 排序，取 Top 3-5
4. 生成"今日注意力清单"

输出（每天早上）：
  
  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  📌 今日注意力清单（2026-08-27）
  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  
  🔥 高注意力（立即处理）
    1. Question_002: "什么时候用 asyncio？" 
       (Score: 0.88 | 明天要决策)
  
  ⚡ 中注意力（本周处理）
    2. Belief_001: "asyncio 适合 I/O 密集型"
       (Score: 0.69 | 信心不足，需验证)
    3. Decision_003: "项目 X 用 asyncio"
       (Score: 0.65 | 待执行)
  
  💡 低注意力（监控即可）
    4. Question_005: "如何优化数据库查询？"
       (Score: 0.32 | 不紧急)
```

---

## 🔧 v4 实现（最小改动）

### 策略：复用 + 合并 + 脚本化

```
v3 错误：
  • 新增太多 Agents（17 个）
  • 新增太多命令（3 个）
  • 改动太大（15%）

v4 正确：
  • 不新增 Agent，复用现有的
  • 合并功能到现有命令
  • 用脚本实现核心逻辑
  • 改动 < 5%
```

### v4 架构（最小化）

#### 1. 不新增 Agent（复用现有）

```
v3 新增：
  • Cognition Manager（第 16 个）
  • Cognition Upgrader（第 17 个）

v4 改为复用：
  • Researcher — 负责搜索 Beliefs/Questions
  • Synthesizer — 负责计算 Attention Score 和生成清单
  • Thinker — 负责升级决策（复用已有的决策框架）
  • Challenger — 负责质疑低 Confidence Beliefs
  
  不新增任何 Agent！
```

#### 2. 不新增命令（合并到现有）

```
v3 新增：
  • /belief
  • /question
  • /upgrade

v4 改为合并：
  • /belief + /question → 合并到 /hi（意图路由）
  • /upgrade → 合并到 /daily-reflection（每日自动）
  
  不新增任何命令！
```

#### 3. 用脚本实现（不是 Agent）

```
新增 3 个脚本（而不是 2 个 Agents）：

scripts/attention.py (~300 行)
  • 计算 Attention Score
  • 生成每日注意力清单
  • 更新 Beliefs/Questions 的注意力权重

scripts/cognition_upgrade.py (~400 行)
  • 合并 v3 的 belief_updater + upgrade
  • 贝叶斯更新 Confidence
  • 触发升级事件

scripts/cognition.py (~200 行)
  • CRUD 操作（Beliefs/Questions/Decisions）
  • 简单的数据管理

总计：~900 行（而不是 v3 的 2,000 行）
```

---

## 📊 完整循环（v4 — 含注意力）

```
┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓
┃          完整认知升级循环（6 阶段，含注意力机制）              ┃
┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┛

  ATTENTION     KNOW        THINK       ACT        LEARN      UPGRADE
┌──────────┐ ┌────────┐  ┌────────┐  ┌────────┐  ┌────────┐  ┌────────┐
│ 计算注意力│→│ 存知识  │→│ 思考   │→│ 行动   │→│ 反思   │→│ 升级   │
│          │ │        │  │        │  │        │  │        │  │        │
│Top 3-5  │ │读书    │  │信念    │  │决策    │  │结果    │  │调整    │
│值得关注  │ │论文    │  │问题    │  │执行    │  │经验    │  │信念    │
└──────────┘ └────────┘  └────────┘  └────────┘  └────────┘  └────────┘
     ↑                                                             │
     │                                                             │
     └─────────────────────────────────────────────────────────────┘
                        回到 ATTENTION（更聪明的筛选）
```

### 每个阶段详细说明

#### ATTENTION（注意力分配）⭐ v4 新增

```
每天早上/每周：
  1. 扫描所有 Beliefs/Questions/Decisions
  2. 计算 Attention Score
  3. 生成"今日注意力清单"（Top 3-5）
  4. 推送到 /daily-reflection

输出：
  "今天该关注这 3 个问题"
  "这个 Belief 信心不足，需要验证"
  "这个 Decision 拖太久了，该执行了"
```

#### KNOW（存知识）

```
基于 Attention 清单，优先读取相关知识
  ↓
llm_wiki 生成 Wiki
  ↓
Atelierr 计算 TrustRank
```

#### THINK（思考）

```
基于 Attention 清单，优先思考高分对象
  ↓
形成/更新 Beliefs
  ↓
提出/解决 Questions
```

#### ACT（行动）

```
基于 Attention 清单，优先执行高分 Decisions
```

#### LEARN（反思）

```
记录结果
  ↓
更新 Attention Score
  • 成功 → ↓ Attention（已解决，不需要关注）
  • 失败 → ↑ Attention（需要更多关注）
```

#### UPGRADE（升级）

```
基于 LEARN 结果，自动升级认知
  ↓
升级后，重新计算 Attention Score
```

---

## 💡 完整例子（含注意力）

### 场景：学习 asyncio，但信息过载

```
背景：
  你有 20 个 Beliefs
  你有 15 个 Questions
  你有 10 个 Decisions
  
  总计 45 个对象，信息过载！
  你不知道该关注什么。
```

### 第 1 天早上：ATTENTION

```
系统自动计算 Attention Score：

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
📌 今日注意力清单（2026-08-27）
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

🔥 高注意力（立即处理）
  1. Question_002: "什么时候用 asyncio？"
     Score: 0.88 | 明天要做决策

⚡ 中注意力（本周处理）
  2. Belief_001: "asyncio 适合 I/O 密集型"
     Score: 0.69 | 信心 60%，不够高
  3. Decision_003: "项目 X 用 asyncio"
     Score: 0.65 | 已开放 7 天未执行

💤 其他 42 个对象：注意力低，暂不关注
```

### 第 2 步：KNOW（聚焦）

```
基于注意力清单，你只关注：
  • Question_002
  • Belief_001
  
读相关论文、Wiki
  ↓
llm_wiki 生成 wiki/asyncio_performance.md
```

### 第 3 步：THINK（聚焦）

```
基于新知识，更新 Belief_001：
  "asyncio 适合纯 I/O，混合计算时不如线程池"
  Confidence: 0.6 → 0.75（↑）
  
解决 Question_002：
  创建决策框架
```

### 第 4 步：ACT

```
执行 Decision_003：项目 X 用 asyncio
```

### 第 5 步：LEARN

```
30 天后：
  Satisfaction: 0.85（成功）
  
更新 Attention Score：
  • Belief_001: 0.69 → 0.30（已验证，降低关注）
  • Question_002: 0.88 → 0.10（已解决，降低关注）
```

### 第 6 步：UPGRADE

```
系统自动：
  ↑ Belief_001 Confidence: 0.75 → 0.85
  状态: DRAFT → ACTIVE（激活）
  
  写入 Wiki（L3.5 → L4）
```

### 第 7 天：新的 ATTENTION

```
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
📌 今日注意力清单（2026-09-03）
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

🔥 高注意力（新的焦点）
  1. Question_008: "如何优化数据库查询？"
     Score: 0.82 | 新项目需要

⚡ 中注意力
  2. Belief_005: "Redis 适合缓存"
     Score: 0.58 | 需要验证

注意力自动转移到新问题！✅
```

---

## 📊 v4 vs v3 对比（改动大幅减少）

| 项目 | v3（改动大） | v4（改动小） | 说明 |
|------|-------------|-------------|------|
| **新 Agent** | +2 个 | **0 个** | 复用现有 |
| **新命令** | +3 个 | **0 个** | 合并到现有 |
| **新脚本** | +7 个（2,000 行）| **+3 个（900 行）** | 减少 55% |
| **改动代码** | 15% | **< 5%** | 减少 67% |
| **新功能** | 认知升级 | **认知升级 + 注意力** | 功能更多 |
| **系统稳定性** | 中 | **高** | 改动小 |

---

## 🔧 v4 新增内容清单（最小化）

### 1. 0 个新 Agent（复用现有）

```
复用 Atelierr 现有 15 个 Agents：

Attention 相关：
  • Researcher — 搜索相关 Beliefs/Questions
  • Synthesizer — 计算 Attention Score，生成清单

Cognition 相关：
  • Thinker — 升级决策框架
  • Challenger — 质疑低 Confidence Beliefs
  • Reviewer — 质量审查

不新增任何 Agent！
```

### 2. 0 个新命令（合并到现有）

```
合并策略：

v3: /belief, /question → v4: /hi belief "..."
                             /hi question "..."
                             (通过意图路由)

v3: /upgrade → v4: /daily-reflection（自动升级检查）
                   /weekly（周度升级）

不新增任何命令！
```

### 3. 3 个新脚本（而不是 7 个）

```python
scripts/attention.py (~300 行)
  • 计算 Attention Score（4 维度）
  • 生成每日注意力清单
  • 更新注意力权重

scripts/cognition_upgrade.py (~400 行)
  • 合并 v3 的 upgrade.py + belief_updater.py
  • 贝叶斯更新 Confidence
  • 触发升级事件
  • 调用 attention.py 更新权重

scripts/cognition.py (~200 行)
  • Beliefs/Questions/Decisions CRUD
  • 状态管理
  • SQLite 索引

总计：~900 行
v3 是 2,000 行，减少 55%
```

### 4. 数据存储（不变）

```
$OV/cognition/
├── beliefs/
├── questions/
├── decisions/
└── attention/          ← 新增（注意力清单）
    ├── daily_2026-08-27.md
    └── weekly_2026-W35.md
```

### 5. 集成点（最小侵入）

```
集成到现有命令（微调）：

.claude/commands/daily-reflection.md（微调）
  Step 0: 读取今日注意力清单
  Step 1-7: 现有流程（不变）
  Step 8: 自动升级检查（新增）

.claude/commands/hi.md（微调）
  新增 2 个意图：
    intents.belief
    intents.question
  路由到 cognition.py

.claude/commands/weekly.md（微调）
  Step 0: 读取本周注意力清单
  Step 1-5: 现有流程（不变）
  Step 6: 周度升级（新增）
```

---

## ✅ v4 关键优势

### 1. 功能更强（+注意力）

```
v3: 认知升级
v4: 认知升级 + 注意力机制

注意力解决的问题：
  • 信息过载 → 自动筛选 Top 3-5
  • 不知道该关注什么 → 每日清单
  • 注意力分散 → 聚焦高分对象
  • "Attention is All You Need" ✅
```

### 2. 改动更小（< 5%）

```
v3: 15% 改动
v4: < 5% 改动

策略：
  • 复用现有 Agents（不新增）
  • 合并到现有命令（不新增）
  • 用脚本而不是 Agent
  • 减少代码量（900 行 vs 2,000 行）
```

### 3. 稳定性更高

```
改动小 → 风险小 → 稳定性高

v3 风险：
  • 17 个 Agents（太多，复杂度高）
  • 新增 3 个命令（学习成本高）
  • 2,000 行代码（bug 概率高）

v4 风险：
  • 0 个新 Agent（复杂度不变）
  • 0 个新命令（学习成本为 0）
  • 900 行代码（bug 概率低）
```

### 4. 完全解耦（不变）

```
删除步骤（5 步）：
1. rm -rf $OV/cognition/
2. rm scripts/attention.py scripts/cognition_upgrade.py scripts/cognition.py
3. git revert <3 个微调 commits>

结果：Atelierr 100% 恢复
```

---

## 📊 改动统计（v4 最终）

```
总代码量：~21,400 行
  • Atelierr 核心：20,000 行 (93%)
  • Cognition + Attention (v4)：900 行 (4%)
  • 微调现有命令：500 行 (2%)

改动比例：< 5%

新增文件：3 个脚本
微调文件：3 个命令
新增 Agent：0 个
新增命令：0 个
```

---

## 🎯 v4 总结

```
v4 = v3 的所有功能 + 注意力机制 - 大部分改动

功能：
  ✅ KNOW → THINK → ACT → LEARN → UPGRADE（认知升级）
  ✅ ATTENTION（注意力分配）
  ✅ 完整的 6 阶段闭环

改动：
  ✅ < 5%（v3 是 15%）
  ✅ 0 个新 Agent
  ✅ 0 个新命令
  ✅ 900 行代码（v3 是 2,000 行）
  
稳定性：
  ✅ 改动小 → 风险低 → 稳定性高
  ✅ 复用现有组件 → 学习成本低
  ✅ 完全解耦 → 随时可删除
```

---

**v4 才是最终方案：功能强 + 改动小 + 稳定性高。**

这个设计符合你的要求吗？还有什么需要调整的吗？
