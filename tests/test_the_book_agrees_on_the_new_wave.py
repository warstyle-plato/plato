"""Книга и движок на том, что пришло волной 21–22.10, — по итогам, а не на глаз.

Сверка книги с движком (`scripts/excel_book_parity.py`) шла по эталонам, ни
один из которых не включал подземную часть в несколько уровней с надбавкой за
глубину (#823) и офис в аренде с выходом по шкале класса (#837). Здесь оба
сценария эталонов (`office_rent`, `deep_underground`) считаются `xlsx_eval` —
формулами самой книги, — и сравниваются той же мерой, что у скрипта:
строки ОТЧЕТ жилой книги и лист «Сверка» нежилой.

Каждая проверка падает на подделке: книга без надбавки за глубину и книга с
испорченной стоимостью выхода обязаны разойтись с движком; строка «Сверки» с
ошибкой вместо числа обязана снять вердикт «ПРОЙДЕНО».

Запуск: python3 -m pytest tests/test_the_book_agrees_on_the_new_wave.py -q
"""

from __future__ import annotations

import copy
import io
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import main_legacy as core  # noqa: E402

import excel_book_parity as parity  # noqa: E402
import golden_snapshot as gs  # noqa: E402
import office_workbook as ow  # noqa: E402
from xlsx_eval import Evaluator  # noqa: E402

openpyxl = pytest.importorskip("openpyxl")

PARAMS = "'Параметры модели'"
_BUILT: dict[str, tuple[bytes, dict]] = {}


def _built(name: str) -> tuple[bytes, dict]:
    """Книга сценария и сводка движка — один раз на модуль."""
    if name not in _BUILT:
        spec = gs.SCENARIOS[name](core, ROOT)
        content, _, meta = core.build_project_workbook(
            copy.deepcopy(spec["inputs"]), copy.deepcopy(spec["tep"]), [],
            copy.deepcopy(spec["phasing"]), project_name=name)
        assert meta.get("missing") in (None, []), meta["missing"]
        bundle = core._run_authoritative_model(
            copy.deepcopy(spec["inputs"]), copy.deepcopy(spec["tep"]), [],
            copy.deepcopy(spec["phasing"]))
        _BUILT[name] = content, bundle["consolidated"]
    return _BUILT[name]


def _report_mismatches(content: bytes, consolidated: dict, tamper=None) -> list[str]:
    book = openpyxl.load_workbook(io.BytesIO(content))
    if tamper:
        tamper(book)
    sys.setrecursionlimit(max(sys.getrecursionlimit(), 400000))
    evaluator = Evaluator(book)
    sheet = book["ОТЧЕТ"]
    rows = {}
    for row in range(1, 40):
        label = sheet.cell(row, 1).value
        if isinstance(label, str) and not label.startswith("="):
            rows.setdefault(label.strip(), (row, evaluator.cell("ОТЧЕТ", f"B{row}")))
    return parity.compare_report(rows, consolidated)


def _drop_depth_markup(book) -> None:
    """Подделка: СМР подземной части по ставке без надбавки за глубину."""
    capex = book["CAPEX"]
    markup = re.compile(r"\(" + re.escape(f"{PARAMS}!$B$45") + r"\*" + re.escape(PARAMS)
                        + r"!\$[A-Z]+\$\d+\)")
    dropped = 0
    for row in capex.iter_rows(min_col=2, max_col=2):
        cell = row[0]
        if isinstance(cell.value, str) and markup.search(cell.value):
            cell.value = markup.sub(f"{PARAMS}!$B$45", cell.value)
            dropped += 1
    assert dropped >= 2, "надбавка за глубину не найдена в строках подземной части очередей"


def test_deep_underground_queues_agree_with_the_engine() -> None:
    content, consolidated = _built("deep_underground")
    massing = consolidated["tep"]["site_massing"]
    # Сценарий действительно про глубину: три уровня и множитель больше единицы.
    assert massing["underground_levels"] == 3
    assert massing["underground_depth_factor"] > 1.005
    assert _report_mismatches(content, consolidated) == []


def test_a_book_without_the_depth_markup_is_caught() -> None:
    content, consolidated = _built("deep_underground")
    lines = _report_mismatches(content, consolidated, tamper=_drop_depth_markup)
    assert any("CAPEX" in line for line in lines), lines


def _check_sheet(content: bytes, tamper=None) -> tuple[str, list]:
    """Вердикт «ПРОВЕРОК» книги офиса: (раздел, показатель) каждой несошедшейся строки."""
    book = openpyxl.load_workbook(io.BytesIO(content))
    if tamper:
        tamper(book)
    return ow.verdict(ow.evaluate(book))


