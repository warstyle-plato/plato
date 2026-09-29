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

# Паркинг — продукт своего объекта; в этих проверках места продаёт офисник.
OFFICE_PARKING = "object_parking_offices"

import page_blocks  # noqa: E402
from browser import chromium_or_skip  # noqa: E402
from test_object_parking_reaches_the_queue import _phased  # noqa: E402

PORT = 18934

# Порядок отчёта о прибылях (владелец, 28.09.2026): доходы → все расходы
# подряд → финансирование → прибыль, последней строкой — чистая прибыль на
# м². Удельный стоит в разделе своей величины; ничего не свёрнуто.
BLOCKS = ["mkd", "osz", "revenue", "costs", "finance", "result"]
REVENUE_TAIL = [
    "Выручка всего",
    "Цена реализации на м² продаваемой",
    "в т.ч. квартиры — на м² их продаваемой",
    "Цена реализации на м² ГНС",
]
RATES = [f"{name} — цена м² МКД очереди" for name in (
    "ИРД и согласования", "Проектирование П+РД", "Подготовительные работы", "Наружные сети")]
EXPENSE_NOTE = ("По объектам не делятся: финансирование, коммерческие расходы "
                "и налог считаются на очередь целиком")
COSTS_TAIL = [
    "CAPEX всего",
    "CAPEX на м² ГНС",
    "Полные расходы",
    EXPENSE_NOTE,
    "Полные расходы на м² продаваемой",
    "Полные расходы на м² ГНС",
]


def _expected_costs(bundle: dict) -> list[str]:
    """«Затраты» зеркалят «Выручку»: объекты — в порядке строк ОСЗ выручки,
    выведенном из реестров напрямую, а не из проверяемой функции."""
    labels = core.product_labels()
    phases = bundle["phases"]
    built = [o.key for o in core.STANDALONE_OBJECTS
             if any(float(p["result"]["capex"].get(o.key) or 0) > 0.5 for p in phases)]
    out = RATES + ["МКД и общепроектные статьи"]
    for o in core.STANDALONE_OBJECTS:
        if o.key in built:
            out.append(labels[o.key])
            park = core.OBJECT_PARKING_PRODUCT_KEYS.get(o.key)
            if park and any((x.get("revenue_by_product") or {}).get(park)
                            for x in bundle["comparison"]):
                out.append(labels[park] + " — в CAPEX объекта")
    if len(built) > 1:
        out.append("Итого ОСЗ")
    return out + COSTS_TAIL
