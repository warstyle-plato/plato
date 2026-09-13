"""Поля «какая очередь строит объект» рисует реестр, а не разметка.

Четыре поля стояли разметкой, и вместе с ними умолчание очереди — двумя
копиями в коде, — а приставки объектов с гаражом третьим списком. Пятый объект
в любом из них молчит, и молчит убедительно: на экране он выглядит объектом
без очереди и без гаража, при том что расчёт его строит.

Это ГЕОМЕТРИЯ и живое состояние страницы: в исходнике сломанная и починенная
выглядят одинаково, поэтому поля считаются в настоящем Chromium, а не ищутся
строкой в файле.

Запуск: python3 -m pytest tests/test_the_objects_choose_their_queue_by_the_roster.py -q
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from browser import chromium_or_skip, serve  # noqa: E402

import main as wrapper  # noqa: E402

core = wrapper.core
PORT = 18242


def test_the_page_carries_no_second_list_of_objects() -> None:
    """Перечисления объектов на странице живут в реестре, а не в коде.

    Запрещается МЕСТО, а не слово: объявление реестра и подстановка ключи
    называют по построению, и искать надо рукописные перечисления рядом с
    `phasing.discrete` и с приставками гаража.
    """
    page = core.PAGE
    assert "discrete:discreteDefaults(count)" in page
    assert "STANDALONE_OBJECTS.filter(o=>o.garage).map(o=>o.prefix)" in page
    # Рукописная четвёрка в умолчании очереди — то, из-за чего всё затевалось.
    assert "discrete:{offices:" not in page
    assert "{offices:Math.min(3,count)" not in page
    # Поля с зашитыми именами объектов: их рисует реестр.
    for dead in ("assignOffices", "assignRetail", "assignSports", "assignAboveParking"):
        assert dead not in page, f"поле {dead} осталось разметкой"


def test_in_a_real_browser_every_object_gets_its_queue_field() -> None:
    """Полей ровно столько, сколько объектов, и подпись у них — имя продукта."""
    chrome = chromium_or_skip()
    from playwright.sync_api import sync_playwright

    with serve(wrapper.app, PORT) as root, sync_playwright() as pw:
        browser = pw.chromium.launch(executable_path=str(chrome))
        try:
            page = browser.new_page()
            page.goto(root, wait_until="load")
            # Объявление функции поднимается наверх и существует ещё до того,
            # как страница доработала; `phasing` — `let`, и до своей строки он
            # в мёртвой зоне, где даже `typeof` бросает. Поэтому ждём само
            # состояние, а вопрос о нём заворачиваем в `try`.
            page.wait_for_function(
                "(()=>{try{return typeof phasing!=='undefined'}"
                "catch(e){return false}})()", timeout=30000)
            # Вкладка открывается так же, как её открывает человек: поле на
            # закрытой панели существует и невидимо, а «невидимое поле» и
            # «поля нет» на экране — одно и то же.
            page.click("button.tab[data-tab='phasing']")
            page.check("#phasingEnabled")
            page.wait_for_function(
                "document.querySelectorAll('#assignObjects select[data-object]').length>0",
                timeout=30000)

            got = page.evaluate("""() => Array.from(
                document.querySelectorAll('#assignObjects select[data-object]')
            ).map(s => ({key: s.dataset.object,
                         label: s.closest('.field').querySelector('label').textContent,
                         value: s.value}))""")
            expected = [o.key for o in core.STANDALONE_OBJECTS]
            assert [g["key"] for g in got] == expected
            assert [g["label"] for g in got] == [o.tep_label
                                                 for o in core.STANDALONE_OBJECTS]

            # Умолчание очереди — из реестра, а не из памяти страницы.
            wanted = {o.key: min(o.default_queue, 2) for o in core.STANDALONE_OBJECTS}
            assert {g["key"]: int(g["value"]) for g in got} == wanted

            # Выбор доезжает до состояния: поле, которое ничего не меняет,
            # на экране неотличимо от работающего.
            key = expected[0]
            # Выбирается очередь, ОТЛИЧНАЯ от умолчания: поставь то же число,
            # и проверка зелена даже у поля, которое ничего не меняет.
            assert wanted[key] != 1
            page.select_option(f"#assignObjects select[data-object='{key}']", "1")
            assert page.evaluate(f"phasing.discrete['{key}']") == 1
        finally:
            browser.close()
