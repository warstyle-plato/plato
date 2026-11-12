"""Смена класса второго офиса: CAPEX, ручные вводные и отсутствие ложного ПФ."""
from __future__ import annotations

import copy
import io
from datetime import date
from math import fsum

import pytest
import openpyxl

import main_legacy as core
import office_workbook as ow
import developaid_nonres_strategy as ns
from xlsx_eval import Evaluator
from test_two_offices_keep_their_own_class import _two_offices


@pytest.fixture(scope="module")
def two_office_book():
    x, t = _two_offices(retail_enabled=False)
    base = core.class_base_preset("comfort", "msk", "nonresidential", x)
    for prefix in ("offices", "offices2"):
        for suffix in ("price_th_per_sqm", "cost_th_per_sqm"):
            x[f"{prefix}_{suffix}"] = base[f"{prefix}_{suffix}"]
    # Ручное число остаётся ручным, даже совпав со ступенью класса.
    x["_class_manual"] = ["offices2_price_th_per_sqm"]
    x.setdefault("_field_origin", {})["inputs.offices2_rent_th_per_sqm_month"] = {
        "source": "manual", "text": "Вписано вручную"}
    x["offices2_rent_th_per_sqm_month"] = ns.office_class_fields("A+")["rent_th_per_sqm_month"]
    recorded = []
    parent = ow._Book

    class RecordingBook(parent):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            recorded.append(self)

    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(ow, "_Book", RecordingBook)
        content, _, meta = core.build_project_workbook(x, t, [], {}, project_name="Два офиса")
    return x, t, content, meta, recorded[-1].reg


def _read(evaluator, registry, key):
    sheet, row, column = registry[key]
    return evaluator.cell(sheet, f"{column or 'B'}{row}")


def _write(book, registry, key, value):
    sheet, row, column = registry[key]
    book[sheet][f"{column or 'B'}{row}"] = value


def test_the_two_classes_agree_with_all_five_engine_paths(two_office_book):
    _, _, content, meta, _ = two_office_book
    assert meta["missing"] == [] and meta["checks"] == ow.PASSED, meta
    evaluator = ow.evaluate(openpyxl.load_workbook(io.BytesIO(content)))
    assert ow.verdict(evaluator) == (ow.PASSED, [])
    assert len(meta["comparisons"][0]["paths"]) == 5


def test_the_second_class_changes_automatic_capex_but_not_the_first_office(two_office_book):
    x, _, content, _, registry = two_office_book
    book = openpyxl.load_workbook(io.BytesIO(content))
    before = Evaluator(book)
    first = _read(before, registry, "cx.o1.building.amt")
    second = _read(before, registry, "cx.o2.building.amt")
    _write(book, registry, "in.o2.class", "B")
    after = Evaluator(book)
    changed = {**x, "offices2_office_class": "B"}
    expected_rate = core.class_base_preset("comfort", "msk", "nonresidential", changed)[
        "offices2_cost_th_per_sqm"]
    assert _read(after, registry, "cx.o1.building.amt") == first
    assert _read(after, registry, "cx.o2.building.amt") == pytest.approx(
        x["offices2_gba_sqm"] * expected_rate / 1000)
    assert _read(after, registry, "cx.o2.building.amt") != second


def test_manual_values_equal_to_the_class_survive_a_class_change(two_office_book):
    x, _, content, _, registry = two_office_book
    book = openpyxl.load_workbook(io.BytesIO(content))
    _write(book, registry, "in.o2.class", "B")
    evaluator = Evaluator(book)
    price_keys = [key for key in registry if key.startswith("o2") and key.endswith(".price")]
    rent_keys = [key for key in registry if key.startswith("o2") and key.endswith(".rent_rate")]
    assert len(price_keys) == 3 and len(rent_keys) == 2
    assert [_read(evaluator, registry, key) for key in price_keys] == [x["offices2_price_th_per_sqm"]] * 3
    assert [_read(evaluator, registry, key) for key in rent_keys] == [x["offices2_rent_th_per_sqm_month"]] * 2


