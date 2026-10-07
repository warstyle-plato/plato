"""Книга гостиничного проекта: живые формулы, годовой USALI, итоги и сверка.

Решения владельца (05.10.2026): шаг расчёта — месяц, как у движка; в книге
дополнительно годовой лист USALI; итоги — как «Контр_панель» эталонных
моделей (NPV, IRR, PBP, DPBP); лист «Сверка» сравнивает формулы книги с
движком.

Методика — та же, что у движка (`developaid_hotel_strategy.hotel_flows`):
каждая колонка листа «Расчёт» повторяет одну строку модуля формулой Excel —
номера, департаменты, USALI, износ и налог на имущество, возмещение НДС,
кредит (обычный или льготный, лимит, отсрочка, аннуитет / под DSCR / весь
поток), налог на прибыль с переносом убытка (половинное ограничение, как у
движка), потоки проекта и капитала. Значениями приходят только данные,
которых книге не посчитать, и так и подписаны: затраты проекта по месяцам и их
части (мебель, участок) — CAPEX считает движок; ключевая ставка сценария;
число дней месяца (календарь). IRR — значение движка, а книга проверяет его
формулой: NPV потока при этой ставке равен нулю.

Формулы — только IF/AND/OR/MIN/MAX/SUM/SUMIF/COUNT/COUNTIF/ABS и степень,
чтобы их считали и Excel, и вычислитель в тестах.
"""

from __future__ import annotations

import io
from datetime import date
from typing import Any

from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill
from openpyxl.utils import get_column_letter

import developaid_hotel_strategy as hs
from developaid_finance_math import LOSS_CARRY_USE_LIMIT

ENGINE_FILL = PatternFill("solid", fgColor="FFF3E0")
INPUT_FILL = PatternFill("solid", fgColor="FFFDE7")
BOLD = Font(bold=True)

INPUTS_SHEET = "Вводные"
CALC_SHEET = "Расчёт"
USALI_SHEET = "USALI по годам"
TOTALS_SHEET = "Итоги"
CHECK_SHEET = "Сверка"
FIRST_ROW = 6  # первая строка помесячной таблицы на листе «Расчёт»
NO_DRAW = 1_000_000  # «выдачи не было» — номер строки, которого нет

# Модельные величины листа «Вводные» (столбец C): ключ → подпись.
MODEL: tuple[tuple[str, str], ...] = (
    ("keys", "Номерной фонд, номеров"),
    ("adr", "ADR на дату цены, ₽ без НДС"),
    ("price_k", "Дата цены ADR — номер строки расчёта (k)"),
    ("index", "Индексация ADR, доля в год"),
    ("occ_start", "Стартовая загрузка, доля"),
    ("occ_target", "Целевая загрузка, доля"),
    ("ramp", "Выход на целевую загрузку, мес."),
    ("fnb", "F&B, доля выручки номеров"),
    ("other", "Прочие департаменты, доля выручки номеров и F&B"),
    ("rooms_cost", "Расходы номерного фонда, доля"),
    ("fnb_cost", "Расходы F&B, доля"),
    ("other_cost", "Расходы прочих департаментов, доля"),
    ("ag", "A&G, доля выручки"),
    ("sm", "S&M, доля выручки"),
    ("pom", "POM, доля выручки"),
    ("util", "Utilities, доля выручки"),
    ("base_fee", "Базовое вознаграждение оператора, доля выручки"),
    ("incentive", "Поощрительное вознаграждение, доля GOP"),
    ("reserve", "Резерв FF&E, доля выручки"),
    ("relief_months", "Льгота НДС на проживание, мес. с ввода"),
    ("rev_mult", "Множитель выручки сценария"),
    ("vat", "Ставка НДС"),
    ("property_rate", "Налог на имущество, доля в год"),
    ("insurance_rate", "Страхование, доля CAPEX без НДС в год"),
    ("building_months", "Амортизация здания, мес."),
    ("ffe_months", "Амортизация мебели и оборудования, мес."),
    ("financing", "Финансирование (commercial / preferential / none)"),
    ("loan_share", "Доля кредита в затратах"),
    ("spread", "Спред обычного кредита к КС"),
    ("pref_share", "Льготный: доля ключевой ставки"),
    ("pref_margin", "Льготный: маржа"),
    ("limit_on", "Лимит кредита задан (1 / 0)"),
    ("limit", "Лимит кредита, ₽"),
    ("fee", "Комиссия за выдачу, доля"),
    ("term", "Срок кредита от первой выдачи, мес."),
    ("grace", "Отсрочка тела от первой выдачи, мес."),
    ("repayment", "Погашение (annuity / sculpted / sweep)"),
    ("dscr", "Целевой DSCR (погашение «под DSCR»)"),
    ("exit_mode", "Конец срока (sale / hold)"),
    ("valuation", "Оценка выхода (cap_rate / ev_ebitda)"),
    ("cap", "Ставка капитализации"),
    ("multiple", "Мультипликатор EV/EBITDA"),
    ("exit_cost", "Затраты на продажу, доля"),
    ("tax_rate", "Налог на прибыль"),
    ("loss_limit", "Зачёт убытка прошлых лет, не более доли базы"),
    ("discount", "Ставка дисконтирования"),
    ("comm", "Ввод — номер строки расчёта (k)"),
    ("horizon", "Конец срока — номер строки расчёта (k)"),
)
DERIVED: tuple[tuple[str, str], ...] = (
    ("vs", "Доля НДС в сумме с НДС"),
    ("capex_total", "Затраты проекта за срок, ₽ с НДС"),
    ("land_total", "Участок и ВРИ, ₽ (без НДС, без амортизации)"),
    ("ffe_total", "Мебель и оборудование, ₽ с НДС"),
    ("capex_vat", "НДС в затратах, ₽"),
    ("capex_net", "Затраты без НДС, ₽"),
    ("ffe_net", "Мебель и оборудование без НДС, ₽"),
    ("building_net", "Здание без НДС, ₽ (база налога на имущество)"),
    ("insurance_month", "Страхование в месяц, ₽"),
    ("first_draw", "Первая выдача кредита — k"),
    ("maturity", "Срок кредита — k"),
    ("amort_start", "Начало погашения тела — k"),
    ("forward_ebitda", "EBITDA 12 месяцев после срока, ₽"),
    ("exit_value", "Стоимость гостиницы на выходе, ₽"),
    ("peak", "Пик долга, ₽"),
    ("rate_m", "Месячная ставка дисконтирования проекта (как NPV движка)"),
)
_ROWS: dict[str, int] = {key: 4 + i for i, (key, _) in enumerate(MODEL)}
_ROWS.update({key: 4 + len(MODEL) + 2 + i for i, (key, _) in enumerate(DERIVED)})

