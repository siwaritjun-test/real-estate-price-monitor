"""Turn the difference between two snapshots into the alerts the user asked for."""

from __future__ import annotations

from typing import Any

from .config import Watch
from .models import Listing
from .store import utc_now


def _base(watch: Watch, listing: Listing, run_date: str) -> dict[str, Any]:
    return {
        "watch_id": watch.id,
        "project": watch.project,
        "room_type": watch.room_type.describe(),
        "source": listing.source,
        "listing_id": listing.listing_id,
        "title": listing.title,
        "url": listing.url,
        "area_sqm": listing.area_sqm,
        "bedrooms": listing.bedrooms,
        "date": run_date,
        "detected_at": utc_now(),
    }


def detect(
    watch: Watch,
    previous: dict[str, dict[str, Any]],
    listings: list[Listing],
    *,
    run_date: str,
    bootstrap: bool,
) -> list[dict[str, Any]]:
    """Compare this run against the last one.

    On a watch's first ever run ``bootstrap`` is true and no "new listing"
    alerts are emitted -- otherwise day one would fire one alert per unit on
    the market, which is noise rather than news.
    """
    rules = watch.alerts
    alerts: list[dict[str, Any]] = []

    for listing in listings:
        old = previous.get(listing.key)

        if old is None:
            if rules.alert_new and not bootstrap:
                alerts.append(
                    {
                        **_base(watch, listing, run_date),
                        "type": "new_listing",
                        "price": listing.price,
                        "price_per_sqm": listing.price_per_sqm,
                    }
                )
            continue

        if not rules.alert_price_drop:
            continue

        old_price = old.get("price")
        if not (old_price and listing.price and listing.price < old_price):
            continue

        drop = old_price - listing.price
        drop_pct = round(drop / old_price * 100, 2)
        if drop < rules.min_drop_thb or drop_pct < rules.min_drop_pct:
            continue

        alerts.append(
            {
                **_base(watch, listing, run_date),
                "type": "price_drop",
                "price": listing.price,
                "previous_price": old_price,
                "drop": drop,
                "drop_pct": drop_pct,
                "price_per_sqm": listing.price_per_sqm,
            }
        )

    # Biggest, most actionable first.
    alerts.sort(key=lambda a: (a["type"] != "price_drop", -(a.get("drop") or 0)))
    return alerts


def format_markdown(alerts: list[dict[str, Any]]) -> str:
    """Render alerts as the body of a GitHub issue / chat notification."""
    if not alerts:
        return "No new alerts."

    drops = [a for a in alerts if a["type"] == "price_drop"]
    new = [a for a in alerts if a["type"] == "new_listing"]
    lines: list[str] = []

    def money(value: Any) -> str:
        return f"฿{value:,.0f}" if value else "price on ask"

    if drops:
        lines.append(f"### Price drops ({len(drops)})\n")
        for a in drops:
            lines.append(
                f"- **{a['project']}** · {a['room_type']} · _{a['source']}_ — "
                f"{money(a['previous_price'])} → **{money(a['price'])}** "
                f"(−{money(a['drop'])}, −{a['drop_pct']}%) · [listing]({a['url']})"
            )
        lines.append("")

    if new:
        lines.append(f"### New listings ({len(new)})\n")
        for a in new:
            size = f" · {a['area_sqm']:g} sqm" if a.get("area_sqm") else ""
            ppsqm = f" · ฿{a['price_per_sqm']:,}/sqm" if a.get("price_per_sqm") else ""
            lines.append(
                f"- **{a['project']}** · {a['room_type']} · _{a['source']}_ — "
                f"{money(a['price'])}{size}{ppsqm} · [listing]({a['url']})"
            )
        lines.append("")

    return "\n".join(lines).strip()
