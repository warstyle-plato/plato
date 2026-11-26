import pytest
from urllib.parse import urlparse
from test_monitor_cumulative_controls import browser_page,KEY

@pytest.mark.parametrize('width',[390,1440])
def test_native_page_manual_preview_apply_and_literal_source_text(width):
    from playwright.sync_api import expect
    with browser_page(width) as (page,responses,errors):
        calls=[]
        marker='<img src=x onerror="window.diskInjected=true">'
        entry=dict(id='b'*64,sha256='c'*64,filename=marker,locations=[dict(path='/Юрист/Подрядчик/A-12/Договор/'+marker)],status='new')
        def handle(route):
            body=route.request.post_data_json
            assert body['key']==KEY
            path=urlparse(route.request.url).path
            calls.append((path,body))
            if path.endswith('/scan'):
                value=dict(revision='a'*64,entries=[entry],issues=[],missing_previous_files=[],notice='Каталог проверен',scope_notice='Проверены только найденные разделы: Юрист. Не просмотрены: Служебные, Бухгалтер, Строитель. '+marker)
            elif path.endswith('/stage'):
                assert body['item_ids']==['b'*64]
                value=dict(stage_token='d'*64,entries=[{**entry,'status':'ready'}],notice='Проверенные исходники готовы')
            else:
                assert body['stage_token']=='d'*64
                assert body['taken_at']=='2026-11-25'
                value=dict(entries=[dict(id='b'*64,sha256='c'*64,status='imported')],review=[],notice='Прежние версии сохранены')
            route.fulfill(json=dict(pending=False,ok=True,disk_source=value))
        page.route('**/monitor/contracts/disk/**',handle)
        assert not calls
        page.locator('#dataTab').click()
        page.locator('#contractDiskUrl').fill('https://disk.yandex.ru/d/fixture-source')
        page.locator('#contractDiskScan').click()
        expect(page.locator('#contractDiskMsg')).to_contain_text('Каталог проверен')
        expect(page.locator('.contract-disk-choice')).to_have_count(1)
        expect(page.locator('#contractDiskScope')).to_contain_text('Не просмотрены: Служебные, Бухгалтер, Строитель')
        expect(page.locator('#contractDiskScope')).to_contain_text(marker)
        assert len(calls)==1
        page.locator('#contractDiskStage').click()
        expect(page.locator('#contractDiskMsg')).to_contain_text('исходники готовы')
        page.locator('#contractDiskDate').fill('2026-11-25')
        page.locator('#contractDiskApply').click()
        expect(page.locator('#contractDiskMsg')).to_contain_text('Прежние версии сохранены')
        assert len(calls)==3
        assert page.evaluate('window.diskInjected') is None
        assert page.locator('#contractDiskList img').count()==0
        assert page.locator('#contractDiskScope img').count()==0
        expect(page.locator('#contractDiskScope')).to_contain_text('Служебные')
        page.locator('#contractDiskUrl').fill('https://disk.yandex.ru/d/another-source')
        expect(page.locator('#contractDiskScope')).to_be_empty()
        assert not errors
        assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
