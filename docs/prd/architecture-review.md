# PRD v0.2 架构深度审查

**审查日期:** 2026-08-26  
**审查人:** AI Assistant + User  
**文档版本:** PRD v0.2  
**目的:** 深入对齐架构细节，识别潜在问题，细化技术决策

---

## 审查方法

我们将按照以下维度审查：
1. **架构一致性** — 各模块职责是否清晰，边界是否明确
2. **可行性验证** — 技术方案是否可实施，性能目标是否可达成
3. **接口设计** — 模块间接口是否完整，契约是否清晰
4. **数据流** — 数据在各模块间如何流转，是否有遗漏
5. **错误处理** — 异常情况如何处理，降级策略是否完善
6. **演进路径** — V0 → V1 → V2 是否合理，是否有技术债务

---

## 🔍 审查问题清单

### A. 核心架构问题

#### A1. 三模块架构的职责边界

**问题：Module 1 (Cognition Core) 和 Module 4 (Knowledge Vault) 的职责边界是否清晰？**

**当前设计：**
- Module 1: Belief/Question/Decision 管理
- Module 4: Claim/Source/TrustRank 管理

**潜在问题：**
- Belief 基于 Claims，那么 Belief 的创建流程跨越两个模块？
- TrustRank 影响 Belief 的 Confidence，这个依赖关系如何处理？

**需要明确：**
```
场景：用户看到新的 Claim，想基于它创建 Belief

方案 A: Cognition Core 主动查询 Knowledge Vault
  User → Cognition Core.create_belief(statement, [claim_ids])
  Cognition Core → Knowledge Vault.get_claims([claim_ids])
  Cognition Core → 验证 Claims 存在
  Cognition Core → 创建 Belief

方案 B: Knowledge Vault 提供组合接口
  User → Knowledge Vault.create_belief_from_claims(statement, [claim_ids])
  Knowledge Vault → 内部验证 + 创建
  Knowledge Vault → 返回 Belief

推荐方案：A（职责清晰，Cognition Core 是业务逻辑层）
```

**建议：**
- ✅ 明确 Cognition Core 是业务逻辑层
- ✅ Knowledge Vault 是数据访问层
- ✅ 添加接口设计图，展示调用链

---

#### A2. Support Tools 的调用时机

**问题：Support Tools 何时被调用？由谁调用？**

**当前描述：**
- scripts/context_bundle.py — "Cognition Core 需要上下文时"
- scripts/semantic.py — "Knowledge Vault 查询时"
- scripts/trustrank.py — "Knowledge Vault 摄入新知识后"

**潜在问题：**
- 这些调用是同步还是异步？
- 如果 scripts 失败，主流程如何处理？
- 是否有性能瓶颈（例如 TrustRank 计算很慢）？

**需要明确：**

```yaml
context_bundle.py:
  调用者: Module 1 (Cognition Core)
  调用时机: create_belief(), make_decision() 等需要上下文时
  调用方式: 同步调用
  失败处理: 降级到无上下文模式
  性能目标: < 500ms

semantic.py:
  调用者: Module 4 (Knowledge Vault)
  调用时机: query_claims() 时
  调用方式: 同步调用
  失败处理: 降级到关键词搜索
  性能目标: < 200ms

trustrank.py:
  调用者: Module 4 (Knowledge Vault)
  调用时机: ingest_wiki_page() 后
  调用方式: 异步调用（后台任务）
  失败处理: 使用默认 trust 值
  性能目标: < 10s (1000 claims)
```

**建议：**
- ✅ 明确每个 Tool 的调用契约
- ✅ 定义失败降级策略
- ✅ 考虑异步化 TrustRank 计算

---

#### A3. llm_wiki 依赖的鲁棒性

**问题：如果 llm_wiki 不可用，系统如何工作？**

**当前设计：**
- File Watcher 监听 llm_wiki 输出
- HTTP API 查询 llm_wiki

**潜在风险：**
- llm_wiki 崩溃 → File Watcher 无新文件
- llm_wiki API 不可用 → HTTP API 查询失败
- llm_wiki 数据损坏 → 摄入错误数据

**需要明确：**

