"""One server calculation for the total/product cumulative pace and weighted price."""
from __future__ import annotations

import copy
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from market_search import contracting


def sale(month, *, product="Квартира", amount=100., area=10., units=1.):
    return {"month": month, "signed": month + "-01", "product": product,
            "amount": amount, "area": area, "units": units, "rooms": "",
            "payment_variant": "", "broker": "", "broker_fee": 0.,
            "sales_bonus_paid": 0., "escrow_paid": 0., "contract": "synthetic",
            "unit": "", "kind": "", "contract_type": "", "state": "",
            "company_buyer": False, "escrow_schedule": [], "broker_rate": None}


def summary(rows, until=None):
    return contracting.summarise({"rows": rows}, until=until)


def test_calendar_pauses_and_trailing_empty_months_are_in_both_denominators():
    result = summary([sale("2026-01"), sale("2026-03", amount=600., area=30., units=3.)], "2026-04")
    pace = result["dynamics_pace"]
    assert pace["total"] == contracting.pace_since_start(result["dynamics"], "2026-04")
    product = pace["by_product"]["Квартира"]
    assert [r["month"] for r in product] == ["2026-01", "2026-02", "2026-03", "2026-04"]
    assert [r["months_since_start"] for r in product] == [1, 2, 3, 4]
    for rows in (pace["total"], product):
        assert [r["amount"] for r in rows] == [100., 0., 600., 0.]
        assert [r["area"] for r in rows] == [10., 0., 30., 0.]
        assert [r["units"] for r in rows] == [1., 0., 3., 0.]
        assert rows[-1]["avg_amount"] == 175.
        assert rows[-1]["avg_area"] == 10.
        assert rows[-1]["avg_units"] == 1.
    assert product[1]["price"] is None and product[-1]["price"] is None
    # Weighted by sold metres: (100 + 600) / (10 + 30), not mean(10, 20).
    assert product[-1]["avg_price"] == 17.5
    assert pace["total"][-1]["avg_price_flats"] == 17.5
    # Historical monthly facts stay sparse and unchanged.
    assert [r["month"] for r in result["dynamics"]] == ["2026-01", "2026-03"]


def test_default_endpoint_is_last_source_month_and_explicit_until_is_inclusive():
    rows = [sale("2026-01"), sale("2026-03", amount=300., area=20.), sale("2026-05")]
    assert summary(rows)["dynamics_pace"]["total"][-1]["month"] == "2026-05"
    cut = summary(rows, "2026-03")["dynamics_pace"]["total"]
    assert cut[-1]["month"] == "2026-03" and cut[-1]["avg_amount"] == pytest.approx(400 / 3)


def test_each_product_starts_at_its_own_first_sale_and_aliases_are_canonical():
    rows = [sale("2026-01"), sale("2026-03", product="ПСН", amount=400., area=20.),
            sale("2026-05", product="Машиноместа", amount=200., area=0.)]
    products = summary(rows, "2026-04")["dynamics_pace"]["by_product"]
    assert products["Коммерческие площади"][-1]["months_since_start"] == 2
    assert products["Коммерческие площади"][-1]["avg_amount"] == 200.
    assert products["Квартира"][-1]["months_since_start"] == 4
    assert products["Машиноместо"] == []


@pytest.mark.parametrize("product", ["Машиноместа", "Кладовая"])
def test_unit_product_price_is_amount_per_lot_despite_missing_metres(product):
    rows = [sale("2026-01", product=product, amount=6e6, area=0., units=3.),
            sale("2026-03", product=product, amount=4e6, area=None)]
    result = summary(rows, "2026-04")
    pace = result["dynamics_pace"]["by_product"][contracting.product_name(product)]
    assert pace[-1]["avg_price"] == 2.5e6  # 10 million / 4 lots, not mean monthly prices.
    assert pace[-1]["avg_amount"] == 2.5e6 and pace[-1]["avg_units"] == 1.
    assert pace[-1]["avg_area"] is None
    assert pace[0]["price"] == 2e6 and pace[2]["price"] == 4e6
    assert pace[1]["price"] is None
    assert result["dynamics_pace"]["total"][-1]["avg_price_flats"] is None


