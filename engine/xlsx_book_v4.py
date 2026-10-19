"""Единая книга проекта v4: templates/DevelopAid_model_v4.xlsx — шаблон,
раскладка объектов, ячейки и режимы листа «Вводные», форматы и стили ввода.

Книга v4 лежит кусками `engine/xlsx_book_v4*.py`; `main_legacy.py` выполняет
их подряд, в прежнем порядке объявлений. Этот кусок — первый, сборка книги и
маршрут /report/workbook — в `xlsx_book_v4_build.py`.

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
    "AS": _V4_FMT_AMOUNT, "AY": _V4_FMT_AREA,
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