```yaml
llm_wiki 不可用的场景:
  场景 1: llm_wiki 未启动
    影响: 
      - 无法摄入新知识（可接受，V0 MVP）
      - 无法使用 llm_wiki API 查询（降级到本地 semantic.py）
    处理:
      - File Watcher 继续运行，等待 llm_wiki 启动
      - HTTP API 调用返回 connection error，降级到本地查询
  
  场景 2: llm_wiki API 失败
    影响:
      - 查询功能不可用
    处理:
      - 降级到本地 scripts/semantic.py
      - 记录错误日志
  
  场景 3: llm_wiki 生成错误数据
    影响:
      - 摄入错误的 Claims
    处理:
      - TrustRank 会降低错误 Claims 的 trust 值
      - 用户可手工删除错误的 Beliefs
```

**建议：**
- ✅ 明确 llm_wiki 不可用时的降级策略
- ✅ File Watcher 应该有健康检查（检测 llm_wiki 是否运行）
- ✅ HTTP API 调用应该有超时和重试机制
- ⚠️ 考虑是否需要"离线模式"（完全不依赖 llm_wiki）

---

### B. 数据流问题

#### B1. Belief 创建的完整数据流

**问题：从 llm_wiki 输出到 Belief 创建的完整数据流是什么？**

**需要梳理：**

```
Step 1: llm_wiki 生成知识
  llm_wiki 处理 PDF → 生成 wiki/programming/python-asyncio.md
  内容包含:
    - title: "Python asyncio 编程模型"
    - source: "/path/to/fluent-python.pdf"
    - created: "2026-08-20"
    - 正文: Markdown 格式的知识

Step 2: File Watcher 检测
  File Watcher 检测到 wiki/programming/python-asyncio.md 创建
  触发: ingest_wiki_page("wiki/programming/python-asyncio.md")

Step 3: Knowledge Vault 摄入
  Module 4.ingest_wiki_page():
    1. 读取 Markdown 文件
    2. 解析 YAML frontmatter
    3. 提取 Claims（如何提取？规则是什么？）
    4. 创建 Source 记录
    5. 创建 Claim 记录
    6. 触发 TrustRank 计算（异步）
    7. 存储到 Markdown + SQLite

Step 4: 用户创建 Belief
  User → CLI: cognition belief create "Python asyncio 适合 I/O 密集型任务"
  CLI → Module 1.create_belief(statement, [claim_ids])
  Module 1:
    1. 查询 Module 4.get_claims([claim_ids])
    2. 验证 Claims 存在
    3. 计算初始 Confidence（基于 Claims 的 Trust）
    4. 创建 Belief 记录
    5. 存储到 Markdown + SQLite

Step 5: Belief 更新
  User 看到新的证据 → 更新 Belief
  CLI → Module 1.update_belief(belief_id, new_confidence, new_claims)
  Module 1:
    1. 加载 Belief
    2. 查询新的 Claims
    3. 重新计算 Confidence
    4. 记录变化历史
    5. 更新 Markdown + SQLite
```

**潜在问题：**
- **Claim 提取规则不明确** — llm_wiki 的 Markdown 如何转换为 Claim？
- **Confidence 计算公式未定义** — 如何从 Claims 的 Trust 计算 Belief 的 Confidence？

**建议：**
- ⚠️ **必须定义 Claim 提取规则**
- ⚠️ **必须定义 Confidence 计算公式**

---

#### B2. Claim 提取规则

**问题：如何从 llm_wiki 的 Markdown 提取 Claims？**

**llm_wiki 输出格式（假设）：**
```markdown
---
title: "Python asyncio 编程模型"
source: "/path/to/fluent-python.pdf"
created: 2026-08-20
---

# Python asyncio 编程模型

## 核心概念

asyncio 是 Python 的异步 I/O 框架，基于协程和事件循环。

## 适用场景

asyncio 特别适合 I/O 密集型任务，因为它可以在等待 I/O 时切换到其他任务。

## 性能特点

根据《Fluent Python》第 18 章，asyncio 在处理大量并发连接时性能优于传统的多线程方案。
```

