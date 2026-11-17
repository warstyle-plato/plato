"""Сохранённый МО-проект проходит настоящие renderInputs/renderTep/calculate."""
from contextlib import contextmanager
import ipaddress
import json
import os
import socket
from urllib.parse import urlparse

import pytest

import browser
import browser_launch
import main_registry

core = main_registry.core
KEY = "fictional-full-page-mo-key"
CALCULATIONS = {"/calculate", "/calculate-phased"}


@pytest.fixture(scope="module")
def served():
    patch = pytest.MonkeyPatch()
    accesses = []
    external_dns = []
    original_lookup = socket.getaddrinfo

    def local_lookup(host, *args, **kwargs):
        if host not in (None, "", "localhost", b"localhost"):
            try:
                address = ipaddress.ip_address(host.decode() if isinstance(host, bytes) else host)
            except ValueError:
                address = None
            if address is None or not (address.is_loopback or address.is_unspecified):
                external_dns.append(str(host))
                raise AssertionError("full PAGE fixture allows localhost only")
        return original_lookup(host, *args, **kwargs)

    def allowed(session, key, what, **kwargs):
        accesses.append({"what": what, "synthetic_key": key == KEY})
        return {"allowed": True, "code": "admin", "basis": "fictional_local_test"}

    patch.setattr(core, "require_calc_access", allowed)
    # Та же offline-вводная ЦБ, что в штатных whole-PAGE проверках. Сам
    # calculate не подменён; никакого запроса к правовому/банковскому сайту.
    patch.setattr(core, "fetch_current_cbr_key_rate", lambda: {
        "rate": 14.0, "date": "2026-11-15", "live": False, "source": "Fictional local rate"})
    patch.setattr(socket, "getaddrinfo", local_lookup)
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    try:
        with browser.serve(core.app, port) as base:
            yield base, accesses
    finally:
        patch.undo()
        assert not external_dns, external_dns


SETUP = """()=>{
 const stored=x=>JSON.parse(JSON.stringify(x));
 const model=Object.assign(stored(INPUT_DEFAULT),{
  vri_region:'mo',land_right:'lease',land_rent_mode:'mo_housing_new_2026',
  _project_uid:'fictional-full-page-mo',land_rights_cost_mln:1000,
  mo_vri_compensation_mln:0,vri_transfer_offset_mln:30,vri_relief_mode:'none'});
 delete model._mo_calc;delete model._mo_vri_relief;delete model._partial_tep;
 const savedTep=stored(TEP_DEFAULT);
 savedTep.apartments=Object.assign(savedTep.apartments,{gns:40000,saleable:30000,transfer:2000});
 const savedPhasing=makeDefaultPhasing(2);
 savedPhasing.enabled=true;savedPhasing.user_enabled=true;
 savedPhasing.products.apartments=[60,40];
 applyProjectSnapshot(stored({inputs:model,tep:savedTep,phasing:savedPhasing,scenario:'base'}));
 projectsAdminKey='fictional-full-page-mo-key';openTab('vri');
 document.getElementById('moVriBenefitMode').value='manual';moVriBenefitModeChanged();
}"""

READ = """()=>({
 fee:inputs.land_rights_cost_mln,compensation:inputs.mo_vri_compensation_mln,
 offset:inputs.vri_transfer_offset_mln,transfer:tep.apartments.transfer,
 phasing:JSON.parse(JSON.stringify(phasing)),tep:JSON.parse(JSON.stringify(tep)),
 partial:partialTepMode(),region:classRegion(),proof:inputs._mo_vri_relief||null,
 result:!!lastResult,run:calcRun,settled:calcSettled,idle:calcIdle(),
 overflow:document.documentElement.scrollWidth>innerWidth+1
})"""


