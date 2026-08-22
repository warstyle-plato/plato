"""Импорт пресета: один файл заполняет проект целиком.

Пресет — это собранные вместе ГПЗУ, ППТ, соглашения по ВРИ и МПТ и справки по
техприсоединению. Модель документов не знает: она знает продукты, площади и
деньги, — и весь смысл импорта в переводе одного в другое.

Проверочный случай — Румянцево, 402 000 м² по ППТ. На нём же и вылезают все
ловушки, ради которых написан этот набор:

* **Два спортивных объекта, которые нельзя смешивать.** Стадион регби —
  объект проекта, но строит его АНО «Регби Инвест», а проект платит деньгами;
  СК им. Стрельцова (Торпедо) — вообще чужой объект продавца, и в периметре
  сделки его нет. Оба «спортивные», и на этом сходство кончается.
* **Площадь, которая не должна стать стройкой.** У стадиона есть 5 540 м² по
  ППТ. Посчитать по ним себестоимость — самая естественная ошибка импорта, и
  она добавила бы проекту миллиард расходов, которых у него нет.
* **Техприсоединение вместо удельной ставки.** В справке 225 093 708,38 ₽
  плановых платежей, из них 16 804 764,11 ₽ — тепло стадиона. В потребность
  проекта идут 208 288 944,27 ₽, но исключённый платёж сохраняется: аудит
  должен видеть, что его убрали осознанно.
* **TBD — это значение, а не пропуск.** Денежное обязательство по стадиону в
  пресете не задано, и оно обязано остаться видимым, а не превратиться в ноль.

Маппинг сверен с владельцем 14.08.2026.

Запуск: python3 -m pytest tests -q
"""

from __future__ import annotations

import copy
import json
import math
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import main_legacy as core  # noqa: E402
import project_preset  # noqa: E402

client = TestClient(core.app)


def preset() -> dict:
    """Румянцево: тот же файл, что разбирали руками."""
    return {
        "schema_version": "developaid.project_preset.v3",
        "project": {"name": "Румянцево", "region": "Москва"},
        "planning": {
            "ppt_gfa_total_m2": 402000,
            "objects": [
                {"id": "VGK1", "name": "ВГК-1", "in_deal_perimeter": True, "gfa_m2": 119670,
                 "residential_part_m2": 112250, "embedded_nonresidential_m2": 7420,
                 "cost_settings": {"hard_cost_multiplier": 1.12,
                                   "multiplier_status": "underwriting_assumption",
                                   "underground_gba_m2": "TBD"}},
                {"id": "VGK2", "name": "ВГК-2", "in_deal_perimeter": True, "gfa_m2": 116960,
                 "residential_part_m2": 109750, "embedded_nonresidential_m2": 7210,
                 "cost_settings": {"hard_cost_multiplier": 1.15,
                                   "multiplier_status": "underwriting_assumption",
                                   "underground_gba_m2": "TBD",
                                   "special_requirements": [
                                       {"type": "civil_defense_shelter", "capacity_people": 2780,
                                        "incremental_capex_rub": "TBD"}]}},
                {"id": "EDU", "name": "Единый образовательный объект (СОШ + ДОО)",
                 "in_deal_perimeter": True, "gfa_m2": 14030,
                 "capacity": {"total_places": 530, "school_places": 350, "preschool_places": 180},
                 "cost_classification": "mandatory_social_construction"},
                {"id": "RUGBY", "name": "Стадион регби — денежная социальная нагрузка",
                 "in_deal_perimeter": False, "gfa_m2": 5540,
                 "cost_classification": "social_burden_cash",
                 "construction_capex_in_project": False, "social_burden_cash_rub": "TBD"},
                {"id": "LOS", "name": "ЛОС", "in_deal_perimeter": True, "gfa_m2": 1390},
                {"id": "RP_KNS", "name": "РП/КНС", "in_deal_perimeter": True, "gfa_m2": 100},
                {"id": "BUSINESS_125", "name": "Административно-деловое здание",
                 "in_deal_perimeter": True, "gfa_m2": 125160},
                {"id": "BUSINESS_19", "name": "Общественно-деловое здание с гаражом",
                 "in_deal_perimeter": True, "gfa_m2": 19150},
            ],
        },
        "mpt": {"torpedo": {"name": "Спортивный комплекс им. Э.А. Стрельцова (Торпедо)",
                            "in_deal_perimeter": False, "capex_in_deal": 0,
                            "built_and_funded_by": "продавец",
                            "benefit_to_project": "льгота по ВРИ",
                            "minimum_area_m2": 36530,
                            "max_vri_benefit_rub": 3450828368.0}},
        "vri": {"original_principal_rub": 3757736839.15, "mpt_benefit_rub": 3450828368.0,
                "residual_principal_rub": 306908471.15,
                "planned_interest_on_residual_rub": 51023533.33,
                "confirmed_payments": [{"date": "2026-06-25", "amount_rub": 91010165.85,
                                        "purpose": "рассрочка ВРИ"}],
                "remaining_cash_out_after_confirmed_payment_rub": 266921838.63},
        "tp": {"planned_payments_rub": 225093708.38,
               "planned_payments_project_perimeter_rub": 208288944.27,
               "excluded_rugby_tp_rub": 16804764.11,
               "planned_payments": [
                   {"date": "2027-12-30", "object": "Стадион регби", "resource": "теплоснабжение",
                    "amount_rub": 16804764.11, "include_in_project_tp_cash_need": False},
                   {"date": "2028-09-30", "object": "ВГК-1", "resource": "теплоснабжение",
                    "amount_rub": 64608026.95, "include_in_project_tp_cash_need": True}],
               "open_items": ["АДЦ-2: тепловая нагрузка без договора"]},
        "validation_controls": {"tp_project_perimeter_planned_payments_rub": 208288944.27,
                                "torpedo_capex_in_project": 0,
                                "rugby_construction_capex_in_project": 0},
    }


