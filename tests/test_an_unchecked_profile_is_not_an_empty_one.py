"""«Не смогли проверить» и «не заполнено» — разные ответы, и на экране тоже.

Знакомство лежит на ядре по chat_id и переживает и выкатку, и смену устройства.
Спрашивать его второй раз незачем — а спрашивали: `loadProfile` при любом сбое
возвращала прежнее состояние с `complete:false`, и вызывающий открывал анкету.
Отказ проверки сессии, пятисотка ядра, обрыв сети — всё выглядело как «анкета
пустая». Владелец, вошедший тем же аккаунтом с ноутбука, прочитал это как
«просят завести аккаунт заново» (25.08.2026).

То же правило уже записано про НСПД: отсутствие ответа внешнего источника
нельзя показывать как его отрицательный ответ.

Запуск: python3 -m pytest tests/test_an_unchecked_profile_is_not_an_empty_one.py -q
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import main_legacy as core  # noqa: E402


def _body(name: str) -> str:
    start = core.PAGE.index(f"function {name}(")
    return core.PAGE[start:core.PAGE.index("\n}", start)]


def test_a_failed_check_is_marked_as_unknown() -> None:
    """Сбой обязан сказать «не знаю», а не оставить «не заполнено»."""
    body = _body("loadProfile")
    assert "known:false" in body
    assert "known:true" in body
    assert "Знакомство не проверено" in body


def test_the_questionnaire_opens_only_on_a_known_empty_profile() -> None:
    """Анкета — ответ на знание, а не на молчание."""
    assert "state.known&&!state.complete" in _body("askProfileOnResult"), \
        "анкета открывается по неизвестному состоянию"
    body = _body("loadProfile")
    assert "if(openIfEmpty&&!profileState.complete)openProfile();" in body
    # Оба пути сбоя выходят из функции РАНЬШЕ открытия анкеты: пометив
    # состояние «не знаем», функция возвращается, и до `openProfile` дело
    # не доходит.
    opening = body.index("if(openIfEmpty&&!profileState.complete)openProfile();")
    assert body.count("known:false") == 2, "оба сбоя — сеть и отказ сервера"
    assert body.rindex("known:false") < opening


def test_the_cabinet_says_the_reason_instead_of_demanding_the_form() -> None:
    """В кабинете при непроверенном знакомстве стоит причина, а не требование."""
    body = _body("renderAccountBox")
    assert "profileState.known===false" in body
    assert "profileState.known&&!profileState.complete" in body


def test_the_default_state_is_unknown_not_empty() -> None:
    """До ответа сервера мы не знаем ничего — и объявлено это прямо."""
    assert "let profileState={complete:false,profile:{},sources:[],known:false,reason:''};" in core.PAGE
