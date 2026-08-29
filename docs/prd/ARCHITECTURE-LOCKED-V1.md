# Atelierr 架构规范 v1.2 (LOCKED)

**版本**: v1.2  
**状态**: 🔒 已锁定  
**日期**: 2026-08-28  
**下次修订**: 需明确的问题或需求变更时

> v1.1 修订：Confidence 语义统一为"新鲜度"模型，与 `docs/ACCEPTANCE-CRITERIA.md` 对齐。  
> v1.2 修订：平面存储（Flatnotes 兼容）+ sidecar 状态索引 + 无状态 confidence 重算 + 访问信号契约 + trash/purge 流程。

---

## 文档说明

本文档是 Atelierr 系统的**官方架构规范**，当前锁定版本为 v1.2。

**修订原则**:
- ✅ 实现过程中发现的技术细节可补充
- ✅ 发现重大设计缺陷时可修订
- ❌ 不因小的困难而轻易改动
- ❌ 保持架构稳定性优先

---

## 系统总览

Atelierr 是一个**基于 LLM 的个人反思系统**，通过三个独立模块协同工作：

```
┌──────────────────────────────────────┐
│  模块 1: Web 交互界面 (Flatnotes)   │
│  • Docker 独立部署                   │
│  • 提供网页访问                      │
│  • 移动端友好                        │
└────────────┬─────────────────────────┘
             ↓ (读写文件系统)
┌──────────────────────────────────────┐
│  模块 2: 记忆模块 (Memory-Like-A-Tree)│
│  • scripts/memory/ (Python 包)       │
│  • Confidence-based lifecycle        │
│  • 自动衰减机制                      │
└────────────┬─────────────────────────┘
             ↓ (被调用)
┌──────────────────────────────────────┐
│  模块 3: Atelierr 核心 (现有系统)   │
│  • .claude/agents/ (15+ Agents)     │
│  • 反思、研究、阅读流程              │
│  • 语义搜索和上下文管理              │
└──────────────────────────────────────┘
```

---

## 核心原则

### 1. 完全解耦

```
✅ 三个模块通过文件系统通信
✅ 任何模块可独立替换
✅ 无直接 API 调用依赖
✅ Markdown 文件为唯一数据交换格式
```

### 2. 数据为中心

```
✅ $OV/ 是唯一数据源
✅ Markdown + YAML frontmatter
✅ 人类可读、可编辑
✅ Git 可追踪历史
```

### 3. 渐进式增强

```
✅ 现有功能不受影响
✅ 新模块独立添加
✅ 可逐步启用新功能
✅ 降级方案可用
```

---

## 模块 1: Web 交互界面

### 基本信息

```yaml
名称: Flatnotes Web 界面
来源: dullage/flatnotes (GitHub)
部署: Docker 容器
位置: 独立部署，不在 Atelierr 代码库
```

### 核心功能

```
✅ Web UI (Vue.js 前端 + Flask 后端)
✅ 移动端响应式设计
✅ Markdown 编辑器
✅ 全文搜索
✅ 标签系统
✅ 飞书机器人集成（可选）
```

### 部署方式

```bash
# 推荐: docker/docker-compose.yml
cd docker && cp .env.example .env  # 设置密码后
docker compose up -d

# 等价的 docker run
docker run -d \
  --name flatnotes \
  -p 8080:8080 \
  -v /path/to/$OV/memory:/data \
  -e "FLATNOTES_AUTH_TYPE=password" \
  dullage/flatnotes
```

### 职责边界

```
负责:
  ✅ 用户交互界面
  ✅ 文件的 CRUD 操作
  ✅ 搜索和显示

不负责:
  ❌ Confidence 计算
  ❌ 记忆衰减
  ❌ 层级分配
  ❌ Agent 调度
```

### 数据格式

```markdown
---
title: 笔记标题
created: 2026-08-27T16:00:00
source: web
tags: [learning, python]
---

笔记内容...
```

---

## 模块 2: 记忆模块

### 基本信息

```yaml
名称: Memory-Like-A-Tree (自实现)
位置: Atelierr/scripts/memory/ (Python 包)
语言: Python 3.11+
依赖: python-frontmatter, pathlib
```

