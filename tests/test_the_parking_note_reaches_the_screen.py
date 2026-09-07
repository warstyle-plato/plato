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


def _render_fields(result):
    """Отрисовать подписи и поля так, как их рисует страница."""
    script = """
const cells = {parkNorm_offices:{textContent:""}, parkNorm_retail:{textContent:""},
               objectParkingNote:{innerHTML:""},
               f_offices_parking_under_spaces:{value:null},
               f_offices_parking_over_spaces:{value:null}};
global.document = {getElementById: id => cells[id] || null, activeElement: null};
function escapeHtml(s){return String(s)}
const num = v => String(v);
let inputs = {};
let lastResult = %(result)s;
%(a)s
%(b)s
renderObjectParkingNote();
console.log(JSON.stringify({
  note_offices: cells.parkNorm_offices.textContent,
  note_retail: cells.parkNorm_retail.textContent,
  field_offices: cells.f_offices_parking_under_spaces.value,
  field_retail: (cells.f_retail_parking_under_spaces||{value:null}).value,
  inputs}));
""" % {"result": json.dumps(result, ensure_ascii=False),
       "a": _piece("objectParkingFieldNote"),
       "b": _piece("renderObjectParkingNote")}
    out = subprocess.run(["node", "-e", script], capture_output=True, text=True, timeout=60)
    assert out.returncode == 0, out.stderr[-2000:]
    return json.loads(out.stdout)

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


def test_the_norm_fills_the_field_and_the_note_says_whose_it_is() -> None:
    """«А почему нельзя туда где я скрин прислал стоит пусто ставить этот
    норматив» (владелец, 07.09.2026).

    Можно — и норма пишется прямо в поле объекта. Прежде число жило одной
    плашкой под ПОСЛЕДНИМ полем группы, «мест на первых этажах» у ФОКа:
    смотришь на офисы — ответ через два экрана вниз, а на телефоне не найти
    вовсе. Подпись при этом число НЕ повторяет: одно и то же дважды подряд
    перестают читать — она отвечает на другое, чьё оно и что будет, если поле
    тронуть.
    """
    result = {"parking": {"note": "Свод.", "own": [
        {"prefix": "offices", "tep_key": "offices", "enabled": True,
         "by_norm": True, "required_spaces": 2956, "units": 2956,
         "under_spaces": 2956, "over_spaces": 0},
        {"prefix": "retail", "tep_key": "standalone_retail", "enabled": True,
         "by_norm": False, "required_spaces": 310, "units": 40,
         "under_spaces": 40, "over_spaces": 0},
    ]}}
    seen = _render_fields(result)
    assert seen["field_offices"] == 2956, "норма не доехала до самого поля"
    assert seen["inputs"]["offices_parking_under_spaces"] == 2956
    assert "норматив" in seen["note_offices"].lower()
    assert "2956" not in seen["note_offices"], "число сказано дважды подряд"
    # Перебитое руками поле норма не трогает, а подпись называет ОБА числа:
    # одно без другого не сравнить.
    assert seen["field_retail"] is None, "норма затёрла вписанное руками"
    assert "310" in seen["note_retail"] and "руками" in seen["note_retail"]


