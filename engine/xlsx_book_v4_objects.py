"""Объекты в книге v4: выручка очереди по продуктам на КОНСОЛИДАТОРЕ, блоки
дописанных объектов и их паркинга, строки ТЭП, структура продукта в ОТЧЁТЕ,
скрытые строки отсутствующих продуктов, ПРОВЕРКИ объектов.

Кусок книги v4: файлы `engine/xlsx_book_v4*.py` выполняются подряд на
месте прежнего `_engine_part("xlsx_book_v4")`. Не самостоятельный модуль:
`main_legacy.py` выполняет этот файл в своём пространстве имён
(`_engine_part("xlsx_book_v4_objects")`), поэтому здесь видны все имена движка,
а подмены `core.<имя>` из `main.py` и тестов действуют и на этот код.
Отдельно не импортировать: второй импорт поднял бы вторую копию движка.
"""
# ruff: noqa

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
        rate_ref = _v4_under_rate_ref(params_name)
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
    # Строка 58 — общая площадь очереди (слово — у глоссария), база
    # удельного CAPEX движка и Дашборда (решение 4 от 29.09, переход —
    # владелец 16.10.2026).
    ("A58", "Общая площадь (GBA)",
     f"{TOTAL_AREA.name}: наземная + подземная, объекты с гаражами, соцобъекты"),
    ("H58", "Жилые очереди и отдельно стоящие объекты",
     f"Как {TOTAL_AREA.lower()} листа ТЭП, по очередям"),
    ("A62", "CAPEX на м² GBA", f"CAPEX на м² {TOTAL_AREA.genitive}"),
    ("H62", "CAPEX очереди / общая площадь",
     f"CAPEX очереди / {TOTAL_AREA.lower()} (строка 58) — база движка"),
    ("F9", "CAPEX на м² GBA", f"CAPEX на м² {TOTAL_AREA.genitive}"),
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

    Гараж заведён 06.09.2026, а проверка CAPEX сравнивала фактический расход
    с «GBA × ставка» без подземного гаража. Кричащая зря проверка хуже
    отсутствующей — её перестают читать.

    «Реализованный объём» здесь не правится: ожидаемое в нём — расчётная
    продаваемая площадь объекта (K26 / K46), а она уже считается от GBA за
    вычетом мест первых этажей, пропорционально, как в движке. Прежде здесь
    вычиталось ещё раз «места × площадь своего ПОДЗЕМНОГО места»: дважды и не
    той площадью — и проверка писала FAIL (23 400 против 22 000), а статус
    модели «СБОЙ» на любом объекте с местами на первых этажах.

    Формулы не сочиняются: множители снимаются с самой формулы шаблона, а имя
    листа вводных берётся из неё же — он переименован, и зашитое имя однажды
    перестанет совпадать.
    """
    for (label, enabled_row, _units, _revenue, _capex_cell, under, _over,
         *_rest) in _v4_object_parking():
        rows = _V4_OBJECT_CHECK_ROWS.get(enabled_row)
        if rows is None:
            continue                      # своих проверок у объекта нет
        _volume_row, row = rows
        formula = _v4_cell_formula(xml, f"C{row}")
        if formula is None or not formula.endswith(",0)"):
            missing.append(f"ПРОВЕРКИ: C{row} ({label}, CAPEX) не опознана")
            continue
        sheet = re.search(r"('[^']+')!", formula)
        if sheet is None:
            missing.append(f"ПРОВЕРКИ: C{row} ({label}) без листа вводных")
            continue
        params = sheet.group(1)
        per_space = f"{params}!$K$158"
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
        addition = (f"+{under_ref}*{per_space}*{_v4_under_rate_ref(params)}/1000"
                    f"*{params}!$H$6"
                    f"*INDEX({params}!$T$88:$T$91,{phase})"
                    f"*INDEX({params}!$AH$88:$AH$91,{phase})")
        updated = formula[:-3] + addition + ",0)"
        xml, done = _v4_set_cell(xml, f"C{row}", formula=updated)
        if not done:
            missing.append(f"ПРОВЕРКИ: C{row} ({label}, CAPEX) не записана")
    return xml
