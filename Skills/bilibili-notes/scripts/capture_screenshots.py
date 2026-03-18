#!/usr/bin/env python3
"""
Bilibili Video Screenshot Capturer (HD)

Capture HIGH-QUALITY screenshots from Bilibili videos at original resolution
(1080p or higher) using yt-dlp + ffmpeg. No need to download the full video —
ffmpeg seeks directly on the remote stream URL.

Dependencies:
    pip install yt-dlp imageio-ffmpeg Pillow requests

Usage:
    python capture_screenshots.py <video_url_or_bvid> --output-dir <dir> [options]

Examples:
    # Auto-select 10 key frames at original resolution
    python capture_screenshots.py BV1Et4y1P7ro --output-dir ./screenshots --count 10

    # Capture at specific timestamps (seconds)
    python capture_screenshots.py BV1Et4y1P7ro --output-dir ./screenshots --timestamps 0,60,120,300

    # Smart capture aligned to subtitle segment boundaries
    python capture_screenshots.py BV1Et4y1P7ro --output-dir ./screenshots --segments-json subs.segments.json --count 15

    # Fallback to sprite-sheet mode (low-res, no ffmpeg needed)
    python capture_screenshots.py BV1Et4y1P7ro --output-dir ./screenshots --count 10 --sprite-fallback
"""

import argparse
import json
import math
import os
import re
import struct
import subprocess
import sys
from io import BytesIO
from pathlib import Path

try:
    import requests
except ImportError:
    print("ERROR: 'requests' library is required. Install with: pip install requests")
    sys.exit(1)

try:
    from PIL import Image
except ImportError:
    print("ERROR: 'Pillow' library is required. Install with: pip install Pillow")
    sys.exit(1)


# ==================== Constants ====================

BILIBILI_VIDEO_INFO_API = "https://api.bilibili.com/x/web-interface/view"
BILIBILI_VIDEOSHOT_API = "https://api.bilibili.com/x/player/videoshot"
BILIBILI_PLAYURL_API = "https://api.bilibili.com/x/player/playurl"

DEFAULT_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Referer": "https://www.bilibili.com",
}


# ==================== ffmpeg Discovery ====================

def find_ffmpeg() -> str:
    """
    Find ffmpeg executable. Priority:
    1. System PATH
    2. imageio-ffmpeg bundled binary
    3. None (will fall back to sprite-sheet mode)
    """
    # Check system PATH
    import shutil
    ffmpeg_path = shutil.which("ffmpeg")
    if ffmpeg_path:
        return ffmpeg_path

    # Check imageio-ffmpeg
    try:
        import imageio_ffmpeg
        ffmpeg_path = imageio_ffmpeg.get_ffmpeg_exe()
        if ffmpeg_path and os.path.isfile(ffmpeg_path):
            return ffmpeg_path
    except ImportError:
        pass

    return ""


# ==================== URL Parsing ====================

def parse_bvid(url_or_bvid: str) -> str:
    """Extract BV ID from a Bilibili URL or raw BV string."""
    if re.match(r"^BV[0-9A-Za-z]+$", url_or_bvid):
        return url_or_bvid
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
    """Fetch video info (aid, cid, title, duration, pages)."""
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
        "duration": video_data.get("duration", 0),
        "pic": video_data.get("pic", ""),
        "pages": [
            {"cid": p["cid"], "part": p["part"], "page": p["page"], "duration": p.get("duration", 0)}
            for p in video_data.get("pages", [])
        ],
    }


# ==================== HD Screenshot via yt-dlp + ffmpeg ====================

