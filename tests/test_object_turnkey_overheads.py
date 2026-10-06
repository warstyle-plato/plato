"""Ставка объекта — «под ключ»; резерв не начисляется на плату за ВРИ.

Решение владельца 06.10.2026. Ставка строительства отдельно стоящего объекта
(офис, ТЦ, ФОК, наземный паркинг, гараж объекта) уже включает ИРД, проект,
сети, ввод, генподряд и техзаказчика. Поэтому генподряд и техзаказчик
начисляются только на СМР ядра и соцобъекты, а не на стройку объекта: прежде
офисник получал «Основное строительство» — одно вознаграждение генподрядчика —
и «Технического заказчика» от собственной ставки «под ключ». Резерв на объект
остаётся, а на плату за смену ВРИ — нет: это известная сумма, а не смета.

Методика одна на движок и обе книги: книгу ПЛАТО v4 и книгу нежилого проекта.
Каждая проверка падает на прежней методике — это доказывают подделки ниже.

Запуск: python3 -m pytest tests/test_object_turnkey_overheads.py -q
"""

from __future__ import annotations

import copy
import io
import sys
from pathlib import Path

import openpyxl
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import main as wrapper  # noqa: E402
import nonres_workbook as nw  # noqa: E402
from xlsx_eval import Evaluator  # noqa: E402

core = wrapper.core


def _amounts(**over) -> dict[str, float]:
    x = copy.deepcopy(core.DEFAULT_INPUTS)
    x.update(offices_enabled=True)
    x.update(over)
    return core.build_operating_model(x, copy.deepcopy(core.TEP_DEFAULT))["capex_amounts"]


def test_the_object_rate_carries_no_gc_fee_and_no_technical_customer() -> None:
    """Дороже объект — генподряд и техзаказчик те же; резерв растёт на
    процент от прибавки. На прежней методике оба процента выросли бы."""
    cheap = _amounts(offices_cost_th_per_sqm=150)
    dear = _amounts(offices_cost_th_per_sqm=250)
    added = dear["offices"] - cheap["offices"]
    assert added > 0
    assert dear["gc_fee"] == pytest.approx(cheap["gc_fee"])
    assert dear["technical_supervision"] == pytest.approx(cheap["technical_supervision"])
    reserve_pct = core.DEFAULT_INPUTS["reserve_pct"] / 100
    assert dear["reserve"] - cheap["reserve"] == pytest.approx(added * reserve_pct)
    # Базы — ровно СМР ядра и соцобъекты, без объекта.
    works = dear["main_above"] + dear["main_under"] + dear["social"]
    assert dear["gc_fee"] == pytest.approx(works * core.DEFAULT_INPUTS["gc_fee_pct"] / 100)
    assert dear["technical_supervision"] == pytest.approx(
        works * core.DEFAULT_INPUTS["technical_supervision_pct"] / 100)


def test_the_reserve_ignores_the_vri_fee() -> None:
    """Плата за ВРИ меняется — резерв нет. На прежней методике резерв брал 5%
    и с платы: 2,86 млрд ₽ умолчаний давали 143 млн ₽ резерва из ниоткуда."""
    low = _amounts(land_rights_cost_mln=1000.0)
    high = _amounts(land_rights_cost_mln=3000.0)
    assert high["land_rights"] - low["land_rights"] == pytest.approx(2000e6)
    assert high["reserve"] == pytest.approx(low["reserve"])


def test_the_reserve_base_is_every_article_but_the_excluded() -> None:
    """Резерв — процент от всех статей до него, кроме списка исключений."""
    a = _amounts()
    shadow = {"reserve", "vri_interest", "vri_security", "land_rights_gross",
              "land_rights_relief"}
    base = sum(v for k, v in a.items() if k not in shadow | core.RESERVE_EXCLUDED_ARTICLES)
    assert a["land_rights"] > 0 and a["offices"] > 0
    assert a["reserve"] == pytest.approx(base * core.DEFAULT_INPUTS["reserve_pct"] / 100)
    assert core.RESERVE_EXCLUDED_ARTICLES <= core._M2_RESERVE_EXCLUDED


def test_the_object_rate_hint_says_turnkey() -> None:
    """Подпись ставки объекта говорит, что сверху ничего не начисляется."""
    for obj in core.STANDALONE_OBJECTS:
        _title, fields = core.standalone_object_group(obj)
        hints = {row[0]: row[2] for row in fields}
        assert core.OBJECT_TURNKEY_HINT in hints[obj.rate_cost], obj.key


# --- Книга ПЛАТО v4 ----------------------------------------------------------

_V4_ROWS = {27: "technical_supervision", 29: "gc_fee", 30: "reserve"}


