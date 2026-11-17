"""Сверщик «Книга ↔ движок» (`scripts/book_engine_parity.py`) сам проверен.

Полный прогон по всем эталонам идёт отдельным workflow («Книга ↔ движок»), на
PR, трогающем методику или книгу, и ночью на main. Здесь — то, без чего его
зелёный ничего не значит:

* эталоны покрывают каждый вид проекта, который обязан сходиться;
* жилая книга и книга нежилого проекта сходятся с движком, а испорченная
  формула в каждой из них даёт расхождение с подписью «проект, строка, книга,
  движок, разница»;
* известное расхождение методики (`KNOWN_GAPS`) существует на самом деле:
  исчезло — запись надо снять, иначе она прячет будущую поломку.

Запуск: python3 -m pytest tests/test_book_engine_parity.py -q
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

pytest.importorskip("openpyxl")

import book_engine_parity as bep  # noqa: E402
import main_legacy as core  # noqa: E402

_BUILT: dict[str, tuple] = {}


def _built(name: str) -> tuple:
    if name not in _BUILT:
        _BUILT[name] = bep.build(core, name)
    return _BUILT[name]


def test_the_reference_set_covers_every_kind_of_project() -> None:
    titles = " | ".join(title for _, title, _ in bep.PROJECTS.values())
    for word in ("Жильё", "Офис по ДДУ", "Офис без ДДУ", "ТЦ", "ФОК", "паркинг", "Смешанный"):
        assert word in titles, word
    assert {kind for kind, _, _ in bep.PROJECTS.values()} == {"v4", "office", "hotel"}


def test_the_housing_book_agrees_and_its_known_gaps_are_real() -> None:
    result = bep.check(core, "default", built=_built("default"))
    assert result.checked > 100
    assert result.mismatches == [], [line.text("default") for line in result.mismatches]
    # Каждая запись KNOWN_GAPS ещё расходится: исчезло расхождение — запись снять.
    seen = {key for key in bep.KNOWN_GAPS for line, _ in result.known if line.row.startswith(key)}
    assert seen == set(bep.KNOWN_GAPS), set(bep.KNOWN_GAPS) - seen


def test_a_tampered_housing_book_is_caught() -> None:
    result = bep.check(core, "default", bep.tamper_v4_reserve, built=_built("default"))
    rows = [line.row for line in result.mismatches]
    assert "CAPEX: Резерв" in rows and any(row.startswith("ОТЧЕТ: CAPEX") for row in rows), rows
    text = result.mismatches[0].text("default")
    assert text.startswith("проект default, строка «") and "книга" in text and "движок" in text and "разница" in text


def test_the_office_book_agrees_and_a_tampered_one_is_caught() -> None:
    clean = bep.check(core, "office_ddu", built=_built("office_ddu"))
    assert clean.checked > 30
    assert clean.mismatches == [], [line.text("office_ddu") for line in clean.mismatches]
    tampered = bep.check(core, "office_ddu", bep.tamper_office_revenue, built=_built("office_ddu"))
    assert any(line.row.endswith("Выручка проекта") for line in tampered.mismatches), tampered.mismatches


def test_a_word_against_a_number_is_a_mismatch() -> None:
    assert not bep.Line("IRR", "N/A — долг не погашен", 0.12, ratio=True).agrees()
    assert bep.Line("IRR", "N/A — долг не погашен", "N/A — долг не погашен").agrees()
    assert not bep.Line("Выручка", None, 5.0).agrees()
    assert bep.Line("Выручка", 1000.0005, 1000.0).agrees()
    assert not bep.Line("Выручка", 1000.2, 1000.0).agrees()


@pytest.mark.parametrize("name", ["office_lease_retained", "hotel_lease_retained"])
def test_retained_lease_books_agree_and_a_changed_lease_base_is_caught(name) -> None:
    built = _built(name)
    canonical = built[2]["land_rent"]
    assert canonical["development_cash_total"] > 0
    assert canonical["operating_cash_total"] > 0
    assert canonical["valuation"]["land_exposures"]
    clean = bep.check(core, name, built=built)
    assert clean.mismatches == [], [line.text(name) for line in clean.mismatches]

    def tamper(book):
        book["Аренда ЗУ"]["B9"] = 200

    changed = bep.check(core, name, tamper, built=built)
    assert any("аренд" in line.row.lower() for line in changed.mismatches), changed.mismatches


def test_hotel_hold_edit_keeps_operating_rent_live_beyond_month_180():
    import copy
    import io

    import hotel_workbook as hw
    import openpyxl
    from xlsx_eval import Evaluator

    name = "hotel_lease_retained"
    content, _, original = _built(name)
    book = openpyxl.load_workbook(io.BytesIO(content))
    book[hw.INPUTS_SHEET][f"C{hw._ROWS['hold']}"] = 18
    spec = bep.PROJECTS[name][2](core)
    spec["inputs"]["hotel_hold_years"] = 18
    expected = core._run_authoritative_model(copy.deepcopy(spec["inputs"]),
        copy.deepcopy(spec["tep"]), [], copy.deepcopy(spec["phasing"]))["consolidated"]
    evaluator = Evaluator(book)
    assert evaluator.cell("Аренда ЗУ", "B19") * 1e6 == pytest.approx(expected["land_rent"]["cash_total"])
    # More operating years must not increase the building/depreciation basis.
    assert evaluator.cell(hw.INPUTS_SHEET, f"C{hw._ROWS['capex_total']}") == pytest.approx(original["capex"]["total"])
    assert evaluator.cell(hw.INPUTS_SHEET, f"C{hw._ROWS['building_net']}") == pytest.approx(
        expected["finance"]["hotel"]["kpi"]["building_net"])
    row = hw.FIRST_ROW + 200
    assert evaluator.cell(hw.CALC_SHEET, f"{hw._c('land_rent_operating')}{row}") > 0
