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
A number printed on several schedule lines gives the later lines their own code
(«14.1, повтор»); the printed number is kept and the lines are listed in `repeats`.

Estimate checks compare quantity × price, material + work, and every section
and grand total with the document's own totals; a total that cannot be checked
(unread sum, a subsection, no section) carries its reason, and so does an
estimate without a grand total. A printed figure or date the reader cannot take
is named with its printed text, never dropped. A repeated position number is
reported, not merged: such positions need their name and unit to be told apart.
An act of acceptance КС-2 brings no table of the plan: its header gives the
act's number, date, reporting period and the contract, read by position under
the printed labels of the unified form, and its last page the total by act.
The agreement the act names is a reference, not an edition of the contract.
Design and the next steps: docs/contract_schedule_control.md.
"""
from __future__ import annotations

import bisect
import datetime as dt
import re
from math import fsum

# Raise when reading changes: stored documents are then read again from their PDF.
READER_VERSION = 9
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
# Columns 5…9 of the estimate, named in the warning when the cell is printed but is no number.
# A ГПР with money (a cost column, sums printed by months) gives the plan its dates only.
_MONEY_HEAD = re.compile(r'руб|стоимост|сумм', re.I)
# A sum, not a day, a week «2-14», a date or a year: thousands by spaces, four figures and more, or kopecks.
_MONEY = re.compile(r'(?<![\d.,-])(?:\d{1,3}(?:[ \u00a0]\d{3})+|(?!(?:19|20)\d\d(?![\d,]))\d{4,})(?:,\d{1,2})?(?![\d.,-])|(?<![\d.])\d+,\d{2}(?!\d)')
_UNREAD = ('цена материала', 'цена работы', 'цена', 'стоимость материала', 'стоимость работы')
# Electronic-signature stamps of the document operator are printed over the table.
_STAMP = re.compile(r'ДОКУМЕНТ\s+ПОДПИСАН|ОТПРАВЛЕНО|УТВЕРЖДЕНО|Оператор\s+ЭДО|Сертификат|Идентификатор:')
_STAMP_MARGIN = 10.0
_TOLERANCE = 1.0
# The form's title in capitals and its header labels: a contract only mentions such acts in its text.
_ACT_FORM = (re.compile(r'АКТ\s+О\s+ПРИ[ЕЁ]МКЕ\s+ВЫПОЛНЕННЫХ\s+РАБОТ'), re.compile(r'Отч[её]тный\s+период', re.I),
             re.compile(r'Дата\s+составления', re.I))
# The values of the form's header stand on the first line under their labels, each in its label's column;
# a label printed in two lines («№» over «документа») leaves a wider gap.
_ACT_ROW = 14.0
_ACT_BELOW = 30.0
_ACT_COLUMN = 25.0


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


def _figure(value):
    """A sum as the document prints it: 58 150,00."""
    return f'{value:,.2f}'.replace(',', ' ').replace('.', ',')


def _times(count):
    return f'{count} раза' if count % 10 in (2, 3, 4) and count % 100 not in (12, 13, 14) else f'{count} раз'


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


def _total_kind(label):
    low = label.lower()
    return 'subsection' if 'подраздел' in low else 'section' if 'раздел' in low else 'overall'


def _estimate_rows(cells, page_number, state, warnings):
    numbers = [str(n) for n in range(1, _ESTIMATE_COLUMNS+1)]
    for row in cells:
        if len(row) < _ESTIMATE_COLUMNS or not any(c.strip() for c in row):
            continue
        number, name, unit = row[0].strip().rstrip('.'), _space(row[1]), _space(row[2])
        quantity = _amount(row[3])
        price = [_amount(c) for c in row[4:7]]
        money = [_amount(c) for c in row[7:10]]
        label = _space(' '.join(row[:7]))
        # A note under the table may be numbered «1. 2. 3. Примечание: …»; a continuation page repeats the header,
        # in words or as the row of column numbers.
        if re.match(r'(?:\d+\.\s*)*(?:в том числе|примечание|ндс)', label.lower()) or _labels(row) or \
                [_space(c) for c in row[:_ESTIMATE_COLUMNS]] == numbers:
            continue
        if label.lower().startswith(_TOTALS) or name.lower().startswith(_TOTALS):
            kind = _total_kind(label)
            state['totals'].append({'label': label, 'amount': money[2], 'material': money[0],
                                    'work': money[1], 'page': page_number, 'kind': kind,
                                    'section': state['section'] if kind == 'section' else None,
                                    'printed': _space(row[9])})
            continue
        if unit and quantity is not None and money[2] is not None:
            if not _CODE.match(number):
                warnings.append(f'Стр. {page_number}: у позиции «{name[:80]}» нет номера.')
            unread = [f'{column} «{_space(text)}»' for column, text, value in zip(_UNREAD, row[4:9], price+money)
                      if _space(text) and value is None]
            if unread:
                warnings.append(f'Стр. {page_number}: у позиции {number} не прочитано: {", ".join(unread)}. '
                                'Сверка по этим графам не выполнена.')
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
            warnings.append(f'Номер позиции {number} повторяется в расчёте {_times(len(seen))} '
                            f'(стр. {", ".join(str(n) for n in sorted(set(seen)))}): по одному номеру такие '
                            'позиции не различить, нужны ещё название и единица измерения.')
    for position in estimate['positions']:
        amount, price = position['amount'], position['unit_price']
        if price['total'] is not None:
            expected = position['quantity']*price['total']
            if abs(expected-amount['total']) > max(_TOLERANCE, abs(expected)*0.0005):
                warnings.append(f'Позиция {position["number"]}: количество × цена = {_figure(expected)}, '
                                f'а в графе «Всего» {_figure(amount["total"])}.')
        if amount['material'] is not None and amount['work'] is not None and \
                abs(amount['material']+amount['work']-amount['total']) > _TOLERANCE:
            warnings.append(f'Позиция {position["number"]}: материал и работа не дают графу «Всего».')
    _check_totals(estimate)


def _check_totals(estimate):
    """Each total is compared with the sum of its positions, or carries `reason` why it was not.

    A document may print several overall totals (without and with VAT): one that
    equals the sum of all positions settles the others, which are then only marked."""
    warnings, positions = estimate['warnings'], estimate['positions']
    everything = sum(p['amount']['total'] for p in positions)
    mismatches = []
    for total in estimate['totals']:
        printed = total.pop('printed', '')
        total.update(checked=False, reason=None)
        if total['amount'] is None:
            total['reason'] = (f'сумма итога «{printed}» не прочитана' if printed else
                               'в графе «Всего» у итога нет суммы')
        elif total['kind'] == 'subsection':
            total['reason'] = 'позиции подраздела в расчёте не выделены, итог подраздела со всем разделом не сверяется'
        elif total['kind'] == 'section' and not total['section']:
            total['reason'] = 'над итогом не найдено название раздела'
        else:
            members = [p['amount']['total'] for p in positions
                       if total['kind'] == 'overall' or p['section'] == total['section']]
            total['checked'] = abs(sum(members)-total['amount']) <= _TOLERANCE*max(1, len(members))
            if not total['checked']:
                mismatches.append((total, sum(members)))
        if total['reason']:
            warnings.append(f'{total["label"][:80]}: не сверено — {total["reason"]}.')
    overall = [t for t in estimate['totals'] if t['kind'] == 'overall']
    settled = any(t['checked'] for t in overall)
    for total, members in mismatches:
        if total['kind'] == 'overall' and settled:
            total['reason'] = 'с суммой позиций совпал другой общий итог документа, этот итог посчитан на иной основе'
            continue
        total['reason'] = f'сумма позиций {_figure(members)} не равна итогу {_figure(total["amount"])}'
        warnings.append(f'{total["label"][:80]}: {total["reason"]}.')
    if positions and not overall:
        warnings.append(f'В расчёте не найден общий итог («Всего» или «Итого» по расчёту): сумма позиций '
                        f'{_figure(everything)} не сверена с документом.')


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


def _sums(grid, header, rows, first, page_number, warnings):
    """Say that money printed in the ГПР is not read, rather than drop it: the plan stays even by days."""
    heads = [_space(cell) for cell in (grid.cells[header] if header is not None else []) if _MONEY_HEAD.search(cell)]
    codes = [_space(grid.cells[index][0]).rstrip('.') or 'без номера' for index in rows
             if any(_MONEY.search(cell) for cell in grid.cells[index][first:])]
    if not heads and not codes:
        return
    found = []
    if heads:
        found.append(f'в шапке графика есть графа «{heads[0][:60]}»')
    if codes:
        found.append('на диаграмме напечатаны суммы у строк ' + ', '.join(codes[:5]) + (' и других' if len(codes) > 5 else ''))
    warnings.append(f'Стр. {page_number}: {" и ".join(found)}. Помесячные суммы графика не прочитаны: план '
                    'разложен по дням строк равномерно.')


def _schedule_page(page, page_number, schedule):
    lines, warnings = schedule['lines'], schedule['warnings']
    grid = _Grid(page)
    header = next((i for i, row in enumerate(grid.cells)
                   if 'наименование' in ' '.join(row[:2]).lower() and 'дата' in ' '.join(row[2:4]).lower()), None)
    if header is None:
        return False
    if len(grid.cells[header]) < 4:
        warnings.append(f'Стр. {page_number}: в таблице графика не хватает граф начала и окончания. '
                        'Сроки работ не прочитаны: нужен график с обеими графами дат.')
        return True
    dates, problem = _calendar(grid, 4, page, grid.rows[header+1])
    if problem:
        warnings.append(f'Стр. {page_number}: {problem} Полосы графика не прочитаны.')
    columns = grid.columns
    fills = _fills(page)
    _sums(grid, header, range(header+1, len(grid.cells)), 4, page_number, warnings)
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
        line = {'code': code, 'name': name, 'start': start, 'finish': finish,
                'dates_from': {'start': 'cells', 'finish': 'cells'},
                'cells': {'start': start, 'finish': finish}, 'corrected': False,
                'bar': {'start': bar[0], 'finish': bar[1]} if bar else None,
                'level': code.count('.')+1, 'parent': code.rsplit('.', 1)[0] if '.' in code else None,
                'page': page_number}
        # A printed date the reader cannot take (a year of two figures) is kept as printed, never dropped.
        unread = {key: _space(text) for key, text, value in (('start', row[2], start), ('finish', row[3], finish))
                  if _space(text) and value is None}
        if unread:
            line['unread'] = unread
        lines.append(line)
        reversed_dates = bool(start and finish and finish < start)
        if bar and (reversed_dates or (start and _apart(start, bar[0]))
                    or (finish and _apart(finish, bar[1]))
                    or (finish or bar[1]) < (start or bar[0])):
            said = (f'в графах дат {_shown(start)} — {_shown(finish)}' if start and finish else
                    _cells(line['cells'], unread))
            problem = (f'окончание {_shown(finish)} раньше начала {_shown(start)}' if reversed_dates else
                       (f'{said}, а ' if said else '') + f'полоса на диаграмме идёт {_shown(bar[0])} — {_shown(bar[1])}')
            if unread:
                problem = _unread(unread) + '; ' + problem
            _correct(schedule, line, bar[0], bar[1], 'bar',
                     f'Стр. {page_number}: у строки {code} «{name[:60]}» {problem}. '
                     f'Взяты даты полосы: {_shown(bar[0])} — {_shown(bar[1])}.')
        elif bar and (start is None or finish is None):
            used = {'start': start or bar[0], 'finish': finish or bar[1]}
            basis = {key: 'cells' if line['cells'][key] else 'bar' for key in used}
            if unread:
                _correct(schedule, line, used['start'], used['finish'], basis,
                         f'Стр. {page_number}: у строки {code} «{name[:60]}» {_unread(unread)}. '
                         + ('Взята дата полосы: ' if len(unread) == 1 else 'Взяты даты полосы: ')
                         + ' — '.join(_shown(used[key]) for key in unread) + '.')
            else:
                line.update(used, dates_from=basis)
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

_CHART_DATE = re.compile(r'(?<!\d)(\d{1,2}\.\d{2}\.(?:\d{4}|\d{2}))(?!\d)')
CHART_DATES_ASSUMPTION = (
    'Отдельных граф начала и окончания нет. Границы полос прочитаны по первой и последней '
    'подписанной дате закрашенных столбцов. Точность — до отметок диаграммы; '
    'это оценка по графику, а не отдельно указанные даты начала и окончания работ.')


def _dated_bar_page(page, page_number, schedule):
    """A chart with number/name/unit/volume and dated columns, including rotated labels.

    Rebuild the column bounds from the labelled header: a stray rule through
    the name and the signature's right border are not extra data columns.
    Dates are source labels (point bounds), never invented ten-day periods.
    """
    grid = _Grid(page)
    for header, row in enumerate(grid.cells):
        filled = [(i, _space(cell)) for i, cell in enumerate(row) if _space(cell)]
        if (len(filled) < 5 or not filled[0][1].startswith('№')
                or not filled[1][1].lower().startswith('наименован')
                or not filled[2][1].lower().startswith('ед')
                or not filled[3][1].lower().replace('ё', 'е').startswith(('объем', 'кол'))):
            continue
        if not any(_CHART_DATE.search(cell) for _, cell in filled[4:]):
            continue
        # Keep every physical calendar column, including one without a label.
        # Only the four metadata columns may merge stray rules through their text.
        # The table's horizontal border excludes a separate signature border.
        across, _ = _rules(page)
        first_calendar = filled[3][0]+1
        top, bottom = grid.band(header)
        segments = sorted((x0, x1) for y, x0, x1 in across
                          if abs(y-top) <= 1 or abs(y-bottom) <= 1)
        right = grid.columns[0]
        for x0, x1 in segments:
            if x0 <= right+1:
                right = max(right, x1)
        if right <= grid.columns[first_calendar]:
            # With no usable border keep the physical grid; an unread label
            # then makes dates unknown rather than removing calendar columns.
            right = grid.columns[-1]
        calendar = [i for i in range(first_calendar, len(grid.columns)-1)
                    if grid.columns[i] < right-1]
        bounds = [grid.columns[i] for i, _ in filled[:4]] + [grid.columns[first_calendar]] + [
            grid.columns[i+1] for i in calendar]
        marks = [_CHART_DATE.findall(_space(row[i])) for i in calendar]
        dates, problem = {}, None
        previous = None
        for column, found in enumerate(marks, 4):
            if len(found) != 1:
                problem = 'В шапке графика не прочитана дата календарного столбца.'
                break
            try:
                text = found[0]
                day = dt.datetime.strptime(text, '%d.%m.%Y' if len(text.rsplit('.', 1)[1]) == 4
                                            else '%d.%m.%y').date()
            except ValueError:
                problem = 'В шапке графика есть недопустимая календарная дата.'
                break
            if previous is not None and day <= previous:
                problem = 'Подписанные даты графика не возрастают слева направо.'
                break
            dates[column] = (day, day)
            previous = day
        if problem:
            schedule['warnings'].append(f'Стр. {page_number}: {problem} Сроки полос не прочитаны.')
        schedule['warnings'].append(CHART_DATES_ASSUMPTION)
        layout = {'bounds': bounds, 'first': 4, 'dates': None if problem else dates,
                  'page': page_number, 'body_row': header+1,
                  'assumption': CHART_DATES_ASSUMPTION, 'date_precision': 'chart_marks'}
        return _weekly_page(page, page_number, schedule, layout)
    return None


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
        rows = range(layout.get('body_row', 0) if layout.get('page') == page_number else 0, len(grid.cells))
    body = grid.rows[rows.start] if rows else 0.0
    schedule['assumption'] = layout.get('assumption') or WEEKS_ASSUMPTION
    first, fills = layout['first'], _fills(page)
    _sums(grid, rows.start - 1 if rows.start else None, rows, first, page_number, warnings)
    by_code = {line['code']: line for line in lines}
    for index in rows:
        row = grid.cells[index]
        if all(_space(cell) == str(i+1) for i, cell in enumerate(row)):
            continue  # Printed column numbers are not a work with code1 and name2.
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
                'dates_from': {'start': 'bar', 'finish': 'bar'}, 'cells': {'start': None, 'finish': None},
                'corrected': False,
                'bar': {'start': bar[0], 'finish': bar[1]} if bar else None,
                'level': code.count('.')+1, 'parent': parent, 'section': schedule.get('section'),
                'page': page_number}
        if layout.get('date_precision'):
            line['date_precision'] = layout['date_precision']
        lines.append(line)
        by_code.setdefault(code, line)
    return layout


def _apart(cell, bar):
    return abs((dt.date.fromisoformat(cell)-dt.date.fromisoformat(bar)).days) > 1


def _cells(cells, unread):
    """What the date cells of a line hold; an unread date is named by _unread, an empty cell as empty."""
    named = {'start': 'начала', 'finish': 'окончания'}
    said = [f'в графе {named[key]} {_shown(cells[key])}' if cells[key] else f'в графе {named[key]} даты нет'
            for key in ('start', 'finish') if key not in unread]
    return ', '.join(said)


def _unread(unread):
    """The printed dates the reader could not take, named with their text."""
    named = {'start': 'начала', 'finish': 'окончания'}
    if len(unread) == 1:
        ((key, text),) = unread.items()
        return f'дата {named[key]} «{text}» не прочитана: нужна запись вида 01.02.2026'
    return (f'даты начала «{unread["start"]}» и окончания «{unread["finish"]}» не прочитаны: '
            'нужна запись вида 01.02.2026')


def _correct(schedule, line, start, finish, basis, text):
    """Dates of the source replaced by the chart bar or by the works' span.

    The owner chose correction over a bare warning; the original cells stay on
    the line and the correction is listed apart, to be shown in red. `basis` is
    'bar' or 'works', or a mapping of each date to where it came from."""
    dates_from = basis if isinstance(basis, dict) else {'start': basis, 'finish': basis}
    line.update(start=start, finish=finish, dates_from=dates_from, corrected=True)
    replaced = next(value for value in dates_from.values() if value != 'cells')
    record = next((item for item in schedule['corrections'] if item['code'] == line['code']), None)
    if record is None:
        schedule['corrections'].append({'code': line['code'], 'name': line['name'], 'page': line['page'],
                                        'cells': dict(line['cells']), 'used': {'start': start, 'finish': finish},
                                        'basis': replaced, 'text': text, **({'unread': line['unread']}
                                                                            if line.get('unread') else {})})
    else:
        record.update(used={'start': start, 'finish': finish}, basis=replaced, text=record['text']+' '+text)


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
             if colour not in background and min(colour) < 0.97 and rect.x0 >= left-1.0 and rect.x1 <= right+1.0]
    if not marks:
        return None
    x0, x1 = min(r.x0 for r in marks), max(r.x1 for r in marks)
    covered = [days for column, days in dates.items() if x0 <= (columns[column]+columns[column+1])/2 <= x1]
    return (min(d[0] for d in covered).isoformat(), max(d[1] for d in covered).isoformat()) if covered else None


def _repeat_code(number, count):
    return f'{number}, повтор' + (f' {count-1}' if count > 2 else '')


def _separate_repeats(schedule):
    """A number printed on several lines: the later lines get their own code, the number stays in `printed`.

    A line belongs to the nearest heading above it with its parent's number, so the
    works under a repeated heading stay under that heading. Which line a position of
    the estimate means is the owner's choice (decision А), never the first one found.
    """
    count, last, repeats = {}, {}, {}
    for line in schedule['lines']:
        number = line['code']
        count[number] = count.get(number, 0) + 1
        if count[number] > 1:
            line.update(code=_repeat_code(number, count[number]), printed=number)
            repeats.setdefault(number, [last[number]]).append(line)
        if line.get('parent') in last:
            line['parent'] = last[line['parent']]['code']
        last[number] = line
    schedule['repeats'] = [{'number': number, 'lines': [{'code': x['code'], 'name': x['name'], 'page': x.get('page')}
                                                        for x in found]}
                           for number, found in repeats.items()]
    for repeat in schedule['repeats']:
        shown = ' и '.join(f'«{x["code"]}» (стр. {x["page"]})' for x in repeat['lines'])
        schedule['warnings'].append(f'Номер строки графика {repeat["number"]} повторяется: строки показаны как '
                                    f'{shown}. Позиции расчёта с этим номером свяжите со строкой вручную, а '
                                    'подрядчика попросите исправить нумерацию графика.')


def _check_schedule(schedule):
    lines = schedule['lines']
    _separate_repeats(schedule)
    warnings = schedule['warnings']
    # Deepest lines first, so a heading without dates spans its works' spans.
    for line in sorted(lines, key=lambda item: -item['level']):
        children = [c for c in lines if c['parent'] == line['code'] and c['start'] and c['finish']]
        if not children:
            if line.get('unread') and not (line['start'] and line['finish']):
                warnings.append(f'Стр. {line["page"]}: у строки {line["code"]} «{line["name"][:60]}» '
                                f'{_unread(line["unread"])}, а полосы на диаграмме нет: срок взять неоткуда.')
            elif not (line['start'] and line['finish']):
                warnings.append(f'Стр. {line["page"]}: у строки {line["code"]} «{line["name"][:80]}» '
                                'нет дат начала и окончания.')
            continue
        start, finish = min(c['start'] for c in children), max(c['finish'] for c in children)
        if not line['start'] and not line['finish'] and line.get('unread'):
            _correct(schedule, line, start, finish, 'works',
                     f'Строка {line["code"]} «{line["name"][:60]}»: {_unread(line["unread"])}. '
                     f'Взяты сроки входящих в неё работ: {_shown(start)} — {_shown(finish)}.')
        elif not line['start'] and not line['finish']:
            line.update(start=start, finish=finish, dates_from={'start': 'works', 'finish': 'works'})
        elif (start, finish) != (line['start'], line['finish']):
            _correct(schedule, line, start, finish, 'works',
                     f'Строка {line["code"]} «{line["name"][:60]}»: в графике {_shown(line["start"])} — '
                     f'{_shown(line["finish"])}, а входящие в неё работы идут {_shown(start)} — '
                     f'{_shown(finish)}. Взяты сроки работ.')


def _act_words(page):
    """Words of the page once: a PDF printed twice over itself carries every word twice."""
    seen, out = set(), []
    for word in _words(page):
        key = (round(word[0]), round(word[1]), word[4])
        if key not in seen:
            seen.add(key)
            out.append(word)
    return out


def _middle(word):
    return (word[0]+word[2])/2


def _right_of(words, label, test=lambda text: True):
    """The first word to the right of `label` on its line that passes `test`."""
    found = sorted((w for w in words if w[0] > label[2] and abs(w[1]-label[1]) < 3 and test(w[4])),
                   key=lambda w: w[0])
    return found[0] if found else None


def _below(words, label, test):
    """The word under `label` on the nearest line below, nearest to its middle, that passes `test`."""
    found = [w for w in words if label[3]-2 < w[1] < label[3]+_ACT_BELOW
             and abs(_middle(w)-_middle(label)) < _ACT_COLUMN and test(w[4])]
    return min(found, key=lambda w: (round(w[1]), abs(_middle(w)-_middle(label))), default=None)


def _act_total(words):
    """The amount right of «Итого по акту» on its line: the rightmost run of figures."""
    for word in words:
        if word[4].lower().rstrip(':') != 'акту':
            continue
        line = sorted((w for w in words if abs(w[1]-word[1]) < 3), key=lambda w: w[0])
        before = [w[4].lower() for w in line if w[2] <= word[0]]
        if before[-2:] != ['итого', 'по']:
            continue
        runs = []
        for w in (w for w in line if w[0] > word[2]):
            if runs and w[0]-runs[-1][-1][2] < 4:
                runs[-1].append(w)
            else:
                runs.append([w])
        for run in reversed(runs):
            value = _amount(''.join(w[4] for w in run))
            if value is not None:
                return value
    return None


def _act_layout(cells):
    """Columns of the act's table from its row of labels: (row index, columns) or (None, None).

    The form prints «по порядку», «позиции по смете», the name, «Единица измерения»,
    one quantity or two («(материал)», «(СМР)») and then the money: a price and a cost,
    a price of materials and of work and one cost, or both price and cost so split."""
    for index, row in enumerate(cells):
        low = [_space(cell).lower() for cell in row]
        order = next((n for n, cell in enumerate(low) if cell.startswith('по поряд')), None)
        place = next((n for n, cell in enumerate(low) if cell.startswith('позиции по смете')), None)
        unit = next((n for n, cell in enumerate(low) if cell.startswith(('единица', 'ед.'))), None)
        counts = [n for n, cell in enumerate(low) if cell.startswith(('количество', 'кол-во', 'кол.'))]
        if None in (order, place, unit) or not counts or not order < place < unit < counts[0]:
            continue
        money = [n for n in range(counts[-1]+1, len(low)) if low[n]]
        work = next((n for n in counts if 'смр' in low[n]), None)
        material = next((n for n in counts if 'материал' in low[n]), None)
        if len(counts) == 1:
            work, material = counts[0], None
        if work is None or len(money) not in (2, 3, 4):
            return index, None
        return index, {'order': order, 'number': place, 'name': list(range(place+1, unit)), 'unit': unit,
                       'work': work, 'material': material, 'money': money}
    return None, None


_SECTION_TOTAL = re.compile(r'(?:итого|всего)\s+по\s+(?:под)?(?:раздел|глав)')


def _settle_heading(act, state, number=''):
    """A row with a volume but no cost is a heading only when the next row is numbered inside it (6.1 → 6.1.1)."""
    heading, state['heading'] = state['heading'], None
    if heading is None or (heading['number'] and number.startswith(heading['number'] + '.')):
        return
    state['group'] = heading['previous']
    act['warnings'].append(f'Стр. {heading["page"]}: у строки № {heading["order"]} акта «{heading["name"][:80]}» '
                           'есть единица и объём, но нет цены и стоимости. Это не позиция, и это не заголовок '
                           'группы: следующая строка не входит в неё по номеру. Её объём не учтён.')


def _act_rows(cells, columns, page_number, act, state):
    """Positions of the act: a row with its number by order, unit, volume and cost; headings name their section."""
    money = columns['money']
    costs = money[len(money)//2:] if len(money) != 3 else money[2:]
    for row in cells:
        if len(row) <= money[-1] or not any(cell.strip() for cell in row):
            continue
        if state['table_total'] is not None:
            return  # The table of works ends at its total; the list of the customer's materials follows.
        order, label = _space(row[columns['order']]), _space(' '.join(row)).lower()
        filled = [_space(cell) for cell in row if _space(cell)]
        if filled == [str(n) for n in range(1, len(filled)+1)]:
            continue  # The row of column numbers under the labels.
        if not order.isdigit():
            if label.startswith(('итого', 'всего')) and 'в том числе' not in label and not _SECTION_TOTAL.match(label):
                parts = [_amount(row[n]) for n in costs]
                if any(v is not None for v in parts):
                    _settle_heading(act, state)
                    state['table_total'] = fsum(v for v in parts if v is not None)
            elif _SECTION_TOTAL.match(label):
                _settle_heading(act, state)
            elif label.startswith('раздел'):
                # «Итого по разделу» closes a section, not the table; the next section names itself.
                _settle_heading(act, state)
                state['section'], state['group'] = _space(' '.join(cell for cell in row if _space(cell))), None
            continue
        number = _space(row[columns['number']]).rstrip('.')
        name = _space(' '.join(row[n] for n in columns['name']))
        unit = _space(row[columns['unit']])
        work = _amount(row[columns['work']])
        material = _amount(row[columns['material']]) if columns['material'] is not None else None
        values = [_amount(row[n]) for n in money]
        if len(values) == 2:
            price = {'material': None, 'work': None, 'total': values[0]}
            amount = {'material': None, 'work': None, 'total': values[1]}
        elif len(values) == 3:
            parts = [v for v in values[:2] if v is not None]
            price = {'material': values[0], 'work': values[1], 'total': fsum(parts) if parts else None}
            amount = {'material': None, 'work': None, 'total': values[2]}
        else:
            parts = [v for v in values[2:] if v is not None]
            price = {'material': values[0], 'work': values[1], 'total': None}
            amount = {'material': values[2], 'work': values[3], 'total': fsum(parts) if parts else None}
        quantity = work if work is not None else material
        if all(v is None and _space(row[n]) in ('', '-') for n, v in zip(money, values)):
            # A heading may give the volume of its works and leave the cost to them.
            _settle_heading(act, state, number)
            previous = state['group']
            if name.lower().startswith('раздел'):
                state['section'], state['group'] = name, None
            elif name:
                state['group'] = name
            if unit or quantity is not None:
                state['heading'] = {'order': order, 'number': number if _CODE.match(number) else '', 'name': name,
                                    'page': page_number, 'previous': previous}
            continue
        _settle_heading(act, state, number)
        if not unit or quantity is None or amount['total'] is None:
            act['warnings'].append(f'Стр. {page_number}: строка № {order} акта «{name[:80]}» не распознана как '
                                   'позиция: не хватает единицы, объёма или стоимости.')
            continue
        if not _CODE.match(number):
            act['warnings'].append(f'Стр. {page_number}: у строки № {order} акта «{name[:80]}» нет номера позиции '
                                   'по смете: с расчётом договорной стоимости её не связать по номеру.')
        act['positions'].append({'row': int(order), 'number': number if _CODE.match(number) else '', 'name': name,
                                 'unit': unit, 'quantity': quantity,
                                 'quantity_basis': 'work' if work is not None else 'material',
                                 'quantity_material': material, 'unit_price': price, 'amount': amount,
                                 'section': state['section'], 'group': state['group'], 'page': page_number})


def _act_positions(document, act):
    """The table of the act page by page: a continuation page without labels keeps the columns of the first."""
    state = {'section': None, 'group': None, 'table_total': None, 'heading': None}
    columns, bounds, found = None, None, False
    for index, page in enumerate(document):
        if state['table_total'] is not None:
            break
        # A PDF printed twice over itself carries every word twice: the cells take each word once.
        page._contract_words = _act_words(page)
        grid = _Grid(page)
        header, layout = _act_layout(grid.cells)
        if header is not None:
            found = True
            if layout is None:
                act['warnings'].append(f'Стр. {index+1}: в таблице акта КС-2 не распознаны графы объёма, цены и '
                                       'стоимости: позиции акта не прочитаны.')
                columns = None
                continue
            columns, bounds = layout, grid.columns
            _act_rows(grid.cells[header+1:], columns, index+1, act, state)
        elif columns is not None and _continues(grid, bounds):
            _act_rows(_Grid(page, bounds).cells, columns, index+1, act, state)
        else:
            columns = None
    if not found:
        act['warnings'].append('В акте КС-2 не найдена таблица выполненных работ: позиции и объёмы не прочитаны.')
        return
    _settle_heading(act, state)
    act['table_total'] = state['table_total']
    for position in act['positions']:
        price, amount = position['unit_price'], position['amount']
        for part in ('total', 'material', 'work'):
            volume = position['quantity_material'] if part == 'material' else position['quantity']
            if price[part] is None or amount[part] is None or volume is None:
                continue
            expected = volume*price[part]
            if abs(expected-amount[part]) > max(_TOLERANCE, abs(expected)*0.0005):
                act['warnings'].append(f'Строка № {position["row"]} акта (позиция {position["number"] or "без номера"}): '
                                       f'объём × цена = {_figure(expected)}, а в графе стоимости '
                                       f'{_figure(amount[part])}.')
    if act['positions'] and act['table_total'] is not None:
        listed = fsum(p['amount']['total'] for p in act['positions'])
        if abs(listed-act['table_total']) > _TOLERANCE*max(1, len(act['positions'])):
            act['warnings'].append(f'Сумма позиций акта {_figure(listed)} не равна строке «Итого» таблицы '
                                   f'{_figure(act["table_total"])}: проверьте, все ли строки прочитаны.')
    if not act['positions']:
        act['warnings'].append('В таблице акта КС-2 не найдено ни одной позиции с единицей, объёмом и стоимостью.')


def _act(document, text):
    """Number, date, reporting period, total and positions of an act КС-2, or None for another document.

    Each value is read under its label of the form's header: «Номер документа»,
    «Дата составления», «Отчётный период с … по …». A label without its value
    leaves the value None and a warning; nothing is guessed from the file name.
    """
    if not all(pattern.search(_space(text)) for pattern in _ACT_FORM):
        return None
    words = _act_words(document[0])
    named = lambda text: [w for w in words if w[4].lower() == text]
    act = {'number': None, 'date': None, 'start': None, 'finish': None, 'total': None, 'positions': [],
           'table_total': None, 'warnings': []}
    contract = None
    for label in named('договор'):
        number = _right_of(words, label, lambda text: not _DATE.fullmatch(text))
        dated = next((w for w in sorted(named('дата'), key=lambda w: w[1]) if 0 < w[1]-label[1] < _ACT_ROW), None)
        when = dated and _right_of(words, dated, lambda text: bool(_DATE.fullmatch(text)))
        if number:
            contract = {'number': _contract_number(number[4]), 'date': when and _date(when[4])}
            break
    is_date = lambda text: bool(_DATE.fullmatch(text))
    for key, label in (('number', 'документа'), ('date', 'составления')):
        for found in named(label):
            value = _below(words, found, (lambda text: not is_date(text) and bool(re.fullmatch(r'[\w/.-]+', text)))
                           if key == 'number' else is_date)
            if value:
                act[key] = value[4] if key == 'number' else _date(value[4])
                break
    composed = next(iter(named('составления')), None)
    if act['number'] is None and composed:
        # Some forms print the label of the number as «№» alone, left of «Дата составления».
        for sign in sorted(named('№'), key=lambda w: composed[0]-w[2]):
            if abs(sign[1]-composed[1]) < _ACT_ROW and 0 < composed[0]-sign[2] < 3*_ACT_COLUMN:
                value = _below(words, sign, lambda text: not is_date(text) and bool(re.fullmatch(r'[\w/.-]+', text)))
                if value:
                    act['number'] = value[4]
                    break
    period = next((w for w in words if w[4].lower() in ('отчетный', 'отчётный')), None)
    until = period and min((w for w in words if w[4].lower() == 'по' and 0 <= w[1]-period[1] < _ACT_BELOW
                            and w[0] > period[0]), key=lambda w: (w[1], w[0]), default=None)
    since = until and max((w for w in words if w[4].lower() == 'с' and abs(w[1]-until[1]) < 3
                           and w[2] <= until[0]), key=lambda w: w[0], default=None)
    for key, label in (('start', since), ('finish', until)):
        value = label and _below(words, label, is_date)
        act[key] = value and _date(value[4])
    for page in document:
        act['total'] = _act_total(_act_words(page))
        if act['total'] is not None:
            break
    _act_positions(document, act)
    if act['total'] is None:
        # Without «Итого по акту» the total row of the act's own table is its total.
        act['total'] = act['table_total']
    elif act['positions'] and (act['table_total'] is None or abs(act['table_total']-act['total']) > _TOLERANCE):
        listed = fsum(p['amount']['total'] for p in act['positions'])
        if act['table_total'] is not None and abs(listed-act['table_total']) <= _TOLERANCE*max(1, len(act['positions'])):
            # Every row is read: the total of the act differs from the table by itself (VAT, coefficients).
            act['warnings'].append(f'Строка «Итого» таблицы акта {_figure(act["table_total"])} не равна строке '
                                   f'«Итого по акту» {_figure(act["total"])}. Позиции прочитаны все; разница '
                                   'может быть налогом или коэффициентом — проверьте акт.')
        elif abs(listed-act['total']) > _TOLERANCE*max(1, len(act['positions'])):
            act['warnings'].append(f'Сумма позиций акта {_figure(listed)} не равна строке «Итого по акту» '
                                   f'{_figure(act["total"])}: проверьте, все ли строки прочитаны.')
    shown = {'number': 'номер документа', 'date': 'дата составления', 'start': 'начало отчётного периода',
             'finish': 'окончание отчётного периода', 'total': 'итог по акту'}
    missing = [shown[key] for key in shown if act[key] is None]
    if missing:
        act['warnings'].append('В акте КС-2 не прочитаны: ' + ', '.join(missing) + '.')
    if act['start'] and act['finish'] and act['start'] > act['finish']:
        act['warnings'].append(f'В акте КС-2 начало отчётного периода {_shown(act["start"])} позже его окончания '
                               f'{_shown(act["finish"])}: период по акту не определён.')
        act['start'] = act['finish'] = None
    return {'contract': contract, 'act': act}


# A contract with all its annexes is tens of pages; a longer file is not read in a shared worker.
MAX_PAGES = 300


def read(data: bytes) -> dict:
    """Read a contract or agreement PDF. Unreadable documents raise ValueError."""
    import pymupdf
    try:
        document = pymupdf.open(stream=data, filetype='pdf')
    except (RuntimeError, ValueError) as error:
        raise ValueError('Файл не открылся как PDF. Сохраните документ в PDF заново, например выгрузкой из системы '
                         'электронного документооборота, и загрузите ещё раз.') from error
    with document:
        if document.page_count > MAX_PAGES:
            raise ValueError(f'В документе страниц: {document.page_count}, а читается не больше {MAX_PAGES}. '
                             'Загрузите договор, соглашения и акты отдельными файлами.')
        return _read(document)


def _read(document) -> dict:
    texts = [page.get_text() for page in document]
    if not any(_space(text) for text in texts):
        raise ValueError('В PDF нет текстового слоя: это скан. Графы расчёта и графика по скану не прочитать '
                         'надёжно; нужен PDF с текстом, например выгрузка из системы электронного документооборота.')
    accepted = _act(document, texts[0])
    if accepted is not None:
        # The agreement an act names is the one it was signed under, not a new edition.
        return {'contract': accepted['contract'], 'agreement': None, 'act': accepted['act'], 'estimates': [],
                'schedule': None, 'warnings': accepted['act'].pop('warnings'), 'pages': len(texts)}
    import developaid_contract_terms as terms
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
            weekly = _weekly_page(page, number, schedule) or _dated_bar_page(page, number, schedule)
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
    # A PDF's text stream may print an entire date column after its heading.
    # Dates inside the recognised GPR/RDS are work rows, not legal clauses.
    # Keep contract paragraphs outside the table, including on the same page.
    table_pages = set((out['schedule'] or {}).get('pages') or [])
    table_pages.update(n for e in out['estimates'] for n in e['pages'])
    table_pages.update(n for n, text in enumerate(texts, 1)
                       if (_SCHEDULE_TITLE.search(text) or _ESTIMATE_TITLE.search(text))
                       and _Grid(document[n-1]).rows)
    condition_texts = list(texts)
    for number in table_pages:
        page = document[number-1]
        grid = _Grid(page)
        condition_texts[number-1] = ' '.join(w[4] for w in _words(page)
            if grid.rows and not grid.rows[0] <= (w[1]+w[3])/2 <= grid.rows[-1])
    out['terms'] = terms.read(condition_texts)
    out['warnings'].extend(out['terms']['warnings'])
    if not out['estimates'] and not out['schedule'] and not mentioned and not out['terms']['changes_deadline']:
        out['warnings'].append('В документе нет таблиц расчёта договорной стоимости и графика производства работ: '
                               'он их не меняет, или таблицы не распознаны.')
    return out
