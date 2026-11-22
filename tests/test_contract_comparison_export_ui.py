"""Actual Monitor JS selection/download protocol plus two browser downloads."""
import io
import json

from openpyxl import load_workbook
import pytest

from developaid_monitor_page import MONITOR_PAGE
import developaid_contract_comparison_export as export
from tests import page_blocks
from tests.test_contract_comparison_export import native_card, PROJECT, CUT


@pytest.mark.parametrize("case", ["download", "filter_changed", "denied"])
def test_node_actual_page_exports_only_native_selected_tokens_and_drops_stale_download(case):
    cached = native_card()
    cached["comparison"]["lines"][0]["name"] = "Ёж и кладка"
    cached["comparison_export"] = export.bind_snapshot(PROJECT, CUT, "c" * 64, cached, {})
    state, binding = cached["comparison"], {**cached["comparison_export"], "ticket": "a" * 32, "id": "c" * 64}
    prelude = "const contractComparisonState=" + json.dumps(state, ensure_ascii=False) + ";\n"
    prelude += "const contractComparisonExport=" + json.dumps(binding, ensure_ascii=False) + ";\n"
    prelude += r"""
const widgets={contractComparisonExport:{isConnected:true,disabled:false},contractComparisonFilter:{value:'behind'},contractComparisonSearch:{value:'ёЖ'}};
function $(id){return widgets[id]};let live=true,authEpoch=1,calls=[],downloads=[],messages=[],checks=[];
function hasAuth(){return live};function requireLogin(){throw Error('unexpected login')};
function cumulativeContext(){return{project:'Учебный проект',cut:'2026-03-05',key:'synthetic-key',session:'synthetic-owner'}};
function sameCumulativeContext(){return live};function msg(...args){messages.push(args)};
function checkAuthResponse(r,d,key,epoch){checks.push([r.status,key,epoch]);if(r.status===403)live=false};
const URL={createObjectURL:()=>{downloads.push('blob-created');return'blob:local'},revokeObjectURL:()=>{}};
const document={body:{appendChild:()=>{}},createElement:()=>({click(){downloads.push(this.download)},remove(){}})};
let deliver;const ok={ok:true,status:200,headers:{get:()=> 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'},blob:async()=>({size:20})};
globalThis.fetch=(path,options)=>{calls.push({path,method:options.method,body:JSON.parse(options.body)});return new Promise(resolve=>deliver=resolve)};
"""
    tail = r"""
(async()=>{const pending=exportContractComparison();
CASE
await pending;console.log(JSON.stringify({calls,downloads,checks,disabled:widgets.contractComparisonExport.disabled}));})().catch(e=>{console.error(e);process.exit(1)});
"""
    action = {"download": "deliver(ok);", "filter_changed": "widgets.contractComparisonFilter.value='all';deliver(ok);",
              "denied": "deliver({ok:false,status:403,json:async()=>({detail:'Нет доступа'})});"}[case]
    result = page_blocks.run_json(prelude, tail.replace("CASE", action), page=MONITOR_PAGE)
    assert len(result["calls"]) == 1
    request = result["calls"][0]
    assert request["path"] == "/monitor/contracts/comparison.xlsx" and request["method"] == "POST"
    assert request["body"]["selected_tokens"] == [binding["row_tokens"][0]]
    assert not ({"rows", "planned", "fact", "deviation"} & request["body"].keys())
    assert "synthetic" not in request["path"]
    if case == "download":
        assert result["downloads"] == ["blob-created", "contract-plan-fact-2026-03-05.xlsx"]
    else:
        assert result["downloads"] == []
    if case == "denied":
        assert result["checks"] == [[403, "synthetic-key", 1]]
    else:
        assert result["disabled"] is False


def _browser_export(page, cached, contract_id, key, calls):
    cached["contract_id"] = contract_id
    cached["comparison_export"] = export.bind_snapshot(PROJECT, CUT, contract_id, cached, {"contract": "Т-1"})
    def documents(route):
        body = route.request.post_data_json
        assert body["project"] == PROJECT and body["cut"] == CUT and body["contract_id"] == contract_id
        route.fulfill(json={**cached, "ticket": body["ticket"]})
    def download(route):
        body = route.request.post_data_json
        calls.append(body)
        assert body["key"] == key and "rows" not in body
        meta, comparison, rows = export.select_snapshot(cached, body["project"], body["cut"], body["contract_id"],
                                                       body["revision"], body["selected_tokens"])
        raw = export.workbook(meta, comparison, rows, query=body["query"], filter=body["filter"])
        route.fulfill(body=raw, content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                      headers={"Content-Disposition": 'attachment; filename="contract-plan-fact.xlsx"'})
    page.route("**/monitor/contracts/documents", documents)
    page.route("**/monitor/contracts/comparison.xlsx", download)
    page.locator("#cut").fill(CUT)
    page.locator("#contractsTab").click()
    page.locator(f'tr[data-contract-id="{contract_id}"] .contract-open').click()
    page.locator("#contractComparisonExport").wait_for(state="visible")


