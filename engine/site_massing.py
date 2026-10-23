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
import glavapu_scenario as _glavapu_scenario
import site_massing_book as _massing_book

# Выше этого здание расчёт не ставит, когда предел участка не задан
# (владелец 22.10.2026). Один источник с книгой и объёмной схемой.
STOREYS_LIMIT_DEFAULT = _massing_book.STOREYS_LIMIT_DEFAULT
COVERAGE_PCT_DEFAULT = _massing_book.COVERAGE_PCT_DEFAULT
RESIDENTIAL_STOREYS_DEFAULT = _massing_book.RESIDENTIAL_STOREYS_DEFAULT

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

# Отдельные здания на своих участках (владелец 23.10.2026): школа, детский
# сад и прочие нежилые здания жилого проекта не входят в жилой баланс —
# двор, процент застройки и этажность жилья считаются на остатке участка.
# Без данных ГлавАПУ участок на место — как у типовых зданий калькулятора
# (выгрузка Нагатино 06.10.2026: ДОО на 250 мест — 0,8 га, школа на 2 500
# мест — 3,5 га), этажность — экспертное умолчание.
SOCIAL_SITE_OBJECTS: dict[str, dict[str, Any]] = {
    "kindergarten": {"label": "Детский сад", "sqm_per_place": 32.0, "storeys": 3,
                     "typical": "типовой детский сад калькулятора ГлавАПУ: 250 мест на 0,8 га"},
    "school": {"label": "Школа", "sqm_per_place": 14.0, "storeys": 4,
               "typical": "типовая школа калькулятора ГлавАПУ: 2 500 мест на 3,5 га"},
}
# Строки ГлавАПУ с участками соцобъектов: ключ ТЭП → (места, участок) в выгрузке.
GLAVAPU_SOCIAL_ROWS: dict[str, tuple[str, str, str]] = {
    "kindergarten": ("actual_kindergarten_places", "actual_kindergarten_land_ha", "строка 21"),
    "school": ("actual_school_places", "actual_school_land_ha", "строка 25"),
    "clinic": ("actual_clinic_capacity", "actual_clinic_land_ha", "строка 29"),
}
# Прочие отдельные нежилые здания (офисы, ТЦ, наземный паркинг, ФОК,
# поликлиника без строки ГлавАПУ): этажность и участок — два пятна.
OTHER_OBJECT_STOREYS_DEFAULT = 12
OTHER_OBJECT_PLOT_PER_FOOTPRINT = 2.0
# Строки ТЭП жилых домов (квартиры, кладовые, встроенная коммерция) и
# подземные — остальное с наземной ГНС стоит отдельными зданиями.
RESIDENTIAL_TEP_KEYS = ("apartments", "storage", "ground_commercial")
# Соцобъекты, чьи участки передаются городу: под ними подземного контура нет.
SOCIAL_PLOT_KEYS = ("kindergarten", "school", "clinic")
NOT_ABOVE_TEP_KEYS = ("underground_parking",)

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


def _norm_ru(value: float) -> str:
    """Норматив на жителя по-русски: 5, 6,5."""
    return f"{value:g}".replace(".", ",")


