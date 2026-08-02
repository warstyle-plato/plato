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
    # Индексация очереди — множителем цены к сдвигу старта, как в движке.
    assert sheet["S89"].value == pytest.approx(1.08)
    assert sheet["AE89"].value == pytest.approx(0.0)


def test_percent_weights_are_normalized_to_shares():
    """Страница хранит веса очередей в процентах ([40, 32, 28]): записанные
    как есть, они раздували ГНС очереди в сорок раз, а долю покупки — в сто."""
    phasing = {
        "enabled": True, "phase_count": 3,
        "phases": [{"start_offset_months": 12 * i, "construction_months": 24}
                   for i in range(3)],
        "products": {"apartments": [40, 32, 28], "ground_commercial": [40, 32, 28],
                     "underground_parking": [40, 32, 28], "storage": [40, 32, 28]},
        "shared_allocation": {"purchase": [100, 0, 0], "land_rights": [100, 0, 0],
                              "social_compensation": [100, 0, 0]},
        "cost_inflation_pct": 8, "sales_price_inflation_pct": 8,
    }
    content, _, _ = build(phasing=phasing)
    sheet = openpyxl.load_workbook(io.BytesIO(content), data_only=False)["Вводные"]
    total = core.TEP_DEFAULT["apartments"]["gns"]

    assert sheet["W88"].value == pytest.approx(total * 0.40, rel=1e-6)
    assert sheet["W90"].value == pytest.approx(total * 0.28, rel=1e-6)
    assert sheet["P88"].value == pytest.approx(1.0)
    assert sheet["U88"].value == pytest.approx(0.40)


def test_social_construction_is_not_lost_by_the_book():
    """Книга знает один канал соцнагрузки — компенсацию. Строительство садов
    и школ (у Мытищ — миллиарды) иначе выпадало из расходов, завышая LLCR."""
    _, _, _, sheet = _book({
        "social_mode": "Строительство", "social_compensation_mln": 100,
        "kindergarten_places": 465, "kindergarten_cost_mln_per_place": 2.75,
        "school_places": 975, "school_cost_mln_per_place": 3,
        "clinic_capacity": 0,
    })
    assert sheet["B17"].value == pytest.approx(100 + 465 * 2.75 + 975 * 3)


def test_social_construction_is_indexed_to_its_queue():
    """Движок строит соцобъекты в своих очередях с инфляцией затрат: сады во
    второй (×1,08), школа в третьей (×1,166). Базовая сумма занижала
    социалку книги на 12% против движка."""
    phasing = {
        "enabled": True, "phase_count": 3,
        "phases": [{"start_offset_months": 12 * i, "construction_months": 24}
                   for i in range(3)],
        "products": {k: [40, 32, 28] for k in ("apartments", "ground_commercial",
                                               "underground_parking", "storage")},
        "shared_allocation": {}, "cost_inflation_pct": 8,
        "sales_price_inflation_pct": 8,
    }
    content, _, _ = build(
        {"social_mode": "Строительство", "social_compensation_mln": 0,
         "kindergarten_places": 453, "kindergarten_cost_mln_per_place": 2.75,
         "school_places": 950, "school_cost_mln_per_place": 3,
         "clinic_capacity": 124, "clinic_cost_mln_per_unit": 3},
        phasing=phasing)
    sheet = openpyxl.load_workbook(io.BytesIO(content), data_only=False)["Вводные"]

    expected = (453 * 2.75 * 1.08 + 950 * 3 * 1.08 ** 2 + 124 * 3 * 1.08)
    assert sheet["B17"].value == pytest.approx(expected, rel=1e-6)


def test_a_pure_compensation_stays_as_entered():
    _, _, _, sheet = _book({"social_mode": "Денежная компенсация",
                            "social_compensation_mln": 575.379,
                            "kindergarten_places": 465})
    assert sheet["B17"].value == pytest.approx(575.379)


def test_stale_formula_caches_are_stripped(default_book):
    """Просмотрщики формулы не считают: кэшированные результаты шаблона
    показывали числа проекта, под который книга собиралась в прошлый раз."""
    import re as _re
    content, _, _, _ = default_book
    archive = zipfile.ZipFile(io.BytesIO(content))
    stale = 0
    for name in archive.namelist():
        if name.startswith("xl/worksheets/") and name.endswith(".xml"):
            text = archive.read(name).decode("utf-8")
            stale += len(_re.findall(r"</x:f><x:v>", text))
            stale += len(_re.findall(r"<x:f[^>]*/><x:v>", text))
    assert stale == 0, f"в книге осталось {stale} кэшированных результатов формул"


# --- книга считает так же, как движок ---------------------------------------

