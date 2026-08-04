"""Приветствие продаёт ВРИ и живую модель; книга не носит чужие источники.

Реклама привела холодных пользователей, а приветствие молчало про два
сильнейших факта: расчёт платы за смену ВРИ с ТЭП по нормативам ГлавАПУ
и живую Excel-модель с формулами (в тексте был только PDF). Лист
«Источники» книги оставался шаблонным — кадастр 77:09 и московское
593-ПП даже у областных проектов. IRR очереди без собственного капитала
показывал вырожденный XIRR вместо честного «капитал не привлекался».

Запуск: python3 -m pytest tests -q
"""

from __future__ import annotations

import io
import sys
from pathlib import Path

import openpyxl

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import main as wrapper  # noqa: E402

core = wrapper.core


def test_the_welcome_mentions_vri_and_the_live_model():
    source = open("main_legacy.py", encoding="utf-8").read()
    start = source.find("Добро пожаловать в DevelopAid")
    block = source[start:start + 3000]
    assert "плату за изменение ВРИ" in block
    assert "нормативам ГлавАПУ" in block
    assert "живую Excel-модель" in block
    assert "показывайте банку" in block


def test_the_pdf_column_names_the_project_gns():
    source = open("main_legacy.py", encoding="utf-8").read()
    assert "тыс ₽/м² ГНС проекта" in source, \
        "без слова «проекта» удельные СМР читались как ставка на свой метр"


def test_the_sources_sheet_carries_the_project():
    inputs = dict(core.DEFAULT_INPUTS)
    inputs["vri_region"] = "mo"
    tep = {key: dict(value) for key, value in core.TEP_DEFAULT.items()}
    content, _, _ = core.build_project_workbook(
        inputs, tep, [], {}, project_name="Тестовый проект", finance_hints={})
    sheet = openpyxl.load_workbook(io.BytesIO(content), data_only=False)["Источники"]
    assert sheet["D6"].value == "Тестовый проект"
    assert "77-09" not in str(sheet["D6"].value)
    assert "Московская область" in str(sheet["C7"].value), \
        "областной проект не должен ссылаться на московское 593-ПП"
    assert core.VERSION in str(sheet["C16"].value)


def test_the_queue_irr_guards_zero_equity():
    template = openpyxl.load_workbook(core._V4_TEMPLATE_PATH, data_only=False)
    for sheet in ("CF_1", "CF_2", "CF_3", "CF_4"):
        formula = str(template[sheet]["B80"].value)
        assert "капитал не привлекался" in formula, \
            "XIRR на нулевом вкладе вырожден и читался как ошибка доходности"
    labels = template["Вводные"]
    assert "лимитом не является" in str(labels["A24"].value)
    assert "календарям очередей" in str(labels["A18"].value)
