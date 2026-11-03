"""Повторы одного извещения — одна строка, а не тридцать.

ГИС Торги приезжают лотами, а не извещениями: тридцать гаражей одного ГСК
в с. Шеметово — тридцать карточек по 26 м² и 0,2 млн ₽ с одним днём подачи.
На экране владельца (25.08.2026) их было столько, что участок в Коммунарке
за 1,1 млрд ₽ терялся между ними: «68 карточек но очень много повторов».

Схлопывать такое можно только по совпадению ВСЕХ признаков сразу — включая
порядок величины цены и площади. Без него «Аукцион в отношении земельного
участка с КН …» после чистки чисел выглядит одинаково и у лота за 0,1 млн,
и у площадки за миллиард: они слиплись бы в одну строку, и дорогая площадка
уехала бы внутрь группы дешёвых.

И ничто не пропадает: балл группы — балл ЛУЧШЕГО её лота, число лотов стоит
в строке, а под таблицей написано, сколько групп и сколько строк убрано.
Схлопывание, которое молча прячет лот, — это фильтр, которого никто не просил.

Запуск: python3 -m pytest tests/test_repeated_lots_are_one_row.py -q
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from auction_search.ui import auctions_page  # noqa: E402


def script() -> str:
    page = auctions_page()
    return page[page.rindex("<script>") + len("<script>"):page.rindex("</script>")]


def function_source(name: str) -> str:
    body = script()
    start = body.index(f"function {name}(")
    depth = 0
    for position in range(body.index("{", start), len(body)):
        if body[position] == "{":
            depth += 1
        elif body[position] == "}":
            depth -= 1
            if depth == 0:
                return body[start:position + 1]
    raise AssertionError(f"не найдена функция {name}")


def const_line(prefix: str) -> str:
    body = script()
    start = body.index(prefix)
    return body[start:body.index("\n", start)]


FUNCTIONS = ("lotDeadlineDays", "lotScore", "lotScoreNote", "lotFamilySignature",
             "lotMagnitude", "lotFamilyKey", "lotFamilies", "lotRange")


def families(lots: list[dict]) -> list[dict]:
    node = shutil.which("node")
    if not node:
        pytest.skip("node недоступен")
    parts = [const_line("const LOT_BASE_BY_KIND="), const_line("const FAMILY_MIN=")]
    parts += [function_source(name) for name in FUNCTIONS]
    program = "\n".join(parts) + (
        "\nconst out=lotFamilies(" + json.dumps(lots) + ")"
        ".map(f=>({key:f.key,count:f.count,collapsed:f.collapsed,score:f.score.score,"
        "lead:f.lead.title,priceMin:f.priceMin,priceMax:f.priceMax,"
        "areaMin:f.areaMin,areaMax:f.areaMax,docs:f.docs,titles:f.lots.map(l=>l.title)}));"
        "\nconsole.log(JSON.stringify(out));")
    done = subprocess.run([node, "-e", program], capture_output=True, text=True, timeout=60)
    assert done.returncode == 0, done.stderr[:800]
    return json.loads(done.stdout)


def garage(number: int) -> dict:
    return {
        "title": f"Гараж, бокс № {number}, Московская область, Сергиево-Посадский г.о., с. Шеметово",
        "lot_kind": "property_complex",
        "origin": "city",
        "building_area_sqm": 26 + (number % 2),
        "current_price_rub": 200_000 + number * 100,
        "application_deadline": "2099-09-13T09:00:00",
        "cadastral_numbers": [f"50:05:0020503:30{number:02d}"],
        "documents": [],
        "source": {"platform": "torgi_gov", "external_lot_id": f"g{number}"},
        "screening": {"concerns": []},
    }


KOMMUNARKA = {
    "title": "Аукцион в отношении земельного участка с КН 50:21:0120316:1221",
    "lot_kind": "land_sale",
    "origin": "other",
    "land_area_sqm": 173_494,
    "current_price_rub": 1_100_300_000,
    "application_deadline": "2099-09-11T09:00:00",
    "cadastral_numbers": ["50:21:0120316:1221"],
    "documents": [{"title": "извещение"}],
    "source": {"platform": "torgi_gov", "external_lot_id": "k1"},
    "screening": {"concerns": []},
}


def small_land(number: int) -> dict:
    return {
        "title": f"Аукцион в отношении земельного участка с КН 50:34:00201{number:02d}:{number}",
        "lot_kind": "land_sale",
        "origin": "other",
        "current_price_rub": 100_000 + number * 1_000,
        "application_deadline": "2099-09-11T09:00:00",
        "cadastral_numbers": [f"50:34:00201{number:02d}:{number}"],
        "documents": [],
        "source": {"platform": "torgi_gov", "external_lot_id": f"s{number}"},
        "screening": {"concerns": []},
    }


def test_thirty_garages_become_one_row() -> None:
    got = families([garage(n) for n in range(1, 31)])
    assert len(got) == 1
    assert got[0]["count"] == 30
    assert got[0]["collapsed"] is True


def test_the_row_says_how_many_and_from_where_to_where() -> None:
    got = families([garage(n) for n in range(1, 31)])[0]
    assert got["priceMin"] < got["priceMax"]
    assert got["areaMin"] == 26 and got["areaMax"] == 27
    assert len(got["titles"]) == 30, "лоты остаются в группе, а не выбрасываются"


def test_a_billion_never_joins_the_small_ones() -> None:
    """Порядок величины стоит в ключе именно ради этого случая."""
    lots = [small_land(n) for n in range(1, 21)] + [KOMMUNARKA]
    got = families(lots)
    big = [f for f in got if f["lead"] == KOMMUNARKA["title"]]
    assert len(big) == 1
    assert big[0]["count"] == 1 and big[0]["collapsed"] is False


def test_the_good_lot_stands_first() -> None:
    lots = [garage(n) for n in range(1, 31)] + [small_land(n) for n in range(1, 21)] + [KOMMUNARKA]
    got = families(lots)
    assert got[0]["lead"] == KOMMUNARKA["title"]
    assert len(got) < 10, f"строк на экране должно стать в разы меньше, стало {len(got)}"


def test_the_family_carries_the_best_score() -> None:
    """Балл группы — балл лучшего лота, иначе схлопывание прячет находку."""
    weak = [garage(n) for n in range(1, 4)]
    strong = dict(weak[0])
    strong["documents"] = [{"t": 1}, {"t": 2}]
    got = families(weak + [strong])[0]
    assert got["count"] == 4
    alone = families([strong])[0]["score"]
    assert got["score"] == alone


def test_two_alike_lots_are_not_a_crowd() -> None:
    """Пара одинаковых строк — не поток; сворачивать её значит прятать без нужды."""
    got = families([garage(1), garage(2)])
    assert len(got) == 1 and got[0]["count"] == 2 and got[0]["collapsed"] is False


def test_different_days_are_different_notices() -> None:
    first = garage(1)
    second = dict(garage(2), application_deadline="2099-10-01T09:00:00")
    third = garage(3)
    got = families([first, second, third])
    assert len(got) == 2


def test_a_nameless_lot_never_joins_a_family() -> None:
    """Пустое название — не признак сходства, а его отсутствие."""
    blank = [dict(garage(n), title="", address="") for n in range(1, 5)]
    got = families(blank)
    assert len(got) == 4
    assert all(f["count"] == 1 for f in got)


def test_the_screen_says_what_it_folded() -> None:
    body = script()
    note = function_source("renderFoldNote")
    assert "state.families" in note
    assert "групп" in note and "убрано с экрана" in note
    assert "раскрыть группу" in note
    render = function_source("renderRows")
    assert "familyRowHtml" in render and "toggleFamily" in render
    assert "renderFoldNote()" in render
    assert 'id="foldNote"' in body or 'foldNote' in auctions_page()


def test_platon_sees_the_group_as_one_line() -> None:
    context = function_source("askDigest")
    assert "state.families" in context
    assert "ГРУППА ПОВТОРОВ" in context
