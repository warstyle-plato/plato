"""Очередь платит проектирование, подготовку и сети по своему объёму.

«То есть не будет так, что проектирование и прочие расходы будут браться своей
ценой? А если ставить 42, то и удельные вводные меняться должны» (владелец,
04.09.2026). Общепроектные статьи считаются один раз на проект и делились
кассовыми долями, к объёму очереди не привязанными: на Нагатине при 42% первая
очередь платила 25,9 тыс ₽/м² проектирования при вводной 14,5, третья — 6,3, и
вводная на экране не менялась.

Закреплено:
- статья «по объёму» (`shared_cash[key] == "volume"`) даёт каждой очереди цену
  метра, равную вводной с поправкой на инфляцию очереди; доля берётся от той
  же базы, что у движка, — ГНС МКД, а не весь объём с офисами;
- заданная руками доля остаётся, и фактическая цена метра очереди доезжает в
  сравнение (`shared_rates_th`) рядом с вводной (`shared_rate_inputs_th`);
- применённые доли движок отдаёт (`shared_cash_applied`), и книга берёт их
  оттуда — слово «volume» в phasing книга числом не заменяет сама;
- скрининг КРТ ставит тот же порядок.

Запуск: python3 -m pytest tests/test_a_queue_pays_shared_articles_at_its_own_price.py -q
"""

from __future__ import annotations

import copy
import io
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

import main_legacy as core  # noqa: E402


def _phasing(shared: dict) -> dict:
    return {
        "enabled": True, "phase_count": 2, "phase_gap_months": 12, "cost_inflation_pct": 8,
        "phases": [
            {"name": "О1", "start_offset_months": 0, "construction_months": 24},
            {"name": "О2", "start_offset_months": 12, "construction_months": 24},
        ],
        # Очереди разного размера и офисы во второй: доля по объёму и доля по
        # продукту здесь расходятся, иначе проверять было бы нечего.
        "products": {key: [30, 70] for key in ("apartments", "ground_commercial", "underground_parking", "storage")},
        "shared_cash": shared,
        "social_objects": [],
        "discrete": {"offices": 2, "standalone_retail": 2, "above_parking": 2},
    }


def _inputs() -> dict:
    inputs = copy.deepcopy(core.DEFAULT_INPUTS)
    inputs.update(apartment_price_th=650, commercial_price_th=650, parking_price_th=5000,
                  offices_enabled=True, offices_gba_sqm=40000, offices_saleable_sqm=30000)
    return inputs


@pytest.fixture(scope="module")
def by_volume() -> dict:
    return core._run_authoritative_model(
        _inputs(), copy.deepcopy(core.TEP_DEFAULT), [],
        _phasing({"design": "volume", "preparation": "volume", "utilities": "volume"}))


@pytest.fixture(scope="module")
def by_hand() -> dict:
    return core._run_authoritative_model(
        _inputs(), copy.deepcopy(core.TEP_DEFAULT), [],
        _phasing({"design": [70, 30], "preparation": [70, 30], "utilities": [70, 30]}))


def test_each_queue_pays_the_input_rate_by_volume(by_volume: dict) -> None:
    # Допуск 0,1%: сумма строк продуктов очередей отличается от базы проекта на
    # сотую долю процента (паркинг очереди считается от своих мест), и ровно на
    # неё цена метра отходит от вводной.
    for row, item in zip(by_volume["comparison"], by_volume["phases"]):
        inflation = float(item.get("cost_inflation_factor") or 1.0)
        for key in ("design", "preparation", "utilities"):
            assert row["shared_rates_th"][key] == pytest.approx(
                row["shared_rate_inputs_th"][key] * inflation, rel=1e-3), (row["name"], key)


def test_the_volume_share_follows_the_mkd_base_not_the_offices(by_volume: dict) -> None:
    """Офисы во второй очереди её долю проектирования не поднимают: у объекта своя цена."""
    applied = by_volume["shared_cash_applied"]["design"]
    assert sum(applied) == pytest.approx(100.0, abs=1e-6)
    bases = [row["shared_rate_base_sqm"] for row in by_volume["comparison"]]
    assert applied[0] == pytest.approx(bases[0] / sum(bases) * 100, rel=1e-6)
    # Предохранитель: у второй очереди действительно есть метры сверх базы МКД,
    # иначе проверка пустая. Сравнивается строительный объём, а не ГНС: с
    # 04.09.2026 ГНС — наземная площадь, и подземный паркинг, входящий в базу
    # МКД, из неё вычтен — «наземная против базы МКД» сравнивало бы разное.
    volume = [row["construction_volume_sqm"] for row in by_volume["comparison"]]
    assert volume[1] > bases[1], "у второй очереди офисы сверх базы МКД — иначе проверка пустая"


def test_a_hand_set_share_shows_its_real_rate(by_hand: dict) -> None:
    first, second = by_hand["comparison"]
    assert by_hand["shared_cash_applied"]["design"] == pytest.approx([70.0, 30.0])
    assert first["shared_rates_th"]["design"] > first["shared_rate_inputs_th"]["design"] * 1.5
    assert second["shared_rates_th"]["design"] < second["shared_rate_inputs_th"]["design"]


def test_the_word_volume_is_not_a_list_of_weights_for_the_book() -> None:
    weights = core._v4_shared_weights({"shared_cash": {"design": "volume"}}, "design", 2)
    assert len(weights) == 2 and sum(weights) == pytest.approx(1.0)


def test_the_workbook_takes_the_applied_shares_from_the_engine() -> None:
    openpyxl = pytest.importorskip("openpyxl")
    from xlsx_eval import Evaluator

    content, _, missing = core.build_project_workbook(
        _inputs(), copy.deepcopy(core.TEP_DEFAULT), [],
        _phasing({"design": "volume", "preparation": "volume", "utilities": "volume"}),
        project_name="П")
    assert not [m for m in missing if "по объёму" in m], missing
    sys.setrecursionlimit(400000)
    evaluator = Evaluator(openpyxl.load_workbook(io.BytesIO(content), data_only=False))
    checks = evaluator.workbook["ПРОВЕРКИ"]
    for row in range(76, 85):
        if checks[f"A{row}"].value is None:
            continue
        assert evaluator.cell("ПРОВЕРКИ", f"F{row}") == "OK", (
            str(checks[f"A{row}"].value), evaluator.cell("ПРОВЕРКИ", f"B{row}"), evaluator.cell("ПРОВЕРКИ", f"C{row}"))


def test_the_screening_uses_the_same_rule() -> None:
    from auction_search.krt_screening import _phase_configuration
    cfg = _phase_configuration(150_000, 24)
    assert cfg["shared_cash"] == {"design": "volume", "preparation": "volume", "utilities": "volume"}


def test_the_page_preset_and_editor_know_the_word() -> None:
    page = core.PAGE
    assert "return 'volume'" in page
    assert "по объёму очереди" in page and "setSharedManual" in page and "setSharedVolume" in page
    assert "shared_rates_th" in page
