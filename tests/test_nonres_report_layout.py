"""Своя вёрстка отчёта проекта без жилья — девять разделов владельца.

Владелец (05.10.2026): «вёрстка нежилых объектов, где они не идут в проекте с
жильём, должна быть своей». Прежде нежилой отчёт был жилым, из которого
`report_layout` прятал квартиры, эскроу, БРИДЖ, ПФ и LLCR, — разделы
оставались жилыми, а стройка офиса стояла «общими» строками «Основное
строительство», «Технический заказчик», «Резерв».

Проверки держат:

* решение движка — какую вёрстку выбирать (`report_layout.kind`) и какие
  разделы в ней (`report_layout.sections`); жилой и смешанный не меняются;
* один источник — числа разделов равны величинам движка, смета объекта и
  общие затраты складываются в CAPEX, ОПУ сходится к чистой прибыли;
* поверхности — отрисованная страница (playwright и `page_blocks.run`),
  PDF и тизер по извлечённому тексту и порядку разделов, карточка бота.

Каждая проверка страницы падает на подделке.

Запуск: python3 -m pytest tests/test_nonres_report_layout.py -q
"""

from __future__ import annotations

import copy
import html
import io
import json
import re
import sys
import urllib.request
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

import main as wrapper  # noqa: E402
import page_blocks  # noqa: E402
from test_nonres_debt_metric import _nonres_inputs  # noqa: E402
from test_nonres_object_result import _spec  # noqa: E402

core = wrapper.core

TITLES = ["Решение", "Объект и участок", "Стратегия реализации", "Доходы", "Затраты",
          "Финансирование", "Экономика собственника", "Чувствительность", "Календарь"]
KEYS = ["decision", "object", "strategy", "income", "costs", "finance", "owner",
        "sensitivity", "calendar"]

_CACHE: dict[tuple, dict] = {}


def _two_objects(**over) -> tuple[dict, dict]:
    """Проект без жилья: офисы в аренду и ТЦ на продажу ДКП, участок куплен."""
    x, t = _spec(purchase_price_mln=1500, **over)
    for key in core.MKD_PRODUCTS:
        for col in ("gns", "total_area", "useful", "saleable", "transfer", "units"):
            if key in t:
                t[key][col] = 0
    x["project_kind"] = core.PROJECT_KIND_NONRESIDENTIAL
    return x, t


def _run(kind: str = "two", **over) -> dict:
    key = (kind, *sorted(over.items()))
    if key not in _CACHE:
        x, t = _two_objects(**over) if kind == "two" else _nonres_inputs(**over)
        _CACHE[key] = core.calculate(core.CalcRequest(inputs=x, tep=t, rates=[]))
    return _CACHE[key]


def _sections(result: dict) -> dict[str, dict]:
    return {s["key"]: s for s in result["report"]["object_report"]["sections"]}


def _block(section: dict, title: str) -> dict:
    return next(b for b in section["blocks"] if b.get("title") == title)


def _values(block: dict) -> dict[str, object]:
    return {r["label"]: r["value"] for r in block.get("rows") or []}


# --- решение движка -----------------------------------------------------------

def test_a_project_without_housing_gets_its_own_nine_sections() -> None:
    layout = _run()["report"]["layout"]
    assert layout["kind"] == core.REPORT_KIND_OBJECT
    assert [s["key"] for s in layout["sections"]] == KEYS
    assert [s["title"] for s in layout["sections"]] == TITLES
    assert all(s["brief"] for s in layout["sections"])
    report = _run()["report"]["object_report"]
    assert [s["key"] for s in report["sections"]] == KEYS


@pytest.mark.parametrize("over", [
    {},  # жильё по умолчанию
    {"offices_enabled": True, "offices_gba_sqm": 40000.0, "offices_saleable_sqm": 24000.0,
     "offices_strategy": "income"},  # смешанный: жильё и офис вне ДДУ
])
def test_housing_and_mixed_projects_keep_their_report(over) -> None:
    x = copy.deepcopy(core.DEFAULT_INPUTS)
    t = copy.deepcopy(core.TEP_DEFAULT)
    x.update(over)
    if over:
        x, t = _spec(**over)
    result = core.calculate(core.CalcRequest(inputs=x, tep=t, rates=[]))
    layout = result["report"]["layout"]
    assert layout["kind"] == core.REPORT_KIND_HOUSING
    assert [s["key"] for s in layout["sections"]] == [
        "site", "summary", "phases", "expenses", "income", "finance", "sensitivity", "calendar"]
    assert result["report"]["object_report"] == {}


