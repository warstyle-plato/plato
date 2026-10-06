"""Наши формулы против калькулятора ГлавАПУ: выгрузка Нагатино от 06.10.2026.

Замысел владельца: данные ГлавАПУ берём снимком, а правки пользователя
пересчитываем СВОИМИ формулами, не вызывая калькулятор. Значит, свои формулы
обязаны совпадать с его. Здесь их две:

* `vri_tep_quick("msk", …)` — серверный дубль калькулятора (тот, на который
  сайт переходит без браузера): строка за строкой против таблицы ТЭП выгрузки;
* `tep_derived_norms` — наша нормативная функция (население, соцпотребность,
  машино-места, МПТ, компенсация), которой движок пересчитывает правки.

Входы — выгрузки Нагатино на умолчаниях калькулятора (17,8109 га, плотность
23,1, 100/0) и параметры квартала 77:05:0004001 той же даты
(`tests/fixtures/glavapu_nagatino_calc_2026_10_06.json`).

Расхождение не прячется допуском: строка совпадает, либо записана в
`*_KNOWN` с причиной. Новое расхождение без записи — падение; запись, чьё
расхождение ушло, — тоже падение: список говорит правду о движке.

Запуск: python3 -m pytest tests/test_nagatino_engine_vs_glavapu.py -q
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import glavapu_scenario as gs  # noqa: E402
import main_legacy as core  # noqa: E402

REFERENCE = json.loads((ROOT / "tests" / "fixtures" / "glavapu_nagatino_calc_2026_10_06.json")
                       .read_text(encoding="utf-8"))
I = REFERENCE["inputs"]

# --------------------------------------------------------- дубль калькулятора --

# Строка выгрузки → строка нашей книги (раскладка «Элементов жилых
# территорий» у калькулятора с осени новая: 57.1 насаждения, 57.2 площадки и
# ДТС, 58 общего пользования; у нас прежняя — 58 детские, 59 взрослые, 60
# общего пользования).
MIRROR_ROW = {"58": "60"}

MIRROR_KNOWN = {
    "44": ("индексация базовой стоимости: у нас 1,0175 (_GLAVAPU_VRI_BASE_INDEXATION, "
           "от 16.08.2026), у калькулятора выходит 1,017494 — 18 265,750 против "
           "18 265,873 млн ₽, 0,0007 %"),
    "57.1": ("раскладку «Элементов жилых территорий» калькулятор сменил: насаждений "
             "(3,5 м²/чел.) отдельной строкой у нас нет — шаблон книги общий с "
             "областью и с распознаванием выгрузок на странице"),
    "57.2": "то же: площадки и ДТС (1,5 м²/чел.) у нас — две строки 0,5 и 0,1",
}

TOLERANCE = 0.0005


@pytest.fixture(scope="module")
def mirror() -> dict[str, float | None]:
    analysis = {
        "territory": {"area_ha": I["site_area_ha"], "inside_ttc": False,
                      "district": "Нагатино-Садовники"},
        "coefficients": {"rail": I["k1"], "business_outside_ttc": I["k2"],
                         "business_inside_ttc": 0.2, "rent": I["rent_coeff"],
                         "base_cost_zh_high": I["base_cost_mkd_rub"], "upks_zh_high": I["upks_rub"]},
    }
    result = core.vri_tep_quick("msk", "77:05:0004001:1", analysis=analysis)
    import io
    import openpyxl
    sheet = openpyxl.load_workbook(io.BytesIO(result["file"]))["ТЭП"]
    rows: dict[str, float | None] = {}
    for row in sheet.iter_rows(min_row=2, values_only=True):
        if row[0] not in (None, ""):
            rows[str(row[0]).strip()] = gs.ru_number(row[3])
    return rows


def _mirror_table(mirror) -> list[dict]:
    out = []
    for code, (theirs, label) in REFERENCE["rows"].items():
        mine = mirror.get(MIRROR_ROW.get(code, code))
        same = mine is not None and abs(mine - theirs) <= max(TOLERANCE, abs(theirs) * 1e-6)
        out.append({"code": code, "label": label, "ours": mine, "glavapu": theirs, "same": same})
    return out


def test_the_mirror_density_is_the_calculators_recommended() -> None:
    assert core.glavapu_recommended_density(17.8109) == 23.1
    assert core.glavapu_recommended_density(0.651) == 35.0
    assert core.glavapu_recommended_density(60) == 20.0


def test_every_mirror_row_matches_or_is_named(mirror) -> None:
    bad = [r for r in _mirror_table(mirror) if not r["same"] and r["code"] not in MIRROR_KNOWN]
    assert not bad, "дубль калькулятора расходится без причины: " + "; ".join(
        f"строка {r['code']} «{r['label']}»: наше {r['ours']} против {r['glavapu']}" for r in bad)


def test_a_closed_mirror_difference_leaves_the_list(mirror) -> None:
    same = {r["code"] for r in _mirror_table(mirror) if r["same"]}
    assert not (same & set(MIRROR_KNOWN)), sorted(same & set(MIRROR_KNOWN))


def test_the_mirror_jobs_follow_the_calculators_norm(mirror) -> None:
    """МПТ встроенных помещений — 32 м² НП на место к ближайшему: 22 217 → 694."""
    analysis = {"territory": {"area_ha": I["site_area_ha"]},
                "coefficients": {"rail": I["k1"], "business_outside_ttc": I["k2"]}}
    book = core.vri_tep_quick("msk", "77:05:0004001:1", analysis=analysis)["file"]
    assert gs.mpt_by_vri(book)["total"] == 694


# ------------------------------------------------------ нормативная функция --

DERIVED_KNOWN = {
    "parking_permanent": (
        "пункт 2 приложения 5 к 945-ПП (ред. 2118-ПП) по средней квартире — решение "
        "владельца 04.09.2026: ⌈3 628 × 0,8⌉ = 2 903; калькулятор считает пунктом 1 от "
        "площади квартир — 2 902 (та же формула у нас: moscow_permanent_parking_2118)"),
    "parking_short_stop": (
        "мест кратковременной остановки нормативная функция не считает (дубль "
        "калькулятора считает: площадь квартир / 22 100 + НП встроенных / 450, не больше 4)"),
}


def _derived() -> dict:
    norms = core.tep_derived_norms(
        apartment_area_sqm=I["apartment_area_sqm"],
        residential_living_spp_sqm=I["residential_living_spp_sqm"],
        nonresidential_np_sqm=I["built_in_np_sqm"], k1=I["k1"], k2=I["k2"],
        upks_rub=I["upks_rub"], apartment_count=I["apartment_count"])
    out = {key: norms.get(key) for key in (
        "population", "apartment_units", "kindergarten_places", "school_places",
        "clinic_capacity", "parking_permanent", "parking_guest", "parking_onsite",
        "compensation_mln")}
    out["parking_short_stop"] = None
    for kind, value in norms["compensation_breakdown_mln"].items():
        out[f"compensation_{kind}_mln"] = value
    out["jobs"] = norms["jobs"]
    return out


def _derived_table() -> list[dict]:
    ours = _derived()
    reference = dict(REFERENCE["calculator"], jobs=[694, "МПТ встроенных: 22 217 м² НП / 32"])
    rows = []
    for kind, (theirs, where) in reference.items():
        mine = ours.get(kind)
        same = mine is not None and abs(float(mine) - float(theirs)) <= 0.01
        rows.append({"kind": kind, "ours": mine, "glavapu": theirs, "where": where, "same": same})
    return rows


def test_every_derived_difference_is_named_with_its_reason() -> None:
    bad = [r for r in _derived_table() if not r["same"] and r["kind"] not in DERIVED_KNOWN]
    assert not bad, "расхождение с калькулятором без причины: " + "; ".join(
        f"{r['kind']}: наше {r['ours']} против {r['glavapu']} ({r['where']})" for r in bad)


def test_a_closed_derived_difference_leaves_the_list() -> None:
    same = {r["kind"] for r in _derived_table() if r["same"]}
    assert not (same & set(DERIVED_KNOWN)), sorted(same & set(DERIVED_KNOWN))


def test_the_engine_agrees_where_the_methods_agree() -> None:
    rows = {r["kind"]: r for r in _derived_table()}
    for kind in ("population", "apartment_units", "kindergarten_places", "school_places",
                 "clinic_capacity", "parking_guest", "parking_onsite", "jobs",
                 "compensation_kindergarten_mln", "compensation_school_mln",
                 "compensation_clinic_mln", "compensation_mln"):
        assert rows[kind]["same"], rows[kind]


def test_point_one_is_the_calculators_permanent_parking() -> None:
    """Калькулятор считает постоянные места пунктом 1 — наша функция пункта 1
    даёт то же на обеих выгрузках Нагатино (умолчания и наш сценарий)."""
    assert core.moscow_permanent_parking_2118(I["apartment_area_sqm"]) == 2902
    assert core.moscow_permanent_parking_2118(3897 * 33) == 1485


# ------------------------------------- правка не зовёт живой калькулятор --

LIVE_ROUTES = ("/glavapu/scenario", "/cadastral/tep-server", "/cadastral/tep-from-calculator")


def test_an_edit_recalculates_with_our_formulas_only() -> None:
    """Правка вводной или ячейки ТЭП пересчитывается своими формулами: путь
    правки (`scheduleTepAutoRecalc` → `recalcFromTep`) не ходит ни на один
    маршрут живого калькулятора. Его зовут только явные кнопки."""
    import page_blocks
    for name in ("scheduleTepAutoRecalc", "recalcFromTep", "recalcFromTepByNorms"):
        body = page_blocks.function(name)
        assert not any(route in body for route in LIVE_ROUTES), name
    assert "fetch('/tep/recalc-from-baseline'" in page_blocks.function("recalcFromTep")
    assert "fetch('/tep/derived-by-site'" in page_blocks.function("recalcFromTepByNorms")


def test_the_recalc_routes_never_start_the_browser(monkeypatch) -> None:
    def forbidden(*args, **kwargs):
        raise AssertionError("пересчёт правки поднял браузер калькулятора")
    monkeypatch.setattr(core, "_glavapu_headless_run", forbidden)
    from fastapi.testclient import TestClient
    client = TestClient(core.app)
    got = client.post("/tep/derived-by-site", json={
        "apartment_area_sqm": I["apartment_area_sqm"],
        "residential_living_spp_sqm": I["residential_living_spp_sqm"],
        "nonresidential_np_sqm": I["built_in_np_sqm"], "district": "Нагатино-Садовники"})
    assert got.status_code == 200 and got.json()["population"] == 7618
