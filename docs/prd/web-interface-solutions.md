# Web 交互界面方案调研

**日期:** 2026-08-27  
**目的:** 为 Atelierr 找到合适的 Web 交互界面方案  
**用户需求:** 
- 异地访问知识管理系统
- Web 界面交互（不依赖 Obsidian 或 CLI）
- 支持飞书集成
- 开源方案
- 与其他模块完全解耦

---

## 🎯 用户需求分析

```
你的需求：
  ✅ Web 界面（随时随地访问）
  ✅ 不依赖 Obsidian 或 CLI
  ✅ 飞书集成（企业协作）
  ✅ 开源方案
  ✅ 独立模块（完全解耦）

使用场景：
  • 在公司（无法装 Obsidian）→ 用 Web 界面
  • 在手机上 → 用 Web 界面
  • 在飞书中 → 直接查询/记录
  • 在家 → 用 Obsidian（本地）

核心：需要一个"前端界面层"，与后端（$OV/ 文件系统）解耦
```

---

## 🔍 GitHub 调研结果

### Top 10 Web 知识管理界面

| 项目 | Stars | 语言 | 描述 |
|------|-------|------|------|
| **memos** | 62,578 ⭐ | Go | Self-hosted, Markdown-native note-taking |
| **logseq** | 44,649 ⭐ | Clojure | Privacy-first knowledge management platform |
| **trilium** | 37,605 ⭐ | JavaScript | Personal knowledge base |
| **siyuan** | 27,000+ ⭐ | Go/TypeScript | Privacy-first personal knowledge system |
| **flatnotes** | 3,203 ⭐ | Python | Database-less, flat folder markdown notes |
| TriliumNext/Notes | 2,927 ⭐ | JavaScript | Build personal knowledge base |
| gamosoft/NoteDiscovery | 2,773 ⭐ | - | Self-hosted knowledge base |
| kenforthewin/atomic | 1,929 ⭐ | - | Semantically-connected knowledge base |
| bangle-io | 1,230 ⭐ | - | WYSIWYG note-taking web app |

---

## 📊 重点方案深度分析

### 1. usememos/memos ⭐⭐⭐⭐⭐（最推荐）

```
GitHub: https://github.com/usememos/memos
官网: https://usememos.com
Stars: 62,578 ⭐（最高）
语言: Go
描述: Open-source, self-hosted, Markdown-native note-taking

核心特性：
  ✅ Self-hosted（自托管）
  ✅ Markdown-native（原生 Markdown）
  ✅ Web 界面（漂亮的现代 UI）
  ✅ 快速捕获（quick capture）
  ✅ RESTful API（易于集成）
  ✅ 轻量级
  ✅ Docker 部署
  ✅ 移动端友好

架构：
  Frontend（Web UI）→ Backend（Go API）→ Storage（文件系统/DB）
  
  可以改造为：
  Frontend（Web UI）→ Backend（Go API）→ $OV/（Markdown 文件）

为什么适合你？
  ✅ 62K stars（非常成熟）
  ✅ Markdown 原生（与你的设计一致）
  ✅ 轻量级（Go 单二进制）
  ✅ 漂亮的 Web UI
  ✅ API 丰富（易于集成飞书）
  ✅ 活跃维护

集成方案：
  Memos Web UI
       ↓（RESTful API）
  Memos Backend（改造）
       ↓（读写文件）
  $OV/memory/（Markdown 文件）
       ↓
  Atelierr（Python 核心）

优点：
  ✅ 成熟度最高（62K stars）
  ✅ 现代化 UI
  ✅ 移动端友好
  ✅ 轻量级（单二进制）
  ✅ Docker 一键部署
  ✅ API 完善

缺点：
  ⚠️ Go 实现（你是 Python，但可以分离部署）
  ⚠️ 需要改造后端（连接到 $OV/）
```

### 2. dullage/flatnotes ⭐⭐⭐⭐⭐（最符合需求）

