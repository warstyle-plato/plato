import main_legacy as core

from auction_search.krt_screening import build_krt_model_screening


PROJECT = {
    "slug": "no7-oktabr-skoe-pole",
    "name": "№7 Октябрьское поле",
    "housing_gfa_sqm": 161_680,
    "business_gfa_sqm": 12_700,
    "total_gfa_sqm": 184_930,
}


def _market(price: int, market: int = 708_000) -> dict:
    """`price` — цена входа соседей (справка), `market` — рекомендация отчёта (в модель)."""
    return {
        "analysis": {
            "site": {
                "segment": "бизнес",
                "price_per_sqm": market,
                "sold_lot_avg": 50.0,
                "units_per_month": 21.5,
            }
        },
        "price_hint": {"entry_per_sqm": price, "price_per_sqm": market},
    }


def test_krt_screening_uses_market_class_and_authoritative_phasing() -> None:
    # 680 тыс ₽/м², а не 650: полный профиль себестоимости класса «бизнес»
    # (26.08.2026 — благоустройство 15,5 и сети 10,8 вместо умолчаний) опустил
    # LLCR слабейшей очереди на прежней цене ниже целевых 1,20x ещё до цены
    # входа — потолок честно не подбирался. Тесту нужен проект, где потолок
    # существует; отказ подбора проверяется отдельным тестом ниже.
    result = build_krt_model_screening(PROJECT, _market(680_000), core)

    assert result["available"] is True
    assert result["market"]["recommended_segment"] == "бизнес"
    assert result["market"]["model_class"] == "business"
    # Стартовая цена — рекомендация отчёта (708), а не цена входа соседей (680):
    # два ответа одного модуля на один вопрос — второй ответ.
    assert result["market"]["start_price_rub_sqm"] == 708_000
    assert result["market"]["entry_price_rub_sqm"] == 680_000
    assert result["phasing"]["count"] == 2
    assert result["phasing"]["saleable_sqm"] == round(161_680 * 0.65)
    assert len(result["phasing"]["phases"]) == 2
    assert result["absorption"]["available"] is True
    assert result["absorption"]["market_units_per_month"] == 21.5
    assert result["absorption"]["sellout_months_per_phase"] > 24
    assert result["metrics"]["weakest_phase_llcr_x"] == min(
        row["llcr_x"] for row in result["phasing"]["phases"]
    )
    # Светофор судит проект целиком, слабейшая очередь остаётся рядом диагнозом.
    assert result["metrics"]["project_llcr_x"] == round(result["metrics"]["llcr_x"], 3)
    assert result["metrics"]["project_llcr_x"] >= result["metrics"]["weakest_phase_llcr_x"]
    assert "LLCR проекта" in result["text"]
    assert result["entry_capacity"]["available"] is True
    assert result["entry_capacity"]["amount_mln"] > 0
    assert any("Цена приобретения" in row for row in result["exclusions"])
    assert any("ВРИ" in row for row in result["exclusions"])


def test_krt_screening_can_reject_operating_case_before_land_price() -> None:
    result = build_krt_model_screening(PROJECT, _market(455_000, market=455_000), core)

    assert result["available"] is True
    assert result["traffic_light"]["tone"] == "bad"
    assert result["metrics"]["net_profit_mln"] < 0
    assert result["entry_capacity"]["available"] is False


def test_krt_screening_does_not_invent_market_class_or_price() -> None:
    no_class = build_krt_model_screening(PROJECT, {"analysis": {}}, core)
    no_price = build_krt_model_screening(
        PROJECT, {"analysis": {"site": {"segment": "бизнес"}}}, core
    )

    assert no_class == {"available": False, "reason": "Маркетинг пока не определил класс продукта"}
    assert no_price == {"available": False, "reason": "Маркетинг пока не дал ценового ориентира"}


