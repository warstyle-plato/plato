"""Contract documents read from PDF: «Расчёт договорной стоимости» and the ГПР.

One reader serves the contract and its supplementary agreements (ДС). A table
is read by its ruled grid: rows lie between horizontal rules, columns between
vertical rules. An unrecognised grid, header or row is a warning or an error
with its page, never an empty success. A scan without a text layer is named as
such. The reader returns positions and schedule lines with the page where each
was seen; it builds neither a plan nor a fact.

Schedule dates come from the start and finish cells. A bar of the chart gives
dates to a line whose cells are empty. A line whose cells disagree with its bar
by more than a day, or end before they start, takes the bar's dates; a group
line whose dates differ from the span of its works takes that span. Each such
correction keeps the original cells and is listed in `corrections` with its
reason — never silently (owner's decision: correct by the bar, show in red).

Estimate checks compare quantity × price, material + work, and every section
and grand total with the document's own totals. A repeated position number is
reported, not merged: such positions need their name and unit to be told apart.
Design and the next steps: docs/contract_schedule_control.md.
"""
from __future__ import annotations

import bisect
import datetime as dt
import re

# Raise when reading changes: stored documents are then read again from their PDF.
READER_VERSION = 2
MONTHS = {'январь': 1, 'февраль': 2, 'март': 3, 'апрель': 4, 'май': 5, 'июнь': 6, 'июль': 7,
          'август': 8, 'сентябрь': 9, 'октябрь': 10, 'ноябрь': 11, 'декабрь': 12}
_CODE = re.compile(r'^\d+(?:\.\d+)*\.?$')
_DATE = re.compile(r'(\d\d)\.(\d\d)\.(\d{4})')
_GENITIVE = {'января': 1, 'февраля': 2, 'марта': 3, 'апреля': 4, 'мая': 5, 'июня': 6, 'июля': 7,
             'августа': 8, 'сентября': 9, 'октября': 10, 'ноября': 11, 'декабря': 12}
# A date in figures (16.03.2026) or in words («16» марта 2026 г.).
_WHEN = (r'(?:\d\d\.\d\d\.\d{4}|[«"“]?\d{1,2}[»"”]?\s+(?:' + '|'.join(_GENITIVE) + r')\s+\d{4})')
_CONTRACT = re.compile(r'Договор\w*\s+подряда\s+№\s*(.+?)\s+(?:от\s+(' + _WHEN + r')|на\s+выполнение)', re.I)
_AGREEMENT = re.compile(r'Дополнительн\w+\s+соглашени\w+\s+№\s*(\d+)(?:\s+от\s+(' + _WHEN + r'))?', re.I)
# The date line under the title («г. Москва «16» марта 2026 г.») follows it closely.
_DATELINE = 400
_ANNEX = re.compile(r'Приложение\s*№\s*(\d+(?:\.\d+)*)')
_ESTIMATE_TITLE = re.compile(r'Расч[её]т\s+договорной\s+стоимости', re.I)
_SCHEDULE_TITLE = re.compile(r'График\s+производства', re.I)
_SCOPES = (('на выполненные и принятые работы', 'accepted'), ('на завершение работ', 'remaining'))
_ESTIMATE_COLUMNS = 10
_TOTALS = ('итого', 'всего', 'по разделу')
# Electronic-signature stamps of the document operator are printed over the table.
_STAMP = re.compile(r'ДОКУМЕНТ\s+ПОДПИСАН|ОТПРАВЛЕНО|УТВЕРЖДЕНО|Оператор\s+ЭДО|Сертификат|Идентификатор:')
_STAMP_MARGIN = 10.0
_TOLERANCE = 1.0


def _space(text):
    return re.sub(r'\s+', ' ', str(text or '').replace('\xa0', ' ')).strip()


def _date(text):
    text = _space(text)
    match = _DATE.fullmatch(text)
    words = re.fullmatch(r'[«"“]?(\d{1,2})[»"”]?\s+(\w+)\s+(\d{4})', text)
    if words and words[2].lower() in _GENITIVE:
        day, month, year = int(words[1]), _GENITIVE[words[2].lower()], int(words[3])
    elif match:
        day, month, year = int(match[1]), int(match[2]), int(match[3])
    else:
        return None
    try:
        return dt.date(year, month, day).isoformat()
    except ValueError:
        return None


def _shown(iso):
    """An ISO date as people read it in the document: 07.05.2025."""
    return '.'.join(reversed(iso.split('-'))) if iso else '—'


def _amount(text):
    text = re.sub(r'(?:₽|руб\.?)$', '', _space(text).replace(' ', '').replace(',', '.'))
    if not re.fullmatch(r'-?\d+(?:\.\d+)?', text):
        return None
    return float(text)


