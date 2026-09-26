"""Дашборд книги и тизер PDF показывают тот же расчёт, что движок.

ТЗ владельца (19.09.2026): одна модель представления на две поверхности —
инвестор читает Excel, банк и партнёр одну страницу. Здесь проверяется вся
цепочка: движок → `presentation_numbers` → модель представления → скрытый
`Dashboard_Data` (через вычислитель формул) → «Дашборд» → тизер (текст PDF).

Сверяются те величины, за которые книга уже отвечает строками паритета
(ПРОВЕРКИ 76–87): Dashboard_Data читает их же колонку B, и второй источник
«где в книге выручка» здесь не заводится. NPV в книге считается СВОЕЙ
формулой (КОНСОЛИДАТОР!O8 — NPV помесячного CF капитала) и с движком на
умолчаниях расходится на 200 млн ₽ — строки паритета у него нет, поэтому здесь
он не сверяется, а назван в задачах.

Предохранитель: проект с нехваткой одобренного лимита и с дефолтом в РВЭ —
иначе риски не проверяются вовсе, и проверка зелена на любом коде.

Запуск: python3 -m pytest tests/test_the_dashboard_and_the_teaser_show_one_calculation.py -q
"""

from __future__ import annotations

import ast
import copy
import io
import re
import sys
import zipfile
from pathlib import Path

import openpyxl
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from xlsx_eval import Evaluator  # noqa: E402

import main as _wrapper  # noqa: E402
import presentation  # noqa: E402
import teaser_pdf  # noqa: E402
import v4_dashboard  # noqa: E402

core = _wrapper.core
ROOT = Path(__file__).resolve().parent.parent

# Величины, за которые книга отвечает строками паритета, — и их допуски.
SWORN = ("revenue_mln", "capex_mln", "ebitda_mln", "financing_mln", "tax_mln",
         "net_profit_mln", "llcr", "peak_bridge_mln", "peak_pf_mln", "vat_mln",
         "pf_shortfall_mln", "commercial_mln", "rve_unpaid_mln", "ending_pf_mln",
         "term_months", "margin")


def _tolerance(key: str, target: float, evaluator=None) -> float:
    """Допуск — тот, которым книга сама судит свой паритет.

    У строк ПРОВЕРОК он стоит в колонке E: у производных (налог, чистая
    прибыль) это сумма допусков слагаемых, а не полпроцента от себя —
    второй список допусков здесь разошёлся бы с книгой и краснел бы на её
    же шуме.
    """
    if evaluator is not None and key in v4_dashboard._PARITY:
        return float(evaluator.cell("ПРОВЕРКИ", f"E{v4_dashboard._PARITY[key]}") or 0)
    if key == "llcr":
        return core._V4_PARITY_LLCR_TOLERANCE
    if key == "margin":
        return 0.001
    if key == "term_months":
        return 0.0
    share = core._V4_PARITY_SHARE.get(key, core._V4_PARITY_SHARE_DEFAULT)
    return max(1.0, abs(target) * share)


def _starved() -> tuple[dict, dict, None]:
    """Одобренный лимит меньше потребности: нехватка ПФ и LLCR ниже цели."""
    inputs = copy.deepcopy(core.DEFAULT_INPUTS)
    inputs.update(pf_limit_approved_mln=15000, project_name="Проект дашборда")
    return inputs, copy.deepcopy(core.TEP_DEFAULT), None


def _defaulted() -> tuple[dict, dict, None]:
    """Дефолт в РВЭ: раскрытого эскроу не хватает."""
    inputs = copy.deepcopy(core.DEFAULT_INPUTS)
    inputs.update(project_name="Проект с дефолтом")
    return inputs, copy.deepcopy(core.TEP_DEFAULT), None


def _phased() -> tuple[dict, dict, dict]:
    """Две очереди: строки сроков и лента дашборда живут по очередям."""
    inputs = copy.deepcopy(core.DEFAULT_INPUTS)
    inputs.update(project_name="Проект в две очереди")
    phasing = {"enabled": True, "mode": "phased", "phase_count": 2, "user_enabled": True,
               "phase_gap_months": 12,
               "phases": [{"name": f"О{i + 1}", "start_offset_months": 12 * i,
                           "construction_months": 30} for i in range(2)]}
    return inputs, copy.deepcopy(core.TEP_DEFAULT), phasing


def _build(shape):
    inputs, tep, phasing = shape()
    bundle = core._run_authoritative_model(inputs, tep, [], phasing)
    numbers = core.presentation_numbers(bundle["consolidated"])
    model = core.project_presentation(bundle, inputs, tep, phasing)
    sys.setrecursionlimit(400000)
    content, _, meta = core.build_project_workbook(inputs, tep, [], phasing)
    assert meta["missing"] == [], meta["missing"]
    evaluator = Evaluator(openpyxl.load_workbook(io.BytesIO(content), data_only=False))
    teaser = core.build_teaser_pdf(bundle, inputs, tep, phasing)
    return bundle, numbers, model, content, evaluator, teaser


