"""Тарифы, мой доступ и администрирование — на странице и в боте.

Здесь закреплено:

- экран «Тарифы» — настоящий код страницы (`tariffsHtml`, стенд на node):
  цены и НДС «в том числе», остаток бесплатного, сроки участков, а оплата —
  кнопками только там, где сервер её включил, иначе — куда идти;
- кабинет и бот читают одни и те же права и условия (`/access/me`);
- администрирование — только администраторам; ручная выдача пишется в журнал
  с именем выдавшего;
- подвал несёт строку о регистрации программы из `docs/legal/product.json`,
  ссылки на договор и возврат.

Запуск: python3 -m pytest tests/test_paid_access_cabinet.py -q
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import page_blocks

import main as _wrapper

core = _wrapper.core
client = TestClient(core.app)
CHAT, ADMIN = 9090, 777
A1 = "50:20:0010101:31"


@pytest.fixture(autouse=True)
def env(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123456:cabinet-test-token")
    monkeypatch.setenv("DEVELOPAID_ADMIN_IDS", str(ADMIN))
    monkeypatch.setenv("DEVELOPAID_ADMIN_KEY", "kluch")
    monkeypatch.setattr(core, "_MO_CALC_API_URL", "")
    yield


def me(chat: int = CHAT) -> dict:
    answer = client.post("/access/me", json={"session": core._telegram_session(chat, [])})
    assert answer.status_code == 200, answer.text
    return answer.json()


def tariffs(data: dict) -> str:
    prelude = "function escapeHtml(s){return String(s).replace(/</g,'&lt;')}"
    out, _ = page_blocks.run(prelude, f"console.log(tariffsHtml({json.dumps(data)}));")
    return out


def test_the_tariffs_screen_shows_prices_vat_and_my_plots():
    core.access_use(CHAT, core.access_plot(cadastral=[A1]))
    text = tariffs(me())
    assert "10 000 ₽" in text and "100 000 ₽" in text
    assert "в том числе НДС 5" in text
    assert "Бесплатных участков осталось: 0 из 1" in text
    assert A1 in text and "доступ до" in text
    # Ключей и оферты нет — кнопок оплаты нет, сказано, куда идти.
    assert "payForAccess" not in text and "напишите нам в бот" in text
    assert "свидетельство № 2026691589" in text


def test_payment_buttons_appear_only_when_the_server_enables_payment():
    data = me()
    data["payments_available"] = True
    text = tariffs(data)
    assert "payForAccess('plot')" in text and "payForAccess('subscription')" in text
    assert 'href="/offer"' in text and 'href="/refund"' in text


def test_a_visitor_without_login_is_told_to_log_in():
    data = client.post("/access/me", json={}).json()
    assert data["signed_in"] is False
    assert "войдите через Telegram" in tariffs(data)


def test_the_admin_section_is_for_admins_only():
    assert client.post("/access/admin/overview",
                       json={"session": core._telegram_session(CHAT, [])}).status_code == 403
    assert client.post("/access/admin/grant", json={
        "session": core._telegram_session(CHAT, []), "chat": CHAT, "cadastral": [A1]}).status_code == 403


def test_the_admin_grants_by_hand_and_sees_it():
    core.users_touch(CHAT, surface="telegram", name="Иван Петров")
    session = core._telegram_session(ADMIN, [])
    answer = client.post("/access/admin/grant", json={
        "session": session, "chat": CHAT, "kind": "plot", "cadastral": [A1], "days": 7,
        "note": "пилот"})
    assert answer.status_code == 200, answer.text
    plots = answer.json()["status"]["plots"]
    assert plots[0]["source"] == "admin" and plots[0]["active"]
    overview = client.post("/access/admin/overview", json={"key": "kluch"}).json()
    person = next(p for p in overview["people"] if p["chat"] == CHAT)
    assert person["active_plots"][0]["label"] == A1
    grant = next(r for r in overview["journal"] if r.get("chat") == CHAT and r.get("event") == "grant")
    assert "администратор 777" in grant["note"] and "пилот" in grant["note"]
    assert me()["status"]["plots"][0]["source"] == "admin"


def test_the_bot_shows_the_same_tariffs(monkeypatch):
    sent: list[str] = []
    monkeypatch.setattr(_wrapper, "_send_message", lambda chat, text, **kw: sent.append(text))
    core.access_use(CHAT, core.access_plot(cadastral=[A1]))
    _wrapper._tariffs_message(CHAT)
    text = sent[-1]
    assert "10 000 ₽" in text and "в том числе НДС 5" in text
    assert "Бесплатных участков осталось: 0 из 1" in text and A1 in text


def test_the_bot_grant_is_for_admins(monkeypatch):
    core.users_touch(CHAT, surface="telegram", name="Иван Петров")
    sent: list[str] = []
    monkeypatch.setattr(_wrapper, "_send_message", lambda chat, text, **kw: sent.append(text))
    _wrapper._grant_command(CHAT, CHAT, f"{CHAT} 30 {A1}")
    assert "только администраторы" in sent[-1]
    _wrapper._grant_command(ADMIN, ADMIN, f"{CHAT} 30 подписка")
    assert "Доступ выдан" in sent[-1]
    assert core.access_status(CHAT)["subscription_active"]


def test_the_footer_names_the_registration_and_the_contract():
    page = core.PAGE
    footer = page[page.index("<footer"):page.index("</footer>")]
    assert core.product_registration_line() in footer
    assert 'href="/offer"' in footer and 'href="/refund"' in footer


def test_the_locked_economics_leads_to_the_tariffs():
    # Без ответа сервера (`/access/check` недоступен) плашка всё равно ведёт в
    # «Тарифы»: сама плашка с ценами проверяется на отрисованной странице
    # (tests/test_paid_access_plaque.py).
    prelude = ("const box={style:{},innerHTML:'',classList:{add(){},remove(){}}};"
               "const document={getElementById:()=>box};let lastResult=1,phaseBundle=1;"
               "const fetch=()=>Promise.reject(new Error('нет сети'));")
    out, _ = page_blocks.run(prelude, "renderCalcLocked('Причина',402);console.log(box.innerHTML);")
    assert "openTariffs()" in out


def test_the_tariffs_open_on_the_drawn_page(monkeypatch, tmp_path):
    """Кнопка «Тарифы» видна в шапке и открывает кабинет с условиями — в браузере."""
    pytest.importorskip("playwright.sync_api")
    from playwright.sync_api import sync_playwright

    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import browser

    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    path = browser.chromium_or_skip()
    errors: list[str] = []
    with browser.serve(core.app, 18971) as base, sync_playwright() as pw:
        with pw.chromium.launch(executable_path=str(path)) as engine:
            page = engine.new_page(viewport={"width": 1440, "height": 900})
            page.on("pageerror", lambda exc: errors.append(str(exc)))
            page.goto(base, wait_until="networkidle")
            button = page.locator("#tariffsButton")
            assert button.is_visible()
            button.click()
            page.wait_for_function(
                "document.getElementById('tariffsBox').textContent.includes('Подписка')")
            text = page.locator("#tariffsBox").inner_text()
            assert page.locator("#projectsDialog").is_visible()
            footer = page.locator("footer").first.inner_text()
            page.close()
    assert "10 000 ₽" in text.replace(" ", " ") and "в том числе НДС 5" in text
    assert "войдите через Telegram" in text
    assert "свидетельство № 2026691589" in footer
    assert not errors, errors


def test_a_grant_to_an_unknown_id_is_refused_and_names_the_recipient():
    """Опечатка в номере не открывает доступ несуществующему человеку, а удачная
    выдача говорит, кому и что выдано (замечание владельца, 22.10.2026)."""
    refused = client.post("/access/admin/grant", json={"key": "kluch", "chat": 1,
                                                       "kind": "subscription"})
    assert refused.status_code == 400 and "ещё не было" in refused.json()["detail"]
    assert not core.access_status(1)["subscription_active"]
    core.users_touch(CHAT, surface="telegram", name="Иван Петров")
    granted = client.post("/access/admin/grant", json={
        "key": "kluch", "chat": CHAT, "kind": "plot",
        "cadastral": [A1, "50:20:0010101:32"]}).json()
    assert granted["who"] == f"Иван Петров (ID {CHAT})"
    assert granted["what"].startswith("участок 50:20:0010101:31, 50:20:0010101:32")
    # Набор открывает и любую свою часть.
    assert core.access_use(CHAT, core.access_plot(cadastral=[A1]))["allowed"]


def test_the_grant_form_names_its_fields_on_the_drawn_page(monkeypatch):
    """Подписи полей видны и после ввода; подписка прячет поле номеров; срок — 30."""
    pytest.importorskip("playwright.sync_api")
    from playwright.sync_api import sync_playwright

    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import browser

    core.users_touch(CHAT, surface="telegram", name="Иван Петров")
    admin_session = core._telegram_session(ADMIN, [])
    path = browser.chromium_or_skip()
    with browser.serve(core.app, 18975) as base, sync_playwright() as pw:
        with pw.chromium.launch(executable_path=str(path)) as engine:
            page = engine.new_page(viewport={"width": 1280, "height": 900})
            page.add_init_script(
                f"localStorage.setItem('developaid_web_session', {json.dumps(admin_session)})")
            page.goto(base, wait_until="networkidle")
            page.click("#tariffsButton")
            page.wait_for_function(
                "document.querySelector('#grantChat option[value=\"" + str(CHAT) + "\"]')")
            form = page.inner_text(".grant-form")
            assert "Кому выдать доступ" in form and "Кадастровые номера участка" in form
            assert "несколько участков" in form
            assert page.input_value("#grantDays") == "30"
            assert "Иван Петров" in page.inner_text("#grantChat")
            page.select_option("#grantKind", "subscription")
            assert not page.locator("#grantCadastralRow").is_visible()
            page.select_option("#grantChat", str(CHAT))
            page.click(".grant-form button:has-text('Выдать доступ')")
            page.wait_for_function(
                "document.getElementById('accessAdminStatus').textContent.includes('Выдано')")
            status = page.inner_text("#accessAdminStatus")
            page.close()
    assert "подписка" in status and "Иван Петров" in status


def test_the_cabinet_speaks_one_type_scale_on_the_drawn_page(monkeypatch):
    """Кабинет набран шкалой страницы: не больше трёх кеглей и одно семейство.

    Жалоба владельца: «залито оформлен и разными шрифтами» — внутри окна было
    восемь размеров (10,8–17 px) и Arial у полей рядом с системным шрифтом.
    Меряется отрисованный кабинет администратора, где видны все блоки: тарифы
    с включённой оплатой (как на проде), выдача доступа, таблицы людей и
    оплат, демо-ссылки, мои проекты. Почта для чека и число участков стоят в
    одной строке, а селекты без системного вида: Safari иначе рисует их своим
    шрифтом.
    """
    pytest.importorskip("playwright.sync_api")
    from playwright.sync_api import sync_playwright

    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import browser

    monkeypatch.setattr(core, "payments_available", lambda: True)
    core.users_touch(CHAT, surface="telegram", name="Иван Петров")
    client.post("/access/admin/demo/create", json={"key": "kluch", "days": 5, "note": "проверка",
                                                 "blocks": ["calc", "cabinet"]})
    admin_session = core._telegram_session(ADMIN, [])
    path = browser.chromium_or_skip()
    with (browser.serve(core.app, 18977) as base, sync_playwright() as pw,
          pw.chromium.launch(executable_path=str(path)) as engine):
        page = engine.new_page(viewport={"width": 1200, "height": 900})
        page.add_init_script(
            f"localStorage.setItem('developaid_web_session', {json.dumps(admin_session)})")
        page.goto(base, wait_until="networkidle")
        page.click("#tariffsButton")
        page.wait_for_function(
            "document.querySelector('#grantChat option[value=\"" + str(CHAT) + "\"]')"
            "&&document.querySelector('#demoInviteList .demo-link')"
            "&&document.getElementById('payPlotButton')")
        seen = page.evaluate("""() => {
          const sizes = {}, families = {};
          for (const el of document.querySelectorAll('#projectsDialog *')) {
            if (!el.getClientRects().length) continue;
            const own = ['INPUT','SELECT','BUTTON','TEXTAREA'].includes(el.tagName)
              || [...el.childNodes].some(n => n.nodeType === 3 && n.textContent.trim());
            if (!own) continue;
            const cs = getComputedStyle(el), where = el.id || el.className || el.tagName;
            (sizes[cs.fontSize] = sizes[cs.fontSize] || []).push(where);
            (families[cs.fontFamily] = families[cs.fontFamily] || []).push(where);
          }
          const top = id => Math.round(document.getElementById(id).getBoundingClientRect().top);
          const looks = [...document.querySelectorAll('#projectsDialog select')]
            .map(el => getComputedStyle(el).appearance);
          return {sizes, families, rows: [top('payEmail'), top('payCount')], looks};
        }""")
        page.close()
    assert len(seen["sizes"]) <= 3, {k: v[:5] for k, v in seen["sizes"].items()}
    assert len(seen["families"]) == 1, {k: v[:5] for k, v in seen["families"].items()}
    assert abs(seen["rows"][0] - seen["rows"][1]) <= 4, seen["rows"]
    assert set(seen["looks"]) == {"none"}, seen["looks"]