def _contract_number(text):
    return re.sub(r'\s*[–—-]\s*', '-', _space(text)).strip(' ,.;')


def _dated(text, start):
    """The first date of the date line after `start`: a title without «от» is dated under it."""
    match = re.search(_WHEN, text[start:start+_DATELINE])
    return _date(match[0]) if match else None


def identity(text):
    """Contract and agreement named on the first page; absent parts stay None.

    «Договор подряда № … на выполнение работ …» and «Дополнительное соглашение
    № 1 к Договору …» carry their own date in the date line below the title,
    after the contract they name."""
    text = _space(text)
    agreement = _AGREEMENT.search(text)
    after = agreement.end() if agreement else 0
    contract = _CONTRACT.search(text, after) or _CONTRACT.search(text)
    contract_date = _date(contract[2]) if contract and contract[2] else contract and _dated(text, contract.end())
    agreement_date = None
    if agreement:
        own = agreement[2] and _date(agreement[2])
        agreement_date = own or _dated(text, contract.end() if contract and contract.start() >= after else after)
    return {'contract': {'number': _contract_number(contract[1]), 'date': contract_date} if contract else None,
            'agreement': {'number': agreement[1], 'date': agreement_date} if agreement else None}


def _merge(values, tolerance=0.8):
    out = []
    for value in sorted(values):
        if not out or value - out[-1] > tolerance:
            out.append(value)
    return out


def _rules(page):
    """Horizontal and vertical rules as segments, from lines and thin rectangles."""
    across, down = [], []
    for drawing in page.get_drawings():
        for item in drawing['items']:
            if item[0] == 'l':
                a, b = item[1], item[2]
                if abs(a.y-b.y) < 0.5 and abs(a.x-b.x) > 2:
                    across.append((a.y, min(a.x, b.x), max(a.x, b.x)))
                elif abs(a.x-b.x) < 0.5 and abs(a.y-b.y) > 2:
                    down.append((a.x, min(a.y, b.y), max(a.y, b.y)))
            elif item[0] == 're':
                r = item[1]
                if r.height < 1.5 and r.width > 2:
                    across.append(((r.y0+r.y1)/2, r.x0, r.x1))
                elif r.width < 1.5 and r.height > 2:
                    down.append(((r.x0+r.x1)/2, r.y0, r.y1))
    return across, down


def _words(page):
    """Words of the page without the signature stamps laid over the table.

    A stamp shares blocks, lines and even the area of cells with table text, so
    it is cut out character by character: spans of the colour and font family
    that carry at least two different stamp markers, inside the area those
    markers occupy. The body style of the page is never a stamp, so a marker
    word printed in the text («Сертификат соответствия») erases nothing.
    Each word is (x0, y0, x1, y1, text, block, line, word), as in pymupdf."""
    if getattr(page, '_contract_words', None) is None:
        blocks = [block for block in page.get_text('rawdict')['blocks'] if block.get('type') == 0]
        spans = [span for block in blocks for line in block['lines'] for span in line['spans']]
        family = lambda span: (span['font'].split('-')[0].split(',')[0], span['color'])
        text = lambda span: ''.join(char['c'] for char in span['chars'])
        weight = {}
        for span in spans:
            weight[family(span)] = weight.get(family(span), 0) + len(span['chars'])
        body = max(weight, key=weight.get, default=None)
        kinds = {}
        for span in spans:
            for match in _STAMP.finditer(text(span)):
                kinds.setdefault(family(span), set()).add(match[0].split()[0].lower())
        styles = {style for style, found in kinds.items() if len(found) > 1 and style != body}
        markers = [span for span in spans if family(span) in styles and _STAMP.search(text(span))]
        area = (min(s['bbox'][0] for s in markers)-_STAMP_MARGIN, min(s['bbox'][1] for s in markers)-_STAMP_MARGIN,
                max(s['bbox'][2] for s in markers)+_STAMP_MARGIN, max(s['bbox'][3] for s in markers)+_STAMP_MARGIN) \
            if markers else None
        stamp = lambda span: family(span) in styles and \
            area[0] <= (span['bbox'][0]+span['bbox'][2])/2 <= area[2] and \
            area[1] <= (span['bbox'][1]+span['bbox'][3])/2 <= area[3]
        words = []
        for b, block in enumerate(blocks):
            for l, line in enumerate(block['lines']):
                current, n = [], 0
                chars = [dict(char, size=span['size']) for span in line['spans'] if not stamp(span)
                         for char in span['chars']] + [{'c': ' '}]
                for char in chars:
                    # Text placed separately may share a line without a space between.
                    gap = current and 'bbox' in char and char['bbox'][0]-current[-1]['bbox'][2] > char['size']*0.4
                    if not char['c'].isspace() and not gap:
                        current.append(char)
                        continue
                    if current:
                        box = [char['bbox'] for char in current]
                        words.append((min(x[0] for x in box), min(x[1] for x in box),
                                      max(x[2] for x in box), max(x[3] for x in box),
                                      ''.join(char['c'] for char in current), b, l, n))
                        current, n = [], n+1
                    if not char['c'].isspace():
                        current.append(char)
        page._contract_words = words
    return page._contract_words


