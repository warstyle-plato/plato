"""Площадь гаража у страницы и у движка — один ответ, а не два.

«Я менял вручную ТЭПы и получается, что машиноместа пересчитали, а подземная
площадь за этим не пошла» (владелец, 12.09.2026). Замер на паре полей
«Машино-места — решение проекта» 666 мест и заданные 15 540 м²:

* движок — 15 540 м²: заданная руками площадь сильнее норматива (правило
  владельца 19.08.2026, «вписанная руками площадь гаража — число человека и
  не трогается»);
* страница — 23 310 м²: она брала площадь как `места × 35` и введённое число
  выбрасывала, как только мест больше нуля.

7 770 м² подземной части, которых движок не строит. Это тот же разрыв, что
днём раньше развёл книгу с отчётом (0.23.12): там он чинился у книги, здесь —
у его корня, на экране. Комментарий рядом при этом обещал верное поведение
(«заданная руками площадь главнее импорта») — код обещания не исполнял.

Закреплено:
- при заданных обоих полях страница и движок кладут в строку ТЭП одну площадь;
- места не заданы — площадь по-прежнему ведущая и даёт своё число мест;
- площадь не задана — работает норматив `места × 35`, как и раньше.

Запуск: python3 -m pytest tests/test_the_page_reads_the_garage_pair_like_the_engine.py -q
"""

from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

import main_legacy as core  # noqa: E402
import page_blocks  # noqa: E402

PAGE = core.PAGE
SPACES, AREA = 666, 15540


def _page_row(inputs: dict) -> dict:
    """Строка ТЭП подземного паркинга так, как её ставит сама страница.

    Куски страницы стенд добирает САМ: перечисленные руками, они отстают от
    неё, и падение выходит про стенд, а не про то, что он проверяет. Так и
    случилось — рядом с `repairParkingFromGlavapu` появился признак типа
    проекта, и три проверки разом упали на «isNonResidential is not defined».
    """
    prelude = (
        "const num=v=>String(v);const document={getElementById:()=>null};\n"
        "const tep={apartments:{saleable:32254,units:504},storage:{gns:0},"
        "underground_parking:{units:0,gns:0,total_area:0,useful:0,saleable:0,transfer:0}};\n"
        f"const inputs={json.dumps(inputs)};\n"
    )
    tail = ("repairParkingFromGlavapu();"
            "process.stdout.write(JSON.stringify(tep.underground_parking));")
    out, _ = page_blocks.run(prelude, tail)
    return json.loads(out)


def _engine_row(inputs: dict) -> dict:
    x = copy.deepcopy(core.DEFAULT_INPUTS)
    x.update(inputs)
    result = core.calculate(core.CalcRequest(inputs=x, tep=copy.deepcopy(core.TEP_DEFAULT)))
    return {row["key"]: row for row in result["tep"]["rows"]}["underground_parking"]


def test_a_given_area_wins_on_both_surfaces() -> None:
    """Оба поля заполнены: площадь человека, а не норматив от мест."""
    given = {"underground_manual_spaces": SPACES, "underground_manual_gns_sqm": AREA}
    page, engine = _page_row(given), _engine_row(given)
    # Предохранитель: без него сценарий не проверяет ничего — норматив от мест
    # обязан ОТЛИЧАТЬСЯ от заданной площади, иначе обе стороны сойдутся сами.
    assert abs(SPACES * 35 - AREA) > 1, "норматив совпал с заданной площадью"
    assert abs(float(page["gns"]) - AREA) < 0.6, page
    assert abs(float(engine["gns"]) - AREA) < 0.6, engine
    assert abs(float(page["units"]) - float(engine["units"])) < 0.6


def test_without_an_area_the_norm_still_sizes_the_floor() -> None:
    """Площадь не задана — прежний порядок: места × норматив."""
    given = {"underground_manual_spaces": SPACES, "underground_manual_gns_sqm": 0}
    page, engine = _page_row(given), _engine_row(given)
    assert abs(float(page["gns"]) - SPACES * 35) < 0.6, page
    assert abs(float(engine["gns"]) - float(page["gns"])) < 0.6, engine


def test_without_spaces_the_area_still_leads() -> None:
    """Мест нет — число мест выводится из площади, и обе стороны согласны."""
    given = {"underground_manual_spaces": 0, "underground_manual_gns_sqm": AREA}
    page, engine = _page_row(given), _engine_row(given)
    assert abs(float(page["gns"]) - AREA) < 0.6, page
    assert abs(float(page["units"]) - round(AREA / 35)) < 0.6, page
    assert abs(float(engine["units"]) - float(page["units"])) < 0.6, engine
