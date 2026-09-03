#!/usr/bin/env python3
"""
Scrapes the Income Tax Department's "News & e-Campaigns" page on
incometax.gov.in (NOT incometaxindia.gov.in -- that's a different domain/
server, and unlike incometaxindia.gov.in's RSS feeds, this page is NOT
IP-blocked from GitHub Actions as of 03 Aug 2026 testing).

CONFIRMED STRUCTURE: the page is plain server-rendered HTML (Drupal-based),
not a JavaScript single-page app -- no headless browser is required, a
simple HTTP GET works. Each entry looks like:

    27-Jul-2026

    The Central Board of Direct Taxes (CBDT), vide Notification No.
    97/2026 [F. No. 370142/11/2026-TPL], has notified the ... Click here

...where "Click here" links directly to the notification, often a PDF
hosted on the same domain (e.g. .../sites/default/files/2026-07/
Notification-97-2026.pdf) -- meaning this source can supply both the
update text AND its real PDF link in one step, unlike the other sources.

The page paginates (?page=1, ?page=2, ...) -- this script pulls the first
page or two, which is plenty for a daily-refresh feed.

Requires: only the standard library (urllib, re, html) -- no Playwright.
"""

import html
import json
import re
import urllib.request

BASE_URL = "https://www.incometax.gov.in/iec/foportal/latest-news"
SOURCE_NAME = "Income Tax Dept - News & e-Campaigns"
CATEGORY = "income-tax"
PAGES_TO_FETCH = 2  # ~10 items per page; 2 pages is enough for a daily refresh

DATE_PATTERN = re.compile(r"\b(\d{1,2}-[A-Za-z]{3}-\d{4})\b")
MONTHS = {
    "Jan": "01", "Feb": "02", "Mar": "03", "Apr": "04", "May": "05", "Jun": "06",
    "Jul": "07", "Aug": "08", "Sep": "09", "Oct": "10", "Nov": "11", "Dec": "12",
}


def date_to_iso(raw):
    m = re.match(r"(\d{1,2})-([A-Za-z]{3})-(\d{4})", raw)
    if not m:
        return raw
    day, mon, year = m.groups()
    mon_num = MONTHS.get(mon[:3].title())
    if not mon_num:
        return raw
    return f"{year}-{mon_num}-{int(day):02d}"


def fetch_page(url):
    req = urllib.request.Request(url, headers={
        "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"),
        "Accept": "text/html,application/xhtml+xml",
        "Accept-Language": "en-IN,en;q=0.9",
    })
    with urllib.request.urlopen(req, timeout=30) as resp:
        return resp.read().decode("utf-8", errors="replace")


def strip_tags(raw):
    text = re.sub(r"<[^>]+>", " ", raw or "")
    return re.sub(r"\s+", " ", html.unescape(text)).strip()


def scrape_incometax_news():
    items = []
    seen_titles = set()

    for page_num in range(PAGES_TO_FETCH):
        url = BASE_URL if page_num == 0 else f"{BASE_URL}?page=%2C{page_num}"
        try:
            raw_html = fetch_page(url)
        except Exception as e:
            print(f"ERR fetching page {page_num} -> {e}")
            continue

        # Save the first page for debugging if extraction below finds nothing.
        if page_num == 0:
            with open("incometax_debug.html", "w", encoding="utf-8") as f:
                f.write(raw_html)

        # Split the page on date markers -- each date starts a new news item.
        # We locate every date occurrence and take the HTML between it and
        # the next date as that item's block (title text + its link).
        date_matches = list(DATE_PATTERN.finditer(raw_html))
        for i, m in enumerate(date_matches):
            date_raw = m.group(1)
            block_start = m.end()
            block_end = date_matches[i + 1].start() if i + 1 < len(date_matches) else block_start + 3000
            block = raw_html[block_start:block_end]

            # The item's description text is the block with tags stripped,
            # up to (but not including) the "Click here" link text.
            text = strip_tags(block)
            text = re.sub(r"\s*Click here\s*$", "", text, flags=re.I).strip()
            if not text or len(text) < 15:
                continue
            if text in seen_titles:
                continue
            seen_titles.add(text)

            # Find the link (usually the href of the "Click here" anchor).
            link = None
            link_match = re.search(r'<a[^>]+href="([^"]+)"[^>]*>\s*Click here', block, flags=re.I)
            if link_match:
                href = link_match.group(1)
                if href.startswith("http://") or href.startswith("https://"):
                    link = href
                elif href.startswith("//"):
                    link = "https:" + href
                elif href.startswith("/"):
                    link = "https://www.incometax.gov.in" + href
                else:
                    link = "https://www.incometax.gov.in/" + href.lstrip("/")

            is_pdf = bool(link and link.lower().endswith(".pdf"))

            items.append({
                "title": text[:300],
                "link": link or BASE_URL,
                "pdf_link": link if is_pdf else None,
                "date": date_to_iso(date_raw),
                "source": SOURCE_NAME,
                "category": CATEGORY,
            })

    return items


if __name__ == "__main__":
    results = scrape_incometax_news()
    print(f"Extracted {len(results)} candidate item(s) from incometax.gov.in.")
    print(json.dumps(results[:5], indent=2, ensure_ascii=False))
    if not results:
        print("\nNo items extracted. Check incometax_debug.html (saved alongside "
              "this script) to see what actually came back, and share it so the "
              "parsing can be fixed.")
