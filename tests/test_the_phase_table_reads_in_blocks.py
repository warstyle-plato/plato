"""Таблица «Сравнение очередей» читается блоками, итоги отличимы от слагаемых.

Замечания владельца по проду 0.24.41: строки «Итого МКД», «Итого отдельные
объекты», «Выручка» не выделены и не отличаются от слагаемых; места паркинга
отдельно стоящих объектов стояли сразу после «Общая площадь — ГНС», посреди
площадей МКД, а деньги того же паркинга — внизу, среди ОСЗ; «подземная часть
под объектами» висела среди площадей без своего блока.

Проверяется отрисованное: стенд на node исполняет настоящую
`renderPhaseComparison` из `PAGE` (куски — через `page_blocks.run`), а
Chromium меряет живую страницу — жирность, линию над итогом и отступ.

Запуск: python3 -m pytest tests/test_the_phase_table_reads_in_blocks.py -q
"""

from __future__ import annotations

import html
import json
import re
import sys
import threading
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import main_legacy as core  # noqa: E402
import page_blocks  # noqa: E402
from browser import chromium_or_skip  # noqa: E402
from test_object_parking_reaches_the_queue import _phased  # noqa: E402

PORT = 18934

# Порядок отчёта о прибылях: объёмы → выручка → расходы → финансирование →
# прибыль, удельные — после них (владелец, 27.09.2026).
BLOCKS = ["mkd", "osz", "revenue", "costs", "finance", "result", "unit"]
LAST_ROW = "Чистая прибыль на м² продаваемой"


@pytest.fixture(scope="module")
def bundle() -> dict:
    # Офисы с гаражом в первой очереди, ТЦ во второй: паркинг объектов
    # строится и продаётся, выручка ОСЗ есть в обеих очередях.
    sys.setrecursionlimit(400000)
    data = json.loads(json.dumps(_phased(), default=str))
    assert any(x["object_parking_units"] > 0 for x in data["comparison"])
    return data


def _rows_from_node(bundle: dict) -> list[dict]:
    prelude = (
        "const phaseBundle=" + json.dumps(bundle, ensure_ascii=False) + ";\n"
        "const box=()=>({style:{},innerHTML:'',textContent:'',className:''});\n"
        "const phaseComparisonCard=box(),phaseComparisonHead=box(),"
        "phaseComparisonBody=box();\n"
        "var document={getElementById:()=>null,querySelector:()=>null,"
        "querySelectorAll:()=>[]};\n"
    )
    tail = ("renderPhaseComparison();\n"
            "console.log(phaseComparisonBody.innerHTML);\n")
    out, _ = page_blocks.run(prelude, tail)
    rows = []
    for tr in re.findall(r"<tr[^>]*>.*?</tr>", out, re.S):
        attrs = tr[:tr.index(">")]
        get = lambda name: (re.search(name + r'="([^"]*)"', attrs) or [None, ""])[1]  # noqa: E731
        cells = re.findall(r"<t[dh]([^>]*)>(.*?)</t[dh]>", tr, re.S)
        rows.append({
            "block": get("data-block"), "cls": get("class"), "group": get("data-group"),
            "label": html.unescape(re.sub(r"<[^>]+>", "", cells[0][1])).strip() if cells else "",
            "values": [float(v.group(1)) if (v := re.search(r'data-v="([^"]*)"', a)) else None
                       for a, _ in cells[1:]],
        })
    return rows


@pytest.fixture(scope="module")
def rows(bundle) -> list[dict]:
    return _rows_from_node(bundle)


def test_every_row_sits_in_a_titled_block_in_order(rows) -> None:
    heads = [r["block"] for r in rows if r["cls"] == "pc-block"]
    assert heads == BLOCKS, heads
    current = None
    for r in rows:
        if r["cls"] == "pc-block":
            current = r["block"]
            continue
        assert r["block"] and r["block"] == current, r


def test_unit_block_follows_finance_and_profit_per_metre_closes_the_table(rows) -> None:
    heads = [r["block"] for r in rows if r["cls"] == "pc-block"]
    assert heads.index("unit") > heads.index("finance"), heads
    assert heads.index("unit") > heads.index("result"), heads
    assert rows[-1]["label"] == LAST_ROW, rows[-1]["label"]
    assert rows[-1]["block"] == "unit"


