"""Баланс территории: пятно застройки, средняя этажность и подземные уровни.

Вопрос владельца (22.10.2026): по пятну застройки понять, сколько этажей у
здания и сколько подземных уровней нужно на машино-места. Решение — «проверка
+ ставка по уровням». Допущения согласованы с владельцем: проезды 15 %
участка, отступ 3 м, коэффициент контура 0,85, надбавки +10 % / +20 %, двор —
площадь благоустройства не меньше нормы региона, открытая стоянка 22,5 м² в
МО и 25 м² в остальных.

Проверочный пример — офис владельца, Пролетарский проспект, вл. 20: участок
0,243 га, наземная ГНС 22 842 м², 68 мест × 35 м² = 2 380 м² под землёй.

Запуск: python3 -m pytest tests/test_site_massing.py -q
"""

from __future__ import annotations

import copy
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import main as _wrapper  # noqa: E402

core = _wrapper.core


def _office(**extra):
    x = copy.deepcopy(core.DEFAULT_INPUTS)
    x.update(project_kind="nonresidential", project_class="business", site_area_ha=0.243,
             project_region="msk", vri_region="msk")
    base = core.class_base_preset("business", "msk", "nonresidential")
    x["main_under_th_per_sqm"] = base["main_under_th_per_sqm"]
    x.update(extra)
    tep = {"underground_parking": {"units": 68, "gns": 2380.0, "total_area": 2380.0},
           "offices": {"gns": 22842.0, "total_area": 22842.0}}
    return x, tep


def test_the_proletarsky_example_gives_fifteen_storeys_and_two_levels():
    x, t = _office()
    assert core.project_above_gns(t) == pytest.approx(22842.0)
    m = core.site_massing(x, t)
    assert m["site_sqm"] == pytest.approx(2430.0)
    assert m["yard_sqm"] == 0.0 and "нет жителей" in m["yard_basis"]
    assert m["driveways_sqm"] == pytest.approx(364.5)
    assert m["setbacks_sqm"] == pytest.approx(2430 - (2430 ** 0.5 - 6) ** 2)
    assert m["footprint_sqm"] == pytest.approx(1510, abs=1)
    assert m["footprint_share"] == pytest.approx(0.62, abs=0.01)
    assert m["footprint_origin"] == "estimate"
    assert 15 <= m["average_storeys"] <= 20
    assert m["average_storeys"] == pytest.approx(22842 / m["footprint_sqm"])
    assert m["underground_sqm"] == pytest.approx(2380.0)
    assert m["underground_levels"] == 2
    rows = m["underground_level_rows"]
    assert rows[0]["area_sqm"] == pytest.approx(m["underground_contour_sqm"] * 0.85)
    assert sum(r["area_sqm"] for r in rows) == pytest.approx(2380.0)
    assert [r["markup_pct"] for r in rows] == [0.0, 10.0]
    expect = (rows[0]["area_sqm"] + rows[1]["area_sqm"] * 1.1) / 2380.0
    assert m["underground_depth_factor"] == pytest.approx(expect)
    assert m["underground_depth_factor"] > 1.0
    assert "двух уровнях" in m["summary"]


def test_the_depth_markup_reaches_the_underground_capex():
    """Надбавка — в деньгах СМР подземной части, а не только на экране."""
    x, t = _office()
    op = core.build_operating_model(x, t)
    factor = op["site_massing"]["underground_depth_factor"]
    rate = float(x["main_under_th_per_sqm"])
    assert op["capex_amounts"]["main_under"] == pytest.approx(
        op["core_under_gns"] * rate * factor * 1000)
    # Старый код считал одной ставкой: проверка падает на нём.
    assert op["capex_amounts"]["main_under"] > op["core_under_gns"] * rate * 1000 * 1.01


@pytest.mark.parametrize("how", ["origin", "class_manual", "deviation"])
def test_a_hand_rate_stays_without_markups(how):
    x, t = _office()
    if how == "origin":
        x["_field_origin"] = {"inputs.main_under_th_per_sqm": {"source": "manual"}}
    elif how == "class_manual":
        x["_class_manual"] = ["main_under_th_per_sqm"]
    else:
        x["main_under_th_per_sqm"] = float(x["main_under_th_per_sqm"]) + 7
    m = core.site_massing(x, t)
    assert m["underground_levels"] == 2
    assert m["underground_rate_by_hand"] is True
    assert m["underground_depth_factor"] == 1.0
    assert "вручную" in m["underground_depth_basis"]


