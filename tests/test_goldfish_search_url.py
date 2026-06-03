from scrape_goldfish_two_phase import build_search_url


def test_search_url_uses_period_end_in_url():
    url = build_search_url("2026-05-18", "2026-06-03")
    assert "05/18/2026" in url
    assert "06/03/2026" in url
    assert "+-+" in url


def test_search_url_formats_dates_as_us():
    url = build_search_url("2026-01-05", "2026-01-15")
    assert "01/05/2026" in url
    assert "01/15/2026" in url


def test_search_url_single_day_window():
    url = build_search_url("2026-05-18", "2026-05-18")
    assert "05/18/2026+-+05/18/2026" in url