def test_article_rates_sit_with_the_costs(rows) -> None:
    """Ставки — подгруппой в «Затратах»: заголовок с единицей, строки с отступом.

    Голое «1,0» под колонкой «млрд ₽» читалось как продолжение денег.
    """
    at = next(i for i, r in enumerate(rows) if r["cls"] == "pc-caption")
    caption = rows[at]
    assert caption["block"] == "costs" and "тыс ₽/м²" in caption["label"], caption
    rates = rows[at + 1:at + 5]
    assert [r["label"].split(" (")[0] for r in rates] == [
        "ИРД и согласования", "Проектирование П+РД", "Подготовительные работы", "Наружные сети"]
    assert all(r["block"] == "costs" and r["cls"] == "pc-sub" for r in rates), rates


def _block_of(rows, text: str) -> str:
    found = [r["block"] for r in rows if r["cls"] != "pc-block" and r["label"].startswith(text)]
    assert found, f"строки «{text}» в таблице нет"
    return found[0] if len(set(found)) == 1 else ",".join(found)


def test_object_parking_lives_in_the_object_block(rows) -> None:
    """Места, «из них продаётся» и подземная часть — в блоке ОСЗ, рядом с
    площадями объектов, а не посреди площадей МКД."""
    for text in ("Паркинг отдельно стоящих объектов — мест", "из них продаётся",
                 "подземная часть под объектами"):
        assert _block_of(rows, text) == "osz", text
    # Деньги того же паркинга — слагаемое «Итого ОСЗ», а не МКД.
    money = [r for r in rows if r["block"] == "revenue"
             and r["label"] == core.NON_TEP_PRODUCT_LABELS["object_parking"]]
    assert money and money[0]["group"] == "osz"


def test_object_rows_follow_the_registry(rows, bundle) -> None:
    """Состав блока ОСЗ — из STANDALONE_OBJECTS: объект с выручкой встаёт сам."""
    labels = {p["key"]: p["label"] for p in bundle["consolidated"]["report"]["products"]}
    osz = [r["label"] for r in rows if r["block"] == "revenue" and r["group"] == "osz"
           and r["cls"] == "pc-part"]
    order = [o.key for o in core.STANDALONE_OBJECTS]
    sold = [k for k in order
            if any((x["revenue_by_product"] or {}).get(k) for x in bundle["comparison"])]
    assert sold, "на вводных нет ОСЗ с выручкой — проверять нечего"
    assert osz[:len(sold)] == [labels[k] for k in sold]


def test_totals_are_marked_and_equal_the_sum_of_their_parts(rows) -> None:
    totals = {r["label"]: r for r in rows if r["cls"] == "pc-total"}
    assert {"Итого МКД", "Итого ОСЗ", "Выручка всего"} <= set(totals), list(totals)
    for label, group in (("Итого МКД", "mkd"), ("Итого ОСЗ", "osz"),
                         ("Выручка всего", None)):
        total = totals[label]
        parts = [r for r in rows if r["cls"] == "pc-part"
                 and (group is None or r["group"] == group)]
        assert parts, label
        for i, value in enumerate(total["values"]):
            assert value is not None, (label, i)
            assert value == pytest.approx(sum(p["values"][i] for p in parts),
                                          rel=1e-9, abs=1.0), (label, i)
    # Итог стоит ПОСЛЕ своих слагаемых, не над ними.
    idx = {r["label"]: i for i, r in enumerate(rows)}
    for group, label in (("mkd", "Итого МКД"), ("osz", "Итого ОСЗ")):
        last = max(i for i, r in enumerate(rows) if r["cls"] == "pc-part" and r["group"] == group)
        assert idx[label] > last, label


def _server():
    import uvicorn

    server = uvicorn.Server(uvicorn.Config(core.app, host="127.0.0.1", port=PORT,
                                           log_level="error"))
    threading.Thread(target=server.run, daemon=True).start()
    for _ in range(200):
        if server.started:
            break
        time.sleep(0.05)
    assert server.started
    return server


def _open(pw, chrome, bundle, width: int):
    """Живая страница с таблицей сравнения на пакете очередей."""
    browser = pw.chromium.launch(executable_path=str(chrome))
    page = browser.new_page(viewport={"width": width, "height": 900})
    errors: list[str] = []
    page.on("pageerror", lambda exc: errors.append(str(exc)))
    page.goto(f"http://127.0.0.1:{PORT}/", wait_until="domcontentloaded")
    page.wait_for_function("typeof renderPhaseComparison==='function'")
    page.evaluate(
        "b=>{phaseBundle=b;let n=document.getElementById('phaseComparisonCard');"
        "while(n){if(n.style)n.style.display='block';n=n.parentElement}"
        "renderPhaseComparison()}", bundle)
    return browser, page, errors


