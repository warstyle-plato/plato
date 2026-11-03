"""NPV и IRR проекта — числом и при непогашенном долге; «N/A» — только у капитала.

Решение владельца 17.10.2026 («Проект — числом»): NPV и IRR проекта считаются
по потоку до финансирования, кредита в нём нет, и остаток ПФ к концу проекта им
не мешает. Правило 2 от 29.09.2026 («N/A — долг не погашен») остаётся только
у доходности капитала: IRR и NPV собственного капитала.

Решает одна функция движка (`_apply_equity_returns_verdict`): она пишет
`summary.equity_returns` и снимает `npv_equity`/`irr_equity`, а `npv` и
`irr_project` не трогает. Читатели строк проекта печатают число и признак не
читают: классика, карточка решения, сводка для бота и Telegram, тизер, Платон,
книга нежилого проекта, Дашборд книги v4.

Каждая проверка падает на прежнем коде: там у Нагатино и умолчаний `npv` и
`irr_project` были None, а поверхности писали «N/A — долг не погашен».

Запуск: python3 -m pytest tests/test_project_returns_are_a_number_when_the_debt_is_unpaid.py -q
"""

from __future__ import annotations

import copy
import io
import json
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(ROOT / "scripts"))

import main as _wrapper  # noqa: E402
import page_blocks  # noqa: E402

core = _wrapper.core
LABEL = "N/A — долг не погашен"
OVERLAY = (ROOT / "ia_preview" / "assets" / "overlay.js").read_text(encoding="utf-8")


def _unpaid(summary: dict) -> None:
    """Стенд про непогашенный долг: иначе проверка пуста."""
    assert float(summary["ending_pf"]) > core.EQUITY_RETURNS_UNREPAID_DEBT_MIN_RUB, \
        "стенд не про непогашенный долг"
    assert summary["equity_returns"]["status"] == "debt_unrepaid"


def _project_is_a_number(summary: dict) -> None:
    assert isinstance(summary["npv"], float), summary.get("npv")
    assert isinstance(summary["irr_project"], float), summary.get("irr_project")
    assert summary["npv_equity"] is None and summary["irr_equity"] is None
    assert summary["equity_returns"]["label"] == LABEL
    assert core.equity_irr_label(summary) == LABEL


@pytest.fixture(scope="module")
def defaults() -> dict:
    """Умолчания: ПФ к концу проекта не погашен."""
    return core._run_authoritative_model(copy.deepcopy(core.DEFAULT_INPUTS),
                                         copy.deepcopy(core.TEP_DEFAULT), [], {})


@pytest.fixture(scope="module")
def nagatino() -> dict:
    """КРТ Нагатино, четыре очереди: долг не погашен у свода, О1 и О2."""
    import golden_snapshot

    spec = golden_snapshot.s_nagatino(core, ROOT)
    return core._run_authoritative_model(spec["inputs"], spec["tep"], [], spec["phasing"])


def test_the_engine_keeps_the_project_returns_and_drops_the_equity_ones(defaults):
    summary = defaults["consolidated"]["summary"]
    _unpaid(summary)
    _project_is_a_number(summary)


def test_nagatino_has_project_returns_in_every_phase_and_the_whole(nagatino):
    results = {"свод": nagatino["consolidated"]}
    results.update({f"О{i + 1}": p["result"] for i, p in enumerate(nagatino["phases"])})
    unpaid = {name: r for name, r in results.items()
              if float(r["summary"]["ending_pf"]) > core.EQUITY_RETURNS_UNREPAID_DEBT_MIN_RUB}
    assert set(unpaid) >= {"свод", "О1", "О2"}, list(unpaid)
    for name, result in unpaid.items():
        _unpaid(result["summary"])
        _project_is_a_number(result["summary"])
    # Контрпример: очередь с погашенным долгом — числа и признак «ok».
    repaid = [r["summary"] for name, r in results.items() if name not in unpaid]
    assert repaid, "у Нагатино нет очереди с погашенным долгом — стенд не про разницу"
    for summary in repaid:
        assert summary["equity_returns"]["status"] == "ok"
        assert isinstance(summary["npv"], float) and isinstance(summary["npv_equity"], float)


