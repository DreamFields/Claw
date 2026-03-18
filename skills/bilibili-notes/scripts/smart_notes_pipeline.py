#!/usr/bin/env python3
"""
Smart Notes Pipeline (v4)

Three-step intelligent video note generation:
  Step 1 — Slice & Summarize: Cut subtitles into 3-10 min segments, summarize each.
  Step 2 — Parallel Frame Capture: Capture dense keyframes per segment, deduplicate.
  Step 3 — Weighted Image Insertion: Distribute images across topics by weight.

Usage:
    python smart_notes_pipeline.py <video_url_or_bvid> \
        --output-dir <dir> \
        --segment-minutes 5 \
        --detail-level 3 \
        --style technical

Dependencies:
    pip install requests Pillow yt-dlp imageio-ffmpeg openai
"""

import argparse
import hashlib
import json
import math
import os
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Optional

try:
    import requests
except ImportError:
    print("ERROR: 'requests' is required. pip install requests")
    sys.exit(1)

try:
    from PIL import Image
except ImportError:
    print("ERROR: 'Pillow' is required. pip install Pillow")
    sys.exit(1)


# ======================================================================
#  Configuration
# ======================================================================

DEFAULT_SEGMENT_MINUTES = 5       # Default segment length
MIN_SEGMENT_MINUTES = 3           # Minimum allowed
MAX_SEGMENT_MINUTES = 10          # Maximum allowed
FRAMES_PER_MINUTE = 2             # Dense capture: 2 frames/minute base rate
DEDUP_HASH_THRESHOLD = 8          # Hamming distance threshold for perceptual dedup
MIN_FRAMES_PER_SEGMENT = 3        # At least 3 frames per segment
MAX_FRAMES_PER_SEGMENT = 20       # Cap per segment


# ======================================================================
#  Step 0 — Helpers
# ======================================================================

