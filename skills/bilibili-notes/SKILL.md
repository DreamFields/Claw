---
name: bilibili-notes
description: >
  This skill should be used when users want to generate technical notes, summaries,
  or study materials from Bilibili (B站) videos. Trigger phrases include "B站笔记",
  "bilibili笔记", "从视频生成笔记", "视频总结", "B站视频摘要", or when users
  provide a Bilibili video URL and ask for notes, summaries, or key takeaways.
  Also triggers when users mention extracting subtitles or transcripts from B站 videos.
---

# Bilibili Video to Technical Notes (v4 — Smart Pipeline)

Generate structured technical notes from Bilibili videos using a **3-step intelligent pipeline**:

1. **切片总结** — 将字幕按时间段切片，逐段 LLM 总结
2. **并行抓帧** — 对每个时间段密集抓帧 + 感知哈希去重
3. **权重分配** — 根据主题数和字数，将截图按权重插入对应主题前

## Workflow

### Step 1: Parse Video URL

Parse the Bilibili video URL from user input. Supported formats:
- `https://www.bilibili.com/video/BVxxxxxxxxxx`
- `https://b23.tv/xxxxxx` (short link)
- Raw BV number like `BV1xx411x7xx`
- Multi-part videos with `?p=N` parameter

### Step 2: Ask User Preferences

Before generating, ask the user (using `ask_followup_question`):

1. **Detail level** (1-5):
   - 1 = Brief: Quick summary, 5-8 bullet points (~300 chars)
   - 2 = Concise: Key points with short explanations (~1 page)
   - 3 = Standard: Structured notes with sections (~2-3 pages) **[default]**
   - 4 = Detailed: Comprehensive with code, quotes (~4-6 pages)
   - 5 = Exhaustive: Near-transcript detail (~8+ pages)

2. **Segment length** (3-10 minutes, default: 5):
   - Shorter segments → more granular topics, more screenshots
   - Longer segments → bigger-picture summaries, fewer screenshots

3. **Note style** (optional, default: technical):
   - `technical` — Structured technical notes
   - `summary` — Concise bullet-point summary
   - `detailed` — Comprehensive with timestamps
   - `study` — Q&A format for review

**If user says "详细一点" or "需要更多细节" → use detail level 4 or 5.**
**If user says "简单总结" → use detail level 1 or 2.**
**Default to detail level 3, segment 5 min if not specified.**

### Step 3: Run Smart Pipeline (one command does everything)

**Recommended approach — use `smart_notes_pipeline.py`:**

```bash
python {SKILL_DIR}/scripts/smart_notes_pipeline.py <video_url_or_bvid> \
  --output-dir <output_dir> \
  --segment-minutes 5 \
  --detail-level 3 \
  --style technical
```

This single command executes the full 3-step pipeline:

#### Pipeline Step 1 — Slice & Summarize

- Extracts subtitles via Bilibili API
- Cuts subtitles into time-based segments (default 5 min each)
- For each segment, calls LLM to produce a structured summary with:
  - Topic headings (`### 知识点标题`)
  - Key concepts and explanations
  - Practical takeaways

#### Pipeline Step 2 — Parallel Frame Capture + Dedup

- Runs in parallel with summarization (ThreadPool)
- Uses yt-dlp + ffmpeg to capture dense frames (2 frames/minute by default)
- For each segment, captures frames at even intervals across the time range
- **Perceptual hash deduplication**: removes visually identical frames (e.g., static slides)
- Stores frames organized by segment: `screenshots/seg_001/`, `screenshots/seg_002/`, etc.

#### Pipeline Step 3 — Weighted Image Insertion

- For each segment, counts the topics and their character lengths
- Allocates frames to topics proportionally:
  - Each topic gets at least 1 frame
  - Heavier topics (more text) get more frames
- Inserts frames **before** each topic heading in the Markdown
- Final assembly produces a single `.md` file with inline screenshots

### Step 4: Present Results

After generation, open the resulting Markdown file using `open_result_view`.

### Alternative: Individual Scripts

The pipeline script internally uses these standalone scripts, which can also be run separately:

#### Extract Subtitles Only

```bash
python {SKILL_DIR}/scripts/extract_subtitles.py <video_url_or_bvid> --output <output_path>
```

#### Capture Screenshots Only

```bash
python {SKILL_DIR}/scripts/capture_screenshots.py <video_url_or_bvid> \
  --output-dir <screenshots_dir> \
  --auto \
  --segments-json <segments_json_path> \
  --count <N>
```

