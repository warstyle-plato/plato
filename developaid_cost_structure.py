from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
REFERENCE_DIR = ROOT / "reference_data" / "statistics"
STRUCTURE_PATH = REFERENCE_DIR / "developaid_cost_structure.json"
CLASS_ADJUSTMENTS_PATH = REFERENCE_DIR / "class_adjustments.json"

UNIT_LABELS = {
    "gba": "₽/м² общей ГНС",
    "above_ground": "₽/м² наземной ГНС",
    "apartments": "₽/м² общей площади квартир",
    "building_total": "₽/м² общей площади здания",
    "sellable": "₽/м² продаваемой площади",
    "underground": "₽/м² подземной ГНС",
}

CLASS_LABELS = {
    "standard": "Стандарт",
    "comfort": "Комфорт",
    "business": "Бизнес",
    "premium": "Премиум",
    "elite": "Элитный",
    "mass_market": "Массовый / комфорт",
    "unknown": "Без класса",
}

STATUS_LABELS = {
    "value": "значение",
    "source_aggregate": "агрегат источника",
    "included_in_aggregate": "входит в агрегат",
    "included_in_broader_total": "входит в более широкий итог",
    "included_residual": "входит в нераскрытый остаток",
    "not_disclosed": "н/д",
    "outside_scope": "вне scope",
    "separate_denominator": "отдельная база площади",
    "share": "доля",
    "share_range": "диапазон доли",
    "combined_share": "совместная доля",
    "unallocated_remainder": "нераспределённый остаток",
}


def _load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def load_cost_structure() -> dict[str, Any]:
    data = _load_json(STRUCTURE_PATH)
    # Correct a bad intermediate-workbook denominator that was accidentally
    # curated as a source fact. The underlying Grodnenskaya FM has about
    # 762m RUB of underground cost over 3,629 m² underground GNS: ~210k/m².
    for source in data.get("sources", []):
        if source.get("source_id") != "developaid-grodnenskaya-structure-2026-07":
            continue
        cell = source.get("components", {}).get("main_under")
        if cell:
            cell["value_rub_m2"] = 210000.0
            cell["unit"] = "underground"
            cell["note"] = "По исходной ФМ: ~762 млн ₽ / 3 629 м² подземной ГНС ≈ 210 тыс. ₽/м²."
    return data


def load_class_adjustments() -> dict[str, Any]:
    return _load_json(CLASS_ADJUSTMENTS_PATH)


def _ratio(mapping: dict[str, float], source_class: str, target_class: str) -> float | None:
    source = mapping.get(source_class)
    target = mapping.get(target_class)
    if source in (None, 0) or target is None:
        return None
    return float(target) / float(source)


def _component_ratio(component: str, source_class: str, target_class: str, cfg: dict[str, Any]) -> float | None:
    return _ratio(cfg.get("components", {}).get(component, {}), source_class, target_class)


def _scope_ratio(scope: str | None, source_class: str, target_class: str, cfg: dict[str, Any]) -> float | None:
    if not scope:
        return None
    return _ratio(cfg.get("scope_coefficients", {}).get(scope, {}), source_class, target_class)


def _round_money(value: float | None) -> float | None:
    return None if value is None else round(float(value), 2)


def _apply_range_adjustment(result: dict[str, Any], ratio: float) -> None:
    for key in ("value_low_rub_m2", "value_high_rub_m2"):
        value = result.get(key)
        if value is not None:
            result[f"source_{key}"] = _round_money(value)
            result[f"adjusted_{key}"] = _round_money(float(value) * ratio)


def _decorate_cell(component: str, cell: dict[str, Any], source_class: str, target_class: str, cfg: dict[str, Any]) -> dict[str, Any]:
    result = deepcopy(cell)
    result["status_label"] = STATUS_LABELS.get(result.get("status"), result.get("status", ""))
    unit = result.get("unit")
    if unit:
        result["unit_label"] = UNIT_LABELS.get(unit, unit)

    value = result.get("value_rub_m2")
    if value is not None and result.get("status") == "value":
        ratio = _component_ratio(component, source_class, target_class, cfg)
        if ratio is not None:
            result["source_value_rub_m2"] = _round_money(value)
            result["class_adjustment_ratio"] = round(ratio, 4)
            result["adjusted_value_rub_m2"] = _round_money(float(value) * ratio)
            _apply_range_adjustment(result, ratio)
            result["class_adjusted"] = source_class != target_class
            result["adjustment_method"] = "expert_component_ratio"

    if result.get("status") == "source_aggregate" and value is not None:
        ratio = _scope_ratio(result.get("scope"), source_class, target_class, cfg)
        if ratio is not None:
            result["source_value_rub_m2"] = _round_money(value)
            result["class_adjustment_ratio"] = round(ratio, 4)
            result["adjusted_value_rub_m2"] = _round_money(float(value) * ratio)
            _apply_range_adjustment(result, ratio)
            result["class_adjusted"] = source_class != target_class
            result["adjustment_method"] = "expert_scope_ratio"
    return result


