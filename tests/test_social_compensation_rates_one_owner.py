"""Ставки компенсации за соцобъекты — у одного владельца, и он сходится с
калькулятором ГлавАПУ сегодня.

Ночная проверка «Посадка ↔ нормативы» 25.10.2026 нашла: серверные формулы, по
которым считает Telegram и откат сайта, дают по школе на 7 % меньше штатного
калькулятора. Причина — город поднял в коде калькулятора УУПСС на место
(ДОО 4 799,71 → 4 980,45; школа 4 578,69 → 5 066,73; поликлиника
7 887,92 → 8 149,59 тыс. ₽), а у нас эти три числа стояли литералами в двух
местах: в серверном дубле калькулятора и в норме по введённому ТЭП.

Эталон — прод 25.10.2026 (`tests/fixtures/glavapu_prod_2026_10_25.json`):
таблица штатного калькулятора по двум участкам и анализ их кварталов.

Запуск: python3 -m pytest tests/test_social_compensation_rates_one_owner.py -q
"""

from __future__ import annotations

import inspect
import io
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import main as wrapper  # noqa: E402

core = wrapper.core

PROD = json.loads((ROOT / "tests" / "fixtures" / "glavapu_prod_2026_10_25.json")
                  .read_text(encoding="utf-8"))["sites"]
# Калькулятор округляет слагаемые до тысячных.
MONEY_TOL = 0.0015


def _calculator(cad: str) -> dict[str, float]:
    return {str(r[0]).strip(): core._ru_number(str(r[3])) for r in PROD[cad]["calculator_rows"]}


def _mirror_rows(cad: str) -> dict[str, float]:
    site = PROD[cad]
    calc = _calculator(cad)
    # Площадь — как у калькулятора (до тысячной гектара): вопрос теста —
    # ставки, а не округление площади.
    analysis = {"territory": dict(site["territory"], area_ha=calc["1"]),
                "coefficients": site["coefficients"]}
    import openpyxl
    result = core.vri_tep_quick("msk", cad, analysis=analysis)
    sheet = openpyxl.load_workbook(io.BytesIO(result["file"]))["ТЭП"]
    return {str(row[0]).strip(): core._ru_number(str(row[3]))
            for row in sheet.iter_rows(min_row=2, values_only=True)
            if row[0] not in (None, "")}


@pytest.mark.parametrize("cad", sorted(PROD))
def test_the_server_formulas_match_todays_calculator(cad: str) -> None:
    """Дубль калькулятора (кнопка бота, откат сайта) — строки 54–56."""
    calc, ours = _calculator(cad), _mirror_rows(cad)
    for code in ("30", "31", "33", "34"):
        assert ours[code] == calc[code], f"строка {code}: места разошлись"
    for code in ("54", "55", "56"):
        assert ours[code] == pytest.approx(calc[code], abs=MONEY_TOL), \
            f"{cad}, строка {code}: наше {ours[code]} против калькулятора {calc[code]}"


@pytest.mark.parametrize("cad", sorted(PROD))
def test_the_norm_by_tep_matches_todays_calculator(cad: str) -> None:
    """Норма по введённому ТЭП (страница, правка ТЭП) — те же три суммы."""
    calc = _calculator(cad)
    site = PROD[cad]
    population = calc["4"]
    got = core.tep_derived_norms(
        apartment_area_sqm=population * 33.0,
        residential_living_spp_sqm=0.0,
        zone_two=core.district_zone_two(site["territory"]["district"]),
        upks_rub=site["coefficients"]["upks_zh_high"])
    assert got["population"] == population
    parts = got["compensation_breakdown_mln"]
    for kind, code in (("kindergarten", "54"), ("school", "55"), ("clinic", "56")):
        assert parts[kind] == pytest.approx(calc[code], abs=MONEY_TOL), \
            f"{cad}, {kind}: наше {parts[kind]} против калькулятора {calc[code]}"


def test_an_old_export_is_checked_with_the_rates_of_its_day() -> None:
    """Ставки версионные: 16.08.2026 калькулятор давал по школе 294,540 на
    том же Савёловском участке, сегодня 316,795. Оба ответа верны на свою дату."""
    old = core.glavapu_social_compensation_mln("school", 38, 98974.74, "2026-08-16")
    new = core.glavapu_social_compensation_mln("school", 38, 98974.74)
    assert old == pytest.approx(294.540, abs=MONEY_TOL)
    assert new == pytest.approx(316.795, abs=MONEY_TOL)


def test_no_reader_keeps_its_own_copy_of_the_rates() -> None:
    """Ни одна из двух формул не держит ставок у себя: обе зовут владельца."""
    rates = [str(v) for row in core.GLAVAPU_SOCIAL_COMPENSATION_RATES
             for v in row["uupss_th_rub"].values()]
    for reader in (core.vri_tep_quick, core.tep_derived_norms):
        source = inspect.getsource(reader)
        assert "glavapu_social_compensation_mln(" in source, reader.__name__
        leaked = [v for v in rates if v in source]
        assert not leaked, f"{reader.__name__} держит свои ставки: {leaked}"