def get_stream_url_ytdlp(bvid: str, part: int = 1, cookie: str = "") -> dict:
    """
    Use yt-dlp to extract the best video stream URL (no download).

    Returns:
        {"url": str, "width": int, "height": int, "format": str}
    """
    try:
        import yt_dlp
    except ImportError:
        print("[WARN] yt-dlp not installed. Install with: pip install yt-dlp")
        return {}

    video_url = f"https://www.bilibili.com/video/{bvid}?p={part}"

    ydl_opts = {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
        # Prefer the highest-resolution video stream regardless of container
        # Priority: 4K > 1080p60 > 1080p > 720p, any container
        "format": (
            "bestvideo[height>=2160]/"
            "bestvideo[height>=1080][fps>=50]/"
            "bestvideo[height>=1080]/"
            "bestvideo[height>=720]/"
            "bestvideo/best"
        ),
    }

    if cookie:
        # Write cookie to temp file for yt-dlp
        cookie_path = Path(__file__).parent / "_temp_cookie.txt"
        # Convert raw cookie string to Netscape format
        _write_netscape_cookie(cookie, cookie_path)
        ydl_opts["cookiefile"] = str(cookie_path)

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(video_url, download=False)

            # For multi-part videos, yt-dlp may return entries
            if "entries" in info:
                entries = list(info["entries"])
                if part <= len(entries):
                    info = entries[part - 1]
                else:
                    info = entries[0]

            stream_url = info.get("url", "")
            width = info.get("width", 0) or 0
            height = info.get("height", 0) or 0
            fmt = info.get("format", "")
            ext = info.get("ext", "")

            # If url is empty, try to find it in requested_formats
            if not stream_url and info.get("requested_formats"):
                for rf in info["requested_formats"]:
                    if rf.get("vcodec", "none") != "none":
                        stream_url = rf.get("url", "")
                        width = rf.get("width", width) or width
                        height = rf.get("height", height) or height
                        fmt = rf.get("format", fmt)
                        break

            if not stream_url:
                print("[WARN] yt-dlp could not extract stream URL")
                return {}

            return {
                "url": stream_url,
                "width": width,
                "height": height,
                "format": fmt,
                "ext": ext,
                "http_headers": info.get("http_headers", {}),
            }
    except Exception as e:
        print(f"[WARN] yt-dlp extraction failed: {e}")
        return {}
    finally:
        # Clean up temp cookie
        cookie_path = Path(__file__).parent / "_temp_cookie.txt"
        if cookie_path.exists():
            cookie_path.unlink()


def _write_netscape_cookie(cookie_str: str, path: Path):
    """Convert a raw cookie string to Netscape cookie file format for yt-dlp."""
    lines = [
        "# Netscape HTTP Cookie File",
        "# This file is generated automatically",
        "",
    ]
    for item in cookie_str.split(";"):
        item = item.strip()
        if "=" in item:
            key, value = item.split("=", 1)
            lines.append(f".bilibili.com\tTRUE\t/\tFALSE\t0\t{key.strip()}\t{value.strip()}")

    path.write_text("\n".join(lines), encoding="utf-8")


def capture_frame_ffmpeg(
    ffmpeg_path: str,
    stream_url: str,
    timestamp_sec: float,
    output_path: str,
    http_headers: dict = None,
    quality: int = 2,  # ffmpeg -q:v (1=best, 31=worst for JPEG); ignored for PNG
    hd_png: bool = False,  # If True, output lossless PNG instead of JPEG
) -> bool:
    """
    Use ffmpeg to capture a single frame from a remote video stream.

    Args:
        ffmpeg_path: Path to ffmpeg binary
        stream_url: Direct video stream URL
        timestamp_sec: Timestamp in seconds
        output_path: Output image path (e.g. .jpg or .png)
        http_headers: HTTP headers to pass to ffmpeg
        quality: JPEG quality (1=best, 31=worst). Ignored when hd_png=True.
        hd_png: If True, capture as lossless PNG for maximum clarity.

    Returns:
        True if successful
    """
    # Build ffmpeg command
    # -ss before -i = fast seek (input seeking)
    cmd = [ffmpeg_path]

    # Add HTTP headers if provided
    if http_headers:
        header_str = "\r\n".join(f"{k}: {v}" for k, v in http_headers.items())
        cmd.extend(["-headers", header_str])

    cmd.extend([
        "-ss", f"{timestamp_sec:.3f}",
        "-i", stream_url,
        "-frames:v", "1",
    ])

    # Output format-specific options
    if hd_png or output_path.lower().endswith(".png"):
        # PNG: lossless, no quality knob needed
        cmd.extend(["-c:v", "png"])
    else:
        # JPEG: -q:v 1 = highest quality
        cmd.extend(["-q:v", str(quality)])

    cmd.extend([
        "-y",  # overwrite
        output_path,
    ])

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode != 0:
            # Extract useful error info
            err = result.stderr.strip().split("\n")[-3:] if result.stderr else ["unknown error"]
            print(f"[WARN] ffmpeg error at {timestamp_sec:.1f}s: {' '.join(err)}")
            return False
        return os.path.isfile(output_path) and os.path.getsize(output_path) > 0
    except subprocess.TimeoutExpired:
        print(f"[WARN] ffmpeg timeout at {timestamp_sec:.1f}s")
        return False
    except Exception as e:
        print(f"[WARN] ffmpeg exception at {timestamp_sec:.1f}s: {e}")
        return False


