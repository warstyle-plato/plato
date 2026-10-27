"""Отказ сервера печатается словами, а не «[object Object]».

Владелец выдавал подписку в кабинете (26.10.2026) и вместо причины увидел
«[object Object]»: страница подставляла `detail` ответа как есть, а отказ
проверки полей (FastAPI, 422) приходит списком {loc, msg}. Разбор теперь
один — `serverDetail`, — и его читают все запросы страницы.

Запуск: python3 -m pytest tests/test_a_server_refusal_is_said_in_words.py -q
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import page_blocks

import main as _wrapper

core = _wrapper.core
client = TestClient(core.app)
ADMIN, CHAT = 777, 9393


@pytest.fixture(autouse=True)
def env(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123456:refusal-test-token")
    monkeypatch.setenv("DEVELOPAID_ADMIN_IDS", str(ADMIN))
    monkeypatch.setattr(core, "_MO_CALC_API_URL", "")
    yield


def _real_422() -> dict:
    """Настоящий ответ сервера на поле не того вида — не выдуманный образец."""
    answer = client.post("/access/admin/grant", json={"chat": "не число"})
    assert answer.status_code == 422
    return answer.json()


def _said(data) -> str:
    out, _ = page_blocks.run("", f"console.log(serverDetail({json.dumps(data)}));")
    return out.strip()


def test_every_shape_of_refusal_is_words():
    said = _said(_real_422())
    assert "[object Object]" not in said and "поле «chat»" in said
    assert _said({"detail": "Раздел доступен только администраторам."}) == \
        "Раздел доступен только администраторам."
    assert _said({}) == ""
    assert _said({"detail": {"message": "Нет связи с ядром"}}) == "Нет связи с ядром"


def test_the_page_reads_refusals_through_one_place():
    """Сырое `x.detail||…` на странице снова дало бы «[object Object]».

    Страница — как у посетителя: с кусками, которые вставляют модули
    `main_registry` (льгота МПТ). Без него проверка зависела бы от того, загрузил
    ли их другой тест раньше в том же процессе."""
    import re

    import main_registry  # noqa: F401 — дописывает свои куски в PAGE

    raw = re.findall(r"(?<![\w.])\w+\.detail\|\|", core.PAGE)
    assert not raw, f"отказ сервера читается мимо serverDetail: {raw[:5]}"


def test_the_grant_form_says_the_refusal_on_the_drawn_page():
    pytest.importorskip("playwright.sync_api")
    from playwright.sync_api import sync_playwright

    import browser

    core.users_touch(CHAT, surface="telegram", name="Иван Петров")
    refusal = _real_422()
    path = browser.chromium_or_skip()
    with browser.serve(core.app, 18996) as base, sync_playwright() as pw:
        with pw.chromium.launch(executable_path=str(path)) as engine:
            page = engine.new_page(viewport={"width": 1280, "height": 900})
            page.route("**/access/admin/grant", lambda route: route.fulfill(
                status=422, content_type="application/json", body=json.dumps(refusal)))
            page.add_init_script("localStorage.setItem('developaid_web_session', "
                                 f"{json.dumps(core._telegram_session(ADMIN, []))})")
            page.goto(base, wait_until="networkidle")
            page.add_style_tag(content="#profileDialog{display:none!important}")
            page.click("#tariffsButton")
            page.wait_for_function(
                "document.querySelector('#grantChat option[value=\"" + str(CHAT) + "\"]')")
            # Форма выдачи доступа — на вкладке «Администрирование» кабинета
            # (её показывает ответ сервера is_admin), а кнопка тарифов
            # открывает вкладку «Тарифы и доступ».
            page.click("#cabTabAdmin")
            page.select_option("#grantKind", "subscription")
            page.select_option("#grantChat", str(CHAT))
            page.click("button:has-text('Выдать доступ')")
            page.wait_for_function(
                "document.getElementById('accessAdminStatus').textContent.length>0")
            status = page.inner_text("#accessAdminStatus")
            page.close()
    assert "[object Object]" not in status
    assert "Сервер не принял запрос" in status and "поле «chat»" in status
