"""Стратегия финансирования очередей — в «Экономика → Финансирование».

Решение владельца (19.10.2026): блок «Стратегия финансирования очередей»
стоит последним в группе «Финансирование», а не на вкладке «Очередность».
Виден он при том же условии, что настройки очередей: очередность включена и
очередей две и больше. Скрытый блок значений не теряет — выбор живёт в
`phasing`, а не в узлах страницы. Разметка одна: шаблон
`phaseFinancingTemplate`, который ставит в группу `renderInputs`.

Когда очереди включены (2+), на вкладке «Очередность» стоит подсказка с
кнопкой перехода к блоку (решение владельца, 19.10.2026).

Проверяется отрисованная страница (`main_registry.app`, ширина 390).

Запуск: python3 -m pytest tests/test_phasing_strategy_lives_in_finance.py -q
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

import main_legacy as core  # noqa: E402

PORT = 19863
GROUP = "Финансирование"

# Где блок и виден ли он: в группе «Финансирование», на вкладке «Очередность»
# и в каком месте группы он стоит.
PROBE = """()=>{
  const det=document.querySelector('details[data-group="Финансирование"]');
  const block=document.getElementById('phaseFinancingBlock');
  const shown=el=>!!el&&!!(el.offsetWidth||el.offsetHeight||el.getClientRects().length);
  const kids=det?Array.from(det.children).filter(shown):[];
  const r=block?block.getBoundingClientRect():null;
  return {
    group:!!det, open:!!(det&&det.open),
    inGroup:!!(det&&block&&det.contains(block)),
    shown:shown(block),
    last:!!block&&kids[kids.length-1]===block,
    count:document.querySelectorAll('#phaseFinancingBlock').length,
    onPhasingTab:!!document.querySelector('#phasing #phaseFinancingIndependent'),
    independent:!!(document.getElementById('phaseFinancingIndependent')||{}).checked,
    unified:!!(document.getElementById('phaseFinancingUnified')||{}).checked,
    strategy:phasing.financing_strategy,
    text:block?block.textContent:'',
    left:r?r.left:null, right:r?r.right:null,
    pageScroll:document.documentElement.scrollWidth-document.documentElement.clientWidth,
  };
}"""


@pytest.fixture(scope="module")
def page():
    import browser
    chrome = browser.chromium_or_skip()
    from playwright.sync_api import sync_playwright
    import main_registry

    with browser.serve(main_registry.app, PORT) as origin:
        with sync_playwright() as pw:
            engine = pw.chromium.launch(executable_path=str(chrome))
            tab = engine.new_page(viewport={"width": 390, "height": 900})
            tab.goto(origin + "/", wait_until="domcontentloaded")
            browser.wait_for_result(tab)
            yield tab
            engine.close()


def _open_finance(page) -> dict:
    page.get_by_role("button", name="Экономика", exact=True).first.click()
    page.evaluate("""()=>{const d=document.querySelector('details[data-group="Финансирование"]');
      if(d&&!d.open)d.querySelector('summary').click();}""")
    return page.evaluate(PROBE)


def _phases(page, count: int) -> None:
    import browser
    page.evaluate(f"()=>{{togglePhasing(true);setPhaseCount({count});}}")
    browser.wait_for_result(page)


def test_one_queue_shows_no_strategy_and_the_queue_tab_lost_it(page) -> None:
    got = _open_finance(page)
    assert got["group"] and got["open"], got
    assert not got["shown"], "без очередности стратегия очередей видна в «Финансировании»"
    assert not got["onPhasingTab"], "блок остался на вкладке «Очередность»"

    _phases(page, 1)
    got = _open_finance(page)
    assert not got["shown"], "при одной очереди стратегия очередей видна"


def test_two_queues_put_the_strategy_last_and_the_choice_reaches_the_calculation(page) -> None:
    import browser
    _phases(page, 2)
    got = _open_finance(page)
    assert got["inGroup"] and got["shown"], got
    assert got["last"], "блок стратегии не последний в группе «Финансирование»"
    assert got["count"] == 1, "блок стратегии нарисован не один раз"
    assert not got["onPhasingTab"], "блок остался на вкладке «Очередность»"
    assert got["independent"] and not got["unified"], got
    assert got["left"] >= 0 and got["right"] <= 390 and got["pageScroll"] <= 0, got
    # Простым языком: жаргон прежнего блока ушёл с экрана.
    for word in ("cash", "РНС", "БРИДЖ", "Кэш-свип", "Excel-книга", "x —"):
        assert word not in got["text"], f"на экране осталось «{word}»"
    assert "разрешения на строительство" in got["text"]
    assert "проектное финансирование (ПФ, банковский кредит на стройку)" in got["text"]

    with page.expect_request("**/calculate-phased") as sent:
        page.click("#phaseFinancingUnified")
    body = json.loads(sent.value.post_data or "{}")
    assert body["phasing"]["financing_strategy"] == "unified_project_cash", body["phasing"]
    browser.wait_for_result(page)
    page.wait_for_function(
        "()=>/Единый денежный поток включён/.test(document.getElementById('phaseFinancingSummary').textContent)",
        timeout=30_000)

    # Перерисовка «Экономики» выбор не сбрасывает.
    page.evaluate("()=>renderInputs()")
    got = page.evaluate(PROBE)
    assert got["unified"] and not got["independent"], got

    # Очередность выключили — блок спрятан, выбор сохранился; включили — вернулся.
    page.evaluate("()=>togglePhasing(false)")
    browser.wait_for_result(page)
    got = _open_finance(page)
    assert not got["shown"] and got["strategy"] == "unified_project_cash", got
    _phases(page, 3)
    got = _open_finance(page)
    assert got["shown"] and got["last"] and got["unified"], got


HINT = """()=>{
  const hint=document.getElementById('phaseFinanceHint');
  const shown=!!hint&&!!(hint.offsetWidth||hint.offsetHeight||hint.getClientRects().length);
  const r=hint?hint.getBoundingClientRect():null;
  return {shown, text:hint?hint.textContent:'', left:r?r.left:null, right:r?r.right:null,
    pageScroll:document.documentElement.scrollWidth-document.documentElement.clientWidth};
}"""


def test_switching_queues_on_points_to_the_finance_block(page) -> None:
    import browser
    page.evaluate("()=>togglePhasing(false)")
    browser.wait_for_result(page)
    page.evaluate("()=>openTab('phasing')")
    assert not page.evaluate(HINT)["shown"], "подсказка видна без очередей"

    page.click("#phasingEnabled")
    browser.wait_for_result(page)
    page.evaluate("()=>{if(Number(phasing.phase_count||1)<2)setPhaseCount(2)}")
    browser.wait_for_result(page)
    got = page.evaluate(HINT)
    assert got["shown"], "после включения очередей подсказки нет"
    assert "Очереди включены" in got["text"] and "«Экономика → Финансирование»" in got["text"], got
    assert got["left"] >= 0 and got["right"] <= 390 and got["pageScroll"] <= 0, got

    page.get_by_role("button", name="Перейти к финансированию очередей").click()
    landed = page.evaluate("""()=>{const b=document.getElementById('phaseFinancingBlock');
      const r=b?b.getBoundingClientRect():null;
      return {inputs:document.getElementById('inputs').classList.contains('active'),
        top:r?r.top:null, h:innerHeight, shown:!!b&&!b.hidden};}""")
    assert landed["inputs"] and landed["shown"], landed
    assert 0 <= landed["top"] < landed["h"], landed


def test_the_markup_lives_once_in_a_template() -> None:
    page = core.PAGE
    assert page.count('id="phaseFinancingTemplate"') == 1
    assert page.count('id="phaseFinancingIndependent"') == 1
    # Блок — внутри шаблона, а не второй живой копией на странице.
    tpl = page.split('id="phaseFinancingTemplate"', 1)[1].split("</template>", 1)[0]
    assert 'id="phaseFinancingIndependent"' in tpl
