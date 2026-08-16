"""Льгота за создание места приложения труда — ПП Москвы № 1874-ПП.

Модуль намеренно отделён от расчётного движка ВРИ и финансовой модели: он
считает только размер льготы, создаваемой самим МПТ. Применение этой льготы к
конкретному проекту — отдельный шаг, которого здесь нет.

Источник — текст постановления от 31.12.2019 № 1874-ПП, приложение 3 и
приложение 1 (Порядок). Всё, чего в этом тексте нет, из расчёта убрано:
прежняя версия множила льготу на «Ксрок» 1,00–1,10, брала Кмест 0,7/0,8 и
переопределяла его таблицей из 99 кадастровых кварталов. Ни Ксрока, ни таких
коэффициентов, ни кварталов в постановлении нет — поиск по всем 37 страницам
даёт ноль совпадений. На спальном районе это завышало льготу вдвое.

Формула (п. 1.14.1 Порядка):

    Льгота = 1000 руб./кв.м × Sмпт × Кзатр × Кмест

Для объекта незавершённого строительства (п. 1.14.2):

    Льгота = 1000 руб./кв.м × Sмпт × (1 − Кгт/100) × Кзатр × Кмест
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from datetime import date
from typing import Any, Literal

Category = Literal[
    "office",
    "industrial",
    "social",
    "hotel",
    "mededu",
    "private_education",
    "sport",
    "culture",
]
Mode = Literal["new", "reconstruction", "ons"]
TtkPosition = Literal["inside", "outside"]

# Кзатр устанавливается не постановлением, а приказом ДИиПП (п. 1.14.1), и он
# не константа. Действующая редакция приказа ДИПП-ПР-34/20 от 28.02.2020 — в
# редакции приказа от 10.03.2026: Кзатр равен 166,23078 с 01.01.2026, а начиная
# со второго квартала 2026 года корректируется с первого числа первого месяца
# каждого квартала на обобщённый индекс изменения стоимости строительства за
# последний месяц предыдущего квартала к декабрю 2025 года.
#
# Прежняя редакция (приказ ДИПП-ПР-35/25 от 11.02.2025) давала 138,11132 с
# 01.01.2025 и индекс к декабрю 2024 года — на 2026 год она не действует.
#
# Зашитое число протухает раз в три месяца молча, поэтому значение вводится
# вместе с кварталом, к которому относится, и расчёт говорит, когда квартал
# сменился. До начала индексации оно установлено приказом точно и сверки не
# требует.
KZATR_BASE = 166.23078
KZATR_BASE_FROM = date(2026, 1, 1)
KZATR_DEFAULT = KZATR_BASE
KZATR_INDEXATION_FROM_QUARTER = "2026-Q2"
# Имя с «to» — потому что значение всегда стоит после предлога «к».
KZATR_INDEX_BASE_TO = "декабрю 2025 года"
KZATR_SOURCE = (
    "приказ ДИиПП ДИПП-ПР-34/20 от 28.02.2020 в редакции приказа от 10.03.2026: "
    "166,23078 с 01.01.2026, со второго квартала 2026 года — ежеквартальная "
    "корректировка на обобщённый индекс изменения стоимости строительства к "
    "декабрю 2025 года"
)
# Переходное положение того же приказа: квартальная корректировка не
# применяется к заявлениям по соглашениям, заключённым до его вступления в
# силу, — кроме увеличения общей площади МПТ и только в части прироста.
KZATR_TRANSITION = (
    "Квартальная корректировка не применяется к заявлениям по соглашениям, "
    "заключённым до вступления приказа от 10.03.2026 в силу, за исключением "
    "увеличения общей площади МПТ и только в части прироста такой площади."
)


# Обобщённые индексы изменения стоимости строительства к декабрю 2025 года —
# строка «Строительство» из распоряжения ДЭПР города Москвы № ДПРР-18-26 от
# 29.07.2026 (утверждает индексы за январь–июль 2026). Для квартала берётся
# индекс за последний месяц предыдущего квартала, как велит приказ ДИиПП:
# 2026-Q2 — март (1,0072), 2026-Q3 — июнь (1,0229). Квартал, которого здесь
# нет, честно остаётся без числа — /status напомнит принести следующее
# распоряжение, а не промолчит со старым Кзатр.
KZATR_INDICES_TO_DEC2025: dict[str, float] = {
    "2026-Q2": 1.0072,
    "2026-Q3": 1.0229,
}
KZATR_INDICES_SOURCE = (
    "распоряжение ДЭПР Москвы № ДПРР-18-26 от 29.07.2026, строка «Строительство», "
    "индексы к декабрю 2025 года"
)


def kzatr_for_quarter(quarter: str) -> float | None:
    """Кзатр квартала: база приказа × индекс к декабрю 2025 года.

    До начала индексации — база как есть; для квартала без утверждённого
    индекса — None: старое число выглядело бы как посчитанное.
    """
    key = str(quarter or "")
    if not key:
        return None
    if not quarter_is_indexed(key):
        return KZATR_BASE
    index = KZATR_INDICES_TO_DEC2025.get(key)
    if index is None:
        return None
    return round(KZATR_BASE * index, 5)


def quarter_of(day: date) -> str:
    return f"{day.year}-Q{(day.month - 1) // 3 + 1}"


def quarter_is_indexed(quarter: str) -> bool:
    """До второго квартала 2026 года Кзатр установлен приказом и не двигается."""
    return str(quarter or "") >= KZATR_INDEXATION_FROM_QUARTER


NORMATIVE_SNAPSHOT = (
    "ПП Москвы № 1874-ПП от 31.12.2019 · приложение 3 (Кмест), приложение 1 "
    "(формула, пороги, условия) · Кзатр — приказ ДИиПП ДИПП-ПР-34/20 в редакции "
    "от 10.03.2026, со второго квартала 2026 года пересматривается ежеквартально"
)

CATEGORY_LABELS: dict[str, str] = {
    "office": "Деловое управление / наука / торговля / развлечения / общепит",
    "industrial": "Производственная деятельность (кроме складов и складских площадок)",
    "social": "Социальное обслуживание (кроме общежитий) / бытовое обслуживание",
    "hotel": "Гостиница",
    "mededu": "Здравоохранение / образование и просвещение",
    "private_education": "Образование и просвещение",
    "sport": "Спорт",
    "culture": "Культурное развитие (кроме парков, цирков и зверинцев)",
}

# Графы таблицы приложения 3. Их три, а не восемь: постановление делит МПТ по
# видам разрешённого использования, а не по бытовым названиям объектов.
COLUMN_BUSINESS = "business"   # графа 2
COLUMN_SOCIAL = "social"       # графа 3
COLUMN_HOTEL = "hotel"         # графа 4

CATEGORY_COLUMN: dict[str, str] = {
    "office": COLUMN_BUSINESS,
    "industrial": COLUMN_BUSINESS,
    "social": COLUMN_SOCIAL,
    "mededu": COLUMN_SOCIAL,
    "private_education": COLUMN_SOCIAL,
    "sport": COLUMN_SOCIAL,
    "culture": COLUMN_SOCIAL,
    "hotel": COLUMN_HOTEL,
}

# Пороги — пункты 3.1.1–3.1.3 Перечня и пункт 4.2 (гостиницы).
MIN_AREA_SQM: dict[str, float] = {
    "office": 5_000.0,        # п. 3.1.2
    "industrial": 2_000.0,    # п. 3.1.1
    "social": 2_000.0,        # п. 3.1.1
    "mededu": 2_000.0,        # п. 3.1.1
    "private_education": 2_000.0,
    "sport": 2_000.0,
    "culture": 2_000.0,
    "hotel": 3_000.0,         # п. 4.2
}
MIXED_USE_MIN_AREA_SQM = 5_000.0  # п. 3.1.3
HOTEL_ROOMS_MIN_SHARE = 0.75      # п. 4.2: номерной фонд не менее 75%

# Приложение 3. Значение графы печатается в PDF до конца списка, когда строка
# переносится через страницу; разбивка восстановлена по монотонности ряда —
# 0 в центре, 0,9 в ТиНАО, без единого исключения.
# «Красносельский» назван в постановлении дважды, в первой и второй строке;
# значения у них совпадают, поэтому на расчёт это не влияет.
KMEST_GROUPS: tuple[tuple[dict[str, float], tuple[str, ...]], ...] = (
    (
        {COLUMN_BUSINESS: 0.0, COLUMN_SOCIAL: 0.0, COLUMN_HOTEL: 0.5},
        ("Арбат", "Замоскворечье", "Красносельский", "Таганский", "Тверской", "Якиманка"),
    ),
    (
        {COLUMN_BUSINESS: 0.0, COLUMN_SOCIAL: 0.0, COLUMN_HOTEL: 0.5},
        ("Аэропорт", "Басманный", "Беговой", "Даниловский", "Донской", "Дорогомилово",
         "Лефортово", "Марьина Роща", "Мещанский", "Нагатино-Садовники", "Нижегородский",
         "Пресненский", "Савеловский", "Соколиная Гора", "Сокольники", "Хамовники",
         "Хорошевский"),
    ),
    (
        {COLUMN_BUSINESS: 0.33, COLUMN_SOCIAL: 0.3, COLUMN_HOTEL: 0.5},
        ("Академический", "Алексеевский", "Бутырский", "Войковский", "Гагаринский",
         "Капотня", "Останкинский", "Печатники", "Покровское-Стрешнево",
         "Преображенское", "Ростокино", "Сокол", "Черемушки", "Южнопортовый"),
    ),
    (
        {COLUMN_BUSINESS: 0.5, COLUMN_SOCIAL: 0.3, COLUMN_HOTEL: 0.5},
        ("Внуково", "Головинский", "Дмитровский", "Западное Дегунино", "Измайлово",
         "Коньково", "Коптево", "Котловка", "Крылатское", "Кунцево", "Метрогородок",
         "Можайский", "Московский", "Москворечье-Сабурово", "Мосрентген", "Нагорный",
         "Обручевский", "Очаково-Матвеевское", "Перово", "Проспект Вернадского",
         "Раменки", "Савелки", "Свиблово", "Сосенское", "Текстильщики",
         "Тимирязевский", "Тропарево-Никулино", "Филевский Парк",
         "Чертаново Центральное", "Щукино", "Южное Тушино"),
    ),
    (
        {COLUMN_BUSINESS: 0.75, COLUMN_SOCIAL: 0.3, COLUMN_HOTEL: 0.5},
        ("Алтуфьевский", "Бабушкинский", "Бескудниковский", "Бибирево",
         "Бирюлево Восточное", "Бирюлево Западное", "Богородское", "Братеево",
         "Вешняки", "Восточное Дегунино", "Восточное Измайлово", "Восточный",
         "Выхино-Жулебино", "Гольяново", "Левобережный", "Зюзино", "Зябликово",
         "Ивановское", "Косино-Ухтомский", "Крюково", "Кузьминки", "Куркино",
         "Лианозово", "Ломоносовский", "Лосиноостровский", "Люблино", "Марфино",
         "Марьино", "Матушкино", "Митино", "Молжаниновский", "Нагатинский Затон",
         "Некрасовка", "Новогиреево", "Новокосино", "Ново-Переделкино", "Отрадное",
         "Орехово-Борисово Северное", "Орехово-Борисово Южное", "Рязанский",
         "Северное Бутово", "Северное Измайлово", "Северное Медведково",
         "Северное Тушино", "Северный", "Силино", "Солнцево", "Старое Крюково",
         "Строгино", "Теплый Стан", "Фили-Давыдково", "Ховрино",
         "Хорошево-Мневники", "Царицыно", "Чертаново Северное", "Чертаново Южное",
         "Южное Бутово", "Южное Медведково", "Ярославский", "Ясенево"),
    ),
    (
        {COLUMN_BUSINESS: 0.9, COLUMN_SOCIAL: 0.3, COLUMN_HOTEL: 0.5},
        ("Внуковское", "Воскресенское", "Вороновское", "Десеновское",
         "Краснопахорское", "Киевский", "Кленовское", "Кокошкино", "Марушкинское",
         "Михайлово-Ярцевское", "Новофедоровское", "Первомайское", "Роговское",
         "Рязановское", "Троицк", "Филимонковское", "Щаповское", "Щербинка"),
    ),
)

# Прежняя версия называла поселения ТиНАО по-district'ному. Сохранённый проект
# с такими именами не должен падать — но и молча считаться по другой строке
# таблицы тоже: имена сведены к постановлению, расхождение попадает в ответ.
LEGACY_DISTRICT_ALIASES: dict[str, str] = {
    "Вороново": "Вороновское",
    "Краснопахорский": "Краснопахорское",
    "Филимонковский": "Филимонковское",
}


class MptCalculationError(ValueError):
    pass


@dataclass(frozen=True)
class MptInput:
    category: Category
    district: str
    area_sqm: float
    mode: Mode = "new"
    ttk_position: TtkPosition | None = None
    parking_sqm: float = 0.0
    garages_sqm: float = 0.0
    warehouse_inside_sqm: float = 0.0
    warehouse_yard_sqm: float = 0.0
    hotel_rooms_sqm: float = 0.0
    # Примечание к таблице приложения 3: если назначение соответствует
    # нескольким ВРИ из граф 2 и 3, коэффициенты применяются пропорционально
    # площади с соответствующим видом использования. Пусто — весь объект идёт
    # по графе выбранной категории.
    area_business_sqm: float = 0.0
    area_social_sqm: float = 0.0
    kzatr: float = KZATR_DEFAULT
    kzatr_quarter: str = ""
    # Переходное положение приказа от 10.03.2026: по соглашению, заключённому
    # до его вступления в силу, коэффициент не индексируется поквартально.
    # Прирост площади — исключение, к нему индексация применяется.
    kzatr_fixed_by_agreement: bool = False
    ons_readiness_pct: float = 0.0
    ons_registered_before_2019_11_01: bool | None = None


@dataclass(frozen=True)
class MptResult:
    benefit_rub: float
    # Что дала бы формула, будь условия соблюдены. Нужно, чтобы отказ читался
    # как отказ, а не как поломка расчёта.
    potential_benefit_rub: float
    eligible_area_sqm: float
    excluded_area_sqm: float
    warehouse_counted_sqm: float
    warehouse_excluded_sqm: float
    kmest: float
    kmest_source: str
    kmest_column: str
    kmest_mix: tuple[tuple[str, float, float], ...]
    kzatr: float
    kzatr_quarter: str
    readiness_factor: float
    minimum_area_sqm: float
    eligible_for_minimum: bool
    eligible_for_status: bool
    blockers: tuple[str, ...]
    warnings: tuple[str, ...]
    formula: str
    normative_snapshot: str
    calculation_date: str

    def as_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["warnings"] = list(self.warnings)
        payload["blockers"] = list(self.blockers)
        payload["kmest_mix"] = [
            {"column": column, "area_sqm": area, "kmest": value}
            for column, area, value in self.kmest_mix
        ]
        return payload


def _district_key(name: str) -> str:
    return " ".join(str(name or "").replace("ё", "е").lower().split())


_DISTRICT_GROUP: dict[str, int] = {}
_DISTRICT_CANONICAL: dict[str, str] = {}
for _index, (_values, _names) in enumerate(KMEST_GROUPS):
    for _name in _names:
        _DISTRICT_CANONICAL.setdefault(_district_key(_name), _name)
        _DISTRICT_GROUP.setdefault(_district_key(_name), _index)
for _legacy, _actual in LEGACY_DISTRICT_ALIASES.items():
    _DISTRICT_CANONICAL[_district_key(_legacy)] = _actual
    _DISTRICT_GROUP[_district_key(_legacy)] = _DISTRICT_GROUP[_district_key(_actual)]

ALL_DISTRICTS: tuple[str, ...] = tuple(
    sorted({name for _values, names in KMEST_GROUPS for name in names})
)


def canonical_district(name: str) -> str:
    district = _DISTRICT_CANONICAL.get(_district_key(name))
    if not district:
        raise MptCalculationError(
            "Район не найден в приложении 3 к 1874-ПП. Проверьте название по таблице."
        )
    return district


def district_group(name: str) -> int:
    return _DISTRICT_GROUP[_district_key(canonical_district(name))]


def kmest_for(category: str, district: str) -> tuple[float, str, str]:
    if category not in CATEGORY_LABELS:
        raise MptCalculationError("Неизвестная категория МПТ.")
    canonical = canonical_district(district)
    group = district_group(canonical)
    column = CATEGORY_COLUMN[category]
    value = float(KMEST_GROUPS[group][0][column])
    graph = {COLUMN_BUSINESS: 2, COLUMN_SOCIAL: 3, COLUMN_HOTEL: 4}[column]
    return value, f"Приложение 3, графа {graph}, строка {group + 1}: {canonical}", column


def _thousands(value: float) -> str:
    return f"{value:,.0f}".replace(",", " ")


def _finite(label: str, value: float) -> float:
    value = float(value)
    # NaN не меньше нуля и не больше — любое сравнение с ним ложно, поэтому
    # проверка «< 0» его пропускала, а бесконечность проходила как обычное
    # число. Дальше расчёт давал nan/inf, и FastAPI отдавал его как null.
    if not math.isfinite(value):
        raise MptCalculationError(f"{label} должна быть числом.")
    if value < 0:
        raise MptCalculationError(f"{label} не может быть отрицательной.")
    return value


def calculate_mpt_benefit(data: MptInput, *, today: date | None = None) -> MptResult:
    today = today or date.today()
    category = str(data.category)
    if category not in CATEGORY_LABELS:
        raise MptCalculationError("Неизвестная категория МПТ.")
    if data.mode not in {"new", "reconstruction", "ons"}:
        raise MptCalculationError("Неизвестный сценарий расчёта.")

    area = _finite("Площадь МПТ", data.area_sqm)
    if area <= 0:
        raise MptCalculationError("Площадь МПТ должна быть больше нуля.")
    parking = _finite("Площадь парковок", data.parking_sqm)
    garages = _finite("Площадь гаражей", data.garages_sqm)
    warehouse = _finite("Площадь склада внутри здания", data.warehouse_inside_sqm)
    yard = _finite("Площадь открытой складской площадки", data.warehouse_yard_sqm)
    rooms = _finite("Площадь номерного фонда", data.hotel_rooms_sqm)
    part_business = _finite("Площадь по графе 2", data.area_business_sqm)
    part_social = _finite("Площадь по графе 3", data.area_social_sqm)
    kzatr = _finite("Кзатр", data.kzatr)
    if kzatr <= 0:
        raise MptCalculationError("Кзатр должен быть больше нуля.")

    kmest, kmest_source, column = kmest_for(category, data.district)

    # Пропорция по примечанию к таблице приложения 3.
    split = part_business > 0 or part_social > 0
    if split:
        if category == "hotel":
            raise MptCalculationError(
                "Гостиница — отдельная графа 4; распределять её площадь между "
                "графами 2 и 3 постановление не предусматривает."
            )
        if abs(part_business + part_social - area) > 0.5:
            raise MptCalculationError(
                f"Сумма площадей по графам ({part_business + part_social:.0f} м²) "
                f"не совпадает с общей площадью ({area:.0f} м²)."
            )

    warnings: list[str] = []
    blockers: list[str] = []
    warehouse_counted = 0.0
    if category == "industrial":
        # Графа 2 прямо исключает склады и складские площадки из
        # производственного вида разрешённого использования.
        warehouse_counted = min(warehouse, area * 0.25)
        warehouse_excluded = max(warehouse - warehouse_counted, 0.0)
        eligible_area = area - parking - garages - yard - warehouse_excluded
        if warehouse > area * 0.25:
            warnings.append(
                "Склад внутри здания превышает 25% базовой площади: превышение исключено из Sмпт."
            )
        warnings.append(
            "Приложение 3 исключает склады и складские площадки из производственного "
            "вида разрешённого использования; долю склада нужно подтвердить экспликацией."
        )
    elif category == "hotel":
        warehouse_excluded = 0.0
        eligible_area = area - parking - garages
        if warehouse or yard:
            warnings.append(
                "Для гостиницы склад и открытая складская площадка не вычитаются "
                "автоматически: базовая площадь должна включать только помещения, "
                "допустимые требованиями к типу и категории средства размещения."
            )
    else:
        warehouse_excluded = warehouse
        eligible_area = area - parking - garages - warehouse - yard

    components = parking + garages if category == "hotel" else parking + garages + warehouse + yard
    if components > area:
        warnings.append("Сумма исключаемых компонент превышает базовую площадь — проверьте ТЭП.")
    eligible_area = max(eligible_area, 0.0)
    excluded_area = max(area - eligible_area, 0.0)

    # --- условия присвоения статуса ------------------------------------------
    # ТТК в постановлении не коэффициент, а условие: п. 1.2 и 3.5 требуют, чтобы
    # МПТ располагался за внешними границами ТТК; исключение — гостиницы.
    # Прежняя версия трактовала его как множитель Кмест и спрашивала только у
    # двух категорий в одной группе районов.
    if category != "hotel":
        if data.ttk_position not in {"inside", "outside"}:
            raise MptCalculationError(
                "Укажите положение участка относительно ТТК: статус присваивается "
                "только за внешними границами Третьего транспортного кольца (п. 1.2)."
            )
        if data.ttk_position == "inside":
            blockers.append(
                "Участок внутри ТТК: статус МПТ не присваивается (п. 1.2, п. 3.5). "
                "Исключение сделано только для гостиниц."
            )

    mixed = split and part_business > 0 and part_social > 0
    minimum = MIXED_USE_MIN_AREA_SQM if mixed else MIN_AREA_SQM[category]
    meets_minimum = eligible_area >= minimum
    if not meets_minimum:
        blockers.append(
            f"Sмпт {_thousands(eligible_area)} м² ниже минимума "
            f"{_thousands(minimum)} м² (п. 3.1): статус не присваивается."
        )

    if category == "hotel":
        share = rooms / eligible_area if eligible_area else 0.0
        if rooms <= 0:
            warnings.append(
                "Не задана площадь номерного фонда: п. 4.2 требует не менее 75% "
                "общей площади гостиницы — условие не проверено."
            )
        elif share < HOTEL_ROOMS_MIN_SHARE:
            blockers.append(
                f"Номерной фонд {share * 100:.1f}% от площади гостиницы при минимуме "
                "75% (п. 4.2): статус не присваивается."
            )

    readiness_factor = 1.0
    if data.mode == "ons":
        readiness = float(data.ons_readiness_pct)
        if not math.isfinite(readiness) or not 0 <= readiness < 100:
            raise MptCalculationError("Готовность ОНС должна быть от 0 до 99,99%.")
        if data.ons_registered_before_2019_11_01 is not True:
            raise MptCalculationError(
                "Льгота по п. 1.14.2 применяется к ОНС, права на которые "
                "зарегистрированы до 1 ноября 2019 г. включительно."
            )
        readiness_factor = 1.0 - readiness / 100.0

    if data.mode == "reconstruction":
        warnings.append(
            "При реконструкции Sмпт — прирост общей площади к первоначальной "
            "(п. 1.14.1), а не полная площадь объекта."
        )
    if kmest == 0:
        warnings.append("Кмест = 0 по приложению 3: расчётная льгота равна нулю.")
    current_quarter = quarter_of(today)
    stated_quarter = str(data.kzatr_quarter or "").strip()
    if data.kzatr_fixed_by_agreement:
        # Индексации нет — сверять квартал не с чем, ругаться не на что.
        warnings.append(
            f"Кзатр {kzatr:g} принят зафиксированным по ранее заключённому "
            f"соглашению. {KZATR_TRANSITION}"
        )
    elif not quarter_is_indexed(stated_quarter or current_quarter):
        # До второго квартала 2026 года значение установлено приказом прямо.
        pass
    elif not stated_quarter:
        warnings.append(
            f"Кзатр {kzatr:g} принят без указания квартала. Базовое значение "
            f"{KZATR_BASE} установлено с 01.01.2026, а со второго квартала "
            f"2026 года корректируется каждый квартал на индекс стоимости "
            f"строительства к {KZATR_INDEX_BASE_TO} (приказ ДИиПП от "
            f"10.03.2026); сейчас {current_quarter} — сверьте действующее значение."
        )
    elif stated_quarter != current_quarter:
        warnings.append(
            f"Кзатр относится к {stated_quarter}, а сейчас {current_quarter}: "
            "с первого числа каждого квартала коэффициент пересматривается."
        )

    kmest_mix: tuple[tuple[str, float, float], ...] = ()
    if split and area > 0:
        # Исключения (парковки, гаражи, склад) снимаются пропорционально: какая
        # часть площади к какой графе относится, постановление берёт по ВРИ, а
        # не по тому, где именно стоит парковка.
        scale = eligible_area / area
        business_area = part_business * scale
        social_area = part_social * scale
        k_business = kmest_for("office", data.district)[0]
        k_social = kmest_for("sport", data.district)[0]
        weighted_sum = business_area * k_business + social_area * k_social
        kmest = weighted_sum / eligible_area if eligible_area else 0.0
        kmest_mix = (
            (COLUMN_BUSINESS, business_area, k_business),
            (COLUMN_SOCIAL, social_area, k_social),
        )
        # Пробел как разделитель тысяч ставится в самих числах: глобальный
        # `replace(",", " ")` съедал бы и запятые предложения.
        kmest_source = (
            f"Приложение 3, примечание: графа 2 — {_thousands(business_area)} м² × "
            f"{k_business}, графа 3 — {_thousands(social_area)} м² × {k_social}"
        )
        if mixed:
            warnings.append(
                "Назначение по нескольким ВРИ из граф 2 и 3: коэффициенты применены "
                "пропорционально площади (примечание к таблице приложения 3), порог — 5 000 м²."
            )
        if category == "industrial":
            warnings.append(
                "Послабление по складу в пределах 25% рассчитано для чисто "
                "производственного объекта; при смешанном назначении долю склада "
                "подтверждайте экспликацией."
            )

    potential = 1000.0 * eligible_area * readiness_factor * kzatr * kmest
    eligible_for_status = not blockers
    benefit = potential if eligible_for_status else 0.0

    pieces = ["1 000", f"{eligible_area:.2f}"]
    if data.mode == "ons":
        pieces.append(f"{readiness_factor:.6f}")
    pieces.extend([f"{kzatr:.5f}", f"{kmest:.2f}"])
    formula = " × ".join(pieces) + f" = {potential:.2f} ₽"
    if not eligible_for_status:
        formula += " → 0,00 ₽: условия присвоения статуса не выполнены"

    return MptResult(
        benefit_rub=benefit,
        potential_benefit_rub=potential,
        eligible_area_sqm=eligible_area,
        excluded_area_sqm=excluded_area,
        warehouse_counted_sqm=warehouse_counted,
        warehouse_excluded_sqm=warehouse_excluded,
        kmest=kmest,
        kmest_source=kmest_source,
        kmest_column=column,
        kmest_mix=kmest_mix,
        kzatr=kzatr,
        kzatr_quarter=stated_quarter or current_quarter,
        readiness_factor=readiness_factor,
        minimum_area_sqm=minimum,
        eligible_for_minimum=meets_minimum,
        eligible_for_status=eligible_for_status,
        blockers=tuple(blockers),
        warnings=tuple(warnings),
        formula=formula,
        normative_snapshot=NORMATIVE_SNAPSHOT,
        calculation_date=today.isoformat(),
    )


def metadata() -> dict[str, Any]:
    today_quarter = quarter_of(date.today())
    current_kzatr = kzatr_for_quarter(today_quarter)
    source = KZATR_SOURCE
    if quarter_is_indexed(today_quarter):
        if current_kzatr is not None:
            source = (f"{KZATR_SOURCE}. Квартал {today_quarter}: "
                      f"{current_kzatr} = {KZATR_BASE} × "
                      f"{KZATR_INDICES_TO_DEC2025[today_quarter]} ({KZATR_INDICES_SOURCE})")
        else:
            source = (f"{KZATR_SOURCE}. Для квартала {today_quarter} индекс ещё "
                      f"не принесён — подставлено значение базы, требуется сверка")
    return {
        "categories": [{"value": key, "label": label, "column": CATEGORY_COLUMN[key]}
                       for key, label in CATEGORY_LABELS.items()],
        "districts": list(ALL_DISTRICTS),
        "kmest_groups": [
            {"values": values, "districts": list(names)} for values, names in KMEST_GROUPS
        ],
        "minimum_area_sqm": MIN_AREA_SQM,
        "mixed_use_minimum_sqm": MIXED_USE_MIN_AREA_SQM,
        "hotel_rooms_min_share": HOTEL_ROOMS_MIN_SHARE,
        "kzatr_default": current_kzatr if current_kzatr is not None else KZATR_DEFAULT,
        # Квартал, которому дефолт соответствует: страница подставляет его в
        # поле квартала, и расчёт не ругается «значение не сверено» зря.
        "kzatr_default_quarter": today_quarter if current_kzatr is not None else "",
        "kzatr_indices_to_dec2025": KZATR_INDICES_TO_DEC2025,
        "kzatr_indices_source": KZATR_INDICES_SOURCE,
        "kzatr_base": KZATR_BASE,
        "kzatr_base_from": KZATR_BASE_FROM.isoformat(),
        "kzatr_source": source,
        "kzatr_indexation_from_quarter": KZATR_INDEXATION_FROM_QUARTER,
        "kzatr_index_base_to": KZATR_INDEX_BASE_TO,
        "kzatr_transition": KZATR_TRANSITION,
        "current_quarter": quarter_of(date.today()),
        "ttk_required_outside": True,
        "normative_snapshot": NORMATIVE_SNAPSHOT,
    }
