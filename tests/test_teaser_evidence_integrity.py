"""Counterexamples: source evidence, conflicts and the exact engine packet."""
import json

import pytest

import document_intake as di
import intake_evidence
import teaser_card as tc


def field(value, quote, key="purchase_price_mln", unit="млн ₽"):
    return {"key": key, "value": value, "quote": quote, "unit": unit}


def check(fields, text):
    return intake_evidence.validate(di.parse_intake(json.dumps({"fields": fields})), {"text": text})


@pytest.mark.parametrize("candidate,text", [
    (field(900, "Цена 400 млн руб."), "Цена 400 млн руб."),
    (field(900, "Цена 900 млн руб."), "Цена 400 млн руб."),
    (field(400, "Цена 400 руб."), "Цена 400 руб."),
    (field(-1, "Цена -1 млн руб."), "Цена -1 млн руб."),
    (field(float("inf"), "Цена 400 млн руб."), "Цена 400 млн руб."),
    (field("1.5", "Паркинг 1.5 мест", "underground_manual_spaces", "мест"), "Паркинг 1.5 мест"),
    (field("77:01:0005017:20", "77:01:0005017:56", "cadastral_numbers", "список"), "77:01:0005017:56"),
    (field(400, "Цена 400 млн руб. | выдуманный хвост"), "Цена 400 млн руб."),
    (field(100, "Паркинг 100 мест", "apartments_gns_sqm", "м²"), "Паркинг 100 мест"),
    (field(100, "Цена 100 млн руб.", "underground_manual_spaces", "мест"), "Цена 100 млн руб."),
    (field(100, "Площадь 100 акров", "apartments_gns_sqm", "м²"), "Площадь 100 акров"),
    (field(100, "Поликлиника 100 мест", "clinic_capacity", "пос./смену"), "Поликлиника 100 мест"),
    (field(400, "Стоимость 400 млн USD"), "Стоимость 400 млн USD"),
    (field(400, "Площадь 400 млн м²"), "Площадь 400 млн м²"),
    (field(400, "Стоимость 400 млн ₽/м²"), "Стоимость 400 млн ₽/м²"),
    (field(400, "Стоимость 400 млн ₽ за гектар"), "Стоимость 400 млн ₽ за гектар"),
    (field(400, "Стоимость 400 млн ₽ на м²"), "Стоимость 400 млн ₽ на м²"),
    (field(400, "Стоимость 400 млн ₽ за место"), "Стоимость 400 млн ₽ за место"),
])
def test_a_candidate_without_matching_source_is_never_an_engine_fact(candidate, text):
    got = check([candidate], text)
    assert not got["fields"]
    assert got["unverified"][0]["reason"]
    state = tc.start({"fields": [candidate]}, {"text": text}, "teaser.pdf", presets={}, current_class="")
    card = tc.build(state, {}, {}, spp_split={}, presets={}, defaults={})
    assert not card["to_engine"]
    assert card["refused"]


@pytest.mark.parametrize("candidate,text", [
    (field("1,2", "Цена 1,2 млрд руб.", unit="млрд руб."), "Цена 1,2 млрд руб."),
    (field(400, "Цена 400 млн руб.; ВРИ 2 млрд руб."), "Цена 400 млн руб.; ВРИ 2 млрд руб."),
    (field("10 000", "Площадь 1 га", key="offices_gba_sqm", unit="м²"), "Площадь 1 га"),
    (field("100", "Паркинг 100 мест", key="underground_manual_spaces", unit="мест"), "Паркинг 100 мест"),
])
def test_matching_facts_keep_the_source_and_server_normalization(candidate, text):
    got = check([candidate], text)
    assert len(got["fields"]) == 1
    assert got["fields"][0]["source_checked"]
    assert not got["unverified"]


@pytest.mark.parametrize('key',['apartments_gns_sqm','residential_spp_sqm'])
def test_saleable_area_is_retained_as_a_source_fact_and_never_becomes_gns(key):
    quote='Продаваемая площадь квартир 12 340 м²'
    got=check([field('12 340',quote,key=key,unit='м²')],'[стр. 2]\n'+quote)
    assert not got['fields']
    refused=got['unverified'][0]
    assert refused['refusal_code']=='saleable_area'
    assert refused['source_fact']=={'kind':'saleable_area','value':'12 340',
        'unit':'м²','quote':quote,'page':2}
    assert quote in got['notes'][0] and 'стр. 2' in got['notes'][0]
    state=tc.start(got,{'text':'[стр. 2]\n'+quote},'source.pdf',presets={},current_class='')
    card=tc.build(state,{}, {},spp_split={},presets={},defaults={})
    assert not card['to_engine'] and card['refused'][0]['refusal_code']=='saleable_area'


