# Personal Intelligence System - 架构决策确认文档

**决策日期:** 2026-08-26  
**决策人:** 用户 + AI Assistant  
**基于:** PRD v0.2 + 架构审查  
**状态:** ✅ 已确认（2026-08-26 19:45）

---

## 决策原则

1. **简洁优于完美** — V0 是 MVP，选择最简单可行的方案
2. **降级优于失败** — 优雅降级，保证核心流程
3. **Markdown 优先** — Markdown 是源真相
4. **异步解耦** — 非关键路径异步处理
5. **工具容错** — 工具失败不影响核心

---

## A. 核心架构决策（4 个）

### A1. 模块分层架构 ✅ 推荐方案

**决策：** 采用三层架构

```
┌─────────────────────────┐
│ Cognition Core          │ 业务逻辑层
│ (Belief/Question/       │
│  Decision Management)   │
└────────┬────────────────┘
         │ 调用
         ↓
┌─────────────────────────┐
│ Knowledge Vault         │ 数据访问层
│ (Claim/Source/          │
│  TrustRank)             │
└────────┬────────────────┘
         │ 调用
         ↓
┌─────────────────────────┐
│ Storage Layer           │ 存储层
│ (Markdown + SQLite)     │
└─────────────────────────┘
```

**接口示例：**

```python
# Module 1: Cognition Core (业务逻辑层)
class CognitionCore:
    def __init__(self, knowledge_vault: KnowledgeVault):
        self.knowledge_vault = knowledge_vault
    
    def create_belief(self, statement: str, claim_ids: List[str]) -> Belief:
        # 1. 验证 Claims 存在
        claims = []
        for claim_id in claim_ids:
            claim = self.knowledge_vault.get_claim(claim_id)
            if claim is None:
                raise ValueError(f"Claim {claim_id} 不存在")
            claims.append(claim)
        
        # 2. 计算 Confidence（基于 Claims 的 TrustRank）
        confidence = self._calculate_confidence(claims)
        
        # 3. 创建 Belief
        belief = Belief(
            id=generate_id(),
            statement=statement,
            based_on=claim_ids,
            confidence=confidence,
            created=datetime.now()
        )
        
        # 4. 保存到存储层
        self.belief_repository.save(belief)
        
        return belief

# Module 4: Knowledge Vault (数据访问层)
class KnowledgeVault:
    def __init__(self, storage: StorageLayer):
        self.storage = storage
        self.semantic_search = SemanticSearch()  # 封装 scripts/semantic.py
        self.trustrank = TrustRank()  # 封装 scripts/trustrank.py
    
    def get_claim(self, claim_id: str) -> Optional[Claim]:
        return self.storage.get_claim(claim_id)
    
    def query_claims(self, query: str) -> List[Claim]:
        # 优先使用语义搜索
        try:
            return self.semantic_search.search(query)
        except Exception as e:
            log.warning(f"语义搜索失败，降级到关键词搜索: {e}")
            return self.storage.keyword_search_claims(query)
```

**职责划分：**
- **Cognition Core:** 业务逻辑（创建、更新、查询 Beliefs/Questions/Decisions）
- **Knowledge Vault:** 数据访问（Claims/Sources 的 CRUD + 语义搜索 + TrustRank）
- **Storage Layer:** 持久化（Markdown 读写 + SQLite 索引）

**✅ 确认点：**
- [ ] 同意三层架构
- [ ] 同意 Cognition Core 通过依赖注入获得 Knowledge Vault
- [ ] 同意 Knowledge Vault 封装 Support Tools

---

### A2. Support Tools 调用方式 ✅ 推荐方案

**决策：** 封装为类，同步调用主路径，异步调用非关键路径

```python
# Support Tools 封装为类
class SemanticSearch:
    """封装 scripts/semantic.py"""
    def __init__(self, index_path: str):
        self.index_path = index_path
        self._load_index()
    
    def search(self, query: str, top_k: int = 10) -> List[SearchResult]:
        # 调用原有的 scripts/semantic.py 逻辑
        pass

class TrustRank:
    """封装 scripts/trustrank.py"""
    def calculate(self, claim_id: str) -> float:
        # 调用原有的 scripts/trustrank.py 逻辑
        pass
    
    def propagate_all(self):
        """异步批量计算 TrustRank"""
        pass

class ContextBundle:
    """封装 scripts/context_bundle.py"""
    def load_context(self, intent: str) -> Context:
        # 调用原有的 scripts/context_bundle.py 逻辑
        pass
```

**调用时机与方式：**

| Tool | 调用者 | 调用时机 | 方式 | 失败处理 | 性能目标 |
|------|--------|---------|------|----------|---------|
| **semantic.py** | Knowledge Vault | query_claims() | 同步 | 降级到关键词搜索 | < 200ms |
| **trustrank.py** | Knowledge Vault | ingest_wiki_page() | 异步 | 使用默认 trust 值 | < 10s (1000 claims) |
| **context_bundle.py** | Cognition Core | create_belief(), make_decision() | 同步 | 降级到无上下文 | < 500ms |
| **cues.py** | Human Interface | 启动时 / 用户请求 | 同步 | 展示警告 | < 1s |
| **pricing.py** | Human Interface | 用户请求 | 同步 | 展示错误 | < 1s |

**优雅降级示例：**

```python
class KnowledgeVault:
    def query_claims(self, query: str) -> List[Claim]:
        try:
            # 主路径：语义搜索
            results = self.semantic_search.search(query)
            return results
        except IndexCorruptedError:
            log.error("向量索引损坏，需要重建")
            # 降级：关键词搜索
            return self.storage.keyword_search_claims(query)
        except Exception as e:
            log.error(f"查询失败: {e}")
            # 最终降级：返回空结果
            return []
```

