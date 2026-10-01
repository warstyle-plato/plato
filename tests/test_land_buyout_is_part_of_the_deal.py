"""Выкуп ЗУ/ОКС у третьих лиц — строка стоимости сделки, рядом с ценой участка.

Решение владельца (29.09.2026) по вопросу методики PR #584: «при переносе в
DevelopAid из расчёта КРТ эти суммы выкупа должны идти в стоимость сделки».
Стоимость сделки = цена участка/права + выкуп; выкуп платится графиком покупки,
входит в лимит БРИДЖа той частью, что до РнС, из базы НДС вычитается, как
покупка. Проект не из КРТ: вводная пуста, числа не меняются.

Запуск: python3 -m pytest tests/test_land_buyout_is_part_of_the_deal.py -q
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

PRICE, BUYOUT = 700.0, 350.0
LABEL = "Выкуп ЗУ/ОКС у третьих лиц"


def _inputs(**overrides):
    return {**BASE, "purchase_price_mln": PRICE, **overrides}


def _model(**overrides):
    return core.build_operating_model(_inputs(**overrides), tep_of_a_real_project(), [])


def test_the_field_lives_in_the_deal_block():
    deal = next(group for group in core.PAGE_FIELD_GROUPS if group[0] == "Сделка и сроки")
    keys = [field[0] for field in deal[1]]
    assert keys.index("land_buyout_mln") == keys.index("purchase_price_mln") + 1
    assert core.DEFAULT_INPUTS["land_buyout_mln"] == 0.0


def test_the_buyout_is_paid_by_the_deal_schedule():
    schedule = "40%@0; 60%@6"
    base = _model(purchase_schedule=schedule)
    with_buyout = _model(purchase_schedule=schedule, land_buyout_mln=BUYOUT)
    before = base["capex_by_article"]["purchase"]
    after = with_buyout["capex_by_article"]["purchase"]
    assert sum(after.values()) == pytest.approx((PRICE + BUYOUT) * 1e6)
    # Та же пропорция графика: каждый платёж вырос в (цена + выкуп) / цена.
    for month, amount in before.items():
        assert after[month] == pytest.approx(amount * (PRICE + BUYOUT) / PRICE)
    info = with_buyout["purchase_schedule"]
    assert (info["price_mln"], info["buyout_mln"], info["total_mln"]) == (PRICE, BUYOUT, PRICE + BUYOUT)
    # Строительный CAPEX и резерв выкупом не задеты.
    assert with_buyout["capex_amounts"]["reserve"] == pytest.approx(base["capex_amounts"]["reserve"])
    assert "land_buyout" not in with_buyout["capex_amounts"]


def test_without_a_price_the_buyout_follows_the_deal_date():
    op = _model(purchase_price_mln=0.0, land_buyout_mln=BUYOUT)
    assert sum(op["capex_by_article"]["purchase"].values()) == pytest.approx(BUYOUT * 1e6)


def test_the_bridge_limit_takes_the_buyout_paid_before_the_permit():
    x = _inputs()
    base = core._run_authoritative_model(x, tep_of_a_real_project(), [], {})
    more = core._run_authoritative_model({**x, "land_buyout_mln": BUYOUT},
                                         tep_of_a_real_project(), [], {})
    limit = lambda b: b["consolidated"]["finance"]["calculated_bridge_limit"]  # noqa: E731
    assert limit(more) - limit(base) == pytest.approx(BUYOUT * 1e6, rel=1e-6)
    deal = more["consolidated"]["deal"]
    assert (deal["price_mln"], deal["buyout_mln"], deal["total_mln"]) == (PRICE, BUYOUT, PRICE + BUYOUT)
    group = next(item for item in more["consolidated"]["report"]["expense_structure"]
                 if item["label"] == "Цена приобретения")
    assert group["value"] == pytest.approx((PRICE + BUYOUT) * 1e6)


def test_an_empty_buyout_changes_nothing():
    assert _model()["capex_by_article"]["purchase"] == _model(land_buyout_mln=0.0)["capex_by_article"]["purchase"]


def test_the_book_and_the_engine_agree_on_the_deal():
    openpyxl = pytest.importorskip("openpyxl")
    from xlsx_eval import Evaluator

    x = _inputs(land_buyout_mln=BUYOUT)
    content, _, missing = core.build_project_workbook(x, tep_of_a_real_project(), [], {},
                                                      project_name="П")
    assert not [m for m in missing.get("missing", []) if "выкуп" in m.lower()], missing
    wb = openpyxl.load_workbook(io.BytesIO(content))
    assert wb["Параметры модели"]["E16"].value == LABEL
    assert wb["ОТЧЕТ"]["A33"].value == "Покупка: участок + выкуп ЗУ/ОКС"
    sys.setrecursionlimit(400000)
    ev = Evaluator(wb)
    assert ev.cell("CAPEX", "B14") == pytest.approx(PRICE + BUYOUT, rel=1e-6)
    assert ev.cell("ОТЧЕТ", "B33") == pytest.approx(PRICE + BUYOUT, rel=1e-6)
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


def test_queues_split_the_buyout_with_the_price():
    x = _inputs(land_buyout_mln=BUYOUT)
    bundle = core.calculate_phased(core.PhasedCalcRequest(
        inputs=dict(x), tep=tep_of_a_real_project(), rates=[],
        phasing={"enabled": True, "phase_count": 2, "phase_gap_months": 0}))
    deal = bundle["consolidated"]["deal"]
    assert deal["buyout_mln"] == pytest.approx(BUYOUT, rel=1e-6)
    assert deal["total_mln"] == pytest.approx(PRICE + BUYOUT, rel=1e-6)


def test_the_key_economics_rows_name_both_lines_and_the_total():
    x = _inputs(land_buyout_mln=BUYOUT)
    bundle = core._run_authoritative_model(x, tep_of_a_real_project(), [], {})
    rows = core._pdf_entry_cost_rows(bundle["consolidated"],
                                     bundle["consolidated"]["report"]["expense_structure"])
    labels = [row[0] for row in rows]
    assert labels[:3] == ["Цена участка / права",
                          "Выкуп ЗУ/ОКС у третьих лиц (кадастровая стоимость, не цена сделки)",
                          "Стоимость сделки"]


def test_the_print_names_the_buyout():
    pytest.importorskip("reportlab", reason="reportlab нужен только для PDF")
    from market_search.krt_requirements import pdf_text

    x = _inputs(land_buyout_mln=BUYOUT)
    bundle = core._run_authoritative_model(x, tep_of_a_real_project(), [], {})
    pdf = core._build_developaid_pdf({"result": bundle["consolidated"], "project_name": "П",
                                      "inputs": x, "tep": tep_of_a_real_project()})
    assert "Выкуп ЗУ/ОКС у третьих лиц" in pdf_text(pdf)


def test_the_krt_estimate_fills_the_deal_line_and_names_its_origin():
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
    # Денежная нагрузка читает ту же строку: ручное — сильнее, контурное — её же число.
    assert krt_investment_score._manual_buyout_mln(manual) == 90.0
    assert krt_investment_score._manual_buyout_mln(auto) is None


def test_the_inputs_page_names_the_origin_and_the_warning():
    from page_blocks import run_json

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
