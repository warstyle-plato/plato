"""Единая книга проекта: DevelopAid v4, заполненная текущими вводными.

На сайте жили две выгрузки — ZIP с детализацией значениями и ZIP с шаблоном
ПЛАТО, — и рядом они читались как разные модели одного проекта. Теперь кнопка
одна и отдаёт книгу v4: весь расчёт — живые формулы, сюда пишутся только
значения листа «Вводные». Книга несёт диаграммы, которые openpyxl при
перезаписи теряет, поэтому значения правятся прямо в XML внутри zip.

Запуск: python3 -m pytest tests -q
"""

from __future__ import annotations

import io
import sys
import zipfile
from datetime import datetime
from pathlib import Path

import openpyxl
import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import main as wrapper  # noqa: E402

core = wrapper.core
client = TestClient(wrapper.app)


def build(inputs=None, tep=None, phasing=None, name="Тест"):
    x = {**core.DEFAULT_INPUTS, **(inputs or {})}
    t = {k: dict(v) for k, v in core.TEP_DEFAULT.items()}
    for key, row in (tep or {}).items():
        t.setdefault(key, {}).update(row)
    return core.build_project_workbook(x, t, [], phasing or {}, project_name=name)


@pytest.fixture(scope="module")
def default_book():
    content, filename, meta = build()
    sheet = openpyxl.load_workbook(io.BytesIO(content), data_only=False)["Вводные"]
    return content, filename, meta, sheet


# --- сборка ----------------------------------------------------------------

def test_every_input_finds_its_cell(default_book):
    """Поле без соответствия — потерянные данные, а не мелочь."""
    _, _, meta, _ = default_book
    assert meta["missing"] == []


def test_the_charts_survive_the_fill(default_book):
    """Ради диаграмм книга и правится в XML, а не через openpyxl."""
    content, _, _, _ = default_book
    names = zipfile.ZipFile(io.BytesIO(content)).namelist()
    assert any("charts/chart" in name for name in names), "диаграммы потеряны"


def test_the_filename_is_a_single_xlsx_not_an_archive(default_book):
    _, filename, _, _ = default_book
    assert filename.endswith(".xlsx")


# --- значения --------------------------------------------------------------

def test_percent_points_become_fractions(default_book):
    """Движок хранит 25, книга ждёт 0,25 — иначе налог посчитается в 2500%."""
    _, _, _, sheet = default_book
    assert sheet["B21"].value == pytest.approx(0.25)   # налог на прибыль
    assert sheet["B63"].value == pytest.approx(0.85)   # доля продаж до РВЭ
    assert sheet["B25"].value == pytest.approx(0.06)   # спред БРИДЖ
    assert sheet["B33"].value == pytest.approx(0.14)   # ключевая на старте


def test_the_tep_lands_in_the_first_queue(default_book):
    _, _, _, sheet = default_book
    assert sheet["B88"].value == "Да"
    assert sheet["B89"].value == "Нет"
    assert sheet["W88"].value == pytest.approx(core.TEP_DEFAULT["apartments"]["gns"], rel=1e-6)
    assert sheet["Z88"].value == pytest.approx(core.TEP_DEFAULT["apartments"]["saleable"], rel=1e-6)
    assert sheet["AB88"].value == pytest.approx(
        core.TEP_DEFAULT["underground_parking"]["units"], rel=1e-6)


def test_the_project_start_drives_the_horizon(default_book):
    _, _, _, sheet = default_book
    assert sheet["B8"].value == datetime(2027, 1, 1)
    assert sheet["D88"].value == datetime(2027, 1, 1)


def test_the_formulas_of_the_book_are_not_overwritten(default_book):
    """Пишутся только значения: срок продаж и целевая ставка остаются формулами."""
    _, _, _, sheet = default_book
    assert str(sheet["H88"].value).startswith("=")
    assert str(sheet["B34"].value).startswith("=")


def test_the_bridge_limit_is_computed_not_hardcoded(default_book):
    """Фиксированный лимит 3 500 млн резал выборку БРИДЖ на крупном проекте."""
    _, _, _, sheet = default_book
    formula = str(sheet["B24"].value)
    assert formula.startswith("=")
    assert "CAPEX" in formula


