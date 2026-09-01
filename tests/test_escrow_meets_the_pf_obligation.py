"""Эскроу против обязательства по ПФ — на всех поверхностях одним счётом.

График «Долг и эскроу» сравнивал счёт с ТЕЛОМ долга. Банку в дату раскрытия
причитается и начисленное: проценты и комиссии копятся вне лимита и платятся
кассой проекта. Пока их не видно, «эскроу выше долга» читается как
«рассчитались» — а сверх эскроу проект платит деньгами. И свод по проекту не
отвечает, какой очереди не хватило: дата раскрытия у каждой своя.

Запуск: python3 -m pytest tests -q
"""

from __future__ import annotations

import io
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import main as wrapper  # noqa: E402

core = wrapper.core


def _single() -> dict:
    inputs = dict(core.DEFAULT_INPUTS)
    tep = {key: dict(value) for key, value in core.TEP_DEFAULT.items()}
    return core._run_authoritative_model(inputs, tep, [], {})


def test_the_month_says_what_the_bank_is_owed():
    bundle = _single()
    rows = bundle["consolidated"]["finance"]["rows"]
    assert rows, "расчёт не дал помесячных строк"
    for row in rows:
        assert "pf_payable" in row and "pf_obligation" in row
        assert row["pf_obligation"] == pytest.approx(
            row["pf_balance"] + row["pf_payable"], rel=1e-9, abs=1.0)
    # Проверка, которая не доходит до начисленного, не проверяет ничего.
    assert any(row["pf_payable"] > 0 for row in rows), \
        "на этих вводных проценты не копятся — проверка ничего не значит"
    assert any(row["pf_obligation"] > row["pf_balance"] for row in rows), \
        "обязательство нигде не больше тела — сравнивать нечего"


def test_the_answer_names_the_gap_and_the_interest():
    bundle = _single()
    cover = bundle["consolidated"]["report"]["financing"]["escrow_cover"]
    assert cover, "перекрытие эскроу не доехало до отчёта"
    assert cover["lines"], "числа есть, а ответа словами нет"
    text = " ".join(cover["lines"])
    assert "раскрыти" in text.lower()
    body = cover["pf_body_repaid"] + cover["pf_body_unpaid"]
    assert cover["pf_body"] == pytest.approx(body, abs=1.0)
    assert cover["obligation"] == pytest.approx(
        cover["pf_body"] + cover["interest_due"], abs=1.0)
    if cover["pf_body_unpaid"] > 0:
        assert not cover["covered"] and "не хватает" in text
    else:
        assert cover["covered"] and "закрывает" in text


def test_the_summary_does_not_answer_for_a_phase():
    """У каждой очереди своя дата раскрытия — свод её не называет."""
    inputs = dict(core.DEFAULT_INPUTS)
    tep = {key: dict(value) for key, value in core.TEP_DEFAULT.items()}
    phasing = {"enabled": True, "phase_count": 2, "phase_gap_months": 12}
    bundle = core._run_authoritative_model(inputs, tep, [], phasing)
    financing = bundle["consolidated"]["report"]["financing"]
    phases = financing.get("escrow_cover_phases") or []
    assert len(phases) == 2, "перекрытие по очередям до отчёта не доехало"
    for cover in phases:
        assert cover["label"], "очередь без имени — какой из них не хватило, неясно"
        assert cover["lines"], "очередь молчит о своём раскрытии"
    assert len({cover.get("rve") for cover in phases}) == 2, \
        "у очередей совпали даты раскрытия — свод и очередь неразличимы"
    # У каждой очереди свои строки, и они разные: одинаковые значили бы, что
    # мы показываем свод дважды.
    for item in bundle["phases"]:
        rows = item["result"]["finance"]["rows"]
        assert any(row["pf_obligation"] > 0 for row in rows)


