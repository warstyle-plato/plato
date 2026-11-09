"""The editable workbook repeats the canonical lease convention and cash plan."""
from __future__ import annotations

import datetime as dt
import io

import openpyxl
import pytest

import developaid_land_rent as rent
import v4_land_rent as book
from xlsx_eval import Evaluator


def _base():
    return {"land_right": "lease", "vri_region": "msk", "land_rent_mode": "manual",
            "land_rent_cadastral_mln": 100, "land_rent_regime_start": "2026-06-15",
            "land_rent_rates": [{"year": 1, "rate_pct": 1.5}, {"year": 2, "rate_pct": 3}],
            "land_rent_tail_rule": "repeat_last", "land_rent_first_year_relation": "regular_only"}


def _build(inputs, *, start=dt.date(2027, 1, 1), rve=dt.date(2029, 1, 1), end=None,
           shares=(1.0,), actuals=None, social_dates=None):
    end = end or rve
    canonical = rent.build(inputs, start, rve, end)
    if social_dates:
        canonical = rent.qualify_scope(canonical,social_dates)
    if actuals:
        import developaid_actuals
        schedule = {dt.date.fromisoformat(month):value for month,value in canonical["monthly"].items()}
        op = {"land_rent":canonical,"capex_by_article":{"land_rent":schedule},
              "capex":schedule,"capex_amounts":{"land_rent":sum(schedule.values())}}
        canonical = developaid_actuals.overlay(op,actuals)["op"]["land_rent"]
    w = openpyxl.Workbook()
    w.remove(w.active)
    params = w.create_sheet("Параметры модели")
    for i, value in enumerate((start, rve, end), 1):
        params.cell(i, 2, value)
    params.cell(4,2,inputs.get("land_rights_cost_mln"))
    rates = w.create_sheet("Ставки")
    capex = w.create_sheet("CAPEX")
    for p in range(4):
        cf = w.create_sheet(f"CF_{p+1}")
        total = 32 + p*34
        for i in range(180):
            col = openpyxl.utils.get_column_letter(i+4)
            rates.cell(3, i+4, rent._add_months(start.replace(day=1), i))
            capex.cell(total, i+4, "=10")
            cf.cell(17, i+4, f"='CAPEX'!{col}{total}")
            cf.cell(20, i+4, f"={col}17")
            cf.cell(21, i+4, "=(SUM($D$20:$GA$20)-0)*0.2")
    output = io.BytesIO()
    w.save(output)
    content = book.apply(output.getvalue(), inputs, canonical,
        project_start_formula="'Параметры модели'!B1", rve_formula="'Параметры модели'!B2",
        project_end_formula="MAX('Параметры модели'!B3,'Аренда ЗУ'!B15)", phase_shares=list(shares),
        hostvri_amount_formula="'Параметры модели'!B4")
    actual = openpyxl.load_workbook(io.BytesIO(content), data_only=False)
    return actual, Evaluator(actual), canonical


@pytest.mark.parametrize("changes", [
    {},
    {"land_rent_rates": [{"year": 1, "rate_pct": 1.5}], "land_rent_tail_rule": "unknown"},
    {"land_rent_rates": [{"year": 1, "rate_pct": 1.5}, {"year": 3, "rate_pct": 7}]},
    {"land_rent_first_year_relation": "full_year_in_vri", "land_rent_first_year_confirmed": True},
    {"land_rent_first_year_relation": "full_year_in_vri"},
    {"land_rent_termination_date": "2028-03-11"},
    {"land_rent_base_kind": "annual_amount", "land_rent_annual_base_mln": 1.2},
])
def test_editable_annual_accrual_matches_canonical_parts(changes):
    inputs = {**_base(), **changes}
    _, ev, canonical = _build(inputs)
    assert ev.cell(book.SHEET, "B19")*1e6 == pytest.approx(canonical["known_total"], abs=0.01)
    assert bool(ev.cell(book.SHEET, "B17")) == canonical["complete"]
    for offset in (0, 5, 12, 20, 25):
        month = rent._add_months(dt.date(2027, 1, 1), offset).isoformat()
        col = openpyxl.utils.get_column_letter(4+offset)
        assert ev.cell(book.SHEET, f"{col}4")*1e6 == pytest.approx(canonical["accrual_monthly"].get(month, 0), abs=0.01)


