"""The owner grants an exact project/group through the protected Monitor UI."""
import json
import socket

import pytest

from test_site_chat_owner_grants import GROUP, KEY, PROJECT, bot


@pytest.mark.parametrize("width", [390, 1440])
def test_the_owner_authorizes_and_revokes_a_group_in_the_monitor(bot, width):
    from browser import chromium_or_skip, serve
    from playwright.sync_api import expect, sync_playwright

    chrome = chromium_or_skip()
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    with serve(bot.core.app, port) as base, sync_playwright() as playwright:
        browser = playwright.chromium.launch(executable_path=str(chrome))
        try:
            page = browser.new_page(viewport={"width": width, "height": 1000})
            page.add_init_script("localStorage.setItem('plato_projects_key'," + json.dumps(KEY) + ");"
                                 "localStorage.setItem('monitor_project'," + json.dumps(PROJECT) + ");")
            calls = []
            page.on("request", lambda request: calls.append(request)
                    if "/monitor/site-chats/" in request.url else None)
            page.goto(base + "/monitor", wait_until="domcontentloaded")
            page.locator("#siteAccessCard > summary").click()
            page.locator("#siteChatId").fill(str(GROUP))
            title = '<img src="private-marker" onerror="window.groupXss=true">'
            page.locator("#siteChatTitle").fill(title)
            page.locator("#siteAuthorizeBtn").click()
            expect(page.locator("#siteAccessMsg")).to_contain_text("Группа разрешена")
            assert bot.core._site_chat_project(GROUP) == PROJECT
            expect(page.locator("#siteAccessList")).to_contain_text(title)
            assert page.locator("#siteAccessList img").count() == 0
            assert not page.evaluate("Boolean(window.groupXss)")
            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
            page.locator("#siteAccessList button").click()
            expect(page.locator("#project")).to_have_value(PROJECT)
            expect(page.locator("#siteChatId")).to_have_value(str(GROUP))
            expect(page.locator("#siteChatTitle")).to_have_value(title)

            page.locator("#siteRevokeBtn").click()
            expect(page.locator("#siteAccessMsg")).to_contain_text("Доступ группы отозван")
            assert bot.core._site_chat_project(GROUP) == ""
            assert bot.core._site_chats_path().exists(), "History/catalogue must survive revocation"

            writes = [request for request in calls if request.method == "POST"]
            assert len(writes) == 2
            assert [request.url.rsplit("/", 1)[-1] for request in writes] == ["authorize", "revoke"]
            assert all(request.post_data_json["chat_id"] == GROUP and
                       request.post_data_json["project"] == PROJECT and
                       request.post_data_json["key"] == KEY for request in writes)
            assert all("session" not in request.post_data_json for request in writes)
            assert all(KEY not in request.url for request in calls)

            page.evaluate("localStorage.setItem('plato_projects_key','wrong-fixture-key')")
            page.locator("#siteAccessRefresh").click()
            expect(page.locator("#privateArea")).to_be_hidden()
            expect(page.locator("#loginBox")).to_be_visible()
            expect(page.locator("#siteAccessList")).to_be_empty()
        finally:
            browser.close()


def test_bad_group_id_never_reaches_the_owner_api(bot):
    from browser import chromium_or_skip, serve
    from playwright.sync_api import expect, sync_playwright

    chrome = chromium_or_skip()
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    with serve(bot.core.app, port) as base, sync_playwright() as playwright:
        browser = playwright.chromium.launch(executable_path=str(chrome))
        try:
            page = browser.new_page()
            page.add_init_script("localStorage.setItem('plato_projects_key'," + json.dumps(KEY) + ");"
                                 "localStorage.setItem('monitor_project'," + json.dumps(PROJECT) + ");")
            calls = []
            page.on("request", lambda request: calls.append(request)
                    if "/monitor/site-chats/" in request.url else None)
            page.goto(base + "/monitor", wait_until="domcontentloaded")
            page.locator("#siteAccessCard > summary").click()
            page.locator("#siteChatId").fill("100")
            page.locator("#siteAuthorizeBtn").click()
            expect(page.locator("#siteAccessMsg")).to_contain_text("отрицательный числовой ID")
            assert not calls
            assert not bot.core._site_chat_grants_path().exists()
        finally:
            browser.close()


