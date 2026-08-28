# Atelierr 项目文档

欢迎来到 Atelierr 记忆管理系统的文档中心！

---

## 📚 文档导航

### 🚀 快速开始

```
第一次接触？从这里开始：

1. 阅读 ../README.md（5分钟了解项目）
2. 阅读 ../QUICK-START.md（10分钟跑起来）
3. 阅读 user/getting-started.md（30分钟入门）
```

---

## 📂 文档分类

### 🎨 PRD 文档（产品需求）

**位置**: `docs/prd/`  
**状态**: 🔒 已锁定（设计阶段完成）  
**用途**: 了解系统设计思路和决策过程

```
推荐阅读顺序:
  1. prd/README.md           - PRD 总索引
  2. prd/ARCHITECTURE-LOCKED-V1.md  - 核心架构
  3. prd/IMPLEMENTATION-PLAN-PARALLEL.md - 实施计划
  4. prd/*.png               - 架构图解
```

**适合人群**: 
- 想了解设计理念的开发者
- 想了解架构决策的技术负责人
- 想参与贡献的开发者

---

### 💻 开发文档（开发者）

**位置**: `docs/dev/`  
**状态**: ⚡ 持续更新  
**用途**: 参与开发、理解实现细节

```
核心文档:
  ✅ dev/setup.md           - 开发环境设置
  ✅ dev/architecture.md    - 架构说明（技术视角）
  ✅ dev/api-reference.md   - API 完整参考
  ✅ dev/testing.md         - 测试指南
  ✅ dev/contributing.md    - 贡献指南
  ✅ dev/troubleshooting.md - 问题排查
```

**适合人群**:
- 项目开发者
- 想深入了解技术实现的人
- 想贡献代码的人

---

### 👥 用户文档（使用者）

**位置**: `docs/user/`  
**状态**: ⚡ 持续更新  
**用途**: 学习如何使用系统

```
按学习顺序:
  1. user/installation.md       - 安装指南
  2. user/getting-started.md    - 入门教程
  3. user/web-interface.md      - Web 界面使用
  4. user/input-processing.md   - 输入处理指南
  5. user/memory-management.md  - 记忆管理说明
  6. user/user-guide.md         - 完整使用手册
  7. user/faq.md                - 常见问题

示例:
  user/examples/basic-workflow.md
  user/examples/video-processing.md
  user/examples/advanced-usage.md
```

**适合人群**:
- 最终用户（技术或非技术）
- 想快速上手的人
- 遇到问题需要帮助的人

---

### 🔬 设计文档（深入理解）

**位置**: `docs/design/`  
**状态**: 📝 按需编写  
**用途**: 深入理解算法和设计细节

```
技术深度文档:
  ✅ design/memory-decay-algorithm.md  - 衰减算法
  ✅ design/confidence-calculation.md  - Confidence 计算
  ✅ design/file-format.md             - 文件格式规范
```

**适合人群**:
- 想深入理解算法的人
- 想优化参数的高级用户
- 想改进算法的研究者

---

## 🎯 根据角色选择文档

### 我是新用户

```
→ ../README.md（了解项目）
→ ../QUICK-START.md（快速体验）
→ user/installation.md（正式安装）
→ user/getting-started.md（入门教程）
→ user/faq.md（遇到问题）
```

### 我是开发者（想贡献代码）

```
→ prd/README.md（了解设计）
→ dev/setup.md（设置环境）
→ dev/architecture.md（理解架构）
→ dev/contributing.md（贡献指南）
→ dev/testing.md（编写测试）
```

### 我是技术负责人（想评估项目）

```
→ prd/ARCHITECTURE-LOCKED-V1.md（核心架构）
→ prd/IMPLEMENTATION-PLAN-PARALLEL.md（实施计划）
→ dev/architecture.md（技术细节）
→ dev/api-reference.md（API 设计）
```

### 我是研究者（想了解算法）

```
→ design/confidence-calculation.md
→ design/memory-decay-algorithm.md
→ dev/api-reference.md
```

---

## 📋 文档规范

### 文档分层原则

```
1. 根目录文档
   → 快速了解项目

2. PRD 文档（docs/prd/）
   → 设计阶段文档（已锁定）

3. 开发文档（docs/dev/）
   → 开发者文档（持续更新）

4. 用户文档（docs/user/）
   → 最终用户文档

5. 设计文档（docs/design/）
   → 算法和技术深度
```

### 完整规范

详见: [DOCUMENTATION-STRUCTURE.md](./DOCUMENTATION-STRUCTURE.md)

---

## 🔄 文档状态

### 当前进度

```
✅ PRD 文档          - 100%（已锁定）
⏳ 开发文档          - 待开发时编写
⏳ 用户文档          - 待功能完成后编写
⏳ 设计文档          - 按需编写
```

### 更新频率

```
PRD 文档:
  - 已锁定，不再更新

开发文档:
  - 代码变化立即更新
  - API 自动生成

用户文档:
  - 功能完成后更新
  - 用户反馈后改进

设计文档:
  - 需要时编写
  - 算法变化时更新
```

---

## 🛠️ 文档工具

### 本地查看

```bash
# 在浏览器中查看 Markdown
# 推荐工具:
- Typora
- Obsidian
- VS Code + Markdown Preview

# 或使用文档网站（可选）
pip install mkdocs
mkdocs serve
# 访问 http://localhost:8000
```

### 生成 PDF（可选）

```bash
# 安装 pandoc
sudo apt install pandoc

# 生成 PDF
pandoc README.md -o README.pdf
```

---

## 💡 如何贡献文档

### 发现文档问题

```
1. 提交 Issue:
   - 标题: [文档] 简短描述
   - 内容: 哪个文档，什么问题

2. 直接提 PR:
   - 修改对应文档
   - 说明修改原因
   - 提交 Pull Request
```

### 改进文档

```
欢迎：
  ✅ 修正错别字
  ✅ 改进表述
  ✅ 添加示例
  ✅ 补充说明
  ✅ 更新过期内容

请遵守:
  ✅ Markdown 规范
  ✅ 文档结构规范
  ✅ 清晰的提交信息
```

---

## 📞 获取帮助

### 文档相关问题

```
1. 查看 user/faq.md
2. 查看 dev/troubleshooting.md
3. 提交 Issue（标签: documentation）
4. 在讨论区提问
```

### 快速链接

```
- GitHub Issues: https://github.com/your-repo/issues
- 讨论区: https://github.com/your-repo/discussions
- 邮件: your-email@example.com
```

---

## 🎉 总结

### 文档结构清晰

```
根目录/          → 快速了解
docs/prd/        → 设计文档（已锁定）
docs/dev/        → 开发文档（持续更新）
docs/user/       → 用户文档
docs/design/     → 技术深度
```

### 各取所需

```
新用户      → user/ 目录
开发者      → dev/ 目录
技术评估    → prd/ 目录
算法研究    → design/ 目录
```

### 持续改进

```
✅ 欢迎反馈
✅ 欢迎贡献
✅ 持续更新
```

---

**📚 选择你需要的文档，开始探索吧！**