def test_a_nonresidential_object_sold_by_ddu_is_judged_as_before() -> None:
    # ДДУ — эскроу и ПФ: банковский отчёт, своей вёрстки нет.
    result = _run(offices_strategy="ddu", retail_strategy="ddu")
    assert result["report"]["layout"]["kind"] == core.REPORT_KIND_HOUSING


# --- один источник ------------------------------------------------------------

def test_the_object_estimate_and_the_common_costs_add_up_to_the_capex() -> None:
    result = _run()
    costs = _sections(result)["costs"]
    estimates = [b for b in costs["blocks"] if str(b.get("title", "")).startswith("Смета объекта")]
    assert {b["title"] for b in estimates} == {"Смета объекта — Офисы", "Смета объекта — Коммерция ОСЗ"}
    total = sum(_values(b)["Итого смета объекта"] for b in estimates)
    common = _values(_block(costs, "Общие затраты проекта — участок, ИРД, проект, сети"))
    assert total + common["Итого общие затраты"] == pytest.approx(result["capex"]["total"], rel=1e-9)
    # Части сметы объекта — его статья плюс начисленное от неё.
    for block in estimates:
        rows = _values(block)
        parts = sum(v for k, v in rows.items() if k not in (
            "Итого смета объекта", "на м² наземной ГНС объекта", "на м² арендопригодной / продаваемой"))
        assert parts == pytest.approx(rows["Итого смета объекта"])
    # Генподряд и техзаказчик проекта без жилья — целиком доли объектов:
    # «общими» строками их нет. Резерв — доля объекта со своей стройки, а
    # резерв на статьи проекта (полная смета нежилого, 06.10.2026) — общей
    # строкой «Резерв — вне объектов»; вместе — резерв проекта.
    for key in ("gc_fee", "technical_supervision"):
        assert sum(p[key] for p in result["object_costs"].values()) == pytest.approx(result["capex"][key])
    assert not {"Вознаграждение генподрядчика — вне объектов",
                "Технический заказчик — вне объектов"} & set(common)
    reserve_objects = sum(p["reserve"] for p in result["object_costs"].values())
    assert reserve_objects + common["Резерв — вне объектов"] == pytest.approx(result["capex"]["reserve"])
    assert common["Участок — стоимость сделки"] == pytest.approx(1500e6)


def test_the_estimate_follows_the_cost_scenario() -> None:
    base, dear = _run(), _run(scenario_cost_multiplier=1.1)
    for key, parts in base["object_costs"].items():
        for name, value in parts.items():
            assert dear["object_costs"][key][name] == pytest.approx(value * 1.1)


def test_the_income_statement_reaches_the_net_profit_of_the_engine() -> None:
    result = _run()
    s = result["summary"]
    pnl = _values(_block(_sections(result)["owner"], "Отчёт о прибылях и убытках"))
    assert pnl["Выручка"] - pnl["Затраты стройки (смета объектов и общие)"] \
        - pnl["Эксплуатация, налог на имущество, продажа и выход"] \
        - pnl.get("Коммерческие расходы", 0.0) == pytest.approx(pnl["EBITDA"], rel=1e-9)
    assert pnl["EBITDA"] - pnl["Проценты и комиссии"] == pytest.approx(pnl["Прибыль до налога"])
    assert pnl["Прибыль до налога"] - pnl["Налог на прибыль"] - pnl["НДС к уплате"] \
        == pytest.approx(pnl["Чистая прибыль"])
    assert pnl["Чистая прибыль"] == s["net_profit"] and pnl["EBITDA"] == s["ebitda"]


