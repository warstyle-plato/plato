"""Книга v4 считает как движок там, где повторная ревизия 15.10.2026 нашла разрыв.

Ревизия пересчитала книги восьми эталонов и «Донского» (LibreOffice) и
сверила ОТЧЕТ и ПРОВЕРКИ с движком. Четыре разрыва были ошибками реализации;
каждый тест ниже падает на прежней книге:

1. «Реализованный объём» объекта с местами на первых этажах вычитал их из
   продаваемой второй раз и не той площадью — FAIL 23 400 против 22 000 и
   статус «СБОЙ» на исправном расчёте.
2. Денежная компенсация без введённой суммы: движок платит стоимость стройки
   программы, книга — ноль (Донской: 49,75 млн ₽ соцнагрузки, 57 млн CAPEX).
   Строка «Социальная нагрузка» структуры расходов показывала ноль.
3. Перенесённые в РнС проценты БРИДЖа капитализировались по ставке ПФ со
   следующего месяца, а не с месяца переноса — 2,5 млн ₽ стоимости
   финансирования на умолчаниях.
4. «Оценка потребности в финансировании» прибавляла покупку, ВРИ и
   соцнагрузку к «Расходам проекта всего», где они уже есть.

Полный разбор — docs/excel_book_audit_2026-10-15.md.

Запуск: python3 -m pytest tests/test_the_book_audit_2026_10_15.py -q
"""

from __future__ import annotations

import copy
import io
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

import main_legacy as core  # noqa: E402

openpyxl = pytest.importorskip("openpyxl")

DONSKOY = json.loads((ROOT / "tests" / "fixtures" / "project_settings_donskoy_0_25_78.json")
                     .read_text(encoding="utf-8"))


def _evaluate(content: bytes):
    from xlsx_eval import Evaluator

    sys.setrecursionlimit(400000)
    return Evaluator(openpyxl.load_workbook(io.BytesIO(content), data_only=False))


def _book(x: dict, t: dict, name: str):
    content, _name, meta = core.build_project_workbook(
        dict(x), copy.deepcopy(t), [], {}, project_name=name)
    assert list(meta.get("missing") or []) == [], meta.get("missing")
    return _evaluate(content)


def _engine(x: dict, t: dict) -> dict:
    return core._run_authoritative_model(dict(x), copy.deepcopy(t), [], {})["consolidated"]


# --- 1. места первых этажей вычитаются из продаваемой один раз ----------------

def _office_with_floor_places() -> tuple[dict, dict]:
    x = dict(core.DEFAULT_INPUTS)
    x.update(offices_enabled=True, offices_gba_sqm=40000.0, offices_saleable_sqm=24000.0,
             offices_parking_under_spaces=200, offices_parking_over_spaces=40,
             offices_parking_guest_pct=10)
    t = copy.deepcopy(core.TEP_DEFAULT)
    t["offices"].update(gns=40000, total_area=37600, useful=24000, saleable=24000)
    return x, t


@pytest.fixture(scope="module")
def office_book():
    x, t = _office_with_floor_places()
    return _engine(x, t), _book(x, t, "Офис с местами на первых этажах")


def test_the_office_really_has_floor_places(office_book) -> None:
    """Предохранитель: без мест первых этажей проверка ниже ничего не значит."""
    engine, _book_ = office_book
    row = next(r for r in engine["tep"]["rows"] if r["key"] == "offices")
    assert row["parking_over_units"] == 40
    assert row["parking_saleable_after_sqm"] < row["saleable"]


def test_the_volume_check_expects_what_the_engine_sells(office_book) -> None:
    engine, book = office_book
    sold = next(r for r in engine["tep"]["rows"] if r["key"] == "offices")[
        "parking_saleable_after_sqm"]
    assert book.cell("ПРОВЕРКИ", "C39") == pytest.approx(sold, rel=1e-9)
    assert book.cell("ПРОВЕРКИ", "B39") == pytest.approx(sold, rel=1e-9)
    assert book.cell("ПРОВЕРКИ", "F39") == "OK"


def test_no_check_of_the_office_book_fails(office_book) -> None:
    _engine_, book = office_book
    checks = book.workbook["ПРОВЕРКИ"]
    failed = [f"{checks[f'A{row}'].value}: {book.cell('ПРОВЕРКИ', f'B{row}')} "
              f"против {book.cell('ПРОВЕРКИ', f'C{row}')}"
              for row in range(4, 130)
              if checks[f"A{row}"].value and book.cell("ПРОВЕРКИ", f"F{row}") == "FAIL"]
    assert failed == []


# --- 2. денежная компенсация без суммы — стоимость стройки, как у движка ------