def _yard_floor(x: dict[str, Any], tep: dict[str, Any], site_sqm: float) -> tuple[float, str]:
    """Нижняя граница двора по норме региона → (м², основание)."""
    region = project_region(x)
    population, _ = project_population(tep, region)
    if population <= 0:
        return 0.0, ""
    if region == "msk":
        ours = MSK_GREEN_ZHK_SQM_PER_PERSON * population
        basis = (f"норма Москвы (2152-ПП): {_norm_ru(MSK_GREEN_ZHK_SQM_PER_PERSON)} м² на жителя "
                 f"× {population} жителей")
        city, city_basis = _glavapu_green_zhk(x, tep)
        if city > ours + 0.5:
            return city, (f"{city_basis} — больше нашей нормы ({basis}, {_fmt_ru(ours)} м²): "
                          "калькулятор считает жителей как квартиры × 2,1, поэтому взята его")
        if city_basis and city <= 0:
            return ours, f"{basis}. {city_basis}"
        return ours, basis
    if region == "mo":
        per = float(MO_NORMS_DEFAULT["green_quarter_sqm_per_person"])
        return (per * population,
                f"норма Московской области: {_norm_ru(per)} м² на жителя × {population} жителей")
    # Прочие регионы — большее из федерального СП 42 (25 % участка) и нормы
    # Москвы на жителя: своих норм региона у нас нет (владелец 22.10.2026).
    share = OTHER_REGION_GREEN_SHARE * site_sqm
    per_person = MSK_GREEN_ZHK_SQM_PER_PERSON * population
    if per_person > share + 0.5:
        return (per_person,
                f"допущение: норма Москвы {_norm_ru(MSK_GREEN_ZHK_SQM_PER_PERSON)} м² на жителя × "
                f"{population} жителей — норм этого региона у нас нет; это больше, чем требует "
                "СП 42.13330.2016, п. 7.4 (25% участка)")
    return (share,
            "СП 42.13330.2016, п. 7.4: озеленение жилого квартала — не меньше 25% участка "
            f"(это не меньше нормы Москвы {_norm_ru(MSK_GREEN_ZHK_SQM_PER_PERSON)} м² на жителя × "
            f"{population} жителей, которую берём допущением: норм этого региона у нас нет)")


def _glavapu_territory_value(cell: Any) -> float:
    """Ячейка территории калькулятора — число га или пара [га, строка]."""
    value = cell[0] if isinstance(cell, (list, tuple)) and cell else cell
    try:
        return max(0.0, float(value or 0.0))
    except (TypeError, ValueError):
        return 0.0


def _glavapu_green_zhk(x: dict[str, Any], tep: dict[str, Any]) -> tuple[float, str]:
    """Строка 57 калькулятора ГлавАПУ «Озеленённые территории ЖК» → (м², основание).

    Решение владельца 22.10.2026: двор по норме — большее из нашей нормы и
    строки 57. Источники: сверка сценария (`_glavapu_scenario`, кнопка
    «Сверить сценарий») и загруженная выгрузка (`_glavapu_import`). Строка 57 —
    5 м² × квартиры × 2,1, поэтому берётся, только если калькулятор считал для
    того же числа квартир, что сейчас в ТЭП; иначе снимок устарел — (0, причина).
    Ни сверки, ни выгрузки — (0, "").
    """
    units_tep = int(round(float((tep.get("apartments") or {}).get("units") or 0)))
    reasons: list[str] = []
    check = x.get("_glavapu_scenario") or {}
    territory = check.get("territory") or {}
    green = _glavapu_territory_value(territory.get("green_zhk")) * 10000.0
    if green > 0:
        flats = int(float(check.get("flats_count") or 0))
        if flats > 0 and flats == units_tep:
            plants = _glavapu_territory_value(territory.get("57_1")) * 10000.0
            grounds = _glavapu_territory_value(territory.get("57_2")) * 10000.0
            parts = (f" (зелёные насаждения {_fmt_ru(plants)} м², площадки и дорожки "
                     f"{_fmt_ru(grounds)} м²)" if plants > 0 or grounds > 0 else "")
            return green, (f"ГлавАПУ, сверка сценария, строка 57: {_fmt_ru(green)} м² "
                           f"озеленённых территорий ЖК{parts}")
        reasons.append(f"Строка 57 сверки с калькулятором ГлавАПУ ({_fmt_ru(green)} м²) посчитана "
                       f"для {flats or 'неизвестного числа'} квартир, а в ТЭП сейчас {units_tep} — "
                       "для двора она не берётся, повторите сверку")
    imported = x.get("_glavapu_import") or {}
    normalized = imported.get("normalized") or {}
    green_ha = _glavapu_territory_value(normalized.get("green_zhk_ha"))
    if green_ha > 0:
        units_export = int(float(normalized.get("apartment_units") or 0))
        if units_export > 0 and units_export == units_tep:
            when = (imported.get("source") or {}).get("export_date")
            where = (f"ГлавАПУ, {'выгрузка от ' + when if when else 'выгрузка (дата в файле не указана)'}, "
                     "лист «ТЭП», строка 57")
            return green_ha * 10000.0, f"{where}: {_fmt_ru(green_ha * 10000)} м² озеленённых территорий ЖК"
        reasons.append(f"Строка 57 выгрузки ГлавАПУ ({_fmt_ru(green_ha * 10000)} м²) посчитана "
                       f"для {units_export or 'неизвестного числа'} квартир, а в ТЭП сейчас "
                       f"{units_tep} — для двора она не берётся")
    return 0.0, ". ".join(reasons)


