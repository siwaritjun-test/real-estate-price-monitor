import json

from scraper.models import Listing
from scraper.store import Store, summarise


def unit(price, key_id="1", area=22.0):
    return Listing("ddproperty", key_id, f"https://x/{key_id}", "Eastgate", price=price, area_sqm=area)


def test_merge_keeps_first_seen_and_records_the_change(tmp_path):
    store = Store(tmp_path)
    first = store.merge({}, [unit(3_000_000)], run_date="2026-09-01")
    assert first["ddproperty:1"]["first_seen"] == "2026-09-01"
    assert first["ddproperty:1"]["price_changes"] == []

    second = store.merge(first, [unit(2_800_000)], run_date="2026-09-08")
    row = second["ddproperty:1"]
    assert row["first_seen"] == "2026-09-01"
    assert row["last_seen"] == "2026-09-08"
    assert row["first_price"] == 3_000_000
    assert row["previous_price"] == 3_000_000
    assert row["price_changes"] == [{"date": "2026-09-08", "from": 3_000_000, "to": 2_800_000}]


def test_merge_does_not_log_a_change_when_the_price_holds(tmp_path):
    store = Store(tmp_path)
    first = store.merge({}, [unit(3_000_000)], run_date="2026-09-01")
    second = store.merge(first, [unit(3_000_000)], run_date="2026-09-08")
    assert second["ddproperty:1"]["price_changes"] == []


def test_snapshot_round_trips(tmp_path):
    store = Store(tmp_path)
    records = store.merge({}, [unit(3_000_000), unit(2_000_000, "2")], run_date="2026-09-01")
    store.save_snapshot("w", records, {"project": "p"})
    loaded = store.load_records("w")
    assert set(loaded) == {"ddproperty:1", "ddproperty:2"}
    assert loaded["ddproperty:2"]["price"] == 2_000_000


def test_history_replaces_a_same_day_point(tmp_path):
    store = Store(tmp_path)
    store.append_history("w", {"date": "2026-09-01", "listings": 1})
    store.append_history("w", {"date": "2026-09-01", "listings": 5})
    store.append_history("w", {"date": "2026-09-02", "listings": 7})
    points = json.loads(store.history_path("w").read_text(encoding="utf-8"))["points"]
    assert [p["listings"] for p in points] == [5, 7]


def test_summarise_splits_by_source():
    rows = [
        unit(3_000_000, "1").to_dict(),
        unit(2_000_000, "2").to_dict(),
        {**unit(4_000_000, "3").to_dict(), "source": "livinginsider"},
    ]
    point = summarise(rows, "2026-09-01")
    assert point["listings"] == 3
    assert point["median_price"] == 3_000_000
    assert point["min_price"] == 2_000_000
    assert set(point["by_source"]) == {"ddproperty", "livinginsider"}
    assert point["by_source"]["livinginsider"]["median_price"] == 4_000_000


def test_summarise_survives_listings_with_no_price():
    rows = [unit(None, "1").to_dict(), unit(3_000_000, "2").to_dict()]
    point = summarise(rows, "2026-09-01")
    assert point["listings"] == 2
    assert point["priced_listings"] == 1
    assert point["median_price"] == 3_000_000


def test_alerts_log_is_capped_and_newest_first(tmp_path):
    store = Store(tmp_path)
    store.append_alerts([{"type": "new_listing", "n": 1}])
    stored = store.append_alerts([{"type": "price_drop", "n": 2}])
    assert [a["n"] for a in stored] == [2, 1]


def test_summarise_splits_by_room_bucket():
    rows = [
        Listing("ddproperty", "1", "u", "t", price=2_000_000, area_sqm=22.0, bedrooms=1).to_dict(),
        Listing("ddproperty", "2", "u", "t", price=2_400_000, area_sqm=26.0, bedrooms=1).to_dict(),
        Listing("ddproperty", "3", "u", "t", price=4_000_000, area_sqm=45.0, bedrooms=2).to_dict(),
        Listing("ddproperty", "4", "u", "t", price=1_500_000, area_sqm=21.0, bedrooms=0).to_dict(),
    ]
    point = summarise(rows, "2026-09-01")
    assert point["listings"] == 4
    assert list(point["by_room"]) == ["studio", "1br", "2br"]
    assert point["by_room"]["1br"]["listings"] == 2
    assert point["by_room"]["1br"]["median_price"] == 2_200_000
    assert point["by_room"]["2br"]["by_source"]["ddproperty"]["median_price"] == 4_000_000