@pytest.mark.parametrize("missing", [0., None])
def test_incomplete_area_suppresses_cumulative_metres_and_price_without_rewriting_facts(missing):
    rows = [sale("2026-01"), sale("2026-02", amount=50., area=missing),
            sale("2026-02", amount=200.)]
    original = copy.deepcopy(rows)
    result = summary(rows, "2026-04")
    product = result["dynamics_pace"]["by_product"]["Квартира"]
    assert product[0]["avg_area"] == 10. and product[0]["avg_price"] == 10.
    for r in product[1:]:
        assert r["avg_area"] is None and r["avg_price"] is None
        assert r["area_unknown_cum"] == 1.
    assert product[-1]["avg_amount"] == 87.5 and product[-1]["avg_units"] == .75
    for r in result["dynamics_pace"]["total"][1:]:
        assert r["avg_area"] is None and r["avg_price_flats"] is None
    # Existing monthly facts retain their old meaning; coverage discloses the missing lot.
    february = result["dynamics"][1]
    assert february["area"] == 10. and february["price_flats"] == 25.
    assert february["area_unknown"] == 1.
    assert rows == original


def test_missing_first_sale_area_cannot_be_repaired_by_later_known_sales():
    pace = summary([sale("2026-01", area=0.), sale("2026-02")], "2026-03")["dynamics_pace"]
    assert all(r["avg_price"] is None for r in pace["by_product"]["Квартира"])
    assert all(r["avg_price_flats"] is None for r in pace["total"])
    assert pace["total"][-1]["avg_amount"] == pytest.approx(200 / 3)


def test_unrelated_products_and_their_unknown_area_do_not_change_flat_price():
    rows = [sale("2026-01"), sale("2026-02", product="ПСН", amount=500., area=0.),
            sale("2026-03", product="Машиноместа", amount=1e6, area=None)]
    pace = summary(rows, "2026-04")["dynamics_pace"]
    assert all(r["avg_price_flats"] == 10. for r in pace["total"])
    assert pace["total"][-1]["avg_area"] is None
    assert pace["by_product"]["Квартира"][-1]["avg_price"] == 10.
    assert pace["by_product"]["Машиноместо"][-1]["avg_price"] == 1e6


def test_a_single_month_has_one_point_and_equal_monthly_and_average_values():
    result = summary([sale("2026-07", amount=300., area=20., units=2.)])
    product = result["dynamics_pace"]["by_product"]["Квартира"]
    assert len(product) == 1 and product[0]["months_since_start"] == 1
    assert product[0]["avg_amount"] == product[0]["amount"] == 300.
    assert product[0]["avg_area"] == product[0]["area"] == 20.
    assert product[0]["avg_units"] == product[0]["units"] == 2.
    assert product[0]["avg_price"] == product[0]["price"] == 15.


def test_no_data_and_cutoff_before_sales_keep_an_empty_pace():
    assert summary([])["dynamics_pace"] == {"total": [], "by_product": {}}
    assert summary([], "2026-12")["dynamics_pace"] == {"total": [], "by_product": {}}
    assert summary([sale("2026-07")], "2026-06")["dynamics_pace"] == {
        "total": [], "by_product": {"Квартира": []}}


def test_zero_amount_for_a_known_sold_area_is_a_real_zero_price():
    row = summary([sale("2026-01", amount=0.)])["dynamics_pace"]["by_product"]["Квартира"][0]
    assert row["avg_price"] == row["price"] == 0.


@pytest.mark.parametrize("until", ["2026-13", "2026-00", "2026-01-01", "not-a-month"])
def test_invalid_cutoff_is_rejected_instead_of_unbounded_calendar_expansion(until):
    with pytest.raises(ValueError, match="YYYY-MM"):
        summary([sale("2026-01")], until)


def test_upper_iso_year_does_not_expand_past_the_last_month():
    result = summary([sale("9999-12")], "9999-12")["dynamics_pace"]
    assert len(result["total"]) == 1


def test_the_existing_management_text_and_html_handle_unknown_average_area(tmp_path, monkeypatch):
    import developaid_management_report as report
    import developaid_monitor as monitor
    from test_management_report_analytics import _full

    monkeypatch.setattr(monitor, "_SNAPSHOT_DIR", tmp_path / "monitor")
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    built = _full()
    built["sales"]["pace"] = summary([sale("2026-01", area=0.)], "2026-02")["dynamics_pace"]["total"]
    assert "в среднем в месяц: —, лотов" in report.render_text(built)
    assert "pace-average" in report.render_html(built)
