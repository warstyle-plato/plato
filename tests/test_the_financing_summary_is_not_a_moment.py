"""Свод финансирования на очередях: итоги, а не моменты.

Владелец, 31.08.2026: «раскрытый эскроу в РВЭ — какое из них? в том числе
принято от предыдущей очереди — какой? это же сводный блок… при очередях
вообще блок должен быть у каждой очереди».

Половина строк блока — величины, привязанные к дате очереди: раскрытие
эскроу, погашение из него, остаток, принятый долг, лимит договора. В своде они
складывались под именами моментов и читались как одно событие. Числа при этом
верные — неверны подписи и место.

Разложено так: по очередям эти величины стоят в таблице сравнения, где у
каждой есть имя и дата РВЭ; в своде остались те же суммы, названные итогами.

Запуск: python3 -m pytest tests/test_the_financing_summary_is_not_a_moment.py -q
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT.parent))

import main as _wrapper  # noqa: E402

core = _wrapper.core


@pytest.fixture(scope="module")
def bundle() -> dict:
    inputs = dict(core.DEFAULT_INPUTS)
    inputs["purchase_price_mln"] = 700
    tep = {key: dict(row) for key, row in core.TEP_DEFAULT.items()}
    return core.calculate_phased(core.PhasedCalcRequest(
        inputs=inputs, tep=tep, rates=[],
        phasing={"enabled": True, "mode": "phased", "user_enabled": True,
                 "phase_count": 2, "phase_gap_months": 12,
                 "phases": [{"name": "О1"}, {"name": "О2"}],
                 "shared_cash": {}, "shared_allocation": {}, "social_objects": []}))


def test_every_queue_carries_its_own_rve_numbers(bundle) -> None:
    """У очереди своя дата раскрытия, свой лимит и свой остаток."""
    rows = bundle["comparison"]
    assert len(rows) > 1
    dates = set()
    for row in rows:
        for key in ("rve", "pf_limit", "rve_pf_before_repayment",
                    "rve_escrow_release", "rve_pf_repayment", "rve_pf_shortfall"):
            assert key in row, (row.get("name"), key)
        assert row["rve"], row.get("name")
        dates.add(row["rve"])
    # Ради чего всё: даты РАЗНЫЕ, и одна подпись «в РВЭ» их не описывает.
    assert len(dates) == len(rows), dates


def test_the_queue_numbers_add_up_to_the_summary(bundle) -> None:
    """Свод — сумма очередей. Иначе таблица и карточка скажут разное."""
    financing = (bundle["consolidated"].get("report") or {}).get("financing") or {}
    for key in ("rve_escrow_release", "rve_pf_repayment", "rve_pf_shortfall",
                "rve_pf_before_repayment", "pf_limit"):
        by_queue = sum(float(row.get(key) or 0.0) for row in bundle["comparison"])
        assert float(financing.get(key) or 0.0) == pytest.approx(by_queue, rel=1e-6), key


def _block(name: str) -> str:
    page = core.PAGE
    start = page.index(name)
    return page[start:start + 6000]


def test_the_summary_calls_them_totals_when_there_are_queues() -> None:
    """На очередях подпись говорит «всего», а не «в РВЭ»."""
    page = core.PAGE
    block = _block("reportFinanceTable.innerHTML=")
    assert "const phased=" in _block("// Свод финансирования на многоочередном")
    for pair in ("'Раскрыто эскроу за проект'", "'Долг ПФ перед раскрытием — всего'",
                 "'Не покрыто эскроу при раскрытии — всего'",
                 "'Лимит ПФ — сумма по очередям'"):
        assert pair in block, pair
    # Одиночный проект подписи не теряет: там «в РВЭ» — правда.
    for pair in ("'Долг ПФ перед раскрытием в РВЭ'", "'Раскрытый эскроу в РВЭ'",
                 "'Остаток ПФ после раскрытия в РВЭ'"):
        assert pair in block, pair


def test_the_receiving_queue_is_named_in_the_table_not_the_summary() -> None:
    """«Принято от предыдущей» в своде — сумма приёмов, и при трёх очередях
    «предыдущая» не отвечает ни на что. В своде остаётся итог."""
    block = _block("reportFinanceTable.innerHTML=")
    assert "'Переоформлено между очередями, всего'" in block
    assert "!phased&&Number(r.report.financing.carried_debt_in" in block.replace(" ", "")


def test_the_comparison_table_shows_the_rve_block() -> None:
    """Место этих величин — рядом с именем очереди и её датой."""
    body = core.PAGE[core.PAGE.index("const rows=["):]
    body = body[:body.index("phaseComparisonBody.innerHTML")]
    for label in ("'Лимит ПФ'", "'РВЭ очереди'", "'Долг ПФ перед раскрытием'",
                  "'Раскрыто эскроу'", "'Из него на погашение ПФ'",
                  "'Не покрыто эскроу при раскрытии'"):
        assert label in body, label
    assert "dateRu(x.rve)" in body


def test_the_pdf_says_the_same_thing() -> None:
    """Отчёт носят в банк — там подписи обязаны быть теми же."""
    source = Path(core.__file__).read_text(encoding="utf-8")
    assert "_pdf_phased = len(result.get(\"comparison\") or []) > 1" in source
    assert 'f"{base} — всего" if _pdf_phased else f"{base} в РВЭ"' in source
    # И четвёртое число, без которого три не вычитаются, теперь в PDF тоже.
    assert '["Из него на погашение ПФ",_pdf_money(financing.get(\'rve_pf_repayment\'))]' in source
