import json

from scraper import universe
from scraper.universe import crawl

from test_sources import FakeFetcher

BASE = "https://www.ddproperty.com"
QUERY = "?regionCode=TH10&sort=date&order=asc"
FIRST = f"{BASE}/en/condo-for-sale{QUERY}"


def card(listing_id, project_id, project, price, sqm, beds, district="Phaya Thai"):
    return {"listingData": {
        "id": listing_id, "statusCode": "ACT",
        "property": {"id": project_id},
        "localizedTitle": f"{project}, bangkok",
        "shortAddress": f"Samsen Nai, {district}, Bangkok",
        "url": f"{BASE}/en/property/x-{listing_id}",
        "price": {"value": price},
        "area": {"localeStringValue": f"{sqm} sqm"},
        "bedrooms": beds,
    }}


def page(cards, current, total):
    data = {"props": {"pageProps": {"pageData": {"data": {
        "listingsData": cards,
        "paginationData": {"currentPage": current, "totalPages": total, "baseUrl": BASE,
                           "folder": "/en/condo-for-sale", "queryString": QUERY},
    }}}}}
    return f'<script id="__NEXT_DATA__" type="application/json">{json.dumps(data)}</script>'


def url(n):
    return f"{BASE}/en/condo-for-sale/{n}{QUERY}"


def test_crawl_groups_listings_by_project_and_district():
    fetcher = FakeFetcher({
        FIRST: page([card(1, 10, "Via Ari", 5_000_000, 40, 1), card(2, 20, "Noble Ploenchit", 9_000_000, 50, 1,
                                                                      district="Pathum Wan")], 1, 2),
        url(2): page([card(3, 10, "Via Ari", 7_000_000, 60, 2), card(4, None, "No project", 3_000_000, 30, 1)], 2, 2),
    })
    projects, stats = crawl(fetcher, FIRST)
    assert set(projects) == {"10", "20"}
    assert projects["10"].name == "Via Ari"
    assert projects["10"].district == "Phaya Thai"
    assert len(projects["10"].listings) == 2
    assert projects["20"].district == "Pathum Wan"
    assert stats.no_project == 1
    assert stats.coverage == 1.0


def test_crawl_stops_when_the_site_repeats_its_last_page():
    last = page([card(2, 10, "Via Ari", 5_000_000, 40, 1)], 2, 5)
    fetcher = FakeFetcher({
        FIRST: page([card(1, 10, "Via Ari", 5_000_000, 40, 1)], 1, 5),
        url(2): last,
        url(3): last.replace('"currentPage": 2', '"currentPage": 2'),
    })
    projects, stats = crawl(fetcher, FIRST)
    assert url(4) not in fetcher.requested
    assert stats.pages_fetched == 2
    assert stats.coverage == 1.0


def test_partial_crawl_writes_nothing(tmp_path, monkeypatch):
    fetcher = FakeFetcher(
        {FIRST: page([card(1, 10, "Via Ari", 5_000_000, 40, 1)], 1, 10)},
        fail={url(n) for n in range(2, 11)},
    )
    monkeypatch.setattr(universe, "Fetcher", lambda: fetcher)
    code = universe.run(FIRST, tmp_path, tmp_path / "none.yml", None, False)
    assert code == 2
    assert not (tmp_path / "universe").exists()


def test_run_writes_project_files_and_index(tmp_path, monkeypatch):
    fetcher = FakeFetcher({
        FIRST: page([card(1, 10, "Ideo Mobi Sukhumvit Eastgate", 2_000_000, 22, 1),
                     card(2, 10, "Ideo Mobi Sukhumvit Eastgate", 2_600_000, 30, 1),
                     card(3, 20, "Via Ari", 9_000_000, 60, 2)], 1, 1),
    })
    monkeypatch.setattr(universe, "Fetcher", lambda: fetcher)
    assert universe.run(FIRST, tmp_path, "config/watchlist.yml", None, False) == 0

    index = json.loads((tmp_path / "universe" / "index.json").read_text(encoding="utf-8"))
    by_id = {p["id"]: p for p in index["projects"]}
    assert by_id["dd-10"]["listings"] == 2
    assert by_id["dd-10"]["pinned_as"] == "ideo-mobi-sukhumvit-eastgate"
    assert by_id["dd-20"]["pinned_as"] is None
    assert by_id["dd-20"]["by_room"]["2br"]["listings"] == 1
    assert index["districts"]["Phaya Thai"]["projects"] == 2
    assert index["overall"]["listings"] == 3

    snap = json.loads((tmp_path / "universe" / "snapshots" / "dd-10.json").read_text(encoding="utf-8"))
    row = snap["listings"][0]
    assert row["room"] == "1br" and row["price_per_sqm"] and row["first_seen"]
    assert "title" not in row and "last_seen" not in row
    hist = json.loads((tmp_path / "universe" / "history" / "dd-10.json").read_text(encoding="utf-8"))
    assert hist["points"][0]["by_room"]["1br"]["listings"] == 2