def test_unknown_lease_is_visible_and_preserves_legacy_numeric_totals():
    w, ev, canonical = _build({"land_right": "lease"})
    assert not canonical["complete"]
    assert ev.cell(book.SHEET, "B18") == "Не рассчитано полностью"
    assert ev.cell("CAPEX", "D145") == "Не рассчитано"
    assert ev.cell("CF_1", "D17") == 10
    assert "Плановое начисление" in ev.cell(book.SHEET, "B6")
    assert w[book.SHEET]["B9"].fill.fgColor.rgb == "FFFFF2CC"


def test_known_schedule_is_allocated_once_and_excluded_from_input_vat():
    w, ev, canonical = _build(_base(), shares=(0.3, 0.7))
    total = sum(ev.cell("CAPEX", f"B{r}") for r in book.CAPEX_ROWS if isinstance(ev.cell("CAPEX", f"B{r}"), (int, float)))
    assert total*1e6 == pytest.approx(canonical["known_total"], abs=0.01)
    assert ev.cell("CAPEX", "B145")*1e6 == pytest.approx(canonical["known_total"]*0.3, abs=0.01)
    assert "SUM('CAPEX'!$B$145)" in w["CF_1"]["D21"].value
    assert "'Аренда ЗУ'!$I$18" in w["CF_1"]["D21"].value
    assert ev.cell("CF_1", "D21") == pytest.approx(1800*0.2)


def test_changing_inputs_and_rve_recomputes_amount_without_engine_values():
    w, initial, _ = _build({**_base(),"_field_origin":{
        "inputs.land_rent_cadastral_mln":{"text":"НСПД: выбранный арендуемый участок"}}})
    assert initial.cell(book.SHEET,"I19") == "НСПД: выбранный арендуемый участок"
    w[book.SHEET]["B9"] = 200
    w[book.SHEET]["D23"] = 4
    w["Параметры модели"]["B2"] = dt.date(2030, 1, 1)
    w["Параметры модели"]["B3"] = dt.date(2030, 1, 1)
    inputs = {**_base(), "land_rent_cadastral_mln": 200,
              "land_rent_rates": [{"year": 1, "rate_pct": 1.5}, {"year": 2, "rate_pct": 4}]}
    expected = rent.build(inputs, dt.date(2027,1,1), dt.date(2030,1,1))
    changed = Evaluator(w)
    assert changed.cell(book.SHEET, "B19")*1e6 == pytest.approx(expected["known_total"], abs=0.01)
    assert changed.cell(book.SHEET,"I19") == "Изменено вручную в этой книге"


def test_post_rve_is_separate_and_not_assumed_terminated():
    inputs = _base()
    _, ev, canonical = _build(inputs, end=dt.date(2030,1,1))
    assert ev.cell(book.SHEET, "B19")*1e6 == pytest.approx(canonical["known_total"], abs=0.01)
    shown = ev.cell(book.SHEET, "B18")
    assert isinstance(shown, (float,int)) == (canonical["total"] is not None)


@pytest.mark.parametrize("indices", [[], [{"year":2027,"index_pct":5}],
    [{"year":2027,"index_pct":5},{"year":2028,"index_pct":3},{"year":2028,"index_pct":10}],
    [{"year":2027,"index_pct":5},{"year":2028,"index_pct":0},{"year":2029,"index_pct":3}]])
