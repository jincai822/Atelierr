# 多模态输入处理 - 实际示例

本文档展示各种输入类型的实际处理示例。

---

## 示例 1: 微信聊天记录

### 输入

```
用户导出微信聊天记录（文本格式）:

===================
与张三的聊天记录
2026-08-27

14:30 我: 最近在用 asyncio，发现 CPU 密集型任务很慢
14:32 张三: 对的，asyncio 是为 I/O 设计的
14:33 我: 那怎么办？
14:35 张三: CPU 密集型用 multiprocessing
14:36 张三: [图片]
14:37 我: 明白了，我试试
===================
```

### 处理命令

```bash
python scripts/input_processor.py \
  --type wechat \
  --input ~/Downloads/wechat-chat-zhangsan.txt
```

### 输出文件

**$OV/memory/short-term/observations/2026-08-27-asyncio-discussion.md**

```markdown
---
title: 与张三讨论 asyncio 性能问题
created: 2026-08-27T14:30:00+08:00
source: wechat
confidence: 0.4
participants: ["我", "张三"]
tags: ["对话", "asyncio", "性能"]
duration_minutes: 7
---

# 微信对话 - asyncio 性能讨论

## 上下文

与张三讨论了 asyncio 在 CPU 密集型任务中的性能问题。

## 关键要点

1. **问题**: asyncio 处理 CPU 密集型任务很慢
2. **原因**: asyncio 是为 I/O 密集型任务设计的
3. **解决方案**: CPU 密集型任务应该使用 multiprocessing

## 对话记录

**14:30 我**: 最近在用 asyncio，发现 CPU 密集型任务很慢

**14:32 张三**: 对的，asyncio 是为 I/O 设计的

**14:33 我**: 那怎么办？

**14:35 张三**: CPU 密集型用 multiprocessing

**14:36 张三**: [分享了代码示例]

![代码示例](attachments/wechat-image-1.jpg)

**14:37 我**: 明白了，我试试

## 行动项

- [ ] 测试 multiprocessing 性能
- [ ] 重构现有 asyncio 代码
- [ ] 阅读 multiprocessing 文档

## 相关笔记

- [[Python 并发编程]]
- [[AsyncIO 最佳实践]]

## 元数据

- **对话时长**: 7 分钟
- **参与者**: 我, 张三
- **主题**: Python, asyncio, 性能优化
```

---

## 示例 2: 抖音学习视频

### 输入

```
抖音链接:
https://v.douyin.com/Python-performance-5-tips/

视频信息:
- 标题: Python 性能优化 5 个技巧
- 作者: Python小课堂
- 时长: 3分12秒
- 发布: 2026-08-25
```

### 处理命令

```bash
python scripts/input_processor.py \
  --type link \
  --url "https://v.douyin.com/Python-performance-5-tips/" \
  --download-video  # 可选：下载视频到本地
```

### 输出文件

**$OV/memory/short-term/observations/2026-08-27-python-performance-tips.md**

```markdown
---
title: Python 性能优化 5 个技巧 (抖音)
created: 2026-08-27T16:00:00+08:00
source: link
platform: douyin
url: https://v.douyin.com/Python-performance-5-tips/
confidence: 0.5
tags: ["视频", "Python", "性能优化", "教程"]
duration: 192
author: "Python小课堂"
publish_date: "2026-08-25"
---

# Python 性能优化 5 个技巧

## 视频信息

- **平台**: 抖音
- **作者**: Python小课堂
- **时长**: 3分12秒
- **发布日期**: 2026-08-25
- **原始链接**: https://v.douyin.com/Python-performance-5-tips/

## 内容摘要

视频介绍了 5 个实用的 Python 性能优化技巧，适合日常开发使用。

## 5 个技巧详解

### 1. 使用内置函数代替循环 (00:30)

**问题代码**:
```python
result = []
for i in my_list:
    result.append(i * 2)
