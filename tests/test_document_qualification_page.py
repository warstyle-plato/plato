"""Whole PAGE with actual signed handoff, local/server save, reload and edit."""
import copy
import json
import socket
import threading
import time
from urllib.parse import urlsplit

import pytest
import main
from browser import chromium_or_skip, wait_for_result
from test_document_qualification import core, document, qual, CHAT


@pytest.mark.parametrize('width',[390,1440])
def test_actual_page_keeps_qualification_through_calculation_save_reload_and_edit(document,monkeypatch,width):
    import uvicorn
    from playwright.sync_api import sync_playwright
    item=document();sent=[];attachments=[]
    monkeypatch.setenv('DEVELOPAID_PAYWALL','0')
    monkeypatch.setenv('DEVELOPAID_ADMIN_IDS',str(CHAT))
    monkeypatch.setattr(core,'fetch_current_cbr_key_rate',lambda:{'rate':14.0,'date':'2026-11-15','live':False,'source':'Synthetic local rate'})
    monkeypatch.setattr(core,'_telegram_api',lambda method,payload=None,**kw:sent.append((method,copy.deepcopy(payload)))or{})
    # Delivery is synthetic here; the separate native PDF/teaser/workbook tests
    # render and parse the actual artifacts from the same canonical input field.
    monkeypatch.setattr(core,'_telegram_send_attachments',lambda *a,**k:attachments.append((a,k)))
    monkeypatch.setattr(core,'_projects_remote_url',lambda *a,**k:'')
    with socket.socket()as reserve:
        reserve.bind(('127.0.0.1',0));port=reserve.getsockname()[1]
    server=uvicorn.Server(uvicorn.Config(main.app,host='127.0.0.1',port=port,log_level='error'))
    thread=threading.Thread(target=server.run,daemon=True);thread.start()
    for _ in range(200):
        if server.started:break
        time.sleep(.025)
    assert server.started
    try:
        with sync_playwright()as pw:
            browser=pw.chromium.launch(executable_path=str(chromium_or_skip()))
            context=browser.new_context(viewport={'width':width,'height':900})
            context.add_init_script("localStorage.setItem('plato_projects_key','synthetic-qualification-admin')")
            page=context.new_page();errors=[];page.on('pageerror',lambda error:errors.append(str(error)))
            base=f'http://127.0.0.1:{port}'
            initial_url=item['markup']['inline_keyboard'][0][0]['web_app']['url']
            page.goto(base+urlsplit(initial_url).path+'#'+urlsplit(initial_url).fragment,wait_until='networkidle')
            page.wait_for_function("() => lastResult?.summary?.intake_qualification?.status==='conditional'",timeout=30000)
            wait_for_result(page)
            record=page.evaluate('() => inputs._intake_qualification')
            assert record==item['record']
            assert page.evaluate('() => inputs.purchase_price_mln')==73.5
            assert '275 м²'in page.locator('body').inner_text()
            assert 'не включена'in page.locator('body').inner_text()
            assert page.evaluate('() => lastResult.summary.preliminary')is True
            page.evaluate("() => openTab('inputs')")
            field=page.locator('#f_purchase_price_mln')
            field.evaluate("el=>{for(let d=el.closest('details');d;d=d.parentElement?.closest('details'))d.open=true}")
            field.fill('74.5');field.press('Tab')
            page.wait_for_function('() => inputs.purchase_price_mln===74.5')
            wait_for_result(page)
            assert page.evaluate('() => inputs._intake_qualification')==record
            # Intake launch deliberately does not auto-send. Invoke the actual
            # explicit send handler once; all server handlers remain native.
            page.evaluate('() => sendTelegramResult()')
            page.wait_for_function('() => telegramResultSent===true')
            stored=page.evaluate('() => {persistLocalSilently();return projectStorePayload()}')
            saved=page.request.post(base+'/projects/save',data={'key':'synthetic-qualification-admin',
                'name':'Synthetic conditional model',**stored})
            assert saved.status==200,saved.text()
            project_id=saved.json()['id']
            opened=page.request.post(base+'/projects/open',data={'key':'synthetic-qualification-admin','id':project_id})
            assert opened.status==200,opened.text()
            payload=opened.json()['payload']
            assert payload['inputs'][qual.KEY]==record
            assert payload['inputs']['purchase_price_mln']==74.5
            # Plain browser reload uses the actual local-storage loader, with
            # no Telegram override to overwrite an ordinary manual edit.
            page.goto(base+'/',wait_until='networkidle');wait_for_result(page)
            assert page.evaluate('() => inputs._intake_qualification')==record
            assert page.evaluate('() => inputs.purchase_price_mln')==74.5
            assert '275 м²'in page.locator('body').inner_text()
            # The native saved-project snapshot adapter also retains the exact
            # signed record before a fresh real calculation.
            page.evaluate('data=>{applyProjectSnapshot(data);return calculate()}',payload)
            wait_for_result(page)
            assert page.evaluate('() => lastResult.summary.intake_qualification.status')=='conditional'
            assert page.evaluate('() => inputs._intake_qualification')==record
            assert '275 м²'in page.evaluate('() => lastResult.summary.preliminary_reason')
            messages=[value for method,value in sent if method=='sendMessage']
            assert any('275 м²'in value['text']and'не включена'in value['text']for value in messages)
            edit_url=next(value['reply_markup']['inline_keyboard'][0][0]['web_app']['url']for value in reversed(messages)if value.get('reply_markup'))
            page.goto(base+urlsplit(edit_url).path+'#'+urlsplit(edit_url).fragment,wait_until='networkidle')
            page.reload(wait_until='networkidle')
            wait_for_result(page)
            assert page.evaluate('() => inputs._intake_qualification')==record
            assert page.evaluate('() => inputs.purchase_price_mln')==74.5
            assert page.evaluate('() => lastResult.summary.intake_qualification.status')=='conditional'
            assert '275 м²'in page.locator('body').inner_text()
            assert not errors,errors
            assert attachments and attachments[0][0][1]['inputs'][qual.KEY]==record
            # A genuine earlier verified-empty link must not overlay the
            # current unknown from another native document, even in this chat.
            other=document(True)
            priced=core._telegram_verify_session(other['token'])
            old_url=core._telegram_web_app_url(CHAT,[],calc_overrides=priced['calc_overrides'],
                application_proof=priced['overrides_application'],mode='edit')
            page.goto(base+urlsplit(old_url).path+'#'+urlsplit(old_url).fragment,wait_until='networkidle')
            page.reload(wait_until='networkidle')
            page.wait_for_selector('#telegramOverridesReview')
            assert page.locator('#telegramOverridesReview').is_visible()
            assert 'подтвердить заново'in page.locator('#telegramOverridesReview').inner_text()
            assert page.evaluate('() => inputs._intake_qualification')==record
            assert page.evaluate('() => inputs.purchase_price_mln')==74.5
            assert page.evaluate('() => telegramOverridesReviewRequired')is True
            assert page.evaluate('() => lastResult')is None
            assert not errors,errors
            browser.close()
    finally:
        server.should_exit=True;thread.join(timeout=10)
