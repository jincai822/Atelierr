# 架构设计 v3 — 完整认知升级循环

**版本:** v3.0  
**日期:** 2026-08-27  
**状态:** 添加认知升级循环（修复 v2 重大缺陷）  
**核心原则:** 最小改动 + 完全解耦 + 认知升级

---

## ⚠️ v2 架构的重大缺陷

你说得太对了，我之前的版本有重大缺陷：

| 阶段 | v2 | v3 |
|------|----|----|
| **KNOW** | ✅ 存知识 | ✅ 存知识 |
| **THINK** | ✅ 思考（Beliefs/Questions/Decisions） | ✅ 思考 |
| **ACT** | ✅ 行动 | ✅ 行动 |
| **LEARN** | ❌ 只是反馈打分 | ✅ 反思经验 |
| **UPGRADE** | ❌ **完全缺失** | ✅ **认知升级（核心）** |

**问题：** 知识只进不出，认知永远不升级，等于"超大的笔记系统"，没有智能。

---

## 🎯 认知升级循环（核心设计）

### 完整的 5 阶段循环

```
┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓
┃              完整认知升级循环（5 阶段）                      ┃
┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┛

   KNOW        THINK       ACT        LEARN       UPGRADE
┌────────┐  ┌────────┐  ┌────────┐  ┌────────┐  ┌────────┐
│ 存知识  │→│ 思考   │→│ 行动   │→│ 反思   │→│升级认知│
│        │  │        │  │        │  │        │  │        │
│存储原  │  │形成信念│  │做决策  │  │记录结果│  │改写信念│
│始信息  │  │提出问题│  │执行计划│  │学习经验│  │修正认知│
└────────┘  └────────┘  └────────┘  └────────┘  └────────┘
   ↑                                                    │
   │                                                    │
   └────────────────────────────────────────────────────┘
                    闭环（持续）
```

### 每个阶段详细说明

#### KNOW（存知识）

```
你读了一本书，llm_wiki 生成了 Markdown Wiki 文件。
   ↓
Atelierr 计算 TrustRank。
   ↓
知识存储在 L1-L5 各层。
```

#### THINK（思考）

```
基于 Wiki 中的 Claims，你形成：
   • Beliefs（你相信的陈述）
   • Questions（你困惑的问题）
   • Hypotheses（你的假设）
   ↓
Cognition Manager 自动计算 Confidence 和 Priority。
```

#### ACT（行动）

```
基于 Beliefs 和 Questions：
   • 做决策（用 /decision）
   • 执行计划（GTD 系统）
   • 解决问题（用 Research + Challenger）
```

#### LEARN（反思）

```
行动结果记录：
   • Decision Outcome（成功/失败）
   • Satisfaction Score（满意度 0-1）
   • Lessons Learned（学到的教训）
   • Surprise Markers（意外发现）
   ↓
存储在 $OV/reflections/ (Atelierr 现有的 L2 层)
```

#### UPGRADE（升级认知）⭐ 核心环节

```
基于 LEARN 的结果，自动：
   1. 更新 Belief Confidence
      • 决策成功 → 相关 Beliefs ↑ Confidence
      • 决策失败 → 相关 Beliefs ↓ Confidence
   
   2. 触发 Belieff 状态变化
      • 高 Confidence + 新证据 → 写入 Wiki（L2 → L4）
      • 低 Confidence + 反例 → 标记 QUESTIONED
      • 反复失败 → 触发 REVISION_REQUEST
   
   3. 升华到 Wiki
      • Beliefs → Wiki Claims
      • Lessons Learned → Wiki Entries
      • Frameworks → Wiki Patterns
   
   4. 触发新 Questions
      • 发现未知 → 新 Questions
      • 假设错误 → 新 Research
```

---

## 🔧 实现细节（升级循环）

### 新增 1 个工作流（核心）

```
/upgrade — 认知升级工作流

输入：
   • LEARN 阶段的反思记录
   • Decision 的执行结果
   • 新的 Wiki 证据

输出：
   • 更新的 Beliefs（Confidence 变化）
   • 新升的 Wiki Entries
   • 触发的 Questions
   • 认知健康报告

时机：
   • 手动触发：/upgrade
   • 自动触发：满足条件时（如决策完结、重大 Wiki 更新）
   • 周/月度：定期升级
```

### 新增 1 个 Agent（核心）

```
Cognition Upgrader（认知升级器）

职责：
   1. 检测认知不一致
      • Belief 和 Decision 结果矛盾
      • Wiki 新证据 vs 现有 Belief
   
   2. 自动调整 Confidence
      • 学习曲线建模
      • 贝叶斯更新
   
   3. 触发升级事件
      • 新 Wiki Entry
      • 新 Question
      • Belieff 状态变化

Le Cercle 原型：
   The Evolutionist (Degas Studio) — 推动认知进化的催化者
```

