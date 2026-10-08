"""Куски скрипта страницы для стендов на node — по границам, а не перечислением.

Стенд, который собирает скрипт из функций ПО ИМЕНАМ, падает на правке страницы,
а не на том, что он проверяет: рядом появилась функция — «X is not defined», и
разбирать приходится чужое падение вместо своего. Так уже было с
`parkingRequirement`, и 07.09.2026 повторилось с `applyDerivedInputs`: замок
«Требования КРТ» встал на пути выгрузки ГлавАПУ, и три стенда упали разом,
ничего не сказав о том, что сломалось на самом деле (ничего).

Границей куска служат скобки и собственное объявление, а не соседняя строка, и
ответ на «где живёт этот кусок» один на все стенды: две копии разошлись бы
молча — так же молча, как расходятся две копии любого другого правила.
"""

from __future__ import annotations

import functools
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import main_legacy as core  # noqa: E402


def function(name: str, page: str | None = None) -> str:
    """Тело функции страницы целиком, по балансу скобок.

    Страница по умолчанию основная (`PAGE`); у торгов своя, и берётся она тем
    же способом — иначе у одного правила «где живёт этот кусок» завелось бы
    два ответа.
    """
    page = core.PAGE if page is None else page
    declaration = f"function {name}("
    start = page.find(declaration)
    if start < 0:
        raise AssertionError(f"на странице нет функции {name}")
    # `async` стоит ПЕРЕД словом `function`, и срез от него терял это слово:
    # node отвечал «await is only valid in async functions», то есть падал на
    # стенде, а не на том, что стенд проверяет.
    if page[max(0, start - 6):start] == "async ":
        start -= 6
    depth = 0
    for position in range(page.index("{", start), len(page)):
        if page[position] == "{":
            depth += 1
        elif page[position] == "}":
            depth -= 1
            if depth == 0:
                return page[start:position + 1]
    raise AssertionError(f"тело функции {name} не закрыто скобкой")


def constant(name: str, page: str | None = None) -> str:
    """Объявление константы страницы целиком — до `;` вне скобок.

    Функция страницы часто читает объявленную рядом константу (`PARKING_2118`
    подставляется движком плейсхолдером), и стенд, который берёт только
    функции, падает на «X is not defined» — то есть на своей неполноте, а не на
    том, что проверяет.
    """
    page = core.PAGE if page is None else page
    for keyword in ("const ", "let ", "var "):
        start = page.find(f"{keyword}{name}=")
        if start >= 0:
            break
    else:
        raise AssertionError(f"на странице нет константы {name}")
    depth = 0
    for position in range(start, len(page)):
        symbol = page[position]
        if symbol in "([{":
            depth += 1
        elif symbol in ")]}":
            depth -= 1
        elif symbol == ";" and depth == 0:
            return page[start:position + 1]
    raise AssertionError(f"объявление {name} не закрыто точкой с запятой")


def piece(name: str, page: str | None = None) -> str:
    """Кусок страницы по имени: функция, а нет такой — объявление константы.

    Ответ на «где живёт этот кусок» один: стенд, разрешающий зависимости сам,
    не перечисляет их списком, который отстаёт от страницы.
    """
    try:
        return function(name, page)
    except AssertionError:
        return constant(name, page)


def krt_lock() -> str:
    """Замок «Требования КРТ» со списком запертых полей и общим писателем.

    Через `applyDerivedInputs` пишут вводные и пересчёт ТЭП, и выгрузка
    ГлавАПУ: приоритет по полю не зависит от того, кто пишет.
    """
    page = core.PAGE
    start = page.find("const KRT_REQUIREMENT_INPUTS=")
    if start < 0:
        raise AssertionError("на странице нет списка запертых требованием КРТ полей")
    end = page.find("function applyDerivedInputs(", start)
    if end < 0:
        raise AssertionError("на странице нет общего писателя вводных applyDerivedInputs")
    return page[start:end] + function("applyDerivedInputs")


