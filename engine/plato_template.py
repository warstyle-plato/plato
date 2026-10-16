"""Выгрузка в шаблон ПЛАТО: templates/PLATO_template.xlsx.

Заполнение шаблона, консолидатор, новая книга (build_plato_model_v2) и
сверка рассчитанной книги с движком (audit_plato_workbook).

Не самостоятельный модуль. `main_legacy.py` выполняет этот файл в своём
пространстве имён на том месте, где этот код стоял раньше
(`_engine_part("plato_template")`), поэтому здесь видны все имена движка,
а подмены `core.<имя>` из `main.py` и тестов действуют и на этот код.
Отдельно не импортировать: второй импорт поднял бы вторую копию движка.
"""
# ruff: noqa

# ---------------------------------------------------------------------------
# Выгрузка в шаблон ПЛАТО: заполняем только листы-вводные, остальное считает
# сам шаблон. В templates/PLATO_template.xlsx около ста тысяч формул на 27
# листах, поэтому трогать их нельзя — иначе рушится вся модель.
# ---------------------------------------------------------------------------

_PLATO_TEMPLATE_PATH = Path(__file__).resolve().parent / "templates" / "PLATO_template.xlsx"

# Лист «Вводные»: подпись параметра -> ключ модели и способ пересчёта.
#   number — как есть, pct — проценты в доли, date — дата, bool — Да/Нет.
_PLATO_INPUT_MAP: list[tuple[str, str, str]] = [
    ("Стоимость покупки / цена входа", "purchase_price_mln", "number"),
    ("Начало проекта", "project_start", "date"),
    ("Срок строительства", "construction_months", "number"),
    ("Стартовая цена квартир", "apartment_price_th", "number"),
    ("Стартовая цена коммерции", "commercial_price_th", "number"),
    ("Цена машино-места", "parking_price_th", "number"),
    ("Цена кладовой", "storage_price_th", "number"),
    ("Доля продаж до РВЭ", "share_before_rve_pct", "pct"),
    ("Смещение темпа продаж к поздним месяцам", "pace_adjustment_pct", "pct"),
    ("Инфляция после РВЭ", "inflation_after_rve_pct", "pct"),
    ("Сезонное снижение темпа", "seasonal_reduction_pct", "pct"),
    ("Рост цены — этап 1", "growth_stage1_pct", "pct"),
    ("Рост цены — этап 2", "growth_stage2_pct", "pct"),
    ("Рост цены — этап 3", "growth_stage3_pct", "pct"),
    ("Рост цены — этап 4", "growth_stage4_pct", "pct"),
    ("ИРД и согласования", "ird_th_per_sqm", "number"),
    ("Проектирование стадии П", "design_p_th_per_sqm", "number"),
    ("Проектирование стадии РД", "design_rd_th_per_sqm", "number"),
    ("Подготовительные работы", "preparation_th_per_sqm", "number"),
    ("Основное строительство ЖК", "main_above_th_per_sqm", "number"),
    ("Наружные инженерные сети", "utilities_th_per_sqm", "number"),
    ("Благоустройство — норматив площади на человека", "landscaping_area_per_person_sqm", "number"),
    ("Благоустройство — площадь территории (0 — по нормативу)", "landscaping_area_sqm", "number"),
    ("Благоустройство", "landscaping_th_per_sqm", "number"),
    ("Сдача и ввод", "commissioning_th_per_sqm", "number"),
    ("Содержание стройплощадки", "site_maintenance_th_per_sqm", "number"),
    ("Вознаграждение генподрядчика", "gc_fee_pct", "pct"),
    ("Резерв", "reserve_pct", "pct"),
    ("Управление проектом", "project_management_pct", "pct"),
    ("Маркетинг", "marketing_pct", "pct"),
    ("Расходы на продажи", "selling_pct", "pct"),
    ("Налог на прибыль", "profit_tax_pct", "pct"),
    ("НДС", "vat_pct", "pct"),
    ("Спред БРИДЖ", "bridge_spread_pp", "pct"),
    ("Спред капитализации БРИДЖ", "bridge_cap_spread_pp", "pct"),
    ("Спред ПФ", "pf_spread_pp", "pct"),
    ("Специальная ставка ПФ", "pf_special_pct", "pct"),
    ("Плата за лимит", "limit_fee_pct", "pct"),
    ("Плата за резервирование", "reservation_fee_pct", "pct"),
    ("Ставка дисконтирования", "discount_rate_pct", "pct"),
    ("Срок ИРД до РнС", "ird_months", "number"),
    ("Лаг старта продаж после РнС", "sales_lag_months", "number"),
    ("Лаг погашения БРИДЖ после РнС", "bridge_repay_lag_months", "number"),
    ("Остаточные продажи после РВЭ", "residual_sales_months", "number"),
    # Социальная нагрузка
    ("Количество мест", "kindergarten_places", "number"),          # блок ДОУ
    ("Мощность", "clinic_capacity", "number"),
    ("Срок строительства", "kindergarten_months", "number"),        # уточняется блоком
    # Отдельно стоящие объекты
    ("Продаваемая площадь", "offices_saleable_sqm", "number"),
    ("Количество машино-мест", "above_parking_spaces", "number"),
]

# Поля, где шаблон считает своё вместо нашего и потому обязан уступить.
# Себестоимость соцобъектов и мощность поликлиники он тянет с листа
# «Расчет ВРИ (ТЭП)» — остаток прежней методики, расходящийся с движком.
_PLATO_OVERRIDE_TEMPLATE_FORMULA = frozenset({
    "kindergarten_cost_mln_per_place",
    "school_cost_mln_per_place",
    "clinic_cost_mln_per_unit",
    "clinic_capacity",
})

# Блочные параметры: (блок в колонке A, подпись в B) -> ключ и тип.
_PLATO_BLOCK_MAP: list[tuple[str, str, str, str]] = [
    ("ДОУ", "Количество мест", "kindergarten_places", "number"),
    ("ДОУ", "Срок строительства", "kindergarten_months", "number"),
    ("СОШ", "Количество мест", "school_places", "number"),
    ("СОШ", "Срок строительства", "school_months", "number"),
    ("Поликлиника", "Мощность", "clinic_capacity", "number"),
    ("Поликлиника", "Срок строительства", "clinic_months", "number"),
    # Себестоимость соцобъектов в карту не входила, и в ячейках оставалось то,
    # что лежало в шаблоне: 0,0097 млн ₽ за место вместо 2,75. Социальная
    # нагрузка выходила 0,6 млн ₽ вместо 193,2 млн ₽, а прибыль и LLCR — выше
    # настоящих. Движок эти же поля читает, значит и шаблон обязан их получать.
    ("ДОУ", "Себестоимость одного места", "kindergarten_cost_mln_per_place", "number"),
    ("СОШ", "Себестоимость одного места", "school_cost_mln_per_place", "number"),
    ("Поликлиника", "Себестоимость единицы мощности", "clinic_cost_mln_per_unit", "number"),
    ("МФОЦ / офисы", "Общая площадь (GBA)", "offices_gba_sqm", "number"),
    ("МФОЦ / офисы", "Продаваемая площадь", "offices_saleable_sqm", "number"),
    ("МФОЦ / офисы", "Срок строительства", "offices_months", "number"),
    ("МФОЦ / офисы", "Себестоимость строительства", "offices_cost_th_per_sqm", "number"),
    ("МФОЦ / офисы", "Стартовая цена", "offices_price_th_per_sqm", "number"),
    ("МФОЦ / офисы", "Доля продаж до РВЭ", "offices_share_before_rve_pct", "pct"),
    ("МФОЦ / офисы", "Остаточные продажи после РВЭ", "offices_residual_months", "number"),
    ("МФОЦ / офисы", "Объект включен", "offices_enabled", "bool"),
    ("ТЦ / коммерция", "Общая площадь (GBA)", "retail_gba_sqm", "number"),
    ("ТЦ / коммерция", "Продаваемая площадь", "retail_saleable_sqm", "number"),
    ("ТЦ / коммерция", "Срок строительства", "retail_months", "number"),
    ("ТЦ / коммерция", "Себестоимость строительства", "retail_cost_th_per_sqm", "number"),
    ("ТЦ / коммерция", "Стартовая цена", "retail_price_th_per_sqm", "number"),
    ("ТЦ / коммерция", "Доля продаж до РВЭ", "retail_share_before_rve_pct", "pct"),
    ("ТЦ / коммерция", "Остаточные продажи после РВЭ", "retail_residual_months", "number"),
    ("ТЦ / коммерция", "Объект включен", "retail_enabled", "bool"),
    ("Наземный парки", "Количество машино-мест", "above_parking_spaces", "number"),
    ("Наземный парки", "Себестоимость одного места", "above_parking_cost_mln_per_space", "number"),
    ("Наземный парки", "Срок строительства", "above_parking_months", "number"),
    ("Наземный парки", "Стартовая цена места", "above_parking_price_mln_per_space", "number"),
    ("Наземный парки", "Доля продаж до РВЭ", "above_parking_share_before_rve_pct", "pct"),
    ("Наземный парки", "Остаточные продажи после РВЭ", "above_parking_residual_months", "number"),
    ("Наземный парки", "Объект включен", "above_parking_enabled", "bool"),
    # У отдельно стоящих объектов рост цены и календарь задаются напрямую —
    # в отличие от жилья, где шаблон выводит месячный рост из целевого. Без
    # этих строк объекты считались по умолчанию шаблона, а не по модели.
    ("МФОЦ / офисы", "Ежемесячный рост цены до РВЭ", "offices_growth_pre_pct", "pct"),
    ("МФОЦ / офисы", "Ежемесячный рост цены после РВЭ", "offices_growth_post_pct", "pct"),
    ("МФОЦ / офисы", "Начало строительства", "offices_start", "date"),
    ("МФОЦ / офисы", "Старт продаж", "offices_sales_start", "date"),
    ("ТЦ / коммерция", "Ежемесячный рост цены до РВЭ", "retail_growth_pre_pct", "pct"),
    ("ТЦ / коммерция", "Ежемесячный рост цены после РВЭ", "retail_growth_post_pct", "pct"),
    ("ТЦ / коммерция", "Начало строительства", "retail_start", "date"),
    ("ТЦ / коммерция", "Старт продаж", "retail_sales_start", "date"),
    ("Наземный парки", "Ежемесячный рост цены до РВЭ", "above_parking_growth_pre_pct", "pct"),
    ("Наземный парки", "Ежемесячный рост цены после РВЭ", "above_parking_growth_post_pct", "pct"),
    ("Наземный парки", "Начало строительства", "above_parking_start", "date"),
    ("Наземный парки", "Старт продаж", "above_parking_sales_start", "date"),
]

# Лист «Расчет ВРИ (ТЭП)»: подпись в колонке B -> что кладём в колонку D.
_PLATO_TEP_ROWS: list[tuple[str, str]] = [
    ("Количество квартир", "apartments.units"),
    ("СПП жилая", "apartments.gns"),
    ("СПП нежилой части жилых зданий", "ground_commercial.gns"),
    ("НП жилая", "apartments.total_area"),
    ("НП нежилой части жилых зданий", "ground_commercial.total_area"),
    ("Площадь квартир", "apartments.saleable"),
    ("Нежилая наземная площадь (ННП)", "ground_commercial.saleable"),
    # ТЭП!I33 шаблона складывает постоянные и гостевые парковки. Значит в
    # «постоянные» идёт не всё число мест, а число за вычетом гостевых —
    # иначе гостевые считаются дважды. Обе строки пишутся явно: оставленное
    # в шаблоне чужое значение попало бы в расчёт как своё.
    ("Постоянные парковки", "underground_parking.permanent_units"),
    ("Гостевые парковки", "underground_parking.guest_units"),
]


def _plato_normalize(text: Any) -> str:
    return re.sub(r"\s+", " ", str(text or "").replace("ё", "е").replace("—", "-")).strip().lower()


def _plato_value(kind: str, value: Any) -> Any:
    if kind == "date":
        text = _land_text(value)
        try:
            return datetime.strptime(text[:10], "%Y-%m-%d")
        except ValueError:
            return None
    if kind == "bool":
        return "Да" if bool(value) else "Нет"
    number = _land_float(value)
    if number is None:
        return None
    return number / 100.0 if kind == "pct" else number


def _plato_tep_value(tep: dict[str, dict[str, Any]], path: str) -> float | None:
    product, field = path.split(".", 1)
    values = tep.get(product) or {}
    if product == "underground_parking" and field in ("permanent_units", "guest_units"):
        # Гостевые места модель хранит рядом с общим числом, а при ручном вводе
        # выводит из норматива. Книге нужны обе половины по отдельности.
        if not values:
            return 0.0
        guest = float(underground_guest_spaces(values))
        return guest if field == "guest_units" else underground_saleable_spaces(values)
    if field not in values:
        # Показателя нет в модели — значит в шаблоне на его месте данные чужого
        # проекта, и оставлять их нельзя: они попадут в расчёт как свои.
        return 0.0
    return _land_float(values.get(field))


# Лист «ЗУ» шаблона — не справка, а действующий блок: cf_1 ссылается на него
# 357 раз. В нём уже собраны рассрочка ВРИ помесячно (строка 64), окончательный
# платёж (65) и проценты на остаток по ключевой плюс спред (66). Не заполнены
# только вводные, а вместо них в шаблоне остались данные чужого проекта:
# кадастровый номер на Лётной, плановая кадастровая стоимость 1,51 млрд и даты
# 2024 года. Мы их вычищаем и подставляем свои.
_PLATO_LAND_BLOCKS = ((22, 31), (40, 49))
_PLATO_LAND_ROWS = (
    "Кад.№", "Адрес", "Площадь, кв.м", "ВРИ", "УПКС жилье",
    "Кадастровая стоимость", "План. кад.стоимость, руб.",
    "Ставка арендной платы, %", "Смена ВРИ, руб.", "Дата первого платежа:",
)


def _plato_land_parcel(inputs: dict[str, Any]) -> dict[str, Any]:
    """Сведения об участке из последнего поиска ЕГРН или расчёта Подмосковья."""
    lookup = (inputs.get("_land_lookup") or {}).get("results") or []
    parcel = next((item for item in lookup if item.get("kind") == "land"), None)
    if parcel:
        return parcel
    parcels = ((inputs.get("_mo_calc") or {}).get("vri") or {}).get("parcels") or []
    return parcels[0] if parcels else {}


def _plato_drop_external_links(data: bytes) -> bytes:
    """Убрать из книги ссылку на отсутствующий внешний файл.

    В шаблоне живёт ссылка на лист «ОПТИМУМ» с пометкой xlPathMissing: файла,
    на который она указывает, нет. Excel при открытии спрашивает про обновление
    связей, а часть программ такую книгу просто не грузит. Расчёт от неё не
    зависит — ни одна формула наружу не смотрит, — поэтому связь удаляется
    целиком: сама часть, ссылка из книги, отношение и запись типа.
    """
    source = zipfile.ZipFile(io.BytesIO(data))
    if not any("externalLink" in name for name in source.namelist()):
        return data
    buffer = io.BytesIO()
    result = zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED)
    for item in source.infolist():
        if "externalLink" in item.filename:
            continue
        payload = source.read(item.filename)
        if item.filename == "xl/workbook.xml":
            payload = re.sub(rb"<externalReferences>.*?</externalReferences>", b"", payload, flags=re.S)
        elif item.filename == "xl/_rels/workbook.xml.rels":
            payload = re.sub(rb"<Relationship[^>]*externalLink[^>]*/>", b"", payload)
        elif item.filename == "[Content_Types].xml":
            payload = re.sub(rb"<Override[^>]*externalLink[^>]*/>", b"", payload)
        result.writestr(item, payload)
    result.close()
    return buffer.getvalue()


def _plato_merge_management_and_smr(
    sheet: Any, rows_by_label: dict[str, list[int]],
    inputs: dict[str, Any], tep: dict[str, dict[str, Any]],
    filled: list[dict[str, Any]],
) -> None:
    """Слить техзаказчика с управлением, а подземные СМР — с наземными.

    Книга ведёт одну строку «Управление проектом» и одну «Основное
    строительство ЖК». Движок считает управление, технический заказчик и
    авторский надзор порознь, а СМР — отдельно по наземной и подземной части.
    Пишется в колонки сценариев D–F. Колонка G — переключатель: там формула
    INDEX, выбирающая сценарий, и запись значением её убивает.

    Разложить их в книге некуда, поэтому передаётся то же самое одним числом:
    процент, дающий сумму трёх статей на базе книги, и ставка, дающая сумму
    обеих частей на ядре МКД — на той базе, на которую СМР и начислен.
    """
    result = calculate(CalcRequest(inputs=dict(inputs), tep=dict(tep), rates=[]))
    capex = result.get("capex") or {}

    def amount(name: str) -> float:
        value = capex.get(name)
        return float(value) if isinstance(value, (int, float)) else 0.0

    # База книги под процент управления — строительные статьи плюс соцобъекты:
    # ровно то, что она показывает строками «Расходы на строительство» и
    # «Строительство соцобъектов».
    base = sum(amount(name) for name in (
        "ird", "design_p", "design_rd", "preparation", "main_above", "main_under",
        "gc_fee", "utilities", "landscaping", "commissioning", "site_maintenance",
        "reserve", "social",
    ))
    management = amount("project_management") + amount("technical_supervision") + amount("author_supervision")
    if base > 0 and management > 0:
        rows = rows_by_label.get(_plato_normalize("Управление проектом")) or []
        if rows:
            share = round(management / base, 6)
            for column in range(4, 7):
                sheet.cell(row=rows[0], column=column).value = share
            filled.append({"sheet": "Вводные", "row": rows[0],
                           "label": "Управление проектом · с техзаказчиком и надзором",
                           "value": share})

    # Делитель берут оттуда же, откуда числитель. СМР ядра посчитан на
    # `core_above_gns` и `core_under_gns`; ГНС ВСЕХ строк ТЭП сюда не годится —
    # там же садик, школа, офисы и ОСЗ, которых эта статья не строит. Пока у
    # них у всех ГНС стоял нулём, две суммы совпадали и ошибки не было видно:
    # с включёнными офисами ставка выходила 170,9 при обеих заданных 190, то
    # есть занижалась ровно на чужие метры. Вылезло это, когда у соцобъекта
    # умолчания ГНС перестал быть нулём.
    tep_totals = result.get("tep") or {}
    gns = (float(tep_totals.get("core_above_gns") or 0.0)
           + float(tep_totals.get("core_under_gns") or 0.0))
    smr = amount("main_above") + amount("main_under")
    if gns > 0 and smr > 0:
        rows = rows_by_label.get(_plato_normalize("Основное строительство ЖК")) or []
        if rows:
            rate = round(smr / gns / 1000.0, 6)
            for column in range(4, 7):
                sheet.cell(row=rows[0], column=column).value = rate
            filled.append({"sheet": "Вводные", "row": rows[0],
                           "label": "Основное строительство · с подземной частью",
                           "value": rate})


