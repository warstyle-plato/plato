"""Книга нежилого проекта: свои живые формулы и сверка с движком.

Владелец (04.10.2026): у нежилого проекта без ДДУ отчёт, тизер и книга —
самостоятельные. Книга v4 устроена вокруг ДДУ, эскроу и ПФ; здесь — объект на
аренде или прямой продаже со своим кредитом.

Методика — та же, что у движка (`developaid_nonres_strategy.object_flows`):
каждая колонка помесячной таблицы повторяет одну строку модуля формулой Excel,
и лист «Сверка» сравнивает итоги формул с итогами движка. Исходные данные,
которые книге не посчитать, приходят значениями и так и подписаны: CAPEX
объекта по месяцам и его доля общих затрат (их считает движок проекта) и
ключевая ставка сценария. Налог на прибыль, NPV и IRR проекта — тоже значения
движка: налог считается по проекту целиком, с переносом убытков.

Формулы — только IF/AND/OR/MIN/MAX/SUM/SUMIF/INT и степень, чтобы их считали
и Excel, и вычислитель в тестах.
"""

from __future__ import annotations

import io
from datetime import date
from typing import Any

from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill
from openpyxl.utils import get_column_letter

import developaid_nonres_strategy as ns

ENGINE_FILL = PatternFill("solid", fgColor="FFF3E0")
INPUT_FILL = PatternFill("solid", fgColor="FFFDE7")
BOLD = Font(bold=True)

FIRST_ROW = 60  # первая строка помесячной таблицы

# Вводные объекта: ключ → (строка, подпись).
INPUTS: dict[str, tuple[int, str]] = {
    "strategy": (2, "Стратегия (income — аренда, direct — прямая продажа)"),
    "area": (3, "Арендопригодная / продаваемая площадь, м²"),
    "spaces": (4, "Машино-места объекта (без гостевых), шт."),
    "rent": (5, "Ставка аренды, ₽/м²/мес. с НДС"),
    "parking_rent": (6, "Аренда машино-места, ₽/мес. с НДС"),
    "rent_index": (7, "Индексация аренды, доля в год"),
    "occ_start": (8, "Загрузка на открытии, доля"),
    "occ_stable": (9, "Стабильная загрузка, доля"),
    "leaseup": (10, "Срок заполнения, мес."),
    "opex": (11, "Операционные расходы, доля выручки (не более 0,95)"),
    "rev_mult": (12, "Множитель выручки сценария"),
    "property_tax": (13, "Налог на имущество, доля в год"),
    "vat": (14, "Ставка НДС"),
    "loan_share": (15, "Доля кредита в затратах"),
    "spread": (16, "Спред кредита к ключевой ставке"),
    "fee": (17, "Комиссия за выдачу, доля выборки"),
    "term": (18, "Срок кредита от первой выдачи, мес."),
    "balloon_share": (19, "Баллон, доля долга на ввод"),
    "hold": (20, "Срок удержания, мес."),
    "cap": (21, "Ставка капитализации выхода"),
    "exit_cost": (22, "Затраты на выход, доля"),
    "exit_mode": (23, "Выход (sale — продажа, hold — удержание)"),
    "repayment": (24, "Погашение (annuity / sweep / bullet)"),
    "comm": (25, "Месяц ввода — номер строки таблицы (k)"),
    "horizon": (26, "Конец горизонта объекта — номер строки (k)"),
    "price": (27, "Цена продажи, ₽/м² с НДС"),
    "parking_price": (28, "Цена машино-места, ₽"),
    "growth_pre": (29, "Рост цены до ввода, доля в месяц"),
    "growth_post": (30, "Рост цены после ввода, доля в месяц"),
    "price_start": (31, "Отсчёт цены — номер строки (k)"),
    "selling": (32, "Маркетинг и продажи, доля выручки"),
    "cost_mult": (33, "Множитель затрат сценария"),
    "sale_start": (34, "Старт прямых продаж — номер строки (k)"),
    "sale_months": (35, "Срок прямых продаж, мес."),
    "curve": (36, "Профиль продаж (flat / bell / front_loaded / back_loaded)"),
    "dep_years": (37, "Срок амортизации для налога, лет"),
}
DERIVED: dict[str, tuple[int, str]] = {
    "capex_total": (39, "CAPEX объекта, ₽ с НДС"),
    "basis": (40, "Стоимость объекта без НДС (база налога на имущество и амортизации)"),
    "first_draw": (41, "Первая выдача кредита — номер строки (k)"),
    "maturity": (42, "Срок погашения — номер строки (k)"),
    "comm_balance": (43, "Долг на ввод, ₽"),
    "balloon": (44, "Баллон, ₽"),
    "forward_noi": (45, "NOI следующих 12 мес. после срока удержания, ₽"),
    "exit_value": (46, "Стоимость выхода = NOI / ставка, ₽"),
    "stabilized_noi": (47, "Стабилизированный NOI, год, ₽"),
    "curve_sum": (48, "Сумма весов профиля продаж"),
    "peak": (49, "Пик долга, ₽"),
}

