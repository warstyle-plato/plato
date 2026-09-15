"""Каждый отдельно стоящий объект доезжает до CAPEX, выручки и строки ТЭП.

«У нас не завершена работа по паркингу офисников, и вообще ОСЗ разных —
попадают ли они в капекс и в выручку так как надо» (владелец, 14.09.2026).
Ревизия прогоном нашла две потери, и обе — перечисление вместо объявленного
списка.

**ФОК не был назван ни одной подстрокой.** Строка расходов «Отдельные
объекты» раскладывается на «в т.ч.», и список объектов был выписан руками:
офисы, ТЦ, наземный паркинг. ФОК завели четвёртым 05.09.2026, в перечисление
он не вошёл — и его 3 616 млн ₽ (19% строки) стояли в итоге, не имея своей
строки ни на экране, ни в PDF. Та же болезнь, что у корзин находок: корзина,
заведённая позже, в счётчик не попадает.

**Наземный паркинг строился без метров.** Строку ТЭП ему заполняла только
страница (`syncTep`), а проект, пришедший файлом, ссылкой, мостом КРТ, ботом
или скринингом, получал ноль: CAPEX и выручка на месте (они считаются от
числа мест), а метров объекта нет ни в ГНС проекта, ни в строительном объёме —
том самом, на котором считаются общие статьи и все удельные. Мера на
проверочном проекте: расходы 68 710,3 против 68 888,2 млн ₽, ГНС 235 380,7
против 242 880,7. Правило это уже было выведено на соцобъекте: строка, которую
чинит только страница, чинится не везде.

Предохранители обязательны: в умолчаниях ни одного отдельно стоящего объекта
нет вовсе, и без своих вводных файл зеленел бы при полностью забытых объектах.

Запуск: python3 -m pytest tests/test_every_standalone_object_reaches_capex_and_revenue.py -q
"""

from __future__ import annotations

import copy
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import main_legacy as core  # noqa: E402

SPACES = 200          # мест в гараже каждого объекта
GROUND_SPACES = 300   # мест наземного паркинга


def _inputs() -> dict:
    x = dict(core.DEFAULT_INPUTS)
    x.update(
        offices_enabled=True, offices_gba_sqm=40000.0, offices_saleable_sqm=24000.0,
        offices_parking_under_spaces=SPACES, offices_parking_guest_pct=10,
        retail_enabled=True, retail_gba_sqm=30000.0, retail_saleable_sqm=18000.0,
        retail_parking_under_spaces=SPACES,
        sports_enabled=True, sports_gba_sqm=20000.0, sports_saleable_sqm=12000.0,
        sports_disposition="sale", sports_parking_under_spaces=SPACES,
        above_parking_enabled=True, above_parking_spaces=GROUND_SPACES,
    )
    return x


def _tep() -> dict:
    t = copy.deepcopy(core.TEP_DEFAULT)
    t["offices"].update(gns=40000, total_area=37600, saleable=24000)
    t["standalone_retail"].update(gns=30000, total_area=28200, saleable=18000)
    t["sports"].update(gns=20000, total_area=18800, saleable=12000)
    return t


def _result(tep: dict | None = None) -> dict:
    return core.calculate(core.CalcRequest(
        inputs=dict(_inputs()), tep=copy.deepcopy(tep if tep is not None else _tep()),
        rates=[]))


def _standalone_line(result: dict) -> dict:
    lines = [row for row in result["report"]["expense_structure"]
             if row["label"] == "Отдельные объекты"]
    assert lines, "строки «Отдельные объекты» в расходах нет вовсе"
    return lines[0]


def test_the_project_actually_has_all_four_objects() -> None:
    """Предохранитель: не стало объектов — остальное в файле ничего не значит."""
    capex = _result().get("capex") or {}
    for obj in core.STANDALONE_OBJECTS:
        assert float(capex.get(obj.key) or 0) > 0, (
            f"у объекта {obj.key} нет CAPEX — проверки этого файла "
            "перестали что-либо значить")


def test_not_a_single_object_is_left_out_of_the_breakdown() -> None:
    """Сумма подстрок «в т.ч.» равна строке: молча не назван — значит потерян."""
    line = _standalone_line(_result())
    items = line.get("items") or []
    named = {str(item["key"]) for item in items}
    assert named == {obj.key for obj in core.STANDALONE_OBJECTS}, (
        f"в разбивке названы не все объекты: {sorted(named)}")
    assert sum(float(item["value"]) for item in items) == pytest.approx(
        float(line["value"]), rel=1e-9), "подстроки не складываются в свою строку"


def test_every_object_named_in_the_breakdown_has_a_russian_name() -> None:
    """Сырой ключ на экране — это не имя, а ключ."""
    for item in _standalone_line(_result()).get("items") or []:
        assert any("а" <= ch.lower() <= "я" or ch.lower() == "ё" for ch in str(item["label"])), (
            f"объект назван ключом: {item['label']}")


def test_the_ground_parking_carries_its_metres_off_the_page() -> None:
    """Метры наземного паркинга считает движок, а не только `syncTep`."""
    rows = {row["key"]: row for row in _result()["tep"]["rows"]}
    ground = rows["above_parking"]
    per_space = float(core.DEFAULT_INPUTS["above_parking_area_per_space_sqm"])
    assert ground["units"] == GROUND_SPACES
    assert ground["gns"] == pytest.approx(GROUND_SPACES * per_space)
    assert ground["gns"] > 0, "объект строится, а метров у него нет"


def test_the_page_and_the_engine_agree_on_the_ground_parking() -> None:
    """Страница заполняет ту же строку — и обе поверхности дают одни числа."""
    filled = _tep()
    filled["above_parking"].update(core.above_parking_tep_row(_inputs()))
    as_page = _result(filled)["summary"]
    as_engine = _result()["summary"]
    for key in ("total_expenses", "revenue", "construction_volume_sqm", "llcr"):
        assert as_engine[key] == pytest.approx(as_page[key], rel=1e-9), key


def test_only_the_office_garage_is_sold() -> None:
    """Места ТЦ и ФОКа строятся и не продаются, у офисника — за вычетом гостевых."""
    rows = {row["key"]: row for row in _result()["tep"]["rows"]}
    for obj in core.STANDALONE_OBJECTS:
        if not obj.garage:
            continue
        row = rows[obj.key]
        assert row["parking_units"] == SPACES, f"{obj.key}: гараж не построен"
        if obj.garage_sellable:
            assert 0 < row["parking_saleable_units"] < SPACES, (
                f"{obj.key}: продаются все места, включая гостевые")
        else:
            assert row["parking_saleable_units"] == 0, (
                f"{obj.key}: места проданы, хотя это обеспеченность посетителей")