# ==================== Sprite Sheet Fallback ====================

def get_videoshot(aid: int = None, bvid: str = None, cid: int = None, headers: dict = None) -> dict:
    """Fetch video snapshot (sprite sheet) data — LOW RESOLUTION fallback."""
    params = {"index": 1}
    if bvid:
        params["bvid"] = bvid
    elif aid:
        params["aid"] = aid
    if cid:
        params["cid"] = cid

    resp = requests.get(
        BILIBILI_VIDEOSHOT_API,
        params=params,
        headers=headers or DEFAULT_HEADERS,
        timeout=15,
    )
    resp.raise_for_status()
    data = resp.json()

    if data.get("code") != 0:
        raise RuntimeError(f"Videoshot API error: {data.get('message', 'Unknown error')}")

    shot_data = data["data"]

    index = shot_data.get("index", [])
    if not index and shot_data.get("pvdata"):
        index = _parse_pvdata(shot_data["pvdata"], headers or DEFAULT_HEADERS)

    return {
        "image": shot_data.get("image", []),
        "index": index,
        "img_x_len": shot_data.get("img_x_len", 10),
        "img_y_len": shot_data.get("img_y_len", 10),
        "img_x_size": shot_data.get("img_x_size", 160),
        "img_y_size": shot_data.get("img_y_size", 90),
    }


def _parse_pvdata(pvdata_url: str, headers: dict) -> list:
    """Parse binary pvdata into timestamp array."""
    if pvdata_url.startswith("//"):
        pvdata_url = "https:" + pvdata_url
    resp = requests.get(pvdata_url, headers=headers, timeout=15)
    resp.raise_for_status()
    raw = resp.content
    count = len(raw) // 2
    return list(struct.unpack(f">{count}H", raw))


def download_sprite_sheet(url: str, headers: dict) -> Image.Image:
    """Download a sprite sheet image."""
    if url.startswith("//"):
        url = "https:" + url
    resp = requests.get(url, headers=headers, timeout=30)
    resp.raise_for_status()
    return Image.open(BytesIO(resp.content))


def crop_frame_sprite(
    sprite: Image.Image,
    frame_index_in_sheet: int,
    img_x_len: int,
    img_y_len: int,
    img_x_size: int,
    img_y_size: int,
) -> Image.Image:
    """Crop a single frame from a sprite sheet."""
    row = frame_index_in_sheet // img_x_len
    col = frame_index_in_sheet % img_x_len
    left = col * img_x_size
    top = row * img_y_size
    return sprite.crop((left, top, left + img_x_size, top + img_y_size))


def find_nearest_frame(target_time: float, index: list) -> int:
    """Find the frame index closest to the target timestamp."""
    if not index:
        return 0
    best_idx = 0
    best_diff = abs(index[0] - target_time)
    for i, t in enumerate(index):
        diff = abs(t - target_time)
        if diff < best_diff:
            best_diff = diff
            best_idx = i
    return best_idx


# ==================== Timestamp Selection ====================

def select_timestamps_evenly(total_duration: float, count: int, margin: float = 5.0) -> list:
    """Select evenly-spaced timestamps across the video duration."""
    if count <= 0:
        return []
    if count == 1:
        return [total_duration / 2]
    start = min(margin, total_duration * 0.02)
    end = total_duration - min(margin, total_duration * 0.02)
    if start >= end:
        return [total_duration / 2]
    step = (end - start) / (count - 1)
    return [start + i * step for i in range(count)]


def select_timestamps_from_segments(segments: list, count: int) -> list:
    """Select timestamps aligned to subtitle segment boundaries (topic transitions)."""
    if not segments:
        return []

    gaps = []
    for i in range(1, len(segments)):
        prev_end = segments[i - 1].get("to", segments[i - 1].get("from", 0))
        curr_start = segments[i].get("from", 0)
        gap = curr_start - prev_end
        gaps.append((i, gap, curr_start))

    gaps.sort(key=lambda x: x[1], reverse=True)

    transition_times = [segments[0].get("from", 0)]
    for idx, gap, time in gaps[:count - 1]:
        transition_times.append(time)
    transition_times.sort()

    if len(transition_times) < count:
        total = segments[-1].get("to", segments[-1].get("from", 0))
        extra = select_timestamps_evenly(total, count - len(transition_times))
        transition_times.extend(extra)
        transition_times = sorted(set(transition_times))[:count]

    return transition_times