def test_mo_calendar_indices_are_cumulative_and_unknown_is_not_zero(indices):
    inputs = {**_base(), "vri_region":"mo", "land_rent_mode":"mo_housing_new_2026",
              "land_rent_preset_confirmed":True, "land_rent_contract_date":"2026-06-15",
              "land_rent_public_scope":"regional", "land_rent_grant_basis":"ordinary_nonauction",
              "land_rent_mo_cadastral_unchanged":True, "land_rent_calendar_indices":indices}
    _, ev, canonical = _build(inputs)
    assert ev.cell(book.SHEET,"B19")*1e6 == pytest.approx(canonical["known_total"],abs=0.01)
    assert bool(ev.cell(book.SHEET,"B17")) == canonical["complete"]
    for offset in (0,5,12,20):
        month = rent._add_months(dt.date(2027,1,1),offset).isoformat()
        col = openpyxl.utils.get_column_letter(4+offset)
        assert ev.cell(book.SHEET,f"{col}4")*1e6 == pytest.approx(canonical["monthly"].get(month,0),abs=0.01)


@pytest.mark.parametrize("schedule,valid", [("50%@0;50%@12", True), ("10%@0", False),
    ("100%@0;broken", False), ("1@0;50%@12", False)])
def test_manual_payments_reconcile_without_normalising(schedule, valid):
    inputs = {**_base(), "land_rent_payment_mode": "manual", "land_rent_payment_schedule": schedule}
    _, ev, canonical = _build(inputs)
    assert bool(ev.cell(book.SHEET, "F17")) == valid
    for offset in (0, 3, 12, 20):
        month = rent._add_months(dt.date(2027,1,1),offset).isoformat()
        col = openpyxl.utils.get_column_letter(4+offset)
        assert ev.cell(book.SHEET, f"{col}6")*1e6 == pytest.approx(canonical["monthly"].get(month,0),abs=0.01)


def test_unconfirmed_preset_does_not_claim_statutory_rates():
    inputs = {**_base(), "land_rent_mode": "msk_mkd_3_2"}
    _, ev, canonical = _build(inputs)
    assert not canonical["complete"]
    assert ev.cell(book.SHEET, "B17") == 0
    assert ev.cell(book.SHEET, "B19") == 0


@pytest.mark.parametrize("changes", [{"land_right":"ownership"}, {"land_rent_cadastral_mln":0}])
def test_persisted_settings_do_not_make_ownership_a_lease_or_zero_land_free(changes):
    w, ev, canonical = _build({**_base(), **changes})
    assert ev.cell(book.SHEET,"B19")*1e6 == pytest.approx(canonical["known_total"],abs=0.01)
    assert bool(ev.cell(book.SHEET,"B17")) == canonical["complete"]
    if changes.get("land_right") == "ownership":
        w[book.SHEET]["B8"] = "Ручные ставки"
        assert Evaluator(w).cell(book.SHEET,"B19") == 0


def test_leap_anniversary_and_midmonth_boundaries_match_actual_days():
    inputs = {**_base(), "land_rent_regime_start":"2024-02-29"}
    _, ev, canonical = _build(inputs, start=dt.date(2027,1,15),rve=dt.date(2029,5,17))
    assert ev.cell(book.SHEET,"B19")*1e6 == pytest.approx(canonical["known_total"],abs=0.01)


def test_vat_choice_changes_the_deduction_without_changing_land_cost():
    w, ev, canonical = _build({**_base(),"land_rent_vat_treatment":"taxable"})
    assert ev.cell("CF_1","D21") == pytest.approx((1800+canonical["known_total"]/1e6)*0.2)
    w[book.SHEET]["I18"] = "Без НДС: публичный собственник"
    fresh = Evaluator(w)
    assert fresh.cell("CF_1","D21") == pytest.approx(1800*0.2)
    assert fresh.cell(book.SHEET,"B19")*1e6 == pytest.approx(canonical["known_total"],abs=0.01)


def test_construction_cash_plan_is_usable_while_post_rve_obligation_is_open():
    inputs = {**_base(),"land_rent_payment_mode":"manual","land_rent_payment_schedule":"50%@0;50%@12"}
    _, ev, canonical = _build(inputs,end=dt.date(2030,1,1))
    assert canonical["total"] is None
    assert not canonical["cash_schedule_estimated"]
    assert ev.cell(book.SHEET,"F17") == 1
    assert ev.cell(book.SHEET,"B18") == "Не рассчитано полностью"
    assert ev.cell(book.SHEET,"D6")*1e6 == pytest.approx(canonical["monthly"]["2027-01-01"],abs=0.01)