```
GitHub: https://github.com/dullage/flatnotes
Stars: 3,203 ⭐
语言: Python ✅
描述: Database-less note-taking, flat folder of markdown files

核心特性：
  ✅ Python 实现（与 Atelierr 一致！）
  ✅ Database-less（无数据库）
  ✅ Flat folder markdown（平面文件夹）
  ✅ Web 界面
  ✅ 搜索功能
  ✅ 标签系统
  ✅ 简单易用

架构（完美匹配）：
  Flatnotes Web UI
       ↓（Flask/FastAPI）
  Python Backend
       ↓（直接读写）
  Markdown Files（文件夹）
  
  可以直接指向：
  $OV/memory/（Markdown 文件）

为什么最适合你？
  ✅ Python 实现（与 Atelierr 技术栈一致）
  ✅ Database-less（与你的设计一致）
  ✅ Flat folder（直接读写 $OV/）
  ✅ 轻量级
  ✅ 易于改造

集成方案（最简单）：
  1. 部署 Flatnotes
  2. 配置指向 $OV/memory/
  3. 完成！

优点：
  ✅ Python（易于集成）
  ✅ 无数据库（直接读写文件）
  ✅ 简单轻量
  ✅ 易于改造
  ✅ 3K stars（成熟）

缺点：
  ⚠️ UI 较简单（不如 Memos 漂亮）
  ⚠️ 功能相对基础
```

### 3. siyuan-note/siyuan ⭐⭐⭐⭐⭐（专业级）

```
GitHub: https://github.com/siyuan-note/siyuan
Stars: 27,000+ ⭐
语言: Go + TypeScript
描述: Privacy-first personal knowledge system

核心特性：
  ✅ 完整的知识管理系统
  ✅ 双向链接
  ✅ 块级引用
  ✅ Web + 桌面端
  ✅ 移动端支持
  ✅ Markdown 存储
  ✅ 数据库索引（性能好）
  ✅ 中文原生支持 ✅

为什么适合你？
  ✅ 27K stars（非常成熟）
  ✅ 中文社区活跃
  ✅ Web + 移动端
  ✅ 功能完整
  ✅ 本地优先

优点：
  ✅ 功能最完整
  ✅ 中文支持好
  ✅ 社区活跃
  ✅ 移动端好

缺点：
  ⚠️ 复杂（功能太多）
  ⚠️ 有自己的数据结构
  ⚠️ 改造成本高
```

### 4. logseq ⭐⭐⭐⭐

```
GitHub: https://github.com/logseq/logseq
Stars: 44,649 ⭐
语言: Clojure
描述: Privacy-first knowledge management

核心特性：
  ✅ 大纲笔记
  ✅ 双向链接
  ✅ 知识图谱
  ✅ Web + 桌面端
  ✅ 隐私优先
  ✅ Markdown 存储

优点：
  ✅ 44K stars（非常成熟）
  ✅ 功能强大
  ✅ 社区活跃

缺点：
  ⚠️ Clojure（改造难）
  ⚠️ 大纲风格（可能不适合）
  ⚠️ 复杂度高
```

---

## 🎯 最终推荐方案

### 方案 1：Flatnotes（改造版）⭐⭐⭐⭐⭐（最推荐）

#### 为什么选 Flatnotes？

```
完美匹配你的需求：

1. Python 实现 ✅
   • 与 Atelierr 技术栈一致
   • 易于改造和集成

2. Database-less ✅
   • 直接读写 Markdown 文件
   • 无需数据库同步

3. Flat folder ✅
   • 直接指向 $OV/memory/
   • 无需数据迁移

4. 轻量级 ✅
   • 简单易部署
   • 资源占用少

5. 开源 ✅
   • 3K stars（成熟）
   • MIT License
```

#### 架构设计（完全解耦）

