#!/usr/bin/env python3
"""
Claw - Git Commit Exporter for AI Migration

将 Git 提交的文件修改导出为 AI 友好的格式化文件，
便于后续迁移项目时让 AI 自动识别并恢复代码变更。

用法:
    python claw.py <commit_hash> [options]
    python claw.py <commit_hash1>..<commit_hash2> [options]  # 导出范围内的提交
"""

import subprocess
import sys
import os
import argparse
import json
from datetime import datetime
from pathlib import Path
from typing import Optional


# ─── 版本 ───────────────────────────────────────────────────────────
__version__ = "1.0.0"


# ─── Git 操作封装 ───────────────────────────────────────────────────
class GitOperator:
    """封装所有 Git 命令调用"""

    def __init__(self, repo_path: str = "."):
        self.repo_path = os.path.abspath(repo_path)
        self._validate_repo()

    def _validate_repo(self):
        """验证目录是否为有效的 Git 仓库"""
        try:
            self._run_git("rev-parse", "--git-dir")
        except RuntimeError:
            raise RuntimeError(f"'{self.repo_path}' 不是一个有效的 Git 仓库")

    def _run_git(self, *args: str) -> str:
        """执行 Git 命令并返回输出"""
        cmd = ["git", "-C", self.repo_path] + list(args)
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
            )
            if result.returncode != 0:
                raise RuntimeError(f"Git 命令失败: {' '.join(cmd)}\n{result.stderr}")
            return result.stdout.strip()
        except FileNotFoundError:
            raise RuntimeError("未找到 git 命令，请确保 Git 已安装并在 PATH 中")

    def get_commit_info(self, commit_hash: str) -> dict:
        """获取提交的元信息"""
        fmt = "%H%n%h%n%an%n%ae%n%ai%n%s%n%b"
        output = self._run_git("log", "-1", f"--format={fmt}", commit_hash)
        lines = output.split("\n")
        return {
            "full_hash": lines[0],
            "short_hash": lines[1],
            "author_name": lines[2],
            "author_email": lines[3],
            "date": lines[4],
            "subject": lines[5],
            "body": "\n".join(lines[6:]).strip(),
        }

    def get_changed_files(self, commit_hash: str) -> list[dict]:
        """获取提交中变更的文件列表及其状态"""
        output = self._run_git(
            "diff-tree", "--no-commit-id", "-r", "--name-status", "-M", "-C",
            commit_hash
        )
        if not output:
            return []

        files = []
        for line in output.split("\n"):
            if not line.strip():
                continue
            parts = line.split("\t")
            status_code = parts[0]

            if status_code.startswith("R"):
                # 重命名: R100\told_name\tnew_name
                score = status_code[1:] if len(status_code) > 1 else "100"
                files.append({
                    "status": "RENAMED",
                    "old_path": parts[1],
                    "new_path": parts[2],
                    "similarity": f"{score}%",
                })
            elif status_code.startswith("C"):
                # 复制: C100\told_name\tnew_name
                score = status_code[1:] if len(status_code) > 1 else "100"
                files.append({
                    "status": "COPIED",
                    "old_path": parts[1],
                    "new_path": parts[2],
                    "similarity": f"{score}%",
                })
            else:
                status_map = {
                    "A": "ADDED",
                    "M": "MODIFIED",
                    "D": "DELETED",
                    "T": "TYPE_CHANGED",
                }
                files.append({
                    "status": status_map.get(status_code, f"UNKNOWN({status_code})"),
                    "path": parts[1],
                })
        return files

    def get_file_diff(self, commit_hash: str, file_path: str) -> str:
        """获取单个文件的 diff"""
        try:
            output = self._run_git(
                "diff", f"{commit_hash}~1", commit_hash, "--", file_path
            )
            return output
        except RuntimeError:
            # 如果是初始提交，没有父提交
            try:
                output = self._run_git(
                    "diff", "--no-index", "/dev/null", file_path
                )
                return output
            except RuntimeError:
                return self._run_git(
                    "show", f"{commit_hash}:{file_path}"
                )

    def get_full_diff(self, commit_hash: str) -> str:
        """获取完整的 diff"""
        try:
            return self._run_git(
                "diff", f"{commit_hash}~1", commit_hash, "-M", "-C"
            )
        except RuntimeError:
            # 初始提交
            return self._run_git(
                "diff-tree", "-p", "--root", commit_hash
            )

    def get_file_content_at_commit(self, commit_hash: str, file_path: str) -> Optional[str]:
        """获取某次提交时文件的内容"""
        try:
            return self._run_git("show", f"{commit_hash}:{file_path}")
        except RuntimeError:
            return None

    def get_file_content_before_commit(self, commit_hash: str, file_path: str) -> Optional[str]:
        """获取提交之前文件的内容"""
        try:
            return self._run_git("show", f"{commit_hash}~1:{file_path}")
        except RuntimeError:
            return None

    def get_commit_range(self, range_spec: str) -> list[str]:
        """获取范围内的提交列表（从旧到新）"""
        output = self._run_git("log", "--reverse", "--format=%H", range_spec)
        if not output:
            return []
        return output.split("\n")


