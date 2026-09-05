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

import v4_inputs  # noqa: E402

openpyxl = pytest.importorskip("openpyxl")


@pytest.fixture(scope="module")
def sheet():
    content, _, _ = core.build_project_workbook(
        {**core.DEFAULT_INPUTS}, core.TEP_DEFAULT, [], {}, project_name="Имена")
    return v4_inputs.inputs(openpyxl.load_workbook(io.BytesIO(content), data_only=False))


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
    sheet = v4_inputs.inputs(openpyxl.load_workbook(io.BytesIO(content), data_only=False))
    for phase in (1, 2):
        row = next(number for number in range(1, sheet.max_row + 1)
                   if str(sheet[f"A{number}"].value or "") == f"ДОО — очередь {phase}")
        assert sheet[f"H{row}"].value in (None, ""), (phase, sheet[f"H{row}"].value)


# --- блоки внизу листа ------------------------------------------------------

BLOCK_INPUTS = {**core.DEFAULT_INPUTS, "purchase_price_mln": 1000,
                "purchase_schedule": "30%@0; 40%@6; 30%@12",
                "offices_enabled": True, "retail_enabled": True,
                "above_parking_enabled": True,
                "offices_sales_profile": "60%@0; 40%@12",
                "retail_sales_profile": "70%@0; 30%@6",
                "above_parking_sales_profile": "80%@0; 20%@6",
                "growth_stage1_pct": 10, "offices_growth_stage1_pct": 8,
                "retail_growth_stage1_pct": 5, "above_parking_growth_stage1_pct": 4}


@pytest.fixture(scope="module")
def blocks():
    content, _, _ = core.build_project_workbook(
        BLOCK_INPUTS, core.TEP_DEFAULT, [], {}, project_name="Блоки")
    return v4_inputs.inputs(openpyxl.load_workbook(io.BytesIO(content), data_only=False))


def labels(sheet, column: str) -> set[str]:
    return {str(sheet[f"{column}{row}"].value or "")
            for row in range(1, sheet.max_row + 1)}


def test_the_schedule_blocks_say_which_input_they_are(blocks):
    """График, профиль и лестница лежали блоками без единого ключа: ячейки есть,
    а какая это вводная — не сказано (нашёл соседний писатель, 03.09.2026)."""
    named = labels(blocks, "D")
    for key in ("purchase_schedule", "offices_sales_profile",
                "retail_sales_profile", "above_parking_sales_profile"):
        assert key in named, key
    for prefix in ("", "offices_", "retail_", "above_parking_"):
        for stage in (1, 2, 3, 4):
            assert f"{prefix}growth_stage{stage}_pct" in named, (prefix, stage)


def test_a_schedule_carries_one_key_for_the_whole_block(blocks):
    """Вводная здесь ОДНА («30%@0; 40%@6»), а строк у неё столько, сколько
    шагов: ключ на каждой строке назвал бы шаг целой вводной."""
    row = next(number for number in range(1, blocks.max_row + 1)
               if str(blocks[f"A{number}"].value or "") == "ГРАФИК ПЛАТЕЖЕЙ ЗА ПОКУПКУ")
    assert blocks[f"D{row}"].value == "purchase_schedule"
    steps = [number for number in range(row, row + 8)
             if str(blocks[f"A{number}"].value or "").startswith("Шаг ")]
    assert len(steps) == 3, steps
    for step in steps:
        assert blocks[f"D{step}"].value == "доля", "шаг подписан ключом целой вводной"


def test_a_ladder_carries_a_key_on_every_stage(blocks):
    """У лестницы наоборот: каждый этап — своя вводная движка."""
    row = next(number for number in range(1, blocks.max_row + 1)
               if str(blocks[f"A{number}"].value or "").startswith("ЛЕСТНИЦА ЦЕНЫ · КВАРТИРЫ"))
    for index, stage in enumerate(range(row + 2, row + 6), 1):
        assert blocks[f"D{stage}"].value == f"growth_stage{index}_pct", stage


def test_an_empty_payment_date_stays_empty(blocks):
    """Жёлтая ячейка с формулой — ложное приглашение: впишешь число, как цвет и
    зовёт, и затрёшь формулу. Пустая дата остаётся пустой, а запасной путь
    живёт у читателя вместе с самой обрезкой по РнС."""
    content, _, _ = core.build_project_workbook(
        {**core.DEFAULT_INPUTS, "social_comp_date": ""},
        core.TEP_DEFAULT, [], {}, project_name="Пустая дата")
    sheet = v4_inputs.inputs(openpyxl.load_workbook(io.BytesIO(content), data_only=False))
    assert sheet["B18"].value in (None, ""), sheet["B18"].value

    cash = next(number for number in range(1, sheet.max_row + 1)
                if str(sheet[f"A{number}"].value or "").startswith("Денежная компенсация"))
    formula = str(sheet[f"D{cash}"].value or "")
    assert formula.startswith("=IF($B$18=") and "MIN($B$18" in formula, formula


def test_a_failed_engine_is_named_not_swallowed(monkeypatch):
    """Без контрольных чисел лист ПРОВЕРОК выглядит просто пустым, и «паритет не
    считался» неотличимо от «паритет сошёлся»."""
    def boom(*args, **kwargs):
        raise RuntimeError("движок упал")

    monkeypatch.setattr(core, "_run_authoritative_model", boom)
    _, _, meta = core.build_project_workbook(
        {**core.DEFAULT_INPUTS}, core.TEP_DEFAULT, [], {}, project_name="Без движка")
    assert any("контрольные числа движка" in item for item in meta["missing"]), meta["missing"]
