"""The header of a scanned contract document, recognised and held until the user confirms it.

A scan has no text layer, so the tables of the contract estimate, the ГПР and the
act КС-2 are not read from it: one misread figure in a table would quietly shift
the plan, the fact and the lag. Only the header is recognised (`pdf_ocr`, the
service's one recognition): the contract and the agreement by the same
`identity` as a PDF with text, the act КС-2 by its title line, where the form
prints the act's number, its date and the reporting period in one row.

What is recognised is a proposal. The record carries `scan` with the values as
read; nothing of it enters the plan, the fact or the dating of KS-6a periods
until the user has checked the values, corrected them if needed and confirmed
(`developaid_contract_files.confirm_scan`). Owner's decision 13.11.2026 «А».
"""
from __future__ import annotations

import re

import developaid_contract_documents as documents

# Pages recognised in search of the header: a КС-3 or a cover letter may come first.
PAGES = 3
# Forms are printed small; at 200 dpi the dates of the act's row run together.
DPI = 300
# Enough of the recognised text to find the card's contract number in it again.
KEPT_TEXT = 20000
_ACT_TITLE = re.compile(r'АКТ\s+О\s+ПРИ[ЕЁ]МКЕ\s+ВЫПОЛНЕННЫХ\s+РАБОТ', re.I)
_ACT_NUMBER = re.compile(r'[\w/.-]*\d[\w/.-]*')
_UNNUMBERED = re.compile(r'Дополнительн\w+\s+соглашени\w+\W{0,6}(?:б/н\W{0,3})?к\s+Договор', re.I)
_ACT_CONTRACT = re.compile(r'^\W*(?:Договор|Д\w{4,6}р)\w*(?:\s+подряда)?[\s|\]\[:—_-]+№?\s*([\w./-]*\d[\w./-]*)',
                           re.I | re.M)
TABLES_NOT_READ = ('Документ — скан: распознана только шапка. Таблицы расчёта, графика и позиций акта по скану '
                   'не читаются — для них нужен PDF с текстом, например выгрузка из системы электронного '
                   'документооборота.')
CHECK = ('Значения прочитаны со скана распознаванием и могут быть ошибочны. Проверьте их, исправьте при '
         'необходимости и подтвердите: до подтверждения документ в расчёт не входит.')


def unavailable(reason: str) -> str:
    return (f'В PDF нет текстового слоя: это скан, а распознавание на сервере сейчас недоступно ({reason}). '
            'Загрузите PDF с текстом, например выгрузку из системы электронного документооборота.')


def _act(text: str) -> dict | None:
    """Number, date and reporting period from the title row of the act КС-2, or None for another document."""
    title = _ACT_TITLE.search(text)
    if not title:
        return None
    row = text[title.end():].split('\n', 1)[0]
    dates = [documents._date(m[0]) for m in documents._DATE.finditer(row)]
    first = documents._DATE.search(row)
    number = _ACT_NUMBER.search(row[:first.start()] if first else row)
    act = {'number': number[0].strip('.') if number else None, 'date': None, 'start': None, 'finish': None,
           'total': None, 'positions': [], 'table_total': None}
    warnings = []
    if len(dates) == 3 and all(dates) and dates[1] <= dates[2]:
        act.update(date=dates[0], start=dates[1], finish=dates[2])
    else:
        warnings.append('Дата акта и отчётный период по скану не распознаны: впишите их по документу.')
    if act['date'] and act['date'] < act['finish']:
        warnings.append('Дата акта по скану раньше конца отчётного периода: проверьте обе даты по документу.')
    if act['number'] is None:
        warnings.append('Номер акта по скану не распознан: впишите его по документу.')
    found = _ACT_CONTRACT.search(text[:title.start()])
    contract = None
    if found:
        after = text[found.end():found.end() + 120]
        when = documents._DATE.search(after)
        contract = {'number': documents._contract_number(found[1]), 'date': when and documents._date(when[0])}
    return {'act': act, 'contract': contract, 'warnings': warnings}


def _header(text: str) -> dict | None:
    """The header found on one recognised page, or None when the page names no document."""
    act = _act(text)
    if act:
        return {'contract': act['contract'], 'agreement': None, 'act': act['act'], 'warnings': act['warnings']}
    found = documents.identity(text)
    if found['agreement'] is None and _UNNUMBERED.search(documents._space(text)):
        spaced = documents._space(text)
        contract = documents._CONTRACT.search(spaced)
        found['agreement'] = {'number': 'б/н', 'date': contract and documents._dated(spaced, contract.end())}
    if found['contract'] or found['agreement']:
        return {**found, 'act': None, 'warnings': []}
    return None


def read(data: bytes, pages: int) -> dict:
    """The recognised header of a scan of `pages` pages; ValueError when recognition is unavailable."""
    import pdf_ocr
    reason = pdf_ocr.unavailable_reason()
    if reason:
        raise ValueError(unavailable(reason))
    texts, header, page = [], None, None
    for index in range(min(PAGES, pages)):
        try:
            text = pdf_ocr.text(data, dpi=DPI, page_indices=[index], upright=True).split('\n', 1)[-1]
        except pdf_ocr.Unavailable as exc:
            raise ValueError(unavailable(exc.public_message)) from None
        texts.append(text)
        header = _header(text)
        if header:
            page = index + 1
            break
    warnings = list(header['warnings']) if header else [
        f'На первых {len(texts)} страницах скана не распознаны ни договор, ни дополнительное соглашение, '
        'ни акт КС-2: впишите, что это за документ, или загрузите PDF с текстом.']
    found = {key: (header or {}).get(key) for key in ('contract', 'agreement', 'act')}
    return {**found, 'estimates': [], 'schedule': None, 'pages': pages, 'warnings': [TABLES_NOT_READ, *warnings],
            'scan': {'page': page, 'read': found, 'text': '\n'.join(texts)[:KEPT_TEXT], 'confirmed_at': None}}
