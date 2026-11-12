"""Посчитанная аренда земли видна в «Результате» и не держит «уточните аренду».

1. Строка «Аренда земли участка» в «Параметрах проекта»: раньше посчитанная
   аренда в «Результат» не попадала вовсе. Своя земля — строки нет (ноль
   читался бы «аренда бесплатна»); не вся сумма известна — число с оговоркой.
   Применимость и полноту решает движок (`land_rent.status`).
2. Карточка «Инвестиционное решение» писала «Предварительная экономика:
   уточните аренду земли», пока предварительными оставались только график
   оплаты или НДС, — хотя сумма аренды уже определена. Заголовок остаётся,
   только когда суммы нет; оговорку несёт подпись под плитками.

Запуск: python3 -m pytest tests/test_land_rent_shows_in_the_result.py -q
"""

from __future__ import annotations

import copy
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import main as _wrapper  # noqa: E402
from browser import chromium_or_skip, serve, wait_for_result  # noqa: E402

core = _wrapper.core
PORT = 18833
ASK = "Предварительная экономика: уточните аренду земли"
LEASE = {"land_right": "lease", "vri_region": "msk", "land_rent_mode": "manual",
         "land_rent_cadastral_mln": 100, "land_rent_regime_start": "2027-01-01",
         "project_start": "2027-01-01", "land_rent_rates": [{"year": 1, "rate_pct": 1.5}],
         "land_rent_tail_rule": "repeat_last", "land_rent_vat_treatment": "public_exempt"}


def _run(**kw) -> dict:
    x = {**copy.deepcopy(core.DEFAULT_INPUTS), **LEASE, **kw}
    return core._run_authoritative_model(x, copy.deepcopy(core.TEP_DEFAULT), [], {})


def test_a_known_rent_sum_does_not_ask_to_clarify_the_rent():
    # Договор кончается до ввода: сумма аренды определена, а график оплаты
    # и НДС ещё предварительные.
    bundle = _run(land_rent_termination_date="2028-01-01")
    rent, summary = bundle["consolidated"]["land_rent"], bundle["consolidated"]["summary"]
    assert rent["complete"] and rent["total"] is not None
    assert summary["preliminary"] and summary["preliminary_reason"], "стенд не про предварительный график"
    assert core.entry_price_verdict(bundle)["title"] != ASK


def test_an_unknown_rent_sum_still_asks():
    # Без даты окончания аренда после ввода не посчитана — суммы нет.
    bundle = _run()
    assert bundle["consolidated"]["land_rent"]["total"] is None
    assert core.entry_price_verdict(bundle)["title"] == ASK


def test_the_result_shows_the_rent_row_only_where_the_engine_says_it_applies():
    chrome = chromium_or_skip()
    from playwright.sync_api import sync_playwright

    from main_registry import app as registry_app

    with serve(registry_app, PORT) as base, sync_playwright() as pw:
        browser = pw.chromium.launch(executable_path=str(chrome))
        try:
            tab = browser.new_page()
            errors: list[str] = []
            tab.on("pageerror", lambda e: errors.append(str(e)))
            tab.goto(f"{base}/classic", wait_until="domcontentloaded")
            wait_for_result(tab)
            got = tab.evaluate("""async ()=>{
              await settledCalculate();
              const grab=()=>[...document.querySelectorAll('#projectParamsTable tr')]
                .map(tr=>[...tr.children].map(x=>(x.textContent||'').replace(/\\s+/g,' ').trim()))
                .filter(r=>r[0]==='Аренда земли участка');
              const own={status:(lastResult.land_rent||{}).status, rows:grab()};
              lastResult.land_rent={status:'preliminary'};
              lastResult.capex.land_rent=2.5e9;
              renderResult();
              const lease=grab();
              lastResult.land_rent={status:'incomplete'};
              renderResult();
              return {own, lease, incomplete:grab()};
            }""")
        finally:
            browser.close()

    other = [line for line in errors if "Failed to fetch" not in line]
    assert not other, f"страница упала: {other[:2]}"
    assert got["own"]["status"] == "not_applicable", "стенд не про свою землю"
    assert got["own"]["rows"] == [], "у своей земли строка аренды нулём"
    assert len(got["lease"]) == 1 and got["lease"][0][1].replace(" ", " ") == "2,5 млрд ₽", got["lease"]
    assert "известна не вся сумма" in got["incomplete"][0][1], got["incomplete"]
