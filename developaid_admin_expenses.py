"""Read-only explanation of economic AHR; no bank allocation or gap calculation."""
from __future__ import annotations

import hashlib
import html
import math

FIELDS = (("total", "АХР — всего"), ("fact", "АХР — факт по финмодели"),
          ("plan", "АХР — осталось по финмодели"))
NOTE = ("АХР уже входят в утверждённый бюджет. Здесь они показаны отдельно для расшифровки "
        "и повторно к расходам или дефициту не прибавляются.")
BANK_NOTE = ("Включение АХР в банковскую смету и доступный остаток банковского покрытия — разные "
             "показатели. Денежный остаток покрытия этой расшифровкой не подтверждается.")


def _number(value, factor):
    if value is None or isinstance(value, bool) or factor is None:
        return None
    try:
        rubles = float(str(value).replace('\xa0', '').replace(' ', '').replace(',', '.')) * factor
    except (ValueError, TypeError, OverflowError):
        return None
    return rubles if math.isfinite(rubles) else None


def unavailable(reason, source=None):
    return {"state": "missing", "reason": reason, "rows": [], "source": source or {},
            "scope": "raw_saved_snapshot", "cut_eligibility": "unknown",
            "financial_acceptance": False, "total": None, "fact": None, "plan": None,
            "note": NOTE, "bank_note": BANK_NOTE}


def _projection_model(projection, cut="", filename=""):
    """One normalized view of fixed cached cells, with source scope kept explicit."""
    import datetime as dt

    raw_source = projection.get('source') or {}
    evidence = projection.get('unit_evidence') or {}
    unit = evidence.get('recognized_unit') if evidence.get('state') == 'observed' else None
    factor = {'руб.': 1.0, 'тыс. руб.': 1000.0, 'млн руб.': 1000000.0}.get(unit)
    source = {**raw_source, 'taken_at': raw_source.get('version_date') or '',
              'filename': filename, 'unit': unit, 'unit_factor_to_rubles': factor,
              'unit_evidence': evidence}
    try:
        version = dt.date.fromisoformat(raw_source.get('version_date'))
    except (ValueError, TypeError):
        version = None
    try:
        selected = dt.date.fromisoformat(str(cut))
    except (ValueError, TypeError):
        selected = None
    eligible = version <= selected if version and selected else None
    reasons = []
    if version is None:
        reasons.append('Дата версии текущей сохранённой финмодели не указана; '
                       'эти значения не отнесены к выбранной дате.')
    elif eligible is False:
        reasons.append('Версия финмодели позже выбранного среза; её суммы не показаны как факт этого среза.')
    elif selected is None:
        reasons.append('Дата просмотра не определена; эти значения относятся только к сохранённой версии финмодели.')
    if factor is None:
        reasons.append('Единицы денежных граф финмодели не подтверждены по шапке листа.'
                       if evidence.get('state') != 'ambiguous' else
                       'В шапке листа указаны разные денежные единицы; масштаб сумм не подтверждён.')
    allowed_factor = factor if eligible is not False else None
    rows = []
    for item in projection.get('rows') or []:
        cells = item.get('cells') or {}
        rows.append({'code': item['code'], 'name': 'Строка финмодели ' + item['code'],
                     'row': item['row'],
                     'cells': {key: (cells.get(key) or {}).get('cell', '') for key, _ in FIELDS},
                     **{key: _number((cells.get(key) or {}).get('cached_value'), allowed_factor)
                        for key, _ in FIELDS}})
    if not rows:
        return unavailable('В финмодели нет распознанных строк АХР без налогов.', source)
    result = {'state': ('source_after_cut' if eligible is False else 'unit_unknown' if factor is None
                        else 'current_source_only' if eligible is None else 'ok'),
              'scope': 'raw_saved_snapshot', 'cut': str(cut),
              'cut_eligibility': 'eligible' if eligible is True else 'future' if eligible is False else 'unknown',
              'source_date_state': 'declared_in_metadata' if version else 'unknown',
              'values_are_normalized_rubles': factor is not None,
              'historical_eligibility_evaluated': eligible is not None,
              'financial_acceptance': False,
              'source': source, 'rows': rows, 'management_article': '2.6',
              'management_basis': 'управленческая группировка по решению владельца',
              'reason': ' '.join(reasons), 'note': NOTE, 'bank_note': BANK_NOTE}
    for key, _ in FIELDS:
        known = [r[key] for r in rows if r[key] is not None]
        subtotal = sum(known) if known else None
        if subtotal is not None and not math.isfinite(subtotal):
            subtotal = None
            result['reason'] += ' Сумма исходных ячеек превышает допустимый числовой диапазон.'
        result[key] = subtotal if len(known) == len(rows) else None
        result[key + '_known_part'] = subtotal
        result[key + '_missing'] = len(rows) - len(known)
    result['difference'] = (result['total'] - result['fact'] - result['plan']
                            if all(result[k] is not None for k, _ in FIELDS) else None)
    if result['difference'] is not None and not math.isfinite(result['difference']):
        result['difference'] = None
    # A raw saved-snapshot amount is never silently promoted to a dated fact.
    result['amounts_at_cut'] = {key: result[key] if eligible is True else None for key, _ in FIELDS}
    return result


