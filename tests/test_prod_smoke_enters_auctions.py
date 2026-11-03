"""Смоук прода входит в закрытый раздел «Торги», а не ждёт его 120 секунд.

После личных ключей торгов (#594) /auctions без входа отвечает 401 и формой
ключа. Шаг «3. Excel-выгрузка торгов» открывал страницу без входа и падал
таймаутом `wait_for_function`. Здесь заглушка-сервер ведёт себя как прод:
страница закрыта до `POST /auctions/login`. Смоук с ключом входит и
выгружает; без ключа — сразу понятная причина.

Запуск: python3 -m pytest tests/test_prod_smoke_enters_auctions.py -q
"""

from __future__ import annotations

import importlib.util
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs

import pytest

ROOT = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location("prod_smoke_auctions", ROOT / "scripts" / "prod_smoke.py")
smoke = importlib.util.module_from_spec(_spec)
sys.modules["prod_smoke_auctions"] = smoke
_spec.loader.exec_module(smoke)

GOOD_KEY = "smoke-auctions-key"
XLSX = b"PK\x03\x04 fake workbook"

LOGIN_FORM = (b'<!doctype html><form method="post" action="/auctions/login">'
              b'<input name="key"><button>OK</button></form>')
PAGE = b"""<!doctype html><meta charset="utf-8">
<button id="refresh" onclick="discover()">refresh</button>
<a id="auctionExport" href="/auctions/export.xlsx" download="auctions.xlsx">xlsx</a>
<script>var state={filtered:[]};function discover(){state.filtered=[1,2,3]}</script>"""


class _Prod(BaseHTTPRequestHandler):
    def log_message(self, *args):  # тишина в выводе pytest
        pass

    def _entered(self) -> bool:
        return "auctions_view=ok" in (self.headers.get("Cookie") or "")

    def _send(self, status: int, body: bytes, ctype: str = "text/html; charset=utf-8",
              extra: dict | None = None):
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        for name, value in (extra or {}).items():
            self.send_header(name, value)
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path.startswith("/auctions/export.xlsx"):
            if not self._entered():
                return self._send(401, b'{"detail":"need key"}', "application/json")
            return self._send(200, XLSX, "application/vnd.openxmlformats-officedocument."
                              "spreadsheetml.sheet",
                              {"Content-Disposition": 'attachment; filename="auctions.xlsx"'})
        if self.path.rstrip("/") == "/auctions":
            if self._entered():
                return self._send(200, PAGE)
            return self._send(401, LOGIN_FORM)
        return self._send(404, b"no")

    def do_POST(self):
        length = int(self.headers.get("Content-Length") or 0)
        form = parse_qs(self.rfile.read(length).decode("utf-8"))
        if self.path == "/auctions/login" and (form.get("key") or [""])[0] == GOOD_KEY:
            return self._send(303, b"", extra={"Location": "/auctions",
                                               "Set-Cookie": "auctions_view=ok; Path=/"})
        return self._send(401, LOGIN_FORM)


@pytest.fixture()
def prod():
    pytest.importorskip("playwright.sync_api")
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Prod)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_address[1]}"
    server.shutdown()


def _export(base, tmp_path, key):
    logs: list[str] = []
    try:
        return smoke.browser_auction_export(base, tmp_path, logs.append, key)
    except smoke.AuctionsLocked:
        raise
    except Exception as exc:  # noqa: BLE001
        if "Executable doesn't exist" in str(exc) or "launch" in str(exc).lower():
            pytest.skip(f"Chromium недоступен: {exc}")
        raise


def test_with_a_key_the_smoke_enters_and_downloads(prod, tmp_path, monkeypatch):
    monkeypatch.delenv("HTTPS_PROXY", raising=False)
    status, body, count = _export(prod, tmp_path, GOOD_KEY)
    assert status == 200
    assert body == XLSX
    assert count == 3


def test_without_a_key_the_reason_is_named_at_once(prod, tmp_path, monkeypatch):
    monkeypatch.delenv("HTTPS_PROXY", raising=False)
    began = time.monotonic()
    with pytest.raises(smoke.AuctionsLocked) as caught:
        _export(prod, tmp_path, "")
    assert time.monotonic() - began < 60, "причина сразу, а не таймаут ожидания"
    assert caught.value.keyed is False
    assert smoke.AUCTIONS_KEY_ENV in str(caught.value)


def test_a_wrong_key_is_named_as_not_accepted(prod, tmp_path, monkeypatch):
    monkeypatch.delenv("HTTPS_PROXY", raising=False)
    with pytest.raises(smoke.AuctionsLocked) as caught:
        _export(prod, tmp_path, "wrong")
    assert caught.value.keyed is True
    assert "не принят" in str(caught.value)


def test_without_the_login_step_the_check_fails(prod, tmp_path, monkeypatch):
    """Подделка: вход убран (функция входа ничего не делает). Смоук с ключом
    обязан тогда упереться в форму — иначе тест входа выше ничего не доказывал."""
    monkeypatch.delenv("HTTPS_PROXY", raising=False)
    monkeypatch.setattr(smoke, "_auctions_login", lambda *a, **k: True)
    with pytest.raises(smoke.AuctionsLocked):
        _export(prod, tmp_path, GOOD_KEY)


@pytest.mark.parametrize("keyed, verdict", [(False, "SKIP"), (True, "FAIL")])
def test_run_reports_the_locked_section(monkeypatch, tmp_path, keyed, verdict):
    """В итоге прогона закрытый раздел — строка с причиной: без ключа пропуск,
    с непринятым ключом провал."""
    def locked(*args, **kwargs):
        raise smoke.AuctionsLocked("раздел закрыт", keyed=keyed)

    monkeypatch.setattr(smoke, "browser_auction_export", locked)
    monkeypatch.setattr(smoke, "browser_project", lambda *a, **k: {
        "itog": {"params": {}, "locked": True}, "payload": {}})
    monkeypatch.setattr(smoke, "fetch", lambda *a, **k: (503, "", b"", ""))
    checks = smoke.run("http://prod.invalid", smoke.load_reference(), "", tmp_path,
                       lambda _m: None, "key" if keyed else "")
    row = next(c for c in checks if c.name.startswith("3."))
    assert row.status == getattr(smoke, verdict)
    assert "раздел закрыт" in row.detail
