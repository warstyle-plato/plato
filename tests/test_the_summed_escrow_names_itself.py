"""Сводный график эскроу — сумма разных договоров, и он это говорит.

Владелец, 04.09.2026: «кажется, что 2 очередь стартует сразу с выборки и
эскроу не с 0, а с 10 млрд, а 3 с 30». Числа верны: свод складывает счета
эскроу и долги ВСЕХ очередей, и после раскрытия первой кривая продолжается с
остатка остальных. Неверно место — покрытие такой кривой не принадлежит ни
одному договору, а ступень ставки ПФ банк считает по очереди.

Запуск: python3 -m pytest tests/test_the_summed_escrow_names_itself.py -q
"""

from __future__ import annotations

import inspect
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import main_legacy as core  # noqa: E402

PAGE = core.PAGE


def _function(name: str) -> str:
    start = PAGE.index(f"function {name}(")
    depth, index, seen = 0, PAGE.index("{", start), False
    while index < len(PAGE):
        if PAGE[index] == "{":
            depth, seen = depth + 1, True
        elif PAGE[index] == "}":
            depth -= 1
            if seen and depth == 0:
                return PAGE[start:index + 1]
        index += 1
    raise AssertionError(f"не нашёл конец функции {name}")


def _phased():
    inputs = dict(core.DEFAULT_INPUTS)
    inputs["apartment_price_th"] = 450.0
    tep = {key: dict(value) for key, value in core.TEP_DEFAULT.items()}
    return core._run_authoritative_model(inputs, tep, [], {"enabled": True, "phase_count": 4})


def test_the_summed_coverage_belongs_to_no_contract() -> None:
    """Мера, ради которой стоит оговорка: свод не равен ни одной очереди."""
    bundle = _phased()
    rows = bundle["consolidated"]["finance"]["rows"]
    phases = [p["result"]["finance"]["rows"] for p in bundle["phases"]]

    def f(row, key):
        return float(row.get(key, 0.0) or 0.0)

    disagreements = 0
    for row in rows:
        duty = f(row, "pf_balance") + f(row, "pf_payable")
        if duty < 1_000_000:
            continue
        summed = f(row, "escrow") / duty
        own = [f(q, "coverage") for rows_q in phases
               for q in rows_q if q["month"] == row["month"]]
        own = [value for value in own if value > 0]
        if own and all(abs(summed - value) > 0.05 for value in own):
            disagreements += 1
    assert disagreements > 12, (
        "свод совпал с очередями — на этих вводных оговорка ничего не защищает")


def test_the_consolidated_chart_says_it_is_a_sum() -> None:
    """Кривая без этой строки читается как покрытие проекта."""
    body = _function("renderFinanceChart")
    assert "Это СУММА очередей" in body
    assert "не совпадает ни с одним договором" in body
    assert "phaseBundle.mode==='phased'" in body, (
        "оговорка обязана появляться только у проекта с очередями")


def test_the_queue_lines_stand_under_the_summed_one() -> None:
    """Методика, до которой надо дойти на соседнюю вкладку, — методика, которой нет."""
    assert 'id="financeEscrowPhases"' in PAGE
    assert 'id="reportEscrowPhases"' in PAGE
    body = _function("renderPhaseEscrowCharts")
    for name in ("financeEscrowPhases", "reportEscrowPhases"):
        assert name in body, f"контейнер {name} не заполняется"
    assert "renderPhaseEscrowCharts();" in _function("renderFinanceChart"), (
        "линии очередей рисуются только при открытии сравнения очередей")


def test_the_pdf_draws_each_queue_once() -> None:
    """Отчёт носят в банк, и расходиться с экраном ему нельзя."""
    source = inspect.getsource(core)
    start = source.index("for cover in (financing.get(\"escrow_cover_phases\")")
    assert source.count("financing.get(\"escrow_cover_phases\")") == 1, (
        "второй обход очередей в PDF — это второй набор графиков")
    assert "escrow_cover_block(phase_rows.get(name)" in source[start:start + 400]


# --- живая страница ---------------------------------------------------------
# «Зачем графики эскроу и долга дважды по очередям теперь в финансировании и
# очередности» (владелец, 05.09.2026). Дубль жил в РАЗМЕТКЕ, а не в числах:
# один и тот же набор рисовался в три контейнера, два из которых лежат внутри
# панели отчёта. Строковый тест такого не ловит — контейнеры существуют оба, и
# каждый по отдельности заполняется верно. Считать надо картинки на экране.

PORT = 18251

COUNT = """() => {
  const seen = box => box
    ? box.querySelectorAll('.phase-escrow').length : -1;
  return {
    finance: seen(document.getElementById('finance')),
    report: seen(document.getElementById('report')),
    total: document.querySelectorAll('.phase-escrow').length,
    // Свод обязан остаться на месте: убирали дубль, а не график.
    summed: !!document.querySelector('#financeChart svg'),
    caveat: (document.getElementById('escrowCoverNote') || {}).textContent || '',
  };
}"""


def test_in_a_real_browser_each_queue_is_drawn_once_per_surface() -> None:
    try:
        from playwright.sync_api import sync_playwright
    except Exception:  # pragma: no cover — образ без playwright
        pytest.skip("playwright недоступен")
    chrome = Path("/opt/pw-browsers/chromium-1194/chrome-linux/chrome")
    if not chrome.exists():  # pragma: no cover
        pytest.skip("chromium в образе не найден")
    import json
    import threading
    import time

    import uvicorn

    import main as wrapper

    bundle = _phased()
    queues = len(bundle["phases"])
    assert queues == 4, "проверка держится на проекте с очередями"

    server = uvicorn.Server(uvicorn.Config(wrapper.app, host="127.0.0.1", port=PORT,
                                           log_level="error"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    for _ in range(200):
        if server.started:
            break
        time.sleep(0.05)
    assert server.started
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(executable_path=str(chrome))
            page = browser.new_page()
            errors: list[str] = []
            page.on("pageerror", lambda exc: errors.append(str(exc)))
            page.on("dialog", lambda dialog: dialog.accept())
            page.goto(f"http://127.0.0.1:{PORT}/", wait_until="networkidle")
            # Числа считает движок; страница их только рисует — иначе проверка
            # мерила бы вторую реализацию расчёта.
            count = page.evaluate(
                "(data) => { phaseBundle=data; lastResult=data.consolidated;"
                " const fin=lastResult.finance||{};"
                " renderFinanceChart(fin.rows||[],"
                "  ((lastResult.report||{}).financing||{}).escrow_cover||{});"
                " return (" + COUNT + ")(); }",
                json.loads(json.dumps(bundle, default=float)))
            browser.close()
    finally:
        server.should_exit = True
        thread.join(timeout=10)

    assert not errors, errors
    assert count["summed"], "сводный график пропал вместе с дублем"
    assert count["finance"] == queues, count
    # Здесь и была жалоба: в отчёте набор стоял дважды — под сводным графиком и
    # в разделе «Очереди проекта».
    assert count["report"] == queues, count
    assert count["total"] == queues * 2, count
    assert "Линии очередей — ниже" in count["caveat"], (
        "оговорка обещает линии ниже — значит они обязаны быть под сводным")
