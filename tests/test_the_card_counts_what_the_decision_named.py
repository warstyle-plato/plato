"""Считаем то, что документ назвал, а не только то, что мы привыкли читать.

«Как это нет данных и сразу есть?» (владелец, 08.09.2026, карточка Рубцовской
наб., влд. 3). Сверху карточки стояло «В проекте решения нет жилого объёма» и
«Балл площадки: — · ТЭП не указан», а двумя блоками ниже — «Квартиры по
решению 4 290 м²» и «Нежилая наземная 16 200 м²» из того же PDF.

Причина: это ДВЕ РАЗНЫЕ ПАРЫ величин под похожими именами. Балл и модель
читают жилую и нежилую СПП (`housing_gfa_sqm`, `business_gfa_sqm`); решение
называет площадь квартир и нежилую наземную (`flats_sqm`,
`nonresidential_ground_sqm`) — свои поля со своей базой. Карточка их печатала,
потому что документ их назвал; балл и модель их не видели.

Замер прода 08.09.2026: 18 строк из 598 — у 11 названы квартиры, у 17 нежилая
наземная, и ни одной величины, которую балл умел мерить.

Запуск: python3 -m pytest tests/test_the_card_counts_what_the_decision_named.py -q
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import main_legacy as core  # noqa: E402
from auction_search import ui  # noqa: E402
from auction_search.krt_screening import build_krt_model_screening  # noqa: E402

PAGE = ui.AUCTIONS_PAGE


def _market(price: int = 400_000) -> dict:
    return {
        "analysis": {"site": {"segment": "комфорт", "price_per_sqm": price,
                              "sold_lot_avg": 45.0, "units_per_month": 12.0}},
        "price_hint": {"entry_per_sqm": price, "price_per_sqm": price},
    }


# Рубцовская наб., влд. 3 — площадка-решение с проды: жилой СПП документ не
# называет, площадь квартир называет.
FLATS_ONLY = {"slug": "decision:333331220", "name": "Рубцовская наб., влд. 3",
              "no_card": True, "area_ha": 0.73, "flats_sqm": 4_290.0,
              "nonresidential_ground_sqm": 16_200.0}


def test_the_model_counts_the_housing_product_from_the_flats_the_decision_named() -> None:
    """Продаваемая равна числу ГОРОДА, а не нашему пересчёту.

    Жилой объём восстанавливается той же долей, которой модель считает
    продаваемую, и в обратную сторону: своя вторая доля дала бы два ответа на
    «сколько квартир в жилом объёме», и оба выглядели бы верными.
    """
    got = build_krt_model_screening(FLATS_ONLY, _market(), core)
    assert got["available"] is True, got.get("reason")
    assert got["phasing"]["saleable_sqm"] == round(FLATS_ONLY["flats_sqm"])


def test_the_restored_volume_is_named_restored() -> None:
    """«Принят за ГНС» рядом с числом, которого в документе нет, читается как
    цифра города."""
    got = build_krt_model_screening(FLATS_ONLY, _market(), core)
    said = " ".join(got["assumptions"])
    assert "восстановлен из площади квартир" in said, said
    assert "НАШ пересчёт" in said, said


def test_more_flats_than_housing_is_a_refusal_not_a_number() -> None:
    """Квартиры — часть жилой СПП, больше неё их не бывает.

    На проде такие пары есть: Енисейская 89 690 при 67 580 и Красного маяка
    108 060 при 3 450. Это ошибка разбора решения, и считать по ней нельзя ни
    по одному из двух чисел.
    """
    broken = {**FLATS_ONLY, "housing_gfa_sqm": 3_450.0, "flats_sqm": 108_060.0}
    got = build_krt_model_screening(broken, _market(), core)
    assert got["available"] is False
    assert "больше жилого объёма" in got["reason"], got["reason"]


def test_a_site_where_nothing_is_named_still_refuses() -> None:
    """Починка не должна сделать отказ невозможным: молчащий документ молчит."""
    silent = {"slug": "decision:1", "name": "Молчит", "no_card": True, "area_ha": 2.0}
    got = build_krt_model_screening(silent, _market(), core)
    assert got["available"] is False
    assert "ни площади квартир" in got["reason"], got["reason"]


# --- балл: мера называется, и она своя у каждой величины -------------------

def _piece(head: str) -> str:
    start = PAGE.index(head)
    if head.startswith("function"):
        opener = PAGE.index("{", PAGE.index(")", start))
    else:
        opener = min(i for i in (PAGE.find("{", start), PAGE.find("[", start)) if i >= 0)
    depth, index, seen = 0, opener, False
    while index < len(PAGE):
        if PAGE[index] in "{[":
            depth, seen = depth + 1, True
        elif PAGE[index] in "}]":
            depth -= 1
            if seen and depth == 0:
                return PAGE[start:index + 1]
        index += 1
    raise AssertionError(f"не нашёл конец: {head}")


def _line(head: str) -> str:
    start = PAGE.index(head)
    return PAGE[start:PAGE.index("\n", start)]


def _fit(row: dict, purpose: list[str] | None = None) -> dict:
    node = shutil.which("node")
    if not node:
        pytest.skip("node недоступен")
    program = "\n".join([
        "function esc(s){return String(s==null?'':s)}",
        "const state={krtRank:{},krtModels:{},krtCards:{},krtPress:{},krtTenders:{},"
        "krtOrderBySite:{},krtOrders:{},krtTenderLinks:{},krtRequirements:{},"
        f"krtPick:{{purpose:new Set({json.dumps(purpose or [])})}}}};",
        _piece("const KRT_SCALE="), _line("const fmtArea="),
        _piece("function krtBroken("), _piece("function krtNumber("),
        _piece("function krtVolumeShare("), _piece("function krtTaskProfile("),
        _piece("function krtFit("),
        f"const fit=krtFit({json.dumps(row)});",
        "console.log(JSON.stringify({measure:fit.measure,reasons:fit.reasons,"
        "checks:fit.checks,score:fit.score,known:fit.known}));",
    ])
    done = subprocess.run([node, "-e", program], capture_output=True, text=True, timeout=60)
    assert done.returncode == 0, done.stderr[:800]
    return json.loads(done.stdout)


def test_the_score_is_measured_by_the_flats_the_decision_named() -> None:
    """Мера названа, и площадка перестала быть «ТЭП не указан».

    Балл при этом остаётся нулевым, и это верно: 4 290 м² квартир ниже
    десятого процентиля каталога — площадка правда крошечная (0,73 га).
    «Не знаем» и «мало» — разные ответы, и теперь звучит второй.
    """
    got = _fit(FLATS_ONLY)
    assert got["known"], "названный документом объём остался «не указан»"
    assert got["measure"] == "площадь квартир", got
    assert any("площадь квартир" in one for one in got["reasons"]), got


def test_a_large_flats_area_actually_earns_points() -> None:
    """Шкала обязана различать: иначе новая мера — не мера, а метка."""
    big = {**FLATS_ONLY, "slug": "decision:big", "flats_sqm": 90_000.0}
    got = _fit(big)
    assert got["measure"] == "площадь квартир" and got["score"] > 0, got


def test_a_business_task_is_measured_by_the_nonresidential_ground_area() -> None:
    """Порядок последней ступени — по задаче: деловой ближе нежилая наземная."""
    got = _fit(FLATS_ONLY, purpose=["business"])
    assert got["measure"] == "нежилая наземная площадь", got


def test_each_new_measure_has_its_own_scale() -> None:
    """Мерить чужой шкалой — то же, что назвать одну величину другой."""
    scale = _piece("const KRT_SCALE=")
    assert "flats:" in scale and "ground:" in scale, scale


# --- кнопка передачи -------------------------------------------------------

def test_the_handoff_button_is_dark_before_it_is_pressed() -> None:
    """Отказ, о котором сказано заранее, — свойство площадки; отказ после
    клика — поломка."""
    node = shutil.which("node")
    if not node:
        pytest.skip("node недоступен")
    program = "\n".join([
        "const state={krtModels:{},krtScreening:{}};",
        _piece("function krtBroken("), _piece("function krtHandoffBlock("),
        "const x={slug:'decision:1'};",
        "const cold=krtHandoffBlock(x,null);",
        "state.krtScreening['decision:1']={available:false,reason:'в решении нет объёма'};",
        "const said=krtHandoffBlock(x,null);",
        "state.krtScreening['decision:1']={available:true};",
        "const open=krtHandoffBlock(x,null);",
        "console.log(JSON.stringify({cold,said,open}));",
    ])
    done = subprocess.run([node, "-e", program], capture_output=True, text=True, timeout=60)
    assert done.returncode == 0, done.stderr[:800]
    got = json.loads(done.stdout)
    assert got["cold"], "непосчитанная модель не погасила кнопку"
    assert "в решении нет объёма" in got["said"], got["said"]
    assert got["open"] == "", "посчитанная модель оставила кнопку погашенной"


def test_the_refusal_is_printed_where_the_button_is() -> None:
    """Причина уезжала в `krtShareNote` первой группы — двумя экранами выше
    кнопки, — и человек видел только серый «Передаю»."""
    handler = _piece("async function handoffKrt(")
    assert "$('krtHandoffNote')" in handler, handler[:300]
    assert "krtShareNote" not in handler, "отказ снова печатается в чужой группе"
    # И сам узел стоит рядом с кнопкой, а не в другой группе карточки.
    button = PAGE.index("id=\"krtHandoff\"")
    note = PAGE.index("id=\"krtHandoffNote\"")
    assert 0 < note - button < 1200, "узел отказа далеко от кнопки"


def test_the_handoff_button_does_not_rename_itself() -> None:
    """Нарисована «Передать в расчёт DevelopAid», а `finally` возвращал
    «Передать в DevelopAid»: после первого нажатия имя менялось молча."""
    assert PAGE.count("const KRT_HANDOFF_LABEL=") == 1
    assert "'Передать в DevelopAid'" not in PAGE, "вторая подпись у той же кнопки"
