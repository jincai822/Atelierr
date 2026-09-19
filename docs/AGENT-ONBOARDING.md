# Atelierr Agent Onboarding

任何编码代理（Kimi Code / Claude Code / Codex / Cursor 等）接手 Atelierr
开发前必读。本文件是唯一的跨代理入口。

> 2026-09-19 评审修订：同步到架构 v1.5 现实（三层结构、basic-memory
> 底座、Python 3.12、MinerU、MVP 全部完成）。

## 仓库里有两个系统

| 系统 | 位置 | 你的关系 |
|---|---|---|
| **Atelierr 记忆管理系统**（生产运行中） | `scripts/{memory,cognition,dispatch,web,processors,cli,utils}/` | ✅ 你的工作范围 |
| Atelier 反思框架（存量，正常运行中） | `scripts/atelier/`、`.claude/`、`.codex/`、`.agents/`、`harness/`、`protocols/`、`frameworks/`、`sources/`、`tests/` 根层的 `test_*.py`、`scripts/*.sh` | ❌ 禁止改动 |

同样禁改：`CLAUDE.md`、`AGENTS.md`、`pyproject.toml`、`uv.lock`、`.venv`
（框架专用环境，只许只读运行 `harness_smoke.py`）。

## 契约（唯一事实源，冲突时以此为准）

1. **架构**：`docs/prd/ARCHITECTURE-LOCKED-V1.md`（**v1.5**）
2. **认知模块**：`docs/prd/COGNITION-SPEC.md`（**v1.0**）
3. **验收**：`docs/ACCEPTANCE-CRITERIA.md`（**v1.1**，测试规格逐条对应实现）
4. **计划**：`DEVELOPMENT-PLAN-3MVP.md`、`docs/prd/IMPLEMENTATION-PLAN-PARALLEL.md`

`docs/prd/archive/` 是历史存档，**不要引用**（旧模型清单见其 README）。

## 设计不变量（违反即返工）

- 笔记是 Markdown 文件，机器**绝不移动、绝不改写**已创建的笔记；归一化
  补 frontmatter 时用 `os.utime` 还原 mtime。授权例外仅限：用户点按钮
  后的删单标签/归档移动/日记行追加（均有用户裁决记录）。
- **三层知识结构**（2026-09-18 裁决）：原料层 `memory/<类目>/`（原文，
  机器不改写）｜压缩层 `memory/distilled/`（机器浓缩品，人批准进门，有
  保鲜期）｜知识层 `memory/wiki/`（人认证，只增不改）。**嵌套子目录是
  合法现状**（早期"平面无子目录"不变量已随 v1.3→v1.5 修订废止）。
- 机器产出卡的唯一落点是 `$OV/inbox/` 中转站；源文件在 `$OV/attachments/`；
  车间规划区在 `$OV/gtd/`（与 memory/ 平级）。
- confidence/layer/last_accessed/references 等动态状态只存 sidecar 索引
  （`<state_dir>/index.json`）；**所有索引写入必须走 flock 事务**
  （`_index_transaction`），禁止缓存回写。
- confidence 是无状态纯函数：`0.95 ** (idle_days × source_factor / ref_factor)`；
  v1.4 起 link/media 来源 ×3 加速衰减；禁止增量累乘。
- 任何路径都不自动删除笔记：`pending_delete` 标记 → `review` → `purge` → `trash/`。
- **记忆底座是 basic-memory**（2026-09-19 方案三）：检索经
  `scripts/memory/bm_bridge.py` 委托（CLI 子进程，防 anyio 线程泄漏；
  语义故障显形——后端宕机报"暂时不可用"，不误报"没有找到"）；
  衰减/复习/回收站继续在文件+sidecar 上自研运行。

## 环境

```bash
python3.12 -m venv .venv-atelierr-312   # 生产 venv（勿用 .venv-atelierr/.venv）
source .venv-atelierr-312/bin/activate
pip install -r requirements.txt         # 含 mineru、basic-memory、whisper 等
```

- OCR：**MinerU 4.0**（常驻 `atelierr-mineru.service`；PaddleOCR/rapidocr 已退役）。
- 转写：Whisper large-v3（GPU 优先）。LLM：DeepSeek（key 在
  `~/.config/atelierr/env`，600 权限，见同目录 README.md）。
- basic-memory：项目 `atelierr` → `~/atelierr-data/memory`，索引在
  `~/.basic-memory/`（库外）；每日 03:20 `atelierr-bmindex.timer` 重建。

## 测试与验证

```bash
.venv-atelierr-312/bin/python -m pytest -q        # 全量（当前 937，覆盖率 ≥80%）
.venv-atelierr-312/bin/python tools/acceptance_test.py   # 端到端验收（当前 8/8）
.venv/bin/python scripts/atelier/harness_smoke.py        # 框架烟测（只读跑，exit 0）
```

覆盖率只统计 Atelierr 包（pytest.ini 已配置）。不要运行 `tests/` 根层的
框架测试，也不要动 `scripts/atelier/` 下的工具。

## 现状（MVP 已全部完成，勿重复建设）

1. **MVP1 记忆模块**：core/confidence/decay/search/watcher/scheduler + CLI ✅
2. **输入处理**：链接（抖音/小红书/B站）、附件（图片 OCR/音视频/PDF/书籍）✅
3. **分发与回路**：15 分钟 links/light 班次、晨报、待确认提醒、每日四问、
   周回顾（含盲测）、月度脉冲（含费曼讲稿）、判断登记+复盘闭环 ✅
4. **中枢**：飞书长连接桥（确认卡/表单/回调）；Flatnotes 已退役；微信在
   backlog，不做。

## 提交规范

- 消息格式：`atelierr: <小写摘要>`（参考 `git log --oneline`）
- 只提交 Atelierr 范围内的文件；提交前跑三件套（pytest + 验收 + smoke）
- 不 push、不改共享基础设施，除非用户明确要求
