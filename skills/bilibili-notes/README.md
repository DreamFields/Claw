# bilibili-notes

把 B 站视频整理成 **结构化技术笔记** 的 CodeBuddy skill。

它适合以下场景：

- 从 B 站技术视频生成学习笔记
- 提取字幕并按时间片段做总结
- 从视频中自动抓取关键截图并插入到笔记中
- 生成便于复习、分享或再次加工的 Markdown 文档

## 主要能力

- 解析 B 站视频链接、短链和 BV 号
- 提取字幕并按时间片段切分
- 调用 LLM 生成分段总结和结构化主题
- 使用 `yt-dlp` + `ffmpeg` 密集抓帧
- 用感知哈希去重，减少重复截图
- 自动把截图按主题权重插入最终 Markdown

## 推荐入口

优先使用：

```bash
python scripts/smart_notes_pipeline.py <video_url_or_bvid> --output-dir <output_dir>
```

这条命令会串起整个 3 步流程：

1. **切片总结**：按时间段切分字幕并逐段总结
2. **并行抓帧**：对视频关键区间抓帧并去重
3. **插图组装**：把截图按主题分配后插入笔记

## 目录结构

```text
bilibili-notes/
├── README.md
├── SKILL.md
├── .gitignore
├── assets/
├── references/
└── scripts/
    ├── extract_subtitles.py
    ├── capture_screenshots.py
    ├── generate_notes.py
    ├── smart_notes_pipeline.py
    └── get_bilibili_cookie.py
```

## 依赖

常见依赖包括：

- Python 3.10+
- `requests`
- `Pillow`
- `yt-dlp`
- `imageio-ffmpeg`
- `openai`（可选，用于 LLM 总结）
- `playwright`（可选，用于获取登录 cookie）

你可以直接安装仓库内附带的依赖清单：

```bash
pip install -r requirements.txt
```


## 安全与隐私

这个 skill 运行时可能会使用：

- `BILIBILI_COOKIE`
- 本地 `cookie.txt` / `cookie.json`
- `OPENAI_API_KEY`

为了适合公开分享，仓库中**不会提交真实 cookie、token 或本地运行输出**。如果你在本地使用，请自行配置，并确保不要把这些文件提交到版本库。

## 适合谁使用

- 想把长视频快速整理成笔记的开发者
- 需要做课程复盘、知识整理或团队分享的人
- 想把视频内容转成 Markdown 再继续交给 AI 加工的人

## 更多说明

- 面向 Agent 的触发与执行说明见 `SKILL.md`
- 具体脚本实现位于 `scripts/`
- 参考资料见 `references/`
