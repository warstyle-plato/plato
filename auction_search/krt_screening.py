"""Preliminary KRT screening through the authoritative DevelopAid model.

The public KRT catalogue has enough data for a product/scale screen, but not
for an investment decision: acquisition price, land-rights/VRI payments and
the complete investor obligations are absent.  This module therefore builds a
transparent zero-entry scenario, runs the existing model, and reports both the
result and the missing inputs.  It deliberately does not create a second
financial calculator.
"""

from __future__ import annotations

import copy
import math
from typing import Any

from market_search.krt_requirements import social_objects_from_decision
from market_search.segments import BUSINESS, COMFORT, ECONOMY, ELITE, PREMIUM, normalize_segment


TARGET_PHASE_SALEABLE_SQM = 70_000.0
MAX_PHASES = 5
PHASE_GAP_MONTHS = 12
TARGET_LLCR = 1.20
PARKING_GUEST_SHARE = 0.10
UNDERGROUND_AREA_PER_SPACE = 35.0

_CLASS_MAP = {
    ECONOMY: ("comfort", "Комфорт", "Эконом сопоставлен с ближайшим доступным пресетом «Комфорт»"),
    COMFORT: ("comfort", "Комфорт", None),
    BUSINESS: ("business", "Бизнес", None),
    PREMIUM: ("elite", "Элитный", "Премиум сопоставлен с ближайшим доступным пресетом «Элитный»"),
    ELITE: ("elite", "Элитный", None),
}

_TEP_FIELDS = ("gns", "total_area", "useful", "saleable", "transfer", "units")


def _number(value: Any) -> float:
    try:
        return float(value or 0.0)
    except (TypeError, ValueError):
        return 0.0


def _ru_number(value: Any, digits: int = 0) -> str:
    return f"{_number(value):,.{digits}f}".replace(",", " ")


def _queue_word(count: int) -> str:
    if count % 10 == 1 and count % 100 != 11:
        return "очередь"
    if count % 10 in (2, 3, 4) and count % 100 not in (12, 13, 14):
        return "очереди"
    return "очередей"


def _verdict(report: dict[str, Any]) -> dict[str, Any]:
    analysis = report.get("analysis") or {}
    return analysis.get("site") or analysis.get("overall") or {}


def _territory_keys(core: Any) -> list[str]:
    """Поля участка — со страницы движка, копии здесь нет."""
    try:
        from developaid_v2_form import territory_input_keys
        return list(territory_input_keys(core))
    except Exception:  # noqa: BLE001 — страница без списка: обнуляем то, что знаем
        return ["purchase_price_mln", "site_area_ha", "site_density_sqm_per_ha",
                "land_rights_cost_mln", "social_compensation_mln", "offices_gba_sqm",
                "offices_saleable_sqm", "retail_gba_sqm", "retail_saleable_sqm",
                "above_parking_spaces"]


def _empty_tep(core: Any) -> dict[str, dict[str, Any]]:
    tep = copy.deepcopy(core.TEP_DEFAULT)
    for row in tep.values():
        for field in _TEP_FIELDS:
            row[field] = 0.0
    return tep


def _market_inputs(report: dict[str, Any]) -> tuple[str | None, float, float, str]:
    verdict = _verdict(report)
    hint = report.get("price_hint") or {}
    segment = normalize_segment(verdict.get("segment"))
    market_price = _number(verdict.get("price_per_sqm") or hint.get("price_per_sqm"))
    entry_price = _number(hint.get("entry_per_sqm"))
    if entry_price > 0:
        return segment, entry_price, market_price, "медиана входных цен соседних проектов"
    return segment, market_price, market_price, "медиана действующих прайсов рекомендованного класса"


def _phase_configuration(saleable_sqm: float, construction_months: int) -> dict[str, Any]:
    count = max(1, min(MAX_PHASES, math.ceil(saleable_sqm / TARGET_PHASE_SALEABLE_SQM)))
    return {
        "enabled": count > 1,
        "user_enabled": False,
        "automatic": True,
        "phase_count": count,
        "target_size_sqm": TARGET_PHASE_SALEABLE_SQM,
        "phase_gap_months": PHASE_GAP_MONTHS,
        "cost_inflation_pct": 8.0,
        "sales_price_inflation_pct": 8.0,
        "phases": [
            {
                "name": f"О{index + 1}",
                "start_offset_months": index * PHASE_GAP_MONTHS,
                "construction_months": construction_months,
                "products": {},
            }
            for index in range(count)
        ],
    }


def _snapshot(core: Any, result: dict[str, Any]) -> dict[str, Any]:
    if hasattr(core, "_result_snapshot"):
        return core._result_snapshot(result)
    summary = result.get("summary") or {}
    finance = result.get("finance") or {}
    return {
        "revenue_mln": round(_number(summary.get("revenue")) / 1e6, 2),
        "capex_mln": round(_number(summary.get("capex")) / 1e6, 2),
        "net_profit_mln": round(_number(summary.get("net_profit")) / 1e6, 2),
        "margin_pct": round(_number(summary.get("margin")) * 100, 2),
        "llcr_x": round(_number(summary.get("llcr")), 4),
        "peak_bridge_mln": round(_number(finance.get("peak_bridge")) / 1e6, 2),
        "peak_pf_mln": round(_number(finance.get("peak_pf")) / 1e6, 2),
    }