### 升级循环的具体例子

#### 例子：从失败决策到认知升级

```
第 1 周（KNOW）：
   你读了论文，形成 Belief：
     "asyncio 比 threading 快 2 倍" (Confidence: 0.85)

第 2 周（THINK）：
   创建 Decision：
     "在项目 X 用 asyncio 而不是 threading"
     关联 Belief_001（Confidence: 0.85）

第 3 周（ACT）：
   执行 Decision：项目 X 用 asyncio
   记录执行过程

第 4 周（LEARN）：
   结果：asyncio 反而慢了 1.5 倍
   Satisfaction: 0.3（很低）
   Lessons Learned:
     • 假设"fast I/O = fast"过于简单
     • 没考虑 context switch 成本

   ↓
   自动检测到：Decision 结果与 Belief 矛盾
   
第 5 周（UPGRADE）：
   系统自动：
   1. ↓ Belief_001 Confidence: 0.85 → 0.45
      状态：DRAFT → QUESTIONED
   
   2. 创建新 Wiki Entry：
      "asyncio vs threading 选择的边界条件"
      Claims:
        [C1] 纯 I/O 密集：asyncio 快 2-3 倍
        [C2] I/O + 计算混合：threading 更快
        [C3] context switch 成本>节省时，反转
      引用：原 Belief_001 + Decision_001 outcome
   
   3. 创建新 Question：
      "我的项目应该用 asyncio 还是线程池？"
      Priority: HIGH
   
   4. 触发新 Research：
      "查找更好的并发决策框架"
```

### 升级触发器（5 种自动触发）

```
1. Outcome Contradiction（结果矛盾）
   条件: Satisfaction < 0.4
        AND Decision 关联的 Beliefs
   动作: ↓ Belief Confidence, 创建新 Question

2. Strong Confirmation（强烈确认）
   条件: Satisfaction > 0.8
        AND 多次确认
        AND Belief Confidence < 0.7
   动作: ↑ Belief Confidence, 考虑写入 Wiki

3. New Evidence（新证据）
   条件: 新 Wiki Entry 与 Belief 相关
   动作: 重新评估 Belief, 可能更新 Confidence

4. Stagnation（停滞）
   条件: Question 开放 > 30 天
        AND Priority > 0.5
   动作: 提示用户, 建议采取行动

5. Cross-domain Pattern（跨域模式）
   条件: 多个 Domain 的 Lessons Learned 有相似模式
   动作: 提议创建 Pattern Library Entry
```

---

## 📊 升级循环的架构优势

### 1. 实现真正的"智能"

```
传统笔记系统（v2）：
   存知识 → 思考 → 决策 → 反思 → 结束

认知升级系统（v3）：
   存知识 → 思考 → 决策 → 反思 → 升级 → 更好的存知识
                ↑                              ↓
                └──────────────────────────────┘
                     越用越聪明
```

### 2. 自动从错误中学习

```
传统：决策失败了 → 记录下来 → 再也不看
v3：决策失败了 → 自动 ↓ Belief → 触发新研究 → 下次更好
```

### 3. 知识自动沉淀

```
传统：好经验只存在脑海里
v3：好经验自动 → Wiki Entry → TrustRank 提升 → 影响其他思考
```

### 4. 跨项目复用

```
传统：经验 1 在项目 A，经验 2 在项目 B，互不相关
v3：经验 1 + 经验 2 → 检测到相似模式 → 创建 Pattern → 影响所有项目
```

---

## 🔌 数据流（升级循环视角）

```
                Atelierr                    Cognition Layer
┌──────────────────────────┐      ┌──────────────────────────────┐
│                           │      │                              │
│  L4 Wiki (Claims, Trust) │─────→│  READ TrustRank for Beliefs  │
│                           │      │                              │
│  L3 Papers (Evidence)     │─────→│  USE Evidence for Confidence │
│                           │      │                              │
│  L2 Reflections           │─────→│  ANALYZE Lessons Learned     │
│  (Session outputs)        │      │                              │
│                           │      │                              │
│  L2 Decisions/Outcomes    │─────→│  TRACK Satisfaction Score    │
│                           │      │                              │
│  GTD/WIP/Research         │─────→│  DETECT New Questions        │
│                           │      │                              │
└──────────────────────────┘      │                              │
         ↑                         │                              │
         │                         │                              │
         │ WRITE BACK               │                              │
         │ (After Upgrade)         │                              │
         │                         │                              │
         │                         │  WRITE BACK (Approved)       │
         │←─────────────────────────│                              │
         │                         │                              │
         │  • New Wiki Entries    │                              │
         │  • Updated Wiki Claims  │                              │
         │  • Invalidated Markers  │                              │
         │                         │                              │
         └─────────────────────────→│                              │
                                   │                              │
                              UPDATE                              │
                              Beliefs                            │
                              Questions                           │
                              Decisions                           │
                                   ↓                              │
                              TRIGGER                             │
                              New Research                        │
                              New Decisions                       │
                              New Questions                       │
                                                                  │
└──────────────────────────────────────────────────────────────────┘
```