def tep_cell_stand() -> str:
    """Стенд для правки ячейки ТЭП: настоящие функции страницы плюс заглушки.

    Ответ на «как погонять `tepCellChanged`» один на все проверки: две копии
    стенда разошлись бы молча, и одна из них однажды проверяла бы прошлое
    поведение. Заглушками стоит только то, что к арифметике строки отношения
    не имеет — отрисовка, вводные, расчёт.
    """
    pieces = [
        page_const("TEP_RATIOS"),
        # Подписи переданных метров — со страницы, а не литералом: получателя
        # модель не знает, и вторая копия слова разошлась бы с движком молча.
        page_const("TRANSFER_LABELS"),
        page_const("TRANSFER_WORD"),
        page_const("TRANSFER_NOTE_WORD"),
        page_const("TRANSFER_RECIPIENT_NOTE"),
        "const inputs={};",
        "let tep={};",
        "const landNum=(v,d)=>Number(v||0).toFixed(d===undefined?1:d);",
        "let recalcs=0;",
        "function tepRowToInputs(){}",
        "function renderInputs(){}",
        "function renderTep(){}",
        "function updateTepTotals(){}",
        "function scheduleTepAutoRecalc(){}",
        "function calculate(){recalcs++}",
        "const TEP_SOCIAL_INPUTS={};",
        "function socialTotalShare(){return 0.9}",
        function("tepRatioOverrides"),
        function("tepRatio"),
        function("tepFillByRatios"),
        function("tepApplyTransfer"),
        # Пара «штуки ↔ метры» кладовых: правка ячейки зовёт её, и без
        # неё стенд падал бы на неопределённом имени — то есть про себя,
        # а не про то, что проверяет.
        function("storageAreaPerUnit"),
        function("syncStoragePair"),
        # Правка ячейки помечает поле ручным (`_field_origin`): импорт
        # выгрузки ГлавАПУ его потом не перезаписывает.
        function("fieldOrigins"),
        function("markFieldManual"),
        function("tepCellChanged"),
        # Пересборка строки по долям — тот же путь, что правка ячейки:
        # «наши» и правка доли обязаны считать переданное так же.
        "let tepRatioComplaint='';",
        "const TEP_ROW_SWITCH={};",
        "let RATIO_STORE={};",
        function("tepRatioChain"),
        function("tepRatioWrite"),
        function("tepRatioChangedKeys"),
        function("refillTepRow"),
        function("tepRatioSet"),
        function("tepRatioReset"),
    ]
    return "\n".join(pieces) + "\n"


# Одно и то же объявление ищется ДЕСЯТКИ ТЫСЯЧ раз за один стенд: разрешитель
# спрашивает «занято ли имя» про каждую зависимость и про каждого её соседа, а
# собранный скрипт к концу разбора — сотни килобайт. Поиск по имени сканировал
# весь текст заново на каждый вопрос, и 73 секунды из 84 у одного стенда
# уходили в `re.search` (замер 27.09.2026 профилировщиком на подписи паркинга:
# 57 811 сканирований, node при этом занял 0,2 с). Поэтому текст разбирается
# ОДИН раз в набор объявленных имён, а вопрос про имя становится взглядом в
# набор. Правило то же, что и было: перекос в сторону «занято».
#
# Выражения — те же самые, только имя в них не подставляется, а вынимается
# группой: два написания правила разошлись бы молча.
_DECLARED_FUNCTION = re.compile(r"(?:^|[^\w$.])(?:async\s+)?function\s+([A-Za-z_$][\w$]*)\s*\(")
_DECLARED_BINDING = re.compile(r"(?<![\w$.])([A-Za-z_$][\w$]*)\s*=(?![=>])")
# Сколько раз текст пришлось разобрать целиком. Считается, чтобы возврат к
# «сканировать на каждое имя» был виден проверкой, а не только секундами.
_SCANS = 0


def scans() -> int:
    """Сколько раз разбирался текст целиком за всё время процесса."""
    return _SCANS


@functools.lru_cache(maxsize=512)
def _declared_names(text: str) -> frozenset[str]:
    """Все имена, связанные в этом тексте, — один разбор на текст."""
    global _SCANS
    _SCANS += 1
    return frozenset(_DECLARED_FUNCTION.findall(text)) | frozenset(
        _DECLARED_BINDING.findall(text))


def _declared_in(text: str, name: str) -> bool:
    """Занято ли имя в уже собранном скрипте — включая заглушки стенда.

    Проверяется связывание в любой форме, а не только `const имя=`: стенды
    объявляют заглушки через запятую (`const renderProjectClassPreview=()=>{},
    renderClassDialog=()=>{};`), и страж, знавший одну форму, добирал поверх
    заглушки настоящий кусок — «Identifier has already been declared», то есть
    SyntaxError на весь скрипт.

    Перекос намеренно в сторону «занято»: лишний отказ добора только вернёт
    имя ленивому пути, где оно всплывёт своей же ошибкой, а лишний добор
    роняет стенд целиком. Отсечка точкой — чтобы `x.имя=` не считалось
    объявлением, `(?![=>])` — чтобы им не считались `==` и `=>`.
    """
    return name in _declared_names(text)


