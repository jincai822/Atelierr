# 多模态输入处理方案

**版本**: v1.0  
**状态**: 架构扩展（补充文档）  
**日期**: 2026-08-27

---

## 问题

**用户输入的内容不只是文本，还包括**:
- 微信聊天记录（文本 + 图片）
- 抖音/YouTube 链接
- 视频文件
- 图片
- PDF 文件
- 音频录音
- 网页截图

**如何让这些内容进入 Atelierr 系统？**

---

## 设计原则

```
✅ 保持三模块架构不变
✅ 所有输入最终转化为 Markdown + 附件
✅ 处理流程在"记忆模块"之前
✅ 用户可选择自动化程度
```

---

## 整体架构（扩展版）

```
输入层（新增）
    ↓
预处理层（新增）
    ↓
Web 界面 (Flatnotes)
    ↓
$OV/memory/*.md
    ↓
记忆模块 (memory.py)
    ↓
Atelierr Core (Agents)
```

---

## 方案 1: 输入处理流水线（推荐）

### 架构图

```
┌─────────────────────────────────────────────────┐
│           输入层（多模态）                       │
├─────────────────────────────────────────────────┤
│                                                 │
│  📱 微信聊天记录    🎬 抖音链接    📸 图片      │
│  🎥 视频文件       📄 PDF        🎤 音频       │
│                                                 │
└─────────────┬───────────────────────────────────┘
              ↓
┌─────────────────────────────────────────────────┐
│      预处理层（新增组件）                        │
├─────────────────────────────────────────────────┤
│                                                 │
│  • input_processor.py                           │
│    ├── WeChatProcessor   (微信处理器)           │
│    ├── VideoProcessor    (视频处理器)           │
│    ├── ImageProcessor    (图片处理器)           │
│    ├── LinkProcessor     (链接处理器)           │
│    └── AudioProcessor    (音频处理器)           │
│                                                 │
└─────────────┬───────────────────────────────────┘
              ↓
┌─────────────────────────────────────────────────┐
│      标准化输出                                  │
├─────────────────────────────────────────────────┤
│                                                 │
│  Markdown 文件 + 附件文件夹                      │
│  ├── content.md                                 │
│  └── attachments/                               │
│      ├── image1.jpg                             │
│      ├── video1.mp4                             │
│      └── transcript.txt                         │
│                                                 │
└─────────────┬───────────────────────────────────┘
              ↓
┌─────────────────────────────────────────────────┐
│      现有系统（无需改动）                        │
├─────────────────────────────────────────────────┤
│                                                 │
│  Web 界面 → 记忆模块 → Atelierr Core            │
│                                                 │
└─────────────────────────────────────────────────┘
```

---

## 文件结构（扩展）

```
Atelierr/
├── scripts/
│   ├── memory.py              (现有)
│   ├── input_processor.py     (新增 - 主处理器)
│   └── processors/            (新增 - 各类处理器)
│       ├── __init__.py
│       ├── wechat.py          # 微信处理器
│       ├── video.py           # 视频处理器
│       ├── image.py           # 图片处理器
│       ├── link.py            # 链接处理器
│       ├── audio.py           # 音频处理器
│       ├── pdf.py             # PDF 处理器
│       └── base.py            # 基础处理器类

$OV/
├── inbox/                     (新增 - 输入暂存区)
│   ├── wechat/                # 微信导出
│   ├── videos/                # 视频文件
│   ├── images/                # 图片
│   └── raw/                   # 其他原始文件
│
├── memory/                    (现有)
│   ├── long-term/
│   ├── mid-term/
│   └── short-term/
│       └── observations/
│           ├── 2026-08-27-wechat-chat.md
│           └── attachments/
│               ├── chat-screenshot.jpg
│               └── shared-video.mp4
│
└── archive/                   (新增 - 已处理的原始文件)
    └── 2026-08/
        └── wechat-export-20260827.zip
```

---

## 详细处理流程

### 1. 微信聊天记录

#### 输入格式

```
用户通过以下方式导出:
  • 微信 PC 端：聊天记录 → 导出为文本
  • 第三方工具：WeChatExporter
  • 手动截图
```

