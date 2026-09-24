from scraper.models import Listing, normalise


def test_price_per_sqm_needs_both_numbers():
    assert Listing("s", "1", "u", "t", price=2_490_000, area_sqm=22.0).price_per_sqm == 113182
    assert Listing("s", "1", "u", "t", price=2_490_000).price_per_sqm is None
    assert Listing("s", "1", "u", "t", area_sqm=22.0).price_per_sqm is None


def test_implausible_catches_a_page_counter_read_as_a_price():
    assert Listing("s", "1", "u", "t", price=64_498).implausible()
    assert Listing("s", "1", "u", "t", price=2_490_000, area_sqm=22.0).implausible() is None


def test_implausible_catches_absurd_area():
    assert Listing("s", "1", "u", "t", price=2_490_000, area_sqm=0.5).implausible()


def test_normalise_collapses_separators():
    assert normalise("IDEO-MOBI  Sukhumvit_81") == "ideo mobi sukhumvit 81"


def test_room_bucket():
    from scraper.models import room_bucket
    assert [room_bucket(b) for b in (None, 0, 1, 2, 3, 5)] == [
        "unknown", "studio", "1br", "2br", "3br+", "3br+",
    ]


def test_implausible_price_per_sqm_is_rejected():
    from scraper.models import Listing
    typo = Listing("ddproperty", "1", "u", "t", price=4_800_000, area_sqm=532.0)
    assert "plausible" in typo.implausible()
    rent_as_sale = Listing("ddproperty", "2", "u", "t", price=180_000, area_sqm=30.0)
    assert rent_as_sale.implausible()
    fine = Listing("ddproperty", "3", "u", "t", price=4_800_000, area_sqm=53.2)
    assert fine.implausible() is None