#### Generate Notes Only (legacy, without pipeline)

```bash
python {SKILL_DIR}/scripts/generate_notes.py <subtitle_file> \
  --output <output_path> \
  --style <style> \
  --detail-level <1-5> \
  --screenshot-dir <screenshots_dir>
```

### Option B: Using WorkBuddy's AI directly (when no API key)

When `OPENAI_API_KEY` is not set, the agent should:
1. Run the pipeline with `--no-screenshots` (or run extract_subtitles.py separately)
2. Read the full subtitle text and segments JSON
3. Manually perform the 3-step process using its own AI capability
4. Use capture_screenshots.py separately for frames

## File Structure

After running the smart pipeline, the output structure looks like:

```
output_dir/
├── subtitles.txt                    # Raw subtitle text
├── subtitles.segments.json          # Subtitle segments with timestamps
├── segment_001_summary.md           # Per-segment summary
├── segment_002_summary.md
├── ...
├── screenshots/
│   ├── seg_001/                     # Frames for segment 1 (lossless PNG)
│   │   ├── seg001_f001_01m30s.png
│   │   ├── seg001_f002_02m45s.png
│   │   └── ...
│   ├── seg_002/                     # Frames for segment 2
│   │   └── ...
│   └── ...
├── Video_Title_笔记.md              # Final notes with inline screenshots
├── Video_Title_笔记_纯文字.md       # Clean version without images
└── pipeline_manifest.json           # Pipeline metadata and stats
```

## Pipeline Parameters

| Parameter | Default | Description |
|-----------|---------|-------------|
| `--segment-minutes` | 5 | Minutes per segment (3-10) |
| `--detail-level` | 3 | LLM detail level 1-5 |
| `--style` | technical | Note style |
| `--frames-per-minute` | 2 | Capture density |
| `--dedup-threshold` | 8 | Perceptual hash threshold (lower = stricter dedup) |
| `--no-screenshots` | false | Skip frame capture |

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `OPENAI_API_KEY` | (optional) | API key for LLM-based note generation |
| `OPENAI_BASE_URL` | `https://api.openai.com/v1` | API base URL |
| `OPENAI_MODEL` | `gpt-4o` | Model name |
| `BILIBILI_COOKIE` | (optional) | Browser cookie for AI subtitles |

## Dependencies

| Package | Required For | Install |
|---------|-------------|---------|
| `requests` | All scripts | `pip install requests` |
| `Pillow` | Screenshot capture + dedup | `pip install Pillow` |
| `yt-dlp` | HD screenshots (stream URL extraction) | `pip install yt-dlp` |
| `imageio-ffmpeg` | HD screenshots (bundled ffmpeg binary) | `pip install imageio-ffmpeg` |
| `openai` | LLM note generation | `pip install openai` |
| `playwright` | Cookie acquisition (optional) | `pip install playwright && python -m playwright install chromium` |

> **Note:** If `yt-dlp` and `imageio-ffmpeg` are not installed, screenshots will be skipped.
> The pipeline still works for subtitle extraction and summarization without them.

## Cookie Management

The scripts auto-detect `{SKILL_DIR}/cookie.txt` for Bilibili authentication.

To acquire a cookie:
```bash
python {SKILL_DIR}/scripts/get_bilibili_cookie.py
```
This opens a browser window for QR code login and saves the cookie automatically.

## Troubleshooting

- **No subtitles found**: Video needs AI-generated or manually uploaded subtitles. Try setting up cookie first.
- **Screenshots are low resolution**: Make sure `yt-dlp` and `imageio-ffmpeg` are installed. Without them, HD capture is unavailable. HD mode outputs lossless PNG at the source stream's native resolution (1080p or higher when available). The format selector aggressively prefers 4K > 1080p60 > 1080p > 720p streams.
- **Too many duplicate frames**: Lower `--dedup-threshold` (e.g., 5) for stricter dedup. This is common for lecture videos with static slides.
- **Segments too short/long**: Adjust `--segment-minutes` (3-10). Shorter = more granular, longer = bigger picture.
- **LLM summarization skipped**: Set `OPENAI_API_KEY` environment variable. Without it, raw subtitles are used.
- **Cookie expired**: Re-run `get_bilibili_cookie.py` to refresh.
- **Notes too brief/verbose**: Adjust `--detail-level` (1-5) to match your needs.
