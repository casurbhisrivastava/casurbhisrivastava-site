#!/usr/bin/env python3
"""
Scrapes GST's official "News and Updates" page (https://www.gst.gov.in/newsandupdates)
using a real headless browser, because the page is an AngularJS single-page app --
the news list does not exist in the raw HTML, only after client-side rendering.

CONFIRMED STRUCTURE (from a real debug run, 03 Aug 2026):
Each news item is a plain <li> inside <ul class="news-updts">, with the date in a
<p class="dt"> and the title + link in an <a> tag inside a second <p>:

    <ul class="news-updts">
      <li>
        <p class="dt">01/08/2026</p>
        <p><a href="//www.gst.gov.in/newsandupdates/read/669" title="...">Title text</a></p>
      </li>
      ...
    </ul>

Requires: playwright (see requirements.txt / the workflow's install step)
"""

import json
import re
from datetime import datetime

from playwright.sync_api import sync_playwright

URL = "https://www.gst.gov.in/newsandupdates"
SOURCE_NAME = "GST Portal (Official)"
CATEGORY = "gst"


def try_parse_date(text):
    text = text.strip()
    for fmt in ("%d/%m/%Y", "%d-%m-%Y", "%d/%m/%y", "%d-%m-%y"):
        try:
            return datetime.strptime(text, fmt).date().isoformat()
        except ValueError:
            continue
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
            # The AngularJS list populates a moment after networkidle; wait for at
            # least one real item before reading, rather than a blind sleep.
            page.wait_for_selector("ul.news-updts li", timeout=15000)

            # Save what actually rendered, for debugging if extraction below finds nothing.
            html = page.content()
            with open("gst_debug.html", "w", encoding="utf-8") as f:
                f.write(html)

            rows = page.locator("ul.news-updts li")
            count = rows.count()
            for i in range(count):
                row = rows.nth(i)
                try:
                    date_text = row.locator("p.dt").first.inner_text(timeout=2000).strip()
                except Exception:
                    date_text = ""
                try:
                    link_el = row.locator("a").first
                    title = link_el.inner_text(timeout=2000).strip()
                    href = link_el.get_attribute("href", timeout=1000)
                    if not href:
                        link = URL
                    elif href.startswith("http://") or href.startswith("https://"):
                        link = href
                    elif href.startswith("//"):
                        link = "https:" + href
                    elif href.startswith("/"):
                        link = "https://www.gst.gov.in" + href
                    else:
                        link = "https://www.gst.gov.in/" + href.lstrip("/")
                except Exception:
                    title, link = "", URL

                if not title or len(title) < 10:
                    continue

                items.append({
                    "title": title[:300],
                    "link": link,
                    "date": try_parse_date(date_text) or "",
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

