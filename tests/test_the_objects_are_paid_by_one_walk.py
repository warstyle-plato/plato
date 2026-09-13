"""Выручка и CAPEX отдельно стоящих объектов — один обход реестра.

Блоков было четыре, почти одинаковых, и различались они ровно тремя вещами:
умолчание срока стройки, умолчание роста цены и чем объект меряется. Пока это
жило литералами внутри блоков, «поставить пару ОСЗ» означало пятый такой блок,
а сам состав уже был объявлен один раз (`STANDALONE_OBJECTS`) и до денег не
доезжал.

Проверки держат УТВЕРЖДЕНИЯ, а не форму записи: объект, снятый с реестра,
перестаёт приносить и деньги, и расходы; умолчания реестра — те самые, что
применяет расчёт; порядок строк выручки совпадает с порядком строк ТЭП.
"""

from __future__ import annotations

import copy
import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

import main_legacy as core  # noqa: E402


def _project() -> tuple[dict, dict]:
    """Проект, где у КАЖДОГО объекта живые метры и живой гараж.

    На нулях перестановка невидима — это уже стоило пропущенной ошибки,
    поэтому фикстура включает все объекты разом.
    """
    x = dict(core.DEFAULT_INPUTS)
    x.update({
        "offices_enabled": True, "offices_gba_sqm": 40000, "offices_saleable_sqm": 34000,
        "offices_cost_th_per_sqm": 190, "offices_price_th_per_sqm": 320,
        "offices_parking_under_spaces": 300, "offices_parking_over_spaces": 80,
        "retail_enabled": True, "retail_gba_sqm": 22000, "retail_saleable_sqm": 18000,
        "retail_cost_th_per_sqm": 150, "retail_price_th_per_sqm": 260,
        "retail_parking_under_spaces": 210, "retail_parking_over_spaces": 40,
        "above_parking_enabled": True, "above_parking_spaces": 300,
        "above_parking_cost_mln_per_space": 1.2, "above_parking_price_mln_per_space": 2.1,
        "sports_enabled": True, "sports_gba_sqm": 9000, "sports_saleable_sqm": 7500,
        "sports_cost_th_per_sqm": 170, "sports_price_th_per_sqm": 240,
        "sports_disposition": "sale",
        "sports_parking_under_spaces": 90, "sports_parking_over_spaces": 25,
    })
    tep = copy.deepcopy(core.TEP_DEFAULT)
    for key, gns, sale in (("offices", 40000, 34000), ("standalone_retail", 22000, 18000),
                           ("sports", 9000, 7500)):
        tep[key].update({"gns": gns, "total_area": gns * 0.94,
                         "useful": sale, "saleable": sale})
    tep["above_parking"].update({"units": 300})
    return x, tep


def _run(x: dict, tep: dict) -> dict:
    return core._run_authoritative_model(x, tep, [], {})["consolidated"]


def test_every_object_of_the_roster_earns_and_costs():
    """Реестр — не список имён: по нему идут и выручка, и расходы."""
    out = _run(*_project())
    revenue = out["revenue"]
    capex = out["capex"]
    for obj in core.standalone_objects():
        assert revenue.get(obj.key, 0) > 0, f"{obj.label}: выручки нет"
        assert capex.get(obj.key, 0) > 0, f"{obj.label}: расходов нет"


def test_an_object_taken_off_the_roster_stops_being_paid(monkeypatch):
    """Диверсант: реестр без офисов — и денег у офисов нет ни с какой стороны.

    Проверка утверждает, что деньги считаются ПО РЕЕСТРУ. Пока блоки были
    написаны порознь, снятие строки реестра не меняло ничего, и «состав
    объявлен один раз» было обещанием, а не механизмом.
    """
    x, tep = _project()
    full = _run(x, tep)
    assert full["revenue"]["offices"] > 0 and full["capex"]["offices"] > 0

    short = tuple(o for o in core.STANDALONE_OBJECTS if o.key != "offices")
    monkeypatch.setattr(core, "STANDALONE_OBJECTS", short)
    out = _run(x, tep)
    assert out["revenue"].get("offices", 0) == 0, "офисы принесли деньги мимо реестра"
    assert out["capex"].get("offices", 0) == 0, "офисы стоили денег мимо реестра"
    # Соседи при этом на месте: снят один объект, а не выключен обход.
    assert out["revenue"]["standalone_retail"] > 0


