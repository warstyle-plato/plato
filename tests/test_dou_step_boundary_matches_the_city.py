"""Ступень ННП ДОО на ровно 125 местах — 18 м²/место, как у калькулятора ГлавАПУ.

2151-ПП: «до 125 мест — 27; от 125 до 250 — 18». Калькулятор ГлавАПУ читает
границу строго (`e < 125 → 27`), мы читали «до 125» включительно и на объекте
ровно в 125 мест давали 27 — 3 375 м² против 2 250 у города. Решение владельца
(18.10.2026): как у ГлавАПУ. Школа не менялась: «до 550 / от 551» у обоих
включительно.

Страница считает ту же ступень своим кодом по таблице движка: её ответ
проверяется на node, а не по исходнику.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

import page_blocks  # noqa: E402
import main_legacy as core  # noqa: E402


def test_exactly_125_places_take_the_second_step() -> None:
    per = core.moscow_social_area_per_place
    assert [per("kindergarten", n) for n in (124, 125, 126, 250, 251)] == [27.0, 18.0, 18.0, 18.0, 16.0]
    # Школа — как была: 550 включительно.
    assert [per("school", n) for n in (550, 551, 1000, 1001)] == [18.0, 15.0, 15.0, 13.0]


def test_the_page_answers_the_same_as_the_engine() -> None:
    # Стенд добирает куски страницы по именам сам (`page_blocks.run`): ступень
    # читает регион проекта, и перечисленный руками список отстал бы от неё.
    page = page_blocks.run_json(
        "let inputs={vri_region:'msk'};",
        "console.log(JSON.stringify([124,125,126,550,551].map("
        "n=>[socialAreaPerPlace('kindergarten',n),socialAreaPerPlace('school',n)])));")
    engine = [[core.moscow_social_area_per_place("kindergarten", n),
               core.moscow_social_area_per_place("school", n)] for n in (124, 125, 126, 550, 551)]
    assert page == engine
    assert page[1][0] == 18
