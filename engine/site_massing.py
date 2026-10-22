"""Баланс территории участка: пятно застройки, средняя этажность и подземные уровни.

Вопрос владельца (22.10.2026): «по калькулятору ГлавАПУ мы знаем пятно
застройки — остальное уйдёт под благоустройство и дорогу. Значит, мы примерно
понимаем, сколько этажей будет у здания и сколько подземных этажей надо на
такое количество машино-мест?» Решение — «проверка + ставка по уровням».

Пятно = участок − двор − проезды − наземные стоянки − отступы. Средняя
этажность — наземная ГНС ÷ пятно, по определению норматива
(`mo_land_capacity.average_storeys`, второй формулы нет). Подземная часть
ложится в контур «участок минус отступы» с коэффициентом использования, и
число уровней — округление вверх. Ставка подземной части растёт с глубиной:
надбавка за −2 и за −3 и ниже; ставка, заданная руками, остаётся ручной.

Допущения согласованы с владельцем 22.10.2026 (AskUserQuestion):
проезды 15 % участка, отступ 3 м по периметру, коэффициент контура 0,85,
надбавки +10 % / +20 %, двор — площадь благоустройства, но не меньше нормы
региона, место открытой стоянки — 22,5 м² в МО и 25 м² в остальных.

Это оценка по балансу территории, не проект: формы участка мы не знаем, и
отступ считается полосой по периметру квадрата той же площади.

Не самостоятельный модуль: `main_legacy.py` выполняет файл в пространстве
имён движка (`_engine_part("site_massing")`).
"""
# ruff: noqa

import math as _math

import mo_land_capacity as _mo_land_capacity

# Нижняя граница двора по региону. Москва — 2152-ПП: 5,0 м² озеленённых
# территорий ЖК на жителя (её же требует калькулятор ГлавАПУ, строка 57).
# Подмосковье — РНГП МО, та же норма, что у калькулятора области
# (`MO_NORMS_DEFAULT["green_quarter_sqm_per_person"]`). Прочие регионы —
# СП 42.13330.2016, п. 7.4: озеленённая территория квартала многоквартирной
# застройки — не менее 25 % его площади.
MSK_GREEN_ZHK_SQM_PER_PERSON = 5.0
OTHER_REGION_GREEN_SHARE = 0.25

# Место на открытой стоянке, м² земли: МО — 713/30, п. 5.11 (та же величина,
# что `MO_NORMS_DEFAULT["parking_surface_sqm_per_space"]`); Москва и прочие —
# экспертное умолчание (место и проезд к нему), владелец 22.10.2026.
SURFACE_PARKING_SQM_DEFAULT = 25.0

def _massing_number(x: dict[str, Any], key: str) -> float:
    """Число поля; пустое и ноль — «по умолчанию», а не «нет величины»."""
    try:
        value = float(x.get(key) or 0.0)
    except (TypeError, ValueError):
        return 0.0
    return value if value > 0 else 0.0


def _massing_default(key: str) -> float:
    return _massing_number(DEFAULT_INPUTS, key)


def _massing_value(x: dict[str, Any], key: str) -> tuple[float, bool]:
    """→ (значение, задано ли оно в проекте). Пусто — умолчание движка."""
    raw = x.get(key)
    if raw in (None, ""):
        return _massing_default(key), False
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return _massing_default(key), False
    return max(0.0, value), True


def surface_parking_sqm_per_space(x: dict[str, Any]) -> tuple[float, str]:
    given = _massing_number(x, "surface_parking_sqm_per_space")
    if given > 0:
        return given, "задано в проекте"
    if project_region(x) == "mo":
        return (float(MO_NORMS_DEFAULT["parking_surface_sqm_per_space"]),
                "норматив Московской области (713/30, п. 5.11)")
    return SURFACE_PARKING_SQM_DEFAULT, "экспертное умолчание"