def test_a_manual_cost_survives_class_changes_without_moving_the_first_office(two_office_book):
    x, _, content, _, registry = two_office_book
    book = openpyxl.load_workbook(io.BytesIO(content))
    first = _read(Evaluator(book), registry, "cx.o1.building.amt")
    _write(book, registry, "in.o2.rate_cost", 260)
    _write(book, registry, "in.o2.class", "B")
    evaluator = Evaluator(book)
    assert _read(evaluator, registry, "cx.o1.building.amt") == first
    assert _read(evaluator, registry, "cx.o2.building.amt") == x["offices2_gba_sqm"] * 260 / 1000


def test_the_editable_cost_scale_changes_only_its_office(two_office_book):
    x, _, content, _, registry = two_office_book
    book = openpyxl.load_workbook(io.BytesIO(content))
    sheet = book[ow.INPUTS_SHEET]
    row = next(r for r in range(1, sheet.max_row + 1)
               if sheet.cell(r, 1).value == "Стоимость стройки «под ключ»")
    first = _read(Evaluator(book), registry, "cx.o1.building.amt")
    sheet[f"E{row}"] = 260  # Шкала A+, класс второго офиса.
    evaluator = Evaluator(book)
    pair = core.class_base_preset("elite", "msk", "nonresidential")
    expected = core.object_smr_rate(260, pair) * x["offices2_gba_sqm"] / 1000
    assert _read(evaluator, registry, "cx.o2.building.amt") == pytest.approx(expected)
    assert _read(evaluator, registry, "cx.o1.building.amt") == first


def test_a_manual_cost_equal_to_the_class_stays_fixed_after_export(two_office_book):
    x, t, _, _, _ = two_office_book
    x, t = copy.deepcopy((x, t))
    x["_class_manual"].append("offices2_cost_th_per_sqm")
    content, _, meta = core.build_project_workbook(x, t, [], {}, project_name="Ручная стоимость")
    assert meta["checks"] == ow.PASSED, meta
    book = openpyxl.load_workbook(io.BytesIO(content))
    sheet = book[ow.INPUTS_SHEET]
    class_row = next(r for r in range(1, sheet.max_row + 1)
                     if str(sheet.cell(r, 1).value).startswith("Класс офиса"))
    sheet[f"C{class_row}"] = "B"
    cost_row = next(r for r in range(1, sheet.max_row + 1)
                    if str(sheet.cell(r, 1).value).startswith("Стоимость стройки здания"))
    assert sheet[f"C{cost_row}"].value == x["offices2_cost_th_per_sqm"]
    capex = book[ow.CAPEX_SHEET]
    row = next(r for r in range(1, capex.max_row + 1) if capex.cell(r, 1).value == "Офисы 2: здание")
    assert Evaluator(book).cell(ow.CAPEX_SHEET, f"B{row}") == pytest.approx(
        x["offices2_gba_sqm"] * x["offices2_cost_th_per_sqm"] / 1000)


def test_clearing_manual_inputs_returns_them_to_the_second_class(two_office_book):
    _, _, content, _, registry = two_office_book
    book = openpyxl.load_workbook(io.BytesIO(content))
    _write(book, registry, "in.o2.class", "B")
    _write(book, registry, "in.o2.price", None)
    _write(book, registry, "in.o2.rent", None)
    evaluator = Evaluator(book)
    assert _read(evaluator, registry, "o2s.price") == ns.OFFICE_CLASS_SCALE["B"]["price_th_per_sqm"]
    assert _read(evaluator, registry, "o2r.rent_rate") == ns.office_class_fields("B")["rent_th_per_sqm_month"]


