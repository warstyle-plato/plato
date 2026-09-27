"""Formula-driven Excel exporters for the DevelopAid commercial beta.

These books are independent from the residential v4 workbook. They do not
contain escrow or residential project-finance mechanics.
"""

from __future__ import annotations

import io
from typing import Any

import xlsxwriter

from developaid_commercial import CommercialRequest, calculate, default_inputs

_ASSETS = {
    "office": ("Office", "Офис"),
    "retail": ("Retail", "Торговый объект"),
    "hotel": ("Hotel", "Гостиница"),
}

_LABELS = {
    "land_cost_rub": ("Стоимость участка", "₽"),
    "gross_area_sqm": ("ГНС", "м²"),
    "construction_cost_rub_sqm": ("Строительство", "₽/м² ГНС"),
    "soft_cost_pct": ("Проектирование и soft costs", "% hard cost"),
    "contingency_pct": ("Резерв", "% hard cost"),
    "construction_months": ("Срок строительства", "мес."),
    "stabilization_months": ("Выход на стабилизацию", "мес."),
    "hold_years": ("Горизонт после ввода", "лет"),
    "exit_cap_rate_pct": ("Exit cap rate", "%"),
    "sale_start_month": ("Старт продаж", "мес. от старта"),
    "sale_months": ("Период продаж", "мес."),
    "selling_cost_pct": ("Расходы на продажи", "% выручки"),
    "debt_share_pct": ("Доля кредита", "% затрат"),
    "debt_rate_pct": ("Ставка кредита", "% годовых"),
    "loan_fee_pct": ("Комиссия за кредит", "% лимита"),
    "sales_cash_sweep_pct": ("Погашение долга из продаж", "% поступлений"),
    "income_area_sqm": ("Арендопригодная площадь", "м²"),
    "rent_rub_sqm_month": ("Базовая аренда", "₽/м²/мес."),
    "occupancy_pct": ("Стабилизированная загрузка", "%"),
    "opex_pct": ("Операционные расходы", "% выручки"),
    "saleable_area_sqm": ("Продаваемая площадь", "м²"),
    "sale_price_rub_sqm": ("Цена продажи", "₽/м²"),
    "sales_rub_sqm_month": ("Оборот арендаторов", "₽/м²/мес."),
    "turnover_rent_pct": ("Процент с оборота", "%"),
    "keys": ("Номерной фонд", "ключей"),
    "adr_rub": ("ADR", "₽/номер/сутки"),
    "other_revenue_pct": ("Прочая выручка", "% room revenue"),
    "ffe_reserve_pct": ("FF&E reserve", "% выручки"),
    "saleable_keys": ("Продаваемые номера", "шт."),
    "sale_price_rub_key": ("Цена продажи номера", "₽/номер"),
}

_PERCENT_KEYS = {
    "soft_cost_pct", "contingency_pct", "exit_cap_rate_pct", "selling_cost_pct",
    "debt_share_pct", "debt_rate_pct", "loan_fee_pct", "sales_cash_sweep_pct",
    "occupancy_pct", "opex_pct", "turnover_rent_pct", "other_revenue_pct",
    "ffe_reserve_pct",
}


def _name(key: str) -> str:
    return "inp_" + "".join(ch if ch.isalnum() or ch == "_" else "_" for ch in key)


def _formats(book: xlsxwriter.Workbook) -> dict[str, Any]:
    return {
        "title": book.add_format({
            "bold": True, "font_size": 18, "font_color": "#FFFFFF",
            "bg_color": "#101C2C", "align": "left", "valign": "vcenter",
        }),
        "section": book.add_format({
            "bold": True, "font_color": "#FFFFFF", "bg_color": "#17375E",
        }),
        "header": book.add_format({
            "bold": True, "font_color": "#FFFFFF", "bg_color": "#244B73",
            "border": 1, "border_color": "#D9E2F3",
        }),
        "input": book.add_format({
            "font_color": "#0000FF", "bg_color": "#FFFDEB",
            "num_format": '#,##0.00;[Red](#,##0.00);-',
        }),
        "input_int": book.add_format({
            "font_color": "#0000FF", "bg_color": "#FFFDEB",
            "num_format": '#,##0;[Red](#,##0);-',
        }),
        "input_pct": book.add_format({
            "font_color": "#0000FF", "bg_color": "#FFFDEB",
            "num_format": '0.0%;[Red](0.0%);-',
        }),
        "money": book.add_format({
            "font_color": "#000000",
            "num_format": '#,##0;[Red](#,##0);-',
        }),
        "number": book.add_format({
            "font_color": "#000000",
            "num_format": '#,##0.00;[Red](#,##0.00);-',
        }),
        "percent": book.add_format({
            "font_color": "#000000",
            "num_format": '0.0%;[Red](0.0%);-',
        }),
        "note": book.add_format({"font_color": "#6B7280", "italic": True, "font_size": 9}),
        "total_label": book.add_format({"bold": True, "top": 1, "top_color": "#777777"}),
        "total_money": book.add_format({
            "bold": True, "top": 1, "top_color": "#777777",
            "num_format": '#,##0;[Red](#,##0);-',
        }),
    }


