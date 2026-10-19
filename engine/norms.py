"""Нормативы: плата за ВРИ вручную, индексы Москвы, парковки, кладовые, соцнормы.

Ставки компенсации и VRI_USE_TYPES, vri_manual_payment, индексы и
коэффициенты Москвы, нормы постоянных парковок (2118), средняя квартира,
подземная парковка и кладовые в ТЭП, пересчёт от базы ГлавАПУ, нормы
соцобъектов (tep_derived_norms), парковка отдельно стоящих объектов и
parking_demand.

Не самостоятельный модуль. `main_legacy.py` выполняет этот файл в своём
пространстве имён на том месте, где этот код стоял раньше
(`_engine_part("norms")`), поэтому здесь видны все имена движка,
а подмены `core.<имя>` из `main.py` и тестов действуют и на этот код.
Отдельно не импортировать: второй импорт поднял бы вторую копию движка.
"""
# ruff: noqa

# Дрейф-контроль серверных формул ГлавАПУ. Штатный браузерный калькулятор —
# первоисточник; серверные формулы (путь Telegram и кнопки бота) сняты с его
# кода и обязаны совпадать. Каждый успешный сбор штатного калькулятора на
# сайте сверяется с формулами: если ГлавАПУ поменяет методику, расхождение
# всплывёт в тот же день — в предупреждениях импорта, в /status и в ответах
# серверного пути, — а не будет молча жить в Telegram. Память процесса: после
# перезапуска флаг снимается до следующего сбора на сайте.
# Дата, на которую сняты зашитые ставки компенсации за соцобъекты. Город
# индексирует их поквартально: 04.08.2026 штатный калькулятор дал по одному
# участку 220,3 млн ₽ против серверных 185,1 — отставание в 19%. Дата едет в
# предупреждение серверного ответа, чтобы отставание было видно сразу, а не
# всплывало при сравнении расчётов с двух компьютеров.
_GLAVAPU_COMPENSATION_RATES_DATE = "01.08.2026"

# Квартальная индексация базовой стоимости ВРИ. Выгрузки штатного калькулятора
# от 16.08.2026 на двух кварталах (77:07:0008006 и 77:09:0004014) разошлись с
# формулой ровно на +1,7495%: город применяет индекс к базовой стоимости, а
# анализ территории отдаёт её прежней. Следующий квартал сдвинет индекс — при
# расхождении платы на одинаковый процент при совпадающей базе первым
# подозреваемым идёт эта константа, а не формула.
# --- свой расчёт платы за ВРИ и производных ТЭП ------------------------------
# Калькулятор ГлавАПУ считает по НОРМАТИВНОМУ ТЭП: плотность × площадь участка.
# На руках у людей бывает решение ГЗК, где метров в разы меньше, и тогда ответ
# калькулятора неверен для этого проекта — но менять его молча нельзя: город
# считает по своему. Поэтому свой расчёт стоит рядом, на тех же формулах и на
# основаниях участка, и подписан как свой (владелец, 20.08.2026).
#
# Типы использования — из листа «УПКС и базовые стоимости» выгрузки
# калькулятора. Нулевая базовая стоимость означает, что за этот вид плата не
# берётся: у производства и социальных объектов она ноль в самой выгрузке.
VRI_USE_TYPES: list[list[str]] = [
    ["mkd", "Жильё и встроенные помещения жилых зданий", "МКД (многоэтажный жилой дом)"],
    ["trade", "Торговля и многофункциональные объекты", "Торговля и многофункц."],
    ["office", "Офисы и административные здания", "Офисы"],
    ["hotel", "Объекты временного проживания", "Временное проживание"],
    ["garage", "Гаражи и хранение транспорта", "Гаражи"],
    ["industry", "Производство", "Производство"],
    ["social", "Социальные объекты", "Социальные объекты"],
]


def vri_manual_payment(rows: list[dict[str, Any]], rent_coeff: float,
                       index: float | None = None, *,
                       land_right: str = "ownership") -> dict[str, Any]:
    """Плата за смену ВРИ по своим метрам и своим основаниям.

    Формула та же, что у калькулятора (класс Df, метод calcOwn):
    1,8964 × СПП × коэффициент аренды × базовая стоимость × индекс / делитель.
    Она линейна по СПП, поэтому считается построчно и складывается.

    Делитель зависит от права на участок: собственность 1,00001, аренда 1,001.
    Аренда платит — просто по своему делителю, на 0,099% меньше; повышенная
    составляющая первого года по 273-ПП здесь не считается и названа вслух.

    Нулевая базовая стоимость — это «за этот вид не платят», а не «данных нет»:
    так в выгрузке стоят производство и социальные объекты. Отсутствующая
    базовая — другое дело, и строка уходит в `missing`, а не в ноль.
    """
    factor = float(index if index is not None else _GLAVAPU_VRI_BASE_INDEXATION)
    rent = max(0.0, float(rent_coeff or 0.0))
    right = str(land_right or "ownership").strip().lower()
    leased = right in ("lease", "аренда", "rent")
    divisor = _VRI_RIGHT_DIVISOR["lease" if leased else "ownership"]
    labels = {item[0]: item[1] for item in VRI_USE_TYPES}
    lines: list[dict[str, Any]] = []
    missing: list[str] = []
    total = 0.0
    for row in rows or []:
        key = str((row or {}).get("type") or "").strip()
        try:
            spp = max(0.0, float((row or {}).get("spp_sqm") or 0.0))
        except (TypeError, ValueError):
            spp = 0.0
        raw_base = (row or {}).get("base_cost_rub")
        if spp <= 0:
            continue
        if raw_base in (None, ""):
            missing.append(f"{labels.get(key, key)}: не задана базовая стоимость")
            continue
        try:
            base = max(0.0, float(raw_base))
        except (TypeError, ValueError):
            missing.append(f"{labels.get(key, key)}: базовая стоимость не число")
            continue
        payment = 1.8964 * spp * rent * base * factor / divisor
        total += payment
        lines.append({
            "type": key or "other",
            "label": labels.get(key, key or "Прочее"),
            "spp_sqm": round(spp, 2),
            "base_cost_rub": round(base, 2),
            "payment_mln": round(payment / 1e6, 3),
        })
    notes: list[str] = []
    if leased:
        notes.append(
            "право на участок — аренда: делитель 1,001 вместо 1,00001, плата ниже "
            "на 0,099%. Повышенная составляющая первого года по 273-ПП — отдельный "
            "платёж, здесь не считается")
    return {
        "lines": lines,
        "total_mln": round(total / 1e6, 3),
        "rent_coeff": rent,
        "index": factor,
        "index_date": _GLAVAPU_VRI_BASE_INDEXATION_DATE,
        "land_right": "lease" if leased else "ownership",
        "land_right_divisor": divisor,
        "notes": notes,
        "missing": missing,
        "basis": ("1,8964 × СПП × коэффициент аренды "
                  + f"{rent:g}".replace(".", ",")
                  + " × базовая стоимость × индекс "
                  + f"{factor:g}".replace(".", ",")
                  + " / делитель " + f"{divisor:g}".replace(".", ",")
                  + (" (аренда)" if leased else " (собственность)")),
    }


# --- нормативные справочники Москвы ------------------------------------------
# Свод норм прислан владельцем 20.08.2026 (`docs/normative/`), оригинал 2118-ПП
# у нас целиком. Величины версионируемые: старое значение не затирается новым —
# плата зависит от даты возникновения обязательства и применимой редакции.
#
# Числа здесь не участвуют в действующем пути расчёта: он берёт ставки из самой
# выгрузки ГлавАПУ (`recalculate_from_glavapu_baseline`). Справочник нужен для
# участка без выгрузки и как контроль импорта — контрольный квартал сходится с
# городским расчётом.
MOSCOW_VRI_PRICE_INDEX: list[dict[str, Any]] = [
    {"effective_from": "2026-07-30", "value": 1.9296,
     "document": "Приказ ДГИ Москвы № 303 от 30.07.2026",
     "note": "коэффициент изменения цен k1"},
]

# Функциональный коэффициент платы за ВРИ по 593-ПП. Не путать с K2
# приобъектной парковки (деловая активность территории): разные таблицы и
# разный смысл, а называются оба «к2».
MOSCOW_VRI_FUNCTION_COEFF: dict[str, float] = {
    "mkd": 1.0, "izh": 1.0, "hotel": 1.0,
    "office": 0.001, "trade": 0.001, "garage": 0.001,
    "industry": 0.001, "social": 0.001,
}

# Приложение 8 к 273-ПП: Pi по функциям и Kr по кварталу. Здесь один квартал —
# контрольный: он сходится с выгрузкой калькулятора по тому же участку, и это
# проверка правильности импорта, а не «справочник Москвы».
MOSCOW_QUARTER_REFERENCE: dict[str, dict[str, Any]] = {
    "77:01:0004023": {
        "rent_coeff": 0.1497,
        "base_costs_rub": {"mkd": 287560.46, "garage": 89143.74,
                           "trade": 194737.19, "hotel": 206274.93,
                           "office": 187578.99, "izh": 123651.00},
        "document": "273-ПП, приложение 8, таблицы 1 и 2",
        "checked_against": "выгрузка калькулятора ГлавАПУ 20.08.2026",
    },
}

# УУПСС, выпуск 25, уровень цен 01.01.2026. Какая колонка нужна — с
# технологическим присоединением или без — свод не решал; ответ даёт сам акт:
# 3135-ПП, прил. 2 п. 2.1 (ред. 2072-ПП) — «с учетом технологического
# присоединения и дополнительных затрат» на дату решения ГЗК. Колонка названа,
# но в расчёт эти числа по-прежнему не входят: компенсация считается ставками
# исходного расчёта.
MOSCOW_SOCIAL_UUPSS: dict[str, Any] = {
    "effective_from": "2026-03-03",
    "price_level": "2026-01-01",
    "document": "Приказ Москомэкспертизы МКЭ-ОД/26-14 от 03.03.2026, выпуск 25",
    "column_unresolved": False,
    "column": "with_tp",
    "column_basis": ("3135-ПП, прил. 2 п. 2.1 (ред. 2072-ПП): «с учетом "
                     "технологического присоединения и дополнительных затрат» "
                     "на дату решения ГЗК"),
    "values_th_rub": {
        "kindergarten": {"unit": "место", "without_tp": 4329.61, "with_tp": 4728.76},
        "school": {"unit": "место", "without_tp": 4283.72, "with_tp": 4490.91},
        "clinic": {"unit": "посещение/смену", "without_tp": 7707.29, "with_tp": 7924.58},
    },
}

# Приложение 6 к 945-ПП: приобъектная парковка, Nв = X / X2 × K1 × K2.
# Приложение 5 переписано 2118-ПП, приложение 6 — нет, и переписывать его
# вместе с ним нельзя.
MOSCOW_ATTACHED_PARKING_X2: dict[str, float] = {
    "office": 63.0, "mall": 54.0, "shop": 63.0, "catering": 54.0,
}


def moscow_price_index(at: str = "") -> dict[str, Any]:
    """Коэффициент изменения цен на дату. Пусто — последний известный."""
    rows = sorted(MOSCOW_VRI_PRICE_INDEX, key=lambda row: str(row["effective_from"]))
    moment = str(at or "").strip()
    chosen = None
    for row in rows:
        if not moment or str(row["effective_from"]) <= moment:
            chosen = row
    return dict(chosen or rows[-1])


# --- места постоянного размещения транспортных средств жителей ---------------
# Приложение 5 к 945-ПП в редакции 2118-ПП от 05.08.2026 (текст на руках,
# владелец прислал 20.08.2026). Прежняя наша строка — НП жилая / 90 × К1 — на
# выгрузке давала те же 897 мест, и это было совпадением: у неё другой
# driver (наземная площадь вместо площади квартир) и лишний множитель К1,
# которого в новом порядке нет вовсе. На утверждённом ТЭП различие уже видно —
# 123 места против 130.
_PARKING_2118_HOUSEHOLD = 2.1     # средний размер домовладения, чел.
_PARKING_2118_PER_FLAT = 0.8      # D — мест на одну квартиру
# S₁ — площадь квартир на жителя. Число — не приложения 5: его называет
# 2152-ПП, п. 1.4.2, табл. 1.4.1 (ред. 2579-ПП от 28.10.2025), а формула
# машино-мест лишь читает его как S₁.
_PARKING_2118_SQM_PER_PERSON = 33.0
_PARKING_GUEST_SHARE = 0.1        # гостевые — десятая часть постоянных
# Пункт 2: коэффициенты по полосам площади квартиры и границы полос —
# до 70 м², от 70 до 100, свыше 100.
_PARKING_2118_MIX = {"small": 0.8, "medium": 1.2, "large": 1.6}
_PARKING_2118_BANDS = {"small_max": 70.0, "medium_max": 100.0}
# Те же числа нужны странице: она показывает потребность в местах рядом с ТЭП и
# обязана считать её той же нормой. Копии на странице нет — как у `TEP_RATIOS`
# и `VERSION`, значения подставляются плейсхолдером.
PARKING_2118_PARAMS: dict[str, Any] = {
    "sqm_per_person": _PARKING_2118_SQM_PER_PERSON,
    "household": _PARKING_2118_HOUSEHOLD,
    "per_flat": _PARKING_2118_PER_FLAT,
    "guest_share": _PARKING_GUEST_SHARE,
    # Пункт 2 по средней квартире — те же полосы и коэффициенты, что у движка.
    "mix": dict(_PARKING_2118_MIX),
    "bands": dict(_PARKING_2118_BANDS),
    # Область считается своей нормой (`underground_parking_requirement`),
    # и её числа странице подставляются отсюда же — копии нет.
    "mo": {key: MO_NORMS_DEFAULT[key] for key in (
        "living_space_per_person_sqm", "parking_permanent_per_1000",
        "parking_permanent_share")},
}
PARKING_2118_PLACEHOLDER = "__DEVELOPAID_PARKING_2118__"

