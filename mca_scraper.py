#!/usr/bin/env python3
"""
Scrapes MCA's official "Notices & Circulars" page
(https://www.mca.gov.in/content/mca/global/en/notifications-tender/notices-circulars.html)
using a real headless browser.

MCA's site actively blocks plain automated HTTP requests (a direct fetch
returns a bot-detection block, not the page content), and the listing itself
appears to be loaded/filtered client-side rather than present in the raw
HTML. A real browser sidesteps both problems the same way gst_scraper.py
does for the GST portal.

IMPORTANT — same caveat as gst_scraper.py: this was built without the
ability to load the live rendered page (no network access to mca.gov.in from
the environment that built this script, and mca.gov.in blocks the fetch tool
directly). The extraction logic below is deliberately generic (it doesn't
guess specific CSS class names) to maximise the chance it works, but it will
likely need one round of adjustment based on real output. If it returns zero
items, check the debug artifact this script saves (mca_debug.html) to see
what the page actually rendered, and share that.

Requires: playwright (see requirements.txt / the workflow's install step)
"""

import json
import re
from datetime import datetime

from playwright.sync_api import sync_playwright

URL = "https://www.mca.gov.in/content/mca/global/en/notifications-tender/notices-circulars.html"
SOURCE_NAME = "MCA Notices & Circulars (Official)"
CATEGORY = "mca"

# Matches common Indian date formats appearing in notice listings, e.g.
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


def scrape_mca_notices():
    items = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(user_agent=(
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
        ))
        try:
            page.goto(URL, wait_until="networkidle", timeout=45000)
            # Give any client-side listing/filter script a little extra time to render
            page.wait_for_timeout(3000)

            # Save what actually rendered, for debugging if extraction below finds nothing.
            html = page.content()
            with open("mca_debug.html", "w", encoding="utf-8") as f:
                f.write(html)

            # Generic extraction strategy, same reasoning as gst_scraper.py: look at
            # every element that appears to be a list item / row / card under the main
            # content area, and treat non-trivial text blocks as candidate notices.
            # Avoids hardcoding a specific CSS class name we can't currently verify.
            candidates = page.locator(
                "main li, main tr, main .row, #main-content li, #main-content tr, "
                "[class*='notice'] li, [class*='notice'] tr, [class*='circular'] li, "
                "[class*='circular'] tr, [class*='result'] li, [class*='result'] tr, "
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

                # Skip obvious navigation/chrome text that isn't an actual notice
                if text.lower() in ("circulars", "what's new", "latest news", "important updates",
                                    "press release", "rss feeds", "archive", "notices & circulars"):
                    continue

                date_iso = try_parse_date(text)
                title = text
                for pat in DATE_PATTERNS:
                    title = pat.sub("", title).strip(" -–—|,")
                title = re.sub(r"\s+", " ", title).strip()

                if not title or len(title) < 10:
                    continue

                # Try to find a link (often the notice PDF itself) inside this same element
                link = None
                try:
                    link_el = candidates.nth(i).locator("a").first
                    href = link_el.get_attribute("href", timeout=1000)
                    if href:
                        link = href if href.startswith("http") else ("https://www.mca.gov.in" + href)
                except Exception:
                    pass

                items.append({
                    "title": title[:300],
                    "link": link or URL,
                    "date": date_iso or "",
                    "source": SOURCE_NAME,
                    "category": CATEGORY,
                    # MCA notices are very often themselves direct PDF links -- if so,
                    # fetch_updates.py's find_pdf_link() step will confirm/use it directly.
                })
        finally:
            browser.close()

    return items


if __name__ == "__main__":
    results = scrape_mca_notices()
    print(f"Extracted {len(results)} candidate item(s) from MCA.")
    print(json.dumps(results[:5], indent=2, ensure_ascii=False))
    if not results:
        print("\nNo items extracted. Check mca_debug.html (saved alongside this script) "
              "to see what actually rendered, and share it so the selectors can be fixed.")
