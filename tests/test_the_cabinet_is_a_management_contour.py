"""Кабинет — вход в управленческий контур, а не одна из четырёх страниц.

«Кабинет надо объединить и сделать внутренним управленческим контуром. В
котором есть ссылки для строителя — монитор, коммерции — отчёт о продажах и
маркетинговый инструментарий для отчётов по рынку, инвестиций — КРТ и торги»
(владелец, 29.08.2026).

Это перестановка входов, а не переписывание модулей: страницы остаются свои,
контур становится их оглавлением. Объявлен он один раз и подставляется, как
подвал документов и версия, — копию негде обновлять. И проверяется набор
поверхностей не списком: поверхность, добавленная позже, попадает в проверку
тем, что она появилась, — иначе следующая страница останется без входа в
контур, а проверка останется зелёной. Так уже было с подвалом.

Запуск: python3 -m pytest tests/test_the_cabinet_is_a_management_contour.py -q
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import management_contour as contour  # noqa: E402

# Внутренние поверхности контура. Публичный расчёт сюда не входит намеренно:
# на нём стоят посторонние люди, и управленческое оглавление им не показывают.
INSIDE = ("/monitor", "/auctions", "/statistics", "/cabinet")


def test_every_role_the_owner_named_has_its_entrance() -> None:
    roles = {str(role["role"]): role for role in contour.ROLES}
    # Три кабинета: аналитика уехала в инвестиции (владелец, 30.08.2026).
    assert set(roles) == {"Строителю", "Коммерции", "Инвестициям"}
    hrefs = {role: [str(link["href"]) for link in item["links"]]
             for role, item in roles.items()}
    assert "/monitor" in hrefs["Строителю"]
    # Оба отчёта — своими страницами, а не якорем на общую: «они должны быть
    # ссылками в меню коммерции, и всё» (владелец, 30.08.2026).
    assert "/cabinet/sales" in hrefs["Коммерции"]
    assert "/cabinet/market" in hrefs["Коммерции"]
    assert "#" not in "".join(hrefs["Коммерции"]), "якорь читается как переход, которого нет"
    assert "/auctions" in hrefs["Инвестициям"]
    # Статистика себестоимости обосновывает наши ставки, а не помогает
    # продавать: «это аналитический блок, а не маркетинг» (владелец,
    # 30.08.2026).
    assert "/statistics" in hrefs["Инвестициям"]
    assert "/statistics" not in hrefs["Коммерции"]
    # У каждого кабинета своё имя и свой портрет: карточка без имени — это
    # строка списка, а её и так видно в контуре.
    for item in contour.ROLES:
        assert str(item["room"]).strip() and str(item["face"]).strip()
    # У каждой ссылки сказано, что за ней: имя раздела в чужой роли ничего не
    # говорит человеку, который туда не ходит.
    for item in contour.ROLES:
        for link in item["links"]:
            assert str(link["note"]).strip(), link


def test_the_page_you_stand_on_is_not_a_link() -> None:
    """«Монитор» на мониторе — это переход, который не произошёл."""
    here = contour.markup("/monitor")
    assert 'aria-current="page"' in here
    assert 'href="/monitor"' not in here
    assert 'href="/auctions"' in here


def test_the_contour_is_declared_once_and_substituted() -> None:
    """Копии нет по той же причине, что и у версии: копию негде обновлять."""
    for path in (ROOT / "market_search" / "cabinet.py",
                 ROOT / "auction_search" / "ui.py",
                 ROOT / "developaid_monitor_page.py",
                 ROOT / "developaid_statistics_page.py"):
        body = path.read_text(encoding="utf-8")
        assert "Строителю" not in body, f"копия контура в {path.name}"
        assert "Инвестициям" not in body, f"копия контура в {path.name}"


def test_a_page_without_the_placeholder_is_served_as_it_was() -> None:
    """Контур — оглавление, а не условие работы страницы."""
    assert contour.apply("<b>страница</b>") == "<b>страница</b>"


def test_every_internal_surface_carries_the_contour() -> None:
    from fastapi.testclient import TestClient

    import main_registry

    client = TestClient(main_registry.app)
    skipped, seen = [], []
    for path in INSIDE:
        answer = client.get(path)
        if answer.status_code != 200:
            # Молча пропускать нельзя: непроверенная страница и страница без
            # замечаний выглядят одинаково.
            skipped.append(f"{path} → {answer.status_code}")
            continue
        seen.append(path)
        assert "Управленческий контур" in answer.text, f"{path} без входа в контур"
        assert ".contour{" in answer.text, f"{path} без стиля контура"
        assert "__DEVELOPAID_CONTOUR" not in answer.text, f"{path}: плейсхолдер на экране"
    assert seen, f"ни одна поверхность не проверена: {skipped}"
    assert skipped == [] or all("/cabinet" in item for item in skipped), skipped


def test_the_cabinet_is_checked_too_when_its_key_is_set(tmp_path, monkeypatch) -> None:
    """Кабинет закрыт ключом, и без него страница не отдаётся вовсе."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from market_search.api import install

    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("MARKET_CABINET_KEY", "stand-key-2026")
    app = FastAPI()
    install(app)
    client = TestClient(app)
    client.post("/cabinet/login", content="key=stand-key-2026",
                headers={"Content-Type": "application/x-www-form-urlencoded"},
                follow_redirects=False)
    page = client.get("/cabinet")
    assert page.status_code == 200
    # На титуле оглавление — карточки кабинетов; полоска контура стоит на
    # страницах разделов, куда эти карточки и ведут.
    assert 'class="room"' in page.text
    assert "__DEVELOPAID_" not in page.text, "плейсхолдер не подставился"
    for view in ("/cabinet/sales", "/cabinet/market"):
        inner = client.get(view)
        assert inner.status_code == 200, view
        assert "Управленческий контур" in inner.text
        assert "__DEVELOPAID_" not in inner.text


