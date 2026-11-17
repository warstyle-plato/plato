"""Сохранённый МО-проект: настоящая панель PAGE, отдельное применение и устаревшие ответы."""
from __future__ import annotations

import json
import os
from pathlib import Path
import re

import pytest

import main_legacy as core
import normatives_registry
from tests import page_blocks
from mpt_extension import inject_mpt_panel
from test_mo_vri_fee_only import money, money_namespace, request as fee_request  # noqa: F401

MODEL = {"vri_region": "mo", "land_rights_cost_mln": 1000, "vri_transfer_offset_mln": 30,
         "vri_relief_mode": "none", "_project_uid": "fictional-mo-parcel",
         "_manual_tep_import": {"project_name": "Сохранённый проект МО"}}
TEP = {"apartments": {"gns": 12000, "saleable": 8000, "transfer": 2000}}
PHASING = {"enabled": True, "phases": [{"id": "first", "share": 0.4}, {"id": "second", "share": 0.6}]}
NODE_IDS = ["moVriReliefPanel", "moVriGross", "moCompensation", "moVriGrossSource",
            "moVriApplyButton", "moVriPreviewButton", "moVriReliefStatus", "moVriReliefResult",
            "moVriReliefTotals", "moVriCurrentFee", "moVriTransferNote", "moVriReliefSource",
            "mpt-benefit-panel"]


def state_prelude():
    return "\n".join([
        "let inputs=" + json.dumps(MODEL) + ";",
        "let tep=" + json.dumps(TEP) + ";",
        "let phasing=" + json.dumps(PHASING) + ";",
        "const INPUT_DEFAULT={vri_region:'msk'},TEP_DEFAULT=" + json.dumps(TEP) + ";",
        "let persisted=null,recalculated=0;",
        "const scenarioSelect={value:'base'};let socialPopulationNoteText='',openedProject=null;",
        "function activeSession(){return 'fictional-session'}",
        "let projectsAdminKey='fictional-owner-key';",
        "function partialTepMode(){return false}",
        "function renderInputs(){renderMoVriRelief()}",
        "function renderTep(){} function renderPhasing(){}",
        "async function calculate(){recalculated++}",
        "function persistLocalSilently(){persisted=JSON.stringify({inputs,tep,phasing,scenario:'base'})}",
        "function projectSummaryForStore(){return {}} function projectCadastral(){return []}",
        "function forgetTerritoryState(){} function renderCalculationQualification(){}",
        "function rememberDerivedTail(){} function phasingFromSaved(value){return structuredClone(value)}",
        "function seedParkingByHand(){} function adoptObjectRateKind(){} function syncOfficeClasses(){}",
        "function restoreKrtClearedVriFee(){} function syncProjectClassSelector(){} function syncProjectKindSelector(){}",
        "function renderStoredCadastralQuery(){} function renderStoredGlavapu(){} function renderStoredCadastral(){}",
        "function renderStoredLand(){} function renderStoredMo(){} function renderSitePanel(){}",
    ])


def stand(money, tail, delayed=False, status=200):
    answer = money["mo_vri_compensation_preview"](fee_request(money, vri_transfer_offset_mln=30))
    prelude = state_prelude() + "\n" + "\n".join([
        "const nodes=Object.fromEntries(" + json.dumps(NODE_IDS) + ".map(id=>[id,{id,value:'',style:{},innerHTML:'',textContent:'',disabled:false,hidden:false}]));",
        "const document={getElementById(id){return nodes[id]||null}};",
        "const ANSWER=" + json.dumps(answer, ensure_ascii=False) + ";",
        "let calls=[],releaseResponse=null;",
        "async function fetch(url,options){calls.push({url,body:JSON.parse(options.body)});"
        + ("await new Promise(resolve=>{releaseResponse=resolve});" if delayed else "")
        + "return {ok:" + ("true" if status == 200 else "false") + ",status:" + str(status)
        + ",text:async()=>JSON.stringify(" + ("ANSWER" if status == 200 else "{detail:'fictional refusal'}") + ")}}",
    ])
    out, taken = page_blocks.run(prelude, tail)
    return json.loads(out), taken, answer