def _fills(page):
    out = []
    for drawing in page.get_drawings():
        fill = drawing.get('fill')
        if fill and drawing['rect'].width > 1.5 and drawing['rect'].height > 1.5:
            out.append((tuple(round(c, 2) for c in fill), drawing['rect']))
    return out


class _Grid:
    """Cells of one ruled table on one page; `columns` overrides the page's own rules."""

    def __init__(self, page, columns=None):
        across, down = _rules(page)
        self.verticals = _merge([x for x, y0, y1 in down if y1-y0 > 5])
        self.columns = list(columns or self.verticals)
        self.rows, self.cells = [], []
        if len(self.columns) < 3:
            return
        first = (self.columns[0]+self.columns[1])/2
        # A continuation page may lack the top or bottom border: the left rule
        # of the table still bounds it.
        edge = [(y0, y1) for x, y0, y1 in down if abs(x-self.columns[0]) <= 2 and y1-y0 > 5]
        self.rows = _merge([y for y, x0, x1 in across if x0-0.5 <= first <= x1+0.5]
                           + ([min(y0 for y0, _ in edge), max(y1 for _, y1 in edge)] if edge else []))
        if len(self.rows) < 2:
            return
        cells = {}
        for word in _words(page):
            x, y = (word[0]+word[2])/2, (word[1]+word[3])/2
            row, column = bisect.bisect(self.rows, y)-1, bisect.bisect(self.columns, x)-1
            if 0 <= row < len(self.rows)-1 and 0 <= column < len(self.columns)-1:
                cells.setdefault((row, column), []).append(word)
        for row in range(len(self.rows)-1):
            self.cells.append([' '.join(w[4] for w in sorted(cells.get((row, column), []),
                                                             key=lambda w: (w[5], w[6], w[7])))
                               for column in range(len(self.columns)-1)])

    def band(self, row):
        return self.rows[row], self.rows[row+1]


def _labels(cells):
    """Header of the estimate named in words, without a row of column numbers."""
    low = [_space(cell).lower() for cell in cells]
    return (len(low) == _ESTIMATE_COLUMNS and low[0].startswith('№') and low[1].startswith('наименован')
            and low[2].startswith('ед') and low[3].startswith('кол'))


def _estimate_header(grid):
    """Row of the column numbers 1…10, or else of the column names, and the rules bounding those ten columns.

    A stray rule inside a column (a merged name cell, a margin line) joins the
    numbered column to its left instead of shifting every later column."""
    rows = [(index, [(column, cell.strip()) for column, cell in enumerate(row) if cell.strip()])
            for index, row in enumerate(grid.cells)]
    numbers = [str(n) for n in range(1, _ESTIMATE_COLUMNS+1)]
    named = [(index, filled) for index, filled in rows if [cell for _, cell in filled] == numbers] or \
        [(index, filled) for index, filled in rows if _labels([cell for _, cell in filled])]
    for index, filled in named[:1]:
        numbered = [cell for _, cell in filled] == numbers
        bounds = [grid.columns[column] for column, _ in filled] + [grid.columns[filled[-1][0]+1]]
        if not numbered:
            return index, bounds, True
        above = ' '.join(' '.join(cell for column, cell in enumerate(r) if filled[2][0] <= column < filled[4][0])
                         for r in grid.cells[:index]).lower()
        return index, bounds, 'ед' in above and 'кол' in above
    return None, None, False


def _continues(grid, bounds):
    return all(any(abs(x-bound) <= 2 for x in grid.verticals) for bound in bounds)