@pytest.mark.parametrize("width", [390, 1440])
@pytest.mark.parametrize("change,status", [("project",200),("key",200),("key",403),("logout",200)])
def test_old_group_access_result_cannot_repopulate_another_context(bot, width, change, status):
    from browser import chromium_or_skip, serve
    from playwright.sync_api import expect, sync_playwright

    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    with serve(bot.core.app, port) as base, sync_playwright() as playwright:
        browser = playwright.chromium.launch(executable_path=str(chromium_or_skip()))
        try:
            page = browser.new_page(viewport={"width": width,"height":1000})
            page.add_init_script("localStorage.setItem('plato_projects_key',"+json.dumps(KEY)+");"
                                 "localStorage.setItem('monitor_project',"+json.dumps(PROJECT)+");")
            errors=[]
            page.on("pageerror",lambda error:errors.append(str(error)))
            page.goto(base+"/monitor",wait_until="domcontentloaded")
            page.locator("#siteAccessCard > summary").click()
            delayed=[]
            page.route("**/monitor/site-chats/access",lambda route:delayed.append(route))
            with page.expect_request('**/monitor/site-chats/access'):
                page.evaluate("()=>{window.oldAccess=loadSiteAccess().catch(()=>null)}")
            for _ in range(100):
                if delayed:break
                page.wait_for_timeout(20)
            assert len(delayed)==1
            if change=="project":
                page.locator("#project").fill("Другой синтетический проект")
                page.locator("#project").dispatch_event("change")
            elif change=="key":
                # Reentering even the same key starts a new authorization epoch.
                page.once("dialog",lambda dialog:dialog.accept(KEY))
                page.locator("#keyBtn").click()
            else:
                page.locator("#logoutBtn").click()
            delayed[0].fulfill(status=status,content_type="application/json",body=json.dumps({
                "detail":"old denial", "chats":[{"chat_id":GROUP,"title":"OLD_PRIVATE_GROUP",
                    "project":PROJECT,"authorized":True}]}))
            page.evaluate("window.oldAccess")
            expect(page.locator("#siteAccessList")).to_be_empty()
            expect(page.locator("#siteChatTitle")).to_have_value("")
            assert "OLD_PRIVATE_GROUP" not in page.locator("body").inner_text()
            if change=="key":
                expect(page.locator("#privateArea")).to_be_visible()
                assert "old denial" not in page.locator("#loginMsg").inner_text()
            if change=="logout":
                expect(page.locator("#privateArea")).to_be_hidden()
            assert page.evaluate("document.documentElement.scrollWidth<=innerWidth")
            assert errors==[]
        finally:
            browser.close()


@pytest.mark.parametrize("width",[390,1440])
@pytest.mark.parametrize("change",["project","key","cut","logout"])
def test_late_monitor_answer_does_not_enter_changed_project_or_authorization(bot,width,change):
    from browser import chromium_or_skip,serve
    from playwright.sync_api import expect,sync_playwright
    with socket.socket() as probe:
        probe.bind(("127.0.0.1",0));port=probe.getsockname()[1]
    with serve(bot.core.app,port) as base,sync_playwright() as playwright:
        instance=playwright.chromium.launch(executable_path=str(chromium_or_skip()))
        try:
            page=instance.new_page(viewport={"width":width,"height":1000})
            page.add_init_script("localStorage.setItem('plato_projects_key',"+json.dumps(KEY)+");"
                                 "localStorage.setItem('monitor_project',"+json.dumps(PROJECT)+");")
            page.goto(base+"/monitor",wait_until="domcontentloaded")
            delayed=[]
            page.route("**/monitor/ask",lambda route:delayed.append(route))
            page.evaluate("monitorTalk.said('Previous question','OLD_PRIVATE_ANSWER')")
            with page.expect_request('**/monitor/ask'):
                page.evaluate("()=>{window.oldMonitor=askMonitorPlato('Synthetic question')}")
            for _ in range(100):
                if delayed:break
                page.wait_for_timeout(20)
            assert len(delayed)==1
            if change=="project":
                page.locator('#project').fill('Other synthetic project')
                page.locator('#project').dispatch_event('change')
            elif change=="cut":
                page.locator('#cut').fill('2026-10-31')
                page.locator('#cut').dispatch_event('change')
            elif change=="key":
                page.once('dialog',lambda dialog:dialog.accept(KEY));page.locator('#keyBtn').click()
            else:page.locator('#logoutBtn').click()
            delayed[0].fulfill(status=200,content_type='application/json',body=json.dumps({'answer':'LATE_PRIVATE_ANSWER'}))
            page.evaluate('window.oldMonitor')
            assert page.evaluate('monitorTalk.rounds()')==0
            expect(page.locator('#scenarioOutput')).to_be_empty()
            assert 'LATE_PRIVATE_ANSWER' not in page.locator('body').inner_text()
            assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
        finally:instance.close()
