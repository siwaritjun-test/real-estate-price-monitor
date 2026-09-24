from pathlib import Path

import pytest

from scraper.config import Watch
from scraper.http import FetchError
from scraper.sources.ddproperty import DDProperty, _page_data
from scraper.sources.hipflat import Hipflat
from scraper.sources.livinginsider import LivingInsider

FIXTURES = Path(__file__).parent / "fixtures"
WATCH = Watch(id="w", project="Ideo Mobi Sukhumvit Eastgate", match=["Ideo Mobi Sukhumvit Eastgate"])


def fixture(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


class FakeFetcher:
    """Serves canned pages and records the order they were requested in."""

    def __init__(self, pages: dict[str, str], fail: set[str] | None = None):
        self.pages = pages
        self.fail = fail or set()
        self.requested: list[str] = []

    def get(self, url: str) -> str:
        self.requested.append(url)
        if url in self.fail:
            raise FetchError(f"HTTP 401 for {url}")
        if url not in self.pages:
            raise FetchError(f"HTTP 404 for {url}")
        return self.pages[url]


# -- DDproperty --------------------------------------------------------------

def test_ddproperty_parses_structured_payload():
    data = _page_data(fixture("ddproperty_search.html"))
    listings = DDProperty()._parse_listings(data, WATCH)
    assert len(listings) == 2, "the deleted listing must be dropped"

    priced = listings[0]
    assert priced.price == 2_790_000
    assert priced.area_sqm == 26.0
    assert priced.bedrooms == 1
    assert priced.price_per_sqm == 107_308
    assert priced.posted_on == "2026-09-23"


def test_ddproperty_normalises_studio_and_price_on_ask():
    data = _page_data(fixture("ddproperty_search.html"))
    studio = DDProperty()._parse_listings(data, WATCH)[1]
    assert studio.bedrooms == 0, "-1 bedrooms means studio"
    assert studio.bathrooms is None
    assert studio.price is None, "'price on ask' must not become 0"
    assert studio.area_sqm == 1250.0, "thousands separators must parse"


def test_ddproperty_paginates_using_the_sites_own_pagination_block():
    url = "https://www.ddproperty.com/en/property-for-sale?freetext=Ideo+Mobi+Sukhumvit+Eastgate"
    page2 = "https://www.ddproperty.com/en/property-for-sale/2?freetext=Ideo+Mobi+Sukhumvit+Eastgate"
    fetcher = FakeFetcher({url: fixture("ddproperty_search.html"), page2: fixture("ddproperty_search.html")})
    result = DDProperty().collect(WATCH, {"url": url, "max_pages": 5}, fetcher)
    assert fetcher.requested == [url, page2]
    assert result.pages_fetched == 2
    assert len(result.listings) == 2, "page 2 repeats page 1, so nothing new is added"


def test_ddproperty_rejects_a_search_url_that_is_not_filtering():
    html = fixture("ddproperty_search.html").replace('"totalPages": 2', '"totalPages": 3266')
    fetcher = FakeFetcher({"u": html})
    result = DDProperty().collect(WATCH, {"url": "u"}, fetcher)
    assert result.status == "error"
    assert "too broad" in result.detail


def test_ddproperty_reports_a_blocked_fetch_rather_than_raising():
    fetcher = FakeFetcher({}, fail={"u"})
    result = DDProperty().collect(WATCH, {"url": "u"}, fetcher)
    assert result.status == "error"
    assert result.listings == []


# -- Livinginsider -----------------------------------------------------------

def test_livinginsider_ignores_the_sitewide_counter_above_the_spec_block():
    """Regression: 'For sale : 64,498' once won over 'FOR SELL : 2,790,000'."""
    listing = LivingInsider()._parse_detail(
        fixture("livinginsider_detail.html"),
        "https://www.livinginsider.com/en/detail/condo-for-sale-condo-x-1bedroom-1739914",
        WATCH,
    )
    assert listing.price == 2_790_000
    assert listing.area_sqm == 26.0
    assert listing.bedrooms == 1
    assert listing.floor == 23, "'No of floors : 25' must not win over 'Floor : 23'"
    assert listing.listing_id == "1739914"
    assert listing.title.endswith("CX-173361")


def test_livinginsider_dedupes_thai_and_english_urls_for_one_unit():
    urls = LivingInsider()._detail_urls(fixture("livinginsider_project.html"))
    assert len(urls) == 2
    assert all("/en/detail/" in u for u in urls), "the English page is preferred"


def test_livinginsider_collect_walks_project_then_details():
    project = "https://www.livinginsider.com/en/project/p"
    detail = "https://www.livinginsider.com/en/detail/condo-for-sale-condo-ideo-mobi-sukhumvit-eastgate-1bedroom-1739914"
    detail2 = "https://www.livinginsider.com/en/detail/condo-for-sale-condo-ideo-mobi-sukhumvit-eastgate-2bedroom-2014686"
    fetcher = FakeFetcher({
        project: fixture("livinginsider_project.html"),
        detail: fixture("livinginsider_detail.html"),
        detail2: fixture("livinginsider_detail.html"),
    })
    result = LivingInsider().collect(WATCH, {"url": project}, fetcher)
    assert result.status == "ok"
    assert len(result.listings) == 2


def test_livinginsider_respects_max_listings():
    project = "https://www.livinginsider.com/en/project/p"
    detail = "https://www.livinginsider.com/en/detail/condo-for-sale-condo-ideo-mobi-sukhumvit-eastgate-1bedroom-1739914"
    fetcher = FakeFetcher({project: fixture("livinginsider_project.html"), detail: fixture("livinginsider_detail.html")})
    result = LivingInsider().collect(WATCH, {"url": project, "max_listings": 1}, fetcher)
    assert len(result.listings) == 1
    assert "capped at max_listings=1" in result.detail


def test_livinginsider_survives_one_bad_detail_page():
    project = "https://www.livinginsider.com/en/project/p"
    good = "https://www.livinginsider.com/en/detail/condo-for-sale-condo-ideo-mobi-sukhumvit-eastgate-1bedroom-1739914"
    bad = "https://www.livinginsider.com/en/detail/condo-for-sale-condo-ideo-mobi-sukhumvit-eastgate-2bedroom-2014686"
    fetcher = FakeFetcher({project: fixture("livinginsider_project.html"), good: fixture("livinginsider_detail.html")},
                          fail={bad})
    result = LivingInsider().collect(WATCH, {"url": project}, fetcher)
    assert result.status == "ok"
    assert len(result.listings) == 1
    assert "1 detail page(s) failed" in result.detail


# -- Hipflat -----------------------------------------------------------------

def test_hipflat_reports_blocked_with_a_reason():
    fetcher = FakeFetcher({}, fail={"u"})
    result = Hipflat().collect(WATCH, {"url": "u"}, fetcher)
    assert result.status == "blocked"
    assert "401" in result.detail


@pytest.mark.parametrize("source_cls", [DDProperty, LivingInsider, Hipflat])
def test_every_source_skips_cleanly_without_a_url(source_cls):
    result = source_cls().collect(WATCH, {}, FakeFetcher({}))
    assert result.status == "skipped"
    assert result.listings == []


def test_livinginsider_reads_the_newer_property_information_layout():
    """Studio pages use a label-per-line layout with no 'Listing ID' block."""
    listing = LivingInsider()._parse_detail(
        fixture("livinginsider_detail_v2.html"),
        "https://www.livinginsider.com/en/detail/condo-for-sale-condo-ideo-mobi-sukhumvit-eastgate-studio-3208179",
        WATCH,
    )
    assert listing.price == 2_400_000
    assert listing.area_sqm == 22.0
    assert listing.bedrooms == 0, "'Studio Room' means studio"
    assert listing.bathrooms == 1
    assert listing.floor is None, "'11-20' is a band, not a floor"