def _phase_rows(bundle: dict[str, Any]) -> list[dict[str, Any]]:
    rows = []
    for item in bundle.get("phases") or []:
        summary = (item.get("result") or {}).get("summary") or {}
        rows.append({
            "name": item.get("name") or f"О{len(rows) + 1}",
            "saleable_sqm": round(_number(summary.get("monetizable_saleable_sqm"))),
            "llcr_x": round(_number(summary.get("llcr")), 3),
            "margin_pct": round(_number(summary.get("margin")) * 100, 1),
        })
    return rows


def _goal_seek_entry_capacity(
    core: Any,
    inputs: dict[str, Any],
    tep: dict[str, dict[str, Any]],
    phasing: dict[str, Any],
    bundle: dict[str, Any],
) -> dict[str, Any] | None:
    if not all(hasattr(core, name) for name in ("AgentChatRequest", "_tool_goal_seek")):
        return None
    request = core.AgentChatRequest(
        message="Предварительный скрининг КРТ",
        inputs=inputs,
        tep=tep,
        rates=[],
        phasing=phasing,
        selected_view="all",
    )
    scope = "weakest_phase" if bundle.get("mode") == "phased" else "consolidated"
    result = core._tool_goal_seek(
        request,
        bundle,
        "purchase_price_mln",
        "llcr",
        TARGET_LLCR,
        "at_least",
        "maximum_variable",
        scope,
        0.0,
        None,
    )
    if not result.get("available"):
        return {"available": False, "reason": result.get("reason")}
    solution = result.get("solution") or {}
    return {
        "available": True,
        "amount_mln": round(_number(solution.get("variable")), 1),
        "llcr_x": round(_number(solution.get("metric")), 3),
        "scope": result.get("scope"),
        "phase_llcr": result.get("phase_llcr_at_solution") or [],
        "meaning": (
            "Предельный резерв по переменной «цена входа» при целевом LLCR 1,20x. "
            "Это не оценка участка: цена, ВРИ и обязательства делят это пространство, "
            "а иной график их оплаты изменит результат."
        ),
    }


def _traffic_light(weakest_llcr: float, net_profit_mln: float) -> dict[str, Any]:
    if net_profit_mln <= 0 or weakest_llcr < 1.0:
        return {"tone": "bad", "label": "Не проходит даже до цены входа", "score": 25}
    if weakest_llcr < TARGET_LLCR:
        return {"tone": "warn", "label": "Ниже целевого LLCR", "score": 55}
    return {"tone": "ok", "label": "Операционный сценарий проходит", "score": 85}


def _requirements_for_model(requirements: dict[str, Any] | None) -> dict[str, Any]:
    """Translate published duties into model inputs without inventing prices."""
    source = requirements if isinstance(requirements, dict) else {}
    actions = source.get("object_actions") or []
    definite_demolition = [
        item for item in actions
        if isinstance(item, dict) and item.get("category") == "demolition"
    ]
    conditional = [
        item for item in actions
        if isinstance(item, dict) and item.get("category") == "demolition_or_reconstruction"
    ]
    reconstruction = [
        item for item in actions
        if isinstance(item, dict) and item.get("category") == "reconstruction"
    ]
    preservation = [
        item for item in actions
        if isinstance(item, dict) and item.get("category") == "preservation"
    ]

    def area(items: list[dict[str, Any]]) -> float:
        return sum(_number(item.get("area_sqm")) for item in items)

    demolition_area = area(definite_demolition)
    conditional_area = area(conditional)
    construction = list(source.get("construction") or [])[:10]
    unmodelled_construction = [
        item for item in construction
        if any(marker in str(item).casefold() for marker in (
            "образован", "школ", "детск", "поликлиник", "медицин",
            "инженер", "дорог", "паркинг", "офис", "торгов", "рынок",
            "спорт", "производствен", "общественно-делов",
        ))
    ]
    return {
        "available": bool(source.get("available")),
        "decision_available": bool(source.get("decision_available")),
        # Что город назвал сам: конкретные ДОО и СОШ иногда стоят прямо в
        # решении, и тогда норматив не спрашивают — документ сильнее.
        "social_objects": social_objects_from_decision(
            list(source.get("construction") or [])
            + list((source.get("decision") or {}).get("construction") or [])
        ),
        "source_level": source.get("source_level"),
        # Городские нужды — не «да/нет», а объём: доля меряется, а не
        # оценивается на глаз. Читается из решения; ноль записей — это «в
        # прочитанном не сказано», и вызывающий обязан отличать это от «нет».
        "renovation": (source.get("renovation")
                       or (source.get("decision") or {}).get("renovation")
                       or {"mentioned": False, "area_sqm": None, "quote": ""}),
        "decision": copy.deepcopy(source.get("decision")),
        "demolition_area_sqm": demolition_area,
        "demolition_objects": len(definite_demolition),
        "demolition_known_area_objects": sum(
            1 for item in definite_demolition if _number(item.get("area_sqm")) > 0),
        "conditional_area_sqm": conditional_area,
        "conditional_objects": len(conditional),
        "conditional_known_area_objects": sum(
            1 for item in conditional if _number(item.get("area_sqm")) > 0),
        "reconstruction_area_sqm": area(reconstruction),
        "reconstruction_objects": len(reconstruction) or len(source.get("reconstruction") or []),
        "reconstruction_known_area_objects": sum(
            1 for item in reconstruction if _number(item.get("area_sqm")) > 0),
        "preservation_area_sqm": area(preservation),
        "preservation_objects": len(preservation) or len(source.get("preservation") or []),
        "preservation_known_area_objects": sum(
            1 for item in preservation if _number(item.get("area_sqm")) > 0),
        "resettlement": list(source.get("resettlement") or [])[:10],
        "resettlement_mentions": len(source.get("resettlement") or []),
        "construction": construction,
        "unmodelled_construction": unmodelled_construction,
        "permitted_uses": list(source.get("permitted_uses") or [])[:20],
        "deadlines": list(source.get("deadlines") or [])[:5],
        "warning": source.get("warning"),
    }


