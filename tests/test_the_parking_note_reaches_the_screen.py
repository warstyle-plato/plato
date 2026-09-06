"""Разница между асфальтом и гаражом видна на экране.

Приобъектная стоянка и паркинг объекта меряются одной единицей — местами — и
стоят рядом в одной группе полей. Однажды их приняли за одно число: норматив
взяли источником гаража, и модель построила 7 770 м² подземного паркинга и
продала 410,0 млн ₽ гостевых мест. Владелец (06.09.2026): «приобъектную нельзя
поставить на кадастр значит нельзя и продать. Это кусок асфальта».

Фразу считает СЕРВЕР, рядом с числами: собранная на странице, она была бы
вторым счётом той же величины и однажды разошлась бы с отчётом.

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
global.document = {getElementById: id => (id === 'objectParkingNote' ? box : null)};
function escapeHtml(s){return String(s).replace(/[&<>"]/g, c =>
  ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]))}
let lastResult = %(result)s;
%(fn)s
renderObjectParkingNote();
console.log(JSON.stringify({html: box.innerHTML}));
"""


def _render(result) -> str:
    script = HARNESS % {"result": json.dumps(result, ensure_ascii=False),
                        "fn": _piece("renderObjectParkingNote")}
    out = subprocess.run(["node", "-e", script], capture_output=True, text=True, timeout=60)
    assert out.returncode == 0, out.stderr[-2000:]
    return json.loads(out.stdout)["html"]


def test_the_asphalt_is_named_asphalt() -> None:
    html = _render({"parking": {"note": (
        "Приобъектных мест по нормативу: 222. Это стоянка вдоль проезда — на "
        "кадастр не ставится и не продаётся, её стоимость внутри "
        "благоустройства. Собственный паркинг объектов не задан.")}})
    assert "не продаётся" in html
    assert "222" in html


def test_the_garage_is_named_with_its_places() -> None:
    html = _render({"parking": {"note": (
        "Приобъектных мест по нормативу: 222. Это стоянка вдоль проезда. "
        "Собственный паркинг объектов — 100 мест, они продаются машино-местами: "
        "Офисы — 80 подземных, 20 на первых этажах.")}})
    assert "80 подземных" in html and "20 на первых этажах" in html


def test_nothing_is_drawn_before_the_first_calculation() -> None:
    """Пустая плашка честнее выдуманной: расчёта ещё не было."""
    assert _render(None) == ""
    assert _render({"parking": {}}) == ""


def test_the_screen_shows_the_sentence_and_does_not_recount_it() -> None:
    """Второй счёт той же величины однажды разошёлся бы с отчётом.

    Утверждение здесь именно такое: отрисовка берёт готовую фразу и НЕ
    прикасается к числам, из которых она сложена. Запрет на знак арифметики
    был бы проверкой не о том: она падала на «//» в комментарии, то есть на
    верном коде.
    """
    body = _piece("renderObjectParkingNote")
    for field in ("required_total", "own", "rows", "own_units", "area_per_space_sqm"):
        assert f"parking.{field}" not in body, (
            f"отрисовка полезла в число: parking.{field}")
    assert "note" in body


def test_the_plate_does_not_pretend_to_check_one_against_the_other() -> None:
    """Сверять норматив с гаражом нельзя: это ответы на разные вопросы.

    «Сходится» между асфальтом и гаражом значило бы, что мы считаем норматив
    планом стройки — ровно то заблуждение, из которого выросли 410 млн ₽
    несуществующей выручки.
    """
    body = _piece("renderObjectParkingNote")
    assert "check" not in body
