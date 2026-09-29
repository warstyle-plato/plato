"""Выкуп ЗУ/ОКС у третьих лиц — своя статья CAPEX, а не цена входа.

Решение владельца (29.09.2026) по вопросу методики PR #584: выкуп у третьих
лиц — отдельная строка «Расходов» с графиком платежей до РнС. Цену входа
(`purchase_price_mln`) выкупом больше не нагружаем; денежная нагрузка КРТ
читает ту же статью. Проект не из КРТ: вводная пуста → статья ноль, эталоны не
двигаются.

Запуск: python3 -m pytest tests/test_land_buyout_is_its_own_article.py -q
"""

from __future__ import annotations

import io
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

import main_legacy as core  # noqa: E402
from auction_search import krt_contour_objects as contour  # noqa: E402
from auction_search import krt_investment_score  # noqa: E402
from test_book_interest_horizon_follows_the_engine import BASE, tep_of_a_real_project  # noqa: E402

BUYOUT = 350.0
LABEL = "Выкуп ЗУ/ОКС у третьих лиц"


def _model(**overrides):
    return core.build_operating_model({**BASE, **overrides}, tep_of_a_real_project(), [])


def test_the_engine_pays_it_before_the_permit_without_reserve_or_entry_price():
    base, with_buyout = _model(), _model(land_buyout_mln=BUYOUT)
    amounts = with_buyout["capex_amounts"]
    assert amounts["land_buyout"] == pytest.approx(BUYOUT * 1e6)
    # Резерв стройки на приобретение не начисляется, цена входа не меняется.
    assert amounts["reserve"] == pytest.approx(base["capex_amounts"]["reserve"])
    assert amounts.get("purchase", 0.0) == pytest.approx(base["capex_amounts"].get("purchase", 0.0))
    # Весь выкуп — в месяцах до РнС.
    schedule = with_buyout["capex_by_article"]["land_buyout"]
    before = sum(v for m, v in schedule.items() if m < with_buyout["permit"])
    assert before == pytest.approx(BUYOUT * 1e6, rel=1e-9)
    assert core._MONTHLY_CAPEX_LABELS["land_buyout"] == LABEL


def test_an_empty_input_is_a_zero_article():
    assert _model()["capex_amounts"]["land_buyout"] == 0.0


def test_the_book_and_the_engine_agree_on_the_buyout():
    openpyxl = pytest.importorskip("openpyxl")
    from xlsx_eval import Evaluator

    x = {**BASE, "land_buyout_mln": BUYOUT}
    content, _, _ = core.build_project_workbook(x, tep_of_a_real_project(), [], {},
                                                project_name="П")
    wb = openpyxl.load_workbook(io.BytesIO(content))
    assert wb["CAPEX"]["A39"].value == LABEL
    sys.setrecursionlimit(400000)
    ev = Evaluator(wb)
    assert ev.cell("CAPEX", "B39") == pytest.approx(BUYOUT, rel=1e-6)
    # Паритет книги с движком по CAPEX, БРИДЖу и прибыли — с выкупом внутри.
    ws = wb["ПРОВЕРКИ"]
    checked = 0
    for row in range(60, 100):
        name = str(ws.cell(row, 1).value or "")
        if "аритет" not in name.lower():
            continue
        fact = ev.cell("ПРОВЕРКИ", f"B{row}")
        expected, tolerance = ws.cell(row, 3).value, ws.cell(row, 5).value
        if expected is None or tolerance is None:
            continue
        assert abs(float(fact) - float(expected)) <= float(tolerance), (name, fact, expected)
        checked += 1
    assert checked >= 6


def test_queues_share_the_buyout_once():
    inputs = {**BASE, "land_buyout_mln": BUYOUT}
    bundle = core.calculate_phased(core.PhasedCalcRequest(
        inputs=dict(inputs), tep=tep_of_a_real_project(), rates=[],
        phasing={"enabled": True, "phase_count": 2, "phase_gap_months": 0}))
    paid = 0.0
    for phase in bundle["phases"]:
        costs = ((phase.get("result") or {}).get("monthly") or {}).get("costs") or []
        paid += sum(float(c.get("total") or 0) for c in costs if c.get("key") == "land_buyout")
    assert paid == pytest.approx(BUYOUT * 1e6, rel=1e-6)


def _bundle():
    inputs = {**BASE, "land_buyout_mln": BUYOUT}
    return inputs, core._run_authoritative_model(inputs, tep_of_a_real_project(), [], {})