def _object_rows(x: dict[str, Any], tep: dict[str, Any]) -> list[tuple[str, dict[str, Any], float]]:
    """Строки ТЭП отдельных зданий жилого проекта → [(ключ, строка, наземная ГНС)].

    У проекта без жилья отдельных зданий нет: всё наземное и есть здание.
    """
    if without_housing(x):
        return []
    out = []
    for key, row in (tep or {}).items():
        if (not isinstance(row, dict) or key in RESIDENTIAL_TEP_KEYS
                or key in NOT_ABOVE_TEP_KEYS):
            continue
        gns = n(row, "gns")
        if gns > 0:
            out.append((key, row, gns))
    return out


def residential_above_gns(x: dict[str, Any], tep: dict[str, Any]) -> float:
    """Наземная ГНС жилых домов: наземная ГНС проекта без отдельных зданий."""
    return max(0.0, project_above_gns(tep or {}) - sum(g for _, _, g in _object_rows(x, tep)))


def _glavapu_ha(cell: Any) -> float:
    """Число га из строки ГлавАПУ: число, пара [га, строка] или «4,401 (24,7%)»."""
    value = cell[0] if isinstance(cell, (list, tuple)) and cell else cell
    if isinstance(value, str):
        head = value.strip().split(" ")[0].replace("\u00a0", "").replace(",", ".")
        try:
            return max(0.0, float(head))
        except ValueError:
            return 0.0
    return _glavapu_territory_value(value)


def _glavapu_when(x: dict[str, Any]) -> str:
    when = ((x.get("_glavapu_import") or {}).get("source") or {}).get("export_date")
    return f"выгрузка от {when}" if when else "выгрузка (дата в файле не указана)"


def _glavapu_social_plot(x: dict[str, Any], key: str, places: int) -> tuple[float, str]:
    """Участок соцобъекта из ГлавАПУ, если калькулятор считал то же число мест."""
    check = x.get("_glavapu_scenario") or {}
    social = check.get("social_obj") or {}
    got = int(round(_glavapu_ha(social.get(f"{key}.places"))))
    site = _glavapu_ha(social.get(f"{key}.site"))
    if site > 0 and got > 0 and got == places:
        return site * 10000.0, "ГлавАПУ, сверка сценария: участок калькулятора для того же числа мест"
    row = GLAVAPU_SOCIAL_ROWS.get(key)
    normalized = (x.get("_glavapu_import") or {}).get("normalized") or {}
    if row:
        got = int(round(_glavapu_territory_value(normalized.get(row[0]))))
        site = _glavapu_territory_value(normalized.get(row[1]))
        if site > 0 and got > 0 and got == places:
            return site * 10000.0, f"ГлавАПУ, {_glavapu_when(x)}, лист «ТЭП», {row[2]}"
    return 0.0, ""


def _glavapu_public_plots(x: dict[str, Any], gns_total: float) -> tuple[float, str]:
    """Строка 14 ГлавАПУ «Участки общественных, производственных объектов» —
    если калькулятор считал ту же наземную площадь отдельных нежилых зданий."""
    if gns_total <= 0:
        return 0.0, ""
    check = x.get("_glavapu_scenario") or {}
    spp = float(check.get("spp_nonres_ths") or 0.0) * 1000.0
    plots = _glavapu_ha((check.get("balance") or {}).get("14"))
    if plots > 0 and abs(spp - gns_total) <= 0.01 * gns_total:
        return plots * 10000.0, "ГлавАПУ, сверка сценария, баланс территории, строка 14"
    normalized = (x.get("_glavapu_import") or {}).get("normalized") or {}
    spp = _glavapu_territory_value(normalized.get("standalone_nonres_spp_sqm"))
    plots = _glavapu_territory_value(normalized.get("balance_public_ha"))
    if plots > 0 and abs(spp - gns_total) <= 0.01 * gns_total:
        return plots * 10000.0, f"ГлавАПУ, {_glavapu_when(x)}, лист «ТЭП», строка 14"
    return 0.0, ""