# ─── 导出格式化器 ──────────────────────────────────────────────────
class ClawExporter:
    """将 Git 提交信息导出为 AI 友好的格式"""

    def __init__(self, git: GitOperator, include_full_content: bool = False):
        self.git = git
        self.include_full_content = include_full_content

    def export_commit(self, commit_hash: str) -> str:
        """导出单个提交"""
        info = self.git.get_commit_info(commit_hash)
        changed_files = self.git.get_changed_files(commit_hash)

        sections = []
        sections.append(self._render_header(info))
        sections.append(self._render_summary(changed_files))
        sections.append(self._render_file_changes(commit_hash, changed_files))
        sections.append(self._render_footer())

        return "\n".join(sections)

    def export_commit_range(self, commit_hashes: list[str]) -> str:
        """导出多个提交"""
        sections = []
        sections.append(self._render_range_header(len(commit_hashes)))

        for i, commit_hash in enumerate(commit_hashes, 1):
            info = self.git.get_commit_info(commit_hash)
            changed_files = self.git.get_changed_files(commit_hash)

            sections.append(f"\n{'='*80}")
            sections.append(f"# Commit {i}/{len(commit_hashes)}")
            sections.append(f"{'='*80}\n")
            sections.append(self._render_header(info))
            sections.append(self._render_summary(changed_files))
            sections.append(self._render_file_changes(commit_hash, changed_files))

        sections.append(self._render_footer())
        return "\n".join(sections)

    def _render_header(self, info: dict) -> str:
        """渲染提交头部信息"""
        lines = [
            "<!-- CLAW EXPORT FORMAT v1.0 -->",
            "<!-- 本文件由 Claw 工具自动生成，用于 AI 辅助代码迁移 -->",
            "",
            "# 🔧 Git Commit Export",
            "",
            "## 提交信息 (Commit Metadata)",
            "",
            f"- **Commit Hash**: `{info['full_hash']}`",
            f"- **Short Hash**: `{info['short_hash']}`",
            f"- **Author**: {info['author_name']} <{info['author_email']}>",
            f"- **Date**: {info['date']}",
            f"- **Subject**: {info['subject']}",
        ]
        if info["body"]:
            lines.append(f"- **Body**:")
            lines.append(f"  ```")
            lines.append(f"  {info['body']}")
            lines.append(f"  ```")
        lines.append("")
        return "\n".join(lines)

    def _render_summary(self, changed_files: list[dict]) -> str:
        """渲染变更文件摘要"""
        lines = [
            "## 变更摘要 (Change Summary)",
            "",
            f"共 **{len(changed_files)}** 个文件变更:",
            "",
            "| # | 操作 | 文件路径 |",
            "|---|------|----------|",
        ]

        for i, f in enumerate(changed_files, 1):
            status = f["status"]
            status_emoji = {
                "ADDED": "➕ ADDED",
                "MODIFIED": "✏️ MODIFIED",
                "DELETED": "🗑️ DELETED",
                "RENAMED": "📝 RENAMED",
                "COPIED": "📋 COPIED",
                "TYPE_CHANGED": "🔄 TYPE_CHANGED",
            }.get(status, status)

            if status in ("RENAMED", "COPIED"):
                path = f"`{f['old_path']}` → `{f['new_path']}` ({f['similarity']})"
            else:
                path = f"`{f['path']}`"

            lines.append(f"| {i} | {status_emoji} | {path} |")

        lines.append("")
        return "\n".join(lines)

    def _render_file_changes(self, commit_hash: str, changed_files: list[dict]) -> str:
        """渲染每个文件的具体变更"""
        lines = [
            "## 文件变更详情 (File Changes)",
            "",
            "> **AI 迁移指令**: 请按以下各文件的变更操作，在目标项目中逐一应用修改。",
            "> 每个文件块包含操作类型和完整的 diff，请据此精确还原代码变更。",
            "",
        ]

        for i, f in enumerate(changed_files, 1):
            status = f["status"]
            lines.append(f"---")
            lines.append(f"")
            lines.append(f"### 文件 {i}: {self._get_file_display_name(f)}")
            lines.append(f"")
            lines.append(f"- **操作 (Action)**: `{status}`")

            if status in ("RENAMED", "COPIED"):
                lines.append(f"- **原路径**: `{f['old_path']}`")
                lines.append(f"- **新路径**: `{f['new_path']}`")
                lines.append(f"- **相似度**: {f['similarity']}")
                file_path = f["new_path"]
                old_path = f["old_path"]
            elif status == "DELETED":
                file_path = f["path"]
                old_path = f["path"]
                lines.append(f"- **文件路径**: `{file_path}`")
            else:
                file_path = f["path"]
                old_path = f["path"]
                lines.append(f"- **文件路径**: `{file_path}`")

            # 文件扩展名用于代码块语法高亮
            ext = Path(file_path).suffix.lstrip(".")
            lang = self._ext_to_lang(ext)

            lines.append(f"")

            # Diff 内容
            if status == "DELETED":
                lines.append(f"#### Diff (完整删除)")
                before_content = self.git.get_file_content_before_commit(commit_hash, old_path)
                if before_content:
                    lines.append(f"")
                    lines.append(f"被删除文件的完整内容:")
                    lines.append(f"```{lang}")
                    lines.append(before_content)
                    lines.append(f"```")
            elif status == "ADDED":
                lines.append(f"#### Diff (新增文件)")
                after_content = self.git.get_file_content_at_commit(commit_hash, file_path)
                if after_content is not None:
                    lines.append(f"")
                    lines.append(f"新文件的完整内容 — **请创建此文件并写入以下内容**:")
                    lines.append(f"```{lang}")
                    lines.append(after_content)
                    lines.append(f"```")
            else:
                # MODIFIED, RENAMED, COPIED
                diff_content = self._get_file_diff_safe(commit_hash, file_path, old_path)
                if diff_content:
                    lines.append(f"#### Diff")
                    lines.append(f"")
                    lines.append(f"```diff")
                    lines.append(diff_content)
                    lines.append(f"```")

                # 可选: 包含完整文件内容
                if self.include_full_content and status != "DELETED":
                    after_content = self.git.get_file_content_at_commit(commit_hash, file_path)
                    if after_content is not None:
                        lines.append(f"")
                        lines.append(f"#### 变更后完整文件内容 (Full Content After Change)")
                        lines.append(f"")
                        lines.append(f"```{lang}")
                        lines.append(after_content)
                        lines.append(f"```")

            lines.append(f"")

        return "\n".join(lines)

    def _get_file_diff_safe(self, commit_hash: str, file_path: str, old_path: str = None) -> str:
        """安全地获取文件 diff"""
        try:
            diff = self.git.get_file_diff(commit_hash, file_path)
            if not diff and old_path and old_path != file_path:
                diff = self.git.get_file_diff(commit_hash, old_path)
            return diff
        except RuntimeError:
            return ""

    def _render_footer(self) -> str:
        """渲染尾部信息"""
        lines = [
            "---",
            "",
            "## AI 迁移指南 (Migration Instructions for AI)",
            "",
            "请按照以下步骤还原此次提交的所有变更:",
            "",
            "1. **ADDED (新增)**: 在指定路径创建新文件，写入提供的完整内容",
            "2. **MODIFIED (修改)**: 找到对应文件，按照 diff 中的变更进行修改:",
            "   - 以 `-` 开头的行表示需要**删除**的内容",
            "   - 以 `+` 开头的行表示需要**添加**的内容",
            "   - 以空格开头的行表示**上下文**（不变的内容）",
            "   - `@@ ... @@` 标记表示变更的位置信息",
            "3. **DELETED (删除)**: 删除指定路径的文件",
            "4. **RENAMED (重命名)**: 将文件从原路径移动到新路径，并应用 diff 中的修改（如有）",
            "5. **COPIED (复制)**: 复制文件到新路径，并应用 diff 中的修改（如有）",
            "",
            "请确保所有变更都精确应用，包括空格、缩进和换行符。",
            "",
            f"<!-- Generated by Claw v{__version__} at {datetime.now().isoformat()} -->",
            "",
        ]
        return "\n".join(lines)

    def _get_file_display_name(self, f: dict) -> str:
        """获取文件显示名称"""
        if f["status"] in ("RENAMED", "COPIED"):
            return f"`{f['new_path']}`"
        return f"`{f['path']}`"

    def _ext_to_lang(self, ext: str) -> str:
        """将文件扩展名映射到代码块语言标识"""
        lang_map = {
            "py": "python",
            "js": "javascript",
            "ts": "typescript",
            "tsx": "tsx",
            "jsx": "jsx",
            "rb": "ruby",
            "go": "go",
            "rs": "rust",
            "java": "java",
            "kt": "kotlin",
            "swift": "swift",
            "c": "c",
            "cpp": "cpp",
            "h": "c",
            "hpp": "cpp",
            "cs": "csharp",
            "php": "php",
            "sh": "bash",
            "bash": "bash",
            "zsh": "bash",
            "yml": "yaml",
            "yaml": "yaml",
            "json": "json",
            "xml": "xml",
            "html": "html",
            "css": "css",
            "scss": "scss",
            "less": "less",
            "sql": "sql",
            "md": "markdown",
            "toml": "toml",
            "ini": "ini",
            "cfg": "ini",
            "dockerfile": "dockerfile",
            "vue": "vue",
            "svelte": "svelte",
            "lua": "lua",
            "r": "r",
            "dart": "dart",
            "scala": "scala",
            "ex": "elixir",
            "exs": "elixir",
            "erl": "erlang",
            "hs": "haskell",
            "clj": "clojure",
            "tf": "hcl",
            "proto": "protobuf",
            "graphql": "graphql",
            "gql": "graphql",
        }
        return lang_map.get(ext.lower(), ext.lower() if ext else "")


