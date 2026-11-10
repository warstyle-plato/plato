"""An admitted workbook may not silently drop known non-rent land costs."""
import copy

import pytest

from test_land_rent_engine import core, inputs


def observed(facts):
    x = inputs(land_rent_payment_mode="manual", land_rent_payment_schedule="100%@0",
               land_rent_termination_date="2029-01-01")
    t = copy.deepcopy(core.TEP_DEFAULT)
    result = core.calculate(core.CalcRequest(inputs=x, tep=t, rates=[], actuals={
        "cut":"2027-04-01", "land_rent_mapping_version":1, "capex_by_article":facts}))
    bundle = {"consolidated":result,"phases":[]}
    return x,t,result,bundle,core._v4_finance_hints(bundle)


def test_known_tax_and_other_payments_are_preserved_in_core_and_refused_by_generic_v4():
    x,t,result,_,hints = observed({"land_tax":{"2027-01-01":1e6},
                                 "land_use_other":{"2027-01-01":2e6}})
    before = copy.deepcopy(result)
    assert result["capex"]["land_tax"] == 1e6
    assert result["capex"]["land_use_other"] == 2e6
    with pytest.raises(core.HTTPException) as raised:
        core.build_project_workbook(x,t,[],{},finance_hints=hints,cache_values=False)
    assert raised.value.status_code == 422
    assert "Земельный налог" in raised.value.detail
    assert "Прочие платежи" in raised.value.detail
    assert "не переносит их суммы и графики" in raised.value.detail
    assert "не предоставлены" not in raised.value.detail
    assert result == before


@pytest.mark.parametrize("payments", [
    {"2027-01-01":-1e6},
    {"2027-01-01":1e6,"2027-02-01":-1e6},
])
def test_refunds_and_zero_net_dated_rows_still_require_an_explicit_export_refusal(payments):
    x,t,result,_,hints = observed({"land_tax":payments})
    dated = result["land_rent"]["additional_land_costs"]["land_tax"]
    for month,value in payments.items():
        assert dated[month] == value
    if sum(payments.values()) == 0:
        # The legacy rounded presentation filters this row; source provenance
        # must still stop the unsupported export instead of assuming zero.
        assert not any(row["key"]=="land_tax" for row in result["monthly"]["costs"])
    with pytest.raises(core.HTTPException) as raised:
        core.build_project_workbook(x,t,[],{},finance_hints=hints,cache_values=False)
    assert raised.value.status_code == 422


def test_http_path_returns_the_same_concrete_refusal(monkeypatch):
    x,t,_,bundle,_ = observed({"land_use_other":{"2027-01-01":2e6}})
    monkeypatch.setattr(core,"require_calc_access",lambda *a,**kw:None)
    monkeypatch.setattr(core,"_run_authoritative_model",lambda *a,**kw:bundle)
    with pytest.raises(core.HTTPException) as raised:
        core.report_workbook(core.WorkbookExportRequest(inputs=x,tep=t))
    assert raised.value.status_code == 422
    assert "Прочие платежи за пользование землёй" in raised.value.detail


@pytest.mark.parametrize("value", [None, "", float("nan"), True])
def test_explicit_unknown_amount_is_not_replaced_with_zero(value):
    assert core._v4_unrepresented_land_costs({"capex":{"land_tax":value}}) == ["Земельный налог"]


def test_legacy_dated_presentation_with_zero_net_is_also_detected():
    result = {"capex":{"land_use_other":0},"monthly":{"costs":[{
        "key":"land_use_other","total":0,"values":[2e6,-2e6]}]}}
    assert core._v4_unrepresented_land_costs(result) == ["Прочие платежи за пользование землёй"]
    assert core._v4_unrepresented_land_costs({"capex":{"land_tax":0}}) == []


def test_known_land_costs_are_not_lost_when_financing_details_are_missing():
    assert core._v4_finance_hints({"consolidated":{"capex":{"land_tax":1e6}}}) == {
        "unrepresented_land_costs":["Земельный налог"]}


def test_dated_source_is_checked_even_when_a_caller_omits_the_compiled_hint():
    x,t,_,_,hints = observed({"land_use_other":{"2027-01-01":1e6,"2027-02-01":-1e6}})
    hints.pop("unrepresented_land_costs")
    with pytest.raises(core.HTTPException) as raised:
        core.build_project_workbook(x,t,[],{},finance_hints=hints,cache_values=False)
    assert raised.value.status_code == 422
    assert "Прочие платежи" in raised.value.detail


def test_native_dispatch_does_not_inherit_the_generic_v4_restriction(monkeypatch):
    sentinel = (b"native", "native.xlsx", {"hotel_book":True})
    monkeypatch.setattr(core,"_hotel_project_workbook",lambda *a,**kw:sentinel)
    assert core.build_project_workbook({"project_kind":"hotel"},{},finance_hints={
        "unrepresented_land_costs":["Земельный налог"]}) == sentinel
