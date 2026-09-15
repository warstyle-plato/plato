"""Самопроверки книги знают о паркинге отдельно стоящих объектов.

Числа в книге были верны: `ОБЪЕКТЫ!B33` несла выручку мест офисника, `B28` —
его CAPEX вместе с гаражом, аллокация по очередям обе величины уже разносила.
Не знали о них три СОБСТВЕННЫЕ проверки книги и строка ТЭП — и на проекте с
гаражом книга давала четыре FAIL при исправном расчёте: «Офисы: CAPEX»
59 309 против 43 432, «Выручка продуктов = CF» и «ТЭП: выручка = CF»
213 605 против 235 123, «Аллокация выручки объектов» 78 006 против 56 488.
Кричащая зря проверка хуже отсутствующей: её перестают читать, а книгу с
красными строками нельзя отдать людям.

**Почему это пережило прежний набор.** Проверка
`test_the_book_counts_the_same_parking_as_the_engine` смотрит ТОЛЬКО строки,
чьё имя начинается на «паритет», — а паритет с движком был и остался
ПРОЙДЕН: расходились не итоги, а внутренние сверки книги. Смотреть надо на ту
поверхность, на которую жалуются, поэтому здесь читаются ВСЕ строки вердикта.

Предохранитель обязателен: в умолчаниях гаража объектов нет вовсе, и без
своих вводных этот файл зеленел бы при полностью забытой книге.

Запуск: python3 -m pytest tests/test_the_book_checks_know_the_object_garage.py -q
"""

from __future__ import annotations

import copy
import io
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

import main_legacy as core  # noqa: E402


def _inputs() -> dict:
    x = dict(core.DEFAULT_INPUTS)
    x.update(offices_enabled=True,
             offices_gba_sqm=40000.0, offices_saleable_sqm=24000.0,
             offices_parking_under_spaces=300, offices_parking_over_spaces=0,
             offices_parking_guest_pct=10)
    return x


def _tep() -> dict:
    t = copy.deepcopy(core.TEP_DEFAULT)
    t["offices"].update(gns=40000, total_area=37600, saleable=24000)
    return t


def _built() -> tuple[dict, bytes]:
    x, t = _inputs(), _tep()
    result = core.calculate(core.CalcRequest(
        inputs=dict(x), tep=copy.deepcopy(t), rates=[]))
    content, _name, _report = core.build_project_workbook(
        dict(x), copy.deepcopy(t), [], None, project_name="Гараж объекта")
    return result, content


def _phasing() -> dict:
    """Две очереди: колонки продуктов КОНСОЛИДАТОР рисует только у них."""
    return {
        "enabled": True, "phase_count": 2, "phase_gap_months": 12,
        "cost_inflation_pct": 8, "sales_price_inflation_pct": 8,
        "financing_strategy": "independent",
        "phases": [{"name": f"О{i + 1}", "start_offset_months": i * 12,
                    "construction_months": 24, "products": {}} for i in range(2)],
        "products": {key: [50.0, 50.0] for key in
                     ("apartments", "ground_commercial", "underground_parking", "storage")},
        "social_objects": [],
        "discrete": {"offices": 1, "standalone_retail": 2,
                     "above_parking": 2, "sports": 2},
    }


def _phased() -> tuple[dict, bytes]:
    """Тот же проект, нарезанный на две очереди."""
    x, t = _inputs(), _tep()
    phasing = _phasing()
    bundle = core._run_authoritative_model(dict(x), copy.deepcopy(t), [], phasing)
    content, _name, _report = core.build_project_workbook(
        dict(x), copy.deepcopy(t), [], phasing,
        project_name="Гараж объекта · очереди")
    return bundle["consolidated"], content


def _evaluator(content: bytes):
    openpyxl = pytest.importorskip("openpyxl")
    from xlsx_eval import Evaluator

    sys.setrecursionlimit(400000)
    return Evaluator(openpyxl.load_workbook(io.BytesIO(content), data_only=False))


