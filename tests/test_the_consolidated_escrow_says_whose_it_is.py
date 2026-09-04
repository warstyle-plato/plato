"""Свод складывает счета эскроу очередей — и это не ответ про очередь.

Владелец, 04.09.2026: «Чем на второй очереди сразу покрывается так хорошо
выборка эскроу? Странно несколько. Это деньги первой очереди или что?
Выглядит непонятно.»

Ответ буквально «да, первой». На умолчаниях с двумя очередями в месяц первой
выборки ПФ второй очереди сводная линия эскроу стоит на 8,88 млрд ₽, из
которых 8,43 — деньги ПЕРВОЙ очереди, а покрытие свода 0,58 против 0,22 у
самой очереди. Сумма верна; неверно, что она отвечает на вопрос про очередь —
у каждой свой счёт и своя дата раскрытия, и чужое эскроу её выборку не
покрывает.

Поэтому доля каждой очереди едет вместе с суммой, площадь эскроу на своде
разложена слоями, а оговорка названа числом. Считает это движок один раз:
второй счёт той же величины на экране однажды разошёлся бы с первым, и обе
площади выглядели бы верными.

Запуск: python3 -m pytest tests/test_the_consolidated_escrow_says_whose_it_is.py -q
"""

from __future__ import annotations

import io
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import main as wrapper  # noqa: E402

core = wrapper.core

PHASING = {"enabled": True, "phase_count": 2, "phase_gap_months": 12}


@pytest.fixture(scope="module")
def bundle():
    return core._run_authoritative_model(
        dict(core.DEFAULT_INPUTS),
        {key: dict(value) for key, value in core.TEP_DEFAULT.items()}, [], PHASING)


def test_the_consolidated_row_says_whose_escrow_it_is(bundle) -> None:
    finance = bundle["consolidated"]["finance"]
    names = finance["phase_names"]
    assert len(names) == len(bundle["phases"]), "имя очереди у каждой доли"
    for row in finance["rows"]:
        parts = row["escrow_by_phase"]
        assert len(parts) == len(names)
        # Доли — это разложение суммы, а не второй счёт: разойдись они, обе
        # величины выглядели бы верными.
        assert sum(parts) == pytest.approx(row["escrow"], rel=1e-9, abs=1.0)


def test_a_queue_opening_its_line_sees_mostly_other_peoples_money(bundle) -> None:
    """Тот самый месяц, из-за которого задан вопрос."""
    finance = bundle["consolidated"]["finance"]
    second = bundle["phases"][1]["result"]["finance"]["rows"]
    start = next(row["month"] for row in second if row.get("pf_draw", 0.0) > 0)
    total = next(row for row in finance["rows"] if row["month"] == start)
    mine = next(row for row in second if row["month"] == start)
    others = total["escrow"] - mine["escrow"]
    assert others > mine["escrow"], (
        "проверка держит именно тот случай, ради которого написана: чужого "
        "эскроу на сводной линии больше своего")
    # И покрытие свода в этот месяц выше собственного покрытия очереди —
    # ровно поэтому сводный график читался как «выборка сразу покрыта».
    own_coverage = mine["escrow"] / mine["pf_balance"] if mine["pf_balance"] else 0.0
    assert total["coverage"] > own_coverage


def test_the_caveat_is_named_with_numbers(bundle) -> None:
    cover = bundle["consolidated"]["finance"]["escrow_cover"]
    lines = cover.get("phase_lines") or []
    assert lines, "оговорка обязана быть на своде с очередями"
    assert all(line in cover["lines"] for line in lines), "и доезжать до общего списка"
    text = " ".join(lines)
    assert "открывает ПФ" in text and "из них своих" in text
    assert "счета других очередей" in text


def test_a_single_queue_says_nothing_extra() -> None:
    """У одиночного проекта чужого эскроу нет, и оговорка была бы шумом."""
    bundle = core._run_authoritative_model(
        dict(core.DEFAULT_INPUTS),
        {key: dict(value) for key, value in core.TEP_DEFAULT.items()}, [], {})
    cover = bundle["consolidated"]["finance"]["escrow_cover"]
    assert not (cover.get("phase_lines") or [])


def test_the_chart_draws_the_layers_and_does_not_count_them(bundle) -> None:
    """Экран рисует готовые доли: второй счёт разошёлся бы с первым молча."""
    node = shutil.which("node")
    if not node:
        pytest.skip("node недоступен")
    page = core.PAGE
    start = page.index("function escrowCoverSvg(")
    depth = 0
    for position in range(page.index("{", start), len(page)):
        if page[position] == "{":
            depth += 1
        elif page[position] == "}":
            depth -= 1
            if depth == 0:
                body = page[start:position + 1]
                break
    else:  # pragma: no cover
        raise AssertionError("escrowCoverSvg не найдена")
    rows = [{key: row.get(key) for key in
             ("month", "escrow", "pf_balance", "pf_payable", "pf_obligation",
              "escrow_by_phase", "escrow_released_cumulative",
              "sales_after_rve_cumulative")}
            for row in bundle["consolidated"]["finance"]["rows"]]
    script = ("function mln(v){return String(v)}\n" + body
              + f"\nconsole.log(escrowCoverSvg({json.dumps(rows)},{{}}));")
    done = subprocess.run([node, "-e", script], capture_output=True, text=True, timeout=60)
    assert done.returncode == 0, done.stderr[:600]
    svg = done.stdout
    assert "слоями по очередям" in svg, "разделённая площадь без подписи читается как одна"
    # Два слоя — два многоугольника эскроу: одна общая площадь означала бы,
    # что разложение до рисунка не доехало.
    assert svg.count('fill="#2D6A4F"') >= len(bundle["phases"])
    # Долей на экране не считают — их только рисуют.
    assert "escrow_by_phase" in body
    assert not re.search(r"escrow_by_phase[^\n]*/\s*Number\(", body), "экран делит сам"


def test_the_pdf_says_the_same(bundle) -> None:
    """Отчёт носят в банк, и расходиться с экраном ему нельзя."""
    pypdf = pytest.importorskip("pypdf")
    data = core._build_developaid_pdf({
        "result": bundle["consolidated"], "inputs": dict(core.DEFAULT_INPUTS),
        "tep": {key: dict(value) for key, value in core.TEP_DEFAULT.items()},
        "rates": [], "phasing": PHASING, "scenario": "base", "project_name": "Эскроу"})
    text = "\n".join(page.extract_text() or ""
                     for page in pypdf.PdfReader(io.BytesIO(data)).pages)
    assert "слоями по очередям" in text
    assert "счета других очередей" in text
