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
const num = v => String(v);
%(prefixes)s
let lastResult = %(result)s;
// Сверка старого проекта читает вводные: без них стенд падает на «inputs is
// not defined», и падение выходит про стенд, а не про подпись.
let inputs = {_parking_by_norm: []};
%(note)s
%(fn)s
renderObjectParkingNote();
console.log(JSON.stringify({html: box.innerHTML}));
"""


def _render(result) -> str:
    script = HARNESS % {"result": json.dumps(result, ensure_ascii=False),
                        "prefixes": _const("OBJECT_PARKING_PREFIXES"),
                        "note": _piece("objectParkingFieldNote") + "\n"
                        + _piece("markParkingByNorm") + "\n"
                        + _piece("reconcileLegacyParking"),
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


def _const(name: str) -> str:
    """Объявление константы страницы — из самой страницы, а не переписанное.

    Вторая копия списка объектов разошлась бы с первой молча, и стенд проверял
    бы не то, что рисует страница.
    """
    start = PAGE.index(f"const {name}=")
    end = PAGE.index(";", start)
    return PAGE[start:end + 1]


def _render_fields(result, inputs=None):
    """Отрисовать подписи и поля так, как их рисует страница."""
    script = """
const cells = {parkNorm_offices:{textContent:""}, parkNorm_retail:{textContent:""},
               objectParkingNote:{innerHTML:""},
               f_offices_parking_under_spaces:{value:null},
               f_offices_parking_over_spaces:{value:null}};
global.document = {getElementById: id => cells[id] || null, activeElement: null};
function escapeHtml(s){return String(s)}
const num = v => String(v);
%(prefixes)s
let inputs = %(inputs)s;
let lastResult = %(result)s;
%(a)s
%(mark)s
%(b)s
renderObjectParkingNote();
console.log(JSON.stringify({
  note_offices: cells.parkNorm_offices.textContent,
  note_retail: cells.parkNorm_retail.textContent,
  field_offices: cells.f_offices_parking_under_spaces.value,
  field_retail: (cells.f_retail_parking_under_spaces||{value:null}).value,
  note_retail: cells.parkNorm_retail.textContent,
  inputs}));
""" % {"result": json.dumps(result, ensure_ascii=False),
       "inputs": json.dumps(inputs or {}, ensure_ascii=False),
       "prefixes": _const("OBJECT_PARKING_PREFIXES"),
       "a": _piece("objectParkingFieldNote"),
       # Норма помечает своё число — без этой функции стенд падает на
       # неопределённом имени, и падение выходит про стенд, а не про подпись.
       "mark": _piece("markParkingByNorm") + "\n"
                 + _piece("reconcileLegacyParking"),
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
    # Норма помечает своё число (`markParkingByNorm`) — без неё стенд падает
    # на неопределённом имени, и падение выходит про стенд, а не про то,
    # что он проверяет.
    for name in ("renderObjectParkingNote", "objectParkingFieldNote",
                 "markParkingByNorm"):
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
         "by_norm": True, "required_spaces": 2778, "units": 2778,
         "under_spaces": 2778, "over_spaces": 0},
        {"prefix": "retail", "tep_key": "standalone_retail", "enabled": True,
         "by_norm": False, "required_spaces": 310, "units": 40,
         "under_spaces": 40, "over_spaces": 0},
    ]}}
    seen = _render_fields(result)
    assert seen["field_offices"] == 2778, "норма не доехала до самого поля"
    assert seen["inputs"]["offices_parking_under_spaces"] == 2778
    assert "норматив" in seen["note_offices"].lower()
    assert "2778" not in seen["note_offices"], "число сказано дважды подряд"
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
                          offices_parking_under_spaces=2778)
    assert (filled, by_norm) == (2778, True)
    grew, by_norm = run(200000.0, _parking_by_hand=[],
                        offices_parking_under_spaces=2778)
    assert by_norm and grew > filled, "поле замерло на вчерашнем числе"
    # Тронутое руками норма не перебивает — включая ноль. Прежде сказать
    # «гаража у объекта нет» было нечем вовсе: ноль читался как «не задано».
    assert run(200000.0, _parking_by_hand=["offices"],
               offices_parking_under_spaces=40) == (40, False)
    assert run(200000.0, _parking_by_hand=["offices"],
               offices_parking_under_spaces=0) == (0, False)
    # Проект, сохранённый до правки, списка не несёт — его числа человеческие.
    assert run(200000.0, offices_parking_under_spaces=40) == (40, False)


def test_a_field_shows_no_stale_number_but_names_the_reason() -> None:
    """До расчёта поле не несёт ЧИСЛА, но называет причину.

    Прежняя редакция требовала полного молчания, и это было верно наполовину:
    прежняя норма под новыми метрами действительно читается как посчитанная.
    Но молчание читается не лучше — на экране владельца 08.09.2026 стояли
    обещание в подсказке, ноль в поле и пустота под ним, и вместе это читалось
    как «норматив решил, что мест не надо».

    Утверждение, верное СЕЙЧАС: числа нет, причина есть. Прежнее беспокойство
    держится тем же тестом — в подписи не должно быть старого числа.

    Случай не редкий: `lastResult` обнуляет и `renderCalcLocked` — расчёт закрыт
    входом, а вход у каждого браузера свой.
    """
    script = """
