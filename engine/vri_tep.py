"""Быстрый ТЭП по ВРИ: скелет ТЭП ГлавАПУ, vri_tep_quick, прокси генплана.

Скелет строк ТЭП ГлавАПУ и заполненный шаблон, рекомендуемая плотность,
vri_tep_quick, прокси генплана и простая XLSX-книга из строк
(_build_glavapu_xlsx_from_rows).

Не самостоятельный модуль. `main_legacy.py` выполняет этот файл в своём
пространстве имён на том месте, где этот код стоял раньше
(`_engine_part("vri_tep")`), поэтому здесь видны все имена движка,
а подмены `core.<имя>` из `main.py` и тестов действуют и на этот код.
Отдельно не импортировать: второй импорт поднял бы вторую копию движка.
"""
# ruff: noqa

_GLAVAPU_TEP_SKELETON: list[tuple[str, str, str]] = [
    ('1', 'Площадь территории проектирования', 'га'),
    ('2', 'Плотность от СПП', 'тыс.кв.м./га'),
    ('3', 'Плотность от НП', 'тыс.кв.м./га'),
    ('4', 'Население', 'чел.'),
    ('5', 'Количество квартир', 'шт.'),
    ('', 'СПП в ГНС:', ''),
    ('6', 'СПП, всего:', 'тыс.кв.м.'),
    ('7', 'СПП жилых зданий, в т.ч.:', 'тыс.кв.м.'),
    ('7.1', 'СПП жилая', 'тыс.кв.м.'),
    ('7.2', 'СПП нежилой части жилых зданий', 'тыс.кв.м.'),
    ('8', 'СПП нежилых зданий, в т.ч.:', 'тыс.кв.м.'),
    ('8.1', 'СПП общественных, производственных объектов', 'тыс.кв.м.'),
    ('8.2', 'СПП социальных объектов', 'тыс.кв.м.'),
    ('', 'Наземная площадь:', ''),
    ('9', 'НП, всего:', 'тыс.кв.м.'),
    ('9.1', 'НП жилых зданий, в т.ч.:', 'тыс.кв.м.'),
    ('9.1.1', 'НП жилая', 'тыс.кв.м.'),
    ('9.1.2', 'НП нежилой части жилых зданий', 'тыс.кв.м.'),
    ('9.2', 'НП нежилых зданий, в т.ч.:', 'тыс.кв.м.'),
    ('9.2.1', 'НП общественных, производственных объектов', 'тыс.кв.м.'),
    ('9.2.2', 'НП социальных объектов', 'тыс.кв.м.'),
    ('', 'Единый показатель:', ''),
    ('10', 'Площадь квартир', 'тыс.кв.м.'),
    ('11', 'Нежилая наземная площадь (ННП)', 'тыс.кв.м.'),
    ('', 'Баланс территории:', ''),
    ('12', 'Территория жилых зданий, в т.ч.:', 'га'),
    ('12.1', 'участки многоквартирных жилых зданий', 'га'),
    ('12.2', 'незастраиваемая территория', 'га'),
    ('13', 'Участки социальных объектов', 'га'),
    ('14', 'Участки общественных, производственных объектов', 'га'),
    ('', 'Расчётная плотность территории от НП:', ''),
    ('15', 'жилых участков', 'тыс.кв.м./га'),
    ('16', 'социальных объектов', 'тыс.кв.м./га'),
    ('17', 'общественных, производственных объектов', 'тыс.кв.м./га'),
    ('', 'ДОО:', ''),
    ('18', 'количество мест', 'мест'),
    ('19', 'СПП', 'тыс.кв.м.'),
    ('20', 'наземная площадь', 'тыс.кв.м.'),
    ('21', 'площадь земельного участка', 'га'),
    ('', 'Школы:', ''),
    ('22', 'количество мест', 'мест'),
    ('23', 'СПП', 'тыс.кв.м.'),
    ('24', 'наземная площадь', 'тыс.кв.м.'),
    ('25', 'площадь земельного участка', 'га'),
    ('', 'Поликлиники:', ''),
    ('26', 'мощность', 'пос./см.'),
    ('27', 'СПП', 'тыс.кв.м.'),
    ('28', 'наземная площадь', 'тыс.кв.м.'),
    ('29', 'площадь земельного участка', 'га'),
    ('', 'Расчёт объектов обслуживания:', ''),
    ('30', 'ДОО', 'мест'),
    ('31', 'Школа', 'мест'),
    ('32', 'Поликлиника смешанного типа', 'пос./см.'),
    ('33', 'Поликлиника взрослая', 'пос./см.'),
    ('34', 'Поликлиника детская', 'пос./см.'),
    ('35', 'Плоскостные спортивные сооружения', 'га'),
    ('36', 'Крытые объекты спорта (ННП), в т.ч.:', 'тыс.кв.м.'),
    ('36.1', 'в радиусе пешеходной доступности до 500 м', 'тыс.кв.м.'),
    ('36.2', 'в радиусе пешеходной доступности до 1500 м', 'тыс.кв.м.'),
    ('37', 'Объекты торговли (ННП)', 'тыс.кв.м.'),
    ('38', 'Объекты бытового обслуживания населения (ННП)', 'тыс.кв.м.'),
    ('39', 'Объекты общественного питания (ННП)', 'тыс.кв.м.'),
    ('40', 'Объекты культуры и досуга (ННП)', 'тыс.кв.м.'),
    ('41', 'Объекты для размещения городских служб (ННП)', 'тыс.кв.м.'),
    ('', 'Расчёт машино-мест:', ''),
    ('42', 'Места хранения и паркирования, в т.ч.:', 'м/м'),
    ('42.1', 'Постоянные парковки', 'м/м'),
    ('42.2', 'Гостевые парковки', 'м/м'),
    ('42.3', 'Приобъектные парковки', 'м/м'),
    ('43', 'Места кратковременной остановки', 'м/м'),
    ('', 'Расчёт стоимости смены ВРИ:', 'млн.руб.'),
    ('44', 'Многоквартирная жилые здания', 'млн.руб.'),
    ('45', 'Индивидуальные, блочные жилые здания', 'млн.руб.'),
    ('46', 'Хранение индивидуального транспорта', 'млн.руб.'),
    ('47', 'Объекты мультифункционального назначения', 'млн.руб.'),
    ('48', 'Объекты для временного проживания', 'млн.руб.'),
    ('49', 'Административные, офисные здания', 'млн.руб.'),
    ('50', 'Производственные здания', 'млн.руб.'),
    ('51', 'Социальные объекты', 'млн.руб.'),
    ('52', 'Льгота на стр-во жилья за создание МПТ', 'млн.руб.'),
    ('53', 'Льгота на стр-во жилья за передачу жилых помещений в собственность города Москвы', 'млн.руб.'),
    ('', 'Расчёт компенсации за социальные объекты:', 'млн.руб.'),
    ('54', 'ДОО', 'млн.руб.'),
    ('55', 'Школа', 'млн.руб.'),
    ('56', 'Поликлиника', 'млн.руб.'),
    ('', 'Элементы жилых территорий:', ''),
    ('57', 'Озелененные территории ЖК', 'га'),
    ('58', 'Территории детских площадок', 'га'),
    ('59', 'Территории площадок отдыха взрослых', 'га'),
    ('60', 'Озелененные территории общего пользования', 'га'),
]


