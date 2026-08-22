"""Описание формы вводных /v2 — из справочников движка, без своей копии.

Блоки, подписи, единицы и типы полей берутся из `FIELD_GROUPS` — того же
справочника, которым рисуется действующая страница и который читает
`_field_meta()` для анализа чувствительности. Умолчания — `DEFAULT_INPUTS`,
`TEP_DEFAULT` и `TEP_RATIOS`. Своего словаря методики здесь нет: третья копия
разъехалась бы с движком молча.

Модуль ничего не считает и ничего не проверяет по существу: он описывает,
что показать. Значения собирает страница, экономику считает движок.
"""

from __future__ import annotations

import copy
import re
from typing import Any

# Варианты двух выпадающих списков, у которых их нет в FIELD_GROUPS: режим
# соцнагрузки и проценты БРИДЖ. Копий больше нет — оба списка берутся из
# движка, оттуда же их берут страница и книга. Копия здесь была третьей, и
# третья форма соцнагрузки в неё не попала: движок считал, книга предлагала,
# а прототип 2.0 предлагал два варианта из трёх.
def select_options(core: Any, key: str) -> list[str]:
    """Варианты списка — из движка, у которого их берут страница и книга."""
    return [str(pair[0]) for pair in core._M2_EXTRA_OPTIONS[key]]


# Продукты, которые делятся между очередями. Ключи — те же, что понимает
# `calculate_phased`; подписи берутся из ТЭП движка.
PHASE_PRODUCT_KEYS = ("apartments", "ground_commercial", "underground_parking", "storage")

_TEP_ROW_HINTS = {
    "storage": (
        "Количество кладовых — самостоятельная ТЭП-вводная. Выручка считается "
        "как количество × цена кладовой; площадь кладовых сейчас в выручке не участвует."
    ),
}

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


def _field(item: list[Any], core: Any) -> dict[str, Any]:
    """Поле формы ровно так, как его описывает движок."""
    key, label, unit, kind = str(item[0]), str(item[1]), str(item[2]), str(item[3])
    options: list[dict[str, str]] = []
    if len(item) > 4 and item[4]:
        options = [{"value": str(pair[0]), "label": str(pair[1])} for pair in item[4]]
    elif kind == "select":
        # `select` без вариантов в справочнике — режим социальной нагрузки.
        options = [{"value": value, "label": value}
                   for value in select_options(core, "social_mode")]
    elif kind == "finance_select":
        options = [{"value": value, "label": value}
                   for value in select_options(core, "bridge_interest_mode")]
        kind = "select"
    return {"key": key, "label": label, "unit": unit, "type": kind, "options": options}


def _tep_block(core: Any) -> dict[str, Any]:
    """Блок ТЭП: строки продуктов движка и их собственные поля.

    Порядок строк остаётся порядком `TEP_DEFAULT`: API формы не создаёт вторую
    карту продуктов. Экран вправе переставить кладовые рядом с паркингом как
    чисто визуальное решение.

    Методические доли не копируются: строка получает их из `core.TEP_RATIOS`.
    Для кладовых показываем только количество — именно оно вместе с ценой
    формирует выручку; нулевые ГНС/общая/полезная создавали видимость, будто
    от них что-то зависит.
    """
    rows = []
    for key, row in core.TEP_DEFAULT.items():
        names = [name for name in row if name != _TEP_LABEL_FIELD]
        if key == "storage":
            names = [name for name in names if name == "units"]
        fields = [
            {"key": name,
             "label": _TEP_FIELD_LABELS.get(name, (name, ""))[0],
             "unit": _TEP_FIELD_LABELS.get(name, (name, ""))[1]}
            for name in names
        ]
        item: dict[str, Any] = {
            "key": key,
            "label": str(row.get("label") or key),
            "fields": fields,
        }
        hint = _TEP_ROW_HINTS.get(key)
        if hint:
            item["hint"] = hint
        ratios = (getattr(core, "TEP_RATIOS", {}) or {}).get(key)
        if ratios:
            total, saleable_of_total = core.tep_ratio_chain(ratios)
            item["default_ratio"] = {
                "total_pct": total * 100.0,
                "saleable_of_total_pct": saleable_of_total * 100.0,
                "source": str(ratios.get("source") or ""),
            }
        rows.append(item)
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
        "fields": [_field(list(item), core) for item in _PHASING_FIELDS],
        "products": [{"key": key, "label": labels[key]} for key in PHASE_PRODUCT_KEYS],
    }


