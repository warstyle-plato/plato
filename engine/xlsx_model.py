"""Состав выгружаемой модели: колонки, подписи и листы XLSX полной модели.

Не самостоятельный модуль. `main_legacy.py` выполняет этот файл в своём
пространстве имён на том месте, где этот код стоял раньше
(`_engine_part("xlsx_model")`), поэтому здесь видны все имена движка,
а подмены `core.<имя>` из `main.py` и тестов действуют и на этот код.
Отдельно не импортировать: второй импорт поднял бы вторую копию движка.
"""
# ruff: noqa

# ---------------------------------------------------------------------------
# Состав выгружаемой модели
# ---------------------------------------------------------------------------

_MODEL_FINANCE_COLUMNS: list[tuple[str, str, str]] = [
    ("sales", "Продажи (поступления)", "mln"),
    ("project_costs", "Расходы проекта", "mln"),
    ("key_rate", "Ключевая ставка", "pct"),
    ("bridge_rate", "Ставка БРИДЖ", "pct"),
    ("project_cash_draw", "Свободный cash проекта", "mln"),
    ("own_funds_draw", "Собственные средства", "mln"),
    ("bridge_draw", "Выборка БРИДЖ", "mln"),
    ("bridge_balance", "Остаток БРИДЖ", "mln"),
    ("bridge_interest", "Проценты БРИДЖ", "mln"),
    ("bridge_capitalization", "Капитализация БРИДЖ", "mln"),
    ("pf_draw", "Выборка ПФ", "mln"),
    ("pf_repayment", "Погашение ПФ", "mln"),
    ("pf_balance", "Остаток ПФ", "mln"),
    ("escrow", "Эскроу", "mln"),
    ("escrow_release", "Раскрытие эскроу", "mln"),
    ("coverage", "Покрытие эскроу, ×", "num"),
    ("pf_rate", "Ставка ПФ", "pct"),
    ("pf_interest", "Проценты ПФ", "mln"),
    ("pf_interest_capitalization", "Капитализация процентов ПФ", "mln"),
    ("limit_fee", "Плата за лимит", "mln"),
    ("interest_payment", "Выплата процентов", "mln"),
    ("taxable_margin", "Налоговая маржа", "mln"),
    ("financing_tax_deduction", "Вычет по финансированию", "mln"),
    ("taxable_profit_cumulative", "Накопленная база налога", "mln"),
    ("profit_tax", "Налог на прибыль", "mln"),
]

# Суммировать по месяцам можно только потоки; остатки и ставки — нет.
_MODEL_FINANCE_SUMMABLE = {
    "sales", "project_costs", "project_cash_draw", "own_funds_draw",
    "bridge_draw", "bridge_interest", "bridge_capitalization",
    "pf_draw", "pf_repayment", "escrow_release", "pf_interest", "pf_interest_capitalization",
    "limit_fee", "interest_payment", "taxable_margin", "financing_tax_deduction", "profit_tax",
}

# Короткие подписи тех же статей — для таблицы «Расходы» на странице, где на
# имя есть одна строка. Это НЕ второй список статей: имена берутся по ключам
# `_MODEL_CAPEX_LABELS` ниже, и статья без короткой подписи получает полную.
# Прежде страница держала свой словарь `capNames`, и статьи, заведённые позже,
# доезжали до экрана сырыми ключами: «resettlement» и «demolition» стояли
# среди русских названий (владелец, 25.08.2026). Копию негде обновлять, потому
# что копии больше нет.
CAPEX_SHORT_NAMES: dict[str, str] = {
    "land_rights": "Земля / смена ВРИ",
    "ird": "ИРД",
    "design_p": "Проект П",
    "design_rd": "Проект РД",
    "utilities": "Наружные сети",
    "offices": "Офисы",
    "standalone_retail": "Коммерция ОСЗ",
    "sports": "ФОК / медцентр",
    "hotel": "Гостиница — здание",
    "hotel_ffe": "Гостиница — мебель и оборудование",
    "social": "Социальный платеж / соцобъекты",
    "gc_fee": "Генподрядчик",
    "main_above": "Основное строительство — наземная часть",
    "main_under": "Основное строительство — подземная часть",
}
CAPEX_NAMES_PLACEHOLDER = "__DEVELOPAID_CAPEX_NAMES__"