**方案 A: 基于自然段落（简单）**
```python
def extract_claims_simple(markdown_content, source_id):
    """
    每个段落作为一个 Claim
    """
    claims = []
    for paragraph in split_paragraphs(markdown_content):
        if is_informative(paragraph):  # 过滤掉标题、列表等
            claims.append(Claim(
                statement=paragraph,
                source_id=source_id,
                trust=0.7  # 默认信任度
            ))
    return claims
```

**方案 B: 基于语义分割（复杂）**
```python
def extract_claims_semantic(markdown_content, source_id):
    """
    使用 LLM 分析段落，提取原子化的 Claims
    """
    claims = []
    for paragraph in split_paragraphs(markdown_content):
        # 调用 LLM 提取 Claims
        atomic_claims = llm.extract_claims(paragraph)
        for claim in atomic_claims:
            claims.append(Claim(
                statement=claim.statement,
                source_id=source_id,
                trust=claim.confidence
            ))
    return claims
```

**方案 C: 用户手工标注（V0 推荐）**
```python
def extract_claims_manual(markdown_content, source_id):
    """
    V0 阶段，用户手工创建 Claims
    llm_wiki 的内容只是参考
    """
    # V0: 不自动提取，用户在 Obsidian 中手工添加
    # 格式:
    # ## Claims
    # - C1: asyncio 基于协程和事件循环
    # - C2: asyncio 适合 I/O 密集型任务
    
    claims = []
    # 解析 "## Claims" section
    claims_section = extract_section(markdown_content, "## Claims")
    for line in claims_section.split("\n"):
        if line.startswith("- "):
            claims.append(Claim(
                statement=line[2:],  # 去掉 "- "
                source_id=source_id,
                trust=0.8
            ))
    return claims
```

**建议：**
- ✅ **V0 推荐方案 C（用户手工标注）**
  - 简单，无需 LLM
  - 用户完全控制 Claims 质量
  - 符合 Atelier 的手工整理传统
- ⚠️ **V1 考虑方案 B（语义分割）**
  - 自动化程度高
  - 需要 LLM 支持

---

#### B3. Confidence 计算公式

**问题：如何从 Claims 的 Trust 计算 Belief 的 Confidence？**

**场景：**
```python
belief = Belief(
    statement="Python asyncio 适合 I/O 密集型任务",
    based_on=[
        Claim(id="c1", trust=0.95),  # 来自《Fluent Python》
        Claim(id="c2", trust=0.85),  # 来自视频讲解
    ]
)

# Confidence = ?
```

**方案 A: 简单平均**
```python
def calculate_confidence_avg(claims):
    return sum(c.trust for c in claims) / len(claims)

# 示例: (0.95 + 0.85) / 2 = 0.9
```

**方案 B: 加权平均（基于来源质量）**
```python
def calculate_confidence_weighted(claims):
    weights = {
        "L4": 1.0,  # 外部认证（书籍、论文）
        "L3": 0.8,  # 本地认证 Wiki
        "L2": 0.5,  # 工作笔记
    }
    total_weight = sum(weights[c.quality] * c.trust for c in claims)
    total = sum(weights[c.quality] for c in claims)
    return total_weight / total

# 示例: (1.0*0.95 + 0.8*0.85) / (1.0 + 0.8) = 0.92
```

**方案 C: 贝叶斯融合（最复杂）**
```python
def calculate_confidence_bayesian(claims, prior=0.5):
    """
    贝叶斯更新：每个 Claim 更新先验概率
    """
    posterior = prior
    for claim in claims:
        # 贝叶斯更新
        likelihood = claim.trust
        posterior = (likelihood * posterior) / (
            likelihood * posterior + (1 - likelihood) * (1 - posterior)
        )
    return posterior

# 复杂，但考虑了证据间的依赖关系
```

**建议：**
- ✅ **V0 推荐方案 A（简单平均）**
  - 简单，易于理解
  - 对于 2-3 个 Claims 足够
- ⚠️ **V1 考虑方案 B（加权平均）**
  - 考虑来源质量
  - 更准确

---

### C. 存储方案问题

#### C1. 双写机制的原子性

**问题：Markdown + SQLite 双写如何保证原子性？**