#### 处理流程

```python
# scripts/processors/wechat.py

class WeChatProcessor:
    """微信聊天记录处理器"""
    
    def process(self, input_path: str) -> Dict:
        """
        处理微信聊天记录
        
        输入: 
          - 文本文件 (.txt)
          - 导出的 HTML
          - 截图 (.jpg, .png)
        
        输出:
          - Markdown 文件
          - 附件文件夹
        """
        
        # 1. 检测输入类型
        input_type = self.detect_type(input_path)
        
        if input_type == 'text':
            # 解析文本格式
            messages = self.parse_text(input_path)
        
        elif input_type == 'html':
            # 解析 HTML 格式
            messages = self.parse_html(input_path)
        
        elif input_type == 'image':
            # OCR 识别截图
            messages = self.ocr_screenshot(input_path)
        
        # 2. 提取关键信息
        summary = self.summarize_chat(messages)
        key_points = self.extract_key_points(messages)
        participants = self.extract_participants(messages)
        
        # 3. 生成 Markdown
        markdown = self.generate_markdown(
            summary=summary,
            key_points=key_points,
            participants=participants,
            messages=messages
        )
        
        # 4. 处理附件（图片、视频）
        attachments = self.extract_attachments(messages)
        
        # 5. 保存到 $OV/memory/
        output_path = self.save_to_memory(
            markdown=markdown,
            attachments=attachments,
            confidence=0.4  # 聊天记录初始置信度较低
        )
        
        return {
            'status': 'success',
            'output_path': output_path,
            'attachments_count': len(attachments)
        }
```

#### 输出示例

```markdown
---
title: 与张三讨论 asyncio 性能问题
created: 2026-08-27T16:00:00
source: wechat
confidence: 0.4
participants: ["我", "张三"]
tags: ["对话", "技术讨论", "asyncio"]
---

# 微信聊天记录 - asyncio 性能讨论

## 概要

与张三讨论了 asyncio 在 CPU 密集型任务中的性能问题。

## 关键要点

1. asyncio 不适合 CPU 密集任务
2. 建议使用 multiprocessing
3. 张三分享了一个性能测试案例

## 对话记录

### 2026-08-27 14:30

**我**: 最近在用 asyncio，发现 CPU 密集型任务很慢

**张三**: 对的，asyncio 是为 I/O 设计的

**我**: 那怎么办？

**张三**: CPU 密集型用 multiprocessing
（分享了一段代码截图）

![代码示例](attachments/code-screenshot.jpg)

## 行动项

- [ ] 测试 multiprocessing 性能
- [ ] 重构现有代码

## 相关资源

- [[Python 并发编程]]
- [[AsyncIO 最佳实践]]
```

---

### 2. 抖音/YouTube 链接

#### 处理流程

```python
# scripts/processors/link.py

class LinkProcessor:
    """视频链接处理器"""
    
    def process(self, url: str) -> Dict:
        """
        处理视频链接
        
        支持:
          - 抖音
          - YouTube
          - B站
          - 其他视频平台
        """
        
        # 1. 下载视频（可选）
        video_path = self.download_video(url) if self.should_download() else None
        
        # 2. 获取元数据
        metadata = self.fetch_metadata(url)
        # title, description, duration, author, publish_date
        
        # 3. 提取字幕/转录
        transcript = self.extract_transcript(url)
        
        # 4. 生成摘要
        summary = self.summarize_transcript(transcript)
        
        # 5. 生成 Markdown
        markdown = self.generate_markdown(
            url=url,
            metadata=metadata,
            transcript=transcript,
            summary=summary,
            video_path=video_path
        )
        
        # 6. 保存
        output_path = self.save_to_memory(
            markdown=markdown,
            video_path=video_path,
            confidence=0.5
        )
        
        return {
            'status': 'success',
            'output_path': output_path
        }
```

#### 输出示例