**✅ 确认点：**
- [ ] 同意将 Support Tools 封装为类
- [ ] 同意语义搜索同步调用，TrustRank 异步调用
- [ ] 同意优雅降级策略

---

### A3. Claim 引用完整性策略 ✅ 推荐方案

**决策：** 宽松策略（Lazy Loading + 警告）

**场景：** Belief 引用了 `claim_xxx`，但 `claim_xxx` 不存在

**方案对比：**

| 方案 | 优点 | 缺点 | 推荐 |
|------|------|------|------|
| 严格检查 | 数据完整性强 | 用户体验差，创建 Belief 可能失败 | ❌ |
| 宽松处理 | 用户体验好 | 可能有悬空引用 | ✅ |
| 延迟解析 | 兼顾两者 | 实现复杂度适中 | ✅ |

**推荐实现：**

```python
class CognitionCore:
    def create_belief(self, statement: str, claim_ids: List[str]) -> Belief:
        # 验证 Claims 存在（警告但不阻止）
        valid_claim_ids = []
        for claim_id in claim_ids:
            if self.knowledge_vault.claim_exists(claim_id):
                valid_claim_ids.append(claim_id)
            else:
                log.warning(f"Claim {claim_id} 不存在，已忽略")
        
        # 即使没有有效的 Claim，也允许创建 Belief
        # （用户可能是先创建 Belief，后摄入 Claims）
        belief = Belief(
            statement=statement,
            based_on=valid_claim_ids,  # 只保存有效的
            confidence=self._calculate_confidence(valid_claim_ids) if valid_claim_ids else 0.5
        )
        
        return belief
    
    def get_belief_with_claims(self, belief_id: str) -> BeliefWithClaims:
        """延迟加载 Claims"""
        belief = self.belief_repository.get(belief_id)
        
        claims = []
        missing_claims = []
        for claim_id in belief.based_on:
            claim = self.knowledge_vault.get_claim(claim_id)
            if claim:
                claims.append(claim)
            else:
                missing_claims.append(claim_id)
        
        if missing_claims:
            log.warning(f"Belief {belief_id} 引用的 Claims 不存在: {missing_claims}")
        
        return BeliefWithClaims(belief, claims, missing_claims)
```

**✅ 确认点：**
- [ ] 同意宽松策略（警告但不阻止）
- [ ] 同意延迟加载 Claims
- [ ] 同意在 UI 中展示缺失的 Claims

---

### A4. TrustRank → Confidence 更新策略 ✅ 推荐方案

**决策：** 手动触发 + 定期批量重算

**场景：** Claim 的 TrustRank 变化，Belief 的 Confidence 是否自动更新？

**方案对比：**

| 方案 | 优点 | 缺点 | 推荐 |
|------|------|------|------|
| 实时更新 | 数据始终最新 | 性能开销大，复杂度高 | ❌ |
| 定期批量 | 性能可控 | 数据有延迟 | ✅ |
| 手动触发 | 简单 | 用户需要记得触发 | ✅ |

**推荐实现：**

```python
class CognitionCore:
    def recalculate_belief_confidence(self, belief_id: str) -> Belief:
        """手动重算单个 Belief 的 Confidence"""
        belief = self.belief_repository.get(belief_id)
        
        # 获取最新的 Claims
        claims = [self.knowledge_vault.get_claim(id) for id in belief.based_on]
        claims = [c for c in claims if c is not None]  # 过滤不存在的
        
        # 重新计算 Confidence
        old_confidence = belief.confidence
        new_confidence = self._calculate_confidence(claims)
        
        if old_confidence != new_confidence:
            belief.confidence = new_confidence
            belief.updated = datetime.now()
            self.belief_repository.update(belief)
            
            log.info(f"Belief {belief_id} Confidence: {old_confidence:.2f} → {new_confidence:.2f}")
        
        return belief
    
    def recalculate_all_beliefs(self) -> Dict[str, float]:
        """批量重算所有 Beliefs（定期任务）"""
        results = {}
        for belief in self.belief_repository.list():
            updated_belief = self.recalculate_belief_confidence(belief.id)
            results[belief.id] = updated_belief.confidence
        return results
```

**定期任务配置：**

```yaml
# config/tasks.yaml
scheduled_tasks:
  - name: recalculate_all_beliefs
    schedule: "0 2 * * *"  # 每天凌晨 2 点
    enabled: true
```

**CLI 命令：**

```bash
# 手动触发
$ cognition belief recalculate <belief_id>
$ cognition belief recalculate --all
```

**✅ 确认点：**
- [ ] 同意手动触发 + 定期批量重算
- [ ] 同意每天凌晨 2 点自动重算
- [ ] 同意提供 CLI 命令

---

## B. 数据流决策（3 个）

### B1. Markdown + SQLite 双写原子性 ✅ 推荐方案

**决策：** Markdown 优先 + 异步索引 + 健康检查

**核心原则：**
- **Markdown 是源真相** — 必须保证写入成功
- **SQLite 是索引** — 失败可以后台重试
- **最终一致性** — 接受短暂的不一致

**实现方案：**

