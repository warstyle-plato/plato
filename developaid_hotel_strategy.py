"""Гостиница в эксплуатации: номера, департаменты, USALI, кредит, выход.

Решения владельца (05.10.2026):

* гостиница — ОТДЕЛЬНЫЙ тип проекта (третий рядом с «Жильё» и «Нежилое»), а
  не объект внутри жилого проекта или КРТ;
* шаг расчёта — месяц, как у движка; годовой USALI — свод тех же месяцев;
* класс (звёздность) — поле уже сейчас;
* ориентиры эталонных моделей не подставляются молча: поле либо пустое с
  подсказкой-диапазоном, либо заполнено ориентиром и хранит его
  происхождение (`hotel_presets`);
* финансирование — льготный кредит по госпрограмме (ставка = доля ключевой
  ставки × КС + маржа) или обычный кредит (КС + спред); отсрочка тела, срок
  и DSCR — параметры;
* выход — EV/EBITDA или ставка капитализации, продажа или удержание;
* USALI укрупнённый: номерной фонд / F&B / прочие департаменты, A&G, S&M,
  POM, Utilities, базовое и поощрительное вознаграждение оператора, резерв
  FF&E, налог на имущество, страхование.

Модуль чистый: ни движка, ни ввода-вывода. CAPEX проекта по месяцам (с НДС),
дату ввода, ключевую ставку и ставку дисконтирования передаёт движок —
CAPEX считается ОДИН раз там. Налог на прибыль, NPV и IRR — общие функции
`developaid_finance_math`, те же, что у движка: второй реализации правила
здесь нет.

Деньги эксплуатации — БЕЗ НДС, как в USALI и во всех эталонных моделях: НДС
с выручки за вычетом входящего с закупок — транзит, который в тот же месяц
уходит в бюджет, денег гостиницы он не меняет. Остаются две вещи, где НДС
меняет деньги:

* входящий НДС стройки — возмещается из бюджета с лагом квартала
  (камеральная проверка), как в модели Домбая («Оборачиваемость НДС к
  получению — 1 квартал»);
* ставка 0 % на услуги размещения в первые годы после ввода (пп. 19 п. 1
  ст. 164 НК): цена гостю та же, а налог с номеров гостиница оставляет себе.
  Это отдельная строка выручки «льгота НДС», и база долей расходов её не
  видит — оператор и департаменты не работают больше от того, что налог
  ниже (так же считает Домбай: «выручка без учёта действия льготы по НДС»).
"""

from __future__ import annotations

import calendar
from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from typing import Any, Callable

from developaid_finance_math import (
    equity_npv, monthly_irr, monthly_npv, profit_tax_schedule)

# --- выборы -----------------------------------------------------------------

FINANCING_COMMERCIAL = "commercial"
FINANCING_PREFERENTIAL = "preferential"
FINANCING_NONE = "none"
FINANCINGS: tuple[tuple[str, str], ...] = (
    (FINANCING_COMMERCIAL, "Обычный кредит: ключевая ставка + спред"),
    (FINANCING_PREFERENTIAL, "Льготный кредит по госпрограмме: доля КС + маржа"),
    (FINANCING_NONE, "Без кредита"),
)

REPAY_ANNUITY = "annuity"
REPAY_SCULPTED = "sculpted"
REPAY_SWEEP = "sweep"
REPAYMENTS: tuple[tuple[str, str], ...] = (
    (REPAY_ANNUITY, "Аннуитет после отсрочки"),
    (REPAY_SCULPTED, "Под DSCR: обслуживание = EBITDA ÷ целевой DSCR"),
    (REPAY_SWEEP, "Весь свободный поток в погашение"),
)

EXIT_SALE = "sale"
EXIT_HOLD = "hold"
EXITS: tuple[tuple[str, str], ...] = (
    (EXIT_SALE, "Продажа в конце срока"),
    (EXIT_HOLD, "Удержание: оценка без сделки"),
)

VALUATION_CAP = "cap_rate"
VALUATION_MULTIPLE = "ev_ebitda"
VALUATIONS: tuple[tuple[str, str], ...] = (
    (VALUATION_CAP, "Ставка капитализации: EBITDA следующих 12 мес. ÷ ставка"),
    (VALUATION_MULTIPLE, "Мультипликатор EV/EBITDA × EBITDA следующих 12 мес."),
)

# Класс (звёздность) по Положению о классификации гостиниц (ПП РФ № 1951).
# Пусто — класс не задан, а не «без звёзд».
CLASSES: tuple[tuple[str, str], ...] = (
    ("5", "5*"), ("4", "4*"), ("3", "3*"), ("2", "2*"), ("1", "1*"),
    ("0", "Без звёзд"),
)


# --- поля ------------------------------------------------------------------

ORIGIN_ENGINE = "умолчание движка — то же, что у кредита объекта нежилого"
ORIGIN_LAW_PROPERTY = "НК РФ ст. 380: предельная ставка налога на имущество"
ORIGIN_PROGRAM = ("госпрограмма льготного кредитования гостиниц (ПП РФ № 141): "
                  "так же в моделях Домбая и UAI")
ORIGIN_DEPRECIATION = "срок полезного использования: здания — 30 лет, мебель и оборудование — 8"


@dataclass(frozen=True)
class HotelField:
    """Вводная гостиницы. Имя на странице и в книге — `hotel_<key>`.

    `default is None` — умолчания НЕТ: поле пустое, пока его не заполнит
    человек или явный выбор ориентира (`hotel_presets`). Отсутствие числа не
    превращается в ноль: расчёт называет незаполненное поимённо
    (`missing_fields`). Умолчание есть только у того, что не является чужой
    площадкой: закона, программы, правил кредита движка — и оно несёт своё
    происхождение (`origin`).
    """
    key: str
    label: str
    unit: str
    group: str
    default: Any = None
    origin: str = ""
    required: bool = True
    kind: str = "number"           # number | choice | date
    choices: tuple[tuple[str, str], ...] = ()
    hint: str = ""
    # При каком выборе поле нужно: (поле, значения). Пусто — нужно всегда.
    needed_when: tuple[str, tuple[str, ...]] | None = None
    # Поле стройки: из него движок считает CAPEX (один раз, у себя), а
    # расчёт гостиницы получает уже готовые затраты по месяцам.
    capex: bool = False


