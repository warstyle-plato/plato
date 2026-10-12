"""Единая книга проекта v4: templates/DevelopAid_model_v4.xlsx.

Не самостоятельный модуль. `main_legacy.py` выполняет этот файл в своём
пространстве имён на том месте, где этот код стоял раньше
(`_engine_part("xlsx_book_v4")`), поэтому здесь видны все имена движка,
а подмены `core.<имя>` из `main.py` и тестов действуют и на этот код.
Отдельно не импортировать: второй импорт поднял бы вторую копию движка.
"""
# ruff: noqa

# ---------------------------------------------------------------------------
# Единая книга проекта: templates/DevelopAid_model_v4.xlsx. Считает весь
# проект живыми формулами; сюда пишутся только вводные листа «Вводные» —
# каждая ячейка ввода подписана «Ключом API» движка. Книга несёт диаграммы,
# которые openpyxl при перезаписи теряет, поэтому значения правятся прямо
# в XML внутри zip — как и выгрузка в шаблон ПЛАТО ниже.
# ---------------------------------------------------------------------------

_V4_TEMPLATE_PATH = Path(__file__).resolve().parent / "templates" / "DevelopAid_model_v4.xlsx"

# Ключ движка -> ячейка листа «Вводные». Проценты движок хранит в пунктах
# (25 = 25%), книга — в долях, пересчёт по суффиксу _pct/_pp.
# --- где объект живёт в книге ----------------------------------------------
# Шаблон несёт ТРИ блока отдельно стоящих объектов — офисы, ТЦ и наземный
# паркинг, — и каждый из них расписан по пяти листам своими строками: блок
# вводных на «Параметрах модели», блок ОБЪЕКТЫ, строка ТЭП, строка структуры
# продукта в ОТЧЁТЕ и места гаража. Всякий следующий объект реестра — ФОК,
# второй офисник, второй ТЦ — дописывается КОПИЕЙ блока своего двойника
# (`StandaloneObject.book_twin`) в свободный низ листов.
#
# Прежде такой объект был один, и его строки стояли числами в десятке мест
# поимённо: «поставить второй офисник» значило переписать их все ещё раз.
# Теперь ответ «на какой строке объект» один — эта раскладка, — и всё, что
# пишет объект в книгу, читает её.
class _V4ObjectLayout(NamedTuple):
    obj: "StandaloneObject"
    twin: str               # ключ блока шаблона, с которого снята копия
    twin_prefix: str        # приставка вводных двойника
    input_head: int         # строка заголовка блока вводных
    input_offset: int       # сдвиг строк вводных относительно двойника
    object_head: int        # строка заголовка блока листа ОБЪЕКТЫ
    object_offset: int      # сдвиг строк ОБЪЕКТОВ относительно двойника
    disposition_row: int    # «что с объектом дальше»; 0 — признака нет
    residual_row: int       # остаточные продажи после РВЭ
    parking_under: str      # мест в своём подземном; "" — гаража нет
    parking_over: str       # мест на первых этажах
    parking_guest: str      # доля гостевых; "" — места не продаются
    parking_under_price: str
    parking_over_price: str
    tep_row: int            # строка листа ТЭП
    report_row: int         # строка структуры продукта; 0 — в строке двойника

    @property
    def extra(self) -> bool:
        """Объект дописан копией, а не стоит в шаблоне своим блоком."""
        return bool(self.input_offset or self.object_offset)


# Три блока шаблона. Числа сняты с самого шаблона — это его адреса, а не наш
# выбор, и сдвинуть их нельзя: на них ссылаются десятки тысяч формул.
_V4_TEMPLATE_OBJECT_LAYOUT = {
    # ключ: (заголовок вводных, заголовок ОБЪЕКТОВ, остаточные продажи,
    #        подземный, первые этажи, гостевые, цена под землёй, цена на этаже,
    #        строка ТЭП, строка структуры продукта)
    "offices": (18, 6, 36, "K161", "K162", "K167", "K169", "K170", 31, 50),
    "standalone_retail": (38, 34, 56, "K163", "K164", "", "", "", 32, 51),
    "above_parking": (58, 62, 76, "", "", "", "", "", 33, 52),
}
# Первый дописанный объект сидит там, где его застала книга: вводные с 121-й
# строки, ОБЪЕКТЫ с 124-й, места — в общем блоке паркинга (165/166), строка
# ТЭП на месте прежнего итога (34), строка структуры продукта — на 53-й.
# Следующие встают ниже всего, что есть на листе, каждый через свой шаг.
_V4_EXTRA_FIRST_SLOT = (121, 124, "K165", "K166", 34, 53)
_V4_EXTRA_INPUT_HEAD = 172        # вводные второго дописанного объекта
_V4_EXTRA_INPUT_STRIDE = 28       # блок 25 строк и зазор
_V4_EXTRA_OBJECT_HEAD = 154       # ОБЪЕКТЫ второго дописанного объекта
_V4_EXTRA_OBJECT_STRIDE = 30      # блок 28 строк и зазор
_V4_EXTRA_TEP_HEAD = 46           # заголовок дописанных строк ТЭП — под соцобъектами
_V4_INPUT_BLOCK_ROWS = 18         # заголовок + шапка + 16 вводных


def _v4_object_layouts(
        objects: "tuple[StandaloneObject, ...] | None" = None,
) -> tuple[_V4ObjectLayout, ...]:
    """Раскладка всех объектов реестра по листам книги, в порядке реестра.

    Дописанный объект с неизвестным двойником — ошибка сборки, а не пропуск:
    объект без блока в книге выглядел бы посчитанным на экране и отсутствовал
    бы в Excel.
    """
    objects = STANDALONE_OBJECTS if objects is None else objects
    by_key = {o.key: o for o in objects}
    out: list[_V4ObjectLayout] = []
    slot = 0
    # Места дописанным объектам раздаются в порядке «свой продукт раньше
    # второго экземпляра»: ФОК дописан первым и стоит на строках, которые
    # книга несёт давно; вторые ОСЗ встают ниже, в порядке реестра.
    for obj in sorted(objects, key=lambda o: bool(o.family)):
        if obj.key in _V4_TEMPLATE_OBJECT_LAYOUT:
            (head, ohead, residual, under, over, guest, uprice, oprice,
             tep_row, report_row) = _V4_TEMPLATE_OBJECT_LAYOUT[obj.key]
            out.append(_V4ObjectLayout(
                obj, obj.key, obj.prefix, head, 0, ohead, 0, 0, residual,
                under, over, guest, uprice, oprice, tep_row, report_row))
            continue
        twin = obj.book_twin
        if twin not in _V4_TEMPLATE_OBJECT_LAYOUT or twin not in by_key:
            raise ValueError(f"объект «{obj.key}»: у книги нет блока-двойника «{twin}»")
        (twin_head, twin_ohead, *_rest) = _V4_TEMPLATE_OBJECT_LAYOUT[twin]
        if slot == 0:
            head, ohead, under, over, tep_row, report_row = _V4_EXTRA_FIRST_SLOT
        else:
            head = _V4_EXTRA_INPUT_HEAD + (slot - 1) * _V4_EXTRA_INPUT_STRIDE
            ohead = _V4_EXTRA_OBJECT_HEAD + (slot - 1) * _V4_EXTRA_OBJECT_STRIDE
            under, over = f"K{head + 20}", f"K{head + 21}"
            tep_row, report_row = _V4_EXTRA_TEP_HEAD + slot, 0
        if not obj.garage:
            under = over = ""
        guest = uprice = oprice = ""
        if obj.garage and obj.garage_sellable:
            guest, uprice, oprice = (f"K{head + 22}", f"K{head + 23}", f"K{head + 24}")
        out.append(_V4ObjectLayout(
            obj, twin, by_key[twin].prefix, head, head - twin_head, ohead,
            ohead - twin_ohead, head + 18 if obj.sale_gate else 0, head + 19,
            under, over, guest, uprice, oprice, tep_row, report_row))
        slot += 1
    return tuple(out)


_V4_OBJECT_LAYOUTS = _v4_object_layouts()
_V4_EXTRA_OBJECT_LAYOUTS = tuple(lay for lay in _V4_OBJECT_LAYOUTS if lay.extra)

# Какие дописанные объекты есть в ЭТОЙ книге. Раскладка выше — все объекты
# реестра, и адреса у них постоянные; но второй офисник пишется в книгу, только
# когда он в проекте. Книга проекта без вторых объектов обязана совпасть с
# прежней поячеечно — блоки выключенных объектов добавили бы ей десять тысяч
# ячеек и сдвинули бы лист «Вводные», ничего не посчитав. ФОК стоит в книге
# всегда: он дописан первым и книга несёт его давно (`_v4_book_objects`).
#
# Набор живёт в контексте сборки, а не в глобальной переменной: книги
# собираются параллельно, и чужой проект не должен решать, что есть в этом.
# Без сборки (None) в книге все объекты — так раскладку читают проверки.
_V4_BOOK_OBJECTS: contextvars.ContextVar[frozenset[str] | None] = contextvars.ContextVar(
    "_V4_BOOK_OBJECTS", default=None)


def _v4_book_objects(inputs: dict[str, Any]) -> frozenset[str]:
    """Объекты этой книги: шаблон и ФОК всегда, второй объект — если включён."""
    return frozenset(o.key for o in STANDALONE_OBJECTS
                     if not o.family or b(inputs, o.enabled_key))


def _v4_in_book(key: str) -> bool:
    active = _V4_BOOK_OBJECTS.get()
    return active is None or key in active


def _v4_extras() -> tuple["_V4ObjectLayout", ...]:
    """Дописанные объекты этой книги, в порядке раскладки."""
    return tuple(lay for lay in _V4_EXTRA_OBJECT_LAYOUTS if _v4_in_book(lay.obj.key))


def _v4_layouts() -> tuple["_V4ObjectLayout", ...]:
    """Все объекты этой книги — шаблона и дописанные."""
    return tuple(lay for lay in _V4_OBJECT_LAYOUTS if _v4_in_book(lay.obj.key))


def _v4_input_in_book(input_key: str) -> bool:
    """Вводная принадлежит объекту этой книги (или ни одному объекту)."""
    owner = next((lay.obj.key for lay in _V4_EXTRA_OBJECT_LAYOUTS
                  if input_key.startswith(lay.obj.prefix + "_")), None)
    return owner is None or _v4_in_book(owner)


def _v4_label_in_book(label: str) -> bool:
    """Строка карты, подписанная именем объекта, — объекта этой книги."""
    owner = next((lay.obj.key for lay in _V4_EXTRA_OBJECT_LAYOUTS
                  if label == (lay.obj.group_label or lay.obj.label)), None)
    return owner is None or _v4_in_book(owner)


def _v4_layout(key: str) -> _V4ObjectLayout:
    return next(lay for lay in _V4_OBJECT_LAYOUTS if lay.obj.key == key)


def _v4_row_shift(coord: str, offset: int) -> str:
    """«K43» со сдвигом на 83 — «K126»; пустая ячейка остаётся пустой."""
    if not coord:
        return coord
    match = re.match(r"([A-Z]+)(\d+)$", coord)
    return f"{match.group(1)}{int(match.group(2)) + offset}"


_V4_INPUT_CELLS: dict[str, str] = {
    "purchase_price_mln": "B15", "land_rights_cost_mln": "B16",
    "social_compensation_mln": "B17", "marketing_pct": "B19", "selling_pct": "B20",
    "profit_tax_pct": "B21", "vat_pct": "B22", "discount_rate_pct": "B23",
    "bridge_spread_pp": "B25", "pf_spread_pp": "B27", "pf_special_pct": "B28",
    "limit_fee_pct": "B29", "reservation_fee_pct": "B30",
    # Ставка на старте и срок нормализации писались рукописным put, и подпись
    # оставалась шаблонная — `key_rate_start_pct`, `key_rate_decline_months`.
    # Одно число под двумя именами: сверить книгу с движком по ключу нельзя.
    "rate_start_pct": "B33", "rate_normalization_months": "B35",
    "ird_th_per_sqm": "B40", "design_p_th_per_sqm": "B41",
    "design_rd_th_per_sqm": "B42", "preparation_th_per_sqm": "B43",
    "main_above_th_per_sqm": "B44", "main_under_th_per_sqm": "B45",
    "utilities_th_per_sqm": "B46", "landscaping_th_per_sqm": "B47",
    "commissioning_th_per_sqm": "B48", "site_maintenance_th_per_sqm": "B49",
    "gc_fee_pct": "B50", "author_supervision_pct": "B51",
    "project_management_pct": "B52", "technical_supervision_pct": "B53",
    "reserve_pct": "B54",
    "apartment_price_th": "B59", "commercial_price_th": "B60",
    "parking_price_th": "B61", "storage_price_th": "B62",
    "share_before_rve_pct": "B63", "monthly_growth_pre_pct": "B64",
    "monthly_growth_post_pct": "B65",
    # sales_lag_months здесь НЕ стоит: ячейку B68 не читает ни одна формула,
    # лаг живёт колонкой G блока очередей — у каждой очереди свой. Один ключ
    # на двух ячейках означал бы, что правка живой и правка мёртвой выглядят
    # одинаково.
    "residual_sales_months": "B69",
    "vri_periodicity_months": "B78", "vri_interest_spread_pp": "B81",
    "vri_relief_mln": "B82", "vri_security_cost_mln": "B83",
    # Свои деньги до ПФ. Поля не было в карте, и книга считала весь разрыв до
    # РнС банковским: пик БРИДЖа расходился ровно на внесённую сумму (3,2 млрд
    # на Вест Гарден), а следом проценты, налог, прибыль и LLCR. Место у поля
    # не в блоке финансирования только потому, что там нет ни одной пустой
    # строки, а вставлять строку в шаблон нельзя — поедут все ссылки.
    "pre_pf_own_funds_mln": "B85",
    "site_area_ha": "K7",
    "offices_gba_sqm": "K23", "offices_saleable_sqm": "K24",
    "offices_start": "K27", "offices_months": "K28",
    "offices_cost_th_per_sqm": "K29", "offices_sales_start": "K30",
    "offices_price_th_per_sqm": "K31", "offices_share_before_rve_pct": "K32",
    "offices_growth_pre_pct": "K34", "offices_growth_post_pct": "K35",
    "retail_gba_sqm": "K43", "retail_saleable_sqm": "K44",
    "retail_start": "K47", "retail_months": "K48",
    "retail_cost_th_per_sqm": "K49", "retail_sales_start": "K50",
    "retail_price_th_per_sqm": "K51", "retail_share_before_rve_pct": "K52",
    "retail_growth_pre_pct": "K54", "retail_growth_post_pct": "K55",
    # Паркинг отдельно стоящих объектов — свободный низ листа: вставить строку в
    # занятое место нельзя, поедут все ссылки. Норматив (К1, К2, таблицы
    # города) книге не сосчитать и он остаётся у движка, а РАЗМЕЩЕНИЕ — это
    # два числа и множитель, их книга считает сама: «если величина в книге не
    # выражается формулой, значит не хватает не формулы, а вводной».
    "object_parking_area_per_space_sqm": "K158",
    "object_parking_over_area_per_space_sqm": "K160",
    "offices_parking_under_spaces": "K161",
    "offices_parking_over_spaces": "K162",
    "retail_parking_under_spaces": "K163",
    "retail_parking_over_spaces": "K164",
    "offices_parking_guest_pct": "K167",
    "offices_parking_under_price_mln_per_space": "K169",
    "offices_parking_over_price_mln_per_space": "K170",
    "above_parking_spaces": "K63", "above_parking_area_per_space_sqm": "K64",
    "above_parking_cost_mln_per_space": "K67", "above_parking_start": "K68",
    "above_parking_months": "K69", "above_parking_sales_start": "K70",
    "above_parking_price_mln_per_space": "K71",
    "above_parking_share_before_rve_pct": "K72",
    "above_parking_growth_pre_pct": "K74", "above_parking_growth_post_pct": "K75",
}
# Ячейки книги, чьё значение не вводная, а ответ движка на неё: своего поля у
# величины нет, и писать в книгу пришлось бы пустоту или старое сохранённое.
_V4_DERIVED_INPUTS: dict[str, Callable[[dict[str, Any]], Any]] = {
    "object_parking_area_per_space_sqm": lambda x: object_parking_area_per_space(x),
}
_V4_DATE_KEYS = frozenset({
    "offices_start", "offices_sales_start", "retail_start", "retail_sales_start",
    "above_parking_start", "above_parking_sales_start",
})
_V4_BOOL_CELLS = {  # ключ -> ячейка «Да/Нет»
    "offices_enabled": "K20", "retail_enabled": "K40", "above_parking_enabled": "K60",
}


def _v4_extra_object_cells(cells: dict[str, str],
                           layouts: tuple[_V4ObjectLayout, ...] | None = None,
                           ) -> dict[str, str]:
    """Ячейки вводных дописанного объекта — ячейки двойника со сдвигом.

    Ключ живёт там же, где решается, куда писать значение: второго списка
    «какой ключ в какой ячейке» не бывает, а у копии блока ключи те же, что у
    образца, с приставкой своего объекта.
    """
    out: dict[str, str] = {}
    for lay in (_V4_EXTRA_OBJECT_LAYOUTS if layouts is None else layouts):
        if not lay.extra:
            continue
        twin_head = lay.input_head - lay.input_offset
        for key, coord in cells.items():
            if not key.startswith(lay.twin_prefix + "_"):
                continue
            row = int(re.sub(r"[A-Z]+", "", coord))
            if twin_head <= row < twin_head + _V4_INPUT_BLOCK_ROWS:
                out[lay.obj.prefix + key[len(lay.twin_prefix):]] = _v4_row_shift(
                    coord, lay.input_offset)
        for suffix, coord in (("parking_under_spaces", lay.parking_under),
                              ("parking_over_spaces", lay.parking_over),
                              ("parking_guest_pct", lay.parking_guest),
                              ("parking_under_price_mln_per_space", lay.parking_under_price),
                              ("parking_over_price_mln_per_space", lay.parking_over_price)):
            if coord:
                out[f"{lay.obj.prefix}_{suffix}"] = coord
    return out


_V4_INPUT_CELLS.update(_v4_extra_object_cells(_V4_INPUT_CELLS))
_V4_DATE_KEYS = _V4_DATE_KEYS | frozenset(
    f"{lay.obj.prefix}_{name}" for lay in _V4_EXTRA_OBJECT_LAYOUTS
    for name in ("start", "sales_start"))
_V4_BOOL_CELLS.update({lay.obj.enabled_key: f"K{lay.input_head + 2}"
                       for lay in _V4_EXTRA_OBJECT_LAYOUTS})
# Проценты в этих ячейках движок хранит пунктами, но сами ключи без суффикса.
_V4_NO_PCT_KEYS = frozenset({"vri_relief_mln", "vri_security_cost_mln"})


def _v4_excel_serial(value: Any) -> float | None:
    """ISO-дата -> серийный номер Excel (стиль даты уже стоит на ячейке)."""
    try:
        parsed = datetime.strptime(str(value)[:10], "%Y-%m-%d").date()
    except Exception:
        return None
    return float((parsed - date(1899, 12, 30)).days)


def _v4_number(value: Any) -> str:
    number = float(value)
    if number == int(number) and abs(number) < 1e15:
        return str(int(number))
    return format(number, ".10g")


def _v4_set_cell(
    xml: str,
    coord: str,
    *,
    number: Any = None,
    text: str | None = None,
    formula: str | None = None,
) -> tuple[str, bool]:
    """Заменяет содержимое ячейки, сохраняя её стиль. Формат листа — теги x:."""
    pattern = re.compile(
        r'<x:c r="%s"([^>]*?)(?:/>|>.*?</x:c>)' % re.escape(coord), re.S)
    found = pattern.search(xml)
    if not found:
        return xml, False
    style = re.search(r'\ss="(\d+)"', found.group(1))
    style_attr = f' s="{style.group(1)}"' if style else ""
    if formula is not None:
        body = f"<x:f>{xml_escape(formula)}</x:f>"
        replacement = f'<x:c r="{coord}"{style_attr}>{body}</x:c>'
    elif text is not None:
        replacement = (
            f'<x:c r="{coord}"{style_attr} t="inlineStr">'
            f"<x:is><x:t>{xml_escape(str(text))}</x:t></x:is></x:c>"
        )
    else:
        replacement = f'<x:c r="{coord}"{style_attr}><x:v>{_v4_number(number)}</x:v></x:c>'
    return xml[:found.start()] + replacement + xml[found.end():], True



# Режимы на листе «Вводные» берутся из канонического FIELD_GROUPS и
# реестра объектов. Отдельного списка «что показать dropdown-ом» нет:
# добавили select/checkbox/finance_select — он автоматически попадает сюда,
# если не объявлен engine-only с причиной.
_V4_MODE_KINDS = frozenset({"select", "checkbox", "finance_select"})


def _v4_declared_mode_fields() -> dict[str, Any]:
    """Все объявленные режимы DevelopAid, включая генерируемые поля объектов."""
    out: dict[str, Any] = {}
    for _group, fields in FIELD_GROUPS:
        for field in fields:
            if len(field) >= 4 and str(field[3]) in _V4_MODE_KINDS:
                out[str(field[0])] = field
    # Прогноз ставки исторически живёт отдельным каноническим блоком страницы,
    # а не FIELD_GROUPS. Это не Excel-список: берём то же объявление формы.
    for field in globals().get("_M2_RATE_INPUTS", ()):
        if len(field) >= 4 and str(field[3]) in _V4_MODE_KINDS:
            out[str(field[0])] = field
    return out


def _v4_mode_pairs(key: str) -> list[list[str]]:
    """Canonical internal/display pairs of one mode, from the page declaration."""
    field = _v4_declared_mode_fields().get(key)
    if field and len(field) > 4 and isinstance(field[4], list):
        return [[str(pair[0]), str(pair[1])] for pair in field[4]]
    if key == "rate_scenario":
        return [[str(pair[0]), str(pair[1])]
                for pair in globals().get("_M2_RATE_SCENARIOS", ())]
    return [[str(pair[0]), str(pair[1])]
            for pair in globals().get("_M2_EXTRA_OPTIONS", {}).get(key, ())]


def _v4_mode_display(key: str, internal: Any) -> str:
    """Показываем пользователю display value, а не технический API value."""
    value = "" if internal is None else str(internal)
    if isinstance(internal, bool):
        value = "1" if internal else "0"
    for raw, shown in _v4_mode_pairs(key):
        if value == raw:
            return shown
    return value


def _v4_live_mode_options() -> dict[str, list[str]]:
    """Русские display values всех режимов, которые Excel умеет менять live."""
    out: dict[str, list[str]] = {}
    for key, field in _v4_declared_mode_fields().items():
        if key in V4_INPUTS_NOT_IN_BOOK:
            continue
        kind = str(field[3])
        if kind == "checkbox":
            out[key] = ["Да", "Нет"]
            continue
        pairs = _v4_mode_pairs(key)
        if pairs:
            out[key] = [shown for _raw, shown in pairs]
    return out


def _v4_formula_literal(value: str) -> str:
    return '"' + str(value).replace('"', '""') + '"'


def _v4_mode_decode_formula(key: str, entry_coord: str,
                            output_by_internal: dict[str, str] | None = None,
                            *, fallback: str = '""') -> str:
    """Display value пользовательского листа -> значение, которое ждут формулы."""
    ref = f"'Вводные'!{entry_coord}"
    pairs = _v4_mode_pairs(key)
    expression = fallback
    for internal, shown in reversed(pairs):
        output = (output_by_internal or {}).get(internal, internal)
        if re.fullmatch(r"-?\d+(?:\.\d+)?", str(output)):
            result = str(output)
        else:
            result = _v4_formula_literal(str(output))
        expression = (
            f"IF({ref}={_v4_formula_literal(shown)},{result},{expression})")
    return expression


def _v4_apply_mode_decoders(xml: str, entry_report: dict[str, Any],
                            rate_scenario_ref: str | None,
                            missing: list[str]) -> str:
    """Декодеры между русским dropdown и историческими формулами шаблона.

    Пользователь всегда видит canonical display. Параметры модели получают
    ровно тот тип/слово, которое ожидали до появления dropdown — поэтому
    downstream формулы не приходится переписывать по всей книге.
    """
    moved = entry_report.get("map") or {}

    def source_coord(ref: str | None) -> str | None:
        if not ref:
            return None
        return str(ref).replace("$", "").split("!")[-1]

    def rewrite(source: str, formula: str, key: str) -> None:
        nonlocal xml
        if source not in moved:
            missing.append(f"Вводные · decoder {key}: пользовательская ячейка не найдена")
            return
        xml, done = _v4_set_cell(xml, source, formula=formula)
        if not done:
            missing.append(f"Параметры модели · decoder {key}: {source} не найден")

    # Периодичность хранится числом в формулах графика, но человек выбирает
    # «Ежемесячно / Ежеквартально / ...».
    periodic_entry = moved.get("B78")
    if periodic_entry:
        periodic_formula = _v4_mode_decode_formula(
            "vri_periodicity_months", periodic_entry, fallback="3")
        # Движок принудительно ставит квартал для Москвы независимо от выбора;
        # Excel обязан повторять это ограничение, а не считать иной график.
        rewrite("B78", f'IF($K$6="Москва",3,{periodic_formula})',
                "vri_periodicity_months")

    # Трёхсостояние «По региону» раньше схлопывалось в Да/Нет ещё builder-ом.
    # Теперь оно живое: Москва разрешает default в «Да», МО — в «Нет».
    interest_entry = moved.get("B80")
    if interest_entry:
        interest_ref = f"'Вводные'!{interest_entry}"
        interest_formula = (
            f"IF({interest_ref}={_v4_formula_literal('По региону')},"
            f'IF($K$6="Москва","Да","Нет"),'
            f"IF({interest_ref}={_v4_formula_literal('Начисляются')},"
            f'"Да","Нет"))')
        rewrite("B80", interest_formula, "vri_interest_enabled")

    # Проценты БРИДЖа при РнС: display страницы → слово, которое ждут формулы
    # CF (`_V4_BRIDGE_MODE_NAMES`). Без декодера «Выплата при
    # рефинансировании» не попадала ни в одну ветку формул.
    bridge_entry = moved.get("B31")
    if bridge_entry:
        rewrite("B31", _v4_mode_decode_formula(
            "bridge_interest_mode", bridge_entry, _V4_BRIDGE_MODE_NAMES,
            fallback=_v4_formula_literal("Капитализация в ПФ")),
            "bridge_interest_mode")

    # На странице сценарии называются по-русски; лист «Ставки» исторически
    # ждёт имена колонок Base/Upside/Downside.
    rate_source = source_coord(rate_scenario_ref)
    if rate_source and rate_source in moved:
        outputs = {
            internal: _V4_RATE_SCENARIO_NAMES.get(internal, internal)
            for internal, _shown in _v4_mode_pairs("rate_scenario")
        }
        rewrite(rate_source, _v4_mode_decode_formula(
            "rate_scenario", moved[rate_source], outputs, fallback='"Base"'),
            "rate_scenario")
    return xml


def _v4_cell_text(xml: str, coord: str) -> str | None:
    found = re.search(r'<x:c r="%s"[^>]*>(.*?)</x:c>' % re.escape(coord), xml, re.S)
    if not found:
        return None
    inline = re.search(r"<x:t>(.*?)</x:t>", found.group(1), re.S)
    if inline:
        return html.unescape(inline.group(1))
    value = re.search(r"<x:v>(.*?)</x:v>", found.group(1), re.S)
    return html.unescape(value.group(1)) if value else None


def _v4_input_field_meta() -> dict[str, tuple[str, str]]:
    """Ключ поля → (тип, единица) из единого FIELD_GROUPS."""
    field_meta: dict[str, tuple[str, str]] = {}
    for _group, fields in FIELD_GROUPS:
        for field in fields:
            if len(field) >= 4:
                field_meta[str(field[0])] = (str(field[3]), str(field[2]))
    for field in globals().get("_M2_RATE_INPUTS", ()):
        if len(field) >= 4:
            field_meta.setdefault(str(field[0]), (str(field[3]), str(field[2])))
    return field_meta


_V4_FMT_DATE = "dd.mm.yyyy"
_V4_FMT_PCT = "0.0%;[Red](0.0%);-"
_V4_FMT_PCT_FINE = "0.00%;[Red](0.00%);-"
_V4_FMT_COUNT = "0"
_V4_FMT_AREA = "#,##0;[Red](#,##0);-"
_V4_FMT_AMOUNT = "#,##0.0;[Red](#,##0.0);-"
_V4_FMT_AMOUNT_FINE = "#,##0.00;[Red](#,##0.00);-"


def _v4_input_format_code(kind: str, unit: str, value: Any = None) -> str | None:
    """Формат числа вводной по типу и единице поля — одно решение на книгу.

    Все коды — из каталога шаблона (dd.mm.yyyy, 0.0%, 0, #,##0, #,##0.0):
    своих форматов книга не заводит. Дробная часть решается по записанному
    значению: 2,75 тыс. ₽/м² форматом #,##0.0 показалось бы 2,8 — число на
    экране разошлось бы с числом в ячейке. Текстовое поле — None: формат
    ему не нужен.
    """
    if kind == "date":
        return _V4_FMT_DATE
    if kind != "number":
        return None
    unit = (unit or "").strip()
    try:
        number = float(value)
    except (TypeError, ValueError):
        number = None

    def decimals(scale: float = 1.0) -> int:
        if number is None:
            return 0
        text = f"{abs(number) * scale:.10f}".rstrip("0")
        return len(text.split(".")[1]) if "." in text else 0

    if unit.startswith("%") or unit.startswith("п.п."):
        return _V4_FMT_PCT_FINE if decimals(100) > 1 else _V4_FMT_PCT
    if re.match(r"(мес|лет|год|шт|мест|пос\.)", unit):
        return _V4_FMT_COUNT
    if (unit.startswith("м²") and unit[2:3] not in ("/", "(")) or unit.startswith("м "):
        return _V4_FMT_AREA
    return _V4_FMT_AMOUNT_FINE if decimals() > 1 else _V4_FMT_AMOUNT


_V4_INPUT_BLOCKS = (("D", "B"), ("H", "F"), ("M", "K"))

# Вводные с ключом, которого нет в FIELD_GROUPS: служебные поля книги.
_V4_KEYED_INPUT_FORMATS = {
    "engine_horizon_end": _V4_FMT_DATE,
    "vri_obligation_lead_months": _V4_FMT_COUNT,
    "social_cash_part_mln": _V4_FMT_AMOUNT,
    # Очередь объекта — число; объекты из реестра, вторые включительно.
    **{f"{_obj.prefix}_queue": _V4_FMT_COUNT for _obj in STANDALONE_OBJECTS},
    # Площадь подземного места гаража ОСЗ своего поля не имеет — это норматив
    # класса (`object_parking_area_per_space`), и формат его ячейки — здесь.
    "object_parking_area_per_space_sqm": _v4_input_format_code("number", "м²/место", 35),
}
_V4_FMT_MULTIPLE = "0.00x;[Red](0.00x);-"
# Таблица очередей «Параметров модели» (строки 88–91): колонка → формат.
_V4_QUEUE_INPUT_FORMATS = {
    "E": _V4_FMT_COUNT, "F": _V4_FMT_COUNT, "G": _V4_FMT_COUNT,
    "W": _V4_FMT_AREA, "X": _V4_FMT_AREA, "Y": _V4_FMT_AREA,
    "Z": _V4_FMT_AREA, "AA": _V4_FMT_AREA, "AB": _V4_FMT_AREA, "AC": _V4_FMT_AREA,
    "AS": _V4_FMT_AMOUNT,
}
# Блок соцобъектов «Вводных»: колонка → формат (заголовки пишет
# `_v4_social_rows_xml`; F — формула стоимости, она не ввод).
_V4_SOCIAL_INPUT_FORMATS = {
    "B": _V4_FMT_AREA, "C": _V4_FMT_AMOUNT_FINE, "D": _V4_FMT_DATE, "E": _V4_FMT_COUNT,
    "G": _V4_FMT_MULTIPLE, "L": _V4_FMT_AREA, "M": _V4_FMT_AMOUNT, "P": _V4_FMT_PCT,
}


def _v4_block_input_formats(social_base_row: int | None,
                            ladder_refs: list[tuple[str, str]],
                            population_norm_ref: str | None) -> dict[str, str]:
    """Форматы вводных без ключа поля — по месту, которое знает их сборщик."""
    out: dict[str, str] = {}
    for row in range(_V4_CF_QUEUE_ENABLED_ROW, _V4_CF_QUEUE_ENABLED_ROW + _V4_CAPEX_PHASES):
        for column, code in _V4_QUEUE_INPUT_FORMATS.items():
            out[f"{column}{row}"] = code
    if social_base_row is not None:
        for type_index in range(len(_V4_SOCIAL_TYPES)):
            for phase in range(4):
                row = _v4_social_row(social_base_row, type_index, phase)
                for column, code in _V4_SOCIAL_INPUT_FORMATS.items():
                    out[f"{column}{row}"] = code
        out[f"F{_v4_social_cash_row(social_base_row)}"] = _V4_FMT_AMOUNT
    for edge_ref, rate_ref in ladder_refs:
        out[edge_ref.split("!")[-1].replace("$", "")] = _V4_FMT_MULTIPLE
        out[rate_ref.split("!")[-1].replace("$", "")] = _V4_FMT_PCT_FINE
    if population_norm_ref:
        out[population_norm_ref.replace("$", "")] = _V4_FMT_AREA
    return out


def _v4_type_input_formats(xml: str, styles: str,
                           extra: dict[str, str] | None = None) -> tuple[str, str]:
    """У каждой вводной с ключом — формат её поля.

    Шаблон и дописанные нами строки ставили вводным стиль с General: цель
    ставки 9% читалась как 0,09, дата старта — как 46227, суммы — без
    разрядов. Стиль ячейки меняется только в формате числа (xf клонируется у
    шаблона), и только там, где формат обещает не то семейство: General,
    процент у суммы, число у процента. Удачный формат шаблона того же
    семейства остаётся его решением.

    Вводные без ключа поля (таблицы соцобъектов, очередей, ступеней ставки)
    приходят явной картой `extra` «ячейка → формат»: угадывать тип по
    подписи колонки значило бы однажды назвать сумму процентом.
    """
    field_meta = _v4_input_field_meta()
    entry = v4_entry_sheet.style_map(styles)["entry"]
    rows = [int(number) for number in re.findall(r'<x:row r="(\d+)"', xml)]
    wanted: dict[str, str] = {}
    for key_col, value_col in _V4_INPUT_BLOCKS:
        for row in range(1, max(rows, default=0) + 1):
            key = _v4_cell_text(xml, f"{key_col}{row}")
            coord = f"{value_col}{row}"
            if key in _V4_KEYED_INPUT_FORMATS:
                wanted[coord] = _V4_KEYED_INPUT_FORMATS[key]
                continue
            if key not in field_meta or key in V4_INPUTS_NOT_IN_BOOK:
                continue
            code = _v4_input_format_code(*field_meta[key], _v4_cell_text(xml, coord))
            if code is not None:
                wanted[coord] = code
    for coord, code in (extra or {}).items():
        wanted.setdefault(coord, code)
    for coord, code in wanted.items():
        found = re.search(r'<x:c r="%s"([^>]*?)(/?>)' % re.escape(coord), xml)
        if not found:
            continue
        if code == _V4_FMT_DATE:
            # Ноль в поле даты — «не задана», а не 00.01.1900. И читатели
            # книги (openpyxl, наш вычислитель) превращают ноль под форматом
            # даты во время суток 00:00, на котором встаёт любая арифметика.
            try:
                if float(_v4_cell_text(xml, coord) or 0) <= 0:
                    continue
            except ValueError:
                continue
        style = re.search(r'\ss="(\d+)"', found.group(1))
        if not style or int(style.group(1)) not in entry:
            continue
        current = v4_entry_sheet.format_code(
            styles, v4_entry_sheet.num_fmt_id(styles, int(style.group(1))))
        have = v4_entry_sheet.format_family(current)
        if have != "general" and have == v4_entry_sheet.format_family(code):
            continue
        styles, fmt_id = v4_entry_sheet.with_format(styles, code)
        styles, new_style = v4_entry_sheet.xf_with_format(styles, int(style.group(1)), fmt_id)
        attrs = re.sub(r'\ss="\d+"', f' s="{new_style}"', found.group(1), count=1)
        xml = (xml[:found.start()] + f'<x:c r="{coord}"{attrs}{found.group(2)}'
               + xml[found.end():])
    return xml, styles


def _v4_with_number_format(xml: str, coord: str, code: str, styles: str
                           ) -> tuple[str, str, bool]:
    """Ячейке — формат числа `code`; цвет и рамка её стиля остаются.

    → (лист, styles.xml, найдена ли ячейка).
    """
    found = re.search(r'<x:c r="%s"([^>]*?)(/?>)' % re.escape(coord), xml)
    if not found:
        return xml, styles, False
    style = re.search(r'\ss="(\d+)"', found.group(1))
    styles, fmt_id = v4_entry_sheet.with_format(styles, code)
    styles, new_style = v4_entry_sheet.xf_with_format(
        styles, int(style.group(1)) if style else 0, fmt_id)
    attrs = (re.sub(r'\ss="\d+"', f' s="{new_style}"', found.group(1), count=1) if style
             else f'{found.group(1)} s="{new_style}"')
    return (xml[:found.start()] + f'<x:c r="{coord}"{attrs}{found.group(2)}'
            + xml[found.end():], styles, True)


_V4_REF_ONLY = re.compile(r"^\s*'?([^'!]+)'?!\$?([A-Z]{1,3})\$?(\d+)\s*$")


def _v4_report_number_formats(report_xml: str, tep_xml: str, consolidator_xml: str,
                              styles: str) -> tuple[str, str, str]:
    """Числа ОТЧЁТа и расшифровки ТЭП — с форматом, а не General.

    Дописанные нами ячейки (строка дефолта, соцобъекты, подземные метры и
    итог структуры продукта) и ссылки шаблона на КОНСОЛИДАТОР шли без
    формата: 2 349,1 млн читались как 2349.07318, даты как 46905. Формат
    задан здесь явно — по месту, которое пишет сборщик, — а у ссылки
    `=КОНСОЛИДАТОР!X` он берётся у её источника, как у читалок «Вводных».
    """
    tep_formats: dict[str, str] = {}
    for tep_row in (40, 41, 42):
        tep_formats.update({f"B{tep_row}": _V4_FMT_AREA, f"C{tep_row}": _V4_FMT_AREA,
                            f"E{tep_row}": _V4_FMT_AMOUNT, f"F{tep_row}": _V4_FMT_AREA})
    tep_formats["E43"] = _V4_FMT_AMOUNT

    report_formats: dict[str, str] = {f"B{_V4_REPORT_DEFAULT_ROW}": _V4_FMT_AMOUNT}
    for report_row in (33, 34, 35):
        report_formats.update({f"F{report_row}": _V4_FMT_AREA,
                               f"H{report_row}": _V4_FMT_AMOUNT})
    report_formats.update({"H36": _V4_FMT_AMOUNT, "H37": _V4_FMT_AMOUNT})
    under, total = _V4_UNDER_COLUMN, _V4_PRODUCT_STRUCTURE_TOTAL_ROW
    for row in range(_V4_PRODUCT_STRUCTURE_FIRST_ROW, total + 1):
        report_formats[f"{under}{row}"] = _V4_FMT_AREA
    report_formats.update({f"B{total}": _V4_FMT_AREA, f"C{total}": _V4_FMT_AREA,
                           f"D{total}": _V4_FMT_AREA, f"E{total}": _V4_FMT_AMOUNT})
    for column in "BCDEF":
        report_formats[f"{column}73"] = _V4_FMT_AMOUNT

    # Сравнение очередей — ссылки на КОНСОЛИДАТОР строка в строку: формат у
    # каждой — формат её источника, второго ответа «как это показать» нет.
    for cell in re.finditer(r'<x:c r="([A-Z]+\d+)"[^>]*?>\s*<x:f>([^<]*)</x:f>', report_xml):
        link = _V4_REF_ONLY.match(html.unescape(cell.group(2)))
        if not link or link.group(1) != "КОНСОЛИДАТОР":
            continue
        source = re.search(r'<x:c r="%s%s"[^>]*?\ss="(\d+)"' % (link.group(2), link.group(3)),
                           consolidator_xml)
        fmt_id = v4_entry_sheet.num_fmt_id(styles, int(source.group(1)) if source else None)
        if fmt_id:
            report_formats.setdefault(cell.group(1), v4_entry_sheet.format_code(styles, fmt_id))

    # Нет ячейки — нет и числа, которое можно показать не тем форматом: без
    # блока соцобъектов, например, колонки F расшифровки ТЭП не пишутся.
    for coord, code in tep_formats.items():
        tep_xml, styles, _found = _v4_with_number_format(tep_xml, coord, code, styles)
    for coord, code in report_formats.items():
        report_xml, styles, _found = _v4_with_number_format(report_xml, coord, code, styles)
    return report_xml, tep_xml, styles


def _v4_mirror_secondary_input_styles(xml: str) -> str:
    """E:H — такая же форма ввода, как A:D, с правильным типом значения.

    Копировать стиль той же СТРОКИ нельзя: справа может стоять процент, а
    слева в этой строке — сумма или дата. Стиль Excel несёт number format,
    поэтому визуально похожая правка превращала 3% в 0,03. Образец выбирается
    по семейству формата, которое решает `_v4_input_format_code`, — тем же
    решением, что и формат вводных A:D и J:M; точный формат ставит следом
    `_v4_type_input_formats`.
    """
    field_meta = _v4_input_field_meta()

    def style_of(coord: str) -> str | None:
        found = re.search(r'<x:c r="%s"[^>]*?\ss="(\d+)"' % re.escape(coord), xml)
        return found.group(1) if found else None

    # Штатные образцы шаблона: обычное число, процент, дата и текстовый режим.
    exemplar = {
        "label": style_of("A15"),
        "number": style_of("B15"),
        "pct": style_of("B19"),
        "date": style_of("B8"),
        "text": style_of("B31"),
        "readonly": (str(_v4_formula_style_id())
                     if _v4_formula_style_id() is not None else None),
        "unit": style_of("C15"),
        "key": style_of("D15"),
        "header": str(_v4_header_style_id()) if _v4_header_style_id() is not None else None,
    }

    def set_style(coord: str, style: str | None) -> None:
        nonlocal xml
        if style is None:
            return
        pattern = re.compile(r'(<x:c r="%s")([^>]*)' % re.escape(coord))
        def apply(match: "re.Match[str]") -> str:
            attrs = re.sub(r'\s+s="\d+"', "", match.group(2))
            return f'{match.group(1)}{attrs} s="{style}"'
        xml = pattern.sub(apply, xml, count=1)

    for row in range(1, 160):
        key = _v4_cell_text(xml, f"H{row}")
        has_e = _v4_cell_text(xml, f"E{row}") is not None
        has_f = (_v4_cell_text(xml, f"F{row}") is not None
                 or _v4_cell_formula(xml, f"F{row}") is not None)
        if not has_e:
            continue
        if not key and not has_f:
            set_style(f"E{row}", exemplar["header"])
            continue
        if str(key) not in field_meta:
            # В H стоит не ключ, а текст шаблона: заголовок «ОЧЕРЕДИ ПРОЕКТА»
            # растянут по E:H, и его F-клетка — не вводная. Покрашенная в
            # стиль ввода, она уезжала на «Вводные» пустой жёлтой ячейкой,
            # которую не читает ни одна формула.
            continue

        set_style(f"E{row}", exemplar["label"])
        set_style(f"G{row}", exemplar["unit"])
        set_style(f"H{row}", exemplar["key"])

        kind, unit = field_meta.get(str(key), ("text", ""))
        if str(key) in V4_INPUTS_NOT_IN_BOOK:
            # Engine-only значение остаётся результатом/основанием и не
            # получает стиль пользовательского ввода.
            value_style = exemplar["readonly"]
        else:
            code = _v4_input_format_code(kind, unit, _v4_cell_text(xml, f"F{row}"))
            family = v4_entry_sheet.format_family(code) if code else "text"
            value_style = exemplar.get(family, exemplar["number"])
        set_style(f"F{row}", value_style)
    return xml



def _v4_mark_engine_only_readonly(xml: str) -> str:
    """Engine-only поля не должны выглядеть редактируемыми на «Вводных».

    Координата выводится из API key в D/H/M, поэтому отдельной карты Excel для
    этого не существует. Формульный стиль не попадает в набор entry styles —
    v4_entry_sheet не переносит такую ячейку на пользовательский лист.
    """
    style = _v4_formula_style_id()
    if style is None:
        return xml
    key_columns = {"D": "B", "H": "F", "M": "K"}
    rows = [int(number) for number in re.findall(r'<x:row r="(\d+)"', xml)]
    max_row = max(rows, default=0)

    for key_col, value_col in key_columns.items():
        for row in range(1, max_row + 1):
            key = _v4_cell_text(xml, f"{key_col}{row}")
            if key not in V4_INPUTS_NOT_IN_BOOK:
                continue
            coord = f"{value_col}{row}"
            pattern = re.compile(r'(<x:c r="%s")([^>]*)' % re.escape(coord))
            def apply(match: "re.Match[str]") -> str:
                attrs = re.sub(r'\s+s="\d+"', "", match.group(2))
                return f'{match.group(1)}{attrs} s="{style}"'
            xml = pattern.sub(apply, xml, count=1)
    return xml


def _v4_strip_engine_only_from_entry(xml: str, params: str, entry_report: dict[str, Any],
                                     missing: list[str]) -> tuple[str, str]:
    """Убирает engine-only блоки из пользовательского листа «Вводные» — и
    возвращает их значения на расчётный лист.

    Стиль уже не жёлтый, но одной заливки недостаточно: Excel позволяет
    перепечатать любую незапароленную ячейку. Поэтому поле, которое не умеет
    пересчитываться offline, на пользовательском листе отсутствует целиком.
    Соседний блок той же строки (A:D, E:H или J:M) не затрагивается.

    Снятая ячейка при этом УЖЕ отдана расчётному листу зеркалом
    `='Вводные'!K6`: сборщик листа ввода перенёс её как вводную. Оставить
    зеркало на снятую ячейку — значит читать пустоту: регион «Москва» в K6
    становился пустым, все `$K$6="Москва"` — ложью, проценты по ВРИ «по
    региону» — «Нет», а паритет книги на рассрочке — СБОЙ. Поэтому значение
    возвращается на «Параметры модели» литералом, каким приехало из движка,
    и из карты переезда вычёркивается: для декодеров и инструкции такой
    вводной на листе ввода нет.
    """
    blocks = {"D": ("A", "B", "C", "D"),
              "H": ("E", "F", "G", "H"),
              "M": ("J", "K", "L", "M")}
    value_column = {"D": "B", "H": "F", "M": "K"}
    moved: dict[str, str] = entry_report.get("map") or {}
    back = {target: source for source, target in moved.items()}
    restored: list[str] = []
    rows = [int(number) for number in re.findall(r'<x:row r="(\d+)"', xml)]
    max_row = max(rows, default=0)
    for key_col, columns in blocks.items():
        for row in range(1, max_row + 1):
            key = _v4_cell_text(xml, f"{key_col}{row}")
            if key not in V4_INPUTS_NOT_IN_BOOK:
                continue
            value_coord = f"{value_column[key_col]}{row}"
            source = back.get(value_coord)
            if source:
                cell = re.search(r'<x:c r="%s"([^>]*)(?:/>|>(.*?)</x:c>)' % re.escape(value_coord),
                                 xml, re.S)
                is_text = bool(cell and re.search(r'\st="(?:inlineStr|str|s)"', cell.group(1)))
                value = _v4_cell_text(xml, value_coord)
                if value is None:
                    params, done = _v4_set_cell(params, source, text="")
                elif is_text:
                    params, done = _v4_set_cell(params, source, text=value)
                else:
                    try:
                        params, done = _v4_set_cell(params, source, number=float(value))
                    except ValueError:
                        params, done = _v4_set_cell(params, source, text=value)
                if not done:
                    missing.append(f"Параметры модели · engine-only {key}: {source} не найден")
                moved.pop(source, None)
                restored.append(source)
            for column in columns:
                coord = f"{column}{row}"
                xml = re.sub(
                    r'<x:c r="%s"[^>]*(?:/>|>.*?</x:c>)' % re.escape(coord),
                    "", xml, count=1, flags=re.S)
    entry_report["engine_only_restored"] = restored
    return xml, params


def _v4_add_mode_dropdowns(xml: str, missing: list[str]) -> str:
    """Data Validation для режимов, которые реально пересчитывает Excel.

    Ключ ищется в D/H/M; значение находится соответственно в B/F/K.
    Это позволяет не держать ещё одну карту координат и автоматически
    подхватывает переезд строк внутри существующей формы.
    """
    options = _v4_live_mode_options()
    validations: list[tuple[str, list[str]]] = []
    key_columns = {"D": "B", "H": "F", "M": "K"}
    # Пользовательский лист собирается заново, и ключи в нём бывают не только
    # inlineStr (<x:t>), но и строковыми <x:v>. Regex по одному виду строки
    # находил часть полей случайно: на реальной книге восемь живых режимов,
    # включая bridge_interest_mode, оставались без dropdown.
    row_numbers = [int(number) for number in re.findall(r'<x:row r="(\d+)"', xml)]
    max_row = max(row_numbers, default=0)
    for key, values in options.items():
        # Выключатель второго объекта, которого нет в этой книге, — не
        # потерянная вводная: его блок в книгу не пишется (`_v4_book_objects`).
        if not _v4_input_in_book(key):
            continue
        target: str | None = None
        for key_col, value_col in key_columns.items():
            for row in range(1, max_row + 1):
                if _v4_cell_text(xml, f"{key_col}{row}") == key:
                    target = f"{value_col}{row}"
                    break
            if target is not None:
                break
        # B75 исторически подписан сразу двумя ключами. После разделения
        # значения и срока координата режима однозначна, но старый составной
        # текст ключа может ещё жить в шаблоне до того, как builder его заменил.
        if key == "vri_payment_mode" and target is None and _v4_cell_text(xml, "B75") is not None:
            target = "B75"
        if target is None:
            # Ставка добавляется динамическим блоком; если ключа нет, это уже
            # потерянная вводная, и сборка должна сказать об этом.
            missing.append(f"Вводные · dropdown {key}: ячейка не найдена")
            continue
        if _v4_cell_text(xml, target) is None and _v4_cell_formula(xml, target) is None:
            missing.append(f"Вводные · dropdown {key}: значение {target} не найдено")
            continue
        validations.append((target, values))

    if not validations:
        return xml

    rendered: list[str] = []
    for coord, values in validations:
        formula = '"' + ",".join(str(value).replace('"', '""') for value in values) + '"'
        rendered.append(
            f'<x:dataValidation type="list" allowBlank="0" showDropDown="0" '
            f'showErrorMessage="1" errorStyle="stop" '
            f'errorTitle="Недопустимое значение" '
            f'error="Выберите значение из выпадающего списка." sqref="{coord}">'
            f'<x:formula1>{xml_escape(formula)}</x:formula1></x:dataValidation>')

    existing = re.search(
        r'<x:dataValidations([^>]*)>(.*?)</x:dataValidations>', xml, re.S)
    if existing:
        attrs = re.sub(r'\s+count="\d+"', "", existing.group(1))
        old_count = len(re.findall(r"<x:dataValidation\b", existing.group(2)))
        block = (f'<x:dataValidations{attrs} count="{old_count + len(rendered)}">'
                 + existing.group(2) + "".join(rendered) + "</x:dataValidations>")
        return xml[:existing.start()] + block + xml[existing.end():]

    block = (f'<x:dataValidations count="{len(rendered)}">'
             + "".join(rendered) + "</x:dataValidations>")
    # По схеме worksheet dataValidations идут после conditionalFormatting и
    # до hyperlinks/printOptions/pageMargins. У шаблона эти хвосты есть; если
    # конкретная версия их лишилась, перед закрытием worksheet Excel тоже
    # принимает блок.
    candidates = [
        xml.find("<x:hyperlinks"), xml.find("<x:printOptions"),
        xml.find("<x:pageMargins"), xml.find("<x:pageSetup"),
        xml.find("<x:headerFooter"), xml.find("<x:drawing"),
        xml.rfind("</x:worksheet>"),
    ]
    candidates = [index for index in candidates if index >= 0]
    if not candidates:
        missing.append("Вводные · dropdown: не найдено место для dataValidations")
        return xml
    at = min(candidates)
    return xml[:at] + block + xml[at:]


def _v4_column_letter(number: int) -> str:
    letters = ""
    while number > 0:
        number, rest = divmod(number - 1, 26)
        letters = chr(65 + rest) + letters
    return letters


def _v4_column_number(letters: str) -> int:
    number = 0
    for letter in letters:
        number = number * 26 + ord(letter) - 64
    return number


def _v4_row_xml(row: int, cells: list[str]) -> str:
    """Собирает строку листа, расставляя ячейки по возрастанию колонки.

    Excel требует от ячеек строки возрастающего порядка ссылок и молча
    выбрасывает те, что стоят после старшей колонки. Блок раздачи налога
    писал `A B C D E F G L M N O P H I J K` — и в Excel колонки «Налог О1…О4»
    оказывались ПУСТЫМИ, а «Итого» под ними нулём: чистая прибыль ОТЧЁТа шла
    без налога на прибыль (на четырёх очередях 56 598,6 вместо 42 128,6 при
    налоге 14 470,0). Наш вычислитель читает ячейки по координате и порядка
    не замечает — то есть книга и проверки расходились молча, а поймал это
    владелец глазами (14.09.2026).

    Поэтому строку собирает эта функция, а не конкатенация в порядке
    написания кода: порядок ячеек — свойство файла, а не порядка вычислений.
    """
    ordered = sorted(cells, key=lambda cell: _v4_column_number(
        re.match(r'<x:c r="([A-Z]+)', cell).group(1)))
    return f'<x:row r="{row}">' + "".join(ordered) + "</x:row>"


# Ширина помесячной сетки книги объявлена ЗДЕСЬ и больше нигде. Прежде тот же
# факт стоял в трёх видах — этой константой, числом `_V4_CAPEX_MONTH_COLUMNS`
# и одиннадцатью литералами `$DS$` внутри f-строк, — и протянуть книгу со 120
# месяцев до 180 значило найти все три копии. Цена промаха измерена: на четырёх
# очередях с шагом 36 горизонт движка 163 месяца, а книга обрезала его до 120 и
# собиралась МОЛЧА — CAPEX 36 769 против 49 085 млн ₽, EBITDA 190 против 2 701.
_V4_CF_FIRST_COL = 4                 # D
_V4_CF_LAST_COL = 183                # GA — 180 месяцев
_V4_LAST_COLUMN = _v4_column_letter(_V4_CF_LAST_COL)
_V4_MONTH_COLUMNS = _V4_CF_LAST_COL - _V4_CF_FIRST_COL + 1


def _v4_month_span(row: int, sheet: str = "") -> str:
    """Диапазон «весь горизонт» по строке листа: `$D$37:$GA$37`."""
    prefix = f"'{sheet}'!" if sheet else ""
    return f"{prefix}$D${row}:${_V4_LAST_COLUMN}${row}"


def _v4_cell_formula(xml: str, coord: str) -> str | None:
    """Формула ячейки как есть. Нет ячейки или нет формулы — `None`.

    Читается затем, чтобы правку строить НА НЕЙ, а не писать свою рядом: свою
    пришлось бы держать в согласии с шаблоном вручную, и она разошлась бы молча.
    """
    found = re.search(
        r'<x:c r="%s"[^>]*>(.*?)</x:c>' % re.escape(coord), xml, re.S)
    if not found:
        return None
    formula = re.search(r"<x:f>(.*?)</x:f>", found.group(1), re.S)
    return html.unescape(formula.group(1)) if formula else None


def _v4_col_number(letters: str) -> int:
    number = 0
    for ch in letters:
        number = number * 26 + (ord(ch) - 64)
    return number


def _v4_set_or_insert_cell(
    xml: str, coord: str, *, number: Any = None, text: str | None = None,
    formula: str | None = None,
) -> tuple[str, bool]:
    """Пишет в ячейку, а если её в XML нет — вставляет на своё место в строке.

    Пустых ячеек в файле не существует, и `_v4_set_cell` умеет только заменять
    существующую. Новая колонка (кассовые доли общепроектных статей) поэтому
    молча не записывалась. Порядок колонок внутри строки обязан расти, иначе
    Excel вправе счесть лист повреждённым.
    """
    updated, done = _v4_set_cell(xml, coord, number=number, text=text, formula=formula)
    if done:
        return updated, True
    letters = re.match(r"([A-Z]+)(\d+)", coord)
    if not letters:
        return xml, False
    column, row = letters.group(1), letters.group(2)
    row_pattern = re.compile(r'(<x:row r="%s"[^>]*>)(.*?)(</x:row>)' % row, re.S)
    found = row_pattern.search(xml)
    if not found:
        return xml, False
    if formula is not None:
        cell = f'<x:c r="{coord}"><x:f>{xml_escape(formula)}</x:f></x:c>'
    elif text is not None:
        cell = (f'<x:c r="{coord}" t="inlineStr">'
                f"<x:is><x:t>{xml_escape(str(text))}</x:t></x:is></x:c>")
    else:
        cell = f'<x:c r="{coord}"><x:v>{_v4_number(number)}</x:v></x:c>'
    body = found.group(2)
    insert_at = len(body)
    for existing in re.finditer(r'<x:c r="([A-Z]+)%s"' % row, body):
        if _v4_col_number(existing.group(1)) > _v4_col_number(column):
            insert_at = existing.start()
            break
    new_body = body[:insert_at] + cell + body[insert_at:]
    return (xml[:found.start()] + found.group(1) + new_body + found.group(3)
            + xml[found.end():]), True


_V4_ROW_CELL_RE = re.compile(r'<x:c r="([A-Z]{1,3})(\d+)"[^>]*?(?:/>|>.*?</x:c>)', re.S)


def _v4_row_formulas(xml: str, row: int) -> dict[str, str]:
    """Формулы всей строки за один проход по листу.

    Обратная сторона `_v4_set_cells`: читать ячейку за ячейкой так же дорого,
    как писать. Блок паркинга объектов читал 120 месяцев по четырём строкам в
    четырёх блоках — почти пять тысяч проходов по мегабайтному листу, и сборка
    книги подорожала с 3,2 до 15,0 секунды. Платил за это весь набор: книгу
    собирают 34 файла проверок, и полный прогон на CI вырос с 40 минут до 74.
    """
    found = re.search(
        r'<x:row r="%d"[^>]*?(?:/>|>(?P<body>.*?)</x:row>)' % row, xml, re.S)
    if not found:
        return {}
    out: dict[str, str] = {}
    for cell in _V4_ROW_CELL_RE.finditer(found.group("body") or ""):
        formula = re.search(r"<x:f>(.*?)</x:f>", cell.group(0), re.S)
        if formula:
            out[cell.group(1) + cell.group(2)] = html.unescape(formula.group(1))
    return out


def _v4_set_cells(xml: str, row: int, cells: dict[str, dict[str, Any]],
                  styles: dict[str, str | None] | None = None) -> tuple[str, bool]:
    """Пишет пачку ячеек ОДНОЙ строки за один проход по листу.

    Каждая ячейка искалась регуляркой по всему XML листа. У строки сноса и
    строки процентов ВРИ таких ячеек 120 на блок, блоков четыре, строк четыре —
    и сборка книги подорожала с 6,3 до 11,2 секунды, а вместе с ней весь набор
    тестов: он перестал укладываться в сорок пять минут CI. Лист теперь
    трогается один раз на строку, а не один раз на ячейку.
    """
    found = re.search(
        r'<x:row r="%d"(?P<attrs>[^>]*?)(?:/>|>(?P<body>.*?)</x:row>)' % row, xml, re.S)
    if not found:
        return xml, False
    body = found.group("body") or ""
    kept: dict[str, str] = {}
    for cell in _V4_ROW_CELL_RE.finditer(body):
        kept[cell.group(1) + cell.group(2)] = cell.group(0)
    styles = styles or {}
    for coord, payload in cells.items():
        style = styles.get(coord)
        if style is None:
            previous = kept.get(coord)
            got = re.search(r'\ss="(\d+)"', previous) if previous else None
            style = got.group(1) if got else None
        attr = f' s="{style}"' if style else ""
        if payload.get("formula") is not None:
            rendered = f'<x:c r="{coord}"{attr}><x:f>{xml_escape(payload["formula"])}</x:f></x:c>'
        elif payload.get("text") is not None:
            rendered = (f'<x:c r="{coord}"{attr} t="inlineStr">'
                        f'<x:is><x:t>{xml_escape(str(payload["text"]))}</x:t></x:is></x:c>')
        else:
            rendered = f'<x:c r="{coord}"{attr}><x:v>{_v4_number(payload.get("number"))}</x:v></x:c>'
        kept[coord] = rendered
    order = sorted(kept, key=lambda c: _v4_col_number(re.match(r"[A-Z]+", c).group(0)))
    rebuilt = f'<x:row r="{row}"{found.group("attrs") or ""}>' + "".join(
        kept[coord] for coord in order) + "</x:row>"
    return xml[:found.start()] + rebuilt + xml[found.end():], True


def _v4_ensure_row(xml: str, row: int) -> str:
    """Создаёт пустую строку листа, если её в XML нет вовсе.

    Пустых строк в файле не существует, а «Вводные» держат между блоками зазоры —
    и добавка группы обязана вставать в СВОЙ блок, а не в конец листа (решение
    владельца, 03.09.2026: править объект, листая от одной его половины к другой,
    нельзя). Строка вставляется на своё место по возрастанию номера: Excel вправе
    счесть лист повреждённым, если порядок нарушен, и это уже ловится тестом.
    """
    if re.search(r'<x:row r="%d"[ />]' % row, xml):
        return xml
    for existing in re.finditer(r'<x:row r="(\d+)"', xml):
        if int(existing.group(1)) > row:
            return xml[:existing.start()] + f'<x:row r="{row}"></x:row>' + xml[existing.start():]
    tail = "</x:sheetData>"
    assert tail in xml
    return xml.replace(tail, f'<x:row r="{row}"></x:row>' + tail, 1)


def _v4_note_cell(xml: str, value_coord: str, text: str) -> tuple[str, bool]:
    """Пишет примечание в колонку E строки ячейки ``value_coord``.

    Пустых E-ячеек в XML шаблона нет, поэтому при отсутствии ячейка
    вставляется в строку — на своё место по порядку колонок, иначе Excel
    вправе отбросить лист как повреждённый.
    """
    row = re.sub(r"[A-Z]+", "", value_coord)
    coord = f"E{row}"
    updated, done = _v4_set_cell(xml, coord, text=text)
    if done:
        return updated, True
    row_pattern = re.compile(r'(<x:row r="%s"[^>]*>)(.*?)(</x:row>)' % row, re.S)
    found = row_pattern.search(xml)
    if not found:
        return xml, False
    cell = (f'<x:c r="{coord}" t="inlineStr">'
            f"<x:is><x:t>{xml_escape(text)}</x:t></x:is></x:c>")
    body = found.group(2)
    insert_at = len(body)
    for existing in re.finditer(r'<x:c r="([A-Z]+)%s"' % row, body):
        if _v4_col_number(existing.group(1)) > _v4_col_number("E"):
            insert_at = existing.start()
            break
    new_body = body[:insert_at] + cell + body[insert_at:]
    return (xml[:found.start()] + found.group(1) + new_body + found.group(3)
            + xml[found.end():]), True


# Лист ввода дописывается в книгу как новый файл: имя занято своим,
# отношение и тип содержимого объявляются рядом. Переиспользовать чужой номер
# нельзя — шаблон нумерует листы своими sheetN.xml.
_V4_ENTRY_SHEET_PATH = "xl/worksheets/sheetEntry.xml"
_V4_ENTRY_REL_ID = "RidEntryInputs0001"
_V4_GUIDE_SHEET_PATH = "xl/worksheets/sheetGuide.xml"
_V4_GUIDE_REL_ID = "RidEntryGuide0001"


def _v4_workbook_with_entry(workbook: str, add: bool) -> str:
    """Переименовать расчётный лист и поставить лист ввода первым.

    Первым — потому что с него начинают: книга открывается там, где печатают.
    А расчётный лист уходит за отчёт: печатать в нём больше нечего, и вторым
    он занимал бы место того, ради чего книгу открывают («книгу открывают ради
    отчёта, а он лежал пятнадцатым листом»). Порядок листов ничего не ломает:
    формулы ссылаются по именам, а не по позиции.
    """
    workbook = re.sub(r'(<x:sheet name=")%s(")' % re.escape(v4_entry_sheet.ENTRY_SHEET),
                      lambda m: m.group(1) + v4_entry_sheet.PARAMS_SHEET + m.group(2),
                      workbook, count=1)
    if not add:
        return workbook
    workbook = _v4_sheet_moved_behind(workbook, v4_entry_sheet.PARAMS_SHEET, "Дашборд")
    namespace = 'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"'
    # Инструкция стоит второй — сразу за листом, о котором она. Первой её
    # ставить нельзя: книгу открывают, чтобы печатать, а не читать инструкцию,
    # и первый лист — тот, с которого начинают работу.
    guide = (f'<x:sheet name="{v4_entry_sheet.GUIDE_SHEET}" sheetId="901" '
             f'r:id="{_V4_GUIDE_REL_ID}" {namespace} />')
    entry = (f'<x:sheet name="{v4_entry_sheet.ENTRY_SHEET}" sheetId="900" '
             f'r:id="{_V4_ENTRY_REL_ID}" {namespace} />')
    return workbook.replace("<x:sheets>", "<x:sheets>" + entry + guide, 1)


def _v4_sheet_moved_behind(workbook: str, name: str, after: str) -> str:
    """Переставить лист за другой. Не нашли — оставить как есть.

    Молча переставить не тот лист хуже, чем не переставить: порядок читают
    глазами, и проверка на него стоит отдельно.
    """
    moved = re.search(r'<x:sheet name="%s"[^>]*/>' % re.escape(name), workbook)
    anchor = re.search(r'<x:sheet name="%s"[^>]*/>' % re.escape(after), workbook)
    if not moved or not anchor or moved.start() > anchor.start():
        return workbook
    without = workbook[:moved.start()] + workbook[moved.end():]
    anchor = re.search(r'<x:sheet name="%s"[^>]*/>' % re.escape(after), without)
    if not anchor:
        return workbook
    return without[:anchor.end()] + moved.group(0) + without[anchor.end():]


def _v4_rels_with_entry(rels: str) -> str:
    links = "".join(
        '<Relationship Type="http://schemas.openxmlformats.org/officeDocument/2006/'
        'relationships/worksheet" Target="/' + path + '" ' + f'Id="{rel}" />'
        for path, rel in ((_V4_ENTRY_SHEET_PATH, _V4_ENTRY_REL_ID),
                          (_V4_GUIDE_SHEET_PATH, _V4_GUIDE_REL_ID)))
    return rels.replace("</Relationships>", links + "</Relationships>", 1)


def _v4_types_with_entry(types: str) -> str:
    overrides = "".join(
        '<Override PartName="/' + path + '" ContentType='
        '"application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml" />'
        for path in (_V4_ENTRY_SHEET_PATH, _V4_GUIDE_SHEET_PATH))
    return types.replace("</Types>", overrides + "</Types>", 1)


def _v4_sheet_path(archive: zipfile.ZipFile, name: str) -> str:
    workbook = archive.read("xl/workbook.xml").decode("utf-8")
    sheet = re.search(r'<x:sheet name="%s"[^>]*r:id="([^"]+)"' % re.escape(name), workbook)
    if not sheet:
        raise RuntimeError(f"в книге v4 нет листа «{name}»")
    rels = archive.read("xl/_rels/workbook.xml.rels").decode("utf-8")
    rel = re.search(r'Target="([^"]+)"[^>]*Id="%s"' % re.escape(sheet.group(1)), rels) \
        or re.search(r'Id="%s"[^>]*Target="([^"]+)"' % re.escape(sheet.group(1)), rels)
    if not rel:
        raise RuntimeError(f"лист «{name}» не найден в связях книги v4")
    target = rel.group(1)
    return "xl/" + target.lstrip("/").removeprefix("xl/")


def _v4_sheet_names_by_path(archive: zipfile.ZipFile) -> dict[str, str]:
    """Путь листа в архиве -> его имя в книге.

    Продление сетки решается по ИМЕНИ листа, а имя лежит в `workbook.xml`:
    угадывать его по номеру файла нельзя — порядок `sheetN.xml` в шаблоне
    имени не соответствует (CF_4 лежит в sheet19.xml).
    """
    workbook = archive.read("xl/workbook.xml").decode("utf-8")
    rels = archive.read("xl/_rels/workbook.xml.rels").decode("utf-8")
    targets = {match.group(2): match.group(1) for match in re.finditer(
        r'Target="([^"]+)"[^>]*?Id="([^"]+)"', rels)}
    targets.update({match.group(1): match.group(2) for match in re.finditer(
        r'Id="([^"]+)"[^>]*?Target="([^"]+)"', rels)})
    out: dict[str, str] = {}
    for match in re.finditer(r'<x:sheet name="([^"]+)"[^>]*?r:id="([^"]+)"', workbook):
        target = targets.get(match.group(2))
        if target:
            out["xl/" + target.lstrip("/").removeprefix("xl/")] = match.group(1)
    return out


def _v4_inputs_sheet_path(archive: zipfile.ZipFile) -> str:
    return _v4_sheet_path(archive, "Вводные")


def _v4_normalized(weights: list[float], count: int) -> list[float]:
    """Веса очередей в долях единицы. Страница хранит их в процентах
    ([40, 32, 28]); записанные как есть, они раздували ГНС очереди в
    сорок раз. Нормировка на сумму принимает оба формата."""
    total = sum(weights[:count])
    return [w / total for w in weights[:count]]


def _v4_fold_tail(weights: list[float], enabled: int, book: int) -> list[float]:
    """Очередей больше, чем листов CF в книге: хвост сливается в последнюю
    книжную очередь, а не размазывается по всем — объёмы четвёртой очереди
    ближе по срокам к третьей, чем к первой."""
    trimmed = weights[:enabled]
    if enabled > book and len(trimmed) >= book:
        trimmed = trimmed[:book - 1] + [sum(trimmed[book - 1:])]
    return trimmed


# Статьи, за которыми идёт «Управление проектом»: своего окна у него нет —
# штаб загружен тем, чем вызван, и его доля месяца равна доле этих расходов.
# Список объявлен здесь и больше нигде: движок разносит по нему статью, книга
# v2 собирает по нему формулу, а книга v4 приводится к нему при выгрузке.
# Копия в шаблоне v4 включала «Сдачу и ввод» — статью последних трёх месяцев,
# — и книга смещала управление к сдаче: помесячный CAPEX расходился с движком
# на сотую долю процента. Само по себе это ничего не стоило, пока покрытие
# эскроу не легло на ступень ставки ПФ: 1,10002× в книге против 1,09993× у
# движка — и один месяц пошёл по 3,47% вместо 1,75%, а стоимость
# финансирования разошлась на 28,9 млн ₽ при совпадающих выручке, CAPEX,
# EBITDA и пике долга.
# Что входит в многоквартирный дом, а что стоит отдельным объектом (решение
# владельца, 23.08.2026: жильё, коммерция, машино-места и кладовки — это МКД).
# Подземный паркинг и кладовые продаются своими продуктами, но строятся тем же
# домом, и в промежуточном итоге стоят с ним. Список объявлен один раз: копия
# на странице разошлась бы с этой молча.
MKD_PRODUCTS: tuple[str, ...] = (
    "apartments", "ground_commercial", "underground_parking", "storage",
)
# Состав объявлен один раз — в STANDALONE_OBJECTS; здесь только его ключи.
STANDALONE_PRODUCTS: tuple[str, ...] = tuple(o.key for o in STANDALONE_OBJECTS)

# Продукты, делящие ОДИН остаточный пул расходов: у них нет своей статьи CAPEX,
# и себестоимость признаётся долей проданного количества. У отдельно стоящего
# объекта пул свой (его CAPEX — отдельная статья), а вот его паркинг своей
# статьи не имеет: места строятся тем же подземным метром, и деньги за них
# лежат в общем пуле. Отсюда и место в этом списке — не «он часть МКД»
# (`MKD_PRODUCTS` отвечает на другой вопрос: чем он построен), а «его расход
# признаётся из остатка».
#
# Списка было два, одинаковых с виду: налоговая база и разбивка расходов по
# продуктам в отчёте. Оба перечисляли четыре продукта МКД руками, а
# `object_parking` завели позже (06.09.2026, «продаётся то, что можно
# поставить на кадастр»), и он не попал ни в один. Выручка от него собиралась,
# налога с неё не брали вовсе: на пресете Нагатино это 5 366,6 млн ₽ выручки
# мимо базы, 395,6 млн налога и 556,3 млн чистой прибыли — а на проекте
# владельца от 13.09.2026 уже 5 138,8 млн налога и 6 101,4 млн прибыли.
# Книга при этом считала верно, и её же блок паритета об этом кричал.
#
# Третьим списком был НДС, и его закрыли отдельно и лучше: облагаемые продукты
# берутся из самих расписаний выручки (`vat_taxable_products`), то есть перечня
# там больше нет вовсе. Здесь так нельзя — пул отвечает не на «кто продаётся»,
# а на «чей расход признаётся из остатка», и у объекта со своей статьёй CAPEX
# ответ обратный.
#
# С 27.09.2026 паркинга объектов в этом пуле нет (владелец: «весь гараж и
# подземный и наземный должен иметь отношение в затратах и выручке только
# своего объекта, но никак не МКД. И это правило для всех объектов»). Его
# расход — в статье его объекта (гараж и метры под местами первых этажей) и
# признаётся вместе с ней; так же и в книге. В пуле дома он забирал долю
# стройки МКД и разбавлял признание квартир своими штуками.
COST_POOL_PRODUCTS: tuple[str, ...] = MKD_PRODUCTS

# Разделы таблицы ТЭП. Двенадцать строк одним списком читаются как двенадцать
# равных продуктов, а это три разные вещи: дом, который мы строим и продаём;
# отдельно стоящие объекты со своей экономикой; и объекты, которые уходят
# городу. Списки уже объявлены выше — здесь только их порядок и имена разделов,
# а третий раздел ОСТАТОЧНЫЙ: продукт, добавленный позже и не попавший ни в
# один список, обязан остаться в таблице, а не исчезнуть из неё молча.
TEP_GROUPS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("Многоквартирный дом", MKD_PRODUCTS),
    ("Отдельно стоящие объекты", STANDALONE_PRODUCTS),
    ("Социальные объекты", ()),
)

# Строки ТЭП, у которых наземной площади нет вовсе: гараж и кладовые лежат под
# землёй, и их метры в ГНС — наземную площадь здания — не входят. Число в
# колонке ГНС у них своё, и без этого списка таблица складывает две разные
# величины под одним именем. Список объявлен здесь и подставляется на страницу
# плейсхолдером — копию негде обновлять, потому что копии нет.
UNDERGROUND_PRODUCTS: tuple[str, ...] = ("underground_parking", "storage")


def project_above_gns(tep: dict[str, Any]) -> float:
    """Наземная ГНС проекта — та самая, что стоит в сводке под именем ГНС.

    Объявлена один раз: её читают и сводка, и удельные, и статья
    благоустройства. Второй счёт той же величины разошёлся бы с первым, и оба
    числа выглядели бы верными.
    """
    object_under = sum(n(row, "under_gns") for row in tep.values())
    underground = (sum(n(tep.get(key) or {}, "gns") for key in UNDERGROUND_PRODUCTS)
                   + object_under)
    volume = sum(n(row, "gns") for row in tep.values()) + object_under
    return max(0.0, volume - underground)
_UNDERGROUND_TEP_KEYS = frozenset(UNDERGROUND_PRODUCTS)


# Чем СЧИТАЕТСЯ продукт. Квартира, машино-место, место в детском саду и
# посещение поликлиники в смену — четыре разные величины, и сумма у них не
# значит ничего: «конечно это не надо суммировать» (владелец, 27.09.2026).
#
# Пока меры не было, свод складывал все штуки подряд — 2 811 на умолчаниях, —
# и это число не только печаталось итогом на странице, в книге, в отчёте и в
# тизере. Его ДЕЛИЛИ: обеспеченность парковкой считалась от него и выходила
# 28,98 вместо 12,36, а строка тизера «Машино-места» печатала 2 811 м/м при
# 1 199 настоящих. Документ для банка утверждал число, которого в проекте нет.
#
# Объявлено ОДИН раз и читается всеми поверхностями. Продукт без меры —
# ошибка объявления, а не «штуки по умолчанию»: проверка требует меру у
# каждой строки ТЭП, поэтому новый продукт заставляет решить, в чём он.
# Сами слова объявлены в `presentation` — модуле ниже всех, кто их печатает.
# Вторая их копия здесь разошлась бы с книгой и тизером молча.
COUNT_FLATS = _presentation.FLATS_MEASURE
COUNT_PARKING = _presentation.PARKING_MEASURE
COUNT_PLACES = _presentation.PLACES_MEASURE
COUNT_VISITS = _presentation.VISITS_MEASURE
COUNT_PIECES = _presentation.PIECES_MEASURE
# Метровый продукт штуками не считается вовсе — у него нет меры счёта, и это
# не пробел: «сколько штук у офисного центра» вопрос без смысла.
COUNT_BY_AREA = _presentation.AREA_MEASURE

HOTEL_TEP_KEY = "hotel"
TEP_COUNT_MEASURE: dict[str, str] = {
    "apartments": COUNT_FLATS,
    # Гостиница меряется метрами здания; номера — не «штуки» свода, их
    # делитель — показатели «на номер» в блоке гостиницы.
    HOTEL_TEP_KEY: COUNT_BY_AREA,
    "ground_commercial": COUNT_BY_AREA,
    "offices": COUNT_BY_AREA,
    "standalone_retail": COUNT_BY_AREA,
    "sports": COUNT_BY_AREA,
    "underground_parking": COUNT_PARKING,
    "above_parking": COUNT_PARKING,
    "storage": COUNT_PIECES,
    "kindergarten": COUNT_PLACES,
    "school": COUNT_PLACES,
    "clinic": COUNT_VISITS,
    "other_mandatory": COUNT_PIECES,
}
# Второй объект того же рода считается как его продукт: второй офисник —
# метрами, второй наземный паркинг — машино-местами. Из реестра, чтобы
# следующий объект не ушёл в «шт.» последнего прибежища.
for _obj in STANDALONE_OBJECTS:
    TEP_COUNT_MEASURE.setdefault(_obj.key, TEP_COUNT_MEASURE[_obj.product])


def tep_count_measure(key: str) -> str:
    """Мера счёта строки ТЭП. Незнакомый продукт — «шт.» и жалоба проверке.

    Возврат «шт.» здесь не умолчание, а последнее прибежище: складывать
    незнакомое с известным нельзя, но и терять его в своде тоже нельзя.
    Настоящее место решения — `TEP_COUNT_MEASURE`, и проверка следит, чтобы
    новый продукт туда попал.
    """
    return TEP_COUNT_MEASURE.get(str(key or ""), COUNT_PIECES)


def tep_units_by_measure(rows: "list[dict[str, Any]]", field: str = "units",
                         garage_field: str = "parking_units") -> dict[str, float]:
    """Штуки свода, разложенные по мере счёта.

    Ответ на «сколько всего единиц» — не число, а разбор: 1 362 квартиры,
    1 199 машино-мест, 250 мест ДОО. Складывать их в 2 811 нельзя, а потерять
    нельзя тем более.

    Гараж объекта (`parking_units`) — тоже машино-места, и он попадает в ту же
    меру: иначе «сколько машино-мест в проекте» отвечалось бы без гаража
    офисника, который в проекте есть.
    """
    out: dict[str, float] = {}
    for row in rows:
        value = n(row, field)
        if value:
            measure = tep_count_measure(row.get("key"))
            if measure:
                out[measure] = out.get(measure, 0.0) + value
        garage = n(row, garage_field) if garage_field else 0.0
        if garage:
            out[COUNT_PARKING] = out.get(COUNT_PARKING, 0.0) + garage
    return out


def tep_parking_spaces(rows: "list[dict[str, Any]]", field: str = "units",
                       garage_field: str = "parking_units") -> float:
    """Машино-места проекта — и подземные, и наземные, и гаражи объектов.

    Отдельной функцией, потому что спрашивают именно её: обеспеченность,
    строка тизера и книга. Чтение меры из общего разбора — чтобы «что считать
    машино-местом» отвечалось один раз.
    """
    return tep_units_by_measure(rows, field, garage_field).get(COUNT_PARKING, 0.0)


# Поля свода ТЭП, которые СКЛАДЫВАЮТСЯ построчно. Список объявлен один раз:
# две его копии стояли в одиночном и очередном расчёте и однажды разошлись бы.
# Штук здесь нет намеренно — они группируются мерой, а не складываются.
TEP_SUMMABLE_FIELDS: tuple[str, ...] = (
    "gns", "total_area", "useful", "saleable", "transfer",
    "guest_units", "transfer_units", "under_gns",
    "parking_units", "parking_saleable_units",
    "parking_under_units", "parking_over_units", "parking_guest_units",
)


MANAGEMENT_PROFILE_ARTICLES: tuple[str, ...] = (
    "ird", "design_p", "design_rd", "author_supervision", "preparation",
    "main_above", "main_under", "utilities", "landscaping", "site_maintenance",
)

# Строки листа CAPEX книги v4: блок очереди повторяется каждые 34 строки.
_V4_CAPEX_ARTICLE_ROW: dict[str, int] = {
    "ird": 16, "design_p": 17, "design_rd": 18, "author_supervision": 19,
    "preparation": 20, "main_above": 21, "main_under": 22, "utilities": 23,
    "landscaping": 24, "commissioning": 25, "site_maintenance": 26,
    "technical_supervision": 27, "project_management": 28, "gc_fee": 29,
    "reserve": 30,
}
_V4_CAPEX_BLOCK_STRIDE = 34
_V4_CAPEX_PHASES = 4


# Общепроектные статьи, которые движок раскладывает по очередям КАССОВЫМИ
# долями, а книга считала от площадей самой очереди. Пока доли близки, разница
# прячется в допуске; на проекте с длинным ИРД и крупной покупкой это 686 млн ₽
# пика БРИДЖа при совпадающих выручке и CAPEX. Ключ — как в `shared_cash`
# движка, строка — в блоке CAPEX первой очереди, колонка — где книга берёт долю.
_V4_SHARED_CASH_ARTICLES = (
    ("ird", 16, "AJ"),
    ("design", 17, "AK"),
    ("design", 18, "AK"),
    ("preparation", 20, "AL"),
    ("utilities", 23, "AM"),
)
# Площади очереди в формуле статьи: их место занимает площадь всего проекта,
# а долю очереди даёт кассовый вес.
_V4_QUEUE_AREA = "('Вводные'!$I${row}+'Вводные'!$J${row}+'Вводные'!$K${row})"
_V4_PROJECT_AREA = "SUM('Вводные'!$I$88:$K$91)"


def _v4_apply_shared_cash_articles(xml: str, missing: list[str]) -> str:
    """Приводит ИРД, проектирование, подготовку и наружные сети к кассовым долям.

    Движок берёт эти статьи по проекту целиком и делит их между очередями
    кассовыми долями (`shared_cash`; умолчание — веса очередей, со страницы
    приходит front-loaded пресет). Книга считала каждую от площадей своей
    очереди — то есть по долям ТЭП. Отношение выборок на проверочном проекте
    вышло 1,571, а это ровно 55/35: кассовая доля против доли ТЭП.

    Формула не переписывается вслепую: не опознали — в `missing`.
    """
    for phase in range(_V4_CAPEX_PHASES):
        base = _V4_CAPEX_BLOCK_STRIDE * phase
        queue_row = _V4_CF_QUEUE_ENABLED_ROW + phase
        area = _V4_QUEUE_AREA.format(row=queue_row)
        for _key, article_row, column in _V4_SHARED_CASH_ARTICLES:
            row = article_row + base
            pattern = re.compile(r'(<x:c r="B%d"[^>]*>)(.*?)(</x:c>)' % row, re.S)
            found = pattern.search(xml)
            if not found:
                missing.append(f"CAPEX · кассовая доля: ячейка B{row} не найдена")
                return xml
            body = found.group(2)
            if area not in body:
                missing.append(
                    f"CAPEX · кассовая доля: формула B{row} не опознана "
                    f"(нет площадей очереди {phase + 1})")
                return xml
            share = f"'Вводные'!${column}${queue_row}"
            body = body.replace(area, f"({_V4_PROJECT_AREA}*{share})", 1)
            xml = (xml[:found.start()] + found.group(1) + body + found.group(3)
                   + xml[found.end():])
    return xml


# Снос и расселение в блоке CAPEX. У шаблона для них нет строки: движок тратил
# 270,9 млн ₽ на снос, книга — ничего, и ровно на эту сумму расходились пик
# БРИДЖа, а следом CAPEX, проценты, налог и LLCR (владелец, 04.09.2026:
# «расхождения опять»). Вводные для них с 0.21.84 стоят в F39–F41 «Вводных»,
# но их не читала ни одна формула. Строки 36–37 каждого блока в шаблоне пусты —
# ряд заводится туда, не сдвигая ни одной ссылки; итог блока (строка 32) и
# база резерва (строка 30) переписываются, чтобы видеть новые строки.
_V4_CAPEX_EXTRA_ROWS = (
    (36, "Снос и демонтаж",
     "('Вводные'!$F$39*'Вводные'!$F$40/1000)"),
    (37, "Расселение", "'Вводные'!$F$41"),
)
_V4_CAPEX_TOTAL_ROW = 32
_V4_CAPEX_RESERVE_ROW = 30
_V4_CAPEX_MONTH_COLUMNS = _V4_MONTH_COLUMNS


def _v4_apply_demolition_rows(xml: str, missing: list[str]) -> str:
    """Строки сноса и расселения в каждом блоке CAPEX по образцу подготовки.

    Сумма — как у строки 20: вводная × сценарий × множитель затрат очереди ×
    признак очереди × коэффициент затрат к старту × кассовая доля (та же
    колонка AL, что у подготовки: движок делит снос её долей). Помесячно —
    окно перед РнС, как у подготовки. Формула не опознана — `missing`.
    """
    from openpyxl.utils import get_column_letter as _col

    def styled(cell_xml: str, coord: str, style: str | None) -> str:
        return cell_xml.replace(f'<x:c r="{coord}"', f'<x:c r="{coord}" s="{style}"', 1) if style else cell_xml

    def style_of(coord: str) -> str | None:
        found = re.search(r'<x:c r="%s"[^>]*?\ss="(\d+)"' % coord, xml)
        return found.group(1) if found else None

    label_style, amount_style, month_style = style_of("A20"), style_of("B20"), style_of("D20")
    for phase in range(_V4_CAPEX_PHASES):
        base = _V4_CAPEX_BLOCK_STRIDE * phase
        queue_row = _V4_CF_QUEUE_ENABLED_ROW + phase
        permit = f"$B${7 + base}"
        for row_at, label, amount in _V4_CAPEX_EXTRA_ROWS:
            row = row_at + base
            xml = _v4_ensure_row(xml, row)
            formula = (f"{amount}*'Вводные'!$H$6*'Вводные'!$T${queue_row}"
                       f"*--('Вводные'!$B${queue_row}=\"Да\")*'Вводные'!$AH${queue_row}"
                       f"*'Вводные'!$AL${queue_row}")
            cells = {f"A{row}": dict(text=label),
                     f"B{row}": dict(formula=formula),
                     f"C{row}": dict(text="млн ₽")}
            styles = {f"A{row}": label_style, f"B{row}": amount_style, f"C{row}": None}
            for index in range(_V4_CAPEX_MONTH_COLUMNS):
                column = _col(4 + index)
                window = f"MIN(6,'Вводные'!$E${queue_row})"
                cells[f"{column}{row}"] = dict(formula=(
                    f"IF(AND({column}$3>=EDATE({permit},-{window}),{column}$3<{permit}),"
                    f"$B${row}/MAX(1,{window}),0)"))
                styles[f"{column}{row}"] = month_style
            xml, done = _v4_set_cells(xml, row, cells, styles)
            if not done:
                missing.append(f"CAPEX · снос и расселение: строка {row} не записана")
                return xml
        # Итог блока видит новые строки: SUM(X14:X31)+ОБЪЕКТЫ → +X36+X37.
        total_row = _V4_CAPEX_TOTAL_ROW + base
        extra = [row_at + base for row_at, _label, _amount in _V4_CAPEX_EXTRA_ROWS]
        pattern = re.compile(
            r'(<x:c r="(?P<col>[A-Z]{1,3})%d"[^>]*><x:f>)SUM\((?P=col)%d:(?P=col)%d\)\+'
            % (total_row, 14 + base, 31 + base))
        xml, count = pattern.subn(
            lambda m: m.group(1) + "SUM(%s%d:%s%d)+%s+" % (
                m.group("col"), 14 + base, m.group("col"), 31 + base,
                "+".join(f"{m.group('col')}{r}" for r in extra)), xml)
        if count < _V4_CAPEX_MONTH_COLUMNS:
            missing.append(f"CAPEX · итог очереди {phase + 1}: формула строки {total_row} не опознана "
                           f"({count} колонок из {_V4_CAPEX_MONTH_COLUMNS})")
        # База резерва — все статьи блока: (SUM(B15:B29)+B31+…) → +B36+B37.
        reserve_row = _V4_CAPEX_RESERVE_ROW + base
        pattern = re.compile(r'(<x:c r="B%d"[^>]*><x:f>\(SUM\(B%d:B%d\)\+B%d)' % (
            reserve_row, 15 + base, 29 + base, 31 + base))
        xml, count = pattern.subn(lambda m: m.group(1) + "".join(f"+B{r}" for r in extra), xml)
        if count != 1:
            missing.append(f"CAPEX · резерв очереди {phase + 1}: формула B{reserve_row} не опознана")
    return xml


# Лист «ВРИ»: четыре блока по 13 строк, первый начинается на строке 6.
_V4_VRI_BLOCK_STRIDE = 13
_V4_VRI_PRINCIPAL_ROW = 12     # погашение основного долга
_V4_VRI_INTEREST_ROW = 13      # проценты по рассрочке
_V4_VRI_SECURITY_ROW = 14      # расходы на обеспечение
# Строка CAPEX, куда уходят проценты и обеспечение: 36 и 37 заняты сносом и
# расселением, 38 в шаблоне пуста.
_V4_CAPEX_VRI_EXTRA_ROW = 38
_V4_CF_VAT_ROW = 21                  # CF очереди: «НДС к уплате»
_V4_CAPEX_VRI_ROW = 15


def _v4_apply_vri_installment_start(xml: str, missing: list[str]) -> str:
    """Первый платёж рассрочки ВРИ — в дату обязательства, а не периодом позже.

    Правило движка с 08.2026: рассрочка начинается в дату обязательства.
    Шаблон остался на прежней методике — условие платежа требовало, чтобы от
    даты обязательства прошло БОЛЬШЕ нуля месяцев, и первый взнос уезжал на
    период вперёд. Число платежей при этом сохранялось, поэтому расходилось не
    тело, а проценты: на трёхлетней квартальной рассрочке книга начисляла их
    двенадцать раз вместо одиннадцати и на полную сумму — 317,9 млн ₽ против
    269,1 у движка при одинаковой плате.

    Замена точечная: «прошло > 0 месяцев» → «прошло >= 0», а верхняя граница
    становится строгой, иначе платежей стало бы тринадцать. Формула шаблона не
    опознана — `missing`, а не молча посчитанный по-своему график.
    """
    expected = _V4_CAPEX_MONTH_COLUMNS * 2 * _V4_CAPEX_PHASES
    start_from, start_count = ")&gt;0,MOD(", xml.count(")&gt;0,MOD(")
    upper_from, upper_count = "&lt;=&#39;Вводные&#39;!$B$77*12", 0
    # Апостроф в XML может быть и целым, и мнемоникой — считаем оба написания.
    for candidate in ("&lt;='Вводные'!$B$77*12", "&lt;=&#39;Вводные&#39;!$B$77*12"):
        if xml.count(candidate):
            upper_from, upper_count = candidate, xml.count(candidate)
            break
    if start_count != expected or upper_count != expected:
        missing.append(
            f"ВРИ · начало рассрочки: условие графика не опознано "
            f"({start_count} и {upper_count} вместо {expected})")
        return xml
    xml = xml.replace(start_from, ")&gt;=0,MOD(")
    xml = xml.replace(upper_from, upper_from.replace("&lt;=", "&lt;", 1))
    return xml


_V4_VRI_BALANCE_END_ROW = 16   # остаток на конец месяца
_V4_VRI_RATE_ROW = 17          # ставка по рассрочке
_V4_VRI_ACCRUAL_ROW = 18       # накопленные проценты — служебная строка блока


def _v4_apply_vri_monthly_accrual(xml: str, missing: list[str]) -> str:
    """Проценты по рассрочке ВРИ копятся помесячно, как в движке.

    Шаблон начислял их в месяц платежа: остаток × ставка ЭТОГО месяца ×
    периодичность / 12. Движок идёт по месяцам между платежами и берёт ставку
    каждого месяца (`build_vri_schedule`), а ключевая ставка у нас снижается —
    на трёхлетней рассрочке книга недосчитывала около двух процентов.

    Свободная строка блока (18, 31, 44, 57 — в шаблоне пусты) копит начисление
    на остаток КОНЦА месяца: в месяц платежа это остаток после погашения, то
    есть ровно та база, на которой считает движок. Платёж забирает накопленное
    за прошлые месяцы, поэтому на первом взносе процентов нет.
    """
    from openpyxl.utils import get_column_letter as _col

    def style_of(coord: str) -> str | None:
        found = re.search(r'<x:c r="%s"[^>]*?\ss="(\d+)"' % coord, xml)
        return found.group(1) if found else None

    label_style, month_style = style_of("A13"), style_of("D13")
    for phase in range(_V4_CAPEX_PHASES):
        base = _V4_VRI_BLOCK_STRIDE * phase
        principal = _V4_VRI_PRINCIPAL_ROW + base
        interest = _V4_VRI_INTEREST_ROW + base
        balance_end = _V4_VRI_BALANCE_END_ROW + base
        rate = _V4_VRI_RATE_ROW + base
        accrual = _V4_VRI_ACCRUAL_ROW + base
        xml = _v4_ensure_row(xml, accrual)
        carried_cells = {f"A{accrual}": dict(text="Накопленные проценты (служебная строка)"),
                         f"B{accrual}": dict(formula=f"{_V4_LAST_COLUMN}{accrual}")}
        styles = {f"A{accrual}": label_style, f"B{accrual}": None}
        paid_cells: dict[str, dict[str, Any]] = {}
        for index in range(_V4_CAPEX_MONTH_COLUMNS):
            column = _col(4 + index)
            previous = _col(3 + index)
            carried = "0" if index == 0 else f"{previous}{accrual}"
            month = (f"IF(AND('Вводные'!$B$75<>\"Единовременно\",'Вводные'!$B$80=\"Да\","
                     f"{column}{balance_end}>0),{column}{balance_end}*{column}{rate}/12,0)")
            carried_cells[f"{column}{accrual}"] = dict(
                formula=f"{carried}+{month}-{column}{interest}")
            styles[f"{column}{accrual}"] = month_style
            paid_cells[f"{column}{interest}"] = dict(formula=(
                "0" if index == 0 else f"IF({column}{principal}>0,{previous}{accrual},0)"))
        for target, payload, style_map in ((accrual, carried_cells, styles),
                                           (interest, paid_cells, None)):
            xml, done = _v4_set_cells(xml, target, payload, style_map)
            if not done:
                missing.append(f"ВРИ · накопление процентов: строка {target} не записана")
                return xml
    return xml


def _v4_apply_vat_base(xml: str, phase: int, missing: list[str]) -> str:
    """Проценты по рассрочке ВРИ НДС не облагаются — значит и вычета не дают.

    Строка 21 листа CF берёт базу вычета как «все расходы очереди минус покупка
    и минус тело платы за ВРИ». Проценты и обеспечение рассрочки приезжают в
    расходы строкой 38 CAPEX (0.23.х) и в эту базу входили, то есть книга
    возвращала НДС с процентов. Движок их из базы вычитает
    (`vri_interest`, `vri_security` в `vat_bearing_costs`), и на проекте с
    трёхлетней рассрочкой расхождение выходило 5,9 млн ₽ — при совпадающих
    CAPEX, выручке и EBITDA. Нашла его строка паритета НДС первым же прогоном.

    Формула шаблона не опознана — `missing`, а не тихий вычет по прежней базе.
    """
    row = _V4_CF_VAT_ROW
    # `phase` здесь — НОМЕР листа CF (1..4), как в остальных проходах этого
    # цикла: блок CAPEX у первой очереди идёт без смещения.
    extra = (f"'CAPEX'!$B$"
             f"{_V4_CAPEX_VRI_EXTRA_ROW + _V4_CAPEX_BLOCK_STRIDE * (phase - 1)}")
    was = "(SUM($D$20:$GA$20)-"
    now = f"(SUM($D$20:$GA$20)-{extra}-"
    formulas = _v4_row_formulas(xml, row)
    cells: dict[str, dict[str, Any]] = {}
    for coord, formula in formulas.items():
        # Колонка берётся целиком: «AC21» начинается на «A», и проверка по
        # первой букве выбрасывала весь блок AA..CZ — 81 ячейку из 183, ровно
        # ту середину строки, где и стоит живой месяц. Снаружи это выглядело
        # как «правка не сработала»: D21 с правкой, а число прежнее.
        column = re.match(r"[A-Z]+", coord).group(0)
        if column in ("A", "B", "C"):
            continue
        if was not in formula:
            continue
        cells[coord] = dict(formula=formula.replace(was, now, 1))
    if not cells:
        missing.append(f"CF очереди {phase}: база НДС в строке {row} не опознана")
        return xml
    xml, done = _v4_set_cells(xml, row, cells)
    if not done:
        missing.append(f"CF очереди {phase}: база НДС строки {row} не записана")
    return xml


def _v4_apply_vri_interest_row(xml: str, missing: list[str]) -> str:
    """Проценты и обеспечение по рассрочке ВРИ — своей строкой, вне базы резерва.

    Строка 15 CAPEX брала ВЕСЬ денежный платёж по ВРИ (тело, проценты и
    обеспечение), а база резерва — это `SUM(B15:B29)`: книга начисляла резерв и
    на проценты. Движок берёт резерв до того, как проценты и обеспечение
    становятся статьями (они прибавляются после `base_for_overheads`), и на
    317,9 млн ₽ процентов это давало лишние 15,9 млн ₽ резерва.

    Поэтому строка 15 несёт только тело, а проценты с обеспечением встают
    строкой 38 своего блока: она входит в итог блока и не входит в базу резерва.
    """
    from openpyxl.utils import get_column_letter as _col

    def style_of(coord: str) -> str | None:
        found = re.search(r'<x:c r="%s"[^>]*?\ss="(\d+)"' % coord, xml)
        return found.group(1) if found else None

    label_style, amount_style, month_style = style_of("A15"), style_of("B15"), style_of("D15")
    for phase in range(_V4_CAPEX_PHASES):
        base = _V4_CAPEX_BLOCK_STRIDE * phase
        vri_base = _V4_VRI_BLOCK_STRIDE * phase
        principal = _V4_VRI_PRINCIPAL_ROW + vri_base
        interest = _V4_VRI_INTEREST_ROW + vri_base
        security = _V4_VRI_SECURITY_ROW + vri_base
        row = _V4_CAPEX_VRI_EXTRA_ROW + base
        vri_row = _V4_CAPEX_VRI_ROW + base
        xml = _v4_ensure_row(xml, row)
        extra = {f"A{row}": dict(text="Проценты и обеспечение по рассрочке ВРИ"),
                 f"B{row}": dict(formula=(
                     f"SUM('ВРИ'!D{interest}:{_V4_LAST_COLUMN}{interest})"
                     f"+SUM('ВРИ'!D{security}:{_V4_LAST_COLUMN}{security})")),
                 f"C{row}": dict(text="млн ₽")}
        styles = {f"A{row}": label_style, f"B{row}": amount_style, f"C{row}": None}
        body = {f"B{vri_row}": dict(
            formula=f"SUM('ВРИ'!D{principal}:{_V4_LAST_COLUMN}{principal})")}
        for index in range(_V4_CAPEX_MONTH_COLUMNS):
            column = _col(4 + index)
            extra[f"{column}{row}"] = dict(
                formula=f"'ВРИ'!{column}{interest}+'ВРИ'!{column}{security}")
            styles[f"{column}{row}"] = month_style
            body[f"{column}{vri_row}"] = dict(formula=f"'ВРИ'!{column}{principal}")
        for target, payload, style_map in ((row, extra, styles), (vri_row, body, None)):
            xml, done = _v4_set_cells(xml, target, payload, style_map)
            if not done:
                missing.append(f"CAPEX · проценты ВРИ: строка {target} не записана")
                return xml
        # Итог блока видит новую строку; база резерва (B30) её не видит намеренно.
        total_row = _V4_CAPEX_TOTAL_ROW + base
        pattern = re.compile(
            r'(<x:c r="(?P<col>[A-Z]{1,3})%d"[^>]*><x:f>SUM\((?P=col)%d:(?P=col)%d\)'
            r'(?:\+(?P=col)\d+)*)' % (total_row, 14 + base, 31 + base))
        xml, count = pattern.subn(
            lambda m: m.group(1) + f"+{m.group('col')}{row}", xml)
        if count < _V4_CAPEX_MONTH_COLUMNS:
            missing.append(f"CAPEX · итог очереди {phase + 1}: строка процентов ВРИ не добавлена "
                           f"({count} колонок из {_V4_CAPEX_MONTH_COLUMNS})")
    return xml


# Строки статей блока CAPEX, чья база меняется методикой «объект под ключ».
_V4_CAPEX_TECH_SUPERVISION_ROW = 27
_V4_CAPEX_GC_FEE_ROW = 29


def _v4_apply_turnkey_overheads(xml: str, missing: list[str]) -> str:
    """Генподряд, техзаказчик и резерв — на базах движка (решение 06.10.2026).

    Шаблон брал техзаказчика (B27) и генподряд (B29) от СМР ядра, соцстройки
    И «CAPEX объектов» с листа «ОБЪЕКТЫ», а резерв (B30) — от `SUM(B15:B29)`,
    то есть и от платы за смену ВРИ (B15). Методика теперь иная: ставка
    объекта — «под ключ», генподряд и техзаказчик в ней уже есть; плата за ВРИ
    — известная сумма, резерв на неё не нужен. Правка точечная, поверх формулы
    шаблона: из B27/B29 уходит слагаемое объектов, у резерва сумма начинается
    со строки 16. Не опознанная формула — в `missing`, а не молчаливое
    расхождение с движком.
    """
    objects_term = re.compile(r"\+'ОБЪЕКТЫ'!\$B\$\d+")
    for phase in range(_V4_CAPEX_PHASES):
        base = _V4_CAPEX_BLOCK_STRIDE * phase
        for row_at, label in ((_V4_CAPEX_TECH_SUPERVISION_ROW, "техзаказчик"),
                              (_V4_CAPEX_GC_FEE_ROW, "генподряд")):
            row = row_at + base
            formula = _v4_cell_formula(xml, f"B{row}")
            fixed, count = objects_term.subn("", formula or "", count=1)
            if count != 1:
                missing.append(f"CAPEX · {label} очереди {phase + 1}: формула B{row} не опознана")
                continue
            xml, done = _v4_set_cells(xml, row, {f"B{row}": dict(formula=fixed)})
            if not done:
                missing.append(f"CAPEX · {label} очереди {phase + 1}: B{row} не записана")
        row = _V4_CAPEX_RESERVE_ROW + base
        formula = _v4_cell_formula(xml, f"B{row}") or ""
        was = f"SUM(B{_V4_CAPEX_VRI_ROW + base}:B{29 + base})"
        if was not in formula:
            missing.append(f"CAPEX · резерв очереди {phase + 1}: формула B{row} не опознана")
            continue
        fixed = formula.replace(was, f"SUM(B{_V4_CAPEX_VRI_ROW + 1 + base}:B{29 + base})", 1)
        xml, done = _v4_set_cells(xml, row, {f"B{row}": dict(formula=fixed)})
        if not done:
            missing.append(f"CAPEX · резерв очереди {phase + 1}: B{row} не записана")
    return xml


# Статьи проекта в блоке CAPEX очереди: разносимые долями движка по очередям
# (база — сумма площадей всех очередей × доля) и считаемые своей очередью.
_V4_SHARED_AREA_ARTICLE_ROWS = (16, 17, 18, 20, 23)
_V4_PHASE_AREA_ARTICLE_ROWS = (25, 26)
_V4_CAPEX_MANAGEMENT_ROW = 28


def _v4_apply_nonres_full_estimate(xml: str, inputs: dict[str, Any], missing: list[str]) -> str:
    """Чисто нежилой проект: полная смета формулами, как в движке.

    Решение владельца 06.10.2026 (`object_rate_is_turnkey`): ставка метрового
    объекта нежилого проекта — СМР здания. Статьи проекта (ИРД, П, РД,
    подготовка, сети, ввод, содержание) идут по своим ставкам от суммарной
    площади объектов в ГНС — здание (GBA) плюс свой гараж (места × площадь
    места), — а генподряд, техзаказчик и управление начисляются и на СМР
    объекта. Шаблон считал эти статьи от площади МКД (у нежилого — ноль) и без
    объектов. Правка точечная, поверх формул: к площади добавляются слагаемые
    объектов, к базам процентов — CAPEX объектов своей очереди. Объект «под
    ключ» (наземный паркинг) в эти слагаемые не входит. Не опознанная формула —
    в `missing`.
    """
    def cond(lay: "_V4ObjectLayout") -> str:
        head = lay.object_head
        return (f"AND('ОБЪЕКТЫ'!$B${head + 1}=\"Да\",IFERROR(INDEX('Вводные'!$B$88:$B$91,"
                f"'ОБЪЕКТЫ'!$B${head + 2}),\"Нет\")=\"Да\")")

    def area(lay: "_V4ObjectLayout") -> str:
        head = lay.object_head
        garage = ""
        if lay.parking_under:
            col, row = re.match(r"([A-Z]+)(\d+)$", lay.parking_under).groups()
            garage = f"+'Вводные'!${col}${row}*'Вводные'!$K$158"
        return f"IF({cond(lay)},'ОБЪЕКТЫ'!$B${head + 6}{garage},0)"

    smr = [lay for lay in _v4_layouts() if not object_rate_is_turnkey(inputs, lay.obj)]
    if not smr:
        return xml
    total_area = "+".join(area(lay) for lay in smr)

    def phase_area(phase: int) -> str:
        return "+".join(f"IF('ОБЪЕКТЫ'!$B${lay.object_head + 2}={phase + 1},{area(lay)},0)"
                        for lay in smr)

    def phase_works(phase: int) -> str:
        return "+".join(f"IF('ОБЪЕКТЫ'!$B${lay.object_head + 2}={phase + 1},"
                        f"'ОБЪЕКТЫ'!$B${lay.object_head + 22},0)" for lay in smr)

    def patch(row: int, was: str, now: str, label: str) -> None:
        nonlocal xml
        formula = _v4_cell_formula(xml, f"B{row}") or ""
        if was not in formula:
            missing.append(f"CAPEX · нежилой проект, {label}: формула B{row} не опознана")
            return
        xml, done = _v4_set_cells(xml, row, {f"B{row}": dict(formula=formula.replace(was, now, 1))})
        if not done:
            missing.append(f"CAPEX · нежилой проект, {label}: B{row} не записана")

    shared = "SUM('Вводные'!$AR$88:$AR$91)"
    for phase in range(_V4_CAPEX_PHASES):
        base = _V4_CAPEX_BLOCK_STRIDE * phase
        for row in _V4_SHARED_AREA_ARTICLE_ROWS:
            patch(row + base, shared + ")", f"{shared}+{total_area})",
                  f"статья проекта очереди {phase + 1}")
        own = f"'Вводные'!$AR${88 + phase})"
        for row in _V4_PHASE_AREA_ARTICLE_ROWS:
            patch(row + base, own, f"'Вводные'!$AR${88 + phase}+{phase_area(phase)})",
                  f"статья проекта очереди {phase + 1}")
        works = phase_works(phase)
        for row in (_V4_CAPEX_TECH_SUPERVISION_ROW, _V4_CAPEX_GC_FEE_ROW):
            patch(row + base, f"B{31 + base})*", f"B{31 + base}+{works})*",
                  f"генподряд и техзаказчик очереди {phase + 1}")
        patch(_V4_CAPEX_MANAGEMENT_ROW + base, f"B{26 + base})*", f"B{26 + base}+{works})*",
              f"управление очереди {phase + 1}")
    return xml


def _v4_management_profile_ranges() -> tuple[int, int, list[int]]:
    """Первая и последняя строка профиля и строки, которые в него не входят."""
    rows = sorted(_V4_CAPEX_ARTICLE_ROW[key] for key in MANAGEMENT_PROFILE_ARTICLES)
    first, last = rows[0], rows[-1]
    excluded = [row for row in range(first, last + 1) if row not in rows]
    return first, last, excluded


# Подписи, называющие подземную площадь наземной. ГНС — наземная площадь
# здания (внутренний термин DevelopAid), и у гаража с кладовыми её нет вовсе:
# в их строке стоит площадь подземного этажа. Итог складывает обе величины и
# потому зовётся строительным объёмом — на нём считаются общие статьи и все
# удельные «на метр». Формулы это не двигает: `ТЭП!C36` читает единственная
# ячейка `ОТЧЕТ!G6`, и её саму не читает никто.
_V4_GNS_LABELS: tuple[tuple[str, str, str, str], ...] = (
    ("ТЭП", "C3", "ГНС, м²", "ГНС / подземная площадь, м²"),
    ("ТЭП", "A36", "ИТОГО ПРОЕКТ", f"ИТОГО ПРОЕКТ — {TOTAL_AREA.lower()}"),
    ("ОТЧЕТ", "F6", "ГНС", TOTAL_AREA.name),
    ("ОТЧЕТ", "A33", "Покупка", "Покупка: участок + выкуп ЗУ/ОКС"),
)


# Выкуп ЗУ/ОКС у третьих лиц — строка стоимости сделки (решение владельца,
# 29.09.2026). В книге он стоит своей ячейкой блока сделки, а там, где книга
# берёт цену покупки, — покупка идёт вместе с выкупом: строка «Приобретение»
# каждой очереди (та же доля очереди, тот же график), база вычета НДС листов
# CF и «Покупка» структуры расходов ОТЧЕТа. Движок делает то же самое: выкуп
# платится статьёй покупки и из базы НДС вычитается.
_V4_CAPEX_PURCHASE_ROW = 14
# Апостроф в XML листа бывает и целым, и мнемоникой — опознаются все написания.
_V4_DEAL_PRICE_CELLS = ("'Вводные'!$B$15", "&apos;Вводные&apos;!$B$15",
                        "&#39;Вводные&#39;!$B$15")


def _v4_deal_includes_buyout(xml: str, sheet: str, rows: tuple[int, ...],
                             missing: list[str]) -> str:
    """Цена покупки в названных строках → цена покупки плюс выкуп ЗУ/ОКС."""
    for row in rows:
        cells: dict[str, dict[str, Any]] = {}
        for coord, formula in _v4_row_formulas(xml, row).items():
            for price in _V4_DEAL_PRICE_CELLS:
                buyout = price.replace("$B$15", "$F$16")
                if price in formula and buyout not in formula:
                    cells[coord] = dict(formula=formula.replace(
                        price, f"({price}+{buyout})"))
                    break
        if not cells:
            missing.append(f"{sheet} · строка {row}: цена покупки не опознана — "
                           "выкуп ЗУ/ОКС в стоимость сделки не добавлен")
            continue
        xml, done = _v4_set_cells(xml, row, cells)
        if not done:
            missing.append(f"{sheet} · строка {row}: стоимость сделки с выкупом не записана")
    return xml


def _v4_rename_labels(xml: str, sheet: str, missing: list[str]) -> str:
    """Переименовать подписи листа — по опознанному тексту, а не вслепую.

    Не нашли прежнюю подпись — это `missing`, а не молчание: подпись, которую
    не удалось заменить, продолжает называть подземную площадь наземной, и
    снаружи это неотличимо от переименованной.
    """
    for name, coord, was, becomes in _V4_GNS_LABELS:
        if name != sheet:
            continue
        pattern = re.compile(
            r'(<(?:x:)?c r="%s"[^>]*>\s*<(?:x:)?v>)%s(</(?:x:)?v>)' % (coord, re.escape(was))
        )
        xml, count = pattern.subn(lambda m: m.group(1) + becomes + m.group(2), xml, count=1)
        if not count:
            missing.append(
                f"{sheet}!{coord}: подпись «{was}» не опознана — "
                f"переименование в «{becomes}» не применено")
    return xml


def _v4_apply_management_profile(xml: str, missing: list[str]) -> str:
    """Приводит формулу «Управление проектом» книги v4 к списку движка.

    Шаблон брал сплошной диапазон строк, а в нём лежит и статья, которой в
    профиле движка нет. Формула не переписывается вслепую: не опознали — в
    `missing`, а не молча посчитали по-своему.
    """
    first, last, excluded = _v4_management_profile_ranges()
    if not excluded:
        return xml
    for phase in range(_V4_CAPEX_PHASES):
        base = _V4_CAPEX_BLOCK_STRIDE * phase
        top, bottom = first + base, last + base
        drop = [row + base for row in excluded]
        pattern = re.compile(
            r"SUM\((?P<col>[A-Z]{1,2})%d:(?P=col)%d\)/SUM\(\$D\$%d:\$%s\$%d\)"
            % (top, bottom, top, _V4_LAST_COLUMN, bottom))
        def replace(match: "re.Match[str]") -> str:
            column = match.group("col")
            month = (f"(SUM({column}{top}:{column}{bottom})-"
                     + "-".join(f"{column}{row}" for row in drop) + ")")
            total = (f"(SUM($D${top}:${_V4_LAST_COLUMN}${bottom})-"
                     + "-".join(f"SUM({_v4_month_span(row)})" for row in drop) + ")")
            return f"{month}/{total}"
        xml, count = pattern.subn(replace, xml)
        if not count:
            missing.append(
                f"CAPEX · профиль управления очереди {phase + 1}: формула строки "
                f"{_V4_CAPEX_ARTICLE_ROW['project_management'] + base} не опознана")
    return xml


# Перенос непогашенного долга между очередями в книге.
#
# Строки 64 и 65 листов CF в шаблоне пусты — значит ряд заводится, не сдвигая
# ни одной ссылки. Вставлять строку в занятое место нельзя: поедет всё, что
# на неё ссылается (тем же правилом зачёт переданных метров лёг в ячейку
# льготы, а не в свою).
_V4_CARRY_ACCEPTED_ROW = 64          # ПФ — принятый долг предыдущей очереди
_V4_CARRY_PASSED_ROW = 65            # ПФ — долг передан следующей очереди
# Сколько не покрыл раскрытый эскроу. Отдельная строка, а не «переданное»:
# линия закрывается при нехватке ВСЕГДА, перенесли долг или объявили дефолт.
# Строка 29 листов CF в шаблоне пуста — ряд встаёт, не сдвигая ссылок.
_V4_RVE_UNPAID_ROW = 29
_V4_CARRY_FLAG_CELL = "B92"          # признак на «Вводных»
_V4_CF_QUEUE_ENABLED_ROW = 88        # 'Вводные'!B88 — очередь 1 включена
_V4_BRIDGE_FEE_ROW = 57              # база комиссии выдачи = лимит БРИДЖа


def _v4_insert_row(xml: str, row: int, body: str, before: int | None) -> tuple[str, bool]:
    """Вставляет целую строку в пустое место листа.

    Пустая строка в XML не существует вовсе, а `_v4_set_cell` умеет только
    заменять существующую ячейку. Вставлять в ЗАНЯТОЕ место нельзя — поедут
    все ссылки; поэтому вызывающий обязан выбрать строку, которой в шаблоне
    нет, и это проверяется здесь.
    """
    if f'<x:row r="{row}"' in xml:
        return xml, False
    # Строка последняя на листе — вставлять не перед чем, дописываем в конец
    # данных. Порядок строк в sheetData обязан расти, поэтому только в конец.
    marker = f'<x:row r="{before}"' if before else "</x:sheetData>"
    at = xml.find(marker)
    if at < 0:
        return xml, False
    return xml[:at] + f'<x:row r="{row}">' + body + "</x:row>" + xml[at:], True


def _v4_write_carry_flag(xml: str, enabled: bool, missing: list[str],
                         sweep_share: float = 0.0) -> str:
    """Признак переноса долга на «Вводных» — своей строкой, как остальные Да/Нет.

    Доля кэш-свипа стоит в той же строке: это одно и то же событие — очередь
    отдала долг и с её поступлений банк забирает долю. Отдельной строки для
    неё в шаблоне нет, а вставлять вторую значило бы двигать заголовок блока
    ставок.
    """
    row = int(_V4_CARRY_FLAG_CELL[1:])
    body = (
        f'<x:c r="A{row}" t="str"><x:v>Перенос долга между очередями применён '
        f'(решает гейт по LLCR)</x:v></x:c>'
        f'<x:c r="B{row}" s="12" t="str"><x:v>{"Да" if enabled else "Нет"}</x:v></x:c>'
        f'<x:c r="C{row}" t="str"><x:v>Да / Нет</x:v></x:c>'
        f'<x:c r="D{row}" t="str"><x:v>carry_debt_applied</x:v></x:c>'
        f'<x:c r="E{row}" t="str"><x:v>Кэш-свип: доля поступлений банку</x:v></x:c>'
        f'<x:c r="F{row}"><x:v>{_v4_number(round(sweep_share, 6))}</x:v></x:c>')
    updated, done = _v4_insert_row(xml, row, body, row + 1)
    if not done:
        missing.append(f"признак переноса долга: строка {row} «Вводных» занята")
        return xml
    return updated


def _v4_cf_columns() -> list[str]:
    from openpyxl.utils import get_column_letter
    return [get_column_letter(c) for c in range(_V4_CF_FIRST_COL, _V4_CF_LAST_COL + 1)]


def _v4_carry_row_xml(row: int, label: str, formulas: dict[str, str]) -> str:
    """Строка листа CF целиком: подпись, итог, единица и месяцы.

    Стили берутся у строки 47 («ПФ — долг на конец») — той же природы величина,
    и Excel не должен увидеть чужой формат в середине блока.
    """
    cells = [
        f'<x:c r="A{row}" s="113" t="str"><x:v>{xml_escape(label)}</x:v></x:c>',
        f'<x:c r="B{row}" s="113" t="n"><x:f>SUM(D{row}:{_V4_LAST_COLUMN}{row})</x:f></x:c>',
        f'<x:c r="C{row}" s="113" t="str"><x:v>млн ₽</x:v></x:c>',
    ]
    for column in _v4_cf_columns():
        cells.append(
            f'<x:c r="{column}{row}" s="120">'
            f"<x:f>{xml_escape(formulas[column])}</x:f></x:c>")
    return f'<x:row r="{row}">' + "".join(cells) + "</x:row>"


def _v4_apply_debt_carry(xml: str, phase: int, queues: int, missing: list[str]) -> str:
    """Учит лист CF очереди принимать долг предыдущей и отдавать свой следующей.

    Методика — движковая (владелец, 27–29.08.2026): долг переезжает в месяц
    раскрытия эскроу передавшей очереди, в сумме, которой раскрытому эскроу не
    хватило; лимита он не выбирает, но проценты несёт и разбавляет покрытие;
    после этого линия передавшей закрыта — ни выборки, ни погашения.

    Формулы шаблона не переписываются вслепую: не опознали — в `missing`, а не
    молча посчитали по-своему. Признак выключен — ряды дают ноль, и все
    правленые формулы сходятся к прежним: книга без переноса обязана считать
    ровно как раньше, иначе паритет поедет на проектах, где его никто не
    включал.
    """
    columns = _v4_cf_columns()
    sheet = f"CF_{phase}"
    previous = f"CF_{phase - 1}"
    flag = f"'Вводные'!${_V4_CARRY_FLAG_CELL[0]}${_V4_CARRY_FLAG_CELL[1:]}=\"Да\""
    next_enabled = f"'Вводные'!$B${_V4_CF_QUEUE_ENABLED_ROW + phase}=\"Да\""

    accepted: dict[str, str] = {}
    passed: dict[str, str] = {}
    unpaid: dict[str, str] = {}
    for column in columns:
        # Нехватка в РВЭ: считается всегда, до всякого решения о переносе.
        unpaid[column] = (
            f"IF(AND($B$5=1,YEAR({column}$3)=YEAR($B$8),MONTH({column}$3)=MONTH($B$8)),"
            f"MAX(0,{column}38+{column}45+{column}{_V4_CARRY_ACCEPTED_ROW}-{column}46),0)")
        if phase <= 1:
            accepted[column] = "0"
        else:
            # Дата приёма — максимум из РВЭ передавшей и РнС этой: раньше
            # своей линии принять долг в ПФ нельзя, её ещё нет.
            at = f"MAX('{previous}'!$B$8,$B$7)"
            accepted[column] = (
                f"IF(AND($B$5=1,YEAR({column}$3)=YEAR({at}),"
                f"MONTH({column}$3)=MONTH({at})),'{previous}'!$B${_V4_CARRY_PASSED_ROW},0)")
        if phase >= queues or phase >= 4:
            # Последней очереди передавать некому: «перенос» был бы фикцией.
            passed[column] = "0"
        else:
            passed[column] = (
                f"IF(AND({flag},{next_enabled}),{column}{_V4_RVE_UNPAID_ROW},0)")

    unpaid_xml = _v4_carry_row_xml(
        _V4_RVE_UNPAID_ROW, "ПФ — не покрыто раскрытым эскроу", unpaid)
    rows_xml = (_v4_carry_row_xml(_V4_CARRY_ACCEPTED_ROW,
                                  "ПФ — принятый долг предыдущей очереди", accepted)
                + _v4_carry_row_xml(_V4_CARRY_PASSED_ROW,
                                    "ПФ — долг передан следующей очереди", passed))
    marker = '<x:row r="66"'
    if marker not in xml:
        missing.append(f"{sheet}: не найдена строка 66 — ряд переноса вставить некуда")
        return xml
    if f'<x:row r="{_V4_CARRY_ACCEPTED_ROW}"' in xml:
        missing.append(f"{sheet}: строка {_V4_CARRY_ACCEPTED_ROW} уже занята")
        return xml
    at = xml.index(marker)
    xml = xml[:at] + rows_xml + xml[at:]
    # Строка 29 в шаблоне существует, но пуста: в XML есть сам элемент <x:row>
    # без ячеек. Заполняем его, а не вставляем второй с тем же номером —
    # Excel вправе счесть такой лист повреждённым. Непустую строку не трогаем:
    # значит шаблон изменился, и молча писать поверх нельзя.
    existing = re.search(
        r'<x:row r="%d"[^>]*>(.*?)</x:row>' % _V4_RVE_UNPAID_ROW, xml, re.S)
    if existing:
        # «Занята» — это есть значение или формула, а не есть ячейки: пустая
        # строка шаблона состоит из самозакрытых <x:c r="A29" /> со стилями.
        if "<x:v>" in existing.group(1) or "<x:f>" in existing.group(1):
            missing.append(f"{sheet}: строка {_V4_RVE_UNPAID_ROW} занята")
            return xml
        xml = xml[:existing.start()] + unpaid_xml + xml[existing.end():]
    else:
        unpaid_marker = f'<x:row r="{_V4_RVE_UNPAID_ROW + 1}"'
        if unpaid_marker not in xml:
            missing.append(f"{sheet}: не найдена строка {_V4_RVE_UNPAID_ROW + 1}")
            return xml
        at = xml.index(unpaid_marker)
        xml = xml[:at] + unpaid_xml + xml[at:]

    # Правки формул. Каждая — точной строкой, а не по всему листу: `L38+L45`
    # встречается и там, где принятый долг не при чём.
    a = _V4_CARRY_ACCEPTED_ROW
    b = _V4_CARRY_PASSED_ROW
    # Правки по строкам, а не по всему листу: `L38+L45` встречается и там, где
    # принятый долг ни при чём. Сравнения в XML хранятся сущностями (`&gt;`),
    # и искать надо именно их — иначе формула «не опознана» на ровном месте.
    edits: dict[int, list[tuple[str, str]]] = {row: [] for row in (40, 42, 43, 44, 46, 47, 61)}
    for index, column in enumerate(columns):
        # Долг на конец и его же проверка roll-forward.
        edits[47].append((f"MAX(0,{column}38+{column}45-{column}46)",
                          f"MAX(0,{column}38+{column}45+{column}{a}-{column}46-{column}{b})"))
        edits[61].append((f"{column}47-({column}38+{column}45-{column}46)",
                          f"{column}47-({column}38+{column}45+{column}{a}-{column}46-{column}{b})"))
        # Проценты и покрытие эскроу — принятый долг входит в базу: он несёт
        # проценты как тело, и покрывать его тоже надо.
        edits[42].append((f"({column}38+{column}45)&gt;0",
                          f"({column}38+{column}45+{column}{a})&gt;0"))
        edits[42].append((f"({column}38+{column}45)*{column}41/12",
                          f"({column}38+{column}45+{column}{a})*{column}41/12"))
        # А плата за невыбранный лимит — НЕТ, и это разные правила под одной
        # строкой комментария. Принятый долг лимита не выбирает (решение
        # владельца, 27.08.2026), значит и свободного лимита не уменьшает.
        # Прежде он входил и сюда: долг приезжает в строку 38 из остатка 47,
        # поэтому база вычитается своей — остаток за вычетом накопленного
        # принятого. Движок делает то же самое (`own_pf_principal`), и обе
        # поверхности ошибались ОДИНАКОВО — паритет на это молчал.
        # Накопленное принятое берётся по ПРЕДЫДУЩИЕ месяцы: долг этого месяца
        # в остаток на начало (38) ещё не вошёл — он попадает туда через
        # остаток на конец (47) только со следующей колонки. Сложенный с ним
        # здесь, он вычитался бы из базы, которой в ней нет, и в месяц приёма
        # плата выходила на свой же размер больше — 4,1 млн ₽ на проверочном
        # проекте, ровно один месяц из двадцати четырёх. В первой колонке
        # предыдущей нет, и накопленного тоже.
        # И не просто накопленное, а ОСТАТОК принятого: кэш-свип (строка 26)
        # гасит именно его — он ради него и заведён. Не вычти сметённое, и
        # база уменьшится на уже погашенное, а свободный лимит с платой за
        # него вырастут на ту же величину.
        if index == 0:
            seen_accepted = ""
        else:
            previous_column = columns[index - 1]
            seen_accepted = (
                f"-MAX(0,SUM($D${a}:{previous_column}{a})"
                f"-SUM($D${_V4_SWEEP_ROW}:{previous_column}{_V4_SWEEP_ROW}))")
        edits[43].append((f"-({column}38+{column}45))",
                          f"-MAX(0,{column}38+{column}45{seen_accepted}))"))
        edits[40].append((f"MAX(1,{column}38+{column}45)",
                          f"MAX(1,{column}38+{column}45+{column}{a})"))
        edits[46].append((f"MIN({column}38+{column}45,",
                          f"MIN({column}38+{column}45+{column}{a},"))
        # Линия закрыта после того, как долг с неё ушёл: банковской потребности
        # больше нет. Гасится она в строке 44, а не в выборке 45: иначе книга
        # считала бы потребность, которую никто не финансирует, и её же
        # проверка «потребность профинансирована полностью» краснела бы на
        # ровном месте — 270 млн ₽ на проверочном проекте. Расход остаточного
        # периода никуда не девается, он платится кассой.
        #
        # Признак «перенос уже случился» — накопленная строка 65 по ПРЕДЫДУЩИЕ
        # месяцы, а не её итог B65: итог суммирует в том числе этот месяц, а
        # строка 65 читает строку 45, которая читает 44, — вышла бы круговая
        # ссылка, и Excel сказал бы то же, что сказал вычислитель формул. В
        # месяц РВЭ выборка ещё идёт: движок в этот месяц выбирает, гасит
        # раскрытым эскроу и только потом отдаёт остаток. В первом месяце
        # модели переносить нечему — формула остаётся прежней.
        if index == 0:
            continue
        # Признак «линия уже закрыта» — накопленная нехватка по ПРЕДЫДУЩИЕ
        # месяцы: итог строки суммирует и этот месяц, а он читает строки 44–46,
        # и вышла бы круговая ссылка.
        # Закрывается линия по факту ПЕРЕНОСА (строка 65), а не по факту
        # нехватки: дефолт модель называет, но на нём не обрывается —
        # реструктуризацию считаем прежним допущением и говорим о нём вслух.
        seen = f"SUM($D${b}:{columns[index - 1]}{b})"
        # Вторая закрытая линия — рассчитавшаяся: раскрытый эскроу погасил
        # долг целиком (строка 29 по предыдущие месяцы — ноль), и после РВЭ
        # выбирать больше нечего, расход платит касса. Иначе поздний платёж
        # рассрочки за покупку выбирался с закрытой линии и оставался
        # «непогашенным долгом» проекта с LLCR 1,23x (04.09.2026). Остался
        # долг в РВЭ и не передан — прежнее допущение: линия обслуживается
        # продажами дальше, и книга считает так же, как движок.
        unpaid_seen = f"SUM($D${_V4_RVE_UNPAID_ROW}:{columns[index - 1]}{_V4_RVE_UNPAID_ROW})"
        edits[44].append((f"<x:f>IF({column}$3&gt;=$B$7,",
                          f"<x:f>IF(AND({column}$3&gt;=$B$7,"
                          f"OR({column}$3&lt;=$B$8,AND({seen}&lt;=0,{unpaid_seen}&gt;0))),"))
        # Закрытая линия не собирает: остаточные продажи остаются застройщику.
        edits[46].append((f"<x:f>MIN({column}38+{column}45+{column}{a},",
                          f"<x:f>IF(AND({seen}&gt;0,{column}$3&gt;$B$8),0,"
                          f"MIN({column}38+{column}45+{column}{a},"))
        edits[46].append((f"IF({column}$3&gt;$B$8,{column}12,0)))</x:f>",
                          f"IF({column}$3&gt;$B$8,{column}12,0))))</x:f>"))
        # И не начисляет: проценты по договорной ставке на закрытом НКЛ — та же
        # фикция, из-за которой остаток «гасился» продажами.
        edits[42].append((f"IF(AND(({column}38+{column}45+{column}{a})&gt;0,",
                          f"IF(AND({seen}&lt;=0,({column}38+{column}45+{column}{a})&gt;0,"))
    for row in sorted(edits):
        pattern = re.compile(r'(<x:row r="%d">)(.*?)(</x:row>)' % row, re.S)
        found = pattern.search(xml)
        if not found:
            missing.append(f"{sheet}: строка {row} не найдена")
            return xml
        body = found.group(2)
        for old, new in edits[row]:
            if old not in body:
                missing.append(f"{sheet}: формула строки {row} не опознана ({old})")
                return xml
            body = body.replace(old, new, 1)
        xml = (xml[:found.start()] + found.group(1) + body + found.group(3)
               + xml[found.end():])
    return xml


# Выручка очереди по продуктам на листе КОНСОЛИДАТОР.
#
# «Выручка одной строкой не говорит, чем очередь живёт: у одной весь объём в
# квартирах, у другой треть в офисах и ОСЗ, а маржа и риск у них разные»
# (владелец, 23.08.2026). На экране разбивка есть, а в книге жила только в
# выгрузке детализации — и уехала вместе с ней, когда архив очередей сняли.
# Переносится в живую книгу: колонки Q и дальше свободны во всех строках, ряд
# встаёт, не сдвигая ни одной ссылки.
#
# Числа книга считает сама, своими формулами: площадные продукты — с листа
# «Продажи» (блок очереди через 23 строки), отдельно стоящие объекты — с листа
# «ОБЪЕКТЫ», и там же лежит номер очереди, в которой объект финансируется.
_V4_TEP_PHASE_STRIDE = 6                  # шаг блока очереди на листе ТЭП
_V4_TEP_STORAGE_ROW = 7                   # строка «Кладовые» первой очереди
_V4_REPORT_STORAGE_ROW = 49               # строка «Кладовые» структуры продукта
_V4_CONSOLIDATOR_ROWS = (4, 5, 6, 7)      # очереди 1–4
_V4_CONSOLIDATOR_TOTAL_ROW = 8
_V4_CONSOLIDATOR_FIRST_COL = 17           # Q — первая свободная
_V4_SALES_PHASE_STRIDE = 23               # шаг блока очереди на листе «Продажи»
_V4_SALES_PRODUCT_ROW = {                 # строка выручки в блоке первой очереди
    "apartments": 16,
    "ground_commercial": 19,
    "underground_parking": 22,
    "storage": 25,
}
# Ключ продукта «паркинг объектов» объявлен в движке
# (`NON_TEP_PRODUCT_LABELS`) — здесь только имя, по которому книга узнаёт свой
# случай; строки его выручки стоят в `_V4_OBJECT_PARKING`.
# Продукт «паркинг объекта» — у каждого объекта свой ключ; книга узнаёт его
# здесь и находит строку выручки объекта в `_V4_OBJECT_PARKING_BY_KEY`.
_V4_OBJECT_PARKING_KEYS = {pkey: okey for okey, pkey in OBJECT_PARKING_PRODUCT_KEYS.items()}

_V4_OBJECT_PRODUCT_CELLS = {              # (очередь объекта, его выручка)
    "offices": (8, 24),
    "standalone_retail": (36, 52),
    "above_parking": (64, 80),
}
# Дописанные объекты — копии блоков шаблона со сдвигом: строки те же, что у
# двойника, плюс сдвиг его копии.
_V4_OBJECT_PRODUCT_CELLS.update({
    lay.obj.key: tuple(row + lay.object_offset
                       for row in _V4_OBJECT_PRODUCT_CELLS[lay.twin])
    for lay in _V4_EXTRA_OBJECT_LAYOUTS})
# Шаблон несёт ТРИ блока объектов; всё, что ниже, дописано копированием — и
# лист ПРОВЕРКИ о дописанном узнаёт отсюда, а не из выписанных формул.
_V4_TEMPLATE_OBJECT_REVENUE_ROWS = (24, 52, 80)
_V4_OBJECT_CHECKS_CAPEX_SHIFT = 4         # строка CAPEX блока = его выручка + 4
# Проверки объекта на листе ПРОВЕРКИ: строка «реализованный объём» и строка
# «CAPEX», по строке «включён» блока ОБЪЕКТЫ. У ФОКа своих строк в шаблоне нет
# — он дописан ниже трёх шаблонных, и проверок ему не заведено; сказано вслух,
# чтобы молчание не читалось как «его проверяют».
_V4_OBJECT_CHECK_ROWS = {
    7: (39, 40),        # МФОЦ / офисы
    35: (42, 43),       # ТЦ / ОСЗ
}


# --- дописанные объекты в книге v4 ------------------------------------------
# Объект в книге появляется ровно так же, как в движке, — иначе книга снова
# станет придатком веб-сервиса. Шаблон несёт ТРИ блока отдельно стоящих
# объектов (строки 6/34/62 листа ОБЪЕКТЫ) и три блока их вводных (J18/J38/J58
# «Вводных»). Следующие дописываются в СВОБОДНЫЙ низ обоих листов: вставить
# строку в занятое место нельзя — поедут все ссылки. Где именно — решает
# раскладка `_v4_object_layouts`.
#
# Формулы блока НЕ пишутся заново: они снимаются с блока двойника и
# переносятся со сдвигом строк. Сочинить их кодом значило бы завести вторую
# реализацию методики владельца — ту самую, которую запрещает правило
# «пересобирать книгу целиком нельзя». Перенос механический: ссылки на строки
# своего блока сдвигаются, ссылки на другие листы остаются, а вводные двойника
# подменяются вводными объекта.
_V4_OBJECT_BLOCK_ROWS = 26                # заголовок блока ОБЪЕКТЫ … «Расходы всего»
_V4_OBJECT_SALE_WORD = "Продаётся"
_V4_OBJECT_TRANSFER_WORD = "Передаётся городу"

# Подписи блока вводных по строке от заголовка: у двойника они свои, и
# оставить его ключи значило бы завести в книге второй торговый центр. Ключ
# API меняется тем же проходом — по нему книга и движок сверяются, и
# «retail_*» в блоке ФОКа сделал бы сверку бессмысленной. Две формы — метры и
# места: у наземного паркинга своя.
_V4_OBJECT_INPUT_LABELS = {
    "sqm": {
        2: ("Объект включён", "Да / Нет", "enabled"),
        3: ("Очередь финансирования", "1–4", "queue"),
        4: ("Пересчитывать по плотности", "Да / Нет", "density_linked"),
        5: ("Базовая общая площадь (GBA)", "м²", "gba_base_sqm"),
        6: ("Базовая продаваемая площадь", "м²", "saleable_base_sqm"),
        7: ("Расчётная общая площадь (GBA)", "м²", "gba_sqm"),
        8: ("Расчётная продаваемая площадь", "м²", "saleable_sqm"),
        9: ("Начало строительства", "дата", "start"),
        10: ("Срок строительства", "мес.", "months"),
        11: ("Себестоимость строительства", "тыс. ₽/м² GBA", "cost_th_per_sqm"),
        12: ("Старт продаж", "дата", "sales_start"),
        13: ("Стартовая цена", "тыс. ₽/м²", "price_th_per_sqm"),
        14: ("Доля продаж до РВЭ", "%", "share_before_rve_pct"),
        15: ("Общий срок продаж", "мес.", "sales_term_months"),
        16: ("Рост цены до РВЭ", "%/мес.", "growth_pre_pct"),
        17: ("Рост цены после РВЭ", "%/мес.", "growth_post_pct"),
    },
    "spaces": {
        2: ("Объект включён", "Да / Нет", "enabled"),
        3: ("Очередь финансирования", "1–4", "queue"),
        4: ("Пересчитывать по плотности", "Да / Нет", "density_linked"),
        5: ("Базовое количество машино-мест", "шт.", "spaces_base"),
        6: ("Площадь на одно место для ТЭП", "м²/место", "area_per_space_sqm"),
        7: ("Расчётное количество машино-мест", "шт.", "spaces"),
        8: ("Расчётная общая площадь (GBA)", "м²", "gba_sqm"),
        9: ("Себестоимость одного места", "млн ₽/место", "cost_mln_per_space"),
        10: ("Начало строительства", "дата", "start"),
        11: ("Срок строительства", "мес.", "months"),
        12: ("Старт продаж", "дата", "sales_start"),
        13: ("Стартовая цена места", "млн ₽/место", "price_mln_per_space"),
        14: ("Доля продаж до РВЭ", "%", "share_before_rve_pct"),
        15: ("Общий срок продаж", "мес.", "sales_term_months"),
        16: ("Рост цены до РВЭ", "%/мес.", "growth_pre_pct"),
        17: ("Рост цены после РВЭ", "%/мес.", "growth_post_pct"),
    },
}
# Строки блока вводных по месту от заголовка — у метров и у мест они разные
# (у паркинга срок стройки ниже на строку).
_V4_OBJECT_INPUT_ROW = {
    "sqm": {"enabled": 2, "queue": 3, "density": 4, "base": 5, "base_saleable": 6,
            "gba": 7, "saleable": 8, "start": 9, "months": 10, "sales_start": 12,
            "price": 13, "term": 15},
    "spaces": {"enabled": 2, "queue": 3, "density": 4, "base": 5, "base_saleable": 0,
               "gba": 8, "saleable": 0, "start": 10, "months": 11, "sales_start": 12,
               "price": 13, "term": 15},
}


def _v4_input_row(lay: _V4ObjectLayout, name: str) -> int:
    """Строка вводной `name` в блоке объекта на «Параметрах модели»."""
    at = _V4_OBJECT_INPUT_ROW[lay.obj.measure][name]
    return lay.input_head + at if at else 0


_V4_SHEET_REF_RE = re.compile(r"'[^']+'!\$?[A-Z]{1,3}\$?\d+")
_V4_BARE_REF_RE = re.compile(r"(?<![A-Za-z0-9_$!])(\$?)([A-Z]{1,3})(\$?)(\d+)")


def _v4_shift_formula(formula: str, rows: range, offset: int,
                      input_rows: range | None = None,
                      input_offset: int = 0) -> str:
    """Переносит формулу блока на `offset` строк, не трогая чужие листы.

    Ссылка на «Вводные» — не строка нашего блока, и сдвигать её общим правилом
    нельзя: `'Вводные'!$K$45` попала бы под диапазон 34–59 и уехала бы в чужую
    ячейку с уверенным видом. Поэтому чужие листы сперва прячутся за метки, и
    только потом сдвигаются свои строки.
    """
    protected: list[str] = []

    def hide(match: "re.Match[str]") -> str:
        ref = match.group(0)
        if input_rows is not None and ref.startswith("'Вводные'!"):
            tail = re.match(r"'Вводные'!(\$?)([A-Z]{1,3})(\$?)(\d+)$", ref)
            if tail and tail.group(2) == "K" and int(tail.group(4)) in input_rows:
                ref = (f"'Вводные'!{tail.group(1)}K{tail.group(3)}"
                       f"{int(tail.group(4)) + input_offset}")
        protected.append(ref)
        return f"\x00{len(protected) - 1}\x00"

    body = _V4_SHEET_REF_RE.sub(hide, formula)

    def shift(match: "re.Match[str]") -> str:
        row = int(match.group(4))
        if row not in rows:
            return match.group(0)
        return f"{match.group(1)}{match.group(2)}{match.group(3)}{row + offset}"

    body = _V4_BARE_REF_RE.sub(shift, body)
    for index, ref in enumerate(protected):
        body = body.replace(f"\x00{index}\x00", ref)
    return body


def _v4_copy_block(xml: str, rows: range, offset: int, *,
                   input_rows: range | None = None, input_offset: int = 0,
                   ) -> tuple[str, list[int]]:
    """Копирует строки листа со сдвигом, сохраняя стили и формулы.

    Стиль едет вместе с содержимым: дописанная строка без стиля — единственная
    неокрашенная на листе ровно там, где написано «правьте значения».
    """
    written: list[int] = []
    parts: list[str] = []
    for row in rows:
        found = re.search(r'<x:row r="%d"(?:[ ][^>]*)?>(.*?)</x:row>' % row, xml, re.S)
        if not found:
            continue
        body = found.group(1)
        target = row + offset
        body = re.sub(r'(<x:c r="([A-Z]{1,3}))%d"' % row,
                      lambda m: f'{m.group(1)}{target}"', body)
        body = re.sub(
            r"<x:f>(.*?)</x:f>",
            lambda m: "<x:f>" + xml_escape(_v4_shift_formula(
                html.unescape(m.group(1)), rows, offset,
                input_rows=input_rows, input_offset=input_offset)) + "</x:f>",
            body, flags=re.S)
        parts.append(f'<x:row r="{target}">' + body + "</x:row>")
        written.append(target)
    tail = "</x:sheetData>"
    if not parts or tail not in xml:
        return xml, []
    return xml.replace(tail, "".join(parts) + tail, 1), written


def _v4_extra_inputs_blocks(xml: str, missing: list[str]) -> str:
    """Блоки вводных дописанных объектов: копии блоков двойников со своими подписями."""
    for lay in _v4_extras():
        xml = _v4_extra_inputs_block(xml, lay, missing)
    return xml


def _v4_extra_inputs_block(xml: str, lay: _V4ObjectLayout, missing: list[str]) -> str:
    obj, head = lay.obj, lay.input_head
    name = obj.group_label or obj.label
    title = name.upper()
    twin_head = head - lay.input_offset
    if re.search(r'<x:row r="%d"[ />]' % head, xml):
        missing.append(f"{name}: строка {head} «Вводных» занята")
        return xml
    rows = range(twin_head, twin_head + _V4_INPUT_BLOCK_ROWS)
    xml, written = _v4_copy_block(xml, rows, lay.input_offset)
    if len(written) != len(rows):
        missing.append(f"{name}: блок вводных не скопирован целиком")
        return xml
    # Колонки A–D блока двойника уехали бы вместе с ним: там живут статьи
    # себестоимости, и вторая их копия читалась бы как второй набор ставок.
    for row in written:
        xml = re.sub(r'<x:c r="[A-D]%d"[^>]*?(?:/>|>.*?</x:c>)' % row, "", xml,
                     flags=re.S)
    labels = {head: (title, None, None)}
    labels.update({head + at: (label, unit, f"{obj.prefix}_{suffix}")
                   for at, (label, unit, suffix)
                   in _V4_OBJECT_INPUT_LABELS[obj.measure].items()})
    for row, (label, unit, key) in labels.items():
        xml, done = _v4_set_cell(xml, f"J{row}", text=label)
        if not done:
            missing.append(f"{name}: подпись J{row}")
        if unit is not None:
            xml, _ = _v4_set_cell(xml, f"L{row}", text=unit)
        if key is not None:
            xml, _ = _v4_set_cell(xml, f"M{row}", text=key)
    # Заголовок блока написан во всех четырёх ячейках — так его пишет шаблон.
    for column in ("K", "L", "M"):
        xml, _ = _v4_set_cell(xml, f"{column}{head}", text=title)
    # Признак «что с объектом дальше» и остаточные продажи — строки сверх
    # блока двойника, и берутся они КОПИЕЙ его строк, а не пустыми ячейками.
    # Лист ввода узнаёт вводную ПО ЦВЕТУ, и голая ячейка осталась бы на
    # расчётном листе — то есть приглашала бы печатать там, где печатать
    # нельзя. Образцы выбраны по типу значения: «включён» — «Да/Нет»,
    # одиннадцатая строка блока — число.
    extra_rows = [(twin_head + 11, lay.residual_row)]
    if lay.disposition_row:
        extra_rows.insert(0, (twin_head + 2, lay.disposition_row))
    for source_row, target_row in extra_rows:
        xml, written_extra = _v4_copy_block(xml, range(source_row, source_row + 1),
                                            target_row - source_row)
        if len(written_extra) != 1:
            missing.append(f"{name}: строка {target_row} «Вводных» не заведена")
            continue
        xml = re.sub(r'<x:c r="[A-D]%d"[^>]*?(?:/>|>.*?</x:c>)' % target_row, "", xml,
                     flags=re.S)
    if not lay.disposition_row:
        return xml
    row = lay.disposition_row
    for coord, text in ((f"J{row}", "Что с объектом дальше"),
                        (f"L{row}", f"{_V4_OBJECT_TRANSFER_WORD} / {_V4_OBJECT_SALE_WORD}"),
                        (f"M{row}", obj.sale_gate),
                        (f"K{row}", _V4_OBJECT_TRANSFER_WORD)):
        xml, done = _v4_set_cell(xml, coord, text=text)
        if not done:
            missing.append(f"{name}: ячейка {coord}")
    # Продаваемая площадь гаснет при передаче городу — той же формулой, что и
    # включение объекта: переданный объект строится, но не продаётся. Стройка
    # при этом идёт от РАСЧЁТНОЙ ОБЩЕЙ площади и остаётся на месте.
    saleable = _v4_input_row(lay, "saleable")
    if saleable:
        xml, done = _v4_set_cell(
            xml, f"K{saleable}",
            formula=(f'IF(AND(K{_v4_input_row(lay, "enabled")}="Да",'
                     f'K{row}="{_V4_OBJECT_SALE_WORD}"),'
                     f'K{_v4_input_row(lay, "base_saleable")}'
                     f'*IF(K{_v4_input_row(lay, "density")}="Да",$K$15,1),0)'))
        if not done:
            missing.append(f"{name}: формула продаваемой площади K{saleable}")
    return xml


# Паркинг отдельно стоящих объектов в книге. Три места, и все три обязательны:
# подпись блока вводных, деньги объекта и дверь в CF.
#
# CAPEX своего подземного считается ПО ТОЙ ЖЕ ставке подземной части, что и у
# движка, и теми же множителями инфляции очереди, что и остальной CAPEX
# объекта: иначе книга и отчёт разойдутся ровно на инфляцию, а выглядеть это
# будет как ошибка счёта.
#
# Выручка мест идёт СВОЕЙ строкой, а не прибавляется к «Продажам по договорам»:
# там же рядом стоит «Цена реализации» = продажи / метры, и подмешанные в неё
# деньги мест дали бы цену офисного метра, которой никто не назначал.
_V4_OBJECT_PARKING = (
    # (подпись, строка «включён», строка мест, строка выручки, ячейка CAPEX,
    #  «мест под землёй», «мест на этажах», строка объёма продаж объекта,
    #  строка цены объекта, ячейка цены объекта, ячейка GBA объекта,
    #  строка «Расчётная продаваемая площадь» объекта, места продаются,
    #  ячейка гостевых мест — пусто, если продавать нечего,
    #  ячейки своей цены места под землёй и на этаже — пусто, если нечего)
    ("МФОЦ / офисы", 7, 32, 33, "B28", "K161", "K162", 22, 23, "K31", "K25", 13,
     True, "K167", ("K169", "K170")),
    ("ТЦ / ОСЗ", 35, 60, 61, "B56", "K163", "K164", 50, 51, "K51", "K45", 41,
     False, "", ("", "")),
)
# Дописанный объект с гаражом — строки двойника со сдвигом его копии; места и
# цены мест — свои ячейки из раскладки.
_V4_OBJECT_PARKING = _V4_OBJECT_PARKING + tuple(
    (lay.obj.group_label or lay.obj.label,
     *(row + lay.object_offset for row in twin[1:4]),
     _v4_row_shift(twin[4], lay.object_offset),
     lay.parking_under, lay.parking_over,
     *(row + lay.object_offset for row in twin[7:9]),
     _v4_row_shift(twin[9], lay.input_offset), _v4_row_shift(twin[10], lay.input_offset),
     twin[11] + lay.object_offset, lay.obj.garage_sellable, lay.parking_guest,
     (lay.parking_under_price, lay.parking_over_price))
    for lay in _V4_EXTRA_OBJECT_LAYOUTS if lay.parking_under
    for twin in [next(item for item in _V4_OBJECT_PARKING
                      if item[1] == _V4_TEMPLATE_OBJECT_LAYOUT[lay.twin][1] + 1)])
# Строка паркинга книги у КАЖДОГО объекта — по явному признаку: ячейке «мест в
# своём подземном» из раскладки объекта, а не по порядку перечисления. Её читает
# колонка выручки «Паркинг — <объект>» в КОНСОЛИДАТОРЕ.
_V4_OBJECT_PARKING_BY_KEY = {
    lay.obj.key: next(item for item in _V4_OBJECT_PARKING if item[5] == lay.parking_under)
    for lay in _V4_OBJECT_LAYOUTS if lay.parking_under
}
_V4_OBJECT_PARKING_INPUT_ROWS = (
    # (строка, подпись, ячейка значения, единица) — номер строки задан явно, а
    # не выведен из порядка: снятая строка сдвинула бы все ячейки под собой, и
    # значения уехали бы в чужие клетки. Места дописанных объектов — из их
    # раскладки (`_v4_object_parking_input_rows`).
    (157, "ПАРКИНГ ОТДЕЛЬНО СТОЯЩИХ ОБЪЕКТОВ · МЕСТА", None, None),
    (158, "Площадь на 1 место своего подземного", "K158", "м²/место"),
    (159, "Приобъектная стоянка нормируется отдельно: она вдоль проезда, "
          "в благоустройстве, и здесь её нет", None, None),
    (160, "Площадь на 1 место на первых этажах", "K160", "м²/место"),
    (161, "Офисы — мест в своём подземном", "K161", "шт."),
    (162, "Офисы — мест на первых этажах", "K162", "шт."),
    (163, "ТЦ / ОСЗ — мест в своём подземном", "K163", "шт."),
    (164, "ТЦ / ОСЗ — мест на первых этажах", "K164", "шт."),
    (167, "Офисы — гостевых (не продаются)", "K167", "доля мест"),
    (169, "Офисы — цена подземного места (0 = общая цена)", "K169", "млн ₽/место"),
    (170, "Офисы — цена места на первом этаже (0 = общая цена)", "K170", "млн ₽/место"),
)


def _v4_object_parking_input_rows() -> tuple[tuple[int, str, str | None, str | None], ...]:
    """Строки мест всех объектов с гаражом: общий блок и блоки дописанных."""
    rows = list(_V4_OBJECT_PARKING_INPUT_ROWS)
    for lay in _v4_extras():
        name = lay.obj.group_label or lay.obj.label
        for coord, text, unit in (
                (lay.parking_under, "мест в своём подземном", "шт."),
                (lay.parking_over, "мест на первых этажах", "шт."),
                (lay.parking_guest, "гостевых (не продаются)", "доля мест"),
                (lay.parking_under_price, "цена подземного места (0 = общая цена)",
                 "млн ₽/место"),
                (lay.parking_over_price, "цена места на первом этаже (0 = общая цена)",
                 "млн ₽/место")):
            if coord:
                rows.append((int(coord[1:]), f"{name} — {text}", coord, unit))
    return tuple(sorted(rows, key=lambda item: item[0]))


def _v4_object_saleable_formula(lay: _V4ObjectLayout) -> str:
    """Продаваемая площадь объекта с гаражом: за вычетом пятна мест на этажах.

    Первые этажи занимают существующую GBA. Сначала вычитаем их пятно из
    расчётной GBA, затем применяем исходную долю продаваемой площади. Объект
    с признаком «что дальше» при передаче городу не продаёт ничего.
    """
    row = lambda name: f"K{_v4_input_row(lay, name)}"
    enabled = f'{row("enabled")}="Да"'
    if lay.disposition_row:
        enabled = f'AND({enabled},K{lay.disposition_row}="{_V4_OBJECT_SALE_WORD}")'
    base, gba = row("base"), row("gba")
    return (f'IF({enabled},IF({base}>0,MAX(0,{gba}-{lay.parking_over}*$K$160)'
            f'*{row("base_saleable")}/{base},0),0)')


def _v4_object_parking_input_labels(xml: str, missing: list[str]) -> str:
    """Подписи блока размещения мест на листе «Параметры модели».

    Значение и ключ пишет общая карта `_V4_INPUT_CELLS`; без подписи и единицы
    рядом это столбик чисел, о котором человек не знает, что правит.
    """
    for row, label, coord, unit in _v4_object_parking_input_rows():
        # Строки внизу листа не существует, пока её не завели: пустых строк в
        # файле не бывает, и запись значения по карте ключей молча не нашла бы
        # ячейку — так эти вводные и приезжали в книгу пустыми.
        xml = _v4_ensure_row(xml, row)
        xml, done = _v4_set_or_insert_cell(xml, f"J{row}", text=label)
        if not done:
            missing.append(f"паркинг объектов: подпись J{row}")
        if unit:
            xml, done = _v4_set_or_insert_cell(xml, f"L{row}", text=unit)
            if not done:
                missing.append(f"паркинг объектов: единица L{row}")
        if coord:
            # Место под значение И под ключ: общая карта пишет и то и другое
            # заменой, а в несуществующую ячейку замена не попадает. Ключ живёт
            # в колонке M — без него книгу нечем сверить с движком по имени.
            for cell in (coord, "M" + coord[1:]):
                xml, done = _v4_set_or_insert_cell(xml, cell, number=0)
                if not done:
                    missing.append(f"паркинг объектов: место под {cell}")
    garaged = sorted((lay for lay in _v4_layouts()
                      if lay.parking_over and _v4_input_row(lay, "saleable")),
                     key=lambda lay: lay.input_head)
    formulas = {f"K{_v4_input_row(lay, 'saleable')}": _v4_object_saleable_formula(lay)
                for lay in garaged}
    for coord, formula in formulas.items():
        xml, done = _v4_set_or_insert_cell(xml, coord, formula=formula)
        if not done:
            missing.append(f"паркинг объектов: остаточная GBA в {coord}")

    xml = _v4_ensure_row(xml, 168)
    xml, done = _v4_set_or_insert_cell(
        xml, "J168", text="Проверка: места на первых этажах помещаются в ГНС")
    if not done:
        missing.append("паркинг объектов: подпись проверки J168")
    guard = ("IF(OR(" + ",".join(
        f'AND(K{_v4_input_row(lay, "enabled")}="Да",'
        f'{lay.parking_over}*$K$160>K{_v4_input_row(lay, "gba")})' for lay in garaged)
        + '),"WARN: паркинг первых этажей не помещается в GBA объекта","OK")')
    xml, done = _v4_set_or_insert_cell(xml, "K168", formula=guard)
    if not done:
        missing.append("паркинг объектов: проверка K168")
    return xml


def _v4_object_parking_block(xml: str, missing: list[str]) -> str:
    """Деньги паркинга отдельно стоящих объектов на листе ОБЪЕКТЫ.

    Строки 32–33 и 60–61 в шаблоне пусты — это зазор между блоками объектов, и
    ряд встаёт туда. Вставить строку в занятое место нельзя: поедет всё, что на
    неё ссылается.
    """
    for (label, enabled_row, units_row, revenue_row, capex_cell, under, over,
         volume_row, price_row, price_cell, gba_cell,
         saleable_row, sellable, guest_cell, own_prices) in _v4_object_parking():
        for row in (units_row, revenue_row):
            if re.search(r'<x:c r="A%d"[ />]' % row, xml):
                missing.append(f"паркинг объектов: строка {row} листа ОБЪЕКТЫ занята")
                return xml
            xml = _v4_ensure_row(xml, row)
        # Построено — не то же, что продано, и в книге это ДВА разных числа.
        # Место в ТЦ не покупают: там паркинг обеспечивает посетителей
        # (владелец, 06.09.2026). У офисника продаются все, кроме гостевых.
        # Строка выручки идёт от ПРОДАВАЕМЫХ; метры и CAPEX — от построенных,
        # они выше и признаком продажи не гасятся.
        block_sheet = re.search(r"('[^']+')!", _v4_cell_formula(xml, f"B{enabled_row}") or "")
        params = block_sheet.group(1) if block_sheet else "'Вводные'"
        built = f"({params}!${under[0]}${under[1:]}+{params}!${over[0]}${over[1:]})"
        if not sellable:
            spaces = "0"
        elif guest_cell:
            # Гостевые — ДОЛЯ мест объекта, а не штуки: число мест меняется
            # вместе с ТЭП. Ячейка несёт долю (0,1), потому что все ключи на
            # `_pct` книга хранит долей — второй порядок величины в одной
            # колонке читался бы как ошибка счёта.
            spaces = (f"MAX(0,{built}-ROUND({built}*"
                      f"{params}!${guest_cell[0]}${guest_cell[1:]},0))")
        else:
            spaces = built
        # Продаваемая площадь уже пересчитана на листе Параметры модели от
        # остаточной GBA. Здесь ОБЪЕКТЫ только читает её: второго вычета нет.
        if _v4_cell_formula(xml, f"B{saleable_row}") is None:
            missing.append(f"паркинг объектов: продаваемая B{saleable_row} не найдена")
        xml, done = _v4_set_or_insert_cell(
            xml, f"A{units_row}", text="Паркинг объекта — мест")
        if not done:
            missing.append(f"паркинг объектов: подпись A{units_row}")
        xml, done = _v4_set_or_insert_cell(
            xml, f"B{units_row}",
            formula=f'IF($B${enabled_row}="Да",{spaces},0)')
        if not done:
            missing.append(f"паркинг объектов: мест B{units_row}")
        xml, done = _v4_set_or_insert_cell(
            xml, f"A{revenue_row}", text="Паркинг объекта — выручка")
        if not done:
            missing.append(f"паркинг объектов: подпись A{revenue_row}")
        # Продаются места тем же профилем, что и сам объект: строки 19 и 21 —
        # нормированные веса до и после РВЭ, они уже посчитаны блоком.
        xml, done = _v4_set_or_insert_cell(
            xml, f"B{revenue_row}",
            formula=f"SUM(D{revenue_row}:{_V4_LAST_COLUMN}{revenue_row})")
        if not done:
            missing.append(f"паркинг объектов: итог B{revenue_row}")
        # Помесячно места продаются тем же профилем, что и метры объекта: доля
        # проданного за месяц берётся из его же строки объёма. Второй набор
        # весов однажды разошёлся бы с первым, и обе кривые выглядели бы верными.
        # Цена — цена машино-места с тем же ростом, что у объекта: формула цены
        # берётся из его строки и в ней подменяется базовая ставка. Написать
        # свою значило бы завести вторую реализацию цены.
        # Месяцы пишутся ПАЧКОЙ на строку, а не ячейка за ячейкой: лист
        # мегабайтный, и проход по нему на каждую ячейку стоит дороже самой
        # записи (см. `_v4_set_cells` и `_v4_row_formulas`).
        prices = _v4_row_formulas(xml, price_row)
        month_units: dict[str, dict[str, Any]] = {}
        month_value: dict[str, dict[str, Any]] = {}
        written = 0
        for index in range(_V4_MONTH_COLUMNS):
            column = _v4_column_letter(_V4_CF_FIRST_COL + index)
            price = prices.get(f"{column}{price_row}")
            if price is None:
                break
            if sellable:
                # Только офисный гараж продаётся. Его подземные места и места
                # первых этажей имеют разные цены; 0 в новой вводной означает
                # обратную совместимость с общей ценой подземного м/м (B61).
                under_own, over_own = (f"{params}!${cell[0]}${cell[1:]}"
                                       for cell in own_prices)
                under_price = f"IF({under_own}>0,{under_own}*1000,{params}!$B$61)"
                over_price = f"IF({over_own}>0,{over_own}*1000,{params}!$B$61)"
                under_ref = f"{params}!$" + under[0] + "$" + under[1:]
                over_ref = f"{params}!$" + over[0] + "$" + over[1:]
                weighted_price = (
                    f"IF({built}=0,{params}!$B$61,"
                    f"({under_ref}*({under_price})+"
                    f"{over_ref}*({over_price}))/{built})")
                # Убираем и имя листа исходной ставки: подстановка уже содержит
                # полные ссылки и не должна получить «'Вводные'!IF(...)».
                pattern = (
                    rf"(?:{re.escape(params)}!)?\$%s\$%s\b"
                    % (price_cell[0], price_cell[1:]))
                own, swapped = re.subn(pattern, f"({weighted_price})", price)
            else:
                own, swapped = re.subn(
                    r"\$%s\$%s\b" % (price_cell[0], price_cell[1:]), "$B$61", price)
            if not swapped:
                missing.append(f"паркинг объектов: цена {column}{price_row} не опознана")
                break
            month_units[f"{column}{units_row}"] = {
                "formula": (f"IF($B${volume_row}=0,0,$B${units_row}"
                            f"/$B${volume_row}*{column}{volume_row})")}
            month_value[f"{column}{revenue_row}"] = {
                "formula": f"{column}{units_row}*({own})/1000"}
            written += 1
        for target, payload in ((units_row, month_units), (revenue_row, month_value)):
            if not payload:
                continue
            xml, done = _v4_set_cells(xml, target, payload)
            if not done:
                missing.append(f"паркинг объектов: месяцы строки {target} блока {label}")
        if written < 100:
            missing.append(f"паркинг объектов: у блока {label} расписано {written} месяцев")
        # Маркетинг и расходы на продажи считаются от ВСЕЙ выручки объекта:
        # в шаблоне они умножают строку продаж метров, а места продаются
        # своей строкой. Не дописать её значит показать места бесплатными в
        # продаже — на проверочном проекте это 23,1 млн ₽ EBITDA из ниоткуда.
        # Те же деньги обязаны дойти и до эскроу: покрытие эскроу решает
        # ступень ставки ПФ, и выручка, не попавшая на счёт, удешевляет
        # финансирование ровно на свою долю покрытия. Строки 25–27 — приход на
        # эскроу, прямой приход после РВЭ и раскрытие.
        # Раскрытие эскроу (строка 27) в список не входит: оно копит строку
        # прихода, а не считается от продаж, и деньги мест уже внутри неё.
        # Тронуть её значило бы посчитать их дважды, а пожаловаться на
        # «неопознанную формулу» — закричать там, где всё на месте.
        for cost_row in (revenue_row - 8, revenue_row - 7,
                         revenue_row - 4, revenue_row - 3):
            formulas = _v4_row_formulas(xml, cost_row)
            payload: dict[str, dict[str, Any]] = {}
            for index in range(_V4_MONTH_COLUMNS):
                column = _v4_column_letter(_V4_CF_FIRST_COL + index)
                formula = formulas.get(f"{column}{cost_row}")
                if formula is None:
                    break
                if f"{column}{volume_row + 2}" not in formula:
                    missing.append(f"паркинг объектов: {column}{cost_row} не опознана")
                    break
                if f"{column}{revenue_row}" in formula:
                    continue
                payload[f"{column}{cost_row}"] = {
                    "formula": formula.replace(
                        f"{column}{volume_row + 2}",
                        f"({column}{volume_row + 2}+{column}{revenue_row})")}
            if not payload:
                continue
            xml, done = _v4_set_cells(xml, cost_row, payload)
            if not done:
                missing.append(f"паркинг объектов: строка {cost_row}")
        # CAPEX своего подземного — по подземной ставке и теми же множителями
        # инфляции очереди, что и остальной CAPEX объекта.
        capex = _v4_cell_formula(xml, capex_cell)
        if capex is None:
            missing.append(f"паркинг объектов: CAPEX {capex_cell} не найден")
            continue
        sheet = re.search(r"('[^']+')!", capex)
        params_name = sheet.group(1) if sheet else "'Вводные'"
        under_ref = f"{params_name}!${under[0]}${under[1:]}"
        area_ref = f"{params_name}!$K$158"
        rate_ref = f"{params_name}!$B$45"
        # Опознаём формулу по её базе: у офисов это $B$12, у ТЦ — $B$40, то есть
        # строка «Расчётная общая площадь» СВОЕГО блока. Зашитый номер одной из
        # них принял бы чужую формулу за неопознанную.
        own_gba = f"$B${enabled_row + 5}"
        if f"${gba_cell[0]}${gba_cell[1:]}" not in capex and own_gba not in capex:
            missing.append(f"паркинг объектов: формула CAPEX {capex_cell} не опознана")
            continue
        addition = (f'+IF($B${enabled_row}="Да",{under_ref}*{area_ref}*{rate_ref}'
                    f"/1000*{params_name}!$H$6"
                    f"*INDEX({params_name}!$T$88:$T$91,$B${enabled_row + 1})"
                    f"*INDEX({params_name}!$AH$88:$AH$91,$B${enabled_row + 1}),0)")
        xml, done = _v4_set_cell(xml, capex_cell, formula=capex + addition)
        if not done:
            missing.append(f"паркинг объектов: CAPEX {capex_cell}")
    return xml


def _v4_object_parking_allocation(xml: str, missing: list[str]) -> str:
    """Выручка мест доезжает до очередей той же дверью, что и сами объекты.

    Блок аллокации — единственный путь объектов в CF: не расширить его значит
    построить паркинг и не показать его нигде. Правится только строка выручки:
    CAPEX паркинга уже внутри CAPEX объекта, а эскроу и раскрытие считаются от
    выручки строками того же блока.
    """
    added = 0
    counted = (r"IF\(\$B\$(?:%s)=\d+,[A-Z]{1,3}(?:%s),0\)" % (
        "|".join(str(item[1] + 1) for item in _v4_object_parking()),
        "|".join(str(item[3]) for item in _v4_object_parking())))
    for row in range(92, 123):
        found = re.search(r'<x:row r="%d"(?:[ ][^>]*)?>(.*?)</x:row>' % row, xml, re.S)
        if not found:
            continue
        # Строку выручки отбирает сам образец формулы, а не подпись: подписи
        # шаблона лежат общими строками, и `<x:t>` в ячейке нет вовсе — проверка
        # по подписи не срабатывала НИ РАЗУ, а счётчик при этом рапортовал успех.
        def extend(match: "re.Match[str]") -> str:
            formula = html.unescape(match.group(1))
            # Продажи объектов стоят в формуле парами «очередь — ячейка»;
            # места приписываются к своему объекту его же условием очереди.
            for _, enabled_row, _, revenue_row, *_rest in _v4_object_parking():
                queue_cell = f"$B${enabled_row + 1}"
                anchor_row = revenue_row - 9
                target = re.search(
                    r"IF\(%s=(\d+),([A-Z]{1,3})%d,0\)" % (re.escape(queue_cell), anchor_row),
                    formula)
                if not target:
                    return match.group(0)
                queue, column = target.group(1), target.group(2)
                formula = formula.replace(
                    target.group(0),
                    target.group(0) + f",IF({queue_cell}={queue},{column}{revenue_row},0)")
            return "<x:f>" + xml_escape(formula) + "</x:f>"

        before = found.group(1)
        body = re.sub(r"<x:f>(.*?)</x:f>", extend, before, flags=re.S)
        added += sum(1 for _ in re.finditer(counted, body))
        xml = xml[:found.start(1)] + body + xml[found.end(1):]
    if added < 4 * 100:
        missing.append(f"паркинг объектов: аллокация расширена лишь в {added} ячейках")
    return xml


# Строка объекта на листе ТЭП — по строке его объёма продаж: второй список
# «какой объект в какой строке» разошёлся бы с первым молча.
_V4_OBJECT_TEP_ROW = {
    _V4_OBJECT_PRODUCT_CELLS[lay.obj.key][1] - 2: lay.tep_row
    for lay in _V4_OBJECT_LAYOUTS}


def _v4_object_parking_in_tep(xml: str, missing: list[str]) -> str:
    """Выручка мест объекта доезжает до строки ТЭП, а не только до CF.

    Лист CF её уже знает (аллокация по очередям расширена), а строка ТЭП
    считала объект одной продажей здания — и собственная проверка книги
    «ТЭП: выручка = CF» кричала FAIL на верном расчёте: на живом проекте это
    21,5 млрд ₽ из 235,1. Кричащая зря проверка хуже отсутствующей, её
    перестают читать.

    Правится ТОЛЬКО колонка выручки. Площадь, единицы и стартовая цена
    остаются про здание: место продаётся штукой, и метры гаража в
    продаваемой площади объекта не лежат. Чтобы «Выручка» не читалась как
    «продаваемая × цена», у строки стоит своя оговорка в колонке
    комментария — правило о показателе, у которого база не одна.
    """
    for (_label, enabled_row, _spaces_row, revenue_row, *rest) in _v4_object_parking():
        volume_row, sellable = rest[3], rest[8]
        if not sellable:
            # Места ТЦ и ФОКа строятся, стоят денег и выручки не дают
            # (решение владельца, 06.09.2026): складывать нечего.
            continue
        tep_row = _V4_OBJECT_TEP_ROW.get(volume_row)
        if not tep_row:
            missing.append(f"ТЭП: строка объекта для строки объёма {volume_row} не известна")
            continue
        was = _v4_cell_formula(xml, f"G{tep_row}")
        want = f"'ОБЪЕКТЫ'!B{volume_row + 2}+'ОБЪЕКТЫ'!B{revenue_row}"
        if was is None or was.replace(" ", "") not in (
                f"'ОБЪЕКТЫ'!B{volume_row + 2}", want):
            missing.append(f"ТЭП: формула выручки G{tep_row} не опознана")
            continue
        xml, done = _v4_set_cell(xml, f"G{tep_row}", formula=want)
        if not done:
            missing.append(f"ТЭП: выручка паркинга не встала в G{tep_row}")
            continue
        xml, _ = _v4_set_or_insert_cell(
            xml, f"H{tep_row}",
            text="Выручка включает продажу мест в паркинге объекта; "
                 "площадь и цена в строке — про здание")
    return xml


# Строка проверки CAPEX объекта и его ячейки на листе вводных: (строка
# проверки, «объект включён», «очередь объекта»). У ФОКа своей строки в шаблоне
# нет — его CAPEX сверяет «Аллокация CAPEX объектов».
_V4_OBJECT_CAPEX_CHECK = {
    7: (40, "K20", "K21"),
    35: (43, "K40", "K41"),
}


def _v4_extra_object_blocks(xml: str, missing: list[str]) -> str:
    """Блоки дописанных объектов листа ОБЪЕКТЫ и их доля в аллокации по очередям."""
    for lay in _v4_extras():
        xml = _v4_extra_object_block(xml, lay, missing)
    if not _v4_extras():
        return xml
    # Аллокация — единственная дверь, через которую объекты попадают в CF
    # очередей. Не расширить её значит построить объект и не показать его
    # нигде. Формула каждой ячейки кончается слагаемым наземного паркинга —
    # последнего блока шаблона; слагаемые дописанных объектов встают за ним в
    # порядке реестра, каждое своей очередью и строкой своей копии.
    last_head = _V4_TEMPLATE_OBJECT_LAYOUT["above_parking"][1]
    added = 0
    for row in range(92, 123):
        found = re.search(
            r'<x:row r="%d"(?:[ ][^>]*)?>(.*?)</x:row>' % row, xml, re.S)
        if not found:
            continue
        body = found.group(1)
        def extend(match: "re.Match[str]") -> str:
            formula = html.unescape(match.group(1))
            last = re.search(r"IF\(\$B\$%d=(\d+),([A-Z]{1,3})(\d+),0\)\)$"
                             % (last_head + 2), formula)
            if not last:
                return match.group(0)
            queue, column, target = last.group(1), last.group(2), int(last.group(3))
            terms = "".join(
                f",IF($B${lay.object_head + 2}={queue},{column}"
                f"{target - last_head + lay.object_head},0)"
                for lay in _v4_extras())
            return "<x:f>" + xml_escape(formula[:-1] + terms + ")") + "</x:f>"
        new_body, count = re.subn(r"<x:f>(.*?)</x:f>", extend, body, flags=re.S)
        added += count
        xml = xml[:found.start(1)] + new_body + xml[found.end(1):]
    if added < 28 * 100:
        missing.append(f"дописанные объекты: аллокация по очередям расширена лишь в {added} ячейках")
    return xml


def _v4_extra_object_block(xml: str, lay: _V4ObjectLayout, missing: list[str]) -> str:
    name = lay.obj.group_label or lay.obj.label
    head = lay.object_head
    if re.search(r'<x:row r="%d"[ />]' % head, xml):
        missing.append(f"{name}: строка {head} листа ОБЪЕКТЫ занята")
        return xml
    twin_head = head - lay.object_offset
    twin_input = lay.input_head - lay.input_offset
    rows = range(twin_head, twin_head + _V4_OBJECT_BLOCK_ROWS)
    xml, written = _v4_copy_block(
        xml, rows, lay.object_offset,
        input_rows=range(twin_input + 2, twin_input + _V4_INPUT_BLOCK_ROWS),
        input_offset=lay.input_offset)
    if len(written) != len(rows):
        missing.append(f"{name}: блок объекта не скопирован целиком")
        return xml
    # Заголовок стоит во всех ячейках строки — так его пишет шаблон (полоса
    # заливки во всю ширину). Оставить там подпись двойника значило бы завести
    # в книге второй торговый центр, который на самом деле ФОК.
    # Прежде подпись менялась в A–D, а с E по GA оставался «ТОРГОВЫЙ ЦЕНТР»
    # двойника, и объединения строки копия не несла — ревизия 29.09.2026
    # видела его на экране. Подпись ставится во все ячейки, строка
    # объединяется, как заголовки блоков шаблона.
    # Строка переписывается одним проходом: по ячейке через `_v4_set_cell`
    # это 183 чтения всего листа ОБЪЕКТЫ на один заголовок.
    found = re.search(rf'(<x:row r="{head}"[^>]*>)(.*?)(</x:row>)', xml, re.S)
    columns = re.findall(r'<x:c r="([A-Z]+)%d"' % head, found.group(2)) if found else []
    if "A" not in columns:
        missing.append(f"{name}: заголовок блока объекта")
        return xml
    text = xml_escape(name.upper())

    def titled(cell: "re.Match[str]") -> str:
        attrs = re.sub(r'\st="[^"]*"', "", cell.group(2))
        return (f'<x:c r="{cell.group(1)}{head}"{attrs} t="inlineStr">'
                f"<x:is><x:t>{text}</x:t></x:is></x:c>")

    body = re.sub(rf'<x:c r="([A-Z]+){head}"([^>]*?)(?:/>|>.*?</x:c>)', titled,
                  found.group(2), flags=re.S)
    xml = xml[:found.start()] + found.group(1) + body + found.group(3) + xml[found.end():]
    return _v4_add_merge(xml, f"A{head}:{columns[-1]}{head}")


def _v4_add_merge(xml: str, ref: str) -> str:
    """Добавляет объединение в `mergeCells` листа и правит счётчик."""
    found = re.search(r'<x:mergeCells(?:\s[^>]*)?>(.*?)</x:mergeCells>', xml, re.S)
    if not found:
        return xml
    if f'ref="{ref}"' in found.group(1):
        return xml
    body = found.group(1) + f'<x:mergeCell ref="{ref}" />'
    count = len(re.findall(r"<x:mergeCell ", body))
    return (xml[:found.start()] + f'<x:mergeCells count="{count}">' + body
            + "</x:mergeCells>" + xml[found.end():])


def _v4_object_tep_cells(lay: _V4ObjectLayout) -> dict[str, str]:
    """Формулы строки дописанного объекта на листе ТЭП — по ячейкам его блока.

    Колонки те же, что у строки двойника: C — GBA, D — продаваемая площадь
    (у мест — пусто), E — единицы (у метров — пусто), F — стартовая цена с
    множителями очереди, G — выручка блока ОБЪЕКТЫ. Цена места хранится в
    миллионах, а колонка — в тысячах: отсюда ×1000 только у мест.
    """
    params = "'Вводные'!"
    ref = lambda name: f"{params}$K${_v4_input_row(lay, name)}"
    queue = ref("queue")
    per_unit = "*1000" if lay.obj.measure == "spaces" else ""
    cells = {"C": ref("gba"), "D": "", "E": ""}
    if lay.obj.measure == "spaces":
        cells["E"] = f"{params}$K${lay.input_head + 7}"
    else:
        cells["D"] = ref("saleable")
    cells["F"] = (f"{ref('price')}{per_unit}*{params}$H$5"
                  f"*INDEX({params}$S$88:$S$91,{queue})"
                  f"*INDEX({params}$AG$88:$AG$91,{queue})")
    cells["G"] = f"'ОБЪЕКТЫ'!B{_V4_OBJECT_PRODUCT_CELLS[lay.twin][1] + lay.object_offset}"
    return cells


def _v4_dashboard_extra_products() -> tuple[tuple[str, ...], ...]:
    """Строки дописанных объектов для дашборда — ячейками их строки ТЭП.

    Та же форма, что у продуктов шаблона в `v4_dashboard.PRODUCT_ITEMS`:
    ключ, подпись, ГНС наземная, подземная, продаваемая, единицы, выручка,
    стартовая цена, темп, чем ценится, в чём считается. Подземная — гараж объекта из его
    строки структуры продукта ОТЧЁТа; объект без своей строки сидит в строке
    двойника, и его гараж уже там — второй раз его не пишем.
    Колонки строки ТЭП объявлены одним местом (`_v4_object_tep_cells`), и
    читается строка, а не блок объекта: переданный городу ФОК несёт нули
    продаваемой и выручки уже там.
    """
    out = []
    for lay in _v4_extras():
        tep = _v4_object_tep_cells(lay)
        cell = lambda letter: f"'ТЭП'!{letter}{lay.tep_row}" if tep.get(letter) else ""  # noqa: E731
        # У мест метров ГНС на дашборде нет, как у наземного паркинга шаблона:
        # выручка на штуку, а не на метр.
        gns = cell("C") if lay.obj.measure != "spaces" else ""
        under = (f"'ОТЧЕТ'!G{lay.report_row}"
                 if lay.report_row and lay.obj.garage else "")
        # Чем объект ценится и в чём считаются его штуки — как у двойника:
        # второй офисник меряет места гаража машино-местами, как первый.
        twin = next(item for item in v4_dashboard.PRODUCT_ITEMS if item[0] == lay.twin)
        out.append((lay.obj.key, lay.obj.group_label or lay.obj.label, gns, under, cell("D"),
                    cell("E"), cell("G"), cell("F"), "", twin[-2], twin[-1]))
    return tuple(out)


def _v4_extra_tep_rows(xml: str, missing: list[str]) -> str:
    """Строки дописанных объектов в блоке отдельно стоящих объектов листа ТЭП.

    Строк в блоке шаблона ровно три, а итог стоит четвёртой. Вставлять строку
    нельзя — поедут ссылки, — поэтому итог переезжает на пустую строку 35 (она
    есть в шаблоне и ничем не занята), а его прежнее место занимает первый
    дописанный объект (ФОК). Ссылок на строки 31–35 листа ТЭП нет ни на одном
    другом листе — проверено по всей книге, — и единственный читатель итога,
    «ИТОГО ПРОЕКТ», правится здесь же. Следующим объектам места над итогом
    нет: ниже стоят «ИТОГО ПРОЕКТ» и соцобъекты, на которые ссылаются другие
    листы. Они встают под соцобъектами своим разделом, и итог объектов
    складывает оба куска — это сказано в строке раздела.
    """
    below = [lay for lay in _v4_extras() if lay.tep_row > 36]
    # Итог переезжает с 34 на 35 — и его стиль вместе с ним (см. `_v4_restyle_row`).
    total_styles = _v4_sheet_row_styles(xml, 34)
    plain_styles = _v4_sheet_row_styles(xml, 33)
    for letter in ("C", "D", "E", "G"):
        parts = [f"{letter}31:{letter}34"]
        if below:
            parts.append(f"{letter}{below[0].tep_row}:{letter}{below[-1].tep_row}")
        xml, done = _v4_set_cell(xml, f"{letter}35", formula=f"SUM({','.join(parts)})")
        if not done:
            missing.append(f"ТЭП · итог объектов {letter}35")
    # Кладовые лежат на подземном этаже гаража: своей наземной ГНС у них нет,
    # а подземная уже посчитана строкой паркинга. Прежде этих формул не было
    # ВОВСЕ, и пустая клетка рвала кэш итога колонки: «Итого очередь», «ИТОГО
    # ЖИЛЫЕ ОЧЕРЕДИ» и «ИТОГО ПРОЕКТ» приходили пустыми в любой просмотрщик,
    # который не пересчитывает книгу.
    for storage_row in (7, 13, 19, 25):
        for letter in ("C", "D"):
            xml, done = _v4_set_or_insert_cell(xml, f"{letter}{storage_row}", formula="0")
            if not done:
                missing.append(f"ТЭП · кладовые {letter}{storage_row}")
    for coord, text in (("A35", "ИТОГО ОБЪЕКТЫ"), ("B35", "")):
        xml, done = _v4_set_or_insert_cell(xml, coord, text=text)
        if not done:
            missing.append(f"ТЭП · подпись {coord}")
    for letter in ("C", "D", "E", "G"):
        xml, done = _v4_set_cell(xml, f"{letter}36", formula=f"SUM({letter}28,{letter}35)")
        if not done:
            missing.append(f"ТЭП · итог проекта {letter}36")
    # Подземные гаражи объектов строятся и стоят денег, а в метрах их не было
    # нигде: строки объектов несут наземную ГБА, и «строительный объём» без
    # них не равен объёму движка. Добавляются здесь же, где собирается итог.
    garages = "+".join(
        f"IF('Вводные'!$K${_v4_input_row(lay, 'enabled')}=\"Да\","
        f"'Вводные'!${lay.parking_under[0]}${lay.parking_under[1:]},0)"
        for lay in sorted((lay for lay in _v4_layouts() if lay.parking_under),
                          key=lambda lay: lay.input_head))
    xml, done = _v4_set_cell(
        xml, "C36",
        formula=f"SUM(C28,C35,F40:F43)+'Вводные'!$K$158*({garages})")
    if not done:
        missing.append(f"ТЭП · гаражи объектов в {TOTAL_AREA.prepositional}")
    xml, _ = _v4_set_or_insert_cell(
        xml, "H36",
        text="Включая соцобъекты и подземные гаражи отдельно стоящих объектов")
    # Прежний итог становится строкой первого дописанного объекта, следующие
    # встают под соцобъектами. Продаваемая площадь и выручка берутся из блока
    # объекта; у переданного городу обе равны нулю сами — гейт стоит в
    # формуле продаваемой площади «Вводных», а не здесь.
    if below:
        head = below[0].tep_row - 1
        for coord, text in ((f"A{head}", "ОТДЕЛЬНО СТОЯЩИЕ ОБЪЕКТЫ · ПРОДОЛЖЕНИЕ"),
                            (f"H{head}", "Входят в «ИТОГО ОБЪЕКТЫ» (строка 35) и "
                                         "«ИТОГО ПРОЕКТ» выше")):
            xml = _v4_ensure_row(xml, head)
            xml, done = _v4_set_or_insert_cell(xml, coord, text=text)
            if not done:
                missing.append(f"ТЭП · раздел дописанных объектов {coord}")
    for lay in _v4_extras():
        row = lay.tep_row
        xml = _v4_ensure_row(xml, row)
        note = ("Передан городу — строится, но не продаётся" if lay.disposition_row
                else "Отдельно стоящий объект")
        items = [(f"A{row}", "text", "Проект"),
                 (f"B{row}", "text", lay.obj.tep_label or lay.obj.label)]
        for letter, formula in _v4_object_tep_cells(lay).items():
            items.append((f"{letter}{row}", "formula" if formula else "text", formula))
        items.append((f"H{row}", "text", note))
        for coord, kind, value in items:
            if kind == "text":
                xml, done = _v4_set_or_insert_cell(xml, coord, text=value)
            else:
                xml, done = _v4_set_or_insert_cell(xml, coord, formula=value)
            if not done:
                missing.append(f"ТЭП · строка {lay.obj.label} {coord}")
    xml = _v4_restyle_row(xml, 34, plain_styles, whole_row=True)
    xml = _v4_restyle_row(xml, 35, total_styles, whole_row=True)
    # Блок соцобъектов в шаблоне стоит без оформления: заголовок раздела,
    # шапка и итог получают стили своих ролей с этого же листа.
    section = _v4_sheet_row_styles(xml, 30).get("A", "")
    header = _v4_sheet_row_styles(xml, 3)
    xml = _v4_restyle_row(xml, 38, {"A": section})
    xml = _v4_restyle_row(xml, 39, {c: header.get("A", "") for c in "ABCDEF"})
    xml = _v4_restyle_row(xml, 44, {"A": total_styles.get("A", ""),
                                    "E": total_styles.get("G", "")})
    return xml


# Блок «СТРУКТУРА ПРОДУКТА» листа ОТЧЁТ: (строка, подпись, ячейка наземной
# площади, ячейка продаваемой, строка выручки объекта на листе ОБЪЕКТЫ, строка
# продаваемых мест его гаража, строка выручки гаража, ячейка мест гаража под
# землёй, продаются ли места). Пусто — величины у этого объекта нет.
_V4_PRODUCT_STRUCTURE_OBJECTS = (
    (50, "МФОЦ / офисный центр", "K25", "K26", 24, 32, 33, "K161", True),
    (51, "Торговый центр / ОСЗ", "K45", "K46", 52, 60, 61, "K163", False),
    (52, "Наземный паркинг", "K66", "", 80, 0, 0, "", False),
)


def _v4_extra_product_structure(lay: _V4ObjectLayout) -> tuple:
    """Строка структуры продукта дописанного объекта — строка двойника со сдвигом."""
    twin = next(item for item in _V4_PRODUCT_STRUCTURE_OBJECTS
                if item[0] == _V4_TEMPLATE_OBJECT_LAYOUT[lay.twin][9])
    shift_rows = lambda row: row + lay.object_offset if row else 0
    return (lay.report_row, lay.obj.group_label or lay.obj.label,
            _v4_row_shift(twin[2], lay.input_offset),
            _v4_row_shift(twin[3], lay.input_offset),
            shift_rows(twin[4]), shift_rows(twin[5]) if lay.parking_under else 0,
            shift_rows(twin[6]) if lay.parking_under else 0,
            lay.parking_under, lay.obj.garage_sellable)


# Дописанный объект со своей строкой (ФОК — продукт другого рода) встаёт ею;
# второй офисник или второй ТЦ — тот же продукт, что у двойника, и их числа
# складываются в строку двойника: блок называется «структура продукта», и
# два офисных центра в нём — один продукт.
_V4_PRODUCT_STRUCTURE_OBJECTS = _V4_PRODUCT_STRUCTURE_OBJECTS + tuple(
    _v4_extra_product_structure(lay) for lay in _V4_EXTRA_OBJECT_LAYOUTS if lay.report_row)
_V4_PRODUCT_STRUCTURE_JOINED = {
    _V4_TEMPLATE_OBJECT_LAYOUT[lay.twin][9]: tuple(
        _v4_extra_product_structure(other) for other in _V4_EXTRA_OBJECT_LAYOUTS
        if not other.report_row and other.twin == lay.twin)
    for lay in _V4_EXTRA_OBJECT_LAYOUTS if not lay.report_row}
_V4_PRODUCT_STRUCTURE_TOTAL_ROW = 54


def _v4_object_parking() -> tuple:
    """Карта гаражей объектов — только объектов этой книги."""
    return tuple(item for item in _V4_OBJECT_PARKING if _v4_label_in_book(item[0]))


def _v4_object_product_cells() -> dict[str, tuple[int, int]]:
    """Очередь и выручка объектов — только объектов этой книги."""
    return {key: cells for key, cells in _V4_OBJECT_PRODUCT_CELLS.items() if _v4_in_book(key)}


_V4_PRODUCT_STRUCTURE_FIRST_ROW = 46
_V4_UNDER_COLUMN = "G"


def _v4_product_structure_block(xml: str, missing: list[str]) -> str:
    """Блок «СТРУКТУРА ПРОДУКТА»: наземное и подземное — разными колонками.

    «В книге в сумму ГНС считается площадь подземного паркинга, на движке это
    правил, а тут нет» (владелец, 14.09.2026). Итог блока складывал под шапкой
    «ГНС, м²» наземные метры квартир и подземные метры паркинга — 475 870,
    число, не равное ни наземной ГНС проекта (443 701), ни строительному
    объёму (601 621). В движке это разведено с 04.09: три величины и три поля.

    Здесь же чинятся три соседние потери того же корня. **ФОК не имел строки
    вовсе** — список продуктов стоял перечислением, и четвёртый объект в него
    не вошёл; итог переезжает на свободную строку 54, а его прежнее место
    занимает ФОК (тот же приём, что на листе ТЭП). **Гараж объекта не входил
    ни в выручку блока, ни в его единицы**: выручка 213 605,2 против 235 123,1
    у движка и 2 160 мест вместо 4 660 — правку 0.23.69 этот блок не увидел,
    потому что читает объект своей ссылкой мимо ТЭП и КОНСОЛИДАТОРа.
    **У кладовых не было формул вовсе**: пустая клетка читается как «не
    посчитали», а своей наземной площади у них и нет — она внутри подземной.

    Соцобъекты в блок не идут: они не продукт, их метры видны на листе ТЭП.
    Итог поэтому зовётся «ИТОГО ПРОДУКТЫ», а не «ИТОГО ПРОЕКТ»: имя, которое
    обещает весь проект, обязано его и складывать.
    """
    under = _V4_UNDER_COLUMN
    first = _V4_PRODUCT_STRUCTURE_FIRST_ROW
    total = _V4_PRODUCT_STRUCTURE_TOTAL_ROW
    param = "'Параметры модели'!"

    def put(coord: str, *, formula: str = "", text: str | None = None) -> None:
        if text is not None:
            _xml, done = _v4_set_or_insert_cell(xml_holder[0], coord, text=text)
        else:
            _xml, done = _v4_set_or_insert_cell(xml_holder[0], coord, formula=formula)
        xml_holder[0] = _xml
        if not done:
            missing.append(f"ОТЧЁТ · структура продукта: ячейка {coord} не поставлена")

    # Стиль итога шаблона стоит на строке, которую займёт ФОК: он переезжает
    # на строку итога вместе с ним, а ФОК получает стиль обычной строки.
    total_styles = _v4_sheet_row_styles(xml, total - 1)
    plain_styles = _v4_sheet_row_styles(xml, total - 2)
    xml_holder = [_v4_ensure_row(xml, total)]
    # Шапка: колонка называет то, что в ней лежит.
    put("B45", text="ГНС наземная, м²")
    put(f"{under}45", text="Подземная, м²")

    # Числа квартир здесь НЕТ намеренно. Колонка D этого блока означает
    # продаваемые МЕСТА (машино-места паркинга и гаража офисника) — её итог
    # сверяется с движком именно так. Квартиры в ту же колонку сложились бы с
    # местами, и «Единицы» блока перестали бы отвечать на какой-либо вопрос.
    # Квартиры считаются в блоке очередей и читаются оттуда напрямую.
    # Площадные продукты очередей: наземное в B, подземное в G.
    put("B48", formula="0")
    put(f"{under}48", formula=f"SUM({param}K88:K91)")
    # У кладовых своей наземной площади нет: ноль здесь — ответ, а пустая
    # клетка была отсутствием формулы. Подземную кладовых пишет
    # `_v4_storage_area_cells` — она же пишет её на ТЭП, и второй ответ на
    # «сколько метров у кладовых» здесь разошёлся бы с первым молча.
    put("B49", formula="0")
    put("C49", formula="0")
    for row in (46, 47):
        put(f"{under}{row}", formula="0")

    garages = []
    for item in _V4_PRODUCT_STRUCTURE_OBJECTS:
        if not _v4_label_in_book(item[1]):
            continue
        row, label = item[0], item[1]
        members = (item,) + tuple(m for m in _V4_PRODUCT_STRUCTURE_JOINED.get(row, ())
                                  if _v4_label_in_book(m[1]))
        cell = lambda coord: f"{param}${coord[0]}${coord[1:]}"
        joined = lambda parts: "+".join(parts) if parts else "0"
        put(f"A{row}", text=label)
        put(f"B{row}", formula=joined([cell(m[2]) for m in members]))
        saleable = [cell(m[3]) for m in members if m[3]]
        if saleable:
            put(f"C{row}", formula=joined(saleable))
        revenue = []
        for m in members:
            revenue.append(f"'ОБЪЕКТЫ'!B{m[4]}")
            if m[6]:
                revenue.append(f"'ОБЪЕКТЫ'!B{m[6]}")
        put(f"E{row}", formula="+".join(revenue))
        put(f"F{row}", text="Отдельный объект")
        areas = [f"{cell(m[7])}*{param}$K$158" for m in members if m[7]]
        put(f"{under}{row}", formula=joined(areas))
        garages.extend(areas)
        # Места гаража продаются только у офисника — у ТЦ и ФОКа это
        # обеспеченность посетителей, и «единиц к продаже» у них нет. Ноль
        # ставится явно: на строке ФОКа прежде стоял итог блока, и не стерев
        # его, мы оставили бы сумму блока в графе «Единицы» одного объекта.
        put(f"D{row}", formula=joined([f"'ОБЪЕКТЫ'!B{m[5]}" for m in members
                                       if m[8] and m[5]]))
        if not saleable:
            put(f"C{row}", formula="0")

    put(f"A{total}", text="ИТОГО ПРОДУКТЫ")
    for column in ("B", "C", "D", "E", under):
        put(f"{column}{total}", formula=f"SUM({column}{first}:{column}{total - 1})")
    put(f"H{total}", text=(f"{TOTAL_AREA.name} = наземная + подземная. "
                           "Соцобъекты сюда не входят — они не продукт; "
                           "их метры на листе ТЭП."))
    xml_holder[0] = _v4_restyle_row(xml_holder[0], total - 1, plain_styles, whole_row=True)
    xml_holder[0] = _v4_restyle_row(xml_holder[0], total, total_styles, whole_row=True)
    return xml_holder[0]


def _v4_report_unit_tables_style(xml: str) -> str:
    """Юнит-экономика и темпы продаж ОТЧЕТА: данные — стилем данных.

    В шаблоне подписи строк 76–83 и 87–93 (и единицы E87:E93) залиты тёмным
    цветом ЗАГОЛОВКА раздела, а шапки 75 и 86 — тем же цветом, а не цветом
    шапок таблиц листа. Таблица читалась сплошной тёмной полосой (ревизия
    29.09.2026). Стили берутся у соседних таблиц этого же листа: подпись —
    у «Продаваемая площадь» (A57), единица — у G57, шапка — у строки 56.
    """
    label = _v4_sheet_row_styles(xml, 57)
    header = _v4_sheet_row_styles(xml, 56)
    head = header.get("B", "")
    for row in (75, 86):
        xml = _v4_restyle_row(xml, row, {c: head for c in "ABCDE"})
    for row in list(range(76, 84)) + list(range(87, 94)):
        xml = _v4_restyle_row(xml, row, {"A": label.get("A", ""), "E": label.get("G", "")})
    # «Итого» доли структуры расходов — в процентах, как строки над ним
    # (стоял формат суммы: «1,0» вместо «100,0%»); шапка «Подземная, м²» —
    # стилем шапки своей таблицы.
    shares = _v4_sheet_row_styles(xml, 39).get("C")
    if shares:
        xml = _v4_restyle_row(xml, 40, {"C": shares.replace('"', '"')})
    product_header = _v4_sheet_row_styles(xml, 45).get("F")
    if product_header:
        xml = _v4_restyle_row(xml, 45, {"G": product_header})
    return xml


_V4_FINAL_DEBT_ROW = 23
_V4_FINAL_DEBT_LABEL = "Финальный долг"
_V4_DEBT_DEFAULT_STATUS = "ДЕФОЛТ ПО ДОЛГУ"


def _v4_name_debt_default_status(xml: str, missing: list[str]) -> str:
    """Вердикт ПРОВЕРОК отличает дефолт по долгу от сбоя расчёта.

    Решение владельца 29.09.2026: непогашенный к концу долг — это ответ модели
    о проекте, а не поломка модели. Прежде единственный FAIL «Финальный долг»
    давал «СБОЙ», и все три проверенных проекта читались сломанными. Теперь:
    FAIL в любой другой строке — «СБОЙ»; FAIL только в строке финального долга
    — «ДЕФОЛТ ПО ДОЛГУ». Строка берётся по подписи, а не по номеру наугад.
    """
    label = _v4_cell_text(xml, f"A{_V4_FINAL_DEBT_ROW}")
    if label != _V4_FINAL_DEBT_LABEL:
        missing.append(f"ПРОВЕРКИ · строка {_V4_FINAL_DEBT_ROW} не «{_V4_FINAL_DEBT_LABEL}», "
                       f"а {label!r}: статус дефолта не назван")
        return xml
    current = _v4_cell_formula(xml, "B3") or ""
    found = re.search(r"COUNTIF\(F6:F(\d+),", current)
    if not found:
        missing.append("ПРОВЕРКИ · вердикт B3 не распознан: статус дефолта не назван")
        return xml
    last = found.group(1)
    debt = f"F{_V4_FINAL_DEBT_ROW}"
    formula = (f'IF(COUNTIF(F6:F{last},"FAIL")-COUNTIF({debt},"FAIL")>0,"СБОЙ",'
               f'IF(COUNTIF({debt},"FAIL")>0,"{_V4_DEBT_DEFAULT_STATUS}",'
               f'IF(COUNTIF(F6:F{last},"WARN")>0,"ПРОЙДЕНО С ПРЕДУПРЕЖДЕНИЯМИ","ПРОЙДЕНО")))')
    xml, done = _v4_set_cell(xml, "B3", formula=formula)
    if not done:
        missing.append("ПРОВЕРКИ · вердикт B3 не записан")
        return xml
    # Подсветка вердикта: дефолт красится как сбой — оба красные, но названы по-разному.
    rule = re.search(r'<x:cfRule type="expression" dxfId="(\d+)" priority="\d+">'
                     r'<x:formula>\$B\$3="СБОЙ"</x:formula></x:cfRule>', xml)
    if rule:
        priorities = [int(p) for p in re.findall(r'priority="(\d+)"', xml)]
        added = (f'<x:cfRule type="expression" dxfId="{rule.group(1)}" '
                 f'priority="{max(priorities) + 1}"><x:formula>$B$3="{_V4_DEBT_DEFAULT_STATUS}"'
                 f'</x:formula></x:cfRule>')
        xml = xml[:rule.end()] + added + xml[rule.end():]
    return xml


# Подписи удельных показателей ОТЧЕТА — по их фактическому делителю (решение
# владельца 29.09.2026: база следует показателю и называется в подписи).
# (ячейка, прежняя подпись шаблона, новая подпись). Прежняя сверяется: если
# шаблон поменялся, подпись не переписывается вслепую.
_V4_REPORT_AREA_LABELS = (
    ("A58", "Общая площадь (GBA)", "GBA продуктов: наземная + подземная очередей"),
    ("H58", "Жилые очереди и отдельно стоящие объекты",
     "Жилые очереди с подземной частью и наземная GBA отдельных объектов; "
     "без соцобъектов и гаражей объектов"),
    ("A62", "CAPEX на м² GBA", "CAPEX на м² GBA продуктов"),
    ("H62", "CAPEX очереди / общая площадь", "CAPEX очереди / «GBA продуктов» (строка 58)"),
    ("F9", "CAPEX на м² GBA", "CAPEX на м² GBA продуктов"),
    ("C75", "на м² GBA, тыс. ₽", "на м² GBA с подземной и соцобъектами, тыс. ₽"),
)


def _v4_report_area_labels(xml: str, missing: list[str]) -> str:
    """ОТЧЕТ делил «на м² GBA» на две разные площади под одной подписью.

    `F62`/`G9` — на GBA продуктов (строка 58), `C76:C83` — на строительный
    объём ТЭП!C36 (с соцобъектами и гаражами объектов): рядом стояли две
    «CAPEX на м² GBA» — 190 и 185 на дефолтном проекте. Делители не меняются,
    меняются подписи: каждая называет то, на что делит.
    """
    for coord, old, new in _V4_REPORT_AREA_LABELS:
        current = _v4_cell_text(xml, coord)
        if current == new:
            continue
        if current != old:
            missing.append(f"ОТЧЕТ · подпись {coord}: ждали «{old}», в шаблоне {current!r}")
            continue
        xml, done = _v4_set_or_insert_cell(xml, coord, text=new)
        if not done:
            missing.append(f"ОТЧЕТ · подпись {coord} не записана")
    return xml


def _v4_family_present(inputs: dict[str, Any], key: str) -> bool:
    """Есть ли в проекте объект этого вида — сам или любой его экземпляр."""
    return any(b(inputs, o.enabled_key) for o in STANDALONE_OBJECTS
               if o.key == key or o.family == key)


def _v4_storage_present(tep: dict[str, dict[str, Any]]) -> bool:
    return float((tep.get("storage") or {}).get("units") or 0) > 0


def _v4_absent_products(inputs: dict[str, Any], tep: dict[str, dict[str, Any]]) -> frozenset[str]:
    """Продукты шаблона, которых нет в проекте, — их строки Дашборд не показывает."""
    absent = {key for key in _V4_TEMPLATE_OBJECT_LAYOUT
              if not _v4_family_present(inputs, key)}
    if not _v4_storage_present(tep):
        absent.add("storage")
    return frozenset(absent)


# Строки листов, которые скрываются, когда объекта нет в проекте. Подпись —
# часть адреса: оформление сверяет её и не скрывает строку, если стоит другая.
_V4_ABSENT_OBJECT_ROWS: dict[str, tuple[tuple[str, int, str, str], ...]] = {
    "offices": (("ОТЧЕТ", 50, "A", "МФОЦ"), ("ОТЧЕТ", 91, "A", "МФОЦ"),
                ("ТЭП", 31, "B", "МФОЦ")),
    "standalone_retail": (("ОТЧЕТ", 51, "A", "Торговый центр"), ("ОТЧЕТ", 92, "A", "Торговый центр"),
                          ("ТЭП", 32, "B", "Торговый центр")),
    "above_parking": (("ОТЧЕТ", 52, "A", "Наземный паркинг"), ("ОТЧЕТ", 93, "A", "Наземный паркинг"),
                      ("ТЭП", 33, "B", "Наземный")),
    "sports": (("ОТЧЕТ", 53, "A", "ФОК"), ("ТЭП", 34, "B", "ФОК")),
}
_V4_OBJECT_BLOCK_SPAN = 28          # заголовок блока ОБЪЕКТЫ … «Паркинг объекта — выручка»
_V4_OBJECT_QUEUE_FIRST = 92         # ОБЪЕКТЫ: «Очередь 1 — Выручка объектов»
_V4_OBJECT_QUEUE_STRIDE = 8
_V4_OBJECT_QUEUE_ROWS = 7
_V4_TEP_QUEUE_PRODUCTS = ("Квартиры", "Коммерция 1 этажа", "Подземный паркинг", "Кладовые")
_V4_QUEUE_BLOCKS = {                # лист: (заголовок первой очереди, шаг блока)
    "Продажи": (6, _V4_SALES_PHASE_STRIDE),
    "CAPEX": (6, _V4_CAPEX_BLOCK_STRIDE),
    "ВРИ": (6, _V4_VRI_BLOCK_STRIDE),
}


def _v4_hidden_plan(inputs: dict[str, Any], tep: dict[str, dict[str, Any]], queues: int,
                    entry_xml: str) -> tuple[dict[str, list[tuple[int, str, str]]], set[str]]:
    """Что скрыть в книге: объекты и очереди, которых нет в проекте.

    Решение владельца 29.09.2026. Скрывается, а не удаляется: формулы на эти
    строки ссылаются, и включённый потом прямо в Excel объект вернётся, стоит
    показать строки. Вводные объектов не скрываются — в них сам выключатель.
    """
    rows: dict[str, list[tuple[int, str, str]]] = {}

    def hide(sheet: str, row: int, column: str = "A", label: str = "") -> None:
        rows.setdefault(sheet, []).append((row, column, label))

    for key, places in _V4_ABSENT_OBJECT_ROWS.items():
        present = (b(inputs, "sports_enabled") if key == "sports"
                   else _v4_family_present(inputs, key))
        if not present:
            for sheet, row, column, label in places:
                hide(sheet, row, column, label)
    for lay in _v4_layouts():
        if b(inputs, lay.obj.enabled_key):
            continue
        name = (lay.obj.group_label or lay.obj.label).upper() if lay.extra else ""
        head = lay.object_head
        hide("ОБЪЕКТЫ", head, "A", name)
        for row in range(head + 1, head + _V4_OBJECT_BLOCK_SPAN):
            hide("ОБЪЕКТЫ", row)
        if lay.extra and lay.tep_row > 36:
            hide("ТЭП", lay.tep_row, "B", lay.obj.tep_label or lay.obj.label)
    if not _v4_storage_present(tep):
        hide("ОТЧЕТ", 49, "A", "Кладовые")
        hide("ОТЧЕТ", 90, "A", "Кладовые")
    for q in range(queues + 1, 5):
        hide("ОТЧЕТ", 24 + q)
        tep_head = 4 + _V4_TEP_PHASE_STRIDE * (q - 1)
        for index, product in enumerate(_V4_TEP_QUEUE_PRODUCTS):
            hide("ТЭП", tep_head + index, "B", product)
        hide("ТЭП", tep_head + len(_V4_TEP_QUEUE_PRODUCTS), "A", f"Итого очередь {q}")
        for sheet, (first, stride) in _V4_QUEUE_BLOCKS.items():
            head = first + stride * (q - 1)
            hide(sheet, head, "A", f"ОЧЕРЕДЬ {q}")
            for row in range(head + 1, head + stride):
                hide(sheet, row)
        start = _V4_OBJECT_QUEUE_FIRST + _V4_OBJECT_QUEUE_STRIDE * (q - 1)
        for row in range(start, start + _V4_OBJECT_QUEUE_ROWS):
            hide("ОБЪЕКТЫ", row, "A", f"Очередь {q} —")
        for found in re.finditer(r'<x:row r="(\d+)"[^>]*>(.*?)</x:row>', entry_xml or "", re.S):
            text = _v4_cell_text(found.group(0), f"A{found.group(1)}") or ""
            if re.fullmatch(rf"(ДОО|СОШ|Поликлиника) — очередь {q}", text):
                hide("Вводные", int(found.group(1)), "A", text)
    if _v4_storage_present(tep):
        pass
    else:
        for q in range(1, queues + 1):
            hide("ТЭП", 4 + _V4_TEP_PHASE_STRIDE * (q - 1) + 3, "B", "Кладовые")
    return rows, {f"CF_{q}" for q in range(queues + 1, 5)}


def _v4_object_checks(xml: str, missing: list[str]) -> str:
    """Учит лист ПРОВЕРКИ знать о дописанных объектах.

    Проверка, не знающая о новой строке, кричит «FAIL» на верном расчёте — и
    её перестают читать. Это уже было с проверкой лимита при переносе долга.

    Строки берутся из `_V4_OBJECT_PRODUCT_CELLS`, а не выписываются: объект,
    заведённый завтра, попадает сюда тем, что он появился, — иначе пятый
    объект снова дал бы FAIL на верном расчёте.
    """
    template = _V4_TEMPLATE_OBJECT_REVENUE_ROWS
    added = tuple(row for _, row in _v4_object_product_cells().values()
                  if row not in template)
    if not added:
        return xml

    def objects(rows: tuple[int, ...], shift: int = 0) -> str:
        return ",".join(f"'ОБЪЕКТЫ'!B{row + shift}" for row in rows)

    sales = "'Продажи'!B26,'Продажи'!B49,'Продажи'!B72,'Продажи'!B95"
    whole = template + added
    # Гараж объекта — отдельный продукт (`NON_TEP_PRODUCT_LABELS`), и своей
    # строки в ТЭП у него нет: его выручка стоит СВОЕЙ строкой у каждого
    # объекта. В аллокацию и в CF она входит, а в суммы выручки продуктов и
    # объектов не входила вовсе — и обе проверки кричали FAIL на верном
    # расчёте ровно на её величину. CAPEX гаража этого не требует: он уже
    # внутри CAPEX объекта (`_v4_object_parking_block`).
    # Строку 49 («ТЭП: выручка = CF») здесь НЕ трогаем: выручку гаража кладёт в
    # САМУ строку ТЭП `_v4_object_parking_in_tep`, и прибавка к `'ТЭП'!G36`
    # была бы вторым счётом той же величины — на проверочном проекте это
    # 630,93 млн ₽, ровно выручка мест офисника.
    garage = tuple(row for _, _, _, row, *_rest in _v4_object_parking())
    with_garage = ",".join(f"'ОБЪЕКТЫ'!B{row}" for row in garage)
    swaps = (
        (f"SUM({sales},{objects(template)})",
         f"SUM({sales},{objects(whole)},{with_garage})"),
        (f"SUM({objects(template)})", f"SUM({objects(whole)},{with_garage})"),
        (f"SUM({objects(template, _V4_OBJECT_CHECKS_CAPEX_SHIFT)})",
         f"SUM({objects(whole, _V4_OBJECT_CHECKS_CAPEX_SHIFT)})"),
    )
    for old, new in swaps:
        encoded = xml_escape(old)
        if encoded not in xml:
            missing.append("ПРОВЕРКИ: формула не опознана — " + old[:48])
            continue
        xml = xml.replace(encoded, xml_escape(new))
    return xml


def _v4_object_parking_in_checks(xml: str, missing: list[str]) -> str:
    """Учит проверки объекта тому, что у него есть гараж.

    Гараж заведён 06.09.2026, а две проверки на объект остались прежними и с
    тех пор кричат «FAIL» на верном расчёте: «реализованный объём» сравнивает
    проданное с СЫРОЙ вводной продаваемой, хотя метры первых этажей из неё
    вычтены (тот же этаж нельзя продать дважды), а «CAPEX» сравнивает
    фактический расход с «GBA × ставка» без подземного гаража. Кричащая зря
    проверка хуже отсутствующей — её перестают читать.

    Формулы не сочиняются: множители снимаются с самой формулы шаблона, а имя
    листа вводных берётся из неё же — он переименован, и зашитое имя однажды
    перестанет совпадать.
    """
    for (label, enabled_row, _units, _revenue, _capex_cell, under, over,
         *_rest) in _v4_object_parking():
        rows = _V4_OBJECT_CHECK_ROWS.get(enabled_row)
        if rows is None:
            continue                      # своих проверок у объекта нет
        volume_row, capex_row = rows
        for row, kind in ((volume_row, "объём"), (capex_row, "CAPEX")):
            formula = _v4_cell_formula(xml, f"C{row}")
            if formula is None or not formula.endswith(",0)"):
                missing.append(f"ПРОВЕРКИ: C{row} ({label}, {kind}) не опознана")
                continue
            sheet = re.search(r"('[^']+')!", formula)
            if sheet is None:
                missing.append(f"ПРОВЕРКИ: C{row} ({label}) без листа вводных")
                continue
            params = sheet.group(1)
            per_space = f"{params}!$K$158"
            over_ref = f"{params}!${over[0]}${over[1:]}"
            if kind == "объём":
                # Площадь мест первых этажей уходит из продаваемой — тем же
                # `MAX(0, …)`, что и в самом блоке: мест больше здания это
                # расхождение, а не отрицательная площадь.
                area = re.search(r",('[^']+'!\$[A-Z]+\$\d+),0\)$", formula)
                if area is None:
                    missing.append(f"ПРОВЕРКИ: C{row} ({label}) без продаваемой")
                    continue
                cell = area.group(1)
                updated = formula.replace(
                    f",{cell},0)", f",MAX(0,{cell}-{over_ref}*{per_space}),0)")
            else:
                queue = re.search(
                    r"INDEX\('[^']+'!\$B\$88:\$B\$91,('[^']+'!\$[A-Z]+\$\d+)\)",
                    formula)
                if queue is None:
                    missing.append(f"ПРОВЕРКИ: C{row} ({label}) без очереди")
                    continue
                phase = queue.group(1)
                under_ref = f"{params}!${under[0]}${under[1:]}"
                # Те же множители, что у самого CAPEX гаража: подземная ставка,
                # инфляция затрат очереди и её коэффициент.
                addition = (f"+{under_ref}*{per_space}*{params}!$B$45/1000"
                            f"*{params}!$H$6"
                            f"*INDEX({params}!$T$88:$T$91,{phase})"
                            f"*INDEX({params}!$AH$88:$AH$91,{phase})")
                updated = formula[:-3] + addition + ",0)"
            xml, done = _v4_set_cell(xml, f"C{row}", formula=updated)
            if not done:
                missing.append(f"ПРОВЕРКИ: C{row} ({label}, {kind}) не записана")
    return xml


# Столбцы месяцев на листах CF: D..DS. Сетка у всех листов одна — строка 3
# каждого берёт даты с «Ставок», — поэтому налоговый год месяца объявляется
# ОДИН раз строкой на КОНСОЛИДАТОРЕ и читается всеми очередями.
_V4_TAX_YEARS_SPAN = 12          # горизонт 120 месяцев = 10 лет; с запасом
_V4_TAX_QUEUE_COLUMNS = ("C", "D", "E", "F")      # база очередей 1–4
_V4_TAX_SHARE_COLUMNS = ("H", "I", "J", "K")      # налог очередей 1–4
_V4_TAX_MONTHLY_COLUMNS = ("L", "M", "N", "O")    # запасная мера — месяцы с налогом
_V4_TAX_RESERVE_TOTAL = "P"


def _v4_tax_share_by_year(xml: str, missing: list[str]) -> str:
    """Сводный налог раздаётся очередям ПО ГОДАМ, а не одним весом за горизонт.

    Год — единственная мера, которую задаёт НК: налоговый период по налогу на
    прибыль это календарный год (ст. 285), база считается нарастающим итогом с
    начала периода (п. 7 ст. 274), а месяц объектом налогообложения не является
    вовсе. Книга делила налог долей `MAX(SUM(база за все месяцы),0)`, потом —
    долей ПОЛОЖИТЕЛЬНЫХ МЕСЯЦЕВ: обе меры приписывали очереди налог за месяцы и
    годы, в которых проект не был должен бюджету ничего. На четырёх очередях с
    шагом 24 месяца это 733 млн ₽ на строке очереди при совпадающем итоге.

    Свёртка до РВЭ обязательна и повторяет `_profit_tax_schedule`: всё, что
    признано до первого облагаемого месяца, приходит в ГОД этого месяца.
    Наивная раздача «по календарному году» без неё даёт на том же проекте
    770 млн вместо 1 847 — она выбрасывает отсрочку, которую делает сам расчёт
    налога.

    Блок дописывается в свободный низ листа: вставить строку в занятое место
    нельзя — поедут все ссылки. Налоговый год месяца считается один раз строкой
    `MAX(YEAR('CF'!D$3); первый облагаемый год)` — clamp и есть свёртка, и
    после него у каждого года простое равенство, без условий по датам.
    """
    rows = [int(number) for number in re.findall(r'<x:row r="(\d+)"', xml)]
    if not rows:
        missing.append("КОНСОЛИДАТОР: лист пуст — блок раздачи налога не дописан")
        return xml
    at = max(rows) + 2

    def label(coord: str, text: str) -> str:
        return (f'<x:c r="{coord}"{_v4_label_attr()} t="inlineStr">'
                f"<x:is><x:t>{xml_escape(text)}</x:t></x:is></x:c>")

    def formula(coord: str, text: str) -> str:
        return (f'<x:c r="{coord}"{_v4_formula_attr()}>'
                f"<x:f>{xml_escape(text)}</x:f></x:c>")

    parts: list[str] = []
    head = at
    parts.append(f'<x:row r="{head}">'
                 + _v4_head_cell(f"A{head}", "РАЗДАЧА СВОДНОГО НАЛОГА ПО ГОДАМ")
                 + "</x:row>")
    note = head + 1
    parts.append(f'<x:row r="{note}">'
                 + label(f"A{note}",
                         "Налог каждого года делится по вкладу очередей в базу "
                         "ЭТОГО года. Признанное до первого РВЭ отложено в год "
                         "РВЭ — так же считает строка 37 листа CF. Считается, "
                         "править нечего.")
                 + "</x:row>")
    gate = note + 1
    # Первый облагаемый месяц объявлен на листе CF строкой 31 — оттуда его и
    # берём. Второе объявление «с какого месяца облагается» разошлось бы с
    # первым молча: у книги тогда две даты гейта, и обе выглядят верными.
    # 99999 в строке 31 значит «включённых очередей нет» — год из него не
    # берём вовсе.
    parts.append(f'<x:row r="{gate}">'
                 + label(f"A{gate}", "Первый облагаемый год — год строки 31 листа CF")
                 + formula(f"B{gate}",
                           "IF('CF'!$B$31>50000,0,IFERROR(YEAR('CF'!$B$31),0))")
                 + "</x:row>")
    years = gate + 1
    year_cells = [label(f"A{years}", "Налоговый год месяца")]
    for column in _v4_cf_columns():
        year_cells.append(
            formula(f"{column}{years}", f"MAX(YEAR('CF'!{column}$3),$B${gate})"))
    parts.append(_v4_row_xml(years, year_cells))
    # Запасная мера на год, у которого налог есть, а годовая база
    # отрицательна: внутри года накопленным итогом была прибыль, налог
    # начислен и обратно не возвращается. Такой год делится по МЕСЯЦАМ, в
    # которых налог и начислен, — по ним же считает движок.
    monthly = years + 1
    for index in range(len(_V4_TAX_QUEUE_COLUMNS)):
        row = monthly + index
        cells = [label(f"A{row}",
                       f"База О{index + 1} в месяцы с начисленным налогом")]
        for column in _v4_cf_columns():
            cells.append(formula(
                f"{column}{row}",
                f"IF('CF'!{column}$37>0,MAX('CF_{index + 1}'!{column}$22,0),0)"))
        parts.append(_v4_row_xml(row, cells))
    header = monthly + len(_V4_TAX_QUEUE_COLUMNS)
    titles = ["Год", "Налог свода"]
    titles += [f"База О{index + 1}" for index in range(len(_V4_TAX_QUEUE_COLUMNS))]
    titles += ["Итого положительная"]
    titles += [f"Налог О{index + 1}" for index in range(len(_V4_TAX_SHARE_COLUMNS))]
    titles += [f"Запас О{index + 1}" for index in range(len(_V4_TAX_MONTHLY_COLUMNS))]
    titles += ["Итого запас"]
    parts.append(f'<x:row r="{header}">'
                 + "".join(_v4_head_cell(f"{_v4_column_letter(index + 1)}{header}", title)
                           for index, title in enumerate(titles))
                 + "</x:row>")
    grid = _v4_month_span(years)
    first = header + 1
    last = first + _V4_TAX_YEARS_SPAN - 1
    for offset in range(_V4_TAX_YEARS_SPAN):
        row = first + offset
        cells = [formula(f"A{row}", f"$B${gate}" if offset == 0 else f"A{row - 1}+1"),
                 formula(f"B{row}", f"SUMIF({grid},$A{row},{_v4_month_span(37, 'CF')})")]
        for index, column in enumerate(_V4_TAX_QUEUE_COLUMNS):
            cells.append(formula(
                f"{column}{row}",
                f"MAX(SUMIF({grid},$A{row},"
                f"{_v4_month_span(22, f'CF_{index + 1}')}),0)"))
        span = f"{_V4_TAX_QUEUE_COLUMNS[0]}{row}:{_V4_TAX_QUEUE_COLUMNS[-1]}{row}"
        cells.append(formula(f"G{row}", f"SUM({span})"))
        for index, column in enumerate(_V4_TAX_MONTHLY_COLUMNS):
            cells.append(formula(
                f"{column}{row}",
                f"SUMIF({grid},$A{row},{_v4_month_span(monthly + index)})"))
        reserve = (f"{_V4_TAX_MONTHLY_COLUMNS[0]}{row}:"
                   f"{_V4_TAX_MONTHLY_COLUMNS[-1]}{row}")
        cells.append(formula(f"{_V4_TAX_RESERVE_TOTAL}{row}", f"SUM({reserve})"))
        for index, column in enumerate(_V4_TAX_SHARE_COLUMNS):
            annual = f"{_V4_TAX_QUEUE_COLUMNS[index]}{row}"
            monthly_cell = f"{_V4_TAX_MONTHLY_COLUMNS[index]}{row}"
            total_reserve = f"${_V4_TAX_RESERVE_TOTAL}{row}"
            # Год не дал ответа — делим по месяцам с налогом; не дали и они —
            # поровну между ВКЛЮЧЁННЫМИ очередями: терять налог нельзя, а
            # основания у деления в этом случае нет, и так и написано.
            cells.append(formula(
                f"{column}{row}",
                f"IF($G{row}>0,$B{row}*{annual}/$G{row},"
                f"IF({total_reserve}>0,$B{row}*{monthly_cell}/{total_reserve},"
                f"IF($B${4 + index}=\"Да\",$B{row}/MAX(COUNTIF($B$4:$B$7,\"Да\"),1),0)))"))
        parts.append(_v4_row_xml(row, cells))
    total = last + 1
    total_cells = [label(f"A{total}", "Итого"),
                   formula(f"B{total}", f"SUM(B{first}:B{last})")]
    for column in _V4_TAX_SHARE_COLUMNS:
        total_cells.append(
            formula(f"{column}{total}", f"SUM({column}{first}:{column}{last})"))
    parts.append(_v4_row_xml(total, total_cells))
    check = total + 1
    parts.append(f'<x:row r="{check}">'
                 + label(f"A{check}",
                         "Расхождение со сводным налогом — обязано быть 0")
                 + formula(f"B{check}", f"B{total}-$K$8")
                 + "</x:row>")

    tail = "</x:sheetData>"
    if tail not in xml:
        missing.append("КОНСОЛИДАТОР: конец sheetData не найден — блок не дописан")
        return xml
    xml = xml.replace(tail, "".join(parts) + tail, 1)

    # Доля очереди теперь считается от её налога по годам, а не от базы за
    # горизонт. Подпись столбца обязана переехать вместе с величиной: «доля»
    # под двумя разными мерами — это два ответа на один вопрос.
    for index, column in enumerate(_V4_TAX_SHARE_COLUMNS, start=1):
        row = 29 + index
        span = _v4_month_span(22, f"CF_{index}")
        old = f"MAX(SUM({span}),0)"
        alt = f"SUMIF({span},\">0\")"
        source = f"{column}{total}"
        for candidate in (old, alt):
            encoded = xml_escape(candidate)
            if encoded in xml:
                xml = xml.replace(encoded, xml_escape(source), 1)
                break
        else:
            missing.append(f"КОНСОЛИДАТОР: доля налога очереди {index} не опознана")
    was = "<x:t>Положительная база</x:t>"
    if was in xml:
        xml = xml.replace(was, "<x:t>Налог очереди по годам</x:t>", 1)
    else:
        missing.append("КОНСОЛИДАТОР: подпись «Положительная база» не опознана")
    return xml


def _v4_revenue_by_product(xml: str, products: list[dict[str, Any]],
                           missing: list[str]) -> str:
    """Колонки «Выручка · продукт» по очередям и строка итога.

    Колонка заводится под продукт, у которого выручка есть хоть в одной
    очереди: семь нулевых колонок — шум, а не полнота (то же правило, что на
    экране). Продукт, которого книга посчитать не умеет, в `missing`, а не
    молча пропущен: пустая колонка и отсутствующая выглядят одинаково.
    """
    if not products:
        return xml
    labels = {str(item.get("key")): str(item.get("label") or item.get("key"))
              for item in products}
    column = _V4_CONSOLIDATOR_FIRST_COL
    for key in labels:
        letter = get_column_letter(column)
        if key in _V4_SALES_PRODUCT_ROW:
            base = _V4_SALES_PRODUCT_ROW[key]
            per_queue = [f"'Продажи'!$B${base + _V4_SALES_PHASE_STRIDE * index}"
                         for index in range(len(_V4_CONSOLIDATOR_ROWS))]
        elif key in _V4_OBJECT_PRODUCT_CELLS:
            phase_cell, revenue_cell = _V4_OBJECT_PRODUCT_CELLS[key]
            per_queue = [f"IF('ОБЪЕКТЫ'!$B${phase_cell}={index + 1},"
                         f"'ОБЪЕКТЫ'!$B${revenue_cell},0)"
                         for index in range(len(_V4_CONSOLIDATOR_ROWS))]
        elif key in _V4_OBJECT_PARKING_KEYS:
            # Паркинг — продукт СВОЕГО объекта: колонка на объект, строка его
            # выручки на листе ОБЪЕКТЫ и очередь та же, что у самого объекта
            # (владелец, 27.09.2026: «Паркинг — МФОЦ / офисы», «Паркинг — ТЦ»…).
            parking = _V4_OBJECT_PARKING_BY_KEY.get(_V4_OBJECT_PARKING_KEYS[key])
            if parking is None:
                missing.append(f"КОНСОЛИДАТОР: у книги нет строки паркинга для «{labels[key]}»")
                continue
            enabled_row, revenue_row = parking[1], parking[3]
            per_queue = [f"IF('ОБЪЕКТЫ'!$B${enabled_row + 1}={index + 1},"
                         f"'ОБЪЕКТЫ'!$B${revenue_row},0)"
                         for index in range(len(_V4_CONSOLIDATOR_ROWS))]
        else:
            missing.append(f"КОНСОЛИДАТОР: книга не умеет считать выручку «{labels[key]}»")
            continue
        xml, done = _v4_set_or_insert_cell(
            xml, f"{letter}3", text=f"Выручка · {labels[key]}, млн ₽")
        if not done:
            missing.append(f"КОНСОЛИДАТОР: заголовок {letter}3 не поставлен")
            continue
        for row, formula in zip(_V4_CONSOLIDATOR_ROWS, per_queue):
            xml, done = _v4_set_or_insert_cell(xml, f"{letter}{row}", formula=formula)
            if not done:
                missing.append(f"КОНСОЛИДАТОР: ячейка {letter}{row} не поставлена")
        first, last = _V4_CONSOLIDATOR_ROWS[0], _V4_CONSOLIDATOR_ROWS[-1]
        xml, done = _v4_set_or_insert_cell(
            xml, f"{letter}{_V4_CONSOLIDATOR_TOTAL_ROW}",
            formula=f"SUM({letter}{first}:{letter}{last})")
        if not done:
            missing.append(f"КОНСОЛИДАТОР: итог {letter}{_V4_CONSOLIDATOR_TOTAL_ROW}")
        column += 1
    return xml


# Кэш-свип в книге.
#
# Очередь передала долг, но продавать не перестала: строка 12 её листа —
# «Прямые поступления после РВЭ», и долю от них банк забирает в погашение
# долга, который теперь несёт следующая. Строка 26 листов CF в шаблоне пуста —
# ряд встаёт, не сдвигая ссылок; доля лежит на «Вводных» рядом с признаком
# переноса.
# Ячейка одобренного лимита ПФ на «Вводных» и строка непокрытой потребности,
# дописываемая в конец листа CF: свободных строк внутри блока ПФ (38–47) в
# шаблоне не осталось — 26, 29, 64 и 65 уже заняты свипом, нехваткой в РВЭ и
# переносом долга. Вставить строку в занятое место нельзя: поедут все ссылки.
_V4_PF_APPROVED_CELL = "F26"
# Блок очередей «Вводных»: лимит НКЛ очереди (ввод) и её потолок (формула).
_V4_PF_QUEUE_INDIVIDUAL_COL = "AS"
_V4_PF_QUEUE_CAP_COL = "AT"
# Количество квартир очереди. Колонки под него в шаблоне нет вовсе: книга
# знала метры квартир и не знала, сколько их, — «Единицы» строки «Квартиры»
# стояли пустыми и на ТЭП, и на Дашборде. База (штуки на исходных метрах) и
# живое число, которое идёт за плотностью так же, как за ней идёт продаваемая
# площадь (L = Z×K15): числом оно стояло бы мёртвым — правка плотности
# двигала бы метры и не двигала квартиры.
#
# Буквы колонок объявлены у читателя (дашборд), а не здесь второй раз:
# писатель и читатель одной ячейки, назвавшие её порознь, однажды назовут
# разные.
_V4_APARTMENT_UNITS_BASE_COL = v4_dashboard.QUEUE_APARTMENT_UNITS_BASE_COL
_V4_APARTMENT_UNITS_COL = v4_dashboard.QUEUE_APARTMENT_UNITS_COL
_V4_PF_UNCOVERED_ROW = 87
_V4_PF_UNCOVERED_PARITY_ROW = 87

_V4_SWEEP_ROW = 26
_V4_SWEEP_SHARE_CELL = "F92"


# Служебная строка блока CAPEX: база лимита БРИДЖа — те же статьи, но только
# в месяцах ДО РнС. 36 и 37 заняты сносом и расселением, 38 — процентами ВРИ,
# 39 в шаблоне пуста. В итог блока и в базу резерва она не входит по
# построению: обе формулы читают диапазон 14:31 и перечисленные строки.
_V4_CAPEX_BRIDGE_BASE_ROW = 39


def _v4_apply_bridge_limit_before_permit(xml: str, missing: list[str]) -> str:
    """Лимит БРИДЖа в книге — по платежам ДО РнС, как у движка.

    «Бридж по определению это только то, что ДО РнС» (владелец, 04.09.2026).
    База комиссии выдачи (строка 57 листов CF) брала итоги статей целиком —
    покупку, П, РД и денежную соцкомпенсацию, — и рассрочка входила в неё вся,
    включая платежи после открытия ПФ. С РнС эти платежи финансирует ПФ, и
    лимит под них — просьба о деньгах дважды.

    Считается по помесячным строкам самих статей, а не по их итогам: у покупки
    график задаётся вводной, у соцкомпенсации своя дата, а РД у длинного
    проекта переваливает за РнС. При совмещённом режиме соцнагрузки денежная
    часть идёт профилем строки 31 в той доле, в какой она денежная, — сумма за
    месяцы до РнС выходит той же, что у движка.
    """
    from openpyxl.utils import get_column_letter as _col

    def style_of(coord: str) -> str | None:
        found = re.search(r'<x:c r="%s"[^>]*?\ss="(\d+)"' % coord, xml)
        return found.group(1) if found else None

    label_style, amount_style, month_style = style_of("A20"), style_of("B20"), style_of("D20")
    for phase in range(_V4_CAPEX_PHASES):
        base = _V4_CAPEX_BLOCK_STRIDE * phase
        row = _V4_CAPEX_BRIDGE_BASE_ROW + base
        permit = f"$B${7 + base}"
        social_total = f"$B${31 + base}"
        queue_row = _V4_CF_QUEUE_ENABLED_ROW + phase
        cash = f"'Вводные'!$B$56*'Вводные'!$R${queue_row}*'Вводные'!$H$6"
        xml = _v4_ensure_row(xml, row)
        cells = {f"A{row}": dict(text="Справочно: база лимита БРИДЖа (платежи до РнС)"),
                 f"B{row}": dict(formula=f"SUM(D{row}:{_V4_LAST_COLUMN}{row})"),
                 f"C{row}": dict(text="млн ₽")}
        styles = {f"A{row}": label_style, f"B{row}": amount_style, f"C{row}": None}
        for index in range(_V4_CAPEX_MONTH_COLUMNS):
            column = _col(4 + index)
            social = (
                f"IF('Вводные'!$B$37=\"Денежная компенсация\",{column}{31 + base},"
                f"IF('Вводные'!$B$37=\"{SOCIAL_MODE_BOTH}\","
                f"{column}{31 + base}*IFERROR(({cash})/{social_total},0),0))")
            cells[f"{column}{row}"] = dict(formula=(
                f"IF({column}$3<{permit},"
                f"{column}{14 + base}+{column}{17 + base}+{column}{18 + base}+{social},0)"))
            styles[f"{column}{row}"] = month_style
        xml, done = _v4_set_cells(xml, row, cells, styles)
        if not done:
            missing.append(f"CAPEX · база лимита БРИДЖа: строка {row} не записана")
    return xml


def _v4_use_bridge_base_row(xml: str, phase: int, missing: list[str]) -> str:
    """Строка 57 листа CF берёт базу лимита из служебной строки CAPEX."""
    base = _V4_CAPEX_BLOCK_STRIDE * (phase - 1)
    row = _V4_CAPEX_BRIDGE_BASE_ROW + base
    purchase, design_p, design_rd = 14 + base, 17 + base, 18 + base
    social = 31 + base
    queue_row = _V4_CF_QUEUE_ENABLED_ROW + (phase - 1)
    cash = f"'Вводные'!$B$56*'Вводные'!$R${queue_row}*'Вводные'!$H$6"
    old = (f"('CAPEX'!$B${purchase}+'CAPEX'!$B${design_p}+'CAPEX'!$B${design_rd}"
           f"+IF('Вводные'!$B$37=\"Денежная компенсация\",'CAPEX'!$B${social},"
           f"IF('Вводные'!$B$37=\"{SOCIAL_MODE_BOTH}\",{cash},0)))")
    new = f"SUM({_v4_month_span(row, 'CAPEX')})"

    def build(_column: str, body: str) -> str:
        return body.replace(old, new)

    xml, count = _v4_rewrite_row_formulas(xml, _V4_BRIDGE_FEE_ROW, old, build)
    if not count:
        missing.append(
            f"CF_{phase}: строка {_V4_BRIDGE_FEE_ROW} не опознана — лимит БРИДЖа "
            "остался от полной цены, а не от платежей до РнС")
    return xml


def _v4_apply_extra_objects_tax_row(xml: str, phase: int, missing: list[str]) -> str:
    """Признание стоимости дописанных объектов в налоговой базе очереди — как в движке.

    Проданный объект признаёт СВОЙ CAPEX по своему проданному объёму: он и в
    движке стоит отдельным пулом (`krt_products`) — тем же слагаемым, что
    шаблон пишет трём своим объектам. У объекта с признаком «что дальше»
    (ФОК) переданный городу не признаёт ничего — выручки у него нет, — и его
    стоимость возвращается в общий пул очереди, откуда её вычитала строка
    аллокации объектов. Забыть вторую половину значит оставить стоимость
    непризнанной до конца проекта: налог вырос бы на четверть её, и обе книги
    выглядели бы верными.
    """
    if not _v4_extras():
        return xml
    queue = phase
    alloc_row = 96 + 8 * (phase - 1)
    pool_old = f"(SUM({_v4_month_span(20)})-'ОБЪЕКТЫ'!$B${alloc_row})"
    returned = ""
    for lay in _v4_extras():
        if lay.disposition_row:
            sold = (f"'Вводные'!$K${lay.disposition_row}=\"{_V4_OBJECT_SALE_WORD}\"")
            capex = f"'ОБЪЕКТЫ'!$B${lay.object_head + 22}"
            returned += (f"+IF({sold},0,IF('ОБЪЕКТЫ'!$B${lay.object_head + 2}={queue},"
                         f"{capex},0))")
    pool_new = pool_old[:-1] + returned + ")"

    def build(column: str, body: str) -> str:
        # Хвост формулы — колонко-зависимый: «-D53-D57-D21» в колонке D и
        # «-E53-E57-E21» в соседней. Искать его строкой одной колонки значит
        # не найти его ни в одной, кроме первой.
        tail = f"-{column}53-{column}57-{column}21"
        if pool_old not in body or tail not in body:
            return body
        body = body.replace(pool_old, pool_new)
        own = ""
        for lay in _v4_extras():
            head = lay.object_head
            mine = f"'ОБЪЕКТЫ'!$B${head + 2}={queue}"
            volume = _V4_OBJECT_PRODUCT_CELLS[lay.obj.key][1] - 2
            share = (f"IF({mine},IFERROR('ОБЪЕКТЫ'!$B${head + 22}*'ОБЪЕКТЫ'!{column}{volume}"
                     f"/'ОБЪЕКТЫ'!$B${volume},0),0)")
            if lay.disposition_row:
                sold = (f"'Вводные'!$K${lay.disposition_row}=\"{_V4_OBJECT_SALE_WORD}\"")
                own += f"-IF({sold},{share},0)"
            else:
                own += f"-{share}"
        # Слагаемые встают ПЕРЕД процентами и НДС — там же, где стоят три
        # объекта шаблона: порядок слагаемых читается как порядок признания.
        at = body.rindex(tail)
        return body[:at] + own + body[at:]

    xml, count = _v4_rewrite_row_formulas(xml, 22, "'ОБЪЕКТЫ'!$B$64=", build)
    if count < 100:
        missing.append(f"CF_{phase}: строка налоговой базы не знает о дописанных объектах ({count})")
    return xml


def _v4_apply_core_pool_without_sales(xml: str, phase: int, missing: list[str]) -> str:
    """Общий пул расходов очереди без проданных штук признаётся в РВЭ — как в движке.

    Строка налоговой базы делит пул (все расходы очереди минус CAPEX
    объектов) на проданные квартиры, коммерцию, паркинг и кладовые. У проекта
    без них — нежилого, офисника — делитель ноль, IFERROR отдавал 0, и пул не
    вычитался НИ В ОДНОМ месяце. Движок (`core_cost and not
    core_quantity_total`) вычитает его целиком в месяц РВЭ. На проекте
    владельца «Вавилов» (офисы 19 110 м²) это 1 819,65 млн ₽ мимо базы:
    налог книги 763,9 млн против 308,6 у движка, и паритет налога, чистой
    прибыли и LLCR падал.

    Правится только запасная ветка IFERROR, и после прохода дописанных
    объектов: пул к этому моменту уже несёт возвращённую стоимость ФОКа.
    """
    head = f"IFERROR((SUM({_v4_month_span(20)})-'ОБЪЕКТЫ'!$B${96 + 8 * (phase - 1)}"

    def build(column: str, body: str) -> str:
        at = body.find(head)
        if at < 0:
            return body
        # Пул — первая скобка внутри IFERROR; запасная ветка — «,0)» в конце
        # вызова. Скобки считаются, а не ищутся строкой: внутри пула стоят
        # вложенные IF дописанных объектов.
        start = at + len("IFERROR(")
        depth, pool_end, call_end = 0, -1, -1
        for index in range(start, len(body)):
            char = body[index]
            if char == "(":
                depth += 1
            elif char == ")":
                depth -= 1
                if depth == 0 and pool_end < 0:
                    pool_end = index + 1
                if depth < 0:
                    call_end = index
                    break
        if pool_end < 0 or call_end < 0 or body[call_end - 2:call_end] != ",0":
            return body
        pool = body[start:pool_end]
        in_rve = f"{_v4_month_offset(column, '$B$8')}=0"
        return (body[:call_end - 1] + f"IF({in_rve},{pool},0)" + body[call_end:])

    xml, count = _v4_rewrite_row_formulas(xml, 22, head, build)
    if count < 100:
        missing.append(f"CF_{phase}: строка налоговой базы не признаёт пул без продаж ({count})")
    return xml


_V4_ACCRUAL_ROW = 58                 # Финансовые расходы месяца (начисление)


def _v4_accrual_row_xml(row: int, label: str, formulas: dict[str, str]) -> str:
    """Строка листа CF деньгами — стилями строк 53 и 57, ближайших соседей той
    же природы: у них месяц стоит стилем 117, а подпись и итог идут без своего.
    Свой формат посреди блока Excel показал бы чужим."""
    cells = [
        f'<x:c r="A{row}" t="inlineStr"><x:is><x:t>{xml_escape(label)}</x:t></x:is></x:c>',
        f'<x:c r="B{row}"><x:f>SUM(D{row}:{_V4_LAST_COLUMN}{row})</x:f></x:c>',
        f'<x:c r="C{row}" t="str"><x:v>млн ₽</x:v></x:c>',
    ]
    for column in _v4_cf_columns():
        cells.append(
            f'<x:c r="{column}{row}" s="117">'
            f"<x:f>{xml_escape(formulas[column])}</x:f></x:c>")
    return f'<x:row r="{row}">' + "".join(cells) + "</x:row>"


def _v4_apply_interest_accrual(xml: str, phase: int, missing: list[str]) -> str:
    """Проценты уменьшают базу налога в месяце НАЧИСЛЕНИЯ (п. 8 ст. 272 НК).

    Строка 53 «ПФ — уплата процентов и комиссий» отвечает на вопрос кассы, и
    там она и остаётся: вклад капитала (49), распределение собственнику (50) и
    проверка фондирования (63) считают деньги. А база налога (строка 22)
    вычитала её же — то есть признавала расход в месяце ВЫПЛАТЫ, а платится в
    этой модели всё разом в РВЭ. Пока очереди прибыльны, разницы нет; она
    появляется на убыточной очереди, где половинное ограничение ст. 283
    считает по годам и год признания решает, сколько убытка зачтётся.

    Начисление собирается из строк, которые уже есть, а не считается второй
    раз: проценты БРИДЖа (32) и их капитализация — та же величина, что растит
    строку 37, — проценты ПФ (42), плата за лимит (43) и капитализация ПФ,
    растящая строку 48. Гейты повторяют гейты этих строк слово в слово, иначе
    начисленное за горизонт не сойдётся с уплаченным.

    Капитализацию в базе не путать с капитализацией в ДОЛГЕ: та лимит ПФ не
    выбирает (решение владельца 04.08.2026) и живёт отдельным обязательством —
    здесь речь только о том, в каком месяце расход признан.
    """
    sheet = f"CF_{phase}"
    columns = _v4_cf_columns()
    row = _V4_ACCRUAL_ROW

    formulas: dict[str, str] = {}
    for index, column in enumerate(columns):
        previous = columns[index - 1] if index else "C"
        # Капитализация БРИДЖа — тем же условием, что у строки 37, и по ставке
        # БРИДЖа: строка 37 берёт её оттуда же.
        bridge_cap = (f"IF(AND({column}$3<$B$7,$B$5=1),"
                      f"{previous}37*'Ставки'!{column}$6/12,0)")
        # Капитализация ПФ живёт, пока копится строка 48: с РнС и по РВЭ
        # включительно — в сам месяц РВЭ её начисляет строка 53, грубя
        # накопленное на (1+ставка/12).
        pf_cap = (f"IF(AND({column}$3>=$B$7,{column}$3<=$B$8),"
                  f"{previous}48*{column}41/12,0)")
        formulas[column] = (f"{column}32+{bridge_cap}"
                            f"+{column}42+{column}43+{pf_cap}")

    body = _v4_accrual_row_xml(row, "Финансовые расходы месяца (начисление)", formulas)
    existing = re.search(r'<x:row r="%d"[^>]*>(.*?)</x:row>' % row, xml, re.S)
    if not existing:
        missing.append(f"{sheet}: строка {row} не найдена")
        return xml
    # «Занята» — это формула или число в МЕСЯЧНЫХ ячейках. Подпись и единица
    # строки-разделителя наши: в шаблоне там пустая строка и знак «×».
    taken = [column for column, cell in re.findall(
        r'<x:c r="([A-Z]{1,3})%d"[^>]*>(.*?)</x:c>' % row, existing.group(1), re.S)
        if column in set(columns) and ("<x:f>" in cell or "<x:v>" in cell)]
    if taken:
        missing.append(f"{sheet}: строка {row} занята ({taken[0]}{row})")
        return xml
    xml = xml[:existing.start()] + body + xml[existing.end():]

    # База налога вычитает начисленное вместо уплаченного. Хвост формулы
    # колонко-зависимый — «-D53-D57-D21» в колонке D и «-E53-E57-E21» в
    # соседней: искать его строкой одной колонки значит не найти ни в одной,
    # кроме первой.
    changed = 0

    def swap(column: str, formula: str) -> str:
        nonlocal changed
        tail = f"-{column}53-{column}57-{column}21"
        if tail not in formula:
            return formula
        changed += 1
        return formula.replace(tail, f"-{column}{row}-{column}57-{column}21")

    xml, seen = _v4_rewrite_row_formulas(xml, 22, "'ОБЪЕКТЫ'!", swap)
    if changed < len(columns):
        missing.append(
            f"{sheet}: база налога не отдала выплату процентов начислению "
            f"({changed} из {len(columns)}, узнано {seen})")
    return xml


def _v4_mark_as_entry(xml: str, coord: str, missing: list[str]) -> str:
    """Ставит ячейке стиль ввода, не трогая её содержимого.

    Стиль здесь — утверждение о ячейке: «это правят руками». Лист ввода
    отбирает по нему строки, поэтому вводная без стиля остаётся на расчётном
    листе — то есть там, где её никто не ищет.
    """
    found = re.search(r'<x:c r="%s"(?P<attrs>[^>]*?)(/>|>)' % coord, xml)
    if not found:
        missing.append(f"стиль ввода: ячейки {coord} нет")
        return xml
    attrs = found.group("attrs")
    updated = (re.sub(r'\ss="\d+"', "", attrs) + ' s="12"').strip()
    return (xml[:found.start()] + f'<x:c r="{coord}" {updated}'
            + found.group(2) + xml[found.end():])


def _v4_apply_pf_ceiling(xml: str, phase: int, missing: list[str]) -> str:
    """Одобренный лимит ПФ становится потолком выборки — как у движка.

    Поле `pf_limit_approved_mln` работало только в движке: там заданный лимит
    становится настоящим потолком, выборка режется по свободному остатку, а
    непокрытая потребность уходит в `pf_shortfall` с месяцем первой нехватки.
    Книга же считала лимит СВОЙ (B26 — округление выборки вверх до 10 млн) и
    потолком его не ограничивала: поле стояло на «Вводных» справочно, и это
    было прямо записано в причине `V4_INPUTS_SHOWN_ONLY`.

    Цена: «требуется 30 млрд, банк одобрил 20» — движок обрежет выборку и
    покажет дыру, а книга посчитает так, будто все 30 доступны. Это не допуск
    в полпроцента, а разные проекты в двух файлах одного расчёта.

    Потолок очереди — клетка блока очередей (AT «Вводных»): её лимит НКЛ, а
    у одиночного проекта — одобренный лимит F26. Общий лимит у очередей
    потолком не служит (владелец, 20.09.2026: он ожидание на все очереди,
    а НКЛ каждой считается заново при её открытии). Считает это ровно так же
    движок (`_pf_limit_cap_mln`): разойдись книга с ним, расхождение было бы
    нашим, а не методики.

    Ноль в поле — прежнее поведение до последней формулы: `MIN` и `MAX` из
    формулы исчезают вовсе, и книга без одобренного лимита считает ровно как
    раньше.
    """
    columns = _v4_cf_columns()
    sheet = f"CF_{phase}"
    queue_row = _V4_CF_QUEUE_ENABLED_ROW + phase - 1
    # Потолок очереди — её же клетка блока очередей; ноль в ней значит
    # «потолка нет», и есть ли потолок, решает та же клетка, что и его
    # величину: второй ответ на «задан ли» разошёлся бы с первым.
    approved = f"'Вводные'!${_V4_PF_QUEUE_CAP_COL}${queue_row}"
    has_cap = f"{approved}>0"
    cells: dict[str, dict[str, Any]] = {}
    for index, column in enumerate(columns):
        # Своё тело на НАЧАЛО месяца: потолок держит только его. Принятый долг
        # лимита не выбирает, поэтому из остатка вычитается всё, что принято и
        # ещё не сметено свипом, — по ПРЕДЫДУЩИЕ месяцы: долг этого месяца
        # ложится на баланс ниже по циклу, уже после проверки потолка.
        if index == 0:
            own = f"MAX(0,{column}38)"
        else:
            previous = columns[index - 1]
            own = (f"MAX(0,{column}38-MAX(0,"
                   f"SUM($D${_V4_CARRY_ACCEPTED_ROW}:{previous}{_V4_CARRY_ACCEPTED_ROW})"
                   f"-SUM($D${_V4_SWEEP_ROW}:{previous}{_V4_SWEEP_ROW})))")
        # Формула идёт в `_v4_set_cells` СЫРОЙ: экранирует она сама, и «&gt;»
        # здесь превратилось бы в «&amp;gt;» — Excel открыл бы книгу, а
        # вычислитель не понял 18 592 формулы разом.
        cells[f"{column}45"] = dict(formula=(
            f"IF({has_cap},"
            f"MIN({column}44,MAX(0,{approved}-{own})),{column}44)"))
    xml, done = _v4_set_cells(xml, 45, cells)
    if not done:
        missing.append(f"{sheet}: строка 45 (выборка ПФ) не найдена")
        return xml

    # Непокрытая потребность отдельной величиной: без неё дыра видна только
    # как разбухший «вклад собственного капитала» (строка 49) — там она
    # неотличима от денег, которые инвестор действительно собирался внести.
    body = (
        f'<x:c r="A{_V4_PF_UNCOVERED_ROW}" s="113" t="str"><x:v>'
        f"ПФ — непокрытая потребность (одобренного лимита не хватило)"
        f'</x:v></x:c>'
        f'<x:c r="B{_V4_PF_UNCOVERED_ROW}" s="113" t="n"><x:f>'
        f"IF($B$5=1,SUM(D44:{_V4_LAST_COLUMN}44)"
        f"-SUM(D45:{_V4_LAST_COLUMN}45),0)"
        f'</x:f></x:c>'
        f'<x:c r="C{_V4_PF_UNCOVERED_ROW}" s="113" t="str"><x:v>млн ₽</x:v></x:c>')
    xml, done = _v4_insert_row(xml, _V4_PF_UNCOVERED_ROW, body, None)
    if not done:
        missing.append(
            f"{sheet}: строка {_V4_PF_UNCOVERED_ROW} занята — "
            "непокрытую потребность писать некуда")
    return xml


_V4_FEES_ROW = 57                    # комиссии выдачи (БРИДЖ и резервирование ПФ)
_V4_FEES_EQUITY_NOTE = (
    " — платятся собственным капиталом (вклад в строке 49), "
    "в потребность и лимит ПФ не входят")


def _v4_name_fees_paid_by_equity(xml: str, phase: int, missing: list[str]) -> str:
    """Комиссии выдачи книга платит капиталом — и говорит это в подписи.

    Строка 57 листов CF (комиссия БРИДЖа в первом месяце, резервирование ПФ
    в месяц РнС) входит во вклад собственного капитала (49) и не входит ни
    в потребность ПФ, ни в лимит — так же считает движок (`project_cf` и
    `equity_cf` вычитают `bridge_fee` и `pf_reservation_fee` напрямую).
    Это допустимая банковская конструкция, а не ошибка (решение владельца,
    19.09.2026: «оставляем капиталом и пишем»), но до сих пор она нигде не
    была объявлена, и человек вправе был считать, что комиссия сидит в
    лимите. Банк бывает требует оплаты и за счёт кредитных средств —
    вводная «источник оплаты комиссий» стоит в очереди задач, а пока
    подпись строки говорит, как посчитано.
    """
    found = re.search(
        r'<x:c r="A%d"([^>]*)>\s*(?:<x:v>[^<]*</x:v>|<x:is>.*?</x:is>)\s*</x:c>'
        % _V4_FEES_ROW, xml, re.S)
    if not found:
        missing.append(f"CF_{phase}: подпись строки {_V4_FEES_ROW} не найдена")
        return xml
    attrs = re.sub(r'\s+t="[^"]*"', "", found.group(1))
    label = "Комиссии выдачи (БРИДЖ и резервирование ПФ)" + _V4_FEES_EQUITY_NOTE
    cell = (f'<x:c r="A{_V4_FEES_ROW}"{attrs} t="inlineStr">'
            f"<x:is><x:t>{xml_escape(label)}</x:t></x:is></x:c>")
    return xml[:found.start()] + cell + xml[found.end():]


def _v4_apply_cash_sweep(xml: str, phase: int, missing: list[str]) -> str:
    """Строка 26: сколько принято кэш-свипом с продаж предыдущей очереди.

    Формула — та же, что у движка: доля от прямых поступлений предыдущей
    очереди, но не больше её долга на этот месяц. Больше, чем должны, банк не
    берёт; излишек остаётся проекту, и в книге он просто не списывается.
    """
    columns = _v4_cf_columns()
    sheet = f"CF_{phase}"
    if phase <= 1:
        formulas = {column: "0" for column in columns}
    else:
        previous = f"CF_{phase - 1}"
        share = f"'Вводные'!${_V4_SWEEP_SHARE_CELL[0]}${_V4_SWEEP_SHARE_CELL[1:]}"
        flag = f"'Вводные'!${_V4_CARRY_FLAG_CELL[0]}${_V4_CARRY_FLAG_CELL[1:]}=\"Да\""
        formulas = {}
        for index, column in enumerate(columns):
            if index == 0:
                # В первом месяце передавать ещё нечего.
                formulas[column] = "0"
                continue
            # Свип идёт, только когда предыдущая очередь уже передала долг:
            # до этого её поступления гасят её собственную линию.
            handed = f"SUM('{previous}'!$D$65:'{previous}'!${columns[index - 1]}$65)>0"
            owed = f"MAX(0,{column}38+{column}45+{column}{_V4_CARRY_ACCEPTED_ROW}-{column}46)"
            formulas[column] = (
                f"IF(AND({flag},$B$5=1,{handed}),"
                f"MIN({owed},{share}*'{previous}'!{column}12),0)")
    body = _v4_carry_row_xml(_V4_SWEEP_ROW, "ПФ — погашение кэш-свипом предыдущей очереди",
                             formulas)
    existing = re.search(r'<x:row r="%d"[^>]*>(.*?)</x:row>' % _V4_SWEEP_ROW, xml, re.S)
    if not existing:
        missing.append(f"{sheet}: строка {_V4_SWEEP_ROW} не найдена")
        return xml
    if "<x:v>" in existing.group(1) or "<x:f>" in existing.group(1):
        missing.append(f"{sheet}: строка {_V4_SWEEP_ROW} занята")
        return xml
    xml = xml[:existing.start()] + body + xml[existing.end():]
    # Долг на конец и его самопроверка обязаны увидеть свип, иначе книга
    # покажет погашение и тот же долг.
    for row, pattern, replacement in (
            (47, "{c}38+{c}45+{c}64-{c}46-{c}65", "{c}38+{c}45+{c}64-{c}46-{c}65-{c}26"),
            (61, "{c}38+{c}45+{c}64-{c}46-{c}65", "{c}38+{c}45+{c}64-{c}46-{c}65-{c}26")):
        # Строка читается и пишется ОДНИМ проходом на каждую: правка по ячейке
        # копировала мегабайтный лист на каждый из 180 месяцев — 1440 копий на
        # сборку, 1,4 секунды. Цена прохода растёт вместе с сеткой, и сторож,
        # считающий ПРОХОДЫ, этого подорожания не видит.
        formulas = _v4_row_formulas(xml, row)
        cells: dict[str, dict[str, Any]] = {}
        for column in columns:
            coord = f"{column}{row}"
            formula = formulas.get(coord)
            if formula is None:
                # Ячейка может и быть — без формулы. Читатель об этом узнаёт.
                missing.append(f"{sheet}: формулы {coord} нет")
                break
            old = pattern.format(c=column)
            if old not in formula:
                missing.append(f"{sheet}: формула {coord} не опознана")
                break
            cells[coord] = dict(formula=formula.replace(old, replacement.format(c=column), 1))
        if cells:
            xml, done = _v4_set_cells(xml, row, cells)
            if not done:
                missing.append(f"{sheet}: строка {row} не найдена")
    return xml


_V4_CARRY_PARITY_ROW = 85
_V4_VAT_PARITY_ROW = 86


_V4_REPORT_DEFAULT_ROW = 21          # ОТЧЕТ: строка под «Статусом модели»


def _v4_add_report_default_row(xml: str, missing: list[str]) -> str:
    """Строка ОТЧЁТа: сколько не погашено в РВЭ и не передано дальше.

    Строка 22 у книги уже есть — «Непогашенный долг на конец проекта (дефолт,
    если > 0)». У неё тот же изъян, который на экране чинился отдельно: она
    смотрит на КОНЕЦ горизонта. Банк ждёт погашения в дату раскрытия эскроу, и
    если остаточные продажи закрывают долг годом позже, строка 22 показывает
    ноль — книга о дефолте молчит (владелец, 30.08.2026: «в экселе мы где-то
    увидим что проект дефолт»).

    Нехватку в РВЭ книга считает по очередям (строка 29 листов CF), но одной
    суммой её показывать нельзя: та же величина возникает и при законном
    переносе долга следующей очереди — банк его принял, дефолта нет. Поэтому
    из суммы вычитается переданное (строка 65), и остаётся ровно то, что никто
    не принял.

    Строка 21 в шаблоне пуста в колонках A–C (справа, в F–H, живёт своя
    панель темпов продаж — её не трогаем). Значит ряд встаёт, не сдвигая ни
    одной ссылки.
    """
    row = _V4_REPORT_DEFAULT_ROW
    unpaid = "+".join(f"'CF_{phase}'!$B${_V4_RVE_UNPAID_ROW}" for phase in range(1, 5))
    passed = "+".join(f"'CF_{phase}'!$B${_V4_CARRY_PASSED_ROW}" for phase in range(1, 5))
    for coord, kwargs in (
            (f"A{row}", {"text": "Не погашено в дату раскрытия эскроу и не передано "
                                 "следующей очереди (дефолт по линии, если > 0)"}),
            (f"B{row}", {"formula": f"MAX(0,({unpaid})-({passed}))"})):
        # Занятая ячейка значит, что шаблон изменился: писать поверх молча
        # нельзя — так теряется то, что там стояло.
        existing = re.search(
            r'<x:c r="%s"[^>]*?(?:/>|>(.*?)</x:c>)' % re.escape(coord), xml, re.S)
        if existing and (existing.group(1) or ""):
            missing.append(f"ОТЧЁТ: ячейка {coord} занята")
            continue
        xml, done = _v4_set_cell(xml, coord, **kwargs)
        if not done:
            missing.append(f"ОТЧЁТ: ячейка {coord} не найдена")
    return xml


_V4_REPORT_NET_PROFIT_ROW = 12       # ОТЧЕТ: «Чистая прибыль»
_V4_CF_VAT_ROW = 21                  # CF очереди: НДС к уплате


def _v4_report_net_profit_from_its_own_rows(xml: str, missing: list[str]) -> str:
    """Чистая прибыль считается из строк ТОГО ЖЕ листа, а не из чужого блока.

    В шаблоне `ОТЧЕТ!B12` читает `КОНСОЛИДАТОР!L8` — там чистая собирается по
    очередям, и из каждой вычитается её доля налога (`K4:K7 = K8 × доля`). У
    владельца Excel посчитал эти доли нулями, и налог не вычелся ни у одной
    очереди: на экране стояло 56 598,6 вместо 42 128,6 — ровно на налог
    14 470,0 больше (14.09.2026). Наш вычислитель на том же файле давал верное
    число, то есть расхождение живёт между Excel и цепочкой раздачи, а не в
    методике, и искать в ней виноватую ячейку нечем: формулы там законные.

    Лечится тем, что **величину, которую читает человек, собирают из величин
    рядом с ней**: прибыль до налога (B10) минус налог (B11) минус НДС. Обе
    строки Excel считает верно — это видно на том же экране, — и потерять
    налог по дороге больше негде.

    НДС стоит внутри формулы, а не своей строкой: свободной строки на листе
    нет, а вставить её значит сдвинуть все ссылки. Поэтому лист по-прежнему не
    складывается глазами (B10 − B11 ≠ B12) — это отдельная правка, и она про
    вёрстку, а не про число.

    Раздача налога по очередям остаётся там, где ей место, — в таблице
    сравнения очередей.
    """
    row = _V4_REPORT_NET_PROFIT_ROW
    before = re.search(r'<x:c r="B%d"[^>]*>(.*?)</x:c>' % row, xml, re.S)
    if not before or "КОНСОЛИДАТОР" not in (before.group(1) or ""):
        # Формула шаблона не опознана — значит лист другой, и писать поверх
        # нельзя: расхождение уходит в missing, а не проходит молча.
        missing.append(f"ОТЧЁТ: формула чистой прибыли в B{row} не опознана")
        return xml
    vat = "+".join(f"'CF_{phase}'!$B${_V4_CF_VAT_ROW}" for phase in range(1, 5))
    xml, done = _v4_set_cell(
        xml, f"B{row}", formula=f"B{row - 2}-B{row - 1}-({vat})")
    if not done:
        missing.append(f"ОТЧЁТ: ячейка B{row} не найдена")
    return xml


def _v4_relax_limit_check_for_carried_debt(xml: str, missing: list[str]) -> str:
    """Проверка 72 книги не знает, что принятый долг лимита не выбирает.

    Лимит покрывает только тело, выбранное этой очередью; долг, переоформленный
    с предыдущей, приходит на линию, не выбирая лимита (решение владельца,
    27.08.2026). Проверка сравнивала пик ПФ с лимитом как есть и на любом
    проекте с переносом кричала «превышение», которого по методике нет.
    Кричащая зря проверка хуже отсутствующей: её перестают читать.
    """
    row = 72
    found = re.search(r'<x:c r="B%d"[^>]*>(.*?)</x:c>' % row, xml, re.S)
    if not found:
        missing.append(f"ПРОВЕРКИ: ячейка B{row} не найдена")
        return xml
    body = found.group(1)
    changed = body
    for phase in range(1, 5):
        old = f"'CF_{phase}'!B83-"
        new = f"'CF_{phase}'!B83-'CF_{phase}'!$B${_V4_CARRY_ACCEPTED_ROW}-"
        if old not in changed:
            missing.append(f"ПРОВЕРКИ: формула B{row} не опознана (очередь {phase})")
            return xml
        changed = changed.replace(old, new, 1)
    return xml[:found.start(1)] + changed + xml[found.end(1):]


# Строка-гейт паритета: правил ли человек вводные после сборки книги.
_V4_PARITY_GATE_ROW = 75
# Ссылка на ЛИСТ ВВОДА из чужого листа едет меткой. При записи в архив каждый
# лист проходит переименование «Вводные» → «Параметры модели», и написанная
# прямо ссылка уехала бы на расчётный лист — туда, где формулы читают CAPEX и
# CF, то есть отпечаток вводных двигался бы от расхождения, которое он обязан
# показывать.
_V4_ENTRY_SHEET_TOKEN = "'__ЛИСТ-ВВОДА__'!"


def _v4_parity_verdict(row: int) -> str:
    """Вердикт строки паритета — объявлен один раз на все строки блока.

    Ответов три, и третий появился не для красоты. Цель в колонке C — это
    значение движка на дату сборки, а книга считает сама, и правка вводной в
    ней законна: «эксель должен работать почти как движок, если что-то
    меняешь где-то, всё должно меняться так же» (владелец, 03.09.2026).
    Измерено: подними цену квартир на 10% прямо в книге — она пересчитается
    верно, а ВОСЕМЬ строк паритета из одиннадцати покраснеют, потому что цель
    осталась прежней. Кричащая зря проверка хуже отсутствующей: её перестают
    читать, — а читать её надо, именно эти строки нашли и забытую статью
    сноса, и базу НДС, и паркинг офисника.

    Гейт снимает вердикт только явным «WARN»: не собрался лист ввода, не
    записался отпечаток — и строка ведёт себя как прежде. Отказ гейта обязан
    возвращать проверку, а не выключать её.
    """
    gate = _V4_PARITY_GATE_ROW
    return (f'IF(C{row}="","",IF($F${gate}="WARN",'
            f'"вводные правлены — сверять не с чем",'
            f'IF(ABS(D{row})<=E{row},"OK","FAIL")))')


def _v4_entry_fingerprint(entry_xml: str) -> float:
    """Отпечаток листа ввода: сумма всех его чисел.

    Считается ровно то, что считает `SUM` по всему листу в самой книге:
    числовые ячейки, без подписей и без формул — формул на листе ввода нет
    ни одной, он чистый ввод человека. Поэтому отпечаток не зависит от
    расчёта книги и не может замолчать расхождение, ради показа которого
    строки паритета и стоят.

    Отбрасывается ТЕКСТ, а не всякий объявленный тип: у числа тип бывает
    написан явно (`t="n"`), и запрет по одному наличию `t=` выкидывал
    четырнадцать живых чисел, а даты (они без типа) при этом считал только
    отпечаток — три разных суммы на одну книгу, и гейт кричал на
    свежесобранной. Текст, логическое и ошибку Excel в диапазоне
    пропускает — их и пропускаем.
    """
    total = 0.0
    for match in re.finditer(
            r"<x:c(?P<attrs>\s[^>]*?)?>(?P<body>(?:(?!</x:c>).)*)</x:c>",
            entry_xml, re.S):
        attrs = match.group("attrs") or ""
        body = match.group("body") or ""
        kind = re.search(r'\st="([^"]*)"', attrs)
        if "<x:f" in body or (kind and kind.group(1) != "n"):
            continue
        value = re.search(r"<x:v>([^<]*)</x:v>", body)
        if not value:
            continue
        try:
            total += float(value.group(1))
        except ValueError:
            continue
    return total


def _v4_add_parity_gate_row(xml: str, missing: list[str]) -> str:
    """Строка «вводные не менялись с даты сборки» над блоком паритета.

    Отпечаток дописывается позже — когда лист ввода собран, — поэтому цель
    здесь пустая: пустая цель гасит и саму строку, и гейт, то есть паритет
    остаётся таким, каким был до этой правки.
    """
    row = _V4_PARITY_GATE_ROW
    body = (
        f'<x:c r="A{row}" t="inlineStr"><x:is><x:t>'
        + xml_escape("Лист ввода не менялся с даты сборки")
        + "</x:t></x:is></x:c>"
        + f'<x:c r="B{row}"><x:f>'
        + xml_escape(f"ROUND(SUM({_V4_ENTRY_SHEET_TOKEN}$A$1:$BZ$1000),6)")
        + "</x:f></x:c>"
        + f'<x:c r="C{row}"/>'
        + f'<x:c r="D{row}"><x:f>IF(C{row}="","",B{row}-C{row})</x:f></x:c>'
        + f'<x:c r="E{row}"><x:v>0.001</x:v></x:c>'
        + f'<x:c r="F{row}"><x:f>'
        + xml_escape(f'IF(C{row}="","",IF(ABS(D{row})<=E{row},"OK","WARN"))')
        + "</x:f></x:c>")
    updated, done = _v4_insert_row(xml, row, body, row + 1)
    if not done:
        missing.append(f"гейт паритета: строка {row} ПРОВЕРОК занята")
        return xml
    return updated


# Доля допуска строк паритета. Была одна на все — полпроцента, — и это
# измерено, а не выбрано: на десяти формах проекта (одиночный, дорогой вход,
# рассрочка ВРИ, ступени ставки, лестница цены, одобренный лимит, объекты, три
# и четыре очереди, перенос долга) выручка, CAPEX, EBITDA, НДС, пики БРИДЖа и
# ПФ, переданный долг и непокрытая потребность расходятся не более чем на
# 0,003% — это округление. Полпроцента на них — запас в полтораста раз: на
# проекте в сорок миллиардов допуск CAPEX выходил 188 млн ₽ при фактическом
# расхождении в 50 тыс.
#
# Исключение ровно одно и названо: стоимость финансирования. У неё расхождение
# НАСТОЯЩЕЕ — 0,21–0,42% на тех же десяти формах, то есть до 84% собственного
# допуска, — и сидит оно в капитализированных процентах (302,1 млн у книги
# против 311,3 у движка на проверочном проекте, при совпадении всех четырёх
# слагаемых до шести знаков). Ужать её допуск значит покрасить книгу красным у
# каждого, кто её скачает; причина не найдена и стоит в задачах. Налог и чистая
# прибыль — производные от неё, и их допуск считается от слагаемых ниже.
_V4_PARITY_SHARE_DEFAULT = 0.0005
_V4_PARITY_SHARE = {"financing_mln": 0.005}
# LLCR — абсолютный допуск: доля от 1,1x ничего не значит. Худшее измеренное
# расхождение на тех же формах — 0,00056, запас девятикратный.
_V4_PARITY_LLCR_TOLERANCE = 0.005


def _v4_add_parity_row(xml: str, row: int, label: str, total: str,
                       target_mln: float, missing: list[str], what: str) -> str:
    """Ещё одна строка паритета в свободный низ листа ПРОВЕРКИ.

    Две таких строки были написаны копией, и различались они только подписью и
    формулой: вторая копия однажды забыла бы расширить вердикт B3 на свою же
    строку — она красная, а лист «ПРОЙДЕНО». Допуск считается той же мерой,
    что у строк блока выше.
    """
    tolerance = max(1.0, abs(target_mln) * _V4_PARITY_SHARE_DEFAULT)
    body = (
        f'<x:c r="A{row}" t="inlineStr"><x:is><x:t>{xml_escape(label)}'
        f'</x:t></x:is></x:c>'
        f'<x:c r="B{row}"><x:f>{total}</x:f></x:c>'
        f'<x:c r="C{row}"><x:v>{_v4_number(round(target_mln, 4))}</x:v></x:c>'
        f'<x:c r="D{row}"><x:f>IF(C{row}="","",B{row}-C{row})</x:f></x:c>'
        f'<x:c r="E{row}"><x:v>{_v4_number(round(tolerance, 4))}</x:v></x:c>'
        f'<x:c r="F{row}"><x:f>{xml_escape(_v4_parity_verdict(row))}</x:f>'
        f'</x:c>')
    updated, done = _v4_insert_row(xml, row, body, None)
    if not done:
        missing.append(f"{what}: строка {row} ПРОВЕРОК занята")
        return xml
    # Вердикт листа считает по диапазону — новая строка обязана в него войти,
    # иначе она красная, а лист «ПРОЙДЕНО».
    before = updated
    updated = re.sub(r"COUNTIF\(F6:F\d+,", f"COUNTIF(F6:F{row},", updated)
    if updated == before:
        missing.append(f"{what}: вердикт B3 не расширен на строку {row}")
    return updated


def _v4_object_phase_by_result(phases: list[dict[str, Any]]) -> dict[str, int]:
    """В какой очереди движок ПОСТРОИЛ каждый отдельно стоящий объект.

    Читается результат, а не правила: очередь, в чьих вводных объект ВКЛЮЧЁН,
    и есть его очередь — это то, что движок применил, разложив проект. Повторять
    здесь лестницу приоритета нельзя: это был бы третий ответ на вопрос, у
    которого уже два.

    Первая версия смотрела на строку ТЭП очереди и ошибалась молча: площадь
    объекта движок читает из `offices_gba_sqm`, а строка ТЭП при этом может
    быть нулевой — так устроены умолчания, и на них объект «нигде не построен»
    при живых 10 000 м² и 2 519 млн ₽ CAPEX в четвёртой очереди. Признак
    включения верен и для ПЕРЕДАННОГО городу объекта, у которого ни выручки,
    ни своего пула расходов нет вовсе.

    Объект, не включённый ни в одной очереди, в ответ не попадает: пустое
    значит «движок его не строил», и книга останется на своём умолчании, а не
    получит выдуманную единицу.
    """
    out: dict[str, int] = {}
    for index, phase in enumerate(phases or []):
        phase_inputs = (phase or {}).get("inputs") or {}
        for obj in standalone_objects():
            if obj.key in out:
                continue
            if bool(phase_inputs.get(f"{obj.prefix}_enabled")):
                out[obj.key] = index + 1
    return out


def _v4_add_carry_parity_row(xml: str, target_mln: float, missing: list[str]) -> str:
    """Строка паритета «долг, переданный между очередями» на листе ПРОВЕРКИ.

    Без неё книга могла бы переносить не то и не тогда, а вердикт листа остался
    бы «ПРОЙДЕНО»: остальные строки паритета смотрят на итоги, а перенос между
    очередями итоги проекта почти не двигает — он меняет, КТО платит.
    """
    return _v4_add_parity_row(
        xml, _V4_CARRY_PARITY_ROW, "Паритет: долг, переданный между очередями, млн",
        "+".join(f"'CF_{phase}'!$B${_V4_CARRY_PASSED_ROW}" for phase in range(1, 5)),
        target_mln, missing, "паритет переноса долга")


def _v4_add_vat_parity_row(xml: str, target_mln: float, missing: list[str]) -> str:
    """Строка паритета НДС.

    Своей строки у НДС не было, и проверялся он только внутри чистой прибыли —
    вместе с EBITDA и стоимостью финансирования, у которых допуск считается
    долей от их собственной величины. На проекте с околонулевой прибылью это
    поймало настоящую ошибку (движок не облагал выручку паркинга отдельно
    стоящих объектов — 166,0 млн выручки и 4,7 млн налога), но узнать, что дело
    в НДС, было нельзя: строка называла прибыль. Теперь величина проверяется
    там, где она считается, а прибыль отвечает за себя.
    """
    return _v4_add_parity_row(
        xml, _V4_VAT_PARITY_ROW, "Паритет: НДС к уплате, млн",
        "+".join(f"'CF_{phase}'!$B$21" for phase in range(1, 5)),
        target_mln, missing, "паритет НДС")


def _v4_teach_funding_check_about_the_limit(
    xml: str, missing: list[str]) -> str:
    """Строка 32 ПРОВЕРОК: «потребность профинансирована банком полностью».

    Проверка была написана тогда, когда выборка равнялась потребности ВСЕГДА
    — потолка у книги не существовало, — и «не сошлось» могло означать ровно
    одно: сломалась арифметика. Отсюда FAIL и «СБОЙ» на весь лист.

    С одобренным лимитом разрыв стал законным: банк дал меньше, чем нужно, и
    это факт о ПРОЕКТЕ, а не о книге. FAIL здесь — та самая кричащая зря
    проверка, которую перестают читать: она загоралась бы у каждого, кто
    впишет настоящий лимит из term sheet. Разрыв без заданного лимита
    по-прежнему FAIL: объяснить его нечем.

    Заодно факт берётся из строк, которые эту дыру и считают
    (`_V4_PF_UNCOVERED_ROW` листов CF), а не вторым таким же вычитанием:
    двух ответов на «сколько не покрыто» в одной книге быть не должно.
    """
    row = 32
    facts = ",".join(f"'CF_{phase}'!$B${_V4_PF_UNCOVERED_ROW}"
                     for phase in range(1, 5))
    edits = (
        ("B", "SUM('CF_1'!D44:", f"SUM({facts})"),
        # Метка — начало формулы шаблона: полный текст с прежним вердиктом
        # здесь не пишется, вердикт паритета собирает один _v4_parity_verdict.
        ("F", 'IF(B32&lt;=C32+E32,"OK",',
         'IF(B32&lt;=C32+E32,"OK",'
         "IF(OR(" + ",".join(
             [f"'Вводные'!${_V4_PF_APPROVED_CELL[0]}${_V4_PF_APPROVED_CELL[1:]}&gt;0"]
             + [f"'Вводные'!${_V4_PF_QUEUE_INDIVIDUAL_COL}${_V4_CF_QUEUE_ENABLED_ROW + k}&gt;0"
                for k in range(4)]) + '),"WARN","FAIL"))'),
    )
    for column, mark, replacement in edits:
        found = re.search(r'<x:c r="%s%d"[^>]*>\s*<x:f>(.*?)</x:f>' % (column, row),
                          xml, re.S)
        if not found:
            missing.append(f"ПРОВЕРКИ: формулы {column}{row} нет")
            return xml
        if mark not in found.group(1):
            missing.append(f"ПРОВЕРКИ: формула {column}{row} не опознана")
            return xml
        xml = xml[:found.start(1)] + replacement + xml[found.end(1):]
    # Подпись обязана объяснить WARN: «не профинансирована полностью» без
    # причины читается как поломка книги. Ячейка подписи живёт ОБЩЕЙ СТРОКОЙ
    # (t="s" с номером в таблице строк), поэтому правится не её тело, а она
    # сама — на inlineStr, как у дописанных строк паритета. Стиль остаётся
    # свой: чужая краска в середине блока читалась бы как чужая вставка.
    label = re.search(r'<x:c r="A%d"(?P<attrs>[^>]*?)(?:/>|>.*?</x:c>)' % row,
                      xml, re.S)
    if not label:
        missing.append(f"ПРОВЕРКИ: подписи A{row} нет")
        return xml
    style = re.search(r'\ss="\d+"', label.group("attrs"))
    text = xml_escape(
        "Потребность в долге профинансирована банком полностью "
        "(WARN — не хватило ОДОБРЕННОГО лимита ПФ, см. строку "
        f"{_V4_PF_UNCOVERED_ROW} листов CF)")
    cell = (f'<x:c r="A{row}"{style.group(0) if style else ""} t="inlineStr">'
            f"<x:is><x:t>{text}</x:t></x:is></x:c>")
    return xml[:label.start()] + cell + xml[label.end():]


def _v4_add_pf_uncovered_parity_row(
    xml: str, target_mln: float, missing: list[str]) -> str:
    """Строка паритета: непокрытая потребность в ПФ.

    Пока книга не знала об одобренном лимите, сверять было нечего — у неё
    дыры не бывало по построению. Теперь бывает, и она обязана совпасть с
    движковой: иначе «потолок в книге есть» значит только, что он есть.
    """
    return _v4_add_parity_row(
        xml, _V4_PF_UNCOVERED_PARITY_ROW,
        "Паритет: непокрытая потребность в ПФ, млн",
        "+".join(f"'CF_{phase}'!$B${_V4_PF_UNCOVERED_ROW}" for phase in range(1, 5)),
        target_mln, missing, "паритет непокрытой потребности")


def _v4_parity_targets(consolidated: dict[str, Any]) -> dict[str, float]:
    """Контрольные числа движка для parity-блока листа ПРОВЕРКИ."""
    summary = consolidated.get("summary") or {}
    finance = consolidated.get("finance") or {}
    return {
        "revenue_mln": float(summary.get("revenue") or 0) / 1e6,
        "capex_mln": float(summary.get("capex") or 0) / 1e6,
        "ebitda_mln": float(summary.get("ebitda") or 0) / 1e6,
        "financing_mln": float(summary.get("financing_cost") or 0) / 1e6,
        "tax_mln": float(summary.get("profit_tax") or 0) / 1e6,
        "net_profit_mln": float(summary.get("net_profit") or 0) / 1e6,
        "vat_mln": float(finance.get("vat") or 0) / 1e6,
        "llcr": float(summary.get("llcr") or 0),
        "peak_bridge_mln": float(finance.get("peak_bridge") or 0) / 1e6,
        "peak_pf_mln": float(finance.get("peak_pf") or 0) / 1e6,
        "pf_shortfall_mln": float(finance.get("pf_shortfall") or 0) / 1e6,
    }


def _calculation_fingerprint(
    inputs: dict[str, Any] | None,
    tep: dict[str, Any] | None,
    phasing: dict[str, Any] | None,
) -> str:
    """Отпечаток вводных: один расчёт — один идентификатор в PDF и книге.

    Сверка пары «PDF + книга» начинается с вопроса, один ли это расчёт;
    без отпечатка его выясняли, сравнивая цифры и споря о версиях.

    Считается по ЭФФЕКТИВНЫМ вводным — тем, на которых движок и посчитал:
    умолчания подмешаны, ТЭП слит построчно. Прежде каждая поверхность
    считала отпечаток по тому, что было у неё под рукой: книга — по слитым
    (выгрузка подмешивает `DEFAULT_INPUTS` первой строкой), PDF —
    по сырым, как их прислала страница. Один и тот же расчёт получал два
    разных номера ВСЕГДА, и инструмент, заведённый доказывать тождество,
    доказывал обратное — на нём владельцу уже был дан неверный ответ
    «это разные прогоны» (25.08.2026).

    Отсюда правило: нормализация живёт ЗДЕСЬ, а не у звонящего. Иначе
    появится третья поверхность со своим набором под рукой и своим номером."""
    merged_inputs = {**copy.deepcopy(DEFAULT_INPUTS), **(inputs or {})}
    merged_tep = copy.deepcopy(TEP_DEFAULT)
    for key, values in (tep or {}).items():
        if isinstance(values, dict) and key in merged_tep:
            merged_tep[key].update(values)
        else:
            merged_tep[key] = values
    payload = json.dumps(
        {
            "inputs": {k: v for k, v in sorted(merged_inputs.items())
                       if not str(k).startswith("_")},
            "tep": merged_tep,
            "phasing": phasing or {},
        },
        ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:12]


def presentation_numbers(consolidated: dict[str, Any]) -> dict[str, Any]:
    """Величины модели представления в миллионах и долях — считает движок.

    Слой представления (`presentation.py`) сам не делит и не складывает:
    единицы приводятся здесь, там же, где считаются цели паритета книги
    (`_v4_parity_targets`) — иначе тизер и паритет приводили бы одну величину
    к миллионам двумя копиями.
    """
    numbers = dict(_v4_parity_targets(consolidated))
    summary = consolidated.get("summary") or {}
    finance = consolidated.get("finance") or {}
    report = consolidated.get("report") or {}
    vri_totals = (consolidated.get("vri") or {}).get("totals") or {}
    tep_total = (consolidated.get("tep") or {}).get("total") or {}
    # Машино-места проекта считаются один раз и одним правилом: подземные,
    # наземные и гаражи объектов. Выражение, повторённое трижды внутри
    # словаря, читалось бы хуже и однажды разошлось бы само с собой.
    _parking_block = consolidated.get("parking") or {}
    _parking_built = tep_parking_spaces((consolidated.get("tep") or {}).get("rows") or [])
    _parking_provision = (_parking_block.get("provision")
                          or parking_provision(_parking_built, _parking_block.get("project_required")))
    apartment_sales = report.get("apartment_sales") or {}
    apartments = next((p for p in (report.get("products") or [])
                       if str(p.get("key")) == "apartments"), {})
    numbers.update({
        "margin": float(summary.get("margin") or 0.0),
        # NPV и IRR снимает движок при непогашенном долге: None и подпись
        # причины, а не ноль.
        # Подпись строки — «NPV собственного капитала», и считается он по
        # потоку капитала, как у книги (`_equity_npv`), а не по потоку проекта.
        "npv_mln": (None if summary.get("npv_equity") is None
                    else float(summary.get("npv_equity")) / 1e6),
        "equity_returns_na": equity_returns_na_label(summary),
        "commercial_mln": float(summary.get("commercial_costs") or 0.0) / 1e6,
        "rve_unpaid_mln": float(finance.get("rve_unpaid") or 0.0) / 1e6,
        "ending_pf_mln": float(summary.get("ending_pf") or 0.0) / 1e6,
        "term_months": _months_between(
            str((consolidated.get("dates") or {}).get("project_start") or ""),
            str((consolidated.get("dates") or {}).get("rve") or "")),
        "products": {
            str(item.get("key")): _presentation_product_numbers(item)
            for item in (report.get("products") or [])
        },
        # Строки удельной экономики и себестоимости — те же, что в полном PDF
        # и книге, только итог приведён к миллионам; ставки на метр приходят
        # готовыми парами (`per_base_th` со своей базой / `per_saleable_th`).
        "unit_economics": _presentation_rows_mln(report.get("unit_economics"), "total"),
        "construction_costs": _presentation_rows_mln(report.get("construction_costs"), "value"),
        "expense_structure": _presentation_rows_mln(report.get("expense_structure"), "value"),
        "financing": {
            "bridge_interest_mln": float(finance.get("bridge_interest") or 0.0) / 1e6,
            "bridge_fee_mln": float(finance.get("bridge_fee") or 0.0) / 1e6,
            "pf_interest_mln": float(finance.get("pf_interest") or 0.0) / 1e6,
            "pf_limit_fee_mln": float(finance.get("pf_limit_fee") or 0.0) / 1e6,
            "pf_reservation_fee_mln": float(finance.get("pf_reservation_fee") or 0.0) / 1e6,
            "pf_limit_required_mln": float(finance.get("pf_limit_required") or 0.0) / 1e6,
            "pf_limit_mln": float(finance.get("pf_limit") or 0.0) / 1e6,
            "pf_limit_approved_mln": float(finance.get("pf_limit_approved") or 0.0) / 1e6,
            "own_funds_mln": float(finance.get("own_funds_used") or 0.0) / 1e6,
            "peak_uncovered_pf_mln": float(finance.get("peak_uncovered_pf") or 0.0) / 1e6,
            "peak_escrow_mln": float(finance.get("peak_escrow") or 0.0) / 1e6,
            "rve_escrow_release_mln": float(finance.get("rve_escrow_release") or 0.0) / 1e6,
            "interest_and_fees_mln": float(finance.get("reported_interest_and_fees")
                                           or finance.get("financing_cost") or 0.0) / 1e6,
            "avg_pf_effective_rate": float(finance.get("avg_pf_effective_rate") or 0.0),
            "avg_bridge_rate": float(finance.get("avg_bridge_rate") or 0.0),
            "current_key_rate": float(finance.get("current_key_rate") or 0.0),
            "bridge_spread": float(finance.get("bridge_spread") or 0.0),
            "pf_special_rate": float(finance.get("pf_special_rate") or 0.0),
        },
        "taxes": {
            "profit_before_tax_mln": float(summary.get("profit_before_tax") or 0.0) / 1e6,
            "profit_tax_rate": float(summary.get("profit_tax_rate") or 0.0),
        },
        "efficiency": {
            "irr_equity": (None if summary.get("irr_equity") is None
                           else float(summary.get("irr_equity"))),
            "full_project_cost_mln": float(summary.get("full_project_cost") or 0.0) / 1e6,
            "commercial_mln": float(summary.get("commercial_costs") or 0.0) / 1e6,
        },
        # Построенные МАШИНО-МЕСТА, а не все штуки проекта. Здесь стоял общий
        # итог штук, и в обеспеченность парковкой шли квартиры и места
        # детского сада: 2 811 вместо 1 199 на умолчаниях, обеспеченность
        # 28,98 вместо 12,36. Мера счёта у продуктов разная, и складывать их
        # было нечем — «конечно это не надо суммировать» (владелец,
        # 27.09.2026).
        #
        # Знаменатель — вся нормативная потребность проекта, а не приобъектные
        # места одной коммерции: 1 199 мест гаража делились на 97 мест
        # встроенных магазинов, и выходило 12,36× (#656). Делит один владелец
        # (`parking_provision`), поверхности читают готовый ответ и подпись.
        "parking": {
            "required_total": _parking_provision["required"],
            "required_attached": float(_parking_block.get("required_total") or 0.0),
            "required_parts": list((_parking_block.get("project_required") or {}).get("parts") or []),
            "required_missing": list((_parking_block.get("project_required") or {}).get("missing") or []),
            "built_units": _parking_built,
            "provision": _parking_provision["ratio"],
            "provision_label": _parking_provision["label"],
        },
        "land": {
            "purchase_per_saleable_th": (
                float((report.get("purchase") or {}).get("total_mln") or 0.0) * 1e3
                / float(summary.get("monetizable_saleable_sqm") or 0.0)
                if float(summary.get("monetizable_saleable_sqm") or 0.0) > 0 else None),
            "social_payment_mln": float(summary.get("social_payment") or 0.0) / 1e6,
            "social_payment_mode": str(summary.get("social_payment_mode") or ""),
            "land_rights_mln": float((consolidated.get("capex") or {}).get("land_rights") or 0.0) / 1e6,
            "vri_amount_mln": float(vri_totals.get("amount") or 0.0) / 1e6,
            "vri_relief_mln": float(vri_totals.get("relief") or 0.0) / 1e6,
            "vri_interest_mln": float(vri_totals.get("interest") or 0.0) / 1e6,
            "purchase_mln": float((report.get("purchase") or {}).get("total_mln") or 0.0),
        },
        "sales": {
            "apartment_pace_sqm_month": float(apartments.get("pace_pre") or 0.0),
            "apartment_pace_sqm_year": float(apartments.get("pace_pre") or 0.0) * 12.0,
            "apartment_share_before_rve": float(apartments.get("share_before_rve") or 0.0),
            "avg_unit_sqm": float(apartment_sales.get("avg_unit_sqm") or 0.0),
            "avg_unit_price_mln": float(apartment_sales.get("avg_unit_price_mln") or 0.0),
            "units_total": float(apartment_sales.get("units_total") or 0.0),
        },
        # Ряд для графика «кредит и эскроу»: месяц, тела долга и счёт эскроу
        # в миллионах — рисуют его тизер и дашборд, а считает движок.
        "chart_rows": [
            {"month": str(row.get("month") or ""),
             "bridge_mln": float(row.get("bridge_balance") or 0.0) / 1e6,
             "pf_mln": float(row.get("pf_balance") or 0.0) / 1e6,
             "escrow_mln": float(row.get("escrow") or 0.0) / 1e6}
            for row in (finance.get("rows") or [])
        ],
    })
    return numbers


def _presentation_product_numbers(item: dict[str, Any]) -> dict[str, Any]:
    """Продукт в миллионах и ставках на метр — считается здесь, не в слое представления.

    Метровый продукт меряется ГНС и продаваемой (руб./м² GBA и GSA у образца
    владельца), штучный — единицами: у машино-места деление на его метры
    дало бы число, не сравнимое ни с чем.
    """
    revenue = float(item.get("revenue") or 0.0)
    cost = float(item.get("cost") or 0.0)
    saleable = float(item.get("saleable") or 0.0)
    quantity = float(item.get("quantity") or 0.0)
    by_units = str(item.get("unit") or "") == "шт."
    return {
        # Есть ли продукт в проекте — решает движок (`row_listed`), а слой
        # представления только отбирает: тизер печатал все продукты отчёта,
        # и кладовые 0 и удалённые «Офисы 2…5» стояли в его ТЭП.
        "listed": row_listed(item),
        "revenue_mln": revenue / 1e6,
        "cost_mln": cost / 1e6,
        # Выручка и цена — на продаваемую площадь (решение 4 ревизии книги):
        # на ГНС продукта цену не делят.
        "per_saleable_th": (revenue / saleable / 1e3) if (saleable > 0 and not by_units) else None,
        "per_unit_th": (revenue / quantity / 1e3) if (quantity > 0 and by_units) else None,
        "pace_year": float(item.get("pace_pre") or 0.0) * 12.0,
    }


def _presentation_rows_mln(rows: Any, total_key: str) -> list[dict[str, Any]]:
    """Строки отчёта с итогом в миллионах; ставки на метр — как пришли."""
    out: list[dict[str, Any]] = []
    for item in rows or []:
        out.append({
            "key": str(item.get("key") or "") or None,
            "label": str(item.get("label") or ""),
            "total_mln": float(item.get(total_key) or 0.0) / 1e6,
            # Удельное на свою базу и его подпись — как их решил движок.
            "base": str(item.get("base") or "") or None,
            "base_label": str(item.get("base_label") or "") or None,
            "per_base_th": (None if item.get("per_base_th") is None else float(item.get("per_base_th"))),
            "per_saleable_th": (None if item.get("per_saleable_th") is None
                                else float(item.get("per_saleable_th"))),
            "share": (None if item.get("share") is None else float(item.get("share"))),
        })
    return out


def _months_between(start: str, end: str) -> float | None:
    """Месяцы между двумя датами ISO — как их считает книга: по годам и месяцам."""
    try:
        a, b = date.fromisoformat(start[:10]), date.fromisoformat(end[:10])
    except (TypeError, ValueError):
        return None
    return float((b.year - a.year) * 12 + (b.month - a.month))


def project_presentation(bundle: dict[str, Any], inputs: dict[str, Any],
                         tep: dict[str, Any], phasing: dict[str, Any] | None,
                         site: dict[str, Any] | None = None) -> dict[str, Any]:
    """Модель представления одного расчёта — для тизера и любой поверхности,
    которой нужны те же шесть карточек, что у дашборда книги.

    `site` — участок, о котором посчитано: кадастровые номера и адрес, как их
    прислала страница. Движок их не знает — они не вводные расчёта."""
    consolidated = bundle.get("consolidated") or {}
    origin = presentation_origin(inputs, tep, phasing)
    numbers = presentation_numbers(consolidated)
    # Цена входа — вводная проекта: у свода очередей блока покупки в отчёте
    # нет, а цена одна на проект и делится по очередям кассовыми долями.
    land = numbers.setdefault("land", {})
    price_mln = float((inputs or {}).get("purchase_price_mln") or 0.0)
    if not land.get("purchase_mln") and price_mln > 0:
        land["purchase_mln"] = price_mln
        saleable = float((((consolidated.get("tep") or {}).get("total") or {}).get("saleable")) or 0.0)
        land["purchase_per_saleable_th"] = (price_mln * 1e3 / saleable) if saleable > 0 else None
    # Карточки читают вводные (места ДОО и СОШ, признак ВРИ) — те же, что
    # посчитал движок: у нежилого проекта сырые назвали бы садик, которого
    # он не строит.
    counted_inputs = residential_excluded(inputs or {}, {})[0]
    return _presentation.build_project_presentation(
        numbers, consolidated, list(bundle.get("phases") or []),
        counted_inputs, origin, _AGENT_BANK_LLCR_TARGET, site=site or {})


def presentation_origin(inputs: dict[str, Any], tep: dict[str, Any],
                        phasing: dict[str, Any] | None) -> dict[str, str]:
    """Происхождение расчёта — одно на книгу и тизер: отпечаток вводных,
    версия движка, время сборки."""
    calculation_id = _calculation_fingerprint(inputs, tep, phasing)
    return {
        "calculation_id": calculation_id,
        "inputs_fingerprint": calculation_id,
        "engine_version": VERSION,
        "generated_at": datetime.now().strftime("%d.%m.%Y %H:%M"),
        "template": "DevelopAid_model_v4",
    }


def _v4_fold_tep_rows(
    rows: list[dict[str, dict[str, Any]]], book: int
) -> list[dict[str, dict[str, Any]]]:
    """Очередей больше, чем листов CF в книге: объёмы хвоста складываются в
    последнюю книжную очередь — та же логика, что у долей в _v4_fold_tail."""
    if len(rows) <= book:
        return rows
    merged: dict[str, dict[str, Any]] = {}
    for tail_row in rows[book - 1:]:
        for key, product in tail_row.items():
            if key not in merged:
                merged[key] = copy.deepcopy(product)
            else:
                for field in ("gns", "total_area", "useful", "saleable", "transfer", "units"):
                    merged[key][field] = (
                        float(merged[key].get(field) or 0) + float(product.get(field) or 0))
    return rows[:book - 1] + [merged]


def phase_cash_default_weights(count: int) -> dict[str, list[float]]:
    """Кассовые доли общепроектных статей по умолчанию — один раз на движок и книгу.

    Копия этих умолчаний жила в книге и говорила другое: `_v4_shared_weights`
    при пустом `shared_cash` валила ВСЕ статьи на первую очередь, а движок
    раскладывал ИРД, проектирование, подготовку и сети по весам очередей.
    Страница долю всегда присылает, поэтому в жизни расхождение не всплывало,
    а через API — на двухочередном проекте это 686 млн ₽ разницы в пике
    БРИДЖа между отчётом и книгой, оба достоверные на вид. Тот же класс
    ошибки, что копия `FIELD_GROUPS` на странице: умолчание, объявленное
    дважды, однажды разойдётся.
    """
    count = max(1, int(count))
    weights = _default_phase_weights(count)
    first_only = [100.0] + [0.0] * (count - 1)
    return {
        "purchase": list(first_only),
        "land_rights": list(first_only),
        "ird": list(weights),
        "design": list(weights),
        "preparation": list(weights),
        "utilities": list(weights),
        # Снос и расселение идут до РнС вместе с подготовкой и делятся между
        # очередями так же: прежде каждая очередь платила их ЦЕЛИКОМ — вводная
        # копировалась в каждую без деления, и четыре очереди сносили одно и
        # то же четыре раза.
        "demolition": list(weights),
        "resettlement": list(weights),
        "social_compensation": list(first_only),
        # Свои деньги вкладывают на входе, поэтому по умолчанию они целиком в
        # первой очереди. Иное распределение задаётся shared_cash.own_funds.
        "own_funds": list(first_only),
    }


def _v4_shared_weights(
    phasing: dict[str, Any], key: str, count: int, enabled: int | None = None
) -> list[float]:
    # Доли P/Q/R в книге — кассовый график платежа, поэтому источником служат
    # кассовые доли движка (shared_cash), а не экономическая аллокация
    # (shared_allocation): с аллокацией книга платила ВРИ тремя кусками перед
    # РнС каждой очереди, а движок — целиком перед первым РнС. Дефолт движка
    # тот же: покупка, ВРИ и соцкомпенсация кассово в первой очереди.
    raw = (phasing.get("shared_cash") or {}).get(key)
    weights = [float(w or 0) for w in raw] if isinstance(raw, list) else []
    weights = _v4_fold_tail(weights, enabled or count, count)
    if len(weights) < count or sum(weights[:count]) <= 0:
        # Умолчание берётся у движка, а не пишется здесь второй раз: своя
        # копия говорила «всё в первую очередь» там, где движок раскладывал
        # по весам очередей.
        fallback = phase_cash_default_weights(count).get(key)
        if not fallback:
            return [1.0 if index == 0 else 0.0 for index in range(count)]
        return _v4_normalized(fallback, count)
    return _v4_normalized(weights, count)


@functools.lru_cache(maxsize=1)
def _v4_entry_style_id() -> "int | None":
    """Стиль «здесь печатают» — взятый у самого шаблона, а не своим числом.

    Дописанные блоки — лестница ставок, графики платежей и продаж, лестницы
    цены, календарь соцстройки, кривая ключевой ставки — писались БЕЗ стиля
    вовсе. Пока ввод был один лист, это была придирка к виду. После
    разделения это стало разрывом: перенос решает по цвету, что считается
    вводом, — и шестьдесят вводных из ста семидесяти четырёх остались на
    расчётном листе, где инструкция говорит «печатать нечего». Два ввода,
    ровно то, чего быть не должно.
    """
    with zipfile.ZipFile(_V4_TEMPLATE_PATH) as source:
        styles = source.read("xl/styles.xml").decode("utf-8")
    return v4_entry_sheet.style_map(styles)["entry_default"]


def _v4_entry_attr() -> str:
    """Атрибут стиля для ячейки, в которую печатают. Нет стиля — нет атрибута."""
    style = _v4_entry_style_id()
    return f' s="{style}"' if style is not None else ""


@functools.lru_cache(maxsize=1)
def _v4_header_style_id() -> "int | None":
    """Стиль заголовка раздела — тоже у шаблона.

    Заголовок дописанного блока — такой же заголовок раздела, как «ПРОДАЖИ»
    или «СТОИМОСТЬ СТРОИТЕЛЬСТВА»: строка без значения, называющая, что
    ниже. Пока он шёл без стиля, перенос вёз на лист ввода шаги графика, а
    его имя оставлял на расчётном — блок разрывался надвое, и обе половины
    выглядели целыми.
    """
    with zipfile.ZipFile(_V4_TEMPLATE_PATH) as source:
        styles = source.read("xl/styles.xml").decode("utf-8")
    found = sorted(v4_entry_sheet._header_styles(styles))
    return found[0] if found else None


def _v4_header_attr() -> str:
    style = _v4_header_style_id()
    return f' s="{style}"' if style is not None else ""


@functools.lru_cache(maxsize=1)
def _v4_label_style_id() -> "int | None":
    """Стиль подписи строки — у шаблона, как ввод и заголовок.

    Подпись дописанного блока («Шаг 1», «доля») — такая же подпись строки, как
    «Проект» или «Ставка» у шаблона. Пока она шла без стиля, блок читался
    чужой вставкой: шрифт другой, а на листе, где всё остальное книга
    владельца, это выглядит поломкой, а не нашей строкой.
    """
    with zipfile.ZipFile(_V4_TEMPLATE_PATH) as source:
        sheet = source.read(_v4_inputs_sheet_path(source)).decode("utf-8")
        styles = source.read("xl/styles.xml").decode("utf-8")
    return v4_entry_sheet.chrome_styles(sheet, styles)["label"]


def _v4_label_attr() -> str:
    style = _v4_label_style_id()
    return f' s="{style}"' if style is not None else ""


@functools.lru_cache(maxsize=1)
def _v4_formula_style_id() -> "int | None":
    """Стиль «здесь считается» — зелёный на голубой, конвенция шаблона.

    Дописанная формульная строка без стиля читается чужой вставкой, а хуже
    того — переезд ввода решает по цвету, что вводная: неокрашенная ячейка с
    формулой не поедет никуда, но и не скажет читателю, что её не правят.
    """
    with zipfile.ZipFile(_V4_TEMPLATE_PATH) as source:
        styles = source.read("xl/styles.xml").decode("utf-8")
    return v4_entry_sheet.style_map(styles)["formula"]


def _v4_formula_attr() -> str:
    style = _v4_formula_style_id()
    return f' s="{style}"' if style is not None else ""


def _v4_head_cell(coord: str, value: str) -> str:
    """Ячейка строки-заголовка дописанного блока.

    Тем же стилем, что заголовки разделов шаблона: перенос ввода узнаёт
    заголовок по цвету и везёт его вместе со своими строками.
    """
    return (f'<x:c r="{coord}"{_v4_header_attr()} t="inlineStr">'
            f"<x:is><x:t>{html.escape(str(value), quote=False)}</x:t></x:is></x:c>")


# Слова статусов реестра. Список не «на всякий случай»: неназванный статус
# книга печатает как неназванный, а не подставляет «Действует» — статус это
# утверждение о проверенности, и молча повысить его нельзя.
_V4_NORMATIVE_STATUS_WORDS = {
    "current": "Действует",
    "verified": "Сверено по исходнику",
    "verified_in_engine_source_pack": "Сверено по своду норм, не по акту",
    "review_required": "Требует сверки",
    "source_link_missing": "Нет ссылки на исходник",
    "superseded": "Утратил силу",
}


def _v4_sheet_row_styles(xml: str, row: int) -> dict[str, str]:
    """Стили ячеек одной строки листа — по колонкам.

    Стили берутся у шаблона, а не выдумываются: у листа «Источники» своя
    палитра, и `_v4_label_attr()` принёс бы сюда стиль соседнего листа. Ячейка
    дописанной строки берёт стиль ячейки СВОЕЙ колонки у строки-образца.
    """
    found = re.search(rf'<x:row r="{row}"[^>]*>(.*?)</x:row>', xml, re.S)
    if not found:
        return {}
    styles: dict[str, str] = {}
    for coord, attrs in re.findall(r'<x:c r="([A-Z]+)\d+"([^>]*)>', found.group(1)):
        style = re.search(r'\ss="(\d+)"', attrs)
        if style:
            styles[coord] = f' s="{style.group(1)}"'
    return styles


def _v4_restyle_row(xml: str, row: int, styles: dict[str, str], *,
                    whole_row: bool = False) -> str:
    """Ставит ячейкам строки стили по колонкам.

    Колонки вне `styles` не трогаются; `whole_row=True` — строка целиком
    меняет роль (итог ↔ обычная), и колонке без стиля у образца стиль снимается.

    Сборщик переносит итог блока на строку ниже и отдаёт его прежнее место
    дописанному объекту (ФОК на ОТЧЕТ!53 и ТЭП!34). Содержимое переезжало, а
    стиль итога оставался на месте: ревизия 29.09.2026 нашла жирный серый
    «ФОК / медцентр» над невыделенным «ИТОГО». Стиль — свойство строки-роли, а
    не номера, и переезжает вместе с ней.
    """
    found = re.search(rf'(<x:row r="{row}"[^>]*>)(.*?)(</x:row>)', xml, re.S)
    if not found:
        return xml

    def restyle(match: "re.Match[str]") -> str:
        column, attrs, close = match.group(1), match.group(2), match.group(3)
        if column not in styles and not whole_row:
            return match.group(0)
        attrs = re.sub(r'\ss="\d+"', "", attrs)
        return f'<x:c r="{column}{row}"{attrs}{styles.get(column, "")}{close}>'

    body = re.sub(rf'<x:c r="([A-Z]+){row}"([^>]*?)(/?)>', restyle, found.group(2))
    return xml[:found.start()] + found.group(1) + body + found.group(3) + xml[found.end():]


def _v4_normative_sources_rows(xml: str, region: str, missing: list[str]) -> str:
    """Нормативные основания расчёта — строками того же листа «Источники».

    Второго листа под них не заводим: лист «Источники» у шаблона уже есть и
    отвечает ровно на этот вопрос — чем посчитано и какой редакцией. Реестр при
    этом не копируется: строки собираются из `normatives_registry`, и копию
    негде обновлять, потому что копии нет.

    Отбор по юрисдикции — не украшение, а уже сделанная поломка: в книгу
    областного проекта уезжало московское 593-ПП, и сверка честно читала это
    как «источники от другой юрисдикции». Федеральные акты идут обоим.

    Статус позиции печатается словом реестра, а не «Использовано»: у половины
    строк он «Требует сверки», и выдать это за проверенное значит подписать
    чужим именем. Неизвестный статус называет себя сам — молча пойти за
    «Действует» он не может.
    """
    try:
        import normatives_registry
        rows = list(normatives_registry._merged_registry())
    except Exception as exc:  # реестра нет — это молчание, а не «актов нет»
        missing.append(f"Источники: реестр нормативов не прочитан ({exc})")
        return xml
    if not rows:
        missing.append("Источники: реестр нормативов пуст")
        return xml

    # Отбрасывается ЧУЖОЙ субъект, а не «оставляем свой и федеральный»: имя
    # федеральной области в реестре своё («Общие для РФ»), и спелленное здесь
    # оно молча выкинуло бы 43-ФЗ. Два субъекта названы потому, что это наше
    # поле `vri_region`, а не догадка о реестре.
    scope_here = "Московская область" if str(region or "msk") == "mo" else "Москва"
    other = "Москва" if scope_here == "Московская область" else "Московская область"
    kept = [row for row in rows if str(row.get("scope") or "").strip() != other]
    if not kept:
        missing.append(f"Источники: в реестре нет актов юрисдикции «{scope_here}»")
        return xml

    numbers = [int(number) for number in re.findall(r'<x:row r="(\d+)"', xml)]
    row_at = (max(numbers) if numbers else 0) + 2
    title_styles = _v4_sheet_row_styles(xml, 1)
    head_styles = _v4_sheet_row_styles(xml, 3)
    body_styles = _v4_sheet_row_styles(xml, 4)

    def cell(coord: str, value: str, styles: dict[str, str]) -> str:
        column = re.match(r"[A-Z]+", coord).group(0)
        return (f'<x:c r="{coord}"{styles.get(column, "")} t="inlineStr">'
                f"<x:is><x:t>{html.escape(str(value), quote=False)}</x:t></x:is></x:c>")

    parts: list[str] = []
    parts.append(f'<x:row r="{row_at}">'
                 + cell(f"A{row_at}", "НОРМАТИВНЫЕ ОСНОВАНИЯ РАСЧЁТА", title_styles)
                 + "</x:row>")
    row_at += 1
    parts.append(
        f'<x:row r="{row_at}">'
        + cell(f"A{row_at}",
               f"Акты реестра движка ({scope_here} и федеральный уровень), снят "
               f"{date.today().isoformat()}. «Применение» называет, где акт входит в "
               "расчёт; «справочно» — акт в формулы не входит. Проверять нас нужно "
               "по исходнику, ссылка в колонке рядом.", head_styles)
        + "</x:row>")
    row_at += 1

    # Шапка не переписывается словами, а берётся у строки 3 этого же листа:
    # вторая формулировка тех же колонок разошлась бы с первой молча.
    header = {}
    found = re.search(r'<x:row r="3"[^>]*>(.*?)</x:row>', xml, re.S)
    if found:
        for coord, body in re.findall(r'<x:c r="([A-Z]+)3"[^>]*>(.*?)</x:c>',
                                      found.group(1), re.S):
            # Подпись лежит и `inlineStr`, и `t="str"` со значением: шапка этого
            # листа записана вторым способом, и чтение только первого дало бы
            # «шапка не прочитана» на исправном шаблоне.
            text = (re.search(r"<x:t[^>]*>(.*?)</x:t>", body, re.S)
                    or re.search(r"<x:v>(.*?)</x:v>", body, re.S))
            if text:
                header[coord] = html.unescape(text.group(1))
    if header:
        parts.append(f'<x:row r="{row_at}">'
                     + "".join(cell(f"{col}{row_at}", value, head_styles)
                               for col, value in sorted(header.items()))
                     + "</x:row>")
        row_at += 1
    else:
        missing.append("Источники: шапка колонок не прочитана — строки без подписей")

    for index, row in enumerate(kept, start=1):
        status = str(row.get("status") or "").strip()
        word = _V4_NORMATIVE_STATUS_WORDS.get(status) or (
            f"статус «{status}» реестру неизвестен" if status else "статус не задан")
        applies = "; ".join(str(item) for item in (row.get("affects") or []) if item)
        # Справочный акт — не основание расчёта: движок его не читает. Подать
        # его строкой «оснований» наравне с участвующими значило бы выдать
        # справку за формулу.
        used = "; ".join(
            str(item.get("usage") or item.get("module") or "") if isinstance(item, dict)
            else str(item)
            for item in (row.get("engine_usage") or []) if item)
        applies = (f"в расчёте: {used}" if used
                   else "справочно, в формулы расчёта не входит"
                   + (f" · {applies}" if applies else ""))
        serial = _v4_excel_serial(row.get("current_as_of") or row.get("effective_from"))
        values = {
            "A": f"NRM-{index:02d}",
            "B": str(row.get("scope") or ""),
            "C": str(row.get("short_name") or row.get("title") or ""),
            "D": str(row.get("source_url") or ""),
            "F": "—",
            "G": applies,
            "H": word,
            "I": str(row.get("latest_amendment") or ""),
        }
        # Ячейки строки идут по возрастанию колонки: дата дописанная в конец
        # ставит книгу в тот же разряд, что `mergeCells` перед `sheetData` —
        # Excel объявляет её повреждённой, а на экране это неотличимо от
        # «книга не собралась».
        if serial is not None:
            date_cell = (f'<x:c r="E{row_at}"{body_styles.get("E", "")}>'
                         f"<x:v>{_v4_number(serial)}</x:v></x:c>")
        else:
            date_cell = cell(f"E{row_at}", "дата не задана", body_styles)
        cells = "".join(
            date_cell if col == "E" else cell(f"{col}{row_at}", values[col], body_styles)
            for col in sorted(set(values) | {"E"}))
        parts.append(f'<x:row r="{row_at}">{cells}</x:row>')
        row_at += 1

    tail = "</x:sheetData>"
    if tail not in xml:
        missing.append("Источники: не нашлось конца данных листа")
        return xml
    return xml.replace(tail, "".join(parts) + tail, 1)


def _v4_ladder_rows_xml(xml: str, steps: list[tuple[float, float]]
                        ) -> tuple[str, list[tuple[str, str]]]:
    """Блок ступеней в XML листа «Вводные» книги v4; возвращает ссылки.

    Книга v4 собирается прямо в XML — openpyxl её не пересобирает, поэтому и
    блок лестницы дописывается строками XML в конец sheetData: низ листа
    свободен, ссылки никуда не едут. Формат ячеек тот же, что у листа:
    подпись inlineStr, значение числом.
    """
    import re as _re
    rows = [int(number) for number in _re.findall(r'<x:row r="(\d+)"', xml)]
    row_at = (max(rows) if rows else 0) + 2
    parts: list[str] = []
    refs: list[tuple[str, str]] = []

    def text_cell(coord: str, value: str) -> str:
        return (f'<x:c r="{coord}" t="inlineStr"><x:is><x:t>{value}</x:t></x:is></x:c>')

    parts.append(f'<x:row r="{row_at}">'
                 + _v4_head_cell(f"A{row_at}", "СТУПЕНИ СТАВКИ ПФ ПО ПОКРЫТИЮ ЭСКРОУ")
                 # Ключ один на весь блок: вводная — строка договора целиком
                 # («3,47%@100; 1,75%@110»), а строк у неё столько, сколько
                 # ступеней. То же правило, что у графика платежей.
                 + _v4_head_cell(f"D{row_at}", "pf_special_steps")
                 + "</x:row>")
    row_at += 1
    parts.append(f'<x:row r="{row_at}">'
                 + _v4_head_cell(f"A{row_at}",
                                 "Правьте значения — строка 41 листов CF читает их "
                                 "отсюда. Пустой порог выключает ступень.")
                 + "</x:row>")
    row_at += 1
    for index, (edge, rate) in enumerate(steps):
        parts.append(
            f'<x:row r="{row_at}">'
            + text_cell(f"A{row_at}", f"Ступень {index + 1} — покрытие от")
            + f'<x:c r="B{row_at}"{_v4_entry_attr()}><x:v>{round(edge, 6):g}</x:v></x:c>'
            + text_cell(f"C{row_at}", "×") + "</x:row>")
        edge_ref = f"'Вводные'!$B${row_at}"
        row_at += 1
        parts.append(
            f'<x:row r="{row_at}">'
            + text_cell(f"A{row_at}", f"Ступень {index + 1} — ставка")
            + f'<x:c r="B{row_at}"{_v4_entry_attr()}><x:v>{round(rate, 8):g}</x:v></x:c>'
            + text_cell(f"C{row_at}", "% годовых") + "</x:row>")
        refs.append((edge_ref, f"'Вводные'!$B${row_at}"))
        row_at += 1
    tail = "</x:sheetData>"
    assert tail in xml
    return xml.replace(tail, "".join(parts) + tail, 1), refs


# Книга v4 читает сценарий ставки по своему имени столбца: E4/F4/G4 несут
# «Base»/«Upside»/«Downside», а движок — «base»/«high»/«low». Выше ставки
# у консервативного сценария, поэтому high идёт в Downside, а low в Upside:
# у книги имя про исход проекта, у движка — про уровень ставки.
_V4_RATE_SCENARIO_NAMES = {"base": "Base", "high": "Downside", "low": "Upside"}
# Режим процентов БРИДЖа при РнС: страница и движок зовут второй вариант
# «Выплата при рефинансировании», а формулы шаблона (CF_1–CF_4, по 181 на
# лист) сравнивают B31 с «Оплата капиталом». Слово, которого не знает ни одна
# формула, книга не отвергала: проценты не капитализировались и не платились —
# исчезали, и стоимость финансирования расходилась с движком на всю их сумму.
_V4_BRIDGE_MODE_NAMES = {"Капитализация в ПФ": "Капитализация в ПФ",
                         "Выплата при рефинансировании": "Оплата капиталом"}


def _v4_rate_curve_rows_xml(xml: str, scenario: str, start_date: Any,
                            curve_shape: float, offset_months: int,
                            targets: dict[str, float],
                            selectors: dict[str, str]
                            ) -> tuple[str, dict[str, str]]:
    """Блок кривой ключевой ставки внизу «Вводных»; возвращает ссылки на ячейки.

    Три вводные жили в книге числами ВНУТРИ формулы листа «Ставки»
    (`EXP(-2*…)` и смещение `+5`) либо не жили вовсе. Числа движок подставлял
    верные, но править их в книге было негде: «если величина в книге не
    выражается формулой, значит не хватает не формулы, а вводной».

    Хуже была третья: сценарий ставки книга не знала совсем — ячейка `B6`
    закреплена словом «Base», и целевая ставка бралась базовой при любом
    `rate_scenario`. На умолчаниях с консервативным сценарием это 4 516 млн ₽
    стоимости финансирования у движка против 4 165 у книги. `B6` при этом
    трогать нельзя: он ведёт множители цены и затрат (движок пишет
    ПРИМЕНЁННЫЕ в колонку Base) и задержку старта. Поэтому у ставки свой
    селектор, а не общий.

    Блок дописывается строками XML в свободный низ листа, как лестница
    ступеней: вставить строку в занятое место нельзя — поедут все ссылки.
    """
    import re as _re
    rows = [int(number) for number in _re.findall(r'<x:row r="(\d+)"', xml)]
    row_at = (max(rows) if rows else 0) + 2
    parts: list[str] = []

    def text_cell(coord: str, value: str) -> str:
        return f'<x:c r="{coord}" t="inlineStr"><x:is><x:t>{value}</x:t></x:is></x:c>'

    def number_cell(coord: str, value: float, entry: bool = True) -> str:
        """Число блока. `entry=False` — там, где правит не человек, а формула."""
        return f'<x:c r="{coord}"{_v4_entry_attr() if entry else ""}><x:v>{value:g}</x:v></x:c>'

    parts.append(f'<x:row r="{row_at}">'
                 + _v4_head_cell(f"A{row_at}", "КРИВАЯ КЛЮЧЕВОЙ СТАВКИ")
                 + _v4_head_cell(f"D{row_at}", "Ключ API") + "</x:row>")
    row_at += 1
    parts.append(f'<x:row r="{row_at}">'
                 + _v4_head_cell(f"A{row_at}",
                                 "Правьте значения — лист «Ставки» и ячейка B34 читают их отсюда. "
                                 "Сценарий выбирается как на странице DevelopAid: Консервативный / Базовый / Оптимистичный.")
                 + "</x:row>")
    row_at += 1

    refs: dict[str, str] = {}
    scenario_row = row_at
    parts.append(f'<x:row r="{row_at}">'
                 + text_cell(f"A{row_at}", "Сценарий ключевой ставки")
                 + f'<x:c r="B{row_at}"{_v4_entry_attr()} t="inlineStr">'
                   f"<x:is><x:t>{scenario}</x:t></x:is></x:c>"
                 + text_cell(f"C{row_at}", "сценарий")
                 + text_cell(f"D{row_at}", "rate_scenario") + "</x:row>")
    refs["rate_scenario"] = f"$B${scenario_row}"
    row_at += 1

    serial = _v4_excel_serial(start_date)
    date_row = row_at
    parts.append(f'<x:row r="{row_at}">'
                 + text_cell(f"A{row_at}", "Дата стартовой ставки")
                 + (number_cell(f"B{row_at}", serial) if serial is not None
                    else text_cell(f"B{row_at}", ""))
                 + text_cell(f"C{row_at}", "дата")
                 + text_cell(f"D{row_at}", "rate_start_date") + "</x:row>")
    refs["rate_start_date"] = f"$B${date_row}"
    row_at += 1

    shape_row = row_at
    parts.append(f'<x:row r="{row_at}">'
                 + text_cell(f"A{row_at}", "Форма кривой снижения")
                 + number_cell(f"B{row_at}", round(float(curve_shape), 6))
                 + text_cell(f"C{row_at}", "коэффициент")
                 + text_cell(f"D{row_at}", "rate_curve_shape") + "</x:row>")
    refs["rate_curve_shape"] = f"$B${shape_row}"
    row_at += 1

    # Три целевые ставки стояли в сценарных колонках E8/F8/G8, где свободной
    # соседней ячейки под ключ нет вовсе: строка 8 занята подписью, значением
    # и активным сценарием. Значит правят их здесь, а строка 8 читает —
    # тот же приём, что у лага продаж и тренда темпа (B66/B68).
    for key, label in (("rate_target_base_pct", "Целевая ставка — базовый (Base)"),
                       ("rate_target_low_pct", "Целевая ставка — оптимистичный (Upside)"),
                       ("rate_target_high_pct", "Целевая ставка — консервативный (Downside)")):
        parts.append(f'<x:row r="{row_at}">'
                     + text_cell(f"A{row_at}", label)
                     + number_cell(f"B{row_at}", round(float(targets.get(key, 0.0)), 8))
                     + text_cell(f"C{row_at}", "% годовых")
                     + text_cell(f"D{row_at}", key) + "</x:row>")
        refs[key] = f"$B${row_at}"
        row_at += 1

    # Смещение считает сама книга — тем же выражением, что и движок. Записать
    # его числом значило бы заморозить: правка даты стартовой ставки не
    # двигала бы кривую, а выглядело бы это как рабочая вводная.
    offset_row = row_at
    if serial is not None:
        offset_formula = (f"(YEAR($B$8)-YEAR($B${date_row}))*12"
                          f"+MONTH($B$8)-MONTH($B${date_row})"
                          f"-IF(DAY($B${date_row})&gt;1,1,0)")
        offset_cell = (f'<x:c r="B{offset_row}"><x:f>{offset_formula}</x:f>'
                       f"<x:v>{int(offset_months)}</x:v></x:c>")
    else:
        offset_cell = number_cell(f"B{offset_row}", int(offset_months), entry=False)
    parts.append(f'<x:row r="{row_at}">'
                 + text_cell(f"A{row_at}", "Месяцев от даты ставки до старта проекта")
                 + offset_cell
                 + text_cell(f"C{row_at}", "мес.")
                 + text_cell(f"D{row_at}", "считается из даты выше") + "</x:row>")
    refs["offset"] = f"$B${offset_row}"
    row_at += 1

    # Два селектора страницы, которых книга не считает вовсе, — и об этом
    # сказано прямо. Их следствие в книге уже стоит: ставки себестоимости
    # посчитаны по классу, ТЭП — по пропорциям. Не назвать их значит выдать
    # пустое место за «таких вводных нет»; назвать ключом — пообещать, что
    # правка здесь что-то изменит.
    row_at += 1
    parts.append(f'<x:row r="{row_at}">'
                 + text_cell(f"A{row_at}", "ПРЕДПОСЫЛКИ РАСЧЁТА — книга их не считает")
                 + "</x:row>")
    row_at += 1
    for label, value, note in (
            ("Класс проекта", selectors.get("project_class", ""),
             "ставки себестоимости выше уже посчитаны по нему · project_class"),
            ("Пропорции ТЭП", selectors.get("tep_ratios_custom", "") or "по умолчанию",
             "ТЭП листа «ТЭП» уже посчитан по ним · tep_ratios_custom"),
            # Тип проекта книга тоже не считает: у нежилого жильё обнулено
            # ЕЩЁ ВО ВВОДНЫХ, и книга видит нули на своих местах. Не назвать
            # его значит выдать пустое место за «такой вводной нет».
            ("Тип проекта", selectors.get("project_kind", ""),
             "жильё нежилого проекта обнулено во вводных · project_kind")):
        parts.append(f'<x:row r="{row_at}">'
                     + text_cell(f"A{row_at}", label)
                     + text_cell(f"B{row_at}", str(value))
                     + text_cell(f"D{row_at}", note) + "</x:row>")
        row_at += 1

    tail = "</x:sheetData>"
    assert tail in xml
    return xml.replace(tail, "".join(parts) + tail, 1), refs


def _v4_step_worksheet_xml(text: str, steps: list[tuple[float, float]],
                           refs: list[tuple[str, str]]) -> tuple[str, int]:
    """Строка 41 CF-листа: одна ставка B28 становится лестницей по ссылкам.

    Книга v4 знала только «Специальная ставка ПФ» ячейкой B28: движок считал
    по ступеням, книга по одной ставке, и на проекте с покрытием выше 1×
    паритет стоимости финансирования расходился на миллиарды. Тесты в эту
    ветку не заходили, пока умолчание поля было пустым.
    """
    import re as _re
    counter = 0

    def swap(match: "_re.Match[str]") -> str:
        nonlocal counter
        body = match.group(1)
        column = _re.search(r"\b([A-Z]{1,3})40\b", body)
        if not column or "'Вводные'!$B$28" not in body:
            return match.group(0)
        stepped = pf_special_steps_formula(
            f"{column.group(1)}40", steps, "'Вводные'!$B$28", refs=refs)
        counter += 1
        replaced = body.replace("'Вводные'!$B$28",
                                "(" + stepped.replace(">", "&gt;") + ")")
        return "<x:f>" + replaced + "</x:f>"

    return _re.sub(r"<x:f>([^<]*'Вводные'!\$B\$28[^<]*)</x:f>", swap, text), counter


def _v4_finance_hints(bundle: dict[str, Any]) -> dict[str, Any]:
    """Контрольные числа книги из посчитанного движком — одно объявление.

    Сборка жила двумя копиями: своя у выгрузки с сайта, своя у бота. Копия
    бота отстала — в ней не было ни признака переноса долга, ни его суммы, и
    на проекте с включённым переносом книга из чата не знала о нём вовсе, а
    книга с сайта знала. Два достоверных на вид документа на одних вводных.
    """
    phases = (bundle.get("phases") or []) if isinstance(bundle, dict) else []
    if phases:
        hints: dict[str, Any] = {
            "pf_limit_by_phase": [
                float(p["result"]["finance"].get("pf_limit", 0.0)) / 1e6 for p in phases],
            "bridge_peak_by_phase": [
                float(p["result"]["finance"].get("peak_bridge", 0.0)) / 1e6 for p in phases],
        }
    else:
        finance = ((bundle or {}).get("consolidated") or {}).get("finance") or {}
        if not finance:
            return {}
        hints = {
            "pf_limit_by_phase": [float(finance.get("pf_limit", 0.0)) / 1e6],
            "bridge_peak_by_phase": [float(finance.get("peak_bridge", 0.0)) / 1e6],
        }
    hints["parity"] = _v4_parity_targets(bundle.get("consolidated") or {})
    # Обеспеченность парковкой — места и вся нормативная потребность проекта
    # числами движка (`parking_provision`): норму книга не считает.
    _provision = (((bundle.get("consolidated") or {}).get("parking") or {})
                  .get("provision") or {})
    if float(_provision.get("required") or 0.0) > 0:
        hints["parking_provision"] = {"built": float(_provision.get("built") or 0.0),
                                      "required": float(_provision["required"])}
    # ТЦ и офисы вне ДДУ: книга получает результат движка листом
    # «Нежильё — стратегия» (`v4_nonres_sheet`) — таблицу отчёта и месячные ряды.
    _consolidated = bundle.get("consolidated") or {}
    _nonres_report = (_consolidated.get("report") or {}).get("nonres_strategy") or []
    if _nonres_report:
        hints["nonres"] = {
            "report": _nonres_report,
            "financing": (_consolidated.get("report") or {}).get("nonres_financing") or [],
            "monthly": [
                {"month": row.get("month"),
                 **{key: float(row.get(key) or 0.0) for key, _ in v4_nonres_sheet.MONTHLY_COLUMNS}}
                for row in (_consolidated.get("finance") or {}).get("rows") or []
                if any(float(row.get(key) or 0.0) for key, _ in v4_nonres_sheet.MONTHLY_COLUMNS)],
            # Ряды каждого объекта — строки движка (`nonres_overlay`), не раскладка итога.
            "objects": [{"key": item.get("key"), "title": item.get("title"),
                         "rows": list(item.get("rows") or [])}
                        for item in ((_consolidated.get("finance") or {}).get("nonres") or {})
                        .get("objects") or []],
        }
    # ТЭП, на котором посчитан отчёт. Книга писала присланный страницей, а
    # движок приводит строку ТЭП к вводным: заданная руками площадь гаража
    # сильнее норматива, выгрузка ГлавАПУ сильнее устаревшей строки, соцобъект
    # считается от мест. Правки книга не видела и строила проект, которого
    # движок не считал: на 77:07:0013006 это 23 310 м² подземной части против
    # 15 540 у отчёта при одинаковых 666 местах — 1 494,6 млн ₽ CAPEX, LLCR
    # 0,98 против 1,03, то есть книга говорила «не проходит», а отчёт
    # «проходит». Оба документа выглядели верными.
    hints["tep_applied"] = {
        str(row.get("key")): {key: value for key, value in row.items() if key != "key"}
        for row in ((((bundle or {}).get("consolidated") or {}).get("tep") or {}).get("rows") or [])
        if row.get("key")}
    # В какой очереди объект ПОСТРОЕН — по применённому расчёту, а не по
    # намерению. Очередь объекта решают двое, и решали по-разному: у движка
    # лестница «объявлено продуктами очереди → `discrete` → умолчание», у
    # сборщика книги только `discrete` с зашитым «ТЦ и паркинг во второй».
    # Пресет КРТ Нагатино размещает ТЦ продуктами четвёртой очереди и `discrete`
    # не заполняет вовсе — книга ставила ТЦ во ВТОРУЮ, то есть на два года
    # раньше: он продавался и строился дешевле, и на одних вводных выручка
    # расходилась на 7 910 млн ₽, CAPEX на 6 692, налог на 584. Пик БРИДЖа при
    # этом сходился до копейки, а LLCR проходил допуск — паритет выглядел
    # «почти сошедшимся» там, где очередь строит не тот объект.
    # Ответ спрашивается у результата, а не выводится второй раз: очередь, где
    # у объекта есть метры, и есть та, в которой движок его построил. Вывести
    # лестницу заново значило бы завести третий ответ на тот же вопрос.
    hints["object_phase"] = _v4_object_phase_by_result(phases)
    # ТЭП КАЖДОЙ очереди — по применённому расчёту. Книга выводила разбивку
    # заново (`_phase_tep_product_rows`) и на пресете КРТ Нагатино, который
    # объявляет очередям РАВНЫЕ метры, разложила проект своим убывающим
    # пресетом: 69 031 / 56 087 / 47 459 / 43 144 м² ГНС квартир против
    # 53 930 у каждой. Итог при этом сходится до десятой — метры не теряются,
    # а переезжают между очередями, и потому расхождение выглядит не потерей,
    # а другой экономикой: выручка и CAPEX первых очередей завышены, последних
    # занижены, и пик ПФ первой очереди вылезал за её же банковский лимит.
    # Тот же корень, что у размещения объекта: явное объявление очереди до
    # книги не доезжало вовсе.
    hints["tep_by_phase"] = [
        {str(row.get("key")): {k: v for k, v in row.items() if k != "key"}
         for row in ((((item or {}).get("result") or {}).get("tep") or {}).get("rows") or [])
         if row.get("key")}
        for item in (phases or [])]
    # Горизонт движка — сколько месяцев он посчитал. Книга кончается своей
    # колонкой, и всё, что за ней, она молча теряет: на четырёх очередях с
    # шагом 36 это 43 месяца и −12,3 млрд ₽ CAPEX при собранном без единого
    # слова файле. Обрезка обязана назваться, поэтому длина едет в подсказках.
    hints["horizon_months"] = len(
        (((bundle or {}).get("consolidated") or {}).get("finance") or {}).get("rows") or [])
    # Применён ли перенос — решает движок гейтом по общему LLCR, и книга этого
    # LLCR не знает. Полагаясь на одно намерение пользователя, она перенесла бы
    # долг там, где банк отказал, и показала бы очередь рассчитавшейся, пока
    # отчёт зовёт её дефолтной.
    hints["carry_applied"] = bool((bundle.get("debt_carry") or {}).get("applied"))
    # Доля кэш-свипа: книга берёт её оттуда же, откуда признак переноса.
    # Свип без переноса не бывает — долг остаётся на своей очереди.
    hints["cash_sweep_share"] = (
        max((float((item.get("result") or {}).get("finance", {}).get("cash_sweep_pct") or 0.0)
             for item in phases), default=0.0) / 100.0
        if hints["carry_applied"] and any(
            float((item.get("result") or {}).get("finance", {}).get("bank_sweep_out") or 0.0) > 0
            for item in phases) else 0.0)
    hints["carried_debt_mln"] = sum(
        float((item.get("result") or {}).get("finance", {}).get("debt_carried_out") or 0.0)
        for item in phases) / 1e6
    # Кассовые доли, которые движок применил: статья «по объёму» в phasing
    # стоит словом, а книге нужны числа — те же, что у движка.
    hints["shared_cash_applied"] = dict(bundle.get("shared_cash_applied") or {})
    # Выручка очереди по продуктам: книга считает её своими формулами, а отсюда
    # берёт только список продуктов, у которых выручка есть хоть в одной
    # очереди, и их подписи. Второй счёт той же выручки однажды разошёлся бы с
    # первым, и обе строки выглядели бы верными.
    rows = bundle.get("comparison") or []
    products = ((bundle.get("consolidated") or {}).get("report") or {}).get("products") or []
    hints["revenue_products"] = [
        {"key": str(item.get("key")), "label": str(item.get("label") or item.get("key"))}
        for item in products
        if any(float((row.get("revenue_by_product") or {}).get(str(item.get("key"))) or 0.0) > 0.0
               for row in rows)]
    return hints
def _v4_schedule_rows_xml(xml: str, title: str, hint: str,
                          rows: list[tuple[int, float]], unit: str,
                          key: str = "") -> tuple[str, list[tuple[str, str]]]:
    """Блок «месяц → величина» внизу «Вводных» книги v4; возвращает ссылки.

    Тот же приём, что у ступеней ставки: книга собирается прямо в XML, низ
    листа свободен, блок дописывается в конец sheetData. Значения правятся в
    книге — формулы CAPEX и ОБЪЕКТЫ читают их отсюда, а не зашитые числа.
    """
    import re as _re
    numbers = [int(number) for number in _re.findall(r'<x:row r="(\d+)"', xml)]
    row_at = (max(numbers) if numbers else 0) + 2
    parts: list[str] = []
    refs: list[tuple[str, str]] = []

    def text_cell(coord: str, value: str) -> str:
        return (f'<x:c r="{coord}"{_v4_label_attr()} t="inlineStr">'
                f'<x:is><x:t>{html.escape(value, quote=False)}</x:t></x:is></x:c>')

    # Ключ движка — в шапке блока: вводная здесь ОДНА («30%@0; 40%@6»), а строк
    # у неё столько, сколько шагов. Подписать ключом каждую строку значило бы
    # назвать шаг целой вводной — то же правило, по которому раскиданный по
    # очередям соцобъект ключа не получает.
    parts.append(f'<x:row r="{row_at}">' + _v4_head_cell(f"A{row_at}", title)
                 + (_v4_head_cell(f"D{row_at}", key) if key else "") + "</x:row>")
    row_at += 1
    parts.append(f'<x:row r="{row_at}">' + _v4_head_cell(f"A{row_at}", hint) + "</x:row>")
    row_at += 1
    for index, (month, value) in enumerate(rows):
        parts.append(
            f'<x:row r="{row_at}">'
            + text_cell(f"A{row_at}", f"Шаг {index + 1}")
            + f'<x:c r="B{row_at}"{_v4_entry_attr()}><x:v>{int(month)}</x:v></x:c>'
            + f'<x:c r="C{row_at}"{_v4_entry_attr()}><x:v>{round(float(value), 8):g}</x:v></x:c>'
            + text_cell(f"D{row_at}", unit) + "</x:row>")
        refs.append((f"'Вводные'!$B${row_at}", f"'Вводные'!$C${row_at}"))
        row_at += 1
    tail = "</x:sheetData>"
    assert tail in xml
    return xml.replace(tail, "".join(parts) + tail, 1), refs


def _v4_rewrite_row_formulas(xml: str, row: int, expect: str,
                             build: "Callable[[str, str], str]") -> tuple[str, int]:
    """Переписать формулы всех месячных ячеек строки; `expect` — признак того,
    что формула шаблона та, которую мы умеем менять. Не опознана — не трогаем,
    и число замен скажет об этом вызывающему."""
    import re as _re
    counter = 0

    def swap(match: "_re.Match[str]") -> str:
        nonlocal counter
        column, head, body = match.group(1), match.group(2), match.group(3)
        if column in ("A", "B", "C") or expect not in body:
            return match.group(0)
        counter += 1
        return f'<x:c r="{column}{row}"{head}><x:f>{build(column, body)}</x:f></x:c>'

    pattern = _re.compile(r'<x:c r="([A-Z]{1,3})%d"([^>]*)><x:f>([^<]*)</x:f>(?:<x:v>[^<]*</x:v>)?</x:c>' % row)
    return pattern.sub(swap, xml), counter


def _v4_month_offset(column: str, start_ref: str) -> str:
    """Месяцев от точки отсчёта до колонки: та же арифметика, что в шаблоне."""
    return (f"(12*(YEAR({column}$3)-YEAR({start_ref}))+MONTH({column}$3)-MONTH({start_ref}))")


def _v4_share_by_month(offset: str, refs: list[tuple[str, str]]) -> str:
    """Сумма долей шагов, у которых месяц совпал с колонкой. Только IF и
    сравнения — их считает и Excel, и наш вычислитель паритета."""
    return "(" + "+".join(f"IF({offset}={month_ref},{value_ref},0)"
                          for month_ref, value_ref in refs) + ")"


def _v4_stage_rows_xml(xml: str, title: str, hint: str, growth: list[float],
                       keys: tuple[str, ...] = ()) -> tuple[str, list[str]]:
    """Блок «этап → рост цены» внизу «Вводных» книги v4; возвращает ссылки на
    ячейки роста. Месяц этапа в блоке не хранится — его считает формула из срока
    строительства книги (четверти срока), иначе правка срока в книге оставила
    бы лестницу на прежних месяцах."""
    import re as _re
    numbers = [int(number) for number in _re.findall(r'<x:row r="(\d+)"', xml)]
    row_at = (max(numbers) if numbers else 0) + 2
    parts: list[str] = []
    refs: list[str] = []

    def text_cell(coord: str, value: str) -> str:
        return (f'<x:c r="{coord}"{_v4_label_attr()} t="inlineStr">'
                f'<x:is><x:t>{html.escape(value, quote=False)}</x:t></x:is></x:c>')

    parts.append(f'<x:row r="{row_at}">' + text_cell(f"A{row_at}", title) + "</x:row>")
    row_at += 1
    parts.append(f'<x:row r="{row_at}">' + text_cell(f"A{row_at}", hint) + "</x:row>")
    row_at += 1
    for index, value in enumerate(growth):
        # У лестницы каждый этап — своя вводная движка, поэтому ключ у каждой
        # строки свой. В отличие от графика, где вводная одна на весь блок.
        parts.append(
            f'<x:row r="{row_at}">'
            + text_cell(f"A{row_at}", f"Этап {index + 1} · готовность {STAGE_READINESS_PCT[index]}%")
            + f'<x:c r="B{row_at}"{_v4_entry_attr()}><x:v>{round(float(value), 8):g}</x:v></x:c>'
            + text_cell(f"C{row_at}", "доля роста")
            + (text_cell(f"D{row_at}", keys[index]) if index < len(keys) else "")
            + "</x:row>")
        refs.append(f"'Вводные'!$B${row_at}")
        row_at += 1
    tail = "</x:sheetData>"
    assert tail in xml
    return xml.replace(tail, "".join(parts) + tail, 1), refs


def _v4_stage_factor(offset: str, months_ref: str, refs: list[str]) -> str:
    """Множитель лестницы: этап k действует с месяца ROUNDUP(срок×k/4) от
    начала строительства, этапы перемножаются — та же арифметика, что в
    `stage_ladder_factor`. Только IF, ROUNDUP и сравнения."""
    return "*".join(
        f"(1+IF({offset}&gt;=ROUNDUP({months_ref}*{index}/4,0),{ref},0))"
        for index, ref in enumerate(refs, 1))


def _v4_replace_pre_rve_growth(body: str, factor: str) -> str:
    """В формуле цены шаблона множитель роста до РВЭ «(1+…)^MAX(0,MIN(…))»
    заменяется лестницей, множитель роста после РВЭ остаётся."""
    marker = "*(1+'Вводные'!"
    first = body.index(marker)
    second = body.index(marker, first + len(marker))
    return body[:first] + "*" + factor + body[second:]


def _v4_apply_purchase_schedule(capex_xml: str, refs: list[tuple[str, str]],
                                missing: list[str]) -> str:
    """Строки покупки CAPEX (14/48/82/116) — по графику из блока «Вводных».

    Шаблон клал всю цену в месяц старта очереди; движок платит по графику
    (владелец, 02.09.2026). Формула не опознана — строка в `missing`, книга
    не считает молча иначе, чем отчёт.
    """
    for phase_index in range(4):
        row = 14 + 34 * phase_index
        queue_row = 88 + phase_index
        start_ref = f"EDATE('Вводные'!$D${queue_row},'Вводные'!$H$9)"
        expect = f"YEAR(EDATE('Вводные'!$D${queue_row},'Вводные'!$H$9)"

        def build(column: str, _body: str, row=row, start_ref=start_ref) -> str:
            return f"$B${row}*{_v4_share_by_month(_v4_month_offset(column, start_ref), refs)}"

        capex_xml, done = _v4_rewrite_row_formulas(capex_xml, row, expect, build)
        if not done:
            missing.append(f"CAPEX · график платежей за покупку, очередь {phase_index + 1}")
    return capex_xml


# Строки листа ОБЪЕКТЫ: (объём, цена, старт продаж, база объёма, начало
# строительства, срок строительства в «Вводных», выручка гаража) по объекту.
# Строка выручки гаража стоит здесь, а не выводится из строки цены сдвигом на
# десять: у наземного паркинга гаража нет вовсе, и правило «плюс десять» на нём
# указало бы на чужую строку. Нет гаража — None.
_V4_OBJECT_ROWS = {
    "offices": (22, 23, "$B$11", "$B$13", "$B$9", "'Вводные'!$K$28", 33),
    "retail": (50, 51, "$B$39", "$B$41", "$B$37", "'Вводные'!$K$48", 61),
    "above_parking": (78, 79, "$B$67", "$B$69", "$B$65", "'Вводные'!$K$69", None),
}


def _v4_shift_abs_row(ref: str, offset: int) -> str:
    """«$B$39» или «'Вводные'!$K$48» со сдвигом строки."""
    match = re.match(r"(.*\$)(\d+)$", ref)
    return f"{match.group(1)}{int(match.group(2)) + offset}"


# Дописанный объект — строки двойника со сдвигом своей копии; гаража у него
# нет, если нет своего подземного в раскладке.
_V4_OBJECT_ROWS.update({
    lay.obj.prefix: (
        twin[0] + lay.object_offset, twin[1] + lay.object_offset,
        *(_v4_shift_abs_row(ref, lay.object_offset) for ref in twin[2:5]),
        _v4_shift_abs_row(twin[5], lay.input_offset),
        twin[6] + lay.object_offset if twin[6] is not None and lay.parking_under else None)
    for lay in _V4_EXTRA_OBJECT_LAYOUTS
    for twin in [_V4_OBJECT_ROWS[lay.twin_prefix]]})


def _v4_apply_object_schedule(objects_xml: str, prefix: str,
                              profile_refs: list[tuple[str, str]] | None,
                              stage_refs: list[str] | None,
                              missing: list[str]) -> str:
    """Профиль продаж и лестница цены объекта — формулами листа ОБЪЕКТЫ.

    Профиль замещает «долю до РВЭ + остаток», лестница — множитель
    ежемесячного роста до РВЭ; что не задано, остаётся формулой шаблона.
    """
    (qty_row, price_row, start_ref, base_ref, build_start_ref, months_ref,
     garage_row) = _V4_OBJECT_ROWS[prefix]
    if profile_refs:
        def build_qty(column: str, _body: str) -> str:
            return f"{base_ref}*{_v4_share_by_month(_v4_month_offset(column, start_ref), profile_refs)}"

        objects_xml, done = _v4_rewrite_row_formulas(objects_xml, qty_row, f"{base_ref}*", build_qty)
        if not done:
            missing.append(f"ОБЪЕКТЫ · профиль продаж {prefix}")
    if stage_refs:
        def build_price(column: str, body: str) -> str:
            return _v4_replace_pre_rve_growth(body, _v4_stage_factor(
                _v4_month_offset(column, build_start_ref), months_ref, stage_refs))

        objects_xml, done = _v4_rewrite_row_formulas(
            objects_xml, price_row, "*(1+'Вводные'!", build_price)
        if not done:
            missing.append(f"ОБЪЕКТЫ · лестница цены {prefix}")
        # Места гаража объекта продаются ПО ТОЙ ЖЕ лестнице: движок передаёт
        # им `price_factor` объекта (`sell_object_parking(..., plan["factor"])`),
        # а `sales_schedule` при заданной лестнице ежемесячный рост до РВЭ не
        # применяет вовсе. Строка цены лестницу получала, строка выручки гаража
        # — нет, и книга вела места месячным ростом там, где движок ведёт
        # ступенями: расхождение включалось при первом же заданном этапе.
        if garage_row is not None:
            objects_xml, done = _v4_rewrite_row_formulas(
                objects_xml, garage_row, "*(1+'Вводные'!", build_price)
            if not done:
                missing.append(f"ОБЪЕКТЫ · лестница цены гаража {prefix}")
    return objects_xml


# Лист «Продажи»: блок очереди — 23 строки, цены четырёх продуктов в строках
# 15/18/21/24 первого блока; начало строительства очереди — старт + ИРД +
# задержка сценария, срок строительства — колонка F строки очереди.
_V4_SALES_PRICE_ROWS = (15, 18, 21, 24)
_V4_SALES_PHASE_STRIDE_ROWS = 23


def _v4_apply_core_ladder(sales_xml: str, stage_refs: list[str],
                          missing: list[str]) -> str:
    """Цены основных продуктов на листе «Продажи» — по этапам готовности.

    Множитель ежемесячного роста до РВЭ «(1+B64)^…» замещается лестницей;
    стартовая цена с множителями очереди и рост после РВЭ остаются. Не
    опознали формулу — строка в `missing`.
    """
    for phase_index in range(4):
        queue_row = 88 + phase_index
        build_start_ref = f"EDATE('Вводные'!$D${queue_row},'Вводные'!$E${queue_row}+'Вводные'!$H$9)"
        months_ref = f"'Вводные'!$F${queue_row}"
        for base_row in _V4_SALES_PRICE_ROWS:
            row = base_row + _V4_SALES_PHASE_STRIDE_ROWS * phase_index

            def build(column: str, body: str, build_start_ref=build_start_ref, months_ref=months_ref) -> str:
                return _v4_replace_pre_rve_growth(body, _v4_stage_factor(
                    _v4_month_offset(column, build_start_ref), months_ref, stage_refs))

            sales_xml, done = _v4_rewrite_row_formulas(sales_xml, row, "*(1+'Вводные'!", build)
            if not done:
                missing.append(f"Продажи · лестница цены, строка {row}")
    return sales_xml


# Клетки, где книга получает ЧИСЛО вместо своей формулы. Список закрытый и с
# причиной у каждой строки: книга должна работать почти как движок — «если
# что-то меняешь где-то, всё должно меняться так же» (решение владельца,
# 03.09.2026), — и всякий хард эту связь рвёт. Не «устаревшее число»: соседние
# статьи поедут за новым календарём, а записанная числом останется в прежних
# колонках, то есть перестанет принадлежать своей очереди.
#
# Сторож `test_the_workbook_has_no_unnamed_hard_values` сверяет собранную книгу
# с шаблоном и валится на КАЖДОЙ замене «формула → число», которой здесь нет.
# Пустой список — цель, а не украшение: пока строка тут стоит, книга в этом
# месте самостоятельным продуктом не является.
# Лимит ПФ очереди — её выборка, округлённая вверх до 10 млн (методика движка,
# `pf_limit = ceil(pf_draw_total / 10 млн) × 10 млн`). Округляется КАЖДАЯ очередь,
# а не сумма: округление суммы даёт другое число на любом проекте с очередями.
_V4_PF_LIMIT_PHASE = "ROUNDUP('CF_{n}'!$B$45/10,0)*10"
_V4_PF_LIMIT_FORMULA = "+".join(_V4_PF_LIMIT_PHASE.format(n=n) for n in range(1, 5))


# --- блок соцобъектов на «Вводных» ---------------------------------------------
# Календарь соцстройки был 480 числами в четырёх строках CAPEX: правка сроков
# очереди прямо в книге его не двигала, а движок строит каждый объект в СВОЕЙ
# очереди её календарём. Выразить это формулой было нечем — ячеек объектов на
# «Вводных» не существовало вовсе, только общая строка A17 «Социальный платёж».
# Теперь они есть: по строке на пару «тип × очередь», и строка CAPEX читает их.
# Крайний срок денежной компенсации — за месяц до РнС первой очереди: после
# РнС линия БРИДЖа рефинансирована в ПФ, и платить компенсацию нечем.
_V4_SOCIAL_DEADLINE = "EDATE('CF_1'!$B$7,-1)"

# Вводные движка за каждой колонкой блока: мест, цена места, начало, срок.
_V4_SOCIAL_KEYS: dict[str, tuple[str, str, str, str]] = {
    "kindergarten": ("kindergarten_places", "kindergarten_cost_mln_per_place",
                     "kindergarten_start", "kindergarten_months"),
    "school": ("school_places", "school_cost_mln_per_place",
               "school_start", "school_months"),
    "clinic": ("clinic_capacity", "clinic_cost_mln_per_unit",
               "clinic_start", "clinic_months"),
}
# Площадь объекта и норматив на место — вторая пара колонок того же блока.
# Бюджет считается от МЕСТ, а площадь нужна для контроля общего объёма
# (решение владельца, 03.09.2026), и это два разных числа у одной строки.
_V4_SOCIAL_AREA_KEYS: dict[str, tuple[str, str]] = {
    "kindergarten": ("social_dou_gba_sqm", "social_dou_norm_sqm"),
    "school": ("social_school_gba_sqm", "social_school_norm_sqm"),
    "clinic": ("social_clinic_gba_sqm", "social_clinic_norm_sqm"),
}
# Подписи колонок очередей — как в шаблоне, чтобы ключ дописывался к ним, а не
# заменял их: копия подписи разошлась бы с книгой молча.
_v4_QUEUE_HEADERS: dict[str, str] = {
    "D": "Старт", "E": "ИРД, мес.", "F": "Стройка, мес.", "G": "Лаг продаж",
    "AD": "Тренд темпа продаж, %/мес."}
# Вводные, которых книге не сосчитать: за ними нормативные таблицы города, а не
# арифметика. Решение владельца (03.09.2026): «там где нет нормативных таблиц
# конечно берем из движка». Значит в книгу приходит РЕЗУЛЬТАТ — плата за ВРИ
# суммой, приобъектные места числом, — а сама вводная показывается основанием.
# Ячейку с ключом им заводить нельзя: правил бы человек, а не менялось бы
# ничего — ровно та болезнь, которую ловит сторож «вводная без читателя».
V4_INPUTS_NOT_IN_BOOK: dict[str, str] = {
    "vri_region": (
        "регион решает, по какой методике город считает плату за смену ВРИ; "
        "нормативных таблиц у книги нет, к ней приходит сумма (B16)"),
    "land_right": (
        "право на участок — второй множитель городской методики платы за ВРИ; "
        "в книгу приходит посчитанная сумма (B16)"),
    "parking_k1": (
        "К1 доступности рельсового каркаса — примечание 1 приложения 6 к "
        "945-ПП; книга нормативов не знает, к ней приходит число машино-мест "
        "в строке ТЭП"),
    "parking_rail_distance_m": (
        "расстояние до станции — вводная НОРМАТИВА, из неё считается К1; "
        "книга считает по числу мест, а не по норме, и ступень ей не нужна"),
    "parking_k2": (
        "К2 деловой активности района — 132 строки приложения 3 к 945-ПП; "
        "таблица заведена у движка (решение владельца 06.09.2026), но она "
        "вторая ступень после выгрузки ГлавАПУ, а не самостоятельная власть — "
        "и книге нормативов по-прежнему не нужно: к ней приходит число мест"),
    "parking_inside_ttk": (
        "положение участка относительно ТТК — вводная норматива (К2 по "
        "приложению 3 к 945-ПП) и льготы за МПТ (1874-ПП); владелец ответа — "
        "`site_position`, в книгу приходят число мест и сумма льготы"),
    "parking_design_mode": (
        "край норматива Московской области — выбор внутри нормативного расчёта; "
        "в книгу приходит его результат"),
    "sports_purpose": (
        "назначение объекта «ФОК / медцентр» решает, по какой строке считать "
        "приобъектную парковку: у Москвы спорт — 5.1, здравоохранение — 3.4, у "
        "области своей строки здравоохранения нет вовсе. Это вводная НОРМАТИВА, "
        "а не арифметики: книге приходит число мест, а имя объекта — подписью"),
    "vri_required": (
        "признак сам по себе не задаёт денежный поток книги: движок сначала "
        "нормализует обязательство и сумму платы, а книга получает уже сумму ВРИ"),
    "vri_obligation_date_mode": (
        "режим даты до книги превращается в применённую дату/лаг; варианты "
        "«через N месяцев» и «вручную» требуют движкового разрешения даты"),
    "vri_schedule_mode": (
        "ручной/автоматический график ВРИ разрешается движком до выгрузки; "
        "книга получает уже параметры применённого графика"),
    "vri_pf_open_date": (
        "дата открытия ПФ для досрочного погашения остатка ВРИ разрешается "
        "движком до книги; менять её без пересборки применённого графика нельзя"),
    "vri_in_bank_budget": (
        "признак банковского бюджета делит ВРИ между источниками до книги; "
        "в книгу приходят уже применённые доли финансирования"),
    "vri_financing_mode": (
        "режим источников оплаты ВРИ разрешается до расчёта долей; книга "
        "получает доли, а не сам алгоритм их определения"),
    "vri_relief_mode": (
        "форма льготы применяется при расчёте суммы ВРИ до книги; одна смена "
        "режима без исходной базы и методики льготы не воспроизводит движок"),
    "social_area_source": (
        "источник площади соцобъектов определяет места/метры до финансового "
        "расчёта; книга получает уже применённые физические параметры"),
    # Поля ниже показаны в книге, но ни одна её формула их не читает: движок
    # применяет их до выгрузки, а книге приходит результат. Ячейка со стилем
    # ввода, которую никто не читает, — обещание, а не вводная (сторож
    # test_every_workbook_input_is_alive), поэтому они объявлены здесь.
    "underground_parking_disabled": (
        "отказ от подземного паркинга — пересчёт ТЭП движком: места уходят в "
        "наземный, меняются площади и стоимость стройки; формулы шаблона "
        "читают уже пересчитанные строки ТЭП, а не признак"),
    "underground_area_per_space_sqm": (
        "норматив площади на машино-место применяется движком: площадь "
        "подземки очереди (колонка «База ГНС подземная») приезжает уже "
        "посчитанной; ни одна формула книги эту ячейку не читает"),
    "bridge_repay_lag_months": (
        "лаг погашения БРИДЖа после РнС применяется движком при построении "
        "графика рефинансирования; ни одна формула книги эту ячейку не читает"),
    "bridge_cap_spread_pp": (
        "спред капитализации БРИДЖа учитывается движком при капитализации "
        "процентов в ПФ; ни одна формула книги эту ячейку не читает"),
    "inflation_after_rve_pct": (
        "годовая инфляция после РВЭ входит в движковый профиль цены; ни одна "
        "формула книги эту ячейку не читает"),
    "vri_months_after_purchase": (
        "срок «через N месяцев после покупки» разрешается движком в применённую "
        "дату обязательства; книга получает саму дату"),
    "vri_obligation_date": (
        "дата обязательства по документу разрешается движком вместе с режимом "
        "даты; книга получает применённую дату, а не её источник"),
    "vri_initial_pct": (
        "первый взнос по рассрочке входит в движковый график платежей ВРИ; "
        "книга получает уже разложенный график"),
    "vri_share_bridge_pct": (
        "доля БРИДЖа в плате за ВРИ применяется движком при разделении "
        "источников; книга получает применённые потоки"),
    "vri_share_pf_pct": (
        "доля ПФ в плате за ВРИ применяется движком при разделении источников; "
        "книга получает применённые потоки"),
    "vri_share_equity_pct": (
        "доля собственных средств в плате за ВРИ применяется движком при "
        "разделении источников; книга получает применённые потоки"),
    "vri_relief_pct": (
        "льгота долей от платы применяется движком при расчёте суммы ВРИ; "
        "книга получает сумму после льготы"),
    "vri_transfer_offset_mln": (
        "зачёт переданных муниципалитету площадей вычитается движком из платы "
        "за ВРИ до книги; книга получает сумму после зачёта"),
    "social_mode": (
        "форма исполнения соцнагрузки решает, из чего складывается её сумма и "
        "срок; сумму (B17) и календарь считает движок, а формулы книги читают "
        "готовое число — смена слова в книге ничего не пересчитывает "
        "(решение владельца 26.09.2026: книгу не усложнять)"),
}
# Стратегия реализации ТЦ и офисов (`developaid_nonres_strategy`): аренду,
# кредит объекта и выход формулы шаблона не моделируют. В книгу приходит
# результат движка — лист «Нежильё — стратегия», — а вводные показываются
# основанием, как у платы за ВРИ.
V4_INPUTS_NOT_IN_BOOK.update({
    f"{_obj.prefix}_{_suffix}": (
        "стратегия реализации объекта (ДДУ / прямая продажа / доходный метод) "
        "и её параметры считаются движком; книга получает результат на листе "
        "«Нежильё — стратегия»")
    for _obj in STANDALONE_OBJECTS if _obj.strategies
    for _suffix in nonres_strategy.STRATEGY_FIELD_DEFAULTS
    if _obj.garage_sellable or _suffix != "parking_rent_th_month"})
# Назначение каждого экземпляра ФОКа — та же вводная норматива, что у первого.
V4_INPUTS_NOT_IN_BOOK.update({
    _obj.purpose_key: V4_INPUTS_NOT_IN_BOOK["sports_purpose"]
    for _obj in STANDALONE_OBJECTS if _obj.purpose_key})
# Ячейки, в которых значение ПОКАЗАНО, но книгой не читается ни одной
# формулой. Это не ввод: правка здесь не изменит ничего, а выглядит рабочей —
# «вводная, которую никто не читает, — не вводная, а обещание». Нашлись они
# счётом читателей: у цены квартир их 484, у этих ноль. На лист ввода они не
# едут намеренно: там печатают, а печатать здесь нечего.
# Ячейки, в которые движок пишет ПОСЧИТАННОЕ, а не поле вводных. Это не ошибка
# и не мусор шаблона: у книги одна ячейка на величину, у которой у движка два
# слагаемых. Но и сверять её с полем нельзя — она про другое, и молчаливое
# совпадение имени читалось бы как совпадение величины.
V4_INPUTS_COMPUTED_IN_THE_CELL: dict[str, str] = {
    "social_compensation_mln": (
        "в B17 идёт вся соцнагрузка — и денежная компенсация, и стоимость "
        "стройки садов, школ и поликлиник: у книги ключ соцнагрузки один, а "
        "движок берёт в расчётный лимит БРИДЖа только денежную часть"),
}
# DISPLAY-ONLY для пользовательских вводных больше не допускается: если книгу
# нельзя пересчитать офлайн, поле относится к engine-only и не выглядит
# редактируемым. Имя оставлено пустым ради обратной совместимости проверок.
V4_INPUTS_SHOWN_ONLY: dict[str, dict[str, str]] = {}

def _v4_field_label(key: str) -> str:
    """Подпись поля из канонического реестра вводных, без второй карты Excel."""
    for _group, fields in FIELD_GROUPS:
        for field in fields:
            if len(field) >= 2 and str(field[0]) == key:
                return str(field[1])
    for field in globals().get("_M2_RATE_INPUTS", ()):
        if len(field) >= 2 and str(field[0]) == key:
            return str(field[1])
    return key


def _v4_engine_only_rows() -> tuple[tuple[str, str, str], ...]:
    """Engine-only блок строится из того же реестра классификации."""
    return tuple(
        (key, _v4_field_label(key), reason)
        for key, reason in V4_INPUTS_NOT_IN_BOOK.items()
    )


def _v4_engine_only_rows_xml(xml: str, inputs: dict[str, Any]) -> tuple[str, int]:
    """Блок «считает движок» внизу «Вводных»: основание видно, править нечего.

    Число без основания и основание без числа одинаково бесполезны: по этой
    записи уже приходилось объяснять, откуда взялась плата за ВРИ. Значения
    показываются как есть — это ОСНОВАНИЕ применённого расчёта, а не поле.
    """
    import re as _re
    numbers = [int(number) for number in _re.findall(r'<x:row r="(\d+)"', xml)]
    base_row = (max(numbers) if numbers else 0) + 2
    parts: list[str] = []

    def text_cell(coord: str, value: str) -> str:
        return (f'<x:c r="{coord}" t="inlineStr"><x:is><x:t>'
                f"{xml_escape(value)}</x:t></x:is></x:c>")

    parts.append(f'<x:row r="{base_row}">'
                 + text_cell(f"A{base_row}", "СЧИТАЕТ ДВИЖОК · в книгу приходит результат")
                 + "</x:row>")
    hint = base_row + 1
    parts.append(f'<x:row r="{hint}">'
                 + text_cell(f"A{hint}", "За этими вводными нормативные таблицы города, "
                                         "а не арифметика: править их здесь нечем, "
                                         "видно основание применённого расчёта.")
                 + "</x:row>")
    for index, (key, label, where) in enumerate(_v4_engine_only_rows()):
        row = base_row + 2 + index
        value = inputs.get(key)
        if isinstance(value, bool):
            shown = "Да" if value else "Нет"
        elif value in (None, ""):
            shown = "не задано"
        else:
            shown = str(value)
        parts.append(
            f'<x:row r="{row}">'
            + text_cell(f"A{row}", label)
            + text_cell(f"B{row}", shown)
            + text_cell(f"C{row}", where)
            + text_cell(f"D{row}", key)
            + "</x:row>")
    tail = "</x:sheetData>"
    assert tail in xml
    return xml.replace(tail, "".join(parts) + tail, 1), base_row


_V4_SOCIAL_TYPES: tuple[tuple[str, str], ...] = (
    ("kindergarten", "ДОО"), ("school", "СОШ"), ("clinic", "Поликлиника"))


def _v4_social_total_of_gns() -> float:
    """Доля общей площади соцобъекта к его ГНС — та же, что у жилья.

    Движок считает ГНС соцобъекта как `общая / total_of_gns` (0,9). В книге
    этого числа не было вовсе, поэтому ГНС приезжала готовой — а значит после
    правки мест или площади прямо в книге оставалась прежней.
    """
    return float((TEP_RATIOS.get("apartments") or {}).get("total_of_gns") or 0.9)


def _v4_social_row(base_row: int, type_index: int, phase_index: int) -> int:
    """Строка пары «тип объекта × очередь» в блоке соцобъектов «Вводных»."""
    return base_row + 2 + type_index * 4 + phase_index


def _v4_social_cash_row(base_row: int) -> int:
    """Строка денежной компенсации совмещённого режима."""
    return base_row + 2 + len(_V4_SOCIAL_TYPES) * 4


def _v4_landscaping_rows_xml(xml: str, inputs: dict[str, Any],
                             tep: dict[str, Any]) -> tuple[str, str, str]:
    """Блок благоустройства внизу «Вводных»; → (xml, ячейка м²/чел., ячейка нормы).

    Благоустраивают ДВОР, а не дом: у статьи своя физическая база, и в книге её
    не было вовсе — строка 24 CAPEX умножала ставку на строительный объём. Пока
    ставка стояла 11,5 тыс ₽, это давало 2 060,2 млн ₽ там, где по норме 121,2:
    число посчитано верно, а прочитано неверно.

    Мера одна — м² на человека, и заданная руками площадь к ней приведена ещё в
    движке: тогда очередь считает свою площадь своим населением, и сумма
    очередей сходится с проектом. Норматив населения региональный, книге его не
    сосчитать — он приезжает числом с названным основанием, как К1 и К2.

    Блок дописывается в свободный низ листа: вставить строку в занятое место
    нельзя — поедут все ссылки.
    """
    import re as _re
    numbers = [int(number) for number in _re.findall(r'<x:row r="(\d+)"', xml)]
    base_row = (max(numbers) if numbers else 0) + 2
    parts: list[str] = []

    def text_cell(coord: str, value: str) -> str:
        return f'<x:c r="{coord}" t="inlineStr"><x:is><x:t>{xml_escape(value)}</x:t></x:is></x:c>'

    def number_cell(coord: str, value: float) -> str:
        return f'<x:c r="{coord}"{_v4_entry_attr()}><x:v>{_v4_number(round(value, 6))}</x:v></x:c>'

    per_person, basis = landscaping_area_per_person(inputs, tep)
    given = float(inputs.get("landscaping_area_sqm") or 0.0)
    population_norm = (MO_NORMS_DEFAULT["living_space_per_person_sqm"]
                       if str(inputs.get("vri_region") or "msk").lower() == "mo"
                       else _PARKING_2118_SQM_PER_PERSON)

    parts.append(f'<x:row r="{base_row}">'
                 + _v4_head_cell(f"A{base_row}", "БЛАГОУСТРОЙСТВО — ФИЗИЧЕСКАЯ ПЛОЩАДЬ ДВОРА")
                 + "</x:row>")
    hint = base_row + 1
    parts.append(f'<x:row r="{hint}">'
                 + text_cell(f"A{hint}", "Ставка благоустройства умножается на площадь "
                                         f"двора, а не на {CORE_TOTAL_AREA.lower()}. Площадь "
                                         "считает формула: население × метры на человека; "
                                         "население — площадь квартир очереди делённая на "
                                         "норматив региона.")
                 + "</x:row>")
    per_row = base_row + 2
    parts.append(f'<x:row r="{per_row}">'
                 + text_cell(f"A{per_row}", "Норматив площади на человека, м²/чел.")
                 + number_cell(f"B{per_row}", float(inputs.get(
                     "landscaping_area_per_person_sqm") or 0.0))
                 + text_cell(f"C{per_row}", "норматив класса проекта; работает, пока площадь "
                                            "двора ниже не задана")
                 + text_cell(f"D{per_row}", "landscaping_area_per_person_sqm")
                 + "</x:row>")
    given_row = base_row + 3
    parts.append(f'<x:row r="{given_row}">'
                 + text_cell(f"A{given_row}", "Заданная площадь двора, м² (0 — считать по нормативу)")
                 + number_cell(f"B{given_row}", given)
                 + text_cell(f"C{given_row}", "у человека на руках бывает ППТ или АГР со своей "
                                              "территорией; заданная площадь сильнее норматива")
                 + text_cell(f"D{given_row}", "landscaping_area_sqm")
                 + "</x:row>")
    gns_rate_row = base_row + 4
    parts.append(f'<x:row r="{gns_rate_row}">'
                 + text_cell(f"A{gns_rate_row}", "Ставка на метр ГНС, тыс ₽/м² "
                                                 "(0 — считать методикой двора)")
                 + number_cell(f"B{gns_rate_row}", float(inputs.get(
                     "landscaping_gns_th_per_sqm") or 0.0))
                 + text_cell(f"C{gns_rate_row}", "привычный сметчику показатель; заданный, "
                                                 "он сильнее методики двора — так же, как "
                                                 "заданная площадь сильнее норматива")
                 + text_cell(f"D{gns_rate_row}", "landscaping_gns_th_per_sqm")
                 + "</x:row>")
    norm_row = base_row + 5
    parts.append(f'<x:row r="{norm_row}">'
                 + text_cell(f"A{norm_row}", "Площадь квартир на человека (норматив региона), м²")
                 + number_cell(f"B{norm_row}", float(population_norm))
                 + text_cell(f"C{norm_row}", "приложение 5 к 945-ПП для Москвы, РНГП для области — "
                                             "норматив города, не наша величина")
                 + "</x:row>")
    # Применяемая мера — формулой, а не числом: иначе заданная площадь стоит на
    # листе вводной, которую никто не читает, — правка выглядит рабочей и не
    # меняет ничего. Население здесь ПРОЕКТНОЕ (сумма квартир всех очередей):
    # так приводит заданную площадь и движок, а очередь потом считает свой двор
    # своим населением, и сумма очередей сходится с проектом сама.
    flats = "+".join(f"$L${_V4_CF_QUEUE_ENABLED_ROW + phase}"
                     for phase in range(_V4_CAPEX_PHASES))
    applied_row = base_row + 6
    applied = (f'IF($B${given_row}&gt;0,$B${given_row}/MAX(1,ROUNDUP(({flats})'
               f'/MAX(1,$B${norm_row}),0)),$B${per_row})')
    parts.append(f'<x:row r="{applied_row}">'
                 + text_cell(f"A{applied_row}", "Применяется, м²/чел.")
                 + f'<x:c r="B{applied_row}"><x:f>{applied}</x:f></x:c>'
                 + text_cell(f"C{applied_row}", basis)
                 + "</x:row>")
    tail = "</x:sheetData>"
    assert tail in xml
    return (xml.replace(tail, "".join(parts) + tail, 1),
            f"$B${applied_row}", f"$B${norm_row}", f"$B${gns_rate_row}")


def _v4_apply_landscaping_base(xml: str, per_person: str, population_norm: str,
                               gns_rate: str, missing: list[str]) -> str:
    """Строка 24 каждого блока CAPEX считается от площади двора, а не от ГНС.

    Прежняя база — сумма трёх ГНС очереди; новая — её население по норме.
    Формула шаблона не опознана — `missing`, а не тихий пересчёт по прежней
    базе: расхождение книги с отчётом на порядок никто не заметит глазами.
    """
    row_at = _V4_CAPEX_ARTICLE_ROW["landscaping"]
    for phase in range(_V4_CAPEX_PHASES):
        base = _V4_CAPEX_BLOCK_STRIDE * phase
        row = row_at + base
        queue_row = _V4_CF_QUEUE_ENABLED_ROW + phase
        was = (f"('Вводные'!$I${queue_row}+'Вводные'!$J${queue_row}"
               f"+'Вводные'!$K${queue_row})")
        found = _re_search_cell_formula(xml, f"B{row}")
        if found is None or was not in found:
            missing.append(f"CAPEX · благоустройство: формула строки {row} не опознана")
            continue
        flats = f"'Вводные'!$L${queue_row}"
        yard = (f"(ROUNDUP({flats}/MAX(1,'Вводные'!{population_norm}),0)"
                f"*'Вводные'!{per_person})")
        # Две меры одной статьи, и книга умеет обе, как движок: заданная
        # ставка на метр ГНС сильнее методики двора (просьба владельца,
        # 14.09.2026). Подменяется вся пара «база × ставка» — у ветки ГНС и
        # база другая, и множитель. База здесь (I+J) — НАЗЕМНАЯ ГНС очереди
        # (I+J+K — строительный объём), и движок с 16.09.2026 считает ту же:
        # до этого он множил на метры дома без соцобъектов и ОСЗ, то есть на
        # заданной ставке книга и отчёт расходились на эти метры.
        above = f"('Вводные'!$I${queue_row}+'Вводные'!$J${queue_row})"
        # Ссылка шаблона абсолютная ($B$47), а карта ячеек несёт координату
        # без долларов: сравнение «в лоб» не находило её и уводило живую
        # формулу в `missing` — то есть сторож кричал бы на верной книге.
        _yard_cell = _V4_INPUT_CELLS["landscaping_th_per_sqm"]
        _yard_abs = "$" + _yard_cell[0] + "$" + _yard_cell[1:]
        yard_rate = f"'Вводные'!{_yard_abs}"
        was_pair = f"{was}*{yard_rate}"
        if was_pair not in found:
            missing.append(f"CAPEX · благоустройство: пара «база × ставка» строки {row} "
                           "не опознана")
            continue
        # Знак сравнения пишется СЫРЫМ: `_v4_set_cells` экранирует формулу сам,
        # и готовая сущность превратилась бы в `&amp;gt;` — книга открылась бы,
        # а вычислитель споткнулся.
        now = (f"IF('Вводные'!{gns_rate}>0,{above}*'Вводные'!{gns_rate},"
               f"{yard}*{yard_rate})")
        xml, done = _v4_set_cells(xml, row,
                                  {f"B{row}": dict(formula=found.replace(was_pair, now, 1))})
        if not done:
            missing.append(f"CAPEX · благоустройство: строка {row} не записана")
    return xml


def _v4_storage_area_cells(tep_xml: str, report_xml: str, missing: list[str]
                           ) -> tuple[str, str]:
    """Строки «Кладовые» листов ТЭП и ОТЧЕТ получают свою площадь.

    Обе строки в шаблоне владельца ЕСТЬ, и обе стоят пустыми: итоги над ними
    (`ТЭП!C8` = SUM(C4:C7), `ОТЧЕТ!B53` = SUM(B46:B52)) их складывают, то есть
    книга теряла метры кладовых в собственной таблице площадей. Ячейка без
    писателя выглядит как «у продукта нет площади», а не как наш пробел.

    Площадь берётся из колонки очереди (AR), а не пересчитывается вторым
    правилом: второй ответ на «сколько метров у кладовых» разошёлся бы с
    первым, и обе строки выглядели бы верными.
    """
    stride, first = _V4_TEP_PHASE_STRIDE, _V4_TEP_STORAGE_ROW
    for index in range(_V4_CAPEX_PHASES):
        row = first + stride * index
        queue_row = _V4_CF_QUEUE_ENABLED_ROW + index
        tep_xml, done = _v4_set_cells(tep_xml, row, {f"C{row}": dict(
            formula=f"'Вводные'!$AR${queue_row}")})
        if not done:
            missing.append(f"ТЭП · площадь кладовых очереди {index + 1}")
    # На ОТЧЕТе колонка называет то, что в ней лежит: B — «ГНС наземная», а
    # `{under}` — «Подземная». Кладовые лежат ПОД землёй, и их метры стояли в
    # наземной: итог B складывал их с квартирами и коммерцией, и «ГНС наземная»
    # книги выходила больше движковой ровно на площадь кладовых. Ноль в B —
    # ответ («наземной части у продукта нет»), а не пробел.
    #
    # На ТЭП колонка одна и названа честно — «ГНС / подземная площадь», —
    # поэтому там кладовые остаются в C.
    report_xml, done = _v4_set_cells(report_xml, _V4_REPORT_STORAGE_ROW, {
        f"B{_V4_REPORT_STORAGE_ROW}": dict(formula="0"),
        f"{_V4_UNDER_COLUMN}{_V4_REPORT_STORAGE_ROW}": dict(
            formula="SUM('Вводные'!AR88:AR91)")})
    if not done:
        missing.append("ОТЧЕТ · площадь кладовых")
    return tep_xml, report_xml


def _v4_apply_storage_area_rows(xml: str, missing: list[str]) -> str:
    """Статьи CAPEX, чья база — подземная часть или строительный объём, видят
    площадь кладовых.

    Кладовые прибавляют подземную площадь, а не вычитаются из гаража (решение
    владельца, 13.09.2026), и движок считает базу как «паркинг плюс кладовые»
    (`core_under_gns`). Книга кладовых не знала вовсе: колонка K несёт только
    площадь паркинга, а строки «Кладовые» листов ТЭП и ОТЧЕТ стоят в шаблоне
    пустыми — при том что итоги НАД ними их складывают. На 400 кладовых по 4 м²
    это 1 600 м² подземной части и 140,8 млн ₽ СМР, потерянных молча.

    Правятся три формы базы, и каждая своя:
      · строительный объём проекта `SUM($I$88:$K$91)` — ИРД, П, РД, подготовка,
        сети (их движок делит кассовыми долями);
      · строительный объём очереди `($I$r+$J$r+$K$r)` — сдача и содержание;
      · подземная часть очереди `$K$r` — основное строительство под землёй.
    Благоустройство сюда не входит: его база — двор, а не объём, и к этому
    моменту `_v4_apply_landscaping_base` уже сняла у него сумму трёх ГНС.
    Формула шаблона не опознана — `missing`, а не тихий счёт по прежней базе.
    """
    area = "'Вводные'!$AR$%d"
    volume_was = "SUM('Вводные'!$I$88:$K$91)"
    volume_now = f"({volume_was}+SUM('Вводные'!$AR$88:$AR$91))"
    xml, count = xml.replace(volume_was, volume_now), xml.count(volume_was)
    expect = len(_V4_SHARED_CASH_ARTICLES) * _V4_CAPEX_PHASES
    if count != expect:
        missing.append(f"CAPEX · {CORE_TOTAL_AREA.lower()}: формула общепроектных статей "
                       f"не опознана ({count} из {expect})")
    for phase in range(_V4_CAPEX_PHASES):
        base = _V4_CAPEX_BLOCK_STRIDE * phase
        queue_row = _V4_CF_QUEUE_ENABLED_ROW + phase
        # Подземная часть очереди: K → (K + площадь кладовых).
        row = _V4_CAPEX_ARTICLE_ROW["main_under"] + base
        was = f"'Вводные'!$K${queue_row}"
        found = _re_search_cell_formula(xml, f"B{row}")
        if found is None or was not in found:
            missing.append(f"CAPEX · СМР подземной части: формула строки {row} не опознана")
        else:
            now = f"({was}+{area % queue_row})"
            xml, done = _v4_set_cells(xml, row, {f"B{row}": dict(
                formula=found.replace(was, now, 1))})
            if not done:
                missing.append(f"CAPEX · СМР подземной части: строка {row} не записана")
        # Строительный объём очереди: (I+J+K) → (I+J+K+площадь кладовых).
        for key in ("commissioning", "site_maintenance"):
            row = _V4_CAPEX_ARTICLE_ROW[key] + base
            was = (f"('Вводные'!$I${queue_row}+'Вводные'!$J${queue_row}"
                   f"+'Вводные'!$K${queue_row})")
            found = _re_search_cell_formula(xml, f"B{row}")
            if found is None or was not in found:
                missing.append(f"CAPEX · объём очереди: формула строки {row} не опознана")
                continue
            now = was[:-1] + f"+{area % queue_row})"
            xml, done = _v4_set_cells(xml, row, {f"B{row}": dict(
                formula=found.replace(was, now, 1))})
            if not done:
                missing.append(f"CAPEX · объём очереди: строка {row} не записана")
    return xml


def _re_search_cell_formula(xml: str, coord: str) -> str | None:
    """Формула ячейки как она стоит в XML — или None, если её там нет."""
    found = re.search(r'<x:c r="%s"[^>]*><x:f>(.*?)</x:f>' % re.escape(coord), xml, re.S)
    return found.group(1) if found else None


def _v4_storage_norm_rows_xml(xml: str, inputs: dict[str, Any],
                              tep: dict[str, dict[str, Any]]
                              ) -> tuple[str, str, float]:
    """Площадь одной кладовой — вводной ячейкой, и книга считает метры от штук.

    Прежде площадь кладовых приезжала в книгу ГОТОВЫМ числом: правка их штук
    внутри книги не двигала ни подземной площади, ни СМР — «если величина в
    книге не выражается формулой, значит не хватает не формулы, а вводной».
    Здесь стоит ФАКТИЧЕСКИЙ показатель проекта (метры ÷ штуки), как у
    норматива соцобъекта в режиме «Требование КРТ»: заданная руками площадь
    сильнее норматива, и подменить её нормативом класса значило бы показать
    в книге другой проект.

    Блок дописывается в свободный низ листа: вставить строку в занятое место
    нельзя — поедут все ссылки.
    """
    import re as _re
    numbers = [int(number) for number in _re.findall(r'<x:row r="(\d+)"', xml)]
    base_row = (max(numbers) if numbers else 0) + 2
    row = (tep or {}).get("storage") or {}
    units = _underground_number(row, "units")
    area = _underground_number(row, "gns")
    per = round(area / units, 4) if units > 0 and area > 0 else storage_area_per_unit(inputs)
    basis = ("фактический показатель проекта: площадь ÷ штуки"
             if units > 0 and area > 0 else "норматив класса проекта")
    parts = [f'<x:row r="{base_row}">'
             + _v4_head_cell(f"A{base_row}", "КЛАДОВЫЕ — ПЛОЩАДЬ ОДНОЙ")
             + "</x:row>",
             f'<x:row r="{base_row + 1}">'
             + f'<x:c r="A{base_row + 1}" t="inlineStr"><x:is><x:t>'
             + xml_escape("Площадь одной кладовой, м²/шт.")
             + "</x:t></x:is></x:c>"
             + f'<x:c r="B{base_row + 1}"{_v4_entry_attr()}>'
             + f"<x:v>{_v4_number(per)}</x:v></x:c>"
             + f'<x:c r="C{base_row + 1}" t="inlineStr"><x:is><x:t>'
             + xml_escape(basis + "; штуки кладовых стоят в блоке очередей "
                                  "(AC — к продаже, AP — переданные), и метры "
                                  "считаются от них")
             + "</x:t></x:is></x:c>"
             + f'<x:c r="D{base_row + 1}" t="inlineStr"><x:is><x:t>'
             + xml_escape("storage_area_per_unit_sqm")
             + "</x:t></x:is></x:c>"
             + "</x:row>"]
    tail = "</x:sheetData>"
    assert tail in xml
    return (xml.replace(tail, "".join(parts) + tail, 1),
            f"$B${base_row + 1}", per)


def _v4_social_rows_xml(xml: str, rows: dict[tuple[int, str], dict[str, Any]],
                        cost_per: dict[str, float], months_by_type: dict[str, int],
                        cash_mln: float, areas: dict[str, tuple[float, float]] | None = None
                        ) -> tuple[str, int]:
    """Дописывает блок соцобъектов в конец листа «Вводные»; возвращает базу строк.

    Как и лестница ставок, блок пишется строками XML в свободный низ листа:
    вставлять строку в занятое место нельзя — поедут все ссылки. Строка есть у
    каждой пары «тип × очередь», даже пустой: формула CAPEX ссылается на них
    всегда, а включить объект прямо в книге иначе было бы негде.
    """
    import re as _re
    numbers = [int(number) for number in _re.findall(r'<x:row r="(\d+)"', xml)]
    base_row = (max(numbers) if numbers else 0) + 2
    parts: list[str] = []

    def text_cell(coord: str, value: str) -> str:
        return f'<x:c r="{coord}" t="inlineStr"><x:is><x:t>{xml_escape(value)}</x:t></x:is></x:c>'

    def number_cell(coord: str, value: float) -> str:
        # Всё, что здесь число, человек и правит: мест, цена места, начало,
        # срок, множитель, площадь и норматив. Стоимость объекта (F) — формула,
        # и она пишется отдельно.
        return f'<x:c r="{coord}"{_v4_entry_attr()}><x:v>{_v4_number(round(value, 6))}</x:v></x:c>'

    parts.append(f'<x:row r="{base_row}">'
                 + _v4_head_cell(f"A{base_row}", "СОЦИАЛЬНЫЕ ОБЪЕКТЫ — КАЛЕНДАРЬ СТРОЙКИ")
                 + "</x:row>")
    header = base_row + 1
    parts.append(
        f'<x:row r="{header}">'
        + _v4_head_cell(f"A{header}", "Объект и очередь")
        + _v4_head_cell(f"B{header}", "Мест / мощность")
        + _v4_head_cell(f"C{header}", "Стоимость места, млн ₽")
        + _v4_head_cell(f"D{header}", "Начало")
        + _v4_head_cell(f"E{header}", "Срок, мес.")
        + _v4_head_cell(f"F{header}", "Стоимость, млн ₽")
        + _v4_head_cell(f"G{header}", "Множитель инфляции очереди")
        + _v4_head_cell(f"H{header}", "Ключ API: мест")
        + _v4_head_cell(f"I{header}", "Ключ API: цена места")
        + _v4_head_cell(f"J{header}", "Ключ API: начало")
        + _v4_head_cell(f"K{header}", "Ключ API: срок")
        + _v4_head_cell(f"L{header}", "Площадь объекта, м²")
        + _v4_head_cell(f"M{header}", "Норматив, м²/место")
        + _v4_head_cell(f"N{header}", "Ключ API: площадь")
        + _v4_head_cell(f"O{header}", "Ключ API: норматив")
        + _v4_head_cell(f"P{header}", "Доля общей площади к ГНС")
        + "</x:row>")
    for type_index, (typ, label) in enumerate(_V4_SOCIAL_TYPES):
        # Ключ движка ставится только там, где строка несёт ВСЮ вводную: тип
        # стоит в одной очереди. Раскиданный по очередям объект — это доли
        # одной вводной, и подписать ими проектный ключ значило бы назвать
        # часть целым (по этой же причине свод не подписывают именем момента).
        carriers = [phase for phase in range(4)
                    if float((rows.get((phase, typ)) or {}).get("capacity") or 0.0) > 0]
        # Объекта нет вовсе — ключ идёт первой очереди: ноль это тоже вся
        # вводная, и включают объект именно там, а строка без ключа выглядит
        # как «этого поля в книге нет».
        sole = carriers[0] if len(carriers) == 1 else (0 if not carriers else None)
        for phase_index in range(4):
            row = _v4_social_row(base_row, type_index, phase_index)
            slot = rows.get((phase_index, typ)) or {}
            serial = _v4_excel_serial(str(slot.get("start") or "")[:10]) if slot else None
            keys = _V4_SOCIAL_KEYS[typ] if phase_index == sole else ("", "", "", "")
            parts.append(
                f'<x:row r="{row}">'
                + text_cell(f"A{row}", f"{label} — очередь {phase_index + 1}")
                + number_cell(f"B{row}", float(slot.get("capacity") or 0.0))
                + number_cell(f"C{row}", float(cost_per.get(typ, 0.0)))
                + number_cell(f"D{row}", float(serial) if serial is not None else 0.0)
                + number_cell(f"E{row}", float(slot.get("months")
                                               or months_by_type.get(typ, 24)))
                + f'<x:c r="F{row}"><x:f>$B{row}*$C{row}*$G{row}</x:f></x:c>'
                + number_cell(f"G{row}", float(slot.get("factor") or 1.0))
                + ("".join(text_cell(f"{letter}{row}", key)
                           for letter, key in zip("HIJK", keys) if key))
                # Площадь и норматив — свойство ТИПА, а не очереди: они стоят
                # ОДИН раз, на первой строке типа, иначе одна вводная жила бы
                # четырьмя копиями с разными значениями. Первой строке, а не
                # той, что несёт ключ мест: ключ мест ходит за единственной
                # очередью объекта и исчезает, когда очередей две, — а площадь
                # у типа есть всегда. Цена привязки к ключу измерена: садик на
                # 465 мест в двух очередях получал в книге площадь 0 м² при
                # 7 440 у движка, и ГНС соцобъекта вместе с ней.
                + ("".join((
                    number_cell(f"L{row}", float((areas or {}).get(typ, (0.0, 0.0))[0])),
                    number_cell(f"M{row}", float((areas or {}).get(typ, (0.0, 0.0))[1]),),
                    text_cell(f"N{row}", _V4_SOCIAL_AREA_KEYS[typ][0]),
                    text_cell(f"O{row}", _V4_SOCIAL_AREA_KEYS[typ][1]),
                )) if phase_index == 0 else "")
                # Доля общей площади к ГНС — одна на все три объекта, и стоит
                # она один раз: три копии одного числа разошлись бы. Без неё
                # ГНС соцобъекта в книге считать нечем, и она приезжала числом.
                + (number_cell(f"P{row}", _v4_social_total_of_gns())
                   if (type_index, phase_index) == (0, 0) else "")
                + "</x:row>")
    cash_row = _v4_social_cash_row(base_row)
    # Дата платежа — методикой движка: min(заданная B18, РнС − 1 мес.).
    # Число здесь не двигалось бы от правки РнС прямо в книге, а из обрезанного
    # числа не видно, что за ним стоит правило.
    parts.append(
        f'<x:row r="{cash_row}">'
        + text_cell(f"A{cash_row}", "Денежная компенсация (совмещённый режим)")
        + f'<x:c r="D{cash_row}"><x:f>'
        + xml_escape(f'IF($B$18="",{_V4_SOCIAL_DEADLINE},'
                     f"MIN($B$18,{_V4_SOCIAL_DEADLINE}))") + "</x:f></x:c>"
        # Колонки E у денежного платежа нет: у объектов это срок стройки, и
        # формула делит на неё стоимость (F/E). Денежная часть платится одним
        # платежом в свою дату — делить не на что, и стоявшая здесь единица
        # была жёлтой ячейкой, которую правят, а не читает ни одна формула.
        + number_cell(f"F{cash_row}", float(cash_mln))
        + "</x:row>")
    tail = "</x:sheetData>"
    assert tail in xml
    return xml.replace(tail, "".join(parts) + tail, 1), base_row


def _v4_social_capex_formula(base_row: int, phase_index: int, column: str) -> str:
    """Расход очереди за месяц: каждый объект — ровной долей своего окна.

    Ровно то, что считает движок (`cost / span_months` по месяцам от старта
    объекта), но выраженное ячейками: сдвинули начало или срок — поехал график.
    """
    parts = []
    for type_index in range(len(_V4_SOCIAL_TYPES)):
        row = _v4_social_row(base_row, type_index, phase_index)
        parts.append(
            f"IF(AND('Вводные'!$F${row}>0,{column}$3>='Вводные'!$D${row},"
            f"{column}$3<EDATE('Вводные'!$D${row},'Вводные'!$E${row})),"
            f"'Вводные'!$F${row}/'Вводные'!$E${row},0)")
    if phase_index == 0:
        # Денежная часть совмещённого режима — одним платежом в свою дату:
        # это другое обязательство с другим сроком, и движок платит его порознь.
        cash_row = _v4_social_cash_row(base_row)
        parts.append(
            f"IF(AND('Вводные'!$F${cash_row}>0,"
            f"YEAR({column}$3)=YEAR('Вводные'!$D${cash_row}),"
            f"MONTH({column}$3)=MONTH('Вводные'!$D${cash_row})),"
            f"'Вводные'!$F${cash_row},0)")
    return "+".join(parts)


# Строки шаблона, чьи ФОРМУЛЫ выгрузка переписывает под методику движка.
# У хардов («формула шаблона стала числом») сторож есть с 0.21.77, а у правки
# формулы формулой не было: 302 строки чужой методики переписываются двадцатью
# проходами, и новая безымянная правка прошла бы молча — ровно как проходил
# безымянный хард. Здесь названы строки и причина; строка вне списка краснеет.
# Замена «'Вводные'!» → «'Параметры модели'!» правкой не считается: это переезд
# ввода на свой лист, методики он не трогает.
V4_REWRITTEN_FORMULA_ROWS: dict[str, tuple[tuple[int, ...], str]] = {
    "Дашборд": (
        (2, 5, 10) + tuple(range(15, 44)),
        "Лист собирается заново по ТЗ владельца (19.09.2026, состав страницы "
        "«Итог» 21.09.2026): формулы на скрытый источник Dashboard_Data, "
        "шесть карточек KPI, эффективность, ТЭП, доходы, цены и темп, "
        "себестоимость, структура расходов, финансовая деятельность, риски, "
        "сроки очередей и три диаграммы; прежние карточки ОТЧЕТ и квартальные "
        "ряды CF переехали в источник (v4_dashboard.build)",
    ),
    "CAPEX": (
        (
        9, 12, 14, 15, 16, 17, 18, 20, 21, 22, 23, 24, 25, 26, 27, 28, 29, 30,
        31, 32, 43, 46, 48, 49, 50, 51, 52, 54, 55, 56, 57, 58, 59, 60,
        61, 62, 63, 64, 65, 66, 77, 80, 82, 83, 84, 85, 86, 88, 89, 90, 91, 92,
        93, 94, 95, 96, 97, 98, 99, 100, 111, 114, 116, 117, 118, 119, 120, 122,
        123, 124, 125, 126, 127, 128, 129, 130, 131, 132, 133, 134,
        ),
        "Кассовые доли общих статей, снос и расселение, график платежей "
        "за покупку, профиль управления, лимит БРИДЖа до РнС и календари "
        "объектов: _v4_apply_shared_cash_articles, "
        "_v4_apply_demolition_rows, _v4_apply_purchase_schedule, "
        "_v4_apply_management_profile, "
        "_v4_apply_bridge_limit_before_permit; техзаказчик и генподряд без "
        "стройки объектов «под ключ», резерв без платы за ВРИ (решение "
        "владельца 06.10.2026): _v4_apply_turnkey_overheads; у чисто "
        "нежилого проекта — полная смета: статьи проекта от площади объектов, "
        "генподряд, техзаказчик и управление на их СМР: "
        "_v4_apply_nonres_full_estimate "
    ),
    "CF": (
        (
        31, 37,
        ),
        "Первый облагаемый месяц свода — самый ранний РВЭ включённых "
        "очередей — и сводный налог по методике движка: годовая база с "
        "переносом убытка и половинным ограничением ст. 283 "
    ),
    "CF_1": (
        (
        21, 22, 40, 41, 42, 43, 44, 45, 46, 47, 57, 58, 61,
        ),
        "Ставка ПФ по методике движка со ступенями, горизонт начисления, "
        "признак закрытой линии, перенос долга между очередями, "
        "кэш-свип и признание процентов в месяце начисления "
        "(_v4_apply_interest_accrual); строка 45 — выборка ПФ, обрезанная одобренным лимитом (_v4_apply_pf_ceiling) "
    ),
    "CF_2": (
        (
        21, 22, 40, 41, 42, 43, 44, 45, 46, 47, 57, 58, 61,
        ),
        "Ставка ПФ по методике движка со ступенями, горизонт "
        "начисления, признак закрытой линии, перенос долга между "
        "очередями, кэш-свип и признание процентов в месяце "
        "начисления (_v4_apply_interest_accrual); строка 45 — выборка ПФ, обрезанная одобренным лимитом (_v4_apply_pf_ceiling) "
    ),
    "CF_3": (
        (
        21, 22, 40, 41, 42, 43, 44, 45, 46, 47, 57, 58, 61,
        ),
        "Ставка ПФ по методике движка со ступенями, горизонт "
        "начисления, признак закрытой линии, перенос долга между "
        "очередями, кэш-свип и признание процентов в месяце "
        "начисления (_v4_apply_interest_accrual); строка 45 — выборка ПФ, обрезанная одобренным лимитом (_v4_apply_pf_ceiling) "
    ),
    "CF_4": (
        (
        21, 22, 40, 41, 42, 43, 44, 45, 46, 47, 57, 58, 61,
        ),
        "Ставка ПФ по методике движка со ступенями, горизонт "
        "начисления, признак закрытой линии, перенос долга между "
        "очередями, кэш-свип и признание процентов в месяце "
        "начисления (_v4_apply_interest_accrual); строка 45 — выборка ПФ, обрезанная одобренным лимитом (_v4_apply_pf_ceiling) "
    ),
    "ВРИ": (
        (
        7, 9, 12, 13, 20, 22, 25, 26, 33, 35, 38, 39, 46, 48, 51, 52,
        ),
        "Рассрочка начинается в дату обязательства, начисление "
        "помесячное на остатке конца месяца, проценты с обеспечением "
        "своей строкой вне базы резерва "
    ),
    "Вводные": (
        (
        8, 26, 46,
        ),
        "Читалки живых ячеек вместо мёртвых (лаг старта продаж и тренд "
        "темпа берут значение из колонок очередей); строка 46 — продаваемая "
        "площадь ТЦ после размещения паркинга первых этажей считается от "
        "остаточной GBA (_v4_object_parking_input_labels) "
    ),
    "КОНСОЛИДАТОР": (
        (
        4, 5, 6, 7, 8, 30, 31, 32, 33,
        ),
        "Свод по очередям с учётом четвёртого объекта и переноса долга; "
        "доля налога очереди берётся из блока раздачи по годам внизу листа "
        "(_v4_tax_share_by_year) "
    ),
    "ОБЪЕКТЫ": (
        (
        13, 14, 15, 17, 18, 20, 22, 23, 25, 26, 27, 28, 29, 30, 41, 42,
        43, 45, 46, 48, 50, 51, 53, 54, 55, 56, 57, 58, 70, 71, 73, 74,
        76, 78, 79, 81, 82, 83, 84, 92, 93, 94, 95, 96, 97, 98, 100,
        101, 102, 103, 104, 105, 106, 108, 109, 110, 111, 112, 113, 114,
        116, 117, 118, 119, 120, 121, 122,
        ),
        "Четвёртый объект (ФОК) и его признак «продаётся / передаётся», "
        "графики объёма и цены, лестница этапов, старт не раньше РнС "
        "своей очереди; гараж объекта: его метры вычитаются из наземной "
        "площади здания (13, 41 — места на первых этажах × площадь "
        "места), а маркетинг и продажи считаются от площади объекта "
        "вместе с гаражом (29, 30, 57, 58) "
    ),
    "ОТЧЕТ": (
        (
        2, 12, 33, 45, 46, 47, 48, 49, 50, 51, 52, 53, 54, 58, 61,
        ),
        f"Наземная ГНС, {TOTAL_AREA.lower()}, непогашенный долг при "
        "переносе между очередями и чистая прибыль из строк того же "
        "листа (12); покупка вместе с выкупом ЗУ/ОКС у третьих лиц (33, "
        "_v4_deal_includes_buyout) "
    ),
    "ПРОВЕРКИ": (
        (
        3, 29, 32, 39, 40, 42, 43, 45, 46, 48, 50, 51, 52, 53, 54, 55, 57,
        58, 59, 71, 72, 76, 77, 78, 79, 80, 81, 82, 83, 84,
        ),
        "Строка 32 знает про одобренный лимит: разрыв, им объяснённый, — "
        "WARN, а не FAIL, и факт берётся из строк непокрытой потребности "
        "листов CF, а не вторым таким же вычитанием. "
        "Строки паритета и самопроверки под четвёртый объект, перенос "
        "долга, кэш-свип и гараж отдельно стоящего объекта: его метры уходят "
        "из продаваемой, его CAPEX входит в расход объекта, а его выручка — "
        "в суммы выручки продуктов и объектов; вердикт строк паритета "
        "(76–84) — общий с дописанными ниже и с гейтом правленых вводных "
    ),
    "Продажи": (
        (
        7, 8, 9, 10, 12, 14, 15, 17, 18, 20, 21, 23, 24, 30, 31, 32, 33,
        35, 37, 38, 40, 41, 43, 44, 46, 47, 53, 54, 55, 56, 58, 60, 61,
        63, 64, 66, 67, 69, 70, 76, 77, 78, 79, 81, 83, 84, 86, 87, 89,
        90, 92, 93,
        ),
        "Лестница цены по этапам готовности, множитель роста после РВЭ, "
        "продаваемые места без гостевых и переданных "
    ),
    "Ставки": (
        (
        5,
        ),
        "Кривая ключевой ставки по своему сценарию (rate_scenario), а не "
        "по активному сценарию проекта "
    ),
    "ТЭП": (
        (
        4, 5, 6, 7, 10, 11, 12, 13, 16, 17, 18, 19, 22, 23, 24, 25, 31,
        32, 33, 34, 36,
        ),
        "Наземная и подземная площади своими колонками, продаваемые "
        "места и метры без гостевых и переданных, строка ФОКа "
    ),
}

V4_ENGINE_WRITTEN_CELLS: dict[tuple[str, str], str] = {
    ("Вводные", "B77"): (
        "Срок рассрочки ВРИ — ВВОДНАЯ (ключ vri_installment_years), а не вывод "
        "из строки B75: формула шаблона разбирала слово «3 года» из ячейки "
        "режима, то есть держала режим и срок одним текстом. С dropdown режим "
        "стоит в B75 отдельно, а срок — числом здесь; формулы графика читают "
        "B77 как число лет и не изменились"),
    ("ТЭП", "E34"): (
        "Строка 34 была итогом блока объектов, а стала строкой ФОКа: итог "
        "переехал на пустую строку 35, ссылок на 31–35 нет ни на одном другом "
        "листе. Колонка «Единицы» у строк объектов пуста — у офисов, ТЦ и "
        "наземного паркинга тоже: они меряются метрами, — и формула суммы "
        "здесь была бы суммой пустых клеток. Продаваемая площадь ФОКа стоит "
        "в своей колонке D, а не здесь"),
    ("Вводные", "B18"): (
        "Заданная дата денежной компенсации — это ВВОДНАЯ (ключ social_comp_date), "
        "а не результат: формула шаблона стояла здесь потому, что места под "
        "введённую дату в книге не было вовсе. Правило движка "
        "min(заданная, РнС − 1 мес.) переехало к читателю — в строку денежной "
        "компенсации блока соцобъектов. Дата не задана — здесь снова формула"),
}


def v4_hard_value_reason(sheet: str, coord: str) -> str | None:
    """Причина, по которой в клетке стоит число, а не формула. Нет — значит хард."""
    direct = V4_ENGINE_WRITTEN_CELLS.get((sheet, coord))
    if direct:
        return direct
    row = "".join(ch for ch in coord if ch.isdigit())
    return V4_ENGINE_WRITTEN_CELLS.get((sheet, f"строка {row}"))


class _SkipValueCache(Exception):
    """Проход сохранённых значений выключен — это выбор, а не сбой."""


# Статьи сметы, которые книга нежилого проекта формулой не повторяет:
# благоустройство считается методикой двора, соцобъекты — программой и своими
# графиками, рассрочка ВРИ — с процентами на остаток. Они приходят в книгу
# значениями движка и называются в `missing`, а не выглядят посчитанными.
NONRES_BOOK_ENGINE_ARTICLES = ("landscaping", "social", "vri_interest", "vri_security")


def nonres_book_spec(prepared: dict[str, Any], consolidated: dict[str, Any],
                     project_name: str = "") -> dict[str, Any]:
    """Вводные книги нежилого проекта — те же числа, которые читает движок.

    Каждое значение берётся тем же вызовом `n(x, ключ, умолчание)`, что в
    `build_operating_model` и `developaid_nonres_strategy.object_flows`; книга
    дальше считает всё своими формулами, а лист «Сверка» сравнивает её итоги с
    авторитетным расчётом (`consolidated`). Разойдись здесь умолчание — сверка
    покраснеет, а не промолчит.
    """
    x, t, rates = prepared["x"], prepared["t"], prepared["rates"] or []
    op = build_operating_model(x, t, rates)
    start = op["project_start"]
    months = [d(m) for m in (consolidated.get("cashflow") or {}).get("months") or []]
    scenario = str(x.get("rate_scenario", "low"))
    scenario_key = scenario if scenario in ("high", "base", "low") else "base"
    # Прогноз — всеми тремя сценариями: выбор сценария в книге — список, и
    # он обязан менять ставку, а не только подпись. Пропуск в строке — прежнее
    # значение сценария, как у `rate_lookup`.
    rate_table: list[dict[str, Any]] = []
    held = {key: float(rates[0].get(key, 0.0)) if rates else 0.0 for key in ("low", "base", "high")}
    for row in rates:
        held = {key: float(row.get(key, held[key])) for key in held}
        rate_table.append({"date": d(row["date"]), **held})

    def k_of(month: date) -> int:
        return months_between(start, month)

    # Выкуп ЗУ/ОКС платится графиком покупки в той же пропорции, без цены
    # участка — тем же графиком сам по себе: доли одни на обе суммы.
    payments, _ = purchase_payment_plan(
        (n(x, "purchase_price_mln") or n(x, "land_buyout_mln")) * 1_000_000,
        x.get("purchase_schedule"), start, op["end"])
    paid = sum(amount for _, amount in payments)
    plan: dict[int, float] = defaultdict(float)
    for when, amount in payments:
        plan[k_of(when)] += amount / paid if paid else 0.0
    vri = op.get("vri") or {}
    vri_gross = n(x, "land_rights_cost_mln") * 1_000_000
    relief, _net = vri_relief(x, vri_gross)
    by_article = op.get("capex_by_article") or {}
    engine_articles = {}
    for key in NONRES_BOOK_ENGINE_ARTICLES + (("land_rights",) if vri.get("enabled") else ()):
        schedule = {k_of(m): float(v) for m, v in (by_article.get(key) or {}).items() if v}
        if schedule:
            engine_articles[key] = schedule
    nonres_plans = op.get("nonres_plans") or {}
    objects = []
    for obj in standalone_objects():
        if not b(x, obj.enabled_key):
            continue
        row = t.get(obj.key) or {}
        item: dict[str, Any] = {
            "key": obj.key, "prefix": obj.prefix, "title": obj.tep_label or obj.label,
            "measure": obj.measure,
            "volume": n(x, f"{obj.prefix}_spaces") if obj.measure == "spaces" else n(x, f"{obj.prefix}_gba_sqm"),
            "rate_cost": n(x, obj.rate_cost),
            "garage": bool(obj.garage), "under_gns": n(row, "under_gns") if obj.garage else 0.0,
            # Что включает ставка — тот же предикат, что у движка.
            "turnkey": object_rate_is_turnkey(x, obj),
            "start": d(x[f"{obj.prefix}_start"]),
            "months": int(n(x, f"{obj.prefix}_months", obj.default_months)),
            "in_tax_pool": (not obj.sale_gate) or object_is_sold(x, obj),
            "nonres": obj.key in nonres_plans,
        }
        plan_item = nonres_plans.get(obj.key)
        if plan_item:
            params = plan_item.get("params") or {}
            num = nonres_strategy._num
            choice = nonres_strategy._choice
            item.update({
                "strategy": plan_item["strategy"],
                "saleable_sqm": n(x, f"{obj.prefix}_saleable_sqm"),
                "over_units": max(0.0, n(row, "parking_over_units")),
                "over_area": (n(x, "object_parking_over_area_per_space_sqm", OBJECT_PARKING_OVER_AREA_DEFAULT)
                              or OBJECT_PARKING_OVER_AREA_DEFAULT),
                "price": n(x, obj.rate_price),
                "sales_start": d(x[f"{obj.prefix}_sales_start"]),
                "growth_pre_pct": n(x, f"{obj.prefix}_growth_pre_pct", obj.growth_pre_default),
                # Откуда число: владелец спросил, чьё это «1 % в месяц». Умолчание
                # объекта — `StandaloneObject.growth_pre_default` реестра; у жилья
                # своё — `monthly_growth_pre_pct`.
                "growth_pre_default_pct": float(obj.growth_pre_default),
                "growth_post_pct": n(x, f"{obj.prefix}_growth_post_pct", obj.growth_post_default),
                "parking_sellable": bool(obj.garage_sellable),
                "parking_saleable_units": n(row, "parking_saleable_units") if obj.garage_sellable else 0.0,
                "parking_under_units": max(0.0, n(row, "parking_under_units")),
                "parking_over_units": max(0.0, n(row, "parking_over_units")),
                "parking_under_mln": n(x, f"{obj.prefix}_parking_under_price_mln_per_space"),
                "parking_over_mln": n(x, f"{obj.prefix}_parking_over_price_mln_per_space"),
                # Умолчания — те, что у `object_flows`, а не у формы.
                "params": {
                    "loan_share_pct": num(params, "loan_share_pct", 60.0),
                    "loan_spread_pp": num(params, "loan_spread_pp", 4.0),
                    "loan_fee_pct": num(params, "loan_fee_pct", 1.0),
                    "property_tax_pct": num(params, "property_tax_pct", 2.2),
                    "debt_repayment": choice(params, "debt_repayment", nonres_strategy.REPAYMENTS,
                                             nonres_strategy.REPAY_ANNUITY),
                    "loan_term_years": num(params, "loan_term_years", 10),
                    "loan_balloon_pct": num(params, "loan_balloon_pct", 20.0),
                    "direct_sale_offset_months": num(params, "direct_sale_offset_months", 0),
                    "direct_sale_months": num(params, "direct_sale_months", 12),
                    "direct_sale_curve": choice(params, "direct_sale_curve", nonres_strategy.SALE_CURVES, "flat"),
                    "rent_th_per_sqm_month": num(params, "rent_th_per_sqm_month", 0.0),
                    "parking_rent_th_month": num(params, "parking_rent_th_month", 0.0),
                    "rent_index_pct": num(params, "rent_index_pct", 0.0),
                    "occupancy_start_pct": num(params, "occupancy_start_pct", 0.0),
                    "occupancy_stable_pct": num(params, "occupancy_stable_pct", 0.0),
                    "leaseup_months": num(params, "leaseup_months", 12),
                    "opex_pct": num(params, "opex_pct", 0.0),
                    "hold_years": num(params, "hold_years", 5),
                    "exit_mode": choice(params, "exit_mode", (nonres_strategy.EXIT_SALE, nonres_strategy.EXIT_HOLD),
                                        nonres_strategy.EXIT_SALE),
                    "exit_cap_pct": num(params, "exit_cap_pct", 11.0),
                    "exit_cost_pct": num(params, "exit_cost_pct", 1.0),
                    "depreciation_years": num(params, "depreciation_years", 30),
                },
            })
        objects.append(item)
    missing = [f"Смета: «{key}» — значения движка, формулы в книге нет"
               for key in engine_articles]
    if any(op.get("revenue") or {}):
        missing.append("Выручка продуктов по ДДУ — в книге нежилого проекта не моделируется")
    return {
        "name": project_name,
        "start": start, "months": months,
        "ird_months": int(n(x, "ird_months", 18)), "ird_min": IRD_MONTHS_MIN,
        "construction_months": int(n(x, "construction_months", 24)),
        "residual_months": int(n(x, "residual_sales_months", 6)),
        "vat_pct": max(0.0, n(x, "vat_pct", 22)),
        "profit_tax_pct": n(x, "profit_tax_pct", 25),
        "discount_pct": n(x, "discount_rate_pct", 20),
        "loss_limit": _LOSS_CARRY_USE_LIMIT,
        "revenue_mult": n(x, "scenario_revenue_multiplier", 1.0),
        "cost_mult": n(x, "scenario_cost_multiplier", 1.0),
        "marketing_pct": n(x, "marketing_pct"), "selling_pct": n(x, "selling_pct"),
        "rate_scenario": scenario_key, "rate_table": rate_table,
        "core_above_gns": float(op.get("core_above_gns") or 0.0),
        "core_under_gns": float(op.get("core_under_gns") or 0.0),
        "parking_price_th": n(x, "parking_price_th"),
        "main_under_th": n(x, "main_under_th_per_sqm"),
        "cost": {
            "ird_th": n(x, "ird_th_per_sqm"), "design_p_th": n(x, "design_p_th_per_sqm"),
            "design_rd_th": n(x, "design_rd_th_per_sqm"),
            "demolition_area": n(x, "demolition_area_sqm"),
            "demolition_th": n(x, "demolition_cost_th_per_sqm"),
            "resettlement_mln": n(x, "resettlement_cost_mln"),
            "preparation_th": n(x, "preparation_th_per_sqm"),
            "main_above_th": n(x, "main_above_th_per_sqm"),
            "utilities_th": n(x, "utilities_th_per_sqm"),
            "commissioning_th": n(x, "commissioning_th_per_sqm"),
            "site_maintenance_th": n(x, "site_maintenance_th_per_sqm"),
            "author_supervision_pct": n(x, "author_supervision_pct", 0.0),
            "project_management_pct": n(x, "project_management_pct", 5.0),
            "technical_supervision_pct": n(x, "technical_supervision_pct", 0.0),
            "gc_fee_pct": n(x, "gc_fee_pct"), "reserve_pct": n(x, "reserve_pct"),
        },
        "purchase_price_mln": n(x, "purchase_price_mln"),
        "land_buyout_mln": n(x, "land_buyout_mln"),
        "reservation_fee_pct": n(x, "reservation_fee_pct"),
        "limit_fee_pct": n(x, "limit_fee_pct"),
        "purchase_plan": sorted(plan.items()),
        "land_rights_gross_mln": n(x, "land_rights_cost_mln"),
        "land_rights_relief_mln": relief / 1_000_000,
        "vri_enabled": bool(vri.get("enabled")),
        "engine_articles": engine_articles,
        # Статьи без резерва — список движка, а не второй в книге.
        "reserve_excluded": sorted(RESERVE_EXCLUDED_ARTICLES),
        "vri_equity": {k_of(m): float(v) for m, v in (op.get("vri_equity") or {}).items() if v},
        "objects": objects,
        "missing": missing,
    }


def _nonres_project_workbook(inputs: dict[str, Any], tep: dict[str, Any],
                             rates: list[dict[str, Any]] | None,
                             phasing: dict[str, Any] | None,
                             project_name: str) -> tuple[bytes, str, dict[str, Any]] | None:
    """Книга нежилого проекта, если у него нет ДДУ; иначе None — книга v4.

    Решение «есть ли у проекта БРИДЖ/ПФ/эскроу» — то же `report.layout`, что
    читают страница, PDF, тизер и бот.
    """
    consolidated = (_run_authoritative_model(
        inputs or {}, tep or {}, rates or [], phasing or {}) or {}).get("consolidated") or {}
    layout = (consolidated.get("report") or {}).get("layout") or {}
    if layout.get("project_finance", True) or not layout.get("nonres_strategy"):
        return None
    prepared = prepared_calculation(copy.deepcopy(inputs or {}), copy.deepcopy(tep or {}),
                                    copy.deepcopy(rates or []))
    spec = nonres_book_spec(prepared, consolidated, project_name)
    phased = bool((phasing or {}).get("enabled") and int((phasing or {}).get("phase_count") or 1) > 1)
    if phased:
        spec["missing"].append("Очереди: книга моделирует проект одной очередью, "
                               "сверка идёт со сводом очередей")
    content = nonres_workbook.build(consolidated, spec)
    stem = _safe_file_stem(project_name or "project", "project")
    filename = f"DevelopAid_нежилой_{stem}_{date.today().isoformat()}.xlsx"
    return content, filename, {"missing": list(spec["missing"]), "phased": phased,
                               "class_deviations": [], "nonres_book": True}


def _hotel_project_workbook(inputs: dict[str, Any], tep: dict[str, Any],
                            rates: list[dict[str, Any]] | None,
                            phasing: dict[str, Any] | None,
                            project_name: str) -> tuple[bytes, str, dict[str, Any]]:
    """Книга гостиничного проекта из того же авторитетного расчёта, что отчёт."""
    consolidated = (_run_authoritative_model(
        inputs or {}, tep or {}, rates or [], phasing or {}) or {}).get("consolidated") or {}
    content = hotel_workbook.build(consolidated, project_name)
    stem = _safe_file_stem(project_name or "project", "project")
    filename = f"DevelopAid_гостиница_{stem}_{date.today().isoformat()}.xlsx"
    hotel = (consolidated.get("finance") or {}).get("hotel") or {}
    missing = [f"Гостиница · {label}" for label in hotel.get("missing") or []]
    spec = (hotel.get("book") or {}).get("capex_spec") or {}
    labels = spec.get("article_labels") or {}
    missing += [f"Гостиница · {labels.get(key, key)}: исходный график движка, без формулы сметы"
                for key, schedule in (spec.get("engine_articles") or {}).items() if schedule]
    return content, filename, {"missing": missing, "phased": False, "class_deviations": [],
                               "hotel_book": True}


def build_project_workbook(
    inputs: dict[str, Any],
    tep: dict[str, dict[str, Any]],
    rates: list[dict[str, Any]] | None = None,
    phasing: dict[str, Any] | None = None,
    **kwargs: Any,
) -> tuple[bytes, str, dict[str, Any]]:
    """Книга DevelopAid v4 — с дописанными объектами ЭТОГО проекта.

    Второй объект пишется в книгу, только когда он включён: проект без него
    получает ту же книгу, что и до его появления в реестре (`_V4_BOOK_OBJECTS`).
    """
    merged = {**DEFAULT_INPUTS, **(inputs or {})}
    # Гостиничный проект — своя книга (`hotel_workbook`): помесячный расчёт
    # формулами, годовой USALI, итоги и сверка с движком. Книга v4 построена
    # на ДДУ, эскроу и ПФ, которых у гостиницы нет.
    if is_hotel(merged):
        return _hotel_project_workbook(inputs, tep, rates, phasing,
                                       str(kwargs.get("project_name") or ""))
    # Нежилой проект без ДДУ получает свою книгу (`nonres_workbook`): книга v4
    # построена на ДДУ, эскроу и ПФ, которых у него нет (владелец, 04.10.2026:
    # отчёт, тизер и книга нежилого проекта — самостоятельные).
    if is_nonresidential(merged):
        nonres_book = _nonres_project_workbook(inputs, tep, rates, phasing,
                                               str(kwargs.get("project_name") or ""))
        if nonres_book is not None:
            return nonres_book
    # Экземпляр вне состава проекта в книгу не пишется, даже включённый.
    merged = object_instances_applied(merged, {})[0]
    token = _V4_BOOK_OBJECTS.set(_v4_book_objects(merged))
    try:
        return _build_project_workbook(inputs, tep, rates, phasing, **kwargs)
    finally:
        _V4_BOOK_OBJECTS.reset(token)


def _build_project_workbook(
    inputs: dict[str, Any],
    tep: dict[str, dict[str, Any]],
    rates: list[dict[str, Any]] | None = None,
    phasing: dict[str, Any] | None = None,
    *,
    project_name: str = "",
    scenario: str = "base",
    finance_hints: dict[str, Any] | None = None,
    cache_values: bool | None = None,
) -> tuple[bytes, str, dict[str, Any]]:
    """Книга DevelopAid v4, заполненная текущими вводными.

    Пишутся только значения листа «Вводные»; весь расчёт — формулы книги.
    Ячейка без соответствия уходит в meta["missing"], а не молчит.
    """
    # Книга считает по ТОМУ ЖЕ ТЭП, что и движок: приобъектный паркинг
    # раскладывается по строкам объектов здесь же. Без этого строки приходят
    # без своей подземной площади и без мест, и книга строит проект, которого
    # движок не считал, — то есть ровно два достоверных на вид документа.
    # Отпечаток расчёта снимается с ПРИСЛАННЫХ вводных, а не с производных от
    # них: он отвечает на «по чему это посчитано», и книга с PDF обязаны нести
    # один и тот же. Правка ТЭП до отпечатка подписала бы книгу другим расчётом.
    calculation_source_tep = tep
    tep = copy.deepcopy(tep or {})
    applied_parking = apply_object_parking(inputs, tep)

    x = {**DEFAULT_INPUTS, **{k: v for k, v in (inputs or {}).items() if not str(k).startswith("_")}}
    # Книга считает то же, что движок, и по типу проекта тоже: плата за ВРИ,
    # соцкомпенсация и места соцобъектов нежилого проекта в ячейки не идут —
    # тот же предикат, что у движка, а не своя проверка. Движок ниже получает
    # присланное: остаток он называет сам.
    engine_tep = tep
    x, tep = residential_excluded(x, tep)
    x, tep = object_instances_applied(x, tep)
    # Лимиты финансирования — из движка: книжная пропорция от CAPEX-блоков
    # занижала лимит ПФ очереди с офисами, и плата за невыбранный лимит
    # выходила вдвое меньше движковой. Поверхности считают один раз: бот
    # передаёт готовый результат, остальные пути считают здесь; при падении
    # движка книга остаётся на собственных формулах долей.
    p = phasing or {}
    missing: list[str] = []
    if finance_hints is None:
        try:
            finance_hints = _v4_finance_hints(_run_authoritative_model(
                inputs or {}, engine_tep or {}, rates or [], phasing or {}))
        except Exception as exc:
            # Молчать здесь нельзя: без контрольных чисел лист ПРОВЕРОК выглядит
            # просто пустым, и «паритет не считался» неотличимо от «паритет
            # сошёлся». Причина уходит туда же, куда неопознанная формула.
            finance_hints = {}
            missing.append("контрольные числа движка: " + _error_location(exc))

    # Книга считает по ТОМУ ЖЕ ТЭП, что и отчёт. Присланная страницей строка —
    # не то, на чём посчитано: `calculate` приводит её к вводным, и правки
    # книга не видела. Приобъектный паркинг в применённом ТЭП уже разложен,
    # поэтому второй раз его звать нельзя — `apply_object_parking` не
    # идемпотентна, метры первых этажей вычитаются из продаваемой при каждом
    # вызове. Справка о паркинге снята выше, на присланном ТЭП: она считается
    # от вводных и от подмены строки не зависит.
    _tep_applied = (finance_hints or {}).get("tep_applied") or {}
    if _tep_applied:
        tep = {key: dict(value) for key, value in _tep_applied.items()
               if isinstance(value, dict)}
    else:
        missing.append(
            "ТЭП движка: книга пишет присланный — строка, приведённая расчётом "
            "к вводным (площадь гаража, выгрузка ГлавАПУ, соцобъект), до неё не дошла")
        # Строку гаража выводит одна функция, и без ответа движка книга зовёт
        # её сама: иначе она продавала бы места за вычетом гостевых присланной
        # строки (из умолчаний шаблона), а движок — за вычетом своих.
        # Строка правится на копии: присланный ТЭП принадлежит вызывающему.
        tep = {key: dict(value) for key, value in (tep or {}).items()
               if isinstance(value, dict)}
        apply_underground_tep_row({**DEFAULT_INPUTS, **(inputs or {})}, tep)

    # Сетка книги конечна, а горизонт движка — нет. Не влезло — это `missing`
    # числами, а не молчание: обрезанная книга выглядит целой, и половина её
    # показателей при этом верна (БРИДЖ живёт в первых колонках и сходится),
    # то есть ошибка не выглядит ошибкой.
    horizon = int((finance_hints or {}).get("horizon_months") or 0)
    if horizon > _V4_MONTH_COLUMNS:
        missing.append(
            f"горизонт расчёта {horizon} мес. длиннее сетки книги "
            f"({_V4_MONTH_COLUMNS} мес.): последние {horizon - _V4_MONTH_COLUMNS} "
            f"в книгу не поместились. Протянуть сетку — "
            f"scripts/widen_v4_horizon.py")

    # Статья «по объёму» стоит в phasing словом; числа посчитал движок и
    # отдал в подсказках. Книга берёт их оттуда — второго счёта долей нет.
    if any(isinstance(v, str) for v in (p.get("shared_cash") or {}).values()):
        applied_shares = (finance_hints or {}).get("shared_cash_applied") or {}
        p = dict(p)
        shares = dict(p.get("shared_cash") or {})
        for key, value in list(shares.items()):
            if not isinstance(value, str):
                continue
            if applied_shares.get(key):
                shares[key] = [float(w) for w in applied_shares[key]]
            else:
                shares.pop(key)
                missing.append(f"кассовая доля «{key}» по объёму: движок не отдал применённые доли, книга берёт умолчание")
        p["shared_cash"] = shares
        phasing = p

    template = _V4_TEMPLATE_PATH.read_bytes()
    source = zipfile.ZipFile(io.BytesIO(template))
    sheet_path = _v4_inputs_sheet_path(source)
    xml = source.read(sheet_path).decode("utf-8")

    def put(coord: str, *, number=None, text=None, formula=None, label=""):
        nonlocal xml
        xml, done = _v4_set_cell(xml, coord, number=number, text=text, formula=formula)
        if not done:
            missing.append(label or coord)

    def put_new(coord: str, *, number=None, text=None, formula=None, label=""):
        """То же, но заводит ячейку и строку, если их в шаблоне нет.

        Нужно там, где вводная встаёт в СВОЙ блок, а не в конец листа: между
        блоками «Вводных» есть пустые строки, и в XML их не существует.
        """
        nonlocal xml
        row = int("".join(ch for ch in coord if ch.isdigit()))
        xml = _v4_ensure_row(xml, row)
        xml, done = _v4_set_or_insert_cell(
            xml, coord, number=number, text=text, formula=formula)
        if not done:
            missing.append(label or coord)

    # Блок ФОКа дописывается ДО того, как вводные разъезжаются по ячейкам:
    # `put` умеет только заменять существующую ячейку, а строк 121–140 в
    # шаблоне нет вовсе.
    xml = _v4_extra_inputs_blocks(xml, missing)
    xml = _v4_object_parking_input_labels(xml, missing)

    def num_row(row: dict[str, Any] | None, field: str) -> float:
        try:
            return float((row or {}).get(field) or 0)
        except Exception:
            return 0.0

    # Вводная, которую никто не читает, — не вводная, а обещание. «Лаг старта
    # продаж» (B68) и «Тренд темпа продаж» (B66) не читает НИ ОДНА формула
    # книги: соседи по блоку читаются сотнями и тысячами ссылок, а эти две —
    # нулём. Работу делают колонки очередей G и AD, где у лага и тренда своё
    # значение на очередь. Жёлтая клетка правится, и не меняется ничего.
    # Поэтому здесь читалка, а не вводная: голубым, ссылкой на первую очередь,
    # и ключ уезжает к той ячейке, которая работает.
    put("B66", formula="AD88", label="тренд темпа продаж — читалка очереди 1")
    put("D66", text="правится в блоке очередей, колонка AD")
    put("B68", formula="G88", label="лаг продаж — читалка очереди 1")
    put("D68", text="правится в блоке очередей, колонка G")

    # Подпись ключа берётся из самой карты, а не из шаблона: у B69 в шаблоне
    # стояло «sales_term_default_months», а движок пишет туда
    # residual_sales_months — одно число под двумя именами, и сверить книгу с
    # движком по ключу было нельзя. Ключ живёт там же, где решается, куда
    # писать значение, — второго списка «какой ключ в какой ячейке» не бывает.
    # Вводные объекта, которого в этой книге нет, не пишутся вовсе: ни ключ,
    # ни значение (`_v4_input_in_book`).
    for key, coord in _V4_INPUT_CELLS.items():
        if not _v4_input_in_book(key):
            continue
        if coord.startswith("B"):
            put("D" + coord[1:], text=key, label=f"ключ {key}")
        elif coord.startswith("K"):
            put("M" + coord[1:], text=key, label=f"ключ {key}")

    # --- скалярные вводные по карте ключей -------------------------------
    for key, coord in _V4_INPUT_CELLS.items():
        value = (_V4_DERIVED_INPUTS[key](x) if key in _V4_DERIVED_INPUTS
                 else x.get(key))
        if value in (None, "") or not _v4_input_in_book(key):
            continue
        if key in _V4_DATE_KEYS:
            serial = _v4_excel_serial(value)
            if serial is not None:
                put(coord, number=serial, label=key)
            continue
        try:
            number = float(value)
        except Exception:
            missing.append(f"{key}: не число ({value!r})")
            continue
        if (key.endswith("_pct") or key.endswith("_pp")) and key not in _V4_NO_PCT_KEYS:
            number /= 100.0
        put(coord, number=number, label=key)

    # Зачёт переданных муниципалитету площадей уменьшает плату так же, как
    # льгота, и в книге ложится в ту же ячейку: строку в шаблон не вставить —
    # поедут все ссылки, а формулы листов ВРИ и ОТЧЁТ вычитают именно B82.
    # Разбивка «льгота отдельно, зачёт отдельно» остаётся в приложении и в
    # отчёте; книге важно, чтобы плата к оплате совпадала с движком.
    # Считает льготу тот же код, что и движок (`vri_relief`), а не копия его
    # правил: в книгу писалось поле «льгота — сумма», и всё, что льготой не
    # является суммой, до неё не доезжало. Льгота долей (МПТ — обычный случай
    # для Москвы) обнуляла плату в отчёте и оставляла её целиком в книге:
    # 0 против 4 674 млн ₽ на 77:04:0001019:173, при одинаковых вводных.
    try:
        vri_gross = max(0.0, float(x.get("land_rights_cost_mln") or 0)) * 1_000_000
    except Exception:
        vri_gross = 0.0
        missing.append("land_rights_cost_mln: не число")
    relief_amount, _net = vri_relief(x, vri_gross)
    # Книга несёт ПРИМЕНЁННОЕ размещение, а не желаемое: у выключенного объекта
    # гаража нет, сколько бы мест ни осталось в его полях. Та же развилка была
    # у переноса долга между очередями — ячейка несёт решение, которое
    # СОСТОЯЛОСЬ. Норматив сюда не заглядывает вовсе: приобъектная стоянка это
    # асфальт, и однажды взятая источником этих чисел она построила книге
    # гараж, которого никто не заказывал.
    _prefix_of = {tep_key: prefix for tep_key, prefix, _, _ in OBJECT_PARKING_OBJECTS}
    for _item in applied_parking.get("own") or []:
        _prefix = _prefix_of.get(_item.get("tep_key"))
        if not _prefix:
            continue
        for _kind, _field in (("under", "under_spaces"), ("over", "over_spaces")):
            _key = f"{_prefix}_parking_{_kind}_spaces"
            _coord = _V4_INPUT_CELLS.get(_key)
            if not _coord or not _v4_input_in_book(_key):
                continue
            xml, _done = _v4_set_or_insert_cell(
                xml, _coord, number=int(_item.get(_field) or 0))
            if not _done:
                missing.append(f"паркинг объектов: применённое размещение {_coord}")

    put(_V4_INPUT_CELLS["vri_relief_mln"], number=round(relief_amount / 1_000_000, 6),
        label="льгота по плате за ВРИ (движковая: доля, сумма и зачёт вместе)")

    for key, coord in _V4_BOOL_CELLS.items():
        if _v4_input_in_book(key):
            put(coord, text="Да" if x.get(key) else "Нет", label=key)

    # Признак ФОКа — не «Да/Нет», а «куда уходит объект»: у него два ответа, и
    # оба содержательные. Формула продаваемой площади читает именно это слово.
    for _lay in _v4_extras():
        if _lay.disposition_row:
            put(f"K{_lay.disposition_row}",
                text=(_V4_OBJECT_SALE_WORD if object_is_sold(x, _lay.obj)
                      else _V4_OBJECT_TRANSFER_WORD),
                label=_lay.obj.sale_gate)

    # Признак переноса долга между очередями. Стоит рядом с остальными Да/Нет,
    # но живёт в phasing, а не во вводных проекта: это условие сделки с банком,
    # а не свойство площадки.
    xml = _v4_write_carry_flag(
        xml, bool((finance_hints or {}).get("carry_applied")), missing,
        sweep_share=float((finance_hints or {}).get("cash_sweep_share") or 0.0))

    # Ставка, ушедшая от базы класса, помечается рядом со значением: молча
    # книга и отчёт «одного класса» разойдутся, и оба будут выглядеть верно.
    class_deviations = project_class_deviations(x)
    for item in class_deviations["rows"]:
        coord = _V4_INPUT_CELLS.get(item["field"])
        if not coord or not _v4_input_in_book(item["field"]):
            continue
        note = f"≠ база класса «{class_deviations['label']}»: {item['base']:g}"
        xml, done = _v4_note_cell(xml, coord, note)
        if not done:
            missing.append(f"примечание о классе: {item['field']}")

    # --- шапка, сценарий и ставка ----------------------------------------
    title = str(project_name or x.get("project_name") or "Проект DevelopAid")
    put("B4", text=title, label="project_name")
    # B6 — не надпись, а ключ: книга ищет его MATCH'ем по списку сценариев
    # («Base»/«Optimistic»/…), русское слово роняет весь расчёт.
    put("B6", text="Base", label="scenario")
    put("E5", number=float(x.get("scenario_revenue_multiplier") or 1), label="scenario_revenue_multiplier")
    put("E6", number=float(x.get("scenario_cost_multiplier") or 1), label="scenario_cost_multiplier")
    start_serial = _v4_excel_serial(x.get("project_start")) or _v4_excel_serial("2027-01-01")
    put("B8", number=start_serial, label="project_start")
    put("B36", number=start_serial, label="price_cost_base_date")
    # Дата платежа денежной компенсации — ЗАДАННАЯ, а не уже обрезанная.
    # Методика движка (social_cash_payment_date) — min(заданная, РнС − 1 мес.):
    # компенсация платится в бридж-период, после РнС линия рефинансирована.
    # Обрезка живёт в формуле читателя, а не в записанном числе: обрезанное
    # число не двигалось от правки РнС прямо в книге, а введённая дата в нём
    # уже не видна — человек правил бы результат правила, не зная об этом.
    _book_permit = add_months(str(x.get("project_start") or "2027-01-01")[:10],
                              int(max(float(IRD_MONTHS_MIN), n(x, "ird_months", 18.0))))
    # Пустая дата остаётся ПУСТОЙ, а не подменяется формулой крайнего срока:
    # ячейка жёлтая, то есть по конвенции «вписано руками», и формула в ней —
    # ложное приглашение (впишешь число, как цвет и зовёт, — затрёшь её).
    # Запасной путь живёт у читателя вместе с самой обрезкой: там он и нужен.
    _wanted_social_date = _v4_excel_serial(str(x.get("social_comp_date") or "")[:10])
    if _wanted_social_date is None:
        put("B18", text="", label="social_comp_date")
    else:
        put("B18", number=_wanted_social_date, label="social_comp_date")
    # Конец горизонта движка: он не выводится из РВЭ, а тянется за последним
    # денежным потоком — стройка садика заканчивается позже РВЭ + 12 месяцев и
    # растягивает расчёт. Книга знала только календарную часть правила и
    # переставала начислять проценты ПФ там, где долг ещё жив: три месяца и
    # 8,8 млн ₽ мимо на садике 250 мест. Формула берёт максимум из своей
    # границы и этой даты — правка сроков прямо в Excel по-прежнему двигает
    # границу вслед за РВЭ.
    try:
        # Вводные — те же `x`, что у ячеек: сырые продлили бы горизонт
        # стройкой садика, которого нежилой проект не строит.
        _horizon = build_operating_model(dict(x), tep or {}, rates or [])["end"]
        put("B71", number=_v4_excel_serial(_horizon.isoformat()) or 0.0,
            label="engine_horizon_end")
    except Exception:
        put("B71", number=0.0, label="engine_horizon_end")
    # Сезонность: в движке одно значение на январь и май–август.
    seasonal = float(x.get("seasonal_reduction_pct") or 0) / 100.0
    # Сезонность у движка ОДНА вводная на оба окна, а шаблон подписал их своими
    # именами — тот же случай, что sales_term_default_months над остаточными
    # продажами: одно число под двумя чужими именами, и сверить нечем.
    put("B67", number=seasonal, label="seasonal_reduction_pct (январь)")
    put("D67", text="seasonal_reduction_pct")
    put("B70", number=seasonal, label="seasonal_reduction_pct (май–август)")
    put("D70", text="seasonal_reduction_pct")
    put("B31", text=str(x.get("bridge_interest_mode") or "Капитализация в ПФ"),
        label="bridge_interest_mode")
    # Форма исполнения соцнагрузки: книге она нужна не для расходов (те
    # приходят суммой в B17), а для базы комиссии выдачи БРИДЖа. Движок берёт
    # в расчётный лимит только денежную компенсацию, стройку — нет, а B17
    # несёт обе, и без признака комиссия считалась и со стройки.
    put("B37", text=str(x.get("social_mode") or "Строительство"),
        label="social_mode")

    # Социалка строительством: в книге v4 один канал соцнагрузки —
    # компенсация (B17). Без свёртки стоимость строительства садов, школ и
    # поликлиники выпадала из расходов книги целиком — у Мытищ это миллиарды,
    # и LLCR книги завышался против движка. Сумма индексируется как в движке:
    # каждый объект раскладывается по очередям той же
    # _phase_social_allocation, и его стоимость растёт с инфляцией затрат к
    # старту своей очереди — базовая сумма занижала социалку на 12%.
    # График строительства при этом сворачивается в разовый платёж за месяц
    # до РнС (дата B18 — формула книги): приближение, но расход не теряется.
    social_cash_by_phase: list[float] | None = None
    social_monthly_by_phase: list[list[float]] | None = None
    social_base_row: int | None = None
    social_rows: dict[tuple[int, str], dict[str, Any]] = {}
    social_cash_mln = 0.0
    cost_per: dict[str, float] = {}
    months_by_type: dict[str, int] = {}
    social_breakdown = {typ: {"places": 0.0, "cost": 0.0, "phases": set()}
                        for typ in ("kindergarten", "school", "clinic")}
    social_is_construction = str(x.get("social_mode") or "") in ("Строительство", SOCIAL_MODE_BOTH)
    if social_is_construction:
        social_count = max(1, min(4, int(p.get("phase_count") or 1) if p.get("enabled") else 1))
        social_phases = list(p.get("phases") or [])
        # Отсутствующий ключ — не ноль: движок без cost_inflation_pct берёт
        # 8% годовых, и социалка поздних очередей растёт тем же фактором.
        social_inflation = (float(p.get("cost_inflation_pct", 8.0) or 0) / 100.0
                            if social_count > 1 else 0.0)
        cost_per = {
            "kindergarten": float(x.get("kindergarten_cost_mln_per_place") or 0),
            "school": float(x.get("school_cost_mln_per_place") or 0),
            "clinic": float(x.get("clinic_cost_mln_per_unit") or 0),
        }
        objects = [dict(obj) for obj in (p.get("social_objects") or []) if isinstance(obj, dict)]
        if not objects:
            for typ, key in (("kindergarten", "kindergarten_places"),
                             ("school", "school_places"), ("clinic", "clinic_capacity")):
                capacity = float(x.get(key) or 0)
                if capacity > 0:
                    objects.append({"type": typ, "capacity": capacity, "auto": True})
        if objects:
            _phase_social_allocation(objects, social_count)
        social_build = 0.0
        social_build_by_phase = [0.0, 0.0, 0.0, 0.0]
        # Расшифровка для ОТЧЁТа и ТЭП: сумма B17 приезжала чёрным ящиком,
        # и «где расходы на садик и школы» было не увидеть нигде в книге.
        for obj in objects:
            phase_index = max(1, min(social_count, int(obj.get("phase") or 1))) - 1
            offset_months = (float(social_phases[phase_index].get("start_offset_months") or 0)
                             if phase_index < len(social_phases) else 0.0)
            factor = (1.0 + social_inflation) ** (offset_months / 12.0)
            cost = (float(obj.get("capacity") or 0)
                    * cost_per.get(str(obj.get("type") or "kindergarten"), 0.0) * factor)
            social_build += cost
            social_build_by_phase[min(phase_index, 3)] += cost
            slot = social_breakdown.get(str(obj.get("type") or "kindergarten"))
            if slot is not None:
                slot["places"] += float(obj.get("capacity") or 0)
                slot["cost"] += cost
                slot["phases"].add(phase_index + 1)
        if social_build > 0:
            # Только стройка: движок в режиме «Строительство» денежную
            # компенсацию не платит вовсе — либо одно, либо другое. Сложение
            # обеих сумм задваивало социалку на ГлавАПУ-проекте с компенсацией
            # в вводных: 774 млн в книге против 166 у движка, минус 648 млн
            # EBITDA и плюс 11% к пику БРИДЖа.
            # В совмещённом режиме проект и строит, и платит: в книге канал
            # соцнагрузки один, поэтому в B17 идёт сумма обеих форм, а
            # денежная часть дублируется в B56 — из неё считается база
            # комиссии выдачи БРИДЖа, куда стройка не входит.
            cash_part = (n(x, "social_compensation_mln")
                         if str(x.get("social_mode")) == SOCIAL_MODE_BOTH else 0.0)
            put("B17", number=social_build + cash_part,
                label="социалка строительством" + (" и компенсацией" if cash_part else ""))
            put("B56", number=cash_part, label="денежная часть соцнагрузки")
            # Кассовые доли R — по очередям объектов: «всё в первую» верно
            # для денежной компенсации, а стройка платится там, где стоит
            # объект. Доля 100% в О1 перегружала её ПФ на миллиарды и
            # уводила первую очередь в дефолт при гасящем долг движке.
            social_cash_by_phase = [share / social_build
                                    for share in social_build_by_phase]
            # Помесячный график соцстройки — готовыми числами по очередям:
            # единое окно B18/E18 платило социалку всех очередей одним куском,
            # а движок строит каждый объект в своей очереди — объект без
            # своей даты стартует со старта очереди, введённая дата раньше
            # очереди объекту не положена. Расхождение держало БРИДЖ первой
            # очереди на сотни миллионов меньше движка.
            months_by_type = {
                "kindergarten": max(1, int(float(x.get("kindergarten_months") or 24))),
                "school": max(1, int(float(x.get("school_months") or 30))),
                "clinic": max(1, int(float(x.get("clinic_months") or 24))),
            }
            project_start_iso = str(x.get("project_start") or "2027-01-01")[:10]
            # Атомарный движок (одна очередь) строит по введённым датам типов;
            # подмена «объект стартует со старта своей очереди» — только
            # фазовая. Иначе single-режим строил социалку с первого месяца
            # и завышал пик БРИДЖа на десять процентов.
            typed_starts = {
                "kindergarten": str(x.get("kindergarten_start") or "")[:10],
                "school": str(x.get("school_start") or "")[:10],
                "clinic": str(x.get("clinic_start") or "")[:10],
            }
            # Движок агрегирует объекты типа внутри фазы: сумма мест и
            # минимальная из собственных дат; общие вводные даты в
            # фазированном режиме не участвуют.
            grouped: dict[tuple[int, str], dict[str, Any]] = {}
            for obj in objects:
                phase_index = max(1, min(social_count, int(obj.get("phase") or 1))) - 1
                typ = str(obj.get("type") or "kindergarten")
                slot = grouped.setdefault((phase_index, typ), {"capacity": 0.0, "dates": []})
                slot["capacity"] += float(obj.get("capacity") or 0)
                if obj.get("start_date"):
                    slot["dates"].append(str(obj["start_date"])[:10])
            social_monthly_by_phase = [[0.0] * 120 for _ in range(4)]
            # Каждая пара «тип × очередь» получает свою строку на «Вводных»:
            # мест, стоимость места, начало, срок и стоимость формулой. Пустая
            # пара пишется нулями — строка есть всегда, иначе формула CAPEX
            # ссылалась бы в пустоту, а включить объект в книге было бы негде.
            social_rows: dict[tuple[int, str], dict[str, Any]] = {}
            for (phase_index, typ), slot in grouped.items():
                offset_months = (float(social_phases[phase_index].get("start_offset_months") or 0)
                                 if phase_index < len(social_phases) else 0.0)
                cost = (slot["capacity"] * cost_per.get(typ, 0.0)
                        * (1.0 + social_inflation) ** (offset_months / 12.0))
                if cost <= 0:
                    continue
                phase_start = add_months(project_start_iso, int(offset_months)).isoformat()
                if social_count == 1:
                    own_start = (min(slot["dates"]) if slot["dates"]
                                 else typed_starts.get(typ) or phase_start)
                    obj_start = max(own_start, project_start_iso)
                else:
                    # Не раньше РнС очереди — как в движке: стройка до РнС
                    # ложилась бы на БРИДЖ.
                    phase_permit = add_months(
                        phase_start, int(max(float(IRD_MONTHS_MIN), n(x, "ird_months", 18.0)))).isoformat()
                    obj_start = max(min(slot["dates"]) if slot["dates"] else phase_start,
                                    phase_start, phase_permit)
                span_months = months_by_type.get(typ, 24)
                first_col = months_between(
                    date.fromisoformat(project_start_iso), date.fromisoformat(obj_start))
                for month_index in range(span_months):
                    column = first_col + month_index
                    if 0 <= column < 120:
                        social_monthly_by_phase[min(phase_index, 3)][column] += cost / span_months
                slot_key = (min(phase_index, 3), typ)
                previous = social_rows.get(slot_key)
                if previous is None:
                    social_rows[slot_key] = {
                        "capacity": slot["capacity"], "start": obj_start,
                        "months": span_months, "factor": (1.0 + social_inflation)
                        ** (offset_months / 12.0)}
                else:
                    # Движок агрегирует объекты типа внутри очереди — сюда
                    # приходит один раз на пару, но пусть сложение не потеряется.
                    previous["capacity"] += slot["capacity"]
                    previous["start"] = min(previous["start"], obj_start)
            # Денежная часть совмещённого режима — одним платежом в свою дату,
            # а не размазанная по графику стройки: это разные обязательства с
            # разными сроками, и движок платит их порознь.
            social_cash_mln = 0.0
            social_cash_date = None
            if str(x.get("social_mode")) == SOCIAL_MODE_BOTH:
                cash_mln = n(x, "social_compensation_mln")
                # Дата — движковой методикой: платёж не выходит за бридж-период.
                comp_date = social_cash_payment_date(
                    x, add_months(project_start_iso,
                                  int(max(float(IRD_MONTHS_MIN), n(x, "ird_months", 18.0)))))
                social_cash_date = comp_date
                if cash_mln > 0:
                    social_cash_mln = cash_mln
                    column = months_between(date.fromisoformat(project_start_iso), comp_date)
                    if 0 <= column < 120:
                        social_monthly_by_phase[0][column] += cash_mln


    # --- блок соцобъектов на «Вводных» -------------------------------------
    # Пишется при ЛЮБОЙ форме соцнагрузки, а не только при стройке. Пока
    # чисто денежный режим шёл мимо блока, строка CAPEX оставалась на формуле
    # шаблона, а та читает B18 без обрезки по РнС — и заданная дата за
    # бридж-периодом платилась в свой месяц вместо крайнего: пик БРИДЖа падал
    # ровно на сумму компенсации (4132,8 вместо 4713,5 млн). Две дороги к
    # одному платежу однажды разойдутся; дорога одна.
    if social_monthly_by_phase is None:
        social_monthly_by_phase = [[0.0] * 120 for _ in range(4)]
        social_rows = {}
        cost_per = {}
        months_by_type = {}
        _cash_start = str(x.get("project_start") or "2027-01-01")[:10]
        social_cash_mln = n(x, "social_compensation_mln")
        if social_cash_mln > 0:
            _cash_when = social_cash_payment_date(
                x, add_months(_cash_start,
                              int(max(float(IRD_MONTHS_MIN), n(x, "ird_months", 18.0)))))
            _cash_column = months_between(date.fromisoformat(_cash_start), _cash_when)
            if 0 <= _cash_column < 120:
                social_monthly_by_phase[0][_cash_column] += social_cash_mln
    # Дописывается строками в свободный низ листа, как лестница ставок:
    # вставить строку в занятое место нельзя — поедут все ссылки.
    xml, social_base_row = _v4_social_rows_xml(
        xml, social_rows, cost_per, months_by_type, social_cash_mln,
        # Площадь берётся тем же ответом, что и строка ТЭП: книга читала поле
        # «Вводных» напрямую, и на местах, введённых без площади, показывала
        # ноль там, где модель строила объект по нормативу.
        areas={typ: (social_tep_row(x, typ)["total_area"],
                     social_area_per_place(x, typ))
               for typ in _V4_SOCIAL_AREA_KEYS})

    # Вводные, которых книге не сосчитать, показываются основанием: число без
    # основания и основание без числа одинаково бесполезны. Плата за ВРИ стоит
    # в книге суммой, и от чего она — узнать было негде.
    xml, _ = _v4_engine_only_rows_xml(xml, x)

    # Благоустройство меряется физической площадью двора: блок вводных для него
    # дописывается тем же способом, что лестница ставок и соцкалендарь.
    (xml, _landscaping_per_person, _landscaping_norm,
     _landscaping_gns_rate) = _v4_landscaping_rows_xml(xml, x, tep)

    # Метры кладовых книга считает от их штук, а не принимает числом: иначе
    # правка штук внутри книги не двигает ни подземной площади, ни СМР.
    xml, _storage_per_unit, _storage_per_unit_value = _v4_storage_norm_rows_xml(xml, x, tep)

    # --- расшифровка соцнагрузки: ОТЧЕТ (E31:H37) и ТЭП (38–44) -----------
    # «Где в Excel расходы на садик и школы?» — раньше нигде: B17 приезжал
    # одной цифрой. Расшифровка — формулы от блока «Вводных», а не числа на
    # дату сборки: правка мест прямо в книге обязана двигать и строку. Итоги
    # (H37, E44) — тоже формулы, чтобы сумма сходилась с B17.
    report_sheet_path = _v4_sheet_path(source, "ОТЧЕТ")
    tep_sheet_path = _v4_sheet_path(source, "ТЭП")
    report_xml = source.read(report_sheet_path).decode("utf-8")
    report_xml = _v4_add_report_default_row(report_xml, missing)
    report_xml = _v4_report_net_profit_from_its_own_rows(report_xml, missing)
    report_xml = _v4_product_structure_block(report_xml, missing)
    report_xml = _v4_report_unit_tables_style(report_xml)
    report_xml = _v4_report_area_labels(report_xml, missing)
    report_xml = _v4_rename_labels(report_xml, "ОТЧЕТ", missing)
    tep_xml = _v4_extra_tep_rows(
        source.read(tep_sheet_path).decode("utf-8"), missing)
    tep_xml = _v4_object_parking_in_tep(tep_xml, missing)
    tep_xml = _v4_rename_labels(tep_xml, "ТЭП", missing)
    tep_xml, report_xml = _v4_storage_area_cells(tep_xml, report_xml, missing)

    # Соцстройка — готовыми числами в строку 31 блока каждой очереди CAPEX:
    # объект платится в своей очереди её календарём, как в движке. Итог
    # строки становится суммой месяцев — прежняя формула с R-долей осталась
    # бы жить своей жизнью поверх записанных чисел.
    capex_sheet_path = _v4_sheet_path(source, "CAPEX")
    capex_xml = source.read(capex_sheet_path).decode("utf-8")
    capex_xml = _v4_apply_management_profile(capex_xml, missing)
    capex_xml = _v4_apply_shared_cash_articles(capex_xml, missing)
    capex_xml = _v4_apply_demolition_rows(capex_xml, missing)
    capex_xml = _v4_apply_landscaping_base(
        capex_xml, _landscaping_per_person, _landscaping_norm,
        _landscaping_gns_rate, missing)
    capex_xml = _v4_apply_storage_area_rows(capex_xml, missing)
    capex_xml = _v4_apply_bridge_limit_before_permit(capex_xml, missing)
    capex_xml = _v4_apply_vri_interest_row(capex_xml, missing)
    capex_xml = _v4_apply_turnkey_overheads(capex_xml, missing)
    capex_xml = _v4_apply_nonres_full_estimate(capex_xml, x, missing)
    vri_sheet_path = _v4_sheet_path(source, "ВРИ")
    vri_xml = _v4_apply_vri_installment_start(
        source.read(vri_sheet_path).decode("utf-8"), missing)
    vri_xml = _v4_apply_vri_monthly_accrual(vri_xml, missing)
    objects_sheet_path = _v4_sheet_path(source, "ОБЪЕКТЫ")
    objects_xml = _v4_extra_object_blocks(
        source.read(objects_sheet_path).decode("utf-8"), missing)
    objects_xml = _v4_object_parking_block(objects_xml, missing)
    objects_xml = _v4_object_parking_allocation(objects_xml, missing)
    sales_sheet_path = _v4_sheet_path(source, "Продажи")
    sales_xml = source.read(sales_sheet_path).decode("utf-8")
    if social_monthly_by_phase is not None and social_base_row is not None:
        # Строка соцстройки — формулой по блоку «Вводных», а не 120 числами на
        # очередь: сдвинули начало объекта или срок стройки прямо в книге —
        # поехал график, как в движке. Прежде правка календаря не двигала
        # ничего, и книга была придатком веб-сервиса, где считает движок.
        from openpyxl.utils import get_column_letter as _col
        for phase_index in range(4):
            row = 31 + 34 * phase_index
            cells = {f"B{row}": dict(formula=f"SUM(D{row}:{_V4_LAST_COLUMN}{row})")}
            for column_index in range(_V4_MONTH_COLUMNS):
                column = _col(_V4_CF_FIRST_COL + column_index)
                cells[f"{column}{row}"] = dict(
                    formula=_v4_social_capex_formula(social_base_row, phase_index, column))
            capex_xml, done = _v4_set_cells(capex_xml, row, cells)
            if not done:
                missing.append(f"соцграфик CAPEX: строка {row} очереди {phase_index + 1}")

    # Ключевая ставка — движковой кривой, а не линейкой шаблона: движок ведёт
    # экспоненциальное снижение от даты стартовой ставки (generate_rate_curve),
    # книга линейно снижала от первого месяца проекта. На старте в январе 2027
    # при ставке с июля 2026 книга держала ключ 14% там, где у движка уже 12%,
    # и БРИДЖ с ПФ дорожали на десятки миллионов из ниоткуда. Сценарный
    # переключатель сохранён: целевая ставка остаётся ячейкой B34 (= H8).
    # Сама кривая пишется ниже, когда известны ячейки блока: форма и смещение
    # стояли здесь числами внутри формулы, и правка их в книге ничего не
    # меняла — «если величина в книге не выражается формулой, значит не
    # хватает не формулы, а вводной».
    rates_sheet_path = _v4_sheet_path(source, "Ставки")
    rates_xml = source.read(rates_sheet_path).decode("utf-8")

    # Лист «Источники» — данными этого проекта, а не шаблонного: там жил
    # кадастр 77:09 и московское 593-ПП даже у областных проектов, и сверка
    # честно читала это как «источники от другой юрисдикции».
    sources_sheet_path = _v4_sheet_path(source, "Источники")
    sources_xml = source.read(sources_sheet_path).decode("utf-8")
    _tep_source = ("Импорт ГлавАПУ" if (inputs or {}).get("_glavapu_import")
                   else "ТЭП DevelopAid (вводные проекта)")
    sources_xml, _ = _v4_set_cell(sources_xml, "C6", text=_tep_source)
    sources_xml, _ = _v4_set_cell(sources_xml, "D6", text=str(
        project_name or x.get("project_name") or "текущий проект"))
    if str(x.get("vri_region") or "msk") == "mo":
        # Правка этой строки была применена НАПОЛОВИНУ: имя источника и ссылку
        # заменили, а колонка «Применение» осталась с московским 593-ПП — то
        # есть областная книга по-прежнему называла основанием чужой акт, и
        # выглядело это как исправленная строка. Строка меняется целиком.
        sources_xml, _ = _v4_set_cell(
            sources_xml, "C7", text="Московская область")
        sources_xml, _ = _v4_set_cell(
            sources_xml, "D7",
            text="Диапазоны платы за смену ВРИ по округам МО (справочник DevelopAid)")
        sources_xml, _ = _v4_set_cell(
            sources_xml, "G7",
            text="1745-ПП: коэффициент Кд по видам использования, плата считается "
                 "по методике области")
        sources_xml, _ = _v4_set_cell(
            sources_xml, "I7",
            text="Сумма платы приходит из расчёта; порядок, ставки и рассрочка — "
                 "областные, московские здесь не применяются")
    calculation_id = _calculation_fingerprint(inputs, calculation_source_tep, phasing)
    sources_xml, _ = _v4_set_cell(
        sources_xml, "C16", text=f"Сборка DevelopAid {VERSION}")
    sources_xml, _ = _v4_set_cell(
        sources_xml, "D16",
        text=f"собрано {date.today().isoformat()} · расчёт {calculation_id}")
    # Нормативные основания — строками ниже проектных источников: книга
    # владельца отвечает «чем посчитано», а нормативы это половина ответа.
    sources_xml = _v4_normative_sources_rows(
        sources_xml, str(x.get("vri_region") or "msk"), missing)

    # Parity-блок ПРОВЕРОК: контрольные числа движка — значениями в C, допуск
    # в E; формулы книги в B посчитает Excel, и вердикт листа скажет FAIL,
    # если поверхности разойдутся. Без движковых чисел строки молчат.
    # Перенос непогашенного долга между очередями: строки 64 и 65 листов CF.
    # Признак живёт на «Вводных» и по умолчанию выключен — с выключенным ряды
    # дают ноль, и все правленые формулы сходятся к прежним.
    _carry_on = bool(p.get("carry_debt_forward")) and bool(p.get("enabled"))
    _queue_count = max(1, min(4, int(p.get("phase_count") or 1) if p.get("enabled") else 1))
    cf_sheet_paths: dict[str, str] = {}
    cf_sheet_xml: dict[str, str] = {}
    for _phase in range(1, 5):
        _name = f"CF_{_phase}"
        try:
            _path = _v4_sheet_path(source, _name)
        except Exception:
            missing.append(f"{_name}: лист не найден")
            continue
        cf_sheet_paths[_name] = _path
        # Начисление процентов идёт ПОСЛЕДНИМ: оно переводит базу налога со
        # строки выплаты на свою, а до него ту же строку 22 правит признание
        # ФОКа — по хвосту «-D53-D57-D21», которого после нас там уже нет.
        # База вычета НДС правится ПОСЛЕДНЕЙ, и это измерено, а не выбрано:
        # поставленная первой, она доезжала до 102 ячеек строки из 183 —
        # соседний проход переписывал середину строки 21 прежней формулой, и
        # живой месяц (AC) оказывался ровно в ней. Снаружи это выглядело как
        # «правка не сработала»: D21 в книге с правкой, а число прежнее.
        cf_sheet_xml[_name] = _v4_apply_vat_base(
            _v4_apply_interest_accrual(
                _v4_apply_core_pool_without_sales(_v4_apply_extra_objects_tax_row(
                    _v4_use_bridge_base_row(
                        _v4_apply_cash_sweep(
                            _v4_apply_pf_ceiling(
                                _v4_name_fees_paid_by_equity(
                                    _v4_apply_debt_carry(
                                        source.read(_path).decode("utf-8"),
                                        _phase, _queue_count, missing),
                                    _phase, missing),
                                _phase, missing),
                            _phase, missing),
                        _phase, missing),
                    _phase, missing),
                    _phase, missing),
                _phase, missing),
            _phase, missing)

    # Выручка очереди по продуктам: на экране разбивка есть, а в книге жила
    # только в снятой выгрузке детализации.
    consolidator_sheet_path = _v4_sheet_path(source, "КОНСОЛИДАТОР")
    consolidator_xml = _v4_revenue_by_product(
        _v4_tax_share_by_year(
            source.read(consolidator_sheet_path).decode("utf-8"), missing),
        list((finance_hints or {}).get("revenue_products") or []), missing)

    checks_sheet_path = _v4_sheet_path(source, "ПРОВЕРКИ")
    checks_xml = _v4_relax_limit_check_for_carried_debt(
        _v4_object_parking_in_checks(
            _v4_object_checks(source.read(checks_sheet_path).decode("utf-8"), missing),
            missing),
        missing)
    _parity = (finance_hints or {}).get("parity") or {}
    if _parity:
        _parity_rows = (
            (76, "revenue_mln"), (77, "capex_mln"), (78, "ebitda_mln"),
            (79, "financing_mln"), (80, "tax_mln"), (81, "net_profit_mln"),
            (82, "llcr"), (83, "peak_bridge_mln"), (84, "peak_pf_mln"),
        )
        # Допуск: полпроцента от величины, но не уже 1 млн (LLCR: 0,02) —
        # ловим методические разъезды, а не шум сериализации.
        def _own_tolerance(key: str) -> float:
            if key == "llcr":
                return _V4_PARITY_LLCR_TOLERANCE
            share = _V4_PARITY_SHARE.get(key, _V4_PARITY_SHARE_DEFAULT)
            return max(1.0, abs(float(_parity.get(key) or 0.0)) * share)

        # Производная величина не может быть точнее своих слагаемых. У EBITDA и
        # стоимости финансирования допуск считается долей ОТ НИХ САМИХ —
        # десятки млн на проекте в сорок миллиардов, — а прибыль и налог бывают
        # околонулевыми, и им доставался пол в 1 млн. Строка краснела на сумме
        # допусков соседей, то есть на их шуме, и сказать по ней, ЧТО
        # разошлось, было нельзя. Ответ не в том, чтобы ослабить проверку:
        # каждая величина отвечает за себя своей строкой — НДС с 0.23.23 тоже,
        # и первым же своим прогоном он назвал настоящую ошибку в базе налога.
        _base_parts = ("ebitda_mln", "financing_mln")
        _derived_tolerance = {
            # База налога — разность EBITDA и стоимости финансирования, а сам
            # налог её доля: на 25% разрыв в пять млн базы даёт 1,3 млн налога.
            "tax_mln": lambda: sum(_own_tolerance(part) for part in _base_parts)
            * max(0.0, n(x, "profit_tax_pct", 25)) / 100,
            "net_profit_mln": lambda: (
                sum(_own_tolerance(part) for part in (*_base_parts, "vat_mln"))
                + max(_own_tolerance("tax_mln"),
                      _derived_tolerance["tax_mln"]())),
        }
        for _row, _key in _parity_rows:
            _target = float(_parity.get(_key) or 0.0)
            _tol = _own_tolerance(_key)
            if _key in _derived_tolerance:
                _tol = max(_tol, _derived_tolerance[_key]())
            checks_xml, done = _v4_set_cell(checks_xml, f"C{_row}", number=round(_target, 4))
            if done:
                checks_xml, done = _v4_set_cell(checks_xml, f"E{_row}", number=round(_tol, 4))
            if done:
                # Вердикт переписывается на общий: строки блока и строки,
                # дописанные ниже, обязаны отвечать одним правилом.
                checks_xml, done = _v4_set_cell(
                    checks_xml, f"F{_row}", formula=_v4_parity_verdict(_row))
            if not done:
                missing.append(f"паритет ПРОВЕРКИ: строка {_row}")
                break
    if _parity:
        checks_xml = _v4_add_parity_gate_row(checks_xml, missing)
    checks_xml = _v4_add_carry_parity_row(
        checks_xml, float((finance_hints or {}).get("carried_debt_mln") or 0.0), missing)
    if _parity:
        # Без контрольных чисел движка строки паритета не бывает: ноль в
        # цели — это не «налога нет», а «нам его не сказали», и строка
        # краснела бы на любом проекте с НДС.
        checks_xml = _v4_add_vat_parity_row(
            checks_xml, float(_parity.get("vat_mln") or 0.0), missing)
        checks_xml = _v4_add_pf_uncovered_parity_row(
            checks_xml, float(_parity.get("pf_shortfall_mln") or 0.0), missing)
    checks_xml = _v4_teach_funding_check_about_the_limit(checks_xml, missing)
    checks_xml = _v4_name_debt_default_status(checks_xml, missing)

    def _put_extra(sheet_xml: str, coord: str, *, number=None, text=None) -> str:
        updated, done = _v4_set_cell(sheet_xml, coord, number=number, text=text)
        if not done:
            missing.append(f"расшифровка соцнагрузки: {coord}")
        return updated

    social_compensation_amount = (
        0.0 if social_is_construction else float(x.get("social_compensation_mln") or 0))
    _social_rows = (
        ("kindergarten", 33, 40, "kindergarten_places", "social_dou_gba_sqm"),
        ("school", 34, 41, "school_places", "social_school_gba_sqm"),
        ("clinic", 35, 42, "clinic_capacity", "social_clinic_gba_sqm"),
    )
    # Детализация соцнагрузки — ФОРМУЛАМИ от блока «Вводных», а не числами на
    # дату сборки. Цена измерена: удвоив места школы прямо в книге, человек
    # получал CAPEX 147 193 вместо 144 578 — денежная цепочка пересчитывается
    # сама, — и рядом замершие 373 места за 2 349 млн. Два разных ответа об
    # одном объекте в одном файле. Ссылки идут на «Вводные» напрямую, как
    # формула соцстройки на листе CAPEX: у этого блока такой путь уже принят.
    def _social_span(type_index: int, letter: str) -> str:
        first = _v4_social_row(social_base_row, type_index, 0)
        last = _v4_social_row(social_base_row, type_index, 3)
        return f"'Вводные'!${letter}${first}:${letter}${last}"

    for type_index, (typ, report_row, tep_row, places_key, gba_key) in enumerate(_social_rows):
        slot = social_breakdown[typ]
        places = slot["places"] if social_is_construction else float(x.get(places_key) or 0)
        cost = round(slot["cost"], 3)
        queue_label = ("+".join(f"О{n}" for n in sorted(slot["phases"]))
                       if slot["phases"] else "—")
        if social_base_row is None:
            # Блока в книге нет — тогда честнее число, чем ссылка в никуда.
            report_xml = _put_extra(report_xml, f"F{report_row}", number=round(places))
            report_xml = _put_extra(report_xml, f"G{report_row}", text=queue_label)
            report_xml = _put_extra(report_xml, f"H{report_row}", number=cost)
            tep_xml = _put_extra(tep_xml, f"B{tep_row}", number=round(places))
            tep_xml = _put_extra(tep_xml, f"C{tep_row}",
                                 number=round(float(x.get(gba_key) or 0)))
            tep_xml = _put_extra(tep_xml, f"D{tep_row}", text=queue_label)
            tep_xml = _put_extra(tep_xml, f"E{tep_row}", number=cost)
            continue
        capacity = _social_span(type_index, "B")
        money = _social_span(type_index, "F")
        area = _social_span(type_index, "L")
        norm = _social_span(type_index, "M")
        ratio = f"'Вводные'!$P${_v4_social_row(social_base_row, 0, 0)}"
        # Метка очередей — тоже производная: объект переставили в книге, и
        # подпись обязана переехать за ним, иначе она говорит о прошлом.
        parts = "&".join(
            f"IF('Вводные'!$B${_v4_social_row(social_base_row, type_index, phase)}>0,"
            f'"О{phase + 1}+","")' for phase in range(4))
        label = f'IF(SUM({capacity})>0,LEFT({parts},LEN({parts})-1),"—")'
        for where, coord, formula in (
                ("tep", f"B{tep_row}", f"SUM({capacity})"),
                ("tep", f"C{tep_row}", f"IF(SUM({area})>0,SUM({area}),"
                                       f"SUM({capacity})*SUM({norm}))"),
                ("tep", f"D{tep_row}", label),
                ("tep", f"E{tep_row}", f"SUM({money})"),
                # ГНС соцобъекта — своей колонкой: в блоке стояла только общая
                # площадь, а строительный объём считается по ГНС, и соцобъекты
                # в него не входили вовсе — 28 520 м² на проекте владельца.
                ("tep", f"F{tep_row}", f"IFERROR(C{tep_row}/{ratio},0)"),
                ("report", f"F{report_row}", f"'ТЭП'!B{tep_row}"),
                ("report", f"G{report_row}", f"'ТЭП'!D{tep_row}"),
                ("report", f"H{report_row}", f"'ТЭП'!E{tep_row}"),
        ):
            target = tep_xml if where == "tep" else report_xml
            target, done = _v4_set_or_insert_cell(target, coord, formula=formula)
            if not done:
                missing.append(f"детализация соцнагрузки формулой: {coord}")
            if where == "tep":
                tep_xml = target
            else:
                report_xml = target
    tep_xml, _done = _v4_set_or_insert_cell(tep_xml, "F39", text="ГНС, м²")
    if not _done:
        missing.append("расшифровка соцнагрузки: подпись F39")
    # Денежная компенсация — та же вводная, что кормит CAPEX: ссылкой, а не
    # числом на дату сборки. Правка суммы в книге обязана двигать и строку.
    if social_base_row is not None:
        cash_cell = f"'Вводные'!$F${_v4_social_cash_row(social_base_row)}"
        for target_name, coord in (("tep", "E43"), ("report", "H36")):
            target = tep_xml if target_name == "tep" else report_xml
            target, done = _v4_set_or_insert_cell(target, coord, formula=cash_cell)
            if not done:
                missing.append(f"денежная компенсация формулой: {coord}")
            if target_name == "tep":
                tep_xml = target
            else:
                report_xml = target
    else:
        report_xml = _put_extra(report_xml, "H36",
                                number=round(social_compensation_amount, 3))
        tep_xml = _put_extra(tep_xml, "E43",
                             number=round(social_compensation_amount, 3))

    # Лимит БРИДЖ в книге режет выборку (CF r34). Логика вводных DevelopAid —
    # «всё финансирует банк», поэтому лимит расчётный: сделка, ВРИ, социалка
    # и весь CAPEX. Фиксированные 3 500 млн душили проект крупнее Мишина.
    put("B24", formula=(
        "ROUNDUP(($B$15+$B$16+$B$17+$B$83"
        "+SUM('CAPEX'!$B$35,'CAPEX'!$B$69,'CAPEX'!$B$103,'CAPEX'!$B$137))/10,0)*10"
    ), label="bridge_limit_mln")

    # Лимит ПФ — по методике движка: лимит очереди есть её выборка, округлённая
    # вверх до 10 млн (`pf_limit = ceil(pf_draw_total / 10 млн) × 10 млн`).
    # Шаблон считал от «РАСХОДЫ ПРОЕКТА ВСЕГО» — другой величины — и занижал
    # лимит вместе с платой за невыбранный. Число сюда писать нельзя: правка
    # календаря очереди двигает выборку, а лимит остался бы прежним.
    put("B26", formula=_V4_PF_LIMIT_FORMULA, label="pf_limit_mln (методика движка)")

    # --- добавка вводных в СВОИ блоки --------------------------------------
    # Свободных строк у групп левой колонки почти нет, а вставлять строку в
    # занятое место нельзя — поедут все ссылки. Поэтому добавка встаёт ПРАВЕЕ,
    # в те же строки своей группы: править объект, листая от одной его половины
    # к другой, нельзя (решение владельца, 03.09.2026). Колонки E–H у блоков
    # сделки, стоимости стройки, продаж и ВРИ свободны — измерено по шаблону.
    for _extra_row, _extra_label, _extra_key, _extra_unit, _extra_kind in (
            # Сделка и сроки (13–37)
            (15, "Лаг погашения БРИДЖ после РнС", "bridge_repay_lag_months", "мес.", "number"),
            (16, "Выкуп ЗУ/ОКС у третьих лиц", "land_buyout_mln", "млн ₽", "number"),
            # Стоимость строительства (38–54)
            (39, "Снос — площадь сносимого", "demolition_area_sqm", "м²", "number"),
            (40, "Снос — стоимость", "demolition_cost_th_per_sqm", "тыс. ₽/м²", "number"),
            (41, "Расселение", "resettlement_cost_mln", "млн ₽", "number"),
            # Продажи (57–71)
            (59, "Инфляция цены после РВЭ", "inflation_after_rve_pct", "% год", "pct"),
            # Финансирование — в блоке сделки, там же, где спреды
            (25, "Спред капитализации БРИДЖ", "bridge_cap_spread_pp", "п.п.", "pct"),
            (26, "Одобренный лимит ПФ", "pf_limit_approved_mln",
             "млн ₽; 0 — лимит из потребности", "number"),
            # Соцнагрузка — форма площади объекта
            (43, "Площадь соцобъекта", "social_area_source",
             "норматив / вписана руками", "text"),
    ):
        _extra_value = x.get(_extra_key)
        put_new(f"E{_extra_row}", text=_extra_label)
        if _extra_kind == "pct":
            put_new(f"F{_extra_row}", number=n(x, _extra_key, 0.0) / 100.0,
                    label=_extra_key)
        elif _extra_kind == "text":
            put_new(f"F{_extra_row}",
                    text="вписана руками" if str(_extra_value or "norm") == "manual"
                    else "норматив", label=_extra_key)
        else:
            put_new(f"F{_extra_row}", number=n(x, _extra_key, 0.0), label=_extra_key)
        put_new(f"G{_extra_row}", text=_extra_unit)
        put_new(f"H{_extra_row}", text=_extra_key)
        # Ячейка добавки — ВВОД, и сказать об этом обязан её стиль: лист ввода
        # отбирает строки не по нашему списку, а по краске шаблона (синий шрифт
        # на жёлтой заливке). Пока добавка шла без стиля, её строка ехала на
        # лист ввода только за компанию — когда в той же строке уже стоял
        # штатный ввод. У одобренного лимита ПФ соседом по строке стоит
        # ФОРМУЛА (B26 — лимит по методике движка), и строка 26 не ехала
        # никуда: поле, которое просят заполнить, оставалось на расчётном
        # листе. Красится только оно: чужие строки и так переезжают, а лишняя
        # краска сказала бы о них то, чего шаблон не говорит.
        if _extra_key == "pf_limit_approved_mln":
            xml = _v4_mark_as_entry(xml, f"F{_extra_row}", missing)

    # --- ВРИ: остальные вводные в свой блок --------------------------------
    # Лист «ВРИ» — живой график на 1932 формулы, он уже читает периодичность,
    # срок рассрочки, проценты и обеспечение. Недостающие четырнадцать ложатся
    # туда же, в строки СВОЕГО блока (73–85), двумя парами колонок: E/F и G/H.
    # Часть из них книга пока не считает, и это сказано единицей измерения —
    # ложное поле хуже отсутствующего, а молча пропущенное читается как «такой
    # вводной нет».
    _vri_mode_words = {
        "before_rns_1m": "За месяц до РнС", "at_rns": "В дату РнС",
        "before_rns_3m": "За три месяца до РнС",
        "after_purchase": "Через N мес. после покупки", "manual": "Задана вручную"}
    _vri_extra = (
        ("Дата обязательства — режим", "vri_obligation_date_mode", "режим",
         _vri_mode_words.get(str(x.get("vri_obligation_date_mode") or "before_rns_1m"),
                             "За месяц до РнС")),
        ("Месяцев после покупки", "vri_months_after_purchase", "мес.",
         n(x, "vri_months_after_purchase", 12.0)),
        ("Дата обязательства по документу", "vri_obligation_date", "дата; пусто — оценка",
         str(x.get("vri_obligation_date") or "")[:10] or "не задана"),
        ("Первый взнос", "vri_initial_pct", "% платы", n(x, "vri_initial_pct", 0.0) / 100.0),
        ("Порядок графика", "vri_schedule_mode", "режим",
         "Задан вручную" if str(x.get("vri_schedule_mode") or "auto") == "manual" else "Автоматический"),
        ("Дата открытия ПФ для ВРИ", "vri_pf_open_date", "дата; пусто — РнС",
         str(x.get("vri_pf_open_date") or "")[:10] or "не задана"),
        ("ВРИ в банковском бюджете", "vri_in_bank_budget", "Да / Нет",
         "Нет" if x.get("vri_in_bank_budget") is False else "Да"),
        ("Источник оплаты ВРИ", "vri_financing_mode", "режим",
         "Заданы доли" if str(x.get("vri_financing_mode") or "auto") == "shares" else "Автоматически"),
        ("Доля БРИДЖа в плате", "vri_share_bridge_pct", "%",
         n(x, "vri_share_bridge_pct", 0.0) / 100.0),
        ("Доля ПФ в плате", "vri_share_pf_pct", "%", n(x, "vri_share_pf_pct", 0.0) / 100.0),
        ("Доля своих средств в плате", "vri_share_equity_pct", "%",
         n(x, "vri_share_equity_pct", 0.0) / 100.0),
        ("Льгота — форма", "vri_relief_mode", "режим",
         {"share": "Долей", "amount": "Суммой"}.get(
             str(x.get("vri_relief_mode") or "none"), "Нет льготы")),
        ("Льгота — доля", "vri_relief_pct", "% платы", n(x, "vri_relief_pct", 0.0) / 100.0),
        ("Зачёт переданных метров", "vri_transfer_offset_mln", "млн ₽",
         n(x, "vri_transfer_offset_mln", 0.0)),
    )
    # Колонка одна — E–H: I–L в этих строках заняты блоком паркинга и кладовых,
    # и вторая пара затёрла бы его подписи. Полей четырнадцать, строк блока
    # ровно столько же вместе со строкой заголовка (72–85).
    for _index, (_label, _key, _unit, _value) in enumerate(_vri_extra):
        _row = 72 + _index
        put_new(f"E{_row}", text=_label)
        if isinstance(_value, str):
            put_new(f"F{_row}", text=_value, label=_key)
        else:
            put_new(f"F{_row}", number=round(float(_value), 6), label=_key)
        put_new(f"G{_row}", text=_unit)
        put_new(f"H{_row}", text=_key)

    # --- остаточные продажи объектов ---------------------------------------
    # «Общий срок продаж» объекта (K33/K53/K73) — это срок стройки ПЛЮС хвост
    # после ввода, и в книге он стоял одним числом: остаточный срок отдельно не
    # виден, а править его можно было только сложением в уме. Ячейка встаёт в
    # свободную строку СВОЕГО блока — править объект, листая от одной его
    # половины к другой, нельзя (решение владельца, 03.09.2026), — а срок
    # становится формулой: сдвинул стройку или хвост, и он поехал.
    for _obj_prefix, _obj_row, _obj_months, _obj_term in (
            (_lay.obj.prefix, _lay.residual_row, f"$K${_v4_input_row(_lay, 'months')}",
             f"K{_v4_input_row(_lay, 'term')}")
            for _lay in sorted(_v4_layouts(), key=lambda lay: lay.input_head)):
        put_new(f"J{_obj_row}", text="Остаточные продажи после РВЭ")
        put_new(f"K{_obj_row}", number=n(x, f"{_obj_prefix}_residual_months", 6.0),
                label=f"{_obj_prefix}_residual_months")
        put_new(f"L{_obj_row}", text="мес.")
        put_new(f"M{_obj_row}", text=f"{_obj_prefix}_residual_months")
        xml = _v4_mark_as_entry(xml, f"K{_obj_row}", missing)
        put(_obj_term, formula=f"{_obj_months}+$K${_obj_row}",
            label=f"срок продаж {_obj_prefix}")

    # --- подземный паркинг -------------------------------------------------
    # Группа встаёт В СВОЙ блок (J78 «ПАРКИНГ И КЛАДОВЫЕ»), в его же пустые
    # строки 82–85. Норматив — ЧИСЛО, а не формула: от него считается площадь
    # очереди, и обратная формула дала бы круг. Показывается ФАКТИЧЕСКИЙ —
    # площадь ÷ построенные места: заданная руками площадь главнее норматива, и
    # 40,2 м²/место у такого проекта это ответ, а не ошибка. Умолчание 35 берётся
    # только когда мерить нечего.
    _under_row = (tep or {}).get("underground_parking") or {}
    _under_units = num_row(_under_row, "units")
    _under_gns = num_row(_under_row, "gns")
    _under_norm = (_under_gns / _under_units if _under_units > 0 and _under_gns > 0
                   else n(x, "underground_area_per_space_sqm", 35.0) or 35.0)
    put_new("J82", text="Норматив площади на машино-место")
    put_new("K82", number=round(_under_norm, 4), label="underground_area_per_space_sqm")
    put_new("L82", text="м²/место, гросс")
    put_new("M82", text="underground_area_per_space_sqm")
    # Дописанные вводные J:M — остаточные продажи объектов (стиль ставится в
    # их цикле выше) и размещение паркинга объектов — шли без стиля ввода.
    # Лист ввода отбирает по стилю: эти ячейки ехали туда простой копией без
    # читалки (правка на «Вводных» ничего не меняла) или вовсе оставались на
    # «Параметрах модели» вторым местом ввода. Норматив K82 сюда не входит:
    # его не читает ни одна формула, и он объявлен в V4_INPUTS_NOT_IN_BOOK.
    for _entry_coord in [coord for _, _, coord, _ in _V4_OBJECT_PARKING_INPUT_ROWS if coord]:
        xml = _v4_mark_as_entry(xml, _entry_coord, missing)
    put_new("J83", text="Отказ от подземного паркинга")
    put_new("K83", text="Да" if b(x, "underground_parking_disabled") else "Нет",
            label="underground_parking_disabled")
    put_new("L83", text="Да / Нет")
    put_new("M83", text="underground_parking_disabled")
    # Заданные руками места и площадь своей ячейки НЕ получают: в книге их место
    # — колонки очереди, туда и вписывают. Вторая ячейка про то же однажды
    # разошлась бы с первой, и обе выглядели бы верными; поэтому здесь сказано,
    # где их править, а ключ стоит на работающей ячейке.
    put_new("J84", text="Машино-места — решение проекта")
    put_new("K84", text="правятся в блоке очередей, колонка «База паркинга»; "
                        "рядом справочно «из них гостевых» и «из них передано»")
    put_new("M84", text="underground_manual_spaces")
    put_new("J85", text="Площадь подземной парковки")
    put_new("K85", text="считается: (места + гостевые) × норматив выше")
    put_new("M85", text="underground_manual_gns_sqm")

    # --- ВРИ ---------------------------------------------------------------
    land_cost = float(x.get("land_rights_cost_mln") or 0)
    put("B74", text="Да" if land_cost > 0 else "Нет", label="vri_required")
    put_new("D74", text="vri_required")
    _vri_installment = str(x.get("vri_payment_mode") or "lump") == "installment"
    put("B75", text="Рассрочка" if _vri_installment else "Единовременно",
        label="vri_payment_mode")
    # Режим и срок — две разные вводные и должны оставаться двумя ячейками.
    # Прежнее «3 года» в B75 заставляло человека помнить синтаксис строки и
    # мешало сделать нормальный dropdown. Все формулы графика уже читают B77
    # как число лет, поэтому пишем срок прямо туда.
    _vri_years = int(float(x.get("vri_installment_years") or 3))
    put("B77", number=float(_vri_years), label="vri_installment_years")
    xml = _v4_mark_as_entry(xml, "B77", missing)
    put_new("D75", text="vri_payment_mode")
    put_new("D77", text="vri_installment_years")
    put_new("C77", text="лет")
    lead = {"before_rns_1m": 1, "before_rns_3m": 3, "at_rns": 0}.get(
        str(x.get("vri_obligation_date_mode") or "before_rns_1m"), 1)
    put("B76", number=float(lead), label="vri_obligation_lead_months")
    _vri_periodicity = str(int(float(x.get("vri_periodicity_months") or 3)))
    put("B78", text=_v4_mode_display("vri_periodicity_months", _vri_periodicity),
        label="vri_periodicity_months")
    # В шаблоне B78 — число без стиля ввода: лист ввода отбирает строки по
    # стилю, и без пометки периодичность оставалась на расчётном листе текстом
    # «Ежеквартально» — без dropdown, а B79 делил количество платежей на слово.
    xml = _v4_mark_as_entry(xml, "B78", missing)
    _interest_raw = x.get("vri_interest_enabled")
    if _interest_raw in (None, ""):
        _interest_internal = ""
    else:
        _interest_internal = "1" if _vri_flag(_interest_raw, False) else "0"
    put("B80", text=_v4_mode_display("vri_interest_enabled", _interest_internal),
        label="vri_interest_enabled")
    put("B84", text="Да" if x.get("vri_early_repay_after_pf") else "Нет",
        label="vri_early_repay_after_pf")

    # --- плотность: базовый потенциал равен применяемому, коэффициент 1 ----
    put("K6", text="Москва" if str(x.get("vri_region") or "msk") == "msk"
        else "Московская область", label="vri_region")
    put_new("M6", text="vri_region")
    area = float(x.get("site_area_ha") or 0)
    density = float(x.get("site_density_sqm_per_ha") or 0) or 30000.0
    put("K7", number=area, label="site_area_ha")
    put("K8", text="Нет", label="use_default_density")
    put("K11", number=density, label="site_density_sqm_per_ha")
    # Базовый потенциал равен применяемому: коэффициент пересчёта ТЭП = 1,
    # базовый ТЭП очередей — ровно ТЭП проекта. При нулевой площади деление
    # 0/0 гасится IFERROR и коэффициент тоже 1.
    # В самом шаблоне здесь осталось название проекта, на котором его когда-то
    # собирали. Число обновлялось, подпись — нет, поэтому Нагатино получало в
    # своей книге «Базовый потенциал Мишина 46».
    put("J13", text="Базовый потенциал проекта", label="base_gfa_potential_label")
    put("K13", number=(area * density if area > 0 else 0), label="base_gfa_potential_sqm")

    # Полный срок продаж объектов пишется формулой выше, в блоке остаточных
    # продаж: числом он не двигался ни от правки срока стройки, ни от правки
    # хвоста, а само слагаемое «остаточные продажи» в книге было не видно.

    # Очередь финансирования объектов — из очерёдности проекта, как в движке
    # (офисы по умолчанию в третьей, ТЦ и наземный паркинг во второй).
    # Шаблонная единица сажала офисы в первую очередь: продаваемая площадь
    # очередей и их средние цены расходились с отчётом.
    discrete = (phasing or {}).get("discrete") or {}
    queue_cap = max(1, min(4, int((phasing or {}).get("phase_count") or 1)
                           if (phasing or {}).get("enabled") else 1))
    phase_offsets = [float(item.get("start_offset_months") or 0)
                     for item in ((phasing or {}).get("phases") or [])]
    for field, coord, default, date_cells, date_keys in (
        (_lay.obj.key, f"K{_v4_input_row(_lay, 'queue')}", _lay.obj.default_queue,
         (f"K{_v4_input_row(_lay, 'start')}", f"K{_v4_input_row(_lay, 'sales_start')}"),
         (f"{_lay.obj.prefix}_start", f"{_lay.obj.prefix}_sales_start"))
        for _lay in sorted(_v4_layouts(), key=lambda lay: lay.input_head)
    ):
        # Применённое движком размещение сильнее нашего вывода: объект,
        # объявленный продуктами очереди, до `discrete` не доходит вовсе, и
        # книга ставила его по умолчанию — ТЦ во вторую вместо четвёртой.
        # Подсказок нет (движок не ответил) — остаёмся на прежнем пути, но
        # молчать об этом нельзя: разъехавшееся размещение выглядит на экране
        # как посчитанное.
        applied = (finance_hints or {}).get("object_phase") or {}
        if field in applied:
            queue = max(1, min(queue_cap, int(applied[field])))
        else:
            queue = max(1, min(queue_cap, int(float(discrete.get(field) or default))))
            # Приставка вводных объявлена один раз — в `STANDALONE_OBJECTS`;
            # список «ключ → признак включения» здесь был её копией.
            _enabled = next(f"{o.prefix}_enabled"
                            for o in standalone_objects() if o.key == field)
            if (phasing or {}).get("enabled") and bool(x.get(_enabled)):
                missing.append(
                    f"очередь объекта «{field}»: движок не назвал применённую — "
                    f"книга взяла {queue} по своему умолчанию")
        put(coord, number=float(queue), label=f"очередь {field}")
        # Даты объекта сдвигаются на сдвиг старта его очереди — как в движке.
        # Сырая мастер-дата строила офисы третьей очереди на два года раньше:
        # CAPEX падал в БРИДЖ до РнС, и пик завышался почти вдвое.
        offset = (phase_offsets[queue - 1]
                  if (phasing or {}).get("enabled") and queue - 1 < len(phase_offsets) else 0.0)
        if (phasing or {}).get("enabled"):
            # Не раньше РнС своей очереди и продажи не раньше стройки — как в
            # движке: стройка до РнС ложилась бы на БРИДЖ.
            queue_permit = add_months(
                add_months(str(x.get("project_start"))[:10], int(offset)),
                int(max(float(IRD_MONTHS_MIN), n(x, "ird_months", 18.0))))
            build_date = None
            for cell, key in zip(date_cells, date_keys):
                base = x.get(key)
                if not base:
                    continue
                shifted_date = max(add_months(str(base)[:10], int(offset)), queue_permit)
                if build_date is None:
                    build_date = shifted_date
                else:
                    shifted_date = max(shifted_date, build_date)
                shifted = _v4_excel_serial(shifted_date.isoformat())
                if shifted is not None:
                    put(cell, number=shifted, label=f"{key} (сдвиг очереди, не раньше РнС)")

    # --- очереди: базовый ТЭП в W..AC, доли и сроки -------------------------
    enabled_phases = int(p.get("phase_count") or 1) if p.get("enabled") else 1
    count = max(1, min(4, enabled_phases))
    if enabled_phases > 4:
        missing.append(
            f"очередей {enabled_phases}, а листов CF в книге четыре: объёмы и доли "
            "5-й и последующих слиты в четвёртую очередь"
        )
    # Выключенная очерёдность сроков не задаёт. Конфигурация переживает свой
    # выключатель — она остаётся в сохранённом проекте и с экрана не видна, —
    # а книга читала `phases[0]` не глядя на признак. На 77:09:0004014:13 это
    # подменяло срок строительства 36 месяцев на 24 из давно выключенной
    # очереди: движок при выключенной в обёртку очередей не заходит вовсе
    # (`calculate_phased` сразу зовёт `calculate`), и от одной цифры разъезжались
    # РВЭ, горизонт, кривая CAPEX, пик ПФ и LLCR — восемь строк паритета.
    phases = list(p.get("phases") or []) if p.get("enabled") else []
    # ТЭП очередей — канонической аллокацией движка (_phase_tep_product_rows):
    # книга получает готовые числа и не может разойтись с расчётом ни в долях,
    # ни в округлении штучных продуктов.
    # ТЭП очередей берётся у движка — тот, на котором посчитан отчёт. Книга
    # выводила разбивку заново, и на проекте, объявляющем очередям РАВНЫЕ метры
    # (пресет КРТ Нагатино), раскладывала проект своим убывающим пресетом:
    # 69 031 / 56 087 / 47 459 / 43 144 м² ГНС квартир против 53 930 у каждой.
    # Итог сходится до десятой — метры не теряются, а переезжают между
    # очередями, поэтому расхождение выглядит не потерей, а другой экономикой:
    # выручка и CAPEX первых очередей завышены, последних занижены, и пик ПФ
    # первой очереди вылезал за её же банковский лимит (35 324 при 29 600).
    # Не ответил движок — считаем как прежде и говорим об этом: молча взятая
    # своя разбивка на экране неотличима от посчитанной.
    _by_phase = list((finance_hints or {}).get("tep_by_phase") or [])
    if _by_phase:
        canon_rows = _v4_fold_tep_rows(
            [{key: dict(value) for key, value in (item or {}).items()
              if isinstance(value, dict)} for item in _by_phase], count)
    else:
        canon_rows = _v4_fold_tep_rows(
            _phase_tep_product_rows(
                {key: dict(value) for key, value in (tep or {}).items() if isinstance(value, dict)},
                p, max(1, min(5, enabled_phases)))[0],
            count)
        if bool(p.get("enabled")) and count > 1:
            missing.append(
                "ТЭП очередей: движок не назвал применённую разбивку — "
                "книга разложила проект своими весами")
    shared = {key: _v4_shared_weights(p, key, count, enabled_phases)
              for key in ("purchase", "land_rights", "social_compensation", "own_funds",
                          # ИРД, проектирование, подготовка и наружные сети: движок
                          # делит их кассовыми долями, книга считала от площадей
                          # своей очереди. Теперь база у обеих одна.
                          "ird", "design", "preparation", "utilities")}
    # Индексация очередей — готовыми множителями к сдвигу старта, как в
    # движке: О1 ×1, О2 ×1,08, О3 ×1,166 при 8% в год. Годовая инфляция в
    # AE/AF здесь не пишется: книга ведёт её от даты базы цен до старта
    # продаж и индексировала даже первую очередь — на +12% против движка.
    # Отсутствующий ключ — не ноль: движок при пропуске берёт 8% годовых
    # (_phase_sales_price_inflation_factor), и книга обязана взять те же 8%,
    # иначе О2/О3 продаются по ценам первой очереди — минус 2,5 млрд выручки
    # на дефолтных вводных, которых нет в расчёте.
    price_inflation = float(p.get("sales_price_inflation_pct", 8.0) or 0) / 100.0 if count > 1 else 0.0
    cost_inflation = float(p.get("cost_inflation_pct", 8.0) or 0) / 100.0 if count > 1 else 0.0

    # Колонки очередей — это вводные движка, и книга их называет: «Старт» без
    # ключа читается как оформление, а по ключу видно, что правишь именно
    # project_start. Ключ ставится в шапке, потому что колонка одна на все
    # очереди, а значение у каждой своё.
    for _queue_column, _queue_key in (
            ("D", "project_start"), ("E", "ird_months"),
            ("F", "construction_months"), ("G", "sales_lag_months"),
            ("AD", "pace_adjustment_pct")):
        _header = str(_v4_QUEUE_HEADERS[_queue_column])
        put(f"{_queue_column}87", text=f"{_header} · {_queue_key}",
            label=f"подпись колонки {_queue_column}87")

    for index in range(4):
        row = 88 + index
        active = index < count
        crow = canon_rows[index] if active and index < len(canon_rows) else {}
        phase = phases[index] if index < len(phases) else {}
        put(f"B{row}", text="Да" if active else "Нет", label=f"очередь {index + 1}")
        offset = float(phase.get("start_offset_months") or 0) if active else 0.0
        put(f"D{row}", number=start_serial if not active else
            (_v4_excel_serial(add_months(str(x.get("project_start") or "2027-01-01"), int(offset)))
             or start_serial), label=f"старт очереди {index + 1}")
        # Ноль здесь осмыслен: «разрешение уже есть, строим сразу». Прежде стояло
        # `x.get("ird_months") or 18`, а ноль в Python ложен — и в книгу уезжали
        # восемнадцать месяцев. Движок считал РнС в день старта и БРИДЖ не брал
        # вовсе, книга считала его полтора года: 1,28 млрд тела и 190 млн
        # процентов, которых в проекте нет. Читаем через n(): она подменяет
        # только None и пустую строку.
        put(f"E{row}", number=max(float(IRD_MONTHS_MIN), n(x, "ird_months", 18.0)),
            label=f"ИРД очереди {index + 1}")
        months = phase.get("construction_months")
        put(f"F{row}", number=(float(months) if months not in (None, "")
                               else n(x, "construction_months", 24.0)),
            label=f"стройка очереди {index + 1}")
        put(f"G{row}", number=n(x, "sales_lag_months", 0.0), label=f"лаг очереди {index + 1}")
        put(f"P{row}", number=shared["purchase"][index] if active else 0.0, label="доля покупки")
        # Свои деньги — один котёл на проект: без деления каждая очередь взяла
        # бы всю сумму. Умолчание движка то же, что у покупки, — всё в первой.
        put(f"AI{row}", number=shared["own_funds"][index] if active else 0.0,
            label="доля собственных средств")
        # Кассовые доли общепроектных статей. Прежде их в книге не было вовсе:
        # каждая очередь считала ИРД, проектирование, подготовку и сети от
        # СВОИХ площадей, то есть по долям ТЭП, а движок — по кассе.
        for _share_key, _share_col, _share_label in (
                ("ird", "AJ", "Доля ИРД"), ("design", "AK", "Доля проектирования"),
                ("preparation", "AL", "Доля подготовки"),
                ("utilities", "AM", "Доля наружных сетей")):
            xml, _done = _v4_set_or_insert_cell(
                xml, f"{_share_col}{row}",
                number=shared[_share_key][index] if active else 0.0)
            if not _done:
                missing.append(f"кассовая доля «{_share_key}» очереди {index + 1}")
            if index == 0:
                xml, _done = _v4_set_or_insert_cell(
                    xml, f"{_share_col}87", text=_share_label)
                if not _done:
                    missing.append(f"подпись кассовой доли «{_share_key}»")
        put(f"Q{row}", number=shared["land_rights"][index] if active else 0.0, label="доля ВРИ")
        put(f"R{row}", number=(
            (social_cash_by_phase[index] if index < len(social_cash_by_phase) else 0.0)
            if social_cash_by_phase is not None
            else shared["social_compensation"][index]) if active else 0.0,
            label="доля соцнагрузки")
        offset_years = (offset if active else 0.0) / 12.0
        put(f"S{row}", number=(1.0 + price_inflation) ** offset_years, label="множитель цены")
        put(f"T{row}", number=(1.0 + cost_inflation) ** offset_years, label="множитель затрат")
        # Доли лимитов — от движковых лимитов фаз, а не от квартирных весов:
        # очередь с офисами на 13,5 млрд получала 28% лимита ПФ по весу
        # квартир, и книга недосчитывала плату за невыбранный лимит вдвое.
        # Без движка (fallback) — живой формулой от полных расходов очереди:
        # блочные итоги CAPEX несут покупку, ВРИ, социалку и объекты.
        pf_hint = list((finance_hints or {}).get("pf_limit_by_phase") or [])
        bridge_hint = list((finance_hints or {}).get("bridge_peak_by_phase") or [])
        pf_hint = _v4_fold_tail(pf_hint, len(pf_hint), count) if pf_hint else []
        bridge_hint = _v4_fold_tail(bridge_hint, len(bridge_hint), count) if bridge_hint else []
        pf_total = sum(pf_hint)
        bridge_total = sum(bridge_hint)
        # Доля очереди в лимите ПФ считается тем же, чем считается сам лимит
        # (B26): доля от числа при живом лимите разошлась бы с ним на первой же
        # правке календаря — сумма долей перестала бы быть единицей. Формула
        # стоит и у выключенной очереди: включат её прямо в книге — доля пойдёт
        # за выборкой, а ноль остался бы нулём.
        phase_limit = _V4_PF_LIMIT_PHASE.format(n=index + 1)
        put(f"V{row}", formula=f"IFERROR({phase_limit}/$B$26,0)", label="доля лимита ПФ")
        if active and pf_total > 0 and index < len(pf_hint):
            put(f"U{row}", number=(bridge_hint[index] / bridge_total
                                   if bridge_total > 0 and index < len(bridge_hint)
                                   else pf_hint[index] / pf_total),
                label="доля лимита БРИДЖ")
        elif active:
            need_cell = ("'CAPEX'!$B$35", "'CAPEX'!$B$69",
                         "'CAPEX'!$B$103", "'CAPEX'!$B$137")[index]
            need_total = "SUM('CAPEX'!$B$35,'CAPEX'!$B$69,'CAPEX'!$B$103,'CAPEX'!$B$137)"
            share_formula = f"IFERROR({need_cell}/{need_total},{1.0 if index == 0 else 0.0})"
            put(f"U{row}", formula=share_formula, label="доля лимита БРИДЖ")
        else:
            put(f"U{row}", number=0.0, label="доля лимита БРИДЖ")
        put(f"W{row}", number=num_row(crow.get("apartments"), "gns"), label="ГНС квартир")
        put(f"X{row}", number=num_row(crow.get("ground_commercial"), "gns"),
            label="ГНС коммерции")
        # Не «ГНС подземная»: ГНС — наземная площадь здания, а под землёй
        # наружных стен не бывает. Здесь площадь подземного этажа.
        put(f"Y{row}", number=num_row(crow.get("underground_parking"), "gns"),
            label="Подземная площадь")
        put(f"Z{row}", number=num_row(crow.get("apartments"), "saleable"),
            label="прод. квартир")
        put(f"AA{row}", number=num_row(crow.get("ground_commercial"), "saleable"),
            label="прод. коммерции")
        # Строится весь паркинг (ГНС в Y), а продаются только не гостевые места:
        # AB кормит «Продажи», поэтому здесь стоит проданное, а не построенное.
        put(f"AB{row}", number=underground_saleable_spaces(crow.get("underground_parking") or {}),
            label="паркинг к продаже, шт.")
        # Кладовые — то же правило, что у паркинга: строится всё, продаётся
        # непереданное. AC кормит «Продажи».
        put(f"AC{row}", number=storage_saleable_spaces(crow.get("storage") or {}),
            label="кладовые к продаже, шт.")
        # Построенных мест и проданных — разные числа, и книга показывала только
        # проданные: почему их меньше, узнать было негде. Гостевые и переданные
        # в натуре стоят рядом справочными колонками (в продажи не идут).
        _parking_row = crow.get("underground_parking") or {}
        # Колонок AN–AP в шаблоне нет: пишем со вставкой, как кассовые доли.
        for _col, _value in (("AN", float(underground_guest_spaces(_parking_row))),
                             ("AO", transferred_units(_parking_row)),
                             ("AP", transferred_units(crow.get("storage") or {}))):
            xml, _done = _v4_set_or_insert_cell(xml, f"{_col}{row}", number=_value)
            if not _done:
                missing.append(f"гостевые и переданные места очереди {index + 1}")
        if index == 0:
            for _col, _title in (("AN", "Из них гостевых, шт."),
                                 ("AO", "Из них передано, шт."),
                                 ("AP", "Кладовых передано, шт.")):
                xml, _done = _v4_set_or_insert_cell(xml, f"{_col}87", text=_title)
                if not _done:
                    missing.append(f"подпись колонки {_col} блока очередей")
        # Квартир в очереди: база и живое число. Колонок в шаблоне нет —
        # пишем со вставкой, как гостевые места и площадь кладовых.
        _base_col = _V4_APARTMENT_UNITS_BASE_COL
        _units_col = _V4_APARTMENT_UNITS_COL
        xml, _done = _v4_set_or_insert_cell(
            xml, f"{_base_col}{row}", number=num_row(crow.get("apartments"), "units"))
        if not _done:
            missing.append(f"база числа квартир очереди {index + 1}")
        xml, _done = _v4_set_or_insert_cell(
            xml, f"{_units_col}{row}", formula=f"ROUND({_base_col}{row}*$K$15,0)")
        if not _done:
            missing.append(f"число квартир очереди {index + 1}")
        if index == 0:
            for _col, _title in ((_base_col, "База числа квартир, шт."),
                                 (_units_col, "Квартир, шт.")):
                xml, _done = _v4_set_or_insert_cell(xml, f"{_col}87", text=_title)
                if not _done:
                    missing.append(f"подпись колонки {_col} блока очередей")
        # Площадь кладовых — своя колонка, а не слагаемое к паркингу. У книги
        # ЕСТЬ строки под неё (ТЭП «Кладовые» и ОТЧЕТ «Кладовые»), и обе стояли
        # пустыми: их метры не доезжали в книгу ВООБЩЕ, при том что итоги над
        # ними их складывают. На 400 кладовых по 4 м² это 1 600 м² подземной
        # части и 140,8 млн ₽ СМР, потерянных молча. Прибавлять их к колонке K
        # нельзя: её читают ТЭП и ОТЧЕТ под именем «Подземный паркинг», и
        # 43 565 м² под этим именем — то же самое, что «по ДДС» над числом из
        # РСС (владелец, 13.09.2026: кладовые ПРИБАВЛЯЮТ подземную площадь).
        # Плотность двигает их тем же признаком, что и штуки кладовых (K81),
        # а не признаком паркинга: у продукта один ответ на «следует ли он за
        # плотностью».
        # База считается ОТ ШТУК той же очереди (AC к продаже плюс AP
        # переданные) и площади одной кладовой: числом она стояла мёртвой —
        # правка штук в книге не двигала ни метров, ни СМР. Расхождение с
        # движком уходит в `missing`, а не проходит молча: у очереди, где
        # штуки нулевые при живых метрах, формула дала бы ноль, и книга
        # потеряла бы подземную площадь так же тихо, как теряла её до 0.23.54.
        _storage_area = num_row(crow.get("storage"), "gns")
        _storage_units = (storage_saleable_spaces(crow.get("storage") or {})
                          + transferred_units(crow.get("storage") or {}))
        _storage_per = float(_storage_per_unit_value)
        if abs(_storage_units * _storage_per - _storage_area) > 1.0:
            missing.append(f"площадь кладовых очереди {index + 1} не сходится "
                           f"со штуками: {_storage_area:.1f} м² против "
                           f"{_storage_units:.0f} × {_storage_per:.2f}")
        xml, _done = _v4_set_or_insert_cell(
            xml, f"AQ{row}",
            formula=f"ROUND((AC{row}+AP{row})*{_storage_per_unit},1)")
        if not _done:
            missing.append(f"база площади кладовых очереди {index + 1}")
        xml, _done = _v4_set_or_insert_cell(
            xml, f"AR{row}",
            formula=f'ROUND(AQ{row}*IF($K$81="Да",$K$15,1),0)')
        if not _done:
            missing.append(f"площадь кладовых очереди {index + 1}")
        if index == 0:
            for _col, _title in (("AQ", "База площади кладовых"),
                                 ("AR", "Площадь кладовых, м²"),
                                 (_V4_PF_QUEUE_INDIVIDUAL_COL, "Лимит НКЛ очереди, млн"),
                                 (_V4_PF_QUEUE_CAP_COL, "Потолок ПФ очереди, млн")):
                xml, _done = _v4_set_or_insert_cell(xml, f"{_col}87", text=_title)
                if not _done:
                    missing.append(f"подпись колонки {_col} блока очередей")
        # Одобренный лимит у очередей — два поля (владелец, 19.09.2026):
        # общий по генеральным условиям (F26) и лимит НКЛ очереди по
        # индивидуальным. Потолок очереди — только её лимит НКЛ; общий лимит
        # у очередей — ожидание на все, потолком не служит (уточнение
        # владельца, 20.09.2026: НКЛ каждой очереди считается заново при её
        # открытии). У ОДИНОЧНОГО проекта очередь одна, и F26 — её потолок,
        # как в движке. Ноль в AT — «потолка нет», и строка 45 листа CF
        # читает его так же.
        _queue_cfg = ((p.get("phases") or []) + [{}] * 4)[index] or {}
        _individual = max(0.0, float(_queue_cfg.get("pf_limit_approved_mln") or 0.0))
        xml, _done = _v4_set_or_insert_cell(
            xml, f"{_V4_PF_QUEUE_INDIVIDUAL_COL}{row}", number=_individual)
        if _done:
            xml = _v4_mark_as_entry(xml, f"{_V4_PF_QUEUE_INDIVIDUAL_COL}{row}", missing)
        else:
            missing.append(f"лимит НКЛ очереди {index + 1}")
        _general_fallback = (
            f"${_V4_PF_APPROVED_CELL[0]}${_V4_PF_APPROVED_CELL[1:]}"
            if (index == 0 and enabled_phases == 1) else "0")
        xml, _done = _v4_set_or_insert_cell(
            xml, f"{_V4_PF_QUEUE_CAP_COL}{row}",
            formula=(f"IF({_V4_PF_QUEUE_INDIVIDUAL_COL}{row}>0,"
                     f"{_V4_PF_QUEUE_INDIVIDUAL_COL}{row},{_general_fallback})"))
        if not _done:
            missing.append(f"потолок ПФ очереди {index + 1}")
        put(f"AE{row}", number=0.0, label="инфляция цены")
        put(f"AF{row}", number=0.0, label="инфляция затрат")
        # Тренд темпа продаж — движковый pace (25% по умолчанию): вес месяца
        # растёт линейно от старта продаж к РВЭ, после РВЭ не действует.
        # Дефолт шаблона 1%/мес компаундился всё окно продаж и смещал объём
        # в дорогие месяцы: +36 млн по квартирам на Мытищах из ниоткуда.
        put(f"AD{row}", number=float(x.get("pace_adjustment_pct") or 0) / 100.0,
            label="тренд темпа продаж")

    # --- ступени ставки ПФ -------------------------------------------------
    # Лестница — вводная и здесь: блок ячеек внизу «Вводных», формулы строки 41
    # CF-листов ссылаются на него (владелец, 20.08.2026: «сейчас-то надбавка —
    # это вводная»). Пустое поле оставляет одну ставку B28, как было.
    # --- кривая ключевой ставки -------------------------------------------
    # Форма кривой и смещение от даты стартовой ставки стояли ЧИСЛАМИ внутри
    # формулы листа «Ставки», а сценарий книга не знала вовсе. Теперь это три
    # вводные ячейки, и формулы читают их.
    try:
        _rc_raw = str(x.get("rate_start_date") or "")[:10]
        _rc_start = date.fromisoformat(str(x.get("project_start") or "2027-01-01")[:10])
        _rc_date = date.fromisoformat(_rc_raw) if _rc_raw else _rc_start
        _rc_offset = ((_rc_start.year - _rc_date.year) * 12
                      + (_rc_start.month - _rc_date.month)
                      - (1 if _rc_date.day > 1 else 0))
        _rc_shape = max(0.05, float(x.get("rate_curve_shape") or 2.0))
    except Exception:
        _rc_date, _rc_offset, _rc_shape = None, 0, 2.0
    _rc_scenario = _v4_mode_display(
        "rate_scenario", str(x.get("rate_scenario") or "base").strip().lower())
    _rc_refs: dict[str, str] = {}
    try:
        xml, _rc_refs = _v4_rate_curve_rows_xml(
            xml, _rc_scenario, _rc_date, _rc_shape, _rc_offset,
            {"rate_target_base_pct": n(x, "rate_target_base_pct", 9.0) / 100.0,
             "rate_target_low_pct": n(x, "rate_target_low_pct", 7.0) / 100.0,
             "rate_target_high_pct": n(x, "rate_target_high_pct", 11.0) / 100.0},
            {"project_class": str(x.get("project_class") or ""),
             "tep_ratios_custom": str(x.get("tep_ratios_custom") or ""),
             "project_kind": dict(PROJECT_KINDS).get(project_kind(x), "")})
    except Exception as exc:
        missing.append("Вводные · кривая ключевой ставки: " + _error_location(exc))
    if _rc_refs:
        # Целевая ставка активного сценария выбиралась по B6 — общему драйверу
        # сценария, который движок закрепляет словом «Base» (в колонку Base он
        # пишет ПРИМЕНЁННЫЕ множители цены и затрат). Поэтому у ставки свой
        # селектор: иначе проект на консервативном сценарии книга считала по
        # базовой целевой — 4 516 млн ₽ у движка против 4 165 у книги.
        for _coord, _key in (("E8", "rate_target_base_pct"),
                             ("F8", "rate_target_low_pct"),
                             ("G8", "rate_target_high_pct")):
            put(_coord, formula=_rc_refs[_key], label=f"читалка {_key}")
        # Целевая ставка выбиралась по B6 — общему драйверу сценария, который
        # движок закрепляет словом «Base» (в колонку Base он пишет ПРИМЕНЁННЫЕ
        # множители цены и затрат, и это верно). У ставки сценарий свой: иначе
        # проект на консервативном шёл по базовой целевой — 12,82→11,00% у
        # движка против 12,03→9,00% у книги.
        put("H8", formula=f"INDEX($E$8:$G$8,1,MATCH({_rc_refs['rate_scenario']},$E$4:$G$4,0))",
            label="целевая ставка по rate_scenario")
    _rc_shape_ref = (f"'Вводные'!{_rc_refs['rate_curve_shape']}" if _rc_refs
                     else f"{_rc_shape:g}")
    _rc_offset_ref = (f"'Вводные'!{_rc_refs['offset']}" if _rc_refs
                      else f"{_rc_offset:d}")
    from openpyxl.utils import get_column_letter as _rate_col
    for _rate_index in range(_V4_MONTH_COLUMNS):
        _X = _rate_col(_V4_CF_FIRST_COL + _rate_index)
        _progress = (f"(1-EXP(-{_rc_shape_ref}*MIN(MAX(0,{_X}$4-1+{_rc_offset_ref}),"
                     f"'Вводные'!$B$35)/'Вводные'!$B$35))/(1-EXP(-{_rc_shape_ref}))")
        rates_xml, done = _v4_set_cell(
            rates_xml, f"{_X}5",
            formula=(f"MAX(0,'Вводные'!$B$34,'Вводные'!$B$33"
                     f"+('Вводные'!$B$34-'Вводные'!$B$33)*{_progress})"))
        if not done:
            missing.append(f"кривая ключевой ставки: колонка {_rate_index}")
            break

    _ladder_steps = pf_special_steps(x.get("pf_special_steps"))
    _ladder_refs: list[tuple[str, str]] = []
    _ladder_swapped = 0
    if _ladder_steps:
        try:
            xml, _ladder_refs = _v4_ladder_rows_xml(xml, _ladder_steps)
        except Exception as exc:
            _ladder_steps = []
            missing.append("Вводные · ступени ставки ПФ: " + _error_location(exc))

    # --- график платежей за покупку и графики продаж объектов ---------------
    # Методику меняют в двух местах — в движке и в книге. Движок платит покупку
    # по графику и продаёт объекты по профилю и лестнице; книга читает те же
    # шаги из блоков внизу «Вводных». Пусто — формулы шаблона, как было.
    _purchase_items, _purchase_percent, _ = parse_month_schedule(x.get("purchase_schedule"))
    if _purchase_items:
        _price_mln = float(x.get("purchase_price_mln") or 0.0)
        if _purchase_percent:
            _total = sum(amount for amount, _ in _purchase_items) or 1.0
            _shares = [(month, amount / _total) for amount, month in _purchase_items]
        elif _price_mln > 0:
            _shares = [(month, amount / _price_mln) for amount, month in _purchase_items]
            _rest = 1.0 - sum(share for _, share in _shares)
            if abs(_rest) > 1e-9:
                _shares.insert(0, (0, _rest))
        else:
            _shares = []
        _merged: dict[int, float] = {}
        for month, share in _shares:
            _merged[month] = _merged.get(month, 0.0) + share
        if _merged:
            try:
                xml, _purchase_refs = _v4_schedule_rows_xml(
                    xml, "ГРАФИК ПЛАТЕЖЕЙ ЗА ПОКУПКУ",
                    "Месяц от старта очереди → доля цены. Строки покупки CAPEX читают отсюда.",
                    sorted(_merged.items()), "доля", key="purchase_schedule")
                capex_xml = _v4_apply_purchase_schedule(capex_xml, _purchase_refs, missing)
            except Exception as exc:
                missing.append("Вводные · график платежей за покупку: " + _error_location(exc))
    _core_growth = [n(x, f"growth_stage{k}_pct", 0.0) / 100.0 for k in (1, 2, 3, 4)]
    if any(_core_growth):
        try:
            xml, _core_refs = _v4_stage_rows_xml(
                xml, "ЛЕСТНИЦА ЦЕНЫ · КВАРТИРЫ И ОСНОВНЫЕ ПРОДУКТЫ",
                "Рост цены при строительной готовности 25/50/75/100% (четверти срока строительства очереди). Строки цен листа «Продажи» читают отсюда.",
                _core_growth,
                keys=tuple(f"growth_stage{k}_pct" for k in (1, 2, 3, 4)))
            sales_xml = _v4_apply_core_ladder(sales_xml, _core_refs, missing)
        except Exception as exc:
            missing.append("Вводные · лестница цены квартир: " + _error_location(exc))
    for _prefix, _label in ((_lay.obj.prefix, _lay.obj.label) for _lay in
                            sorted(_v4_layouts(), key=lambda lay: lay.input_head)):
        _profile_items, _profile_percent, _ = parse_month_schedule(x.get(f"{_prefix}_sales_profile"))
        _growth = [n(x, f"{_prefix}_growth_stage{k}_pct", 0.0) / 100.0 for k in (1, 2, 3, 4)]
        _profile_refs = _stage_refs = None
        try:
            if _profile_items and _profile_percent:
                _total = sum(amount for amount, _ in _profile_items) or 1.0
                xml, _profile_refs = _v4_schedule_rows_xml(
                    xml, f"ПРОФИЛЬ ПРОДАЖ · {_label.upper()}",
                    "Месяц от старта продаж → доля объёма. Строка «Реализованный объём» листа ОБЪЕКТЫ читает отсюда.",
                    [(month, amount / _total) for amount, month in _profile_items], "доля",
                    key=f"{_prefix}_sales_profile")
            if any(_growth):
                xml, _stage_refs = _v4_stage_rows_xml(
                    xml, f"ЛЕСТНИЦА ЦЕНЫ · {_label.upper()}",
                    "Рост цены при строительной готовности 25/50/75/100% объекта. Строка «Цена реализации» листа ОБЪЕКТЫ читает отсюда.",
                    _growth,
                    keys=tuple(f"{_prefix}_growth_stage{k}_pct" for k in (1, 2, 3, 4)))
            if _profile_refs or _stage_refs:
                objects_xml = _v4_apply_object_schedule(
                    objects_xml, _prefix, _profile_refs, _stage_refs, missing)
        except Exception as exc:
            missing.append(f"Вводные · график продаж {_label}: " + _error_location(exc))

    # --- сборка ------------------------------------------------------------
    # Кэшированные результаты формул шаблона стираются на всех листах:
    # просмотрщики (Telegram, iOS) формулы не считают и показывали числа
    # проекта, под который книга собиралась в прошлый раз, — «модель не
    # подтянула вводные». Excel пересчитает всё при открытии
    # (fullCalcOnLoad уже стоит в книге).
    # --- один ввод: «Вводные» для рук, «Параметры модели» для формул --------
    # Двух вводов быть не должно (владелец, 04.09.2026): два места ввода — это
    # два достоверных на вид ответа про одно число. Лист шаблона со всеми
    # своими 85 665 ссылками остаётся на месте и только переименовывается —
    # адреса не двигаются, — а каждая ячейка, в которую печатали, уезжает на
    # новый лист, оставляя по себе читалку. Что считается вводом, решает цвет
    # самого шаблона, а не наш список: забытая в списке ячейка осталась бы
    # жёлтой на расчётном листе, то есть приглашала бы печатать там, где
    # печатать больше нельзя.
    styles_xml = source.read("xl/styles.xml").decode("utf-8")
    # Правый блок E:H — та же пользовательская форма, что A:D. Стиль ставится
    # ДО переноса и ПОСЛЕ того, как блок дописан: лист «Вводные» собирается
    # из ячеек, которые помечены как пользовательский ввод, а строки E:H
    # появляются в этой же сборке выше — зеркало, вызванное раньше них,
    # красило пустое место, и блок уезжал на лист ввода без стилей.
    report_xml, tep_xml, styles_xml = _v4_report_number_formats(
        report_xml, tep_xml, consolidator_xml, styles_xml)
    xml = _v4_mirror_secondary_input_styles(xml)
    xml, styles_xml = _v4_type_input_formats(xml, styles_xml, _v4_block_input_formats(
        social_base_row, _ladder_refs, _landscaping_norm))
    xml = _v4_mark_engine_only_readonly(xml)
    xml = v4_entry_sheet.rename_sheet_refs(xml)
    try:
        xml, entry_xml, entry_report = v4_entry_sheet.build(xml, styles_xml)
        # Читалки «Параметров модели» несут формат своей вводной — это новые
        # стили, и книга обязана получить styles.xml, где они есть.
        styles_xml = entry_report.get("styles_xml") or styles_xml
        # Engine-only поля снимаются ДО декодеров: декодер региона читает
        # $K$6 расчётного листа, и туда значение должно вернуться раньше.
        entry_xml, xml = _v4_strip_engine_only_from_entry(entry_xml, xml, entry_report, missing)
        xml = _v4_apply_mode_decoders(
            xml, entry_report, _rc_refs.get("rate_scenario"), missing)
        # Dropdown принадлежит именно пользовательскому листу. До разделения
        # листов validation на старом XML остался бы на «Параметры модели»,
        # где человек ничего не вводит.
        entry_xml = _v4_add_mode_dropdowns(entry_xml, missing)
    except Exception as exc:  # noqa: BLE001 — книга без листа ввода не выпускается молча
        entry_xml, entry_report = "", {}
        missing.append("Вводные · лист ввода не собран: " + _error_location(exc))
    if entry_xml and not entry_report.get("moved"):
        missing.append("Вводные · на лист ввода не переехало ни одной ячейки")
    # Отпечаток вводных — только теперь: лист ввода собирается последним, а
    # цель гейта считается по нему. Не собрался — цель остаётся пустой, и
    # паритет ведёт себя ровно так, как до появления гейта.
    if entry_xml and _parity:
        checks_xml, _stamped = _v4_set_cell(
            checks_xml, f"C{_V4_PARITY_GATE_ROW}",
            number=round(_v4_entry_fingerprint(entry_xml), 6))
        if not _stamped:
            missing.append("гейт паритета: отпечаток листа ввода не записан")
    # Объекты вне ДДУ формулами книги не моделируются: их деньги приходят
    # листом движка, и расхождение сверки названо, а не спрятано.
    _nonres_xml = ""
    _nonres = (finance_hints or {}).get("nonres") or {}
    if _nonres.get("report"):
        _nonres_xml = v4_nonres_sheet.build_sheet(_nonres["report"], _nonres.get("monthly") or [],
                                                  _nonres.get("objects") or [],
                                                  _nonres.get("financing") or [])
        missing.append(
            "Нежильё — стратегия: " + ", ".join(
                f"{item.get('title')} — {next((r.get('value') for r in item.get('rows') or [] if r.get('label') == 'Стратегия'), '')}"
                for item in _nonres["report"])
            + ". Формулы книги считают эти объекты по ДДУ; результат движка — "
              "на листе «Нежильё — стратегия», сверка «ПРОВЕРКИ» по ним расходится.")

    # Инструкция собирается ПОСЛЕ всего: она читает готовый лист ввода и
    # `missing` целиком. Написанная раньше, она обещала бы книгу, которой ещё
    # нет, — и разошлась бы с ней ровно тем, что добавили следом.
    guide_xml = ""
    if entry_xml:
        try:
            guide_xml = v4_entry_sheet.guide(entry_xml, xml, styles_xml,
                                             entry_report, missing)
        except Exception as exc:  # noqa: BLE001 — молчащая инструкция хуже отсутствующей
            missing.append("Вводные · лист инструкции не собран: " + _error_location(exc))

    # «Дашборд» и его скрытый источник `Dashboard_Data`: формулы на листы книги,
    # три диаграммы на диапазоны источника. Не собрался — книга выходит с
    # прежним листом шаблона, и это названо в `missing`, а не спрятано.
    _dashboard: dict[str, Any] | None = None
    try:
        _dashboard = v4_dashboard.build(
            source, _v4_sheet_path(source, v4_dashboard.DASHBOARD_SHEET), styles_xml,
            presentation_origin(inputs, calculation_source_tep, phasing),
            _AGENT_BANK_LLCR_TARGET, _v4_cf_columns(), enabled_phases > 1,
            _V4_CAPEX_ARTICLE_ROW, _V4_CAPEX_BLOCK_STRIDE,
            _v4_dashboard_extra_products(),
            frozenset(o.key for o in STANDALONE_OBJECTS if b(x, o.enabled_key)),
            hidden_products=_v4_absent_products(x, tep), queues=count,
            parking=(finance_hints or {}).get("parking_provision"))
    except Exception as exc:  # noqa: BLE001 — дашборд без книги не выпускается молча
        missing.append("Дашборд · не собран: " + _error_location(exc))

    capex_xml = _v4_deal_includes_buyout(
        capex_xml, "CAPEX",
        tuple(_V4_CAPEX_PURCHASE_ROW + _V4_CAPEX_BLOCK_STRIDE * k for k in range(_V4_CAPEX_PHASES)),
        missing)
    for _name in list(cf_sheet_xml):
        cf_sheet_xml[_name] = _v4_deal_includes_buyout(
            cf_sheet_xml[_name], _name, (_V4_CF_VAT_ROW,), missing)
    report_xml = _v4_deal_includes_buyout(report_xml, "ОТЧЕТ", (33,), missing)

    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as archive:
        for item in source.infolist():
            if _dashboard and item.filename in _dashboard["dropped"]:
                continue
            payload = source.read(item.filename)
            if item.filename == sheet_path:
                payload = xml.encode("utf-8")
            elif _dashboard and item.filename in _dashboard["parts"]:
                payload = _dashboard["parts"][item.filename]
            elif item.filename == "xl/styles.xml":
                # Стили пишутся всегда: форматы вводных и читалок дописаны в
                # каталог до дашборда, и книга без дашборда их тоже несёт.
                payload = (_dashboard["styles_xml"] if _dashboard else styles_xml).encode("utf-8")
            elif item.filename == report_sheet_path:
                payload = report_xml.encode("utf-8")
            elif item.filename == tep_sheet_path:
                payload = tep_xml.encode("utf-8")
            elif item.filename == capex_sheet_path:
                payload = capex_xml.encode("utf-8")
            elif item.filename == vri_sheet_path:
                payload = vri_xml.encode("utf-8")
            elif item.filename == objects_sheet_path:
                payload = objects_xml.encode("utf-8")
            elif item.filename == sales_sheet_path:
                payload = sales_xml.encode("utf-8")
            elif item.filename == rates_sheet_path:
                payload = rates_xml.encode("utf-8")
            elif item.filename == sources_sheet_path:
                payload = sources_xml.encode("utf-8")
            elif item.filename == checks_sheet_path:
                payload = checks_xml.encode("utf-8")
            elif item.filename == consolidator_sheet_path:
                payload = consolidator_xml.encode("utf-8")
            elif item.filename in cf_sheet_paths.values():
                payload = cf_sheet_xml[
                    next(k for k, v in cf_sheet_paths.items() if v == item.filename)
                ].encode("utf-8")
            if item.filename.startswith("xl/worksheets/") and item.filename.endswith(".xml"):
                text = payload.decode("utf-8")
                text = re.sub(r"(<x:f(?:\s[^>]*)?>[^<]*</x:f>)<x:v>[^<]*</x:v>", r"\1", text)
                text = re.sub(r"(<x:f(?:\s[^>]*)?/>)<x:v>[^<]*</x:v>", r"\1", text)
                if _ladder_steps and "'Вводные'!$B$28" in text:
                    text, swapped = _v4_step_worksheet_xml(text, _ladder_steps, _ladder_refs)
                    _ladder_swapped += swapped
                # Лист вводных уже переименован до сборки — у него читалки на
                # новый лист, и второй проход увёл бы их обратно.
                if item.filename != sheet_path:
                    text = v4_entry_sheet.rename_sheet_refs(text)
                # Метка ставится уже после переименования: написанная прямо,
                # ссылка на лист ввода уехала бы вместе со всеми на расчётный.
                text = text.replace(_V4_ENTRY_SHEET_TOKEN,
                                    f"'{v4_entry_sheet.ENTRY_SHEET}'!")
                payload = text.encode("utf-8")
            elif item.filename == "xl/workbook.xml":
                text = _v4_workbook_with_entry(payload.decode("utf-8"), bool(entry_xml))
                if _dashboard:
                    text = v4_dashboard.workbook_with_data_sheet(text)
                if _nonres_xml:
                    text = v4_nonres_sheet.workbook_with_sheet(text)
                payload = text.encode("utf-8")
            elif item.filename == "xl/_rels/workbook.xml.rels":
                text = payload.decode("utf-8")
                if entry_xml:
                    text = _v4_rels_with_entry(text)
                if _dashboard:
                    text = v4_dashboard.rels_with_data_sheet(text)
                if _nonres_xml:
                    text = v4_nonres_sheet.rels_with_sheet(text)
                payload = text.encode("utf-8")
            elif item.filename == "[Content_Types].xml":
                text = payload.decode("utf-8")
                if entry_xml:
                    text = _v4_types_with_entry(text)
                if _dashboard:
                    text = v4_dashboard.types_with_data_sheet(text, _dashboard["dropped"])
                if _nonres_xml:
                    text = v4_nonres_sheet.types_with_sheet(text)
                payload = text.encode("utf-8")
            archive.writestr(item, payload)
        if entry_xml:
            archive.writestr(_V4_ENTRY_SHEET_PATH, entry_xml.encode("utf-8"))
            archive.writestr(_V4_GUIDE_SHEET_PATH, guide_xml.encode("utf-8"))
        if _nonres_xml:
            archive.writestr(v4_nonres_sheet.SHEET_PATH, _nonres_xml.encode("utf-8"))
        if _dashboard:
            # Источник дашборда — новая часть, мимо цикла: ссылки на лист ввода
            # переименовываются здесь же, как у остальных листов.
            data_xml = _dashboard["parts"][v4_dashboard.DATA_SHEET_PATH].decode("utf-8")
            archive.writestr(v4_dashboard.DATA_SHEET_PATH,
                             v4_entry_sheet.rename_sheet_refs(data_xml).encode("utf-8"))
            for path in _dashboard["added_charts"]:
                archive.writestr(path, _dashboard["parts"][path])
    source.close()
    if _ladder_steps and not _ladder_swapped:
        # Ступени заданы, а формулы не тронуты — книга посчитает по одной
        # ставке, отчёт по лестнице, и оба будут выглядеть достоверно.
        missing.append("CF · ступени ставки по покрытию эскроу")

    # Значения кладутся рядом с формулами, а не вместо них. Без них книга
    # пуста везде, где формулы не считают: предпросмотр в телеграме, Quick Look,
    # телефон, диски — и владелец открыл выгрузку 13.09.2026 со словами «модель
    # пустая вообще». Считает их наш же вычислитель; `fullCalcOnLoad="1"`
    # остаётся, поэтому в Excel число живёт ровно до открытия и устареть не
    # может. Сбой оставляет книгу без значений и говорит об этом: выгрузка без
    # чисел хуже, чем с ними, но несобранная выгрузка хуже обеих.
    content = out.getvalue()
    # Оформление по решениям владельца (ревизия 29.09.2026): порядок листов,
    # закрепления, печать, форматы по единице, скрытие того, чего нет в
    # проекте. Только стили и атрибуты — формулы не трогаются.
    _hidden_rows, _hidden_sheets = _v4_hidden_plan(x, tep, count, entry_xml)
    try:
        content = v4_book_polish.polish(content, hidden_rows=_hidden_rows,
                                        hidden_sheets=_hidden_sheets, missing=missing)
    except Exception as exc:  # noqa: BLE001 — книга без оформления лучше несобранной
        missing.append("оформление книги не применено: " + _error_location(exc))
    polished = content
    # Счёт всей книги стоит около четырнадцати секунд — для выгрузки это
    # ничто, а для набора тестов много: книгу собирают 62 файла, и на каждой
    # сборке набор подорожал бы получасом. Поэтому `tests/conftest.py` гасит
    # проход, а проверка, которая его и держит, включает обратно. Умолчание —
    # ВКЛЮЧЕНО: выгрузка без значений и есть та болезнь, от которой всё это.
    if cache_values is None:
        cache_values = os.environ.get("DEVELOPAID_WORKBOOK_CACHE", "1") not in (
            "0", "false", "no", "")
    try:
        if not cache_values:
            raise _SkipValueCache
        content, cache_report = v4_value_cache.with_cached_values(content)
        if cache_report.get("unresolved"):
            missing.append(
                f"сохранённые значения: {cache_report['unresolved']} формул "
                f"вычислитель не понял, эти клетки останутся пустыми вне Excel "
                f"({', '.join(cache_report.get('examples') or [])})")
    except _SkipValueCache:
        pass
    except Exception as exc:  # noqa: BLE001 — молчащая потеря значений и есть болезнь
        content = polished
        missing.append("сохранённые значения не записаны: " + _error_location(exc))

    stem = _safe_file_stem(title, "project")
    filename = f"DevelopAid_модель_{stem}_{date.today().isoformat()}.xlsx"
    return content, filename, {"missing": missing, "phased": count > 1,
                                      "class_deviations": class_deviations}


class WorkbookExportRequest(BaseModel):
    inputs: dict[str, Any]
    tep: dict[str, dict[str, Any]]
    rates: list[dict[str, Any]] = []
    phasing: dict[str, Any] = {}
    project_name: str = ""
    scenario: str = "base"


_XLSX_MEDIA_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


@app.post("/report/workbook")
def report_workbook(req: WorkbookExportRequest) -> Response:
    try:
        content, filename, meta = build_project_workbook(
            req.inputs, req.tep, req.rates, req.phasing,
            project_name=req.project_name, scenario=req.scenario,
        )
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Не удалось собрать книгу: {exc}") from exc
    if meta.get("missing"):
        # Молча пропущенное поле — потерянные данные: доносим в журнал.
        _TELEGRAM_RUNTIME["last_error"] = "Книга v4, без соответствия: " + "; ".join(
            str(item) for item in meta["missing"][:6])
    encoded_name = urllib.parse.quote(filename)
    return Response(
        content=content,
        media_type=_XLSX_MEDIA_TYPE,
        headers={
            "Content-Disposition":
                f"attachment; filename=DevelopAid_model.xlsx; filename*=UTF-8''{encoded_name}",
        },
    )
