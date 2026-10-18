"""Стоимость сделки на странице: части, итог и график — из одного расчёта.

Случай владельца (участок 77:02:0007003:52): цена участка 0, выкуп ЗУ/ОКС у
третьих лиц 1,85 млрд из контура КРТ. Три строки сделки стояли на равных и
итог читался третьей статьёй, подпись выкупа «не цена сделки» спорила со
строкой «Стоимость сделки», а график платежей за покупку выходил пустым.
Расход при этом был учтён один раз — ошибка подачи, не счёта.

Проверка смотрит на ОТРИСОВАННУЮ страницу: подписи и график — то, что читает
человек; разбор PDF и Telegram — в `test_land_buyout_is_part_of_the_deal.py`.

Запуск: python3 -m pytest tests/test_the_deal_total_reads_as_a_total.py -q
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from browser import chromium_or_skip, serve, wait_for_result  # noqa: E402

PORT = 8794
BUYOUT = 1850.0


def test_in_a_real_browser_the_deal_is_parts_and_a_total():
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
            got = tab.evaluate("""async (buyout)=>{
              // Расчёт забирает форму поверх `inputs` — пишем в поля, как человек.
              const put=(id,v)=>{inputs[id]=v;const el=document.getElementById('f_'+id);if(el)el.value=v;};
              put('purchase_price_mln',0);
              put('land_buyout_mln',buyout);
              put('purchase_schedule','100%@0');
              inputs._land_buyout_source={value:buyout,kind:'krt_contour',
                by:'оценка по кадастровой стоимости: 3 объектов'};
              await settledCalculate();
              const rows=t=>[...t.querySelectorAll('tr')].map(x=>(x.textContent||'').replace(/\\s+/g,' ').trim());
              return {params: rows(projectParamsTable), finance: rows(reportFinanceTable),
                      deal: lastResult.deal};
            }""", BUYOUT)
        finally:
            browser.close()

    other = [line for line in errors if "Failed to fetch" not in line]
    assert not other, f"страница упала: {other[:2]}"
    deal = got["deal"]
    assert deal["buyout_basis"] == "krt_cadastral", deal
    params = got["params"]
    total = [line for line in params if line.startswith(deal["total_label"])]
    assert total, f"строки-итога сделки нет: {params[:12]}"
    parts = [line for line in params if line.startswith("в т.ч.")]
    assert any("оценка по кадастровой стоимости" in line for line in parts), parts
    assert not any("не цена сделки" in line for line in params), params
    # Итог стоит над своими «в т.ч.», а не третьей статьёй после них.
    assert params.index(total[0]) < params.index(parts[0])
    schedule = [line for line in got["finance"] if line.startswith("График платежей за покупку")]
    assert schedule, f"графика покупки нет: {got['finance'][:6]}"
    assert re.search(r"\d{2}\.\d{2}\.\d{4}", schedule[0]) and "100" in schedule[0], schedule[0]