def build_cost_structure_matrix(region: str = "Москва", housing_class: str = "business") -> dict[str, Any]:
    structure = load_cost_structure()
    cfg = load_class_adjustments()
    target_class = housing_class if housing_class in cfg.get("classes", []) else cfg.get("base_class", "comfort")

    components = structure.get("components", [])
    sources: list[dict[str, Any]] = []
    for raw in structure.get("sources", []):
        if raw.get("region") != region:
            continue
        source = deepcopy(raw)
        source_class = source.get("base_class") or cfg.get("base_class", "comfort")
        source["base_class_label"] = CLASS_LABELS.get(source_class, source_class)
        source["target_class"] = target_class
        source["target_class_label"] = CLASS_LABELS.get(target_class, target_class)
        source["published_unit_label"] = UNIT_LABELS.get(source.get("published", {}).get("unit"), source.get("published", {}).get("unit"))

        published = source.get("published", {})
        published_value = published.get("value_rub_m2")
        published_scope = published.get("scope")
        scope_ratio = _scope_ratio(published_scope, source_class, target_class, cfg)
        if published_value is not None and scope_ratio is not None:
            source["published_adjusted_value_rub_m2"] = _round_money(float(published_value) * scope_ratio)
            source["published_adjustment_ratio"] = round(scope_ratio, 4)
            source["published_class_adjusted"] = source_class != target_class
        else:
            source["published_adjusted_value_rub_m2"] = _round_money(published_value)
            source["published_adjustment_ratio"] = 1.0
            source["published_class_adjusted"] = False

        cells: dict[str, Any] = {}
        for component in components:
            key = component["key"]
            raw_cell = source.get("components", {}).get(key, {"status": "not_disclosed"})
            cells[key] = _decorate_cell(key, raw_cell, source_class, target_class, cfg)
        source["cells"] = cells
        source.pop("components", None)
        sources.append(source)

    return {
        "methodology_version": structure.get("methodology_version", "3.1"),
        "region": region,
        "housing_class": target_class,
        "housing_class_label": CLASS_LABELS.get(target_class, target_class),
        "canonical_unit": structure.get("canonical_unit", "gba"),
        "canonical_unit_label": structure.get("canonical_unit_label", UNIT_LABELS["gba"]),
        "components": components,
        "sources": sources,
        "class_adjustments": {
            "status": cfg.get("status"),
            "base_class": cfg.get("base_class"),
            "base_class_label": CLASS_LABELS.get(cfg.get("base_class", "comfort"), cfg.get("base_class")),
            "description": cfg.get("description"),
            "components": cfg.get("components", {}),
            "scope_coefficients": cfg.get("scope_coefficients", {}),
            "rules": cfg.get("rules", []),
        },
        "rules": [
            "Строки таблицы — статьи методики DevelopAid; терминология внешнего источника не меняет структуру модели.",
            "Наземное и подземное СМР имеют собственные знаменатели площади; общепроектные статьи — общую ГНС.",
            "Значения с разными знаменателями площади конвертируются только при наличии ТЭП целевого проекта.",
            "Пустая статья означает отсутствие раскрытия, а не нулевую стоимость.",
            "Экспертный коэффициент класса показан отдельно от опубликованного значения и не маскируется под статистику.",
        ],
    }


def class_adjustment_catalog() -> dict[str, Any]:
    cfg = load_class_adjustments()
    return {
        "methodology_version": cfg.get("methodology_version", "3.0"),
        "status": cfg.get("status", "expert_provisional"),
        "base_class": cfg.get("base_class", "comfort"),
        "base_class_label": CLASS_LABELS.get(cfg.get("base_class", "comfort"), cfg.get("base_class")),
        "classes": [{"key": key, "label": CLASS_LABELS.get(key, key)} for key in cfg.get("classes", [])],
        "components": cfg.get("components", {}),
        "scope_coefficients": cfg.get("scope_coefficients", {}),
        "rules": cfg.get("rules", []),
    }