def _ts_label(sec: float) -> str:
    """Format seconds → 'MMmSSs'."""
    m, s = int(sec // 60), int(sec % 60)
    return f"{m:02d}m{s:02d}s"


def _ts_display(sec: float) -> str:
    """Format seconds → 'MM:SS'."""
    m, s = int(sec // 60), int(sec % 60)
    return f"{m:02d}:{s:02d}"


# ======================================================================
#  Step 1 — Slice Subtitles into Time Segments
# ======================================================================

def slice_subtitles(
    segments: list[dict],
    segment_minutes: float = 5.0,
) -> list[dict]:
    """
    Slice subtitle segments into time-based chunks.

    Each subtitle segment has {"from": float, "to": float, "content": str}.
    We group them into larger chunks of `segment_minutes` minutes.

    Returns:
        [
            {
                "index": 0,
                "start_sec": 0.0,
                "end_sec": 300.0,
                "subtitles": [{"from":..., "to":..., "content":...}, ...],
                "text": "full text of this slice",
                "text_with_timestamps": "[00:05] blah\n[00:10] blah...",
                "char_count": 1234,
            },
            ...
        ]
    """
    if not segments:
        return []

    segment_seconds = segment_minutes * 60
    total_duration = max(seg.get("to", seg.get("from", 0)) for seg in segments)

    # Calculate number of slices
    n_slices = max(1, math.ceil(total_duration / segment_seconds))

    slices = []
    for i in range(n_slices):
        start = i * segment_seconds
        end = min((i + 1) * segment_seconds, total_duration + 1)

        # Collect subtitles in this range
        subs_in_range = [
            seg for seg in segments
            if seg.get("from", 0) >= start and seg.get("from", 0) < end
        ]

        if not subs_in_range:
            continue

        text_lines = [seg["content"].strip() for seg in subs_in_range if seg.get("content", "").strip()]
        ts_lines = []
        for seg in subs_in_range:
            content = seg.get("content", "").strip()
            if content:
                ts_lines.append(f"[{_ts_display(seg['from'])}] {content}")

        slices.append({
            "index": i,
            "start_sec": start,
            "end_sec": end,
            "subtitles": subs_in_range,
            "text": "\n".join(text_lines),
            "text_with_timestamps": "\n".join(ts_lines),
            "char_count": sum(len(line) for line in text_lines),
        })

    return slices


# ======================================================================
#  Step 1b — Summarize Each Slice (LLM)
# ======================================================================

SLICE_SYSTEM_PROMPT = """你是一位专业的技术笔记整理专家。你正在逐段观看一个视频，需要对当前片段做结构化总结。
请用中文输出，除非原文是英文。

你的总结必须包含：
1. **本段主题** — 用一句话概括这一段在讲什么
2. **核心知识点** — 按逻辑列出关键知识点（带序号），每个要点用 2-4 句话解释
3. **关键概念/术语** — 列出本段出现的重要概念
4. **实践要点** — 如有可操作的建议，列出

输出格式为 Markdown，每个知识点用 `### 知识点标题` 格式。
"""

SLICE_DETAIL_MODIFIERS = {
    1: "极简模式：每段只需 3-5 个要点，每个要点一句话。总计不超过 300 字。",
    2: "精简模式：每段列出关键知识点，每个用 2-3 句话解释。总计 500-1000 字。",
    3: "标准模式：结构化总结，含知识点展开解释和代码示例（如有）。总计 1000-2000 字。",
    4: "详细模式：完整提取所有知识点，含详细解释、代码、引用原话。总计 2000-4000 字。",
    5: "详尽模式：几乎逐句记录所有内容，不遗漏任何细节。不限字数。",
}


def summarize_slice(
    slice_data: dict,
    video_title: str,
    video_owner: str,
    total_slices: int,
    detail_level: int = 3,
    style: str = "technical",
    client=None,
    model: str = "gpt-4o",
) -> dict:
    """
    Summarize a single time-segment slice using LLM.

    Returns the slice_data dict augmented with:
        - "summary": str  (Markdown text)
        - "topics": list[dict]  (extracted topic headings with char counts)
    """
    detail_mod = SLICE_DETAIL_MODIFIERS.get(detail_level, SLICE_DETAIL_MODIFIERS[3])

    user_prompt = (
        f"视频标题: {video_title}\n"
        f"UP主: {video_owner}\n"
        f"当前片段: 第 {slice_data['index'] + 1}/{total_slices} 段 "
        f"({_ts_display(slice_data['start_sec'])} ~ {_ts_display(slice_data['end_sec'])})\n\n"
        f"{detail_mod}\n\n"
        f"---\n\n"
        f"以下是这一段的字幕内容（带时间戳）：\n\n"
        f"{slice_data['text_with_timestamps']}"
    )

    try:
        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": SLICE_SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.3,
            max_tokens={1: 1024, 2: 2048, 3: 4096, 4: 8192, 5: 16384}.get(detail_level, 4096),
        )
        summary = response.choices[0].message.content
    except Exception as e:
        print(f"  [WARN] LLM error for slice {slice_data['index'] + 1}: {e}")
        summary = f"## 片段 {slice_data['index'] + 1} ({_ts_display(slice_data['start_sec'])} ~ {_ts_display(slice_data['end_sec'])})\n\n> 总结生成失败，请手动补充。"

    # Parse topics from summary (look for ### headings)
    topics = _extract_topics(summary)

    slice_data["summary"] = summary
    slice_data["topics"] = topics
    return slice_data


def _extract_topics(summary_md: str) -> list[dict]:
    """
    Extract topic headings and their character count from a Markdown summary.

    Returns:
        [
            {"heading": "主题名", "level": 3, "char_count": 500, "line_start": 5, "line_end": 20},
            ...
        ]
    """
    lines = summary_md.split("\n")
    topics = []
    current_topic = None
    current_chars = 0
    current_start = 0

    for i, line in enumerate(lines):
        heading_match = re.match(r"^(#{2,4})\s+(.+)", line)
        if heading_match:
            # Save previous topic
            if current_topic is not None:
                topics.append({
                    "heading": current_topic,
                    "level": current_level,
                    "char_count": current_chars,
                    "line_start": current_start,
                    "line_end": i - 1,
                })
            current_topic = heading_match.group(2).strip()
            current_level = len(heading_match.group(1))
            current_chars = 0
            current_start = i
        else:
            current_chars += len(line)

    # Last topic
    if current_topic is not None:
        topics.append({
            "heading": current_topic,
            "level": current_level,
            "char_count": current_chars,
            "line_start": current_start,
            "line_end": len(lines) - 1,
        })

    return topics


# ======================================================================
#  Step 2 — Parallel Dense Frame Capture + Deduplication
# ======================================================================

def compute_phash(image_path: str, hash_size: int = 8) -> str:
    """
    Compute perceptual hash (pHash) of an image.
    Returns a hex string.
    """
    try:
        img = Image.open(image_path).convert("L").resize(
            (hash_size + 1, hash_size), Image.Resampling.LANCZOS
        )
        pixels = list(img.getdata()) if not hasattr(img, 'get_flattened_data') else list(img.get_flattened_data())
        width = hash_size + 1

        # Compute difference hash (dHash variant — fast and effective)
        bits = []
        for y in range(hash_size):
            for x in range(hash_size):
                left = pixels[y * width + x]
                right = pixels[y * width + x + 1]
                bits.append(1 if left > right else 0)

        # Convert to hex
        hash_int = 0
        for bit in bits:
            hash_int = (hash_int << 1) | bit
        return format(hash_int, f"0{hash_size * hash_size // 4}x")
    except Exception:
        return ""


def hamming_distance(hash1: str, hash2: str) -> int:
    """Compute hamming distance between two hex hash strings."""
    if not hash1 or not hash2 or len(hash1) != len(hash2):
        return 999
    val1 = int(hash1, 16)
    val2 = int(hash2, 16)
    xor = val1 ^ val2
    return bin(xor).count("1")


def deduplicate_frames(
    frame_paths: list[dict],
    threshold: int = DEDUP_HASH_THRESHOLD,
) -> list[dict]:
    """
    Remove visually duplicate frames using perceptual hashing.

    Args:
        frame_paths: list of dicts with at least {"path": str, "timestamp": float, ...}
        threshold: hamming distance threshold; lower = stricter dedup

    Returns:
        Filtered list with duplicates removed (keeps the first occurrence).
    """
    if len(frame_paths) <= 1:
        return frame_paths

    hashes = []
    for f in frame_paths:
        h = compute_phash(f["path"])
        hashes.append(h)

    kept = []
    kept_hashes = []
    removed = 0

    for i, frame in enumerate(frame_paths):
        h = hashes[i]
        if not h:
            kept.append(frame)
            continue

        is_dup = False
        for kh in kept_hashes:
            if hamming_distance(h, kh) <= threshold:
                is_dup = True
                break

        if not is_dup:
            kept.append(frame)
            kept_hashes.append(h)
        else:
            removed += 1
            # Delete the duplicate file to save space
            try:
                os.remove(frame["path"])
            except OSError:
                pass

    if removed > 0:
        print(f"  [INFO] Dedup: removed {removed} duplicate frames, kept {len(kept)}")

    return kept


def capture_segment_frames(
    segment_slice: dict,
    ffmpeg_path: str,
    stream_url: str,
    http_headers: dict,
    output_dir: Path,
    segment_index: int,
    frames_per_minute: float = FRAMES_PER_MINUTE,
) -> list[dict]:
    """
    Capture dense frames for a single time segment.

    Returns list of frame dicts.
    """
    start = segment_slice["start_sec"]
    end = segment_slice["end_sec"]
    duration_min = (end - start) / 60

    # Calculate number of frames for this segment
    n_frames = max(MIN_FRAMES_PER_SEGMENT, min(
        MAX_FRAMES_PER_SEGMENT,
        int(duration_min * frames_per_minute)
    ))

    # Generate evenly-spaced timestamps within the segment
    margin = min(3.0, (end - start) * 0.05)
    seg_start = start + margin
    seg_end = end - margin
    if seg_start >= seg_end:
        seg_start = start
        seg_end = end

    if n_frames == 1:
        timestamps = [(seg_start + seg_end) / 2]
    else:
        step = (seg_end - seg_start) / (n_frames - 1)
        timestamps = [seg_start + i * step for i in range(n_frames)]

    frames = []
    seg_dir = output_dir / f"seg_{segment_index:03d}"
    seg_dir.mkdir(parents=True, exist_ok=True)

    # Import capture function from capture_screenshots module
    from capture_screenshots import capture_frame_ffmpeg

    for i, ts in enumerate(timestamps):
        filename = f"seg{segment_index:03d}_f{i + 1:03d}_{_ts_label(ts)}.png"
        filepath = str(seg_dir / filename)

        success = capture_frame_ffmpeg(
            ffmpeg_path=ffmpeg_path,
            stream_url=stream_url,
            timestamp_sec=ts,
            output_path=filepath,
            http_headers=http_headers,
            quality=1,
            hd_png=True,
        )

        if success and os.path.isfile(filepath) and os.path.getsize(filepath) > 100:
            try:
                img = Image.open(filepath)
                w, h = img.size
                img.close()
            except Exception:
                w, h = 0, 0

            frames.append({
                "path": filepath,
                "timestamp": ts,
                "filename": filename,
                "segment_index": segment_index,
                "width": w,
                "height": h,
            })

    # Deduplicate within this segment
    frames = deduplicate_frames(frames)

    return frames


def parallel_capture_all_segments(
    slices: list[dict],
    ffmpeg_path: str,
    stream_url: str,
    http_headers: dict,
    output_dir: Path,
    frames_per_minute: float = FRAMES_PER_MINUTE,
    max_workers: int = 3,
) -> dict[int, list[dict]]:
    """
    Capture frames for all segments in parallel (ThreadPool).

    Returns:
        {segment_index: [frame_dicts]}
    """
    results = {}

    # Use ThreadPoolExecutor for I/O-bound ffmpeg calls
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {}
        for sl in slices:
            future = executor.submit(
                capture_segment_frames,
                segment_slice=sl,
                ffmpeg_path=ffmpeg_path,
                stream_url=stream_url,
                http_headers=http_headers,
                output_dir=output_dir,
                segment_index=sl["index"],
                frames_per_minute=frames_per_minute,
            )
            futures[future] = sl["index"]

        for future in as_completed(futures):
            seg_idx = futures[future]
            try:
                frames = future.result()
                results[seg_idx] = frames
                print(f"  [OK] Segment {seg_idx + 1}: captured {len(frames)} unique frames")
            except Exception as e:
                print(f"  [ERR] Segment {seg_idx + 1} failed: {e}")
                results[seg_idx] = []

    return results


# ======================================================================
#  Step 3 — Weighted Image Insertion
# ======================================================================

def allocate_images_to_topics(
    topics: list[dict],
    frames: list[dict],
    segment_start: float,
    segment_end: float,
) -> list[dict]:
    """
    Distribute frames to topics based on weight (topic char_count / total chars).

    Each topic gets at least 1 frame. Extra frames go to heavier topics.
    Frames are assigned in timestamp order to maintain visual chronology.

    Returns frames augmented with "assigned_topic_index" and "assigned_topic_heading".
    """
    if not topics or not frames:
        return frames

    total_chars = sum(t["char_count"] for t in topics) or 1

    # Calculate weight for each topic
    weights = []
    for t in topics:
        w = t["char_count"] / total_chars
        weights.append(w)

    # Distribute frames: each topic gets at least 1
    n_frames = len(frames)
    n_topics = len(topics)

    if n_frames <= n_topics:
        # Fewer frames than topics — give one frame to each topic, distribute evenly
        allocation = [0] * n_topics
        for i in range(n_frames):
            allocation[i % n_topics] = 1
    else:
        # First give 1 to each, then distribute remainder by weight
        allocation = [1] * n_topics
        remaining = n_frames - n_topics
        # Proportional to weight
        for _ in range(remaining):
            # Give to the topic with highest (weight - current_allocation/n_frames)
            deficits = [
                weights[j] - allocation[j] / n_frames
                for j in range(n_topics)
            ]
            best = deficits.index(max(deficits))
            allocation[best] += 1

    # Assign frames chronologically to topics
    # Sort frames by timestamp
    sorted_frames = sorted(frames, key=lambda f: f["timestamp"])

    frame_idx = 0
    for topic_idx, n_alloc in enumerate(allocation):
        for _ in range(n_alloc):
            if frame_idx < len(sorted_frames):
                sorted_frames[frame_idx]["assigned_topic_index"] = topic_idx
                sorted_frames[frame_idx]["assigned_topic_heading"] = topics[topic_idx]["heading"]
                frame_idx += 1

    # Any remaining unassigned frames go to the last topic
    while frame_idx < len(sorted_frames):
        sorted_frames[frame_idx]["assigned_topic_index"] = n_topics - 1
        sorted_frames[frame_idx]["assigned_topic_heading"] = topics[-1]["heading"]
        frame_idx += 1

    return sorted_frames


def insert_images_into_summary(
    summary_md: str,
    allocated_frames: list[dict],
    notes_dir: str,
) -> str:
    """
    Insert allocated frames before their assigned topic headings in the summary Markdown.
    """
    if not allocated_frames:
        return summary_md

    # Group frames by topic heading
    topic_frames = {}
    for f in allocated_frames:
        heading = f.get("assigned_topic_heading", "")
        if heading not in topic_frames:
            topic_frames[heading] = []
        topic_frames[heading].append(f)

    lines = summary_md.split("\n")
    result = []

    for line in lines:
        # Check if this is a heading that has assigned frames
        heading_match = re.match(r"^(#{2,4})\s+(.+)", line)
        if heading_match:
            heading_text = heading_match.group(2).strip()
            # Check if frames are assigned to this heading
            if heading_text in topic_frames:
                frames = topic_frames.pop(heading_text)
                # Insert frames BEFORE the heading
                for f in sorted(frames, key=lambda x: x["timestamp"]):
                    rel_path = os.path.relpath(f["path"], notes_dir).replace("\\", "/")
                    ts = _ts_display(f["timestamp"])
                    result.append(f"![{ts}]({rel_path})")
                    result.append("")
        result.append(line)

    # Any remaining unassigned frames go at the end
    remaining = []
    for frames in topic_frames.values():
        remaining.extend(frames)
    if remaining:
        result.append("")
        result.append("---")
        result.append("")
        result.append("#### 更多截图参考")
        result.append("")
        for f in sorted(remaining, key=lambda x: x["timestamp"]):
            rel_path = os.path.relpath(f["path"], notes_dir).replace("\\", "/")
            ts = _ts_display(f["timestamp"])
            result.append(f"![{ts}]({rel_path})")
            result.append("")

    return "\n".join(result)


# ======================================================================
#  Final Assembly — Merge all segment summaries into one document
# ======================================================================

MERGE_SYSTEM_PROMPT = """你是一位专业的技术笔记编辑。你收到了一份视频笔记的各段分别总结，需要将它们整合为一份流畅、结构清晰的完整笔记。

要求：
1. 保持各段的核心内容不丢失
2. 统一标题层级（## 用于大章节，### 用于知识点）
3. 合并重复出现的概念
4. 添加全文概述和总结
5. 输出纯 Markdown
"""


def merge_segment_summaries(
    slices: list[dict],
    video_title: str,
    video_owner: str,
    detail_level: int = 3,
    client=None,
    model: str = "gpt-4o",
) -> str:
    """
    Merge per-segment summaries into a single cohesive note.

    If LLM is available, uses it for intelligent merging.
    Otherwise, does structural concatenation.
    """
    # Build the combined input
    parts = []
    for sl in slices:
        time_range = f"{_ts_display(sl['start_sec'])} ~ {_ts_display(sl['end_sec'])}"
        parts.append(f"--- 第 {sl['index'] + 1} 段 ({time_range}) ---\n\n{sl.get('summary', '')}")

    combined = "\n\n".join(parts)

    if client:
        try:
            detail_mod = SLICE_DETAIL_MODIFIERS.get(detail_level, SLICE_DETAIL_MODIFIERS[3])
            user_prompt = (
                f"视频标题: {video_title}\n"
                f"UP主: {video_owner}\n\n"
                f"{detail_mod}\n\n"
                f"以下是视频各段的分别总结，请整合为一份完整的技术笔记：\n\n"
                f"{combined}"
            )

            response = client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": MERGE_SYSTEM_PROMPT},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=0.3,
                max_tokens={1: 2048, 2: 4096, 3: 8192, 4: 16384, 5: 32768}.get(detail_level, 8192),
            )
            return response.choices[0].message.content
        except Exception as e:
            print(f"[WARN] LLM merge failed: {e}, using structural merge")

    # Fallback: structural concatenation
    header = f"# {video_title}\n\n> UP主: {video_owner}\n\n---\n\n"
    body = ""
    for sl in slices:
        time_range = f"{_ts_display(sl['start_sec'])} ~ {_ts_display(sl['end_sec'])}"
        body += f"## 第 {sl['index'] + 1} 部分 ({time_range})\n\n"
        body += sl.get("summary", "_无内容_") + "\n\n"

    return header + body