def test_the_book_passes_its_own_checks_and_matches_the_engine():
    """Книга вся из формул, и ошибка в любой уедет к аналитику молча. Поэтому
    заполненная книга пересчитывается своим вычислителем: собственные проверки
    книги не дают FAIL, а выручка и LLCR сходятся с движком. Так был пойман
    двойной счёт офисов на листе ТЭП и индексация цены первой очереди."""
    import sys
    sys.setrecursionlimit(300000)
    from xlsx_eval import Evaluator

    # Цена выше умолчания: паритет проверяется на проекте, который гасит долг.
    # На слабом проекте книга честно даёт FAIL «финальный долг не ноль» — это
    # её бизнес-чек, а не расхождение с движком.
    inputs = {**core.DEFAULT_INPUTS, "apartment_price_th": 500, "commercial_price_th": 500}
    tep = {k: dict(v) for k, v in core.TEP_DEFAULT.items()}
    phasing = {
        "enabled": True, "phase_count": 2,
        "phases": [{"start_offset_months": 0, "construction_months": 24},
                   {"start_offset_months": 12, "construction_months": 24}],
        "products": {k: [55, 45] for k in ("apartments", "ground_commercial",
                                           "underground_parking", "storage")},
        "shared_allocation": {"purchase": [100, 0], "land_rights": [60, 40],
                              "social_compensation": [100, 0]},
        "cost_inflation_pct": 8, "sales_price_inflation_pct": 8,
    }
    content, _, meta = core.build_project_workbook(
        inputs, tep, [], phasing, project_name="Паритет")
    assert meta["missing"] == []

    book = openpyxl.load_workbook(io.BytesIO(content), data_only=False)
    evaluator = Evaluator(book)
    status = evaluator.cell("ПРОВЕРКИ", "B3")
    if status not in ("PASS", "PASS WITH WARNINGS"):
        broken = [
            f'{book["ПРОВЕРКИ"][f"A{row}"].value}: '
            f'факт={evaluator.cell("ПРОВЕРКИ", f"B{row}")} '
            f'ожид={evaluator.cell("ПРОВЕРКИ", f"C{row}")}'
            for row in range(6, 62)
            if book["ПРОВЕРКИ"][f"A{row}"].value
            and evaluator.cell("ПРОВЕРКИ", f"F{row}") == "FAIL"
        ]
        raise AssertionError(f"книга не проходит свои проверки: {broken}")

    engine = core.calculate_phased(core.PhasedCalcRequest(
        inputs=inputs, tep=tep, rates=[], phasing=phasing))
    summary = engine["consolidated"]["summary"]
    book_revenue = float(evaluator.cell("CF", "B6"))
    book_llcr = float(evaluator.cell("CF", "B30"))

    assert book_revenue == pytest.approx(summary["revenue"] / 1e6, rel=0.02), \
        "выручка книги разошлась с движком больше чем на 2%"
    assert book_llcr == pytest.approx(summary["llcr"], rel=0.05), \
        "LLCR книги разошёлся с движком больше чем на 5%"


def test_the_tep_sheet_does_not_double_count_the_objects():
    """«ИТОГО ЖИЛЫЕ ОЧЕРЕДИ» ссылался на CF!B6, который уже включает офисы,
    ТЦ и наземный паркинг, — и лист ТЭП считал объекты дважды."""
    template = openpyxl.load_workbook(core._V4_TEMPLATE_PATH, data_only=False)
    assert str(template["ТЭП"]["G22"].value).replace(" ", "") == "=SUM(G8,G14,G20)"


def test_a_fourth_queue_is_folded_into_the_third_not_smeared():
    """Листов CF в книге три. Объёмы 4-й очереди ближе по срокам к третьей,
    чем к первой: хвост сливается в О3, а не размазывается по всем, и
    сборка честно говорит об этом в meta."""
    phasing = {
        "enabled": True, "phase_count": 4,
        "phases": [{"start_offset_months": 12 * i, "construction_months": 24}
                   for i in range(4)],
        "products": {k: [30, 30, 20, 20] for k in ("apartments", "ground_commercial",
                                                   "underground_parking", "storage")},
        "shared_allocation": {"purchase": [100, 0, 0, 0], "land_rights": [25, 25, 25, 25],
                              "social_compensation": [100, 0, 0, 0]},
        "cost_inflation_pct": 8, "sales_price_inflation_pct": 8,
    }
    content, _, meta = build(phasing=phasing)
    sheet = openpyxl.load_workbook(io.BytesIO(content), data_only=False)["Вводные"]
    total = core.TEP_DEFAULT["apartments"]["gns"]

    assert any("слиты в третью" in str(item) for item in meta["missing"])
    assert sheet["W88"].value == pytest.approx(total * 0.30, rel=1e-6)
    assert sheet["W89"].value == pytest.approx(total * 0.30, rel=1e-6)
    assert sheet["W90"].value == pytest.approx(total * 0.40, rel=1e-6), \
        "объём четвёртой очереди не слит в третью"
    assert sheet["Q90"].value == pytest.approx(0.50)  # доли ВРИ 25+25