```

**优化代码**:
```python
result = list(map(lambda x: x * 2, my_list))
```

**性能提升**: 10-20%

---

### 2. 列表推导式比 for 循环快 (01:00)

**问题代码**:
```python
squares = []
for x in range(1000):
    squares.append(x**2)
```

**优化代码**:
```python
squares = [x**2 for x in range(1000)]
```

**性能提升**: 20-30%

---

### 3. 避免全局变量 (01:30)

全局变量查找比局部变量慢，尽量使用函数参数和局部变量。

---

### 4. 使用局部变量缓存 (02:00)

**问题代码**:
```python
for i in range(len(my_list)):
    process(my_list[i])
```

**优化代码**:
```python
for item in my_list:
    process(item)
```

---

### 5. 使用生成器节省内存 (02:30)

**问题代码**:
```python
def get_numbers():
    return [i for i in range(1000000)]
```

**优化代码**:
```python
def get_numbers():
    return (i for i in range(1000000)  # 生成器
```

**内存节省**: 显著

## 关键见解

- ✅ 内置函数用 C 实现，性能远超 Python 循环
- ✅ 列表推导式不仅代码简洁，而且执行更快
- ✅ 全局变量查找涉及额外的字典操作
- ✅ 直接迭代容器比索引访问快
- ✅ 生成器延迟计算，节省内存

## 行动项

- [ ] 审查现有代码，寻找可优化点
- [ ] 将频繁使用的循环改为列表推导式
- [ ] 检查是否有不必要的全局变量
- [ ] 考虑在大数据处理时使用生成器

## 相关笔记

- [[Python 性能优化指南]]
- [[列表推导式最佳实践]]
- [[生成器与迭代器]]

## 本地视频

如果下载了视频，可以在这里观看:

[观看本地视频](attachments/douyin-python-tips.mp4)

## 完整转录

00:00 - 大家好，今天分享 Python 性能优化的 5 个技巧

00:15 - 这些技巧简单实用，马上可以用到你的项目中

00:30 - 第一个技巧：使用内置函数代替循环
       比如 map、filter、sum 这些内置函数...

01:00 - 第二个技巧：列表推导式
       不仅代码更简洁，而且性能更好...

01:30 - 第三个技巧：避免全局变量
       全局变量的查找速度比局部变量慢...

02:00 - 第四个技巧：使用局部变量缓存
       避免重复的属性查找和索引访问...

02:30 - 第五个技巧：使用生成器
       处理大量数据时可以节省内存...

03:00 - 今天的分享就到这里，记得点赞关注！
```

---

## 示例 3: 代码截图

### 输入

用户上传一张代码截图：

![代码截图示例](https://via.placeholder.com/800x600/1E293B/F8FAFC?text=Code+Screenshot)

### 处理命令

```bash
python scripts/input_processor.py \
  --type image \
  --input ~/Pictures/code-screenshot.jpg
```

### 输出文件

**$OV/memory/short-term/observations/2026-08-27-code-screenshot.md**

```markdown
---
title: 代码截图 - multiprocessing 性能测试
created: 2026-08-27T17:00:00+08:00
source: image
confidence: 0.3
tags: ["截图", "代码", "multiprocessing"]
ocr_confidence: 0.92
---

# 代码截图 - multiprocessing 性能测试

## 原始图片

![代码截图](attachments/code-screenshot.jpg)

## OCR 提取的代码

```python
import time
from multiprocessing import Pool

def cpu_bound_task(n):
    """CPU 密集型任务"""
    return sum(i * i for i in range(n))

def main():
    # 测试单进程
    start = time.time()
    results = [cpu_bound_task(10000000) for _ in range(8)]
    single_time = time.time() - start
    print(f"单进程: {single_time:.2f}s")
    
    # 测试多进程
    start = time.time()
    with Pool(8) as p:
        results = p.map(cpu_bound_task, [10000000] * 8)
    multi_time = time.time() - start
    print(f"多进程: {multi_time:.2f}s")
    
    print(f"加速比: {single_time / multi_time:.2f}x")

if __name__ == '__main__':
    main()
```

## 代码分析

### 功能

这段代码对比了单进程和多进程处理 CPU 密集型任务的性能差异。

### 关键点

1. **任务类型**: CPU 密集型（数学计算）
2. **测试方法**: 8 个相同任务的执行时间对比
3. **多进程实现**: 使用 `multiprocessing.Pool`
4. **性能指标**: 加速比（单进程时间 / 多进程时间）

### 预期结果

在 8 核 CPU 上，多进程版本应该有接近 8x 的加速比（理想情况）。

实际加速比可能在 6-7x（考虑进程创建开销和通信成本）。

## 学习要点

- ✅ `multiprocessing.Pool` 适合批量相似任务
- ✅ CPU 密集型任务应该使用多进程而非 asyncio
- ✅ 进程数通常设置为 CPU 核心数
- ✅ 使用 `if __name__ == '__main__':` 保护入口

## 改进建议

### 1. 添加更详细的性能分析

```python
import psutil

def main():
    cpu_count = psutil.cpu_count()
    print(f"CPU 核心数: {cpu_count}")
    
    # ... 测试代码 ...
    
    print(f"CPU 使用率: {psutil.cpu_percent()}%")
```

### 2. 测试不同进程数的效果

```python
for num_processes in [1, 2, 4, 8, 16]:
    with Pool(num_processes) as p:
        start = time.time()
        results = p.map(cpu_bound_task, [10000000] * 8)
        elapsed = time.time() - start
        print(f"{num_processes} 进程: {elapsed:.2f}s")
```

## 相关笔记

- [[Python 多进程编程]]
- [[CPU vs IO 密集型任务]]
- [[性能测试最佳实践]]

## 行动项

- [ ] 在自己的项目中实现这个性能对比
- [ ] 测试不同任务大小的影响
- [ ] 记录实际的加速比数据

## 元数据

- **OCR 置信度**: 92%
- **代码语言**: Python
- **主题**: 性能测试, 多进程
- **图片尺寸**: 1920x1080
```

---

## 示例 4: YouTube 技术讲座

### 输入

```
YouTube 链接:
https://www.youtube.com/watch?v=example-async-talk

视频信息:
- 标题: Understanding Python AsyncIO
- 作者: PyCon 2024
- 时长: 45:23
- 字幕: 英文（自动生成）
```

### 处理命令

```bash
python scripts/input_processor.py \
  --type link \
  --url "https://www.youtube.com/watch?v=example-async-talk" \
  --extract-chapters  # 提取章节
```

### 输出文件

**$OV/memory/mid-term/learnings/2026-08-27-understanding-asyncio.md**

```markdown
---
title: Understanding Python AsyncIO (PyCon 2024)
created: 2026-08-27T18:00:00+08:00
source: link
platform: youtube
url: https://www.youtube.com/watch?v=example-async-talk
confidence: 0.6
tags: ["视频", "讲座", "asyncio", "python", "pycon"]
duration: 2723
author: "PyCon 2024"
language: "en"
has_slides: true
---

# Understanding Python AsyncIO

## 讲座信息

- **会议**: PyCon 2024
- **讲者**: David Beazley
- **时长**: 45分23秒
- **难度**: 中级
- **语言**: 英文
- **原始链接**: https://www.youtube.com/watch?v=example-async-talk

## 章节目录

1. [00:00] 介绍和动机
2. [05:30] 什么是 AsyncIO
3. [12:45] Event Loop 工作原理
4. [20:15] async/await 语法详解
5. [28:30] 常见陷阱和误区
6. [35:00] 性能对比实验
7. [42:00] 总结和 Q&A

## 核心内容摘要

### 1. AsyncIO 的本质 (05:30)

AsyncIO 不是真正的并发，而是**协作式多任务**（cooperative multitasking）。

关键概念:
- **Event Loop**: 事件循环，协调所有异步任务
- **Coroutine**: 协程，可以暂停和恢复的函数
- **Task**: 被调度的协程

```python
# 传统同步代码
def fetch_data():
    response = requests.get(url)  # 阻塞
    return response.json()

# AsyncIO 异步代码
async def fetch_data():
    response = await aiohttp.get(url)  # 非阻塞
    return await response.json()
```

### 2. Event Loop 详解 (12:45)

Event Loop 的工作流程:

```
1. 检查是否有就绪的任务
2. 运行一个就绪任务直到它 await
3. 任务挂起，切换到下一个任务
4. 重复 1-3
```

**关键点**: 只有在 `await` 时才会切换任务！

### 3. 常见陷阱 (28:30)

#### 陷阱 1: 在异步函数中调用同步阻塞代码

```python
# ❌ 错误
async def bad_example():
    time.sleep(5)  # 阻塞整个 Event Loop！
    
# ✅ 正确
async def good_example():
    await asyncio.sleep(5)  # 让出控制权
```

#### 陷阱 2: CPU 密集型任务

```python
# ❌ AsyncIO 不适合
async def cpu_task():
    result = sum(i**2 for i in range(10000000))  # CPU 密集
    return result

# ✅ 应该使用
from concurrent.futures import ProcessPoolExecutor

async def cpu_task():
    with ProcessPoolExecutor() as executor:
        result = await loop.run_in_executor(
            executor, heavy_computation
        )
    return result
```

#### 陷阱 3: 忘记 await

```python
# ❌ 错误 - 返回 coroutine 对象，不执行
async def main():
    fetch_data()  # 没有 await
    
# ✅ 正确
async def main():
    await fetch_data()
```

### 4. 性能对比实验 (35:00)

讲者展示了三种方案的性能对比：

| 方案 | 100 个请求耗时 | 适用场景 |
|------|---------------|---------|
| 同步 requests | 150s | 单个请求 |
| AsyncIO aiohttp | 3s | I/O 密集 |
| multiprocessing | 145s | CPU 密集 |

**结论**: AsyncIO 对 I/O 密集型任务有 50x 的加速！

## 关键见解

1. **AsyncIO 适合 I/O 密集型任务**
   - 网络请求
   - 数据库查询
   - 文件读写（异步 I/O）

2. **AsyncIO 不适合 CPU 密集型任务**
   - 数学计算
   - 数据处理
   - 加密解密

3. **混合使用策略**
   - I/O: AsyncIO
   - CPU: ProcessPoolExecutor
   - 通过 `run_in_executor` 桥接

4. **调试建议**
   - 使用 `asyncio.create_task()` 创建任务
   - 使用 `asyncio.gather()` 等待多个任务
   - 启用 debug 模式: `asyncio.run(main(), debug=True)`

## 代码示例（讲座中的完整例子）

```python
import asyncio
import aiohttp
import time

async def fetch_url(session, url):
    """获取单个 URL"""
    async with session.get(url) as response:
        return await response.text()

async def main():
    """并发获取多个 URL"""
    urls = [f'http://example.com/{i}' for i in range(100)]
    
    async with aiohttp.ClientSession() as session:
        tasks = [fetch_url(session, url) for url in urls]
        results = await asyncio.gather(*tasks)
    
    return results

if __name__ == '__main__':
    start = time.time()
    results = asyncio.run(main())
    print(f"Total time: {time.time() - start:.2f}s")
```

## Q&A 精选 (42:00)

**Q: AsyncIO 和多线程有什么区别？**

A: 
- AsyncIO: 单线程，协作式，开销小
- 多线程: 多线程，抢占式，开销大
- AsyncIO 更适合 I/O 密集型，线程适合需要真正并行的场景

**Q: 什么时候应该用 AsyncIO？**

A: 三个条件都满足时：
1. 大量 I/O 操作
2. 这些操作可以并发
3. 使用支持 async 的库（aiohttp, asyncpg, etc.）

## 行动项

- [ ] 重新审视项目中的 I/O 操作
- [ ] 评估 AsyncIO 的适用性
- [ ] 学习 aiohttp 和 asyncpg
- [ ] 实践混合 AsyncIO + ProcessPool

## 相关资源

- [讲座幻灯片](https://example.com/slides.pdf)
- [示例代码仓库](https://github.com/example/asyncio-examples)
- [[Python AsyncIO 官方文档]]
- [[David Beazley 其他讲座]]

## 本地视频

如果下载了视频和字幕:

- [观看视频](attachments/pycon-asyncio-talk.mp4)
- [英文字幕](attachments/subtitles-en.srt)
- [讲座幻灯片](attachments/slides.pdf)
```

---

## 示例 5: 语音备忘录

### 输入

用户录制了一段语音备忘录（5分钟）

### 处理命令

```bash
python scripts/input_processor.py \
  --type audio \
  --input ~/Voice_Memos/idea-2026-08-27.m4a
```

### 输出文件

**$OV/memory/short-term/ideas/2026-08-27-voice-memo.md**

```markdown
---
title: 语音备忘 - 新项目想法
created: 2026-08-27T20:00:00+08:00
source: audio
confidence: 0.4
tags: ["语音", "想法", "项目"]
duration: 300
transcription_confidence: 0.88
---

# 语音备忘录 - 新项目想法

## 音频信息

- **时长**: 5分钟
- **录制时间**: 2026-08-27 20:00
- **转录置信度**: 88%

## 完整转录

今天突然有个想法，我想做一个记忆管理系统。

现在的问题是，我记录了很多笔记，但是时间久了就忘记了。很多重要的想法和学到的东西，都埋在笔记里，找不到了。

我希望有个系统能够：

第一，自动管理笔记的生命周期。不重要的笔记自动删除，重要的笔记保留下来。

第二，根据置信度分层。就像人的记忆一样，有短期记忆、中期记忆、长期记忆。

第三，支持多种输入方式。不只是文字，还要支持语音、图片、视频。因为很多时候灵感来了，我不想打字，我想直接说或者拍照。

第四，和我现有的反思系统集成。我已经有一套 Agent 系统了，希望能复用这些 Agent。

技术方面，我想用三层架构：
- Web 界面负责交互
- 中间有个记忆模块负责管理
- 底层是现有的 Agent 系统

关键是要用 Confidence-based 的衰减机制。比如一个笔记，如果长时间不访问，Confidence 就降低，最后自动删除。但是如果经常访问，Confidence 就提高，保留下来。

我觉得这个想法挺有意思的，明天开始设计一下。

## 结构化提取

### 核心问题

现有笔记系统的问题：
1. 笔记越来越多
2. 重要内容被埋没
3. 找不到历史笔记
4. 缺乏主动管理

### 期望功能

1. **自动生命周期管理**
   - 不重要的笔记自动删除
   - 重要的笔记保留

2. **分层存储**
   - 短期记忆
   - 中期记忆
   - 长期记忆

3. **多模态输入**
   - 文字
   - 语音
   - 图片
   - 视频

4. **与现有系统集成**
   - 复用 Agent 系统

### 技术架构

```
三层架构:
  ├── Web 界面（交互）
  ├── 记忆模块（管理）
  └── Agent 系统（现有）
```

### 核心机制

**Confidence-based 衰减**:
- 不访问 → Confidence 降低 → 最终删除
- 频繁访问 → Confidence 提高 → 保留

### 下一步行动

- [ ] 详细设计架构
- [ ] 选择技术栈
- [ ] 开始实现

## 相关笔记

- [[记忆管理系统设计]]
- [[Confidence 机制设计]]
- [[多模态输入处理]]

## 元数据

- **音频文件**: [原始录音](attachments/voice-memo.m4a)
- **转录方法**: Whisper (本地)
- **语言**: 中文
- **情绪**: 兴奋
```

---

## 总结

所有这些不同格式的输入，最终都转化为：

```
统一格式:
  content.md (Markdown 文件)
  + 
  attachments/ (附件文件夹)
  
↓

进入现有系统:
  Web 界面 → 记忆模块 → Agents
```

**关键优势**: 
- ✅ 保持架构简单
- ✅ 所有内容人类可读
- ✅ 可以手动编辑
- ✅ Git 可追踪
