# 🧰 AI Tool Library

[![CI](https://img.shields.io/github/actions/workflow/status/DreamFields/Claw/ci.yml?branch=main&label=CI)](https://github.com/DreamFields/Claw/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](./LICENSE)
[![Stars](https://img.shields.io/github/stars/DreamFields/Claw?style=social)](https://github.com/DreamFields/Claw/stargazers)

这是一个面向 **AI 工作流 / Agent 生态** 的工具库仓库，后续会持续收录：

- `MCP/`：面向模型上下文协议的工具或集成
- `Skills/`：可复用的 Agent / CodeBuddy skill
- `Plugins/`：插件、扩展或宿主集成
- `Scripts/`：独立脚本、小工具、CLI 与自动化辅助程序

当前仓库中的代表工具是 **Claw**：一个把 Git 提交导出为 AI 易读格式的脚本，便于在迁移项目时让 AI 自动理解并恢复改动。

## ✨ 快速导航

- **Scripts**：`Scripts/claw.py`
- **Skills 索引**：[Skills/README.md](Skills/README.md)
- **B 站笔记 skill**：[Skills/bilibili-notes/README.md](Skills/bilibili-notes/README.md)
- **Markdown to Notion skill**：[Skills/md2notion/README.md](Skills/md2notion/README.md)
- **许可证**：[LICENSE](LICENSE)

## 📁 仓库结构

```text
Claw/
├── .github/
│   ├── ISSUE_TEMPLATE/
│   └── workflows/
├── MCP/
├── Plugins/
├── Scripts/
│   └── claw.py
├── Skills/
│   ├── README.md
│   ├── bilibili-notes/
│   │   ├── README.md
│   │   ├── SKILL.md
│   │   ├── .gitignore
│   │   ├── requirements.txt
│   │   ├── scripts/
│   │   ├── assets/
│   │   └── references/
│   └── md2notion/
│       ├── README.md
│       ├── SKILL.md
│       ├── .gitignore
│       ├── scripts/
│       ├── assets/
│       └── references/
├── LICENSE
└── README.md
```

## 🧭 顶层目录约定

- **`MCP/`**：放置 MCP server、桥接脚本、协议适配器或相关配置
- **`Skills/`**：放置适合公开复用的 skill，每个 skill 自带 `README.md`、`SKILL.md` 和局部忽略规则
- **`Plugins/`**：放置各类插件、IDE 集成、宿主扩展
- **`Scripts/`**：放置可独立运行的脚本和 CLI 工具

这样做的目标是：让这个仓库逐步演化成一个**面向 AI 的通用工具库**，而不是只承载单一脚本。

## 🚀 当前可用工具

### `Scripts/claw.py`

`Claw` 用于把某次 Git 提交导出为 AI 易读的结构化文件（Markdown / JSON）。

```bash
# 导出最新一次提交
python Scripts/claw.py HEAD

# 导出指定提交到 Markdown 文件
python Scripts/claw.py abc1234 -o changes.md

# 导出为 JSON
python Scripts/claw.py HEAD -f json -o changes.json

# 导出时附带变更后完整文件内容
python Scripts/claw.py HEAD --full -o migration.md
```

### `Skills/`

目前已经整理入库的 skills：

- [Skills/README.md](Skills/README.md)
- [Skills/bilibili-notes/README.md](Skills/bilibili-notes/README.md)
- [Skills/md2notion/README.md](Skills/md2notion/README.md)

## 🤖 `Claw` 的典型工作流

### 导出阶段

```bash
python Scripts/claw.py <commit_hash> --full -o migration.md
```

### 迁移阶段

把 `migration.md` 发给 AI，并附上类似提示：

> 请阅读以下 Claw 导出文件，该文件描述了一次 Git 提交中的所有代码变更。请按照文件中的指令，在当前项目中精确还原这些变更。

AI 通常可以据此：

- 创建新文件
- 修改已有文件
- 删除或重命名文件
- 逐项还原 diff 里的代码改动

## 🛠️ 开源协作支持

这个仓库当前已经包含一些基础协作设施：

- **GitHub Actions CI**：自动检查 `Scripts/claw.py`、`Skills/bilibili-notes` 下的 Python 脚本、`Skills/md2notion` 下的 Node 脚本
- **Issue 模板**：区分 bug report 与 feature request
- **统一目录分层**：方便后续继续扩展 MCP、Skills、Plugins、Scripts

## 🔐 安全说明

为了让这个仓库更适合公开分享，仓库中已显式排除以下内容：

- `Skills/bilibili-notes` 下的真实 `cookie.txt`、`cookie.json`
- 所有 `node_modules`、`__pycache__`、`.env*` 等本地依赖与环境文件
- 各 skill 运行时生成的本地输出、缓存与截图目录

如果后续继续往这个仓库收录新工具，建议保持同样策略：

- **只提交源码、文档、示例与最小依赖清单**
- **不要提交 token、cookie、缓存、输出物或本地安装目录**

## 📄 License

MIT License