# Колонки помесячной таблицы: ключ → (буква, подпись).
COLUMNS: dict[str, tuple[str, str]] = {
    "k": ("A", "k"), "month": ("B", "Месяц"),
    "capex": ("C", "CAPEX объекта (движок)"), "common": ("D", "Общие затраты (движок)"),
    "key_rate": ("E", "Ключевая ставка (движок)"),
    "open": ("F", "Месяц эксплуатации"), "occ": ("G", "Загрузка"), "growth": ("H", "Индексация"),
    "rent": ("I", "Арендная выручка"), "opex": ("J", "OPEX"), "ptax": ("K", "Налог на имущество"),
    "weight": ("L", "Доля продаж месяца"), "factor": ("M", "Рост цены"),
    "sale": ("N", "Выручка прямых продаж"), "selling": ("O", "Расходы на продажу"),
    "exit": ("P", "Выход — продажа"), "exit_cost": ("Q", "Затраты на выход"),
    "residual": ("R", "Удержание — оценка"), "op_rev": ("S", "Выручка эксплуатации (без срока)"),
    "fwd": ("T", "NOI после срока удержания"), "stab": ("U", "NOI стабилизированного года"),
    "vat_charged": ("V", "НДС начисленный"), "vat_pre": ("W", "НДС к зачёту до расчёта"),
    "vat_paid": ("X", "НДС к уплате (− возмещение)"), "vat_credit": ("Y", "НДС к зачёту на конец"),
    "rate": ("Z", "Ставка кредита"), "bal_open": ("AA", "Долг на начало"),
    "interest": ("AB", "Проценты"), "int_cap": ("AC", "Проценты капитализированные"),
    "int_paid": ("AD", "Проценты уплаченные"), "draw": ("AE", "Выборка"), "fee": ("AF", "Комиссия"),
    "first_k": ("AG", "Служебная: выборка"), "bal_after": ("AH", "Долг после выборки"),
    "comm_bal": ("AI", "Служебная: долг на ввод"), "cash": ("AJ", "Деньги до погашения"),
    "repay": ("AK", "Погашение"), "annuity": ("AL", "Тело по аннуитету"),
    "amort": ("AM", "Плановое тело (для DSCR)"), "bal_close": ("AN", "Долг на конец"),
    "to_equity": ("AO", "Деньги объекта собственнику (без CAPEX)"),
    "year": ("AP", "Год эксплуатации"), "noi": ("AQ", "NOI"),
    "book_open": ("AR", "Остаточная стоимость на начало"), "recognized": ("AS", "Признано в расходах"),
    "book_close": ("AT", "Остаточная стоимость на конец"), "realized": ("AU", "Выручка ДКП к признанию"),
    "margin": ("AV", "Налоговая маржа объекта"),
}


def _c(name: str) -> str:
    return COLUMNS[name][0]


def _in(name: str) -> str:
    row = (INPUTS.get(name) or DERIVED[name])[0]
    return f"$B${row}"


def _month(text: str) -> date:
    return date.fromisoformat(str(text)[:10]).replace(day=1)


def _index(start: date, month: date) -> int:
    return (month.year - start.year) * 12 + month.month - start.month