### 核心功能

```python
class MemoryTree:
    """记忆模块核心类"""
    
    def __init__(self, ov_path: str):
        """初始化平面笔记目录与 sidecar 状态目录（不存在则创建）"""
        
    def create_note(self, filename: str, content: str) -> Path:
        """创建新笔记（平面目录根层），登记 sidecar，初始 confidence = 1.0"""
        
    def read_note(self, note_path: Path) -> str:
        """读取笔记内容，文件不存在抛 FileNotFoundError"""
        
    def move_note(self, note_path: Path, layer: str) -> Path:
        """手动覆写笔记层级（写 sidecar，不移动文件）"""
        
    def list_notes(self, layer: str) -> List[Path]:
        """按 sidecar 中的 layer 列出笔记"""
        
    def search(self, query: str) -> List[Memory]:
        """搜索记忆（委托 MemorySearcher）"""
        
    def get_stats(self) -> Dict:
        """获取记忆统计信息"""

# 配套组件
#   ConfidenceCalculator  - 无状态 confidence 重算（confidence.py）
#   DecayManager          - 每日重算/分层/待删标记/报告，支持 dry-run（decay.py）
#   MemorySearcher        - 全文/标签/日期搜索（search.py）
#   memory_cli review/purge - 待删除笔记的人工确认与移入 trash（cli/）
```

### 存储结构

```
$OV/memory/                     # 平面目录（Flatnotes 直接挂载；不使用子目录）
├── asyncio-not-for-cpu.md
├── 2026-08-28-quick-idea.md
└── ...                         # 所有笔记都在根层，文件永不被机器移动

<state_dir>/                    # 机器状态目录（config/memory.yaml: state_dir）
├── index.json                  # sidecar 索引：id / layer / confidence /
│                               #   last_accessed / references / pending_delete
├── reports/                    # 衰减报告 decay-YYYY-MM-DD.md
└── trash/                      # purge 后的笔记归宿（永不静默删除）
```

**逻辑分层**（layer 是 sidecar 索引中的派生属性，不是物理目录）：

```
short-term   confidence ≥ 0.7        新鲜、活跃
mid-term     0.4 ≤ confidence < 0.7
long-term    confidence < 0.4        低频归档
```

原三层子目录方案已废弃：Flatnotes 是刻意的平面设计（不支持子目录），
且物理移动文件会破坏笔记身份、wiki 链接和并发写入。原分类目录
（observations/ideas/beliefs/...）改用 frontmatter tags 表达。

### Confidence 机制

```python
# Confidence 表示"新鲜度/活跃度"，范围 [0.0, 1.0]
# 无状态纯函数：任何时刻都能从元数据重算，不依赖上一次的值

class ConfidenceCalculator:
    def calculate(self, metadata: Dict) -> float:
        # 活跃时点 = 最后访问与最后修改的较新者
        last_active = max(metadata["accessed"], metadata["modified"])
        idle_days = (now - last_active).days

        # 引用减缓时间流逝（被引用越多，衰减越慢）
        ref_factor = 1 + 0.2 * min(metadata.get("references", 0), 10)

        return 0.95 ** (idle_days / ref_factor)
```

**设计要点**：
- 新笔记 idle_days = 0 → confidence = 1.0
- 无引用笔记：约 7 天降到 0.7（出 short-term），约 19 天降到 0.4，
  约 45 天降到 0.1（进入待删除标记区）
- 10 次引用（ref_factor = 3）：时间轴放慢 3 倍，约 135 天才触及 0.1
- 纯函数 ⇒ 幂等：定时任务漏跑、重跑结果都一致；不存在增量复利误差
- 衰减率与引用系数通过 `config/memory.yaml` 配置

**访问信号契约**（衰减的输入从哪来）：
- `modified`：文件 mtime（用户在 Flatnotes/Obsidian 编辑即刷新）— 主信号
- `accessed`：CLI / Agent 调用 `on_note_accessed()` 时写入 sidecar — 辅信号
- 明确接受的降级：**Web 端纯阅读不计入访问**（Flatnotes 无回调机制，
  文件系统 atime 不可靠）。阅读多、编辑少的重要笔记靠引用因子保护
