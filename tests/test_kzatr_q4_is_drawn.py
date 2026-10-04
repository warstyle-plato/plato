"""Кзатр четвёртого квартала 2026 — на странице МПТ, а не только в справочнике.

С 01.10.2026 идёт 2026-Q4. Приказ ДИиПП от 10.03.2026 велит брать обобщённый
индекс стоимости строительства к декабрю 2025 года за последний месяц
предыдущего квартала — СЕНТЯБРЬ 2026. Его утвердило распоряжение ДЭПР Москвы
от 28.09.2026 № ДПР-Р-25/26 (строка «Строительство»: 1,0394; август рядом —
1,0395). Кзатр Q4 = 166,23078 × 1,0394 = 172,78027 тыс ₽/м².

Человек видит это число в панели МПТ — туда же ведёт кнопка бота
(`?section=mpt`). Поэтому проверяется отрисованная страница в Chromium:
поле Кзатр, поле квартала, подпись источника и формула расчёта после «Рассчитать».
Ожидаемое число записано здесь из документа, а не взято из модуля, — иначе
проверка повторяла бы код. И она обязана падать на подделке: страница с
индексом за август вместо сентября (172,7969) проверку не проходит.

Запуск: python3 -m pytest tests/test_kzatr_q4_is_drawn.py -q
"""

from __future__ import annotations

import socket
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

import browser  # noqa: E402
import main_registry  # noqa: E402
import mpt_calculator  # noqa: E402

Q4_KZATR = "172.78027"  # 166,23078 × 1,0394 (сентябрь 2026, ДПР-Р-25/26)


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _drawn(monkeypatch, indices: dict[str, float]) -> dict[str, str]:
    """Что показывает панель МПТ по ссылке из бота на 2026-Q4."""
    pytest.importorskip("playwright.sync_api")
    from playwright.sync_api import sync_playwright

    # Квартал «сегодня» закреплён: проверка не должна краснеть в 2027 году.
    monkeypatch.setattr(mpt_calculator, "quarter_of", lambda day: "2026-Q4")
    monkeypatch.setattr(mpt_calculator, "KZATR_INDICES_TO_DEC2025", indices)
    chrome = browser.chromium_or_skip()
    errors: list[str] = []
    with browser.serve(main_registry.app, _free_port()) as base, sync_playwright() as pw:
        with pw.chromium.launch(executable_path=str(chrome)) as engine:
            page = engine.new_page(viewport={"width": 1280, "height": 900})
            page.on("pageerror", lambda exc: errors.append(str(exc)))
            page.goto(base + "/?section=mpt", wait_until="domcontentloaded")
            page.wait_for_function(
                "() => (document.getElementById('mpt-kzatr-note')||{}).textContent", timeout=20000)
            shown = page.evaluate("""() => ({
                kzatr: document.getElementById('mpt-kzatr').value,
                quarter: document.getElementById('mpt-kzatr-quarter').value,
                note: document.getElementById('mpt-kzatr-note').textContent,
            })""")
            page.evaluate("""() => {
                const d = document.getElementById('mpt-district');
                d.value = d.options[1].value;
                d.dispatchEvent(new Event('change'));
                const t = document.getElementById('mpt-ttk');
                t.value = 'outside';
                t.dispatchEvent(new Event('change'));
                document.getElementById('mpt-area').value = '10000';
            }""")
            page.click("#mpt-calc")
            page.wait_for_function(
                "() => (document.getElementById('mpt-formula')||{}).textContent", timeout=20000)
            shown["formula"] = page.evaluate(
                "() => document.getElementById('mpt-formula').textContent")
            shown["warnings"] = page.evaluate(
                "() => document.getElementById('mpt-warnings').textContent")
            page.close()
    shown["errors"] = "; ".join(errors)
    return shown


def _assert_q4(shown: dict[str, str]) -> None:
    assert not shown["errors"], shown["errors"]
    assert shown["kzatr"] == Q4_KZATR, shown
    assert shown["quarter"] == "2026-Q4", shown
    assert "ДПР-Р-25/26 от 28.09.2026" in shown["note"], shown["note"]
    assert "1.0394" in shown["note"], shown["note"]
    assert Q4_KZATR in shown["formula"], shown["formula"]
    assert "сверьте" not in shown["warnings"] and "сейчас 2026-Q4" not in shown["warnings"], (
        shown["warnings"])


def test_the_page_draws_the_fourth_quarter_kzatr(monkeypatch):
    _assert_q4(_drawn(monkeypatch, dict(mpt_calculator.KZATR_INDICES_TO_DEC2025)))


def test_the_august_index_is_caught(monkeypatch):
    """Подделка: Q4 по индексу АВГУСТА (1,0395) — число правдоподобное, но не то."""
    forged = dict(mpt_calculator.KZATR_INDICES_TO_DEC2025, **{"2026-Q4": 1.0395})
    # Падать обязана именно сверка числа, а не что-то постороннее на странице.
    with pytest.raises(AssertionError, match=r"'kzatr': '172\.7969'"):
        _assert_q4(_drawn(monkeypatch, forged))


def test_a_missing_quarter_is_caught(monkeypatch):
    """Подделка: Q4 не принесён — страница показывает базу, проверка обязана упасть."""
    forged = {k: v for k, v in mpt_calculator.KZATR_INDICES_TO_DEC2025.items() if k != "2026-Q4"}
    with pytest.raises(AssertionError, match=r"'kzatr': '166\.23078'"):
        _assert_q4(_drawn(monkeypatch, forged))