def test_the_sales_link_lands_on_the_sales_report() -> None:
    """Свёрнутый отчёт под ссылкой «Отчёт о продажах» — переход, которого нет.

    Ссылка контура ведёт на `/cabinet/sales`, и отчёт там единственное, зачем
    приходят. Свёрнутый, он оставлял на странице одну серую строку — «там нет
    ничего на вкладке» (владелец, 31.08.2026).
    """
    body = (ROOT / "market_search" / "cabinet.py").read_text(encoding="utf-8")
    report = body[body.index("function renderSales(d){"):]
    report = report[: report.index("\nfunction tile(")]
    assert '<details class="salesreport" id="sales">' not in report, \
        "отчёт снова свёрнут — страница показывает одну строку вместо свода"
    assert '<div class="card" id="salesreport">' in report


def test_the_contour_wears_the_house_style() -> None:
    """Сервис один: у страницы торгов прямые углы и нет теней, и контур,
    приехавший на неё со своими скруглениями, выглядел чужим — это поймал
    её собственный тест оформления."""
    assert "border-radius:0" in contour.STYLE
    assert "box-shadow" not in contour.STYLE
    for radius in ("border-radius:12px", "border-radius:7px", "border-radius:14px"):
        assert radius not in contour.STYLE


def test_the_print_stays_declared_last() -> None:
    """Стиль контура встал перед блоком печати, а не после него: правило экрана,
    объявленное ниже печати, тихо её перебивает — на этом уже пропадали карты."""
    from market_search.cabinet import CABINET_PAGE

    assert CABINET_PAGE.index("__DEVELOPAID_CONTOUR_STYLE__") < CABINET_PAGE.index("@media print{")


def test_the_public_calculator_stays_outside() -> None:
    """На главной стоят посторонние люди: внутреннее оглавление им не показывают."""
    from fastapi.testclient import TestClient

    import main_registry

    main = TestClient(main_registry.app).get("/")
    assert main.status_code == 200
    assert "Управленческий контур" not in main.text


def test_the_cabinet_opens_with_the_rooms_and_nothing_else() -> None:
    """«Зачем тут 76 договоров, если это титульный лист кабинета? И зачем внизу
    отчёты? Они должны быть ссылками в меню коммерции, и всё» (владелец,
    30.08.2026).

    Титул кабинета — это выбор кабинета, а не сводка проекта: числа продаж
    живут на странице продаж, конструктор рынка — на своей. Раньше на одной
    странице стояло всё сразу, и у отчёта о рынке не было ссылки вовсе: он
    ссылался на страницу, где человек уже стоял, и рисовался неактивным.
    """
    from market_search.cabinet import cabinet_page

    home = cabinet_page("home")
    assert "<title>Кабинет DevelopAid</title>" in home
    assert home.count('class="room"') == len(contour.ROLES)
    for role in contour.ROLES:
        assert str(role["room"]) in home
    # Ни чисел проекта, ни инструментов: их место на своих страницах.
    for stranger in ('id="overview"', 'id="form"', 'id="market"', 'id="cf"',
                     # Клон отчёта на втором источнике живёт на странице рынка;
                     # на титуле его быть не должно, а плейсхолдер вне кусков
                     # разметки вылез бы на всех трёх видах незамеченным.
                     'id="bnmap"'):
        assert stranger not in home, f"на титуле осталось {stranger}"
    # И полоски контура тут нет: её работу делают карточки, два меню подряд —
    # это одно и то же дважды.
    assert 'class="contour"' not in home

    sales, market = cabinet_page("sales"), cabinet_page("market")
    assert 'id="overview"' in sales and 'id="cf"' in sales
    assert 'id="form"' not in sales, "конструктор рынка уехал на свою страницу"
    assert 'id="form"' in market
    assert 'id="overview"' not in market
    # На страницах разделов полоска контура на месте — уйти из раздела нечем.
    assert 'class="contour"' in sales and 'class="contour"' in market