def test_hand_values_are_kept_and_estimates_follow_the_tep():
    x, t = _office(building_footprint_sqm=1200, underground_levels=3)
    m = core.site_massing(x, t)
    assert (m["footprint_sqm"], m["footprint_origin"]) == (1200, "manual")
    assert (m["underground_levels"], m["underground_levels_origin"]) == (3, "manual")
    assert m["average_storeys"] == pytest.approx(22842 / 1200)
    # Без ручных значений оценка следует за ТЭП.
    x2, t2 = _office()
    t2["offices"]["gns"] = 30000.0
    t2["underground_parking"]["gns"] = 4000.0
    m2 = core.site_massing(x2, t2)
    assert m2["average_storeys"] == pytest.approx(30000 / m2["footprint_sqm"])
    assert m2["underground_levels"] == 3


def test_too_many_storeys_are_said_aloud():
    x, t = _office(max_storeys_allowed=9)
    m = core.site_massing(x, t)
    assert any("разрешено не выше 9 этажей" in w and "не помещается" in w
               for w in m["warnings"])
    assert not core.site_massing(*_office(max_storeys_allowed=25))["warnings"]


def test_without_a_site_area_the_reason_is_named():
    x, t = _office(site_area_ha=0)
    m = core.site_massing(x, t)
    assert m["footprint_sqm"] == 0 and m["underground_levels"] == 0
    assert m["underground_depth_factor"] == 1.0
    assert any("Площадь участка не задана" in w for w in m["warnings"])


def _housing(region):
    x = copy.deepcopy(core.DEFAULT_INPUTS)
    x.update(project_kind="residential", site_area_ha=2.0, project_region=region,
             vri_region=region, landscaping_area_per_person_sqm=1.0)
    t = {"apartments": {"gns": 60000.0, "saleable": 45000.0, "units": 900},
         "underground_parking": {"units": 300, "gns": 10500.0}}
    return x, t


def test_the_yard_beside_the_building_is_the_region_norm():
    """Рядом со зданием — двор по норме региона; благоустройство сверх нормы
    может быть на кровле стилобата (владелец 22.10.2026) и пятна не съедает."""
    for region, needle in (("msk", "2152-ПП"), ("mo", "Московской области"),
                           ("other", "СП 42.13330")):
        x, t = _housing(region)
        m = core.site_massing(x, t)
        assert needle in m["yard_basis"], region
        assert m["yard_roof_sqm"] == 0.0
    x, t = _housing("msk")
    x["landscaping_area_per_person_sqm"] = 20
    m = core.site_massing(x, t)
    norm = core._yard_floor(x, t, m["site_sqm"])[0]
    landscaping = core.landscaping_area(x, t)[0]
    assert m["yard_sqm"] == pytest.approx(norm) and landscaping > norm
    assert m["landscaping_sqm"] == pytest.approx(landscaping)
    # На кровлю уходит только то, чему не хватило земли рядом со зданием.
    ground = (m["site_sqm"] - m["footprint_sqm"] - m["driveways_sqm"]
              - m["surface_parking_sqm"] - m["setbacks_sqm"])
    assert m["yard_ground_sqm"] == pytest.approx(ground)
    assert m["yard_roof_sqm"] == pytest.approx(max(0.0, landscaping - max(ground, norm)))


def _one_hectare(**extra):
    """Случай владельца: 1 га в Москве, плотность 28 000 м²/га — 26 410 м² наземной
    ГНС. Прежний расчёт дал пятно 511 м² и 51,7 этажа."""
    x = copy.deepcopy(core.DEFAULT_INPUTS)
    x.update(project_kind="residential", site_area_ha=1.0, project_region="msk",
             vri_region="msk", landscaping_area_per_person_sqm=11)
    x.update(extra)
    t = {"apartments": {"gns": 23076.9, "saleable": 14123.0, "units": 241},
         "ground_commercial": {"gns": 3333.3, "saleable": 2700.0},
         "underground_parking": {"units": 206, "gns": 7200.0}}
    return x, t


