# Condo price monitor

Tracks the **asking prices of condo projects, split by room type and size,** across Thai
listing sites, keeps a daily price history in the repo, alerts on new listings and
price drops, and publishes a dashboard to GitHub Pages.

It answers questions like *"what is a 1-bedroom at Ideo Mobi Sukhumvit Eastgate
actually being asked for this month, and has anything been cut?"*

---

## What it does

1. **Scrapes** each configured source for the project you are watching.
2. **Filters** to the project with one shared name-matching rule set, so every
   source is measured the same way, and buckets each unit by bedroom count.
3. **Diffs** against the previous run to find new listings and price drops.
4. **Writes** a snapshot, a daily history point, and an alert log into `data/`.
5. **Notifies** by opening a GitHub issue (and optionally a Slack/Discord webhook).
6. **Publishes** `index.html`, a dependency-free dashboard reading those JSON files.

Everything is committed to the repo, so the price history is a plain, diffable,
permanent record — no database, no hosting bill.

---

## Sources

| Source | Status | How it is read |
|---|---|---|
| **DDproperty** | working | Search pages embed the full result set as JSON in Next.js `__NEXT_DATA__`, so listings are read as structured objects rather than scraped from markup. Robust and cheap: one request per 20 listings. |
| **Livinginsider** | working | Search results are client-rendered and `/api/` is disallowed by their robots.txt, so neither is used. Project pages *are* server-rendered and list every unit; each detail page carries a plain-text spec block that is parsed. Costs one request per listing, hence `max_listings`. |
| **Hipflat** | **blocked, disabled** | Hipflat answers every non-browser request with `401 Access Denied` (Cloudflare), including `robots.txt`. The only user agent it serves is Googlebot. This project does not impersonate a search crawler to get around a block, so the adapter ships switched off and the dashboard states the reason instead of silently omitting the source. If the site ever serves ordinary clients, set `enabled: true` and it starts contributing with no code change. |

Source health — including the disabled one and why — is shown on the dashboard
and stored in each snapshot.

---

## Quick start

```bash
pip install -r requirements.txt
python -m scraper.main --config config/watchlist.yml --data data
```

Then serve the dashboard (it reads `data/` over HTTP, so open it through a server,
not `file://`):

```bash
python -m http.server 8000
# http://127.0.0.1:8000/index.html
```

Useful flags:

```bash
python -m scraper.main --watch ideo-mobi-sukhumvit-eastgate       # one watch only
python -m scraper.main --dry-run                                  # fetch, write nothing
python -m scraper.main -v                                         # debug logging
```

---

## Configuring a watch

Everything lives in `config/watchlist.yml`. **One entry per project.** Every unit
in the project is collected; the dashboard then lets you pick the room type
(studio / 1 / 2 / 3+ bedrooms) and a size range separately, and the history is
stored per bedroom bucket so each room type gets its own trend line.

```yaml
watches:
  - id: ideo-mobi-sukhumvit-eastgate         # also the data filename
    project: Ideo Mobi Sukhumvit Eastgate
    deal: sale                               # sale | rent

    match:                                   # title must contain one of these
      - Ideo Mobi Sukhumvit Eastgate
    exclude:                                 # ...and none of these
      - Eastgate Phase 2

    alerts:
      room_type:                             # alert only on this unit shape;
        bedrooms: 1                          # delete the block to alert on all
        min_sqm: 20                          # (0 bedrooms means studio)
        max_sqm: 40

    sources:
      ddproperty:
        url: https://www.ddproperty.com/en/property-for-sale?freetext=Ideo+Mobi+Sukhumvit+Eastgate
        max_pages: 5
      livinginsider:
        url: https://www.livinginsider.com/en/project/condo-ideo-mobi-sukhumvit-eastgate-condo-buysell
        max_listings: 60
```

A top-level `room_type:` (same fields) is still accepted and drops non-matching
units before they are stored — use it only if you never want to see other units.

To add a project, copy the entry, change `id`, `project`, `match` and the two
source URLs. It appears in the dashboard's project picker after the next run.

**Finding the URLs.** Each `url` is a page you can open yourself — copy it from the
site with whatever filters you want:

