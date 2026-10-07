"""Отчёт гостиницы — объектная рамка, наполненная гостиницей.

Владелец (07.10.2026): «Тизер и отчёт собираются криво. Не соответствуют типу
гостиницы по содержанию вообще». Гостиница получала жилую вёрстку
(«Продаваемая площадь 0 м²», «Распроданность до ввода», «Проект — продажи»),
а Equity IRR Отеля 1 печатался 191 %.

Проверки держат:

* решение движка — гостиница идёт рамкой «объект» (`report_layout.kind`) с
  девятью разделами, и каждый раздел наполнен гостиницей: номера, класс, ГНС,
  ADR, загрузка, RevPAR, USALI, CAPEX на номер, кредит, выход, NPV/IRR/PBP;
* один источник — числа разделов равны `finance.hotel` и смете движка;
* правило капитала (владелец: «как Отель 1»): пока кредит не погашен,
  свободный поток собственнику не уходит — он гасит долг;
* база ИРД, проекта, сетей и ввода у гостиницы — её ГНС (владелец);
* поверхности — страница (`page_blocks.run` и Chromium), тизер и бот.

Каждая проверка поверхности падает на подделке.

Запуск: python3 -m pytest tests/test_hotel_report_layout.py -q
"""

from __future__ import annotations

import copy
import io
import json
import re
import sys
import urllib.request
from datetime import date
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

import developaid_hotel_strategy as hs  # noqa: E402
import hotel_presets  # noqa: E402
import main as wrapper  # noqa: E402
from test_hotel_strategy import plan, run  # noqa: E402
from test_nonres_report_layout import (  # noqa: E402
    KEYS, TITLES, _drawn_mismatches, _in_order, _render_blocks)

core = wrapper.core

# Слова жилой вёрстки, которых в отчёте гостиницы быть не должно.
HOUSING_WORDS = ("Продаваем", "продаваем", "Распроданност", "эскроу", "ДДУ", "РВЭ", "МКД",
                 "квартир", "Проект — продажи", "LLCR", "БРИДЖ")

_CACHE: dict[tuple, dict] = {}


def _inputs(**over) -> tuple[dict, dict]:
    x = copy.deepcopy(core.DEFAULT_INPUTS)
    t = copy.deepcopy(core.TEP_DEFAULT)
    x["project_kind"] = "hotel"
    x = hotel_presets.apply_preset(x, "hotel1")
    x.update(over)
    return x, t


def _run(**over) -> dict:
    key = tuple(sorted(over.items()))
    if key not in _CACHE:
        x, t = _inputs(**over)
        _CACHE[key] = core.calculate(core.CalcRequest(inputs=x, tep=t, rates=[]))
    return _CACHE[key]


def _sections(result: dict) -> dict[str, dict]:
    return {s["key"]: s for s in result["report"]["object_report"]["sections"]}


def _block(section: dict, title: str) -> dict:
    return next(b for b in section["blocks"] if b.get("title") == title)


def _value(block: dict, label: str):
    return next(r["value"] for r in block["rows"] if r["label"] == label)


def _texts(result: dict) -> str:
    """Все подписи и текстовые значения отчёта гостиницы одной строкой."""
    out = []
    for section in result["report"]["object_report"]["sections"]:
        for row in section.get("brief") or []:
            out += [str(row["label"]), str(row["value"]) if row["unit"] == "text" else ""]
        for block in section.get("blocks") or []:
            out.append(str(block.get("title") or ""))
            for row in block.get("rows") or []:
                out += [str(row["label"]), str(row["value"]) if row["unit"] == "text" else ""]
            out += [str(c[1]) for c in block.get("columns") or []]
    for event in (_sections(result)["calendar"].get("calendar") or {}).get("events") or []:
        out.append(event["label"])
    return "\n".join(out)


# --- решение движка -----------------------------------------------------------

def test_a_hotel_gets_the_object_frame_with_nine_sections() -> None:
    result = _run()
    layout = result["report"]["layout"]
    assert layout["kind"] == core.REPORT_KIND_OBJECT
    assert [s["key"] for s in layout["sections"]] == KEYS
    assert [s["title"] for s in layout["sections"]] == TITLES
    assert result["report"]["object_report"]["hotel"] is True