```python
class Repository:
    def __init__(self):
        self.index_queue = queue.Queue()
        self.indexer_thread = threading.Thread(target=self._background_indexer, daemon=True)
        self.indexer_thread.start()
    
    def save(self, entity: Entity) -> None:
        """保存实体（Markdown 优先）"""
        # 1. 写 Markdown（关键路径，必须成功）
        try:
            self._write_markdown(entity)
        except Exception as e:
            log.error(f"Markdown 写入失败: {e}")
            raise  # 失败则抛出异常
        
        # 2. 异步更新 SQLite（非关键路径）
        self.index_queue.put(('save', entity))
    
    def _background_indexer(self):
        """后台索引线程"""
        while True:
            try:
                operation, entity = self.index_queue.get()
                
                if operation == 'save':
                    self._update_sqlite_index(entity)
                elif operation == 'delete':
                    self._delete_from_sqlite_index(entity.id)
                
                log.debug(f"索引已更新: {entity.id}")
            except Exception as e:
                log.error(f"索引更新失败: {e}")
                # 失败不影响主流程，但记录到失败队列
                self._record_index_failure(entity)
    
    def _update_sqlite_index(self, entity: Entity):
        """更新 SQLite 索引（单线程，避免锁冲突）"""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                INSERT OR REPLACE INTO entities (id, data, updated_at)
                VALUES (?, ?, ?)
            """, (entity.id, entity.to_json(), datetime.now()))
            conn.commit()
```

**查询时的处理：**

```python
class Repository:
    def get(self, entity_id: str) -> Optional[Entity]:
        """查询实体（优先 SQLite，回退 Markdown）"""
        # 1. 尝试从 SQLite 读取（快）
        entity = self._get_from_sqlite(entity_id)
        if entity:
            return entity
        
        # 2. SQLite 未命中，从 Markdown 读取（慢）
        log.warning(f"SQLite 未命中 {entity_id}，回退到 Markdown")
        entity = self._get_from_markdown(entity_id)
        
        # 3. 补充到 SQLite 索引
        if entity:
            self.index_queue.put(('save', entity))
        
        return entity
    
    def query(self, filters: Dict) -> List[Entity]:
        """复杂查询（依赖 SQLite）"""
        try:
            return self._query_from_sqlite(filters)
        except Exception as e:
            log.error(f"SQLite 查询失败: {e}")
            # 降级到扫描 Markdown（慢）
            log.warning("降级到 Markdown 扫描")
            return self._scan_markdown_files(filters)
```

**健康检查与修复：**

```python
def health_check_consistency():
    """启动时检查一致性"""
    log.info("检查 Markdown ↔ SQLite 一致性...")
    
    inconsistent = []
    missing_in_sqlite = []
    
    # 扫描所有 Markdown 文件
    for md_file in glob("$OV/**/*.md", recursive=True):
        entity = parse_markdown(md_file)
        entity_from_db = get_from_sqlite(entity.id)
        
        if entity_from_db is None:
            # SQLite 缺失
            missing_in_sqlite.append(entity.id)
            insert_to_sqlite(entity)
        elif not entities_equal(entity, entity_from_db):
            # 不一致，Markdown 优先
            inconsistent.append(entity.id)
            update_sqlite(entity)
    
    log.info(f"一致性检查完成: 缺失 {len(missing_in_sqlite)}, 不一致 {len(inconsistent)}")
    return missing_in_sqlite, inconsistent
```

**✅ 确认点：**
- [ ] 同意 Markdown 优先 + 异步索引
- [ ] 同意查询时 SQLite 优先，回退 Markdown
- [ ] 同意启动时进行健康检查

---

### B2. Obsidian → 系统同步策略 ✅ 推荐方案

**决策：** 实时 File Watcher + 防抖动

**场景：** 用户在 Obsidian 中编辑 `belief_001.md`，系统如何同步？

**实现方案：**

```python
import time
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

class ObsidianFileWatcher(FileSystemEventHandler):
    def __init__(self, repository: Repository):
        self.repository = repository
        self.pending_changes = {}  # file_path -> last_modified_time
        self.debounce_timer = None
    
    def on_modified(self, event):
        if event.is_directory or not event.src_path.endswith('.md'):
            return
        
        # 添加到待处理队列
        self.pending_changes[event.src_path] = time.time()
        
        # 重置防抖动计时器（用户可能正在编辑）
        if self.debounce_timer:
            self.debounce_timer.cancel()
        
        self.debounce_timer = threading.Timer(2.0, self._process_pending_changes)
        self.debounce_timer.start()
    
    def _process_pending_changes(self):
        """处理待同步的文件（防抖动后）"""
        for file_path in list(self.pending_changes.keys()):
            try:
                # 解析 Markdown
                entity = parse_markdown_file(file_path)
                
                # 更新 SQLite 索引
                self.repository.update_index(entity)
                
                log.info(f"已同步: {os.path.basename(file_path)}")
            except Exception as e:
                log.error(f"同步失败 {file_path}: {e}")
            finally:
                del self.pending_changes[file_path]

# 启动监听
observer = Observer()
handler = ObsidianFileWatcher(repository)
observer.schedule(handler, path="$OV/beliefs/", recursive=False)
observer.schedule(handler, path="$OV/decisions/", recursive=False)
observer.schedule(handler, path="$OV/questions/", recursive=False)
observer.start()
```

**防抖动策略：**
- 2 秒内的多次修改只触发一次同步
- 避免用户编辑时频繁触发

**✅ 确认点：**
- [ ] 同意实时 File Watcher
- [ ] 同意 2 秒防抖动延迟
- [ ] 同意只监听特定目录（beliefs/decisions/questions）

---

### B3. SQLite 并发写入策略 ✅ 推荐方案

**决策：** 单线程写入队列 + WAL 模式

**问题：** 多个进程同时写 SQLite 会导致锁冲突

**解决方案：**