def test_the_density_factor_is_one_at_export(default_book):
    """Базовый потенциал равен применяемому: ТЭП уезжает ровно как в проекте."""
    _, _, _, sheet = default_book
    assert sheet["K8"].value == "Нет"
    assert sheet["K11"].value == pytest.approx(30000)


def test_the_vri_switch_follows_the_payment_not_the_flag():
    """Выключатель ВРИ — нулевая плата: заданная сумма платится всегда."""
    _, _, _, sheet = _book({"vri_required": False, "land_rights_cost_mln": 500})
    assert sheet["B74"].value == "Да"
    _, _, _, sheet = _book({"vri_required": True, "land_rights_cost_mln": 0})
    assert sheet["B74"].value == "Нет"


def _book(inputs):
    content, filename, meta = build(inputs)
    return content, filename, meta, openpyxl.load_workbook(
        io.BytesIO(content), data_only=False)["Вводные"]


def test_an_installment_is_written_in_the_words_of_the_book():
    _, _, _, sheet = _book({"vri_payment_mode": "installment", "vri_installment_years": 3})
    assert sheet["B75"].value == "3 года"


def test_the_office_block_carries_dates_and_terms():
    _, _, _, sheet = _book({"offices_enabled": True, "offices_gba_sqm": 21700,
                            "offices_months": 24, "offices_residual_months": 6})
    assert sheet["K20"].value == "Да"
    assert sheet["K23"].value == pytest.approx(21700)
    assert sheet["K33"].value == pytest.approx(30)
    assert sheet["K27"].value == datetime(2028, 7, 1)


# --- очереди ---------------------------------------------------------------

def test_the_phases_split_the_tep_by_their_weights():
    phasing = {
        "enabled": True, "phase_count": 2,
        "phases": [{"start_offset_months": 0, "construction_months": 24},
                   {"start_offset_months": 12, "construction_months": 30}],
        "products": {"apartments": [0.6, 0.4], "ground_commercial": [0.5, 0.5],
                     "underground_parking": [0.7, 0.3], "storage": [1, 0]},
        "shared_allocation": {"purchase": [1, 0], "land_rights": [0.5, 0.5],
                              "social_compensation": [0, 1]},
        "cost_inflation_pct": 8, "sales_price_inflation_pct": 8,
    }
    content, _, meta = build(phasing=phasing)
    sheet = openpyxl.load_workbook(io.BytesIO(content), data_only=False)["Вводные"]
    total = core.TEP_DEFAULT["apartments"]["gns"]
    assert meta["phased"] is True
    assert sheet["B88"].value == "Да" and sheet["B89"].value == "Да"
    assert sheet["B90"].value == "Нет"
    assert sheet["W88"].value == pytest.approx(total * 0.6, rel=1e-6)
    assert sheet["W89"].value == pytest.approx(total * 0.4, rel=1e-6)
    assert sheet["D89"].value == datetime(2028, 1, 1)
    assert sheet["F89"].value == pytest.approx(30)
    assert sheet["Q89"].value == pytest.approx(0.5)
    assert sheet["AE89"].value == pytest.approx(0.08)


# --- поверхности -----------------------------------------------------------

def test_the_endpoint_returns_a_single_workbook():
    response = client.post("/report/workbook", json={
        "inputs": dict(core.DEFAULT_INPUTS),
        "tep": {k: dict(v) for k, v in core.TEP_DEFAULT.items()},
        "rates": [], "phasing": {}, "project_name": "Ручной", "scenario": "base",
    })
    assert response.status_code == 200
    assert response.headers["content-type"].startswith(
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    assert response.content[:2] == b"PK"


def test_the_page_offers_one_model_download():
    """Зачем и шаблон, и зип? Кнопка одна, и она отдаёт книгу v4."""
    assert "Скачать модель (Excel)" in core.PAGE
    assert "/report/workbook" in core.PAGE
    assert "Выгрузить в шаблон ПЛАТО" not in core.PAGE
    assert "exportPlatoTemplate" not in core.PAGE


def test_the_bot_attachment_is_the_same_workbook():
    """Бот и сайт отдают одну книгу, а не каждый свою."""
    import inspect
    source = inspect.getsource(core._telegram_send_attachments)
    assert "build_project_workbook" in source
    assert "build_model_archive" not in source