# Колонки листа «Расчёт»: ключ → подпись. Буквы — по порядку.
_COLUMN_LIST: tuple[tuple[str, str], ...] = (
    ("k", "k"), ("month", "Месяц"), ("year", "Год (календарь)"), ("days", "Дней (календарь)"),
    ("capex", "Затраты, ₽ с НДС (движок)"), ("capex_ffe", "в т.ч. FF&E (движок)"),
    ("capex_land", "в т.ч. участок и ВРИ (движок)"), ("key_rate", "Ключевая ставка (движок)"),
    ("in_h", "В сроке расчёта"), ("year_h", "Год в сроке"),
    ("open", "Месяц работы"), ("occ", "Загрузка"), ("growth", "Индекс ADR"), ("adr", "ADR"),
    ("avail", "Номеро-ночи в продаже"), ("sold", "Проданные номеро-ночи"),
    ("rooms", "Выручка номеров"), ("fnb", "Выручка F&B"), ("other", "Выручка прочих"),
    ("dept", "Выручка департаментов"), ("relief", "Льгота НДС на проживание"),
    ("rooms_exp", "Расходы НФ"), ("fnb_exp", "Расходы F&B"), ("other_exp", "Расходы прочих"),
    ("ag", "A&G"), ("sm", "S&M"), ("pom", "POM"), ("util", "Utilities"), ("gop", "GOP"),
    ("base_fee", "Базовое вознаграждение"), ("incentive", "Поощрительное вознаграждение"),
    ("reserve", "Резерв FF&E"),
    ("book_b_open", "Здание: стоимость на начало"), ("dep_b", "Здание: износ"),
    ("book_b_close", "Здание: стоимость на конец"), ("book_f_open", "FF&E: стоимость на начало"),
    ("dep_f", "FF&E: износ"), ("book_f_close", "FF&E: стоимость на конец"),
    ("ptax", "Налог на имущество"), ("ins", "Страхование"),
    ("revenue", "Выручка всего"), ("opex", "Расходы USALI"), ("ebitda", "EBITDA"),
    ("exit", "Выход — продажа"), ("exit_cost", "Затраты на продажу"),
    ("residual", "Удержание — оценка"),
    ("vatin", "НДС в затратах месяца"), ("refund", "Возмещение НДС стройки"),
    ("rate", "Ставка кредита"), ("bal_open", "Долг на начало"), ("interest", "Проценты"),
    ("int_cap", "Проценты капитализированные"), ("int_paid", "Проценты уплаченные"),
    ("want", "Нужно кредита"), ("cum_prev", "Выдано до месяца"), ("draw", "Выдача"),
    ("cum_draw", "Выдано всего"), ("fee", "Комиссия"), ("first_k", "Служебная: выдача"),
    ("bal_after", "Долг после выдачи"), ("prepay", "Возмещение НДС в погашение"),
    ("bal_pre", "Долг до погашения"), ("annuity", "Тело по аннуитету"),
    ("sched", "Плановое погашение тела"),
    ("free", "Свободные деньги после процентов и налога"),
    ("res_open", "Удержано в проекте на начало"),
    ("sweep", "Погашение удержанными деньгами"),
    ("repay", "Погашение тела"), ("repay_total", "Погашение всего"),
    ("bal_close", "Долг на конец"),
    ("res_close", "Удержано в проекте на конец"), ("retained", "Удержано за месяц"),
    ("amort", "Плановое тело (для DSCR)"),
    ("dep", "Амортизация"), ("margin", "Налоговая маржа"), ("fin_ded", "Проценты и комиссии к вычету"),
    ("def_acc", "Расходы до ввода, к году ввода"), ("newyear", "Новый налоговый год"),
    ("prior", "Убыток прошлых лет"), ("yres", "Результат года нарастающим"),
    ("used", "Зачтено убытка"), ("base", "База налога"), ("ypaid_prev", "Налог года до месяца"),
    ("tax", "Налог на прибыль"), ("ypaid", "Налог года с месяцем"),
    ("vat_paid", "НДС к уплате (− возмещение)"), ("operating", "Деньги эксплуатации"),
    ("to_equity", "Деньги собственнику без CAPEX"), ("project_cf", "Поток проекта"),
    ("equity_cf", "Поток капитала"), ("fcff", "Поток до финансирования"),
    ("disc_p", "Поток проекта, дисконт."), ("disc_e", "Поток капитала, дисконт."),
    ("irr_p", "Поток проекта при IRR движка"), ("irr_e", "Поток капитала при IRR движка"),
    ("cum_p", "Поток проекта нарастающим"), ("cross_p", "Окупаемость: месяц перехода"),
    ("cum_dp", "Дисконт. поток нарастающим"), ("cross_dp", "DPBP: месяц перехода"),
)
COLUMNS: dict[str, tuple[str, str]] = {
    key: (get_column_letter(i), label) for i, (key, label) in enumerate(_COLUMN_LIST, start=1)}


def _c(name: str) -> str:
    return COLUMNS[name][0]


def _in(name: str) -> str:
    return f"'{INPUTS_SHEET}'!$C${_ROWS[name]}"


def _month(text: str) -> date:
    return date.fromisoformat(str(text)[:10]).replace(day=1)


def _index(start: date, month: date) -> int:
    return (month.year - start.year) * 12 + month.month - start.month


def _num(params: dict[str, Any], key: str) -> float:
    value = params.get(key)
    try:
        return 0.0 if value in (None, "") else float(value)
    except (TypeError, ValueError):
        return 0.0