def test_the_report_speaks_of_a_hotel_not_of_housing() -> None:
    text = _texts(_run())
    for word in HOUSING_WORDS:
        assert word not in text, word
    for word in ("Номерной фонд", "Класс гостиницы", "ADR", "RevPAR", "GOP", "EBITDA",
                 "CAPEX на номер", "FF&E", "Кредит гостиницы", "Стоимость выхода", "DPBP"):
        assert word in text, word


def test_the_housing_check_fails_on_a_forgery() -> None:
    result = copy.deepcopy(_run())
    _sections(result)["object"]["blocks"][0]["rows"][0]["label"] = "Продаваемая площадь"
    text = _texts(result)
    assert any(word in text for word in HOUSING_WORDS)


def test_an_empty_hotel_names_what_is_missing() -> None:
    x, t = _inputs()
    x["hotel_adr_rub"] = None
    result = core.calculate(core.CalcRequest(inputs=x, tep=t, rates=[]))
    sections = _sections(result)
    assert sections["decision"]["verdict"]["status"] == "not_available"
    assert "ADR" in sections["decision"]["verdict"]["text"]
    assert "ADR" in str(sections["income"]["brief"][0]["value"])


# --- один источник ------------------------------------------------------------

def test_the_decision_reads_the_hotel_numbers() -> None:
    result = _run()
    kpi = result["finance"]["hotel"]["kpi"]
    block = _block(_sections(result)["decision"], "Ключевые показатели")
    assert _value(block, "IRR проекта") == kpi["irr_project"]
    assert _value(block, "IRR собственного капитала") == kpi["irr_equity"]
    assert _value(block, "Собственный капитал — пик вложений") == kpi["equity_peak"]
    # Капитал проекта и гостиницы — одни деньги: IRR сводки тот же.
    assert result["summary"]["irr_equity"] == pytest.approx(kpi["irr_equity"], rel=1e-9)
    worst = cumulative = 0.0
    for value in result["cashflow"]["equity"]:
        cumulative += value
        worst = min(worst, cumulative)
    assert kpi["equity_peak"] == pytest.approx(-worst, rel=1e-9)


def test_the_capex_block_adds_up_to_the_hotel_capex() -> None:
    result = _run()
    block = _block(_sections(result)["costs"], "CAPEX гостиницы")
    articles = []
    for row in block["rows"]:
        if row["label"] == "Итого CAPEX с НДС":
            break
        articles.append(float(row["value"]))
    capex = result["finance"]["hotel"]["kpi"]["capex"]
    assert sum(articles) == pytest.approx(capex, rel=1e-9)
    assert _value(block, "Итого CAPEX с НДС") == pytest.approx(result["capex"]["total"], rel=1e-9)
    assert _value(block, "CAPEX на номер с НДС") == pytest.approx(capex / 320, rel=1e-9)


def test_income_and_usali_years_are_the_annual_rows_of_the_hotel() -> None:
    result = _run()
    hotel = result["finance"]["hotel"]
    income = _sections(result)["income"]
    block = _block(income, "Выручка по департаментам за срок")
    parts = sum(_value(block, label) for label in (
        "Выручка номерного фонда", "Выручка F&B", "Выручка прочих департаментов",
        "Льгота НДС на проживание"))
    assert parts == pytest.approx(hotel["totals"]["revenue"], rel=1e-9)
    years = _block(income, "Выручка по годам (USALI)")["years"]
    operating = [row for row in hotel["annual"] if row["rooms_available"]]
    assert [y["year"] for y in years] == [row["year"] for row in operating]
    assert [y["revenue"] for y in years] == [row["revenue"] for row in operating]
    costs = _block(_sections(result)["costs"], "Расходы и EBITDA по годам")["years"]
    assert [y["ebitda"] for y in costs] == [row["ebitda"] for row in operating]


def test_the_loan_years_end_with_the_engine_balance() -> None:
    result = _run()
    years = _block(_sections(result)["finance"], "Кредит по годам")["years"]
    assert sum(y["loan_draw"] for y in years) == pytest.approx(
        result["finance"]["hotel"]["totals"]["loan_draw"], rel=1e-9)
    assert years[-1]["loan_balance"] == pytest.approx(0.0, abs=1.0)