def _estimate_rows(cells, page_number, state, warnings):
    for row in cells:
        if len(row) < _ESTIMATE_COLUMNS or not any(c.strip() for c in row):
            continue
        number, name, unit = row[0].strip().rstrip('.'), _space(row[1]), _space(row[2])
        quantity = _amount(row[3])
        price = [_amount(c) for c in row[4:7]]
        money = [_amount(c) for c in row[7:10]]
        label = _space(' '.join(row[:7]))
        # A note under the table may be numbered «1. 2. 3. Примечание: …»; a continuation page repeats the header.
        if re.match(r'(?:\d+\.\s*)*(?:в том числе|примечание|ндс)', label.lower()) or _labels(row):
            continue
        if label.lower().startswith(_TOTALS) or name.lower().startswith(_TOTALS):
            state['totals'].append({'label': label, 'amount': money[2], 'material': money[0],
                                    'work': money[1], 'page': page_number,
                                    'section': state['section'] if 'раздел' in label.lower() else None})
            continue
        if unit and quantity is not None and money[2] is not None:
            if not _CODE.match(number):
                warnings.append(f'Стр. {page_number}: у позиции «{name[:80]}» нет номера.')
            # Under several headings in a row the position belongs to the one its number is numbered under;
            # a title without a number heads the positions that follow it.
            prefixes = [number.rsplit('.', n)[0] for n in range(1, number.count('.')+1)]
            untitled = state['group'] and not state['group']['number']
            group = state['group'] if untitled else next(
                (state['headings'][p] for p in prefixes if p in state['headings']), state['group'])
            state['untitled'] = None
            state['positions'].append({'number': number, 'name': name, 'unit': unit, 'quantity': quantity,
                                       'unit_price': {'material': price[0], 'work': price[1], 'total': price[2]},
                                       'amount': {'material': money[0], 'work': money[1], 'total': money[2]},
                                       'section': state['section'], 'group': group, 'page': page_number})
            continue
        if all(v is None for v in price+money) and (not unit and quantity is None or _CODE.match(number)):
            # A numbered heading may give the volume of its works and leave the cost to them.
            title = _space(' '.join(row[1:7]) if not unit else row[1])
            if title.lower().startswith('раздел'):
                state['section'], state['group'], state['headings'] = title, None, {}
            elif title:
                # A title without a number heads the positions under it, unless numbered groups follow:
                # then it names their section («Корпус 1 …»).
                if _CODE.match(number) and state['untitled']:
                    state['section'], state['headings'] = state['untitled'], {}
                state['untitled'] = None if _CODE.match(number) else title
                state['group'] = {'number': number if _CODE.match(number) else '', 'name': title}
                if state['group']['number']:
                    state['headings'][number] = state['group']
            continue
        warnings.append(f'Стр. {page_number}: строка «{label[:100]}» не распознана как позиция: '
                        'не хватает единицы, количества или стоимости.')


def _check_estimate(estimate):
    warnings, pages = estimate['warnings'], {}
    for position in estimate['positions']:
        pages.setdefault(position['number'], []).append(position['page'])
    for number, seen in pages.items():
        if len(seen) > 1:
            warnings.append(f'Номер позиции {number} повторяется в расчёте {len(seen)} раза '
                            f'(стр. {", ".join(str(n) for n in sorted(set(seen)))}): по одному номеру такие '
                            'позиции не различить, нужны ещё название и единица измерения.')
    for position in estimate['positions']:
        amount, price = position['amount'], position['unit_price']
        if price['total'] is not None:
            expected = position['quantity']*price['total']
            if abs(expected-amount['total']) > max(_TOLERANCE, abs(expected)*0.0005):
                warnings.append(f'Позиция {position["number"]}: количество × цена = {expected:,.2f}, '
                                f'а в графе «Всего» {amount["total"]:,.2f}.'.replace(',', ' '))
        if amount['material'] is not None and amount['work'] is not None and \
                abs(amount['material']+amount['work']-amount['total']) > _TOLERANCE:
            warnings.append(f'Позиция {position["number"]}: материал и работа не дают графу «Всего».')
    for total in estimate['totals']:
        if total['amount'] is not None and (total['section'] or total['label'].lower().startswith('всего')):
            members = [p['amount']['total'] for p in estimate['positions']
                       if not total['section'] or p['section'] == total['section']]
            if abs(sum(members)-total['amount']) > _TOLERANCE*max(1, len(members)):
                warnings.append(f'{total["label"][:80]}: сумма позиций {sum(members):,.2f} не равна итогу '
                                f'{total["amount"]:,.2f}.'.replace(',', ' '))


def _estimate_meta(text):
    text = _space(text)
    annex = _ANNEX.search(text)
    edition = re.search(r'в\s+редакции\s+Дополнительного\s+соглашения\s+№\s*(\d+)\s+от\s+(' + _WHEN + ')', text, re.I)
    scope = next((kind for phrase, kind in _SCOPES if phrase in text.lower()), 'full')
    return {'annex': annex[1] if annex else None, 'scope': scope,
            'edition': {'number': edition[1], 'date': _date(edition[2])} if edition else None}