_MODEL_CAPEX_LABELS: list[tuple[str, str]] = [
    ("purchase", "Покупка / цена входа"),
    ("land_rights", "Земельные правоотношения / смена ВРИ"),
    ("vri_security", "Обеспечение обязательства по ВРИ"),
    ("vri_interest", "Проценты по рассрочке ВРИ"),
    ("ird", "ИРД и согласования"),
    ("design_p", "Проектирование, стадия П"),
    ("design_rd", "Проектирование, стадия РД"),
    ("author_supervision", "Авторский надзор"),
    ("technical_supervision", "Технический заказчик / стройконтроль"),
    ("demolition", "Снос и демонтаж"),
    ("resettlement", "Расселение"),
    ("preparation", "Подготовительные работы"),
    ("main_above", "Основное строительство, наземная часть"),
    ("main_under", "Основное строительство, подземная часть"),
    ("utilities", "Наружные инженерные сети"),
    ("landscaping", "Благоустройство"),
    ("commissioning", "Сдача и ввод"),
    ("site_maintenance", "Содержание стройплощадки"),
    ("offices", "МФОЦ / офисы"),
    ("standalone_retail", "ТЦ / коммерция ОСЗ"),
    ("above_parking", "Наземный паркинг"),
    ("sports", "ФОК / медцентр"),
    ("hotel", "Гостиница — здание"),
    ("hotel_ffe", "Гостиница — мебель и оборудование (FF&E)"),
    ("social", "Социальная нагрузка"),
    ("project_management", "Управление проектом"),
    ("gc_fee", "Вознаграждение генподрядчика"),
    ("reserve", "Резерв"),
]


def _after_their_product(items: list[tuple[str, Any]],
                         label_of: "Callable[[StandaloneObject], Any]") -> list[tuple[str, Any]]:
    """Вставить вторые объекты реестра сразу за строкой их продукта.

    Порядок прежних строк не меняется: книга и таблицы, собранные до вторых
    объектов, читаются так же. Второй объект без строки продукта в списке не
    появляется — список, в котором продукта нет, о нём и не спрашивал.
    """
    out = list(items)
    for obj in STANDALONE_OBJECTS:
        if not obj.family or any(key == obj.key for key, *_ in out):
            continue
        at = max((i for i, (key, *_) in enumerate(out)
                  if key in _BY_KEY and _BY_KEY[key].product == obj.family), default=-1)
        if at >= 0:
            out.insert(at + 1, (obj.key, label_of(obj)))
    return out


_MODEL_CAPEX_LABELS = _after_their_product(
    _MODEL_CAPEX_LABELS, lambda obj: obj.group_label or obj.label)
def standalone_objects_report_order() -> tuple[StandaloneObject, ...]:
    """Объекты реестра в порядке таблиц отчёта: офисы — первыми.

    Таблица продуктов, календарь и налоговая маржа исторически начинаются с
    офисов, и по этому порядку строятся колонки КОНСОЛИДАТОРА книги: смени
    его — и книга проекта без вторых объектов перестала бы совпадать с
    прежней. Остальное — порядок реестра (порядок строк ТЭП), второй объект
    стоит за своим двойником. Это перестановка реестра, а не выборка.
    """
    return tuple(sorted(STANDALONE_OBJECTS, key=lambda obj: obj.product != "offices"))


# Имена объектов в таблице продуктов, которые отличаются от имени строки ТЭП.
# Остальные берут имя строки: одно имя на продукт.
_PRODUCT_SPEC_LABELS = {"offices": "Офисы / МФОЦ"}
_CALENDAR_OBJECT_LABELS = {"sports": "ФОК / спорт"}


# Короткое имя второго объекта — имя его строки ТЭП, как у первого
# («Офисы», «Коммерция ОСЗ»).
CAPEX_SHORT_NAMES.update({
    obj.key: obj.tep_label for obj in STANDALONE_OBJECTS
    if obj.family and CAPEX_SHORT_NAMES.get(obj.family) and obj.tep_label})