@pytest.fixture(scope="module")
def starved():
    return _build(_starved)


@pytest.fixture(scope="module")
def defaulted():
    return _build(_defaulted)


@pytest.fixture(scope="module")
def phased():
    return _build(_phased)


def _pdf_text(pdf: bytes) -> str:
    """Текст тизера. Страниц ровно две — тизер и «Итог» (образец владельца):
    третья значит, что блок не влез, а не что тизер стал подробнее."""
    from pypdf import PdfReader
    reader = PdfReader(io.BytesIO(pdf))
    assert len(reader.pages) == 2, f"тизер — две страницы, а вышло {len(reader.pages)}"
    return " ".join(page.extract_text() for page in reader.pages)


# --- модель представления не считает ------------------------------------------

def test_the_presentation_layer_contains_no_arithmetic():
    tree = ast.parse((ROOT / "presentation.py").read_text(encoding="utf-8"))
    arithmetic = (ast.Add, ast.Sub, ast.Mult, ast.Div, ast.FloorDiv, ast.Mod, ast.Pow)
    found = [f"строка {node.lineno}: {type(node.op).__name__}"
             for node in ast.walk(tree)
             if isinstance(node, ast.BinOp) and isinstance(node.op, arithmetic)]
    assert not found, "в модели представления появилась арифметика: " + "; ".join(found)


def test_the_fixtures_carry_the_risks(starved, defaulted):
    """Предохранитель: без нехватки лимита и дефолта риски не проверяются."""
    _, numbers, model, *_ = starved
    assert numbers["pf_shortfall_mln"] > 1.0
    assert {r["key"] for r in model["risks"] if r["active"]} >= {"pf_shortfall", "llcr_below_target"}
    _, numbers, model, *_ = defaulted
    assert numbers["rve_unpaid_mln"] > 1.0
    assert "default_rve" in {r["key"] for r in model["risks"] if r["active"]}


# --- движок → Dashboard_Data ---------------------------------------------------

@pytest.mark.parametrize("shape", ["starved", "defaulted"])
def test_the_data_sheet_reads_the_same_numbers_as_the_engine(shape, request):
    _, numbers, _, _, evaluator, _ = request.getfixturevalue(shape)
    for key in SWORN:
        row = v4_dashboard.DATA_ROWS[key]
        book = float(evaluator.cell(v4_dashboard.DATA_SHEET, f"C{row}") or 0)
        engine = float(numbers[key] or 0)
        assert abs(book - engine) <= _tolerance(key, engine, evaluator), (key, book, engine)


def test_the_product_rows_match_the_engine(starved):
    bundle, numbers, model, _, evaluator, _ = starved
    by_key = {p["key"]: p for p in model["products"]}
    checked = 0
    for key, row in v4_dashboard.PRODUCT_ROWS.items():
        product = by_key.get(key)
        if not product:
            continue
        book_revenue = float(evaluator.cell(v4_dashboard.DATA_SHEET, f"F{row}") or 0)
        assert abs(book_revenue - float(product["revenue_mln"] or 0)) <= max(1.0, abs(book_revenue) * 0.0005), key
        if product.get("saleable"):
            book_saleable = float(evaluator.cell(v4_dashboard.DATA_SHEET, f"D{row}") or 0)
            assert abs(book_saleable - float(product["saleable"])) <= 1.0, key
        if product.get("gns"):
            book_gns = float(evaluator.cell(v4_dashboard.DATA_SHEET, f"C{row}") or 0)
            assert abs(book_gns - float(product["gns"])) <= 1.0, key
        checked += 1
    assert checked >= 3, "продуктов с выручкой должно быть хотя бы три"


@pytest.mark.parametrize("shape", ["starved", "defaulted"])
def test_the_risks_agree(shape, request):
    _, _, model, _, evaluator, _ = request.getfixturevalue(shape)
    for risk in model["risks"]:
        row = v4_dashboard.RISK_ROWS[risk["key"]]
        book_flag = float(evaluator.cell(v4_dashboard.DATA_SHEET, f"C{row}") or 0)
        assert book_flag == (1.0 if risk["active"] else 0.0), (risk["key"], book_flag, risk)


# --- движок → Dashboard_Data: страница «Итог» -----------------------------------

SUMMARY_KEYS = ("irr_equity", "full_project_cost_mln", "peak_escrow_mln", "rve_escrow_release_mln",
                "bridge_interest_mln", "pf_interest_mln", "gns_above_sqm", "saleable_sqm")


