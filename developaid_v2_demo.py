"""Демонстрационные вводные контрольных проектов 2.0 — только вводные.

Здесь нет ни одного посчитанного показателя: модуль собирает **вводные**
(inputs / ТЭП / очереди) двух контрольных проектов и отдаёт их движку.
Числа, которые увидит интерфейс, считает движок при каждом запросе.

Откуда берутся вводные:

- ТЭП и плата за ВРИ — из серверных предустановок `presets/*.xlsx` разбором
  движка (`parse_glavapu_xlsx`) и его же картой `mappings`. Ровно так же
  предустановку применяет Telegram-поток: `inputs = mappings["inputs"]`,
  `tep = mappings["tep"]`. Собственного разбора здесь нет;
- конфигурация проекта (округ, офисы, очереди 40/32/28, рабочая социалка) —
  та же, что применяет мини-приложение в `applyServerPresetProjectConfig`.
  Это настройка сценария, а не экономика: цены, себестоимость, сроки и
  ставки остаются умолчаниями движка;
- всё остальное — `DEFAULT_INPUTS` и `TEP_DEFAULT` движка.

Поэтому показатели демонстрационных проектов совпадают с расчётом движка на
этих вводных, а не с контрольными PDF: часть вводных приёмочных расчётов
(цена входа, цены продаж, себестоимость) жила в состоянии страницы и в
репозитории её нет. Подгонять числа под отчёт нельзя — это вернуло бы второй
источник экономики, ради устранения которого /v2 и переводится на движок.
"""

from __future__ import annotations

import copy
from typing import Any

# Сценарии демонстрации. Значения — конфигурация проекта из предустановки
# мини-приложения, не результаты расчёта.
DEMO_SCENARIOS: dict[str, dict[str, Any]] = {
    "mishina": {
        "slug": "mishina",
        "preset_id": "mishina",
        "name": "Мишина",
        "region": "Москва",
        "subtitle": "Компактный городской проект · предустановка ГлавАПУ",
        "cadastral_numbers": ["77:09:0004014:13"],
        "source_label": "Предустановка «Мишина» · ТЭП ГлавАПУ",
        # Предустановка «Мишина» одноочередная и без отдельных объектов КРТ —
        # ровно то, что делает `applyServerPresetProjectConfig('mishina')`.
        "inputs": {
            "vri_region": "msk",
            "technical_supervision_pct": 5,
            "offices_enabled": False,
            "offices_gba_sqm": 0,
            "offices_saleable_sqm": 0,
            "retail_enabled": False,
            "retail_gba_sqm": 0,
            "retail_saleable_sqm": 0,
            "above_parking_enabled": False,
            "above_parking_spaces": 0,
        },
        "phasing": {},
    },
    "mytishchi": {
        "slug": "mytishchi",
        "preset_id": "mytishchi",
        "name": "Мытищи",
        "region": "Московская область",
        "subtitle": "22 участка · 3 очереди · офисы в О3",
        "cadastral_numbers": [],
        "source_label": "Предустановка «Мытищи» · ТЭП ГлавАПУ",
        # Округ решает Кср и Кд платы за ВРИ: без него расчёт берёт среднее по
        # области. Социалка — рабочая программа предустановки, стройкой.
        "inputs": {
            "vri_region": "mo",
            "mo_district": "Городской округ Мытищи",
            "technical_supervision_pct": 5,
            "social_mode": "Строительство",
        },
        # Три очереди 40/32/28 с шагом 12 месяцев — конфигурация предустановки.
        "phasing": {
            "enabled": True,
            "user_enabled": False,
            "source": "preset_mytishchi",
            "phase_count": 3,
            "phase_gap_months": 12,
            "cost_inflation_pct": 8,
            "sales_price_inflation_pct": 8,
            "products": {
                "apartments": [40, 32, 28],
                "ground_commercial": [40, 32, 28],
                "underground_parking": [40, 32, 28],
                "storage": [40, 32, 28],
            },
        },
    },
}


def list_scenarios() -> list[dict[str, Any]]:
    """Каталог демонстрационных проектов: только описание, без цифр."""
    return [
        {
            "slug": item["slug"],
            "name": item["name"],
            "region": item["region"],
            "subtitle": item["subtitle"],
            "demo": True,
        }
        for item in DEMO_SCENARIOS.values()
    ]


def scenario_payload(core: Any, slug: str) -> dict[str, Any]:
    """Вводные демонстрационного проекта в формате запроса мини-приложения.

    `core` — модуль движка (`main.core`): разбор предустановки, умолчания и
    карта соответствий берутся у него, своих здесь нет.
    """
    scenario = DEMO_SCENARIOS.get(slug)
    if scenario is None:
        raise KeyError(slug)

    meta = core.SERVER_TEP_PRESETS[scenario["preset_id"]]
    path = core.PRESET_DIR / meta["filename"]
    parsed = core.parse_glavapu_xlsx(path.read_bytes(), meta["filename"])
    mappings = parsed.get("mappings") or {}
    normalized = parsed.get("normalized") or {}

    inputs: dict[str, Any] = copy.deepcopy(core.DEFAULT_INPUTS)
    inputs.update(mappings.get("inputs") or {})
    inputs["site_area_ha"] = normalized.get("site_area_ha") or 0
    suggested = normalized.get("suggested_social_mode")
    if suggested:
        inputs["social_mode"] = suggested
    inputs.update(scenario.get("inputs") or {})
    # Импорт ГлавАПУ едет с вводными: без него движок не увидит ни требуемого
    # паркинга, ни нормативной социальной потребности.
    inputs["_glavapu_import"] = {
        "source": {**(parsed.get("source") or {}),
                   "preset_id": scenario["preset_id"],
                   "preset_name": meta["name"],
                   "server_preset": True},
        "normalized": normalized,
        "recognized": parsed.get("recognized") or [],
        "warnings": parsed.get("warnings") or [],
        "mappings": mappings,
    }

    tep: dict[str, Any] = copy.deepcopy(core.TEP_DEFAULT)
    for key, row in (mappings.get("tep") or {}).items():
        tep[key] = {**(tep.get(key) or {}), **row}

    return {
        "inputs": inputs,
        "tep": tep,
        "rates": [],
        "phasing": copy.deepcopy(scenario.get("phasing") or {}),
        "project_name": scenario["name"],
        "region": scenario["region"],
        "cadastral_numbers": list(scenario.get("cadastral_numbers") or []),
        "source_label": scenario["source_label"],
        "scenario": "base",
    }
