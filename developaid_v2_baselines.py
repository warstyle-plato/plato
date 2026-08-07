"""Accepted control baselines for DevelopAid 2.0.

The values in this module are not a second calculation engine. They are
acceptance fixtures copied from the approved Excel/PDF reports and are used
only until the live ProjectResult adapter is connected.
"""

from __future__ import annotations

from typing import Any


MISHINA_ACCEPTED_2026_08_03: dict[str, Any] = {
    "slug": "mishina",
    "name": "Мишина",
    "region": "Москва",
    "subtitle": "77:09:0004014:13 · ГлавАПУ · бизнес-класс",
    "status": "Требует пересмотра условий покупки",
    "statusTone": "warning",
    "source": "Эталон Excel/PDF DevelopAid · 03.08.2026",
    "prototype": True,
    "acceptedBaseline": True,
    "seriesPrototype": False,
    "kpi": {
        "revenue": 12.74300931780029,
        "costs": 11.662565375599463,
        "ebitda": 2.728464657554266,
        "netProfit": 1.0804439422008295,
        "margin": 8.478718921531297,
        "llcr": 1.0947782477164054,
        "bridgeCalc": 1.410503,
        "bridgePeak": 2.76125545,
        "bridgePeakCapitalized": 2.973929591891138,
        "pfPeak": 2.64,
        "pfLimit": 10.02,
        "interest": 1.287872734619827,
    },
    "tep": {
        "gns": 25967,
        "saleable": 15150,
        "apartments": 13920,
        "commercial": 1230,
        "parking": 91,
        "vri": 1.28973,
        "socialPayment": 0.580668,
    },
    "products": [
        {"name": "Квартиры", "value": 11.19, "share": 87.8},
        {"name": "Коммерция", "value": 0.9885, "share": 7.8},
        {"name": "Паркинг", "value": 0.5626, "share": 4.4},
    ],
    "costStructure": [
        {"name": "Основное строительство", "value": 5.72},
        {"name": "Смена ВРИ / земельные права", "value": 1.28973},
        {"name": "Проценты и комиссии", "value": 1.287872734619827},
        {"name": "Маркетинг и продажи", "value": 0.8917},
        {"name": "Цена приобретения", "value": 0.70},
        {"name": "Социальная нагрузка", "value": 0.580668},
        {"name": "Прочие расходы", "value": 1.19},
    ],
    # Quarterly values are taken from the cached monthly Excel calculation:
    # project CF is summed by quarter; debt and escrow are quarter-end balances.
    "cashflow": [
        -0.704544225,
        -0.004544225,
        -0.004544225,
        -0.004544225,
        -0.086340275,
        -1.956738275,
        -0.5244164105206055,
        -0.8423544618745109,
        -0.9967513367691881,
        -0.9982278772387124,
        -1.0049616391663991,
        -1.0226561829009622,
        -0.8221407785898387,
        -0.8861207340580395,
        11.396709056812416,
        0.8304924911264994,
    ],
    "debt": [
        0.7277762151602007,
        0.7678254243854348,
        0.8085843566631803,
        0.8499574972291914,
        0.9748127496117237,
        2.973929591891138,
        3.6661115942758054,
        4.612389953587831,
        5.719011477560992,
        6.835536747271543,
        7.9678237724867955,
        9.12148996099267,
        10.076292098727,
        11.088876999741698,
        0.0,
        0.0,
    ],
    "escrow": [
        0.0,
        0.0,
        0.0,
        0.0,
        0.0,
        0.0,
        0.9601433210203604,
        2.1079123466281264,
        3.284177784782803,
        4.481536658216397,
        5.7750921306169465,
        7.321426799225538,
        8.90615333036843,
        10.519298044546511,
        0.0,
        0.0,
    ],
    "timeline": [
        "2027 Q1", "2027 Q2", "2027 Q3", "2027 Q4",
        "2028 Q1", "2028 Q2", "2028 Q3", "2028 Q4",
        "2029 Q1", "2029 Q2", "2029 Q3", "2029 Q4",
        "2030 Q1", "2030 Q2", "2030 Q3", "2030 Q4",
    ],
    "phases": [
        {"name": "ИРД и согласования", "start": 0, "length": 40, "tone": "blue"},
        {"name": "БРИДЖ", "start": 0, "length": 40, "tone": "violet"},
        {"name": "Строительство ЖК", "start": 38, "length": 52, "tone": "cyan"},
        {"name": "Продажи", "start": 38, "length": 62, "tone": "green"},
        {"name": "Проектное финансирование", "start": 38, "length": 62, "tone": "amber"},
    ],
    "sensitivity": [
        {"name": "Цена квартир", "low": 1.043, "base": 1.095, "high": 1.191},
        {"name": "Наземное строительство", "low": 1.073, "base": 1.095, "high": 1.168},
        {"name": "Лаг старта продаж", "low": 1.057, "base": 1.095, "high": 1.095},
        {"name": "Срок строительства", "low": 1.088, "base": 1.095, "high": 1.147},
        {"name": "ВРИ", "low": 1.082, "base": 1.095, "high": 1.108},
    ],
    "queues": [],
    "risks": [
        "LLCR 1,10x ниже целевого уровня 1,20x",
        "Фактическая выборка БРИДЖа 2,76 млрд ₽ против расчётных 1,41 млрд ₽",
        "Пик БРИДЖа с капитализацией процентов достигает 2,99 млрд ₽",
        "ВРИ 1,29 млрд ₽ и социальный платёж 580,7 млн ₽ создают нагрузку до РнС",
    ],
}


def apply_accepted_baselines(projects: dict[str, dict[str, Any]]) -> None:
    """Replace only accepted control fixtures; never calculate inside UI code."""

    projects["mishina"] = MISHINA_ACCEPTED_2026_08_03
