"""Скрининг КРТ ставит соцобъекты первым очередям, а не последней.

«Что-то с баллами у нас не то в каталоге КРТ. По факту это отличный КРТ»
(владелец, 03.09.2026, Варшавское ш., вл. 37). Скрининг делил очереди сам и
соцобъекты по ним не размещал; умолчание движка «поздняя раскладка» уводило
школу на 1 000 мест в последнюю очередь, та тонула (0,81× против 0,97× при
раннем размещении), и балл каталога снимал за «слабейшую очередь» как за
экономику площадки. Ловушка та же, что на пресете этой территории
(см. CLAUDE.md «Размещение соцобъектов объявляют объектами»).

Запуск: python3 -m pytest tests/test_the_screening_places_social_objects_early.py -q
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import main as wrapper  # noqa: E402
from auction_search.krt_screening import build_krt_model_screening  # noqa: E402

core = wrapper.core
PROJECT = {"slug": "v37", "name": "Варшавское шоссе, вл. 37", "status": "Планируемый",
           "area_ha": 14.62, "housing_gfa_sqm": 229_490, "total_gfa_sqm": 415_180,
           "nonresidential_gfa_sqm": 185_690, "business_gfa_sqm": 0,
           "district": "Нагатино-Садовники"}
REPORT = {"subject": {"project_name": PROJECT["name"]},
          "analysis": {"site": {"segment": "комфорт", "price_per_sqm": 400_000, "sold_lot_avg": 45.0}},
          "price_hint": {"entry_per_sqm": 400_000}, "peers": []}
REQUIREMENTS = {"available": True, "decision_available": True, "source_level": "decision",
                "object_actions": [],
                "construction": ["Дошкольная образовательная организация на 350 мест",
                                 "Общеобразовательная школа на 1000 мест"]}


def test_the_social_objects_are_not_later_than_the_first_queues() -> None:
    sys.setrecursionlimit(400000)
    screening = build_krt_model_screening(PROJECT, REPORT, core, "", REQUIREMENTS)
    inputs = screening["model_inputs"]["inputs"]
    assert inputs["kindergarten_not_later_than"] == 1
    assert inputs["school_not_later_than"] == 2
    assert inputs["school_places"] == 1000 and inputs["kindergarten_places"] == 350
    bundle = core._run_authoritative_model(
        dict(inputs), screening["model_inputs"]["tep"], [], screening["model_inputs"]["phasing"])
    allocation = {a["type"]: a for a in bundle.get("social_allocation") or []}
    assert allocation["kindergarten"]["phase"] == 1 and allocation["school"]["phase"] <= 2, allocation
    # Предохранитель: без размещения школа уезжала бы в последнюю очередь.
    late = core._run_authoritative_model(
        {**inputs, "kindergarten_not_later_than": None, "school_not_later_than": None},
        screening["model_inputs"]["tep"], [], screening["model_inputs"]["phasing"])
    late_alloc = {a["type"]: a for a in late.get("social_allocation") or []}
    count = int((screening["model_inputs"]["phasing"] or {}).get("phase_count") or 1)
    assert late_alloc["school"]["phase"] == count and count > 2, late_alloc
    weakest = min(float(p["result"]["summary"]["llcr"]) for p in bundle["phases"])
    weakest_late = min(float(p["result"]["summary"]["llcr"]) for p in late["phases"])
    assert weakest > weakest_late


def test_the_assumption_names_it() -> None:
    screening = build_krt_model_screening(PROJECT, REPORT, core, "", REQUIREMENTS)
    assert any("не позже первой" in a and "допущение DevelopAid" in a for a in screening["assumptions"])