# Нули калькулятор пишет в формате единицы измерения: «0,000» у тысяч
# квадратных метров, «0,0000» у гектаров — голый «0» сразу выдаёт подделку.
_GLAVAPU_ZERO_BY_UNIT = {
    "тыс.кв.м.": "0,000",
    "га": "0,0000",
    "млн.руб.": "0,000",
    "тыс.кв.м./га": "0,00",
}


def _glavapu_rows(values: dict[str, str]) -> list[list[str]]:
    """Полный 91-строчный лист ТЭП формата калькулятора ГлавАПУ: секции и
    номера строк — как в эталоне; незаполненное — нули в формате единицы.
    Секции «Расчёт стоимости смены ВРИ:» и «Расчёт компенсации…» несут итог
    прямо в строке секции — значение подставляется по ключу «#Имя секции»."""
    rows: list[list[str]] = [["№", "Наименования", "Единицы измерения", "Показатель"]]
    for code, name, unit in _GLAVAPU_TEP_SKELETON:
        if code:
            value = values.get(code, "") or _GLAVAPU_ZERO_BY_UNIT.get(unit, "0")
        else:
            value = values.get("#" + name, "")
        rows.append([code, name, unit, value])
    return rows


def _manual_tep_filled_template(project_name: str, region_label: str,
                                area_ha: float, vri_mln: float, comp_mln: float,
                                products: dict[str, dict[str, float]]) -> bytes:
    """Шаблон DevelopAid, заполненный расчётом: тот же файл, что отдаёт
    /template, — его можно поправить руками и загрузить обратно боту."""
    from openpyxl import load_workbook

    content = base64.b64decode(
        MANUAL_TEP_TEMPLATE_B64_PATH.read_text(encoding="ascii").strip())
    book = load_workbook(io.BytesIO(content))
    sheet = book["ТЭП DevelopAid"]
    rows_by_label = {str(sheet.cell(row=r, column=1).value or "").strip(): r
                     for r in range(1, sheet.max_row + 1)}

    def put(label: str, value: Any) -> None:
        row = rows_by_label.get(label)
        if row:
            sheet.cell(row=row, column=2, value=value)

    put("Название проекта", project_name)
    put("Регион / город", region_label)
    put("Площадь территории", round(float(area_ha or 0), 4))
    put("Смена ВРИ / земельные права", round(float(vri_mln or 0), 3))
    put("Социальная компенсация", round(float(comp_mln or 0), 3))
    columns = {"gns": 3, "total_area": 4, "useful": 5,
               "saleable": 6, "transfer": 7, "units": 8}
    for code, fields in products.items():
        row = rows_by_label.get(code)
        if not row:
            continue
        for field, column in columns.items():
            value = float(fields.get(field) or 0)
            if value > 0:
                # Количество — штуки: дробные 3 320,51 квартиры из плотности
                # выглядят ошибкой ввода.
                sheet.cell(row=row, column=column,
                           value=round(value) if field == "units" else round(value, 2))
    out = io.BytesIO()
    book.save(out)
    return out.getvalue()


# Рекомендуемая плотность от СПП калькулятора ГлавАПУ, тыс. м²/га — таблица по
# площади территории (без ограничений) с линейной интерполяцией и округлением
# до 0,1 (код калькулятора: Yd/dg). Нагатино 17,8109 га → 23,1.
GLAVAPU_DENSITY_BY_AREA = ((2.5, 35.0), (10.0, 25.0), (22.5, 22.0), (45.0, 20.0))


def glavapu_recommended_density(area_ha: float) -> float:
    area = max(0.0, float(area_ha or 0.0))
    table = GLAVAPU_DENSITY_BY_AREA
    if area <= table[0][0]:
        return table[0][1]
    for (a0, d0), (a1, d1) in zip(table, table[1:]):
        if area <= a1:
            return round(d0 + (area - a0) / (a1 - a0) * (d1 - d0), 1)
    return table[-1][1]


# Норма МПТ калькулятора — м² наземной площади на рабочее место по виду
# (код калькулятора, таблица Q): встроенные помещения и офисы 32, торговля 45.
# Владелец норм — `vri_benefits.JOB_NORM_SQM` (льготы ВРИ считают по ней же
# рабочие места); здесь только имена видов этого блока.
GLAVAPU_SQM_PER_JOB = {"built_in": vri_benefits.JOB_NORM_SQM["built_in"],
                       "offices": vri_benefits.JOB_NORM_SQM["office"],
                       "retail": vri_benefits.JOB_NORM_SQM["retail"]}


def _ru_trim(value: float, digits: int) -> str:
    text = f"{float(value):.{digits}f}".rstrip("0").rstrip(".")
    return text.replace(".", ",") or "0"