def test_the_hand_keeps_the_field_and_the_norm_follows_the_tep() -> None:
    """Заполненное поле обязано СЛЕДОВАТЬ за базой, пока его не тронули.

    Иначе это ровно та ловушка, что уже стоила разбора со ставками классов:
    сохранённое значение сильнее базы, и правка базы под ним не видна. Правь
    ГНС офисов — а мест остаётся вчерашнее число, и на экране оно выглядит
    посчитанным. Проверяется движком, а не экраном: решение принимает он.
    """
    import copy

    def run(gba, **over):
        x = dict(core.DEFAULT_INPUTS)
        x.update({"offices_enabled": True, "offices_gba_sqm": gba})
        x.update(over)
        t = copy.deepcopy(core.TEP_DEFAULT)
        t.setdefault("offices", {}).update(
            {"label": "Офисы", "gns": gba, "useful": gba * 0.55,
             "saleable": gba * 0.47, "units": 0.0})
        got = core.apply_object_parking(x, t)
        row = [i for i in got["own"] if i["tep_key"] == "offices"][0]
        return row["under_spaces"], row["by_norm"]

    filled, by_norm = run(186180.0, _parking_by_hand=[],
                          offices_parking_under_spaces=2956)
    assert (filled, by_norm) == (2956, True)
    grew, by_norm = run(200000.0, _parking_by_hand=[],
                        offices_parking_under_spaces=2956)
    assert by_norm and grew > filled, "поле замерло на вчерашнем числе"
    # Тронутое руками норма не перебивает — включая ноль. Прежде сказать
    # «гаража у объекта нет» было нечем вовсе: ноль читался как «не задано».
    assert run(200000.0, _parking_by_hand=["offices"],
               offices_parking_under_spaces=40) == (40, False)
    assert run(200000.0, _parking_by_hand=["offices"],
               offices_parking_under_spaces=0) == (0, False)
    # Проект, сохранённый до правки, списка не несёт — его числа человеческие.
    assert run(200000.0, offices_parking_under_spaces=40) == (40, False)


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
    """Поле показывает число, а подсказка обещала «пусто».

    Пустым оно не бывает вовсе: до правки там стоял 0, теперь — норматив.
    Обещание состояния, которого не существует, читается как несработавший
    расчёт — тот же класс, что оговорка, устаревшая молча.
    """
    hints = [f[2] for group in core.FIELD_GROUPS for f in group[1]
             if str(f[0]).endswith("_parking_under_spaces")
             or str(f[0]).endswith("_parking_over_spaces")]
    assert hints, "полей паркинга объекта на экране нет"
    for hint in hints:
        assert "пусто" not in hint, hint
        assert "норматив" in hint and "перебива" in hint, hint


def test_the_screen_does_not_claim_the_norm_and_the_garage_agree() -> None:
    """Сверять норматив с гаражом нельзя: это ответы на разные вопросы.

    Норма отвечает «сколько положено», гараж — «сколько строим и продаём», и
    «сходится» между ними значило бы, что мы считаем норматив планом стройки —
    ровно то заблуждение, из которого выросли 410 млн ₽ несуществующей выручки.
    Норма теперь ЗАПОЛНЯЕТ поле, и соблазн сверки только вырос: заполненное
    ею поле рядом с ней самой выглядит как проверка.

    Прежняя редакция запрещала слово «check» — то есть проверяла написание, а
    не утверждение. Держится здесь само утверждение: вердикта о согласии двух
    величин на экране нет. Знак сравнения уликой не считается — «>» живёт в
    стрелочной функции, и запрет на него падал бы на верном коде.
    """
    verdicts = ("сходится", "не сходится", "расхожд", "недостро", "нехват", "превыш")
    for name in ("renderObjectParkingNote", "objectParkingFieldNote"):
        low = _piece(name).lower()
        for word in verdicts:
            assert word not in low, f"{name}: вердикт о согласии ({word})"


def test_a_project_saved_before_this_keeps_its_hand_written_numbers() -> None:
    """Посев списка тронутых полей: непустое число проекта — человеческое.

    Проект, сохранённый до правки, списка не несёт, и без посева норма затёрла
    бы вписанные в него числа при первом же пересчёте. А проект, сохранённый
    ПОСЛЕ, список несёт — и пересев затёр бы его: заполненное нормой поле
    стало бы «тронутым руками» и замерло бы навсегда.
    """
    script = """
%(seed)s
let inputs = %(legacy)s;
seedParkingByHand();
const legacy = inputs._parking_by_hand;
inputs = %(fresh)s;
seedParkingByHand();
console.log(JSON.stringify({legacy, fresh: inputs._parking_by_hand}));
""" % {"seed": _piece("seedParkingByHand"),
       "legacy": json.dumps({"offices_parking_under_spaces": 40,
                             "retail_parking_under_spaces": 0}),
       "fresh": json.dumps({"offices_parking_under_spaces": 2956,
                            "_parking_by_hand": []})}
    script = "const OBJECT_PARKING_PREFIXES=['offices','retail','sports'];\n" + script
    out = subprocess.run(["node", "-e", script], capture_output=True, text=True, timeout=60)
    assert out.returncode == 0, out.stderr[-2000:]
    seen = json.loads(out.stdout)
    assert seen["legacy"] == ["offices"], seen
    assert seen["fresh"] == [], "пересев затёр список проекта"