**升级循环数据流要点：**

1. **Atelierr → Cognition**（被动，只读）
   - 读 TrustRank 用于 Belief Confidence
   - 读 Evidence 用于验证
   - 读 Reflections 用于分析

2. **Cognition → Atelierr**（主动，写回，但需用户批准）
   - 创建新 Wiki Entry（需要 `/promote` 工作流 + 用户批准）
   - 更新 Wiki Claim（需要 `/promote` 工作流）
   - 标记 invalid_at（写入带时间戳的标记）

3. **Cognition 内部循环**（自动）
   - 更新 Beliefs
   - 更新 Questions
   - 更新 Decisions
   - 触发新研究/决策

---

## 🆕 新增内容对比（v2 vs v3）

| 项目 | v2 | v3 | 变化 |
|------|----|----|------|
| **AI 智能体** | 16 个（含 Cognition Manager）| 17 个（+ Cognition Upgrader）| +1 个 |
| **命令** | 23 个 | 24 个（+ /upgrade）| +1 个 |
| **脚本** | 60 个 | 64 个（+ 4 个升级循环相关）| +4 个 |
| **数据层** | L3.5 (Cognition) | L3.5 + Upgrade Events Stream | +1 个 |
| **循环** | KNOW→THINK→ACT→LEARN | KNOW→THINK→ACT→LEARN→UPGRADE | 添加升级 |

### v3 新增内容清单

#### 1. 1 个 AI 智能体（第 17 个）

```
Cognition Upgrader（认知升级器）

职责：
  • 自动检测认知不一致
  • 调整 Belief Confidence（贝叶斯更新）
  • 触发升级事件
  • 提议新 Wiki Entry
  • 检测跨域模式

Le Cercle 原型：
  The Evolutionist (Degas Studio)

输入：
  • Reflections (LEARN 输出)
  • Decision Outcomes
  • Wiki Evidence
  • TrustRank Changes

输出：
  • Updated Beliefs (with Confidence)
  • Wiki Promotion Candidates
  • New Questions (Research)
  • Cognitive Health Report
```

#### 2. 1 个新命令

```
/upgrade — 认知升级工作流

子命令：
  /upgrade auto       — 自动检测升级事件
  /upgrade check      — 手动检查
  /upgrade apply      — 应用升级建议
  /upgrade review     — 审查所有 pending 升级

触发时机：
  手动：用户主动调用
  自动：满足升级触发器时
  定期：每周/每月一次
```

#### 3. 1 个新工作流（集成到 /hi）

```
Intent: upgrade (意图路由)

路由到：.claude/commands/upgrade.md

Patterns (触发短语):
  • "upgrade my cognition"
  • "update my beliefs based on recent learnings"
  • "apply lessons learned"
  • "improve my decision-making"
  • "从最近的学习中升级信念"
  • "根据经验调整我的信念"
  • "应用学到的教训"
```

#### 4. 4 个新脚本

```python
scripts/upgrade.py (~500 行)
  • 主升级工作流
  • 调用其他 3 个脚本

scripts/belief_updater.py (~400 行)
  • Belief Confidence 贝叶斯更新
  • 触发器逻辑
  • 状态转换

scripts/cross_pattern.py (~300 行)
  • 跨域模式检测
  • 相似性分析
  • 提议 Pattern Library Entry

scripts/upgrade_report.py (~200 行)
  • 升级报告生成
  • 认知健康度量
  • 可视化数据导出
```

#### 5. 升级事件流（数据流）

```
$OV/cognition/
├── beliefs/
├── questions/
├── decisions/
└── upgrades/              ← 新增
    ├── event_001.jsonl    ← 升级事件流
    ├── event_002.jsonl
    └── pending/           ← 待审核升级
        ├── wiki_promote_001.md
        └── belief_update_001.md
```

---

## ✅ 改动统计（v3）