RESULT_TAIL = [
    "Чистая прибыль — cash",
    "Маржинальность",
    "Чистая прибыль на м² ГНС",
    "Чистая прибыль на м² продаваемой",
]
LAST_ROW = RESULT_TAIL[-1]
DIVISORS = ("на м² продаваемой — продаваемая площадь", "на м² ГНС — ГНС наземная")


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
        caption = re.search(r'<small class="pc-divisors">(.*?)</small>', tr, re.S)
        rows.append({
            "caption": html.unescape(re.sub(r"<[^>]+>", " ", caption.group(1))) if caption else "",
            "block": get("data-block"), "cls": get("class"), "group": get("data-group"),
            "label": html.unescape(re.sub(r"<small.*?</small>|<[^>]+>", "", cells[0][1], flags=re.S)).strip() if cells else "",
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
        if r["cls"] == "pc-caption":
            assert current is None, "подпись-делитель стоит не над таблицей"
            continue
        assert r["block"] and r["block"] == current, r


def _labels(rows, block: str) -> list[str]:
    return [r["label"] for r in rows if r["block"] == block and r["cls"] != "pc-block"]


def _strip_input(label: str) -> str:
    return re.sub(r" \(вводная [^)]*\)$", "", label)


def test_the_table_reads_like_a_profit_report(rows, bundle) -> None:
    """Доходы → все расходы подряд → финансирование → прибыль, и чистая
    прибыль на м² — последняя строка таблицы (прод, телефон: «всё в кучу» —
    владелец, 28.09.2026)."""
    heads = [r["block"] for r in rows if r["cls"] == "pc-block"]
    assert heads.index("revenue") < heads.index("costs") < heads.index("finance") \
        < heads.index("result") == len(heads) - 1, heads
    assert "unit" not in heads, "удельные снова собраны в свой блок вперемешку"
    revenue = _labels(rows, "revenue")
    assert revenue[-len(REVENUE_TAIL):] == REVENUE_TAIL, revenue
    costs = [_strip_input(x) for x in _labels(rows, "costs")]
    assert costs == _expected_costs(bundle), costs
    result = _labels(rows, "result")
    assert result[-len(RESULT_TAIL):] == RESULT_TAIL, result
    assert rows[-1]["label"] == LAST_ROW, rows[-1]["label"]
    # Цены — только среди доходов, расходы на метр — только среди расходов.
    for r in rows:
        if "Цена реализации" in r["label"]:
            assert r["block"] == "revenue", r
        if r["label"].startswith(("CAPEX на", "Полные расходы на")) or "цена м² МКД" in r["label"]:
            assert r["block"] == "costs", r


def test_divisors_are_a_caption_not_body_rows(rows, bundle) -> None:
    """«Делитель зачем показывать, тем более так крупно»: делитель — подпись
    таблицы мелким шрифтом, строк-делителей в теле нет. Числа подписи — те
    же площади, на которые делит движок."""
    assert not [r for r in rows if r["cls"] not in ("pc-block", "pc-caption")
                and "елитель" in r["label"]], [r["label"] for r in rows]
    captions = [r["caption"] for r in rows if r["caption"]]
    assert len(captions) == 1, captions
    caption = captions[0]
    for text in DIVISORS:
        assert text in caption, caption
    summary = bundle["consolidated"]["summary"]
    for key in ("monetizable_saleable_sqm", "project_gns_sqm"):
        total = f"{round(float(summary[key])):,}".replace(",", " ")
        assert total in caption.replace(" ", " "), (key, total, caption)


def test_article_rates_are_visible_costs_with_their_input(rows, bundle) -> None:
    """Ставки общепроектных статей — видимые строки расходов, до CAPEX, с
    вводной рядом; ничего не свёрнуто и не спрятано на другую вкладку."""
    costs = _labels(rows, "costs")
    assert [_strip_input(x) for x in costs[:len(RATES)]] == RATES, costs
    inputs = bundle["comparison"][0]["shared_rate_inputs_th"]
    for label, key in zip(costs, ("ird", "design", "preparation", "utilities")):
        if inputs.get(key) is not None:
            assert "(вводная " in label, label


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
             and r["label"] == core.NON_TEP_PRODUCT_LABELS[OFFICE_PARKING]]
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
    """Итог равен сумме своих слагаемых в своём разделе: «Итого МКД/ОСЗ» —
    своей группы, «Выручка всего» и «CAPEX всего» — всех слагаемых раздела.
    Итог стоит ПОСЛЕ своих слагаемых, не над ними."""
    checked = set()
    for block in ("revenue", "costs"):
        mine = [(i, r) for i, r in enumerate(rows) if r["block"] == block]
        for i, total in mine:
            if total["cls"] != "pc-total":
                continue
            everything = total["group"].endswith("all")
            parts = [(j, p) for j, p in mine if p["cls"] == "pc-part"
                     and (everything or p["group"] == total["group"])]
            assert parts, total["label"]
            assert i > max(j for j, _ in parts), total["label"]
            for k, value in enumerate(total["values"]):
                assert value is not None, (total["label"], k)
                assert value == pytest.approx(sum(p["values"][k] for _, p in parts),
                                              rel=1e-9, abs=1.0), (block, total["label"], k)
            checked.add((block, total["label"]))
    assert {("revenue", "Итого МКД"), ("revenue", "Итого ОСЗ"), ("revenue", "Выручка всего"),
            ("costs", "CAPEX всего")} <= checked, checked


def test_capex_of_an_object_is_the_engines_article(rows, bundle) -> None:
    """Число объекта в «Затратах» — статья объекта в расчёте очереди, а не
    доля, посчитанная страницей; МКД + ОСЗ = CAPEX очереди."""
    labels = core.product_labels()
    phases = bundle["phases"]
    costs = {r["label"]: r for r in rows if r["block"] == "costs" and r["cls"] == "pc-part"}
    objects = [o.key for o in core.STANDALONE_OBJECTS if labels[o.key] in costs]
    assert len(objects) >= 2, "на вводных меньше двух объектов со стройкой — проверять нечего"
    for key in objects:
        got = costs[labels[key]]["values"][:len(phases)]
        want = [float(p["result"]["capex"].get(key) or 0) for p in phases]
        assert got == pytest.approx(want, abs=1.0), key
    for k, p in enumerate(phases):
        assert sum(r["values"][k] for r in costs.values()) == pytest.approx(
            p["result"]["capex"]["total"], abs=1.0)


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
      '#phaseComparisonBody tr.pc-block')].map(t=>t.dataset.block),
    costs:[...document.querySelectorAll('#phaseComparisonBody tr[data-block="costs"]:not(.pc-block)')]
      .map(t=>t.cells[0].innerText.trim().replace(/ \(вводная [^)]*\)$/,'')),
    hidden:rows.filter(t=>t.offsetHeight===0).map(t=>t.cells[0].innerText)};
  const cap=document.querySelector('#phaseComparisonBody tr.pc-caption small.pc-divisors');
  const cell=document.querySelector('#phaseComparisonBody tr[data-block="costs"]:not(.pc-block) td');
  if(cap){const cr=cap.getBoundingClientRect();
    res.caption={text:cap.innerText,visible:cap.offsetHeight>0,
      size:parseFloat(getComputedStyle(cap).fontSize),rowSize:parseFloat(getComputedStyle(cell).fontSize),
      left:cr.left-w.left,right:w.right-cr.right}}
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
    assert got["costs"] == _expected_costs(bundle), got["costs"]
    assert not got["hidden"], f"строки скрыты: {got['hidden']}"
    # Делитель виден подписью блока — мельче строки таблицы и в пределах
    # экрана, а не отдельной крупной строкой.
    cap = got.get("caption")
    assert cap and cap["visible"], got
    assert all(t in " ".join(cap["text"].split()) for t in DIVISORS), cap
    assert cap["size"] < cap["rowSize"], cap
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
          .filter(t=>!t.classList.contains('pc-block')&&!t.classList.contains('pc-caption')&&!t.classList.contains('pc-note')).map(t=>{
            const c=t.cells[0],s=getComputedStyle(c),n=getComputedStyle(t.cells[1]);
            return {label:c.innerText.trim(),cls:t.className,visible:t.offsetHeight>0,
              weight:+n.fontWeight,border:parseFloat(n.borderTopWidth),
              indent:parseFloat(s.paddingLeft)}})""")
        heads = page.evaluate("""()=>[...document.querySelectorAll(
          '#phaseComparisonBody tr.pc-block')].map(t=>t.offsetHeight>0&&t.innerText.trim())""")
        # Заголовок раздела против итога: размер шрифта, фон, цвет текста.
        look = page.evaluate("""()=>{
          const st=el=>{const s=getComputedStyle(el);return {size:parseFloat(s.fontSize),
            bg:s.backgroundColor,color:s.color,height:el.getBoundingClientRect().height}};
          return {head:st(document.querySelector('#phaseComparisonBody tr.pc-block th')),
            total:st(document.querySelector('#phaseComparisonBody tr.pc-total td'))}}""")
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
    # Раздел отличим от «Итого» с первого взгляда: крупнее и на своей
    # полосе (владелец, 29.09.2026: «теряются среди строк Итого»).
    head, total = look["head"], look["total"]
    assert head["size"] >= total["size"] + 1, look
    transparent = ("rgba(0, 0, 0, 0)", "transparent")
    assert head["bg"] not in transparent and head["bg"] != total["bg"], look
    assert head["color"] != total["color"], look
