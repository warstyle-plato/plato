"""Порядок разделов отчёта, паритет сайта с ботом и правило двух баз.

Три вещи, сходящиеся в одном отчёте.

Первое: разделы собирались в том порядке, в каком их удобно было считать, и
отчёт читался как история правок — удельные расходы стройки стояли на первой
странице до ТЭП, вводные лежали после выводов и чувствительности, графики
продаж жили в блоке финансирования. Теперь порядок — разбор проекта: что за
участок → что на нём выходит → на чём считали → сколько стоит → сколько
приносит → чем финансируется → чем рискуем → когда.

Второе: правило «поверхности считают один раз» применили к боту и забыли про
сайт. Бот пересчитывал модель на сервере, а /report/pdf строил отчёт по
результату из браузера — пока вкладка свежая, разницы нет, а устаревшая давала
два достоверных на вид отчёта с разными числами.

Третье: удельный показатель без второй базы читается как другой показатель.
23 тыс ₽/м² подземной части — это на метр ГНС проекта, а ставка подземного
метра 190, и одна колонка уже стоила разбирательства.

Запуск: python3 -m pytest tests -q
"""

from __future__ import annotations

import io
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import main as wrapper  # noqa: E402

core = wrapper.core


def _payload(phasing: dict | None = None):
    inputs = dict(core.DEFAULT_INPUTS)
    tep = {key: dict(value) for key, value in core.TEP_DEFAULT.items()}
    bundle = core._run_authoritative_model(inputs, tep, [], phasing or {})
    return {"result": bundle["consolidated"], "inputs": inputs, "tep": tep,
            "rates": [], "phasing": phasing or {}, "scenario": "base",
            "project_name": "Вёрстка"}


@pytest.fixture(scope="module")
def payload():
    return _payload()


@pytest.fixture(scope="module")
def text(payload):
    pypdf = pytest.importorskip("pypdf")
    data = core._build_developaid_pdf(payload)
    return "\n".join(page.extract_text() or ""
                     for page in pypdf.PdfReader(io.BytesIO(data)).pages)


# --- порядок разделов --------------------------------------------------------

_ORDER = [
    "ТЭП",
    "Ключевая экономика",
    "Удельная экономика проекта",
    "Оценка целесообразности покупки",
    "Цены и основные предпосылки",
    "Структура расходов",
    "Удельные расходы строительства",
    "Продажи и продукты",
    "Темп продаж квартир",
    "Финансирование и динамика проекта",
    "Календарный план проекта",
]


def test_the_report_reads_as_a_project_review(text):
    """Участок и ТЭП — раньше экономики: сначала что за объект, потом сколько
    он даёт. Себестоимость — после структуры расходов, а не до ТЭП."""
    positions = []
    for title in _ORDER:
        position = text.find(title)
        assert position >= 0, f"раздел пропал: {title}"
        positions.append(position)
    assert positions == sorted(positions), (
        "порядок разделов разъехался: " + ", ".join(_ORDER))


def test_the_sales_charts_stand_next_to_the_sales_tables(text):
    """Графики темпа жили в блоке финансирования — между таблицей продаж и её
    же картинкой стояли долг, ставки и БРИДЖ."""
    assert text.find("Месячный темп продаж") > text.find("Темп продаж квартир")
    assert text.find("Месячный темп продаж") < text.find("Финансирование и динамика")


def test_an_empty_section_leaves_no_blank_page():
    """Разрывы страниц ставит сборка, а не сами блоки: раздела нет — нет и
    пустой страницы под него."""
    order = [("a", False), ("empty", True), ("b", True)]
    marks = core._PdfSection
    story = [marks("a"), "первый", marks("b"), "второй"]
    out = core._pdf_ordered_story(story, order, lambda: "РАЗРЫВ")
    assert out == ["первый", "РАЗРЫВ", "второй"]


def test_the_head_stays_above_every_section():
    """Шапка — всё до первой метки: дата, источник ТЭП и отпечаток расчёта
    обязаны остаться первыми, куда бы ни уехали разделы."""
    out = core._pdf_ordered_story(
        ["шапка", core._PdfSection("x"), "раздел"], [("x", False)], lambda: "РАЗРЫВ")
    assert out[0] == "шапка"


# --- паритет сайта с ботом ---------------------------------------------------

def test_the_site_pdf_is_built_from_the_server_calculation(payload, monkeypatch):
    """Сайт печатал то, что прислал браузер. Теперь — то, что посчитал сервер,
    как и бот: иначе два отчёта по одним вводным расходятся молча."""
    seen = {}
    original = core._run_authoritative_model

    def counted(inputs, tep, rates, phasing):
        seen["ran"] = True
        return original(inputs, tep, rates, phasing)

    monkeypatch.setattr(core, "_run_authoritative_model", counted)
    stale = {**payload, "result": {**payload["result"],
                                   "summary": {**payload["result"]["summary"],
                                               "net_profit": 0.0}}}
    response = TestClient(core.app).post("/report/pdf", json=stale)
    assert response.status_code == 200
    assert seen.get("ran"), "сервер обязан пересчитать модель сам"

    pypdf = pytest.importorskip("pypdf")
    text = "\n".join(page.extract_text() or ""
                     for page in pypdf.PdfReader(io.BytesIO(response.content)).pages)
    assert "разошёлся с расчётом на сервере" in text, (
        "подменить числа молча нельзя — человек увидит в PDF не то, что на экране")


