"""Нормативная потребность в машино-местах — один модуль на весь продукт.

Формула нормы жила четырьмя копиями в трёх файлах: зеркало калькулятора
ГлавАПУ, наш расчёт по закону, быстрый пресет бота и пресет КРТ. Копии
разошлись ещё до того, как их сравнили: у пресета КРТ не было ни К1, ни К2, у
бота К1 принят единицей, а в Московской области нежилые объекты не порождали
мест вовсе. Так же однажды разошлись ставка ПФ и профиль управления — правило
то же: **норма объявляется один раз**.

Что этот модуль НЕ делает:

- не считает постоянные места жителей (приложение 5 к 945-ПП в редакции
  2118-ПП живёт в `moscow_permanent_parking_2118`) и не трогает гостевые;
- не воспроизводит штатный калькулятор ГлавАПУ. Зеркало калькулятора —
  отдельная вещь с отдельной задачей: оно обязано отдавать то, что отдал бы
  город, даже если город считает не по действующей редакции. Свести их к
  одному числу значит потерять фолбэк;
- не превращает площадь в квадратные метры паркинга. Норматив обеспеченности
  и строительная площадь на одно место — разные величины, и связывать их здесь
  нельзя: у DevelopAid для этого свои поля (`underground_area_per_space_sqm`,
  `above_parking_area_per_space_sqm`).

Что он делает: по функции объекта, его метрам (или местам, или номерам) и
юрисдикции возвращает нормативную потребность **вместе с её основанием** —
каким документом, в какой редакции, по какой расчётной единице, с какими
коэффициентами и какими допущениями. Число без основания в споре с городом
стоит ноль.

## О подтверждённости

У части строк текста акта на руках нет. Такие строки помечены
`source_confirmed: False`, и любой ответ, построенный на них, несёт это в
`assumptions`. Молчащее неподтверждённое число неотличимо от проверенного —
это правило проекта, а не осторожность.
"""

from __future__ import annotations

import math
from typing import Any


MOSCOW = "moscow"
MOSCOW_OBLAST = "moscow_oblast"

# Расчётная единица — часть норматива, а не подробность. «Площадь» без
# указания какая читается как другая величина: между СПП и наземной нежилой
# десять процентов метров при тех же исходных.
UNIT_SPP_SQM = "spp_sqm"                 # суммарная поэтажная площадь
UNIT_ABOVE_NONRES_SQM = "above_ground_nonresidential_area_sqm"
UNIT_TOTAL_AREA_SQM = "total_area_sqm"   # общая площадь
UNIT_SEATS = "seats"                     # посадочные места
UNIT_HOTEL_ROOMS = "hotel_rooms"
UNIT_EMPLOYEES = "employees"

UNIT_LABELS = {
    UNIT_SPP_SQM: "м² суммарной поэтажной площади",
    UNIT_ABOVE_NONRES_SQM: "м² нежилой наземной площади",
    UNIT_TOTAL_AREA_SQM: "м² общей площади",
    UNIT_SEATS: "посадочных мест",
    UNIT_HOTEL_ROOMS: "номеров",
    UNIT_EMPLOYEES: "работающих",
}


