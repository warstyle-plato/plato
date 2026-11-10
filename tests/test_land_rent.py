from datetime import date

import pytest

import developaid_land_rent as rent


def settings(**kw):
    base = dict(land_right="lease", vri_region="msk", land_rent_mode="manual",
                land_rent_cadastral_mln=100, land_rent_regime_start="2027-01-01",
                land_rent_rates=[{"year": 1, "rate_pct": 1.5}, {"year": 2, "rate_pct": 3}],
                land_rent_tail_rule="repeat_last", land_rent_vat_treatment="public_exempt")
    return {**base, **kw}


def test_delay_adds_regular_rent_without_restarting_lease_year():
    x = settings()
    first = rent.build(x, date(2027, 1, 1), date(2028, 1, 1))
    late = rent.build(x, date(2027, 1, 1), date(2030, 1, 1))
    assert first["construction_total"] == pytest.approx(1_500_000)
    assert late["construction_total"] == pytest.approx(7_500_000)
    acquired = rent.build(x, date(2028, 1, 1), date(2030, 1, 1))
    assert acquired["construction_total"] == pytest.approx(6_000_000)
    assert [r["year"] for r in acquired["annual_rows"]] == [2, 3]


def test_leap_anniversary_and_partial_month_use_declared_convention():
    x = settings(land_rent_regime_start="2024-02-29")
    a = rent.build(x, date(2024, 2, 29), date(2025, 2, 28))
    assert a["construction_total"] == pytest.approx(1_500_000)
    assert sum(a["monthly"].values()) == pytest.approx(1_500_000)
    partial = rent.build(x, date(2024, 3, 15), date(2024, 4, 1))
    assert partial["construction_total"] == pytest.approx(1_500_000 * 17 / 365)
    assert "не установленный законом" in partial["convention"]


def test_missing_rate_is_not_zero_and_keeps_proven_parts():
    x = settings(land_rent_tail_rule="unknown")
    x["land_rent_rates"] = [{"year": 1, "rate_pct": 0}, {"year": 2, "rate_pct": 2}]
    result = rent.build(x, date(2027, 1, 1), date(2030, 1, 1))
    assert result["known_total"] == pytest.approx(2_000_000)
    assert result["total"] is result["construction_total"] is None
    assert result["annual_rows"][0]["amount"] == 0
    assert result["annual_rows"][2]["amount"] is None
    assert not result["complete"]


def test_old_leased_project_gets_visible_unknown_not_fake_zero():
    result = rent.build({"land_right": "lease"}, date(2027, 1, 1), date(2028, 1, 1))
    assert result["total"] is None and result["monthly"] == {}
    assert result["missing"] and "Предварительный" in rent.disclosure(result)
    assert rent.build({"land_right": "ownership"}, date(2027, 1, 1), date(2028, 1, 1))["financial_complete"]


def test_first_year_exclusion_requires_confirmation_and_does_not_erase_year_two():
    x = settings(land_rent_first_year_relation="full_year_in_vri")
    rejected = rent.build(x, date(2027, 1, 1), date(2029, 1, 1))
    assert rejected["total"] is None
    x["land_rent_first_year_confirmed"] = True
    accepted = rent.build(x, date(2027, 1, 1), date(2029, 1, 1))
    assert accepted["construction_total"] == pytest.approx(3_000_000)
    assert accepted["annual_rows"][0]["included_in_vri"]


def test_preset_requires_applicability_confirmation_and_matching_region():
    x = settings(land_rent_mode="msk_mkd_3_2")
    assert rent.build(x, date(2027, 1, 1), date(2034, 1, 1))["total"] is None
    x["land_rent_preset_confirmed"] = True
    result = rent.build(x, date(2027, 1, 1), date(2034, 1, 1))
    assert [r["rate_pct"] for r in result["annual_rows"]] == [1.5, 1.5, 3, 5, 7, 8, 10]
    x["vri_region"] = "mo"
    assert rent.build(x, date(2027, 1, 1), date(2028, 1, 1))["total"] is None