def _calendar(grid, first, page, bottom):
    """Dates of the day columns: the line of day numbers and the month headers above it.

    Header cells are often merged, so the numbers are read as words on one line,
    one per day column, not as cell texts."""
    columns = grid.columns[first:]
    if len(columns) < 8:
        return None, 'Столбцы дней графика не найдены.'
    digits = sorted((w for w in _words(page) if re.fullmatch(r'\d{1,2}', w[4])
                     and columns[0] <= (w[0]+w[2])/2 <= columns[-1] and (w[1]+w[3])/2 <= bottom),
                    key=lambda w: (w[1]+w[3])/2)
    lines, current = [], []
    for word in digits:
        if current and (word[1]+word[3])/2 - (current[-1][1]+current[-1][3])/2 > 1:
            lines.append(current)
            current = []
        current.append(word)
    if current:
        lines.append(current)
    line = max(lines, key=len, default=[])
    days = {}
    for word in line:
        days.setdefault(bisect.bisect(columns, (word[0]+word[2])/2)-1, []).append(int(word[4]))
    if len(days) != len(columns)-1 or any(len(v) != 1 for v in days.values()):
        return None, 'Строка с числами дней графика не найдена.'
    headers = sorted((x, value) for value, x in _month_words(page, grid.rows[0], bottom))
    segments = []
    for column in range(len(columns)-1):
        day = days[column][0]
        if not segments or day != segments[-1][-1][1]+1:
            segments.append([])
        segments[-1].append((first+column, day))
    if len(segments) != len(headers):
        return None, f'Месяцы графика не совпали с числами дней: месяцев {len(headers)}, отрезков дней {len(segments)}.'
    dates = {}
    for segment, (_, (month, year)) in zip(segments, headers):
        for column, day in segment:
            try:
                dates[column] = (dt.date(year, month, day),)*2
            except ValueError:
                return None, f'В шапке графика нет дня {day:02d}.{month:02d}.{year}.'
    return dates, None


def _month_words(page, top, bottom):
    words = sorted((w for w in _words(page) if top-30 <= (w[1]+w[3])/2 <= bottom),
                   key=lambda w: (w[5], w[6], w[7]))
    for i, word in enumerate(words):
        month = MONTHS.get(word[4].lower())
        if month:
            year = next((int(w[4]) for w in words[i+1:i+3] if re.fullmatch(r'20\d\d', w[4])), None)
            if year:
                yield (month, year), word[0]


def _schedule_page(page, page_number, schedule):
    lines, warnings = schedule['lines'], schedule['warnings']
    grid = _Grid(page)
    header = next((i for i, row in enumerate(grid.cells)
                   if 'наименование' in ' '.join(row[:2]).lower() and 'дата' in ' '.join(row[2:4]).lower()), None)
    if header is None:
        return False
    dates, problem = _calendar(grid, 4, page, grid.rows[header+1])
    if problem:
        warnings.append(f'Стр. {page_number}: {problem} Полосы графика не прочитаны.')
    columns = grid.columns
    fills = _fills(page)
    for index in range(header+1, len(grid.cells)):
        row = grid.cells[index]
        code, name = row[0].strip().rstrip('.'), _space(row[1])
        if not code and not name:
            continue
        if not _CODE.match(code):
            warnings.append(f'Стр. {page_number}: у строки графика «{name[:80]}» нет номера.')
            continue
        start, finish = _date(row[2]), _date(row[3])
        bar = _bar(grid, index, fills, columns, dates, body=grid.rows[header+1])
        line = {'code': code, 'name': name, 'start': start, 'finish': finish, 'dates_from': 'cells',
                'cells': {'start': start, 'finish': finish}, 'corrected': False,
                'bar': {'start': bar[0], 'finish': bar[1]} if bar else None,
                'level': code.count('.')+1, 'parent': code.rsplit('.', 1)[0] if '.' in code else None,
                'page': page_number}
        lines.append(line)
        reversed_dates = bool(start and finish and finish < start)
        if bar and (start is None or finish is None):
            line.update(start=start or bar[0], finish=finish or bar[1], dates_from='bar')
        elif bar and (reversed_dates or _apart(start, bar[0]) or _apart(finish, bar[1])):
            problem = (f'окончание {_shown(finish)} раньше начала {_shown(start)}' if reversed_dates else
                       f'в графах дат {_shown(start)} — {_shown(finish)}, а полоса на диаграмме идёт '
                       f'{_shown(bar[0])} — {_shown(bar[1])}')
            _correct(schedule, line, bar[0], bar[1], 'bar',
                     f'Стр. {page_number}: у строки {code} «{name[:60]}» {problem}. '
                     f'Взяты даты полосы: {_shown(bar[0])} — {_shown(bar[1])}.')
        elif reversed_dates:
            warnings.append(f'Стр. {page_number}: у строки {code} окончание {_shown(finish)} раньше начала '
                            f'{_shown(start)}, а полосы на диаграмме нет: исправить даты нечем.')
    return True


