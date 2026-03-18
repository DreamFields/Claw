#!/usr/bin/env python3
"""
AI-Powered Note Generator (v2)

Transform raw subtitle text into structured technical notes using LLM.
Supports configurable detail levels (1-5) and video screenshot embedding.

Usage:
    python generate_notes.py <subtitle_file> --output <output_path> [options]

Detail Levels:
    1 - Brief:    Quick summary, 5-8 bullet points, keywords only
    2 - Concise:  Key points with short explanations, ~1 page
    3 - Standard: Structured notes with sections, examples, takeaways (~2-3 pages)
    4 - Detailed: Comprehensive notes with full explanations, code, quotes (~4-6 pages)
    5 - Exhaustive: Near-transcript level detail, every point captured (~8+ pages)

Styles:
    technical  - Structured technical notes (default)
    summary    - Concise summary with bullet points
    detailed   - Comprehensive notes with timestamps
    study      - Study notes with Q&A format
"""

import argparse
import json
import os
import sys
from pathlib import Path

try:
    from openai import OpenAI
except ImportError:
    print("ERROR: 'openai' library is required. Install with: pip install openai")
    sys.exit(1)


# ==================== Prompt Templates ====================

SYSTEM_PROMPT = """你是一位专业的技术笔记整理专家。你擅长将视频字幕文本转化为结构清晰、重点突出的技术笔记。
请用中文输出笔记，除非原文是英文内容。"""

# Detail level descriptors that modify the base style prompts
DETAIL_LEVEL_MODIFIERS = {
    1: """
**细节程度: 极简摘要**
- 用一段话（3-5句）概括整个视频核心思想
- 列出 5-8 个最关键的要点，每个要点一句话
- 列出 5-8 个关键词/标签
- 不需要展开解释，不需要代码块，不需要引用原文
- 整体控制在 300-500 字以内""",

    2: """
**细节程度: 精简笔记**
- 概述段落（3-5句话总结）
- 列出核心知识点（8-15个），每个知识点用 2-3 句话简要解释
- 关键术语列表（附一句话定义）
- 可操作的要点/结论（3-5条）
- 整体控制在 800-1500 字以内
- 不需要代码块和详细引用""",

    3: """
**细节程度: 标准笔记**
- 完整的章节结构，按内容逻辑分为 3-6 个大章节
- 每个章节包含：标题、内容概述、关键知识点（带展开解释）
- 重要概念用加粗标注，附简明定义
- 包含代码示例（如果视频涉及编程）
- 实践要点和注意事项
- 总结段落
- 整体控制在 2000-4000 字""",

    4: """
**细节程度: 详细笔记**
- 完整的多级标题结构（大章节 > 小节 > 要点）
- 每个知识点都要详细展开解释，包括：
  - 是什么（定义）
  - 为什么（动机/原因）
  - 怎么做（方法/步骤）
  - 注意什么（陷阱/限制）
- 包含完整的代码示例和算法描述
- 引用视频中的关键原话（用引用块标注）
- 对比分析（如果涉及多种方案对比）
- 每个章节末尾的小结
- 延伸阅读和相关资源
- 整体控制在 5000-8000 字""",

    5: """
**细节程度: 详尽记录**
- 近乎逐段的完整记录，不遗漏任何知识点
- 完整保留视频中的所有技术细节、参数、数据
- 每个概念都要深入解释，包括背景知识和上下文
- 完整的代码块、算法伪代码、数据结构描述
- 大量引用视频原话（用引用块）
- 包含视频中提到的所有对比、权衡、取舍分析
- 详细的实践指南和操作步骤
- Q&A 部分（如果视频中有问答环节）
- 术语表（Glossary）
- 思维导图式的知识结构总览
- 不限字数，力求完整""",
}