GROUPS: tuple[tuple[str, str], ...] = (
    ("object", "Гостиница"),
    ("revenue", "Номера и выручка"),
    ("costs", "Расходы USALI"),
    ("fixed", "Налоги, страхование, амортизация"),
    ("finance", "Кредит гостиницы"),
    ("exit", "Срок и выход"),
)

FIELDS: tuple[HotelField, ...] = (
    HotelField("stars", "Класс (звёздность)", "", "object", required=False,
               kind="choice", choices=CLASSES,
               hint="пусто — класс не задан; ориентиры подбираются по классу"),
    HotelField("keys", "Номерной фонд", "номеров", "object",
               hint="делитель всех показателей «на номер»"),
    HotelField("gba_sqm", "Площадь гостиницы (ГНС)", "м²", "object", capex=True,
               hint="строительный объём; CAPEX здания = ГНС × ставка"),
    HotelField("cost_th_per_sqm", "Стройка здания", "тыс. ₽/м² ГНС с НДС", "object",
               capex=True, hint="СМР, сети и отделка без мебели и оборудования"),
    HotelField("ffe_th_per_key", "Мебель и оборудование (FF&E)", "тыс. ₽/номер с НДС",
               "object", capex=True, hint="амортизируется своим сроком и не облагается налогом "
                              "на имущество (движимое)"),
    HotelField("adr_rub", "ADR — средняя цена номера", "₽/сутки без НДС", "revenue",
               hint="средневзвешенная по типам номеров, каналам и сезонам"),
    HotelField("adr_price_date", "Дата цены ADR", "", "revenue", required=False,
               kind="date", hint="от неё идёт индексация; пусто — начало проекта"),
    HotelField("index_pct", "Индексация ADR", "%/год", "revenue",
               hint="расходы — доли выручки и растут вместе с ней"),
    HotelField("occ_start_pct", "Стартовая загрузка", "%", "revenue"),
    HotelField("occ_target_pct", "Целевая загрузка", "%", "revenue"),
    HotelField("ramp_months", "Выход на целевую загрузку", "мес.", "revenue",
               hint="линейно от старта до цели; 1-й месяц — стартовая"),
    HotelField("fnb_pct", "Выручка F&B", "% выручки номеров", "revenue"),
    HotelField("other_pct", "Прочие департаменты (SPA, MICE, прочее)",
               "% выручки номеров и F&B", "revenue"),
    HotelField("rooms_cost_pct", "Расходы номерного фонда", "% выручки номеров",
               "costs", hint="прямые расходы и ФОТ со взносами"),
    HotelField("fnb_cost_pct", "Расходы F&B", "% выручки F&B", "costs",
               hint="себестоимость, прямые расходы и ФОТ со взносами"),
    HotelField("other_cost_pct", "Расходы прочих департаментов", "% их выручки", "costs"),
    HotelField("ag_pct", "Административные (A&G, вкл. IT)", "% выручки", "costs"),
    HotelField("sm_pct", "Продажи и маркетинг (S&M)", "% выручки", "costs"),
    HotelField("pom_pct", "Эксплуатация и ремонт (POM)", "% выручки", "costs"),
    HotelField("utilities_pct", "Коммунальные (Utilities)", "% выручки", "costs"),
    HotelField("base_fee_pct", "Базовое вознаграждение оператора", "% выручки", "costs",
               hint="вместе с маркетинговым и лицензионным сборами оператора"),
    HotelField("incentive_fee_pct", "Поощрительное вознаграждение оператора", "% GOP",
               "costs"),
    HotelField("ffe_reserve_pct", "Резерв на замену FF&E", "% выручки", "costs"),
    HotelField("vat_relief_years", "НДС 0 % на проживание", "лет с ввода", "fixed",
               default=0, origin="пп. 19 п. 1 ст. 164 НК РФ; 0 — льгота не применяется",
               hint="цена гостю та же, налог с номеров остаётся гостинице"),
    HotelField("property_tax_pct", "Налог на имущество", "% стоимости здания в год",
               "fixed", default=2.2, origin=ORIGIN_LAW_PROPERTY,
               hint="база — здание без мебели и оборудования и без земли"),
    HotelField("insurance_pct", "Страхование имущества", "% CAPEX без НДС в год", "fixed"),
    HotelField("building_years", "Амортизация здания", "лет", "fixed",
               default=30, origin=ORIGIN_DEPRECIATION),
    HotelField("ffe_years", "Амортизация мебели и оборудования", "лет", "fixed",
               default=8, origin=ORIGIN_DEPRECIATION),
    HotelField("financing", "Финансирование", "", "finance", default=FINANCING_COMMERCIAL,
               origin="обычный кредит: льготу программа даёт по отбору, её выбирают явно",
               kind="choice", choices=FINANCINGS),
    HotelField("loan_share_pct", "Доля кредита в затратах", "%", "finance",
               default=60.0, origin=ORIGIN_ENGINE,
               needed_when=("financing", (FINANCING_COMMERCIAL, FINANCING_PREFERENTIAL))),
    HotelField("loan_spread_pp", "Спред к ключевой ставке", "п.п.", "finance",
               default=4.0, origin=ORIGIN_ENGINE,
               needed_when=("financing", (FINANCING_COMMERCIAL,))),
    HotelField("pref_key_share_pct", "Льготный: доля ключевой ставки", "%", "finance",
               default=30.0, origin=ORIGIN_PROGRAM,
               needed_when=("financing", (FINANCING_PREFERENTIAL,))),
    HotelField("pref_margin_pp", "Льготный: маржа", "п.п.", "finance",
               default=3.0, origin=ORIGIN_PROGRAM,
               needed_when=("financing", (FINANCING_PREFERENTIAL,))),
    HotelField("loan_limit_th_per_key", "Лимит кредита на номер", "тыс. ₽/номер",
               "finance", required=False,
               hint="пусто — без лимита; сверх лимита платит капитал",
               needed_when=("financing", (FINANCING_COMMERCIAL, FINANCING_PREFERENTIAL))),
    HotelField("loan_fee_pct", "Комиссия за выдачу", "% выдачи", "finance",
               default=1.0, origin=ORIGIN_ENGINE,
               needed_when=("financing", (FINANCING_COMMERCIAL, FINANCING_PREFERENTIAL))),
    HotelField("loan_term_years", "Срок кредита", "лет с первой выдачи", "finance",
               default=10, origin=ORIGIN_ENGINE,
               needed_when=("financing", (FINANCING_COMMERCIAL, FINANCING_PREFERENTIAL))),
    HotelField("grace_months", "Отсрочка погашения тела", "мес. с первой выдачи",
               "finance", default=0, origin="0 — тело гасится с ввода",
               hint="тело не гасится раньше ввода, сколько бы ни стояло здесь",
               needed_when=("financing", (FINANCING_COMMERCIAL, FINANCING_PREFERENTIAL))),
    HotelField("repayment", "Погашение", "", "finance", default=REPAY_ANNUITY,
               origin=ORIGIN_ENGINE, kind="choice", choices=REPAYMENTS,
               needed_when=("financing", (FINANCING_COMMERCIAL, FINANCING_PREFERENTIAL))),
    HotelField("dscr_target", "Целевой DSCR", "x", "finance",
               hint="для погашения «под DSCR»; ниже цели год помечается",
               needed_when=("repayment", (REPAY_SCULPTED,))),
    HotelField("hold_years", "Срок эксплуатации в расчёте", "лет", "exit",
               default=10, origin="умолчание движка"),
    HotelField("exit_mode", "Конец срока", "", "exit", default=EXIT_SALE,
               origin=ORIGIN_ENGINE, kind="choice", choices=EXITS),
    HotelField("valuation", "Оценка выхода", "", "exit", default=VALUATION_CAP,
               origin=ORIGIN_ENGINE, kind="choice", choices=VALUATIONS),
    HotelField("exit_cap_pct", "Ставка капитализации", "%", "exit",
               default=11.0, origin=ORIGIN_ENGINE,
               needed_when=("valuation", (VALUATION_CAP,))),
    HotelField("exit_multiple", "Мультипликатор EV/EBITDA", "x", "exit",
               needed_when=("valuation", (VALUATION_MULTIPLE,))),
    HotelField("exit_cost_pct", "Затраты на продажу", "% цены", "exit",
               default=1.0, origin=ORIGIN_ENGINE,
               needed_when=("exit_mode", (EXIT_SALE,))),
)
FIELD_BY_KEY: dict[str, HotelField] = {f.key: f for f in FIELDS}
PREFIX = "hotel_"