_WEEK = re.compile(r'(?<![\d.])(\d{1,2})\s*-\s*(\d{1,2})(?![\d.])')
_MONTH = re.compile(r'(янв|фев|мар|апр|ма[йя]|июн|июл|авг|сен|окт|ноя|дек)\w*\.?\s*(\d{2})$', re.I)
_SHORT = {'янв': 1, 'фев': 2, 'мар': 3, 'апр': 4, 'май': 5, 'мая': 5, 'июн': 6, 'июл': 7, 'авг': 8, 'сен': 9,
          'окт': 10, 'ноя': 11, 'дек': 12}
WEEKS_ASSUMPTION = ('В графике нет граф с датами, только полосы по неделям: начало работы — первый день первой '
                    'закрашенной недели, окончание — последний день последней. Это допущение, а не даты графика.')


def _weekly_header(grid):
    """Header of a chart by weeks: «№», «Наименование», «Примечание», then a column per week («5-11»).

    Returns the row, the rules bounding those columns (a stray rule inside the
    name column joins it) and the index of the first week column."""
    for index, row in enumerate(grid.cells):
        filled = [(column, _space(cell)) for column, cell in enumerate(row) if _space(cell)]
        if len(filled) < 5 or not filled[0][1].startswith('№') or \
                not filled[1][1].lower().startswith('наименован') or not _WEEK.search(filled[-1][1]):
            continue
        first = next((i for i, (_, cell) in enumerate(filled) if _WEEK.search(cell)), None)
        if first not in (2, 3):
            continue
        bounds = [grid.columns[column] for column, _ in filled] + [grid.columns[filled[-1][0]+1]]
        return index, bounds, first
    return None, None, None


def _weeks(grid, header, first, page):
    """First and last day of each week column, by the month headers over them.

    The days of the weeks start again in each month; a month header stands over
    its own weeks, so months hidden from the chart are not counted."""
    columns = grid.columns
    weeks = []
    for column in range(first, len(columns)-1):
        found = _WEEK.search(grid.cells[header][column])
        if not found:
            return None, f'У столбца графика {column-first+1} нет недели в шапке.'
        weeks.append((column, int(found[1]), int(found[2])))
    top, bottom = grid.band(header)
    months = sorted(((w[0]+w[2])/2, _MONTH.match(w[4])) for w in _words(page)
                    if top-30 <= (w[1]+w[3])/2 <= bottom and columns[first] <= (w[0]+w[2])/2 <= columns[-1]
                    and _MONTH.match(w[4]))
    segments = []
    for week in weeks:
        if not segments or week[1] <= segments[-1][-1][2]:
            segments.append([])
        segments[-1].append(week)
    if len(segments) != len(months):
        return None, f'Месяцы графика не совпали с неделями: месяцев {len(months)}, отрезков недель {len(segments)}.'
    dates = {}
    for segment, (x, month) in zip(segments, months):
        if not columns[segment[0][0]] - 2 <= x <= columns[segment[-1][0]+1] + 2:
            return None, f'Месяц «{month[0]}» в шапке графика стоит не над своими неделями.'
        number, year = _SHORT[month[1].lower()], 2000+int(month[2])
        for column, start, finish in segment:
            try:
                dates[column] = (dt.date(year, number, start), dt.date(year, number, finish))
            except ValueError:
                return None, f'В шапке графика нет недели {start}-{finish} в месяце {number:02d}.{year}.'
    return dates, None


