"""Анкета работает и в боте, а не только на сайте.

На сайте анкета — два десятка пунктов с оценками; в чате столько никто не
заполнит (владелец, 19.08.2026). Поэтому форма другая — одна оценка кнопкой и
одна строка словами, — а данные те же: всё ложится в общий журнал `survey` теми
же ключами, и свод считает сайт и бота вместе, раздельно по поверхности.

Запуск: python3 -m pytest tests/test_feedback_in_the_bot.py -q
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import main as wrapper  # noqa: E402

core = wrapper.core


def _capture(monkeypatch) -> tuple[list, list]:
    sent: list = []
    tracked: list = []
    monkeypatch.setattr(wrapper, "_send_message",
                        lambda chat_id, text, **kw: sent.append((chat_id, text, kw)))
    monkeypatch.setattr(core, "usage_track",
                        lambda kind, **kw: tracked.append((kind, kw)))
    return sent, tracked


def test_the_score_alone_is_a_complete_answer(monkeypatch, tmp_path):
    """Пятёрка кнопкой — уже ответ: писать ничего не обязательно."""
    monkeypatch.setattr(wrapper, "_STATE_DIR", tmp_path)
    sent, tracked = _capture(monkeypatch)
    wrapper._feedback_start(101)
    assert "Оцените DevelopAid" in sent[0][1]
    buttons = sent[0][2]["reply_markup"]["inline_keyboard"][0]
    assert [b["callback_data"] for b in buttons] == [f"fb_score_{n}" for n in range(1, 6)]

    wrapper._feedback_score(101, 5)
    surveys = [kw for kind, kw in tracked if kind == "survey"]
    assert surveys, "оценка не попала в журнал"
    assert surveys[0]["surface"] == "telegram"
    assert surveys[0]["ratings"] == {"general_overall": 5}


def test_a_low_score_asks_what_went_wrong(monkeypatch, tmp_path):
    """Оценка ниже четвёрки — вопрос про раздел, а не молчание."""
    monkeypatch.setattr(wrapper, "_STATE_DIR", tmp_path)
    sent, tracked = _capture(monkeypatch)
    wrapper._feedback_start(202)
    wrapper._feedback_score(202, 2)
    areas = sent[-1][2]["reply_markup"]["inline_keyboard"]
    keys = [row[0]["callback_data"] for row in areas]
    assert "fb_area_report" in keys, keys
    assert not [kw for kind, kw in tracked if kind == "survey"], (
        "низкая оценка записывается вместе с причиной, а не до неё")

    wrapper._feedback_area(202, "report")
    wrapper._feedback_pending_text(202, "не верю числам")
    survey = [kw for kind, kw in tracked if kind == "survey"][-1]
    assert survey["ratings"] == {"general_overall": 2}
    assert survey["problems"] == {"report": "не верю числам"}


def test_the_text_after_the_score_is_not_read_as_an_address(monkeypatch, tmp_path):
    """«Дорого и непонятно» — комментарий, а не кадастровый номер."""
    monkeypatch.setattr(wrapper, "_STATE_DIR", tmp_path)
    _capture(monkeypatch)
    wrapper._feedback_start(303)
    wrapper._feedback_score(303, 4)
    assert wrapper._feedback_pending_text(303, "дорого и непонятно") is True
    # Второй раз — уже не анкета: состояние снято.
    assert wrapper._feedback_pending_text(303, "77:01:0001001:1") is False


def test_the_question_is_declared_once():
    """Общая оценка — пункт анкеты, а не выдумка бота."""
    assert "general_overall" in core.FEEDBACK_ITEMS
    commands = [item["command"] for item in core.TELEGRAM_BOT_COMMANDS]
    assert "feedback" in commands, commands


def test_the_button_stands_in_the_menu():
    """Кнопка живёт в меню помощи — том же, что и остальные решения.

    Читаем исходник обёртки, а не функцию: к моменту импорта её уже обернул
    модуль МПТ, и `inspect.getsource` вернёт обёртку, а не тело меню.
    """
    source = (Path(__file__).resolve().parent.parent / "main.py").read_text(encoding="utf-8")
    menu = source[source.index("def _help_markup("):]
    menu = menu[:menu.index("def _send_help(")]
    assert "fb_start" in menu
    assert "Оценить DevelopAid" in menu