STYLE_PROMPTS = {
    "technical": """请将以下视频字幕整理为结构化的技术笔记，要求：

1. **标题与概述**：提炼视频主题，写一段简短概述
2. **核心知识点**：按逻辑顺序列出关键知识点，每个知识点包含：
   - 知识点标题
   - 详细解释
   - 如有代码相关内容，提取为代码块
3. **关键概念**：列出视频中提到的重要概念、术语，简要解释
4. **实践要点**：提炼可操作的实践建议或步骤
5. **总结**：概括视频核心内容

输出格式为 Markdown。注意去除口语化表达，保持专业简洁。""",

    "summary": """请将以下视频字幕整理为简洁的摘要笔记，要求：

1. **一句话总结**：用一句话概括视频内容
2. **要点列表**：用 bullet points 列出核心要点
3. **关键词**：列出关键词/标签

输出格式为 Markdown。简洁明了，去除冗余信息。""",

    "detailed": """请将以下视频字幕整理为详细的学习笔记，要求：

1. **视频信息**：标题、主题、适合人群
2. **内容大纲**：按时间线列出章节标题
3. **详细笔记**：每个章节的完整笔记，包含：
   - 主要内容
   - 代码示例（如有）
   - 重要引用
   - 注意事项
4. **延伸阅读**：提及的工具、库、参考资料
5. **个人备注区**：留出空间供后续补充

输出格式为 Markdown。保留重要细节，适合深入学习。""",

    "study": """请将以下视频字幕整理为学习复习笔记，要求：

1. **知识卡片**：将核心知识拆分为独立的知识卡片，每张包含：
   - 概念名称
   - 解释说明
   - 示例或应用场景
2. **问答练习**：基于视频内容生成问答对（Q&A），用于自测
3. **易错点**：列出容易混淆或遗忘的知识点
4. **思维导图文本**：用缩进列表形式呈现知识结构

输出格式为 Markdown。适合复习巩固。""",
}


# ==================== Screenshot Integration ====================

