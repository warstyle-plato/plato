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

    # Явный refresh на карточке — уже команда, а не просмотр.
    assert client.get(
        "/krt/nagatino/parcels",
        params={"refresh": "true"},
    ).status_code == 403

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


def test_install_does_not_break_an_already_started_fastapi_app(monkeypatch):
    """Некоторые тестовые/встраиваемые приложения доустанавливают модуль позже."""
    monkeypatch.setenv(view_access.ENV_NAME, VIEW_KEY)
    app = FastAPI()

    @app.get("/ping")
    async def ping():
        return {"ok": True}

    client = TestClient(app)
    assert client.get("/ping").status_code == 200
    # FastAPI уже собрал middleware_stack. install не должен пытаться вызвать
    # add_middleware после этого — именно это ломало независимые тесты ядра.
    install(app)
    assert client.get("/ping").status_code == 200


def _viewer(monkeypatch):
    _keys(monkeypatch)
    client = _without_core(monkeypatch)
    entered = client.post("/auctions/login", data={"key": VIEW_KEY},
                          follow_redirects=False)
    assert entered.status_code == 303
    return client


def test_a_command_flag_is_read_like_fastapi_reads_bool(monkeypatch):
    """`?refresh=t` FastAPI читает как True; гейт обязан читать так же."""
    client = _viewer(monkeypatch)
    for name, value in (("refresh", "t"), ("refresh", "y"), ("refresh", "True"),
                        ("force", "Y"), ("rebuild", "on"), ("ensure_model", "1")):
        answer = client.get("/auctions/krt/map", params={name: value})
        assert answer.status_code == 403, (name, value, answer.status_code)
        assert name in answer.json()["detail"]
    # Ложные значения — чистое чтение: гейт пропускает дальше маршрута.
    for value in ("", "0", "false", "f", "n", "no", "off"):
        assert view_access.command_flag({"refresh": value}) == ""


def test_the_view_key_opens_only_listed_routes(monkeypatch):
    """Новый маршрут закрыт для ключа просмотра, пока его не внесли в список."""
    client = _viewer(monkeypatch)
    for path in (
        "/auctions/krt/some-site/open-sources",      # платный поиск и запись
        "/auctions/krt/api-probe/browser",           # браузер по чужому url=
        "/auctions/roseltorg/browser",
        "/auctions/fedresurs/browser",
        "/auctions/etp/probe/browser",
        "/auctions/krt/some-site/report",
        "/auctions/krt/some-site/market",
        "/auctions/egrn/archive",
    ):
        answer = client.get(path, params={"url": "http://169.254.169.254/"})
        assert answer.status_code == 403, (path, answer.status_code)
        assert "ключом кабинета" in answer.json()["detail"]
    for path in ("/auctions/krt/ranking/refresh", "/auctions/krt/press/run",
                 "/auctions/ingest", "/auctions/krt/investment-rating/target"):
        assert client.post(path).status_code == 403, path


def test_the_view_key_may_export_what_it_sees(monkeypatch):
    """Выгрузка xlsx ничего не пишет: это тот же просмотр, файлом."""
    client = _viewer(monkeypatch)
    answer = client.post("/auctions/export.xlsx", json={"rows": [], "kind": "krt"})
    assert answer.status_code == 200, answer.text
    assert answer.content[:2] == b"PK"


def test_the_view_key_does_not_order_paid_lot_comments(monkeypatch, tmp_path):
    """Выгрузка по ключу просмотра читает готовые комментарии, но не ставит лоты в платный разбор."""
    from auction_search import lot_notes

    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    client = _viewer(monkeypatch)
    rows = [{"section": "Торги", "name": "Лот", "url": "https://etp/lot/1"}]
    assert client.post("/auctions/export.xlsx", json={"rows": rows, "kind": "auctions"}).status_code == 200
    assert lot_notes.LotNotes(tmp_path / "market").queue() == []
