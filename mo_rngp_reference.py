"""Справочник нормативов градостроительного проектирования Московской области.

Только данные и ссылки. Здесь ничего не считается: модуль отвечает на вопрос
«что говорит норматив», а не «сколько получилось». Правило то же, что и для
адаптера результата 2.0 — первая арифметика здесь означает вторую реализацию
методики.

Зачем отдельный файл. Мы возили московские нормативы под видом общих: паркинг
считался по московской методике (площадь квартир ÷ 90), участки ДОО и школ
брались из калькулятора ГлавАПУ. Для Московской области это неверно, и ошибка
выглядела достоверно — ровно тот случай, что записан в правилах проекта про
зашитую цифру, неотличимую от посчитанной.

Порядок работы, установленный владельцем 16.08.2026: движок формулирует, каких
норм ему не хватает; владелец приносит подтверждённый источник; движок вносит
подтверждённое сюда. Норма без прямой цитаты и официальной публикации живёт со
статусом UNRESOLVED и в автоматический отказ не идёт.

Статусы источника
-----------------
CONFIRMED_PRIMARY  — прочитано в тексте самого постановления.
CONFIRMED_EXAMPLE  — воспроизведено из официального примера в приложении и
                     сошлось с ним численно (см. tests).
UNRESOLVED         — есть только вторичный источник или пересказ. Не применять
                     для автоматического отказа.

Действующая редакция
--------------------
Нормативы градостроительного проектирования Московской области утверждены
постановлением Правительства Московской области от 17.08.2015 № 713/30.
Последняя учтённая поправка — постановление Правительства Московской области
от 02.07.2026 № 774-ПП, вступило в силу 03.07.2026. Официальное опубликование:
http://publication.pravo.gov.ru/document/5000202607030006
"""

from __future__ import annotations

from typing import Any

# Постановление, из которого прочитаны нормы со статусом CONFIRMED_PRIMARY.
PP_774 = {
    "document": "Постановление Правительства Московской области от 02.07.2026 № 774-ПП",
    "changes": "Нормативы градостроительного проектирования Московской области "
               "(ПП МО от 17.08.2015 № 713/30)",
    "effective_revision": "02.07.2026",
    "in_force_since": "2026-07-03",
    "official_publication": "http://publication.pravo.gov.ru/document/5000202607030006",
}

# Единицы, которые здесь встречаются. Заведены явно, потому что путаница между
# «на место» и «на человека» и между «здание» и «земля» — главный источник
# ошибок в разы, а не в проценты.
UNIT_CARS_PER_1000 = "авто/1000 чел."
UNIT_SQM_PER_SPACE = "м²/машино-место"
UNIT_SQM_PER_PERSON = "м²/чел."
UNIT_SQM_PER_FLAT_SQM = "м² квартир/чел."
UNIT_SHARE = "доля"
UNIT_METERS = "м"

# База, к которой относится площадь. LAND_PLOT — территория участка;
# BUILDING_FOOTPRINT — пятно застройки здания; BUILDING_GFA — площадь здания.
BASIS_LAND_PLOT = "LAND_PLOT_AREA"
BASIS_BUILDING_FOOTPRINT = "BUILDING_FOOTPRINT"
BASIS_NONE = None


def _rule(**fields: Any) -> dict[str, Any]:
    """Одна норма. Обязательные поля перечислены явно, чтобы норма без цитаты
    не проскочила: тест ловит пропуск."""
    return fields


# --- ПАРКОВКИ: потребность (п. 5.12 в редакции 774-ПП) ---------------------------

PARKING_PERMANENT_RATE = _rule(
    key="parking_permanent_rate",
    value=0.90 * 356,                      # 320,4 автомобиля на 1000 человек
    unit=UNIT_CARS_PER_1000,
    rule_type="MANDATORY_CALCULATION_RULE",
    area_basis=BASIS_NONE,
    conditions="обычная жилая застройка; расчётное население",
    document=PP_774["document"],
    point="п. 5.12 Нормативов",
    effective_revision=PP_774["effective_revision"],
    official_publication=PP_774["official_publication"],
    quote="Потребность расчетного населения в местах для постоянного хранения "
          "индивидуального автомобильного транспорта составляет 90% от уровня "
          "автомобилизации – 356 автомобилей на 1000 человек расчетного населения",
    status="CONFIRMED_PRIMARY",
)