def _row_formulas(r: int) -> dict[str, str]:
    """Формулы строки r — построчный пересказ `object_flows` языком Excel."""
    A = f"{_c('k')}{r}"
    prev = r - 1
    first = FIRST_ROW
    v = {name: f"{_c(name)}{r}" for name in COLUMNS}
    p = {name: f"{_c(name)}{prev}" for name in COLUMNS}
    vs = f"{_in('vat')}/(1+{_in('vat')})"
    income = f'{_in("strategy")}="income"'
    direct = f'{_in("strategy")}="direct"'
    opex_share = f"MIN(0.95,{_in('opex')})"
    base_price = f"({_in('area')}*{_in('price')}+{_in('spaces')}*{_in('parking_price')})"
    j = f"({A}-{_in('sale_start')}+1)"
    n = _in("sale_months")
    prev_weights = f"SUM({_c('weight')}${first}:{_c('weight')}{prev})" if r > first else "0"
    r12 = f"{v['rate']}/12"
    left = f"({_in('maturity')}-{A})"
    return {
        "open": f"=IF({A}>={_in('comm')},{A}-{_in('comm')}+1,0)",
        "occ": (f"=IF({v['open']}=0,0,MIN({_in('occ_start')},{_in('occ_stable')})"
                f"+({_in('occ_stable')}-MIN({_in('occ_start')},{_in('occ_stable')}))"
                f"*IF({_in('leaseup')}=1,1,MAX(0,MIN(1,({v['open']}-1)/({_in('leaseup')}-1)))))"),
        "growth": f"=(1+MAX(-0.95,{_in('rent_index')}))^(MAX(0,{v['open']}-1)/12)",
        "op_rev": (f"=({_in('area')}*{_in('rent')}+{_in('spaces')}*{_in('parking_rent')})"
                   f"*{v['growth']}*{v['occ']}*{_in('rev_mult')}"),
        "rent": f"=IF(AND({income},{v['open']}>=1,{v['open']}<={_in('hold')}),{v['op_rev']},0)",
        "opex": f"={v['rent']}*{opex_share}",
        "weight": (f"=IF(AND({direct},{j}>=1,{j}<={n}),IF({_in('curve')}=\"bell\",{j}*({n}+1-{j}),"
                   f"IF({_in('curve')}=\"front_loaded\",{n}+1-{j},IF({_in('curve')}=\"back_loaded\",{j},1)))"
                   f"/{_in('curve_sum')},0)"),
        "ptax": (f"=IF({income},IF(AND({v['open']}>=1,{v['open']}<={_in('hold')}),"
                 f"{_in('basis')}*{_in('property_tax')}/12,0),"
                 f"IF(AND({A}>={_in('comm')},{A}<={_in('horizon')}),"
                 f"{_in('basis')}*{_in('property_tax')}/12*MAX(0,1-{prev_weights}),0))"),
        "factor": (f"=(1+{_in('growth_pre')})^MAX(0,MIN({A}-{_in('price_start')},"
                   f"{_in('comm')}-{_in('price_start')}))"
                   f"*(1+{_in('growth_post')})^MAX(0,{A}-MAX({_in('price_start')},{_in('comm')}))"),
        "sale": f"={base_price}*{v['factor']}*{v['weight']}*{_in('rev_mult')}",
        "selling": f"={base_price}*{v['factor']}*{v['weight']}*{_in('selling')}*{_in('cost_mult')}",
        "exit": f'=IF(AND({income},{_in("exit_mode")}="sale",{A}={_in("horizon")}),{_in("exit_value")},0)',
        "exit_cost": f"={v['exit']}*{_in('exit_cost')}",
        "residual": f'=IF(AND({income},{_in("exit_mode")}="hold",{A}={_in("horizon")}),{_in("exit_value")},0)',
        "fwd": (f"=IF(AND({v['open']}>={_in('hold')}+1,{v['open']}<={_in('hold')}+12),"
                f"{v['op_rev']}*(1-{opex_share}),0)"),
        "stab": (f"=IF(AND({v['open']}>={_in('leaseup')},{v['open']}<={_in('leaseup')}+11),"
                 f"{v['op_rev']}*(1-{opex_share}),0)"),
        "vat_charged": f"=IF({A}>{_in('horizon')},0,({v['sale']}+{v['rent']}+{v['exit']})*{vs})",
        "vat_pre": (f"=IF({A}>{_in('horizon')},0,{p['vat_credit'] if r > first else '0'}"
                    f"+{v['capex']}*{vs}-{v['vat_charged']})"),
        "vat_paid": (f"=IF(AND({A}={_in('comm')},{v['vat_pre']}>0),-{v['vat_pre']},"
                     f"IF({v['vat_pre']}<0,-{v['vat_pre']},0))"),
        "vat_credit": f"={v['vat_pre']}+{v['vat_paid']}",
        "rate": f"={v['key_rate']}+{_in('spread')}",
        "bal_open": f"={p['bal_close'] if r > first else '0'}",
        "interest": f"={v['bal_open']}*{v['rate']}/12",
        "int_cap": f"=IF({A}<{_in('comm')},{v['interest']},0)",
        "int_paid": f"=IF({A}>={_in('comm')},{v['interest']},0)",
        "draw": f"=IF({A}<={_in('comm')},({v['capex']}+{v['common']})*{_in('loan_share')},0)",
        "fee": f"={v['draw']}*{_in('fee')}",
        "first_k": f"=IF({v['draw']}>0,{A},1000000)",
        "bal_after": f"={v['bal_open']}+{v['int_cap']}+{v['draw']}",
        "comm_bal": f"=IF({A}={_in('comm')},{v['bal_after']},0)",
        "cash": (f"={v['sale']}+{v['rent']}+{v['exit']}-{v['selling']}-{v['opex']}-{v['ptax']}"
                 f"-{v['exit_cost']}-{v['vat_paid']}-{v['int_paid']}"),
        "annuity": (f"=IF(AND({A}>{_in('comm')},{A}<{_in('maturity')}),"
                    f"IF({v['rate']}>0,MIN({v['bal_after']},MAX(0,({v['bal_after']}-{_in('balloon')}"
                    f"/(1+{r12})^{left})*({r12})/(1-(1+{r12})^(-{left}))-{v['interest']})),"
                    f"MIN({v['bal_after']},MAX(0,({v['bal_after']}-{_in('balloon')})/{left}))),0)"),
        "repay": (f"=IF({v['bal_after']}<=0,0,IF(OR({A}>={_in('comm')},{direct}),"
                  f"IF({A}={_in('horizon')},{v['bal_after']},"
                  f'IF(OR({_in("repayment")}="sweep",{direct}),MIN({v["bal_after"]},MAX(0,{v["cash"]})),'
                  f'IF({_in("repayment")}="annuity",IF({A}={_in("comm")},'
                  f"IF({_in('maturity')}<={_in('comm')},{v['bal_after']},0),"
                  f"IF({A}>={_in('maturity')},{v['bal_after']},{v['annuity']})),0))),0))"),
        "amort": (f'=IF(AND({income},{_in("repayment")}="annuity",{A}>{_in("comm")},'
                  f"{A}<{_in('maturity')},{A}<>{_in('horizon')}),{v['repay']},0)"),
        "bal_close": f"={v['bal_after']}-{v['repay']}",
        "to_equity": (f"={v['sale']}+{v['rent']}+{v['exit']}+{v['residual']}-{v['selling']}"
                      f"-{v['opex']}-{v['ptax']}-{v['exit_cost']}-{v['vat_paid']}-{v['int_paid']}"
                      f"-{v['fee']}+{v['draw']}-{v['repay']}"),
        "year": f"=IF(AND({v['open']}>=1,{v['open']}<={_in('hold')}),INT(({v['open']}-1)/12)+1,0)",
        "noi": f"={v['rent']}-{v['opex']}-{v['ptax']}",
        "book_open": f"={p['book_close'] if r > first else _in('basis')}",
        "recognized": (f"=IF({A}>{_in('horizon')},0,IF({direct},"
                       f"IF({A}<{_in('comm')},0,IF({A}={_in('comm')},"
                       f"SUM({_c('weight')}${first}:{_c('weight')}{r}),{v['weight']}))*{_in('basis')},"
                       f"IF({A}>={_in('comm')},IF(AND({v['exit']}>0,{A}={_in('horizon')}),{v['book_open']},"
                       f"MIN({v['book_open']},{_in('basis')}/({_in('dep_years')}*12))),0)))"),
        "book_close": f"={v['book_open']}-{v['recognized']}",
        "realized": (f"=IF({A}<{_in('comm')},0,IF({A}={_in('comm')},"
                     f"SUM({_c('sale')}${first}:{_c('sale')}{r})-SUM({_c('vat_charged')}${first}:{_c('vat_charged')}{r}),"
                     f"{v['sale']}-{v['vat_charged']}))"),
        "margin": (f"=IF({A}>{_in('horizon')},0,IF({direct},{v['realized']}-{v['recognized']}"
                   f"-{v['selling']}-{v['ptax']},{v['sale']}+{v['rent']}+{v['exit']}-{v['vat_charged']}"
                   f"-{v['recognized']}-{v['selling']}-{v['opex']}-{v['ptax']}-{v['exit_cost']}))"),
    }