# Средняя квартира — делитель, которым площадь превращается в ЧИСЛО квартир, и
# ответ у него разный по источнику (решение владельца, 03.09.2026: «там где мы
# сами вручную собираем, пусть будет 60, там где подгружаем из АПУ — как в АПУ,
# если Подмосковье по кадастру или адресу — РНГП Подмосковья»). Пока делителей
# было четыре и ни один не назывался, на 136 818 м² выходило от 1 974 до 3 800
# квартир, и на экране они выглядели одинаково достоверно.
#
# Норматив Москвы 33 × 2,1 = 69,3 м² остаётся мерой НАСЕЛЕНИЯ — по нему считают
# жителей, соцнагрузку и машино-места. Мерой квартиры он не является: город
# нормирует обеспеченность, а квартиры продаёт рынок.
AVERAGE_FLAT_MANUAL_SQM = 60.0
AVERAGE_FLAT_MO_SQM = round(
    MO_NORMS_DEFAULT["living_space_per_person_sqm"] * _PARKING_2118_HOUSEHOLD, 2)
AVERAGE_FLAT_SOURCES: dict[str, tuple[float, str]] = {
    "manual": (AVERAGE_FLAT_MANUAL_SQM,
               "рынок — 60 м² на квартиру (решение владельца, 03.09.2026)"),
    # РНГП области называет 28 м² на человека и НЕ называет размера
    # домовладения — 2,1 взят из 2118-ПП и назван вслух: подставленное молча
    # число из чужого документа неотличимо от числа этого.
    "mo": (AVERAGE_FLAT_MO_SQM,
           "РНГП Московской области — "
           f"{MO_NORMS_DEFAULT['living_space_per_person_sqm']:g} м² на человека "
           f"при размере домовладения {_PARKING_2118_HOUSEHOLD:g} (2118-ПП)".replace(".", ",")),
}
AVERAGE_FLAT_PLACEHOLDER = "__DEVELOPAID_AVERAGE_FLAT__"


def average_flat_sqm(source: str) -> tuple[float, str]:
    """Средняя квартира и ОСНОВАНИЕ, по которому она взята.

    Выгрузки ГлавАПУ здесь нет намеренно: она приносит готовое число квартир
    (строка 5), и делить её площадь нашим делителем значит дать второй ответ на
    вопрос, на который город уже ответил.
    """
    value, basis = AVERAGE_FLAT_SOURCES.get(
        str(source or "manual"), AVERAGE_FLAT_SOURCES["manual"])
    return value, basis


# Население для соцнагрузки Москвы (ДОО, СОШ, поликлиника и компенсация за
# них). Норма — п. 1.4.2 и табл. 1.4.1 2152-ПП в ред. 2579-ПП: площадь квартир
# / 33 м². Город же на деле требует «1 квартира = 2,1 жителя» (решение
# владельца, 16.10.2026: умолчание — норма, требование органа — переключателем
# проекта). Это НЕ норма РНГП, и основание говорит это вслух; разбор —
# docs/rngp_social_load_population.md. Машино-места и двор считаются своими
# нормами и этим полем не меняются.
SOCIAL_POPULATION_METHODS: dict[str, str] = {
    "rngp_area": "По РНГП: площадь квартир / 33 м²",
    "flats_household": "Альтернативный расчёт «1 квартира = 2,1 жителя» (Москва)",
}
SOCIAL_POPULATION_DEFAULT = "rngp_area"


def moscow_social_population(apartment_area_sqm: float, apartment_count: float = 0.0,
                             method: str = SOCIAL_POPULATION_DEFAULT) -> tuple[int, str, str]:
    """→ (жителей, основание, способ). Неизвестный способ — норма РНГП."""
    area = max(0.0, float(apartment_area_sqm or 0.0))
    chosen = str(method or SOCIAL_POPULATION_DEFAULT).strip().lower()
    if chosen not in SOCIAL_POPULATION_METHODS:
        chosen = SOCIAL_POPULATION_DEFAULT
    by_area = math.ceil(area / _PARKING_2118_SQM_PER_PERSON) if area > 0 else 0
    if chosen == "rngp_area":
        return by_area, (f"площадь квартир / {_PARKING_2118_SQM_PER_PERSON:g} м² "
                         "(п. 1.4.2, табл. 1.4.1 2152-ПП)"), chosen
    count = max(0.0, float(apartment_count or 0.0))
    if count > 0:
        flats, origin = math.ceil(count), "число квартир из ТЭП"
    else:
        flat_sqm, _ = average_flat_sqm("manual")
        if area <= 0 or flat_sqm <= 0:
            return 0, "квартир нет — население 0", chosen
        flats = math.ceil(area / flat_sqm)
        origin = (f"число квартир в ТЭП не задано — площадь / {flat_sqm:g} м² "
                  "средней квартиры")
    population = math.ceil(round(flats * _PARKING_2118_HOUSEHOLD, 6))
    household = f"{_PARKING_2118_HOUSEHOLD:g}".replace(".", ",")
    return population, (f"{flats} квартир × {household} — требование органа, не РНГП "
                        f"({origin}; по норме было бы {by_area})"), chosen


_PARKING_REGIMES = ("2118_2026", "legacy_945")


def moscow_parking_band(average_flat_sqm: float) -> str:
    """Полоса пункта 2 по площади квартиры: до 70 — малая, до 100 — средняя."""
    avg = float(average_flat_sqm or 0.0)
    if avg < _PARKING_2118_BANDS["small_max"]:
        return "small"
    if avg <= _PARKING_2118_BANDS["medium_max"]:
        return "medium"
    return "large"


def moscow_permanent_parking_by_average(apartment_area_sqm: float,
                                        apartment_count: float) -> tuple[int, str]:
    """Пункт 2 по средней квартире — когда известно число квартир, а состава нет.

    Состав квартир по размерам есть только со стадии АГР; на стадии оценки его
    нет, но средняя квартира меняется вместе с числом квартир, и от неё можно
    плясать (владелец, 04.09.2026). Все квартиры относятся к полосе средней: на
    28 966 м² при 750 квартирах (38,6 м²) это 600 мест, при 419 (69,1 м²) — 336;
    пункт 1 от площади дал бы 335 в обоих случаях, потому что число квартир в
    него не входит. Это оценка, и основание говорит это словами. Без числа
    квартир — пункт 1.
    """
    area = max(0.0, float(apartment_area_sqm or 0.0))
    count = max(0.0, float(apartment_count or 0.0))
    if area <= 0:
        return 0, "площади квартир нет — мест не посчитать"
    if count <= 0:
        return (moscow_permanent_parking_2118(area),
                "приложение 5 к 945-ПП в редакции 2118-ПП, пункт 1: S / (S₁ × 2,1) × 0,8, "
                "S₁ = 33 м² по 2152-ПП, табл. 1.4.1 (число квартир не задано)")
    avg = area / count
    band = moscow_parking_band(avg)
    label = {"small": "до 70 м²", "medium": "от 70 до 100 м²", "large": "свыше 100 м²"}[band]
    places = math.ceil(count * _PARKING_2118_MIX[band])
    basis = (f"приложение 5 к 945-ПП в редакции 2118-ПП, пункт 2 по средней квартире "
             f"{avg:.1f} м²: все {int(count)} квартир отнесены к полосе {label} "
             f"× {_PARKING_2118_MIX[band]:g} — оценка, состава квартир до АГР нет")
    return places, basis


def moscow_permanent_parking_2118(apartment_area_sqm: float,
                                  sqm_per_person: float = _PARKING_2118_SQM_PER_PERSON) -> int:
    """Пункт 1: Nп = S / (S₁ × 2,1) × D — для градостроительного проектирования.

    S — площадь квартир; S₁ — площадь квартир на жителя (33 м² — 2152-ПП,
    табл. 1.4.1 в ред. 2579-ПП); D = 0,8 места на квартиру. Округление вверх.
    """
    area = max(0.0, float(apartment_area_sqm or 0.0))
    per_person = float(sqm_per_person or 0.0)
    if area <= 0 or per_person <= 0:
        return 0
    return math.ceil(area / (per_person * _PARKING_2118_HOUSEHOLD) * _PARKING_2118_PER_FLAT)


def moscow_permanent_parking_by_mix(small: float, medium: float, large: float) -> int:
    """Пункт 2: Nп = F₁×0,8 + F₂×1,2 + F₃×1,6 — когда известен состав квартир.

    F₁ — до 70 м², F₂ — от 70 до 100, F₃ — свыше 100 плюс ИЖС и блокированные.
    Это стадия АГР: до неё состава нет, и считают по пункту 1.
    """
    counts = (max(0.0, float(small or 0.0)), max(0.0, float(medium or 0.0)),
              max(0.0, float(large or 0.0)))
    if not any(counts):
        return 0
    return math.ceil(counts[0] * _PARKING_2118_MIX["small"]
                     + counts[1] * _PARKING_2118_MIX["medium"]
                     + counts[2] * _PARKING_2118_MIX["large"])
# `n` и `b` стоят здесь, а не ниже по файлу: строка ТЭП подземного
# паркинга считается ими ПРИ ИМПОРТЕ, когда собирается умолчание, и
# объявление ниже своего читателя дало бы `NameError` на ровном месте.
def n(x: dict, key: str, default: float = 0.0) -> float:
    try:
        value = x.get(key, default)
        return float(default if value in (None, "") else value)
    except (TypeError, ValueError):
        return float(default)


def b(x: dict, key: str) -> bool:
    value = x.get(key, False)
    if isinstance(value, bool):
        return value
    return str(value).lower() in ("1", "true", "да", "yes", "on")


# --- строка ТЭП подземного паркинга ------------------------------------------
def _underground_number(source: dict[str, Any], key: str) -> float:
    try:
        return max(0.0, float(source.get(key) or 0.0))
    except (TypeError, ValueError):
        return 0.0


def underground_area_per_space(inputs: dict[str, Any]) -> float:
    """Норматив площади на машино-место: гросс — рампы и проезды внутри.

    Ноль и пустое значат «умолчание», а не «площади нет»: поле приходит со
    страницы явным нулём, когда его не было в сохранённом проекте.
    """
    fallback = _underground_number(DEFAULT_INPUTS, "underground_area_per_space_sqm")
    return (_underground_number(inputs, "underground_area_per_space_sqm")
            or fallback or 35.0)


def glavapu_apartments_unchanged(normalized: dict[str, Any],
                                 apartment_row: dict[str, Any]) -> bool:
    """Квартиры те же, что у выгрузки ГлавАПУ? Импорт кладёт их в ТЭП как есть.

    Сверяются и площадь, и число квартир: норма считает места по средней
    квартире, и правка одного числа квартир при той же площади меняет её
    («меняю количество квартир до 24 — почему не меняется количество
    машиномест», владелец, «Донской», 07.10.2026).

    Нет площади в выгрузке — сравнить не с чем, и «не меняли» не доказано:
    отсутствие числа не равно совпадению.
    """
    city = _underground_number(normalized or {}, "apartment_area_sqm")
    if city <= 0:
        return False
    same_area = abs(_underground_number(apartment_row or {}, "saleable") - city) < 0.5
    same_count = abs(_underground_number(apartment_row or {}, "units")
                     - _underground_number(normalized or {}, "apartment_units")) < 0.5
    return same_area and same_count


