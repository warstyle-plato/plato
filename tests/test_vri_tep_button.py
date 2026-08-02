"""Кнопка бота «Посчитать ВРИ и ТЭП»: регион → участок → карточка + файл.

МО считается полностью (РНГП, УПКС, Кд); для Москвы серверу доступны анализ
территории и методика DevelopAid 94/6 — точный ГлавАПУ живёт в
мини-приложении, и карточка честно об этом говорит. Файл — формат
калькулятора ГлавАПУ: его читает наш же парсер, и числа совпадают.

Запуск: python3 -m pytest tests -q
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import main as wrapper  # noqa: E402

core = wrapper.core


def test_the_mo_branch_counts_vri_and_returns_a_readable_file():
    result = core.vri_tep_quick("mo", "", site_area_ha=10.0,
                                district="Городской округ Мытищи")
    assert "Московская область" in result["card"]
    assert "плата за смену ВРИ" in result["card"]
    parsed = core.parse_glavapu_xlsx(result["file"], result["filename"])
    normalized = parsed["normalized"]
    assert normalized["site_area_ha"] == pytest.approx(10.0)
    assert normalized["apartment_area_sqm"] == pytest.approx(300000.0)
    assert (normalized["change_vri_mln"] or 0) > 0, "плата за ВРИ потерялась в файле"


def test_the_msk_branch_says_where_the_exact_calculation_lives(monkeypatch):
    monkeypatch.setattr(core, "analyze_cadastral_territory", lambda req: {
        "territory": {"area_ha": 0.651, "district": "Савеловский",
                      "cadastral_quarter": "77:09:0004014"},
        "coefficients": {"rail": 0.75, "rent": 0.1281},
    })
    result = core.vri_tep_quick("msk", "77:09:0004014:13")
    assert "Москва" in result["card"]
    assert "мини-приложении" in result["card"]
    parsed = core.parse_glavapu_xlsx(result["file"], result["filename"])
    assert parsed["normalized"]["site_area_ha"] == pytest.approx(0.651)


def test_the_bot_flow_asks_region_then_takes_the_parcel(monkeypatch, tmp_path):
    sent: list[dict] = []
    monkeypatch.setattr(wrapper, "_STATE_DIR", tmp_path)
    monkeypatch.setattr(wrapper, "_send_message",
                        lambda chat_id, text, **kw: sent.append(
                            {"text": text, "markup": kw.get("reply_markup")}))
    documents: list[str] = []
    monkeypatch.setattr(core, "_telegram_send_document_bytes",
                        lambda chat_id, data, name, **kw: documents.append(name))
    monkeypatch.setattr(core, "vri_tep_quick",
                        lambda region, query, **kw: {
                            "card": f"карточка {region} {query}",
                            "file": b"PK", "filename": "f.xlsx"})

    wrapper._start_vritep(42)
    assert "Выберите регион" in sent[-1]["text"]
    wrapper._vritep_ask_input(42, "mo")
    assert wrapper._vritep_region(42) == "mo"
    handled = wrapper._vritep_handle_text(42, "50:12:0100131:497")
    assert handled
    assert any("карточка mo 50:12:0100131:497" in item["text"] for item in sent)
    assert documents == ["f.xlsx"]
    assert wrapper._vritep_region(42) == "", "состояние не снято после расчёта"


def test_the_manual_area_and_district_are_parsed(monkeypatch, tmp_path):
    monkeypatch.setattr(wrapper, "_STATE_DIR", tmp_path)
    calls: list[dict] = []
    monkeypatch.setattr(wrapper, "_send_message", lambda *a, **kw: None)
    monkeypatch.setattr(core, "_telegram_send_document_bytes", lambda *a, **kw: None)
    monkeypatch.setattr(core, "vri_tep_quick",
                        lambda region, query, **kw: calls.append(
                            {"region": region, "query": query, **kw}) or {
                            "card": "к", "file": b"PK", "filename": "f.xlsx"})
    wrapper._vritep_ask_input(42, "mo")
    wrapper._vritep_handle_text(42, "10,5 га Городской округ Мытищи")
    assert calls[-1]["site_area_ha"] == pytest.approx(10.5)
    assert calls[-1]["district"] == "Городской округ Мытищи"
    assert calls[-1]["query"] == ""


def test_the_button_lives_in_both_menus():
    """Стартовое меню бота живёт в движке, меню помощи — в обёртке: кнопка
    была только во втором, и /start её не показывал."""
    legacy = open("main_legacy.py", encoding="utf-8").read()
    assert legacy.count('"vritep_start"') >= 1, "кнопки нет в стартовом меню"
    wrapper_src = open("main.py", encoding="utf-8").read()
    assert wrapper_src.count('"vritep_start"') >= 2, \
        "кнопка или колбэк пропали из обёртки"