def _summary_engine(model: dict) -> dict[str, float | None]:
    eff, fin, tep = model["efficiency"], model["financing"], model["tep"]
    return {
        "irr_equity": eff.get("irr_equity"),
        "full_project_cost_mln": eff.get("full_project_cost_mln"),
        "peak_escrow_mln": fin.get("peak_escrow_mln"),
        "rve_escrow_release_mln": fin.get("rve_escrow_release_mln"),
        "bridge_interest_mln": fin.get("bridge_interest_mln"),
        "pf_interest_mln": fin.get("pf_interest_mln"),
        "gns_above_sqm": tep.get("project_gns_sqm"),
        "saleable_sqm": tep.get("saleable_sqm"),
    }


def _close(book: float, engine: float, key: str = "") -> bool:
    if key == "irr_equity":
        return abs(book - engine) <= 0.002
    if key.endswith("_sqm"):
        return abs(book - engine) <= 1.0
    return abs(book - engine) <= max(1.0, abs(engine) * 0.005)


@pytest.mark.parametrize("shape", ["starved", "phased"])
def test_the_summary_rows_read_the_same_numbers_as_the_engine(shape, request):
    """Эффективность, финансовая деятельность и базы удельных страницы «Итог»
    — те же числа, что у движка, а не второй счёт по книге."""
    _, _, model, _, evaluator, _ = request.getfixturevalue(shape)
    engine = _summary_engine(model)
    for key in SUMMARY_KEYS:
        book = evaluator.cell(v4_dashboard.DATA_SHEET, f"C{v4_dashboard.DATA_ROWS[key]}")
        assert engine[key] is not None, key
        assert _close(float(book), float(engine[key]), key), (key, book, engine[key])
    # Комиссии книга делит иначе (плата за лимит; выдача БРИДЖа и резервирование
    # ПФ вместе) — сходится их сумма.
    fin = model["financing"]
    fees_engine = sum(float(fin.get(k) or 0.0) for k in ("bridge_fee_mln", "pf_limit_fee_mln", "pf_reservation_fee_mln"))
    fees_book = sum(float(evaluator.cell(v4_dashboard.DATA_SHEET, f"C{v4_dashboard.DATA_ROWS[k]}") or 0)
                    for k in ("pf_limit_fee_mln", "issue_fees_mln"))
    assert _close(fees_book, fees_engine), (fees_book, fees_engine)


@pytest.mark.parametrize("shape", ["starved", "phased"])
def test_the_construction_costs_match_the_engine(shape, request):
    _, _, model, _, evaluator, _ = request.getfixturevalue(shape)
    book_labels = [label for label, _keys in v4_dashboard.COST_ITEMS]
    assert model["construction_costs"], "у движка нет статей себестоимости"
    for row in model["construction_costs"]:
        assert row["label"] in book_labels, row["label"]
        r = v4_dashboard.COST_FIRST_ROW + book_labels.index(row["label"])
        total = float(evaluator.cell(v4_dashboard.DATA_SHEET, f"B{r}") or 0)
        assert _close(total, row["total_mln"]), (row["label"], total, row["total_mln"])
        per_gns = float(evaluator.cell(v4_dashboard.DATA_SHEET, f"C{r}") or 0)
        per_saleable = float(evaluator.cell(v4_dashboard.DATA_SHEET, f"D{r}") or 0)
        assert abs(per_gns - row["per_gns_th"]) <= max(0.01, row["per_gns_th"] * 0.005), row["label"]
        assert abs(per_saleable - row["per_saleable_th"]) <= max(0.01, row["per_saleable_th"] * 0.005), row["label"]
    book_total = float(evaluator.cell(v4_dashboard.DATA_SHEET, f"B{v4_dashboard.COST_TOTAL_ROW}") or 0)
    assert _close(book_total, sum(r["total_mln"] for r in model["construction_costs"]))


