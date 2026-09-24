"""Normalised listing record shared by every source adapter."""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from typing import Any


def normalise(text: str | None) -> str:
    """Lowercase and collapse everything non-alphanumeric to single spaces.

    Used for project-name matching so that "IDEO MOBI Sukhumvit 81" and
    "Ideo-Mobi Sukhumvit81" compare equal to the watchlist phrase.
    """
    if not text:
        return ""
    return re.sub(r"[^a-z0-9฀-๿]+", " ", text.lower()).strip()


# Bedroom buckets the history is split by, in display order. The dashboard
# filters on these keys, so they are part of the data format.
ROOM_BUCKETS = ("studio", "1br", "2br", "3br+", "unknown")
ROOM_LABELS = {
    "studio": "Studio",
    "1br": "1 bed",
    "2br": "2 bed",
    "3br+": "3+ bed",
    "unknown": "Unknown beds",
}


def room_bucket(bedrooms: int | None) -> str:
    """Map a bedroom count to its history bucket (0 means studio)."""
    if bedrooms is None:
        return "unknown"
    if bedrooms <= 0:
        return "studio"
    if bedrooms >= 3:
        return "3br+"
    return f"{bedrooms}br"


@dataclass
class Listing:
    """One unit on the market, as seen by one source at one point in time."""

    source: str
    listing_id: str
    url: str
    title: str
    deal: str = "sale"
    price: int | None = None
    area_sqm: float | None = None
    bedrooms: int | None = None
    bathrooms: int | None = None
    floor: int | None = None
    address: str | None = None
    posted_on: str | None = None

    @property
    def key(self) -> str:
        return f"{self.source}:{self.listing_id}"

    @property
    def price_per_sqm(self) -> int | None:
        if self.price and self.area_sqm:
            return round(self.price / self.area_sqm)
        return None

    def implausible(self) -> str | None:
        """Reason this record looks like a parse failure, or None if it is sane.

        A mis-parsed number is worse than a missing one: it silently drags the
        median. These bounds are wide enough to never reject a real Bangkok
        condo and tight enough to catch a page counter read as a price.
        """
        if self.area_sqm is not None and not 5 <= self.area_sqm <= 2000:
            return f"area {self.area_sqm} sqm out of range"
        if self.price is None:
            return None
        if self.deal == "sale" and self.price < 100_000:
            return f"sale price {self.price} below floor"
        if self.deal == "rent" and self.price > 2_000_000:
            return f"rent price {self.price} above ceiling"
        # A size typo (532 for 53.2 sqm) or a rent posted as a sale lands far
        # outside anything a Bangkok condo sells for per square metre.
        ppsqm = self.price_per_sqm
        if self.deal == "sale" and ppsqm and not 15_000 <= ppsqm <= 1_000_000:
            return f"{ppsqm:,} baht/sqm is outside the plausible range"
        return None

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["key"] = self.key
        d["price_per_sqm"] = self.price_per_sqm
        d["room"] = room_bucket(self.bedrooms)
        return d
