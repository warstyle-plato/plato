"""IRR и NPV при непогашенном долге — «N/A — долг не погашен», а не число.

Решение владельца 29.09.2026 (ревизия книги, решение 2): если ПФ к концу
проекта не погашен, доходность капитала не считается. Книга так и делала
(`КОНСОЛИДАТОР!N8`: IF('CF'!B19>0.5, "N/A (долг не погашен)", …)), а движок
показывал число — у Нагатино IRR 11 % при 6,7 млрд непогашенного долга.

Решение принимает движок один раз (`summary.equity_returns`); страница, тизер,
Платон и Telegram печатают его подпись, а не сравнивают остаток долга сами.
Отсутствие числа — не ноль.

Каждая проверка падает на прежнем коде (там число), а проверка страницы —
ещё и на подделке, которая решала бы по остатку долга сама.

Запуск: python3 -m pytest tests/test_returns_are_na_when_the_debt_is_unpaid.py -q
"""

from __future__ import annotations

import copy
import io
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import main as _wrapper  # noqa: E402
from browser import chromium_or_skip, serve  # noqa: E402

core = _wrapper.core
LABEL = "N/A — долг не погашен"
PORT = 18799


def _single(**update) -> dict:
    inputs = copy.deepcopy(core.DEFAULT_INPUTS)
    inputs.update(update)
    return core._run_authoritative_model(inputs, copy.deepcopy(core.TEP_DEFAULT), [], {})


@pytest.fixture(scope="module")
def unpaid() -> dict:
    """Умолчания: ПФ к концу не погашен (~980 млн ₽)."""
    return _single(project_name="Долг не погашен")


@pytest.fixture(scope="module")
def repaid() -> dict:
    """Контрпример: рост цены 1,5 %/мес. — долг погашен, числа на месте."""
    return _single(project_name="Долг погашен", monthly_growth_pre_pct=1.5)


def test_the_engine_drops_the_numbers_and_names_the_reason(unpaid, repaid):
    summary = unpaid["consolidated"]["summary"]
    assert float(summary["ending_pf"]) > core.EQUITY_RETURNS_UNREPAID_DEBT_MIN_RUB, \
        "стенд не про непогашенный долг"
    assert summary["npv"] is None and summary["irr_equity"] is None
    assert summary["equity_returns"]["status"] == "debt_unrepaid"
    assert summary["equity_returns"]["label"] == LABEL
    assert "млн ₽" in summary["equity_returns"]["reason"]

    ok = repaid["consolidated"]["summary"]
    assert float(ok["ending_pf"]) <= core.EQUITY_RETURNS_UNREPAID_DEBT_MIN_RUB
    assert isinstance(ok["npv"], float), "при погашенном долге NPV — число"
    assert ok["equity_returns"]["status"] == "ok" and ok["equity_returns"]["label"] is None


def test_the_threshold_is_the_books():
    """Порог тот же, что у книги: 'CF'!B19 > 0,5 млн ₽."""
    openpyxl = pytest.importorskip("openpyxl")
    book = openpyxl.load_workbook(ROOT / "templates" / "DevelopAid_model_v4.xlsx")
    formula = str(book["КОНСОЛИДАТОР"]["N8"].value)
    found = re.search(r"'CF'!B19>([\d.]+)", formula)
    assert found and "долг не погашен" in formula, formula
    assert float(found.group(1)) * 1_000_000 == core.EQUITY_RETURNS_UNREPAID_DEBT_MIN_RUB


def test_every_phase_and_the_whole_are_decided():
    """Очереди и свод решаются каждый по своему долгу."""
    inputs = copy.deepcopy(core.DEFAULT_INPUTS)
    phasing = {"enabled": True, "mode": "phased", "phase_count": 2, "user_enabled": True,
               "phase_gap_months": 12,
               "phases": [{"name": f"О{i + 1}", "start_offset_months": 12 * i,
                           "construction_months": 30} for i in range(2)]}
    bundle = core._run_authoritative_model(inputs, copy.deepcopy(core.TEP_DEFAULT), [], phasing)
    results = [bundle["consolidated"]] + [item["result"] for item in bundle["phases"]]
    for result in results:
        summary = result["summary"]
        unpaid = float(summary["ending_pf"]) > core.EQUITY_RETURNS_UNREPAID_DEBT_MIN_RUB
        assert summary["equity_returns"]["status"] == ("debt_unrepaid" if unpaid else "ok")
        if unpaid:
            assert summary["npv"] is None and summary["irr_equity"] is None