PARKING_PERMANENT_RATE_LOW_RISE_CLUSTER = _rule(
    key="parking_permanent_rate_low_rise_cluster",
    value=1.00 * 356,
    unit=UNIT_CARS_PER_1000,
    rule_type="MANDATORY_CALCULATION_RULE",
    area_basis=BASIS_NONE,
    conditions="малоэтажная жилая застройка в кластерах МЖС",
    document=PP_774["document"],
    point="п. 5.12 Нормативов",
    effective_revision=PP_774["effective_revision"],
    official_publication=PP_774["official_publication"],
    quote="потребность расчетного населения для малоэтажной жилой застройки в "
          "кластерах МЖС в местах для постоянного хранения индивидуального "
          "автомобильного транспорта составляет 100% от уровня автомобилизации "
          "356 автомобилей на 1000 человек расчетного населения",
    status="CONFIRMED_PRIMARY",
)

PARKING_TEMPORARY_RATE = _rule(
    key="parking_temporary_rate",
    value=30.0,
    unit=UNIT_CARS_PER_1000,
    rule_type="MANDATORY_MINIMUM",
    area_basis=BASIS_NONE,
    conditions="временное хранение легковых автомобилей; размещение в границах "
               "жилого района",
    document=PP_774["document"],
    point="п. 5.12 Нормативов",
    effective_revision=PP_774["effective_revision"],
    official_publication=PP_774["official_publication"],
    quote="Потребность расчетного населения в местах для временного хранения "
          "легковых автомобилей следует предусматривать из расчета не менее – "
          "30 автомобилей на 1000 человек расчетного населения",
    status="CONFIRMED_PRIMARY",
)

# --- ПАРКОВКИ: где размещаются ----------------------------------------------------
#
# Это та норма, которая запрещает считать «на участке не хватает земли под все
# места» отказом: на квартал приходится не менее 40%, остальное размещается в
# границах жилого района.

PARKING_SHARE_IN_QUARTER = _rule(
    key="parking_share_in_quarter",
    value=0.40,
    unit=UNIT_SHARE,
    rule_type="MANDATORY_MINIMUM",
    area_basis=BASIS_NONE,
    conditions="доля мест постоянного хранения в границах квартала",
    document=PP_774["document"],
    point="п. 5.12 Нормативов",
    effective_revision=PP_774["effective_revision"],
    official_publication=PP_774["official_publication"],
    quote="Распределение обеспеченности расчетного населения местами для "
          "постоянного хранения индивидуального автомобильного транспорта: "
          "в границах квартала – не менее 40%",
    status="CONFIRMED_PRIMARY",
)

PARKING_SHARE_IN_DISTRICT = _rule(
    key="parking_share_in_district",
    value=0.60,
    unit=UNIT_SHARE,
    rule_type="MANDATORY_CALCULATION_RULE",
    area_basis=BASIS_NONE,
    conditions="в границах жилого района на селитебных территориях и на "
               "прилегающих производственных территориях, при соблюдении "
               "дальности пешеходной доступности",
    document=PP_774["document"],
    point="п. 5.12 Нормативов",
    effective_revision=PP_774["effective_revision"],
    official_publication=PP_774["official_publication"],
    quote="в границах жилого района на селитебных территориях и на прилегающих "
          "производственных территориях – 60% при условии обеспечения для "
          "расчетного населения дальности пешеходной доступности мест для "
          "постоянного хранения индивидуального автомобильного транспорта не "
          "более 800 м, а в районах (территориях) реконструкции – не более 1200 м",
    status="CONFIRMED_PRIMARY",
)