def field_defaults() -> dict[str, Any]:
    """Умолчания полей с приставкой: `hotel_<key>` → значение или пусто."""
    return {PREFIX + f.key: f.default for f in FIELDS}


def params_from_inputs(inputs: dict[str, Any] | None) -> dict[str, Any]:
    """Вводные гостиницы без приставки. Отсутствующее — None, не ноль."""
    x = inputs or {}
    return {f.key: x.get(PREFIX + f.key) for f in FIELDS}


def _blank(value: Any) -> bool:
    return value is None or (isinstance(value, str) and not value.strip())


def _is_needed(field: HotelField, params: dict[str, Any]) -> bool:
    if field.needed_when is None:
        return True
    owner, values = field.needed_when
    owner_value = params.get(owner)
    if _blank(owner_value):
        owner_value = FIELD_BY_KEY[owner].default
    if not _is_needed(FIELD_BY_KEY[owner], params):
        return False
    return str(owner_value) in values


def effective_params(params: dict[str, Any]) -> dict[str, Any]:
    """Вводные с умолчаниями там, где умолчание есть. Пустое без умолчания —
    остаётся пустым."""
    out = {}
    for f in FIELDS:
        value = params.get(f.key)
        out[f.key] = f.default if _blank(value) else value
    return out


def missing_fields(params: dict[str, Any], *, with_capex: bool = False
                   ) -> list[HotelField]:
    """Нужные расчёту поля, которых нет. Пустое — не ноль: без ADR выручки
    нет не потому, что она ноль, а потому, что её не задали.

    Поля стройки (`capex`) нужны движку, а не расчёту гостиницы: он получает
    затраты готовыми. `with_capex` — проверить и их."""
    full = effective_params(params)
    out = []
    for f in FIELDS:
        if not f.required or not _is_needed(f, full) or (f.capex and not with_capex):
            continue
        if _blank(full.get(f.key)):
            out.append(f)
            continue
        if f.kind == "number":
            try:
                float(full[f.key])
            except (TypeError, ValueError):
                out.append(f)
    return out


# --- даты -------------------------------------------------------------------