# ─── JSON 导出器 ───────────────────────────────────────────────────
class ClawJsonExporter:
    """将 Git 提交信息导出为 JSON 格式（机器可读）"""

    def __init__(self, git: GitOperator, include_full_content: bool = False):
        self.git = git
        self.include_full_content = include_full_content

    def export_commit(self, commit_hash: str) -> str:
        """导出单个提交为 JSON"""
        data = self._build_commit_data(commit_hash)
        return json.dumps(data, indent=2, ensure_ascii=False)

    def export_commit_range(self, commit_hashes: list[str]) -> str:
        """导出多个提交为 JSON"""
        data = {
            "claw_version": __version__,
            "export_time": datetime.now().isoformat(),
            "format": "claw-json-v1",
            "total_commits": len(commit_hashes),
            "commits": [self._build_commit_data(h) for h in commit_hashes],
        }
        return json.dumps(data, indent=2, ensure_ascii=False)

    def _build_commit_data(self, commit_hash: str) -> dict:
        """构建单个提交的数据结构"""
        info = self.git.get_commit_info(commit_hash)
        changed_files = self.git.get_changed_files(commit_hash)

        files_data = []
        for f in changed_files:
            file_entry = {"status": f["status"]}
            status = f["status"]

            if status in ("RENAMED", "COPIED"):
                file_entry["old_path"] = f["old_path"]
                file_entry["new_path"] = f["new_path"]
                file_entry["similarity"] = f["similarity"]
                file_path = f["new_path"]
                old_path = f["old_path"]
            else:
                file_entry["path"] = f["path"]
                file_path = f["path"]
                old_path = f["path"]

            # 获取 diff
            if status == "ADDED":
                content = self.git.get_file_content_at_commit(commit_hash, file_path)
                file_entry["full_content"] = content
            elif status == "DELETED":
                content = self.git.get_file_content_before_commit(commit_hash, old_path)
                file_entry["deleted_content"] = content
            else:
                try:
                    diff = self.git.get_file_diff(commit_hash, file_path)
                    file_entry["diff"] = diff
                except RuntimeError:
                    file_entry["diff"] = ""

                if self.include_full_content:
                    content = self.git.get_file_content_at_commit(commit_hash, file_path)
                    if content is not None:
                        file_entry["full_content_after"] = content

            files_data.append(file_entry)

        return {
            "claw_version": __version__,
            "export_time": datetime.now().isoformat(),
            "format": "claw-json-v1",
            "commit": info,
            "changes_count": len(changed_files),
            "files": files_data,
        }


