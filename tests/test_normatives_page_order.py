"""Порядок страницы «Нормативная документация» (/normatives).

Владелец, 26.10.2026: «разнобой какой-то в последовательности и значимости
документов». Схема (выбрана владельцем): сверху «Требует внимания» — только
новость источника, а нашу очередь сверки видит лишь администратор; затем
разделы по уровню акта (федеральные законы и кодексы, своды правил, Москва,
Московская область); внутри раздела сначала акты, от которых зависят деньги
расчёта; заменённые и отменённые — в свёрнутой «Истории» внизу.

Порядок меряется на отрисованной странице, а не по позиции литералов в
исходнике: разметку собирает `_page`, браузер показывает её как есть.
"""
from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))

import normatives_registry as registry  # noqa: E402
from test_normatives_registry import _checker, _request  # noqa: E402


def _rendered(rows: list[dict], admin: bool = False) -> list[dict]:
    """Разделы и карточки так, как их видит браузер: заголовок, видимые имена."""
    from browser import chromium_or_skip
    from playwright.sync_api import sync_playwright

    chrome = chromium_or_skip()
    core = SimpleNamespace(_is_admin_request=_checker(answer=admin))
    page = registry._page(_request("key=x" if admin else ""), core)
    with sync_playwright() as pw:
        browser = pw.chromium.launch(executable_path=str(chrome))
        try:
            tab = browser.new_page()
            tab.set_content(page)
            return tab.evaluate("""() => [...document.querySelectorAll('.nsection')].map(s => ({
                key: s.dataset.section,
                title: s.querySelector('.sechead').innerText,
                open: s.tagName !== 'DETAILS' || s.open,
                cards: [...s.querySelectorAll('.ncard')].map(c => ({
                    // textContent, а не innerText: карточки свёрнутой «Истории»
                    // не отрисованы, и innerText у них пуст.
                    name: c.querySelector('h2').textContent.trim(),
                    shown: c.checkVisibility(),
                    impact: ((c.querySelector('.impact') || {}).textContent || '').trim()}))}))""")
        finally:
            browser.close()


def _rows() -> list[dict]:
    return registry._load_registry()


def test_every_row_says_its_level_and_its_weight() -> None:
    """Уровень и влияние записаны в строке, а не угаданы по названию."""
    levels = {key for key, _ in registry.PAGE_LEVELS}
    for row in _rows():
        assert row.get("level") in levels, row["id"]
        assert row.get("impact") in registry.IMPACT_LABELS, row["id"]


def test_the_sections_go_by_level_and_history_is_last_and_folded(monkeypatch) -> None:
    rows = _rows()
    monkeypatch.setattr(registry, "_merged_registry", lambda: rows)
    sections = _rendered(rows)
    keys = [s["key"] for s in sections]
    assert keys[:4] == ["federal_law", "rules", "moscow", "mo"], keys
    assert keys[-1] == "history", keys
    history = sections[-1]
    # Свёрнута: карточки истории не видны, пока её не раскрыли.
    assert history["open"] is False
    assert not any(card["shown"] for card in history["cards"])
    names = " ".join(card["name"] for card in history["cards"])
    assert "СП 42.13330.2016" in names and "СП 154.13130.2013" in names, names
    current = " ".join(card["name"] for s in sections[:-1] for card in s["cards"])
    assert "СП 42.13330.2016" not in current and "СП 42.13330.2026" in current
    # 214-ФЗ — федеральный закон, СП 113 — свод правил, 593-ПП — Москва.
    where = {card["name"].split(" — ")[0]: s["key"] for s in sections for card in s["cards"]}
    assert where["214-ФЗ"] == "federal_law" and where["СП 113.13330.2023"] == "rules"
    assert where["593-ПП"] == "moscow" and where["1745-ПП"] == "mo"


def test_inside_a_section_money_goes_first(monkeypatch) -> None:
    rows = _rows()
    monkeypatch.setattr(registry, "_merged_registry", lambda: rows)
    for section in _rendered(rows)[:-1]:
        weights = [card["impact"] for card in section["cards"]]
        money = registry.IMPACT_LABELS["money"]
        if money in weights:
            first_other = next((i for i, w in enumerate(weights) if w != money), len(weights))
            assert all(w != money for w in weights[first_other:]), (section["key"], weights)
    moscow = next(s for s in _rendered(rows) if s["key"] == "moscow")
    assert moscow["cards"][0]["impact"] == registry.IMPACT_LABELS["money"]


def test_attention_shows_source_news_to_everyone_and_our_queue_to_the_admin(monkeypatch) -> None:
    """Новость источника — наверх всем; «не сверено нами» — только администратору.

    Владелец, 07.09.2026: «Зачем пользователю видеть что источник требует
    проверки» — наша очередь читателю не показывается.
    """
    rows = [dict(row) for row in _rows()]
    by_id = {row["id"]: row for row in rows}
    by_id["moscow-945-pp"]["check"] = {"result": "changed"}
    by_id["moscow-1160-pp-parks"]["status"] = "review_required"
    monkeypatch.setattr(registry, "_merged_registry", lambda: rows)

    reader = _rendered(rows)
    assert reader[0]["key"] == "attention"
    names = [card["name"] for card in reader[0]["cards"]]
    assert any(name.startswith("945-ПП") for name in names), names
    assert not any(name.startswith("1160-ПП") for name in names), names

    admin = _rendered(rows, admin=True)
    names = [card["name"] for card in admin[0]["cards"]]
    assert any(name.startswith("1160-ПП") for name in names), names
    # Карточка стоит один раз: в «внимании», а не ещё и в своём разделе.
    total = [card["name"] for s in admin for card in s["cards"]]
    assert len(total) == len(rows)


def test_without_news_there_is_no_empty_attention_block(monkeypatch) -> None:
    rows = [dict(row, check={}) for row in _rows()]
    monkeypatch.setattr(registry, "_merged_registry", lambda: rows)
    assert _rendered(rows)[0]["key"] == "federal_law"


def test_the_tiles_and_filters_follow_the_sections(monkeypatch) -> None:
    """Плитки сверху идут в порядке разделов, кнопка «Москва» оставляет Москву."""
    from browser import chromium_or_skip
    from playwright.sync_api import sync_playwright

    rows = [dict(row, check={}) for row in _rows()]
    monkeypatch.setattr(registry, "_merged_registry", lambda: rows)
    core = SimpleNamespace(_is_admin_request=_checker(answer=False))
    page = registry._page(_request(), core)
    with sync_playwright() as pw:
        browser = pw.chromium.launch(executable_path=str(chromium_or_skip()))
        try:
            tab = browser.new_page()
            tab.set_content(page)
            tiles = tab.eval_on_selector_all(".summary span", "xs => xs.map(x => x.innerText)")
            assert tiles[:4] == ["Федеральные законы и кодексы", "Своды правил", "Москва",
                                 "Московская область"], tiles
            assert tiles[-1].startswith("История"), tiles
            tab.click('.filters button[data-filter="moscow"]')
            shown = tab.eval_on_selector_all(
                ".nsection", "xs => xs.filter(x => x.checkVisibility()).map(x => x.dataset.section)")
            assert shown == ["moscow"], shown
            tab.click('.filters button[data-filter="history"]')
            assert tab.eval_on_selector("details.history", "x => x.open") is True
        finally:
            browser.close()
