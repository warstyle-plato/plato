"""The primary IA surface visibly exposes a native pre-delivery refusal."""
import copy
import socket
from urllib.parse import urlsplit

import pytest

from browser import chromium_or_skip, serve, wait_for_result
from test_document_qualification import core, document, qual, CHAT


@pytest.mark.parametrize('width',[390,1440])
def test_primary_page_native_document_refusal_is_visible_without_delivery(document,monkeypatch,width):
    from playwright.sync_api import sync_playwright, expect
    import main_registry
    original=document();other=document(True);sent=[];attachments=[]
    monkeypatch.setenv('DEVELOPAID_PAYWALL','0')
    monkeypatch.setenv('DEVELOPAID_ADMIN_IDS',str(CHAT))
    monkeypatch.setattr(core,'fetch_current_cbr_key_rate',lambda:{'rate':14.0,'date':'2026-11-15','live':False,'source':'Synthetic local rate'})
    monkeypatch.setattr(core,'_telegram_send_message',lambda *a,**kw:sent.append((a,kw)))
    monkeypatch.setattr(core,'_telegram_send_attachments',lambda *a,**kw:attachments.append((a,kw)))
    with socket.socket()as reserve:
        reserve.bind(('127.0.0.1',0));port=reserve.getsockname()[1]
    with serve(main_registry.app,port)as base,sync_playwright()as pw:
        browser=pw.chromium.launch(executable_path=str(chromium_or_skip()))
        page=browser.new_page(viewport={'width':width,'height':900});errors=[]
        page.on('pageerror',lambda error:errors.append(str(error)))
        launch=original['markup']['inline_keyboard'][0][0]['web_app']['url']
        page.goto(base+urlsplit(launch).path+'#'+urlsplit(launch).fragment,wait_until='networkidle');wait_for_result(page)
        assert page.locator('.ia-nav').is_visible()
        payload={'inputs':copy.deepcopy(other['inputs']),'tep':copy.deepcopy(other['tep']),'phasing':{},'scenario':'base'}
        page.evaluate('payload=>{applyProjectSnapshot(payload);return calculate()}',payload);wait_for_result(page)
        assert page.evaluate('()=>inputs._intake_qualification.intake_id')==other['record']['intake_id']
        page.evaluate('()=>sendTelegramResult()')
        expect(page.locator('#telegramResultError')).to_be_visible()
        expect(page.locator('#telegramResultError')).to_contain_text('карточк')
        assert page.locator('#telegramResultError').count()==1
        bounds=page.locator('#telegramResultError').bounding_box()
        assert bounds and 0<=bounds['x']and 0<=bounds['y']
        assert bounds['x']+bounds['width']<=width+1 and bounds['y']+bounds['height']<=900
        assert page.locator('#telegramResultError').evaluate('(el)=>{const b=el.getBoundingClientRect();return el.contains(document.elementFromPoint(b.x+b.width/2,b.y+b.height/2))}')
        assert 'Доставка неизвестна'not in page.locator('#telegramResultError').inner_text()
        assert page.evaluate('()=>sendTelegramResult.uncertain')is False
        assert page.evaluate('()=>telegramResultSent')is False
        assert not sent and not attachments and not errors
        assert page.evaluate('()=>inputs._intake_qualification')==other['record']
        page.evaluate('payload=>applyProjectSnapshot(payload)',payload)
        assert page.locator('#telegramResultError').count()==0
        page.evaluate('()=>calculate()');wait_for_result(page)
        page.evaluate('()=>sendTelegramResult()')
        expect(page.locator('#telegramResultError')).to_be_visible()
        page.evaluate('()=>resetAll()')
        assert page.locator('#telegramResultError').count()==0
        browser.close()
