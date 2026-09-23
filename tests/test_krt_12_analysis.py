from auction_search import krt_12_analysis as a
from auction_search import krt_cadastral_selector as s


def test_twelve_lots_are_exactly_the_selected_set():
    assert [x["lot"] for x in a.LOT_DEFS] == [2,6,10,11,12,14,16,18,21,28,31,42]


def test_lot_matching_uses_address_not_pdf_score():
    rows=[
        {"slug":"wrong","name":"Дмитровское шоссе, вл. 160","okrug":"САО"},
        {"slug":"right","name":"КРТ Дмитровское шоссе, владение 60","okrug":"САО"},
    ]
    got=a._match(a.LOT_DEFS[0],rows)
    assert got["slug"] == "right"


def test_nspd_owner_classifier_never_invents_unknown_private():
    assert s._owner_from_options({"ownership_type":"Частная собственность"})["group"] == "private"
    assert s._owner_from_options({"ownership_type":"Собственность города Москвы"})["group"] == "moscow"
    assert s._owner_from_options({"address":"Москва"}) == {}
