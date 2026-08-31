# Atelierr 三 MVP 并行开发计划

**版本**: v4.0 (三 MVP 并行版)  
**日期**: 2026-08-28  
**状态**: 🔒 最终对齐

---

## 🎯 核心理解：不是一个 MVP，而是三个！

### 传统误解（我之前的理解）

```
一个大 MVP = 记忆模块 + Web 界面 + 输入处理
  └─ 需要全部完成才能交付
```

### 正确理解（并行 MVP）

```
MVP 1: 记忆模块 (独立可用)
  ✅ 命令行工具
  ✅ 独立运行
  ✅ 价值：笔记管理和智能衰减

MVP 2: Web 界面 (独立可用)
  ✅ Flatnotes 部署
  ✅ 独立运行
  ✅ 价值：Web 笔记编辑

MVP 3: 输入处理 (独立可用)
  ✅ 各种格式转换
  ✅ 独立运行
  ✅ 价值：多模态输入

最终集成 = MVP1 + MVP2 + MVP3
```

---

## 🚀 三个独立 MVP 详解

### MVP 1: 记忆模块（核心）

**价值主张**: 智能笔记管理系统，自动计算重要度，自动衰减分层

**独立运行**:

```bash
# 不需要 Web 界面，不需要输入处理
# 直接通过命令行或 Python API 使用

# 创建笔记
python -m scripts.cli.memory_cli create "我的笔记.md" --content "笔记内容"

# 搜索笔记
python -m scripts.cli.memory_cli search "关键词"

# 查看统计
python -m scripts.cli.memory_cli stats

# 手动衰减
python -m scripts.cli.memory_cli decay --dry-run
```

**核心功能**:

```
✅ 三层目录结构 (short-term, mid-term, long-term)
✅ Confidence 计算（时间、引用、修改）
✅ 自动衰减机制
✅ 全文搜索
✅ 命令行接口
✅ Python API

交付标准:
  - 测试覆盖率 ≥ 80%
  - 命令行工具可用
  - 1000 笔记性能达标
  - 文档完整
```

**交付时间**: Week 1 (5-7天)

**独立价值**: ⭐⭐⭐⭐⭐
- 即使没有 Web 界面，也可以用命令行管理笔记
- 即使没有输入处理，也可以手动创建 Markdown 文件

---

### MVP 2: Web 界面（独立）

**价值主张**: 现代化的 Web 笔记编辑器，随时随地访问

**独立运行**:

```bash
# 不需要记忆模块，不需要输入处理
# 就是一个纯粹的 Flatnotes 部署

docker-compose up -d flatnotes

# 访问 http://localhost:8080
# 创建、编辑、搜索笔记
```

**核心功能**:

```
✅ Flatnotes Docker 部署
✅ Web 界面访问
✅ Markdown 编辑
✅ 文件管理
✅ 搜索功能（Flatnotes 自带）
✅ 移动端支持

交付标准:
  - Docker Compose 一键启动
  - Web 界面可访问
  - 基础笔记功能可用
  - 部署文档完整
```

**交付时间**: Day 1-2 (2天)

**独立价值**: ⭐⭐⭐⭐
- 即使没有记忆模块，也是个好用的笔记工具
- 即使没有输入处理，也可以手动创建笔记

---

### MVP 3: 输入处理（独立）

**价值主张**: 多模态转换工具，一键处理各种格式

**独立运行**:

```bash
# 不需要记忆模块，不需要 Web 界面
# 就是一个格式转换工具集

# 图片 OCR
python -m scripts.cli.process_cli image screenshot.jpg --output output.md

# PDF 转 Markdown
python -m scripts.cli.process_cli pdf document.pdf --output output.md

# 视频转文字
python -m scripts.cli.process_cli video lecture.mp4 --output output.md

# 批量处理
python -m scripts.cli.batch_cli --input-dir ~/Downloads/ --output-dir ~/Notes/
```

**核心功能**:

```
✅ 图片处理器（PaddleOCR）
✅ PDF 处理器（PyMuPDF）
✅ 视频处理器（Whisper）
✅ 音频处理器（Whisper）
⏳ 微信处理器（→ backlog：导出格式不稳定，不进 MVP）
✅ 批量处理工具

交付标准:
  - 所有处理器可用
  - 命令行工具可用
  - 性能达标
  - 文档完整
```

**交付时间**: Week 1-2 (7-10天)

**独立价值**: ⭐⭐⭐⭐⭐
- 即使没有记忆模块，也是个强大的转换工具
- 即使没有 Web 界面，命令行就能用

---

## 📅 并行开发时间表

### Week 1: 三个 MVP 同时启动

