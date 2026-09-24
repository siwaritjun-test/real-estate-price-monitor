"""JSON persistence: snapshots, daily history, alert log, and the dashboard index."""

from __future__ import annotations

import json
import statistics
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from .models import ROOM_BUCKETS, Listing, room_bucket

HISTORY_LIMIT = 730  # roughly two years of daily points
ALERT_LIMIT = 500


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def today() -> str:
    return datetime.now(timezone.utc).date().isoformat()


def _read_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return default


def _write_json(path: Path, payload: Any, compact: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = (
        json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        if compact
        else json.dumps(payload, ensure_ascii=False, indent=1, sort_keys=False)
    )
    path.write_text(text + "\n", encoding="utf-8")


def _median(values: Iterable[float]) -> float | None:
    data = [v for v in values if v is not None]
    return round(statistics.median(data), 2) if data else None


@dataclass
class Store:
    """All reads and writes under the data directory."""

    root: Path
    # Thousands of universe files are written per run; skip the indentation.
    compact: bool = False

    def __post_init__(self) -> None:
        self.root = Path(self.root)

    # -- paths ---------------------------------------------------------------
    def snapshot_path(self, watch_id: str) -> Path:
        return self.root / "snapshots" / f"{watch_id}.json"

    def history_path(self, watch_id: str) -> Path:
        return self.root / "history" / f"{watch_id}.json"

    @property
    def alerts_path(self) -> Path:
        return self.root / "alerts.json"

    @property
    def index_path(self) -> Path:
        return self.root / "watches.json"

    # -- snapshots -----------------------------------------------------------
    def load_records(self, watch_id: str) -> dict[str, dict[str, Any]]:
        """Return the previous run's listings keyed by ``source:id``."""
        data = _read_json(self.snapshot_path(watch_id), {})
        return {row["key"]: row for row in data.get("listings", []) if "key" in row}

    def save_snapshot(self, watch_id: str, records: dict[str, dict[str, Any]], meta: dict[str, Any]) -> None:
        payload = {
            "watch_id": watch_id,
            "updated_at": utc_now(),
            **meta,
            "listings": sorted(
                records.values(),
                key=lambda r: (r.get("price") is None, r.get("price") or 0),
            ),
        }
        _write_json(self.snapshot_path(watch_id), payload, self.compact)

    def merge(
        self,
        previous: dict[str, dict[str, Any]],
        listings: Iterable[Listing],
        *,
        run_date: str,
    ) -> dict[str, dict[str, Any]]:
        """Fold this run's listings onto the previous records, keeping provenance."""
        merged: dict[str, dict[str, Any]] = {}
        for listing in listings:
            row = listing.to_dict()
            old = previous.get(listing.key)
            if old:
                row["first_seen"] = old.get("first_seen", run_date)
                row["first_price"] = old.get("first_price") or listing.price
                row["previous_price"] = old.get("price")
                changes = list(old.get("price_changes") or [])
                old_price = old.get("price")
                if listing.price and old_price and listing.price != old_price:
                    changes.append({"date": run_date, "from": old_price, "to": listing.price})
                row["price_changes"] = changes[-20:]
            else:
                row["first_seen"] = run_date
                row["first_price"] = listing.price
                row["previous_price"] = None
                row["price_changes"] = []
            row["last_seen"] = run_date
            merged[listing.key] = row
        return merged

    # -- history -------------------------------------------------------------
    def load_history(self, watch_id: str) -> list[dict[str, Any]]:
        return _read_json(self.history_path(watch_id), {}).get("points", [])

    def append_history(self, watch_id: str, point: dict[str, Any]) -> None:
        """Add today's aggregate, replacing an earlier point from the same day."""
        data = _read_json(self.history_path(watch_id), {"watch_id": watch_id, "points": []})
        points = [p for p in data.get("points", []) if p.get("date") != point["date"]]
        points.append(point)
        points.sort(key=lambda p: p["date"])
        data["watch_id"] = watch_id
        data["points"] = points[-HISTORY_LIMIT:]
        _write_json(self.history_path(watch_id), data, self.compact)

    # -- alerts --------------------------------------------------------------
    def append_alerts(self, new_alerts: list[dict[str, Any]]) -> list[dict[str, Any]]:
        data = _read_json(self.alerts_path, {"alerts": []})
        alerts = new_alerts + data.get("alerts", [])
        alerts = alerts[:ALERT_LIMIT]
        _write_json(self.alerts_path, {"generated_at": utc_now(), "alerts": alerts})
        return alerts

    # -- index ---------------------------------------------------------------
    def save_index(self, entries: list[dict[str, Any]]) -> None:
        _write_json(self.index_path, {"generated_at": utc_now(), "watches": entries})


def summarise(records: Iterable[dict[str, Any]], run_date: str) -> dict[str, Any]:
    """Build one daily history point from the current set of listings.

    The top level covers every unit in the project; ``by_room`` repeats the same
    figures per bedroom bucket so the dashboard can chart one room type alone.
    """
    rows = list(records)
    point = {"date": run_date, **_aggregate(rows)}

    rooms: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        rooms.setdefault(row.get("room") or room_bucket(row.get("bedrooms")), []).append(row)
    point["by_room"] = {
        name: _aggregate(rooms[name]) for name in ROOM_BUCKETS if name in rooms
    }
    return point


def _aggregate(rows: list[dict[str, Any]]) -> dict[str, Any]:
    prices = [r["price"] for r in rows if r.get("price")]
    ppsqm = [r["price_per_sqm"] for r in rows if r.get("price_per_sqm")]

    by_source: dict[str, Any] = {}
    for row in rows:
        bucket = by_source.setdefault(row["source"], {"prices": [], "ppsqm": []})
        if row.get("price"):
            bucket["prices"].append(row["price"])
        if row.get("price_per_sqm"):
            bucket["ppsqm"].append(row["price_per_sqm"])

    return {
        "listings": len(rows),
        "priced_listings": len(prices),
        "median_price": _median(prices),
        "median_ppsqm": _median(ppsqm),
        "min_price": min(prices) if prices else None,
        "max_price": max(prices) if prices else None,
        "by_source": {
            name: {
                "listings": len(bucket["prices"]) or None,
                "median_price": _median(bucket["prices"]),
                "median_ppsqm": _median(bucket["ppsqm"]),
            }
            for name, bucket in sorted(by_source.items())
        },
    }
