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
    # База названа целиком: без неё 23 тыс ₽/м² подземной части читались как
    # ставка на подземный метр (она — 190, во вводных). Названа она ровно тем,
    # чем число делится: `per_gns_th` считается на `project_gns_sqm`, а это
    # НАЗЕМНАЯ площадь. Прежде тут стояло «строительного объёма» — подпись,
    # которую эта же проверка и держала.
    assert "тыс ₽/м² наземной ГНС" in source, \
        "без названия базы удельные СМР читаются как ставка на свой метр"
    # Запрещается МЕСТО, а не слово: «тыс ₽/м² строит. объёма» — верная подпись
    # у ставок вводных, которые правда умножаются на весь объём.
    for line in source.splitlines():
        if '"Показатель", "Всего"' in line or '"Статья", "млн ₽"' in line \
                or 'expense_rows=[["Статья"' in line:
            assert "строит. объёма" not in line and "строительного объёма" not in line, (
                "колонка названа базой, которой не делится: " + line.strip()[:120])


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
