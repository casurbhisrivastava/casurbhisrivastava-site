#!/usr/bin/env python3
"""
Fetches official Indian financial-regulator RSS feeds (RBI, PIB, Income Tax
Dept) plus the GST headless-browser scraper, and writes a filtered,
structured JSON file (updates-feed.json) for the website's Live Feed section
to consume.

This script is meant to run server-side (e.g. via the included GitHub Actions
workflow) on a schedule -- NOT in the browser -- because browsers block
cross-origin requests to .gov.in domains that don't send CORS headers.

Categories map onto the site's category dropdown (see index.html):
  income-tax, gst, banking, mca, goi, misc
  (icai, audit, ibc currently have no reliable automated source -- see
  README.md "Categories without an automated source yet" for why, and what
  it would take to add one.)

Each item also carries a best-effort "pdf_link" field: if the RSS entry's own
link is already a PDF, that's used directly; otherwise the script does one
lightweight fetch of the linked page and looks for the first link on it that
points to a .pdf file (common on RBI/Income Tax Dept pages, which usually
link out to the actual notification PDF). If nothing is found, pdf_link is
null and the site shows only the "Read source" link for that item, no PDF
button.

Sources used (all official, all public):
  - RBI Press Releases RSS : https://www.rbi.org.in/pressreleases_rss.xml
  - RBI Notifications RSS  : https://www.rbi.org.in/notifications_rss.xml
  - PIB (all ministries)   : https://www.pib.gov.in/ViewRss.aspx?reg=3&lang=1
  - Income Tax Dept RSS feeds (press release / circular / notification)
  - Economic Times topic feeds (GST, Income Tax, Personal Finance, Banking)
  - GST portal (via gst_scraper.py -- headless browser, no RSS available)
  - MCA notices & circulars (via mca_scraper.py -- headless browser, site
    blocks plain requests and its listing renders client-side)
"""

import json
import re
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from html import unescape

FEEDS = [
    {"url": "https://www.rbi.org.in/pressreleases_rss.xml", "source": "RBI Press Release", "category": "banking", "always_include": False},
    {"url": "https://www.rbi.org.in/notifications_rss.xml", "source": "RBI Notification", "category": "banking", "always_include": False},
    {"url": "https://www.pib.gov.in/ViewRss.aspx?reg=3&lang=1", "source": "PIB (Ministry of Finance)", "category": "goi", "always_include": True},
    # NOTE: the old incometaxindia.gov.in RSS feeds (Press Release / Circular /
    # Notification) are IP-blocked from GitHub Actions runners (confirmed
    # 03 Aug 2026 -- 403 Forbidden even with a real browser User-Agent, while
    # the exact same feed loads fine from a normal residential connection).
    # Replaced below by incometax_scraper.py, which pulls the same kind of
    # content from a *different* domain (incometax.gov.in, not
    # incometaxindia.gov.in) that isn't blocked, and additionally supplies
    # direct PDF links where available -- see the "Income Tax Dept" merge
    # step further down in this file.
    # Economic Times — these are already topic-dedicated feeds (editorially curated by ET
    # for that specific subject), so we trust them and skip keyword filtering entirely.
    {"url": "https://economictimes.indiatimes.com/small-biz/gst/rssfeeds/58475404.cms", "source": "Economic Times - GST", "category": "gst", "always_include": True},
    {"url": "https://economictimes.indiatimes.com/wealth/tax/rssfeeds/47119912.cms", "source": "Economic Times - Income Tax", "category": "income-tax", "always_include": True},
    {"url": "https://economictimes.indiatimes.com/wealth/personal-finance-news/rssfeeds/49674901.cms", "source": "Economic Times - Personal Finance", "category": "misc", "always_include": True},
    # Banking/Finance Industry is broader (covers company results, strategy etc. too),
    # so it still goes through the keyword filter below.
    {"url": "https://economictimes.indiatimes.com/rssfeeds/13358259.cms", "source": "Economic Times - Banking/Finance", "category": "banking", "always_include": False},
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

MAX_ITEMS = 30
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


def parse_rss(xml_bytes, source, category, always_include=False):
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
        if not always_include and not is_relevant(title):
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
    req = urllib.request.Request(url, headers={
        "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"),
        "Accept": "application/rss+xml, application/xml, text/xml, */*",
        "Accept-Language": "en-IN,en;q=0.9",
    })
    with urllib.request.urlopen(req, timeout=30) as resp:
        return resp.read()


