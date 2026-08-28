# 大文件处理方案

**版本**: v1.0  
**状态**: 架构扩展  
**日期**: 2026-08-27

---

## 问题

**大文件处理挑战**:
- 视频文件: 1GB+
- PDF 文档: 200MB+
- 音频录音: 500MB+

**面临的问题**:
1. 存储空间占用大
2. 处理时间长
3. 内存消耗高
4. 传输带宽限制
5. 版本控制困难（Git 不适合大文件）

---

## 核心策略

### 策略 1: 分离存储（推荐）

```
原则: 内容和元数据分离

Markdown (小文件, Git 管理)
  ├── 元数据
  ├── 摘要
  ├── 关键信息
  └── 指向原始文件的链接

原始大文件 (独立存储, 不进入 Git)
  ├── 本地路径
  ├── 云存储
  └── NAS
```

### 策略 2: 智能处理

```
不保存完整文件
  ↓
只提取关键信息
  ↓
保存到 Markdown
```

---

## 详细方案

### 方案 A: 本地引用（最简单）

#### 架构

```
$OV/                           (Git 管理)
├── memory/
│   └── 2026-08-27-video.md   (元数据 + 摘要, 5KB)
│
外部存储/                      (不进入 Git)
├── /mnt/nas/videos/
│   └── lecture-2026-08-27.mp4  (1GB)
│
└── /mnt/nas/pdfs/
    └── research-paper.pdf      (200MB)
```

#### Markdown 格式

```markdown
---
title: Python AsyncIO 深度讲座
created: 2026-08-27T16:00:00+08:00
source: video
confidence: 0.6
tags: ["视频", "python", "asyncio"]

# 大文件信息
original_file:
  path: "/mnt/nas/videos/lecture-2026-08-27.mp4"
  size: 1073741824  # 1GB
  duration: 3600    # 1小时
  format: "mp4"
  checksum: "sha256:abc123..."
  
# 备用位置
backup_locations:
  - "s3://my-bucket/videos/lecture-2026-08-27.mp4"
  - "https://youtube.com/watch?v=xxxxx"
---

# Python AsyncIO 深度讲座

## 原始文件

⚠️ **大文件**: 此笔记引用 1GB 的视频文件

**本地路径**: `/mnt/nas/videos/lecture-2026-08-27.mp4`

**在线观看**: https://youtube.com/watch?v=xxxxx

## 视频信息

- 时长: 1小时
- 讲者: David Beazley
- 会议: PyCon 2024

## 完整转录

（从视频中提取的文字，约 10-20KB）
00:00 - 大家好，今天我们来深入探讨 AsyncIO...
...

## 关键见解

1. AsyncIO 适合 I/O 密集型任务
2. Event Loop 的工作原理
3. 常见陷阱和解决方案

（详细内容...）
```

#### 优势

```
✅ Git 仓库保持轻量（只有文字）
✅ 原始文件独立存储
✅ 可以随时访问原始文件
✅ 支持多个备份位置
```

#### 劣势

```
❌ 需要管理外部存储
❌ 文件移动后需要更新路径
❌ 跨设备访问需要同步
```

---

### 方案 B: 增量提取（推荐）

#### 核心思想

```
不保存完整大文件
  ↓
只提取和保存关键信息
  ↓
原始文件可选保留
```

#### 对于视频文件 (1GB)

**提取内容**:

```python
# scripts/processors/video.py

class VideoProcessor:
    def process_large_video(self, video_path: str) -> Dict:
        """处理大视频文件"""
        
        # 1. 提取音频 (100MB) → 转文字 (100KB)
        audio = self.extract_audio(video_path)
        transcript = self.speech_to_text(audio)  # 约 100KB
        os.remove(audio)  # 删除临时音频
        
        # 2. 提取关键帧 (10 张图片 × 500KB = 5MB)
        keyframes = self.extract_keyframes(
            video_path, 
            num_frames=10,
            max_size=(1920, 1080)
        )
        
        # 3. 提取元数据 (1KB)
        metadata = self.extract_metadata(video_path)
        
        # 4. 生成摘要 (10KB)
        summary = self.summarize_transcript(transcript)
        
        # 5. 生成章节 (5KB)
        chapters = self.generate_chapters(transcript)
        
        # 总大小: 约 5-10MB (从 1GB 压缩到 10MB)
        
        return {
            'transcript': transcript,      # 100KB
            'keyframes': keyframes,        # 5MB
            'metadata': metadata,          # 1KB
            'summary': summary,            # 10KB
            'chapters': chapters,          # 5KB
            'total_size_saved': '5-10MB'
        }
```