def _num(params: dict[str, Any], key: str, default: float) -> float:
    try:
        value = params.get(key)
        return default if value in (None, "") else float(value)
    except (TypeError, ValueError):
        return default


def _object_sheet(book: Workbook, item: dict[str, Any], title: str) -> dict[str, str]:
    """Лист объекта: вводные, помесячная таблица, итоги. Возвращает адреса итогов."""
    data = item["book"]
    params = data.get("params") or {}
    ws = book.create_sheet(title[:31])
    rows = data["months"]
    start = _month(rows[0]["month"])
    comm = _index(start, _month(data["commissioning"]))
    horizon = len(rows) - 1
    strategy = data["strategy"]
    sale_start = 0
    if strategy == ns.STRATEGY_DIRECT:
        sale_start = _index(start, ns.direct_sale_window({
            "commissioning": _month(data["commissioning"]), "params": params})[0])
    hold_years = max(1, int(_num(params, "hold_years", 5)))
    values: dict[str, Any] = {
        "strategy": strategy,
        "area": data["area_sqm"], "spaces": data["parking_spaces"],
        "rent": _num(params, "rent_th_per_sqm_month", 0.0) * 1000.0,
        "parking_rent": _num(params, "parking_rent_th_month", 0.0) * 1000.0,
        "rent_index": _num(params, "rent_index_pct", 0.0) / 100.0,
        "occ_start": min(1.0, max(0.0, _num(params, "occupancy_start_pct", 0.0) / 100.0)),
        "occ_stable": min(1.0, max(0.0, _num(params, "occupancy_stable_pct", 0.0) / 100.0)),
        "leaseup": max(1, int(_num(params, "leaseup_months", 12))),
        "opex": max(0.0, _num(params, "opex_pct", 0.0) / 100.0),
        "rev_mult": data["revenue_multiplier"],
        "property_tax": max(0.0, _num(params, "property_tax_pct", 2.2) / 100.0),
        "vat": data["vat_rate"],
        "loan_share": min(0.95, max(0.0, _num(params, "loan_share_pct", 60.0) / 100.0)),
        "spread": _num(params, "loan_spread_pp", 4.0) / 100.0,
        "fee": max(0.0, _num(params, "loan_fee_pct", 1.0) / 100.0),
        "term": max(1, int(_num(params, "loan_term_years", 10))) * 12,
        "balloon_share": min(1.0, max(0.0, _num(params, "loan_balloon_pct", 20.0) / 100.0)),
        "hold": hold_years * 12,
        "cap": _num(params, "exit_cap_pct", 11.0) / 100.0,
        "exit_cost": max(0.0, _num(params, "exit_cost_pct", 1.0) / 100.0),
        "exit_mode": (str(params.get("exit_mode") or "").strip().lower()
                      if str(params.get("exit_mode") or "").strip().lower() in (ns.EXIT_SALE, ns.EXIT_HOLD)
                      else ns.EXIT_SALE),
        "repayment": (str(params.get("debt_repayment") or "").strip().lower()
                      if str(params.get("debt_repayment") or "").strip().lower() in ns.REPAYMENTS
                      else ns.REPAY_ANNUITY),
        "comm": comm, "horizon": horizon,
        "price": data["price_rub_sqm"], "parking_price": data["parking_price_rub"],
        "growth_pre": data["growth_pre"], "growth_post": data["growth_post"],
        "price_start": _index(start, _month(data["price_start"])),
        "selling": data["selling_share"], "cost_mult": data["cost_multiplier"],
        "sale_start": sale_start,
        "sale_months": max(1, int(_num(params, "direct_sale_months", 12))),
        "curve": (str(params.get("direct_sale_curve") or "").strip().lower()
                  if str(params.get("direct_sale_curve") or "").strip().lower() in ns.SALE_CURVES
                  else "flat"),
        "dep_years": max(1, int(_num(params, "depreciation_years", 30))),
    }
    ws["A1"] = f"{data.get('title') or ''} — {ns.STRATEGY_LABELS.get(strategy, strategy)}"
    ws["A1"].font = BOLD
    for name, (row, label) in INPUTS.items():
        ws[f"A{row}"] = label
        ws[f"B{row}"] = values[name]
        ws[f"B{row}"].fill = INPUT_FILL
    last = FIRST_ROW + len(rows) - 1 + 12  # +12 месяцев для NOI после удержания
    col = lambda name: f"{_c(name)}${FIRST_ROW}:{_c(name)}${last}"  # noqa: E731
    n = _in("sale_months")
    derived = {
        "capex_total": f"=SUM({col('capex')})",
        "basis": f"={_in('capex_total')}*(1-{_in('vat')}/(1+{_in('vat')}))",
        "first_draw": f"=MIN({col('first_k')})",
        "maturity": f"=MAX(IF({_in('first_draw')}<1000000,{_in('first_draw')},{_in('comm')})+{_in('term')},{_in('comm')})",
        # Прямая ссылка на строку ввода: сумма по столбцу замкнула бы цикл —
        # строки после ввода сами читают баллон.
        "comm_balance": f"={_c('bal_after')}{FIRST_ROW + comm}",
        "balloon": f"={_in('comm_balance')}*{_in('balloon_share')}",
        "forward_noi": f'=IF({_in("strategy")}="income",SUM({col("fwd")})-{_in("basis")}*{_in("property_tax")},0)',
        "exit_value": f"=IF(AND({_in('cap')}>0,{_in('forward_noi')}>0),{_in('forward_noi')}/{_in('cap')},0)",
        "stabilized_noi": f'=IF({_in("strategy")}="income",SUM({col("stab")})-{_in("basis")}*{_in("property_tax")},0)',
        "curve_sum": (f'=IF({_in("curve")}="bell",{n}*({n}+1)*({n}+2)/6,'
                      f'IF(OR({_in("curve")}="front_loaded",{_in("curve")}="back_loaded"),{n}*({n}+1)/2,{n}))'),
        "peak": f"=MAX({col('bal_close')})",
    }
    for name, (row, label) in DERIVED.items():
        ws[f"A{row}"] = label
        ws[f"B{row}"] = derived[name]
    head = FIRST_ROW - 1
    for name, (letter, label) in COLUMNS.items():
        ws[f"{letter}{head}"] = label
        ws[f"{letter}{head}"].font = BOLD
    for name in ("capex", "common", "key_rate"):
        ws[f"{_c(name)}{head - 1}"] = "СЧИТАЕТ ДВИЖОК"
    for i in range(len(rows) + 12):
        r = FIRST_ROW + i
        source = rows[i] if i < len(rows) else {}
        ws[f"A{r}"] = i
        ws[f"B{r}"] = str(source.get("month") or "")[:7]
        for name in ("capex", "common", "key_rate"):
            ws[f"{_c(name)}{r}"] = float(source.get(name, 0.0) or 0.0)
            ws[f"{_c(name)}{r}"].fill = ENGINE_FILL
        for name, formula in _row_formulas(r).items():
            # До ввода (и в сам месяц ввода) аннуитета нет. Формула там всё
            # равно ссылалась бы на баллон, а баллон — на долг месяца ввода,
            # который читает эти строки: Excel видит такую ссылку циклом,
            # даже если условие её не исполняет.
            if name == "annuity" and i <= comm:
                formula = 0
            ws[f"{_c(name)}{r}"] = formula
    for i in range(1, len(COLUMNS) + 1):
        ws.column_dimensions[get_column_letter(i)].width = 16
    ws.column_dimensions["A"].width = 58

    # Годы удержания: NOI, проценты, плановое тело, DSCR и ICR — формулами.
    years_row = last + 3
    ws[f"A{years_row}"] = "Год эксплуатации"
    ws[f"B{years_row}"] = "NOI"
    ws[f"C{years_row}"] = "Проценты"
    ws[f"D{years_row}"] = "Плановое тело"
    ws[f"E{years_row}"] = "DSCR"
    ws[f"F{years_row}"] = "ICR"
    for y in range(1, hold_years + 1):
        r = years_row + y
        ws[f"A{r}"] = y
        ws[f"B{r}"] = f"=SUMIF({col('year')},A{r},{col('noi')})"
        ws[f"C{r}"] = f"=SUMIF({col('year')},A{r},{col('int_paid')})"
        ws[f"D{r}"] = f"=SUMIF({col('year')},A{r},{col('amort')})"
        ws[f"E{r}"] = f'=IF(C{r}>0,B{r}/(C{r}+D{r}),"")'
        ws[f"F{r}"] = f'=IF(C{r}>0,B{r}/C{r},"")'
    span = f"{years_row + 1}:{years_row + hold_years}"
    first_y, last_y = span.split(":")
    totals = {
        "revenue": f"=SUM({col('sale')})+SUM({col('rent')})+SUM({col('exit')})+SUM({col('residual')})",
        "rent_revenue": f"=SUM({col('rent')})", "sale_revenue": f"=SUM({col('sale')})",
        "exit_revenue": f"=SUM({col('exit')})", "residual_value": f"=SUM({col('residual')})",
        "opex": f"=SUM({col('opex')})", "property_tax": f"=SUM({col('ptax')})",
        "selling_cost": f"=SUM({col('selling')})", "exit_cost": f"=SUM({col('exit_cost')})",
        "vat_paid": f"=SUM({col('vat_paid')})", "loan_draw": f"=SUM({col('draw')})",
        "loan_interest": f"=SUM({col('int_cap')})+SUM({col('int_paid')})",
        "loan_fee": f"=SUM({col('fee')})", "loan_repayment": f"=SUM({col('repay')})",
        "loan_peak": f"={_in('peak')}", "tax_margin": f"=SUM({col('margin')})",
        "noi": f"=IF({_in('strategy')}=\"income\",SUM({col('noi')}),0)",
        "exit_value": f"={_in('exit_value')}", "stabilized_noi": f"={_in('stabilized_noi')}",
        "dscr_min": f'=IF(COUNT(E{first_y}:E{last_y})>0,MIN(E{first_y}:E{last_y}),"")',
    }
    out: dict[str, str] = {}
    totals_row = years_row + hold_years + 3
    ws[f"A{totals_row}"] = "Итоги объекта (формулы книги)"
    ws[f"A{totals_row}"].font = BOLD
    for i, (name, formula) in enumerate(totals.items(), start=1):
        r = totals_row + i
        ws[f"A{r}"] = name
        ws[f"B{r}"] = formula
        out[name] = f"'{ws.title}'!$B${r}"
    return out


