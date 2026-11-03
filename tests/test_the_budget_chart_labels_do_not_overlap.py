"""Подписи статей под столбцами графика бюджета не налезают друг на друга.

Владелец (23.10.2026, скриншот графика «Бюджет на октябрь 2026: план и
оплачено по статьям»): «Смазалось» — пять длинных названий статей шли одной
строкой по центру узких слотов и накладывались. Теперь подпись переносится по
словам в несколько строк, а легенда опускается ниже последней строки.

Мерится отрисованный SVG в Chromium, а не позиции в разметке: перекрытие
видно только по реальным рамкам текста.
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import developaid_report_charts as charts  # noqa: E402
from developaid_report_page import REPORT_PAGE  # noqa: E402

GROUPS = ["Стройка и проектирование", "Коммерческие расходы",
          "Служба заказчика, охрана и офис", "Приобретение проекта (земля)",
          "Административно-хозяйственные расходы"]


def _chart() -> str:
    return charts.bar_chart(
        "Бюджет на октябрь 2026: план и оплачено по статьям", GROUPS,
        [{"name": "План", "values": [401.0, 43.3, 6.5, 78.1, 1.6]},
         {"name": "Оплачено", "values": [117.6, 15.3, 12.4, 78.1, 3.1]}], "млн ₽", digits=1)


def _boxes(width: int) -> dict:
    from browser import chromium_or_skip

    chrome = chromium_or_skip()
    from playwright.sync_api import sync_playwright

    with sync_playwright() as pw:
        browser = pw.chromium.launch(executable_path=str(chrome))
        try:
            tab = browser.new_page(viewport={"width": width, "height": 900})
            tab.route("**/*", lambda route: route.fulfill(status=200, body="{}",
                                                           content_type="application/json"))
            tab.set_content(REPORT_PAGE)
            tab.evaluate("html => { document.getElementById('reportBox').innerHTML = html; "
                         "document.getElementById('privateArea').classList.remove('hidden') }",
                         _chart())
            return tab.evaluate("""groups => {
                const svg = document.querySelector('#reportBox svg.chart');
                const texts = [...svg.querySelectorAll('text')];
                const rect = t => { const r = t.getBoundingClientRect();
                    return {left: r.left, right: r.right, top: r.top, bottom: r.bottom}; };
                // Строки переноса склеены в textContent без пробелов — сравниваем без них.
                const flat = s => s.replace(/\\s+/g, '');
                return {
                    svg: rect(svg),
                    labels: groups.map(g => rect(texts.find(t => flat(t.textContent) === flat(g)))),
                    legend: rect(texts.find(t => flat(t.textContent) === 'План')),
                };
            }""", GROUPS)
        finally:
            browser.close()


def test_the_article_labels_stand_apart_and_above_the_legend():
    boxes = _boxes(760)
    labels = boxes["labels"]
    assert all(labels), "каждая подпись статьи есть на графике"
    for a, b in zip(labels, labels[1:]):
        assert a["right"] <= b["left"] + 0.5, (a, b)
    assert all(l["left"] >= boxes["svg"]["left"] - 0.5 and l["right"] <= boxes["svg"]["right"] + 0.5
               for l in labels), labels
    # Легенда ниже самой длинной подписи, а не поверх неё.
    assert boxes["legend"]["top"] >= max(l["bottom"] for l in labels) - 0.5, (boxes["legend"], labels)


def test_the_labels_keep_apart_on_a_phone_too():
    labels = _boxes(390)["labels"]
    for a, b in zip(labels, labels[1:]):
        assert a["right"] <= b["left"] + 0.5, (a, b)


def test_a_long_word_breaks_at_its_hyphen_and_short_labels_stay_whole():
    assert charts._wrap("Административно-хозяйственные расходы", 105) == [
        "Административно-", "хозяйственные", "расходы"]
    assert charts._wrap("Служба заказчика, охрана и офис", 105) == ["Служба заказчика,", "охрана и офис"]
    assert charts._wrap("01.26", 105) == ["01.26"]
    # Месяцы темпа продаж по-прежнему в одну строку: рисунок не растёт.
    months = charts.bar_chart("t", ["01.26", "02.26", "03.26"],
                              [{"name": "м²", "values": [1.0, 2.0, 3.0]}], "м²")
    assert f'viewBox="0 0 {charts.WIDTH} {charts.HEIGHT}"' in months
