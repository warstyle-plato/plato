"""Балл прежней методики рейтинга КРТ не выдаётся за нынешний.

Фон пересчитывает не всё: площадку «В реализации» он пропускает нарочно, а
ранний сигнал, пропавший из каталога, не видит вовсе. Такие строки жили с
баллом v1/v2 рядом с баллами нынешней методики — или с пустым баллом без
объяснения. Теперь балл пуст, прежний сохранён в `previous_*`, а причина
названа.
"""

from __future__ import annotations

import json
import shutil
import subprocess

import pytest

from auction_search.krt_ranking import rating_by_current_methodology
from auction_search.ui import auctions_page

CURRENT = "issue-485-krt-rating-4x100-v4"
OLD = "issue-485-krt-rating-4x100-v1"
NODE = shutil.which("node")


def _row(slug: str, version: str, status: str = "", score=40) -> dict:
    return {"slug": slug, "status": status, "investment_rating_version": version,
            "investment_rating": {"score": score, "display_score": score, "rankable": True}}


def test_a_current_row_is_untouched() -> None:
    row = _row("a", CURRENT)
    assert rating_by_current_methodology(row, CURRENT, catalogue_slugs={"a"}) is row
    unrated = {"slug": "b"}
    assert rating_by_current_methodology(unrated, CURRENT, catalogue_slugs=set()) is unrated


def test_an_orphan_of_the_catalogue_is_named() -> None:
    marked = rating_by_current_methodology(_row("early:2", OLD), CURRENT,
                                           catalogue_slugs={"a"})
    rating = marked["investment_rating"]
    assert rating["display_score"] is None and rating["score"] is None
    assert rating["stale_methodology"] is True
    assert rating["previous_display_score"] == 40 and rating["previous_version"] == OLD
    assert rating["reason"].startswith("не пересчитано по текущей методике (посчитано v1)")
    assert "нет в нынешнем каталоге" in rating["reason"]


def test_a_running_site_and_a_queued_one_say_why() -> None:
    running = rating_by_current_methodology(
        _row("r", OLD, "В реализации", None), CURRENT, catalogue_slugs={"r"})
    assert "в реализации" in running["investment_rating"]["reason"]
    queued = rating_by_current_methodology(_row("q", OLD), CURRENT, catalogue_slugs={"q"})
    assert "пересчёт в очереди" in queued["investment_rating"]["reason"]


def test_an_incomplete_catalogue_does_not_claim_absence() -> None:
    marked = rating_by_current_methodology(_row("early:2", OLD), CURRENT, catalogue_slugs=None)
    assert "нет в нынешнем каталоге" not in marked["investment_rating"]["reason"]
    assert marked["investment_rating"]["stale_methodology"] is True


@pytest.mark.skipif(NODE is None, reason="node не установлен")
def test_the_catalogue_cell_shows_the_reason_not_the_old_score() -> None:
    page = auctions_page()
    start = page.index("function krtInvestmentRatingCell(")
    depth = 0
    for index in range(page.index("{", start), len(page)):
        depth += {"{": 1, "}": -1}.get(page[index], 0)
        if depth == 0:
            fn = page[start:index + 1]
            break
    rank = rating_by_current_methodology(_row("early:2", OLD), CURRENT, catalogue_slugs=set())
    code = ("const esc=s=>String(s??'');const state={krtRatingTarget:650000,krtRank:"
            + json.dumps({"early:2": rank}) + "};" + fn
            + ";console.log(JSON.stringify(krtInvestmentRatingCell('early:2')))")
    out = subprocess.run([NODE, "-e", code], capture_output=True, text=True, timeout=30)
    assert out.returncode == 0, out.stderr
    cell = json.loads(out.stdout)
    assert "не пересчитано по текущей методике" in cell
    assert "<b>40</b>" not in cell and "ещё не рассчитан" not in cell
