"""Карточка КРТ не показывает просроченный лот как «Идёт аукцион».

У карточки была своя копия правила: она проверяла поле `moment`, которого
сервер не отдаёт, и считала живым любой запомненный лот — лот со сроком
1 сентября светился «Идёт аукцион — вход открыт». Правило теперь одно
(`krt_tenders.LIVE_LOT_SCRIPT`); здесь исполняется код, который реально стоит в
отрисованных страницах карточки и каталога.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess

import pytest

from auction_search.krt_investment_card import krt_investment_card_page
from auction_search.ui import auctions_page

NODE = shutil.which("node")
NOW = 1_790_000_000_000  # 2026-09-21, мс
LOTS = {
    "expired": [{"deadline": "01.09.2026", "deadline_iso": "2026-09-01T18:00:00+03:00"}],
    "live": [{"deadline": "01.10.2026", "deadline_iso": "2026-10-01T18:00:00+03:00"}],
    "unparsed": [{"deadline": "в течение месяца", "deadline_iso": ""}],
    "no_deadline": [{"number": "1"}],
}


def _function(page: str, name: str) -> str:
    start = page.index(f"function {name}(")
    depth = 0
    for index in range(page.index("{", start), len(page)):
        depth += {"{": 1, "}": -1}.get(page[index], 0)
        if depth == 0:
            return page[start:index + 1]
    raise AssertionError(name)


def _run(code: str) -> dict:
    out = subprocess.run([NODE, "-e", code], capture_output=True, text=True, timeout=30)
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout)


@pytest.mark.skipif(NODE is None, reason="node не установлен")
def test_the_card_and_the_catalogue_answer_the_same():
    card = krt_investment_card_page("x")
    catalogue = auctions_page()
    # Правило вставлено в обе страницы, а не переписано в каждой.
    assert _function(card, "liveTenderLot") == _function(catalogue, "liveTenderLot")
    assert not re.search(r"x\.moment|\.ended", _function(card, "activeTender"))

    realNow = f"const RealDate=Date;Date.now=()=>{NOW};"
    answers = _run(
        realNow
        + _function(card, "liveTenderLot")
        + _function(card, "activeTender")
        + f"const lots={json.dumps(LOTS)};const out={{}};"
        + "for(const k in lots)out[k]=!!activeTender({tender_lots:lots[k]});"
        + "console.log(JSON.stringify(out));"
    )
    assert answers == {"expired": False, "live": True, "unparsed": True,
                       "no_deadline": False}


@pytest.mark.skipif(NODE is None, reason="node не установлен")
def test_a_source_link_opens_only_over_http():
    card = krt_investment_card_page("x")
    start = card.index("const safeUrl=")
    code = card[start:card.index("\n", start)]
    answers = _run(code + "console.log(JSON.stringify(["
                   "safeUrl('javascript:alert(1)'),safeUrl(' JavaScript:x'),"
                   "safeUrl('https://torgi.gov.ru/lot/1'),safeUrl(null)]))")
    assert answers == ["#", "#", "https://torgi.gov.ru/lot/1", "#"]
    assert "href=\"'+esc(x.url)" not in card and "href=\"'+esc(live.url)" not in card
