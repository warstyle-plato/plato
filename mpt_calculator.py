"""Moscow MPT benefit calculator under PP Moscow No. 1874-PP.

The module is intentionally isolated from the development/VRI financial engine.
It calculates only the *potential MPT benefit amount* created by an MPT object.
Applying that benefit to a particular VRI/lease payment is a separate future step.

Normative snapshot: rules and coefficients verified for 2026-08-08.
"""

from __future__ import annotations

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

KZATR_2026 = 166.23078
KZATR_EFFECTIVE_FROM = date(2026, 1, 1)
NORMATIVE_YEAR = 2026
NORMATIVE_SNAPSHOT = "ПП Москвы № 1874-ПП · приложение 3 · Кзатр 166,23078 · 08.08.2026"

CATEGORY_LABELS: dict[str, str] = {
    "office": "Офис / деловое управление / банк / наука / торговля / общепит / развлечения",
    "industrial": "Light Industrial / промышленно-производственный МПТ",
    "social": "Соцобслуживание / бытовое обслуживание / стационарная медицина",
    "hotel": "Гостиница / средство размещения / санаторий",
    "mededu": "Амбулаторная медицина / образование и просвещение",
    "private_education": "Образование — специальная категория частной собственности",
    "sport": "Спорт",
    "culture": "Культурное развитие",
}

MIN_AREA_SQM: dict[str, float] = {
    "office": 5_000.0,
    "industrial": 2_000.0,
    "social": 2_000.0,
    "hotel": 3_000.0,
    "mededu": 2_000.0,
    "private_education": 2_000.0,
    "sport": 2_000.0,
    "culture": 2_000.0,
}

GROUP_1 = {
    "Арбат",
    "Замоскворечье",
    "Тверской",
    "Якиманка",
}

GROUP_2 = {
    "Алексеевский",
    "Аэропорт",
    "Басманный",
    "Беговой",
    "Гагаринский",
    "Даниловский",
    "Донской",
    "Дорогомилово",
    "Красносельский",
    "Лефортово",
    "Марьина Роща",
    "Мещанский",
    "Нижегородский",
    "Печатники",
    "Пресненский",
    "Раменки",
    "Савеловский",
    "Сокольники",
    "Таганский",
    "Хамовники",
    "Хорошевский",
    "Южнопортовый",
}

GROUP_3 = {
    "Академический",
    "Алтуфьевский",
    "Бабушкинский",
    "Бекасово",
    "Бескудниковский",
    "Бибирево",
    "Бирюлево Восточное",
    "Бирюлево Западное",
    "Богородское",
    "Братеево",
    "Бутырский",
    "Вешняки",
    "Внуково",
    "Войковский",
    "Вороново",
    "Восточное Дегунино",
    "Восточное Измайлово",
    "Восточный",
    "Выхино-Жулебино",
    "Головинский",
    "Гольяново",
    "Дмитровский",
    "Западное Дегунино",
    "Зюзино",
    "Зябликово",
    "Ивановское",
    "Измайлово",
    "Капотня",
    "Коммунарка",
    "Коньково",
    "Коптево",
    "Косино-Ухтомский",
    "Котловка",
    "Краснопахорский",
    "Крылатское",
    "Крюково",
    "Кузьминки",
    "Кунцево",
    "Куркино",
    "Левобережный",
    "Лианозово",
    "Ломоносовский",
    "Лосиноостровский",
    "Люблино",
    "Марфино",
    "Марьино",
    "Матушкино",
    "Метрогородок",
    "Митино",
    "Можайский",
    "Молжаниновский",
    "Москворечье-Сабурово",
    "Нагатино-Садовники",
    "Нагатинский Затон",
    "Нагорный",
    "Некрасовка",
    "Новогиреево",
    "Новокосино",
    "Ново-Переделкино",
    "Обручевский",
    "Орехово-Борисово Северное",
    "Орехово-Борисово Южное",
    "Останкинский",
    "Отрадное",
    "Очаково-Матвеевское",
    "Перово",
    "Покровское-Стрешнево",
    "Преображенское",
    "Проспект Вернадского",
    "Ростокино",
    "Рязанский",
    "Савелки",
    "Свиблово",
    "Северное Бутово",
    "Северное Измайлово",
    "Северное Медведково",
    "Северное Тушино",
    "Северный",
    "Силино",
    "Сокол",
    "Соколиная Гора",
    "Солнцево",
    "Старое Крюково",
    "Строгино",
    "Текстильщики",
    "Теплый Стан",
    "Тимирязевский",
    "Троицк",
    "Тропарево-Никулино",
    "Филевский Парк",
    "Фили-Давыдково",
    "Филимонковский",
    "Ховрино",
    "Хорошево-Мневники",
    "Царицыно",
    "Черемушки",
    "Чертаново Северное",
    "Чертаново Центральное",
    "Чертаново Южное",
    "Щербинка",
    "Щукино",
    "Южное Бутово",
    "Южное Медведково",
    "Южное Тушино",
    "Ярославский",
    "Ясенево",
}