def test_a_hectare_with_28000_density_is_not_a_fifty_storey_tower():
    x, t = _one_hectare()
    m = core.site_massing(x, t)
    assert m["above_gns_sqm"] == pytest.approx(26410.2)
    # Рядом со зданием — двор по норме (5 м² на жителя), остальное
    # благоустройство — на кровле стилобата; свободно около половины участка,
    # но жилой дом занимает процент застройки — 30 %: этажность около 8,8.
    assert m["footprint_estimate_sqm"] > 3000
    # Благоустройство 11 м² × 428 жителей = 4 708 м²; рядом со зданием для него
    # 10 000 − 3 000 − 1 500 − 1 164 = 4 336 м², на кровлю — остаток 372 м².
    assert m["yard_ground_sqm"] == pytest.approx(10000 - 3000 - 1500 - m["setbacks_sqm"])
    assert m["yard_roof_sqm"] == pytest.approx(m["landscaping_sqm"] - m["yard_ground_sqm"])
    assert "кровле стилобата" in m["yard_basis"]
    assert (m["footprint_origin"], m["coverage_pct"], m["coverage_origin"]) == (
        "coverage", 30.0, "default")
    assert m["footprint_sqm"] == pytest.approx(3000)
    assert m["average_storeys"] == pytest.approx(26410.2 / 3000)
    assert not m["warnings"]


def test_a_hand_footprint_that_eats_the_norm_yard_is_said_aloud():
    """Пятно руками больше свободного места — двор по норме не помещается, и это сказано."""
    x, t = _one_hectare(building_footprint_sqm=6000)
    m = core.site_massing(x, t)
    assert m["footprint_origin"] == "manual"
    assert m["footprint_shortage_sqm"] == pytest.approx(6000 - m["footprint_estimate_sqm"])
    assert any("двор по норме на участке не помещается" in w for w in m["warnings"])
    assert not core.site_massing(*_one_hectare(building_footprint_sqm=3000))["warnings"]


def test_the_coverage_from_the_town_plan_wins_and_offices_have_no_default():
    m = core.site_massing(*_one_hectare(site_coverage_max_pct=40))
    assert (m["footprint_sqm"], m["coverage_origin"]) == (pytest.approx(4000), "manual")
    # Нежилой проект: процента по умолчанию нет — пятно всё свободное место.
    office = core.site_massing(*_office())
    assert office["coverage_origin"] == "none" and office["footprint_origin"] == "estimate"
    capped = core.site_massing(*_office(site_coverage_max_pct=50))
    assert capped["footprint_origin"] == "coverage"
    assert capped["footprint_sqm"] == pytest.approx(2430 * 0.5)


def test_a_remainder_too_small_takes_the_footprint_by_the_limit():
    """Остаток участка дал бы здание выше 25 этажей — пятно по пределу, нехватка числом."""
    x, t = _one_hectare(surface_parking_spaces=200)
    m = core.site_massing(x, t)
    assert m["footprint_estimate_sqm"] < 26410.2 / 25
    assert m["footprint_origin"] == "limit"
    assert m["storeys_limit"] == 25 and m["storeys_limit_origin"] == "default"
    assert m["average_storeys"] == pytest.approx(25)
    assert m["footprint_sqm"] == pytest.approx(26410.2 / 25)
    assert m["footprint_shortage_sqm"] == pytest.approx(
        m["footprint_sqm"] - m["footprint_estimate_sqm"])
    [warning] = m["warnings"]
    assert "выше 25 этажей расчёт здание не ставит" in warning and "не хватает" in warning
    # С пределом участка — по нему.
    m9 = core.site_massing(*_one_hectare(surface_parking_spaces=200, max_storeys_allowed=9))
    assert m9["average_storeys"] == pytest.approx(9)
    assert any("разрешено не выше 9 этажей" in w for w in m9["warnings"])
    # Места нет вовсе — то же правило, а не пятно 0.
    m0 = core.site_massing(*_one_hectare(surface_parking_spaces=400))
    assert m0["footprint_estimate_sqm"] == 0 and m0["footprint_sqm"] == pytest.approx(26410.2 / 25)


