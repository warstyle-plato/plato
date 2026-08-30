"""Вопрос Платону в торгах укладывается в предел.

Владелец, 31.08.2026: на странице торгов кнопка «Спросить» отвечала «Вопрос
слишком длинный» на вопрос в две строки. Причина та же, что была у свода
продаж, только в чистом виде: свод торгов собирался ВОВСЕ без бюджета — шапка,
список лотов и выбранная площадка склеивались целиком и уходили на сервер, где
предел 4000 знаков.

Ломается это только на объёме: семнадцать лотов с длинными названиями и
выбранный участок, в описании которого перечислены ЗОУИТ и охранные зоны ЛЭП.
Поэтому здесь настоящий свод страницы гоняется настоящим узлом на таком
состоянии, а не пересказывается.

Запуск: python3 -m pytest tests/test_the_auction_question_fits_the_limit.py -q
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from auction_search.ui import auctions_page  # noqa: E402
from market_search import ask_budget  # noqa: E402

LIMIT = 4000

# Описание того самого лота: Коммунарка, 173 494 м², с перечнем ограничений.
LONG_TITLE = (
    "Земельный участок общей площадью - 173 494 кв. м, адрес: г. Москва, вн.тер.г. "
    "муниципальный округ Коммунарка, квартал 101, земельный участок 2, кадастровый "
    "номер 50:21:0120316:1221, земли населенных пунктов - многофункциональные "
    "общественные центры, ограничения и обременения: ограничения прав на земельный "
    "участок, предусмотренные ст. 56 Земельного Кодекса РФ, ЗОУИТ 77:06.2.2 Охранная "
    "зона ЛЭП 110 кВ «Битца - Ясенево» – на 30 389 м2, ЗОУИТ: 77.00.2.71, 77:00-6.122 "
    "Охранная зона ВЛ 220 кВ Бутово"
)


def _lot(index: int) -> dict:
    return {
        "title": f"{LONG_TITLE} (лот {index})",
        "address": "г. Москва, Коммунарка, квартал 101",
        "lot_kind": "land",
        "land_area_sqm": 173494,
        "current_price_rub": 1_150_000_000,
        "application_deadline": "2026-09-15",
        "documents": [{"name": f"Документ {n}"} for n in range(4)],
        "screening": {
            "why_here": "Участок под многофункциональную застройку рядом с метро.",
            "concerns": [f"Ограничение номер {n}: охранная зона режет пятно застройки"
                         for n in range(6)],
            "verify_before_calculation": [
                f"Проверить до расчёта пункт {n}: сведения ЕГРН и градплан" for n in range(6)],
        },
    }


def _question(count: int = 17) -> str:
    """Вопрос собирается настоящим кодом страницы, а не его пересказом."""
    page = auctions_page()
    body = page[page.index("function askDigest(){"):]
    digest = body[:body.index("\nfunction renderAskContext")]
    lots = [_lot(i) for i in range(count)]
    stub = """
const state={lots:%s, filtered:%s, families:%s, selected:%s,
  krt:[], krtFiltered:[], krtModels:{}, krtRank:{}, selectedKrt:null};
const $=id=>({classList:{contains:()=>true}});
const fmtArea=v=>String(v)+' м²', fmtMoney=v=>String(v)+' ₽';
const shortDate=v=>String(v||''), kindLabel=v=>String(v||'');
const lotRange=(a,b,f)=>f(a)+'–'+f(b);
const lotScore=()=>({score:71, base:100, cut:29, cuts:[{label:'нет цены'},{label:'срок прошёл'}]});
const krtScore=()=>({score:0, base:0, cut:0, cuts:[]});
""" % (json.dumps(lots, ensure_ascii=False), json.dumps(lots, ensure_ascii=False),
       json.dumps([{"lead": lot, "score": {"score": 71, "base": 100, "cut": 29,
                                           "cuts": [{"label": "нет цены"}]},
                    "collapsed": False, "count": 1} for lot in lots], ensure_ascii=False),
       json.dumps(lots[0], ensure_ascii=False))
    # Вступление и сборка берутся из самой страницы: если они там изменятся, а
    # тест продолжит считать по-своему, он подтвердит сам себя.
    ask = page[page.index("async function askPlato(){"):]
    ask = ask[ask.index("const preamble="):]
    preamble = ask[:ask.index(";\n")]
    script = (stub + ask_budget.SCRIPT + "\n" + digest + "\n"
              + "const question=" + json.dumps(
                  "Чем опасна выбранная площадка? Назови три риска по убыванию цены вопроса.",
                  ensure_ascii=False) + ";\n"
              + preamble + ";\n"
              + "const {head, groups}=askDigest();\n"
              + f"const room={LIMIT}-preamble.length-question.length-64;\n"
              + "process.stdout.write(preamble+'\\n\\n'+fitAsk(head,groups,room)"
                "+'\\n\\nВопрос: '+question);\n")
    # Скрипт кладётся файлом, а не аргументом: со семнадцатью длинными лотами
    # он не влезает в командную строку — «Argument list too long».
    import tempfile

    with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False,
                                     encoding="utf-8") as handle:
        handle.write(script)
        path = handle.name
    try:
        done = subprocess.run(["node", path], capture_output=True, text=True)
    finally:
        Path(path).unlink(missing_ok=True)
    assert done.returncode == 0, done.stderr
    return done.stdout


def test_seventeen_long_lots_still_fit() -> None:
    """Ровно тот случай с экрана владельца: семнадцать лотов и выбранный участок."""
    message = _question(17)
    assert len(message) <= LIMIT, f"вопрос {len(message)} знаков при пределе {LIMIT}"
    assert message.rstrip().endswith("цены вопроса."), "вопрос человека обрезан"


def test_the_selected_lot_survives_the_budget() -> None:
    """Спрашивают о выбранном, список — фон. Он и должен уцелеть первым."""
    message = _question(17)
    assert "ВЫБРАН:" in message
    assert "НАСТОРАЖИВАЕТ:" in message


def test_what_did_not_fit_is_named() -> None:
    """Молча выброшенный раздел читается как отсутствие данных."""
    message = _question(17)
    assert "НЕ ПОМЕСТИЛОСЬ В ВОПРОС" in message


def test_the_budget_is_the_shared_one() -> None:
    """Счёт один на обе поверхности: две копии однажды разойдутся."""
    page = auctions_page()
    assert page.count("function fitAsk") == 1
    assert ask_budget.PLACEHOLDER not in page
    source = (ROOT / "auction_search" / "ui.py").read_text()
    assert "NOTE_ROOM" not in source, "бюджет переписан копией в модуле торгов"