**最终保存**:

```
$OV/memory/
└── 2026-08-27-asyncio-lecture/
    ├── content.md              (约 100KB, 包含完整转录)
    └── attachments/
        ├── keyframe-00-00.jpg  (500KB)
        ├── keyframe-05-30.jpg  (500KB)
        ├── keyframe-12-00.jpg  (500KB)
        └── ...                 (共 10 张)
        
总大小: ~5-10MB (原始 1GB)
压缩比: 99%
```

**Markdown 内容**:

```markdown
---
title: Python AsyncIO 深度讲座
source: video
original_size: 1073741824  # 1GB
processed_size: 10485760   # 10MB
compression_ratio: 0.99
tags: ["视频", "python"]

# 原始文件（可选保留）
original_file:
  deleted: false
  path: "/archive/videos/lecture.mp4"
  note: "原始文件已归档，可根据需要删除"
---

# Python AsyncIO 深度讲座

## 章节概览

- [00:00] 介绍
- [05:30] Event Loop 原理
- [12:00] async/await 语法
- [20:00] 常见陷阱
- [35:00] 性能对比
- [50:00] Q&A

## 关键帧

### 开场 (00:00)

![开场](attachments/keyframe-00-00.jpg)

讲者介绍 AsyncIO 的背景和动机...

### Event Loop 工作原理 (05:30)

![Event Loop 图解](attachments/keyframe-05-30.jpg)

Event Loop 的核心机制...

### 性能对比实验 (35:00)

![性能对比表格](attachments/keyframe-35-00.jpg)

三种方案的性能测试结果...

## 完整转录

00:00 - 大家好，我是 David Beazley...
00:15 - 今天我们来深入探讨 AsyncIO...
（约 20,000 字的完整转录）
...

## 核心内容摘要

（AI 生成的结构化摘要，约 2000 字）

1. AsyncIO 的本质
   - 协作式多任务
   - Event Loop 机制
   
2. 使用场景
   - 适合: I/O 密集型
   - 不适合: CPU 密集型
   
...
```

#### 优势

```
✅ 99% 的空间节省
✅ 保留了所有关键信息
✅ Git 仓库保持轻量
✅ 搜索效率高（纯文本）
✅ 可选保留原始文件
```

---

#### 对于 PDF 文件 (200MB)

**提取策略**:

```python
# scripts/processors/pdf.py

class PDFProcessor:
    def process_large_pdf(self, pdf_path: str) -> Dict:
        """处理大 PDF 文件"""
        
        # 1. 提取文本 (通常 1-5MB)
        text = self.extract_text(pdf_path)
        
        # 2. 提取图表 (重要的图，约 10 张 × 200KB = 2MB)
        images = self.extract_important_images(
            pdf_path,
            max_images=10,
            min_importance=0.7
        )
        
        # 3. 提取目录结构 (1KB)
        toc = self.extract_toc(pdf_path)
        
        # 4. 提取元数据 (1KB)
        metadata = self.extract_metadata(pdf_path)
        
        # 5. 生成摘要 (10KB)
        summary = self.summarize_content(text)
        
        # 总大小: 约 3-7MB (从 200MB 压缩到 7MB)
        
        return {
            'text': text,              # 1-5MB
            'images': images,          # 2MB
            'toc': toc,               # 1KB
            'metadata': metadata,      # 1KB
            'summary': summary         # 10KB
        }
```

**PDF 特殊处理**:

```markdown
---
title: 深度学习论文 - Attention Is All You Need
source: pdf
original_size: 209715200  # 200MB
processed_size: 5242880   # 5MB
pages: 500
tags: ["论文", "深度学习"]

original_file:
  path: "/archive/papers/attention-paper.pdf"
  url: "https://arxiv.org/pdf/1706.03762.pdf"
  note: "可从 arXiv 重新下载"
---

# Attention Is All You Need

## 论文信息

- **作者**: Vaswani et al.
- **发表**: NeurIPS 2017
- **页数**: 500 页
- **原始文件**: 200MB (包含高清图表)
- **在线地址**: https://arxiv.org/pdf/1706.03762.pdf

## 目录

1. Introduction (p.1-10)
2. Background (p.11-50)
3. Model Architecture (p.51-150)
4. Experiments (p.151-300)
5. Results (p.301-450)
6. Conclusion (p.451-500)

## 核心内容

### 1. Introduction

Transformer 模型摒弃了传统的 RNN 和 CNN 结构...

### 2. Model Architecture

![Transformer 架构图](attachments/figure-1-architecture.png)

模型由以下几部分组成:
- Encoder
- Decoder
- Self-Attention 机制
- Position Encoding

（详细文字说明...）

### 3. Self-Attention 机制

![Self-Attention 计算](attachments/figure-2-attention.png)

Self-Attention 的核心公式:

```
Attention(Q, K, V) = softmax(QK^T / sqrt(d_k))V
```

（详细解释...）

### 4. 实验结果

![性能对比表](attachments/table-1-results.png)

在 WMT 2014 英德翻译任务上:
- BLEU: 28.4
- 训练时间: 3.5 天
- 参数量: 65M

## 完整文本

（提取的 PDF 文本，约 1-5MB）

Introduction

The dominant sequence transduction models...
（完整论文文本）
...

## 关键公式

1. Self-Attention: ...
2. Multi-Head Attention: ...
3. Position Encoding: ...

## 重要图表

（保存了 10 张最重要的图表，共 2MB）

## 参考文献

（提取的参考文献列表）
```

---

### 方案 C: 云存储 + 本地缓存

#### 架构

```
用户上传大文件
    ↓
处理并提取关键信息
    ↓
┌──────────────────┬─────────────────┐
│                  │                 │
本地保存          云端备份         原始文件处理
(Markdown + 摘要)  (完整文件)      (可选删除)
$OV/memory/       S3/Dropbox/NAS    /tmp/ 或 /archive/
(5-10MB)          (1GB, 可选)       (删除或移动)
```

#### 配置

```yaml
# config/storage.yaml

large_file_handling:
  # 大文件阈值
  size_threshold: 100MB
  
  # 处理策略
  strategy: "extract_and_backup"  # extract_only, reference, backup
  
  # 云存储配置
  cloud_storage:
    enabled: true
    provider: "s3"  # s3, dropbox, nas
    bucket: "my-atelier-files"
    region: "us-west-2"
    
  # 本地归档
  local_archive:
    enabled: true
    path: "/mnt/nas/atelier-archive/"
    
  # 原始文件处理
  original_file:
    action: "move_to_archive"  # keep, delete, move_to_archive
    
  # 视频特殊配置
  video:
    extract_audio: true
    extract_keyframes: true
    keyframe_interval: 300  # 每 5 分钟一帧
    max_keyframes: 20
    
  # PDF 特殊配置
  pdf:
    extract_text: true
    extract_images: true
    max_images: 15
    image_quality: 0.8
```

#### 工作流程

