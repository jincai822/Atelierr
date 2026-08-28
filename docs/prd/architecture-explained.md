# 架构说明（大白话版 v3 — 含认知升级循环）

**版本:** v3.0  
**日期:** 2026-08-27  
**目的:** 用最简单的语言说清楚完整设计（含认知升级）

---

## 🎯 你想要什么？（一句话）

**你想要：** 在 Atelierr 基础上，加一个**认知管理 + 自动升级**系统，管理你的信念、问题、决策，并且**自动从经验中学习**，让认知越来越聪明。

---

## 🚨 v2 的关键问题（我刚意识到）

**我之前的设计是错的：**

```
v2 (错): KNOW → THINK → ACT → LEARN (结束)

这等于"超大的笔记系统"，知识存了就完了
没用！
```

**v3 (对):**

```
KNOW → THINK → ACT → LEARN → UPGRADE → 更好的 KNOW
 ↑                                          ↓
 └──────────────────────────────────────────┘

从经验中自动学习，认知持续升级！
```

---

## 🏠 用学习做比喻

### Atelierr 本身（已存在）

```
你有一所学校（Atelierr）：
  • 15 个老师（AI 智能体）
  • 21 种课程（命令）
  • 5 层图书馆（L1-L5）
  • 信任评分系统（TrustRank）
  
学校运转很好，但是：
  ❌ 老师只教书，不记录学生的"个人理解"
  ❌ 学生读完书就完了，没有"持续进步"机制
```

### v3 新增的（Cognition Layer）

```
在学校加一个"个人学习中心"：

1️⃣ 三本个人笔记
   • 信念本（Beliefs）
   • 问题本（Questions）
   • 决策本（Decisions）

2️⃣ 智能助手（Cognition Upgrader）
   自动检测、自动升级
```

---

## 📚 Atelierr 是什么？（5 句话说清楚）

### 1. Atelierr = 你的个人知识管理系统

就像一个**智能图书馆+学校**，帮你管理笔记、阅读、反思、决策。

### 2. 它有 5 层仓库（L1-L5）

```
L5 — 教科书级别（暂时空）
L4 — 你确认无误的知识（Wiki，最可信）
L3 — 论文、文章（有外部证据）
L2 — 你的日常笔记、想法
L1 — 随手记录、待处理的东西
```

### 3. 它有 15 个 AI 工人（Le Cercle）

每个工人有自己的专长（研究员、编辑、辩论对手、收纳师、侦察兵等）。

### 4. 它有一个"信任引擎"（TrustRank）

**作用：** 给知识打分，告诉你哪些可信。
- 有外部证据 → 高分
- 只有自己说 → 低分

### 5. 它有 21 个命令

`/hi` `/daily-reflection` `/weekly` `/read` `/decision` 等。

---

## 🆕 v3 想加什么？（3 个本子 + 1 个升级器）

### 三个本子（v2 就有了，v3 保留）

```
1️⃣ 信念本（Beliefs）
   记录你相信的陈述
   "Python asyncio 适合 I/O 密集型" → 可信度 85%

2️⃣ 问题本（Questions）
   记录待解决的问题
   "什么时候用 asyncio？" → 优先级 0.78

3️⃣ 决策本（Decisions）
   记录决策和结果
   "选 asyncio" → 满意度 90%
```

### ⭐ 1 个升级器（v3 新增，核心！）

```
Cognition Upgrader（认知升级器）

作用：自动从经验中学习

什么时候工作？
1. 你做完决策，记录了结果
2. 升级器自动工作
3. 根据结果调整你的信念

具体做什么？

  决策成功 → ↑ 相关信念的可信度
  决策失败 → ↓ 相关信念的可信度
  多次确认 → 把信念写入 Wiki（L4）
  发现反例 → 标记信念为 QUESTIONED
  跨域模式 → 创建 Pattern Library
```

---

## 🔄 完整循环（v3 核心）

