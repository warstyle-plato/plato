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
    # `krtVolumeShare` — шкала объёма: балл больше не складывается из
    # постоянных прибавок, и без неё `krtFit` не считается вовсе.
    # `krtTaskProfile` читает выбранное назначение: отдельного списка задач
    # больше нет, он дублировал «Статус» и «Назначение», и мера балла следует
    # тому же полю, что и отбор.
    # `krtRenovation` — измеренная доля городских нужд: снижение за них больше
    # не плоская четверть, и без неё балл не считается вовсе. `krtRuleValue`
    # называет число правила в его единицах, `krtInt`/`krtPct` — оформление
    # подписи, а не арифметика балла.
    # `krtBroken`/`krtNumber` — один ответ на «известна ли величина строки»:
    # у карточки, разбор которой съехал на поле, её значений нет ни в ячейке,
    # ни в сортировке, ни в балле.
    for name in ("krtVolumeShare", "krtTaskProfile", "krtBroken", "krtNumber",
                 "krtFit", "krtIntent",
                 "krtInt", "krtPct", "krtRenovation", "krtLots", "krtLiveLot", "krtAskingPrice", "krtPriceVerdict", "krtRuleValue",
                 "krtPenalty", "krtScoreSource", "krtScore", "krtScoreNote"):
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
    # Якоря шкалы сняты с самого каталога и объявлены рядом с функцией.
    scale = script[script.index("const KRT_SCALE="):]
    out.insert(0, scale[:scale.index("};") + 2])
    return "\n".join(out)


