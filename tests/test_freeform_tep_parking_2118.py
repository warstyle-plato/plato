"""Свободный ТЭП бота считает постоянные места по 2118-ПП, а не по НП/90 × К1.

Решение владельца 16.10.2026 (docs/normative_audit_msk_mo_2026-10.md, §6 п.2):
с 05.08.2026 действует приложение 5 к 945-ПП в редакции 2118-ПП, пункт 1 —
Nп = S / (33 × 2,1) × 0,8, где S — площадь квартир. Прежняя строка бота
«НП жилая / 90 × К1» называлась «методикой города», а К1 в новом порядке
к местам жителей не применяется вовсе. Формулу объявляет движок
(`moscow_permanent_parking_2118`); свободный ТЭП обязан читать её, а не
держать копию.

Запуск: python3 -m pytest tests/test_freeform_tep_parking_2118.py -q
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import main_legacy as core  # noqa: E402

APARTMENTS_SQM = 136818.0


def _freeform(**raw) -> dict:
    values = {"site_area_ha": 5.0, "apartments_saleable_sqm": APARTMENTS_SQM}
    values.update(raw)
    return core.build_freeform_tep("", raw_values=values)


def test_permanent_spaces_follow_2118_and_the_engine_formula():
    """Постоянные места — S / (33 × 2,1) × 0,8 от площади квартир, как в движке."""
    tep = _freeform()
    permanent = math.ceil(APARTMENTS_SQM / (33.0 * 2.1) * 0.8)
    assert permanent == core.moscow_permanent_parking_2118(APARTMENTS_SQM)
    guest = math.ceil(permanent * core._PARKING_GUEST_SHARE)
    assert guest == math.ceil(permanent * 0.1)
    units = tep["tep"]["underground_parking"]["units"]
    assert units == permanent + guest, units
    # Прежняя строка — НП жилая / 90 × К1 (К1 = 1) плюс десятая часть гостевых —
    # дала бы другое число: driver у неё наземная площадь, а не площадь квартир.
    old_permanent = math.ceil(APARTMENTS_SQM / 0.65 * 0.9 / 90.0)
    assert units != old_permanent + math.ceil(old_permanent / 10.0)


def test_the_gns_only_input_reaches_the_same_norm():
    """Когда введена только жилая ГНС, S — 65 % от неё, и норма та же."""
    gns = 200000.0
    tep = _freeform(apartments_saleable_sqm=None, apartments_gns_sqm=gns)
    permanent = core.moscow_permanent_parking_2118(gns * 0.65)
    assert tep["tep"]["underground_parking"]["units"] == (
        permanent + math.ceil(permanent * core._PARKING_GUEST_SHARE))


def test_the_text_names_2118_and_does_not_claim_k1_for_residents():
    """Основание печатается рядом с числом; К1 к местам жителей не приписывается."""
    tep = _freeform()
    calculated = " ".join(tep.get("calculated") or [])
    assumptions = " ".join(tep.get("assumptions") or [])
    assert "2118-ПП" in calculated, calculated
    assert "33 × 2,1" in calculated and "0,8" in calculated, calculated
    assert "гостев" in calculated, calculated
    assert "К1" not in assumptions, assumptions
    assert "К1" not in calculated, calculated


def test_explicit_parking_is_still_the_users_number():
    """Введённое число мест не пересчитывается нормой."""
    tep = _freeform(parking_spaces=777)
    assert tep["tep"]["underground_parking"]["units"] == 777
    assert "2118-ПП" not in " ".join(tep.get("calculated") or [])
    assert any("777" in line for line in tep.get("provided") or [])
