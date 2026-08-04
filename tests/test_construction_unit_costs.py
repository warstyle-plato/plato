"""Удельные расходы строительства: движок отдаёт статьи, PDF их печатает.

PDF с сайта был беднее ботовского при тех же вводных: без торнадо (страница
шлёт чувствительность, только если её считали в окне, а дообогащал отчёт
только бот) и без удельной экономики стройки — статьи СМР, сетей и
благоустройства жили только внутри группы «Основное строительство». Теперь
движок отдаёт report.construction_costs (млн ₽ и тыс ₽/м² ГНС), PDF печатает
раздел на первой странице, а /report/pdf досчитывает чувствительность сам.

Запуск: python3 -m pytest tests -q
"""

from __future__ import annotations

import io
import re
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import main as wrapper  # noqa: E402

core = wrapper.core


def _payload():
    inputs = dict(core.DEFAULT_INPUTS)
    tep = {key: dict(value) for key, value in core.TEP_DEFAULT.items()}
    bundle = core._run_authoritative_model(inputs, tep, [], {})
    return {"result": bundle["consolidated"], "inputs": inputs, "tep": tep,
            "rates": [], "phasing": {}, "scenario": "base",
            "project_name": "Удельные расходы"}


@pytest.fixture(scope="module")
def payload():
    return _payload()


def test_the_engine_reports_construction_articles(payload):
    """Статьи стройки в отчётном блоке: суммы положительны, удельные — это
    статья, делённая на ГНС проекта, а не на площадь её части."""
    report = payload["result"]["report"]
    rows = report.get("construction_costs") or []
    labels = [row["label"] for row in rows]
    assert "СМР наземной части" in labels
    assert "Наружные инженерные сети" in labels
    assert "Благоустройство" in labels
    gns = float(payload["result"]["summary"]["project_gns_sqm"])
    for row in rows:
        assert row["value"] > 0
        assert row["per_gns_th"] == pytest.approx(row["value"] / gns / 1000)


def test_the_phased_report_sums_articles_over_queues():
    """Консолидация очередей складывает статьи, не пересортировывая смету."""
    inputs = dict(core.DEFAULT_INPUTS)
    tep = {key: dict(value) for key, value in core.TEP_DEFAULT.items()}
    phasing = {"enabled": True, "phase_count": 2, "phase_gap_months": 12}
    bundle = core._run_authoritative_model(inputs, tep, [], phasing)
    consolidated = bundle["consolidated"]["report"]["construction_costs"]
    by_label: dict[str, float] = {}
    for item in bundle["phases"]:
        for row in item["result"]["report"]["construction_costs"]:
            by_label[row["label"]] = by_label.get(row["label"], 0.0) + row["value"]
    assert [row["label"] for row in consolidated] == list(by_label)
    for row in consolidated:
        assert row["value"] == pytest.approx(by_label[row["label"]])


def test_the_pdf_prints_the_section(payload):
    pypdf = pytest.importorskip("pypdf")
    data = core._build_developaid_pdf(payload)
    text = "\n".join(page.extract_text() or ""
                     for page in pypdf.PdfReader(io.BytesIO(data)).pages)
    assert "Удельные расходы строительства" in text
    assert "СМР наземной части" in text
    assert "Итого строительство" in text
    assert "Внутренние инженерные" in text


def test_the_site_pdf_gets_the_tornado(payload, monkeypatch):
    """/report/pdf досчитывает чувствительность, когда страница её не
    прислала: раньше торнадо был только в PDF из бота."""
    calls = {}
    original = core.run_sensitivity

    def fake_sensitivity(inputs, tep, rates, phasing):
        calls["ran"] = True
        return original(inputs, tep, rates, phasing,
                        parameters=["apartment_price_th"])

    monkeypatch.setattr(core, "run_sensitivity", fake_sensitivity)
    client = TestClient(core.app)
    response = client.post("/report/pdf", json={k: v for k, v in payload.items()
                                                if k != "sensitivity"})
    assert response.status_code == 200
    assert calls.get("ran"), "эндпоинт обязан сам запустить чувствительность"
    pypdf = pytest.importorskip("pypdf")
    text = "\n".join(page.extract_text() or ""
                     for page in pypdf.PdfReader(io.BytesIO(response.content)).pages)
    assert "Чувствительность проекта" in text


def test_the_book_verdict_speaks_russian():
    """Формула ПРОВЕРКИ!B3 выводит русские вердикты, а критерии COUNTIF
    остаются английскими — по ним считается колонка проверок."""
    import zipfile
    xml = zipfile.ZipFile(core._V4_TEMPLATE_PATH).read(
        "xl/worksheets/sheet16.xml").decode("utf-8")
    assert "ПРОЙДЕНО С ПРЕДУПРЕЖДЕНИЯМИ" in xml
    # Диапазон растёт вместе с parity-строками (0.17.18: F6:F84) — тесту
    # важен сам механизм COUNTIF по колонке, а не конкретная граница.
    assert re.search(r'COUNTIF\(F6:F\d+,"FAIL"\)', xml)
    assert '"PASS WITH WARNINGS"' not in xml


def test_the_scenario_key_stays_english():
    """B6 — ключ MATCH'а по списку сценариев книги, а не надпись: перевод
    этого слова роняет расчёт целиком (проверено — MATCH не находит)."""
    import openpyxl
    content, _, _ = core.build_project_workbook(
        dict(core.DEFAULT_INPUTS),
        {key: dict(value) for key, value in core.TEP_DEFAULT.items()},
        [], {}, finance_hints={})
    sheet = openpyxl.load_workbook(io.BytesIO(content), data_only=False)["Вводные"]
    assert sheet["B6"].value == "Base"
