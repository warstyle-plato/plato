"""Exercise the actual /v2 upload, questions, stale-card gate and calculation."""
import json
import document_intake_protocol as protocol

import pytest

from browser import chromium_or_skip, serve


def prepare_teaser(monkeypatch, tmp_path, gns):
    import main_registry
    import main as wrapper
    import document_intake

    core = wrapper.core
    monkeypatch.setattr(core, "_PLATO_STAGE_DIR", tmp_path)
    monkeypatch.setattr(core, "_require_web_access", lambda *_a, **_k: None)
    monkeypatch.setattr(core, "require_calc_access", lambda *_a, **_k: {})
    monkeypatch.setattr(core, "usage_track", lambda *_a, **_k: None)
    quote = f"Цена 400 млн руб.\nКвартиры {gns} м²\nЛьгота МПТ 2,57 млрд руб."
    monkeypatch.setattr(document_intake, "extract_text", lambda _data, name:
                        {"text": "[стр. 1]\n" + quote, "pages": 1, "filename": name})
    fields = [
        {"key": "purchase_price_mln", "value": "400", "unit": "млн руб.", "quote": "Цена 400 млн руб."},
        {"key": "apartments_gns_sqm", "value": str(gns), "unit": "м²", "quote": f"Квартиры {gns} м²"},
        {"key": "vri_relief_mln", "value": "2,57", "unit": "млрд руб.", "quote": "Льгота МПТ 2,57 млрд руб."},
    ]
    monkeypatch.setattr(core, "plato_answer", lambda *_a:
                        {"answer": json.dumps({"fields": fields, "questions": [], "notes": []})})
    return main_registry.app


@pytest.mark.parametrize("width,gns", [(390, 31000), (1440, 31000), (390, 100.25)])
def test_v2_applies_only_the_ready_current_server_card(monkeypatch, tmp_path, width, gns):
    from playwright.sync_api import sync_playwright

    app = prepare_teaser(monkeypatch, tmp_path, gns)
    calculated = []
    answered = []
    with serve(app, 18371 + (width == 390)) as base:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(executable_path=str(chromium_or_skip()))
            page = browser.new_page(viewport={"width": width, "height": 900})
            errors = []
            page.on("pageerror", lambda exc: errors.append(str(exc)))
            page.on("request", lambda req: calculated.append(req.post_data_json)
                    if req.method == "POST" and req.url.endswith("/api/v2/calculate") else None)
            page.on("response", lambda response: answered.append({"request": response.request.post_data_json,
                    "status": response.status, "data": response.json()})
                    if response.url.endswith(protocol.ANSWER_PATH) else None)
            page.goto(base + "/v2", wait_until="networkidle")
            page.set_input_files("#v2TeaserUpload", {"name": "test.pdf", "mimeType": "application/pdf", "buffer": b"%PDF-test"})
            page.get_by_role("button", name="Перейти к вопросам (2)").wait_for(timeout=15000)
            assert page.locator("#v2TeaserApply").count() == 0
            assert not calculated
            page.get_by_role("button", name="Перейти к вопросам (2)").click()
            page.locator('#v2TeaserQuestion [data-teaser-choice="1"]').click()  # explicitly take relief
            page.locator("#v2TeaserQuestion").get_by_role("button", name="Бизнес", exact=True).wait_for()
            first = answered[0]
            assert first["status"] == 200
            assert first["request"]["queue_revision"] == 0
            assert len(first["request"]["question_token"]) == 64
            # A duplicate delivery of the first click cannot answer the next
            # question or change its version/token.
            duplicate = page.request.post(base + protocol.ANSWER_PATH, data=first["request"])
            assert duplicate.status == 409
            current = duplicate.json()["detail"]["card"]
            assert current["questions"]["index"] == 1
            assert current["queue_revision"] == first["data"]["card"]["queue_revision"] == 1
            assert current["question_token"] == first["data"]["card"]["question_token"]
            assert not calculated
            page.locator("#v2TeaserQuestion").get_by_role("button", name="Бизнес", exact=True).click()
            page.locator("#v2TeaserApply").wait_for()
            assert answered[-1]["status"] == 200
            assert answered[-1]["request"]["queue_revision"] == 1
            assert answered[-1]["request"]["question_token"] == current["question_token"]
            assert current["question_token"] != first["request"]["question_token"]
            assert not calculated
            page.evaluate("() => { form.draft.inputs.purchase_price_mln = 999; }")
            page.locator("#v2TeaserApply").click()
            page.locator("#v2ImportStatus").filter(has_text="Вводные изменились").wait_for()
            assert not calculated
            page.locator("#v2TeaserApply").click()
            page.locator("#v2ImportStatus").filter(has_text="проект пересчитан").wait_for(state="attached", timeout=30000)
            page.evaluate("() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)))")
            assert len(calculated) == 1
            sent = calculated[0]
            assert sent["inputs"]["purchase_price_mln"] == 400
            assert sent["inputs"]["vri_relief_mln"] == 2570
            assert sent["inputs"]["vri_relief_mode"] == "amount"
            assert sent["tep"]["apartments"]["gns"] == gns
            assert sent["tep"]["apartments"]["saleable"] < gns
            assert sent["inputs"]["_field_origin"]["inputs.purchase_price_mln"]["source"] == "document"
            assert not errors, errors
            browser.close()


