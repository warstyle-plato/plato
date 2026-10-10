"""Чувствительность: те же формулы месячной модели, связанные с вводными.

Без таблиц данных Excel и без линейной аппроксимации: каждый вариант
пересчитывает кредит и налог, а не умножает готовый IRR.
"""
from __future__ import annotations

from openpyxl.styles import Alignment

import hotel_workbook_capex as capex

SHEET = "Чувствительность"
FACTORS = ("ADR", "Целевая загрузка", "Ставка СМР", "FF&E на номер",
           "Стоимость выхода", "Ставка кредита")


def build(book, rows, hw):
    ws = book.create_sheet(SHEET, book.index(book[hw.CHECK_SHEET]))
    ws["A1"] = "Чувствительность гостиницы"
    ws["A2"] = "Один фактор за раз; кредит, налог и потоки пересчитываются формулами. Вводные — общие с базой."
    for col, label in zip("ABCDE", ("Фактор", "Изменение", "NPV проекта, ₽", "IRR проекта", "IRR капитала")):
        ws[f"{col}3"] = label
    ws["A4"] = "Базовый проект"
    ws["B4"] = 0
    ws["C4"] = f"='{hw.TOTALS_SHEET}'!B4"
    ws["D4"] = f"='{hw.TOTALS_SHEET}'!B5"
    ws["E4"] = f"='{hw.TOTALS_SHEET}'!B7"
    calculation_sheets = []
    for factor_index, label in enumerate(FACTORS):
        for delta_index, delta in enumerate((-0.1, 0.1)):
            row = 5 + factor_index * 2 + delta_index
            factor = f"(1+'{SHEET}'!$B${row})"
            ws[f"A{row}"], ws[f"B{row}"] = label, delta
            ws[f"B{row}"].fill = hw.INPUT_FILL
            names = {hw.INPUTS_SHEET: f"С{row}_Вводные", capex.SHEET: f"С{row}_Затраты",
                     hw.CALC_SHEET: f"С{row}_Расчёт"}
            for original, name in names.items():
                clone = book.copy_worksheet(book[original])
                clone.title, clone.sheet_state = name, "hidden"
                for cells in clone.iter_rows():
                    for cell in cells:
                        if cell.data_type == "f":
                            expr = cell.value
                            for old, new in names.items():
                                expr = expr.replace(f"'{old}'!", f"'{new}'!")
                            cell.value = expr
                        elif cell.value is not None and cell.fill in (hw.INPUT_FILL, hw.ENGINE_FILL):
                            cell.value = f"='{original}'!{cell.coordinate}"
            inp = book[names[hw.INPUTS_SHEET]]
            if factor_index in (0, 1):
                key = "adr" if factor_index == 0 else "occ_target"
                target = f"C{hw._ROWS[key]}"
                expr = f"'{hw.INPUTS_SHEET}'!{target}*{factor}"
                inp[target] = "=" + (f"MIN(1,MAX(0,{expr}))" if key == "occ_target" else expr)
            elif factor_index in (2, 3):
                key = "hotel_cost_th_per_sqm" if factor_index == 2 else "hotel_ffe_th_per_key"
                target = f"C{capex.INPUT_ROWS[key]}"
                inp[target] = f"='{hw.INPUTS_SHEET}'!{target}*{factor}"
            elif factor_index == 4:
                cell = inp[f"C{hw._ROWS['exit_value']}"]
                cell.value = f"=({cell.value[1:]})*{factor}"
            else:
                for key in ("spread", "pref_margin"):
                    target = f"C{hw._ROWS[key]}"
                    inp[target] = f"='{hw.INPUTS_SHEET}'!{target}*{factor}"
                for r in range(120, 120 + rows):
                    inp[f"F{r}"] = f"='{hw.INPUTS_SHEET}'!F{r}*{factor}"
            calc = names[hw.CALC_SHEET]
            calculation_sheets.append(calc)
            def col(key):
                return f"'{calc}'!{hw._c(key)}{hw.FIRST_ROW}:{hw._c(key)}{hw.FIRST_ROW+rows-1}"
            ws[f"C{row}"] = f"=SUM({col('disc_p')})"
            ws[f"D{row}"] = f'=IFERROR((1+IRR({col("project_cf")},0.01))^12-1,"")'
            ws[f"E{row}"] = f'=IFERROR((1+IRR({col("equity_cf")},0.01))^12-1,"")'
            # Эти служебные колонки не участвуют в результате сценария.
            for r in range(hw.FIRST_ROW, hw.FIRST_ROW + rows):
                for key in ("irr_p", "irr_e"):
                    book[calc][f"{hw._c(key)}{r}"] = "=0"
    for row in range(4, 5 + len(FACTORS) * 2):
        ws[f"B{row}"].number_format = '+0%;-0%;"база"'
        ws[f"C{row}"].number_format = hw.MONEY
        ws[f"D{row}"].number_format = ws[f"E{row}"].number_format = hw.PERCENT
    ws.column_dimensions["A"].width = 30
    for col in "BCDE":
        ws.column_dimensions[col].width = 22
    ws.freeze_panes = "C4"
    ws["A18"] = "Изменяйте отклонения в жёлтых ячейках. Здесь сравнение с базой, а не со старым снимком движка."
    ws.merge_cells("A18:E18")
    ws["A18"].alignment = Alignment(wrap_text=True)
    ws.row_dimensions[18].height = 36
    return calculation_sheets