```python
import sqlite3
import queue
import threading

class SQLiteWriter:
    def __init__(self, db_path: str):
        self.db_path = db_path
        self.write_queue = queue.Queue()
        self.writer_thread = threading.Thread(target=self._writer_loop, daemon=True)
        self.writer_thread.start()
        
        # 启用 WAL 模式（Write-Ahead Logging）
        self._enable_wal_mode()
    
    def _enable_wal_mode(self):
        """启用 WAL 模式，提高并发性能"""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=NORMAL")  # 提高性能
    
    def _writer_loop(self):
        """单线程写入循环"""
        while True:
            operation = self.write_queue.get()
            
            try:
                with sqlite3.connect(self.db_path) as conn:
                    operation.execute(conn)
                    conn.commit()
            except Exception as e:
                log.error(f"SQLite 写入失败: {e}")
                operation.on_error(e)
            finally:
                self.write_queue.task_done()
    
    def execute_async(self, operation: SQLiteOperation):
        """异步执行 SQL 操作"""
        self.write_queue.put(operation)
    
    def wait_for_completion(self):
        """等待所有写入完成"""
        self.write_queue.join()

# 使用示例
class SQLiteOperation:
    def execute(self, conn: sqlite3.Connection):
        raise NotImplementedError
    
    def on_error(self, error: Exception):
        pass

class InsertBeliefOperation(SQLiteOperation):
    def __init__(self, belief: Belief):
        self.belief = belief
    
    def execute(self, conn: sqlite3.Connection):
        conn.execute("""
            INSERT OR REPLACE INTO beliefs (id, statement, confidence, created, updated)
            VALUES (?, ?, ?, ?, ?)
        """, (self.belief.id, self.belief.statement, self.belief.confidence,
              self.belief.created, self.belief.updated))
```

**WAL 模式优势：**
- 读写不互斥（多个读者 + 1 个写者）
- 提高并发性能
- 更好的崩溃恢复

**✅ 确认点：**
- [ ] 同意单线程写入队列
- [ ] 同意启用 WAL 模式
- [ ] 同意异步写入 API

---

## C. 存储层决策（4 个）

### C1. 一致性检查策略 ✅ 推荐方案

**决策：** 启动时 + 定期（每周）+ 手动

**实现方案：**

```python
def health_check_storage_consistency():
    """存储层一致性检查"""
    log.info("=" * 60)
    log.info("存储层一致性检查")
    log.info("=" * 60)
    
    issues = {
        'missing_in_sqlite': [],
        'inconsistent': [],
        'orphaned_in_sqlite': []
    }
    
    # 1. 检查 Markdown → SQLite
    log.info("检查 Markdown → SQLite...")
    for md_file in glob("$OV/**/*.md", recursive=True):
        entity = parse_markdown(md_file)
        entity_from_db = get_from_sqlite(entity.id)
        
        if entity_from_db is None:
            issues['missing_in_sqlite'].append(entity.id)
            # 自动修复
            insert_to_sqlite(entity)
            log.warning(f"  [修复] SQLite 缺失: {entity.id}")
        elif not entities_equal(entity, entity_from_db):
            issues['inconsistent'].append(entity.id)
            # 自动修复（Markdown 优先）
            update_sqlite(entity)
            log.warning(f"  [修复] 数据不一致: {entity.id}")
    
    # 2. 检查 SQLite → Markdown（孤儿记录）
    log.info("检查 SQLite → Markdown...")
    all_ids_in_db = get_all_ids_from_sqlite()
    all_ids_in_md = get_all_ids_from_markdown()
    
    orphaned = set(all_ids_in_db) - set(all_ids_in_md)
    for entity_id in orphaned:
        issues['orphaned_in_sqlite'].append(entity_id)
        # 删除孤儿记录
        delete_from_sqlite(entity_id)
        log.warning(f"  [修复] SQLite 孤儿记录: {entity_id}")
    
    # 3. 汇总报告
    log.info("=" * 60)
    log.info(f"一致性检查完成:")
    log.info(f"  - SQLite 缺失: {len(issues['missing_in_sqlite'])}")
    log.info(f"  - 数据不一致: {len(issues['inconsistent'])}")
    log.info(f"  - 孤儿记录: {len(issues['orphaned_in_sqlite'])}")
    log.info("=" * 60)
    
    return issues
```

**调用时机：**

```python
# 1. 启动时自动检查
def on_system_startup():
    log.info("系统启动，执行健康检查...")
    health_check_storage_consistency()

# 2. 定期任务（每周日凌晨 3 点）
# config/tasks.yaml
scheduled_tasks:
  - name: storage_consistency_check
    schedule: "0 3 * * 0"  # 每周日凌晨 3 点
    enabled: true

# 3. CLI 手动触发
$ cognition health check --storage
```

**✅ 确认点：**
- [ ] 同意启动时自动检查
- [ ] 同意每周定期检查
- [ ] 同意提供 CLI 手动触发

---

### C2. 索引重建触发策略 ✅ 推荐方案

**决策：** 手动触发 + 检测到损坏时自动重建

**场景：**
1. SQLite 文件损坏
2. 新增字段需要重建索引
3. 用户手动请求

**实现方案：**