@pytest.mark.parametrize("shape", ["starved", "phased"])
def test_the_expense_structure_matches_the_engine(shape, request):
    """Статьи структуры расходов — те же, что у движка, с его долями и
    удельными; проценты и налог — в допуске паритета своей строки."""
    _, _, model, _, evaluator, _ = request.getfixturevalue(shape)
    book_labels = [label for label, _f in v4_dashboard.STRUCTURE_ITEMS]
    parity_tolerance = {"Проценты и комиссии": "financing_mln", "Налог на прибыль": "tax_mln"}
    assert len(model["expense_structure"]) >= 8
    for row in model["expense_structure"]:
        assert row["label"] in book_labels, row["label"]
        r = v4_dashboard.STRUCTURE_FIRST_ROW + book_labels.index(row["label"])
        total = float(evaluator.cell(v4_dashboard.DATA_SHEET, f"B{r}") or 0)
        key = parity_tolerance.get(row["label"])
        tolerance = _tolerance(key, row["total_mln"], evaluator) if key else max(1.0, row["total_mln"] * 0.005)
        assert abs(total - row["total_mln"]) <= tolerance, (row["label"], total, row["total_mln"])
        share = float(evaluator.cell(v4_dashboard.DATA_SHEET, f"C{r}") or 0)
        assert abs(share - row["share"]) <= 0.001, (row["label"], share, row["share"])
    total = float(evaluator.cell(v4_dashboard.DATA_SHEET, f"B{v4_dashboard.STRUCTURE_TOTAL_ROW}") or 0)
    assert _close(total, sum(r["total_mln"] for r in model["expense_structure"]))
    # Строки без денег в книге стоят нулём — и только они не встречаются у движка.
    engine_labels = {r["label"] for r in model["expense_structure"]}
    for index, label in enumerate(book_labels):
        if label not in engine_labels:
            r = v4_dashboard.STRUCTURE_FIRST_ROW + index
            assert abs(float(evaluator.cell(v4_dashboard.DATA_SHEET, f"B{r}") or 0)) < 0.5, label


def test_the_product_prices_and_pace_match_the_engine(starved):
    _, _, model, _, evaluator, _ = starved
    by_key = {p["key"]: p for p in model["products"]}
    columns = v4_dashboard.PRODUCT_COLUMNS
    checked = 0
    for key, row in v4_dashboard.PRODUCT_ROWS.items():
        product = by_key.get(key)
        if not product or not product.get("revenue_mln"):
            continue
        cell = lambda name: float(evaluator.cell(v4_dashboard.DATA_SHEET, f"{columns[name]}{row}") or 0)  # noqa: E731
        assert abs(cell("start_price") - float(product["start_price_th"])) <= 0.5, key
        assert abs(cell("avg_price") - float(product["avg_price_th"])) <= max(0.5, product["avg_price_th"] * 0.005), key
        assert abs(cell("pace") - float(product["pace_month"])) <= max(0.5, product["pace_month"] * 0.005), key
        per_gns = product.get("per_gns_th") if product.get("per_gns_th") is not None else product.get("per_unit_th")
        assert abs(cell("per_gns") - float(per_gns)) <= max(0.1, per_gns * 0.005), key
        if product.get("per_saleable_th"):
            assert abs(cell("per_saleable") - float(product["per_saleable_th"])) <= max(0.1, product["per_saleable_th"] * 0.005), key
        checked += 1
    assert checked >= 3
    unit = {u["label"]: u for u in model["unit_economics"]}["Выручка"]
    t = v4_dashboard.PRODUCT_TOTAL_ROW
    assert abs(float(evaluator.cell(v4_dashboard.DATA_SHEET, f"{columns['per_gns']}{t}")) - unit["per_gns_th"]) <= 0.1
    assert abs(float(evaluator.cell(v4_dashboard.DATA_SHEET, f"{columns['per_saleable']}{t}")) - unit["per_saleable_th"]) <= 0.1


def test_the_queue_dates_match_the_engine(phased):
    """Даты очередей на дашборде — те же, что у движка; выключенные очереди
    молчат, а лента стройки длится ровно столько месяцев, сколько стройка."""
    _, _, model, _, evaluator, _ = phased
    columns = v4_dashboard.QUEUE_COLUMNS
    phases = model["phases"]
    assert len(phases) == 2
    for q, phase in enumerate(phases):
        r = v4_dashboard.QUEUE_FIRST_ROW + q
        assert float(evaluator.cell(v4_dashboard.DATA_SHEET, f"{columns['on']}{r}")) == 1.0
        for book_key, engine_key in (("permit", "permit"), ("rve", "rve"),
                                     ("sales_start", "sales_start"), ("sales_end", "sales_end")):
            book = evaluator.cell(v4_dashboard.DATA_SHEET, f"{columns[book_key]}{r}")
            assert str(book)[:10] == phase["dates"][engine_key], (q, book_key, book, phase["dates"])
    for q in range(len(phases), v4_dashboard.QUEUE_COUNT):
        r = v4_dashboard.QUEUE_FIRST_ROW + q
        assert float(evaluator.cell(v4_dashboard.DATA_SHEET, f"{columns['on']}{r}")) == 0.0
    # Лента на «Дашборде»: строка стройки первой очереди — по одной клетке на
    # год, знаков в клетках столько, сколько месяцев стройки.
    sheet = _dashboard_grid(evaluator)
    build_rows = [r for r, cells in sheet.items() if cells.get("B") == "Стройка"]
    sales_rows = [r for r, cells in sheet.items() if cells.get("B") == "Продажи"]
    assert len(build_rows) == 2 and len(sales_rows) == 2, (build_rows, sales_rows)
    months = int(evaluator.cell(v4_dashboard.DATA_SHEET, f"{columns['build_months']}{v4_dashboard.QUEUE_FIRST_ROW}"))
    bars = "".join(str(v) for c, v in sheet[build_rows[0]].items() if c not in ("A", "B"))
    assert set(bars) == {"█"} and len(bars) == months, (bars, months)
    # Выключенных очередей на ленте нет: их строки пусты.
    quiet = [r for r, cells in sheet.items() if r > build_rows[-1] and cells.get("A") in ("Очередь 3", "Очередь 4")]
    assert quiet == [], quiet