- `references`：每日任务全量扫描 `[[wikilink]]` 反链得出，写入 sidecar

`source`（web/obsidian/lark/agent/reflection）仅作为元数据记录，不参与计算。

### 衰减机制

```python
# 每日任务（幂等；只写 sidecar 索引，绝不改动笔记文件）
def daily_decay(dry_run: bool = False):
    references = scan_backlinks(memory_root)      # 全量 [[wikilink]] 反链统计

    for note in all_notes(memory_root):
        meta = index.metadata(note, references)   # accessed/modified/references
        conf = calculator.calculate(meta)         # 无状态重算

        new_layer = assign_layer(conf)            # ≥0.7 short / ≥0.4 mid / else long
        pending = conf < 0.1                      # 只标记，绝不自动删除

        if not dry_run:
            index.update(note, confidence=conf,
                         layer=new_layer, pending_delete=pending)

    report = build_report(index)                  # 层级迁移 + 待删除清单
    write(state_dir / "reports" / f"decay-{today}.md", report)
```

**待删除流程**：`pending_delete` 笔记只出现在报告和 `memory_cli review` 里，
由用户确认后执行 `memory_cli purge`，笔记移入 `<state_dir>/trash/`。
trash 内容不参与索引和搜索，用户可随时手工找回。系统在任何路径下都
不会静默删除笔记文件。

### 访问增强

```python
# 记忆被访问时（CLI / Agent 显式上报）
def on_note_accessed(note_path: Path):
    # 只更新 sidecar 的活跃时点；confidence 由纯函数在下次计算时得出
    # （idle 归零 ⇒ confidence 回到 ~1.0，层级随之回升）
    index.update(note_path, last_accessed=datetime.now())
```

不再使用 "+0.05" 式加分：在无状态模型下，访问的语义就是"重置闲置时钟"，
与遗忘曲线的复习模型一致，也避免了与每日任务的重复计分。

### 职责边界

```
负责:
  ✅ Confidence 计算和更新
  ✅ 自动衰减调度
  ✅ 层级分配和迁移
  ✅ 记忆搜索
  ✅ 统计和报告

不负责:
  ❌ Web UI
  ❌ 用户交互
  ❌ Agent 调度
  ❌ 反思流程
```

---

## 模块 3: Atelierr 核心

### 基本信息

```yaml
位置: .claude/agents/
语言: Markdown (Agent 定义) + Python (脚本)
Agents: 15+ 个专业 Agents
```

### 核心 Agents

```
现有 Agents (保持不变):
  • researcher.md      - 研究员
  • synthesizer.md     - 综合者
  • reader.md          - 阅读者
  • scholar.md         - 学者
  • scout.md           - 侦查员
  • thinker.md         - 思考者
  • challenger.md      - 挑战者
  • curator.md         - 策展人
  • evolver.md         - 进化者
  • librarian.md       - 图书管理员
  • meeting.md         - 会议记录员
  • scribe.md          - 抄写员
  • reviewer.md        - 审阅者
  • privacy-reviewer.md - 隐私审查员

新增 Agents:
  • forgetter.md       - 遗忘者 (主动衰减)
```

### Forgetter Agent (新增)

```markdown
# Forgetter Agent

## 角色
遗忘者 - 主动管理记忆衰减和清理

## 能力
- 定期执行记忆衰减
- 识别低价值记忆
- 生成遗忘报告
- 建议记忆归档

## 工作流程
1. 扫描所有记忆
2. 计算每个记忆的价值
3. 执行自动衰减
4. 标记待删除记忆
5. 生成遗忘报告

## 调用方式
```python
from scripts.memory.core import MemoryTree
from scripts.memory.decay import DecayManager

memory = MemoryTree(ov_path=OV_PATH)
report = DecayManager(memory).run()
print(report)
```
```

### Agent 如何使用记忆模块