@pytest.fixture(scope="module")
def server():
    chromium_or_skip()
    srv = _server()
    yield srv
    srv.should_exit = True


# Число, разорванное переносом («917,9 тыс ₽/м» и «²» строкой ниже), и
# колонка подписей, уехавшая при прокрутке, — то, что видел владелец на
# телефоне. Меряется на отрисованной странице, а не по CSS в исходнике.
_LAYOUT = """()=>{
  const wrap=document.querySelector('#phaseComparisonCard .scroll');
  const rows=[...document.querySelectorAll('#phaseComparisonBody tr:not(.pc-block):not(.pc-caption)')];
  const lines=el=>{const r=document.createRange();r.selectNodeContents(el);
    return new Set([...r.getClientRects()].filter(x=>x.width>0).map(x=>Math.round(x.top))).size};
  const broken=[];
  rows.forEach(t=>[...t.cells].slice(1).forEach(td=>{if(lines(td)>1)broken.push(td.innerText)}));
  wrap.scrollLeft=wrap.scrollWidth;
  const w=wrap.getBoundingClientRect(),row=rows[rows.length-1];
  const first=row.cells[0].getBoundingClientRect(),last=row.cells[row.cells.length-1].getBoundingClientRect();
  const res={broken:broken.slice(0,5),scrolls:wrap.scrollWidth>wrap.clientWidth,
    firstLeft:first.left-w.left,lastRight:w.right-last.right,
    lastText:row.cells[0].innerText.trim(),order:[...document.querySelectorAll(
      '#phaseComparisonBody tr.pc-block')].map(t=>t.dataset.block)};
  wrap.scrollLeft=0;return res}"""


@pytest.mark.timeout(300)
@pytest.mark.parametrize("width", [1300, 390])
def test_the_table_reads_on_desktop_and_phone(bundle, server, width) -> None:
    from playwright.sync_api import sync_playwright

    chrome = chromium_or_skip()
    with sync_playwright() as pw:
        browser, page, errors = _open(pw, chrome, bundle, width)
        got = page.evaluate(_LAYOUT)
        browser.close()
    assert not errors, errors
    assert got["order"] == BLOCKS, got["order"]
    assert got["lastText"] == LAST_ROW, got["lastText"]
    assert not got["broken"], f"число разорвано переносом на {width}px: {got['broken']}"
    # Прокрученная до конца таблица показывает «Свод» целиком, а подпись
    # строки стоит у левого края.
    assert got["lastRight"] >= -1, got
    assert abs(got["firstLeft"]) <= 1, got
    if width == 390:
        assert got["scrolls"], "на телефоне таблица обязана прокручиваться вбок"


@pytest.mark.timeout(300)
def test_totals_look_like_totals_on_the_rendered_page(bundle, server) -> None:
    from playwright.sync_api import sync_playwright

    chrome = chromium_or_skip()
    with sync_playwright() as pw:
        browser, page, errors = _open(pw, chrome, bundle, 1300)
        got = page.evaluate("""()=>[...document.querySelectorAll('#phaseComparisonBody tr')]
          .filter(t=>!t.classList.contains('pc-block')&&!t.classList.contains('pc-caption')).map(t=>{
            const c=t.cells[0],s=getComputedStyle(c),n=getComputedStyle(t.cells[1]);
            return {label:c.innerText.trim(),cls:t.className,visible:t.offsetHeight>0,
              weight:+n.fontWeight,border:parseFloat(n.borderTopWidth),
              indent:parseFloat(s.paddingLeft)}})""")
        heads = page.evaluate("""()=>[...document.querySelectorAll(
          '#phaseComparisonBody tr.pc-block')].map(t=>t.offsetHeight>0&&t.innerText.trim())""")
        browser.close()
    assert not errors, errors
    assert len(heads) == len(BLOCKS) and all(heads), heads
    assert all(r["visible"] for r in got)
    plain = [r for r in got if not r["cls"]]
    totals = [r for r in got if r["cls"] == "pc-total"]
    parts = [r for r in got if r["cls"] in ("pc-part", "pc-sub")]
    assert totals and parts and plain
    base_weight = max(r["weight"] for r in plain)
    base_indent = max(r["indent"] for r in plain)
    for r in totals:
        assert r["weight"] >= 700 and r["weight"] > base_weight, r
        assert r["border"] >= 1, r
    for r in parts:
        assert r["indent"] >= base_indent + 10, r