def _dashboard_grid(evaluator) -> dict[int, dict[str, object]]:
    """Все непустые значения «Дашборда» по строкам — как их посчитает Excel."""
    sheet = evaluator.workbook["Дашборд"]
    grid: dict[int, dict[str, object]] = {}
    for row in sheet.iter_rows():
        for cell in row:
            if cell.value is None:
                continue
            value = cell.value
            if isinstance(value, str) and value.startswith("="):
                value = evaluator.cell("Дашборд", cell.coordinate)
            if value in (None, ""):
                continue
            grid.setdefault(cell.row, {})[cell.column_letter] = value
    return grid


SUMMARY_SECTIONS = ("ПОКАЗАТЕЛИ ЭФФЕКТИВНОСТИ ПРОЕКТА", "ТЭП · ПОСТРОЕНО", "ДОХОДЫ",
                    "ЦЕНЫ РЕАЛИЗАЦИИ И ТЕМП ПРОДАЖ", "СЕБЕСТОИМОСТЬ СТРОИТЕЛЬСТВА",
                    "СТРУКТУРА РАСХОДОВ ПРОЕКТА", "ФИНАНСОВАЯ ДЕЯТЕЛЬНОСТЬ И НАЛОГИ",
                    "СРОКИ · ОЧЕРЕДИ", "ДОЛГ И ЭСКРОУ ПО МЕСЯЦАМ")


def test_the_dashboard_is_narrow_and_follows_the_summary_page(starved):
    """Двенадцать колонок и ни одной шире; блоки — как на странице «Итог»,
    сверху вниз; диаграммы не выходят за правый край."""
    _, _, _, content, evaluator, _ = starved
    archive = zipfile.ZipFile(io.BytesIO(content))
    sheet = archive.read(core._v4_sheet_path(archive, "Дашборд")).decode("utf-8")
    columns = {re.match(r"[A-Z]+", ref).group(0) for ref in re.findall(r'<x:c r="([A-Z]+\d+)"', sheet)}
    assert max(v4_dashboard._col_index(c) for c in columns) + 1 == v4_dashboard.WIDTH == 12, sorted(columns)
    for merge in re.findall(r'<x:mergeCell ref="[A-Z]+\d+:([A-Z]+)\d+"', sheet):
        assert v4_dashboard._col_index(merge) < v4_dashboard.WIDTH, merge
    drawing = archive.read("xl/drawings/drawing1.xml").decode("utf-8")
    anchors = re.findall(r"<xdr:to><xdr:col>(\d+)</xdr:col>", drawing)
    assert len(anchors) == 3 and all(int(c) <= v4_dashboard.WIDTH for c in anchors), anchors
    grid = _dashboard_grid(evaluator)
    titles = [str(cells["A"]) for _r, cells in sorted(grid.items()) if "A" in cells]
    order = [titles.index(section) for section in SUMMARY_SECTIONS]
    assert order == sorted(order), list(zip(SUMMARY_SECTIONS, order))
    # Строки «Итога» на своих местах: полные расходы, IRR, раскрытие эскроу,
    # НДС, себестоимость по статье и структура — все читают источник.
    by_label = {str(cells["A"]): cells for _r, cells in grid.items() if "A" in cells}
    for label in ("Полные расходы проекта (с НДС), млн ₽", "IRR собственного капитала, %",
                  "Раскрыто эскроу в РВЭ, млн ₽", "НДС к уплате, млн ₽", "СМР наземной части",
                  "Основное строительство", "Квартиры"):
        assert label in by_label, label
    # Маржинальность и IRR — проценты, а не «0,0» денежного формата.
    styles = archive.read("xl/styles.xml").decode("utf-8")
    xfs = re.findall(r'<x:xf [^>]*?(?:/>|>.*?</x:xf>)', re.search(r"<x:cellXfs[^>]*>(.*?)</x:cellXfs>", styles, re.S).group(1), re.S)
    for coordinate in ("E10", "E17", "E18"):
        style = int(re.search(rf'<x:c r="{coordinate}" s="(\d+)"', sheet).group(1))
        assert 'numFmtId="202"' in xfs[style], (coordinate, xfs[style])
    assert float(by_label["Полные расходы проекта (с НДС), млн ₽"]["E"]) == pytest.approx(
        float(evaluator.cell(v4_dashboard.DATA_SHEET, f"C{v4_dashboard.DATA_ROWS['full_project_cost_mln']}")))


