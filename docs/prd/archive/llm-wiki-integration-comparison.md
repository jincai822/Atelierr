# llm_wiki 集成方案对比分析

**创建日期:** 2026-08-26 20:11  
**目的:** 帮助用户选择最适合的集成方案

---

## 方案总览

| 方案 | 复杂度 | 自动化 | 灵活性 | 推荐度 |
|------|--------|--------|--------|--------|
| 方案 1: File Watcher | 中 | ⭐⭐⭐ | ⭐⭐ | ⭐⭐ |
| 方案 2: 手动触发 | 低 | ⭐ | ⭐⭐⭐ | ⭐⭐ |
| 方案 3: 智能检测 | 低 | ⭐⭐⭐ | ⭐⭐⭐ | ⭐⭐⭐ |
| 方案 4: 混合方案 | 高 | ⭐⭐⭐ | ⭐⭐⭐ | ⭐⭐⭐ |

---

## 详细对比

### 使用场景分析

**场景 A: 你在 llm_wiki 中批量生成了 100 个 Wiki 页面**

- 方案 1: ✅ 自动全部摄入（可能需要 1-2 分钟）
- 方案 2: ❌ 需要手动执行 `--all`（一次命令搞定）
- 方案 3: ⚠️ 不会立即摄入，只在你用到时才摄入（省资源）
- 方案 4: ✅ 可选择自动或手动

**场景 B: 你想创建一个 Belief，需要引用 3 个 Claims**

- 方案 1: ✅ 如果 Wiki 已摄入，直接引用
- 方案 2: ❌ 需要先手动导入 Wiki
- 方案 3: ✅ 自动检测并按需加载（1-2 秒延迟）
- 方案 4: ✅ 按需加载或提前导入都行

**场景 C: llm_wiki 正在生成 Wiki，你马上要用**

- 方案 1: ✅ 2 秒后自动可用
- 方案 2: ❌ 需要等生成完再手动导入
- 方案 3: ✅ 创建 Belief 时自动加载
- 方案 4: ✅ 最灵活

---

## 实现复杂度对比

### 方案 1: File Watcher

**需要实现：**
```python
1. WikiFileWatcher 类（监听文件变化）
2. 防抖动机制（避免频繁触发）
3. 文件完整性检查（避免读取不完整文件）
4. 错误重试机制
```

**代码量：** ~200 行  
**测试复杂度：** 中（需要模拟文件事件）

---

### 方案 2: 手动触发

**需要实现：**
```python
1. CLI 命令：cognition wiki import <path>
2. 批量导入：cognition wiki import --all
3. 基本错误处理
```

**代码量：** ~50 行  
**测试复杂度：** 低

---

### 方案 3: 智能检测（推荐）

**需要实现：**
```python
1. 检测 Wiki 页面是否已摄入
2. 按需从 llm_wiki/wiki/ 读取文件
3. 缓存已摄入的 Wiki（避免重复读取）
4. 基本错误处理
```

**代码量：** ~100 行  
**测试复杂度：** 低

**示例代码：**
```python
class KnowledgeVault:
    def get_claims_from_wiki(self, wiki_title: str) -> List[Claim]:
        """从 Wiki 页面获取 Claims（智能检测）"""
        
        # 1. 检查是否已摄入
        if self._is_wiki_ingested(wiki_title):
            return self.storage.get_claims_by_source(wiki_title)
        
        # 2. 未摄入，立即读取并摄入
        wiki_path = f"{self.wiki_dir}/{wiki_title}.md"
        
        if not os.path.exists(wiki_path):
            log.warning(f"Wiki 页面不存在: {wiki_title}")
            return []
        
        # 3. 摄入 Wiki 页面
        log.info(f"按需摄入 Wiki: {wiki_title}")
        claims = self.ingest_wiki_page(wiki_path)
        
        return claims

# 使用示例
class CognitionCore:
    def create_belief(self, statement: str, wiki_refs: List[str]) -> Belief:
        """创建 Belief，自动处理 Wiki 引用"""
        
        # 自动从 Wiki 获取 Claims（会触发按需加载）
        all_claims = []
        for wiki_title in wiki_refs:
            claims = self.knowledge_vault.get_claims_from_wiki(wiki_title)
            all_claims.extend(claims)
        
        # 创建 Belief
        belief = Belief(
            statement=statement,
            based_on=[c.id for c in all_claims],
            confidence=self._calculate_confidence(all_claims)
        )
        
        return belief
```

---

### 方案 4: 混合方案

**需要实现：**
```
方案 1 的所有代码 + 方案 2 的所有代码 + 方案 3 的所有代码
```

**代码量：** ~350 行  
**测试复杂度：** 高

---

## 性能对比

### 内存占用

- 方案 1: 额外的 File Watcher 线程（~5MB）
- 方案 2: 无额外内存
- 方案 3: 缓存已摄入的 Wiki 标题（~1MB）
- 方案 4: 方案 1 + 方案 3（~6MB）

### 响应速度

