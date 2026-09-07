"""Сводный налог раздаётся очередям ПО ГОДАМ — и движок, и книга.

Очереди — один налогоплательщик (решение владельца, 24.08.2026), поэтому
налог считается один раз на своде, а строкам очередей достаётся его доля.
Мера этой доли не произвольна: налоговый период по налогу на прибыль это
календарный год (ст. 285 НК), база считается нарастающим итогом с начала
периода (п. 7 ст. 274), а месяц объектом налогообложения не является вовсе.

Мер было две, и обе неверны. Книга делила налог долей положительных МЕСЯЦЕВ,
движок — суммой прибыльных ЛЕТ за весь горизонт: и та и другая приписывали
очереди налог за периоды, когда проект не был должен бюджету ничего. На
четырёх очередях с шагом 18 месяцев старая мера движка ошибалась на 361 млн ₽
в строке очереди при совпадающем итоге.

Свёртка до РВЭ обязательна: всё, что признано до первого облагаемого месяца,
приходит в ГОД этого месяца — так считает сама `_profit_tax_schedule`. Без
неё «раздача по календарным годам» даёт на контрольном проекте 770 млн вместо
1 847 и выглядит при этом посчитанной.

Запуск: python3 -m pytest tests/test_the_consolidated_tax_is_shared_year_by_year.py -q
"""

from __future__ import annotations

import io
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import main_legacy as core  # noqa: E402


QUEUES, GAP, BUILD = 4, 18, 18


def _scenario() -> tuple[dict, dict, dict]:
    """Очереди прибыльны в РАЗНЫЕ облагаемые годы — там и живёт разница.

    Горизонт держится внутри 103 месяцев намеренно: сетка книги — 120 столбцов,
    и на более длинном проекте она обрезает выручку, а не считает иначе.
    """
    inputs = dict(core.DEFAULT_INPUTS)
    inputs.update(apartment_price_th=650, commercial_price_th=650,
                  parking_price_th=5000, purchase_price_mln=6000)
    tep = {key: dict(value) for key, value in core.TEP_DEFAULT.items()}
    phasing = {
        "enabled": True, "phase_count": QUEUES, "phase_gap_months": GAP,
        "phases": [{"name": f"О{index + 1}",
                    "start_offset_months": GAP * index,
                    "construction_months": BUILD} for index in range(QUEUES)],
        "social_objects": [],
        "discrete": {"offices": QUEUES, "standalone_retail": QUEUES,
                     "above_parking": QUEUES},
    }
    return inputs, tep, phasing


@pytest.fixture(scope="module")
def phased():
    inputs, tep, phasing = _scenario()
    return core.calculate_phased(core.PhasedCalcRequest(
        inputs=inputs, tep=tep, phasing=phasing))


def _base(row: dict) -> float:
    return (float(row.get("taxable_margin", 0.0) or 0.0)
            - float(row.get("financing_tax_deduction", 0.0) or 0.0))


def _tax_by_year(finance: dict) -> dict[int, float]:
    years: dict[int, float] = {}
    for row in finance["rows"]:
        tax = float(row.get("profit_tax", 0.0) or 0.0)
        if tax:
            year = int(str(row["month"])[:4])
            years[year] = years.get(year, 0.0) + tax
    return years


def test_the_tax_falls_in_several_years_and_the_queues_differ(phased) -> None:
    """Предохранитель самого набора.

    Подкрути кто-нибудь вводные так, что весь налог ляжет в один год или
    очереди станут прибыльны в одни и те же годы, — и всё ниже продолжит
    зеленеть на любой из трёх мер, ничего не проверяя. Ровно так прожил
    разрыв в 3 332 млн: ни один прогон не доходил до убыточной очереди.
    """
    years = _tax_by_year(phased["consolidated"]["finance"])
    assert len(years) >= 3, f"налог должен лечь в разные годы, а лёг в {years}"
    bases = core._phase_tax_bases(
        [phase["result"] for phase in phased["phases"]],
        phased["consolidated"]["finance"]["first_taxable_month"])
    profitable = [frozenset(year for year, value in base.items() if value > 0)
                  for base in bases]
    assert len(set(profitable)) > 1, "очереди прибыльны в одни и те же годы"


