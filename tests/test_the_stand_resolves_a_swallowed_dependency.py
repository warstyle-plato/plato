"""Разрешитель стенда добирает зависимости куска, а не ждёт их ошибки.

Куски скрипта страницы стенд добирал ПО ИМЕНИ ИЗ `ReferenceError` — и потому
был слеп ровно к тому куску, чью ошибку глушит чужой `try/catch`. Правило
«падение внутри try/catch разрешителю невидимо» записано про `loadLocal`, где
node выходил нулём; здесь оно вышло хуже — функция возвращает ПУСТУЮ СТРОКУ, и
стенд молча отвечает неверным текстом.

Замер 15.09.2026 на живых записях прода (Варшавское ш., вл. 37 и Рубцовская
наб., влд. 3): карточка печатала «Согласно распоряжению № ДГП-Р-54/26 от »
без дня. `krtCityDay` зовёт `moscowFormat`, ловит его отсутствие своим же
`catch` и отдаёт ''. На живой странице весь скрипт одним блоком — то есть врал
стенд, а не прод; с добранной зависимостью печатается «17 августа 2026 г.» и
«3 сентября 2026 г.» (ровно случай московской полуночи, ради которого
`krtCityDay` и заведена).

Запуск: python3 -m pytest tests/test_the_stand_resolves_a_swallowed_dependency.py -q
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import page_blocks  # noqa: E402
from auction_search import ui  # noqa: E402

# Отметка города: 02.09 21:00 UTC — это 03.09 00:00 по Москве. День у неё
# московский, и именно на таком дне видно, что зона пришпилена.
MIDNIGHT = 1788382800


def _day() -> str:
    page = ui.auctions_page(None)
    tail = "\nconsole.log(JSON.stringify({day: krtCityDay(%d)}));\n" % MIDNIGHT
    return page_blocks.run_json("", tail, page=page)["day"]


def test_a_swallowed_dependency_is_taken_anyway():
    """Кусок, чью ошибку глушит чужой `catch`, всё равно добирается."""
    said = _day()
    assert said, "день не напечатан — зависимость не добрана, а ошибка проглочена"
    assert "сентября" in said and "2026" in said, said


def test_the_resolver_would_notice_the_blindness():
    """Предохранитель: со слепым разрешителем стенд ОТВЕЧАЕТ ПУСТОТОЙ, а не падает.

    Без этой проверки соседняя зеленела бы и на разрешителе, который просто
    добирает всё подряд: важно не то, что день напечатан, а то, что молчание
    здесь возможно и ловится. Слепоту изображаем тем же способом, каким она и
    случилась, — куском, объявленным отдельно от своей зависимости.
    """
    page = ui.auctions_page(None)
    blind = page_blocks.function("krtCityDay", page)
    tail = "\nconsole.log(JSON.stringify({day: krtCityDay(%d)}));\n" % MIDNIGHT
    # `moscowFormat` не добран нарочно, и `krtCityDay` уже объявлена — значит
    # разрешителю добирать нечего, а node выйдет нулём с пустым ответом.
    said = page_blocks.run_json(blind, tail, page=page)["day"]
    assert said == "", "проглоченная ошибка обязана давать пустую строку — иначе пример не тот"


def test_a_stub_is_not_overwritten_by_the_page():
    """Заглушку стенда настоящий кусок не перебивает — даже объявленную через запятую.

    Стенды объявляют заглушки списком (`const a=()=>{},b=()=>{};`), и страж,
    знавший одну форму записи, добирал поверх настоящую функцию: «Identifier
    has already been declared» — SyntaxError на весь скрипт, то есть падение
    стенда вместо утверждения о странице.
    """
    stand = "const moscowFormat=()=>({format:()=>'ЗАГЛУШКА'}),ignored=0;"
    tail = "\nconsole.log(JSON.stringify({day: krtCityDay(%d)}));\n" % MIDNIGHT
    said = page_blocks.run_json(stand, tail, page=ui.auctions_page(None))["day"]
    assert said == "ЗАГЛУШКА", said
