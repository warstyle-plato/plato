"""The parcel keeps five exit dates even on v4's four financing blocks."""
import copy
from datetime import date
import io
import sys
from pathlib import Path

import openpyxl
import pytest

import developaid_land_rent as rent
import main_legacy as core
import v4_land_rent as book
from xlsx_eval import Evaluator


def inputs(**changes):
    return {**copy.deepcopy(core.DEFAULT_INPUTS), "project_start": "2027-01-01",
        "ird_months": 12, "construction_months": 24,
        "land_right": "lease", "land_rights_cost_mln": 0,
        "land_rent_mode": "manual", "land_rent_cadastral_mln": 100,
        "land_rent_regime_start": "2027-01-01",
        "land_rent_rates": [{"year": 1, "rate_pct": 1.5}],
        "land_rent_tail_rule": "repeat_last", "land_rent_vat_treatment": "public_exempt",
        "social_mode": "Денежная компенсация", "social_compensation_mln": 0, **changes}


def test_all_released_shares_do_not_create_another_unknown_rent_during_residual_sales():
    result = rent.build(inputs(), date(2027,1,1), date(2030,1,1), date(2032,1,1),
        phase_land=[{"share": .35, "rve": "2029-01-01"}, {"share": .65, "rve": "2030-01-01"}])
    assert [p["accrual_total"] for p in result["phase_land"]] == pytest.approx([1_050_000, 2_925_000])
    assert result["total"] == pytest.approx(3_975_000)
    assert sum(v for m,v in result["monthly"].items() if m >= "2030-01-01") == 0
    assert not result["post_rve_unknown"]
    assert result["post_rve_policy"] == "proportional_phase_release"
    assert rent.sum_state(result) == {"known": True, "reason": ""}
    # A determined amount is not a confirmation of payment dates or the
    # legal termination of the lease contract.
    assert not result["financial_complete"]
    assert "payments" in result["financial_missing_codes"]
    assert "post_rve" not in result["financial_missing_codes"]
    assert any("не подтверждение прекращения договора" in s for s in result["assumptions"])


@pytest.mark.parametrize("bad", [
    [{"share": .35, "rve": "2029-01-01"}, {"share": .5, "rve": "2030-01-01"}],
    [{"share": -.35, "rve": "2029-01-01"}, {"share": 1.35, "rve": "2030-01-01"}],
    [{"share": float("nan"), "rve": "2029-01-01"}, {"share": .65, "rve": "2030-01-01"}],
    [{"share": .35, "rve": "bad"}, {"share": .65, "rve": "2030-01-01"}],
    [{"share": .35}, {"share": .65, "rve": "2030-01-01"}],
    [None, {"share": 1, "rve": "2030-01-01"}],
])
def test_incomplete_or_invalid_phase_geometry_does_not_remove_unknown_rent(bad):
    result = rent.build(inputs(), date(2027,1,1), date(2030,1,1), date(2032,1,1), phase_land=bad)
    assert result["post_rve_unknown"]
    assert result["total"] is None and not result["complete"]
    assert not rent.sum_state(result)["known"]
    assert result["missing"]


def test_a_missing_base_keeps_every_source_queue_for_an_editable_book():
    phases = [{"share": share, "rve": f"{2030+i}-01-01"}
              for i,share in enumerate((.28,.22,.19,.16,.15))]
    result = rent.build(inputs(land_rent_cadastral_mln=None), date(2027,1,1),
        date(2034,1,1), date(2035,1,1), phase_land=phases)
    assert len(result["phase_land"]) == 5
    assert [p["rve"] for p in result["phase_land"]] == [p["rve"] for p in phases]
    assert result["total"] is None and not rent.sum_state(result)["known"]


@pytest.mark.parametrize("change,code", [
    ({"land_rent_rates": [], "land_rent_tail_rule": "unknown"}, "inputs"),
    ({"land_rent_mode": "msk_mkd_3_2", "land_rent_preset_confirmed": True,
      "land_rent_premium_status": "separate_required"}, "premium"),
    ({"land_rent_cadastral_target_mln": None}, "cadastral_change"),
])
def test_proportional_scope_does_not_confirm_missing_rates_premium_or_future_cadastral(change, code):
    result = rent.build(inputs(**change), date(2027,1,1), date(2030,1,1), date(2032,1,1),
        cadastral_switch=date(2028,1,1) if code == "cadastral_change" else None,
        phase_land=[{"share": .35, "rve": "2029-01-01"}, {"share": .65, "rve": "2030-01-01"}])
    assert code in result["financial_missing_codes"]
    assert not rent.sum_state(result)["known"]
    assert not result["financial_complete"]


@pytest.mark.parametrize("shares", [[.2,.2,.2,.2,.1], [-.2,.3,.3,.3,.3],
                                       [float("nan"),.2,.2,.2,.2], [float("inf"),0,0,0,0]])
def test_book_rejects_invalid_source_shares_even_with_valid_folding(shares):
    with pytest.raises(ValueError, match="доли очередей"):
        book.apply(b"", {}, {}, project_start_formula="1", rve_formula="2",
            phase_shares=shares, phase_capex_groups=[[0],[1],[2],[3,4]])


