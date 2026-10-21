"""Сводка руководству видна на странице мониторинга и скачивается PDF.

«А где же экспорт PDF?» (владелец, 20.10.2026). Сводка собиралась моделью и
текстом для бота, а документа не было. Теперь карточка «Сводка руководству»
показывает ту же разметку, что уходит в PDF, и кнопка скачивает PDF, который
печатает сервер. Числа в PDF те же, что в сообщении: считает одна модель.

Проверяется отрисованная страница и настоящий PDF.

Запуск: python3 -m pytest tests/test_the_management_report_prints.py -q
"""
from __future__ import annotations

import io
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

import developaid_monitor as monitor  # noqa: E402
import developaid_monthly_budget as monthly_budget  # noqa: E402
from browser import chromium_or_skip, serve  # noqa: E402
from test_management_report_model import PROJECT, _project, budget_book  # noqa: E402

PORT = 18801


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(monitor, "_SNAPSHOT_DIR", tmp_path / "monitor")
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))


def test_the_report_card_and_its_pdf(tmp_path, monkeypatch):
    chrome = chromium_or_skip()
    from playwright.sync_api import sync_playwright

    import main_legacy as core

    _project()
    monthly_budget.store_budget(PROJECT, budget_book(), "2026-10-02")
    monkeypatch.setattr(core, "_require_web_access", lambda *_a, **_k: None)
    with serve(core.app, PORT) as base, sync_playwright() as pw:
        browser = pw.chromium.launch(executable_path=str(chrome))
        try:
            tab = browser.new_page(accept_downloads=True)
            errors: list[str] = []
            tab.on("pageerror", lambda e: errors.append(str(e)))
            tab.add_init_script("localStorage.setItem('developaid_web_session','проба')")
            # Сводка — своя страница рядом с Монитором (владелец, 20.10.2026).
            tab.goto(f"{base}/report", wait_until="domcontentloaded")
            tab.wait_for_selector(f"#project option[value='{PROJECT}']", state="attached")
            tab.select_option("#project", PROJECT)
            tab.fill("#cut", "2026-10-18")
            tab.click("#reportBtn")
            tab.wait_for_function(
                "document.getElementById('reportBox').textContent.includes('12.10 — 18.10.2026')")
            week = tab.inner_text("#reportBox")
            tab.select_option("#reportKind", "month")
            tab.wait_for_function(
                "document.getElementById('reportBox').textContent.includes('за октябрь 2026')")
            month = tab.inner_text("#reportBox")
            with tab.expect_download(timeout=90_000) as download:
                tab.click("#reportPdfBtn")
            path = download.value.path()
            name = download.value.suggested_filename
            pdf = Path(path).read_bytes()
            done = tab.inner_text("#reportMsg")
        finally:
            browser.close()

    assert not errors, errors
    assert "за неделю 12.10 — 18.10.2026" in week
    assert "Стройка и проектирование" in month and "400,0 млн ₽" in month
    assert name.endswith(".pdf")
    assert pdf.startswith(b"%PDF"), pdf[:20]
    assert done == "PDF скачан."
    try:
        from pypdf import PdfReader
    except ImportError:
        return
    text = " ".join(" ".join((page.extract_text() or "").split())
                    for page in PdfReader(io.BytesIO(pdf)).pages)
    assert "Сводка по проекту" in text and "Бюджет месяца" in text
    # Блок финансирования: выборка кредита — те же числа, что на странице.
    assert "Финансирование" in text and "Выборка кредита" in text
    # Первая страница — «Главное», графики напечатаны (их подписи — текст SVG).
    first = PdfReader(io.BytesIO(pdf)).pages[0].extract_text() or ""
    assert "Главное за период" in first
    # Плитки с главными числами — на первой странице, над «Главным».
    first = " ".join(first.split())
    assert first.index("БЮДЖЕТ СТРОЙКИ ЗА МЕСЯЦ") < first.index("Главное за период")
    # Бюджет по статьям напечатан с итогом стройки и коммерции.
    assert "Итого стройка и коммерческие расходы" in text
    # Подпись и столбцы графика бюджета напечатаны текстом SVG: те же 400,0 и
    # 150,0 млн ₽, что в таблице (pypdf теряет двоеточие, поэтому без него).
    chart = text[text.index("Бюджет на октябрь 2026"):]
    assert "план и оплачено по статьям" in chart[:80]
    assert "400,0 150,0 Стройка и проектирование" in chart
    assert "Финансирование" in month
    assert "400,0" in text, "в PDF не те числа, что на странице"


def test_the_monitor_does_not_carry_the_summary():
    """Сводка и записи — не в Мониторе стройки, а на своей странице с входом в контуре."""
    import management_contour
    from developaid_monitor_page import MONITOR_PAGE

    assert 'id="reportCard"' not in MONITOR_PAGE and 'id="notesCard"' not in MONITOR_PAGE
    builder = next(role for role in management_contour.ROLES if role["role"] == "Строителю")
    assert [link["href"] for link in builder["links"]] == ["/monitor", "/report"]