# --- Москва -----------------------------------------------------------------
# Приложение 6 к 945-ПП объявляет формулу, приложение 1 — таблицу расчётных
# единиц. Редакции лежат рядом и выбираются датой: норматив привязан к моменту,
# и затирать старую редакцию новой нельзя — по ней считали ранее выданные ГПЗУ.
MOSCOW_X2_EDITIONS: tuple[dict[str, Any], ...] = (
    {
        "id": "945pp_2015",
        "effective_from": "2016-01-01",
        "source": "945-ПП от 23.12.2015, приложение 1 (первоначальная редакция)",
        "source_confirmed": True,      # текст акта на руках, 24.08.2026
        "unit": UNIT_SPP_SQM,
        "x2": {
            "3.1": 110.0, "3.2": 440.0, "3.3": 110.0, "3.4": 330.0, "3.5": 440.0,
            "3.6": 220.0, "3.7": 220.0, "3.8": 220.0, "3.9": 220.0, "3.10": 330.0,
            "4.1": 60.0, "4.2": 60.0, "4.3": 60.0, "4.4": 70.0, "4.5": 70.0,
            "4.6": 60.0, "4.7": 330.0, "4.8": 330.0,
            "5.1": 220.0,
            "6.9": 550.0,
            "park": 2000.0, "recreation": 3000.0,
        },
    },
    {
        # Действующая редакция. Главное её отличие — не числа, а СНОСКА 2:
        # расчётной единицей строк «кв. м» объявлена НЕЖИЛАЯ НАЗЕМНАЯ ПЛОЩАДЬ.
        # В первоначальной редакции колонка называлась «суммарная поэтажная
        # площадь». Между ними десятая часть метров при тех же исходных, и
        # ошибка здесь не выглядит ошибкой.
        "id": "945pp_2579_2025",
        "effective_from": "2025-10-28",
        "source": ("945-ПП, приложение 1 в редакции 2579-ПП от 28.10.2025 "
                   "(«Вестник Москвы» № 61, том 2)"),
        "source_confirmed": True,
        "unit": UNIT_ABOVE_NONRES_SQM,
        "x2": {
            "3.1": 100.0, "3.2": 400.0, "3.3": 100.0, "3.4": 300.0, "3.5": 400.0,
            "3.6": 200.0, "3.7": 200.0, "3.8": 200.0, "3.9": 200.0, "3.10": 300.0,
            "4.1": 63.0, "4.2": 54.0, "4.3": 54.0, "4.4": 63.0, "4.5": 63.0,
            "4.6": 54.0, "4.7": 300.0, "4.8": 300.0,
            "5.1": 200.0, "5.2.1": 300.0,
            "6.9": 500.0,
            "park": 2000.0, "recreation": 3000.0,
        },
        # Строки с ДИАПАЗОНОМ и своей расчётной единицей. Переводить их в метры
        # нельзя: у производства единица — работающие, у вокзала — пассажиры в
        # час пик. Диапазон остаётся диапазоном по тому же правилу, что в МО.
        "ranges": {
            "6.0-6.12": {"unit": UNIT_EMPLOYEES, "per": 100.0, "min": 7.0, "max": 10.0,
                         "label": "Производственная деятельность (6.0–6.8, 6.10–6.12)"},
            "7.1.2": {"unit": "peak_passengers", "per": 1.0, "min": 8.0, "max": 10.0,
                      "label": "Обслуживание железнодорожных перевозок"},
            "7.2.2": {"unit": "peak_passengers", "per": 1.0, "min": 10.0, "max": 15.0,
                      "label": "Обслуживание перевозок пассажиров"},
            "7.3": {"unit": "peak_passengers", "per": 1.0, "min": 7.0, "max": 9.0,
                    "label": "Водный транспорт"},
            "7.4": {"unit": "peak_passengers", "per": 1.0, "min": 6.0, "max": 8.0,
                    "label": "Воздушный транспорт"},
            "8.4": {"unit": UNIT_EMPLOYEES, "per": 1.0, "min": 7.0, "max": 9.0,
                    "label": "Обеспечение деятельности по исполнению наказаний"},
        },
    },
)

# Наши имена функций — коды ВРИ. Читать «4.1» в отчёте нельзя, поэтому у
# каждой есть подпись, и она же связывает функцию с продуктом DevelopAid.
MOSCOW_FUNCTIONS: dict[str, dict[str, Any]] = {
    "office": {"vri": "4.1", "label": "Деловое управление (офисы)"},
    "mall": {"vri": "4.2", "label": "Торговый центр / ТРЦ"},
    "market": {"vri": "4.3", "label": "Рынки"},
    "shop": {"vri": "4.4", "label": "Магазины"},
    "bank": {"vri": "4.5", "label": "Банковская и страховая деятельность"},
    "catering": {"vri": "4.6", "label": "Общественное питание"},
    "hotel": {"vri": "4.7", "label": "Гостиничное обслуживание"},
    "entertainment": {"vri": "4.8", "label": "Развлечения"},
    "sport": {"vri": "5.1", "label": "Спорт"},
    "warehouse": {"vri": "6.9", "label": "Склады"},
    "tourism": {"vri": "5.2.1", "label": "Туристическое обслуживание"},
    "park": {"vri": "park", "label": "Городские парки"},
    "recreation": {"vri": "recreation", "label": "Зоны отдыха"},
    "healthcare": {"vri": "3.4", "label": "Здравоохранение"},
    "education": {"vri": "3.5", "label": "Образование и просвещение"},
    "culture": {"vri": "3.6", "label": "Культурное развитие"},
    "public_admin": {"vri": "3.8", "label": "Общественное управление"},
    "science": {"vri": "3.9", "label": "Обеспечение научной деятельности"},
    "utility": {"vri": "3.1", "label": "Коммунальное обслуживание"},
    "household": {"vri": "3.3", "label": "Бытовое обслуживание"},
}