@pytest.mark.parametrize("groups", [[[0],[1],[2],[3]], [[0],[1],[2],[3,3,4]],
                                     [[0],[1],[],[2,3,4]], [[0],[1],[2],[3],[4]]])
def test_book_rejects_lost_duplicated_or_unrepresentable_cash_groups(groups):
    with pytest.raises(ValueError, match="ровно один раз"):
        book.apply(b"", {}, {}, project_start_formula="1", rve_formula="2",
            phase_shares=[.28,.22,.19,.16,.15], phase_capex_groups=groups)


@pytest.mark.parametrize("count,empty", [(2,None),(5,"")])
def test_nullable_source_phase_duration_keeps_the_existing_book_default(count, empty):
    x = inputs()
    p = {"enabled":True,"phase_count":count,"phase_gap_months":12,
         "phases":[{"start_offset_months":12*i,"construction_months":24,"site_area_ha":i+1}
                   for i in range(count)]}
    bundle = core._run_authoritative_model(x, copy.deepcopy(core.TEP_DEFAULT), [], p)
    # The supplied authoritative result has already applied the default.
    # An empty raw value must not introduce int(None)/int('') in the writer.
    p["phases"][-1]["construction_months"] = empty
    _,_,meta = core.build_project_workbook(x, copy.deepcopy(core.TEP_DEFAULT), [], p,
        project_name="Synthetic empty phase duration", finance_hints=core._v4_finance_hints(bundle), cache_values=False)
    assert meta["land_rent"]["workbook_supported"], meta["land_rent"]


@pytest.fixture(scope="module")
def five_queue_book():
    x = inputs()
    p = {"enabled": True, "user_enabled": True, "phase_count": 5, "phase_gap_months": 12,
        "cost_inflation_pct": 20, "sales_price_inflation_pct": 8,
        "phases": [{"name": f"О{i+1}", "start_offset_months": 12*i,
                    "construction_months": 24, "site_area_ha": weight}
                   for i,weight in enumerate((28,22,19,16,15))],
        "products": {key:[28,22,19,16,15] for key in
                     ("apartments","ground_commercial","underground_parking","storage")}}
    p["phases"][3]["land_rent_release_date"] = "2032-11-17"
    p["phases"][4]["land_rent_release_date"] = "2034-04-09"
    bundle = core._run_authoritative_model(x, copy.deepcopy(core.TEP_DEFAULT), [], p)
    hints = core._v4_finance_hints(bundle)
    content, _, meta = core.build_project_workbook(x, copy.deepcopy(core.TEP_DEFAULT), [], p,
        project_name="Synthetic five-queue lease", finance_hints=hints, cache_values=False)
    assert meta["land_rent"]["workbook_supported"], meta["land_rent"]
    # Preserve the limitation of the general template: this test proves the
    # lease cash, not the independent financing parity of five source queues.
    assert any("слиты в четвёртую" in str(v) for v in meta["missing"])
    workbook = openpyxl.load_workbook(io.BytesIO(content), data_only=False)
    sys.setrecursionlimit(400000)
    return bundle, workbook, Evaluator(workbook), meta


def phase_rows(workbook):
    ws = workbook[book.SHEET]
    first = next(cell.row+1 for row in ws for cell in row if cell.value == "Доля участка")
    return list(range(first, first+5))


def test_five_independent_exit_dates_are_preserved_and_cash_4_plus_5_reaches_cf4_once(five_queue_book):
    bundle, workbook, ev, meta = five_queue_book
    canonical = bundle["consolidated"]["land_rent"]
    rows = phase_rows(workbook)
    assert len(canonical["phase_land"]) == 5
    own = [p["cash_total"] for p in canonical["phase_land"]]
    expected = own[:3] + [sum(own[3:])]
    assert [ev.cell("CAPEX", f"B{145+i}")*1e6 for i in range(4)] == pytest.approx(expected, abs=.01)
    assert [ev.cell(book.SHEET, f"F{r}")*1e6 for r in rows] == pytest.approx(own, abs=.01)
    assert ev.cell(book.SHEET, "B19")*1e6 == pytest.approx(sum(own), abs=.01)
    assert "очереди 4, 5" in workbook["CAPEX"]["A148"].value
    assert "SUM('CAPEX'!$B$148)" in workbook["CF_4"]["D21"].value
    assert ev.cell(book.SHEET, "F18") == 1
    assert ev.cell(book.SHEET, "B18")*1e6 == pytest.approx(canonical["total"], abs=.01)
    assert "не подтверждение прекращения договора" in workbook[book.SHEET]["A2"].value
    # Check every cash bucket across the later queue's exit. CF_4 keeps
    # reading CAPEX after its own RVE; the fifth queue is not cut off at it.
    for offset in range(100):
        col = openpyxl.utils.get_column_letter(4+offset)
        month = rent._add_months(date(2027,1,1), offset).isoformat()
        expected_month = sum(p.get(month, 0) for p in canonical["phase_monthly"][3:])
        actual = ev.cell("CAPEX", f"{col}148")
        assert isinstance(actual, (int,float)), (month, actual, ev.cell(book.SHEET,f"{col}5"), ev.cell(book.SHEET,f"{col}6"))
        assert actual*1e6 == pytest.approx(expected_month, abs=.01), month
        assert ev.cell("CF_4", f"{col}17") == pytest.approx(ev.cell("CAPEX", f"{col}134")), month
    assert sum(v for m,v in canonical["phase_monthly"][4].items() if m >= "2033-01-01") > 0
    assert not canonical["post_rve_unknown"]