def test_a_fresh_page_gets_no_parity_warning(payload):
    """Свежая вкладка совпадает с сервером — плашке взяться неоткуда."""
    response = TestClient(core.app).post("/report/pdf", json=payload)
    assert response.status_code == 200
    pypdf = pytest.importorskip("pypdf")
    text = "\n".join(page.extract_text() or ""
                     for page in pypdf.PdfReader(io.BytesIO(response.content)).pages)
    assert "разошёлся с расчётом на сервере" not in text


def test_a_failed_recalculation_still_returns_the_report(payload, monkeypatch):
    """Отчёт нужнее сверки: пересчёт упал — печатаем присланное, как раньше."""
    def boom(*args, **kwargs):
        raise RuntimeError("расчёт не состоялся")

    monkeypatch.setattr(core, "_run_authoritative_model", boom)
    response = TestClient(core.app).post("/report/pdf", json=payload)
    assert response.status_code == 200
    assert response.content[:4] == b"%PDF"


# --- обе базы у каждого удельного --------------------------------------------

_PAIRS = [
    ("full_cost_per_saleable_th", "full_cost_per_gns_th"),
    ("construction_cost_per_saleable_th", "construction_cost_per_gns_th"),
    ("ebitda_per_saleable_th", "ebitda_per_gns_th"),
    ("net_profit_per_saleable_th", "net_profit_per_gns_th"),
]


def test_every_summary_unit_metric_has_both_bases(payload):
    summary = payload["result"]["summary"]
    gns = float(summary["project_gns_sqm"])
    saleable = float(summary["monetizable_saleable_sqm"])
    for saleable_key, gns_key in _PAIRS:
        assert saleable_key in summary and gns_key in summary, (saleable_key, gns_key)
    assert summary["net_profit_per_gns_th"] == pytest.approx(
        summary["net_profit"] / gns / 1000)
    assert summary["net_profit_per_saleable_th"] == pytest.approx(
        summary["net_profit"] / saleable / 1000)


def test_the_phased_summary_carries_both_bases_too():
    bundle = core._run_authoritative_model(
        dict(core.DEFAULT_INPUTS),
        {key: dict(value) for key, value in core.TEP_DEFAULT.items()},
        [], {"enabled": True, "phase_count": 2, "phase_gap_months": 12})
    summary = bundle["consolidated"]["summary"]
    for saleable_key, gns_key in _PAIRS:
        assert saleable_key in summary and gns_key in summary
    for item in bundle["comparison"]:
        for key in ("revenue_per_saleable_th", "revenue_per_gns_th",
                    "capex_per_saleable_th", "capex_per_gns_th",
                    "expenses_per_saleable_th", "expenses_per_gns_th",
                    "net_profit_per_saleable_th", "net_profit_per_gns_th"):
            assert key in item, key


def test_no_lonely_unit_metric_survives_anywhere(payload):
    """Правило проверяется механически: любое поле «на метр» обязано иметь
    пару по второй базе. Так новое удельное поле нельзя завести с одной."""
    lonely: list[str] = []

    def walk(node, path=""):
        if isinstance(node, dict):
            keys = set(node)
            for key in keys:
                if key.endswith("per_gns_th") and key.replace("per_gns_th", "per_saleable_th") not in keys:
                    lonely.append(f"{path}.{key}")
                if key.endswith("per_saleable_th") and key.replace("per_saleable_th", "per_gns_th") not in keys:
                    lonely.append(f"{path}.{key}")
            for key, value in node.items():
                walk(value, f"{path}.{key}")
        elif isinstance(node, list):
            for index, value in enumerate(node[:3]):
                walk(value, f"{path}[{index}]")

    walk(payload["result"])
    assert not lonely, "удельные без второй базы: " + ", ".join(sorted(set(lonely)))


def test_the_expense_structure_speaks_in_roubles_per_metre(payload, text):
    """По этим статьям спорят с подрядчиком и банком, а они были только в
    долях процента."""
    for item in payload["result"]["report"]["expense_structure"]:
        assert item["per_gns_th"] > 0 and item["per_saleable_th"] > 0
    flat = " ".join(text.split())
    assert "Итого расходы" in flat


def test_the_page_shows_both_bases_as_well():
    page = core.PAGE
    assert "construction_cost_per_saleable_th" in page
    assert "net_profit_per_gns_th" in page
    assert "ebitda_per_gns_th" in page
    assert "expenseTotalGns" in page and "expenseTotalSaleable" in page


def test_the_workbook_phase_sheet_pairs_the_columns():
    """Итоговая строка книги берёт колонки по заголовку: номера разъезжались
    каждый раз, когда в таблицу добавлялся показатель."""
    import inspect
    source = inspect.getsource(core._model_sheet_phase_comparison)
    assert 'header.index("CAPEX, тыс ₽/м² продаваемой")' in source
    assert 'header.index("Чистая прибыль, тыс ₽/м² строит. объёма")' in source
    assert "1: \"saleable_sqm\"" not in source, "номера колонок вернулись"