def test_the_report_names_the_article_on_its_own_bases():
    _inputs, bundle = _bundle()
    rows = bundle["consolidated"]["report"]["expense_structure"]
    row = next(item for item in rows if item["label"] == LABEL)
    assert row["value"] == pytest.approx(BUYOUT * 1e6)
    # Удельные — на те же базы, что подписаны в таблице отчёта.
    summary = bundle["consolidated"]["summary"]
    assert row["per_gns_th"] == pytest.approx(
        BUYOUT * 1e6 / float(summary["project_gns_sqm"]) / 1000, rel=1e-6)


def test_the_print_names_the_article():
    pytest.importorskip("reportlab", reason="reportlab нужен только для PDF")
    from market_search.krt_requirements import pdf_text

    inputs, bundle = _bundle()
    pdf = core._build_developaid_pdf({"result": bundle["consolidated"], "project_name": "П",
                                      "inputs": inputs, "tep": tep_of_a_real_project()})
    assert LABEL in pdf_text(pdf)


def test_the_krt_estimate_fills_the_input_and_names_its_origin():
    view = {"available": True, "amount_mln": 180.0, "paid_count": 3, "moscow_zero_count": 1,
            "unknown_numbers": []}
    out = contour.apply_buyout({"land_buyout_mln": 0.0}, view)
    assert out["land_buyout_mln"] == 180.0
    assert "не цена сделки" in out["_land_buyout_source"]["by"]
    assert "у Москвы — 0" in out["_land_buyout_source"]["by"]
    assert not out["_land_buyout_source"]["warn"]


def test_an_unknown_owner_is_a_warning_with_the_list_not_a_zero():
    view = {"available": False, "known_paid_mln": 180.0, "paid_count": 3,
            "unknown_numbers": ["77:05:0001001:11"], "reason": "Выкуп не собран полностью"}
    out = contour.apply_buyout({}, view)
    marker = out["_land_buyout_source"]
    assert out["land_buyout_mln"] == 180.0, "в сумму — только доказанные"
    assert "77:05:0001001:11" in marker["warn"] and "не определён" in marker["warn"]
    assert marker["unknown"] == ["77:05:0001001:11"]
    # Пока ЕГРН дочитывается — вводная не трогается вовсе.
    assert contour.apply_buyout({"land_buyout_mln": 5.0}, {"pending": True}) == {"land_buyout_mln": 5.0}


def test_a_manual_buyout_is_not_overwritten_and_wins_in_the_burden():
    view = {"available": True, "amount_mln": 180.0, "paid_count": 3}
    manual = contour.apply_buyout({"land_buyout_mln": 90.0}, view)
    assert manual["land_buyout_mln"] == 90.0 and "_land_buyout_source" not in manual
    assert "вручную" in manual["_land_buyout_source_skipped"]["reason"]
    edited = {"land_buyout_mln": 95.0,
              "_land_buyout_source": {"value": 180.0, "kind": "krt_contour", "by": "контур"}}
    assert contour.apply_buyout(edited, view)["land_buyout_mln"] == 95.0
    auto = contour.apply_buyout({}, view)
    assert contour.apply_buyout(auto, {**view, "amount_mln": 200.0})["land_buyout_mln"] == 200.0
    # Денежная нагрузка читает ту же статью: ручное — сильнее, контурное — её же число.
    assert krt_investment_score._manual_buyout_mln(manual) == 90.0
    assert krt_investment_score._manual_buyout_mln(auto) is None


def test_the_inputs_page_names_the_origin_and_the_warning():
    from page_blocks import run_json

    assert any(field[0] == "land_buyout_mln" for group in core.PAGE_FIELD_GROUPS
               for field in group[1]), "поля выкупа нет на странице"
    out = run_json(
        "let inputs={land_buyout_mln:180,_land_buyout_source:{value:180,"
        "by:'кадастровая стоимость, не цена сделки: 3 объектов не Москвы',"
        "warn:'собственник не определён у 1 объектов — в сумму не вошли: 77:05:0001001:11',"
        "kind:'krt_contour'}};",
        "const a=classFieldUnitText('land_buyout_mln','млн ₽');"
        "inputs.land_buyout_mln=90;"
        "const b=classFieldUnitText('land_buyout_mln','млн ₽');"
        "console.log(JSON.stringify([a,b]));")
    assert "не цена сделки" in out[0] and "77:05:0001001:11" in out[0]
    assert out[1] == "млн ₽", "исправленное руками — уже без подписи контура"