_MODEL_SUMMARY_ROWS: list[tuple[str, str, str]] = [
    ("revenue", "Выручка", "mln"),
    ("capex", "CAPEX", "mln"),
    ("commercial_costs", "Коммерческие расходы", "mln"),
    ("total_expenses", "Расходы всего", "mln"),
    ("ebitda", "EBITDA", "mln"),
    ("financing_cost", "Стоимость финансирования", "mln"),
    ("profit_before_tax", "Прибыль до налога", "mln"),
    ("profit_tax", "Налог на прибыль", "mln"),
    ("vat", "НДС", "mln"),
    ("net_profit", "Чистая прибыль", "mln"),
    ("margin", "Маржинальность", "pct"),
    ("llcr", "LLCR", "num"),
    ("npv", "NPV", "mln"),
    ("irr_equity", "IRR собственного капитала", "pct"),
    ("full_project_cost", "Полная стоимость проекта", "mln"),
    ("project_gns_sqm", "ГНС проекта (наземная), м²", "int"),
    ("monetizable_saleable_sqm", "Продаваемая площадь, м²", "int"),
    ("full_cost_per_saleable_th", "Полная себестоимость, тыс. ₽/м² продаж", "num"),
    ("construction_cost_per_gns_th", f"Строительство, тыс. ₽/м² {CORE_TOTAL_AREA.genitive}", "num"),
]

_MODEL_FINANCE_SUMMARY_ROWS: list[tuple[str, str, str]] = [
    ("calculated_bridge_limit", "Расчётный лимит БРИДЖ", "mln"),
    ("peak_bridge", "Пиковая задолженность БРИДЖ", "mln"),
    ("bridge_interest", "Проценты БРИДЖ", "mln"),
    ("avg_bridge_rate", "Средняя ставка БРИДЖ", "pct"),
    ("pf_limit", "Лимит ПФ", "mln"),
    ("pf_limit_required", "Требуется лимита ПФ по расчёту", "mln"),
    ("pf_shortfall", "Непокрытая потребность в ПФ", "mln"),
    ("peak_pf", "Пиковая задолженность ПФ", "mln"),
    ("peak_uncovered_pf", "Пиковая непокрытая эскроу задолженность ПФ", "mln"),
    ("rve_pf_before_repayment", "Долг ПФ перед раскрытием в РВЭ", "mln"),
    ("rve_escrow_release", "Раскрытый эскроу в РВЭ", "mln"),
    ("rve_pf_shortfall", "Остаток ПФ после раскрытия в РВЭ", "mln"),
    ("pf_interest", "Проценты ПФ", "mln"),
    ("pf_limit_fee", "Плата за лимит ПФ", "mln"),
    ("avg_pf_base_rate", "Средняя ставка ПФ без эффекта эскроу", "pct"),
    ("avg_pf_effective_rate", "Средняя фактическая ставка ПФ с учётом эскроу", "pct"),
    ("financing_cost", "Стоимость финансирования всего", "mln"),
    ("llcr", "LLCR", "num"),
]


def _model_value_cell(value: Any, kind: str) -> _XlsxCell:
    if kind == "mln":
        return _cell_mln(value)
    if kind == "pct":
        number = _land_float(value)
        return _XlsxCell(number, _XLSX_STYLE_PCT) if number is not None else _cell_text("")
    if kind == "int":
        return _cell_num(value, _XLSX_STYLE_INT)
    return _cell_num(value)


def _parking_num_text(value: Any) -> str:
    """Число норматива строкой: 63.0 -> «63», 0.75 -> «0,75»."""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return ""
    if number != number or abs(number) == float("inf"):
        return ""
    text = f"{number:.4f}".rstrip("0").rstrip(".")
    return (text or "0").replace(".", ",")


