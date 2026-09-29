"""Обрыв соединения на одной проверке прода не роняет весь прогон.

Прод после выката оборвал POST /report/teaser (RemoteDisconnected): исключение
вылетело из `run`, проверки 3–5 не выполнились, итог не записался, issue не
создался. Здесь `http` подменён без сети: тизер рвёт соединение, остальные
маршруты отвечают. Прогон обязан дойти до конца, назвать причину и место
обрыва в строке тизера и записать итог и json.

Запуск: python3 -m pytest tests/test_prod_smoke_survives_disconnect.py -q
"""

from __future__ import annotations

import importlib.util
import json
import sys
from http.client import RemoteDisconnected
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location("prod_smoke_disconnect", ROOT / "scripts" / "prod_smoke.py")
smoke = importlib.util.module_from_spec(_spec)
sys.modules["prod_smoke_disconnect"] = smoke
_spec.loader.exec_module(smoke)

REF = smoke.load_reference()


class FakeProd:
    """Прод без сети: тизер рвёт соединение `drops` раз, остальное отвечает."""

    def __init__(self, drops: int, teaser_status: int = 200):
        self.drops = drops
        self.teaser_status = teaser_status
        self.calls: list[str] = []

    def __call__(self, method, url, body=None, timeout=300, headers=None):
        path = url.split("://", 1)[-1].split("/", 1)[-1]
        self.calls.append(f"{method} /{path}")
        if path == "health":
            return 200, "application/json", json.dumps({"version": "v-test", "commit": "abc"}).encode()
        if path == "land/lookup":
            results = [{"found": True, "cadastral_number": n,
                        "area_ha": float(REF["land_area_ha"]) / len(REF["cadastral_numbers"])}
                       for n in REF["cadastral_numbers"]]
            return 200, "application/json", json.dumps({"results": results}).encode()
        if path == "report/teaser":
            if self.drops:
                self.drops -= 1
                raise RemoteDisconnected("Remote end closed connection without response")
            return self.teaser_status, "text/plain", b"Internal Server Error"
        if path == "report/workbook":
            return 500, "text/plain", b"boom"
        raise AssertionError(f"неожиданный маршрут {url}")


@pytest.fixture
def prod(monkeypatch, tmp_path):
    def install(fake: FakeProd):
        monkeypatch.setattr(smoke, "http", fake)
        monkeypatch.setattr(smoke, "RETRY_PAUSE", 0)
        monkeypatch.setattr(smoke, "browser_project", lambda *a, **k: {
            "itog": {"params": {}, "locked": False}, "payload": {"inputs": {}, "tep": {}}})
        monkeypatch.setattr(smoke, "browser_auction_export",
                            lambda *a, **k: (503, b"unavailable", 0))
        monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
        return fake
    return install


def _main(tmp_path):
    summary, result = tmp_path / "summary.md", tmp_path / "result.json"
    code = smoke.main(["--base", "https://prod.test", "--summary", str(summary),
                       "--json", str(result), "--out", str(tmp_path / "out")])
    return code, summary.read_text(encoding="utf-8"), json.loads(result.read_text(encoding="utf-8"))


def test_a_disconnect_on_the_teaser_fails_only_the_teaser(prod, tmp_path):
    fake = prod(FakeProd(drops=2))
    code, summary, result = _main(tmp_path)

    assert code == 1
    names = [c["name"] for c in result["checks"]]
    for want in ("1. Автозагрузка участков", "2. Тизер PDF", "3. Excel-выгрузка торгов",
                 "4. Книга Excel v4", "5. Страница «Итог»"):
        assert want in names, f"проверка «{want}» не выполнена: {names}"
    assert "POST /report/workbook" in fake.calls, "после обрыва на тизере книга не запрошена"
    assert fake.calls.count("POST /report/teaser") == 2, "обрыв без ответа повторяется ровно один раз"

    teaser = next(c for c in result["checks"] if c["name"] == "2. Тизер PDF")
    assert teaser["status"] == "fail"
    assert "обрыв соединения" in teaser["detail"]
    assert "POST /report/teaser через" in teaser["detail"]
    assert "повтор после обрыва" in teaser["detail"]
    assert "обрыв соединения" in summary and "POST /report/teaser" in summary
    autoload = next(c for c in result["checks"] if c["name"] == "1. Автозагрузка участков")
    assert autoload["status"] == "ok"