def test_mo_01_january_contract_is_outside_the_new_regime():
    inputs = {**_base(),"vri_region":"mo","land_rent_mode":"mo_housing_new_2026",
        "land_rent_contract_date":"2026-01-01","land_rent_preset_confirmed":True,
        "land_rent_public_scope":"regional","land_rent_grant_basis":"ordinary_nonauction",
        "land_rent_mo_cadastral_unchanged":True,
        "land_rent_calendar_indices":[{"year":2027,"index_pct":5},{"year":2028,"index_pct":5}]}
    _, ev, canonical = _build(inputs)
    assert not canonical["complete"]
    assert ev.cell(book.SHEET,"B19") == 0
    assert ev.cell(book.SHEET,"B17") == 0


@pytest.mark.parametrize("year,expected", [(2027,6_600_000),(2028,7_260_000)])
def test_full_mo_calendar_year_does_not_depend_on_lease_anniversary(year,expected):
    inputs = {**_base(),"vri_region":"mo","land_rent_mode":"mo_housing_new_2026",
        "land_rent_regime_start":"2026-07-01", "land_rent_contract_date":"2026-07-01",
        "land_rent_preset_confirmed":True,"land_rent_public_scope":"regional",
        "land_rent_grant_basis":"ordinary_nonauction","land_rent_mo_cadastral_unchanged":True,
        "land_rent_calendar_indices":[{"year":2027,"index_pct":10},{"year":2028,"index_pct":10}]}
    _, ev, canonical = _build(inputs,start=dt.date(year,1,1),rve=dt.date(year+1,1,1))
    assert canonical["known_total"] == pytest.approx(expected,abs=0.01)
    assert ev.cell(book.SHEET,"B19")*1e6 == pytest.approx(expected,abs=0.01)


@pytest.mark.parametrize("manual", [False,True])
def test_classified_actuals_replace_only_their_coverage_and_leave_future_plan_editable(manual):
    inputs = _base()
    if manual:
        inputs.update(land_rent_payment_mode="manual",land_rent_payment_schedule="50%@0;50%@12")
    actuals = {"cut":"2027-04-01","land_rent_mapping_version":1,"capex_by_article":{
        "land_rent":{"2027-01-01":50_000,"2027-03-01":80_000}}}
    _, ev, canonical = _build(inputs,actuals=actuals)
    for offset in (0,1,2,3,12):
        col = openpyxl.utils.get_column_letter(4+offset)
        month = rent._add_months(dt.date(2027,1,1),offset).isoformat()
        assert ev.cell(book.SHEET,f"{col}6")*1e6 == pytest.approx(canonical["monthly"].get(month,0),abs=0.01)
    assert ev.cell(book.SHEET,"B19")*1e6 == pytest.approx(canonical["applied_total"],abs=0.01)


def test_legacy_combined_import_does_not_charge_past_land_rent_again():
    actuals = {"cut":"2027-04-01","capex_by_article":{"land_rights":{"2027-01-01":2_000_000}}}
    _, ev, canonical = _build(_base(),actuals=actuals)
    assert not canonical["financial_complete"]
    assert ev.cell(book.SHEET,"B17") == 1  # the rate calculation itself remains known
    assert ev.cell(book.SHEET,"L18") == 0  # the historical cash split is unknown
    original = rent.build(_base(),dt.date(2027,1,1),dt.date(2029,1,1))
    assert ev.cell(book.SHEET,"L17")*1e6 == pytest.approx(original["known_total"],abs=0.01)
    assert ev.cell(book.SHEET,"D6") == 0
    assert ev.cell(book.SHEET,"D5") > 0
    assert ev.cell(book.SHEET,"B19")*1e6 == pytest.approx(canonical["applied_total"],abs=0.01)