```
总代码量：~23,500 行
  • Atelierr 核心：20,000 行 (85%)
  • Cognition Layer (v2)：1,500 行 (6%)
  • Upgrade Loop (v3 新增)：2,000 行 (9%)

改动比例：15% （v2 是 7.5%）

改动文件：8 个
  • 5 个微调（v2 同）
  • 3 个新增（升级相关）
```

---

## 🎯 v3 关键优势

### 1. 真正实现 KNOW→THINK→ACT→LEARN→UPGRADE 闭环

```
v2: 知识 → 思考 → 行动 → 反思 (结束)
v3: 知识 → 思考 → 行动 → 反思 → 升级 → 更好的知识
```

### 2. 自动从错误中学习

```
传统：决策失败 → 记录 → 结束
v3：决策失败 → 自动 ↓ Belief → 触发研究 → 下次更聪明
```

### 3. 知识自动沉淀

```
v2: Beliefs 只存在 Cognition Layer 里
v3: 高 Confidence Beliefs 自动写入 Wiki（L4），影响 TrustRank
```

### 4. 跨域洞察

```
v2: 每次反思只能看到当前 Decision
v3: 跨项目/领域检测模式，自动提议通用框架
```

### 5. 避免"超大的笔记系统"

```
v2: 知识越积越多，认知不变
v3: 知识通过升级循环，持续提升认知质量
```

---

## ❓ 仍然完全解耦

### 删除测试（v3 版本）

```bash
# Step 1: 删除数据目录
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
```

---

## 💡 完整的升级循环示例（端到端）

### 场景：重新评估"晨跑"习惯

```
第 1 月（KNOW）：
   读到研究"晨跑提高生产力"，形成 Belief：
     "晨跑让我工作更高效" (Confidence: 0.6)

第 2 月（THINK+ACT）：
   决定：尝试晨跑 30 天
   Decision: "每天 6:30 晨跑 30 分钟"

第 3 月（LEARN）：
   30 天后：
   • 实际跑：18/30 天（12 天没起床）
   • 满意度：0.3
   • 工作效率：提升有限
   Lessons:
     • "我早上起不来"
     • "效率提升不明显"

   ↓
   系统检测到：
     • Satisfaction (0.3) << Belief Confidence (0.6)
     • 触发器 1: Outcome Contradiction

第 4 月（UPGRADE）自动执行：

   1. ↓ Belief_001 Confidence: 0.6 → 0.35
      状态: DRAFT → QUESTIONED
      
   2. 创建新 Wiki Entry：
      "晨跑习惯的有效性边界条件"
      Claims:
        [C1] 对大多数人有效（证据：3 篇论文）
        [C2] 需要 > 21 天才能形成习惯
        [C3] 早晨型人格效果更显著 (证据: Chronotype 研究)
        [C4] 晚间型人格可能不如晚练或午练
      引用: Belief_001 + Decision 反思

   3. 创建新 Questions:
      "我应该晚上跑还是中午跑？" (Priority: HIGH)
      "怎样提高起床成功率？" (Priority: MEDIUM)

   4. 自动研究触发:
      Research task: "查找晚间型人格的运动最佳实践"

   5. Cognitive Health Report:
      ⚠️ Warning: Belief_001 decreased significantly
      📊 Update: Created 2 new research directions
      💡 Suggestion: Try evening runs next month

第 5 月（基于升级的 KNOW）：
   读到自己创建的 Wiki Entry:
     "早晨型人格效果更显著"
   ↓
   新 Belief: "我是晚间型，晚跑更适合我" (Confidence: 0.7)
   ↓
   新 Decision: "尝试晚跑 30 天"
   ↓
   循环继续，认知提升
```

**这个例子展示了：**
1. ✅ 知识存储
2. ✅ 基于知识思考
3. ✅ 行动（决策）
4. ✅ 反思（学习）
5. ✅ 升级认知（核心）
6. ✅ 基于升级后的认知，再次行动（更好）
7. ✅ 持续循环，认知越来越精准

---

## 🎯 总结：v2 vs v3

```
v2 (我的错误设计)：
  ❌ 只有 4 个阶段：KNOW→THINK→ACT→LEARN
  ❌ 没有真正的"智能"
  ❌ 知识只进不出
  ❌ 不能从错误中学习

v3 (你的反馈修正)：
  ✅ 完整 5 阶段：KNOW→THINK→ACT→LEARN→UPGRADE
  ✅ 真正实现"持续智能"
  ✅ 知识通过升级循环持续优化
  ✅ 自动从错误中学习，认知越来越精准
```

---

**v3 才是完整的"个人认知与智能系统"。**

如果同意这个升级设计，我再更新所有架构文档。是否还有其他你觉得重要的环节？