```
┌─────────────────────────────────────────────────────────┐
│              Atelierr 完整架构（含 Web 界面）            │
├─────────────────────────────────────────────────────────┤
│                                                          │
│  [前端层] — Web Interface Module（独立模块）            │
│                                                          │
│    Flatnotes Web UI（React/Vue）                        │
│         ↓                                                │
│    Flatnotes Backend（Python/Flask）                    │
│         ↓                                                │
│    RESTful API                                           │
│         ├─ GET /notes                                    │
│         ├─ POST /notes                                   │
│         ├─ PUT /notes/:id                                │
│         └─ DELETE /notes/:id                             │
│                                                          │
│  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━  │
│                                                          │
│  [存储层] — File System（共享）                         │
│                                                          │
│    $OV/memory/                                           │
│         ├── long-term/*.md                               │
│         ├── mid-term/*.md                                │
│         └── short-term/*.md                              │
│                                                          │
│  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━  │
│                                                          │
│  [后端层] — Atelierr Core（独立模块）                   │
│                                                          │
│    scripts/memory.py                                     │
│    scripts/attention.py                                  │
│    scripts/cognition.py                                  │
│                                                          │
└─────────────────────────────────────────────────────────┘

关键：
  • Web 界面和 Atelierr Core 完全解耦
  • 两者通过文件系统交互（$OV/memory/）
  • 没有直接的代码依赖
```

#### 部署方案

```yaml
# docker-compose.yml

version: '3.8'

services:
  # Web 界面（Flatnotes 改造版）
  atelierr-web:
    image: flatnotes:latest
    ports:
      - "5000:5000"
    volumes:
      - /path/to/$OV/memory:/data
    environment:
      - FLATNOTES_PATH=/data
      - FLATNOTES_TITLE=Atelierr Memory
    restart: unless-stopped

  # 可选：反向代理（支持 HTTPS + 域名）
  nginx:
    image: nginx:alpine
    ports:
      - "443:443"
    volumes:
      - ./nginx.conf:/etc/nginx/nginx.conf
      - ./ssl:/etc/nginx/ssl
    restart: unless-stopped
```

#### 飞书集成方案

```python
# scripts/feishu_webhook.py

from flask import Flask, request, jsonify
import requests
from pathlib import Path

app = Flask(__name__)

# Flatnotes API 地址
FLATNOTES_API = "http://localhost:5000/api"

@app.route('/feishu/webhook', methods=['POST'])
def feishu_webhook():
    """
    飞书 Webhook 接收器
    
    用户在飞书中发送：
      /note 今天学习了 asyncio
    
    自动保存到 $OV/memory/
    """
    data = request.json
    
    # 解析飞书消息
    text = data.get('text', {}).get('content', '')
    
    if text.startswith('/note '):
        content = text[6:]  # 移除 '/note '
        
        # 调用 Flatnotes API 创建笔记
        response = requests.post(
            f"{FLATNOTES_API}/notes",
            json={
                "title": f"飞书记录 {datetime.now().strftime('%Y-%m-%d %H:%M')}",
                "content": content,
                "tags": ["feishu", "quick-capture"]
            }
        )
        
        return jsonify({"msg": "笔记已保存 ✅"})
    
    return jsonify({"msg": "未识别的命令"})

if __name__ == '__main__':
    app.run(port=8080)
```

#### 改造 Flatnotes（连接 $OV/）

```python
# flatnotes_adapter.py（适配器）

from pathlib import Path
import frontmatter
from datetime import datetime

class AtelierrMemoryAdapter:
    """
    Flatnotes 到 Atelierr Memory 的适配器
    
    将 Flatnotes 的操作转换为 Atelierr Memory 格式
    """
    
    def __init__(self, memory_path: str):
        self.memory_path = Path(memory_path)
    
    def create_note(self, title: str, content: str, tags: list, confidence: float = 0.5):
        """创建笔记（自动分配到合适的层）"""
        # 根据置信度分配层级
        if confidence > 0.8:
            layer = self.memory_path / "long-term" / "beliefs"
        elif confidence > 0.5:
            layer = self.memory_path / "mid-term" / "learnings"
        else:
            layer = self.memory_path / "short-term" / "observations"
        
        layer.mkdir(parents=True, exist_ok=True)
        
        # 生成文件名
        slug = title.replace(' ', '-').lower()
        filepath = layer / f"{slug}.md"
        
        # 使用 python-frontmatter
        post = frontmatter.Post(content)
        post.metadata = {
            'title': title,
            'created': datetime.now().isoformat(),
            'confidence': confidence,
            'tags': tags,
            'source': 'web'
        }
        
        # 写入文件
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(frontmatter.dumps(post))
        
        return str(filepath)
    
    def search_notes(self, query: str) -> list:
        """搜索笔记（跨所有层）"""
        results = []
        for md_file in self.memory_path.rglob("*.md"):
            with open(md_file, 'r', encoding='utf-8') as f:
                post = frontmatter.load(f)
                if query.lower() in post.content.lower():
                    results.append({
                        'path': str(md_file),
                        'title': post.metadata.get('title', md_file.stem),
                        'preview': post.content[:200],
                        'layer': md_file.parent.parent.name
                    })
        return results
```