**场景：**
```python
def create_belief(belief):
    # Step 1: 写 Markdown
    write_markdown(f"$OV/beliefs/{belief.id}.md", belief.to_markdown())
    
    # Step 2: 写 SQLite
    db.execute("INSERT INTO beliefs (...) VALUES (...)", belief.to_tuple())
    db.commit()
    
    # 问题：如果 Step 1 成功，Step 2 失败，怎么办？
```

**方案 A: 先 SQLite，后 Markdown**
```python
def create_belief(belief):
    try:
        # 先写 SQLite（可回滚）
        db.execute("INSERT INTO beliefs (...) VALUES (...)", belief.to_tuple())
        db.commit()
        
        # 再写 Markdown
        write_markdown(f"$OV/beliefs/{belief.id}.md", belief.to_markdown())
    except Exception as e:
        # SQLite 可以回滚
        db.rollback()
        raise e
```

**问题：**
- 如果 Markdown 写入失败，SQLite 已提交，无法回滚
- 结果：SQLite 有记录，但 Markdown 缺失

**方案 B: 先 Markdown，后 SQLite（推荐）**
```python
def create_belief(belief):
    # 先写 Markdown（源真相）
    write_markdown(f"$OV/beliefs/{belief.id}.md", belief.to_markdown())
    
    try:
        # 再写 SQLite
        db.execute("INSERT INTO beliefs (...) VALUES (...)", belief.to_tuple())
        db.commit()
    except Exception as e:
        # SQLite 失败，但 Markdown 已存在
        # 可以通过 rebuild_index() 恢复
        log_error(f"SQLite write failed for {belief.id}, Markdown exists")
        # 不删除 Markdown
```

**问题：**
- 如果 SQLite 失败，Markdown 已存在
- 但可以通过 `rebuild_index()` 恢复

**方案 C: 事务日志（最复杂）**
```python
def create_belief(belief):
    # 写 WAL (Write-Ahead Log)
    wal.append({
        "op": "create_belief",
        "belief_id": belief.id,
        "status": "pending"
    })
    
    try:
        write_markdown(...)
        db.execute(...)
        db.commit()
        wal.mark_complete(belief.id)
    except Exception as e:
        wal.mark_failed(belief.id)
        # 后台任务重试
```

**建议：**
- ✅ **V0 推荐方案 B（先 Markdown，后 SQLite）**
  - Markdown 是源真相
  - SQLite 失败可通过 rebuild_index() 恢复
  - 简单，无需 WAL
- ⚠️ **V1 考虑方案 C（事务日志）**
  - 如果发现方案 B 的一致性问题
  - 增加 WAL 确保严格一致性

---

#### C2. SQLite 索引性能

**问题：SQLite 索引是否能支撑 < 200ms 的查询性能？**

**查询场景：**
```sql
-- 查询 1: 查询所有高置信度 Beliefs
SELECT id, statement, confidence
FROM beliefs
WHERE confidence > 0.8
ORDER BY updated DESC
LIMIT 10;

-- 查询 2: 全文搜索
SELECT id, statement
FROM beliefs_fts
WHERE beliefs_fts MATCH 'asyncio'
ORDER BY rank
LIMIT 10;

-- 查询 3: 查询 Belief 的所有支持 Claims
SELECT c.id, c.statement, r.relation_type
FROM relationships r
JOIN claims c ON r.to_id = c.id
WHERE r.from_type = 'belief'
  AND r.from_id = 'belief_001'
  AND r.relation_type = 'BASED_ON';
```

**性能验证（需要实测）：**
```python
# 测试数据
- 1000 个 Beliefs
- 5000 个 Claims
- 10000 个 Relationships

# 性能目标
- 查询 1: < 50ms
- 查询 2: < 100ms
- 查询 3: < 50ms

# 索引策略
CREATE INDEX idx_beliefs_confidence ON beliefs(confidence DESC);
CREATE INDEX idx_beliefs_updated ON beliefs(updated DESC);
CREATE INDEX idx_rel_from ON relationships(from_type, from_id);
CREATE INDEX idx_rel_to ON relationships(to_type, to_id);
CREATE VIRTUAL TABLE beliefs_fts USING fts5(statement, content='beliefs');
```

**建议：**
- ✅ **Week 1 进行性能 POC**
  - 生成测试数据（1000 Beliefs）
  - 测量实际查询延迟
  - 如果 > 200ms，优化索引策略