# ─── CLI ───────────────────────────────────────────────────────────
def create_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="claw",
        description="🐾 Claw - Git Commit Exporter for AI Migration",
        epilog="示例:\n"
               "  python claw.py abc123\n"
               "  python claw.py abc123 -o changes.md\n"
               "  python claw.py abc123..def456 --full\n"
               "  python claw.py HEAD -f json -o changes.json\n"
               "  python claw.py HEAD~3 --repo /path/to/repo\n",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    parser.add_argument(
        "commit",
        help="提交哈希值、引用（如 HEAD、HEAD~1）或范围（如 abc..def）",
    )
    parser.add_argument(
        "-o", "--output",
        help="输出文件路径（默认输出到 stdout）",
        default=None,
    )
    parser.add_argument(
        "-f", "--format",
        help="输出格式: md (Markdown, 默认) 或 json",
        choices=["md", "json"],
        default="md",
    )
    parser.add_argument(
        "--full",
        help="包含变更后文件的完整内容（用于复杂变更的精确恢复）",
        action="store_true",
    )
    parser.add_argument(
        "--repo",
        help="Git 仓库路径（默认为当前目录）",
        default=".",
    )
    parser.add_argument(
        "-v", "--version",
        action="version",
        version=f"Claw v{__version__}",
    )

    return parser