def _model_parking_norm_rows(result: dict[str, Any]) -> list[list[_XlsxCell]]:
    """Нормативная потребность нежилья — отдельным блоком под ТЭП.

    Методику меняют в двух местах: в движке и в книге. Ставку ПФ однажды
    правили только в движке, и книга полгода считала своё — расхождение нашли
    по чужой сверке. Поэтому норма приезжает в книгу тем же числом, что на
    экране, и с тем же основанием.

    Построенный ТЭП и нормативная потребность — разные вещи, и стоять в одной
    таблице они не должны: «требуется 596 мест» не значит «596 мест
    построено». Отсюда отдельный заголовок, а не лишние строки в ТЭП.
    """
    parking = result.get("parking") or {}
    data = parking.get("rows") or []
    if not data:
        return []
    oblast = str(parking.get("jurisdiction") or "") == "moscow_oblast"
    rows: list[list[_XlsxCell]] = [
        [],
        [_cell_text("Приобъектная парковка нежилья — нормативная потребность",
                    _XLSX_STYLE_TITLE)],
        _header_row(["Объект", "База, м²", "Расчётная единица", "На одно место",
                     "К1", "К2", "Требуется мест"]),
    ]
    for item in data:
        if oblast:
            per = (f"{_parking_num_text(item.get('norm_denominator_min'))}–"
                   f"{_parking_num_text(item.get('norm_denominator_max'))}")
        else:
            per = _parking_num_text(item.get("x2"))
        rows.append([
            _cell_text(item.get("label") or item.get("function") or "—"),
            _cell_num(item.get("input_value"), _XLSX_STYLE_INT),
            _cell_text(item.get("input_unit_label") or ""),
            _cell_text(per),
            _cell_text("" if oblast else _parking_num_text(item.get("k1"))),
            _cell_text("" if oblast else _parking_num_text(item.get("k2"))),
            _cell_num(item.get("required_spaces"), _XLSX_STYLE_INT),
        ])
    rows.append([
        _cell_text("Итого требуется", _XLSX_STYLE_BOLD), _cell_text(""), _cell_text(""),
        _cell_text(""), _cell_text(""), _cell_text(""),
        _cell_num(parking.get("required_total"), _XLSX_STYLE_TOTAL_INT),
    ])
    # Приобъектная стоянка — благоустройство, а не продукт: её нельзя поставить
    # на кадастр, значит нельзя и продать. Без этой строки норматив рядом с
    # деньгами читается как объём стройки.
    rows.append([_cell_text(
        "Приобъектная стоянка — вдоль проезда, в составе благоустройства: "
        "на кадастр не ставится, отдельных метров и выручки не даёт. Размещение — "
        "плоскостная парковка или сторона улицы в красных линиях УДС до 200 м от "
        "объекта (945-ПП п. 6.1.2.3, 6.1.2.5.3); в подземный паркинг МКД не входит")])
    own = [item for item in (parking.get("own") or []) if item.get("enabled")]
    if own:
        rows.append([_cell_text(
            "Собственный паркинг объектов (продаётся машино-местами): "
            + "; ".join(f"{item['label']} — {item['under_spaces']} подземных, "
                        f"{item['over_spaces']} на первых этажах" for item in own))])
    sources = list(dict.fromkeys(
        str(item.get("normative_source") or "") for item in data if item.get("normative_source")))
    for line in sources:
        rows.append([_cell_text("Основание: " + line)])
    # Неподтверждённое и непосчитанное говорится вслух. Пустая строка вместо
    # оговорки читается как «посчитано и всё в порядке».
    for line in parking.get("assumptions") or []:
        rows.append([_cell_text("Допущение: " + line)])
    for line in parking.get("missing") or []:
        rows.append([_cell_text("Не посчитано — " + line)])
    return rows


