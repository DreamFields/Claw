# 🐾 Claw - Git Commit Exporter for AI Migration

将 Git 提交的文件修改导出为 AI 友好的格式化文件，便于项目迁移时让 AI 自动识别并恢复代码变更。

## ✨ 功能特点

- 📄 **Markdown 格式导出** — AI 最容易理解和处理的格式
- 📊 **JSON 格式导出** — 机器可读的结构化格式
- 📝 **完整的提交元信息** — Hash、作者、日期、提交消息
- 🔍 **精确的 diff 内容** — 包含完整的代码差异，便于精确还原
- 📦 **新增文件完整内容** — 新添加的文件直接输出完整内容
- 🔄 **重命名/复制检测** — 自动识别文件重命名和复制操作
- 📚 **范围导出** — 支持导出一个区间内的多个提交
- 🧭 **AI 迁移指南** — 自动生成 AI 可遵循的迁移指令

## 🚀 快速开始

### 前置条件

- Python 3.10+
- Git

### 基本用法

```bash
# 导出最新一次提交
python claw.py HEAD

# 导出指定提交到文件
python claw.py abc1234 -o changes.md

# 导出为 JSON 格式
python claw.py HEAD -f json -o changes.json

# 包含变更后文件的完整内容（推荐用于复杂变更）
python claw.py HEAD --full -o changes.md

# 导出多个提交（范围）
python claw.py abc1234..def5678 -o batch_changes.md

# 指定仓库路径
python claw.py HEAD --repo /path/to/your/repo -o changes.md
```

## 📖 命令参数

| 参数 | 说明 | 默认值 |
|------|------|--------|
| `commit` | 提交哈希、引用（HEAD, HEAD~1）或范围（abc..def） | 必填 |
| `-o, --output` | 输出文件路径 | stdout |
| `-f, --format` | 输出格式: `md` 或 `json` | `md` |
| `--full` | 包含变更后文件的完整内容 | 关闭 |
| `--repo` | Git 仓库路径 | 当前目录 |
| `-v, --version` | 显示版本号 | - |

## 📋 导出格式说明

### Markdown 格式 (默认)

生成结构清晰的 Markdown 文件，包含：

1. **提交信息** — hash、作者、日期、提交消息
2. **变更摘要** — 文件变更列表表格
3. **文件变更详情** — 每个文件的 diff 或完整内容
4. **AI 迁移指南** — 指导 AI 如何应用变更

### JSON 格式

生成结构化 JSON，适合程序化处理：

```json
{
  "claw_version": "1.0.0",
  "format": "claw-json-v1",
  "commit": {
    "full_hash": "...",
    "subject": "...",
    ...
  },
  "files": [
    {
      "status": "MODIFIED",
      "path": "src/main.py",
      "diff": "..."
    }
  ]
}
```

## 🤖 AI 迁移工作流

### 导出阶段

```bash
# 在原项目中导出关键提交
python claw.py <commit_hash> --full -o migration.md
```

### 迁移阶段

将 `migration.md` 文件发送给 AI（如 ChatGPT / Claude / CodeBuddy），并使用以下提示词：

> 请阅读以下 Claw 导出文件，该文件描述了一次 Git 提交中的所有代码变更。
> 请按照文件中的指令，在当前项目中精确还原这些变更。

AI 会根据文件中的结构化信息和迁移指南自动：
- 创建新文件
- 修改已有文件
- 删除/重命名文件
- 精确应用所有 diff 变更

## 💡 使用建议

1. **复杂变更使用 `--full`** — 当 diff 难以理解时，包含完整文件内容能帮助 AI 更精确地还原
2. **大型提交分步导出** — 如果一次提交修改了大量文件，建议拆分多次应用
3. **二进制文件** — 工具会跳过无法处理的二进制文件，需要手动迁移
4. **验证导出** — 导出后可以快速浏览文件，确认内容完整

## 🧩 仓库内附带 Skills

当前仓库额外收录了两个可复用的 CodeBuddy skill：

- `skills/bilibili-notes` — 从 B 站视频提取字幕、截图并生成结构化笔记
- `skills/md2notion` — 将 Markdown 笔记和本地图片上传到 Notion

出于安全考虑，仓库已显式排除以下内容，不会被提交：

- `bilibili-notes` 下的真实 `cookie.txt`、`cookie.json`
- 所有 `node_modules`、`__pycache__`、`.env*` 等本地依赖与环境文件

## 📄 License


MIT License