def vri_tep_quick(region: str, query: str,
                 site_area_ha: float | None = None,
                 district: str | None = None,
                 density_sqm_per_ha: float | None = None,
                 analysis: dict[str, Any] | None = None) -> dict[str, Any]:
    """Кнопка бота «Посчитать ВРИ и ТЭП»: карточка + файл формата ГлавАПУ.

    МО считается полностью (РНГП, УПКС, Кд); Москва — по формулам
    калькулятора ГлавАПУ, восстановленным из его выгрузок: СПП 94/6,
    НП 90% СПП, квартиры 65% жилой СПП, население 33 м² квартир на человека,
    соцпотребность по нормативам на тысячу жителей. Машино-места и плату за
    смену ВРИ бот не реверсирует (их формулы живут в браузерном калькуляторе)
    — они нули, а карточка отсылает в мини-приложение.
    """
    def fmt(value: Any, digits: int = 1) -> str:
        try:
            return f"{float(value):,.{digits}f}".replace(",", " ").replace(".", ",")
        except (TypeError, ValueError):
            return "—"

    if region == "mo":
        request_kwargs: dict[str, Any] = dict(
            query=query, site_area_ha=float(site_area_ha or 0),
            district=str(district or ""))
        if density_sqm_per_ha and density_sqm_per_ha > 0:
            request_kwargs["density_sqm_per_ha"] = float(density_sqm_per_ha)
        result = mo_calculate(MoCalculateRequest(**request_kwargs))
        tep = result.get("tep") or {}
        social = result.get("social") or {}
        vri = result.get("vri") or {}
        parcel = result.get("territory") or {}
        area = float(parcel.get("site_area_ha") or site_area_ha or 0)
        apartments = float((tep.get("apartments") or {}).get("saleable") or 0)
        density = float(result.get("density_sqm_per_ha") or 0)
        vri_mln = float(vri.get("payment_used_mln") or vri.get("payment_mln") or 0)
        dou = float((social.get("kindergarten") or {}).get("places") or 0)
        school = float((social.get("school") or {}).get("places") or 0)
        clinic = float((social.get("clinic") or {}).get("capacity") or 0)
        parking = float((tep.get("underground_parking") or {}).get("units") or 0)
        apartments_row = tep.get("apartments") or {}
        commerce_row = tep.get("ground_commercial") or {}
        kinder = social.get("kindergarten") or {}
        school_row = social.get("school") or {}
        clinic_row = social.get("clinic") or {}
        parking_row = social.get("parking") or {}
        green = social.get("green") or {}
        premises = {str(item.get("label") or ""): float(item.get("gba_sqm") or 0)
                    for item in (social.get("public_premises") or [])}
        social_gba = (float(kinder.get("gba_sqm") or 0)
                      + float(school_row.get("gba_sqm") or 0)
                      + float(clinic_row.get("gba_sqm") or 0))
        social_site = (float(kinder.get("site_ha") or 0)
                       + float(school_row.get("site_ha") or 0)
                       + float(clinic_row.get("site_ha") or 0))
        apart_gns = float(apartments_row.get("gns") or 0)
        apart_np = float(apartments_row.get("total_area") or 0)
        comm_gns = float(commerce_row.get("gns") or 0)
        comm_np = float(commerce_row.get("total_area") or 0)
        permanent = float(parking_row.get("permanent_spaces") or 0)
        temporary = float(parking_row.get("temporary_spaces") or 0)
        th = lambda v, d=3: fmt(v / 1000.0, d)
        values = {
            "1": fmt(area, 4),
            "2": fmt(density / 1000.0, 2),
            "3": fmt(density * (apart_np / apart_gns if apart_gns else 0.9) / 1000.0, 2),
            "4": fmt(float(social.get("population") or 0), 0),
            "5": fmt(float(apartments_row.get("units") or 0), 0),
            "6": th(apart_gns + comm_gns + social_gba),
            "7": th(apart_gns + comm_gns),
            "7.1": th(apart_gns),
            "7.2": th(comm_gns),
            "8": th(social_gba),
            "8.2": th(social_gba),
            "9": th(apart_np + comm_np + social_gba),
            "9.1": th(apart_np + comm_np),
            "9.1.1": th(apart_np),
            "9.1.2": th(comm_np),
            "9.2": th(social_gba),
            "9.2.2": th(social_gba),
            "10": th(apartments),
            "11": th(float(commerce_row.get("saleable") or 0)),
            "12": fmt(max(area - social_site, 0.0), 4),
            "13": fmt(social_site, 4),
            "18": fmt(dou, 0),
            "19": th(float(kinder.get("gba_sqm") or 0)),
            "20": th(float(kinder.get("gba_sqm") or 0)),
            "21": fmt(float(kinder.get("site_ha") or 0), 4),
            "22": fmt(school, 0),
            "23": th(float(school_row.get("gba_sqm") or 0)),
            "24": th(float(school_row.get("gba_sqm") or 0)),
            "25": fmt(float(school_row.get("site_ha") or 0), 4),
            "26": fmt(clinic, 0),
            "27": th(float(clinic_row.get("gba_sqm") or 0)),
            "28": th(float(clinic_row.get("gba_sqm") or 0)),
            "29": fmt(float(clinic_row.get("site_ha") or 0), 4),
            "30": fmt(dou, 0),
            "31": fmt(school, 0),
            "32": fmt(clinic, 0),
            "37": th(premises.get("Торговые объекты", 0)),
            "38": th(premises.get("Бытовое обслуживание", 0)),
            "39": th(premises.get("Общественное питание", 0)),
            "40": th(premises.get("Культура и досуг", 0)),
            "41": th(premises.get("Городские службы", 0)),
            "42": fmt(permanent + temporary, 0),
            "42.1": fmt(permanent, 0),
            "42.2": fmt(temporary, 0),
            "#Расчёт стоимости смены ВРИ:": fmt(vri_mln, 3),
            "44": fmt(vri_mln, 3),
            "57": fmt(float(green.get("quarter_sqm") or 0) / 10000.0, 4),
            "60": fmt(float(green.get("public_ha") or 0), 4),
        }
        rows = _glavapu_rows(values)
        extra_sheets = [
            ("МПТ", [
                ["№", "Наименования", "Единицы измерения", "Показатель"],
                ["1", "Встроенно-пристроенные помещения многоквартирного дома (2.1.1, 2.5, 2.6)",
                 "рабочие места",
                 fmt(math.ceil(comm_gns / 36.0) if comm_gns > 0 else 0, 0)],
            ]),
            ("Машино-места", [
                ["№", "Наименования", "Единицы измерения", "Всего",
                 "Приобъектные", "Постоянные", "Гостевые", "Кратковременные"],
                ["1", "Многоквартирный дом (2.1.1, 2.5, 2.6)", "машино-места",
                 fmt(permanent + temporary, 0), "0", fmt(permanent, 0),
                 fmt(temporary, 0), "0"],
                ["2", "Встроенно-пристроенные помещения многоквартирного дома (2.1.1, 2.5, 2.6)",
                 "машино-места", "0", "0", "0", "0", "0"],
            ]),
        ]
        params = [
            ["Параметр", "Значение", "Ед.изм."],
            ["Социальные объекты", "", ""],
            ["Округ", str(parcel.get("district") or ""), "—"],
            ["Плотность застройки", fmt(density, 0), "м² квартир / га"],
            ["Стоимость смены ВРИ", "", ""],
            ["Методика", "Нормативы РНГП МО, УПКС, Кд (Таблица 3)", "—"],
        ]
        card = (
            "<b>ВРИ и ТЭП · Московская область</b>\n"
            f"Участок: <code>{html.escape(str(query)[:80])}</code>\n"
            f"• площадь — {fmt(area, 4)} га"
            f" · округ — {html.escape(str(parcel.get('district') or '—'))}\n"
            f"• квартиры — {fmt(apartments, 0)} м² продаваемой"
            f" (плотность {fmt(density, 0)} м² квартир/га"
            f"{' — по умолчанию' if not density_sqm_per_ha else ''})\n"
            f"• соцобъекты — ДОО {fmt(dou, 0)} мест, СОШ {fmt(school, 0)} мест, "
            f"поликлиника {fmt(clinic, 0)} пос./см.\n"
            f"• подземный паркинг — {fmt(parking, 0)} м/м\n"
            f"• <b>плата за смену ВРИ — {fmt(vri_mln, 1)} млн ₽</b>\n"
        )
        warn = [str(w) for w in (result.get("warnings") or [])][:3]
        if warn:
            card += "<i>" + html.escape("; ".join(warn)) + "</i>\n"
        template_region = "Московская область" + (
            f" · {parcel.get('district')}" if parcel.get("district") else "")
        template_vri, template_comp = vri_mln, 0.0
        template_products = {
            "apartments": {"gns": apart_gns, "total_area": apart_np,
                           "saleable": apartments,
                           "units": float(apartments_row.get("units") or 0)},
            "ground_commercial": {"gns": comm_gns, "total_area": comm_np,
                                  "saleable": float(commerce_row.get("saleable") or 0)},
            "underground_parking": {"units": permanent + temporary},
            "kindergarten": {"units": dou,
                             "total_area": float(kinder.get("gba_sqm") or 0)},
            "school": {"units": school,
                       "total_area": float(school_row.get("gba_sqm") or 0)},
            "clinic": {"units": clinic,
                       "total_area": float(clinic_row.get("gba_sqm") or 0)},
        }
    else:
        # По адресу калькулятор не искал: «Мишина 46 Москва» падал в анализе
        # территории. Кадастры добываются тем же поиском, что и основной бот.
        numbers = _CADASTRAL_NUMBER_RE.findall(str(query or "").replace("：", ":"))
        if not numbers:
            lookup = land_lookup_via_core(str(query or ""))
            numbers = [str(item.get("cadastral_number") or "")
                       for item in (lookup.get("results") or [])
                       if item.get("kind") == "land" and item.get("cadastral_number")][:10]
            if not numbers:
                raise HTTPException(
                    status_code=400,
                    detail="По этому адресу участок в ЕГРН не нашёлся. "
                           "Пришлите кадастровый номер или уточните адрес.")
        # Территорию мог принести вызывающий: страница спрашивает её перед
        # расчётом, и второй поход к ГлавАПУ за тот же клик — это лишние
        # секунды на ровном месте. Именно они и складывались в «очень долго».
        if not isinstance(analysis, dict) or not (analysis.get("coefficients") or {}):
            analysis = analyze_cadastral_territory(CadastralAnalysisRequest(
                cadastral_numbers=numbers))
        territory = analysis.get("territory") or {}
        coeff = analysis.get("coefficients") or {}
        area = float(territory.get("area_ha") or site_area_ha or 0)
        # Воспроизводим формулы калькулятора ГлавАПУ, восстановленные по двум
        # его выгрузкам (население 422 и 1224 — обе сходятся до последней
        # цифры): СПП 94/6, НП — 90% СПП, квартиры — 65% жилой СПП, население —
        # 33 м² квартир на человека, квартир — население/2,1, соцпотребность и
        # обслуживание — нормативы на тысячу жителей с округлением вверх.
        # Плотность: заданная вызывающим, иначе рекомендуемая калькулятора —
        # таблица по площади территории (`glavapu_recommended_density`).
        # Прежде здесь стояли 35 тыс. м²/га для любой площади: это верно
        # только до 2,5 га, а на Нагатино (17,81 га) калькулятор берёт 23,1.
        density = (float(density_sqm_per_ha) if density_sqm_per_ha and density_sqm_per_ha > 0
                   else glavapu_recommended_density(area) * 1000.0)
        spp = area * density
        apartments_gns = spp * MKD_SPP_SPLIT["apartments"]
        apartments = apartments_gns * 0.65
        commerce_gns = spp * MKD_SPP_SPLIT["ground_commercial"]
        population = math.ceil(apartments / 33.0) if apartments > 0 else 0
        units = round(population / 2.1) if population else 0
        # Вверх, как все нормативы на тысячу: на Нагатино (7 618 жителей)
        # калькулятор даёт 336, округление к ближайшему давало 335.
        dou = math.ceil(population * 44 / 1000) if population else 0
        school = math.ceil(population * 90 / 1000) if population else 0
        # Взрослая поликлиника — 13,2 пос./смену на тысячу, не 13,3: три
        # выгрузки (население 377, 422 и 1224 → 5, 6 и 17) сходятся только на
        # 13,2 с округлением вверх; 13,3 на населении 377 давала 6 против 5
        # у штатного калькулятора — и через мощность завышала компенсацию.
        clinic_adult = math.ceil(population * 13.2 / 1000) if population else 0
        # Детская — 5,8 пос./смену на тысячу (код калькулятора; Нагатино
        # 06.10.2026: 45 при 7 618 жителях). Прежние 6,5 давали 50.
        clinic_child = math.ceil(population * 5.8 / 1000) if population else 0
        # Смешанная поликлиника — свой норматив 19 пос./смену на тысячу, а не
        # сумма взрослой и детской: на населении 970 город даёт 19 при наших
        # частях 13+7 (дрейф компенсации 190,814 против 200,857, третья точка
        # 16.08.2026); на населении 377 и 422 суммы совпадали со смешанной
        # случайно (8 = 5+3, 9 = 6+3). Компенсация считается от смешанной.
        clinic = math.ceil(population * 19.0 / 1000) if population else 0
        per_k = lambda norm, digits: math.ceil(population * norm / 1000 * 10 ** digits) / 10 ** digits
        # Компенсация за соцобъекты — ставки из выгрузки калькулятора от
        # 01.08.2026 (188,414/19, 294,540/38 и 97,714/9): город индексирует их
        # поквартально, выгрузка от 21.07 несла ставки на ~11% ниже.
        # Компенсация за соцобъекты — формулой калькулятора (функция ap):
        # коэфф × (УУПСС на место × места / 1000 + площадь ЗУ × УПКС квартала).
        # Прежде ставки были зашиты тремя константами, снятыми с одного
        # участка, — и на любом другом квартале платёж уезжал вместе с его
        # УПКС: на 77:01 это дало 185,1 млн против 220,3 у калькулятора.
        # Обратный счёт по трём прежним ставкам дал один и тот же УПКС
        # 98 973 ₽/м² и нормативы земли 35 / 19 / 30 м² на место — формула
        # восстановлена по трём независимым точкам.
        upks = _land_float(coeff.get("upks_zh_high")) or 0.0
        def _social_comp(places: float, uupss_th: float, zu_sqm: float,
                         factor: float, legacy_rate: float) -> float:
            if places <= 0:
                return 0.0
            if upks <= 0:
                # УПКС не пришёл: без земли платёж вышел бы почти вдвое ниже.
                # Прежние ставки сняты при УПКС 98 973 ₽/м² — это хотя бы
                # порядок, а не половина суммы.
                return places * legacy_rate
            return factor * (uupss_th * places / 1000.0 + places * zu_sqm * upks / 1e6)
        # Земля на место — по мощности объекта, как в коде калькулятора:
        # ДОО 35 м² до 150 мест, дальше 32; школа 19 до 900, 16 до 1 500,
        # дальше 14. Мощность поликлиники в компенсации — взрослая + детская
        # (Нагатино 06.10.2026: 101 + 45 = 146 при строке 32 = 145).
        dou_land = 35.0 if dou <= 150 else 32.0
        school_land = 19.0 if school <= 900 else 16.0 if school <= 1500 else 14.0
        comp_dou = _social_comp(dou, 4799.71, dou_land, 1.2, 9.916526)
        comp_school = _social_comp(school, 4578.69, school_land, 1.2, 7.751053)
        comp_clinic = _social_comp(clinic_adult + clinic_child, 7887.92, 30.0, 1.0, 10.857111)
        # МПТ встроенных помещений — 32 м² НП на место, округление ВНИЗ: так
        # считает код калькулятора (таблица Q: embeddedNonResidential 32,
        # места по ВРИ — lodash `floor`; вверх, `ceil`, — только соцобъекты).
        jobs = math.floor(commerce_gns * 0.9 / GLAVAPU_SQM_PER_JOB["built_in"]) if commerce_gns > 0 else 0
        # Машино-места. Постоянные — методика города с августа 2026: одно
        # место на 90 м² НП жилых зданий (те же 100 м² их СПП) × К1. Прежняя
        # строка калькулятора — площадь квартир × 0,257/33 × К1 — на свежих
        # выгрузках давала 73 и 82 места против 144 и 161 у штатного расчёта;
        # новая сверена по двум выгрузкам от 16.08.2026 (население 377 и 422),
        # обе сходятся до единицы. Остальные виды без изменений: гостевые —
        # десятая часть постоянных, приобъектные встроенных помещений —
        # НП/90 × К1 × К2, кратковременные — квартиры/22 100 и НП/450 с кэпом
        # 4; округление всюду вверх.
        #
        # К2 брался «вне ТТК» с оговоркой «признак попадания внутрь ТТК анализ
        # не отдаёт». Оговорка неверна: признак приходит тем же ответом
        # (`insideTTC`) и лежит в двух строках от самого коэффициента, а у
        # анализа есть оба значения. Выгрузка штатного калькулятора по участку
        # внутри ТТК подписывает строку «К2 — деловая активность (внутри ТТК)»
        # и берёт внутренний коэффициент; наш расчёт на тех же вводных считал
        # приобъектные места по внешнему — то есть по другому числу.
        k1 = _land_float(coeff.get("rail")) or 0.0
        inside_ttc = bool(territory.get("inside_ttc"))
        k2_key = "business_inside_ttc" if inside_ttc else "business_outside_ttc"
        k2 = _land_float(coeff.get(k2_key)) or 0.0
        if not k2 and inside_ttc:
            # Внутреннего значения нет — берём внешнее, но это уже другое
            # число, и молчать о подмене нельзя.
            k2 = _land_float(coeff.get("business_outside_ttc")) or 0.0
            k2_key = "business_outside_ttc"
        commerce_np = commerce_gns * 0.9
        # Плата за смену ВРИ МКД — формула калькулятора (класс Df, calcOwn):
        # 1,8964 × СПП жилых зданий × коэффициент аренды квартала × базовая
        # стоимость МКД / 1,00001. Обе контрольные выгрузки сходятся:
        # 1 267,5 и 2 917,9 млн ₽. Считается для права собственности — у
        # аренды жилья делитель 1,001, разница 0,1%; льготы за МПТ и передачу
        # жилья городу требуют условий соглашения и остаются мини-приложению.
        rent_coeff = _land_float(coeff.get("rent")) or 0.0
        base_cost = _land_float(coeff.get("base_cost_zh_high")) or 0.0
        vri_msk = 0.0
        if rent_coeff > 0 and base_cost > 0 and spp > 0:
            # Базовая стоимость из анализа индексируется городом поквартально —
            # множитель у константы _GLAVAPU_VRI_BASE_INDEXATION вместе с датой.
            vri_msk = round(1.8964 * spp * rent_coeff * base_cost
                            * _GLAVAPU_VRI_BASE_INDEXATION / 1.00001 / 1e6, 3)
        mm = None
        if k1 > 0 and k2 > 0 and apartments > 0:
            # Это ЗЕРКАЛО калькулятора, а не наш нормативный расчёт: строка
            # выведена из двух его выгрузок и обязана отдавать то же, что отдал
            # бы он. Наш ответ по 2118-ПП живёт в `tep_derived_norms` и
            # `recalculate_from_glavapu_baseline` — он про наши метры и про
            # закон, а этот про нормативный ТЭП города. Приводить их к одному
            # числу нельзя: тогда фолбэк перестанет заменять калькулятор.
            # Постоянные — пункт 1 приложения 5 к 945-ПП в ред. 2118-ПП:
            # S / (33 × 2,1) × 0,8 вверх, без К1. Сходится со всеми тремя
            # выгрузками: 144 и 161 (16.08.2026), 2 902 (Нагатино 06.10.2026);
            # прежняя строка «НП жилых / 90 × К1» на Нагатино давала 2 901.
            mm_permanent = moscow_permanent_parking_2118(apartments)
            mm_guest = math.ceil(mm_permanent / 10.0)
            mm_onsite = math.ceil(commerce_np / 90.0 * k1 * k2)
            mm = {
                "permanent": mm_permanent,
                "guest": mm_guest,
                "onsite": mm_onsite,
                "short_mkd": math.ceil(apartments / 22100.0),
                "short_nzh": min(4, math.ceil(commerce_np / 450.0)),
            }
        rows = _glavapu_rows({
            "1": fmt(area, 3),
            # Плотность — как печатает калькулятор: без хвостовых нулей
            # («23,1», «20,79», «31,5»).
            "2": _ru_trim(density / 1000, 3),
            "3": _ru_trim(density * 0.9 / 1000, 2),
            "4": fmt(population, 0),
            "5": fmt(units, 0),
            "6": fmt(spp / 1000, 3),
            "7": fmt(spp / 1000, 3),
            "7.1": fmt(apartments_gns / 1000, 3),
            "7.2": fmt(commerce_gns / 1000, 3),
            "9": fmt(spp * 0.9 / 1000, 3),
            "9.1": fmt(spp * 0.9 / 1000, 3),
            "9.1.1": fmt(apartments_gns * 0.9 / 1000, 3),
            "9.1.2": fmt(commerce_gns * 0.9 / 1000, 3),
            "10": fmt(apartments / 1000, 3),
            "11": fmt(commerce_gns * 0.9 / 1000, 3),
            # Социалка компенсацией: участки не выделяются, вся территория —
            # жилая, как в эталоне («0,651 (100,0%)»).
            "12": f"{fmt(area, 3)} (100,0%)",
            "12.1": f"{fmt(area, 3)} (100,0%)",
            "12.2": "0 (0,0%)",
            "13": "0 (0,0%)",
            "14": "0 (0,0%)",
            "15": fmt(density * 0.9 / 1000, 2),
            "16": "0,00",
            "17": "0,00",
            "30": fmt(dou, 0),
            "31": fmt(school, 0),
            "32": fmt(clinic, 0),
            "33": fmt(clinic_adult, 0),
            "34": fmt(clinic_child, 0),
            "35": fmt(per_k(0.097, 4), 4),
            "36": fmt(per_k(0.8, 3), 3),
            "36.1": fmt(per_k(0.32, 3), 3),
            "36.2": fmt(per_k(0.48, 3), 3),
            "37": fmt(per_k(0.27, 3), 3),
            "38": fmt(per_k(0.1, 3), 3),
            "39": fmt(per_k(0.12, 3), 3),
            "40": fmt(per_k(0.15, 3), 3),
            "41": fmt(per_k(0.09, 3), 3),
            "#Расчёт компенсации за социальные объекты:":
                fmt(comp_dou + comp_school + comp_clinic, 3),
            "54": fmt(comp_dou, 3),
            "55": fmt(comp_school, 3),
            "56": fmt(comp_clinic, 3),
            "57": fmt(per_k(5.0, 4) / 10, 4),
            "58": fmt(per_k(0.5, 4) / 10, 4),
            "59": fmt(math.ceil(population * 0.1 / 10000 * 10 ** 4) / 10 ** 4, 4),
            "60": fmt(math.ceil(population * 0.7 / 10000 * 10 ** 4) / 10 ** 4, 4),
        } | ({} if not mm else {
            "42": fmt(mm["permanent"] + mm["guest"] + mm["onsite"], 0),
            "42.1": fmt(mm["permanent"], 0),
            "42.2": fmt(mm["guest"], 0),
            "42.3": fmt(mm["onsite"], 0),
            "43": fmt(mm["short_mkd"] + mm["short_nzh"], 0),
        }) | ({} if not vri_msk else {
            "#Расчёт стоимости смены ВРИ:": fmt(vri_msk, 3),
            "44": fmt(vri_msk, 3),
        }))
        extra_sheets = [
            ("МПТ", [
                ["№", "Наименования", "Единицы измерения", "Показатель"],
                ["1", "Встроенно-пристроенные помещения многоквартирного дома (2.1.1, 2.5, 2.6)",
                 "рабочие места", fmt(jobs, 0)],
            ]),
            ("Машино-места", [
                ["№", "Наименования", "Единицы измерения", "Всего",
                 "Приобъектные", "Постоянные", "Гостевые", "Кратковременные"],
                ["1", "Многоквартирный дом (2.1.1, 2.5, 2.6)", "машино-места",
                 fmt(mm["permanent"] + mm["guest"] + mm["short_mkd"], 0) if mm else "0",
                 "0",
                 fmt(mm["permanent"], 0) if mm else "0",
                 fmt(mm["guest"], 0) if mm else "0",
                 fmt(mm["short_mkd"], 0) if mm else "0"],
                ["2", "Встроенно-пристроенные помещения многоквартирного дома (2.1.1, 2.5, 2.6)",
                 "машино-места",
                 fmt(mm["onsite"] + mm["short_nzh"], 0) if mm else "0",
                 fmt(mm["onsite"], 0) if mm else "0",
                 "0", "0",
                 fmt(mm["short_nzh"], 0) if mm else "0"],
            ]),
        ]
        params = [
            ["Параметр", "Значение", "Ед.изм."],
            ["Машино-места", "", ""],
            ["К1 — доступность рельсового каркаса", coeff.get("rail") or "", "—"],
            ["К2 — деловая активность "
             + ("(внутри ТТК)" if bool(territory.get("inside_ttc")) else "(вне ТТК)"),
             coeff.get("business_inside_ttc" if bool(territory.get("inside_ttc"))
                       else "business_outside_ttc") or "", "—"],
            ["Социальные объекты", "", ""],
            ["Район", str(territory.get("district") or ""), "—"],
            ["Норматив ДОО", "44", "мест / 1000 жит."],
            ["Норматив школ", "90", "мест / 1000 жит."],
            ["Стоимость смены ВРИ", "", ""],
            ["Кадастровый квартал", str(territory.get("cadastral_quarter") or ""), "—"],
            ["Коэффициент аренды", coeff.get("rent") or "", "—"],
            ["Базовая стоимость МКД", coeff.get("base_cost_zh_high") or "", "руб/м²"],
            ["Методика", "Формулы калькулятора ГлавАПУ"
                         + ("" if vri_msk else "; плата за смену ВРИ — расчёт "
                                               "в мини-приложении")
                         + ("" if mm else "; машино-места — расчёт "
                                          "в мини-приложении"), "—"],
        ]
        card = (
            "<b>ВРИ и ТЭП · Москва</b>\n"
            f"Участок: <code>{html.escape(str(query)[:80])}</code>\n"
            f"• площадь — {fmt(area, 4)} га · район — "
            f"{html.escape(str(territory.get('district') or '—'))}\n"
            f"• СПП при плотности 35 — {fmt(spp / 1000, 1)} тыс. м² "
            f"· квартиры — {fmt(apartments, 0)} м²\n"
            f"• население — {fmt(population, 0)} чел. · квартир — {fmt(units, 0)}\n"
            f"• соцпотребность — ДОО {fmt(dou, 0)} мест, СОШ {fmt(school, 0)} мест, "
            f"поликлиники {fmt(clinic_adult, 0)}+{fmt(clinic_child, 0)} пос./см.\n"
            f"• <b>компенсация за соцобъекты — "
            f"{fmt(comp_dou + comp_school + comp_clinic, 1)} млн ₽</b> "
            "(ставки города, индексируются поквартально)\n"
            + (f"• паркинг — {fmt(mm['permanent'] + mm['guest'], 0)} м/м "
               f"(постоянные {fmt(mm['permanent'], 0)} + гостевые "
               f"{fmt(mm['guest'], 0)}) · приобъектные {fmt(mm['onsite'], 0)}\n"
               if mm else "")
            + (f"• <b>плата за смену ВРИ — {fmt(vri_msk, 1)} млн ₽</b> "
               "(собственность, без льгот и МАИП)\n"
               # Основание платы — тремя числами: расхождение с расчётом на
               # сайте раньше приходилось раскапывать перепиской, хотя вся
               # разница всегда в одном из этих трёх множителей.
               f"  <i>основание: СПП {fmt(spp, 0)} м² × коэфф. аренды "
               f"{coeff.get('rent') or '—'} × базовая стоимость "
               f"{fmt(_land_float(coeff.get('base_cost_zh_high')) or 0, 0)} ₽/м²"
               f" × 1,8964</i>\n" if vri_msk else "")
            + f"• К1 рельсовый — {coeff.get('rail') or '—'} · аренда — "
              f"{coeff.get('rent') or '—'}\n"
            + ("<i>Льготы по ВРИ (МПТ, передача жилья городу), аренда и МАИП "
               "— в мини-приложении: кнопка «Открыть и изменить расчёт».</i>\n"
               if mm and vri_msk else
               "<i>"
               + ("" if vri_msk else "Плату за смену ВРИ")
               + (" и машино-места" if not mm and not vri_msk else
                  ("Машино-места" if not mm else ""))
               + " считает калькулятор ГлавАПУ в мини-приложении: "
               "кнопка «Открыть и изменить расчёт».</i>\n")
            + ("<b>ВНИМАНИЕ:</b> серверные формулы разошлись со штатным "
               "калькулятором — методика ГлавАПУ могла измениться, сверьте "
               "расчёт на сайте.\n" if _GLAVAPU_FORMULA_DRIFT["items"] else "")
        )
        template_region = "Москва" + (
            f" · {territory.get('district')}" if territory.get("district") else "")
        # Соцнагрузка Москвы исполняется компенсацией — объектов в составе
        # проекта нет; плата за ВРИ уезжает посчитанной, если у квартала
        # известна базовая стоимость МКД.
        template_vri, template_comp = vri_msk, comp_dou + comp_school + comp_clinic
        template_products = {
            "apartments": {"gns": apartments_gns,
                           "total_area": apartments_gns * 0.9,
                           "saleable": apartments, "units": units},
            "ground_commercial": {"gns": commerce_gns, "total_area": commerce_np,
                                  "saleable": commerce_np},
        }
        if mm:
            template_products["underground_parking"] = {
                "units": mm["permanent"] + mm["guest"]}
    workbook = _build_glavapu_xlsx_from_rows(rows, params, extra_sheets)
    safe = re.sub(r"[^0-9A-Za-zА-Яа-я_-]+", "_", str(query))[:40] or "участок"
    today = date.today().isoformat()
    filename = f"ВРИ_ТЭП_{safe}_{today}.xlsx"
    result_payload = {"card": card, "file": workbook, "filename": filename}
    # Второй файл — заполненный шаблон DevelopAid: формат, который бот сам
    # предлагает заполнить и загрузить, — его правят и возвращают в расчёт.
    try:
        result_payload["template_file"] = _manual_tep_filled_template(
            str(query or district or "Участок").strip()[:80] or "Участок",
            template_region, area, template_vri, template_comp,
            template_products)
        result_payload["template_filename"] = f"ТЭП_DevelopAid_{safe}_{today}.xlsx"
    except Exception as exc:
        _TELEGRAM_RUNTIME["last_error"] = "Шаблон ВРИ/ТЭП: " + _error_location(exc)
    return result_payload


