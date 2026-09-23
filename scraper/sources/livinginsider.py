"""Livinginsider adapter.

Search results on Livinginsider are client-rendered and its ``/api/`` routes are
disallowed by robots.txt, so neither is usable. Project pages, however, are
server-rendered and carry every listing link for the project; each detail page
then carries a plain-text spec block ("FOR SELL : 2,490,000", "Usable area : 22
sqm", ...) that we parse. That costs one request per listing, so ``max_listings``
caps the work per run.
"""

from __future__ import annotations

import logging
import re
from typing import Any

from bs4 import BeautifulSoup

from ..config import Watch
from ..http import Fetcher, FetchError
from ..models import Listing
from .base import Source, SourceResult

log = logging.getLogger(__name__)

BASE = "https://www.livinginsider.com"
DETAIL_HREF_RE = re.compile(r'href="(/(?:en/)?detail/[^"#?]+)"')
ID_FROM_URL_RE = re.compile(r"-(\d+)$")
BEDROOM_FROM_URL_RE = re.compile(r"-(\d+)bedroom", re.I)

# The spec block starts at "Listing ID". Field patterns are matched inside it
# and never span a line break, because the surrounding page carries site-wide
# counters ("For sale : 64,498") that otherwise match first and would price a
# unit at 64,498 baht.
SPEC_ANCHOR_RE = re.compile(r"Listing ID[^\S\n]*:[^\S\n]*[A-Za-z0-9\-]+")
SPEC_BLOCK_CHARS = 1500

H = r"[^\S\n]*"  # horizontal whitespace only
FIELD_PATTERNS = {
    "listing_code": re.compile(rf"Listing ID{H}:{H}([A-Za-z0-9\-]+)"),
    "price": re.compile(rf"FOR (?:SELL|SALE|RENT){H}:{H}([\d,]+)"),
    "area_sqm": re.compile(rf"Usable area{H}:{H}([\d,.]+){H}sqm", re.I),
    "bedrooms": re.compile(rf"No\.?{H}of Bedroom{H}:{H}(\d+)", re.I),
    "bathrooms": re.compile(rf"No\.?{H}of Bathroom{H}:{H}(\d+)", re.I),
    # Anchored to line start (leading indent allowed) so the neighbouring
    # "No of floors : 25" cannot win over "Floor : 23".
    "floor": re.compile(rf"(?mi)^{H}Floor{H}:{H}(\d+)"),
}
# Fallback for the rendered price chip, e.g. "฿ 2,490,000".
PRICE_CHIP_RE = re.compile(rf"฿{H}([\d,]{{7,}})")


def _to_number(text: str | None) -> float | None:
    if not text:
        return None
    try:
        return float(text.replace(",", ""))
    except ValueError:
        return None


def _absolute(href: str) -> str:
    return href if href.startswith("http") else f"{BASE}{href}"


class LivingInsider(Source):
    name = "livinginsider"

    def collect(self, watch: Watch, options: dict[str, Any], fetcher: Fetcher) -> SourceResult:
        url = options.get("url")
        result = SourceResult(source=self.name)
        if not url:
            result.status = "skipped"
            result.detail = "no 'url' configured for this source"
            return result

        max_listings = int(options.get("max_listings", 60))

        try:
            project_html = fetcher.get(url)
        except FetchError as exc:
            result.status = "blocked" if "401" in str(exc) or "403" in str(exc) else "error"
            result.detail = str(exc)
            return result
        result.pages_fetched = 1

        detail_urls = self._detail_urls(project_html)
        if not detail_urls:
            result.status = "error"
            result.detail = "project page contained no listing links -- check the 'url'"
            return result

        truncated = len(detail_urls) > max_listings
        failures = 0
        for detail_url in detail_urls[:max_listings]:
            try:
                listing = self._parse_detail(fetcher.get(detail_url), detail_url, watch)
            except FetchError as exc:
                failures += 1
                log.warning("livinginsider detail failed: %s", exc)
                continue
            result.pages_fetched += 1
            if listing:
                result.listings.append(listing)

        notes = []
        if truncated:
            notes.append(f"capped at max_listings={max_listings} of {len(detail_urls)} found")
        if failures:
            notes.append(f"{failures} detail page(s) failed")
        result.detail = "; ".join(notes)
        if not result.listings:
            result.status = "error"
            result.detail = result.detail or "no listing details could be parsed"
        return result

    def _detail_urls(self, html: str) -> list[str]:
        """Collect unique detail links, preferring the English version of each."""
        by_id: dict[str, str] = {}
        for href in DETAIL_HREF_RE.findall(html):
            match = ID_FROM_URL_RE.search(href)
            if not match:
                continue
            listing_id = match.group(1)
            # /en/detail/... and /detail/... are the same unit; keep /en/.
            if listing_id not in by_id or href.startswith("/en/"):
                by_id[listing_id] = href
        return [_absolute(h) for h in by_id.values()]

    def _parse_detail(self, html: str, url: str, watch: Watch) -> Listing | None:
        id_match = ID_FROM_URL_RE.search(url)
        if not id_match:
            return None

        soup = BeautifulSoup(html, "lxml")
        text = soup.get_text("\n")

        anchor = SPEC_ANCHOR_RE.search(text)
        block = text[anchor.start() : anchor.start() + SPEC_BLOCK_CHARS] if anchor else text

        values: dict[str, Any] = {}
        for field, pattern in FIELD_PATTERNS.items():
            match = pattern.search(block)
            values[field] = match.group(1) if match else None

        price = _to_number(values["price"])
        if price is None:
            chip = PRICE_CHIP_RE.search(block)
            price = _to_number(chip.group(1)) if chip else None

        bedrooms = values["bedrooms"]
        if bedrooms is None:
            url_bed = BEDROOM_FROM_URL_RE.search(url)
            bedrooms = url_bed.group(1) if url_bed else None

        title = soup.title.get_text(strip=True) if soup.title else ""
        title = re.sub(r"\s*\|\s*Livinginsider\s*$", "", title)

        return Listing(
            source=self.name,
            listing_id=id_match.group(1),
            url=url,
            title=title,
            deal=watch.deal,
            price=int(price) if price else None,
            area_sqm=_to_number(values["area_sqm"]),
            bedrooms=int(bedrooms) if bedrooms else None,
            bathrooms=int(values["bathrooms"]) if values["bathrooms"] else None,
            floor=int(values["floor"]) if values["floor"] else None,
            address=None,
            posted_on=None,
        )