@functools.lru_cache(maxsize=8)
def _page_function_names(page: str) -> frozenset[str]:
    """Имена функций страницы — один разбор на страницу, а не на имя."""
    global _SCANS
    _SCANS += 1
    return frozenset(re.findall(r"function ([A-Za-z_$][\w$]*)\(", page))


def _page_declares(name: str, page: str) -> bool:
    """Объявлена ли у страницы ФУНКЦИЯ с таким именем.

    Только функция, и это не половинчатость, а граница измеренного. Объявление
    значения `constant` ищет подстрокой `const имя=`, а такая строка бывает и
    в СЕРЕДИНЕ чужой функции: добранный по ней кусок уезжает наверх и объявляет
    там имена, которых в этом месте быть не должно («Identifier 'area' has
    already been declared» на первом же прогоне). Значения по-прежнему
    добираются лениво, по своей ошибке, — а слепота разрешителя, ради которой
    правка и написана, померена на функции (`moscowFormat`).

    Подстрока `function имя(` и имя в наборе имён — одно и то же условие:
    набор собран тем же выражением, что и подстрока, включая отсутствие
    пробела перед скобкой.
    """
    return name in _page_function_names(page)


# Обращение к свойству (`Math.max`, `x.slice`) именем страницы не является:
# без отсечки точкой разрешитель тянул бы куски по именам чужих методов.
_NAME = re.compile(r"(?<![\w$.])([A-Za-z_$][\w$]*)")


def _needs(body: str, page: str) -> list[str]:
    """Имена страницы, которые читает этот кусок, в порядке первого чтения."""
    out: list[str] = []
    for found in _NAME.findall(body):
        if found not in out and not _declared_in(body, found) \
                and _page_declares(found, page):
            out.append(found)
    return out


def _piece_with_deps(name: str, page: str | None, have: str,
                     depth: int = 0) -> list[tuple[str, str]]:
    """Кусок вместе с ЕГО зависимостями, зависимости впереди.

    Разрешитель добирал куски по имени из `ReferenceError`, и потому был слеп
    к падению, проглоченному чужим `try/catch`. `krtCityDay` зовёт
    `moscowFormat`, ловит его отсутствие своим же `catch` и возвращает пустую
    строку: карточка печатала «Согласно распоряжению № ДГП-Р-54/26 от » без
    дня, node выходил нулём, добирать было нечего, и стенд молча отвечал
    неверным текстом (замер 15.09.2026 на живых записях прода). На живой
    странице весь скрипт одним блоком, то есть врал стенд, а не прод.

    Правило то же, что уже записано про `loadLocal`: падение внутри
    `try/catch` разрешителю невидимо — значит зависимости берутся РАЗБОРОМ
    куска, а не ожиданием его ошибки. Уже объявленное (в том числе заглушку
    стенда) не трогаем: заглушка ответила бы за страницу только если её ставили
    нарочно, и перебивать её настоящим куском — это менять стенд под собой.
    """
    # Чья это страница, решается здесь же, а не у вызывающего: `piece` умеет
    # умолчание, а разбор зависимостей получал сырой `None` и падал «argument
    # of type NoneType is not iterable» — то есть на стенде, а не на том, что
    # стенд проверяет.
    page = core.PAGE if page is None else page
    return _deps(name, page, _declared_names(have), depth)


def _deps(name: str, page: str, seen: frozenset[str],
          depth: int = 0) -> list[tuple[str, str]]:
    """То же, но занятые имена едут НАБОРОМ, а не растущим текстом.

    Раньше сюда ехал собранный скрипт, и «занято ли имя» сканировало его
    целиком на каждую зависимость. Текст к концу разбора — сотни килобайт,
    вопросов — десятки тысяч, и один стенд подписи паркинга съедал 84 секунды,
    из них 73 в `re.search` (замер 27.09.2026). Набор собирается по разу на
    КУСОК, а не по разу на вопрос; правило «занято» не менялось.
    """
    if depth > 40:
        raise AssertionError(f"зависимости {name} не сходятся — цепочка глубже 40")
    body = piece(name, page)
    out: list[tuple[str, str]] = []
    seen = seen | _declared_names(body)
    for dependency in _needs(body, page):
        if dependency in seen:
            continue
        for got_name, got_body in _deps(dependency, page, seen, depth + 1):
            if got_name not in seen:
                out.append((got_name, got_body))
                seen = seen | _declared_names(got_body)
    out.append((name, body))
    return out