# Соцобъект живёт в трёх местах разом: строкой ТЭП, местами во вводных и
# площадью во вводных. Список объявлен один раз — разойдясь, эти три места
# показали бы про один садик разное, и все три выглядели бы верными.
_SOCIAL_ROWS: dict[str, tuple[str, str, str, str, str]] = {
    "kindergarten": ("kindergarten", "kindergarten_places", "social_dou_gba_sqm",
                     "social_dou_norm_sqm", "ДОО"),
    "school": ("school", "school_places", "social_school_gba_sqm",
               "social_school_norm_sqm", "СОШ"),
    "clinic": ("clinic", "clinic_capacity", "social_clinic_gba_sqm",
               "social_clinic_norm_sqm", "Поликлиника"),
}
POPULATION_SQM_PER_PERSON = 33.0


def _programme(
    core: Any,
    project: dict[str, Any],
    duties: dict[str, Any],
    inputs: dict[str, Any],
    tep: dict[str, dict[str, Any]],
    applied_ratios: dict[str, Any],
    apartments_saleable_sqm: float,
) -> dict[str, Any]:
    """Разложить объёмы города по продуктам модели.

    Город даёт три слагаемых: жилое, нежилое и общественно-деловое (сумма их
    равна общему объёму — проверено на карточках Кунцева и Магистральных улиц).
    Жильё мы считаем сами; соцобъекты город либо назвал в решении, либо их
    считает норматив; **остаток нежилого за вычетом соцобъектов** — это ОСЗ и
    ТЦ, а общественно-деловое — офисы (решение владельца, 02.09.2026).

    Отрицательный остаток — находка, а не ноль: он значит, что соцобъекты по
    нормативу не помещаются в нежилой объём города, и молча обнулить его
    значит спрятать противоречие между двумя источниками.
    """
    housing = _number(project.get("housing_gfa_sqm"))
    nonresidential = _number(project.get("nonresidential_gfa_sqm"))
    business = _number(project.get("business_gfa_sqm"))
    total = _number(project.get("total_gfa_sqm"))
    district = str(project.get("district") or "").strip()
    zone_two = core.district_zone_two(district)
    population = apartments_saleable_sqm / POPULATION_SQM_PER_PERSON

    named: dict[str, dict[str, Any]] = {}
    for item in duties.get("social_objects") or []:
        kind = str(item.get("kind") or "")
        if kind not in _SOCIAL_ROWS:
            continue
        slot = named.setdefault(
            kind, {"places": 0.0, "area_sqm": 0.0, "quotes": [], "numbered": False})
        places = _number(item.get("places"))
        area = _number(item.get("area_sqm"))
        if places > 0 or area > 0:
            slot["numbered"] = True
        slot["places"] += places
        slot["area_sqm"] += area
        if item.get("quote"):
            slot["quotes"].append(str(item["quote"]))

    social_rows: list[dict[str, Any]] = []
    social_area = 0.0
    for kind, (tep_key, places_key, area_key, norm_key, label) in _SOCIAL_ROWS.items():
        norm_sqm = _number(inputs.get(norm_key))
        demanded = named.get(kind)
        by_norm = math.ceil(core.moscow_social_places(kind, population, zone_two=zone_two))
        if demanded and demanded["numbered"]:
            places = demanded["places"]
            area = demanded["area_sqm"]
            if places <= 0 and area > 0 and norm_sqm > 0:
                places = area / norm_sqm
            source = "decision"
        else:
            places = float(by_norm)
            area = 0.0
            # Объект город назвал, а мощность его — нет. Отказаться считать
            # значит потерять обязательство целиком; поэтому считаем нормативом
            # и говорим, что число наше, а не города.
            source = "norm_after_named" if demanded else "norm"
        # Площадь на место — ступень по ёмкости здания (РНГП, редакция
        # 2579-ПП): маленький садик стоит 27 м² на место, крупный 16. Поле
        # вводных несёт одно число на любую ёмкость, поэтому норматив города
        # сильнее — и записывается в то же поле, чтобы страница показывала
        # именно то, чем посчитано.
        city_norm = core.moscow_social_area_per_place(kind, places)
        if city_norm:
            norm_sqm = city_norm
            inputs[norm_key] = city_norm
        if area <= 0:
            area = places * norm_sqm
        inputs[places_key] = places
        inputs[area_key] = area
        tep[tep_key].update({"total_area": area, "transfer": area, "units": places})
        social_area += area
        social_rows.append({
            "kind": kind,
            "label": label,
            "places": round(places, 1),
            "gba_sqm": round(area, 1),
            "norm_sqm_per_place": norm_sqm,
            "norm_is_the_citys": bool(city_norm),
            "by_norm_places": by_norm,
            "source": source,
            "quotes": (demanded or {}).get("quotes", [])[:3],
        })
    # Соцобъекты строятся, а не откупаются: решение города называет объекты, и
    # денежная компенсация вместо них — другое обязательство, а не то же самое.
    inputs["social_mode"] = "Строительство"

    commercial = nonresidential - social_area
    retail_ratios = applied_ratios.get("standalone_retail") or {}
    office_ratios = applied_ratios.get("offices") or {}
    if commercial > 0:
        saleable = commercial * _number(retail_ratios.get("saleable_of_gns"))
        inputs["retail_enabled"] = True
        inputs["retail_gba_sqm"] = commercial
        inputs["retail_saleable_sqm"] = saleable
        tep["standalone_retail"].update({
            "gns": commercial,
            "total_area": commercial * _number(retail_ratios.get("total_of_gns")),
            "useful": saleable,
            "saleable": saleable,
        })
    if business > 0:
        saleable = business * _number(office_ratios.get("saleable_of_gns"))
        inputs["offices_enabled"] = True
        inputs["offices_gba_sqm"] = business
        inputs["offices_saleable_sqm"] = saleable
        tep["offices"].update({
            "gns": business,
            "total_area": business * _number(office_ratios.get("total_of_gns")),
            "useful": saleable,
            "saleable": saleable,
        })

    # Сходимость объявленного городом. Расхождение называется, а не
    # выравнивается: три числа карточки — его данные, и подгонять их под сумму
    # значит выдать нашу правку за его объём.
    declared_sum = housing + nonresidential + business
    difference = total - declared_sum if total > 0 else 0.0
    return {
        "city": {
            "total_gfa_sqm": total,
            "housing_gfa_sqm": housing,
            "nonresidential_gfa_sqm": nonresidential,
            "business_gfa_sqm": business,
            "district": district,
            "zone_two": zone_two,
            "area_ha": _number(project.get("area_ha")),
        },
        "population": int(math.ceil(population)),
        "social": social_rows,
        "social_gba_sqm": round(social_area, 1),
        "social_from_decision": any(row["source"] == "decision" for row in social_rows),
        "commercial_gba_sqm": round(commercial, 1),
        "commercial_negative": commercial < 0,
        "offices_gba_sqm": round(business, 1),
        "balance": {
            "declared_sum_sqm": round(declared_sum, 1),
            "difference_sqm": round(difference, 1),
            "matches": total <= 0 or abs(difference) <= max(1.0, total * 0.001),
            "total_published": total > 0,
        },
    }


