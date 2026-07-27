# Live Regulatory Feed — Setup Guide

This folder makes the "Live Regulatory Feed" section on your website genuinely
auto-update every day, straight from RBI and Government of India (PIB) RSS
feeds — no manual editing required once it's set up.

## Why this needs a separate setup step

Browsers block a webpage from silently pulling data from another domain
(a security feature called CORS), and government sites don't grant an
exception for arbitrary websites. So the fetching has to happen **outside**
the browser, on a schedule, and the results saved as a plain file that your
site can read from itself. That's what `fetch_updates.py` +
`.github/workflows/update-feed.yml` do together.

## What's in this folder

```
automation/
├── fetch_updates.py                     ← the script that checks official sources
└── .github/workflows/update-feed.yml    ← tells GitHub to run it daily, automatically
```

## One-time setup (about 10 minutes, free)

1. **Create a GitHub account** if you don't have one: https://github.com/join

2. **Create a new repository** (e.g. `casurbhisrivastava-site`) — make it Public.

3. **Upload these files to the repository root**, keeping the folder structure:
   - `index.html` (your website)
   - `fetch_updates.py` (from this `automation/` folder — move it to the repo root, not inside a subfolder)
   - `.github/workflows/update-feed.yml` (from this folder — keep the `.github/workflows/` path exactly as-is)

   Easiest way: on GitHub, use "Add file → Upload files" and drag everything in,
   or use GitHub Desktop / `git push` if you're comfortable with that.

4. **Enable GitHub Pages**: in the repo, go to *Settings → Pages*, set
   "Source" to your main branch, and save. GitHub will give you a live URL
   like `https://yourusername.github.io/casurbhisrivastava-site/`.

5. **Run the automation once manually** to generate the first `updates-feed.json`:
   go to the *Actions* tab → "Refresh statutory updates feed" → *Run workflow*.
   After ~30 seconds, refresh your repo and you should see a new file
   `updates-feed.json` at the root.

6. **Done.** From now on, GitHub will automatically re-run this every day at
   06:00 UTC (11:30 AM IST) and commit the refreshed file — you never have to
   touch it again. Your site's "Live Regulatory Feed" section will pick up the
   new file automatically on each page load.

## Customizing what gets included

Open `fetch_updates.py` and edit the `INCLUDE_KEYWORDS` list to add or remove
topics (e.g. add `"repo rate"` or `"digital lending"`), and `EXCLUDE_PATTERNS`
to filter out noise you don't want (e.g. routine bond-auction results).
Commit the change — the next scheduled run will use your new filters.

## Adding more sources later

The script currently reads:
- RBI Press Releases (`https://www.rbi.org.in/pressreleases_rss.xml`)
- RBI Notifications (`https://www.rbi.org.in/notifications_rss.xml`)
- PIB, all ministries (`https://www.pib.gov.in/ViewRss.aspx?reg=3&lang=1`)

Income Tax Dept has official RSS feeds (already included above). GST has no
RSS/API, so `gst_scraper.py` uses a headless browser instead. MCA and ICAI
don't currently have a usable public feed — MCA's site actively blocks
automated requests (same reason GST needed a headless-browser workaround
instead of simple RSS parsing), and no reliable public ICAI feed could be
found. If you want these added, the same headless-browser approach used for
GST could likely be adapted for MCA; that's a follow-up task, not something
this script currently does.

## Categories and the category dropdown

Every item gets a `category` matching the site's dropdown/filter options:
`income-tax`, `gst`, `banking`, `mca`, `goi`, `misc`. The `icai`, `audit` and
`ibc` dropdown options currently have no automated source feeding them (see
above) — they'll show the site's "No updates posted in this category yet"
message until either a source is added here, or items are added to them
manually in the Statutory Bulletin section of `index.html`.

## PDF attachment detection

Each item also gets a best-effort `pdf_link` field. If the RSS entry's own
link already points to a `.pdf` file, that's used directly. Otherwise the
script does one extra fetch of the linked page and looks for the first link
on it pointing to a `.pdf` — this catches the common pattern on RBI and
Income Tax Dept pages where the news/press-release page links out to the
actual notification PDF. If nothing is found, `pdf_link` is left empty and
the site just shows the normal "Read source" link for that item, no PDF
button. This is inherently imperfect — some official pages structure their
PDF links in ways the simple pattern-match won't catch — so don't expect
100% coverage, but it should catch a meaningful share of items automatically
with zero manual work.

## Important limits (please read)

- This is a **headline + link (+ PDF where found)** feed only. It cannot generate the detailed
  What/When/Why/Whom/Whose/Background breakdown the manually curated bulletin
  above it has — that level of analysis requires a person to read and
  interpret each notification, which is exactly what the manual section is
  for. Think of the two sections as complementary: manual = deep, curated,
  explained; live feed = fast, comprehensive, headline-only.
- RSS feed structure can change without notice on the source's end, which
  could break parsing. If the feed ever stops updating, check the Actions
  tab for a failed run and let me know — the fix is usually small.
- This only works once the site is actually hosted online. Opening
  `index.html` directly from your computer (double-clicking the file) will
  never show live feed results, by design — that's a browser security rule,
  not a bug.
