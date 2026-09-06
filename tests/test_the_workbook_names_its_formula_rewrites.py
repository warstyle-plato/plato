"""Формула шаблона переписывается только там, где это названо.

«Так ты ревизию то провёл по формулам» (владелец, 06.09.2026). Ревизия хардов
(«формула шаблона стала числом») стоит с 0.21.77 и нашла тогда 482 клетки. У
второй болезни сторожа не было вовсе: выгрузка переписывает формулу ФОРМУЛОЙ —
на замере это 24 110 ячеек, то есть 302 строки на пятнадцати листах, и делают
это двадцать проходов `_v4_apply_*`. Каждый из них честно уходит в `missing`,
не опознав формулу, но списка «какие строки чужой методики мы правим» не
существовало: новая безымянная правка прошла бы молча, ровно как проходил
безымянный хард.

Замена «'Вводные'!» → «'Параметры модели'!» правкой не считается и меряется
отдельно (7 979 ячеек на умолчаниях): это переезд ввода на свой лист, ссылка
меняет адрес и не меняет методику.

Запуск: python3 -m pytest tests/test_the_workbook_names_its_formula_rewrites.py -q
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
sys.path.insert(0, str(Path(__file__).resolve().parent))

import main_legacy as core  # noqa: E402

from test_the_workbook_has_no_unnamed_hard_values import TEMPLATE, read  # noqa: E402

openpyxl = pytest.importorskip("openpyxl")

MOVED_SHEET = (("'Вводные'!", "'Параметры модели'!"), ("Вводные!", "'Параметры модели'!"))


def _bare(formula: object) -> str:
    return re.sub(r"\s+", "", str(formula))


def _only_moved(was: object, now: object) -> bool:
    """Правка сводится к переезду листа ввода — методика не тронута."""
    moved = str(was)
    for old, new in MOVED_SHEET:
        moved = moved.replace(old, new)
    return _bare(moved) == _bare(now)


def _rewritten_rows(inputs: dict, tep: dict, phasing: dict | None) -> dict[str, set[int]]:
    bundle = core._run_authoritative_model(inputs, tep, [], phasing)
    content, _, meta = core.build_project_workbook(
        inputs, tep, [], phasing, project_name="Ревизия",
        finance_hints=core._v4_finance_hints(bundle))
    assert not meta.get("missing"), meta["missing"]
    template, book = read(TEMPLATE), read(io.BytesIO(content))

    # Сторож отказывается судить о пустоте: не разобралась книга — это не
    # «нарушений нет», а «мы не прочитали». То же правило, что у ревизии хардов.
    formulas = sum(1 for cells in template.values()
                   for kind, _ in cells.values() if kind == "f")
    assert len(template) >= 15 and formulas > 50_000, (len(template), formulas)

    rows: dict[str, set[int]] = {}
    for sheet, cells in template.items():
        for coord, (kind, was) in cells.items():
            if kind != "f":
                continue
            got = book.get(sheet, {}).get(coord)
            if not (got and got[0] == "f" and got[1] != was):
                continue
            if _only_moved(was, got[1]):
                continue
            rows.setdefault(sheet, set()).add(int(re.sub(r"[A-Z]+", "", coord)))
    return rows


def _named() -> dict[str, set[int]]:
    return {sheet: set(rows) for sheet, (rows, _) in core.V4_REWRITTEN_FORMULA_ROWS.items()}


def _single() -> tuple[dict, dict, None]:
    return copy.deepcopy(core.DEFAULT_INPUTS), copy.deepcopy(core.TEP_DEFAULT), None


def _with_objects_and_queues() -> tuple[dict, dict, dict]:
    inputs = copy.deepcopy(core.DEFAULT_INPUTS)
    inputs.update(
        offices_enabled=True, offices_gba_sqm=20000.0, offices_saleable_sqm=18000.0,
        retail_enabled=True, retail_gba_sqm=12000.0, retail_saleable_sqm=9000.0,
        sports_enabled=True, sports_gba_sqm=5000.0, sports_saleable_sqm=3500.0,
        above_parking_enabled=True, above_parking_spaces=150,
    )
    phasing = {
        "enabled": True, "phase_count": 2, "phase_gap_months": 12,
        "cost_inflation_pct": 8,
        "phases": [
            {"name": "О1", "start_offset_months": 0, "construction_months": 24},
            {"name": "О2", "start_offset_months": 12, "construction_months": 24},
        ],
        "products": {key: [50, 50] for key in
                     ("apartments", "ground_commercial", "underground_parking", "storage")},
        "social_objects": [{"kind": "kindergarten", "places": 150, "phase": 1}],
        "discrete": {"offices": 2, "standalone_retail": 2, "above_parking": 2, "sports": 2},
    }
    return inputs, copy.deepcopy(core.TEP_DEFAULT), phasing


@pytest.mark.parametrize("shape", ["одиночный проект", "очереди и объекты"])
def test_every_rewritten_row_is_named(shape: str) -> None:
    """Строка, чью формулу мы переписали, стоит в списке с причиной."""
    inputs, tep, phasing = _single() if shape == "одиночный проект" else _with_objects_and_queues()
    named = _named()
    unnamed = {
        sheet: sorted(rows - named.get(sheet, set()))
        for sheet, rows in _rewritten_rows(inputs, tep, phasing).items()
        if rows - named.get(sheet, set())
    }
    assert not unnamed, f"формулы переписаны без названной причины: {unnamed}"


def test_every_named_row_carries_a_reason() -> None:
    """Список — это не перечень номеров: у каждого листа названа причина."""
    for sheet, (rows, reason) in core.V4_REWRITTEN_FORMULA_ROWS.items():
        assert rows, sheet
        assert len(reason.strip()) > 40, (sheet, reason)


def test_the_guard_falls_on_an_unnamed_rewrite() -> None:
    """Проверка, которая не падает на поломке, — не проверка."""
    named = _named()
    planted = dict(named)
    planted["CAPEX"] = named["CAPEX"] - {min(named["CAPEX"])}
    rows = _rewritten_rows(*_single())
    assert rows["CAPEX"] - planted["CAPEX"], "снятая строка обязана всплыть как безымянная"
