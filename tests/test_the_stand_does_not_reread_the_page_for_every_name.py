"""Стенд на node разбирает собранный скрипт один раз на кусок, а не на имя.

Разрешитель спрашивает «занято ли это имя» про каждую зависимость и про
каждого её соседа — за один стенд вопросов десятки тысяч, — а собранный скрипт
к концу разбора весит сотни килобайт. Пока ответ искался поиском по всему
тексту, один стенд подписи паркинга занимал 84 секунды, из них 73 в
`re.search` (57 811 сканирований; node при этом — 0,2 с, замер
профилировщиком 27.09.2026). Три таких теста давали по 80 секунд каждый, а
файл целиком — больше получаса в доле CI, и доля 3 не укладывалась в потолок.

Проверяется не скорость (секунды зависят от машины), а причина: сколько раз
текст разбирается целиком против того, сколько раз его спрашивают. Возврат к
«сканировать на каждое имя» уравнял бы эти числа, и проверка упадёт.

Запуск: python3 -m pytest tests/test_the_stand_does_not_reread_the_page_for_every_name.py -q
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import page_blocks  # noqa: E402

import main_legacy as core  # noqa: E402

# Функция страницы с длинной цепочкой зависимостей: на ней и мерили.
WITH_DEPS = "renderObjectParkingNote"


def _literal_declared_in(text: str, name: str) -> bool:
    """Правило «занято» ОДНИМ именем — так оно и было записано изначально."""
    word = re.escape(name)
    return bool(re.search(rf"(?:^|[^\w$.])(?:async\s+)?function\s+{word}\s*\(", text)
                or re.search(rf"(?<![\w$.]){word}\s*=(?![=>])", text))


def _literal_page_declares(name: str, page: str) -> bool:
    return f"function {name}(" in page


def test_the_resolver_asks_far_more_than_it_reads(monkeypatch) -> None:
    """Вопросов — тысячи, разборов текста — сотни."""
    asked = {"n": 0}
    real = page_blocks._declared_in

    def counted(text: str, name: str) -> bool:
        asked["n"] += 1
        return real(text, name)

    monkeypatch.setattr(page_blocks, "_declared_in", counted)
    before = page_blocks.scans()
    got = page_blocks._piece_with_deps(WITH_DEPS, None, "")
    read = page_blocks.scans() - before

    assert [name for name, _ in got][-1] == WITH_DEPS, "сам кусок должен приехать последним"
    assert asked["n"] > 500, (
        f"вопросов всего {asked['n']} — стенд измеряют не на этом куске")
    assert read * 10 <= asked["n"], (
        f"текст разобран {read} раз на {asked['n']} вопросов: разбор снова идёт "
        "на каждое имя, а не на кусок")


def test_a_name_is_taken_in_every_form_the_stand_writes() -> None:
    """Набор имён отвечает то же, что поиск по одному имени."""
    cases = [
        ("function moscowFormat(x){}", "moscowFormat", True),
        ("async function loadLocal(){}", "loadLocal", True),
        ("const renderProjectClassPreview=()=>{}, renderClassDialog=()=>{};",
         "renderClassDialog", True),
        ("let lastResult = null;", "lastResult", True),
        ("state.lastResult = null;", "lastResult", False),
        ("if (a==lastResult) {}", "lastResult", False),
        ("const f = lastResult => lastResult;", "lastResult", False),
        ("const PARKING_OWNER_FIELDS={};", "PARKING_OWNER_FIELDS", True),
        ("callSomething(notDeclared);", "notDeclared", False),
    ]
    for text, name, expected in cases:
        assert page_blocks._declared_in(text, name) is expected, (text, name)
        assert _literal_declared_in(text, name) is expected, (text, name)


def test_the_page_names_are_the_ones_the_substring_found() -> None:
    """На настоящей странице оба правила дают один и тот же ответ."""
    page = core.PAGE
    names = re.findall(r"function ([A-Za-z_$][\w$]*)\(", page)
    assert len(names) > 100, "на странице должно быть много функций"
    # Имя-начало чужого имени и заведомо отсутствующее — контрпримеры.
    sample = sorted(set(names))[:300] + [names[0][:3], "заведомоНетТакойФункции"]
    for name in sample:
        assert page_blocks._page_declares(name, page) == _literal_page_declares(name, page), name


# --- слово node о видимости сильнее текстового совпадения -------------------

# Имя объявлено у страницы НАВЕРХУ и такой же строкой — локально внутри чужой
# функции. Ровно это и стоит на настоящей странице: `const money=v=>…` сверху
# и `const money=opts.value==='money_or_share';` внутри разбора графика.
# Порядок как на настоящей странице: верхнее объявление ВЫШЕ локального, иначе
# `constant` вынет локальное и проверка будет про другую дыру.
SHADOWED_PAGE = """
const money=v=>'\u20bd'+String(v);
function outer(opts){ const money=opts.value==='x'; return money ? 1 : 0; }
function shows(){ return String(outer({value:'y'})) + money(2); }
"""


def test_a_name_node_asks_for_is_taken_even_if_the_text_looks_busy() -> None:
    """Локальное объявление в чужом куске не отменяет добор верхнего.

    Разрешитель добирал `shows` вместе с `outer`, а тот приносил с собой
    локальную строку `const money=…`. Дальше страж «занято» — он проверяет
    ТЕКСТ и области видимости не знает — запрещал добрать настоящий верхний
    `money`, node повторял «money is not defined», и стенд упирался в предел,
    ничего не сказав о причине. На прежнем коде этот тест падает отказом
    «зависимостей больше 60».
    """
    out, taken = page_blocks.run("", "console.log(shows());\n", page=SHADOWED_PAGE)
    assert out.strip() == "0₽2", out
    assert "money" in taken, taken