def _weekly_page(page, page_number, schedule, layout=None):
    """A chart by weeks without date cells, its first page or (with `layout`) a page continuing it.

    A line takes the dates of its bars (WEEKS_ASSUMPTION). A numbered line with
    a bar is a work even when deeper lines are numbered under it (4.1 and
    4.1.1 are two works of the estimate); its heading is the nearest line above
    it by the numbering that has no bar. A line without a number is the title
    of the following lines («Корпус 1 этаж 1-9»), or a total that is skipped."""
    lines, warnings = schedule['lines'], schedule['warnings']
    if layout is None:
        grid = _Grid(page)
        header, bounds, first = _weekly_header(grid)
        if header is None:
            return None
        grid = _Grid(page, bounds)
        dates, problem = _weeks(grid, header, first, page)
        if problem:
            warnings.append(f'Стр. {page_number}: {problem} Полосы графика не прочитаны.')
        layout = {'bounds': bounds, 'first': first, 'dates': dates}
        rows = range(header+1, len(grid.cells))
    else:
        grid = _Grid(page, layout['bounds'])
        rows = range(len(grid.cells))
    body = grid.rows[rows.start] if rows else 0.0
    schedule['assumption'] = WEEKS_ASSUMPTION
    first, fills = layout['first'], _fills(page)
    by_code = {line['code']: line for line in lines}
    for index in rows:
        row = grid.cells[index]
        code, name = re.sub(r'\s+', '', row[0]).rstrip('.'), _space(row[1])
        if not code and not name:
            continue
        if not code:
            # A total closes its building: lines after it are not of that building until the next title.
            schedule['section'] = None if name.lower().startswith(_TOTALS) else name
            continue
        if not _CODE.match(code):
            warnings.append(f'Стр. {page_number}: у строки графика «{name[:80]}» нет номера.')
            continue
        bar = _bar(grid, index, fills, grid.columns, layout['dates'], first, body)
        parent, prefix = None, code
        while '.' in prefix:
            prefix = prefix.rsplit('.', 1)[0]
            parent = parent or prefix
            if prefix in by_code and not by_code[prefix]['bar']:
                parent = prefix
                break
        line = {'code': code, 'name': name, 'start': bar and bar[0], 'finish': bar and bar[1],
                'dates_from': 'bar', 'cells': {'start': None, 'finish': None}, 'corrected': False,
                'bar': {'start': bar[0], 'finish': bar[1]} if bar else None,
                'level': code.count('.')+1, 'parent': parent, 'section': schedule.get('section'),
                'page': page_number}
        lines.append(line)
        by_code.setdefault(code, line)
    return layout


def _apart(cell, bar):
    return abs((dt.date.fromisoformat(cell)-dt.date.fromisoformat(bar)).days) > 1


def _correct(schedule, line, start, finish, basis, text):
    """Dates of the source replaced by the chart bar or by the works' span.

    The owner chose correction over a bare warning; the original cells stay on
    the line and the correction is listed apart, to be shown in red."""
    line.update(start=start, finish=finish, dates_from=basis, corrected=True)
    record = next((item for item in schedule['corrections'] if item['code'] == line['code']), None)
    if record is None:
        schedule['corrections'].append({'code': line['code'], 'name': line['name'], 'page': line['page'],
                                        'cells': dict(line['cells']), 'used': {'start': start, 'finish': finish},
                                        'basis': basis, 'text': text})
    else:
        record.update(used={'start': start, 'finish': finish}, basis=basis, text=record['text']+' '+text)


def _bar(grid, row, fills, columns, dates, first=4, body=0.0):
    """Start and finish of the chart bars in `row`: `dates` give each chart column its first and last day.

    Several bars of one line (stages of one work) give one span, from the first to the last. `body` is
    the top of the table under its header: a fill of the header is never a bar."""
    if not dates:
        return None
    top, bottom = grid.band(row)
    left, right = columns[first], columns[-1]
    # A bar of merged cells is one fill over several rows: it is the bar of each row it covers.
    inside = [(colour, rect) for colour, rect in fills
              if (rect.y0 >= top-0.5 and rect.y1 <= bottom+0.5 or rect.y0 <= top+0.5 and rect.y1 >= bottom-0.5)
              and rect.y0 >= body-0.5 and rect.x1 > left+0.5]
    name = (columns[1]+columns[2])/2
    background = {colour for colour, rect in inside if rect.x0 <= name <= rect.x1}
    marks = [rect for colour, rect in inside
             if colour not in background and min(colour) < 0.97 and rect.x0 >= left-0.5 and rect.x1 <= right+0.5]
    if not marks:
        return None
    x0, x1 = min(r.x0 for r in marks), max(r.x1 for r in marks)
    covered = [days for column, days in dates.items() if x0 <= (columns[column]+columns[column+1])/2 <= x1]
    return (min(d[0] for d in covered).isoformat(), max(d[1] for d in covered).isoformat()) if covered else None