```
         Day 1    Day 2    Day 3    Day 4    Day 5    Day 6    Day 7
         ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
MVP 1   │ 框架   │Confid│Confid│ Decay │ Search│ 集成  │ 测试  │
记忆    │ 设计   │ence  │ence  │       │       │       │ 验收  │
        ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
MVP 2   │Flatnot│Flatnot│ 集成  │ 测试  │ 文档  │       │       │
Web     │ 部署   │ 配置  │ 验证  │       │       │ (完成) │ (完成) │
        ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
MVP 3   │ 框架  │ 框架  │ 图片  │ 图片  │ PDF   │ PDF   │ 测试  │
输入    │ 设计  │ 实现  │ OCR   │ OCR   │ 处理  │ 处理  │ 验收  │
        ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Week 1 结束:
  ✅ MVP 1: 记忆模块核心完成，可独立使用
  ✅ MVP 2: Web 界面已完成，可独立使用 ⭐
  ✅ MVP 3: 图片+PDF 处理完成，可独立使用
```

### Week 2: 三个 MVP 独立完善

```
         Day 8    Day 9    Day 10   Day 11   Day 12   Day 13   Day 14
         ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
MVP 1   │ CLI   │ CLI   │定时任务│定时任务│ 优化  │ 优化  │ 发布  │
记忆    │ 工具  │ 工具  │       │       │       │       │ v1.0  │
        ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
MVP 2   │ 监控  │ 监控  │同步测试│ 优化  │ 文档  │       │ 发布  │
Web     │       │       │       │       │       │(完成)  │ v1.0  │
        ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
MVP 3   │ 视频  │ 视频  │ 音频  │ 微信  │ 批量  │ 批量  │ 发布  │
输入    │ 处理  │ 处理  │ 处理  │ 处理  │ 工具  │ 工具  │ v1.0  │
        ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Week 2 结束:
  ✅ MVP 1 v1.0: 记忆模块完整版，可独立发布
  ✅ MVP 2 v1.0: Web 界面完整版，可独立发布
  ✅ MVP 3 v1.0: 输入处理完整版，可独立发布
```

### Week 3: 三个 MVP 集成

```
Day 15-21: 集成周

MVP 1 + MVP 2:
  ✅ Web 界面调用记忆模块 API
  ✅ 实时显示 confidence
  ✅ Web 创建的笔记自动进入记忆系统

MVP 1 + MVP 3:
  ✅ 输入处理器输出直接进入记忆系统
  ✅ 自动计算 confidence
  ✅ 自动分层

MVP 2 + MVP 3:
  ✅ Web 界面支持拖放上传
  ✅ 自动调用处理器
  ✅ 结果显示在 Web

MVP 1 + MVP 2 + MVP 3:
  ✅ 完整集成测试
  ✅ 端到端测试
  ✅ 性能测试

Week 3 结束:
  ✅ Atelierr v1.0 完整版发布 🎉
```

---

## 🎯 单人开发策略

### 策略 1: 串行执行三个 MVP（保守）

```
Week 1-2: MVP 1 (记忆模块)
  → 完成并独立测试
  
Week 3: MVP 2 (Web 界面)
  → 完成并独立测试
  
Week 4-5: MVP 3 (输入处理)
  → 完成并独立测试
  
Week 6: 集成
  → 三个 MVP 整合

总时间: 6 周
优势: 清晰、可控
劣势: 较慢
```

### 策略 2: 时间切片（平衡）⭐ 推荐

```
每天时间分配:

上午 (4h): MVP 1 (记忆模块) - 核心开发
  → 你自己写核心逻辑

下午 (2h): MVP 2 (Web 界面) - 部署配置
  → 简单任务，快速完成

晚上 (2h): MVP 3 (输入处理) - AI 辅助
  → AI 生成处理器框架，你验证

周末: 集成和测试

Week 1 结束:
  ✅ MVP 1: 60% 完成
  ✅ MVP 2: 100% 完成 ⭐
  ✅ MVP 3: 40% 完成

Week 2 结束:
  ✅ MVP 1: 100% 完成 ⭐
  ✅ MVP 2: 100% 完成
  ✅ MVP 3: 80% 完成

Week 3 结束:
  ✅ MVP 1: 100% 完成
  ✅ MVP 2: 100% 完成
  ✅ MVP 3: 100% 完成 ⭐
  ✅ 开始集成

总时间: 3-4 周
优势: 快速、有成就感
劣势: 需要任务切换
```

### 策略 3: AI 并行（激进）

