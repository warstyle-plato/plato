"""Тесты калькулятора Подмосковья: соцнагрузка РНГП МО, ТЭП и плата за смену ВРИ.

Эталоны взяты из расчётов заказчика: ППТ на 200 000 м² квартир и расчёт смены
ВРИ по 22 участкам в Мытищах. Сеть не используется — ЕГРН подменяется фикстурой.
Запуск: python3 -m pytest tests -q
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from fastapi import HTTPException

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import main as _wrapper  # noqa: E402

main = _wrapper.core

# --- эталон ППТ на 200 000 м² квартир ---------------------------------------

SAMPLE_APARTMENTS_SQM = 200000.0

# Участки из расчёта смены ВРИ (площадь, кадастровая стоимость).
MYTISHCHI_PARCELS = [
    (73156, 358977955.12), (82697, 547422715.14), (500, 3595380.0), (916, 6872319.0),
    (990, 7126307.1), (990, 7110051.3), (500, 3679715.0), (500, 3681790.0),
    (500, 3681310.0), (980, 7177618.0), (985, 7144894.5), (500, 3690100.0),
    (500, 3726575.0), (500, 3690185.0), (500, 3726395.0), (500, 3689670.0),
    (500, 3690695.0), (500, 3690545.0), (580, 4310786.2), (580, 4310589.0),
    (980, 7015565.2), (55876, 281002080.28),
]
MYTISHCHI_MARKET_PRICE = 208733.0


def parcels() -> list[dict]:
    return [
        {"cadastral_number": f"50:12:0100131:{index}", "area_sqm": area, "cadastral_value_rub": value}
        for index, (area, value) in enumerate(MYTISHCHI_PARCELS, start=1)
    ]


def parcel_feature(area_sqm: float = 73156.0, value: float = 358977955.12) -> dict:
    return {
        "type": "Feature",
        "geometry": {"type": "Polygon", "coordinates": [[
            [4200000, 7550000], [4200100, 7550000], [4200100, 7550100], [4200000, 7550100], [4200000, 7550000],
        ]]},
        "properties": {
            "categoryName": "Земельные участки ЕГРН",
            "options": {
                "cad_num": "50:12:0100131:497",
                "readable_address": "Московская область, городской округ Мытищи, д. Юрьево",
                "land_record_area": area_sqm,
                "cost_value": value,
                "quarter_cad_number": "50:12:0100131",
                "permitted_use_established_by_document": "Для ведения личного подсобного хозяйства",
            },
        },
    }


@pytest.fixture
def egrn(monkeypatch):
    monkeypatch.setattr(main, "_nspd_search_features", lambda query: [parcel_feature()])


# --- социальная нагрузка ----------------------------------------------------

@pytest.fixture(scope="module")
def program():
    return main.mo_social_program(SAMPLE_APARTMENTS_SQM)


@pytest.mark.parametrize("path, expected", [
    ("population", 7143),
    ("kindergarten.required_places", 464.295),
    ("kindergarten.places", 465),
    ("kindergarten.site_ha", 1.767),
    ("school.required_places", 964.305),
    ("school.places", 975),
    ("school.site_ha", 3.0225),
    ("clinic.required_capacity", 126.788),
    ("clinic.capacity", 127),
    ("parking.permanent_spaces", 2289),
    # Временные места — НОРМАТИВ, а не число этого ППТ: «не менее 30 на 1000»
    # (п. 5.12), то есть 215 на 7 143 жителя. В самом ППТ заказчика их 458 —
    # 64 на тысячу, — и это его собственное решение выше пола нормы. «ППТ может
    # быть у всех разное, а норматив один» (владелец, 04.09.2026): модель
    # показывает норматив, конкретное требование вписывают, когда оно известно.
    ("parking.temporary_spaces", 215),
    ("parking.underground_sqm", 80115.0),
    ("green.quarter_sqm", 46429.5),
    ("green.public_sqm", 31429.2),
    ("jobs.required", 3571.5),
    ("gns_sqm", 314911.04),
    ("budget_compensation.hospital_beds", 42.858),
    ("budget_compensation.ambulance_cars", 0.714),
    ("budget_compensation.fire_cars", 1.429),
])
def test_social_program_matches_ppt_sample(program, path, expected):
    value = program
    for key in path.split("."):
        value = value[key]
    assert value == pytest.approx(expected, abs=0.01)


def test_public_premises_breakdown(program):
    rows = {item["label"]: item["gba_sqm"] for item in program["public_premises"]}
    assert rows["Торговые объекты"] == pytest.approx(14207.43, abs=0.02)
    assert rows["Бытовое обслуживание"] == pytest.approx(2335.76, abs=0.02)
    assert rows["Общественное питание"] == pytest.approx(1714.32, abs=0.02)
    assert program["public_premises_sqm"] == pytest.approx(sum(rows.values()), abs=0.02)


def test_offices_cover_the_jobs_deficit(program):
    jobs = program["jobs"]
    assert jobs["from_objects"] > 0
    assert jobs["deficit"] == pytest.approx(jobs["required"] - jobs["from_objects"], abs=0.01)
    assert program["office_sqm"] == pytest.approx(jobs["deficit"] * 10, abs=0.01)


def test_norms_can_be_overridden():
    changed = main.mo_social_program(SAMPLE_APARTMENTS_SQM, {"living_space_per_person_sqm": 35.0})
    assert changed["population"] == 5715
    assert changed["kindergarten"]["places"] < 465


def test_zero_area_gives_empty_program():
    empty = main.mo_social_program(0)
    assert empty["population"] == 0
    assert empty["kindergarten"]["places"] == 0
    assert empty["public_premises_sqm"] == 0


# --- плата за смену ВРИ -----------------------------------------------------

@pytest.fixture(scope="module")
def vri():
    reference = main._mo_district_upks("Городской округ Мытищи")
    return main.mo_vri_payment(
        parcels(),
        upks_target=reference["upks_land_residential"],
        upks_average_oks=reference["upks_oks_mkd"],
        apartments_sqm=SAMPLE_APARTMENTS_SQM,
        market_price_rub_per_sqm=MYTISHCHI_MARKET_PRICE,
        kd=0.1,
    )


def test_vri_matches_customer_sample(vri):
    assert vri["total_area_sqm"] == pytest.approx(224230, abs=0.01)
    assert vri["cadastral_value_current_rub"] == pytest.approx(1279013240.84, abs=0.05)
    assert vri["cadastral_value_target_rub"] == pytest.approx(1909977686.2, abs=0.5)
    assert vri["delta_rub"] == pytest.approx(630964445.36, abs=0.5)
    assert vri["k1"] == pytest.approx(1.8302, abs=0.0001)
    assert vri["k"] == pytest.approx(3.615, abs=0.001)
    assert vri["payment_rub"] == pytest.approx(4174618253.82, rel=1e-9)


def test_vri_chain_collapses_to_direct_formula(vri):
    # П = дельтаКС × К1 × К алгебраически равно Кср × S × Кд (с точностью до 1.00001 в G)
    direct = MYTISHCHI_MARKET_PRICE * SAMPLE_APARTMENTS_SQM * 0.1
    assert vri["payment_direct_rub"] == pytest.approx(direct, rel=1e-9)
    assert vri["payment_rub"] == pytest.approx(direct, rel=2e-5)


def test_vri_per_parcel_rows(vri):
    first = vri["parcels"][0]
    assert first["area_sqm"] == 73156
    assert first["upks_current"] == pytest.approx(4907.02, abs=0.01)
    assert first["upks_target"] == pytest.approx(8517.94, abs=0.01)
    assert first["delta_rub"] == pytest.approx(264160463.52, abs=0.5)


def test_vri_without_parcels_falls_back_to_direct():
    result = main.mo_vri_payment(
        [], upks_target=8517.94, upks_average_oks=114047.68,
        apartments_sqm=200000, market_price_rub_per_sqm=MYTISHCHI_MARKET_PRICE, kd=0.1,
    )
    assert result["payment_rub"] is None
    assert result["payment_used_rub"] == pytest.approx(4174660000.0, rel=1e-9)
    assert result["payment_basis"].startswith("прямая формула")
    assert any("не заданы" in item for item in result["warnings"])


def test_vri_without_market_price_is_not_calculated():
    result = main.mo_vri_payment(
        parcels(), upks_target=8517.94, upks_average_oks=114047.68,
        apartments_sqm=200000, market_price_rub_per_sqm=0, kd=0.1,
    )
    assert result["payment_used_rub"] is None
    assert any("Кср" in item for item in result["warnings"])


# --- справочники ------------------------------------------------------------

def test_district_reference_holds_all_districts():
    assert len(main._MO_UPKS_BY_DISTRICT) == 60
    mytishchi = main._mo_district_upks("Городской округ Мытищи")
    assert mytishchi["upks_land_residential"] == pytest.approx(8517.94)
    assert mytishchi["upks_oks_mkd"] == pytest.approx(114047.68)


@pytest.mark.parametrize("written", [
    "Мытищи", "мытищи", "Городской округ Мытищи", "г.о. Мытищи", "ГОРОДСКОЙ ОКРУГ МЫТИЩИ",
])
def test_district_lookup_is_tolerant_to_wording(written):
    assert main._mo_district_upks(written)["district"] == "Городской округ Мытищи"


def test_unknown_district_returns_empty_reference():
    assert main._mo_district_upks("Городской округ Тверь")["district"] == ""


@pytest.mark.parametrize("address, expected", [
    ("Московская область, городской округ Мытищи, д. Юрьево", "Городской округ Мытищи"),
    ("Московская обл., г.о. Люберцы, пос. Октябрьский", "Городской округ Люберцы"),
    ("обл. Московская, Ленинский городской округ, с. Молоково", "Ленинский городской округ"),
    ("г. Москва, ул. Тверская", ""),
])
def test_district_detected_from_address(address, expected):
    assert main._mo_district_from_address(address) == expected


def test_quarter_registry_is_loaded():
    table = main._mo_quarter_upks_table()
    assert len(table) > 30000
    assert "50:12:0100131" in table


# --- сквозной расчёт --------------------------------------------------------

def test_calculate_from_cadastral_number(egrn):
    result = main.mo_calculate(main.MoCalculateRequest(
        query="50:12:0100131:497", density_sqm_per_ha=8000, market_price_rub_per_sqm=MYTISHCHI_MARKET_PRICE,
    ))
    territory = result["territory"]
    assert territory["site_area_ha"] == pytest.approx(7.3156, abs=0.0001)
    assert territory["district"] == "Городской округ Мытищи"
    assert territory["district_source"] == "адрес ЕГРН"
    assert territory["quarter"] == "50:12:0100131"
    assert result["social"]["apartments_sqm"] == pytest.approx(7.3156 * 8000, abs=0.01)
    assert result["vri"]["payment_basis"] == "методика по участкам ЕГРН"


def test_default_density_is_30000(egrn):
    result = main.mo_calculate(main.MoCalculateRequest(query="50:12:0100131:497"))
    assert result["density_sqm_per_ha"] == 30000
    assert result["social"]["apartments_sqm"] == pytest.approx(7.3156 * 30000, abs=0.01)


def test_density_is_a_parameter():
    low = main.mo_calculate(main.MoCalculateRequest(site_area_ha=10, density_sqm_per_ha=9000, district="Мытищи"))
    high = main.mo_calculate(main.MoCalculateRequest(site_area_ha=10, density_sqm_per_ha=18000, district="Мытищи"))
    assert high["social"]["population"] == pytest.approx(low["social"]["population"] * 2, rel=0.001)


def test_dense_project_warns_about_territory_balance():
    result = main.mo_calculate(main.MoCalculateRequest(site_area_ha=10, density_sqm_per_ha=30000, district="Мытищи"))
    assert result["balance"]["remaining_ha"] < 0
    assert any("не помещается" in item for item in result["warnings"])


def test_moscow_number_is_rejected():
    with pytest.raises(HTTPException) as exc:
        main.mo_calculate(main.MoCalculateRequest(query="77:01:0001001:1"))
    assert exc.value.status_code == 400
    assert "Московской области" in str(exc.value.detail)


def test_manual_area_without_query_works():
    result = main.mo_calculate(main.MoCalculateRequest(site_area_ha=22.89, density_sqm_per_ha=8737.9, district="Мытищи"))
    assert result["territory"]["parcel_count"] == 0
    assert result["social"]["population"] == 7144


def test_area_is_required():
    with pytest.raises(HTTPException) as exc:
        main.mo_calculate(main.MoCalculateRequest())
    assert exc.value.status_code == 400


def test_egrn_failure_explains_what_to_do(monkeypatch):
    monkeypatch.setattr(main, "_nspd_search_features", lambda query: [])
    with pytest.raises(HTTPException) as exc:
        main.mo_calculate(main.MoCalculateRequest(query="50:12:0100131:497"))
    assert "вручную" in str(exc.value.detail)


# --- перенос в модель -------------------------------------------------------

def test_tep_and_inputs_feed_the_model():
    result = main.mo_calculate(main.MoCalculateRequest(
        site_area_ha=22.89, density_sqm_per_ha=8737.9, district="Мытищи",
        market_price_rub_per_sqm=MYTISHCHI_MARKET_PRICE,
    ))
    social = result["social"]
    tep = result["tep"]
    assert tep["apartments"]["saleable"] == pytest.approx(social["apartments_sqm"], abs=0.01)
    assert tep["apartments"]["gns"] == pytest.approx(social["gns_sqm"], abs=0.01)
    assert tep["underground_parking"]["units"] == social["parking"]["permanent_spaces"]
    assert tep["kindergarten"]["units"] == social["kindergarten"]["places"]
    assert tep["school"]["units"] == social["school"]["places"]

    inputs = {**main.DEFAULT_INPUTS, **result["inputs"]}
    assert inputs["kindergarten_places"] == social["kindergarten"]["places"]
    assert inputs["land_rights_cost_mln"] == pytest.approx(result["vri"]["payment_used_mln"])
    calculated = main.calculate(main.CalcRequest(inputs=inputs, tep=tep, rates=[]))
    assert calculated["summary"]["revenue"] > 0
    assert calculated["tep"]["total"]["saleable"] > 0


def test_model_export_works_on_mo_project():
    result = main.mo_calculate(main.MoCalculateRequest(site_area_ha=15, density_sqm_per_ha=9000, district="Мытищи"))
    content, filename, meta = main.build_project_workbook(
        {**main.DEFAULT_INPUTS, **result["inputs"]}, result["tep"], [], {}, project_name="Подмосковье",
    )
    assert content[:2] == b"PK"
    assert "Подмосковье" in filename
    assert meta["missing"] == [], meta["missing"]


# --- эндпоинты и бот --------------------------------------------------------

def test_reference_endpoint():
    reference = main.mo_reference()
    assert reference["density_default_sqm_per_ha"] == 30000
    assert len(reference["districts"]) == 60
    assert reference["quarter_upks_loaded"] > 30000
    assert "living_space_per_person_sqm" in reference["norms"]


def test_routes_are_registered():
    routes = {getattr(route, "path", "") for route in _wrapper.app.routes}
    assert {"/mo/calculate", "/mo/reference"}.issubset(routes)


def test_bot_routes_region_50_to_mo_calculator(monkeypatch, egrn):
    sent: list[dict] = []
    monkeypatch.setattr(main, "_telegram_api", lambda method, payload=None: {"ok": True})
    monkeypatch.setattr(
        _wrapper, "_ORIGINAL_SEND_MESSAGE",
        lambda chat_id, text, *, reply_markup=None, **kw: sent.append({"text": text, "markup": reply_markup}),
    )
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "test-token")
    main._telegram_handle_cadastral_numbers(555, ["50:12:0100131:497"])
    texts = " ".join(item["text"] for item in sent)
    assert "Московской области" in texts
    assert "Проверьте ТЭП" in texts
    assert _wrapper._PLATON_TEP_CONTEXT.get(555)


def test_bot_keeps_moscow_numbers_on_the_old_path(monkeypatch):
    called: list[str] = []

    def fake_analyze(req):
        called.append("glavapu")
        raise HTTPException(status_code=400, detail="тест")

    monkeypatch.setattr(main, "analyze_cadastral_territory", fake_analyze)
    monkeypatch.setattr(main, "_telegram_send_message", lambda *a, **kw: None)
    main._telegram_handle_cadastral_numbers(556, ["77:01:0001001:1"])
    assert called == ["glavapu"]


# --- справочник Кср (распоряжение Комитета по ценам и тарифам МО) ------------

def market_price_xlsx(rows: list[tuple[str, str]]) -> bytes:
    """Синтетическое приложение к распоряжению в формате .xlsx."""
    table = [["Приложение к распоряжению Комитета по ценам и тарифам Московской области"],
             ["№ п/п", "Наименование муниципального образования", "Стоимость, руб."]]
    for index, (name, price) in enumerate(rows, start=1):
        table.append([str(index), name, price])
    table.append(["", "в целом по Московской области", "185 000,00"])
    return main._build_glavapu_xlsx_from_rows(table, [[""]])


@pytest.fixture(autouse=True)
def clean_market_price(monkeypatch, tmp_path):
    monkeypatch.setattr(main, "_MO_MARKET_PRICE_PATH", tmp_path / "mo_market_price.csv")
    monkeypatch.setattr(main, "_mo_market_price", None)
    yield
    monkeypatch.setattr(main, "_mo_market_price", None)


def test_market_price_import_parses_official_table():
    payload = market_price_xlsx([
        ("Городской округ Мытищи", "208 733,00"),
        ("Городской округ Люберцы", "195 400,50"),
        ("Ленинский городской округ", "210 100,00"),
        ("Городской округ Тверь", "150 000,00"),
    ])

    class _Request:
        async def body(self):
            return payload

    import asyncio
    result = asyncio.run(main.mo_market_price_import(_Request(), period="III–IV кварталы 2025"))
    prices = {row["municipality"]: row["price_rub_per_sqm"] for row in result["rows"]}
    assert prices["Городской округ Мытищи"] == pytest.approx(208733.0)
    assert prices["Городской округ Люберцы"] == pytest.approx(195400.5)
    assert prices["Ленинский городской округ"] == pytest.approx(210100.0)
    assert prices["Московская область (среднее)"] == pytest.approx(185000.0)
    assert result["matched_districts"] == 3
    assert "Городской округ Тверь" in result["unmatched"]
    assert result["stored_on_disk"] is True
    assert result["csv"].startswith("municipality,")


def test_market_price_import_rejects_table_without_prices():
    class _Request:
        async def body(self):
            return main._build_glavapu_xlsx_from_rows([["Наименование"], ["Городской округ Мытищи"]], [[""]])

    import asyncio
    with pytest.raises(HTTPException) as exc:
        asyncio.run(main.mo_market_price_import(_Request()))
    assert exc.value.status_code == 400


def test_market_price_manual_upload_and_readback():
    main.mo_market_price_set(main.MoMarketPriceRequest(
        rows=[{"municipality": "Мытищи", "price_rub_per_sqm": 208733}],
        period="III–IV кварталы 2025",
        document="Распоряжение № 89-Р от 22.04.2025",
    ))
    table = main.mo_market_price()
    assert table["count"] == 1
    assert table["rows"][0]["municipality"] == "Городской округ Мытищи"
    assert table["period"] == "III–IV кварталы 2025"


def test_market_price_is_used_as_ksr_by_default():
    main.mo_market_price_set(main.MoMarketPriceRequest(
        rows=[{"municipality": "Городской округ Мытищи", "price_rub_per_sqm": 208733}],
        period="III–IV кварталы 2025",
    ))
    result = main.mo_calculate(main.MoCalculateRequest(site_area_ha=10, density_sqm_per_ha=9000, district="Мытищи"))
    vri = result["vri"]
    assert vri["market_price_rub_per_sqm"] == pytest.approx(208733.0)
    assert vri["market_price_source"] == "распоряжение Комитета по ценам и тарифам МО"
    assert vri["market_price_period"] == "III–IV кварталы 2025"
    assert vri["payment_used_rub"] == pytest.approx(208733.0 * 90000 * 0.1, rel=1e-9)


def test_explicit_ksr_wins_over_reference():
    main.mo_market_price_set(main.MoMarketPriceRequest(
        rows=[{"municipality": "Городской округ Мытищи", "price_rub_per_sqm": 208733}],
    ))
    result = main.mo_calculate(main.MoCalculateRequest(
        site_area_ha=10, district="Мытищи", market_price_rub_per_sqm=250000,
    ))
    assert result["vri"]["market_price_rub_per_sqm"] == pytest.approx(250000.0)
    assert result["vri"]["market_price_source"] == "запрос"


def test_without_reference_falls_back_to_upks():
    result = main.mo_calculate(main.MoCalculateRequest(site_area_ha=10, district="Мытищи"))
    assert result["vri"]["market_price_source"] == "УПКС ОКС округа"
    assert any("не найдена в справочнике" in item for item in result["warnings"])


def test_reference_endpoint_reports_market_price_state():
    assert main.mo_reference()["market_price"]["count"] == 0
    main.mo_market_price_set(main.MoMarketPriceRequest(
        rows=[{"municipality": "Городской округ Мытищи", "price_rub_per_sqm": 208733}], period="III–IV кв. 2025",
    ))
    state = main.mo_reference()["market_price"]
    assert state["count"] == 1 and state["period"] == "III–IV кв. 2025"


def test_totals_row_is_not_a_district():
    assert "Итого по Московской области" not in main._MO_UPKS_BY_DISTRICT
    assert main._MO_UPKS_REGION_AVERAGE[1] == pytest.approx(94205.97)


def test_pavlovsky_posad_synonym():
    assert main._mo_district_upks("Павлово-Посадский городской округ")["district"] == "Городской округ Павловский Посад"


def test_region_average_is_used_when_district_has_no_row():
    main.mo_market_price_set(main.MoMarketPriceRequest(
        rows=[
            {"municipality": "Городской округ Мытищи", "price_rub_per_sqm": 238052},
            {"municipality": "Московская область (среднее)", "price_rub_per_sqm": 198907},
        ],
        period="III–IV кварталы 2026",
    ))
    price, _, _, level = main._mo_market_price_for("Городской округ Протвино")
    assert price == pytest.approx(198907.0)
    assert level == "среднее по области"
    result = main.mo_calculate(main.MoCalculateRequest(site_area_ha=10, district="Городской округ Протвино"))
    assert "среднее по области" in result["vri"]["market_price_source"]
    assert any("нет отдельной строки" in item for item in result["warnings"])


def test_shipped_reference_holds_the_2026_decree(tmp_path, monkeypatch):
    """Файл data/mo_market_price.csv, поставляемый с приложением."""
    monkeypatch.setattr(main, "_MO_MARKET_PRICE_PATH", Path(__file__).resolve().parent.parent / "data" / "mo_market_price.csv")
    monkeypatch.setattr(main, "_mo_market_price", None)
    table = main.mo_market_price()
    assert table["count"] == 56
    assert table["region_average"] == pytest.approx(198907.0)
    assert "2026" in table["period"]
    assert "114-Р" in table["document"]
    prices = {row["municipality"]: row["price_rub_per_sqm"] for row in table["rows"]}
    assert prices["Городской округ Мытищи"] == pytest.approx(238052.0)
    assert prices["Городской округ Красногорск"] == pytest.approx(251426.0)
    assert prices["Городской округ Серебряные Пруды"] == pytest.approx(77041.0)
    assert prices["Городской округ Электросталь"] == pytest.approx(128832.0)
    # каждая строка распоряжения легла на округ справочника УПКС
    unknown = [name for name in prices if name not in main._MO_UPKS_BY_DISTRICT]
    assert unknown == []


def test_upks_source_is_reported():
    source = main.mo_reference()["upks_source"]
    assert source["land"]["valuation_date"] == "01.01.2022"
    assert source["land"]["applied_from"] == "01.01.2023"
    assert source["oks"]["valuation_date"] == "01.01.2023"
    assert "01/2022" in source["land"]["report"]
    assert "01/2023" in source["oks"]["report"]


def test_calculation_carries_upks_source(egrn):
    result = main.mo_calculate(main.MoCalculateRequest(query="50:12:0100131:497"))
    assert result["upks"]["source"]["land"]["valuation_date"] == "01.01.2022"


def test_parcel_rows_carry_cadastral_value_date():
    rows = main.mo_vri_payment(
        [{"cadastral_number": "50:12:0100131:497", "area_sqm": 73156,
          "cadastral_value_rub": 358977955.12, "cadastral_value_date": "2023-01-01"}],
        upks_target=8517.94, upks_average_oks=114047.68, apartments_sqm=200000,
        market_price_rub_per_sqm=MYTISHCHI_MARKET_PRICE, kd=0.1,
    )["parcels"]
    assert rows[0]["cadastral_value_date"] == "2023-01-01"


def test_market_price_routes_are_registered():
    routes = {getattr(route, "path", "") for route in _wrapper.app.routes}
    assert {"/mo/market-price", "/mo/market-price/import"}.issubset(routes)


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
