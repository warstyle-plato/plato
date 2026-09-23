"""Отдельный ключ открывает только просмотр /auctions и карточек КРТ."""

from __future__ import annotations

import sys
import types

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from auction_search.api import install
from auction_search import view_access
from market_search import cabinet as market_cabinet


VIEW_KEY = "plato-auctions-test-2026"
FULL_KEY = "plato-market-test-2026"


def _without_core(monkeypatch):
    monkeypatch.delitem(sys.modules, "developaid_core", raising=False)
    app = FastAPI()
    install(app)
    return TestClient(app)


def _with_owner_gate(monkeypatch):
    def require_admin(session: str, key: str, what: str) -> None:
        if key != "owner":
            raise HTTPException(status_code=401, detail=f"{what}: не владелец")

    core = types.ModuleType("developaid_core")
    core._require_admin = require_admin  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "developaid_core", core)
    app = FastAPI()
    install(app)
    return TestClient(app)


def _keys(monkeypatch):
    monkeypatch.setenv(view_access.ENV_NAME, VIEW_KEY)
    monkeypatch.setenv(market_cabinet.ENV_NAME, FULL_KEY)


def test_auctions_view_key_has_its_own_login_and_is_read_only(monkeypatch):
    _keys(monkeypatch)
    client = _without_core(monkeypatch)

    locked = client.get("/auctions")
    assert locked.status_code == 401
    assert 'action="/auctions/login"' in locked.text
    assert "карточки КРТ" in locked.text

    wrong = client.post(
        "/auctions/login",
        data={"key": "not-the-key"},
        follow_redirects=False,
    )
    assert wrong.status_code == 401

    entered = client.post(
        "/auctions/login",
        data={"key": VIEW_KEY},
        follow_redirects=False,
    )
    assert entered.status_code == 303
    assert entered.headers["location"] == "/auctions"
    assert view_access.COOKIE_NAME in entered.headers.get("set-cookie", "")
    # После входа секрет не возвращается браузеру: cookie — производный HMAC.
    assert VIEW_KEY not in entered.headers.get("set-cookie", "")
    assert market_cabinet.COOKIE_NAME not in entered.headers.get("set-cookie", "")

    assert client.get("/auctions").status_code == 200

    # Ограниченный ключ смотрит, но не меняет состояние. Проверяем на
    # несуществующем POST: 403 отдаёт именно гейт до маршрутизации.
    denied = client.post("/auctions/no-such-route")
    assert denied.status_code == 403
    assert "только просмотр" in denied.text

    # GET с побочным эффектом тоже не становится разрешённым из-за метода.
    refresh = client.get("/auctions/krt", params={"refresh": "true"})
    assert refresh.status_code == 403


def test_full_market_key_still_has_full_auction_access(monkeypatch):
    _keys(monkeypatch)
    client = _without_core(monkeypatch)

    entered = client.post(
        "/auctions/login",
        data={"key": FULL_KEY},
        follow_redirects=False,
    )
    assert entered.status_code == 303
    assert market_cabinet.COOKIE_NAME in entered.headers.get("set-cookie", "")

    # Полный ключ проходит гейт; дальше отвечает обычный роутер.
    assert client.post("/auctions/no-such-route").status_code == 404


def test_view_key_opens_krt_site_data_but_not_share_or_cabinet_role(monkeypatch):
    _keys(monkeypatch)
    client = _with_owner_gate(monkeypatch)

    # Без любого ключа служебные данные карточки по-прежнему закрыты.
    assert client.get("/krt/site/no-such-site/parcels").status_code == 401

    entered = client.post(
        "/auctions/login",
        data={"key": VIEW_KEY},
        follow_redirects=False,
    )
    assert entered.status_code == 303

    # 404 здесь важнее 401: ограниченный ключ прошёл общий гейт карточек,
    # после чего уже обычный поиск честно сказал, что такого slug нет.
    assert client.get("/krt/site/no-such-site/parcels").status_code == 404

    # Выдавать публичную ссылку может только владелец. Read-only ключ этого
    # маршрута не открывает.
    assert client.get("/krt/nagatino/share").status_code == 401

    # И роль кабинета рынка ему не присваивается.
    assert not market_cabinet.key_accepted(VIEW_KEY)


def test_auctions_gate_is_dormant_until_the_new_env_is_configured(monkeypatch):
    monkeypatch.delenv(view_access.ENV_NAME, raising=False)
    monkeypatch.delenv(market_cabinet.ENV_NAME, raising=False)
    client = _without_core(monkeypatch)

    # Код можно выкатить раньше секрета: до настройки AUCTIONS_VIEW_KEY
    # существующий /auctions не закрывается внезапно.
    assert client.get("/auctions").status_code == 200
