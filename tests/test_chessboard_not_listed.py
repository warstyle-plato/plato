"""Невыведенная квартира — непроданный запас, а не продажа и не нулевая цена."""
from __future__ import annotations

import copy
import io

import pytest
from openpyxl import Workbook

from market_search import chessboard


TODAY = "2026-11-20"
COVERAGE = {"from": "2026-08-01", "through": "2026-10-31"}


def inventory(not_listed="not_listed", unknown="unknown"):
    rows = []
    for unit, (status, area) in enumerate([
            ("available", 40), (not_listed, 60), ("booked", 50),
            ("regrouping", 70), ("sold", 80), (unknown, 90)], 1):
        rows.append({"key": f"1:apartment:{unit}", "building": "1", "unit": str(unit),
                     "product": "apartment", "area": area, "status": status,
                     "status_raw": "не для продажи" if unit == 2 else status,
                     "price_per_sqm": 100_000, "amount": area * 100_000,
                     "price_consistent": True})
    return {"buildings": {"1": {"as_of": "2026-11-15", "lots": rows}}}


def contract(unit=99, signed="2026-08-15", area=60):
    return {"unit": f"корп 1 кв.{unit}", "contract": f"ДДУ {unit}",
            "signed": signed, "area": area, "amount": area * 100_000,
            "product": "Квартира"}


def test_new_reader_names_not_listed_and_legacy_snapshot_is_not_rewritten():
    wb = Workbook()
    sheet = wb.active
    for cell, value in {"A2": "корпус 1", "B7": 3, "C7": 1, "E7": 40,
                        "F7": "м²", "C9": 100_000, "E9": 4_000_000,
                        "C10": "Не для продажи"}.items():
        sheet[cell] = value
    stream = io.BytesIO()
    wb.save(stream)
    wb.close()
    assert chessboard.read(stream.getvalue())["buildings"]["1"]["lots"][0]["status"] == "not_listed"
    legacy = inventory("unavailable")
    before = copy.deepcopy(legacy)
    actual = chessboard.overlay(legacy, [contract()], TODAY, COVERAGE)
    current = chessboard.overlay(inventory(), [contract()], TODAY, COVERAGE)
    assert legacy == before
    assert actual["counts"]["unavailable"] == 1
    assert "not_listed" not in actual["counts"]
    assert {k: v for k, v in actual.items() if k != "counts"} == {
        k: v for k, v in current.items() if k != "counts"}


@pytest.mark.parametrize("unknown", ["unknown", "unexpected future status"])
def test_unsold_includes_all_known_statuses_and_unknown_is_never_called_sold(unknown):
    block = chessboard.overlay(inventory(unknown=unknown), [contract()], TODAY, COVERAGE)
    assert block["available"] == 1 and block["available_area"] == 40
    assert block["not_listed"] == 1 and block["not_listed_area"] == 60
    assert block["known_unsold"] == 4 and block["known_unsold_area"] == 220
    assert block["remaining_by_status"] == {
        "available": {"units": 1, "area": 40}, "not_listed": {"units": 1, "area": 60},
        "booked": {"units": 1, "area": 50}, "regrouping": {"units": 1, "area": 70}}
    assert block["unsold_complete"] is False
    assert block["unknown_status"] == 1 and block["unknown_status_area"] == 90
    assert block["ordinary_units"] == 3 and block["ordinary_area"] == 150
    assert block["valuation"] == 15_000_000
    assert block["valuation_scope"] == block["forecast_scope"] == "available+not_listed+booked"
    assert block["unsold_valuation"] is None
    assert block["regrouping_lots"] is block["regrouping_value"] is None


@pytest.mark.parametrize("coverage", [None, COVERAGE])
def test_unknown_release_makes_even_a_complete_pace_horizon_conditional(coverage):
    block = chessboard.overlay(inventory(), [contract()], TODAY, coverage)
    assert block["pace_state"] == ("ok" if coverage else "partial")
    assert block["pace_observed_area"] == 20
    assert block["forecast_area"] == 150
    assert block["months_to_sell"] is block["confirmed_months_to_sell"] is None
    assert block["conditional_months_to_sell"] == 7.5
    assert block["forecast_state"] == "conditional" and block["release_dates_unknown"]
    text = chessboard.render(block)
    for phrase in ["известный непроданный остаток — 4 квартир, 220,0 м²",
                   "свободно квартир — 1, 40,0 м²", "не выведены на витрину",
                   "в бронях — 1, 50,0 м²", "7,5 месяца", "Сроки выхода невыведенных квартир неизвестны",
                   "не подтверждает дату распродажи", "полный непроданный остаток неизвестен",
                   "Квартиры для объединения учтены в непроданном остатке"]:
        assert phrase in text


def test_missing_price_is_unknown_and_priced_subset_has_explicit_coverage():
    snapshot = inventory()
    snapshot["buildings"]["1"]["lots"][1].update(amount=None, price_per_sqm=None, price_consistent=False)
    block = chessboard.overlay(snapshot, [], TODAY)
    assert block["valuation"] is None and block["price_unconfirmed"] == 1
    assert block["priced_units"] == 2 and block["priced_area"] == 90
    assert block["priced_value"] == 9_000_000
    text = chessboard.render(block)
    assert "Цены подтверждены для 2 из 3 квартир (90,0 из 150,0 м²)" in text
    assert "Стоимость только оценённой части — 9,0 млн ₽" in text
    for lot in snapshot["buildings"]["1"]["lots"]:
        lot.update(amount=None, price_consistent=False)
    block = chessboard.overlay(snapshot, [], TODAY)
    assert block["valuation"] is block["priced_value"] is None
    assert block["known_unsold_area"] == 220


