"""Площадь ЗУ в шапке отчёта складывается из земли и ни из чего больше.

Плитка первой страницы складывала площади ВСЕХ найденных объектов разбора,
у которых есть контур, — то есть метры зданий вставали в «Площадь ЗУ» рядом
с метрами земли. На КРТ по ул. Архитектора Власова это дало 4 899 м² при
3 407,02 по ЕГРН, а ровно с 0,3407 га запущен калькулятор ГлавАПУ: число
шапки спорило с основанием всего расчёта (владелец, 21.09.2026).

Проверяется то, что видно: тексты плитки, а не список объектов, — в
исходнике сломанная и починенная версии выглядят одинаково осмысленно.
"""

from __future__ import annotations

import main_legacy as core
import pdf_first_page_extension as base


def _texts(flowables) -> list[str]:
    """Все подписи собранного блока, как их увидит читатель PDF."""
    found: list[str] = []

    def walk(node) -> None:
        if isinstance(node, (list, tuple)):
            for item in node:
                walk(item)
            return
        text = getattr(node, "text", None)
        if isinstance(text, str):
            found.append(text)
        for attribute in ("_content", "_cellvalues"):
            child = getattr(node, attribute, None)
            if child is not None:
                walk(child)

    walk(flowables)
    return found


def _payload(results, *, site_area_ha: float = 0.0) -> dict:
    return {
        "inputs": {"_land_lookup": {"results": results}, "site_area_ha": site_area_ha},
        "tep": {},
        "result": {"summary": {}, "report": {}, "tep": {"total": {"gns": 33610, "saleable": 18000}}},
    }


def _land(number: str, area: float) -> dict:
    return {"found": True, "kind": "land", "cadastral_number": number,
            "area_sqm": area,
            "contour_merc": [[[0.0, 0.0], [10.0, 0.0], [10.0, 10.0], [0.0, 0.0]]]}


def _building(number: str, area: float) -> dict:
    return {"found": True, "kind": "building", "cadastral_number": number,
            "area_sqm": area,
            "contour_merc": [[[1.0, 1.0], [2.0, 1.0], [2.0, 2.0], [1.0, 1.0]]]}


def _tile(monkeypatch, payload) -> list[str]:
    # Схема участка тут ни при чём, а её рисовальщик подменяет `pdf_first_page_v2`
    # на весь процесс: проверка не должна зависеть от того, кто шёл в прогоне
    # раньше.
    monkeypatch.setattr(base, "_parcel_drawing", lambda payload, core, **kw: object())
    return _texts(base._front_page_flowables(payload, core))


def _value_after(texts: list[str], label: str) -> str:
    assert label in texts, f"строки «{label}» в плитке нет: {texts}"
    return texts[texts.index(label) + 1]


def test_the_plot_area_adds_up_parcels_only(monkeypatch):
    """Метры ОКС в «Площадь ЗУ» не идут — и сами не пропадают."""
    lands = [_land("77:06:0003016:32", 2227.02), _land("77:06:0003016:1000", 1180.0)]
    building = _building("77:06:0003016:2001", 1492.0)
    # Предохранитель: без своих метров у ОКС проверка была бы зелёной и на
    # коде, который складывает всё подряд.
    assert building["area_sqm"] > 0

    texts = _tile(monkeypatch, _payload(lands + [building]))

    assert _value_after(texts, "Площадь ЗУ") == "3 407 м²"
    assert "4 899 м²" not in texts
    assert _value_after(texts, "ОКС, вне площади ЗУ") == "1 · 1 492 м²"


def test_a_parcel_without_geometry_still_counts(monkeypatch):
    """Контур нужен рисунку, а не счёту: участок без геометрии — это земля."""
    plain = _land("77:06:0003016:1000", 1180.0)
    del plain["contour_merc"]
    texts = _tile(monkeypatch, _payload([_land("77:06:0003016:32", 2227.02), plain]))

    assert _value_after(texts, "Площадь ЗУ") == "3 407 м²"


def test_a_premise_is_not_called_a_building(monkeypatch):
    """Имя строки идёт за составом: «ОКС» поверх помещения — чужое слово."""
    premise = {"found": True, "kind": "premise", "cadastral_number": "77:06:0003016:5001",
               "area_sqm": 84.0, "contour_merc": []}
    texts = _tile(monkeypatch, _payload([_land("77:06:0003016:32", 2227.02), premise]))

    assert "ОКС, вне площади ЗУ" not in texts
    assert _value_after(texts, "Объекты ЕГРН, вне площади ЗУ") == "1 · 84 м²"


def test_without_parcels_the_area_names_its_source(monkeypatch):
    """Вписанная руками площадь — не ответ реестра, и так и подписана."""
    texts = _tile(monkeypatch, _payload([_building("77:06:0003016:2001", 1492.0)],
                                        site_area_ha=0.4899))

    assert _value_after(texts, "Площадь ЗУ") == "4 899 м² · вписана руками"


def test_an_unknown_area_is_not_a_zero(monkeypatch):
    """Ноль в клетке читается как посчитанный ноль, а мы не знаем."""
    texts = _tile(monkeypatch, _payload([_building("77:06:0003016:2001", 0.0)]))

    assert _value_after(texts, "Площадь ЗУ") == "—"
