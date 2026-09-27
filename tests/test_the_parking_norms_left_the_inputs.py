"""Блок «Нормативы парковки нежилья» во «Вводных» не нужен (владелец, 27.09.2026).

«Почему мы до сих пор не спрятали этот блок». Шесть полей трёх разных видов:
- площадь подземного места гаража ОСЗ — норматив класса, тот же, что у
  паркинга дома (35 / 37,5 / 40): своего поля больше нет;
- площадь места на первых этажах — в «Настройках класса» (пока 25 везде);
- К1, расстояние до станции, К2 и край норматива Подмосковья — свойства
  участка: карточка «Участок и плотность».

Запуск: python3 -m pytest tests/test_the_parking_norms_left_the_inputs.py -q
"""

from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import page_blocks  # noqa: E402
import main_legacy as core  # noqa: E402


def test_the_garage_place_follows_the_class() -> None:
    """Смена класса двигает гараж ОСЗ так же, как паркинг дома."""
    def garage(klass: str) -> float:
        x = copy.deepcopy(core.DEFAULT_INPUTS)
        x.update({"offices_enabled": True, "offices_parking_under_spaces": 100,
                  "_parking_by_hand": ["offices"],
                  "underground_area_per_space_sqm":
                      core.PROJECT_CLASS_PRESETS[klass]["underground_area_per_space_sqm"]})
        t = copy.deepcopy(core.TEP_DEFAULT)
        t["offices"].update({"gns": 10_000, "total_area": 9_000,
                             "useful": 6_000, "saleable": 6_000})
        core.apply_object_parking(x, t)
        return t["offices"]["under_gns"]
    assert garage("comfort") == pytest.approx(100 * 35)
    assert garage("elite") == pytest.approx(100 * 40)


def test_the_first_floor_place_lives_in_the_class() -> None:
    for preset in core.PROJECT_CLASS_PRESETS.values():
        assert preset["object_parking_over_area_per_space_sqm"] == 25
    assert "object_parking_over_area_per_space_sqm" in core.CLASS_ONLY_INPUTS


def test_the_inputs_do_not_draw_the_block_and_the_site_card_does() -> None:
    """Страница: группа не рисуется во «Вводных», поля участка — в карточке."""
    prelude = """
const nodes={};
function mk(tag){return {tag,children:[],style:{},dataset:{},innerHTML:'',textContent:'',value:'',
 appendChild(c){this.children.push(c);return c},contains(){return false}};}
const box=mk('div');
const document={activeElement:null,getElementById:id=>id==='siteParkingFields'?box:null,
 createElement:mk};
let inputs={parking_k1:0.9,parking_rail_distance_m:'',parking_k2:'',parking_design_mode:'minimum'};
let phaseBundle=null, lastResult=null;
"""
    tail = """
renderSiteParkingFields();
const ids=box.children.map(w=>w.children[0].id);
const values=box.children.map(w=>w.children[0].value);
process.stdout.write(JSON.stringify({ids,values,
  hidden:FIELD_GROUPS.filter(g=>!g[1].some(f=>!notOnInputs(f[0]))).map(g=>g[0])}));
"""
    out = page_blocks.run_json(prelude, tail)
    assert out["ids"] == ["site_parking_k1", "site_parking_rail_distance_m",
                          "site_parking_k2", "site_parking_design_mode"]
    assert out["values"][0] == 0.9 and out["values"][1] == ""
    assert out["values"][3] == "minimum"
    assert "Нормативы парковки нежилья (общие на объекты)" in out["hidden"]


def test_an_unset_coefficient_is_empty_not_zero() -> None:
    """Прод 0.24.50: в К1, К2 и расстоянии стоял 0, а подсказка обещала пустоту.

    Пустое поле — не ноль (CLAUDE.md). Умолчание — пустота; старый проект с
    нулём считается так же, как пустой: цепочка «по расстоянию → по району →
    1,0» работает в обоих случаях, а ноль норму мест не обнуляет.
    """
    for key in ("parking_k1", "parking_rail_distance_m", "parking_k2"):
        assert core.DEFAULT_INPUTS[key] == "", key

    def parking(**over):
        x = copy.deepcopy(core.DEFAULT_INPUTS)
        x.update({"offices_enabled": True}, **over)
        t = copy.deepcopy(core.TEP_DEFAULT)
        t["offices"].update({"gns": 10_000, "total_area": 9_000,
                             "useful": 6_000, "saleable": 6_000})
        return core.calculate(core.CalcRequest(inputs=x, tep=t, rates=[]))["parking"]
    empty, zero = parking(), parking(parking_k1=0, parking_k2=0, parking_rail_distance_m=0)
    assert empty["k1"] == zero["k1"] == 1.0 and empty["k_origin"] == zero["k_origin"]
    assert empty["required_total"] == zero["required_total"] > 0


def test_the_site_card_shows_what_the_calculation_took() -> None:
    prelude = """
function mk(tag){return {tag,children:[],style:{},innerHTML:'',textContent:'',value:'',placeholder:'',
 appendChild(c){this.children.push(c);return c},contains(){return false}};}
const box=mk('div');
const document={activeElement:null,getElementById:id=>id==='siteParkingFields'?box:null,createElement:mk};
let phaseBundle=null;
let lastResult={parking:{k1:1,k2:1,k_origin:{k1:'upper_edge',k2:'upper_edge'}}};
let inputs={parking_k1:0,parking_rail_distance_m:'',parking_k2:0,parking_design_mode:'maximum'};
"""
    tail = """
renderSiteParkingFields();
process.stdout.write(JSON.stringify(box.children.map(w=>[w.children[0].id,w.children[0].value,w.children[0].placeholder||''])));
"""
    got = {row[0]: row[1:] for row in page_blocks.run_json(prelude, tail)}
    assert got["site_parking_k1"][0] == "", "старый ноль показан числом"
    assert "авто: 1" in got["site_parking_k1"][1] and "верхний край" in got["site_parking_k1"][1]