- *DDproperty*: search the project name and copy the address bar. Use the
  `freetext=` form; do **not** add `region_code`, which overrides the text search
  and silently returns the whole region. The scraper rejects a search URL that
  reports more than 200 pages for exactly this reason.
- *Livinginsider*: project pages are listed in
  `https://www.livinginsider.com/sitemap-project-0.xml` (there are ten shards).
  Search that file for your project slug.

**Matching is deliberately explicit.** Titles are compared with case, spacing and
punctuation ignored, but the two sites name sibling towers differently — DDproperty
has *Eastpoint* where Livinginsider has *Eastgate*. Pin the building with `match`
plus `exclude`, then check the first run's listing table before trusting the medians.

---

## Alerts

Two kinds, both switchable per watch:

- **New listing** — a unit that was not in the previous snapshot.
- **Price drop** — an existing unit whose asking price fell by **both** at least
  `min_drop_pct` and at least `min_drop_thb`. Requiring both keeps rounding noise
  on cheap units and trivial cuts on expensive ones out of your inbox.

```yaml
defaults:
  alerts:
    min_drop_pct: 1.0
    min_drop_thb: 20000
    alert_new: true
    alert_price_drop: true
```

A watch's **first ever run emits no "new listing" alerts** — otherwise day one would
fire one alert per unit on the market. Alerts begin from the second run.

Delivery:

- A **GitHub issue** per run that has alerts, labelled `price-alert`. As repo owner
  you get the usual email for it — no extra setup.
- Optionally a **Slack or Discord webhook**: add the URL as a repository secret
  named `ALERT_WEBHOOK_URL`. The payload shape is picked from the hostname.

---

## Deploying

1. Push the repo to GitHub.
2. **Settings → Pages → Source: Deploy from a branch**, branch `master`, folder `/`
   (root). The dashboard is plain static files, so a committed data update *is* a
   site update.
3. **Settings → Actions → General → Workflow permissions: Read and write**, so the
   scheduled run can commit `data/` back.
4. (Optional) add the `ALERT_WEBHOOK_URL` secret.

`.github/workflows/monitor.yml` runs daily at 01:00 UTC (08:00 Bangkok) and can be
triggered by hand from the Actions tab, optionally for a single watch.

---

## Data layout

```
data/
├── watches.json                  index the dashboard loads first
├── alerts.json                   rolling alert log, newest first (max 500)
├── latest_alerts.md              this run's alerts, used as the issue body
├── snapshots/<watch-id>.json     current listings + per-source health
└── history/<watch-id>.json       one point per day, overall + per bedroom bucket (max ~2 years)
```

Each snapshot row keeps `first_seen`, `first_price`, `previous_price` and a
`price_changes` log, so a unit's whole asking-price path survives even though only
one row per unit is stored.

**If a source fails**, its listings from the previous run are carried over rather
than being treated as delisted — an outage should not look like the whole building
selling overnight. The carry-over is recorded in the snapshot.

---

## Reliability notes

Scrapers break when sites change. This one is built to fail loudly and partially:

- A broken adapter, a blocked source, or a bad URL is recorded as a per-source
  status and never sinks the rest of the run.
- Prices and sizes are sanity-checked before they reach the medians. A mis-parsed
  number is worse than a missing one, so implausible values are dropped and logged.
  (This is not hypothetical: Livinginsider's pages carry a site-wide "For sale :
  64,498" counter that a naive regex reads as the asking price. There is a
  regression test for it.)
- `data/` is append-mostly, so a bad run degrades one day's point rather than
  destroying the history.

---

## Caveats worth knowing

- These are **asking prices, not transaction prices.** Thai condo listings often sit
  above the price things actually close at, and the same unit can be listed by
  several agents at different prices.
- **Duplicates across sites are not merged.** The same unit appearing on both sites
  counts twice in the overall median. Per-source medians on the chart are the
  honest comparison; where the two lines agree, the picture is trustworthy.
- A listing vanishing means *delisted*, which usually but not always means sold.
- Scraping is rate-limited and polite (one request at a time, ~1s apart). Keep
  `max_listings` modest; this is a personal tracker, not a crawler.

---

## Tests

```bash
pip install -r requirements-dev.txt
python -m pytest tests -q
```

The adapter tests run against saved HTML fixtures, so they need no network and
they pin the exact parsing failures that have been hit in practice.