PARKING_WALK_DISTANCE = _rule(
    key="parking_walk_distance",
    value=800.0,
    value_reconstruction=1200.0,
    unit=UNIT_METERS,
    rule_type="MANDATORY_MAXIMUM",
    area_basis=BASIS_NONE,
    conditions="дальность пешеходной доступности; в районах (территориях) "
               "реконструкции — 1200 м",
    document=PP_774["document"],
    point="п. 5.12 Нормативов",
    effective_revision=PP_774["effective_revision"],
    official_publication=PP_774["official_publication"],
    quote="не более 800 м, а в районах (территориях) реконструкции – не более 1200 м",
    status="CONFIRMED_PRIMARY",
)

PARKING_SHORTAGE_GOES_UNDERGROUND_OR_MULTILEVEL = _rule(
    key="parking_shortage_goes_multilevel",
    value=None,
    unit=None,
    rule_type="MANDATORY_RULE",
    area_basis=BASIS_NONE,
    conditions="недостаточность территории квартала",
    document=PP_774["document"],
    point="п. 5.12 Нормативов",
    effective_revision=PP_774["effective_revision"],
    official_publication=PP_774["official_publication"],
    quote="В случае недостаточности территории квартала размещение автомобилей "
          "жителей необходимо предусматривать в многоэтажных подземных и (или) "
          "наземных гаражах.",
    status="CONFIRMED_PRIMARY",
)

DEPENDENT_SPACES_NOT_ALLOWED = _rule(
    key="dependent_spaces_not_allowed",
    value=None,
    unit=None,
    rule_type="MANDATORY_PROHIBITION",
    area_basis=BASIS_NONE,
    conditions="зависимые места хранения (одно за другим)",
    document=PP_774["document"],
    point="п. 5.12 Нормативов",
    effective_revision=PP_774["effective_revision"],
    official_publication=PP_774["official_publication"],
    quote="Не допускается обеспечение нормативной потребности планируемой "
          "застройки в местах хранения индивидуального автомобильного транспорта "
          "и приобъектных стоянках за счет зависимых мест хранения автотранспорта.",
    status="CONFIRMED_PRIMARY",
)

# --- ПАРКОВКИ: разрешённые снижения потребности -----------------------------------
#
# Оба снижения обусловлены близостью к станции железной дороги, метро или
# скоростного трамвая: 15% — если до станции можно дойти пешком, 10% — если до
# неё довозит наземный транспорт. Суммируются ли они, из текста не следует;
# до выяснения складывать нельзя.

PARKING_REDUCTION_STATION_WALK = _rule(
    key="parking_reduction_station_walk",
    value=0.15,
    unit=UNIT_SHARE,
    rule_type="ALLOWED_REDUCTION",
    area_basis=BASIS_NONE,
    conditions="пешеходные коммуникации до входа на станцию ж/д, метро или "
               "скоростного трамвая не более 800 м (реконструкция — 1200 м)",
    document=PP_774["document"],
    point="п. 5.12 Нормативов",
    effective_revision=PP_774["effective_revision"],
    official_publication=PP_774["official_publication"],
    quote="на 15% при наличии/обустройстве пешеходных коммуникаций … при "
          "пешеходной доступности от жилого дома до ближайшего входа на станцию – "
          "не более 800 м, а в районах (территориях) реконструкции – не более 1200 м",
    cumulative_with_others="UNKNOWN",
    status="CONFIRMED_PRIMARY",
)

PARKING_REDUCTION_TRANSIT_TO_STATION = _rule(
    key="parking_reduction_transit_to_station",
    value=0.10,
    unit=UNIT_SHARE,
    rule_type="ALLOWED_REDUCTION",
    area_basis=BASIS_NONE,
    conditions="остановка наземного пассажирского транспорта не более 500 м от "
               "дома; время в пути до станции не более 10 минут, расстояние не "
               "более 5 км",
    document=PP_774["document"],
    point="п. 5.12 Нормативов",
    effective_revision=PP_774["effective_revision"],
    official_publication=PP_774["official_publication"],
    quote="на 10 % - при наличии остановок наземного пассажирского транспорта в "
          "пешеходной доступности не более 500 метров от жилого дома, при этом "
          "время в пути от остановки до указанных станций на наземном "
          "пассажирском транспорте составляет не более 10 минут, расстояние – "
          "не более 5 км",
    cumulative_with_others="UNKNOWN",
    status="CONFIRMED_PRIMARY",
)

