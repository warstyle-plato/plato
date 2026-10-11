"""Выход гостиницы по решению владельца (08.10.2026, #653).

* оценка — EV/EBITDA, умолчание 9× с подписью происхождения;
* конец срока — удержание без сделки: выручки выхода в деньгах нет;
* стоимость на конец срока (EBITDA следующих 12 мес. × 9) входит в IRR и
  NPV как терминальная, но не в деньги: окупаемость считается без неё;
* ориентир «Отель 1» хранит метод своей книги (удержание, Гордон).

Поверхности — отчёт, тизер, PDF и книга — печатают EV/EBITDA 9× и
удержание. Каждая проверка падает на подделке.

Запуск: python3 -m pytest tests/test_hotel_exit_owner_default.py -q
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

import developaid_finance_math as fm  # noqa: E402
import developaid_hotel_strategy as hs  # noqa: E402
import hotel_presets  # noqa: E402
import hotel_workbook as hw  # noqa: E402
from test_hotel_strategy import params, plan, run  # noqa: E402

EXIT_FIELDS = ("exit_mode", "valuation", "exit_multiple")


# --- поля и движок --------------------------------------------------------------

def test_the_owner_exit_is_the_default_with_its_origin() -> None:
    f = hs.FIELD_BY_KEY
    assert f["exit_mode"].default == hs.EXIT_HOLD
    assert f["valuation"].default == hs.VALUATION_MULTIPLE
    assert f["exit_multiple"].default == 9.0
    for key in EXIT_FIELDS:
        assert "решение владельца 08.10.2026" in f[key].origin, key
    # Ставка капитализации — выбор, а не умолчание способа.
    assert not hs._is_needed(f["exit_cap_pct"], hs.effective_params(params()))


def test_a_project_without_choice_holds_and_values_at_nine_ebitda() -> None:
    r = run()
    kpi, totals = r["kpi"], r["totals"]
    assert kpi["exit_mode"] == hs.EXIT_HOLD and kpi["valuation"] == hs.VALUATION_MULTIPLE
    assert kpi["exit_value"] == pytest.approx(kpi["forward_ebitda"] * 9.0)
    assert totals["exit_revenue"] == 0 and totals["exit_cost"] == 0
    assert totals["residual_value"] == pytest.approx(kpi["exit_value"])


def test_the_residual_value_is_in_irr_and_npv_but_not_in_payback() -> None:
    r = run()
    end = r["months"].index(r["horizon_end"])
    residual = r["kpi"]["exit_value"]
    project_cash = list(r["project_cf"])
    project_cash[end] -= residual
    equity_cash = list(r["equity_cf"])
    equity_cash[end] -= residual
    # IRR и NPV — с терминальной стоимостью.
    assert r["kpi"]["irr_project"] == pytest.approx(fm.monthly_irr(r["project_cf"]))
    assert r["kpi"]["irr_project"] > (fm.monthly_irr(project_cash) or -1.0)
    assert r["kpi"]["npv_project"] == pytest.approx(fm.monthly_npv(r["project_cf"], 0.15))
    # Окупаемость — деньгами, без оценки удержания.
    assert r["kpi"]["pbp_years"] == hs.payback_years(project_cash)
    assert r["kpi"]["dpbp_years"] == hs.payback_years(project_cash, 0.15)
    assert r["kpi"]["equity_pbp_years"] == hs.payback_years(equity_cash)


def test_the_payback_check_fails_on_a_forgery() -> None:
    """Короткий срок: деньгами проект не окупается, с оценкой — окупается.
    Срок по потоку с оценкой отличался бы — проверка выше его ловит."""
    r = run(plan(params=params(hold_years=1)))
    assert r["kpi"]["pbp_years"] is None
    assert hs.payback_years(r["project_cf"]) is not None


def test_the_hotel1_preset_keeps_its_book_exit() -> None:
    """Книга Отеля 1: терминальная стоимость без сделки по Гордону (Расчеты!1641,
    1678; g = E1634, r = E1623), а не умолчание 9×."""
    values = hotel_presets.BY_KEY["hotel1"].values
    assert values["exit_mode"].value == hs.EXIT_HOLD
    assert values["valuation"].value == hs.VALUATION_GORDON
    assert values["gordon_growth_pct"].value == pytest.approx(3.9999)
    assert values["gordon_rate_pct"].value == pytest.approx(15.0)
    x = hotel_presets.apply_preset({}, "hotel1")
    assert (x["hotel_exit_mode"], x["hotel_valuation"]) == (hs.EXIT_HOLD, hs.VALUATION_GORDON)


def test_the_exit_summary_names_hold_and_multiple() -> None:
    assert hs.exit_summary(params(hold_years=10)) == (
        "Эксплуатация 10 лет, затем удержание (оценка без сделки, EV/EBITDA 9×)")
    assert hs.exit_summary(params(hold_years=15, exit_mode="sale", exit_multiple=4)) == (
        "Эксплуатация 15 лет, затем продажа по EV/EBITDA 4×")
    assert hs.exit_summary(params(valuation="cap_rate", exit_cap_pct=10.5)).endswith(
        "ставка капитализации 10,5%)")


# --- поверхности ----------------------------------------------------------------

@pytest.fixture(scope="module")
def project():
    import main as wrapper
    core = wrapper.core
    x = copy.deepcopy(core.DEFAULT_INPUTS)
    t = copy.deepcopy(core.TEP_DEFAULT)
    x["project_kind"] = "hotel"
    x = hotel_presets.apply_preset(x, "hotel1")
    # Проект без ориентира выхода: остальное — ориентир, выход — умолчание.
    for key in EXIT_FIELDS:
        x.pop("hotel_" + key, None)
        x[hotel_presets.ORIGINS_KEY].pop(key, None)
    bundle = core._run_authoritative_model(x, t, [], {})
    return core, x, t, bundle


def _strategy_rows(result: dict) -> dict:
    section = next(s for s in result["report"]["object_report"]["sections"]
                   if s["key"] == "strategy")
    return {r["label"]: r["value"] for b in section["blocks"] for r in b.get("rows") or []}


def test_the_report_prints_hold_and_nine(project) -> None:
    _, _, _, bundle = project
    rows = _strategy_rows(bundle["consolidated"])
    assert rows["Стратегия"].endswith("затем удержание (оценка без сделки, EV/EBITDA 9×)")
    assert rows["Конец срока"] == dict(hs.EXITS)[hs.EXIT_HOLD]
    assert rows["Оценка выхода"] == dict(hs.VALUATIONS)[hs.VALUATION_MULTIPLE]
    assert rows["Мультипликатор EV/EBITDA"] == 9.0
    assert "Стоимость гостиницы — оценка удержания" in rows


def _pdf_text(data: bytes) -> str:
    pypdf = pytest.importorskip("pypdf")
    text = " ".join(p.extract_text() or "" for p in pypdf.PdfReader(io.BytesIO(data)).pages)
    return " ".join(text.split())


def test_the_teaser_prints_hold_and_nine(project) -> None:
    core, x, t, bundle = project
    flat = _pdf_text(core.build_teaser_pdf(bundle, x, t, {}))
    assert "удержание (оценка без сделки, EV/EBITDA 9×)" in flat
    assert "продажа по EV/EBITDA" not in flat


def test_the_book_prints_hold_and_nine_with_origin(project) -> None:
    openpyxl = pytest.importorskip("openpyxl")
    core, x, t, _ = project
    content, _, _ = core.build_project_workbook(x, t, [], {}, project_name="Отель")
    sheet = openpyxl.load_workbook(io.BytesIO(content))[hw.INPUTS_SHEET]
    rows = {sheet[f"E{n}"].value: (sheet[f"G{n}"].value, sheet[f"H{n}"].value)
            for n in range(4, 4 + len(hs.FIELDS))}
    assert rows["Конец срока"][0] == dict(hs.EXITS)[hs.EXIT_HOLD]
    assert rows["Оценка выхода"][0] == dict(hs.VALUATIONS)[hs.VALUATION_MULTIPLE]
    assert rows["Мультипликатор EV/EBITDA"][0] == 9.0
    for label in ("Конец срока", "Оценка выхода", "Мультипликатор EV/EBITDA"):
        assert rows[label][1].startswith("умолчание: решение владельца 08.10.2026"), label


def test_the_pdf_prints_hold_and_nine(project) -> None:
    core, x, t, bundle = project
    result = core.calculate(core.CalcRequest(inputs=x, tep=t, rates=[]))
    flat = _pdf_text(core._build_developaid_pdf({
        "result": result, "inputs": x, "tep": t, "rates": [], "phasing": {},
        "scenario": "base", "project_name": "Гостиница"}))
    assert "удержание (оценка без сделки, EV/EBITDA 9×)" in flat
    assert "Удержание: оценка без сделки" in flat


def test_the_book_agrees_with_the_engine_on_hold_and_nine(tmp_path) -> None:
    pytest.importorskip("openpyxl")
    from test_hotel_workbook import _book, _evaluate
    content, _, _ = _book(hotel_hold_years=6, hotel_exit_mode="", hotel_valuation="",
                          hotel_exit_multiple="")
    verdict, bad = _evaluate(content, tmp_path)
    assert bad == [] and verdict == "ПРОЙДЕНО"