const cell = {textContent:"дырка"};
global.document = {getElementById: id => (id === 'parkNorm_offices' ? cell : null)};
function escapeHtml(s){return String(s)}
const num = v => String(v);
%(prefixes)s
let inputs = {};
let lastResult = null;
%(a)s
%(mark)s
%(b)s
renderObjectParkingNote();
console.log(JSON.stringify({left: cell.textContent}));
""" % {"prefixes": _const("OBJECT_PARKING_PREFIXES"),
       "a": _piece("objectParkingFieldNote"),
       "mark": _piece("markParkingByNorm") + "\n"
                 + _piece("reconcileLegacyParking"),
       "b": _piece("renderObjectParkingNote")}
    out = subprocess.run(["node", "-e", script], capture_output=True, text=True, timeout=60)
    assert out.returncode == 0, out.stderr[-2000:]
    left = json.loads(out.stdout)["left"]
    assert "дырка" not in left, "прежнее число осталось стоять — читается как посчитанное"
    assert "Расчёт не выполнен" in left, left


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
    # Норма помечает своё число (`markParkingByNorm`) — без неё стенд падает
    # на неопределённом имени, и падение выходит про стенд, а не про то,
    # что он проверяет.
    for name in ("renderObjectParkingNote", "objectParkingFieldNote",
                 "markParkingByNorm"):
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
       "fresh": json.dumps({"offices_parking_under_spaces": 2778,
                            "_parking_by_hand": []})}
    script = "const OBJECT_PARKING_PREFIXES=['offices','retail','sports'];\n" + script
    out = subprocess.run(["node", "-e", script], capture_output=True, text=True, timeout=60)
    assert out.returncode == 0, out.stderr[-2000:]
    seen = json.loads(out.stdout)
    assert seen["legacy"] == ["offices"], seen
    assert seen["fresh"] == [], "пересев затёр список проекта"


def test_a_disabled_object_says_why_the_field_is_empty() -> None:
    """Выключенный объект называет причину, а не молчит.

    Экран владельца 08.09.2026: «как было так и есть». В блоке «МФОЦ / офисы»
    признак «Объект включён» снят, поле паркинга — 0, подписи под ним нет
    вовсе, а подсказка у поля обещает норму. Выходило обещание, ноль и тишина;
    и по той же подсказке ноль читается как «гаража нет, вписано руками».

    Расчёт при этом верен: выключенный объект не строится, значит и мест у него
    нет (`take_norm = enabled and not by_hand`). Врал экран, и чинится он, а не
    движок.
    """
    seen = _render_fields({"parking": {"own": [
        {"prefix": "offices", "enabled": False, "by_norm": False,
         "required_spaces": 0, "under_spaces": 0, "over_spaces": 0},
    ]}})
    note = seen["note_offices"]
    assert note, "подпись у выключенного объекта пуста — молчание не объяснено"
    assert "выключен" in note, note
    assert "Включите" in note, "не сказано, что сделать, чтобы поле заполнилось"
    assert seen["field_offices"] in (None, 0), "выключенному объекту норму не пишем"


def test_the_field_hint_does_not_promise_the_norm_unconditionally() -> None:
    """Подсказка у поля — утверждение о ПОЛЕ, а не о методике.

    То же правило уже было выведено 07.09.2026 на плате за ВРИ и здесь не
    применялось: подсказка обещала «заполняется нормативом» всегда, в том числе
    у выключенного объекта, где норма не считается вовсе.
    """
    import main_legacy as core

    hints = [field[2] for _title, fields in core.FIELD_GROUPS for field in fields
             if str(field[0]).endswith(("_parking_under_spaces", "_parking_over_spaces"))]
    assert hints, "поля паркинга объектов не найдены"
    for hint in hints:
        assert "нормативом приложения 6" in hint, hint
        assert "ВКЛЮЧЁННОГО" in hint, f"обещание безусловно: {hint}"


def test_without_a_calculation_the_note_says_so() -> None:
    """Нет расчёта — подпись называет причину, а не молчит.

    Экран владельца 08.09.2026, второй заход: объект уже ВКЛЮЧЁН, поле по-прежнему
    0, подписи нет. Цепочка при этом исправна — померено сквозь: движок даёт 159
    мест, писатель ставит 159 в поле. Молчало потому, что расчёта не было вовсе:
    `/calculate` закрыт входом и на телефоне отвечает 401, а `lastResult` тогда
    пуст.

    Число мы намеренно не показываем — прежнее под новыми вводными читалось бы
    как посчитанное. Но причина обязана быть сказана: обещание в подсказке плюс
    ноль в поле плюс тишина читаются как «норматив решил, что мест не надо».
    """
    seen = _render_fields({})
    note = seen["note_offices"]
    assert note, "без расчёта подпись пуста — молчание не объяснено"
    assert "Расчёт не выполнен" in note, note
    assert "вход" in note, "не названа самая частая причина — расчёт закрыт входом"


def test_a_fresh_result_still_fills_the_field() -> None:
    """Предохранитель: объяснение молчания не должно съесть саму норму.

    Проверяется то, ради чего всё писалось, — при свежем расчёте число встаёт
    В ПОЛЕ, а подпись говорит, чьё оно.
    """
    seen = _render_fields({"parking": {"own": [
        {"prefix": "offices", "enabled": True, "by_norm": True,
         "required_spaces": 159, "under_spaces": 159, "over_spaces": 0},
    ]}})
    assert seen["field_offices"] == 159, seen
    assert "нормативу приложения 6" in seen["note_offices"], seen["note_offices"]


def test_a_stale_result_is_not_called_a_disabled_object() -> None:
    """Галочка стоит, а расчёт её не видел — так и говорим.

    Экран владельца 08.09.2026, «ТЦ / коммерция ОСЗ»: объект включён, поле 0.
    Движок требование считает — 186 мест по X2=54, они строятся и не продаются,
    — и писатель их ставит; померено сквозь. Не совпадали не числа, а моменты:
    ответ расчёта старше галочки.

    Первая редакция этой подписи сказала бы в такую минуту «объект выключен» —
    неправду о том, что человек видит строкой выше. Признак берётся из вводных
    (`inputs[prefix+'_enabled']`), а не из ответа: ответ и есть то, что устарело.
    """
    seen = _render_fields(
        {"parking": {"own": [
            {"prefix": "retail", "enabled": False, "by_norm": False,
             "required_spaces": 0, "under_spaces": 0, "over_spaces": 0},
        ]}},
        inputs={"retail_enabled": True},
    )
    note = seen["note_retail"]
    assert "ещё не видел" in note, note
    assert "выключен" not in note, f"сказано неправдой о включённом объекте: {note}"


def test_a_truly_disabled_object_still_says_it_is_off() -> None:
    """Предохранитель: различение не съело сам ответ про выключённый объект."""
    seen = _render_fields(
        {"parking": {"own": [
            {"prefix": "retail", "enabled": False, "by_norm": False,
             "required_spaces": 0, "under_spaces": 0, "over_spaces": 0},
        ]}},
        inputs={"retail_enabled": False},
    )
    assert "Объект выключен" in seen["note_retail"], seen["note_retail"]


def test_a_number_the_norm_wrote_does_not_freeze_after_reload() -> None:
    """Число нормы переживает загрузку как ЕЁ число, а не как человеческое.

    Норма заполняет поле с 07.09.2026, а посев списка тронутых полей считал
    непустое число вписанным руками — и её же число замирало навсегда. На
    живом проекте офисы стояли 2 956 мест при норме 134 286: правь ГНС хоть
    до девяти миллионов, поле не двигалось (владелец, 09.09.2026:
    «машиноместа не пересчитались вообще»). Два порядка разницы, и на экране
    замершее число выглядит посчитанным.

    Утверждений здесь три, и каждое своё:
    - поле, помеченное нормой, посев тронутым не считает;
    - правка руками пометку нормы снимает — иначе посев вернёт число ей;
    - старый проект БЕЗ обоих списков остаётся человеческим: молча переписать
      вписанное руками хуже, чем оставить, — но подпись обязана назвать путь
      назад, и это держит соседняя проверка.
    """
    script = """