PARKING_REDUCTION_COOPERATIVE = _rule(
    key="parking_reduction_cooperative",
    value=0.15,
    unit=UNIT_SHARE,
    rule_type="ALLOWED_REDUCTION",
    area_basis=BASIS_NONE,
    conditions="кооперированная стоянка, обслуживающая группы объектов разного "
               "назначения; снижение за счёт сдвига часов пик",
    document=PP_774["document"],
    point="п. 5.12 Нормативов",
    effective_revision=PP_774["effective_revision"],
    official_publication=PP_774["official_publication"],
    quote="допускается снижать суммарное требуемое количество машино-мест без "
          "снижения обеспеченности ими за счет сдвига часов пик при "
          "функционировании обслуживаемых парковками объектов не более чем на 15%",
    cumulative_with_others="UNKNOWN",
    status="CONFIRMED_PRIMARY",
)

# --- ПАРКОВКИ: габариты и площадь --------------------------------------------------

PARKING_STALL_MIN_SIZE = _rule(
    key="parking_stall_min_size",
    value=(5.3, 2.5),
    unit="м × м",
    rule_type="MANDATORY_MINIMUM",
    area_basis=BASIS_NONE,
    conditions="машино-место; для инвалида на кресле-коляске 6,0 × 3,6 м; вдоль "
               "проезжей части длина 6,8 м",
    document=PP_774["document"],
    point="п. 5.12 Нормативов",
    effective_revision=PP_774["effective_revision"],
    official_publication=PP_774["official_publication"],
    quote="Минимально допустимые размеры машино-места составляют 5,3 х 2,5 м.",
    status="CONFIRMED_PRIMARY",
)

# ВНИМАНИЕ ОБ ОБЛАСТИ ПРИМЕНЕНИЯ. В тексте 774-ПП число 22,5 стоит внутри абзаца
# о площадках временного хранения для кластеров ИЖС и МЖС. Общая норма «площадь
# территории для автомобиля на открытой автостоянке — 22,5 кв.м» приписывается
# п. 5.11, но в 774-ПП этот пункт не менялся, и первичного текста п. 5.11 у нас
# нет. Поэтому здесь зафиксирована только та область, которую видно в самом
# постановлении, а общая — отдельной дырой G3a.
PARKING_FLAT_AREA_PER_SPACE_CLUSTER = _rule(
    key="parking_flat_area_per_space_cluster",
    value=22.5,
    unit=UNIT_SQM_PER_SPACE,
    rule_type="MANDATORY_CALCULATION_RULE",
    area_basis=BASIS_LAND_PLOT,
    conditions="площадки временного хранения автомобилей для расчётного "
               "населения кластеров ИЖС и МЖС",
    document=PP_774["document"],
    point="п. 5.12 Нормативов",
    effective_revision=PP_774["effective_revision"],
    official_publication=PP_774["official_publication"],
    quote="При этом площадь территории для размещения одного автомобиля "
          "принимается из расчета 22,5 кв. м.",
    scope_warning="В первичном тексте это правило стоит в абзаце про кластеры "
                  "ИЖС и МЖС. Применимость ко всем открытым стоянкам МКД не "
                  "подтверждена — см. дыру G3a.",
    status="CONFIRMED_PRIMARY",
)

# --- ПРИОБЪЕКТНЫЕ СТОЯНКИ ----------------------------------------------------------

PARKING_SCHOOL_DROPOFF = _rule(
    key="parking_school_dropoff",
    value={"до 1100 учащихся": {"на 100 учащихся": 1, "на 100 работающих": 7},
           "1100 и более учащихся": {"на 100 учащихся": 1, "на 100 работающих": 5}},
    unit="машино-мест",
    rule_type="MANDATORY_MINIMUM",
    area_basis=BASIS_NONE,
    conditions="кратковременная остановка автотранспорта родителей и работников; "
               "пешеходная доступность не более 200 м от территории учреждения",
    document=PP_774["document"],
    point="п. 5.12 Нормативов, таблица",
    effective_revision=PP_774["effective_revision"],
    official_publication=PP_774["official_publication"],
    quote="до 1100 учащихся — 1 м/м на 100 учащихся и 7 м/м на 100 работающих; "
          "1100 и более учащихся — 1 м/м на 100 учащихся и 5 м/м на 100 работающих",
    status="CONFIRMED_PRIMARY",
)