def test_one_disconnect_is_retried_and_marked(prod, tmp_path):
    fake = prod(FakeProd(drops=1, teaser_status=500))
    _code, _summary, result = _main(tmp_path)

    assert fake.calls.count("POST /report/teaser") == 2
    teaser = next(c for c in result["checks"] if c["name"] == "2. Тизер PDF")
    # Второй ответ — HTTP 500: это ответ прода, он остаётся провалом.
    assert teaser["status"] == "fail"
    assert "HTTP 500" in teaser["got"]
    assert "повтор после обрыва" in teaser["got"]


def test_an_http_error_is_not_retried(prod, tmp_path):
    fake = prod(FakeProd(drops=0, teaser_status=502))
    _code, _summary, result = _main(tmp_path)

    assert fake.calls.count("POST /report/teaser") == 1
    teaser = next(c for c in result["checks"] if c["name"] == "2. Тизер PDF")
    assert teaser["status"] == "fail" and "HTTP 502" in teaser["got"]
    assert "повтор" not in teaser["got"]


def test_the_workflow_raises_an_issue_when_the_summary_is_missing():
    wf = yaml.safe_load((ROOT / ".github" / "workflows" / "prod-smoke.yml").read_text(encoding="utf-8"))
    steps = wf["jobs"]["smoke"]["steps"]
    smoke_step = next(s for s in steps if s.get("id") == "smoke")
    script = smoke_step["run"]
    # Итог не записан — шаг пишет его сам с причиной, до `cat`, и код не теряется.
    missing = script.index("[ ! -s smoke-summary.md ]")
    assert "прогон упал без итога" in script
    assert missing < script.index("cat smoke-summary.md")
    assert missing < script.index('echo "code=$code"')
    issue = next(s for s in steps if s.get("name") == "Issue prod-regression")
    assert "steps.smoke.outcome == 'failure'" in issue["if"]
    assert "прогон упал без итога" in issue["with"]["script"]


class TicketProd(FakeProd):
    """Холодный тизер: POST отвечает 202 с билетом, опрос билета один раз рвётся."""

    def __call__(self, method, url, body=None, timeout=300, headers=None):
        path = url.split("://", 1)[-1].split("/", 1)[-1]
        if path == "report/teaser":
            self.calls.append(f"{method} /{path}")
            return 202, "application/json", json.dumps({"ticket": "ab" * 16, "detail": "сборка"}).encode()
        if path.startswith("report/teaser/"):
            self.calls.append(f"{method} /report/teaser/<ticket>")
            if self.drops:
                self.drops -= 1
                raise RemoteDisconnected("Remote end closed connection without response")
            return 500, "text/plain", b"Internal Server Error"
        return super().__call__(method, url, body, timeout, headers)


def test_a_disconnect_while_polling_the_ticket_is_retried(prod, tmp_path, monkeypatch):
    fake = prod(TicketProd(drops=1))
    monkeypatch.setattr(smoke.time, "sleep", lambda _s: None)
    _code, _summary, result = _main(tmp_path)

    assert fake.calls.count("GET /report/teaser/<ticket>") == 2
    teaser = next(c for c in result["checks"] if c["name"] == "2. Тизер PDF")
    assert teaser["status"] == "fail" and "HTTP 500" in teaser["got"]
    assert "повтор после обрыва" in teaser["got"] and "GET /report/teaser/" in teaser["got"]
    assert "4. Книга Excel v4" in [c["name"] for c in result["checks"]]