def test_surface_parking_land_by_region():
    for region, per in (("mo", 22.5), ("msk", 25.0), ("other", 25.0)):
        x, t = _housing(region)
        x["surface_parking_spaces"] = 10
        m = core.site_massing(x, t)
        assert m["surface_parking_sqm"] == pytest.approx(10 * per), region


def test_a_phase_reads_the_project_levels():
    x, t = _office()
    project = core.site_massing(x, t)
    x["_site_massing_project"] = project
    half = copy.deepcopy(t)
    half["underground_parking"]["gns"] = 1190.0
    assert core.site_massing(x, half)["underground_depth_factor"] == project[
        "underground_depth_factor"]


def test_the_pdf_prints_the_engine_line():
    """PDF печатает фразу движка и его предупреждение — тот же расчёт."""
    import io

    pypdf = pytest.importorskip("pypdf")
    x, t = _office(max_storeys_allowed=9, offices_enabled=True, offices_gba_sqm=22842,
                   offices_parking_under_spaces=68, _parking_by_hand=["offices"])
    t = {"offices": {"gns": 22842.0, "total_area": 22842.0}}
    bundle = core._run_authoritative_model(x, t, [], {})
    m = bundle["consolidated"]["tep"]["site_massing"]
    assert m["underground_levels"] == 2 and m["warnings"], m
    pdf = core._build_developaid_pdf({
        "result": bundle["consolidated"], "phases": bundle.get("phases") or [],
        "inputs": x, "tep": t, "rates": [], "phasing": {}, "scenario": "base",
        "cadastral_numbers": []})
    text = " ".join(" ".join(p.extract_text() for p in pypdf.PdfReader(io.BytesIO(pdf)).pages)
                    .split())
    assert "Пятно застройки и этажность" in text and "Подземных уровней 2" in text, text[:3000]
    assert "разрешено не выше 9 этажей" in text


def _with_glavapu(x, green_ha, units):
    x["_glavapu_import"] = {"source": {"export_date": "06.10.2026"},
                            "normalized": {"green_zhk_ha": green_ha, "apartment_units": units}}
    return x


def test_the_yard_norm_is_the_larger_of_ours_and_the_glavapu_row_57():
    """Москва с выгрузкой ГлавАПУ: двор по норме — большее из нашей нормы и строки 57
    (владелец 22.10.2026); строка посчитана для квартир выгрузки."""
    x, t = _housing("msk")
    ours = core.site_massing(x, t)["yard_sqm"]
    assert ours == pytest.approx(5.0 * 1364)
    m = core.site_massing(_with_glavapu(x, 1.0, 900), t)
    assert m["yard_sqm"] == pytest.approx(10000.0)
    assert "ГлавАПУ, выгрузка от 06.10.2026, лист «ТЭП», строка 57" in m["yard_basis"]
    assert "квартиры × 2,1" in m["yard_basis"]
    # Строка 57 меньше нашей нормы — остаётся наша.
    x, t = _housing("msk")
    assert core.site_massing(_with_glavapu(x, 0.5, 900), t)["yard_sqm"] == pytest.approx(ours)
    # Квартир в ТЭП уже не столько, сколько в выгрузке, — снимок устарел и не берётся.
    x, t = _housing("msk")
    stale = core.site_massing(_with_glavapu(x, 1.0, 1856), t)
    assert stale["yard_sqm"] == pytest.approx(ours)
    assert "для двора она не берётся" in stale["yard_basis"]


def test_the_row_57_is_read_from_the_glavapu_export(tmp_path):
    import test_glavapu_full_check as owner

    parsed = core.parse_glavapu_xlsx(owner._owner_book(tmp_path), "owner.xlsx")
    assert parsed["normalized"]["green_zhk_ha"] == pytest.approx(1.9485)
    assert core._GLAVAPU_SOURCE_ROWS["green_zhk_ha"][1].startswith("строка 57")
