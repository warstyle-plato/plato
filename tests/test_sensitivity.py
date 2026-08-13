"""Анализ чувствительности: один параметр за расчёт.

Сценарии «консервативный / базовый / оптимистичный» двигают цены и затраты
одновременно, и по ним не понять, что именно решает судьбу проекта. Tornado
меняет по одному параметру и считает всё тем же движком модели.

Запуск: python3 -m pytest tests -q
"""

from __future__ import annotations

import copy
import sys
from pathlib import Path

import pytest
from fastapi import HTTPException

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import main as wrapper  # noqa: E402

core = wrapper.core


def project(**overrides):
    inputs = dict(core.DEFAULT_INPUTS)
    inputs["purchase_price_mln"] = 6500
    inputs.update(overrides)
    tep = {key: dict(value) for key, value in core.TEP_DEFAULT.items()}
    return inputs, tep


PHASING = {
    "enabled": True, "phase_count": 3, "phase_gap_months": 12,
    "phases": [{"name": f"О{i+1}", "start_offset_months": i * 12,
                "construction_months": 24} for i in range(3)],
}


@pytest.fixture(scope="module")
def single():
    inputs, tep = project()
    return core.run_sensitivity(inputs, tep, [], {}, metric="llcr")


def item(report, key):
    return next(row for row in report["items"] if row["parameter"] == key)


# --- 1. Базовая модель не изменяется после анализа ---------------------------

def test_the_analysis_leaves_the_project_untouched():
    inputs, tep = project()
    rates, phasing = [], copy.deepcopy(PHASING)
    before = copy.deepcopy((inputs, tep, rates, phasing))

    core.run_sensitivity(inputs, tep, rates, phasing, metric="llcr")

    assert (inputs, tep, rates, phasing) == before, "анализ переписал вводные пользователя"


def test_the_api_does_not_touch_the_request_object():
    inputs, tep = project()
    request = core.SensitivityRequest(inputs=inputs, tep=tep, phasing=copy.deepcopy(PHASING))
    before = request.model_dump()

    core.sensitivity_api(request)

    assert request.model_dump() == before


# --- 2-3. Меняется ровно один параметр, и результат совпадает с прямым счётом -

def test_only_the_chosen_parameter_moves():
    inputs, tep = project()
    report = core.run_sensitivity(inputs, tep, [], {}, metric="llcr",
                                  parameters=["apartment_price_th"], change_pct=10)
    row = item(report, "apartment_price_th")

    assert row["base_input"] == inputs["apartment_price_th"]
    assert row["low_input"] == pytest.approx(inputs["apartment_price_th"] * 0.9)
    assert row["high_input"] == pytest.approx(inputs["apartment_price_th"] * 1.1)


def test_the_numbers_match_a_direct_call_to_the_engine():
    """Значения обязан возвращать движок, а не отдельная арифметика анализа."""
    inputs, tep = project()
    report = core.run_sensitivity(inputs, tep, [], {}, metric="llcr",
                                  parameters=["main_above_th_per_sqm"], change_pct=10)
    row = item(report, "main_above_th_per_sqm")

    direct = dict(inputs)
    direct["main_above_th_per_sqm"] = row["high_input"]
    bundle = core._run_authoritative_model(direct, {k: dict(v) for k, v in tep.items()}, [], {})
    expected = bundle["consolidated"]["summary"]["llcr"]

    assert row["high_result"] == pytest.approx(expected, abs=1e-9)


# --- 4. Сортировка по влиянию ------------------------------------------------

def test_parameters_are_sorted_by_impact(single):
    impacts = [row["impact"] for row in single["items"]]

    assert impacts == sorted(impacts, reverse=True)
    assert impacts[0] > 0


def test_the_direction_of_the_effect_is_kept(single):
    """Рост цены поднимает LLCR, рост себестоимости — опускает."""
    price = item(single, "apartment_price_th")
    cost = item(single, "main_above_th_per_sqm")

    assert price["high_result"] > price["low_result"]
    assert cost["high_result"] < cost["low_result"]


# --- 5-7. Одна очередь, много очередей, слабейшая очередь --------------------