def _plato_fill_land_sheet(
    workbook: Any, inputs: dict[str, Any], filled: list[dict[str, Any]],
    tep: dict[str, Any] | None = None,
) -> None:
    if "ЗУ" not in workbook.sheetnames:
        return
    sheet = workbook["ЗУ"]

    def put(row: int, value: Any, label: str) -> None:
        sheet.cell(row=row, column=3).value = value
        filled.append({"sheet": "ЗУ", "row": row, "label": label, "value": value})

    parcel = _plato_land_parcel(inputs)
    first_block = True
    for start, end in _PLATO_LAND_BLOCKS:
        labels = {
            _plato_normalize(sheet.cell(row=row, column=2).value): row
            for row in range(start, end + 1)
        }
        for name in _PLATO_LAND_ROWS:
            row = labels.get(_plato_normalize(name))
            if row:
                sheet.cell(row=row, column=3).value = None
        if not first_block:
            continue
        first_block = False
        for name, value in (
            ("Кад.№", _land_text(parcel.get("cadastral_number"))),
            ("Адрес", _land_text(parcel.get("address"))),
            ("Площадь, кв.м", _land_float(parcel.get("area_sqm"))),
            ("ВРИ", _land_text(parcel.get("permitted_use"))),
            ("Кадастровая стоимость", _land_float(parcel.get("cadastral_value_rub"))),
        ):
            row = labels.get(_plato_normalize(name))
            if row and value not in (None, ""):
                put(row, value, name)

    # Условия рассрочки ВРИ: доля к оплате после льготы, спред и окно платежей.
    permit = add_months(d(inputs.get("project_start", "2027-01-01")),
                        max(IRD_MONTHS_MIN, int(n(inputs, "ird_months", 18))))
    gross = n(inputs, "land_rights_cost_mln") * 1_000_000
    relief, net = vri_relief(inputs, gross, tep)
    schedule = build_vri_schedule(inputs, net, permit)
    labels = {
        _plato_normalize(sheet.cell(row=row, column=2).value): row
        for row in range(56, 70)
    }
    share = (net / gross) if gross else 1.0
    row = labels.get(_plato_normalize("Доля оплаты"))
    if row:
        put(row, round(share, 6), "Доля оплаты по ВРИ")
    row = labels.get(_plato_normalize("%% за рассрочку"))
    if row:
        put(row, round(n(inputs, "vri_interest_spread_pp", 3.0) / 100.0, 6), "Спред по рассрочке ВРИ")

    rows = schedule.get("rows") or []
    if not rows and gross > 0:
        # Сумма ВРИ есть, а графика нет — так бывает, когда стоимость введена
        # руками, а расчёт ВРИ выключен. Уйти отсюда молча нельзя: в книге
        # останутся её собственные формулы — первый платёж в дату РнС и
        # рассрочка на 72 месяца равными долями. Движок же платит по дате
        # обязательства, по умолчанию за месяц до РнС, то есть до открытия ПФ,
        # и платёж несёт БРИДЖ. Расхождение выходит не в графике, а в объёме
        # долга: книга выбирала ПФ на 1,2 млрд ₽ меньше расчёта.
        obligation, _basis, _estimated = vri_obligation_date(inputs, permit)
        rows = [{"date": obligation.isoformat(), "amount": net}]
    if not rows:
        return
    first = d(rows[0]["date"])
    last = d(rows[-1]["date"])
    row = labels.get(_plato_normalize("Первый"))
    if row:
        put(row, datetime(first.year, first.month, first.day), "Первый платёж ВРИ")
    row = labels.get(_plato_normalize("Последний"))
    if row:
        # В шаблоне «Последний» по умолчанию равен «Первому», поэтому окно
        # платежей пустое и вся плата падает в первый месяц.
        put(row, datetime(last.year, last.month, last.day), "Последний платёж ВРИ")
    row = labels.get(_plato_normalize("В месяц"))
    if row:
        months = max(1, months_between(first, last))
        sheet.cell(row=row, column=3).value = f"=C{row - 4}/{months}"
        filled.append({"sheet": "ЗУ", "row": row,
                       "label": "Ежемесячный платёж ВРИ", "value": f"1/{months}"})
    _plato_repair_vri_columns(sheet, labels, filled)


def _plato_repair_vri_columns(
    sheet: Any, labels: dict[str, int], filled: list[dict[str, Any]]
) -> None:
    """Достраивает первые две колонки рассрочки ВРИ.

    В шаблоне окончательный платёж в колонке D задан статикой
    ='Расчет ВРИ (ТЭП)'!D73 — плата падает в первый месяц модели независимо
    от дат, а E65 пустая. Проценты на остаток в D66 и E66 тоже отсутствуют,
    поэтому первые два месяца их не начисляют. С третьей колонки формулы
    правильные — повторяем их для первых двух.
    """
    final_row = labels.get(_plato_normalize("Окончательный платеж"))
    interest_row = labels.get(_plato_normalize("Плата за рассрочку"))
    monthly_row = labels.get(_plato_normalize("В месяц"))
    total_row = labels.get(_plato_normalize("Плата за ВРИ итого"))
    if not (final_row and interest_row and monthly_row and total_row):
        return
    fixes = {
        f"D{final_row}": f"=IF(D19=$C${final_row - 2},$C${total_row},0)",
        f"E{final_row}": f"=IF(E19=$C${final_row - 2},$C${total_row}-SUM($D{monthly_row}:D{monthly_row}),0)",
        f"D{interest_row}": f"=IF(D19>=$C${final_row - 3},$C${total_row}*D{interest_row - 5}/12,0)",
        f"E{interest_row}": (
            f"=IF(E19>=$C${final_row - 3},($C${total_row}-SUM($D{monthly_row}:D{final_row}))"
            f"*E{interest_row - 5}/12,0)"
        ),
    }
    for reference, formula in fixes.items():
        sheet[reference] = formula
    filled.append({"sheet": "ЗУ", "row": final_row,
                   "label": "Первые месяцы рассрочки ВРИ", "value": "формулы достроены"})


from openpyxl.utils import get_column_letter, column_index_from_string  # noqa: E402
from openpyxl.formula.translate import Translator  # noqa: E402


def _plato_fix_social_capex_links(
    workbook: Any, filled: list[dict[str, Any]], missing: list[str],
) -> None:
    """CAPEX соцобъектов при денежной компенсации ссылался на количество мест.

    Формулы G6:G8 листа «ОБЪЕКТЫ КРТ» брали 'Расчет ВРИ (ТЭП)'!D54:D56 и делили
    на тысячу. Но в строках 54–56 лежит мощность — 15 мест, 10, 5, — а деньги
    ниже, в 84–86. Вместо 188,4 млн ₽ по ДОО выходило 0,015: ошибка ссылки на
    строку, не методики. Подписи там повторяются дважды, и промахнуться легко —
    на этом же месте я уже спотыкался, записывая компенсацию.
    """
    if "ОБЪЕКТЫ КРТ" not in workbook.sheetnames or "Расчет ВРИ (ТЭП)" not in workbook.sheetnames:
        missing.append("ОБЪЕКТЫ КРТ · ссылки на компенсацию")
        return
    tep = workbook["Расчет ВРИ (ТЭП)"]
    start = next(
        (row for row in range(1, tep.max_row + 1)
         if "компенсац" in _plato_normalize(tep.cell(row=row, column=2).value)),
        None,
    )
    if not start:
        missing.append("ОБЪЕКТЫ КРТ · ссылки на компенсацию")
        return
    money = {}
    for row in range(start + 1, min(start + 8, tep.max_row + 1)):
        label = _plato_normalize(tep.cell(row=row, column=2).value)
        if label in ("доо", "школа", "поликлиника"):
            money[label] = row

    sheet = workbook["ОБЪЕКТЫ КРТ"]
    changed = 0
    for cell_row, label in ((6, "доо"), (7, "школа"), (8, "поликлиника")):
        target = money.get(label)
        cell = sheet.cell(row=cell_row, column=7)
        if not target or not isinstance(cell.value, str):
            continue
        # Меняем только ссылку и убираем перевод в миллионы: в строках 84–86
        # деньги уже в миллионах, делить их на тысячу незачем.
        fixed = re.sub(
            r"'Расчет ВРИ \(ТЭП\)'!\$?D\d+\s*/\s*1000",
            f"'Расчет ВРИ (ТЭП)'!$D${target}",
            cell.value,
        )
        if fixed == cell.value:
            continue
        cell.value = fixed
        changed += 1
    if not changed:
        missing.append("ОБЪЕКТЫ КРТ · ссылки на компенсацию")
        return
    filled.append({"sheet": "ОБЪЕКТЫ КРТ", "row": 6,
                   "label": "CAPEX соцобъектов · ссылка на деньги, а не на места",
                   "value": changed})


def _plato_backward_range(formula: str) -> bool:
    """Есть ли в формуле диапазон, у которого конец левее начала."""
    for start, end in re.findall(r"\$?([A-Z]{1,2})\d+:\$?([A-Z]{1,2})\d+", formula):
        if column_index_from_string(end) < column_index_from_string(start):
            return True
    return False


def _plato_apply_pf_cashflow(
    workbook: Any, filled: list[dict[str, Any]], missing: list[str],
) -> None:
    """Живая формула погашения ПФ вместо выборки из листа «факт».

    Строка 61 листа «КРЕДИТЫ» брала погашение из «факта» — фактических данных
    действующего проекта. На инвестиционном анализе их нет, лист пуст, и долг
    только накапливался: 1,83 → 7,94 млрд ₽ за двадцать четыре месяца, ни разу
    не уменьшившись, при том что доступных средств к концу набиралось 9,56.
    Отсюда и расхождение с расчётом по выборке ПФ и процентам.

    Формула остаётся формулой: аналитик меняет цены или сроки — книга
    пересчитывает погашение сама. Гасим тем, что накоплено к прошлому месяцу
    плюс поступления текущего, но не больше остатка долга. Ссылка на
    предыдущую колонку, а не на строку 51 того же месяца, — иначе выйдет
    круговая ссылка: строка 51 сама зависит от погашения.
    """
    if "КРЕДИТЫ" not in workbook.sheetnames:
        missing.append("КРЕДИТЫ · движение ПФ")
        return
    sheet = workbook["КРЕДИТЫ"]
    total = 0
    for row, label in ((60, "Получение ПФ"), (61, "Погашение ПФ")):
        stale = [c for c in range(2, sheet.max_column + 1)
                 if isinstance(sheet.cell(row=row, column=c).value, str)
                 and "факт!" in sheet.cell(row=row, column=c).value]
        if not stale:
            continue
        donor_column = next(
            (c for c in range(2, sheet.max_column + 1)
             if isinstance(sheet.cell(row=row, column=c).value, str)
             and sheet.cell(row=row, column=c).value.startswith("=")
             and "факт!" not in sheet.cell(row=row, column=c).value
             and "SUM(" != sheet.cell(row=row, column=c).value[1:5]
             and c > max(stale)),
            None,
        )
        if not donor_column:
            missing.append(f"КРЕДИТЫ · {label.lower()}")
            continue
        donor = sheet.cell(row=row, column=donor_column).value
        origin = f"{get_column_letter(donor_column)}{row}"
        for column in stale:
            target = f"{get_column_letter(column)}{row}"
            moved = Translator(donor, origin=origin).translate_formula(target)
            # Накопительные диапазоны в первой колонке вырождаются
            # (SUM($S61:R61)): Excel нормализует их и получает ссылку на саму
            # себя. Считать там нечего — ни выбирать, ни гасить ещё не из чего.
            if _plato_backward_range(moved):
                sheet.cell(row=row, column=column).value = 0
            else:
                sheet.cell(row=row, column=column).value = moved
            total += 1
        filled.append({"sheet": "КРЕДИТЫ", "row": row,
                       "label": f"{label} · формула вместо листа «факт»",
                       "value": len(stale)})
    if not total:
        missing.append("КРЕДИТЫ · движение ПФ")


def _ladder_input_block(ws_in, steps: list[tuple[float, float]],
                        where: str) -> list[tuple[str, str]]:
    """Блок ступеней внизу листа «Вводные»: ячейки, на которые смотрит формула.

    Низ листа свободен и никем не адресуется; вставка строк в середину для
    openpyxl закрыта — он не переписывает формулы при сдвиге. Возвращает пары
    ссылок (порог, ставка) для `pf_special_steps_formula`.
    """
    row_at = ws_in.max_row + 2
    ws_in.cell(row=row_at, column=1, value="СТУПЕНИ СТАВКИ ПФ ПО ПОКРЫТИЮ ЭСКРОУ")
    ws_in.cell(row=row_at + 1, column=1,
               value=f"Правьте значения — {where}. Пустой порог выключает ступень.")
    row_at += 2
    refs: list[tuple[str, str]] = []
    for index, (edge, rate) in enumerate(steps):
        ws_in.cell(row=row_at, column=1, value=f"Ступень {index + 1} — покрытие от")
        ws_in.cell(row=row_at, column=2, value=round(edge, 6))
        ws_in.cell(row=row_at, column=3, value="×")
        edge_ref = f"Вводные!$B${row_at}"
        row_at += 1
        ws_in.cell(row=row_at, column=1, value=f"Ступень {index + 1} — ставка")
        ws_in.cell(row=row_at, column=2, value=round(rate, 8)).number_format = "0.00%"
        ws_in.cell(row=row_at, column=3, value="% годовых")
        refs.append((edge_ref, f"Вводные!$B${row_at}"))
        row_at += 1
    return refs


_PLATO_PARKING_SALES_CELL = "I33"
_PLATO_PARKING_SALES_EXPECTED = "='Расчет ВРИ (ТЭП)'!D68+'Расчет ВРИ (ТЭП)'!D69"
_PLATO_PARKING_SALES_FIXED = "='Расчет ВРИ (ТЭП)'!D68"


def _plato_sell_only_permanent_parking(
    workbook, filled: list[dict[str, Any]], missing: list[str],
) -> None:
    """Книга продаёт столько же машино-мест, сколько движок.

    Гостевые места строятся, но не продаются — это методика, и движок ей уже
    следует. Книга не следовала: `ТЭП!I33` складывала постоянные и гостевые, а
    это число читают ровно два листа, и оба про продажи — `ПОДБОР_КВ.М`!D32 и
    `План продаж`!D7. Площадь и стоимость стройки отсюда не берутся вовсе
    (проверено по всем формулам шаблона), так что сумма здесь означала одно:
    гостевые места продаются.

    Расхождение выходило ровно в десятую часть паркинга — 2 054 млн ₽ выручки
    в книге против 1 867 у движка на умолчаниях, — и тянуло за собой всё:
    эскроу, покрытие, ступень ставки ПФ, налог, LLCR. Две поверхности на одни
    вводные, обе достоверные на вид.

    Формула сверяется перед заменой. Другая формула — это другая книга, и
    молча переписывать её нельзя: строка уходит в `missing`.
    """
    if "ТЭП" not in workbook.sheetnames:
        missing.append("ТЭП · продаваемые машино-места")
        return
    sheet = workbook["ТЭП"]
    cell = sheet[_PLATO_PARKING_SALES_CELL]
    current = str(cell.value or "").replace(" ", "")
    if current == _PLATO_PARKING_SALES_FIXED.replace(" ", ""):
        return
    if current != _PLATO_PARKING_SALES_EXPECTED.replace(" ", ""):
        missing.append(
            f"ТЭП!{_PLATO_PARKING_SALES_CELL} · формула не опознана: {cell.value!r}")
        return
    cell.value = _PLATO_PARKING_SALES_FIXED
    filled.append({
        "sheet": "ТЭП", "cell": _PLATO_PARKING_SALES_CELL,
        "label": "Продаваемые машино-места",
        "value": _PLATO_PARKING_SALES_FIXED,
        "note": "гостевые места строятся, но не продаются — как в движке",
    })


