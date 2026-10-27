"""Весть «вам открыт доступ» доходит, даже когда ядро не видит Telegram.

Доступ выдаётся на ядре (Яндекс), а до api.telegram.org достаёт только Render.
Прежде выдавший читал «Telegram API недоступен: Network is unreachable.
Напишите человеку сами». Теперь весть ложится в очередь ядра, бот на Render
забирает её подписанным запросом и отправляет. Отказ самого Telegram (человек
не писал боту) — другое: в очередь он не идёт, причина уходит выдавшему.

Запуск: python3 -m pytest tests/test_the_grant_notice_reaches_telegram_through_the_bot.py -q
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

sys.path.insert(0, str(Path(__file__).resolve().parent))

import main as _wrapper

core = _wrapper.core
client = TestClient(core.app)
CHAT, ADMIN = 9292, 779


@pytest.fixture(autouse=True)
def env(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123456:grant-notice-token")
    monkeypatch.setenv("DEVELOPAID_ADMIN_IDS", str(ADMIN))
    monkeypatch.setenv("DEVELOPAID_ADMIN_KEY", "kluch")
    monkeypatch.setattr(core, "_MO_CALC_API_URL", "")
    core.users_touch(CHAT, surface="telegram", name="Ольга")
    yield


def _grant() -> dict:
    answer = client.post("/access/admin/grant", json={"key": "kluch", "chat": CHAT,
                                                      "kind": "subscription", "days": 30})
    assert answer.status_code == 200, answer.text
    return answer.json()


def _unreachable(chat, text, **_):
    raise RuntimeError("Telegram API недоступен: <urlopen error [Errno 101] Network is unreachable>")


def _notices(sign: str | None = None) -> dict:
    sign = core._web_login_sign("access-notices", 0) if sign is None else sign
    return client.post("/internal/access/notices",
                       json={"code": "access-notices", "chat_id": 0, "sign": sign})


def test_an_unreachable_telegram_queues_the_notice_and_says_so(monkeypatch):
    monkeypatch.setattr(core, "_telegram_send_message", _unreachable)
    notice = _grant()["notice"]
    assert notice["sent"] is False and notice["queued"] is True
    assert "отправит бот" in notice["reason"] and "Network" not in notice["reason"]
    assert _notices("чужая").status_code == 403
    queued = _notices().json()["notices"]
    assert [n["chat"] for n in queued] == [CHAT] and "подписк" in queued[0]["text"].lower()
    assert _notices().json()["notices"] == [], "весть отдаётся один раз"


def test_the_bot_sends_what_the_core_queued(monkeypatch):
    monkeypatch.setattr(core, "_telegram_send_message", _unreachable)
    _grant()
    sent: list[tuple[int, str]] = []
    monkeypatch.setattr(core, "_telegram_send_message", lambda chat, text, **_: sent.append((chat, text)))
    monkeypatch.setattr(core, "_telegram_webhook_enabled", lambda: True)
    _wrapper._deliver_access_notices()
    assert [chat for chat, _ in sent] == [CHAT]
    _wrapper._deliver_access_notices()
    assert len(sent) == 1, "отправленное второй раз не уходит"


def test_a_telegram_refusal_is_not_queued(monkeypatch):
    def refused(chat, text, **_):
        raise RuntimeError("Telegram API: HTTP 403: Forbidden: bot was blocked by the user")
    monkeypatch.setattr(core, "_telegram_send_message", refused)
    notice = _grant()["notice"]
    assert notice["sent"] is False and not notice.get("queued")
    assert "blocked" in notice["reason"]
    assert _notices().json()["notices"] == []


def test_the_page_says_the_bot_will_send_it(monkeypatch):
    """Настоящий `accessAdminGrant` страницы: очередь — не «напишите сами»."""
    import page_blocks

    prelude = """
const fields={grantChat:{value:'CHAT'},grantKind:{value:'subscription'},grantCadastral:{value:''},
 grantDays:{value:'30'},grantCount:{value:'0'},grantNote:{value:''},accessAdminStatus:{textContent:''}};
const document={getElementById:id=>fields[id]||null};
function renderAccessAdmin(){}
function accessDate(){return '25.11.2026'}
function escapeHtml(s){return String(s)}
async function accessAdminCall(){return {what:'подписка',who:'Ольга (ID CHAT)',until:1795000000,
 notice:{sent:false,queued:true,reason:'сервер расчётов сам до Telegram не достаёт, его отправит бот в течение минуты'}}}
""".replace("CHAT", str(CHAT))
    out, _ = page_blocks.run(prelude, "accessAdminGrant().then(()=>console.log(fields.accessAdminStatus.textContent));")
    assert "его отправит бот" in out and "Напишите человеку сами" not in out


def test_the_bot_grant_command_says_the_bot_will_send_it(monkeypatch):
    monkeypatch.setattr(core, "_telegram_send_message", _unreachable)
    said: list[str] = []
    monkeypatch.setattr(_wrapper, "_send_message", lambda chat, text, *a, **k: said.append(text))
    _wrapper._grant_command(ADMIN, ADMIN, f"{CHAT} 30 подписка")
    assert said and "отправит бот" in said[-1] and "Напишите ему сами" not in said[-1]


def test_the_bot_comes_for_the_notice_within_the_promised_minute():
    """Обещание «в течение минуты» держится кругом опроса, а не памятью."""
    assert 0 < core.ACCESS_NOTICE_POLL_SECONDS <= 60
    assert callable(_wrapper._access_notices_loop)


def test_a_round_on_the_core_itself_does_not_lose_the_notice(monkeypatch):
    """Круг доставки, запущенный там, где Telegram не виден, весть не теряет."""
    monkeypatch.setattr(core, "_telegram_send_message", _unreachable)
    monkeypatch.setattr(core, "_telegram_webhook_enabled", lambda: True)
    _grant()
    _wrapper._deliver_access_notices()
    assert [n["chat"] for n in _notices().json()["notices"]] == [CHAT]