def test_an_office_for_rent_agrees_with_the_engine() -> None:
    content, consolidated = _built("office_rent")
    paths = consolidated.get("office_paths") or {}
    # Сценарий действительно про аренду класса A с паркингом проекта у офиса.
    assert paths.get("current") == "income"
    inputs = gs.SCENARIOS["office_rent"](core, ROOT)["inputs"]
    assert inputs["offices_rent_date"] and inputs["offices_exit_cap_pct"] == 9.5
    verdict, bad = _check_sheet(content)
    assert bad == [] and verdict == ow.PASSED


def test_a_broken_exit_value_is_caught() -> None:
    content, _ = _built("office_rent")

    def tamper(book) -> None:
        sheet = book[ow.EXIT_SHEET]
        row = next(r for r in range(1, sheet.max_row + 1) if sheet[f"A{r}"].value == "Стоимость здания")
        sheet[f"B{row}"] = str(sheet[f"B{row}"].value) + "*0.9"

    verdict, bad = _check_sheet(content, tamper)
    assert verdict == ow.FAILED and any(label == "Офис: стоимость здания" for _, label in bad), bad


def test_an_error_in_a_check_row_is_not_a_pass() -> None:
    """Ячейка с ошибкой не содержит слова «РАСХОЖДЕНИЕ» — и прежний вердикт
    пропускал её как успех. Ошибку Excel здесь изображает её текст."""
    content, _ = _built("office_rent")

    def tamper(book) -> None:
        checks = book[ow.CHECK_SHEET]
        row = next(r for r in range(5, checks.max_row + 1)
                   if checks[f"B{r}"].value == "Чистая прибыль")
        checks[f"G{row}"] = "#VALUE!"

    verdict, bad = _check_sheet(content, tamper)
    assert verdict == ow.FAILED and any(label == "Чистая прибыль" for _, label in bad)


# --- две причины, по которым Нагатино расходилось на 1,31 млн ЧП --------------
# По отдельности обе ниже допуска ОТЧЕТ, поэтому проверяются по месту.

def _evaluated(inputs: dict, tep: dict, phasing: dict | None):
    content, _, meta = core.build_project_workbook(
        inputs, tep, [], phasing or {}, project_name="Сверка")
    assert meta.get("missing") in (None, []), meta["missing"]
    sys.setrecursionlimit(max(sys.getrecursionlimit(), 400000))
    bundle = core._run_authoritative_model(
        copy.deepcopy(inputs), copy.deepcopy(tep), [], copy.deepcopy(phasing or {}))
    return Evaluator(openpyxl.load_workbook(io.BytesIO(content))), bundle


def test_queue_areas_are_not_rounded_to_a_metre() -> None:
    """ГНС очереди — без ROUND(…,0): движок метры не округляет."""
    spec = gs.SCENARIOS["deep_underground"](core, ROOT)
    evaluator, bundle = _evaluated(spec["inputs"], spec["tep"], spec["phasing"])
    for index, phase in enumerate(bundle["phases"]):
        rows = {row["key"]: row for row in phase["result"]["tep"]["rows"]}
        row = 88 + index
        for column, key in (("I", "apartments"), ("J", "ground_commercial"),
                            ("K", "underground_parking")):
            engine = float(rows[key]["gns"])
            book = evaluator.cell("Параметры модели", f"{column}{row}")
            assert book == pytest.approx(engine, abs=1e-3), (column, row, book, engine)
    # Сценарий проверяет дробные метры, а не целые, на которых ROUND невидим.
    first = {row["key"]: row for row in bundle["phases"][0]["result"]["tep"]["rows"]}
    assert 0.01 < float(first["apartments"]["gns"]) % 1 < 0.99


def test_the_bridge_limit_takes_the_whole_cash_social_part() -> None:
    """Совмещённый режим соцнагрузки: в лимит БРИДЖа идёт вся денежная часть,
    которую первая очередь платит до РнС, как у движка, а не её доля по R."""
    inputs, tep = copy.deepcopy(core.DEFAULT_INPUTS), copy.deepcopy(core.TEP_DEFAULT)
    inputs.update(social_mode=core.SOCIAL_MODE_BOTH, social_compensation_mln=500.0)
    phasing = gs.SCENARIOS["deep_underground"](core, ROOT)["phasing"]
    evaluator, bundle = _evaluated(inputs, tep, phasing)
    for index, phase in enumerate(bundle["phases"]):
        finance = phase["result"]["finance"]
        if index == 0:
            assert finance["calculated_bridge_parts"]["social"] == pytest.approx(500e6)
        book = evaluator.cell("CAPEX", f"B{39 + 34 * index}")
        assert book == pytest.approx(finance["calculated_bridge_limit"] / 1e6, abs=1e-6), index