def test_the_calendar_runs_from_construction_to_exit() -> None:
    calendar = _sections(_run())["calendar"]["calendar"]
    labels = [e["label"] for e in calendar["events"]]
    for label in ("Строительство гостиницы", "Ввод гостиницы", "Выход на целевую загрузку",
                  "Эксплуатация", "Кредит гостиницы", "Выход: продажа гостиницы"):
        assert label in labels, label
    assert any(label.startswith("Стабилизированный год") for label in labels)
    assert not {"Старт продаж", "Продажи", "БРИДЖ", "РВЭ / РНВ", "Строительство ЖК"} & set(labels)
    groups = [e["group"] for e in calendar["events"]]
    assert "Продажи" not in groups


def test_sensitivity_moves_the_hotel_factors() -> None:
    x, t = _inputs()
    sensitivity = _sections(_run())["sensitivity"]["sensitivity"]
    assert sensitivity["metric"] == "npv_mln"
    assert {"hotel_adr_rub", "hotel_occ_target_pct", "hotel_exit_multiple"} <= set(
        sensitivity["parameters"])
    # Ставка капитализации у оценки мультипликатором не читается.
    assert "hotel_exit_cap_pct" not in sensitivity["parameters"]
    report = core.run_sensitivity(x, t, [], {}, metric="npv_mln", change_pct=10,
                                  parameters=["hotel_adr_rub"])
    item = report["items"][0]
    assert item["label"] == "ADR — средняя цена номера"
    assert item["high_result"] > report["base"]["value"] > item["low_result"]


# --- правило капитала: «как Отель 1» ------------------------------------------

def _paid_out_while_in_debt(flows: dict) -> list[date]:
    """Месяцы эксплуатации, когда собственник получил деньги, а кредит так и
    остался непогашенным (долг есть и на конец месяца). Месяц погашения
    отдаёт остаток удержанного — он не в счёт, как и выход в конце срока."""
    balance = flows["monthly"].get("loan_balance") or {}
    return [month for month, value in zip(flows["months"], flows["equity_cf"])
            if flows["commissioning"] <= month < flows["horizon_end"]
            and balance.get(month, 0.0) > 1.0 and value > 1.0]


def test_nothing_goes_to_the_owner_while_the_loan_is_outstanding() -> None:
    flows = run(plan(params={**plan()["params"], "loan_share_pct": 90, "grace_months": 30,
                             "repayment": "sculpted", "dscr_target": 1.2, "hold_years": 8}))
    assert flows["kpi"]["loan_repaid_month"] is not None
    assert _paid_out_while_in_debt(flows) == []
    # Удержанное в отсрочку гасит долг досрочно, как только погашение разрешено.
    assert sum((flows["monthly"].get("loan_cash_sweep") or {}).values()) > 0
    # После погашения капитал получает деньги.
    repaid = date.fromisoformat(str(flows["kpi"]["loan_repaid_month"])[:10])
    after = [v for mm, v in zip(flows["months"], flows["equity_cf"]) if mm > repaid]
    assert max(after) > 0


def test_the_owner_rule_check_fails_on_a_forgery() -> None:
    flows = run(plan(params={**plan()["params"], "loan_share_pct": 90, "grace_months": 30}))
    forged = copy.deepcopy(flows)
    month = next(mm for mm in forged["months"] if mm >= forged["commissioning"])
    index = forged["months"].index(month)
    forged["equity_cf"][index] = 1_000_000.0
    assert _paid_out_while_in_debt(forged) == [month]


def test_the_retained_cash_is_the_owner_money_not_lost() -> None:
    """Удержание не съедает денег: поток капитала за срок равен потоку проекта
    до финансирования минус уплаченные проценты и комиссии плюс выдача минус
    погашение — удержанное за срок возвращается собственнику целиком."""
    flows = run(plan(params={**plan()["params"], "loan_share_pct": 90, "grace_months": 30}))
    totals, monthly = flows["totals"], flows["monthly"]
    assert sum(monthly.get("cash_retained", {}).values()) == pytest.approx(0.0, abs=1e-3)
    assert sum(flows["equity_cf"]) == pytest.approx(
        sum(monthly["fcff"].values()) - sum(monthly["loan_interest_paid"].values())
        - totals["loan_fee"] + totals["loan_draw"] - totals["loan_repayment"], rel=1e-9)
    assert totals["loan_draw"] == pytest.approx(totals["loan_repayment"]
                                                - sum(flows["monthly"]["loan_interest_cap"].values()),
                                                rel=1e-6)


