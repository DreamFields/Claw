# md2notion

把本地 Markdown 笔记和图片上传到 Notion 的 CodeBuddy skill。

它适合以下场景：

- 把带截图的技术笔记导入 Notion
- 把本地知识库内容批量同步到 Notion 页面
- 把由 AI 生成的 Markdown 文档转成 Notion 原生块结构

## 主要能力

- 启动本地 `markdown-upload-to-notion` 服务
- 收集指定目录下的 Markdown 文件与图片资源
- 把 Markdown 解析成 Notion 原生 block
- 通过 Notion File Upload API 上传图片并建立引用
- 处理大文档的分批创建与追加

## 推荐流程

1. 启动本地服务：

```bash
node scripts/start_server.js
```

2. 执行上传：

```bash
node scripts/upload.js --token <TOKEN> --parent <PAGE_ID> --dir <NOTES_DIR>
```

## 目录结构

```text
md2notion/
├── README.md
├── SKILL.md
├── .gitignore
├── assets/
├── references/
└── scripts/
    ├── start_server.js
    ├── upload.js
    ├── package.json
    └── package-lock.json
```

## 依赖

常见依赖包括：

- Node.js 14+
- 一个可用的 `markdown-upload-to-notion` 服务端项目
- Notion Integration Token
- 目标 Notion Page ID 或 Database 目标

## 安全与隐私

这个 skill 运行时会接触到：

- Notion token
- Page ID / Database ID
- 本地 Markdown 与图片内容

为了适合公开分享，仓库中**只保留脚本、说明和最小依赖清单**，不会提交真实 token、`.env`、本地服务缓存或安装产物。

## 适合谁使用

- 用 Markdown 写笔记但长期在 Notion 中整理的人
- 想把 AI 生成的文档自动同步到 Notion 的开发者
- 需要保留图片与结构化标题层级的知识库维护者

## 更多说明

- 面向 Agent 的执行说明见 `SKILL.md`
- 详细转换规则与排障说明见 `SKILL.md`
- 上传脚本与启动脚本位于 `scripts/`