def _plato_apply_pf_rate_methodology(
    workbook: Any, filled: list[dict[str, Any]], missing: list[str],
    steps: list[tuple[float, float]] | None = None,
) -> None:
    """Привести ставку ПФ на листе «КРЕДИТЫ» к действующей методике.

    Шаблон считает ставку двумя ветками: строка 56 «СЗ > Эскроу» — взвешенная
    сумма базовой и специальной ставок, строка 57 «СЗ < Эскроу» — снижение
    специальной ставки на трансферный доход (D17) и полка 0,01% годовых выше
    двух покрытий. Вторая ветка описывает то, чего в кредитном договоре нет:
    покрывать больше 100% долга нечего, и ниже специальной ставка не идёт.
    Ровно эти две ветки убраны из движка, и пока они оставались в книге, она
    считала долг почти бесплатным — 360,3 млн ₽ процентов против 746,5 млн ₽
    в расчёте на одних и тех же вводных.

    Поэтому строка 55 больше не выбирает ветку, а строка 56 берёт вес покрытия
    с ограничением сверху. Трогаются только помесячные колонки: в P–R той же
    строки лежат сводные AVERAGEIF, и их формулы другие.
    """
    if "КРЕДИТЫ" not in workbook.sheetnames:
        missing.append("КРЕДИТЫ · методика ставки ПФ")
        return
    sheet = workbook["КРЕДИТЫ"]
    changed = 0
    stepped = 0
    # Лестница — вводная и в книге: пороги и ставки ложатся ячейками на
    # «Вводные» (колонки K–L свободны и никем не адресуются — проверено по
    # всем листам), а формула строки 57 ссылается на них. Правка ячейки в
    # Excel пересчитывает книгу; зашитые в формулу числа пришлось бы менять
    # по всем месячным колонкам двух очередей (владелец, 20.08.2026:
    # «сейчас-то надбавка — это вводная»).
    # Вставить строки в середину листа нельзя: openpyxl при сдвиге формулы не
    # переписывает, а под блоком финансирования живёт вся карта записи
    # фиксированными адресами (B82 льгота и далее) — съехало бы всё. Низ листа
    # свободен и никем не адресуется (проверено по всем листам), блок ложится
    # туда теми же колонками A–C, в стиле самого листа.
    step_refs: list[tuple[str, str]] | None = None
    if steps and "Вводные" in workbook.sheetnames:
        step_refs = _ladder_input_block(
            workbook["Вводные"], steps,
            "формула строки 57 листа «КРЕДИТЫ» читает их отсюда")
    # Очередей в книге две, и у каждой свой блок: 55–57 у первой, 78–80 у
    # второй. Правились только строки первой, и на многоочередном проекте
    # расхождение возвращалось через вторую.
    for rate_row, coverage_row, special_row, weighted_row in ((55, 53, 57, 56), (78, 76, 80, 79)):
        # =IF(X$3<$D61,IF(X53>1,X57,X56),X$13) -> =IF(X$3<$D61,X56,X$13)
        branch = re.compile(
            rf"^=IF\((?P<col>[A-Z]{{1,2}})\$3<\$D(?P<anchor>\d+),"
            rf"IF\((?P=col){coverage_row}>1,(?P=col){special_row},(?P=col){weighted_row}\),"
            rf"(?P=col)\$13\)$"
        )
        weight = re.compile(rf"\b([A-Z]{{1,2}}){coverage_row}\b")
        for column in range(1, sheet.max_column + 1):
            rate = sheet.cell(row=rate_row, column=column)
            share = sheet.cell(row=weighted_row, column=column)
            if not isinstance(rate.value, str) or not isinstance(share.value, str):
                continue
            match = branch.match(rate.value.strip())
            if not match or "MIN(" in share.value:
                continue
            col = match.group("col")
            rate.value = f"=IF({col}$3<$D{match.group('anchor')},{col}{weighted_row},{col}$13)"
            share.value = weight.sub(rf"MIN(\g<1>{coverage_row},1)", share.value)
            if steps:
                # Ступени задали — строка специальной ставки перестаёт быть
                # константой и выбирается по покрытию того же месяца, как в
                # движке. Прежнее содержимое ячейки становится последней
                # ветвью: ниже первой ступени действует обычная ставка.
                special = sheet.cell(row=special_row, column=column)
                previous = special.value
                if isinstance(previous, str) and previous.strip().startswith("="):
                    base = previous.strip()[1:]
                elif isinstance(previous, (int, float)):
                    base = f"{float(previous):.8g}"
                else:
                    base = ""
                if base:
                    special.value = "=" + pf_special_steps_formula(
                        f"{col}{coverage_row}", steps, base, refs=step_refs)
                    stepped += 1
            changed += 1
    if not changed:
        # Шаблон переставили или формулы переписали — молча считать по старому
        # нельзя, это возвращает расхождение по процентам.
        missing.append("КРЕДИТЫ · методика ставки ПФ")
        return
    filled.append({
        "sheet": "КРЕДИТЫ", "row": 55,
        "label": "Ставка ПФ · вес покрытия ограничен 1×", "value": changed,
    })
    if steps:
        if not stepped:
            # Ступени заданы, а в книгу не легли — это расхождение методик,
            # и молчать о нём нельзя: книга посчитает по одной ставке, отчёт
            # по лестнице, и оба будут выглядеть достоверно.
            missing.append("КРЕДИТЫ · ступени ставки по покрытию эскроу")
        else:
            filled.append({
                "sheet": "КРЕДИТЫ", "row": 57,
                "label": "Ставка ПФ · ступени по покрытию эскроу", "value": stepped,
            })


def fill_plato_template(
    inputs: dict[str, Any],
    tep: dict[str, dict[str, Any]],
    *,
    scenario: str = "base",
    template_path: Path | None = None,
    project_name: str = "",
) -> tuple[bytes, dict[str, Any]]:
    """Заполняет листы-вводные шаблона ПЛАТО, не трогая формулы."""
    inputs = dict(inputs or {})
    migrate_growth_post(inputs)
    try:
        from openpyxl import load_workbook
    except ImportError as exc:  # pragma: no cover - зависимость объявлена в requirements
        raise HTTPException(
            status_code=500,
            detail="Для выгрузки в шаблон ПЛАТО нужен пакет openpyxl. Добавьте его в requirements.txt.",
        ) from exc

    path = template_path or _PLATO_TEMPLATE_PATH
    if not path.is_file():
        raise HTTPException(
            status_code=503,
            detail=(
                "Шаблон ПЛАТО не найден на сервере: положите файл в "
                "templates/PLATO_template.xlsx и передеплойте сервис."
            ),
        )
    merged = {**copy.deepcopy(DEFAULT_INPUTS), **(inputs or {})}
    merged_tep = copy.deepcopy(TEP_DEFAULT)
    for key, values in (tep or {}).items():
        if isinstance(values, dict) and key in merged_tep:
            merged_tep[key].update(values)
    # Тип проекта — тем же предикатом, что у движка: шаблон строит то, что
    # движок считает, а не присланное целиком (и не умолчание квартир).
    merged, merged_tep = residential_excluded(merged, merged_tep)
    merged, merged_tep = object_instances_applied(merged, merged_tep)

    workbook = load_workbook(path, data_only=False, keep_vba=False)
    filled: list[dict[str, Any]] = []
    missing: list[str] = []

    sheet = workbook["Вводные"]
    rows_by_label: dict[str, list[int]] = defaultdict(list)
    rows_by_block: dict[tuple[str, str], list[int]] = defaultdict(list)
    for row in range(1, sheet.max_row + 1):
        block = _plato_normalize(sheet.cell(row=row, column=1).value)
        label = _plato_normalize(sheet.cell(row=row, column=2).value)
        if label:
            rows_by_label[label].append(row)
            if block:
                rows_by_block[(block, label)].append(row)

    def write_scenario_row(row: int, value: Any, name: str, *, replace_formula: bool = False) -> None:
        # Значение модели одно, поэтому оно кладётся во все три сценария:
        # переключатель в шаблоне тогда не меняет цифры расчёта DevelopAid.
        # Колонка G обычно выбирает сценарий формулой INDEX и трогать её нельзя,
        # но у выключателей «Объект включен» сценарных колонок нет вовсе: там
        # пусто, а в G лежит готовое «Нет». Пока мы писали только в D:F, МФОЦ,
        # ТЦ и наземный паркинг оставались выключенными в каждой выгрузке, и их
        # выручка пропадала из модели.
        # replace_formula — для полей, где шаблон считает своё вместо нашего.
        # Себестоимость соцобъектов он тянул с листа «Расчет ВРИ (ТЭП)» и давал
        # 0,0097 млн ₽ за место вместо 2,75: социальная нагрузка выходила
        # 0,6 млн ₽ вместо 193,2 млн ₽. Считает движок, шаблон обязан показывать
        # его цифры, а не остатки прежней методики.
        for column in (4, 5, 6, 7):
            cell = sheet.cell(row=row, column=column)
            formula = isinstance(cell.value, str) and cell.value.startswith("=")
            if formula and not (replace_formula and column != 7):
                continue
            cell.value = value
        filled.append({"sheet": "Вводные", "row": row, "label": name, "value": value})

    for label, key, kind in _PLATO_INPUT_MAP:
        rows = rows_by_label.get(_plato_normalize(label)) or []
        if not rows or key not in merged:
            continue
        value = _plato_value(kind, merged.get(key))
        if value is None:
            continue
        write_scenario_row(rows[0], value, label)

    # Ставка, ушедшая от базы класса, помечается в свободной колонке H той же
    # строки: сценарные D–F заняты значением, G — переключателем, и его не
    # трогать никогда. Молча книга и отчёт «одного класса» разошлись бы, и
    # оба выглядели бы верно.
    class_deviations = project_class_deviations(merged)
    deviated = {item["field"]: item for item in class_deviations["rows"]}
    for label, key, _kind in _PLATO_INPUT_MAP:
        item = deviated.get(key)
        if not item:
            continue
        rows = rows_by_label.get(_plato_normalize(label)) or []
        if not rows:
            continue
        sheet.cell(row=rows[0], column=8).value = (
            f"≠ база класса «{class_deviations['label']}»: {item['base']:g}")
        filled.append({"sheet": "Вводные", "row": rows[0],
                       "label": f"{label} · отметка о базе класса",
                       "value": item["base"]})

    for block, label, key, kind in _PLATO_BLOCK_MAP:
        block_key, label_key = _plato_normalize(block), _plato_normalize(label)
        rows = rows_by_block.get((block_key, label_key)) or []
        if not rows:
            # Подписи блоков в шаблоне длиннее ключа карты, сверяем по началу строки.
            rows = [
                row
                for (found_block, found_label), found_rows in rows_by_block.items()
                if found_label == label_key and found_block.startswith(block_key)
                for row in found_rows
            ]
        if not rows:
            missing.append(f"Вводные · {block} · {label}")
            continue
        value = _plato_value(kind, merged.get(key))
        if value is None:
            continue
        write_scenario_row(rows[0], value, f"{block} · {label}",
                           replace_formula=key in _PLATO_OVERRIDE_TEMPLATE_FORMULA)

    # Прогноз ключевой ставки устроен не как остальные вводные: подпись лежит
    # в колонке A, а значения разбросаны по C–G. Карта ищет подписи в колонке B
    # и до этого блока не дотягивалась, поэтому шаблон жил на своих ставках:
    # цели 13/11/10% против наших 11/9/7% и выбранный сценарий «Низкая» вместо
    # базового. Проценты по кредитам расходились с расчётом почти на треть.
    rate_scenario_names = {"high": "Высокая", "base": "Базовая", "low": "Низкая"}
    rate_row = next(
        (row for row in range(1, sheet.max_row + 1)
         if _plato_normalize(sheet.cell(row=row, column=1).value) == "сценарий ставки"),
        None,
    )
    if rate_row is None:
        missing.append("Вводные · Прогноз ключевой ставки")
    else:
        scenario_key = str(merged.get("rate_scenario") or "base").strip().lower()
        rate_cells: list[tuple[int, int, Any, str]] = [
            (rate_row, 3, rate_scenario_names.get(scenario_key, "Базовая"), "Сценарий ставки"),
            (rate_row, 5, n(merged, "rate_start_pct", 0.0) / 100, "Текущая ключевая ставка"),
            (rate_row, 7, n(merged, "rate_normalization_months", 24), "Срок выхода на цель"),
            (rate_row + 1, 4, n(merged, "rate_target_high_pct", 0.0) / 100, "Целевая ставка · высокая"),
            (rate_row + 1, 5, n(merged, "rate_target_base_pct", 0.0) / 100, "Целевая ставка · базовая"),
            (rate_row + 1, 6, n(merged, "rate_target_low_pct", 0.0) / 100, "Целевая ставка · низкая"),
        ]
        for row, column, value, name in rate_cells:
            cell = sheet.cell(row=row, column=column)
            # Колонку G строки «Целевая ставка» выбирает формула INDEX по C54 —
            # её трогать нельзя, иначе сценарий перестанет переключаться.
            if isinstance(cell.value, str) and cell.value.startswith("="):
                continue
            cell.value = value
            filled.append({"sheet": "Вводные", "row": row, "label": name, "value": value})

    # Шаблон не принимает месячный рост цены напрямую: он выводит его из
    # целевого совокупного роста за период продаж по формуле
    # (1+цель)^(1/N)-1, где N — месяцы от старта продаж до РВЭ. Пока эта строка
    # не заполнена, там остаётся 30% сценария, а модель считает по своему
    # месячному росту — на длинных продажах расхождение по выручке доходит до
    # четверти. Пересчитываем цель обратно, чтобы месячный рост совпал.
    growth_rows = rows_by_label.get(_plato_normalize(
        "Целевой совокупный рост цены от старта продаж до РВЭ")) or []
    if growth_rows:
        monthly = (_land_float(merged.get("monthly_growth_pre_pct")) or 0.0) / 100.0
        months = int(_land_float(merged.get("construction_months")) or 0) - int(
            _land_float(merged.get("sales_lag_months")) or 0)
        target = (1.0 + monthly) ** max(1, months) - 1.0
        # Округлять грубее нельзя: шаблон берёт из этого числа корень степени
        # months, и потерянные знаки возвращаются заметной ошибкой в месячном росте.
        write_scenario_row(growth_rows[0], round(target, 12),
                           "Целевой совокупный рост цены от старта продаж до РВЭ")

    mode_rows = rows_by_block.get((_plato_normalize("Соцнагрузка"), _plato_normalize("Форма исполнения"))) or []
    if not mode_rows:
        mode_rows = rows_by_label.get(_plato_normalize("Форма исполнения")) or []
    if mode_rows:
        write_scenario_row(mode_rows[0], str(merged.get("social_mode") or "Строительство"), "Форма исполнения")

    # Прогноз ключевой ставки
    for label, key, kind in (
        ("Текущая ключевая ставка", "rate_start_pct", "pct"),
        ("Срок выхода на цель, мес.", "rate_normalization_months", "number"),
    ):
        for row in range(1, sheet.max_row + 1):
            for column in range(1, 8):
                if _plato_normalize(sheet.cell(row=row, column=column).value) == _plato_normalize(label):
                    target = sheet.cell(row=row, column=column + 1)
                    value = _plato_value(kind, merged.get(key))
                    if value is not None and not (isinstance(target.value, str) and str(target.value).startswith("=")):
                        target.value = value
                        filled.append({"sheet": "Вводные", "row": row, "label": label, "value": value})
                    break

    tep_sheet = workbook["Расчет ВРИ (ТЭП)"]
    tep_rows: dict[str, int] = {}
    for row in range(1, tep_sheet.max_row + 1):
        label = _plato_normalize(tep_sheet.cell(row=row, column=2).value)
        if label and label not in tep_rows:
            tep_rows[label] = row
    for label, path_expr in _PLATO_TEP_ROWS:
        row = tep_rows.get(_plato_normalize(label))
        if not row:
            missing.append(f"Расчет ВРИ (ТЭП) · {label}")
            continue
        value = _plato_tep_value(merged_tep, path_expr)
        if value is None:
            continue
        tep_sheet.cell(row=row, column=4).value = round(value, 4)
        filled.append({"sheet": "Расчет ВРИ (ТЭП)", "row": row, "label": label, "value": round(value, 4)})

    # Стоимость смены ВРИ и компенсация социальных объектов — из модели.
    vri_row = tep_rows.get(_plato_normalize("Многоквартирная жилые здания"))
    if vri_row:
        land_rights = _land_float(merged.get("land_rights_cost_mln")) or 0.0
        tep_sheet.cell(row=vri_row, column=4).value = round(land_rights, 3)
        filled.append({"sheet": "Расчет ВРИ (ТЭП)", "row": vri_row,
                       "label": "Стоимость смены ВРИ", "value": round(land_rights, 3)})

    # Компенсация за социальные объекты разнесена по типам — так её и считает
    # калькулятор ГлавАПУ, и так её читает импорт. В книгу же уходила только
    # плата за ВРИ, а строки ДОО, школы и поликлиники оставались с прежними
    # числами шаблона: 319,1 + 509,6 + 159,8 = 988,4 млн ₽ вместо 580,7. При
    # денежной форме исполнения книга берёт обременение именно отсюда, поэтому
    # расходы завышались на 407,7 млн ₽, а следом расходились прибыль и LLCR.
    imported = (merged.get("_glavapu_import") or {}).get("normalized") or {}
    # Подписи «ДОО», «Школа» и «Поликлиника» на листе встречаются дважды: сперва
    # количество мест в «Расчёте объектов обслуживания», ниже — деньги. Ищем от
    # заголовка компенсации, иначе сумма ляжет в строку мощности.
    compensation_start = next(
        (row for row in range(1, tep_sheet.max_row + 1)
         if "компенсац" in _plato_normalize(tep_sheet.cell(row=row, column=2).value)),
        None,
    )
    # Итог компенсации — отдельная строка, а не сумма трёх ниже. Книга берёт
    # обременение именно из неё: ОТЧЕТ!C15 -> Вводные!G100 -> D83. Пока писалась
    # только раскладка, итог оставался прежним, и в модели держались 988,4 млн ₽
    # вместо 580,7 — раскладка при этом уже была правильной.
    if compensation_start and isinstance(imported.get("social_compensation_total_mln"), (int, float)):
        total = round(float(imported["social_compensation_total_mln"]), 3)
        tep_sheet.cell(row=compensation_start, column=4).value = total
        filled.append({"sheet": "Расчет ВРИ (ТЭП)", "row": compensation_start,
                       "label": "Компенсация · итого", "value": total})

    for label, key in (
        ("ДОО", "social_compensation_kindergarten_mln"),
        ("Школа", "social_compensation_school_mln"),
        ("Поликлиника", "social_compensation_clinic_mln"),
    ):
        row = None
        if compensation_start:
            row = next(
                (r for r in range(compensation_start + 1, min(compensation_start + 8, tep_sheet.max_row + 1))
                 if _plato_normalize(tep_sheet.cell(row=r, column=2).value) == _plato_normalize(label)),
                None,
            )
        value = imported.get(key)
        if not row or not isinstance(value, (int, float)):
            continue
        tep_sheet.cell(row=row, column=4).value = round(float(value), 3)
        filled.append({"sheet": "Расчет ВРИ (ТЭП)", "row": row,
                       "label": f"Компенсация · {label}", "value": round(float(value), 3)})

    # Техзаказчик и авторский надзор — те же расходы на управление, а СМР
    # подземной части — те же СМР: в книге под них нет отдельных строк, и
    # держать их порознь незачем. Передаём слитыми: эффективный процент
    # управления и взвешенная ставка строительства. Без этого книга считала
    # управление своими 5% (291,9 млн ₽ против 523,1) и знала только наземную
    # часть, отчего расходы на строительство расходились с расчётом.
    try:
        _plato_merge_management_and_smr(sheet, rows_by_label, merged, tep, filled)
    except Exception as exc:
        missing.append("Вводные · управление и СМР: " + _error_location(exc))

    _plato_fill_land_sheet(workbook, merged, filled, merged_tep)
    _plato_apply_pf_rate_methodology(
        workbook, filled, missing, pf_special_steps(merged.get("pf_special_steps")))
    _plato_apply_pf_cashflow(workbook, filled, missing)
    _plato_fix_social_capex_links(workbook, filled, missing)
    _plato_sell_only_permanent_parking(workbook, filled, missing)

    # Имя проекта в шапке ОТЧЕТа — не украшение: без него каждая выгрузка
    # уезжает заказчику подписанной чужим проектом из шаблона.
    title = str(project_name or "").strip()
    if title:
        workbook["ОТЧЕТ"]["C1"] = title
        filled.append({"sheet": "ОТЧЕТ", "row": 1, "label": "Проект", "value": title})

    workbook.calculation.fullCalcOnLoad = True
    buffer = io.BytesIO()
    workbook.save(buffer)
    return _plato_drop_external_links(buffer.getvalue()), {
        "filled": filled,
        "filled_count": len(filled),
        "missing": missing,
        "scenario": scenario,
        "template": path.name,
        "class_deviations": class_deviations,
    }


