"""Контроль суммы приобъектного паркинга виден на экране.

Владелец, 05.09.2026: «При выборе парковок надо сделать выбор, что идет в
надземные и подземные с контролем суммы по обязательствам согласном нормам».
Считает контроль СЕРВЕР, рядом с числами: собранный на странице, он был бы
вторым счётом той же величины и однажды разошёлся бы с отчётом.

Проверяется отрисовка, а не наличие строки в файле: искомый текст присутствует
и в сломанной странице. Функция берётся по своим скобкам — контракт, а не
соседняя строка.

Запуск: python3 -m pytest tests/test_the_parking_check_reaches_the_screen.py -q
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import main_legacy as core  # noqa: E402

PAGE = core.PAGE


def _piece(name: str) -> str:
    start = PAGE.index(f"function {name}(")
    depth, i = 0, PAGE.index("{", start)
    while True:
        if PAGE[i] == "{":
            depth += 1
        elif PAGE[i] == "}":
            depth -= 1
            if depth == 0:
                return PAGE[start:i + 1]
        i += 1


HARNESS = """
const box = {innerHTML: ""};
global.document = {getElementById: id => (id === 'objectParkingCheck' ? box : null)};
function escapeHtml(s){return String(s).replace(/[&<>"]/g, c =>
  ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]))}
let lastResult = %(result)s;
%(fn)s
renderObjectParkingCheck();
console.log(JSON.stringify({html: box.innerHTML}));
"""


def _render(result) -> str:
    script = HARNESS % {"result": json.dumps(result, ensure_ascii=False),
                        "fn": _piece("renderObjectParkingCheck")}
    out = subprocess.run(["node", "-e", script], capture_output=True, text=True, timeout=60)
    assert out.returncode == 0, out.stderr[-2000:]
    return json.loads(out.stdout)["html"]


def test_a_matching_placement_is_stated_plainly() -> None:
    html = _render({"parking": {"check": {
        "state": "ok", "text": "Сходится с нормативом: 222 мест из 222."}}})
    assert "222 мест из 222" in html
    assert "warning" not in html, "сошедшееся не красят тревогой"


def test_a_gap_is_named_with_its_number() -> None:
    html = _render({"parking": {"check": {
        "state": "mismatch",
        "text": "Не сходится с нормативом — Офисы: 10 против 80 (-70)."}}})
    assert "10 против 80" in html
    assert "warning" in html, "расхождение обязано быть видно тоном, а не только словами"


def test_an_uncounted_norm_is_its_own_answer() -> None:
    """«Сходится» на непосчитанном нормативе читается как пройденная проверка."""
    html = _render({"parking": {"check": {
        "state": "unknown", "text": "Сверить не с чем: К1 не задан."}}})
    assert "Сверить не с чем" in html
    assert "warning" in html


def test_nothing_is_drawn_before_the_first_calculation() -> None:
    """Пустая плашка честнее выдуманной: расчёта ещё не было."""
    assert _render(None) == ""
    assert _render({"parking": {}}) == ""


def test_the_screen_shows_the_verdict_and_does_not_recount_it() -> None:
    """Второй счёт той же величины однажды разошёлся бы с отчётом.

    Утверждение здесь именно такое: отрисовка читает готовый вердикт — его
    текст и состояние — и НЕ прикасается к числам, из которых он сложен.
    Запрет на знак арифметики был бы проверкой не о том: она падала на «//»
    в комментарии, то есть на верном коде.
    """
    body = _piece("renderObjectParkingCheck")
    for field in ("required", "placed", "rows", "under", "over", "delta"):
        assert f"check.{field}" not in body, (
            f"отрисовка полезла в число вердикта: check.{field}")
    assert "check.text" in body and "check.state" in body
