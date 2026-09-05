"""ФОК — объект модели, и уходит он целиком одним путём.

«Фок может и продаваться и передаваться, как и поликлиника или мед центр»
(владелец, 05.09.2026), и следом: «Скорее нет, все или так или так» — половиной
метров объект не делится. Отсюда признак у объекта, а не пара долей: доля
попросила бы делить выручку и зачёт перед городом по одному объекту, и обе
половины выглядели бы верными.

Закреплено:
- ФОК строится в любом случае: деньги на него тратятся и при передаче городу;
- продаётся он только по признаку, и переданный не даёт выручки нигде —
  ни в продуктах отчёта, ни в книге;
- переданный ФОК не имеет своего налогового пула: признавать его стоимость
  нечем, и она уходит в общий пул очереди — как у соцобъекта;
- книга считает то же самое: девять строк паритета проходят при обоих
  признаках, и одиночным проектом, и очередями;
- норматив приобъектной парковки берётся по своей строке юрисдикции: у Москвы
  это код ВРИ 5.1, у области — «оздоровительные комплексы» приложения № 10, и
  одно имя на обе таблицы нашло бы в соседней не ту строку.

Запуск: python3 -m pytest tests/test_the_sports_object_goes_one_way_or_the_other.py -q
"""

from __future__ import annotations

import copy
import io
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

import main_legacy as core  # noqa: E402
import parking_norms  # noqa: E402

GBA = 5000.0
SALEABLE = 3500.0


def _inputs(enabled: bool = True, disposition: str = "sale") -> dict:
    inputs = copy.deepcopy(core.DEFAULT_INPUTS)
    inputs.update(sports_enabled=enabled, sports_disposition=disposition,
                  sports_gba_sqm=GBA, sports_saleable_sqm=SALEABLE)
    return inputs


def _tep() -> dict:
    tep = copy.deepcopy(core.TEP_DEFAULT)
    tep["sports"] = {**tep["sports"], "gns": GBA, "total_area": GBA * 0.94,
                     "saleable": SALEABLE}
    return tep


def _phasing() -> dict:
    return {
        "enabled": True, "phase_count": 2, "phase_gap_months": 12,
        "cost_inflation_pct": 8,
        "phases": [
            {"name": "О1", "start_offset_months": 0, "construction_months": 24},
            {"name": "О2", "start_offset_months": 12, "construction_months": 24},
        ],
        "products": {key: [50, 50] for key in
                     ("apartments", "ground_commercial", "underground_parking", "storage")},
        "social_objects": [],
        # ФОК во второй очереди: в первой его формулы книги не проверялись бы.
        "discrete": {"offices": 2, "standalone_retail": 2, "above_parking": 2, "sports": 2},
    }


def _report(inputs: dict) -> dict:
    return core.calculate(core.CalcRequest(inputs=inputs, tep=_tep(), rates=[]))


def _product(report: dict, key: str) -> dict:
    for item in report["report"]["products"]:
        if item.get("key") == key:
            return item
    return {}


# --- движок -----------------------------------------------------------------

def test_a_transferred_sports_object_is_built_and_not_sold() -> None:
    sold = _report(_inputs(disposition="sale"))
    given = _report(_inputs(disposition="transfer"))
    off = _report(_inputs(enabled=False))

    cost = GBA * core.DEFAULT_INPUTS["sports_cost_th_per_sqm"] * 1000
    assert sold["capex"]["sports"] == pytest.approx(cost)
    # Переданный стоит ровно столько же: город получает построенный объект.
    assert given["capex"]["sports"] == pytest.approx(cost)
    assert off["capex"]["sports"] == 0.0

    assert _product(sold, "sports")["revenue"] > 0
    assert _product(given, "sports").get("revenue", 0.0) == 0.0
    assert _product(off, "sports").get("revenue", 0.0) == 0.0


def test_a_transferred_sports_object_has_no_tax_pool_of_its_own() -> None:
    """Признавать стоимость переданного объекта нечем — выручки у него нет.

    Оставить ему собственный пул значит не признать стоимость до конца проекта:
    налог вырос бы на четверть её при живом расчёте.
    """
    sold = _report(_inputs(disposition="sale"))["finance"]["tax_cost_by_product"]
    given = _report(_inputs(disposition="transfer"))["finance"]["tax_cost_by_product"]
    cost = GBA * core.DEFAULT_INPUTS["sports_cost_th_per_sqm"] * 1000
    assert sold.get("sports", 0.0) == pytest.approx(cost)
    assert given.get("sports", 0.0) == 0.0
    # Стоимость не исчезла — она в общем пуле очереди.
    assert given["core"] > sold["core"]


def test_the_disposition_defaults_to_transfer_when_the_key_is_lost() -> None:
    """Отсутствующий ключ — это «передаём», а не «продаём».

    Поле приходит со страницы явным значением, а потерянное не должно молча
    дорисовывать проекту продажи, которых человек не заказывал.
    """
    assert core.sports_is_sold({}) is False
    assert core.sports_is_sold({"sports_disposition": ""}) is False
    assert core.sports_is_sold({"sports_disposition": "sale"}) is True


# --- книга ------------------------------------------------------------------