def test_the_page_draws_the_obligation_and_not_only_the_body():
    page = core.PAGE
    assert "function escrowCoverSvg(" in page
    assert "Эскроу против обязательств по ПФ" in page
    assert "escrowCoverNote" in page
    assert "renderPhaseEscrowCharts()" in page, \
        "график по очередям не зовётся — методика, до которой не дойти"
    assert "x.pf_payable" in page, "помесячная таблица молчит о начисленном"
    # Рисовальщик один на проект и на очереди: два разошлись бы молча.
    assert page.count("function escrowCoverSvg(") == 1
    # Заливка, а не линии: ответ на «перекрывает или нет» — это площадь.
    assert "<polygon" in page.split("function escrowCoverSvg(")[1][:4000]
    # Линия «сколько банк получил всего»: раскрытый эскроу и то, чем гасят
    # дальше. Продажи после раскрытия рисовались от нуля и рядом с эскроу в
    # десятки миллиардов не значили ничего (владелец, 01.09.2026).
    assert "escrow_and_sales_cumulative" in page, "погашенное банку не нарисовано"
    assert "Раскрытый эскроу и продажи после него" in page, "линия не названа"
    assert "не погашено" in page, "последняя точка не названа — читается как обрыв"


def test_the_report_shows_the_chart_the_pdf_prints():
    """График жил на вкладке «Финансирование», а печатается отчёт.

    «В PDF есть, на сайте нет» (владелец, 31.08.2026) — потому что в разделе
    «Результат» его не было вовсе.
    """
    page = core.PAGE
    assert 'id="reportEscrowChart"' in page
    assert 'id="reportEscrowNote"' in page
    body = page.split("function renderFinanceChart(")[1][:900]
    assert "reportEscrowChart" in body, "отчёт не получает тот же график"
    assert "reportEscrowNote" in body


def test_the_page_script_still_parses():
    page = core.PAGE
    body = "\n".join(
        part.split("</script>")[0] for part in page.split("<script>")[1:])
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "page.js"
        path.write_text(body, encoding="utf-8")
        done = subprocess.run(["node", "--check", str(path)],
                              capture_output=True, text=True)
    assert done.returncode == 0, done.stderr


def test_the_pdf_prints_the_escrow_cover():
    pypdf = pytest.importorskip("pypdf")
    inputs = dict(core.DEFAULT_INPUTS)
    tep = {key: dict(value) for key, value in core.TEP_DEFAULT.items()}
    phasing = {"enabled": True, "phase_count": 2, "phase_gap_months": 12}
    bundle = core._run_authoritative_model(inputs, tep, [], phasing)
    payload = {"result": bundle["consolidated"], "inputs": inputs, "tep": tep,
               "rates": [], "phasing": bundle.get("phasing") or phasing,
               "phases": bundle.get("phases") or [],
               "scenario": "base", "project_name": "Эскроу"}
    text = "\n".join(page.extract_text() or "" for page in pypdf.PdfReader(
        io.BytesIO(core._build_developaid_pdf(payload))).pages)
    flat = " ".join(text.split())
    assert "Эскроу против обязательств по ПФ" in flat
    assert "Обязательство: тело + начисленное" in flat
    for cover in bundle["consolidated"]["report"]["financing"]["escrow_cover_phases"]:
        assert cover["label"] in flat, "очередь не названа в отчёте"


def test_the_dashed_line_starts_where_escrow_ends_and_never_goes_back():
    """Накопленное на своде считается по потоку, а не складыванием итогов.

    Сложить два накопленных ряда нельзя: горизонты очередей разной длины, и в
    месяце, где строки одной кончились, сумма падает — «погашено банку»
    уезжало с 41,8 до 19,7 млрд ₽ на ровном месте.
    """
    inputs = dict(core.DEFAULT_INPUTS)
    tep = {key: dict(value) for key, value in core.TEP_DEFAULT.items()}
    bundle = core._run_authoritative_model(
        inputs, tep, [], {"enabled": True, "phase_count": 2, "phase_gap_months": 12})
    rows = bundle["consolidated"]["finance"]["rows"]
    assert any(row["escrow_and_sales_cumulative"] > 0 for row in rows), \
        "линия пуста — проверка ничего не значит"
    for before, after in zip(rows, rows[1:]):
        assert after["escrow_and_sales_cumulative"] >= before["escrow_and_sales_cumulative"] - 1.0, (
            f"накопленное упало в {after['month']}: "
            f"{before['escrow_and_sales_cumulative']:.0f} → {after['escrow_and_sales_cumulative']:.0f}")
    # И линия начинается там, где раскрылся эскроу, а не с нуля после него.
    release = max(row["escrow_release"] for row in rows)
    jump = max(after["escrow_and_sales_cumulative"] - before["escrow_and_sales_cumulative"]
               for before, after in zip(rows, rows[1:]))
    assert jump >= release * 0.9, \
        "линия не подхватывает раскрытый эскроу — она снова идёт от нуля"
