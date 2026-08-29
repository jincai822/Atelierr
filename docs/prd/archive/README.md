# PRD 历史存档

本目录是 Atelierr 设计过程的**决策存档**（v0.1 PRD、v3/v4/v5 架构草案、
方案对比、图解等），仅供追溯设计演进，**不代表当前设计**。

当前生效的契约：

- 架构：`../ARCHITECTURE-LOCKED-V1.md`（v1.2：平面存储 + sidecar 索引 + 无状态 confidence）
- 验收：`../../ACCEPTANCE-CRITERIA.md`
- 实施：`../IMPLEMENTATION-PLAN-PARALLEL.md`

存档文档中的以下描述均已过时，请勿引用：

- `scripts/memory.py` 单文件（现为 `scripts/memory/` 包）
- 三层物理目录 short-term/mid-term/long-term（现为 sidecar 中的逻辑分层）
- 来源权重/内容权重的重要度模型、`>0.8 进 long-term`、`<0.3 自动删除`
- `add_memory / search_memory / decay_memories` API 命名
- Flatnotes 5000 端口（现为 8080）
- `DOCUMENTATION-STRUCTURE.md`：早期"文档结构愿景"（docs/dev、docs/user、
  docs/design 分层规划），该结构从未按计划落地，已被 `docs/README.md`
  的实际文档索引取代，故随本批次归档于此