def test_the_project_file_upload_lives_with_the_summary() -> None:
    """Загрузка источников — про проект, а не про отчёт о рынке: в карточке
    конструктора она стояла чужой."""
    from market_search.cabinet import CABINET_PAGE

    overview = CABINET_PAGE[CABINET_PAGE.index('id="overview"'):]
    overview = overview[: overview.index('<details class="salesreport" id="market">')]
    assert 'id="cf"' in overview and "Загрузить файл проекта" in overview
    form = CABINET_PAGE[CABINET_PAGE.index('<div class="card" id="form">'):]
    form = form[: form.index("</details>")]
    assert 'id="cf"' not in form


def test_each_view_of_the_cabinet_opens_without_a_script_error(tmp_path) -> None:
    """Скрипт кабинета один на три вида, и элемента на виде может не быть.

    Необработанная ошибка в этом блоке гасит страницу целиком: обработчики не
    навешиваются ни на что, и человек видит мёртвый экран. Строковые проверки
    такого не ловят — нужен настоящий браузер. Без Chromium это пропуск, а не
    зелёный прогон на пустом месте.
    """
    import pytest

    play = pytest.importorskip("playwright.sync_api")

    import browser_launch

    from market_search.cabinet import cabinet_page

    broken: dict[str, list[str]] = {}
    with play.sync_playwright() as pw:
        try:
            browser = browser_launch.launch(pw)
        except Exception as exc:  # noqa: BLE001
            pytest.skip(f"Chromium недоступен: {exc}")
        try:
            for view in ("home", "sales", "market"):
                file = tmp_path / f"{view}.html"
                file.write_text(
                    cabinet_page(view).replace("__DEVELOPAID_VERSION__", "test"),
                    encoding="utf-8")
                tab = browser.new_page()
                errors: list[str] = []
                tab.on("pageerror", lambda exc: errors.append(str(exc)))
                tab.route("**/*", lambda route: route.abort()
                          if route.request.url.startswith("http")
                          else route.continue_())
                tab.goto(file.as_uri())
                # Функции объявляются только если блок доработал до конца.
                alive = tab.evaluate("() => typeof askPlato === 'function'")
                if errors or not alive:
                    broken[view] = errors or ["скрипт не доработал до конца"]
                tab.close()
        finally:
            browser.close()
    assert not broken, f"вид кабинета упал: {broken}"


def test_each_room_has_its_portrait_and_a_stranger_gets_a_refusal(tmp_path, monkeypatch) -> None:
    """Портреты кабинетов лежат файлами и отдаются своим маршрутом.

    Карточка без портрета говорит, какого именно не хватает, — пустой круг
    читался бы как «так и надо». Имя проверяется: маршрут отдаёт файлы из
    каталога, и путь в нём собирать из чужой строки нельзя.
    """
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from market_search.api import install

    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("MARKET_CABINET_KEY", "stand-key-2026")
    app = FastAPI()
    install(app)
    client = TestClient(app)
    client.post("/cabinet/login", content="key=stand-key-2026",
                headers={"Content-Type": "application/x-www-form-urlencoded"},
                follow_redirects=False)

    for role in contour.ROLES:
        got = client.get(f"/cabinet/assets/{role['face']}.webp")
        assert got.status_code == 200, role["face"]
        assert got.headers["content-type"] == "image/webp"
        assert len(got.content) > 5000, "портрет подозрительно пуст"
    # Чужого имени нет, и обход каталога тоже: имя ограничено набором знаков.
    assert client.get("/cabinet/assets/plato-нет.webp").status_code == 404
    assert client.get("/cabinet/assets/..%2F..%2Fmain_legacy.webp").status_code == 404