# ======================================================================
#  Orchestrator — The Full Pipeline
# ======================================================================

def run_pipeline(
    bvid: str,
    output_dir: str,
    part: int = 1,
    segment_minutes: float = DEFAULT_SEGMENT_MINUTES,
    detail_level: int = 3,
    style: str = "technical",
    frames_per_minute: float = FRAMES_PER_MINUTE,
    cookie: str = "",
    api_key: str = "",
    base_url: str = "",
    model: str = "",
    no_screenshots: bool = False,
    dedup_threshold: int = DEDUP_HASH_THRESHOLD,
) -> dict:
    """
    Run the full 3-step pipeline.

    Returns:
        {
            "notes_path": str,
            "slices": list,
            "total_frames": int,
            "output_dir": str,
        }
    """
    from extract_subtitles import extract, parse_bvid
    from capture_screenshots import find_ffmpeg, get_stream_url_ytdlp

    # Resolve config
    api_key = api_key or os.environ.get("OPENAI_API_KEY", "")
    base_url = base_url or os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1")
    model = model or os.environ.get("OPENAI_MODEL", "gpt-4o")

    segment_minutes = max(MIN_SEGMENT_MINUTES, min(MAX_SEGMENT_MINUTES, segment_minutes))

    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    screenshots_dir = out / "screenshots"

    # ── Extract subtitles ──────────────────────────────────
    print("=" * 60)
    print("[PIPELINE] Step 0: Extracting subtitles...")
    print("=" * 60)

    result = extract(url_or_bvid=bvid, part=part, cookie=cookie, with_timestamps=True)
    if not result["text"]:
        raise RuntimeError("No subtitles found. Cannot proceed.")

    # Save subtitles
    sub_path = out / "subtitles.txt"
    with open(sub_path, "w", encoding="utf-8") as f:
        f.write(f"# {result['title']}\n# UP主: {result['owner']}\n---\n\n")
        f.write(result["text"])

    seg_path = out / "subtitles.segments.json"
    with open(seg_path, "w", encoding="utf-8") as f:
        json.dump(result["segments"], f, ensure_ascii=False, indent=2)

    video_title = result["title"]
    video_owner = result["owner"]
    segments = result["segments"]

    # ── Step 1: Slice & Summarize ──────────────────────────
    print("\n" + "=" * 60)
    print(f"[PIPELINE] Step 1: Slicing subtitles ({segment_minutes} min/segment)...")
    print("=" * 60)

    slices = slice_subtitles(segments, segment_minutes=segment_minutes)
    print(f"[INFO] Created {len(slices)} segments")
    for sl in slices:
        print(f"  Seg {sl['index'] + 1}: {_ts_display(sl['start_sec'])} ~ {_ts_display(sl['end_sec'])} "
              f"({sl['char_count']} chars, {len(sl['subtitles'])} subs)")

    # Initialize LLM client
    client = None
    if api_key:
        try:
            from openai import OpenAI
            client = OpenAI(api_key=api_key, base_url=base_url)
            print(f"[INFO] LLM ready: {model}")
        except ImportError:
            print("[WARN] openai not installed, will output raw slices without summarization")

    # ── Step 2: Parallel capture (starts simultaneously with summarization) ──
    print("\n" + "=" * 60)
    print("[PIPELINE] Step 2: Parallel frame capture + dedup...")
    print("=" * 60)

    segment_frames = {}  # {seg_index: [frame_dicts]}
    total_frames = 0

    if not no_screenshots:
        ffmpeg_path = find_ffmpeg()
        if ffmpeg_path:
            print(f"[INFO] ffmpeg: {ffmpeg_path}")
            bvid_parsed = parse_bvid(bvid)
            stream_info = get_stream_url_ytdlp(bvid_parsed, part, cookie)
            if stream_info and stream_info.get("url"):
                print(f"[INFO] Stream: {stream_info.get('width', '?')}x{stream_info.get('height', '?')}")
                segment_frames = parallel_capture_all_segments(
                    slices=slices,
                    ffmpeg_path=ffmpeg_path,
                    stream_url=stream_info["url"],
                    http_headers=stream_info.get("http_headers", {}),
                    output_dir=screenshots_dir,
                    frames_per_minute=frames_per_minute,
                    max_workers=3,
                )
                total_frames = sum(len(v) for v in segment_frames.values())
                print(f"[INFO] Total unique frames captured: {total_frames}")
            else:
                print("[WARN] Could not get stream URL, skipping screenshots")
        else:
            print("[WARN] ffmpeg not found, skipping screenshots")

    # ── Summarize each slice (can overlap with frame capture in future) ──
    print("\n[PIPELINE] Step 1 (cont): Summarizing each segment...")

    if client:
        for sl in slices:
            print(f"  Summarizing segment {sl['index'] + 1}/{len(slices)}...", end=" ", flush=True)
            summarize_slice(
                slice_data=sl,
                video_title=video_title,
                video_owner=video_owner,
                total_slices=len(slices),
                detail_level=detail_level,
                style=style,
                client=client,
                model=model,
            )
            n_topics = len(sl.get("topics", []))
            print(f"OK ({n_topics} topics, {len(sl.get('summary', ''))} chars)")
    else:
        # No LLM — store raw text as "summary"
        for sl in slices:
            sl["summary"] = (
                f"## 片段 {sl['index'] + 1} "
                f"({_ts_display(sl['start_sec'])} ~ {_ts_display(sl['end_sec'])})\n\n"
                f"```\n{sl['text']}\n```"
            )
            sl["topics"] = []

    # Save per-segment summaries
    for sl in slices:
        seg_summary_path = out / f"segment_{sl['index'] + 1:03d}_summary.md"
        with open(seg_summary_path, "w", encoding="utf-8") as f:
            f.write(sl.get("summary", ""))

    # ── Step 3: Weighted image insertion ──────────────────
    print("\n" + "=" * 60)
    print("[PIPELINE] Step 3: Weighted image insertion...")
    print("=" * 60)

    for sl in slices:
        seg_idx = sl["index"]
        frames = segment_frames.get(seg_idx, [])
        topics = sl.get("topics", [])

        if frames and topics:
            # Allocate images to topics by weight
            allocated = allocate_images_to_topics(
                topics=topics,
                frames=frames,
                segment_start=sl["start_sec"],
                segment_end=sl["end_sec"],
            )

            # Insert images into this segment's summary
            sl["summary_with_images"] = insert_images_into_summary(
                summary_md=sl["summary"],
                allocated_frames=allocated,
                notes_dir=str(out),
            )

            alloc_info = {}
            for f in allocated:
                h = f.get("assigned_topic_heading", "?")
                alloc_info[h] = alloc_info.get(h, 0) + 1
            print(f"  Seg {seg_idx + 1}: {len(frames)} frames → {len(topics)} topics")
            for h, c in alloc_info.items():
                print(f"    [{c} frame(s)] {h}")
        elif frames:
            # No topics parsed, just append frames at end
            lines = [sl.get("summary", "")]
            for f in sorted(frames, key=lambda x: x["timestamp"]):
                rel_path = os.path.relpath(f["path"], str(out)).replace("\\", "/")
                lines.append(f"\n![{_ts_display(f['timestamp'])}]({rel_path})")
            sl["summary_with_images"] = "\n".join(lines)
            print(f"  Seg {seg_idx + 1}: {len(frames)} frames appended (no topics parsed)")
        else:
            sl["summary_with_images"] = sl.get("summary", "")
            print(f"  Seg {seg_idx + 1}: no frames")

    # ── Final assembly ─────────────────────────────────────
    print("\n" + "=" * 60)
    print("[PIPELINE] Assembling final notes...")
    print("=" * 60)

    # Build the final merged document
    if client and len(slices) > 1:
        # Use LLM to merge, but with images we need special handling
        # First merge the text-only summaries
        print("[INFO] Merging with LLM...")
        merged_text = merge_segment_summaries(
            slices=slices,
            video_title=video_title,
            video_owner=video_owner,
            detail_level=detail_level,
            client=client,
            model=model,
        )
        # Then create the image-rich version from per-segment summaries
        image_sections = []
        for sl in slices:
            image_sections.append(sl.get("summary_with_images", sl.get("summary", "")))
        image_notes = "\n\n---\n\n".join(image_sections)
    else:
        merged_text = ""
        image_sections = []
        for sl in slices:
            image_sections.append(sl.get("summary_with_images", sl.get("summary", "")))
        image_notes = "\n\n---\n\n".join(image_sections)

    # Write the final notes (with images)
    detail_labels = {1: "极简", 2: "精简", 3: "标准", 4: "详细", 5: "详尽"}
    detail_label = detail_labels.get(detail_level, "标准")

    header = (
        f"# {video_title}\n\n"
        f"> UP主: {video_owner}  \n"
        f"> 笔记等级: {detail_level} ({detail_label}) | "
        f"切片: {len(slices)} 段 x {segment_minutes}分钟 | "
        f"截图: {total_frames} 张（去重后）\n\n"
        f"---\n\n"
    )

    # Sanitize filename (remove chars illegal on Windows)
    safe_title = re.sub(r'[\\/:*?"<>|]', '_', video_title[:50].strip())

    # Main output: per-segment with images
    notes_path = out / f"{safe_title}_笔记.md"
    with open(notes_path, "w", encoding="utf-8") as f:
        f.write(header)
        f.write(image_notes)

    # Also write the clean merged version (no images) if available
    if merged_text:
        clean_path = out / f"{safe_title}_笔记_纯文字.md"
        with open(clean_path, "w", encoding="utf-8") as f:
            f.write(header.replace(f"截图: {total_frames} 张（去重后）", "纯文字版"))
            f.write(merged_text)
        print(f"[INFO] Clean notes (no images): {clean_path}")

    # Write manifest
    manifest = {
        "video_title": video_title,
        "video_owner": video_owner,
        "bvid": bvid,
        "part": part,
        "segment_minutes": segment_minutes,
        "detail_level": detail_level,
        "total_slices": len(slices),
        "total_frames": total_frames,
        "notes_path": str(notes_path),
        "output_dir": str(out),
        "slices": [
            {
                "index": sl["index"],
                "start_sec": sl["start_sec"],
                "end_sec": sl["end_sec"],
                "char_count": sl["char_count"],
                "n_topics": len(sl.get("topics", [])),
                "n_frames": len(segment_frames.get(sl["index"], [])),
            }
            for sl in slices
        ],
    }
    manifest_path = out / "pipeline_manifest.json"
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)

    print(f"\n{'=' * 60}")
    print(f"[SUCCESS] Pipeline complete!")
    print(f"  Notes: {notes_path}")
    print(f"  Segments: {len(slices)}")
    print(f"  Frames: {total_frames}")
    print(f"  Manifest: {manifest_path}")
    print(f"{'=' * 60}")

    return {
        "notes_path": str(notes_path),
        "slices": slices,
        "total_frames": total_frames,
        "output_dir": str(out),
    }


