from scraper.alerts import detect, format_markdown
from scraper.config import AlertRules, RoomType, Watch
from scraper.models import Listing

WATCH = Watch(
    id="w",
    project="Ideo Mobi Sukhumvit Eastgate",
    match=["Ideo Mobi Sukhumvit Eastgate"],
    room_type=RoomType(bedrooms=1),
    alerts=AlertRules(min_drop_pct=1.0, min_drop_thb=20_000),
)


def unit(price, key_id="1"):
    return Listing("ddproperty", key_id, f"https://x/{key_id}", "Eastgate", price=price, area_sqm=22.0)


def previous(price, key_id="1"):
    return {f"ddproperty:{key_id}": {"key": f"ddproperty:{key_id}", "price": price, "source": "ddproperty"}}


def test_first_run_does_not_fire_a_flood_of_new_listing_alerts():
    alerts = detect(WATCH, {}, [unit(2_000_000)], run_date="2026-09-23", bootstrap=True)
    assert alerts == []


def test_new_listing_fires_after_bootstrap():
    alerts = detect(WATCH, previous(2_000_000, "9"), [unit(2_000_000, "1")], run_date="2026-09-23", bootstrap=False)
    assert [a["type"] for a in alerts] == ["new_listing"]


def test_price_drop_must_clear_both_thresholds():
    # 10,000 off 2,000,000 is 0.5% and below the baht floor -- no alert.
    assert detect(WATCH, previous(2_000_000), [unit(1_990_000)], run_date="d", bootstrap=False) == []
    # 1,000,000 off 50,000,000 is 2% but... clears baht floor and pct floor.
    alerts = detect(WATCH, previous(2_100_000), [unit(2_000_000)], run_date="d", bootstrap=False)
    assert len(alerts) == 1
    assert alerts[0]["type"] == "price_drop"
    assert alerts[0]["drop"] == 100_000
    assert alerts[0]["drop_pct"] == 4.76


def test_price_rise_is_not_an_alert():
    assert detect(WATCH, previous(2_000_000), [unit(2_500_000)], run_date="d", bootstrap=False) == []


def test_drops_sort_before_new_listings_and_by_size():
    prev = {**previous(3_000_000, "a"), **previous(5_000_000, "b")}
    listings = [unit(2_900_000, "a"), unit(4_000_000, "b"), unit(1_000_000, "c")]
    alerts = detect(WATCH, prev, listings, run_date="d", bootstrap=False)
    assert [a["type"] for a in alerts] == ["price_drop", "price_drop", "new_listing"]
    assert alerts[0]["drop"] == 1_000_000


def test_alerts_can_be_switched_off():
    watch = Watch(id="w", project="p", match=["Eastgate"], alerts=AlertRules(alert_price_drop=False))
    assert detect(watch, previous(3_000_000), [unit(2_000_000)], run_date="d", bootstrap=False) == []


def test_markdown_renders_both_sections():
    prev = previous(3_000_000, "a")
    alerts = detect(WATCH, prev, [unit(2_500_000, "a"), unit(1_900_000, "z")], run_date="d", bootstrap=False)
    body = format_markdown(alerts)
    assert "Price drops (1)" in body
    assert "New listings (1)" in body
    assert "฿3,000,000" in body


def test_markdown_handles_no_alerts():
    assert format_markdown([]) == "No new alerts."


def test_alert_room_type_limits_alerts_but_not_collection():
    watch = Watch(
        id="w", project="p", match=["Eastgate"],
        alerts=AlertRules(room_type=RoomType(bedrooms=1, max_sqm=40)),
    )
    one_bed = Listing("ddproperty", "1", "u1", "Eastgate", price=2_000_000, area_sqm=22.0, bedrooms=1)
    two_bed = Listing("ddproperty", "2", "u2", "Eastgate", price=4_000_000, area_sqm=45.0, bedrooms=2)
    alerts = detect(watch, previous(1, "old"), [one_bed, two_bed], run_date="d", bootstrap=False)
    assert [a["listing_id"] for a in alerts] == ["1"]
    assert alerts[0]["room"] == "1br"
    assert alerts[0]["room_type"] == "1 bed, 22 sqm"