# Appendix 3, table 2. Current table applies to the office/business category.
SPECIAL_OFFICE_QUARTERS = {
    "77:02:0007002", "77:02:0007003", "77:02:0009001", "77:02:0009002", "77:02:0009003",
    "77:02:0009004", "77:02:0017001", "77:03:0004009", "77:03:0004010", "77:03:0004011",
    "77:03:0005025", "77:03:0006001", "77:03:0006002", "77:03:0006007", "77:03:0006008",
    "77:03:0006009", "77:03:0006026", "77:04:0001008", "77:04:0001010", "77:04:0001012",
    "77:04:0001013", "77:04:0001014", "77:04:0001015", "77:04:0001016", "77:04:0001017",
    "77:04:0001018", "77:04:0001019", "77:04:0001020", "77:04:0002001", "77:04:0002002",
    "77:04:0002003", "77:04:0002004", "77:04:0002020", "77:04:0003001", "77:04:0003002",
    "77:04:0003003", "77:04:0003004", "77:04:0003005", "77:04:0003006", "77:05:0005006",
    "77:05:0005008", "77:05:0006001", "77:05:0006004", "77:05:0006005", "77:05:0007002",
    "77:05:0007003", "77:05:0007004", "77:05:0008001", "77:05:0009001", "77:05:0009004",
    "77:05:0009005", "77:05:0010001", "77:07:0002003", "77:07:0012002", "77:07:0012004",
    "77:07:0012005", "77:07:0012006", "77:07:0012007", "77:07:0012008", "77:07:0014001",
    "77:07:0014002", "77:09:0001015", "77:09:0001027", "77:09:0001028", "77:09:0001029",
    "77:09:0002025", "77:09:0002029", "77:09:0002030", "77:09:0002031", "77:09:0003024",
    "77:09:0003025", "77:09:0003026", "77:16:0010105", "77:16:0060101", "77:08:0010013",
    "77:08:0010015", "77:08:0012001", "77:08:0012002", "77:08:0012003", "77:08:0012004",
    "77:08:0012005", "77:09:0005005", "77:09:0005009", "77:09:0005010", "77:09:0005011",
    "77:09:0005012", "77:09:0005013", "77:09:0005016", "77:17:0120303", "77:17:0130206",
    "77:17:0120316", "77:17:0120106", "77:17:0120305", "77:09:0005008", "77:09:0005014",
    "77:01:0004034", "77:01:0004040", "77:01:0004041", "77:01:0004042",
}

_TABLE_1: dict[int, dict[str, float | None]] = {
    1: {
        "office": 0.0,
        "industrial": 0.0,
        "social": 0.3,
        "hotel": 0.5,
        "mededu": 0.3,
        "private_education": 0.8,
        "sport": 0.8,
        "culture": 0.8,
    },
    2: {
        "office": None,  # 0 inside TTK / 0.7 outside
        "industrial": None,  # 0 inside TTK / 0.8 outside
        "social": 0.3,
        "hotel": 0.5,
        "mededu": 0.3,
        "private_education": 0.8,
        "sport": 0.8,
        "culture": 0.8,
    },
    3: {
        "office": 0.7,
        "industrial": 0.8,
        "social": 0.3,
        "hotel": 0.5,
        "mededu": 0.3,
        "private_education": 0.8,
        "sport": 0.8,
        "culture": 0.8,
    },
}


