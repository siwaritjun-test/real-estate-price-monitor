"""Watchlist loading and the room-type filter that decides what counts as a hit."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from .models import Listing, normalise


@dataclass
class RoomType:
    """The unit shape being tracked. Every populated field must match."""

    bedrooms: int | None = None
    bathrooms: int | None = None
    min_sqm: float | None = None
    max_sqm: float | None = None

    def matches(self, listing: Listing) -> bool:
        if self.bedrooms is not None and listing.bedrooms != self.bedrooms:
            return False
        if self.bathrooms is not None and listing.bathrooms != self.bathrooms:
            return False
        if self.min_sqm is not None:
            if listing.area_sqm is None or listing.area_sqm < self.min_sqm:
                return False
        if self.max_sqm is not None:
            if listing.area_sqm is None or listing.area_sqm > self.max_sqm:
                return False
        return True

    def describe(self) -> str:
        bits = []
        if self.bedrooms is not None:
            bits.append(f"{self.bedrooms} bed")
        if self.min_sqm is not None or self.max_sqm is not None:
            lo = f"{self.min_sqm:g}" if self.min_sqm is not None else ""
            hi = f"{self.max_sqm:g}" if self.max_sqm is not None else ""
            bits.append(f"{lo}–{hi} sqm".strip("–"))
        return ", ".join(bits) or "any unit"


@dataclass
class AlertRules:
    """Thresholds that decide when a change is worth telling someone about."""

    min_drop_pct: float = 1.0
    min_drop_thb: int = 20_000
    alert_new: bool = True
    alert_price_drop: bool = True


@dataclass
class Watch:
    """One project + room type tracked across one or more sources."""

    id: str
    project: str
    match: list[str]
    exclude: list[str] = field(default_factory=list)
    deal: str = "sale"
    room_type: RoomType = field(default_factory=RoomType)
    alerts: AlertRules = field(default_factory=AlertRules)
    sources: dict[str, dict[str, Any]] = field(default_factory=dict)

    def matches_name(self, listing: Listing) -> bool:
        """True when the listing title names this project and nothing excluded."""
        title = normalise(listing.title)
        if not any(normalise(p) in title for p in self.match):
            return False
        return not any(normalise(p) in title for p in self.exclude)

    def accepts(self, listing: Listing) -> bool:
        return self.matches_name(listing) and self.room_type.matches(listing)

    def enabled_sources(self) -> dict[str, dict[str, Any]]:
        return {
            name: opts
            for name, opts in self.sources.items()
            if opts.get("enabled", True)
        }

    def disabled_sources(self) -> dict[str, dict[str, Any]]:
        """Sources switched off in config, kept so the dashboard can say why."""
        return {
            name: opts
            for name, opts in self.sources.items()
            if not opts.get("enabled", True)
        }


def load_watchlist(path: str | Path) -> list[Watch]:
    """Parse config/watchlist.yml into Watch objects."""
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    defaults = raw.get("defaults") or {}
    watches: list[Watch] = []
    seen: set[str] = set()

    for entry in raw.get("watches") or []:
        wid = entry.get("id")
        if not wid:
            raise ValueError(f"watch entry is missing an 'id': {entry!r}")
        if wid in seen:
            raise ValueError(f"duplicate watch id: {wid}")
        seen.add(wid)

        alert_cfg = {**(defaults.get("alerts") or {}), **(entry.get("alerts") or {})}
        watches.append(
            Watch(
                id=wid,
                project=entry.get("project") or wid,
                match=entry.get("match") or [entry.get("project") or wid],
                exclude=entry.get("exclude") or [],
                deal=entry.get("deal") or defaults.get("deal") or "sale",
                room_type=RoomType(**(entry.get("room_type") or {})),
                alerts=AlertRules(**alert_cfg),
                sources=entry.get("sources") or {},
            )
        )

    if not watches:
        raise ValueError(f"no watches defined in {path}")
    return watches