# Что сверяется: итог книги → (подпись, где лежит у движка).
CHECKS: tuple[tuple[str, str, str], ...] = (
    ("revenue", "Выручка объекта", "totals"),
    ("rent_revenue", "Арендная выручка", "totals"),
    ("sale_revenue", "Выручка прямых продаж", "totals"),
    ("exit_revenue", "Выход — продажа", "totals"),
    ("residual_value", "Удержание — оценка", "totals"),
    ("opex", "OPEX", "totals"),
    ("property_tax", "Налог на имущество", "totals"),
    ("selling_cost", "Расходы на продажу", "totals"),
    ("exit_cost", "Затраты на выход", "totals"),
    ("vat_paid", "НДС к уплате", "totals"),
    ("loan_draw", "Кредит — выборка", "totals"),
    ("loan_interest", "Кредит — проценты", "totals"),
    ("loan_fee", "Кредит — комиссия", "totals"),
    ("loan_repayment", "Кредит — погашение", "totals"),
    ("loan_peak", "Кредит — пик долга", "totals"),
    ("noi", "NOI за срок удержания", "totals"),
    ("tax_margin", "Налоговая маржа объекта", "totals"),
    ("exit_value", "Стоимость выхода", "kpi"),
    ("stabilized_noi", "Стабилизированный NOI", "kpi"),
    ("dscr_min", "DSCR — минимум", "kpi"),
)
TOLERANCE_SHARE = 1e-6


