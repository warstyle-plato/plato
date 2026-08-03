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
    assert "await obtainServerTep(cadastralAnalysis,status)" in body, \
        "падение автоматизации должно докатываться серверными формулами"
    assert "function obtainServerTep" in core.PAGE
    assert "/cadastral/tep-server" in core.PAGE
