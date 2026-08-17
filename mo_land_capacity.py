"""Нормативная ёмкость участка по РНГП Московской области.

Отвечает на вопрос покупки: сколько метров квартир нормативно помещается на
этой площадке и не мал ли участок под заявленный объём. Считает по формуле
самого норматива — S_min = К_уд × расчётное население, — а не по геометрии,
поэтому генплан не нужен.

Числа берутся из mo_rngp_reference и здесь не задаются: справочник отвечает за
происхождение норм, этот модуль — только за арифметику. Копию негде обновлять,
потому что копии нет.

Три решения, на которых стоит расчёт (владелец, 16.08.2026)
----------------------------------------------------------
**Считаем по кварталу, не по жилому району.** Без ППТ и решения о КРТ никто не
знает, чем окажется участок, но выбор несимметричен: квартал даёт К_уд 19,50, а
квартал вместе с жилым районом — около 39. Завысить требование вдвое значит
кричать на здоровых проектах. Школа, поликлиника, озеленение общего пользования
и улично-дорожная сеть нормируются на уровне жилого района и в расчёт не входят —
об этом сказано в самом ответе, иначе человек решит, что школа посчитана.

**Этажность вводится, а не угадывается.** К_уд зависит от неё в полтора раза:
28,67 при трёх этажах против 19,50 при шести-семи. В ППТ ограничение по этажам
есть почти всегда, его и берём. Известно пятно застройки — этажность считается
определением норматива: поэтажная площадь в габаритах наружных стен, делённая
на площадь застройки (проверено на официальном примере, где 38 757 ÷ 6 459 = 6).

**Вывод односторонний.** Дефицит territoryи — строгий вывод: обязательный минимум
больше участка, значит объём не садится. Профицит не значит ничего: норматив не
знает ни формы участка, ни пожарных разрывов, ни инсоляции. Поэтому здесь есть
`deficit_sqm` и нет ни одного поля со словом «резерв».
"""

from __future__ import annotations

from typing import Any

import mo_rngp_reference as ref

# Численность населённого пункта, для которой построена таблица № 13. За её
# пределами действуют другие таблицы Нормативов, которых у нас нет.
POPULATION_RANGE = (15_000, 50_000)

STOREYS_CHOICES = ("≤3", "4-5", "6-7")


def average_storeys(floor_area_sqm: float, footprint_sqm: float) -> float:
    """Средняя этажность по определению норматива.

    Суммарная поэтажная площадь в габаритах наружных стен, делённая на площадь
    застройки. На официальном примере даёт ровно объявленные там 6,0.
    """
    if footprint_sqm <= 0:
        return 0.0
    return floor_area_sqm / footprint_sqm


def storeys_column(storeys: float) -> str:
    """Столбец таблицы № 13 по средней этажности."""
    if storeys <= 3:
        return "≤3"
    if storeys <= 5:
        return "4-5"
    return "6-7"


def land_capacity(
    site_area_sqm: float,
    *,
    storeys: float | str = "6-7",
    flat_area_sqm: float | None = None,
    settlement_population: float | None = None,
) -> dict[str, Any]:
    """Нормативная ёмкость участка и потребность в машино-местах.

    `flat_area_sqm` — заявленный объём квартир. Если не задан, считается
    предельный: сколько квартир участок выдерживает по нормативу.
    `settlement_population` — численность населённого пункта; нужна только для
    предупреждения о применимости таблицы, в саму формулу не входит.
    """
    site_area_sqm = max(0.0, float(site_area_sqm or 0.0))
    column = storeys if isinstance(storeys, str) else storeys_column(float(storeys))
    if column not in STOREYS_CHOICES:
        raise ValueError(f"неизвестная этажность: {storeys!r}")
    kud = ref.kud_for_quarter(column)
    per_person = float(ref.LAND_POPULATION_PER_FLAT_AREA["value"])

    # Предельный объём квартир: участок ÷ К_уд даёт население, население ×
    # норму жилищной обеспеченности — метры квартир.
    capacity_population = site_area_sqm / kud if kud else 0.0
    max_flat_area = capacity_population * per_person

    declared = None if flat_area_sqm is None else max(0.0, float(flat_area_sqm))
    population = (declared / per_person) if declared is not None else capacity_population
    s_min = kud * population
    balance = site_area_sqm - s_min

    permanent_rate = float(ref.PARKING_PERMANENT_RATE["value"]) / 1000
    temporary_rate = float(ref.PARKING_TEMPORARY_RATE["value"]) / 1000
    quarter_share = float(ref.PARKING_SHARE_IN_QUARTER["value"])

    warnings: list[str] = [
        "Расчёт по нормативу квартала. Школа, поликлиника, озеленение общего "
        "пользования и улично-дорожная сеть нормируются на уровне жилого района "
        "и в эту площадь не входят — они обеспечиваются за границами участка.",
        "Отсутствие дефицита не означает, что объём физически садится: норматив "
        "не знает ни формы участка, ни пожарных разрывов, ни инсоляции.",
    ]
    applicable = True
    if settlement_population is not None:
        low, high = POPULATION_RANGE
        if not (low <= float(settlement_population) <= high):
            applicable = False
            warnings.insert(0, (
                f"Таблица № 13 построена для населённых пунктов от {low // 1000} "
                f"до {high // 1000} тысяч жителей, а здесь "
                f"{float(settlement_population):,.0f}".replace(",", " ")
                + ". Для другой численности действуют свои таблицы Нормативов — "
                  "результат считать нельзя."))
    else:
        warnings.append(
            "Численность населённого пункта не задана. Таблица № 13 действует "
            "для городов от 15 до 50 тысяч жителей; за этими пределами нужны "
            "другие таблицы Нормативов.")

    return {
        "applicable": applicable,
        "storeys_column": column,
        "kud_sqm_per_person": kud,
        "living_space_per_person_sqm": per_person,
        "flat_area_per_site_sqm": per_person / kud if kud else 0.0,
        "max_flat_area_sqm": max_flat_area,
        "capacity_population": capacity_population,
        "declared_flat_area_sqm": declared,
        "population": population,
        "s_min_sqm": s_min,
        "balance_sqm": balance,
        # Единственный вывод, который норматив позволяет сделать строго.
        "deficit_sqm": max(0.0, -balance),
        "parking_permanent": population * permanent_rate,
        "parking_temporary": population * temporary_rate,
        "parking_permanent_in_quarter_min": population * permanent_rate * quarter_share,
        "warnings": warnings,
        "source": {
            "document": ref.LAND_TABLE_13["document"],
            "point": ref.LAND_TABLE_13["point"],
            "effective_revision": ref.LAND_TABLE_13["effective_revision"],
            "official_publication": ref.LAND_TABLE_13["official_publication"],
        },
    }
