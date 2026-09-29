"""Кладовые лежат под землёй и в наземную ГНС не входят.

«Почему у нас кладовки попадают в ГНС? Они же в подземной части» (владелец).
Правило объявлено один раз — `UNDERGROUND_PRODUCTS` и `project_above_gns` в
движке, — а страница в двух местах считала наземную сама и пропускала только
гараж: панель «Участок и плотность» записывала кладовые в «Использовано
наземной ГНС» и в потенциал участка, а площади для свода ставок класса —
в наземную базу. Обе теперь читают правило строки (`tepRowAboveGns`,
`tepRowUnderGns`), которое стоит на плейсхолдере из движка.

Проверяется отрисованный кусок страницы на node: проект с кладовыми ≠ 0, и
их метров нет ни в наземной ГНС участка, ни в наземной базе свода.

Запуск: python3 -m pytest tests/test_the_storage_is_not_above_ground.py -q
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

import main_legacy as core  # noqa: E402
import page_blocks  # noqa: E402

STORAGE = 7_000.0


def _tep() -> dict:
    return {
        "apartments": {"gns": 100_000, "saleable": 60_000},
        "ground_commercial": {"gns": 5_000, "saleable": 4_000},
        "underground_parking": {"gns": 30_000, "saleable": 0},
        "storage": {"gns": STORAGE, "saleable": 3_000},
        "offices": {"gns": 2_000, "saleable": 1_500},
    }


def _above(tep: dict) -> float:
    return core.project_above_gns(tep)


PRELUDE = """
const inputs=%(inputs)s;
let tep=%(tep)s;
const shown={};
const el=id=>{if(!shown[id])shown[id]={id,style:{},value:'',textContent:'',innerHTML:'',placeholder:''};return shown[id];};
const document={getElementById:el,activeElement:null};
const num=v=>String(Math.round(v));
function renderSiteParkingFields(){}
function projectParking(){return {own:[]};}
"""


def _run(tail: str, inputs: dict | None = None) -> dict:
    prelude = PRELUDE % {
        "inputs": json.dumps(inputs or {"site_area_ha": 1, "site_density_sqm_per_ha": 100_000,
                                        "_glavapu_import": {"normalized": {}}}),
        "tep": json.dumps(_tep()),
    }
    return page_blocks.run_json(prelude, tail)


def test_the_engine_keeps_the_storage_underground():
    """Опора проверки: владелец ответа сам не пускает кладовые в наземную."""
    assert "storage" in core.UNDERGROUND_PRODUCTS
    assert _above(_tep()) == pytest.approx(107_000)


def test_the_site_usage_does_not_count_the_storage():
    out = _run("renderSitePanel();console.log(JSON.stringify(shown));")
    assert out["siteUsageLabel"]["textContent"] == "Использовано наземной ГНС"
    # Потенциал 100 000 м² — процент прямо равен тысячам наземных метров.
    assert out["siteUsage"]["textContent"] == num_pct(_above(_tep()) / 100_000 * 100)
    warn = out["siteDensityWarn"]["innerHTML"]
    assert f"<b>{round(_above(_tep()))} м²</b>" in warn
    # Жильё и коммерция 1 этажа — без кладовых; прочие наземные — офисы.
    assert "<b>105000 м²</b>" in warn and "<b>2000 м²</b>" in warn


def num_pct(value: float) -> str:
    return f"{round(value)}%"


def test_the_class_stats_keep_the_storage_underground():
    out = _run("console.log(JSON.stringify(classStatsAreas()));")
    assert out["above_ground_gns_sqm"] == str(round(_above(_tep())))
    assert out["underground_gns_sqm"] == str(round(30_000 + STORAGE))
    assert out["gba_sqm"] == str(round(sum(r["gns"] for r in _tep().values())))


@pytest.mark.parametrize("fn", ["renderSitePanel", "classStatsAreas"])
def test_a_reader_does_not_keep_its_own_underground_list(fn):
    """Копия списка отстала бы от движка: читатель берёт правило строки."""
    body = page_blocks.function(fn)
    assert "'underground_parking'" not in body and "'storage'" not in body
    # Читатель берёт правило строки сам или через общую сумму наземной ГНС.
    assert "tepRowAboveGns" in body or "projectAboveGnsParts" in body
    assert "tepRowAboveGns" in page_blocks.function("projectAboveGnsParts")


def test_the_bot_summary_names_the_above_ground_gns():
    """Сводка ТЭП в Telegram печатает «ГНС» — наземную, без гаража и кладовых."""
    parsed = core.build_freeform_tep("", raw_values={
        "project_name": "Тестовый квартал",
        "site_area_ha": 4.5,
        "apartments_saleable_sqm": 60000,
        "commercial_saleable_sqm": 4000,
    })
    tep = parsed["tep"]
    below = sum(float((tep.get(k) or {}).get("gns") or 0) for k in core.UNDERGROUND_PRODUCTS)
    assert below > 0, "стенд без подземной части ничего не проверяет"
    total = sum(float(r.get("gns") or 0) for r in tep.values())
    assert parsed["summary"]["total_gns_sqm"] == pytest.approx(core.project_above_gns(tep))
    assert parsed["summary"]["total_gns_sqm"] == pytest.approx(total - below)


def test_the_site_panel_repeats_the_tep_total():
    """Приёмка владельца: предупреждение участка и «Использовано наземной ГНС»
    равны итогу таблицы ТЭП на одном проекте — на одной отрисовке.

    На проде итог таблицы был 443 700,6, а предупреждение — 448 000,6: ровно
    4 300 м² кладовых. Итог и панель теперь берут одно правило строки.
    """
    tail = (
        "for(const id of ['tg','ta','tu','ts','tt','tn'])globalThis[id]=el(id);\n"
        "updateTepTotals();\n"
        "console.log(JSON.stringify(shown));\n"
    )
    prelude_extra = "function repairParkingFromGlavapu(){return false;}\n"
    prelude = (PRELUDE % {
        "inputs": json.dumps({"site_area_ha": 1, "site_density_sqm_per_ha": 100_000,
                              "_glavapu_import": {"normalized": {}}}),
        "tep": json.dumps(_tep()),
    }) + prelude_extra
    out = page_blocks.run_json(prelude, tail)
    total = out["tg"]["textContent"]
    assert total == str(round(_above(_tep())))
    warn = out["siteDensityWarn"]["innerHTML"]
    assert f"Наземная ГНС проекта <b>{total} м²</b>" in warn
    assert out["siteUsage"]["textContent"] == f"{round(int(total) / 100_000 * 100)}%"
