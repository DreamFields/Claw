#!/usr/bin/env node
/**
 * md2notion upload script
 * 
 * Upload Markdown files + images to Notion via markdown-upload-to-notion server.
 * 
 * Usage:
 *   node upload.js --token <NOTION_TOKEN> --parent <PAGE_ID> --dir <NOTES_DIR> [--server <SERVER_URL>]
 * 
 * Arguments:
 *   --token   Notion Integration Token (secret_xxx or ntn_xxx)
 *   --parent  Target parent page ID (with or without dashes)
 *   --dir     Path to the notes directory containing .md files and images
 *   --server  (Optional) Server URL, default: http://localhost:3000
 *   --target  (Optional) "page" or "database", default: "page"
 */

const fs = require('fs');
const path = require('path');
const FormData = require('form-data');
const fetch = require('node-fetch');

// ─── Parse CLI arguments ────────────────────────────────────────────
function parseArgs() {
    const args = process.argv.slice(2);
    const parsed = {};
    for (let i = 0; i < args.length; i += 2) {
        const key = args[i].replace(/^--/, '');
        parsed[key] = args[i + 1];
    }
    return parsed;
}

const args = parseArgs();

const SERVER_URL = args.server || 'http://localhost:3000';
const NOTION_TOKEN = args.token;
const PARENT_ID = args.parent;
const NOTES_DIR = args.dir;
const TARGET = args.target || 'page';

if (!NOTION_TOKEN || !PARENT_ID || !NOTES_DIR) {
    console.error('Usage: node upload.js --token <TOKEN> --parent <PAGE_ID> --dir <NOTES_DIR>');
    console.error('  --token   Notion Integration Token');
    console.error('  --parent  Target parent page ID');
    console.error('  --dir     Notes directory path');
    console.error('  --server  (Optional) Server URL, default: http://localhost:3000');
    console.error('  --target  (Optional) "page" or "database", default: "page"');
    process.exit(1);
}

// ─── Image extensions ───────────────────────────────────────────────
const IMAGE_EXTS = new Set(['.png', '.jpg', '.jpeg', '.gif', '.webp', '.svg', '.bmp']);

// ─── Recursively collect all image files from a directory ───────────
function collectImages(dir) {
    const results = [];
    if (!fs.existsSync(dir)) return results;

    const entries = fs.readdirSync(dir, { withFileTypes: true });
    for (const entry of entries) {
        const fullPath = path.join(dir, entry.name);
        if (entry.isDirectory()) {
            results.push(...collectImages(fullPath));
        } else if (IMAGE_EXTS.has(path.extname(entry.name).toLowerCase())) {
            results.push({ name: entry.name, path: fullPath });
        }
    }
    return results;
}

// ─── Collect all .md files from a directory (non-recursive) ─────────
function collectMarkdownFiles(dir) {
    const results = [];
    const entries = fs.readdirSync(dir, { withFileTypes: true });
    for (const entry of entries) {
        if (!entry.isDirectory() && entry.name.endsWith('.md')) {
            results.push({ name: entry.name, path: path.join(dir, entry.name) });
        }
    }
    return results;
}

// ─── Main ───────────────────────────────────────────────────────────
async function main() {
    // 1. Check server health
    try {
        const healthRes = await fetch(`${SERVER_URL}/api/health`);
        if (!healthRes.ok) throw new Error(`Status ${healthRes.status}`);
        console.log(`[OK] Server is running at ${SERVER_URL}`);
    } catch (e) {
        console.error(`[ERROR] Cannot reach server at ${SERVER_URL}`);
        console.error('  Start the server first:');
        console.error('  cd <markdown-upload-to-notion dir> && node server.js');
        process.exit(1);
    }

    // 2. Collect files
    const mdFiles = collectMarkdownFiles(NOTES_DIR);
    if (mdFiles.length === 0) {
        console.error(`[ERROR] No .md files found in ${NOTES_DIR}`);
        process.exit(1);
    }

    const imageFiles = collectImages(NOTES_DIR);
    console.log(`Found ${mdFiles.length} Markdown file(s) and ${imageFiles.length} image(s)`);

    // 3. Build FormData
    const formData = new FormData();
    formData.append('token', NOTION_TOKEN);
    formData.append('target', TARGET);
    formData.append('targetId', PARENT_ID);

    // Add markdown files
    for (const md of mdFiles) {
        const buffer = fs.readFileSync(md.path);
        formData.append('files', buffer, {
            filename: md.name,
            contentType: 'text/markdown'
        });
        console.log(`  [MD] ${md.name} (${(buffer.length / 1024).toFixed(1)} KB)`);
    }

    // Add image files
    for (const img of imageFiles) {
        const buffer = fs.readFileSync(img.path);
        const ext = path.extname(img.name).toLowerCase();
        const mimeMap = {
            '.png': 'image/png', '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg',
            '.gif': 'image/gif', '.webp': 'image/webp', '.svg': 'image/svg+xml',
            '.bmp': 'image/bmp'
        };
        formData.append('files', buffer, {
            filename: img.name,
            contentType: mimeMap[ext] || 'image/png'
        });
    }
    console.log(`  [IMG] ${imageFiles.length} images added`);

    // 4. Upload
    console.log(`\nUploading to Notion...`);
    console.log(`  Target: ${TARGET} ${PARENT_ID}`);
    console.log(`  Files: ${mdFiles.length} MD + ${imageFiles.length} images\n`);

    const response = await fetch(`${SERVER_URL}/api/batch-upload`, {
        method: 'POST',
        body: formData,
        headers: formData.getHeaders()
    });

    if (!response.ok) {
        const errorText = await response.text();
        console.error(`[ERROR] Upload failed (${response.status}):`, errorText);
        process.exit(1);
    }

    const result = await response.json();

    if (result.success) {
        console.log('\n=== Upload Complete ===');
        console.log(`  Images uploaded: ${result.results.uploadedImages}`);
        console.log(`  Pages created:   ${result.results.uploadedPages}`);
        if (result.results.pages) {
            for (const page of result.results.pages) {
                console.log(`  Page: ${page.title}`);
                console.log(`  URL:  ${page.url}`);
            }
        }
        if (result.results.errors && result.results.errors.length > 0) {
            console.log(`\n  Warnings:`);
            result.results.errors.forEach(e => console.log(`    - ${e}`));
        }
    } else {
        console.error('[ERROR] Upload failed:', JSON.stringify(result, null, 2));
        process.exit(1);
    }
}

main().catch(err => {
    console.error('[FATAL]', err.message);
    process.exit(1);
});
