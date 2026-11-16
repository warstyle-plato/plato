"""Whole PAGE: a stale web answer stays a proposal and is never replayed."""
import json
import threading
import time

import pytest
from browser import chromium_or_skip, wait_for_result
import main

core = main.core


@pytest.mark.parametrize('width', [390, 1440])
def test_page_keeps_unapplied_value_and_refreshes_without_auto_answer(monkeypatch, width):
    from playwright.sync_api import sync_playwright
    import uvicorn
    import socket
    monkeypatch.setattr(core, '_require_web_access', lambda *a, **k: None)
    monkeypatch.setattr(core, 'usage_track', lambda *a, **k: None)
    monkeypatch.setattr(core.document_intake, 'extract_text', lambda *a:
        {'text': 'Стоимость расселения не указана.', 'pages': 1, 'filename': 'synthetic.pdf'})
    monkeypatch.setattr(core, 'document_intake_read', lambda *a:
        {'fields': [], 'questions': [{'key': 'resettlement_cost_mln',
         'question': 'Какова стоимость расселения?', 'options': ['Расселение не требуется — 0', 'Требуется']}], 'notes': []})
    with socket.socket() as reserve:
        reserve.bind(('127.0.0.1', 0)); port = reserve.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(main.app, host='127.0.0.1', port=port, log_level='error'))
    thread = threading.Thread(target=server.run, daemon=True); thread.start()
    for _ in range(200):
        if server.started: break
        time.sleep(.025)
    assert server.started
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(executable_path=str(chromium_or_skip()))
            page = browser.new_page(viewport={'width': width, 'height': 900})
            errors, answers = [], []
            page.on('pageerror', lambda error: errors.append(str(error)))
            page.on('request', lambda req: answers.append(json.loads(req.post_data))
                if req.method == 'POST' and req.url.endswith('/agent/document/qualified-v1/answer') else None)
            base = f'http://127.0.0.1:{port}'
            page.goto(base+'/', wait_until='networkidle'); wait_for_result(page)
            page.evaluate('() => toggleAgent(true)')
            page.set_input_files('#aiFile', files=[{'name': 'synthetic.pdf', 'mimeType': 'application/pdf', 'buffer': b'%PDF synthetic'}])
            page.wait_for_function('() => !aiBusy && aiCard !== null')
            shown = page.evaluate('() => aiCard')
            page.locator('.ai-card').last.get_by_role('button', name='Перейти к вопросам').click()
            page.locator('.ai-question-value').last.fill('2,5 млн')
            # A second tab's native request wins while this page still shows Q0.
            winner = page.request.post(base+'/agent/document/qualified-v1/answer', data={
                'intake_id': shown['id'], 'index': 0, 'action': 'skip',
                'queue_revision': shown['queue_revision'], 'question_token': shown['question_token'],
                'inputs': shown['inputs'], 'tep': shown['tep']})
            assert winner.status == 200
            page.locator('.ai-question').last.get_by_role('button', name='Ответить', exact=True).click()
            page.wait_for_function('() => !aiBusy && document.querySelector(".ai-unapplied-answer") !== null')
            assert '2,5 млн' in page.locator('.ai-unapplied-answer').inner_text()
            assert 'не применён' in page.locator('.ai-unapplied-answer').inner_text()
            assert page.evaluate('() => aiQuestion.index') == 1
            assert page.evaluate('() => aiQuestion.queue_revision') == 1
            assert len(answers) == 1 and answers[0]['queue_revision'] == 0
            assert answers[0]['question_token'] == shown['question_token']
            # The disabled old button and its captured handler cannot answer Q1.
            page.locator('.ai-question').first.locator('[data-answer="typed"]').evaluate('(b) => b.onclick()')
            assert len(answers) == 1
            path = core._intake_queue_path(shown['id'])
            saved = json.loads(path.read_bytes())
            assert len(saved['answers']) == 1 and saved['answers'][0]['action'] == 'skip'
            assert saved['index'] == 1 and saved['revision'] == 1
            assert not errors
            browser.close()
    finally:
        server.should_exit = True; thread.join(timeout=10)
