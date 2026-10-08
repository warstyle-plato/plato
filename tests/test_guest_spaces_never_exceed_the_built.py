"""Гостевых мест не больше, чем построено, и книга сама приводит строку гаража.

Число гостевых в строке ТЭП может быть чужим: умолчания шаблона несут 109
гостевых из 1 199 мест, и на гараже в 69 мест строка говорила «109 гостевых».
Правило Москвы для ручных мест остаётся S/11 (решение владельца 06.10.2026);
здесь — только то, что такое число не переживает своего гаража, и что книга
без ответа движка выводит строку той же функцией, что движок.
"""

from __future__ import annotations

import main_legacy as core


def test_a_foreign_guest_count_is_capped_by_the_garage() -> None:
    row = {"units": 69, "guest_units": 109}
    assert core.underground_guest_spaces(row) == 69
    assert core.underground_saleable_spaces(row) == 0.0


def test_a_sane_guest_count_and_the_moscow_eleventh_are_untouched() -> None:
    assert core.underground_guest_spaces({"units": 400, "guest_units": 40}) == 40
    assert core.underground_guest_spaces({"units": 220}) == 20


def test_the_book_without_the_engine_derives_the_garage_row(monkeypatch) -> None:
    seen: list[dict] = []
    real = core.apply_underground_tep_row

    def spy(inputs, tep):
        seen.append(tep)
        return real(inputs, tep)

    monkeypatch.setattr(core, "apply_underground_tep_row", spy)
    tep = {"apartments": {"saleable": 20000.0, "units": 300},
           "underground_parking": {"units": 1199, "gns": 41965, "guest_units": 109}}
    inputs = {"underground_manual_spaces": 69, "underground_manual_gns_sqm": 2415}
    try:
        core._build_project_workbook(inputs, tep, [], finance_hints={})
    except Exception:  # noqa: BLE001 — книга на урезанном ТЭП может не собраться
        pass
    assert seen, "книга без ответа движка не вывела строку гаража"
    assert seen[0]["underground_parking"]["units"] == 69
    # Присланный ТЭП вызывающего не тронут.
    assert tep["underground_parking"]["units"] == 1199