PARKING_DOO_DROPOFF = _rule(
    key="parking_doo_dropoff",
    value={"до 330 мест": {"всего": 5},
           "свыше 330 мест": {"на 100 мест": 1, "на 100 сотрудников": 10}},
    unit="машино-мест",
    rule_type="MANDATORY_MINIMUM",
    area_basis=BASIS_NONE,
    conditions="кратковременная остановка; пешеходная доступность не более 200 м",
    document=PP_774["document"],
    point="п. 5.12 Нормативов, таблица",
    effective_revision=PP_774["effective_revision"],
    official_publication=PP_774["official_publication"],
    quote="до 330 мест — 5 м/м; свыше 330 мест — 1 м/м на 100 мест и 10 м/м "
          "на 100 сотрудников",
    status="CONFIRMED_PRIMARY",
)

# Прямо про наши ПСН и коммерцию первых этажей: одно место на 50 м² общей площади.
PARKING_NONRESIDENTIAL_GROUND_FLOOR = _rule(
    key="parking_nonresidential_ground_floor",
    value=50.0,
    unit="м² общей площади на 1 машино-место",
    rule_type="MANDATORY_CALCULATION_RULE",
    area_basis=BASIS_NONE,
    conditions="встроенно-пристроенные нежилые помещения первых этажей жилой "
               "застройки и многоуровневых паркингов в уровне первого этажа, "
               "независимо от функции; кроме ДОО и поликлиник. Помещения с "
               "определённой функцией — по приложению № 10",
    document=PP_774["document"],
    point="п. 5.12 Нормативов",
    effective_revision=PP_774["effective_revision"],
    official_publication=PP_774["official_publication"],
    quote="для встроенно-пристроенных нежилых помещений на первых этажах жилой "
          "застройки и многоуровневых паркингов в уровне первого этажа "
          "независимо от функции (за исключением дошкольных образовательных "
          "организаций, поликлиник) - из расчета 1 место на 50 кв. м общей "
          "площади таких помещений",
    status="CONFIRMED_PRIMARY",
)

# --- ЗЕМЛЯ: минимально необходимая площадь территории ------------------------------
#
# Главное открытие сверки: земельный баланс в области нормирован, и считается он
# не по геометрии, а удельным коэффициентом на человека. В самом нормативе есть
# и строка «Профицит (дефицит)» — то есть односторонний показатель, который мы
# собирались вводить сами, уже существует.

LAND_SMIN_FORMULA = _rule(
    key="land_smin_formula",
    value="S_min = К_уд × расчётное население",
    unit=None,
    rule_type="MANDATORY_CALCULATION_RULE",
    area_basis=BASIS_LAND_PLOT,
    conditions="для целей межевания; К_уд — сумма строк таблицы № 13 Нормативов "
               "по типу устойчивой системы расселения и численности населения",
    document=PP_774["document"],
    point="приложение 7, пример 4, пункт 1",
    effective_revision=PP_774["effective_revision"],
    official_publication=PP_774["official_publication"],
    quote="определяем минимально необходимую площадь территории для жилого дома "
          "и / или комплекса жилых домов по формуле: S min = К уд. х расчетное "
          "население",
    status="CONFIRMED_PRIMARY",
)

