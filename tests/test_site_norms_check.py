"""Проверка «Посадка ↔ нормативы» падает на подделке и молчит на верном ответе.

Ответы сайта здесь — выжимки настоящих ответов прода 25.10.2026
(77:06:0003002:18, 50:21:0120316:1221, 50:12:0100131:497, 50:20:0010101:1).
"""

import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location("site_norms_check", ROOT / "scripts" / "site_norms_check.py")
snc = importlib.util.module_from_spec(_spec)
sys.modules["site_norms_check"] = snc  # dataclass ищет свой модуль здесь
_spec.loader.exec_module(snc)

REF_18 = {"cad": "77:06:0003002:18", "region": "msk", "zone": 1, "expect_flags": []}
TEP_18 = {"normalized": {
    "apartment_area_sqm": 11678.0, "parking_permanent": 135.0, "parking_guest": 14.0,
    "parking_attached": 7.0, "parking_k1_coefficient": 0.75, "parking_k2_coefficient": 0.7,
    "ground_commercial_np_sqm": 1032.0, "standalone_nonres_np_sqm": 0.0,
    "required_kindergarten_places": 16.0, "required_school_places": 32.0},
    "source": {"calculator_url": "https://genplan.tech/calc/?terrArea=0.5461&restrictArea=0"}}


def statuses(checks, code=None):
    return [c.status for c in checks if code is None or c.code == code]


def test_moscow_norms_pass_on_the_real_answer():
    checks = snc.check_moscow_tep(REF_18, TEP_18)
    assert statuses(checks) == [snc.OK] * 5, checks


def test_each_moscow_norm_fails_on_a_forged_number():
    for key, code in (("parking_permanent", "П1"), ("parking_guest", "П2"), ("parking_attached", "П3"),
                      ("required_kindergarten_places", "С1"), ("required_school_places", "С2")):
        forged = json.loads(json.dumps(TEP_18))
        forged["normalized"][key] += 1
        assert statuses(snc.check_moscow_tep(REF_18, forged), code) == [snc.VIOLATION], key


def test_zone_two_uses_its_own_rate():
    # Коммунарка, зона 2: 7 452 жителя → 470 мест ДОО (63 на 1000), в зоне 1 было бы 328.
    ref = {"cad": "50:21:0120316:1221", "zone": 2}
    tep = {"normalized": {"apartment_area_sqm": 245910.0, "required_kindergarten_places": 470.0,
                          "required_school_places": 925.0}}
    assert statuses(snc.check_moscow_tep(ref, tep), "С1") == [snc.OK]
    assert statuses(snc.check_moscow_tep({**ref, "zone": 1}, tep), "С1") == [snc.VIOLATION]


def test_missing_tep_is_no_data_not_ok():
    assert statuses(snc.check_moscow_tep(REF_18, {"normalized": {}})) == [snc.NO_DATA]


def test_drift_warning_of_another_parcel_is_a_violation():
    foreign = [("ВНИМАНИЕ: серверные формулы DevelopAid разошлись со штатным калькулятором "
                "(компенсация ДОО: калькулятор 156.098, формулы 152.628).")]
    ref = {"cad": "77:03:0006015:30"}
    assert statuses(snc.check_drift_warning(ref, foreign)) == [snc.VIOLATION]
    own = [foreign[0] + " Участок 77:03:0006015:30."]
    assert statuses(snc.check_drift_warning(ref, own)) == [snc.QUESTION]
    assert snc.check_drift_warning(ref, ["Показатели считаны из таблицы."]) == []


def _screening(findings, headline="Критических ограничений не обнаружено", disclaimer="Проверены ЕГРН."):
    return {"parcels": [{"found": True, "findings": findings,
                         "verdict": {"headline": headline, "disclaimer": disclaimer}}]}