def _summary(book: xlsxwriter.Workbook, req: CommercialRequest, fmt: dict[str, Any]) -> None:
    ws = book.add_worksheet("Summary")
    ws.hide_gridlines(2)
    ws.set_column("A:A", 34)
    ws.set_column("B:B", 22)
    ws.set_column("C:C", 42)
    ws.merge_range("A1:C1", "DevelopAid · " + _ASSETS[req.asset_type][1] + " · итог", fmt["title"])
    ws.write("A3", "Стратегия")
    ws.write_formula("B3", '=IF(model_strategy="income","Доходная модель","Продажа площадей / номеров")')
    ws.write("A4", "Финансирование")
    ws.write_formula("B4", '=IF(model_financing="equity","100% собственные средства","Собственные средства + обычный кредит")')
    ws.write("A5", "Эскроу")
    ws.write("B5", "Не используется")
    ws.write("C5", "Нежилой beta-контур отделён от жилой экономики.", fmt["note"])

    ws.merge_range("A7:C7", "Ключевые показатели", fmt["section"])
    metrics = [
        ("Development cost, ₽", "=development_cost", fmt["money"], "Участок + hard + soft + contingency"),
        ("Совокупная выручка / стоимость, ₽", "=SUM(cf_operating_revenue)+SUM(cf_sale_revenue)+SUM(cf_terminal)", fmt["money"], ""),
        ("Стоимость финансирования, ₽", "=SUM(cf_interest)+SUM(cf_debt_draw)*inp_loan_fee_pct", fmt["money"], ""),
        ("Прибыль до налога, ₽", "=SUM(cf_project)-SUM(cf_interest)-SUM(cf_debt_draw)*inp_loan_fee_pct", fmt["money"], ""),
        ("Маржа", '=IF(B9=0,0,B11/B9)', fmt["percent"], ""),
        ("Project IRR", '=IFERROR((1+IRR(cf_project))^12-1,0)', fmt["percent"], "Unlevered"),
        ("Equity IRR", '=IFERROR((1+IRR(cf_equity))^12-1,0)', fmt["percent"], "Levered"),
        ("Необходимый equity, ₽", '=-SUMIF(cf_equity,"<0",cf_equity)', fmt["money"], ""),
        ("Пиковый долг, ₽", "=MAX(cf_debt_balance)", fmt["money"], ""),
        ("Стабилизированный NOI, ₽/год", '=IF(model_strategy="income",op_noi_annual,0)', fmt["money"], ""),
        ("Yield on cost", '=IF(OR(model_strategy<>"income",development_cost=0),0,op_noi_annual/development_cost)', fmt["percent"], ""),
        ("Exit value, ₽", "=SUM(cf_terminal)", fmt["money"], ""),
    ]
    row = 8
    for label, formula, number_fmt, note in metrics:
        ws.write(row - 1, 0, label)
        ws.write_formula(row - 1, 1, formula, number_fmt)
        ws.write(row - 1, 2, note, fmt["note"])
        row += 1

    ws.merge_range(row + 1, 0, row + 1, 2, "Примечания beta", fmt["section"])
    ws.write(row + 2, 0, "Продажная модель")
    ws.write(row + 2, 1, "Прямые поступления по продаже без блокировки на эскроу.")
    ws.write(row + 3, 0, "Кредит")
    ws.write(row + 3, 1, "Обычный долг; ставка не зависит от наполнения эскроу.")
    ws.write(row + 4, 0, "Налоги")
    ws.write(row + 4, 1, "В beta не моделируются; KPI показаны до налога.")


