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

> 💡 **无 GPU 机器建议先装 CPU 版 torch**（省 ~2GB 下载量）：
>
> ```bash
> pip install torch --index-url https://download.pytorch.org/whl/cpu
> pip install -r requirements.txt
> ```

依赖是否可解析可以先验证（不实际安装）：

```bash
pip install --dry-run -r requirements.txt
# 输出示例（全部 "Requirement already satisfied" 表示可解析）:
# Requirement already satisfied: pyyaml>=6.0 in ./.venv-atelierr/lib/python3.10/site-packages (from -r requirements.txt (line 3)) (6.0.2)
# Requirement already satisfied: watchdog>=2.1.0 in ./.venv-atelierr/lib/python3.10/site-packages (from -r requirements.txt (line 4)) (6.0.0)
# ...（其余依赖类似，最后退出码 0）
```

### Step 3: 配置路径（1 分钟）

```bash
# 编辑配置文件
cp config/memory.yaml.example config/memory.yaml

# 修改 root 与 state_dir 为你的目录（默认 ~/atelierr-data）
# 例如: /home/username/atelierr-data/memory
nano config/memory.yaml
```

### Step 4: 初始化目录结构（30 秒）

```bash
# 自动创建必要的目录（幂等，可重复执行）
python tools/init_memory.py
```

输出示例（已存在的目录显示"已存在"，新建的显示"创建"）：

```
✅ 已存在目录: /home/cj1024/atelierr-data/memory
✅ 已存在目录: /home/cj1024/atelierr-data/state
✅ 已存在目录: /home/cj1024/atelierr-data/state/reports
✅ 创建目录: /home/cj1024/atelierr-data/state/trash
✅ 创建目录: /home/cj1024/atelierr-data/inbox
✅ 初始化完成！
```

创建内容：
- 平面笔记目录（`memory.root`，Flatnotes 直接挂载）
- 状态目录（`memory.state_dir`，含 `reports/` 衰减报告与 `trash/` 回收站）
- inbox 目录（笔记目录的同级兄弟 `inbox/`，待处理输入入口）

### Step 5: 启动 Web 界面（1 分钟）

```bash
# 启动 Flatnotes（compose 文件在 docker/ 下）
cd docker && docker compose up -d

# 检查状态
docker compose ps
```

真实输出：

```
 Container atelierr-flatnotes Running 
NAME                 IMAGE                      COMMAND            SERVICE     CREATED       STATUS                    PORTS
atelierr-flatnotes   dullage/flatnotes:latest   "/entrypoint.sh"   flatnotes   3 hours ago   Up 32 minutes (healthy)   0.0.0.0:8080->8080/tcp, [::]:8080->8080/tcp
```

访问: http://localhost:8080

---

## 🎯 第一次使用

### 创建第一个笔记（2 分钟）

#### 方法 1: 通过 Web 界面（推荐）

1. 打开 http://localhost:8080
2. 点击 "New Note"
3. 输入标题和内容
4. 保存（文件写入 `~/atelierr-data/memory/`）

#### 方法 2: 直接创建文件

```bash
cat > ~/atelierr-data/memory/first-note.md << 'MARKDOWN'
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

手工/外部工具创建的文件需要归一化登记后，`show`/`decay` 才能处理
（`search` 可直接搜到）。运行一次 sync 即可（与 Web 集成 watcher
的自动登记等价）：

```bash
python -m scripts.cli.memory_cli sync
```

真实输出：

```
归一化: 1
新登记: 0
注销: 0
跳过: 0
```

> 💡 用命令行创建可以一步到位（自动补 frontmatter 并登记）：
> `python -m scripts.cli.memory_cli create "first-note.md" --content "笔记内容" --source manual --tags 测试`

### 查看笔记元数据与 Confidence（1 分钟）

```bash
# 查看笔记的元数据与 live confidence
python -m scripts.cli.memory_cli show first-note.md
```

真实输出：

```
                           first-note.md                            
┏━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓
┃ 字段           ┃ 值                                              ┃
┡━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┩
│ path           │ /home/cj1024/atelierr-data/memory/first-note.md │
│ id             │ 01M16AMMX7ZJ0GSBMVJT7Y8BE7                      │
│ title          │ 我的第一个笔记                                  │
│ created        │ 2026-08-27 18:00:00+08:00                       │
│ source         │ manual                                          │
│ tags           │ ['测试']                                        │
│ layer          │ short-term                                      │
│ confidence     │ 1.0                                             │
│ references     │ 0                                               │
│ last_accessed  │ None                                            │
│ pending_delete │ False                                           │
└────────────────┴─────────────────────────────────────────────────┘
```

### 测试搜索（1 分钟）

```bash
# 搜索包含 "特性" 的笔记
python -m scripts.cli.memory_cli search "特性"
```

真实输出：

```
[short-term] conf=1.000 first-note.md — 我的第一个笔记
```

---

## 🎨 尝试多模态输入（2 分钟）

### 处理图片（30 秒）

```bash
# 准备一张图片（例如代码截图）
# 然后运行（--output 不填时 Markdown 打印到 stdout）:
python -m scripts.cli.process_cli image /path/to/screenshot.jpg --output ~/atelierr-data/memory/2026-08-29-screenshot.md
```

真实输出（首次运行会下载 OCR 模型，之后使用缓存）：

```
已写入: /home/cj1024/atelierr-data/memory/2026-08-29-screenshot.md
```

生成的笔记（Markdown 输出不含 confidence frontmatter；confidence 等动态
状态存于 sidecar，不在笔记文件里。标题与图片链接取输入文件名）：

```markdown
# screenshot

