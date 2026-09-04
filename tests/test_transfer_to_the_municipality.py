"""Переданные муниципалитету метры: не продаются и уменьшают плату за ВРИ.

В Подмосковье есть условия, при которых застройщик передаёт муниципалитету
какое-то количество метров и на их стоимость уменьшает плату за смену ВРИ
(владелец, 19.08.2026). До сих пор колонка «передаваемая» в таблице ТЭП была
справочной: вписанное в неё число не двигало ни выручку, ни плату — ни в
движке, ни в книге.

Два правила, из которых это собрано:

* переданные метры строятся, но не продаются — ГНС и общая площадь остаются,
  продаваемая уменьшается на переданное;
* сумма зачёта берётся из соглашения, а не считается нами по цене продажи:
  муниципалитет засчитывает по своей оценке, и она другая. Поэтому это
  отдельная вводная, а не производная от площади.

Запуск: python3 -m pytest tests/test_transfer_to_the_municipality.py -q
"""

from __future__ import annotations

import copy
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import v4_inputs  # noqa: E402

import main as wrapper  # noqa: E402

core = wrapper.core

BASE = {**core.DEFAULT_INPUTS, "vri_required": True, "land_rights_cost_mln": 1000.0}


def _summary(extra: dict) -> dict:
    return core.calculate(core.CalcRequest(
        inputs={**BASE, **extra}, tep=copy.deepcopy(core.TEP_DEFAULT)))["summary"]


def test_the_offset_lowers_the_vri_payment():
    """Зачёт 300 млн ₽ уменьшает обязательство ровно на 300 млн ₽."""
    gross = core.vri_relief({}, 1000e6)[1]
    assert gross == pytest.approx(1000e6)
    relief, net = core.vri_relief({"vri_transfer_offset_mln": 300.0}, 1000e6)
    assert relief == pytest.approx(300e6)
    assert net == pytest.approx(700e6)


def test_the_offset_adds_up_with_the_relief():
    """Льгота и зачёт — разные основания: складываются, а не заменяют друг друга."""
    relief, net = core.vri_relief(
        {"vri_relief_mode": "amount", "vri_relief_mln": 200.0,
         "vri_transfer_offset_mln": 300.0}, 1000e6)
    assert relief == pytest.approx(500e6)
    assert net == pytest.approx(500e6)


def test_the_offset_never_makes_the_payment_negative():
    relief, net = core.vri_relief({"vri_transfer_offset_mln": 5000.0}, 1000e6)
    assert relief == pytest.approx(1000e6)
    assert net == 0.0


def test_the_offset_reaches_the_model():
    """Через вводные — до прибыли: 300 млн ₽ зачёта видно в результате."""
    without = _summary({})
    with_offset = _summary({"vri_transfer_offset_mln": 300.0})
    assert with_offset["net_profit"] > without["net_profit"]
    assert "vri_transfer_offset_mln" in core.DEFAULT_INPUTS
    labels = [name for group in core.FIELD_GROUPS for name, *_ in group[1]]
    assert "vri_transfer_offset_mln" in labels, "поля нет на вкладке «Вводные»"


def test_the_transferred_metres_leave_the_saleable_area():
    """Метры строятся, но не продаются: ГНС на месте, продаваемая меньше."""
    body = core.PAGE[core.PAGE.index("function tepCellChanged"):]
    body = body[:body.index("let storageInsideParking")]
    assert "col==='transfer'" in body
    assert "tep[key].saleable=Math.max(0" in body
    assert "не продаются" in body
    # У соцобъектов передаваемая — вся площадь объекта, правило туда не идёт.
    assert "TEP_RATIOS[key]" in body.split("col==='transfer'")[1][:120]


def test_the_workbook_gets_the_offset_too():
    """Книга должна платить столько же, сколько движок.

    Строку в шаблон не вставить — поедут все ссылки, — а формулы листов ВРИ и
    ОТЧЁТ вычитают из платы именно ячейку льготы. Поэтому зачёт ложится туда же
    суммой: у книги и движка одна плата к оплате, и `audit_plato_workbook` их
    сводит без расхождения.
    """
    import io

    openpyxl = pytest.importorskip("openpyxl")
    inputs = {**BASE, "vri_relief_mode": "amount", "vri_relief_mln": 200.0,
              "vri_transfer_offset_mln": 300.0}
    content, _, missing = core.build_project_workbook(
        inputs, copy.deepcopy(core.TEP_DEFAULT), [], {}, project_name="Проверка")
    assert not [item for item in missing if "vri" in item], missing
    book = openpyxl.load_workbook(io.BytesIO(content))
    assert v4_inputs.inputs(book)["B82"].value == pytest.approx(500.0)

    # Столько же остаётся к оплате в движке: 1 000 − 200 льготы − 300 зачёта.
    _, net = core.vri_relief(inputs, 1000e6)
    assert net == pytest.approx(500e6)


def test_the_workbook_builds_on_the_reduced_saleable_area():
    """Книга берёт продаваемую из ТЭП — значит переданное в неё не попадает.

    Лист ТЭП книги v4 собирается формулами из «Вводных»: ГНС и продаваемая
    приходят отдельными ячейками. Передали метры городу — продаваемая меньше,
    ГНС на месте: строят столько же, продают меньше.
    """
    import io

    openpyxl = pytest.importorskip("openpyxl")

    def cells(tep):
        content, _, _ = core.build_project_workbook(
            {**BASE}, tep, [], {}, project_name="Проверка")
        sheet = v4_inputs.inputs(openpyxl.load_workbook(io.BytesIO(content)))
        return sheet["W88"].value, sheet["Z88"].value

    plain = copy.deepcopy(core.TEP_DEFAULT)
    handed = copy.deepcopy(core.TEP_DEFAULT)
    handed["apartments"]["saleable"] -= 10000
    handed["apartments"]["transfer"] = 10000

    gns_before, saleable_before = cells(plain)
    gns_after, saleable_after = cells(handed)
    assert gns_before == gns_after, "ГНС не меняется: метры строятся"
    assert saleable_before - saleable_after == pytest.approx(10000)