```python
# 任何 Agent 都可以这样使用记忆模块

from scripts.memory.core import MemoryTree

def agent_workflow():
    # 初始化
    memory = MemoryTree(ov_path=OV_PATH)
    
    # 搜索相关记忆
    relevant = memory.search(
        query="asyncio performance",
        layer="mid-term"  # 可选：限定层级
    )
    
    # 使用记忆进行工作
    for mem in relevant:
        print(f"Found: {mem.title} (confidence: {mem.confidence})")
    
    # 创建新记忆（进入 short-term/，confidence = 1.0）
    memory.create_note(
        filename="new-insight-about-asyncio.md",
        content="...",
        source="agent"
    )
```

### 职责边界

```
负责:
  ✅ 反思流程编排
  ✅ Agent 协作
  ✅ 语义搜索
  ✅ 上下文管理
  ✅ 调用记忆模块

不负责:
  ❌ Web UI
  ❌ 记忆生命周期管理（委托给模块 2）
  ❌ 直接文件操作（通过记忆模块）
```

---

## 数据格式规范

### 记忆文件格式

frontmatter 在创建时写入一次，此后**机器不再改写笔记文件**
（confidence / layer / last_accessed 等动态状态存于 sidecar 索引，
避免 mtime 污染、Git 噪音和与 Web 编辑器的写冲突）：

```markdown
---
# 创建时写入，静态不变
id: "01J6ABCDEF"               # 稳定 ID（层级与链接不随文件名变化失效）
title: "asyncio 不适合 CPU 密集型任务"
created: "2026-08-27T16:00:00+08:00"
source: "reflection"           # web, obsidian, lark, agent, reflection
tags: ["python", "asyncio", "beliefs"]   # 原 category 用 tag 表达

# 关联（用户/Agent 维护）
related: ["[[Python GIL]]", "[[Threading vs Asyncio]]"]
references: ["https://example.com/article"]
---

# asyncio 不适合 CPU 密集型任务

## 核心观点

asyncio 是为 I/O 密集型任务设计的...

## 证据

1. 测试结果：...
2. 性能对比：...

## 相关经验

- [[项目 X 性能优化]] 中的实践
- 与 [[Threading]] 的对比

## 行动建议

- CPU 密集型任务使用 multiprocessing
- I/O 密集型任务使用 asyncio
```

**sidecar 索引条目**（`<state_dir>/index.json`，以 id 为键）：

```json
{
  "01J6ABCDEF": {
    "path": "asyncio-not-for-cpu.md",
    "confidence": 0.85,
    "layer": "short-term",
    "last_accessed": "2026-08-27T18:00:00+08:00",
    "references": 3,
    "pending_delete": false
  }
}
```

### 认知文件格式

```markdown
---
title: "线程安全的最佳实践"
type: "belief"                # belief, question, hypothesis
confidence: 0.92
created: "2026-08-27T16:00:00+08:00"
upgraded_from: "memory/mid-term/learnings/thread-safety.md"
---

# 线程安全的最佳实践

（高信心的信念内容）
```

---

## 技术栈

### 模块 1: Web 界面

```yaml
前端:
  - Vue.js 3
  - Tailwind CSS
  - Markdown-it (渲染)

后端:
  - Flask (Python)
  - Whoosh (全文搜索)

部署:
  - Docker
  - Nginx (反向代理)
```

### 模块 2: 记忆模块

```yaml
语言: Python 3.11+

核心依赖:
  - python-frontmatter  # YAML frontmatter 解析
  - pathlib             # 文件路径操作
  - datetime            # 时间处理

可选依赖:
  - sentence-transformers  # 语义搜索（未来）
  - numpy                  # 数值计算（未来）
```

### 模块 3: Atelierr 核心

```yaml
语言: 
  - Markdown (Agent 定义)
  - Python 3.11+ (脚本)

现有依赖:
  - anthropic           # Claude API
  - openai              # OpenAI API (可选)
  - chromadb            # 向量数据库
  - python-frontmatter  # Markdown 解析

新增依赖:
  - 无（复用现有）
```

---

## 接口规范

### 文件系统接口