def _row_formulas(r: int, irr_project: float | None, irr_equity: float | None
                  ) -> dict[str, str]:
    """Формулы строки r — построчный пересказ `hotel_flows` языком Excel."""
    first = FIRST_ROW
    A = f"{_c('k')}{r}"
    v = {name: f"{_c(name)}{r}" for name in COLUMNS}
    p = {name: f"{_c(name)}{r - 1}" for name in COLUMNS}
    has_prev = r > first

    def prev(name: str, default: str = "0") -> str:
        return p[name] if has_prev else default

    i = _in
    open_ = v["open"]
    r12 = f"{v['rate']}/12"
    left = f"({i('maturity')}-{A})"
    refund_window = f"{_c('vatin')}{max(first, r - 3)}:{_c('vatin')}{r}"
    refund_lag = f"{_c('vatin')}{r - 3}" if r - 3 >= first else "0"
    irr_p = "0" if irr_project is None else f"((1+{irr_project!r})^(1/12)-1)"
    irr_e = "0" if irr_equity is None else f"((1+{irr_equity!r})^(1/12)-1)"
    return {
        "in_h": f"=IF({A}<={i('horizon')},1,0)",
        "year_h": f"=IF({v['in_h']}=1,{v['year']},0)",
        "open": f"=IF({A}>={i('comm')},{A}-{i('comm')}+1,0)",
        "occ": (f"=IF({open_}=0,0,IF({i('ramp')}=0,{i('occ_target')},{i('occ_start')}"
                f"+({i('occ_target')}-{i('occ_start')})*MAX(0,MIN(1,({open_}-1)/{i('ramp')}))))"),
        "growth": f"=(1+MAX(-0.95,{i('index')}))^(({A}-{i('price_k')})/12)",
        "adr": f"={i('adr')}*{v['growth']}",
        "avail": f"=IF({open_}>0,{i('keys')}*{v['days']},0)",
        "sold": f"={v['avail']}*{v['occ']}",
        "rooms": f"={v['sold']}*{v['adr']}*{i('rev_mult')}",
        "fnb": f"={v['rooms']}*{i('fnb')}",
        "other": f"=({v['rooms']}+{v['fnb']})*{i('other')}",
        "dept": f"={v['rooms']}+{v['fnb']}+{v['other']}",
        "relief": f"=IF(AND({open_}>0,{open_}<={i('relief_months')}),{v['rooms']}*{i('vat')},0)",
        "rooms_exp": f"={v['rooms']}*{i('rooms_cost')}",
        "fnb_exp": f"={v['fnb']}*{i('fnb_cost')}",
        "other_exp": f"={v['other']}*{i('other_cost')}",
        "ag": f"={v['dept']}*{i('ag')}",
        "sm": f"={v['dept']}*{i('sm')}",
        "pom": f"={v['dept']}*{i('pom')}",
        "util": f"={v['dept']}*{i('util')}",
        "gop": (f"={v['dept']}-{v['rooms_exp']}-{v['fnb_exp']}-{v['other_exp']}"
                f"-{v['ag']}-{v['sm']}-{v['pom']}-{v['util']}"),
        "base_fee": f"={v['dept']}*{i('base_fee')}",
        "incentive": f"=MAX(0,{v['gop']})*{i('incentive')}",
        "reserve": f"={v['dept']}*{i('reserve')}",
        "book_b_open": f"={prev('book_b_close', i('building_net'))}",
        "dep_b": f"=IF({open_}>0,MIN({v['book_b_open']},{i('building_net')}/{i('building_months')}),0)",
        "book_b_close": f"={v['book_b_open']}-{v['dep_b']}",
        "book_f_open": f"={prev('book_f_close', i('ffe_net'))}",
        "dep_f": f"=IF({open_}>0,MIN({v['book_f_open']},{i('ffe_net')}/{i('ffe_months')}),0)",
        "book_f_close": f"={v['book_f_open']}-{v['dep_f']}",
        "ptax": f"=IF({open_}>0,({v['book_b_open']}-{v['dep_b']}/2)*{i('property_rate')}/12,0)",
        "ins": f"=IF({open_}>0,{i('insurance_month')},0)",
        "revenue": f"={v['dept']}+{v['relief']}",
        "opex": f"={v['dept']}-{v['gop']}+{v['base_fee']}+{v['incentive']}+{v['reserve']}",
        "ebitda": f"={v['revenue']}-{v['opex']}-{v['ptax']}-{v['ins']}",
        "exit": f'=IF(AND({i("exit_mode")}="sale",{A}={i("horizon")}),{i("exit_value")},0)',
        "exit_cost": f"={v['exit']}*{i('exit_cost')}",
        "residual": f'=IF(AND({i("exit_mode")}="hold",{A}={i("horizon")}),{i("exit_value")},0)',
        "vatin": f"=IF({v['in_h']}=1,MAX(0,{v['capex']}-{v['capex_land']})*{i('vs')},0)",
        "refund": (f"=IF({A}>{i('horizon')},0,IF({A}={i('horizon')},SUM({refund_window}),"
                   f"{refund_lag}))"),
        "rate": (f'=IF({i("financing")}="none",0,IF({i("financing")}="preferential",'
                 f"{i('pref_share')}*{v['key_rate']}+{i('pref_margin')},"
                 f"{v['key_rate']}+{i('spread')}))"),
        "bal_open": f"={prev('bal_close')}",
        "interest": f"={v['bal_open']}*{v['rate']}/12",
        "int_cap": f"=IF({A}<{i('comm')},{v['interest']},0)",
        "int_paid": f"=IF(AND({A}>={i('comm')},{v['in_h']}=1),{v['interest']},0)",
        "want": f"=IF(AND({A}<={i('comm')},{v['in_h']}=1),{v['capex']}*{i('loan_share')},0)",
        "cum_prev": f"={prev('cum_draw')}",
        "draw": (f"=IF({i('limit_on')}=1,MIN({v['want']},MAX(0,{i('limit')}-{v['cum_prev']})),"
                 f"{v['want']})"),
        "cum_draw": f"={v['cum_prev']}+{v['draw']}",
        "fee": f"={v['draw']}*{i('fee')}",
        "first_k": f"=IF({v['draw']}>0,{A},{NO_DRAW})",
        "bal_after": f"={v['bal_open']}+{v['int_cap']}+{v['draw']}",
        "prepay": f"=IF({v['bal_after']}>0,MIN({v['bal_after']},{v['refund']}),0)",
        "bal_pre": f"={v['bal_after']}-{v['prepay']}",
        "annuity": (f"=IF(AND({A}>={i('amort_start')},{A}<{i('maturity')},{v['bal_pre']}>0),"
                    f"IF({v['rate']}>0,MIN({v['bal_pre']},MAX(0,{v['bal_pre']}*{r12}"
                    f"/(1-(1+{r12})^(-{left}))-{v['interest']})),"
                    f"MIN({v['bal_pre']},MAX(0,{v['bal_pre']}/{left}-{v['interest']}))),0)"),
        "sched": (f"=IF(OR({v['bal_pre']}<=0,{A}<{i('comm')},{A}>{i('horizon')}),0,"
                  f"IF(OR({A}={i('horizon')},{A}>={i('maturity')}),{v['bal_pre']},"
                  f"IF({A}>={i('amort_start')},"
                  f'IF({i("repayment")}="sweep",MIN({v["bal_pre"]},MAX(0,{v["ebitda"]}-{v["interest"]})),'
                  f'IF({i("repayment")}="sculpted",MIN({v["bal_pre"]},MAX(0,MAX(0,{v["ebitda"]})'
                  f"/{i('dscr')}-{v['interest']})),{v['annuity']})),0)))"),
        # Удержание свободного потока (как в `hotel_flows`): пока долг не
        # погашен, деньги после процентов и налога копятся в проекте и гасят
        # кредит сверх планового платежа, когда погашение разрешено.
        "free": (f"=IF(AND({A}>={i('comm')},{A}<{i('horizon')}),"
                 f"{v['ebitda']}-{v['int_paid']}-{v['fee']}-{v['tax']},0)"),
        "res_open": f"={prev('res_close')}",
        "sweep": (f"=IF(AND({A}>={i('comm')},{A}<{i('horizon')},{v['bal_pre']}>{v['sched']},"
                  f"OR({A}>={i('amort_start')},{A}>={i('maturity')})),"
                  f"MIN({v['bal_pre']}-{v['sched']},MAX(0,{v['res_open']}+{v['free']}-{v['sched']})),0)"),
        "repay": f"={v['sched']}+{v['sweep']}",
        "repay_total": f"={v['repay']}+{v['prepay']}",
        "bal_close": f"={v['bal_pre']}-{v['repay']}",
        "res_close": (f"=IF(OR({A}<{i('comm')},{A}>={i('horizon')},{v['bal_close']}<=0.000001),0,"
                      f"MAX(0,{v['res_open']}+{v['free']}-{v['repay']}))"),
        "retained": f"={v['res_close']}-{v['res_open']}",
        "amort": f"=IF({A}={i('horizon')},0,{v['sched']})",
        "dep": f"=IF({v['in_h']}=1,{v['dep_b']}+{v['dep_f']},0)",
        "margin": (f"=IF({v['in_h']}=0,0,{v['ebitda']}+{v['exit']}-{v['exit_cost']}-{v['dep']}"
                   f'-IF(AND({A}={i("horizon")},{i("exit_mode")}="sale"),'
                   f"{v['book_b_close']}+{v['book_f_close']}+{i('land_total')},0))"),
        "fin_ded": f"=IF({v['in_h']}=1,{v['int_cap']}+{v['int_paid']}+{v['fee']},0)",
        "def_acc": f"=IF({A}<{i('comm')},{prev('def_acc')}+{v['margin']}-{v['fin_ded']},0)",
        "newyear": (f"=IF({A}<={i('comm')},0,IF({v['year']}<>{prev('year', v['year'])},1,0))"),
        "prior": (f"=IF({A}<={i('comm')},0,IF({v['newyear']}=1,{prev('prior')}"
                  f"+IF({prev('yres')}<0,-{prev('yres')},-{prev('used')}),{prev('prior')}))"),
        "yres": (f"=IF({A}<{i('comm')},0,IF(OR({A}={i('comm')},{v['newyear']}=1),0,{prev('yres')})"
                 f"+{v['margin']}-{v['fin_ded']}+IF({A}={i('comm')},{prev('def_acc')},0))"),
        "used": (f"=IF(AND({A}>={i('comm')},{v['yres']}>0,{v['prior']}>0),"
                 f"MIN({v['prior']},{v['yres']}*{i('loss_limit')}),0)"),
        "base": f"=IF({A}<{i('comm')},0,MAX({v['yres']}-{v['used']},0))",
        "ypaid_prev": f"=IF(OR({A}<={i('comm')},{v['newyear']}=1),0,{prev('ypaid')})",
        "tax": (f"=IF(OR({A}<{i('comm')},{v['in_h']}=0),0,"
                f"MAX({v['base']}*{i('tax_rate')}-{v['ypaid_prev']},0))"),
        "ypaid": f"={v['ypaid_prev']}+{v['tax']}",
        "vat_paid": f"=-{v['refund']}",
        "operating": (f"=IF({v['in_h']}=0,0,{v['ebitda']}+{v['exit']}+{v['residual']}"
                      f"-{v['exit_cost']}-{v['vat_paid']})"),
        "to_equity": (f"={v['operating']}-{v['int_paid']}-{v['fee']}+{v['draw']}"
                      f"-{v['repay_total']}-{v['retained']}"),
        "project_cf": (f"=IF({v['in_h']}=0,0,{v['operating']}-{v['capex']}-{v['int_cap']}"
                       f"-{v['int_paid']}-{v['fee']}-{v['tax']})"),
        "equity_cf": f"=IF({v['in_h']}=0,0,{v['to_equity']}-{v['capex']}-{v['tax']})",
        "fcff": f"=IF({v['in_h']}=0,0,{v['operating']}-{v['capex']}-{v['tax']})",
        "disc_p": f"={v['project_cf']}/(1+{i('rate_m')})^{A}",
        "disc_e": f"={v['equity_cf']}/(1+{i('discount')}/12)^{A}",
        "irr_p": f"={v['project_cf']}/(1+{irr_p})^{A}",
        "irr_e": f"={v['equity_cf']}/(1+{irr_e})^{A}",
        "cum_p": f"={prev('cum_p')}+{v['project_cf']}",
        "cross_p": (f"=IF(AND({prev('cum_p')}<0,{v['cum_p']}>=0),"
                    f"{A}+(-{prev('cum_p')})/{v['project_cf']},{NO_DRAW})"),
        "cum_dp": f"={prev('cum_dp')}+{v['disc_p']}",
        "cross_dp": (f"=IF(AND({prev('cum_dp')}<0,{v['cum_dp']}>=0),"
                     f"{A}+(-{prev('cum_dp')})/{v['disc_p']},{NO_DRAW})"),
    }


