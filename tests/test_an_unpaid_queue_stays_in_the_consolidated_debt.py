"""Долг очереди, чья линия кончилась, остаётся в сводном ряду.

Помесячный свод складывал строки очередей, а очередь после конца своего
горизонта строк не имеет — и выпадала из суммы месяца ЦЕЛИКОМ, вместе с
непогашенным долгом. На пресете Нагатино первая очередь кончается 2033-01 с
долгом 2 348,19 млн, вторая 2034-01 с 623,81: с этих месяцев сводный долг падал
ровно на них, и пик «одновременно открытых линий» выходил 92 150,16 против
94 498,35. Движок при этом ЗНАЛ, что долг остался: сумма хвостов стоит у него в
`ending_pf` свода до копейки — но в помесячный ряд не попадала, а из него
считаются пик ПФ, пик общего долга, покрытие и график эскроу. Книга хвосты
держала и была права; блок паритета это и показывал.

Поток и остаток здесь складываются по-разному, и вторая половина правила не
менее важна первой: выборка, погашение, проценты и выручка после конца
горизонта равны нулю, а долг, счёт эскроу и начисленное к уплате — нет.
Перенесённый поток задвоил бы выручку и CAPEX.

Запуск: python3 -m pytest tests/test_an_unpaid_queue_stays_in_the_consolidated_debt.py -q
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import main as wrapper  # noqa: E402
import project_preset  # noqa: E402

core = wrapper.core

_MLN = 1e6


@pytest.fixture(scope="module")
def bundle():
    """Пресет с ДЕФОЛТНОЙ очередью: на рассчитавшихся проверять нечего."""
    sys.setrecursionlimit(400000)
    preset = json.loads(
        (ROOT / "presets" / "КРТ_Нагатино.json").read_text(encoding="utf-8"))
    preview = project_preset.build_preview(preset)
    inputs = {**core.DEFAULT_INPUTS, **preview["inputs"]}
    tep = {key: dict(value) for key, value in core.TEP_DEFAULT.items()}
    for key, row in (preview["tep"] or {}).items():
        tep.setdefault(key, {})
        tep[key].update(row)
    return core._run_authoritative_model(inputs, tep, [], preview["phasing"])


def _tails(bundle) -> dict[int, tuple[str, float]]:
    """Очереди, кончившиеся с непогашенным долгом: последний месяц и остаток."""
    out: dict[int, tuple[str, float]] = {}
    for index, phase in enumerate(bundle["phases"]):
        rows = phase["result"]["finance"]["rows"]
        last = rows[-1]
        debt = float(last.get("pf_balance") or 0.0)
        if debt > 0:
            out[index] = (str(last["month"]), debt)
    return out


def test_this_project_actually_has_an_unpaid_queue(bundle):
    """Предохранитель: без дефолтной очереди и горизонта длиннее неё проверки
    ниже зелены на любом коде — складывать было бы нечего."""
    tails = _tails(bundle)
    assert tails, "все очереди рассчитались — проверять перенос не на чем"
    rows = bundle["consolidated"]["finance"]["rows"]
    last_month = str(rows[-1]["month"])
    assert any(month < last_month for month, _ in tails.values()), (
        "горизонт свода не длиннее ни одной дефолтной очереди")


def test_the_consolidated_debt_exceeds_the_live_queues_by_the_tails(bundle):
    """Сводный долг месяца = долг живых очередей + хвосты кончившихся.

    Утверждение именно равенством, а не «не меньше»: сводный долг в разгар
    стройки — десятки миллиардов, и «не меньше хвоста» проходит на любом коде.
    Долг живых очередей берётся из их же строк (что есть, то и читаем), хвост —
    из последней строки кончившейся: перенос здесь не повторяется, а
    ПРОВЕРЯЕТСЯ.
    """
    rows = {str(row["month"]): row for row in bundle["consolidated"]["finance"]["rows"]}
    tails = _tails(bundle)
    checked = 0
    for month in sorted(rows):
        ended = {index: debt for index, (last, debt) in tails.items() if last < month}
        if not ended:
            continue
        live = sum(
            float(row.get("pf_balance") or 0.0)
            for phase in bundle["phases"]
            for row in phase["result"]["finance"]["rows"]
            if str(row["month"]) == month)
        expected = live + sum(ended.values())
        assert float(rows[month].get("pf_balance") or 0.0) == pytest.approx(
            expected, abs=1.0), (
            f"{month}: свод {float(rows[month].get('pf_balance') or 0.0) / _MLN:.2f} млн "
            f"против живых {live / _MLN:.2f} плюс хвосты "
            f"{sum(ended.values()) / _MLN:.2f}")
        checked += 1
    assert checked > 0, "не нашлось ни одного месяца после конца дефолтной очереди"


def test_the_last_consolidated_month_owes_exactly_the_tails(bundle):
    """На конец горизонта сводный долг равен сумме хвостов и `ending_pf`.

    Долг, исчезнувший из ряда, но названный итогом, — это два ответа об одном
    обязательстве, и оба выглядят верными.
    """
    finance = bundle["consolidated"]["finance"]
    expected = sum(debt for _, debt in _tails(bundle).values())
    assert float(finance["rows"][-1].get("pf_balance") or 0.0) == pytest.approx(
        expected, abs=1.0)
    assert float(finance.get("ending_pf") or 0.0) == pytest.approx(expected, abs=1.0)


def test_the_peak_sees_the_tail_too(bundle):
    """Пик ПФ свода не ниже любого месяца ряда — включая месяцы с хвостами."""
    finance = bundle["consolidated"]["finance"]
    highest = max(float(row.get("pf_balance") or 0.0) for row in finance["rows"])
    assert float(finance["peak_pf"]) == pytest.approx(highest, abs=1.0)
    assert float(finance["peak_total_debt"]) >= highest - 1.0
    # И пик обязан быть не ниже месяца, где к живым линиям добавился хвост:
    # на прежнем коде он выходил на 2 348,19 млн ниже — ровно на долг первой
    # очереди, дефолтнувшей до месяца пика.
    tails = _tails(bundle)
    peak_month = max(finance["rows"], key=lambda row: float(row.get("pf_balance") or 0.0))
    ended_by_peak = sum(
        debt for last, debt in tails.values() if last < str(peak_month["month"]))
    assert ended_by_peak > 0, "к месяцу пика ни одна очередь не успела кончиться"
    live_at_peak = sum(
        float(row.get("pf_balance") or 0.0)
        for phase in bundle["phases"]
        for row in phase["result"]["finance"]["rows"]
        if str(row["month"]) == str(peak_month["month"]))
    assert float(finance["peak_pf"]) == pytest.approx(
        live_at_peak + ended_by_peak, abs=1.0)


def test_a_flow_is_not_carried_forward(bundle):
    """Потоки НЕ переносятся: их итог по своду равен сумме по очередям.

    Обратная половина правила. Перенесённый поток удвоил бы выручку и CAPEX, и
    сумма ряда разошлась бы с суммой очередей — молча и в плюс.
    """
    rows = bundle["consolidated"]["finance"]["rows"]
    for key in ("revenue", "capex", "pf_draw", "pf_repayment"):
        total = sum(float(row.get(key) or 0.0) for row in rows)
        by_phase = sum(
            float(row.get(key) or 0.0)
            for phase in bundle["phases"]
            for row in phase["result"]["finance"]["rows"])
        assert total == pytest.approx(by_phase, rel=1e-9, abs=1.0), key
