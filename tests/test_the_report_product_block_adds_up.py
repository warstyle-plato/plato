"""Блок «СТРУКТУРА ПРОДУКТА» листа ОТЧЁТ сходится с движком.

«В книге в сумму ГНС считается площадь подземного паркинга, на движке это
правил, а тут нет» (владелец, 14.09.2026). Итог блока складывал под шапкой
«ГНС, м²» наземные метры квартир и подземные метры паркинга — 475 870, число,
не равное ни наземной ГНС проекта (443 701), ни строительному объёму
(601 621). Рядом в том же блоке жили ещё три потери: выручка 213 605,2 вместо
235 123,1 и 2 160 мест вместо 4 660 (гараж объекта читался мимо), ФОК не имел
строки вовсе, а у кладовых не было формул.

**Почему это пережило весь набор.** Лист ПРОВЕРКИ сверяет ТЭП с CF, аллокацию
и паритет с движком — до блока ОТЧЁТа не доходит ни одна проверка, а наши
тесты читали книгу через тот же лист. Смотреть надо на ту поверхность, на
которую жалуются.

Предохранитель обязателен: без гаража объекта и соцобъектов проверка зелена
при любом складывании.

Запуск: python3 -m pytest tests/test_the_report_product_block_adds_up.py -q
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

TOTAL = core._V4_PRODUCT_STRUCTURE_TOTAL_ROW
UNDER = core._V4_UNDER_COLUMN


def _inputs() -> dict:
    x = dict(core.DEFAULT_INPUTS)
    x.update(offices_enabled=True, offices_gba_sqm=40000.0,
             offices_saleable_sqm=24000.0,
             offices_parking_under_spaces=300, offices_parking_guest_pct=10,
             kindergarten_places=180, school_places=400,
             social_mode="Строительство")
    return x


def _tep() -> dict:
    t = copy.deepcopy(core.TEP_DEFAULT)
    t["offices"].update(gns=40000, total_area=37600, saleable=24000)
    return t


def _build(cache: bool = False) -> tuple[dict, bytes]:
    x, t = _inputs(), _tep()
    result = core.calculate(core.CalcRequest(
        inputs=dict(x), tep=copy.deepcopy(t), rates=[]))
    content, _name, report = core.build_project_workbook(
        dict(x), copy.deepcopy(t), [], None, project_name="Структура продукта",
        cache_values=cache)
    assert not report.get("missing"), report.get("missing")
    return result, content


def _built() -> tuple[dict, "object"]:
    """Значения считает наш вычислитель: в прогоне кэш книги выключен."""
    openpyxl = pytest.importorskip("openpyxl")
    from xlsx_eval import Evaluator

    result, content = _build()
    sys.setrecursionlimit(400000)
    return result, Evaluator(openpyxl.load_workbook(io.BytesIO(content), data_only=False))


def test_the_project_has_a_garage_and_social_objects() -> None:
    """Предохранитель: без них блок сходится при любом складывании."""
    result, _book = _built()
    rows = {row["key"]: row for row in result["tep"]["rows"]}
    assert rows["offices"]["parking_saleable_units"] > 0, "гараж объекта не продаётся"
    assert rows["kindergarten"]["gns"] > 0 and rows["school"]["gns"] > 0, (
        "соцобъектов нет — разница наземной ГНС не проверяется")


def test_the_block_splits_above_ground_from_underground() -> None:
    """Наземное и подземное — разными колонками, как в движке."""
    result, book = _built()
    summary = result["summary"]
    rows = {row["key"]: row for row in result["tep"]["rows"]}
    social_gns = sum(rows[key]["gns"] for key in ("kindergarten", "school", "clinic"))

    under = book.cell("ОТЧЕТ", f"{UNDER}{TOTAL}")
    assert under == pytest.approx(summary["underground_gns_sqm"], abs=2), (
        "подземная колонка не равна подземной части движка")
    above = book.cell("ОТЧЕТ", f"B{TOTAL}")
    assert above == pytest.approx(summary["project_gns_sqm"] - social_gns, abs=2), (
        "наземная колонка не равна наземной ГНС продуктов")


def test_the_block_totals_match_the_engine() -> None:
    """Выручка, продаваемая и единицы блока — те же, что у движка."""
    result, book = _built()
    products = {str(item["key"]): item for item in result["report"]["products"]}
    revenue_mln = sum(float(item["revenue"]) for item in products.values()) / 1e6
    # Утверждение здесь про КНИГУ: итог блока обязан сойтись с её же CF —
    # ровно это и расходилось на 21,5 млрд. С движком книга сверяется грубее:
    # базы ТЭП она пишет округлёнными до метра, и выручка отличается на доли
    # сотой процента — это старое и к этому блоку отношения не имеет.
    assert book.cell("ОТЧЕТ", f"E{TOTAL}") == pytest.approx(
        book.cell("CF", "B6"), rel=1e-9)
    assert book.cell("ОТЧЕТ", f"E{TOTAL}") == pytest.approx(revenue_mln, rel=1e-4)

    rows = {row["key"]: row for row in result["tep"]["rows"]}
    units = (rows["underground_parking"]["saleable_units"]
             + rows["offices"]["parking_saleable_units"])
    assert book.cell("ОТЧЕТ", f"D{TOTAL}") == pytest.approx(units, abs=1)


def test_the_construction_volume_of_the_tep_sheet_matches_the_engine() -> None:
    """Строительный объём книги включает соцобъекты и гаражи объектов."""
    result, book = _built()
    assert book.cell("ТЭП", "C36") == pytest.approx(
        result["summary"]["construction_volume_sqm"], abs=2)


def test_every_standalone_object_has_its_own_row_in_the_block() -> None:
    """ФОК в блоке есть — список продуктов не перечисляется руками."""
    _result, book = _built()
    labels = {str(book.cell("ОТЧЕТ", f"A{row}") or "")
              for row, *_rest in core._V4_PRODUCT_STRUCTURE_OBJECTS}
    assert any("ФОК" in label for label in labels), labels
    assert len(labels) == len(core._V4_PRODUCT_STRUCTURE_OBJECTS), labels


def test_the_totals_are_not_empty_in_a_viewer() -> None:
    """Пустая формула кладовых рвала кэш итогов — в просмотрщике были прочерки."""
    openpyxl = pytest.importorskip("openpyxl")
    _result, content = _build(cache=True)
    tep = openpyxl.load_workbook(io.BytesIO(content), data_only=True)["ТЭП"]
    for coord in ("C7", "C8", "C28", "C36"):
        assert tep[coord].value is not None, (
            f"ТЭП!{coord} без сохранённого значения — в просмотрщике пусто")
