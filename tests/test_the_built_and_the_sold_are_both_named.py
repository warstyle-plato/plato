"""Построенных штук и проданных — разные числа, и оба названы.

Владелец, 04.09.2026: «а где у нас указывается „из них гостевых"?». До сих пор
это было сказано только в подписи под строкой паркинга при импорте ГлавАПУ и в
ответе пересчёта по нормативам. В таблице результата, в PDF и в книге стояло
одно число — построенные места, — а продавалось другое.

Разниц теперь две: гостевые места (строятся, но общие) и переданные в натуре
(строятся, но отданы). Обе считает движок и обе везёт строкой ТЭП.

Запуск: python3 -m pytest tests/test_the_built_and_the_sold_are_both_named.py -q
"""

from __future__ import annotations

import io
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import main_legacy as core  # noqa: E402

openpyxl = pytest.importorskip("openpyxl")
PAGE = core.PAGE


def _tep() -> dict[str, dict[str, float]]:
    tep = {key: dict(value) for key, value in core.TEP_DEFAULT.items()}
    tep["underground_parking"].update({"units": 400, "guest_units": 40,
                                       "transfer_units": 25, "gns": 14000,
                                       "total_area": 14000})
    return tep


def test_the_row_of_the_result_carries_both_numbers() -> None:
    """Строка ТЭП несёт построенные, гостевые, переданные и продаваемые."""
    got = core.calculate(core.CalcRequest(
        inputs=dict(core.DEFAULT_INPUTS), tep=_tep(), rates=[]))
    row = next(r for r in got["tep"]["rows"] if r["key"] == "underground_parking")
    assert row["units"] == 400
    assert row["guest_units"] == 40
    assert row["transfer_units"] == 25
    assert row["saleable_units"] == 335
    assert got["tep"]["total"]["saleable_units"] < got["tep"]["total"]["units"]


def test_the_screen_shows_the_sold_column_and_says_why() -> None:
    """У таблицы результата своя колонка проданного и пояснение к разнице."""
    assert "<th>Построено, шт.</th><th>Продаётся, шт.</th>" in PAGE
    assert "из них ${parts.join(' · ')}" in PAGE
    assert "'гостевых '+num(x.guest_units)" in PAGE
    assert "'передано '+num(x.transfer_units)" in PAGE
    # Экран не считает: проданное берётся строкой движка, а не выводится тут.
    assert "x.saleable_units!==undefined?x.saleable_units:x.units" in PAGE


def test_the_book_names_the_guest_and_the_given_places() -> None:
    """В книге рядом с продаваемыми местами стоят гостевые и переданные."""
    content, _, missing = core.build_project_workbook(
        dict(core.DEFAULT_INPUTS), _tep(), [], {}, project_name="П")
    assert not [m for m in missing if "гостев" in m.lower()], missing
    ws = openpyxl.load_workbook(io.BytesIO(content))["Вводные"]
    assert ws["AN87"].value == "Из них гостевых, шт."
    assert ws["AO87"].value == "Из них передано, шт."
    assert float(ws["AB88"].value) == 335, "в продажи идут только непереданные негостевые"
    assert float(ws["AN88"].value) == 40
    assert float(ws["AO88"].value) == 25
    # Обещание книги про место правки приведено к правде: колонки «База
    # гостевых мест» в блоке очередей нет и не было.
    assert "База гостевых мест" not in str(ws["K84"].value)
