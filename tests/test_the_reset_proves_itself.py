"""Сброс проверяет сам себя и называет уцелевшее.

«При сбросе проекта до сих пор не сбрасываются ТЭПы, полного обнуления нет всех
вкладок» (владелец, 27.08.2026) — и это спор, который нельзя выиграть памятью:
обе стороны правы про разные поля. Молчание здесь и есть причина спора.

Поэтому после сброса состояние сверяется с тем, каким оно обязано быть, и
уцелевшее НАЗЫВАЕТСЯ. Пусто — значит пусто, а не «кажется, сработало».

Запуск: python3 -m pytest tests/test_the_reset_proves_itself.py -q
"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PAGE = (ROOT / "main_legacy.py").read_text(encoding="utf-8")


def _body(name: str, until: str) -> str:
    start = PAGE.index(name)
    return PAGE[start:PAGE.index(until, start)]


def test_the_wanted_state_is_declared_once() -> None:
    """Пока умолчаний было два, проверка честно жаловалась на поля, которые
    сброс сам же и ставит."""
    assert "function resetInputsWanted()" in PAGE
    reset = _body("function resetAll(){", "\n// Сброс, который проверяет сам себя")
    assert "inputs=resetInputsWanted()" in reset
    for gone in ("inputs.project_class='comfort'", "inputs.scenario_cost_multiplier=1"):
        assert gone not in reset, "вторая копия умолчаний вернулась в сброс"

    check = _body("function resetLeftovers(){", "\n}")
    assert "resetInputsWanted()" in check, "проверка сверяется с тем же выражением"


def test_the_leftovers_are_named_not_hinted() -> None:
    check = _body("function resetLeftovers(){", "\n}")
    assert "вводная «" in check and "ТЭП «" in check
    assert "лишняя вводная «" in check, "поле, которого в умолчаниях нет, — тоже след"

    caller = _body("function resetProject(){", "\nfunction resetTepControls(")
    assert "resetAll()" in caller and "left" in caller
    assert "Сброс оставил" in caller, "уцелевшее показывается человеку"


def test_a_late_calculation_does_not_refill_the_report() -> None:
    """Сброс перерисовывает поля, их onchange зовёт расчёт, а расчёт
    асинхронный: он возвращается уже после обнуления и заполняет отчёт заново.
    На сайте это скрыто перезагрузкой, в мини-приложении её нет."""
    assert "const startedAtReset=resetRun" in PAGE
    assert "if(startedAtReset!==resetRun){" in PAGE
    guard = PAGE[PAGE.index("if(startedAtReset!==resetRun){"):]
    guard = guard[:guard.index("\n }")]
    assert "lastResult=null" in guard and "blankResultSurfaces()" in guard


def test_the_reset_still_starts_the_page_over_outside_telegram() -> None:
    """У перезагрузки нет списка полей, и обойти его нечем — это и есть самый
    полный сброс. Исключение только для мини-приложения: бот открыл бы окно
    заново с той же сессией."""
    caller = _body("function resetProject(){", "\nfunction resetTepControls(")
    assert "location.replace(location.pathname)" in caller
    assert "isTelegramWebApp()" in caller
    assert "localStorage.removeItem('plato_v04')" in caller