def _model_matrix_sheet(
    name: str,
    title: str,
    months: list[str],
    blocks: list[tuple[str, list[dict[str, Any]], str]],
) -> dict[str, Any]:
    """Лист «строки × месяцы»: статьи или продукты по горизонтали времени."""
    rows: list[list[_XlsxCell]] = [[_cell_text(title, _XLSX_STYLE_TITLE)], []]
    for block_title, items, unit in blocks:
        if not items:
            continue
        rows.append([_cell_text(block_title, _XLSX_STYLE_BOLD)])
        rows.append(_header_row([f"Показатель, {unit}", "Итого"] + months))
        first_data_row = len(rows) + 1
        money = unit.startswith("млн")
        last_column = _xlsx_column_name(len(months) + 1)
        for item in items:
            row_number = len(rows) + 1
            values = item.get("values") or []
            total = _land_float(item.get("total")) or 0.0
            row: list[_XlsxCell] = [
                _cell_text(item.get("label")),
                _cell_formula(
                    f"SUM(C{row_number}:{last_column}{row_number})",
                    total / 1_000_000.0 if money else total,
                ),
            ]
            for value in values:
                number = _land_float(value) or 0.0
                row.append(_cell_num(number / 1_000_000.0 if money else number))
            rows.append(row)
        last_data_row = len(rows)
        total_row: list[_XlsxCell] = [_cell_text("Итого", _XLSX_STYLE_BOLD)]
        for index in range(len(months) + 1):
            column = _xlsx_column_name(index + 1)
            column_total = sum(
                (_land_float((item.get("values") or [0] * len(months))[index - 1]) or 0.0)
                if index else (_land_float(item.get("total")) or 0.0)
                for item in items
            )
            total_row.append(_cell_formula(
                _sum_formula(column, first_data_row, last_data_row),
                column_total / 1_000_000.0 if money else column_total,
            ))
        rows.append(total_row)
        rows.append([])
    return {
        "name": name,
        "rows": rows,
        "widths": [46, 16] + [13] * len(months),
        "freeze": "C5",
        "split_x": 2,
        "split_y": 4,
    }


# Остатки берутся на конец квартала, ставки и покрытие — средние за квартал.
_MODEL_FINANCE_BALANCES = {"bridge_balance", "pf_balance", "escrow", "taxable_profit_cumulative"}
_MODEL_FINANCE_AVERAGES = {"key_rate", "bridge_rate", "pf_rate", "coverage"}


def _quarter_label(month: str) -> str:
    text = str(month or "")
    try:
        parsed = datetime.strptime(text[:10], "%Y-%m-%d")
    except ValueError:
        return text
    return f"{parsed.year}-Q{(parsed.month - 1) // 3 + 1}"


def _quarter_groups(months: list[str]) -> list[tuple[str, list[int]]]:
    groups: dict[str, list[int]] = {}
    order: list[str] = []
    for index, month in enumerate(months):
        label = _quarter_label(month)
        if label not in groups:
            groups[label] = []
            order.append(label)
        groups[label].append(index)
    return [(label, groups[label]) for label in order]


def _quarterly_items(items: list[dict[str, Any]], groups: list[tuple[str, list[int]]]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for item in items:
        values = item.get("values") or []
        result.append({
            **item,
            "values": [
                sum(_land_float(values[index]) or 0.0 for index in indexes if index < len(values))
                for _, indexes in groups
            ],
        })
    return result


_MODEL_VRI_SETTING_ROWS: list[tuple[str, str]] = [
    ("region", "Регион"),
    ("land_right", "Право на участок"),
    ("obligation_date", "Дата возникновения обязательства"),
    ("obligation_basis", "Основание даты"),
    ("payment_mode", "Порядок оплаты"),
    ("years", "Срок рассрочки, лет"),
    ("periodicity", "Периодичность платежей, мес."),
    ("schedule_mode", "График платежей"),
    ("interest_enabled", "Проценты на остаток"),
    ("pf_open", "Дата открытия ПФ"),
    ("in_bank_budget", "Включена в банковский бюджет"),
    ("financing_mode", "Источники оплаты"),
]

_MODEL_VRI_LABELS: dict[str, str] = {
    "msk": "Москва", "mo": "Московская область",
    "ownership": "Собственность", "lease": "Аренда",
    "lump": "Единовременно", "installment": "Рассрочка",
    "auto": "Автоматический", "shares": "Заданные доли",
    "manual": "Ручной", "True": "Да", "False": "Нет",
}


def _safe_file_stem(value: str, fallback: str = "DevelopAid") -> str:
    stem = re.sub(r"[^0-9A-Za-zА-Яа-яЁё _-]+", "_", str(value or "")).strip(" _")
    return (stem[:60] or fallback)
