"""Перенос непогашенного долга между очередями на листах CF книги v4.

Кусок книги v4: файлы `engine/xlsx_book_v4*.py` выполняются подряд на
месте прежнего `_engine_part("xlsx_book_v4")`. Не самостоятельный модуль:
`main_legacy.py` выполняет этот файл в своём пространстве имён
(`_engine_part("xlsx_book_v4_debt_carry")`), поэтому здесь видны все имена движка,
а подмены `core.<имя>` из `main.py` и тестов действуют и на этот код.
Отдельно не импортировать: второй импорт поднял бы вторую копию движка.
"""
# ruff: noqa

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
# Единая касса проекта (financing_strategy = unified_project_cash): расходы
# следующей очереди до РнС покрываются свободной кассой предыдущих, и только
# остаток берётся БРИДЖем. Признак стоит в той же строке 92: это тоже условие
# финансирования очередей, а не свойство площадки. Читают его строки 88 листов CF.
# Третий блок вводных (подпись J, значение K, единица L, ключ M): во втором
# блоке F92 занята долей свипа, а колонка H по соглашению листа — ключ, не ввод.
_V4_UNIFIED_CASH_CELL = "K92"
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
                         sweep_share: float = 0.0, unified_cash: bool = False) -> str:
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
        f'<x:c r="F{row}"><x:v>{_v4_number(round(sweep_share, 6))}</x:v></x:c>'
        # Единая касса — рядом, той же строкой: свободная касса предыдущих
        # очередей покрывает расходы следующей до РнС (строки 88–89 CF).
        f'<x:c r="J{row}" t="str"><x:v>Единая касса проекта: расходы очереди до РнС '
        f'покрываются свободной кассой предыдущих</x:v></x:c>'
        f'<x:c r="{_V4_UNIFIED_CASH_CELL}" s="12" t="str"><x:v>'
        f'{"Да" if unified_cash else "Нет"}</x:v></x:c>'
        f'<x:c r="L{row}" t="str"><x:v>Да / Нет</x:v></x:c>'
        f'<x:c r="M{row}" t="str"><x:v>financing_strategy</x:v></x:c>')
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