def test_the_decision_reads_the_engine() -> None:
    result = _run()
    decision = _sections(result)["decision"]
    rows = _values(_block(decision, "Ключевые показатели"))
    layout, equity = result["report"]["layout"], result["report"]["equity_participation"]
    metric = layout["debt_metric"]
    assert rows[metric["label"]] == metric["value"]
    assert rows["IRR собственника"] == result["summary"]["irr_equity"]
    assert rows["NPV собственника @20%"] == equity["npv"]
    assert rows["Пик собственных средств"] == equity["peak"]
    assert rows["Чистая прибыль проекта"] == result["summary"]["net_profit"]
    verdict = core._purchase_feasibility(
        1500, result["summary"]["net_profit"] / 1e6, 0.0, 0.0, 0.0, None, 0.0, None,
        core._layout_dscr(layout), core._layout_no_debt_cover(layout))
    assert decision["verdict"] == verdict
    assert decision["goal_seek"]["metric"] == metric["key"]


def test_strategy_and_income_come_from_the_object_rows() -> None:
    result = _run()
    sections = _sections(result)
    objects = {o["title"]: o for o in result["finance"]["nonres"]["objects"]}
    offices = _values(_block(sections["strategy"], "Офисы"))
    assert offices["Ставка аренды"] == 4.5 and offices["Выход"] == "Продажа по ставке капитализации"
    retail = _values(_block(sections["strategy"], "Коммерция ОСЗ"))
    assert retail["Стартовая цена ДКП"] == pytest.approx(450.0)
    years = _block(sections["income"], "По годам — Офисы")["years"]
    assert sum(y["noi"] for y in years) == pytest.approx(objects["Офисы"]["totals"]["noi"])
    assert sum(y["rent_revenue"] for y in years) == pytest.approx(objects["Офисы"]["totals"]["rent_revenue"])
    sold = _block(sections["strategy"], "График продаж — Коммерция ОСЗ")["years"]
    assert sold[-1]["sold_share"] == pytest.approx(1.0)


def test_the_calendar_has_no_escrow_milestones() -> None:
    events = _sections(_run())["calendar"]["calendar"]["events"]
    labels = [e["label"] for e in events]
    assert not {"Старт продаж", "РВЭ / РНВ", "Окончание продаж", "Продажи"} & set(labels)
    assert {"Заполнение — Офисы", "Аренда — Офисы", "Выход: продажа — Офисы",
            "Продажи ДКП — Коммерция ОСЗ", "Кредит объекта — Офисы"} <= set(labels)


def test_sensitivity_moves_the_factors_of_the_objects() -> None:
    sensitivity = _sections(_run())["sensitivity"]["sensitivity"]
    assert sensitivity["metric"] == "dscr"
    keys = set(sensitivity["parameters"])
    assert {"offices_rent_th_per_sqm_month", "offices_occupancy_stable_pct", "offices_exit_cap_pct",
            "retail_price_th_per_sqm", "offices_loan_spread_pp", "purchase_price_mln"} <= keys
    # Цены квартир у проекта без жилья нет, и аренды у проданного ТЦ — тоже.
    assert not {"apartment_price_th", "retail_rent_th_per_sqm_month", "offices_price_th_per_sqm"} & keys
    x, t = _two_objects()
    report = core.run_sensitivity(x, t, [], {}, metric="dscr", change_pct=10,
                                  parameters=["offices_rent_th_per_sqm_month"])
    item = report["items"][0]
    assert item["label"] == "Ставка аренды — офисы"
    assert item["high_result"] > report["base"]["value"] > item["low_result"]


# --- страница: page_blocks ----------------------------------------------------

def _render_blocks(report: dict) -> dict:
    prelude = "const inputs={site_area_ha:1.5,cadastral_numbers:'77:01:0001001:1'};\nconst R=%s;\n" % (
        json.dumps({"report": report}, ensure_ascii=False))
    tail = r"""
const rep=objectReportOf(R);
const out=rep.sections.filter(s=>!OBJECT_SHARED_SECTIONS[s.key]).map(s=>({key:s.key,
 html:s.blocks.map(b=>objectBlockHtml(b,s)).join('')}));
console.log(JSON.stringify(out));
"""
    out, _ = page_blocks.run(prelude, tail)
    return {item["key"]: item["html"] for item in json.loads(out)}


