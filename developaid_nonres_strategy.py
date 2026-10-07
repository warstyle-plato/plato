"""Стратегия реализации нежилого объекта: ДДУ, прямая продажа, доходный метод.

Владелец (03.10.2026): у каждого ТЦ и офисника в основном расчёте есть выбор —

* ``ddu``    — продажа по ДДУ 214-ФЗ с эскроу. Как было: этот модуль объект
  не трогает вовсе, деньги идут в общий эскроу проекта.
* ``direct`` — прямая продажа без эскроу (ДКП после ввода). Деньги приходят
  застройщику сразу и гасят СВОЙ кредит объекта.
* ``income`` — доходный метод: объект удерживается и сдаётся в аренду, NOI
  гасит кредит, в конце срока — выход продажей по ставке капитализации или
  удержание с оценкой стоимости.

Финансирование (б) и (в) — своё, не проектное: «финансирование может быть у
них другим, не по ДДУ же, без эскроу». Отсюда кредит объекта: выборка долей
затрат стройки, проценты по ключевой ставке плюс спред, капитализация до ввода,
погашение из денег объекта.

Модуль чистый: ни движка, ни ввода-вывода. Затраты объекта, дату ввода, цену и
ключевую ставку ему передаёт движок (`main_legacy.simulate_financing`) — CAPEX
считается ОДИН раз там, а не второй раз здесь. Расчёт эксплуатации (заполнение,
индексация аренды, OPEX, NOI, стоимость выхода) перенесён из
``feature/commercial-engine-v2`` (PR #531, ``developaid_commercial_engine``):
``_occupancy``, ``_growth_factor``, ``_office_month``, ``_sales_weights``. Его
собственная стройка, долг и IRR не перенесены: здесь они — у основного движка.

Все деньги — рубли С НДС, как и везде в движке; НДС объекта считается здесь
отдельной строкой (начислено с выручки, к вычету — входящий со стройки).
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date
from typing import Any, Callable

STRATEGY_DDU = "ddu"
STRATEGY_DIRECT = "direct"
STRATEGY_INCOME = "income"
STRATEGIES: tuple[tuple[str, str], ...] = (
    (STRATEGY_DDU, "Продажа по ДДУ 214-ФЗ (эскроу)"),
    (STRATEGY_DIRECT, "Прямая продажа без эскроу (ДКП, в т.ч. до ввода)"),
    (STRATEGY_INCOME, "Доходный метод: аренда и выход"),
)
STRATEGY_LABELS = dict(STRATEGIES)

EXIT_SALE = "sale"
EXIT_HOLD = "hold"
REPAY_ANNUITY = "annuity"
REPAY_SWEEP = "sweep"
REPAY_BULLET = "bullet"
REPAYMENTS = (REPAY_ANNUITY, REPAY_SWEEP, REPAY_BULLET)
SALE_CURVES = ("flat", "bell", "front_loaded", "back_loaded")

# Поля стратегии у объекта: суффикс → (умолчание офиса, умолчание ТЦ).
# Аренда, загрузка, OPEX и ставка капитализации — умолчания PR #531
# (`ASSET_DEFAULTS` / `COMMON_DEFAULTS`), переведённые в тыс. ₽; это стартовые
# числа, а не рынок конкретной площадки.
STRATEGY_FIELD_DEFAULTS: dict[str, tuple[Any, Any]] = {
    "strategy": (STRATEGY_DDU, STRATEGY_DDU),
    "loan_share_pct": (60.0, 60.0),
    "loan_spread_pp": (4.0, 4.0),
    "loan_fee_pct": (1.0, 1.0),
    "property_tax_pct": (2.2, 2.2),
    "direct_sale_offset_months": (0, 0),
    "direct_sale_months": (12, 12),
    "direct_sale_curve": ("flat", "flat"),
    "rent_th_per_sqm_month": (4.5, 3.8),
    "rent_index_pct": (5.0, 5.0),
    "occupancy_start_pct": (55.0, 60.0),
    "occupancy_stable_pct": (92.0, 94.0),
    "leaseup_months": (12, 12),
    "opex_pct": (18.0, 24.0),
    "parking_rent_th_month": (8.0, 0.0),
    "hold_years": (5, 5),
    "exit_mode": (EXIT_SALE, EXIT_SALE),
    "exit_cap_pct": (11.0, 11.0),
    "exit_cost_pct": (1.0, 1.0),
    # Удержание: кредит после ввода — долгосрочный, проценты и тело ежемесячно
    # аннуитетом, в конце срока — «баллон» (владелец, 04.10.2026: «кредит
    # становится условно 10 летним с регулярным погашением… в конце ещё
    # небольшой баллон»).
    "debt_repayment": (REPAY_ANNUITY, REPAY_ANNUITY),
    "loan_term_years": (10, 10),
    "loan_balloon_pct": (20.0, 20.0),
    "depreciation_years": (30, 30),
}


def strategy_defaults(prefix: str, family: str) -> dict[str, Any]:
    column = 1 if family == "standalone_retail" else 0
    return {f"{prefix}_{suffix}": pair[column]
            for suffix, pair in STRATEGY_FIELD_DEFAULTS.items()}


def object_strategy(inputs: dict[str, Any] | None, prefix: str) -> str:
    """Стратегия объекта. Отсутствующее или чужое значение — ДДУ, как было."""
    value = str((inputs or {}).get(f"{prefix}_strategy") or "").strip().lower()
    return value if value in STRATEGY_LABELS else STRATEGY_DDU


# --- даты -------------------------------------------------------------------

def _add_months(value: date, months: int) -> date:
    index = value.year * 12 + value.month - 1 + int(months)
    return date(index // 12, index % 12 + 1, 1)


def _month_index(start: date, month: date) -> int:
    return (month.year - start.year) * 12 + month.month - start.month


# --- перенесено из PR #531 (developaid_commercial_engine) -------------------

def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def sales_weights(months: int, shape: str) -> list[float]:
    """Веса продаж по месяцам, сумма ровно 1 (PR #531 `_sales_weights`)."""
    months = max(1, int(months))
    shape = str(shape or "flat").strip().lower()
    if shape == "bell":
        raw = [float(m * (months + 1 - m)) for m in range(1, months + 1)]
    elif shape == "front_loaded":
        raw = [float(months + 1 - m) for m in range(1, months + 1)]
    elif shape == "back_loaded":
        raw = [float(m) for m in range(1, months + 1)]
    else:
        raw = [1.0] * months
    total = sum(raw) or 1.0
    weights = [value / total for value in raw]
    weights[-1] += 1.0 - sum(weights)
    return weights


def occupancy(months_open: int, start: float, stable: float, leaseup: int) -> float:
    """Линейное заполнение от стартовой загрузки до стабильной (PR #531)."""
    if months_open <= 0:
        return 0.0
    start = min(start, stable)
    leaseup = max(1, int(leaseup))
    progress = (1.0 if leaseup == 1 else
                _clamp((months_open - 1) / (leaseup - 1), 0.0, 1.0))
    return start + (stable - start) * progress


def growth_factor(annual_rate: float, months_open: int) -> float:
    """Индексация аренды от первого месяца эксплуатации (PR #531)."""
    return (1.0 + max(-0.95, annual_rate)) ** (max(0, months_open - 1) / 12.0)


def operating_month(p: dict[str, float], months_open: int) -> dict[str, float]:
    """Месяц эксплуатации: выручка аренды, OPEX, NOI (PR #531 `_office_month`).

    Арендопригодная площадь — продаваемая объекта: та самая, которую объект
    продал бы по ДДУ. Места гаража сдаются по своей ставке за место.
    """
    occ = occupancy(months_open, p["occ_start"], p["occ_stable"], p["leaseup"])
    growth = growth_factor(p["rent_index"], months_open)
    space_rent = p["area"] * p["rent"] * growth * occ
    parking_rent = p["parking_spaces"] * p["parking_rent"] * growth * occ
    revenue = (space_rent + parking_rent) * p["revenue_multiplier"]
    opex = revenue * min(0.95, p["opex_share"])
    return {"occupancy": occ, "revenue": revenue, "opex": opex,
            "noi": revenue - opex}


# --- расчёт объекта ---------------------------------------------------------

def direct_sale_window(plan: dict[str, Any]) -> tuple[date, int]:
    """Старт и срок прямых продаж. Сдвиг считается от ввода и может быть
    отрицательным: предварительный ДКП с авансами до ввода, без эскроу
    (владелец, 03.10.2026: «возможна и нужна»)."""
    params = plan.get("params") or {}
    offset = int(_num(params, "direct_sale_offset_months", 0))
    period = max(1, int(_num(params, "direct_sale_months", 12)))
    return _add_months(plan["commissioning"], max(-120, offset)), period


def plan_horizon_end(plan: dict[str, Any]) -> date:
    """Последний месяц денег объекта: конец прямых продаж или выход.

    Движок продлевает по нему горизонт проекта ДО финансирования: удержанный
    офис живёт дольше жилья, и его NOI не должен обрезаться РВЭ дома.
    """
    params = plan.get("params") or {}
    commissioning: date = plan["commissioning"]
    if plan["strategy"] == STRATEGY_DIRECT:
        start, period = direct_sale_window(plan)
        return max(commissioning, _add_months(start, period - 1))
    hold_years = max(1, int(_num(params, "hold_years", 5)))
    return _add_months(commissioning, hold_years * 12 - 1)



def _num(params: dict[str, Any], key: str, default: float) -> float:
    try:
        value = params.get(key)
        return default if value in (None, "") else float(value)
    except (TypeError, ValueError):
        return default


def _choice(params: dict[str, Any], key: str, allowed: tuple[str, ...], default: str) -> str:
    value = str(params.get(key) or "").strip().lower()
    return value if value in allowed else default


def object_flows(plan: dict[str, Any], key_rate: Callable[[date], float],
                 *, vat_rate: float) -> dict[str, Any]:
    """Денежный поток объекта при стратегии «прямая продажа» или «доход».

    ``plan`` собирает движок: ``strategy``, ``capex`` {месяц: ₽ с НДС},
    ``commissioning`` (месяц ввода), ``area_sqm``, ``parking_spaces``,
    ``price_rub_sqm`` и ``price_start`` (цена и её дата отсчёта),
    ``growth_pre`` / ``growth_post`` (рост цены в месяц до и после ввода),
    ``parking_price_rub``, ``selling_share`` (маркетинг + продажи), множители
    сценария и ``params`` — вводные стратегии без приставки объекта.

    Возвращает помесячные ряды (ключ — первое число месяца) и итоги. Всё, что
    уходит в общий расчёт, лежит в ``monthly``; движок складывает эти ряды со
    своими и больше ничего не пересчитывает.
    """
    strategy = plan["strategy"]
    params = plan.get("params") or {}
    capex: dict[date, float] = {m: float(v) for m, v in (plan.get("capex") or {}).items() if v}
    commissioning: date = plan["commissioning"]
    vat_share = vat_rate / (1.0 + vat_rate) if vat_rate > 0 else 0.0
    revenue_multiplier = float(plan.get("revenue_multiplier", 1.0) or 1.0)
    cost_multiplier = float(plan.get("cost_multiplier", 1.0) or 1.0)
    capex_total = sum(capex.values())
    cost_basis = capex_total * (1.0 - vat_share)  # входящий НДС объекта — к вычету
    warnings: list[str] = []

    loan_share = _clamp(_num(params, "loan_share_pct", 60.0) / 100.0, 0.0, 0.95)
    spread = _num(params, "loan_spread_pp", 4.0) / 100.0
    fee_share = max(0.0, _num(params, "loan_fee_pct", 1.0) / 100.0)
    # Плата за резервирование лимита НКЛ объекта: банк кредитует долю всех
    # затрат — участка, проекта, стройки — одной линией, и резервирует её
    # лимит при открытии. Ставка — проектная вводная (как у БРИДЖа и ПФ).
    reservation_share = max(0.0, float(plan.get("reservation_fee_pct", 0.0) or 0.0) / 100.0)
    # Плата за невыбранный лимит — как у ПФ: остаток лимита сверх выбранного
    # тела × ставка / 12, пока линия доступна (с первой выдачи до ввода).
    commitment_share = max(0.0, float(plan.get("limit_fee_pct", 0.0) or 0.0) / 100.0)
    property_tax = max(0.0, _num(params, "property_tax_pct", 2.2) / 100.0)
    repayment = _choice(params, "debt_repayment", REPAYMENTS, REPAY_ANNUITY)
    term_months = max(1, int(_num(params, "loan_term_years", 10))) * 12
    balloon_share = _clamp(_num(params, "loan_balloon_pct", 20.0) / 100.0, 0.0, 1.0)
    # Общие затраты проекта (участок, проект, надбавки), которые несёт этот
    # объект: в нежилом проекте банк кредитует долю ВСЕЙ стоимости. Они
    # финансируются кредитом, но не входят ни в НДС, ни в себестоимость
    # объекта — их учитывает проект.
    common: dict[date, float] = {mm: float(v) for mm, v in (plan.get("common_capex") or {}).items() if v}

    first = min([commissioning, *capex, *(plan.get("common_capex") or {})])
    m = defaultdict(lambda: defaultdict(float))  # ряд → месяц → значение
    sold_share: dict[date, float] = {}
    horizon_end = commissioning
    exit_value = residual_value = forward_noi = stabilized_noi = 0.0
    exit_month: date | None = None

    if strategy == STRATEGY_DIRECT:
        start, period = direct_sale_window(plan)
        curve = _choice(params, "direct_sale_curve", SALE_CURVES, "flat")
        first = min(first, start)
        price_start: date = plan.get("price_start") or commissioning
        growth_pre = float(plan.get("growth_pre", 0.0) or 0.0)
        growth_post = float(plan.get("growth_post", 0.0) or 0.0)
        area = float(plan.get("area_sqm", 0.0) or 0.0)
        spaces = float(plan.get("parking_spaces", 0.0) or 0.0)
        for index, weight in enumerate(sales_weights(period, curve)):
            month = _add_months(start, index)
            # Цена идёт той же траекторией, что у ДДУ: рост «до ввода» до
            # месяца ввода и «после» — дальше. Один метр в одну дату стоит
            # одинаково при любой стратегии; разницу задаёт сама цена.
            pre = max(0, min(_month_index(price_start, month),
                             _month_index(price_start, commissioning)))
            post = max(0, _month_index(max(price_start, commissioning), month))
            factor = (1.0 + growth_pre) ** pre * (1.0 + growth_post) ** post
            base = (area * float(plan.get("price_rub_sqm", 0.0) or 0.0)
                    + spaces * float(plan.get("parking_price_rub", 0.0) or 0.0)) * factor * weight
            m["sale_revenue"][month] += base * revenue_multiplier
            m["selling_cost"][month] += base * float(plan.get("selling_share", 0.0) or 0.0) * cost_multiplier
            sold_share[month] = sold_share.get(month, 0.0) + weight
        horizon_end = plan_horizon_end(plan)
        # Налог на имущество — с непроданной доли готового здания; проданное
        # авансом до ввода в неё уже не входит.
        unsold = max(0.0, 1.0 - sum(share for when, share in sold_share.items()
                                    if when < commissioning))
        month = commissioning
        while month <= horizon_end:
            # Налог на имущество — с непроданной доли готового здания.
            m["property_tax"][month] += cost_basis * property_tax / 12.0 * unsold
            unsold = max(0.0, unsold - sold_share.get(month, 0.0))
            month = _add_months(month, 1)
    elif strategy == STRATEGY_INCOME:
        hold_years = max(1, int(_num(params, "hold_years", 5)))
        exit_mode = _choice(params, "exit_mode", (EXIT_SALE, EXIT_HOLD), EXIT_SALE)
        cap = _num(params, "exit_cap_pct", 11.0) / 100.0
        exit_cost_share = max(0.0, _num(params, "exit_cost_pct", 1.0) / 100.0)
        p = {
            "area": float(plan.get("area_sqm", 0.0) or 0.0),
            "parking_spaces": float(plan.get("parking_spaces", 0.0) or 0.0),
            "rent": _num(params, "rent_th_per_sqm_month", 0.0) * 1000.0,
            "parking_rent": _num(params, "parking_rent_th_month", 0.0) * 1000.0,
            "rent_index": _num(params, "rent_index_pct", 0.0) / 100.0,
            "occ_start": _clamp(_num(params, "occupancy_start_pct", 0.0) / 100.0, 0.0, 1.0),
            "occ_stable": _clamp(_num(params, "occupancy_stable_pct", 0.0) / 100.0, 0.0, 1.0),
            "leaseup": max(1, int(_num(params, "leaseup_months", 12))),
            "opex_share": max(0.0, _num(params, "opex_pct", 0.0) / 100.0),
            "revenue_multiplier": revenue_multiplier,
        }
        hold_months = hold_years * 12
        horizon_end = plan_horizon_end(plan)
        for index in range(hold_months):
            month = _add_months(commissioning, index)
            row = operating_month(p, index + 1)
            m["rent_revenue"][month] += row["revenue"]
            m["opex"][month] += row["opex"]
            m["occupancy"][month] = row["occupancy"]
            m["property_tax"][month] += cost_basis * property_tax / 12.0
        # Стоимость выхода — от NOI СЛЕДУЮЩИХ двенадцати месяцев: покупатель
        # платит за доход, который получит сам. PR #531 брал последний месяц ×12
        # — это доход продавца, на год индексации меньше.
        forward_noi = sum(
            operating_month(p, hold_months + k)["noi"] for k in range(1, 13)
        ) - cost_basis * property_tax
        stabilized_noi = sum(
            operating_month(p, max(p["leaseup"], 1) + k)["noi"] for k in range(12)
        ) - cost_basis * property_tax
        if cap <= 0:
            warnings.append("Ставка капитализации не задана — стоимость выхода не считается.")
        exit_value = forward_noi / cap if cap > 0 and forward_noi > 0 else 0.0
        exit_month = horizon_end
        if exit_mode == EXIT_SALE:
            m["exit_revenue"][exit_month] += exit_value
            m["exit_cost"][exit_month] += exit_value * exit_cost_share
        else:
            # Удержание: стоимость объекта — оценка, а не поступление. Она
            # закрывает горизонт, чтобы IRR не считал объект бесплатным, но
            # без НДС, налога и затрат выхода: сделки нет.
            residual_value = exit_value
            m["residual_value"][exit_month] += residual_value
    else:
        raise ValueError(f"стратегия «{strategy}» не считается этим модулем")

    # --- НДС объекта ------------------------------------------------------
    vat_credit = 0.0
    months: list[date] = []
    month = min(first, commissioning)
    while month <= horizon_end:
        months.append(month)
        month = _add_months(month, 1)
    for month in months:
        charged = (m["sale_revenue"][month] + m["rent_revenue"][month]
                   + m["exit_revenue"][month]) * vat_share
        vat_credit += capex.get(month, 0.0) * vat_share - charged
        m["vat_charged"][month] = charged
        # Входящий НДС стройки принимается к вычету, и непокрытый начислением
        # остаток возмещается из бюджета — в месяц ввода, когда объект принят.
        # Без возмещения он сгорал бы в конце горизонта, хотя себестоимость
        # уже посчитана без него.
        if month == commissioning and vat_credit > 0:
            m["vat_paid"][month] = -vat_credit
            vat_credit = 0.0
        elif vat_credit < 0:
            m["vat_paid"][month] = -vat_credit
            vat_credit = 0.0

    # --- кредит объекта ---------------------------------------------------
    balance = 0.0
    peak = 0.0
    balloon = 0.0
    maturity: date | None = None
    first_draw: date | None = None
    for month in months:
        rate = key_rate(month) + spread
        interest = balance * rate / 12.0
        m["loan_rate"][month] = rate
        if month < commissioning:
            m["loan_interest_cap"][month] = interest
            balance += interest
        else:
            m["loan_interest_paid"][month] = interest
        draw = ((capex.get(month, 0.0) + common.get(month, 0.0)) * loan_share
                if month <= commissioning else 0.0)
        if draw:
            first_draw = first_draw or month
            m["loan_draw"][month] = draw
            m["loan_fee"][month] = draw * fee_share
            balance += draw
        # Авансы прямой продажи гасят кредит сразу, и до ввода: эскроу нет.
        if balance > 0 and (month >= commissioning or strategy == STRATEGY_DIRECT):
            cash = (m["sale_revenue"][month] + m["rent_revenue"][month]
                    + m["exit_revenue"][month] - m["selling_cost"][month]
                    - m["opex"][month] - m["property_tax"][month]
                    - m["exit_cost"][month] - m["vat_paid"][month]
                    - m["loan_interest_paid"][month])
            last = month == horizon_end
            if last:
                repay = balance  # недостающее вносит капитал
            elif repayment == REPAY_SWEEP or strategy == STRATEGY_DIRECT:
                repay = min(balance, max(0.0, cash))
            elif repayment == REPAY_ANNUITY:
                if maturity is None:
                    # Кредит на доходный объект длинный СРАЗУ (владелец,
                    # 04.10.2026): срок считается от первой выдачи, стройка —
                    # льготный период по телу. С ввода — аннуитет, к сроку
                    # остаётся баллон (доля долга на ввод). Срок, истёкший до
                    # ввода, гасит весь долг в месяц ввода.
                    maturity = max(_add_months(first_draw or commissioning, term_months),
                                   commissioning)
                    balloon = balance * balloon_share
                    repay = balance if maturity <= commissioning else 0.0
                elif month >= maturity:
                    repay = balance  # баллон
                else:
                    # Платежей до срока; в сам срок гасится остаток — баллон.
                    left = _month_index(month, maturity)
                    r = rate / 12.0
                    target = balance - balloon / (1.0 + r) ** left if r else balance - balloon
                    payment = (target * r / (1.0 - (1.0 + r) ** -left)) if r else target / left
                    repay = min(balance, max(0.0, payment - interest))
                    m["loan_amortization"][month] = repay
            else:
                repay = 0.0
            if repay:
                m["loan_repayment"][month] = repay
                balance -= repay
        m["loan_balance"][month] = balance
        peak = max(peak, balance)

    # Две НКЛ (владелец, 06.10.2026: «основной лимит открывается ближе к
    # РнС… де-факто два лимита НКЛ»): первая — на участок и проект, её
    # лимит — выборка до РнС; вторая, строительная, — выборка с РнС. Каждая
    # открывается своей первой выдачей: тогда и плата за резервирование её
    # лимита, и с того же месяца — плата за невыбранный остаток, как у ПФ.
    # После последней выдачи линии остаток нулевой — плата кончается сама.
    # Без даты РнС в плане линия одна. Всё лежит в комиссиях (`loan_fee`):
    # поток, налог и итог объекта видят их сами.
    permit: date = plan.get("permit") or min(m["loan_draw"] or [commissioning])
    lines = {"land": [mm for mm in months if mm < permit and m["loan_draw"][mm]],
             "build": [mm for mm in months if mm >= permit and m["loan_draw"][mm]]}
    limits = {name: sum(m["loan_draw"][mm] for mm in draws) for name, draws in lines.items()}
    loan_limit = sum(limits.values())
    for name, draws in lines.items():
        if not draws or not limits[name]:
            continue
        opened = draws[0]
        if reservation_share:
            m["loan_reservation_fee"][opened] += limits[name] * reservation_share
            m["loan_fee"][opened] += limits[name] * reservation_share
        if commitment_share:
            drawn = 0.0
            for month in months:
                if month < opened or month > draws[-1]:
                    continue
                drawn += m["loan_draw"][month]
                unused = max(0.0, limits[name] - drawn)
                if unused > 0:
                    m["loan_commitment_fee"][month] += unused * commitment_share / 12.0
                    m["loan_fee"][month] += unused * commitment_share / 12.0

    # --- налоговая база объекта (без процентов: они идут вычетом финансирования)
    monthly_dep = cost_basis / (max(1, int(_num(params, "depreciation_years", 30))) * 12.0)
    book = cost_basis
    # Аванс по предварительному ДКП — не доход: выручка и себестоимость
    # признаются передачей, то есть не раньше ввода. НДС с аванса начислен в
    # месяц оплаты (ст. 167 НК) и в базу прибыли не идёт.
    realized_sale: dict[date, float] = defaultdict(float)
    realized_share: dict[date, float] = defaultdict(float)
    for month, share in sold_share.items():
        when = max(month, commissioning)
        realized_sale[when] += m["sale_revenue"][month] - m["vat_charged"][month]
        realized_share[when] += share
    for month in months:
        if strategy == STRATEGY_DIRECT:
            recognized = cost_basis * realized_share.get(month, 0.0)
            book -= recognized
            m["cost_recognized"][month] = recognized
            m["tax_margin"][month] = (
                realized_sale.get(month, 0.0) - recognized - m["selling_cost"][month]
                - m["property_tax"][month])
            continue
        if month >= commissioning:
            recognized = min(book, monthly_dep)
            if exit_month == month and m["exit_revenue"][month]:
                recognized = book  # при продаже списывается остаток стоимости
        else:
            recognized = 0.0
        book -= recognized
        m["cost_recognized"][month] = recognized
        m["tax_margin"][month] = (
            m["sale_revenue"][month] + m["rent_revenue"][month] + m["exit_revenue"][month]
            - m["vat_charged"][month] - recognized - m["selling_cost"][month]
            - m["opex"][month] - m["property_tax"][month] - m["exit_cost"][month])

    # --- деньги объекта для капитала: CAPEX платит проект, остальное — здесь
    for month in months:
        m["cash_to_equity"][month] = (
            m["sale_revenue"][month] + m["rent_revenue"][month] + m["exit_revenue"][month]
            + m["residual_value"][month]
            - m["selling_cost"][month] - m["opex"][month] - m["property_tax"][month]
            - m["exit_cost"][month] - m["vat_paid"][month]
            - m["loan_interest_paid"][month] - m["loan_fee"][month]
            + m["loan_draw"][month] - m["loan_repayment"][month])

    # Покрытие процентов кредита объекта NOI (ICR) по годам эксплуатации и
    # месяц, когда кредит погашен. DSCR при погашении «из NOI» всегда 1 —
    # гасится ровно остаток после процентов, — поэтому показатель здесь ICR.
    icr_by_year: list[float] = []
    dscr_by_year: list[float] = []
    if strategy == STRATEGY_INCOME:
        for year in range(max(1, int(_num(params, "hold_years", 5)))):
            span = [_add_months(commissioning, year * 12 + k) for k in range(12)]
            noi = sum(m["rent_revenue"][mm] - m["opex"][mm] - m["property_tax"][mm] for mm in span)
            interest = sum(m["loan_interest_paid"][mm] for mm in span)
            service = interest + sum(m["loan_amortization"][mm] for mm in span)
            if interest > 0:
                icr_by_year.append(noi / interest)
                dscr_by_year.append(noi / service)
    repaid = next((mm for mm in months if mm >= commissioning
                   and m["loan_repayment"][mm] and not m["loan_balance"][mm]), None)

    def total(name: str) -> float:
        return float(sum(m[name].values()))

    revenue_total = (total("sale_revenue") + total("rent_revenue")
                     + total("exit_revenue") + total("residual_value"))
    noi_total = (total("rent_revenue") - total("opex") - total("property_tax")
                 if strategy == STRATEGY_INCOME else 0.0)
    equity_cf = [m["cash_to_equity"][mm] - capex.get(mm, 0.0) for mm in months]
    return {
        "strategy": strategy,
        "months": months,
        "commissioning": commissioning,
        "horizon_end": horizon_end,
        # Нули не несём: ряд — это месяцы, в которых что-то было.
        "monthly": {name: {month: value for month, value in series.items() if value}
                    for name, series in m.items()},
        # Затраты объекта по месяцам: своя стройка и доля общих затрат проекта,
        # которую кредитует его кредит. Платит их проект, но итог объекта
        # (`main_legacy.object_result`) без них не сложить.
        "capex_by_month": dict(capex),
        "common_by_month": dict(common),
        "cost_basis": cost_basis,
        "totals": {
            "capex": capex_total,
            "revenue": revenue_total,
            "sale_revenue": total("sale_revenue"),
            "rent_revenue": total("rent_revenue"),
            "exit_revenue": total("exit_revenue"),
            "residual_value": total("residual_value"),
            "opex": total("opex"),
            "property_tax": total("property_tax"),
            "selling_cost": total("selling_cost"),
            "exit_cost": total("exit_cost"),
            "vat_paid": total("vat_paid"),
            "vat_charged": total("vat_charged"),
            "loan_draw": total("loan_draw"),
            "loan_interest": total("loan_interest_cap") + total("loan_interest_paid"),
            "loan_fee": total("loan_fee"),
            "loan_reservation_fee": total("loan_reservation_fee"),
            "loan_commitment_fee": total("loan_commitment_fee"),
            "loan_limit": loan_limit,
            "loan_limit_land": limits["land"],
            "loan_limit_build": limits["build"],
            "loan_repayment": total("loan_repayment"),
            "loan_peak": peak,
            "noi": noi_total,
            "tax_margin": total("tax_margin"),
        },
        "kpi": {
            "stabilized_noi": stabilized_noi,
            "forward_noi": forward_noi,
            "exit_value": exit_value,
            "yield_on_cost": stabilized_noi / capex_total if capex_total else 0.0,
            "exit_month": exit_month,
            "equity_cash_flow_sum": sum(equity_cf),
            "icr_min": min(icr_by_year) if icr_by_year else None,
            "icr_by_year": icr_by_year,
            # DSCR — NOI на проценты и плановое тело (без баллона и выхода).
            "dscr_min": min(dscr_by_year) if dscr_by_year else None,
            "dscr_by_year": dscr_by_year,
            "loan_maturity": maturity,
            "loan_balloon": balloon,
            "loan_repaid_month": repaid,
        },
        "warnings": warnings,
    }
