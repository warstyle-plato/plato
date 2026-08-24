"""Выкатка не уводит прод на выпуск назад молча.

Сборка образа из `main` упала дважды подряд на проверке версии, тег `prod`
остался на прошлом выпуске, и очередная выкатка увела прод на релиз назад — с
экрана пропало всё, что там было (владелец, 23.08.2026). Проба этого не ловила
и не могла: она спрашивает «жив ли новый образ», а не «новее ли он того, что
работает».

Осознанный откат остаётся возможным — он и нужен, когда новое сломалось, — но
теперь его надо назвать вслух: `ALLOW_DOWNGRADE=1`.

Запуск: python3 -m pytest tests/test_deploy_refuses_to_step_back.py -q
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parent.parent / "deploy-developaid.sh"


def source() -> str:
    return SCRIPT.read_text(encoding="utf-8")


def function_source(name: str) -> str:
    body = source()
    start = body.index(f"{name}() {{")
    end = body.index("\n}", start)
    return body[start:end + 2]


def order(new: str, live: str) -> str:
    shell = shutil.which("bash")
    if not shell:
        pytest.skip("bash недоступен")
    program = f'{function_source("version_order")}\nversion_order "$1" "$2"\n'
    done = subprocess.run([shell, "-c", program, "sh", new, live],
                          capture_output=True, text=True, timeout=60)
    assert done.returncode == 0, done.stderr[:400]
    return done.stdout.strip()


def test_a_lower_release_is_older() -> None:
    assert order("0.19.52", "0.19.53") == "older"


def test_a_higher_release_is_newer() -> None:
    assert order("0.19.62", "0.19.53") == "newer"


def test_the_same_release_is_the_same() -> None:
    assert order("0.19.53", "0.19.53") == "same"


def test_the_comparison_is_by_numbers_not_by_letters() -> None:
    """Строкой «0.19.9» больше «0.19.10» — и откат прошёл бы за повышение."""
    assert order("0.19.9", "0.19.10") == "older"
    assert order("0.19.100", "0.19.99") == "newer"


def test_an_unreadable_version_does_not_pretend_to_know() -> None:
    """Не смогли сравнить — так и говорим, а не выдаём за «новее»."""
    assert order("непонятно", "0.19.53") == "unknown"


def test_the_script_refuses_a_step_back_by_default() -> None:
    body = source()
    assert 'case "$(version_order "$NEW_VERSION" "$LIVE_VERSION")"' in body
    step_back = body[body.index("    older)"):]
    step_back = step_back[:step_back.index("      ;;")]
    assert "ОТКАЗ" in step_back
    assert "exit 1" in step_back
    assert "прод не тронут" in step_back


def test_a_deliberate_rollback_is_still_possible() -> None:
    body = source()
    assert 'ALLOW_DOWNGRADE:-0' in body, "осознанный откат обязан остаться"
    assert "ALLOW_DOWNGRADE=1 sh" in body, "и способ назван прямо в отказе"


def test_the_running_version_is_asked_of_the_container_not_of_the_tag() -> None:
    """Тег переставляют, а версию приложение объявляет о себе само."""
    body = function_source("running_version")
    assert "/health" in body
    assert "docker port" in body


def test_the_check_stands_after_the_probe_and_before_the_swap() -> None:
    body = source()
    probe = body.index('say "проба пройдена')
    guard = body.index("NEW_VERSION=")
    swap = body.index("# --- замена рабочего контейнера")
    assert probe < guard < swap, "проверять надо до подмены, а не после"
