"""Описание формы вводных /v2 — из справочников движка, без своей копии.

Блоки, подписи, единицы и типы полей берутся из `FIELD_GROUPS` — того же
справочника, которым рисуется действующая страница и который читает
`_field_meta()` для анализа чувствительности. Умолчания — `DEFAULT_INPUTS` и
`TEP_DEFAULT`. Своего словаря полей здесь нет: третья копия разъехалась бы с
первыми двумя молча, а поле, которого нет в карте, остаётся мусором.

Модуль ничего не считает и ничего не проверяет по существу: он описывает,
что показать. Значения собирает страница, экономику считает движок.
"""

from __future__ import annotations

import copy
from typing import Any

# Варианты двух выпадающих списков, у которых их нет в FIELD_GROUPS: страница
# подставляет их сама (`select` без вариантов — режим социалки,
# `finance_select` — проценты БРИДЖ). Копия сверяется с PAGE тестом
# `test_the_select_options_match_the_page`; разъехаться молча она не может.
SOCIAL_MODE_OPTIONS = ["Строительство", "Денежная компенсация"]
BRIDGE_INTEREST_OPTIONS = ["Капитализация в ПФ", "Выплата при рефинансировании"]

# Продукты, которые делятся между очередями. Ключи — те же, что понимает
# `calculate_phased`; подписи берутся из ТЭП движка.
PHASE_PRODUCT_KEYS = ("apartments", "ground_commercial", "underground_parking", "storage")

# Поле ТЭП «label» — подпись строки, а не вводная: редактировать нечего.
_TEP_LABEL_FIELD = "label"

_TEP_FIELD_LABELS = {
    "gns": ("ГНС", "м²"),
    "total_area": ("Общая площадь", "м²"),
    "useful": ("Полезная", "м²"),
    "saleable": ("Продаваемая", "м²"),
    "transfer": ("Передаётся городу", "м²"),
    "units": ("Количество", "шт."),
}

_PHASING_FIELDS = [
    ("enabled", "Считать проект по очередям", "Да / Нет", "checkbox"),
    ("phase_count", "Количество очередей", "шт. (до 5)", "number"),
    ("phase_gap_months", "Лаг между очередями", "мес.", "number"),
    ("cost_inflation_pct", "Инфляция затрат по очередям", "% год", "number"),
    ("sales_price_inflation_pct", "Рост цен по очередям", "% год", "number"),
]

DEFAULT_PHASING: dict[str, Any] = {
    "enabled": False,
    "phase_count": 1,
    "phase_gap_months": 12,
    "cost_inflation_pct": 8,
    "sales_price_inflation_pct": 8,
    "products": {},
}


def _field(item: list[Any]) -> dict[str, Any]:
    """Поле формы ровно так, как его описывает движок."""
    key, label, unit, kind = str(item[0]), str(item[1]), str(item[2]), str(item[3])
    options: list[dict[str, str]] = []
    if len(item) > 4 and item[4]:
        options = [{"value": str(pair[0]), "label": str(pair[1])} for pair in item[4]]
    elif kind == "select":
        # `select` без вариантов в справочнике — режим социальной нагрузки.
        options = [{"value": value, "label": value} for value in SOCIAL_MODE_OPTIONS]
    elif kind == "finance_select":
        options = [{"value": value, "label": value} for value in BRIDGE_INTEREST_OPTIONS]
        kind = "select"
    return {"key": key, "label": label, "unit": unit, "type": kind, "options": options}


def _tep_block(core: Any) -> dict[str, Any]:
    """Блок ТЭП: строки продуктов движка и их собственные поля."""
    rows = []
    for key, row in core.TEP_DEFAULT.items():
        fields = [
            {"key": name,
             "label": _TEP_FIELD_LABELS.get(name, (name, ""))[0],
             "unit": _TEP_FIELD_LABELS.get(name, (name, ""))[1]}
            for name in row if name != _TEP_LABEL_FIELD
        ]
        rows.append({"key": key, "label": str(row.get("label") or key), "fields": fields})
    return {
        "key": "tep",
        "title": "ТЭП проекта",
        "kind": "tep",
        "hint": "Площади и количества по продуктам. Их же приносит импорт ГлавАПУ "
                "и «Поиск ТЭП» — форма нужна, когда правят руками.",
        "rows": rows,
    }


def _phasing_block(core: Any) -> dict[str, Any]:
    """Блок очередей: параметры и веса продуктов по очередям."""
    labels = {key: str((core.TEP_DEFAULT.get(key) or {}).get("label") or key)
              for key in PHASE_PRODUCT_KEYS}
    return {
        "key": "phasing",
        "title": "Очереди",
        "kind": "phasing",
        "hint": "Выключено — проект считается одной очередью. Веса задают, какая "
                "доля каждого продукта приходится на очередь; сумма приводится "
                "движком к 100%.",
        "fields": [_field(list(item)) for item in _PHASING_FIELDS],
        "products": [{"key": key, "label": labels[key]} for key in PHASE_PRODUCT_KEYS],
    }


def form_description(core: Any) -> dict[str, Any]:
    """Блоки формы и умолчания движка одним ответом."""
    blocks: list[dict[str, Any]] = [_tep_block(core)]
    for index, (title, fields) in enumerate(core.FIELD_GROUPS):
        blocks.append({
            "key": f"group{index}",
            "title": str(title),
            "kind": "inputs",
            "fields": [_field(list(item)) for item in fields],
        })
    blocks.append(_phasing_block(core))
    return {
        "blocks": blocks,
        "defaults": {
            "inputs": copy.deepcopy(core.DEFAULT_INPUTS),
            "tep": copy.deepcopy(core.TEP_DEFAULT),
            "phasing": copy.deepcopy(DEFAULT_PHASING),
        },
        "scenarios": copy.deepcopy(core.SCENARIOS),
        "project_classes": [
            {"value": key, "label": str(preset.get("label") or key)}
            for key, preset in core.PROJECT_CLASS_PRESETS.items()
        ],
        "presets": [
            {"id": key, "name": str(meta["name"]), "description": str(meta["description"])}
            for key, meta in core.SERVER_TEP_PRESETS.items()
        ],
    }