def test_known_signed_actuals_are_not_hidden_by_an_unknown_future_rate():
    inputs = {**_base(),"land_rent_rates":[{"year":1,"rate_pct":1.5}],"land_rent_tail_rule":"unknown"}
    actuals = {"cut":"2027-02-01","land_rent_mapping_version":1,
               "capex_by_article":{"land_rent":{"2027-01-01":-2_000_000}}}
    _, ev, canonical = _build(inputs,actuals=actuals)
    assert not canonical["complete"]
    assert canonical["applied_total"] < 0
    assert ev.cell("CAPEX","B145")*1e6 == pytest.approx(canonical["applied_total"],abs=0.01)


def _msk_first_year(status="unknown",source="",vri=5):
    return {**_base(),"land_rent_mode":"msk_mkd_3_2","land_rent_preset_confirmed":True,
        "land_rent_regime_start":"2027-01-01","land_rights_cost_mln":vri,
        "land_rent_premium_status":status,"land_rent_premium_source":source,
        "land_rent_payment_mode":"manual","land_rent_payment_schedule":"100%@0"}


@pytest.mark.parametrize("status,source,vri,accepted", [
    ("unknown","",5,False),("separate_required","расчёт отдельно",5,False),
    ("in_vri","договор и расчёт ДГИ",5,True),("in_vri","",5,False),
    ("in_vri","   ",5,False),("in_vri","договор",0,False),
    ("not_applicable","основание по договору",0,True),("not_applicable","",0,False)])
def test_premium_is_qualified_without_adding_or_erasing_base_rent(status,source,vri,accepted):
    _,ev,canonical = _build(_msk_first_year(status,source,vri),rve=dt.date(2028,1,1))
    assert canonical["premium"]["required"]
    assert canonical["financial_complete"] == accepted
    assert ev.cell(book.SHEET,"L17") == pytest.approx(1.5)
    assert ev.cell(book.SHEET,"B19") == pytest.approx(1.5)
    assert bool(ev.cell(book.SHEET,"L18")) == accepted
    assert bool(ev.cell(book.SHEET,"L13")) == (not accepted)


def test_editing_premium_confirmation_uses_live_host_vri_input():
    w,_,_ = _build(_msk_first_year(),rve=dt.date(2028,1,1))
    w[book.SHEET]["L16"] = "Учтена в ВРИ"
    w[book.SHEET]["L19"] = "Договор и расчёт"
    confirmed = Evaluator(w)
    assert confirmed.cell(book.SHEET,"L13") == ""
    assert confirmed.cell(book.SHEET,"L20") == 5
    w["Параметры модели"]["B4"] = 0
    missing = Evaluator(w)
    assert "доплата первого года" in missing.cell(book.SHEET,"L13").lower()
    assert missing.cell(book.SHEET,"L17") == pytest.approx(1.5)


def test_premium_gate_does_not_follow_the_project_into_second_lease_year():
    inputs = {**_msk_first_year(),"land_rent_regime_start":"2026-01-01"}
    _,ev,canonical = _build(inputs,rve=dt.date(2028,1,1))
    assert not canonical["premium"]["required"]
    assert canonical["financial_complete"]
    assert ev.cell(book.SHEET,"L13") == ""


@pytest.mark.parametrize("conditions", [{"_krt_site":{"id":"synthetic"}},
    {"land_rent_grant_basis":"auction"},{"land_rent_grant_basis":"special"}])
def test_known_special_grant_does_not_inherit_moscow_ordinary_rates(conditions):
    _,ev,canonical = _build({**_msk_first_year("in_vri","договор",5),**conditions},rve=dt.date(2028,1,1))
    assert not canonical["complete"]
    assert ev.cell(book.SHEET,"B17") == 0
    assert ev.cell(book.SHEET,"L17") == 0


def test_manual_cutoff_resolves_parcel_scope_without_changing_housing_rve():
    inputs = {**_base(),"land_rent_payment_mode":"manual","land_rent_payment_schedule":"100%@0",
              "land_rent_vat_treatment":"public_exempt"}
    w,initial,canonical = _build(inputs,rve=dt.date(2028,1,1),social_dates={"kindergarten":dt.date(2029,1,1)})
    assert not canonical["scope_complete"]
    assert "охват" in initial.cell(book.SHEET,"L13").lower()
    housing_before = initial.cell("Параметры модели","B2")
    w[book.SHEET]["L15"] = dt.date(2029,1,1)
    confirmed = Evaluator(w)
    assert confirmed.cell(book.SHEET,"L13") == ""
    assert confirmed.cell("Параметры модели","B2") == housing_before
    assert confirmed.cell(book.SHEET,"B19") > initial.cell(book.SHEET,"B19")


