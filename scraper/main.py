"""Run every watch against every enabled source and write the dashboard data."""

from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path
from typing import Any

from . import alerts as alerts_mod
from .config import Watch, load_watchlist
from .http import Fetcher
from .models import Listing
from .sources import REGISTRY
from .sources.base import SourceResult
from .store import Store, summarise, today

log = logging.getLogger("monitor")


def collect_watch(watch: Watch, fetcher: Fetcher) -> tuple[list[Listing], list[SourceResult]]:
    """Fetch every enabled source for one watch and apply the watch's filters."""
    kept: list[Listing] = []
    results: list[SourceResult] = []

    for name, options in watch.enabled_sources().items():
        adapter_cls = REGISTRY.get(name)
        if adapter_cls is None:
            results.append(
                SourceResult(source=name, status="skipped", detail=f"unknown source '{name}'")
            )
            continue

        log.info("[%s] fetching %s", watch.id, name)
        try:
            result = adapter_cls().collect(watch, options, fetcher)
        except Exception as exc:  # a broken adapter must not sink the whole run
            log.exception("[%s] %s raised", watch.id, name)
            results.append(SourceResult(source=name, status="error", detail=repr(exc)))
            continue

        matched = []
        for item in result.listings:
            if not watch.accepts(item):
                continue
            reason = item.implausible()
            if reason:
                log.warning("[%s] %s: dropping %s -- %s", watch.id, name, item.url, reason)
                continue
            matched.append(item)
        log.info(
            "[%s] %s: %d found, %d match %s",
            watch.id,
            name,
            len(result.listings),
            len(matched),
            watch.room_type.describe(),
        )
        result.listings = matched
        results.append(result)
        kept.extend(matched)

    # Record switched-off sources too, so the dashboard shows why a site is
    # missing rather than silently leaving it out.
    for name, options in watch.disabled_sources().items():
        results.append(
            SourceResult(
                source=name,
                status="disabled",
                detail=options.get("reason", "disabled in config/watchlist.yml"),
            )
        )

    return kept, results


def run(config_path: Path, data_dir: Path, only: list[str] | None, dry_run: bool) -> int:
    watches = load_watchlist(config_path)
    if only:
        watches = [w for w in watches if w.id in only]
        if not watches:
            log.error("no watch matched %s", only)
            return 1

    store = Store(data_dir)
    fetcher = Fetcher()
    run_date = today()
    index: list[dict[str, Any]] = []
    fresh_alerts: list[dict[str, Any]] = []

    for watch in watches:
        previous = store.load_records(watch.id)
        listings, results = collect_watch(watch, fetcher)

        # Never let a source outage look like every unit vanishing: if a source
        # that had listings last run returns none this run, keep its previous
        # records rather than treating them as delisted.
        failed = {r.source for r in results if r.status in ("error", "blocked")}
        carried = 0
        if failed:
            for key, row in previous.items():
                if row.get("source") in failed and key not in {l.key for l in listings}:
                    listings.append(Listing(**{
                        k: row.get(k) for k in (
                            "source", "listing_id", "url", "title", "deal", "price",
                            "area_sqm", "bedrooms", "bathrooms", "floor", "address",
                            "posted_on",
                        )
                    }))
                    carried += 1
            if carried:
                log.warning("[%s] carried %d record(s) from failed source(s)", watch.id, carried)

        bootstrap = not previous
        watch_alerts = alerts_mod.detect(
            watch, previous, listings, run_date=run_date, bootstrap=bootstrap
        )
        fresh_alerts.extend(watch_alerts)

        records = store.merge(previous, listings, run_date=run_date)
        point = summarise(records.values(), run_date)

        if dry_run:
            log.info("[%s] dry run: %s", watch.id, point)
        else:
            store.save_snapshot(
                watch.id,
                records,
                {
                    "project": watch.project,
                    "room_type": watch.room_type.describe(),
                    "deal": watch.deal,
                    "sources": [r.to_dict() for r in results],
                    "carried_over": carried,
                },
            )
            store.append_history(watch.id, point)

        index.append(
            {
                "id": watch.id,
                "project": watch.project,
                "room_type": watch.room_type.describe(),
                "deal": watch.deal,
                "listings": point["listings"],
                "median_price": point["median_price"],
                "median_ppsqm": point["median_ppsqm"],
                "bootstrap": bootstrap,
                "sources": [r.to_dict() for r in results],
            }
        )

    if dry_run:
        log.info("dry run complete: %d alert(s) would fire", len(fresh_alerts))
        return 0

    store.save_index(index)
    store.append_alerts(fresh_alerts)

    body = alerts_mod.format_markdown(fresh_alerts)
    (data_dir / "latest_alerts.md").write_text(body + "\n", encoding="utf-8")

    # Let the workflow decide whether to notify without re-parsing the markdown.
    github_output = os.environ.get("GITHUB_OUTPUT")
    if github_output:
        with open(github_output, "a", encoding="utf-8") as handle:
            handle.write(f"alert_count={len(fresh_alerts)}\n")

    log.info("%d new alert(s)", len(fresh_alerts))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default="config/watchlist.yml", type=Path)
    parser.add_argument("--data", default="data", type=Path)
    parser.add_argument("--watch", action="append", help="only run this watch id (repeatable)")
    parser.add_argument("--dry-run", action="store_true", help="fetch but write nothing")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(message)s",
        datefmt="%H:%M:%S",
    )

    try:
        return run(args.config, args.data, args.watch, args.dry_run)
    except (OSError, ValueError) as exc:
        log.error("%s", exc)
        return 1


if __name__ == "__main__":
    sys.exit(main())
