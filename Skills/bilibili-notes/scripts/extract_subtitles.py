#!/usr/bin/env python3
"""
Bilibili Subtitle Extractor

Extract subtitles from Bilibili videos via their public API.

Usage:
    python extract_subtitles.py <video_url_or_bvid> --output <output_path> [--part N] [--cookie COOKIE]

Examples:
    python extract_subtitles.py https://www.bilibili.com/video/BV1xx411x7xx --output subtitles.txt
    python extract_subtitles.py BV1xx411x7xx --output subtitles.txt --part 2
"""

import argparse
import json
import os
import re
import sys
from pathlib import Path

try:
    import requests
except ImportError:
    print("ERROR: 'requests' library is required. Install with: pip install requests")
    sys.exit(1)


# ==================== Constants ====================

BILIBILI_VIDEO_INFO_API = "https://api.bilibili.com/x/web-interface/view"
BILIBILI_PLAYER_API = "https://api.bilibili.com/x/player/wbi/v2"

DEFAULT_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Referer": "https://www.bilibili.com",
}


# ==================== URL Parsing ====================

def parse_bvid(url_or_bvid: str) -> str:
    """Extract BV ID from a Bilibili URL or raw BV string."""
    # Direct BV ID
    if re.match(r"^BV[0-9A-Za-z]+$", url_or_bvid):
        return url_or_bvid

    # URL patterns
    match = re.search(r"(BV[0-9A-Za-z]+)", url_or_bvid)
    if match:
        return match.group(1)

    raise ValueError(f"Cannot parse BV ID from: {url_or_bvid}")


def parse_part_number(url: str) -> int:
    """Extract part number from URL query parameter ?p=N. Default is 1."""
    match = re.search(r"[?&]p=(\d+)", url)
    return int(match.group(1)) if match else 1


# ==================== Bilibili API ====================

def get_video_info(bvid: str, headers: dict) -> dict:
    """
    Fetch video info (aid, cid, title, pages) from Bilibili API.

    API: https://api.bilibili.com/x/web-interface/view?bvid=BVxxxxxx
    """
    resp = requests.get(
        BILIBILI_VIDEO_INFO_API,
        params={"bvid": bvid},
        headers=headers,
        timeout=15,
    )
    resp.raise_for_status()
    data = resp.json()

    if data.get("code") != 0:
        raise RuntimeError(f"Bilibili API error: {data.get('message', 'Unknown error')}")

    video_data = data["data"]
    return {
        "aid": video_data["aid"],
        "bvid": video_data["bvid"],
        "title": video_data["title"],
        "desc": video_data.get("desc", ""),
        "owner": video_data.get("owner", {}).get("name", ""),
        "pages": [
            {"cid": p["cid"], "part": p["part"], "page": p["page"]}
            for p in video_data.get("pages", [])
        ],
    }


def get_subtitle_list(aid: int, cid: int, headers: dict) -> list:
    """
    Fetch subtitle list for a video part.

    API: https://api.bilibili.com/x/player/wbi/v2?aid=xxx&cid=xxx
    """
    resp = requests.get(
        BILIBILI_PLAYER_API,
        params={"aid": aid, "cid": cid},
        headers=headers,
        timeout=15,
    )
    resp.raise_for_status()
    data = resp.json()

    if data.get("code") != 0:
        raise RuntimeError(f"Player API error: {data.get('message', 'Unknown error')}")

    subtitles = data.get("data", {}).get("subtitle", {}).get("subtitles", [])
    return subtitles


def download_subtitle(subtitle_url: str, headers: dict) -> list:
    """
    Download subtitle JSON content.

    Returns a list of subtitle segments: [{"from": 0.0, "to": 2.5, "content": "..."}]
    """
    if subtitle_url.startswith("//"):
        subtitle_url = "https:" + subtitle_url

    resp = requests.get(subtitle_url, headers=headers, timeout=15)
    resp.raise_for_status()
    data = resp.json()

    return data.get("body", [])


# ==================== Subtitle Processing ====================

def select_best_subtitle(subtitles: list) -> dict | None:
    """
    Select the best subtitle from the list.
    Priority: zh-CN > zh-Hans > zh > en > first available.
    """
    if not subtitles:
        return None

    priority = ["zh-CN", "zh-Hans", "zh", "ai-zh", "en", "ai-en"]

    for lang in priority:
        for sub in subtitles:
            lan = sub.get("lan", "")
            if lan == lang or lan.startswith(lang):
                return sub

    # Fallback to first
    return subtitles[0]


