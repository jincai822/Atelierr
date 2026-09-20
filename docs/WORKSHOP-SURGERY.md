# 车间瘦身手术清单（WORKSHOP-SURGERY）

> 2026-09-20 定稿。执行场所：**Codex 会话**（harness 自留地；Kimi 侧禁改区不动）。
> 执行方式建议：在仓库根目录开 Codex，说「读 docs/WORKSHOP-SURGERY.md，按清单执行」。

## 0. 目标与三条铁规

**目标**：把旧知识世界的引擎正式熄火，车间注册表瘦到"活着的编制"，与 Atelierr 应用层的分层契约（管道=海马体 / 车间=元认知层）对齐。

**铁规（全程不得违反）**：

1. 🔴 **衰减/遗忘唯一归 `scripts/memory/decay.py`**（无状态纯函数契约）。forgetter、decay_scan、autoevo-nightly 全部熄火，任何路径不得再对 `memory/`、`wiki/` 做衰减扫描。
2. **只归档不删除**：退役的命令说明书移入 `legacy/commands/`，注册表条目删除，但文件永留。回滚 = `git checkout`。
3. **术前先快照**：`git status` 干净或另行提交后开工；术后必须过验证三件套（见第 6 节）。

**术前已核实的安全事实（2026-09-20 Kimi 侧审计）**：paths.toml 登记的 33 个 tier 中，旧世界目录在 vault 里**只有 `sessions/` 存在且为空（0 文件）**，其余全部不存在。摘除注册条目零数据风险。

## 1. 刀一：`harness/commands.toml`（21 条 → 8 条）

**保留 8 条（活着的编制）**：

| 条目 | 理由 |
|---|---|
| `hi` | 门房路由，唯一入口 |
| `reflect`（alias of hi） | 别名，随 hi 保留 |
| `weekly` | 周回顾深度版（周日自动跑初稿的载体） |
| `decision` | 上层四件套 |
| `explore` | 上层四件套 |
| `promote` | 上层四件套 |
| `lint` | 车间自检 |
| `system-review` | harness 自维护（ops） |

**退役 10 条（删除注册表块）**：`daily-reflection`、`review`、`read`、`energy-audit`、`prm`、`introspect`、`curate`、`sync`、`civ`、`dine`

理由：前两个与应用层定时仪式重复（应用问、车间写已定稿）；read/energy-audit/prm/introspect/civ/dine 为休眠生活技能（归档可召回）；curate/sync 与应用层捕获归一化重复。

**冻结 3 条（删除注册表块 + 第 4 节冻结声明）**：`autoevo-nightly` 🔴（旧衰减引擎的夜间载体，最高优先）、`autoevo-review`、`run-routine`

## 2. 刀二：`harness/intents.toml`（18 条 → 7 条）

**保留 7 条**：`weekly`、`decision`、`explore`、`promote`、`lint`、`reflection`、`general`

**退役 11 条**：`capture`、`reading`、`finance-analysis`、`meeting`、`talk`、`sync`、`forget` 🔴（遗忘意图，旧衰减引擎的用户侧扳机，最高优先）、`energy-audit`、`review`、`curate`、`introspect`

注意：退役意图引用的 `protocols/intent-capture.md`、`protocols/intent-forget.md`、`protocols/intent-meeting.md`、`protocols/analysis-signals.md` 一并移入 `legacy/protocols/`。

## 3. 刀三：`harness/paths.toml`（33 条 → 11 条）

**保留 11 条**：`wiki`、`reflections`、`memory`、`cognition`、`inbox`、`cache`、`sessions`、`archive`、`meta`、`routine_prompts`、`private_features`

**摘除 22 条**：`papers`、`preprints`、`daily_notes`、`research`、`agent_findings`、`wip`、`gtd`（待办合一走应用 inbox todo；反悔可在 `paths.local.toml` 加回）、`travel`、`health`、`work`、`career`、`people`、`talent`、`finance`、`personal`、`housing`、`auto`、`abroad`、`secure`、`dev`、`projects`、`zettelm`（/sync 退役后无消费者）

**已知副作用（属预期熄火行为）**：`scripts/atelier/` 中引用被摘 tier 的休眠脚本（todos.py、recurring.py、cues.py、staleness.py、zk_audit.py、decay_scan.py 等）若被调用会以 "unknown tier" 报错退出——这正是冻结信号，**不要去修这些脚本**。若某报错来自仍在使用的路径，说明该 tier 误摘，回滚该条。

## 4. 刀四：说明书归档 + 冻结声明

1. 退役/冻结命令的说明书移入 `legacy/commands/`：
   `daily-reflection.md`、`review.md`、`read.md`、`energy-audit.md`、`prm.md`、`introspect.md`、`curate.md`、`sync.md`、`civ.md`、`dine.md`、`autoevo-nightly.md`、`autoevo-review.md`、`run-routine.md`
2. 新建 `legacy/README.md`，内容要点：
   - 本目录是 2026-09-20 车间瘦身的归档，非删除，可召回。
   - **冻结声明**：memory/ 与 wiki/ 的衰减与遗忘唯一归 `scripts/memory/decay.py`（无状态纯函数 `0.95^(idle/ref)`）。forgetter、decay_scan、autoevo-nightly 自今日起熄火；重新启用需用户本人明示批准。
3. `harness/agents.toml`、`harness/capabilities.toml` 若引用已退役命令，同步摘除对应行（执行时 grep 验证：`rg -n 'daily-reflection|curate|dine|autoevo' harness/*.toml`）。

## 5. 重新渲染运行时边缘

注册表改完后必须重渲染（`.codex/agents/` 与 `.agents/skills/` 是生成物）：

```bash
uv run scripts/atelier/render_runtime_edges.py --runtime codex --apply
```

预期：退役命令对应的 `.agents/skills/<name>/` 目录消失；`hi/weekly/decision/explore/promote/lint/system-review/reflect` 保留。

## 6. 术后验证三件套（全绿才算完）

```bash
python3 scripts/atelier/harness_lint.py            # 结构一致
.venv/bin/python scripts/atelier/harness_smoke.py  # 冒烟 exit 0
git diff --stat                                    # 变更面审一眼
```

再抽验一次路由：Codex 里发 `$hi`，应只看到保留意图的菜单；发"忘掉旧笔记"类的话，**不得**再触发 forget 扫描。

## 7. 回滚

```bash
git checkout -- harness/ .claude/commands/ .agents/skills/ .codex/agents/
# legacy/ 是新目录，留着无妨
```

## 8. 术后通知

完成后告知 Kimi 会话：核对中台备查卡与 `exports/atelierr-architecture.html`（分层版）是否与瘦身结果一致；第二刀（$weekly 周日自动跑）在瘦身后的 `$weekly` 上实施。
