"""Потолок цены входа «0 млн ₽» при LLCR 1,06 — ошибка подбора, а не ответ.

Владелец (прод 0.27.7, 22.10.2026): цена 4 550 млн, LLCR 1,06, а «Максимум
цены входа — 0 млн ₽, запас −4 550». Порог при нулевой цене выполнялся, и
потолок нулём быть не мог.

Корень — график покупки суммами («2000@0; 2550@12»). Суммы графика платятся
как есть, разница с ценой ложится на дату сделки. Подбор менял одну цену: при
любой цене выше нуля проект платил те же 4 550 млн по графику плюс «возврат»
в дату сделки, при нулевой — ничего. LLCR прыгал у нуля с 1,21 на 1,17, и
решатель честно находил «0». Теперь подбор держит профиль оплаты: доли
платежей — от текущей сделки (`_purchase_schedule_as_shares`).

Здесь закреплено:

- график суммами и тот же график долями дают один потолок, и он не ноль;
- найденный потолок держит порог при проверочном пересчёте с тем же
  профилем, а на 1 % дороже — уже нет;
- нулевая цена, при которой порог не выполнен, потолком не выдаётся;
- Платон в чате называет то же число, что карточка решения.

Запуск: python3 -m pytest tests/test_a_scheduled_purchase_does_not_cap_the_entry_price_at_zero.py -q
"""

from __future__ import annotations

import copy
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import main as wrapper  # noqa: E402

core = wrapper.core
PRICE = 4550.0
TARGET = 1.20


def _case(schedule: str, apartment: float = 460.0) -> tuple[dict, dict, list, dict]:
    inputs = copy.deepcopy(core.DEFAULT_INPUTS)
    # Вводные, на которых LLCR при цене 4 550 около 1,06, как у владельца.
    inputs.update(apartment_price_th=apartment, commercial_price_th=apartment,
                  parking_price_th=5000, purchase_price_mln=PRICE, purchase_schedule=schedule)
    return inputs, copy.deepcopy(core.TEP_DEFAULT), copy.deepcopy(core.RATE_CURVE), {}


def _llcr(inputs: dict, tep: dict, rates: list, phasing: dict) -> float:
    bundle = core._run_authoritative_model(inputs, tep, rates, phasing)
    return float(bundle["consolidated"]["summary"]["llcr"])


def _ceiling(schedule: str, apartment: float = 460.0) -> dict:
    x, t, r, ph = _case(schedule, apartment)
    bundle = core._run_authoritative_model(x, t, r, ph)
    return core.entry_price_ceiling(bundle, x, t, r, ph)


@pytest.fixture(scope="module")
def by_sums() -> dict:
    return _ceiling("2000@0; 2550@12")


def test_the_owner_case_is_reproduced(by_sums) -> None:
    assert by_sums["current"]["metric"] == pytest.approx(1.07, abs=0.02)


def test_sums_and_shares_give_one_ceiling_and_it_is_not_zero(by_sums) -> None:
    shares = _ceiling(f"{2000 / PRICE * 100:.10g}%@0; {2550 / PRICE * 100:.10g}%@12")
    assert by_sums["available"] is True and shares["available"] is True
    assert by_sums["solution"]["variable"] > 100.0
    assert by_sums["solution"]["variable"] == pytest.approx(shares["solution"]["variable"], rel=0.01)


def test_the_ceiling_holds_on_a_check_recount(by_sums) -> None:
    ceiling = by_sums["solution"]["variable"]
    x, t, r, ph = _case("2000@0; 2550@12")
    core._apply_variable(x, "purchase_price_mln", ceiling)
    assert _llcr(x, t, r, ph) >= TARGET - 1e-4
    core._apply_variable(x, "purchase_price_mln", ceiling * 1.01)
    assert _llcr(x, t, r, ph) < TARGET


def test_the_schedule_profile_is_kept_at_the_current_price() -> None:
    x, t, r, ph = _case("2000@0; 2550@12")
    before = _llcr(x, t, r, ph)
    core._apply_variable(x, "purchase_price_mln", PRICE)
    assert "%" in x["purchase_schedule"]
    assert _llcr(x, t, r, ph) == pytest.approx(before, abs=1e-6)


def test_zero_is_not_a_found_ceiling_when_zero_fails() -> None:
    data = _ceiling("2000@0; 2550@12", apartment=440.0)
    assert data["available"] is False
    assert "solution" not in data
    assert data["closest_tested"]["variable"] == 0.0
    tiles = core.entry_price_tiles(*_bundle_inputs("2000@0; 2550@12", 440.0), data)
    assert tiles[2]["value"] == "не достигается"
    assert tiles[3]["value"] == "—"


def _bundle_inputs(schedule: str, apartment: float) -> tuple[dict, dict]:
    x, t, r, ph = _case(schedule, apartment)
    return core._run_authoritative_model(x, t, r, ph), x


def test_plato_names_the_same_ceiling(by_sums) -> None:
    x, t, r, ph = _case("2000@0; 2550@12")
    req = core.AgentChatRequest(message="", inputs=x, tep=t, rates=r, phasing=ph)
    bundle = core._run_authoritative_model(x, t, r, ph)
    text = core._local_max_purchase_price(req, bundle)
    assert core._agent_num(by_sums["solution"]["variable"], 1) in text


def test_an_uneven_metric_is_said_not_hidden(by_sums) -> None:
    sampled = [(0.0, 1.25, True), (100.0, 1.19, False), (200.0, 1.21, True),
               (300.0, 1.22, True), (400.0, 1.1, False)]
    assert core._goal_feasible_ranges(sampled) == [[0.0, 0.0], [200.0, 300.0]]
    goal = {**by_sums, "non_monotonic": True, "feasible_ranges": [[0.0, 0.0], [200.0, 300.0]]}
    tiles = core.entry_price_tiles(*_bundle_inputs("2000@0; 2550@12", 460.0), goal)
    assert "меняется с ценой неровно" in tiles[2]["note"]
    assert "от 200 млн ₽ до 300 млн ₽" in tiles[2]["note"].replace(" ", " ")
