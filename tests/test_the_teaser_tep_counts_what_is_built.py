"""ТЭП тизера: единицы — построенное в мере счёта, итог ГНС — сумма строк.

Владелец, 14.10.2026, по тизеру «1-я Останкинская»: «Нет количества квартир»
у строки квартир стояло «—», у паркинга 108 проданных мест над итогом
«90 квартир · 119 м/м», а итог колонки ГНС — 14 203 (наземная) под строками на
18 666. Полный PDF печатает 90 квартир, 119 м/м и 18 666; тизер берёт те же
числа у движка (`_presentation_product_count`, суммарная площадь в ГНС).

На прежнем коде падает: квартир в строке нет, паркинг 1 090 вместо 1 199,
итог — наземная ГНС.

Запуск: python3 -m pytest tests/test_the_teaser_tep_counts_what_is_built.py -q
"""

from __future__ import annotations

import copy
import io
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import main as _wrapper  # noqa: E402

core = _wrapper.core


def _fmt(value: float) -> str:
    return f"{value:,.0f}".replace(",", " ")


@pytest.fixture(scope="module")
def teaser():
    from pypdf import PdfReader
    inputs, tep = copy.deepcopy(core.DEFAULT_INPUTS), copy.deepcopy(core.TEP_DEFAULT)
    bundle = core._run_authoritative_model(inputs, tep, [], {})
    pdf = core.build_teaser_pdf(bundle, inputs, tep, {})
    text = " ".join(p.extract_text() for p in PdfReader(io.BytesIO(pdf)).pages)
    return bundle["consolidated"], re.sub(r"\s+", " ", text)


def test_rows_print_built_units_in_their_measure(teaser):
    consolidated, text = teaser
    rows = {r["key"]: r for r in consolidated["tep"]["rows"]}
    flats, parking = rows["apartments"], rows["underground_parking"]
    assert parking["saleable_units"] < parking["units"], "умолчания должны различать проданные и построенные"
    assert re.search(r"Квартиры [\d ]+ [\d ]+ " + _fmt(flats["units"]) + " ", text)
    assert re.search(r"Подземный паркинг [\d ]+ — " + _fmt(parking["units"]) + " ", text)
    assert not re.search(r"Подземный паркинг [\d ]+ — " + _fmt(parking["saleable_units"]) + " ", text)


def test_total_is_the_sum_of_the_rows(teaser):
    consolidated, text = teaser
    summary = consolidated["summary"]
    assert summary["construction_volume_sqm"] != pytest.approx(summary["project_gns_sqm"])
    assert re.search(r"Итого " + _fmt(summary["construction_volume_sqm"]) + " ", text)
    assert not re.search(r"Итого " + _fmt(summary["project_gns_sqm"]) + " ", text)