def test_the_objects_inherit_their_queue_from_the_phasing():
    """Шаблонная «очередь 1» сажала офисы в первую очередь, а движок ведёт их
    в третьей: продаваемая площадь очередей расходилась с отчётом."""
    phasing = {
        "enabled": True, "phase_count": 3,
        "phases": [{"start_offset_months": 12 * i, "construction_months": 24}
                   for i in range(3)],
        "products": {k: [40, 32, 28] for k in ("apartments", "ground_commercial",
                                               "underground_parking", "storage")},
        "shared_allocation": {},
        "discrete": {"offices": 3, "standalone_retail": 2, "above_parking": 2},
        "cost_inflation_pct": 8, "sales_price_inflation_pct": 8,
    }
    content, _, _ = build(phasing=phasing)
    sheet = openpyxl.load_workbook(io.BytesIO(content), data_only=False)["Вводные"]

    assert sheet["K21"].value == pytest.approx(3)   # офисы
    assert sheet["K41"].value == pytest.approx(2)   # ТЦ
    assert sheet["K61"].value == pytest.approx(2)   # наземный паркинг

    single, _, _ = build()  # без очередей всё в первой
    sheet_single = openpyxl.load_workbook(io.BytesIO(single), data_only=False)["Вводные"]
    assert sheet_single["K21"].value == pytest.approx(1)


def test_the_report_carries_a_pdf_comparable_unit_revenue():
    """«Средняя цена реализации» книги — площадные продукты без паркинга, а
    PDF делит всю выручку очереди: цифры расходились на цену паркинга и
    читались как ошибка. Строка-мостик считает по определению PDF."""
    template = openpyxl.load_workbook(core._V4_TEMPLATE_PATH, data_only=False)["ОТЧЕТ"]

    assert "как в PDF" in str(template["A73"].value)
    for cell, consolidator in (("B73", "G4"), ("C73", "G5"), ("D73", "G6"), ("E73", "G7")):
        formula = str(template[cell].value)
        assert f"'КОНСОЛИДАТОР'!{consolidator}" in formula, f"{cell} не делит выручку консолидатора"


def test_both_surfaces_carry_the_pure_apartment_unit_price():
    """Смешанные периметры удельных («вся выручка» против «площадных») не
    сверить глазами. Чисто квартирная цена на м² продаваемой — общий
    знаменатель: колонка «в т.ч. квартиры» в PDF и строка 95 книги."""
    import inspect
    module = inspect.getsource(core)
    assert "в т.ч. квартиры" in module, "в PDF нет квартирной колонки"

    phasing = {
        "enabled": True, "phase_count": 2,
        "phases": [{"start_offset_months": 0, "construction_months": 24},
                   {"start_offset_months": 12, "construction_months": 24}],
        "products": {k: [55, 45] for k in ("apartments", "ground_commercial",
                                           "underground_parking", "storage")},
        "shared_allocation": {}, "cost_inflation_pct": 8,
        "sales_price_inflation_pct": 8,
    }
    bundle = core.calculate_phased(core.PhasedCalcRequest(
        inputs=dict(core.DEFAULT_INPUTS),
        tep={k: dict(v) for k, v in core.TEP_DEFAULT.items()},
        rates=[], phasing=phasing))
    row = (bundle.get("comparison") or [{}])[0]
    assert row.get("apartment_price_th"), "сравнение очередей не несёт цену квартир"
    assert row.get("apartment_saleable_sqm"), "нет квартирной продаваемой для итога"

    # Строка стоит внутри таблицы удельных — сразу после «Средней цены
    # реализации», как колонка в PDF, — а не отдельным блоком под отчётом.
    template = openpyxl.load_workbook(core._V4_TEMPLATE_PATH, data_only=False)["ОТЧЕТ"]
    assert template["A60"].value == "Средняя цена реализации"
    assert template["A61"].value == "в т.ч. квартиры"
    for cell, sales in (("B61", "B16"), ("C61", "B39"), ("D61", "B62")):
        formula = str(template[cell].value)
        assert f"'Продажи'!{sales}" in formula and "$L$" in formula, \
            f"{cell} книги не делит квартирную выручку на квартирную продаваемую"
    assert template["B61"].number_format == template["B60"].number_format, \
        "квартирная строка без числового формата удельных"
    # Сдвиг не разорвал ссылки соседних блоков: юнит-экономика читает
    # сдвинутые строки, чеки книги — тоже (это проверяет паритет-тест).
    assert str(template["G9"].value) == "=E62"
    assert str(template["G21"].value) == "=E70"


def test_the_queue_price_multiplier_carries_the_phase_indexation():
    """Индексация очередей — множителем к сдвигу старта, как в движке:
    книга вела годовую инфляцию от даты базы цен и индексировала даже
    первую очередь — на +12% против движка."""
    phasing = {
        "enabled": True, "phase_count": 2,
        "phases": [{"start_offset_months": 0, "construction_months": 24},
                   {"start_offset_months": 12, "construction_months": 24}],
        "products": {k: [55, 45] for k in ("apartments", "ground_commercial",
                                           "underground_parking", "storage")},
        "shared_allocation": {}, "cost_inflation_pct": 8,
        "sales_price_inflation_pct": 8,
    }
    content, _, _ = build(phasing=phasing)
    sheet = openpyxl.load_workbook(io.BytesIO(content), data_only=False)["Вводные"]

    assert sheet["S88"].value == pytest.approx(1.0)
    assert sheet["S89"].value == pytest.approx(1.08)
    assert sheet["AE88"].value == pytest.approx(0.0)
    assert sheet["AE89"].value == pytest.approx(0.0)


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