```
你 (主线): MVP 1 (记忆模块)
  → 全力开发核心逻辑

AI 助手 1: MVP 2 (Web 界面)
  → 自动部署和配置

AI 助手 2: MVP 3 (输入处理)
  → 生成处理器代码

你 (审查): 每天晚上审查 AI 的工作
  → 验证、测试、修正

Week 1 结束:
  ✅ MVP 1: 80% 完成
  ✅ MVP 2: 90% 完成
  ✅ MVP 3: 60% 完成

Week 2 结束:
  ✅ 所有 MVP 100% 完成 ⭐

总时间: 2-3 周
优势: 最快
劣势: 需要强大的 AI 辅助能力
```

---

## 📊 三个 MVP 的依赖关系

### 完全独立（可以任意顺序开发）

```
MVP 1 (记忆模块)
  ├─ 不依赖 MVP 2
  ├─ 不依赖 MVP 3
  └─ 独立运行: 命令行工具

MVP 2 (Web 界面)
  ├─ 不依赖 MVP 1
  ├─ 不依赖 MVP 3
  └─ 独立运行: Flatnotes

MVP 3 (输入处理)
  ├─ 不依赖 MVP 1
  ├─ 不依赖 MVP 2
  └─ 独立运行: 转换工具

集成 (可选):
  ├─ MVP 1 + MVP 2: Web 调用记忆 API
  ├─ MVP 1 + MVP 3: 处理器输出到记忆
  └─ MVP 2 + MVP 3: Web 上传调用处理器
```

### 接口设计（为集成准备）

```python
# MVP 1: 记忆模块提供 API
class MemoryTree:
    def create_note(self, title: str, content: str) -> Path:
        """创建笔记，返回路径"""
        pass
    
    def search(self, query: str) -> List[Dict]:
        """搜索笔记，返回结果"""
        pass

# MVP 3: 输入处理提供 API
class ImageProcessor:
    def process(self, image_path: str) -> Dict:
        """处理图片，返回结构化数据"""
        return {
            "title": "OCR 结果",
            "content": "提取的文字...",
            "markdown": "# OCR 结果\n\n提取的文字..."
        }

# 集成: MVP 1 + MVP 3
processor = ImageProcessor()
memory = MemoryTree("/path/to/memory")

result = processor.process("screenshot.jpg")
memory.create_note(result["title"], result["markdown"])
```

---

## 🚀 推荐执行方案

### 单人开发推荐: 策略 2 (时间切片)

```
Week 1:
  Monday:
    上午: MVP 1 - MemoryTree 核心类
    下午: MVP 2 - Flatnotes Docker 部署
    晚上: MVP 3 - 处理器框架设计
  
  Tuesday:
    上午: MVP 1 - Confidence 计算
    下午: MVP 2 - 测试 Flatnotes
    晚上: MVP 3 - 图片处理器
  
  Wednesday:
    上午: MVP 1 - Confidence 计算
    下午: MVP 2 - 文档 (MVP 2 完成! ⭐)
    晚上: MVP 3 - 图片处理器
  
  Thursday:
    上午: MVP 1 - 衰减机制
    下午: 休息或复习
    晚上: MVP 3 - PDF 处理器
  
  Friday:
    上午: MVP 1 - 搜索功能
    下午: 集成测试
    晚上: MVP 3 - PDF 处理器
  
  Weekend:
    ✅ MVP 1: 测试和文档
    ✅ MVP 3: 测试和文档
    ✅ 准备 Week 2

Week 1 结束交付:
  ✅ MVP 2 已完成，可独立使用 ⭐
  ✅ MVP 1 核心完成 (60-80%)
  ✅ MVP 3 图片+PDF 完成 (40-60%)
```

---

## ✅ 验收标准（三个独立 MVP）

### MVP 1: 记忆模块验收

```bash
# 1. 命令行工具可用
python -m scripts.cli.memory_cli --help

# 2. 创建笔记
python -m scripts.cli.memory_cli create "test.md" --content "测试"

# 3. 搜索笔记
python -m scripts.cli.memory_cli search "测试"

# 4. 查看统计
python -m scripts.cli.memory_cli stats

# 5. 测试通过
pytest tests/unit/test_memory/ -v

验收标准:
  ✅ 所有命令可用
  ✅ 测试覆盖率 ≥ 80%
  ✅ 文档完整
  ✅ 可独立使用（不需要其他 MVP）
```

### MVP 2: Web 界面验收

```bash
# 1. 启动服务
docker-compose up -d flatnotes

# 2. 访问界面
curl http://localhost:8080

# 3. 测试功能
# - 打开浏览器
# - 创建笔记
# - 编辑笔记
# - 搜索笔记

验收标准:
  ✅ Docker Compose 一键启动
  ✅ Web 界面可访问
  ✅ 基础功能可用
  ✅ 移动端可用
  ✅ 可独立使用（不需要其他 MVP）
```