ZONE = {"category": "ПКК. Территориальные зоны", "flag_class": "info", "coverage_pct": 100.0}
OOPT = {"category": "ПКК. Особо охраняемые природные территории", "name": "ПКК. Особо охраняемые природные территории",
        "flag_class": "killer", "impact": "застройка ООПТ запрещена", "coverage_pct": 100.0}
GRID = {"type_zone": "Охранная зона инженерных коммуникаций", "flag_class": "economic",
        "impact": "в охранной зоне строить нельзя — режет пятно", "coverage_pct": 21.4}


def test_silent_missing_zone_is_a_violation_and_named_one_is_not():
    ref = {"cad": "77:06:0003002:18", "expect_flags": []}
    assert statuses(snc.check_screening(ref, _screening([]), ""), "З1") == [snc.VIOLATION]
    named = _screening([], disclaimer="Территориальную зону получить не удалось.")
    assert statuses(snc.check_screening(ref, named, ""), "З1") == [snc.OK]
    assert statuses(snc.check_screening(ref, _screening([ZONE]), ""), "З1") == []


def test_killer_flag_must_leave_a_trace_in_the_tep():
    ref = {"cad": "50:12:0100131:497", "expect_flags": ["killer"]}
    screening = _screening([ZONE, OOPT])
    assert statuses(snc.check_screening(ref, screening, "Расчёт готов."), "З3") == [snc.VIOLATION]
    traced = "Участок целиком в ООПТ — застройка запрещена, ТЭП показан справочно."
    assert statuses(snc.check_screening(ref, screening, traced), "З3") == []


def test_changed_flags_are_a_question_not_a_verdict():
    ref = {"cad": "x", "expect_flags": []}
    assert statuses(snc.check_screening(ref, _screening([ZONE, GRID]), ""), "З2") == [snc.QUESTION]


def test_restrict_area_must_reach_the_calculator():
    ref = {"cad": "50:21:0120316:1221"}
    screening = _screening([GRID])
    zero = {"source": {"calculator_url": "https://genplan.tech/calc/?terrArea=17.3479&restrictArea=0"}}
    passed = {"source": {"calculator_url": "https://genplan.tech/calc/?terrArea=17.3479&restrictArea=3.71"}}
    assert statuses(snc.check_restrict_area(ref, zero, screening)) == [snc.VIOLATION]
    assert statuses(snc.check_restrict_area(ref, passed, screening)) == [snc.OK]
    assert snc.check_restrict_area(ref, zero, _screening([])) == []


def test_mo_vri_payment_contradicting_its_own_warning():
    ref = {"cad": "50:20:0010101:1"}
    mo = {"density_sqm_per_ha": 20000.0, "vri": {
        "delta_rub": -23821950.0, "payment_used_mln": 200.819, "payment_basis": "методика по участкам ЕГРН",
        "warnings": [("Кадастровая стоимость участков не ниже целевой для жилой застройки: разница "
                      "неположительная, плата по методике не определяется.")]}}
    assert statuses(snc.check_mo(ref, mo), "В1") == [snc.VIOLATION]
    mo["vri"]["payment_used_mln"] = None
    assert statuses(snc.check_mo(ref, mo), "В1") == []


def test_mo_default_density_and_overfull_site_are_questions():
    checks = snc.check_mo({"cad": "50:20:0010101:1"},
                          {"density_sqm_per_ha": 30000.0, "balance": {"remaining_ha": -0.399}})
    assert statuses(checks) == [snc.QUESTION, snc.QUESTION]


def test_reference_names_each_parcel_once_with_a_region():
    parcels = json.loads((ROOT / "scripts" / "site_norms_reference.json").read_text("utf-8"))["parcels"]
    cads = [p["cad"] for p in parcels]
    assert len(cads) == len(set(cads)) and 8 <= len(cads) <= 12
    assert {p["region"] for p in parcels} == {"msk", "mo"}
    assert all(p.get("zone") in (1, 2) for p in parcels if p["region"] == "msk")
    assert "77:06:0003002:18" in cads