def add_months(value: date, months: int) -> date:
    index = value.year * 12 + value.month - 1 + int(months)
    return date(index // 12, index % 12 + 1, 1)


def month_index(start: date, month: date) -> int:
    return (month.year - start.year) * 12 + month.month - start.month


def month_days(month: date) -> int:
    return calendar.monthrange(month.year, month.month)[1]


def _as_date(value: Any, fallback: date) -> date:
    if isinstance(value, date):
        return date(value.year, value.month, 1)
    try:
        text = str(value or "").strip()[:10]
        parsed = date.fromisoformat(text)
        return date(parsed.year, parsed.month, 1)
    except ValueError:
        return fallback


def _num(params: dict[str, Any], key: str) -> float:
    value = params.get(key)
    try:
        return 0.0 if _blank(value) else float(value)
    except (TypeError, ValueError):
        return 0.0


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


# --- операции ---------------------------------------------------------------

def occupancy(months_open: int, start: float, target: float, ramp: int) -> float:
    """Загрузка месяца эксплуатации: линейно от старта до цели.

    Первый месяц — стартовая, месяц `ramp + 1` — целевая. Модели Домбая и
    UAI держат ту же прямую поквартально (старт + k/N разницы на квартал k).
    """
    if months_open <= 0:
        return 0.0
    ramp = max(0, int(ramp))
    if ramp == 0:
        return target
    progress = _clamp((months_open - 1) / ramp, 0.0, 1.0)
    return start + (target - start) * progress


@dataclass(frozen=True)
class Operations:
    keys: float
    adr: float
    price_date: date
    index: float
    occ_start: float
    occ_target: float
    ramp: int
    fnb: float
    other: float
    rooms_cost: float
    fnb_cost: float
    other_cost: float
    ag: float
    sm: float
    pom: float
    utilities: float
    base_fee: float
    incentive_fee: float
    ffe_reserve: float
    vat_relief_months: int
    revenue_multiplier: float


def operations_from_params(params: dict[str, Any], *, price_date: date,
                           revenue_multiplier: float = 1.0) -> Operations:
    p = effective_params(params)
    pct = lambda key: _num(p, key) / 100.0  # noqa: E731
    return Operations(
        keys=max(0.0, _num(p, "keys")),
        adr=max(0.0, _num(p, "adr_rub")),
        price_date=_as_date(p.get("adr_price_date"), price_date),
        index=pct("index_pct"),
        occ_start=_clamp(pct("occ_start_pct"), 0.0, 1.0),
        occ_target=_clamp(pct("occ_target_pct"), 0.0, 1.0),
        ramp=max(0, int(_num(p, "ramp_months"))),
        fnb=max(0.0, pct("fnb_pct")),
        other=max(0.0, pct("other_pct")),
        rooms_cost=max(0.0, pct("rooms_cost_pct")),
        fnb_cost=max(0.0, pct("fnb_cost_pct")),
        other_cost=max(0.0, pct("other_cost_pct")),
        ag=max(0.0, pct("ag_pct")),
        sm=max(0.0, pct("sm_pct")),
        pom=max(0.0, pct("pom_pct")),
        utilities=max(0.0, pct("utilities_pct")),
        base_fee=max(0.0, pct("base_fee_pct")),
        incentive_fee=max(0.0, pct("incentive_fee_pct")),
        ffe_reserve=max(0.0, pct("ffe_reserve_pct")),
        vat_relief_months=max(0, int(round(_num(p, "vat_relief_years") * 12))),
        revenue_multiplier=float(revenue_multiplier or 1.0),
    )


def operating_month(ops: Operations, month: date, months_open: int,
                    vat_rate: float) -> dict[str, float]:
    """Месяц работы гостиницы: номера, департаменты, USALI до GOP и сборы.

    Налог на имущество и страхование зависят от стоимости здания, а не от
    месяца работы, — их добавляет `hotel_flows`.
    """
    days = month_days(month)
    occ = occupancy(months_open, ops.occ_start, ops.occ_target, ops.ramp)
    growth = (1.0 + max(-0.95, ops.index)) ** (month_index(ops.price_date, month) / 12.0)
    adr = ops.adr * growth
    available = ops.keys * days
    sold = available * occ
    rooms = sold * adr * ops.revenue_multiplier
    fnb = rooms * ops.fnb
    other = (rooms + fnb) * ops.other
    departments = rooms + fnb + other
    relief = rooms * vat_rate if 0 < months_open <= ops.vat_relief_months else 0.0
    rooms_exp = rooms * ops.rooms_cost
    fnb_exp = fnb * ops.fnb_cost
    other_exp = other * ops.other_cost
    ag = departments * ops.ag
    sm = departments * ops.sm
    pom = departments * ops.pom
    utilities = departments * ops.utilities
    gop = departments - rooms_exp - fnb_exp - other_exp - ag - sm - pom - utilities
    base_fee = departments * ops.base_fee
    incentive = max(0.0, gop) * ops.incentive_fee
    reserve = departments * ops.ffe_reserve
    return {
        "days": days, "rooms_available": available, "rooms_sold": sold,
        "occupancy": occ, "adr": adr,
        "rooms_revenue": rooms, "fnb_revenue": fnb, "other_revenue": other,
        "department_revenue": departments, "vat_relief": relief,
        "rooms_expense": rooms_exp, "fnb_expense": fnb_exp, "other_expense": other_exp,
        "ag": ag, "sm": sm, "pom": pom, "utilities": utilities, "gop": gop,
        "base_fee": base_fee, "incentive_fee": incentive, "ffe_reserve": reserve,
    }


# Ряды месяца эксплуатации в порядке USALI — их же складывает годовой свод.
OPERATING_SERIES = (
    "rooms_available", "rooms_sold", "rooms_revenue", "fnb_revenue",
    "other_revenue", "department_revenue", "vat_relief",
    "rooms_expense", "fnb_expense", "other_expense", "ag", "sm", "pom",
    "utilities", "gop", "base_fee", "incentive_fee", "ffe_reserve",
)


def plan_horizon_end(plan: dict[str, Any]) -> date:
    """Последний месяц гостиницы: ввод + срок эксплуатации − 1."""
    params = effective_params(plan.get("params") or {})
    hold_years = max(1, int(_num(params, "hold_years") or 1))
    return add_months(plan["commissioning"], hold_years * 12 - 1)


# --- расчёт гостиницы -------------------------------------------------------

def hotel_flows(plan: dict[str, Any], key_rate: Callable[[date], float], *,
                vat_rate: float, profit_tax_rate: float,
                discount_rate: float) -> dict[str, Any]:
    """Денежный поток гостиничного проекта по месяцам.

    ``plan`` собирает движок:

    * ``commissioning`` — месяц ввода (первый месяц работы);
    * ``capex`` {месяц: ₽ с НДС} — ВСЕ затраты проекта, один раз посчитанные
      движком: здание, FF&E, участок, проект, сети, надбавки;
    * ``capex_ffe`` {месяц: ₽ с НДС} — из них мебель и оборудование;
    * ``capex_land`` {месяц: ₽} — из них участок и плата за ВРИ: без НДС, не
      амортизируются и не облагаются налогом на имущество;
    * ``params`` — вводные гостиницы без приставки (`params_from_inputs`);
    * ``start`` — начало проекта (дата цены ADR по умолчанию);
    * ``revenue_multiplier`` — множитель выручки сценария.

    Ставки налогов и дисконтирования — проекта, от движка. Возвращает ряды
    (ключ — первое число месяца), годовой свод, итоги и показатели. Всё, что
    уходит в общий расчёт, лежит в ``monthly``; движок складывает ряды и
    ничего не пересчитывает.
    """
    params = effective_params(plan.get("params") or {})
    missing = missing_fields(plan.get("params") or {})
    if missing:
        raise ValueError("не заданы: " + ", ".join(f.label for f in missing))
    commissioning: date = plan["commissioning"]
    capex = {m: float(v) for m, v in (plan.get("capex") or {}).items() if v}
    capex_ffe = {m: float(v) for m, v in (plan.get("capex_ffe") or {}).items() if v}
    capex_land = {m: float(v) for m, v in (plan.get("capex_land") or {}).items() if v}
    vat_share = vat_rate / (1.0 + vat_rate) if vat_rate > 0 else 0.0
    warnings: list[str] = []

    ops = operations_from_params(
        params, price_date=_as_date(plan.get("start"), commissioning),
        revenue_multiplier=float(plan.get("revenue_multiplier", 1.0) or 1.0))
    horizon_end = plan_horizon_end(plan)
    # Ряды начинаются с начала проекта, как месячные строки движка: NPV
    # дисконтирует от первого месяца ряда, и ряд, начатый с первой затраты,
    # дал бы другое число при тех же деньгах.
    start = plan.get("start")
    first = min([commissioning, *capex, *([_as_date(start, commissioning)] if start else [])])
    months: list[date] = []
    month = first
    while month <= horizon_end:
        months.append(month)
        month = add_months(month, 1)
    if any(m > horizon_end for m in capex):
        warnings.append("Часть затрат приходится на месяцы после конца срока и в расчёт не вошла.")

    m: dict[str, dict[date, float]] = defaultdict(lambda: defaultdict(float))

    # --- стоимость имущества --------------------------------------------
    capex = {mm: v for mm, v in capex.items() if mm <= horizon_end}
    capex_total = sum(capex.values())
    land_total = sum(capex_land.values())
    ffe_total = sum(capex_ffe.values())
    vat_bearing = max(0.0, capex_total - land_total)
    capex_vat = vat_bearing * vat_share
    capex_net = capex_total - capex_vat
    ffe_net = ffe_total * (1.0 - vat_share)
    building_net = max(0.0, capex_net - ffe_net - land_total)
    building_months = max(1, int(_num(params, "building_years") or 30)) * 12
    ffe_months = max(1, int(_num(params, "ffe_years") or 8)) * 12
    property_rate = max(0.0, _num(params, "property_tax_pct") / 100.0)
    insurance_rate = max(0.0, _num(params, "insurance_pct") / 100.0)

    # Входящий НДС стройки возмещается кварталом позже месяца затрат.
    for mm, value in capex.items():
        if mm > horizon_end:
            continue
        m["capex"][mm] = value
        vat = max(0.0, value - capex_land.get(mm, 0.0)) * vat_share
        if vat:
            m["vat_refund"][min(add_months(mm, 3), horizon_end)] += vat

    # --- эксплуатация ---------------------------------------------------
    # Срок расчёта и ещё 12 месяцев после него — одним правилом: EBITDA
    # следующих 12 месяцев (база оценки выхода) считается тем же месяцем
    # эксплуатации, с тем же износом здания, а не отдельной формулой.
    building_book = building_net
    ffe_book = ffe_net
    book_at_end = (building_net, ffe_net)
    forward_ebitda = 0.0
    forward = [add_months(horizon_end, k) for k in range(1, 13)]
    for month in [*months, *forward]:
        if month < commissioning:
            continue
        months_open = month_index(commissioning, month) + 1
        row = operating_month(ops, month, months_open, vat_rate)
        # Налог на имущество — со здания по остаточной стоимости (движимое
        # имущество с 2019 года не облагается); страхование — от CAPEX.
        dep_building = min(building_book, building_net / building_months)
        dep_ffe = min(ffe_book, ffe_net / ffe_months)
        property_tax = (building_book - dep_building / 2.0) * property_rate / 12.0
        insurance = (capex_net - land_total) * insurance_rate / 12.0
        building_book -= dep_building
        ffe_book -= dep_ffe
        revenue = row["department_revenue"] + row["vat_relief"]
        opex = (row["department_revenue"] - row["gop"] + row["base_fee"]
                + row["incentive_fee"] + row["ffe_reserve"])
        ebitda = revenue - opex - property_tax - insurance
        if month > horizon_end:
            forward_ebitda += ebitda
            continue
        for name in OPERATING_SERIES:
            m[name][month] = row[name]
        m["occupancy"][month] = row["occupancy"]
        m["adr"][month] = row["adr"]
        m["property_tax"][month] = property_tax
        m["insurance"][month] = insurance
        m["depreciation"][month] = dep_building + dep_ffe
        m["revenue"][month] = revenue
        m["opex"][month] = opex
        m["ebitda"][month] = ebitda
        if month == horizon_end:
            book_at_end = (building_book, ffe_book)
    building_book, ffe_book = book_at_end

    # --- выход ----------------------------------------------------------
    exit_mode = str(params.get("exit_mode") or EXIT_SALE)
    valuation = str(params.get("valuation") or VALUATION_CAP)
    if valuation == VALUATION_MULTIPLE:
        multiple = _num(params, "exit_multiple")
        exit_value = forward_ebitda * multiple if forward_ebitda > 0 else 0.0
    else:
        cap = _num(params, "exit_cap_pct") / 100.0
        if cap <= 0:
            warnings.append("Ставка капитализации не задана — стоимость выхода не считается.")
        exit_value = forward_ebitda / cap if cap > 0 and forward_ebitda > 0 else 0.0
    if forward_ebitda <= 0:
        warnings.append("EBITDA следующих 12 месяцев не положительна — стоимость выхода 0.")
    exit_cost = 0.0
    if exit_mode == EXIT_SALE:
        exit_cost = exit_value * max(0.0, _num(params, "exit_cost_pct") / 100.0)
        m["exit_revenue"][horizon_end] += exit_value
        m["exit_cost"][horizon_end] += exit_cost
    else:
        # Удержание: стоимость — оценка, а не поступление. Она закрывает
        # горизонт, чтобы IRR не считал гостиницу бесплатной, но без налога и
        # затрат продажи: сделки нет.
        m["residual_value"][horizon_end] += exit_value

    # --- кредит ---------------------------------------------------------
    financing = str(params.get("financing") or FINANCING_COMMERCIAL)
    loan_on = financing in (FINANCING_COMMERCIAL, FINANCING_PREFERENTIAL)
    loan_share = _clamp(_num(params, "loan_share_pct") / 100.0, 0.0, 1.0) if loan_on else 0.0
    fee_share = max(0.0, _num(params, "loan_fee_pct") / 100.0)
    spread = _num(params, "loan_spread_pp") / 100.0
    pref_share = _clamp(_num(params, "pref_key_share_pct") / 100.0, 0.0, 1.0)
    pref_margin = _num(params, "pref_margin_pp") / 100.0
    limit = (_num(params, "loan_limit_th_per_key") * 1000.0 * ops.keys
             if not _blank(params.get("loan_limit_th_per_key")) else None)
    term_months = max(1, int(_num(params, "loan_term_years") or 1)) * 12
    grace = max(0, int(_num(params, "grace_months")))
    repayment = str(params.get("repayment") or REPAY_ANNUITY)
    dscr_target = _num(params, "dscr_target")
    if repayment == REPAY_SCULPTED and dscr_target <= 0:
        dscr_target = 1.0
        warnings.append("Целевой DSCR не задан — погашение «под DSCR» идёт как 1,0.")

    def rate_of(month: date) -> float:
        kr = key_rate(month)
        if financing == FINANCING_PREFERENTIAL:
            return pref_share * kr + pref_margin
        return kr + spread

    balance = drawn = peak = 0.0
    first_draw: date | None = None
    maturity: date | None = None
    amort_start: date | None = None
    capped = 0.0
    for month in months:
        rate = rate_of(month) if loan_on else 0.0
        interest = balance * rate / 12.0
        if loan_on:
            m["loan_rate"][month] = rate
        if month < commissioning:
            m["loan_interest_cap"][month] = interest
            balance += interest
        else:
            m["loan_interest_paid"][month] = interest
        want = capex.get(month, 0.0) * loan_share if month <= commissioning else 0.0
        if want and limit is not None:
            room = max(0.0, limit - drawn)
            capped += max(0.0, want - room)
            want = min(want, room)
        if want > 0:
            first_draw = first_draw or month
            m["loan_draw"][month] = want
            m["loan_fee"][month] = want * fee_share
            balance += want
            drawn += want
        if first_draw and maturity is None:
            maturity = add_months(first_draw, term_months)
            amort_start = max(commissioning, add_months(first_draw, grace))
        repay = 0.0
        # Возмещённый НДС стройки гасит кредит первым: банк дал деньги и на
        # налог в составе затрат, и возмещение возвращается ему, а не
        # капиталу (НДС-транш). Без этого капитал получал бы деньги, которых
        # не вкладывал.
        refund = m["vat_refund"].get(month, 0.0)
        if balance > 0 and refund > 0:
            prepay = min(balance, refund)
            m["loan_vat_prepayment"][month] = prepay
            balance -= prepay
            repay_vat = prepay
        else:
            repay_vat = 0.0
        if balance > 0 and month >= commissioning:
            cash = m["ebitda"][month] - interest
            if month == horizon_end or (maturity is not None and month >= maturity):
                repay = balance  # срок или конец расчёта: остаток платит выход или капитал
            elif amort_start is not None and month >= amort_start:
                if repayment == REPAY_SWEEP:
                    repay = min(balance, max(0.0, cash))
                elif repayment == REPAY_SCULPTED:
                    service = max(0.0, m["ebitda"][month]) / dscr_target
                    repay = min(balance, max(0.0, service - interest))
                else:
                    left = month_index(month, maturity)
                    r = rate / 12.0
                    payment = (balance * r / (1.0 - (1.0 + r) ** -left)) if r else balance / left
                    repay = min(balance, max(0.0, payment - interest))
        if repay:
            balance -= repay
        if repay or repay_vat:
            m["loan_repayment"][month] = repay + repay_vat
        m["loan_balance"][month] = balance
        peak = max(peak, balance)
    if capped > 0:
        warnings.append(
            f"Лимит кредита {limit / 1e6:,.1f} млн ₽ ниже доли кредита в затратах: "
            f"{capped / 1e6:,.1f} млн ₽ сверх лимита платит капитал.".replace(",", " "))

    # --- налог на прибыль -----------------------------------------------
    for month in months:
        recognized = m["depreciation"][month]
        if month == horizon_end and exit_mode == EXIT_SALE:
            # Продажа списывает остаток стоимости, участок — целиком.
            recognized += max(0.0, building_book) + max(0.0, ffe_book) + land_total
        m["tax_margin"][month] = (m["ebitda"][month] + m["exit_revenue"][month]
                                  - m["exit_cost"][month] - recognized)
    financing_deduction = {mm: m["loan_interest_cap"][mm] + m["loan_interest_paid"][mm]
                           + m["loan_fee"][mm] for mm in months}
    tax_schedule, tax_detail = profit_tax_schedule(
        months, {mm: m["tax_margin"][mm] for mm in months}, financing_deduction,
        commissioning, profit_tax_rate)
    for mm, value in tax_schedule.items():
        if value:
            m["profit_tax"][mm] = value

    # --- деньги ---------------------------------------------------------
    project_cf: list[float] = []
    equity_cf: list[float] = []
    for month in months:
        # НДС к уплате гостиницы — только возмещение входящего НДС стройки
        # (с минусом): НДС эксплуатации — транзит (см. шапку модуля).
        vat_paid = -m["vat_refund"][month]
        m["vat_paid"][month] = vat_paid
        operating = (m["ebitda"][month] + m["exit_revenue"][month]
                     + m["residual_value"][month] - m["exit_cost"][month] - vat_paid)
        m["cash_to_equity"][month] = (
            operating - m["loan_interest_paid"][month] - m["loan_fee"][month]
            + m["loan_draw"][month] - m["loan_repayment"][month])
        m["project_cf"][month] = (operating - m["capex"][month]
                                  - m["loan_interest_cap"][month]
                                  - m["loan_interest_paid"][month] - m["loan_fee"][month]
                                  - m["profit_tax"][month])
        m["equity_cf"][month] = (m["cash_to_equity"][month] - m["capex"][month]
                                 - m["profit_tax"][month])
        m["fcff"][month] = operating - m["capex"][month] - m["profit_tax"][month]
        project_cf.append(m["project_cf"][month])
        equity_cf.append(m["equity_cf"][month])

    annual = annual_table(months, m)
    dscr_by_year = [row["dscr"] for row in annual if row.get("dscr") is not None]
    if dscr_target > 0:
        low = [row["year"] for row in annual
               if row.get("dscr") is not None and row["dscr"] < dscr_target - 1e-9]
        if low:
            warnings.append("DSCR ниже цели " + f"{dscr_target:.2f}".replace(".", ",")
                            + " в годы: " + ", ".join(str(y) for y in low) + ".")
    stabilized = _stabilized_year(annual, commissioning, ops.ramp)

    def total(name: str) -> float:
        return float(sum(m[name].values()))

    repaid = next((mm for mm in months if mm >= commissioning
                   and m["loan_repayment"][mm] and not m["loan_balance"][mm]), None)
    revenue_total = total("revenue")
    kpi = {
        "keys": ops.keys,
        "capex": capex_total, "capex_net": capex_net, "capex_vat": capex_vat,
        "capex_per_key": capex_total / ops.keys if ops.keys else 0.0,
        "building_net": building_net, "ffe_net": ffe_net, "land": land_total,
        "adr_first_year": annual_first(annual, "adr"),
        "stabilized_year": stabilized.get("year"),
        "stabilized_occupancy": stabilized.get("occupancy"),
        "stabilized_adr": stabilized.get("adr"),
        "stabilized_revpar": stabilized.get("revpar"),
        "stabilized_revenue": stabilized.get("revenue"),
        "stabilized_gop": stabilized.get("gop"),
        "stabilized_ebitda": stabilized.get("ebitda"),
        "gop_margin": total("gop") / total("department_revenue") if total("department_revenue") else 0.0,
        "ebitda_margin": total("ebitda") / revenue_total if revenue_total else 0.0,
        "yield_on_cost": (stabilized.get("ebitda") or 0.0) / capex_net if capex_net else 0.0,
        "forward_ebitda": forward_ebitda,
        "exit_value": exit_value, "exit_month": horizon_end,
        "exit_mode": exit_mode, "valuation": valuation,
        "loan_peak": peak, "loan_drawn": drawn, "loan_maturity": maturity,
        "loan_repaid_month": repaid,
        "dscr_by_year": dscr_by_year,
        "dscr_min": min(dscr_by_year) if dscr_by_year else None,
        "profit_tax": total("profit_tax"),
        "npv_project": monthly_npv(project_cf, discount_rate),
        "irr_project": monthly_irr(project_cf),
        "npv_equity": equity_npv(equity_cf, discount_rate),
        "irr_equity": monthly_irr(equity_cf),
        "pbp_years": payback_years(project_cf),
        "dpbp_years": payback_years(project_cf, discount_rate),
        "equity_pbp_years": payback_years(equity_cf),
        "discount_rate": discount_rate,
    }
    totals = {name: total(name) for name in (
        *OPERATING_SERIES, "revenue", "opex", "property_tax", "insurance", "ebitda",
        "depreciation", "exit_revenue", "exit_cost", "residual_value", "vat_paid",
        "vat_refund", "loan_draw", "loan_fee", "loan_repayment", "profit_tax",
        "cash_to_equity", "tax_margin")}
    totals["loan_interest"] = total("loan_interest_cap") + total("loan_interest_paid")
    totals["capex"] = capex_total
    return {
        "strategy": "hotel",
        "months": months,
        "commissioning": commissioning,
        "horizon_end": horizon_end,
        "monthly": {name: {mm: value for mm, value in series.items() if value}
                    for name, series in m.items()},
        "annual": annual,
        "totals": totals,
        "kpi": kpi,
        "project_cf": project_cf,
        "equity_cf": equity_cf,
        "tax_detail": tax_detail,
        "warnings": warnings,
        "params": params,
    }


def payback_years(flows: list[float], discount_rate: float | None = None) -> float | None:
    """Срок окупаемости в годах от первого месяца ряда; None — не окупается.

    Дисконтированный — той же месячной ставкой, что `monthly_npv`. Месяц, в
    котором накопленный итог переходит через ноль, делится пропорционально.
    """
    rate = 0.0 if discount_rate is None else pow(1.0 + max(discount_rate, -0.999999), 1 / 12) - 1.0
    cumulative = 0.0
    went_negative = False
    for i, cf in enumerate(flows):
        value = cf / (1.0 + rate) ** i if rate else cf
        before = cumulative
        cumulative += value
        if cumulative < -1e-9:
            went_negative = True
        if went_negative and before < 0 <= cumulative:
            share = -before / value if value else 0.0
            return (i + share) / 12.0
    return None


# Строки годового свода USALI: (ключ, подпись, ряд-источник или None).
ANNUAL_ROWS: tuple[tuple[str, str], ...] = (
    ("rooms_available", "Номеро-ночи в продаже"),
    ("rooms_sold", "Проданные номеро-ночи"),
    ("occupancy", "Загрузка"),
    ("adr", "ADR, ₽ без НДС"),
    ("revpar", "RevPAR, ₽ без НДС"),
    ("rooms_revenue", "Выручка номерного фонда"),
    ("fnb_revenue", "Выручка F&B"),
    ("other_revenue", "Выручка прочих департаментов"),
    ("department_revenue", "Выручка департаментов"),
    ("vat_relief", "Льгота НДС на проживание"),
    ("revenue", "Выручка всего"),
    ("rooms_expense", "Расходы номерного фонда"),
    ("fnb_expense", "Расходы F&B"),
    ("other_expense", "Расходы прочих департаментов"),
    ("ag", "A&G"),
    ("sm", "S&M"),
    ("pom", "POM"),
    ("utilities", "Utilities"),
    ("gop", "GOP"),
    ("base_fee", "Базовое вознаграждение оператора"),
    ("incentive_fee", "Поощрительное вознаграждение оператора"),
    ("ffe_reserve", "Резерв FF&E"),
    ("property_tax", "Налог на имущество"),
    ("insurance", "Страхование"),
    ("ebitda", "EBITDA"),
    ("depreciation", "Амортизация"),
    ("interest", "Проценты по кредиту"),
    ("profit_tax", "Налог на прибыль"),
    ("debt_service", "Обслуживание долга (проценты + тело)"),
    ("dscr", "DSCR (EBITDA ÷ обслуживание)"),
    ("capex", "CAPEX с НДС"),
    ("fcff", "Поток до финансирования (FCFF)"),
    ("equity_cf", "Поток капитала (FCFE)"),
)


def annual_table(months: list[date], m: dict[str, dict[date, float]]) -> list[dict[str, Any]]:
    """Годовой USALI по календарным годам — свод тех же месяцев."""
    years: dict[int, list[date]] = defaultdict(list)
    for mm in months:
        years[mm.year].append(mm)
    out = []
    for year, span in sorted(years.items()):
        row: dict[str, Any] = {"year": year, "months": len(span)}
        for name in ("rooms_available", "rooms_sold", "rooms_revenue", "fnb_revenue",
                     "other_revenue", "department_revenue", "vat_relief", "revenue",
                     "rooms_expense", "fnb_expense", "other_expense", "ag", "sm", "pom",
                     "utilities", "gop", "base_fee", "incentive_fee", "ffe_reserve",
                     "property_tax", "insurance", "ebitda", "depreciation", "profit_tax",
                     "fcff", "equity_cf", "loan_repayment", "exit_revenue",
                     "residual_value", "capex"):
            row[name] = float(sum(m[name].get(mm, 0.0) for mm in span))
        row["interest"] = float(sum(m["loan_interest_cap"].get(mm, 0.0)
                                    + m["loan_interest_paid"].get(mm, 0.0) for mm in span))
        paid = float(sum(m["loan_interest_paid"].get(mm, 0.0) for mm in span))
        # Тело в DSCR — плановое: возмещённый НДС стройки и остаток, гасимый
        # выходом в последний месяц расчёта, обслуживанием года не считаются.
        last = span[-1]
        scheduled = (row["loan_repayment"]
                     - float(sum(m["loan_vat_prepayment"].get(mm, 0.0) for mm in span))
                     - (m["loan_repayment"].get(last, 0.0)
                        - m["loan_vat_prepayment"].get(last, 0.0)
                        if last == months[-1] else 0.0))
        row["debt_service"] = paid + max(0.0, scheduled)
        row["dscr"] = (row["ebitda"] / row["debt_service"]
                       if row["debt_service"] > 1.0 and row["rooms_available"] > 0 else None)
        row["occupancy"] = (row["rooms_sold"] / row["rooms_available"]
                            if row["rooms_available"] else 0.0)
        row["adr"] = row["rooms_revenue"] / row["rooms_sold"] if row["rooms_sold"] else 0.0
        row["revpar"] = (row["rooms_revenue"] / row["rooms_available"]
                         if row["rooms_available"] else 0.0)
        out.append(row)
    return out


def annual_first(annual: list[dict[str, Any]], key: str) -> float | None:
    for row in annual:
        if row.get("rooms_available"):
            return row.get(key)
    return None


def _stabilized_year(annual: list[dict[str, Any]], commissioning: date,
                     ramp: int) -> dict[str, Any]:
    """Первый полный календарный год, целиком на целевой загрузке."""
    target_from = add_months(commissioning, max(0, ramp))
    for row in annual:
        if row["months"] == 12 and row["rooms_available"] and date(row["year"], 1, 1) >= target_from:
            return row
    full = [row for row in annual if row["months"] == 12 and row["rooms_available"]]
    return full[-1] if full else {}