_PLATO_CONSOLIDATOR_PATH = Path(__file__).resolve().parent / "templates" / "PLATO_consolidator.xlsx"
_PLATO_CONSOLIDATOR_SLOTS = 4


# --- Новая книга: вводные, помесячный расчёт, отчёт ------------------------
#
# Шаблон ПЛАТО — учётная модель действующего проекта: погашение и выборка там
# приходят с листа «факт», рассрочка ВРИ зашита на шесть лет, а параллельный
# лист «Расчет ВРИ (ТЭП)» считает свои нормативы. Свести его с движком удалось
# восемью правками, и каждая проверялась чужим пересчётом, потому что здесь
# посчитать книгу нечем.
#
# Эта книга собирается с нуля и устроена иначе. Вводные и помесячные драйверы —
# продажи, затраты, ключевая ставка — приходят значениями: это сценарий, а не
# расчёт, и спорить о нём книге незачем. Весь финансовый блок — эскроу, БРИДЖ,
# ПФ, ставки, проценты, налог, LLCR — живые формулы по методике движка.
# Аналитик меняет спред, ставку или налог и видит пересчёт.

_MODEL2_INPUTS: list[tuple[str, str, str]] = [
    ("Цена покупки / вход", "purchase_price_mln", "млн ₽"),
    ("Выкуп ЗУ/ОКС у третьих лиц (в стоимости сделки)", "land_buyout_mln", "млн ₽"),
    ("Смена ВРИ / земельные права", "land_rights_cost_mln", "млн ₽"),
    ("Спред БРИДЖ", "bridge_spread_pp", "п.п."),
    ("Спред капитализации БРИДЖ", "bridge_cap_spread_pp", "п.п."),
    ("Спред ПФ", "pf_spread_pp", "п.п."),
    ("Ставка ПФ при покрытии эскроу 1×", "pf_special_pct", "%"),
    ("Плата за лимит", "limit_fee_pct", "%"),
    ("Плата за резервирование", "reservation_fee_pct", "%"),
    ("Налог на прибыль", "profit_tax_pct", "%"),
]

# Листы книги. Порядок сборки — это порядок зависимостей: продажи и затраты
# не знают о кредите, эскроу не знает о ставке, кредит читает всех троих.
# Циклов между листами нет, иначе Excel показал бы круговую ссылку.
_M2_SHEETS = {
    "inputs": "Вводные",
    "tep": "ТЭП",
    "schedule": "СРОКИ",
    "sales": "ПРОДАЖИ",
    "costs": "СЕБЕСТОИМОСТЬ",
    "rates": "СТАВКИ",
    "escrow": "ЭСКРОУ",
    "credit": "КРЕДИТОВАНИЕ",
    "tax": "НАЛОГИ",
    "cf": "CF",
    "llcr": "LLCR",
    "vri": "ВРИ",
    "report": "ОТЧЁТ",
}

# Продукт -> как книга его считает. Колонка базы: 5 — продаваемая площадь,
# 7 — единицы; у отдельных объектов КРТ база берётся не с «ТЭП», а прямо из
# вводных — движок считает их по своим полям. Сезонность и смещение темпа
# действуют только на основные продукты: к объектам КРТ движок их не применяет.
_M2_PRODUCTS: dict[str, dict[str, Any]] = {
    "apartments": {
        "base_column": 5, "price": "apartment_price_th", "scale": 0.001, "unit": "м²",
        "share": "share_before_rve_pct", "residual": "residual_sales_months",
        "growth_pre": "monthly_growth_pre_pct", "growth_post": None,
        "core": True,
    },
    "ground_commercial": {
        "base_column": 5, "price": "commercial_price_th", "scale": 0.001, "unit": "м²",
        "share": "share_before_rve_pct", "residual": "residual_sales_months",
        "growth_pre": "monthly_growth_pre_pct", "growth_post": None,
        "core": True,
    },
    "underground_parking": {
        # Колонка 9 — «Продаётся, ед.»: гостевые места в продажи не входят.
        "base_column": 9, "price": "parking_price_th", "scale": 0.001, "unit": "м/м",
        "share": "share_before_rve_pct", "residual": "residual_sales_months",
        "growth_pre": "monthly_growth_pre_pct", "growth_post": None,
        "core": True,
    },
    "storage": {
        "base_column": 9, "price": "storage_price_th", "scale": 0.001, "unit": "шт.",
        "share": "share_before_rve_pct", "residual": "residual_sales_months",
        "growth_pre": "monthly_growth_pre_pct", "growth_post": None,
        "core": True,
    },
    "offices": {
        "base_input": "offices_saleable_sqm", "price": "offices_price_th_per_sqm",
        "scale": 0.001, "unit": "м²", "share": "offices_share_before_rve_pct",
        "residual": "offices_residual_months", "growth_pre": "offices_growth_pre_pct",
        "growth_post": "offices_growth_post_pct", "core": False,
        "sales_start": "offices_sales_start", "build_start": "offices_start",
        "build_months": "offices_months",
    },
    "standalone_retail": {
        "base_input": "retail_saleable_sqm", "price": "retail_price_th_per_sqm",
        "scale": 0.001, "unit": "м²", "share": "retail_share_before_rve_pct",
        "residual": "retail_residual_months", "growth_pre": "retail_growth_pre_pct",
        "growth_post": "retail_growth_post_pct", "core": False,
        "sales_start": "retail_sales_start", "build_start": "retail_start",
        "build_months": "retail_months",
    },
    "above_parking": {
        "base_input": "above_parking_spaces", "price": "above_parking_price_mln_per_space",
        "scale": 1.0, "unit": "м/м", "share": "above_parking_share_before_rve_pct",
        "residual": "above_parking_residual_months", "growth_pre": "above_parking_growth_pre_pct",
        "growth_post": "above_parking_growth_post_pct", "core": False,
        "sales_start": "above_parking_sales_start", "build_start": "above_parking_start",
        "build_months": "above_parking_months",
    },
}

# Месяцы пониженного спроса — те же, что в шаблоне ПЛАТО (лист ПОДБОР_КВ.М).
_M2_SEASONAL_LOW_MONTHS = (1, 5, 6, 7, 8)

# Списки для полей, у которых на странице свой набор вариантов: FIELD_GROUPS их
# не несёт, а без них в книге вместо выбора остаётся свободный ввод.
_M2_EXTRA_OPTIONS: dict[str, list[list[str]]] = {
    "bridge_interest_mode": [["Капитализация в ПФ", "Капитализация в ПФ"],
                             ["Выплата при рефинансировании", "Выплата при рефинансировании"]],
    "social_mode": [["Строительство", "Строительство"],
                    ["Денежная компенсация", "Денежная компенсация"],
                    [SOCIAL_MODE_BOTH, SOCIAL_MODE_BOTH]],
}

# Прогноз ключевой ставки: на странице он в своём блоке, а не в FIELD_GROUPS.
# Без него ставка приезжала бы в книгу готовым рядом чисел.
_M2_RATE_INPUTS: list[tuple[str, str, str, str]] = [
    ("rate_start_date", "Дата стартовой ставки", "дата", "date"),
    ("rate_start_pct", "Ключевая ставка на старте", "%", "number"),
    ("rate_target_high_pct", "Цель — консервативный сценарий", "%", "number"),
    ("rate_target_base_pct", "Цель — базовый сценарий", "%", "number"),
    ("rate_target_low_pct", "Цель — оптимистичный сценарий", "%", "number"),
    ("rate_normalization_months", "Срок выхода на цель", "мес.", "number"),
    ("rate_curve_shape", "Форма кривой", "коэффициент", "number"),
    ("rate_scenario", "Сценарий ставки", "сценарий", "select"),
]

_M2_RATE_SCENARIOS = [["high", "Консервативный"], ["base", "Базовый"], ["low", "Оптимистичный"]]

# Поля страницы, до расчёта не доходящие: движок их не читает, они уезжают
# только в шаблон ПЛАТО. В книге они помечены — иначе аналитик правит этап
# роста цены, ничего не происходит, и виноватой оказывается книга.
# «vat_pct» ушла отсюда 16.08.2026: НДС теперь считается, и пометка «не
# участвует» на «Вводных» стала бы такой же обманкой, какой была сама ставка.
# Этапы роста цены («growth_stage1..4_pct») ушли отсюда 02.09.2026: движок
# читает их как лестницу цены по строительной готовности.
# «inflation_after_rve_pct» ушла отсюда 15.10.2026: она — единственный
# источник роста цены после РВЭ.
_M2_TEMPLATE_ONLY_INPUTS: frozenset[str] = frozenset()

# Статьи движка, на которые резерв не начисляется. Плата за смену ВРИ —
# известная сумма по расчёту органа власти, а не смета, у которой бывает
# перерасход: резерв на неё не нужен (решение владельца 06.10.2026). Проценты
# и обеспечение рассрочки ВРИ, её теневые ключи (`land_rights_gross`,
# `land_rights_relief`) и цена участка в `amounts` к моменту резерва ещё не
# лежат. Один список на движок и обе книги.
RESERVE_EXCLUDED_ARTICLES = frozenset({"land_rights"})

# Из базы резерва движок исключает цену входа, плату за смену ВРИ и стоимость
# её рассрочки: процент берётся от набора статей, в который они не входят.
_M2_RESERVE_EXCLUDED = frozenset({"reserve", "purchase", "vri_interest", "vri_security",
                                  *RESERVE_EXCLUDED_ARTICLES})

# Статьи затрат в порядке листа. Третий признак — считает ли книга статью сама.
# Плата за ВРИ и соцнагрузка идут по собственным графикам (рассрочка на своём
# листе, объекты со своими сроками ввода) и приходят рядом значений; считаемые
# статьи стоят на листе всегда, даже с нулевой суммой, — иначе нулевая цена
# входа лишает книгу строки и вписать покупку становится некуда.
_M2_COST_ARTICLES: list[tuple[str, str, bool]] = [
    ("purchase", "Приобретение / вход", True),
    ("land_rights", "Земельные правоотношения / смена ВРИ", False),
    ("ird", "ИРД и согласования", True),
    ("design_p", "Проектирование, стадия П", True),
    ("design_rd", "Проектирование, стадия РД", True),
    ("demolition", "Снос и демонтаж", True),
    ("resettlement", "Расселение", True),
    ("preparation", "Подготовительные работы", True),
    ("main_above", "Основное строительство, наземная часть", True),
    ("main_under", "Основное строительство, подземная часть", True),
    ("utilities", "Наружные инженерные сети", True),
    ("site_maintenance", "Содержание стройплощадки", True),
    ("author_supervision", "Авторский надзор", True),
    ("technical_supervision", "Технический заказчик / стройконтроль", True),
    ("project_management", "Управление проектом", True),
    ("landscaping", "Благоустройство", True),
    ("commissioning", "Сдача и ввод", True),
    ("social", "Социальная нагрузка", False),
    ("offices", "МФОЦ / офисы", False),
    ("standalone_retail", "ТЦ / коммерция ОСЗ", False),
    ("above_parking", "Наземный паркинг", False),
    ("sports", "ФОК / медцентр", False),
    ("vri_interest", "Проценты по рассрочке ВРИ", False),
    ("vri_security", "Обеспечение по рассрочке ВРИ", False),
    ("gc_fee", "Вознаграждение генподрядчика", True),
    ("reserve", "Резерв", True),
]

# Показатели листа «ОТЧЁТ» — порядок строк, на него ссылается тест.
_M2_REPORT_KEYS = [
    "revenue", "capex", "operating", "ebitda", "financing_cost",
    "profit_before_tax", "profit_tax", "vat", "net_profit",
    "peak_bridge", "pf_draw_total", "peak_pf", "avg_pf_rate", "llcr",
]


def _model2_letter(index: int) -> str:
    return get_column_letter(index)


class _MonthGrid:
    """Помесячный лист: колонка A — подписи, B и далее — месяцы.

    Строки заводятся по порядку и запоминаются под ключом, поэтому формулы
    ссылаются на соседей по имени, а не по номеру: вставка строки посередине
    не ломает лист.
    """

    MONTH_ROW = 2
    FIRST_COLUMN = 2

    def __init__(self, sheet, months: list, styles: dict, *, title: str = "") -> None:
        self.sheet = sheet
        self.months = months
        self.styles = styles
        self.rows: dict[str, int] = {}
        self._next = 3
        sheet.cell(row=1, column=1, value=title or sheet.title).font = styles["title"]
        sheet.cell(row=self.MONTH_ROW, column=1, value="Месяц").font = styles["bold"]
        for index, month in enumerate(months):
            cell = sheet.cell(row=self.MONTH_ROW, column=self.FIRST_COLUMN + index, value=month)
            cell.number_format = styles["month"]
            cell.font = styles["bold"]
        sheet.column_dimensions["A"].width = 46
        sheet.freeze_panes = "B3"

    # --- адресация ---------------------------------------------------------

    def letter(self, index: int) -> str:
        return get_column_letter(self.FIRST_COLUMN + index)

    def month(self, index: int) -> str:
        return f"{self.letter(index)}${self.MONTH_ROW}"

    def at(self, key: str, index: int) -> str:
        """Ссылка на свою строку в колонке месяца — для формул этого же листа."""
        return f"{self.letter(index)}{self.rows[key]}"

    def before(self, key: str, index: int) -> str:
        """Та же строка месяцем раньше; в первом месяце — ноль."""
        return "0" if index == 0 else f"{self.letter(index - 1)}{self.rows[key]}"

    def outside(self, key: str, index: int) -> str:
        """Ссылка с другого листа."""
        return f"{self.sheet.title}!{self.letter(index)}{self.rows[key]}"

    def outside_before(self, key: str, index: int) -> str:
        if index == 0:
            return "0"
        return f"{self.sheet.title}!{self.letter(index - 1)}{self.rows[key]}"

    def span(self, key: str) -> str:
        """Весь ряд месяцев одной строки: «ЛИСТ!B7:BD7»."""
        last = self.letter(len(self.months) - 1)
        return f"{self.sheet.title}!{self.letter(0)}{self.rows[key]}:{last}{self.rows[key]}"

    # --- строки ------------------------------------------------------------

    def layout(self, *items: str | tuple[str, str]) -> None:
        """Разметить лист до заполнения.

        Формула ссылается на соседа сверху и снизу — «остаток на конец месяца»
        нужен строке «раскрытие», а сам считается через неё. Поэтому номера
        строк раздаются один раз, здесь, а формулы пишутся потом в любом
        порядке. Пара («section», «БРИДЖ») — заголовок блока.
        """
        for item in items:
            if isinstance(item, tuple):
                self.sheet.cell(row=self._next, column=1, value=item[1]).font = self.styles["section"]
            else:
                self.rows[item] = self._next
            self._next += 1

    def values(self, key: str, label: str, series, fmt: str, *, bold: bool = False) -> int:
        row = self._claim(key, label, bold=bold, driver=True)
        for index in range(len(self.months)):
            value = float(series[index]) if index < len(series) else 0.0
            cell = self.sheet.cell(row=row, column=self.FIRST_COLUMN + index,
                                   value=round(value, 12))
            cell.number_format = fmt
        return row

    def formula(self, key: str, label: str, maker, fmt: str, *, bold: bool = False) -> int:
        row = self._claim(key, label, bold=bold)
        for index in range(len(self.months)):
            cell = self.sheet.cell(row=row, column=self.FIRST_COLUMN + index,
                                   value=maker(index))
            cell.number_format = fmt
        return row

    def _claim(self, key: str, label: str, *, bold: bool = False, driver: bool = False) -> int:
        row = self.rows.get(key)
        if row is None:
            row = self._next
            self._next += 1
            self.rows[key] = row
        cell = self.sheet.cell(row=row, column=1, value=label)
        if bold:
            cell.font = self.styles["bold"]
        elif driver:
            cell.font = self.styles["driver"]
        return row



# Первый скрытый столбец «Вводных» под списки вариантов, в подписях которых
# есть запятая (см. `put_input`).
_M2_LIST_COLUMN = 40

