---
name: md2notion
description: Upload Markdown files with local images to Notion. This skill should be used when the user wants to upload, import, or sync Markdown notes (especially those containing local image references) to Notion pages or databases. Triggers include mentions of "upload to Notion", "import markdown to Notion", "md to notion", "notes to Notion", or any request involving transferring .md files with screenshots/images to Notion. Handles the complete workflow: server startup, image upload via Notion File Upload API, Markdown parsing, and page creation.
---

# md2notion

## Overview

Upload Markdown files with embedded local images to Notion pages or databases. This skill orchestrates the [markdown-upload-to-notion](https://github.com/starding/markdown-upload-to-notion) server to handle the complete pipeline: image compression and upload via Notion's File Upload API, Markdown-to-Notion-blocks parsing, and batch page creation with automatic large-document splitting.

## Core Principle: Semantic Block Correctness

**Every block sent to Notion must be a semantically correct Notion native type.** No Markdown syntax should leak into paragraph text.

### Rule 1: Markdown Content → Must Convert to Notion Block Types

If the uploaded content is Markdown format (e.g., local `.md` files), Markdown syntax **must** be converted to the corresponding Notion Block types. Never pass raw Markdown as plain text:

- `# heading` → `heading_1` block, **NOT** a paragraph containing `# ` prefix
- `## heading` → `heading_2` block
- `### heading` → `heading_3` block
- `####` ~ `######` → downgrade to `heading_3` (Notion only supports 3 heading levels)
- `- item` / `* item` / `+ item` → `bulleted_list_item` block, **NOT** a paragraph containing `- ` prefix
- `1. item` → `numbered_list_item` block
- `- [ ] task` → `to_do` block (unchecked)
- `- [x] task` → `to_do` block (checked)
- ` ```lang ... ``` ` → `code` block with language, **NOT** paragraph + code annotation
- `> quote` → `quote` block, **NOT** a paragraph containing `> ` prefix
- `---` / `***` / `___` → `divider` block, **NOT** an empty paragraph
- `![alt](path)` → `image` block (with uploaded file ID)
- `| A | B | ... |` → `table` + `table_row` blocks
- `**bold**` / `*italic*` / `` `code` `` / `~~strike~~` → `rich_text` with proper `annotations`
- `***bold+italic***` → `rich_text` with both `bold` and `italic` annotations
- `[text](url)` → `rich_text` with `link`

### Rule 2: Non-Markdown Content → Must Use Notion Block Format

If the uploaded content is not Markdown (e.g., conversation summaries, free-form text), content **must** be organized using Notion Block native types directly (`heading_1`/`heading_2`/`heading_3` for headings, `bulleted_list_item` for bullet points, `code` for code, `table` for tables, etc.), rather than dumping everything into `paragraph` blocks.

**One-sentence summary**: Every block Notion receives should be the semantically correct Notion native type.

## Prerequisites

The following must be available on the system:

| Dependency | Location | Notes |
|---|---|---|
| **markdown-upload-to-notion** | `C:\Users\vinmeng\WorkBuddy\markdown-upload-to-notion` | Already cloned and `npm install` completed |
| **Node.js** | System PATH | v14+ required |
| **Notion Integration Token** | User must provide | `ntn_xxx` or `secret_xxx` format |

## Workflow

### Step 1 — Gather Information

Before executing anything, collect the following from the user or infer from context:

1. **Notes directory** — Absolute path to the folder containing `.md` files and images
2. **Notion token** — The Notion Integration Token. Check if the user has previously provided one in the conversation. If a Notion MCP server is configured, the token may already be available.
3. **Parent page ID** — The Notion page ID under which new pages will be created. Can be a URL (extract the 32-char hex ID) or a raw ID with/without dashes.

If any of these cannot be determined, ask the user.

### Step 2 — Start the Server

Run the server startup script to ensure the markdown-upload-to-notion service is available:

```bash
node "<skill-base-dir>/scripts/start_server.js"
```

This script:
- Checks if the server is already running on port 3000
- If not, starts `server.js` in detached mode
- Waits for the health check endpoint to respond
- Exits with code 0 on success

If the server fails to start, verify that the project directory exists and dependencies are installed:
```bash
cd C:\Users\vinmeng\WorkBuddy\markdown-upload-to-notion && npm install
```

### Step 3 — Upload Notes

Run the upload script:

```bash
node "<skill-base-dir>/scripts/upload.js" --token <TOKEN> --parent <PAGE_ID> --dir <NOTES_DIR>
```

**Parameters:**

| Flag | Required | Description |
|---|---|---|
| `--token` | Yes | Notion Integration Token |
| `--parent` | Yes | Parent page ID (32-char hex, dashes optional) |
| `--dir` | Yes | Path to notes directory |
| `--server` | No | Server URL (default: `http://localhost:3000`) |
| `--target` | No | `"page"` or `"database"` (default: `"page"`) |

The script automatically:
1. Collects all `.md` files from the directory root
2. Recursively collects all images (`.png`, `.jpg`, `.jpeg`, `.gif`, `.webp`, `.svg`, `.bmp`) from subdirectories
3. Sends everything to the server's `/api/batch-upload` endpoint
4. Reports created page URLs on completion

### Step 4 — Verify Results

After upload completes, confirm success by:
1. Checking the script output for page URLs and error counts
2. Optionally using the Notion MCP (`API-get-block-children`) to verify blocks and images were created correctly

## Markdown → Notion Block Conversion Reference

The server's `parseMarkdownToBlocks()` function handles the following conversions:

### Block-Level Conversions

| Markdown Syntax | Notion Block Type | Notes |
|---|---|---|
| `# Title` | `heading_1` | ATX-style headings |
| `## Title` | `heading_2` | |
| `### Title` | `heading_3` | |
| `####` ~ `######` | `heading_3` | Downgraded (Notion max = 3 levels) |
| `## Title ##` | `heading_2` | Trailing `#` stripped |
| `- item` / `* item` / `+ item` | `bulleted_list_item` | All three bullet chars supported |
| `  - sub-item` | `bulleted_list_item` (nested) | 2-space indent = 1 nesting level, via `children` |
| `1. item` | `numbered_list_item` | |
| `  1. sub-item` | `numbered_list_item` (nested) | Same nesting logic |
| `- [ ] task` | `to_do` (`checked: false`) | Task list / checkbox |
| `- [x] task` / `- [X] task` | `to_do` (`checked: true`) | Case-insensitive x |
| ` ```lang\n...\n``` ` | `code` | Language extracted; defaults to `plain text` |
| `> line1\n> line2` | `quote` | Consecutive `>` lines merge into one block |
| `---` / `***` / `___` | `divider` | 3+ chars of `-`, `*`, or `_` |
| `![alt](path)` | `image` | Matches by `path.basename()` in imageMap |
| `\| A \| B \|\n\| --- \| --- \|\n\| 1 \| 2 \|` | `table` + `table_row` | Header detection via separator line; supports alignment markers |
| Everything else (non-empty) | `paragraph` | Fallback for unrecognized content |

### Inline / Rich Text Conversions

| Markdown | Notion rich_text annotation |
|---|---|
| `**bold**` / `__bold__` | `{ bold: true }` |
| `*italic*` / `_italic_` | `{ italic: true }` |
| `***bold+italic***` / `___both___` | `{ bold: true, italic: true }` |
| `` `code` `` | `{ code: true }` |
| `~~strikethrough~~` | `{ strikethrough: true }` |
| `[text](url)` | `text.link.url` set |

### Edge Cases Handled

- **Windows `\r\n` line endings** — Normalized to `\n` before parsing (prevents regex failures)
- **Blank lines between list items** — Skipped; does not break list continuity
- **Multi-line blockquotes** — Consecutive `>` lines merged into one `quote` block
- **H4-H6 headings** — Downgraded to `heading_3`
- **Table alignment markers** (`:---`, `:---:`, `---:`) — Parsed as separator, alignment not sent to Notion (Notion doesn't support column alignment)
- **Table cell count mismatch** — Cells padded/truncated to match header column count
- **Images not found in imageMap** — Fallback to `[图片未找到: filename]` paragraph

## How It Works (Under the Hood)

Understanding the internals helps diagnose issues:

1. **Image upload** — Each image is uploaded via Notion's File Upload API (2-step process: create upload object → send binary data). Images > 5MB are automatically compressed using `sharp`.
2. **Markdown parsing** — Custom parser converts Markdown to Notion block objects. See the conversion reference above for full details.
3. **Image matching** — The parser matches `![alt](path)` references to uploaded images by **filename only** (not full path). This means image filenames must be unique across all subdirectories.
4. **Large document splitting** — Notion API limits 100 blocks per request. Documents exceeding this are automatically split: first 100 blocks create the page, remaining blocks are appended in batches of 100.

## Troubleshooting

| Problem | Cause | Fix |
|---|---|---|
| "Cannot reach server" | Server not started | Run `start_server.js` first |
| Images show as "[图片未找到]" | Filename mismatch between Markdown reference and actual file | Ensure image filenames in `![](path)` match the actual file names |
| Duplicate image filenames | Two images in different subdirs have the same name | Rename one of them; the parser matches by basename only |
| Upload timeout | Too many large images | The server compresses images > 5MB, but many large files can be slow. Be patient or pre-compress. |
| Chinese filename garbled | Encoding issue | The server handles `latin1 → utf-8` conversion automatically; if still broken, ensure terminal uses UTF-8 |
| List items render as paragraphs | Windows `\r\n` not normalized | Already fixed — `parseMarkdownToBlocks` normalizes `\r\n` → `\n` |
| Headings show with `#` prefix | Markdown not parsed | Server converts `# Title` → `heading_1` block; if still broken, check if content reaches `parseMarkdownToBlocks()` |
| Table shows as plain text | No separator line detected | Ensure table has a `| --- | --- |` separator line between header and body |

## Typical Directory Structures

The skill handles these common note layouts:

```
# Flat layout (images alongside markdown)
notes/
├── my-notes.md
├── screenshot1.png
└── screenshot2.jpg

# Nested layout (images in subdirectory)
notes/
├── lecture-notes.md
└── screenshots/
    ├── img001.png
    └── img002.png

# Multi-level nested (e.g., video segmented screenshots)
notes/
├── video-notes.md
└── screenshots/
    ├── seg_000/
    │   ├── seg000_f001_00m03s.png
    │   └── seg000_f002_00m35s.png
    └── seg_001/
        ├── seg001_f001_05m12s.png
        └── seg001_f002_07m44s.png
```

All layouts are supported — images are collected recursively from all subdirectories.