def site_objects(x: dict[str, Any], tep: dict[str, Any], limit: float) -> list[dict[str, Any]]:
    """Отдельные здания жилого проекта на своих участках (владелец 23.10.2026).

    Школа и детский сад — участок из ГлавАПУ (строки 21, 25 — если калькулятор
    считал то же число мест), иначе как у типовых зданий калькулятора;
    этажность 4 и 3. Прочие (офисы, ТЦ, наземный паркинг, ФОК, поликлиника без
    строки ГлавАПУ) — 12 этажей, но не выше предела участка; участок — строка
    14 ГлавАПУ, разделённая по наземной площади, иначе два пятна здания.
    """
    rows = _object_rows(x, tep)
    objects: list[dict[str, Any]] = []
    others: list[dict[str, Any]] = []
    for key, row, gns in rows:
        places = int(round(n(row, "units")))
        social = SOCIAL_SITE_OBJECTS.get(key)
        plot, plot_basis = _glavapu_social_plot(x, key, places) if key in GLAVAPU_SOCIAL_ROWS \
            else (0.0, "")
        if social:
            storeys = float(min(social["storeys"], limit))
            item = {"key": key, "label": social["label"], "kind": "social", "gns_sqm": gns,
                    "places": places, "storeys": storeys, "storeys_origin": "default",
                    "footprint_sqm": gns / storeys}
            if plot > 0:
                item.update(plot_sqm=plot, plot_origin="glavapu", plot_basis=plot_basis)
            elif places > 0:
                item.update(plot_sqm=places * social["sqm_per_place"], plot_origin="default",
                            plot_basis=(f"{_norm_ru(social['sqm_per_place'])} м² на место × "
                                        f"{places} мест — {social['typical']}"))
            else:
                item.update(plot_sqm=OTHER_OBJECT_PLOT_PER_FOOTPRINT * item["footprint_sqm"],
                            plot_origin="default",
                            plot_basis="мест в ТЭП нет, поэтому участок — два пятна здания")
            objects.append(item)
            continue
        storeys = float(min(OTHER_OBJECT_STOREYS_DEFAULT, limit))
        label = SOCIAL_SITE_OBJECTS.get(key, {}).get("label") or (
            "Поликлиника" if key == "clinic" else _glavapu_scenario._label(tep, key))
        item = {"key": key, "label": label, "kind": "other", "gns_sqm": gns, "places": places,
                "storeys": storeys, "storeys_origin": "default", "footprint_sqm": gns / storeys}
        if plot > 0:
            item.update(plot_sqm=plot, plot_origin="glavapu", plot_basis=plot_basis)
            objects.append(item)
        else:
            others.append(item)
    others_gns = sum(o["gns_sqm"] for o in others)
    public, public_basis = _glavapu_public_plots(x, others_gns)
    for item in others:
        if public > 0:
            item.update(plot_sqm=public * item["gns_sqm"] / others_gns, plot_origin="glavapu",
                        plot_basis=f"{public_basis}: доля по наземной площади")
        else:
            item.update(plot_sqm=OTHER_OBJECT_PLOT_PER_FOOTPRINT * item["footprint_sqm"],
                        plot_origin="default",
                        plot_basis=(f"{_fmt_ru(item['storeys'])} этажей, участок — два пятна "
                                    "здания (застройка 50%, остальное — проезды и территория "
                                    "у здания); экспертное умолчание"))
        objects.append(item)
    return objects


