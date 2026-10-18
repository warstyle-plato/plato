"""Общая финансовая арифметика расчёта: NPV, IRR и налог на прибыль.

Вынесено из `main_legacy` без изменений, чтобы правило жило в одном месте:
движок и чистые модули объектов (`developaid_hotel_strategy`) зовут одни и те
же функции. Вторая реализация того же правила однажды разошлась бы с первой,
и обе выглядели бы верными. Движок импортирует их под прежними именами
(`_monthly_npv`, `_equity_npv`, `_monthly_irr`, `_profit_tax_schedule`,
`_LOSS_CARRY_USE_LIMIT`).
"""

from __future__ import annotations

import math
from datetime import date
from math import pow
from typing import Any


def monthly_npv(cashflows: list[float], annual_rate: float) -> float:
    if not cashflows:
        return 0.0
    monthly_rate = pow(1.0 + max(annual_rate, -0.999999), 1.0 / 12.0) - 1.0
    return sum(cf / pow(1.0 + monthly_rate, i) for i, cf in enumerate(cashflows))


def equity_npv(cashflows: list[float], annual_rate: float) -> float:
    """NPV потока собственного капитала — методикой книги.

    `КОНСОЛИДАТОР!O8` = 'CF'!D25 + NPV('Вводные'!B23/12, 'CF'!E25:GA25):
    первый месяц без дисконта, дальше ставка «годовая / 12». Тот же поток, что
    у IRR капитала. `npv` сводки — другой вопрос (поток проекта без кредитов);
    тизер подписывал его «NPV собственного капитала», и рядом с IRR капитала
    две строки спорили: IRR 411 % при NPV −29,7 млн ₽ (владелец, 05.10.2026).
    """
    if not cashflows:
        return 0.0
    monthly_rate = max(annual_rate, -0.999999) / 12.0
    return sum(cf / pow(1.0 + monthly_rate, i) for i, cf in enumerate(cashflows))


def _irr_falling_bracket(npv: Any) -> tuple[float, float] | None:
    """Самый правый отрезок месячных ставок, где NPV падает через ноль."""
    grid = [-0.95 + 0.01 * i for i in range(95)]
    rate = 0.0
    while rate < 100:
        grid.append(rate)
        rate = rate + 0.005 if rate < 0.2 else rate * 1.25
    found = None
    previous, f_previous = grid[0], npv(grid[0])
    for rate in grid[1:]:
        f_rate = npv(rate)
        if f_previous > 0 >= f_rate:
            found = (previous, rate)
        previous, f_previous = rate, f_rate
    return found


def monthly_irr(cashflows: list[float]) -> float | None:
    if not cashflows or not any(v < 0 for v in cashflows) or not any(v > 0 for v in cashflows):
        return None

    # Знак NPV на ставке, уходящей к −100%, задаёт последний ненулевой поток:
    # его знаменатель меньше всех остальных, и он перевешивает весь ряд.
    tail_sign = next((1.0 if cf > 0 else -1.0 for cf in reversed(cashflows) if cf), 0.0)

    def npv(rate: float) -> float:
        if rate <= -0.999999:
            return math.inf * tail_sign if tail_sign else 0.0
        total = 0.0
        factor = 1.0
        base = 1.0 + rate
        for cf in cashflows:
            # На длинном горизонте знаменатель проваливается в ноль раньше, чем
            # ряд кончается: 0,05 в 240-й степени — это уже машинный ноль, и
            # деление на него роняло весь расчёт очередей (площадка КРТ
            # «Магистральные улицы», 02.09.2026). Ноль в знаменателе — не ошибка
            # данных, а предел арифметики: дальше ряд считает знак хвоста.
            if factor == 0.0:
                return math.inf * tail_sign if tail_sign else total
            total += cf / factor
            try:
                factor *= base
            except OverflowError:
                factor = math.inf
        return total

    lo, hi = -0.95, 1.0
    f_lo, f_hi = npv(lo), npv(hi)
    expand = 0
    while f_lo * f_hi > 0 and hi < 100 and expand < 30:
        hi *= 2
        f_hi = npv(hi)
        expand += 1
    if f_lo * f_hi > 0:
        # Края одного знака бывают и у ряда с корнем: вложение, большой приход
        # и хвост расходов после него (налог свода, который очередь платит
        # после своих продаж). У такого ряда NPV отрицателен и у −95%, где
        # решает хвост, и у больших ставок, где решает вложение, а между ними —
        # положителен. Ищем по сетке, где NPV переходит с плюса на минус с
        # ростом ставки, и берём самый правый переход: это доходность
        # вложения, а левый корень — арифметика хвоста.
        bracket = _irr_falling_bracket(npv)
        if bracket is None:
            return None
        lo, hi = bracket
        f_lo, f_hi = npv(lo), npv(hi)

    for _ in range(180):
        mid = (lo + hi) / 2
        f_mid = npv(mid)
        if abs(f_mid) < 1e-5:
            lo = hi = mid
            break
        if f_lo * f_mid <= 0:
            hi = mid
            f_hi = f_mid
        else:
            lo = mid
            f_lo = f_mid

    monthly = (lo + hi) / 2
    return pow(1 + monthly, 12) - 1