def underground_parking_requirement(inputs: dict[str, Any],
                                    tep: dict[str, dict[str, Any]]) -> dict[str, Any] | None:
    """Потребность в подземных местах: выгрузка города первой, её нет — норма.

    Выгрузка идёт первой потому, что знает приобъектные места нежилья; наша
    норма их не считает и говорит это в основании — К1 и К2 квартала без
    выгрузки неизвестны, а единица «пока не знаем» отдала бы максимум,
    выданный за норматив.
    """
    rows = tep or {}
    per = underground_area_per_space(inputs)
    apartment_row = rows.get("apartments") or {}
    apartments = _underground_number(apartment_row, "saleable")
    normalized = (inputs.get("_glavapu_import") or {}).get("normalized") or {}
    if project_region(inputs) == "other":
        # Другой регион: норм его у нас нет, а 2118-ПП и РНГП области — чужие.
        # Места вписывает человек (решение владельца 19.10.2026); «не знаем» —
        # не ноль мест.
        return None
    if project_region(inputs) == "mo":
        # В области норматив мест свой — РНГП МО, и он у движка уже есть
        # (`mo_social_program`): по нему же считаются соцобъекты. 2118-ПП —
        # постановление Москвы, а выгрузка ГлавАПУ — московский орган; в
        # области ни то ни другое потребность не задаёт. Гостевых здесь нет:
        # временные места норматив МО отдаёт жилому району, а не кварталу.
        if apartments <= 0:
            return None
        program = mo_social_program(apartments)
        permanent = float(program["parking"]["permanent_spaces"])
        if permanent <= 0:
            return None
        return {"permanent": permanent, "guest": 0.0, "mfc": 0.0, "spaces": permanent,
                "basis": (f"РНГП Московской области: {program['population']} чел. от "
                          + f"{apartments:,.0f}".replace(",", " ")
                          + " м² квартир, только постоянное хранение"),
                "gns": permanent * per}
    imported_permanent = _underground_number(normalized, "parking_permanent")
    imported_guest = _underground_number(normalized, "parking_guest")
    imported_mfc = _underground_number(normalized, "mfc_parking_spaces")
    if imported_permanent + imported_guest + imported_mfc > 0:
        permanent, guest = imported_permanent, imported_guest
        basis = "норматив ГлавАПУ по нормативному ТЭП"
        if apartments > 0 and not glavapu_apartments_unchanged(normalized, apartment_row):
            # Квартиры правили после выгрузки — места пересчитываются нормой от
            # НОВЫХ квартир: число города посчитано на его же ТЭП. Пока
            # квартиры те же, что у города, его места и остаются (решение
            # владельца 07.10.2026: «числа ГлавАПУ до правки»). Норма — та же,
            # что без выгрузки: пункт 2 по средней квартире, второй формулы нет.
            places, basis = moscow_permanent_parking_by_average(
                apartments, _underground_number(apartment_row, "units"))
            permanent = float(places)
            guest = float(math.ceil(permanent * _PARKING_GUEST_SHARE))
        mfc = imported_mfc
        was_office = _underground_number(normalized, "office_gba_sqm")
        if imported_mfc > 0 and was_office > 0:
            now_office = sum(_underground_number(rows.get(key) or {}, "gns")
                             for key in object_keys_of("offices", "standalone_retail"))
            mfc = float(math.ceil(imported_mfc * now_office / was_office))
        spaces = permanent + guest + mfc
        if spaces <= 0:
            return None
        # Площадь паркинга МФЦ город назвал сам — пересчитывать её нашим
        # нормативом незачем, пока число мест осталось его.
        mfc_area = mfc * per
        if imported_mfc > 0 and mfc == imported_mfc:
            mfc_area = _underground_number(normalized, "mfc_parking_area_sqm") or mfc * per
        return {"permanent": permanent, "guest": guest, "mfc": mfc, "spaces": spaces,
                "basis": basis, "gns": (permanent + guest) * per + mfc_area}
    if apartments <= 0:
        return None
    permanent_places, basis = moscow_permanent_parking_by_average(
        apartments, _underground_number(apartment_row, "units"))
    permanent = float(permanent_places)
    guest = float(math.ceil(permanent * _PARKING_GUEST_SHARE))
    spaces = permanent + guest
    if spaces <= 0:
        return None
    return {"permanent": permanent, "guest": guest, "mfc": 0.0, "spaces": spaces,
            "basis": basis + "; приобъектные места нежилья не учтены",
            "gns": spaces * per}


def underground_parking_by_hand(inputs: dict[str, Any]) -> bool:
    """Пара «места ↔ площадь» подземного паркинга — решение человека?

    Страница сама заполняет пару нормой и помечает это `_parking_by_norm`
    (`fillUndergroundFromTep`): поле непустое, но число — нормы. Движок прежде
    читал всякое непустое поле как ручное, и производные строки (гостевые)
    замирали на прежних вводных. Пометка руки сильнее пометки нормы; проект без
    пометок (до них, API, бот) — непустое поле человеческое.

    От `object_parking_by_hand` отличается одним: проектный подземный посев
    списка `_parking_by_hand` не проходит намеренно, поэтому отсутствие в нём
    ещё не значит «норма».
    """
    key = "underground"
    if key in set(inputs.get("_parking_by_hand") or ()):
        return True
    if key in set(inputs.get("_parking_by_norm") or ()):
        return False
    return True


def underground_tep_row(inputs: dict[str, Any],
                        tep: dict[str, dict[str, Any]]) -> dict[str, float] | None:
    """Строка ТЭП подземного паркинга — производная, и ответ у неё ОДИН.

    Считали её четверо и по-разному. Страница (`repairParkingFromGlavapu`)
    шла по порядку «отказ → руками → выгрузка → норматив»; движок последней
    ступени не имел ВОВСЕ и на проекте без ручных полей и без выгрузки брал
    присланное — на умолчаниях это 1 107,51 места (дробное число мест!) и
    38 763 м² против 1 199 и 41 965 у страницы, а правка норматива 35 → 40 не
    двигала в движке ничего. Книга показывает ФАКТИЧЕСКИЙ норматив (площадь ÷
    места) и потому следует за строкой, а `/v2` пересчитывает пару при правке
    ячейки — обе поверхности верны ровно настолько, насколько верна строка.

    Кладовые площадь гаража НЕ уменьшают — они прибавляют свою (решение
    владельца, 13.09.2026: «конечно они добавляют подземную площадь, иначе на
    машиноместа и хватит просто площадей»). Здесь стоит ровно «места ×
    норматив»: ни один источник не даёт нам этаж целиком — ни выгрузка ГлавАПУ,
    ни ручной шаблон, ни поле «Площадь подземной парковки», которое пара
    «места ↔ площадь» держит на том же нормативе. Вычитание превращало
    норматив 35 м²/место в фактические 33,67 при 400 кладовых по 4 м², то есть
    молча отнимало у гаража метры, которых в нём и не было.

    Возвращает `None`, когда считать не из чего: ни отказа, ни ручных полей,
    ни выгрузки, ни квартир. Тогда строку не трогают — «мы не знаем» не то же
    самое, что «паркинга нет».
    """
    row = (tep or {}).get("underground_parking")
    if not isinstance(row, dict):
        return None
    zero = {"units": 0.0, "gns": 0.0, "total_area": 0.0,
            "useful": 0.0, "saleable": 0.0, "transfer": 0.0}
    if b(inputs, "underground_parking_disabled"):
        # Отказ от подземного паркинга: потребность закрывает наземный гараж.
        # Ноль в поле мест значит «по нормативу», поэтому отказ — свой признак.
        return dict(zero)
    per = underground_area_per_space(inputs)
    manual_spaces = _underground_number(inputs, "underground_manual_spaces")
    manual_area = _underground_number(inputs, "underground_manual_gns_sqm")
    guest: float | None = None
    if underground_parking_by_hand(inputs) and (manual_spaces > 0 or manual_area > 0):
        # Заданная руками площадь сильнее норматива ВСЕГДА, а не только когда
        # мест не назвали: реальный подземный этаж диктуют пятно застройки,
        # рампы и техпомещения, а норматив описывает потребность.
        spaces = manual_spaces if manual_spaces > 0 else (
            round(manual_area / per) if per > 0 else 0.0)
        area = manual_area if manual_area > 0 else spaces * per
        # Гостевые человек не вписывал — они выводятся из его мест тем же
        # правилом, что у читателя (S/11). Оставить в строке прежнее число
        # значит заморозить производное: на «Донском» 44 места несли 109
        # гостевых от давно сменившихся вводных.
        guest = float(underground_guest_spaces({"units": spaces}))
        # Места поставил метод (норматив по ТЭП, сценарий ГлавАПУ) — гостевые
        # тоже его: метод их знает, места/11 только приближение (решение
        # владельца 16.10.2026). Число действует, пока места те же самые.
        method = underground_method_guest(inputs, spaces)
        if method is not None:
            guest = method
    else:
        need = underground_parking_requirement(inputs, tep)
        if not need:
            return None
        spaces, area, guest = need["spaces"], need["gns"], need["guest"]
    if project_region(inputs) != "msk":
        # Другой регион — тоже без московской одиннадцатой части: правила
        # гостевых мест его у нас нет, и вписанные места все постоянные.
        # Гостевых мест норматив области в квартале не строит — значит, и
        # заданные руками места все постоянные. Без явного нуля движок
        # вычел бы из них московскую одиннадцатую часть и не продал бы её.
        guest = 0.0
    computed = dict(zero)
    computed["units"] = float(spaces)
    computed["gns"] = round(area, 1)
    computed["total_area"] = computed["gns"]
    if guest is not None:
        # Точное число гостевых известно из самой нормы — выводить его из доли
        # незачем, а потерять значит продать их.
        computed["guest_units"] = guest
    return computed


def underground_method_guest(inputs: dict[str, Any], spaces: float) -> float | None:
    """Гостевые, которые метод дал вместе с этими местами, или None.

    Страница пишет их рядом с местами (`setUndergroundFromMethod`). Места с
    тех пор поменяли — число метода уже про другой гараж и не читается.
    """
    pinned = inputs.get("_underground_method_guest")
    if not isinstance(pinned, dict):
        return None
    try:
        at, guest = float(pinned.get("spaces")), float(pinned.get("guest"))
    except (TypeError, ValueError):
        return None
    if abs(at - float(spaces)) > 1e-9 or not 0 <= guest <= at:
        return None
    return guest


def apply_underground_tep_row(inputs: dict[str, Any],
                              tep: dict[str, dict[str, Any]]) -> None:
    """Привести строку подземного паркинга к вводным. Правится на месте.

    Объявленную очередью строку не трогаем: её площадь — доля уже посчитанной
    проектной, и повторный вычет кладовых снял бы их дважды.
    """
    row = (tep or {}).get("underground_parking")
    if not isinstance(row, dict) or row.get(TEP_ROW_DECLARED):
        return
    stale = underground_stale_guests(row)
    computed = underground_tep_row(inputs, tep)
    if computed:
        row.update(computed)
    if stale is not None:
        # Чужое число не меняется молча: строка несёт, что было в проекте, и
        # страница подписывает замену (`guest_units_stale`).
        row["guest_units_stale"] = stale


def underground_stale_guests(row: dict[str, Any]) -> float | None:
    """Гостевые строки, которых больше, чем мест, — чужое число, или None."""
    try:
        guest = float(row.get("guest_units"))
        units = float(row.get("units") or 0)
    except (TypeError, ValueError):
        return None
    return guest if guest > units else None


STORAGE_AREA_PER_UNIT_DEFAULT = 4.3


def storage_area_per_unit(inputs: dict[str, Any]) -> float:
    """Площадь одной кладовой, м². Ноль и пустое значат «умолчание».

    Величина измерена, а не назначена: средняя кладовая в продаже 4,3 м² (ПИК,
    май–июль 2026) и 4,6 (НДВ, 2024), в продаже 2,3–9,8, а СП 4.13130.2013
    изм. 3 ограничивает одну кладовую десятью метрами. Замер накрывает
    масс-сегмент; у бизнеса и элитки своего замера нет, и потому число одно на
    все классы — у кого кладовая крупнее, правит его в профиле своего класса.
    """
    fallback = _underground_number(DEFAULT_INPUTS, "storage_area_per_unit_sqm")
    return (_underground_number(inputs, "storage_area_per_unit_sqm")
            or fallback or STORAGE_AREA_PER_UNIT_DEFAULT)


def storage_tep_row(inputs: dict[str, Any],
                    tep: dict[str, dict[str, Any]]) -> dict[str, float] | None:
    """Строка ТЭП кладовых: штуки и метры — одна величина в двух видах.

    Жили они независимо, и это ровно то, что владелец увидел на экране
    (14.09.2026: «ввёл в ТЭП 800 штук — ничего не изменилось в площади и
    наоборот»). Замер на живых функциях страницы подтвердил дословно: 800 штук
    давали 0 м², 8 000 м² давали 0 штук. Цена обеих половин посчитана на
    умолчаниях: 800 кладовых без метров это +989,1 млн ₽ выручки и ноль СМР
    (LLCR 0,9656 → 0,9893) — товар из воздуха; 8 000 м² без штук это +1 169,9
    млн ₽ CAPEX и ноль выручки (0,9333) — стройка без товара. Верная пара
    (800 × 4,3 = 3 440 м²) даёт 0,9750, то есть настоящий ответ лежит между
    двумя молчаливыми ошибками, и ни одна из них ошибкой не выглядит.

    Ведущее — ШТУКИ: продаётся кладовая, а не её метр, и норматив меняют,
    когда меняется представление о самой кладовой. Заданная руками площадь
    сильнее норматива — то же правило, что у подземного паркинга: реальный
    этаж диктует пятно застройки, а не норматив.

    Нормы «сколько кладовых на дом» не существует ни у города, ни у нас,
    поэтому пустая строка остаётся пустой: сколько их строить — решение
    проекта, и выдуманный норматив потребности построил бы товар, которого
    никто не заказывал.
    """
    row = (tep or {}).get("storage")
    if not isinstance(row, dict):
        return None
    per = storage_area_per_unit(inputs)
    units = _underground_number(row, "units")
    area = _underground_number(row, "gns")
    if units <= 0 and area <= 0:
        return None
    if units > 0 and area > 0:
        # Заданы оба — это решение человека, и трогать его нечем: фактический
        # норматив (площадь ÷ штуки) виден в подписи строки, как у соцобъектов
        # в режиме «Требование КРТ».
        return None
    # Кладовая неделима: 833⅓ штуки не продаются и не строятся. Живой импорт
    # такие числа приносит — он сам считает их из площади (на Мытищах 833,3333
    # при 5 555,6 м² общей), — и пока метров у строки не было, дробь никому не
    # мешала. С парой она мешает сразу: по очередям штуки раздаются целыми
    # (`_integer_phase_allocations`), их сумма становится 833, а метры едут
    # долей от 833⅓ — сумма очередей выходит 3 581,87 против 3 583,3 у
    # участка. Округляем ЗДЕСЬ, у единственного места, где пара считается:
    # округление в раздаче лечило бы следствие, а дробная кладовая осталась бы
    # в отчёте и в выручке.
    units = float(round(units))
    if units > 0:
        area = round(units * per, 1)
    else:
        units = float(round(area / per)) if per > 0 else 0.0
    computed = {"units": units, "gns": round(area, 1)}
    computed["total_area"] = computed["gns"]
    return computed


