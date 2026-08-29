# Atelierr Agent Onboarding

任何编码代理（Kimi Code / Claude Code / Codex / Cursor 等）接手 Atelierr
开发前必读。本文件是唯一的跨代理入口。

## 仓库里有两个系统

| 系统 | 位置 | 你的关系 |
|---|---|---|
| **Atelierr 记忆管理系统**（在建） | `scripts/{memory,web,processors,cli,utils}/` | ✅ 你的工作范围 |
| Atelier 反思框架（存量，正常运行中） | `scripts/atelier/`、`.claude/`、`.codex/`、`.agents/`、`harness/`、`protocols/`、`frameworks/`、`sources/`、`tests/` 根层的 `test_*.py`、`scripts/*.sh` | ❌ 禁止改动 |

同样禁改：`CLAUDE.md`、`AGENTS.md`、`pyproject.toml`、`uv.lock`、`.venv`
（框架专用环境）。

## 契约（唯一事实源，冲突时以此为准）

1. **架构**：`docs/prd/ARCHITECTURE-LOCKED-V1.md`（**v1.3**）
2. **认知模块**：`docs/prd/COGNITION-SPEC.md`（**v1.0**）
3. **验收**：`docs/ACCEPTANCE-CRITERIA.md`（**v1.1**，测试规格逐条对应实现）
4. **计划**：`DEVELOPMENT-PLAN-3MVP.md`、`docs/prd/IMPLEMENTATION-PLAN-PARALLEL.md`

`docs/prd/archive/` 是历史存档，**不要引用**（旧模型清单见其 README）。

## 设计不变量（违反即返工）

- 笔记是 `$OV/memory/` 根层的平面 Markdown 文件，**无子目录**（Flatnotes 兼容）
- 机器**绝不移动、绝不改写**已创建的笔记文件；归一化补 frontmatter 时用
  `os.utime` 还原 mtime
- confidence/layer/last_accessed/references 等动态状态只存 sidecar 索引
  （`<state_dir>/index.json`）
- confidence 是无状态纯函数：`0.95 ** (idle_days / ref_factor)`
- 任何路径都不自动删除笔记：`pending_delete` 标记 → `review` → `purge` → `trash/`

## 环境

```bash
python3 -m venv .venv-atelierr        # 勿用 .venv（框架专用）
source .venv-atelierr/bin/activate
# 先装核心即可开发 MVP1（paddle/whisper 很重，做 MVP3 时再装）
pip install pyyaml watchdog python-frontmatter pytest pytest-cov click rich
# 完整依赖: pip install -r requirements.txt
```

## 测试与验证

```bash
pytest                                # 只收集 Atelierr 测试（pytest.ini 已限定）
python tools/acceptance_test.py       # 端到端验收
```

覆盖率只统计五个 Atelierr 包（pytest.ini 已配置），MVP 目标 ≥ 80%。
不要运行 `tests/` 根层的框架测试，也不要动 `scripts/atelier/` 下的工具。

## 工作顺序

1. **MVP1 记忆模块**：`core.py` → `confidence.py` → `decay.py` → `search.py`
   → `watcher.py`/`scheduler.py` → `cli/memory_cli.py`（测试与实现同步写）
2. **MVP2 Web**：`docker compose up -d` 验证 Flatnotes + `web/integration.py` 归一化
3. **MVP3 输入处理**：`processors/base.py` → `image.py` → `pdf.py`
   （video/audio 其次；wechat 在 backlog，不做）
4. 集成与端到端测试

## 提交规范

- 消息格式：`atelierr: <小写摘要>`（参考 `git log --oneline`）
- 只提交 Atelierr 范围内的文件；提交前跑 `pytest` 全绿
- 不 push、不改共享基础设施，除非用户明确要求