```python
def rebuild_sqlite_index(backup: bool = True) -> None:
    """重建 SQLite 索引"""
    log.info("=" * 60)
    log.info("开始重建 SQLite 索引")
    log.info("=" * 60)
    
    # 1. 备份旧索引
    if backup and os.path.exists(DB_PATH):
        backup_path = f"{DB_PATH}.backup.{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        shutil.copy(DB_PATH, backup_path)
        log.info(f"已备份到: {backup_path}")
    
    # 2. 删除旧索引
    if os.path.exists(DB_PATH):
        os.remove(DB_PATH)
        log.info("已删除旧索引")
    
    # 3. 创建新索引
    init_database()
    log.info("已创建新索引")
    
    # 4. 扫描所有 Markdown 文件
    log.info("扫描 Markdown 文件...")
    
    stats = {'beliefs': 0, 'decisions': 0, 'questions': 0, 'claims': 0}
    
    for md_file in glob("$OV/beliefs/*.md"):
        belief = parse_markdown_file(md_file)
        insert_belief_to_index(belief)
        stats['beliefs'] += 1
    
    for md_file in glob("$OV/decisions/*.md"):
        decision = parse_markdown_file(md_file)
        insert_decision_to_index(decision)
        stats['decisions'] += 1
    
    for md_file in glob("$OV/questions/*.md"):
        question = parse_markdown_file(md_file)
        insert_question_to_index(question)
        stats['questions'] += 1
    
    for md_file in glob("$OV/wiki/**/*.md", recursive=True):
        claims = extract_claims_from_wiki(md_file)
        for claim in claims:
            insert_claim_to_index(claim)
        stats['claims'] += len(claims)
    
    # 5. 验证索引
    log.info("验证索引...")
    verify_index_integrity()
    
    # 6. 汇总报告
    log.info("=" * 60)
    log.info(f"索引重建完成:")
    log.info(f"  - Beliefs: {stats['beliefs']}")
    log.info(f"  - Decisions: {stats['decisions']}")
    log.info(f"  - Questions: {stats['questions']}")
    log.info(f"  - Claims: {stats['claims']}")
    log.info("=" * 60)

def check_sqlite_integrity() -> bool:
    """检查 SQLite 完整性"""
    try:
        with sqlite3.connect(DB_PATH) as conn:
            result = conn.execute("PRAGMA integrity_check").fetchone()
            return result[0] == 'ok'
    except Exception as e:
        log.error(f"SQLite 完整性检查失败: {e}")
        return False

# 启动时检查，损坏时自动重建
def on_system_startup():
    if not os.path.exists(DB_PATH):
        log.warning("SQLite 索引不存在，自动重建")
        rebuild_sqlite_index(backup=False)
    elif not check_sqlite_integrity():
        log.error("SQLite 索引损坏，自动重建")
        rebuild_sqlite_index(backup=True)
```

**CLI 命令：**

```bash
# 手动重建（带备份）
$ cognition index rebuild

# 强制重建（不备份）
$ cognition index rebuild --no-backup

# 只验证，不重建
$ cognition index verify
```

**✅ 确认点：**
- [ ] 同意手动触发 + 自动检测损坏
- [ ] 同意重建时自动备份
- [ ] 同意提供 CLI 命令

---

### C3. Markdown 文件格式规范 ✅ 推荐方案

**决策：** YAML frontmatter + Markdown body

**Belief 格式：**

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

## 当前置信度

- **Confidence**: 0.9 (Very High)
- **上次更新**: 2026-08-26

## 支持证据

### 证据 1：《Fluent Python》第 18 章

- **来源**: [[fluent_python_chapter_18]]
- **断言**: [[claim_fluent_python_ch18_001]]
- **Trust**: 0.95
- **内容**: "asyncio 的核心优势在于 I/O 等待期间可以切换任务..."

### 证据 2：视频讲解

- **来源**: [[python_asyncio_video]]
- **断言**: [[claim_asyncio_video_001]]
- **时间戳**: 15:20-22:10
- **Trust**: 0.85
- **内容**: "CPU 密集型任务不应该使用 asyncio..."

## 变化历史

- **2026-08-26 12:00**: Confidence 从 0.85 升至 0.9（新增视频证据）
- **2026-08-20 10:30**: 创建（基于 Fluent Python）

## 相关问题

- [[question_when_to_use_asyncio]]
- [[question_asyncio_vs_threading]]
```

**Decision 格式：**

```markdown
---
type: decision
id: decision_20260826_001
question_id: question_20260820_001
chosen_option: "使用 asyncio"
alternatives:
  - "使用 threading"
  - "使用 multiprocessing"
decided_at: 2026-08-26T14:00:00Z
decided_by: USER
status: EXECUTED
outcome_recorded: false
tags:
  - programming
  - architecture
---

# 决策：使用 asyncio 实现 Web Crawler

## 决策背景

需要实现一个高并发的 Web Crawler，爬取 10000+ 个网页。

## 选项分析

### ✅ 选项 1: asyncio（已选择）

**优势:**
- I/O 密集型任务性能最优
- 内存占用低（< 100MB）
- 代码简洁，易于维护

**劣势:**
- 调试较困难
- 学习曲线陡峭

**性能测试结果**: 1000 req/s

### ❌ 选项 2: threading

**优势:**
- 熟悉的编程模型
- 更好的调试支持

**劣势:**
- GIL 限制性能
- 内存占用高（~500MB）

**性能测试结果**: 300 req/s

### ❌ 选项 3: multiprocessing

**优势:**
- 真正的并行执行

**劣势:**
- 内存占用极高（~2GB）
- 进程间通信复杂

**性能测试结果**: 500 req/s

## 决策理由

基于以下 Beliefs:
- [[belief_20260826_001]]: Python asyncio 适合 I/O 密集型任务
- [[belief_20260825_002]]: Web Crawler 是 I/O 密集型任务

性能测试表明 asyncio 性能最优（1000 req/s），且内存占用最低。

## 执行结果

- **开始时间**: 2026-08-26
- **状态**: COMPLETED
- **实际性能**: 1200 req/s（超出预期 20%）
- **内存占用**: 80MB（低于预期）

## 学到的教训

- asyncio 的实际性能比预期更好
- 需要注意 CPU 密集型任务的混入（会阻塞事件循环）
- aiohttp 的连接池配置很重要

## 相关决策