# Встроенно-пристроенные нежилые помещения жилой застройки — своя норма, и она
# СВОЯ СТРОКА ДЕЙСТВУЮЩЕГО ПРИЛОЖЕНИЯ 6, а не строка приложения 1. Мы полгода
# считали её «практикой города, восстановленной по выгрузке», потому что в
# приложении 1 такой строки нет, а 63 из него давало на тех же метрах 22 вместо
# 15. Основание нашлось 24.08.2026: приложение 6 прямо устанавливает 90 кв. м
# нежилой наземной площади на одно место. Число не менялось — появилось
# основание, и это разные вещи.
MOSCOW_BUILT_IN_X2 = 90.0
MOSCOW_BUILT_IN_SOURCE = (
    "945-ПП, приложение 6: для встроенно-пристроенных нежилых помещений жилой "
    "застройки — 90 кв. м нежилой наземной площади на одно место")

# СВОЕЙ ТАБЛИЦЫ К2 ПО РАЙОНАМ У НАС НЕТ И НЕ БУДЕТ — решение владельца
# (24.08.2026): «ГлавАПУ всё верно посчитает без нас». Приложение 3 несёт 132
# строки, и второй справочник жил бы отдельной жизнью, а однажды разошёлся бы с
# городом — та же причина, по которой плату за ВРИ считает штатный калькулятор,
# а формулы остались фолбэком. К2 и К1 приходят из выгрузки; без выгрузки
# расчёт по Москве отказывается, и это честно: у такого участка нет ни ТЭП, ни
# коэффициентов. В Московской области коэффициентов не существует вовсе.
#
# Приложение 6 в действующей редакции: Nв = X / X2 × K1 × K2, где K1 —
# коэффициент пешей доступности рельсового каркаса, K2 — деловая активность
# района по приложению 3. Прежняя редакция 2015 года звала их K3 и K2 и брала
# базой суммарную поэтажную площадь — использовать её нельзя.
#
# Расстояние — по СУЩЕСТВУЮЩИМ И ПРОЕКТИРУЕМЫМ ПЕШЕХОДНЫМ путям от объекта до
# ближайшего входа на станцию. Радиусом от точки участка это не считается:
# полоса отвода, река и железная дорога радиусу не мешают, а человеку мешают.
#
# Примечание 3 приложения 6: «Округление числа мест производится до целого в
# большую сторону» — отсюда единственный ceil в самом конце.
MOSCOW_K1_STEPS: tuple[tuple[float, float, str], ...] = (
    (1200.0, 0.75, "менее 1200 м"),
    (2200.0, 0.90, "1200–2200 м"),
    (float("inf"), 1.00, "более 2200 м"),
)

# Примечания приложения 1: послабления для торговли. Распространять их на
# другие функции нельзя — это исключение, а не общее правило.
MOSCOW_TRADE_VRI = ("4.2", "4.4")
MOSCOW_TRADE_RELIEF_FROM = 450.0   # ННП, м² (редакция 2579-ПП)
MOSCOW_TRADE_RELIEF_TO = 900.0
MOSCOW_TRADE_RELIEF_FACTOR = 2.5
MOSCOW_TRADE_SKIP_BELOW = 450.0
MOSCOW_SPECIALTY_SHOP_FACTOR = 2.0


