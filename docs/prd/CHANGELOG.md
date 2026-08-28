# 架构演进日志

本文档记录 Atelierr 架构的重要变更历史。

---

## 2026-08-27: v1.0 架构锁定

### 状态
🔒 **已锁定** - 准备开始实现

### 核心决策

#### 1. 三模块架构
- **模块 1**: Web 交互界面 (Flatnotes)
- **模块 2**: 记忆模块 (Memory-Like-A-Tree, 自实现)
- **模块 3**: Atelierr 核心 (现有系统 + 扩展)

#### 2. 通信方式
- 文件系统为唯一通信通道
- Markdown + YAML frontmatter 格式
- 完全解耦设计

#### 3. 数据结构
```
$OV/
├── memory/
│   ├── long-term/    (confidence > 0.8)
│   ├── mid-term/     (0.5 < confidence ≤ 0.8)
│   └── short-term/   (confidence ≤ 0.5)
└── cognition/
    ├── beliefs/
    ├── questions/
    └── hypotheses/
```

#### 4. 技术栈
- Web 界面: Flatnotes (Docker)
- 记忆模块: Python 3.11+
- Atelierr 核心: 现有技术栈

### 关键文件

```
✅ ARCHITECTURE-LOCKED-V1.md  - 完整架构规范
✅ README-visual.md            - 可视化说明
✅ architecture-diagram.png    - 架构总览图
✅ dataflow-diagram.png        - 数据流程图
✅ file-structure-diagram.png  - 文件结构图
```

### 实现路径

```
Phase 1: 记忆模块核心 (Week 1-2)
Phase 2: 衰减机制 (Week 2)
Phase 3: Web 界面集成 (Week 3)
Phase 4: Agent 集成 (Week 3-4)
Phase 5: 认知模块 (Week 4+)
```

### 下一步

- [ ] 实现 MemoryTree 类
- [ ] 编写单元测试
- [ ] 部署 Flatnotes Docker
- [ ] 创建 Forgetter Agent

---

## 版本历史

### v1.0 (2026-08-27)
- 初始架构设计完成
- 三模块架构确定
- API 规范定义
- 数据格式规范
- 实现路径规划

### 未来版本

待定义

---

## 修订原则

1. **只在以下情况修订**:
   - 实现中发现重大设计缺陷
   - 用户需求明确变更
   - 技术选型证明不可行

2. **不因以下原因修订**:
   - 实现困难但可克服
   - 优化想法（放入未来扩展）
   - 个人偏好变化

3. **修订流程**:
   - 记录问题和理由
   - 提供替代方案对比
   - 更新版本号
   - 更新 CHANGELOG

---

## 联系

如需讨论架构变更，请在修订前明确：
- 问题是什么？
- 为什么现有架构不适用？
- 替代方案是什么？
- 影响范围有多大？