def test_hotel1_equity_irr_is_no_longer_191_percent() -> None:
    kpi = _run()["finance"]["hotel"]["kpi"]
    assert 0.2 < kpi["irr_equity"] < 1.0
    assert kpi["equity_pbp_years"] > 6


# --- база удельных статей ------------------------------------------------------

def test_project_articles_of_a_hotel_are_counted_from_its_gns() -> None:
    result = _run()
    x, _ = _inputs()
    for article in ("ird", "design_p", "design_rd", "preparation", "utilities",
                    "commissioning", "site_maintenance"):
        expected = x["hotel_gba_sqm"] * x[f"{article}_th_per_sqm"] * 1000
        assert result["capex"][article] == pytest.approx(expected, rel=1e-9), article
        assert expected > 0


# --- страница: page_blocks ----------------------------------------------------

def test_the_page_prints_the_hotel_sections_of_the_engine() -> None:
    report = _run()["report"]
    drawn = _render_blocks(report)
    assert list(drawn) == KEYS[:7]
    assert _drawn_mismatches(drawn, report) == []
    assert "18 357 ₽" in drawn["strategy"].replace(" ", " ").replace(" ", " ")
    assert "object-years" in drawn["income"]


def test_the_page_check_fails_on_a_forgery() -> None:
    report = _run()["report"]
    drawn = _render_blocks(report)
    forged = dict(drawn)
    forged["decision"] = re.sub(r"(<td>IRR проекта</td><td>)[^<]+", r"\g<1>99%", drawn["decision"])
    forged["costs"] = drawn["costs"].replace("Здание — ГНС × ставка стройки", "Основное строительство", 1)
    assert len(_drawn_mismatches(forged, report)) == 2


# --- страница: браузер --------------------------------------------------------

PORT = 18993

READ = r"""() => {
  openTab('report', null);
  const seen = el => el && el.offsetParent !== null;
  const sections = [...document.querySelectorAll('#report .report-section')].filter(seen)
    .map(s => ({id: s.id, title: s.querySelector('.report-section-title').textContent.trim(),
                text: s.innerText}));
  return {sections, toc: [...document.querySelectorAll('#reportToc a')].map(a => a.textContent.trim()),
          dates: [...document.querySelectorAll('#reportCalendarDates .datebox')].map(x => x.innerText),
          gantt: [...document.querySelectorAll('#reportCalendarGantt .gantt-label')]
            .map(x => x.textContent.trim()),
          sensParams: [...document.querySelectorAll('#sensitivityParams input:checked')]
            .map(x => x.value)};
}"""


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
            page.evaluate("() => { applyProjectKind('hotel'); closeProjectKindDialog(); }")
            page.wait_for_function("() => lastResult.report && lastResult.report.hotel")
            page.evaluate(
                "() => document.querySelector('.hotel-preset[data-preset=hotel1] button').click()")
            page.wait_for_function(
                "() => lastResult.report.object_report && lastResult.report.object_report.hotel"
                " && lastResult.report.hotel.computed")
            out["hotel"] = page.evaluate(READ)
            out["errors"] = errors
            page.close()
    return out


def test_the_rendered_hotel_page_reads_as_nine_sections(walk) -> None:
    state = walk["hotel"]
    assert [s["title"] for s in state["sections"]] == TITLES
    assert state["toc"] == TITLES
    # Заголовки блоков страница пишет прописными (CSS) — сравнение без регистра.
    text = "\n".join(s["text"] for s in state["sections"]).lower()
    for word in (w.lower() for w in HOUSING_WORDS):
        assert word not in text, word
    for word in ("Номерной фонд", "RevPAR", "CAPEX на номер с НДС", "Кредит по годам",
                 "Выход на загрузку по годам"):
        assert word.lower() in text, word
    dates = [d.lower() for d in state["dates"]]
    assert any("ввод гостиницы" in d for d in dates), dates
    assert not any("старт продаж" in d or "рвэ" in d for d in dates)
    assert walk["errors"] == []