def _check_schedule(schedule):
    lines, warnings = schedule['lines'], schedule['warnings']
    seen = {}
    for line in lines:
        if line['code'] in seen:
            warnings.append(f'Номер строки графика {line["code"]} повторяется (стр. {seen[line["code"]]["page"]} '
                            f'и {line["page"]}).')
        seen.setdefault(line['code'], line)
    # Deepest lines first, so a heading without dates spans its works' spans.
    for line in sorted(lines, key=lambda item: -item['level']):
        children = [c for c in lines if c['parent'] == line['code'] and c['start'] and c['finish']]
        if not children:
            if not (line['start'] and line['finish']):
                warnings.append(f'Стр. {line["page"]}: у строки {line["code"]} «{line["name"][:80]}» '
                                'нет дат начала и окончания.')
            continue
        start, finish = min(c['start'] for c in children), max(c['finish'] for c in children)
        if not line['start'] and not line['finish']:
            line.update(start=start, finish=finish, dates_from='works')
        elif (start, finish) != (line['start'], line['finish']):
            _correct(schedule, line, start, finish, 'works',
                     f'Строка {line["code"]} «{line["name"][:60]}»: в графике {_shown(line["start"])} — '
                     f'{_shown(line["finish"])}, а входящие в неё работы идут {_shown(start)} — '
                     f'{_shown(finish)}. Взяты сроки работ.')


def read(data: bytes) -> dict:
    """Read a contract or agreement PDF. Unreadable documents raise ValueError."""
    import pymupdf
    try:
        document = pymupdf.open(stream=data, filetype='pdf')
    except (RuntimeError, ValueError) as error:
        raise ValueError('Файл не открылся как PDF.') from error
    texts = [page.get_text() for page in document]
    if not any(_space(text) for text in texts):
        raise ValueError('В PDF нет текстового слоя: это скан. Графы расчёта и графика по скану не прочитать '
                         'надёжно; нужен PDF с текстом, например выгрузка из системы электронного документооборота.')
    out = dict(identity(texts[0]), estimates=[], schedule=None, warnings=[], pages=len(texts))
    estimate, layout, weekly, mentioned = None, None, None, set()
    for index, page in enumerate(document):
        number, text = index+1, texts[index]
        if weekly is not None and not _SCHEDULE_TITLE.search(text) and _continues(_Grid(page), weekly['bounds']):
            _weekly_page(page, number, out['schedule'], weekly)
            out['schedule']['pages'].append(number)
            continue
        weekly = None
        if _SCHEDULE_TITLE.search(text):
            schedule = out['schedule'] or {'pages': [], 'lines': [], 'warnings': [], 'corrections': []}
            if _schedule_page(page, number, schedule):
                estimate, out['schedule'] = None, schedule
                schedule['pages'].append(number)
                continue
            weekly = _weekly_page(page, number, schedule)
            if weekly is not None:
                estimate, out['schedule'] = None, schedule
                schedule['pages'].append(number)
                continue
            mentioned.add('schedule')
        if _ESTIMATE_TITLE.search(text):
            grid = _Grid(page)
            header, bounds, labelled = _estimate_header(grid)
            if header is None or not labelled:
                # A page of the contract text names the annex; only a ruled table is a broken estimate.
                if len(grid.columns) > _ESTIMATE_COLUMNS:
                    out['warnings'].append(f'Стр. {number}: в расчёте договорной стоимости не распознаны графы '
                                           '(номер, наименование, единица, количество, цены, стоимость).')
                mentioned.add('estimate')
                estimate = None
                continue
            estimate = dict(_estimate_meta(text), pages=[number], positions=[], totals=[], warnings=[],
                            section=None, group=None, headings={}, untitled=None)
            out['estimates'].append(estimate)
            layout = bounds
            _estimate_rows(_Grid(page, bounds).cells[header+1:], number, estimate, estimate['warnings'])
            continue
        if estimate is not None:
            grid = _Grid(page)
            if _continues(grid, layout):
                estimate['pages'].append(number)
                _estimate_rows(_Grid(page, layout).cells, number, estimate, estimate['warnings'])
                continue
            estimate = None
    for item in out['estimates']:
        item.pop('section'), item.pop('group'), item.pop('headings'), item.pop('untitled')
        _check_estimate(item)
        if not item['positions']:
            item['warnings'].append('В расчёте не найдено ни одной позиции с единицей, количеством и стоимостью.')
    if out['schedule']:
        out['schedule'].pop('section', None)
        _check_schedule(out['schedule'])
        if not out['schedule']['lines']:
            out['schedule']['warnings'].append('В графике не найдено ни одной строки работ.')
    if 'estimate' in mentioned and not out['estimates']:
        out['warnings'].append('Расчёт договорной стоимости упомянут, но его таблица не найдена.')
    if 'schedule' in mentioned and not out['schedule']:
        out['warnings'].append('График производства работ упомянут, но его таблица не найдена.')
    if not out['estimates'] and not out['schedule'] and not mentioned:
        out['warnings'].append('В документе нет таблиц расчёта договорной стоимости и графика производства работ: '
                               'он их не меняет, или таблицы не распознаны.')
    return out