def run(prelude: str, tail: str, limit: int = 60,
        page: str | None = None) -> tuple[str, list[str]]:
    """Гоняет стенд на node, добирая недостающие куски страницы по именам.

    Тот же приём был выписан копиями в трёх проверках, а общий стенд
    перечислял зависимости руками — и падал на своей неполноте, когда рядом
    заводили функцию: «setTepNote is not defined» вместо утверждения о строке.
    Имя берётся из самой ошибки, кусок — у страницы; имени на странице нет —
    падаем с ним, а не подсовываем заглушку: заглушка ответила бы за страницу.

    `page` — чья это страница. По умолчанию основная (`PAGE`); у торгов своя, и
    без этого разрешитель искал бы имена её функций на чужой странице, то есть
    падал бы на своей неполноте ровно там, ради чего написан.
    """
    import os  # noqa: PLC0415 — нужны только здесь
    import shutil  # noqa: PLC0415
    import subprocess  # noqa: PLC0415
    import tempfile  # noqa: PLC0415

    node = shutil.which("node")
    if not node:
        import pytest  # noqa: PLC0415

        pytest.skip("node недоступен")
    taken: list[str] = []
    bodies: list[str] = []
    moved: set[str] = set()
    # Имя и ошибка нужны отказу ПОСЛЕ цикла: без объявления здесь отказ при
    # нулевом пределе падал бы своей же UnboundLocalError — то есть снова про
    # стенд, а не про то, что стенд проверяет.
    name, error = "", ""

    for _ in range(limit):
        script = prelude + "\n" + "\n".join(bodies) + "\n" + tail
        # Скрипт уезжает ФАЙЛОМ, а не аргументом: разрешитель добирает куски
        # вместе с их зависимостями, и `node -e` упирался в предел длины
        # команды — «Argument list too long», то есть падение стенда, а не
        # того, что стенд проверяет.
        with tempfile.NamedTemporaryFile("w", suffix=".js", encoding="utf-8",
                                         delete=False) as handle:
            handle.write(script)
            where = handle.name
        try:
            done = subprocess.run([node, where], capture_output=True,
                                  text=True, timeout=120)
        finally:
            os.unlink(where)
        if done.returncode == 0:
            return done.stdout, taken
        error = done.stderr
        # У «имени нет» две формы, и вторую стенд не узнавал. `const`,
        # объявленный НИЖЕ своего читателя, node зовёт не «is not defined», а
        # «Cannot access 'X' before initialization»: имя в скрипте есть, просто
        # стоит не там. Отказ по такой форме выходил про стенд — «не
        # разрешается» с чужой трассировкой, — а лечится она тем же переносом
        # вперёд, что и первая (PROJECT_PARKING_KEY, читаемый картой полей
        # паркинга, 14.09.2026).
        name = ""
        if "ReferenceError" in error and " is not defined" in error:
            name = error.split("ReferenceError: ")[1].split(" is not defined")[0].strip()
        elif "Cannot access '" in error and "' before initialization" in error:
            name = error.split("Cannot access '")[1].split("'")[0].strip()
        if not name:
            raise AssertionError(error[-2500:])
        if name in taken:
            # Имя уже добрано, а node его всё равно не видит — значит порядок:
            # кусок стоит ПОСЛЕ того, кто его читает. Один перенос вперёд, и
            # только потом отказ: иначе настоящий цикл крутился бы до предела.
            if name in moved:
                raise AssertionError(f"{name} не разрешается\n{error[-1500:]}")
            moved.add(name)
            at = taken.index(name)
            bodies.insert(0, bodies.pop(at))
            taken.insert(0, taken.pop(at))
            continue
        # Добранный кусок встаёт перед СВОИМ читателем, а не в конец и не в
        # начало. В конец нельзя: `const`, объявленный ниже того, кто его
        # читает, падает временной мёртвой зоной, и падение выглядит как
        # «имени нет», хотя оно есть строкой ниже. В начало — тоже: у
        # `TRANSFER_LABELS` два читателя, и добранный последним
        # `TRANSFER_RECIPIENT_NOTE` уезжал впереди них обоих (13.09.2026).
        reader = next((i for i, text in enumerate(bodies)
                       if re.search(rf"\b{re.escape(name)}\b", text)), 0)
        have = prelude + "\n" + "\n".join(bodies) + "\n" + tail
        # Дважды объявленное имя — SyntaxError на весь скрипт, и решает это
        # МЕСТО вставки: оно одно видит собранный скрипт целиком, а страж
        # внутри рекурсии видит только свою ветку. Занятые имена растут
        # набором: пересобирать текст на каждую вставку значило бы снова
        # сканировать сотни килобайт по разу на кусок.
        have_names = _declared_names(have)
        offset = 0
        for got_name, got_body in _piece_with_deps(name, page, have):
            # Имя, которое НАЗВАЛ сам node, добирается даже если текст считает
            # его занятым. «Занято» здесь проверяется текстом и об области
            # видимости не знает: `money` объявлен у страницы наверху
            # (`const money=v=>…`), но такая же строка стоит ЛОКАЛЬНО внутри
            # чужой функции (`const money=opts.value==='money_or_share';`), и
            # добранный кусок приносил её с собой. Дальше страж говорил
            # «занято», настоящий верхний `money` не добирался никогда, node
            # повторял «money is not defined», а разрешитель каждый круг
            # подтягивал соседей — и упирался в предел, ничего не сказав о
            # причине. Так 27.09.2026 разъехались доли CI: стенд таблицы
            # очередей сходился или нет в зависимости от того, какую ветку
            # отрисовки node прошёл первой.
            #
            # Обещание «лишний отказ добора только вернёт имя ленивому пути»
            # здесь не работает: ленивый путь упирается в ту же слепую
            # проверку. Слово node о неопределённом имени — ответ о ВИДИМОСТИ,
            # и текстовое совпадение внутри чужой функции его не отменяет.
            # Двойного объявления это не создаёт: объяви прелюдия имя сверху,
            # node не сказал бы «is not defined».
            if got_name in have_names and got_name != name:
                continue
            bodies.insert(reader + offset, got_body)
            taken.insert(reader + offset, got_name)
            have_names = have_names | _declared_names(got_body)
            offset += 1
    # Отказ НАЗЫВАЕТ причину. Прежде он говорил только «зависимостей больше
    # 60», и разбор стоил пяти прогонов по двадцать минут: какие куски стенд
    # успел добрать и на чём именно встал node, не знал никто. Между тем
    # разрешитель знает и то, и другое — и молчал.
    #
    # Настоящему стенду хватает единиц кусков: таблице очередей — тринадцати.
    # Упереться в предел значит, что разрешитель ушёл не туда, и увидеть это
    # можно только по СПИСКУ добранного: он показывает, с какого имени
    # цепочка свернула в сторону. Повтор одного имени сюда не доходит — его
    # ловит страж «не разрешается» выше, — значит здесь именно длинная
    # цепочка разных имён, и читать надо её.
    raise AssertionError(
        f"зависимостей больше {limit} — стенд не сходится.\n"
        f"Последним node не увидел: {name!r}\n"
        f"Добрано по порядку ({len(taken)}): " + ", ".join(taken)
        + f"\nПоследняя ошибка node:\n{error[-1200:]}")


