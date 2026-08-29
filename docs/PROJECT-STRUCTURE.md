# Atelierr 开发目录结构

**版本**: v1.0  
**状态**: 🔒 已锁定  
**日期**: 2026-08-27

---

## 🎯 核心原则

### 并行开发友好

```
✅ 模块独立：不同开发者可以同时工作
✅ 最小依赖：模块间松耦合
✅ 清晰边界：每个目录职责明确
✅ 快速集成：接口标准化
```

### 时间估算修正

```
❌ 之前: 4-6周（太保守）
✅ 实际: 1-2周 MVP 可用

原因:
  - Flatnotes 是现成的（开源）
  - PaddleOCR 是现成的（开源）
  - Whisper 是现成的（开源）
  - 我们只需要写胶水代码！
```

---

## 📁 开发目录结构

```
Atelierr/
├── scripts/                        ← Python 核心代码
│   ├── __init__.py
│   │
│   ├── memory/                     ← 模块 1: 记忆管理（独立开发）
│   │   ├── __init__.py
│   │   ├── core.py                 ← MemoryTree 核心类
│   │   ├── confidence.py           ← Confidence 计算
│   │   ├── decay.py                ← 衰减机制
│   │   ├── search.py               ← 搜索功能
│   │   ├── watcher.py              ← 文件监控
│   │   └── scheduler.py            ← 定时任务
│   │
│   ├── web/                        ← 模块 2: Web 界面（独立开发）
│   │   ├── __init__.py
│   │   ├── integration.py          ← 与记忆模块集成
│   │   └── custom_styles.py        ← 自定义样式（可选）
│   │
│   ├── processors/                 ← 模块 3: 输入处理（独立开发）
│   │   ├── base.py                 ← 基类（先写这个）
│   │   ├── image.py                ← 图片处理（调用 PaddleOCR）
│   │   ├── video.py                ← 视频处理（调用 Whisper）
│   │   ├── pdf.py                  ← PDF 处理（调用 PyMuPDF）
│   │   ├── audio.py                ← 音频处理
│   │   └── wechat.py               ← 微信记录
│   │
│   ├── cli/                        ← CLI 命令（独立开发）
│   │   ├── __init__.py
│   │   ├── memory_cli.py           ← 记忆管理命令
│   │   ├── process_cli.py          ← 输入处理命令
│   │   └── batch_cli.py            ← 批量处理命令
│   │
│   └── utils/                      ← 共享工具（公共代码）
│       ├── __init__.py
│       ├── file_utils.py
│       ├── text_utils.py
│       ├── date_utils.py
│       └── config.py
│
├── config/                         ← 配置文件
│   ├── memory.yaml                 ← 记忆模块配置
│   ├── storage.yaml                ← 存储配置
│   ├── processors.yaml             ← 处理器配置
│   └── logging.yaml                ← 日志配置
│
├── docker/                         ← Docker 配置（独立开发）
│   ├── docker-compose.yml          ← Flatnotes 部署
│   └── .env.example                ← 环境变量示例
│
├── tests/                          ← 测试（随开发同步）
│   ├── unit/                       ← 单元测试
│   │   ├── test_memory/
│   │   ├── test_processors/
│   │   └── test_utils/
│   ├── integration/                ← 集成测试
│   │   ├── test_memory_web.py
│   │   └── test_end_to_end.py
│   └── fixtures/                   ← 测试数据
│       ├── sample.md
│       ├── sample.jpg
│       └── sample.pdf
│
├── examples/                       ← 示例脚本
│   ├── basic_usage.py
│   ├── batch_processing.py
│   └── custom_processor.py
│
└── tools/                          ← 开发工具
    ├── init_memory.py              ← 初始化目录
    ├── verify_installation.py      ← 验证安装
    └── generate_test_data.py       ← 生成测试数据
```

---

## 🚀 并行开发策略

### 三个独立模块

#### 模块 1: 记忆管理（scripts/memory/）

**开发者 A / 你自己（最优先）**

