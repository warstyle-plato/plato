"""Погашение кредитов на экране: сводка руководству и карточка Монитора.

Проверяется то, что видит человек, — в Chromium по настоящей разметке:

- в сводке раздел «Погашение кредитов» сверху — вывод и одна таблица по датам
  платежей НКЛ с процентами против эскроу (владелец, 27.10.2026) из того же
  прогноза; подробный расчёт свёрнут за «Как посчитано» и раскрывается: статус,
  верхний блок и основная таблица в порядке столбцов ТЗ (п. 7), строка
  раскрывается до двух НКЛ, число — до формулы;
- в сводке нет технических пояснений (имён наборов, пунктов ТЗ, условий
  расчёта) — они на странице Монитора;
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


def test_the_report_shows_the_credit_block_as_the_tz_asks():
    credit.save(PROJECT, _items(), "проверка")
    built = report.build(PROJECT, "week", "2026-10-18")
    assert built["credit"]["state"] == "ok" and built["credit_due"]["state"] == "ok"
    # В сообщении — первая дата и итог простой таблицы, а не статус подробного расчёта.
    told = report.render_text(built)
    assert "Погашение кредитов: " + report.credit_main(built["credit_due"]) in told
    assert "Кредиты: статус" not in told
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
            simple = section.locator("table.credit-due")
            assert simple.locator("th").all_inner_texts()[:4] == [
                "Дата", "Основной долг", "Проценты (темп)", "Проценты (план ФМ)"]
            # Подробный расчёт свёрнут, пока его не открыли.
            more = section.locator("details.credit-more")
            assert not more.locator("table.credit-table").is_visible()
            more.locator("summary").first.click()
            assert more.locator("table.credit-table").is_visible()
            heads = tab.locator("table.credit-table th").all_inner_texts()
            assert heads == ["Дата", "Основной долг к погашению", "Проценты и комиссии",
                             "Всего к оплате", "Эскроу до раскрытия", "Доступно из раскрытия",
                             "Другие источники", "Дефицит", "Долг после платежа"]
            dates = tab.locator("table.credit-table tr.date td:first-child").all_inner_texts()
            # Первый платёж — раскрытие эскроу 20.09.2027: долг к погашению в его размере
            # (договор А, п. 6.1.2); до него проценты и плата за лимит в отсрочке.
            assert dates[0] == "20.09.2027 (раскрытие эскроу: долг к погашению)"
            assert dates[1] == "30.09.2027 (раскрытие позже)"
            loans = tab.locator("table.credit-table tr.loan td:first-child").all_inner_texts()
            # Раскрытие гасит сначала НКЛ 2025 — в первой строке только она.
            assert loans[0] == "в т. ч. НКЛ 2025"
            assert set(loans) == {"в т. ч. НКЛ 2025", "в т. ч. НКЛ 2026"}
            labels = tab.locator("table.credit-top td:first-child").all_inner_texts()
            assert labels[:3] == ["Текущий совокупный долг", "Текущий остаток эскроу",
                                  "Ближайший платёж 20.09.2027: всего обязательств"]
            assert "Непокрытый дефицит" in labels and any(
                label.startswith("Максимальный дефицит за прогноз") for label in labels)
            debt = tab.locator("table.credit-top tr").nth(1)
            assert debt.locator("td").nth(1).inner_text() == "3 200,000"
            formula = debt.locator("details.how div").first
            assert not formula.is_visible()
            debt.locator("summary").click()
            assert formula.is_visible()
            assert "долг НКЛ 2025 3 000,000 + долг НКЛ 2026 200,000" in formula.inner_text()
            status = tab.locator("details.credit-more div.credit p.credit-status").first
            assert status.inner_text().startswith("Статус: красный")
            text = tab.locator("div.credit").first.inner_text()
            assumptions = tab.locator("div.credit-assumptions").first
            assert assumptions.is_visible()
            assert "Ставка по НКЛ 2026 посчитана по аналогии с НКЛ 2025" in assumptions.inner_text()
        finally:
            browser.close()
    # Без технических пояснений: условия расчёта и пункты ТЗ — на Мониторе.
    for word in ("nkl2025", "ТЗ владельца", "Условия расчёта", "facts."):
        assert word not in text, word


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
    assert shown["disclosure"]["source"] == "поправка вручную: письмо банка"
    bad = client.post("/monitor/credit/data", json={
        "project": PROJECT, "key": "kluch", "datasets": [
            {"name": "escrow", "as_of": "2026-10-05", "source": "банк", "data": {"balance": 1}}]})
    assert bad.status_code == 400 and "единицу" in bad.json()["detail"]
    nothing = client.post("/monitor/credit", json={"project": "Другой", "key": "kluch"})
    assert nothing.json()["state"] == "missing"
    assert "в системе не заведены" in nothing.json()["reason"]


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
