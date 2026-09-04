"""Проценты уменьшают базу в месяце начисления, а не в месяце уплаты.

Пункт 8 статьи 272 НК: по договорам, срок действия которых приходится более
чем на один отчётный период, расход признаётся на конец КАЖДОГО МЕСЯЦА
независимо от даты выплат по договору.

Прежде вычет строился по `interest_payment`: у проекта с эскроу проценты
платятся разом в дату раскрытия, а всё, чего в этой строке нет вовсе —
проценты БРИДЖа, капитализация, плата за лимит и обе разовые комиссии, —
досыпалось в ПОСЛЕДНИЙ месяц горизонта. Сумма при этом сходилась, момент нет:
на умолчаниях 2 634 млн ₽ вычета стояли не в тех годах.

Запуск: python3 -m pytest tests/test_interest_reduces_the_base_when_it_accrues.py -q
"""

from __future__ import annotations

import inspect
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import main_legacy as core  # noqa: E402


def _finance(**overrides) -> dict:
    inputs = dict(core.DEFAULT_INPUTS)
    inputs.update(overrides)
    tep = {key: dict(value) for key, value in core.TEP_DEFAULT.items()}
    return core._run_authoritative_model(inputs, tep, [], {})["consolidated"]["finance"]


def _deduction(row: dict) -> float:
    return float(row.get("financing_tax_deduction", 0.0) or 0.0)


def test_the_schedule_equals_the_reported_cost() -> None:
    """График начисления обязан сойтись со стоимостью финансирования."""
    for name, kwargs in (
        ("умолчания", {}),
        ("сильный проект", {"apartment_price_th": 450.0}),
        ("длинный хвост", {"residual_sales_months": 36}),
    ):
        finance = _finance(**kwargs)
        total = sum(_deduction(row) for row in finance["rows"])
        cost = float(finance["financing_cost"])
        assert abs(cost - total) < 1_000, f"{name}: {cost:.0f} против {total:.0f}"


def test_the_deduction_stands_in_the_month_of_accrual() -> None:
    """Месяц, где проценты начислены и не выплачены, вычет всё равно несёт."""
    finance = _finance()
    accrued_unpaid = [
        row for row in finance["rows"]
        if float(row.get("pf_interest", 0.0) or 0.0) > 0
        and float(row.get("interest_payment", 0.0) or 0.0) == 0
    ]
    assert accrued_unpaid, "на этих вводных проценты платятся сразу — проверка слепа"
    for row in accrued_unpaid:
        assert _deduction(row) > 0, f"{row['month']}: начислено, а вычета нет"


def test_nothing_is_dumped_into_the_last_month() -> None:
    """Остаток больше не досыпается в конец горизонта: там сверка, а не признание."""
    finance = _finance()
    rows = finance["rows"]
    last = _deduction(rows[-1])
    body = sum(_deduction(row) for row in rows)
    assert last < body * 0.02, (
        f"в последний месяц ушло {last:.0f} из {body:.0f} — это досыпка, а не начисление")


def test_the_one_off_fees_stand_at_their_own_dates() -> None:
    """Комиссии за выдачу и резервирование в помесячные строки не входят."""
    source = inspect.getsource(core.simulate_financing)
    block = source[source.index("financing_deductions: dict[date, float]"):]
    block = block[:block.index("financing_reconciliation")]
    assert "bridge_interest" in block and "pf_interest" in block and "limit_fee" in block
    assert "bridge_capitalization" in block and "pf_interest_capitalization" in block
    assert "interest_payment" not in block, "вычет снова строится по выплате"
    assert "financing_deductions[project_start] += result[\"bridge_fee\"]" in block
    assert "financing_deductions[permit] += result[\"pf_reservation_fee\"]" in block