@pytest.mark.parametrize("width", [390, 1440])
def test_v2_stale_answer_shows_current_question_and_keeps_the_unapplied_proposal(monkeypatch, tmp_path, width):
    from playwright.sync_api import sync_playwright, expect

    app = prepare_teaser(monkeypatch, tmp_path, 100.25)
    read = []
    cards = []
    calculated = []
    answered = []
    with serve(app, 18373 + (width == 390)) as base, sync_playwright() as pw:
        browser = pw.chromium.launch(executable_path=str(chromium_or_skip()))
        page = browser.new_page(viewport={"width": width, "height": 900})
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.on("request", lambda req: read.append(req.post_data_json)
                if req.url.endswith("/agent/document/start") else None)
        page.on("request", lambda req: calculated.append(req.post_data_json)
                if req.url.endswith("/api/v2/calculate") else None)
        def response_received(response):
            if "/agent/result/" in response.url:
                result = response.json()
                if result.get("card"):
                    cards.append(result["card"])
            if response.url.endswith(protocol.ANSWER_PATH):
                answered.append({"status": response.status, "request": response.request.post_data_json,
                                 "data": response.json()})
        page.on("response", response_received)
        page.goto(base + "/v2", wait_until="networkidle")
        page.set_input_files("#v2TeaserUpload", {"name": "test.pdf", "mimeType": "application/pdf", "buffer": b"%PDF-test"})
        page.get_by_role("button", name="Перейти к вопросам (2)").click(timeout=15000)
        shown = cards[-1]
        proposal = shown["questions"]["card"]["options"][1]["label"]
        other_tab_answer = {"intake_id": shown["id"], "index": shown["questions"]["index"],
            "queue_revision": shown["queue_revision"], "question_token": shown["question_token"],
            "action": "answer", "choice": 0, "inputs": read[0]["inputs"], "tep": read[0]["tep"]}
        changed = page.request.post(base + protocol.ANSWER_PATH, data=other_tab_answer)
        assert changed.status == 200
        current = changed.json()["card"]
        assert current["questions"]["index"] == 1
        page.locator('#v2TeaserQuestion [data-teaser-choice="1"]').click()
        expect(page.locator("#v2ImportStatus")).to_contain_text("Ответ не применён")
        expect(page.locator("#v2ImportStatus")).to_contain_text(proposal)
        expect(page.locator("#v2ImportStatus")).to_be_visible()
        expect(page.locator("#v2ImportStatus")).to_be_in_viewport()
        expect(page.locator("#v2TeaserQuestion").get_by_role("button", name="Бизнес", exact=True)).to_be_visible()
        assert answered[-1]["status"] == 409
        assert answered[-1]["data"]["detail"]["card"]["id"] == shown["id"]
        assert answered[-1]["request"]["queue_revision"] == shown["queue_revision"]
        assert page.locator("#v2TeaserApply").count() == 0
        assert not calculated
        with page.expect_response(lambda response: response.url.endswith(protocol.ANSWER_PATH)) as accepted_response:
            page.locator("#v2TeaserQuestion").get_by_role("button", name="Бизнес", exact=True).click()
        expect(page.locator("#v2TeaserApply")).to_be_visible()
        accepted = accepted_response.value
        assert accepted.status == 200
        assert accepted.request.post_data_json["queue_revision"] == current["queue_revision"]
        assert accepted.request.post_data_json["question_token"] == current["question_token"]
        assert accepted.json()["card"]["inputs"]["vri_relief_mln"] == current["inputs"]["vri_relief_mln"] == 0
        assert accepted.json()["card"]["tep"]["apartments"]["gns"] == 100.25
        assert not calculated and not errors
        browser.close()


@pytest.mark.parametrize('width',[390,1440])
def test_v2_new_card_then_legacy_worker_HOLD_is_in_viewport_without_retry(monkeypatch,tmp_path,width):
    from playwright.sync_api import sync_playwright,expect
    import main
    app=prepare_teaser(monkeypatch,tmp_path,100.25);cards=[];posts=[];errors=[]
    with serve(app,18471+(width==390))as base,sync_playwright()as pw:
        browser=pw.chromium.launch(executable_path=str(chromium_or_skip()))
        page=browser.new_page(viewport={'width':width,'height':900})
        page.on('pageerror',lambda error:errors.append(str(error)))
        def result(response):
            if '/agent/result/'in response.url:
                value=response.json()
                if value.get('card'):cards.append(value['card'])
        page.on('response',result)
        page.on('request',lambda req:posts.append(req.url)if req.method=='POST'else None)
        page.goto(base+'/v2',wait_until='networkidle')
        page.set_input_files('#v2TeaserUpload',{'name':'synthetic.pdf','mimeType':'application/pdf','buffer':b'%PDF-test'})
        page.get_by_role('button',name='Перейти к вопросам (2)').click()
        assert cards
        path=main.core._intake_queue_path(cards[-1]['id']);before=path.read_bytes()
        # Exact native56/57/58 lack this new route. Simulate the POST landing
        # there after the preceding capability/card came from the new worker.
        page.route('**'+protocol.ANSWER_PATH,lambda route:route.fulfill(status=404,
            content_type='application/json',body='{"detail":"Not Found"}'))
        with page.expect_response(lambda response:response.url.endswith(protocol.ANSWER_PATH)):
            page.locator('#v2TeaserQuestion [data-teaser-choice="1"]').click()
        note=page.locator('#v2ImportStatus')
        expect(note).to_contain_text('Модель обновляется')
        expect(note).to_be_in_viewport()
        page.evaluate('() => new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve)))')
        assert sum(url.endswith(protocol.ANSWER_PATH)for url in posts)==1
        assert not any(url.endswith(('/agent/document/answer','/agent/document/apply','/api/v2/calculate'))for url in posts)
        assert path.read_bytes()==before and not errors,errors
        browser.close()
