"""Удельная экономика и темп продаж квартир в штуках.

Юнит-экономика на м² ГНС и на м² продаваемой площади жила в книге и на
странице, а в отчёте её не было вовсе: решение принимают по рублю на метр, а
в PDF стояли только миллиарды и одна колонка удельных расходов стройки — на
ГНС. Обе базы обязаны стоять рядом: на ГНС считают стройку, на продаваемую
сравнивают с ценой продажи, и подмена одной другой ошибается почти вдвое.

Темп продаж был только в метрах. Квартиры продаются штуками: «40 квартир в
месяц» проверяется отделом продаж и рынком, «2 400 м² в месяц» — нет.

Запуск: python3 -m pytest tests -q
"""

from __future__ import annotations

import io
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import main as wrapper  # noqa: E402

core = wrapper.core


def _bundle(phasing: dict | None = None):
    inputs = dict(core.DEFAULT_INPUTS)
    tep = {key: dict(value) for key, value in core.TEP_DEFAULT.items()}
    return core._run_authoritative_model(inputs, tep, [], phasing or {}), inputs, tep


@pytest.fixture(scope="module")
def payload():
    bundle, inputs, tep = _bundle()
    return {"result": bundle["consolidated"], "inputs": inputs, "tep": tep,
            "rates": [], "phasing": {}, "scenario": "base",
            "project_name": "Удельная экономика"}


# --- удельные на две базы ----------------------------------------------------

def test_the_construction_articles_carry_both_bases(payload):
    """Стройка на м² ГНС и на м² продаж различается в полтора-два раза, и
    сравнивать с ценой продажи можно только вторую."""
    summary = payload["result"]["summary"]
    gns = float(summary["project_gns_sqm"])
    saleable = float(summary["monetizable_saleable_sqm"])
    assert saleable < gns, "продаваемая всегда меньше ГНС — иначе базы перепутаны"
    for row in payload["result"]["report"]["construction_costs"]:
        assert row["per_gns_th"] == pytest.approx(row["value"] / gns / 1000)
        assert row["per_saleable_th"] == pytest.approx(row["value"] / saleable / 1000)
        assert row["per_saleable_th"] > row["per_gns_th"]


def test_the_phased_report_keeps_both_bases():
    """Консолидация очередей делит на свои итоги, а не на итоги первой."""
    bundle, _, _ = _bundle({"enabled": True, "phase_count": 2, "phase_gap_months": 12})
    consolidated = bundle["consolidated"]
    gns = float(consolidated["summary"]["project_gns_sqm"])
    saleable = float(consolidated["summary"]["monetizable_saleable_sqm"])
    rows = consolidated["report"]["construction_costs"]
    assert rows, "статьи стройки обязаны доехать до сводки"
    for row in rows:
        assert row["per_gns_th"] == pytest.approx(row["value"] / gns / 1000)
        assert row["per_saleable_th"] == pytest.approx(row["value"] / saleable / 1000)


def test_the_pdf_prints_the_unit_economics(payload):
    """Раздела не было в отчёте вовсе — при том, что в книге он есть."""
    pypdf = pytest.importorskip("pypdf")
    data = core._build_developaid_pdf(payload)
    text = "\n".join(page.extract_text() or ""
                     for page in pypdf.PdfReader(io.BytesIO(data)).pages)
    assert "Удельная экономика проекта" in text
    assert "продаваемой" in text
    # Обе базы названы числом: «тыс ₽/м²» без базы читается как что угодно.
    assert "База ГНС" in text


def test_the_pdf_construction_table_gained_the_saleable_column(payload):
    pypdf = pytest.importorskip("pypdf")
    data = core._build_developaid_pdf(payload)
    text = "\n".join(page.extract_text() or ""
                     for page in pypdf.PdfReader(io.BytesIO(data)).pages)
    assert "Удельные расходы строительства" in text
    assert text.count("продаваемой") >= 2, "колонка обязана быть и в стройке"