def load_screenshot_manifest(manifest_path: str) -> dict | None:
    """Load screenshot manifest JSON file."""
    path = Path(manifest_path)
    if not path.exists():
        return None

    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def build_screenshot_reference(manifest: dict, notes_output_dir: str) -> str:
    """
    Build a screenshot reference section and return Markdown image links.
    Also returns a mapping of timestamps to relative image paths for inline use.
    """
    if not manifest or not manifest.get("frames"):
        return "", {}

    frames = manifest["frames"]
    screenshot_dir = Path(manifest.get("output_dir", ""))
    notes_dir = Path(notes_output_dir)

    # Calculate relative paths from notes file to screenshots
    timestamp_to_image = {}
    for frame in frames:
        frame_path = Path(frame["path"])
        try:
            rel_path = os.path.relpath(frame_path, notes_dir)
        except ValueError:
            rel_path = str(frame_path)
        # Normalize path separators for Markdown
        rel_path = rel_path.replace("\\", "/")

        ts = frame["timestamp"]
        m = int(ts // 60)
        s = int(ts % 60)
        ts_label = f"{m:02d}:{s:02d}"
        timestamp_to_image[ts] = {
            "path": rel_path,
            "label": ts_label,
            "filename": frame["filename"],
        }

    return timestamp_to_image


def find_closest_screenshot(timestamp: float, timestamp_to_image: dict, tolerance: float = 30.0) -> dict | None:
    """Find the closest screenshot to a given timestamp within tolerance."""
    if not timestamp_to_image:
        return None

    best_ts = None
    best_diff = float("inf")

    for ts in timestamp_to_image:
        diff = abs(ts - timestamp)
        if diff < best_diff:
            best_diff = diff
            best_ts = ts

    if best_ts is not None and best_diff <= tolerance:
        return timestamp_to_image[best_ts]
    return None


def inject_screenshots_into_notes(
    notes_md: str,
    timestamp_to_image: dict,
    subtitle_segments: list = None,
) -> str:
    """
    Inject screenshot images into generated notes at appropriate positions.

    Strategy:
    - Look for section headers (## or ###) and try to match them to timestamps
    - Insert the closest screenshot after each major section header
    - For sections with timestamps like [MM:SS], use exact matching
    """
    import re as _re

    if not timestamp_to_image:
        return notes_md

    lines = notes_md.split("\n")
    result_lines = []
    used_screenshots = set()

    # Sorted screenshot timestamps for sequential allocation
    sorted_ts = sorted(timestamp_to_image.keys())

    # Track which section we're in based on sequential position
    section_count = 0
    total_sections = sum(1 for line in lines if _re.match(r"^#{1,3}\s+", line))

    for line in lines:
        result_lines.append(line)

        # Check if this is a section header
        header_match = _re.match(r"^(#{1,3})\s+(.+)", line)
        if not header_match:
            continue

        header_level = len(header_match.group(1))
        header_text = header_match.group(2)

        # Try to find a timestamp reference in the header text [MM:SS]
        ts_match = _re.search(r"\[(\d{1,2}):(\d{2})\]", header_text)
        target_ts = None

        if ts_match:
            target_ts = int(ts_match.group(1)) * 60 + int(ts_match.group(2))
        elif total_sections > 0:
            # Estimate timestamp based on section position
            section_count += 1
            if sorted_ts:
                max_ts = max(sorted_ts)
                estimated_ts = (section_count / total_sections) * max_ts
                target_ts = estimated_ts

        if target_ts is not None:
            img_info = find_closest_screenshot(target_ts, timestamp_to_image, tolerance=60.0)
            if img_info and img_info["path"] not in used_screenshots:
                used_screenshots.add(img_info["path"])
                # Insert screenshot after header with caption
                result_lines.append("")
                result_lines.append(f"![视频截图 {img_info['label']}]({img_info['path']})")
                result_lines.append("")

    # If we have unused screenshots, add them as an appendix
    unused = [ts for ts in sorted_ts if timestamp_to_image[ts]["path"] not in used_screenshots]
    if unused and len(unused) <= len(sorted_ts):  # Don't add appendix if none were used (notes had no sections)
        if used_screenshots:  # Only add appendix if some were already used inline
            remaining = [ts for ts in unused]
            if remaining:
                result_lines.append("")
                result_lines.append("---")
                result_lines.append("")
                result_lines.append("## 附录：视频截图参考")
                result_lines.append("")
                for ts in remaining:
                    img_info = timestamp_to_image[ts]
                    result_lines.append(f"**[{img_info['label']}]**")
                    result_lines.append(f"![{img_info['label']}]({img_info['path']})")
                    result_lines.append("")
        else:
            # No screenshots were injected inline, add them all at the end
            result_lines.append("")
            result_lines.append("---")
            result_lines.append("")
            result_lines.append("## 视频关键画面")
            result_lines.append("")
            for ts in unused:
                img_info = timestamp_to_image[ts]
                result_lines.append(f"**[{img_info['label']}]**")
                result_lines.append(f"![{img_info['label']}]({img_info['path']})")
                result_lines.append("")

    return "\n".join(result_lines)


# ==================== Note Generation ====================

def read_subtitle_file(filepath: str) -> tuple[dict, str]:
    """
    Read subtitle file and extract metadata + content.
    Returns: (metadata_dict, subtitle_text)
    """
    path = Path(filepath)
    if not path.exists():
        raise FileNotFoundError(f"Subtitle file not found: {filepath}")

    with open(path, "r", encoding="utf-8") as f:
        content = f.read()

    metadata = {}
    lines = content.split("\n")
    text_start = 0

    for i, line in enumerate(lines):
        if line.startswith("# "):
            parts = line[2:].split(": ", 1)
            if len(parts) == 2:
                metadata[parts[0].strip()] = parts[1].strip()
        elif line.strip() == "---":
            text_start = i + 1
            break
        elif not line.startswith("#"):
            text_start = i
            break

    subtitle_text = "\n".join(lines[text_start:]).strip()
    return metadata, subtitle_text


def chunk_text(text: str, max_chars: int = 12000) -> list[str]:
    """Split text into chunks that fit within token limits."""
    lines = text.split("\n")
    chunks = []
    current_chunk = []
    current_len = 0

    for line in lines:
        line_len = len(line) + 1
        if current_len + line_len > max_chars and current_chunk:
            chunks.append("\n".join(current_chunk))
            current_chunk = []
            current_len = 0
        current_chunk.append(line)
        current_len += line_len

    if current_chunk:
        chunks.append("\n".join(current_chunk))

    return chunks


def build_user_prompt(style: str, detail_level: int, context: str, subtitle_text: str) -> str:
    """Build the full user prompt combining style, detail level, and content."""
    style_prompt = STYLE_PROMPTS.get(style, STYLE_PROMPTS["technical"])
    detail_modifier = DETAIL_LEVEL_MODIFIERS.get(detail_level, DETAIL_LEVEL_MODIFIERS[3])

    return f"{style_prompt}\n\n{detail_modifier}\n\n---\n\n{context}字幕内容:\n\n{subtitle_text}"


def get_max_tokens_for_detail(detail_level: int) -> int:
    """Return appropriate max_tokens based on detail level."""
    return {
        1: 1024,
        2: 2048,
        3: 4096,
        4: 8192,
        5: 16384,
    }.get(detail_level, 4096)


def generate_notes(
    subtitle_text: str,
    metadata: dict,
    style: str = "technical",
    detail_level: int = 3,
    api_key: str = "",
    base_url: str = "",
    model: str = "",
) -> str:
    """
    Generate structured notes from subtitle text using LLM.

    Args:
        subtitle_text: Raw subtitle text
        metadata: Video metadata dict
        style: Note style (technical/summary/detailed/study)
        detail_level: Detail level 1-5
        api_key: OpenAI API key
        base_url: OpenAI-compatible base URL
        model: Model name
    """
    api_key = api_key or os.environ.get("OPENAI_API_KEY", "")
    base_url = base_url or os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1")
    model = model or os.environ.get("OPENAI_MODEL", "gpt-4o")

    if not api_key:
        raise ValueError(
            "OPENAI_API_KEY is required. Set it as an environment variable or pass via --api-key."
        )

    client = OpenAI(api_key=api_key, base_url=base_url)
    max_tokens = get_max_tokens_for_detail(detail_level)

    # Build context
    video_title = metadata.get("标题", metadata.get("title", "未知"))
    video_owner = metadata.get("UP主", metadata.get("owner", "未知"))
    context = f"视频标题: {video_title}\nUP主: {video_owner}\n\n"

    # Adjust chunk size based on detail level
    # Higher detail = smaller chunks to preserve more info per chunk
    chunk_size = {1: 20000, 2: 16000, 3: 12000, 4: 10000, 5: 8000}.get(detail_level, 12000)
    chunks = chunk_text(subtitle_text, max_chars=chunk_size)
    print(f"[INFO] Subtitle split into {len(chunks)} chunk(s) (chunk size: {chunk_size})")

    if len(chunks) == 1:
        user_prompt = build_user_prompt(style, detail_level, context, chunks[0])

        print(f"[INFO] Generating notes (detail={detail_level}, style={style}, model={model})...")
        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.3,
            max_tokens=max_tokens,
        )
        return response.choices[0].message.content

    else:
        # Multi-chunk processing
        chunk_summaries = []

        # For higher detail levels, extract more from each chunk
        chunk_instruction = {
            1: "请提取这部分的 3-5 个最关键要点，每个要点一句话：",
            2: "请提取这部分的关键知识点，每个要点用 2-3 句话解释：",
            3: "请提取这部分的关键知识点和要点，保持适度详细：",
            4: "请详细提取这部分的所有知识点，包括解释、示例和引用原文：",
            5: "请尽可能完整地记录这部分的所有内容，不遗漏任何知识点、细节、引用和数据：",
        }.get(detail_level, "请提取这部分的关键知识点和要点，保持简洁：")

        chunk_max_tokens = {1: 1024, 2: 1536, 3: 2048, 4: 4096, 5: 8192}.get(detail_level, 2048)

        for i, chunk in enumerate(chunks):
            print(f"[INFO] Processing chunk {i + 1}/{len(chunks)}...")
            user_prompt = (
                f"以下是视频字幕的第 {i + 1}/{len(chunks)} 部分。"
                f"{chunk_instruction}\n\n{context}{chunk}"
            )

            response = client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=0.3,
                max_tokens=chunk_max_tokens,
            )
            chunk_summaries.append(response.choices[0].message.content)

        # Combine summaries into final notes
        combined = "\n\n---\n\n".join(chunk_summaries)
        detail_modifier = DETAIL_LEVEL_MODIFIERS.get(detail_level, DETAIL_LEVEL_MODIFIERS[3])
        style_prompt = STYLE_PROMPTS.get(style, STYLE_PROMPTS["technical"])

        final_prompt = (
            f"{style_prompt}\n\n{detail_modifier}\n\n---\n\n{context}"
            f"以下是从视频字幕中分段提取的要点，请将它们整合为一份完整的笔记：\n\n{combined}"
        )

        print(f"[INFO] Generating final combined notes...")
        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": final_prompt},
            ],
            temperature=0.3,
            max_tokens=max_tokens,
        )
        return response.choices[0].message.content


