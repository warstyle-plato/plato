import os
import re
import socket
import sys
import threading
import time
import tempfile
from pathlib import Path

ROOT=Path(__file__).resolve().parent.parent
sys.path.insert(0,str(ROOT))
temporary=tempfile.TemporaryDirectory(prefix='developaid-ui-')
os.environ['DEVELOPAID_DESKTOP_DATA']=temporary.name
from desktop.runtime import load_engine,data_directory
from desktop.storage import Store
from desktop.app import create_app
from playwright.sync_api import sync_playwright
import uvicorn

core=load_engine(data_directory())
sock=socket.socket();sock.bind(('127.0.0.1',0));origin=f'http://127.0.0.1:{sock.getsockname()[1]}'
app=create_app(core,Store(data_directory()/'developaid.sqlite3'),'ui-test',origin)
server=uvicorn.Server(uvicorn.Config(app,log_config=None,access_log=False))
thread=threading.Thread(target=server.run,kwargs={'sockets':[sock]},daemon=True);thread.start()
while not server.started:time.sleep(.05)
try:
  with sync_playwright() as p:
    browser=p.chromium.launch(executable_path=os.getenv('DEVELOPAID_TEST_CHROMIUM'),headless=True,args=['--no-sandbox','--disable-gpu','--disable-dev-shm-usage'])
    page=browser.new_page(viewport={'width':1512,'height':982},device_scale_factor=1)
    errors=[];page.on('pageerror',lambda error: errors.append(str(error)))
    page.goto(origin)
    page.locator('#blockTitle').filter(has_text='ТЭП проекта').wait_for()
    assert page.locator('[data-stage]').all_text_contents()==['01 Проект','02 Экономика','03 Результат']
    assert page.locator('#blockList button').all_text_contents()==['ТЭП проекта','Очерёдность']
    page.locator('#nextStep').click()
    page.locator('#blockTitle').filter(has_text='Очереди').wait_for()
    page.locator('#previousStep').click()
    page.locator('#blockTitle').filter(has_text='ТЭП проекта').wait_for()
    page.locator('[data-stage="economics"]').click()
    page.locator('#blockList summary').click()
    page.locator('#blockList details button').filter(has_text='Кладовые').click()
    page.locator('#blockTitle').filter(has_text='Кладовые').wait_for()
    assert page.locator('#blockList details').evaluate('(e)=>e.open')
    page.locator('#projectName').fill('Рабочая модель · пример')
    page.locator('[data-stage="economics"]').click()
    page.locator('#blockList button').filter(has_text='Сделка и сроки').click()
    page.locator('[data-field="purchase_price_mln"]').fill('1200')
    page.locator('#saveProject').click()
    page.locator("#saveState").filter(has_text=re.compile("^Сохранено")).wait_for()
    first=page.locator('.metric-value').all_text_contents()
    page.reload()
    page.locator('#projectList button').filter(has_text='Рабочая модель').first.click()
    page.locator("#saveState").filter(has_text=re.compile("^Сохранённый")).wait_for()
    assert page.locator('.metric-value').all_text_contents()==first
    page.locator('[data-stage="economics"]').click()
    page.locator('#blockList button').filter(has_text='Сделка и сроки').click()
    assert page.locator('[data-field="purchase_price_mln"]').input_value()=='1200'
    page.locator('[data-tab="references"]').click()
    page.locator('#previewProfile').click()
    assert page.locator('#profileDiff table tr').count()>3
    page.locator('[data-stage="economics"]').click()
    page.locator('#blockList summary').click()
    page.screenshot(path=str(ROOT/'docs/desktop-preview.png'),full_page=True)
    page.locator('[data-stage="result"]').click()
    page.locator('[data-tab="cashflow"]').click()
    page.locator('#cashflowBody table').wait_for()
    page.locator('[data-tab="result"]').click()
    with page.expect_download() as download:
      page.locator('[data-export="json"]').click()
    assert download.value.suggested_filename.endswith('.json')
    page.locator('[data-tab="history"]').click()
    page.locator('#historyBody button').first.wait_for()
    assert not errors,errors
    print('PASS: edit → calculate/save → reload/reopen → exact displayed KPIs; reference diff; history; JSON download; three stages, phasing next to TEP, object submenu; no JS errors')
    browser.close()
finally:
  server.should_exit=True;thread.join(10);sock.close();temporary.cleanup()