![原始图片](/path/to/screenshot.jpg)

## 识别的文字

（OCR 识别出的文字，例如: Atelierr OCR test 123）
```

---

## ✅ 验证安装

运行完整的验证脚本（检查 Python/依赖/目录/配置/Docker/Flatnotes 可达性/
模块导入/MemoryTree 冒烟）：

```bash
python tools/verify_installation.py
```

真实输出：

```
============================================================
  Atelierr 安装验证
============================================================

🔍 检查 Python 版本...
  ✅ Python 3.10.12
🔍 检查依赖包...
  ✅ pyyaml
  ✅ watchdog
  ✅ pytest
  ✅ frontmatter
  ✅ click
  ✅ rich

  （可选，MVP3 输入处理引擎）:
  ✅ PaddlePaddle
  ✅ PaddleOCR
  ✅ OpenAI Whisper
  ✅ PyMuPDF
🔍 检查目录结构...
  ✅ scripts/memory
  ✅ scripts/web
  ✅ scripts/processors
  ✅ scripts/cli
  ✅ scripts/utils
  ✅ config
  ✅ docker
  ✅ tests
  ✅ examples
  ✅ tools
🔍 检查配置文件...
  ✅ requirements.txt
  ✅ .gitignore
  ✅ pytest.ini
  ✅ docker/docker-compose.yml
🔍 检查 Docker...
  ✅ Docker version 29.7.2, build a7dcaa6
🔍 检查 Flatnotes...
  ✅ http://localhost:8080 可访问 (HTTP 200)
🔍 检查 Atelierr 模块...
  ✅ 记忆模块核心
  ✅ Confidence 计算
  ✅ 自动衰减
  ✅ 搜索功能
  ✅ Web 集成
  ✅ 处理器基类
  ✅ 图片处理器
  ✅ PDF 处理器
  ✅ Memory CLI
  ✅ 配置工具
🔍 测试 MemoryTree...
  ✅ create_note / search / note_info 正常

============================================================
  检查报告
============================================================

检查结果:
  ✅ Python 版本
  ✅ 依赖包
  ✅ 目录结构
  ✅ 配置文件
  ✅ Docker
  ✅ Flatnotes
  ✅ Atelierr 模块
  ✅ MemoryTree

总计: 8 项检查
通过: 8 项
失败: 0 项

✅ 安装验证完全通过！系统准备就绪。
```

---

## 🎉 下一步

### 1. 了解核心概念（10 分钟）

阅读: [核心概念](./README.md#核心概念) 与 [文档导航](./docs/README.md)

### 2. 定时衰减

手动触发一次衰减（只写 sidecar 与报告，不改笔记文件）：

```bash
python -m scripts.cli.memory_cli decay
```

真实输出：

```
总数: 1 | short-term: 1 | mid-term: 0 | long-term: 0
已迁移: 0 条
报告: /home/cj1024/atelierr-data/state/reports/decay-2026-08-29.md
```

生产环境每天 03:00 自动衰减（systemd timer / crontab）：
[定时衰减（生产部署）](./docs/DECAY-SCHEDULING.md)

### 3. 处理真实内容

```bash
# 图片 OCR
python -m scripts.cli.process_cli image screenshot.jpg --output screenshot.md

# PDF 转 Markdown
python -m scripts.cli.process_cli pdf paper.pdf --output paper.md

# 视频转文字（Whisper，--model 可选: tiny/base/small/medium/large）
python -m scripts.cli.process_cli video lecture.mp4 --output lecture.md

# 音频转文字
python -m scripts.cli.process_cli audio note.wav --output note.md

# 批量处理目录（并行，--workers 可调，默认 4）
python -m scripts.cli.batch_cli --input-dir ~/Downloads/ --output-dir ~/Notes/
```

### 4. 探索高级功能

- [验收标准](./docs/ACCEPTANCE-CRITERIA.md) 与 `python tools/acceptance_test.py --phase all`
- [测试指南](./docs/TESTING-GUIDE.md)
- 配置示例: `config/memory.yaml.example`、`config/processors.yaml.example`

---

## 🐛 遇到问题？

### 常见问题

**Q: 无法访问 http://localhost:8080**

```bash
# 在 docker/ 目录下检查 Docker 状态
cd docker
docker compose ps

# 查看日志
docker compose logs flatnotes

# 重启
docker compose restart
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
```

### 获取帮助

- [文档导航](./docs/README.md)
- [测试指南](./docs/TESTING-GUIDE.md)
- [提交 Issue](https://github.com/your-username/Atelierr/issues)

---

## 📚 完整文档

- [文档导航](./docs/README.md) - 所有文档索引
- [验收标准](./docs/ACCEPTANCE-CRITERIA.md) - 功能验收与配置语义
- [测试指南](./docs/TESTING-GUIDE.md) - 测试运行方法
- [定时衰减（生产部署）](./docs/DECAY-SCHEDULING.md) - 每日自动衰减

---

**🎨 开始你的智能记忆管理之旅吧！**