def test_a_single_phase_project_is_analysed_as_a_whole(single):
    assert single["base"]["scope"] == "consolidated"
    assert single["items"]


def test_a_phased_project_defaults_to_the_weakest_phase():
    inputs, tep = project()
    report = core.run_sensitivity(inputs, tep, [], copy.deepcopy(PHASING), metric="llcr")

    assert report["base"]["scope"] == "weakest_phase"
    assert report["base"]["scope_label"].startswith("О")
    assert report["items"]


def test_the_consolidated_scope_can_be_asked_for():
    inputs, tep = project()
    report = core.run_sensitivity(inputs, tep, [], copy.deepcopy(PHASING),
                                  metric="llcr", scope="consolidated")

    assert report["base"]["scope_label"] == "Весь проект"


def test_the_gap_between_phases_is_only_analysed_when_there_are_phases():
    inputs, tep = project()
    phased = core.run_sensitivity(inputs, tep, [], copy.deepcopy(PHASING), metric="llcr")
    single_phase = core.run_sensitivity(inputs, tep, [], {}, metric="llcr")

    assert any(row["parameter"] == "phase_gap_months" for row in phased["items"])
    assert not any(row["parameter"] == "phase_gap_months" for row in single_phase["items"])


# --- 8. Нулевые и отключённые продукты ---------------------------------------

def test_products_absent_from_the_tep_are_skipped():
    inputs, tep = project()
    tep["storage"]["units"] = 0
    tep["storage"]["saleable"] = 0

    report = core.run_sensitivity(inputs, tep, [], {}, metric="llcr")

    assert not any(row["parameter"] == "storage_price_th" for row in report["items"])


def test_a_zero_input_is_skipped():
    """Ноль, умноженный на процент, остаётся нулём — расчёт не изменится."""
    inputs, tep = project(social_compensation_mln=0, social_mode="Денежная компенсация")

    report = core.run_sensitivity(inputs, tep, [], {}, metric="llcr")

    assert not any(row["parameter"] == "social_compensation_mln" for row in report["items"])


def test_social_compensation_is_skipped_when_objects_are_built():
    inputs, tep = project(social_compensation_mln=500, social_mode="Строительство")

    report = core.run_sensitivity(inputs, tep, [], {}, metric="llcr",
                                  parameters=["social_compensation_mln"])

    assert not report["items"]
    assert any("компенсируются деньгами" in text for text in report["warnings"])


# --- 9. Понятные ошибки ------------------------------------------------------

def test_an_unknown_parameter_is_reported_clearly():
    inputs, tep = project()
    with pytest.raises(HTTPException) as failure:
        core.run_sensitivity(inputs, tep, [], {}, metric="llcr", parameters=["выдумка"])

    assert failure.value.status_code == 400
    assert "выдумка" in str(failure.value.detail)


def test_an_unknown_metric_lists_the_available_ones():
    inputs, tep = project()
    with pytest.raises(HTTPException) as failure:
        core.run_sensitivity(inputs, tep, [], {}, metric="счастье")

    assert "llcr" in str(failure.value.detail)


def test_a_zero_range_is_rejected():
    inputs, tep = project()
    with pytest.raises(HTTPException):
        core.run_sensitivity(inputs, tep, [], {}, change_pct=0, duration_change_months=0)


# --- 10. Экономически невозможные значения -----------------------------------

def test_a_duration_never_goes_below_one_month():
    inputs, tep = project(construction_months=3)

    report = core.run_sensitivity(inputs, tep, [], {}, metric="llcr",
                                  parameters=["construction_months"],
                                  duration_change_months=12)

    assert item(report, "construction_months")["low_input"] >= 1


def test_a_price_never_goes_negative():
    inputs, tep = project()

    report = core.run_sensitivity(inputs, tep, [], {}, metric="llcr",
                                  parameters=["apartment_price_th"], change_pct=200)

    assert item(report, "apartment_price_th")["low_input"] == 0


def test_a_share_never_exceeds_a_hundred_percent():
    inputs, tep = project(share_before_rve_pct=95)

    report = core.run_sensitivity(inputs, tep, [], {}, metric="llcr",
                                  parameters=["share_before_rve_pct"], change_pct=20)

    assert item(report, "share_before_rve_pct")["high_input"] == 100


