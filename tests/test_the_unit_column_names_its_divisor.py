"""Колонка «на метр» названа той базой, на которую число и делится.

В отчёте по КРТ на ул. Архитектора Власова колонка удельных стояла с подписью
«тыс ₽/м² строит. объёма», а числа в ней делились на НАЗЕМНУЮ ГНС
(`project_gns_sqm`): на умолчаниях это 145 381 м² против 187 346 м²
строительного объёма — разница в 22%. Числа были верные, врал заголовок, и
сравнить показатель с чужой сметой «на метр» по нему было нельзя.

Держать подпись строкой мало: три прежние проверки её и закрепляли — одна из
них прямо утверждала «база удельных — весь строительный объём». Поэтому здесь
сравнивается ПЕЧАТНОЕ число с делением на каждую из двух баз: подпись верна
ровно тогда, когда совпадает с той, что названа.

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


def test_unit_economics_divide_by_the_above_ground_gns(bundle, summary):
    gns = float(summary["project_gns_sqm"])
    volume = float(summary["construction_volume_sqm"])
    report = bundle["consolidated"]["report"]
    for item in report["unit_economics"]:
        total = float(item.get("total") or 0.0)
        if abs(total) < 1.0:
            continue
        assert item["per_gns_th"] == pytest.approx(total / gns / 1000, rel=1e-9), item["label"]
        assert item["per_gns_th"] != pytest.approx(total / volume / 1000, rel=1e-6), item["label"]
    for item in report["construction_costs"]:
        value = float(item.get("value") or 0.0)
        if value < 1.0:
            continue
        assert item["per_gns_th"] == pytest.approx(value / gns / 1000, rel=1e-9), item["label"]


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

    assert "тыс ₽/м² наземной ГНС" in flat
    # Запрещается МЕСТО, а не слово: в предпосылках отчёта стоит «тыс. ₽/м²
    # строит. объёма» у ставки наружных сетей, и это правда — её умножают на
    # весь объём. Запрет держит колонки, у которых делитель наземный.
    assert "тыс ₽/м² строит. объёма" not in flat
    assert "тыс ₽/м² строительного объёма" not in flat
    assert "на м² строит. объёма" not in flat

    gns = float(summary["project_gns_sqm"])
    volume = float(summary["construction_volume_sqm"])
    revenue = float(bundle["consolidated"]["summary"]["revenue"])
    printed = core._pdf_num(revenue / gns / 1000, 1)
    other = core._pdf_num(revenue / volume / 1000, 1)
    assert printed != other, (printed, other)
    assert printed in flat, ("в колонке стоит не то число, что названо базой",
                             printed, other)


def test_the_page_columns_name_the_same_base():
    """Три таблицы отчёта на странице делят на `r.summary.project_gns_sqm` —
    ту же наземную ГНС, что и PDF."""
    page = core.PAGE
    assert page.count("<th>тыс ₽/м² наземной ГНС</th>") == 3
    assert "тыс ₽/м² строит. объёма" not in page
    for anchor in ("Структура расходов", "Структура затрат по статьям",
                   "Структура выручки"):
        head = page[page.find(anchor):][:600]
        assert "тыс ₽/м² наземной ГНС" in head, anchor
    # Делитель на странице тот же, что в движке: если он сменится на
    # строительный объём, подпись обязана уехать вместе с ним.
    assert "construction_volume_sqm" not in re.sub(
        r"\s+", "", page[page.find("revenueTable.innerHTML") - 400:
                         page.find("capexTable.innerHTML") + 400])


def test_the_construction_cost_names_the_core_volume():
    """`construction_cost_per_gns_th` делится на `core_gns` — строительный
    объём МКД (наземная плюс подземная части ядра), а не на наземную ГНС и не
    на объём всего проекта. Обе прежние подписи называли чужую базу."""
    source = open("main_legacy.py", encoding="utf-8").read()
    assert '("construction_cost_per_gns_th", "Строительство, тыс. ₽/м² строит. объёма МКД", "num"),' in source
    line = next(l for l in source.splitlines()
                if "construction_cost_per_saleable_th)+'/м² прод." in l)
    assert "строит. объёма МКД" in line and "/м² ГНС" not in line, line.strip()[:160]