def test_node_normal_reopen_uses_a_fresh_ticket_after_a_legacy_completed_result():
    prelude = r"""
let calls=[],counter=0;function cumulativeNonce(){return String(++counter).repeat(32)};
async function post(path,body){calls.push(body.ticket);return{pending:false,ok:true,ticket:body.ticket,...(calls.length===2?{comparison_export:{available:true}}:{})}};
async function cumulativePause(){throw Error('unexpected poll')};
"""
    # The generic extractor stops at the default options={} argument. Take
    # the complete native declaration, including its multi-line body.
    start = MONITOR_PAGE.index("async function cumulativeJob(")
    end = MONITOR_PAGE.index("\nfunction sourceLabel(", start)
    prelude += MONITOR_PAGE[start:end] + "\n"
    tail = r"""
(async()=>{const old=await cumulativeJob('/documents','/result',{project:'Synthetic'},()=>true);
const fresh=await cumulativeJob('/documents','/result',{project:'Synthetic'},()=>true);
console.log(JSON.stringify({tickets:calls,oldHasBinding:!!old.comparison_export,freshHasBinding:!!fresh.comparison_export}));})();
"""
    result = page_blocks.run_json(prelude, tail, page=MONITOR_PAGE)
    assert result == {"tickets": ["1" * 32, "2" * 32], "oldHasBinding": False, "freshHasBinding": True}


@pytest.mark.parametrize("status", [307, 308])
def test_node_export_refuses_redirect_before_replaying_credentials(status):
    prelude = "const redirectStatus=" + str(status) + ";\n" + r"""
let authEpoch=1,calls=[],forwarded=[],downloads=[];
const contractComparisonState={lines:[]};
const contractComparisonExport={available:true,ticket:'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa',id:'cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc',revision:'dddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddd',cut:'2026-03-05',row_tokens:[]};
const widgets={contractComparisonExport:{isConnected:true,disabled:false},contractComparisonFilter:{value:'all'},contractComparisonSearch:{value:''}};
function $(id){return widgets[id]}function hasAuth(){return true}function requireLogin(){throw Error('Unexpected login')}
function cumulativeContext(){return{project:'Synthetic',cut:'2026-03-05',key:'synthetic-redirect-admin',session:'synthetic-redirect-owner'}};
function sameCumulativeContext(){return true}function msg(){}function checkAuthResponse(){};
const URL={createObjectURL(){downloads.push('blob');return'blob:local'},revokeObjectURL(){}};
const document={body:{appendChild(){}},createElement(){return{click(){downloads.push('download')},remove(){}}}};
// Model Fetch's 307/308 default-follow body replay; no actual transport.
globalThis.fetch=async(path,options)=>{
 calls.push({path,redirect:options.redirect||'follow',status:redirectStatus});
 if(options.redirect==='error')throw new TypeError('Synthetic redirect refused');
 forwarded.push({origin:'https://foreign.invalid',body:JSON.parse(options.body)});
 return{ok:true,status:200,headers:{get(){return'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'}},blob:async()=>({size:20})};
};
const deny=()=>{throw Error('Actual transport forbidden')};
require('http').request=deny;require('https').request=deny;require('net').connect=deny;require('dns').lookup=deny;
"""
    tail = r"""
(async()=>{await exportContractComparison();console.log(JSON.stringify({calls,forwarded,downloads,disabled:widgets.contractComparisonExport.disabled}));})().catch(e=>{console.error(e);process.exit(1)});
"""
    result = page_blocks.run_json(prelude, tail, page=MONITOR_PAGE)
    assert result["calls"] == [{"path": "/monitor/contracts/comparison.xlsx", "redirect": "error", "status": status}]
    assert result["forwarded"] == [] and result["downloads"] == [] and result["disabled"] is False


def test_browser_download_contains_only_the_current_shown_plan_fact_rows(tmp_path):
    from playwright.sync_api import expect
    from tests.test_monitor_cumulative_controls import browser_page, CONTRACT, KEY
    cached, calls = native_card(), []
    with browser_page(1440) as (page, _, errors):
        _browser_export(page, cached, CONTRACT, KEY, calls)
        page.locator("#contractComparisonSearch").fill("нулевым")
        expect(page.locator("#contractComparisonRows tr[data-comparison-code]")).to_have_count(1)
        with page.expect_download() as got:
            page.locator("#contractComparisonExport").click()
        path = tmp_path / "shown.xlsx"
        got.value.save_as(path)
        sheet = load_workbook(path).active
        texts = [str(c.value) for row in sheet for c in row if c.value is not None]
        assert any("Работа с нулевым фактом" in text for text in texts)
        assert not any("Кладка стен" in text for text in texts)
        assert len(calls) == 1 and len(calls[0]["selected_tokens"]) == 1
        assert not errors


def test_browser_download_without_a_plan_names_the_reason_instead_of_zero(tmp_path):
    from playwright.sync_api import expect
    from tests.test_monitor_cumulative_controls import browser_page, CONTRACT, KEY
    cached, calls = native_card(empty=True), []
    with browser_page(390) as (page, _, errors):
        _browser_export(page, cached, CONTRACT, KEY, calls)
        expect(page.locator("#contractComparisonExport")).to_be_enabled()
        with page.expect_download() as got:
            page.locator("#contractComparisonExport").click()
        path = tmp_path / "unknown.xlsx"
        got.value.save_as(path)
        sheet = load_workbook(path).active
        assert any("нет действующей редакции плана" in str(c.value) for row in sheet for c in row)
        assert calls[0]["selected_tokens"] == [] and not errors
