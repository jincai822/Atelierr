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
- **视频**: 智能提取转录和关键帧（99% 压缩）
- **PDF**: 文本提取和图表保留
- **音频**: 语音转文字
- **微信记录**: 聊天记录结构化保存

### 💾 智能大文件处理

- **极致压缩**: 1GB 视频 → 5MB（保留完整信息）
- **Git 友好**: 仓库保持 <1GB
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
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# 启动 Web 界面
docker-compose up -d

# 启动记忆管理守护进程
python scripts/memory_scheduler.py --daemon
```

### 创建第一个笔记

```bash
# 通过 Web 界面（推荐）
打开 http://localhost:8080

# 或直接创建 Markdown
echo "# 我的第一个笔记" > $OV/memory/short-term/test.md
```

### 处理多模态输入

```bash
# 处理图片
python scripts/input_processor.py --type image --input screenshot.jpg

# 处理视频
python scripts/input_processor.py --type video --input lecture.mp4

# 处理 PDF
python scripts/input_processor.py --type pdf --input paper.pdf
```

---

## 📖 文档

### 快速链接

- [快速开始指南](./QUICK-START.md) - 10分钟上手
- [完整文档](./docs/README.md) - 所有文档导航
- [用户手册](./docs/user/user-guide.md) - 详细使用说明
- [API 参考](./docs/dev/api-reference.md) - 开发者文档

### 架构文档

- [核心架构](./docs/prd/ARCHITECTURE-LOCKED-V1.md) - 系统设计
- [实施计划](./docs/prd/IMPLEMENTATION-PLAN-PARALLEL.md) - 开发路线图
- [架构图解](./docs/prd/) - 可视化架构

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

更多细节: [架构图解](./docs/prd/README-visual.md)

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

### Confidence（置信度）

每个笔记都有一个 0.0-1.0 的 confidence 值，表示其可信度和重要性：

```yaml
---
title: 笔记标题
created: 2026-08-27
confidence: 0.8          # 初始 confidence
last_accessed: 2026-08-27
access_count: 1
source: manual           # 来源类型
tags: ["标签1", "标签2"]
---

笔记内容...
```

### 三层记忆

```
短期记忆 (Short-term):
  - Confidence: 0.0-0.4
  - 位置: $OV/memory/short-term/
  - 衰减: 快速（每天 -5%）
  - 用途: 临时想法、待整理

中期记忆 (Mid-term):
  - Confidence: 0.4-0.7
  - 位置: $OV/memory/mid-term/
  - 衰减: 中等（每天 -2%）
  - 用途: 项目知识、学习笔记

长期记忆 (Long-term):
  - Confidence: 0.7-1.0
  - 位置: $OV/memory/long-term/
  - 衰减: 缓慢（每天 -0.5%）
  - 用途: 核心知识、重要参考
```

### 自动衰减

```
每天自动执行:
  1. 所有笔记 confidence 下降
  2. 访问过的笔记 confidence 提升
  3. 低于阈值的笔记移到下层
  4. 极低 confidence 的笔记归档
```

---

## 📊 性能指标

### 功能指标

```
✅ 支持 5+ 种输入类型
✅ 大文件压缩比 >98%
✅ 自动化程度 >90%
```

### 性能指标

```
✅ 1000 笔记搜索 <100ms
✅ 1GB 视频处理 <15分钟
✅ 200MB PDF 处理 <5分钟
✅ Git 仓库 <1GB
```

---

## 🛣️ 开发路线图

### ✅ Phase 1: 记忆模块核心（Week 1-2）

- [x] MemoryTree 核心类
- [x] Confidence 计算
- [x] 自动衰减机制
- [x] 基础搜索功能

### ⏳ Phase 2: Web 界面集成（Week 3）

- [ ] Flatnotes 部署
- [ ] 文件监控集成
- [ ] 自动化工作流

### ⏳ Phase 3: 输入处理（Week 4）

- [ ] 图片 OCR
- [ ] 视频处理
- [ ] PDF 处理

### ⏳ Phase 4: 大文件和多模态（Week 5-8）

- [ ] 大文件智能提取
- [ ] 微信记录处理
- [ ] 音频转文字
- [ ] 批量处理工具

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

详见: [贡献指南](./docs/dev/contributing.md)

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
