"""Карточка КРТ открывается со своего имени и не спорит с метками строки.

Три замечания владельца одного вечера (06.09.2026), и все три про одну колонку.

**«Жму и не могу открыть именно этот КРТ.»** Карточка — своё окно прокрутки:
`.side` держит `max-height` в высоту экрана, потому что таблица рядом длиной в
сотню тысяч пикселей. Прокрутку это окно помнило: замер в Chromium дал 1552 px
до нажатия на соседнюю строку и 159 px после — новая карточка открывалась
серединой, заголовок с именем площадки стоял на 142 px ВЫШЕ окна, и в окне
было видно «Что за площадка» чужой стройки. Со стороны это неотличимо от
«нажатие не сработало».

**«А где кнопки все? Платона вообще нет.»** То же окно: содержимое карточки
1580–2426 px при окне 874 px, а «Рекомендация Платона», «Поделиться» и
«Открыть krt.mos.ru» лежат на 1529 и 2375 px. Они достижимы прокруткой ВНУТРИ
карточки, и ничто об этом не говорило: полоса прокрутки у macOS накладная и
появляется только при движении.

**«Как одно и другое не исключают друг друга? Вход открыт куда?»** На строке
Полимерной ул., вл. 8 стояли метки «реновация — всё жильё» и «ГК
„СтройИнновация"», а шапка карточки писала «Вход не закрыт — но и торгов пока
нет». Оба факта у нас были — не сказана была их цена для входа, и складывать
её приходилось читателю. Жильё целиком уходит Программе реновации, значит
девелоперского продукта здесь нет вовсе (владелец, 03.09.2026), а названный
застройщик вход не закрывает — его определяют торги.

Проверяется настоящим браузером: прокрутка и видимость — это поведение, и
строкой в исходнике они не доказываются.

Запуск: python3 -m pytest tests/test_the_card_opens_at_its_name.py -q
"""

from __future__ import annotations

import sys
import threading
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

PORT = 18797

BIG = {"slug": "polimernaya-8", "name": "Полимерная ул., вл. 8 (Мартеновская ул.)",
       "status": "Планируемый", "okrug": "ВАО", "district": "Новогиреево",
       "area_ha": 12.97, "total_gfa_sqm": 305_440, "housing_gfa_sqm": 300_440}
OTHER = {"slug": "proshlyakova-9", "name": "Маршала Прошлякова ул., вл. 9",
         "status": "Планируемый", "okrug": "СЗАО", "district": "Строгино",
         "area_ha": 69.73, "total_gfa_sqm": 951_073, "housing_gfa_sqm": 580_096}

# Строка рейтинга: решение прочитано, весь жилой объём — Программе реновации,
# а публикация назвала застройщика. Ровно та пара, что стояла на экране.
RANK = {
    "requirements": {"renovation": {"mentioned": True, "area_sqm": 300_440,
                                    "basis": "zone_programme_clause",
                                    "quote": "объекты жилого назначения (для реализации "
                                             "Программы реновации) – 300 440 кв.м"}},
    "press_facts": {"available": True, "taken": False, "operator_named": [],
                    "developer_named": [{"name": "ГК «СтройИнновация»",
                                         "quote": "Застройщик ГК «СтройИнновация» в Москве и МО",
                                         "url": "https://realty.yandex.ru/zastroyschik/1754396/"}],
                    "city_needs": [], "agreement": [], "selling_now": [],
                    "buckets": [{"key": "developer_named",
                                 "title": "Застройщик назван", "heavy": False}]},
}


def _app():
    from fastapi import FastAPI

    from auction_search.api import install

    app = FastAPI()
    app.state.market_discovery_service = SimpleNamespace(
        krt=SimpleNamespace(
            catalogue=lambda **_: [dict(BIG), dict(OTHER)],
            status=lambda: {"complete": True, "refreshing": False},
            tender_lots_known=lambda: {},
            remember_tender_lots=lambda *_: None,
        ),
    )
    install(app)
    return app


