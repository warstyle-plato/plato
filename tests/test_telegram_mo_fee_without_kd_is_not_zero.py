"""Сводка МО в Telegram без Кд не печатает «0 ₽» на месте платы за ВРИ.

Когда ядро не рассчитало плату (`payment_used_rub` = None: Кд не установлен,
нет Кср), сводка писала «Смена ВРИ: 0,0 млн ₽» рядом с «Основание: Кд не
установлен» — ноль из поля, которое не содержит величину, читался как ответ
источника. Теперь на этом месте «не рассчитана», а причину называет
`payment_basis` — тот же текст, что и везде, без второй копии.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import main as _wrapper  # noqa: E402

main = _wrapper.core

NUMBER = "50:12:0100131:1"
REASON = (
    "Кд не установлен: округ «Пущино» отсутствует в таблице 3 к 1745-ПП; "
    "впишите коэффициент доходности вручную (vri_kd)."
)


def _mo(vri_patch: dict) -> dict:
    vri = {
        "payment_used_rub": None, "payment_used_mln": None,
        "payment_basis": "Кд не установлен", "kd": None,
        "kd_basis": "округа нет в таблице 3", "kd_document": "",
        "warnings": [REASON],
    }
    vri.update(vri_patch)
    return {
        "territory": {"site_area_ha": 6.6667, "parcel_count": 1, "district": "Городской округ Пущино",
                      "quarter": "50:60:0010101", "cadastral_numbers": [NUMBER]},
        "density_sqm_per_ha": 30000.0,
        "social": {"apartments_sqm": 200000.0, "population": 7143,
                   "kindergarten": {"places": 464, "gba_sqm": 12528.0},
                   "school": {"places": 966, "gba_sqm": 26082.0},
                   "clinic": {"capacity": 127, "gba_sqm": 1905.0},
                   "parking": {"permanent_spaces": 2289}},
        "upks": {"source": {}},
        "vri": vri,
        "warnings": [REASON],
        "inputs": {"vri_region": "mo"},
        "tep": {},
    }


@pytest.fixture
def sent(monkeypatch):
    messages: list[str] = []
    monkeypatch.setattr(main, "_telegram_send_message", lambda chat_id, text, **kw: messages.append(str(text)))
    monkeypatch.setattr(main, "_telegram_send_tep_review", lambda *a, **k: None)
    monkeypatch.setattr(main, "_telegram_territory_photo_async", lambda *a, **k: None)
    return messages


def test_summary_says_not_calculated_instead_of_zero(sent, monkeypatch):
    monkeypatch.setattr(main, "mo_calculate_via_core", lambda query, **kw: _mo({}))
    main._telegram_handle_mo_numbers(1, [NUMBER], NUMBER)
    report = "\n".join(sent)
    assert "Смена ВРИ: <b>не рассчитана</b>" in report
    assert "Основание: Кд не установлен" in report
    assert "0,0 млн ₽" not in report and "0,00 млрд ₽" not in report
    # Причина — одна строка, из предупреждений ядра, а не вторая копия в сводке.
    assert report.count("таблице 3 к 1745-ПП") == 1


def test_parsed_assumptions_carry_the_same_words():
    assumptions = main._telegram_mo_parsed(_mo({}))["assumptions"]
    line = next(item for item in assumptions if item.startswith("плата за смену ВРИ"))
    assert line == "плата за смену ВРИ — не рассчитана (Кд не установлен)"
    assert "0,0 млн" not in line


def test_a_computed_fee_is_still_printed_as_money(sent, monkeypatch):
    computed = {
        "payment_used_rub": 2_087_330_000.0, "payment_used_mln": 2087.33,
        "payment_basis": "прямая формула Кср × площадь квартир × Кд", "kd": 0.05, "warnings": [],
    }
    monkeypatch.setattr(main, "mo_calculate_via_core", lambda query, **kw: _mo(computed))
    main._telegram_handle_mo_numbers(1, [NUMBER], NUMBER)
    report = "\n".join(sent)
    assert "Смена ВРИ: <b>2,09 млрд ₽</b>" in report
    assert "не рассчитана" not in report
    assumptions = main._telegram_mo_parsed(_mo(computed))["assumptions"]
    assert any(item.startswith("плата за смену ВРИ — 2,09 млрд ₽") for item in assumptions)
