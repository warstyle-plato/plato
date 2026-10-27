"""Погашение кредитов на экране: сводка руководству и карточка Монитора.

Проверяется то, что видит человек, — в Chromium по настоящей разметке:

- в сводке раздел «Погашение кредитов» — таблица платежей по договорам НКЛ и
  эскроу (`credit_due`), без выписок банка и их расчёта (владелец, 27.10.2026);
- загрузка данных через Монитор (только команде) пересчитывает прогноз, а
  второй прогноз называет отклонение от первого (ТЗ, п. 8);
- карточка Монитора — настоящий код страницы: зовёт `/monitor/credit` со
  стрессом из полей и показывает ответ.

Запуск: python3 -m pytest tests/test_credit_repayment_on_screen.py -q
"""
from __future__ import annotations

import base64
import json
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

import credit_repayment_fixture as fx  # noqa: E402
import developaid_credit_repayment as credit  # noqa: E402
import developaid_management_report as report  # noqa: E402
import developaid_monitor as monitor  # noqa: E402
import main as _wrapper  # noqa: E402

core = _wrapper.core
client = TestClient(core.app, raise_server_exceptions=False)
PROJECT = "Кутузов Сити"


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(monitor, "_SNAPSHOT_DIR", tmp_path / "monitor")
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123456:credit-test-token")
    monkeypatch.setenv("DEVELOPAID_ADMIN_KEY", "kluch")


def _items(changes=None):
    data = fx.raw()
    data.update(changes or {})
    return [{"name": name, "as_of": fx.AS_OF, "source": "выписка банка",
             "unit": "млн ₽", "data": body} for name, body in data.items()]


def _launch():
    from browser import chromium_or_skip

    chrome = chromium_or_skip()
    from playwright.sync_api import sync_playwright
    return chrome, sync_playwright


def test_the_report_shows_the_contract_schedule_not_the_bank_statements():
    """Владелец, 27.10.2026: «Все данные есть в НКЛ, когда гасить всю сумму
    кредита по этапам. Какие выписки и зачем они нужны?! Все выборки есть в РСС,
    будущие к РНВ = лимиту». Сводка показывает таблицу платежей по договорам НКЛ
    даже когда в Монитор загружены наборы банка — их расчёт в сводку не идёт."""
    credit.save(PROJECT, _items(), "проверка")
    built = report.build(PROJECT, "week", "2026-10-18")
    assert "credit" not in built and built["credit_due"]["state"] == "ok"
    text = report.render_text(built)
    assert "Погашение НКЛ: первый обязательный платёж 30.09.2027 — 3,35 млрд ₽" in text
    assert "Кредиты: статус" not in text
    body = report.render_html(built)
    chrome, sync_playwright = _launch()
    with sync_playwright() as pw:
        browser = pw.chromium.launch(executable_path=str(chrome))
        try:
            tab = browser.new_page(viewport={"width": 1280, "height": 900})
            tab.set_content(f"<html><head><meta charset='utf-8'><style>{report.REPORT_STYLE}"
                            f"</style></head><body>{body}</body></html>")
            block = tab.locator("#block-credit")
            assert block.is_visible() and block.inner_text() == "Погашение кредитов"
            section = tab.locator("div.keep:has(#block-credit)")
            heads = section.locator("table th").all_inner_texts()
            assert heads[:3] == ["Платёж по НКЛ", "НКЛ 2025", "НКЛ 2026"]
            dates = section.locator("table tr td:first-child").all_inner_texts()
            assert dates[0] == "30.09.2027" and dates[-1] == "30.09.2029"
            shown = section.inner_text()
        finally:
            browser.close()
    for word in ("выписк", "данные банка", "не загружены", "Статус: красный", "nkl2025",
                 "facts."):
        assert word not in shown, word


def test_the_monitor_upload_recalculates_and_names_the_change():
    upload = {"project": PROJECT, "key": "kluch", "content_base64": base64.b64encode(
        json.dumps({"datasets": _items()}, ensure_ascii=False).encode()).decode()}
    first = client.post("/monitor/credit/data", json=upload)
    assert first.status_code == 200, first.text
    assert first.json()["status"]["color"] == "red"
    assert "Условия расчёта и их источник" in first.json()["html"]
    # Проверки по договорам — на Мониторе; без бизнес-плана — «нет данных».
    assert "Проверки по кредитным договорам" in first.json()["html"]
    assert "п. 8.2.57" in first.json()["html"]
    moved = fx.raw()["disclosure"]
    moved["items"][0]["date"] = "2027-10-20"
    second = client.post("/monitor/credit/data", json={
        "project": PROJECT, "key": "kluch", "datasets": [
            {"name": "disclosure", "as_of": "2026-10-05", "source": "письмо банка",
             "unit": "млн ₽", "data": moved}]})
    assert second.status_code == 200, second.text
    texts = [c["text"] for c in second.json()["changes"]]
    assert any("перенесено с 20.09.2027 на 20.10.2027" in t for t in texts), texts
    shown = {d["name"]: d for d in second.json()["datasets"]}
    assert shown["disclosure"]["as_of"] == "2026-10-05"
    assert shown["disclosure"]["source"] == "письмо банка"
    bad = client.post("/monitor/credit/data", json={
        "project": PROJECT, "key": "kluch", "datasets": [
            {"name": "escrow", "as_of": "2026-10-05", "source": "банк", "data": {"balance": 1}}]})
    assert bad.status_code == 400 and "единицу" in bad.json()["detail"]
    nothing = client.post("/monitor/credit", json={"project": "Другой", "key": "kluch"})
    assert nothing.json()["state"] == "missing"
    assert "не загружены" in nothing.json()["reason"]


def test_the_monitor_card_runs_the_page_code():
    credit.save(PROJECT, _items(), "проверка")
    answer = client.post("/monitor/credit", json={"project": PROJECT, "key": "kluch"}).json()
    chrome, sync_playwright = _launch()
    seen = []

    def reply(route):
        seen.append(json.loads(route.request.post_data))
        route.fulfill(status=200, body=json.dumps(answer, ensure_ascii=False),
                      content_type="application/json")

    with sync_playwright() as pw:
        browser = pw.chromium.launch(executable_path=str(chrome))
        try:
            tab = browser.new_page(viewport={"width": 1280, "height": 900})
            tab.route("**/monitor/credit", reply)
            tab.route("http://plato.test/monitor", lambda route: route.fulfill(
                status=200, body=core.MONITOR_PAGE_HTML, content_type="text/html"))
            tab.goto("http://plato.test/monitor")
            # Вошедший командой: ключ администратора в хранилище, как после входа.
            tab.evaluate("localStorage.setItem(ADMIN_KEY, 'kluch'); syncAuthUi()")
            tab.fill("#project", PROJECT)
            # Так карточку открывает «Обновить» после расчёта среза.
            tab.evaluate("renderCredit()")
            tab.wait_for_selector("#creditBody table.credit-table")
            tab.fill("#creditCut", "35")
            tab.click("#creditRun")
            tab.wait_for_selector("#creditBody table.credit-table")
            assert tab.locator("#creditCard").is_visible()
            assert tab.locator("#creditState").inner_text() == "статус: красный"
            assert tab.locator("#creditBody table.credit-table th").count() == 9
        finally:
            browser.close()
    assert seen and seen[-1]["project"] == PROJECT
    assert seen[-1]["stress"]["inflow_cut_pct"] == "35"
    assert seen[-1]["key"] == "kluch"
