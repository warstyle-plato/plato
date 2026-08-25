"""Ставка, ушедшая от базы класса, называется вслух в каждой поверхности.

База классов одна и общая (решение владельца, 24.08.2026). Проект, ушедший от
неё — правкой руками или личной перекрышкой, — обязан говорить об этом сам:
молча книга и отчёт «одного класса» разойдутся, и оба будут выглядеть
достоверно. Список полей класса читается из самого пресета — поле, добавленное
в пресет позже (например, благоустройство), попадает в сверку без правок здесь.

Запуск: python3 -m pytest tests -q
"""

from __future__ import annotations

import io
import re
import sys
import zipfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import main as wrapper  # noqa: E402

core = wrapper.core
openpyxl = pytest.importorskip("openpyxl")

PLATO_TEMPLATE = Path(__file__).resolve().parent.parent / "templates" / "PLATO_template.xlsx"
V4_TEMPLATE = Path(__file__).resolve().parent.parent / "templates" / "DevelopAid_model_v4.xlsx"


def test_deviation_rows_compare_inputs_to_the_class_base():
    inputs = dict(core.DEFAULT_INPUTS)
    inputs.update(project_class="business", main_above_th_per_sqm=210,
                  apartment_price_th=650, commercial_price_th=650,
                  parking_price_th=5000, main_under_th_per_sqm=190)
    result = core.project_class_deviations(inputs)
    assert result["label"] == "Бизнес"
    assert [row["field"] for row in result["rows"]] == ["main_above_th_per_sqm"]
    row = result["rows"][0]
    assert row["base"] == 190 and row["actual"] == 210
    # Подпись — из FIELD_GROUPS, единственного объявления списка полей.
    assert "наземная часть" in row["label"]


def test_exact_base_and_custom_class_produce_no_rows():
    inputs = dict(core.DEFAULT_INPUTS)
    inputs.update(project_class="business", apartment_price_th=650,
                  commercial_price_th=650, parking_price_th=5000,
                  main_above_th_per_sqm=190, main_under_th_per_sqm=190)
    assert core.project_class_deviations(inputs)["rows"] == []
    inputs["project_class"] = "custom"
    custom = core.project_class_deviations(inputs)
    assert custom["rows"] == [] and custom["label"] == "Пользовательский"


@pytest.mark.skipif(not PLATO_TEMPLATE.is_file(), reason="шаблон ПЛАТО не поставляется")
def test_plato_marks_deviated_rate_in_column_h():
    inputs = dict(core.DEFAULT_INPUTS)
    inputs.update(project_class="business", apartment_price_th=700,
                  commercial_price_th=650, parking_price_th=5000,
                  main_above_th_per_sqm=210, main_under_th_per_sqm=190)
    data, report = core.fill_plato_template(inputs, core.TEP_DEFAULT, project_name="Проверка")
    sheet = openpyxl.load_workbook(io.BytesIO(data))["Вводные"]
    notes = {}
    for row in range(1, sheet.max_row + 1):
        note = sheet.cell(row=row, column=8).value
        if note:
            notes[str(sheet.cell(row=row, column=2).value or "").strip()] = str(note)
    assert any("Основное строительство" in label for label in notes), notes
    smr_note = next(v for k, v in notes.items() if "Основное строительство" in k)
    assert "база класса" in smr_note and "Бизнес" in smr_note and "190" in smr_note
    fields = {row["field"] for row in report["class_deviations"]["rows"]}
    assert fields == {"apartment_price_th", "main_above_th_per_sqm"}
    # Колонка G — переключатель сценария, отметка её не трогает: проверяем,
    # что в помеченной строке G осталась формулой или прежним значением, а не
    # текстом отметки.
    for row in range(1, sheet.max_row + 1):
        if sheet.cell(row=row, column=8).value:
            g = sheet.cell(row=row, column=7).value
            assert not (isinstance(g, str) and "база класса" in g)


@pytest.mark.skipif(not V4_TEMPLATE.is_file(), reason="шаблон v4 не поставляется")
def test_v4_marks_deviated_rate_next_to_the_value():
    inputs = dict(core.DEFAULT_INPUTS)
    inputs.update(project_class="business", apartment_price_th=650,
                  commercial_price_th=650, parking_price_th=5000,
                  main_above_th_per_sqm=210, main_under_th_per_sqm=190)
    content, _name, meta = core.build_project_workbook(
        inputs, core.TEP_DEFAULT, [], {}, project_name="Проверка")
    assert [row["field"] for row in meta["class_deviations"]["rows"]] == [
        "main_above_th_per_sqm"]
    sheet = openpyxl.load_workbook(io.BytesIO(content))["Вводные"]
    coord = core._V4_INPUT_CELLS["main_above_th_per_sqm"]
    row = int(re.sub(r"[A-Z]+", "", coord))
    note = str(sheet.cell(row=row, column=5).value or "")
    assert "база класса" in note and "Бизнес" in note and "190" in note
    # Ставка без отклонения примечания не несёт.
    under_row = int(re.sub(r"[A-Z]+", "", core._V4_INPUT_CELLS["main_under_th_per_sqm"]))
    assert not sheet.cell(row=under_row, column=5).value


@pytest.mark.skipif(not V4_TEMPLATE.is_file(), reason="шаблон v4 не поставляется")
def test_v4_note_insertion_keeps_workbook_openable():
    inputs = dict(core.DEFAULT_INPUTS)
    inputs.update(project_class="elite", apartment_price_th=1600,
                  commercial_price_th=1500, parking_price_th=20000,
                  main_above_th_per_sqm=320, main_under_th_per_sqm=300)
    content, _name, meta = core.build_project_workbook(
        inputs, core.TEP_DEFAULT, [], {}, project_name="Проверка")
    assert not [m for m in meta["missing"] if "примечание о классе" in str(m)]
    # openpyxl падает на ячейках, вставленных не по порядку колонок, —
    # само открытие книги и есть проверка вставки.
    with zipfile.ZipFile(io.BytesIO(content)):
        pass
    openpyxl.load_workbook(io.BytesIO(content)).close()


def test_pdf_names_the_class_and_its_deviations():
    import inspect
    source = inspect.getsource(core._build_developaid_pdf)
    assert "project_class_deviations" in source
    assert "Ставки отличаются от базы класса" in source
    assert "Класс проекта" in source


def test_pdf_still_builds_with_a_deviated_class():
    pytest.importorskip("reportlab")
    inputs = dict(core.DEFAULT_INPUTS)
    inputs.update(project_class="business", apartment_price_th=700,
                  commercial_price_th=650, parking_price_th=5000,
                  main_above_th_per_sqm=210, main_under_th_per_sqm=190,
                  purchase_price_mln=700)
    bundle = core._run_authoritative_model(inputs, core.TEP_DEFAULT, [], {})
    data = core._build_developaid_pdf({
        "result": bundle["consolidated"], "inputs": inputs,
        "tep": core.TEP_DEFAULT, "rates": [], "phasing": {},
        "scenario": "base", "project_name": "Проверка"})
    assert data[:4] == b"%PDF"