def apply_storage_tep_row(inputs: dict[str, Any],
                          tep: dict[str, dict[str, Any]]) -> None:
    """Привести строку кладовых к паре. Правится на месте.

    Объявленную очередью строку не трогаем: её метры и штуки — доля уже
    посчитанной проектной пары, и второй пересчёт развёл бы сумму очередей с
    проектом.
    """
    row = (tep or {}).get("storage")
    if not isinstance(row, dict) or row.get(TEP_ROW_DECLARED):
        return
    computed = storage_tep_row(inputs, tep)
    if computed:
        row.update(computed)


# Умолчание строки считается тем же ответом, а не пишется литералом: копию
# негде обновлять, потому что копии нет. Прежний литерал нёс 1 107,5142857
# места — дробное число мест, которых не строят, — и 38 763 м², то есть ответ
# ещё одной, пятой методики.
if "underground_parking" in TEP_DEFAULT:
    _underground_default = underground_tep_row(DEFAULT_INPUTS, TEP_DEFAULT)
    if _underground_default:
        TEP_DEFAULT["underground_parking"].update(_underground_default)
    del _underground_default


# Делители платы за смену ВРИ по праву на участок — из формулы калькулятора
# (класс Df): собственность 1,00001, аренда жилья 1,001. Разница 0,099%, но
# платят при обоих правах, и отказ вместо расчёта показывал бы ноль там, где
# деньги есть.
_VRI_RIGHT_DIVISOR: dict[str, float] = {"ownership": 1.00001, "lease": 1.001}


def _ceil_places(value: float) -> int:
    """Округление мест вверх без двоичного шума.

    Ставка, снятая с базы (места / НП), умноженная на ту же НП, даёт не ровно
    целое, а 93,000…01 — и ⌈⌉ отдавал 94 там, где город сказал 93. Шестой знак
    отсекает шум и не трогает настоящие дроби: 0,000001 места не бывает.
    """
    return math.ceil(round(float(value), 6))


def recalculate_from_glavapu_baseline(baseline: dict[str, Any],
                                      areas: dict[str, Any]) -> dict[str, Any]:
    """Пересчёт по параметрам исходного расчёта ГлавАПУ.

    Второй калькулятор строить не нужно: территория уже посчитана, и при правке
    ТЭП меняется только количественная база. Кадастровый квартал, К1, зона,
    коэффициент аренды, базовые стоимости и УПКС остаются теми же — значит
    ставки территории можно снять с самой выгрузки и применить к новым метрам
    (решение владельца, 20.08.2026).

    Так надёжнее зашитых констант: у ставок, снятых с базы, нет срока годности —
    новая выгрузка приносит новые. Наши УУПСС дали компенсацию 486,9 млн там,
    где ставки выгрузки дают 497,0.

    Метод проверяет сам себя: применённый к ИСХОДНОМУ ТЭП, он обязан
    воспроизвести числа ГлавАПУ. Не воспроизводит — результат не показывается
    как расчёт, а называется расхождением с базой.
    """
    def num(source: dict[str, Any], key: str) -> float:
        try:
            return max(0.0, float(source.get(key) or 0.0))
        except (TypeError, ValueError):
            return 0.0

    base_res_spp = num(baseline, "residential_spp_sqm")
    base_built_in_spp = num(baseline, "ground_commercial_spp_sqm")
    base_vri_spp = base_res_spp + base_built_in_spp
    base_res_np = num(baseline, "residential_np_sqm")
    base_built_in_np = num(baseline, "ground_commercial_np_sqm")
    base_apartments = num(baseline, "apartment_area_sqm")

    warnings: list[str] = []
    rates: dict[str, Any] = {}

    # --- ставки территории, снятые с базы --------------------------------
    vri_base = num(baseline, "change_vri_mln")
    vri_rate = vri_base / base_vri_spp if base_vri_spp > 0 else 0.0
    if vri_rate <= 0:
        warnings.append("в исходном расчёте нет платы за ВРИ — ставку снять не с чего")
    rates["vri_mln_per_sqm"] = vri_rate

    social_rates: dict[str, float] = {}
    for key, money_key, places_key in (
            ("kindergarten", "social_compensation_kindergarten_mln", "required_kindergarten_places"),
            ("school", "social_compensation_school_mln", "required_school_places"),
            ("clinic", "social_compensation_clinic_mln", "required_clinic_capacity")):
        places = num(baseline, places_key)
        money = num(baseline, money_key)
        social_rates[key] = money / places if places > 0 else 0.0
    rates["social_mln_per_place"] = social_rates
    if not any(social_rates.values()):
        warnings.append("в исходном расчёте нет компенсации за соцобъекты — ставки снять не с чего")

    # Ставка снимается с той же НП, которой потом считаются новые метры —
    # СПП × 0,9. Выгрузка печатает НП округлённой до тысяч (22,217 против
    # 24,686 × 0,9 = 22,2174), и ставка с напечатанной НП на исходных же
    # метрах давала 93,002 → 94 вместо 93 города. Нет СПП в базе — берём НП.
    base_res_np_rate = base_res_spp * 0.9 if base_res_spp > 0 else base_res_np
    base_built_in_np_rate = (base_built_in_spp * 0.9 if base_built_in_spp > 0
                             else base_built_in_np)
    permanent_rate = (num(baseline, "parking_permanent") / base_res_np_rate
                      if base_res_np_rate > 0 else 0.0)
    attached_rate = (num(baseline, "parking_attached") / base_built_in_np_rate
                     if base_built_in_np_rate > 0 else 0.0)
    rates["parking_permanent_per_sqm"] = permanent_rate
    rates["parking_attached_per_sqm"] = attached_rate

    # --- новые метры -----------------------------------------------------
    apartments = num(areas, "apartment_area_sqm")
    res_spp = num(areas, "residential_living_spp_sqm")
    built_in_spp = num(areas, "ground_commercial_spp_sqm")
    nonres_np = num(areas, "nonresidential_np_sqm")
    nonres_by_use = {str(key): max(0.0, float(value or 0.0))
                     for key, value in (areas.get("nonres_spp_by_use") or {}).items()}

    # --- население и соцпотребность --------------------------------------
    # Пропорцией население не считают: округления вверх идут на каждом шаге.
    zone_two = bool(areas.get("zone_two") or baseline.get("calculation_zone") == "2")
    norms = tep_derived_norms(
        apartment_area_sqm=apartments, residential_living_spp_sqm=res_spp,
        nonresidential_np_sqm=nonres_np, k1=1.0, k2=1.0, zone_two=zone_two,
        apartment_count=float(areas.get("apartment_count") or 0.0),
        social_population_method=str(areas.get("social_population_method") or ""))
    places = {"kindergarten": norms["kindergarten_places"],
              "school": norms["school_places"],
              "clinic": norms["clinic_capacity"]}
    compensation = {key: round(social_rates.get(key, 0.0) * count, 3)
                    for key, count in places.items()}

    # --- машино-места ----------------------------------------------------
    # К1 и К2 в ставках уже сидят: они сняты с базы, где город их применил.
    regime = str(areas.get("parking_norm_regime") or "2118_2026")
    if regime not in _PARKING_REGIMES:
        regime = "2118_2026"
        warnings.append("неизвестный режим норматива парковки — считаю по 2118-ПП")
    flats = areas.get("apartment_mix") or {}
    if regime == "legacy_945":
        # Переходные положения 2118-ПП (п. 2.1): объекты с разрешением на
        # строительство, свидетельством АГР, одобренной 3D-моделью на 05.08.2026
        # или вводом до 01.01.2028 считаются по прежней редакции. Определять это
        # «примерно по дате» нельзя — режим задаётся явно.
        permanent = _ceil_places(res_spp * 0.9 * permanent_rate) if res_spp and permanent_rate else 0
        parking_basis = "прежняя редакция 945-ПП: ставка исходного расчёта на метр НП жилой"
    elif any(float(flats.get(key) or 0) for key in ("small", "medium", "large")):
        permanent = moscow_permanent_parking_by_mix(
            flats.get("small"), flats.get("medium"), flats.get("large"))
        parking_basis = ("приложение 5 к 945-ПП в редакции 2118-ПП, пункт 2: "
                         "F₁×0,8 + F₂×1,2 + F₃×1,6 по составу квартир")
    else:
        # Число квартир известно — пункт 2 по средней квартире; нет — пункт 1.
        # На числе квартир самой выгрузки (население / 2,1) средняя равна
        # 69,3 м² — та же полоса и тот же 0,8, что в пункте 1; расходятся они
        # только на округление числа квартир вверх (898 против 897 на базе).
        permanent, parking_basis = moscow_permanent_parking_by_average(
            apartments, float(areas.get("apartment_count") or 0.0))
    guest = math.ceil(permanent / 10.0) if permanent else 0
    # Приобъектные места — по ставке базы от ВСТРОЕННЫХ помещений: ставка снята
    # с их НП (12 мест на 6 867 м²), и растягивать её на отдельно стоящее
    # офисное здание значит выдать 109 мест за посчитанные. У отдельного здания
    # свой паркинг со своим нормативом, и он в проекте отдельным продуктом.
    built_in_np = built_in_spp * 0.9
    attached = (_ceil_places(built_in_np * attached_rate)
                if built_in_np and attached_rate else 0)
    standalone_np = max(0.0, nonres_np - built_in_np)
    if standalone_np > 1:
        warnings.append(
            f"приобъектные места посчитаны для встроенных помещений "
            f"({built_in_np:,.0f} м² НП); отдельно стоящие нежилые здания "
            f"({standalone_np:,.0f} м² НП) обеспечиваются своим паркингом и здесь "
            f"не считаются".replace(",", " "))

    # --- плата за ВРИ ----------------------------------------------------
    # Жильё — по ставке базы. Нежилые функции — по той же ставке, поправленной
    # отношением базовых стоимостей: формула линейна, коэффициент аренды и
    # индекс те же, и вводить их руками не надо (вписанные руками 25 вместо
    # 0,1497 дали 238 млрд ₽ платы, 20.08.2026).
    bases = dict((baseline.get("vri_base_costs_by_use") or {}))
    base_mkd = float(bases.get("mkd") or 0.0)
    vri_lines = []
    vri_total = 0.0
    # Плата за смену ВРИ берётся при обоих правах — отличается делитель: у
    # собственности 1,00001, у аренды жилья 1,001 (формула калькулятора, класс
    # Df). Разница 0,099%. Отказывать при аренде было неверно: модель показывала
    # ноль там, где платят (владелец, 20.08.2026).
    land_right = str(areas.get("land_right") or "ownership").strip().lower()
    leased = land_right in ("lease", "аренда", "rent")
    # Ставка снята с расчёта калькулятора, а он считает для собственности.
    right_factor = (_VRI_RIGHT_DIVISOR["ownership"] / _VRI_RIGHT_DIVISOR["lease"]
                    if leased else 1.0)
    if leased:
        warnings.append(
            "право на участок — аренда: ставка снята с расчёта для собственности, "
            "к плате применён делитель аренды 1,001 (разница 0,099%). Повышенная "
            "составляющая первого года по 273-ПП — отдельный платёж, здесь не считается")
    vri_available = True
    residential_payment = vri_rate * (res_spp + built_in_spp) * right_factor
    if residential_payment:
        vri_lines.append({"type": "mkd", "spp_sqm": round(res_spp + built_in_spp, 2),
                          "payment_mln": round(residential_payment, 3),
                          "rate_mln_per_sqm": vri_rate})
        vri_total += residential_payment
    # Отдельно стоящее нежилое здание в плату НЕ идёт (владелец, 20.08.2026:
    # «смену ВРИ калькулятор считает по жилью и нежилью первого этажа; зачем нам
    # считать 65 000 отдельно стоящего здания офисов»). Прежде оно считалось по
    # той же ставке, поправленной отношением базовых стоимостей, и на ТЭП по
    # решению ГЗК давало 3 656 млн ₽ поверх 1 444 млн жилья: плата выходила
    # 5 100 вместо 1 444, и число выглядело посчитанным.
    #
    # Считать его всё же приходится — но отдельно и не в итог: свод норм 593-ПП
    # даёт иному нежилому функциональный коэффициент 0,001, то есть плату почти
    # нулевую, а таблица базовых стоимостей калькулятора несёт для торговли и
    # офисов настоящие числа. Что из этого применит город к отдельному зданию,
    # ни выгрузка, ни свод не решают. Молчать нельзя, приписывать к плате —
    # тоже: строка стоит рядом с суммой и названа справочной.
    standalone_total = 0.0
    for use, spp in sorted(nonres_by_use.items()):
        if spp <= 0:
            continue
        base_cost = bases.get(use)
        if base_cost is None or base_mkd <= 0:
            warnings.append(
                f"{use}: нет базовой стоимости в исходном расчёте — справочную плату "
                f"по этим {spp:,.0f} м² посчитать не из чего".replace(",", " "))
            continue
        rate = (vri_rate * float(base_cost) / base_mkd * right_factor
                if float(base_cost) > 0 else 0.0)
        payment = rate * spp
        standalone_total += payment
        vri_lines.append({"type": use, "spp_sqm": round(spp, 2),
                          "payment_mln": round(payment, 3), "rate_mln_per_sqm": rate,
                          "in_total": False,
                          "note": "отдельно стоящее здание — в плату не включено"})
    if standalone_total > 0:
        warnings.append(
            f"отдельно стоящие нежилые здания в плату за ВРИ не включены "
            f"({standalone_total:,.1f} млн ₽ справочно): город считает смену ВРИ по жилью "
            f"и встроенным помещениям первых этажей. По 593-ПП у иного нежилого "
            f"функциональный коэффициент 0,001 — плата почти нулевая, но применит ли "
            f"город его к отдельному зданию, выгрузка не решает".replace(",", " "))

    # --- самопроверка обратным ходом -------------------------------------
    # Проверять имеет смысл только то, что считается НЕ снятой с базы ставкой:
    # плата за ВРИ и постоянные места по ставке воспроизводят базу тождественно,
    # какой бы база ни была, и такая «проверка» ничего не значит. Настоящие
    # проверки — там, где у нас своя формула против числа города: население по
    # 33 м², места по нормативам зоны и гостевые как десятая часть постоянных.
    #
    # Каждая сверка помечена своей половиной (`scope`): население и места
    # соцобъектов — «social», машино-места — «parking», ставка ВРИ — «vri».
    # Переключатель населения для соцобъектов меняет только соцполовину и
    # читает только её вердикт (`social_matches_baseline`): машино-места,
    # которые он не трогает, не повод отказывать в пересчёте мест ДОО.
    self_check: dict[str, Any] = {"checked": [], "mismatch": [],
                                  "mismatch_by_scope": {"social": [], "parking": [], "vri": []}}

    def compare(name: str, got: Any, want: Any, scope: str,
                low: Any = None, high: Any = None) -> None:
        """`low`..`high` — что даёт та же формула на границах округления входа."""
        entry = {"name": name, "baseline": want, "recalculated": got, "scope": scope}
        self_check["checked"].append(entry)
        if not want or got == want:
            return
        if low is not None and high is not None and low <= want <= high:
            entry["within_rounding"] = True
            return
        line = f"{name}: {got} против {want}"
        self_check["mismatch"].append(line)
        self_check["mismatch_by_scope"][scope].append(line)

    # Ставка, снятая с базы, обязана сходиться с формулой города: та же плата
    # считается как 1,8964 × СПП × коэффициент аренды × базовая × индекс /
    # делитель. Есть коэффициент и базовая — считаем и сверяем; расходится
    # больше чем на 2% (индексация квартала) — это не ставка, а ошибка чтения
    # выгрузки, и пропорция на ней даст уверенно неверные деньги.
    base_rent = num(baseline, "rent_coefficient")
    if vri_rate > 0 and base_rent > 0 and base_mkd > 0:
        formula_rate = 1.8964 * base_rent * base_mkd / 1.00001 / 1e6
        drift = abs(vri_rate - formula_rate) / formula_rate
        self_check["checked"].append({
            "name": "ставка ВРИ против формулы города",
            "baseline": round(vri_rate, 6), "recalculated": round(formula_rate, 6),
            "drift_pct": round(drift * 100, 2)})
        if drift > 0.05:
            line = (f"ставка ВРИ {vri_rate:.6f} млн/м² расходится с формулой города "
                    f"{formula_rate:.6f} на {drift*100:.1f}% — так индексация не дрейфует, "
                    f"похоже на ошибку чтения выгрузки")
            self_check["mismatch"].append(line)
            self_check["mismatch_by_scope"]["vri"].append(line)

    # Соцполовина сверяется с допуском округления норматива: площадь квартир
    # выгрузка печатает целыми метрами (±0,5 м²), а места — ⌈норма × жители /
    # 1000⌉. Число, которое формула даёт на границе округления входа, — не
    # расхождение. Дальше границы — расхождение, и пересчёт мест на нём не
    # строится.
    if base_apartments > 0:
        compare("население", math.ceil(base_apartments / 33.0), int(num(baseline, "population")),
                "social", low=math.ceil((base_apartments - 0.5) / 33.0),
                high=math.ceil((base_apartments + 0.5) / 33.0))
        base_pop = int(num(baseline, "population"))
        if base_pop:
            base_zone_two = bool(baseline.get("calculation_zone") == "2")
            compare("места ДОО",
                    math.ceil((63 if base_zone_two else 44) * base_pop / 1000),
                    int(num(baseline, "required_kindergarten_places")), "social")
            compare("места школы",
                    math.ceil((124 if base_zone_two else 90) * base_pop / 1000),
                    int(num(baseline, "required_school_places")), "social")
            compare("мощность поликлиники",
                    math.ceil(19 * base_pop / 1000),
                    int(num(baseline, "required_clinic_capacity")), "social")
    base_permanent = int(num(baseline, "parking_permanent"))
    if base_permanent:
        compare("гостевые машино-места", math.ceil(base_permanent / 10.0),
                int(num(baseline, "parking_guest")), "parking")
    # Приобъектные: ставка (с СПП × 0,9) на НАПЕЧАТАННОЙ НП базы обязана
    # вернуть число базы — две записи одной площади в выгрузке согласны друг
    # с другом; не согласны (прочитана не та строка) — это расхождение, а не
    # расчёт. Пока строки не было, 94 против 93 на исходном ТЭП шло молча.
    base_attached = int(num(baseline, "parking_attached"))
    # НП выгрузка печатает целыми метрами, а ставка снята с СПП × 0,9 — дробной:
    # 1 365 × 0,9 = 1 228,5 печатается как 1 229, и ⌈ставка × 1 229⌉ даёт 17
    # там, где город сказал 16. Это округление печати, а не не та строка: на
    # границах ±0,5 м² формула обязана дать число базы, и тогда записи согласны.
    if base_attached and base_built_in_np > 0 and attached_rate > 0:
        compare("приобъектные машино-места",
                _ceil_places(base_built_in_np * attached_rate), base_attached, "parking",
                low=_ceil_places((base_built_in_np - 0.5) * attached_rate),
                high=_ceil_places((base_built_in_np + 0.5) * attached_rate))
        if regime == "2118_2026" and base_apartments > 0:
            # Настоящая проверка формулы: город посчитал 897 мест на 77 696 м²
            # квартир — ровно столько даёт пункт 1. Разойдётся — значит база
            # считалась по прежней редакции или норматив снова сменился.
            compare("постоянные машино-места",
                    moscow_permanent_parking_2118(base_apartments), base_permanent, "parking")
    self_check["matches_baseline"] = not self_check["mismatch"]
    self_check["social_matches_baseline"] = not self_check["mismatch_by_scope"]["social"]
    if self_check["mismatch"]:
        warnings.append("пересчёт не воспроизводит исходный расчёт: "
                        + "; ".join(self_check["mismatch"]))

    return {
        "method": "glavapu_baseline_rescale",
        "title": "Пересчёт по параметрам исходного расчёта ГлавАПУ",
        "population": norms["population"],
        "social_population": norms["social_population"],
        "social_population_basis": norms["social_population_basis"],
        "social_population_method": norms["social_population_method"],
        "places": places,
        "compensation_mln": round(sum(compensation.values()), 3),
        "compensation_breakdown_mln": compensation,
        "parking": {"permanent": permanent, "guest": guest, "attached": attached,
                    "total": permanent + guest + attached,
                    "regime": regime, "basis": parking_basis},
        "vri_lines": vri_lines,
        "vri_total_mln": round(vri_total, 3),
        "vri_available": vri_available,
        "land_right": land_right,
        "land_right_factor": right_factor,
        "rates": rates,
        "baseline": {
            "vri_mln": round(vri_base, 3),
            "compensation_mln": round(num(baseline, "social_compensation_kindergarten_mln")
                                      + num(baseline, "social_compensation_school_mln")
                                      + num(baseline, "social_compensation_clinic_mln"), 3),
            "parking_total": int(num(baseline, "parking_permanent")
                                 + num(baseline, "parking_guest")
                                 + num(baseline, "parking_attached")),
            "population": int(num(baseline, "population")),
            "places": {"kindergarten": int(num(baseline, "required_kindergarten_places")),
                       "school": int(num(baseline, "required_school_places")),
                       "clinic": int(num(baseline, "required_clinic_capacity"))},
        },
        "self_check": self_check,
        "warnings": warnings,
    }