- [[decision_20260827_001]]: 选择 aiohttp 作为 HTTP 客户端
```

**Question 格式：**

```markdown
---
type: question
id: question_20260826_001
question: "什么时候应该使用 asyncio？"
importance: 0.8
status: ANSWERED
created: 2026-08-26T10:00:00Z
answered_at: 2026-08-26T14:00:00Z
tags:
  - programming
  - python
---

# 什么时候应该使用 asyncio？

## 问题背景

经常在 threading、multiprocessing、asyncio 之间纠结。

## 当前理解

基于 [[belief_20260826_001]]，asyncio 适合 I/O 密集型任务。

## 相关决策

- [[decision_20260826_001]]: 使用 asyncio 实现 Web Crawler

## 延伸问题

- asyncio 和 threading 的性能差异有多大？
- 如何判断任务是 I/O 密集型还是 CPU 密集型？
```

**✅ 确认点：**
- [ ] 同意 YAML frontmatter + Markdown body 格式
- [ ] 同意 Belief/Decision/Question 的字段定义
- [ ] 同意使用双向链接 `[[...]]`

---

### C4. 文件命名规范 ✅ 推荐方案

**决策：** `{type}_{date}_{seq}.md`

**命名规则：**

```
beliefs/belief_20260826_001.md
beliefs/belief_20260826_002.md

decisions/decision_20260826_001.md

questions/question_20260826_001.md
```

**ID 生成规则：**

```python
def generate_id(entity_type: str) -> str:
    """生成唯一 ID"""
    date_str = datetime.now().strftime("%Y%m%d")
    
    # 查询当天已有的最大序号
    existing_ids = get_existing_ids(entity_type, date_str)
    max_seq = max([int(id.split('_')[-1]) for id in existing_ids], default=0)
    
    seq = max_seq + 1
    return f"{entity_type}_{date_str}_{seq:03d}"

# 示例
generate_id("belief")  # → "belief_20260826_001"
generate_id("decision")  # → "decision_20260826_001"
```

**✅ 确认点：**
- [ ] 同意 `{type}_{date}_{seq}` 命名格式
- [ ] 同意序号从 001 开始，3 位数字

---

## D. 集成层决策（3 个）

### D1. File Watcher 防抖动策略 ✅ 推荐方案

**决策：** 2 秒防抖动 + 文件完整性检查

**实现方案：**

```python
class WikiFileWatcher(FileSystemEventHandler):
    def __init__(self, knowledge_vault: KnowledgeVault):
        self.knowledge_vault = knowledge_vault
        self.pending_files = {}  # file_path -> (last_modified_time, file_size)
        self.debounce_delay = 2.0  # 秒
        self.timer = None
    
    def on_created(self, event):
        if event.is_directory or not event.src_path.endswith('.md'):
            return
        
        # 记录文件信息
        self.pending_files[event.src_path] = (time.time(), 0)
        
        # 重置防抖动计时器
        self._schedule_batch_process()
    
    def on_modified(self, event):
        # 同 on_created
        self.on_created(event)
    
    def _schedule_batch_process(self):
        """调度批量处理（防抖动）"""
        if self.timer:
            self.timer.cancel()
        
        self.timer = threading.Timer(self.debounce_delay, self._batch_process)
        self.timer.start()
    
    def _batch_process(self):
        """批量处理待摄入的文件"""
        for file_path in list(self.pending_files.keys()):
            try:
                # 检查文件是否完整（不再增长）
                if not self._is_file_complete(file_path):
                    log.debug(f"文件尚未完整: {file_path}，等待下一轮")
                    continue
                
                # 摄入 Wiki 页面
                self.knowledge_vault.ingest_wiki_page(file_path)
                log.info(f"✅ 已摄入: {os.path.basename(file_path)}")
                
                # 从待处理队列移除
                del self.pending_files[file_path]
            except Exception as e:
                log.error(f"❌ 摄入失败 {file_path}: {e}")
                # 不移除，下次重试
    
    def _is_file_complete(self, file_path: str) -> bool:
        """检查文件是否完整（不再增长）"""
        if not os.path.exists(file_path):
            return False
        
        size1 = os.path.getsize(file_path)
        time.sleep(0.1)
        size2 = os.path.getsize(file_path)
        
        return size1 == size2 and size1 > 0