# Слагаемые К_уд из официального примера: городская УСР, население 15–50 тыс.
# Это НЕ вся таблица № 13, а только тот её столбец, который виден в примере.
LAND_KUD_EXAMPLE_URBAN_15_50K = _rule(
    key="land_kud_urban_15_50k",
    value={
        "1. Территории объектов для хранения индивидуального автотранспорта": 2.30,
        "2. Территории объектов инженерного обеспечения": 0.25,
        "3. Территории объектов физкультурно-спортивного назначения": 1.02,
        "4. Территории объектов торговли и общественного питания": 0.30,
        "5. Территории объектов коммунального и бытового обслуживания": 0.13,
        "14. Территории объектов жилищного строительства": 15.50,
    },
    total=19.50,
    unit=UNIT_SQM_PER_PERSON,
    rule_type="MANDATORY_CALCULATION_RULE",
    area_basis=BASIS_LAND_PLOT,
    conditions="устойчивая система расселения — городская; население населённого "
               "пункта от 15 до 50 тысяч человек",
    document=PP_774["document"],
    point="приложение 7, пример 4, пункт 1 (со ссылкой на таблицу № 13 Нормативов)",
    effective_revision=PP_774["effective_revision"],
    official_publication=PP_774["official_publication"],
    quote="К уд. = 2,3 + 0,25 + 1,02 + 0,30 + 0,13 + 15,5 = 19,50 (кв. м/человека)",
    scope_warning="Значения сняты с одного столбца таблицы № 13. Для другой УСР "
                  "или другой численности они иные — см. дыру G14.",
    status="CONFIRMED_PRIMARY",
)

# Расчётное население в официальном примере получено из площади квартир: на всех
# четырёх строках отношение одно и то же, 27,97–27,99. Самой нормы с этим числом
# в тексте поправки нет — она в неизменённой части Нормативов, поэтому статус
# «воспроизведено из примера», а сам делитель остаётся дырой G13.
LAND_POPULATION_PER_FLAT_AREA = _rule(
    key="land_population_per_flat_area",
    value=27.98,
    unit=UNIT_SQM_PER_FLAT_SQM,
    rule_type="DERIVED",
    area_basis=BASIS_NONE,
    conditions="расчётное население = площадь квартир ÷ норма жилищной "
               "обеспеченности",
    document=PP_774["document"],
    point="приложение 7, пример 4, пункт 1 — таблица исходных данных",
    effective_revision=PP_774["effective_revision"],
    official_publication=PP_774["official_publication"],
    quote="МКД 1: площадь квартир 26000, расчетное население 929; МКД 2: 19940 и "
          "713; МКД 3: 8700 и 311; ИТОГО: 54640 и 1953",
    scope_warning="Делитель в тексте поправки не назван, восстановлен обратным "
                  "счётом по четырём строкам примера. Точное значение и его "
                  "зависимость от типа застройки — дыра G13.",
    status="CONFIRMED_EXAMPLE",
)

# Официальный пример целиком: на нём проверяется, что наша реализация формулы
# совпадает с нормативом. Строки — (площадь квартир, население, S_min, ЗУ по ПМТ).
LAND_SMIN_OFFICIAL_EXAMPLE = {
    "kud": 19.50,
    "rows": [
        {"name": "МКД 1", "flat_area_sqm": 26000, "population": 929,
         "s_min_sqm": 18115.5, "plot_sqm": 19000, "balance_sqm": 885.0},
        {"name": "МКД 2", "flat_area_sqm": 19940, "population": 713,
         "s_min_sqm": 13903.5, "plot_sqm": 13200, "balance_sqm": -703.5},
        {"name": "МКД 3", "flat_area_sqm": 8700, "population": 311,
         "s_min_sqm": 6064.5, "plot_sqm": 6200, "balance_sqm": 135.5},
        {"name": "МКД 1-3", "flat_area_sqm": 54640, "population": 1953,
         "s_min_sqm": 38083.5, "plot_sqm": 38400, "balance_sqm": 316.5},
    ],
    "document": PP_774["document"],
    "point": "приложение 7, пример 4, пункт 1",
    "official_publication": PP_774["official_publication"],
}


# --- Что ещё не подтверждено -------------------------------------------------------
#
# Дыры нумерованы сквозным списком, который ведётся в переписке с владельцем.
# Норма отсюда в автоматический отказ не идёт: у неё нет первичного источника.

