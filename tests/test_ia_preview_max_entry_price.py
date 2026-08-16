"""Максимальная цена входа перестала быть доступной только из чата.

Число, ради которого модель и открывают — «за сколько максимум можно купить,
чтобы LLCR держался на банковском пороге», — движок считал давно, но
единственной дверью к нему был чип в переписке с Платоном Сергеевичем. Отчёт
показывал что угодно, кроме ответа на вопрос сделки.

`/ia/goal-seek` эту дверь открывает и ничего к ней не добавляет: подбор ведёт
`_tool_goal_seek` движка — тот же, что зовёт агент. Здесь закреплено, что
маршрут остаётся дверью, а не второй реализацией:

- подбор действительно ведёт движок, и модель вызывающего не меняется;
- ответ несёт своё происхождение: версию движка и время расчёта;
- недостижимый порог возвращается отказом с причиной, а не числом.

Вводные подобраны так, чтобы порог был достижим. На умолчаниях проект
глубоко убыточен (LLCR 0,90 при нулевой цене покупки), и тест, написанный на
них, зелёным проходил бы мимо всей ветки подбора — как уже было со ставкой ПФ,
пережившей 581 тест.

Запуск: python3 -m pytest tests/test_ia_preview_max_entry_price.py -q
"""

from __future__ import annotations

import copy
import sys
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import main as wrapper  # noqa: E402
from ia_preview import install  # noqa: E402

core = wrapper.core
TARGET = 1.20


@pytest.fixture(scope="module")
def client() -> TestClient:
    app = FastAPI()
    install(app, core)
    return TestClient(app)


def payload(**overrides) -> dict:
    inputs = copy.deepcopy(core.DEFAULT_INPUTS)
    inputs.update(overrides)
    return {
        "inputs": inputs,
        "tep": copy.deepcopy(core.TEP_DEFAULT),
        "rates": copy.deepcopy(core.RATE_CURVE),
        "phasing": {},
    }


def viable() -> dict:
    """Проект, который порог проходит: иначе ветка подбора недостижима."""
    return payload(apartment_price_th=650, commercial_price_th=650, parking_price_th=5000)


def test_the_ceiling_holds_the_target_llcr(client: TestClient):
    """Найденная цена — та, при которой LLCR ровно на пороге."""
    data = client.post("/ia/goal-seek", json=viable()).json()
    assert data["available"], data.get("reason")
    assert data["solution"]["variable"] > 0
    assert data["solution"]["metric"] == pytest.approx(TARGET, abs=1e-3)
    assert data["current"]["metric"] > TARGET, "порог должен быть достижим на этих вводных"


def test_the_answer_carries_where_it_came_from(client: TestClient):
    """Карточка решения переживает свои вводные — значит, несёт штамп."""
    data = client.post("/ia/goal-seek", json=viable()).json()
    assert data["engine_version"] == core.VERSION
    assert data["computed_at"].startswith("20")


def test_the_engine_does_the_search(client: TestClient, monkeypatch):
    """Подбор ведёт движок: второй реализации у него нет."""
    calls: list[str] = []
    original = core._tool_goal_seek

    def counted(*args, **kwargs):
        calls.append(args[2])
        return original(*args, **kwargs)

    monkeypatch.setattr(core, "_tool_goal_seek", counted)
    client.post("/ia/goal-seek", json=viable())
    assert calls == ["purchase_price_mln"]


def test_the_callers_model_is_not_touched(client: TestClient):
    """Подбор гоняет копию: текущая модель после него та же."""
    body = viable()
    before = copy.deepcopy(body)
    client.post("/ia/goal-seek", json=body)
    assert body == before


def test_an_unreachable_target_is_refused_not_invented(client: TestClient):
    """Умолчания порог не проходят даже при нулевой цене покупки.

    Отказ с причиной честнее числа: цена, «допустимая» у заведомо убыточного
    проекта, выглядит на экране ровно так же, как посчитанная.
    """
    data = client.post("/ia/goal-seek", json=payload()).json()
    assert data["available"] is False
    assert data["reason"]
    assert data.get("solution") is None
