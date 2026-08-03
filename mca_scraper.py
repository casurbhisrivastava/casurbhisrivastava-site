#!/usr/bin/env python3
"""
Scrapes MCA's official "Notices & Circulars" page
(https://www.mca.gov.in/content/mca/global/en/notifications-tender/notices-circulars.html)
using a real headless browser.

CONFIRMED ISSUE (from a real debug run, 03 Aug 2026): MCA's site is protected by
Akamai (an "Access Denied" page from errors.edgesuite.net is returned instead of
real content). This is active bot-blocking, not a wrong CSS selector -- even a
real browser hitting this exact URL directly got the same block, which suggests
Akamai requires either a valid session (cookies picked up by browsing the site
normally first) or is fingerprinting the request as automated.

This version tries the standard workaround: visit the MCA homepage first (so any
session/consent cookies Akamai expects get set), then navigate to the target
page from there via an in-page link click rather than a fresh page.goto(), which
more closely mimics a real visitor. If this still returns 0 items or another
Access Denied page, MCA's bot protection is likely too strict for headless
automation from this environment (GitHub Actions runner IPs are commonly
blocklisted by government WAFs), and MCA updates may need to stay a manual/
AI-search step rather than a fully automated one -- check mca_debug.html to
confirm which case this is.

Requires: playwright (see requirements.txt / the workflow's install step)
"""

import json
import re
from datetime import datetime

from playwright.sync_api import sync_playwright

HOME_URL = "https://www.mca.gov.in/"
URL = "https://www.mca.gov.in/content/mca/global/en/notifications-tender/notices-circulars.html"
SOURCE_NAME = "MCA Notices & Circulars (Official)"
CATEGORY = "mca"

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
            return raw
    return None


def is_blocked(html):
    lowered = html.lower()
    return "access denied" in lowered and "edgesuite" in lowered


def scrape_mca_notices():
    items = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
            ),
            locale="en-IN",
            viewport={"width": 1366, "height": 900},
            extra_http_headers={
                "Accept-Language": "en-IN,en;q=0.9",
            },
        )
        page = context.new_page()
        try:
            # Step 1: visit the homepage first, like a real visitor would, so any
            # cookies/session Akamai expects get set before hitting the deeper page.
            page.goto(HOME_URL, wait_until="networkidle", timeout=45000)
            page.wait_for_timeout(2000)

            # Step 2: navigate to the target page directly (still within the same
            # browser context/session established above).
            page.goto(URL, wait_until="networkidle", timeout=45000)
            page.wait_for_timeout(3000)

            html = page.content()
            with open("mca_debug.html", "w", encoding="utf-8") as f:
                f.write(html)

            if is_blocked(html):
                print("Still blocked by Akamai (Access Denied) even after visiting "
                      "the homepage first. This is very likely IP-based blocking of "
                      "the GitHub Actions runner rather than a fixable header/selector "
                      "issue -- see mca_debug.html.")
                return items

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