def _inputs(book: xlsxwriter.Workbook, req: CommercialRequest, values: dict[str, Any], fmt: dict[str, Any]) -> None:
    ws = book.add_worksheet("Inputs")
    ws.hide_gridlines(2)
    ws.set_column("A:A", 32)
    ws.set_column("B:B", 18)
    ws.set_column("C:C", 20)
    ws.set_column("D:D", 38)
    ws.merge_range("A1:D1", "DevelopAid · " + _ASSETS[req.asset_type][1] + " · beta", fmt["title"])
    for row, label, value, name in [
        (3, "Тип объекта", req.asset_type, "model_asset_type"),
        (4, "Модель реализации", req.strategy, "model_strategy"),
        (5, "Финансирование", req.financing_mode, "model_financing"),
    ]:
        ws.write(row - 1, 0, label)
        ws.write(row - 1, 1, value, fmt["input"])
        book.define_name(name, "=Inputs!$B$" + str(row))

    ws.write_row("A7", ["Параметр", "Значение", "Единица", "Источник / комментарий"], fmt["header"])
    row = 8
    for key in default_inputs(req.asset_type).keys():
        label, unit = _LABELS.get(key, (key, ""))
        value = values.get(key)
        ws.write(row - 1, 0, label)
        if key in _PERCENT_KEYS:
            ws.write_number(row - 1, 1, float(value or 0) / 100.0, fmt["input_pct"])
        elif key.endswith("_months") or key in {"hold_years", "keys", "saleable_keys"}:
            ws.write_number(row - 1, 1, float(value or 0), fmt["input_int"])
        elif isinstance(value, (int, float)):
            ws.write_number(row - 1, 1, float(value), fmt["input"])
        else:
            ws.write(row - 1, 1, value, fmt["input"])
        ws.write(row - 1, 2, unit)
        ws.write(row - 1, 3, "Ввод пользователя / beta default", fmt["note"])
        ws.write_comment(row - 1, 1, "Источник: ввод пользователя или beta-значение по умолчанию DevelopAid.")
        book.define_name(_name(key), "=Inputs!$B$" + str(row))
        row += 1

    row += 1
    ws.merge_range(row - 1, 0, row - 1, 3, "Расчётные параметры", fmt["section"])
    row += 1
    for label, formula, name in [
        ("Hard cost, ₽", "=inp_gross_area_sqm*inp_construction_cost_rub_sqm", "hard_cost"),
        ("Soft cost, ₽", "=hard_cost*inp_soft_cost_pct", "soft_cost"),
        ("Contingency, ₽", "=hard_cost*inp_contingency_pct", "contingency"),
        ("Development cost, ₽", "=inp_land_cost_rub+hard_cost+soft_cost+contingency", "development_cost"),
        ("Горизонт модели, мес.", '=IF(model_strategy="sale",MAX(inp_construction_months+1,inp_sale_start_month+inp_sale_months+1),inp_construction_months+inp_hold_years*12+1)', "model_horizon"),
    ]:
        ws.write(row - 1, 0, label)
        ws.write_formula(row - 1, 1, formula, fmt["number"])
        book.define_name(name, "=Inputs!$B$" + str(row))
        row += 1
    ws.freeze_panes(7, 0)