class MptCalculationError(ValueError):
    pass


@dataclass(frozen=True)
class MptInput:
    category: Category
    district: str
    area_sqm: float
    mode: Mode = "new"
    cadastral_number: str = ""
    ttk_position: TtkPosition | None = None
    parking_sqm: float = 0.0
    garages_sqm: float = 0.0
    warehouse_inside_sqm: float = 0.0
    warehouse_yard_sqm: float = 0.0
    kterm: float = 1.0
    ons_readiness_pct: float = 0.0
    ons_registered_before_2019_11_01: bool | None = None


@dataclass(frozen=True)
class MptResult:
    benefit_rub: float
    eligible_area_sqm: float
    excluded_area_sqm: float
    warehouse_counted_sqm: float
    warehouse_excluded_sqm: float
    kmest: float
    kmest_source: str
    kzatr: float
    kterm: float
    readiness_factor: float
    minimum_area_sqm: float
    eligible_for_minimum: bool
    warnings: tuple[str, ...]
    formula: str
    normative_snapshot: str
    calculation_date: str

    def as_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["warnings"] = list(self.warnings)
        return payload


def _district_key(name: str) -> str:
    return " ".join(str(name or "").replace("ё", "е").lower().split())


_DISTRICT_CANONICAL = {
    _district_key(item): item
    for item in sorted(GROUP_1 | GROUP_2 | GROUP_3)
}


def canonical_district(name: str) -> str:
    district = _DISTRICT_CANONICAL.get(_district_key(name))
    if not district:
        raise MptCalculationError("Район Москвы не найден в действующей таблице Кмест.")
    return district


def district_group(name: str) -> int:
    district = canonical_district(name)
    if district in GROUP_1:
        return 1
    if district in GROUP_2:
        return 2
    return 3


def cadastral_quarter(value: str) -> str:
    parts = [part.strip() for part in str(value or "").strip().split(":")]
    if len(parts) < 3:
        return ""
    return ":".join(parts[:3])


def needs_ttk(category: str, district: str, cadastral_number: str = "") -> bool:
    if category == "office" and cadastral_quarter(cadastral_number) in SPECIAL_OFFICE_QUARTERS:
        return False
    return district_group(district) == 2 and category in {"office", "industrial"}


def kmest_for(
    category: str,
    district: str,
    *,
    ttk_position: str | None = None,
    cadastral_number: str = "",
) -> tuple[float, str]:
    if category not in CATEGORY_LABELS:
        raise MptCalculationError("Неизвестная категория МПТ.")

    group = district_group(district)
    quarter = cadastral_quarter(cadastral_number)
    if category == "office" and quarter in SPECIAL_OFFICE_QUARTERS:
        return 0.8, f"Приложение 3, таблица 2: кадастровый квартал {quarter}"

    if group == 2 and category in {"office", "industrial"}:
        if ttk_position not in {"inside", "outside"}:
            raise MptCalculationError(
                "Для выбранного района и типа МПТ нужно указать положение относительно ТТК."
            )
        if ttk_position == "inside":
            return 0.0, "Приложение 3, таблица 1: внутри ТТК"
        return (
            (0.7 if category == "office" else 0.8),
            "Приложение 3, таблица 1: за внешней границей ТТК",
        )

    value = _TABLE_1[group][category]
    if value is None:
        raise MptCalculationError("Кмест не определён без положения относительно ТТК.")
    return float(value), f"Приложение 3, таблица 1: группа районов {group}"