def test_plato_reads_the_project_numbers_and_the_equity_label(defaults):
    snap = core._result_snapshot(defaults["consolidated"])
    assert isinstance(snap["npv_mln"], float), "NPV проекта читался как N/A"
    assert isinstance(snap["irr_project_pct"], float)
    assert snap["irr_equity_pct"] is None
    assert snap["equity_returns_na"] == LABEL and snap["irr_equity_label"] == LABEL
    assert "числом всегда" in core._AGENT_INSTRUCTIONS
    assert "irr_project_pct" in core._AGENT_INSTRUCTIONS.split("6a.")[1].split("6b.")[0]
    # Чувствительность по NPV и IRR проекта есть: базовое число определено.
    for metric in ("npv_mln", "irr_project_pct"):
        report = core.run_sensitivity(copy.deepcopy(core.DEFAULT_INPUTS),
                                      copy.deepcopy(core.TEP_DEFAULT), [], {}, metric=metric,
                                      parameters=["purchase_price_mln"])
        assert report["base"]["value"] is not None, metric


def test_the_teaser_prints_the_project_irr_as_a_number(defaults):
    from pypdf import PdfReader

    inputs = copy.deepcopy(core.DEFAULT_INPUTS)
    inputs["project_name"] = "Долг не погашен"
    pdf = core.build_teaser_pdf(defaults, inputs, copy.deepcopy(core.TEP_DEFAULT), {})
    text = re.sub(r"\s+", " ", " ".join(
        page.extract_text() for page in PdfReader(io.BytesIO(pdf)).pages))
    assert re.search(r"IRR проекта \(до финансирования\) -?\d", text), text[:600]
    assert not re.search(r"IRR проекта \(до финансирования\) N/A", text), text[:600]
    # Капитал — прежней подписью, и каждая подпись стоит у строки капитала:
    # плитка и строка NPV собственного капитала, строка IRR собственного капитала.
    places = [text[max(0, m.start() - 40):m.start()] for m in re.finditer(re.escape(LABEL), text)]
    assert len(places) == 3 and all("собственного капитала" in p for p in places), places


def test_the_telegram_card_prints_the_project_irr_as_a_number(monkeypatch, defaults):
    sent: list[str] = []
    monkeypatch.setattr(core, "_telegram_verify_session", lambda s: {"chat_id": 42, "cad": []})
    monkeypatch.setattr(core, "_telegram_user_allowed", lambda c: True)
    monkeypatch.setattr(core, "_telegram_send_message",
                        lambda chat_id, text, **kw: sent.append(text))
    monkeypatch.setattr(core, "_telegram_web_app_url", lambda *a, **k: "https://example.org/")
    s = defaults["consolidated"]["summary"]
    # Сводка страницы для бота: IRR проекта числом, подпись — только у капитала.
    core.telegram_result(core.TelegramResultRequest(session="s", summary={
        "purchase_price_mln": 6500, "net_profit_mln": float(s["net_profit"]) / 1e6,
        "llcr": float(s["llcr"]), "revenue_mln": float(s["revenue"]) / 1e6,
        "total_expenses_mln": float(s["total_expenses"]) / 1e6,
        "irr_project": s["irr_project"], "irr_equity": s["irr_equity"],
        "irr_equity_label": core.equity_irr_label(s),
    }))
    assert sent, "карточка не отправлена"
    card = sent[0]
    project = re.search(r"IRR проекта \(до финансирования\) — ([^\n]+)", card)
    assert project and re.match(r"-?\d", project.group(1)), card
    assert re.search(r"IRR собственного капитала — " + re.escape(LABEL), card), card


def test_the_nonres_book_writes_the_project_npv_as_a_formula():
    """Книга нежилого проекта: «NPV проекта» — формула без условия на долг."""
    import golden_snapshot

    spec = golden_snapshot.s_nonresidential(core, ROOT)
    engine = core._run_authoritative_model(
        dict(spec["inputs"]), copy.deepcopy(spec["tep"]), [], {})["consolidated"]
    _unpaid(engine["summary"])
    assert isinstance(engine["summary"]["npv"], float)
    content, _name, meta = core.build_project_workbook(
        dict(spec["inputs"]), copy.deepcopy(spec["tep"]), [], {}, project_name="нежилой")
    # Эталон — офис по ДДУ: с 24.10.2026 его книга — книга офиса; NPV и IRR
    # способа «Продажа по ДДУ» — на листе CF_ДДУ.
    assert meta.get("office_book"), meta
    openpyxl = pytest.importorskip("openpyxl")
    book = openpyxl.load_workbook(io.BytesIO(content))
    sheet = book["CF_ДДУ"]
    formulas = {str(sheet[f"A{row}"].value): str(sheet[f"B{row}"].value)
                for row in range(1, sheet.max_row + 1)
                if str(sheet[f"A{row}"].value or "").startswith(("NPV", "IRR"))}
    assert formulas.get("NPV проекта", "").startswith("=SUMPRODUCT("), formulas
    assert "долг не погашен" not in formulas["NPV проекта"]
    # Капитал — прежним правилом движка.
    for label in ("IRR собственника", "NPV собственника"):
        assert "долг не погашен" in formulas.get(label, ""), formulas