def _storeys_limit(x: dict[str, Any]) -> float:
    given = _massing_number(x, "max_storeys_allowed")
    return given if given > 0 else float(STOREYS_LIMIT_DEFAULT)


def landscaping_room(x: dict[str, Any], tep: dict[str, Any]) -> tuple[float, int]:
    """Сколько благоустройства помещается на участке → (м², жителей проекта).

    Земля участка без проездов, открытых стоянок и отступов — вместе с кровлей
    стилобата (она не больше пятна, поэтому пятно здесь не вычитается), — но
    не меньше двора по норме. Решение владельца 22.10.2026: площадь
    благоустройства в смете не больше этого (`landscaping_area_per_person`).
    Участок и жители — ПРОЕКТА: очередь читает их у проекта
    (`_site_massing_project`), как пятно и уровни. Участок не задан — (0, 0):
    ограничения нет.
    """
    project = x.get("_site_massing_project")
    if isinstance(project, dict) and project:
        return (float(project.get("landscaping_room_sqm") or 0.0),
                int(project.get("landscaping_room_population") or 0))
    site_sqm = _massing_number(x, "site_area_ha") * 10000.0
    if site_sqm <= 0:
        return 0.0, 0
    # Жилая территория — участок без участков отдельных зданий: у школы и сада
    # своё благоустройство в их стоимости.
    plots = sum(o["plot_sqm"] for o in site_objects(x, tep or {}, _storeys_limit(x)))
    home = max(0.0, site_sqm - plots)
    drive_pct, _ = _massing_value(x, "site_driveways_pct")
    setback_m, _ = _massing_value(x, "site_setback_m")
    parking_sqm = (_massing_number(x, "surface_parking_spaces")
                   * surface_parking_sqm_per_space(x)[0])
    yard_sqm, _ = _yard_floor(x, tep or {}, home)
    room = (max(yard_sqm, home - home * drive_pct / 100.0 - parking_sqm
                - setback_area(site_sqm, setback_m) * home / site_sqm) if home > 0 else yard_sqm)
    population, _ = project_population(tep or {}, project_region(x))
    return max(0.0, room), population


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
    max_storeys = _massing_number(x, "max_storeys_allowed")
    limit = max_storeys if max_storeys > 0 else float(STOREYS_LIMIT_DEFAULT)

    # Школа, детский сад и прочие отдельные здания — на своих участках
    # (владелец 23.10.2026); жилой баланс — на остатке участка и по жилой ГНС.
    objects = site_objects(x, tep, limit)
    objects_plot = sum(o["plot_sqm"] for o in objects)
    objects_gns = sum(o["gns_sqm"] for o in objects)
    home_sqm = max(0.0, site_sqm - objects_plot)
    home_gns = max(0.0, above_gns - objects_gns)
    home_share = home_sqm / site_sqm if site_sqm > 0 else 0.0
    subject = "Жилые дома" if objects else "Здание"
    if objects and site_sqm > 0 and objects_plot >= site_sqm - 0.5:
        warnings.append(
            f"Участки отдельных зданий ({', '.join(o['label'].lower() for o in objects)}) "
            f"занимают {_fmt_ru(objects_plot)} м² — весь участок ({_fmt_ru(site_sqm)} м²), и "
            "жилым домам места не остаётся. Проверьте площадь участка и состав ТЭП.")

    # Двор на участке рядом со зданием — норма региона (владелец 22.10.2026):
    # благоустройство сверх нормы, которому не хватит земли рядом со зданием,
    # может быть на кровле стилобата (`yard_roof_sqm`, считается ниже, от пятна).
    # Площадь и деньги благоустройства в смете — прежние (`landscaping_area`).
    landscaping_sqm, _ = landscaping_area(x, tep)
    room_sqm, room_population = landscaping_room(x, tep)
    yard_sqm, floor_basis = _yard_floor(x, tep, home_sqm)
    if yard_sqm > 0:
        yard_basis = f"Норма региона: {floor_basis}."
    elif without_housing(x):
        yard_basis = "В проекте нет жителей, поэтому двор по их числу не считается."
    else:
        yard_basis = "Жителей в ТЭП нет, поэтому двора по норме нет."

    drive_pct, _ = _massing_value(x, "site_driveways_pct")
    setback_m, _ = _massing_value(x, "site_setback_m")
    spaces = _massing_number(x, "surface_parking_spaces")
    per_space, per_space_basis = surface_parking_sqm_per_space(x)
    use_factor = (_massing_number(x, "underground_contour_use_factor")
                  or _massing_default("underground_contour_use_factor"))
    markup2, _ = _massing_value(x, "underground_level2_markup_pct")
    markup3, _ = _massing_value(x, "underground_level3_markup_pct")

    drive_sqm = home_sqm * drive_pct / 100.0
    parking_sqm = spaces * per_space
    setbacks_sqm = setback_area(site_sqm, setback_m)
    # Полоса отступа идёт по границе всего участка; жилой территории достаётся
    # её доля.
    home_setbacks = setbacks_sqm * home_share
    estimate = home_sqm - yard_sqm - drive_sqm - parking_sqm - home_setbacks

    room = max(0.0, estimate)
    # Остаток участка — наибольшее возможное пятно, а не пятно: жилой дом
    # обычно занимает процент застройки из градплана или ПЗЗ (без него — 30 %).
    # У нежилого проекта умолчания нет (владелец 22.10.2026): плотный офис на
    # маленьком участке занимает его почти целиком; процент — только заданный.
    given_coverage = _massing_number(x, "site_coverage_max_pct")
    if given_coverage > 0:
        coverage_pct, coverage_origin = given_coverage, "manual"
    elif without_housing(x):
        coverage_pct, coverage_origin = 0.0, "none"
    else:
        coverage_pct, coverage_origin = COVERAGE_PCT_DEFAULT, "default"
    coverage_sqm = home_sqm * coverage_pct / 100.0 if coverage_pct > 0 else home_sqm
    base = min(room, coverage_sqm)
    # Жилые дома — типовой этажности (владелец 23.10.2026: 17 этажей, одно число
    # для всех классов), но не выше предела; процент застройки и свободное
    # место — верхняя граница пятна. У проекта без жилья типовой нет.
    given_typical = _massing_number(x, "residential_storeys_typical")
    if without_housing(x):
        typical, typical_origin = 0.0, "none"
    elif given_typical > 0:
        typical, typical_origin = given_typical, "manual"
    else:
        typical, typical_origin = RESIDENTIAL_STOREYS_DEFAULT, "default"
    typical_target = home_gns / min(typical, limit) if typical > 0 and home_gns > 0 else 0.0
    manual_footprint = _massing_number(x, "building_footprint_sqm")
    shortage = 0.0
    if manual_footprint > 0:
        footprint, footprint_origin = manual_footprint, "manual"
        shortage = max(0.0, footprint - room) if site_sqm > 0 else 0.0
        if objects:
            notes.append("Пятно, заданное вручную, — пятно жилых домов: школа, детский сад и "
                         "другие отдельные здания стоят на своих участках.")
        if shortage > 0.5:
            warnings.append(
                f"Пятно застройки, заданное вручную ({_fmt_ru(footprint)} м²), больше места, "
                f"которое остаётся на участке после двора по норме, проездов, открытых стоянок "
                f"и отступов ({_fmt_ru(room)} м²): не хватает {_fmt_ru(shortage)} м², и двор по "
                "норме на участке не помещается. Уменьшите пятно, проезды или отступы.")
    elif site_sqm > 0 and home_gns > 0 and (base <= 0 or home_gns / base > limit + 1e-9):
        # Остаток участка дал бы здание выше предела (51 этаж на гектаре —
        # не ответ): пятно — по пределу, нехватка земли названа числом.
        footprint, footprint_origin = home_gns / limit, "limit"
        shortage = max(0.0, footprint - room)
        cap = (f"на участке разрешено не выше {_fmt_ru(limit)} этажей" if max_storeys > 0 else
               f"выше {_fmt_ru(limit)} этажей расчёт здание не ставит: предельная этажность "
               "участка не задана")
        if shortage > 0:
            tall = (f"{subject} с наземной площадью {_fmt_ru(home_gns)} м² встали бы на него в "
                    f"{_fmt_ru(home_gns / room, 1)} этажа, а " if room > 0 and objects else
                    f"{subject} с наземной площадью {_fmt_ru(home_gns)} м² встало бы на него в "
                    f"{_fmt_ru(home_gns / room, 1)} этажа, а " if room > 0 else
                    f"{subject} с наземной площадью {_fmt_ru(home_gns)} м² ставить некуда, а ")
            warnings.append(
                f"На участке после двора, проездов, открытых стоянок и отступов под здание "
                f"остаётся {_fmt_ru(room)} м². {tall}{cap}. Поэтому пятно взято по пределу — "
                f"{_fmt_ru(footprint)} м², и здание не помещается: не хватает {_fmt_ru(shortage)} м², "
                "и двор по норме на участке тогда не помещается. Сократите проезды или отступы, "
                "уменьшите площадь здания или задайте пятно застройки вручную.")
        else:
            warnings.append(
                f"При проценте застройки {_fmt_ru(coverage_pct)}% под здание идёт "
                f"{_fmt_ru(coverage_sqm)} м², и {subject.lower()} с наземной площадью "
                f"{_fmt_ru(home_gns)} м² были бы выше предела, а {cap}. Поэтому пятно взято по "
                f"пределу — {_fmt_ru(footprint)} м², это "
                f"{_fmt_ru(footprint / max(home_sqm, 1.0) * 100)}% "
                f"{'жилой территории' if objects else 'участка'}. "
                "Место на участке для этого есть, но процент застройки выше "
                f"{'заданного' if given_coverage > 0 else 'обычного'}: проверьте его по "
                "градплану или уменьшите площадь здания.")
    elif typical_target > 0 and typical_target <= base + 1e-9:
        footprint, footprint_origin = typical_target, "typical"
    elif coverage_sqm < room:
        footprint, footprint_origin = coverage_sqm, "coverage"
    else:
        footprint, footprint_origin = room, "estimate"

    if site_sqm <= 0:
        warnings.append("Площадь участка не задана, поэтому пятно застройки, этажность "
                        "и число подземных уровней не посчитаны. Укажите площадь участка "
                        "во вкладке «ТЭП».")

    # Земля участка без здания, проездов, стоянок и отступов — на ней двор по
    # норме и благоустройство сверх неё. Что не помещается сверх нормы — на
    # кровлю стилобата; не помещается сама норма — это нехватка выше.
    ground_sqm = max(0.0, home_sqm - footprint - drive_sqm - parking_sqm - home_setbacks)
    yard_roof_sqm = max(0.0, landscaping_sqm - max(ground_sqm, yard_sqm))
    if yard_sqm > 0 and yard_roof_sqm > 0.5:
        yard_basis += (f" Всё благоустройство проекта ({_fmt_ru(landscaping_sqm)} м²) рядом со "
                       f"зданием не помещается: на участке для него {_fmt_ru(ground_sqm)} м². "
                       f"Остальное ({_fmt_ru(yard_roof_sqm)} м²) может быть на кровле стилобата.")
    elif yard_sqm > 0 and landscaping_sqm > yard_sqm + 0.5:
        yard_basis += (f" Всё благоустройство проекта ({_fmt_ru(landscaping_sqm)} м²) помещается "
                       f"на участке рядом со зданием: для него там {_fmt_ru(ground_sqm)} м².")

    storeys = _mo_land_capacity.average_storeys(home_gns, footprint) if footprint > 0 else 0.0
    if max_storeys > 0 and storeys > max_storeys + 1e-9:
        warnings.append(
            f"Средняя этажность по расчёту — {_fmt_ru(storeys, 1)}, а на участке разрешено "
            f"не выше {_fmt_ru(max_storeys)} этажей. {subject} с наземной площадью "
            f"{_fmt_ru(home_gns)} м² на этом участке не помещается: уменьшите площадь "
            "здания или проверьте допущения по пятну застройки.")
    elif max_storeys <= 0 and storeys > 0:
        notes.append(f"Предельная этажность участка не задана, поэтому расчёт не ставит здание "
                     f"выше {_fmt_ru(limit)} этажей. Задайте предел из градплана, если он известен.")

    # Подземный контур — участок без отступов и без участков соцобъектов
    # (владелец 23.10.2026): под школой, садом и поликлиникой паркинг жилья не
    # строят, их участки передаются городу. Полоса отступа — по доле.
    social_plot = sum(o["plot_sqm"] for o in objects if o["key"] in SOCIAL_PLOT_KEYS)
    contour = (max(0.0, site_sqm - social_plot) * (site_sqm - setbacks_sqm) / site_sqm
               if site_sqm > 0 else 0.0)
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
        # Отдельные здания на своих участках и жилой баланс на остатке.
        "objects": objects,
        "objects_plot_sqm": objects_plot,
        "social_plot_sqm": social_plot,
        "objects_gns_sqm": objects_gns,
        "residential_site_sqm": home_sqm,
        "residential_gns_sqm": home_gns,
        "residential_setbacks_sqm": home_setbacks,
        "yard_sqm": yard_sqm,
        "yard_basis": yard_basis,
        "landscaping_sqm": landscaping_sqm,
        "yard_roof_sqm": yard_roof_sqm,
        # Потолок площади благоустройства в смете и жители проекта — очередь
        # читает их отсюда (`landscaping_room`).
        "landscaping_room_sqm": room_sqm,
        "landscaping_room_population": room_population,
        "yard_ground_sqm": ground_sqm,
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
        "footprint_shortage_sqm": shortage,
        # Всё, что стоит на участке: пятно жилых домов и пятна отдельных зданий
        # (владелец 23.10.2026) — тот же итог, что сумма корпусов на схеме.
        "built_sqm": footprint + sum(o["footprint_sqm"] for o in objects),
        "built_share": ((footprint + sum(o["footprint_sqm"] for o in objects)) / site_sqm
                        if site_sqm > 0 else 0.0),
        "coverage_pct": coverage_pct,
        "coverage_origin": coverage_origin,
        "coverage_sqm": coverage_sqm,
        "typical_storeys": typical,
        "typical_storeys_origin": typical_origin,
        # Доля жилой территории (у проекта без отдельных зданий — участка).
        "footprint_share": footprint / home_sqm if home_sqm > 0 else 0.0,
        "average_storeys": storeys,
        "max_storeys_allowed": max_storeys,
        "storeys_limit": limit,
        "storeys_limit_origin": "manual" if max_storeys > 0 else "default",
        "underground_contour_sqm": contour,
        "underground_use_factor": use_factor,
        "underground_sqm": under_sqm,
        # Из чего она: подземные продукты проекта и гаражи отдельных объектов.
        "underground_garages_sqm": sum(n(row, "under_gns") for row in tep.values()
                                       if isinstance(row, dict)),
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
            "footprint_sqm": footprint, "site_sqm": home_sqm,
            "average_storeys": storeys, "underground_sqm": under_sqm,
            "underground_levels": levels, "objects": objects}),
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
    objects = m.get("objects") or []
    head = ("Жилые дома: пятно застройки около {fp} м² ({share}% жилой территории)"
            if objects else "Здание: пятно застройки около {fp} м² ({share}% участка)")
    rest = (". " + "; ".join(f"{o['label']} — участок {_fmt_ru(o['plot_sqm'])} м², "
                              f"{_fmt_ru(o['storeys'])} этажа" if o["storeys"] < 5 else
                              f"{o['label']} — участок {_fmt_ru(o['plot_sqm'])} м², "
                              f"{_fmt_ru(o['storeys'])} этажей" for o in objects)
            if objects else "")
    return (head.format(fp=_fmt_ru(footprint), share=_fmt_ru(footprint / site * 100))
            + f", средняя этажность около {_fmt_ru(float(m.get('average_storeys') or 0.0), 1)}"
            f"{tail}{rest}. Это оценка по балансу территории, а не проект.")
