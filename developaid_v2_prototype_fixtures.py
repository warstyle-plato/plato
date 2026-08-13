"""Контрольные fixtures прототипа /v2 — только демонстрация и тесты.

Это зашитые показатели из утверждённых PDF DevelopAid от 02.08.2026, с
которыми принималась информационная архитектура 2.0. Production их не отдаёт:
`/v2` и `/api/v2/*` считают движком. Модуль остаётся, чтобы было с чем
сверять вёрстку и чтобы приёмочные снимки не пропали, и подключается только
при `DEVELOPAID_V2_PROTOTYPE_FIXTURES=1` — маршрутом `/api/v2/prototype/...`.

Числа отсюда не являются результатом расчёта. Единственный источник
production-цифр — `developaid_v2_result.build_project_result`.
"""

from __future__ import annotations

from typing import Any

# Признак, по которому эти данные видно в любом ответе.
PROTOTYPE = True

PROTOTYPE_PROJECTS: dict[str, dict[str, Any]] = {
    "mishina": {
        "slug": "mishina",
        "name": "Мишина",
        "region": "Москва",
        "subtitle": "Компактный городской проект · ГлавАПУ",
        "status": "Требует пересмотра условий покупки",
        "statusTone": "warning",
        "source": "Контрольный PDF DevelopAid · 02.08.2026",
        "prototype": True,
        "kpi": {
            "revenue": 12.74,
            "costs": 11.44,
            "ebitda": 2.91,
            "netProfit": 1.30,
            "margin": 10.2,
            "llcr": 1.12,
            "bridgeCalc": 0.83,
            "bridgePeak": 2.17,
            "pfPeak": 2.17,
            "interest": 1.18,
        },
        "tep": {
            "gns": 25967,
            "saleable": 15150,
            "apartments": 13920,
            "commercial": 1230,
            "parking": 91,
            "kindergarten": 19,
            "school": 38,
            "clinic": 9,
            "vri": 1.27,
        },
        "products": [
            {"name": "Квартиры", "value": 11.19, "share": 87.8},
            {"name": "Коммерция", "value": 0.99, "share": 7.8},
            {"name": "Паркинг", "value": 0.56, "share": 4.4},
        ],
        "costStructure": [
            {"name": "Строительство", "value": 5.70},
            {"name": "ВРИ / земельные права", "value": 1.27},
            {"name": "Проценты и комиссии", "value": 1.18},
            {"name": "Маркетинг и продажи", "value": 0.89},
            {"name": "Цена приобретения", "value": 0.70},
        ],
        "cashflow": [-0.70, -1.15, -0.86, -0.20, 0.72, 1.38, 1.30],
        "debt": [0.70, 0.83, 2.17, 1.94, 1.31, 0.48, 0.0],
        "escrow": [0.0, 0.0, 0.42, 1.12, 1.78, 2.32, 2.78],
        "timeline": ["01.27", "07.27", "07.28", "01.29", "07.29", "07.30", "12.30"],
        "phases": [
            {"name": "ИРД и согласования", "start": 0, "length": 38, "tone": "blue"},
            {"name": "БРИДЖ", "start": 0, "length": 38, "tone": "violet"},
            {"name": "Строительство", "start": 38, "length": 48, "tone": "cyan"},
            {"name": "Продажи", "start": 38, "length": 60, "tone": "green"},
            {"name": "ПФ", "start": 38, "length": 60, "tone": "amber"},
        ],
        "sensitivity": [
            {"name": "Цена квартир", "low": 1.043, "base": 1.118, "high": 1.191},
            {"name": "Наземное строительство", "low": 1.073, "base": 1.118, "high": 1.168},
            {"name": "Лаг старта продаж", "low": 1.057, "base": 1.118, "high": 1.118},
            {"name": "Срок строительства", "low": 1.088, "base": 1.118, "high": 1.147},
            {"name": "ВРИ", "low": 1.105, "base": 1.118, "high": 1.132},
        ],
        "queues": [],
        "risks": [
            "LLCR 1,12x ниже целевого уровня 1,20x",
            "Фактический пик БРИДЖа выше расчётного в 2,6 раза",
            "Плата за ВРИ формирует существенную нагрузку до РнС",
        ],
    },
    "mytishchi": {
        "slug": "mytishchi",
        "name": "Мытищи",
        "region": "Московская область",
        "subtitle": "22 участка · 3 очереди · офисы в О3",
        "status": "Цена покупки не указана",
        "statusTone": "neutral",
        "source": "Контрольный PDF DevelopAid · 02.08.2026",
        "prototype": True,
        "kpi": {
            "revenue": 123.50,
            "costs": 111.54,
            "ebitda": 25.50,
            "netProfit": 11.96,
            "margin": 9.7,
            "llcr": 1.11,
            "bridgeCalc": 2.24,
            "bridgePeak": 8.10,
            "pfPeak": 10.05,
            "interest": 9.35,
        },
        "tep": {
            "gns": 451709,
            "saleable": 244289,
            "apartments": 201807,
            "commercial": 20532,
            "offices": 21950,
            "parking": 2310,
            "kindergarten": 465,
            "school": 675,
            "clinic": 128,
            "vri": 4.80,
        },
        "products": [
            {"name": "Квартиры", "value": 93.63, "share": 75.8},
            {"name": "Коммерция", "value": 9.53, "share": 7.7},
            {"name": "Офисы / МФОЦ", "value": 15.74, "share": 12.7},
            {"name": "Паркинг", "value": 4.59, "share": 3.7},
        ],
        "costStructure": [
            {"name": "Строительство", "value": 61.24},
            {"name": "Проценты и комиссии", "value": 9.35},
            {"name": "Маркетинг и продажи", "value": 8.64},
            {"name": "Отдельные объекты", "value": 6.40},
            {"name": "ВРИ / земельные права", "value": 4.80},
        ],
        "cashflow": [-2.24, -6.40, -3.75, 1.60, 7.40, 10.20, 11.96],
        "debt": [2.24, 8.10, 4.20, 10.05, 4.10, 7.20, 0.0],
        "escrow": [0.0, 2.50, 12.80, 29.50, 16.20, 38.10, 55.60],
        "timeline": ["01.27", "07.28", "07.29", "07.30", "07.31", "07.32", "12.32"],
        "phases": [
            {"name": "О1", "start": 0, "length": 40, "tone": "blue"},
            {"name": "О2", "start": 20, "length": 40, "tone": "amber"},
            {"name": "О3", "start": 40, "length": 40, "tone": "green"},
            {"name": "Офисы / МФОЦ", "start": 60, "length": 40, "tone": "violet"},
        ],
        "sensitivity": [
            {"name": "Цена квартир О1", "low": 0.893, "base": 0.985, "high": 1.055},
            {"name": "Наземное строительство", "low": 0.933, "base": 0.985, "high": 1.032},
            {"name": "Лаг старта продаж", "low": 0.916, "base": 0.985, "high": 0.985},
            {"name": "Рост цены до РВЭ", "low": 0.964, "base": 0.985, "high": 1.005},
            {"name": "ВРИ", "low": 0.969, "base": 0.985, "high": 1.001},
        ],
        "queues": [
            {"name": "О1", "gns": 169709, "saleable": 88936, "revenue": 40.20, "costs": 40.81, "profit": -0.62, "llcr": 0.98},
            {"name": "О2", "gns": 135760, "saleable": 71148, "revenue": 34.73, "costs": 32.08, "profit": 2.66, "llcr": 1.09},
            {"name": "О3", "gns": 146240, "saleable": 84205, "revenue": 48.57, "costs": 38.64, "profit": 9.92, "llcr": 1.28},
        ],
        "risks": [
            "О1 убыточна и имеет LLCR 0,98x",
            "Пиковая задолженность ПФ 10,05 млрд ₽",
            "Фактический БРИДЖ 8,10 млрд ₽ при расчётном 2,24 млрд ₽",
            "Экономика проекта зависит от сильной третьей очереди",
        ],
    },
}