# Нормативы соцобъектов — мест (посещений в смену) на 1000 жителей по
# расчётной зоне. Один источник: ими считает `tep_derived_norms`, их же сверка
# с калькулятором ГлавАПУ ставит рядом с «Нормативом ДОО / школ» его листа
# «Параметры территории».
SOCIAL_NORMS_PER_1000: dict[str, dict[str, int]] = {
    "kindergarten": {"1": 44, "2": 63},
    "school": {"1": 90, "2": 124},
    "clinic": {"1": 19, "2": 19},
}


def tep_derived_norms(*, apartment_area_sqm: float, residential_living_spp_sqm: float,
                      nonresidential_np_sqm: float = 0.0,
                      k1: float = 1.0, k2: float = 1.0,
                      zone_two: bool = False,
                      upks_rub: float = 0.0,
                      sqm_per_job: float = 32.0,
                      parking_norm_regime: str = "2118_2026",
                      apartment_count: float = 0.0,
                      social_population_method: str = SOCIAL_POPULATION_DEFAULT) -> dict[str, Any]:
    """Что следует из введённого руками ТЭП: население, соцпотребность,
    компенсация, машино-места, места приложения труда.

    `apartment_count` — число квартир, если оно известно: тогда постоянные
    места считаются пунктом 2 по средней квартире, иначе пунктом 1 от площади.

    Формулы городские и сверены на выгрузке штатного калькулятора
    (77:01:0004023, 20.08.2026): постоянные места 897, гостевые 90,
    приобъектные 12 — воспроизводятся до единицы.

    `residential_living_spp_sqm` — СПП **жилая** (строка 7.1 выгрузки, у нас
    «ТЭП → Квартиры → ГНС»), без нежилой части жилых зданий. В действующем
    порядке она на постоянные места не влияет вовсе — они считаются от площади
    квартир, — но нужна прежнему режиму и печатается в основании. Плата за ВРИ
    берётся от полной СПП жилых зданий, включая встроенные помещения.

    Постоянные места — приложение 5 к 945-ПП в редакции 2118-ПП: тот же расчёт,
    что и в пересчёте по параметрам исходной выгрузки. Два наших ответа на одни
    метры расходиться не могут: `parking_norm_regime="legacy_945"` возвращает
    прежнюю строку (НП жилая / 90 × К1) — она нужна, чтобы сверяться с
    калькулятором, а не как второе мнение о норме.
    """
    apartments = max(0.0, float(apartment_area_sqm or 0.0))
    residential_spp = max(0.0, float(residential_living_spp_sqm or 0.0))
    nonresidential_np = max(0.0, float(nonresidential_np_sqm or 0.0))
    k1 = max(0.0, float(k1 or 0.0))
    k2 = max(0.0, float(k2 or 0.0))
    upks = max(0.0, float(upks_rub or 0.0))

    population = math.ceil(apartments / 33.0) if apartments > 0 else 0
    # Соцобъекты — от населения выбранным способом; число квартир для
    # машино-мест по-прежнему из населения по норме (2118-ПП).
    social_population, social_basis, social_method = moscow_social_population(
        apartments, apartment_count, social_population_method)
    zone = "2" if zone_two else "1"
    dou = (math.ceil(SOCIAL_NORMS_PER_1000["kindergarten"][zone] * social_population / 1000)
           if social_population else 0)
    school = (math.ceil(SOCIAL_NORMS_PER_1000["school"][zone] * social_population / 1000)
              if social_population else 0)
    clinic = (math.ceil(SOCIAL_NORMS_PER_1000["clinic"][zone] * social_population / 1000)
              if social_population else 0)

    residential_np = residential_spp * 0.9
    regime = str(parking_norm_regime or "2118_2026").strip().lower()
    if regime not in _PARKING_REGIMES:
        regime = "2118_2026"
    if regime == "2118_2026":
        permanent, parking_basis = moscow_permanent_parking_by_average(
            apartments, apartment_count)
        parking_basis = "постоянные места — " + parking_basis
    else:
        # Прежняя строка города: от НАЗЕМНОЙ ЖИЛОЙ площади (90% жилой СПП), а не
        # от всей СПП жилых зданий — на выгрузке первое даёт 897 мест, второе 954.
        permanent = math.ceil(residential_np / 90.0 * k1) if residential_np and k1 else 0
        parking_basis = ("постоянные места — прежняя строка города: НП жилая / 90 × К1 "
                         f"{k1:g}".replace(".", ",") + " (режим сверки с калькулятором)")
    guest = math.ceil(permanent / 10.0) if permanent else 0
    onsite = math.ceil(nonresidential_np / 90.0 * k1 * k2) if nonresidential_np and k1 and k2 else 0

    def compensation(places: float, uupss_th: float, land_sqm: float, factor: float) -> float:
        if places <= 0 or upks <= 0:
            return 0.0
        return factor * (uupss_th * places / 1000.0 + places * land_sqm * upks / 1e6)

    # Земля на место — по мощности объекта, как у калькулятора: ДОО 35 м² до
    # 150 мест, дальше 32; школа 19 до 900, 16 до 1 500, дальше 14. Мощность
    # поликлиники в компенсации — взрослая (13,2) + детская (5,8) на тысячу:
    # на Нагатино 101 + 45 = 146 при смешанной 145 (выгрузка 06.10.2026).
    clinic_parts = ((math.ceil(13.2 * social_population / 1000)
                     + math.ceil(5.8 * social_population / 1000))
                    if social_population else 0)
    comp_dou = compensation(dou, 4799.71, 35.0 if dou <= 150 else 32.0, 1.2)
    comp_school = compensation(school, 4578.69,
                               19.0 if school <= 900 else 16.0 if school <= 1500 else 14.0, 1.2)
    comp_clinic = compensation(clinic_parts, 7887.92, 30.0, 1.0)
    return {
        "population": population,
        "apartment_units": math.ceil(population / 2.1) if population else 0,
        "social_population": social_population,
        "social_population_basis": social_basis,
        "social_population_method": social_method,
        "kindergarten_places": dou,
        "school_places": school,
        "clinic_capacity": clinic,
        "compensation_mln": round(comp_dou + comp_school + comp_clinic, 3),
        "compensation_breakdown_mln": {
            "kindergarten": round(comp_dou, 3),
            "school": round(comp_school, 3),
            "clinic": round(comp_clinic, 3),
        },
        "parking_permanent": permanent,
        "parking_guest": guest,
        "parking_onsite": onsite,
        "parking_total": permanent + guest + onsite,
        "parking_norm_regime": regime,
        "parking_basis": parking_basis,
        # Места приложения труда — основание льготы по плате за ВРИ (1874-ПП,
        # прил. 1 п. 1.6; 593-ПП прил. 2 п. 86 / п. 2(2); 3135-ПП — про
        # инфраструктурный договор, а не про льготу),
        # у калькулятора для неё своя строка 52 «Льгота на стр-во жилья за
        # создание МПТ». Норма — 32 м² НП на место с округлением ВНИЗ, как в
        # коде калькулятора (таблица Q, места по ВРИ — lodash `floor`;
        # 6 867 м² → 214, а к ближайшему вышло бы 215; Нагатино 22 217 м² →
        # 694). У торговли у калькулятора 45 — поэтому делитель параметр и
        # печатается вместе с ответом.
        "jobs": math.floor(nonresidential_np / sqm_per_job) if nonresidential_np and sqm_per_job else 0,
        "sqm_per_job": float(sqm_per_job or 0.0),
        "upks_rub": upks,
        "k1": k1,
        "k2": k2,
        "zone_two": bool(zone_two),
        # Компенсация без УПКС не считается, и ноль здесь означал бы «бесплатно».
        "missing": ([] if upks > 0 or not population
                    else ["УПКС квартала не задан — компенсация не посчитана"]),
    }


