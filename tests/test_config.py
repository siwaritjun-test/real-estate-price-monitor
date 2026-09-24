from scraper.config import RoomType, Watch, load_watchlist
from scraper.models import Listing


def listing(**kw):
    base = dict(source="ddproperty", listing_id="1", url="u", title="IDEO MOBI Sukhumvit Eastgate, Bangkok")
    return Listing(**{**base, **kw})


def test_name_match_ignores_case_and_punctuation():
    watch = Watch(id="w", project="p", match=["ideo-mobi  sukhumvit eastgate"])
    assert watch.matches_name(listing())


def test_exclude_beats_match():
    watch = Watch(id="w", project="p", match=["Ideo Mobi Sukhumvit"], exclude=["Eastgate"])
    assert not watch.matches_name(listing())


def test_sibling_tower_is_not_a_match():
    watch = Watch(id="w", project="p", match=["Ideo Mobi Sukhumvit Eastgate"])
    assert not watch.matches_name(listing(title="IDEO MOBI Sukhumvit 81, Bangkok"))


def test_room_type_requires_every_populated_field():
    room = RoomType(bedrooms=1, min_sqm=20, max_sqm=40)
    assert room.matches(listing(bedrooms=1, area_sqm=30.0))
    assert not room.matches(listing(bedrooms=2, area_sqm=30.0))
    assert not room.matches(listing(bedrooms=1, area_sqm=55.0))


def test_room_type_rejects_unknown_area_when_bounded():
    assert not RoomType(min_sqm=20).matches(listing(area_sqm=None))
    assert RoomType(bedrooms=1).matches(listing(bedrooms=1, area_sqm=None))


def test_shipped_watchlist_parses():
    watches = load_watchlist("config/watchlist.yml")
    assert watches
    assert "hipflat" not in watches[0].enabled_sources()


def test_shipped_watchlist_keeps_every_unit_but_alerts_on_one_bed():
    from scraper.config import load_watchlist
    watch = load_watchlist("config/watchlist.yml")[0]
    assert watch.room_type.matches(listing(bedrooms=2, area_sqm=60.0))
    assert watch.alerts.covers(listing(bedrooms=1, area_sqm=30.0))
    assert not watch.alerts.covers(listing(bedrooms=2, area_sqm=60.0))