def test_a_saved_mo_snapshot_shows_mo_instead_of_moscow_without_guessing_gross(money):
    shown, taken, _ = stand(money, "\n".join([
        "(async()=>{",
        "applyProjectSnapshot({inputs:" + json.dumps(MODEL) + ",tep:" + json.dumps(TEP) + ",phasing:" + json.dumps(PHASING) + "});",
        "const before=JSON.stringify({inputs,tep,phasing});await previewMoVriRelief();",
        "console.log(JSON.stringify({mo:nodes.moVriReliefPanel.style.display,mpt:nodes['mpt-benefit-panel'].hidden,",
        "gross:nodes.moVriGross.value,reason:nodes.moVriReliefStatus.textContent,calls:calls.length,unchanged:before===JSON.stringify({inputs,tep,phasing})}));",
        "})().catch(e=>{console.error(e);process.exit(1)});",
    ]))
    assert "applyProjectSnapshot" in taken and "renderMoVriRelief" in taken
    assert shown["mo"] == "" and shown["mpt"] is True
    assert shown["gross"] == "" and "плату до уменьшения" in shown["reason"]
    assert shown["calls"] == 0 and shown["unchanged"]


def test_preview_does_not_apply_and_apply_reopen_repeat_preserves_metres_and_offset(money):
    shown, taken, _ = stand(money, "\n".join([
        "(async()=>{renderMoVriRelief();const before=JSON.stringify({inputs,tep,phasing});",
        "nodes.moVriGross.value='100';moVriReliefEdited(true);nodes.moCompensation.value='10';moVriReliefEdited(false);",
        "await previewMoVriRelief();const previewUnchanged=before===JSON.stringify({inputs,tep,phasing});",
        "await applyMoVriRelief();const firstAppliedTep=JSON.stringify(tep),firstAppliedPhasing=JSON.stringify(phasing);const saved=JSON.stringify(projectStorePayload().payload);",
        "applyProjectSnapshot(JSON.parse(saved));const reopenedGross=nodes.moVriGross.value;",
        "await previewMoVriRelief();await applyMoVriRelief();",
        "console.log(JSON.stringify({previewUnchanged,fee:inputs.land_rights_cost_mln,comp:inputs.mo_vri_compensation_mln,",
        "offset:inputs.vri_transfer_offset_mln,tep,phasing,firstAppliedTep,firstAppliedPhasing,source:inputs._mo_vri_relief.source,reopenedGross,",
        "bodies:calls.map(c=>c.body),urls:calls.map(c=>c.url),recalculated}));",
        "})().catch(e=>{console.error(e);process.exit(1)});",
    ]))
    assert "projectStorePayload" in taken and "applyProjectSnapshot" in taken
    assert shown["previewUnchanged"]
    assert (shown["fee"], shown["comp"], shown["offset"]) == (90, 10, 30)
    assert json.loads(shown["firstAppliedTep"]) == TEP
    assert json.loads(shown["firstAppliedPhasing"]) == PHASING
    assert shown["tep"]["apartments"] == TEP["apartments"] and shown["phasing"] == PHASING
    assert shown["source"]["kind"] == "manual"
    assert shown["reopenedGross"] == "100"
    assert [body["payment_before_compensation_rub"] for body in shown["bodies"]] == [100_000_000] * 2
    assert all(body["session"] == "fictional-session" and body["access_key"] == "fictional-owner-key"
               for body in shown["bodies"])
    assert shown["urls"] == ["/mo/vri-compensation"] * 2


@pytest.mark.parametrize("change", [
    "inputs=Object.assign({},inputs,{_project_uid:'another-project',land_rights_cost_mln:444});renderMoVriRelief();",
    "inputs.vri_region='msk';renderMoVriRelief();",
    "nodes.moVriGross.value='200';moVriReliefEdited(true);",
    "inputs.vri_transfer_offset_mln=50;renderMoVriRelief();",
])
def test_a_late_response_after_project_region_or_base_change_cannot_apply(money, change):
    shown, _, _ = stand(money, "\n".join([
        "(async()=>{renderMoVriRelief();nodes.moVriGross.value='100';moVriReliefEdited(true);nodes.moCompensation.value='10';",
        "const pending=previewMoVriRelief();", change,
        "const before=JSON.stringify({inputs,tep,phasing});releaseResponse();await pending;await applyMoVriRelief();",
        "console.log(JSON.stringify({unchanged:before===JSON.stringify({inputs,tep,phasing}),disabled:nodes.moVriApplyButton.disabled}));",
        "})().catch(e=>{console.error(e);process.exit(1)});",
    ]), delayed=True)
    assert shown == {"unchanged": True, "disabled": True}