def build_plato_model_v2(
    inputs: dict[str, Any],
    tep: dict[str, dict[str, Any]],
    rates: list[dict[str, Any]] | None = None,
    project_name: str = "",
) -> tuple[bytes, dict[str, Any]]:
    """Собрать финансовую модель заново: тринадцать листов, живой расчёт.

    Помесячные драйверы — объёмы продаж, выручка по продуктам, статьи затрат,
    прогноз ключевой ставки, налоговая маржа — записаны значениями: это
    сценарий, и спорить о нём книге незачем. Весь финансовый контур считается
    формулами по методике движка (`simulate_financing`): продажи копятся на
    эскроу до РВЭ; до РнС затраты несёт БРИДЖ; на РнС тело рефинансируется в
    ПФ, а начисленные проценты переносятся; покрытие берётся по эскроу до
    раскрытия и по долгу ПФ после выборки, но до погашения; ставка — взвешенная
    сумма базовой и специальной; погашение идёт раскрытием эскроу на РВЭ и
    продажами после.
    """
    import openpyxl
    import openpyxl.styles
    import openpyxl.worksheet.datavalidation

    inputs = dict(inputs or {})
    migrate_growth_post(inputs)
    result = calculate(CalcRequest(inputs=dict(inputs), tep=dict(tep), rates=list(rates or [])))
    finance = result.get("finance") or {}
    rows = finance.get("rows") or []
    monthly = result.get("monthly") or {}
    if not rows:
        raise HTTPException(status_code=500, detail="Расчёт не дал помесячных строк")

    summary = result.get("summary") or {}
    report = result.get("report") or {}
    dates = result.get("dates") or {}
    permit = d(dates.get("permit"))
    rve = d(dates.get("rve"))
    months = [d(item["month"]) for item in rows]
    span = range(len(months))
    capitalize = str(inputs.get("bridge_interest_mode", "Капитализация в ПФ")) == "Капитализация в ПФ"
    transferred = float(finance.get("transferred_bridge_interest") or 0.0)

    workbook = openpyxl.Workbook()
    ws_in = workbook.active
    ws_in.title = _M2_SHEETS["inputs"]
    sheets = {key: (ws_in if key == "inputs" else workbook.create_sheet(title))
              for key, title in _M2_SHEETS.items()}

    money = "#,##0.0"
    percent = "0.00%"
    ratio = "0.0000"
    area = "#,##0"
    month_fmt = "mmm yyyy"
    styles = {
        "title": openpyxl.styles.Font(bold=True, size=12),
        "bold": openpyxl.styles.Font(bold=True),
        "section": openpyxl.styles.Font(bold=True, color="1F4E79"),
        "driver": openpyxl.styles.Font(color="808080"),
        "month": month_fmt,
    }

    # --- Вводные -----------------------------------------------------------
    # Вводные — это все поля модели, теми же группами, что и на странице: их
    # больше сотни, и урезанный список делал книгу нередактируемой. Проценты
    # хранятся долями, чтобы формулы умножали на них напрямую. Поля выбора
    # получают тот же список вариантов, что и на странице: свободный ввод в
    # ячейке, от которой зависит ветка расчёта, — это опечатка ценой в отчёт.
    ws_in["A1"] = "ВВОДНЫЕ"
    ws_in["A1"].font = styles["title"]
    ws_in["A2"] = "Меняйте колонку B. Серым на помесячных листах помечены графики — они приходят значениями."
    for column, label in ((1, "Параметр"), (2, "Значение"), (3, "Ед. изм.")):
        ws_in.cell(row=4, column=column, value=label).font = styles["bold"]

    key_row: dict[str, int] = {}
    choices: dict[str, list[str]] = {}
    list_columns: list[str] = []

    def options_of(key: str, field: tuple) -> list[list[str]] | None:
        # Пятый элемент поля значит разное: у «select» это варианты парами,
        # у «schedule» — настройки редактора словарём. Разбирать его по типу
        # поля, а не по наличию: словарь настроек, прочитанный как варианты,
        # роняет сборку книги целиком.
        if field[3] == "select" and len(field) > 4 and field[4]:
            return [list(pair) for pair in field[4]]
        return _M2_EXTRA_OPTIONS.get(key)

    def put_input(row: int, key: str, label: str, unit: str, kind: str,
                  options: list[list[str]] | None) -> None:
        ws_in.cell(row=row, column=1, value=label)
        cell = ws_in.cell(row=row, column=2)
        raw = inputs.get(key, DEFAULT_INPUTS.get(key))
        if kind == "number":
            value = n(inputs, key, float(DEFAULT_INPUTS.get(key) or 0.0))
            if unit in ("%", "п.п.") or str(unit).startswith("%"):
                cell.value, cell.number_format = round(value / 100.0, 12), percent
            else:
                cell.value, cell.number_format = round(value, 6), money
        elif kind == "date":
            cell.value = d(raw) if raw else None
            cell.number_format = month_fmt
        elif kind == "checkbox":
            # Да/Нет вместо 1/0: аналитик читает лист, а не расшифровывает его.
            cell.value = "Да" if raw else "Нет"
            options = [["Да", "Да"], ["Нет", "Нет"]]
        elif options:
            # В ячейке — подпись варианта, как на странице; ветки расчёта
            # сравниваются с ней же, поэтому кода в книге нет вовсе.
            labels = {str(value): title for value, title in options}
            cell.value = labels.get(str(raw if raw is not None else ""), str(raw or ""))
        else:
            cell.value = "" if raw is None else str(raw)
        if options:
            titles = [str(title) for _, title in options]
            choices[key] = titles
            formula = '"' + ",".join(titles) + '"'
            if any("," in title for title in titles):
                # Запятая в подписи варианта («Автоматически: до ПФ — БРИДЖ,
                # после — ПФ») резала бы список-строку на лишние пункты: такой
                # список берётся из скрытого столбца того же листа, слова те же.
                column = _M2_LIST_COLUMN + len(list_columns)
                list_columns.append(key)
                letter = openpyxl.utils.get_column_letter(column)
                for index, title in enumerate(titles):
                    ws_in.cell(row=5 + index, column=column, value=title)
                ws_in.column_dimensions[letter].hidden = True
                formula = f"${letter}$5:${letter}${4 + len(titles)}"
            rule = openpyxl.worksheet.datavalidation.DataValidation(
                type="list", formula1=formula, allow_blank=False,
                showDropDown=False, showErrorMessage=True,
                errorTitle="Выберите из списка",
                error="Значение должно быть одним из вариантов, как на странице DevelopAid.",
            )
            ws_in.add_data_validation(rule)
            rule.add(cell)
        if key in _M2_TEMPLATE_ONLY_INPUTS:
            ws_in.cell(row=row, column=1).font = styles["driver"]
            cell.font = styles["driver"]
            ws_in.cell(row=row, column=3,
                       value=f"{unit} · в расчёте не участвует, уходит в шаблон ПЛАТО")
        else:
            ws_in.cell(row=row, column=3, value=unit)
        key_row[key] = row

    row = 5
    for group, fields in FIELD_GROUPS:
        ws_in.cell(row=row, column=1, value=group.upper()).font = styles["section"]
        row += 1
        for field in fields:
            key, label, unit, kind = field[0], field[1], field[2], field[3]
            if key in key_row:
                continue
            put_input(row, key, label, unit, kind, options_of(key, field))
            row += 1
        row += 1

    ws_in.cell(row=row, column=1, value="ПРОГНОЗ КЛЮЧЕВОЙ СТАВКИ").font = styles["section"]
    row += 1
    for key, label, unit, kind in _M2_RATE_INPUTS:
        options = _M2_RATE_SCENARIOS if key == "rate_scenario" else None
        put_input(row, key, label, unit, kind, options)
        row += 1
    row += 1

    ws_in.cell(row=row, column=1, value="РАСЧЁТНЫЕ СРОКИ И ЛИМИТЫ").font = styles["section"]
    row += 1
    # Всё в этом блоке — следствие вводных, а не отдельная вводная: сдвинули
    # срок ИРД, и поехали РнС, график освоения, выборка долга и его стоимость.
    for key, label, unit in (
        ("permit", "РнС (начало проекта + срок ИРД)", ""),
        ("rve", "РВЭ (РнС + срок строительства)", ""),
        ("bridge_limit", "Расчётный лимит БРИДЖ", "млн ₽"),
        ("pf_limit", "Лимит ПФ", "млн ₽"),
        ("bridge_fee", "Комиссия за резервирование БРИДЖ", "млн ₽"),
        ("pf_reservation_fee", "Комиссия за резервирование ПФ", "млн ₽"),
    ):
        ws_in.cell(row=row, column=1, value=label)
        if unit:
            ws_in.cell(row=row, column=3, value=unit)
        key_row[key] = row
        row += 1

    # Ступени ставки ПФ — отдельными числовыми строками, а не только текстом
    # поля выше: текст разбирается при сборке книги, и его правка в Excel
    # ничего не пересчитывает. Эти строки — пересчитывают: помесячные формулы
    # ссылаются на них (владелец, 20.08.2026: «сейчас-то надбавка — это
    # вводная»). Пустой порог выключает ступень.
    _ladder = pf_special_steps(inputs.get("pf_special_steps"))
    if _ladder:
        ws_in.cell(row=row, column=1, value="СТУПЕНИ СТАВКИ ПФ ПО ПОКРЫТИЮ ЭСКРОУ"
                   ).font = styles["section"]
        row += 1
        for index, (edge, rate) in enumerate(_ladder):
            ws_in.cell(row=row, column=1, value=f"Ступень {index + 1} — покрытие от")
            ws_in.cell(row=row, column=2, value=round(edge, 6)).number_format = ratio
            ws_in.cell(row=row, column=3, value="×; пусто — ступень выключена")
            key_row[f"pf_step{index}_edge"] = row
            row += 1
            ws_in.cell(row=row, column=1, value=f"Ступень {index + 1} — ставка")
            ws_in.cell(row=row, column=2, value=round(rate, 8)).number_format = percent
            ws_in.cell(row=row, column=3, value="% годовых")
            key_row[f"pf_step{index}_rate"] = row
            row += 1
        row += 1

    ws_in.cell(row=key_row["permit"], column=2,
               value=f"=EDATE($B${key_row['project_start']},$B${key_row['ird_months']})"
               ).number_format = month_fmt
    ws_in.cell(row=key_row["rve"], column=2,
               value=f"=EDATE($B${key_row['permit']},$B${key_row['construction_months']})"
               ).number_format = month_fmt
    for key, limit_key in (("bridge_fee", "bridge_limit"), ("pf_reservation_fee", "pf_limit")):
        ws_in.cell(row=key_row[key], column=2,
                   value=f"=$B${key_row[limit_key]}*$B${key_row['reservation_fee_pct']}"
                   ).number_format = money
    for key in ("bridge_limit", "pf_limit"):
        ws_in.cell(row=key_row[key], column=2).number_format = money

    ws_in.column_dimensions["A"].width = 56
    ws_in.column_dimensions["B"].width = 20
    ws_in.column_dimensions["C"].width = 44

    def ref(key: str) -> str:
        return f"{_M2_SHEETS['inputs']}!$B${key_row[key]}"

    # Режим переноса процентов БРИДЖа — не флаг 1/0, а тот же выбор, что на
    # странице: книга сравнивает ячейку с подписью варианта.
    capitalized = f'({ref("bridge_interest_mode")}="Капитализация в ПФ")'

    # --- ТЭП ---------------------------------------------------------------
    ws_tep = sheets["tep"]
    ws_tep["A1"] = "ТЕХНИКО-ЭКОНОМИЧЕСКИЕ ПОКАЗАТЕЛИ"
    ws_tep["A1"].font = styles["title"]
    ws_tep["A2"] = "Площади — исходные данные проекта. Всё, что ниже, книга считает от них."
    headers = ["Продукт", "ГНС, м²", "Общая площадь, м²", "Полезная, м²",
               "Продаваемая, м²", f"{TRANSFER_WORD}, м²", "Единиц",
               "Гостевых, ед.", "Продаётся, ед."]
    for column, label in enumerate(headers, start=1):
        ws_tep.cell(row=4, column=column, value=label).font = styles["bold"]
    tep_rows = (result.get("tep") or {}).get("rows") or []
    tep_row_of: dict[str, int] = {}
    for offset, item in enumerate(tep_rows):
        line = 5 + offset
        tep_row_of[str(item.get("key"))] = line
        ws_tep.cell(row=line, column=1, value=item.get("label"))
        for column, key in enumerate(
                ("gns", "total_area", "useful", "saleable", "transfer", "units",
                 "guest_units"), start=2):
            ws_tep.cell(row=line, column=column,
                        value=round(float(item.get(key) or 0.0), 6)).number_format = area
        # Продаётся — то, что остаётся за вычетом гостевых: правка мест на этой
        # же строке сразу двигает объём продаж, а не оставляет выгруженное число.
        # У соцобъектов колонка G — мощность учреждения, не продаваемые
        # единицы. Формула G-H для школы превращала 1 000 мест в 1 000
        # «продаж» прямо в выгруженной книге.
        sold_value = (0 if item.get("key") in SOCIAL_TEP_FIELDS
                      else f"=G{line}-H{line}")
        ws_tep.cell(row=line, column=9, value=sold_value).number_format = area
    total_line = 5 + len(tep_rows)
    ws_tep.cell(row=total_line, column=1, value="ИТОГО").font = styles["bold"]
    for column in range(2, 10):
        letter = get_column_letter(column)
        cell = ws_tep.cell(row=total_line, column=column,
                           value=f"=SUM({letter}5:{letter}{total_line - 1})")
        cell.number_format = area
        cell.font = styles["bold"]

    # Базы для удельных ставок: наземная и подземная ГНС основных продуктов.
    # Отдельные объекты КРТ считаются по своим ставкам и в базу не входят.
    # Кладовые лежат на подземном этаже гаража — в наземную площадь они не
    # входят. Книга считала их наземными, движок подземными: одна методика в
    # двух местах, и расходились они молча, пока площадь кладовых была нулём.
    core_above_keys = ("apartments", "ground_commercial")
    core_under_keys = underground_products(inputs)
    base_line = total_line + 2
    ws_tep.cell(row=base_line, column=1, value="БАЗЫ ДЛЯ УДЕЛЬНЫХ СТАВОК").font = styles["section"]
    tep_base: dict[str, int] = {}
    above = "+".join(f"B{tep_row_of[key]}" for key in core_above_keys if key in tep_row_of) or "0"
    under = "+".join(f"B{tep_row_of[key]}" for key in core_under_keys if key in tep_row_of) or "0"
    for offset, (key, label, formula) in enumerate((
        ("core_above_gns", "Наземная площадь (ГНС), м²", f"={above}"),
        ("core_under_gns", "Подземная площадь, м²", f"={under}"),
        ("core_total_gns", CORE_TOTAL_AREA.with_unit(), f"=B{base_line + 1}+B{base_line + 2}"),
        # Благоустраивают двор, а не дом: у статьи своя физическая база.
        # Считается она формулой от площади квартир — правка ТЭП прямо в книге
        # двигает и площадь двора, как в движке. Норматив населения книге не
        # сосчитать (он региональный) и приезжает числом с подписью.
        ("landscaping_sqm", "Площадь благоустройства, м²",
         "=IF({given}>0,{given},ROUNDUP({flats}/{per_person_pop},0)*{per_person_area})".format(
             given=ref("landscaping_area_sqm"),
             flats=f"E{tep_row_of['apartments']}" if "apartments" in tep_row_of else "0",
             per_person_pop=f"{_PARKING_2118_SQM_PER_PERSON:g}",
             per_person_area=ref("landscaping_area_per_person_sqm"))),
    )):
        line = base_line + 1 + offset
        ws_tep.cell(row=line, column=1, value=label).font = styles["bold"]
        ws_tep.cell(row=line, column=2, value=formula).number_format = area
        tep_base[key] = line

    ws_tep.column_dimensions["A"].width = 32
    for column in range(2, 10):
        ws_tep.column_dimensions[get_column_letter(column)].width = 20

    def tep_ref(key: str) -> str:
        return f"{_M2_SHEETS['tep']}!$B${tep_base[key]}"

    def tep_cell(product: str, column: int) -> str:
        return f"{_M2_SHEETS['tep']}!${get_column_letter(column)}${tep_row_of[product]}"

    # --- СРОКИ -------------------------------------------------------------
    ws_dates = sheets["schedule"]
    ws_dates["A1"] = "КАЛЕНДАРЬ ПРОЕКТА"
    ws_dates["A1"].font = styles["title"]
    for column, label in enumerate(("Этап", "Группа", "Начало", "Окончание", "Месяцев"), start=1):
        ws_dates.cell(row=3, column=column, value=label).font = styles["bold"]
    events = ((report.get("calendar") or {}).get("events")) or []
    for offset, event in enumerate(events):
        line = 4 + offset
        ws_dates.cell(row=line, column=1, value=event.get("label"))
        ws_dates.cell(row=line, column=2, value=event.get("group"))
        ws_dates.cell(row=line, column=3, value=d(event.get("start"))).number_format = month_fmt
        ws_dates.cell(row=line, column=4, value=d(event.get("end"))).number_format = month_fmt
        # Длительность считает книга: правка даты сразу видна в сроке.
        ws_dates.cell(row=line, column=5,
                      value=f"=(YEAR(D{line})-YEAR(C{line}))*12+MONTH(D{line})-MONTH(C{line})+1")
    ws_dates.column_dimensions["A"].width = 34
    ws_dates.column_dimensions["B"].width = 22
    for column in ("C", "D", "E"):
        ws_dates.column_dimensions[column].width = 14

    # --- ПРОДАЖИ -----------------------------------------------------------
    # Здесь не осталось выгруженных чисел. Объём — база из ТЭП, разложенная по
    # весам месяцев; веса складываются из сезонности и смещения темпа к поздним
    # месяцам и нормируются отдельно до и после РВЭ, поэтому доля продаж до РВЭ
    # остаётся ровно заданной. Цена растёт своим темпом до РВЭ и своим после.
    # Ровно так же это считает движок — `sales_weights` и `sales_schedule`.
    sales = _MonthGrid(sheets["sales"], months, styles, title="ПРОДАЖИ")
    labels = {str(item["key"]): item for item in (monthly.get("quantity") or [])}
    products: list[tuple[str, dict[str, Any]]] = []
    for key, spec in _M2_PRODUCTS.items():
        # Основные продукты стоят всегда: нулевая площадь на «ТЭП» сама даёт
        # нулевые продажи. Объекты КРТ появляются, только когда включены, —
        # иначе книга посчитала бы их по вводным, а движок держит нули.
        if not spec["core"] and key not in labels:
            continue
        item = labels.get(key) or {
            "key": key, "label": (TEP_DEFAULT.get(key) or {}).get("label") or key}
        products.append((key, item))

    sales_layout: list[str | tuple[str, str]] = []
    for key, item in products:
        sales_layout += [
            ("section", item.get("label") or key),
            f"season_{key}", f"index_{key}", f"post_index_{key}",
            f"wpre_{key}", f"wpost_{key}", f"weight_{key}",
            f"quantity_{key}", f"price_{key}", f"revenue_{key}",
        ]
    sales_layout += [("section", "Итого"), "quantity_total", "revenue", "revenue_cum"]
    sales.layout(*sales_layout)

    # Параметры продаж — отдельным блоком под сеткой: объём, стартовая цена,
    # окно продаж, доля до РВЭ, темпы роста, сезонность и смещение темпа.
    param_line = sales._next + 2
    sheets["sales"].cell(row=param_line, column=1, value="ПАРАМЕТРЫ ПРОДАЖ").font = styles["section"]
    param_line += 1
    for column, label in enumerate((
            "Продукт", "Ед.", "Объём", "Стартовая цена, млн ₽/ед.", "Старт продаж",
            "Окончание (РВЭ продукта)", "Месяцев до РВЭ", "Остаточных месяцев",
            "Доля до РВЭ", "Рост цены до РВЭ", "Рост цены после РВЭ",
            "Сезонное снижение", "Смещение темпа"), start=1):
        sheets["sales"].cell(row=param_line, column=column, value=label).font = styles["bold"]
    param_row = {key: param_line + 1 + offset for offset, (key, _) in enumerate(products)}

    for key, item in products:
        spec = _M2_PRODUCTS[key]
        line = param_row[key]
        base = (tep_cell(key, spec["base_column"]) if spec.get("base_column")
                else ref(spec["base_input"]))
        if spec["core"]:
            start = f"=EDATE({ref('permit')},{ref('sales_lag_months')})"
            finish = f"={ref('rve')}"
            seasonal = f"={ref('seasonal_reduction_pct')}"
            pace = f"={ref('pace_adjustment_pct')}"
        else:
            start = f"={ref(spec['sales_start'])}"
            finish = f"=EDATE({ref(spec['build_start'])},{ref(spec['build_months'])})"
            seasonal, pace = "=0", "=0"
        for column, value, fmt in (
            (1, item.get("label") or key, None),
            (2, spec["unit"], None),
            (3, f"={base}", area),
            (4, f"={ref(spec['price'])}*{spec['scale']}", ratio),
            (5, start, month_fmt),
            (6, finish, month_fmt),
            (7, f"=MAX(1,(YEAR(F{line})-YEAR(E{line}))*12+MONTH(F{line})-MONTH(E{line}))", "0"),
            (8, f"={ref(spec['residual'])}", "0"),
            (9, f"={ref(spec['share'])}", percent),
            (10, f"={ref(spec['growth_pre'])}", percent),
            # Основным продуктам рост после РВЭ даёт годовая инфляция — одна
            # вводная (решение владельца, 15.10.2026), в месяц сложным ростом.
            (11, (f"=(1+{ref('inflation_after_rve_pct')})^(1/12)-1"
                  if spec["growth_post"] is None else f"={ref(spec['growth_post'])}"),
             percent),
            (12, seasonal, percent),
            (13, pace, percent),
        ):
            cell = sheets["sales"].cell(row=line, column=column, value=value)
            if fmt:
                cell.number_format = fmt

    def par(key: str, column: str) -> str:
        return f"${column}${param_row[key]}"

    low_season = ",".join(f"MONTH({{month}})={value}" for value in _M2_SEASONAL_LOW_MONTHS)

    for key, item in products:
        sales.formula(
            f"season_{key}", "Сезонный коэффициент",
            lambda i, key=key: (
                f"=IF(OR({low_season.format(month=sales.month(i))}),1+{par(key, 'L')},1)"), ratio)
        sales.formula(
            f"index_{key}", "№ месяца от старта продаж",
            lambda i, key=key: (
                f"=(YEAR({sales.month(i)})-YEAR({par(key, 'E')}))*12"
                f"+MONTH({sales.month(i)})-MONTH({par(key, 'E')})"), "0")
        sales.formula(
            f"post_index_{key}", "№ месяца от РВЭ",
            lambda i, key=key: (
                f"=(YEAR({sales.month(i)})-YEAR({par(key, 'F')}))*12"
                f"+MONTH({sales.month(i)})-MONTH({par(key, 'F')})"), "0")
        # Смещение темпа нарастает линейно от старта продаж и действует только
        # до РВЭ; сезонность — на всём сроке продаж.
        sales.formula(
            f"wpre_{key}", "Вес месяца до РВЭ",
            lambda i, key=key: (
                f"=IF(AND({sales.month(i)}>={par(key, 'E')},{sales.month(i)}<{par(key, 'F')}),"
                f"{sales.at(f'season_{key}', i)}"
                f"*(1+{par(key, 'M')}*MIN(1,{sales.at(f'index_{key}', i)}/{par(key, 'G')})),0)"),
            ratio)
        sales.formula(
            f"wpost_{key}", "Вес месяца после РВЭ",
            lambda i, key=key: (
                f"=IF(AND({sales.month(i)}>={par(key, 'F')},"
                f"{sales.at(f'post_index_{key}', i)}<{par(key, 'H')}),"
                f"{sales.at(f'season_{key}', i)},0)"), ratio)
        # Веса нормируются отдельно до и после РВЭ — иначе заданная доля продаж
        # до РВЭ поплывёт вслед за сезонностью.
        sales.formula(
            f"weight_{key}", "Доля периода в объёме",
            lambda i, key=key: (
                f"=IFERROR({par(key, 'I')}*{sales.at(f'wpre_{key}', i)}"
                f"/SUM({sales.span(f'wpre_{key}')}),0)"
                f"+IFERROR((1-{par(key, 'I')})*{sales.at(f'wpost_{key}', i)}"
                f"/SUM({sales.span(f'wpost_{key}')}),0)"), percent)
        sales.formula(
            f"quantity_{key}", f"Объём продаж, {_M2_PRODUCTS[key]['unit']}",
            lambda i, key=key: f"={par(key, 'C')}*{sales.at(f'weight_{key}', i)}", area)
        sales.formula(
            f"price_{key}", "Цена, млн ₽ за единицу",
            lambda i, key=key: (
                f"=IF({sales.month(i)}<{par(key, 'F')},"
                f"{par(key, 'D')}*(1+{par(key, 'J')})^{sales.at(f'index_{key}', i)},"
                f"{par(key, 'D')}*(1+{par(key, 'J')})^{par(key, 'G')}"
                f"*(1+{par(key, 'K')})^{sales.at(f'post_index_{key}', i)})"), ratio)
        sales.formula(
            f"revenue_{key}", "Выручка, млн ₽",
            lambda i, key=key: (
                f"={sales.at(f'quantity_{key}', i)}*{sales.at(f'price_{key}', i)}"),
            money, bold=True)

    quantity_keys = [f"quantity_{key}" for key, _ in products]
    revenue_keys = [f"revenue_{key}" for key, _ in products]
    sales.formula("quantity_total", "Объём продаж, всего",
                  lambda i: "=" + ("+".join(sales.at(k, i) for k in quantity_keys) or "0"), area)
    sales.formula("revenue", "Выручка, всего",
                  lambda i: "=" + ("+".join(sales.at(k, i) for k in revenue_keys) or "0"),
                  money, bold=True)
    sales.formula("revenue_cum", "Выручка нарастающим",
                  lambda i: f"={sales.before('revenue_cum', i)}+{sales.at('revenue', i)}", money)

    line = param_line + len(products) + 2
    sheets["sales"].cell(row=line, column=1, value="ИТОГИ ПО ПРОДУКТАМ").font = styles["section"]
    line += 1
    for column, label in enumerate(
            ("Продукт", "Объём", "Выручка, млн ₽", "Средняя цена, млн ₽/ед."), start=1):
        sheets["sales"].cell(row=line, column=column, value=label).font = styles["bold"]
    for offset, (key, item) in enumerate(products):
        current = line + 1 + offset
        sheets["sales"].cell(row=current, column=1, value=item.get("label") or key)
        sheets["sales"].cell(row=current, column=2,
                             value=f"=SUM({sales.span(f'quantity_{key}')})").number_format = area
        sheets["sales"].cell(row=current, column=3,
                             value=f"=SUM({sales.span(f'revenue_{key}')})").number_format = money
        sheets["sales"].cell(row=current, column=4,
                             value=f"=IFERROR(C{current}/B{current},0)").number_format = ratio
    for column in range(2, 14):
        sheets["sales"].column_dimensions[get_column_letter(column)].width = 15

    # --- СЕБЕСТОИМОСТЬ -----------------------------------------------------
    # Статья считается как ставка × база, а по месяцам раскладывается ровно по
    # окну освоения — так же, как это делает движок. Ставку правят на
    # «Вводных», базу — на «ТЭП», окно — в блоке калькуляции под сеткой.
    costs = _MonthGrid(sheets["costs"], months, styles, title="СЕБЕСТОИМОСТЬ · млн ₽")
    cost_rows = {item["key"]: item for item in (monthly.get("costs") or [])}
    articles = [(key, label) for key, label, computed in _M2_COST_ARTICLES
                if computed or key in cost_rows]
    computed_keys = {key for key, _, computed in _M2_COST_ARTICLES if computed}
    cost_keys = [f"cost_{key}" for key, _ in articles]
    costs.layout("index", ("section", "Инвестиционные затраты"), *cost_keys, "capex",
                 ("section", "Операционные затраты"), "operating", "total", "total_cum",
                 ("section", "Потребность в долге"), "debt", "own")
    costs.formula("index", "№ месяца от старта проекта",
                  lambda i: (f"=(YEAR({costs.month(i)})-YEAR({ref('project_start')}))*12"
                             f"+MONTH({costs.month(i)})-MONTH({ref('project_start')})+1"), "0")

    # Блок калькуляции под сеткой: сумма статьи, окно освоения и его номер.
    calc_line = costs._next + 2
    sheets["costs"].cell(row=calc_line, column=1, value="КАЛЬКУЛЯЦИЯ СТАТЕЙ").font = styles["section"]
    calc_line += 1
    for column, label in enumerate(
            ("Статья", "Сумма, млн ₽", "Старт освоения", "Месяцев", "№ месяца старта"), start=1):
        sheets["costs"].cell(row=calc_line, column=column, value=label).font = styles["bold"]
    calc_row = {key: calc_line + 1 + offset for offset, (key, _) in enumerate(articles)}

    def amount(key: str) -> str:
        return f"$B${calc_row[key]}"

    last_column = sales.letter(len(months) - 1)

    def monthly_sum(row_key: str) -> str:
        line = costs.rows[row_key]
        return f"SUM(B{line}:{last_column}{line})"

    # Окна освоения — те же, что в движке: ИРД от старта проекта, проектирование
    # и подготовка прижаты к РнС, стройка идёт весь срок строительства,
    # благоустройство и ввод — последние три месяца до РВЭ.
    design_window = f"MIN(6,{ref('ird_months')})"
    to_permit = f"EDATE({ref('permit')},-{design_window})"
    before_rve = f"EDATE({ref('rve')},-3)"
    build_months = ref("construction_months")
    # База генподряда и техзаказчика — как в движке: СМР ядра и соцобъектов.
    # Ставка объекта «под ключ», процент на неё не начисляется.
    works = "+".join(amount(key) for key in
                     ("main_above", "main_under", "social") if key in calc_row) or "0"

    def unit_rate(rate_key: str, base_key: str) -> str:
        return f"={tep_ref(base_key)}*{ref(rate_key)}/1000"

    plan: dict[str, tuple[str, str, str]] = {
        # Стоимость сделки — цена участка и выкуп ЗУ/ОКС у третьих лиц.
        "purchase": (f"={ref('purchase_price_mln')}+{ref('land_buyout_mln')}",
                     f"={ref('project_start')}", "=1"),
        "ird": (unit_rate("ird_th_per_sqm", "core_total_gns"),
                f"={ref('project_start')}", f"={ref('ird_months')}"),
        "design_p": (unit_rate("design_p_th_per_sqm", "core_total_gns"),
                     f"={to_permit}", f"={design_window}"),
        "design_rd": (unit_rate("design_rd_th_per_sqm", "core_total_gns"),
                      f"={to_permit}", f"={design_window}"),
        "preparation": (unit_rate("preparation_th_per_sqm", "core_total_gns"),
                        f"={to_permit}", f"={design_window}"),
        "main_above": (unit_rate("main_above_th_per_sqm", "core_above_gns"),
                       f"={ref('permit')}", f"={build_months}"),
        "main_under": (unit_rate("main_under_th_per_sqm", "core_under_gns"),
                       f"={ref('permit')}", f"={build_months}"),
        "utilities": (unit_rate("utilities_th_per_sqm", "core_total_gns"),
                      f"={ref('permit')}", f"={build_months}"),
        "site_maintenance": (unit_rate("site_maintenance_th_per_sqm", "core_total_gns"),
                             f"={ref('permit')}", f"={build_months}"),
        "landscaping": (unit_rate("landscaping_th_per_sqm", "landscaping_sqm"),
                        f"={before_rve}", "=3"),
        "commissioning": (unit_rate("commissioning_th_per_sqm", "core_total_gns"),
                          f"={before_rve}", "=3"),
        "author_supervision": (
            f"=({amount('design_p')}+{amount('design_rd')})*{ref('author_supervision_pct')}"
            if "design_p" in calc_row else "=0",
            f"={ref('permit')}", f"={build_months}"),
        "technical_supervision": (f"=({works})*{ref('technical_supervision_pct')}",
                                  f"={ref('permit')}", f"={build_months}"),
        "gc_fee": (f"=({works})*{ref('gc_fee_pct')}", f"={ref('permit')}", f"={build_months}"),
    }
    # Управление проектом не имеет собственного окна: оно идёт за расходами,
    # которыми вызвано, — процент от прямых затрат каждого месяца, как в
    # движке. Сумма статьи в калькуляции — итог этого ряда.
    management_profile_keys = [key for key in MANAGEMENT_PROFILE_ARTICLES if key in calc_row]

    for key, label in articles:
        line = calc_row[key]
        sheets["costs"].cell(row=line, column=1, value=label)
        if key == "reserve":
            # Резерв — процент от прочих статей и потому считается последним.
            # Цена входа и стоимость рассрочки ВРИ в его базу не входят: в
            # движке их нет в наборе, от которого берётся процент, и лишние
            # 700 млн ₽ покупки дали бы 35 млн ₽ резерва из ниоткуда.
            others = "+".join(amount(other) for other, _ in articles
                              if other not in _M2_RESERVE_EXCLUDED)
            formula = f"=({others})*{ref('reserve_pct')}"
            start, length = f"={ref('permit')}", f"={build_months}"
        elif key in plan:
            formula, start, length = plan[key]
        else:
            # Плата за ВРИ и соцнагрузка идут по собственным графикам: рассрочка
            # на своём листе и три объекта со своими сроками. Сумма — итог ряда.
            formula = f"={monthly_sum(f'cost_{key}')}"
            start, length = "", ""
        sheets["costs"].cell(row=line, column=2, value=formula).number_format = money
        if start:
            sheets["costs"].cell(row=line, column=3, value=start).number_format = month_fmt
            sheets["costs"].cell(row=line, column=4, value=length).number_format = "0"
            sheets["costs"].cell(
                row=line, column=5,
                value=f"=(YEAR(C{line})-YEAR({ref('project_start')}))*12"
                      f"+MONTH(C{line})-MONTH({ref('project_start')})+1").number_format = "0"

    # Стройка идёт S-кривой движка, а не равномерным окном. Профиль месяца —
    # доля из фактического движкового ряда (числом), сумма статьи — живая
    # формула калькуляции: ставку правят на «Вводных», профиль остаётся.
    s_curve_keys = {"main_above", "main_under", "utilities", "site_maintenance",
                    "author_supervision", "technical_supervision", "gc_fee", "reserve"}

    def s_profile(key: str) -> list[float]:
        values = [float(v or 0) for v in ((cost_rows.get(key) or {}).get("values") or [])]
        total = sum(values)
        return [v / total for v in values] if total else []

    for key, label in articles:
        row_key = f"cost_{key}"
        if key == "project_management" and key in computed_keys:
            costs.formula(row_key, label,
                          lambda i: ("=(" + "+".join(
                              costs.at(f"cost_{k}", i) for k in management_profile_keys)
                              + f")*{ref('project_management_pct')}"), money)
        elif key in s_curve_keys and key in computed_keys:
            profile = s_profile(key)
            costs.formula(row_key, label,
                          lambda i, profile=profile, key=key: (
                              f"={amount(key)}*{profile[i]:.12f}"
                              if i < len(profile) and profile[i] else "=0"), money)
        elif key in computed_keys:
            line = calc_row[key]
            costs.formula(row_key, label,
                          lambda i, line=line: (
                              f"=IF(AND({costs.at('index', i)}>=$E${line},"
                              f"{costs.at('index', i)}<$E${line}+$D${line}),"
                              f"$B${line}/MAX($D${line},1),0)"), money)
        else:
            item = cost_rows.get(key) or {}
            costs.values(row_key, f"{label} · свой график",
                         [v / 1e6 for v in (item.get("values") or [])], money)

    costs.formula("capex", "CAPEX, всего",
                  lambda i: "=" + "+".join(costs.at(key, i) for key in cost_keys), money, bold=True)
    # Маркетинг и продажи — процент от выручки, а не отдельный ряд чисел.
    costs.formula("operating", "Маркетинг, продажи и содержание",
                  lambda i: (f"={sales.outside('revenue', i)}"
                             f"*({ref('marketing_pct')}+{ref('selling_pct')})"), money)
    costs.formula("total", "Расходы, всего",
                  lambda i: f"={costs.at('capex', i)}+{costs.at('operating', i)}", money, bold=True)
    costs.formula("total_cum", "Расходы нарастающим",
                  lambda i: f"={costs.before('total_cum', i)}+{costs.at('total', i)}", money)

    # Не все расходы финансируются банком: денежная компенсация соцобъектов и
    # плата за ВРИ вне банковского бюджета оплачиваются своими деньгами.
    # Движок в режиме «проценты в тело ПФ» дописывает перенос в затраты месяца
    # РнС — здесь он снимается, книга добавит его сама на «КРЕДИТОВАНИИ».
    debt_costs = []
    for item in rows:
        value = float(item.get("project_costs") or 0.0)
        if not capitalize and d(item["month"]) == permit:
            value -= transferred
        debt_costs.append(value / 1e6)
    costs.values("debt", "Затраты, финансируемые долгом", debt_costs, money)
    costs.formula("own", "Оплачивается своими деньгами",
                  lambda i: f"={costs.at('total', i)}-{costs.at('debt', i)}", money)

    # Расчётный лимит БРИДЖ — цена входа и проектирование, а при денежной
    # компенсации соцобъектов ещё и она: до РнС эти расходы несёт БРИДЖ.
    def cost_amount(key: str) -> str:
        return f"{_M2_SHEETS['costs']}!{amount(key)}"

    # БРИДЖем банк считает то, что существует ДО РнС (владелец, 04.09.2026):
    # при рассрочке покупки часть платежей приходится на период после РнС, и
    # её финансирует уже ПФ. Книга поэтому суммирует не итог статьи, а её
    # помесячные ячейки до месяца РнС — той же методикой, что движок.
    _permit_ref = f"EDATE({ref('project_start')},{ref('ird_months')})"
    _last_month = costs.letter(len(months) - 1)

    def before_permit(key: str) -> str:
        # Диапазоны обязаны нести имя листа: формула живёт на «Вводных», а
        # строки статей — на листе себестоимости. Без префикса SUMIF считал бы
        # соседние ячейки своего листа и падал на подписи «млн ₽».
        line = costs.rows[f"cost_{key}"]
        sheet = _M2_SHEETS["costs"]
        head = f"{sheet}!$B${costs.MONTH_ROW}:${_last_month}${costs.MONTH_ROW}"
        body = f"{sheet}!$B${line}:${_last_month}${line}"
        return f'SUMIF({head},"<"&{_permit_ref},{body})'

    bridge_parts = "+".join(before_permit(key) for key in ("purchase", "design_p", "design_rd")
                            if f"cost_{key}" in costs.rows) or "0"
    social_part = (f'+IF({ref("social_mode")}="Денежная компенсация",{before_permit("social")},0)'
                   if "cost_social" in costs.rows else "")
    ws_in.cell(row=key_row["bridge_limit"], column=2, value=f"={bridge_parts}{social_part}")

    line = max(costs._next, calc_line + len(articles) + 1) + 2
    sheets["costs"].cell(row=line, column=1, value="СТРУКТУРА РАСХОДОВ").font = styles["section"]
    line += 1
    for column, label in enumerate(("Статья", "Сумма, млн ₽", "Доля"), start=1):
        sheets["costs"].cell(row=line, column=column, value=label).font = styles["bold"]
    structure = report.get("expense_structure") or []
    for offset, item in enumerate(structure):
        current = line + 1 + offset
        sheets["costs"].cell(row=current, column=1, value=item.get("label"))
        sheets["costs"].cell(row=current, column=2,
                             value=round(float(item.get("value") or 0.0) / 1e6, 3)).number_format = money
        sheets["costs"].cell(
            row=current, column=3,
            value=f"=IFERROR(B{current}/SUM($B${line + 1}:$B${line + len(structure)}),0)",
        ).number_format = percent
    sheets["costs"].column_dimensions["B"].width = 16
    for column in ("C", "D", "E"):
        sheets["costs"].column_dimensions[column].width = 16

    # --- СТАВКИ ------------------------------------------------------------
    rate_grid = _MonthGrid(sheets["rates"], months, styles, title="СТАВКИ")
    rate_grid.layout("key_rate",
                     ("section", "БРИДЖ"), "bridge_spread", "bridge",
                     "bridge_cap_spread", "bridge_cap",
                     ("section", "Проектное финансирование"), "pf_spread", "pf_base", "pf_special")
    # Прогноз ключевой ставки собирается формулой, как в движке: плавный выход
    # на цель сценария за срок нормализации, форма кривой задаётся показателем.
    horizon = f"MAX(1,{ref('rate_normalization_months')})"
    shape = f"MAX(0.05,{ref('rate_curve_shape')})"
    target = (f'IF({ref("rate_scenario")}="Консервативный",{ref("rate_target_high_pct")},'
              f'IF({ref("rate_scenario")}="Оптимистичный",{ref("rate_target_low_pct")},'
              f'{ref("rate_target_base_pct")}))')
    rate_grid.layout("months_from_start", "progress")
    # Ряд прогноза начинается в дату стартовой ставки, а месяцы модели — первого
    # числа: пока не наступило то же число, действует ставка предыдущего шага.
    rate_grid.formula(
        "months_from_start", "Месяцев от даты стартовой ставки",
        lambda i: (f"=MAX(0,(YEAR({rate_grid.month(i)})-YEAR({ref('rate_start_date')}))*12"
                   f"+MONTH({rate_grid.month(i)})-MONTH({ref('rate_start_date')})"
                   f"-IF(DAY({ref('rate_start_date')})>1,1,0))"), "0")
    rate_grid.formula(
        "progress", "Пройдено до цели",
        lambda i: (f"=IF({rate_grid.at('months_from_start', i)}>={horizon},1,"
                   f"(1-EXP(-{shape}*{rate_grid.at('months_from_start', i)}/{horizon}))"
                   f"/(1-EXP(-{shape})))"), percent)
    rate_grid.formula(
        "key_rate", "Ключевая ставка (прогноз)",
        lambda i: (f"={ref('rate_start_pct')}+({target}-{ref('rate_start_pct')})"
                   f"*{rate_grid.at('progress', i)}"), percent, bold=True)
    rate_grid.formula("bridge_spread", "Спред БРИДЖ", lambda i: f"={ref('bridge_spread_pp')}", percent)
    rate_grid.formula("bridge", "Ставка БРИДЖ",
                      lambda i: f"={rate_grid.at('key_rate', i)}+{rate_grid.at('bridge_spread', i)}",
                      percent, bold=True)
    rate_grid.formula("bridge_cap_spread", "Спред капитализации",
                      lambda i: f"={ref('bridge_cap_spread_pp')}", percent)
    rate_grid.formula("bridge_cap", "Ставка капитализации БРИДЖ",
                      lambda i: f"={rate_grid.at('key_rate', i)}+{rate_grid.at('bridge_cap_spread', i)}",
                      percent)
    rate_grid.formula("pf_spread", "Спред ПФ", lambda i: f"={ref('pf_spread_pp')}", percent)
    rate_grid.formula("pf_base", "Базовая ставка ПФ",
                      lambda i: f"={rate_grid.at('key_rate', i)}+{rate_grid.at('pf_spread', i)}",
                      percent, bold=True)
    rate_grid.formula("pf_special", "Ставка при покрытии эскроу 1×",
                      lambda i: f"={ref('pf_special_pct')}", percent, bold=True)

    # --- ЭСКРОУ ------------------------------------------------------------
    escrow = _MonthGrid(sheets["escrow"], months, styles, title="ЭСКРОУ · млн ₽")
    escrow.layout("sales", "inflow", "release", "balance", "free_sales")
    escrow.formula("sales", "Поступления от продаж",
                   lambda i: f"={sales.outside('revenue', i)}", money)
    escrow.formula("inflow", "Зачисление на эскроу (до РВЭ)",
                   lambda i: f"=IF({escrow.month(i)}<{ref('rve')},{escrow.at('sales', i)},0)", money)
    escrow.formula("release", "Раскрытие эскроу на РВЭ",
                   lambda i: (f"=IF({escrow.month(i)}={ref('rve')},"
                              f"{escrow.before('balance', i)}+{escrow.at('inflow', i)},0)"), money)
    escrow.formula("balance", "Остаток на счетах эскроу",
                   lambda i: (f"={escrow.before('balance', i)}+{escrow.at('inflow', i)}"
                              f"-{escrow.at('release', i)}"), money, bold=True)
    escrow.formula("free_sales", "Продажи после РВЭ (мимо эскроу)",
                   lambda i: f"=IF({escrow.month(i)}>{ref('rve')},{escrow.at('sales', i)},0)", money)

    # --- КРЕДИТОВАНИЕ ------------------------------------------------------
    credit = _MonthGrid(sheets["credit"], months, styles, title="КРЕДИТОВАНИЕ · млн ₽")
    credit.layout(
        ("section", "БРИДЖ"), "bridge_rate", "bridge_cap_rate", "bridge_draw", "bridge_gross",
        "bridge_refinance", "bridge_balance", "bridge_interest", "bridge_cap",
        "bridge_transfer", "bridge_payable",
        ("section", "Проектное финансирование"), "pf_draw", "pf_gross", "pf_repayment",
        "pf_balance", "rve_unpaid", "coverage", "pf_base_rate", "pf_special_rate", "pf_rate",
        "pf_interest", "pf_cap", "limit_fee", "interest_payment", "pf_payable",
        ("section", "Итого стоимость долга"), "fees", "cost")
    credit.formula("bridge_rate", "Ставка", lambda i: f"={rate_grid.outside('bridge', i)}", percent)
    credit.formula("bridge_cap_rate", "Ставка капитализации",
                   lambda i: f"={rate_grid.outside('bridge_cap', i)}", percent)
    credit.formula("bridge_draw", "Выборка (затраты до РнС)",
                   lambda i: (f"=IF({credit.month(i)}<{ref('permit')},"
                              f"MAX({costs.outside('debt', i)},0),0)"), money)
    credit.formula("bridge_gross", "Долг до рефинансирования",
                   lambda i: f"={credit.before('bridge_balance', i)}+{credit.at('bridge_draw', i)}", money)
    credit.formula("bridge_refinance", "Рефинансирование тела в ПФ на РнС",
                   lambda i: (f"=IF({credit.month(i)}={ref('permit')},"
                              f"{credit.at('bridge_gross', i)},0)"), money)
    credit.formula("bridge_balance", "Остаток БРИДЖ",
                   lambda i: f"={credit.at('bridge_gross', i)}-{credit.at('bridge_refinance', i)}",
                   money, bold=True)

    def bridge_accrues(index: int) -> str:
        return (f"AND({credit.month(index)}<{ref('permit')},"
                f"{credit.at('bridge_gross', index)}>0)")

    credit.formula("bridge_interest", "Проценты начисленные",
                   lambda i: (f"=IF({bridge_accrues(i)},{credit.at('bridge_gross', i)}"
                              f"*{credit.at('bridge_rate', i)}/12,0)"), money)
    credit.formula("bridge_cap", "Капитализация процентов",
                   lambda i: (f"=IF({bridge_accrues(i)},{credit.before('bridge_payable', i)}"
                              f"*{credit.at('bridge_cap_rate', i)}/12,0)"), money)

    def bridge_accrued(index: int) -> str:
        return (f"{credit.before('bridge_payable', index)}+{credit.at('bridge_interest', index)}"
                f"+{credit.at('bridge_cap', index)}")

    credit.formula("bridge_transfer", "Перенос процентов на РнС",
                   lambda i: f"=IF({credit.month(i)}={ref('permit')},{bridge_accrued(i)},0)", money)
    credit.formula("bridge_payable", "Начисленные проценты, остаток",
                   lambda i: f"={bridge_accrued(i)}-{credit.at('bridge_transfer', i)}", money)

    # Линия, рассчитавшаяся в РВЭ, после него не кредитует: долг погашен
    # раскрытием целиком — расходы остаточного периода платит касса, а не
    # закрытый НКЛ. Остался долг в РВЭ — прежнее допущение, линия обслуживается
    # продажами дальше. Признак — нехватка в РВЭ по ПРЕДЫДУЩИЕ месяцы, а не
    # итог строки: итог включал бы этот месяц и дал круг (как в v4).
    def unpaid_seen(index: int) -> str:
        if index == 0:
            return "0"
        return f"SUM({credit.letter(0)}{credit.rows['rve_unpaid']}:{credit.letter(index - 1)}{credit.rows['rve_unpaid']})"

    credit.formula("pf_draw", "Выборка",
                   lambda i: (f"=IF(AND({credit.month(i)}>={ref('permit')},"
                              f"OR({credit.month(i)}<={ref('rve')},{unpaid_seen(i)}>0)),"
                              f"MAX({costs.outside('debt', i)},0),0)"
                              f"+{credit.at('bridge_refinance', i)}"
                              f"+IF({capitalized},0,{credit.at('bridge_transfer', i)})"), money)
    credit.formula("pf_gross", "Долг до погашения",
                   lambda i: f"={credit.before('pf_balance', i)}+{credit.at('pf_draw', i)}", money)
    credit.formula("pf_repayment", "Погашение (раскрытие эскроу и продажи после РВЭ)",
                   lambda i: (f"=MIN({escrow.outside('release', i)}+{escrow.outside('free_sales', i)},"
                              f"MAX({credit.at('pf_gross', i)},0))"), money)
    credit.formula("pf_balance", "Остаток ПФ",
                   lambda i: f"={credit.at('pf_gross', i)}-{credit.at('pf_repayment', i)}",
                   money, bold=True)
    credit.formula("rve_unpaid", "ПФ — не покрыто раскрытым эскроу (в РВЭ)",
                   lambda i: f"=IF({credit.month(i)}={ref('rve')},{credit.at('pf_balance', i)},0)", money)
    # Покрытие — эскроу до раскрытия к долгу ПФ после выборки, но до погашения.
    # Взять эскроу после раскрытия — на РВЭ покрытие обнулится, ставка прыгнет к
    # базовой и проценты уедут вверх на весь остаток проекта.
    credit.formula("coverage", "Покрытие эскроу, ×",
                   lambda i: (f"=IF(AND({credit.month(i)}>={ref('permit')},"
                              f"{credit.at('pf_gross', i)}>0),"
                              f"({escrow.outside_before('balance', i)}"
                              f"+{escrow.outside('inflow', i)})/{credit.at('pf_gross', i)},0)"),
                   ratio, bold=True)
    credit.formula("pf_base_rate", "Базовая ставка", lambda i: f"={rate_grid.outside('pf_base', i)}", percent)
    # Ступени по покрытию эскроу — те же, что в движке. Их нет — формула та же,
    # что была: одна ставка на всё покрытие.
    _special_steps = pf_special_steps(inputs.get("pf_special_steps"))
    _step_refs = [(ref(f"pf_step{index}_edge"), ref(f"pf_step{index}_rate"))
                  for index in range(len(_special_steps))
                  if f"pf_step{index}_edge" in key_row] or None
    credit.formula(
        "pf_special_rate",
        "Ставка ступени по покрытию" if _special_steps else "Ставка при покрытии 1×",
        lambda i: "=" + pf_special_steps_formula(
            credit.at("coverage", i), _special_steps,
            rate_grid.outside("pf_special", i), refs=_step_refs), percent)
    # Базовая ставка — на непокрытую эскроу часть долга, специальная — на
    # покрытую. Излишек эскроу сверх долга ставку ниже специальной не тянет.
    credit.formula("pf_rate", "Ставка ПФ",
                   lambda i: (f"=IF({credit.month(i)}>={ref('permit')},"
                              f"{credit.at('pf_base_rate', i)}*(1-MIN({credit.at('coverage', i)},1))"
                              f"+{credit.at('pf_special_rate', i)}*MIN({credit.at('coverage', i)},1),0)"),
                   percent, bold=True)
    credit.formula("pf_interest", "Проценты начисленные",
                   lambda i: (f"=IF({credit.at('pf_gross', i)}>0,{credit.at('pf_gross', i)}"
                              f"*{credit.at('pf_rate', i)}/12,0)"), money)

    def pf_payable_start(index: int) -> str:
        return (f"{credit.before('pf_payable', index)}"
                f"+IF({capitalized},{credit.at('bridge_transfer', index)},0)")

    credit.formula("pf_cap", "Капитализация процентов",
                   lambda i: (f"=IF({credit.at('pf_gross', i)}>0,({pf_payable_start(i)})"
                              f"*{credit.at('pf_rate', i)}/12,0)"), money)
    credit.formula("limit_fee", "Плата за неиспользованный лимит",
                   # Окно доступности линии: до РВЭ. После РВЭ лимита, за
                   # который платят, больше нет — решение владельца.
                   lambda i: (f"=IF(AND({credit.at('pf_gross', i)}>0,"
                              f"{credit.month(i)}<{ref('rve')}),"
                              f"MAX({ref('pf_limit')}-{credit.at('pf_gross', i)},0)"
                              f"*{ref('limit_fee_pct')}/12,0)"), money)

    def pf_accrued(index: int) -> str:
        return (f"{pf_payable_start(index)}+{credit.at('pf_interest', index)}"
                f"+{credit.at('pf_cap', index)}+{credit.at('limit_fee', index)}")

    credit.formula("interest_payment", "Выплата процентов (с РВЭ)",
                   lambda i: (f"=IF(AND({credit.month(i)}>={ref('rve')},{pf_accrued(i)}>0),"
                              f"{pf_accrued(i)},0)"), money)
    credit.formula("pf_payable", "Начисленные проценты, остаток",
                   lambda i: f"={pf_accrued(i)}-{credit.at('interest_payment', i)}", money)

    credit.formula("fees", "Комиссии за резервирование",
                   lambda i: ((f"={ref('bridge_fee')}" if i == 0 else "=0")
                              + f"+IF({credit.month(i)}={ref('permit')},{ref('pf_reservation_fee')},0)"),
                   money)
    credit.formula("cost", "Проценты и комиссии за месяц",
                   lambda i: (f"={credit.at('bridge_interest', i)}+{credit.at('bridge_cap', i)}"
                              f"+{credit.at('pf_interest', i)}+{credit.at('pf_cap', i)}"
                              f"+{credit.at('limit_fee', i)}+{credit.at('fees', i)}"),
                   money, bold=True)

    # Лимит ПФ банк округляет вверх до десяти миллионов от общей выборки.
    ws_in.cell(row=key_row["pf_limit"], column=2,
               value=f"=CEILING(SUM({credit.span('pf_draw')}),10)")

    # --- НАЛОГИ ------------------------------------------------------------
    tax = _MonthGrid(sheets["tax"], months, styles, title="НАЛОГ НА ПРИБЫЛЬ · млн ₽")
    tax.layout("margin", "adjust", "deduction", "margin_cum", "deduction_cum",
               "base", "tax", "tax_cum", "vat")
    tax.values("margin", "Маржа реализованных продуктов",
               [float(item.get("taxable_margin") or 0.0) / 1e6 for item in rows], money)
    adjust = [0.0] * len(rows)
    if rows:
        adjust[-1] = float(finance.get("financing_tax_reconciliation") or 0.0) / 1e6
    tax.values("adjust", "Корректировка вычетов (сверка)", adjust, money)
    # НДС — денежный расход проекта: без него книга показывала прибыль выше
    # расчёта ровно на его величину, и обе цифры выглядели достоверно.
    vat_schedule = {d(month): value for month, value in
                    (finance.get("vat_schedule") or {}).items()}
    tax.values("vat", "НДС к уплате",
               [round(vat_schedule.get(d(item["month"]), 0.0) / 1e6, 6) for item in rows],
               money)
    tax.formula("deduction", "Вычет по финансированию (выплачено)",
                lambda i: (f"={credit.outside('interest_payment', i)}"
                           f"+{credit.outside('fees', i)}+{tax.at('adjust', i)}"), money)
    tax.formula("margin_cum", "Маржа нарастающим",
                lambda i: f"={tax.before('margin_cum', i)}+{tax.at('margin', i)}", money)
    tax.formula("deduction_cum", "Вычеты нарастающим",
                lambda i: f"={tax.before('deduction_cum', i)}+{tax.at('deduction', i)}", money)
    tax.formula("base", "Налоговая база",
                lambda i: f"=MAX({tax.at('margin_cum', i)}-{tax.at('deduction_cum', i)},0)", money)
    # Налог платится не раньше РВЭ и с зачётом уже уплаченного.
    tax.formula("tax", "Налог за месяц",
                lambda i: (f"=IF({tax.month(i)}>={ref('rve')},"
                           f"MAX({tax.at('base', i)}*{ref('profit_tax_pct')}"
                           f"-{tax.before('tax_cum', i)},0),0)"), money, bold=True)
    tax.formula("tax_cum", "Уплачено нарастающим",
                lambda i: f"={tax.before('tax_cum', i)}+{tax.at('tax', i)}", money)

    # --- CF ----------------------------------------------------------------
    flow = _MonthGrid(sheets["cf"], months, styles, title="ДВИЖЕНИЕ ДЕНЕЖНЫХ СРЕДСТВ · млн ₽")
    flow.layout(
        ("section", "Операционная деятельность"), "revenue", "capex", "operating", "tax",
        "vat", "interest", "project", "project_cum",
        ("section", "Финансовая деятельность"), "bridge_draw", "bridge_repay",
        "pf_draw", "pf_repay", "financing",
        ("section", "Поток на собственный капитал"), "cash_in", "equity", "equity_cum")
    flow.formula("revenue", "Поступления от продаж", lambda i: f"={sales.outside('revenue', i)}", money)
    flow.formula("capex", "CAPEX", lambda i: f"=-{costs.outside('capex', i)}", money)
    flow.formula("operating", "Маркетинг, продажи и содержание",
                 lambda i: f"=-{costs.outside('operating', i)}", money)
    flow.formula("tax", "Налог на прибыль", lambda i: f"=-{tax.outside('tax', i)}", money)
    flow.formula("vat", "НДС", lambda i: f"=-{tax.outside('vat', i)}", money)
    flow.formula("interest", "Проценты и комиссии выплаченные",
                 lambda i: f"=-{credit.outside('interest_payment', i)}-{credit.outside('fees', i)}", money)
    # Проектный поток — как его считает движок: до финансирования тела долга,
    # но после его обслуживания и НДС к уплате (решение владельца 13.10.2026).
    # Именно он идёт в NPV.
    flow.formula("project", "Проектный поток",
                 lambda i: (f"={flow.at('revenue', i)}+{flow.at('capex', i)}"
                            f"+{flow.at('operating', i)}+{flow.at('tax', i)}"
                            f"+{flow.at('vat', i)}+{flow.at('interest', i)}"), money, bold=True)
    flow.formula("project_cum", "Проектный поток нарастающим",
                 lambda i: f"={flow.before('project_cum', i)}+{flow.at('project', i)}", money)

    flow.formula("bridge_draw", "Выборка БРИДЖ", lambda i: f"={credit.outside('bridge_draw', i)}", money)
    flow.formula("bridge_repay", "Погашение БРИДЖ (рефинансирование)",
                 lambda i: f"=-{credit.outside('bridge_refinance', i)}", money)
    flow.formula("pf_draw", "Выборка ПФ", lambda i: f"={credit.outside('pf_draw', i)}", money)
    flow.formula("pf_repay", "Погашение ПФ", lambda i: f"=-{credit.outside('pf_repayment', i)}", money)
    flow.formula("financing", "Финансовый поток",
                 lambda i: (f"={flow.at('bridge_draw', i)}+{flow.at('bridge_repay', i)}"
                            f"+{flow.at('pf_draw', i)}+{flow.at('pf_repay', i)}"), money, bold=True)

    # До РВЭ выручка лежит на эскроу и акционеру недоступна: в поток попадают
    # раскрытие и продажи после РВЭ, а не начисленная выручка.
    flow.formula("cash_in", "Денежные поступления (эскроу раскрыто)",
                 lambda i: (f"=IF({flow.month(i)}<{ref('rve')},0,"
                            f"{flow.at('revenue', i)}+{escrow.outside('release', i)})"), money)
    flow.formula("equity", "Поток на собственный капитал",
                 lambda i: (f"={flow.at('cash_in', i)}+{flow.at('capex', i)}"
                            f"+{flow.at('operating', i)}+{flow.at('tax', i)}"
                            f"+{flow.at('vat', i)}+{flow.at('interest', i)}"
                            f"+{flow.at('financing', i)}"), money, bold=True)
    flow.formula("equity_cum", "Поток на собственный капитал нарастающим",
                 lambda i: f"={flow.before('equity_cum', i)}+{flow.at('equity', i)}", money)

    # --- LLCR --------------------------------------------------------------
    ws_llcr = sheets["llcr"]
    ws_llcr["A1"] = "LLCR"
    ws_llcr["A1"].font = styles["title"]
    ws_llcr["A2"] = ((result.get("notes") or {}).get("llcr") or "")
    llcr_rows = [
        ("Поступления (выручка)", f"=SUM({sales.span('revenue')})", money),
        ("Маркетинг, продажи и содержание", f"=-SUM({costs.span('operating')})", money),
        ("CAPEX", f"=-SUM({costs.span('capex')})", money),
        ("Налог на прибыль", f"=-SUM({tax.span('tax')})", money),
        ("НДС", f"=-SUM({tax.span('vat')})", money),
        ("Выборка ПФ", f"=SUM({credit.span('pf_draw')})", money),
        ("ЧИСЛИТЕЛЬ", "=SUM(B4:B9)", money),
        ("Выборка ПФ", "=B9", money),
        ("Проценты и комиссии", f"=SUM({credit.span('cost')})", money),
        ("ЗНАМЕНАТЕЛЬ", "=B11+B12", money),
        ("LLCR", "=IFERROR(B10/B13,0)", ratio),
    ]
    for offset, (label, formula, fmt) in enumerate(llcr_rows):
        line = 4 + offset
        cell = ws_llcr.cell(row=line, column=1, value=label)
        if label in ("ЧИСЛИТЕЛЬ", "ЗНАМЕНАТЕЛЬ", "LLCR"):
            cell.font = styles["bold"]
        ws_llcr.cell(row=line, column=2, value=formula).number_format = fmt
    ws_llcr.column_dimensions["A"].width = 40
    ws_llcr.column_dimensions["B"].width = 18

    # --- ВРИ ---------------------------------------------------------------
    ws_vri = sheets["vri"]
    ws_vri["A1"] = "ПЛАТА ЗА СМЕНУ ВРИ"
    ws_vri["A1"].font = styles["title"]
    vri = result.get("vri") or {}
    if vri.get("enabled") and (vri.get("rows") or []):
        for column, label in enumerate(
                ("Дата", "Период", "Основной долг", "Проценты", "Платёж",
                 "Остаток", "БРИДЖ", "ПФ", "Свои средства"), start=1):
            ws_vri.cell(row=3, column=column, value=label).font = styles["bold"]
        for offset, item in enumerate(vri.get("rows") or []):
            line = 4 + offset
            ws_vri.cell(row=line, column=1, value=d(item.get("date"))).number_format = month_fmt
            ws_vri.cell(row=line, column=2, value=item.get("period"))
            for column, key in enumerate(
                    ("principal", "interest", "total", "balance_after", "bridge", "pf", "equity"),
                    start=3):
                ws_vri.cell(row=line, column=column,
                            value=round(float(item.get(key) or 0.0) / 1e6, 3)).number_format = money
        last_line = 3 + len(vri.get("rows") or [])
        ws_vri.cell(row=last_line + 1, column=1, value="ИТОГО").font = styles["bold"]
        for column in (3, 4, 5, 7, 8, 9):
            letter = get_column_letter(column)
            cell = ws_vri.cell(row=last_line + 1, column=column,
                               value=f"=SUM({letter}4:{letter}{last_line})")
            cell.number_format = money
            cell.font = styles["bold"]
    else:
        ws_vri["A3"] = "Смена ВРИ в расчёте не участвует: плата равна нулю."
    ws_vri.column_dimensions["A"].width = 16
    for column in range(2, 10):
        ws_vri.column_dimensions[get_column_letter(column)].width = 16

    # --- ОТЧЁТ -------------------------------------------------------------
    ws_rep = sheets["report"]
    ws_rep["A1"] = f"ОТЧЁТ · {project_name or 'проект'}"
    ws_rep["A1"].font = styles["title"]
    ws_rep["A2"] = "Колонка B считается книгой, C — расчёт DevelopAid, D — разница."
    for column, label in ((1, "Показатель"), (2, "Книга"), (3, "DevelopAid"), (4, "Δ")):
        ws_rep.cell(row=3, column=column, value=label).font = styles["bold"]

    row_of = {key: 4 + offset for offset, key in enumerate(_M2_REPORT_KEYS)}

    def own(key: str) -> str:
        return f"$B${row_of[key]}"

    report_rows: list[tuple[str, str, str, str, float]] = [
        ("revenue", "Выручка", f"=SUM({sales.span('revenue')})", money,
         float(summary.get("revenue") or 0.0) / 1e6),
        ("capex", "CAPEX (инвестиции)", f"=SUM({costs.span('capex')})", money,
         float(summary.get("capex") or 0.0) / 1e6),
        ("operating", "Маркетинг, продажи и содержание", f"=SUM({costs.span('operating')})", money,
         float(summary.get("commercial_costs") or 0.0) / 1e6),
        ("ebitda", "EBITDA", f"={own('revenue')}-{own('capex')}-{own('operating')}", money,
         float(summary.get("ebitda") or 0.0) / 1e6),
        ("financing_cost", "Проценты и комиссии", f"=SUM({credit.span('cost')})", money,
         float(summary.get("financing_cost") or 0.0) / 1e6),
        ("profit_before_tax", "Прибыль до налога",
         f"={own('ebitda')}-{own('financing_cost')}", money,
         float(summary.get("profit_before_tax") or 0.0) / 1e6),
        ("profit_tax", "Налог на прибыль", f"=SUM({tax.span('tax')})", money,
         float(summary.get("profit_tax") or 0.0) / 1e6),
        ("vat", "НДС", f"=SUM({tax.span('vat')})", money,
         float(finance.get("vat") or 0.0) / 1e6),
        ("net_profit", "Чистая прибыль",
         f"={own('profit_before_tax')}-{own('profit_tax')}-{own('vat')}", money,
         float(summary.get("net_profit") or 0.0) / 1e6),
        ("peak_bridge", "Пик БРИДЖ", f"=MAX({credit.span('bridge_balance')})", money,
         float(finance.get("peak_bridge") or 0.0) / 1e6),
        ("pf_draw_total", "Выборка ПФ", f"=SUM({credit.span('pf_draw')})", money,
         float(finance.get("pf_draw_total") or 0.0) / 1e6),
        ("peak_pf", "Пик ПФ", f"=MAX({credit.span('pf_balance')})", money,
         float(finance.get("peak_pf") or 0.0) / 1e6),
        ("avg_pf_rate", "Средневзвешенная ставка ПФ",
         f"=IFERROR(SUMPRODUCT({credit.span('pf_gross')},{credit.span('pf_rate')})"
         f"/SUM({credit.span('pf_gross')}),0)", percent,
         float(finance.get("avg_pf_rate") or 0.0)),
        ("llcr", "LLCR", f"={_M2_SHEETS['llcr']}!$B$14", ratio,
         float(summary.get("llcr") or 0.0)),
    ]
    for key, label, formula, fmt, expected in report_rows:
        line = row_of[key]
        cell = ws_rep.cell(row=line, column=1, value=label)
        if key in ("ebitda", "net_profit", "llcr"):
            cell.font = styles["bold"]
        ws_rep.cell(row=line, column=2, value=formula).number_format = fmt
        ws_rep.cell(row=line, column=3, value=round(expected, 12)).number_format = fmt
        ws_rep.cell(row=line, column=4, value=f"=B{line}-C{line}").number_format = fmt

    line = 4 + len(report_rows) + 1
    ws_rep.cell(row=line, column=1, value="УДЕЛЬНЫЕ ПОКАЗАТЕЛИ").font = styles["section"]
    line += 1
    for column, label in enumerate(
            ("Показатель", "Всего, млн ₽", "На м² своей базы, тыс. ₽", "База",
             "На продаваемую, тыс. ₽/м²"), start=1):
        ws_rep.cell(row=line, column=column, value=label).font = styles["bold"]
    for offset, item in enumerate(report.get("unit_economics") or []):
        current = line + 1 + offset
        ws_rep.cell(row=current, column=1, value=item.get("label"))
        ws_rep.cell(row=current, column=2,
                    value=round(float(item.get("total") or 0.0) / 1e6, 3)).number_format = money
        # База строки — из движка, подпись — из словаря (решение 4 ревизии).
        if item.get("per_base_th") is not None:
            ws_rep.cell(row=current, column=3,
                        value=round(float(item["per_base_th"]), 3)).number_format = money
        ws_rep.cell(row=current, column=4, value=_pdf_unit_base(item))
        if item.get("per_saleable_th") is not None and item.get("base") != UNIT_BASE_SALEABLE:
            ws_rep.cell(row=current, column=5,
                        value=round(float(item["per_saleable_th"]), 3)).number_format = money
    ws_rep.column_dimensions["A"].width = 40
    for column in ("B", "C", "D", "E"):
        ws_rep.column_dimensions[column].width = 18

    # Отчёт открывается первым, дальше — вводные и расчётные листы по порядку.
    workbook.move_sheet(ws_rep, offset=-(len(workbook.sheetnames) - 1))
    workbook.calculation.fullCalcOnLoad = True
    buffer = io.BytesIO()
    workbook.save(buffer)
    return buffer.getvalue(), {
        "months": len(rows),
        "sheets": list(workbook.sheetnames),
        "layout": {
            "sales": dict(sales.rows), "costs": dict(costs.rows), "rates": dict(rate_grid.rows),
            "escrow": dict(escrow.rows), "credit": dict(credit.rows), "tax": dict(tax.rows),
            "cf": dict(flow.rows), "inputs": dict(key_row), "report": dict(row_of),
        },
        "engine": {key: expected for key, _, _, _, expected in report_rows},
    }


