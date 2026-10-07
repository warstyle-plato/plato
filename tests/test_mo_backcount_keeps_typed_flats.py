"""Обратный счёт Подмосковья не заменяет вписанные метры квартир.

Вписали в строку «Квартиры» ГНС 215 720,6 — таблица разложила её своими
долями (общая 194 148,5, продаваемая 140 218,4) и запустила нормативный
пересчёт РНГП. Ответ сервера выводит ГНС и общую из продаваемой СВОИМИ долями,
и `Object.assign` молча клал поверх вписанного 220 781,6 и 206 203,5. Под
таблицей при этом писалось только «Нормативы пересчитаны…» — о замене ни слова.

Из ответа берётся производное (число квартир, социалка, паркинг, плата за
ВРИ); вписанные площади остаются; пояснение называет, что поменялось.

Стенд гоняет НАСТОЯЩИЕ `tepCellChanged`, `scheduleTepAutoRecalc`,
`recalcMoFromApartments` и `applyNormativeTep`, а ответ `/mo/calculate` берёт
у самого сервера.

Запуск: python3 -m pytest tests/test_mo_backcount_keeps_typed_flats.py -q
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import main_legacy as core  # noqa: E402
from tests import page_blocks  # noqa: E402

AREA_HA = 14.62
TYPED_GNS = 215_720.6
# Строка после «Рассчитать ТЭП от площади и плотности» на этом участке.
BEFORE = {"gns": 690_599.91, "total_area": 645_000.0, "useful": 438_600.0,
          "saleable": 438_600.0, "transfer": 0, "units": 7_459.18}


@pytest.fixture(scope="module")
def shown():
    from fastapi.testclient import TestClient
    import main_registry

    ratio = core.TEP_RATIOS["apartments"]
    saleable = round(TYPED_GNS * ratio["saleable_of_gns"], 1)
    answer = TestClient(main_registry.app).post("/mo/calculate", json={
        "query": "", "limit": 30, "site_area_ha": AREA_HA,
        "density_sqm_per_ha": saleable / AREA_HA, "district": "",
        "market_price_rub_per_sqm": 0, "vri_kd": 0, "average_flat_sqm": 58.8,
    })
    assert answer.status_code == 200, answer.text
    server = answer.json()

    tep = json.loads(json.dumps(core.TEP_DEFAULT, ensure_ascii=False))
    tep["apartments"].update(BEFORE)
    prelude = "\n".join([
        "let inputs={site_area_ha:" + str(AREA_HA) + ",_mo_calc:{apartments_saleable:"
        + str(BEFORE["saleable"]) + "}};",
        "let tep=" + json.dumps(tep, ensure_ascii=False) + ";",
        "const SERVER=" + json.dumps(server, ensure_ascii=False) + ";",
        # Переменные страницы, которые в рабочем окне задаёт загрузка проекта.
        "let cadastralAnalysis=null,moResult=null;",
        "let posted=0;",
        "async function fetch(url){posted++;return {ok:true,json:async()=>SERVER}}",
        "const notes={};",
        "const document={getElementById(id){return notes[id]||(notes[id]={style:{},innerHTML:'',value:''})},"
        "activeElement:null};",
        # Таймер ловится, а не ждётся: отложенный пересчёт зовётся руками.
        "let timer=null;",
        "const setTimeout=(fn)=>{timer=fn;return 1};",
        "const clearTimeout=()=>{};",
        # Отрисовка и расчёт экономики к строке ТЭП отношения не имеют.
        "function renderTep(){}",
        "function renderInputs(){}",
        "function updateTepTotals(){}",
        "function renderPhasing(){}",
        "async function calculate(){}",
        "function syncTep(){}",
        "function escapeHtml(s){return String(s)}",
        "function num(v){return Number(v||0).toFixed(1)}",
        "function landNum(v,d){return Number(v||0).toFixed(d===undefined?1:d)}",
    ])
    tail = "\n".join([
        f"tepCellChanged('apartments','gns',{TYPED_GNS});",
        "const typed=JSON.parse(JSON.stringify(tep.apartments));",
        "(async()=>{",
        " if(!timer)throw new Error('правка квартир не запустила обратный счёт');",
        " timer();",
        # Таймер страницы промиса не возвращает; пересчёт закончен, когда
        # снята его же отсечка от повторного входа.
        " for(let i=0;i<1000&&moAutoBusy;i++)await new Promise(r=>setImmediate(r));",
        " if(moAutoBusy)throw new Error('обратный счёт не закончился');",
        # Отказ страница ловит и пишет в пояснение. Недостающее имя стенда
        # пробрасывается наружу: разрешитель доберёт его со страницы, а не
        # оставит падение про стенд под видом отказа расчёта.
        " const gap=/([A-Za-z_$][\\w$]*) is not defined/.exec((notes.tepDerivedNote||{}).innerHTML||'');",
        " if(gap)throw new ReferenceError(gap[1]+' is not defined');",
        " console.log(JSON.stringify({typed,after:tep.apartments,posted,",
        "  note:(notes.tepDerivedNote||{}).innerHTML||'',",
        "  kindergarten:tep.kindergarten.units}));",
        "})().catch(e=>{console.error(e);process.exit(1)});",
    ])
    out, taken = page_blocks.run(prelude, tail)
    result = json.loads(out)
    result["server"] = server
    result["taken"] = taken
    return result


def test_the_stand_runs_the_real_path(shown):
    for name in ("tepCellChanged", "scheduleTepAutoRecalc",
                 "recalcMoFromApartments", "applyNormativeTep"):
        assert name in shown["taken"], f"стенд обязан гонять настоящий {name}"
    assert shown["posted"] == 1


def test_the_server_would_have_replaced_the_typed_gns(shown):
    """Предохранитель: если сервер отдаёт ту же ГНС, проверять нечего."""
    offered = float(shown["server"]["tep"]["apartments"]["gns"])
    assert abs(offered - TYPED_GNS) > 1000, offered


def test_the_typed_areas_survive_the_recalc(shown):
    typed, after = shown["typed"], shown["after"]
    assert typed["gns"] == pytest.approx(TYPED_GNS)
    for col in ("gns", "total_area", "saleable"):
        assert after[col] == pytest.approx(typed[col], abs=0.05), (
            f"{col}: вписано {typed[col]}, после пересчёта {after[col]}")


def test_the_derived_numbers_still_follow(shown):
    """Число квартир — выход формулы от продаваемой; прежнее описывало
    прежние 438 600 м². Социалка тоже идёт за объёмом."""
    server = shown["server"]["tep"]
    assert shown["after"]["units"] == pytest.approx(float(server["apartments"]["units"]))
    assert shown["after"]["units"] < BEFORE["units"] / 2
    assert shown["kindergarten"] == pytest.approx(float(server["kindergarten"]["units"]))


def test_the_note_names_what_changed(shown):
    note = shown["note"]
    assert "сохранены" in note and f"{TYPED_GNS:.1f}" in note, note
    assert f"было {BEFORE['units']:.1f} → стало" in note, note
    offered = float(shown["server"]["tep"]["apartments"]["gns"])
    assert f"{offered:.1f}" in note and "не подставлено" in note, note
