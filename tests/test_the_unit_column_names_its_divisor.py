"""Колонка «на метр» названа той базой, на которую число и делится.

В отчёте по КРТ на ул. Архитектора Власова колонка удельных стояла с подписью
«тыс ₽/м² строит. объёма», а числа в ней делились на НАЗЕМНУЮ ГНС
(`project_gns_sqm`): на умолчаниях это 145 381 м² против 187 346 м²
строительного объёма — разница в 22%. Числа были верные, врал заголовок, и
сравнить показатель с чужой сметой «на метр» по нему было нельзя.

Держать подпись строкой мало: три прежние проверки её и закрепляли — одна из
них прямо утверждала «база удельных — весь строительный объём». Поэтому здесь
сравнивается ПЕЧАТНОЕ число с делением на каждую из двух баз: подпись верна
ровно тогда, когда совпадает с той, что названа. С 29.09.2026 у каждой
строки своя база (решение 4 ревизии книги), и проверка сверяет число с ней.

Запуск: python3 -m pytest tests -q
"""

from __future__ import annotations

import io
import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import main as wrapper  # noqa: E402

core = wrapper.core
from terms_glossary import TOTAL_AREA  # noqa: E402


@pytest.fixture(scope="module")
def bundle():
    inputs = dict(core.DEFAULT_INPUTS)
    tep = {key: dict(value) for key, value in core.TEP_DEFAULT.items()}
    return core._run_authoritative_model(inputs, tep, [], {})


@pytest.fixture(scope="module")
def summary(bundle):
    return bundle["consolidated"]["summary"]


def test_the_two_bases_differ(summary):
    """Предохранитель: без подземной части обе базы совпадают, и проверка
    ниже зеленеет при любой подписи."""
    gns = float(summary["project_gns_sqm"])
    volume = float(summary["construction_volume_sqm"])
    assert gns > 0 and volume > gns * 1.05, (gns, volume)


def test_unit_economics_divide_by_the_base_they_name(bundle, summary):
    """С 29.09.2026 (решение 4 ревизии книги) у строки своя база, и она
    названа в строке: число обязано делиться ровно на неё, а не на соседнюю."""
    bases = summary["unit_bases"]
    report = bundle["consolidated"]["report"]
    for item in report["unit_economics"] + report["construction_costs"]:
        total = float(item.get("total", item.get("value")) or 0.0)
        if abs(total) < 1.0:
            continue
        assert item["per_base_th"] == pytest.approx(total / bases[item["base"]] / 1000,
                                                    rel=1e-9), item["label"]
        for other, area in bases.items():
            if other != item["base"] and abs(area - bases[item["base"]]) > 1:
                assert item["per_base_th"] != pytest.approx(total / area / 1000, rel=1e-6), \
                    (item["label"], other)


def test_the_pdf_column_carries_the_base_it_divides_by(bundle, summary):
    """Печатное число сверяется с обеими базами: подпись верна ровно тогда,
    когда совпало деление на названную."""
    pypdf = pytest.importorskip("pypdf")
    payload = {
        "result": bundle["consolidated"],
        "inputs": dict(core.DEFAULT_INPUTS),
        "tep": {key: dict(value) for key, value in core.TEP_DEFAULT.items()},
        "rates": [], "phasing": {}, "scenario": "base",
        "project_name": "Подпись удельных",
    }
    data = core._build_developaid_pdf(payload)
    reader = pypdf.PdfReader(io.BytesIO(data))
    flat = " ".join(
        " ".join((page.extract_text() or "").split()) for page in reader.pages)

    assert f"м² {TOTAL_AREA.genitive}" in flat
    assert "тыс ₽/м² наземной ГНС" not in flat, "прежняя общая база вернулась"
    assert "тыс ₽/м² строит. объёма" not in flat
    assert "тыс ₽/м² строительного объёма" not in flat

    gns = float(summary["project_gns_sqm"])
    volume = float(summary["construction_volume_sqm"])
    capex = float(summary["capex"])
    printed = core._pdf_num(capex / volume / 1000, 1)
    other = core._pdf_num(capex / gns / 1000, 1)
    assert printed != other, (printed, other)
    assert printed in flat, ("в колонке стоит не то число, что названо базой",
                             printed, other)


def test_the_page_columns_name_the_same_base():
    """Таблицы отчёта на странице печатают удельные движка и называют базу:
    своей колонкой (удельная экономика, статьи CAPEX) или шапкой, у которой
    база одна на все строки (структура расходов, структура выручки)."""
    page = core.PAGE
    assert "<th>тыс ₽/м² наземной ГНС</th>" not in page
    assert "тыс ₽/м² строит. объёма" not in page
    for anchor in ("Удельная экономика", "Структура затрат по статьям"):
        head = page[page.find(anchor):][:900]
        assert "своей базы" in head and "<th>База</th>" in head, anchor
    assert "<th>тыс ₽/м² продаваемой площади</th>" in page[page.find("Структура выручки"):][:600]
    # Делить на странице больше нечего: удельные приходят из движка.
    block = re.sub(r"\s+", "", page[page.find("revenueTable.innerHTML") - 400:
                                    page.find("capexTable.innerHTML") + 600])
    assert "/1000" not in block, "страница снова делит сама"


def test_the_construction_cost_names_the_core_volume():
    """`construction_cost_per_gns_th` делится на `core_gns` — строительный
    объём МКД (наземная плюс подземная части ядра), а не на наземную ГНС и не
    на объём всего проекта. Обе прежние подписи называли чужую базу."""
    source = open("main_legacy.py", encoding="utf-8").read()
    assert ('("construction_cost_per_gns_th", '
            'f"Строительство, тыс. ₽/м² {CORE_TOTAL_AREA.genitive}", "num"),') in source
    line = next(l for l in source.splitlines()
                if "construction_cost_per_saleable_th)+'/м² прод." in l)
    assert "'/м² '+TERMS.core_total_area.genitive" in line and "/м² ГНС" not in line, line.strip()[:160]