# --- Московская область -----------------------------------------------------
# Формулы «× К1 × К2» в области НЕТ. Снижения п. 5.12 (15% за пешеходные
# коммуникации и станцию, 10% за наземный транспорт) сформулированы ОТ ЖИЛОГО
# ДОМА, то есть про постоянное хранение жителей, и на приобъектную парковку
# офиса и ТЦ не переносятся. Московские коэффициенты сюда не переносятся тем
# более.
#
# Норматив области — диапазон, и это характеристика самого норматива. Среднее
# арифметическое из «1 место на 50–60 м²» — не норматив, а выдуманное число,
# которое выглядит нормативным.
MO_RULES: tuple[dict[str, Any], ...] = (
    {"function": "office", "label": "Коммерческо-деловые центры, офисные здания и помещения, страховые компании",
     "unit": UNIT_TOTAL_AREA_SQM, "min_denominator": 50.0, "max_denominator": 60.0},
    {"function": "mall", "label": "Торговые центры, комплексы, супермаркеты, универсамы, универмаги",
     "unit": UNIT_TOTAL_AREA_SQM, "min_denominator": 40.0, "max_denominator": 50.0},
    {"function": "hypermarket", "label": "Магазины-склады, гипермаркеты",
     "unit": UNIT_TOTAL_AREA_SQM, "min_denominator": 30.0, "max_denominator": 35.0},
    {"function": "specialty_shop", "label": "Специализированные магазины товаров эпизодического спроса",
     "unit": UNIT_TOTAL_AREA_SQM, "min_denominator": 60.0, "max_denominator": 70.0},
    {"function": "market_food", "label": "Рынки продовольственные и сельскохозяйственные",
     "unit": UNIT_TOTAL_AREA_SQM, "min_denominator": 40.0, "max_denominator": 50.0},
    {"function": "market", "label": "Рынки универсальные и непродовольственные",
     "unit": UNIT_TOTAL_AREA_SQM, "min_denominator": 30.0, "max_denominator": 40.0},
    {"function": "public_admin", "label": "Учреждения органов власти и местного самоуправления",
     "unit": UNIT_TOTAL_AREA_SQM, "min_denominator": 200.0, "max_denominator": 220.0},
    {"function": "admin", "label": "Административно-управленческие учреждения",
     "unit": UNIT_TOTAL_AREA_SQM, "min_denominator": 100.0, "max_denominator": 120.0},
    {"function": "bank", "label": "Банки с операционными залами",
     "unit": UNIT_TOTAL_AREA_SQM, "min_denominator": 30.0, "max_denominator": 35.0},
    {"function": "science", "label": "Научно-исследовательские и проектные институты",
     "unit": UNIT_TOTAL_AREA_SQM, "min_denominator": 140.0, "max_denominator": 170.0},
    # Расчётная единица здесь не метры вовсе — переводить общепит в м² нельзя.
    {"function": "catering", "label": "Рестораны, кафе, бары",
     "unit": UNIT_SEATS, "min_denominator": 4.0, "max_denominator": 5.0},
)
MO_RULES_SOURCE = (
    "СП 42.13330.2016, таблица Ж.1 (текст на руках); приложение № 10 к 713/30 "
    "не сверено")
MO_RULES_CONFIRMED = False

# А это — текст 774-ПП от 02.07.2026 дословно, и он подтверждён.
MO_FALLBACK_DENOMINATOR = 50.0
MO_FALLBACK_UNIT = UNIT_TOTAL_AREA_SQM
MO_FALLBACK_SOURCE = (
    "713/30, п. 5.12 в редакции 774-ПП от 02.07.2026: помещения различного "
    "назначения в нежилых зданиях, не являющихся торговыми и "
    "торгово-развлекательными комплексами, при отсутствии конкретной функции, "
    "а также встроенно-пристроенные нежилые помещения первых этажей жилой "
    "застройки — 1 место на 50 кв. м общей площади")
# ДОО и поликлиники правило 1/50 исключает прямым текстом.
MO_FALLBACK_EXCLUDED = ("kindergarten", "clinic")

DESIGN_MODE_MIN = "minimum"
DESIGN_MODE_MAX = "maximum"
DESIGN_MODE_MANUAL = "manual"
DESIGN_MODE_DEFAULT = DESIGN_MODE_MAX


def _number(value: Any) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return 0.0
    return result if result == result and abs(result) != float("inf") else 0.0