def run_json(prelude: str, tail: str, limit: int = 60, page: str | None = None):
    """То же, но ответ разбирается как JSON — стенды печатают им."""
    import json  # noqa: PLC0415

    out, _taken = run(prelude, tail, limit, page)
    return json.loads(out)


def page_const(name: str, page: str | None = None) -> str:
    """Объявление константы страницы целиком, как оно стоит на СОБРАННОЙ странице.

    Литерал в стенде был бы второй копией методики: доли ТЭП, имена продуктов и
    умолчания объявлены в движке и приезжают подстановкой. Взятые со страницы,
    они не могут отстать.

    Страница по умолчанию основная; у торгов своя, и берётся она тем же
    способом — как и у `function`, иначе у одного правила «где живёт этот
    кусок» завелось бы два ответа.
    """
    page = core.PAGE if page is None else page
    head = f"const {name}="
    start = page.find(head)
    if start < 0:
        raise AssertionError(f"на странице нет константы {name}")
    end = page.find("\n", start)
    line = page[start:end if end > 0 else len(page)].rstrip()
    if not line.endswith(";"):
        raise AssertionError(f"объявление {name} не в одну строку — стенд возьмёт половину")
    return line


def object_roster() -> str:
    """Реестр объектов и всё, что из него на странице считается.

    Стенды несли ЧЕТЫРЕ копии состава литералом (`['offices','retail',
    'sports']`) — вторая жизнь у списка, который объявлен один раз в движке.
    Копия не расходится, пока объектов четыре, и заговорит ровно в тот день,
    ради которого реестр и заводился: пятый объект в стенде выглядит
    несуществующим, а на странице он есть.

    Берётся со СОБРАННОЙ страницы: `STANDALONE_OBJECTS` приезжает туда
    подстановкой, а `discreteDefaults` и `OBJECT_PARKING_PREFIXES` из него
    считаются — порознь они в стенде падают на неопределённом имени, и
    падение выходит про стенд, а не про то, что он проверяет.
    """
    # Состав проекта (`object_instances`), вкладки экземпляров и их поля стоят
    # на странице между реестром и `discreteDefaults` и считаются из реестра —
    # берутся одним куском с ним, а не поимённо.
    page = core.PAGE
    start = page.index("const STANDALONE_OBJECTS=")
    head = page.index("function discreteDefaults(", start)
    return "\n".join((page[start:head], function("discreteDefaults"),
                       function("escapeHtml"),
                       page_const("OBJECT_PARKING_PREFIXES")))


