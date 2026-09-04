"""Книга несёт ТЕ ЖЕ значения вводных, что взял движок.

«И тест на соответствие вводных из движка и книги делали?» (владелец,
04.09.2026). Проверок было три, и все про ПРИСУТСТВИЕ: у вводной есть ячейка
со своим ключом, ключ назван, у ячейки есть читатель. Про ЗНАЧЕНИЕ — ни одной.
Присутствие и совпадение — разные утверждения: ячейка на месте, ключ подписан,
а число в ней осталось от шаблона, и книга считает по чужому проекту. Ровно
так уже терялась соцнагрузка — «поле, которого нет в карте записи, молча
остаётся мусором из шаблона».

Счёт нашёл и вторую вещь, крупнее. Дописанные блоки — лестница ставок,
графики платежей и продаж, лестницы цены, календарь соцстройки, кривая
ключевой ставки — писались без стиля, а перенос ввода решает по цвету, что
считается вводом. Шестьдесят вводных из ста семидесяти четырёх оставались на
расчётном листе, где инструкция говорит «печатать нечего»: два ввода, ровно
то, чего быть не должно.

Запуск: python3 -m pytest tests/test_the_book_carries_the_engine_values.py -q
"""

from __future__ import annotations

import datetime
import io
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

import main_legacy as core  # noqa: E402

import v4_entry_sheet as ves  # noqa: E402
import v4_inputs  # noqa: E402

openpyxl = pytest.importorskip("openpyxl")

TEMPLATE = ROOT / "templates" / "DevelopAid_model_v4.xlsx"
pytestmark = pytest.mark.skipif(not TEMPLATE.is_file(), reason="шаблон v4 не поставляется")

# Проект, у которого включено всё и ничего не совпадает с умолчанием шаблона:
# на голых умолчаниях половина блоков не пишется вовсе, а совпадение с
# шаблоном читалось бы как совпадение с движком.
LOADED = {
    **core.DEFAULT_INPUTS,
    "purchase_price_mln": 1234.5, "purchase_schedule": "30%@0; 70%@12",
    "apartment_price_th": 421.0, "commercial_price_th": 383.0,
    "main_above_th_per_sqm": 137.0, "main_under_th_per_sqm": 99.0,
    "profit_tax_pct": 20.0, "marketing_pct": 3.7, "ird_months": 21,
    "construction_months": 29, "share_before_rve_pct": 77.0,
    "pf_spread_pct": 4.1, "pf_special_pct": 3.3, "limit_fee_pct": 0.8,
    "rate_start_pct": 15.5, "rate_curve_shape": 2.5,
    "rate_target_base_pct": 8.5, "rate_target_low_pct": 6.5,
    "rate_target_high_pct": 10.5, "rate_normalization_months": 30,
    "offices_enabled": True, "retail_enabled": True, "above_parking_enabled": True,
    "offices_sales_profile": "60%@0; 40%@12", "retail_sales_profile": "70%@0; 30%@6",
    "above_parking_sales_profile": "80%@0; 20%@6",
    "growth_stage1_pct": 10, "offices_growth_stage1_pct": 8,
    "retail_growth_stage1_pct": 5, "above_parking_growth_stage1_pct": 4,
}


@pytest.fixture(scope="module")
def built():
    content, _, meta = core.build_project_workbook(
        LOADED, core.TEP_DEFAULT, [], {}, project_name="Сверка")
    assert meta["missing"] == [], meta["missing"]
    return openpyxl.load_workbook(io.BytesIO(content), data_only=False), meta


def _same(want, got) -> bool:
    """Совпало ли значение книги с вводной движка — с её единицей.

    Книга держит проценты долей, даты — серийным числом Excel, признаки —
    словом «Да»/«Нет». Это перевод единицы, а не другое число.
    """
    if isinstance(want, bool):
        return got in ("Да", "Нет") and (got == "Да") == want
    if isinstance(want, (int, float)) and isinstance(got, (int, float)):
        want, got = float(want), float(got)
        return abs(want - got) <= max(1e-6, abs(want) * 1e-9) or abs(want / 100.0 - got) <= 1e-9
    if isinstance(got, datetime.datetime) and isinstance(want, str):
        return got.date().isoformat() == want[:10]
    if isinstance(want, str):
        return str(got or "") == want or (want == "" and got is None)
    return False


def test_the_sweep_actually_read_the_book(built):
    """Ноль расхождений значит что-то только вместе с числом сверенного."""
    book, _ = built
    view = v4_inputs.inputs(book)
    read = sum(1 for coord in core._V4_INPUT_CELLS.values()
               if view[coord].value is not None)
    assert read > 50, f"прочитано {read} ячеек — разбор не сработал"


