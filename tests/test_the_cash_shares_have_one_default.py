"""Умолчание кассовых долей объявляется один раз — на движок и книгу.

Копия жила в книге и говорила другое: `_v4_shared_weights` при пустом
`shared_cash` валила ВСЕ статьи на первую очередь, а движок раскладывал ИРД,
проектирование, подготовку и наружные сети по весам очередей. Страница долю
всегда присылает, поэтому в жизни это не всплывало, а через API отчёт и книга
расходились молча.

Тот же класс ошибки, что копия `FIELD_GROUPS` на странице и четырнадцать копий
`VERSION`: умолчание, объявленное дважды, однажды разойдётся, и обе стороны
будут выглядеть верно.

Запуск: python3 -m pytest tests/test_the_cash_shares_have_one_default.py -q
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import main as _wrapper  # noqa: E402

core = _wrapper.core


@pytest.mark.parametrize("count", [1, 2, 3, 4])
def test_the_book_falls_back_to_the_engine_defaults(count):
    engine = core.phase_cash_default_weights(count)
    for key, weights in engine.items():
        book = core._v4_shared_weights({}, key, count)
        assert len(book) == count
        total = sum(weights)
        expected = [value / total for value in weights]
        assert book == pytest.approx(expected), (
            f"«{key}»: книга при пустом shared_cash раскладывает не так, как движок")


def test_the_articles_that_are_not_first_queue_only_are_actually_spread():
    """Предохранитель. Если умолчания вдруг станут «всё в первую очередь» для
    всех статей, тест выше пройдёт на равенстве двух неверных вещей."""
    defaults = core.phase_cash_default_weights(3)
    for key in ("ird", "design", "preparation", "utilities"):
        assert defaults[key][1] > 0, (
            f"«{key}» по умолчанию обязана раскладываться по очередям, а не "
            "падать целиком на первую")
    for key in ("purchase", "land_rights", "social_compensation", "own_funds"):
        assert defaults[key] == [100.0, 0.0, 0.0]


def test_an_explicit_share_still_wins():
    book = core._v4_shared_weights({"shared_cash": {"ird": [20, 80]}}, "ird", 2)
    assert book == pytest.approx([0.2, 0.8])