# Что с чем сверяется на листе «ОТЧЕТ» шаблона. Слева подпись в колонке B,
# справа — как та же величина зовётся в результате движка. Знак не важен:
# шаблон пишет расходы отрицательными, движок — положительными.
_PLATO_AUDIT_ROWS: list[tuple[str, str, str]] = [
    ("Поступления", "summary.revenue", "выручка"),
    ("Вход", "inputs.purchase_price_mln", "цена приобретения"),
    ("Расходы на ЗУ", "inputs.land_rights_cost_mln", "смена ВРИ и земельные права"),
    ("Строительство соцобъектов", "capex.social", "социальная нагрузка"),
    ("Коммерческие", "summary.commercial_costs", "коммерческие расходы"),
    ("Расходы", "summary.total_expenses", "расходы всего"),
    ("EBITDA", "summary.ebitda", "EBITDA"),
    ("%% по кредитам", "summary.financing_cost", "проценты и комиссии"),
    ("Налог на прибыль / прочие налоги", "summary.profit_tax", "налог на прибыль"),
    ("Чистая прибыль", "summary.net_profit", "чистая прибыль"),
    ("NPV @20%", "summary.npv", "NPV"),
    ("LLCR", "summary.llcr", "LLCR"),
    ("Маржинальность", "summary.margin", "маржинальность"),
]