def find_pdf_link(page_url):
    """Best-effort: if the item's own link is already a PDF, use it. Otherwise
    do one lightweight fetch of the linked page and return the first href
    that points to a .pdf file (resolved to an absolute URL). Returns None on
    any failure -- this must never break the main run."""
    if page_url.lower().split("?")[0].endswith(".pdf"):
        return page_url
    try:
        raw = fetch(page_url)
        html = raw.decode("utf-8", errors="ignore")
        # crude but dependency-free: find href="....pdf" (optionally with a querystring)
        match = re.search(r'href=["\']([^"\']+\.pdf(?:\?[^"\']*)?)["\']', html, re.IGNORECASE)
        if not match:
            return None
        pdf_url = match.group(1)
        if pdf_url.startswith("//"):
            pdf_url = "https:" + pdf_url
        elif pdf_url.startswith("/"):
            from urllib.parse import urlparse
            parsed = urlparse(page_url)
            pdf_url = f"{parsed.scheme}://{parsed.netloc}{pdf_url}"
        elif not pdf_url.startswith("http"):
            return None  # relative path without leading slash -- skip, too ambiguous to resolve safely
        return pdf_url
    except Exception:
        return None


def main():
    all_items = []
    errors = []
    for feed in FEEDS:
        try:
            raw = fetch(feed["url"])
            items = parse_rss(raw, feed["source"], feed["category"], feed.get("always_include", False))
            all_items.extend(items)
            print(f"OK  {feed['url']} -> {len(items)} relevant item(s)")
        except Exception as e:
            errors.append(f"{feed['url']}: {e}")
            print(f"ERR {feed['url']} -> {e}")

    # GST portal has no RSS/API -- it's a JS-rendered page, so it needs a headless
    # browser instead of a simple HTTP request. Wrapped defensively so that if
    # Playwright isn't installed, or GST's page changes and breaks extraction,
    # every other source above still succeeds and gets written out normally.
    try:
        from gst_scraper import scrape_gst_news
        gst_items = scrape_gst_news()
        all_items.extend(gst_items)
        print(f"OK  gst.gov.in (headless browser) -> {len(gst_items)} item(s)")
        if not gst_items:
            errors.append("gst.gov.in: scraper ran but found 0 items -- see gst_debug.html artifact")
    except Exception as e:
        errors.append(f"gst.gov.in (headless browser): {e}")
        print(f"ERR gst.gov.in (headless browser) -> {e}")

    # MCA blocks plain HTTP requests and its notices listing renders client-side,
    # so it needs the same headless-browser approach as GST. Same defensive wrapping:
    # if Playwright isn't installed, or MCA's page changes and breaks extraction,
    # every other source above still succeeds and gets written out normally.
    try:
        from mca_scraper import scrape_mca_notices
        mca_items = scrape_mca_notices()
        all_items.extend(mca_items)
        print(f"OK  mca.gov.in (headless browser) -> {len(mca_items)} item(s)")
        if not mca_items:
            errors.append("mca.gov.in: scraper ran but found 0 items -- see mca_debug.html artifact")
    except Exception as e:
        errors.append(f"mca.gov.in (headless browser): {e}")
        print(f"ERR mca.gov.in (headless browser) -> {e}")

    # Income Tax Dept news, from incometax.gov.in (NOT incometaxindia.gov.in --
    # that domain's RSS feeds are IP-blocked from GitHub Actions, see the note
    # in FEEDS above). This is plain server-rendered HTML, no headless browser
    # needed. It also frequently supplies a direct PDF link per item, which is
    # kept as-is below rather than re-detected.
    try:
        from incometax_scraper import scrape_incometax_news
        incometax_items = scrape_incometax_news()
        all_items.extend(incometax_items)
        print(f"OK  incometax.gov.in (news page) -> {len(incometax_items)} item(s)")
        if not incometax_items:
            errors.append("incometax.gov.in: scraper ran but found 0 items -- see incometax_debug.html artifact")
    except Exception as e:
        errors.append(f"incometax.gov.in (news page): {e}")
        print(f"ERR incometax.gov.in (news page) -> {e}")

    # De-duplicate by link, sort newest first, cap the list
    seen = set()
    deduped = []
    for it in sorted(all_items, key=lambda x: x["date"], reverse=True):
        if it["link"] in seen:
            continue
        seen.add(it["link"])
        deduped.append(it)
    deduped = deduped[:MAX_ITEMS]

    # Best-effort PDF detection -- only for the final, capped list, to avoid
    # wasting requests on items that got filtered out or deduplicated away.
    # Skip items that already came with a known direct PDF link (currently
    # only incometax_scraper.py supplies these) so we don't overwrite a
    # confirmed link with a re-guessed one.
    pdf_found = 0
    for it in deduped:
        if not it.get("pdf_link"):
            it["pdf_link"] = find_pdf_link(it["link"])
        if it["pdf_link"]:
            pdf_found += 1
    print(f"PDF links found for {pdf_found} of {len(deduped)} items")

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