def moscow_k1(distance_m: Any) -> dict[str, Any]:
    """К1 по пешеходному расстоянию до входа на станцию рельсового каркаса."""
    distance = _number(distance_m)
    if distance <= 0:
        return {"value": None, "band": "", "reason": "расстояние до станции не задано"}
    for limit, value, band in MOSCOW_K1_STEPS:
        if distance < limit:
            return {"value": value, "band": band, "reason": ""}
    return {"value": 1.0, "band": MOSCOW_K1_STEPS[-1][2], "reason": ""}


def moscow_x2_edition(at: str = "") -> dict[str, Any]:
    """Редакция приложения 1 на дату. Пусто — последняя известная."""
    rows = sorted(MOSCOW_X2_EDITIONS, key=lambda row: str(row["effective_from"]))
    moment = str(at or "").strip()
    chosen = rows[-1]
    if moment:
        chosen = rows[0]
        for row in rows:
            if str(row["effective_from"]) <= moment:
                chosen = row
    return chosen


def moscow_x2(function: str, at: str = "") -> dict[str, Any]:
    """X2 функции: значение, единица, документ и подтверждён ли он.

    Редакция без нужной строки не выдумывает её и не берёт из соседней: она
    отступает на предыдущую редакцию и говорит об этом. Тихо подставленное
    число из другого документа — это и есть способ получить норматив, который
    выглядит нормативно и врёт.
    """
    meta = MOSCOW_FUNCTIONS.get(str(function or "").strip())
    if not meta:
        return {"x2": None,
                "reason": (f"функция «{function}» в приложении 1 не значится — по сноске 6 "
                           "число мест определяется заданием на проектирование")}
    vri = meta["vri"]
    editions = sorted(MOSCOW_X2_EDITIONS, key=lambda row: str(row["effective_from"]), reverse=True)
    active = moscow_x2_edition(at)
    ordered = [active] + [row for row in editions if row["id"] != active["id"]]
    for edition in ordered:
        value = (edition.get("x2") or {}).get(vri)
        if value:
            note = ""
            if edition["id"] != active["id"]:
                note = (f"в редакции «{active['source']}» строки {vri} нет — "
                        f"взята {edition['source']}")
            return {
                "x2": float(value), "vri": vri, "label": meta["label"],
                "unit": edition["unit"], "source": edition["source"],
                "source_confirmed": bool(edition.get("source_confirmed")),
                "edition": edition["id"], "note": note,
            }
    return {"x2": None, "vri": vri,
            "reason": (f"вида разрешённого использования {vri} в приложении 1 нет — "
                       "по сноске 6 число мест определяется заданием на проектирование")}


