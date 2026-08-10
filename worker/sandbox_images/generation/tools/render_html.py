"""
Renders an HTML file to a PNG at an exact pixel size using headless Chromium.

This is the "overlay" half of plate-first rendering (SKILL.md): the plate
already carries the full visual treatment; this step composites the live
HTML text/logo overlay on top of it and produces the single PNG a customer
would actually see. Nothing about brand or copy lives in this script -
it just screenshots whatever HTML it's given, at whatever size it's told.

Usage:
    python render_html.py --html overlay.html --width 1080 --height 1080 --out final.png
"""
import argparse
import os

from playwright.sync_api import sync_playwright


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--html", required=True)
    parser.add_argument("--width", type=int, required=True)
    parser.add_argument("--height", type=int, required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    html_path = os.path.abspath(args.html)
    os.makedirs(os.path.dirname(os.path.abspath(args.out)) or ".", exist_ok=True)

    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": args.width, "height": args.height})
        page.goto(f"file:///{html_path}")
        page.screenshot(path=args.out)
        browser.close()

    print(f"Saved {args.out} ({args.width}x{args.height})")


if __name__ == "__main__":
    main()
