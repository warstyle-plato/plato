"""Срок рассрочки платы за ВРИ в Москве задан суммой платы, а не вводом.

593-ПП, прил. 1 пп. 3.1–3.3 (сверено по «Кодексу» 25.10.2026): до 100 млн ₽ —
один год, от 100 до 500 млн ₽ — не более трёх лет, свыше 500 млн ₽ — не более
шести. Прежде движок брал срок из поля (по умолчанию 3 года), и плата в 80 млн ₽
получала три года рассрочки, которых постановление не даёт. Решение владельца
25.10.2026: срок по умолчанию — предел по сумме, ввод может сократить, но не
удлинить.
"""
from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import main as _wrapper  # noqa: E402

core = _wrapper.core
PERMIT = date(2028, 7, 1)


def _schedule(amount_mln: float, **overrides) -> dict:
    x = {"rate_start_pct": 12.0, "vri_obligation_date_mode": "at_rns", "vri_region": "msk",
         "vri_required": True, "vri_payment_mode": "installment", **overrides}
    return core.build_vri_schedule(x, amount_mln * 1_000_000, PERMIT)


def test_the_limit_is_the_decree_table() -> None:
    limit = core.vri_msk_term_limit
    assert [limit(80e6), limit(100e6), limit(100.5e6), limit(500e6), limit(501e6)] == [1, 1, 3, 3, 6]


def test_a_small_fee_gets_one_year_even_when_three_were_asked() -> None:
    got = _schedule(80, vri_installment_years=3)
    assert got["settings"]["years"] == 1
    assert len(got["rows"]) == 4, "один год поквартально — четыре платежа"
    assert any("593-ПП" in w and "сокращён до 1" in w for w in got["warnings"])


def test_empty_term_means_the_decree_limit() -> None:
    assert _schedule(80, vri_installment_years=0)["settings"]["years"] == 1
    assert _schedule(300, vri_installment_years=0)["settings"]["years"] == 3
    assert _schedule(900, vri_installment_years=0)["settings"]["years"] == 6


def test_a_shorter_term_is_kept_and_not_warned() -> None:
    got = _schedule(900, vri_installment_years=3)
    assert got["settings"]["years"] == 3
    assert not any("593-ПП" in w for w in got["warnings"])


def test_the_oblast_is_not_touched() -> None:
    got = _schedule(80, vri_region="mo", vri_installment_years=3)
    assert got["settings"]["years"] == 3 and got["settings"]["term_limit"] is None
