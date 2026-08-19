"""Анкета работает и в боте, а не только на сайте.

На сайте анкета — два десятка пунктов с оценками; в чате столько никто не
заполнит. Но одной оценки мало (владелец, 19.08.2026): «ничего страшного, если
пять раз оценку поставят, как на сайте, и в конце комментарий напишу». Поэтому
в боте вопрос на раздел кнопками и одна строка словами в конце, а данные те же:
всё ложится в общий журнал `survey` теми же ключами, и свод считает сайт и бота
вместе, раздельно по поверхности.

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


def _answer_all(chat_id: int, score: int) -> None:
    for index in range(len(wrapper._feedback_questions())):
        wrapper._feedback_answer(chat_id, index, score)


def test_the_questions_come_from_the_survey_itself():
    """Разделы не переписаны в бота второй раз — они взяты из анкеты."""
    questions = wrapper._feedback_questions()
    assert len(questions) == len(core.FEEDBACK_GROUPS)
    for (title, key, members), group in zip(questions, core.FEEDBACK_GROUPS):
        assert title == group[1]
        # Ключ — ведущий подпункт раздела: свод показывает оценки по нему.
        assert key == group[2][0][0]
        assert key in core.FEEDBACK_ITEMS
        assert group[2][0][1] in members


def test_five_questions_and_a_comment_at_the_end(monkeypatch, tmp_path):
    """Оценок несколько, комментарий один — и он в конце."""
    monkeypatch.setattr(wrapper, "_STATE_DIR", tmp_path)
    sent, tracked = _capture(monkeypatch)
    wrapper._feedback_start(101)
    questions = wrapper._feedback_questions()
    assert len(questions) >= 5, "одной оценки мало"

    first = sent[-1]
    assert questions[0][0] in first[1]
    assert "вопрос 1 из" in first[1]
    rows = first[2]["reply_markup"]["inline_keyboard"]
    assert [b["callback_data"] for b in rows[0]] == [f"fb_r0_{n}" for n in range(1, 6)]
    assert [b["callback_data"] for b in rows[1]] == ["fb_s0", "fb_done"]

    _answer_all(101, 4)
    surveys = [kw for kind, kw in tracked if kind == "survey"]
    assert len(surveys) == 1, "оценки уходят одной записью"
    assert surveys[0]["surface"] == "telegram"
    assert surveys[0]["ratings"] == {key: 4 for _title, key, _m in questions}

    wrapper._feedback_pending_text(101, "хочу график продаж по месяцам")
    comment = [kw for kind, kw in tracked if kind == "survey"][-1]
    assert comment["impression"] == "хочу график продаж по месяцам"
    # Второй записью, без оценок: иначе каждая посчиталась бы дважды.
    assert comment["ratings"] == {}


def test_a_skipped_question_is_not_a_one(monkeypatch, tmp_path):
    """Не пользовался — это отсутствие оценки, а не единица."""
    monkeypatch.setattr(wrapper, "_STATE_DIR", tmp_path)
    _sent, tracked = _capture(monkeypatch)
    questions = wrapper._feedback_questions()
    wrapper._feedback_start(202)
    wrapper._feedback_answer(202, 0, 3)
    for index in range(1, len(questions)):
        wrapper._feedback_answer(202, index, None)
    survey = [kw for kind, kw in tracked if kind == "survey"][-1]
    assert survey["ratings"] == {questions[0][1]: 3}


def test_finishing_early_keeps_what_was_answered(monkeypatch, tmp_path):
    """Кнопка «Закончить» на середине сохраняет уже поставленные оценки."""
    monkeypatch.setattr(wrapper, "_STATE_DIR", tmp_path)
    _sent, tracked = _capture(monkeypatch)
    questions = wrapper._feedback_questions()
    wrapper._feedback_start(303)
    wrapper._feedback_answer(303, 0, 5)
    wrapper._feedback_answer(303, 1, 2)
    wrapper._feedback_finish(303)
    survey = [kw for kind, kw in tracked if kind == "survey"][-1]
    assert survey["ratings"] == {questions[0][1]: 5, questions[1][1]: 2}


def test_an_old_button_does_not_answer_todays_question(monkeypatch, tmp_path):
    """Воркеров два, состояние на диске: кнопка чужого вопроса молчит."""
    monkeypatch.setattr(wrapper, "_STATE_DIR", tmp_path)
    _sent, tracked = _capture(monkeypatch)
    questions = wrapper._feedback_questions()
    wrapper._feedback_start(404)
    wrapper._feedback_answer(404, 0, 5)
    # Повтор той же кнопки не должен ни писать оценку заново, ни двигать анкету.
    wrapper._feedback_answer(404, 0, 1)
    wrapper._feedback_answer(404, 1, 4)
    for index in range(2, len(questions)):
        wrapper._feedback_answer(404, index, None)
    survey = [kw for kind, kw in tracked if kind == "survey"][-1]
    assert survey["ratings"] == {questions[0][1]: 5, questions[1][1]: 4}


def test_the_text_after_the_survey_is_not_read_as_an_address(monkeypatch, tmp_path):
    """«Дорого и непонятно» — комментарий, а не кадастровый номер."""
    monkeypatch.setattr(wrapper, "_STATE_DIR", tmp_path)
    _capture(monkeypatch)
    wrapper._feedback_start(505)
    _answer_all(505, 4)
    assert wrapper._feedback_pending_text(505, "дорого и непонятно") is True
    # Второй раз — уже не анкета: состояние снято.
    assert wrapper._feedback_pending_text(505, "77:01:0001001:1") is False


def test_the_comment_reaches_the_summary(monkeypatch):
    """Свободный текст без раздела раньше не доходил до свода вовсе."""
    events = [{"at": 1_800_000_000.0, "kind": "survey", "surface": "telegram",
               "chat": 77, "ratings": {"general_overall": 4},
               "impression": "верните кнопку пересчёта"}]
    monkeypatch.setattr(core, "usage_events", lambda days=30: events)
    monkeypatch.setattr(core.time, "time", lambda: 1_800_000_100.0)
    data = core.survey_summary(30)
    assert any("верните кнопку пересчёта" == note["text"] for note in data["notes"]), \
        data["notes"]


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
