"""Source adapter contract and the result wrapper that carries per-source health."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..config import Watch
from ..http import Fetcher
from ..models import Listing


@dataclass
class SourceResult:
    """What one source returned for one watch, including how it went."""

    source: str
    listings: list[Listing] = field(default_factory=list)
    status: str = "ok"  # ok | blocked | error | skipped
    detail: str = ""
    pages_fetched: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "status": self.status,
            "detail": self.detail,
            "pages_fetched": self.pages_fetched,
            "listings_found": len(self.listings),
        }


class Source:
    """Base class for site adapters.

    An adapter turns a watch's configured URL into raw Listings. It must not
    filter by project or room type — main.py applies the watch filters so that
    the same rules are used for every source.
    """

    name = "base"

    def collect(self, watch: Watch, options: dict[str, Any], fetcher: Fetcher) -> SourceResult:
        raise NotImplementedError