# Налог на прибыль: перенос убытка по ст. 283 НК.
#
# Убыток прошлых лет переносится БЕССРОЧНО — десятилетний лимит снят с 2017
# года, и убыток расходуется столько лет, сколько нужно (подтверждено
# владельцем 08.09.2026). Ограничение теперь не в сроке, а в доле: уменьшить
# базу прошлым убытком можно НЕ БОЛЕЕ ЧЕМ НАПОЛОВИНУ, и половинное правило
# продлено до конца 2030 года (владелец, 08.09.2026). Внутри одного года
# доходы и расходы сходятся свободно: половина касается только убытка
# ЗАКРЫТЫХ лет.
#
# Что будет после 2030 года, движок не гадает: половина применяется всегда,
# без проверки года. Это допущение, и оно осторожное — налог выходит не ниже
# должного. Цена его видна: на проекте с убыточным стартом и прибылью в
# 2031-2033 это 2 203 млн против 137 при полном зачёте. Продлят правило ещё
# раз или дадут ему истечь — решение владельца, а не догадка кода.
#
# Прежде движок вёл базу накопленной с начала проекта и гасил ею прибыль
# целиком: это мягче закона — налог начинался позже, чем на самом деле.
LOSS_CARRY_USE_LIMIT = 0.5


def profit_tax_schedule(
    months: list[date],
    margin_by_month: dict[date, float],
    financing_by_month: dict[date, float],
    first_taxable_month: date | None,
    tax_rate: float,
    use_limit: float = LOSS_CARRY_USE_LIMIT,
    defer_financing: bool = True,
) -> tuple[dict[date, float], list[dict[str, Any]]]:
    """График налога на прибыль с переносом убытка и половинным ограничением.

    Объявлен один раз и зовётся дважды: одиночным расчётом и сводом очередей.
    Вторая реализация того же правила однажды разойдётся с первой, и обе
    будут выглядеть верными — так уже расходились ставка ПФ и профиль
    управления между движком и книгой.

    Возвращает помесячный налог и построчную расшифровку: сколько убытка
    прошлых лет зачтено в этом году и сколько осталось. Без расшифровки
    «налог вырос» не отличить от «зачёт упёрся в половину».

    `defer_financing=False` — правило спецзастройщика (владелец, 16.10.2026):
    до первого облагаемого месяца (РВЭ) откладывается только МАРЖА продаж —
    выручка и себестоимость дома признаются при его вводе, — а проценты и
    комиссии остаются расходом месяца начисления (п. 8 ст. 272). Годы до РВЭ
    выходят убыточными, и этот убыток гасит прибыль года РВЭ не больше чем
    наполовину, как любой убыток прошлых лет. Прежде (`True`, его держит
    гостиница) проценты до РВЭ уезжали в год РВЭ целиком и гасили прибыль
    без половинного ограничения.
    """
    if not defer_financing:
        return _profit_tax_schedule_margin_deferred(
            months, margin_by_month, financing_by_month, first_taxable_month,
            tax_rate, use_limit)
    schedule: dict[date, float] = {}
    detail: list[dict[str, Any]] = []
    prior_losses = 0.0      # убыток закрытых лет, ждущий зачёта
    year: int | None = None
    year_result = 0.0       # прибыль или убыток текущего года
    year_used = 0.0         # сколько убытка прошлых лет зачтено в этом году
    year_tax_paid = 0.0
    # Всё, что признано ДО первого облагаемого месяца, приходит в год РВЭ, а
    # не пропадает. Выручка по ДДУ облагается при передаче объекта, поэтому
    # налог и начинается с РВЭ — но это ОТСРОЧКА, а не списание. Пока база
    # была накопленной с начала проекта, разницы не было: прибыль доживала до
    # РВЭ сама. С годовым сбросом прибыльные годы до РВЭ обнулялись молча — на
    # проверочном проекте так пропали 4 327 и 13 407 млн, и налог вышел вдвое
    # меньше должного при внешне исправном расчёте.
    deferred = 0.0
    for month in months:
        gated = first_taxable_month is not None and month < first_taxable_month
        if gated:
            deferred += (margin_by_month.get(month, 0.0)
                         - financing_by_month.get(month, 0.0))
            schedule[month] = 0.0
            detail.append({
                "month": month.isoformat(), "year_result": deferred,
                "loss_used": 0.0, "loss_carry_forward": prior_losses,
                "taxable_base": 0.0, "profit_tax": 0.0,
            })
            continue
        if year is not None and month.year != year:
            # Год закрылся: убыточный пополняет запас, прибыльный — тратит.
            if year_result < 0:
                prior_losses += -year_result
            else:
                prior_losses -= year_used
            year_result = year_used = year_tax_paid = 0.0
        year = month.year
        year_result += (margin_by_month.get(month, 0.0)
                        - financing_by_month.get(month, 0.0)) + deferred
        deferred = 0.0
        year_used = (min(prior_losses, year_result * use_limit)
                     if year_result > 0 and prior_losses > 0 else 0.0)
        base = max(year_result - year_used, 0.0)
        target = base * tax_rate if (
            first_taxable_month is None or month >= first_taxable_month) else 0.0
        tax_month = max(target - year_tax_paid, 0.0)
        year_tax_paid += tax_month
        schedule[month] = tax_month
        detail.append({
            "month": month.isoformat(),
            "year_result": year_result,
            "loss_used": year_used,
            "loss_carry_forward": prior_losses - year_used,
            "taxable_base": base,
            "profit_tax": tax_month,
        })
    return schedule, detail