def test_contracts_remove_each_unsold_status_once_without_mutating_the_snapshot():
    snapshot = inventory("unavailable")
    before = copy.deepcopy(snapshot)
    rows = [contract(unit, "2026-11-16", area) for unit, area in [(1, 40), (2, 60), (3, 50), (4, 70)]]
    rows += [dict(row) for row in rows]
    block = chessboard.overlay(snapshot, rows, TODAY, COVERAGE)
    assert block["known_unsold"] == block["known_unsold_area"] == 0
    assert block["adjusted_signed"] == 4
    assert block["available"] == block["not_listed"] == block["booked"] == block["regrouping_units"] == 0
    assert block["unknown_status"] == 1
    assert snapshot == before
    ignored = [contract(2, "2026-11-14"), contract(2, "2026-11-21"),
               dict(contract(2, "2026-11-16"), unit="корп 2 кв.2")]
    assert chessboard.overlay(snapshot, ignored, TODAY)["known_unsold"] == 4


@pytest.mark.parametrize("contracts,state", [(None, "missing"), ([], "ok")])
def test_missing_or_confirmed_zero_pace_does_not_generate_a_conditional_horizon(contracts, state):
    block = chessboard.overlay(inventory(), contracts, TODAY, COVERAGE)
    assert block["pace_state"] == state
    assert block["months_to_sell"] is block["conditional_months_to_sell"] is None


def test_conflicting_pace_does_not_gain_a_horizon_from_not_listed_stock():
    row = contract()
    block = chessboard.overlay(inventory(), [row, dict(row, area=600)], TODAY, COVERAGE)
    assert block["pace_state"] == "unknown"
    assert block["months_to_sell"] is block["conditional_months_to_sell"] is None


def test_a_signed_unknown_lot_becomes_known_sold_without_rewriting_source_status():
    snapshot = inventory()
    before = copy.deepcopy(snapshot)
    row = contract(6, "2026-11-16", 90)
    block = chessboard.overlay(snapshot, [row, dict(row)], TODAY, COVERAGE)
    assert block["unknown_status"] == block["unknown_status_area"] == 0
    assert block["unsold_complete"] is True
    assert block["counts"]["unknown"] == 1 and block["adjusted_signed"] == 1
    assert block["known_unsold"] == 4 and block["known_unsold_area"] == 220
    assert snapshot == before


def test_unknown_remaining_status_makes_a_known_subset_horizon_conditional():
    snapshot = inventory(not_listed="sold")
    block = chessboard.overlay(snapshot, [contract()], TODAY, COVERAGE)
    assert not block["release_dates_unknown"] and block["pace_state"] == "ok"
    assert block["ordinary_area"] == block["forecast_area"] == 90
    assert block["months_to_sell"] is block["confirmed_months_to_sell"] is None
    assert block["conditional_months_to_sell"] == 4.5
    assert "Оценка относится только к известной части обычного остатка" in chessboard.render(block)


def test_regrouping_alone_has_no_zero_month_sellout_even_with_positive_pace():
    snapshot = inventory()
    for lot in snapshot["buildings"]["1"]["lots"]:
        if lot["status"] != "regrouping":
            lot["status"] = "sold"
    block = chessboard.overlay(snapshot, [contract()], TODAY, COVERAGE)
    assert block["known_unsold"] == 1 and block["known_unsold_area"] == 70
    assert block["ordinary_units"] == block["forecast_area"] == 0
    assert block["pace_area"] == 20
    assert block["months_to_sell"] is block["conditional_months_to_sell"] is None
    assert block["forecast_state"] == "unknown" and block["unsold_valuation"] is None
    text = chessboard.render(block)
    assert "Обычного остатка для оценки срока нет" in text
    assert "нет положительного темпа продаж" not in text
    assert "Состав новых лотов" in text


def test_complete_ordinary_stock_without_regrouping_has_a_full_value_and_stated_horizon_scope():
    snapshot = inventory(not_listed="sold", unknown="sold")
    snapshot["buildings"]["1"]["lots"][3]["status"] = "sold"
    block = chessboard.overlay(snapshot, [contract()], TODAY, COVERAGE)
    assert block["unsold_complete"] is True
    assert block["known_unsold"] == block["ordinary_units"] == 2
    assert block["known_unsold_area"] == block["ordinary_area"] == 90
    assert block["valuation"] == block["unsold_valuation"] == 9_000_000
    assert block["months_to_sell"] == 4.5 and block["conditional_months_to_sell"] is None
    assert "обычный остаток соответствует 4,5 месяца продаж" in chessboard.render(block)


@pytest.mark.parametrize("state", ["not_listed", "unavailable"])
def test_booking_on_not_listed_stock_does_not_imply_a_sold_flat(state):
    text = "Отчёт за 20.11.2026\nТекущих броней: 1\n- квартира №2, 60 кв.м."
    assert not chessboard.questions(inventory(state), [], text, TODAY)
    sold = text.replace("№2, 60", "№5, 80")
    assert chessboard.questions(inventory(state), [], sold, TODAY)[0]["kind"] == "chess_status"