# --- нормативная потребность объектов в машино-местах -----------------------
# Норма объявлена один раз, в `parking_norms`. Здесь только сборка: какой
# продукт какой функцией считается, какие метры ему принадлежат и куда его
# места ставит человек.
#
# Правило владельца (24.08.2026): МЕСТА ОБЪЕКТА ПРИНАДЛЕЖАТ ОБЪЕКТУ. Норматив
# порождает объект, а не проект целиком: у офисника в третьей очереди своя
# потребность, у ТЦ во второй — своя. Прибавлять их к общей куче нельзя, потому
# что куча разносится по очередям своими правилами и приезжает не туда.
#
# Куда ставить места — решение владельца 05.09.2026: «у осз должны быть паркинг
# или подземные или наземные напервых этажах». Двух мест ровно два, и общий
# наземный паркинг проекта в них НЕ входит — объекты его больше не наполняют.
#
# НАДЗЕМНЫЙ и НАЗЕМНЫЙ — разные вещи, и различие стоило владельцу отдельной
# поправки («стоп надземные не вычитается, я ошибся, вычитается наземный»).
# Надземный — этажи самого здания: его метры уже внутри ГНС объекта, и ГНС
# не меняется. Наземный — отдельная стоянка (`above_parking`), её метры свои,
# из объекта они вычитаются; в модели у неё своя строка ТЭП и мера «место».
#
# Выбор — ДВА ЧИСЛА, а не переключатель («При выборе парковок надо сделать
# выбор, что идет в надземные и подземные с контролем суммы по обязательствам
# согласном нормам»). Переключатель сумму сводит по построению, и проверять в
# нём нечего; два числа принадлежат человеку и с нормой могут не сойтись —
# ради этого расхождения контроль и написан.
# Имя функции у юрисдикций СВОЁ. У Москвы это код ВРИ (спорт — 5.1), у области
# — строка приложения № 10, и называются они по-разному: «спорт» против
# «оздоровительные комплексы». Одно имя на обе таблицы однажды нашло бы в
# соседней не ту строку — а выглядело бы это как посчитанный норматив.
_PARKING_DEMAND_PRODUCTS = (
    # (ключ ТЭП, функция Москвы, функция области, встроенность)
    ("ground_commercial", "shop", "shop", True),
    ("offices", "office", "office", False),
    ("standalone_retail", "mall", "mall", False),
    ("sports", "sport", "fitness", False),
)
# Второй объект нормируется функцией своего продукта: второй офисник — офис.
_PARKING_DEMAND_PRODUCTS = _PARKING_DEMAND_PRODUCTS + tuple(
    (obj.key, *next(item[1:] for item in _PARKING_DEMAND_PRODUCTS if item[0] == obj.family))
    for obj in STANDALONE_OBJECTS
    if obj.family and any(item[0] == obj.family for item in _PARKING_DEMAND_PRODUCTS))

# Соцобъекты квартала нормируются той же формулой приложения 6 к 945-ПП:
# ДОО и школа — образование (ВРИ 3.5), поликлиника — здравоохранение (3.4).
# В приобъектные места объектов (`required_total`) они не входят — у них свой
# итог, нужный только нормативной потребности проекта целиком (#656).
_PARKING_SOCIAL_PRODUCTS = (
    ("kindergarten", "education", "kindergarten", False),
    ("school", "education", "school", False),
    ("clinic", "healthcare", "clinic", False),
)
_PARKING_SOCIAL_KEYS = frozenset(item[0] for item in _PARKING_SOCIAL_PRODUCTS)

# Назначение отдельно стоящего объекта «ФОК / медцентр» решает его норматив.
#
# Объект один: двух таких в проекте разом не бывает (владелец, 15.09.2026),
# поэтому вместо пятого объекта у ФОКа появилось назначение. Норматив у них
# РАЗНЫЙ, и это не оттенок: у Москвы спорт — код ВРИ 5.1 (200 м² ННП на место),
# здравоохранение — 3.4 (300 м²), то есть в полтора раза меньше мест. Оставь
# медцентр на спортивном нормативе — и лишние места выглядели бы посчитанными.
#
# У области строки здравоохранения НЕТ ВОВСЕ: приложение № 10 знает только
# оздоровительные комплексы, а п. 5.12 в редакции 774-ПП даёт правило «1 место
# на 50 м² общей площади» для нежилого здания без конкретной функции — оно и
# применяется. Поликлиники это правило исключает прямым текстом, но поликлиника
# города и коммерческий медцентр — разные вещи: первая приходит нормативом
# соцнагрузки, второй строится на продажу. Отнести медцентр к исключению значит
# оставить объект вовсе без норматива; отнести к фитнесу — посчитать по чужой
# строке. Взято правило без функции, и основание это называет.
_SPORTS_PURPOSE_FUNCTIONS = {
    "sport": ("sport", "fitness"),
    "healthcare": ("healthcare", "healthcare"),
}


def sports_parking_functions(inputs: dict[str, Any] | None,
                             purpose_key: str = "sports_purpose") -> tuple[str, str]:
    """Функции норматива для объекта «ФОК / медцентр»: (Москва, область).

    У области строки здравоохранения в таблице нет, и `mo_required` отвечает на
    неё правилом п. 5.12 «1 место на 50 м²», называя это допущением, — своего
    костыля здесь не нужно. Назначение у каждого экземпляра ФОКа своё
    (`purpose_key`).
    """
    purpose = str(((inputs or {}).get(purpose_key) or "sport")).strip().lower()
    return _SPORTS_PURPOSE_FUNCTIONS.get(purpose, _SPORTS_PURPOSE_FUNCTIONS["sport"])



OBJECT_PARKING_AREA_DEFAULT = 35.0
OBJECT_PARKING_OVER_AREA_DEFAULT = 25.0


def standalone_object_saleable(inputs: dict[str, Any], tep: dict[str, Any] | None,
                               key: str) -> float:
    """Продаваемая площадь ОСЗ после пятна мест первых этажей. Ответ один.

    Ровно формула книги v4 (K26/K46/K129 «Расчётная продаваемая площадь»):
    (GBA вводных − места первых этажей × площадь места) × продаваемая / GBA
    вводных. Себестоимость объекта движок и книга берут с той же GBA вводных;
    выручка в движке после #481 читала строку ТЭП, и при ТЭП, пришедшем
    отдельно от вводных (API, бот), продавала 16 575 м² против 5 840 в книге.
    Её же читают строки отчёта: объём «Офисы / МФОЦ» стоял до паркинга, а
    выручка — после, и средняя цена метра выходила ниже назначенной.
    """
    obj = next((item for item in standalone_objects() if item.key == key), None)
    if obj is None or obj.measure == "spaces":
        return 0.0
    base_saleable = max(0.0, n(inputs, f"{obj.prefix}_saleable_sqm"))
    base_gba = max(0.0, n(inputs, f"{obj.prefix}_gba_sqm"))
    if base_gba <= 0:
        return 0.0
    row = (tep or {}).get(key) or {}
    over_gba = max(0.0, n(row, "parking_over_units")) * (
        n(inputs, "object_parking_over_area_per_space_sqm", OBJECT_PARKING_OVER_AREA_DEFAULT)
        or OBJECT_PARKING_OVER_AREA_DEFAULT)
    return max(0.0, base_gba - over_gba) * base_saleable / base_gba


def object_sold_saleable(inputs: dict[str, Any], tep: dict[str, Any] | None,
                         key: str) -> float:
    """Сколько метров объекта ПРОДАЁТСЯ — для структуры продукта, отчёта и сводки.

    Строка ТЭП объекта держит площадь здания: места первых этажей её не
    уменьшают (владелец, 29.09.2026: «оставь в структуре»). Продаётся остаток
    — `standalone_object_saleable`. Строка без продаваемой (объект выключен,
    передан) или объект без вводной ГНС отвечают своей строкой.
    """
    row = (tep or {}).get(key) or {}
    obj = _BY_KEY.get(key)
    if (obj is None or obj.measure == "spaces" or n(row, "saleable") <= 0
            or n(inputs, f"{obj.prefix}_gba_sqm") <= 0):
        return n(row, "saleable")
    return standalone_object_saleable(inputs, tep, key)


def object_parking_by_hand(inputs: dict[str, Any], prefix: str) -> bool:
    """Места гаража объекта заданы человеком? Ответ один на проект и очередь.

    Страница ведёт список тронутых руками (`_parking_by_hand`). Пока он есть,
    объект вне списка — поле заполнила норма, и оно идёт за ТЭП, а не замирает
    на вчерашнем числе. Проект без списка (сохранён до него) — непустое поле
    человеческое. Пометка нормы (`_parking_by_norm`) говорит «её число» прямо.

    Прежде ответов было два: очередь считала ручным всякое непустое поле, а
    проект — по списку, и одни и те же вводные строили разные гаражи в своде и
    в очередях.
    """
    key = str(prefix)
    if key in set(inputs.get("_phase_parking_by_hand") or ()):
        return True
    marks = inputs.get("_parking_by_hand")
    if marks is not None:
        return key in set(marks)
    if key in set(inputs.get("_parking_by_norm") or ()):
        return False
    return any(n(inputs, f"{prefix}_parking_{kind}_spaces") > 0 for kind in ("under", "over"))


# Своё поле площади места гаража объекта удалено (#541): теперь это норматив
# класса. Проекты, сохранённые раньше, несут прежний ключ, и молча терять
# вписанное туда число нельзя — сохранённое состояние накладывается на
# умолчания, а не исчезает. Прежнее умолчание поля было одно на все классы —
# 35 м², — и оно решением человека не считается.
OBJECT_PARKING_AREA_SAVED_KEY = "object_parking_area_per_space_sqm"
OBJECT_PARKING_AREA_OLD_DEFAULT = 35.0


def object_parking_area_saved(inputs: dict[str, Any]) -> dict[str, Any] | None:
    """Число прежнего поля из сохранённого проекта и его судьба.

    `None` — ключа нет, он пуст или совпадает с нормативом класса: сказать
    нечего. Иначе `origin`:
    - `manual` — число вписано руками, оно и действует для гаража объекта;
    - `old_default` — стояло прежнее умолчание 35 м²: действует норматив
      класса, а человеку сказано, что число заменено.
    """
    raw = (inputs or {}).get(OBJECT_PARKING_AREA_SAVED_KEY)
    if raw in (None, "") or isinstance(raw, bool):
        return None
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(value) or value <= 0:
        return None
    norm = underground_area_per_space(inputs) or OBJECT_PARKING_AREA_DEFAULT
    if math.isclose(value, norm, abs_tol=1e-9):
        return None
    origin = ("old_default"
              if math.isclose(value, OBJECT_PARKING_AREA_OLD_DEFAULT, abs_tol=1e-9)
              else "manual")
    return {"value": value, "norm": norm, "origin": origin}


def object_parking_area_per_space(inputs: dict[str, Any]) -> float:
    """Площадь одного подземного места гаража ОСЗ — норматив класса.

    Ответ один на гараж дома и гараж объекта: `underground_area_per_space`.
    Исключение одно — число, вписанное руками в прежнее поле сохранённого
    проекта (`object_parking_area_saved`). Книга пишет в K158 это же число
    (`_V4_DERIVED_INPUTS`).
    """
    saved = object_parking_area_saved(inputs)
    if saved and saved["origin"] == "manual":
        return saved["value"]
    return underground_area_per_space(inputs) or OBJECT_PARKING_AREA_DEFAULT