def main():
    parser = create_parser()
    args = parser.parse_args()

    try:
        git = GitOperator(args.repo)
    except RuntimeError as e:
        print(f"❌ 错误: {e}", file=sys.stderr)
        sys.exit(1)

    # 判断是单个提交还是范围
    is_range = ".." in args.commit

    try:
        if is_range:
            commit_hashes = git.get_commit_range(args.commit)
            if not commit_hashes:
                print(f"❌ 未找到指定范围内的提交: {args.commit}", file=sys.stderr)
                sys.exit(1)
            print(f"📦 正在导出 {len(commit_hashes)} 个提交...", file=sys.stderr)
        else:
            # 验证提交存在
            info = git.get_commit_info(args.commit)
            commit_hashes = [info["full_hash"]]
            print(f"📦 正在导出提交 {info['short_hash']}: {info['subject']}", file=sys.stderr)

        # 选择导出器
        if args.format == "json":
            exporter = ClawJsonExporter(git, include_full_content=args.full)
        else:
            exporter = ClawExporter(git, include_full_content=args.full)

        # 导出
        if is_range:
            output = exporter.export_commit_range(commit_hashes)
        else:
            output = exporter.export_commit(commit_hashes[0])

        # 输出
        if args.output:
            output_path = Path(args.output)
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(output, encoding="utf-8")
            print(f"✅ 已导出到 {output_path.resolve()}", file=sys.stderr)
        else:
            print(output)

    except RuntimeError as e:
        print(f"❌ 错误: {e}", file=sys.stderr)
        sys.exit(1)
    except KeyboardInterrupt:
        print("\n⚠️ 已取消", file=sys.stderr)
        sys.exit(130)


if __name__ == "__main__":
    main()
