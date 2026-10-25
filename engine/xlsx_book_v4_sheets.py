"""Дописанные листы книги v4: стили шаблона, источники нормативов, лестница и
кривые ставок, подсказки финансирования, графики покупки, объектов и ядра,
лимит ПФ.

Кусок книги v4: файлы `engine/xlsx_book_v4*.py` выполняются подряд на
месте прежнего `_engine_part("xlsx_book_v4")`. Не самостоятельный модуль:
`main_legacy.py` выполняет этот файл в своём пространстве имён
(`_engine_part("xlsx_book_v4_sheets")`), поэтому здесь видны все имена движка,
а подмены `core.<имя>` из `main.py` и тестов действуют и на этот код.
Отдельно не импортировать: второй импорт поднял бы вторую копию движка.
"""
# ruff: noqa

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
    "not_confirmed": "Не подтверждено",
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
    # Другой регион — ни московских, ни областных актов: его норм у нас нет,
    # и остаются одни федеральные.
    region = project_regions.region_code(region)
    scope_here = project_regions.LABELS[region]
    foreign = {"Москва", "Московская область"} - {scope_here}
    kept = [row for row in rows if str(row.get("scope") or "").strip() not in foreign]
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
               "Акты реестра движка ("
               + ("только федеральный уровень: норм региона проекта у нас нет"
                  if region == project_regions.OTHER
                  else f"{scope_here} и федеральный уровень")
               + f"), снят "
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
    # IRR проекта (до финансирования) — числом движка: поток проекта книги
    # (CF!28) ведёт выручку по раскрытию эскроу, движок — по договорам, и
    # формула книги дала бы второе, несогласное число. Числом и при
    # непогашенном долге: «N/A — долг не погашен» — только у капитала
    # (владелец, 17.10.2026).
    _summary = (bundle.get("consolidated") or {}).get("summary") or {}
    hints["irr_project"] = {"value": _summary.get("irr_project")}
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