```
模块间通过文件系统通信：

Web 界面 (Flatnotes)
    ↓ 写入
    $OV/memory/*.md
    ↑ 读取
记忆模块 (memory.py)
    ↓ 调用
Atelierr Core (Agents)
```

### 记忆模块 API

```python
# scripts/memory/

class MemoryTree:
    """记忆模块主类 (core.py)"""
    
    # 初始化
    def __init__(self, ov_path: str) -> None:
        """初始化平面笔记目录与 sidecar 状态目录"""
    
    # 增
    def create_note(
        self,
        filename: str,
        content: str,
        source: str = "unknown",
        tags: Optional[List[str]] = None
    ) -> Path:
        """创建新笔记（平面目录根层），写一次性 frontmatter，
        登记 sidecar（confidence = 1.0, layer = short-term），返回路径"""
    
    # 查
    def read_note(self, note_path: Path) -> str:
        """读取笔记内容"""
    
    def list_notes(self, layer: str) -> List[Path]:
        """按 sidecar 中的 layer 过滤列出笔记"""
    
    def search(
        self,
        query: str = "",
        tags: Optional[List[str]] = None,
        date_from: Optional[str] = None,
        date_to: Optional[str] = None,
        layer: Optional[str] = None,
        limit: int = 10
    ) -> List[Memory]:
        """搜索记忆，结果按 confidence 排序"""
    
    # 改
    def move_note(self, note_path: Path, layer: str) -> Path:
        """手动覆写层级（只写 sidecar，不移动文件）"""
    
    def on_note_accessed(self, note_path: Path) -> None:
        """记录访问：更新 sidecar 的 last_accessed（闲置时钟归零）"""
    
    # 统计
    def get_stats(self) -> Dict:
        """获取记忆统计"""


class ConfidenceCalculator:
    """无状态 confidence 重算 (confidence.py)"""
    
    def calculate(self, metadata: Dict) -> float:
        """纯函数：0.95 ** (idle_days / ref_factor)，返回 [0.0, 1.0]，
        新笔记 = 1.0；幂等，可随时全量重算"""


class DecayManager:
    """衰减管理 (decay.py)"""
    
    def scan(self) -> Dict:
        """扫描全部笔记，返回分层统计报告（不写任何状态）"""
    
    def run(self, dry_run: bool = False) -> Dict:
        """每日任务：反链统计 → 全量重算 confidence → 更新 sidecar
        （layer、pending_delete<0.1）→ 生成报告。只写 sidecar，
        绝不改动笔记文件；dry_run=True 时只报告不写入"""
```

---

## 部署架构

### 开发环境

```
本地机器
├── $OV/                    (数据目录)
│   ├── memory/
│   ├── cognition/
│   └── ...
│
├── Atelierr/               (代码库)
│   ├── scripts/
│   │   └── memory.py
│   └── .claude/agents/
│
└── Docker                  (Flatnotes 容器)
    └── flatnotes:latest
        └── /data → $OV/memory/
```

### 生产环境（可选）

```
服务器
├── Docker Compose
│   ├── flatnotes          (Web 界面)
│   ├── nginx              (反向代理)
│   └── volumes
│       └── ov-data → $OV/
│
└── Cron Jobs
    ├── daily-decay.sh     (每日衰减)
    └── weekly-stats.sh    (每周统计)
```

---

## 工作流程

### 用户创建笔记

```
1. 用户打开 Flatnotes (https://memory.example.com)
2. 创建新笔记 "asyncio 测试失败"
3. Flatnotes 保存到 $OV/memory/asyncio-test-fail.md（平面目录根层）
4. watcher（或每日任务）发现未登记的新文件
5. 归一化：补写一次性 frontmatter（id, title, created, source: web）
6. 登记 sidecar：confidence = 1.0, layer = short-term
7. 此后机器不再改写该文件；层级/confidence 变化只发生在 sidecar
```

### Agent 使用记忆

```
1. Researcher Agent 需要搜索 "asyncio"
2. 调用 memory.search("asyncio", layer="mid-term")
3. memory 模块返回相关记忆列表
4. Agent 读取记忆内容
5. 调用 memory.on_note_accessed(note_path)
6. sidecar 中该笔记 last_accessed 归零（下次重算 confidence ≈ 1.0）
7. Agent 生成新洞察
8. 调用 memory.create_note(filename, content)
9. 新笔记登记为 short-term（confidence = 1.0），随访问情况自然分层
```

