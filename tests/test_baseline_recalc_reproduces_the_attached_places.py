"""Пересчёт по базе на исходном ТЭП обязан вернуть исходные приобъектные места.

`recalculate_from_glavapu_baseline` снимает ставку приобъектных мест с выгрузки
(места / НП встроенных) и применяет её к новым метрам с округлением вверх. На
тех же метрах произведение ставки и площади — не ровно целое, а 93,000…01 (так
складывается двоичная дробь), и ⌈⌉ отдавал 94 там, где город сказал 93.
Самопроверка метода приобъектные не сравнивала и молчала.

Выгрузка — Нагатино 06.10.2026 (`tests/fixtures/glavapu_nagatino_calc_2026_10_06.json`):
93 приобъектных на 22 217 м² НП встроенных. Сверка:
docs/glavapu_vs_engine_formulas_2026-10.md, § 3 (В1) и § 5.
"""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import main_legacy as core  # noqa: E402

REFERENCE = json.loads((ROOT / "tests" / "fixtures" / "glavapu_nagatino_calc_2026_10_06.json")
                       .read_text(encoding="utf-8"))
I = REFERENCE["inputs"]
C = {key: value[0] for key, value in REFERENCE["calculator"].items()}

BASELINE = {
    "residential_spp_sqm": I["residential_living_spp_sqm"], "ground_commercial_spp_sqm": 24686.0,
    "residential_np_sqm": 348071.0, "ground_commercial_np_sqm": I["built_in_np_sqm"],
    "apartment_area_sqm": I["apartment_area_sqm"], "population": C["population"],
    "required_kindergarten_places": C["kindergarten_places"],
    "required_school_places": C["school_places"],
    "required_clinic_capacity": C["clinic_capacity"],
    "parking_permanent": C["parking_permanent"], "parking_guest": C["parking_guest"],
    "parking_attached": C["parking_onsite"], "change_vri_mln": 18265.873,
    "social_compensation_kindergarten_mln": C["compensation_kindergarten_mln"],
    "social_compensation_school_mln": C["compensation_school_mln"],
    "social_compensation_clinic_mln": C["compensation_clinic_mln"],
    "rent_coefficient": I["rent_coeff"], "vri_base_costs_by_use": {"mkd": I["base_cost_mkd_rub"]},
    "calculation_zone": "1",
}
SAME_AREAS = {
    "apartment_area_sqm": I["apartment_area_sqm"],
    "residential_living_spp_sqm": I["residential_living_spp_sqm"],
    "ground_commercial_spp_sqm": 24686.0, "nonresidential_np_sqm": I["built_in_np_sqm"],
}


def test_the_noise_is_real() -> None:
    """Контрпример существует: ставка × та же площадь даёт не целое."""
    rate = C["parking_onsite"] / I["built_in_np_sqm"]
    assert rate * I["built_in_np_sqm"] > 93 and math.ceil(rate * I["built_in_np_sqm"]) == 94


def test_the_same_metres_give_the_same_attached_places() -> None:
    out = core.recalculate_from_glavapu_baseline(BASELINE, SAME_AREAS)
    assert out["parking"]["attached"] == C["parking_onsite"] == 93
    assert out["parking"]["guest"] == C["parking_guest"] == 291
    assert out["self_check"]["matches_baseline"], out["self_check"]["mismatch"]


def test_the_self_check_names_the_attached_places() -> None:
    """Самопроверка сравнивает и приобъектные: выгрузка, у которой НП встроенных
    не сходится с СПП × 0,9 (прочитана не та строка), называет расхождение,
    а не молчит."""
    out = core.recalculate_from_glavapu_baseline(BASELINE, SAME_AREAS)
    names = [item["name"] for item in out["self_check"]["checked"]]
    assert any("приобъектные" in name for name in names), names
    misread = core.recalculate_from_glavapu_baseline(
        dict(BASELINE, ground_commercial_np_sqm=20000.0), SAME_AREAS)
    assert not misread["self_check"]["matches_baseline"]
    assert any("приобъектные" in line for line in misread["self_check"]["mismatch"]), \
        misread["self_check"]["mismatch"]


def test_the_noise_guard_itself() -> None:
    """Защита режет только двоичный шум: 93,000…01 → 93, а 93,0001 — уже 94."""
    assert core._ceil_places(93 / 22217 * 22217) == 93
    assert core._ceil_places(93.0001) == 94 and core._ceil_places(92.5) == 93


def test_more_metres_still_round_up() -> None:
    """Защита от шума не превращает округление вверх в округление вниз."""
    out = core.recalculate_from_glavapu_baseline(
        BASELINE, dict(SAME_AREAS, ground_commercial_spp_sqm=30000.0, nonresidential_np_sqm=27000.0))
    assert out["parking"]["attached"] == math.ceil(27000.0 * 93 / I["built_in_np_sqm"]) == 114