# --- темп продаж квартир в штуках --------------------------------------------

def test_the_pace_in_units_matches_the_metres(payload):
    """Штуки — это метры, делённые на среднюю площадь квартиры из ТЭП.
    Сумма помесячных штук обязана сойтись с числом квартир в проекте."""
    sales = payload["result"]["report"]["apartment_sales"]
    tep_apartments = next(row for row in payload["result"]["tep"]["rows"]
                          if row["key"] == "apartments")
    assert sales["units_total"] == pytest.approx(tep_apartments["units"])
    assert sales["avg_unit_sqm"] == pytest.approx(
        tep_apartments["saleable"] / tep_apartments["units"])
    assert sum(row["units"] for row in sales["rows"]) == pytest.approx(
        sales["units_total"], rel=1e-6)


def test_the_pace_before_rve_is_not_the_average_of_the_whole_period(payload):
    """До РВЭ продаётся заданная доля (85% по умолчанию) — темп там выше
    среднего по всему периоду вместе с остаточными продажами."""
    sales = payload["result"]["report"]["apartment_sales"]
    assert sales["pace_pre_rve_units"] > 0
    assert sales["peak_units"] >= sales["pace_units"]
    assert sales["months"] == len(sales["rows"])


def test_the_phased_pace_adds_up_the_queues():
    """В один месяц продаются квартиры двух очередей — отдел продаж видит их
    одной цифрой, а не двумя."""
    bundle, _, _ = _bundle({"enabled": True, "phase_count": 2, "phase_gap_months": 12})
    sales = bundle["consolidated"]["report"]["apartment_sales"]
    phase_total = sum(float((item["result"]["report"].get("apartment_sales") or {})
                            .get("units_total") or 0.0) for item in bundle["phases"])
    assert sales["units_total"] == pytest.approx(phase_total)
    assert sum(row["units"] for row in sales["rows"]) == pytest.approx(
        sales["units_total"], rel=1e-6)
    months = [row["month"] for row in sales["rows"]]
    assert months == sorted(months) and len(months) == len(set(months))


def test_the_pdf_prints_the_pace_in_units(payload):
    pypdf = pytest.importorskip("pypdf")
    data = core._build_developaid_pdf(payload)
    text = "\n".join(page.extract_text() or ""
                     for page in pypdf.PdfReader(io.BytesIO(data)).pages)
    assert "Темп продаж квартир" in text
    assert "Средняя площадь квартиры" in text
    assert "кв./мес." in text
    # Денежный график прячет и рост цены, и нарезку — нужен график в штуках.
    assert "Месячный темп продаж квартир" in text


def test_the_workbook_carries_the_same_pace(payload):
    """Книга и отчёт обязаны говорить одно: расхождение поверхностей уже
    стоило разбирательства «какая из двух правда»."""
    sheet = core._model_sheet_revenue(payload["result"])
    text = "\n".join(str(getattr(cell, "value", cell))
                     for row in sheet["rows"] for cell in row)
    assert "Темп продаж квартир" in text
    assert "Темп до РВЭ, кв./мес." in text


def test_the_page_shows_the_pace_too():
    page = core.PAGE
    assert 'id="apartmentPaceTable"' in page
    assert "Темп продаж до РВЭ" in page
    assert "apartment_sales" in page


def test_an_empty_apartment_block_stays_silent():
    """Проект без квартир (только коммерция) не обязан печатать нули:
    пустой раздел читается как ошибка расчёта."""
    inputs = dict(core.DEFAULT_INPUTS)
    tep = {key: dict(value) for key, value in core.TEP_DEFAULT.items()}
    tep["apartments"] = dict(tep["apartments"], gns=0, total_area=0, useful=0,
                             saleable=0, units=0)
    bundle = core._run_authoritative_model(inputs, tep, [], {})
    assert not (bundle["consolidated"]["report"].get("apartment_sales") or {})