```markdown
---
title: 如何优化 Python 性能 - 抖音视频
created: 2026-08-27T17:00:00
source: link
url: https://v.douyin.com/xxxxx
confidence: 0.5
tags: ["视频", "Python", "性能优化"]
duration: 180
author: "Python小课堂"
---

# 如何优化 Python 性能

## 视频信息

- **来源**: 抖音
- **时长**: 3分钟
- **作者**: Python小课堂
- **发布**: 2026-08-25

## 内容摘要

视频介绍了 5 个 Python 性能优化技巧：

1. 使用内置函数代替循环
2. 列表推导式比 for 循环快
3. 避免全局变量
4. 使用局部变量
5. 使用生成器节省内存

## 字幕/转录

00:00 - 大家好，今天分享 Python 性能优化技巧...
00:30 - 第一个技巧是使用内置函数...
01:00 - 第二个技巧是列表推导式...

## 关键见解

- 内置函数用 C 实现，比 Python 循环快 10 倍
- 列表推导式不仅简洁，而且更快
- 全局变量查找比局部变量慢

## 行动项

- [ ] 审查现有代码，替换为内置函数
- [ ] 重构循环为列表推导式

## 相关笔记

- [[Python 性能优化指南]]
- [[代码优化实践]]

## 原始链接

https://v.douyin.com/xxxxx

## 本地视频

如果已下载: [观看本地视频](attachments/douyin-video.mp4)
```

---

### 3. 图片

#### 处理流程

```python
# scripts/processors/image.py

class ImageProcessor:
    """图片处理器"""
    
    def process(self, image_path: str) -> Dict:
        """
        处理图片
        
        功能:
          - OCR 识别文字
          - 图像识别
          - 提取元数据
        """
        
        # 1. OCR 识别
        ocr_text = self.ocr_extract(image_path)
        
        # 2. 图像识别（可选，使用 Vision API）
        image_description = self.describe_image(image_path)
        
        # 3. 提取 EXIF 元数据
        metadata = self.extract_exif(image_path)
        
        # 4. 生成 Markdown
        markdown = self.generate_markdown(
            image_path=image_path,
            ocr_text=ocr_text,
            description=image_description,
            metadata=metadata
        )
        
        # 5. 保存
        output_path = self.save_to_memory(
            markdown=markdown,
            image_path=image_path,
            confidence=0.3  # 图片信息置信度较低
        )
        
        return {
            'status': 'success',
            'output_path': output_path
        }
```

#### 输出示例

```markdown
---
title: 代码截图 - asyncio 性能测试
created: 2026-08-27T18:00:00
source: image
confidence: 0.3
tags: ["截图", "代码", "asyncio"]
---

# 代码截图 - asyncio 性能测试

## 原始图片

![代码截图](attachments/code-screenshot.jpg)

## OCR 提取的文字

```python
import asyncio
import time

async def cpu_task():
    # CPU 密集型任务
    result = sum(i * i for i in range(10000000))
    return result

async def main():
    start = time.time()
    tasks = [cpu_task() for _ in range(10)]
    await asyncio.gather(*tasks)
    print(f"Time: {time.time() - start:.2f}s")

asyncio.run(main())
```

## 图片描述

这是一段 Python 代码的截图，展示了使用 asyncio 进行 CPU 密集型计算的示例。

## 分析

- 代码使用 asyncio.gather 并发执行任务
- 任务是 CPU 密集型（求和计算）
- **问题**: asyncio 不适合 CPU 密集型任务

## 改进建议

应该使用 multiprocessing:

```python
from multiprocessing import Pool

def cpu_task():
    return sum(i * i for i in range(10000000))

if __name__ == '__main__':
    with Pool(10) as p:
        results = p.map(cpu_task, range(10))
```

## 相关笔记

- [[AsyncIO 适用场景]]
- [[Python 并发编程]]
```

---

### 4. 视频文件

#### 处理流程

