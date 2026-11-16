"""Canonical Cabinet navigation on actual Monitor/Report PAGE, including host CSS."""
import ast
from pathlib import Path
import re

import pytest

import management_contour as contour
import plato_question
from developaid_monitor_page import MONITOR_PAGE
from developaid_report_page import REPORT_PAGE

ROOT=Path(__file__).resolve().parents[1]
PAGES={'/monitor':MONITOR_PAGE.replace(plato_question.PLACEHOLDER,plato_question.SCRIPT),'/report':REPORT_PAGE}
PAGES={path:html.replace('__VERSION__','0.29.71')for path,html in PAGES.items()}


def cabinet_reference():
    # This is the real native Cabinet template; no business renderer/provider.
    tree=ast.parse((ROOT/'market_search/cabinet.py').read_bytes())
    template=next(ast.literal_eval(n.value)for n in tree.body if isinstance(n,ast.Assign)and any(isinstance(t,ast.Name)and t.id=='CABINET_PAGE'for t in n.targets))
    template=template.replace('__DEVELOPAID_CONTOUR_STYLE__',contour.STYLE).replace(contour.PLACEHOLDER,contour.markup('/cabinet/market'))
    return re.sub(r'<script\b[^>]*>.*?</script>','',template,flags=re.S)


@pytest.mark.parametrize('width',[390,1440])
def test_native_header_and_canonical_nav_match_cabinet_with_global_visible_on_every_view(width):
    from playwright.sync_api import sync_playwright,expect
    from browser import chromium_or_skip
    measure="""e=>{const s=getComputedStyle(e),r=e.getBoundingClientRect();return {width:r.width,height:r.height,x:r.x,fontFamily:s.fontFamily,fontSize:s.fontSize,lineHeight:s.lineHeight,color:s.color,background:s.backgroundColor,border:s.borderTop,borderRadius:s.borderRadius,padding:s.padding,gap:s.gap,grid:s.gridTemplateColumns}}"""
    pages={**PAGES,'/cabinet/market':cabinet_reference()}
    with sync_playwright()as pw:
        browser=pw.chromium.launch(executable_path=str(chromium_or_skip()),args=['--no-sandbox','--disable-background-networking'])
        try:
            page=browser.new_page(viewport={'width':width,'height':1000})
            def route(r):
                from urllib.parse import urlsplit
                path=urlsplit(r.request.url).path
                if r.request.method=='GET'and path in pages:r.fulfill(content_type='text/html',body=pages[path])
                else:r.abort('blockedbyclient')
            page.route('**/*',route)
            page.goto('https://developaid.ru/cabinet/market')
            reference=page.locator('nav.contour').evaluate(measure)
            reference_notes=page.locator('nav.contour i,nav.contour a span').all_text_contents()
            for path in ['/monitor','/report']:
                page.goto('https://developaid.ru'+path)
                nav=page.locator('nav.contour');expect(nav).to_be_visible()
                assert nav.evaluate(measure)==reference
                assert nav.locator('i,a span').all_text_contents()==reference_notes
                assert nav.locator('[data-monitor-view]').count()==0
                assert page.locator('.monitor-tabs [data-monitor-view]').count()==4
                assert page.locator('.monitor-tabs').bounding_box()['y']>=page.locator('.top').bounding_box()['y']+page.locator('.top').bounding_box()['height']
                assert page.locator('.monitor-page-header .brand img').get_attribute('src')=='/guide/assets/logo.webp'
                if path=='/monitor':
                    for name in ['contracts','money','data','monitor']:
                        page.locator('#'+name+'Tab').click()
                        expect(nav).to_be_visible()
                        assert nav.evaluate(measure)==reference
                        expect(page.locator('#'+name+'Tab')).to_have_attribute('aria-selected','true')
                page.emulate_media(media='print');expect(nav).to_be_hidden();page.emulate_media(media='screen')
        finally:browser.close()
