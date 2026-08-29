# Atelierr 快速开始指南

10 分钟快速体验 Atelierr 记忆管理系统。

---

## 📋 前置要求

```yaml
操作系统: Linux/macOS（推荐），Windows（WSL2）
Python: 3.9+
Docker: 20.10+（用于 Web 界面）
磁盘空间: 2GB+
内存: 4GB+
```

---

## 🚀 安装步骤

### Step 1: 克隆仓库（1 分钟）

```bash
git clone https://github.com/your-username/Atelierr.git
cd Atelierr
```

### Step 2: 设置 Python 环境（2 分钟）

```bash
# 创建虚拟环境
python3 -m venv .venv-atelierr  # 独立环境，勿用 .venv（Atelier 框架专用）

# 激活虚拟环境
source .venv-atelierr/bin/activate  # Linux/macOS
# 或
.venv-atelierr\Scripts\activate     # Windows

# 安装依赖
pip install -r requirements.txt
```

### Step 3: 配置路径（1 分钟）

```bash
# 编辑配置文件
cp config/memory.yaml.example config/memory.yaml

# 修改 root_path 为你的笔记目录
# 例如: /home/username/Documents/memory
nano config/memory.yaml
```

### Step 4: 初始化目录结构（30 秒）

```bash
# 自动创建必要的目录
python scripts/init_memory.py
```

输出：
```
✅ 创建目录: $OV/memory/            (平面笔记目录)
✅ 创建目录: ~/atelierr-data/state/ (sidecar 索引 / 报告 / trash)
✅ 创建目录: $OV/inbox/
✅ 初始化完成！
```

### Step 5: 启动 Web 界面（1 分钟）

```bash
# 启动 Flatnotes
docker-compose up -d

# 检查状态
docker-compose ps
```

访问: http://localhost:8080

---

## 🎯 第一次使用

### 创建第一个笔记（2 分钟）

#### 方法 1: 通过 Web 界面（推荐）

1. 打开 http://localhost:8080
2. 点击 "New Note"
3. 输入标题和内容
4. 保存

#### 方法 2: 直接创建文件

```bash
cat > $OV/memory/first-note.md << 'MARKDOWN'
---
title: 我的第一个笔记
created: 2026-08-27T18:00:00+08:00
source: manual
tags: ["测试"]
---

# 我的第一个笔记

这是一个测试笔记，用于验证系统工作正常。

## 核心特性

- 自动衰减
- 智能搜索
- 多模态输入

## 待办事项

- [ ] 熟悉 Web 界面
- [ ] 尝试处理图片
- [ ] 了解 confidence 机制
MARKDOWN
```

### 查看 Confidence（1 分钟）

```bash
# 查看笔记的 confidence
python -m scripts.cli.memory_cli show first-note.md

# 输出:
# 📄 first-note.md
# 🎯 Confidence: 1.0
# 📁 Tier: short-term
# 🏷️  Tags: 测试
# 📅 Created: 2026-08-27
# 👁️  Access count: 1
```

### 测试搜索（1 分钟）

```bash
# 搜索包含 "特性" 的笔记
python -m scripts.cli.memory_cli search "特性"

# 输出:
# 找到 1 个结果:
# 
# 📄 first-note.md (confidence: 1.0)
#    ... 自动衰减
#    - 智能搜索
#    - 多模态输入 ...
```

---

## 🎨 尝试多模态输入（2 分钟）

### 处理图片（30 秒）

```bash
# 准备一张图片（例如代码截图）
# 然后运行:
python scripts/input_processor.py \
  --type image \
  --input /path/to/screenshot.jpg

# 输出:
# 🔍 检测到图片...
# 📝 正在进行 OCR 识别...
# ✅ 识别完成！提取了 120 个字符
# 💾 已保存到: $OV/memory/2026-08-27-screenshot.md
```

生成的笔记：
```markdown
---
title: 截图内容 - 2026-08-27
source: ocr
confidence: 0.5
---

# 截图内容

![原始图片](attachments/screenshot.jpg)

## 识别的文字

def calculate_confidence(note_path: str) -> float:
    """计算笔记的 confidence 值"""
    ...
```

---

## ✅ 验证安装

运行完整的验证脚本：

```bash
python scripts/verify_installation.py
```

预期输出：
```
🔍 检查 Python 版本... ✅ Python 3.10.0
🔍 检查依赖包... ✅ 所有依赖已安装
🔍 检查配置文件... ✅ config/memory.yaml 存在
🔍 检查目录结构... ✅ 所有目录存在
🔍 检查 Docker... ✅ Docker 运行中
🔍 检查 Flatnotes... ✅ http://localhost:8080 可访问
🔍 测试 MemoryTree... ✅ 核心功能正常
🔍 测试搜索... ✅ 搜索功能正常

🎉 安装验证通过！一切准备就绪！
```

---

## 🎉 下一步

### 1. 了解核心概念（10 分钟）

阅读: [核心概念](./docs/user/getting-started.md#核心概念)

### 2. 尝试更多功能（30 分钟）

```bash
# 启动自动衰减守护进程
python scripts/memory_scheduler.py --daemon

# 启动文件夹监控（自动处理放入 inbox 的文件）
python scripts/input_watcher.py --daemon
```

### 3. 处理真实内容

```bash
# 处理视频
python scripts/input_processor.py \
  --type video \
  --input lecture.mp4

# 处理 PDF
python scripts/input_processor.py \
  --type pdf \
  --input paper.pdf
```

### 4. 探索高级功能

- [批量处理](./docs/user/user-guide.md#批量处理)
- [自定义配置](./docs/user/user-guide.md#配置)
- [最佳实践](./docs/user/user-guide.md#最佳实践)

---

## 🐛 遇到问题？

### 常见问题

**Q: 无法访问 http://localhost:8080**

```bash
# 检查 Docker 状态
docker-compose ps

# 查看日志
docker-compose logs flatnotes

# 重启
docker-compose restart
```

**Q: Python 依赖安装失败**

```bash
# 确保 pip 是最新的
pip install --upgrade pip

# 使用国内镜像（可选）
pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
```

**Q: 找不到配置文件**

```bash
# 从示例复制
cp config/memory.yaml.example config/memory.yaml

# 或使用向导创建
python scripts/setup_wizard.py
```

### 获取帮助

- [完整 FAQ](./docs/user/faq.md)
- [故障排查](./docs/dev/troubleshooting.md)
- [提交 Issue](https://github.com/your-username/Atelierr/issues)

---

## 📚 完整文档

- [用户指南](./docs/user/user-guide.md) - 详细使用说明
- [开发文档](./docs/dev/README.md) - 开发者文档
- [API 参考](./docs/dev/api-reference.md) - API 文档

---

**🎨 开始你的智能记忆管理之旅吧！**
