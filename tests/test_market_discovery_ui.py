from __future__ import annotations

from market_search.ui import install


class FakeCore:
    PAGE = """
    <html><head></head><body>
      <button class="tab" data-tab="report" onclick="openTab('report',this)">Отчёт</button>
      <div id="report" class="panel"></div>
    </body></html>
    """


def test_market_discovery_tab_is_installed() -> None:
    core = FakeCore()
    install(core)
    assert 'data-tab="marketDiscovery"' in core.PAGE
    assert "Yandex Search API" in core.PAGE
    assert "Наш.Дом.РФ" in core.PAGE
    assert "/market/discovery" in core.PAGE


def test_market_discovery_install_is_idempotent() -> None:
    core = FakeCore()
    install(core)
    once = core.PAGE
    install(core)
    assert core.PAGE == once