def _yard_floor(x: dict[str, Any], tep: dict[str, Any], site_sqm: float) -> tuple[float, str]:
    """Нижняя граница двора по норме региона → (м², основание)."""
    region = project_region(x)
    population, _ = project_population(tep, region)
    if population <= 0:
        return 0.0, ""
    if region == "msk":
        return (MSK_GREEN_ZHK_SQM_PER_PERSON * population,
                f"норма Москвы (2152-ПП): {MSK_GREEN_ZHK_SQM_PER_PERSON:g} м² на жителя "
                f"× {population} чел.".replace(".", ","))
    if region == "mo":
        per = float(MO_NORMS_DEFAULT["green_quarter_sqm_per_person"])
        return (per * population,
                f"норма Московской области: {per:g} м² на жителя × {population} чел."
                .replace(".", ","))
    return (OTHER_REGION_GREEN_SHARE * site_sqm,
            "СП 42.13330.2016, п. 7.4: озеленение жилого квартала — не меньше 25% участка")


def setback_area(site_sqm: float, setback_m: float) -> float:
    """Полоса отступа по периметру квадрата той же площади (форма участка неизвестна)."""
    if site_sqm <= 0 or setback_m <= 0:
        return 0.0
    side = _math.sqrt(site_sqm)
    inner = max(0.0, side - 2 * setback_m)
    return site_sqm - inner * inner


def underground_area_of(x: dict[str, Any], tep: dict[str, Any]) -> float:
    """Подземная площадь проекта — та же, что строительный объём берёт под землёй:
    подземные продукты проекта (паркинг, подземные кладовые) и свои гаражи объектов."""
    return (sum(n(tep.get(key) or {}, "gns") for key in underground_products(x))
            + sum(n(row, "under_gns") for row in tep.values() if isinstance(row, dict)))


def underground_rate_by_hand(x: dict[str, Any]) -> bool:
    """Ставка подземной части задана человеком, а не взята из базы класса.

    Ручная — вписанная в поле проекта (`_field_origin`, `_class_manual`) или отличная от базы
    класса (`project_class_deviations`: правка руками или личная перекрышка).
    Надбавки за глубину к ней не прибавляются: число человека остаётся его
    числом.
    """
    origin = ((x.get("_field_origin") or {}).get("inputs.main_under_th_per_sqm") or {})
    if isinstance(origin, dict) and origin.get("source") == "manual":
        return True
    # Страница помечает правку ставки класса списком `_class_manual`: число,
    # вписанное руками, остаётся ручным, даже если совпало с базой.
    if "main_under_th_per_sqm" in (x.get("_class_manual") or []):
        return True
    return any(row.get("field") == "main_under_th_per_sqm"
               for row in project_class_deviations(x).get("rows") or [])


def _level_areas(total: float, capacity: float, levels: int) -> list[float]:
    """Площадь по уровням: верхние заполняются до вместимости, остаток — на нижнем.

    Не помещается (уровней задано руками меньше, чем нужно) или вместимости
    нет — площадь делится поровну. Та же раскладка — формулами книги
    (`site_massing_book.formulas`).
    """
    if levels <= 0 or total <= 0:
        return []
    if capacity <= 0 or capacity * levels < total:
        return [total / levels] * levels
    areas: list[float] = []
    left = total
    for _ in range(levels):
        part = min(capacity, left)
        areas.append(part)
        left -= part
    return areas


def _fmt_ru(value: float, digits: int = 0) -> str:
    text = f"{value:,.{digits}f}".replace(",", " ").replace(".", ",")
    return text