def test_the_queue_rows_add_up_to_the_consolidated_tax(phased) -> None:
    """Раздача ничего не теряет: сумма строк равна своду."""
    total = float(phased["consolidated"]["summary"]["profit_tax"])
    rows = sum(float(row.get("profit_tax") or 0.0) for row in phased["comparison"])
    assert total > 0, "проверять нечего: налога на этом проекте нет"
    assert rows == pytest.approx(total, rel=1e-9)


def test_the_share_is_the_year_by_year_one_not_the_horizon_total(phased) -> None:
    """Мера — год, а не сумма прибыльных лет за весь горизонт.

    Прежняя мера давала очереди долю налога тех лет, в которых её собственной
    базы не было вовсе. Здесь она и её ответ считаются рядом: тест валится,
    если движок вернулся к горизонтной мере, и валится, если обе меры вдруг
    совпали, — тогда он ничего не проверяет.
    """
    finance = phased["consolidated"]["finance"]
    total = float(phased["consolidated"]["summary"]["profit_tax"])
    bases = core._phase_tax_bases(
        [phase["result"] for phase in phased["phases"]],
        finance["first_taxable_month"])
    weights = [sum(value for value in base.values() if value > 0) for base in bases]
    spread = sum(weights)
    horizon = [total * weight / spread for weight in weights]

    expected = [0.0] * len(bases)
    for year, tax in _tax_by_year(finance).items():
        positive = [max(base.get(year, 0.0), 0.0) for base in bases]
        share = sum(positive)
        assert share > 0, f"в {year} году базы нет — проверяется не та ветка"
        for index, value in enumerate(positive):
            expected[index] += tax * value / share

    actual = [float(row.get("profit_tax") or 0.0) for row in phased["comparison"]]
    gap = max(abs(a - b) for a, b in zip(horizon, expected))
    assert gap > 1e6, "меры совпали — проект не различает их, тест бесполезен"
    for got, want in zip(actual, expected):
        assert got == pytest.approx(want, rel=1e-9)


def test_everything_before_the_gate_lands_in_the_year_of_the_gate() -> None:
    """Отсрочка до РВЭ свёрнута в год РВЭ — так же, как её сворачивает налог.

    Без свёртки база очереди живёт в годах до первого РВЭ, в которых налога
    не было; наивная раздача «по календарному году» отдаёт очереди 770 млн
    там, где верно 1 847, и выглядит посчитанной.
    """
    rows = [{"month": "2028-05-01", "taxable_margin": 100.0,
             "financing_tax_deduction": 10.0},
            {"month": "2030-09-01", "taxable_margin": 50.0,
             "financing_tax_deduction": 0.0}]
    bases = core._phase_tax_bases([{"finance": {"rows": rows}}], "2030-07-01")
    assert bases == [{2030: 140.0}], bases
    # Без гейта каждая строка остаётся в своём календарном году.
    assert core._phase_tax_bases([{"finance": {"rows": rows}}], None) == [
        {2028: 90.0, 2030: 50.0}]


def test_the_workbook_shares_the_tax_the_same_way(phased) -> None:
    """Книга считает ту же раздачу — методику меняют в двух местах.

    Ставку ПФ однажды правили только в движке, и книга полгода считала
    по-своему. Здесь сверяются строки очередей, а не итог: итог сходился и у
    книги со старой мерой.
    """
    openpyxl = pytest.importorskip("openpyxl")
    from xlsx_eval import Evaluator

    sys.setrecursionlimit(400000)
    inputs, tep, phasing = _scenario()
    content, _, meta = core.build_project_workbook(
        inputs, tep, [], phasing, project_name="Раздача налога по годам")
    assert meta["missing"] == []
    evaluator = Evaluator(openpyxl.load_workbook(io.BytesIO(content)))
    book_total = evaluator.cell("КОНСОЛИДАТОР", "K8")
    engine_total = phased["consolidated"]["summary"]["profit_tax"] / 1e6
    assert book_total == pytest.approx(engine_total, rel=0.005), (
        f"свод: книга {book_total:,.1f} против движка {engine_total:,.1f}")
    for index, row in enumerate(phased["comparison"]):
        book = evaluator.cell("КОНСОЛИДАТОР", f"K{4 + index}")
        engine = float(row.get("profit_tax") or 0.0) / 1e6
        assert book == pytest.approx(engine, abs=max(1.0, engine * 0.01)), (
            f"{row['name']}: книга {book:,.1f} против движка {engine:,.1f}")