%(seed)s
%(mark)s
%(hand)s
const out = {};
let inputs = {offices_parking_under_spaces: 2956, _parking_by_norm: ['offices']};
seedParkingByHand();
out.norm_written = inputs._parking_by_hand;
inputs = {offices_parking_under_spaces: 2956, _parking_by_norm: ['offices']};
markParkingByHand('offices');
out.after_hand_norm = inputs._parking_by_norm;
out.after_hand_hand = inputs._parking_by_hand;
inputs = {offices_parking_under_spaces: 2956};
seedParkingByHand();
out.legacy = inputs._parking_by_hand;
console.log(JSON.stringify(out));
""" % {"seed": _piece("seedParkingByHand"),
       "mark": _piece("markParkingByNorm") + "\n"
                 + _piece("reconcileLegacyParking"),
       "hand": _piece("markParkingByHand")}
    script = "const OBJECT_PARKING_PREFIXES=['offices','retail','sports'];\n" + script
    out = subprocess.run(["node", "-e", script], capture_output=True, text=True, timeout=60)
    assert out.returncode == 0, out.stderr[-2000:]
    got = json.loads(out.stdout)
    assert got["norm_written"] == [], (
        "число нормы посев записал в «тронутые руками» — оно замрёт навсегда")
    assert got["after_hand_hand"] == ["offices"], got
    assert got["after_hand_norm"] == [], "правка руками не сняла пометку нормы"
    assert got["legacy"] == ["offices"], (
        "старый проект без списков: вписанное руками молча переписывать нельзя")


def test_a_hand_written_field_names_the_way_back() -> None:
    """Замок называет, чем его открыть.

    Без этого поле старого проекта заперто навсегда, а норматив рядом молчит:
    2 956 на экране и 134 286 по норме выглядят одинаково посчитанными.
    """
    seen = _render_fields(
        {"parking": {"own": [{"prefix": "offices", "enabled": True, "by_norm": False,
                              "units": 2956, "required_spaces": 134286,
                              "under_spaces": 2956, "over_spaces": 0}], "rows": []}},
        inputs={"offices_enabled": True})
    note = seen["note_offices"]
    assert "Задано руками" in note, note
    assert "134286" in note.replace(" ", "").replace(" ", ""), note
    assert "Очистите поле" in note, "путь назад не назван"


def test_a_saved_project_recognises_the_norms_own_number() -> None:
    """Сохранённый проект узнаёт число нормы совпадением, а не пометкой.

    «Это не работает, только если грузить сохранённый проект. Если заново вбить
    ТЭП — всё работает» (владелец, 09.09.2026). Разница ровно в посеве: у
    сохранённого поле непустое, и оно объявлялось человеческим. Пометок у такого
    проекта нет вовсе, зато есть сравнение: стоит ровно то, что даёт норма на
    тех же вводных — значит её. Числа при этом не меняются (они и так равны);
    меняется другое: со следующей правки ТЭП поле снова идёт за нормой.

    Обратный случай держит вторая половина проверки: число, НЕ равное норме,
    остаётся человеческим — молча переписать вписанное руками нельзя.
    """
    saved = {"offices_enabled": True, "offices_parking_under_spaces": 560,
             "offices_parking_over_spaces": 0}
    result = {"parking": {"own": [{"prefix": "offices", "enabled": True, "by_norm": False,
                                   "units": 560, "required_spaces": 560,
                                   "under_spaces": 560, "over_spaces": 0}], "rows": []}}
    seen = _render_fields(result, inputs=saved)
    assert seen["inputs"].get("_parking_by_norm") == ["offices"], (
        "совпавшее с нормой число осталось «вписанным руками» — оно замрёт")

    other = dict(saved, offices_parking_under_spaces=2956)
    result_other = json.loads(json.dumps(result))
    result_other["parking"]["own"][0].update(units=2956, under_spaces=2956,
                                             required_spaces=134286)
    seen_other = _render_fields(result_other, inputs=other)
    assert seen_other["inputs"].get("_parking_by_norm") == [], (
        "число, не равное норме, объявлено её — так переписывают вписанное руками")