```python
# scripts/processors/large_file.py

class LargeFileHandler:
    def __init__(self, config):
        self.config = config
        self.cloud = CloudStorage(config)
        
    def process(self, file_path: str) -> Dict:
        """处理大文件"""
        
        file_size = os.path.getsize(file_path)
        
        if file_size > self.config['size_threshold']:
            return self.process_large_file(file_path)
        else:
            return self.process_normal_file(file_path)
    
    def process_large_file(self, file_path: str) -> Dict:
        """大文件处理流程"""
        
        # 1. 提取关键信息
        extracted = self.extract_key_content(file_path)
        
        # 2. 上传到云端（可选）
        if self.config['cloud_storage']['enabled']:
            cloud_url = self.cloud.upload(file_path)
            extracted['cloud_url'] = cloud_url
        
        # 3. 移动到归档（可选）
        if self.config['local_archive']['enabled']:
            archive_path = self.move_to_archive(file_path)
            extracted['archive_path'] = archive_path
        
        # 4. 删除原始文件（可选）
        if self.config['original_file']['action'] == 'delete':
            os.remove(file_path)
        
        # 5. 保存 Markdown
        markdown_path = self.save_markdown(extracted)
        
        return {
            'status': 'success',
            'markdown_path': markdown_path,
            'original_size': file_size,
            'processed_size': extracted['size'],
            'compression_ratio': 1 - (extracted['size'] / file_size)
        }
```

---

## 存储成本分析

### 场景: 100 个大文件

#### 方案对比

| 方案 | 原始文件 | 提取内容 | 总存储 | Git 大小 | 云存储成本 |
|------|---------|---------|--------|---------|-----------|
| **全部保存** | 100GB | 500MB | 100.5GB | 100GB | - |
| **仅提取** | 删除 | 500MB | 500MB | 500MB | - |
| **提取+归档** | 100GB (NAS) | 500MB | 100.5GB | 500MB | - |
| **提取+云存储** | 删除 | 500MB | 500MB | 500MB | $2.3/月 |

#### 推荐配置

```
个人使用:
  ✅ 仅提取 (最省空间)
  ✅ 原始文件保留在外部硬盘
  
团队使用:
  ✅ 提取 + 云存储
  ✅ Git 保持轻量
  ✅ 云端备份保证可用性
  
高价值内容:
  ✅ 提取 + 本地归档 + 云存储
  ✅ 多重备份
```

---

## 处理性能

### 视频处理 (1GB)

```
步骤                  耗时        输出大小
────────────────────────────────────────
1. 提取音频            30s        100MB
2. 语音转文字          5分钟      100KB
3. 提取关键帧          1分钟      5MB
4. 生成摘要            30s        10KB
5. 保存 Markdown       1s         100KB
────────────────────────────────────────
总计                   ~7分钟     ~5MB
```

### PDF 处理 (200MB)

```
步骤                  耗时        输出大小
────────────────────────────────────────
1. 提取文本            2分钟      5MB
2. 提取图表            1分钟      2MB
3. 生成摘要            30s        10KB
4. 保存 Markdown       1s         5MB
────────────────────────────────────────
总计                   ~4分钟     ~7MB
```

### 优化建议

```python
# 异步处理
async def process_multiple_files(files: List[str]):
    tasks = [process_file(f) for f in files]
    results = await asyncio.gather(*tasks)
    return results

# 后台队列
from celery import Celery

@celery.task
def process_large_file_async(file_path: str):
    """后台异步处理大文件"""
    result = processor.process(file_path)
    notify_user(result)
```

---

## 用户体验

### 上传流程

```
1. 用户上传 1GB 视频
   ↓
2. 显示: "文件较大，正在处理..."
   ↓
3. 后台处理 (5-10 分钟)
   - 提取音频
   - 语音转文字
   - 提取关键帧
   ↓
4. 通知: "处理完成，已生成笔记"
   ↓
5. 用户查看 Markdown (立即可用)
   ↓
6. 原始文件:
   - 选项 A: 已上传到云端
   - 选项 B: 已移动到归档
   - 选项 C: 已删除（可从云端重新下载）
```

### 进度显示

```
正在处理大文件: lecture.mp4 (1.2GB)

[████████░░] 80% 
当前步骤: 提取关键帧 (4/5)
预计剩余: 2 分钟

已完成:
✅ 提取音频
✅ 语音转文字 (45 分钟内容)
✅ 生成摘要
✅ 提取关键帧 (16/20)

待完成:
⏳ 上传到云存储
⏳ 生成最终笔记
```

---

## 特殊场景

### 场景 1: 高清视频课程 (5GB)