def test_every_mapped_input_holds_the_value_the_engine_used(built):
    """Ячейка на месте и ключ подписан — ещё не значит, что число то же."""
    book, _ = built
    view = v4_inputs.inputs(book)
    wrong = []
    for key, coord in sorted(core._V4_INPUT_CELLS.items()):
        if key not in LOADED or key in core.V4_INPUTS_COMPUTED_IN_THE_CELL:
            continue
        got = view[coord].value
        if isinstance(got, str) and got.startswith("="):
            continue  # ячейка стала читалкой — её значение считает книга
        if not _same(LOADED[key], got):
            wrong.append(f"{key} ({coord}): движок {LOADED[key]!r}, книга {got!r}")
    assert not wrong, "книга несёт не те значения:\n  " + "\n  ".join(wrong)


@pytest.mark.parametrize("key, changed", [
    ("purchase_schedule", "10%@0; 90%@24"),
    ("pf_special_steps", "2,5%@100; 1,1%@130"),
    ("growth_stage1_pct", 17.0),
    ("offices_sales_profile", "25%@0; 75%@18"),
    ("rate_curve_shape", 3.25),
])
def test_a_changed_input_changes_the_book(key, changed):
    """Блоки пишутся своим кодом, и карты координат у них нет: сверять их
    значения по адресу значило бы угадывать геометрию. Проверяется то, ради
    чего вводная существует, — правка обязана доехать."""
    def build(inputs):
        content, _, meta = core.build_project_workbook(
            inputs, core.TEP_DEFAULT, [], {}, project_name="Правка")
        assert meta["missing"] == [], meta["missing"]
        return content
    before = build(LOADED)
    after = build({**LOADED, key: changed})
    assert before != after, f"правка {key} до книги не доехала"


def test_every_input_lives_on_the_sheet_people_type_on(built):
    """Ввод один. Вводная, оставшаяся на расчётном листе, — второй ввод.

    Было шестьдесят таких из ста семидесяти четырёх: дописанные блоки шли без
    стиля, а перенос узнаёт ввод по цвету.
    """
    book, _ = built
    entry = book[ves.ENTRY_SHEET]
    named: set[str] = set()
    for row in entry.iter_rows():
        for cell in row:
            if isinstance(cell.value, str):
                named.update(word for word in re.findall(r"[a-z][a-z0-9_]{3,}", cell.value)
                             if word in core.DEFAULT_INPUTS)
    covered = named | set(core._V4_INPUT_CELLS)
    keys = [field[0] for group in core.FIELD_GROUPS for field in group[1]]
    absent = [key for key in keys
              if key not in covered and key not in core.V4_INPUTS_NOT_IN_BOOK
              and key not in core.V4_INPUTS_SHOWN_ONLY]
    assert not absent, ("вводные, до листа ввода не доехавшие: " + ", ".join(absent))


def test_the_computed_cells_are_named_and_filled(built):
    """Ячейка, в которую идёт посчитанное, названа — иначе её молча сверяли бы
    с полем и однажды «починили» бы под него."""
    book, _ = built
    view = v4_inputs.inputs(book)
    for key, reason in core.V4_INPUTS_COMPUTED_IN_THE_CELL.items():
        assert len(reason) > 30, f"{key}: причина не названа"
        coord = core._V4_INPUT_CELLS[key]
        assert view[coord].value is not None, f"{key} ({coord}): пусто"


def test_the_shown_only_inputs_are_really_unread(built):
    """Список «показано справочно» не свалка: у каждой причина, и книга их
    правда не читает — иначе это рабочая вводная, спрятанная от человека."""
    book, _ = built
    cross = re.compile(re.escape(ves.PARAMS_SHEET) + r"'?!\$?([A-Z]{1,2})\$?(\d+)\b")
    local = re.compile(r"(?<![A-Z0-9!:$])\$?([A-Z]{1,2})\$?(\d+)")
    readers: dict[str, int] = {}
    for sheet in book.worksheets:
        own = sheet.title == ves.PARAMS_SHEET
        for row in sheet.iter_rows():
            for cell in row:
                if not (isinstance(cell.value, str) and cell.value.startswith("=")):
                    continue
                for column, number in cross.findall(cell.value):
                    readers[column + number] = readers.get(column + number, 0) + 1
                if own:
                    for column, number in local.findall(cell.value):
                        readers[column + number] = readers.get(column + number, 0) + 1
    params = book[ves.PARAMS_SHEET]
    for key, item in core.V4_INPUTS_SHOWN_ONLY.items():
        assert len(item["reason"]) > 30, f"{key}: причина не названа"
        coord = item["cell"]
        assert readers.get(coord, 0) == 0, \
            f"{key} ({coord}): ячейку читают {readers[coord]} формул — это рабочая вводная"
        assert params[coord].value is not None, f"{key}: ячейки {coord} нет вовсе"


def test_the_guard_catches_a_value_that_did_not_arrive(built):
    """Проверка, которая не падает на поломке, — не проверка."""
    assert not _same(100.0, 7.0)
    assert not _same(True, "Нет")
    assert _same(4.5, 0.045) and _same(True, "Да")