@pytest.mark.parametrize("kind", ["hotel", "nonresidential"])
@pytest.mark.parametrize("preset", ["msk_mkd_3_2", "msk_mkd_arch_confirmed", "mo_housing_new_2026"])
def test_housing_preset_cannot_override_known_project_kind(kind, preset):
    x = settings(project_kind=kind, land_rent_mode=preset, land_rent_preset_confirmed=True)
    result = rent.build(x, date(2027, 1, 1), date(2028, 1, 1))
    assert not result["housing_applicable"]
    assert not result["complete"] and result["total"] is None
    assert result["monthly"] == {}
    assert any("Жилищная предустановка" in message for message in result["missing"])
    manual = rent.build({**x, "land_rent_mode": "manual"}, date(2027, 1, 1), date(2028, 1, 1))
    assert manual["construction_total"] == pytest.approx(1.5e6)


@pytest.mark.parametrize("alias", ["msk", "77", "Москва", "moscow", ""])
def test_rent_uses_the_existing_project_region_and_preserves_its_origin(alias):
    origin = {"source": "document", "text": "По применённой территории участка"}
    x = settings(vri_region=alias, land_rent_mode="msk_mkd_3_2",
                 land_rent_preset_confirmed=True, _field_origin={"inputs.vri_region": origin})
    result = rent.build(x, date(2027, 1, 1), date(2028, 1, 1))
    assert result["region"] == "msk"
    assert result["region_origin"] == origin
    assert result["construction_total"] == pytest.approx(1.5e6)
    outside = rent.build({**x, "vri_region": "other"}, date(2027, 1, 1), date(2028, 1, 1))
    assert outside["construction_total"] is None
    assert any("региону" in message for message in outside["missing"])


def test_manual_dates_amounts_reconcile_without_silent_balancing():
    x = settings(land_rent_payment_mode="manual", land_rent_payment_schedule="0.5@0; 1@6")
    result = rent.build(x, date(2027, 1, 1), date(2028, 1, 1))
    assert result["monthly"] == {"2027-01-01": 500_000, "2027-07-01": 1_000_000}
    assert result["financial_complete"]
    x["land_rent_payment_schedule"] = "0.5@0; 0.9@6"
    rejected = rent.build(x, date(2027, 1, 1), date(2028, 1, 1))
    assert not rejected["financial_complete"] and rejected["cash_schedule_estimated"]
    assert sum(rejected["monthly"].values()) == pytest.approx(1_500_000)
    assert any("не сходится" in n for n in rejected["notes"])


def test_post_commissioning_requires_separate_choice_or_real_termination():
    x = settings()
    unknown = rent.build(x, date(2027, 1, 1), date(2028, 1, 1), date(2029, 1, 1))
    assert unknown["construction_total"] == pytest.approx(1_500_000)
    assert unknown["total"] is None and not unknown["financial_complete"]
    x["land_rent_termination_date"] = "2028-01-01"
    terminated = rent.build(x, date(2027, 1, 1), date(2028, 1, 1), date(2029, 1, 1))
    assert terminated["total"] == pytest.approx(1_500_000)


@pytest.mark.parametrize("value", [None, "", True, float("nan"), -1])
def test_invalid_cadastral_base_is_not_treated_as_zero(value):
    x = settings(land_rent_cadastral_mln=value)
    result = rent.build(x, date(2027, 1, 1), date(2028, 1, 1))
    assert result["total"] is None and result["missing"]


def mo_settings(**kw):
    return settings(land_rent_mode="mo_housing_new_2026", vri_region="mo",
                    land_rent_contract_date="2027-01-01", land_rent_regime_start="2027-07-01",
                    land_rent_public_scope="regional", land_rent_grant_basis="ordinary_nonauction",
                    land_rent_preset_confirmed=True, land_rent_mo_cadastral_unchanged=True,
                    **kw)