def _object_parking_area_saved_line(saved: dict[str, Any]) -> str:
    value = _pdf_num(saved["value"], 1).replace(",0", "")
    norm = _pdf_num(saved["norm"], 1).replace(",0", "")
    if saved["origin"] == "manual":
        return (f"площадь подземного места гаража объектов {value} м² — из сохранённого "
                f"проекта, вписана руками; норматив класса {norm} м²")
    return (f"в сохранённом проекте площадь места гаража объектов стояла {value} м² — "
            f"прежнее умолчание; теперь берётся норматив класса {norm} м²")


def apply_object_parking(inputs: dict[str, Any], tep: dict[str, Any]) -> dict[str, Any]:
    """Разместить СОБСТВЕННЫЙ паркинг объектов по строкам ТЭП.

    Подземные места добавляют отдельную подземную площадь объекта. Места на
    первых этажах занимают часть уже существующей наземной ГНС: ГНС объекта
    не растёт и не уменьшается, а общая, полезная и продаваемая площади
    пересчитываются от остатка ГНС в тех же долях, которые были у объекта до
    размещения паркинга.
    """
    # Книга может вызвать расчёт повторно на той же копии ТЭП. Первый проход
    # запоминает исходные площади, а следующий обязан быть идемпотентным.
    # Но ТЭП может быть ПЕРЕСЧИТАН между проходами на той же структуре: прежняя
    # реализация безусловно восстанавливала старый _object_parking_base_* и
    # тем самым отменяла свежий ТЭП. Поэтому рядом с базой держим последнее
    # значение, которое поставили МЫ. Если текущее значение уже отличается от
    # него, это внешнее изменение — оно становится новой базой.
    for tep_key, prefix, _enabled_key, _sellable in OBJECT_PARKING_OBJECTS:
        row = (tep or {}).get(tep_key) or None
        if row is None:
            continue
        # Продаваемая объекта — вводная, а не присланная строка: страница
        # кладёт в свою строку ответ прошлого расчёта, и строка, сохранённая,
        # пока движок вычитал в ней места первых этажей, несёт уже уменьшенное
        # число — следующий расчёт вычитал бы его снова (строка ТЭП 50 709 м²
        # при выручке от 66 613, владелец, 29.09.2026).
        # Строка приводится к вводной одной долей: пропорции общей, полезной и
        # продаваемой у неё свои, и место мест в них не меняет.
        # Строка с другой ГНС — это другой ТЭП (свежий пересчёт, доля очереди),
        # и вводная о ней не говорит: тогда база — сама строка.
        anchor = max(0.0, n(inputs, f"{prefix}_saleable_sqm"))
        sent = n(row, "saleable")
        same_object = math.isclose(n(row, "gns"), n(inputs, f"{prefix}_gba_sqm"),
                                   rel_tol=1e-9, abs_tol=0.05)
        if (same_object and anchor > 0 and sent > 0
                and not math.isclose(anchor, sent, rel_tol=1e-9, abs_tol=1e-6)):
            scale = anchor / sent
            for field in ("total_area", "useful", "saleable"):
                row[field] = n(row, field) * scale
        for field in ("total_area", "useful", "saleable"):
            base_key = f"_object_parking_base_{field}"
            applied_key = f"_object_parking_applied_{field}"
            current = n(row, field)
            if base_key not in row:
                row[base_key] = current
                continue
            applied = row.get(applied_key)
            if applied is not None and not math.isclose(
                    current, float(applied), rel_tol=1e-10, abs_tol=1e-6):
                row[base_key] = current
            else:
                row[field] = n(row, base_key)

    demand = parking_demand(inputs, tep)
    # Площадь подземного места гаража объекта — та же, что у паркинга дома:
    # норматив класса (35 / 37,5 / 40 м²). Своё поле у гаража было второй
    # копией того же числа и при смене класса не двигалось (владелец,
    # 27.09.2026: блок «Нормативы парковки нежилья» во вводных не нужен).
    under_per_space = object_parking_area_per_space(inputs)
    over_per_space = (
        n(inputs, "object_parking_over_area_per_space_sqm", OBJECT_PARKING_OVER_AREA_DEFAULT)
        or OBJECT_PARKING_OVER_AREA_DEFAULT
    )
    required_by_key = {row.get("tep_key"): row.get("required_spaces")
                       for row in (demand.get("rows") or [])
                       if row.get("required_spaces")}
    own: list[dict[str, Any]] = []
    layout_warnings: list[str] = []

    for tep_key, prefix, enabled_key, sellable in OBJECT_PARKING_OBJECTS:
        row = (tep or {}).get(tep_key) or None
        if row is None:
            continue
        enabled = b(inputs, enabled_key)
        under = max(0, int(n(inputs, f"{prefix}_parking_under_spaces"))) if enabled else 0
        over = max(0, int(n(inputs, f"{prefix}_parking_over_spaces"))) if enabled else 0

        by_norm = False
        take_norm = enabled and not object_parking_by_hand(inputs, prefix)
        if take_norm:
            required = int((required_by_key.get(tep_key) or 0))
            if required > 0:
                under, over, by_norm = required, 0, True
            else:
                under, over = 0, 0

        guests = 0
        if sellable and enabled:
            # Половина — вверх, как ROUND книги (`xlsx_book_v4_objects`): round()
            # Python ведёт её к чётному, и на 25 местах при 10% движок давал 2
            # гостевых, а книга 3 — выручка расходилась на одно место.
            share = (under + over) * n(inputs, f"{prefix}_parking_guest_pct") / 100.0
            guests = int(math.floor(round(share, 9) + 0.5))
            guests = max(0, min(guests, under + over))

        row["under_gns"] = under * under_per_space
        row["parking_under_units"] = float(under)
        row["parking_over_units"] = float(over)
        row["parking_units"] = float(under + over)
        row["parking_saleable_units"] = (
            float(max(0, under + over - guests)) if sellable else 0.0
        )
        # Гостевые — число движка, а не разность на экране: у ТЦ и ФОКа места
        # не продаются, и «построено − продаётся» называло гостевыми все места.
        # Поле перенесено из ветки Codex fix/object-parking-tep-expense-units.
        row["parking_guest_units"] = float(guests)

        base_gns = max(0.0, n(row, "gns"))
        over_gba = over * over_per_space
        remaining_gba = max(0.0, base_gns - over_gba)
        ratio = (remaining_gba / base_gns) if base_gns > 0 else (1.0 if over_gba <= 0 else 0.0)

        # Строка ТЭП объекта остаётся площадью ЗДАНИЯ: места первых этажей её
        # не уменьшают. Вычет живёт в структуре продукта — продаётся остаток,
        # `standalone_object_saleable`, — и называется здесь числом (владелец,
        # 29.09.2026: «оставь в структуре»). Прежде строка уменьшалась, и
        # ТЭП, продукт и присланная назад строка давали три разных числа.
        losses: dict[str, float] = {}
        for field in ("total_area", "useful", "saleable"):
            base = n(row, f"_object_parking_base_{field}")
            row[field] = base
            row[f"_object_parking_applied_{field}"] = base
            losses[field] = max(0.0, base - max(0.0, base * ratio))
        row["parking_saleable_after_sqm"] = max(0.0, n(row, "saleable") - losses["saleable"])

        overflow = max(0.0, over_gba - base_gns)
        if overflow > 1e-9:
            label = str(row.get("label") or tep_key)
            layout_warnings.append(
                f"{label}: паркинг первых этажей требует {over_gba:,.0f} м² ГНС, "
                f"а у объекта только {base_gns:,.0f} м²; площадь объекта не увеличена"
            )

        row["parking_over_gba_sqm"] = over_gba
        row["parking_layout_overflow_sqm"] = overflow
        row["parking_saleable_taken"] = losses["saleable"]

        own.append({
            "tep_key": tep_key,
            "prefix": prefix,
            "label": row.get("label") or tep_key,
            "enabled": enabled,
            "under_spaces": under,
            "over_spaces": over,
            "units": under + over,
            "guest_spaces": guests,
            "by_norm": by_norm,
            "required_spaces": int(required_by_key.get(tep_key) or 0),
            "sellable": sellable,
            "saleable_units": int(row["parking_saleable_units"]),
            "under_gns": row["under_gns"],
            "over_gba_sqm": over_gba,
            "layout_overflow_sqm": overflow,
            "saleable_taken_sqm": losses["saleable"],
        })

    demand["own"] = own
    demand["own_units"] = sum(item["units"] for item in own if item["enabled"])
    demand["own_saleable_units"] = sum(item["saleable_units"] for item in own if item["enabled"])
    demand["own_under_gns"] = sum(item["under_gns"] for item in own if item["enabled"])
    demand["area_per_space_sqm"] = under_per_space
    demand["over_area_per_space_sqm"] = over_per_space
    # Происхождение площади места — рядом с числом: норматив класса и число
    # из сохранённого проекта на экране выглядят одинаково.
    saved_area = object_parking_area_saved(inputs)
    demand["area_per_space_source"] = (
        "saved_manual" if saved_area and saved_area["origin"] == "manual" else "class_norm")
    demand["area_per_space_saved"] = saved_area
    if saved_area and any(item["under_spaces"] for item in own if item["enabled"]):
        demand.setdefault("assumptions", []).append(_object_parking_area_saved_line(saved_area))
    if layout_warnings:
        demand.setdefault("warnings", []).extend(layout_warnings)
    demand["note"] = _object_parking_note(demand, own)
    demand["project_required"] = project_parking_requirement(inputs, tep, demand)
    return demand


def project_parking_requirement(inputs: dict[str, Any], tep: dict[str, Any],
                                demand: dict[str, Any]) -> dict[str, Any]:
    """Вся нормативная потребность проекта в машино-местах — знаменатель
    обеспеченности парковкой (решение владельца, #656).

    Гараж проекта строится на всех: жители, встроенная коммерция, отдельные
    объекты, соцобъекты. Делить его на потребность одной коммерции значило
    сравнить числитель и знаменатель разных потребителей (12,36× на
    умолчаниях). Части берутся у своих владельцев и не пересчитываются:

    - жители — постоянные и гостевые `underground_parking_requirement`
      (выгрузка ГлавАПУ первой, нет её — 2118-ПП). Места МФЦ из выгрузки сюда
      НЕ идут: это приобъектные места офисов, и их уже считает норма объектов;
    - приобъектные встроенной коммерции и отдельных объектов —
      `parking_demand.required_total`;
    - соцобъекты — `parking_demand.social_required_total`.

    Чего норма не посчитала, называется в `missing`, а не молчит нулём.
    """
    residents = underground_parking_requirement(inputs, tep) or {}
    permanent = int(residents.get("permanent") or 0)
    guest = int(residents.get("guest") or 0)
    attached = int(demand.get("required_total") or 0)
    social = int(demand.get("social_required_total") or 0)
    parts = [
        {"key": "residents", "label": "жители (постоянные и гостевые)",
         # Оговорка «приобъектные не учтены» верна для самой нормы жителей,
         # но здесь они учтены соседней частью — оставить её значило бы
         # опровергнуть итог в его же расшифровке.
         "spaces": permanent + guest,
         "basis": str(residents.get("basis") or "").replace(
             "; приобъектные места нежилья не учтены", "")},
        {"key": "attached", "label": "приобъектные коммерции и объектов",
         "spaces": attached, "basis": f"по нормативу {demand.get('norm_of') or ''}".strip()},
        {"key": "social", "label": "соцобъекты", "spaces": social,
         "basis": f"по нормативу {demand.get('norm_of') or ''}".strip()},
    ]
    return {
        "total": permanent + guest + attached + social,
        "residents_permanent": permanent,
        "residents_guest": guest,
        "attached": attached,
        "social": social,
        "parts": parts,
        "missing": list(demand.get("missing") or []) + list(demand.get("social_missing") or []),
    }


def parking_provision(built: float, requirement: dict[str, Any] | None) -> dict[str, Any]:
    """Обеспеченность парковкой: все места проекта / вся потребность.

    Одна функция на все поверхности — страница, отчёт, PDF, тизер, Платон и
    книга читают её ответ, а не делят сами. Подпись несёт обе величины: «во
    сколько раз» без «чего на что» не проверить глазами.
    """
    required = float((requirement or {}).get("total") or 0.0)
    built = float(built or 0.0)
    ratio = built / required if required > 0 else None
    if ratio is None:
        label = (f"{_parking_count_text(built)} мест / нормативная потребность не посчитана"
                 if built else "")
    else:
        label = (f"{_parking_count_text(built)} мест / {_parking_count_text(required)} по норме = "
                 + f"{ratio:.2f}".replace(".", ",") + "×")
    return {"built": built, "required": required, "ratio": ratio, "label": label}


def _parking_count_text(value: float) -> str:
    return f"{int(round(float(value or 0))):,}".replace(",", "\u00a0")

