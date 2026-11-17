"""Сверка МПТ читает рабочие места того же расчёта, что льготы проекта.

Синтетические ТЭП: отдельно проверяем соцобъекты, разные назначения и
отказы. Денежную льготу сверка не пересчитывает и проект не изменяет.
"""

from __future__ import annotations

import copy

import pytest


@pytest.fixture(scope="module")
def core():
    import main
    return main.core


def _project():
    inputs = {
        "vri_region": "msk", "vri_required": True,
        "vri_relief_mode": "none", "land_rights_cost_mln": 5000.0,
        "project_start": "2026-01-01", "ird_months": 18,
        "vri_obligation_date_mode": "manual", "vri_obligation_date": "2026-11-01",
        "_cadastral_analysis": {"territory": {
            "district": "Кунцево", "inside_ttc": False,
        }},
    }
    tep = {
        "ground_commercial": {"gns": 27022.0, "total_area": 24320.0},
        "kindergarten": {"gns": 6667.0, "total_area": 6000.0, "units": 370},
        "school": {"gns": 12223.0, "total_area": 11000.0, "units": 750},
        "clinic": {"gns": 4445.0, "total_area": 4000.0, "units": 160},
    }
    return inputs, tep


@pytest.mark.parametrize("mode", ["none", "percent", "off"])
def test_social_jobs_are_included_independently_of_manual_relief(core, mode):
    inputs, tep = _project()
    inputs.update(vri_relief_mode=mode, vri_relief_pct=100)
    original = copy.deepcopy((inputs, tep))
    before = core.vri_benefits_for(inputs, tep)
    money = core.vri_relief(inputs, 5_000_000_000, tep)

    ours, reasons = core._glavapu_scenario_ours(inputs, tep, {})

    assert {row["key"]: row["jobs"] for row in before["rows"]} == {
        "ground_commercial": 760, "kindergarten": 37, "school": 89, "clinic": 24,
    }
    assert ours["mpt"][0] == 910
    assert "льгот проекта" in ours["mpt"][1] and "соцобъектов" in ours["mpt"][1]
    assert "соцобъектов" in reasons["mpt"] and "32 м²" not in reasons["mpt"]
    assert core.vri_benefits_for(inputs, tep) == before
    assert core.vri_relief(inputs, 5_000_000_000, tep) == money
    assert (inputs, tep) == original


@pytest.mark.parametrize(("purpose", "sports_jobs"), [("sport", 37), ("healthcare", 31)])
def test_jobs_use_each_product_norm_and_exclude_a_disabled_object(core, purpose, sports_jobs):
    inputs, _ = _project()
    tep = {
        "offices": {"gns": 1112.0, "total_area": 1000.0},
        "standalone_retail": {"gns": 1112.0, "total_area": 1000.0},
        "sports": {"gns": 1112.0, "total_area": 1000.0},
    }
    inputs["sports_purpose"] = purpose
    ours, _ = core._glavapu_scenario_ours(inputs, tep, {})
    # Офисы /32, торговля /45, спорт /27. Единая норма /32 дала бы 93.
    assert ours["mpt"][0] == 31 + 22 + sports_jobs
    retail = next(o for o in core.STANDALONE_OBJECTS if o.key == "standalone_retail")
    inputs[retail.enabled_key] = False
    ours, _ = core._glavapu_scenario_ours(inputs, tep, {})
    assert ours["mpt"][0] == 31 + sports_jobs


def test_missing_social_places_follow_the_project_without_area_substitution(core):
    inputs, tep = _project()
    del tep["kindergarten"]["units"]
    before = core.vri_benefits_for(inputs, tep)
    row = next(r for r in before["rows"] if r["key"] == "kindergarten")
    assert row["jobs"] == 0 and "нет числа мест" in row["jobs_basis"]
    ours, _ = core._glavapu_scenario_ours(inputs, tep, {})
    assert ours["mpt"][0] == before["jobs_total"] == 873


def test_missing_geography_blocks_money_but_not_known_jobs(core):
    inputs, tep = _project()
    del inputs["_cadastral_analysis"]
    before = core.vri_benefits_for(inputs, tep)
    assert before["missing"] and before["mpt_mln"] == 0
    ours, _ = core._glavapu_scenario_ours(inputs, tep, {})
    assert ours["mpt"][0] == before["jobs_total"] == 910


@pytest.mark.parametrize("removed", [True, False])
def test_a_social_object_without_area_is_not_included(core, removed):
    inputs, tep = _project()
    if removed:
        del tep["school"]
    else:
        tep["school"]["gns"] = 0
    ours, _ = core._glavapu_scenario_ours(inputs, tep, {})
    assert ours["mpt"][0] == 760 + 37 + 24


def test_zero_jobs_are_distinct_from_an_unavailable_calculation(core, monkeypatch):
    inputs, _ = _project()
    ours, _ = core._glavapu_scenario_ours(inputs, {}, {})
    assert ours["mpt"][0] == 0 and ours["mpt"][1]
    # Ручная льгота не зависит от отказа расчёта МПТ.
    inputs.update(vri_relief_mode="percent", vri_relief_pct=10)
    monkeypatch.setattr(core, "vri_benefits_for", lambda *_: {
        "applicable": False, "rows": [], "reason": "нет исходных данных для МПТ",
    })
    ours, reasons = core._glavapu_scenario_ours(inputs, {}, {})
    assert ours["mpt"] == (None, "")
    assert reasons["mpt"] == "нет исходных данных для МПТ"
    assert ours["vri_relief"]["total"][0] == 500.0


def test_moscow_jobs_are_not_used_for_an_oblast_project(core):
    inputs, tep = _project()
    inputs["vri_region"] = "mo"
    ours, reasons = core._glavapu_scenario_ours(inputs, tep, {})
    assert ours["mpt"] == (None, "")
    assert "московские" in reasons["mpt"]