### 记忆衰减

```
1. Cron 每日 03:00 触发
2. 执行 python -m scripts.cli.memory_cli decay
3. DecayManager 全量扫描 [[wikilink]] 反链，更新 references
4. 对每个笔记（只写 sidecar，不碰文件）：
   - 无状态重算: conf = 0.95^(idle_days / ref_factor)
   - 按阈值更新逻辑层级: ≥0.7 short / 0.4~0.7 mid / <0.4 long
   - conf < 0.1: 置 pending_delete 标记（不自动删除）
5. 生成衰减报告（层级迁移 + 待删除清单）
6. 保存到 <state_dir>/reports/decay-YYYY-MM-DD.md
7. 用户择期 memory_cli review → 确认后 purge 移入 <state_dir>/trash/
```

---

## 实现路径

### Phase 1: 记忆模块核心 (Week 1-2)

```
✅ 实现 MemoryTree 类
✅ 实现 Confidence 计算
✅ 实现层级分配逻辑
✅ 实现基础搜索
✅ 编写单元测试
✅ 编写集成测试
```

### Phase 2: 衰减机制 (Week 2)

```
✅ 实现衰减算法
✅ 实现定时任务
✅ 实现访问增强
✅ 测试衰减逻辑
✅ 生成衰减报告
```

### Phase 3: Web 界面集成 (Week 3)

```
✅ 部署 Flatnotes Docker
✅ 配置文件挂载
✅ 测试文件读写
✅ 配置域名和 SSL
✅ 测试移动端访问
```

### Phase 4: Agent 集成 (Week 3-4)

```
✅ 创建 Forgetter Agent
✅ 更新现有 Agents 使用记忆模块
✅ 测试 Agent 工作流
✅ 优化性能
✅ 编写文档
```

### Phase 5: 认知模块 (Week 4+)

```
✅ 实现 cognition.py
✅ 实现升级机制
✅ 测试认知流程
✅ 集成到现有流程
```

---

## 性能目标

### 记忆模块

```
✅ 搜索延迟: < 100ms (1000 条记忆)
✅ 添加记忆: < 50ms
✅ 衰减全量: < 5s (10000 条记忆)
✅ 内存占用: < 100MB
```

### Web 界面

```
✅ 页面加载: < 2s
✅ 搜索响应: < 500ms
✅ 编辑保存: < 200ms
✅ 移动端流畅: 60fps
```

---

## 安全考虑

### 数据安全

```
✅ $OV/ 权限: 700 (仅用户可访问)
✅ Flatnotes 认证: 基础认证或 OAuth
✅ HTTPS: 强制使用 SSL
✅ 备份: 每日自动备份到独立位置
```

### 隐私保护

```
✅ 无外部服务依赖（除非用户启用）
✅ 所有数据本地存储
✅ Git 提交前隐私检查
✅ 敏感信息自动过滤
```

---

## 监控和日志

### 记忆模块日志

```
logs/memory.log
  - 记忆创建/删除
  - Confidence 变化
  - 衰减执行
  - 错误和异常
```

### 统计指标

```
每周自动生成:
  - 记忆总数（按层级）
  - Confidence 分布
  - 访问热力图
  - 衰减统计
  - 存储占用
```

---

## 降级方案

### 记忆模块不可用

```
✅ Agents 直接读取 $OV/memory/ 文件
✅ 不执行自动衰减（手动管理）
✅ Confidence 为固定值
```

### Web 界面不可用

```
✅ 使用 Obsidian 编辑
✅ 使用 CLI 工具
✅ 直接编辑 Markdown 文件
```

---

## 未来扩展

### 计划中

```
⏳ 语义搜索（向量数据库）
⏳ 记忆可视化（关系图）
⏳ 多模态记忆（图片、音频）
⏳ 协作记忆（多用户）
```

### 不计划