- ⚠️ **如果 SQLite 不够快，考虑备选方案**
  - 使用 PostgreSQL（更强大的全文搜索）
  - 但增加部署复杂度

---

### D. 接口设计问题

#### D1. Module 间接口的版本化

**问题：如果 Module 1 的接口变化，Module 4 如何兼容？**

**当前设计（隐式契约）：**
```python
# Module 1 调用 Module 4
claims = knowledge_vault.get_claims([claim_id1, claim_id2])
```

**潜在问题：**
- 如果 `get_claims()` 的返回格式变化，Module 1 需要同步修改
- V0 → V1 演进时，接口可能需要扩展

**方案 A: 版本化接口**
```python
# Module 4 API v1
class KnowledgeVaultV1:
    def get_claims(self, claim_ids: List[str]) -> List[Claim]:
        ...

# Module 4 API v2（扩展）
class KnowledgeVaultV2:
    def get_claims(self, claim_ids: List[str], include_evidence: bool = False) -> List[ClaimWithEvidence]:
        ...

# Module 1 选择版本
vault = KnowledgeVaultV2()  # 使用 v2 API
```

**方案 B: 兼容性包装**
```python
class KnowledgeVault:
    def get_claims(self, claim_ids, **kwargs):
        # 向后兼容
        if "include_evidence" in kwargs:
            return self._get_claims_with_evidence(claim_ids)
        else:
            return self._get_claims_simple(claim_ids)
```

**建议：**
- ✅ **V0 不需要版本化（只有一个版本）**
- ⚠️ **V1 考虑引入接口版本化**
  - 如果接口变化频繁
  - 使用 Semantic Versioning

---

#### D2. 错误传播策略

**问题：如果 Module 4 查询失败，Module 1 如何处理？**

**场景：**
```python
# Module 1
def create_belief(statement, claim_ids):
    try:
        claims = knowledge_vault.get_claims(claim_ids)
    except ClaimNotFoundError as e:
        # 问题：如何处理？
        # 方案 A: 抛出异常，创建失败
        raise BeliefCreationError(f"Claim {e.claim_id} not found")
        
        # 方案 B: 忽略缺失的 Claim，继续创建
        claims = [c for c in claims if c is not None]
        
        # 方案 C: 降级模式（不验证 Claim）
        belief = Belief(statement, confidence=0.5)  # 低置信度
```

**建议：**
- ✅ **V0 推荐方案 A（严格模式）**
  - 创建 Belief 必须基于已存在的 Claims
  - 避免数据不一致
- ⚠️ **V1 考虑方案 C（降级模式）**
  - 如果 Knowledge Vault 不可用
  - 允许创建低置信度的 Belief

---

### E. 性能问题

#### E1. TrustRank 计算的性能瓶颈

**问题：TrustRank 全图传播在大规模知识库中可能很慢**

**当前算法（from v0.1）：**
```python
def trustrank(claim: Claim) -> float:
    base_trust = source_trust(claim.anchor)
    evidence_boost = sum(evidence_trust(e) for e in claim.evidence)
    time_decay = age_factor(claim.since)
    contradiction_penalty = contradiction_count(claim)
    
    return base_trust * evidence_boost * time_decay - contradiction_penalty
```

**问题：**
- 如果每次摄入新 Claim 都触发全图传播，成本很高
- 100G 知识库可能有数百万个 Claims

**方案 A: 增量更新（推荐）**
```python
def incremental_trustrank(new_claim):
    """
    只更新受影响的 Claims
    """
    # 1. 计算新 Claim 的 trust
    new_claim.trust = calculate_initial_trust(new_claim)
    
    # 2. 找到依赖新 Claim 的 Claims（通过 Evidence）
    affected_claims = find_affected_claims(new_claim.id)
    
    # 3. 只重新计算受影响的 Claims
    for claim in affected_claims:
        claim.trust = recalculate_trust(claim)
```

**方案 B: 定期全图校准**
```python
# 平时使用增量更新
# 每周一次全图校准（后台任务）
def weekly_trustrank_calibration():
    """
    每周全图重算一次，校正累积误差
    """
    all_claims = load_all_claims()
    for claim in all_claims:
        claim.trust = trustrank(claim)
    save_all_claims(all_claims)
```

