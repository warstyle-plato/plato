"""Оговорка о дефолте в РВЭ называет, чем гасится долг, и не путает убыток с прибылью.

Владелец прислал PDF проекта с одной очередью: «Чистая прибыль −870,1 млн ₽ —
условная: в модели дефолт, долг закрыт продажами следующих периодов». Две
ошибки в одной строке:

- «следующих периодов» при одной очереди читается как «следующих очередей»,
  которых нет. После РВЭ модель гасит долг продажами самой очереди — того,
  что к вводу осталось нераспроданным (`available_for_repayment = sales`);
- «условная» у УБЫТКА читается как «на деле не так плохо». Допущение банка
  (ждать продаж без пеней и досрочного требования) убыток только смягчает:
  в жизни он больше.

Слова одни на PDF, страницу и Telegram — `DEFAULT_REPAYMENT_WORDS` движка.

Запуск: python3 -m pytest tests/test_the_default_note_names_what_repays_the_debt.py -q
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path
from shutil import which

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from engine_source import engine_source

import main as _wrapper

core = _wrapper.core


def _single_queue(price: float) -> tuple[dict, dict]:
    inputs = dict(core.DEFAULT_INPUTS)
    inputs.update(purchase_price_mln=12000, project_start="2027-01-01",
                  ird_months=12, construction_months=24, apartment_price_th=price)
    tep = {key: dict(row) for key, row in core.TEP_DEFAULT.items()}
    return core.calculate(core.CalcRequest(inputs=inputs, tep=tep, rates=[])), inputs


@pytest.fixture(scope="module")
def loss_after_default() -> tuple[dict, dict]:
    """Одна очередь, дефолт в РВЭ, долг закрыт к концу, итог — убыток."""
    result, inputs = _single_queue(580)
    financing = result["report"]["financing"]
    assert financing.get("default_date"), "предохранитель: дефолт в РВЭ обязан быть"
    assert float(financing.get("rve_pf_shortfall") or 0) > 500_000
    assert float(financing.get("ending_pf") or 0) < 500_000, (
        "предохранитель: долг к концу горизонта закрыт — иначе это ветка «бумажная»")
    assert float(result["summary"]["net_profit"]) < 0, "предохранитель: итог — убыток"
    return result, inputs


def _pdf(result: dict, inputs: dict) -> str:
    pytest.importorskip("reportlab")
    from market_search.krt_requirements import pdf_text
    return " ".join(pdf_text(core._build_developaid_pdf({
        "result": result, "inputs": inputs, "tep": core.TEP_DEFAULT, "rates": [],
        "phasing": {}, "scenario": "base", "project_name": "Одна очередь"})).split())


def test_the_single_queue_debt_is_repaid_by_its_own_unsold_stock() -> None:
    """Механика, которую называет текст: после дефолта долг гасят продажи после РВЭ."""
    result, _ = _single_queue(580)
    finance = result["finance"]
    rve = result["dates"]["rve"]
    after = sum(r["pf_repayment"] for r in finance["rows"] if str(r["month"])[:10] > rve)
    # Продажи после РВЭ гасят не меньше, чем не хватило: сверху — проценты,
    # набежавшие на остаток.
    assert after >= finance["rve_unpaid"] * 0.999
    assert finance["ending_pf"] < 500_000


def test_the_unpaid_debt_keeps_the_paper_branch() -> None:
    """Долг не закрыт к концу горизонта — у прибыли своя, жёсткая оговорка."""
    result, inputs = _single_queue(500)
    assert float(result["report"]["financing"]["ending_pf"]) > 500_000
    text = _pdf(result, inputs)
    assert "бумажная: долг не погашен" in text


def test_the_pdf_loss_is_not_called_conditional(loss_after_default) -> None:
    text = _pdf(*loss_after_default)
    # Строка раздела «Ключевая экономика» — та, что на скриншоте владельца;
    # первая страница печатает своё «Чистая прибыль» раньше.
    at = text.index("Чистая прибыль", text.index("Ключевая экономика"))
    row = text[at:text.index("Маржинальность", at)]
    assert "следующих периодов" not in row, row
    assert "условная" not in row, row
    assert "долг закрыт" not in row, row
    assert "без пеней и досрочного требования" in row, row
    assert "в жизни убыток больше" in row, row
    assert "нераспроданным к вводу (после РВЭ)" in row, row
    # Одна очередь — и слов про «эту очередь» нет.
    assert "очеред" not in row, row
    # Вердикт говорит о том же теми же словами.
    assert "следующих периодов" not in text, text
    assert "Значит показанный убыток" in text, text


def test_profit_and_loss_are_hedged_differently() -> None:
    profit = core.default_profit_note(1e9, 1)
    loss = core.default_profit_note(-1e9, 1)
    assert profit.startswith(" — условная")
    assert "согласится ждать" in profit
    assert "условная" not in loss and "в жизни убыток больше" in loss
    # Несколько очередей — слова про очередь; неизвестно сколько — как одна.
    assert core.default_repayment_words(3) == core.DEFAULT_REPAYMENT_WORDS["phased"]
    assert core.default_repayment_words(None) == core.DEFAULT_REPAYMENT_WORDS["single"]
    assert "этой очереди" in core.DEFAULT_REPAYMENT_WORDS["phased"]


def test_one_owner_of_the_words() -> None:
    source = engine_source()
    assert "следующих периодов\"" not in source and "следующих периодов'" not in source
    assert "продажами следующих периодов." not in source
    page = core.PAGE
    assert "__DEVELOPAID_DEFAULT_REPAYMENT__" not in page
    assert core.DEFAULT_REPAYMENT_WORDS["single"] in page
    assert "DEFAULT_REPAYMENT_WORDS.single" in page
    assert "DEFAULT_REPAYMENT_WORDS.phased" in page


def test_telegram_speaks_of_the_unsold_stock(monkeypatch) -> None:
    sent: list[str] = []
    monkeypatch.setattr(core, "_telegram_verify_session", lambda session: {"chat_id": 42, "cad": []})
    monkeypatch.setattr(core, "_telegram_user_allowed", lambda chat_id: True)
    monkeypatch.setattr(core, "_telegram_send_message",
                        lambda chat_id, text, **kwargs: sent.append(text))
    monkeypatch.setattr(core, "_telegram_web_app_url", lambda *args, **kwargs: "https://example.org/")
    core.telegram_result(core.TelegramResultRequest(session="s", summary={
        "purchase_price_mln": 12000, "net_profit_mln": -1253, "llcr": 0.93,
        "rve_pf_shortfall_mln": 1219, "default_date": "2030-01-01", "queue_count": 1,
    }))
    text = sent[0]
    assert "следующих периодов" not in text, text
    assert core.DEFAULT_REPAYMENT_WORDS["single"] in text, text
    assert "Значит показанный убыток" in text, text


def _function(name: str) -> str:
    page = core.PAGE
    start = page.index(f"function {name}(")
    depth, index = 0, page.index("{", start)
    for position in range(index, len(page)):
        if page[position] == "{":
            depth += 1
        elif page[position] == "}":
            depth -= 1
            if depth == 0:
                return page[start:position + 1]
    raise AssertionError(f"функция {name} не закрыта")


def test_node_single_queue_plate_names_the_unsold_stock() -> None:
    node = which("node")
    if not node:
        pytest.skip("node недоступен")
    months = re.search(r"const RU_MONTHS_IN=\[[^\]]+\];", core.PAGE).group(0)
    words = re.search(r"const DEFAULT_REPAYMENT_WORDS=[^\n]+;", core.PAGE).group(0)
    script = (
        months + "\n" + words + "\nlet phaseBundle=null;\n"
        "const money=v=>String(Math.round(v/1e6))+' млн';\n"
        + _function("ruMonth") + "\n" + _function("pfRveWarningHtml") + "\n"
        + "console.log(pfRveWarningHtml({report:{financing:{rve_pf_shortfall:1.2e9,"
          "default_date:'2030-01-01'}}}).replace(/<[^>]+>/g,''));"
    )
    out = subprocess.run([node, "-e", script], capture_output=True, text=True, timeout=30, check=False)
    assert out.returncode == 0, out.stderr
    text = out.stdout.strip()
    assert "следующих периодов" not in text, text
    assert core.DEFAULT_REPAYMENT_WORDS["single"] in text, text
