"""Группа «Финансирование» во «Вводных» — простым языком (`docs/plain_language.md`).

Пояснения начинаются с единицы, а объяснение идёт отдельным предложением:
по этому разрезу `class_field_unit` берёт единицу для заголовка группы. У
«п.п.» точка — часть единицы, а не конец предложения: без неё в заголовке
стояло бы «4,5 п.п» без точки. Сокращения банковских терминов расшифрованы
при первом упоминании в группе.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import main_legacy as core  # noqa: E402

GROUP = "Финансирование"


def _hints() -> list[tuple[str, str]]:
    for name, fields in core.FIELD_GROUPS:
        if name == GROUP:
            return [(f[0], str(f[2])) for f in fields]
    raise AssertionError(f"нет группы «{GROUP}»")


def test_units_stay_short_and_keep_their_dot():
    units = {key: core.class_field_unit(key) for key, _ in _hints()}
    assert units["bridge_spread_pp"] == "п.п."
    assert units["pf_spread_pp"] == "п.п."
    assert units["bridge_cap_spread_pp"] == "п.п."
    assert units["pre_pf_own_funds_mln"] == "млн ₽"
    assert units["pf_limit_approved_mln"] == "млн ₽"
    assert units["pf_special_pct"] == "% годовых"
    assert units["limit_fee_pct"] == "% в год"
    assert units["discount_rate_pct"] == "% годовых"


def test_no_telegraph_and_terms_are_spelled_out_first():
    hints = _hints()
    for key, hint in hints:
        assert ";" not in hint, (key, hint)
    text = " ".join(hint for _, hint in hints)
    for short, full in (("ПФ", "проектного финансирования (ПФ)"),
                        ("эскроу", "счетах эскроу. Это особые счета в банке"),
                        ("НКЛ", "НКЛ — невозобновляемую кредитную линию"),
                        ("п.п.", "п.п. Процентные пункты")):
        assert full in text, short
        # Первое упоминание сокращения — внутри расшифровки, а не раньше неё.
        start = text.index(full)
        assert start <= text.index(short) < start + len(full), short


def test_the_interest_mode_keeps_its_value_and_says_what_happens():
    page = core.PAGE
    assert "__DEVELOPAID_BRIDGE_INTEREST_MODES__" not in page
    assert '["Капитализация в ПФ", "Выплата при рефинансировании"].forEach' in page
    assert "'Капитализация в ПФ':'Прибавить к долгу ПФ'" in page
    assert "'Выплата при рефинансировании':'Заплатить сразу при переходе на ПФ'" in page