def test_plato_reads_na_not_zero(unpaid, repaid):
    snap = core._result_snapshot(unpaid["consolidated"])
    assert snap["npv_mln"] is None, "отсутствие NPV читалось нулём"
    assert snap["irr_equity_pct"] is None
    assert snap["equity_returns_na"] == LABEL
    assert core._result_snapshot(repaid["consolidated"])["equity_returns_na"] is None
    assert "N/A — долг не погашен" in core._AGENT_INSTRUCTIONS
    numbers = core.presentation_numbers(unpaid["consolidated"])
    assert numbers["npv_mln"] is None and numbers["equity_returns_na"] == LABEL


def _teaser_text(bundle: dict, name: str) -> str:
    from pypdf import PdfReader
    inputs = copy.deepcopy(core.DEFAULT_INPUTS)
    inputs["project_name"] = name
    pdf = core.build_teaser_pdf(bundle, inputs, copy.deepcopy(core.TEP_DEFAULT), {})
    reader = PdfReader(io.BytesIO(pdf))
    return re.sub(r"\s+", " ", " ".join(page.extract_text() for page in reader.pages))


def test_the_teaser_prints_na(unpaid, repaid):
    text = _teaser_text(unpaid, "Долг не погашен")
    # Тизер печатает и IRR, и NPV (две строки «Итога» и строка экономики).
    assert text.count(LABEL) >= 2, text[:400]
    npv = core.presentation_numbers(repaid["consolidated"])["npv_mln"]
    shown = core._pdf_num(npv, 1)
    assert shown in _teaser_text(repaid, "Долг погашен"), "контрпример: NPV числом"
    assert LABEL not in _teaser_text(repaid, "Долг погашен")


def test_the_page_prints_the_engines_label():
    """Отрисованная страница: NPV и IRR — подписью движка.

    Подделка: признак движка переключён на «ok» при том же остатке долга.
    Страница, решающая по `ending_pf` сама, показала бы N/A и тут — проверка
    поймает. Прежний код печатал число (или 0) в обоих случаях.
    """
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
            tab.wait_for_timeout(700)
            got = tab.evaluate("""async ()=>{
              await calculate();
              const cells=()=>{
                const out={};
                for(const tr of document.querySelectorAll('#economicsTable tr')){
                  const c=[...tr.children].map(x=>(x.textContent||'').trim());
                  if(c.length>=2) out[c[0]]=c[1];
                }
                const kpi=[...document.querySelectorAll('div,tr')]
                  .map(x=>(x.textContent||'').replace(/\\s+/g,' ').trim())
                  .filter(t=>t.startsWith('NPV @')).sort((a,b)=>a.length-b.length)[0]||'';
                return {table: out, kpi};
              };
              const before=cells();
              const s=lastResult.summary;
              const status=s.equity_returns&&s.equity_returns.status;
              s.equity_returns={status:'ok',label:null,reason:'',ending_pf:s.ending_pf};
              s.npv=-1234.5e6; s.irr_equity=0.123;
              renderResult();
              return {before, after: cells(), status, ending: s.ending_pf};
            }""")
        finally:
            browser.close()

    other = [line for line in errors if "Failed to fetch" not in line]
    assert not other, f"страница упала: {other[:2]}"
    assert got["status"] == "debt_unrepaid" and got["ending"] > 500_000, got
    before, after = got["before"], got["after"]
    assert before["table"].get("NPV") == LABEL, before["table"]
    assert before["table"].get("IRR equity") == LABEL, before["table"]
    assert LABEL in before["kpi"], before["kpi"]
    # Подделка: тот же остаток долга, но движок сказал «ok» — страница
    # печатает число, то есть решает не сама.
    assert LABEL not in after["table"].get("NPV", ""), after["table"]
    assert "1" in after["table"].get("NPV", "") and "N/A" not in after["table"]["NPV"]
    assert after["table"].get("IRR equity", "").endswith("%"), after["table"]
    assert LABEL not in after["kpi"], after["kpi"]


def test_the_chat_summary_carries_the_label():
    """Сводка страницы для бота несёт подпись движка, а не свой вывод."""
    page = core.PAGE
    assert "equity_returns_na:returnsNa(s)," in page
    assert "const returnsNa=s=>((s||{}).equity_returns||{}).label||null;" in page
