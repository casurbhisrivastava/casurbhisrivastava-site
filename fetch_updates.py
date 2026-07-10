#!/usr/bin/env python3
"""
Fetches official Indian financial-regulator RSS feeds (RBI, PIB) and writes a
filtered, structured JSON file (updates-feed.json) for the website's Live Feed
section to consume.

This script is meant to run server-side (e.g. via the included GitHub Actions
workflow) on a schedule -- NOT in the browser -- because browsers block
cross-origin requests to .gov.in domains that don't send CORS headers.

Sources used (all official, all public):
  - RBI Press Releases RSS : https://www.rbi.org.in/pressreleases_rss.xml
  - RBI Notifications RSS  : https://www.rbi.org.in/notifications_rss.xml
  - PIB (all ministries)   : https://www.pib.gov.in/ViewRss.aspx?reg=3&lang=1
"""

import json
import re
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from html import unescape

FEEDS = [
    {"url": "https://www.rbi.org.in/pressreleases_rss.xml", "source": "RBI Press Release", "category": "banking"},
    {"url": "https://www.rbi.org.in/notifications_rss.xml", "source": "RBI Notification", "category": "banking"},
    {"url": "https://www.pib.gov.in/ViewRss.aspx?reg=3&lang=1", "source": "PIB (Govt. of India)", "category": "general"},
]

# Keep items whose title matches at least one of these (case-insensitive)
INCLUDE_KEYWORDS = [
    "kyc", "loan", "deposit", "bank", "nbfc", "digital payment", "fraud",
    "customer", "interest rate", "repo rate", "credit card", "debit card",
    "upi", "gst", "income tax", "tds", "tcs", "company law", "mca", "roc",
    "compliance", "penalty", "master direction", "due date", "deadline",
    "cbdt", "cbic", "itr", "return filing", "circular", "notification",
    "consumer protection", "ombudsman"
]

# Drop items that match these even if they matched an include keyword above
# (routine market-operations noise that isn't relevant to the site's audience)
EXCLUDE_PATTERNS = [
    "money market operations", "auction of government", "state government securities",
    "variable rate repo", "result of the overnight", "t-bill", "treasury bill",
    "sectoral deployment", "outlook survey", "consumer confidence survey",
    "forward premia", "reference rate for us", "developmental and regulatory policies",
]

MAX_ITEMS = 20
OUTPUT_PATH = "updates-feed.json"


def strip_html(raw_html):
    text = re.sub(r"<[^>]+>", " ", raw_html or "")
    text = unescape(text)
    return re.sub(r"\s+", " ", text).strip()


def is_relevant(title):
    t = title.lower()
    if any(bad in t for bad in EXCLUDE_PATTERNS):
        return False
    return any(kw in t for kw in INCLUDE_KEYWORDS)


def parse_rss(xml_bytes, source, category):
    items = []
    try:
        root = ET.fromstring(xml_bytes)
    except ET.ParseError:
        return items
    for item in root.findall(".//item"):
        title_el = item.find("title")
        link_el = item.find("link")
        date_el = item.find("pubDate")
        if title_el is None or link_el is None:
            continue
        title = strip_html(title_el.text or "")
        link = (link_el.text or "").strip()
        pub_date_raw = (date_el.text or "").strip() if date_el is not None else ""
        pub_date_iso = None
        for fmt in ("%a, %d %b %Y %H:%M:%S", "%a, %d %b %Y %H:%M:%S %Z", "%a, %d %b %Y %H:%M:%S %z"):
            try:
                pub_date_iso = datetime.strptime(pub_date_raw, fmt).date().isoformat()
                break
            except ValueError:
                continue
        if not title or not link:
            continue
        if not is_relevant(title):
            continue
        items.append({
            "title": title,
            "link": link,
            "date": pub_date_iso or pub_date_raw,
            "source": source,
            "category": category,
        })
    return items


def fetch(url):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (compatible; StatutoryUpdateBot/1.0)"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return resp.read()


def main():
    all_items = []
    errors = []
    for feed in FEEDS:
        try:
            raw = fetch(feed["url"])
            items = parse_rss(raw, feed["source"], feed["category"])
            all_items.extend(items)
            print(f"OK  {feed['url']} -> {len(items)} relevant item(s)")
        except Exception as e:
            errors.append(f"{feed['url']}: {e}")
            print(f"ERR {feed['url']} -> {e}")

    # De-duplicate by link, sort newest first, cap the list
    seen = set()
    deduped = []
    for it in sorted(all_items, key=lambda x: x["date"], reverse=True):
        if it["link"] in seen:
            continue
        seen.add(it["link"])
        deduped.append(it)
    deduped = deduped[:MAX_ITEMS]

    output = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "sources": [f["url"] for f in FEEDS],
        "errors": errors,
        "items": deduped,
    }

    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print(f"\nWrote {len(deduped)} items to {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