@contextmanager
def full_page(served, width):
    from playwright.sync_api import sync_playwright

    base, accesses = served
    if not os.environ.get("CHROMIUM_EXECUTABLE_PATH"):
        browser.chromium_or_skip()
    with sync_playwright() as pw:
        engine = browser_launch.launch(pw)
        context = engine.new_context(viewport={"width": width, "height": 1100})
        page = context.new_page()
        errors, requests, calculations = [], [], []
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.on("dialog", lambda dialog: dialog.accept())

        def record(request):
            path = urlparse(request.url).path
            if path in CALCULATIONS or path == "/mo/vri-compensation":
                requests.append(path)

        page.on("request", record)
        page.on("response", lambda response: calculations.append(response.status)
                if urlparse(response.url).path in CALCULATIONS else None)
        page.route("**/*", lambda route: route.continue_()
                   if route.request.url.startswith(base) or route.request.url.startswith("data:")
                   else route.abort())
        try:
            page.goto(base, wait_until="domcontentloaded")
            browser.wait_for_result(page)
            page.evaluate(SETUP)
            page.evaluate("()=>settledCalculate()")
            browser.wait_for_result(page)
            browser.open_vri(page)
            yield page, requests, accesses
            assert calculations and all(status == 200 for status in calculations)
            assert not errors
        finally:
            context.close()
            engine.close()


@pytest.mark.parametrize("width", [390, 1440])
def test_full_page_keeps_draft_through_derived_render_then_applies_and_reopens(served, width):
    from playwright.sync_api import expect

    with full_page(served, width) as (page, requests, accesses):
        panel = page.locator("#moVriReliefPanel")
        expect(panel).to_be_visible()
        expect(page.locator("#mpt-benefit-panel")).to_be_hidden()
        expect(page.locator("#moCompensation")).to_have_count(1)
        expect(page.locator("#moVriGross")).to_have_value("")
        before = page.evaluate(READ)
        assert before["region"] == "mo" and before["partial"] is False
        assert before["offset"] == 30 and before["transfer"] == 2000
        assert len(before["phasing"]["phases"]) == 2
        page.locator("#moVriGross").fill("100")
        page.locator("#moCompensation").fill("10")
        # Ничего не подменено: настоящий calculate дополняет производный ТЭП.
        page.evaluate("()=>settledCalculate()")
        browser.wait_for_result(page)
        browser.open_vri(page)
        expect(page.locator("#moVriGross")).to_have_value("100")
        expect(page.locator("#moCompensation")).to_have_value("10")
        expect(page.locator("#moVriApplyButton")).to_be_disabled()
        page.locator("#moVriPreviewButton").click()
        expect(page.locator("#moVriApplyButton")).to_be_enabled()
        assert requests.count("/mo/vri-compensation") == 1
        preview = page.evaluate(READ)
        for key in ("fee", "compensation", "offset", "transfer", "tep", "phasing"):
            assert preview[key] == before[key], key
        previous_calculations = sum(path in CALCULATIONS for path in requests)
        with page.expect_response(lambda response: urlparse(response.url).path in CALCULATIONS):
            page.locator("#moVriApplyButton").click()
        browser.wait_for_result(page)
        applied = page.evaluate(READ)
        assert applied["fee"] == 90 and applied["compensation"] == 10
        assert applied["offset"] == 30 and applied["transfer"] == 2000
        assert applied["tep"] == before["tep"] and applied["phasing"] == before["phasing"]
        assert applied["proof"]["schema"] == 1
        assert applied["proof"]["vri"]["payment_before_compensation_rub"] == 100_000_000
        assert applied["proof"]["vri"]["payment_after_reliefs_rub"] == 60_000_000
        assert sum(path in CALCULATIONS for path in requests) > previous_calculations
        assert applied["idle"] and applied["result"] and applied["run"] == applied["settled"]
        saved = page.evaluate("""async()=>{
          const payload=JSON.parse(JSON.stringify(projectStorePayload().payload));
          applyProjectSnapshot(JSON.parse(JSON.stringify(payload)));
          await settledCalculate();openTab('vri');return payload;
        }""")
        browser.wait_for_result(page)
        browser.open_vri(page)
        reopened = page.evaluate(READ)
        for key in ("fee", "compensation", "offset", "transfer", "tep", "phasing", "proof"):
            assert reopened[key] == applied[key], key
        assert saved["inputs"]["land_rights_cost_mln"] == 90
        expect(page.locator("#moVriGross")).to_have_value("100")
        expect(panel).to_be_visible()
        expect(page.locator("#mpt-benefit-panel")).to_be_hidden()
        assert not reopened["overflow"]
        assert any(row["synthetic_key"] for row in accesses)