def test_the_object_report_prints_the_project_irr_as_a_number():
    """Отчёт нежилого проекта (`object_report`, раздел «Решение»): IRR проекта
    числом, IRR и NPV собственника — подписью капитала."""
    import golden_snapshot

    spec = golden_snapshot.s_nonresidential(core, ROOT)
    result = core._run_authoritative_model(
        dict(spec["inputs"]), copy.deepcopy(spec["tep"]), [], {})["consolidated"]
    _unpaid(result["summary"])
    report = core.object_report(result)
    assert report, "эталон nonresidential перестал быть нежилым проектом"
    decision = next(s for s in report["sections"] if s["key"] == "decision")
    rows = {row["label"]: row for block in decision["blocks"] for row in block.get("rows") or []}
    project = next(v for k, v in rows.items() if k.startswith("IRR проекта"))
    assert project["unit"] == "pct" and isinstance(project["value"], float), project
    owner = next(v for k, v in rows.items() if k.startswith("IRR собственника"))
    assert owner["unit"] == "text" and owner["value"] == LABEL, owner
    npv = next(v for k, v in rows.items() if k.startswith("NPV собственника"))
    assert npv["unit"] == "text" and npv["value"] == LABEL, npv


def test_the_v4_dashboard_gets_the_project_irr_as_a_number(defaults):
    """Подсказка движка для Дашборда книги v4 — число без подписи, и лист
    данных пишет его числом (`<v>`), а не текстом «N/A — долг не погашен»."""
    hints = core._v4_finance_hints(defaults)
    assert isinstance(hints["irr_project"]["value"], float)
    assert not hints["irr_project"].get("label")

    import v4_dashboard
    from xml.etree import ElementTree

    columns = core._v4_cf_columns()
    sheet = v4_dashboard.build_data_sheet(
        {}, core._AGENT_BANK_LLCR_TARGET, columns[-1], columns,
        core._V4_CAPEX_ARTICLE_ROW, core._V4_CAPEX_BLOCK_STRIDE,
        irr_project=hints["irr_project"])
    row = v4_dashboard.DATA_ROWS["irr_project"]
    cells = {c.get("r"): c for c in ElementTree.fromstring(sheet).iter()
             if c.tag.endswith("}c") or c.tag == "c"}
    cell = cells[f"C{row}"]
    assert cell.get("t") is None, ElementTree.tostring(cell, encoding="unicode")
    value = next(child for child in cell if child.tag.endswith("v"))
    assert float(value.text) == pytest.approx(defaults["consolidated"]["summary"]["irr_project"])


def test_the_decision_card_prints_the_project_irr_as_a_number(defaults):
    """`irrLead` карточки «Инвестиционное решение» — на node, настоящим кодом.

    Подделка: признак движка переключён на «ok» при том же остатке долга —
    строка проекта не меняется, значит карточка по признаку не решает.
    """
    s = defaults["consolidated"]["summary"]
    # `fmtPct` слоя — обёртка над `pct` страницы; здесь `pct` — тот же формат.
    prelude = ("const pct=v=>(Number(v)*100).toLocaleString('ru-RU',{maximumFractionDigits:1})+'%';\n"
               "var fmtPct=function(v){return pct(v);};\n"
               + page_blocks.function("irrLead", OVERLAY) + "\n")
    tail = f"""
const s={json.dumps({k: s[k] for k in ("irr_project", "irr_equity", "equity_returns", "equity_irr")}, ensure_ascii=False)};
const before=irrLead(s);
s.equity_returns={{status:'ok',label:null,reason:'',ending_pf:s.equity_returns.ending_pf}};
s.equity_irr=Object.assign({{}},s.equity_irr,{{status:'ok',meaningful:true,label:null}});
s.irr_equity=0.4321;
console.log(JSON.stringify({{before, after: irrLead(s)}}));
"""
    out, _taken = page_blocks.run(prelude, tail, page=OVERLAY)
    got = json.loads(out.strip().splitlines()[-1])
    before, after = got["before"], got["after"]
    assert re.search(r"^IRR проекта -?\d", before), before
    assert before.endswith("IRR капитала " + LABEL), before
    assert after.startswith(before.split(" · ")[0]), (before, after)
    assert re.search(r"IRR капитала 43", after), after
