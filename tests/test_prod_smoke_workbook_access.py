"""Штатный smoke передаёт ключ в JSON книги и не скрывает её отказ пропуском.

Выполняем настоящий main/run/fetch/http и судью книги. Подменены только браузер
и urlopen: сервер, его ключи, приложение и внешние сервисы не запускаются.
Контракт запроса сверён с WorkbookExportRequest и report_workbook; страница
exportModelArchive передаёт те же session/access_key в JSON.
"""

from __future__ import annotations

import importlib.util
import io
import json
import sys
import urllib.error
from pathlib import Path
from urllib.parse import urlsplit

import openpyxl
import pytest

ROOT = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location("prod_smoke_workbook_access",
                                               ROOT / "scripts" / "prod_smoke.py")
smoke = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = smoke
_spec.loader.exec_module(smoke)

KEY = "fictional-workbook-smoke-key"
NAME = "4. Книга Excel v4"
REF = smoke.load_reference()
PAYLOAD = {
    "inputs": {"project_kind": "mixed"},
    "tep": {"offices": {"gns": 1000}, "standalone_retail": {"gns": 2000}},
    "rates": [], "phasing": {}, "scenario": "base",
}


def _book(sheet="Вводные"):
    wb = openpyxl.Workbook()
    wb.active.title = sheet
    for kind in PAYLOAD["tep"]:
        wb.active.append([REF["osz_parking"][kind]])
    out = io.BytesIO()
    wb.save(out)
    return out.getvalue()


class Response(io.BytesIO):
    status = 200

    def __init__(self, body, content_type="application/json"):
        super().__init__(body)
        self.headers = {"Content-Type": content_type}


@pytest.fixture
def prod(monkeypatch, tmp_path):
    requests = []
    judged = []
    actual_judge = smoke.judge_workbook

    def judge(*args):
        judged.append(args)
        return actual_judge(*args)

    def unavailable_auctions(*args):
        raise ImportError("browser omitted in pure workbook test")

    monkeypatch.setattr(smoke, "judge_workbook", judge)
    monkeypatch.setattr(smoke, "browser_auction_export", unavailable_auctions)
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)

    def run(key=KEY, status=200, book=None, payload=PAYLOAD, browser_error=None):
        content = _book() if book is None else book

        def project(*args):
            if browser_error:
                raise browser_error
            return {"payload": payload, "itog": {"locked": True}}

        def urlopen(request, timeout):
            requests.append(request)
            path = urlsplit(request.full_url).path
            if path == "/health":
                return Response(b'{"version":"fictional","commit":"test"}')
            if path == "/land/lookup":
                return Response(json.dumps({"results": [
                    {"found": True, "cadastral_number": number,
                     "area_ha": REF["land_area_ha"] / len(REF["cadastral_numbers"])}
                    for number in REF["cadastral_numbers"]]}).encode())
            if path == "/report/teaser" or (path == "/report/workbook" and status == 401):
                raise urllib.error.HTTPError(request.full_url, 401, "Unauthorized", {},
                                             io.BytesIO(b'{"detail":"login required"}'))
            assert path == "/report/workbook", path
            return Response(content, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

        monkeypatch.setenv("PROD_SMOKE_ADMIN_KEY", key)
        monkeypatch.setattr(smoke, "browser_project", project)
        monkeypatch.setattr(smoke.urllib.request, "urlopen", urlopen)
        result_path, summary_path = tmp_path / "result.json", tmp_path / "summary.md"
        code = smoke.main(["--base", "https://prod.invalid", "--out", str(tmp_path / "out"),
                           "--json", str(result_path), "--summary", str(summary_path)])
        result = json.loads(result_path.read_text())
        check = next(row for row in result["checks"] if row["name"] == NAME)
        return code, check, result, summary_path.read_text(), content

    return run, requests, judged


@pytest.mark.parametrize("key", [KEY, ""])
def test_workbook_access_is_in_the_json_body_and_success_runs_the_native_judge(prod, tmp_path,
                                                                              capsys, key):
    run, requests, judged = prod
    code, check, result, summary, content = run(key=key)

    assert code == 0
    assert check["status"] == smoke.OK
    request, = [r for r in requests if urlsplit(r.full_url).path == "/report/workbook"]
    assert request.full_url == "https://prod.invalid/report/workbook"
    assert request.method == "POST"
    assert json.loads(request.data) == {**PAYLOAD, "project_name": REF["project"],
                                        "session": "", "access_key": key}
    assert judged == [(content, PAYLOAD["tep"], REF)]
    assert (tmp_path / "out" / "workbook.xlsx").read_bytes() == content
    captured = capsys.readouterr()
    assert KEY not in json.dumps(result) + summary + captured.out + captured.err


@pytest.mark.parametrize("key,reason", [(KEY, "ключ не принят прод-сервером"),
                                       ("", "нужен ключ владельца")])
def test_workbook_401_fails_the_whole_smoke_with_the_actual_reason(prod, key, reason):
    run, requests, judged = prod
    code, check, _result, summary, _content = run(key=key, status=401)

    assert code == 1
    assert check["status"] == smoke.FAIL
    assert check["got"] == "HTTP 401"
    assert reason in check["detail"]
    assert "❌" in summary
    assert not judged
    assert len([r for r in requests if urlsplit(r.full_url).path == "/report/workbook"]) == 1


@pytest.mark.parametrize("error,reason", [(None, "страница не вернула данные проекта"),
                                        (ImportError("fictional missing browser"), "нет playwright"),
                                        (RuntimeError("fictional page failure"), "страница не собрала проект")])
def test_missing_payload_fails_the_book_check_instead_of_skipping_it(prod, error, reason):
    run, requests, judged = prod
    code, check, _result, _summary, _content = run(payload={}, browser_error=error)

    assert code == 1
    assert check["status"] == smoke.FAIL
    assert reason in check["detail"]
    assert not judged
    assert not [r for r in requests if urlsplit(r.full_url).path == "/report/workbook"]


def test_http_200_zip_without_the_inputs_sheet_is_still_rejected_by_the_native_judge(prod):
    run, _requests, judged = prod
    code, check, _result, _summary, content = run(book=_book(sheet="ОТЧЕТ"))

    assert code == 1
    assert check["status"] == smoke.FAIL
    assert "листа «Вводные» нет" in check["detail"]
    assert judged == [(content, PAYLOAD["tep"], REF)]
