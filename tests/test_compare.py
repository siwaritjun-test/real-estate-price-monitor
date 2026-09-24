from scraper.compare import append_trend, days_ago, past_medians, point_near, price_on, unit_moves


def test_price_on_replays_the_change_log():
    row = {"first_seen": "2026-09-01", "first_price": 3_000_000, "price": 2_700_000,
           "price_changes": [{"date": "2026-09-10", "from": 3_000_000, "to": 2_850_000},
                             {"date": "2026-09-20", "from": 2_850_000, "to": 2_700_000}]}
    assert price_on(row, "2026-08-31") is None, "not listed yet"
    assert price_on(row, "2026-09-05") == 3_000_000
    assert price_on(row, "2026-09-10") == 2_850_000
    assert price_on(row, "2026-09-24") == 2_700_000


def test_unit_moves_ignores_units_that_were_not_listed_then():
    rows = [
        {"first_seen": "2026-08-01", "first_price": 2_000_000, "price": 1_900_000,
         "price_changes": [{"date": "2026-09-15", "to": 1_900_000}]},
        {"first_seen": "2026-08-01", "first_price": 3_000_000, "price": 3_000_000, "price_changes": []},
        {"first_seen": "2026-09-20", "first_price": 9_000_000, "price": 9_000_000, "price_changes": []},
    ]
    moves = unit_moves(rows, "2026-09-01")
    assert moves == {"units": 2, "cut": 1, "raised": 0, "median_pct": -2.5, "mean_pct": -2.5}
    assert unit_moves(rows, "2026-07-01") is None


def test_point_near_respects_tolerance():
    points = [{"date": "2026-08-20"}, {"date": "2026-08-27"}]
    assert point_near(points, "2026-08-25", 5)["date"] == "2026-08-27"
    assert point_near(points, "2026-08-10", 5) is None


def test_past_medians_by_period_and_room():
    points = [
        {"date": "2026-08-25", "median_ppsqm": 100_000, "by_room": {"1br": {"median_ppsqm": 95_000}}},
        {"date": "2026-09-23", "median_ppsqm": 104_000, "by_room": {}},
        {"date": "2026-09-24", "median_ppsqm": 105_000, "by_room": {}},
    ]
    past = past_medians(points, "2026-09-24")
    assert past["1"] == {"all": 104_000}
    assert past["30"] == {"all": 100_000, "1br": 95_000}
    assert "7" not in past and "365" not in past
    assert days_ago("2026-09-24", 30) == "2026-08-25"


def test_append_trend_pads_new_keys_and_replaces_same_day():
    t = append_trend({}, "2026-09-23", {"all|all": 100})
    t = append_trend(t, "2026-09-24", {"all|all": 101, "Bang Na|all": 90})
    assert t["dates"] == ["2026-09-23", "2026-09-24"]
    assert t["series"]["Bang Na|all"] == [None, 90]
    t = append_trend(t, "2026-09-24", {"all|all": 102})
    assert t["series"]["all|all"] == [100, 102]
    assert t["series"]["Bang Na|all"] == [None, None]