def _model_values(data: dict[str, Any], start: date) -> dict[str, Any]:
    params = hs.effective_params(data.get("params") or {})
    pct = lambda key: _num(params, key) / 100.0  # noqa: E731
    commissioning = _month(data["commissioning"])
    financing = str(params.get("financing") or hs.FINANCING_COMMERCIAL)
    loan_on = financing in (hs.FINANCING_COMMERCIAL, hs.FINANCING_PREFERENTIAL)
    limit_blank = params.get("loan_limit_th_per_key") in (None, "")
    keys = max(0.0, _num(params, "keys"))
    repayment = str(params.get("repayment") or hs.REPAY_ANNUITY)
    dscr = _num(params, "dscr_target")
    if repayment == hs.REPAY_SCULPTED and dscr <= 0:
        dscr = 1.0
    price_date = params.get("adr_price_date") or data.get("start")
    hold = max(1, int(_num(params, "hold_years") or 1))
    return {
        "keys": keys, "adr": max(0.0, _num(params, "adr_rub")),
        "price_k": _index(start, _month(price_date)),
        "index": pct("index_pct"),
        "occ_start": min(1.0, max(0.0, pct("occ_start_pct"))),
        "occ_target": min(1.0, max(0.0, pct("occ_target_pct"))),
        "ramp": max(0, int(_num(params, "ramp_months"))),
        "fnb": max(0.0, pct("fnb_pct")), "other": max(0.0, pct("other_pct")),
        "rooms_cost": max(0.0, pct("rooms_cost_pct")), "fnb_cost": max(0.0, pct("fnb_cost_pct")),
        "other_cost": max(0.0, pct("other_cost_pct")),
        "ag": max(0.0, pct("ag_pct")), "sm": max(0.0, pct("sm_pct")),
        "pom": max(0.0, pct("pom_pct")), "util": max(0.0, pct("utilities_pct")),
        "base_fee": max(0.0, pct("base_fee_pct")), "incentive": max(0.0, pct("incentive_fee_pct")),
        "reserve": max(0.0, pct("ffe_reserve_pct")),
        "relief_months": max(0, int(round(_num(params, "vat_relief_years") * 12))),
        "rev_mult": float(data.get("revenue_multiplier") or 1.0),
        "vat": float(data["vat_rate"]),
        "property_rate": max(0.0, pct("property_tax_pct")),
        "insurance_rate": max(0.0, pct("insurance_pct")),
        "building_months": max(1, int(_num(params, "building_years") or 30)) * 12,
        "ffe_months": max(1, int(_num(params, "ffe_years") or 8)) * 12,
        "financing": financing if financing in dict(hs.FINANCINGS) else hs.FINANCING_COMMERCIAL,
        "loan_share": min(1.0, max(0.0, pct("loan_share_pct"))) if loan_on else 0.0,
        "spread": pct("loan_spread_pp"),
        "pref_share": min(1.0, max(0.0, pct("pref_key_share_pct"))),
        "pref_margin": pct("pref_margin_pp"),
        "limit_on": 0 if limit_blank else 1,
        "limit": 0.0 if limit_blank else _num(params, "loan_limit_th_per_key") * 1000.0 * keys,
        "fee": max(0.0, pct("loan_fee_pct")),
        "term": max(1, int(_num(params, "loan_term_years") or 1)) * 12,
        "grace": max(0, int(_num(params, "grace_months"))),
        "repayment": repayment, "dscr": dscr,
        "exit_mode": str(params.get("exit_mode") or hs.EXIT_SALE),
        "valuation": str(params.get("valuation") or hs.VALUATION_CAP),
        "cap": pct("exit_cap_pct"), "multiple": _num(params, "exit_multiple"),
        "exit_cost": max(0.0, pct("exit_cost_pct")),
        "tax_rate": float(data["profit_tax_rate"]), "loss_limit": LOSS_CARRY_USE_LIMIT,
        "discount": float(data["discount_rate"]),
        "comm": _index(start, commissioning),
        "horizon": _index(start, hs.add_months(commissioning, hold * 12 - 1)),
    }