def build(result: dict[str, Any], project_name: str = "") -> bytes:
    """Книга нежилого проекта из посчитанного движком результата."""
    finance = result.get("finance") or {}
    summary = result.get("summary") or {}
    objects = [o for o in (finance.get("nonres") or {}).get("objects") or [] if o.get("book")]
    book = Workbook()
    head = book.active
    head.title = "Свод"
    head["A1"] = f"DevelopAid · нежилой проект{(' · ' + project_name) if project_name else ''}"
    head["A1"].font = BOLD
    head["A2"] = ("Объекты считаются формулами на своих листах; проектные итоги ниже — "
                  "СЧИТАЕТ ДВИЖОК (налог на прибыль по проекту с переносом убытков, NPV, IRR).")
    project_rows = (
        ("Выручка проекта", summary.get("revenue")),
        ("Расходы всего", summary.get("total_expenses")),
        ("EBITDA", summary.get("ebitda")),
        ("Налог на прибыль", summary.get("profit_tax")),
        ("НДС", finance.get("vat")),
        ("Чистая прибыль", summary.get("net_profit")),
        ("NPV", summary.get("npv")),
        ("IRR собственного капитала", summary.get("irr_equity")),
    )
    for i, (label, value) in enumerate(project_rows, start=4):
        head[f"A{i}"] = label
        head[f"B{i}"] = float(value or 0.0)
        head[f"B{i}"].fill = ENGINE_FILL
        head[f"C{i}"] = "СЧИТАЕТ ДВИЖОК"
    head.column_dimensions["A"].width = 46
    head.column_dimensions["B"].width = 22

    checks = book.create_sheet("Сверка")
    checks["A1"] = "Сверка формул книги с движком"
    checks["A1"].font = BOLD
    checks.append(["Объект", "Показатель", "Книга", "Движок", "Разница", "Допуск", "Итог"])
    for number, item in enumerate(objects, start=1):
        refs = _object_sheet(book, item, f"Объект {number}")
        for key, label, where in CHECKS:
            engine = (item.get(where) or {}).get(key)
            row = checks.max_row + 1
            checks[f"A{row}"] = item.get("title") or item.get("key")
            checks[f"B{row}"] = label
            checks[f"C{row}"] = f"={refs[key]}"
            checks[f"D{row}"] = float(engine) if engine is not None else ""
            checks[f"D{row}"].fill = ENGINE_FILL
            checks[f"E{row}"] = f'=IF(D{row}="","",C{row}-D{row})'
            checks[f"F{row}"] = f'=IF(D{row}="","",MAX(1,ABS(D{row})*{TOLERANCE_SHARE}))'
            checks[f"G{row}"] = f'=IF(D{row}="","—",IF(ABS(E{row})<=F{row},"сходится","РАСХОЖДЕНИЕ"))'
    last = checks.max_row
    checks["I2"] = "Вердикт"
    checks["I3"] = f'=IF(COUNTIF(G3:G{last},"РАСХОЖДЕНИЕ")=0,"ПРОЙДЕНО","ЕСТЬ РАСХОЖДЕНИЯ")'
    for letter, width in (("A", 22), ("B", 30), ("C", 20), ("D", 20), ("E", 14), ("F", 12), ("G", 14)):
        checks.column_dimensions[letter].width = width
    stream = io.BytesIO()
    book.save(stream)
    return stream.getvalue()