```python
# scripts/processors/video.py

class VideoProcessor:
    """视频文件处理器"""
    
    def process(self, video_path: str) -> Dict:
        """
        处理视频文件
        
        功能:
          - 提取音频
          - 语音转文字
          - 生成字幕
          - 提取关键帧
        """
        
        # 1. 提取音频
        audio_path = self.extract_audio(video_path)
        
        # 2. 语音转文字 (Whisper)
        transcript = self.speech_to_text(audio_path)
        
        # 3. 生成时间轴字幕
        subtitles = self.generate_subtitles(transcript)
        
        # 4. 提取关键帧（可选）
        keyframes = self.extract_keyframes(video_path)
        
        # 5. 生成摘要
        summary = self.summarize_content(transcript)
        
        # 6. 生成 Markdown
        markdown = self.generate_markdown(
            video_path=video_path,
            transcript=transcript,
            subtitles=subtitles,
            summary=summary,
            keyframes=keyframes
        )
        
        # 7. 保存
        output_path = self.save_to_memory(
            markdown=markdown,
            video_path=video_path,
            confidence=0.6
        )
        
        return {
            'status': 'success',
            'output_path': output_path
        }
```

---

## 实现方案

### 方案 A: 命令行工具（最小实现）

```bash
# 处理微信聊天记录
python scripts/input_processor.py \
  --type wechat \
  --input ~/Downloads/wechat-export.txt

# 处理抖音链接
python scripts/input_processor.py \
  --type link \
  --url https://v.douyin.com/xxxxx

# 处理图片
python scripts/input_processor.py \
  --type image \
  --input ~/Pictures/screenshot.jpg

# 处理视频
python scripts/input_processor.py \
  --type video \
  --input ~/Videos/lecture.mp4
```

### 方案 B: Watch 文件夹（自动化）

```python
# scripts/input_watcher.py

from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

class InputWatcher(FileSystemEventHandler):
    """监控 $OV/inbox/ 文件夹"""
    
    def on_created(self, event):
        """新文件时自动处理"""
        
        if event.is_directory:
            return
        
        # 检测文件类型
        file_type = self.detect_type(event.src_path)
        
        # 选择处理器
        processor = self.get_processor(file_type)
        
        # 处理文件
        result = processor.process(event.src_path)
        
        # 移动到归档
        self.archive(event.src_path)
```

用法:

```bash
# 启动监控
python scripts/input_watcher.py --watch $OV/inbox/

# 用户只需把文件放到 inbox/
cp wechat-export.txt $OV/inbox/
# 自动处理并生成 Markdown
```

### 方案 C: Web 界面上传（最佳用户体验）

在 Flatnotes 基础上扩展:

```javascript
// 在 Flatnotes 中添加上传功能

<template>
  <div class="upload-zone">
    <input 
      type="file" 
      @change="handleUpload"
      accept="image/*,video/*,.txt,.pdf"
    >
    
    <input 
      type="url" 
      placeholder="粘贴抖音/YouTube 链接"
      @change="handleLink"
    >
  </div>
</template>

<script>
export default {
  methods: {
    async handleUpload(file) {
      // 上传到服务器
      const formData = new FormData();
      formData.append('file', file);
      
      // 调用预处理 API
      const response = await fetch('/api/process', {
        method: 'POST',
        body: formData
      });
      
      // 返回处理后的 Markdown
      const markdown = await response.json();
      
      // 显示在编辑器
      this.showMarkdown(markdown);
    }
  }
}
</script>
```

---

## 技术栈

### 核心依赖

```yaml
OCR:
  - pytesseract         # 开源 OCR
  - PaddleOCR           # 中文 OCR (更好)
  - OpenAI Vision API   # 商业方案

语音转文字:
  - whisper             # OpenAI Whisper (本地)
  - faster-whisper      # 优化版本
  - cloud APIs          # 云服务（备选）

视频处理:
  - ffmpeg              # 视频/音频处理
  - opencv-python       # 关键帧提取
  - moviepy             # Python 视频编辑

链接处理:
  - yt-dlp              # 视频下载
  - youtube-transcript-api  # YouTube 字幕

其他:
  - watchdog            # 文件监控
  - pillow              # 图片处理
  - beautifulsoup4      # HTML 解析
```

---

## 数据流程（完整版）