def site_massing(x: dict[str, Any], tep: dict[str, Any]) -> dict[str, Any]:
    """Пятно застройки, средняя этажность, подземный контур, уровни и надбавка.

    Каждая величина несёт происхождение (`*_origin`: `estimate` — посчитано
    здесь, `manual` — задано в проекте) и основание. Ручное пятно и ручные
    уровни сильнее оценки; при пустом поле оценка пересчитывается от
    текущего ТЭП. Очередь проекта читает уровни и надбавку ПРОЕКТА
    (`_site_massing_project`): участок у очередей один.
    """
    project = x.get("_site_massing_project")
    if isinstance(project, dict) and project:
        return dict(project)
    tep = tep or {}
    site_sqm = _massing_number(x, "site_area_ha") * 10000.0
    above_gns = project_above_gns(tep)
    under_sqm = underground_area_of(x, tep)
    warnings: list[str] = []
    notes: list[str] = []

    # Двор — та же площадь, что у благоустройства (один источник), но не меньше
    # нормы региона.
    yard_sqm, yard_basis = landscaping_area(x, tep)
    floor_sqm, floor_basis = _yard_floor(x, tep, site_sqm)
    if floor_sqm > yard_sqm + 0.5:
        yard_basis = (f"Площадь благоустройства ({_fmt_ru(yard_sqm)} м²) меньше нормы "
                      f"региона, поэтому взята норма: {floor_basis}.")
        yard_sqm = floor_sqm
    elif yard_sqm <= 0 and without_housing(x):
        yard_basis = "В проекте нет жителей, поэтому двор по их числу не считается."

    drive_pct, _ = _massing_value(x, "site_driveways_pct")
    setback_m, _ = _massing_value(x, "site_setback_m")
    spaces = _massing_number(x, "surface_parking_spaces")
    per_space, per_space_basis = surface_parking_sqm_per_space(x)
    use_factor = (_massing_number(x, "underground_contour_use_factor")
                  or _massing_default("underground_contour_use_factor"))
    markup2, _ = _massing_value(x, "underground_level2_markup_pct")
    markup3, _ = _massing_value(x, "underground_level3_markup_pct")

    drive_sqm = site_sqm * drive_pct / 100.0
    parking_sqm = spaces * per_space
    setbacks_sqm = setback_area(site_sqm, setback_m)
    estimate = site_sqm - yard_sqm - drive_sqm - parking_sqm - setbacks_sqm

    manual_footprint = _massing_number(x, "building_footprint_sqm")
    if manual_footprint > 0:
        footprint, footprint_origin = manual_footprint, "manual"
    else:
        footprint, footprint_origin = max(0.0, estimate), "estimate"

    if site_sqm <= 0:
        warnings.append("Площадь участка не задана, поэтому пятно застройки, этажность "
                        "и число подземных уровней не посчитаны. Укажите площадь участка "
                        "во вкладке «ТЭП».")
    elif footprint_origin == "estimate" and estimate <= 0:
        warnings.append(
            f"На участке не остаётся места под здание: двор, проезды, стоянки и отступы "
            f"занимают {_fmt_ru(site_sqm - estimate)} м² из {_fmt_ru(site_sqm)} м². "
            "Проверьте допущения или задайте пятно застройки вручную.")

    storeys = _mo_land_capacity.average_storeys(above_gns, footprint) if footprint > 0 else 0.0
    max_storeys = _massing_number(x, "max_storeys_allowed")
    if max_storeys > 0 and storeys > max_storeys + 1e-9:
        warnings.append(
            f"Средняя этажность по расчёту — {_fmt_ru(storeys, 1)}, а на участке разрешено "
            f"не выше {_fmt_ru(max_storeys)} этажей. Здание с наземной площадью "
            f"{_fmt_ru(above_gns)} м² на этом участке не помещается: уменьшите площадь "
            "здания или проверьте допущения по пятну застройки.")
    elif max_storeys <= 0 and storeys > 0:
        notes.append("Предельная этажность участка не задана, поэтому сравнить с ней "
                     "расчётную этажность нельзя.")

    contour = max(0.0, site_sqm - setbacks_sqm)
    capacity = contour * use_factor
    manual_levels = int(_massing_number(x, "underground_levels"))
    if under_sqm <= 0:
        levels, levels_origin = 0, "estimate"
    elif manual_levels > 0:
        levels, levels_origin = manual_levels, "manual"
    elif capacity > 0:
        levels, levels_origin = int(_math.ceil(under_sqm / capacity - 1e-9)), "estimate"
    else:
        levels, levels_origin = 0, "estimate"
    if levels_origin == "manual" and capacity > 0 and under_sqm > capacity * levels + 0.5:
        warnings.append(
            f"Подземная часть {_fmt_ru(under_sqm)} м² не помещается на {levels} "
            f"уровн{'е' if levels == 1 else 'ях'}: в контуре участка на одном уровне "
            f"помещается около {_fmt_ru(capacity)} м².")
    areas = _level_areas(under_sqm, capacity, levels)

    by_hand = underground_rate_by_hand(x)
    markups = [0.0 if i == 0 else (markup2 if i == 1 else markup3) for i in range(len(areas))]
    if by_hand or not areas:
        depth_factor = 1.0
    else:
        depth_factor = sum(a * (1 + m / 100.0) for a, m in zip(areas, markups)) / sum(areas)
    rate = n(x, "main_under_th_per_sqm")
    level_rows = [{"level": -(i + 1), "area_sqm": a, "markup_pct": 0.0 if by_hand else m,
                   "rate_th": rate * (1.0 if by_hand else 1 + m / 100.0)}
                  for i, (a, m) in enumerate(zip(areas, markups))]
    if by_hand and len(areas) > 1:
        depth_basis = ("Ставка подземной части задана вручную, поэтому надбавки за глубину "
                       "не применяются.")
    elif len(areas) > 1:
        depth_basis = (f"Ставка второго уровня выше на {_fmt_ru(markup2, 1).replace(',0', '')}%, "
                       f"третьего и ниже — на {_fmt_ru(markup3, 1).replace(',0', '')}%. "
                       "Это экспертная оценка.")
    else:
        depth_basis = "Подземный уровень один, надбавки за глубину нет." if areas else ""

    return {
        "site_sqm": site_sqm,
        "above_gns_sqm": above_gns,
        "yard_sqm": yard_sqm,
        "yard_basis": yard_basis,
        "driveways_sqm": drive_sqm,
        "driveways_pct": drive_pct,
        "surface_parking_spaces": spaces,
        "surface_parking_sqm": parking_sqm,
        "surface_parking_sqm_per_space": per_space,
        "surface_parking_basis": per_space_basis,
        "setback_m": setback_m,
        "setbacks_sqm": setbacks_sqm,
        "footprint_estimate_sqm": max(0.0, estimate),
        "footprint_sqm": footprint,
        "footprint_origin": footprint_origin,
        "footprint_share": footprint / site_sqm if site_sqm > 0 else 0.0,
        "average_storeys": storeys,
        "max_storeys_allowed": max_storeys,
        "underground_contour_sqm": contour,
        "underground_use_factor": use_factor,
        "underground_sqm": under_sqm,
        "underground_levels": levels,
        "underground_levels_origin": levels_origin,
        "underground_level_rows": level_rows,
        "underground_rate_by_hand": by_hand,
        "underground_level2_markup_pct": markup2,
        "underground_level3_markup_pct": markup3,
        "underground_depth_factor": depth_factor,
        "underground_depth_basis": depth_basis,
        "warnings": warnings,
        "notes": notes,
        "summary": site_massing_line({
            "footprint_sqm": footprint, "site_sqm": site_sqm,
            "average_storeys": storeys, "underground_sqm": under_sqm,
            "underground_levels": levels}),
    }


def site_massing_line(m: dict[str, Any]) -> str:
    """Одна фраза для отчёта, PDF и бота — собрана здесь, читается verbatim."""
    footprint = float(m.get("footprint_sqm") or 0.0)
    site = float(m.get("site_sqm") or 0.0)
    if footprint <= 0 or site <= 0:
        return ""
    levels = int(m.get("underground_levels") or 0)
    under = float(m.get("underground_sqm") or 0.0)
    words = {1: "одном уровне", 2: "двух уровнях", 3: "трёх уровнях", 4: "четырёх уровнях"}
    tail = (f", подземная часть {_fmt_ru(under)} м² на "
            f"{words.get(levels, f'{levels} уровнях')}" if levels > 0 and under > 0 else "")
    return (f"Здание: пятно застройки около {_fmt_ru(footprint)} м² "
            f"({_fmt_ru(footprint / site * 100)}% участка), средняя этажность около "
            f"{_fmt_ru(float(m.get('average_storeys') or 0.0), 1)}{tail}. "
            "Это оценка по балансу территории, а не проект.")
