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
import re
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
    controls = json.loads(PRESET_PATH.read_text(encoding="utf-8"))["validation_controls"]
    assert data["applied_inputs"]["social_mode"] == core.SOCIAL_MODE_BOTH
    # Денежная часть — остаток обязательства по регби из ДС №7 от 03.06.2026:
    # лимит 1,2 млрд минус 72,6 млн, уже стоящие в графике. Число берётся из
    # контроля пресета, а не переписывается здесь при каждом новом ДС.
    assert data["applied_inputs"]["social_compensation_mln"] == pytest.approx(
        controls["rugby_social_burden_remaining_rub"] / 1e6)
    assert data["applied_inputs"]["school_places"] == 350
    assert data["applied_inputs"]["kindergarten_places"] == 180


def test_the_preset_carries_every_cadastral_number():
    """Кадастры — часть проекта, а не подпись под ним.

    Диапазон «77:17:0110504:18151–18171» одной строкой участок не ищет: НСПД
    знает номера, а не тире между ними. В пресете лежит развёрнутый список из
    двадцати одного номера, и его длина объявлена контролем.
    """
    preset = json.loads(PRESET_PATH.read_text(encoding="utf-8"))
    numbers = preset["project"]["cadastral_numbers"]
    assert len(numbers) == preset["validation_controls"]["cadastral_numbers_count"]
    assert len(set(numbers)) == len(numbers), "повторы в списке кадастровых номеров"
    assert all(re.match(r"^\d{2}:\d{2}:\d{6,8}:\d+$", number) for number in numbers)
    # Тот же список, но строкой — его вставляют в поле участка.
    assert preset["project"]["cadastral_numbers_input"].count(":") == 3 * len(numbers)


def test_the_phasing_comes_from_the_file(applied):
    data, _ = applied
    phases = data["phasing"]["phases"]
    assert [phase["name"] for phase in phases] == ["ВГК-1", "ВГК-2"]
    assert phases[1]["start_offset_months"] == 24
    assert all(phase["construction_months"] == 36 for phase in phases)
    # Percentages remain the first fill only. The queue now carries the real
    # product TEP used by both the phasing and product-result tabs.
    assert phases[0]["products"]["apartments"]["gns"] == 112250
    assert phases[1]["products"]["apartments"]["gns"] == 109750
    assert phases[1]["products"]["offices"]["gns"] == 125160
    assert phases[1]["products"]["above_parking"]["units"] == 766
    assert phases[0]["products"]["school"]["generates_revenue"] is False


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


def test_the_parcel_arrives_with_the_project():
    """Пресет поднимает проект целиком — значит, и участок.

    Двадцать один номер лежал в файле и не доезжал никуда: загрузчик их не
    читал вовсе. Проект вставал с экономикой и очередями, а карточка участка и
    градостроительные ограничения оставались пустыми — при том, что номера в
    файле есть. Теперь номера уходят в поле участка, и следом идёт та же
    выгрузка ЕГРН, что при ручном вводе; ТЭП при этом не трогается — он пришёл
    из пресета, и штатный расчёт ГлавАПУ его бы перебил.
    """
    preset = json.loads(PRESET_PATH.read_text(encoding="utf-8"))
    numbers = core.project_preset.cadastral_numbers(preset)
    assert len(numbers) == 21

    body = core.PAGE[core.PAGE.index("async function applyPreset"):]
    body = body[:body.index("// --- хранилище проектов")]
    assert "data.cadastral_numbers" in body, "номера пресета не доезжают до страницы"
    assert "drawLandPreviewQuiet" in body, "участок не запрашивается после импорта"
    assert "obtainTep" not in body, "импорт пресета не имеет права перезапускать ТЭП"


def test_a_dash_range_is_not_read_as_a_number():
    """«77:17:0110504:18151–18171» — сокращение человека, а не кадастровый номер."""
    numbers = core.project_preset.cadastral_numbers(
        {"project": {"cadastral": "77:17:0110504:18151–18171"}})
    assert numbers == [], "диапазон нельзя раскрывать самим: участков может не быть"

    mixed = core.project_preset.cadastral_numbers({
        "project": {"cadastral_numbers": ["77:17:0110504:18151", "77:17:0110504:18151"]},
        "land": {"cadastral_numbers_csv": "77:17:0110504:18152"},
    })
    assert mixed == ["77:17:0110504:18151", "77:17:0110504:18152"], "повторы убираются, порядок держится"


def test_the_ppt_ratio_is_signed_by_the_document_not_by_the_methodology(applied):
    """0,75 у жилья — согласованный ППТ, а не норматив ГлавАПУ.

    Калькулятор даёт 0,65 жилой ГНС; на Румянцеве разница — 22 200 м² и около
    7,8 млрд ₽ выручки. Число верное, но подписанное методикой оно молча уехало
    бы в следующий проект, где ППТ другой.
    """
    data, tep = applied
    assert tep["apartments"]["saleable"] == pytest.approx(222000 * 0.75)
    note = next((item["note"] for item in data["notes"] if "квартиры —" in item["note"]), "")
    assert "ППТ" in note, note
    assert "0,65" in note and "144 300" in note.replace("\u00a0", " "), note
    # Пропорции для ручной сборки остаются калькуляторными.
    assert core.TEP_RATIOS["apartments"]["saleable_of_gns"] == 0.65
