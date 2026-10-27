"""Территория КРТ из нескольких участков — корпуса на её карте, а не квадрат молча.

Владелец (26.10.2026, прод, телефон): «А куда делось показать на участке?».
Территория КРТ из нескольких участков, площадь в расчёте 56 400 м². Схема
писала «Площадь контура из ЕГРН (65 м²) заметно отличается…», рисовала участок
квадратом, а кнопка «Показать корпуса на карте участка» молча пропадала.

Решения:
- контур схемы — объединение ВСЕХ найденных земельных участков поиска; здание
  и помещение (`kind` из ответа поиска) — не земля участка, в контур не идут;
- не сходится объединение с площадью расчёта или границ нет — на месте кнопки
  фраза: какие участки найдены, их сумма, площадь в расчёте, что не вошло.

На прежнем коде падает: пятно здания входило в контур участка, а на месте
кнопки не было ничего.

Запуск: python3 -m pytest tests/test_a_krt_territory_is_drawn_on_the_map.py -q
"""

from __future__ import annotations

import copy
import math
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

import browser  # noqa: E402

import main as _wrapper  # noqa: E402

core = _wrapper.core

SITE_SQM = 56400.0
LAT, LNG = 55.70, 37.65


def _merc(shape):
    k = math.cos(math.radians(LAT))
    y0 = math.log(math.tan((90 + LAT) * math.pi / 360)) / (math.pi / 180) * 20037508.34 / 180
    x0 = LNG * 20037508.34 / 180
    return [[x0 + a / k, y0 + b / k] for a, b in shape]


def _rect(x0, y0, w, h):
    return _merc([(x0, y0), (x0 + w, y0), (x0 + w, y0 + h), (x0, y0 + h)])


def _territory():
    """Три смежных участка ≈ 56 400 м² и здание на одном из них."""
    return {"query": "КРТ", "found_count": 4, "results": [
        {"found": True, "kind": "land", "cadastral_number": "77:01:0001001:11",
         "contour_merc": [_rect(0, 0, 120, 160)]},
        {"found": True, "kind": "land", "cadastral_number": "77:01:0001001:12",
         "contour_merc": [_rect(120, 0, 120, 160)]},
        {"found": True, "kind": "land", "cadastral_number": "77:01:0001001:13",
         "contour_merc": [_rect(240, 0, 112.5, 160)]},
        {"found": True, "kind": "building", "cadastral_number": "77:01:0001001:2001",
         "contour_merc": [_rect(20, 20, 60, 40)]},
    ]}


def _tiny():
    """Как на проде: найден один крошечный участок, второй не найден, третье — здание."""
    return {"query": "КРТ", "found_count": 2, "results": [
        {"found": True, "kind": "land", "cadastral_number": "77:01:0001001:15",
         "contour_merc": [_rect(0, 0, 13, 5)]},
        {"found": False, "cadastral_number": "77:01:0001001:16"},
        {"found": True, "kind": "building", "cadastral_number": "77:01:0001001:2002",
         "contour_merc": [_rect(40, 40, 30, 30)]},
    ]}


def _layout(lookup):
    x = copy.deepcopy(core.DEFAULT_INPUTS)
    x["_land_lookup"] = lookup
    return core.site_massing_layout(x, {"site_sqm": SITE_SQM, "footprint_sqm": 12000.0,
                                        "setback_m": 3.0},
                                    [{"phase": 1, "above_gns_sqm": 150000.0}])


def test_the_territory_is_the_union_of_its_land_parcels():
    layout = _layout(_territory())
    assert layout["site_shape_origin"] == "contour"
    assert layout["map_note"] == ""
    # Три участка — три кольца; пятно здания в контур не вошло.
    assert len(layout["site_rings"]) == 3
    contour = sum(abs(core._ring_area(r)) for r in layout["site_rings"])
    assert contour == pytest.approx(SITE_SQM, rel=0.01)
    assert layout["buildings"] and all(b.get("ring_merc") for b in layout["buildings"]
                                       if b.get("ring_m"))


def test_a_tiny_parcel_says_why_there_is_no_map():
    layout = _layout(_tiny())
    assert layout["site_shape_origin"] == "square"
    note = layout["map_note"].replace("\xa0", " ")
    for words in ("77:01:0001001:15 — 65 м²", "56 400 м²", "77:01:0001001:16",
                  "77:01:0001001:2002", "квадратом"):
        assert words in note, (words, note)
    assert note in layout["notes"]


def test_without_any_contour_the_reason_is_named():
    layout = _layout({"results": []})
    assert layout["site_shape_origin"] == "square"
    assert "границ участка из госреестра нет" in layout["map_note"]


# --- Отрисованная страница ---------------------------------------------------