def _validate_non_negative(label: str, value: float) -> float:
    value = float(value)
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
    if float(data.kterm) not in {1.0, 1.05, 1.1}:
        raise MptCalculationError("Ксрок должен быть 1,00, 1,05 или 1,10.")

    area = _validate_non_negative("Площадь МПТ", data.area_sqm)
    if area <= 0:
        raise MptCalculationError("Площадь МПТ должна быть больше нуля.")
    parking = _validate_non_negative("Площадь парковок", data.parking_sqm)
    garages = _validate_non_negative("Площадь гаражей", data.garages_sqm)
    warehouse = _validate_non_negative("Площадь склада внутри здания", data.warehouse_inside_sqm)
    yard = _validate_non_negative("Площадь открытой складской площадки", data.warehouse_yard_sqm)

    kmest, kmest_source = kmest_for(
        category,
        data.district,
        ttk_position=data.ttk_position,
        cadastral_number=data.cadastral_number,
    )

    warnings: list[str] = []
    warehouse_counted = 0.0
    if category == "industrial":
        warehouse_counted = min(warehouse, area * 0.25)
        warehouse_excluded = max(warehouse - warehouse_counted, 0.0)
        eligible_area = area - parking - garages - yard - warehouse_excluded
        if warehouse > area * 0.25:
            warnings.append(
                "Склад внутри здания превышает 25% базовой площади: превышение исключено из Sмпт."
            )
        warnings.append(
            "Light Industrial считается как промышленно-производственный МПТ; "
            "нужно подтвердить производственный ВРИ и профильную деятельность."
        )
    else:
        warehouse_excluded = warehouse
        eligible_area = area - parking - garages - warehouse - yard

    if parking + garages + warehouse + yard > area:
        warnings.append("Сумма компонент площади превышает базовую площадь — проверьте ТЭП.")
    eligible_area = max(eligible_area, 0.0)
    excluded_area = max(area - eligible_area, 0.0)

    readiness_factor = 1.0
    if data.mode == "ons":
        readiness = float(data.ons_readiness_pct)
        if not 0 <= readiness < 100:
            raise MptCalculationError("Готовность ОНС должна быть от 0 до 99,99%.")
        if data.ons_registered_before_2019_11_01 is not True:
            raise MptCalculationError(
                "Для ОНС нужно подтвердить регистрацию права не позднее 01.11.2019 включительно."
            )
        readiness_factor = 1.0 - readiness / 100.0

    minimum = MIN_AREA_SQM[category]
    meets_minimum = eligible_area >= minimum
    if not meets_minimum:
        warnings.append(
            f"Sмпт {eligible_area:,.0f} м² ниже минимального порога {minimum:,.0f} м²."
            .replace(",", " ")
        )
    if kmest == 0:
        warnings.append("Кмест = 0: расчётная льгота равна нулю.")
    if today.year != NORMATIVE_YEAR:
        warnings.append(
            f"Нормативный справочник Кзатр загружен для {NORMATIVE_YEAR} года; "
            "перед использованием расчёта обновите коэффициент."
        )

    benefit = (
        1000.0
        * eligible_area
        * readiness_factor
        * KZATR_2026
        * kmest
        * float(data.kterm)
    )
    pieces = [
        "1 000",
        f"{eligible_area:.2f}",
    ]
    if data.mode == "ons":
        pieces.append(f"{readiness_factor:.6f}")
    pieces.extend([f"{KZATR_2026:.5f}", f"{kmest:.2f}", f"{float(data.kterm):.2f}"])
    formula = " × ".join(pieces) + f" = {benefit:.2f} ₽"

    return MptResult(
        benefit_rub=benefit,
        eligible_area_sqm=eligible_area,
        excluded_area_sqm=excluded_area,
        warehouse_counted_sqm=warehouse_counted,
        warehouse_excluded_sqm=warehouse_excluded,
        kmest=kmest,
        kmest_source=kmest_source,
        kzatr=KZATR_2026,
        kterm=float(data.kterm),
        readiness_factor=readiness_factor,
        minimum_area_sqm=minimum,
        eligible_for_minimum=meets_minimum,
        warnings=tuple(warnings),
        formula=formula,
        normative_snapshot=NORMATIVE_SNAPSHOT,
        calculation_date=today.isoformat(),
    )


def metadata() -> dict[str, Any]:
    return {
        "categories": [{"value": key, "label": label} for key, label in CATEGORY_LABELS.items()],
        "districts": sorted(GROUP_1 | GROUP_2 | GROUP_3),
        "group_2_districts": sorted(GROUP_2),
        "ttk_categories": ["office", "industrial"],
        "special_office_quarters": len(SPECIAL_OFFICE_QUARTERS),
        "kzatr": KZATR_2026,
        "kzatr_effective_from": KZATR_EFFECTIVE_FROM.isoformat(),
        "normative_snapshot": NORMATIVE_SNAPSHOT,
    }
