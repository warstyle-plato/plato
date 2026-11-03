"""Отказ калькулятора территории должен называть участок, а не список.

Владелец запустил ТЭП по адресу «Мишина 46» (19.08.2026). Поиск собрал двадцать
два участка одного квартала, калькулятор ГлавАПУ ответил отказом на весь набор —
«Анализ территории не найден или БД вернула пустой результат», — и на экране
осталась красная строка без единого номера. Виноват один участок из двадцати
двух, но какой именно, из ответа не следует никак: калькулятор отвечает на
список целиком.

Теперь на отказе список разбирается по одному, и территория собирается по тем
участкам, которые калькулятор знает, а незнакомые называются поимённо. Молчать
о них нельзя: площадь территории меньше запрошенной, и ТЭП считается по ней.

Запуск: python3 -m pytest tests/test_territory_refusal_names_the_parcel.py -q
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from fastapi import HTTPException

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import main as wrapper  # noqa: E402

core = wrapper.core

_GOOD = ["77:09:0004014:13", "77:09:0004014:1018", "77:09:0004014:1015"]
_BAD = "77:09:0004014:4235"


def _territory(numbers: list[str]) -> dict:
    return {
        "cadZU": {
            "features": [
                {"properties": {"cad_num": number, "square": 0.5}} for number in numbers
            ],
            "square": 0.5 * len(numbers),
        },
        "insideMSC": True,
        "cadQuarter": {"quarter": "77:09:0004014"},
        "district": {"properties": {"name": "Савёловский", "name_ao": "САО"}},
        "pointPosition": {"lat": 55.8, "lng": 37.5},
    }


def _refusal() -> HTTPException:
    return HTTPException(
        status_code=400,
        detail=(
            "Калькулятор территории вернул ошибку: "
            "Анализ территории не найден или БД вернула пустой результат"
        ),
    )


def _calculator(monkeypatch, *, known: list[str], calls: list[list[str]] | None = None):
    """Калькулятор, который отказывает всему набору с незнакомым участком."""

    def fake_payload(numbers, timeout=30.0):
        if calls is not None:
            calls.append(list(numbers))
        if any(number not in known for number in numbers):
            raise _refusal()
        return _territory(list(numbers))

    monkeypatch.setattr(core, "_glavapu_analysis_payload", fake_payload)


def _ask(numbers: list[str]) -> dict:
    return core.analyze_cadastral_territory(
        core.CadastralAnalysisRequest(cadastral_numbers=", ".join(numbers))
    )


def test_unknown_parcel_is_named_and_the_rest_is_calculated(monkeypatch):
    calls: list[list[str]] = []
    _calculator(monkeypatch, known=_GOOD, calls=calls)

    answer = _ask(_GOOD + [_BAD])

    assert answer["recognized"] == _GOOD
    assert answer["missing"] == [_BAD]
    assert answer["territory"]["parcel_count"] == 3
    said = " ".join(answer["warnings"])
    assert _BAD in said
    assert "по одному" in said
    assert "1 из 4" in said
    # Первый запрос — всем набором: разбор по одному стоит запроса на участок,
    # и платить за него, когда территория собирается сразу, незачем.
    assert calls[0] == _GOOD + [_BAD]
    assert calls[-1] == _GOOD


def test_nobody_is_known_and_the_answer_says_so(monkeypatch):
    _calculator(monkeypatch, known=[])

    with pytest.raises(HTTPException) as failure:
        _ask(_GOOD + [_BAD])

    detail = str(failure.value.detail)
    assert "по одному" in detail
    assert "ни один" in detail
    assert failure.value.status_code == 400


def test_parcels_known_apart_but_not_together_say_it(monkeypatch):
    """Отказ по набору при знакомых участках — не «участка нет», а «не собираются»."""

    def fake_payload(numbers, timeout=30.0):
        if len(numbers) == 1:
            return _territory(list(numbers))
        raise _refusal()

    monkeypatch.setattr(core, "_glavapu_analysis_payload", fake_payload)

    with pytest.raises(HTTPException) as failure:
        _ask(_GOOD)

    detail = str(failure.value.detail)
    assert "по отдельности" in detail
    assert "смежные" in detail


def test_broken_network_is_not_a_verdict_about_the_parcel(monkeypatch):
    """Недоступный калькулятор не разбирается по одному и не выдаётся за отказ."""
    calls: list[list[str]] = []

    def fake_payload(numbers, timeout=30.0):
        calls.append(list(numbers))
        raise HTTPException(status_code=502, detail="Сервис определения территории временно недоступен.")

    monkeypatch.setattr(core, "_glavapu_analysis_payload", fake_payload)

    with pytest.raises(HTTPException) as failure:
        _ask(_GOOD + [_BAD])

    assert failure.value.status_code == 502
    assert len(calls) == 1  # ни одного лишнего запроса


def test_unanswered_probe_is_not_counted_as_unknown(monkeypatch):
    """Участок, о котором спросить не удалось, называется отдельно от незнакомых."""
    silent = "77:09:0004014:1015"

    def fake_payload(numbers, timeout=30.0):
        if len(numbers) == 1 and numbers[0] == silent:
            raise HTTPException(status_code=502, detail="нет ответа")
        if any(number in (silent, _BAD) for number in numbers):
            raise _refusal()
        return _territory(list(numbers))

    monkeypatch.setattr(core, "_glavapu_analysis_payload", fake_payload)

    answer = _ask(_GOOD + [_BAD])

    said = " ".join(answer["warnings"])
    assert _BAD in said
    assert "не удалось проверить" in said.lower()
    assert silent in said.split("Не удалось проверить")[1]
    assert silent not in said.split("Не удалось проверить")[0]
