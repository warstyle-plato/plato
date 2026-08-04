"""Серверный ТЭП по формулам ГлавАПУ — когда браузерная автоматизация недоступна.

Сайт собирал ТЭП, гоняя настоящий калькулятор в скрытом iframe, а Telegram
WebView этого не тянет: мини-приложение падало по таймауту «Калькулятор
ГлавАПУ не ответил вовремя». Формулы калькулятора сняты с его кода и сходятся
с контрольными выгрузками до единицы, поэтому сервер считает их сам:
в Telegram — сразу, на сайте — фолбэком после падения автоматизации.

Запуск: python3 -m pytest tests -q
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import main as wrapper  # noqa: E402

core = wrapper.core


def test_the_server_endpoint_returns_a_full_glavapu_import(monkeypatch):
    monkeypatch.setattr(core, "analyze_cadastral_territory", lambda req: {
        "territory": {"area_ha": 0.651, "district": "Савеловский",
                      "cadastral_quarter": "77:09:0004014"},
        "coefficients": {"rail": 0.75, "business_outside_ttc": 0.5,
                         "rent": 0.1281, "base_cost_zh_high": 229036.29},
    })
    result = core.cadastral_tep_server(core.CadastralAnalysisRequest(
        cadastral_numbers="77:09:0004014:13"))

    assert "серверными формулами" in result["warnings"][0]
    assert "серверный расчёт" in result["source"]["format"]
    normalized = result["normalized"]
    assert normalized["site_area_ha"] == pytest.approx(0.651)
    assert normalized["apartment_area_sqm"] == pytest.approx(13921.6, rel=0.001)
    mapped = result["mappings"]["inputs"]
    assert mapped["land_rights_cost_mln"] == pytest.approx(1267.734, abs=0.001)
    assert mapped["social_compensation_mln"] == pytest.approx(580.668, abs=0.01)
    assert result["mappings"]["tep"]["apartments"]["saleable"] == \
        pytest.approx(13921.6, rel=0.001)
    assert normalized["parking_permanent"] == pytest.approx(82)


def test_the_page_goes_server_side_in_telegram_and_on_failure():
    """Мини-приложение идёт серверным путём сразу, сайт — после падения
    автоматизации; голая ошибка показывается только когда нет и территории."""
    flow = re.search(r"async function obtainCadastralTep\(.*?\n\}", core.PAGE, re.S)
    assert flow, "obtainCadastralTep не найдена на странице"
    body = flow.group(0)
    telegram_branch = body.find("window.Telegram&&window.Telegram.WebApp")
    automation = body.find("Открываю штатный расчёт ГлавАПУ")
    assert 0 < telegram_branch < automation, \
        "Telegram обязан уходить в серверный расчёт до запуска iframe"
    assert "await obtainServerTep(cadastralAnalysis,status,runId)" in body, \
        "падение автоматизации должно докатываться серверными формулами"
    assert "function obtainServerTep" in core.PAGE
    assert "/cadastral/tep-server" in core.PAGE


# --- дрейф-контроль ----------------------------------------------------------
# «Если расчёты ГлавАПУ поменяются, бот будет давать заведомо ложную
# информацию, а сайт верную?» — нет: каждый успешный сбор штатного
# калькулятора на сайте сверяется с серверными формулами, и расхождение
# кричит в предупреждениях импорта, в /status и в ответах серверного пути.

def _mock_analysis(monkeypatch):
    monkeypatch.setattr(core, "analyze_cadastral_territory", lambda req: {
        "territory": {"area_ha": 0.651, "district": "Савеловский",
                      "cadastral_quarter": "77:09:0004014"},
        "coefficients": {"rail": 0.75, "business_outside_ttc": 0.5,
                         "rent": 0.1281, "base_cost_zh_high": 229036.29},
    })


def _calculator_rows(monkeypatch) -> list[dict]:
    """Таблица «штатного калькулятора» — из собственного серверного файла:
    идеальный случай без дрейфа."""
    _mock_analysis(monkeypatch)
    quick = core.vri_tep_quick("msk", "77:09:0004014:13")
    rows = [list(r) + [""] * (4 - len(r)) for r in
            core._xlsx_read_tables(quick["file"])["ТЭП"]]
    return [{"code": str(r[0] or ""), "name": str(r[1] or ""),
             "unit": str(r[2] or ""), "value": str(r[3] or "")}
            for r in rows[1:] if str(r[1] or "").strip()]


def test_a_matching_calculator_clears_the_drift_flag(monkeypatch):
    _mock_analysis(monkeypatch)
    core._GLAVAPU_FORMULA_DRIFT.update(items=["старый дрейф"], found_at="x")
    result = core.import_cadastral_tep(core.CadastralTepRequest(
        rows=_calculator_rows(monkeypatch),
        cadastral_analysis={"recognized": ["77:09:0004014:13"]}))
    assert core._GLAVAPU_FORMULA_DRIFT["items"] == [], \
        "совпавший сбор обязан снимать флаг дрейфа"
    assert not any("разошлись" in w for w in result["warnings"])


def test_a_changed_methodology_screams_everywhere(monkeypatch):
    _mock_analysis(monkeypatch)
    rows = _calculator_rows(monkeypatch)
    for row in rows:
        if row["code"] == "44":
            row["value"] = "2 000,000"  # ГлавАПУ «поменял» методику платы
    result = core.import_cadastral_tep(core.CadastralTepRequest(
        rows=rows, cadastral_analysis={"recognized": ["77:09:0004014:13"]}))

    assert any("разошлись" in w for w in result["warnings"]), \
        "расхождение обязано попасть в предупреждения импорта"
    assert core._GLAVAPU_FORMULA_DRIFT["items"], "флаг дрейфа не взведён"
    assert "Дрейф формул ГлавАПУ" in core._TELEGRAM_RUNTIME.get("last_error", "")

    # Серверный путь и карточка бота предупреждают, пока дрейф не снят.
    server = core.cadastral_tep_server(core.CadastralAnalysisRequest(
        cadastral_numbers="77:09:0004014:13"))
    assert "разошлись" in server["warnings"][0]
    card = core.vri_tep_quick("msk", "77:09:0004014:13")["card"]
    assert "разошлись со штатным калькулятором" in card

    core._GLAVAPU_FORMULA_DRIFT.update(items=[], found_at="", numbers=[])


# --- гонка телеграм-потока ---------------------------------------------------
# Mini App показывал «Калькулятор ГлавАПУ не ответил вовремя», а затем всё
# равно «Готов. Отправляю в чат…»: телеграм-ветка проверяла глобальный
# glavapuImport, который renderStoredGlavapu поднимал из сохранённого проекта,
# и слала старый ТЭП как свежий.

def test_the_telegram_flow_only_uses_this_runs_result():
    launch = re.search(r"if\(telegramCad\)\{.*?\n \}", core.PAGE, re.S)
    assert launch, "телеграм-ветка запуска не найдена"
    body = launch.group(0)
    assert "const payload=await obtainCadastralTep()" in body, \
        "в чат обязан уходить результат именно этого запуска, не глобальное состояние"
    assert "site_area_ha" in body, "перед отправкой проверяются обязательные поля"
    assert "finishTelegramSession('ТЭП не получен" in body, \
        "после ошибки сценарий обязан остановиться с честным сообщением"


def test_every_run_is_tokenized_and_double_clicks_are_ignored():
    assert "let tepRunSequence=0" in core.PAGE
    assert "const runId=++tepRunSequence" in core.PAGE
    flow = re.search(r"async function obtainCadastralTep\(.*?\n\}", core.PAGE, re.S).group(0)
    assert "if(button.disabled)return null" in flow, "повторный клик не должен запускать второй запрос"
    assert flow.count("runId!==tepRunSequence") >= 2, \
        "ответы устаревших запусков обязаны отбрасываться"
    assert "finally" in flow


def test_the_mini_app_url_busts_the_webview_cache(monkeypatch):
    monkeypatch.setattr(core, "_telegram_session", lambda *a, **kw: "sess")
    url = core._telegram_web_app_url(42, [])
    assert f"v={core.VERSION}" in url, \
        "URL мини-приложения обязан включать версию для сброса кэша WebView"


def test_the_two_tep_sources_are_labelled_apart():
    """Штатный калькулятор и серверные формулы помечались одинаково —
    «ГлавАПУ», — и два отчёта с разными числами выглядели одинаково
    достоверно: отличить их можно было только по имени файла выгрузки.
    На двух компьютерах это дало соцплатёж 185,1 и 220,3 млн ₽ без
    единого признака, какой расчёт откуда."""
    page = core.PAGE
    assert "function tepSourceLabel(" in page
    assert "ГлавАПУ · серверный расчёт DevelopAid" in page
    assert "ГлавАПУ · штатный калькулятор" in page
    # Старая безусловная метка не должна вернуться ни в одну из точек сборки.
    assert "source_label:manual?'Ручной шаблон DevelopAid':'ГлавАПУ'" not in page


def test_the_server_answer_dates_its_compensation_rates():
    """Ставки компенсации зашиты на дату и отстают от города: серверный
    ответ обязан называть эту дату, иначе отставание всплывает только при
    сравнении расчётов с разных машин."""
    import inspect
    source = inspect.getsource(core.cadastral_tep_server)
    assert "_GLAVAPU_COMPENSATION_RATES_DATE" in source
    assert "индексирует их" in source
    assert core._GLAVAPU_COMPENSATION_RATES_DATE