@pytest.fixture(scope="module")
def donskoy():
    x = {**core.DEFAULT_INPUTS, **DONSKOY["inputs"]}
    t = copy.deepcopy(DONSKOY["tep"])
    return _engine(x, t), _book(x, t, "Донской")


def test_donskoy_pays_money_without_a_typed_amount(donskoy) -> None:
    """Предохранитель: режим денежный, суммы нет, а движок платит."""
    engine, _book_ = donskoy
    assert DONSKOY["inputs"]["social_mode"] == "Денежная компенсация"
    assert not float(DONSKOY["inputs"].get("social_compensation_mln") or 0)
    assert engine["capex"]["social"] > 1e6


def test_the_book_capex_carries_the_engine_social_payment(donskoy) -> None:
    engine, book = donskoy
    social = sum(book.cell("CAPEX", f"B{row}") or 0 for row in (31, 65, 99, 133))
    assert social == pytest.approx(engine["capex"]["social"] / 1e6, rel=1e-9)
    assert book.cell("ОТЧЕТ", "B6") == pytest.approx(engine["summary"]["capex"] / 1e6, rel=1e-6)


def test_the_expense_structure_shows_the_social_payment(donskoy) -> None:
    """Строка «Социальная нагрузка» показывает то, что заплачено, а не пустое поле."""
    engine, book = donskoy
    assert book.cell("ОТЧЕТ", "B36") == pytest.approx(engine["capex"]["social"] / 1e6, rel=1e-9)
    assert book.cell("ОТЧЕТ", "H37") == pytest.approx(book.cell("ОТЧЕТ", "B36"), rel=1e-9)


def test_the_typed_compensation_still_wins() -> None:
    """Введённая сумма платится как есть — стоимость стройки её не подменяет."""
    x = {**core.DEFAULT_INPUTS, **DONSKOY["inputs"], "social_compensation_mln": 120.0}
    assert core.social_cash_compensation(x) == pytest.approx(120e6)
    x["social_compensation_mln"] = 0
    assert core.social_cash_compensation(x) == pytest.approx(
        sum(core.social_construction_costs(x).values()))


# --- 3 и 4. стоимость финансирования и оценка потребности на умолчаниях --------

@pytest.fixture(scope="module")
def default_book():
    x, t = dict(core.DEFAULT_INPUTS), copy.deepcopy(core.TEP_DEFAULT)
    return _engine(x, t), _book(x, t, "Умолчания")


def test_the_bridge_interest_compounds_from_the_permit_month(default_book) -> None:
    engine, book = default_book
    finance = engine["finance"]
    assert finance["transferred_bridge_interest"] > 1e6, "переносить нечего — тест пуст"
    assert book.cell("ОТЧЕТ", "B9") == pytest.approx(
        finance["financing_cost"] / 1e6, rel=2e-5)


def test_the_financing_need_counts_each_cost_once(default_book) -> None:
    engine, book = default_book
    assert book.cell("Параметры модели", "B24") == pytest.approx(
        engine["finance"]["pf_limit_required"] / 1e6)


# --- 5. книга нежилого: IRR и NPV при непогашенном долге — «N/A», как у движка --

@pytest.fixture(scope="module")
def nonres_unrepaid():
    sys.path.insert(0, str(ROOT / "scripts"))
    import golden_snapshot

    spec = golden_snapshot.s_nonresidential(core, ROOT)
    engine = core._run_authoritative_model(
        dict(spec["inputs"]), copy.deepcopy(spec["tep"]), [], {})["consolidated"]
    content, _name, _meta = core.build_project_workbook(
        dict(spec["inputs"]), copy.deepcopy(spec["tep"]), [], {}, project_name="нежилой")
    return engine, _evaluate(content)


def test_the_nonres_engine_takes_the_returns_away(nonres_unrepaid) -> None:
    """Предохранитель: у эталона долг ПФ не погашен, и движок снял IRR/NPV."""
    engine, _book_ = nonres_unrepaid
    assert engine["summary"]["equity_returns"]["status"] == "debt_unrepaid"
    assert engine["summary"]["npv"] is None


def test_the_nonres_book_says_na_like_the_engine(nonres_unrepaid) -> None:
    engine, book = nonres_unrepaid
    label = engine["summary"]["equity_returns"]["label"]
    report = book.workbook["Отчёт"]
    shown = {report[f"A{row}"].value: book.cell("Отчёт", f"B{row}")
             for row in range(1, report.max_row + 1)
             if str(report[f"A{row}"].value or "").startswith(("NPV", "IRR"))}
    assert shown and all(value == label for value in shown.values()), shown
    assert book.cell("Сверка", "I3") == "ПРОЙДЕНО"
