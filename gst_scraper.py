#!/usr/bin/env python3
"""
Scrapes GST's official "News and Updates" page (https://www.gst.gov.in/newsandupdates)
using a real headless browser, because the page is a JavaScript single-page app --
the news list does not exist in the raw HTML, only after client-side rendering.

IMPORTANT — this was built without the ability to inspect the live rendered page
(the environment that built this script has no network access to gst.gov.in and
cannot execute JavaScript to see the final DOM). The extraction logic below is
deliberately generic (it doesn't guess specific CSS class names) to maximise the
chance it works, but it may need one round of adjustment based on real output.
If it returns zero items, check the debug artifact this script saves
(gst_debug.html) to see what the page actually rendered, and share that.

Requires: playwright (see requirements.txt / the workflow's install step)
"""

import json
import re
from datetime import datetime

from playwright.sync_api import sync_playwright

URL = "https://www.gst.gov.in/newsandupdates"
SOURCE_NAME = "GST Portal (Official)"
CATEGORY = "gst"

# Matches common Indian date formats appearing in news listings, e.g.
# "08-07-2026", "08/07/2026", "08 Jul 2026", "July 8, 2026"
DATE_PATTERNS = [
    re.compile(r"\b\d{1,2}[-/]\d{1,2}[-/]\d{2,4}\b"),
    re.compile(r"\b\d{1,2}\s+(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+\d{4}\b", re.I),
    re.compile(r"\b(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+\d{1,2},?\s+\d{4}\b", re.I),
]


def try_parse_date(text):
    for pat in DATE_PATTERNS:
        m = pat.search(text)
        if m:
            raw = m.group(0)
            for fmt in ("%d-%m-%Y", "%d/%m/%Y", "%d-%m-%y", "%d/%m/%y",
                        "%d %b %Y", "%d %B %Y", "%b %d, %Y", "%B %d, %Y", "%b %d %Y"):
                try:
                    return datetime.strptime(raw, fmt).date().isoformat()
                except ValueError:
                    continue
            return raw  # keep the raw matched text if we can't normalise it
    return None


def scrape_gst_news():
    items = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(user_agent=(
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
        ))
        try:
            page.goto(URL, wait_until="networkidle", timeout=45000)
            # Give the Angular/React app a little extra time to finish rendering
            page.wait_for_timeout(3000)

            # Save what actually rendered, for debugging if extraction below finds nothing.
            html = page.content()
            with open("gst_debug.html", "w", encoding="utf-8") as f:
                f.write(html)

            # Generic extraction strategy: look at every element that appears to be a
            # list item / row / card under the main content area, and treat non-trivial
            # text blocks as candidate news entries. This avoids hardcoding a specific
            # CSS class name we can't currently verify.
            candidates = page.locator(
                "main li, main tr, main .row, #main-content li, #main-content tr, "
                "[class*='news'] li, [class*='news'] tr, [class*='list'] li, "
                "table tr, ul li"
            )
            count = candidates.count()
            seen_texts = set()
            for i in range(count):
                try:
                    text = candidates.nth(i).inner_text(timeout=2000).strip()
                except Exception:
                    continue
                if not text or len(text) < 15 or len(text) > 400:
                    continue
                if text in seen_texts:
                    continue
                seen_texts.add(text)

                date_iso = try_parse_date(text)
                # Strip the matched date substring out of the title for readability
                title = text
                for pat in DATE_PATTERNS:
                    title = pat.sub("", title).strip(" -–—|,")
                title = re.sub(r"\s+", " ", title).strip()

                if not title or len(title) < 10:
                    continue

                # Try to find a link inside this same element
                link = None
                try:
                    link_el = candidates.nth(i).locator("a").first
                    href = link_el.get_attribute("href", timeout=1000)
                    if href:
                        link = href if href.startswith("http") else ("https://www.gst.gov.in" + href)
                except Exception:
                    pass

                items.append({
                    "title": title[:300],
                    "link": link or URL,
                    "date": date_iso or "",
                    "source": SOURCE_NAME,
                    "category": CATEGORY,
                })
        finally:
            browser.close()

    return items


if __name__ == "__main__":
    results = scrape_gst_news()
    print(f"Extracted {len(results)} candidate item(s) from GST portal.")
    print(json.dumps(results[:5], indent=2, ensure_ascii=False))
    if not results:
        print("\nNo items extracted. Check gst_debug.html (saved alongside this script) "
              "to see what actually rendered, and share it so the selectors can be fixed.")