def _cells(markup: str) -> list[tuple[str, str]]:
    """Строки таблиц движка (`object-rows`); участок из вводных — своя таблица."""
    tables = "".join(re.findall(r'<table class="nonres-strategy object-rows">[\s\S]*?</table>', markup))
    # Подписи с «&» (F&B, FF&E) страница экранирует — сравниваем текст.
    return [(html.unescape(re.sub("<[^>]+>", "", a)), html.unescape(re.sub("<[^>]+>", "", b)))
            for a, b in
            re.findall(r"<tr(?: class=\"section\")?><td>([\s\S]*?)</td><td>([\s\S]*?)</td></tr>",
                       tables)]


_SCALE = {"млрд ₽": 1e9, "млн ₽": 1e6, "тыс ₽/м²": 1.0, "м²": 1.0, "x": 1.0, "%": 0.01}


def _number(text: str) -> tuple[float, float]:
    """Напечатанное число и полшага его последнего знака — в единицах движка."""
    clean = text.replace(" ", " ").replace(" ", " ").strip()
    unit = next((u for u in _SCALE if clean.endswith(u)), "")
    digits = clean[:len(clean) - len(unit)].strip().replace(" ", "").replace(",", ".").replace("−", "-")
    step = 10 ** -len(digits.split(".")[1]) if "." in digits else 1.0
    return float(digits) * _SCALE[unit], step / 2 * _SCALE[unit] + 1e-9


def _drawn_mismatches(drawn: dict[str, str], report: dict) -> list[str]:
    """Что напечатала страница против строк движка: подписи по порядку и числа
    — разбором напечатанного, а не формулой страницы."""
    out = []
    for section in report["object_report"]["sections"]:
        if section["key"] not in drawn:
            continue
        cells = _cells(drawn[section["key"]])
        rows = [r for b in section["blocks"] if not b.get("ref") and b.get("kind") != "verdict"
                for r in b.get("rows") or []]
        if [c[0] for c in cells] != [r["label"] for r in rows]:
            out.append(f"{section['key']}: строки не те")
            continue
        for (label, cell), row in zip(cells, rows):
            if row["unit"] in ("rub", "sqm", "th", "mult", "pct") and row["value"] is not None:
                value, tolerance = _number(cell)
                if abs(value - float(row["value"])) > tolerance:
                    out.append(f"{section['key']}: {label} — {cell} вместо {row['value']}")
            elif row["unit"] == "text" and cell != str(row["value"]):
                out.append(f"{section['key']}: {label} — {cell}")
    return out


def test_the_page_prints_the_sections_of_the_engine() -> None:
    report = _run()["report"]
    drawn = _render_blocks(report)
    assert list(drawn) == KEYS[:7]
    assert _drawn_mismatches(drawn, report) == []
    verdict = _sections(_run())["decision"]["verdict"]
    assert verdict["title"] in drawn["decision"]
    assert "data-nonres-finance-card" in drawn["finance"] and "data-equity-card" in drawn["finance"]
    assert "Площадь участка" in drawn["object"] and "77:01:0001001:1" in drawn["object"]


def test_the_page_check_fails_on_a_forgery() -> None:
    report = _run()["report"]
    drawn = _render_blocks(report)
    forged = dict(drawn)
    forged["costs"] = drawn["costs"].replace("Резерв — доля объекта", "Резерв", 1)
    forged["owner"] = re.sub(r"(<td>EBITDA</td><td>)[^<]+", r"\g<1>0,00 млрд ₽", drawn["owner"])
    assert len(_drawn_mismatches(forged, report)) == 2


# --- страница: браузер --------------------------------------------------------

PORT = 18991

SET = r"""([id, value]) => {
  const el = document.querySelector(`[data-field="${id}"] input, [data-field="${id}"] select`);
  if (el.type === 'checkbox') el.checked = value; else el.value = value;
  el.onchange();
}"""

