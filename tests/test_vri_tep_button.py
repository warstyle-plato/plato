"""Кнопка бота «Посчитать ВРИ и ТЭП»: регион → (для МО плотность) → участок →
карточка + файл.

МО считается полностью (РНГП, УПКС, Кд); Москва — по формулам калькулятора
ГлавАПУ, восстановленным из его выгрузок (СПП 94/6, НП 90%, население
33 м²/чел, соцпотребность на тысячу жителей); машино-места и плата за ВРИ
не реверсятся — их считает калькулятор в мини-приложении, и карточка честно
об этом говорит. Файл — формат калькулятора ГлавАПУ: его читает наш же
парсер, и числа совпадают.

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
    """Файл — полный 91-строчный формат калькулятора с секциями: первый
    вариант был огрызком из 13 строк, без секции ВРИ и с «ДОО 0 млн.руб»."""
    result = core.vri_tep_quick("mo", "", site_area_ha=22.423,
                                district="Городской округ Мытищи",
                                density_sqm_per_ha=8700)
    assert "Московская область" in result["card"]
    assert "плата за смену ВРИ — 4 643,9" in result["card"]
    import io
    import openpyxl
    sheet = openpyxl.load_workbook(io.BytesIO(result["file"]))["ТЭП"]
    assert sheet.max_row == 91, "формат неполный — калькулятор ГлавАПУ ведёт 91 строку"
    labels = {str(sheet.cell(row=r, column=1).value): r for r in range(2, 92)}
    assert sheet.cell(row=labels["44"], column=4).value == "4 643,921"
    assert sheet.cell(row=labels["18"], column=4).value == "453"
    assert sheet.cell(row=labels["22"], column=4).value == "950"
    parsed = core.parse_glavapu_xlsx(result["file"], result["filename"])
    normalized = parsed["normalized"]
    assert normalized["site_area_ha"] == pytest.approx(22.423)
    assert normalized["apartment_area_sqm"] == pytest.approx(195080.0, rel=0.001)
    assert normalized["change_vri_mln"] == pytest.approx(4643.921, rel=0.001)
    assert normalized["actual_kindergarten_places"] == pytest.approx(453)


def test_the_msk_branch_follows_the_glavapu_formulas(monkeypatch):
    """Московская ветка воспроизводит формулы калькулятора ГлавАПУ,
    восстановленные по двум его выгрузкам: население 33 м²/чел, соцпотребность
    на тысячу жителей. Первый вариант отдавал только площади."""
    monkeypatch.setattr(core, "analyze_cadastral_territory", lambda req: {
        "territory": {"area_ha": 0.651, "district": "Савеловский",
                      "cadastral_quarter": "77:09:0004014"},
        "coefficients": {"rail": 0.75, "rent": 0.1281},
    })
    result = core.vri_tep_quick("msk", "77:09:0004014:13")
    assert "Москва" in result["card"]
    assert "мини-приложении" in result["card"]
    import io
    import math
    import openpyxl
    sheet = openpyxl.load_workbook(io.BytesIO(result["file"]))["ТЭП"]
    labels = {str(sheet.cell(row=r, column=1).value): r for r in range(2, 92)}
    # 0,651 га × 35 000 × 0,94 × 0,65 = 13 921 м² квартир → 422 человека.
    population = math.ceil(0.651 * 35000 * 0.94 * 0.65 / 33)
    assert population == 422
    assert sheet.cell(row=labels["4"], column=4).value == "422"
    assert sheet.cell(row=labels["30"], column=4).value == "19"   # round(422×0,044)
    assert sheet.cell(row=labels["31"], column=4).value == "38"   # ceil(422×0,09)
    assert sheet.cell(row=labels["33"], column=4).value == "6"    # ceil(422×0,0133)
    assert sheet.cell(row=labels["34"], column=4).value == "3"    # ceil(422×0,0065)
    assert sheet.cell(row=labels["32"], column=4).value == "9"
    # Машино-места и ВРИ бот не реверсирует — они честные нули с отсылкой.
    assert sheet.cell(row=labels["42"], column=4).value == "0"
    assert sheet.cell(row=labels["44"], column=4).value == "0"
    parsed = core.parse_glavapu_xlsx(result["file"], result["filename"])
    assert parsed["normalized"]["site_area_ha"] == pytest.approx(0.651)


def test_the_msk_branch_finds_the_parcel_by_address(monkeypatch):
    """«Мишина 46 Москва» падал: анализ территории ждёт кадастры. Теперь
    адрес сперва проходит через тот же поиск ЕГРН, что и основной бот."""
    seen: dict[str, str] = {}
    monkeypatch.setattr(core, "land_lookup_via_core", lambda query: seen.update(
        {"query": query}) or {"results": [
            {"kind": "land", "cadastral_number": "77:09:0004014:13"},
            {"kind": "building", "cadastral_number": "77:09:0004014:1000"},
        ]})
    analyzed: dict[str, list] = {}
    monkeypatch.setattr(core, "analyze_cadastral_territory", lambda req: analyzed.update(
        {"numbers": list(req.cadastral_numbers)}) or {
        "territory": {"area_ha": 0.651, "district": "Савеловский"},
        "coefficients": {},
    })
    result = core.vri_tep_quick("msk", "Мишина 46 Москва")
    assert seen["query"] == "Мишина 46 Москва"
    assert analyzed["numbers"] == ["77:09:0004014:13"], \
        "в анализ должны уходить только земельные участки"
    assert "0,6510" in result["card"]


def test_the_msk_address_without_a_parcel_reads_like_advice(monkeypatch):
    monkeypatch.setattr(core, "land_lookup_via_core", lambda query: {"results": []})
    with pytest.raises(Exception) as err:
        core.vri_tep_quick("msk", "несуществующий адрес")
    assert "кадастровый номер" in str(getattr(err.value, "detail", err.value))


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
    assert wrapper._vritep_region(42) == "mo_density", \
        "МО начинается с вопроса о плотности"
    assert "по умолчанию" in sent[-1]["text"]
    handled = wrapper._vritep_handle_text(42, "35")
    assert handled
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
    # Участок прислали, минуя вопрос о плотности — берётся умолчание 35
    # тыс. м² СПП/га, то есть ≈ 21 385 м² квартир на гектар.
    assert calls[-1]["density_sqm_per_ha"] == pytest.approx(35 * 1000 * 0.94 * 0.65)


def test_the_button_lives_in_both_menus():
    """Стартовое меню бота живёт в движке, меню помощи — в обёртке: кнопка
    была только во втором, и /start её не показывал."""
    legacy = open("main_legacy.py", encoding="utf-8").read()
    assert legacy.count('"vritep_start"') >= 1, "кнопки нет в стартовом меню"
    wrapper_src = open("main.py", encoding="utf-8").read()
    assert wrapper_src.count('"vritep_start"') >= 2, \
        "кнопка или колбэк пропали из обёртки"


def test_the_density_is_parsed_from_the_bot_text(monkeypatch, tmp_path):
    monkeypatch.setattr(wrapper, "_STATE_DIR", tmp_path)
    calls: list[dict] = []
    monkeypatch.setattr(wrapper, "_send_message", lambda *a, **kw: None)
    monkeypatch.setattr(core, "_telegram_send_document_bytes", lambda *a, **kw: None)
    monkeypatch.setattr(core, "vri_tep_quick",
                        lambda region, query, **kw: calls.append(
                            {"region": region, "query": query, **kw}) or {
                            "card": "к", "file": b"PK", "filename": "f.xlsx"})
    wrapper._vritep_ask_input(42, "mo")
    wrapper._vritep_handle_text(42, "22,4 га Городской округ Мытищи плотность 8700")
    assert calls[-1]["density_sqm_per_ha"] == pytest.approx(8700)
    assert calls[-1]["site_area_ha"] == pytest.approx(22.4)
    assert calls[-1]["district"] == "Городской округ Мытищи"


def test_the_density_step_understands_both_metrics(monkeypatch, tmp_path):
    """Ответ на вопрос о плотности: до 1000 — тыс. м² СПП/га по метрике
    ГлавАПУ, больше — уже м² квартир/га; «квартир 8700» — явная метрика РНГП."""
    monkeypatch.setattr(wrapper, "_STATE_DIR", tmp_path)
    calls: list[dict] = []
    monkeypatch.setattr(wrapper, "_send_message", lambda *a, **kw: None)
    monkeypatch.setattr(core, "_telegram_send_document_bytes", lambda *a, **kw: None)
    monkeypatch.setattr(core, "vri_tep_quick",
                        lambda region, query, **kw: calls.append(
                            {"region": region, "query": query, **kw}) or {
                            "card": "к", "file": b"PK", "filename": "f.xlsx"})
    assert wrapper._vritep_mo_density("35") == pytest.approx(35 * 1000 * 0.94 * 0.65)
    assert wrapper._vritep_mo_density("8 700") == pytest.approx(8700)
    assert wrapper._vritep_mo_density("квартир 8700") == pytest.approx(8700)
    assert wrapper._vritep_mo_density("50:12:0100131:497") is None

    wrapper._vritep_ask_input(42, "mo")
    wrapper._vritep_handle_text(42, "14,3")
    wrapper._vritep_handle_text(42, "10 га Городской округ Мытищи")
    assert calls[-1]["density_sqm_per_ha"] == pytest.approx(14.3 * 1000 * 0.94 * 0.65)


def test_the_native_menu_and_the_command_open_the_button(monkeypatch, tmp_path):
    """Нативное меню Telegram собирается из setMyCommands — кнопки там не
    было, и /vritep бот не понимал."""
    wrapper_src = open("main.py", encoding="utf-8").read()
    assert '{"command": "vritep", "description": "Посчитать ВРИ и ТЭП"}' in wrapper_src
    monkeypatch.setattr(wrapper, "_STATE_DIR", tmp_path)
    sent: list[str] = []
    monkeypatch.setattr(wrapper, "_send_message",
                        lambda chat_id, text, **kw: sent.append(text))
    wrapper._handle_message({"chat": {"id": 42}, "from": {"id": 42},
                             "text": "/vritep"})
    assert sent and "Выберите регион" in sent[-1]
