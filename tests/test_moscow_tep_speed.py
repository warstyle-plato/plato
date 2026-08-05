"""Расчёт Москвы не должен идти минуту.

Локально расчёт модели занимает доли секунды, PDF — полсекунды, книга — секунду.
Минуту брал путь ТЭП, и в нём было три платежа, которых человек не заказывал:

1. Сверка серверных формул со штатным калькулятором шла внутри запроса. Она
   стоит целого расчёта — заново спрашивает территорию у ГлавАПУ и собирает
   книгу ТЭП, — чтобы сравнить одиннадцать чисел. Дрейф методики случается раз
   в квартал, а платили за него каждым кликом.
2. Браузер закрывался после пятнадцати минут простоя. Бот не работает
   непрерывно: между двумя участками почти всегда больше пятнадцати минут, и
   холодный старт Chromium платился каждый раз.
3. Один участок считают по многу раз подряд — поменяли цену, пересчитали. ТЭП
   участка за это время не меняется, меняются наши вводные, а браузер
   поднимался заново.

Запуск: python3 -m pytest tests -q
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import main as wrapper  # noqa: E402

core = wrapper.core

_NUMBERS = ["77:01:0005006:7684"]


def _server_path(monkeypatch, rows_calls: dict):
    """Серверный путь с настоящим калькулятором, но без браузера."""
    def fake_rows(numbers, area_ha):
        rows_calls["count"] = rows_calls.get("count", 0) + 1
        return [{"code": "60", "name": "Озеленение", "unit": "га", "value": "1"}]

    monkeypatch.setattr(core, "_GLAVAPU_HEADLESS_ENABLED", True)
    monkeypatch.setattr(core, "_glavapu_headless_rows", fake_rows)
    monkeypatch.setattr(core, "analyze_cadastral_territory", lambda req: {
        "territory": {"area_ha": 0.1963}, "recognized": _NUMBERS,
        "coefficients": {"rent": 0.1281}, "warnings": []})
    monkeypatch.setattr(core, "import_cadastral_tep", lambda req: {
        "normalized": {"spp_total_sqm": 6870}, "source": {}, "warnings": []})


def test_the_same_parcel_is_not_recalculated_twice(monkeypatch):
    """Второй расчёт того же участка обязан обойтись без браузера."""
    calls: dict = {}
    _server_path(monkeypatch, calls)
    request = core.CadastralAnalysisRequest(cadastral_numbers=", ".join(_NUMBERS))

    first = core.cadastral_tep_server(request)
    second = core.cadastral_tep_server(request)

    assert calls["count"] == 1, "браузер поднялся во второй раз впустую"
    assert second["normalized"] == first["normalized"]
    assert "Штатный калькулятор" in second["source"]["format"], \
        "из кэша обязан приходить тот же расчёт, а не запасной"


def test_the_cache_answers_the_same_parcel_in_any_order(monkeypatch):
    """Порядок и пробелы в номерах — это тот же участок."""
    calls: dict = {}
    _server_path(monkeypatch, calls)
    core.cadastral_tep_server(core.CadastralAnalysisRequest(
        cadastral_numbers="77:01:0005006:7684"))
    core.cadastral_tep_server(core.CadastralAnalysisRequest(
        cadastral_numbers=" 77:01:0005006:7684 "))
    assert calls["count"] == 1


def test_another_parcel_is_counted_on_its_own(monkeypatch):
    """Кэш не имеет права отдать чужой ТЭП: это была бы не скорость, а ошибка."""
    calls: dict = {}
    _server_path(monkeypatch, calls)
    core.cadastral_tep_server(core.CadastralAnalysisRequest(
        cadastral_numbers="77:01:0005006:7684"))
    core.cadastral_tep_server(core.CadastralAnalysisRequest(
        cadastral_numbers="77:09:0004014:13"))
    assert calls["count"] == 2


def test_a_stale_entry_is_recounted(monkeypatch):
    """Ставки город индексирует поквартально — память не вечная."""
    calls: dict = {}
    _server_path(monkeypatch, calls)
    monkeypatch.setattr(core, "_GLAVAPU_TEP_CACHE_SECONDS", 0.05)
    request = core.CadastralAnalysisRequest(cadastral_numbers=", ".join(_NUMBERS))
    core.cadastral_tep_server(request)
    time.sleep(0.1)
    core.cadastral_tep_server(request)
    assert calls["count"] == 2


def test_the_cache_can_be_switched_off(monkeypatch):
    calls: dict = {}
    _server_path(monkeypatch, calls)
    monkeypatch.setattr(core, "_GLAVAPU_TEP_CACHE_SECONDS", 0.0)
    request = core.CadastralAnalysisRequest(cadastral_numbers=", ".join(_NUMBERS))
    core.cadastral_tep_server(request)
    core.cadastral_tep_server(request)
    assert calls["count"] == 2


def test_the_drift_check_does_not_hold_the_request(monkeypatch):
    """Сверка формул стоит целого серверного расчёта — она уходит в фон."""
    import inspect
    source = inspect.getsource(core.import_cadastral_tep)
    assert "_glavapu_drift_in_background" in source
    assert "drift = _glavapu_formula_drift(" not in source, \
        "синхронная сверка вернулась в горячий путь"


def test_the_drift_check_is_throttled(monkeypatch):
    """Дрейф методики — это про квартал, а не про каждый клик."""
    runs = {"count": 0}

    def fake_drift(rows, numbers):
        runs["count"] += 1
        return []

    monkeypatch.setattr(core, "_glavapu_formula_drift", fake_drift)
    core._GLAVAPU_FORMULA_DRIFT.update(checked_at=0.0, running=False)
    for _ in range(3):
        core._glavapu_drift_in_background([["4", "население", "чел.", "10"]], _NUMBERS)
        deadline = time.monotonic() + 30
        while core._GLAVAPU_FORMULA_DRIFT.get("running") and time.monotonic() < deadline:
            time.sleep(0.02)
    assert runs["count"] == 1, "сверка не имеет права идти на каждый расчёт"


def test_the_browser_stays_warm_by_default():
    """Пятнадцать минут простоя между двумя участками — обычное дело для бота,
    и каждый раз платился холодный старт Chromium."""
    assert core._GLAVAPU_HEADLESS_IDLE_SECONDS == 0, \
        "по умолчанию браузер обязан жить, пока живёт процесс"
    import inspect
    source = inspect.getsource(core._glavapu_browser_worker)
    assert "_GLAVAPU_HEADLESS_IDLE_SECONDS or None" in source, \
        "ноль обязан означать «не закрывать», а не «закрыть немедленно»"


def test_the_warm_up_opens_the_page_without_counting():
    """Прогрев греет страницу, но не считает ТЭП: считать нечего — кадастров
    ему не дают."""
    import inspect
    assert "_glavapu_warm_up" in inspect.getsource(core._start_glavapu_warm_up)
    source = inspect.getsource(core._glavapu_drive_page)
    assert "if not numbers:" in source and "прогрев" in source


def test_the_status_shows_whether_the_cache_works():
    from fastapi.testclient import TestClient
    status = TestClient(core.app).get("/telegram/status").json()["glavapu_headless"]
    assert "cache_hits" in status and "cache_size" in status


# --- запасной путь платил столько же, сколько штатный ------------------------

def test_the_formulas_do_not_ask_glavapu_twice(monkeypatch):
    """Страница спрашивает территорию перед расчётом и держит её в руках, а
    формулы шли за ней второй раз за тот же клик. Расчёт формул стоит 0,05 с —
    всё остальное время в этом пути было сетью."""
    asked = {"count": 0}

    def counted(request):
        asked["count"] += 1
        return {"territory": {"area_ha": 0.651}, "recognized": _NUMBERS,
                "coefficients": {"rent": 0.1281, "base_cost_zh_high": 229036.29},
                "warnings": []}

    monkeypatch.setattr(core, "analyze_cadastral_territory", counted)
    monkeypatch.setattr(core, "_GLAVAPU_HEADLESS_ENABLED", False)
    core.cadastral_tep_server(core.CadastralAnalysisRequest(
        cadastral_numbers=", ".join(_NUMBERS),
        cadastral_analysis={"recognized": _NUMBERS,
                            "territory": {"area_ha": 0.651},
                            "coefficients": {"rent": 0.1281,
                                             "base_cost_zh_high": 229036.29}}))
    assert asked["count"] == 0, "готовая территория обязана приниматься и формулами"


def test_the_formulas_are_remembered_too(monkeypatch):
    """Пока штатный калькулятор недоступен, повторный расчёт того же участка
    не должен снова ходить в сеть: помнится и запасной ответ."""
    runs = {"count": 0}
    original = core.vri_tep_quick

    def counted(region, query, **kwargs):
        runs["count"] += 1
        return original(region, query, **kwargs)

    monkeypatch.setattr(core, "analyze_cadastral_territory", lambda request: {
        "territory": {"area_ha": 0.651}, "recognized": _NUMBERS,
        "coefficients": {"rent": 0.1281, "base_cost_zh_high": 229036.29},
        "warnings": []})
    monkeypatch.setattr(core, "vri_tep_quick", counted)
    monkeypatch.setattr(core, "_GLAVAPU_HEADLESS_ENABLED", False)
    request = core.CadastralAnalysisRequest(cadastral_numbers=", ".join(_NUMBERS))
    first = core.cadastral_tep_server(request)
    second = core.cadastral_tep_server(request)
    assert runs["count"] == 1
    assert second["normalized"] == first["normalized"]


def test_a_broken_analysis_does_not_break_the_fallback(monkeypatch):
    """Территорию взять не удалось — формулы спрашивают сами, а не падают:
    запасной путь обязан оставаться запасным."""
    def boom(request):
        raise TimeoutError("ГлавАПУ молчит")

    monkeypatch.setattr(core, "analyze_cadastral_territory", boom)
    monkeypatch.setattr(core, "_GLAVAPU_HEADLESS_ENABLED", False)
    monkeypatch.setattr(core, "vri_tep_quick",
                        lambda region, query, **kwargs: {"file": b"", "filename": "x.xlsx"})
    monkeypatch.setattr(core, "parse_glavapu_xlsx",
                        lambda data, filename: {"normalized": {}, "source": {}, "warnings": []})
    result = core.cadastral_tep_server(core.CadastralAnalysisRequest(
        cadastral_numbers=", ".join(_NUMBERS)))
    assert result["source"]["format"].startswith("Формулы")


def test_the_chain_is_timed_in_the_log():
    """«Очень долго» — это диагноз только тогда, когда в журнале видно, какое
    звено цепочки его берёт."""
    import inspect
    source = inspect.getsource(core.cadastral_tep_server)
    assert "ядро ответило за" in source
    assert "формулы за" in source
    assert "готов за" in source
    # В первой же строке видно, пришла ли территория и жив ли браузер.
    assert "analysis=%s headless=%s" in source


# --- почему считали формулами, видно без доступа к серверу -------------------

def test_the_fallback_explains_itself(monkeypatch):
    """«Прошло мгновенно, но формулами» — законный вопрос, и ответ на него не
    должен требовать ssh на ядро. Браузер живёт там, и с телефона его
    состояние иначе не увидеть."""
    monkeypatch.setattr(core, "_GLAVAPU_HEADLESS_ENABLED", False)
    monkeypatch.setattr(core, "analyze_cadastral_territory", lambda request: {
        "territory": {"area_ha": 0.651}, "recognized": _NUMBERS,
        "coefficients": {"rent": 0.1281, "base_cost_zh_high": 229036.29},
        "warnings": []})
    result = core.cadastral_tep_server(core.CadastralAnalysisRequest(
        cadastral_numbers=", ".join(_NUMBERS)))
    state = result["source"]["headless"]
    assert state["state"] == "выключен"
    assert state["where"] in ("ядро", "Render")
    assert "GLAVAPU_HEADLESS=1" in state["hint"] or "Render" in state["hint"]
    assert any("штатный калькулятор" in str(w).lower() for w in result["warnings"])


def test_the_fuse_names_itself_too(monkeypatch):
    """Взведённый предохранитель — отдельная причина: калькулятор есть, но
    сорвался, и следующая попытка будет через известное время."""
    monkeypatch.setattr(core, "_GLAVAPU_HEADLESS_ENABLED", True)
    core._GLAVAPU_HEADLESS_BLOCKED_UNTIL["at"] = time.monotonic() + 120
    try:
        state = core._glavapu_headless_state()
    finally:
        core._GLAVAPU_HEADLESS_BLOCKED_UNTIL["at"] = 0.0
    assert state["state"] == "предохранитель"
    assert state["blocked_for"] > 0
    assert "last_error" in state


def test_a_working_calculator_says_so(monkeypatch):
    calls: dict = {}
    _server_path(monkeypatch, calls)
    result = core.cadastral_tep_server(core.CadastralAnalysisRequest(
        cadastral_numbers=", ".join(_NUMBERS)))
    assert result["source"]["headless"]["state"] == "готов"


def test_the_page_prints_the_reason():
    """Строка статуса говорит, кто посчитал, и если формулы — почему."""
    page = core.PAGE
    assert "Штатный калькулятор недоступен" in page
    assert "byCalculator" in page
    assert "hl.hint" in page