def test_generic_project_spp_cannot_be_assigned_to_the_residential_house():
    quote='ПАРАМЕТРЫ ПРОЕКТА. СПП в ГНС 23 450 м²'
    got=check([field('23 450',quote,key='residential_spp_sqm',unit='м²')],'[стр. 3]\n'+quote)
    assert not got['fields']
    assert got['unverified'][0]['refusal_code']=='unscoped_project_area'
    assert got['unverified'][0]['source_fact']['page']==3
    assert quote in got['notes'][0]


def test_explicit_residential_house_spp_keeps_its_verified_source():
    quote='СПП жилого дома целиком (квартиры и коммерция) 23 450 м²'
    got=check([field('23 450',quote,key='residential_spp_sqm',unit='м²')],'[стр. 3]\n'+quote)
    assert len(got['fields'])==1 and not got['unverified']


def test_area_basis_notes_do_not_turn_a_missing_quote_into_a_verified_source_fact():
    candidate=field('12 340','Продаваемая площадь квартир 12 340 м²',key='apartments_gns_sqm',unit='м²')
    got=check([candidate],'[стр. 1]\nДругой документ без такой площади')
    assert not got['fields'] and 'source_fact' not in got['unverified'][0]
    assert not got['notes']


@pytest.mark.parametrize('value,accepted',[('10 000',True),('8 000',False)])
def test_gns_and_saleable_labels_in_one_quote_keep_their_own_source_amount(value,accepted):
    quote='ГНС квартир 10 000 м²; продаваемая площадь квартир 8 000 м²'
    got=check([field(value,quote,key='apartments_gns_sqm',unit='м²')],'[стр. 1]\n'+quote)
    assert bool(got['fields'])==accepted
    if not accepted:assert got['unverified'][0]['refusal_code']=='saleable_area'


def test_implementing_a_project_does_not_rename_its_explicit_gns_to_saleable_area():
    quote='ГНС квартир реализуемого проекта 10 000 м²'
    got=check([field('10 000',quote,key='apartments_gns_sqm',unit='м²')],'[стр. 1]\n'+quote)
    assert len(got['fields'])==1 and not got['unverified']


def test_conflicts_require_a_choice_and_are_not_order_dependent():
    fields = [field(400, "Цена 400 млн руб."), field(450, "Цена 450 млн руб.")]
    text = "[стр. 1]\nЦена 400 млн руб.\nЦена 450 млн руб."
    for candidates in (fields, list(reversed(fields))):
        state = tc.start({"fields": candidates}, {"text": text}, "teaser.pdf", presets={}, current_class="")
        card = tc.build(state, {}, {}, spp_split={}, presets={}, defaults={})
        assert not card["to_engine"]
        assert not card["ready"]
        assert card["questions"]["card"]["kind"] == "source_conflict"
        chosen = next(i for i, o in enumerate(state["cards"][0]["options"]) if o["field"]["value"] == 400)
        tc.answer(state, {}, {}, index=0, action="answer", choice=chosen, spp_split={}, presets={})
        got = tc.build(state, {}, {}, spp_split={}, presets={}, defaults={})
        assert next(r["value"] for r in got["to_engine"] if r["path"] == "inputs.purchase_price_mln") == 400


def test_duplicate_facts_are_deduplicated_instead_of_summed():
    got = check([field(400, "Цена 400 млн руб."), field("0,4", "Цена 0,4 млрд руб.", unit="млрд руб.")],
                "Цена 400 млн руб.\nЦена 0,4 млрд руб.")
    assert len(got["fields"]) == 1
    assert not got["conflicts"]