def _checks(inputs: dict, phasing: dict | None) -> list[tuple]:
    openpyxl = pytest.importorskip("openpyxl")
    from xlsx_eval import Evaluator

    bundle = core._run_authoritative_model(inputs, _tep(), [], phasing)
    hints = core._v4_finance_hints(bundle)
    content, _, meta = core.build_project_workbook(
        inputs, _tep(), [], phasing, project_name="П", finance_hints=hints)
    assert not meta["missing"], meta["missing"]
    sys.setrecursionlimit(400000)
    evaluator = Evaluator(openpyxl.load_workbook(io.BytesIO(content), data_only=False))
    sheet = evaluator.workbook["ПРОВЕРКИ"]
    failed = []
    for row in range(76, 86):
        if sheet[f"A{row}"].value is None:
            continue
        if evaluator.cell("ПРОВЕРКИ", f"F{row}") != "OK":
            failed.append((str(sheet[f"A{row}"].value),
                           evaluator.cell("ПРОВЕРКИ", f"B{row}"),
                           evaluator.cell("ПРОВЕРКИ", f"C{row}")))
    return failed


@pytest.mark.parametrize("disposition", ["sale", "transfer"])
def test_the_workbook_matches_the_engine_on_a_single_phase(disposition: str) -> None:
    assert _checks(_inputs(disposition=disposition), None) == []


@pytest.mark.parametrize("disposition", ["sale", "transfer"])
def test_the_workbook_matches_the_engine_across_queues(disposition: str) -> None:
    assert _checks(_inputs(disposition=disposition), _phasing()) == []


def test_the_workbook_zeroes_the_saleable_area_of_a_transferred_object() -> None:
    """Гейт стоит в формуле книги, а не в числе: правка признака в книге работает."""
    openpyxl = pytest.importorskip("openpyxl")
    content, _, _ = core.build_project_workbook(
        _inputs(disposition="transfer"), _tep(), [], None, project_name="П")
    book = openpyxl.load_workbook(io.BytesIO(content))
    inputs_sheet = book["Вводные"]
    assert inputs_sheet["K139"].value == "Передаётся городу"
    assert "Продаётся" in str(inputs_sheet["K129"].value), inputs_sheet["K129"].value
    # Площадь стройки признаком не гасится: объект строится в любом случае.
    assert str(inputs_sheet["K128"].value).startswith('=IF(K123="Да"')
    assert inputs_sheet["K126"].value == pytest.approx(GBA)


def test_the_workbook_names_the_object_and_not_the_shopping_centre() -> None:
    """Блок скопирован с ТЦ — и подписи обязаны стать своими, включая ключ API."""
    openpyxl = pytest.importorskip("openpyxl")
    content, _, _ = core.build_project_workbook(_inputs(), _tep(), [], None, project_name="П")
    book = openpyxl.load_workbook(io.BytesIO(content))
    assert book["ОБЪЕКТЫ"]["A124"].value == "ФОК / СПОРТИВНЫЙ ОБЪЕКТ"
    keys = [book["Вводные"][f"M{row}"].value for row in range(123, 140)]
    assert all(str(key or "").startswith("sports_") for key in keys), keys
    assert book["ТЭП"]["B34"].value == "ФОК / спортивный объект"
    assert book["ТЭП"]["A35"].value == "ИТОГО ОБЪЕКТЫ"
    assert book["ТЭП"]["G35"].value == "=SUM(G31:G34)"
    assert book["ТЭП"]["G36"].value == "=SUM(G28,G35)"


def test_the_consolidated_tax_is_shared_by_positive_months_not_by_the_total() -> None:
    """Доля очереди — по положительным МЕСЯЦАМ базы, иначе налог теряется.

    На убыточном проекте итог базы у каждой очереди отрицательный, доля у всех
    ноль, сумма долей ноль — и сводный налог не вычитался из чистой прибыли
    вовсе. Книга показывала прибыль выше движка ровно на весь налог.
    """
    openpyxl = pytest.importorskip("openpyxl")
    content, _, _ = core.build_project_workbook(
        _inputs(disposition="transfer"), _tep(), [], _phasing(), project_name="П")
    book = openpyxl.load_workbook(io.BytesIO(content))
    for row, queue in zip(range(30, 34), range(1, 5)):
        assert book["КОНСОЛИДАТОР"][f"B{row}"].value == (
            f"=SUMIF('CF_{queue}'!$D$22:$DS$22,\">0\")")


# --- норматив парковки ------------------------------------------------------

def test_each_jurisdiction_reads_its_own_row_for_the_sports_object() -> None:
    products = dict((row[0], row[1:3]) for row in core._PARKING_DEMAND_PRODUCTS)
    assert products["sports"] == ("sport", "fitness")
    moscow = parking_norms.moscow_required("sport", GBA, k1=0.9, k2=0.2)
    assert moscow["vri"] == "5.1" and moscow["required_spaces"] > 0
    oblast = parking_norms.mo_required("fitness", GBA)
    assert oblast["required_spaces"] > 0
    assert oblast["source_confirmed"] is True
    assert "1400/45" in oblast["normative_source"]


def test_the_oblast_norm_steps_by_the_area_of_the_object() -> None:
    """Приложение № 10 даёт ступень по площади, а не один диапазон на всё.

    Взять 25–55 там, где документ говорит 25–40 или 40–55, значит расширить
    вилку вдвое и назвать это нормой.
    """
    small = parking_norms.mo_required("fitness", 800.0)
    large = parking_norms.mo_required("fitness", 5000.0)
    assert (small["norm_denominator_min"], small["norm_denominator_max"]) == (25.0, 40.0)
    assert (large["norm_denominator_min"], large["norm_denominator_max"]) == (40.0, 55.0)
    assert any("менее 1000" in note for note in small["assumptions"])
    assert any("1000 м² и более" in note for note in large["assumptions"])
