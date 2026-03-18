# 🐾 Claw

`Claw` 是一个面向 **AI 辅助迁移** 的 Git 提交导出工具，同时这个仓库也整理收录了一组可复用的 CodeBuddy skills，方便公开分享、二次开发和直接复用。

## ✨ 仓库包含什么

- `claw.py`：将某次 Git 提交导出为 AI 易读的结构化文件（Markdown / JSON）
- `skills/`：整理后的公开 skill 集合，目前包含：
  - `bilibili-notes`：从 B 站视频提取字幕、截图并生成结构化技术笔记
  - `md2notion`：将 Markdown 笔记与本地图片上传到 Notion

## 📁 仓库结构

```text
Claw/
├── claw.py
├── README.md
└── skills/
    ├── README.md
    ├── bilibili-notes/
    │   ├── README.md
    │   ├── SKILL.md
    │   ├── .gitignore
    │   ├── scripts/
    │   ├── assets/
    │   └── references/
    └── md2notion/
        ├── README.md
        ├── SKILL.md
        ├── .gitignore
        ├── scripts/
        ├── assets/
        └── references/
```

## 🚀 快速开始

### 使用 `Claw` 导出提交

```bash
# 导出最新一次提交
python claw.py HEAD

# 导出指定提交到 Markdown 文件
python claw.py abc1234 -o changes.md

# 导出为 JSON
python claw.py HEAD -f json -o changes.json

# 导出时附带变更后完整文件内容
python claw.py HEAD --full -o migration.md
```

### 使用仓库里的公开 skills

先查看 skills 总览：

- [skills/README.md](skills/README.md)

然后进入具体 skill：

- [skills/bilibili-notes/README.md](skills/bilibili-notes/README.md)
- [skills/md2notion/README.md](skills/md2notion/README.md)

## 📖 `Claw` 功能特点

- 📄 **Markdown 格式导出**：适合直接交给 AI 理解和执行
- 📊 **JSON 格式导出**：适合程序化处理或二次集成
- 📝 **完整提交元信息**：包含 hash、作者、日期、提交消息
- 🔍 **精确 diff 内容**：便于 AI 按改动逐项还原
- 📦 **新增文件完整内容**：有利于 AI 直接创建新文件
- 🔄 **重命名 / 复制检测**：更完整表达一次提交中的结构变更
- 🧭 **AI 迁移指南**：输出中自动附带还原建议

## 🤖 AI 迁移工作流

### 导出阶段

```bash
python claw.py <commit_hash> --full -o migration.md
```

### 迁移阶段

把 `migration.md` 发给 AI，并附上类似提示：

> 请阅读以下 Claw 导出文件，该文件描述了一次 Git 提交中的所有代码变更。请按照文件中的指令，在当前项目中精确还原这些变更。

AI 通常可以据此：

- 创建新文件
- 修改已有文件
- 删除或重命名文件
- 逐项还原 diff 里的代码改动

## 🔐 安全说明

为了让这个仓库更适合公开分享，仓库中已显式排除以下内容：

- `bilibili-notes` 下的真实 `cookie.txt`、`cookie.json`
- 所有 `node_modules`、`__pycache__`、`.env*` 等本地依赖与环境文件
- 各 skill 运行时生成的本地输出、缓存与截图目录

如果你要继续往这个仓库收录新的 skill，建议保持同样策略：

- **只提交源码、文档、示例与最小依赖清单**
- **不要提交 token、cookie、缓存、输出物或本地安装目录**

## 📄 License

MIT License
