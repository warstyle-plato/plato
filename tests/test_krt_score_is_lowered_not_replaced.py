"""Балл площадки один, и расчёт его снижает, а не заменяет собой.

В списке КРТ посчитанная модель вытесняла балл: вместо «87 · Высокое»
появлялось «Модель · Не проходит», и сравнить две площадки было уже нечем — у
одной число, у другой фраза (владелец, 23.08.2026). Теперь число одно и всегда
на месте, а маркетинг с движком из него **вычитают**.

Направление одностороннее намеренно: ТЭП говорит, сколько здесь потенциально
метров, экономика — сколько из них выживает. Поднимать балл за хорошую модель
нельзя: она посчитана на предпосылках, а не на сметах, и прибавка была бы
прибавкой за нашу же догадку.

Тест гоняет настоящие функции страницы торгов через node, а не их пересказ.

Запуск: python3 -m pytest tests/test_krt_score_is_lowered_not_replaced.py -q
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from auction_search.ui import auctions_page  # noqa: E402


# Площадка, в которую ещё можно войти. Прежде здесь стояла «В реализации» —
# и это был неудачный пример: инвестор там уже определён, войти нельзя, и
# площадка нужна только справочно (владелец, 25.08.2026). Проверять снижения
# экономики на ней значило мерить их на том, чего мы не купим.
SITE = {"slug": "site", "name": "Площадка", "okrug": "ЮАО", "district": "Нагатино",
        "status": "Планируемый", "area_ha": 14.6,
        "total_gfa_sqm": 500000, "housing_gfa_sqm": 300000,
        "business_gfa_sqm": 100000, "jobs": 1200}


def page_functions() -> str:
    """Настоящие функции балла со страницы, а не их копия здесь."""
    script = auctions_page()
    script = script[script.rindex("<script>") + len("<script>"):script.rindex("</script>")]
    out = []
    # `krtIntent` появилась вместе со снижениями за оператора и городские
    # нужды: балл теперь читает и то, что сказано в источнике о самой площадке.
    for name in ("krtFit", "krtIntent", "krtPenalty", "krtScore", "krtScoreNote"):
        start = script.index(f"function {name}(")
        depth = 0
        for position in range(script.index("{", start), len(script)):
            if script[position] == "{":
                depth += 1
            elif script[position] == "}":
                depth -= 1
                if depth == 0:
                    out.append(script[start:position + 1])
                    break
        else:
            raise AssertionError(f"не найдена функция {name}")
    rules = script[script.index("const KRT_PENALTIES="):]
    out.insert(0, rules[:rules.index("];") + 2])
    return "\n".join(out)


def score(model: dict | None, rank: dict | None = None, site: dict | None = None,
          intent: dict | None = None) -> dict:
    node = shutil.which("node")
    if not node:
        pytest.skip("node недоступен")
    stub = (
        "const state={krtModels:{},krtRank:{},krtRequirements:{},krtPress:{}};\n"
        f"state.krtModels['site']={json.dumps(model)};\n"
        f"state.krtRank['site']={json.dumps(rank or {})};\n"
        f"state.krtRequirements['site']={json.dumps(intent and {'intent': intent} or {})};\n"
        "const document={getElementById:()=>({value:'housing_ready'})};\n"
        "const $=()=>({value:'housing_ready'});\n"
        "function fmtArea(v){return String(v)}\n"
    )
    body = (stub + page_functions()
            + f"\nconsole.log(JSON.stringify(krtScore({json.dumps(site or SITE)})));")
    done = subprocess.run([node, "-e", body], capture_output=True, text=True, timeout=60)
    assert done.returncode == 0, done.stderr[:600]
    return json.loads(done.stdout)


def model_with(llcr: float, margin: float, weakest: float) -> dict:
    return {"metrics": {"project_llcr_x": llcr, "margin_pct": margin,
                        "weakest_phase_llcr_x": weakest}}


def test_without_a_model_the_score_is_the_tep_potential() -> None:
    got = score(None)
    assert got["counted"] is False
    assert got["score"] == got["base"]
    assert got["cut"] == 0
    assert "модель не считалась" in got["note"] if "note" in got else True


def test_a_healthy_project_keeps_its_score() -> None:
    """LLCR 1,20x и маржа 15% — целевые: снимать нечего."""
    got = score(model_with(1.25, 18.0, 1.10), {"entry_capacity_rub_per_sqm": 42000})
    assert got["cut"] == 0
    assert got["score"] == got["base"]


def test_a_weak_project_loses_points_but_keeps_a_number() -> None:
    got = score(model_with(1.01, 1.1, 0.85), {"entry_capacity_rub_per_sqm": 12000})
    assert got["counted"] is True
    assert 0 < got["cut"] <= 95
    assert got["score"] == round(got["base"] * (1 - got["cut"] / 100))
    assert isinstance(got["score"], int) and got["score"] >= 0


def test_the_model_never_raises_the_score() -> None:
    base = score(None)["base"]
    for llcr, margin, weakest in ((1.60, 40.0, 1.50), (1.20, 15.0, 1.00), (0.70, -9.0, 0.50)):
        got = score(model_with(llcr, margin, weakest), {"entry_capacity_rub_per_sqm": 1})
        assert got["score"] <= base, (llcr, margin, weakest, got)


def test_the_penalty_grows_as_the_project_gets_worse() -> None:
    strong = score(model_with(1.15, 12.0, 0.98), {"entry_capacity_rub_per_sqm": 1})
    weak = score(model_with(0.95, 3.0, 0.85), {"entry_capacity_rub_per_sqm": 1})
    assert weak["cut"] > strong["cut"]
    assert weak["score"] < strong["score"]


def test_a_bad_project_still_keeps_a_distinguishable_number() -> None:
    """Ноль в колонке читается как «не оценивали», а не как «плохо»."""
    weak_tep = dict(SITE)
    got = score(model_with(0.60, -20.0, 0.40), {})
    assert got["cut"] <= 95
    assert got["score"] > 0, got
    assert got["score"] < got["base"] * 0.3


def test_an_unpriced_ceiling_costs_points() -> None:
    with_ceiling = score(model_with(1.30, 20.0, 1.20), {"entry_capacity_rub_per_sqm": 30000})
    without = score(model_with(1.30, 20.0, 1.20), {})
    assert without["cut"] - with_ceiling["cut"] == 10


def test_every_deduction_says_what_it_is() -> None:
    got = score(model_with(0.95, 2.0, 0.80), {})
    assert got["cuts"], "снижение без объяснения — это просто другое число"
    for item in got["cuts"]:
        assert item["label"] and item["points"] > 0


def test_a_site_already_under_way_is_reference_only() -> None:
    """«В реализации» — инвестор определён: войти нельзя, и балл это говорит.

    Прежде статус работал наоборот: «В реализации» давало САМУЮ большую
    прибавку, и верх списка занимало то, что нам недоступно.
    """
    entered = score(None, site={**SITE, "status": "В реализации"})
    planned = score(None)
    assert entered["score"] < planned["score"]
    assert any("войти нельзя" in cut["label"] for cut in entered["cuts"])
    # Снижение, а не изгнание: число остаётся, справочная ценность есть.
    assert entered["score"] > 0


def test_the_status_is_not_potential() -> None:
    """Потенциал считается по ТЭП; статус — про возможность войти, и он вычитает."""
    entered = score(None, site={**SITE, "status": "В реализации"})
    assert entered["base"] == score(None)["base"], "статус не должен раздувать потенциал"