def preview(**overrides):
    body = {"preset": preset(), "mode": "preview", "inputs": {}, "tep": {}}
    body.update(overrides)
    response = client.post("/api/project-presets/import", json=body)
    assert response.status_code == 200, response.text
    return response.json()


# --- версия схемы ---------------------------------------------------------------

def test_a_foreign_file_is_refused():
    response = client.post("/api/project-presets/import",
                           json={"preset": {"schema_version": "чужая"}})
    assert response.status_code == 400
    assert "версия" in response.json()["detail"].lower()


@pytest.mark.parametrize("version", sorted(project_preset.SCHEMA_VERSIONS))
def test_every_declared_version_is_accepted(version):
    data = preset()
    data["schema_version"] = version
    assert preview(preset=data)["schema_version"] == version


# --- ТЭП ------------------------------------------------------------------------

def test_the_apartments_come_from_the_residential_part():
    """222 000 м² жилой части × 0,75 — коэффициент решён владельцем для башен
    110 м; методика ГлавАПУ даёт 0,65 и для них занижена."""
    tep = preview()["tep"]
    assert tep["apartments"]["saleable"] == pytest.approx(166500.0)
    assert tep["apartments"]["gns"] == pytest.approx(222000.0)


def test_the_embedded_commercial_keeps_its_own_ratio():
    assert preview()["tep"]["ground_commercial"]["saleable"] == pytest.approx(13167.0)


def test_the_offices_use_the_ratio_from_the_mpt_agreement():
    """0,678 — это полезная к ГНС из соглашения МПТ по АДЦ, а не догадка."""
    tep = preview()["tep"]
    assert tep["offices"]["gns"] == pytest.approx(125160.0)
    assert tep["offices"]["saleable"] == pytest.approx(125160.0 * 0.678)


def test_the_garage_becomes_above_ground_parking_not_offices():
    """19 150 м² «с гаражом» — отдельно стоящий паркинг: в офисы он попадал
    только потому, что стоял в строке с деловой недвижимостью."""
    tep = preview()["tep"]
    assert tep["above_parking"]["units"] == math.ceil(19150 / 25)
    assert tep["offices"]["gns"] == pytest.approx(125160.0)


