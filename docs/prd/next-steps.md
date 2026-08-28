# Personal Intelligence System - 下一步行动计划

**创建日期:** 2026-08-26 19:45  
**状态:** Ready to Execute  
**基于:** PRD v0.2 + 已确认的 17 个架构决策

---

## 🎯 当前状态

✅ **已完成：**
1. PRD v0.1 创建（2332 行）
2. P0 问题识别与解决
3. PRD v0.2 创建（1032 行，简化版）
4. 架构深度审查（17 个关键问题）
5. 架构决策确认（17 个决策方案）

**文档产出：**
- `/srv/workspaces/Atelierr/docs/prd/personal-intelligence-system-prd-v0.1.md` (2332 行)
- `/srv/workspaces/Atelierr/docs/prd/personal-intelligence-system-prd-v0.2.md` (1032 行)
- `/srv/workspaces/Atelierr/docs/prd/p0-resolution.md` (1137 行)
- `/srv/workspaces/Atelierr/docs/prd/prd-v0.2-changes.md` (536 行)
- `/srv/workspaces/Atelierr/docs/prd/architecture-review.md` (审查文档)
- `/srv/workspaces/Atelierr/docs/prd/architecture-decisions.md` (决策文档，已确认)
- `/srv/workspaces/Atelierr/docs/prd/next-steps.md` (本文档)

---

## 📋 下一步选项

### 选项 1: 创建技术规范文档 📐

**目标:** 将架构决策转化为可实施的技术规范

**产出:**
- API 接口定义（Python Protocol/ABC）
- 数据模型定义（Pydantic Models）
- 存储 Schema 定义（SQL DDL）
- 配置文件格式（YAML Schema）
- CLI 命令规范（argparse/typer）

**工作量:** 1-2 天

**适合场景:** 你想要完整的技术蓝图后再开始编码

---

### 选项 2: 搭建项目结构 🏗️

**目标:** 创建 V0 的目录结构和基础代码框架

**产出:**
```
personal-intelligence-system/
├── src/
│   ├── cognition_core/      # Module 1
│   ├── knowledge_vault/      # Module 4
│   ├── human_interface/      # Module 7
│   ├── storage/              # Storage Layer
│   └── utils/
├── scripts/                  # Support Tools (复用 Atelier)
├── config/                   # 配置文件
├── tests/                    # 测试
├── docs/                     # 文档
├── pyproject.toml
└── README.md
```

**工作量:** 0.5-1 天

**适合场景:** 你想快速看到项目结构，边写边完善

---

### 选项 3: 实施关键 POC 🧪

**目标:** 验证 3 个最关键的技术点

**POC 1: 存储层（Markdown + SQLite 双写）**
- 实现 BeliefRepository
- 测试双写机制
- 验证性能（< 200ms）

**POC 2: llm_wiki 集成（File Watcher + HTTP API）**
- 实现 WikiFileWatcher
- 实现 LlmWikiClient
- 测试集成流程

**POC 3: Obsidian 同步（File Watcher）**
- 实现 ObsidianFileWatcher
- 测试防抖动机制
- 验证一致性

**工作量:** 2-3 天

**适合场景:** 你想先验证技术可行性，降低风险

---

### 选项 4: 开始 V0 实施（完整开发）🚀

**目标:** 按照 18 天计划开始完整实施

**Week 1: 基础设施（Day 1-5）**
- Day 1-2: 存储层实现
- Day 3-4: llm_wiki 集成
- Day 5: 测试和文档

**Week 2: Cognition Core（Day 6-10）**
- Day 6-8: Belief Management
- Day 9-10: Question & Decision

**Week 3: Knowledge Vault（Day 11-15）**
- Day 11-13: Knowledge Ingestion
- Day 14-15: 查询和检索

**Week 4: Human Interface & 测试（Day 16-20）**
- Day 16-17: Obsidian 集成
- Day 18: CLI 实现
- Day 19-20: 端到端测试

**工作量:** 18 天（4 周）

**适合场景:** 你已经准备好开始完整开发

---

## 🎯 我的推荐

**推荐路径：选项 3（POC）→ 选项 2（结构）→ 选项 4（实施）**

**理由：**
1. **POC 先行** — 验证 3 个最关键的技术点，降低风险
2. **搭建结构** — POC 验证后，搭建完整项目结构
3. **完整实施** — 按照 18 天计划完整实施

**时间线：**
- Week 1: POC（2-3 天）+ 项目结构（1 天）
- Week 2-5: V0 完整实施（18 天）
- **总计:** 约 22 天

---

## 📊 POC 详细计划（推荐从这里开始）

### POC 1: 存储层验证（Day 1，4-6 小时）

**目标:** 验证 Markdown + SQLite 双写机制

**实现内容:**

```python
# 1. 定义数据模型
class Belief:
    id: str
    statement: str
    confidence: float
    based_on: List[str]
    created: datetime
    updated: datetime

# 2. 实现 Repository
class BeliefRepository:
    def save(self, belief: Belief) -> None:
        # 写 Markdown
        write_markdown(belief)
        # 异步写 SQLite
        self.index_queue.put(belief)
    
    def get(self, belief_id: str) -> Belief:
        # 优先 SQLite，回退 Markdown
        ...

# 3. 性能测试
def test_performance():
    # 创建 1000 个 Beliefs
    # 测量写入延迟
    # 测量查询延迟
```

**验收标准:**
- ✅ 写入延迟 < 50ms（Markdown）
- ✅ 查询延迟 < 200ms（SQLite）
- ✅ 一致性检查通过
- ✅ 异步索引正常工作