```
❌ 云端同步（保持本地优先）
❌ 社交功能（保持私密性）
❌ 复杂权限系统（单用户）
```

---

## 参考资料

### 灵感来源

```
• Memory-Like-A-Tree (GitHub)
  - Confidence-based lifecycle
  - 树状记忆结构

• Flatnotes (GitHub)
  - 简洁的 Web 界面
  - Markdown 编辑器

• Ebbinghaus Forgetting Curve
  - 遗忘曲线理论
  - 衰减算法基础
```

### 技术文档

```
• Python Frontmatter
  https://python-frontmatter.readthedocs.io/

• Flatnotes Documentation
  https://github.com/dullage/flatnotes

• Markdown Spec
  https://commonmark.org/
```

---

## 版本历史

### v1.2 (2026-08-28) - 平面存储与无状态衰减

```
✅ 平面存储：Flatnotes 刻意不支持子目录，三层物理目录方案废弃；
   layer 改为 sidecar 索引中的逻辑属性，文件永不被机器移动
✅ sidecar 状态索引 (<state_dir>/index.json)：confidence/layer/
   last_accessed/references/pending_delete 移出 frontmatter，
   frontmatter 创建时写一次后机器不再改写（消除 mtime 污染、
   Git 噪音、与 Web 编辑器的写冲突）
✅ 无状态 confidence：conf = 0.95^(idle_days / ref_factor)，
   纯函数幂等，修复增量式 0.95^days 每日复利错误与重复加分
✅ 访问信号契约：mtime（编辑）为主信号 + CLI/Agent 显式上报；
   明确接受 Web 纯阅读不计数的降级；references 由每日反链扫描产生
✅ 引用因子改为减缓时间流逝（乘性）而非加分（加性），
   使"读多改少"的重要笔记免于 45 天必然触底
✅ 待删除流程：pending_delete 标记 → review → purge → trash/，
   永不静默删除
```

### v1.1 (2026-08-28) - Confidence 语义对齐

```
✅ Confidence 统一为"新鲜度"模型（新笔记 = 1.0，随时间衰减）
✅ 分层阈值: ≥0.7 short-term / 0.4~0.7 mid-term / <0.4 long-term
✅ 删除策略: <0.1 仅标记待删除，不自动删除
✅ API 命名与 docs/ACCEPTANCE-CRITERIA.md 对齐
   (create_note / move_note / ConfidenceCalculator / DecayManager)
```

### v1.0 (2026-08-27) - 初始锁定版本

```
✅ 确定三模块架构
✅ 定义记忆模块 API
✅ 定义数据格式规范
✅ 明确职责边界
✅ 规划实现路径
```

---

## 附录

### 关键决策记录

#### 决策 1: 为什么选择 Flatnotes？

```
理由:
  ✅ 开源且活跃维护
  ✅ 简洁的设计
  ✅ 移动端友好
  ✅ 无数据库依赖（文件系统）
  ✅ Docker 部署简单

替代方案:
  ❌ 自己实现 Web UI (成本高)
  ❌ Obsidian Publish (不够灵活)
  ❌ Notion API (依赖外部服务)
```

#### 决策 2: 为什么自实现记忆模块？

```
理由:
  ✅ 完全控制衰减逻辑
  ✅ 深度集成 Atelierr
  ✅ 无外部依赖
  ✅ 代码量可控 (~500 行)

替代方案:
  ❌ 使用 Memory-Like-A-Tree 库 (不够灵活)
  ❌ 使用向量数据库 (过度设计)
```

#### 决策 3: 为什么通过文件系统通信？

```
理由:
  ✅ 完全解耦
  ✅ 人类可读
  ✅ Git 可追踪
  ✅ 无需 API 服务器
  ✅ 简单可靠

替代方案:
  ❌ RESTful API (增加复杂度)
  ❌ 数据库 (失去可读性)
  ❌ gRPC (过度设计)
```

---

## 联系方式

如需修订本架构文档，请：

1. 明确问题或需求
2. 提供替代方案对比
3. 说明修订理由
4. 更新版本号

---

**🔒 本文档已锁定为 v1.2 - 开始实现！**
