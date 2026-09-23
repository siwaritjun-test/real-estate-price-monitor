"""Hipflat adapter -- present but disabled by default.

Hipflat sits behind a Cloudflare rule that answers every non-browser request
with ``401 Access Denied``, including ``/robots.txt``. The only response that
gets through is one that claims to be Googlebot, and impersonating a search
crawler to evade a block is not something this project does. The adapter is
therefore shipped switched off: it reports ``blocked`` with the reason so the
dashboard can say why the source is missing rather than silently omitting it.

If the site ever serves ordinary clients again, set ``enabled: true`` on the
source in the watchlist and this will start contributing without further
changes.
"""

from __future__ import annotations

import re
from typing import Any

from bs4 import BeautifulSoup

from ..config import Watch
from ..http import Fetcher, FetchError
from ..models import Listing
from .base import Source, SourceResult

BLOCKED_NOTE = (
    "Hipflat refuses non-browser requests (Cloudflare 401 on every path, "
    "robots.txt included). Enable this source only if it starts serving "
    "ordinary clients."
)

PRICE_RE = re.compile(r"฿\s*([\d,]{5,})")
AREA_RE = re.compile(r"([\d,.]+)\s*(?:sqm|sq\.m\.|m²)", re.I)
BEDROOM_RE = re.compile(r"(\d+)\s*bed", re.I)


class Hipflat(Source):
    name = "hipflat"

    def collect(self, watch: Watch, options: dict[str, Any], fetcher: Fetcher) -> SourceResult:
        url = options.get("url")
        result = SourceResult(source=self.name)
        if not url:
            result.status = "skipped"
            result.detail = "no 'url' configured for this source"
            return result

        try:
            html = fetcher.get(url)
        except FetchError as exc:
            message = str(exc)
            if "401" in message or "403" in message:
                result.status = "blocked"
                result.detail = BLOCKED_NOTE
            else:
                result.status = "error"
                result.detail = message
            return result

        result.pages_fetched = 1
        result.listings = self._parse(html, url, watch)
        if not result.listings:
            result.status = "error"
            result.detail = "page fetched but no listings parsed -- layout has changed"
        return result

    def _parse(self, html: str, url: str, watch: Watch) -> list[Listing]:
        """Best-effort card parse, unverified against a live page (see module docs)."""
        soup = BeautifulSoup(html, "lxml")
        listings: list[Listing] = []
        for anchor in soup.select("a[href*='/listing'], a[href*='/property']"):
            href = anchor.get("href") or ""
            listing_id = href.rstrip("/").rsplit("/", 1)[-1]
            if not listing_id:
                continue
            text = anchor.get_text(" ", strip=True)
            price = PRICE_RE.search(text)
            area = AREA_RE.search(text)
            beds = BEDROOM_RE.search(text)
            listings.append(
                Listing(
                    source=self.name,
                    listing_id=listing_id,
                    url=href if href.startswith("http") else f"https://www.hipflat.co.th{href}",
                    title=text[:160],
                    deal=watch.deal,
                    price=int(price.group(1).replace(",", "")) if price else None,
                    area_sqm=float(area.group(1).replace(",", "")) if area else None,
                    bedrooms=int(beds.group(1)) if beds else None,
                )
            )
        return listings