# --- Dashboard_Data → Дашборд ---------------------------------------------------

def test_the_dashboard_is_formulas_only_and_the_source_is_hidden(starved):
    _, _, _, content, evaluator, _ = starved
    archive = zipfile.ZipFile(io.BytesIO(content))
    workbook = archive.read("xl/workbook.xml").decode("utf-8")
    assert re.search(r'<x:sheet name="Dashboard_Data"[^>]*state="hidden"', workbook)
    sheet = archive.read(core._v4_sheet_path(archive, "Дашборд")).decode("utf-8")
    numbers = re.findall(r'<x:c r="([A-Z]+\d+)"[^>]*>(?:(?!</x:c>).)*?<x:v>', sheet)
    assert numbers == [], f"на «Дашборде» числа вместо формул: {numbers[:5]}"
    formulas = re.findall(r"<x:f>([^<]*)</x:f>", sheet)
    foreign = [f for f in formulas if "Dashboard_Data" not in f and "'" in f]
    assert not foreign, f"«Дашборд» читает мимо источника: {foreign[:5]}"
    data = archive.read(v4_dashboard.DATA_SHEET_PATH).decode("utf-8")
    literals = re.findall(r'<x:c r="([A-Z]+\d+)"[^>]*>\s*<x:v>', data)
    assert literals == [f"C{v4_dashboard.DATA_ROWS['llcr_target']}"], literals
    # Карточки читают те же строки источника, что и паритет.
    first_card = evaluator.cell("Дашборд", "A5")
    assert abs(float(first_card) - float(evaluator.cell("ПРОВЕРКИ", "B76"))) < 1e-6


def test_the_charts_read_the_source_ranges(starved):
    _, _, _, content, _, _ = starved
    archive = zipfile.ZipFile(io.BytesIO(content))
    types = archive.read("[Content_Types].xml").decode("utf-8")
    charts = re.findall(r'PartName="(/xl/drawings/charts/[^"]+)"', types)
    assert len(charts) == 3, charts
    for part in charts:
        xml = archive.read(part.lstrip("/")).decode("utf-8")
        refs = re.findall(r"<c:f>([^<]*)</c:f>", xml)
        assert refs and all("Dashboard_Data" in ref for ref in refs), (part, refs)
    drawing_rels = archive.read("xl/drawings/_rels/drawing1.xml.rels").decode("utf-8")
    assert len(re.findall(r"relationships/chart", drawing_rels)) == 3
    assert "chart4" not in types and "xl/drawings/charts/chart4.xml" not in archive.namelist()


# --- модель представления → тизер ----------------------------------------------

@pytest.mark.parametrize("shape", ["starved", "defaulted"])
def test_the_teaser_prints_the_cards_of_the_model(shape, request):
    _, _, model, _, _, teaser = request.getfixturevalue(shape)
    text = _pdf_text(teaser)
    for card in model["cards"]:
        unit = card["unit"]
        value = card["value"]
        shown = (core._pdf_num(value * 100, 1) + "%" if unit == "%"
                 else core._pdf_num(value, 2) + "x" if unit == "x"
                 else core._pdf_num(value, 1))
        assert shown in text, (card["key"], shown)
    for risk in model["risks"]:
        if risk["active"]:
            assert risk["label"] in text, risk["label"]
    assert model["origin"]["calculation_id"] in text
    assert core.VERSION in text


def test_the_page_offers_the_teaser_next_to_the_pdf():
    page = core.PAGE
    assert 'onclick="exportTeaserPdf()"' in page
    pdf_at = page.index('onclick="exportReportPdf()"')
    assert abs(page.index('onclick="exportTeaserPdf()"') - pdf_at) < 400
    assert "fetch('/report/teaser'" in page