def test_server_refusal_preserves_the_project_and_cannot_enable_apply(money):
    shown, _, _ = stand(money, "\n".join([
        "(async()=>{renderMoVriRelief();nodes.moVriGross.value='100';moVriReliefEdited(true);nodes.moCompensation.value='10';",
        "const before=JSON.stringify({inputs,tep,phasing});await previewMoVriRelief();",
        "console.log(JSON.stringify({unchanged:before===JSON.stringify({inputs,tep,phasing}),disabled:nodes.moVriApplyButton.disabled,reason:nodes.moVriReliefStatus.textContent}));",
        "})().catch(e=>{console.error(e);process.exit(1)});",
    ]), status=401)
    assert shown["unchanged"] and shown["disabled"]
    assert "fictional refusal" in shown["reason"]


@pytest.mark.parametrize("width", [390, 1440])
def test_real_browser_component_has_a_visible_source_and_working_preview_apply(money, width):
    import browser_launch
    from browser import chromium_or_skip
    from playwright.sync_api import sync_playwright, expect

    # Один разрешитель PAGE: браузер берёт тот же автоматически собранный набор,
    # который выполнил сценарий на node, а не список функций, переписанный руками.
    _shown, taken, _ = stand(money, "\n".join([
        "(async()=>{renderMoVriRelief();nodes.moVriGross.value='100';moVriReliefEdited(true);nodes.moCompensation.value='10';",
        "await previewMoVriRelief();await applyMoVriRelief();console.log('{}')})().catch(e=>{console.error(e);process.exit(1)});",
    ]))
    start = core.PAGE.index('<details class="card" id="moVriReliefPanel"')
    end = core.PAGE.index("</details>", start) + len("</details>")
    style = re.search(r"<style[^>]*>(.*?)</style>", core.PAGE, re.S).group(0)
    script = state_prelude() + "\n" + "\n".join(page_blocks.piece(name) for name in taken)
    html = inject_mpt_panel('<!doctype html><html><head><base href="https://fixture.invalid/">' + style
                            + '</head><body><div id="vri" class="panel active">' + core.PAGE[start:end]
                            + '</div><script>' + script + '\nrenderMoVriRelief();</script></body></html>')
    if not os.environ.get("CHROMIUM_EXECUTABLE_PATH"):
        chromium_or_skip()
    with sync_playwright() as pw:
        browser = browser_launch.launch(pw)
        try:
            page = browser.new_page(viewport={"width": width, "height": 1100})
            def serve(route):
                if route.request.url.endswith("/mo/vri-compensation"):
                    dto = money["MoVriCompensationRequest"].model_validate(route.request.post_data_json)
                    route.fulfill(status=200, content_type="application/json",
                                  body=json.dumps(money["mo_vri_compensation_preview"](dto)))
                else:
                    route.fulfill(status=503, content_type="application/json", body='{"detail":"omitted in component test"}')
            page.route("**/*", serve)
            page.set_content(html)
            expect(page.locator("#moVriReliefPanel")).to_be_visible()
            page.wait_for_selector("#mpt-benefit-panel", state="attached")
            expect(page.locator("#mpt-benefit-panel")).not_to_be_visible()
            expect(page.locator("#moVriGross")).to_have_value("")
            expect(page.locator("#moVriReliefSource")).to_have_attribute("href", normatives_registry.official_link("mo-1310-vri-ksu")["url"])
            page.locator("#moVriGross").fill("100")
            page.locator("#moCompensation").fill("10")
            page.locator("#moVriPreviewButton").click()
            expect(page.locator("#moVriApplyButton")).to_be_enabled()
            assert page.evaluate("inputs.land_rights_cost_mln") == 1000
            expect(page.locator("#moVriReliefTotals")).to_contain_text("Итого основная плата")
            page.locator("#moVriApplyButton").click()
            assert page.evaluate("inputs.land_rights_cost_mln") == 90
            assert page.evaluate("JSON.stringify(tep)") == json.dumps(TEP, separators=(",", ":"))
            assert page.evaluate("inputs.vri_transfer_offset_mln") == 30
            page.evaluate("inputs.vri_region='msk';renderInputs()")
            expect(page.locator("#moVriReliefPanel")).not_to_be_visible()
            expect(page.locator("#mpt-benefit-panel")).to_be_visible()
            page.evaluate("inputs.vri_region='mo';renderInputs()")
            expect(page.locator("#moVriGross")).to_have_value("100")
            assert page.evaluate("document.documentElement.scrollWidth<=innerWidth+2")
        finally:
            browser.close()
