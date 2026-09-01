"""Свод, у которого заполнен КАЖДЫЙ раздел, рисуется целиком.

Прежние проверки экрана продаж шли на своде, где прочитана одна контрактация:
планов нет, эскроу нет, квартирографии нет. Ветки, которые включаются вместе с
источником, при этом не исполнялись ни разу — и `salesPlansBlock` ссылался на
`rows` из чужой области видимости, оставшийся там после того, как сборка строк
уехала в `salesPlansChart`. На проекте с восемью источниками это
`ReferenceError`, `renderSales` обрывается на первом же разделе с планами, и в
`#sales` не остаётся НИЧЕГО: плитки сводки нарисованы, отчёта нет вовсе —
«а куда вообще отчёт делся о продажах? там нет ничего на вкладке» (владелец,
31.08.2026).

Отсюда форма проверки: не строка в исходнике, а настоящий Chromium на настоящей
странице, и падение страницы — это провал теста. Строкой такое не ловится: имя
`rows` в файле есть, и выглядит оно правильным.

Запуск: python3 -m pytest tests/test_the_sales_report_survives_a_full_project.py -q
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

from market_search.cabinet import cabinet_page  # noqa: E402


def _quarter(label: str, months: int, k: float) -> dict:
    return {
        "label": label, "months": months, "partial": months < 3,
        "fact_amount": 900e6 * k, "fact_area": 4_100 * k, "fact_units": 46 * k,
        "fm_amount": 1_100e6 * k, "fm_area": 4_800 * k, "fm_units": 52 * k,
        "bank_amount": 1_620e6 * k, "bank_area": 5_300 * k, "bank_units": 58 * k,
        "fact_price": 219_000, "fm_price": 229_000, "bank_price": 305_000,
    }


def full_summary() -> dict:
    """Свод, в котором заполнено всё, что вообще бывает заполнено."""
    import importlib

    from market_search import contracting

    got = importlib.import_module("test_contracting_summary")._summary()
    got["project"] = "Полный проект"
    got["sources"] = [
        {"kind": "contracting", "name": "контрактация ЦФ", "at": "2026-08-31T09:00:00"},
        {"kind": "plan_bank", "name": "план банка", "at": "2026-08-31T09:00:00"},
        {"kind": "plan_fm", "name": "план нашей финмодели", "at": "2026-08-27T09:00:00"},
        {"kind": "mix", "name": "квартирография книги", "at": "2026-08-27T09:00:00"},
        {"kind": "crm", "name": "сделки CRM", "at": "2026-08-27T09:00:00"},
    ]
    got["plans"] = {
        "fm_sheet": "план продаж", "bank_sheet": "КРЕДИТЫ",
        "quarters": [_quarter("2026 Q1", 3, 1.0), _quarter("2026 Q2", 3, 1.1),
                     _quarter("2026 Q3", 2, 0.6)],
    }
    got["escrow"] = {
        "queues": [{"queue": "Очередь 1", "opened_at": "2026-12", "escrow": 7_942e6,
                    "debt": 8_343e6, "coverage": 0.95, "pace": 130e6,
                    "pace_months": 3, "plan_pace": 494e6, "at_open": 3_023e6,
                    "at_open_coverage": 0.36}],
        "missing": ["лист «КРЕДИТЫ» прочитан частично"],
    }
    got["pool"] = contracting.pool_progress(got, [], None, None)
    got["pool"]["bands"] = [
        {"band": "28,3–40 м²", "pool_share": 0.232, "sold_share": 0.464, "left_share": 0.152},
        {"band": "40–55 м²", "pool_share": 0.286, "sold_share": 0.273, "left_share": 0.319},
        {"band": "55–85 м²", "pool_share": 0.282, "sold_share": 0.143, "left_share": 0.329},
        {"band": "85–168,6 м²", "pool_share": 0.200, "sold_share": 0.120, "left_share": 0.200},
    ]
    got["demand"] = {
        "bands": [{"band": "28,3–40 м²", "asked_share": 0.351, "left_share": 0.152},
                  {"band": "55–85 м²", "asked_share": 0.268, "left_share": 0.329}],
        "funnel": {
            "leads": 573, "target": 449, "booked": 34,
            "by_source": [{"source": "звонок", "leads": 512, "booked": 16, "rate": 0.031},
                          {"source": "агент", "leads": 44, "booked": 16, "rate": 0.364}],
            "by_manager": [{"manager": "Менеджер А", "leads": 160, "booked": 20, "rate": 0.125},
                           {"manager": "Менеджер Б", "leads": 168, "booked": 2, "rate": 0.012}],
        },
    }
    got["by_size"] = [{"band": "28,3–40 м²", "contracts": 35, "area": 1_240.0,
                       "amount": 280e6, "price_per_sqm": 225_800}]
    got["terminated"] = [{"contract": "ДДУ-14", "object": "кв. 118", "on": "2026-05-14",
                          "escrow_returned": 9.4e6}]
    # Серверная сборка кварталов зовётся на том же своде: у неё была своя ветка,
    # до которой прежние проверки не доходили — в `plan_comparison` лежал
    # дословный кусок `conclusions` с обращением к `out`, и на проекте с эскроу
    # и спросом это `NameError`, а не «пустой раздел».
    served = contracting.plan_comparison(got)
    assert isinstance(served, dict) and "quarters" in served
    got["conclusions"] = contracting.conclusions(got)
    return got


def test_every_section_of_the_report_draws_without_killing_the_page(tmp_path) -> None:
    pw = pytest.importorskip("playwright.sync_api")
    import browser_launch

    body = cabinet_page("sales").replace("__DEVELOPAID_VERSION__", "test")
    file = tmp_path / "cabinet.html"
    file.write_text(body, encoding="utf-8")

    errors: list[str] = []
    with pw.sync_playwright() as play:
        try:
            browser = browser_launch.launch(play)
        except Exception as exc:  # образ без Chromium — не поломка кабинета
            pytest.skip(f"Chromium недоступен: {exc}")
        try:
            tab = browser.new_page()
            tab.on("pageerror", lambda e: errors.append(str(e)))
            tab.goto(file.as_uri())
            seen = tab.evaluate(
                "(d)=>{showSales(d); const box=document.querySelector('#sales');"
                " return {len:box?box.innerHTML.length:0,"
                "  blocks:document.querySelectorAll('#sales .salesblock').length,"
                "  plans:!!document.getElementById('sb-plan')}}", full_summary())
        finally:
            browser.close()

    assert not errors, f"страница упала на полном своде: {errors[:2]}"
    assert seen["plans"], "раздел «Факт против планов» не нарисован при прочитанных планах"
    assert seen["blocks"] >= 6, f"разделов на экране {seen['blocks']} — свод оборвался"
    assert seen["len"] > 20_000, "отчёт вышел короче, чем один раздел"


def test_the_quarter_rows_belong_to_the_block_that_reads_them() -> None:
    """`rows` собираются один раз и объявлены там, где их читают обе поверхности —
    картинка и таблица под ней."""
    body = (ROOT / "market_search" / "cabinet.py").read_text(encoding="utf-8")
    block = body[body.index("function salesPlansBlock(d){"):]
    block = block[: block.index("\nfunction ", 1)]
    assert "const rows=salesPlansRows(" in block, \
        "таблица кварталов снова читает `rows` из чужой области видимости"
