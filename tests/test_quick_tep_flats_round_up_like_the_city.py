"""Квартиры в дубле калькулятора округляются вверх, как у города.

Калькулятор ГлавАПУ считает квартиры ⌈население / 2,1⌉ (функция `bf` его кода:
`ceil(e * 1e3 / residentsPerFlat)`), и наша норма `tep_derived_norms` делает то
же. Дубль `vri_tep_quick` округлял к ближайшему: на всех записанных выгрузках
(население 422, 377, 970, 2 355, 7 618) дробная часть была ≥ 0,5, и расхождение
не всплывало. Контрпример — население 421: 421 / 2,1 = 200,48 → город 201,
к ближайшему 200.

Сверка: docs/glavapu_vs_engine_formulas_2026-10.md, § 5.
"""

from __future__ import annotations

import io
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import main_legacy as core  # noqa: E402

# Площадь, на которой умолчания калькулятора (плотность 35, 94/6, 0,65) дают
# ровно 421 жителя: 421 × 33 / 0,65 / 0,94 / 35 000 га.
AREA_HA = 421 * 33 / 0.65 / 0.94 / 35000


def _rows(area_ha: float) -> dict[str, str]:
    analysis = {
        "territory": {"area_ha": area_ha, "inside_ttc": False, "district": "Савеловский"},
        "coefficients": {"rail": 0.75, "business_outside_ttc": 0.5,
                         "rent": 0.1281, "base_cost_zh_high": 229036.29},
    }
    result = core.vri_tep_quick("msk", "77:09:0004014:13", analysis=analysis)
    import openpyxl
    sheet = openpyxl.load_workbook(io.BytesIO(result["file"]))["ТЭП"]
    return {str(row[0]).strip(): str(row[3]) for row in sheet.iter_rows(min_row=2, values_only=True)
            if row[0] not in (None, "")}


def test_a_fraction_below_a_half_still_rounds_the_flats_up() -> None:
    rows = _rows(AREA_HA)
    assert rows["4"] == "421"
    assert rows["5"] == "201", "город: ⌈421 / 2,1⌉ = 201; к ближайшему вышло бы 200"


def test_the_mirror_and_the_norm_agree_on_the_flats() -> None:
    """Один вопрос — один владелец ответа: дубль и норма дают одно число квартир."""
    rows = _rows(AREA_HA)
    norm = core.tep_derived_norms(apartment_area_sqm=421 * 33, residential_living_spp_sqm=0.0)
    assert norm["population"] == 421 and norm["apartment_units"] == 201
    assert rows["5"] == str(norm["apartment_units"])
    assert math.ceil(421 / 2.1) == 201 and round(421 / 2.1) == 200
