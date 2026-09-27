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


def _listener(page: str) -> str:
    start = page.index("window.addEventListener('message',e=>{")
    depth = 0
    at = page.index("(", start)
    for index in range(at, len(page)):
        depth += {"(": 1, ")": -1}.get(page[index], 0)
        if depth == 0:
            return page[start:index + 1]
    raise AssertionError("listener")


def test_a_scenario_rating_does_not_reach_the_catalogue() -> None:
    """Сценарий карточки с другим ориентиром не подменяет цифру в таблице.

    Исполняется настоящий обработчик сообщений со страницы каталога.
    """
    import json
    import shutil
    import subprocess

    node = shutil.which("node")
    if node is None:
        import pytest
        pytest.skip("node не установлен")
    code = (
        "let handler;const location={origin:'https://x'};"
        "const window={addEventListener:(k,f)=>{handler=f}};"
        "const state={krtRank:{a:{slug:'a',investment_rating:{score:50}}}};"
        "let rendered=0;const renderKrt=()=>{rendered++};"
        + _listener(auctions_page()) + ";"
        "handler({origin:'https://x',data:{type:'developaid-krt-rating',slug:'a',rating:{score:90}}});"
        "const afterScenario=state.krtRank.a.investment_rating.score;"
        "handler({origin:'https://x',data:{type:'developaid-krt-rating',slug:'a',canonical:true,rating:{score:70}}});"
        "console.log(JSON.stringify([afterScenario,state.krtRank.a.investment_rating.score,rendered]));"
    )
    out = subprocess.run([node, "-e", code], capture_output=True, text=True, timeout=30)
    assert out.returncode == 0, out.stderr
    assert json.loads(out.stdout) == [50, 70, 1]

    card = krt_investment_card_page("decision:1")
    assert "if(canonical===true&&window.parent" in _fn(card, "renderScore")


def test_a_rating_at_an_old_target_is_marked() -> None:
    """После смены общего ориентира непересчитанная строка это называет."""
    import json
    import shutil
    import subprocess

    node = shutil.which("node")
    if node is None:
        import pytest
        pytest.skip("node не установлен")
    page = auctions_page()
    code = (
        "const esc=s=>String(s??'');"
        "const state={krtRatingTarget:650000,krtRank:{"
        "a:{investment_rating:{display_score:71,coverage_pct:100},investment_rating_target_rub_sqm:600000},"
        "b:{investment_rating:{display_score:64,coverage_pct:100},investment_rating_target_rub_sqm:650000},"
        "c:{investment_rating:{display_score:58,coverage_pct:75,deferred:[{component:'burden',"
        "reason:'медиана по 1 площадкам'}]},investment_rating_target_rub_sqm:650000}}};"
        + _fn(page, "krtInvestmentRatingCell")
        + ";console.log(JSON.stringify([krtInvestmentRatingCell('a'),krtInvestmentRatingCell('b'),"
        "krtInvestmentRatingCell('c')]))"
    )
    out = subprocess.run([node, "-e", code], capture_output=True, text=True, timeout=30)
    assert out.returncode == 0, out.stderr
    old, fresh, partial = json.loads(out.stdout)
    assert "без составляющей: нагрузка" in partial, "балл по трём из четырёх выдан за полный"
    assert "без составляющей" not in fresh
    assert "ждёт пересчёта" in old and "600" in old
    assert "ждёт пересчёта" not in fresh