def _origin_text(field: hs.HotelField, origins: dict[str, Any], raw: Any) -> str:
    origin = origins.get(field.key)
    if origin and raw not in (None, ""):
        return str(origin.get("text") or "")
    if raw in (None, "") and field.default is not None:
        return "умолчание: " + field.origin
    if raw in (None, ""):
        return "не задано"
    return "введено вручную"


def _inputs_sheet(book: Workbook, data: dict[str, Any], values: dict[str, Any],
                  rows: int) -> None:
    ws = book.create_sheet(INPUTS_SHEET, 0)
    ws["A1"] = "Вводные гостиницы — как в проекте, с происхождением"
    ws["A1"].font = BOLD
    ws["A3"] = "Модельная величина"
    ws["C3"] = "Значение"
    for cell in ("A3", "C3"):
        ws[cell].font = BOLD
    for key, label in MODEL:
        row = _ROWS[key]
        ws[f"A{row}"] = label
        ws[f"C{row}"] = values[key]
        ws[f"C{row}"].fill = INPUT_FILL
    last = f"{CALC_SHEET}"
    col = lambda name: f"'{last}'!${_c(name)}${FIRST_ROW}:${_c(name)}${FIRST_ROW + rows - 1}"  # noqa: E731
    i = _in
    derived = {
        "vs": f"={i('vat')}/(1+{i('vat')})",
        "capex_total": f"=SUMIF({col('in_h')},1,{col('capex')})",
        "land_total": f"=SUMIF({col('in_h')},1,{col('capex_land')})",
        "ffe_total": f"=SUMIF({col('in_h')},1,{col('capex_ffe')})",
        "capex_vat": f"=MAX(0,{i('capex_total')}-{i('land_total')})*{i('vs')}",
        "capex_net": f"={i('capex_total')}-{i('capex_vat')}",
        "ffe_net": f"={i('ffe_total')}*(1-{i('vs')})",
        "building_net": f"=MAX(0,{i('capex_net')}-{i('ffe_net')}-{i('land_total')})",
        "insurance_month": f"=({i('capex_net')}-{i('land_total')})*{i('insurance_rate')}/12",
        "first_draw": f"=MIN({col('first_k')})",
        "maturity": (f"=IF({i('first_draw')}<{NO_DRAW},{i('first_draw')}+{i('term')},{NO_DRAW})"),
        "amort_start": (f"=IF({i('first_draw')}<{NO_DRAW},MAX({i('comm')},{i('first_draw')}"
                        f"+{i('grace')}),{NO_DRAW})"),
        "forward_ebitda": f"=SUMIF({col('in_h')},0,{col('ebitda')})",
        "exit_value": (f'=IF({i("forward_ebitda")}<=0,0,IF({i("valuation")}="ev_ebitda",'
                       f"{i('forward_ebitda')}*{i('multiple')},"
                       f"IF({i('cap')}>0,{i('forward_ebitda')}/{i('cap')},0)))"),
        "peak": f"=MAX({col('bal_close')})",
        "rate_m": f"=(1+{i('discount')})^(1/12)-1",
    }
    head = _ROWS[DERIVED[0][0]] - 1
    ws[f"A{head}"] = "Производные (формулы)"
    ws[f"A{head}"].font = BOLD
    for key, label in DERIVED:
        row = _ROWS[key]
        ws[f"A{row}"] = label
        ws[f"C{row}"] = derived[key]

    # Поля проекта как их видит человек: значение и откуда оно.
    params = data.get("params") or {}
    origins = data.get("origins") or {}
    ws["E3"] = "Поле проекта"
    ws["F3"] = "Ед."
    ws["G3"] = "Значение"
    ws["H3"] = "Происхождение"
    for cell in ("E3", "F3", "G3", "H3"):
        ws[cell].font = BOLD
    for n, field in enumerate(hs.FIELDS, start=4):
        raw = (data.get("raw_params") or {}).get(field.key, params.get(field.key))
        ws[f"E{n}"] = field.label
        ws[f"F{n}"] = field.unit
        shown = params.get(field.key)
        if field.kind == "choice":
            shown = dict(field.choices).get(str(shown), shown)
        ws[f"G{n}"] = "" if shown is None else shown
        ws[f"H{n}"] = _origin_text(field, origins, raw)
    for letter, width in (("A", 54), ("B", 2), ("C", 20), ("D", 2), ("E", 46), ("F", 22),
                          ("G", 22), ("H", 90)):
        ws.column_dimensions[letter].width = width