@pytest.mark.parametrize("question,quote", [
    ("Инфраструктурный договор 900 млн руб. — куда отнести?", "Цена сделки 400 млн руб."),
    ("Инфраструктурный договор 400 млрд руб. — куда отнести?", "Договор 400 млн руб."),
    ("Договор 400 млн руб., 49% оплачено, 51% в феврале 2028 — куда?", "Договор 400 млн руб."),
])
def test_questions_cannot_smuggle_unverified_amounts_or_schedules(question, quote):
    extraction = di.parse_intake(json.dumps({"fields": [], "questions": [{
        "key": "", "question": question, "quote": quote,
        "options": ["В цену сделки — платится на входе", "В соцнагрузку"]}]}))
    document = {"text": "[стр. 1]\n" + quote}
    # The actual request validates once before creating the card and once at
    # the card boundary; a second pass must never restore untrusted amounts.
    state = tc.start(intake_evidence.validate(extraction, document), document, "teaser.pdf", presets={}, current_class="")
    assert state["cards"][0]["requires_manual"]
    got = tc.answer(state, {}, {}, index=0, action="answer", choice=0, spp_split={}, presets={})
    assert got["invalid"]
    assert state["index"] == 0
    assert not tc.replay(state, {}, {}, spp_split={}, presets={})["origins"]
    tc.answer(state, {}, {}, index=0, action="answer", choice=0, value="400", spp_split={}, presets={})
    replay = tc.replay(state, {}, {}, spp_split={}, presets={})
    assert replay["inputs"]["purchase_price_mln"] == 400
    assert replay["origins"]["inputs.purchase_price_mln"]["source"] == "manual"
    assert not replay["inputs"].get("purchase_schedule")


def test_all_cadastral_numbers_survive_the_local_fallback():
    from developaid_v2_account_projects import _quick_teaser_intake
    got = _quick_teaser_intake(b"", "teaser.pdf", document={"text":
        "[стр. 1]\n77:01:0005017:20\n[стр. 2]\n77:01:0005017:56", "pages": 2})
    checked = check(got["fields"], "[стр. 1]\n77:01:0005017:20\n[стр. 2]\n77:01:0005017:56")
    assert checked["fields"][0]["value"] == ["77:01:0005017:20", "77:01:0005017:56"]


@pytest.fixture
def server(monkeypatch, tmp_path):
    import main as wrapper
    core = wrapper.core
    from starlette.requests import Request
    request = Request({"type": "http", "method": "POST", "path": "/agent/document",
                       "headers": [], "query_string": b""})
    monkeypatch.setattr(core, "_PLATO_STAGE_DIR", tmp_path)
    monkeypatch.setattr(core, "_require_web_access", lambda *_a: None)
    monkeypatch.setattr(core, "usage_track", lambda *_a, **_k: None)
    return core, request


def test_apply_uses_the_owned_ready_card_and_rechecks_all_inputs(server):
    core, request = server
    actor = core._agent_bind_actor(core.AgentDocumentRequest(), request, private_surface="web")
    inputs, tep = dict(core.DEFAULT_INPUTS), core.copy.deepcopy(core.TEP_DEFAULT)
    card = core._intake_queue_start("teaser.pdf", {"fields": [field(400, "Цена 400 млн руб.")]},
                                     {"text": "[стр. 1]\nЦена 400 млн руб."}, inputs, tep, actor=actor)
    # Class is a question, not an implicit import assumption.
    with pytest.raises(core.HTTPException, match="") as exc:
        core.agent_document_apply(core.AgentDocumentApplyRequest(intake_id=card["id"], card_key=card["card_key"], inputs=inputs, tep=tep), request)
    assert exc.value.status_code == 409
    core.agent_document_answer(core.AgentDocumentAnswerRequest(intake_id=card["id"], index=0, choice=0, inputs=inputs, tep=tep,
        queue_revision=card["queue_revision"], question_token=card["question_token"]), request)
    card = core.agent_document_card(core.AgentDocumentCardRequest(intake_id=card["id"], inputs=inputs, tep=tep), request)
    req = core.AgentDocumentApplyRequest(intake_id=card["id"], card_key=card["card_key"], inputs=inputs, tep=tep)
    applied = core.agent_document_apply(req, request)
    assert applied["inputs"]["purchase_price_mln"] == 400
    assert "inputs.purchase_price_mln" in applied["inputs"]["_field_origin"]
    assert core.agent_document_apply(req, request)["inputs"]["purchase_price_mln"] == 400
    changed = req.model_copy(update={"inputs": {**inputs, "construction_months": 99}})
    assert core.agent_document_apply(changed, request)["stale"] is True


def test_another_browser_cannot_apply_the_card(server):
    core, request = server
    actor = core._agent_bind_actor(core.AgentDocumentRequest(), request, private_surface="web")
    card = core._intake_queue_start("teaser.pdf", {"fields": []}, {"text": ""}, {}, {}, actor=actor)
    from starlette.requests import Request
    stranger = Request({"type": "http", "method": "POST", "path": "/agent/document/apply",
                       "headers": [], "query_string": b""})
    with pytest.raises(core.HTTPException) as exc:
        core.agent_document_card(core.AgentDocumentCardRequest(intake_id=card["id"]), stranger)
    assert exc.value.status_code == 403


