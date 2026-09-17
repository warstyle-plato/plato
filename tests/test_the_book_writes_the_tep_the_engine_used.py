"""Книга пишет тот ТЭП, на котором посчитан отчёт, а не присланный страницей.

Владелец прислал пару за 10.09.2026 (77:07:0013006:15579 и соседние) со словами
«опять расхождение». Книга сама его и назвала на листе ПРОВЕРКИ: паритет CAPEX
25 550,8 против 24 056,2 млн ₽ — 1 494,6 разницы, — и ровно на ту же сумму
разошлись EBITDA и пик ПФ. Причина одна: подземная площадь 23 310 м² в книге
против 15 540 у отчёта при одинаковых 666 местах. Всё остальное производные:
СМР подземной части ×1,5, а общие статьи ×1,1035 — во столько же вырос
строительный объём. LLCR при этом 0,98 в книге и 1,03 в отчёте, то есть один
документ говорил «не проходит», другой «проходит», и оба выглядели верными.

`/report/workbook` брал ТЭП, присланный страницей, и `calculate` не звал вовсе,
а движок приводит строку ТЭП к вводным: заданная руками площадь гаража сильнее
норматива, выгрузка ГлавАПУ сильнее устаревшей строки, соцобъект считается от
мест. Этих правок книга не видела.

Закреплено:
- база ТЭП в книге равна тому, что движок посчитал, а не тому, что прислали;
- сценарий держит ТЭП, ОТЛИЧАЮЩИЙСЯ от применённого, — иначе проверка не
  проверяет ничего;
- приобъектный паркинг не раскладывается дважды: `apply_object_parking` не
  идемпотентна, метры первых этажей уходят из продаваемой при каждом вызове;
- движок не ответил — это `missing`, а не молчание: книга на присланном ТЭП
  выглядит собранной.

Запуск: python3 -m pytest tests/test_the_book_writes_the_tep_the_engine_used.py -q
"""

from __future__ import annotations

import copy
import io
import sys
from pathlib import Path

import openpyxl
import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import main_legacy as core  # noqa: E402

# Строки блока баз ТЭП на листе «Вводные»: их читает блок очередей книги.
# Ищутся по ПОДПИСИ, а не по номеру: строка, добавленная в блок вводных выше,
# двигает весь низ листа — так норматив благоустройства сдвинул этот блок на
# три строки, и проверка упала, ничего не сказав о том, что сломалось
# (ничего). То же правило, что у колонок книги: читают по заголовку.
BASE_ROWS = {
    "База ГНС квартир": ("apartments", "gns"),
    "База ГНС коммерции": ("ground_commercial", "gns"),
    "База ГНС подземная": ("underground_parking", "gns"),
    "База прод. квартир": ("apartments", "saleable"),
    "База прод. коммерции": ("ground_commercial", "saleable"),
}


def _sent_tep() -> dict:
    """ТЭП страницы: подземная посчитана нормативом 666 × 35 = 23 310 м²."""
    tep = copy.deepcopy(core.TEP_DEFAULT)
    tep["underground_parking"].update(units=666, gns=23310.0, total_area=23310.0)
    return tep


def _inputs() -> dict:
    """Площадь гаража задана руками — она сильнее норматива (правило движка)."""
    inputs = copy.deepcopy(core.DEFAULT_INPUTS)
    inputs.update(underground_manual_spaces=666, underground_manual_gns_sqm=15540)
    return inputs


def _book_bases(inputs: dict, tep: dict) -> tuple[dict, list]:
    content, _name, meta = core.build_project_workbook(inputs, copy.deepcopy(tep), [], {})
    sheet = openpyxl.load_workbook(io.BytesIO(content))["Вводные"]
    found: dict[str, float] = {}
    for row in range(1, sheet.max_row + 1):
        label = str(sheet[f"A{row}"].value or "").strip()
        if label in BASE_ROWS:
            found[label] = sheet[f"B{row}"].value
    missing_rows = [label for label in BASE_ROWS if label not in found]
    assert not missing_rows, f"строк блока баз ТЭП нет на листе: {missing_rows}"
    return found, list(meta.get("missing") or [])


@pytest.fixture(scope="module")
def applied() -> dict:
    result = core.calculate(core.CalcRequest(inputs=_inputs(), tep=_sent_tep()))
    return {row["key"]: row for row in result["tep"]["rows"]}


def test_the_scenario_actually_differs_from_what_was_sent(applied: dict) -> None:
    """Предохранитель: без расхождения на входе проверка ниже пуста."""
    sent = _sent_tep()["underground_parking"]["gns"]
    assert abs(applied["underground_parking"]["gns"] - sent) > 1.0, (
        "движок оставил присланную площадь как есть — сценарий не проверяет правку ТЭП")


def test_the_book_takes_the_area_the_engine_calculated(applied: dict) -> None:
    bases, _missing = _book_bases(_inputs(), _sent_tep())
    for label, (key, field) in BASE_ROWS.items():
        assert abs(float(bases[label]) - float(applied[key][field])) < 0.6, (
            f"«{label}»: книга {bases[label]}, движок {applied[key][field]}")


def test_the_object_parking_is_not_applied_twice() -> None:
    """Продаваемая офиса уменьшается на метры первых этажей ровно один раз."""
    inputs = copy.deepcopy(core.DEFAULT_INPUTS)
    inputs.update(offices_enabled=True, offices_gba_sqm=18800,
                  offices_parking_under_spaces=100, offices_parking_over_spaces=20)
    tep = copy.deepcopy(core.TEP_DEFAULT)
    tep["offices"].update(gns=20000.0, total_area=18800.0, useful=17000.0, saleable=17000.0)
    result = core.calculate(core.CalcRequest(inputs=inputs, tep=copy.deepcopy(tep)))
    office = {row["key"]: row for row in result["tep"]["rows"]}["offices"]
    taken = 20 * core.n(inputs, "object_parking_area_per_space_sqm",
                        core.OBJECT_PARKING_AREA_DEFAULT)
    assert taken > 0, "мест первых этажей нет — вычитать нечего, ветка не проверяется"
    assert abs(office["saleable"] - (17000.0 - taken)) < 0.6, (
        "метры первых этажей вычтены не один раз")


def test_a_silent_engine_is_named_not_hidden(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(core, "_run_authoritative_model",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("движок молчит")))
    _bases, missing = _book_bases(_inputs(), _sent_tep())
    assert any("ТЭП движка" in str(item) for item in missing), missing