UNRESOLVED: dict[str, dict[str, Any]] = {
    "G1": {
        "question": "Площадь на машино-место для наземного многоуровневого гаража "
                    "по этажности",
        "candidates": "приложение № 9 к 713/30: 20 / 14 / 12 / 10 м² на место для "
                      "2 / 3 / 4 / 5+ этажей; basis — «территория участка, "
                      "занятого гаражом»; показатели названы рекомендованными",
        "source_seen": "вторичный (консолидированный текст на meganorm)",
        "blocks": "земельная нагрузка наземного паркинга",
        "note": "если подтвердится — делить на этажность НЕЛЬЗЯ, она уже внутри "
                "шкалы; и рекомендательный характер запрещает автоматический отказ",
    },
    "G2": {
        "question": "Площадь на машино-место для подземного гаража",
        "candidates": "приложение № 9: под домом 1 ярус — 55, 2 яруса — 25 "
                      "(basis — пятно застройки дома); под двором 1 ярус — 35, "
                      "2 яруса — 21 (basis — территория участка)",
        "source_seen": "вторичный",
        "blocks": "трактовка нашего поля underground_area_per_space_sqm = 35",
        "note": "если подтвердится, 35 — это земля под одноярусной подземкой во "
                "дворе, а НЕ площадь ГНС подземного паркинга. Для CAPEX нужен "
                "отдельный проектный ориентир м² ГНС на место, не из РНГП",
    },
    "G3a": {
        "question": "Общая норма 22,5 м² на автомобиль для открытых стоянок вне "
                    "кластеров ИЖС и МЖС",
        "candidates": "п. 5.11 Нормативов",
        "source_seen": "вторичный; в 774-ПП п. 5.11 не менялся, первичного текста нет",
        "blocks": "земельная нагрузка плоскостной стоянки для МКД",
        "note": "в самом 774-ПП 22,5 стоит только в абзаце про кластеры ИЖС и МЖС",
    },
    "G6": {"question": "Площадь земельного участка ДОО по вместимости, нормативы МО",
           "candidates": "у нас московские 35 / 32 / 20 м² на место",
           "source_seen": "калькулятор ГлавАПУ (Москва)",
           "blocks": "земельная нагрузка соцобъектов"},
    "G7": {"question": "Площадь земельного участка школы по вместимости, нормативы МО",
           "candidates": "у нас московские 19 / 16 / 14 / 10 / 45 м² на место",
           "source_seen": "калькулятор ГлавАПУ (Москва)",
           "blocks": "земельная нагрузка соцобъектов"},
    "G8": {"question": "Площадь земельного участка поликлиники, нормативы МО",
           "candidates": "у нас московские 0,35 га до 350 посещений в смену, "
                         "далее 0,1 га на каждые 100",
           "source_seen": "калькулятор ГлавАПУ (Москва)",
           "blocks": "земельная нагрузка соцобъектов"},
    "G9": {"question": "Обеспеченность плоскостными спортсооружениями в МО и чья "
                       "это земля",
           "candidates": "у нас московские 970 м² на тысячу жителей; в таблице "
                         "№ 13 есть строка «Территории объектов физкультурно-"
                         "спортивного назначения» 1,02 м²/чел — возможно, это она",
           "source_seen": "калькулятор ГлавАПУ (Москва) и пример 774-ПП",
           "blocks": "двойной счёт спорта между школьным участком и К_уд"},
    "G11": {"question": "Условие понижающего коэффициента 0,9 к участку ДОО и школы",
            "candidates": "в исходнике калькулятора ГлавАПУ множитель применяется "
                          "по отдельному флагу",
            "source_seen": "код калькулятора, без нормативного текста",
            "blocks": "пограничные случаи дефицита"},
    "G12": {"question": "Вправе ли городской округ МО ужесточить или смягчить "
                        "региональные нормативы; где публикуются местные НГП",
            "candidates": "нет",
            "source_seen": "нет",
            "blocks": "право давать автоматический отказ по региональной норме"},
    "G13": {"question": "Норма жилищной обеспеченности МО (делитель площади квартир "
                        "для расчётного населения)",
            "candidates": "27,98 м²/чел — восстановлено обратным счётом по "
                          "официальному примеру",
            "source_seen": "пример в приложении 7 (первичный), сама норма — нет",
            "blocks": "весь расчёт населения, а через него и паркинг, и К_уд"},
    "G14": {"question": "Таблица № 13 Нормативов целиком: удельные коэффициенты "
                        "для целей межевания по типам УСР и численности населения",
            "candidates": "из примера известен один столбец: городская УСР, "
                          "15–50 тыс. человек, сумма шести строк = 19,50 м²/чел",
            "source_seen": "пример в приложении 7 (первичный), таблица — нет",
            "blocks": "применение S_min к любому проекту, кроме подходящего под "
                      "условия примера"},
}


