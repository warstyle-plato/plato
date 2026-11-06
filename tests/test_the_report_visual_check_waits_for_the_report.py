"""The report shell must not pass production smoke when its request failed."""
from __future__ import annotations

import json
import sys
from dataclasses import asdict
from pathlib import Path
from urllib.parse import urlsplit

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "tests"))

import prod_visual as visual

PRIVATE_MARKER = "PRIVATE_REPORT_FIXTURE_DETAIL_6f29"


@pytest.fixture
def report_browser(monkeypatch):
    from playwright.sync_api import sync_playwright
    from browser import chromium_or_skip

    monkeypatch.setenv("PROD_SMOKE_ROUTE_VIA_PYTHON", "0")
    with sync_playwright() as pw, pw.chromium.launch(
            executable_path=str(chromium_or_skip())) as browser:
        yield browser


def fixture_browser(browser, outcome):
    """Serve the actual report page and its JS; no live credentials or data."""
    from developaid_report_page import REPORT_PAGE
    import developaid_management_report as report

    html = report.render_html({"project": "Visual fixture", "kind": "week",
                               "start": "2026-11-01", "end": "2026-11-06",
                               "findings": []})

    def reply(route):
        path = urlsplit(route.request.url).path
        if path == "/report":
            return route.fulfill(status=200, content_type="text/html", body=REPORT_PAGE)
        data = {}
        if path == "/monitor/report/projects":
            if outcome == "login-error":
                return route.fulfill(status=403, content_type="application/json",
                                     body=json.dumps({"detail": PRIVATE_MARKER}))
            data = {"projects": [{"project": "Visual fixture"}], "sales_projects": []}
        elif path == "/monitor/report/build":
            if outcome == "connection":
                return route.abort("failed")
            if outcome == "http-error":
                return route.fulfill(status=500, content_type="application/json",
                                     body=json.dumps({"detail": PRIVATE_MARKER}))
            data = {"pending": True, "ticket": "0" * 32}
        elif path == "/monitor/report/result":
            data = {"pending": False, "html": html} if outcome == "success" else {"html": ""}
        return route.fulfill(status=200, content_type="application/json", body=json.dumps(data))

    class RoutedBrowser:
        def new_context(self, **kwargs):
            context = browser.new_context(**kwargs)
            context.route("**/*", reply)
            return context

    return RoutedBrowser()


@pytest.mark.parametrize("outcome", ["connection", "http-error", "login-error"])
def test_a_report_request_failure_is_a_break(report_browser, tmp_path, outcome):
    found = visual.check_team_report(fixture_browser(report_browser, outcome),
                                     "https://report-fixture.test", "fixture-key", tmp_path)
    failures = [f for f in found if f.severity == visual.BREAK]
    assert len(failures) == 2, "Both desktop and phone must reject the failed report"
    assert all(f.kind == "сводка не открылась" for f in failures)
    assert all(f.where == ("#loginMsg" if outcome == "login-error" else "#reportMsg")
               for f in failures)
    # Findings are emitted as JSON, step summary and public PR/issue prose.
    # An arbitrary server detail stays on the user's page, not in these outputs.
    for finding in found:
        finding.new = True
    published = json.dumps([asdict(f) for f in found], ensure_ascii=False)
    published += visual.summary_markdown(found, [], "https://report-fixture.test", {}, "fixture")
    published += visual.author_note(found, "https://report-fixture.test", {})
    assert PRIVATE_MARKER not in published


def test_a_rendered_report_passes(report_browser, tmp_path):
    found = visual.check_team_report(fixture_browser(report_browser, "success"),
                                     "https://report-fixture.test", "fixture-key", tmp_path)
    assert not [f for f in found if f.severity == visual.BREAK]


def test_an_empty_success_response_does_not_pass_as_a_report(report_browser, tmp_path):
    found = visual.check_team_report(fixture_browser(report_browser, "empty"),
                                     "https://report-fixture.test", "fixture-key", tmp_path,
                                     wait_timeout_ms=5_000)
    failures = [f for f in found if f.severity == visual.BREAK]
    assert len(failures) == 2
    assert all(f.where == "#reportMsg" for f in failures)