def test_the_underground_parking_covers_what_the_garage_does_not():
    """Потребность считают жильё и офисы вместе, а отдельно стоящий гараж её
    закрывает: под землю уходит остаток. Прежде подземный паркинг считался от
    одних квартир — офисные места не учитывались вовсе, а гараж стоял рядом
    продуктом и ничего не убавлял."""
    tep = preview()["tep"]
    permanent = math.ceil(166500 / 0.75 / 100.0)
    residential = permanent + math.ceil(permanent * 0.1)
    offices = math.ceil(125160 * 0.678 / 100.0)
    garage = math.ceil(19150 / 25)
    assert tep["above_parking"]["units"] == garage
    assert tep["underground_parking"]["units"] == residential + offices - garage
    assert tep["underground_parking"]["gns"] == pytest.approx(
        tep["underground_parking"]["units"] * 35.0)


def test_a_large_garage_leaves_no_underground_need():
    """Если наземных мест хватает на всё, подземного паркинга нет — а не
    отрицательное число мест."""
    data = preset()
    for item in data["planning"]["objects"]:
        if item["id"] == "BUSINESS_19":
            item["gfa_m2"] = 200000
    tep = preview(preset=data)["tep"]
    assert tep["underground_parking"]["units"] == 0


def test_the_education_object_splits_into_school_and_preschool():
    tep = preview()["tep"]
    assert tep["school"]["units"] == 350
    assert tep["kindergarten"]["units"] == 180
    assert tep["school"]["total_area"] + tep["kindergarten"]["total_area"] == pytest.approx(14030.0)


# --- что не должно стать стройкой -----------------------------------------------

def test_the_rugby_stadium_never_becomes_construction():
    """5 540 м² по ППТ — справочная площадь. Посчитать по ним себестоимость —
    самая естественная ошибка импорта, и она стоит проекту миллиарда."""
    data = preview()
    for values in data["tep"].values():
        assert values.get("gns", 0) != 5540
    assert not any("Стадион" in str(row["label"]) for row in data["diff"]["tep"])


def test_the_external_mpt_object_stays_outside_capex():
    """Торпедо строит продавец; проекту он даёт только льготу по ВРИ."""
    reference = preview()["reference"]
    torpedo = next(b for b in reference if "Стрельцова" in b["title"])
    assert torpedo["capex_in_project"] == 0.0
    assert any("льгота" in str(row[1]).lower() for row in torpedo["rows"])


def test_both_sports_objects_are_listed_separately():
    """Слить их в один — значит либо потерять льготу, либо построить чужое."""
    titles = [b["title"] for b in preview()["reference"]]
    assert any("Стрельцова" in t for t in titles)
    assert any("регби" in t.lower() for t in titles)


def test_the_utility_buildings_are_not_products():
    """ЛОС и КНС — часть расходов на сети, а не продаваемые объекты."""
    data = preview()
    notes = " ".join(note["note"] for note in data["notes"])
    assert "ЛОС" in notes and "сет" in notes
    for values in data["tep"].values():
        assert values.get("gns", 0) not in (1390, 100)


# --- деньги ---------------------------------------------------------------------

def test_the_vri_arrives_already_calculated():
    """Остаток посчитан с учётом льготы МПТ и сделанного платежа. Свой расчёт
    движка выключается: пересчитав, он молча заменил бы документ."""
    inputs = preview()["inputs"]
    assert inputs["land_rights_cost_mln"] == pytest.approx(266.92183863)
    assert inputs["vri_required"] is False


def test_the_connection_fees_replace_the_unit_rate():
    """Удельная ставка была оценкой того, что теперь известно точно."""
    data = preview()
    gns = sum(float(values.get("gns") or 0) for values in data["tep"].values())
    assert data["inputs"]["utilities_th_per_sqm"] == pytest.approx(
        208288944.27 / gns / 1000.0)


def test_the_excluded_payment_is_still_visible():
    """16,8 млн ₽ убраны из потребности, но не из виду: аудит должен видеть,
    что это решение, а не потеря строки."""
    notes = " ".join(note["note"] for note in preview()["notes"])
    assert "16.8" in notes or "16,8" in notes