def test_the_changed_class_still_matches_the_engine_in_all_five_cash_models(two_office_book):
    x, t, content, meta, registry = two_office_book
    x, t = copy.deepcopy((x, t))
    x["offices2_office_class"] = "B"
    x["offices2_cost_th_per_sqm"] = core.class_base_preset("comfort", "msk", "nonresidential", x)[
        "offices2_cost_th_per_sqm"]
    core.apply_office_classes(x)
    expected = core._run_authoritative_model(x, t, [], {})["consolidated"]["office_paths"]
    book = openpyxl.load_workbook(io.BytesIO(content))
    _write(book, registry, "in.o2.class", "B")
    evaluator = ow.evaluate(book)
    for path, engine in zip(meta["comparisons"][0]["paths"], expected["paths"]):
        assert path["key"] == engine["key"]
        assert _read(evaluator, registry, f"{path['code']}.npv") == pytest.approx(
            engine["npv"] / 1e6, rel=1e-6, abs=1e-6)


# Без площади: доли ровно 1. С площадью и ставкой второго офиса 7001 м² и
# 138,3 доли в сумме машинно 0.9999999999999999 — прежнее распределение
# открывало ПФ на 10 млн.
@pytest.mark.parametrize("second", [None, {"offices2_gba_sqm": 7001, "offices2_cost_th_per_sqm": 138.3}])
def test_two_non_ddu_offices_do_not_open_a_project_finance_line(two_office_book, second):
    x, t, _, _, _ = two_office_book
    x, t = copy.deepcopy((x, t)) if second is None else _two_offices(retail_enabled=False)
    x.update(second or {})
    for prefix in ("offices", "offices2"):
        core.apply_path(x, prefix, ns.PATH_PRESALE)
    prepared = core.prepared_calculation(x, t, [])
    x, t, rates = (prepared[key] for key in ("x", "t", "rates"))
    op = core.build_operating_model(x, t, rates)
    fin = core.simulate_financing(x, t, rates, op)
    assert all(value == 0 for value in op["debt_capex"].values())
    for key in ("pf_draw_total", "pf_limit", "peak_pf", "pf_reservation_fee", "pf_limit_fee"):
        assert fin[key] == 0, (key, fin[key])


def test_float_shares_of_a_full_split_leave_no_remainder():
    month = date(2027, 1, 1)
    # Доли трёх объектов по их стройке: точная сумма (`fsum`, как в движке)
    # машинно 0.9999999999999999. Встроенный `sum` тут не годится: в 3.11 он
    # складывает подряд и даёт ровно 1.0, в 3.12 — с компенсацией.
    cost = {"a": 2331.611418125469, "b": 2309.434548868302, "c": 2188.5915923395482}
    total = sum(cost.values())
    shares = {key: value / total for key, value in cost.items()}
    assert fsum(shares.values()) != 1.0
    remaining, allocated = ns.allocate_common_capex(
        {month: 3e9}, {key: {month: value} for key, value in cost.items()}, set(cost), shares)
    assert remaining[month] == 0
    assert sum(allocated[key][month] for key in shares) == pytest.approx(3e9)


@pytest.mark.parametrize("ddu_cost", [0.01, 0.0000001])
def test_real_small_ddu_cost_is_not_discarded(ddu_cost):
    month = date(2027, 1, 1)
    object_cost = {"credit": {month: 1000000.0}, "ddu": {month: ddu_cost}}
    share = 1000000.0 / (1000000.0 + ddu_cost)
    remaining, allocated = ns.allocate_common_capex(
        {month: 1000.0 + ddu_cost}, object_cost, set(object_cost), {"credit": share})
    assert remaining[month] >= ddu_cost * 0.99
    assert remaining[month] + allocated["credit"][month] == pytest.approx(1000.0 + ddu_cost)


def test_an_explicit_partial_share_keeps_unallocated_common_cost():
    month = date(2027, 1, 1)
    remaining, allocated = ns.allocate_common_capex(
        {month: 1000.0}, {"credit": {month: 10.0}}, {"credit"}, {"credit": 0.7})
    assert remaining[month] == 300
    assert allocated["credit"][month] == 700
