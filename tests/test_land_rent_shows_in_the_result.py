"""Посчитанная аренда земли видна в «Результате» и не держит «уточните аренду».

1. Строка «Аренда земли участка» в «Параметрах проекта»: раньше посчитанная
   аренда в «Результат» не попадала вовсе. Своя земля — строки нет (ноль
   читался бы «аренда бесплатна»); сумма не определена — известная часть с
   причиной от движка, а без известной части — «Не определена», не ноль.
   Применимость решает `land_rent.status`, определена ли сумма —
   `summary.land_rent_sum` (`developaid_land_rent.sum_state`).
2. Карточка «Инвестиционное решение» писала «Предварительная экономика:
   уточните аренду земли», пока предварительными оставались только график
   оплаты или НДС, — хотя сумма аренды уже определена. Заголовок остаётся,
   когда сумма не определена по тому же ответу движка, что и строка
   страницы; оговорку несёт подпись под плитками.

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

import pytest  # noqa: E402

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
    # Договор кончается до ввода, стоимость после смены ВРИ указана: сумма
    # аренды определена, предварительным остаётся только график оплаты.
    bundle = _run(land_rent_termination_date="2028-01-01", land_rent_cadastral_target_mln=120)
    rent, summary = bundle["consolidated"]["land_rent"], bundle["consolidated"]["summary"]
    assert rent["financial_missing_codes"] == ["payments"], "стенд не про один лишь график оплаты"
    assert summary["preliminary"] and summary["preliminary_reason"]
    assert summary["land_rent_sum"] == {"known": True, "reason": ""}
    assert core.entry_price_verdict(bundle)["title"] != ASK


@pytest.mark.parametrize("case, kw, reason", [
    # Без даты окончания аренда после ввода не посчитана — суммы нет.
    ("после ввода", {"land_rent_cadastral_target_mln": 120}, "Аренда после ввода требует отдельного расчёта."),
    # Сумма посчитана, но стоимость после смены ВРИ не указана — сумма ещё изменится.
    ("смена ВРИ", {"land_rent_termination_date": "2028-01-01"}, "Кадастровая стоимость участка после смены ВРИ"),
    # Москва: повышенная часть первого года оплачивается отдельно, её сумма не определена.
    ("первый год", {"land_rent_mode": "msk_mkd_3_2", "land_rent_premium_status": "separate_required",
                    "land_rent_termination_date": "2028-01-01", "land_rent_cadastral_target_mln": 120,
                    "land_rent_preset_confirmed": True}, "Повышенная часть первого года"),
    # Земля в аренде, условия не заданы.
    ("нет условий", {"land_rent_mode": "unspecified"}, "Для арендуемой земли не заданы"),
])
def test_a_rent_sum_that_is_not_determined_still_asks(case, kw, reason):
    bundle = _run(**kw)
    got = bundle["consolidated"]["summary"]["land_rent_sum"]
    assert got["known"] is False and got["reason"].startswith(reason), (case, got)
    assert core.entry_price_verdict(bundle)["title"] == ASK, case


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
              lastResult.summary.land_rent_sum={known:true,reason:''};
              lastResult.capex.land_rent=2.5e9;
              renderResult();
              const lease=grab();
              // Сумма посчитана, но ещё изменится (тот же ответ движка, что у карточки).
              lastResult.summary.land_rent_sum={known:false,reason:'Аренда после ввода требует отдельного расчёта.'};
              renderResult();
              const part=grab();
              // Условия не заданы: известной части нет — не ноль.
              lastResult.land_rent={status:'incomplete'};
              lastResult.summary.land_rent_sum={known:false,reason:'Для арендуемой земли не заданы кадастровая база, дата и годовые ставки аренды.'};
              lastResult.capex.land_rent=0;
              renderResult();
              const none=grab();
              // Нет ответа движка — сумма не считается определённой.
              lastResult.land_rent={status:'preliminary'};
              delete lastResult.summary.land_rent_sum;
              lastResult.capex.land_rent=2.5e9;
              renderResult();
              return {own, lease, part, none, silent:grab()};
            }""")
        finally:
            browser.close()

    other = [line for line in errors if "Failed to fetch" not in line]
    assert not other, f"страница упала: {other[:2]}"
    assert got["own"]["status"] == "not_applicable", "стенд не про свою землю"
    assert got["own"]["rows"] == [], "у своей земли строка аренды нулём"
    assert len(got["lease"]) == 1 and got["lease"][0][1].replace(" ", " ") == "2,5 млрд ₽", got["lease"]
    assert got["part"][0][1].replace(" ", " ") == (
        "2,5 млрд ₽ Это известная часть суммы, она ещё уточнится. Аренда после ввода требует отдельного расчёта."), got
    assert got["none"][0][1] == ("Не определена. Для арендуемой земли не заданы кадастровая база, дата и годовые "
                                 "ставки аренды."), got["none"]
    assert got["silent"][0][1].replace(" ", " ") == (
        "2,5 млрд ₽ Это известная часть суммы, она ещё уточнится. Сумма аренды не определена."), got["silent"]
