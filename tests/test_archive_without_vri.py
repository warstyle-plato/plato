"""Многоочередной проект без платы за смену ВРИ должен выгружаться.

Лист ВРИ необязателен: без платы его просто нет, и _model_sheet_vri возвращает
None. Одноочередная ветка это учитывала и отсеивала пустые листы, а сборка
консолидации — нет, и None уезжал прямо в _build_model_xlsx. Весь архив не
собирался с сообщением «'NoneType' object has no attribute 'get'».

Запуск: python3 -m pytest tests -q
"""

from __future__ import annotations

import io
import sys
import zipfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import main as wrapper  # noqa: E402

core = wrapper.core

PHASING = {
    "enabled": True, "phase_count": 3, "phase_gap_months": 12,
    "phases": [{"name": f"О{i+1}", "start_offset_months": i * 12,
                "construction_months": 24} for i in range(3)],
}


def archive(vri_required: bool) -> zipfile.ZipFile:
    inputs = dict(core.DEFAULT_INPUTS)
    inputs["vri_required"] = vri_required
    tep = {key: dict(value) for key, value in core.TEP_DEFAULT.items()}
    data, _ = core.build_model_archive(inputs, tep, [], dict(PHASING), project_name="Тест")
    return zipfile.ZipFile(io.BytesIO(data))


def test_phases_without_vri_still_produce_an_archive():
    names = archive(False).namelist()

    assert any(name.startswith("90_Детализация") for name in names), names
    assert any(name.startswith("00_Консолидатор") for name in names), names


def test_the_vri_sheet_is_simply_absent_without_the_payment():
    book = archive(False)
    detail = book.read("90_Детализация_консолидация.xlsx")
    sheets = zipfile.ZipFile(io.BytesIO(detail)).read("xl/workbook.xml").decode("utf-8")

    assert "ВРИ" not in sheets


def test_with_vri_the_sheet_is_there():
    book = archive(True)
    detail = book.read("90_Детализация_консолидация.xlsx")
    sheets = zipfile.ZipFile(io.BytesIO(detail)).read("xl/workbook.xml").decode("utf-8")

    assert "ВРИ" in sheets


def test_a_missing_sheet_names_itself_instead_of_a_nonetype():
    """«'NoneType' object has no attribute 'get'» не указывает ни на что."""
    with pytest.raises(ValueError) as failure:
        core._build_model_xlsx([{"name": "Свод", "rows": []}, None])

    assert "Лист №2" in str(failure.value)