```
用户输入
    ↓
┌─────────────────────────────────┐
│ 1. 输入识别                     │
│    - 微信聊天记录?              │
│    - 视频链接?                  │
│    - 图片?                      │
│    - 视频文件?                  │
└───────────┬─────────────────────┘
            ↓
┌─────────────────────────────────┐
│ 2. 选择处理器                   │
│    - WeChatProcessor            │
│    - LinkProcessor              │
│    - ImageProcessor             │
│    - VideoProcessor             │
└───────────┬─────────────────────┘
            ↓
┌─────────────────────────────────┐
│ 3. 内容提取                     │
│    - 文字 (OCR / 转录)          │
│    - 元数据                     │
│    - 附件                       │
└───────────┬─────────────────────┘
            ↓
┌─────────────────────────────────┐
│ 4. 生成 Markdown                │
│    - 标题                       │
│    - 内容                       │
│    - Frontmatter (confidence)   │
│    - 附件链接                   │
└───────────┬─────────────────────┘
            ↓
┌─────────────────────────────────┐
│ 5. 保存到 $OV/memory/           │
│    - content.md                 │
│    - attachments/               │
└───────────┬─────────────────────┘
            ↓
┌─────────────────────────────────┐
│ 6. 现有流程（无需改动）          │
│    - 记忆模块计算 confidence    │
│    - 自动衰减                   │
│    - Agents 使用                │
└─────────────────────────────────┘
```

---

## 示例：完整工作流

### 场景: 用户分享抖音学习视频

```bash
# 1. 用户复制链接并运行
python scripts/input_processor.py \
  --type link \
  --url https://v.douyin.com/Python-performance-tips

# 2. 系统自动:
#    - 下载视频 (可选)
#    - 提取字幕/转录
#    - 生成摘要
#    - 创建 Markdown

# 3. 输出到:
$OV/memory/short-term/observations/2026-08-27-python-tips.md
$OV/memory/short-term/observations/attachments/video.mp4

# 4. 记忆模块自动:
#    - 检测新文件
#    - 计算 confidence (0.5, 来源: link)
#    - 保持在 short-term/

# 5. 用户访问:
#    - 通过 Flatnotes 查看笔记
#    - 观看本地视频
#    - 添加笔记和标签

# 6. Agents 可以:
#    - 搜索 "Python 性能" 找到这个记忆
#    - 使用内容进行反思
#    - 与其他记忆关联
```

---

## 成本考虑

### 免费方案

```yaml
OCR: PaddleOCR (本地)
语音转文字: Whisper (本地)
视频处理: FFmpeg (本地)
总成本: $0
```

### 商业方案

```yaml
OCR: OpenAI Vision API
  - $0.01 / image
  
语音转文字: Whisper API
  - $0.006 / 分钟
  
视频下载: yt-dlp (免费)

预估成本: 
  - 100 张图片/月: $1
  - 500 分钟音频/月: $3
  - 总计: ~$5/月
```

---

## 实现优先级

### Phase 1: 最小可用 (Week 1)

```
✅ 命令行工具框架
✅ 图片处理器 (OCR)
✅ 链接处理器 (基础)
✅ 保存到 $OV/memory/
```

### Phase 2: 自动化 (Week 2)

```
✅ Watch 文件夹
✅ 视频处理器
✅ 微信处理器
✅ 自动归档
```

### Phase 3: 集成 (Week 3)

```
✅ Flatnotes 上传功能
✅ 飞书机器人集成
✅ API 接口
✅ 批量处理
```

---

## 总结

### 核心思想

```
任何输入 → 预处理 → Markdown + 附件 → 现有系统
```

### 架构优势

```
✅ 不改变现有三模块架构
✅ 预处理层独立可插拔
✅ 输出标准化 (Markdown)
✅ 渐进式实现
```

### 用户体验

```
最简单: 
  命令行处理 → 手动上传到 Flatnotes
  
自动化:
  文件夹监控 → 自动处理 → 自动保存
  
最佳:
  Web 界面上传 → 实时处理 → 实时预览
```

---

**🎯 多模态输入处理不改变核心架构，只是添加了一个"预处理层"！**
