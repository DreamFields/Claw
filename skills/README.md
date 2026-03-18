# Skills Collection

这个目录整理了当前仓库中适合公开分享的 CodeBuddy skills。

## 收录列表

| Skill | 用途 | 主要技术 | 文档 |
|---|---|---|---|
| `bilibili-notes` | 从 B 站视频生成结构化笔记、截图与学习资料 | Python、Bilibili API、yt-dlp、ffmpeg、OpenAI | [README](./bilibili-notes/README.md) |
| `md2notion` | 将 Markdown 笔记和本地图片上传到 Notion | Node.js、Notion API、本地上传服务 | [README](./md2notion/README.md) |

## 目录约定

每个 skill 目录保持统一结构：

```text
<skill>/
├── README.md      # 面向公开仓库访客的说明
├── SKILL.md       # 面向 CodeBuddy / Agent 的触发与执行说明
├── .gitignore     # 局部敏感文件与运行产物忽略规则
├── scripts/       # 实际脚本
├── assets/        # 示例资源
└── references/    # 参考文档
```

## 公开分享原则

为保证仓库适合直接公开：

- **保留**：源码、脚本、说明文档、参考资料、示例资源、最小依赖清单
- **排除**：cookie、token、`.env*`、`node_modules`、缓存、运行输出、截图结果
- **推荐**：每个 skill 都提供独立 `README.md`，让仓库访客不必先理解 `SKILL.md`

## 如何继续扩展

如果你后续还想把更多 skill 放进这个仓库，建议遵循以下规则：

1. 新建 `skills/<skill-name>/`
2. 保留 `SKILL.md` 作为 Agent 指令入口
3. 补一个面向公开读者的 `README.md`
4. 为该 skill 单独写 `.gitignore`，避免误提交本地产物
5. 在本页增加一行索引，方便浏览和分享