def read(data: bytes, *, taken_at="", cut="", filename=""):
    """Read the same fixed leaf projection used by the bounded native source audit."""
    import datetime as dt
    import developaid_admin_expenses_source as source_reader

    source = {'sha256': hashlib.sha256(data).hexdigest(), 'sheet': 'cf_1_new',
              'version_date': None, 'selection_basis': 'current_stored_bytes_not_a_historical_cut'}
    try:
        source['version_date'] = dt.date.fromisoformat(str(taken_at)).isoformat()
    except (ValueError, TypeError):
        pass
    try:
        if len(data) > source_reader.MAX_SOURCE:
            raise source_reader.SourceProblem('source_size_limit')
        rows, headers, units = source_reader._cells(data)
        return _projection_model({'source': source, 'rows': rows, 'header_cells': headers,
                                  'unit_evidence': units}, cut, filename)
    except source_reader.SourceProblem as exc:
        return unavailable(_source_reason(exc.code), source)
    except Exception:
        return unavailable('Строки АХР в сохранённой финмодели не прочитаны.', source)


def _source_reason(code):
    return {'source_missing': 'Финмодель проекта недоступна.',
            'source_pair_mismatch': 'Финмодель и сведения о её версии не согласованы. Дождитесь завершения сохранения.',
            'source_changed': 'Финмодель меняется. Обновите просмотр после сохранения.',
            'sheet_missing': 'В финансовой книге нет листа «cf_1_new» с АХР.',
            'columns_missing': 'В финмодели не найдены колонки «ИТОГО / ФАКТ / ПЛАН».',
            'columns_ambiguous': 'Колонки АХР неоднозначны: общий итог не подтверждён.',
            'codes_ambiguous': 'В строках АХР повторяются коды: общий итог не подтверждён.',
            'rows_missing': 'В финмодели нет распознанных строк АХР без налогов.'}.get(
                code, 'Ограниченное чтение АХР не выполнено. Обновите просмотр после проверки источника.')


def for_project(project, cut=""):
    import developaid_admin_expenses_source as source_reader
    try:
        # This source reader already pins aliases/directories, shares the native
        # writer lock, verifies the source/metadata pair and detects replacement.
        projection = source_reader.capture_saved_snapshot(project, runtime={})
        return _projection_model(projection, str(cut))
    except source_reader.SourceProblem as exc:
        return unavailable(_source_reason(exc.code))
    except Exception:
        return unavailable('Строки АХР в сохранённой финмодели не прочитаны.')


def availability_note(model):
    if (model.get('source') or {}).get('sha256'):
        return 'Финмодель сохранена; общая финансовая сверка не завершена.'
    return model.get('reason') or 'Финансовая книга не загружена.'


def money(value):
    if value is None:
        return "нет данных"
    return (f'{value:,.0f}' if float(value).is_integer() else f'{value:,.2f}').replace(',', ' ').replace('.', ',') + ' ₽'


def tiles(model):
    result = []
    for key, label in FIELDS:
        value = model.get(key)
        note = model.get('reason') or 'По текущей сохранённой финмодели; уже входит в бюджет.'
        if (model.get(key + '_missing') and (model.get('source') or {}).get('unit_factor_to_rubles') is not None
                and model.get('cut_eligibility') != 'future'):
            partial = f"Нет значения у {model[key + '_missing']} строк. Известная часть: {money(model.get(key + '_known_part'))}."
            note = note + ' ' + partial
        result.append({"label": label, "value": money(value), "note": note, "group": "admin_expenses",
                       "tone": "missing" if value is None else ""})
    return result


def render(model, *, show_tiles=True):
    esc = lambda value: html.escape(str(value))
    out = ['<section class="admin-expenses"><h3>Административные расходы · статья 2.6</h3>',
           '<p>Источник сумм — текущая сохранённая финмодель. Факт относится к этой версии книги.</p>']
    if show_tiles:
        out.append('<div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:12px">')
        for tile in tiles(model):
            out.append(f'<div><small>{esc(tile["label"])}</small><div style="font-size:20px;font-weight:700">'
                       f'{esc(tile["value"])}</div><small>{esc(tile["note"])}</small></div>')
        out.append('</div>')
    out.append(f'<p>{esc(model.get("note") or NOTE)}</p>')
    if model.get('reason'):
        out.append(f'<p>{esc(model["reason"])}</p>')
    source = model.get('source') or {}
    when = source.get('taken_at') or 'дата версии не указана'
    out.append(f'<p>Источник: {esc(source.get("filename") or "сохранённая финмодель")}, '
               f'{esc(source.get("sheet") or "cf_1_new")}; {esc(when)}. Факт относится к этой версии книги.</p>')
    if source.get('unit'):
        out.append(f'<p>Единицы в шапке: {esc(source["unit"])}; плашки приведены к рублям.</p>')
    if source.get('sha256'):
        out.append(f'<details><summary>Отпечаток источника</summary><p style="overflow-wrap:anywhere">{esc(source["sha256"])}</p></details>')
    out.append(f'<p>{esc(model.get("bank_note") or BANK_NOTE)}</p>')
    if model.get('difference') is not None and abs(model['difference']) > .5:
        out.append(f'<p>В источнике ИТОГО отличается от ФАКТ + ПЛАН на {esc(money(model["difference"]))}.</p>')
    if model.get('rows'):
        out.append('<details><summary>Состав АХР без налогов</summary><div style="overflow-x:auto">'
                   '<table><thead><tr><th>Код ФМ</th><th>Расход</th><th>Итого</th><th>Факт</th><th>План</th>'
                   '<th>Ячейки источника</th></tr></thead><tbody>')
        for row in model['rows']:
            out.append('<tr>' + ''.join(f'<td>{esc(v)}</td>' for v in
                [row['code'], row['name'], *(money(row[k]) for k, _ in FIELDS),
                 ' / '.join(row['cells'][k] for k, _ in FIELDS)]) + '</tr>')
        out.append('</tbody></table></div></details>')
    out.append('</section>')
    return ''.join(out)
