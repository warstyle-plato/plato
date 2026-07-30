"""Площадь есть, продавать нечего — это дырка в ТЭП, а не убыточный проект.

ГлавАПУ отдал 10,58 га жилой застройки с «площадью квартир» 0 м². Себестоимость
считается от ГНС, поэтому расходы вышли 23,2 млрд ₽, выручка — 2,3 млрд ₽ (один
паркинг), а карточка вынесла вердикт «предварительно нецелесообразна». Вердикт
относился к непрочитанной строке 10, а не к экономике проекта.

Запуск: python3 -m pytest tests -q
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import main as wrapper  # noqa: E402

core = wrapper.core


def tep(**overrides):
    rows = {
        "apartments": {"label": "Квартиры", "gns": 250000.0, "total_area": 220000.0,
                       "saleable": 160000.0, "transfer": 0, "units": 2600},
        "underground_parking": {"label": "Подземный паркинг", "gns": 43470.0,
                                "total_area": 43470.0, "saleable": 0, "transfer": 0,
                                "units": 1242},
        "kindergarten": {"label": "ДОУ", "gns": 3000.0, "total_area": 3000.0,
                         "saleable": 0, "transfer": 3000.0, "units": 250},
    }
    for key, patch in overrides.items():
        rows[key] = {**rows[key], **patch}
    return rows


def test_a_healthy_tep_is_not_flagged():
    assert core._tep_cost_without_revenue(tep()) == []


def test_apartments_without_saleable_area_are_flagged():
    broken = core._tep_cost_without_revenue(tep(apartments={"saleable": 0}))
    assert broken == ["Квартиры"]


def test_parking_sells_by_the_space_not_the_metre():
    """У паркинга продаваемой площади нет по устройству — выручка идёт с мест."""
    assert "Подземный паркинг" not in core._tep_cost_without_revenue(tep())


def test_a_social_object_is_never_flagged():
    """Садик строится и передаётся городу: выручки нет по существу."""
    assert core._tep_cost_without_revenue(
        {"kindergarten": {"label": "ДОУ", "gns": 3000.0, "saleable": 0,
                          "transfer": 0, "units": 0}}) == []


def test_an_empty_product_is_not_flagged():
    assert core._tep_cost_without_revenue(
        {"offices": {"label": "Офисы", "gns": 0, "saleable": 0, "units": 0}}) == []


def glavapu_file(apartment_area: str):
    """Настоящий файл ГлавАПУ: жилая застройка есть, строка 10 — под вопросом."""
    rows = [
        ["1", "Площадь территории", "га", "10,58"],
        ["7.1", "СПП жилая", "тыс. кв. м", "250,0"],
        ["9.1.1", "НП жилая", "тыс. кв. м", "220,0"],
        ["10", "Площадь квартир", "тыс. кв. м", apartment_area],
    ]
    return core._build_glavapu_xlsx_from_rows(rows, [["Район", "Даниловский"]])


def test_an_unread_apartment_row_is_named_in_the_warnings():
    """Ноль вместо непрочитанной строки уходил в расчёт молча."""
    parsed = core.parse_glavapu_xlsx(glavapu_file("н/д"), "ГлавАПУ.xlsx")

    assert parsed["normalized"]["residential_spp_sqm"] == 250000.0
    assert not parsed["normalized"]["apartment_area_sqm"]
    assert any("квартир не прочитана" in w for w in parsed["warnings"]), parsed["warnings"]


def test_a_readable_apartment_row_produces_no_warning():
    parsed = core.parse_glavapu_xlsx(glavapu_file("160,0"), "ГлавАПУ.xlsx")

    assert parsed["normalized"]["apartment_area_sqm"] == 160000.0
    assert not any("не прочитана" in w for w in parsed["warnings"])


def test_the_broken_import_produces_a_tep_the_check_catches():
    """Связка целиком: непрочитанная строка → ТЭП без продаж → сигнал."""
    parsed = core.parse_glavapu_xlsx(glavapu_file("н/д"), "ГлавАПУ.xlsx")
    assert core._tep_cost_without_revenue(parsed["mappings"]["tep"]) == ["Квартиры"]


def card_text(monkeypatch, tep_rows) -> str:
    """Собирает настоящую карточку Telegram и возвращает её текст."""
    sent: list[str] = []
    monkeypatch.setattr(core, "_telegram_verify_session", lambda s: {"chat_id": 42, "cad": []})
    monkeypatch.setattr(core, "_telegram_user_allowed", lambda c: True)
    monkeypatch.setattr(core, "_telegram_send_message",
                        lambda chat_id, text, **kw: sent.append(text))
    monkeypatch.setattr(core, "_telegram_web_app_url", lambda *a, **k: "https://example.org/")
    core.telegram_result(core.TelegramResultRequest(session="s", summary={
        "purchase_price_mln": 6500, "net_profit_mln": -20900, "llcr": 0.1,
        "revenue_mln": 2300, "total_expenses_mln": 23200,
        "calculated_bridge_mln": 6720, "pf_uncovered_peak_mln": 13360,
        "report_payload": {"tep": tep_rows},
    }))
    assert sent, "карточка не отправлена"
    return sent[0]


def test_the_card_does_not_judge_a_project_by_a_broken_tep(monkeypatch):
    """Вердикт «нецелесообразна» относился к дырке в ТЭП, а не к экономике."""
    text = card_text(monkeypatch, tep(apartments={"saleable": 0}))

    assert "ТЭП неполный" in text
    assert "Квартиры" in text
    assert "Предварительно нецелесообразна" not in text


def test_a_healthy_tep_still_gets_a_verdict(monkeypatch):
    """Убыточный проект с полным ТЭП обязан по-прежнему получать вывод."""
    text = card_text(monkeypatch, tep())

    assert "Предварительно нецелесообразна" in text
    assert "ТЭП неполный" not in text