def test_an_unknown_amount_stays_unknown():
    """TBD — значение, а не пропуск: ноль здесь означал бы «платить не надо»."""
    data = preview()
    tbd = [note for note in data["notes"] if note["origin"] == "tbd"]
    assert tbd and any("регби" in note["note"].lower() for note in tbd)
    assert "social_compensation_mln" not in data["inputs"]


def test_a_given_amount_is_taken():
    data = preset()
    for item in data["planning"]["objects"]:
        if item["id"] == "RUGBY":
            item["social_burden_cash_rub"] = 1149230000.0
    result = preview(preset=data)
    assert result["inputs"]["social_compensation_mln"] == pytest.approx(1149.23)
    # Школа и садик в этом пресете строятся, поэтому режим совмещённый:
    # «Денежная компенсация» отменила бы стройку целиком.
    assert result["inputs"]["social_mode"] == core.SOCIAL_MODE_BOTH


# --- происхождение чисел --------------------------------------------------------

def test_every_number_says_where_it_came_from():
    """Коэффициент, применённый молча, на экране неотличим от цифры из ППТ."""
    origins = {note["origin"] for note in preview()["notes"]}
    assert {"source", "derived"} <= origins


def test_the_multipliers_stay_assumptions():
    """Глобальные ставки сервиса пресет менять не вправе: один проект переписал
    бы себестоимость всем остальным."""
    multipliers = {m["object"]: m for m in preview()["multipliers"]}
    assert multipliers["ВГК-1"]["multiplier"] == 1.12
    assert multipliers["ВГК-2"]["multiplier"] == 1.15
    assert all(m["status"] == "underwriting_assumption" for m in multipliers.values())
    assert core.DEFAULT_INPUTS["main_above_th_per_sqm"] == 110


def test_the_open_questions_reach_the_screen():
    items = " ".join(preview()["open_items"])
    assert "АДЦ-2" in items
    assert "2780" in items or "civil_defense" in items
    assert "подземная площадь" in items


# --- diff и применение ----------------------------------------------------------

def test_the_preview_shows_what_will_change():
    data = preview(inputs=dict(core.DEFAULT_INPUTS),
                   tep={key: dict(value) for key, value in core.TEP_DEFAULT.items()})
    assert data["diff"]["inputs"] and data["diff"]["tep"]
    row = next(r for r in data["diff"]["inputs"] if r["key"] == "land_rights_cost_mln")
    assert row["was"] == pytest.approx(core.DEFAULT_INPUTS["land_rights_cost_mln"])
    assert row["becomes"] == pytest.approx(266.92183863)


def test_preview_changes_nothing_by_itself():
    """Режим просмотра не возвращает готовых вводных — применять нечего."""
    assert "applied_inputs" not in preview()


def test_apply_keeps_manual_input_it_does_not_touch():
    """Импорт — дополнительный способ заполнения, а не замена проекта."""
    mine = {"purchase_price_mln": 4300.0, "apartment_price_th": 650}
    body = {"preset": preset(), "mode": "apply", "inputs": mine, "tep": {}}
    applied = client.post("/api/project-presets/import", json=body).json()["applied_inputs"]
    assert applied["purchase_price_mln"] == 4300.0
    assert applied["apartment_price_th"] == 650
    assert applied["land_rights_cost_mln"] == pytest.approx(266.92183863)


def test_importing_twice_gives_the_same_result():
    """Идемпотентность: второй импорт того же файла ничего не удваивает."""
    body = {"preset": preset(), "mode": "apply", "inputs": {}, "tep": {}}
    first = client.post("/api/project-presets/import", json=body).json()
    second_body = {"preset": preset(), "mode": "apply",
                   "inputs": first["applied_inputs"], "tep": first["applied_tep"]}
    second = client.post("/api/project-presets/import", json=second_body).json()
    assert second["applied_tep"] == first["applied_tep"]
    assert second["applied_inputs"] == first["applied_inputs"]
    assert second["diff"]["tep"] == []


