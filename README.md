# Atelierr - AI 驱动的记忆管理系统

**Atelierr** 是一个智能的个人知识管理系统，通过 **Confidence-based 记忆衰减机制**，帮助你自动管理信息的生命周期，让重要的知识保留，低价值的信息自然淡出。

---

## ✨ 核心特性

### 🧠 智能记忆管理

- **三层记忆结构**: 短期（工作记忆）→ 中期（项目知识）→ 长期（核心知识）
- **自动衰减**: 基于时间和访问频率的智能衰减
- **动态迁移**: 笔记根据价值自动在层级间流动

### 🎨 多模态输入

- **图片/截图**: OCR 自动识别文字
- **视频**: 智能提取转录和关键帧
- **PDF**: 文本提取和图表保留
- **音频**: 语音转文字
- **微信记录**: 聊天记录结构化保存（backlog 规划中，未实现）

### 💾 智能大文件处理

- **灵活存储**: 本地归档或云端备份

### 🌐 现代化界面

- **Web 访问**: 基于 Flatnotes 的优雅界面
- **移动友好**: 随时随地访问笔记
- **Markdown 原生**: 纯文本，永不过时

---

## 🚀 快速开始

### 安装

```bash
# 克隆仓库
git clone https://github.com/your-username/Atelierr.git
cd Atelierr

# 安装依赖
python3 -m venv .venv-atelierr  # 独立环境，勿用 .venv（Atelier 框架专用）
source .venv-atelierr/bin/activate
pip install -r requirements.txt

# 启动 Web 界面（compose 文件在 docker/ 下）
cd docker && docker compose up -d

# 每天 03:00 自动衰减（生产部署）见文末"定时衰减（生产部署）"小节
```

### 创建第一个笔记

```bash
# 通过 Web 界面（推荐）
打开 http://localhost:8080

# 或直接创建 Markdown
echo "# 我的第一个笔记" > ~/atelierr-data/memory/test.md
```

### 处理多模态输入

```bash
# 处理图片（OCR）
python -m scripts.cli.process_cli image screenshot.jpg --output screenshot.md

# 处理视频（Whisper 转写）
python -m scripts.cli.process_cli video lecture.mp4 --output lecture.md

# 处理 PDF
python -m scripts.cli.process_cli pdf paper.pdf --output paper.md

# 批量处理
python -m scripts.cli.batch_cli --input-dir ~/Downloads/ --output-dir ~/Notes/
```

### 定时衰减（生产部署）

每天 03:00 自动执行记忆衰减（只写 sidecar 索引与报告，不改笔记文件）。
生产环境推荐用 systemd timer（备选 crontab），安装与运维见
[定时衰减（生产部署）](./docs/DECAY-SCHEDULING.md)。

手动触发一次：

```bash
python -m scripts.cli.memory_cli decay
```

---

## 📖 文档

### 快速链接

- [快速开始指南](./QUICK-START.md) - 10分钟上手
- [文档导航](./docs/README.md) - 所有文档索引
- [验收标准](./docs/ACCEPTANCE-CRITERIA.md) - 功能验收与配置语义
- [测试指南](./docs/TESTING-GUIDE.md) - 测试运行方法

### 架构文档

- [核心架构](./docs/prd/ARCHITECTURE-LOCKED-V1.md) - 系统设计
- [实施计划](./docs/prd/IMPLEMENTATION-PLAN-PARALLEL.md) - 开发路线图
- [PRD 总索引](./docs/prd/README.md) - 设计文档导航

---

## 🏗️ 系统架构

```
┌─────────────────────────────────┐
│  模块 1: Web 界面 (Flatnotes)   │
│  🌐 网页访问，移动友好           │
└────────────┬────────────────────┘
             ↓ (读写文件)
┌─────────────────────────────────┐
│  模块 2: 记忆模块 (Memory)      │
│  🧠 Confidence-based 生命周期    │
│  📊 自动衰减和层级管理           │
└────────────┬────────────────────┘
             ↓ (被调用)
┌─────────────────────────────────┐
│  模块 3: Atelierr Core          │
│  🤖 15+ AI Agents 协作           │
│  📝 反思、阅读、综合              │
└─────────────────────────────────┘
```

更多细节: [PRD 文档](./docs/prd/README.md)

---

## 🎯 使用场景

### 📚 知识工作者

```
• 阅读大量文章和论文
• 需要整理和回顾笔记
• 想自动过滤低价值信息
```

### 🎓 学生和研究者

```
• 处理课程视频和讲座
• 管理学术论文和资料
• 组织学习笔记
```

### 💼 产品经理和创业者

```
• 记录想法和灵感
• 整理用户反馈
• 管理项目文档
```

---

## 💡 核心概念