def test_the_card_column_is_a_scroll_box_with_a_visible_bar():
    """Окно прокрутки объявлено вместе со своей полосой: без неё низа не видно."""
    from auction_search import ui

    page = ui.auctions_page(None)
    assert ".side::-webkit-scrollbar{" in page, \
        "у карточки нет своей полосы прокрутки — накладная не видна вовсе"
    assert "scrollbar-gutter:stable" in page, \
        "место под полосу не зарезервировано — содержимое дёргается при прокрутке"


@pytest.mark.timeout(240)
def test_in_a_real_browser_the_card_opens_at_its_name():
    """Нажатие на соседнюю строку показывает имя площадки, а не середину."""
    try:
        from playwright.sync_api import sync_playwright
    except Exception:  # noqa: BLE001
        pytest.skip("playwright недоступен")
    chrome = Path("/opt/pw-browsers/chromium-1194/chrome-linux/chrome")
    if not chrome.exists():
        pytest.skip("chromium в образе не найден")
    import uvicorn

    server = uvicorn.Server(uvicorn.Config(_app(), host="127.0.0.1", port=PORT,
                                           log_level="error"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    for _ in range(200):
        if server.started:
            break
        time.sleep(0.05)
    assert server.started
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(executable_path=str(chrome))
            page = browser.new_page(viewport={"width": 1440, "height": 900})
            errors: list[str] = []
            page.on("pageerror", lambda exc: errors.append(str(exc)))
            page.goto(f"http://127.0.0.1:{PORT}/auctions", wait_until="domcontentloaded")
            page.evaluate("switchTab(true)")
            for _ in range(40):
                page.wait_for_timeout(250)
                if page.evaluate("state.krt.length"):
                    break
            page.evaluate("(r)=>{state.krtRank['polimernaya-8']=r}", RANK)
            page.evaluate("filterKrt()")
            page.wait_for_timeout(150)

            page.evaluate("()=>selectKrt(state.krt.find(x=>x.slug==='polimernaya-8'))")
            page.wait_for_timeout(300)
            head = page.evaluate(
                "()=>document.querySelector('#krtSide .notice').textContent"
                ".replace(/\\s+/g,' ')")
            # Карточку дочитали до низа — и нажали соседнюю строку.
            page.evaluate("()=>{const s=document.getElementById('krtSide');s.scrollTop=s.scrollHeight}")
            page.wait_for_timeout(100)
            before = page.evaluate("()=>Math.round(document.getElementById('krtSide').scrollTop)")
            page.evaluate("()=>selectKrt(state.krt.find(x=>x.slug==='proshlyakova-9'))")
            page.wait_for_timeout(300)
            after = page.evaluate("""()=>{const s=document.getElementById('krtSide'),h=s.querySelector('h2');
              const r=h.getBoundingClientRect(),g=s.getBoundingClientRect();
              return {top:Math.round(s.scrollTop),name:h.textContent,
                      seen:r.top>=g.top-1&&r.bottom<=g.bottom+1,
                      tall:s.scrollHeight>s.clientHeight}}""")
            # Низ карточки достижим прокруткой самой карточки: кнопка Платона
            # лежит ниже окна, и добраться до неё можно только так.
            reach = page.evaluate("""()=>{const s=document.getElementById('krtSide');s.scrollTop=s.scrollHeight;
              const b=document.getElementById('krtPlato');if(!b)return null;
              const r=b.getBoundingClientRect(),g=s.getBoundingClientRect();
              return {seen:r.top>=g.top-1&&r.bottom<=g.bottom+1}}""")
            browser.close()
    finally:
        server.should_exit = True
        thread.join(timeout=10)

    assert not errors, errors
    # Шапка называет цену обоих фактов, а не оставляет их спорить с ней.
    assert "подрядчиком" in head, head
    assert "300 440" in head, "объём Программы реновации не назван"
    assert "ГК «СтройИнновация»" in head, "названный застройщик в шапке молчит"
    assert "не закрывает" in head, "не сказано, что застройщик вход не закрывает"
    assert before > 200, f"карточка не была прокручена — проверяется не то ({before})"
    assert after["tall"], "карточка короче окна — проверять нечего"
    assert after["top"] == 0, f"новая карточка открылась серединой: {after}"
    assert after["seen"], f"имя площадки вне окна карточки: {after}"
    assert reach and reach["seen"], "низ карточки прокруткой недостижим — кнопок не будет"