---

### 方案 2：Memos（改造版）⭐⭐⭐⭐⭐（UI 最好）

```
如果你需要更漂亮的 UI：

优点：
  ✅ 62K stars（最成熟）
  ✅ 现代化 UI（非常漂亮）
  ✅ 移动端完美
  ✅ 功能丰富

缺点：
  ⚠️ Go 实现（需要改造后端）
  ⚠️ 改造成本中等

方案：
  • 保留 Memos 前端（UI）
  • 改造后端（连接到 $OV/）
  • 或者：写一个 Python 适配器
```

---

## 📊 方案对比总结

| 方案 | Stars | 语言 | 改造难度 | UI | 移动端 | 推荐度 |
|------|-------|------|---------|----|----|--------|
| **Flatnotes** | 3,203 | Python | 低 | 简单 | 好 | ⭐⭐⭐⭐⭐ |
| **Memos** | 62,578 | Go | 中 | 漂亮 | 完美 | ⭐⭐⭐⭐⭐ |
| **SiYuan** | 27,000+ | Go/TS | 高 | 专业 | 完美 | ⭐⭐⭐⭐ |
| **Logseq** | 44,649 | Clojure | 高 | 完整 | 好 | ⭐⭐⭐ |

---

## 🎯 最终推荐

### 推荐：Flatnotes 改造版

```
理由：
  ✅ Python 实现（与 Atelierr 一致）
  ✅ Database-less（与设计一致）
  ✅ 改造成本低（1-2 天）
  ✅ 完全解耦（独立模块）
  ✅ 轻量级
  ✅ 易于部署

实施步骤：
  Phase 1（Week 1）：
    • 部署 Flatnotes
    • 配置指向 $OV/memory/
    • 测试基本功能

  Phase 2（Week 2）：
    • 添加飞书 Webhook
    • 适配 Atelierr Memory 格式
    • 添加 Confidence 支持

  Phase 3（Week 3）：
    • 优化 UI（可选）
    • 添加移动端优化
    • 部署到生产环境
```

### 部署架构

```
用户设备：
  • 手机 → https://memory.yourdomain.com
  • 电脑（公司）→ https://memory.yourdomain.com
  • 电脑（家）→ Obsidian（本地）
  • 飞书 → Webhook → https://memory.yourdomain.com/api

服务器：
  • Flatnotes Web（Docker）
    ├─ 读写 $OV/memory/
    └─ RESTful API

  • Nginx（反向代理）
    ├─ HTTPS
    └─ 域名

  • Atelierr Core（后台）
    ├─ scripts/memory.py
    ├─ scripts/attention.py
    └─ scripts/cognition.py

关键：
  • Web 界面和 Core 完全解耦
  • 通过文件系统通信（$OV/）
  • 可以独立部署、独立升级
```

---

## 💡 飞书集成详细方案

### 1. 飞书机器人 Webhook

