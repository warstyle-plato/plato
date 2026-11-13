"""Read-only explanation of economic AHR; no bank allocation or gap calculation."""
from __future__ import annotations

import hashlib
import html
import io
import math
import re
from contextlib import closing

FIELDS = (("total", "АХР — всего"), ("fact", "АХР — факт по финмодели"),
          ("plan", "АХР — осталось по финмодели"))
NOTE = ("АХР уже входят в утверждённый бюджет. Здесь они показаны отдельно для расшифровки "
        "и повторно к расходам или дефициту не прибавляются.")
BANK_NOTE = ("Включение АХР в банковскую смету и доступный остаток банковского покрытия — разные "
             "показатели. Денежный остаток покрытия этой расшифровкой не подтверждается.")


def _number(value):
    if value is None or isinstance(value, bool):
        return None
    try:
        value = float(str(value).replace('\xa0', '').replace(' ', '').replace(',', '.'))
    except (ValueError, TypeError):
        return None
    rubles = value * 1000
    return rubles if math.isfinite(rubles) else None


def unavailable(reason, source=None):
    return {"state": "missing", "reason": reason, "rows": [], "source": source or {},
            "total": None, "fact": None, "plan": None, "note": NOTE, "bank_note": BANK_NOTE}


def read(data: bytes, *, taken_at="", cut="", filename=""):
    """Use cached leaf cells of cf_1_new 2.4, excluding taxes 2.4.5, in rubles.

    Independent of the bank-code dictionary, RSS, GPR and other finance gates.
    A formula without a cached value stays unknown; a real zero stays zero.
    """
    from openpyxl import load_workbook
    from openpyxl.utils import get_column_letter

    source = {"sha256": hashlib.sha256(data).hexdigest(), "taken_at": taken_at,
              "filename": filename, "sheet": "cf_1_new", "unit": "тыс. ₽"}
    if taken_at and cut and taken_at[:10] > cut[:10]:
        return unavailable("Версия финмодели позже выбранного среза.", source)
    if len(data) > 32 * 1024 * 1024:
        return unavailable("Финмодель превышает допустимый размер чтения.", source)
    with closing(load_workbook(io.BytesIO(data), read_only=True, data_only=True)) as book:
        if 'cf_1_new' not in book.sheetnames:
            return unavailable("В финансовой книге нет листа «cf_1_new» с АХР.", source)
        sheet = book['cf_1_new']
        if sheet.max_row > 50000 or sheet.max_column > 1000:
            return unavailable("Размер листа АХР превышает допустимый для чтения.", source)
        columns, items, all_codes = None, [], []
        for index, values in enumerate(sheet.iter_rows(values_only=True), 1):
            if columns is None:
                labels = {str(v or '').strip().lower().replace('ё', 'е'): i for i, v in enumerate(values)}
                if {'итого', 'факт', 'план'} <= labels.keys():
                    columns = {key: labels[label] for key, label in
                               (('total', 'итого'), ('fact', 'факт'), ('plan', 'план'))}
                continue
            code = str(values[2] or '').strip().rstrip('.') if len(values) > 2 else ''
            if not re.fullmatch(r'2\.4(?:\.\d+)*', code):
                continue
            all_codes.append(code)
            if code == '2.4.5' or code.startswith('2.4.5.'):
                continue
            items.append({"code": code, "name": str(values[3] or '') if len(values) > 3 else '',
                          "row": index,
                          "cells": {key: f'{get_column_letter(c + 1)}{index}' for key, c in columns.items()},
                          **{key: _number(values[c]) if c < len(values) else None
                             for key, c in columns.items()}})
    if columns is None:
        return unavailable("В финмодели не найдены колонки «ИТОГО / ФАКТ / ПЛАН».", source)
    leaves = [item for item in items if not any(other.startswith(item['code'] + '.')
                                               for other in all_codes)]
    if not leaves:
        return unavailable("В финмодели нет распознанных строк АХР без налогов.", source)
    if len({item['code'] for item in items}) != len(items):
        return unavailable("В строках АХР повторяются коды: общий итог не подтверждён.", source)
    result = {"state": "ok", "source": source, "rows": leaves, "management_article": "2.6",
              "management_basis": "управленческая группировка по решению владельца",
              "note": NOTE, "bank_note": BANK_NOTE}
    for key, _ in FIELDS:
        known = [r[key] for r in leaves if r[key] is not None]
        result[key] = sum(known) if len(known) == len(leaves) else None
        result[key + '_known_part'] = sum(known) if known else None
        result[key + '_missing'] = len(leaves) - len(known)
    result['difference'] = (result['total'] - result['fact'] - result['plan']
                            if all(result[k] is not None for k, _ in FIELDS) else None)
    return result


def for_project(project, cut=""):
    import developaid_monitor as monitor
    path = monitor._project_dir(project) / 'baseline' / 'finance.xlsx'
    try:
        data = path.read_bytes()
    except OSError:
        return unavailable("Финмодель проекта недоступна.")
    meta = monitor.finance_baseline_meta(project) or {}
    try:
        result = read(data, taken_at=str(meta.get('taken_at') or ''), cut=str(cut),
                      filename=str(meta.get('file_name') or ''))
        if path.read_bytes() != data or monitor.finance_baseline_meta(project) != meta:
            return unavailable("Финмодель меняется. Обновите просмотр после сохранения.")
        return result
    except Exception:
        return unavailable("Строки АХР в сохранённой финмодели не прочитаны.")


def money(value):
    if value is None:
        return "нет данных"
    return (f'{value:,.0f}' if float(value).is_integer() else f'{value:,.2f}').replace(',', ' ').replace('.', ',') + ' ₽'


def tiles(model):
    result = []
    for key, label in FIELDS:
        value = model.get(key)
        note = model.get('reason') or 'По сохранённой финмодели; уже входит в бюджет.'
        if model.get(key + '_missing'):
            note = f"Нет значения у {model[key + '_missing']} строк. Известная часть: {money(model.get(key + '_known_part'))}."
        result.append({"label": label, "value": money(value), "note": note,
                       "tone": "missing" if value is None else ""})
    return result


def render(model, *, show_tiles=True):
    esc = lambda value: html.escape(str(value))
    out = ['<section class="admin-expenses"><h3>Административные расходы · статья 2.6</h3>']
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
