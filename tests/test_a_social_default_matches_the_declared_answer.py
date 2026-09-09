"""Один садик — одна площадь, кто бы его ни считал.

Умолчание строки ТЭП стояло литералом: 3000 м² на 250 мест, то есть
12 м²/место — ставка, снятая 03.09.2026 как «ниже городского минимума в любой
ёмкости». `DEFAULT_INPUTS` тогда поправили до 18 (РНГП, ступень 27/18/16), а
строку ТЭП забыли. Тот же садик выходил 3000 м² с нулевой ГНС в одиночном
расчёте и 4500 м² с ГНС 5000 в своде очередей, и обе цифры выглядели
одинаково достоверно.

На экране этого не видно вовсе: страница переписывает строку первым же
`syncTep`. Ломается путь, где переписывать некому, — прямые вызовы
`calculate`: скрининг КРТ, пресеты, присланная ссылка, API.

Запуск: python3 -m pytest tests/test_a_social_default_matches_the_declared_answer.py -q
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import main_legacy as core  # noqa: E402


def test_the_default_row_is_the_declared_answer() -> None:
    """Умолчание не литерал, а тот же счёт, что у всех остальных."""
    for kind, (places_key, _, _) in core.SOCIAL_TEP_FIELDS.items():
        places = core.DEFAULT_INPUTS.get(places_key) or 0.0
        expected = core.social_tep_row(kind, places, core.DEFAULT_INPUTS)
        row = core.TEP_DEFAULT[kind]
        for field, value in expected.items():
            assert row[field] == pytest.approx(value), f"{kind}.{field}"


def test_the_default_kindergarten_is_not_the_retired_rate() -> None:
    """Предохранитель на возврат снятой ставки.

    12 м²/место ниже городского минимума при ЛЮБОЙ ёмкости: у ДОО минимум 16.
    Если умолчание снова окажется ниже ступени РНГП, тест назовёт число.
    """
    row = core.TEP_DEFAULT["kindergarten"]
    places = float(row["units"])
    assert places > 0, "садик умолчания должен иметь места, иначе проверять нечего"
    per_place = float(row["total_area"]) / places
    floor = core.moscow_social_area_per_place("kindergarten", places)
    assert floor is not None
    assert per_place == pytest.approx(floor), (
        f"{per_place:.1f} м²/место против ступени города {floor}")


def test_one_kindergarten_has_one_area_in_both_modes() -> None:
    """Та самая поломка: одиночный расчёт против свода очередей.

    До правки — 3000 м² и ГНС 0 против 4500 и 5000.
    """
    inputs = dict(core.DEFAULT_INPUTS)
    tep = {key: dict(value) for key, value in core.TEP_DEFAULT.items()}
    single = core.calculate(core.CalcRequest(inputs=inputs, tep=tep))

    phasing = {
        "enabled": True, "phase_count": 2, "phase_gap_months": 12,
        "phases": [
            {"name": "О1", "start_offset_months": 0, "construction_months": 24},
            {"name": "О2", "start_offset_months": 12, "construction_months": 24},
        ],
        "social_objects": [],
    }
    phased = core.calculate_phased(core.PhasedCalcRequest(
        inputs=dict(core.DEFAULT_INPUTS),
        tep={key: dict(value) for key, value in core.TEP_DEFAULT.items()},
        phasing=phasing))

    def kindergarten(report: dict) -> dict[str, float]:
        rows = ((report or {}).get("tep") or {}).get("rows") or []
        for row in rows:
            if isinstance(row, dict) and str(row.get("label")) == "ДОО":
                return {k: float(row.get(k) or 0.0) for k in ("gns", "total_area", "units")}
        raise AssertionError("строки ДОО нет в отчёте")

    alone = kindergarten(single)
    together = kindergarten(phased["consolidated"])
    assert alone["units"] > 0, "садик должен строиться, иначе сверять нечего"
    for field in ("gns", "total_area", "units"):
        assert alone[field] == pytest.approx(together[field], rel=1e-6), (
            f"{field}: одиночный {alone[field]:.1f} против свода {together[field]:.1f}")


def test_the_kindergarten_stands_in_the_construction_volume() -> None:
    """Нулевая ГНС занижала строительный объём ровно на объект.

    А на объём делятся ВСЕ удельные показатели.
    """
    inputs = dict(core.DEFAULT_INPUTS)
    tep = {key: dict(value) for key, value in core.TEP_DEFAULT.items()}
    report = core.calculate(core.CalcRequest(inputs=inputs, tep=tep))
    volume = float(report["summary"]["construction_volume_sqm"])
    assert volume >= float(core.TEP_DEFAULT["kindergarten"]["gns"]) > 0