@pytest.mark.parametrize("change", ["offset", "tep", "project"])
def test_full_page_rejects_old_preview_and_isolates_a_replaced_project(served, change):
    from playwright.sync_api import expect

    with full_page(served, 1440) as (page, requests, _):
        page.locator("#moVriGross").fill("100")
        page.locator("#moCompensation").fill("10")
        # Задерживается лишь доставка настоящего server Response; producer,
        # renderInputs/renderTep и calculate остаются реальными.
        page.evaluate("""()=>{
          window.moTestFetch=window.fetch.bind(window);
          window.fetch=async(...args)=>{
            const response=await window.moTestFetch(...args);
            if(args[0]==='/mo/vri-compensation')
              await new Promise(resolve=>{window.moTestRelease=resolve});
            return response;
          };
          window.moTestPending=previewMoVriRelief();return true;
        }""")
        page.wait_for_function("()=>typeof window.moTestRelease==='function'")
        if change == "project":
            page.evaluate("""()=>{
              const payload=JSON.parse(JSON.stringify(projectStorePayload().payload));
              payload.inputs._project_uid='another-fictional-mo';
              payload.inputs.land_rights_cost_mln=444;
              delete payload.inputs._mo_vri_relief;delete payload.inputs._mo_calc;
              applyProjectSnapshot(payload);
            }""")
        elif change == "tep":
            page.evaluate("()=>tepCellChanged('apartments','transfer','2100')")
        else:
            page.locator("#f_vri_transfer_offset_mln").fill("50")
            page.locator("#f_vri_transfer_offset_mln").press("Tab")
        page.evaluate("()=>settledCalculate()")
        browser.wait_for_result(page)
        browser.open_vri(page)
        if change == "project":
            expect(page.locator("#moVriGross")).to_have_value("")
            expect(page.locator("#moCompensation")).to_have_value("")
        else:
            expect(page.locator("#moVriGross")).to_have_value("100")
            expect(page.locator("#moCompensation")).to_have_value("10")
        before_response = page.evaluate(READ)
        page.evaluate("()=>window.moTestRelease()")
        page.evaluate("async()=>await window.moTestPending")
        expect(page.locator("#moVriApplyButton")).to_be_disabled()
        page.evaluate("()=>applyMoVriRelief()")
        after_response = page.evaluate(READ)
        for key in ("fee", "compensation", "offset", "transfer", "tep", "phasing", "proof"):
            assert after_response[key] == before_response[key], key
        assert after_response["fee"] == (444 if change == "project" else 1000)
        assert requests.count("/mo/vri-compensation") == 1


def test_full_page_reset_clears_mo_draft_and_rejects_its_late_response(served):
    from playwright.sync_api import expect

    with full_page(served, 390) as (page, requests, _):
        page.locator("#moVriGross").fill("100")
        page.locator("#moCompensation").fill("10")
        page.evaluate("""()=>{
          window.moResetFetch=window.fetch.bind(window);
          window.fetch=async(...args)=>{
            const response=await window.moResetFetch(...args);
            if(args[0]==='/mo/vri-compensation')
              await new Promise(resolve=>{window.moResetRelease=resolve});
            return response;
          };
          window.moResetPending=previewMoVriRelief();return true;
        }""")
        page.wait_for_function("()=>typeof window.moResetRelease==='function'")
        old_run = page.evaluate("moVriReliefRun")
        page.evaluate("()=>resetAll()")
        cleared = page.evaluate("""()=>({
          owner:moVriReliefOwner,project:moVriReliefProjectKey,model:moVriReliefModelKey,
          preview:moVriReliefPreview,source:moVriReliefBaseSource,
          grossEdited:moVriReliefGrossEdited,compEdited:moVriReliefCompEdited,
          run:moVriReliefRun,proof:inputs._mo_vri_relief||null,
          gross:document.getElementById('moVriGross').value,
          compensation:document.getElementById('moCompensation').value})""")
        assert cleared == {"owner": None, "project": "", "model": "", "preview": None,
                           "source": None, "grossEdited": False, "compEdited": False,
                           "run": cleared["run"], "proof": None, "gross": "", "compensation": ""}
        assert cleared["run"] > old_run
        page.evaluate("()=>window.moResetRelease()")
        page.evaluate("async()=>await window.moResetPending")
        page.evaluate("()=>{inputs.vri_region='mo';renderInputs();openTab('vri')}")
        expect(page.locator("#moVriGross")).to_have_value("")
        expect(page.locator("#moCompensation")).to_have_value("")
        expect(page.locator("#moVriApplyButton")).to_be_disabled()
        assert page.evaluate("inputs._mo_vri_relief||null") is None
        assert requests.count("/mo/vri-compensation") == 1
