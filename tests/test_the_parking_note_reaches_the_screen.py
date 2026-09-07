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


def _executable(body: str) -> str:
    """Оставить от функции то, что ИСПОЛНЯЕТСЯ: без комментариев и без текста.

    Косая черта живёт в разметке (`</div>`) и делением там не является, поэтому
    запрет арифметики поверх сырого текста падал бы на верном коде. Текст строк
    и шаблонов выбрасывается, а подстановки `${…}` остаются: спрятать деление
    внутри шаблона иначе было бы можно, и запрет ничего не значил бы.
    """
    src = "\n".join(line.split("//")[0] for line in body.splitlines())
    out, i, quote = [], 0, ""
    while i < len(src):
        ch = src[i]
        if quote:
            if ch == "\\":
                i += 2
                continue
            if ch == quote:
                quote = ""
            elif quote == "`" and src.startswith("${", i):
                depth, j = 1, i + 2
                while j < len(src) and depth:
                    depth += (src[j] == "{") - (src[j] == "}")
                    j += 1
                out.append(src[i + 2:j - 1])
                i = j
                continue
            i += 1
            continue
        if ch in "\"'`":
            quote = ch
        else:
            out.append(ch)
        i += 1
    return "".join(out)


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


def test_the_screen_shows_the_numbers_and_does_not_recount_them() -> None:
    """Второй счёт той же величины однажды разошёлся бы с отчётом.

    Прежняя редакция запрещала строку «parking.own» — и была обойдена в тот же
    день, когда норму понадобилось поставить у поля объекта: код читает
    `(…||{}).own`, подстроки в нём нет, проверка зелена, а утверждение не
    проверено вовсе. Запрещать надо МЕСТО, а не слово. Место здесь одно:
    арифметики на экране нет — числа печатаются такими, какими их посчитал
    движок, а сводные величины (`required_total`, `rows`, `own_units`,
    `area_per_space_sqm`) отрисовка не трогает и не пересобирает.
    """
    for name in ("renderObjectParkingNote", "objectParkingFieldNote"):
        code = _executable(_piece(name))
        for sign in ("*", "/", "Math."):
            assert sign not in code, f"{name}: на экране считают ({sign})"
        for field in ("required_total", "own_units", "area_per_space_sqm"):
            assert field not in code, f"{name}: отрисовка полезла в свод {field}"


def test_the_norm_stands_at_the_field_the_hand_edits() -> None:
    """«А где посмотреть сколько по нормативу то этому?» (владелец, 07.09.2026).

    Число жило одной плашкой под ПОСЛЕДНИМ полем группы — «мест на первых
    этажах» у ФОКа. Смотришь на офисы — ответ через два экрана вниз, а на
    телефоне его не найти вовсе. Норма стоит у того поля, которое человек
    правит, и приставку поля несёт сам объект: второй карты «какое поле у
    какого объекта» на странице нет.
    """
    cells = {"parkNorm_offices": None, "parkNorm_retail": None, "objectParkingNote": None}
    result = {"parking": {"note": "Свод.", "own": [
        {"prefix": "offices", "tep_key": "offices", "enabled": True,
         "by_norm": True, "required_spaces": 2956, "units": 2956},
        {"prefix": "retail", "tep_key": "standalone_retail", "enabled": True,
         "by_norm": False, "required_spaces": 310, "units": 40},
    ]}}
    script = """
const cells = {parkNorm_offices:{textContent:""}, parkNorm_retail:{textContent:""},
               objectParkingNote:{innerHTML:""}};
global.document = {getElementById: id => cells[id] || null};
function escapeHtml(s){return String(s)}
const num = v => String(v);
let lastResult = %(result)s;
%(a)s
%(b)s
renderObjectParkingNote();
console.log(JSON.stringify({offices: cells.parkNorm_offices.textContent,
                            retail: cells.parkNorm_retail.textContent}));
""" % {"result": json.dumps(result, ensure_ascii=False),
       "a": _piece("objectParkingFieldNote"),
       "b": _piece("renderObjectParkingNote")}
    out = subprocess.run(["node", "-e", script], capture_output=True, text=True, timeout=60)
    assert out.returncode == 0, out.stderr[-2000:]
    seen = json.loads(out.stdout)
    assert "2956" in seen["offices"] and "норматив" in seen["offices"].lower()
    # Перебитая руками норма называет ОБА числа: одно без другого не сравнить.
    assert "310" in seen["retail"] and "40" in seen["retail"]


def test_a_field_says_nothing_before_the_first_calculation() -> None:
    """Прежняя норма под новыми метрами читается как посчитанная."""
    script = """
const cell = {textContent:"дырка"};
global.document = {getElementById: id => (id === 'parkNorm_offices' ? cell : null)};
function escapeHtml(s){return String(s)}
const num = v => String(v);
let lastResult = null;
%(a)s
%(b)s
renderObjectParkingNote();
console.log(JSON.stringify({left: cell.textContent}));
""" % {"a": _piece("objectParkingFieldNote"), "b": _piece("renderObjectParkingNote")}
    out = subprocess.run(["node", "-e", script], capture_output=True, text=True, timeout=60)
    assert out.returncode == 0, out.stderr[-2000:]
    assert json.loads(out.stdout)["left"] == "дырка"


def test_the_field_hint_does_not_promise_an_empty_box() -> None:
    """Поле показывает 0, а подсказка обещала «пусто».

    Условие в движке — `under + over == 0`, то есть ноль и есть «не задано»;
    пустым поле не бывает вовсе. Обещание состояния, которого не существует,
    читается как несработавший расчёт — тот же класс, что оговорка,
    устаревшая молча.
    """
    hints = [f[2] for group in core.FIELD_GROUPS for f in group[1]
             if str(f[0]).endswith("_parking_under_spaces")
             or str(f[0]).endswith("_parking_over_spaces")]
    assert hints, "полей паркинга объекта на экране нет"
    for hint in hints:
        assert "пусто" not in hint, hint
        assert "0" in hint and "норматив" in hint, hint


def test_the_plate_does_not_pretend_to_check_one_against_the_other() -> None:
    """Сверять норматив с гаражом нельзя: это ответы на разные вопросы.

    «Сходится» между асфальтом и гаражом значило бы, что мы считаем норматив
    планом стройки — ровно то заблуждение, из которого выросли 410 млн ₽
    несуществующей выручки.
    """
    body = _piece("renderObjectParkingNote")
    assert "check" not in body
