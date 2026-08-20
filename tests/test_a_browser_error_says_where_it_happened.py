"""Отказ браузера называет место, а не только свои английские слова.

На боевом на iPhone расчёт ТЭП упал строкой «The string did not match the
expected pattern.» — это Safari о себе, и по ней не понять ни что сломалось, ни
на каком шаге (боевая проверка владельца, 18.08.2026). Сервер давно печатает
место ошибки (`_error_location`); страница должна уметь то же самое.

Здесь закреплено: к сообщению добавляется шаг и род ошибки, а чужой язык
помечается как чужой — чтобы человек не искал наших слов там, где их нет.

Запуск: python3 -m pytest tests/test_a_browser_error_says_where_it_happened.py -q
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import main as _wrapper  # noqa: E402

core = _wrapper.core
NODE = shutil.which("node")


def _failure(step: str, name: str, message: str) -> str:
    if not NODE:
        pytest.skip("node недоступен")
    body = core.PAGE[core.PAGE.index("function stepFailure(step, error){"):]
    body = body[:body.index("\n}\n") + 2]
    script = body + (
        f"const error=new Error({json.dumps(message)});"
        f"error.name={json.dumps(name)};"
        f"console.log(stepFailure({json.dumps(step)}, error));")
    done = subprocess.run([NODE, "-e", script], capture_output=True, text=True, check=True)
    return done.stdout.strip()


def test_a_foreign_message_gets_a_place_and_a_mark():
    got = _failure("карточка территории", "TypeError",
                   "The string did not match the expected pattern.")
    assert "The string did not match the expected pattern." in got
    assert "шаг: карточка территории" in got
    assert "TypeError" in got
    assert "сообщение браузера" in got, "чужой язык помечается как чужой"


def test_our_own_message_is_not_marked_as_the_browsers():
    got = _failure("расчёт ТЭП", "Error", "Не удалось определить территорию")
    assert got.startswith("Не удалось определить территорию")
    assert "шаг: расчёт ТЭП" in got
    assert "сообщение браузера" not in got


def test_an_empty_error_still_names_the_step():
    got = _failure("перенос ТЭП в модель", "", "")
    assert "ошибка без описания" in got and "шаг: перенос ТЭП в модель" in got


def test_every_stage_of_the_tep_run_marks_itself():
    """Шаг проставляется перед каждым куском, иначе сообщение назовёт не то
    место, где сломалось."""
    body = core.PAGE[core.PAGE.index("async function obtainCadastralTep("):]
    body = body[:body.index("function stepFailure(")]
    for step in ("сведения по кадастровым номерам", "карточка территории",
                 "штатный калькулятор ГлавАПУ", "чтение таблицы ГлавАПУ",
                 "перенос ТЭП в модель"):
        assert f"tepStep='{step}'" in body, step
    assert "stepFailure(tepStep" in body, "в сообщение уходит именно текущий шаг"