def moscow_required(
    function: str,
    value: Any,
    *,
    k1: Any = None,
    k2: Any = None,
    at: str = "",
    built_in: bool = False,
    specialty_shop: bool = False,
) -> dict[str, Any]:
    """Приобъектная парковка Москвы: N = ceil(X / X2 × K1 × K2).

    Округление одно и в самом конце, всегда вверх, — так велит приложение 6.
    Округлять по дороге значит получить другое число на тех же вводных.
    """
    amount = _number(value)
    assumptions: list[str] = []
    if built_in:
        x2_meta = {
            "x2": MOSCOW_BUILT_IN_X2, "vri": "", "label": "Встроенно-пристроенные помещения",
            "unit": UNIT_ABOVE_NONRES_SQM, "source": MOSCOW_BUILT_IN_SOURCE,
            "source_confirmed": True, "edition": "945pp_annex6", "note": "",
        }
    else:
        x2_meta = moscow_x2(function, at)
    if not x2_meta.get("x2"):
        return {"jurisdiction": MOSCOW, "function": function, "required_spaces": None,
                "reason": x2_meta.get("reason") or "норматив не определён",
                "assumptions": assumptions}

    k1_value = _number(k1)
    k2_value = _number(k2)
    missing = []
    if k1_value <= 0:
        missing.append("К1")
    if k2_value <= 0:
        missing.append("К2")
    if missing:
        # Принять единицу «пока не знаем» нельзя: К1 и К2 только СНИЖАЮТ
        # потребность, и единица даёт максимум, выданный за норматив.
        return {"jurisdiction": MOSCOW, "function": function, "required_spaces": None,
                "reason": "не заданы коэффициенты " + " и ".join(missing),
                "x2": x2_meta["x2"], "assumptions": assumptions}

    factor = 1.0
    if not built_in and x2_meta.get("vri") in MOSCOW_TRADE_VRI:
        if amount < MOSCOW_TRADE_SKIP_BELOW:
            assumptions.append(
                f"ННП менее {MOSCOW_TRADE_SKIP_BELOW:g} м² — сноска 4 приложения 1 "
                "допускает не предусматривать парковочные места")
            return {"jurisdiction": MOSCOW, "function": function, "input_value": amount,
                    "input_unit": x2_meta["unit"], "x2": x2_meta["x2"],
                    "k1": k1_value, "k2": k2_value, "raw_spaces": 0.0,
                    "required_spaces": 0, "normative_source": x2_meta["source"],
                    "source_confirmed": x2_meta["source_confirmed"],
                    "assumptions": assumptions}
        if MOSCOW_TRADE_RELIEF_FROM <= amount <= MOSCOW_TRADE_RELIEF_TO:
            factor = 1.0 / MOSCOW_TRADE_RELIEF_FACTOR
            assumptions.append(
                f"в проектируемой застройке ННП {MOSCOW_TRADE_RELIEF_FROM:g}–"
                f"{MOSCOW_TRADE_RELIEF_TO:g} м² — расчётное число снижено в "
                f"{MOSCOW_TRADE_RELIEF_FACTOR:g} раза (сноска 4 приложения 1)")
    if specialty_shop:
        factor /= MOSCOW_SPECIALTY_SHOP_FACTOR
        assumptions.append(
            "специализированный магазин товаров эпизодического спроса — "
            "расчётное число снижено в два раза (примечание приложения 1)")

    raw = amount / x2_meta["x2"] * k1_value * k2_value * factor
    if not x2_meta["source_confirmed"]:
        assumptions.append(f"источник норматива не сверен по тексту акта: {x2_meta['source']}")
    if x2_meta.get("note"):
        assumptions.append(x2_meta["note"])
    return {
        "jurisdiction": MOSCOW,
        "function": function,
        "function_label": x2_meta.get("label") or "",
        "vri": x2_meta.get("vri") or "",
        "input_value": amount,
        "input_unit": x2_meta["unit"],
        "input_unit_label": UNIT_LABELS.get(x2_meta["unit"], x2_meta["unit"]),
        "x2": x2_meta["x2"],
        "k1": k1_value,
        "k2": k2_value,
        "raw_spaces": raw,
        "required_spaces": int(math.ceil(raw)) if raw > 0 else 0,
        "normative_source": x2_meta["source"],
        "source_confirmed": x2_meta["source_confirmed"],
        "edition": x2_meta.get("edition") or "",
        "assumptions": assumptions,
    }


def mo_rule(function: str) -> dict[str, Any] | None:
    key = str(function or "").strip()
    for row in MO_RULES:
        if row["function"] == key:
            return row
    return None