def select_timestamps_auto(index: list, segments: list, count: int, duration: float) -> list:
    """Auto-select best timestamps combining sprite index and subtitle segments."""
    if segments:
        return select_timestamps_from_segments(segments, count)
    elif index:
        if len(index) <= count:
            return [float(t) for t in index if t > 0]
        step = len(index) / count
        return [float(index[min(int(i * step), len(index) - 1)]) for i in range(count)]
    else:
        return select_timestamps_evenly(duration, count)


def format_timestamp(seconds: float) -> str:
    """Format seconds into MM:SS string."""
    m = int(seconds // 60)
    s = int(seconds % 60)
    return f"{m:02d}m{s:02d}s"


# ==================== Main Capture Logic ====================

def capture_screenshots(
    bvid: str,
    output_dir: str,
    part: int = 1,
    count: int = 10,
    timestamps: list = None,
    segments: list = None,
    auto: bool = False,
    cookie: str = "",
    force_sprite: bool = False,
) -> list:
    """
    Main function to capture HD screenshots from a Bilibili video.

    Strategy:
    1. Try yt-dlp + ffmpeg for original resolution (1080p+)
    2. Fall back to sprite-sheet mode if yt-dlp/ffmpeg unavailable

    Args:
        bvid: Video BV ID
        output_dir: Directory to save screenshots
        part: Video part number
        count: Number of screenshots to capture
        timestamps: Specific timestamps (seconds) to capture
        segments: Subtitle segments for smart timestamp selection
        auto: Auto-select best timestamps
        cookie: Bilibili cookie for auth
        force_sprite: Force use sprite-sheet mode (low-res)

    Returns:
        List of dicts: [{"path": str, "timestamp": float, "filename": str}, ...]
    """
    headers = dict(DEFAULT_HEADERS)
    if cookie:
        headers["Cookie"] = cookie

    # Step 1: Get video info
    print(f"[INFO] Fetching video info for {bvid}...")
    video_info = get_video_info(bvid, headers)
    print(f"[INFO] Title: {video_info['title']}")

    if part < 1 or part > len(video_info["pages"]):
        raise ValueError(f"Part {part} out of range (1-{len(video_info['pages'])})")

    page = video_info["pages"][part - 1]
    cid = page["cid"]
    duration = page.get("duration", video_info["duration"])
    print(f"[INFO] Part {part}: {page['part']} (duration: {duration}s, cid: {cid})")

    # Step 2: Get sprite shot index for timestamp selection (even in HD mode)
    print("[INFO] Fetching videoshot index for timestamp selection...")
    shot_data = None
    index = []
    try:
        shot_data = get_videoshot(bvid=bvid, cid=cid, headers=headers)
        index = shot_data.get("index", [])
        print(f"[INFO] Sprite index frames: {len(index)}")
    except Exception as e:
        print(f"[WARN] Could not fetch videoshot index: {e}")

    # Step 3: Determine target timestamps
    if timestamps:
        target_times = timestamps
    elif auto or segments:
        target_times = select_timestamps_auto(index, segments, count, duration)
    else:
        target_times = select_timestamps_evenly(duration, count)

    print(f"[INFO] Target timestamps ({len(target_times)}): "
          f"{[format_timestamp(t) for t in target_times[:5]]}{'...' if len(target_times) > 5 else ''}")

    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    # Step 4: Decide capture method
    ffmpeg_path = find_ffmpeg() if not force_sprite else ""
    use_hd = False

    if ffmpeg_path and not force_sprite:
        print(f"[INFO] ffmpeg found: {ffmpeg_path}")
        print("[INFO] Attempting HD capture via yt-dlp + ffmpeg...")

        stream_info = get_stream_url_ytdlp(bvid, part, cookie)
        if stream_info and stream_info.get("url"):
            use_hd = True
            res_str = f"{stream_info.get('width', '?')}x{stream_info.get('height', '?')}"
            print(f"[INFO] Stream resolution: {res_str}")
            print(f"[INFO] Stream format: {stream_info.get('format', 'unknown')}")
        else:
            print("[WARN] Could not get stream URL, falling back to sprite-sheet mode")

    if not use_hd:
        print("[INFO] Using sprite-sheet mode (lower resolution)")
        if not shot_data or not shot_data.get("image"):
            raise RuntimeError("No videoshot data available and HD mode failed.")

    # Step 5: Capture frames
    results = []

    if use_hd:
        # ===== HD MODE: ffmpeg + remote stream =====
        stream_url = stream_info["url"]
        http_headers = stream_info.get("http_headers", {})
        # Ensure Referer is set
        if "Referer" not in http_headers:
            http_headers["Referer"] = "https://www.bilibili.com"

        for i, target_time in enumerate(target_times):
            ts_str = format_timestamp(target_time)
            filename = f"frame_{i + 1:03d}_{ts_str}.png"
            filepath = str(output_path / filename)

            print(f"[INFO] Capturing frame {i + 1}/{len(target_times)} at {ts_str}...", end=" ")

            success = capture_frame_ffmpeg(
                ffmpeg_path=ffmpeg_path,
                stream_url=stream_url,
                timestamp_sec=target_time,
                output_path=filepath,
                http_headers=http_headers,
                quality=1,  # highest JPEG quality (fallback)
                hd_png=True,  # lossless PNG for HD captures
            )

            if success:
                # Get actual image dimensions
                try:
                    img = Image.open(filepath)
                    w, h = img.size
                    img.close()
                    print(f"OK ({w}x{h})")
                except:
                    w, h = 0, 0
                    print("OK")

                results.append({
                    "path": filepath,
                    "timestamp": target_time,
                    "filename": filename,
                    "index": i + 1,
                    "width": w,
                    "height": h,
                    "mode": "hd",
                })
            else:
                print("FAILED")
                # Try sprite-sheet fallback for this specific frame
                if shot_data and shot_data.get("image"):
                    print(f"  [INFO] Trying sprite-sheet fallback for this frame...")
                    fallback = _capture_sprite_frame(
                        shot_data, index, target_time, i, output_path, headers
                    )
                    if fallback:
                        results.append(fallback)
    else:
        # ===== SPRITE SHEET MODE (fallback) =====
        frames_per_sheet = shot_data["img_x_len"] * shot_data["img_y_len"]
        sprite_cache = {}

        for i, target_time in enumerate(target_times):
            frame = _capture_sprite_frame(
                shot_data, index, target_time, i, output_path, headers
            )
            if frame:
                results.append(frame)

    print(f"\n[SUCCESS] Captured {len(results)} screenshots to: {output_path}")

    # Summarize resolution
    hd_count = sum(1 for r in results if r.get("mode") == "hd")
    sprite_count = sum(1 for r in results if r.get("mode") == "sprite")
    if hd_count > 0:
        # Get typical resolution
        hd_frames = [r for r in results if r.get("mode") == "hd" and r.get("width")]
        if hd_frames:
            print(f"[INFO] HD frames: {hd_count} ({hd_frames[0]['width']}x{hd_frames[0]['height']})")
    if sprite_count > 0:
        print(f"[INFO] Sprite-sheet frames (low-res): {sprite_count}")

    # Step 6: Generate manifest JSON
    manifest = {
        "video_title": video_info["title"],
        "bvid": bvid,
        "part": part,
        "duration": duration,
        "frame_count": len(results),
        "output_dir": str(output_path),
        "capture_mode": "hd" if use_hd else "sprite",
        "frames": results,
    }

    manifest_path = output_path / "manifest.json"
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)
    print(f"[INFO] Manifest saved to: {manifest_path}")

    return results