def _calc_sheet(book: Workbook, data: dict[str, Any], start: date, values: dict[str, Any],
                irr_project: float | None, irr_equity: float | None) -> int:
    ws = book.create_sheet(CALC_SHEET)
    ws["A1"] = "Помесячный расчёт гостиницы — формулы книги; оранжевое — значения движка"
    ws["A1"].font = BOLD
    ws["A2"] = ("Строки после конца срока (В сроке = 0) — 12 месяцев для оценки выхода: "
                "в итоги они не входят.")
    head = FIRST_ROW - 1
    for name, (letter, label) in COLUMNS.items():
        ws[f"{letter}{head}"] = label
        ws[f"{letter}{head}"].font = BOLD
    for name in ("capex", "capex_ffe", "capex_land", "key_rate"):
        ws[f"{_c(name)}{head - 1}"] = "СЧИТАЕТ ДВИЖОК"
    for name in ("year", "days"):
        ws[f"{_c(name)}{head - 1}"] = "календарь"
    months = data["months"]
    total = values["horizon"] + 1 + 12
    for idx in range(total):
        r = FIRST_ROW + idx
        month = hs.add_months(start, idx)
        source = months[idx] if idx < len(months) else {}
        ws[f"{_c('k')}{r}"] = idx
        ws[f"{_c('month')}{r}"] = month.isoformat()[:7]
        ws[f"{_c('year')}{r}"] = month.year
        ws[f"{_c('days')}{r}"] = hs.month_days(month)
        for name, key in (("capex", "capex"), ("capex_ffe", "capex_ffe"),
                          ("capex_land", "capex_land"), ("key_rate", "key_rate")):
            value = float(source.get(key, 0.0) or 0.0)
            if name == "key_rate" and idx >= len(months) and months:
                value = float(months[-1].get("key_rate", 0.0) or 0.0)
            ws[f"{_c(name)}{r}"] = value
            ws[f"{_c(name)}{r}"].fill = ENGINE_FILL
        for name, formula in _row_formulas(r, irr_project, irr_equity).items():
            ws[f"{_c(name)}{r}"] = formula
    for idx in range(1, len(COLUMNS) + 1):
        ws.column_dimensions[get_column_letter(idx)].width = 15
    ws.freeze_panes = f"C{FIRST_ROW}"
    return total


# Годовой USALI: (ключ, подпись, колонка расчёта или формула от строк года).
USALI_LINES: tuple[tuple[str, str, str], ...] = (
    ("avail", "Номеро-ночи в продаже", "sum"),
    ("sold", "Проданные номеро-ночи", "sum"),
    ("occupancy", "Загрузка", "ratio:sold:avail"),
    ("adr", "ADR, ₽ без НДС", "ratio:rooms:sold"),
    ("revpar", "RevPAR, ₽ без НДС", "ratio:rooms:avail"),
    ("rooms", "Выручка номерного фонда", "sum"),
    ("fnb", "Выручка F&B", "sum"),
    ("other", "Выручка прочих департаментов", "sum"),
    ("dept", "Выручка департаментов", "sum"),
    ("relief", "Льгота НДС на проживание", "sum"),
    ("revenue", "Выручка всего", "sum"),
    ("rooms_exp", "Расходы номерного фонда", "sum"),
    ("fnb_exp", "Расходы F&B", "sum"),
    ("other_exp", "Расходы прочих департаментов", "sum"),
    ("ag", "A&G", "sum"),
    ("sm", "S&M", "sum"),
    ("pom", "POM", "sum"),
    ("util", "Utilities", "sum"),
    ("gop", "GOP", "sum"),
    ("base_fee", "Базовое вознаграждение оператора", "sum"),
    ("incentive", "Поощрительное вознаграждение оператора", "sum"),
    ("reserve", "Резерв FF&E", "sum"),
    ("ptax", "Налог на имущество", "sum"),
    ("ins", "Страхование", "sum"),
    ("ebitda", "EBITDA", "sum"),
    ("dep", "Амортизация", "sum"),
    ("interest", "Проценты по кредиту", "sum:int_cap+int_paid"),
    ("tax", "Налог на прибыль", "sum"),
    ("int_paid", "Проценты уплаченные", "sum"),
    ("amort", "Плановое тело", "sum"),
    ("dscr", "DSCR (EBITDA ÷ проценты и плановое тело)", "dscr"),
    ("capex", "CAPEX с НДС", "sum"),
    ("fcff", "Поток до финансирования (FCFF)", "sum"),
    ("equity_cf", "Поток капитала (FCFE)", "sum"),
)