def project_kind() -> str:
    """Тип проекта и всё, что из него на странице считается.

    Форма читает его дважды: надписью над полями (`projectKindNote`) и
    развилкой «жилое поле в нежилом проекте». Перечислять эти куски у каждого
    стенда значит завести то же, что уже стоило шести падений: стенд падает на
    неопределённом имени, и падение выходит про стенд, а не про то, что он
    проверяет.

    Состав типов и список жилых вводных приезжают на страницу подстановкой из
    движка — здесь они берутся со СОБРАННОЙ страницы, как реестр объектов.
    Гостиничный проект — третий тип: его предикаты (`isHotel`,
    `withoutHousing`) и блок «Гостиница» (`HOTEL`, `hotelInputsBlock`)
    читает та же форма. От вида же зависят поля только жилого дома
    (`RESIDENTIAL_ONLY_INPUTS`) и подпись ставки объекта (`OBJECT_RATE_HINTS`,
    `objectRateUnit`) — решение владельца 06.10.2026.
    """
    return "\n".join((page_const("PROJECT_KINDS"),
                       page_const("NONRESIDENTIAL_CLEARED"),
                       page_const("HOTEL"),
                       page_const("RESIDENTIAL_ONLY_INPUTS"),
                       page_const("OBJECT_RATE_HINTS"),
                       function("objectRateUnit"),
                       # Ставки зданий нежилого проекта — в «Строительстве»
                       # (владелец, 07.10.2026).
                       page_const("OBJECT_SMR"),
                       function("nonresBuildingRateFields"),
                       function("movedToConstruction"),
                       function("projectKind"),
                       function("isNonResidential"),
                       function("isHotel"),
                       function("withoutHousing"),
                       function("projectKindLabel"),
                       function("projectKindHasSaved"),
                       function("projectKindNote"),
                       *(function(name) for name in (
                           "hotelOrigins", "setHotelField", "hotelBlank", "hotelValue",
                           "hotelFieldNeeded", "hotelRangeText", "hotelFieldNote",
                           "applyHotelPreset", "hotelInputsBlock"))))


def auctions_function(*names: str) -> str:
    """Те же куски, но со страницы торгов (`auction_search.ui`).

    Страница там собирается плейсхолдерами, поэтому берётся СОБРАННАЯ: в сырой
    константе на месте кусков стоят метки, и стенд падал бы первой же строкой.
    """
    from auction_search import ui  # локально: движок тянуть незачем

    page = ui.auctions_page()
    return "\n".join(function(name, page) for name in names)


def auctions_const(*names: str) -> str:
    """Константы страницы торгов — тем же способом, что и её функции."""
    from auction_search import ui  # локально: движок тянуть незачем

    page = ui.auctions_page()
    return "\n".join(page_const(name, page) for name in names)