def test_mo_index_changes_on_january_first_not_lease_anniversary():
    x = mo_settings(land_rent_calendar_indices=[{"year": 2028, "index_pct": 10}])
    result = rent.build(x, date(2027, 7, 1), date(2028, 7, 1))
    assert result["construction_total"] == pytest.approx(6e6 * (184/365 + 182*1.1/366))
    assert result["monthly"]["2027-12-01"] == pytest.approx(6e6 * 31/365)
    assert result["monthly"]["2028-01-01"] == pytest.approx(6e6 * 1.1 * 31/366)
    assert result["annual_rows"][0]["rate_pct"] == 6  # explicitly a base Kd


def test_mo_missing_index_is_unknown_but_explicit_zero_is_known():
    x = mo_settings()
    missing = rent.build(x, date(2027, 7, 1), date(2028, 7, 1))
    assert missing["construction_total"] is None
    assert missing["known_total"] == pytest.approx(6e6*184/365)
    x["land_rent_calendar_indices"] = [{"year": 2028, "index_pct": 0}]
    assert rent.build(x, date(2027, 7, 1), date(2028, 7, 1))["construction_total"] == pytest.approx(6e6*(184/365+182/366))


def test_mo_index_origin_is_contract_year_not_cadastral_date_or_project_start():
    x = mo_settings()
    x.update(land_rent_contract_date="2026-06-01", land_rent_calendar_indices=[
        {"year": 2027, "index_pct": 8}, {"year": 2028, "index_pct": 10}])
    result = rent.build(x, date(2027, 7, 1), date(2028, 7, 1))
    assert result["construction_total"] == pytest.approx(6e6 * 1.08 * (184/365+182*1.1/366))


@pytest.mark.parametrize("year", [2027, 2028])
def test_mo_full_calendar_year_has_exact_indexed_annual_amount_with_non_january_anchor(year):
    x = mo_settings()
    x.update(land_rent_contract_date="2026-07-01", land_rent_regime_start="2026-07-01",
             land_rent_calendar_indices=[{"year": 2027, "index_pct": 10}, {"year": 2028, "index_pct": 5}])
    result = rent.build(x, date(year, 1, 1), date(year+1, 1, 1))
    assert result["construction_total"] == pytest.approx(6_600_000 * (1.05 if year == 2028 else 1))


@pytest.mark.parametrize("change", [
    {"land_rent_contract_date": "2025-12-31"}, {"land_rent_public_scope": "municipal"},
    {"land_rent_contract_date": "2026-01-01"},
    {"_krt_site": True}, {"land_rent_grant_basis": "auction"},
    {"land_rent_mo_cadastral_unchanged": False},
])
def test_mo_special_or_unverified_contract_does_not_inherit_six_percent(change):
    x = mo_settings();x.update(change)
    result = rent.build(x, date(2027, 7, 1), date(2028, 7, 1))
    assert result["total"] is None and result["monthly"] == {}


def test_ownership_keeps_saved_settings_without_charging_rent():
    x = settings(land_right="ownership")
    result = rent.build(x, date(2027, 1, 1), date(2028, 1, 1))
    assert result["total"] == 0 and result["monthly"] == {} and result["financial_complete"]


def test_zero_cadastral_base_does_not_mean_a_known_free_leased_plot():
    result = rent.build(settings(land_rent_cadastral_mln=0), date(2027, 1, 1), date(2028, 1, 1))
    assert result["total"] is None and result["missing"]


def test_manual_construction_cash_still_applies_when_post_rve_is_unknown():
    x = settings(land_rent_payment_mode="manual", land_rent_payment_schedule="100%@0")
    result = rent.build(x, date(2027, 1, 1), date(2028, 1, 1), date(2029, 1, 1))
    assert result["total"] is None and result["construction_total"] == pytest.approx(1.5e6)
    assert result["monthly"] == {"2027-01-01": 1.5e6}
    assert not result["cash_schedule_estimated"] and not result["financial_complete"]