**建议：**
- ✅ **V0 使用方案 A（增量更新）**
  - 避免全图传播
  - 性能可接受
- ✅ **V1 添加方案 B（定期校准）**
  - 后台任务，每周一次
  - 校正累积误差

---

#### E2. File Watcher 的性能影响

**问题：File Watcher 监听整个 wiki/ 目录，大量文件变化时性能如何？**

**场景：**
- 用户导入 1000 个 PDF 到 llm_wiki
- llm_wiki 生成 1000 个 wiki 文件
- File Watcher 触发 1000 次 `on_created` 事件

**潜在问题：**
- 1000 次 ingest_wiki_page() 调用
- 可能阻塞主线程

**方案 A: 批量处理**
```python
class WikiFileHandler:
    def __init__(self):
        self.pending_files = []
        self.timer = None
    
    def on_created(self, event):
        # 不立即处理，加入队列
        self.pending_files.append(event.src_path)
        
        # 500ms 后批量处理
        if self.timer:
            self.timer.cancel()
        self.timer = Timer(0.5, self.batch_process)
        self.timer.start()
    
    def batch_process(self):
        # 批量摄入
        ingest_wiki_pages_batch(self.pending_files)
        self.pending_files = []
```

**方案 B: 异步处理**
```python
import asyncio

class WikiFileHandler:
    async def on_created(self, event):
        # 异步摄入，不阻塞
        await asyncio.create_task(ingest_wiki_page_async(event.src_path))
```

**建议：**
- ✅ **V0 使用方案 A（批量处理）**
  - 简单，无需 async
  - 减少系统负载
- ⚠️ **监控 File Watcher 性能**
  - 如果发现瓶颈，考虑方案 B

---

## 🎯 关键决策需要确认

### 决策 1: Claim 提取规则

**选项：**
- A. 用户手工标注（V0 推荐）
- B. 自动语义分割（V1）

**你的选择：** ___________

**理由：** ___________

---

### 决策 2: Confidence 计算公式

**选项：**
- A. 简单平均（V0 推荐）
- B. 加权平均（V1）
- C. 贝叶斯融合（V2）

**你的选择：** ___________

**理由：** ___________

---

### 决策 3: 双写原子性保证

**选项：**
- A. 先 SQLite，后 Markdown
- B. 先 Markdown，后 SQLite（推荐）
- C. 事务日志（WAL）

**你的选择：** ___________

**理由：** ___________

---

### 决策 4: TrustRank 更新策略

**选项：**
- A. 增量更新（推荐）
- B. 全图传播
- C. 增量 + 定期校准

**你的选择：** ___________

**理由：** ___________

---

### 决策 5: File Watcher 性能优化

**选项：**
- A. 批量处理（推荐）
- B. 异步处理
- C. 不优化（先观察）

**你的选择：** ___________

**理由：** ___________

---

## 📝 待补充的设计细节

### 1. Claim 提取规则详细设计

**需要补充：**
- V0 的用户手工标注格式
- Obsidian 中的操作流程
- CLI 命令示例

### 2. Confidence 计算公式实现

**需要补充：**
- Python 实现代码
- 单元测试用例
- 边界情况处理

### 3. 双写机制实现细节

**需要补充：**
- 错误处理流程
- 索引重建命令
- 一致性检查脚本

### 4. 模块间接口定义

**需要补充：**
- Python 接口类（Protocol / ABC）
- 完整的 Capability Contract
- 错误类型定义

### 5. 性能 POC 计划

**需要补充：**
- 测试数据生成脚本
- 性能基准测试
- 优化策略

---

## 🚀 下一步行动

**立即确认（本次会话）：**
1. ✅ 确认 5 个关键决策
2. ✅ 识别遗漏的设计细节
3. ✅ 确定需要 POC 验证的部分

**后续补充（下次会话）：**
1. ⬜ 补充 Claim 提取规则设计
2. ⬜ 补充 Confidence 计算实现
3. ⬜ 补充模块接口定义
4. ⬜ 创建性能 POC 计划

---

**审查完成度:** 70%  
**待确认决策:** 5 个  
**待补充细节:** 5 项  
**估计剩余时间:** 1-2 小时
