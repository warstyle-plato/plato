"""Анкеты и пользователи переживают то, что журнал не переживает.

Журнал обращений подметается через полгода и живёт на том хосте, который
обслужил запрос: на Render он кончается вместе с контейнером. Разбор 23.08.2026
показал, чем это кончается: на 711 расчётов нашлись 2 знакомства и 1 анкета, а
74 вопроса Платону легли под нулевым chat_id, потому что `/agent/chat` его не
передавал вовсе. Поэтому анкета и факт «человек пришёл» лежат файлами рядом с
профилями, а не строками в подметаемом журнале.

Запуск: python3 -m pytest tests/test_surveys_and_users_outlive_the_journal.py -q
"""

from __future__ import annotations

import json
import shutil
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import main_legacy as core  # noqa: E402


@pytest.fixture()
def storage(tmp_path, monkeypatch):
    """Своё место на диске: тест не трогает данные разработчика."""
    monkeypatch.setattr(core, "_PROJECTS_DIR", tmp_path / "projects")
    monkeypatch.setattr(core, "_USAGE_DIR", tmp_path / "usage")
    core._USAGE_SWEPT.clear()
    return tmp_path


def test_survey_survives_the_journal_loss(storage):
    """Журнала не стало — анкета осталась.

    Это не выдуманный случай: диск бота на Render живёт до следующей выкатки,
    а журнал ядра подметается через `_USAGE_KEEP_DAYS`. Анкета лежит своим
    файлом рядом с профилями и не зависит ни от того, ни от другого.
    """
    core.usage_track("survey", surface="site", chat_id=555,
                     ratings={"general_ui": 5}, impression="считает быстро")

    shutil.rmtree(core._USAGE_DIR)
    assert not core._USAGE_DIR.exists()

    stored = core.survey_records()
    assert len(stored) == 1
    assert stored[0]["impression"] == "считает быстро"
    assert stored[0]["chat"] == 555


def test_survey_summary_reads_the_store_not_only_the_journal(storage):
    """Свод показывает анкету, которой в журнале уже нет."""
    core.survey_store({"at": time.time(), "kind": "survey", "chat": 777,
                       "surface": "telegram", "ratings": {"general_ui": 4},
                       "impression": "не верю ставке ПФ", "problems": {}})
    summary = core.survey_summary(30)
    assert summary["answers"] == 1
    assert any("не верю ставке ПФ" in str(note.get("text")) for note in summary["notes"])


def test_survey_is_not_counted_twice(storage):
    """Анкета из журнала и она же из хранилища — одна анкета, а не две."""
    core.usage_track("survey", surface="site", chat_id=42,
                     ratings={"general_ui": 5}, impression="хорошо")
    assert len(core.survey_records()) == 1
    assert core.survey_summary(30)["answers"] == 1


def test_user_appears_from_the_first_event_with_a_chat(storage):
    """Пользователь — это вход через телеграм, и он записывается сам."""
    core.usage_track("calc", surface="site", chat_id=102728814)
    core.usage_track("question", surface="site", chat_id=102728814)
    core.usage_track("calc", surface="site", chat_id=0)  # гость: не человек

    users = core.users_registry_summary(30)
    assert users["total"] == 1
    assert users["new_in_window"] == 1
    row = users["recent"][0]
    assert row["chat"] == 102728814
    assert row["kinds"] == {"calc": 1, "question": 1}


def test_user_registry_outlives_the_journal(storage):
    """Реестр не исчезает вместе с журналом."""
    core.usage_track("calc", surface="site", chat_id=9001)
    shutil.rmtree(core._USAGE_DIR)
    assert core.users_registry_summary(30)["total"] == 1


def test_new_and_active_are_different_numbers(storage):
    """«Пришёл впервые» и «заходил» — разные величины, и складывать их нельзя."""
    core.usage_track("calc", surface="site", chat_id=1)
    old = core._users_dir() / "1.json"
    record = json.loads(old.read_text(encoding="utf-8"))
    record["first_seen"] = time.time() - 90 * 86400
    old.write_text(json.dumps(record), encoding="utf-8")

    users = core.users_registry_summary(30)
    assert users["total"] == 1
    assert users["new_in_window"] == 0      # пришёл давно
    assert users["active_in_window"] == 1   # но заходил сейчас


def test_platon_question_carries_the_chat_id():
    """Вопрос Платону писался без chat_id — 74 живых вопроса легли под нулём."""
    source = (ROOT / "main_legacy.py").read_text(encoding="utf-8")
    call = source[source.index('usage_track("question", surface="site"'):]
    assert "chat_id=_web_identity_chat_id(" in call[:400], (
        "вопрос Платону снова пишется без chat_id — автор вопроса потеряется")


def test_finishing_the_survey_twice_says_it_once(monkeypatch):
    """Кнопка «Закончить» после последнего вопроса не должна отвечать дважды.

    Владелец прошёл анкету в боте и получил подряд «Оценок записано: 7» и
    «Ни одной оценки — ничего страшного» (23.08.2026). Второй вызов читал уже
    перезаписанное состояние. Хуже сообщения была бы гонка двух воркеров:
    оценки записались бы дважды, и средние удвоились бы.
    """
    import main as bot

    sent: list[str] = []
    state: dict[str, object] = {"stage": "rate", "index": 99,
                                "ratings": {"general_ui": 5}, "name": "Владелец"}
    written: list[tuple] = []

    monkeypatch.setattr(bot, "_send_message", lambda chat, text, **kw: sent.append(text))
    monkeypatch.setattr(bot, "_feedback_state", lambda chat: dict(state))
    monkeypatch.setattr(bot, "_feedback_remember",
                        lambda chat, patch: state.update(patch))
    monkeypatch.setattr(bot, "_survey_to_core",
                        lambda chat, name, **fields: written.append((chat, fields)))

    bot._feedback_finish(1)
    bot._feedback_finish(1)   # эхо кнопки «Закончить»

    assert len(written) == 1, "оценки записались дважды — средние удвоятся"
    assert len(sent) == 1, sent
    assert "Оценок записано: 1" in sent[0]