def test_actuals_outside_calendar_are_an_explicit_export_limit():
    actuals = {"cut":"2051-01-01","land_rent_mapping_version":1,
               "capex_by_article":{"land_rent":{"2050-01-01":100_000}}}
    with pytest.raises(ValueError,match="конец календаря"):
        _build(_base(),actuals=actuals)


def test_confirmed_cutoff_before_project_start_is_zero_construction_not_unknown():
    _,ev,canonical = _build({**_base(),"land_rent_manual_cutoff":"2026-01-01"})
    assert canonical["complete"]
    assert canonical["construction_total"] == 0
    assert ev.cell(book.SHEET,"B17") == 1
    assert ev.cell(book.SHEET,"L17") == 0
    assert ev.cell(book.SHEET,"B19") == 0
    assert ev.cell(book.SHEET,"F18") == 0
    assert ev.cell(book.SHEET,"L13")


@pytest.mark.parametrize("rates", [
    [{"year":1,"rate_pct":2},{"year":1,"rate_pct":8}],
    [{"year":1,"rate_pct":2},{"year":2,"rate_pct":None}],
    [{"year":1,"rate_pct":2},{"year":2,"rate_pct":-1}],
])
def test_invalid_declared_rate_neither_selects_first_duplicate_nor_repeats_an_earlier_year(rates):
    inputs = {**_base(), "land_rent_regime_start":"2027-01-01", "land_rent_rates":rates}
    _, ev, canonical = _build(inputs, rve=dt.date(2030,1,1))
    assert not canonical["complete"]
    assert ev.cell(book.SHEET,"B17") == 0
    assert ev.cell(book.SHEET,"L17")*1e6 == pytest.approx(canonical["known_total"],abs=.01)
    assert ev.cell(book.SHEET,"B19")*1e6 == pytest.approx(canonical["cash_total"],abs=.01)


def test_classified_payment_period_qualification_recomputes_after_live_base_edits():
    inputs = {**_base(), "land_rent_regime_start":"2027-01-01", "land_rent_cadastral_mln":120,
        "land_rent_rates":[{"year":1,"rate_pct":2}], "land_rent_vat_treatment":"public_exempt",
        "land_rent_payment_mode":"manual", "land_rent_payment_schedule":"100%@0",
        "land_rent_termination_date":"2028-01-01"}
    actuals = {"cut":"2027-04-01", "land_rent_mapping_version":1,
        "capex_by_article":{"land_rent":{"2027-01-01":900000,"2027-03-01":1500000}}}
    w, original, canonical = _build(inputs,rve=dt.date(2028,1,1),actuals=actuals)
    assert canonical["financial_complete"] and original.cell(book.SHEET,"L13") == ""
    w[book.SHEET]["B9"] = 240
    changed = Evaluator(w)
    assert changed.cell(book.SHEET,"L17") == pytest.approx(4.8)
    assert changed.cell(book.SHEET,"B19") == pytest.approx(2.4)
    assert "платеж" in changed.cell(book.SHEET,"L13").lower()
    # Returning to a reconciled basis must clear only this live qualification.
    w[book.SHEET]["B9"] = 120
    assert Evaluator(w).cell(book.SHEET,"L13") == ""
    w[book.SHEET]["I18"] = "Не уточнён"
    w[book.SHEET]["B9"] = 240
    assert "платеж" in Evaluator(w).cell(book.SHEET,"L13").lower()
    w[book.SHEET]["B9"] = 120
    # Reconciliation cannot erase a separate unknown tax treatment.
    assert Evaluator(w).cell(book.SHEET,"L13")