def format_subtitles(segments: list, with_timestamps: bool = True) -> str:
    """Format subtitle segments into readable text."""
    lines = []
    for seg in segments:
        content = seg.get("content", "").strip()
        if not content:
            continue

        if with_timestamps:
            start = seg.get("from", 0)
            minutes = int(start // 60)
            seconds = int(start % 60)
            lines.append(f"[{minutes:02d}:{seconds:02d}] {content}")
        else:
            lines.append(content)

    return "\n".join(lines)


# ==================== Main ====================

def extract(
    url_or_bvid: str,
    part: int = 1,
    cookie: str = "",
    with_timestamps: bool = True,
) -> dict:
    """
    Main extraction function.

    Returns:
        {
            "title": str,
            "owner": str,
            "part_name": str,
            "subtitle_lang": str,
            "text": str,
            "segments": list,
        }
    """
    bvid = parse_bvid(url_or_bvid)
    print(f"[INFO] Video BV ID: {bvid}")

    # Build headers
    headers = dict(DEFAULT_HEADERS)
    if cookie:
        headers["Cookie"] = cookie

    # Step 1: Get video info
    print("[INFO] Fetching video info...")
    video_info = get_video_info(bvid, headers)
    print(f"[INFO] Title: {video_info['title']}")
    print(f"[INFO] UP: {video_info['owner']}")
    print(f"[INFO] Total parts: {len(video_info['pages'])}")

    # Validate part number
    if part < 1 or part > len(video_info["pages"]):
        raise ValueError(
            f"Part {part} is out of range. This video has {len(video_info['pages'])} part(s)."
        )

    page = video_info["pages"][part - 1]
    cid = page["cid"]
    part_name = page["part"]
    print(f"[INFO] Extracting part {part}: {part_name} (cid={cid})")

    # Step 2: Get subtitle list
    print("[INFO] Fetching subtitle list...")
    subtitle_list = get_subtitle_list(video_info["aid"], cid, headers)

    if not subtitle_list:
        print("[WARN] No subtitles found for this video.")
        print("[HINT] This video may not have AI-generated or manually uploaded subtitles.")
        print("[HINT] Try setting BILIBILI_COOKIE environment variable if the video requires login.")
        return {
            "title": video_info["title"],
            "owner": video_info["owner"],
            "part_name": part_name,
            "subtitle_lang": "",
            "text": "",
            "segments": [],
        }

    print(f"[INFO] Available subtitles: {[s.get('lan_doc', s.get('lan')) for s in subtitle_list]}")

    # Step 3: Select and download best subtitle
    best = select_best_subtitle(subtitle_list)
    print(f"[INFO] Selected subtitle: {best.get('lan_doc', best.get('lan', 'unknown'))}")

    segments = download_subtitle(best["subtitle_url"], headers)
    print(f"[INFO] Downloaded {len(segments)} subtitle segments")

    # Step 4: Format
    text = format_subtitles(segments, with_timestamps=with_timestamps)

    return {
        "title": video_info["title"],
        "owner": video_info["owner"],
        "part_name": part_name,
        "subtitle_lang": best.get("lan_doc", best.get("lan", "unknown")),
        "text": text,
        "segments": segments,
    }


def main():
    parser = argparse.ArgumentParser(description="Extract subtitles from Bilibili videos")
    parser.add_argument("video", help="Bilibili video URL or BV ID")
    parser.add_argument("--output", "-o", required=True, help="Output file path (.txt)")
    parser.add_argument("--part", "-p", type=int, default=None, help="Part number (default: auto-detect from URL)")
    parser.add_argument("--cookie", default="", help="Bilibili cookie string for authentication")
    parser.add_argument("--cookie-file", default="", help="Path to file containing Bilibili cookie string")
    parser.add_argument("--no-timestamps", action="store_true", help="Omit timestamps from output")
    parser.add_argument("--segments-json", default="", help="Also output raw segments as JSON (for screenshot alignment)")
    args = parser.parse_args()

    # Determine part number
    part = args.part if args.part else parse_part_number(args.video)

    # Cookie from arg, file, or env
    cookie = args.cookie or os.environ.get("BILIBILI_COOKIE", "")
    if not cookie and args.cookie_file:
        cookie_path = Path(args.cookie_file)
        if cookie_path.exists():
            cookie = cookie_path.read_text(encoding="utf-8").strip()
            print(f"[INFO] Loaded cookie from file: {cookie_path}")
    # Auto-detect cookie file next to this script's parent dir
    if not cookie:
        auto_cookie = Path(__file__).parent.parent / "cookie.txt"
        if auto_cookie.exists():
            cookie = auto_cookie.read_text(encoding="utf-8").strip()
            print(f"[INFO] Auto-loaded cookie from: {auto_cookie}")

    try:
        result = extract(
            url_or_bvid=args.video,
            part=part,
            cookie=cookie,
            with_timestamps=not args.no_timestamps,
        )
    except Exception as e:
        print(f"[ERROR] {e}")
        sys.exit(1)

    if not result["text"]:
        print("[RESULT] No subtitle content extracted.")
        sys.exit(0)

    # Write output
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    metadata_header = (
        f"# {result['title']}\n"
        f"# UP主: {result['owner']}\n"
        f"# 分P: {result['part_name']}\n"
        f"# 字幕语言: {result['subtitle_lang']}\n"
        f"# 字幕段数: {len(result['segments'])}\n"
        f"---\n\n"
    )

    with open(output_path, "w", encoding="utf-8") as f:
        f.write(metadata_header)
        f.write(result["text"])

    print(f"[SUCCESS] Subtitles saved to: {output_path}")
    print(f"[INFO] Total lines: {len(result['text'].splitlines())}")

    # Optionally output segments JSON for screenshot alignment
    segments_json_path = args.segments_json
    if not segments_json_path:
        # Auto-generate segments JSON path next to the output file
        segments_json_path = str(output_path.with_suffix(".segments.json"))

    if result["segments"]:
        seg_path = Path(segments_json_path)
        seg_path.parent.mkdir(parents=True, exist_ok=True)
        with open(seg_path, "w", encoding="utf-8") as f:
            json.dump(result["segments"], f, ensure_ascii=False, indent=2)
        print(f"[INFO] Segments JSON saved to: {seg_path}")
        print(f"[INFO] Segments count: {len(result['segments'])}")


if __name__ == "__main__":
    main()