def _object_parking_note(demand: dict[str, Any], own: list[dict[str, Any]]) -> str:
    """Одной фразой: сколько мест положено, сколько строим и сколько продаём.

    Приобъектная парковка по приложению 6 к 945-ПП — это «временное хранение»,
    то есть места ПРИ объекте: под ним или на первых этажах (владелец,
    06.09.2026). Норма ставит число, человек его перебивает — и на экране
    обязано быть видно, чьё оно: «по нормативу» и «задано руками» на одном
    поле выглядят одинаково.
    """
    required = int(demand.get("required_total") or 0)
    live = [item for item in own if item.get("enabled")]
    if not live:
        if demand.get("missing"):
            return ("Норматив приобъектной парковки не посчитан: "
                    + demand["missing"][0].split(": ", 1)[-1] + ".")
        return "Нежилых объектов в проекте нет — приобъектная парковка не требуется."
    built = sum(item["units"] for item in live)
    sold = sum(item["saleable_units"] for item in live)
    parts = []
    for item in live:
        # Чьё число — часть числа. «Задано руками» у нетронутого поля — это
        # утверждение о человеке, сделанное из нашего же нуля: он ничего не
        # вписывал, просто мест не потребовалось.
        if item.get("by_norm"):
            whose = ", по нормативу"
        elif item["units"]:
            whose = ", задано руками"
        elif item.get("required_spaces"):
            whose = f", мест нет — а по нормативу положено {item['required_spaces']}"
        else:
            whose = ", норматив мест не требует"
        line = (f"{item['label']} — {item['units']} мест "
                f"({item['under_spaces']} в подземном, {item['over_spaces']} на первых этажах"
                + whose + ")")
        if not item["sellable"]:
            # «Ты видел ТЦ, где покупатели купили бы места?» — обеспеченность
            # посетителей. Не сказать этого рядом с числом значит показать
            # построенные места там, где читатель ждёт продаваемые.
            line += ", не продаются"
        elif item["guest_spaces"]:
            line += f", из них {item['guest_spaces']} гостевых"
        parts.append(line)
    # Норматив считается и встроенной коммерции МКД, а своего гаража у неё нет.
    # Это приобъектная стоянка у дома — плоскостная парковка или сторона улицы
    # (945-ПП п. 6.1.2.3), и в подземный паркинг МКД она не идёт: гараж дома —
    # постоянные и гостевые (`underground_parking_requirement`, выгрузка
    # ГлавАПУ строками 42.1–42.2). Прежде подпись клала её «в подземный паркинг
    # дома» — о гараже, который её не содержит. Без оговорки «положено 222,
    # строим 173» читается как недострой на 49 мест.
    own_keys = {item["tep_key"] for item in own}
    in_house = sum(int(row.get("required_spaces") or 0)
                   for row in (demand.get("rows") or [])
                   if row.get("tep_key") not in own_keys)
    head = (f"По нормативу {demand.get('norm_of') or ''} положено {required} мест."
            if required else "Норматив не посчитан — числа заданы руками.")
    if in_house:
        head += (f" Из них {in_house} — встроенной коммерции МКД: приобъектная "
                 "стоянка у дома (плоскостная парковка или улица, 945-ПП п. 6.1.2.3), "
                 "в подземный паркинг МКД не входит.")
    text = head + f" Строим {built}, продаётся {sold}: " + "; ".join(parts) + "."
    # Оговорка живёт у числа, а не в соседнем месте. Без выгрузки ГлавАПУ норма
    # берёт верхний край (К1 = К2 = 1) — это МАКСИМУМ мест, и подписанный
    # нормой он читается как расчёт города. Число при этом попадает в поля
    # гаража, то есть в метры, в CAPEX и в выручку: молчать о его
    # происхождении дороже, чем показать длинную фразу.
    caveats = [line for line in ((demand.get("assumptions") or []) + (demand.get("warnings") or [])) if line]
    if caveats:
        spoken = "; ".join(caveats)
        text += " " + spoken[:1].upper() + spoken[1:] + "."
    return text


# Чей норматив посчитал приобъектные места — в родительном падеже, чтобы
# встать после «по нормативу». Подпись берётся отсюда же, откуда расчёт
# берёт юрисдикцию: зашитое «приложение 6 к 945-ПП» на участке в области
# называло московский документ под областным числом (Мытищи, 04.10.2026).
PARKING_NORM_OTHER_REGION = "other_region"
PARKING_NORM_OF: dict[str, str] = {
    parking_norms.MOSCOW: "приложения 6 к 945-ПП",
    # Другой регион: норм парковки его у нас нет (решение владельца 19.10.2026).
    PARKING_NORM_OTHER_REGION: "этого региона — его норм у нас нет",
    parking_norms.MOSCOW_OBLAST: ("Московской области (приложение № 10 к 713/30 в ред. "
                                  "1480/45; строки, кроме ФОК, не сверены; "
                                  "СП 42.13330.2016 отменён с 12.07.2026)"),
}


def _parking_demand_other_region() -> dict[str, Any]:
    """Приобъектных мест другого региона не считаем: норм его у нас нет.

    Московские 945-ПП и областные 713/30 к такому участку не относятся, и
    число, посчитанное ими, выглядело бы нормой региона. Пустой ответ той же
    формы, с причиной в `missing`: читатели говорят «не посчитано», а не «ноль».
    """
    reason = ("норм парковки этого региона у нас нет — число машино-мест "
              "стоит нашим умолчанием, поправьте его")
    return {
        "jurisdiction": PARKING_NORM_OTHER_REGION,
        "norm_of": PARKING_NORM_OF[PARKING_NORM_OTHER_REGION],
        "k1": 0.0, "k2": 0.0, "k_input": {"k1": 0.0, "k2": 0.0},
        "k_assumed": False, "k_origin": {"k1": "", "k2": ""},
        "k_basis": {"district": "", "inside_ttk": None, "district_source": "",
                    "ttk_source": "", "rail_distance_m": 0.0, "conflicts": []},
        "design_mode": "",
        "rows": [], "required_total": 0,
        "social_rows": [], "social_required_total": 0, "social_missing": [reason],
        "missing": [reason], "assumptions": [],
    }


def parking_demand(inputs: dict[str, Any], tep: dict[str, Any]) -> dict[str, Any]:
    """Сколько ПРИОБЪЕКТНЫХ мест требует каждый нежилой объект.

    Это справка, а не стройка. Приобъектная парковка — стоянка вдоль проезда:
    её нельзя поставить на кадастр, значит нельзя и продать (решение владельца,
    06.09.2026: «это кусок асфальта»). Она входит в благоустройство своей
    статьёй и ни метров ГНС, ни своего СМР, ни выручки не порождает. Норма
    отвечает на «сколько положено», и на этом её работа кончается.

    Собственный паркинг объекта — другое: гараж под ОСЗ ставится на кадастр и
    продаётся машино-местами. Его число задаёт человек (`OBJECT_PARKING_FIELDS`),
    и из этой нормы оно НЕ выводится.

    База московского норматива — НЕЖИЛАЯ НАЗЕМНАЯ ПЛОЩАДЬ (сноска 2 приложения
    1 в редакции 2579-ПП). В нашем ТЭП это `gns` продукта: подземная часть у
    него своей строкой. Подмена базы здесь не выглядит ошибкой — между ННП и
    суммарной поэтажной площадью десятая часть метров.

    Постоянные и гостевые места жителей сюда не входят: у них своё приложение 5
    и свой расчёт, и трогать его этот модуль не должен.
    """
    region = project_region(inputs)
    if region == "other":
        return _parking_demand_other_region()
    jurisdiction = parking_norms.MOSCOW_OBLAST if region == "mo" else parking_norms.MOSCOW
    k1 = n(inputs, "parking_k1")
    k2 = n(inputs, "parking_k2")
    design_mode = str((inputs or {}).get("parking_design_mode")
                      or parking_norms.DESIGN_MODE_DEFAULT)
    # Вторая ступень лестницы коэффициентов — приложения 3 и 6 по своему
    # участку. Район и ТТК — у одного владельца с льготой за МПТ
    # (`site_position`): руки сильнее документа, противоречие с разбором
    # кадастра показывается, а не молчит. Прежде здесь читалась
    # `_glavapu_import.territory`, которую страница не сохраняет, и ступень
    # «К2 по району из разбора кадастра» в живом проекте не срабатывала.
    position = site_position.site_position(inputs)
    district = position["district"]
    inside_ttk: Any = position["inside_ttc"]
    rail_distance = n(inputs, "parking_rail_distance_m")
    ratios, _ratio_notes = tep_ratios_applied(inputs)
    rows: list[dict[str, Any]] = []
    required_named = 0
    # Коэффициент, ПРИНЯТЫЙ расчётом, а не пришедший во вводных: без выгрузки
    # ГлавАПУ норма берёт верхний край (решение владельца, 06.09.2026), и
    # отдавать наружу ноль значило бы показать одно, а посчитать другим.
    k1_applied = k2_applied = 0.0
    k_assumed = False
    k_origin = {"k1": "", "k2": ""}
    social_rows: list[dict[str, Any]] = []
    social_named = 0
    for tep_key, msk_function, mo_function, built_in in (
            _PARKING_DEMAND_PRODUCTS + _PARKING_SOCIAL_PRODUCTS):
        social = tep_key in _PARKING_SOCIAL_KEYS
        # Единственный продукт, у которого функция норматива зависит от вводных:
        # «ФОК / медцентр» — объект с двумя назначениями, и у каждого его
        # экземпляра назначение своё.
        _purposeful = _BY_KEY.get(tep_key)
        if _purposeful is not None and _purposeful.purpose_key:
            msk_function, mo_function = sports_parking_functions(
                inputs, _purposeful.purpose_key)
        row = (tep or {}).get(tep_key) or {}
        # База у юрисдикций РАЗНАЯ, и это часть норматива, а не подробность.
        # Москва считает от нежилой наземной площади (сноска 2 приложения 1 в
        # редакции 2579-ПП), область — от общей (приложение 10 и п. 5.12).
        #
        # ННП — площадь В ГАБАРИТАХ ВНУТРЕННИХ СТЕН (владелец, 08.09.2026), то
        # есть наша ОБЩАЯ площадь помещений, а не ГНС: ГНС обводит здание по
        # наружным стенам. Прежде встроенная коммерция считалась от общей, а
        # отдельно стоящие — от ГНС целиком: одна единица приложения 1 стояла
        # над двумя разными базами, и на офиснике 20 000 м² это давало 318 мест
        # против 298. Толщина стен — это доля продукта (`total_of_gns`), она
        # версионируемая и правится человеком, поэтому берётся из ПРИМЕНЁННЫХ
        # долей, а не зашивается числом.
        share = float((ratios.get(tep_key) or {}).get("total_of_gns") or 0.0)
        area = n(row, "total_area") or (n(row, "gns") * share if share else 0.0)
        if area <= 0:
            continue
        if social and jurisdiction != parking_norms.MOSCOW:
            # У области строк для ДОО, школы и поликлиники в модели нет, а
            # правило 1/50 ДОО и поликлинику исключает прямым текстом. Нет
            # нормы — нет и числа: ноль здесь выдал бы пробел за ответ.
            got = {"jurisdiction": jurisdiction, "function": tep_key,
                   "required_spaces": None,
                   "reason": "норматив области для соцобъекта в модели не заведён"}
        elif jurisdiction == parking_norms.MOSCOW:
            got = parking_norms.moscow_required(
                msk_function, area, k1=k1, k2=k2, built_in=built_in,
                district=district, inside_ttk=inside_ttk,
                rail_distance_m=rail_distance)
        else:
            # 774-ПП называет встроенно-пристроенные помещения первых этажей
            # прямо, и для них правило 1/50 — не фолбэк, а сама норма.
            got = parking_norms.mo_required(
                "built_in" if built_in else mo_function, area, design_mode=design_mode)
        got["tep_key"] = tep_key
        got["label"] = row.get("label") or tep_key
        if social:
            social_named += int(got.get("required_spaces") or 0)
            social_rows.append(got)
            continue
        if got.get("k1") is not None:
            k1_applied = float(got.get("k1") or 0.0)
            k2_applied = float(got.get("k2") or 0.0)
            k_assumed = k_assumed or bool(got.get("k1_assumed") or got.get("k2_assumed"))
            k_origin = {"k1": str(got.get("k1_origin") or ""),
                        "k2": str(got.get("k2_origin") or "")}
        required_named += int(got.get("required_spaces") or 0)
        rows.append(got)
    assumptions: list[str] = []
    for row in rows:
        assumptions.extend(row.get("assumptions") or [])
    missing = [f"{row['label']}: {row.get('reason')}" for row in rows if row.get("reason")]
    return {
        "jurisdiction": jurisdiction,
        "norm_of": PARKING_NORM_OF[jurisdiction],
        "k1": k1_applied or k1, "k2": k2_applied or k2,
        "k_input": {"k1": k1, "k2": k2},
        "k_assumed": k_assumed,
        # Чьи это коэффициенты: города, приложения или нашего незнания. Между
        # таблицей и верхним краем разница впятеро, и «assumed» их не разводит.
        "k_origin": k_origin,
        "k_basis": {"district": district, "inside_ttk": inside_ttk,
                    "district_source": position["district_source"],
                    "ttk_source": position["ttk_source"],
                    "rail_distance_m": rail_distance,
                    "conflicts": position["conflicts"]},
        "design_mode": design_mode if jurisdiction == parking_norms.MOSCOW_OBLAST else "",
        "rows": rows,
        "required_total": required_named,
        # Соцобъекты — своим списком и своим итогом: `required_total` читают
        # подпись гаражей объектов и сверка с ГлавАПУ, и там им не место.
        # Нужны они одному читателю — нормативной потребности проекта
        # (`project_parking_requirement`).
        "social_rows": social_rows,
        "social_required_total": social_named,
        "social_missing": [f"{row['label']}: {row.get('reason')}"
                           for row in social_rows if row.get("reason")],
        "missing": missing,
        "assumptions": list(dict.fromkeys(assumptions)),
    }