_GENPLAN_BASE_URL = "https://genplan.tech/calc/"
_GENPLAN_ASSET_DIR = Path(__file__).resolve().parent / "genplan_assets"
_GENPLAN_REQUIRED_ASSETS = {
    "index-B0jIwkVO.js",
    "rolldown-runtime-QTnfLwEv.js",
    "@map-C8A16ZpL.js",
    "@mui-Dy0laxMi.js",
    "@react-D7li0Nm9.js",
    "@mui-icons-BAApue2C.js",
    "@export-Dq7e_Rpm.js",
    "area-panel-D5vuUEJ8.js",
    "calc-BTtvF0Z6.js",
    "domain-CwUeX6RP.js",
    "@mui-charts-MKNt4QlC.js",
    "analysis-panel-Bp17MNRz.js",
    "map-page-CqxMR2K5.js",
    "@map-B2k4QVOw.css",
    "index-B8zlAO9I.css",
}


def _proxy_genplan(asset_path: str, request: Request) -> Response:
    """Serve the public calculator under DevelopAid's origin for browser-side automation."""
    clean_path = str(asset_path or "").lstrip("/")
    if any(part == ".." for part in clean_path.split("/")):
        raise HTTPException(status_code=400, detail="Некорректный путь калькулятора")
    if clean_path.startswith("assets/"):
        filename = clean_path.removeprefix("assets/")
        if "/" not in filename:
            local_path = _GENPLAN_ASSET_DIR / filename
            if local_path.is_file():
                media_type = "text/css" if filename.endswith(".css") else "application/javascript"
                return FileResponse(local_path, media_type=media_type, headers={"Cache-Control": "public, max-age=604800"})
    target = _GENPLAN_BASE_URL + urllib.parse.quote(clean_path, safe="/@._-")
    if request.url.query:
        target += "?" + request.url.query
    upstream_request = urllib.request.Request(
        target,
        headers={
            "Accept": request.headers.get("accept", "*/*"),
            "User-Agent": USER_AGENT,
        },
    )
    try:
        with urllib.request.urlopen(upstream_request, timeout=30) as upstream:
            body = upstream.read(20 * 1024 * 1024 + 1)
            content_type = upstream.headers.get("Content-Type") or "application/octet-stream"
    except urllib.error.HTTPError as exc:
        raise HTTPException(status_code=exc.code, detail="Ресурс калькулятора ГлавАПУ недоступен") from exc
    except (urllib.error.URLError, TimeoutError) as exc:
        raise HTTPException(status_code=502, detail="Калькулятор ГлавАПУ временно недоступен") from exc
    if len(body) > 20 * 1024 * 1024:
        raise HTTPException(status_code=502, detail="Ресурс калькулятора ГлавАПУ слишком большой")
    local_assets_ready = all((_GENPLAN_ASSET_DIR / name).is_file() for name in _GENPLAN_REQUIRED_ASSETS)
    if not clean_path and "text/html" in content_type.lower() and not local_assets_ready:
        html = body.decode("utf-8", errors="replace")
        # The calculator document stays on DevelopAid's origin, while its public static
        # modules load directly from genplan.tech. Their server allows CORS, and
        # this avoids relaying multi-megabyte bundles through Render.
        html = html.replace('"/calc/', '"https://genplan.tech/calc/')
        html = html.replace("'/calc/", "'https://genplan.tech/calc/")
        import_map = {
            "/calc/assets/rolldown-runtime-QTnfLwEv.js": "https://genplan.tech/calc/assets/rolldown-runtime-QTnfLwEv.js",
            "/calc/assets/@map-C8A16ZpL.js": "https://genplan.tech/calc/assets/@map-C8A16ZpL.js",
            "/calc/assets/@mui-Dy0laxMi.js": "https://genplan.tech/calc/assets/@mui-Dy0laxMi.js",
            "/calc/assets/@react-D7li0Nm9.js": "https://genplan.tech/calc/assets/@react-D7li0Nm9.js",
            "/calc/assets/@mui-icons-BAApue2C.js": "https://genplan.tech/calc/assets/@mui-icons-BAApue2C.js",
        }
        import_map_tag = '<script type="importmap">' + json.dumps({"imports": import_map}) + "</script>"
        html = html.replace('<script type="module"', import_map_tag + '<script type="module"', 1)
        body = html.encode("utf-8")
    cache_control = "public, max-age=86400" if clean_path else "no-store"
    return Response(body, media_type=content_type.split(";", 1)[0], headers={"Cache-Control": cache_control})