```
┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓
┃        完整认知升级循环（5 阶段，闭环）              ┃
┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┛

    KNOW        THINK       ACT        LEARN       UPGRADE
 ┌────────┐  ┌────────┐  ┌────────┐  ┌────────┐  ┌────────┐
 │  存知识  │→│  思考   │→│  行动   │→│  反思   │→│  升级   │ │
 │        │  │        │  │        │  │        │  │        │ │
 │存书、读 │  │形成信念│  │做决策  │  │记结果  │  │改信念  │ │
 │论文    │  │提问题  │  │执行    │  │学习    │  │写Wiki  │ │
 └────────┘  └────────┘  └────────┘  └────────┘  └────────┘
                                                        │
                                                        ↓
                                                   回到 KNOW
                                                  （更聪明了）
```

### 每个阶段详细说明

#### KNOW（存知识）

```
你读了一本 asyncio 的书
  ↓
llm_wiki 生成 wiki/python_asyncio.md
  ↓
Atelierr 计算 TrustRank: 0.92（很可信）
```

#### THINK（思考）

```
基于 Wiki 中的 Claims：
  • 形成 Belief: "asyncio 适合 I/O 密集型" (Confidence: 0.85)
  • 提出 Question: "什么时候用 asyncio？"
  ↓
Cognition Manager 自动计算 Confidence 和 Priority
```

#### ACT（行动）

```
基于 Belief 和 Question：
  • 做决策: "项目 X 用 asyncio"
  • 执行: 实际写代码、测试
```

#### LEARN（反思）

```
执行完记录结果：
  • Satisfaction: 0.3（失败）
  • 原因: "实际反而更慢"
  • Lessons: "没考虑 context switch 成本"
```

#### UPGRADE（升级认知）⭐ v3 核心

```
升级器自动工作：

1. ↓ Belief_001 Confidence: 0.85 → 0.45
   状态：DRAFT → QUESTIONED（质疑中）

2. 创建新 Wiki Entry:
   "asyncio vs threading 选择的边界条件"
   包含多个 Claims，标注证据

3. 创建新 Question:
   "我的项目应该用 asyncio 还是线程池？" (Priority: HIGH)

4. 触发新 Research:
   "查找更好的并发决策框架"

5. 认知健康报告:
   ⚠️ Belief 显著下降
   📊 创建了 2 个新研究方向
```

### 然后回到 KNOW（更聪明）

```
你读到自己创建的 Wiki Entry:
  "asyncio 适合纯 I/O，混合计算时不如线程池"
  ↓
更新 Belief: "具体场景要具体分析" (Confidence: 0.75)
  ↓
下次做决策会更精准
```

---

## 💡 完整例子：晨跑决策

### 第 1 月：KNOW

```
读到研究论文，形成 Belief:
  "晨跑提高生产力" (Confidence: 0.6)
```

### 第 2 月：THINK + ACT

```
创建 Decision:
  "每天 6:30 晨跑 30 分钟"
  ↓
基于 Belief_001（Confidence: 0.6）
```

### 第 3 月：LEARN

```
30 天结果：
  • 实际跑：18/30 天（12 天没起床）
  • 工作效率：提升有限
  • Satisfaction: 0.3

Lessons:
  • "我早上起不来"
  • "效率提升不明显"

  ↓
  升级器检测到：
  Satisfaction (0.3) << Belief Confidence (0.6)
  触发器 1: Outcome Contradiction
```

### 第 4 月：UPGRADE ⭐ 自动执行

```
1. ↓ Belief_001 Confidence: 0.6 → 0.35
   状态: DRAFT → QUESTIONED

2. 创建新 Wiki Entry:
   "晨跑习惯的有效性边界条件"
   Claims:
     [C1] 对大多数人有效（3 篇论文证据）
     [C2] 需要 > 21 天形成习惯
     [C3] 早晨型人格效果更显著
     [C4] 晚间型可能不如晚练
   TrustRank: 高

3. 创建新 Questions:
   "我应该晚上跑还是中午跑？" (Priority: HIGH)
   "怎样提高起床成功率？" (Priority: MEDIUM)

4. 触发新 Research:
   "查找晚间型人格的运动最佳实践"

5. Cognitive Health Report:
   ⚠️ Warning: Belief_001 显著下降
   💡 Suggestion: 尝试晚跑
```