ALL_RULES: tuple[dict[str, Any], ...] = (
    PARKING_PERMANENT_RATE,
    PARKING_PERMANENT_RATE_LOW_RISE_CLUSTER,
    PARKING_TEMPORARY_RATE,
    PARKING_SHARE_IN_QUARTER,
    PARKING_SHARE_IN_DISTRICT,
    PARKING_WALK_DISTANCE,
    PARKING_SHORTAGE_GOES_UNDERGROUND_OR_MULTILEVEL,
    DEPENDENT_SPACES_NOT_ALLOWED,
    PARKING_REDUCTION_STATION_WALK,
    PARKING_REDUCTION_TRANSIT_TO_STATION,
    PARKING_REDUCTION_COOPERATIVE,
    PARKING_STALL_MIN_SIZE,
    PARKING_FLAT_AREA_PER_SPACE_CLUSTER,
    PARKING_SCHOOL_DROPOFF,
    PARKING_DOO_DROPOFF,
    PARKING_NONRESIDENTIAL_GROUND_FLOOR,
    LAND_SMIN_FORMULA,
    LAND_KUD_EXAMPLE_URBAN_15_50K,
    LAND_POPULATION_PER_FLAT_AREA,
)

# Московская методика, которую нельзя переносить в область. Держим списком, чтобы
# при подключении справочника к движку было видно, что именно замещается.
def reference_status() -> dict[str, Any]:
    """Состояние справочника для /status: по какой редакции живём и когда сверяли.

    Норматив меняется чаще, чем мы о нём вспоминаем: 713/30 за 2026 год правили
    трижды, и апрельская редакция успела устареть за один разговор. Справочник,
    про который не видно, когда его сверяли, ничем не лучше зашитой цифры —
    выглядит достоверно и молча отстаёт.
    """
    unresolved = sorted(UNRESOLVED)
    return {
        "document": PP_774["changes"],
        "effective_revision": PP_774["effective_revision"],
        "in_force_since": PP_774["in_force_since"],
        "amended_by": PP_774["document"],
        "official_publication": PP_774["official_publication"],
        "verified_at": VERIFIED_AT,
        "verified_from": VERIFIED_FROM,
        "rules_confirmed": sum(1 for rule in ALL_RULES
                               if str(rule.get("status", "")).startswith("CONFIRMED")),
        "rules_unresolved": len(unresolved),
        "unresolved": unresolved,
    }


def status_line() -> str:
    """Одна строка для сводки бота."""
    state = reference_status()
    return (f"РНГП МО: ред. {state['effective_revision']} "
            f"(в силе с {state['in_force_since']}), сверено {state['verified_at']} "
            f"по {state['verified_from']}; подтверждено правил "
            f"{state['rules_confirmed']}, открытых дыр {state['rules_unresolved']}")


# Дата и способ последней сверки. Меняются только вместе с содержимым: если
# норматив перечитан и ничего не изменилось, дата всё равно двигается — иначе
# по ней не отличить «сверяли и совпало» от «не открывали полгода».
VERIFIED_AT = "2026-08-16"
VERIFIED_FROM = "тексту постановления 774-ПП (PDF официальной публикации)"

# Московская методика, которую нельзя переносить в область. Держим списком, чтобы
# при подключении справочника к движку было видно, что именно замещается.
SUPERSEDED_MOSCOW_RULES = {
    "постоянные машино-места": "округление вверх от (площадь квартир × К1 ÷ 90); "
                               "в МО — 90% от 356 автомобилей на 1000 человек "
                               "расчётного населения",
    "гостевые машино-места": "десятая часть постоянных; в МО — не менее 30 "
                             "автомобилей на 1000 человек расчётного населения",
}