def test_the_calendar_default_comes_from_the_roster(monkeypatch):
    """Срок стройки по умолчанию — строка реестра, а не литерал в блоке.

    У наземного паркинга он 18 месяцев, у остальных 24; пока числа стояли
    внутри блоков, разница между объектами была не объявлена нигде.
    """
    assert {o.key: o.default_months for o in core.standalone_objects()}["above_parking"] == 18
    x, tep = _project()
    x.pop("above_parking_months", None)
    base = _run(x, tep)["revenue"]["above_parking"]

    longer = tuple(o._replace(default_months=48) if o.key == "above_parking" else o
                   for o in core.STANDALONE_OBJECTS)
    monkeypatch.setattr(core, "STANDALONE_OBJECTS", longer)
    moved = _run(x, tep)["revenue"]["above_parking"]
    assert moved != base, "срок из реестра расчёт не читает"


def test_the_growth_default_comes_from_the_roster(monkeypatch):
    """Рост цены до ввода — оттуда же: у паркинга 0,75%, у прочих 1,5%."""
    rates = {o.key: o.growth_pre_default for o in core.standalone_objects()}
    assert rates["above_parking"] == 0.75 and rates["offices"] == 1.5
    x, tep = _project()
    x.pop("offices_growth_pre_pct", None)
    base = _run(x, tep)["revenue"]["offices"]

    faster = tuple(o._replace(growth_pre_default=12.0) if o.key == "offices" else o
                   for o in core.STANDALONE_OBJECTS)
    monkeypatch.setattr(core, "STANDALONE_OBJECTS", faster)
    assert _run(x, tep)["revenue"]["offices"] > base, "рост из реестра расчёт не читает"


def test_the_revenue_rows_stand_in_the_order_of_the_tep_rows():
    """Один порядок на экране, а не два.

    Строки ТЭП шли порядком реестра (ТЦ, офисы, паркинг, ФОК), а строки
    выручки — порядком денежного пути (офисы, ТЦ, …): два ответа на «в каком
    порядке» на одном экране. Сведение блоков в обход убрало второй.
    """
    out = _run(*_project())
    tep_order = [row["key"] for row in out["tep"]["rows"]
                 if row["key"] in core.STANDALONE_PRODUCTS]
    revenue_order = [row["key"] for row in out["monthly"]["revenue"]
                     if row["key"] in core.STANDALONE_PRODUCTS]
    assert tep_order == revenue_order, (
        f"порядок расходится: ТЭП {tep_order}, выручка {revenue_order}")
    assert len(tep_order) == len(core.STANDALONE_PRODUCTS), "объект потерян на одной из сторон"


def test_the_garage_is_sold_by_its_own_object_calendar():
    """Места гаража продаются календарём СВОЕГО объекта.

    Сдвинь стройку офисника на три года — и выручка его паркинга уедет с ним;
    общий календарь продал бы места офиса вместе с квартирами.
    """
    x, tep = _project()
    base = _run(x, tep)["revenue"]["object_parking"]
    assert base > 0, "гаражи объектов не продаются — мерить нечем"

    late = dict(x)
    late["offices_start"] = "2032-01-01"
    late["offices_sales_start"] = "2032-06-01"
    assert _run(late, tep)["revenue"]["object_parking"] != base, (
        "перенос стройки объекта не двинул выручку его гаража")


def test_a_transferred_object_is_built_but_not_sold():
    """Признак продажи гасит выручку, а не стройку (решение владельца 05.09.2026)."""
    x, tep = _project()
    sold = _run(x, tep)
    x_given = dict(x, sports_disposition="transfer")
    given = _run(x_given, tep)
    assert given["revenue"].get("sports", 0) == 0, "переданный ФОК продан"
    assert given["capex"]["sports"] == pytest.approx(sold["capex"]["sports"]), (
        "переданный ФОК построен за другие деньги")
