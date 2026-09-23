from krt_12_preview import LOTS, _row

def test_twelve_comparison_lots_are_exactly_the_requested_set():
    assert [x["lot"] for x in LOTS] == [2, 6, 10, 11, 12, 14, 16, 18, 21, 28, 31, 42]

def test_partial_source_never_invents_full_rating():
    row = _row(next(x for x in LOTS if x["lot"] == 21))
    assert row["price_score"] is not None
    assert row["coverage_pct"] == 25
    assert row["rating"] is None

def test_missing_market_price_stays_missing():
    row = _row(next(x for x in LOTS if x["lot"] == 42))
    assert row["price_score"] is None
    assert row["coverage_pct"] == 0
    assert row["rating"] is None

def test_acquisition_is_start_plus_seizure():
    row = _row(next(x for x in LOTS if x["lot"] == 2))
    assert row["acquisition_mln"] == 3858.36