def build_krt_model_screening(
    project: dict[str, Any] | None,
    market_report: dict[str, Any],
    core: Any,
    tep_ratios: str = "",
    requirements: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Run an on-demand, explicitly preliminary KRT scenario in DevelopAid.

    Пропорции ТЭП читались прямо из `core.TEP_RATIOS`, мимо разбора движка. На
    обычной странице их правят полем `tep_ratios_custom` — у человека на руках
    бывает ГПЗУ или АГР со своими долями, — и до площадки КРТ эта правка не
    доезжала вовсе, а в предпосылках стояло «по действующей пропорции DevelopAid
    65%», как будто выбор сделан. Теперь доли идут через `tep_ratios_applied`:
    тот же разбор, те же отказы («общая больше ГНС не бывает»), то же умолчание
    при пустой строке.
    """
    if not project:
        return {"available": False, "reason": "Проект КРТ не найден в официальном каталоге"}
    housing_gfa = _number(project.get("housing_gfa_sqm"))
    if housing_gfa <= 0:
        return {
            "available": False,
            "reason": "В официальном каталоге нет жилого объёма для расчёта жилого продукта",
        }

    segment, start_price, market_price, price_basis = _market_inputs(market_report)
    if not segment or segment not in _CLASS_MAP:
        return {"available": False, "reason": "Маркетинг пока не определил класс продукта"}
    if start_price <= 0:
        return {"available": False, "reason": "Маркетинг пока не дал ценового ориентира"}

    model_class, class_label, class_note = _CLASS_MAP[segment]
    inputs = copy.deepcopy(core.DEFAULT_INPUTS)
    preset = copy.deepcopy(core.PROJECT_CLASS_PRESETS[model_class])
    inputs.update({key: value for key, value in preset.items() if key != "label"})
    inputs.update({
        "project_class": model_class,
        "apartment_price_th": start_price / 1000.0,
        "purchase_price_mln": 0.0,
        "land_rights_cost_mln": 0.0,
        "vri_required": False,
        "vri_security_cost_mln": 0.0,
        # Всё, что относится к площадке, обнуляется здесь и заполняется ниже
        # из объёмов города: оставленное умолчание пресета — это чужие метры,
        # выданные за посчитанные.
        "social_mode": "Строительство",
        "social_compensation_mln": 0.0,
        "kindergarten_places": 0.0,
        "school_places": 0.0,
        "clinic_capacity": 0.0,
        "social_dou_gba_sqm": 0.0,
        "social_school_gba_sqm": 0.0,
        "social_clinic_gba_sqm": 0.0,
        "offices_enabled": False,
        "offices_gba_sqm": 0.0,
        "offices_saleable_sqm": 0.0,
        "retail_enabled": False,
        "retail_gba_sqm": 0.0,
        "retail_saleable_sqm": 0.0,
        "above_parking_enabled": False,
    })
    # Площадка КРТ — другой участок, и всё, что относится к участку, обязано
    # обнулиться: список этих полей один, его держит страница
    # (`TERRITORY_INPUT_KEYS`), и читается он оттуда же, откуда его читает
    # перенос ГлавАПУ. Прежде модель собиралась от умолчаний целиком, и в
    # DevelopAid приезжал чужой участок — с офисами 10 000 м² и площадью
    # прошлого проекта («в девелоп он передаёт какой-то другой участок и явно
    # не 14 га», владелец, 02.09.2026). Площадь территории — из каталога.
    for key in _territory_keys(core):
        if key in inputs:
            inputs[key] = 0.0 if not isinstance(inputs[key], bool) else False
    area_ha = _number(project.get("area_ha"))
    if area_ha > 0:
        inputs["site_area_ha"] = area_ha
        total_gfa = _number(project.get("total_gfa_sqm"))
        if total_gfa > 0:
            inputs["site_density_sqm_per_ha"] = round(total_gfa / area_ha, 1)
    duties = _requirements_for_model(requirements)
    duties["nonhousing_gfa_sqm"] = (
        _number(project.get("nonresidential_gfa_sqm"))
        + _number(project.get("business_gfa_sqm"))
    )
    if duties["demolition_area_sqm"] > 0:
        # Проект решения даёт площадь сносимых объектов, но не цену работ.
        # Площадь доезжает в штатное поле DevelopAid; нулевая стоимость не
        # маскируется допущением — ниже такой прогон лишается зелёного статуса.
        inputs["demolition_area_sqm"] = duties["demolition_area_sqm"]

    tep = _empty_tep(core)
    applied_ratios, ratio_warnings = core.tep_ratios_applied(tep_ratios)
    apartment_ratios = applied_ratios["apartments"]
    own_ratios = not core.tep_ratios_changed(tep_ratios)
    saleable = housing_gfa * _number(apartment_ratios.get("saleable_of_gns"))
    total_area = housing_gfa * _number(apartment_ratios.get("total_of_gns"))
    verdict = _verdict(market_report)
    # Средняя квартира объявлена в движке с ОСНОВАНИЕМ: площадку КРТ мы
    # собираем сами, значит делитель ручной сборки — 60 м² (решение владельца,
    # 03.09.2026). Прежде здесь стоял средний ПРОДАННЫЙ лот соседей — на живом
    # примере 36 м², и на 136 818 м² квартир это давало 3 800 лотов против
    # 2 280. Средний лот соседей остаётся наблюдением рынка и печатается
    # предпосылкой, но мерой нашего проекта не становится: чужая нарезка — это
    # чужой продукт, а не наш.
    lot_area, lot_basis = core.average_flat_sqm("manual")
    neighbour_lot = _number(verdict.get("sold_lot_avg"))
    # Метры Программы реновации СТРОЯТСЯ, но не продаются: это часть цены входа,
    # уплаченная метрами (владелец, 03.09.2026: «это по сути часть стоимости
    # входа в проект метрами»). Фонд реновации КРТ не торгует — он оператор КРТ
    # и проводит конкурсы на подрядные работы, а не выкупает у инвестора метры:
    # «Донские улицы», 136 910 м² каталога, ушли подрядчику за 14 млрд ₽, то
    # есть по 102 тыс ₽/м² — это цена СТРОЙКИ, а не цена метра. Значит выручки
    # за эти метры нет ни по рынку, ни по выкупу.
    #
    # ГНС и общая остаются полными — метры строят, и CAPEX за них платят; из
    # продаваемой они вычитаются. То же правило, что у переданных
    # муниципалитету метров: строятся, но не продаются.
    renovation = duties.get("renovation") or {}
    renovation_spp = min(_number(renovation.get("area_sqm")), housing_gfa)
    renovation_share = renovation_spp / housing_gfa if housing_gfa > 0 else 0.0
    saleable_market = saleable * (1 - renovation_share)
    tep["apartments"].update({
        "gns": housing_gfa,
        "total_area": total_area,
        "useful": saleable,
        "saleable": saleable_market,
        # Переданное городу едет тем же полем, каким уже едут метры
        # муниципалитету: второй механизм на одно явление однажды разошёлся бы
        # с первым, и обе строки выглядели бы верными.
        "transfer": saleable - saleable_market,
        "units": saleable_market / lot_area,
    })

    # Нежилой объём города и соцобъекты — до паркинга: места считаются от жилья,
    # но продукты очереди и ТЭП должны быть собраны целиком до прогона модели.
    # Население и нормативы считаются от ВСЕХ квартир, включая реновационные:
    # в них живут люди, и места в саду, школе и паркинге им положены так же.
    # Не продаётся — не значит не заселяется.
    programme = _programme(core, project, duties, inputs, tep, applied_ratios, saleable)

    # Места считает постановление, а не своя строка модуля (решение владельца,
    # 03.09.2026: «машиноместа конечно он должен считать по постановлениям»).
    # Здесь жила третья копия формулы — `ГНС жилья / 100`, то есть прежний
    # порядок 945-ПП и чужая база: 2118-ПП считает от ПЛОЩАДИ КВАРТИР, а не от
    # наземной площади зданий, и К1 в постоянных местах больше нет. На 136 818 м²
    # квартир разница — 1 580 мест по норме против 2 100 по старой строке.
    # Формула объявлена в движке один раз; копий у неё быть не должно.
    permanent = core.moscow_permanent_parking_2118(saleable)
    parking_spaces = permanent + math.ceil(permanent * PARKING_GUEST_SHARE)
    parking_gns = parking_spaces * UNDERGROUND_AREA_PER_SPACE
    tep["underground_parking"].update({
        "gns": parking_gns,
        "total_area": parking_gns,
        "units": parking_spaces,
    })
    inputs["underground_manual_spaces"] = parking_spaces
    inputs["underground_manual_gns_sqm"] = parking_gns
    inputs["underground_parking_disabled"] = False

    phasing = _phase_configuration(saleable, int(_number(inputs.get("construction_months")) or 24))
    units_total = saleable_market / lot_area
    observed_pace = _number(verdict.get("units_per_month"))
    absorption: dict[str, Any] = {"available": False}
    if observed_pace > 0:
        units_per_phase = units_total / phasing["phase_count"]
        construction_months = int(_number(inputs.get("construction_months")) or 24)
        sold_before_rve = min(units_per_phase, observed_pace * construction_months)
        share_before_rve = sold_before_rve / units_per_phase * 100 if units_per_phase else 100.0
        residual_months = math.ceil(max(0.0, units_per_phase - sold_before_rve) / observed_pace)
        inputs["share_before_rve_pct"] = share_before_rve
        inputs["residual_sales_months"] = residual_months
        absorption = {
            "available": True,
            "market_units_per_month": round(observed_pace, 1),
            "estimated_units_per_phase": round(units_per_phase),
            "sellout_months_per_phase": math.ceil(units_per_phase / observed_pace),
            "share_before_rve_pct": round(share_before_rve, 1),
            "residual_sales_months": residual_months,
            "basis": "Медианный темп ДДУ рекомендованного класса принят на одну очередь.",
        }
    bundle = core._run_authoritative_model(inputs, tep, [], phasing)
    consolidated = bundle["consolidated"]
    metrics = _snapshot(core, consolidated)
    phases = _phase_rows(bundle)
    project_llcr = _number(metrics.get("llcr_x"))
    weakest_llcr = min((row["llcr_x"] for row in phases), default=project_llcr)
    # Светофор судит проект целиком: слабейшая очередь — диагноз, а не приговор.
    # Она обслуживается кассой соседних очередей, и по ней одной хорошая
    # площадка выглядит пограничной (решение владельца, 23.08.2026).
    traffic = _traffic_light(project_llcr, _number(metrics.get("net_profit_mln")))
    known_unpriced = bool(
        duties["demolition_area_sqm"] > 0
        or duties["conditional_objects"]
        or duties["resettlement"]
        or duties["unmodelled_construction"]
        or duties["nonhousing_gfa_sqm"] > 0
    )
    if known_unpriced and traffic["tone"] == "ok":
        traffic = {
            "tone": "warn",
            "label": "Проходит до неоценённых обязательств",
            "score": 55,
        }
    entry_capacity = _goal_seek_entry_capacity(core, inputs, tep, phasing, bundle)
    capped_at_five = (
        phasing["phase_count"] == MAX_PHASES
        and saleable > TARGET_PHASE_SALEABLE_SQM * MAX_PHASES
    )

    queue_text = (
        f"объём автоматически разделён на {phasing['phase_count']} "
        f"{_queue_word(phasing['phase_count'])}"
        if phasing["enabled"] else "объём помещается в одну очередь"
    )
    text = (
        f"Маркетинг рекомендует класс «{segment}»; в модель поставлена стартовая цена "
        f"{_ru_number(start_price)} ₽/м². {queue_text.capitalize()}. "
        f"До цены входа и неоценённых обязательств модель даёт LLCR проекта "
        f"{project_llcr:.2f}x и маржу {metrics.get('margin_pct', 0):.1f}%"
        + (f"; слабейшая очередь — {weakest_llcr:.2f}x." if len(phases) > 1 else ".")
    )

    assumptions = [
        f"Жилой объём krt.mos.ru {_ru_number(housing_gfa)} м² принят за ГНС; "
        f"общая площадь — {_ru_number(total_area)} м² "
        f"({_number(apartment_ratios.get('total_of_gns')) * 100:.0f}% ГНС), "
        f"продаваемая — {_ru_number(saleable)} м² "
        f"({_number(apartment_ratios.get('saleable_of_gns')) * 100:.1f}% ГНС). "
        + ("Доли — умолчание DevelopAid; правятся в карточке."
           if own_ratios else "Доли заданы вручную, а не нашей методикой."),
        f"Стартовая цена {_ru_number(start_price)} ₽/м² взята из маркетинга: {price_basis}.",
        f"Себестоимость основного строительства взята из пресета «{class_label}»: "
        f"{_ru_number(preset.get('main_above_th_per_sqm'))} тыс. ₽/м² наземной и "
        f"{_ru_number(preset.get('main_under_th_per_sqm'))} тыс. ₽/м² подземной части.",
        f"Квартирография: средний продаваемый лот {_ru_number(lot_area, 1)} м²; расчётно {_ru_number(saleable / lot_area)} квартир.",
        f"Паркинг рассчитан по методике импорта DevelopAid: {_ru_number(parking_spaces)} мест по {_ru_number(UNDERGROUND_AREA_PER_SPACE)} м² ГНС; "
        f"цена места — {_ru_number(_number(preset.get('parking_price_th')) / 1000, 1)} млн ₽ из классового пресета.",
        "Рост цены принят по базовым вводным модели: 1,5% в месяц до РВЭ и 0,25% после РВЭ; "
        "для очередей дополнительно применены 8% в год к затратам и их стартовой цене.",
    ]
    social_text = "; ".join(
        f"{row['label']} — {_ru_number(row['places'])} "
        + ("пос./смену" if row["kind"] == "clinic" else "мест")
        + f", {_ru_number(row['gba_sqm'])} м² по "
        + (f"{_ru_number(row['norm_sqm_per_place'], 0)} м²/место"
           + (" норматива города для этой ёмкости" if row["norm_is_the_citys"] else " вводных модели")
           + ", ")
        + {
            "decision": "мощность по решению города",
            "norm_after_named": "мощность по нормативу: объект в решении назван, число мест нет",
            "norm": "мощность по нормативу",
        }[row["source"]]
        for row in programme["social"] if row["places"] > 0
    )
    assumptions.append(
        f"Население {_ru_number(programme['population'])} чел. по 33 м² квартир; норматив "
        + ("второй" if programme["city"]["zone_two"] else "первой")
        + " зоны Москвы"
        + (f" по району «{programme['city']['district']}»"
           if programme["city"]["district"] else " — район в карточке не назван, принята первая зона")
        + ". " + (social_text + "." if social_text else "Соцобъекты по нормативу не потребовались.")
    )
    assumptions.append(
        f"Нежилой объём города {_ru_number(programme['city']['nonresidential_gfa_sqm'])} м² "
        f"за вычетом соцобъектов {_ru_number(programme['social_gba_sqm'])} м² дал "
        f"{_ru_number(programme['commercial_gba_sqm'])} м² ГНС на ОСЗ и ТЦ; "
        f"общественно-деловое назначение {_ru_number(programme['offices_gba_sqm'])} м² "
        "принято офисами. Размещение объектов по очередям — умолчание модели."
    )
    if renovation_spp > 0:
        assumptions.append(
            f"Программа реновации — {_ru_number(renovation_spp)} м² СПП "
            f"({renovation_share * 100:.1f}% жилья площадки): метры строятся и передаются "
            f"городу, выручки не несут. Это часть ЦЕНЫ ВХОДА, уплаченная метрами, "
            f"а не убыток: Фонд реновации КРТ не торгует — он оператор КРТ и проводит "
            f"конкурсы на подрядные работы, а не выкупает у инвестора метры. "
            f"Продаваемая по рынку — {_ru_number(saleable_market)} м² из "
            f"{_ru_number(saleable)} м² построенных."
            + (" Всё жильё площадки — Программа реновации: девелоперского продукта "
               "здесь нет вовсе, войти можно подрядчиком."
               if renovation_share >= 0.99 else "")
        )
    elif (renovation or {}).get("mentioned"):
        assumptions.append(
            "Программа реновации в решении названа, но объём не указан: метры "
            "продаются по рынку целиком, потому что вычесть нечего. «Доля "
            "неизвестна» — это не «доли нет»."
        )
    assumptions.append(
        f"Число квартир — {_ru_number(saleable_market / lot_area)} лотов по средней квартире "
        f"{lot_area:g} м²: {lot_basis}."
        + (f" У соседей средний проданный лот {_ru_number(neighbour_lot, 1)} м² — "
           "это наблюдение рынка, а не мера нашей нарезки."
           if neighbour_lot > 0 else "")
    )
    if absorption["available"]:
        assumptions.append(
            f"Темп рынка {_ru_number(absorption['market_units_per_month'], 1)} ДДУ/мес. принят на одну очередь: "
            f"{_ru_number(absorption['share_before_rve_pct'], 1)}% продаж до РВЭ и "
            f"{absorption['residual_sales_months']} мес. остаточных продаж."
        )
    else:
        assumptions.append(
            "Темп ДДУ в маркетинге не определён; график продаж оставлен по базовым вводным DevelopAid."
        )
    if capped_at_five:
        assumptions.append(
            "Объём превышает пять очередей по целевым 70 000 продаваемых м²; "
            "скрининг упёрся в штатный предел модели, поэтому средняя очередь крупнее цели."
        )
    exclusions = [
        "Цена приобретения / входа принята равной нулю.",
        "Плата за ВРИ и оформление земельных правоотношений не включены.",
    ]
    if programme["commercial_gba_sqm"] > 0 or programme["offices_gba_sqm"] > 0:
        objects = " и ".join(filter(None, (
            "ОСЗ" if programme["commercial_gba_sqm"] > 0 else "",
            "офисов" if programme["offices_gba_sqm"] > 0 else "",
        )))
        exclusions.append(
            f"Цена и себестоимость {objects} взяты базовыми вводными модели "
            f"({_ru_number(inputs.get('retail_price_th_per_sqm'))} тыс. ₽/м² продажи и "
            f"{_ru_number(inputs.get('retail_cost_th_per_sqm'))} тыс. ₽/м² ГНС): "
            "маркетинг нежилого не считался, класс продукта не подтверждён."
        )
    if programme["commercial_negative"]:
        exclusions.append(
            f"Соцобъекты {_ru_number(programme['social_gba_sqm'])} м² "
            + ("(по решению города и нормативу) " if programme["social_from_decision"]
               else "(по нормативу) ")
            + "больше всего нежилого объёма города "
            f"{_ru_number(programme['city']['nonresidential_gfa_sqm'])} м² на "
            f"{_ru_number(abs(programme['commercial_gba_sqm']))} м²: остатка на ОСЗ и ТЦ нет, "
            "и обнулять его молча нельзя — либо соцобъекты у города учтены вне нежилого "
            "назначения, либо норматив к этой площадке не применяется целиком."
        )
    if not programme["balance"]["total_published"]:
        exclusions.append(
            "Общий объём застройки в карточке города не опубликован: сходимость "
            "«жилое + нежилое + деловое = всего» проверить не на чем."
        )
    elif not programme["balance"]["matches"]:
        exclusions.append(
            "Слагаемые карточки города не сходятся с её же общим объёмом: "
            f"{_ru_number(programme['balance']['declared_sum_sqm'])} м² против "
            f"{_ru_number(programme['city']['total_gfa_sqm'])} м², разница "
            f"{_ru_number(programme['balance']['difference_sqm'])} м². В модель взяты слагаемые."
        )
    if duties["demolition_area_sqm"] > 0:
        exclusions.append(
            f"Проект решения требует безусловный снос {_ru_number(duties['demolition_area_sqm'], 1)} м²: "
            "площадь передана в DevelopAid, но стоимость сноса не опубликована и пока не включена в CAPEX."
        )
    if duties["conditional_objects"]:
        detail = (
            f" общей площадью {_ru_number(duties['conditional_area_sqm'], 1)} м²"
            if duties["conditional_area_sqm"] > 0 else ""
        )
        exclusions.append(
            f"По {duties['conditional_objects']} объектам{detail} решение допускает выбор «снос/реконструкция»; "
            "сценарий и его стоимость не определены."
        )
    if duties["resettlement"]:
        exclusions.append(
            "В проекте решения найдено расселение/изъятие, но стоимость обязательства не опубликована."
        )
    if duties["unmodelled_construction"]:
        exclusions.append(
            "Опубликованные дополнительные обязательства по строительству прочитаны и переданы в отчёт, "
            "но не включены в CAPEX без подтверждённых площадей/мощностей и продукта."
        )
    if not duties["available"]:
        exclusions.append(
            "Проект решения с обязательствами не прочитан; до углублённой оценки зелёный вывод считать предварительным."
        )
    if class_note:
        assumptions.append(class_note + ".")

    return {
        "available": True,
        "preliminary": True,
        "traffic_light": traffic,
        # Доли едут вместе с результатом: по ним видно, чем посчитано, и на них
        # же держится решение не сохранять чужой расчёт в общий рейтинг.
        "tep_ratios": {
            "apartments": {
                "total_of_gns": round(_number(apartment_ratios.get("total_of_gns")), 6),
                "saleable_of_gns": round(_number(apartment_ratios.get("saleable_of_gns")), 6),
                "source": apartment_ratios.get("source") or "",
            },
            "custom": not own_ratios,
            "raw": str(tep_ratios or ""),
            "warnings": ratio_warnings,
        },
        # Вводные, которыми это посчитано, едут вместе с результатом. Без них
        # «передать в DevelopAid» пришлось бы собирать модель второй раз — а
        # два сборщика на одну площадку однажды разойдутся, и обе страницы
        # будут показывать разное про один и тот же проект.
        "model_inputs": {
            "inputs": copy.deepcopy(inputs),
            "tep": copy.deepcopy(tep),
            "phasing": copy.deepcopy(phasing),
        },
        "requirements": duties,
        # Признак реновации едет ЧИСЛОМ, а не пересказом: метка на строке и
        # предпосылка в отчёте обязаны считаться одним и тем же, иначе они
        # однажды скажут про одну площадку разное.
        "renovation": {
            "spp_sqm": round(renovation_spp),
            "share": round(renovation_share, 4),
            "saleable_lost_sqm": round(saleable - saleable_market),
            "whole_site": renovation_share >= 0.99,
            "mentioned": bool((renovation or {}).get("mentioned")),
            "quote": str((renovation or {}).get("quote") or ""),
        },
        "programme": programme,
        "headline": traffic["label"],
        "text": text,
        "market": {
            "recommended_segment": segment,
            "model_class": model_class,
            "model_class_label": class_label,
            "start_price_rub_sqm": round(start_price),
            "market_price_rub_sqm": round(market_price) if market_price > 0 else None,
            "price_basis": price_basis,
        },
        "phasing": {
            "automatic": True,
            "count": phasing["phase_count"],
            "target_saleable_sqm": TARGET_PHASE_SALEABLE_SQM,
            "gap_months": PHASE_GAP_MONTHS,
            "saleable_sqm": round(saleable_market),
            "average_saleable_sqm": round(saleable_market / phasing["phase_count"]),
            "capped_at_five": capped_at_five,
            "phases": phases,
        },
        "absorption": absorption,
        "metrics": {
            **metrics,
            "project_llcr_x": round(project_llcr, 3),
            "weakest_phase_llcr_x": round(weakest_llcr, 3),
        },
        "entry_capacity": entry_capacity,
        "assumptions": assumptions,
        "exclusions": exclusions,
        "criterion": (
            "Светофор модели проверяет положительную прибыль и LLCR проекта целиком; "
            "целевой ориентир DevelopAid — 1,20x. Это фильтр для углублённой проверки, не решение о покупке."
        ),
    }