### 第 5 月：基于升级的 KNOW

```
读到自己创建的 Wiki Entry
  ↓
新 Belief: "我是晚间型，晚跑更适合" (Confidence: 0.7)
  ↓
新 Decision: "尝试晚跑 30 天"
  ↓
认知升级 ✅
```

**这就是完整的闭环！从失败中学到东西，认知越来越精准。**

---

## 🔧 实现细节（v3）

### 新增 1 个 Agent（第 17 个）

```
Cognition Upgrader（认知升级器）

职责：
  1. 自动检测认知不一致
  2. 贝叶斯更新 Belief Confidence
  3. 触发 Wiki 提升
  4. 提议 Pattern Library Entry
  5. 生成认知健康报告

Le Cercle 原型：
  The Evolutionist (Degas Studio)
```

### 新增 1 个命令

```
/upgrade

子命令：
  /upgrade check    — 手动检查升级机会
  /upgrade apply    — 应用升级建议
  /upgrade report   — 查看认知健康报告
```

### 新增 4 个脚本

```python
scripts/upgrade.py           # 主升级工作流
scripts/belief_updater.py    # 贝叶斯更新 Belief Confidence
scripts/cross_pattern.py     # 跨域模式检测
scripts/upgrade_report.py    # 升级报告生成
```

### 新增数据流

```
$OV/cognition/upgrades/
├── events.jsonl      # 升级事件流
├── pending/          # 待审核升级
│   ├── wiki_promote_001.md
│   └── belief_update_001.md
```

---

## 📊 v3 vs v2 对比

| 项目 | v2 (错) | v3 (对) |
|------|---------|---------|
| **循环** | 4 阶段，开环 | **5 阶段，闭环** |
| **核心** | 知识管理 | **认知升级** |
| **新 Agent** | 16 个 | **17 个（+Upgrader）** |
| **新命令** | 2 个 | **3 个（+/upgrade）** |
| **新脚本** | 3 个 | **7 个（+4 个升级）** |
| **总改动** | 7.5% | **15%** |
| **智能度** | 普通笔记系统 | **真正"越用越聪明"** |

---

## ✅ v3 仍然完全解耦

### 删除测试

```bash
# Step 1: 删除数据
rm -rf $OV/cognition/

# Step 2: 删除脚本
rm scripts/belief.py scripts/question.py scripts/cognition.py
rm scripts/upgrade.py scripts/belief_updater.py scripts/cross_pattern.py scripts/upgrade_report.py

# Step 3: 删除命令
rm .claude/commands/belief.md .claude/commands/question.md
rm .claude/commands/upgrade.md

# Step 4: 删除 Agents
rm .claude/agents/cognition-manager.md
rm .claude/agents/cognition-upgrader.md

# Step 5: 回退微调
git revert <微调 commits>

# 验证：Atelierr 100% 恢复
```

---

## 🎯 v3 关键优势（用白话讲）

```
v2 = 超大的笔记本（记录但不进化）

v3 = 越用越聪明的个人认知系统：
  • 自动从错误中学习
  • 自动从成功中提炼经验
  • 自动把好经验变成 Wiki（影响 TrustRank）
  • 自动检测跨域模式
  • 自动建议研究方向
  • 持续循环，认知永远在升级
```

---

## 📊 改动统计（v3）

```
总代码量：~23,500 行
  • Atelierr 核心：20,000 行 (85%)
  • Cognition Layer (v2)：1,500 行 (6%)
  • Upgrade Loop (v3 新增)：2,000 行 (9%)

改动比例：15%
```

---

**v3 才是完整的"个人认知与智能系统"。**

你的反馈非常重要 — **认知升级是核心**！还有没有其他你觉得重要的环节？