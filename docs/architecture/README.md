# Atelierr 当前架构（2026-09-10 落盘记录）

> 唯一维护的架构图：`atelierr-plan.architecture.json`（archify IR，同目录）。
> 信息流图（dataflow IR，同目录）按粒度四层：
> - 总览：`atelierr-plan.dataflow.json` → `atelierr-flow.html`
> - 细化①捕获→加工→入库：`atelierr-flow-pipeline.dataflow.json`
> - 细化②回响·沉淀·删除·会话：`atelierr-flow-loop.dataflow.json`
> - 细化③飞书中枢（双向通道全颗粒）：`atelierr-flow-feishu.dataflow.json`
> - 细化④摄入模块（拆两张，单页全颗粒过密已废弃）：
>   入口篇（九条来源→落地→分发接手）`atelierr-ingest-sources.dataflow.json`
>   → `atelierr-ingest-sources.html`；
>   加工篇（分发→引擎→入库→下游接口，含直发视频裁决 B）
>   `atelierr-ingest-pipeline.dataflow.json` → `atelierr-ingest-pipeline.html`
> 渲染产物（可点开看的 HTML/PNG）在 `~/atelierr-data/exports/`。
> 纪律（2026-09-02 用户裁决）：架构图只维护这一份计划版，不再出现状图；
> 架构有变化就更新这份 IR 并重渲染。

## 重渲染方法

```bash
# archify 本体在 ~/.codex/skills/archify（只读执行，勿改）：
ARCH=~/.codex/skills/archify
node $ARCH/renderers/architecture/render-architecture.mjs \
  docs/architecture/atelierr-plan.architecture.json /tmp/atelierr-plan.html
node $ARCH/renderers/dataflow/render-dataflow.mjs \
  docs/architecture/atelierr-plan.dataflow.json /tmp/atelierr-flow.html
node $ARCH/renderers/dataflow/render-dataflow.mjs \
  docs/architecture/atelierr-flow-pipeline.dataflow.json /tmp/atelierr-flow-pipeline.html
node $ARCH/renderers/dataflow/render-dataflow.mjs \
  docs/architecture/atelierr-flow-loop.dataflow.json /tmp/atelierr-flow-loop.html
node $ARCH/renderers/dataflow/render-dataflow.mjs \
  docs/architecture/atelierr-flow-feishu.dataflow.json /tmp/atelierr-flow-feishu.html
node $ARCH/renderers/dataflow/render-dataflow.mjs \
  docs/architecture/atelierr-ingest-sources.dataflow.json /tmp/atelierr-ingest-sources.html
node $ARCH/renderers/dataflow/render-dataflow.mjs \
  docs/architecture/atelierr-ingest-pipeline.dataflow.json /tmp/atelierr-ingest-pipeline.html
# 注入流线动画（archify 无动画能力，渲染后加 CSS）：
.venv-atelierr/bin/python tools/archify_animate.py \
  /tmp/atelierr-plan.html /tmp/atelierr-flow.html \
  /tmp/atelierr-flow-pipeline.html /tmp/atelierr-flow-loop.html \
  /tmp/atelierr-flow-feishu.html \
  /tmp/atelierr-ingest-sources.html /tmp/atelierr-ingest-pipeline.html
node $ARCH/scripts/check-render-output.mjs /tmp/atelierr-plan.html  # 全 ok:true
node $ARCH/scripts/check-render-output.mjs /tmp/atelierr-flow.html
node $ARCH/scripts/check-render-output.mjs /tmp/atelierr-flow-feishu.html
node $ARCH/scripts/check-render-output.mjs /tmp/atelierr-ingest-sources.html
node $ARCH/scripts/check-render-output.mjs /tmp/atelierr-ingest-pipeline.html
cp /tmp/atelierr-plan.html /tmp/atelierr-flow.html \
   /tmp/atelierr-flow-pipeline.html /tmp/atelierr-flow-loop.html \
   /tmp/atelierr-flow-feishu.html \
   /tmp/atelierr-ingest-sources.html /tmp/atelierr-ingest-pipeline.html \
   ~/atelierr-data/exports/
```

## 架构速记（与图一致）

**双平面**：Atelier 框架（会话工作台，人在场驱动，20 命令贯穿各层）×
Atelierr 应用（后台管线，定时器无人值守）。两平面代码零互调，交接只走
`$OV` 数据面；只读桥当前仅 `/weekly` 启用。

