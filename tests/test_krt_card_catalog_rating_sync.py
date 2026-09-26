"""The KRT card and catalogue must use the same canonical rating.

A card used to start at a hard-coded 600k target. If the shared catalogue
target had been changed, the server correctly treated that card calculation
as a private scenario and did not persist it. The user then saw a rating in
the card and a dash in the catalogue.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from auction_search.krt_investment_card import krt_investment_card_page  # noqa: E402
from auction_search.ui import auctions_page  # noqa: E402


def _fn(page: str, name: str) -> str:
    start = page.index(f"function {name}(")
    depth = 0
    at = page.index("{", start)
    for index in range(at, len(page)):
        if page[index] == "{":
            depth += 1
        elif page[index] == "}":
            depth -= 1
            if depth == 0:
                return page[start:index + 1]
    raise AssertionError(name)


def test_initial_card_rating_uses_the_catalogue_target() -> None:
    page = krt_investment_card_page("decision:1")
    boot = _fn(page, "boot")
    url = _fn(page, "ratingUrl")

    assert "if(!useInput)return base" in url
    assert "get(ratingUrl(false))" in boot
    assert "canonical_target_rub_sqm" in page
    assert "syncCanonicalTarget(scorePayload)" in boot


def test_manual_card_scenario_still_uses_the_input() -> None:
    page = krt_investment_card_page("decision:1")
    recalc = _fn(page, "recalcRating")
    assert "get(ratingUrl(true))" in recalc


def test_closing_the_card_refreshes_the_catalogue_rating() -> None:
    page = auctions_page()
    close = _fn(page, "closeKrtPrototype")
    assert "loadKrtRanking()" in close
