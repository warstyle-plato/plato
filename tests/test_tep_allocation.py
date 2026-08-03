"""Каноническая аллокация ТЭП по очередям: делит движок, книга берёт готовое.

До 0.17.10 книга нормировала доли продуктов сама: собственный запасной
расклад «поровну» против движкового пресета 40/32/28 и дробная доля даже для
паркинга, который движок раздаёт целыми местами. На Мытищах это давало
2290 машино-мест против 2291 и десятки метров расхождения ГНС очередей.
Теперь деление живёт в одном месте — _phase_tep_product_rows — и книга
получает готовые числа.

Запуск: python3 -m pytest tests -q
"""

from __future__ import annotations

import io
import sys
from pathlib import Path

import openpyxl
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import main as wrapper  # noqa: E402

core = wrapper.core


def _tep() -> dict:
    return {key: dict(value) for key, value in core.TEP_DEFAULT.items()}


def test_indivisible_units_stay_integers_and_keep_the_total():
    """Паркинг и кладовые режутся целыми местами, и сумма частей равна
    округлённому итогу — ни одно место не теряется и не удваивается."""
    tep = _tep()
    tep["underground_parking"]["units"] = 2291
    tep["storage"]["units"] = 437
    phasing = {"products": {"underground_parking": [40, 32, 28],
                            "storage": [40, 32, 28]}}
    rows, _ = core._phase_tep_product_rows(tep, phasing, 3)
    for key, total in (("underground_parking", 2291), ("storage", 437)):
        units = [row[key]["units"] for row in rows]
        assert all(float(u) == int(float(u)) for u in units), f"{key}: дробные места"
        assert sum(units) == total


def test_the_fallback_shares_are_engine_presets():
    """Без явных долей действует пресет движка 40/32/28 — прежний книжный
    запасной расклад «поровну» расходился с расчётом на треть объёма."""
    rows, weights = core._phase_tep_product_rows(_tep(), {}, 3)
    assert weights["apartments"] == pytest.approx([40.0, 32.0, 28.0])
    assert rows[0]["apartments"]["gns"] == pytest.approx(
        0.4 * core.TEP_DEFAULT["apartments"]["gns"])


def test_the_tail_folds_into_the_last_book_queue():
    """Пять очередей на четыре листа CF: объёмы пятой уходят в четвёртую,
    итог по книге равен итогу проекта."""
    tep = _tep()
    tep["underground_parking"]["units"] = 1000
    rows, _ = core._phase_tep_product_rows(tep, {}, 5)
    folded = core._v4_fold_tep_rows(rows, 4)
    assert len(folded) == 4
    assert folded[3]["apartments"]["gns"] == pytest.approx(
        rows[3]["apartments"]["gns"] + rows[4]["apartments"]["gns"])
    assert sum(row["underground_parking"]["units"] for row in folded) == 1000
    assert sum(row["apartments"]["gns"] for row in folded) == pytest.approx(
        tep["apartments"]["gns"])


def test_the_book_carries_engine_phase_volumes():
    """W..AC листа «Вводные» — те же числа, что в ТЭП фаз движка: доли,
    округление паркинга и доли метров совпадают; допуск — только сериализация
    книги (10 значащих цифр, относительная точность 1e-9)."""
    inputs = dict(core.DEFAULT_INPUTS)
    tep = _tep()
    phasing = {"enabled": True, "phase_count": 3,
               "products": {"apartments": [50, 30, 20],
                            "underground_parking": [45, 35, 20]}}
    bundle = core._run_authoritative_model(inputs, tep, [], phasing)
    phases = bundle["phases"]
    assert len(phases) == 3

    content, _, meta = core.build_project_workbook(
        inputs, tep, [], phasing, finance_hints={})
    sheet = openpyxl.load_workbook(io.BytesIO(content), data_only=False)["Вводные"]
    for index, item in enumerate(phases):
        row, phase_tep = 88 + index, item["tep"]
        assert sheet[f"W{row}"].value == pytest.approx(
            phase_tep["apartments"]["gns"], rel=1e-9)
        assert sheet[f"Z{row}"].value == pytest.approx(
            phase_tep["apartments"]["saleable"], rel=1e-9)
        assert sheet[f"X{row}"].value == pytest.approx(
            phase_tep["ground_commercial"]["gns"], rel=1e-9)
        assert sheet[f"Y{row}"].value == pytest.approx(
            phase_tep["underground_parking"]["gns"], rel=1e-9)
        units = float(sheet[f"AB{row}"].value or 0)
        assert units == pytest.approx(phase_tep["underground_parking"]["units"])
        assert units == int(units), "в книгу должны уезжать целые машино-места"