**后台管线**（横向）：捕获入口（速记/链接[抖音·小红书·B站]/截图/录音/PDF/网页剪藏；
原资料按平台分目录存 attachments/媒体/·书籍/·抖音/·小红书/·B站/，视频只存
480p——片源已 ≤480p 则存原件，电脑截图只认 ~/图片/进系统/ 专用夹复制进入，
09-10 捕获 v2.1）→ dispatch 分发
（15 分钟轮询，links→media→todos→highlights；links 同班次处理网页剪藏：
新剪藏复用链接 LLM 摘要管道推飞书确认卡——摘要只进卡片不落笔记，
同 url 重复剪藏由机器在 sidecar 标 pending_delete 待人工 purge，09-10）→ processors 引擎
（OCR/Whisper/LLM 摘要/LLM 划重点代读）→ memory/ 工作记忆（平面 .md
缓冲区，会遗忘）→ wiki/ 知识总库。memory/ 根=收件箱；确认后归子目录
（平台/ · 书籍/分类/ · 日记/想法/目标/）：你手动拖或点飞书 📁 按钮，
机器只在你触发时移动且衰减状态跟随；搜索/衰减递归覆盖子目录
（wiki/attachments/trash/templates 排除）。PDF 走划重点通道：机器代读出可勾选
候选清单，人工勾中直接转 wiki 摘录卡（type: Excerpt，from 指回清单+页码；
Cognitive OS §7.9 机制 09-03 落地，09-06 方案③改为勾选即沉淀，不再经
memory 待确认中转——摘录卡是文献笔记，周日提炼时改写为 concept 卡并互链）。
捕获统计：晨报推送带昨日简数、摘要昨日节附入口分布、周日摘要加本周
详细节（确认率/wiki 沉淀数），`dispatch_cli stats` 可随时查（09-10）。

**回响回路**：decay（03:00 分层，只写 sidecar）+ 检索式晨报（07:53，
复习 + 提炼候选，冷却 3 天）+ 周回顾四问飞书作答回填（09-08，prompt
会话，09-09 首次全环闭环）+ 响应观测（实验 0 在跑）+ 文档健康月检
（每月 2 日 04:17，异常才提醒）。机器产物（摘要/清单/控制台）隔离进
`memory/系统/`（09-08）：渲染可见但不进 decay、不进反链统计。
每日 03:00 对整个数据目录做 git 快照
（版本历史；排除 state/sessions/exports，`.git` 不同步手机）。

**沉淀层（同库分间，COGNITION-SPEC v1.1）**：`memory/wiki/` 一个总库——
根层 concept（人写，只增不改）+ 摘录卡 Excerpt（划重点勾中，机器创建）、
`cognition/` 间（判断登记处，审批写）、`reflections/` 间（周报与决策日志，
只新建）。无 decay 无 purge。

**legacy 卡库已并入 wiki 根层（方案 C，09-06）**：Cognitive OS 资产
542 张卡（208 概念 + 280 术语 + 39 章笔记 + 11 认知条目随迁未激活 +
4 Source 记录）平铺在 `memory/wiki/` 根层，与手工提炼条目同库；
管理档案收 `wiki/_cognitive-os/`（含撞名改名规则：2 张术语卡带
「（术语）」后缀）。WikiManager 三 schema 校验：手工条目要
from+互链；摘录卡（type: Excerpt）要 type/title/from、豁免互链；
Cognitive OS 卡（type+title）豁免 from/互链。② wiki 格式升级随
「信息加工三步法」建议 3 调用；③ 认知条目激活随回路三解冻再议。

**入口**：控制台.md 是总入口（Obsidian 内 Dataview 全 vault 渲染 +
车间口令 + 桌面 ▶ 快捷按钮经 Shell Commands/Advanced URI 拉起 Codex 会话）。
手机端口令卡（Codex 只跑桌面）。Flatnotes 降为兜底入口。**飞书中枢**
（09-10 实测全通，ntfy 已停用）：长连接收消息进库（文字→笔记、语音/图/
文件→attachments/、菜单指令拉取摘要/待办/搜索/看板）；卡片回推（待确认/
待办/晨报置顶/复习/清理提醒），按钮回调三人工例外（删「待确认」/删「待办」/
归档移动单篇）；问答会话（表单卡 schema 2.0 一次收齐或文字按条计）；
**单向同步三件套**（Obsidian→飞书，不回写）：待办→飞书任务（点✅回写完成）、
截止/清理日→「Atelierr」日历、全库元数据→多维表格看板（09-10 新增，
后台已配 task/calendar/bitable/drive 权限）。

**冻结/待办**：wechat 处理器等真实导出样本；回路三（决策校准）等预测；
Codex 侧 paths.toml 三 tier 已对齐（`memory/wiki`、`memory/wiki/cognition`、
`memory/wiki/reflections`，09-03 完成）。