# Sprite sheet cache for fallback (module-level to avoid re-downloading)
_sprite_cache = {}


def _capture_sprite_frame(
    shot_data: dict,
    index: list,
    target_time: float,
    frame_i: int,
    output_path: Path,
    headers: dict,
) -> dict:
    """Capture a single frame using sprite-sheet mode (fallback, low-res)."""
    global _sprite_cache

    frames_per_sheet = shot_data["img_x_len"] * shot_data["img_y_len"]
    frame_global_idx = find_nearest_frame(target_time, index)
    actual_time = index[frame_global_idx] if frame_global_idx < len(index) else target_time

    sheet_idx = frame_global_idx // frames_per_sheet
    frame_in_sheet = frame_global_idx % frames_per_sheet

    if sheet_idx >= len(shot_data["image"]):
        return None

    if sheet_idx not in _sprite_cache:
        url = shot_data["image"][sheet_idx]
        _sprite_cache[sheet_idx] = download_sprite_sheet(url, headers)

    frame = crop_frame_sprite(
        _sprite_cache[sheet_idx],
        frame_in_sheet,
        shot_data["img_x_len"],
        shot_data["img_y_len"],
        shot_data["img_x_size"],
        shot_data["img_y_size"],
    )

    ts_str = format_timestamp(actual_time)
    filename = f"frame_{frame_i + 1:03d}_{ts_str}.jpg"
    filepath = output_path / filename
    frame.save(filepath, "JPEG", quality=90)

    return {
        "path": str(filepath),
        "timestamp": actual_time,
        "filename": filename,
        "index": frame_i + 1,
        "width": frame.width,
        "height": frame.height,
        "mode": "sprite",
    }


