"""Compare today against the past: history lookups and like-for-like price moves.

Two kinds of comparison, because they answer different questions:

- **Median then vs now** -- what the market is asking today against N days ago.
  Honest but noisy: if cheap units sell and expensive ones list, the median rises
  with no unit changing price.
- **Same-unit moves** -- only listings that were on the market N days ago *and*
  still are, comparing each one's own asking price then and now. This is the
  like-for-like signal: are sellers cutting?
"""

from __future__ import annotations

import statistics
from datetime import date, timedelta
from typing import Any, Iterable

PERIODS = (1, 7, 30, 90, 365)
# How far from the exact target day a history point may be and still count.
TOLERANCE = {1: 1, 7: 2, 30: 5, 90: 10, 365: 21}


def days_ago(run_date: str, days: int) -> str:
    return (date.fromisoformat(run_date) - timedelta(days=days)).isoformat()


def point_near(points: list[dict[str, Any]], target: str, tolerance: int) -> dict[str, Any] | None:
    """The history point closest to ``target``, if one lies within ``tolerance`` days."""
    goal = date.fromisoformat(target)
    best, best_gap = None, tolerance + 1
    for point in points:
        gap = abs((date.fromisoformat(point["date"]) - goal).days)
        if gap < best_gap:
            best, best_gap = point, gap
    return best


def price_on(row: dict[str, Any], day: str) -> int | None:
    """A listing's asking price on ``day``, rebuilt from its change log."""
    first_seen = row.get("first_seen")
    if not first_seen or first_seen > day:
        return None
    price = row.get("first_price")
    for change in row.get("price_changes") or []:
        if change.get("date", "") <= day:
            price = change.get("to", price)
    return price


def unit_moves(rows: Iterable[dict[str, Any]], day: str) -> dict[str, Any] | None:
    """Like-for-like asking-price moves since ``day`` for listings present then and now."""
    pcts = []
    for row in rows:
        then = price_on(row, day)
        now = row.get("price")
        if then and now:
            pcts.append((now - then) / then * 100)
    if not pcts:
        return None
    return {
        "units": len(pcts),
        "cut": sum(1 for p in pcts if p < -0.05),
        "raised": sum(1 for p in pcts if p > 0.05),
        "median_pct": round(statistics.median(pcts), 2),
        # The median is 0 whenever fewer than half the units moved; the mean
        # still shows a market where a third of sellers cut.
        "mean_pct": round(statistics.fmean(pcts), 2),
    }


def past_medians(points: list[dict[str, Any]], run_date: str) -> dict[str, Any]:
    """{period: {room: median ฿/sqm then}} for each period that has a history point."""
    out: dict[str, Any] = {}
    earlier = [p for p in points if p["date"] < run_date]
    for period in PERIODS:
        point = point_near(earlier, days_ago(run_date, period), TOLERANCE[period])
        if not point:
            continue
        rooms = {"all": point.get("median_ppsqm")}
        for name, agg in (point.get("by_room") or {}).items():
            rooms[name] = agg.get("median_ppsqm")
        rooms = {k: v for k, v in rooms.items() if v}
        if rooms:
            out[str(period)] = rooms
    return out


def append_trend(trend: dict[str, Any], run_date: str, values: dict[str, float | None]) -> dict[str, Any]:
    """Add one day to a columnar series store: {"dates": [...], "series": {key: [...]}}.

    Columnar so years of daily district figures stay small enough to load on a phone.
    A same-day rerun replaces that day's column.
    """
    dates = list(trend.get("dates") or [])
    series = {k: list(v) for k, v in (trend.get("series") or {}).items()}
    if dates and dates[-1] == run_date:
        col = len(dates) - 1
    else:
        dates.append(run_date)
        col = len(dates) - 1
    for key in set(series) | set(values):
        column = series.setdefault(key, [])
        column.extend([None] * (len(dates) - len(column)))
        column[col] = values.get(key)
    return {"dates": dates, "series": series}
