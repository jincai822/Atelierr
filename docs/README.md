# Atelierr 文档

本目录是 Atelierr 记忆管理系统的文档索引。按需查阅，无需按顺序读完。

## 文档索引

- [AGENT-ONBOARDING.md](./AGENT-ONBOARDING.md) — Agent 与开发者维护本仓库的入口指南（Atelierr 应用工作优先读它）
- [ACCEPTANCE-CRITERIA.md](./ACCEPTANCE-CRITERIA.md) — 锁定验收标准（v1.1，含 Phase 5 cognition 测试映射）
- [TESTING-GUIDE.md](./TESTING-GUIDE.md) — 测试体系与覆盖率门禁
- [DECAY-SCHEDULING.md](./DECAY-SCHEDULING.md) — 定时衰减（systemd timer / crontab）生产部署
- [PROJECT-STRUCTURE.md](./PROJECT-STRUCTURE.md) — 项目目录结构与模块职责
- [prd/ARCHITECTURE-LOCKED-V1.md](./prd/ARCHITECTURE-LOCKED-V1.md) — 锁定架构（v1.3：memory 生命周期 + cognition 边界）
- [prd/COGNITION-SPEC.md](./prd/COGNITION-SPEC.md) — Phase 5 认知模块锁定规格（v1.0）
- [prd/IMPLEMENTATION-PLAN-PARALLEL.md](./prd/IMPLEMENTATION-PLAN-PARALLEL.md) — 并行实施计划
- [prd/README.md](./prd/README.md) — PRD 文档导航
- [prd/archive/](./prd/archive/) — 早期设计草案与决策存档（仅供追溯，不代表当前设计）

## 快速入口

- 第一次接触：根目录 [README.md](../README.md)（项目总览）与 [QUICK-START.md](../QUICK-START.md)（10 分钟上手）
- 验收：`python tools/acceptance_test.py --phase all`
