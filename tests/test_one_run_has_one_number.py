"""Один расчёт — один номер, иначе номер доказывает обратное тому, ради чего заведён.

Отпечаток расчёта стоит в шапке PDF и на листе «Источники» книги, чтобы сверка
пары начиналась с вопроса «один ли это прогон», а не со спора о версиях. Считали
его две поверхности по-разному: книга — по вводным, слитым с умолчаниями
(выгрузка подмешивает `DEFAULT_INPUTS` первой же строкой), PDF — по
сырым, как их прислала страница. Совпасть они могли только у набора, где задано каждое поле; на живом проекте номера расходились ВСЕГДА.

Цена ошибки не в номере. 25.08.2026 владелец прислал PDF и книгу одного прогона,
номера разошлись — и по ним был дан неверный ответ: «это разные расчёты, сверять
нельзя». Инструмент, заведённый доказывать тождество, доказал обратное, и ему
поверили.

Запуск: python3 -m pytest tests/test_one_run_has_one_number.py -q
"""

from __future__ import annotations

import copy
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import main_legacy as core  # noqa: E402

RAW_INPUTS = {"purchase_price_mln": 6000, "offices_enabled": True}
RAW_TEP = {"apartments": {"gns": 222000, "saleable": 166500}}


def _as_the_book_sees_it(inputs, tep):
    """Ровно то, что делает выгрузка книги перед расчётом."""
    merged_inputs = {**copy.deepcopy(core.DEFAULT_INPUTS), **inputs}
    merged_tep = copy.deepcopy(core.TEP_DEFAULT)
    for key, values in tep.items():
        if isinstance(values, dict) and key in merged_tep:
            merged_tep[key].update(values)
        else:
            merged_tep[key] = values
    return merged_inputs, merged_tep


def test_the_raw_and_the_merged_inputs_give_one_number() -> None:
    """PDF считает по присланному, книга — по слитому. Расчёт один и тот же."""
    book_inputs, book_tep = _as_the_book_sees_it(RAW_INPUTS, RAW_TEP)
    assert core._calculation_fingerprint(RAW_INPUTS, RAW_TEP, {}) \
        == core._calculation_fingerprint(book_inputs, book_tep, {})


def test_an_absent_phasing_is_the_same_as_an_empty_one() -> None:
    """`payload.get('phasing')` даёт None, `phasing or {}` — пустой словарь."""
    assert core._calculation_fingerprint(RAW_INPUTS, RAW_TEP, None) \
        == core._calculation_fingerprint(RAW_INPUTS, RAW_TEP, {})


def test_a_real_difference_still_changes_the_number() -> None:
    """Нормализация не должна склеить разные расчёты в один номер."""
    other = {**RAW_INPUTS, "purchase_price_mln": 6001}
    assert core._calculation_fingerprint(RAW_INPUTS, RAW_TEP, {}) \
        != core._calculation_fingerprint(other, RAW_TEP, {})
    other_tep = {"apartments": {"gns": 222000, "saleable": 166501}}
    assert core._calculation_fingerprint(RAW_INPUTS, RAW_TEP, {}) \
        != core._calculation_fingerprint(RAW_INPUTS, other_tep, {})


def test_the_normalisation_lives_in_the_fingerprint_not_in_the_callers() -> None:
    """Третья поверхность со своим набором под рукой получит тот же номер.

    Пока слияние делал звонящий, оно было у книги и не было у PDF — и это
    невозможно было заметить, глядя на любую из двух поверхностей отдельно.
    """
    source = Path(core.__file__).read_text(encoding="utf-8")
    start = source.index("def _calculation_fingerprint(")
    body = source[start:source.index("\ndef ", start + 10)]
    assert "DEFAULT_INPUTS" in body and "TEP_DEFAULT" in body
