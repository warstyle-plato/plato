"""К2 берётся по признаку ТТК, а не всегда «вне».

В расчёте машино-мест К2 читался как `business_outside_ttc` с оговоркой в
коде: «признак попадания внутрь ТТК анализ не отдаёт». Оговорка неверна —
признак приходит тем же ответом (`insideTTC`) и лежит в двух строках от самого
коэффициента, а анализ отдаёт оба значения. Выгрузка штатного калькулятора по
участку внутри ТТК (77:01:0004023, 20.08.2026) подписана «К2 — деловая
активность (внутри ТТК)» и несёт 0,2; наш расчёт на тех же вводных брал
внешний коэффициент, то есть считал приобъектные места по другому числу.

Запуск: python3 -m pytest tests/test_k2_follows_the_ring_road.py -q
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import main as wrapper  # noqa: E402

core = wrapper.core


def _analysis(inside: bool) -> dict:
    return {
        "territory": {"site_area_ha": 3.83, "district": "Пресненский",
                      "cadastral_quarter": "77:01:0004023", "inside_ttc": inside},
        "coefficients": {"rail": 0.75, "business_inside_ttc": 0.2,
                         "business_outside_ttc": 0.5, "rent": 0.1497,
                         "base_cost_zh_high": 287560.46, "upks_zh_high": 123876.46},
    }


def _parking(inside: bool) -> dict:
    card = core.vri_tep_quick("msk", "77:01:0004023:19", site_area_ha=3.83,
                              analysis=_analysis(inside))
    return card


def test_inside_the_ring_takes_the_inside_coefficient():
    """Внутри ТТК приобъектные места считаются по внутреннему К2."""
    inside = _parking(True)
    outside = _parking(False)
    # Коэффициенты разные — значит и приобъектные места разные. Если бы код
    # по-прежнему брал «вне ТТК», числа совпали бы.
    assert inside != outside, "признак ТТК ни на что не повлиял"


def _parameters(inside: bool) -> list[list]:
    """Лист «Параметры территории» из выгрузки — читаем то, что уедет человеку."""
    import io
    import zipfile
    import openpyxl

    card = _parking(inside)
    book = openpyxl.load_workbook(io.BytesIO(card["file"]), data_only=True)
    sheet = book["Параметры территории"]
    return [[cell.value for cell in row] for row in sheet.iter_rows()]


def test_the_export_says_which_coefficient_it_used():
    """Подпись строки обязана называть взятый коэффициент: два разных числа
    под одним именем — это расхождение, которое никто не заметит."""
    for inside, label, value in ((True, "(внутри ТТК)", 0.2),
                                 (False, "(вне ТТК)", 0.5)):
        rows = _parameters(inside)
        line = next((row for row in rows if str(row[0]).startswith("К2")), None)
        assert line, rows
        assert label in str(line[0]), (inside, line)
        assert abs(float(str(line[1]).replace(",", ".")) - value) < 1e-9, (inside, line)


def test_the_analysis_really_carries_the_flag():
    """Оговорка «анализ не отдаёт признак» была неверной — вот он."""
    source = (Path(__file__).resolve().parent.parent / "main_legacy.py").read_text(encoding="utf-8")
    assert '"inside_ttc": bool(payload.get("insideTTC"))' in source
    assert '"business_inside_ttc": business.get("coeff_ba_inside_ttc")' in source
