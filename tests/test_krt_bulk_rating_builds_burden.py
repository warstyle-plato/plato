"""Regression: bulk KRT rating must build the fourth #485 component.

The catalogue button calls investment-score with ensure_model=true.  Before this
regression it only built market/model; generic burden lived exclusively in a
separate background pass, so almost every row stopped at 50/75% and Nagatino
was the lone 100% control case.
"""

from __future__ import annotations

import inspect
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from auction_search import api  # noqa: E402


def test_bulk_rating_explicitly_builds_generic_burden() -> None:
    source = inspect.getsource(api.install)
    route = source[
        source.index('async def auction_krt_investment_score'):
        source.index('async def auction_krt_nagatino_live_data')
    ]

    assert 'if ensure_model:' in route
    assert '_explicit_rating_burden' in route
    assert 'generic_project_burden' in source
    assert 'lookup_chunk=24' in source
    assert '"burden_complete"' in route
    assert '"burden_reason"' in route


def test_explicit_burden_finishes_more_than_one_chunk() -> None:
    source = inspect.getsource(api.install)
    helper = source[
        source.index('def _explicit_rating_burden'):
        source.index('@app.get("/auctions/krt/{slug}/investment-score"')
    ]

    assert 'for _ in range(3)' in helper
    assert 'if not state.get("pending")' in helper