def territory_input_keys(core: Any) -> list[str]:
    """Поля, принадлежащие участку, — списком со страницы движка.

    Страница держит его в `TERRITORY_INPUT_KEYS` и обнуляет эти поля при каждом
    импорте: они относятся к участку, а не к предпосылкам аналитика. Список
    читается оттуда, а не копируется: третья копия разъедется молча, а цена
    предыдущего проекта, оставшаяся во вводных, в глаза не бросается.
    """
    match = re.search(r"const TERRITORY_INPUT_KEYS=\[(.*?)\];", core.PAGE, re.S)
    if not match:
        raise RuntimeError("на странице движка не найден TERRITORY_INPUT_KEYS")
    return re.findall(r"'([^']+)'", match.group(1))


def inputs_from_glavapu(
    core: Any,
    parsed: dict[str, Any],
    extra_inputs: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Разбор ГлавАПУ → вводные и ТЭП проекта.

    Своего переноса здесь нет: значения берутся из карты `mappings`, которую
    строит сам разбор движка. Тем же путём предустановку применяет
    Telegram-поток — `inputs = mappings["inputs"]`, `tep = mappings["tep"]`.

    Порядок повторяет страницу: сначала обнуляется всё, что принадлежит
    участку, потом накладывается принесённое файлом. Иначе поле, которого в
    файле нет, остаётся умолчанием движка и выглядит как данные участка —
    так офисы площадью 10 000 м² появлялись у площадки, где их нет, и стоило
    включить их галочкой, как выручка вырастала на 3,7 млрд ₽.

    Всё, чего файл не касается — цены, себестоимость, сроки, — остаётся
    умолчаниями движка: додумывать экономику за участок нельзя.
    """
    mappings = parsed.get("mappings") or {}
    normalized = parsed.get("normalized") or {}

    inputs: dict[str, Any] = copy.deepcopy(core.DEFAULT_INPUTS)
    for key in territory_input_keys(core):
        if key in inputs:
            inputs[key] = 0
    # Отдельные объекты КРТ выключаются вместе с их площадями: включённым
    # объект делает файл, а не память о прошлом проекте.
    inputs["offices_enabled"] = False
    inputs["retail_enabled"] = False
    inputs["above_parking_enabled"] = False
    inputs.update(mappings.get("inputs") or {})
    inputs["site_area_ha"] = normalized.get("site_area_ha") or 0
    # Плотность приезжает тем же файлом и не должна оставаться справочной:
    # страница её обнуляет, чтобы она выводилась из площади и ТЭП участка.
    if float(normalized.get("density_spp_th_sqm_ha") or 0) > 0:
        inputs["site_density_sqm_per_ha"] = 0
    suggested = normalized.get("suggested_social_mode")
    if suggested:
        inputs["social_mode"] = suggested
    inputs.update(extra_inputs or {})
    # Импорт едет с вводными: без него движок не увидит ни требуемого
    # паркинга, ни нормативной социальной потребности.
    inputs["_glavapu_import"] = {
        "source": parsed.get("source") or {},
        "normalized": normalized,
        "recognized": parsed.get("recognized") or [],
        "warnings": parsed.get("warnings") or [],
        "mappings": mappings,
    }

    # ТЭП тоже принадлежит участку целиком: строка, которой файл не касается,
    # обязана быть нулевой, а не нести площади из умолчаний движка.
    tep: dict[str, Any] = copy.deepcopy(core.TEP_DEFAULT)
    for row in tep.values():
        for field in ("gns", "total_area", "useful", "saleable", "transfer", "units"):
            if field in row:
                row[field] = 0
    for key, row in (mappings.get("tep") or {}).items():
        tep[key] = {**(tep.get(key) or {}), **row}

    return {"inputs": inputs, "tep": tep}


def form_description(core: Any) -> dict[str, Any]:
    """Блоки формы и умолчания движка одним ответом."""
    blocks: list[dict[str, Any]] = [_tep_block(core)]
    for index, (title, fields) in enumerate(core.FIELD_GROUPS):
        blocks.append({
            "key": f"group{index}",
            "title": str(title),
            "kind": "inputs",
            "fields": [_field(list(item), core) for item in fields],
        })
    blocks.append(_phasing_block(core))
    return {
        "blocks": blocks,
        "defaults": {
            "inputs": copy.deepcopy(core.DEFAULT_INPUTS),
            "tep": copy.deepcopy(core.TEP_DEFAULT),
            "tep_ratios": copy.deepcopy(getattr(core, "TEP_RATIOS", {})),
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
