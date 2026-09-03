"""Отказ подбора называет, чьё число не дотянуло, — иначе он спорит со сводом.

На отчёте по четырём очередям стояло: LLCR 1,23x — и тут же «Максимум цены
входа: не достигается, LLCR 1,20x не достигается даже при нулевой цене
входа» (владелец, 03.09.2026: «Максимум не достигается?»). Оба числа верные:
1,23x — свод, а подбор для очередей идёт по слабейшей, у которой 0,95x при
текущей цене и 1,19x при бесплатном участке. Противоречие жило не в счёте, а
в подписи: ни карточка, ни причина отказа не говорили, о ком речь.

Закреплено:
- причина отказа называет охват («Слабейшая очередь О1», «Весь проект»),
  порог, диапазон и то, до чего дотянули и где;
- отказ несёт `scope_label` и охват ближайшей точки: при нулевой цене
  слабейшей может оказаться уже другая очередь, и это говорится;
- слой отчёта показывает свод и слабейшую очередь рядом и подписывает отказ
  тем же охватом, что прислал движок, — своего суждения о том, кто слабейший,
  у слоя нет.

Запуск: python3 -m pytest tests/test_the_refused_ceiling_names_whose_llcr_fell_short.py -q
"""

from __future__ import annotations

import copy
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import main_legacy as core  # noqa: E402

OVERLAY = (ROOT / "ia_preview" / "assets" / "overlay.js").read_text(encoding="utf-8")
TARGET = 1.20


def _request(phasing: dict) -> core.AgentChatRequest:
    return core.AgentChatRequest(
        message="",
        inputs=copy.deepcopy(core.DEFAULT_INPUTS),
        tep=copy.deepcopy(core.TEP_DEFAULT),
        rates=copy.deepcopy(core.RATE_CURVE),
        phasing=phasing,
    )


def _ceiling(req: core.AgentChatRequest) -> dict:
    bundle = core._run_authoritative_model(req.inputs, req.tep, req.rates, req.phasing)
    return core._tool_goal_seek(
        req, bundle, "purchase_price_mln", "llcr", TARGET,
        "at_least", "maximum_variable", core._agent_scope_of(bundle), None, None,
    )


@pytest.fixture(scope="module")
def whole_project() -> dict:
    """Умолчания порог не проходят и при нулевой цене — отказ гарантирован."""
    return _ceiling(_request({}))


@pytest.fixture(scope="module")
def two_queues() -> dict:
    phasing = {
        "enabled": True, "phase_count": 2, "phase_gap_months": 12,
        "phases": [
            {"name": "О1", "start_offset_months": 0, "construction_months": 24},
            {"name": "О2", "start_offset_months": 12, "construction_months": 24},
        ],
        "social_objects": [],
        "discrete": {"offices": 2, "standalone_retail": 2, "above_parking": 2},
    }
    return _ceiling(_request(phasing))


def test_the_refusal_says_whose_number_and_how_far(whole_project: dict) -> None:
    assert whole_project["available"] is False
    reason = whole_project["reason"]
    assert reason.startswith("Весь проект: LLCR не ниже 1,20x не достигается"), reason
    assert "даже при нулевом значении" in reason, reason
    closest = whole_project["closest_tested"]
    assert closest["variable"] == 0
    shown = re.search(r"выходит (\d+,\d+)x", reason)
    assert shown, reason
    assert float(shown.group(1).replace(",", ".")) == pytest.approx(closest["metric"], abs=0.005)
    assert whole_project["scope_label"] == "Весь проект"


def test_a_phased_refusal_is_signed_by_the_weakest_queue(two_queues: dict) -> None:
    assert two_queues["available"] is False
    assert two_queues["scope"] == "weakest_phase"
    assert two_queues["scope_label"].startswith("слабейшая очередь О"), two_queues["scope_label"]
    assert two_queues["reason"].startswith("Слабейшая очередь О"), two_queues["reason"]
    # Ближайшая точка подписана своим охватом: при другой цене слабейшей
    # может быть другая очередь, и подпись обязана это пережить.
    assert two_queues["closest_tested"]["scope_label"].startswith("слабейшая очередь О")


def test_the_layer_shows_the_weakest_queue_beside_the_consolidated_llcr() -> None:
    """Слой читает очереди со страницы и подписывает отказ охватом движка."""
    assert "phaseBundle" in OVERLAY, "очереди берутся из phaseBundle страницы"
    assert "LLCR (свод / слабейшая очередь)" in OVERLAY
    assert "goalSeek.closest_tested" in OVERLAY
    assert "goalSeek.scope_label" in OVERLAY
    # Прежняя подпись без охвата исчезла: она и создавала противоречие.
    assert "LLCR 1,20x не достигается даже при нулевой цене входа.'" not in OVERLAY