# Доли и коэффициенты сравниваются как есть, деньги — в миллионах рублей.
_PLATO_AUDIT_AS_IS = frozenset({"summary.llcr", "summary.margin"})


def _plato_audit_expected(bundle: dict[str, Any], inputs: dict[str, Any], path: str) -> float | None:
    where, _, key = path.partition(".")
    if where == "inputs":
        # Ожидаемое — то, что книга получила: вводные после типа проекта.
        return n(residential_excluded(inputs, {})[0], key, 0.0)
    result = bundle.get("consolidated") or {}
    if where == "summary":
        value = (result.get("summary") or {}).get(key)
    elif where == "capex":
        value = (result.get("capex") or {}).get(key)
    else:
        return None
    if value is None:
        return None
    return float(value) if path in _PLATO_AUDIT_AS_IS else float(value) / 1e6


def audit_plato_workbook(
    content: bytes,
    inputs: dict[str, Any],
    tep: dict[str, dict[str, Any]],
    rates: list[dict[str, Any]] | None = None,
    phasing: dict[str, Any] | None = None,
    *,
    tolerance_pct: float = 1.0,
) -> dict[str, Any]:
    """Сверяет посчитанную книгу ПЛАТО с расчётом движка.

    Шаблон — живая книга на формулах, и ошибиться он может независимо от нас:
    ячейка тянет значение не оттуда, остаётся хвост прежней методики, ломается
    ссылка. Найти это глазами дорого — сегодня расхождение по социальной
    нагрузке (0,6 млн ₽ против 193,2 млн ₽) искалось полтора десятка шагов.

    Книга должна быть пересчитана Excel: openpyxl формулы не считает и читает
    только сохранённый результат. Непосчитанную книгу функция так и назовёт,
    а не выдаст пустые расхождения за совпадение.
    """
    try:
        from openpyxl import load_workbook
    except ModuleNotFoundError as exc:
        raise HTTPException(status_code=500, detail="Для сверки нужен пакет openpyxl") from exc

    workbook = load_workbook(io.BytesIO(content), data_only=True)
    if "ОТЧЕТ" not in workbook.sheetnames:
        raise HTTPException(status_code=400, detail="В книге нет листа «ОТЧЕТ» — это не модель ПЛАТО")
    if "КОНСОЛИДАТОР" in workbook.sheetnames:
        # У книги v4 свой лист «ОТЧЕТ» с подписями в другой колонке: сверка не
        # нашла бы ни строки и назвала бы пересчитанную книгу непересчитанной.
        raise HTTPException(
            status_code=400,
            detail=("Это книга DevelopAid v4, а не модель ПЛАТО: её сверка с движком — "
                    "строки «Паритет» листа «ПРОВЕРКИ» книги, пересчитанной в Excel"))
    sheet = workbook["ОТЧЕТ"]
    found: dict[str, float] = {}
    for row in range(1, 90):
        label = sheet.cell(row=row, column=2).value
        value = sheet.cell(row=row, column=3).value
        if isinstance(label, str) and isinstance(value, (int, float)):
            found.setdefault(_plato_normalize(label), float(value))

    bundle = _run_authoritative_model(
        copy.deepcopy(inputs or {}), copy.deepcopy(tep or {}),
        copy.deepcopy(rates or []), copy.deepcopy(phasing or {}),
    )
    items: list[dict[str, Any]] = []
    missing: list[str] = []
    for label, path, name in _PLATO_AUDIT_ROWS:
        model = found.get(_plato_normalize(label))
        expected = _plato_audit_expected(bundle, inputs or {}, path)
        if model is None or expected is None:
            missing.append(name)
            continue
        model = abs(model) if not path.startswith("summary.llcr") else model
        expected_abs = abs(expected)
        delta = abs(model) - expected_abs
        scale = max(abs(expected_abs), 1e-9)
        items.append({
            "name": name,
            "label": label,
            "model": round(abs(model), 4),
            "engine": round(expected_abs, 4),
            "delta": round(delta, 4),
            "delta_pct": round(delta / scale * 100, 3),
            "matches": abs(delta) <= max(abs(expected_abs) * tolerance_pct / 100, 1e-6),
        })

    mismatched = [item for item in items if not item["matches"]]
    mismatched.sort(key=lambda item: abs(item["delta"]), reverse=True)
    if not found:
        verdict = ("Книга не пересчитана: формулы не имеют сохранённого результата. "
                   "Откройте её в Excel, дождитесь пересчёта, сохраните и повторите сверку.")
    elif not mismatched:
        verdict = f"Расхождений сверх {_telegram_number(tolerance_pct, 1)}% не найдено."
    else:
        worst = mismatched[0]
        verdict = (f"Расхождений: {len(mismatched)} из {len(items)}. Больше всего расходится "
                   f"«{worst['name']}»: в модели {_telegram_number(worst['model'], 1)}, "
                   f"в расчёте {_telegram_number(worst['engine'], 1)}.")
    return {
        "recalculated": bool(found),
        "tolerance_pct": tolerance_pct,
        "items": items,
        "mismatched": mismatched,
        "missing": missing,
        "verdict": verdict,
    }