@app.get("/calc")
@app.get("/calc/")
def proxy_genplan_root(request: Request) -> Response:
    return _proxy_genplan("", request)


@app.get("/calc/{asset_path:path}")
def proxy_genplan_asset(asset_path: str, request: Request) -> Response:
    return _proxy_genplan(asset_path, request)


def _xlsx_xml_text(value: Any) -> str:
    text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", str(value if value is not None else ""))
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _xlsx_column_name(index: int) -> str:
    result = ""
    number = index + 1
    while number:
        number, remainder = divmod(number - 1, 26)
        result = chr(65 + remainder) + result
    return result


def _xlsx_inline_sheet(rows: list[list[Any]]) -> bytes:
    xml_rows: list[str] = []
    for row_index, row in enumerate(rows, 1):
        cells: list[str] = []
        for col_index, value in enumerate(row):
            if value is None or value == "":
                continue
            ref = f"{_xlsx_column_name(col_index)}{row_index}"
            cells.append(
                f'<c r="{ref}" t="inlineStr"><is><t>{_xlsx_xml_text(value)}</t></is></c>'
            )
        xml_rows.append(f'<row r="{row_index}">{"".join(cells)}</row>')
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f'<worksheet xmlns="{_XLSX_MAIN_NS}"><sheetData>{"".join(xml_rows)}</sheetData></worksheet>'
    ).encode("utf-8")


