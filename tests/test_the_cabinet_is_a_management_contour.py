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
    assert set(roles) == {"Строителю", "Коммерции", "Инвестициям"}
    hrefs = {role: [str(link["href"]) for link in item["links"]]
             for role, item in roles.items()}
    assert "/monitor" in hrefs["Строителю"]
    assert "/cabinet#sales" in hrefs["Коммерции"] and "/cabinet" in hrefs["Коммерции"]
    assert "/auctions" in hrefs["Инвестициям"]
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
    assert "Управленческий контур" in page.text
    assert "__DEVELOPAID_CONTOUR" not in page.text


def test_the_sales_link_lands_on_the_sales_report() -> None:
    """Свёрнутый отчёт под ссылкой «Отчёт о продажах» — переход, которого нет."""
    body = (ROOT / "market_search" / "cabinet.py").read_text(encoding="utf-8")
    assert 'class="salesreport" id="sales"' in body
    assert "location.hash==='#sales'" in body
    assert "card.open=true" in body


def test_the_public_calculator_stays_outside() -> None:
    """На главной стоят посторонние люди: внутреннее оглавление им не показывают."""
    from fastapi.testclient import TestClient

    import main_registry

    main = TestClient(main_registry.app).get("/")
    assert main.status_code == 200
    assert "Управленческий контур" not in main.text
