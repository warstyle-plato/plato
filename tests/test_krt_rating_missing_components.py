"""Regression tests for KRT rating components that were visibly stuck at 50%.

A persisted Moscow absorption benchmark of 0 must be treated as missing and
rebuilt.  The city benchmark itself must not collapse to zero because zero
monthly rows cannot be a denominator for the absorption ratio.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from auction_search import api  # noqa: E402
from market_search.market_reference import MoscowMarket  # noqa: E402


def test_zero_or_negative_benchmark_is_not_a_valid_denominator() -> None:
    assert api._positive_float(None) is None
    assert api._positive_float(0) is None
    assert api._positive_float("0") is None
    assert api._positive_float(-1) is None
    assert api._positive_float("88.5") == 88.5


def test_moscow_absorption_benchmark_ignores_zero_months(tmp_path: Path) -> None:
    (tmp_path / "moscow-market-2026-08.json").write_text(
        json.dumps({
            "last_month": "2026-08",
            "source": "test",
            "current": {"Бизнес": {"projects": 3}},
        }, ensure_ascii=False),
        encoding="utf-8",
    )
    (tmp_path / "moscow-dynamics-2026-08.json").write_text(
        json.dumps({
            "last_month": "2026-08",
            "months": ["2026-08"],
            "source": "test",
            "projects": {
                "silent": {"segment": "Бизнес", "area": [0]},
                "one": {"segment": "Бизнес", "area": [100]},
                "two": {"segment": "Бизнес", "area": [200]},
            },
        }, ensure_ascii=False),
        encoding="utf-8",
    )

    city = MoscowMarket.bundled(tmp_path)

    assert city.area_median("Бизнес") == 150.0


def test_card_exposes_the_real_burden_failure_reason() -> None:
    source = Path(api.__file__).read_text(encoding="utf-8")
    assert 'str(row.get("burden_reason") or "")' in source
