#!/usr/bin/env python3
"""
Bilibili Cookie Getter (via Playwright)

Opens a Chromium browser, navigates to Bilibili login page,
waits for the user to scan QR code, then saves the SESSDATA cookie
to a local file for subsequent subtitle extraction.

Usage:
    python get_bilibili_cookie.py [--output <cookie_file>]

Flow:
    1. Opens bilibili.com login page in a visible browser
    2. User scans QR code with Bilibili mobile app
    3. Script detects login success, extracts cookies
    4. Saves cookie string to file & prints SESSDATA

Requirements:
    pip install playwright
    python -m playwright install chromium
"""

import argparse
import json
import sys
import time
from pathlib import Path

try:
    from playwright.sync_api import sync_playwright
except ImportError:
    print("ERROR: playwright is required. Install with:")
    print("  pip install playwright")
    print("  python -m playwright install chromium")
    sys.exit(1)


# ==================== Constants ====================

BILIBILI_LOGIN_URL = "https://passport.bilibili.com/login"
BILIBILI_HOME_URL = "https://www.bilibili.com"
DEFAULT_COOKIE_FILE = Path(__file__).parent.parent / "cookie.txt"
LOGIN_TIMEOUT_SEC = 120  # 2 minutes to scan QR code


# ==================== Core Logic ====================

def get_cookie_via_browser(cookie_output: Path, headless: bool = False) -> str:
    """
    Launch browser, let user login via QR scan, then extract cookies.
    
    Returns the full cookie string.
    """
    print("=" * 60)
    print("  Bilibili Cookie Getter")
    print("=" * 60)
    print()
    print("[INFO] Launching browser...")
    print("[INFO] Please scan the QR code with the Bilibili app.")
    print(f"[INFO] You have {LOGIN_TIMEOUT_SEC} seconds to complete login.")
    print()

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless)
        context = browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/125.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1280, "height": 800},
        )
        page = context.new_page()

        # Navigate to login page
        print("[INFO] Opening Bilibili login page...")
        page.goto(BILIBILI_LOGIN_URL, wait_until="domcontentloaded")
        time.sleep(2)

        # Wait for user to login (poll for SESSDATA cookie)
        print("[INFO] Waiting for QR code scan and login...")
        print()

        start = time.time()
        sessdata = None

        while time.time() - start < LOGIN_TIMEOUT_SEC:
            cookies = context.cookies("https://www.bilibili.com")
            for c in cookies:
                if c["name"] == "SESSDATA":
                    sessdata = c["value"]
                    break

            if sessdata:
                break

            # Check if URL changed to home (login success indicator)
            if "passport" not in page.url and "login" not in page.url:
                # Might have redirected after login, re-check cookies
                cookies = context.cookies("https://www.bilibili.com")
                for c in cookies:
                    if c["name"] == "SESSDATA":
                        sessdata = c["value"]
                        break
                if sessdata:
                    break

            time.sleep(2)
            elapsed = int(time.time() - start)
            remaining = LOGIN_TIMEOUT_SEC - elapsed
            if remaining > 0 and elapsed % 10 == 0:
                print(f"[INFO] Waiting... ({remaining}s remaining)")

        if not sessdata:
            print("[ERROR] Login timed out. No SESSDATA cookie found.")
            print("[HINT] Make sure you scanned the QR code and confirmed login.")
            browser.close()
            return ""

        # Gather all bilibili cookies
        all_cookies = context.cookies("https://www.bilibili.com")
        
        # Build cookie string (key=value; key=value; ...)
        cookie_str = "; ".join(f"{c['name']}={c['value']}" for c in all_cookies)

        # Also save as JSON for future use
        cookie_json = json.dumps(all_cookies, ensure_ascii=False, indent=2)

        browser.close()

    # Save cookie string
    cookie_output.parent.mkdir(parents=True, exist_ok=True)
    with open(cookie_output, "w", encoding="utf-8") as f:
        f.write(cookie_str)

    # Also save JSON version
    json_path = cookie_output.with_suffix(".json")
    with open(json_path, "w", encoding="utf-8") as f:
        f.write(cookie_json)

    print()
    print("=" * 60)
    print("[SUCCESS] Login successful!")
    print(f"[INFO] SESSDATA: {sessdata[:20]}...{sessdata[-10:]}")
    print(f"[INFO] Cookie saved to: {cookie_output}")
    print(f"[INFO] Cookie JSON saved to: {json_path}")
    print("=" * 60)
    print()
    print("You can now use the cookie for subtitle extraction:")
    print(f'  python extract_subtitles.py <video_url> -o output.txt --cookie "$(cat {cookie_output})"')
    print()
    print("Or set as environment variable:")
    print(f'  $env:BILIBILI_COOKIE = Get-Content "{cookie_output}"')

    return cookie_str


# ==================== Main ====================

def main():
    parser = argparse.ArgumentParser(description="Get Bilibili cookie via QR code login")
    parser.add_argument(
        "--output", "-o",
        type=Path,
        default=DEFAULT_COOKIE_FILE,
        help=f"Cookie output file path (default: {DEFAULT_COOKIE_FILE})",
    )
    args = parser.parse_args()

    cookie = get_cookie_via_browser(args.output)
    if not cookie:
        sys.exit(1)


if __name__ == "__main__":
    main()
