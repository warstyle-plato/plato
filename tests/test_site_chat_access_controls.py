"""The owner grants an exact project/group through the protected Monitor UI."""
import json
import socket

import pytest

from test_site_chat_owner_grants import GROUP, KEY, PROJECT, bot


@pytest.mark.parametrize("width", [390, 1280])
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