def test_fifth_queue_calendar_remains_editable_without_changing_the_fourth_exit(five_queue_book):
    _, workbook, _, _ = five_queue_book
    changed = copy.deepcopy(workbook)
    rows = phase_rows(changed)
    ws = changed[book.SHEET]
    # Clear the explicit rent-only override, then delay the fifth queue's
    # construction by one year through its own live calendar input.
    ws[f"I{rows[4]}"] = None
    before = Evaluator(changed)
    fourth = before.cell(book.SHEET, f"D{rows[3]}")
    prior = before.cell(book.SHEET, "B19")
    ws[f"M{rows[4]}"] = 36
    after = Evaluator(changed)
    assert after.cell(book.SHEET, f"D{rows[3]}") == fourth
    assert after.cell(book.SHEET, "B19")-prior == pytest.approx(.225, abs=1e-9)
    assert after.cell("CAPEX", "B148")-before.cell("CAPEX", "B148") == pytest.approx(.225, abs=1e-9)


@pytest.mark.parametrize("width,surface", [(390,"/"),(1440,"/classic")])
def test_real_page_names_proportional_exit_and_does_not_request_an_absent_separate_calculation(width, surface, monkeypatch):
    from playwright.sync_api import expect, sync_playwright
    import main
    from main_registry import app as registry_app
    from tests import browser

    monkeypatch.setattr(main.core, "_telegram_token", lambda: "")
    monkeypatch.setattr(main.core, "require_calc_access", lambda *a, **k: {"allowed":True})
    with browser.serve(registry_app, 18897) as base, sync_playwright() as pw:
        with pw.chromium.launch(executable_path=str(browser.chromium_or_skip())) as chromium:
            page = chromium.new_page(viewport={"width":width,"height":1000}, locale="ru-RU")
            errors = []
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.route("**/ia/goal-seek", lambda route: route.fulfill(status=503, json={"reason":"Синтетический отказ подбора"}))
            page.goto(base.rstrip("/")+surface, wait_until="domcontentloaded")
            browser.wait_for_result(page)
            page.evaluate("""async x=>{
              Object.assign(inputs,x);delete inputs._glavapu_import;delete inputs._mo_calc;
              phasing=makeDefaultPhasing(5);phasing.enabled=true;phasing.user_enabled=true;
              phasing.phase_count=5;
              phasing.phases=Array.from({length:5},(_,i)=>({name:'О'+(i+1),start_offset_months:12*i,
                construction_months:24,site_area_ha:i+1}));
              renderInputs();await settledCalculate();
            }""", inputs())
            browser.wait_for_result(page)
            state = page.evaluate("({rent:lastResult.land_rent, dates:lastResult.dates, sum:lastResult.summary.land_rent_sum, verdict:lastResult.report.entry_price_verdict})")
            assert not state["rent"]["post_rve_unknown"]
            assert state["sum"] == {"known":True,"reason":""}
            assert state["verdict"]["title"] != "Предварительная экономика: уточните аренду земли"
            browser.open_vri(page)
            root = page.locator("#landRentEditor")
            advanced = root.locator("[data-land-rent-advanced]")
            advanced.locator("summary").first.click()
            scope = root.locator('[data-land-rent-detail="scope"]')
            scope.locator("summary").first.click()
            expect(scope).to_contain_text("аренда уменьшается по долям введённых очередей")
            expect(scope).not_to_contain_text("После ввода нужен отдельный расчёт аренды")
            assert scope.locator(".lr-phase-table tbody tr").count() == 5
            assert root.locator('.lr-exposure-table tbody tr').count() == 5
            registration = root.locator('#f_land_rent_registration_months')
            expect(registration).to_have_value('3')
            registration.fill('6')
            registration.dispatch_event('change')
            page.wait_for_function('lastResult.land_rent.registration_months===6')
            browser.wait_for_result(page)
            changed=page.evaluate('({rent:lastResult.land_rent,dates:lastResult.dates})')
            assert changed['dates']==state['dates']
            assert changed['rent']['known_total']>state['rent']['known_total']
            assert all(p['lease_exit']>old['lease_exit'] for p,old in zip(
                changed['rent']['land_exposures'],state['rent']['land_exposures']))
            assert page.evaluate("document.documentElement.scrollWidth<=innerWidth+2")
            output = Path("/tmp/plato-rent-five-queue-proof")
            output.mkdir(mode=0o700, exist_ok=True)
            scope.screenshot(path=str(output/f"phase-exit-{width}.png"))
            assert not errors, errors