def test_the_teaser_route_answers_with_two_pages(monkeypatch):
    from fastapi.testclient import TestClient
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    # Наружу маршрут не ходит: без участка ни карты, ни скрининга не бывает.
    monkeypatch.setattr(core, "land_screening", lambda **kw: (_ for _ in ()).throw(AssertionError("наружу")))
    inputs, tep, _ = _starved()
    client = TestClient(core.app)
    response = client.post("/report/teaser", json={"inputs": inputs, "tep": tep, "rates": [],
                                                   "phasing": {}, "project_name": "Маршрут"})
    assert response.status_code == 200, response.text[:300]
    assert response.headers["content-type"].startswith("application/pdf")
    text = _pdf_text(response.content)
    assert "Маршрут" in text
    assert teaser_pdf.NO_MAP_TEXT in text and teaser_pdf.NOT_SCREENED_TEXT in text
    bad = client.post("/report/teaser", json={"tep": tep})
    assert bad.status_code == 400


# --- тизер по образцам владельца: две страницы, участок, карта --------------

def _map_png() -> bytes:
    from PIL import Image
    buffer = io.BytesIO()
    Image.new("RGB", (320, 240), (220, 225, 215)).save(buffer, format="PNG")
    return buffer.getvalue()


SITE = {
    "cadastral_numbers": ["77:01:0004023:15"],
    "address": "Москва, ул. Россолимо, вл. 17",
    "land_area_sqm": 7500.0, "land_area_ha": 0.75, "density_sqm_per_ha": 193841.0,
    "permitted_use": "эксплуатация зданий", "category": "земли населённых пунктов",
    "screened": True,
    "verdict": {"status": "OK", "headline": "Критических ограничений не обнаружено",
                "free_pct": 92.0, "disclaimer": "", "probed": True},
    "findings": [{"name": "Ориентировочная СЗЗ", "flag_class": "economic", "impact": "",
                  "coverage_pct": 100.0}],
    "parcels": [{"cadastral_number": "77:01:0004023:15", "address": "ул. Россолимо, вл. 17",
                 "area_sqm": 7500.0}],
}


def test_the_teaser_is_a_portrait_page_and_a_landscape_summary(starved):
    """Образец владельца: тизер книжный, «Итог» альбомный — ровно две страницы."""
    from pypdf import PdfReader
    bundle, _, _, _, _, _ = starved
    inputs, tep, phasing = _starved()
    pdf = core.build_teaser_pdf(bundle, inputs, tep, phasing, SITE, _map_png())
    reader = PdfReader(io.BytesIO(pdf))
    assert len(reader.pages) == 2
    first, second = reader.pages
    assert float(first.mediabox.height) > float(first.mediabox.width)
    assert float(second.mediabox.width) > float(second.mediabox.height)
    assert teaser_pdf.PAGE1_TITLE in first.extract_text()
    assert teaser_pdf.PAGE2_TITLE in second.extract_text()


def test_the_teaser_shows_the_site_and_its_map(starved):
    """Адрес или КН, площадь участка, ограничения и карта — обязательные блоки."""
    from pypdf import PdfReader
    bundle, _, _, _, _, _ = starved
    inputs, tep, phasing = _starved()
    pdf = core.build_teaser_pdf(bundle, inputs, tep, phasing, SITE, _map_png())
    reader = PdfReader(io.BytesIO(pdf))
    first = reader.pages[0].extract_text()
    assert "77:01:0004023:15" in first and "Россолимо" in first
    assert "0,75" in first and "Плотность" in first
    assert "Ориентировочная СЗЗ" in first and "Критических ограничений не обнаружено" in first
    assert len(reader.pages[0].images) >= 1, "карта участка не встала на первую страницу"
    assert teaser_pdf.NO_MAP_TEXT not in first


def test_a_missing_map_is_named_not_left_blank(starved):
    """Нет карты — сказано почему; нет скрининга — «не проверялись», а не «чисто»."""
    from pypdf import PdfReader
    bundle, _, _, _, _, _ = starved
    inputs, tep, phasing = _starved()
    bare = {"cadastral_numbers": [], "address": ""}
    pdf = core.build_teaser_pdf(bundle, inputs, tep, phasing, bare, None)
    reader = PdfReader(io.BytesIO(pdf))
    first = reader.pages[0].extract_text()
    assert teaser_pdf.NO_MAP_TEXT in first and "кадастровый номер не задан" in first
    assert teaser_pdf.NOT_SCREENED_TEXT in first
    assert len(reader.pages[0].images) == 0


def test_the_teaser_prints_unit_economics_social_and_vri(starved):
    """Удельная экономика, соцнагрузка и ВРИ — из тех же чисел, что у движка."""
    bundle, numbers, model, _, _, _ = starved
    inputs, tep, phasing = _starved()
    text = _pdf_text(core.build_teaser_pdf(bundle, inputs, tep, phasing, SITE, _map_png()))
    for item in numbers["unit_economics"]:
        assert core._pdf_num(item["per_gns_th"], 1) in text, item["label"]
        assert core._pdf_num(item["per_saleable_th"], 1) in text, item["label"]
    land = model["land"]
    assert core._pdf_num(land["social_payment_mln"], 1) in text
    assert core._pdf_num(land["vri_amount_mln"], 1) in text
    for row in numbers["construction_costs"]:
        assert core._pdf_num(row["total_mln"], 1) in text, row["label"]
    assert teaser_pdf.CHART_TITLE in text and teaser_pdf.GANTT_TITLE in text


