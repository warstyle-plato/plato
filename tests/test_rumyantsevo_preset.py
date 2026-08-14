"""Румянцево: проект целиком поднимается одним файлом.

Пресеты `presets/*.xlsx` до сих пор были только ТЭП — площади и мощности.
Румянцево первый, где в одном файле лежит весь проект: планировка из ППТ,
обязательства по ВРИ и МПТ, техприсоединение по договорам, цены,
себестоимость, сроки и очереди. Он же первый, где сходятся все особые случаи,
которые мы разбирали по одному:

* две очереди по жилым корпусам — 166 500 м² квартир одной очередью требуют
  65 продаж в месяц три с половиной года, столько рынок не берёт;
* совмещённая соцнагрузка — школа и садик строятся, за стадион платят деньгами;
* внешний объект МПТ вне периметра, дающий проекту льготу по ВРИ;
* техприсоединение фактом вместо удельной ставки, с исключённым платежом.

Поэтому файл и лежит в репозитории: это не пример для показа, а эталон, на
котором ломается всё, что можно сломать в импорте.

Запуск: python3 -m pytest tests -q
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import main_legacy as core  # noqa: E402

PRESET_PATH = ROOT / "presets" / "Румянцево.json"
client = TestClient(core.app)


@pytest.fixture(scope="module")
def applied():
    preset = json.loads(PRESET_PATH.read_text(encoding="utf-8"))
    response = client.post("/api/project-presets/import", json={
        "preset": preset, "mode": "apply",
        "inputs": dict(core.DEFAULT_INPUTS), "tep": {}})
    assert response.status_code == 200, response.text
    data = response.json()
    tep = {key: dict(value) for key, value in core.TEP_DEFAULT.items()}
    for key, values in data["applied_tep"].items():
        tep.setdefault(key, {}).update(values)
    return data, tep


def test_the_file_is_in_the_repository():
    assert PRESET_PATH.is_file(), "пресет Румянцева пропал из presets/"


def test_the_controls_from_the_file_hold(applied):
    """Контроли пресет объявляет сам — они и проверяются."""
    data, tep = applied
    controls = json.loads(PRESET_PATH.read_text(encoding="utf-8"))["validation_controls"]
    assert tep["apartments"]["saleable"] == pytest.approx(controls["apartments_saleable_m2"])
    assert tep["offices"]["saleable"] == pytest.approx(controls["offices_saleable_m2"], rel=1e-6)
    assert tep["underground_parking"]["units"] == controls["underground_spaces"]
    assert tep["above_parking"]["units"] == controls["above_parking_spaces"]
    assert data["applied_inputs"]["land_rights_cost_mln"] == pytest.approx(
        controls["vri_remaining_cash_out_rub"] / 1e6)


def test_the_social_burden_takes_both_forms(applied):
    data, _ = applied
    assert data["applied_inputs"]["social_mode"] == core.SOCIAL_MODE_BOTH
    assert data["applied_inputs"]["social_compensation_mln"] == pytest.approx(1149.23)
    assert data["applied_inputs"]["school_places"] == 350
    assert data["applied_inputs"]["kindergarten_places"] == 180


def test_the_phasing_comes_from_the_file(applied):
    data, _ = applied
    phases = data["phasing"]["phases"]
    assert [phase["name"] for phase in phases] == ["ВГК-1", "ВГК-2"]
    assert phases[1]["start_offset_months"] == 24
    assert all(phase["construction_months"] == 36 for phase in phases)


def test_the_prices_and_costs_arrive(applied):
    """Без них пресет заполнял планировку и останавливался."""
    inputs = applied[0]["applied_inputs"]
    assert inputs["apartment_price_th"] == 350
    assert inputs["main_above_th_per_sqm"] == 190
    assert inputs["main_under_th_per_sqm"] == 120
    assert inputs["construction_months"] == 36


def test_the_project_calculates_as_two_phases(applied):
    """Импорт закончен, когда движок посчитал, а не когда файл прочтён."""
    data, tep = applied
    bundle = core.calculate_phased(core.PhasedCalcRequest(
        inputs=data["applied_inputs"], tep=tep, rates=[], phasing=data["phasing"]))
    assert len(bundle["phases"]) == 2
    summary = bundle["consolidated"]["summary"]
    assert summary["revenue"] > 100e9
    assert summary["llcr"] > 0
    # Обе формы соцнагрузки дошли до консолидированного расчёта.
    assert summary["social_payment"] / 1e6 > 1149.23


def test_the_external_object_stays_out(applied):
    data, tep = applied
    torpedo = next(block for block in data["reference"] if "Стрельцова" in block["title"])
    assert torpedo["capex_in_project"] == 0.0
    for values in tep.values():
        assert float(values.get("gns") or 0) != 36530


def test_the_open_questions_are_visible(applied):
    """Пресет несёт и то, чего в нём нет: цена офисов, льгота 7 млрд, АГК."""
    items = " ".join(applied[0]["open_items"])
    assert "офис" in items.lower()
    assert "7 млрд" in items or "льгот" in items.lower()
