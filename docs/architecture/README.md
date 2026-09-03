# Atelierr 当前架构（2026-09-02 落盘记录）

> 唯一维护的架构图：`atelierr-plan.architecture.json`（archify IR，同目录）。
> 渲染产物（可点开看的 HTML/PNG）在 `~/atelierr-data/exports/atelierr-plan.*`。
> 纪律（2026-09-02 用户裁决）：架构图只维护这一份计划版，不再出现状图；
> 架构有变化就更新这份 IR 并重渲染。

## 重渲染方法

```bash
# archify 本体在 /tmp/archify（重启会丢；丢了重新 clone）：
#   git clone --depth 1 https://github.com/tt-a1i/archify /tmp/archify
cd /tmp/archify/archify
node bin/archify.mjs validate architecture \
  /srv/workspaces/Atelierr/docs/architecture/atelierr-plan.architecture.json \
  --quality showcase --json        # 需 ok:true 且 0 issues
node bin/archify.mjs deliver architecture \
  /srv/workspaces/Atelierr/docs/architecture/atelierr-plan.architecture.json \
  /tmp/archify-work/atelierr-plan.html --quality showcase
node bin/archify.mjs visual-check /tmp/archify-work/atelierr-plan.html --json  # 0 errors
cp /tmp/archify-work/atelierr-plan.html ~/atelierr-data/exports/
```

## 架构速记（与图一致）

**双平面**：Atelier 框架（会话工作台，人在场驱动，20 命令贯穿各层）×
Atelierr 应用（后台管线，定时器无人值守）。两平面代码零互调，交接只走
`$OV` 数据面；只读桥当前仅 `/weekly` 启用。

**后台管线**（横向）：捕获入口（速记/链接/截图/录音/PDF）→ dispatch 分发
（15 分钟轮询，links→media→todos→highlights）→ processors 引擎
（OCR/Whisper/LLM 摘要/LLM 划重点代读）→ memory/ 工作记忆（平面 .md
缓冲区，会遗忘）→ wiki/ 知识总库。PDF 走划重点通道：机器代读出可勾选
候选清单，人工勾中才转正式笔记（Cognitive OS §7.9 机制，09-03 落地）。

**回响回路**：decay（03:00 分层，只写 sidecar）+ 检索式晨报（07:53，
复习 + 提炼候选，冷却 3 天）+ 响应观测（实验 0 在跑）+ 文档健康月检
（每月 2 日 04:17，异常才提醒）。每日 03:00 对整个数据目录做 git 快照
（版本历史；排除 state/sessions/exports，`.git` 不同步手机）。

**沉淀层（同库分间，COGNITION-SPEC v1.1）**：`memory/wiki/` 一个总库——
根层 concept（人写，只增不改）、`cognition/` 间（判断登记处，审批写）、
`reflections/` 间（周报与决策日志，只新建）。无 decay 无 purge。

**legacy 卡库区（方案 A · ① 已接入 09-03）**：`legacy/` 为 Cognitive OS
知识库的只读副本（549 文件：208 概念卡 + 280 术语卡 + 39 章笔记 + 11 认知
条目），vault 内可搜可链；不参与 decay/purge，memory 机制只扫 `memory/`
根层天然隔离；原件存档 `/srv/knowledge-active/` 不动，区规则见
`legacy/README.md`。② wiki 格式升级随「信息加工三步法」建议 3 调用；
③ 认知条目迁移随回路三解冻再议。

**入口**：控制台.md 是总入口（Obsidian 内 Dataview 全 vault 渲染 +
车间口令 + 桌面 ▶ 快捷按钮经 Shell Commands/Advanced URI 拉起 Codex 会话）。
手机端口令卡（Codex 只跑桌面）。Flatnotes 降为兜底入口。

**冻结/待办**：wechat 处理器等真实导出样本；回路三（决策校准）等预测；
Codex 侧 paths.toml 三 tier 对齐（`memory/wiki`、`memory/wiki/cognition`、
`memory/wiki/reflections`）待其会话执行。
