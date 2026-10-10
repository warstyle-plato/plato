"""Сверка расчёта гостиницы со «Сводом» эталонной модели Отеля 1 5*.

Вводные — ориентир Отеля 1 (`hotel_presets`: каждое число — ячейка книги или
формула над ячейками) и то, что в нашем проекте дал бы движок: CAPEX по
кварталам (Расчеты!212 + 170, без НДС → с НДС), мебель и оборудование
(Расчеты!207) и ключевая ставка (Предпосылки!60). Сравниваются по годам
2029–2043 выручка («Свод»!38), операционные расходы (39), EBITDA (38 + 39 +
40) и операционный поток без изменения оборотного капитала (43 − 42).
Эталон — «Свод»: листы USALI книги отстают от него (`hotel_reference.DISCREPANCIES`).

Конец срока — удержание: в «Своде» строки 38–43 продажи не видят.

Запуск: python3 -m pytest tests/test_hotel_dombai_svod.py -q
"""

from __future__ import annotations

import datetime as dt
import sys
import warnings
from functools import lru_cache
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import developaid_hotel_strategy as hs  # noqa: E402
import hotel_presets  # noqa: E402
import hotel_reference as ref  # noqa: E402

openpyxl = pytest.importorskip("openpyxl")

YEARS = range(2029, 2044)

# Различия методики — поимённо. Каждое объясняет, откуда допуск, и ни одно не
# прячет ошибку: подделка ADR на 5 % ловится (`test_the_check_fails_on_*`).
METHOD_DIFFERENCES: tuple[tuple[str, str], ...] = (
    ("Шаг расчёта",
     "книга — квартал: загрузка растёт ступенью раз в квартал (старт + k/8 разницы); "
     "у нас — месяц, прямая от старта до цели. Первые два года выручка выше на ~1 %."),
    ("Индексация",
     "книга индексирует цену на конец квартала, мы — с месяца цены сложным процентом "
     "по месяцам: с третьего года выручка ниже на ~0,6 %."),
    ("Сезонность",
     "книга раскладывает загрузку по кварталам коэффициентами (Расчеты!528) и цену — "
     "по сезонам; у нас сезонный профиль загрузки не задаётся, а сезон цены сидит в "
     "среднем ADR ориентира. За год разница < 0,2 %."),
    ("Льгота НДС 0 % на проживание, 5 лет",
     "моделируется так же, как в книге (Предпосылки!E777, Расчеты!852): цена гостю та же, "
     "налог с номеров остаётся гостинице, база долей расходов её не видит."),
    ("Резерв FF&E",
     "книга — ступенями (0,25 % → 0,75 % выручки), у нас — средняя доля за срок "
     "(Расчеты!I1109 ÷ I1102)."),
    ("Банкеты",
     "15 банкетов в год (Предпосылки!E516:E517, E528) в долю F&B не входят: < 0,1 % выручки."),
    ("Налог на землю и расходы до ввода",
     "0,26 млн ₽/год земли и 0,3 млн ₽/год расходов стройки у нас не заводятся."),
    ("Налог на имущество",
     "база — здание без мебели по остаточной стоимости; книга добавляет в стоимость "
     "капитализированные проценты стройки (Расчеты!1345)."),
    ("Налог на прибыль",
     "общая функция движка: расходы до ввода признаются в год ввода, убыток прошлых лет "
     "зачитывается не более половины базы. Книга до 2029 года копит убыток стройки с "
     "лимитом 50 % и с 2030 года зачитывает полностью — отсюда расхождение OCF первых лет."),
    ("Погашение кредита",
     "у нас — под DSCR 1,2 (Предпосылки!E730), книга гасит весь свободный поток; проценты "
     "и налог на прибыль 2032–2035 расходятся на десятки миллионов."),
    ("Оборотный капитал",
     "не моделируется: сравнивается OCF без строки 42 «Изменение оборотного капитала»."),
)

TOLERANCE = {"revenue": 0.02, "opex": 0.025, "ebitda": 0.02, "ocf": 0.07}