# ======================================================================
#  CLI
# ======================================================================

def main():
    parser = argparse.ArgumentParser(
        description="Smart Notes Pipeline: Slice → Capture → Weight → Assemble",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("video", help="Bilibili video URL or BV ID")
    parser.add_argument("--output-dir", "-o", required=True, help="Output directory")
    parser.add_argument("--part", "-p", type=int, default=1, help="Part number (default: 1)")
    parser.add_argument(
        "--segment-minutes", "-m", type=float, default=DEFAULT_SEGMENT_MINUTES,
        help=f"Segment duration in minutes ({MIN_SEGMENT_MINUTES}-{MAX_SEGMENT_MINUTES}, default: {DEFAULT_SEGMENT_MINUTES})"
    )
    parser.add_argument(
        "--detail-level", "-d", type=int, choices=[1, 2, 3, 4, 5], default=3,
        help="Detail level 1-5 (default: 3)"
    )
    parser.add_argument(
        "--style", "-s",
        choices=["technical", "summary", "detailed", "study"],
        default="technical",
        help="Note style (default: technical)"
    )
    parser.add_argument(
        "--frames-per-minute", type=float, default=FRAMES_PER_MINUTE,
        help=f"Capture density in frames/minute (default: {FRAMES_PER_MINUTE})"
    )
    parser.add_argument("--no-screenshots", action="store_true", help="Skip screenshot capture")
    parser.add_argument(
        "--dedup-threshold", type=int, default=DEDUP_HASH_THRESHOLD,
        help=f"Perceptual hash dedup threshold (default: {DEDUP_HASH_THRESHOLD}, lower=stricter)"
    )
    parser.add_argument("--cookie", default="", help="Bilibili cookie string")
    parser.add_argument("--cookie-file", default="", help="Path to cookie file")
    parser.add_argument("--api-key", default="", help="OpenAI API key")
    parser.add_argument("--base-url", default="", help="OpenAI-compatible API base URL")
    parser.add_argument("--model", default="", help="LLM model name")
    args = parser.parse_args()

    # Cookie resolution
    cookie = args.cookie or os.environ.get("BILIBILI_COOKIE", "")
    if not cookie and args.cookie_file:
        cp = Path(args.cookie_file)
        if cp.exists():
            cookie = cp.read_text(encoding="utf-8").strip()
    if not cookie:
        auto_cookie = Path(__file__).parent.parent / "cookie.txt"
        if auto_cookie.exists():
            cookie = auto_cookie.read_text(encoding="utf-8").strip()
            print(f"[INFO] Auto-loaded cookie from: {auto_cookie}")

    try:
        run_pipeline(
            bvid=args.video,
            output_dir=args.output_dir,
            part=args.part,
            segment_minutes=args.segment_minutes,
            detail_level=args.detail_level,
            style=args.style,
            frames_per_minute=args.frames_per_minute,
            cookie=cookie,
            api_key=args.api_key,
            base_url=args.base_url,
            model=args.model,
            no_screenshots=args.no_screenshots,
            dedup_threshold=args.dedup_threshold,
        )
    except Exception as e:
        print(f"[ERROR] Pipeline failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