def test_the_project_actually_sells_object_places() -> None:
    """Предохранитель: нет выручки мест — остальное в файле ничего не значит."""
    result, _content = _built()
    products = {str(item["key"]): float(item.get("revenue") or 0)
                for item in (result.get("report") or {}).get("products") or []}
    assert products.get("object_parking", 0) > 1e8, (
        "у проверочного проекта нет выручки мест объекта — "
        "проверки этого файла перестали что-либо значить: " + str(sorted(products)))


def test_not_a_single_check_of_the_book_fails() -> None:
    """Все строки вердикта, а не только «Паритет»: жалуются на весь лист."""
    _result, content = _built()
    evaluator = _evaluator(content)
    checks = evaluator.workbook["ПРОВЕРКИ"]
    failed = []
    for row in range(1, 130):
        name = checks[f"A{row}"].value
        if not name:
            continue
        if evaluator.cell("ПРОВЕРКИ", f"F{row}") != "FAIL":
            continue
        failed.append(f"{name}: {evaluator.cell('ПРОВЕРКИ', f'B{row}')} "
                      f"против {evaluator.cell('ПРОВЕРКИ', f'C{row}')}")
    assert not failed, failed


def test_the_tep_revenue_carries_the_object_places() -> None:
    """Строка ТЭП объекта несёт и здание, и его гараж — иначе итог не сходится.

    Утверждение здесь про КНИГУ: её лист ТЭП обязан сойтись с её же CF —
    ровно это и расходилось. Сверка с движком стоит отдельно и грубее: у неё
    свой допуск, и она держится строками «Паритет».
    """
    result, content = _built()
    evaluator = _evaluator(content)
    tep_total = evaluator.cell("ТЭП", "G36")
    assert tep_total == pytest.approx(evaluator.cell("CF", "B6"), rel=1e-9)
    assert tep_total == pytest.approx(float(result["summary"]["revenue"]) / 1e6, rel=1e-4)


def test_the_consolidator_carries_the_object_parking_product() -> None:
    """Продукт, которого книга не умела считать, теперь стоит своей колонкой.

    Колонки продуктов КОНСОЛИДАТОР рисует только у проекта с очередями —
    поэтому здесь свои вводные с двумя очередями, а не общая фикстура.
    """
    result, content = _phased()
    evaluator = _evaluator(content)
    products = {str(item["key"]): float(item.get("revenue") or 0)
                for item in (result.get("report") or {}).get("products") or []}
    sheet = evaluator.workbook["КОНСОЛИДАТОР"]
    column = None
    for index in range(core._V4_CONSOLIDATOR_FIRST_COL, core._V4_CONSOLIDATOR_FIRST_COL + 12):
        letter = sheet.cell(row=3, column=index).column_letter
        title = sheet[f"{letter}3"].value
        if title and "Паркинг отдельно стоящих объектов" in str(title):
            column = letter
            break
    assert column, "колонки паркинга объектов на КОНСОЛИДАТОРЕ нет"
    total = evaluator.cell("КОНСОЛИДАТОР", f"{column}{core._V4_CONSOLIDATOR_TOTAL_ROW}")
    assert total == pytest.approx(products["object_parking"] / 1e6, rel=1e-6)


def test_the_build_reports_nothing_missing_for_the_garage() -> None:
    """«Книга не умеет считать выручку …» — это потеря, а не оговорка.

    Колонки продуктов рисует только проект с очередями, поэтому и здесь
    вводные с очередями: на одиночном расчёте эта строка `missing` не
    возникает вовсе, и проверка была бы зелена при забытой книге.
    """
    x, t = _inputs(), _tep()
    phasing = _phasing()
    _content, _name, report = core.build_project_workbook(
        dict(x), copy.deepcopy(t), [], phasing, project_name="Гараж объекта")
    unknown = [item for item in (report.get("missing") or [])
               if "Паркинг отдельно стоящих объектов" in item]
    assert not unknown, unknown
