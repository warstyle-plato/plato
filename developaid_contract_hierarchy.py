"""Shared visual hierarchy; styling never aggregates quantities or creates facts."""
from copy import copy
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side


def style_row(sheet, row, number='', *, corpus=False, total=False, through=None, name_column=2):
    depth = str(number or '').strip('.').count('.')
    fill = '17365D' if corpus else 'B4C6E7' if depth == 0 else 'D9E2F3' if depth == 1 else 'F2F5FA' if depth == 2 else 'FFFFFF'
    if total:
        fill = 'BDD7EE'
    bold = corpus or total or depth <= 1
    size = 13 if corpus else 12 if depth == 0 or total else 11
    for cell in sheet[row][:through or sheet.max_column]:
        cell.fill = PatternFill('solid',fgColor=fill)
        cell.font = Font(name='Calibri',size=size,bold=bold,color='FFFFFF' if corpus else '172B4D')
        cell.border = Border(top=Side(style='medium' if corpus or total else 'thin',color='9DB4CC'),
                             bottom=Side(style='thin',color='DCE6F1'))
    name = sheet.cell(row,name_column)
    alignment = copy(name.alignment)
    alignment.indent = 0 if corpus or total else min(depth,3)
    alignment.wrap_text = True
    name.alignment = alignment
    if corpus or total:
        sheet.row_dimensions[row].height = max(sheet.row_dimensions[row].height or 0,32)
