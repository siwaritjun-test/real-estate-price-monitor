"""Crawl every condo-for-sale listing in a region on DDproperty, grouped by project.

This is the market-wide "universe", refreshed daily. It is deliberately
DDproperty-only: one search page returns 20 listings with their project id, so
all of Bangkok (~50,000 listings) costs ~2,500 requests. Livinginsider costs one
request per listing and stays limited to the pinned watches in watchlist.yml.

Each project is written in the same snapshot/history format as a pinned watch,
under ``data/universe/``, so the dashboard reads both the same way.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import statistics
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .config import load_watchlist
from .http import Fetcher, FetchError
from .models import ROOM_BUCKETS, Listing
from .sources.ddproperty import _fallback_page_url, _page_data, _page_url, parse_card, project_of
from .store import Store, _write_json, summarise, today, utc_now

log = logging.getLogger("universe")

# Oldest first: new listings are appended at the end, so a crawl that takes an
# hour does not see pages shift under it the way the default ranking does.
BANGKOK_URL = "https://www.ddproperty.com/en/condo-for-sale?region_code=TH10&sort=date&order=asc"

# A crawl that reached fewer pages than this share of the total is treated as
# failed and written nowhere, so a mid-run block cannot look like a market crash.
MIN_COVERAGE = 0.9
MAX_EMPTY_PAGES = 3

# Fields not needed once a listing is filed under its project.
DROP_FIELDS = ("title", "address", "deal", "bathrooms", "floor", "last_seen", "previous_price")


@dataclass
class Project:
    id: str
    name: str
    district: str | None
    listings: dict[str, Listing] = field(default_factory=dict)


@dataclass
class CrawlStats:
    pages_expected: int = 0
    pages_fetched: int = 0
    pages_failed: int = 0
    listings: int = 0
    no_project: int = 0
    implausible: int = 0
    seconds: float = 0.0

    @property
    def coverage(self) -> float:
        return self.pages_fetched / self.pages_expected if self.pages_expected else 0.0


def crawl(fetcher: Fetcher, url: str, max_pages: int | None = None) -> tuple[dict[str, Project], CrawlStats]:
    """Walk every result page and file each listing under its project."""
    stats = CrawlStats()
    projects: dict[str, Project] = {}
    started = time.monotonic()

    first = _page_data(fetcher.get(url))
    pagination = first.get("paginationData") or {}
    total = int(pagination.get("totalPages") or 1)
    if max_pages:
        total = min(total, max_pages)
    stats.pages_expected = total
    log.info("crawling %d pages from %s", total, url)

    empty_run = 0
    page = 1
    data: dict[str, Any] | None = first
    while page <= total:
        if data is None:
            page_url = _page_url(pagination, page) or _fallback_page_url(url, page)
            try:
                data = _page_data(fetcher.get(page_url))
            except (FetchError, json.JSONDecodeError) as exc:
                stats.pages_failed += 1
                log.warning("page %d failed: %s", page, exc)
                page += 1
                continue

        # Past the real end the site serves its last page again under our page
        # number; that is the end, not new data.
        served = (data.get("paginationData") or {}).get("currentPage")
        if page > 1 and isinstance(served, int) and served < page:
            log.info("page %d served as page %d; reached the end", page, served)
            stats.pages_expected = page - 1
            break

        stats.pages_fetched += 1
        cards = data.get("listingsData") or []
        empty_run = 0 if cards else empty_run + 1
        for card in cards:
            listing = parse_card(card, "sale")
            if listing is None:
                continue
            project_id, name, district = project_of(card)
            if not project_id:
                stats.no_project += 1
                continue
            if listing.implausible():
                stats.implausible += 1
                continue
            project = projects.setdefault(project_id, Project(project_id, name, district))
            project.listings[listing.key] = listing

        if empty_run >= MAX_EMPTY_PAGES:
            # The total shrinks while we crawl (units get sold); stop at the real end.
            log.info("three empty pages in a row at page %d; treating as the end", page)
            stats.pages_expected = min(stats.pages_expected, page)
            break
        if page % 100 == 0:
            log.info("page %d/%d, %d projects so far", page, total, len(projects))
        data = None
        page += 1

    stats.listings = sum(len(p.listings) for p in projects.values())
    stats.seconds = round(time.monotonic() - started, 1)
    return projects, stats


def _median(values: list[float]) -> float | None:
    values = [v for v in values if v]
    return round(statistics.median(values)) if values else None


def _district_summary(rows_by_district: dict[str, list[dict[str, Any]]]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for name, rows in sorted(rows_by_district.items()):
        by_room = {}
        for bucket in ROOM_BUCKETS:
            sub = [r for r in rows if r.get("room") == bucket]
            if sub:
                by_room[bucket] = {
                    "listings": len(sub),
                    "median_ppsqm": _median([r.get("price_per_sqm") for r in sub]),
                    "median_price": _median([r.get("price") for r in sub]),
                }
        out[name] = {
            "listings": len(rows),
            "projects": len({r["_project"] for r in rows}),
            "median_ppsqm": _median([r.get("price_per_sqm") for r in rows]),
            "median_price": _median([r.get("price") for r in rows]),
            "by_room": by_room,
        }
    return out


def _pinned_lookup(config_path: Path):
    """Return a function mapping a DDproperty title to a pinned watch id, if any."""
    try:
        watches = load_watchlist(config_path)
    except (OSError, ValueError):
        return lambda title: None

    def find(title: str) -> str | None:
        probe = Listing(source="ddproperty", listing_id="-", url="", title=title)
        for watch in watches:
            if watch.matches_name(probe):
                return watch.id
        return None

    return find


def run(url: str, data_dir: Path, config_path: Path, max_pages: int | None, dry_run: bool) -> int:
    fetcher = Fetcher()
    projects, stats = crawl(fetcher, url, max_pages)
    log.info(
        "fetched %d/%d pages (%d failed), %d listings in %d projects, %.0fs",
        stats.pages_fetched, stats.pages_expected, stats.pages_failed,
        stats.listings, len(projects), stats.seconds,
    )
    if stats.coverage < MIN_COVERAGE:
        log.error("coverage %.0f%% is below %.0f%%; writing nothing", stats.coverage * 100, MIN_COVERAGE * 100)
        return 2
    if dry_run:
        return 0

    root = data_dir / "universe"
    store = Store(root, compact=True)
    run_date = today()
    pinned = _pinned_lookup(config_path)
    index: list[dict[str, Any]] = []
    rows_by_district: dict[str, list[dict[str, Any]]] = {}

    for project in projects.values():
        wid = f"dd-{project.id}"
        records = store.merge(store.load_records(wid), project.listings.values(), run_date=run_date)
        for row in records.values():
            for name in DROP_FIELDS:
                row.pop(name, None)
        store.save_snapshot(
            wid,
            records,
            {
                "project": project.name,
                "district": project.district,
                "deal": "sale",
                "sources": [{"source": "ddproperty", "status": "ok", "detail": "",
                             "listings_found": len(records)}],
            },
        )
        point = summarise(records.values(), run_date)
        store.append_history(wid, point)

        sample_title = next(iter(project.listings.values())).title
        index.append({
            "id": wid,
            "project": project.name,
            "district": project.district,
            "listings": point["listings"],
            "median_price": point["median_price"],
            "median_ppsqm": point["median_ppsqm"],
            "min_price": point["min_price"],
            "max_price": point["max_price"],
            "by_room": {
                name: {k: agg[k] for k in ("listings", "median_price", "median_ppsqm", "min_price")}
                for name, agg in point["by_room"].items()
            },
            "pinned_as": pinned(sample_title),
        })
        for row in records.values():
            rows_by_district.setdefault(project.district or "—", []).append({**row, "_project": wid})

    index.sort(key=lambda e: (-e["listings"], e["project"]))
    _write_json(
        root / "index.json",
        {
            "generated_at": utc_now(),
            "source": "ddproperty",
            "region": "Bangkok",
            "crawl": {**vars(stats), "coverage": round(stats.coverage, 3)},
            "overall": _district_summary(
                {"all": [r for rows in rows_by_district.values() for r in rows]}
            ).get("all"),
            "districts": _district_summary(rows_by_district),
            "projects": index,
        },
        compact=True,
    )

    github_output = os.environ.get("GITHUB_OUTPUT")
    if github_output:
        with open(github_output, "a", encoding="utf-8") as handle:
            handle.write(f"projects={len(index)}\nlistings={stats.listings}\n")
    log.info("wrote %d projects", len(index))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--url", default=BANGKOK_URL)
    parser.add_argument("--data", default="data", type=Path)
    parser.add_argument("--config", default="config/watchlist.yml", type=Path)
    parser.add_argument("--max-pages", type=int, help="stop early (for testing)")
    parser.add_argument("--dry-run", action="store_true", help="crawl but write nothing")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(message)s",
        datefmt="%H:%M:%S",
    )
    try:
        return run(args.url, args.data, args.config, args.max_pages, args.dry_run)
    except (OSError, ValueError, FetchError) as exc:
        log.error("%s", exc)
        return 1


if __name__ == "__main__":
    sys.exit(main())