def test_published_krt_duties_reach_developaid_without_an_invented_cost() -> None:
    requirements = {
        "available": True,
        "decision_available": True,
        "source_level": "official_project_decision",
        "object_actions": [
            {"category": "demolition", "area_sqm": 1250, "cadastral_number": "77:01:1:1"},
            {"category": "demolition_or_reconstruction", "area_sqm": 800,
             "cadastral_number": "77:01:1:2"},
            {"category": "reconstruction", "area_sqm": 600,
             "cadastral_number": "77:01:1:3"},
            {"category": "preservation", "area_sqm": 400,
             "cadastral_number": "77:01:1:4"},
        ],
        "construction": ["Предусмотреть строительство объекта образования"],
        "resettlement": ["Переселение жителей выполняется в установленном порядке"],
        "permitted_uses": ["4.2 · Объекты торговли"],
        "deadlines": ["Предельный срок реализации — 6 лет"],
    }
    result = build_krt_model_screening(
        PROJECT, _market(680_000), core, requirements=requirements)

    inputs = result["model_inputs"]["inputs"]
    assert inputs["demolition_area_sqm"] == 1250
    assert inputs["demolition_cost_th_per_sqm"] == 0
    assert result["requirements"]["conditional_area_sqm"] == 800
    assert result["requirements"]["reconstruction_area_sqm"] == 600
    assert result["requirements"]["preservation_area_sqm"] == 400
    assert result["requirements"]["resettlement_mentions"] == 1
    assert result["requirements"]["permitted_uses"] == ["4.2 · Объекты торговли"]
    assert result["requirements"]["unmodelled_construction"]
    assert result["traffic_light"]["tone"] != "ok"
    assert any("стоимость сноса" in item for item in result["exclusions"])
    assert any("снос/реконструкция" in item for item in result["exclusions"])
    assert any("расселение/изъятие" in item for item in result["exclusions"])


def _social(programme: dict, kind: str, field: str) -> float:
    row = next(r for r in programme["social"] if r["kind"] == kind)
    return float(row[field])


def test_the_handoff_carries_this_site_and_not_the_default_one() -> None:
    """«В девелоп он передаёт какой-то другой участок и явно не 14 га»
    (владелец, 02.09.2026): модель собиралась от умолчаний целиком — с офисами
    10 000 м² и участком прошлого проекта. Поля участка обнуляются списком
    страницы, площадь территории — из каталога."""
    from developaid_v2_form import territory_input_keys

    project = dict(PROJECT, area_ha=14.62, total_gfa_sqm=443_700)
    result = build_krt_model_screening(project, _market(680_000), core)
    inputs = result["model_inputs"]["inputs"]
    assert inputs["site_area_ha"] == 14.62
    assert inputs["site_density_sqm_per_ha"] == round(443_700 / 14.62, 1)
    # Поле участка либо обнулено, либо посчитано ПО ЭТОЙ площадке: соцобъекты и
    # нежилые продукты собираются из объёмов города, и требовать от них нуля
    # значило бы требовать, чтобы город ничего не дал. Проверяется поэтому не
    # ноль, а происхождение — число обязано совпасть с разложенной программой.
    programme = result["programme"]
    applied, _ = core.tep_ratios_applied("")
    ratios = {
        "offices": float(applied["offices"]["saleable_of_gns"]),
        "retail": float(applied["standalone_retail"]["saleable_of_gns"]),
    }
    computed = {
        "kindergarten_places": _social(programme, "kindergarten", "places"),
        "school_places": _social(programme, "school", "places"),
        "clinic_capacity": _social(programme, "clinic", "places"),
        "social_dou_gba_sqm": _social(programme, "kindergarten", "gba_sqm"),
        "social_school_gba_sqm": _social(programme, "school", "gba_sqm"),
        "social_clinic_gba_sqm": _social(programme, "clinic", "gba_sqm"),
        "offices_gba_sqm": programme["offices_gba_sqm"],
        "offices_saleable_sqm": programme["offices_gba_sqm"] * ratios["offices"],
        "retail_gba_sqm": max(0.0, programme["commercial_gba_sqm"]),
        "retail_saleable_sqm": max(0.0, programme["commercial_gba_sqm"]) * ratios["retail"],
    }
    for key in territory_input_keys(core):
        if key in ("site_area_ha", "site_density_sqm_per_ha"):
            continue
        if key in computed:
            assert round(float(inputs.get(key) or 0.0), 1) == round(computed[key], 1), (
                f"поле участка {key} не совпало с разложенной программой города")
            continue
        assert not inputs.get(key), f"поле участка {key} приехало от умолчаний: {inputs.get(key)!r}"
    # Умолчания движка при этом несут чужой участок — иначе проверять было бы нечего.
    assert core.DEFAULT_INPUTS.get("land_rights_cost_mln") or core.DEFAULT_INPUTS.get("offices_gba_sqm")
