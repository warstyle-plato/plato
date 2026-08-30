"""Прибыль после дефолта — при допущении, и это сказано у самого числа.

Владелец, 30.08.2026: «значит нельзя писать и чистую прибыль». Речь о том же,
о чём и предыдущая правка: число, показанное голым, читается как достигнутое.

Оговорка в движке была, но срабатывала ровно в одном случае — когда долг
оставался непогашенным на КОНЕЦ горизонта. А банк ждёт погашения в дату
раскрытия эскроу: если денег там не хватило, это дефолт, даже когда
остаточные продажи закрывают долг годом позже. В такой конфигурации вердикт
говорил «Предварительно целесообразна», а прибыль стояла голым числом — при
том что весь исход держится на согласии банка, которого в модели не спрашивали.

Запуск: python3 -m pytest tests/test_profit_after_a_default_is_conditional.py -q
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

import main as _wrapper  # noqa: E402

core = _wrapper.core


def _bundle(price: float) -> dict:
    inputs = dict(core.DEFAULT_INPUTS)
    inputs.update(purchase_price_mln=12000, project_start="2027-01-01",
                  ird_months=12, construction_months=24, apartment_price_th=price)
    tep = {key: dict(row) for key, row in core.TEP_DEFAULT.items()}
    phasing = {
        "enabled": True, "mode": "phased", "user_enabled": True,
        "phase_count": 2, "phase_gap_months": 12,
        "phases": [{"name": "О1", "start_offset_months": 0, "construction_months": 24},
                   {"name": "О2", "start_offset_months": 12, "construction_months": 24}],
        "products": {key: [35, 65] for key in
                     ("apartments", "ground_commercial", "underground_parking")},
        "shared_cash": {}, "shared_allocation": {}, "social_objects": [],
        "carry_debt_forward": False,
    }
    return core.calculate_phased(core.PhasedCalcRequest(
        inputs=inputs, tep=tep, rates=[], phasing=phasing))


@pytest.fixture(scope="module")
def silent_default() -> dict:
    """Дефолт в РВЭ, но к концу горизонта долг закрыт остаточными продажами.

    Ровно та конфигурация, в которой прежние оговорки молчали все до одной.
    """
    bundle = _bundle(900)
    financing = (bundle["consolidated"].get("report") or {}).get("financing") or {}
    assert financing.get("default_date"), (
        "предохранитель: на этих вводных дефолт обязан быть, иначе тест "
        "проверяет не ту ветку")
    assert float(financing.get("ending_pf") or 0.0) < 500_000, (
        "предохранитель: долг обязан быть закрыт к концу — иначе сработала бы "
        "прежняя оговорка про непогашенный долг, и правка ни при чём")
    assert float(bundle["consolidated"]["summary"]["net_profit"]) > 0
    return bundle


def test_the_consolidated_financing_knows_about_the_default(silent_default) -> None:
    """Дефолт одной очереди — свойство всего свода.

    Без этих двух ключей свод не знал о нём вовсе: и вердикт, и PDF считают
    по сводному финансированию, а дефолт живёт в очереди.
    """
    financing = (silent_default["consolidated"].get("report") or {}).get("financing") or {}
    assert financing.get("default_date") == "2030-01-01"
    assert float(financing.get("rve_unpaid") or 0.0) > 500_000


def test_the_verdict_names_the_default_even_when_the_debt_is_closed(silent_default) -> None:
    financing = (silent_default["consolidated"].get("report") or {}).get("financing") or {}
    summary = silent_default["consolidated"]["summary"]
    verdict = core._purchase_feasibility(
        12000, float(summary["net_profit"]) / 1e6, summary["llcr"], 50_000,
        float(financing.get("ending_pf") or 0.0) / 1e6, financing.get("default_date"))
    assert verdict.get("conditional") is True
    assert "В модели есть дефолт" in verdict["text"]
    assert "в январе 2030" in verdict["text"]
    assert "только если банк на это согласится" in verdict["text"]
    assert "а не результат" in verdict["text"]


def test_without_a_default_the_verdict_is_not_hedged() -> None:
    """Предохранитель: оговорка не приклеивается ко всякому вердикту.

    Иначе она перестаёт что-либо значить — как всякое предупреждение, которое
    стоит всегда.
    """
    verdict = core._purchase_feasibility(12000, 25_000, 1.5, 50_000, 0.0, None)
    assert "conditional" not in verdict
    assert "В модели есть дефолт" not in verdict["text"]


def test_the_default_branch_keeps_its_own_words() -> None:
    """Непогашенный на конец долг сильнее: у него оговорка своя, и она жёстче."""
    verdict = core._purchase_feasibility(12000, 25_000, 1.5, 50_000, 3_861.9, "2030-01-01")
    assert verdict["status"] == "default"
    # Две оговорки подряд про одно — это не полнота, а шум.
    assert "В модели есть дефолт" not in verdict["text"]
    assert "бумажная" in verdict["text"]


def test_the_pdf_profit_carries_the_caveat() -> None:
    """В PDF у прибыли три разных исхода, и средний прежде молчал."""
    source = Path(core.__file__).read_text(encoding="utf-8")
    assert '" — условная: в модели дефолт, долг закрыт продажами "' in source
    assert "financing.get('default_date')" in source


def test_the_month_is_spelled_out_not_derived() -> None:
    """Предложный падеж списком: правило «я→е» однажды даст «в феврале»."""
    assert core._month_in_words("2030-01-01") == "в январе 2030"
    assert core._month_in_words("2031-05-01") == "в мае 2031"
    assert core._month_in_words("") == "в дату раскрытия эскроу"
    assert core._month_in_words("2030-13-01") == "в дату раскрытия эскроу"


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


def test_the_screen_decides_about_the_default_once() -> None:
    """Плашка и плитка спрашивают одну функцию, а не считают каждая своё.

    Две проверки на один вопрос однажды разойдутся, и обе будут выглядеть
    верными — плашка скажет «дефолт», плитка промолчит.
    """
    page = core.PAGE
    assert "function modelDefaultInfo(" in page
    assert "modelDefaultInfo(r)" in page
    # Плашка берёт разбор оттуда же, а не сканирует очереди второй раз.
    assert "pfQueueOutcomes()" in _function("pfRveWarningHtml")
    assert "pfQueueOutcomes()" in _function("modelDefaultInfo")


def test_the_conditional_tiles_are_the_ones_that_depend_on_the_flow() -> None:
    body = _function("renderResult")
    for label in ("Чистая прибыль", "Маржинальность", "NPV @"):
        line = next(row for row in body.splitlines() if f"['{label}" in row)
        assert "conditional" in line, label
    # Полная фраза — один раз, у прибыли: три одинаковых строки подряд
    # перестают читаться и становятся фоном.
    profit = next(row for row in body.splitlines() if "['Чистая прибыль'" in row)
    assert "conditionalNote" in profit
    for label in ("Маржинальность", "NPV @"):
        line = next(row for row in body.splitlines() if f"['{label}" in row)
        assert "conditionalShort" in line, label
    # EBITDA считается до финансирования — дефолт её не трогает, и вешать на
    # неё оговорку значит размывать её смысл.
    ebitda = next(row for row in body.splitlines() if "['EBITDA'" in row)
    assert "conditionalNote" not in ebitda


def test_node_marks_the_profit_when_a_queue_defaults() -> None:
    node = which("node")
    if not node:
        pytest.skip("node недоступен")
    months = re.search(r"const RU_MONTHS_IN=\[[^\]]+\];", core.PAGE).group(0)
    script = (
        months + "\nlet phaseBundle=null;\n"
        + _function("ruMonth") + "\n"
        + _function("pfQueueOutcomes") + "\n"
        + _function("modelDefaultInfo") + "\n"
        + """
        phaseBundle = {
          mode: 'phased',
          comparison: [
            {name: 'О1', debt_carried_out: 13.17e9},
            {name: 'О2', debt_carried_out: 0},
          ],
          phases: [
            {result: {report: {financing: {rve_unpaid: 13.17e9}}}},
            {result: {report: {financing: {rve_unpaid: 10.81e9,
                                           default_date: '2031-01-01'}}}},
          ],
        };
        const found = modelDefaultInfo({report: {financing: {}}});
        console.log(JSON.stringify([found && found.name, found && found.when]));
        // Очередь, передавшая долг, дефолтной не считается: банк её долг принял.
        phaseBundle.phases[1].result.report.financing = {rve_unpaid: 0};
        console.log(JSON.stringify(modelDefaultInfo({report: {financing: {}}})));
        """
    )
    out = subprocess.run([node, "-e", script], capture_output=True, text=True, timeout=30)
    assert out.returncode == 0, out.stderr
    first, second = out.stdout.strip().splitlines()
    assert first == '["О2","январе 2031"]', first
    assert second == "null", second
