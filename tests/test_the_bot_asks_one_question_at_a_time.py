"""Бот спрашивает по документу по одному вопросу, а не десятью сразу.

«Бот выплюнул 10 вопросов в одном сообщении, а не один за одним» (владелец,
27.08.2026). В чате разговор, а не анкета: списком из десяти вопросов человек
не знает, на какой отвечает, и бот не знает тоже — ответ не к чему привязать.

Механизм для этого у бота уже был: пошаговый диалог с `step` и сохранением
между сообщениями. Второго не заводим.

Запуск: python3 -m pytest tests/test_the_bot_asks_one_question_at_a_time.py -q
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import main_legacy as engine  # noqa: E402


@pytest.fixture()
def bot(monkeypatch, tmp_path):
    sent: list[dict] = []

    def fake_send(chat_id, text, reply_markup=None, **_):
        sent.append({"chat_id": chat_id, "text": text, "markup": reply_markup})
        return {"ok": True}

    monkeypatch.setattr(engine, "_telegram_send_message", fake_send)
    monkeypatch.setattr(engine, "_PLATO_STAGE_DIR", tmp_path)
    engine._telegram_dialog_clear(777)
    return sent


def _questions(count: int) -> list[dict]:
    return [{"question": f"Вопрос {n}", "options": ["да", "нет"] if n == 1 else []}
            for n in range(1, count + 1)]


def test_ten_questions_go_out_one_by_one(bot):
    dialog = {"step": "await_intake_answer", "intake": {
        "filename": "тизер.pdf", "questions": _questions(10), "answers": [], "index": 0}}
    engine._telegram_dialog_save(777, dialog)
    engine._telegram_intake_ask_next(777, dialog)

    assert len(bot) == 1, "вопросы уходят по одному"
    assert "Вопрос 1 из 10" in bot[0]["text"]
    assert "Вопрос 2" not in bot[0]["text"]

    engine._telegram_handle_dialog_text(777, "да")
    assert "Вопрос 2 из 10" in bot[-1]["text"]
    assert len(bot) == 2


def test_the_answer_is_tied_to_its_question(bot):
    dialog = {"step": "await_intake_answer", "intake": {
        "filename": "тизер.pdf", "questions": _questions(2), "answers": [], "index": 0}}
    engine._telegram_dialog_save(777, dialog)
    engine._telegram_handle_dialog_text(777, "12 000")
    engine._telegram_handle_dialog_text(777, "аренда")

    said = bot[-1]["text"]
    assert "Вопрос 1" in said and "12 000" in said
    assert "Вопрос 2" in said and "аренда" in said


def test_the_answers_survive_a_missing_button(bot):
    """Ссылка мини-приложения собирается по токену бота; без него кнопки нет.
    Ронять из-за неё разбор нельзя — человек потерял бы и свои ответы."""
    dialog = {"step": "await_intake_answer", "intake": {
        "filename": "т.pdf", "questions": _questions(1), "answers": [], "index": 0}}
    engine._telegram_dialog_save(777, dialog)
    engine._telegram_handle_dialog_text(777, "12 000")
    assert "12 000" in bot[-1]["text"], "итог доходит и без кнопки"


def test_a_skip_is_an_answer_and_says_so(bot):
    dialog = {"step": "await_intake_answer", "intake": {
        "filename": "т.pdf", "questions": _questions(1), "answers": [], "index": 0}}
    engine._telegram_dialog_save(777, dialog)
    engine._telegram_handle_dialog_text(777, "-")
    assert "пропущено" in bot[-1]["text"], "пропуск назван, а не показан пустотой"


def test_stopping_keeps_what_was_already_answered(bot):
    """Прекратить разговор — законный ответ, а не сбой."""
    dialog = {"step": "await_intake_answer", "intake": {
        "filename": "т.pdf", "questions": _questions(5), "answers": [], "index": 0}}
    engine._telegram_dialog_save(777, dialog)
    engine._telegram_handle_dialog_text(777, "42")
    engine._telegram_handle_dialog_text(777, "стоп")
    said = bot[-1]["text"]
    assert "42" in said, "отвеченное до остановки не выбрасывается"
    assert "Вопрос 3" not in said


def test_the_dialogue_survives_the_other_worker(bot, tmp_path):
    """Воркеров два, память у них раздельная: следующее сообщение попадает в
    другой процесс, где разговора не было."""
    dialog = {"step": "await_intake_answer", "intake": {
        "filename": "т.pdf", "questions": _questions(3), "answers": [], "index": 0}}
    engine._telegram_dialog_save(777, dialog)
    # Второй воркер: своей памяти о разговоре у него нет.
    engine._TELEGRAM_DIALOGS.pop(777, None)
    restored = engine._telegram_dialog_get(777)
    assert restored and restored["step"] == "await_intake_answer"
    assert len(restored["intake"]["questions"]) == 3


def test_the_intake_message_no_longer_lists_the_questions():
    """Список вопросов из карточки разбора убран — они уходят очередью."""
    source = (ROOT / "main_legacy.py").read_text(encoding="utf-8")
    body = source[source.index("def _telegram_handle_intake_document("):]
    body = body[:body.index("\ndef _telegram_open_model_button(")]
    assert "Чего в документе нет — нужен ваш ответ" not in body
    assert "_telegram_intake_ask_next(" in body
