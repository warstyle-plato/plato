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
    core.agent_document_answer(core.AgentDocumentAnswerRequest(intake_id=card["id"], index=0, choice=0, inputs=inputs, tep=tep), request)
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
