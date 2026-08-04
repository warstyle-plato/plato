"""ТЭП считает сам калькулятор ГлавАПУ, а наши формулы — фолбэк.

Копировать методику оказалось тупиком: плата за ВРИ разошлась со штатным
калькулятором на 1,75%, компенсация за соцобъекты — на 19%, и оба раза
расхождение находил человек на скриншотах. Ставки индексируются поквартально,
коэффициенты меняются, и пересказ отстаёт на неизвестный срок, продолжая
выглядеть достоверно.

Теперь сервер запускает настоящий калькулятор браузером без экрана — той же
последовательностью, что отрабатывает скрытый iframe на сайте. Формулы
остаются запасным путём: при недоступности ГлавАПУ или сломанной автоматизации
отчёт честно говорит, что расчёт запасной, вместо тихой выдачи устаревшего.

Запуск: python3 -m pytest tests -q
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import main as wrapper  # noqa: E402

core = wrapper.core

_NUMBERS = ["77:01:0005006:7684"]


def test_the_headless_run_is_off_until_switched_on():
    """По умолчанию выключено: Chromium есть не на каждой машине, и выкатка
    не должна ронять расчёт там, где его нет."""
    assert core._GLAVAPU_HEADLESS_ENABLED is False


def test_the_server_path_prefers_the_real_calculator(monkeypatch):
    """Включённый флаг ведёт расчёт в настоящий калькулятор, а не в формулы."""
    seen = {}

    def fake_rows(numbers, area_ha):
        seen["numbers"] = list(numbers)
        seen["area"] = area_ha
        return [{"code": "60", "name": "Озеленение", "unit": "га", "value": "1"}]

    def fake_analysis(request):
        return {"territory": {"area_ha": 0.1963}, "recognized": _NUMBERS,
                "coefficients": {}, "warnings": []}

    def fake_import(request):
        seen["imported"] = True
        return {"normalized": {"spp_total_sqm": 6870}, "source": {}, "warnings": []}

    monkeypatch.setattr(core, "_GLAVAPU_HEADLESS_ENABLED", True)
    monkeypatch.setattr(core, "_glavapu_headless_rows", fake_rows)
    monkeypatch.setattr(core, "analyze_cadastral_territory", fake_analysis)
    monkeypatch.setattr(core, "import_cadastral_tep", fake_import)

    result = core.cadastral_tep_server(
        core.CadastralAnalysisRequest(cadastral_numbers=", ".join(_NUMBERS)))
    assert seen["numbers"] == _NUMBERS
    assert seen["imported"] is True
    assert "Штатный калькулятор" in result["source"]["format"]


def test_a_broken_automation_falls_back_to_the_formulas(monkeypatch):
    """Худший исход нового пути — сегодняшнее поведение, а не сломанный бот:
    упавший калькулятор уводит расчёт в формулы, а не в ошибку."""
    def boom(numbers, area_ha):
        raise TimeoutError("калькулятор не отдал таблицу")

    def fake_analysis(request):
        return {"territory": {"area_ha": 0.1963}, "recognized": _NUMBERS,
                "coefficients": {}, "warnings": []}

    calls = {}

    def fake_quick(region, query, **kwargs):
        calls["fallback"] = True
        return {"file": b"", "filename": "x.xlsx"}

    def fake_parse(data, filename):
        return {"normalized": {}, "source": {}, "warnings": []}

    monkeypatch.setattr(core, "_GLAVAPU_HEADLESS_ENABLED", True)
    monkeypatch.setattr(core, "_glavapu_headless_rows", boom)
    monkeypatch.setattr(core, "analyze_cadastral_territory", fake_analysis)
    monkeypatch.setattr(core, "vri_tep_quick", fake_quick)
    monkeypatch.setattr(core, "parse_glavapu_xlsx", fake_parse)

    result = core.cadastral_tep_server(
        core.CadastralAnalysisRequest(cadastral_numbers=", ".join(_NUMBERS)))
    assert calls.get("fallback") is True, "формулы обязаны подхватить"
    assert any("запасной" in str(w) or "формулами" in str(w)
               for w in result["warnings"]), "человек должен знать, что расчёт запасной"
    assert core._GLAVAPU_HEADLESS["last_error"], "сбой обязан оставлять след"


def test_the_status_tells_who_counted():
    """«Бот опять посчитал не то» проверяется статусом, а не скриншотами."""
    from fastapi.testclient import TestClient
    status = TestClient(core.app).get("/telegram/status").json()["glavapu_headless"]
    assert {"enabled", "runs", "fallbacks", "last_ok", "last_error"} <= set(status)


def test_the_automation_repeats_the_page_steps():
    """Серверные шаги — те же, что у скрытого iframe: другая последовательность
    молча дала бы другой расчёт."""
    import inspect
    source = inspect.getsource(core._glavapu_headless_rows)
    for step in ("Участок", "id-cad-numbers-text-field", "Отправить",
                 "Перейти к расчётам"):
        assert step in source, step
    # Готовность таблицы определяется как на странице: коды 60 и 54, ≥60 строк.
    assert '"60" in codes' in source and '"54" in codes' in source
    assert "len(rows) >= 60" in source


def test_only_one_browser_runs_at_a_time():
    """Ядро — 2 vCPU и 4 ГБ, воркеров два, Chromium берёт 300–400 МБ:
    два одновременных запуска клали бы не расчёт, а весь контейнер."""
    assert core._GLAVAPU_HEADLESS_SLOTS == 1
    import inspect
    source = inspect.getsource(core._glavapu_headless_rows)
    assert "_GLAVAPU_HEADLESS_LOCK.acquire" in source
    assert "_GLAVAPU_HEADLESS_LOCK.release" in source
    # Ожидание в очереди конечно: не дождался — уходим на формулы, а не висим.
    assert "_GLAVAPU_HEADLESS_QUEUE_SECONDS" in source


def test_the_container_flags_are_set_for_a_small_machine():
    """В контейнере /dev/shm мал, и без флага Chromium падает молча."""
    import inspect
    source = inspect.getsource(core._glavapu_headless_rows)
    assert "--disable-dev-shm-usage" in source
    assert "--no-sandbox" in source


def test_the_status_counts_queue_timeouts():
    from fastapi.testclient import TestClient
    status = TestClient(core.app).get("/telegram/status").json()["glavapu_headless"]
    assert "queue_timeouts" in status and "parallel_slots" in status