```

**防抖动策略：**
- 2 秒内的多次事件合并为一次处理
- 避免 llm_wiki 批量生成时的事件风暴

**文件完整性检查：**
- 检查文件大小是否稳定（0.1 秒内未变化）
- 避免读取到不完整的内容

**✅ 确认点：**
- [ ] 同意 2 秒防抖动延迟
- [ ] 同意文件完整性检查（0.1 秒采样间隔）
- [ ] 同意失败后保留在队列，下次重试

---

### D2. llm_wiki API 降级方案 ✅ 推荐方案

**决策：** 降级到本地文件读取 + 语义搜索

**场景：** llm_wiki API 不可用（应用未启动、Token 过期、网络问题）

**实现方案：**

```python
class LlmWikiClient:
    def __init__(self, base_url: str, token: str, wiki_dir: str):
        self.base_url = base_url
        self.token = token
        self.wiki_dir = wiki_dir
        self.api_available = self._check_api_availability()
    
    def _check_api_availability(self) -> bool:
        """检查 API 是否可用"""
        try:
            response = requests.get(
                f"{self.base_url}/health",
                timeout=2.0
            )
            return response.status_code == 200
        except Exception:
            return False
    
    def search(self, query: str, top_k: int = 10) -> List[SearchResult]:
        """混合检索（API 优先，降级到本地）"""
        if self.api_available:
            try:
                return self._api_search(query, top_k)
            except (ConnectionError, Timeout, requests.RequestException) as e:
                log.warning(f"llm_wiki API 失败: {e}，降级到本地搜索")
                self.api_available = False  # 标记为不可用
        
        # 降级：本地搜索
        return self._local_search(query, top_k)
    
    def _api_search(self, query: str, top_k: int) -> List[SearchResult]:
        """通过 API 搜索"""
        response = requests.post(
            f"{self.base_url}/projects/current/search",
            headers={"Authorization": f"Bearer {self.token}"},
            json={"query": query, "topK": top_k, "includeContent": True},
            timeout=5.0
        )
        response.raise_for_status()
        
        data = response.json()
        return [
            SearchResult(
                file_path=hit["filePath"],
                content=hit.get("content", ""),
                score=hit.get("vectorScore", 0.0)
            )
            for hit in data["results"]
        ]
    
    def _local_search(self, query: str, top_k: int) -> List[SearchResult]:
        """本地搜索（降级方案）"""
        # 方案 A: 使用 scripts/semantic.py
        from scripts import semantic
        return semantic.search(query, top_k, index_path=f"{self.wiki_dir}/.index")
        
        # 或者方案 B: 简单的关键词搜索
        # return self._keyword_search(query, top_k)
    
    def get_file_content(self, path: str) -> str:
        """读取文件内容（API 优先，降级到本地）"""
        if self.api_available:
            try:
                return self._api_get_file_content(path)
            except Exception as e:
                log.warning(f"llm_wiki API 失败: {e}，降级到本地读取")
                self.api_available = False
        
        # 降级：直接读取本地文件
        full_path = os.path.join(self.wiki_dir, path)
        with open(full_path, 'r', encoding='utf-8') as f:
            return f.read()
```

**降级策略总结：**

| 功能 | API 主路径 | 降级方案 |
|------|-----------|---------|
| 搜索 | POST /search | scripts/semantic.py 本地搜索 |
| 读取文件 | GET /files/content | 直接读取本地文件 |
| 知识图谱 | GET /graph | 本地解析 Wikilinks |
| 触发扫描 | POST /sources/rescan | 无（非关键功能）|

**✅ 确认点：**
- [ ] 同意降级到本地文件读取 + 语义搜索
- [ ] 同意 API 失败后标记为不可用（避免重复尝试）
- [ ] 同意非关键功能（如触发扫描）无需降级

---

### D3. 多项目支持策略 ✅ 推荐方案

**决策：** V0 单项目绑定，V1 支持多项目

**V0 配置：**

```yaml
# config/llm_wiki.yaml
project:
  id: "abc123"
  name: "My Knowledge Base"
  path: "/Users/user/llm_wiki/projects/my_kb"
  wiki_dir: "/Users/user/llm_wiki/projects/my_kb/wiki"

api:
  base_url: "http://127.0.0.1:19828/api/v1"
  token: "${LLM_WIKI_API_TOKEN}"  # 从环境变量读取
```

**项目切换检测（可选，V0 暂不实现）：**

```python
def detect_project_change():
    """检测 llm_wiki 项目是否切换"""
    try:
        current_project = llm_wiki_client.get_current_project()
        
        if current_project.id != config.project.id:
            log.warning(f"⚠️  llm_wiki 项目已切换:")
            log.warning(f"   配置: {config.project.name} ({config.project.id})")
            log.warning(f"   当前: {current_project.name} ({current_project.id})")
            log.warning(f"   请更新配置文件: config/llm_wiki.yaml")
            
            # 暂停 File Watcher，避免摄入错误项目的数据
            file_watcher.pause()
    except Exception as e:
        log.error(f"项目检测失败: {e}")
```

**✅ 确认点：**
- [ ] 同意 V0 单项目绑定
- [ ] 同意在配置文件中明确项目路径
- [ ] 同意 V1 再实现多项目支持

---

## E. 演进性决策（2 个）

### E1. V0 → V1 迁移策略 ✅ 推荐方案

**决策：** 渐进式升级 + 数据兼容

**V0 → V1 变化：**

| 维度 | V0 | V1 |
|------|----|----|
| 模块数 | 3 个 | 8 个 |
| Support Tools | 独立脚本 | Module 8: Memory System |
| Agent | 手工调用 | Module 2: Agent Runtime |
| Workflow | 简单 Intent Router | Module 3: Workflow Engine |
| Model | 单一 Claude | Module 5: Model Gateway |

**迁移策略：**

```python
# V0 代码
from scripts import semantic

results = semantic.search(query)

# V1 代码（保持 V0 兼容）
from memory_system import MemorySystem

memory = MemorySystem()
results = memory.search(query)  # 内部封装 scripts/semantic.py

# V1.1 代码（完全迁移）
results = memory.semantic_search(query)  # 新实现
```

**数据兼容性：**
- Markdown 格式保持不变（向后兼容）
- SQLite Schema 增量升级（ALTER TABLE）
- 旧数据自动迁移

**迁移步骤：**

1. **Phase 1: 添加新模块（不破坏 V0）**
   - 添加 Module 2/3/5，与 V0 并存
   - V0 代码继续工作

2. **Phase 2: 逐步迁移调用方（渐进）**
   - 逐个文件迁移到新 API
   - 保留旧 API 作为兼容层

3. **Phase 3: 数据迁移（自动）**
   - 运行迁移脚本
   - 自动升级 Schema

4. **Phase 4: 移除旧代码（最后）**
   - 确认所有调用已迁移
   - 移除 V0 兼容层

**✅ 确认点：**
- [ ] 同意渐进式升级
- [ ] 同意保持 Markdown 格式向后兼容
- [ ] 同意提供自动迁移脚本

---

### E2. Support Tools → Memory System 升级 ✅ 推荐方案

**决策：** 封装旧脚本 → 逐步替换 → 完全重写

**阶段 1: V0（使用脚本）**

```python
# 直接调用脚本
from scripts import semantic, trustrank, context_bundle