**首次使用某个 Wiki 页面：**
- 方案 1: 0ms（已提前摄入）
- 方案 2: 需要手动导入
- 方案 3: 100-500ms（按需读取）
- 方案 4: 0ms 或 100-500ms（取决于模式）

**后续使用：**
- 所有方案都是 0ms（已在数据库中）

---

## 实际使用体验

### 方案 1: File Watcher

**典型工作流：**
```bash
# 1. 在 llm_wiki 中导入 PDF
$ llm_wiki import asyncio_book.pdf

# 2. llm_wiki 自动生成 Wiki 页面
# wiki/python_asyncio.md
# wiki/event_loop.md
# wiki/coroutines.md

# 3. 本系统自动摄入（无需操作）
# [后台日志]
# ✅ 已摄入: python_asyncio.md
# ✅ 已摄入: event_loop.md
# ✅ 已摄入: coroutines.md

# 4. 你可以直接创建 Belief
$ cognition belief create \
    --statement "Python asyncio 适合 I/O 密集型任务" \
    --wiki python_asyncio

✅ Belief created: belief_20260826_001
```

**体验：** 完全自动，无感知

---

### 方案 2: 手动触发

**典型工作流：**
```bash
# 1. 在 llm_wiki 中导入 PDF（同上）
$ llm_wiki import asyncio_book.pdf

# 2. llm_wiki 生成 Wiki 页面（同上）

# 3. 手动导入到本系统
$ cognition wiki import --all

扫描 wiki/ 目录...
✅ 已导入: python_asyncio.md (5 claims)
✅ 已导入: event_loop.md (3 claims)
✅ 已导入: coroutines.md (4 claims)
总计: 3 个页面, 12 个 claims

# 4. 创建 Belief（同上）
```

**体验：** 需要记得执行导入，但很简单

---

### 方案 3: 智能检测（推荐）

**典型工作流：**
```bash
# 1. 在 llm_wiki 中导入 PDF（同上）
$ llm_wiki import asyncio_book.pdf

# 2. llm_wiki 生成 Wiki 页面（同上）

# 3. 直接创建 Belief（无需导入）
$ cognition belief create \
    --statement "Python asyncio 适合 I/O 密集型任务" \
    --wiki python_asyncio

[检测到 python_asyncio 未摄入，自动加载中...]
✅ 已摄入: python_asyncio.md (5 claims)
✅ Belief created: belief_20260826_001

# 4. 下次再用就是瞬时的
$ cognition belief create \
    --statement "Event Loop 是 asyncio 的核心" \
    --wiki python_asyncio

✅ Belief created: belief_20260826_002  # 无延迟
```

**体验：** 智能又简单，首次有小延迟

---

## 推荐决策树

```
你希望完全自动化，不想手动操作？
  ├─ 是 → 你的 llm_wiki 经常批量生成大量 Wiki？
  │       ├─ 是 → 方案 4（混合）或 方案 1（File Watcher）
  │       └─ 否 → 方案 3（智能检测）✅ 推荐
  └─ 否 → 你希望完全掌控导入时机？
          └─ 是 → 方案 2（手动触发）
```

---

## 我的最终推荐

### 🥇 **方案 3: 智能检测**（推荐用于 V0）

**理由：**
1. ✅ 简单（代码量只有方案 1 的一半）
2. ✅ 智能（按需加载，不浪费资源）
3. ✅ 无感知（用户不需要关心导入）
4. ✅ 灵活（可以手动补充导入命令）

**唯一缺点：** 首次使用某个 Wiki 有 100-500ms 延迟（可接受）

---

### 🥈 方案 4: 混合方案（推荐用于 V1）

**理由：**
- V0 验证方案 3 可行后
- V1 增加 File Watcher 和手动导入
- 提供最大灵活性

---

## 实施建议

### V0（最小可行产品）

```python
# 只实现方案 3（智能检测）
class KnowledgeVault:
    def get_claims_from_wiki(self, wiki_title: str) -> List[Claim]:
        """智能检测并按需加载"""
        if not self._is_wiki_ingested(wiki_title):
            self.ingest_wiki_page(f"{self.wiki_dir}/{wiki_title}.md")
        return self.storage.get_claims_by_source(wiki_title)
```

**工作量：** 0.5 天

---

### V1（增强功能）

```python
# 增加方案 1（File Watcher）
class WikiFileWatcher:
    """后台监听 llm_wiki/wiki/ 目录"""
    pass

# 增加方案 2（手动导入）
@cli.command()
def import_wiki(path: str):
    """手动导入 Wiki 页面"""
    pass
```

**工作量：** 1.5 天

---

## 决策点

**请选择：**

**A. 方案 3（智能检测）** — 我推荐这个，简单又智能

**B. 方案 1（File Watcher）** — 如果你需要完全自动化

**C. 方案 2（手动触发）** — 如果你喜欢完全掌控

**D. 方案 4（混合方案）** — 如果你想要最强大的方案

**E. 其他想法** — 告诉我你的需求

---

**创建时间:** 2026-08-26 20:11  
**状态:** 等待用户选择  
**下一步:** 根据选择更新架构决策