def test_conflicting_year_rates_and_indices_are_not_accepted_as_a_known_first_value():
    x = settings(land_rent_rates=[{"year": 1, "rate_pct": 1}, {"year": 1, "rate_pct": 7}])
    result = rent.build(x, date(2027, 1, 1), date(2028, 1, 1))
    assert result["total"] is None and result["known_total"] == 0
    x = mo_settings(land_rent_calendar_indices=[{"year": 2028, "index_pct": 1}, {"year": 2028, "index_pct": 9}])
    result = rent.build(x, date(2028, 1, 1), date(2028, 7, 1))
    assert result["total"] is None and result["known_total"] == 0


@pytest.mark.parametrize("mode", ["msk_mkd_3_2", "msk_mkd_arch_confirmed"])
@pytest.mark.parametrize("conflict", [{"_krt_site": True}, {"land_rent_grant_basis": "auction"}])
def test_moscow_generic_confirmation_does_not_override_known_special_contract(mode, conflict):
    x = settings(land_rent_mode=mode, land_rent_preset_confirmed=True)
    x.update(conflict)
    result = rent.build(x, date(2027, 1, 1), date(2028, 1, 1))
    assert result["total"] is None and result["monthly"] == {}


def test_first_year_moscow_base_does_not_prove_premium_or_become_complete_by_manual_cash():
    x = settings(land_rent_mode="msk_mkd_3_2", land_rent_preset_confirmed=True,
        land_rent_payment_mode="manual", land_rent_payment_schedule="100%@0", land_rent_termination_date="2028-01-01")
    unknown = rent.build(x, date(2027,1,1), date(2028,1,1))
    assert unknown["construction_total"] == pytest.approx(1.5e6)
    assert unknown["complete"] and not unknown["financial_complete"]
    assert "premium" in unknown["financial_missing_codes"]
    x.update(land_rent_premium_status="in_vri", land_rent_premium_source="Подтверждённый состав ВРИ", land_rights_cost_mln=100)
    confirmed = rent.build(x, date(2027,1,1), date(2028,1,1))
    assert confirmed["financial_complete"]
    assert confirmed["construction_total"] == pytest.approx(1.5e6)  # no second premium
    x["land_rights_cost_mln"] = 0
    assert not rent.build(x, date(2027,1,1), date(2028,1,1))["financial_complete"]


def test_premium_requires_no_new_confirmation_after_the_first_lease_year():
    x = settings(land_rent_mode="msk_mkd_3_2", land_rent_preset_confirmed=True,
        land_rent_payment_mode="manual", land_rent_payment_schedule="100%@0")
    result = rent.build(x, date(2028,1,1), date(2029,1,1))
    assert not result["premium"]["required"] and result["financial_complete"]


def test_manual_parcel_cutoff_has_origin_and_resolves_unlinked_late_social_scope():
    x = settings(land_rent_payment_mode="manual", land_rent_payment_schedule="100%@0")
    base = rent.build(x, date(2027,1,1), date(2028,1,1))
    rent.qualify_scope(base, {"school":date(2030,1,1)})
    assert not base["scope_complete"] and not base["financial_complete"]
    assert base["construction_total"] == pytest.approx(1.5e6)
    x.update(land_rent_manual_cutoff="2031-01-01", _field_origin={"inputs.land_rent_manual_cutoff":{"source":"manual","text":"Договор участка"}})
    fixed = rent.build(x, date(2027,1,1), date(2028,1,1))
    rent.qualify_scope(fixed, {"school":date(2030,1,1)})
    assert fixed["rve"] == "2031-01-01" and fixed["derived_rve"] == "2028-01-01"
    assert fixed["cutoff_origin"] == "manual" and fixed["scope_complete"]
    assert fixed["construction_total"] == pytest.approx(10.5e6)