def test_the_applied_project_is_calculable():
    """Импорт закончен, когда движок посчитал результат, а не когда файл прочтён."""
    body = {"preset": preset(), "mode": "apply",
            "inputs": dict(core.DEFAULT_INPUTS), "tep": {}}
    applied = client.post("/api/project-presets/import", json=body).json()
    merged_tep = {key: dict(value) for key, value in core.TEP_DEFAULT.items()}
    for key, values in applied["applied_tep"].items():
        merged_tep.setdefault(key, {}).update(values)
    result = core.calculate(core.CalcRequest(
        inputs=applied["applied_inputs"], tep=merged_tep, rates=[]))
    assert result["summary"]["revenue"] > 0
    assert result["summary"]["llcr"] > 0


# --- страница -------------------------------------------------------------------

def test_the_page_offers_the_import():
    assert 'id="presetFile"' in core.PAGE
    assert "Импорт проекта / пресета" in core.PAGE


def test_the_page_asks_before_applying():
    """Экран проверки — единственное место, где видно, что заменится.

    Разбор вынесен в `previewPreset`: пресет приходит и файлом, и с сервера, а
    спрашивать надо в обоих случаях. Тест смотрит на общий путь, а не на одну
    из двух дверей — иначе вторая обошла бы проверку молча."""
    assert 'id="presetDialog"' in core.PAGE
    assert "applyPreset()" in core.PAGE
    body = core.PAGE[core.PAGE.index("async function previewPreset("):]
    body = body[:body.index("function presetRows(")]
    assert "mode:'preview'" in body.replace(" ", "")
    # Обе двери ведут через тот же разбор.
    for door in ("async function uploadPreset(", "async function loadServerProjectPreset("):
        opened = core.PAGE[core.PAGE.index(door):]
        opened = opened[:opened.index("\n}\n")]
        assert "previewPreset(" in opened, door


def test_the_screen_separates_documents_from_calculations():
    assert "из документа" in core.PAGE and "рассчитано" in core.PAGE
    assert "не определено" in core.PAGE


def test_applying_lays_over_the_defaults():
    body = core.PAGE[core.PAGE.index("async function applyPreset("):]
    body = body[:body.index("// --- хранилище проектов")]
    assert "structuredClone(INPUT_DEFAULT)" in body
    assert "structuredClone(TEP_DEFAULT)" in body


def test_applying_replaces_stale_phasing_with_the_preset_phasing():
    """ТЭП нового проекта нельзя раскладывать по долям старого проекта.

    До исправления импорт менял вводные и метры, но вообще не присваивал
    `phasing`: на экране оставались 40/13,1/34/12,9 и прочие старые доли.
    """
    body = core.PAGE[core.PAGE.index("async function applyPreset("):]
    body = body[:body.index("// --- хранилище проектов")]
    assert "const importedPhasing=structuredClone(data.phasing)" in body
    assert "phasing.products=importedPhasing.products||phaseDefaults.products" in body
    assert "phasing.shared_cash=Object.assign" in body
    assert "renderPhasing()" in body


# --- две нагрузки сразу модель пока не считает ----------------------------------

def test_cash_burden_does_not_cancel_mandatory_construction():
    """Прежде `social_mode` был переключателем «или/или»: денежная компенсация
    отменяла стройку соцобъектов целиком, и добавленный расход поднимал EBITDA
    на 0,46 млрд ₽. У Румянцева школа и ДОО строятся, а за стадион платят
    деньгами — для этого и появился третий режим (решение владельца)."""
    body = {"preset": preset(), "mode": "apply", "inputs": {}, "tep": {},
            "filled": {"social_compensation_mln": 1149.23}}
    applied = client.post("/api/project-presets/import", json=body).json()["applied_inputs"]
    assert applied["social_mode"] == core.SOCIAL_MODE_BOTH
    assert applied["social_compensation_mln"] == pytest.approx(1149.23)
    assert applied["school_places"] == 350


