"""DDproperty adapter.

Search result pages embed the full result set as JSON in the Next.js
``__NEXT_DATA__`` script tag, so there is no HTML scraping and no fragile CSS
selector here -- we read the same structured objects the page renders from.
"""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from ..config import Watch
from ..http import Fetcher, FetchError
from ..models import Listing
from .base import Source, SourceResult

log = logging.getLogger(__name__)

NEXT_DATA_RE = re.compile(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', re.S)
AREA_RE = re.compile(r"([\d,.]+)\s*sqm", re.I)


def _extract_next_data(html: str) -> dict[str, Any]:
    match = NEXT_DATA_RE.search(html)
    if not match:
        raise FetchError("no __NEXT_DATA__ payload -- page layout changed or request was blocked")
    return json.loads(match.group(1))


def _page_data(html: str) -> dict[str, Any]:
    payload = _extract_next_data(html)
    return payload.get("props", {}).get("pageProps", {}).get("pageData", {}).get("data", {})


def _parse_area(value: Any) -> float | None:
    if not isinstance(value, dict):
        return None
    match = AREA_RE.search(value.get("localeStringValue") or "")
    if not match:
        return None
    try:
        return float(match.group(1).replace(",", ""))
    except ValueError:
        return None


def _parse_posted(value: Any) -> str | None:
    if not isinstance(value, dict):
        return None
    unix = value.get("unix")
    if isinstance(unix, (int, float)) and unix > 0:
        return datetime.fromtimestamp(unix, tz=timezone.utc).date().isoformat()
    return value.get("text") or None


def _page_url(pagination: dict[str, Any], page: int) -> str | None:
    """Build page N's URL from the pagination block the site itself publishes."""
    base = pagination.get("baseUrl")
    folder = pagination.get("folder")
    query = pagination.get("queryString") or ""
    if not base or not folder:
        return None
    return f"{base}{folder}/{page}{query}"


def _fallback_page_url(url: str, page: int) -> str:
    """Insert /N before the query string, DDproperty's pagination convention."""
    parts = urlsplit(url)
    path = parts.path.rstrip("/")
    path = re.sub(r"/\d+$", "", path)
    return urlunsplit((parts.scheme, parts.netloc, f"{path}/{page}", parts.query, ""))


class DDProperty(Source):
    name = "ddproperty"

    def collect(self, watch: Watch, options: dict[str, Any], fetcher: Fetcher) -> SourceResult:
        url = options.get("url")
        result = SourceResult(source=self.name)
        if not url:
            result.status = "skipped"
            result.detail = "no 'url' configured for this source"
            return result

        max_pages = int(options.get("max_pages", 5))
        seen: set[str] = set()

        try:
            html = fetcher.get(url)
            data = _page_data(html)
        except (FetchError, json.JSONDecodeError) as exc:
            result.status = "error"
            result.detail = str(exc)
            return result

        result.pages_fetched = 1
        for listing in self._parse_listings(data, watch):
            if listing.key not in seen:
                seen.add(listing.key)
                result.listings.append(listing)

        pagination = data.get("paginationData") or {}
        total_pages = int(pagination.get("totalPages") or 1)
        # A freetext search that matched nothing falls back to "everything in the
        # region", which is thousands of pages. Treat that as a bad search URL.
        if total_pages > 200:
            result.status = "error"
            result.detail = (
                f"search URL is too broad ({total_pages} pages) -- it is probably not "
                "filtering by project; check the 'url' in the watchlist"
            )
            return result

        for page in range(2, min(max_pages, total_pages) + 1):
            page_url = _page_url(pagination, page) or _fallback_page_url(url, page)
            try:
                page_data = _page_data(fetcher.get(page_url))
            except (FetchError, json.JSONDecodeError) as exc:
                log.warning("ddproperty page %d failed: %s", page, exc)
                result.detail = f"stopped at page {page}: {exc}"
                break
            result.pages_fetched += 1
            new_on_page = 0
            for listing in self._parse_listings(page_data, watch):
                if listing.key not in seen:
                    seen.add(listing.key)
                    result.listings.append(listing)
                    new_on_page += 1
            if new_on_page == 0:
                break

        return result

    def _parse_listings(self, data: dict[str, Any], watch: Watch) -> list[Listing]:
        listings = (parse_card(card, watch.deal) for card in data.get("listingsData") or [])
        return [listing for listing in listings if listing is not None]


def project_of(card: dict[str, Any]) -> tuple[str | None, str, str | None]:
    """(project id, project name, district) for one search-result card."""
    item = card.get("listingData") or {}
    project_id = (item.get("property") or {}).get("id")
    # Titles read "<Project name>, bangkok"; the city suffix is not part of the name.
    name = re.sub(r",\s*[^,]*$", "", item.get("localizedTitle") or "").strip()
    # "Samsen Nai, Phaya Thai, Bangkok" -> "Phaya Thai"
    parts = [p.strip() for p in (item.get("shortAddress") or "").split(",") if p.strip()]
    district = parts[-2] if len(parts) >= 2 else None
    return (str(project_id) if project_id else None), name, district


def parse_card(card: dict[str, Any], deal: str) -> Listing | None:
    """Turn one search-result card into a Listing, or None for non-listings."""
    item = card.get("listingData") or {}
    listing_id = item.get("id")
    if listing_id is None:
        return None
    if item.get("statusCode") not in (None, "ACT"):
        return None

    # DDproperty encodes "studio" as -1 bedrooms; normalise it to 0.
    bedrooms = item.get("bedrooms")
    bedrooms = max(bedrooms, 0) if isinstance(bedrooms, int) else None
    bathrooms = item.get("bathrooms")
    bathrooms = bathrooms if isinstance(bathrooms, int) and bathrooms >= 0 else None

    price_block = item.get("price") or {}
    price = price_block.get("value")
    price = int(price) if isinstance(price, (int, float)) and price > 0 else None

    return Listing(
        source="ddproperty",
        listing_id=str(listing_id),
        url=item.get("url") or "",
        title=item.get("localizedTitle") or "",
        deal=deal,
        price=price,
        area_sqm=_parse_area(item.get("area")),
        bedrooms=bedrooms,
        bathrooms=bathrooms,
        address=item.get("fullAddress") or item.get("shortAddress"),
        posted_on=_parse_posted(item.get("postedOn")),
    )
