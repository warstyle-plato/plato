"""Книга называет вводную ключом движка — иначе сверить её нечем.

Владелец: «эксель должен работать почти как движок… если что-то меняешь где-то,
все должно меняться так же как в движке» (03.09.2026). Проверить это можно
только по имени: «Старт» и «Остаточные продажи» — оформление, а project_start и
residual_sales_months — утверждение о том, какую вводную правишь.

Ревизия нашла в шаблоне подпись `sales_term_default_months` над ячейкой, куда
движок пишет `residual_sales_months`: одно число под двумя именами. Ключ теперь
берётся из той же карты, что решает, куда писать значение, — второго списка
«какой ключ в какой ячейке» не бывает.

Запуск: python3 -m pytest tests/test_the_book_names_its_inputs.py -q
"""

from __future__ import annotations

import io
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import main_legacy as core  # noqa: E402

openpyxl = pytest.importorskip("openpyxl")


@pytest.fixture(scope="module")
def sheet():
    content, _, _ = core.build_project_workbook(
        {**core.DEFAULT_INPUTS}, core.TEP_DEFAULT, [], {}, project_name="Имена")
    return openpyxl.load_workbook(io.BytesIO(content), data_only=False)["Вводные"]


def test_every_mapped_input_carries_its_key(sheet):
    """Подпись берётся из карты, значит расходиться ей негде — но проверяем."""
    for key, coord in core._V4_INPUT_CELLS.items():
        label_column = {"B": "D", "K": "M"}.get(coord[0])
        assert label_column, f"{key}: колонка {coord[0]} без колонки подписи"
        assert sheet[f"{label_column}{coord[1:]}"].value == key, (key, coord)


def test_the_stale_key_is_gone(sheet):
    """Тот самый случай: шаблон подписывал остаточные продажи чужим именем."""
    labels = {str(sheet[f"D{row}"].value or "") for row in range(1, sheet.max_row + 1)}
    assert "residual_sales_months" in labels
    assert "sales_term_default_months" not in labels


def test_the_queue_columns_say_which_input_they_are(sheet):
    """Срок ИРД и срок стройки правят в колонке очереди, а не в строке проекта."""
    for column, key in (("D", "project_start"), ("E", "ird_months"),
                        ("F", "construction_months"), ("G", "sales_lag_months")):
        header = str(sheet[f"{column}87"].value or "")
        assert key in header, (column, header)
        # Подпись шаблона остаётся на месте: ключ дописан к ней, а не заменил её.
        assert header.split(" · ")[0].strip(), header


def test_a_social_object_alone_in_the_project_carries_the_key(sheet):
    """Ключ ставится там, где строка несёт ВСЮ вводную. У книги умолчаний садик
    один и стоит в первой очереди — значит ключ на его строке."""
    row = next(number for number in range(1, sheet.max_row + 1)
               if str(sheet[f"A{number}"].value or "") == "ДОО — очередь 1")
    assert sheet[f"H{row}"].value == "kindergarten_places"
    assert sheet[f"I{row}"].value == "kindergarten_cost_mln_per_place"
    assert sheet[f"J{row}"].value == "kindergarten_start"
    assert sheet[f"K{row}"].value == "kindergarten_months"


def test_a_social_object_split_across_queues_carries_no_project_key():
    """Доля очереди — не вся вводная, и подписывать её проектным ключом значит
    назвать часть целым. То же правило, по которому свод не подписывают именем
    момента."""
    phasing = {
        "enabled": True, "mode": "phased", "user_enabled": True,
        "phase_count": 2, "phase_gap_months": 12,
        "phases": [{"start_offset_months": 12 * index, "construction_months": 24}
                   for index in range(2)],
        "products": {key: [50, 50] for key in
                     ("apartments", "ground_commercial", "underground_parking")},
        "shared_cash": {}, "shared_allocation": {},
        "social_objects": [{"type": "kindergarten", "capacity": 150, "phase": 1},
                           {"type": "kindergarten", "capacity": 100, "phase": 2}],
        "carry_debt_forward": False,
    }
    content, _, _ = core.build_project_workbook(
        {**core.DEFAULT_INPUTS}, core.TEP_DEFAULT, [], phasing, project_name="Доли")
    sheet = openpyxl.load_workbook(io.BytesIO(content), data_only=False)["Вводные"]
    for phase in (1, 2):
        row = next(number for number in range(1, sheet.max_row + 1)
                   if str(sheet[f"A{number}"].value or "") == f"ДОО — очередь {phase}")
        assert sheet[f"H{row}"].value in (None, ""), (phase, sheet[f"H{row}"].value)
