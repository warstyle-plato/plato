"""Модуль рынка доезжает до всех трёх поверхностей собранного приложения.

Проверяется не сам расчёт — его проверяет `test_market_agent_surfaces`, — а
сборка: порядок установки. Слой перестройки снимает копию `core.PAGE` при
установке, и вкладка, добавленная после него, на основном интерфейсе просто
не появляется. Снаружи это неотличимо от «модуль не выкачен»: страница
открывается, версия та же, вкладки нет.
"""

from __future__ import annotations

import importlib

import pytest
from fastapi.testclient import TestClient


@pytest.fixture(scope="module")
def registry():
    return importlib.import_module("main_registry")


@pytest.mark.parametrize("path", ["/", "/classic"])
def test_market_panel_is_on_the_page_that_people_open(registry, path: str) -> None:
    client = TestClient(registry.app)
    page = client.get(path).text
    assert 'data-tab="marketDiscovery"' in page, f"нет вкладки «Рынок» на {path}"
    # Панель приведена к контракту v6: карантин и адрес проекта видны, а не
    # только то, что дошло до конца.
    assert "mdQuarantine" in page
    assert "Адрес проекта" in page


def test_discovery_endpoint_is_served(registry) -> None:
    paths = {route.path for route in registry.app.router.routes}
    assert "/market/discovery" in paths


def test_platon_can_ask_about_competitors(registry) -> None:
    from market_search.plato_tool import TOOL_NAME

    names = [tool["name"] for tool in registry.core._AGENT_TOOLS]
    assert TOOL_NAME in names
    assert names.count(TOOL_NAME) == 1


def test_the_commercial_question_has_a_button_in_the_agent(registry) -> None:
    """Инструмент без входа со стороны человека — это инструмент, которого нет.

    Кнопка ставится вместе с инструментом и падает, если разметка ящика
    Платона изменилась: молча не встать она не может.
    """
    client = TestClient(registry.app)
    page = client.get("/").text
    assert "Рынок конкурентов</button>" in page
    assert "'market_analogues')" in page
    assert page.count("Рынок конкурентов</button>") == 1


def test_the_agent_is_told_when_to_use_it(registry) -> None:
    """Инструмент, не названный в правилах выбора, вызывается через раз."""
    from market_search.plato_tool import TOOL_NAME

    rules = registry.core._AGENT_INSTRUCTIONS
    assert rules.count(TOOL_NAME) == 1
    assert "Цену предложения и официальную среднюю ЕИСЖС не смешивай" in rules


def test_bot_menu_names_the_market(registry) -> None:
    commands = [item["command"] for item in registry.core.TELEGRAM_BOT_COMMANDS]
    assert "market" in commands
    # Расчёт встаёт среди расчётов, а не ниже помощи.
    assert commands.index("market") < commands.index("help")


def test_help_does_not_promise_a_number_of_menu_entries(registry) -> None:
    """Расширения дописывают команды, а написанное словом число устаревает молча."""
    import main

    block = main._commands_block()
    assert "В меню — пять" not in block
    assert "/market" in block or "market" in block
