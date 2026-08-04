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