```python
# scripts/feishu_bot.py

import requests
from flask import Flask, request, jsonify
from pathlib import Path
import json

app = Flask(__name__)

# 飞书配置
FEISHU_APP_ID = "your_app_id"
FEISHU_APP_SECRET = "your_app_secret"

# Flatnotes API
FLATNOTES_API = "http://localhost:5000/api"

@app.route('/feishu/webhook', methods=['POST'])
def feishu_webhook():
    """接收飞书消息"""
    data = request.json
    
    # 解析消息类型
    msg_type = data.get('header', {}).get('event_type')
    
    if msg_type == 'im.message.receive_v1':
        # 获取消息内容
        content = json.loads(data.get('event', {}).get('message', {}).get('content', '{}'))
        text = content.get('text', '')
        
        # 命令解析
        if text.startswith('/note '):
            # 保存笔记
            note_content = text[6:]
            save_note(note_content)
            return jsonify({"msg": "笔记已保存 ✅"})
        
        elif text.startswith('/search '):
            # 搜索笔记
            query = text[8:]
            results = search_notes(query)
            return jsonify({"msg": format_search_results(results)})
        
        elif text.startswith('/attention'):
            # 查看今日注意力清单
            attention_list = get_attention_list()
            return jsonify({"msg": format_attention_list(attention_list)})
    
    return jsonify({"msg": "ok"})

def save_note(content: str):
    """保存笔记到 Flatnotes"""
    response = requests.post(
        f"{FLATNOTES_API}/notes",
        json={
            "title": f"飞书记录 {datetime.now().strftime('%Y-%m-%d %H:%M')}",
            "content": content,
            "tags": ["feishu", "quick-capture"]
        }
    )
    return response.json()

def search_notes(query: str):
    """搜索笔记"""
    response = requests.get(
        f"{FLATNOTES_API}/notes/search",
        params={"q": query}
    )
    return response.json()

if __name__ == '__main__':
    app.run(port=8080)
```

### 2. 飞书命令

```
用户在飞书中可以使用：

/note [内容]
  → 快速记录笔记
  → 保存到 $OV/memory/short-term/

/search [关键词]
  → 搜索记忆
  → 返回相关笔记

/attention
  → 查看今日注意力清单
  → Top 3-5 需要关注的事项

/belief [内容]
  → 创建信念
  → 保存到 $OV/cognition/beliefs/

/question [内容]
  → 记录问题
  → 保存到 $OV/cognition/questions/
```

---

## 🎯 最终架构图

```
┌─────────────────────────────────────────────────────────┐
│           Atelierr 完整系统架构（5 层）                  │
├─────────────────────────────────────────────────────────┤
│                                                          │
│  L1: 交互层（Interface Layer）— 独立模块                │
│      ├─ Obsidian（本地，桌面端）                         │
│      ├─ Flatnotes Web（异地，Web 端）                   │
│      ├─ 飞书机器人（移动，企业协作）                     │
│      └─ CLI（命令行）                                    │
│                                                          │
│  L2: API 层（API Layer）— 可选                          │
│      └─ Flatnotes Backend（RESTful API）                │
│                                                          │
│  L3: 存储层（Storage Layer）— 核心                      │
│      └─ $OV/memory/（Markdown 文件系统）                │
│          ├── long-term/*.md                              │
│          ├── mid-term/*.md                               │
│          └── short-term/*.md                             │
│                                                          │
│  L4: 逻辑层（Logic Layer）— Atelierr Core               │
│      ├─ scripts/memory.py（记忆管理）                   │
│      ├─ scripts/attention.py（注意力）                  │
│      └─ scripts/cognition.py（认知升级）                │
│                                                          │
│  L5: Agent 层（Agent Layer）— 现有 Agents               │
│      ├─ Researcher（研究）                               │
│      ├─ Synthesizer（综合）                              │
│      └─ Reader（阅读）                                   │
│                                                          │
└─────────────────────────────────────────────────────────┘

关键设计原则：
  ✅ 完全解耦（5 层独立）
  ✅ 文件系统作为中心（L3）
  ✅ 多种交互方式（L1）
  ✅ 灵活扩展（可以添加新的 L1）
```

---

**总结：推荐使用 Flatnotes 改造版作为 Web 界面，通过飞书 Webhook 集成企业协作，完全解耦的独立模块。**

这样你就可以：
- 在家用 Obsidian ✅
- 在公司/异地用 Web 界面 ✅
- 在飞书中快速记录 ✅
- 所有数据统一存储在 $OV/memory/ ✅

你觉得这个方案怎么样？😊