def _operating(book: xlsxwriter.Workbook, req: CommercialRequest, fmt: dict[str, Any]) -> None:
    ws = book.add_worksheet("Operating")
    ws.hide_gridlines(2)
    ws.set_column("A:A", 36)
    ws.set_column("B:B", 20)
    ws.set_column("C:C", 30)
    ws.merge_range("A1:C1", _ASSETS[req.asset_type][1] + " · стабилизированная экономика", fmt["title"])
    ws.write_row("A3", ["Показатель", "Значение", "Комментарий"], fmt["header"])

    if req.asset_type == "office":
        rows = [
            ("Доходная площадь, м²", "=inp_income_area_sqm", "NLA", "op_area"),
            ("Аренда, ₽/м²/мес.", "=inp_rent_rub_sqm_month", "", "op_rent"),
            ("Загрузка", "=inp_occupancy_pct", "", "op_occupancy"),
            ("Валовая выручка, ₽/мес.", "=op_area*op_rent*op_occupancy", "", "op_revenue_month"),
            ("OPEX, ₽/мес.", "=op_revenue_month*inp_opex_pct", "", "op_cost_direct"),
            ("NOI, ₽/мес.", "=op_revenue_month-op_cost_direct", "", "op_noi_month"),
        ]
    elif req.asset_type == "retail":
        rows = [
            ("Доходная площадь, м²", "=inp_income_area_sqm", "GLA", "op_area"),
            ("Базовая аренда, ₽/м²/мес.", "=inp_rent_rub_sqm_month", "", "op_rent"),
            ("Оборот, ₽/м²/мес.", "=inp_sales_rub_sqm_month", "", "op_sales"),
            ("Загрузка", "=inp_occupancy_pct", "", "op_occupancy"),
            ("Базовая аренда, ₽/мес.", "=op_area*op_rent*op_occupancy", "", "op_base_rent"),
            ("Процент с оборота, ₽/мес.", "=op_area*op_sales*inp_turnover_rent_pct*op_occupancy", "", "op_turnover_rent"),
            ("Валовая выручка, ₽/мес.", "=MAX(op_base_rent,op_turnover_rent)", "Beta: большее из двух", "op_revenue_month"),
            ("OPEX, ₽/мес.", "=op_revenue_month*inp_opex_pct", "", "op_cost_direct"),
            ("NOI, ₽/мес.", "=op_revenue_month-op_cost_direct", "", "op_noi_month"),
        ]
    else:
        rows = [
            ("Номерной фонд, keys", "=inp_keys", "", "op_keys"),
            ("ADR, ₽", "=inp_adr_rub", "", "op_adr"),
            ("Загрузка", "=inp_occupancy_pct", "", "op_occupancy"),
            ("Room revenue, ₽/мес.", "=op_keys*op_adr*365/12*op_occupancy", "", "op_room_revenue"),
            ("Прочая выручка, ₽/мес.", "=op_room_revenue*inp_other_revenue_pct", "", "op_other_revenue"),
            ("Валовая выручка, ₽/мес.", "=op_room_revenue+op_other_revenue", "", "op_revenue_month"),
            ("OPEX, ₽/мес.", "=op_revenue_month*inp_opex_pct", "", "op_opex_month"),
            ("FF&E reserve, ₽/мес.", "=op_revenue_month*inp_ffe_reserve_pct", "", "op_ffe_month"),
            ("NOI, ₽/мес.", "=op_revenue_month-op_opex_month-op_ffe_month", "", "op_noi_month"),
            ("RevPAR, ₽", "=op_adr*op_occupancy", "", "op_revpar"),
        ]

    row = 4
    for label, formula, note, name in rows:
        ws.write(row - 1, 0, label)
        ws.write_formula(row - 1, 1, formula, fmt["percent"] if label == "Загрузка" else fmt["number"])
        ws.write(row - 1, 2, note, fmt["note"])
        book.define_name(name, "=Operating!$B$" + str(row))
        row += 1

    row += 1
    ws.write(row - 1, 0, "Стабилизированный NOI, ₽/год", fmt["total_label"])
    ws.write_formula(row - 1, 1, "=op_noi_month*12", fmt["total_money"])
    book.define_name("op_noi_annual", "=Operating!$B$" + str(row))

    row += 1
    ws.write(row - 1, 0, "Операционные затраты, ₽/мес.")
    ws.write_formula(row - 1, 1, "=op_revenue_month-op_noi_month", fmt["number"])
    book.define_name("op_cost_month", "=Operating!$B$" + str(row))

    row += 2
    ws.write(row - 1, 0, "Потенциал продажи, ₽", fmt["total_label"])
    sale_formula = "=inp_saleable_keys*inp_sale_price_rub_key" if req.asset_type == "hotel" else "=inp_saleable_area_sqm*inp_sale_price_rub_sqm"
    ws.write_formula(row - 1, 1, sale_formula, fmt["total_money"])
    book.define_name("sale_total", "=Operating!$B$" + str(row))