def _build_glavapu_xlsx_from_rows(rows: list[list[Any]], parameters: list[list[Any]],
                                  extra_sheets: list[tuple[str, list[list[Any]]]] | None = None) -> bytes:
    """Книга формата выгрузки калькулятора ГлавАПУ. Эталон ведёт четыре
    листа — ТЭП, МПТ, Машино-места, Параметры территории; extra_sheets
    вставляются между ТЭП и параметрами в переданном порядке."""
    sheets: list[tuple[str, list[list[Any]]]] = [("ТЭП", rows)]
    sheets.extend(extra_sheets or [])
    sheets.append(("Параметры территории", parameters))
    overrides = "\n".join(
        f'  <Override PartName="/xl/worksheets/sheet{i}.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
        for i in range(1, len(sheets) + 1))
    content_types = f'''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Default Extension="xml" ContentType="application/xml"/>
  <Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>
{overrides}
</Types>'''.encode("utf-8")
    package_rels = f'''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="{_XLSX_PKG_REL_NS}">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>
</Relationships>'''.encode("utf-8")
    sheet_tags = "".join(
        f'<sheet name="{html.escape(name, quote=True)}" sheetId="{i}" r:id="rId{i}"/>'
        for i, (name, _) in enumerate(sheets, 1))
    workbook = f'''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<workbook xmlns="{_XLSX_MAIN_NS}" xmlns:r="{_XLSX_REL_NS}">
  <sheets>{sheet_tags}</sheets>
</workbook>'''.encode("utf-8")
    rel_tags = "\n".join(
        f'  <Relationship Id="rId{i}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet{i}.xml"/>'
        for i in range(1, len(sheets) + 1))
    workbook_rels = f'''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="{_XLSX_PKG_REL_NS}">
{rel_tags}
</Relationships>'''.encode("utf-8")
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", content_types)
        archive.writestr("_rels/.rels", package_rels)
        archive.writestr("xl/workbook.xml", workbook)
        archive.writestr("xl/_rels/workbook.xml.rels", workbook_rels)
        for index, (_, sheet_rows) in enumerate(sheets, 1):
            archive.writestr(f"xl/worksheets/sheet{index}.xml", _xlsx_inline_sheet(sheet_rows))
    return out.getvalue()