### Confidence（新鲜度）

每个笔记都有一个 0.0-1.0 的 confidence 值，表示其新鲜度/活跃度
（新笔记 = 1.0，随闲置时间衰减）。confidence、层级等动态状态存于
sidecar 索引，**不写在笔记文件里**；frontmatter 创建时写一次即静态不变：

```yaml
---
id: 01J6ABCDEF             # 稳定 ID
title: 笔记标题
created: 2026-08-27
source: manual             # 来源类型
tags: ["标签1", "标签2"]
---

笔记内容...
```

### 三层记忆（逻辑分层）

所有笔记存放在同一平面目录（默认 `~/atelierr-data/memory/`，即
`memory.root`），层级是 sidecar 索引中的
逻辑属性（文件不会被移动）。Confidence 表示新鲜度，新笔记 = 1.0，
按 `0.95^(闲置天数/引用因子)` 单一曲线衰减：

```
短期记忆 (Short-term):
  - Confidence ≥ 0.7（新鲜、活跃）
  - 约 7 天不活跃后降级
  - 用途: 新想法、进行中的内容

中期记忆 (Mid-term):
  - 0.4 ≤ Confidence < 0.7
  - 用途: 项目知识、学习笔记

长期记忆 (Long-term):
  - Confidence < 0.4（低频归档）
  - < 0.1 时仅标记待删除，经 review→purge 才移入回收站
```

### 自动衰减

```
每天自动执行（只写 sidecar 索引，不改动笔记文件）:
  1. 扫描 [[wikilink]] 反链，更新引用计数
  2. 无状态重算所有笔记的 confidence
  3. 按阈值更新逻辑层级
  4. confidence < 0.1 的笔记标记待删除（review→purge 才移入回收站）
```

---

## 📊 实测性能

### 检索与维护

```
✅ 1000 条笔记搜索 ~12ms（要求 <100ms）
✅ 衰减全量 1000 条 <5s
```

### 输入处理与质量

```
✅ 整页扫描图 OCR（CPU）：PaddleOCR 12-14s（目标 ≤15s）；RapidOCR ~0.8s
   （`processors.image.engine: rapidocr`，扫描件多时推荐）
✅ 121 项测试通过 / 覆盖率 83%
```

---

## 🛣️ 开发路线图

### ✅ Phase 1: 记忆模块核心（Week 1-2）

- [x] MemoryTree 核心类
- [x] Confidence 计算
- [x] 自动衰减机制
- [x] 基础搜索功能

### ✅ Phase 2: Web 界面集成（Week 3）

- [x] Flatnotes 部署
- [x] 文件监控集成
- [x] 自动化工作流

### ✅ Phase 3: 输入处理（Week 4）

- [x] 图片 OCR
- [x] 视频处理
- [x] PDF 处理

### ⏳ Phase 4: 大文件和多模态（Week 5-8）

- [ ] 大文件智能提取
- [ ] 微信记录处理（→ backlog 规划中）
- [x] 音频转文字
- [x] 批量处理工具

### ⏳ Phase 5: 优化和发布（Week 9-10）

- [ ] 性能优化
- [ ] 完整测试
- [ ] 文档完善
- [ ] v1.0 发布

详见: [并行实施计划](./docs/prd/IMPLEMENTATION-PLAN-PARALLEL.md)

---

## 🤝 贡献

我们欢迎所有形式的贡献！

### 如何贡献

```bash
# 1. Fork 项目
# 2. 创建特性分支
git checkout -b feature/amazing-feature

# 3. 提交更改
git commit -m 'Add amazing feature'

# 4. 推送到分支
git push origin feature/amazing-feature

# 5. 提交 Pull Request
```

---

## 📝 许可证

本项目采用 MIT 许可证 - 详见 [LICENSE](./LICENSE) 文件

---

## 🙏 致谢

### 核心技术

- [Flatnotes](https://github.com/dullage/flatnotes) - Web 界面
- [PaddleOCR](https://github.com/PaddlePaddle/PaddleOCR) - OCR 识别
- [Whisper](https://github.com/openai/whisper) - 语音转文字
- [yt-dlp](https://github.com/yt-dlp/yt-dlp) - 视频下载

### 灵感来源

- 记忆宫殿法
- Zettelkasten 笔记系统
- Evergreen Notes 概念

---

## 📧 联系方式

- **Issues**: [GitHub Issues](https://github.com/your-username/Atelierr/issues)
- **讨论**: [GitHub Discussions](https://github.com/your-username/Atelierr/discussions)
- **邮件**: your-email@example.com

---

## ⭐ Star History

如果这个项目对你有帮助，请给我们一个 Star！⭐

---

**🎨 用智能的方式管理你的记忆，让知识自然流动！**