# ==================== CLI ====================

def main():
    parser = argparse.ArgumentParser(
        description="Capture HD screenshots from Bilibili videos (yt-dlp + ffmpeg)"
    )
    parser.add_argument("video", help="Bilibili video URL or BV ID")
    parser.add_argument("--output-dir", "-o", required=True, help="Output directory for screenshots")
    parser.add_argument("--part", "-p", type=int, default=None, help="Part number (default: auto-detect)")
    parser.add_argument("--count", "-n", type=int, default=10, help="Number of screenshots (default: 10)")
    parser.add_argument("--timestamps", "-t", default="",
                        help="Specific timestamps in seconds, comma-separated")
    parser.add_argument("--segments-json", default="",
                        help="Path to subtitle segments JSON for smart selection")
    parser.add_argument("--auto", action="store_true", help="Auto-select best timestamps")
    parser.add_argument("--cookie", default="", help="Bilibili cookie string")
    parser.add_argument("--cookie-file", default="", help="Path to cookie file")
    parser.add_argument("--sprite-fallback", action="store_true",
                        help="Force sprite-sheet mode (low resolution, no ffmpeg needed)")
    args = parser.parse_args()

    bvid = parse_bvid(args.video)
    part = args.part if args.part else parse_part_number(args.video)

    # Parse timestamps
    timestamps = None
    if args.timestamps:
        timestamps = [float(t.strip()) for t in args.timestamps.split(",") if t.strip()]

    # Parse segments JSON
    segments = None
    if args.segments_json:
        seg_path = Path(args.segments_json)
        if seg_path.exists():
            with open(seg_path, "r", encoding="utf-8") as f:
                segments = json.load(f)
            print(f"[INFO] Loaded {len(segments)} subtitle segments")

    # Cookie
    cookie = args.cookie or os.environ.get("BILIBILI_COOKIE", "")
    if not cookie and args.cookie_file:
        cookie_path = Path(args.cookie_file)
        if cookie_path.exists():
            cookie = cookie_path.read_text(encoding="utf-8").strip()
    if not cookie:
        auto_cookie = Path(__file__).parent.parent / "cookie.txt"
        if auto_cookie.exists():
            cookie = auto_cookie.read_text(encoding="utf-8").strip()
            print(f"[INFO] Auto-loaded cookie from: {auto_cookie}")

    try:
        results = capture_screenshots(
            bvid=bvid,
            output_dir=args.output_dir,
            part=part,
            count=args.count,
            timestamps=timestamps,
            segments=segments,
            auto=args.auto or bool(segments),
            cookie=cookie,
            force_sprite=args.sprite_fallback,
        )
    except Exception as e:
        print(f"[ERROR] {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

    if not results:
        print("[WARN] No screenshots captured.")
        sys.exit(0)

    # Print summary
    print(f"\n{'='*60}")
    print(f"Screenshots captured: {len(results)}")
    for r in results:
        res_str = f"{r.get('width', '?')}x{r.get('height', '?')}"
        mode_str = "[HD]" if r.get("mode") == "hd" else "[sprite]"
        print(f"  [{r['index']:>3}] {format_timestamp(r['timestamp'])} -> {r['filename']}  {res_str} {mode_str}")


if __name__ == "__main__":
    main()