results = semantic.search(query)
trust = trustrank.calculate(claim_id)
context = context_bundle.load(intent)
```

**阶段 2: V1 Early（封装脚本）**

```python
# Memory System 封装旧脚本
class MemorySystem:
    def __init__(self):
        self.semantic = semantic.SemanticSearch()  # 封装
        self.trustrank = trustrank.TrustRank()  # 封装
        self.context = context_bundle.ContextBundle()  # 封装
    
    def search(self, query: str):
        # 调用旧脚本
        return self.semantic.search(query)
```

**阶段 3: V1 Mid（部分重写）**

```python
# 新实现 + 旧实现并存
class MemorySystem:
    def search(self, query: str, use_new_impl: bool = False):
        if use_new_impl:
            return self._new_search(query)  # 新实现
        else:
            return self._legacy_search(query)  # 旧脚本
```

**阶段 4: V1 Late（完全重写）**

```python
# 只保留新实现
class MemorySystem:
    def search(self, query: str):
        return self._new_search(query)  # 新实现
```

**✅ 确认点：**
- [ ] 同意分阶段升级（V0 → V1 Early → V1 Mid → V1 Late）
- [ ] 同意在 V1 Early 保持旧脚本兼容
- [ ] 同意提供开关控制新旧实现

---

## F. 用户体验决策（1 个）

### F1. Belief 创建界面 ✅ 推荐方案

**决策：** CLI + Obsidian 模板（双通道）

**方式 1: CLI 创建（快速）**

```bash
# 交互式创建
$ cognition belief create

> Statement: Python asyncio 适合 I/O 密集型任务
> Based on claims (comma-separated): claim_001,claim_002
> Confidence (0-1): 0.9
> Tags (comma-separated): programming,python,concurrency

✅ Belief created: belief_20260826_001
📄 File: $OV/beliefs/belief_20260826_001.md

# 或者一行命令
$ cognition belief create \
    --statement "Python asyncio 适合 I/O 密集型任务" \
    --claims claim_001,claim_002 \
    --confidence 0.9 \
    --tags programming,python,concurrency

✅ Belief created: belief_20260826_001
```

**方式 2: Obsidian 模板（深度编辑）**

1. 在 Obsidian 中创建新文件 `beliefs/belief_new.md`
2. 使用模板插入内容
3. 填写字段
4. 保存后自动索引

**Obsidian 模板：**

```markdown
---
type: belief
id: <% tp.date.now("YYYYMMDD") %>_<% tp.file.cursor(1) %>
statement: "<% tp.file.cursor(2) %>"
confidence: <% tp.file.cursor(3) %>
based_on:
  - <% tp.file.cursor(4) %>
created: <% tp.date.now("YYYY-MM-DDTHH:mm:ss") %>Z
updated: <% tp.date.now("YYYY-MM-DDTHH:mm:ss") %>Z
tags:
  - <% tp.file.cursor(5) %>
---

# <% tp.file.cursor(6) %>

## 当前置信度

- **Confidence**: <% tp.file.cursor(7) %>
- **上次更新**: <% tp.date.now("YYYY-MM-DD") %>

## 支持证据

### 证据 1

- **来源**: [[<% tp.file.cursor(8) %>]]
- **内容**: <% tp.file.cursor(9) %>

## 变化历史

- <% tp.date.now("YYYY-MM-DD HH:mm") %>: 创建
```

**两种方式对比：**

| 维度 | CLI | Obsidian |
|------|-----|----------|
| 速度 | ✅ 快 | 较慢 |
| 编辑深度 | 基础 | ✅ 深度编辑 |
| 学习成本 | 低 | 需要学习模板 |
| 适用场景 | 快速创建 | 详细记录 |

**✅ 确认点：**
- [ ] 同意 CLI + Obsidian 双通道
- [ ] 同意 CLI 支持交互式和一行命令
- [ ] 同意提供 Obsidian 模板

---

## 决策总结

### 优先级 P0（必须立即确认）

- [x] A1. 模块分层架构
- [x] A2. Support Tools 调用方式
- [x] A3. Claim 引用完整性策略
- [x] A4. TrustRank → Confidence 更新策略
- [x] B1. Markdown + SQLite 双写原子性
- [x] B2. Obsidian → 系统同步策略
- [x] B3. SQLite 并发写入策略
- [x] C3. Markdown 文件格式规范
- [x] D1. File Watcher 防抖动策略
- [x] F1. Belief 创建界面

### 优先级 P1（实施前确认）

- [x] C1. 一致性检查策略
- [x] C2. 索引重建触发策略
- [x] C4. 文件命名规范
- [x] D2. llm_wiki API 降级方案
- [x] D3. 多项目支持策略

### 优先级 P2（V1 前确认）

- [x] E1. V0 → V1 迁移策略
- [x] E2. Support Tools → Memory System 升级

---

## 下一步行动

**立即行动（今天）：**
1. ✅ 用户确认所有决策
2. ⬜ 更新 PRD v0.2（基于确认的决策）
3. ⬜ 创建技术规范文档

**短期行动（本周）：**
1. ⬜ 搭建项目结构
2. ⬜ 实现存储层 POC
3. ⬜ 实现 llm_wiki 集成 POC

**中期行动（2-3 周）：**
1. ⬜ 实施 V0（18 天计划）

---

**决策日期:** 2026-08-26  
**决策状态:** ✅ 已完成建议，待用户确认  
**下一步:** 用户确认所有决策点