```python
Day 1-2: 核心功能
  scripts/memory/core.py          # MemoryTree 类
  scripts/memory/confidence.py    # Confidence 计算
  
Day 3-4: 衰减和搜索
  scripts/memory/decay.py         # 衰减机制
  scripts/memory/search.py        # 搜索功能

Day 5: 自动化
  scripts/memory/watcher.py       # 文件监控
  scripts/memory/scheduler.py     # 定时任务

依赖: 无（完全独立）
输出: MemoryTree API
```

#### 模块 2: Web 界面（docker/ + scripts/web/）

**开发者 B / AI 助手（并行进行）**

```bash
Day 1: Flatnotes 部署
  docker/docker-compose.yml       # Docker 配置
  docker/.env.example             # 环境变量
  
Day 2-3: 集成
  scripts/web/integration.py      # 与 memory 集成

Day 4: 测试
  测试 Web 界面
  测试自动 confidence

依赖: 需要 memory.core.MemoryTree API（第3天后）
输出: 可用的 Web 界面
```

#### 模块 3: 输入处理（scripts/processors/）

**开发者 C / AI 助手（并行进行）**

```python
Day 1: 框架
  scripts/processors/base.py      # 基类接口
  
Day 2: 图片处理（最简单）
  scripts/processors/image.py     # 调用 PaddleOCR
  
Day 3-4: 视频和 PDF
  scripts/processors/video.py     # 调用 Whisper + ffmpeg
  scripts/processors/pdf.py       # 调用 PyMuPDF

Day 5: 其他
  scripts/processors/audio.py
  scripts/processors/wechat.py

依赖: 需要 memory.core.MemoryTree API（第2天后）
输出: 各种输入处理器
```

---

## ⚡ 时间估算修正

### 为什么只需要 1-2 周？

```
我们不需要从头开发:

✅ Flatnotes (现成的)
   - 完整的 Web 界面
   - Markdown 编辑器
   - 移动端支持
   → 只需配置和部署（2小时）

✅ PaddleOCR (现成的)
   - 中文 OCR 识别
   - 高准确率
   → 只需调用 API（半天）

✅ Whisper (现成的)
   - 语音转文字
   - 多语言支持
   → 只需调用 API（半天）

✅ PyMuPDF (现成的)
   - PDF 文本提取
   - 图片提取
   → 只需调用 API（半天）

我们只需要写:
  1. MemoryTree 类（核心逻辑）- 2-3天
  2. 胶水代码（调用开源工具）- 2-3天
  3. 集成测试 - 1-2天
  
总计: 5-8 天（1-2周）！
```

### 修正后的时间线

```
Week 1 (5-7天):
  Day 1-3: 记忆模块核心 + 基础测试
  Day 4: Flatnotes 部署 + 集成
  Day 5: 图片处理器
  Day 6-7: 视频/PDF 处理器
  
  ✅ MVP 完成！

Week 2 (3-5天, 可选):
  Day 1-2: 微信/音频处理
  Day 3-4: 批量工具
  Day 5: 文档和优化
  
  ✅ 完整版完成！

实际时间: 1-2周，不是 4-6周！
```

---

## 🎯 第一周详细计划

### Day 1: 核心架构（6-8小时）

```python
上午 (3-4小时):
  创建目录结构
  mkdir -p scripts/{memory,web,processors,cli,utils}
  
  编写基础接口:
  scripts/memory/core.py          # MemoryTree 骨架
  scripts/processors/base.py      # Processor 基类
  scripts/utils/config.py         # 配置读取

下午 (3-4小时):
  实现 Confidence 计算:
  scripts/memory/confidence.py    # 核心算法
  
  编写单元测试:
  tests/unit/test_memory/test_confidence.py
```

### Day 2: 记忆模块完善（6-8小时）

```python
上午 (3-4小时):
  实现衰减机制:
  scripts/memory/decay.py
  
  编写测试:
  tests/unit/test_memory/test_decay.py

下午 (3-4小时):
  实现搜索功能:
  scripts/memory/search.py
  
  编写集成测试:
  tests/integration/test_memory_basic.py
```

### Day 3: 记忆模块完成（6-8小时）