# ==================== Main ====================

def main():
    parser = argparse.ArgumentParser(
        description="Generate technical notes from video subtitles",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Detail Levels:
  1 - Brief      Quick summary, bullet points only (~300-500 chars)
  2 - Concise    Key points with short explanations (~1 page)
  3 - Standard   Structured notes with sections (~2-3 pages) [default]
  4 - Detailed   Comprehensive with code, quotes (~4-6 pages)
  5 - Exhaustive Near-transcript detail, nothing omitted (~8+ pages)
        """,
    )
    parser.add_argument("subtitle_file", help="Path to subtitle text file")
    parser.add_argument("--output", "-o", required=True, help="Output Markdown file path")
    parser.add_argument(
        "--style", "-s",
        choices=["technical", "summary", "detailed", "study"],
        default="technical",
        help="Note style (default: technical)",
    )
    parser.add_argument(
        "--detail-level", "-d",
        type=int,
        choices=[1, 2, 3, 4, 5],
        default=3,
        help="Detail level 1-5 (default: 3, see epilog for descriptions)",
    )
    parser.add_argument("--screenshot-manifest", default="", help="Path to screenshot manifest.json for image embedding")
    parser.add_argument("--screenshot-dir", default="", help="Path to screenshot directory (auto-finds manifest.json)")
    parser.add_argument("--api-key", default="", help="OpenAI API key")
    parser.add_argument("--base-url", default="", help="OpenAI-compatible API base URL")
    parser.add_argument("--model", default="", help="Model name to use")
    args = parser.parse_args()

    # Read subtitle file
    print(f"[INFO] Reading subtitle file: {args.subtitle_file}")
    metadata, subtitle_text = read_subtitle_file(args.subtitle_file)

    if not subtitle_text.strip():
        print("[ERROR] Subtitle file is empty or contains no text content.")
        sys.exit(1)

    print(f"[INFO] Subtitle length: {len(subtitle_text)} chars, {len(subtitle_text.splitlines())} lines")
    print(f"[INFO] Note style: {args.style}, Detail level: {args.detail_level}")

    # Generate notes
    try:
        notes = generate_notes(
            subtitle_text=subtitle_text,
            metadata=metadata,
            style=args.style,
            detail_level=args.detail_level,
            api_key=args.api_key,
            base_url=args.base_url,
            model=args.model,
        )
    except Exception as e:
        print(f"[ERROR] Note generation failed: {e}")
        sys.exit(1)

    # Load screenshot manifest if available
    manifest = None
    manifest_path = args.screenshot_manifest
    if not manifest_path and args.screenshot_dir:
        manifest_path = str(Path(args.screenshot_dir) / "manifest.json")

    if manifest_path:
        manifest = load_screenshot_manifest(manifest_path)
        if manifest:
            print(f"[INFO] Loaded screenshot manifest: {len(manifest.get('frames', []))} frames")

    # Inject screenshots into notes
    output_path = Path(args.output)
    if manifest:
        timestamp_to_image = build_screenshot_reference(manifest, str(output_path.parent))
        notes = inject_screenshots_into_notes(notes, timestamp_to_image)
        print(f"[INFO] Screenshots injected into notes")

    # Write output
    output_path.parent.mkdir(parents=True, exist_ok=True)

    video_title = metadata.get("标题", metadata.get("title", "视频笔记"))
    video_owner = metadata.get("UP主", metadata.get("owner", ""))

    detail_labels = {1: "极简摘要", 2: "精简笔记", 3: "标准笔记", 4: "详细笔记", 5: "详尽记录"}
    detail_label = detail_labels.get(args.detail_level, "标准笔记")

    header = f"# {video_title}\n\n"
    if video_owner:
        header += f"> UP主: {video_owner}\n\n"
    header += f"> 笔记风格: {args.style} | 细节等级: {args.detail_level} ({detail_label}) | 自动生成\n\n---\n\n"

    with open(output_path, "w", encoding="utf-8") as f:
        f.write(header + notes)

    print(f"[SUCCESS] Notes saved to: {output_path}")
    print(f"[INFO] Output size: {len(notes)} chars")


if __name__ == "__main__":
    main()