def test_editing_a_year_into_a_duplicate_keeps_only_nonconflicting_known_costs():
    rates = [{"year":1,"rate_pct":2},{"year":2,"rate_pct":3},{"year":3,"rate_pct":4}]
    inputs = {**_base(), "land_rent_regime_start":"2027-01-01", "land_rent_rates":rates,
        "land_rent_tail_rule":"unknown"}
    w, original, _ = _build(inputs,rve=dt.date(2030,1,1))
    assert original.cell(book.SHEET,"L17") == pytest.approx(9)
    w[book.SHEET]["A23"] = 1
    expected = rent.build({**inputs,"land_rent_rates":[rates[0],{"year":1,"rate_pct":3},rates[2]]},
        dt.date(2027,1,1),dt.date(2030,1,1))
    changed = Evaluator(w)
    assert not expected["complete"] and expected["known_total"] == pytest.approx(4e6)
    assert changed.cell(book.SHEET,"B17") == 0
    assert changed.cell(book.SHEET,"L17")*1e6 == pytest.approx(expected["known_total"],abs=.01)
    assert changed.cell(book.SHEET,"B19")*1e6 == pytest.approx(expected["cash_total"],abs=.01)
    # The now-missing second year is unknown, not a known zero in CAPEX.
    assert changed.cell("CAPEX","P145") == "Не рассчитано"
    w[book.SHEET]["A23"] = 2
    assert Evaluator(w).cell(book.SHEET,"B17") == 1
    assert Evaluator(w).cell(book.SHEET,"L17") == pytest.approx(9)


@pytest.mark.parametrize("kind", ["hotel","nonresidential"])
def test_housing_preset_is_unavailable_for_known_native_project_kind_but_manual_rates_work(kind):
    inputs = {**_msk_first_year("not_applicable","По основанию",0),"project_kind":kind}
    w, initial, canonical = _build(inputs,rve=dt.date(2028,1,1))
    assert not canonical["housing_applicable"]
    assert initial.cell(book.SHEET,"B17") == 0
    assert initial.cell(book.SHEET,"L17") == 0
    w[book.SHEET]["B8"] = "Ручные ставки"
    assert Evaluator(w).cell(book.SHEET,"L17") == pytest.approx(1.5)


def test_lease_workbook_uses_the_shared_normalized_project_region():
    _,ev,canonical = _build({**_msk_first_year("not_applicable","По основанию",0),"vri_region":"Москва"},
        rve=dt.date(2028,1,1))
    assert canonical["region"] == "msk"
    assert ev.cell(book.SHEET,"I12") == "msk"
    assert ev.cell(book.SHEET,"B17") == 1
    assert ev.cell(book.SHEET,"L17") == pytest.approx(1.5)


def test_live_duplicate_calendar_index_keeps_prior_year_and_makes_conflict_unknown():
    inputs = {**_base(),"vri_region":"mo","land_rent_mode":"mo_housing_new_2026",
        "land_rent_regime_start":"2026-07-01","land_rent_contract_date":"2026-07-01",
        "land_rent_preset_confirmed":True,"land_rent_public_scope":"regional",
        "land_rent_grant_basis":"ordinary_nonauction","land_rent_mo_cadastral_unchanged":True,
        "land_rent_calendar_indices":[{"year":2027,"index_pct":10},{"year":2028,"index_pct":20},{"year":2029,"index_pct":30}]}
    w,_,_ = _build(inputs,rve=dt.date(2030,1,1))
    row2028 = next(row for row in range(628,728) if w[book.SHEET][f"A{row}"].value == 2028)
    row2029 = row2028 + 1
    w[book.SHEET][f"A{row2029}"] = 2028
    expected = rent.build({**inputs,"land_rent_calendar_indices":[{"year":2027,"index_pct":10},
        {"year":2028,"index_pct":20},{"year":2028,"index_pct":30}]},dt.date(2027,1,1),dt.date(2030,1,1))
    changed = Evaluator(w)
    assert expected["known_total"] == pytest.approx(6.6e6)
    assert changed.cell(book.SHEET,"B17") == 0
    assert changed.cell(book.SHEET,"L17")*1e6 == pytest.approx(expected["known_total"],abs=.01)