```python
上午 (3-4小时):
  实现文件监控:
  scripts/memory/watcher.py
  
  实现定时任务:
  scripts/memory/scheduler.py

下午 (3-4小时):
  完善测试
  编写 CLI:
  scripts/cli/memory_cli.py
  
  ✅ 记忆模块 MVP 完成
```

### Day 4: Web 界面（3-4小时）

```bash
上午 (2小时):
  部署 Flatnotes:
  docker/docker-compose.yml
  docker-compose up -d
  
  测试 Web 访问
  http://localhost:8080

下午 (2小时):
  集成记忆模块:
  scripts/web/integration.py
  
  测试:
  - Web 创建笔记 → 自动 confidence
  - 本地修改 → Web 同步
  
  ✅ Web 界面完成
```

### Day 5: 图片处理（4-6小时）

```python
上午 (2-3小时):
  安装 PaddleOCR:
  pip install paddleocr
  
  实现图片处理:
  scripts/processors/image.py
  # 调用 PaddleOCR API
  # 生成 Markdown

下午 (2-3小时):
  编写 CLI:
  scripts/cli/process_cli.py
  
  测试:
  python -m scripts.cli.process_cli \
    --type image \
    --input screenshot.jpg
  
  ✅ 图片处理完成
```

### Day 6-7: 视频和 PDF（8-12小时）

```python
Day 6 上午 (3-4小时):
  安装依赖:
  pip install openai-whisper ffmpeg-python
  
  实现视频处理:
  scripts/processors/video.py

Day 6 下午 (3-4小时):
  测试视频处理
  优化大文件处理

Day 7 上午 (2-3小时):
  安装依赖:
  pip install PyMuPDF
  
  实现 PDF 处理:
  scripts/processors/pdf.py

Day 7 下午 (2-3小时):
  集成测试
  编写文档
  
  ✅ MVP 完全完成！
```

---

## 📦 依赖管理

### requirements.txt

```txt
# 核心依赖（必需）
pyyaml>=6.0
watchdog>=2.1.0

# OCR（图片处理）
paddleocr>=2.6.0
pillow>=9.0.0

# 视频处理
openai-whisper>=20230314
ffmpeg-python>=0.2.0

# PDF 处理
PyMuPDF>=1.21.0

# CLI 工具
click>=8.0.0
rich>=12.0.0

# 测试
pytest>=7.0.0
pytest-cov>=3.0.0
```

### 分阶段安装

```bash
# Day 1-3: 核心功能
pip install pyyaml watchdog pytest

# Day 4: Web 界面
docker pull dullage/flatnotes

# Day 5: 图片处理
pip install paddleocr pillow

# Day 6-7: 视频和 PDF
pip install openai-whisper ffmpeg-python PyMuPDF
```

---

## 🔧 开发工具

### 初始化脚本

```python
# tools/init_project.py
"""快速初始化项目结构"""

import os

STRUCTURE = {
    "scripts": ["memory", "web", "processors", "cli", "utils"],
    "config": [],
    "docker": [],
    "tests": ["unit", "integration", "fixtures"],
    "examples": [],
    "tools": [],
}

def create_structure():
    for dir_name, subdirs in STRUCTURE.items():
        os.makedirs(dir_name, exist_ok=True)
        
        # 创建 __init__.py
        if dir_name == "scripts":
            for subdir in subdirs:
                path = f"{dir_name}/{subdir}"
                os.makedirs(path, exist_ok=True)
                open(f"{path}/__init__.py", "a").close()

if __name__ == "__main__":
    create_structure()
    print("✅ 项目结构创建完成！")
```

---

## 🎉 总结

### 目录结构

```
✅ 3个独立模块（可并行开发）
✅ 清晰的职责划分
✅ 最小依赖
✅ 易于扩展
```

### 时间估算

```
✅ 修正后: 1-2周（不是 4-6周）
✅ Week 1: MVP 完成
✅ Week 2: 完整功能（可选）

原因:
  - 使用现成的开源工具
  - 只写胶水代码
  - 并行开发
```

### 可以立即开始

```
第一步:
  python tools/init_project.py

第二步:
  开始写 scripts/memory/core.py

预计 7 天后:
  ✅ 完整可用的 MVP！
```

---

**⚡ 用开源工具，1-2周完成，不是 4-6周！**