# --- PDF ----------------------------------------------------------------------

@pytest.fixture(scope="module")
def hotel_pdf() -> str:
    pypdf = pytest.importorskip("pypdf")
    x, t = _inputs()
    data = core._build_developaid_pdf({"result": _run(), "inputs": x, "tep": t, "rates": [],
                                       "phasing": {}, "scenario": "base",
                                       "project_name": "Гостиница"})
    return "\n".join(p.extract_text() or "" for p in pypdf.PdfReader(io.BytesIO(data)).pages)


# Жилые разделы и строки, которые владелец нашёл в PDF гостиницы.
PDF_HOUSING = ("Удельная экономика", "Оценка целесообразности покупки",
               "Удельные расходы строительства", "Продажи и продукты", "Осталось от жилья",
               "Базы удельных", "Продаваемая", "эскроу", "РВЭ", "МКД", "LLCR")


def test_the_pdf_follows_the_hotel_sections(hotel_pdf) -> None:
    assert _in_order(hotel_pdf, TITLES[:7]) == []
    flat = " ".join(hotel_pdf.split())
    for word in PDF_HOUSING:
        assert word not in flat, word
    for word in ("Номерной фонд", "CAPEX на номер с НДС", "Условия кредита гостиницы",
                 "Кредит по годам", "Потоки по годам", "Выход на загрузку по годам"):
        assert word in flat, word
    # «Финансирование» гостиницы печатает свои блоки, а не одну оговорку.
    finance = hotel_pdf[hotel_pdf.index("\nФинансирование\n"):hotel_pdf.index("Экономика собственника")]
    assert "Кредит по годам" in finance and "Пик долга" in finance


def test_the_pdf_check_fails_on_a_forgery(hotel_pdf) -> None:
    forged = hotel_pdf.replace("Номерной фонд", "Продаваемая площадь", 1)
    assert any(word in " ".join(forged.split()) for word in PDF_HOUSING)
    swapped = hotel_pdf.replace("\nДоходы\n", "\n§\n", 1).replace("\nЗатраты\n", "\nДоходы\n", 1)
    assert _in_order(swapped, TITLES[:7]) != []


# --- тизер и бот --------------------------------------------------------------

def test_the_teaser_prints_the_hotel_sections(tmp_path) -> None:
    pypdf = pytest.importorskip("pypdf")
    x, t = _inputs()
    bundle = core._run_authoritative_model(x, t, [], {})
    data = core.build_teaser_pdf(bundle, x, t, {})
    text = "\n".join(p.extract_text() or "" for p in pypdf.PdfReader(io.BytesIO(data)).pages)
    assert _in_order(text, TITLES) == []
    flat = " ".join(text.split())
    for word in ("Продаваемая площадь", "Распроданность", "Срок до РВЭ", "Проект — продажи"):
        assert word not in flat, word
    assert "Номерной фонд" in flat and "Ввод гостиницы" in flat
    # ADR и затраты на номер — рублями с разрядами, а не сырым числом.
    assert re.search(r"18 357 ₽", flat.replace(" ", " ")), flat[:2000]
    assert "18356.94" not in flat


def test_the_bot_card_lists_the_hotel_sections(monkeypatch) -> None:
    x, t = _inputs()
    layout = core._run_authoritative_model(x, t, [], {})["consolidated"]["report"]["layout"]
    sent: list[str] = []
    monkeypatch.setattr(core, "_telegram_verify_session", lambda s: {"chat_id": 42, "cad": []})
    monkeypatch.setattr(core, "_telegram_user_allowed", lambda c: True)
    monkeypatch.setattr(core, "_telegram_send_message", lambda chat_id, text, **kw: sent.append(text))
    monkeypatch.setattr(core, "_telegram_web_app_url", lambda *a, **k: "https://example.org/")
    core.telegram_result(core.TelegramResultRequest(session="s", summary={
        "purchase_price_mln": 0, "net_profit_mln": 0, "llcr": 0.0, "layout": layout}))
    text = sent[0]
    assert re.findall(r"<b>\d+\. ([^<]+)</b>", text) == TITLES
    assert "Номерной фонд" in text and "18 357 ₽" in text.replace(" ", " ")