def score(model: dict | None, rank: dict | None = None, site: dict | None = None,
          intent: dict | None = None, catalogue: dict | None = None,
          requirements: dict | None = None) -> dict:
    node = shutil.which("node")
    if not node:
        pytest.skip("node недоступен")
    stub = (
        "const state={krtModels:{},krtRank:{},krtRequirements:{},krtPress:{}};\n"
        f"state.krtModels['site']={json.dumps(model)};\n"
        f"state.krtRank['site']={json.dumps(rank or {})};\n"
        # Шкала считается по САМОМУ каталогу: меньше восьми посчитанных строк —
        # распределения нет, и пороги остаются абсолютными. Соседи нужны только
        # тем проверкам, где мерится относительная шкала.
        + "".join(f"state.krtRank[{json.dumps(slug)}]={json.dumps(row)};\n"
                  for slug, row in (catalogue or {}).items())
        + f"state.krtRequirements['site']={json.dumps(requirements or (intent and {'intent': intent}) or {})};\n"
        + "const document={getElementById:()=>({value:'housing_ready'})};\n"
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
    # Одно снижение за экономику (не три сложенных) плюс два названных пола:
    # мёртвый проект теряет больше половины потенциала, но остаётся числом.
    assert got["score"] < got["base"] * 0.45


def test_an_unpriced_ceiling_is_our_gap_and_costs_nothing() -> None:
    """Наш пробел баллом не наказывают — но и не прячут.

    Снижение за неподобранный потолок стояло у 147 площадок из 153: величина,
    общая почти всем, не различает ничего, а называла она НАШУ неудачу, а не
    свойство площадки. Правило уже записано: непосчитанное не снижает ничего —
    это «не знаем», а не «плохо». Пробел остаётся видимым в подписи.
    """
    with_ceiling = score(model_with(1.30, 20.0, 1.20), {"entry_capacity_rub_per_sqm": 30000})
    without = score(model_with(1.30, 20.0, 1.20), {})
    assert without["cut"] == with_ceiling["cut"]
    assert without["score"] == with_ceiling["score"]
    assert any("потолок входа не подобран" in gap for gap in without["gaps"]), without
    assert with_ceiling["gaps"] == [], with_ceiling


def test_a_counted_model_does_not_pay_for_renovation_twice() -> None:
    """Метры реновации уже не в выручке модели — снижать за них ещё и балл нельзя.

    С 0.21.77 скрининг знает, что они строятся, но не продаются: это часть цены
    входа, уплаченная метрами. Экономика посчитана без этой выручки, и второе
    снижение было бы тем же убытком, посчитанным дважды.
    """
    site = {**SITE, "housing_gfa_sqm": 150940}
    got = score(model_with(1.30, 20.0, 1.20), {"entry_capacity_rub_per_sqm": 30000},
                site=site, requirements={
                    "intent": {"probed": True, "city_needs": ["Программа реновации"]},
                    "renovation": {"mentioned": True, "area_sqm": 15100,
                                   "quote": "передать 15 100 кв. м в Программу реновации"}})
    assert not [c for c in got["cuts"] if "реновац" in c["label"].lower()], got["cuts"]
    # Молча снятое снижение читается как «всё в порядке» — оно названо в пробелах.
    gap = next(g for g in got["gaps"] if "реновац" in g.lower())
    assert "15 100" in gap.replace("\u00a0", " "), gap
    assert "не продаются" in gap and "цены входа" in gap, gap


def test_an_uncounted_model_still_pays_for_the_city_share() -> None:
    """Модель не считалась — вычесть выручку было негде, и снижение остаётся."""
    site = {**SITE, "housing_gfa_sqm": 150940}
    got = score(None, site=site, requirements={
        "intent": {"probed": True, "city_needs": ["Программа реновации"]},
        "renovation": {"mentioned": True, "area_sqm": 15100}})
    cut = next(c for c in got["cuts"] if "реновац" in c["label"].lower())
    assert cut["points"] == 10, got["cuts"]
    assert "10%" in cut["label"], cut["label"]
    assert "модель не считалась" in cut["label"], cut["label"]


def test_an_unnamed_city_share_is_not_the_whole_site() -> None:
    """«Доля неизвестна» — это не «забирают всё» и не «не забирают ничего»."""
    got = score(model_with(1.30, 20.0, 1.20), {"entry_capacity_rub_per_sqm": 30000},
                requirements={
                    "intent": {"probed": True, "city_needs": ["Программа реновации"]},
                    "renovation": {"mentioned": True, "area_sqm": None}})
    cut = next(c for c in got["cuts"] if "городски" in c["label"])
    assert cut["points"] == 10
    assert "объём не назван" in cut["label"], cut["label"]


def test_the_share_is_read_from_the_row_too() -> None:
    """Скрининг кладёт долю в строку рейтинга — без запасного пути её видит
    только тот, кто нажал кнопку в этой вкладке."""
    site = {**SITE, "housing_gfa_sqm": 150940}
    got = score(model_with(1.30, 20.0, 1.20), {
        "entry_capacity_rub_per_sqm": 30000,
        "renovation": {"spp_sqm": 15100, "share": 0.1},
        "requirements": {"intent": {"probed": True,
                                    "city_needs": ["Программа реновации"]}}},
        site=site)
    assert any("реновац" in g.lower() for g in got["gaps"]), got["gaps"]


def test_the_economics_cut_is_one_and_names_the_banks_target() -> None:
    """LLCR, маржа и слабейшая очередь — одно явление, и снижение за них одно.

    Сложенные, три снижения снимали 60–95% у площадки, которая на каждом из
    трёх лишь чуть ниже цели; порог — цель банка, а не процентиль каталога,
    и он назван в подписи рядом со своим числом.
    """
    catalogue = {f"s{index}": {"project_llcr_x": 1.00 + index * 0.05,
                               "margin_pct": 5.0 + index,
                               "weakest_phase_llcr_x": 0.80 + index * 0.03,
                               "entry_capacity_rub_per_sqm": 1000}
                 for index in range(10)}
    got = score(model_with(1.02, 6.0, 0.82),
                {"entry_capacity_rub_per_sqm": 1000}, catalogue=catalogue)
    economics = [c for c in got["cuts"] if "ниже цели банка" in c["label"]]
    assert len(economics) == 1, got["cuts"]
    label = economics[0]["label"]
    assert "1,2x" in label and "1,02x" in label, label
    # Два остальных показателя названы в той же подписи, а не сняты второй раз.
    assert "маржинальность 6%" in label and "слабейшая очередь 0,82x" in label, label
    assert all("каталога" not in c["label"] for c in got["cuts"]), got["cuts"]
    # Балл площадки не зависит от того, кого пересчитали рядом.
    alone = score(model_with(1.02, 6.0, 0.82), {"entry_capacity_rub_per_sqm": 1000})
    assert alone["cut"] == got["cut"] and alone["score"] == got["score"]


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