def _v4_book():
    inputs = dict(core.DEFAULT_INPUTS, offices_enabled=True)
    tep = {key: dict(value) for key, value in core.TEP_DEFAULT.items()}
    op = core.build_operating_model(dict(inputs), copy.deepcopy(tep))
    content, _, meta = core.build_project_workbook(inputs, tep, [], None, finance_hints={})
    assert not [m for m in meta.get("missing", []) if "CAPEX" in m]
    return openpyxl.load_workbook(io.BytesIO(content), data_only=False), op["capex_amounts"]


def test_the_v4_book_counts_the_same_bases() -> None:
    """Книга v4 считает генподряд, техзаказчика и резерв на базах движка;
    вернуть шаблонную формулу — получить расхождение."""
    sys.setrecursionlimit(400000)
    book, engine = _v4_book()
    sheet = book["CAPEX"]
    for row, key in _V4_ROWS.items():
        assert "ОБЪЕКТЫ" not in sheet[f"B{row}"].value or key == "reserve"
        value = float(Evaluator(book).cell("CAPEX", f"B{row}") or 0)
        assert value == pytest.approx(engine[key] / 1e6, abs=0.05), key
    # Подделка: прежние формулы шаблона — объект в базе процентов, ВРИ в резерве.
    sheet["B29"] = sheet["B29"].value.replace(")*", "+'ОБЪЕКТЫ'!$B$96)*", 1)
    sheet["B30"] = sheet["B30"].value.replace("SUM(B16:B29)", "SUM(B15:B29)", 1)
    evaluator = Evaluator(book)
    assert float(evaluator.cell("CAPEX", "B29")) > engine["gc_fee"] / 1e6 + 1
    assert float(evaluator.cell("CAPEX", "B30")) > engine["reserve"] / 1e6 + 1


# --- Книга нежилого проекта --------------------------------------------------

def _nonres_content() -> bytes:
    x = copy.deepcopy(core.DEFAULT_INPUTS)
    t = copy.deepcopy(core.TEP_DEFAULT)
    x.update(offices_enabled=True, offices_gba_sqm=40000.0, offices_saleable_sqm=24000.0,
             offices_strategy="income", project_kind=core.PROJECT_KIND_NONRESIDENTIAL)
    t.setdefault("offices", {}).update(gns=40000.0, total_area=37600.0,
                                       useful=24000.0, saleable=24000.0)
    for key in core.MKD_PRODUCTS:
        for col in ("gns", "total_area", "useful", "saleable", "transfer", "units"):
            if key in t:
                t[key][col] = 0
    content, _, meta = core.build_project_workbook(x, t, [], {}, project_name="Офис")
    assert meta.get("nonres_book") is True and meta["missing"] == []
    return content


def _nonres_check(book) -> tuple[str, set[str], Evaluator]:
    sys.setrecursionlimit(max(sys.getrecursionlimit(), 100000))
    evaluator = Evaluator(book)
    checks = book[nw.CHECK_SHEET]
    bad = {checks[f"B{r}"].value for r in range(3, checks.max_row + 1)
           if evaluator.cell(nw.CHECK_SHEET, f"G{r}") == "РАСХОЖДЕНИЕ"}
    return evaluator.cell(nw.CHECK_SHEET, "I3"), bad, evaluator


def test_the_nonres_book_counts_the_same_bases() -> None:
    """У офисника без ядра генподряд и техзаказчик — ноль, а резерв стоит на
    стройке объекта и не видит строки платы за ВРИ; «Сверка» ПРОЙДЕНО.
    Подделка — объект обратно в базе генподряда — ловится сверкой."""
    content = _nonres_content()
    book = openpyxl.load_workbook(io.BytesIO(content))
    sheet = book[nw.COSTS_SHEET]
    rows = {sheet[f"A{r}"].value: r for r in range(1, nw.FIRST_ROW) if sheet[f"A{r}"].value}
    verdict, bad, evaluator = _nonres_check(book)
    assert verdict == nw.PASSED and not bad
    for label in ("Генподряд", "Технический заказчик"):
        assert float(evaluator.cell(nw.COSTS_SHEET, f"E{rows[label]}") or 0) == 0.0
    building = next(r for label, r in rows.items() if str(label).endswith(": здание"))
    vri_row = next(r for label, r in rows.items() if str(label).startswith("Плата за смену ВРИ"))
    reserve_base = sheet[f"B{rows['Резерв']}"].value.split("+")
    assert f"=E{building}" in reserve_base or f"E{building}" in reserve_base
    assert f"E{vri_row}" not in reserve_base and f"=E{vri_row}" not in reserve_base

    tampered = openpyxl.load_workbook(io.BytesIO(content))
    cell = tampered[nw.COSTS_SHEET][f"B{rows['Генподряд']}"]
    cell.value = cell.value + f"+E{building}"
    verdict, bad, _ = _nonres_check(tampered)
    assert verdict == nw.FAILED and "Генподряд" in bad