def _profit_tax_schedule_margin_deferred(
    months: list[date],
    margin_by_month: dict[date, float],
    financing_by_month: dict[date, float],
    first_taxable_month: date | None,
    tax_rate: float,
    use_limit: float,
) -> tuple[dict[date, float], list[dict[str, Any]]]:
    """`profit_tax_schedule` спецзастройщика: до РВЭ откладывается только маржа."""
    schedule: dict[date, float] = {}
    detail: list[dict[str, Any]] = []
    prior_losses = 0.0
    year: int | None = None
    year_result = year_used = year_tax_paid = 0.0
    deferred = 0.0
    for month in months:
        if year is not None and month.year != year:
            if year_result < 0:
                prior_losses += -year_result
            else:
                prior_losses -= year_used
            year_result = year_used = year_tax_paid = 0.0
        year = month.year
        margin = margin_by_month.get(month, 0.0)
        financing = financing_by_month.get(month, 0.0)
        if first_taxable_month is not None and month < first_taxable_month:
            deferred += margin
            year_result -= financing
            schedule[month] = 0.0
            detail.append({
                "month": month.isoformat(), "year_result": year_result,
                "loss_used": 0.0, "loss_carry_forward": prior_losses,
                "taxable_base": 0.0, "profit_tax": 0.0,
            })
            continue
        year_result += margin - financing + deferred
        deferred = 0.0
        year_used = (min(prior_losses, year_result * use_limit)
                     if year_result > 0 and prior_losses > 0 else 0.0)
        base = max(year_result - year_used, 0.0)
        tax_month = max(base * tax_rate - year_tax_paid, 0.0)
        year_tax_paid += tax_month
        schedule[month] = tax_month
        detail.append({
            "month": month.isoformat(),
            "year_result": year_result,
            "loss_used": year_used,
            "loss_carry_forward": prior_losses - year_used,
            "taxable_base": base,
            "profit_tax": tax_month,
        })
    return schedule, detail


# Месяц уплаты налога, начисленного в месяце (1..12): авансы по итогам
# квартала — до 28-го числа следующего месяца (апрель, июль, октябрь), налог
# года за вычетом авансов — до 28 марта следующего года (ст. 286, 287 НК;
# решение владельца 16.10.2026: «раз в квартал по факту»). Ежемесячные
# авансы внутри квартала (треть прошлого квартала) — прогноз, а не факт, и
# модель их не ведёт.
_TAX_PAYMENT_MONTH = {1: 4, 2: 4, 3: 4, 4: 7, 5: 7, 6: 7, 7: 10, 8: 10, 9: 10,
                      10: 3, 11: 3, 12: 3}


def profit_tax_payment_month(month: date) -> date:
    """Месяц, в котором уходит со счёта налог, начисленный в `month`."""
    pay = _TAX_PAYMENT_MONTH[month.month]
    return date(month.year + (1 if pay < month.month else 0), pay, 1)


def profit_tax_payments(accrued: dict[date, float]) -> dict[date, float]:
    """Помесячное начисление налога → помесячная уплата, квартальными авансами.

    Начисление внутри года не убывает (налог года нарастающим итогом, возврата
    нет), поэтому уплата за квартал — просто сумма его начислений, а за IV
    квартал — доплата года в марте. Сумма уплат равна сумме начислений.
    """
    paid: dict[date, float] = {}
    for month, value in accrued.items():
        if value:
            target = profit_tax_payment_month(month)
            paid[target] = paid.get(target, 0.0) + value
    return dict(sorted(paid.items()))


def unused_tax_loss(detail: list[dict[str, Any]]) -> float:
    """Убыток, не зачтённый к концу горизонта, — по расшифровке графика налога.

    Убыток переносится без срока (ст. 283), но гасит не больше половины базы
    года: у проекта с убыточной стройкой и одним прибыльным годом ввода он
    остаётся, и налог платится при убытке за проект в целом. Зачесть остаток
    можно только будущей прибылью того же ООО — поэтому он называется числом
    (владелец, 16.10.2026: «показать остаток убытка»).
    """
    if not detail:
        return 0.0
    last = detail[-1]
    carry = float(last.get("loss_carry_forward", 0.0) or 0.0)
    year_result = float(last.get("year_result", 0.0) or 0.0)
    return carry + max(-year_result, 0.0)