### MVP 3: 输入处理验收

```bash
# 1. 图片处理
python -m scripts.cli.process_cli image test.jpg --output test.md

# 2. PDF 处理
python -m scripts.cli.process_cli pdf test.pdf --output test.md

# 3. 批量处理
python -m scripts.cli.batch_cli --input-dir ~/test/ --output-dir ~/output/

# 4. 测试通过
pytest tests/unit/test_processors/ -v

验收标准:
  ✅ 所有处理器可用
  ✅ 命令行工具可用
  ✅ 性能达标
  ✅ 测试覆盖率 ≥ 80%
  ✅ 可独立使用（不需要其他 MVP）
```

---

## 🎉 最终总结

### 关键理解

```
❌ 错误理解:
   一个大 MVP = 记忆 + Web + 输入
   必须全部完成才能用

✅ 正确理解:
   三个独立 MVP，每个都有价值
   可以并行开发
   可以独立交付
   可以独立使用
   最后可以集成
```

### 开发策略

```
推荐: 时间切片策略

Day 1:
  上午 4h: MVP 1 (核心)
  下午 2h: MVP 2 (简单)
  晚上 2h: MVP 3 (AI 辅助)

Week 1 结束:
  MVP 2 完成! ⭐
  MVP 1 60-80%
  MVP 3 40-60%

Week 2-3 结束:
  所有 MVP 完成!
  开始集成
```

### 价值递增

```
Week 1 结束:
  ✅ 有了 Web 笔记工具 (MVP 2)

Week 2 结束:
  ✅ 有了智能笔记系统 (MVP 1)
  ✅ Web 工具更强大了

Week 3 结束:
  ✅ 有了格式转换工具 (MVP 3)
  ✅ 完整系统成型

Week 4 结束:
  ✅ 三个 MVP 完美集成 🎉
```

---

**🚀 现在理解对了吗？三个独立 MVP，并行开发，独立交付！**

---

## 📱 移动端捕获（MVP 后增量，2026-08-31 完成）

**定位**: 系统的移动端输入通道，挂靠 MVP 1（记忆模块）。手机端的看和写由
Obsidian 承担，Flatnotes 保留为电脑浏览器入口。不改变架构 v1.2：速记产物是
平面笔记目录里的普通 markdown，走 watcher 归一化既有链路。

**组件**:

```
Obsidian (手机 App)   —— 查看/编辑笔记
  └─ QuickAdd 插件    —— 一键速记：追加 "- HH:mm 内容" 到当天日记 YYYY-MM-DD.md
Syncthing-Fork (手机) —— 与电脑双向同步
Syncthing (docker)    —— 电脑侧守护，host 网络，端口 22000
```

**数据链路**:

```
手机 Obsidian 速记
  → Documents/atelierr-memory (手机)
  → Syncthing 双向同步 → /home/cj1024/atelierr-data/memory (电脑, = $OV/memory)
  → watcher 归一化 frontmatter + sidecar 登记（mtime 保持不变）
  → 每日 03:00 定时器：sync → decay
```

**远程连通**: WireGuard 专线（设备地址 `tcp://10.66.0.2`，电脑侧反向配
`tcp://10.66.0.3`）+ global discovery 公网兜底，手机换网络环境也能同步。
华为手机需在"应用启动管理"中放行 Syncthing 后台，防止被杀导致断线。

**验收**: 端到端实测通过——手机速记三条内容经同步落入电脑侧当天日记，
frontmatter 与正文追加互不干扰。

---

## 📦 Backlog

三个 MVP 已完成并集成后的待办池（不进 MVP 范围，按需排期）：

- **微信记录处理器**: 导出格式不稳定、无官方规范，暂无稳定输入可依赖
- ~~Whisper 真实模型转写验证~~ ✅ 已完成（2026-08-29）：真实 tiny 模型
  转写 JFK 语音样本，audio/video 两条路径均正确识别（含 "ask not" 片段），
  audio 14.0s（含首次模型加载）/ video 0.6s（模型进程内缓存），confidence 0.717
- ~~RapidOCR 5s 路径~~ ✅ 已完成（2026-08-29）：`processors.image.engine: rapidocr`
  已实现（onnxruntime），整页扫描 CPU 实测 ~0.8s/页（vs paddle 12-14s），
  截图类 ~0.8s；PDF 经 `processors.pdf.ocr_engine` 透传
- **完整版验收**: 覆盖率 ≥85%、mypy/pylint 门禁、负载测试（1000+ 笔记）