SET = """async (lookup)=>{
 setSiteArea(%s); await settledCalculate();
 inputs._land_lookup=cloneValue(lookup); landLookup=cloneValue(lookup);
 await settledCalculate();
 openTab('tep'); renderTep();
 const box=document.getElementById('siteMassingScheme');
 const button=document.getElementById('siteMassingMapButton');
 const note=document.getElementById('siteMassingMapNote');
 const visible=n=>!!n&&n.getBoundingClientRect().height>0;
 const out={button:visible(button), note:visible(note)?note.innerText:'',
            text:box?box.innerText:''};
 if(button){button.click();
  out.corpora=Array.from(document.querySelectorAll('#landMapStage .land-map-corpus')).length;}
 return out;
}""" % (SITE_SQM / 10000.0)


@pytest.fixture(scope="module")
def seen():
    pytest.importorskip("playwright.sync_api")
    from playwright.sync_api import sync_playwright

    path = browser.chromium_or_skip()
    out: dict = {}
    with browser.serve(core.app, 18194) as base, sync_playwright() as pw:
        with pw.chromium.launch(executable_path=str(path)) as engine:
            for name, lookup in (("territory", _territory()), ("tiny", _tiny())):
                page = engine.new_page(viewport={"width": 390, "height": 844})
                page.goto(base, wait_until="domcontentloaded")
                browser.wait_for_result(page)
                out[name] = page.evaluate(SET, lookup)
                page.close()
    return out


def test_the_page_shows_the_corpora_on_the_territory(seen):
    got = seen["territory"]
    assert got["button"], got
    assert got.get("corpora", 0) > 0, got
    assert not got["note"]


def test_the_page_says_why_instead_of_hiding_the_button(seen):
    got = seen["tiny"]
    assert not got["button"]
    note = got["note"].replace("\xa0", " ")
    assert "Корпуса на карте участка не показаны" in note and "56 400 м²" in note, got
    # Фраза — одна, на месте кнопки, а не повтором среди пояснений.
    assert got["text"].count("Корпуса на карте участка не показаны") == 1, got["text"]


# --- Повторы и наложения ------------------------------------------------------
# Замечание «Посадки ↔ нормативы» к #947: «объединение» было суммой площадей
# колец — участок 100 × 100, переданный дважды, давал 20 008 м² вместо 10 004,
# причина называла неверную сумму, наложение рисовалось двойным контуром.

def _layout_for(results, site_sqm):
    x = copy.deepcopy(core.DEFAULT_INPUTS)
    x["_land_lookup"] = {"results": results}
    return core.site_massing_layout(x, {"site_sqm": site_sqm, "footprint_sqm": 0.2 * site_sqm,
                                        "setback_m": 3.0},
                                    [{"phase": 1, "above_gns_sqm": site_sqm}])


def _land(number, ring):
    return {"found": True, "kind": "land", "cadastral_number": number, "contour_merc": [ring]}


def test_a_parcel_given_twice_is_one_parcel():
    # Тот же номер — с ведущими нулями и без: один участок.
    layout = _layout_for([_land("77:01:0001001:20", _rect(0, 0, 100, 100)),
                          _land("77:01:1001:20", _rect(0, 0, 100, 100))], 10000.0)
    assert layout["site_shape_origin"] == "contour", layout["map_note"]
    assert len(layout["site_rings"]) == 1


def test_the_reason_names_the_true_sum_without_repeats():
    layout = _layout_for([_land("77:01:0001001:20", _rect(0, 0, 100, 100)),
                          _land("77:01:0001001:20", _rect(0, 0, 100, 100))], SITE_SQM)
    note = layout["map_note"].replace("\xa0", " ")
    assert "10 000 м²" in note and "20 000" not in note, note


def test_a_part_of_a_unified_holding_is_not_counted_twice():
    # Единое землепользование 200 × 100 и его часть 100 × 100 внутри.
    layout = _layout_for([_land("77:01:0001001:30", _rect(0, 0, 200, 100)),
                          _land("77:01:0001001:31", _rect(50, 0, 100, 100))], 20000.0)
    assert layout["site_shape_origin"] == "contour", layout["map_note"]
    assert len(layout["site_rings"]) == 1
    contour = sum(abs(core._ring_area(r)) for r in layout["site_rings"])
    assert contour == pytest.approx(20000.0, rel=0.01)


def test_a_partial_overlap_is_said_in_words():
    # Два участка 100 × 100 накладываются полосой 50 × 100: земли 15 000 м², сумма 20 000.
    layout = _layout_for([_land("77:01:0001001:40", _rect(0, 0, 100, 100)),
                          _land("77:01:0001001:41", _rect(50, 0, 100, 100))], 17000.0)
    text = " ".join(layout["notes"])
    assert "накладываются" in text and "77:01:0001001:40 и 77:01:0001001:41" in text, text
    # Соседи по общей границе — не наложение.
    layout = _layout_for([_land("77:01:0001001:42", _rect(0, 0, 100, 100)),
                          _land("77:01:0001001:43", _rect(100, 0, 100, 100))], 20000.0)
    assert "накладываются" not in " ".join(layout["notes"])