```yaml
策略:
  - 在线观看: 保留原始 YouTube/B站 链接
  - 本地处理: 只下载音频 (50MB)
  - 提取内容:
    - 完整转录 (200KB)
    - 章节标记 (5KB)
    - 关键截图 (2MB)
  
最终保存: ~2MB
压缩比: 99.96%
```

### 场景 2: 扫描版学术专著 (500MB PDF)

```yaml
策略:
  - OCR 识别文字 (第一次处理较慢)
  - 保存识别结果 (10MB 文本)
  - 提取重要图表 (5MB)
  - 原始 PDF 备份到云端
  
最终保存: ~15MB
压缩比: 97%
```

### 场景 3: 播客音频 (500MB, 3小时)

```yaml
策略:
  - 语音转文字 (500KB)
  - 提取音频片段 (重要部分, 20MB)
  - 生成章节和摘要 (50KB)
  - 原始文件可删除（可从播客平台重新下载）
  
最终保存: ~20MB
压缩比: 96%
```

---

## 实现清单

### Phase 1: 基础大文件支持

```
✅ 检测大文件 (>100MB)
✅ 视频提取音频和转录
✅ PDF 提取文本
✅ 关键帧/图表提取
✅ 保存到独立位置
```

### Phase 2: 存储优化

```
✅ 配置文件支持
✅ 归档目录管理
✅ 原始文件清理策略
✅ 存储空间监控
```

### Phase 3: 云存储集成

```
✅ S3 集成
✅ Dropbox 集成
✅ WebDAV 支持
✅ 自动备份
```

### Phase 4: 性能优化

```
✅ 异步处理
✅ 后台队列
✅ 进度显示
✅ 断点续传
```

---

## 配置示例

### 最小配置（本地）

```yaml
# config/storage.yaml

large_file_handling:
  size_threshold: 100MB
  strategy: "extract_only"
  
  original_file:
    action: "move_to_archive"
  
  local_archive:
    enabled: true
    path: "/mnt/external-hdd/atelier-archive/"
```

### 完整配置（云端）

```yaml
# config/storage.yaml

large_file_handling:
  size_threshold: 50MB
  strategy: "extract_and_backup"
  
  cloud_storage:
    enabled: true
    provider: "s3"
    bucket: "my-atelier-files"
    region: "us-west-2"
    access_key: "${AWS_ACCESS_KEY}"
    secret_key: "${AWS_SECRET_KEY}"
  
  local_archive:
    enabled: true
    path: "/mnt/nas/archive/"
    
  original_file:
    action: "delete"  # 云端已备份，本地删除
    
  video:
    extract_audio: true
    extract_keyframes: true
    keyframe_interval: 300
    max_keyframes: 20
    
  pdf:
    extract_text: true
    extract_images: true
    max_images: 15
    
  notification:
    enabled: true
    on_complete: true
    on_error: true
```

---

## 总结

### 核心原则

```
1. 分离存储
   - 元数据和内容 → Git (轻量)
   - 原始大文件 → 外部存储

2. 智能提取
   - 99% 的信息在 1% 的数据里
   - 只保存关键内容

3. 灵活配置
   - 根据需求选择策略
   - 本地/云端/混合
```

### 推荐方案

```
个人用户:
  ✅ 提取关键内容 (5-10MB)
  ✅ 原始文件归档到外部硬盘
  ✅ Git 保持轻量 (<1GB)
  
团队用户:
  ✅ 提取关键内容
  ✅ 云端备份原始文件
  ✅ 按需下载
```

### 成本效益

```
存储成本:
  - 本地方案: $0 (使用现有硬盘)
  - 云存储: ~$2-5/月 (100GB)
  
空间节省:
  - 视频: 99% (1GB → 10MB)
  - PDF: 97% (200MB → 6MB)
  - 音频: 96% (500MB → 20MB)
  
Git 性能:
  - 仓库大小: <1GB (vs 100GB+)
  - Clone 时间: 1分钟 (vs 1小时)
  - 搜索速度: 毫秒级
```

---

**🎯 大文件处理不影响核心架构，只是增加了智能提取和存储管理！**