**产出:**
- `src/storage/belief_repository.py`
- `tests/test_storage.py`
- 性能报告（Markdown）

---

### POC 2: llm_wiki 集成验证（Day 2，4-6 小时）

**目标:** 验证 File Watcher + HTTP API 集成

**实现内容:**

```python
# 1. 实现 File Watcher
class WikiFileWatcher:
    def on_created(self, event):
        # 防抖动
        self.pending_files[event.src_path] = time.time()
        self._schedule_batch_process()
    
    def _batch_process(self):
        # 批量处理
        for file_path in self.pending_files:
            self.ingest_wiki_page(file_path)

# 2. 实现 HTTP API Client
class LlmWikiClient:
    def search(self, query: str):
        # 主路径：API
        try:
            return self._api_search(query)
        except Exception:
            # 降级：本地搜索
            return self._local_search(query)

# 3. 集成测试
def test_integration():
    # 创建测试 Wiki 文件
    # 触发 File Watcher
    # 验证摄入成功
```

**验收标准:**
- ✅ File Watcher 正常监听
- ✅ 防抖动机制生效（2秒）
- ✅ HTTP API 调用成功
- ✅ 降级机制正常工作

**产出:**
- `src/integration/wiki_file_watcher.py`
- `src/integration/llm_wiki_client.py`
- `tests/test_integration.py`
- 集成测试报告

---

### POC 3: Obsidian 同步验证（Day 3，4-6 小时）

**目标:** 验证 Obsidian → 系统的实时同步

**实现内容:**

```python
# 1. 实现 Obsidian File Watcher
class ObsidianFileWatcher:
    def on_modified(self, event):
        # 解析 Markdown
        entity = parse_markdown(event.src_path)
        # 更新 SQLite
        self.repository.update_index(entity)

# 2. 实现 Markdown Parser
def parse_markdown(file_path: str) -> Entity:
    # 解析 YAML frontmatter
    # 解析 Markdown body
    # 返回实体对象

# 3. 同步测试
def test_sync():
    # 模拟 Obsidian 修改文件
    # 验证 SQLite 更新
    # 验证一致性
```

**验收标准:**
- ✅ 文件修改被检测到
- ✅ Markdown 解析正确
- ✅ SQLite 更新成功
- ✅ 防抖动机制生效（500ms）

**产出:**
- `src/integration/obsidian_file_watcher.py`
- `src/parsers/markdown_parser.py`
- `tests/test_obsidian_sync.py`
- 同步测试报告

---

## 📈 POC 成功标准

**技术可行性:**
- ✅ 所有 POC 验收标准通过
- ✅ 性能目标达成
- ✅ 无阻塞性技术风险

**如果 POC 失败:**
- ⚠️ 调整架构决策
- ⚠️ 寻找备选方案
- ⚠️ 重新评估 V0 范围

**如果 POC 成功:**
- ✅ 进入项目结构搭建
- ✅ 开始完整实施

---

## 🛠️ 环境准备

**开发环境:**
```bash
# 1. Python 环境
python3 -m venv .venv
source .venv/bin/activate

# 2. 安装依赖
pip install -r requirements.txt

# 3. 配置 llm_wiki
# 确保 llm_wiki 已安装并运行
# 获取 API Token
```

**依赖项（初步）:**
```txt
# requirements.txt
pydantic>=2.0
sqlite3  # 内置
watchdog>=3.0  # File Watcher
requests>=2.31  # HTTP Client
pyyaml>=6.0  # YAML 解析
typer>=0.9  # CLI 框架
rich>=13.0  # CLI 美化输出
pytest>=7.4  # 测试框架
pytest-asyncio>=0.21  # 异步测试
```

**目录准备:**
```bash
# 创建项目目录
mkdir -p personal-intelligence-system/{src,tests,config,docs}
cd personal-intelligence-system

# 初始化 Git
git init
git add .
git commit -m "Initial commit: Project setup"
```

---

## 📅 时间表

**如果选择 POC 路径（推荐）：**

| 日期 | 任务 | 产出 | 状态 |
|------|------|------|------|
| Day 1 (今天) | POC 1: 存储层 | BeliefRepository + 测试 | ⬜ |
| Day 2 | POC 2: llm_wiki 集成 | File Watcher + API Client | ⬜ |
| Day 3 | POC 3: Obsidian 同步 | Obsidian Watcher + Parser | ⬜ |
| Day 4 | 搭建项目结构 | 完整目录结构 | ⬜ |
| Day 5-22 | V0 完整实施 | 按 18 天计划 | ⬜ |

**总计:** 22 天（约 4.5 周）

---

## 🎯 立即行动

**推荐：从 POC 1 开始**

**步骤：**
1. ✅ 确认环境准备完成
2. ⬜ 创建项目目录
3. ⬜ 开始 POC 1: 存储层验证
4. ⬜ 每天晚上汇报进度

**今天的目标（Day 1）：**
- 完成 POC 1: 存储层验证
- 验证 Markdown + SQLite 双写机制
- 确认性能达标

---

## 💬 你的决定

**请选择：**

**A. 开始 POC 1（推荐）** — 我立即协助你开始存储层 POC

**B. 先创建技术规范** — 我创建完整的 API 定义和数据模型文档

**C. 直接搭建项目结构** — 我创建完整的目录结构和基础代码

**D. 其他想法** — 告诉我你的想法

---

**创建时间:** 2026-08-26 19:45  
**状态:** 等待你的选择  
**下一步:** 根据你的选择开始执行