def test_site_facts_come_from_the_same_screening_as_the_full_pdf(monkeypatch):
    """Паспорт участка и ограничения — одним вызовом `land_screening`;
    отказ источника — «не проверяли», а не «ограничений нет»."""
    calls: list[str] = []

    def fake_screening(cad: str = "", min_area_sqm=None):
        calls.append(cad)
        return {"parcels": [
            {"cadastral_number": "77:01:0004023:15", "found": True, "address": "ул. Россолимо, вл. 17",
             "area_sqm": 5000.0, "category": "земли населённых пунктов", "permitted_use": "офисы",
             "findings": [{"name": "СЗЗ", "flag_class": "economic", "impact": "", "coverage_pct": 40.0}]},
            {"cadastral_number": "77:01:0004023:16", "found": True, "address": "", "area_sqm": 2500.0,
             "category": "", "permitted_use": "", "findings": []},
            {"cadastral_number": "77:01:0004023:99", "found": False},
        ], "verdict": {"status": "OK", "headline": "Критических ограничений нет", "free_pct": 60.0,
                       "disclaimer": "", "probed": True}}

    monkeypatch.setattr(core, "land_screening", fake_screening)
    site = {"cadastral_numbers": ["77:01:0004023:15", "77:01:0004023:16", "77:01:0004023:99"], "address": ""}
    facts = core._teaser_site_facts(site, gns_sqm=15000.0)
    assert calls == ["77:01:0004023:15,77:01:0004023:16,77:01:0004023:99"]
    assert facts["land_area_sqm"] == 7500.0 and facts["land_area_ha"] == 0.75
    assert facts["density_sqm_per_ha"] == pytest.approx(20000.0)
    assert facts["address"] == "ул. Россолимо, вл. 17" and facts["permitted_use"] == "офисы"
    assert facts["screened"] is True and [f["name"] for f in facts["findings"]] == ["СЗЗ"]
    assert len(facts["parcels"]) == 2

    def broken(cad: str = "", min_area_sqm=None):
        raise RuntimeError("НСПД молчит")

    monkeypatch.setattr(core, "land_screening", broken)
    silent = core._teaser_site_facts(site, gns_sqm=15000.0)
    assert silent["screened"] is False and silent["findings"] == [] and silent["land_area_sqm"] is None


def test_the_teaser_map_is_the_bot_picture(monkeypatch):
    """Карта тизера и фото в боте — одна функция; отказ источника — нет карты."""
    monkeypatch.setattr(core, "_territory_image_png", lambda numbers: (b"\x89PNGfake", "подпись"))
    assert core._teaser_map_png({"cadastral_numbers": ["77:01:0004023:15"]}) == b"\x89PNGfake"
    assert core._teaser_map_png({"cadastral_numbers": []}) is None
    monkeypatch.setattr(core, "_territory_image_png", lambda numbers: None)
    assert core._teaser_map_png({"cadastral_numbers": ["77:01:0004023:15"]}) is None

    def boom(numbers):
        raise RuntimeError("НСПД молчит")

    monkeypatch.setattr(core, "_territory_image_png", boom)
    assert core._teaser_map_png({"cadastral_numbers": ["77:01:0004023:15"]}) is None
    source = Path(core.__file__).read_text(encoding="utf-8")
    bot = source[source.index("def _telegram_territory_photo("):]
    bot = bot[:bot.index("\ndef ")]
    assert "_territory_image_png(numbers)" in bot, "бот обязан брать ту же картинку, что тизер"


def test_the_site_numbers_come_from_the_same_place_as_the_full_pdf():
    """Номера участка тизер берёт там же, где полный PDF (`_pdf_screening_numbers`),
    а без них — из груза страницы."""
    inputs = {"_land_lookup": {"query": "77:01:0004023:15, 77:01:0004023:16"}}
    site = core._teaser_site({"cadastral_numbers": ["50:21:0120316:1221"]}, inputs)
    assert site["cadastral_numbers"] == ["77:01:0004023:15", "77:01:0004023:16"]
    site = core._teaser_site({"cadastral_numbers": ["50:21:0120316:1221"], "address": "Коммунарка"}, {})
    assert site["cadastral_numbers"] == ["50:21:0120316:1221"] and site["address"] == "Коммунарка"
