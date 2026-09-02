# wiki 合库方案（同库分间）草案

> 状态：**✅ 已实施完成（2026-09-02）**。pytest 316 全绿、验收 8/8、
> smoke exit 0；COGNITION-SPEC 升 v1.1；迁移为纯移动零改写。
> 前置阅读：`reflections/2026-09-02-decision-exit-convergence.md`（被本方案修订，
> 实施时另写决策修订日志，原日志不改写）。

## 目标形态

```
wiki/                     ← 唯一知识总库（vault 内 memory/wiki/）
├── 概念条目.md            ← 根层：常青知识（concept）
├── cognition/           ← 判断登记处：belief/question/hypothesis
└── reflections/         ← 周报、决策日志
```

三条机器纪律按房间执行，互不越界：

| 房间 | 谁写 | 机器纪律 |
|---|---|---|
| 根层 concept | 人（QuickAdd 提炼） | 只增不改；WikiManager 只校验 |
| cognition/ | CLI + 人工批准 | 审批后写/改；永不删 |
| reflections/ | 框架会话 | 只新建，不改写 |

工具按路径认房间，不解析 type 字段；WikiManager 只扫根层（非递归，现状即如此），
CognitionManager 只认 cognition/ 子目录。

## 为什么是同库分间而不是平铺

- 体裁不混：周报/日志数量会十倍于概念，平铺会淹没常青知识；
- 纪律零成本：按目录认规则，不拆 frontmatter；现有两篇 reflections 纯移动、
  零改写（连一次性例外都不需要）；
- 查询按房间：Dataview `FROM "memory/wiki/reflections"` 即可；
- 可逆：房间是纯的，将来想拆整体搬走即可。

## 变更清单（实施顺序）

1. COGNITION-SPEC 升 v1.1：存储位置 `$OV/cognition/` → `$OV/memory/wiki/cognition/`，
   加分间说明；架构文档同步勘误（技术栈/布局处）
2. `scripts/cognition/manager.py`：只改路径解析（from_config 由 memory.yaml 的
   root + wiki_dirname 拼出 cognition 目录）；逻辑零改动
3. 迁移：两篇 reflections 文件移入 `wiki/reflections/`（纯移动）；删除空的
   `cognition/`、`reflections/` 旧目录
4. 控制台 `memory/控制台.md`：判断登记处改 `FROM "memory/wiki/cognition"`；
   最新反思改 `FROM "memory/wiki/reflections"`；孤儿条目改
   `FROM "memory/wiki" AND -"memory/wiki/cognition" AND -"memory/wiki/reflections"`
5. 主页 `memory/主页.md`：房间规则段重写（三目录 → 一库两间）
6. 测试：test_cognition 路径改为传入合库目录；test_wiki 补"子目录条目不进
   validate/孤儿统计"用例；10k 容量测试在合库目录重跑；验收脚本对齐
7. 门禁三件套（pytest 全绿 + acceptance 8/8 + harness_smoke exit 0）+ 规范提交
8. Codex 提示词（另发）：paths.toml 三 tier 对齐 `memory/wiki`、
   `memory/wiki/cognition`、`memory/wiki/reflections`，并说明按路径分房间
9. 架构图（计划版）更新：沉淀层合成一个 wiki/ 总库组件
10. 决策修订日志一篇（reflections/，记用户知情缺点后仍选简洁 + 同库分间修正）

## 防出事闸口

- CognitionManager 只写自己命名的 `<slug>--<short-id>.md`，人写条目永远只读；
- 晨报 wiki 体检只管根层 concept 条目，子目录不进校验，不刷屏；
- sync-conflict：cognition 获批改写会同步手机，小概率冲突接受（原子写兜底）。

## 回退方案

迁移是纯移动 + 路径配置：把文件搬回、配置改回、规格读回旧版即恢复原状；
无任何文件内容改写，回退零数据风险。

## 验收

- pytest 全绿、acceptance 8/8、harness_smoke exit 0；
- 控制台三栏目渲染正确；晨报 wiki 体检对子目录零误报；
- `cognition_cli list/validate` 在合库目录下正常。