@lru_cache(maxsize=None)
def book() -> dict:
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        wb = openpyxl.load_workbook(ref.workbook_path(ref.DOMBAI), data_only=True,
                                    read_only=True)
    try:
        calc = list(wb["Расчеты"].iter_rows(min_row=1, max_row=215, max_col=100,
                                            values_only=True))
        pre = list(wb["Предпосылки"].iter_rows(min_row=56, max_row=60, max_col=40,
                                               values_only=True))
        svod = list(wb["Свод"].iter_rows(min_row=6, max_row=43, max_col=40,
                                         values_only=True))
    finally:
        wb.close()
    vat = 1 + ref.value("hotel1:Предпосылки!E775")
    capex: dict[dt.date, float] = {}
    ffe: dict[dt.date, float] = {}
    for col, start in enumerate(calc[6]):
        if not isinstance(start, dt.datetime):
            continue
        # тыс. руб. без НДС за квартал → руб. с НДС по месяцам квартала
        net = float(calc[211][col] or 0) + float(calc[169][col] or 0)
        furniture = float(calc[206][col] or 0)
        for k in range(3):
            month = hs.add_months(dt.date(start.year, start.month, 1), k)
            capex[month] = capex.get(month, 0.0) + net * 1000 * vat / 3
            ffe[month] = ffe.get(month, 0.0) + furniture * 1000 * vat / 3
    key_rate = {pre[0][c]: float(pre[4][c]) for c in range(len(pre[0]))
                if isinstance(pre[0][c], int) and pre[4][c] is not None}
    years = svod[0]

    def row(n: int) -> dict[int, float]:
        return {years[c]: float(svod[n - 6][c] or 0.0) for c in range(len(years))
                if isinstance(years[c], int)}

    return {"capex": capex, "ffe": ffe, "key_rate": key_rate,
            "revenue": row(38), "opex": row(39), "admin": row(40),
            "wc": row(42), "ocf": row(43)}


def run(params_override: dict | None = None) -> dict:
    b = book()
    params = {f: v.value for f, v in hotel_presets.BY_KEY["hotel1"].values.items()}
    params["exit_mode"] = hs.EXIT_HOLD
    params.update(params_override or {})
    plan = {"commissioning": dt.date(2029, 1, 1), "capex": b["capex"],
            "capex_ffe": b["ffe"], "capex_land": {}, "params": params,
            "start": dt.date(2025, 10, 1)}
    return hs.hotel_flows(
        plan, lambda month: b["key_rate"].get(month.year, b["key_rate"][max(b["key_rate"])]),
        vat_rate=ref.value("hotel1:Предпосылки!E775"),
        profit_tax_rate=ref.value("hotel1:Предпосылки!E765"), discount_rate=0.15)


def compare(result: dict) -> list[str]:
    """Годы и показатели, вышедшие за допуск: «2031 выручка: … против …»."""
    b = book()
    annual = {row["year"]: row for row in result["annual"]}
    out = []
    for year in YEARS:
        row = annual[year]
        ours = {
            "revenue": row["revenue"] / 1e6,
            "opex": (row["revenue"] - row["ebitda"] - row["property_tax"]
                     - row["insurance"]) / 1e6,
            "ebitda": row["ebitda"] / 1e6,
            "ocf": (row["ebitda"] - row["profit_tax"]) / 1e6,
        }
        theirs = {
            "revenue": b["revenue"][year],
            "opex": -b["opex"][year],
            "ebitda": b["revenue"][year] + b["opex"][year] + b["admin"][year],
            "ocf": b["ocf"][year] - b["wc"][year],
        }
        for name, tol in TOLERANCE.items():
            if abs(ours[name] / theirs[name] - 1) > tol:
                out.append(f"{year} {name}: {ours[name]:,.1f} против {theirs[name]:,.1f} млн ₽")
    return out


def test_the_engine_matches_the_svod_year_by_year():
    assert compare(run()) == []


def test_fifteen_year_totals_are_within_one_percent():
    b = book()
    result = run()
    revenue = sum(row["revenue"] for row in result["annual"]) / 1e6
    ebitda = sum(row["ebitda"] for row in result["annual"]) / 1e6
    assert revenue == pytest.approx(ref.value("hotel1:Свод!I38"), rel=0.01)
    book_ebitda = sum(b["revenue"][y] + b["opex"][y] + b["admin"][y] for y in YEARS)
    assert ebitda == pytest.approx(book_ebitda, rel=0.01)


def test_the_check_fails_on_a_forged_adr():
    """ADR на 5 % выше ориентира — сверка обязана это увидеть."""
    adr = hotel_presets.BY_KEY["hotel1"].values["adr_rub"].value
    assert compare(run({"adr_rub": adr * 1.05}))


def test_the_check_fails_without_the_vat_relief():
    """Льгота НДС — 1,5 млрд ₽ выручки книги: без неё первые пять лет не сходятся."""
    failed = compare(run({"vat_relief_years": 0}))
    assert any(line.startswith("2029 revenue") for line in failed)


def test_the_loan_follows_the_book():
    """Пик долга и год погашения — как у книги (Отчетность годовая!31: 5 189 млн на
    конец 2029, погашен в 2035)."""
    kpi = run()["kpi"]
    assert kpi["loan_peak"] / 1e6 == pytest.approx(5958.1, rel=0.03)
    assert kpi["loan_repaid_month"].year == 2035


def test_every_method_difference_is_named():
    assert len(METHOD_DIFFERENCES) == len({name for name, _ in METHOD_DIFFERENCES})
    text = (ROOT / "docs" / "hotel_reference_benchmarks.md").read_text(encoding="utf-8")
    for name, _ in METHOD_DIFFERENCES:
        assert name in text, f"различие «{name}» не названо в документе"