def _cashflow(book: xlsxwriter.Workbook, fmt: dict[str, Any], months: int = 180) -> None:
    ws = book.add_worksheet("Cash_Flow")
    ws.hide_gridlines(2)
    ws.freeze_panes(3, 2)
    ws.set_column("A:B", 10)
    ws.set_column("C:M", 17)
    ws.merge_range("A1:M1", "Помесячный денежный поток · beta", fmt["title"])
    ws.write_row("A3", [
        "Месяц", "Активен", "Development spend", "Operating revenue",
        "Sale revenue", "Terminal value", "Operating / selling cost",
        "Project CF", "Debt draw", "Interest", "Debt repayment",
        "Debt balance", "Equity CF",
    ], fmt["header"])

    first = 4
    last = first + months - 1
    for month in range(months):
        row = first + month
        previous_balance = "0" if month == 0 else "L" + str(row - 1)
        ws.write_number(row - 1, 0, month)
        ws.write_formula(row - 1, 1, "=--(A" + str(row) + "<model_horizon)")
        ws.write_formula(row - 1, 2, '=IF(B' + str(row) + '=0,0,IF(A' + str(row) + '=0,inp_land_cost_rub,IF(AND(A' + str(row) + '>=1,A' + str(row) + '<=inp_construction_months),(hard_cost+soft_cost+contingency)/MAX(1,inp_construction_months),0)))', fmt["money"])
        ramp = 'MIN(1,0.5+0.5*(A' + str(row) + '-inp_construction_months)/MAX(1,inp_stabilization_months))'
        ws.write_formula(row - 1, 3, '=IF(AND(B' + str(row) + '=1,model_strategy="income",A' + str(row) + '>inp_construction_months),op_revenue_month*' + ramp + ',0)', fmt["money"])
        ws.write_formula(row - 1, 4, '=IF(AND(B' + str(row) + '=1,model_strategy="sale",A' + str(row) + '>=inp_sale_start_month,A' + str(row) + '<inp_sale_start_month+inp_sale_months),sale_total/MAX(1,inp_sale_months),0)', fmt["money"])
        ws.write_formula(row - 1, 5, '=IF(AND(B' + str(row) + '=1,model_strategy="income",A' + str(row) + '=model_horizon-1),op_noi_annual/MAX(0.0001,inp_exit_cap_rate_pct),0)', fmt["money"])
        ws.write_formula(row - 1, 6, '=IF(model_strategy="income",IF(D' + str(row) + '=0,0,op_cost_month*' + ramp + '),E' + str(row) + '*inp_selling_cost_pct)', fmt["money"])
        ws.write_formula(row - 1, 7, '=D' + str(row) + '+E' + str(row) + '+F' + str(row) + '-C' + str(row) + '-G' + str(row), fmt["money"])
        ws.write_formula(row - 1, 8, '=IF(model_financing="equity_debt",C' + str(row) + '*inp_debt_share_pct,0)', fmt["money"])
        ws.write_formula(row - 1, 9, '=' + previous_balance + '*IF(model_financing="equity_debt",inp_debt_rate_pct/12,0)', fmt["money"])
        before_repay = '(' + previous_balance + '+I' + str(row) + ')'
        ws.write_formula(row - 1, 10, '=IF(model_financing<>"equity_debt",0,IF(model_strategy="sale",MIN(' + before_repay + ',E' + str(row) + '*inp_sales_cash_sweep_pct),IF(A' + str(row) + '=model_horizon-1,' + before_repay + ',0)))', fmt["money"])
        ws.write_formula(row - 1, 11, '=MAX(0,' + before_repay + '-K' + str(row) + ')', fmt["money"])
        ws.write_formula(row - 1, 12, '=H' + str(row) + '+I' + str(row) + '-J' + str(row) + '-I' + str(row) + '*inp_loan_fee_pct-K' + str(row), fmt["money"])

    ranges = {
        "cf_project": "H", "cf_debt_balance": "L", "cf_equity": "M",
        "cf_operating_revenue": "D", "cf_sale_revenue": "E", "cf_terminal": "F",
        "cf_operating_cost": "G", "cf_interest": "J", "cf_debt_draw": "I",
    }
    for name, col in ranges.items():
        book.define_name(name, "=Cash_Flow!$" + col + "$" + str(first) + ":$" + col + "$" + str(last))


def build_commercial_workbook(req: CommercialRequest) -> tuple[bytes, str, dict[str, Any]]:
    values = default_inputs(req.asset_type)
    values.update(req.inputs or {})
    result = calculate(req)

    output = io.BytesIO()
    book = xlsxwriter.Workbook(output, {"in_memory": True})
    book.set_properties({
        "title": "DevelopAid " + _ASSETS[req.asset_type][0] + " Model",
        "subject": "Non-residential beta underwriting",
        "author": "DevelopAid",
        "comments": "Commercial beta: no escrow.",
    })
    fmt = _formats(book)
    _summary(book, req, fmt)
    _inputs(book, req, values, fmt)
    _operating(book, req, fmt)
    _cashflow(book, fmt)
    book.close()

    filename = "DevelopAid_" + _ASSETS[req.asset_type][0] + "_Model_Beta.xlsx"
    return output.getvalue(), filename, {
        "asset_type": req.asset_type,
        "strategy": req.strategy,
        "financing_mode": req.financing_mode,
        "uses_escrow": False,
        "engine_kpi": result["kpi"],
    }