def test_client_extraction_can_no_longer_bypass_source_validation(server):
    core, request = server
    with pytest.raises(core.HTTPException) as exc:
        core.agent_document(core.AgentDocumentRequest(accept=["purchase_price_mln"],
                            extraction={"fields": [field(900, "выдуманная цитата")]}), request)
    assert exc.value.status_code == 409


def test_document_queue_failure_does_not_expose_server_details(server, monkeypatch):
    core, _ = server
    sentinel = "PRIVATE_SERVER_PATH_SENTINEL"
    def fail(_queue):
        raise OSError(sentinel)
    monkeypatch.setattr(core, "_intake_queue_save", fail)
    with pytest.raises(core.HTTPException) as failed:
        core._intake_queue_start("teaser.pdf", {"fields": []}, {"text": ""}, {}, {})
    assert failed.value.status_code == 503
    assert sentinel not in str(failed.value.detail)


@pytest.mark.parametrize("gns", [31000, 100.25, 100.26])
def test_gns_import_updates_stale_dependants_in_the_actual_engine(server, gns):
    core, request = server
    actor = core._agent_bind_actor(core.AgentDocumentRequest(), request, private_surface="web")
    inputs, tep = dict(core.DEFAULT_INPUTS), core.copy.deepcopy(core.TEP_DEFAULT)
    before = tep["apartments"]["saleable"]
    quote = f"Квартиры {gns} м²"
    card = core._intake_queue_start("teaser.pdf", {"fields": [field(gns, quote, "apartments_gns_sqm", "м²")]},
        {"text": "[стр. 1]\n" + quote}, inputs, tep, actor=actor)
    core.agent_document_answer(core.AgentDocumentAnswerRequest(intake_id=card["id"], index=0, choice=0, inputs=inputs, tep=tep,
        queue_revision=card["queue_revision"], question_token=card["question_token"]), request)
    card = core.agent_document_card(core.AgentDocumentCardRequest(intake_id=card["id"], inputs=inputs, tep=tep), request)
    applied = core.agent_document_apply(core.AgentDocumentApplyRequest(intake_id=card["id"], card_key=card["card_key"], inputs=inputs, tep=tep), request)
    assert applied["tep"]["apartments"]["gns"] == gns
    assert applied["tep"]["apartments"]["saleable"] != before
    result = core.calculate(core.CalcRequest(inputs=applied["inputs"], tep=applied["tep"], rates=[]))
    row = next(row for row in result["tep"]["rows"] if row["key"] == "apartments")
    assert row["gns"] == gns
    assert row["saleable"] == applied["tep"]["apartments"]["saleable"]


def test_document_extraction_has_no_calculation_or_agent_tools(server, monkeypatch):
    core, request = server
    monkeypatch.setattr(core, "_agent_rate_limit", lambda *_a: None)
    monkeypatch.setattr(core, "_run_authoritative_model", lambda *_a: pytest.fail("extraction calculated project economics"))
    payloads = []
    def model(payload, *, budget_seconds=None):
        assert 0 < budget_seconds <= 240
        payloads.append(payload)
        return {"status": "completed", "output": [{"type": "message", "content": [
            {"type": "output_text", "text": '{"fields":[],"questions":[],"notes":[]}'}]}]}
    monkeypatch.setattr(core, "_openai_responses_request", model)
    req = core.AgentChatRequest(message="read document", inputs=dict(core.DEFAULT_INPUTS),
                                 tep=core.TEP_DEFAULT, scenario="document_intake")
    _, done, outcome = core._plato_chat_launch(req, request)
    assert done.wait(5)
    assert "error" not in outcome
    assert payloads[0]["text"]["format"]["strict"]
    assert "tools" not in payloads[0]


def test_document_jobs_are_bounded_and_release_capacity(server, monkeypatch):
    import threading
    core, request = server
    release = threading.Event()
    monkeypatch.setattr(core, "_DOCUMENT_JOBS", threading.BoundedSemaphore(2))
    monkeypatch.setattr(core, "_agent_rate_limit", lambda *_a: None)
    def read(*_a):
        assert release.wait(5)
        return {"reason": "synthetic result"}
    monkeypatch.setattr(core, "agent_document", read)
    started = []
    try:
        for _ in range(2):
            started.append(core.agent_document_start(core.AgentDocumentRequest(), request))
        with pytest.raises(core.HTTPException) as exc:
            core.agent_document_start(core.AgentDocumentRequest(), request)
        assert exc.value.status_code == 429
    finally:
        release.set()
        names = {"document-" + row["trace_id"] for row in started}
        for thread in threading.enumerate():
            if thread.name in names:
                thread.join(5)
    assert core._DOCUMENT_JOBS.acquire(blocking=False)
    core._DOCUMENT_JOBS.release()