def _usali_sheet(book: Workbook, years: list[int], rows: int) -> dict[tuple[str, int], str]:
    ws = book.create_sheet(USALI_SHEET)
    ws["A1"] = "USALI по годам — свод помесячного расчёта (формулы)"
    ws["A1"].font = BOLD
    ws["A3"] = "Статья"
    ws["A3"].font = BOLD
    col = lambda name: f"'{CALC_SHEET}'!${_c(name)}${FIRST_ROW}:${_c(name)}${FIRST_ROW + rows - 1}"  # noqa: E731
    line_row = {key: 4 + n for n, (key, _, _) in enumerate(USALI_LINES)}
    refs: dict[tuple[str, int], str] = {}
    for j, year in enumerate(years):
        letter = get_column_letter(2 + j)
        ws[f"{letter}3"] = year
        ws[f"{letter}3"].font = BOLD
        for key, label, how in USALI_LINES:
            r = line_row[key]
            ws[f"A{r}"] = label
            if how == "sum":
                formula = f"=SUMIF({col('year_h')},{letter}$3,{col(key)})"
            elif how.startswith("sum:"):
                parts = how[4:].split("+")
                formula = "=" + "+".join(f"SUMIF({col('year_h')},{letter}$3,{col(part)})"
                                         for part in parts)
            elif how.startswith("ratio:"):
                _, num, den = how.split(":")
                formula = (f"=IF({letter}{line_row[den]}=0,0,"
                           f"{letter}{line_row[num]}/{letter}{line_row[den]})")
            else:  # dscr
                ds = f"({letter}{line_row['int_paid']}+{letter}{line_row['amort']})"
                formula = (f'=IF(AND({ds}>1,{letter}{line_row["avail"]}>0),'
                           f'{letter}{line_row["ebitda"]}/{ds},"")')
            ws[f"{letter}{r}"] = formula
            refs[(key, year)] = f"'{USALI_SHEET}'!${letter}${r}"
    ws.column_dimensions["A"].width = 46
    for j in range(len(years)):
        ws.column_dimensions[get_column_letter(2 + j)].width = 16
    ws.freeze_panes = "B4"
    refs[("dscr_range", 0)] = (f"'{USALI_SHEET}'!$B${line_row['dscr']}:"
                               f"${get_column_letter(1 + max(1, len(years)))}${line_row['dscr']}")
    return refs


def _totals(rows: int) -> dict[str, str]:
    col = lambda name: f"'{CALC_SHEET}'!${_c(name)}${FIRST_ROW}:${_c(name)}${FIRST_ROW + rows - 1}"  # noqa: E731

    def in_h(name: str) -> str:
        return f"=SUMIF({col('in_h')},1,{col(name)})"

    return {
        "revenue": in_h("revenue"), "department_revenue": in_h("dept"),
        "rooms_revenue": in_h("rooms"), "fnb_revenue": in_h("fnb"),
        "other_revenue": in_h("other"), "vat_relief": in_h("relief"), "gop": in_h("gop"),
        "opex": in_h("opex"), "property_tax": in_h("ptax"), "insurance": in_h("ins"),
        "ebitda": in_h("ebitda"), "depreciation": in_h("dep"),
        "exit_revenue": f"=SUM({col('exit')})", "exit_cost": f"=SUM({col('exit_cost')})",
        "residual_value": f"=SUM({col('residual')})", "vat_refund": f"=SUM({col('refund')})",
        "loan_draw": f"=SUM({col('draw')})",
        "loan_interest": f"=SUM({col('int_cap')})+SUM({col('int_paid')})",
        "loan_fee": f"=SUM({col('fee')})", "loan_repayment": f"=SUM({col('repay_total')})",
        "profit_tax": f"=SUM({col('tax')})", "tax_margin": f"=SUM({col('margin')})",
        "cash_to_equity": in_h("to_equity"),
        "forward_ebitda": f"={_in('forward_ebitda')}", "exit_value": f"={_in('exit_value')}",
        "loan_peak": f"={_in('peak')}",
        "npv_project": f"=SUM({col('disc_p')})", "npv_equity": f"=SUM({col('disc_e')})",
        "npv_at_irr_project": f"=SUM({col('irr_p')})",
        "npv_at_irr_equity": f"=SUM({col('irr_e')})",
        "pbp_years": f"=IF(MIN({col('cross_p')})<{NO_DRAW},MIN({col('cross_p')})/12,\"\")",
        "dpbp_years": f"=IF(MIN({col('cross_dp')})<{NO_DRAW},MIN({col('cross_dp')})/12,\"\")",
    }


# Сверка: итог книги → (подпись, где лежит у движка).
CHECKS: tuple[tuple[str, str, str], ...] = (
    ("revenue", "Выручка всего", "totals"),
    ("department_revenue", "Выручка департаментов", "totals"),
    ("rooms_revenue", "Выручка номеров", "totals"),
    ("vat_relief", "Льгота НДС на проживание", "totals"),
    ("gop", "GOP", "totals"),
    ("opex", "Расходы USALI", "totals"),
    ("property_tax", "Налог на имущество", "totals"),
    ("insurance", "Страхование", "totals"),
    ("ebitda", "EBITDA", "totals"),
    ("depreciation", "Амортизация", "totals"),
    ("exit_revenue", "Выход — продажа", "totals"),
    ("exit_cost", "Затраты на продажу", "totals"),
    ("residual_value", "Удержание — оценка", "totals"),
    ("vat_refund", "Возмещение НДС стройки", "totals"),
    ("loan_draw", "Кредит — выдача", "totals"),
    ("loan_interest", "Кредит — проценты", "totals"),
    ("loan_fee", "Кредит — комиссия", "totals"),
    ("loan_repayment", "Кредит — погашение", "totals"),
    ("tax_margin", "Налоговая маржа", "totals"),
    ("profit_tax", "Налог на прибыль", "totals"),
    ("cash_to_equity", "Деньги собственнику без CAPEX", "totals"),
    ("forward_ebitda", "EBITDA 12 мес. после срока", "kpi"),
    ("exit_value", "Стоимость на выходе", "kpi"),
    ("loan_peak", "Кредит — пик долга", "kpi"),
    ("npv_project", "NPV проекта", "kpi"),
    ("npv_equity", "NPV собственного капитала", "kpi"),
    ("pbp_years", "Срок окупаемости, лет", "kpi"),
    ("dpbp_years", "Дисконтированный срок окупаемости, лет", "kpi"),
    ("dscr_min", "DSCR — минимум по годам", "kpi"),
)
TOLERANCE_SHARE = 1e-6


