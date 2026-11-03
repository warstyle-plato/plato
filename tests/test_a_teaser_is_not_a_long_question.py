"""Тизер отклонялся всегда, и человек читал претензию к себе.

«Платон на сайте не принимает тизеры, пишет что слишком большой запрос»
(владелец, 04.09.2026). Дело было не в документе: предел в 4 000 знаков
поставлен на СВОБОДНЫЙ ВОПРОС человека, а разбор документа собирает задание
сам — и одна его шапка занимает 2 516 знаков. На документ оставалось 1 484,
меньше одной страницы делового PDF, поэтому любой настоящий тизер упирался в
предел, а отказ звучал как «Вопрос слишком длинный».

Это второй случай одного правила: бюджет считают на ВСЁ сообщение, а не на его
середину. Только здесь сообщение собираем мы, и мерить его человеческим
пределом нельзя.

Запуск: python3 -m pytest tests/test_a_teaser_is_not_a_long_question.py -q
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import document_intake  # noqa: E402
import main_legacy as core  # noqa: E402

TEASER = {"filename": "тизер.pdf", "pages": 7, "text": "Т" * 30_000}


def test_the_scaffolding_alone_used_to_eat_the_whole_budget() -> None:
    """Мера поломки: шапка задания больше половины прежнего предела."""
    empty = document_intake.intake_prompt({"filename": "т.pdf", "pages": 1, "text": ""})
    assert len(empty) > core._PLATO_QUESTION_LIMIT / 2, (
        "шапка задания стала короткой — измерение поломки надо переписать")
    assert core._PLATO_QUESTION_LIMIT - len(empty) < 2_500, (
        "на документ оставалось меньше страницы делового PDF — ради этого правка")


def test_a_real_teaser_fits_the_document_limit() -> None:
    """Настоящий тизер обязан проходить, а не отклоняться по построению."""
    prompt = document_intake.intake_prompt(TEASER)
    limit = core._PLATO_MESSAGE_LIMITS["document_intake"]
    assert len(prompt) <= limit, "задание разбора не помещается в свой предел"
    assert len(prompt) > core._PLATO_QUESTION_LIMIT, (
        "пример слишком мал — прежний предел он бы и так прошёл")


def test_the_free_question_keeps_its_own_limit() -> None:
    """Предел человеческого вопроса на месте: правка не открывает шлюз всем."""
    assert core._PLATO_QUESTION_LIMIT == 4000
    assert core._PLATO_MESSAGE_LIMITS.get("") is None


def test_a_document_longer_than_the_budget_says_so() -> None:
    """Обрезка называется вслух: молча отрезанный хвост читается как «этого нет»."""
    huge = {"filename": "т.pdf", "pages": 200, "text": "Я" * 200_000}
    portion = document_intake.intake_text(huge)
    assert portion["trimmed"] is True
    assert portion["read_chars"] == document_intake.DOCUMENT_TEXT_BUDGET
    assert portion["total_chars"] == 200_000
    prompt = document_intake.intake_prompt(huge)
    assert "прочитан не целиком" in prompt, "модели не сказано, что документ обрезан"
    assert "200000" in prompt.replace(" ", ""), "не названо, сколько знаков в документе"


def test_a_short_document_is_not_called_trimmed() -> None:
    portion = document_intake.intake_text({"text": "коротко"})
    assert portion["trimmed"] is False
    assert "прочитан не целиком" not in document_intake.intake_prompt({"text": "коротко"})


def test_the_refusal_names_the_numbers() -> None:
    """Отказ без чисел не отличить от претензии к человеку."""
    import inspect

    source = inspect.getsource(core._plato_chat_launch)
    assert "при пределе" in source, "в отказе не назван предел"
    assert "_PLATO_MESSAGE_LIMITS" in source, "предел не зависит от сценария"
