"""Блок соцобъектов на «Вводных», вводные вне книги, строки только движка,
благоустройство, площади и норма кладовых.

Кусок книги v4: файлы `engine/xlsx_book_v4*.py` выполняются подряд на
месте прежнего `_engine_part("xlsx_book_v4")`. Не самостоятельный модуль:
`main_legacy.py` выполняет этот файл в своём пространстве имён
(`_engine_part("xlsx_book_v4_social")`), поэтому здесь видны все имена движка,
а подмены `core.<имя>` из `main.py` и тестов действуют и на этот код.
Отдельно не импортировать: второй импорт поднял бы вторую копию движка.
"""
# ruff: noqa

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
    "parking_district": (
        "район участка — вводная норматива (К2 по приложению 3 к 945-ПП) и "
        "Кмест льготы за МПТ (1874-ПП); владелец ответа — `site_position`, в "
        "книгу приходят число мест и сумма льготы"),
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