def build(result: dict[str, Any], project_name: str = "") -> bytes:
    """Книга гостиничного проекта из посчитанного движком результата."""
    finance = result.get("finance") or {}
    summary = result.get("summary") or {}
    hotel = finance.get("hotel") or {}
    book = Workbook()
    book.remove(book.active)
    if not hotel.get("computed"):
        ws = book.create_sheet("Гостиница")
        ws["A1"] = "Гостиница не считается: не заданы " + ", ".join(hotel.get("missing") or [])
        stream = io.BytesIO()
        book.save(stream)
        return stream.getvalue()
    data = hotel["book"]
    kpi = hotel.get("kpi") or {}
    start = _month(data["months"][0]["month"])
    values = _model_values(data, start)
    rows = values["horizon"] + 1 + 12
    _inputs_sheet(book, data, values, rows)
    _calc_sheet(book, data, start, values, kpi.get("irr_project"), kpi.get("irr_equity"))
    years = sorted({row["year"] for row in hotel.get("annual") or [] if row.get("rooms_available")})
    refs = _usali_sheet(book, years, rows)
    totals = _totals(rows)

    sheet = book.create_sheet(TOTALS_SHEET, 0)
    sheet["A1"] = f"DevelopAid · гостиница{(' · ' + project_name) if project_name else ''}"
    sheet["A1"].font = BOLD
    sheet["A2"] = ("Итоги — формулы книги (как «Контр_панель» эталонных моделей); IRR — "
                   "значение движка, проверенное формулой: NPV потока при нём равен нулю.")
    lines = (
        ("NPV проекта", "npv_project"),
        ("IRR проекта (движок)", None, kpi.get("irr_project")),
        ("Проверка: NPV потока проекта при IRR движка", "npv_at_irr_project"),
        ("NPV собственного капитала", "npv_equity"),
        ("IRR собственного капитала (движок)", None, kpi.get("irr_equity")),
        ("Проверка: NPV потока капитала при IRR движка", "npv_at_irr_equity"),
        ("Срок окупаемости (PBP), лет от начала проекта", "pbp_years"),
        ("Дисконтированный срок окупаемости (DPBP), лет", "dpbp_years"),
        ("Выручка за срок", "revenue"),
        ("EBITDA за срок", "ebitda"),
        ("Налог на прибыль", "profit_tax"),
        ("Стоимость на выходе", "exit_value"),
        ("Кредит — пик долга", "loan_peak"),
        ("Кредит — проценты", "loan_interest"),
        ("DSCR — минимум по годам", "dscr_min"),
    )
    total_refs: dict[str, str] = {}
    for n, line in enumerate(lines, start=4):
        label, key = line[0], line[1]
        sheet[f"A{n}"] = label
        if key is None:
            sheet[f"B{n}"] = "" if line[2] is None else float(line[2])
            sheet[f"B{n}"].fill = ENGINE_FILL
            sheet[f"C{n}"] = "СЧИТАЕТ ДВИЖОК"
            continue
        if key == "dscr_min":
            rng = refs[("dscr_range", 0)]
            sheet[f"B{n}"] = f'=IF(COUNT({rng})>0,MIN({rng}),"")'
        else:
            sheet[f"B{n}"] = totals[key]
        total_refs[key] = f"'{TOTALS_SHEET}'!$B${n}"
    project_rows = (
        ("Проект: выручка (движок)", summary.get("revenue")),
        ("Проект: чистая прибыль (движок)", summary.get("net_profit")),
        ("Проект: NPV (движок)", summary.get("npv")),
        ("Проект: IRR собственного капитала (движок)", summary.get("irr_equity")),
    )
    base = 4 + len(lines) + 1
    for n, (label, value) in enumerate(project_rows, start=base):
        sheet[f"A{n}"] = label
        sheet[f"B{n}"] = float(value) if value is not None else ""
        sheet[f"B{n}"].fill = ENGINE_FILL
        sheet[f"C{n}"] = "СЧИТАЕТ ДВИЖОК"
    sheet.column_dimensions["A"].width = 56
    sheet.column_dimensions["B"].width = 22

    checks = book.create_sheet(CHECK_SHEET)
    checks["A1"] = "Сверка формул книги с движком"
    checks["A1"].font = BOLD
    checks.append(["Показатель", "Книга", "Движок", "Разница", "Допуск", "Итог"])
    hidden: dict[str, str] = {}
    for key, label, where in CHECKS:
        engine = (hotel.get(where) or {}).get(key)
        row = checks.max_row + 1
        ref = total_refs.get(key)
        if ref is None:
            hidden[key] = totals[key]
        checks[f"A{row}"] = label
        checks[f"B{row}"] = f"={ref}" if ref else totals[key]
        checks[f"C{row}"] = float(engine) if isinstance(engine, (int, float)) else ""
        checks[f"C{row}"].fill = ENGINE_FILL
        checks[f"D{row}"] = f'=IF(OR(C{row}="",B{row}=""),"",B{row}-C{row})'
        checks[f"E{row}"] = f'=IF(C{row}="","",MAX(1,ABS(C{row})*{TOLERANCE_SHARE}))'
        checks[f"F{row}"] = (f'=IF(AND(C{row}="",B{row}=""),"—",IF(OR(C{row}="",B{row}=""),'
                             f'"РАСХОЖДЕНИЕ",IF(ABS(D{row})<=E{row},"сходится","РАСХОЖДЕНИЕ")))')
    # Годовой USALI — по годам: выручка и EBITDA книги против движка.
    for year_row in hotel.get("annual") or []:
        if not year_row.get("rooms_available"):
            continue
        for key, label, engine_key in (("revenue", "Выручка", "revenue"),
                                       ("ebitda", "EBITDA", "ebitda")):
            row = checks.max_row + 1
            checks[f"A{row}"] = f"{label} {year_row['year']}"
            checks[f"B{row}"] = f"={refs[(key, year_row['year'])]}"
            checks[f"C{row}"] = float(year_row.get(engine_key) or 0.0)
            checks[f"C{row}"].fill = ENGINE_FILL
            checks[f"D{row}"] = f"=B{row}-C{row}"
            checks[f"E{row}"] = f"=MAX(1,ABS(C{row})*{TOLERANCE_SHARE})"
            checks[f"F{row}"] = f'=IF(ABS(D{row})<=E{row},"сходится","РАСХОЖДЕНИЕ")'
    last = checks.max_row
    checks["H2"] = "Вердикт"
    checks["H3"] = f'=IF(COUNTIF(F3:F{last},"РАСХОЖДЕНИЕ")=0,"ПРОЙДЕНО","ЕСТЬ РАСХОЖДЕНИЯ")'
    for letter, width in (("A", 40), ("B", 20), ("C", 20), ("D", 14), ("E", 12), ("F", 14)):
        checks.column_dimensions[letter].width = width
    stream = io.BytesIO()
    book.save(stream)
    return stream.getvalue()