def test_without_construction_the_cash_burden_is_counted():
    """Когда строить нечего, компенсация — единственная форма нагрузки."""
    data = preset()
    data["planning"]["objects"] = [item for item in data["planning"]["objects"]
                                   if item["id"] != "EDU"]
    body = {"preset": data, "mode": "apply", "inputs": {}, "tep": {},
            "filled": {"social_compensation_mln": 1149.23}}
    applied = client.post("/api/project-presets/import", json=body).json()["applied_inputs"]
    assert applied["social_compensation_mln"] == pytest.approx(1149.23)
    assert applied["social_mode"] == "Денежная компенсация"


def test_a_filled_value_reaches_the_inputs():
    body = {"preset": preset(), "mode": "apply", "inputs": {}, "tep": {},
            "filled": {"purchase_price_mln": 4300}}
    applied = client.post("/api/project-presets/import", json=body).json()["applied_inputs"]
    assert applied["purchase_price_mln"] == 4300


def test_the_screen_offers_a_field_for_unknown_values():
    """Править JSON ради одного числа — способ его туда и не внести."""
    assert 'id="fill_' in core.PAGE
    assert "presetFilledValues()" in core.PAGE


def test_the_projects_key_can_be_changed_without_the_console():
    assert "changeProjectsKey()" in core.PAGE
    assert "Сменить ключ" in core.PAGE


def test_the_social_capacity_lives_inside_the_object():
    """Мощность соцобъекта читается из `capacity` объекта, а не из своего раздела.

    В пресете КРТ Нагатино школа и ДОО были объявлены объектами, а места —
    отдельным разделом `social_infrastructure`, которого загрузчик не видит.
    Пресет выглядел полным, ошибки не было, а реестр соцобъектов показывал
    0 / 0: поле, которого нет в карте записи, молча остаётся пустым.
    """
    path = Path(__file__).resolve().parent.parent / "presets" / "КРТ_Нагатино.json"
    if not path.exists():
        pytest.skip("пресет КРТ Нагатино не найден")
    data = project_preset.parse_preset(json.loads(path.read_text(encoding="utf-8")))
    tep, _ = project_preset.map_tep(data)
    assert tep["school"]["units"] == 1000
    assert tep["kindergarten"]["units"] == 350
    assert tep["school"]["total_area"] == 22220
    assert tep["kindergarten"]["total_area"] == 6300


def test_the_nagatino_preset_declares_its_own_numbers():
    """Пресет обязан назвать площади и места сам, а не отдать их фолбэкам.

    Продаваемая жилья, машино-места и число квартир были описаны в разделе
    `tep_derived`, но не объявлены у объектов. Загрузчик их не видел и брал
    свои умолчания: продаваемая выходила 161 790 м² вместо 140 218 (доля 0,75
    вместо 0,65), паркинг 3 004 места вместо 2 503, а количество квартир
    оставалось абсолютной величиной 1 361,8 из TEP_DEFAULT — снятой с чужой
    продаваемой площади, то есть 118 м² на квартиру.
    """
    path = Path(__file__).resolve().parent.parent / "presets" / "КРТ_Нагатино.json"
    if not path.exists():
        pytest.skip("пресет КРТ Нагатино не найден")
    preview = project_preset.build_preview(json.loads(path.read_text(encoding="utf-8")))
    tep = preview["tep"]
    assert tep["apartments"]["saleable"] == pytest.approx(140_218.4, abs=1.0)
    assert tep["underground_parking"]["units"] == 2503
    assert tep["underground_parking"]["guest_units"] == 162
    assert tep["apartments"]["units"] > 2000  # не 1 361,8 из умолчаний
    saleable = tep["apartments"]["saleable"]
    assert 45 <= saleable / tep["apartments"]["units"] <= 70

    # Снос доезжает деньгами: прежние ключи economics.demolition_* загрузчик
    # не читал вовсе, и статья не попадала в модель ни рублём.
    assert preview["inputs"]["social_compensation_mln"] == pytest.approx(768.2, abs=0.1)
    assert preview["inputs"]["social_mode"] == project_preset.SOCIAL_MODE_BOTH