def mo_required(
    function: str,
    value: Any,
    *,
    design_mode: str = DESIGN_MODE_DEFAULT,
    manual_spaces: Any = None,
) -> dict[str, Any]:
    """Московская область: диапазон остаётся диапазоном.

    Норматив «1 место на 40–50 м²» — это два числа, и превращать их в 45
    нельзя: 45 не написано ни в одном документе. Модели нужно одно число —
    значит выбор края объявляется отдельным допущением и называется вслух.
    """
    amount = _number(value)
    assumptions: list[str] = []
    rule = mo_rule(function)
    if rule is None:
        if str(function or "").strip() in MO_FALLBACK_EXCLUDED:
            return {"jurisdiction": MOSCOW_OBLAST, "function": function,
                    "required_spaces": None,
                    "reason": "п. 5.12 исключает эту функцию из правила 1/50 — "
                              "норматив берётся отдельно",
                    "assumptions": assumptions}
        rule = {"function": function, "label": "Функция вне таблицы",
                "unit": MO_FALLBACK_UNIT,
                "min_denominator": MO_FALLBACK_DENOMINATOR,
                "max_denominator": MO_FALLBACK_DENOMINATOR}
        source, confirmed = MO_FALLBACK_SOURCE, True
        assumptions.append("функция в таблице не найдена — применено правило 1 место на 50 м²")
    else:
        source, confirmed = MO_RULES_SOURCE, MO_RULES_CONFIRMED

    if amount <= 0:
        return {"jurisdiction": MOSCOW_OBLAST, "function": function,
                "required_spaces": None, "reason": "нулевая расчётная величина",
                "assumptions": assumptions}

    # Больший делитель даёт меньше мест: min мест — от max_denominator.
    spaces_min = int(math.ceil(amount / rule["max_denominator"]))
    spaces_max = int(math.ceil(amount / rule["min_denominator"]))
    mode = str(design_mode or DESIGN_MODE_DEFAULT).strip().lower()
    if mode == DESIGN_MODE_MANUAL:
        selected = int(_number(manual_spaces))
        assumptions.append("число мест задано вручную")
    elif mode == DESIGN_MODE_MIN:
        selected = spaces_min
        assumptions.append("выбран нижний край норматива — допущение DevelopAid, а не норма МО")
    else:
        mode = DESIGN_MODE_MAX
        selected = spaces_max
        assumptions.append("выбран верхний край норматива как консервативное "
                           "допущение DevelopAid, а не норма МО")
    if not confirmed:
        assumptions.append(f"источник норматива не сверен по тексту акта: {source}")
    return {
        "jurisdiction": MOSCOW_OBLAST,
        "function": function,
        "function_label": rule.get("label") or "",
        "input_value": amount,
        "input_unit": rule["unit"],
        "input_unit_label": UNIT_LABELS.get(rule["unit"], rule["unit"]),
        "norm_denominator_min": rule["min_denominator"],
        "norm_denominator_max": rule["max_denominator"],
        "required_spaces_min": spaces_min,
        "required_spaces_max": spaces_max,
        "required_spaces": selected,
        "selected_spaces": selected,
        "selection_mode": mode,
        "normative_source": source,
        "source_confirmed": confirmed,
        "assumptions": assumptions,
    }


def required_spaces(jurisdiction: str, function: str, value: Any, **kwargs: Any) -> dict[str, Any]:
    """Единая дверь. Юрисдикции — разные алгоритмы, а не один с ветками."""
    where = str(jurisdiction or "").strip().lower()
    if where in (MOSCOW, "msk", "москва"):
        return moscow_required(function, value, **{
            key: kwargs[key] for key in ("k1", "k2", "at", "built_in", "specialty_shop")
            if key in kwargs})
    if where in (MOSCOW_OBLAST, "mo", "область"):
        return mo_required(function, value, **{
            key: kwargs[key] for key in ("design_mode", "manual_spaces") if key in kwargs})
    return {"jurisdiction": where, "function": function, "required_spaces": None,
            "reason": f"юрисдикция «{jurisdiction}» не заведена", "assumptions": []}


def mixed_use_required(parts: list[dict[str, Any]], **kwargs: Any) -> dict[str, Any]:
    """Многофункциональный объект: по функциям, а не одной ставкой к сумме.

    Складывать метры разных функций и делить на один норматив — самый частый
    способ ошибиться кратно: у офиса и склада делители различаются в восемь раз.
    Сырые доли складываются до округления, итог округляется один раз вверх —
    иначе десять маленьких функций дадут десять лишних мест на ровном месте.
    """
    rows, assumptions, raw_total = [], [], 0.0
    failed = []
    for part in parts or []:
        row = required_spaces(
            part.get("jurisdiction") or kwargs.get("jurisdiction") or "",
            part.get("function") or "",
            part.get("value"),
            **{key: value for key, value in {**kwargs, **part}.items()
               if key in ("k1", "k2", "at", "built_in", "specialty_shop",
                          "design_mode", "manual_spaces")})
        rows.append(row)
        if row.get("required_spaces") is None:
            failed.append(f"{part.get('function')}: {row.get('reason') or 'не посчитано'}")
            continue
        raw_total += _number(row.get("raw_spaces") or row.get("required_spaces"))
        assumptions.extend(row.get("assumptions") or [])
    return {
        "parts": rows,
        "raw_spaces": raw_total,
        "required_spaces": int(math.ceil(raw_total)) if raw_total > 0 else 0,
        "not_counted": failed,
        "assumptions": list(dict.fromkeys(assumptions)),
    }