def test_shared_document_poll_transmits_the_same_identity_headers(server):
    import subprocess
    core, _ = server
    source = core.document_client_script().body.decode()
    script = """const window={};const calls=[];
const setTimeout=fn=>fn();let step=0;
const fetch=async(url,init)=>{calls.push({url,init});
if(url===window.PlatoDocumentProtocol.capabilityPath)return{ok:true,json:async()=>({schema:1,protocol:window.PlatoDocumentProtocol.protocol})};
const values=[{trace_id:'abc'},
{pending:true},{pending:false,card:{id:'intake'}}];return{ok:true,json:async()=>values[step++]}};
""" + source + """
window.PlatoDocumentClient.read({session:'synthetic-session',access_key:'synthetic-key'}).then(result=>{
 console.log(JSON.stringify({result,calls}));
});"""
    got = json.loads(subprocess.check_output(["node", "-e", script], text=True))
    assert got["result"]["card"]["id"] == "intake"
    assert len(got["calls"]) == 4
    assert got["calls"][0] == {"url": core.document_protocol.CAPABILITY_PATH, "init": {"cache": "no-store"}}
    started = got["calls"][1]
    assert started["url"] == "/agent/document/start" and started["init"]["method"] == "POST"
    assert json.loads(started["init"]["body"]) == {"session": "synthetic-session", "access_key": "synthetic-key"}
    for call in got["calls"][2:]:
        assert call["init"]["headers"] == {"x-plato-session": "synthetic-session", "x-developaid-admin-key": "synthetic-key"}
        assert call["url"] == "/agent/result/abc" and call["init"]["cache"] == "no-store"
    assert all("synthetic-key" not in call["url"] and "synthetic-session" not in call["url"] for call in got["calls"])


def test_shared_document_poll_keeps_its_deadline_after_protocol_preflight(server):
    import subprocess
    core, _ = server
    source = core.document_client_script().body.decode()
    script = """const window={};const calls=[];const ticks=[0,1,600000];
const Date={now:()=>ticks.shift()};const setTimeout=fn=>fn();
const fetch=async(url,init)=>{calls.push({url,init});
if(url===window.PlatoDocumentProtocol.capabilityPath)return{ok:true,json:async()=>({schema:1,protocol:window.PlatoDocumentProtocol.protocol})};
return{ok:true,json:async()=>url==='/agent/document/start'?{trace_id:'deadline'}:{pending:true}}};
""" + source + """
window.PlatoDocumentClient.read({session:'synthetic-session',access_key:'synthetic-key'}).then(()=>{throw new Error('deadline did not hold')},error=>{
 console.log(JSON.stringify({error:error.message,calls}));
});"""
    got = json.loads(subprocess.check_output(["node", "-e", script], text=True))
    assert got["error"] == "Разбор не завершился за отведённое время. Пришлите нужные страницы отдельно."
    assert [call["url"] for call in got["calls"]] == [core.document_protocol.CAPABILITY_PATH, "/agent/document/start", "/agent/result/deadline"]
    assert got["calls"][2]["init"]["headers"] == {"x-plato-session": "synthetic-session", "x-developaid-admin-key": "synthetic-key"}
    assert all("synthetic-key" not in call["url"] for call in got["calls"])


@pytest.mark.parametrize("public", [True, False])
def test_async_document_keeps_public_source_failure_but_masks_internal_error(server, monkeypatch, public):
    import threading
    core, request = server
    done = threading.Event()
    monkeypatch.setattr(core, "_agent_rate_limit", lambda *_a: None)
    def fail(*_a):
        if public:
            exc = core.HTTPException(504, "Время загрузки документа по ссылке истекло.")
            exc.document_public = True
            raise exc
        raise RuntimeError("PRIVATE_INTERNAL_SENTINEL")
    monkeypatch.setattr(core, "agent_document", fail)
    original = core._plato_answer_put
    def save(key, payload):
        original(key, payload)
        done.set()
    monkeypatch.setattr(core, "_plato_answer_put", save)
    job = core.agent_document_start(core.AgentDocumentRequest(), request)
    assert done.wait(5)
    got = core.agent_result(job["trace_id"], request)
    assert "PRIVATE_INTERNAL_SENTINEL" not in got["error"]
    if public:
        assert got["error"] == "Время загрузки документа по ссылке истекло."