# --- 11. Отказ одного сценария не рушит анализ -------------------------------

def test_one_broken_scenario_does_not_sink_the_rest(monkeypatch):
    inputs, tep = project()
    original = core._run_authoritative_model
    calls = {"n": 0}

    def flaky(*args, **kwargs):
        calls["n"] += 1
        if calls["n"] == 3:
            raise RuntimeError("сценарий не посчитан")
        return original(*args, **kwargs)

    monkeypatch.setattr(core, "_run_authoritative_model", flaky)
    report = core.run_sensitivity(inputs, tep, [], {}, metric="llcr")

    assert report["items"], "анализ развалился из-за одного сценария"
    assert any("не посчитан" in text for text in report["warnings"])


# --- Метрики -----------------------------------------------------------------

@pytest.mark.parametrize("metric", sorted(core._SENSITIVITY_METRICS))
def test_every_metric_either_reports_or_refuses_clearly(metric):
    """IRR не определён, когда поток капитала не меняет знак, — это состояние модели."""
    inputs, tep = project()
    try:
        report = core.run_sensitivity(inputs, tep, [], {}, metric=metric,
                                      parameters=["purchase_price_mln"])
    except HTTPException as refusal:
        assert refusal.status_code == 400
        assert core._SENSITIVITY_METRICS[metric]["label"] in str(refusal.detail)
        return
    assert report["base"]["value"] is not None
    assert report["items"][0]["impact"] >= 0


def test_a_metric_the_model_cannot_compute_is_named():
    inputs, tep = project()
    with pytest.raises(HTTPException) as failure:
        core.run_sensitivity(inputs, tep, [], {}, metric="irr_equity_pct",
                             parameters=["purchase_price_mln"])

    assert "IRR" in str(failure.value.detail)
    assert "не определён" in str(failure.value.detail)


def test_the_options_come_from_the_form_dictionary():
    """Названия и единицы не должны дублироваться руками."""
    options = core.sensitivity_options()
    labels = {item["key"]: item["label"] for item in options["parameters"]}
    form = {field[0]: field[1] for _, fields in core.FIELD_GROUPS for field in fields}

    assert labels["apartment_price_th"] == form["apartment_price_th"]
    assert labels["phase_gap_months"] == "Лаг между очередями"
    assert {metric["key"] for metric in options["metrics"]} == set(core._SENSITIVITY_METRICS)


# --- Автоматический вывод ----------------------------------------------------

def test_the_verdict_names_the_top_factor_and_the_runners_up(single):
    text = " ".join(single["verdict"])

    assert single["items"][0]["label"] in text
    assert single["items"][1]["label"] in text
    assert "по одному" in text, "не сказано, что сочетание отклонений не показано"


def test_the_verdict_flags_a_broken_llcr_target():
    # Цена поднята вслед за умолчаниями: после сверки удельных ставок с
    # банковским бюджетом стройка подорожала, и прежние 620 больше не дают
    # проекту дотянуть до цели, с которой тест начинается (1,164 против 1,20).
    inputs, tep = project(apartment_price_th=680)
    report = core.run_sensitivity(inputs, tep, [], {}, metric="llcr")
    text = " ".join(report["verdict"])

    assert report["base"]["value"] >= 1.20, "подготовленный проект должен держать цель"
    assert "1,20x" in text


def test_the_verdict_flags_a_negative_npv():
    # Проект должен стоять чуть выше нуля, чтобы отклонение фактора уводило его
    # в минус. На прежних 560 после подорожания стройки он уже убыточен в базе,
    # и вердикт говорил бы не о риске, а о состоявшемся убытке.
    inputs, tep = project(apartment_price_th=600)
    report = core.run_sensitivity(inputs, tep, [], {}, metric="npv_mln")

    assert any("в минус" in line for line in report["verdict"])


def test_the_verdict_survives_an_empty_analysis():
    inputs, tep = project()
    report = core.run_sensitivity(inputs, tep, [], {}, metric="llcr",
                                  parameters=["social_compensation_mln"])

    assert report["items"] == []
    assert report["verdict"]