READ = r"""() => {
  openTab('report', null);
  const seen = el => el && el.offsetParent !== null;
  const sections = [...document.querySelectorAll('#report .report-section')].filter(seen)
    .map(s => ({id: s.id, title: s.querySelector('.report-section-title').textContent.trim(),
                rows: [...s.querySelectorAll('table.object-rows tr')].filter(seen)
                  .map(tr => [...tr.cells].map(c => c.innerText.trim()))}));
  return {sections, toc: [...document.querySelectorAll('#reportToc a')].map(a => a.textContent.trim()),
          financeTables: [...document.querySelectorAll('#rsObj-finance table.nonres-finance')]
            .filter(seen).map(t => t.dataset.object),
          equity: seen(document.querySelector('#rsObj-finance .equity-box table')),
          housingShown: ['rsSite', 'rsSummary', 'rsExpenses', 'rsIncome', 'rsFinance']
            .filter(id => seen(document.getElementById(id))),
          gantt: [...document.querySelectorAll('#reportCalendarGantt .gantt-label.group')]
            .map(x => x.textContent.trim()),
          inputs, tep};
}"""


def _post(base: str, payload: dict) -> dict:
    request = urllib.request.Request(
        base.rstrip("/") + "/calculate", data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(request, timeout=120) as response:
        return json.loads(response.read().decode("utf-8"))


@pytest.fixture(scope="module")
def walk() -> dict:
    pytest.importorskip("playwright.sync_api")
    from playwright.sync_api import sync_playwright
    import browser

    path = browser.chromium_or_skip()
    out: dict = {}
    with browser.serve(core.app, PORT) as base, sync_playwright() as pw:
        with pw.chromium.launch(executable_path=str(path)) as engine:
            page = engine.new_page(viewport={"width": 1440, "height": 900})
            errors: list[str] = []
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.goto(base, wait_until="domcontentloaded")
            page.wait_for_function("() => typeof lastResult !== 'undefined' && lastResult")
            out["housing"] = page.evaluate(READ)
            page.evaluate(SET, ["offices_enabled", True])
            page.wait_for_function("() => lastResult && lastResult.revenue.offices > 0")
            page.evaluate("() => { applyProjectKind('nonresidential'); closeProjectKindDialog(); }")
            page.evaluate(SET, ["offices_strategy", "income"])
            page.wait_for_function("() => lastResult.report.layout && lastResult.report.layout.kind === 'object'")
            state = page.evaluate(READ)
            state["engine"] = _post(base, {"inputs": state["inputs"], "tep": state["tep"], "rates": []})
            out["object"] = state
            out["errors"] = errors
            page.close()
    return out


def test_the_rendered_page_reads_as_nine_sections(walk) -> None:
    state = walk["object"]
    titles = [s["title"] for s in state["sections"]]
    assert titles == TITLES
    assert state["toc"] == TITLES
    assert state["housingShown"] == []
    assert state["financeTables"] == ["offices"] and state["equity"] is True
    assert "Аренда" in state["gantt"] and "Выход" in state["gantt"]
    assert walk["errors"] == []


def test_the_rendered_numbers_are_the_engine_numbers(walk) -> None:
    state, engine = walk["object"], walk["object"]["engine"]
    drawn = {s["id"].removeprefix("rsObj-"): '<table class="nonres-strategy object-rows">' + "".join(
        f"<tr><td>{a}</td><td>{b}</td></tr>" for a, b in (r for r in s["rows"] if len(r) == 2))
        + "</table>" for s in state["sections"] if s["id"].startswith("rsObj-")}
    assert _drawn_mismatches(drawn, engine["report"]) == []
    estimate = next(r for r in state["sections"] if r["id"] == "rsObj-costs")["rows"]
    assert ["Вознаграждение генподрядчика — доля объекта", ] == [
        r[0] for r in estimate if r[0].startswith("Вознаграждение генподрядчика")]


def test_a_housing_project_keeps_its_page(walk) -> None:
    state = walk["housing"]
    assert [s["id"] for s in state["sections"]][:2] == ["rsSite", "rsSummary"]
    assert not any(s["id"].startswith("rsObj-") for s in state["sections"])
    assert "Решение" not in state["toc"]


# --- PDF ----------------------------------------------------------------------

def _pdf_text(result: dict, inputs: dict, tep: dict) -> str:
    pypdf = pytest.importorskip("pypdf")
    data = core._build_developaid_pdf({"result": result, "inputs": inputs, "tep": tep, "rates": [],
                                       "phasing": {}, "scenario": "base", "project_name": "Офисы"})
    return "\n".join(p.extract_text() or "" for p in pypdf.PdfReader(io.BytesIO(data)).pages)


def _in_order(text: str, titles: list[str]) -> list[str]:
    """Заголовки, которых нет на своём месте: каждый ищется строкой после
    предыдущего."""
    missing, at = [], 0
    lines = text.splitlines()
    for title in titles:
        index = next((i for i in range(at, len(lines)) if lines[i].strip() == title), None)
        if index is None:
            missing.append(title)
        else:
            at = index + 1
    return missing


@pytest.fixture(scope="module")
def object_pdf() -> str:
    x, t = _two_objects()
    return _pdf_text(_run(), x, t)


def test_the_pdf_follows_the_nine_sections(object_pdf) -> None:
    assert _in_order(object_pdf, TITLES[:7]) == []
    assert "Чувствительность" in object_pdf and "Календарь" in object_pdf
    assert object_pdf.index("Экономика собственника") < object_pdf.index("Чувствительность не рассчитана")
    for housing in ("Ключевая экономика", "Удельная экономика проекта", "Цены и основные предпосылки",
                    "Продажи и продукты", "Класс жилья"):
        assert housing not in object_pdf
    assert "Вознаграждение генподрядчика — доля объекта" in object_pdf


def test_the_pdf_order_check_fails_on_a_forgery(object_pdf) -> None:
    swapped = object_pdf.replace("\nДоходы\n", "\n§\n", 1).replace("\nЗатраты\n", "\nДоходы\n", 1)
    assert _in_order(swapped, TITLES[:7]) != []


# --- тизер и бот --------------------------------------------------------------

def test_the_teaser_prints_the_same_sections(tmp_path) -> None:
    pypdf = pytest.importorskip("pypdf")
    x, t = _two_objects()
    bundle = core._run_authoritative_model(x, t, [], {})
    path = tmp_path / "teaser.pdf"
    path.write_bytes(core.build_teaser_pdf(bundle, x, t, {}))
    pages = pypdf.PdfReader(str(path)).pages
    assert len(pages) == 2
    text = "\n".join(p.extract_text() or "" for p in pages)
    assert _in_order(text, TITLES) == []
    verdict = _sections(bundle["consolidated"])["decision"]["verdict"]["title"]
    assert verdict in " ".join(text.split())
    assert "LLCR" not in text and "Удельная экономика" not in text


def test_the_bot_card_lists_the_sections_in_order(monkeypatch) -> None:
    x, t = _two_objects()
    layout = core._run_authoritative_model(x, t, [], {})["consolidated"]["report"]["layout"]
    sent: list[str] = []
    monkeypatch.setattr(core, "_telegram_verify_session", lambda s: {"chat_id": 42, "cad": []})
    monkeypatch.setattr(core, "_telegram_user_allowed", lambda c: True)
    monkeypatch.setattr(core, "_telegram_send_message", lambda chat_id, text, **kw: sent.append(text))
    monkeypatch.setattr(core, "_telegram_web_app_url", lambda *a, **k: "https://example.org/")
    core.telegram_result(core.TelegramResultRequest(session="s", summary={
        "purchase_price_mln": 1500, "net_profit_mln": 900, "llcr": 0.0, "layout": layout}))
    text = sent[0]
    heads = re.findall(r"<b>\d+\. ([^<]+)</b>", text)
    assert heads == TITLES
    decision = next(s for s in layout["sections"] if s["key"] == "decision")
    assert f"• <b>{decision['brief'][0]['value']}</b>" in text
    assert "LLCR" not in text and "квартиры" not in text and "Оценка целесообразности" not in text
