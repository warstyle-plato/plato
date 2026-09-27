"""Нехватка одобренного лимита ПФ доезжает до вердикта, а не живёт в `finance`.

Движок умел это с самого начала: выборка упёрлась в одобренный потолок —
остаток уходит в `pf_shortfall` с месяцем первой нехватки, и это проверено
отдельно (`test_pf_limit_is_a_ceiling_not_a_note`). Дальше величина не шла
НИКУДА: ни в свод, ни в блок финансирования отчёта, — только в `finance`,
который читает страница и никто больше. Поэтому проект, которому банк не дал
трети нужных денег, получал «Предварительно целесообразна» ровно тем же
текстом, что и полностью профинансированный: прибыль положительная, LLCR выше
1,20x, а откуда взялись недостающие миллиарды — вопрос, который никто не задал.

Замер: одобрено 24 528 млн ₽ при требуемых 40 880 — дыра 16 351 млн, то есть
40% потребности. `summary` о ней не знал, `report.financing` тоже.

Ветки вердикта у этого нет, и это не упущение: приписка того же рода, что у
дефолта в РВЭ (решение владельца, 30.08.2026) — она верна и при низком LLCR, и
при высоком. Правится только заголовок положительной ветки: «целесообразна» —
слово без условий, а условие как раз есть.

Запуск: python3 -m pytest tests/test_a_funding_gap_is_not_a_green_verdict.py -q
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import main as _wrapper  # noqa: E402

core = _wrapper.core


def _calc(approved_mln: float) -> dict:
    inputs = {**core.DEFAULT_INPUTS, "purchase_price_mln": 3000,
              "project_start": "2027-01-01", "ird_months": 12,
              "construction_months": 24, "apartment_price_th": 500,
              "pf_limit_approved_mln": approved_mln}
    tep = {key: dict(row) for key, row in core.TEP_DEFAULT.items()}
    return core.calculate(core.CalcRequest(inputs=inputs, tep=tep, rates=[]))


@pytest.fixture(scope="module")
def free() -> dict:
    return _calc(0)


@pytest.fixture(scope="module")
def starved(free) -> dict:
    """Одобрено 60% требуемого — дыра заведомо крупная."""
    approved = round(float(free["finance"]["pf_limit_required"]) / 1e6 * 0.6)
    return _calc(approved)


def test_the_fixture_really_starves_the_project(starved):
    """Предохранитель: нет дыры — вся проверка ни о чём."""
    gap = float(starved["finance"]["pf_shortfall"])
    required = float(starved["finance"]["pf_limit_required"])
    assert gap > 0
    assert gap / required > 0.2, "дыра должна быть крупной, а не копеечной"
    assert starved["finance"]["pf_shortfall_month"]


def test_the_gap_reaches_the_summary_and_the_report(starved):
    """Величина, живущая в `finance`, на поверхности не существует."""
    assert float(starved["summary"]["pf_shortfall"]) > 0
    assert starved["summary"]["pf_shortfall_month"]

    financing = starved["report"]["financing"]
    assert float(financing["pf_shortfall"]) > 0
    assert financing["pf_shortfall_month"]
    # Обе базы рядом с разницей: «не хватает 16 млрд» без них не проверить.
    assert float(financing["pf_limit_required"]) > float(financing["pf_limit_approved"]) > 0
    # Та же величина в миллионах — для тех, кому считать нельзя (адаптер /v2).
    assert float(financing["pf_shortfall_mln"]) == pytest.approx(
        float(financing["pf_shortfall"]) / 1e6)


def test_a_starved_project_does_not_get_a_bare_green_verdict(starved):
    """Заголовок положительной ветки обязан нести условие."""
    summary, financing = starved["summary"], starved["report"]["financing"]
    verdict = core._purchase_feasibility(
        summary.get("purchase_price_mln") or 3000,
        float(summary["net_profit"]) / 1e6,
        summary["llcr"],
        float(financing.get("pf_uncovered_peak") or 0) / 1e6,
        float(financing.get("ending_pf") or 0) / 1e6,
        financing.get("default_date"),
        float(financing["pf_shortfall"]) / 1e6,
        financing["pf_shortfall_month"],
    )
    assert verdict["financing_gap"] is True
    assert verdict["conditional"] is True
    assert verdict["status"] != "positive"
    assert "целесообразна" not in verdict["title"].lower()
    assert "финансирование не закрыто" in verdict["title"].lower()
    # Сумма и месяц — в тексте: без них оговорка ни к чему не обязывает.
    assert "млн ₽" in verdict["text"]
    assert str(verdict["pf_shortfall_mln"]) and verdict["pf_shortfall_month"]


def test_a_funded_project_keeps_its_plain_verdict():
    """Обратная половина: нет дыры — ни приписки, ни правки заголовка.

    Иначе «финансирование не закрыто» стояло бы на каждом проекте и
    перестало бы читаться.
    """
    verdict = core._purchase_feasibility(3000, 5000, 1.35, 20000, 0.0, None, 0.0, "")
    assert verdict["status"] == "positive"
    assert verdict["title"] == "Предварительно целесообразна"
    assert "financing_gap" not in verdict
    assert "финансирование" not in verdict["text"].lower()


def test_rounding_dust_is_not_a_funding_gap():
    """Порог тот же, что у остатка ПФ в отчёте: полмиллиона."""
    assert "financing_gap" not in core._purchase_feasibility(
        3000, 5000, 1.35, 20000, 0.0, None, 0.4, "2029-01-01")


def test_the_clause_survives_a_bad_branch(starved):
    """Приписка — не ветка: она верна и там, где вердикт и так плохой.

    Ровно как оговорка о дефолте (решение владельца, 30.08.2026): спорить с
    LLCR за очередь ей незачем.
    """
    verdict = core._purchase_feasibility(
        3000, -100, 1.35, 20000, 0.0, None, 16351.5, "2029-01-01")
    assert verdict["status"] == "negative"
    assert verdict["title"] == "Предварительно нецелесообразна"
    assert verdict["financing_gap"] is True
    assert "финансирование не закрыто" in verdict["text"].lower()
