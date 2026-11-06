"""Погашение кредитов и покрытие обязательств эскроу (ТЗ владельца «Кутузов Сити»).

Отвечает на четыре вопроса сводки руководству и Монитора проекта: когда и
сколько платить банку, сколько к этим датам будет на эскроу, сколько из него
раскроется и пойдёт на погашение, сколько денег не хватит и когда. Отдельно
по каждой НКЛ и сводно.

Расчёт здесь один: сводка (`developaid_management_report`) и Монитор
(`/monitor/credit`) только читают `analyse` и рисуют `render_html`.

Устройство (подробно — `docs/credit_repayment.md`):

* условия кредитов — `PRESETS` по выписке договоров
  (`docs/projects/kutuzov_credit_terms.md`): у каждого условия пункт договора
  или пометка «допущение» / «нет данных». Выписка договора заменяет условие
  набором ``terms.<НКЛ>`` / ``terms.project``;
* исходные данные — наборы `DATASETS`, у каждого дата актуальности и
  источник. Нет набора — «нет данных», а не ноль;
* обе НКЛ считаются в одном дневном цикле (`_simulate`): ставка НКЛ 2026
  зависит от долга НКЛ 2025, раскрытие эскроу у них общее. Ставка месяца — по
  среднедневным остаткам и покрытию эскроу (`segment_rate`), в отсрочку —
  капитализация, дальше — уплата 28-го следующего месяца; раскрытие делает
  долг срочным в размере раскрытого;
* эскроу — один на проект: начальный остаток + поступления по действующим
  ДДУ + новые продажи − возвраты − раскрытие, по датам оплаты;
* покрытие — по датам подряд (`_cover`): раскрытое, свободные деньги,
  подтверждённое финансирование; потраченное второй раз не участвует;
* достаточность эскроу (А п. 8.2.60) — `sufficiency`, ковенанты — `covenants`.
"""

from __future__ import annotations

import calendar
import copy
import datetime
import fcntl
import hashlib
import html
import json
from pathlib import Path
from typing import Any

M = 1_000_000.0

TZ = "ТЗ владельца «Кутузов Сити»"
NO_DATA = "нет данных"

# --------------------------------------------------------------------------
# Условия кредитов
# --------------------------------------------------------------------------

DOC = "выписка условий договоров (docs/projects/kutuzov_credit_terms.md)"
_A = f"{DOC}, договор А (НКЛ от 04.04.2025)"
_B = f"{DOC}, договор Б (НКЛ от 26.06.2026)"
_NO_OU = ("нет данных: Общих условий банка (ОУ Сбербанка) в документах нет — "
          "принято как в договоре А")

PRESETS: dict[str, dict[str, Any]] = {
    "kutuzov_city": {
        "title": "Кутузов Сити",
        # Проект Монитора, к которому относятся эти договоры (псевдонимы —
        # через `monitor._project_dir`): привязка явная, не по похожему имени.
        "projects": ["Кутузов Сити"],
        "loans": [
            {"id": "nkl2025", "name": "НКЛ от 04.04.2025", "short": "НКЛ 2025",
             "limit": 5485.689 * M,
             # Лимит нарастающий (п. 1.1 ред. ДС-3). До 31.12.2025 — после
             # выполнения п. 3.3.25; прогноз начинается позже, поэтому это
             # условие на расчёт не влияет.
             "limit_steps": [("2025-04-04", 2600.0 * M), ("2026-01-01", 5000.0 * M),
                             ("2027-01-01", 5485.689 * M)],
             "availability_end": "2027-06-30", "maturity": "2029-03-30",
             "margin_pp": 4.78, "fee_free_limit_pct": 0.70,
             "deferral_limit": "2027-09-30",
             # База — долг на дату окончания доступности (п. 6.1).
             "base": "debt_at_availability_end",
             "schedule": [("2027-09-30", 0.61), ("2027-12-30", 0.07),
                          ("2028-03-30", 0.07), ("2028-06-30", 0.07),
                          ("2028-09-30", 0.08), ("2028-12-30", 0.08),
                          ("2029-03-30", 0.02)],
             # п. 4.1.1: I(a), I(v) ниже 100 % покрытия и по ступеням покрытия.
             "rate_table": {"ia": 2.02, "iv_below": 4.26,
                            "iv_steps": [(1.10, 4.26), (1.20, 2.56), (1.25, 0.86)],
                            "iv_top": 0.01},
             "terms": {
                 "rate": {"value": "contract", "source": f"{_A}, п. 4.1.1"},
                 "escrow_in_rate": {
                     "value": "full",
                     "source": f"{_A}, п. 4.1.1: F — весь остаток эскроу проекта. Банк вправе "
                               "применить и к А долю, как в Б (п. 7.1.4), — подтвердить с банком"},
                 "pay_dates": {"value": "monthly_28", "source": f"{_A}, пп. 4.1.1, 4.2.1"},
                 "day_basis": {"value": "actual", "source": f"{_A}, п. 5.5"},
                 "deferred_rate": {"value": "base", "source": f"{_A}, пп. 4.2.2, 4.2.3"},
                 "prepayment_order": {
                     "value": "nearest",
                     "source": f"{_A}, пп. 6.1, 6.2, 5.9: досрочное уменьшает ближайшие платежи; "
                               "возмещение НДС (п. 8.2.30) — последние"},
                 "disclosure_repays": {"value": "immediate", "source": f"{_A}, п. 6.1.2"},
                 "fee": {"value": "free_limit", "source": f"{_A}, п. 4.4"},
             },
             "source": f"{_A}; {TZ}, п. 2–3"},
            {"id": "nkl2026", "name": "НКЛ от 26.06.2026", "short": "НКЛ 2026",
             "limit": 1125.000 * M,
             "limit_steps": [("2026-06-26", 1125.0 * M)],
             "availability_end": "2027-09-30", "maturity": "2029-09-30",
             "margin_pp": 4.14, "fee_free_limit_pct": 0.70,
             "deferral_limit": "2029-03-30",
             # База — выбранный лимит на следующий день после доступности (п. 5.1).
             "base": "drawn_day_after_availability_end",
             # Последний платёж — остаток (номинально 38 %).
             "schedule": [("2029-03-30", 0.23), ("2029-06-30", 0.39),
                          ("2029-09-30", None)],
             "rate_table": {"ia": 0.70, "iv_below": 4.75,
                            "iv_steps": [(1.10, 4.75), (1.20, 3.39), (1.30, 2.04),
                                         (1.40, 0.68)],
                            "iv_top": 0.01},
             "terms": {
                 "rate": {"value": "analogy",
                          "source": f"Допущение: формула п. 3.3.8.2 Общих условий банка не "
                                    f"получена — порядок как в договоре А, коэффициенты договора "
                                    f"Б ({_B}, п. 3.1.1 ред. ДС-2)"},
                 "escrow_in_rate": {
                     "value": "share",
                     "source": f"{_B}, п. 3.1.1: доля эскроу пропорционально чистому долгу Б в "
                               "совокупном чистом долге А и Б"},
                 "pay_dates": {"value": "monthly_28", "source": f"{_B}, п. 3.1.1 ред. ДС-2"},
                 "day_basis": {"value": "actual", "source": _NO_OU},
                 "deferred_rate": {"value": "base", "source": f"{_B}, п. 3.3 ред. ДС-1"},
                 "prepayment_order": {"value": "nearest", "source": _NO_OU},
                 "disclosure_repays": {
                     "value": "immediate",
                     "source": f"{_B}, п. 5.1.1 (Вариант 1 п. 3.6.6 Общих условий — текста нет)"},
                 "fee": {"value": "free_limit", "source": f"{_B}, п. 4.1"},
             },
             "source": f"{_B}; {TZ}, п. 2–3"},
        ],
        "terms": {
            "disclosure_split": {
                "value": "nkl2025_first",
                "source": "нет данных: как раскрытое эскроу делится между НКЛ, в договорах не "
                          "найдено. Принято — сначала НКЛ 2025 (по графикам она гасится первой). "
                          "Подтвердить с банком (ТЗ, п. 5)"},
            "planned_disclosure": {
                "value": "2027-09-30",
                "source": "допущение: плановой даты раскрытия в договорах нет; регистрация "
                          "собственности не позднее 27.12.2027 за 90 дней после ввода "
                          f"({_A}, п. 8.2.27) — ввод около конца сентября 2027"},
        },
    },
}

TERM_VALUES = {"rate": {"contract", "analogy", "base", "model"}, "escrow_in_rate": {"full", "share"},
               "pay_dates": {"monthly_28"}, "day_basis": {"actual", "365"},
               "deferred_rate": {"base"},
               "prepayment_order": {"from_last", "nearest", "pro_rata"},
               "disclosure_repays": {"immediate", "pool"}, "fee": {"free_limit"},
               "disclosure_split": {"pro_rata", "nkl2025_first", "nkl2026_first"},
               "planned_disclosure": None}


# --------------------------------------------------------------------------
# Наборы исходных данных
# --------------------------------------------------------------------------

DATASETS: dict[str, str] = {
    "facts.nkl2025": "Долг, выдачи и погашения по НКЛ от 04.04.2025",
    "facts.nkl2026": "Долг, выдачи и погашения по НКЛ от 26.06.2026",
    "plan.nkl2025": "Прогнозные выборки и досрочные погашения по НКЛ от 04.04.2025",
    "plan.nkl2026": "Прогнозные выборки и досрочные погашения по НКЛ от 26.06.2026",
    "deferred.nkl2025": "Отложенные проценты и проценты на них по НКЛ от 04.04.2025",
    "deferred.nkl2026": "Отложенные проценты и проценты на них по НКЛ от 26.06.2026",
    "escrow": "Остаток на эскроу",
    "contracts": "Поступления по заключённым ДДУ, включая рассрочки",
    "sales": "Прогноз новых продаж",
    "refunds": "Возвраты и расторжения",
    "disclosure": "Раскрытие эскроу: даты и суммы",
    "letters_of_credit": "Остатки на аккредитивах",
    "free_cash": "Свободные деньги проекта после обязательных расходов",
    "extra": "Дополнительные источники финансирования",
    "key_rate": "Прогноз ключевой ставки",
    "terms.nkl2025": "Условия НКЛ от 04.04.2025 из выписки договора",
    "terms.nkl2026": "Условия НКЛ от 26.06.2026 из выписки договора",
    "terms.project": "Условия по проекту в целом (раскрытие эскроу между НКЛ, плановая дата)",
    "business_plan": "Бизнес-план, согласованный с банком: эскроу и продажи по ДДУ",
}
UNITS = {"млн ₽": M, "₽": 1.0}
# Наборы без денежных сумм — единица им не нужна.
_UNITLESS = {"key_rate", "terms.nkl2025", "terms.nkl2026", "terms.project"}

STRESS_DEFAULT = {"inflow_cut_pct": 20.0, "disclosure_delay_months": 3, "key_rate_pp": 2.0}


# --------------------------------------------------------------------------
# Даты и числа
# --------------------------------------------------------------------------

def _day(value: Any) -> datetime.date:
    if isinstance(value, datetime.date):
        return value
    return datetime.date.fromisoformat(str(value)[:10])


def _month_end(month: str) -> datetime.date:
    year, mon = int(month[:4]), int(month[5:7])
    return datetime.date(year, mon, calendar.monthrange(year, mon)[1])


def _add_months(day: datetime.date, months: int) -> datetime.date:
    total = day.year * 12 + day.month - 1 + months
    year, mon = divmod(total, 12)
    last = calendar.monthrange(year, mon + 1)[1]
    return datetime.date(year, mon + 1, min(day.day, last))


def _year_days(day: datetime.date, basis: str) -> int:
    if basis == "365":
        return 365
    return 366 if calendar.isleap(day.year) else 365


def _known(*values: Any) -> bool:
    return all(value is not None for value in values)


def _sum(*values: float | None) -> float | None:
    return sum(values) if _known(*values) else None


def mln(value: float | None, digits: int = 3) -> str:
    """«3 346,270» — млн ₽ с тремя знаками; неизвестное — «нет данных»."""
    if value is None:
        return NO_DATA
    text = f"{abs(value) / M:,.{digits}f}".replace(",", " ").replace(".", ",")
    return ("−" if value < 0 and round(abs(value) / M, digits) else "") + text


def ddmmyyyy(value: Any) -> str:
    return _day(value).strftime("%d.%m.%Y") if value else NO_DATA


# --------------------------------------------------------------------------
# Чтение и проверка наборов
# --------------------------------------------------------------------------

def _num(value: Any, what: str) -> float:
    if isinstance(value, bool) or value is None or value == "":
        raise ValueError(f"{what}: нужна сумма числом")
    try:
        return float(str(value).replace(" ", "").replace(",", "."))
    except ValueError:
        raise ValueError(f"{what}: «{value}» — не число") from None


def _iso(value: Any, what: str) -> str:
    try:
        return _day(value).isoformat()
    except (TypeError, ValueError):
        raise ValueError(f"{what}: дата «{value}» не разобрана, нужна ГГГГ-ММ-ДД") from None


def _month(value: Any, what: str) -> str:
    text = str(value or "")[:7]
    try:
        datetime.date(int(text[:4]), int(text[5:7]), 1)
    except ValueError:
        raise ValueError(f"{what}: месяц «{value}» не разобран, нужен ГГГГ-ММ") from None
    return text


def _quarter(value: Any, what: str) -> str:
    """«2026 Q3» — календарный квартал."""
    text = str(value or "").strip()
    try:
        year, part = text.split(" Q")
        if not 1 <= int(part) <= 4:
            raise ValueError
        return f"{int(year)} Q{int(part)}"
    except ValueError:
        raise ValueError(f"{what}: квартал «{value}» не разобран, нужен «ГГГГ QN»") from None


def _when(item: dict[str, Any], what: str) -> dict[str, Any]:
    """Дата оплаты: точная (``date``) или только месяц (``month``)."""
    if item.get("date"):
        return {"date": _iso(item["date"], what), "month_only": False}
    if item.get("month"):
        month = _month(item["month"], what)
        return {"date": _month_end(month).isoformat(), "month_only": True}
    raise ValueError(f"{what}: нужна дата оплаты (date) или месяц (month)")


def _payments(items: Any, scale: float, what: str) -> list[dict[str, Any]]:
    out = []
    for i, item in enumerate(items or []):
        label = f"{what}, строка {i + 1}"
        row = dict(_when(item, label), amount=_num(item.get("amount"), label) * scale)
        if item.get("contract"):
            row["contract"] = str(item["contract"]).strip()
        out.append(row)
    return out


def _dated(items: Any, scale: float, what: str, flags: tuple[str, ...] = ()) -> list[dict]:
    out = []
    for i, item in enumerate(items or []):
        label = f"{what}, строка {i + 1}"
        row = {"date": _iso(item.get("date"), label),
               "amount": _num(item.get("amount"), label) * scale}
        for flag in flags:
            if not isinstance(item.get(flag), bool):
                raise ValueError(f"{label}: признак «{flag}» нужен явно — да или нет")
            row[flag] = item[flag]
        if item.get("what"):
            row["what"] = str(item["what"])[:200]
        out.append(row)
    return out


def _expand_sales(items: Any, scale: float) -> list[dict[str, Any]]:
    """Продажа → поступления по датам оплаты: первый взнос и рассрочка.

    Продажа месяца ``month`` на ``amount`` (или ``area`` × ``price``): доля
    ``down_share`` — в месяце продажи, остаток — равными долями
    ``installment_months`` следующих месяцев. Без рассрочки — вся сумма сразу.
    """
    out = []
    for i, item in enumerate(items or []):
        label = f"Прогноз продаж, строка {i + 1}"
        month = _month(item.get("month"), label)
        if item.get("amount") not in (None, ""):
            amount = _num(item["amount"], label) * scale
        else:
            amount = _num(item.get("area"), label + ", площадь") * _num(
                item.get("price"), label + ", цена за м²") * scale
        months = int(item.get("installment_months") or 0)
        if months < 0:
            raise ValueError(f"{label}: срок рассрочки не может быть отрицательным")
        if months and item.get("down_share") in (None, ""):
            raise ValueError(f"{label}: при рассрочке нужен первый взнос (down_share)")
        down = _num(item["down_share"], label) if months else 1.0
        if not 0 <= down <= 1:
            raise ValueError(f"{label}: первый взнос — доля от 0 до 1")
        contract = str(item.get("contract") or "").strip()
        start = _month_end(month)
        out.append({"signed_total": amount, "sale_month": month, "date": start.isoformat(),
                    "month_only": True, "amount": 0.0,
                    **({"contract": contract} if contract else {})})
        steps = [(start, amount * down)] + [
            (_month_end(_add_months(start.replace(day=1), k).strftime("%Y-%m")),
             amount * (1 - down) / months) for k in range(1, months + 1)]
        for day, value in steps:
            if value:
                out.append({"date": day.isoformat(), "month_only": True, "amount": value,
                            "sale_month": month, **({"contract": contract} if contract else {})})
    return out


def normalize(name: str, payload: dict[str, Any]) -> dict[str, Any]:
    """Проверить набор и привести суммы к рублям. Ошибка — словами, с местом."""
    if name not in DATASETS:
        raise ValueError(f"Неизвестный набор данных «{name}».")
    what = DATASETS[name]
    as_of = _iso(payload.get("as_of"), f"{what}: дата актуальности")
    source = str(payload.get("source") or "").strip()
    if not source:
        raise ValueError(f"{what}: укажите источник (например, «выписка банка»).")
    data = payload.get("data")
    if not isinstance(data, dict):
        raise ValueError(f"{what}: нет данных набора.")
    unit = str(payload.get("unit") or "").strip()
    if name in _UNITLESS:
        scale = 1.0
    elif unit not in UNITS:
        raise ValueError(f"{what}: укажите единицу сумм — «млн ₽» или «₽».")
    else:
        scale = UNITS[unit]
    kind = name.split(".")[0]
    if kind == "facts":
        out: dict[str, Any] = {key: _num(data.get(key), f"{what}: {label}") * scale
                               for key, label in (("debt", "долг"), ("drawn", "выбрано всего"),
                                                  ("accrued_interest", "начислено процентов с "
                                                   "последней уплаты"),
                                                  ("accrued_fee", "начислено комиссии с "
                                                   "последней уплаты"))}
        ops = []
        for i, item in enumerate(data.get("operations") or []):
            label = f"{what}, операция {i + 1}"
            if item.get("kind") not in {"draw", "repay", "prepay"}:
                raise ValueError(f"{label}: вид — выдача (draw), плановое погашение (repay) "
                                 "или досрочное (prepay)")
            ops.append({"date": _iso(item.get("date"), label), "kind": item["kind"],
                        "amount": _num(item.get("amount"), label) * scale})
        out["operations"] = ops
        if data.get("schedule_base") not in (None, ""):
            out["schedule_base"] = _num(data["schedule_base"], f"{what}: расчётная база") * scale
    elif kind == "plan":
        out = {"draws": _dated(data.get("draws"), scale, f"{what}: выборки"),
               "prepayments": _dated(data.get("prepayments"), scale,
                                     f"{what}: досрочные погашения")}
    elif kind == "deferred":
        out = {"deferred": _num(data.get("deferred"), f"{what}: отложенные проценты") * scale,
               "interest_on_deferred": _num(data.get("interest_on_deferred"),
                                            f"{what}: проценты на них") * scale}
    elif name in {"escrow", "letters_of_credit"}:
        out = {"balance": _num(data.get("balance"), f"{what}: остаток") * scale}
        if name == "letters_of_credit":
            # Покрытие аккредитивов входит в ставку каждой НКЛ своим остатком (п. 4.1.1).
            out["by_loan"] = {key: _num(value, f"{what}: {key}") * scale
                              for key, value in (data.get("by_loan") or {}).items()}
        else:
            # Остатки на прошлые даты — для проверки наполнения эскроу (п. 8.2.57).
            out["history"] = _dated([{"date": i.get("date"), "amount": i.get("balance")}
                                     for i in data.get("history") or []], scale,
                                    f"{what}: история остатков")
    elif name in {"contracts", "refunds"}:
        out = {"payments": _payments(data.get("payments"), scale, what)}
        if name == "contracts":
            # Суммы цен подписанных ДДУ по месяцам — для ковенанта продаж.
            out["signed"] = [{"month": _month(i.get("month"), f"{what}: подписано"),
                              "amount": _num(i.get("amount"), f"{what}: подписано") * scale}
                             for i in data.get("signed") or []]
    elif name == "sales":
        out = {"payments": _payments(data.get("payments"), scale, what)
               + _expand_sales(data.get("sales"), scale)}
    elif name == "business_plan":
        out = {"escrow": _dated(data.get("escrow"), scale, f"{what}: эскроу"),
               "ddu": [{"quarter": _quarter(i.get("quarter"), f"{what}: квартал"),
                        "amount": _num(i.get("amount"), f"{what}: ДДУ") * scale}
                       for i in data.get("ddu") or []]}
    elif name == "disclosure":
        items = []
        for i, item in enumerate(data.get("items") or []):
            label = f"{what}, строка {i + 1}"
            row = {"date": _iso(item.get("date"), label),
                   # Пустая сумма — раскрывается всё, что на эскроу к этой дате.
                   "amount": (None if item.get("amount") in (None, "")
                              else _num(item["amount"], label) * scale)}
            for flag in ("confirmed", "final"):
                if not isinstance(item.get(flag), bool):
                    raise ValueError(f"{label}: признак «{flag}» нужен явно — да или нет")
                row[flag] = item[flag]
            items.append(row)
        out = {"items": items}
    elif name == "free_cash":
        out = {"items": _dated(data.get("items"), scale, what)}
    elif name == "extra":
        out = {"items": _dated(data.get("items"), scale, what, ("confirmed",))}
    elif name == "key_rate":
        path = []
        for i, item in enumerate(data.get("path") or []):
            label = f"{what}, строка {i + 1}"
            path.append({"from": _iso(item.get("from"), label),
                         "rate": _num(item.get("rate"), label + ", ставка, % годовых")})
        if not path:
            raise ValueError(f"{what}: нужна хотя бы одна ставка с датой начала.")
        out = {"path": sorted(path, key=lambda x: x["from"])}
    else:  # terms
        out = {}
        for key, item in data.items():
            if key not in TERM_VALUES:
                raise ValueError(f"{what}: неизвестное условие «{key}».")
            value = str((item or {}).get("value") or "")
            if key == "planned_disclosure":
                value = _iso(value, f"{what}: плановая дата раскрытия")
            elif value not in TERM_VALUES[key]:
                raise ValueError(f"{what}: условие «{key}» = «{value}» не поддержано.")
            clause = str((item or {}).get("source") or "").strip()
            if not clause:
                raise ValueError(f"{what}: у условия «{key}» нужен пункт договора.")
            out[key] = {"value": value, "source": clause}
    return {"name": name, "as_of": as_of, "source": source[:300],
            "unit": unit or None, "data": out}


# --------------------------------------------------------------------------
# Хранение (каталог проекта Монитора, два воркера — под замком)
# --------------------------------------------------------------------------

def _folder(project: str, create: bool = True) -> Path:
    import developaid_monitor as monitor

    folder = monitor._project_dir(project) / "credit"
    if create:
        folder.mkdir(parents=True, exist_ok=True)
    return folder


def _locked(folder: Path):
    handle = (folder / ".lock").open("a+")
    fcntl.flock(handle, fcntl.LOCK_EX)
    return handle


def load(project: str) -> dict[str, Any]:
    """Сохранённые наборы проекта: {"preset": ..., "datasets": {имя: набор}}."""
    path = _folder(project, create=False) / "inputs.json"
    if not path.exists():
        return {"preset": None, "datasets": {}}
    return json.loads(path.read_text(encoding="utf-8"))


def save(project: str, items: list[dict[str, Any]], author: str,
         preset: str = "kutuzov_city") -> dict[str, Any]:
    """Положить наборы (каждый проверен целиком до записи) и журнал правки."""
    if preset not in PRESETS:
        raise ValueError(f"Неизвестные условия кредитов «{preset}».")
    clean = [normalize(str(item.get("name") or ""), item) for item in items]
    if not clean:
        raise ValueError("Нет наборов данных для загрузки.")
    folder = _folder(project)
    handle = _locked(folder)
    try:
        current = load(project)
        current["preset"] = preset
        now = datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")
        with (folder / "journal.jsonl").open("a", encoding="utf-8") as log:
            for item in clean:
                item = dict(item, author=author, saved_at=now)
                current["datasets"][item["name"]] = item
                log.write(json.dumps(item, ensure_ascii=False) + "\n")
        tmp = folder / "inputs.json.tmp"
        tmp.write_text(json.dumps(current, ensure_ascii=False, indent=1), encoding="utf-8")
        tmp.replace(folder / "inputs.json")
    finally:
        fcntl.flock(handle, fcntl.LOCK_UN)
        handle.close()
    return current


def inputs_for(project: str, sales_project: str = "", sales_dir: Path | None = None,
               end: Any = None, commissioning: dict[str, str] | None = None,
               shift: dict[str, Any] | None = None,
               escrow_plan: dict[str, Any] | None = None) -> dict[str, Any]:
    """Наборы для расчёта: найденное в загруженном + ручные поправки поверх.

    Состояние кредита на дату РСС (долг, отложенные проценты, плата за лимит)
    досчитывается от первой выдачи по условиям договоров — отдельно его никто
    не загружает.
    """
    import developaid_credit_sources as sources

    found = sources.collect(project, sales_project, sales_dir, end, commissioning, shift,
                            escrow_plan)
    kept = load(project)
    manual = kept.get("datasets") or {}
    preset = found["preset"] or kept.get("preset")
    datasets = dict(found["datasets"])
    missing, notes = list(found["missing"]), list(found["notes"])
    history = found.get("history")
    if preset and history:
        hist = dict(history["datasets"])
        if "key_rate" in manual:
            hist["key_rate"] = manual["key_rate"]
        run = forecast({"preset": preset, "datasets": hist,
                        "mark_days": [history["as_of"]]})
        runs = {loan["id"]: loan for loan in run["loans"]}
        for loan in PRESETS[preset]["loans"]:
            lid = loan["id"]
            mark = (runs[lid].get("marks") or {}).get(history["as_of"])
            if mark is None:
                missing.append(f"{loan['name']}: долг на дату РСС не досчитан — "
                               + "; ".join(runs[lid]["gaps"][:2]))
                continue
            in_deferral = _day(history["as_of"]) <= _day(runs[lid]["deferral_end"])
            if None in (mark["deferred"], mark["iod"], mark["accrued_interest"]):
                # Долг досчитан, проценты — нет: причина из досчёта, иначе пустые
                # проценты прогноза останутся без объяснения.
                why = [g.rstrip(".") for g in run["gaps"] + runs[lid]["gaps"]
                       if "не рассчитаны" in g and "аккредитив" not in g][:1]
                missing.append(f"{loan['name']}: проценты до даты РСС не досчитаны — "
                               + (why[0] if why else "причина в досчёте не названа"))
            datasets[f"facts.{lid}"] = {
                "name": f"facts.{lid}", "as_of": history["as_of"], "unit": "₽",
                "source": hist[f"plan.{lid}"]["source"] + "; проценты досчитаны от первой "
                          "выдачи по условиям договора",
                "data": {"debt": mark["principal"], "drawn": mark["drawn"],
                         "accrued_interest": 0.0 if in_deferral else mark["accrued_interest"],
                         "accrued_fee": 0.0 if in_deferral else mark["accrued_fee"],
                         "operations": []}}
            datasets[f"deferred.{lid}"] = {
                "name": f"deferred.{lid}", "as_of": history["as_of"], "unit": "₽",
                "source": "досчитано от первой выдачи по условиям договора",
                "data": {"deferred": _sum(mark["deferred"], mark["deferred_fee"])
                         if in_deferral else 0.0,
                         "interest_on_deferred": mark["iod"] if in_deferral else 0.0}}
        if history["future"]:
            every = sorted([(_day(d["date"]), d["amount"]) for part in history["split"].values()
                            for d in part] + history["future"])
            split, _ = sources._split(PRESETS[preset]["loans"], every)
            for loan in PRESETS[preset]["loans"]:
                lid = loan["id"]
                datasets[f"plan.{lid}"] = {
                    "name": f"plan.{lid}", "as_of": history["as_of"], "unit": "₽",
                    "source": "сроки — план остатка ПФ финмодели (лист «КРЕДИТЫ») сверх "
                              "выбранного; до лимита — к концу периода доступности",
                    "data": {"draws": [d for d in split[lid] if d["date"] > history["as_of"]],
                             "prepayments": []}}
    for name, item in manual.items():
        datasets[name] = dict(item, source=f"поправка вручную: {item['source']}")
    return {"preset": preset, "datasets": datasets, "missing": missing, "notes": notes,
            "escrow_at_disclosure": found.get("escrow_at_disclosure")}


# --------------------------------------------------------------------------
# Кредит по дням
# --------------------------------------------------------------------------

def _rate_on(path: list[dict[str, Any]] | None, day: datetime.date) -> float | None:
    if not path:
        return None
    known = [item["rate"] for item in path if _day(item["from"]) <= day]
    return known[-1] if known else None


def _reduce(installments: list[dict[str, Any]], amount: float, after: datetime.date,
            order: str) -> float:
    """Досрочное погашение уменьшает будущие платежи графика; что не легло — вернуть."""
    ahead = [item for item in installments if _day(item["date"]) > after]
    if order == "pro_rata":
        total = sum(item["amount"] for item in ahead)
        if total <= 0:
            return amount
        share = min(1.0, amount / total)
        for item in ahead:
            item["amount"] -= item["amount"] * share
        return max(0.0, amount - total)
    for item in (reversed(ahead) if order == "from_last" else ahead):
        cut = min(item["amount"], amount)
        item["amount"] -= cut
        amount -= cut
        if amount <= 1e-6:
            return 0.0
    return amount


def _schedule(loan: dict[str, Any], base: float) -> list[dict[str, Any]]:
    out = []
    for date, share in loan["schedule"]:
        nominal = (base * share) if share is not None else None
        out.append({"date": date, "share": share, "nominal": nominal,
                    "amount": nominal if nominal is not None else 0.0,
                    "final": share is None or date == loan["maturity"]})
    if loan["schedule"][-1][1] is None:
        # Остаток: база минус остальные платежи.
        out[-1]["nominal"] = out[-1]["amount"] = base - sum(
            item["nominal"] for item in out[:-1])
    return out


def _limit_on(loan: dict[str, Any], day: datetime.date) -> float:
    steps = [amount for start, amount in loan.get("limit_steps") or [] if _day(start) <= day]
    return steps[-1] if steps else loan["limit"]


def _terms(loan: dict[str, Any], datasets: dict[str, Any]) -> dict[str, dict[str, str]]:
    terms = copy.deepcopy(loan["terms"])
    terms.update((datasets.get(f"terms.{loan['id']}") or {}).get("data") or {})
    return terms


def project_terms(preset: dict[str, Any], datasets: dict[str, Any]) -> dict[str, dict[str, str]]:
    terms = copy.deepcopy(preset["terms"])
    terms.update((datasets.get("terms.project") or {}).get("data") or {})
    return terms


def _iv(table: dict[str, Any], cover: float) -> float:
    """I(v) по покрытию: ниже 100 % — своя ставка, дальше ступени «не более»."""
    if cover < 1.0:
        return table["iv_below"]
    for upper, rate in table["iv_steps"]:
        if cover <= upper + 1e-12:
            return rate
    return table["iv_top"]


def segment_rate(loan: dict[str, Any], kind: str, escrow_rule: str,
                 sums: dict[str, float]) -> tuple[float, float | None]:
    """Ставка расчётного периода по среднедневным остаткам (договор А, п. 4.1.1).

    I = (A·I(a) + F·I(v) + (K−A−F)·I(i)) / K, при A + F > K —
    I = (A·I(a) + (K−A)·I(v)) / K. Покрытие — эскроу к чистому долгу: у НКЛ
    2025 — к её долгу без аккредитивов, у НКЛ 2026 (доля) — к совокупному
    чистому долгу двух НКЛ.
    """
    n = sums["days"]
    k, a, e = sums["K"] / n, sums["A"] / n, sums["E"] / n
    base = sums["base"] / n
    if kind == "model":
        # Ставка финмодели уже итоговая (с учётом покрытия эскроу) — берётся как есть.
        return sums["key"] / n, None
    if kind == "base" or k <= 0:
        return base, None
    table = loan["rate_table"]
    a = min(a, k)
    if escrow_rule == "share":
        net = sums["net"] / n
        cover = e / net if net > 0 else None
        f = e * (k - a) / net if net > 0 else 0.0
    else:
        cover = e / (k - a) if k > a else None
        f = e
    if cover is None:
        return (a * table["ia"] + (k - a) * base) / k, None
    if cover < 1.0:
        return (a * table["ia"] + f * table["iv_below"] + (k - a - f) * base) / k, cover
    return (a * table["ia"] + (k - a) * _iv(table, cover)) / k, cover


def _next_28(day: datetime.date) -> datetime.date:
    first = (day.replace(day=1) + datetime.timedelta(days=32)).replace(day=1)
    return first.replace(day=28)


class _Loan:
    """Состояние одной НКЛ в дневном расчёте."""

    def __init__(self, loan, datasets, deferral_end, out):
        self.loan, self.out = loan, out
        self.terms = out["terms"]
        facts = datasets[f"facts.{loan['id']}"]
        f = facts["data"]
        self.start = _day(facts["as_of"])
        self.principal, self.drawn = f["debt"], f["drawn"]
        self.deferral_end = deferral_end
        self.availability_end = _day(loan["availability_end"])
        self.maturity = _day(loan["maturity"])
        self.base_day = (self.availability_end if loan["base"] == "debt_at_availability_end"
                         else self.availability_end + datetime.timedelta(days=1))
        self.reflected_before_base = loan["base"] == "debt_at_availability_end"
        self.order = self.terms["prepayment_order"]["value"]
        self.basis = self.terms["day_basis"]["value"]
        deferred = datasets.get(f"deferred.{loan['id']}")
        if deferred:
            self.deferred = deferred["data"]["deferred"]
            self.iod = deferred["data"]["interest_on_deferred"]
        elif self.start < deferral_end:
            out["gaps"].append(f"{loan['name']}: {NO_DATA} об отложенных процентах — к дате "
                               "окончания отсрочки сумма не известна.")
            self.deferred = self.iod = None
        else:
            self.deferred = self.iod = 0.0
        self.deferred_fee = 0.0
        # Начисленное с последней уплаты — до первой даты уплаты процентов.
        self.pending: list[list[Any]] = []
        first_due = _next_28(self.start) if self.start.day > 28 else self.start.replace(day=28)
        if self.start >= deferral_end:
            self.pending.append([first_due, "interest", f["accrued_interest"]])
            self.pending.append([first_due, "fee", f["accrued_fee"]])
        else:
            self.deferred = None if self.deferred is None else self.deferred + f["accrued_interest"]
            self.deferred_fee += f["accrued_fee"]
        self.sums = self._fresh()
        self.fee_seg = 0.0
        self.installments = None
        self.pending_prepay = 0.0
        self.segments: list[dict[str, Any]] = []
        self.interest_total: float | None = 0.0
        self.iod_total = 0.0
        self.marks: dict[str, dict[str, Any]] = {}
        self.closed = False
        self.no_rate_named = False
        self.marks[self.start.isoformat()] = {
            "principal": self.principal, "drawn": self.drawn, "unpaid": self.unpaid(),
            "interest_total": 0.0}

    @staticmethod
    def _fresh():
        return {"days": 0, "K": 0.0, "A": 0.0, "E": 0.0, "net": 0.0, "base": 0.0, "key": 0.0,
                "Kyd": 0.0,
                "start": None}

    def segment_interest(self) -> tuple[float | None, float | None, float | None]:
        if not self.sums["days"]:
            return 0.0, None, None
        if self.sums.get("unknown"):
            return None, None, None
        rate, cover = segment_rate(self.loan, self.terms["rate"]["value"],
                                   self.terms["escrow_in_rate"]["value"], self.sums)
        return rate / 100.0 * self.sums["Kyd"], rate, cover

    def close(self, day: datetime.date, due: datetime.date) -> None:
        """Закрыть расчётный период: проценты — в отложенные или к уплате ``due``."""
        if not self.sums["days"]:
            return
        interest, rate, cover = self.segment_interest()
        self.segments.append({"start": self.sums["start"].isoformat(), "end": day.isoformat(),
                              "rate": rate, "cover": cover, "interest": interest,
                              "fee": self.fee_seg, "capitalized": day <= self.deferral_end})
        if interest is None:
            self.interest_total = None
        elif self.interest_total is not None:
            self.interest_total += interest
        if day <= self.deferral_end:
            self.deferred = None if self.deferred is None or interest is None \
                else self.deferred + interest
            self.deferred_fee += self.fee_seg
        else:
            self.pending.append([due, "interest", interest])
            self.pending.append([due, "fee", self.fee_seg])
        self.sums = self._fresh()
        self.fee_seg = 0.0

    def unpaid(self) -> float | None:
        """Начислено и не уплачено на конец дня — с текущим периодом."""
        seg, _, _ = self.segment_interest()
        parts = [seg, self.fee_seg, self.deferred, self.iod, self.deferred_fee] + [
            item[2] for item in self.pending]
        return _sum(*parts)


def _simulate(preset: dict[str, Any], datasets: dict[str, Any], scenario: dict[str, Any],
              escrow: dict[str, Any], loans_out: list[dict[str, Any]],
              split_rule: str, mark_days: set[datetime.date]) -> None:
    """Обе НКЛ по дням: ставка НКЛ 2026 зависит от долга НКЛ 2025, раскрытие — общее."""
    key_rate = (datasets.get("key_rate") or {}).get("data", {}).get("path")
    bump = float(scenario.get("key_rate_pp") or 0.0)
    lcs = (datasets.get("letters_of_credit") or {}).get("data", {}).get("by_loan") or {}
    states: dict[str, _Loan] = {}
    for loan, out in zip(preset["loans"], loans_out):
        if not datasets.get(f"facts.{loan['id']}"):
            out["gaps"].append(f"{loan['name']}: {NO_DATA} о долге и выдачах — график не "
                               "рассчитан.")
            continue
        if not datasets.get(f"plan.{loan['id']}"):
            out["gaps"].append(f"{loan['name']}: {NO_DATA} о прогнозных выборках и досрочных "
                               "погашениях (набор можно загрузить пустым, если их не будет).")
            continue
        states[loan["id"]] = _Loan(loan, datasets, _day(out["deferral_end"]), out)
        if loan["id"] not in lcs:
            out["gaps"].append(f"{loan['name']}: {NO_DATA} об остатке аккредитивов этой НКЛ — "
                               "в ставке принят ноль, ставка оценена сверху.")
    if not states:
        return
    if not key_rate:
        loans_out[0]["gaps"].append(f"{NO_DATA} о прогнозе ключевой ставки — проценты не "
                                    "рассчитаны.")
    if not escrow.get("known"):
        for st in states.values():
            if st.terms["rate"]["value"] != "base":
                st.out["gaps"].append(f"{st.loan['name']}: ставка зависит от остатка эскроу, "
                                      f"а он неизвестен — проценты не рассчитаны.")
    for st in states.values():
        _prepare(st, datasets)
    events = [e for e in escrow.get("events") or []]
    disclosed = {}
    for e in events:
        if e["kind"] == "disclosure" and e["amount"] > 0:
            disclosed[_day(e["date"])] = disclosed.get(_day(e["date"]), 0.0) + e["amount"]
    pointer, balance = 0, escrow.get("opening")
    start = min(st.start for st in states.values())
    end = max(st.maturity for st in states.values())
    day = start
    while day < end:
        day += datetime.timedelta(days=1)
        # Эскроу на начало дня: события до этого дня.
        while escrow.get("known") and pointer < len(events) and _day(events[pointer]["date"]) < day:
            balance = events[pointer]["balance_after"]
            pointer += 1
        key = _rate_on(key_rate, day)
        live = [st for st in states.values() if st.start < day <= st.maturity and not st.closed]
        net = sum(max(0.0, st.principal - lcs.get(st.loan["id"], 0.0)) for st in live)
        for st in live:
            yd = _year_days(day, st.basis)
            s = st.sums
            if s["start"] is None:
                s["start"] = day
            s["days"] += 1
            s["K"] += st.principal
            s["A"] += min(lcs.get(st.loan["id"], 0.0), st.principal)
            s["net"] += net
            s["Kyd"] += st.principal / yd
            if key is None or (balance is None and st.terms["rate"]["value"] != "base"):
                s["unknown"] = True
                # Причина пустых процентов — с датой, а не молчаливое «нет данных».
                if key is None and key_rate and not st.no_rate_named:
                    st.no_rate_named = True
                    st.out["gaps"].append(
                        f"{st.loan['name']}: {NO_DATA} о ключевой ставке на {ddmmyyyy(day)} "
                        "(прогноз ставки начинается позже) — проценты с этой даты не "
                        "рассчитаны.")
            else:
                s["E"] += balance or 0.0
                s["base"] += key + bump + st.loan["margin_pp"]
                s["key"] += key + bump
            if day <= st.deferral_end:
                # Проценты на капитализированные — по базовой ставке.
                if key is None or st.deferred is None:
                    st.iod = None
                elif st.iod is not None:
                    grow = st.deferred * (key + bump + st.loan["margin_pp"]) / 100.0 / yd
                    st.iod += grow
                    st.iod_total += grow
            if day <= st.availability_end:
                st.fee_seg += max(0.0, _limit_on(st.loan, day) - st.drawn) \
                    * st.loan["fee_free_limit_pct"] / 100.0 / yd
            _operations(st, day)
            if day == st.base_day and st.installments is None and st.start < st.base_day:
                _set_base(st, "прогноз")
            # Конец расчётного периода: месяц, отсрочка, погашение.
            month_end = (day + datetime.timedelta(days=1)).day == 1
            if day == st.maturity:
                st.close(day, day)
            elif day == st.deferral_end:
                st.close(day, day)
            elif month_end:
                st.close(day, _next_28(day))
        if day in disclosed:
            _disclose(live, day, disclosed[day], split_rule)
        for st in live:
            _settle(st, day)
            if day in mark_days:
                seg = st.segment_interest()[0]
                st.marks[day.isoformat()] = {
                    "principal": st.principal, "drawn": st.drawn, "unpaid": st.unpaid(),
                    "interest_total": _sum(st.interest_total, seg,
                                           None if st.iod is None else st.iod_total),
                    # Состояние на конец дня — чтобы продолжить счёт с этой даты.
                    "deferred": _sum(st.deferred, seg) if day <= st.deferral_end else st.deferred,
                    "iod": st.iod, "deferred_fee": st.deferred_fee + (
                        st.fee_seg if day <= st.deferral_end else 0.0),
                    "accrued_interest": _sum(*([seg] if day > st.deferral_end else [])
                                             + [i[2] for i in st.pending if i[1] == "interest"]),
                    "accrued_fee": (st.fee_seg if day > st.deferral_end else 0.0) + sum(
                        i[2] or 0.0 for i in st.pending if i[1] == "fee")}
    for st in states.values():
        out = st.out
        out.update(installments=st.installments,
                   interest_total=_sum(st.interest_total, None if st.iod is None
                                       else st.iod_total),
                   segments=st.segments, marks=st.marks, start=st.start.isoformat(),
                   debt_now=datasets[f"facts.{st.loan['id']}"]["data"]["debt"],
                   facts_as_of=datasets[f"facts.{st.loan['id']}"]["as_of"],
                   facts_source=datasets[f"facts.{st.loan['id']}"]["source"])


def _prepare(st: _Loan, datasets: dict[str, Any]) -> None:
    loan, out = st.loan, st.out
    facts = datasets[f"facts.{loan['id']}"]
    f = facts["data"]
    out["base"] = {"day": st.base_day.isoformat()}
    if st.start >= st.base_day:
        base = f.get("schedule_base")
        if base is None:
            out["gaps"].append(f"{loan['name']}: {NO_DATA} о расчётной базе графика "
                               f"(факт на {ddmmyyyy(st.base_day)}) — платежи основного долга "
                               "не рассчитаны.")
        else:
            st.installments = _schedule(loan, base)
            out["base"].update(amount=base, kind="факт", source=facts["source"],
                               as_of=facts["as_of"])
            for op in f.get("operations") or []:
                day = _day(op["date"])
                if op["kind"] == "prepay" and (not st.reflected_before_base or day > st.base_day):
                    _reduce(st.installments, op["amount"], day, st.order)
            st.installments = [i for i in st.installments if _day(i["date"]) > st.start]
    plan = datasets[f"plan.{loan['id']}"]["data"]
    st.events = {}
    ignored = 0.0
    for kind, items in (("draw", plan["draws"]), ("prepay", plan["prepayments"])):
        for item in items:
            day = _day(item["date"])
            if day <= st.start or (kind == "draw" and day > st.availability_end):
                ignored += item["amount"]
                continue
            st.events.setdefault(day, []).append((kind, item["amount"]))
    if ignored:
        out["gaps"].append(f"{loan['name']}: {mln(ignored)} млн ₽ прогнозных операций "
                           f"не учтены — дата раньше фактов ({ddmmyyyy(st.start)}) или выборка "
                           "после окончания доступности.")
    st.today: dict[str, float | None] = {}
    st.from_disclosure = 0.0


def _set_base(st: _Loan, kind: str) -> None:
    base = st.principal if st.loan["base"] == "debt_at_availability_end" else st.drawn
    st.installments = _schedule(st.loan, base)
    st.out["base"].update(amount=base, kind=kind,
                          source="долг по фактам плюс прогнозные выборки и погашения",
                          as_of=st.out.get("facts_as_of") or st.start.isoformat())
    if st.pending_prepay:
        _reduce(st.installments, st.pending_prepay, st.base_day, st.order)
        st.pending_prepay = 0.0


def _prepay(st: _Loan, amount: float, day: datetime.date) -> float:
    paid = min(amount, st.principal)
    st.principal -= paid
    if st.installments is not None:
        _reduce(st.installments, paid, day, st.order)
    elif not st.reflected_before_base:
        st.pending_prepay += paid
    return paid


def _operations(st: _Loan, day: datetime.date) -> None:
    for kind, amount in st.events.get(day, []):
        if kind == "draw":
            room = max(0.0, _limit_on(st.loan, day) - st.drawn)
            take = min(amount, room)
            if amount - take > 1.0:
                st.out["gaps"].append(f"{st.loan['name']}: выборка {mln(amount)} млн ₽ на "
                                      f"{ddmmyyyy(day)} выше свободного лимита — учтено "
                                      f"{mln(take)} млн ₽.")
            st.principal += take
            st.drawn += take
        else:
            # Плановое досрочное погашение — платёж этого дня своими деньгами.
            st.today["prepay"] = st.today.get("prepay", 0.0) + _prepay(st, amount, day)


def _interest_debt(st: _Loan) -> float | None:
    """Проценты и комиссии, уже начисленные и ещё не уплаченные (периоды закрыты)."""
    return _sum(st.deferred, st.iod, st.deferred_fee, *[item[2] for item in st.pending])


def _disclose(live: list[_Loan], day: datetime.date, amount: float, rule: str) -> None:
    """Раскрытие: долг становится срочным в размере раскрытого (А п. 6.1.2, Б п. 5.1.1)."""
    keen = [st for st in live if st.terms["disclosure_repays"]["value"] == "immediate"]
    for st in keen:
        if st.sums["days"]:
            st.close(day, day)
    debts = {}
    for st in keen:
        owed = _interest_debt(st)
        debts[st.loan["id"]] = None if owed is None else owed + st.principal
    if any(value is None for value in debts.values()):
        for st in keen:
            st.today["disclosure_unknown"] = True
        return
    shares = _split(amount, debts, rule)
    for st in keen:
        left = min(shares[st.loan["id"]], debts[st.loan["id"]])
        st.from_disclosure = left
        # Сначала начисленное: отложенные, проценты на них, комиссии, проценты.
        for name in ("deferred", "iod", "deferred_fee"):
            take = min(getattr(st, name), left)
            setattr(st, name, getattr(st, name) - take)
            st.today[name] = st.today.get(name, 0.0) + take
            left -= take
        for item in sorted(st.pending, key=lambda x: x[0]):
            take = min(item[2], left)
            item[2] -= take
            st.today[item[1]] = st.today.get(item[1], 0.0) + take
            left -= take
        st.pending = [item for item in st.pending if item[2] > 1e-6]
        if left > 0:
            st.today["prepay"] = st.today.get("prepay", 0.0) + _prepay(st, left, day)


def _settle(st: _Loan, day: datetime.date) -> None:
    """Платежи дня: график, проценты 28-го, отложенное — в дату окончания отсрочки."""
    today, st.today = st.today, {}
    principal: float | None = today.pop("prepay", 0.0)
    scheduled = 0.0
    if st.installments is not None:
        scheduled = sum(i["amount"] for i in st.installments if _day(i["date"]) == day)
        if day == st.maturity:
            scheduled = st.principal
        scheduled = min(scheduled, st.principal)
        st.principal -= scheduled
        principal += scheduled
    elif day >= st.base_day and any(_day(d) == day for d, _ in st.loan["schedule"]):
        principal = None
    deferred = today.get("deferred", 0.0)
    iod = today.get("iod", 0.0)
    fee = today.get("deferred_fee", 0.0) + today.get("fee", 0.0)
    interest = today.get("interest", 0.0)
    if day == st.deferral_end or (day == st.maturity and st.deferred):
        deferred = _sum(deferred, st.deferred)
        iod = _sum(iod, st.iod)
        fee += st.deferred_fee
        st.deferred = st.iod = 0.0
        st.deferred_fee = 0.0
    keep = []
    for item in st.pending:
        if item[0] <= day or day == st.maturity:
            if item[1] == "interest":
                interest = _sum(interest, item[2])
            else:
                fee = _sum(fee, item[2])
        else:
            keep.append(item)
    st.pending = keep
    parts = [principal, interest, deferred, iod, fee]
    # Меньше рубля — не платёж (проценты при покрытии эскроу выше порога — 0,01 %).
    if all(p is not None and abs(p) < 1.0 for p in parts) and not today.get("disclosure_unknown"):
        return
    if day == st.maturity:
        st.closed = True
    share = next((i["share"] for i in st.installments or [] if i["date"] == day.isoformat()
                  and scheduled), None)
    st.out["payments"][day.isoformat()] = {
        "principal": principal, "interest": interest, "deferred": deferred,
        "interest_on_deferred": iod, "fee": fee,
        "total": None if today.get("disclosure_unknown") else _sum(*parts),
        "debt_after": st.principal if principal is not None else None,
        "share": share, "from_disclosure": st.from_disclosure or 0.0}
    st.from_disclosure = 0.0


# --------------------------------------------------------------------------
# Эскроу
# --------------------------------------------------------------------------

def _counts_after(item: dict[str, Any], as_of: datetime.date) -> bool:
    """Поступление после даты остатка. Известен только месяц — месяц целиком позже.

    Деньги месяца остатка частью уже на счёте: брать их второй раз нельзя.
    """
    day = _day(item["date"])
    if item.get("month_only"):
        return (day.year, day.month) > (as_of.year, as_of.month)
    return day > as_of


def _escrow(datasets: dict[str, Any], scenario: dict[str, Any]) -> dict[str, Any]:
    """События эскроу по датам и остаток. Один эскроу на проект."""
    gaps: list[str] = []
    notes: list[str] = []
    escrow = datasets.get("escrow")
    if not escrow:
        return {"known": False, "gaps": [f"{NO_DATA} об остатке на эскроу."]}
    as_of = _day(escrow["as_of"])
    keep = 1.0 - float(scenario.get("inflow_cut_pct") or 0.0) / 100.0
    delay = int(scenario.get("disclosure_delay_months") or 0)
    events: list[dict[str, Any]] = []
    contracts = datasets.get("contracts")
    existing: set[str] = set()
    if not contracts:
        gaps.append(f"{NO_DATA} о поступлениях по заключённым ДДУ.")
    else:
        for item in contracts["data"]["payments"]:
            if item.get("contract"):
                existing.add(item["contract"])
            if _counts_after(item, as_of):
                events.append({"date": item["date"], "kind": "contracts",
                               "amount": item["amount"] * keep})
    excluded = 0.0
    if scenario.get("confirmed_only"):
        pass  # прогноз новых продаж не берётся: проверка «без него хватает?»
    elif not datasets.get("sales"):
        gaps.append(f"{NO_DATA} о прогнозе новых продаж.")
    else:
        # Продажа месяца, который уже покрыт выгрузкой договоров, — в договорах.
        covered = _day(contracts["as_of"]) if contracts else None
        for item in datasets["sales"]["data"]["payments"]:
            month = item.get("sale_month") or item["date"][:7]
            if (item.get("contract") in existing
                    or (covered and month <= covered.strftime("%Y-%m"))):
                excluded += item["amount"]
                continue
            if _counts_after(item, as_of):
                events.append({"date": item["date"], "kind": "sales",
                               "amount": item["amount"] * keep})
    refunds = datasets.get("refunds")
    if not refunds:
        gaps.append(f"{NO_DATA} о возвратах и расторжениях.")
    else:
        for item in refunds["data"]["payments"]:
            if _counts_after(item, as_of):
                events.append({"date": item["date"], "kind": "refunds", "amount": item["amount"]})
    disclosure = datasets.get("disclosure")
    if not disclosure:
        gaps.append(f"{NO_DATA} о датах и суммах раскрытия эскроу.")
    planned = []
    for item in (disclosure or {}).get("data", {}).get("items") or []:
        if scenario.get("confirmed_only") and not item["confirmed"]:
            continue
        day = _add_months(_day(item["date"]), delay) if delay else _day(item["date"])
        if day > as_of:
            planned.append(dict(item, date=day.isoformat(), planned_date=item["date"]))
    order = {"contracts": 0, "sales": 0, "refunds": 1, "disclosure": 2}
    events += [{"date": item["date"], "kind": "disclosure", "amount": item["amount"],
                "confirmed": item["confirmed"], "final": item["final"],
                "planned_date": item["planned_date"]} for item in planned]
    events.sort(key=lambda e: (e["date"], order[e["kind"]]))
    balance = escrow["data"]["balance"]
    for event in events:
        if event["kind"] in {"contracts", "sales"}:
            balance += event["amount"]
        elif event["kind"] == "refunds":
            balance -= event["amount"]
        else:
            want = balance if event["amount"] is None else event["amount"]
            event["amount"] = max(0.0, min(want, balance))
            if want > balance + 1:
                notes.append(f"Раскрытие {ddmmyyyy(event['date'])}: ждали {mln(want)} млн ₽, "
                            f"на эскроу к этой дате {mln(balance)} млн ₽ — учтено столько.")
            balance -= event["amount"]
        event["balance_after"] = balance
    final = [e["date"] for e in events if e["kind"] == "disclosure" and e.get("final")]
    return {"known": not gaps, "gaps": gaps, "notes": notes, "as_of": escrow["as_of"],
            "source": escrow["source"], "opening": escrow["data"]["balance"],
            "events": events, "closed_on": final[0] if final else None,
            "sales_excluded": excluded}


def _escrow_on(block: dict[str, Any], day: datetime.date) -> dict[str, float | None]:
    """Остаток до раскрытий этого дня и раскрыто всего по этот день включительно."""
    if not block.get("known"):
        return {"before": None, "disclosed": None}
    before = block["opening"]
    disclosed = 0.0
    for event in block["events"]:
        when = _day(event["date"])
        if when > day:
            break
        if event["kind"] == "disclosure":
            disclosed += event["amount"]
            if when < day:
                before -= event["amount"]
        elif event["kind"] == "refunds":
            before -= event["amount"]
        else:
            before += event["amount"]
    return {"before": before, "disclosed": disclosed}


# --------------------------------------------------------------------------
# Покрытие обязательств по датам
# --------------------------------------------------------------------------

def _arrivals(items: list[dict[str, Any]], upto: datetime.date) -> float:
    return sum(item["amount"] for item in items if _day(item["date"]) <= upto)


def _split(amount: float, totals: dict[str, float], rule: str) -> dict[str, float]:
    """Раскрытое на дату — между НКЛ: пропорционально или одной вперёд."""
    out = {key: 0.0 for key in totals}
    if rule in {"nkl2025_first", "nkl2026_first"}:
        first = rule.split("_")[0]
        keys = [first] + [key for key in totals if key != first]
        for key in keys:
            if key in totals:
                out[key] = min(totals[key], amount)
                amount -= out[key]
        return out
    whole = sum(totals.values())
    return {key: (amount * value / whole if whole else 0.0) for key, value in totals.items()}


def _cover(loans: list[dict[str, Any]], escrow: dict[str, Any], datasets: dict[str, Any],
           rule: str) -> list[dict[str, Any]]:
    days = sorted({d for loan in loans for d in loan["payments"]})
    free = datasets.get("free_cash")
    extra = datasets.get("extra")
    free_items = (free or {}).get("data", {}).get("items") or []
    extra_items = [i for i in (extra or {}).get("data", {}).get("items") or [] if i["confirmed"]]
    used_disc = used_free = used_extra = 0.0
    broken = False
    rows = []
    for key in days:
        day = _day(key)
        per = {loan["id"]: loan["payments"].get(key) for loan in loans}
        totals = {lid: (p or {}).get("total", 0.0) if p else 0.0 for lid, p in per.items()}
        due_known = all(value is not None for value in totals.values())
        owed = sum(totals.values()) if due_known else None
        esc = _escrow_on(escrow, day)
        pool = None if esc["disclosed"] is None else esc["disclosed"] - used_disc
        free_pool = None if not free else _arrivals(free_items, day) - used_free
        extra_pool = None if not extra else _arrivals(extra_items, day) - used_extra
        row: dict[str, Any] = {"date": key, "loans": {}, "escrow_before": esc["before"],
                               "disclosed_total": esc["disclosed"]}
        for part in ("principal", "interest", "deferred", "interest_on_deferred", "fee"):
            values = [(p or {}).get(part, 0.0) if p else 0.0 for p in per.values()]
            row[part] = _sum(*values)
        row["interest_and_fees"] = _sum(row["interest"], row["deferred"],
                                        row["interest_on_deferred"], row["fee"])
        row["total"] = owed
        debts = [(p or {}).get("debt_after") if p else _debt_between(loan, key)
                 for loan, p in zip(loans, per.values())]
        row["debt_after"] = _sum(*debts)
        row["disclosed_available"] = pool if not broken else None
        if broken or not _known(owed, pool):
            broken = True
            row.update(disclosed_used=None, need_outside=None, other_used=None,
                       free_used=None, extra_used=None, deficit=None)
        else:
            take = min(pool, owed)
            used_disc += take
            outside = owed - take
            row.update(disclosed_used=take, need_outside=outside)
            if not _known(free_pool, extra_pool):
                broken = True
                row.update(other_used=None, free_used=None, extra_used=None, deficit=None)
            else:
                f_take = min(free_pool, outside)
                e_take = min(extra_pool, outside - f_take)
                used_free += f_take
                used_extra += e_take
                row.update(free_used=f_take, extra_used=e_take, other_used=f_take + e_take,
                           deficit=max(0.0, outside - f_take - e_take))
        if row.get("disclosed_used") is not None:
            # Срочное погашение при раскрытии — своей НКЛ; остаток раскрытого — по правилу.
            own = {lid: min(totals[lid], (p or {}).get("from_disclosure") or 0.0)
                   for lid, p in per.items()}
            rest = row["disclosed_used"] - sum(own.values())
            extra = _split(max(0.0, rest), {lid: totals[lid] - own[lid] for lid in totals}, rule)
            shares = {lid: own[lid] + extra[lid] for lid in totals}
        else:
            shares = {lid: None for lid in totals}
        for loan in loans:
            p = per[loan["id"]]
            if p is None:
                continue
            item = dict(p, disclosed_used=shares.get(loan["id"]))
            if _known(item["disclosed_used"], item["total"], row.get("other_used"),
                      row.get("need_outside")):
                rest = item["total"] - item["disclosed_used"]
                whole = row["need_outside"]
                item["other_used"] = row["other_used"] * rest / whole if whole else 0.0
                item["deficit"] = row["deficit"] * rest / whole if whole else 0.0
            else:
                item["other_used"] = item["deficit"] = None
            row["loans"][loan["id"]] = item
        later = [e for e in escrow.get("events") or []
                 if e["kind"] == "disclosure" and _day(e["date"]) > day and e["amount"] > 0]
        # Платёж основного долга, которому раскрытого не хватило, а раскрытие
        # будет позже, — «раскрытие позже необходимого платежа» (ТЗ, п. 8).
        row["late_disclosure"] = (bool(later) and (row.get("need_outside") or 0.0) > 1.0
                                  and (row.get("principal") or 0.0) > 1.0)
        row["next_disclosure"] = later[0]["date"] if later else None
        rows.append(row)
    return rows


def _debt_between(loan: dict[str, Any], key: str) -> float | None:
    """Долг НКЛ на дату, в которую ей платить нечего: после её прошлой даты."""
    past = [d for d in loan["payments"] if d < key]
    if past:
        return loan["payments"][max(past)]["debt_after"]
    return loan.get("debt_now")


# --------------------------------------------------------------------------
# Прогноз целиком
# --------------------------------------------------------------------------

def _preset(inputs: dict[str, Any]) -> dict[str, Any]:
    return PRESETS[inputs.get("preset") or "kutuzov_city"]


def forecast(inputs: dict[str, Any], scenario: dict[str, Any] | None = None) -> dict[str, Any]:
    """Прогноз по одному сценарию: платежи НКЛ, эскроу, покрытие, сводные числа."""
    scenario = dict(scenario or {})
    preset = _preset(inputs)
    datasets = inputs.get("datasets") or {}
    escrow = _escrow(datasets, scenario)
    gaps = list(escrow["gaps"])
    terms = project_terms(preset, datasets)
    loans = []
    for loan in preset["loans"]:
        # Отсрочка кончается раньше, если все эскроу проекта закрыты (А п. 4.2.2, Б п. 3.3).
        limit = _day(loan["deferral_limit"])
        closed = _day(escrow["closed_on"]) if escrow.get("closed_on") else None
        end = min(limit, closed) if closed else limit
        loans.append({
            "id": loan["id"], "name": loan["name"], "short": loan["short"],
            "limit": loan["limit"], "terms": _terms(loan, datasets),
            "gaps": [], "payments": {}, "deferral_end": end.isoformat(), "base": {},
            "deferral_reason": (
                f"все эскроу закрываются {ddmmyyyy(closed)} — раньше предельной даты "
                f"{ddmmyyyy(limit)}" if closed and closed < limit
                else "предельная дата отсрочки по договору")})
    planned = _day(terms["planned_disclosure"]["value"])
    facts_a = datasets.get(f"facts.{preset['loans'][0]['id']}")
    marks = {SUFFICIENCY_DAY, planned} | {_day(d) for d in inputs.get("mark_days") or []}
    if facts_a:
        marks.add(_day(facts_a["as_of"]))
    _simulate(preset, datasets, scenario, escrow, loans, terms["disclosure_split"]["value"],
              marks)
    for loan in loans:
        gaps += [g for g in loan["gaps"] if g not in gaps]
    rows = _cover(loans, escrow, datasets, terms["disclosure_split"]["value"])
    out = {"scenario": scenario, "loans": loans, "escrow": escrow, "rows": rows,
           "gaps": gaps, "terms": terms, "split_rule": terms["disclosure_split"],
           "months": _months(rows, escrow), "datasets": _dataset_dates(datasets),
           "notes": list(escrow.get("notes") or [])}
    out["sufficiency"] = sufficiency(out, preset, datasets)
    out["covenants"] = covenants(out, datasets)
    out["top"] = _top(out, datasets)
    return out


SUFFICIENCY_DAY = datetime.date(2027, 6, 30)


def sufficiency(result: dict[str, Any], preset: dict[str, Any],
                datasets: dict[str, Any]) -> list[dict[str, Any]]:
    """Достаточность эскроу для полного погашения НКЛ 2025 (договор А, п. 8.2.60).

    Нужно = задолженность по договору + невыбранный лимит + неуплаченные
    проценты + планируемые проценты до плановой даты раскрытия (по ставке с
    плановым долгом и плановыми остатками эскроу и аккредитивов). Сравнивается
    с фактическим объёмом эскроу: на дату данных — остаток банка, на 30.06.2027 —
    прогноз остатка.
    """
    loan = preset["loans"][0]
    run = result["loans"][0]
    terms = result["terms"]
    planned = terms["planned_disclosure"]
    escrow = result["escrow"]
    out = []
    days = []
    if run.get("facts_as_of"):
        days.append(("fact", _day(run["facts_as_of"])))
    days.append(("forecast", SUFFICIENCY_DAY))
    for kind, day in days:
        mark = (run.get("marks") or {}).get(day.isoformat())
        at_planned = (run.get("marks") or {}).get(_day(planned["value"]).isoformat())
        if kind == "fact":
            have = escrow.get("opening")
            have_words = "остаток эскроу по данным банка"
        else:
            have = _escrow_after(escrow, day) if escrow.get("known") else None
            have_words = "прогноз остатка эскроу"
        if mark is None:
            need = debt = undrawn = unpaid = future = None
        else:
            debt = mark["principal"]
            undrawn = max(0.0, loan["limit"] - mark["drawn"])
            unpaid = mark["unpaid"]
            if _day(planned["value"]) <= day:
                future = 0.0
            elif at_planned is None:
                future = None
            else:
                future = (None if not _known(at_planned["interest_total"], mark["interest_total"])
                          else at_planned["interest_total"] - mark["interest_total"])
            need = _sum(debt, undrawn, unpaid, future)
        ok = None if not _known(need, have) else have >= need
        out.append({
            "kind": kind, "date": day.isoformat(), "escrow": have, "need": need, "ok": ok,
            "debt": debt, "undrawn": undrawn, "unpaid": unpaid, "planned_interest": future,
            "planned_disclosure": planned["value"], "planned_source": planned["source"],
            "formula": (f"{have_words} {mln(have)} против: долг {mln(debt)} + невыбранный "
                        f"лимит {mln(undrawn)} + неуплаченные проценты {mln(unpaid)} + "
                        f"планируемые проценты до плановой даты раскрытия "
                        f"{ddmmyyyy(planned['value'])} {mln(future)} = {mln(need)}"),
            "clause": f"{_A}, п. 8.2.60"})
    return out


def _test_days(start: datetime.date, end: datetime.date) -> list[datetime.date]:
    """Даты тестирования наполнения эскроу (А п. 8.2.57): последний рабочий день
    квартала с 31.12.2025 (праздники не учтены — последний будний день)."""
    out = []
    day = datetime.date(2025, 12, 31)
    while day <= end:
        last = day
        while last.weekday() >= 5:
            last -= datetime.timedelta(days=1)
        if last >= start:
            out.append(last)
        day = _month_end(_add_months(day.replace(day=1), 3).strftime("%Y-%m"))
    return out


def covenants(result: dict[str, Any], datasets: dict[str, Any]) -> list[dict[str, Any]]:
    """Проверки по договорам: наполнение эскроу (А п. 8.2.57) и продажи по ДДУ
    (А п. 7.1.8.16, Б SP_15.18) против бизнес-плана, согласованного с банком."""
    plan = datasets.get("business_plan")
    escrow = result["escrow"]
    out: list[dict[str, Any]] = []
    first_disclosure = next((e["date"] for e in escrow.get("events") or []
                             if e["kind"] == "disclosure"), None)
    escrow_check = {"name": "Наполнение эскроу против бизнес-плана",
                    "clause": f"{_A}, п. 8.2.57",
                    "rule": "нарушение — отставание остатка эскроу от бизнес-плана на дату "
                            "тестирования на 25 % и более"}
    sales_check = {"name": "Продажи по ДДУ за два квартала против бизнес-плана",
                   "clause": f"{_A}, п. 7.1.8.16; {_B}, SP_15.18",
                   "rule": "нарушение — сумма цен ДДУ за два календарных квартала подряд ниже "
                           "бизнес-плана на 30 % и более"}
    if not plan:
        for check in (escrow_check, sales_check):
            out.append(dict(check, state="no_data", items=[],
                            text=f"{NO_DATA}: бизнес-план, согласованный с банком, не "
                                 "загружен — проверить не с чем."))
        return out
    series = sorted(plan["data"]["escrow"], key=lambda x: x["date"])
    items = []
    if escrow.get("known") and series:
        history = {i["date"]: i["amount"] for i in
                   (datasets.get("escrow") or {}).get("data", {}).get("history") or []}
        history[escrow["as_of"]] = escrow["opening"]
        stop = _day(first_disclosure) if first_disclosure else _day(series[-1]["date"])
        for day in _test_days(_day(series[0]["date"]), stop):
            planned = [i["amount"] for i in series if _day(i["date"]) <= day]
            if not planned:
                continue
            if day <= _day(escrow["as_of"]):
                actual = history.get(day.isoformat())
                kind = "факт"
            else:
                actual = _escrow_after(escrow, day)
                kind = "прогноз"
            gap = None if actual is None else 1 - actual / planned[-1] if planned[-1] else None
            items.append({"date": day.isoformat(), "plan": planned[-1], "actual": actual,
                          "kind": kind, "gap": gap,
                          "breach": None if gap is None else gap >= 0.25})
    escrow_check.update(items=items, state=_state(items))
    out.append(escrow_check)
    signed: dict[str, float] = {}
    contracts = datasets.get("contracts")
    for item in (contracts or {}).get("data", {}).get("signed") or []:
        quarter = f"{item['month'][:4]} Q{(int(item['month'][5:7]) - 1) // 3 + 1}"
        signed[quarter] = signed.get(quarter, 0.0) + item["amount"]
    covered = contracts["as_of"][:7] if contracts else ""
    for item in (datasets.get("sales") or {}).get("data", {}).get("payments") or []:
        if item.get("signed_total") and item["sale_month"] > covered:
            month = item["sale_month"]
            quarter = f"{month[:4]} Q{(int(month[5:7]) - 1) // 3 + 1}"
            signed[quarter] = signed.get(quarter, 0.0) + item["signed_total"]
    ddu = {i["quarter"]: i["amount"] for i in plan["data"]["ddu"]}
    quarters = sorted(ddu)
    items = []
    for one, two in zip(quarters, quarters[1:]):
        want = ddu[one] + ddu[two]
        have = (signed[one] + signed[two]) if one in signed and two in signed else None
        gap = None if have is None or not want else 1 - have / want
        items.append({"date": f"{one} – {two}", "plan": want, "actual": have, "gap": gap,
                      "kind": "договоры и прогноз продаж",
                      "breach": None if gap is None else gap >= 0.30})
    sales_check.update(items=items, state=_state(items))
    out.append(sales_check)
    return out


def _state(items: list[dict[str, Any]]) -> str:
    if not items or all(i["breach"] is None for i in items):
        return "no_data"
    return "breach" if any(i["breach"] for i in items) else "ok"


def _months(rows: list[dict[str, Any]], escrow: dict[str, Any]) -> list[dict[str, Any]]:
    """Эскроу на конец каждого месяца: поступления, раскрыто, на погашение, доступно."""
    if not escrow.get("known") or not rows:
        return []
    first = _day(escrow["as_of"]).replace(day=1)
    last = _day(rows[-1]["date"]).replace(day=1)
    out = []
    month = first
    while month <= last:
        key = month.strftime("%Y-%m")
        end = _month_end(key)
        got = {"contracts": 0.0, "sales": 0.0, "refunds": 0.0, "disclosure": 0.0}
        for event in escrow["events"]:
            if event["date"][:7] == key:
                got[event["kind"]] += event["amount"]
        state = _escrow_on(escrow, end)
        used = [r["disclosed_used"] for r in rows if _day(r["date"]) <= end]
        used_total = sum(used) if all(u is not None for u in used) else None
        # Раскрытия последнего дня месяца уже не на эскроу.
        blocked = _escrow_after(escrow, end)
        out.append({"month": key, "inflow_contracts": got["contracts"],
                    "inflow_sales": got["sales"], "refunds": got["refunds"],
                    "disclosed": got["disclosure"], "blocked": blocked,
                    "disclosed_total": state["disclosed"],
                    "disclosed_to_repayment": used_total,
                    "disclosed_free": (state["disclosed"] - used_total
                                       if used_total is not None else None)})
        month = _add_months(month, 1)
    return out


def _escrow_after(escrow: dict[str, Any], day: datetime.date) -> float:
    after = [e["balance_after"] for e in escrow["events"] if _day(e["date"]) <= day]
    return after[-1] if after else escrow["opening"]


def _dataset_dates(datasets: dict[str, Any]) -> list[dict[str, Any]]:
    return [{"name": name, "label": label,
             "as_of": (datasets.get(name) or {}).get("as_of"),
             "source": (datasets.get(name) or {}).get("source")}
            for name, label in DATASETS.items() if not name.startswith("terms.")
            or name in datasets]


def _given(datasets: dict[str, Any], name: str) -> str:
    item = datasets.get(name)
    return (f"{item['source']}, на {ddmmyyyy(item['as_of'])}" if item
            else f"{DATASETS[name].lower()} — {NO_DATA}")


def _top(result: dict[str, Any], datasets: dict[str, Any]) -> dict[str, Any]:
    """Верхний блок сводки. У каждого числа — формула и откуда входы."""
    loans, rows, escrow = result["loans"], result["rows"], result["escrow"]
    debts = [loan.get("debt_now") for loan in loans]
    top: dict[str, Any] = {}
    top["debt_now"] = {
        "value": _sum(*debts),
        "formula": " + ".join(f"долг {loan['short']} {mln(loan.get('debt_now'))}"
                              for loan in loans),
        "inputs": [_given(datasets, f"facts.{loan['id']}") for loan in loans]}
    top["escrow_now"] = {"value": escrow.get("opening"),
                         "formula": "остаток на счетах эскроу по данным банка",
                         "inputs": [_given(datasets, "escrow")]}
    nxt = rows[0] if rows else None
    if nxt:
        top["next"] = {
            "date": nxt["date"], "value": nxt["total"],
            "formula": (f"основной долг {mln(nxt['principal'])} + проценты "
                        f"{mln(nxt['interest'])} + отложенные проценты {mln(nxt['deferred'])} "
                        f"+ проценты на них {mln(nxt['interest_on_deferred'])} + комиссия "
                        f"{mln(nxt['fee'])}"),
            "inputs": [_given(datasets, n) for n in
                       [f"facts.{l['id']}" for l in loans] + [f"plan.{l['id']}" for l in loans]
                       + [f"deferred.{l['id']}" for l in loans]
                       + ["key_rate", "escrow", "letters_of_credit"]]}
        escrow_inputs = [_given(datasets, n) for n in
                         ("escrow", "contracts", "sales", "refunds", "disclosure")]
        top["escrow_at_next"] = {
            "value": nxt["escrow_before"],
            "formula": ("остаток эскроу + поступления по действующим ДДУ + новые продажи "
                        "− возвраты − раскрытое раньше этой даты"),
            "inputs": escrow_inputs}
        top["disclosed_at_next"] = {
            "value": nxt["disclosed_available"],
            "formula": "раскрыто по эту дату − уже направлено на прошлые платежи",
            "inputs": [_given(datasets, "disclosure")]}
        top["outside_at_next"] = {
            "value": nxt["need_outside"],
            "formula": (f"всего к оплате {mln(nxt['total'])} − из раскрытия "
                        f"{mln(nxt['disclosed_used'])}"),
            "inputs": ["расчёт выше"]}
        top["deficit_at_next"] = {
            "value": nxt["deficit"],
            "formula": (f"не меньше нуля: нужно вне эскроу {mln(nxt['need_outside'])} − "
                        f"свободные деньги и подтверждённое финансирование "
                        f"{mln(nxt['other_used'])}"),
            "inputs": [_given(datasets, "free_cash"), _given(datasets, "extra")]}
    deficits = [row["deficit"] for row in rows]
    known = rows and all(value is not None for value in deficits)
    first = next((row for row in rows if (row["deficit"] or 0) > 0.5), None)
    biggest = max(rows, key=lambda r: r["deficit"] or 0.0) if rows else None
    top["first_deficit"] = {
        "date": first["date"] if first and known else None,
        "value": first["deficit"] if first and known else (0.0 if known else None),
        "formula": "первая дата платежа, на которую источников не хватает",
        "inputs": ["расчёт по датам платежей"]}
    top["max_deficit"] = {
        "date": biggest["date"] if known and biggest and (biggest["deficit"] or 0) > 0.5 else None,
        "value": (biggest["deficit"] if biggest else 0.0) if known else None,
        "formula": "наибольший дефицит одной даты платежа за весь прогноз",
        "inputs": ["расчёт по датам платежей"]}
    top["deficit_total"] = {
        "value": sum(deficits) if known else None,
        "formula": "сумма дефицитов всех дат платежей", "inputs": ["расчёт по датам платежей"]}
    for item in result.get("sufficiency") or []:
        top[f"sufficiency_{item['kind']}"] = {
            "date": item["date"], "value": item["need"], "ok": item["ok"],
            "escrow": item["escrow"], "formula": item["formula"],
            "inputs": [_given(datasets, n) for n in ("escrow", f"facts.{loans[0]['id']}",
                                                     f"plan.{loans[0]['id']}", "key_rate")]
            + [f"плановая дата раскрытия {ddmmyyyy(item['planned_disclosure'])}: "
               f"{item['planned_source']}"]}
    interest = [loan.get("interest_total") for loan in loans]
    fees = [sum(p["fee"] for p in loan["payments"].values()) for loan in loans]
    top["interest_cost"] = {
        "value": _sum(*interest, *fees),
        "formula": "проценты по кредитам (включая отложенные) и комиссии за весь прогноз",
        "inputs": [_given(datasets, "key_rate")]}
    return top


# --------------------------------------------------------------------------
# Статус, сценарии, сравнение с прошлым прогнозом
# --------------------------------------------------------------------------

def status(base: dict[str, Any], confirmed: dict[str, Any]) -> dict[str, Any]:
    """Зелёный — покрыто; жёлтый — покрытие держится на прогнозе продаж или
    неподтверждённом раскрытии; красный — дефицит или раскрытие позже платежа."""
    top = base["top"]
    reasons: list[str] = []
    if top["deficit_total"]["value"] is None:
        return {"color": "unknown", "reasons": [
            # Слова «статус не определён, не хватает данных» уже даёт заголовок
            # строки (`COLORS["unknown"]`): здесь — только чего именно нет.
            "Чего нет: " + "; ".join(base["gaps"][:3])]}
    if top["deficit_total"]["value"] > 0.5:
        reasons.append(f"Прогнозируется дефицит {mln(top['deficit_total']['value'])} млн ₽, "
                       f"первый — {ddmmyyyy(top['first_deficit']['date'])}.")
    late = [row for row in base["rows"] if row["late_disclosure"]]
    if late:
        reasons.append(f"Раскрытие эскроу ({ddmmyyyy(late[0]['next_disclosure'])}) позже "
                       f"платежа {ddmmyyyy(late[0]['date'])}, которому оно нужно.")
    if reasons:
        return {"color": "red", "reasons": reasons}
    extra = confirmed["top"]["deficit_total"]["value"]
    if extra is None or extra > 0.5:
        return {"color": "yellow", "reasons": [
            "Без прогноза новых продаж и неподтверждённых сроков раскрытия обязательства "
            "не покрываются" + (f": дефицит {mln(extra)} млн ₽." if extra else ".")]}
    return {"color": "green", "reasons": ["Обязательства покрыты доступными источниками."]}


def analyse(inputs: dict[str, Any], stress: dict[str, Any] | None = None) -> dict[str, Any]:
    """Базовый и стрессовый сценарии, статус и отпечаток входов."""
    stress = dict(STRESS_DEFAULT, **(stress or {}))
    base = forecast(inputs)
    confirmed = forecast(inputs, {"confirmed_only": True})
    hard = forecast(inputs, stress)
    hard_confirmed = forecast(inputs, dict(stress, confirmed_only=True))
    digest = hashlib.sha256(json.dumps(inputs, sort_keys=True, ensure_ascii=False,
                                       default=str).encode()).hexdigest()[:16]
    return {"base": base, "stress": hard, "stress_params": stress,
            "status": status(base, confirmed), "stress_status": status(hard, hard_confirmed),
            "digest": digest, "preset": _preset(inputs)["title"]}


def snapshot(result: dict[str, Any]) -> dict[str, Any]:
    """Короткая запись прогноза для сравнения со следующим."""
    base = result["base"]
    top = base["top"]
    return {"digest": result["digest"],
            "made_at": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
            "first_deficit": top["first_deficit"]["date"],
            "deficit_total": top["deficit_total"]["value"],
            "interest_cost": top["interest_cost"]["value"],
            "escrow_by_day": {row["date"]: row["escrow_before"] for row in base["rows"]},
            "escrow_by_month": {m["month"]: m["blocked"] for m in base["months"]},
            "disclosures": [e["date"] for e in base["escrow"].get("events") or []
                            if e["kind"] == "disclosure"],
            "pay_days": [row["date"] for row in base["rows"] if (row["total"] or 0) > 0]}


def remember(project: str, result: dict[str, Any]) -> dict[str, Any] | None:
    """Записать прогноз, если входы изменились; вернуть прошлый (другой) прогноз."""
    folder = _folder(project)
    path = folder / "forecasts.jsonl"
    handle = _locked(folder)
    try:
        rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()
                if line.strip()] if path.exists() else []
        if not rows or rows[-1]["digest"] != result["digest"]:
            with path.open("a", encoding="utf-8") as log:
                log.write(json.dumps(snapshot(result), ensure_ascii=False) + "\n")
            return rows[-1] if rows else None
        return rows[-2] if len(rows) > 1 else None
    finally:
        fcntl.flock(handle, fcntl.LOCK_UN)
        handle.close()


def compare(previous: dict[str, Any] | None, result: dict[str, Any]) -> list[dict[str, str]]:
    """Что изменилось против прошлого прогноза — словами, с тоном."""
    if not previous:
        return []
    now = snapshot(result)
    out: list[dict[str, str]] = []
    was, new = previous.get("deficit_total"), now["deficit_total"]
    if _known(was, new) and abs(new - was) > 0.5:
        out.append({"tone": "bad" if new > was else "good",
                    "text": f"Дефицит {'вырос' if new > was else 'снизился'} на "
                            f"{mln(abs(new - was))} млн ₽: было {mln(was)}, стало {mln(new)}."})
    if previous.get("first_deficit") != now["first_deficit"]:
        out.append({"tone": "bad" if now["first_deficit"] and (
                        not previous.get("first_deficit")
                        or now["first_deficit"] < previous["first_deficit"]) else "good",
                    "text": f"Первая дата дефицита: было {ddmmyyyy(previous.get('first_deficit'))}"
                            f", стало {ddmmyyyy(now['first_deficit'])}."})
    # Отставание эскроу: на месяц, который прошлый прогноз уже предсказывал.
    escrow = result["base"]["escrow"]
    if escrow.get("known"):
        month = escrow["as_of"][:7]
        expected = (previous.get("escrow_by_month") or {}).get(month)
        actual = escrow["opening"]
        if expected is not None and expected - actual > 0.5:
            out.append({"tone": "bad",
                        "text": f"Поступления на эскроу отстают от прошлого прогноза: на "
                                f"{ddmmyyyy(escrow['as_of'])} ждали к концу месяца "
                                f"{mln(expected)} млн ₽, на счёте {mln(actual)} млн ₽."})
    was, new = previous.get("interest_cost"), now["interest_cost"]
    if _known(was, new) and new - was > 0.5:
        out.append({"tone": "bad", "text": f"Процентные расходы выросли на {mln(new - was)} "
                                           f"млн ₽: было {mln(was)}, стало {mln(new)}."})
    days = now["pay_days"]
    for old, cur in zip(previous.get("disclosures") or [], now["disclosures"]):
        passed = [d for d in days if old <= d < cur]
        if passed:
            out.append({"tone": "bad",
                        "text": f"Раскрытие эскроу перенесено с {ddmmyyyy(old)} на "
                                f"{ddmmyyyy(cur)} — за дату обязательного платежа "
                                f"{ddmmyyyy(passed[0])}."})
    return out


def reference(preset: str = "kutuzov_city") -> list[dict[str, Any]]:
    """Справочный график при полной выборке: без досрочных, процентов и комиссий."""
    rows: dict[str, dict[str, Any]] = {}
    for loan in PRESETS[preset]["loans"]:
        for item in _schedule(loan, loan["limit"]):
            row = rows.setdefault(item["date"], {"date": item["date"], "total": 0.0})
            row[loan["id"]] = {"share": item["share"], "amount": item["amount"]}
            row["total"] += item["amount"]
    return [rows[key] for key in sorted(rows)]


# --------------------------------------------------------------------------
# Вид: сводка руководству и Монитор читают одно и то же
# --------------------------------------------------------------------------

COLORS = {"green": ("good", "зелёный", "обязательства покрыты"),
          "yellow": ("warn", "жёлтый", "покрытие зависит от прогноза продаж или "
                                       "неподтверждённого срока раскрытия"),
          "red": ("bad", "красный", "прогнозируется дефицит или раскрытие позже платежа"),
          "unknown": ("missing", "не определён", "не хватает исходных данных")}

TABLE_HEAD = ["Дата", "Основной долг к погашению", "Проценты и комиссии", "Всего к оплате",
              "Эскроу до раскрытия", "Доступно из раскрытия", "Другие источники", "Дефицит",
              "Долг после платежа"]


def _esc(text: Any) -> str:
    return html.escape(str(text))


def _how(item: dict[str, Any]) -> str:
    """Раскрытие числа: формула и откуда входы."""
    inputs = "; ".join(_esc(x) for x in item.get("inputs") or [])
    return (f"<details class='how'><summary>как посчитано</summary>"
            f"<div>{_esc(item.get('formula') or '')}.</div>"
            + (f"<div class='note'>Исходные данные: {inputs}.</div>" if inputs else "")
            + "</details>")


def _status_html(state: dict[str, Any], label: str = "Статус") -> str:
    tone, word, meaning = COLORS[state["color"]]
    reasons = " ".join(_esc(r) for r in state["reasons"])
    return (f"<p class='credit-status {tone}'><b>{_esc(label)}: {word}</b> — {meaning}. "
            f"{reasons}</p>")


def _top_html(result: dict[str, Any]) -> str:
    top = result["base"]["top"]
    nxt = top.get("next") or {}
    lines = [
        ("Текущий совокупный долг", top["debt_now"]),
        ("Текущий остаток эскроу", top["escrow_now"]),
    ]
    if nxt:
        day = ddmmyyyy(nxt["date"])
        lines += [
            (f"Ближайший платёж {day}: всего обязательств", nxt),
            (f"Прогноз эскроу на {day}", top["escrow_at_next"]),
            ("Доступно из раскрытия к этой дате", top["disclosed_at_next"]),
            ("Нужно из источников вне эскроу", top["outside_at_next"]),
            ("Непокрытый дефицит", top["deficit_at_next"]),
        ]
    # Это проверка банка по договору А (п. 8.2.60) на конец периода выборки, а
    # не ответ «к вводу»: дата — из договора, и это сказано, иначе она читается
    # как ещё один срок ввода (владелец на проде, 27.10.2026).
    for kind, words in (("fact", "на дату данных"),
                        ("forecast", "на 30.06.2027 — конец периода выборки, прогноз")):
        item = top.get(f"sufficiency_{kind}")
        if item:
            lines.append((f"Хватит ли эскроу на полное погашение НКЛ 2025 — проверка банка "
                          f"по договору ({words})", item))
    first, biggest = top["first_deficit"], top["max_deficit"]
    lines += [
        ("Первая дата дефицита" + (f" — {ddmmyyyy(first['date'])}" if first["date"] else ""),
         first),
        ("Максимальный дефицит за прогноз"
         + (f" — {ddmmyyyy(biggest['date'])}" if biggest["date"] else ""), biggest),
    ]
    rows = []
    for label, item in lines:
        value = item.get("value")
        cell = mln(value)
        if label.startswith("Первая дата") and value == 0.0 and not item.get("date"):
            cell = "дефицита нет"
        if label.startswith("Хватит ли эскроу"):
            cell = (NO_DATA if item["ok"] is None else
                    f"хватает: {mln(item['escrow'])} при нужных {mln(value)}" if item["ok"] else
                    f"не хватает {mln(value - item['escrow'])}: есть {mln(item['escrow'])}, "
                    f"нужно {mln(value)}")
        rows.append(f"<tr><td>{_esc(label)}</td><td>{cell}</td><td>{_how(item)}</td></tr>")
    return ("<table class='credit-top'><tr><th>Показатель</th><th>млн ₽</th><th></th></tr>"
            + "".join(rows) + "</table>")


def _cell(value: float | None, bad: bool = False) -> str:
    text = mln(value)
    return f"<span class='neg'>{text}</span>" if bad and value and value > 0.5 else text


def _main_table(result: dict[str, Any]) -> str:
    base = result["base"]
    names = {loan["id"]: loan["short"] for loan in base["loans"]}
    body = []
    for row in base["rows"]:
        late = " (раскрытие позже)" if row["late_disclosure"] else ""
        if any((item.get("from_disclosure") or 0) > 1.0 for item in row["loans"].values()):
            late += " (раскрытие эскроу: долг к погашению)"
        body.append(
            "<tr class='date'>" + "".join(f"<td>{c}</td>" for c in [
                ddmmyyyy(row["date"]) + late, _cell(row["principal"]),
                _cell(row["interest_and_fees"]), _cell(row["total"]),
                _cell(row["escrow_before"]), _cell(row["disclosed_available"]),
                _cell(row["other_used"]), _cell(row["deficit"], bad=True),
                _cell(row["debt_after"])]) + "</tr>")
        for lid, item in row["loans"].items():
            fees = _sum(item["interest"], item["deferred"], item["interest_on_deferred"],
                        item["fee"])
            body.append(
                "<tr class='loan'>" + "".join(f"<td>{c}</td>" for c in [
                    f"в т. ч. {_esc(names[lid])}", _cell(item["principal"]), _cell(fees),
                    _cell(item["total"]), "", _cell(item["disclosed_used"]),
                    _cell(item["other_used"]), _cell(item["deficit"], bad=True),
                    _cell(item["debt_after"])]) + "</tr>")
    return ("<table class='credit-table'><tr>" + "".join(f"<th>{h}</th>" for h in TABLE_HEAD)
            + "</tr>" + "".join(body) + "</table>"
            "<p class='note'>Суммы — млн ₽. «Доступно из раскрытия» — раскрытые деньги, ещё не "
            "направленные на прошлые платежи. «Другие источники» — свободные деньги проекта и "
            "подтверждённое дополнительное финансирование, потраченные на этот платёж.</p>")


def _detail_html(result: dict[str, Any]) -> str:
    """Расчёт каждой даты по НКЛ: из чего сложен платёж и чем покрыт."""
    base = result["base"]
    names = {loan["id"]: loan["short"] for loan in base["loans"]}
    out = ["<details class='credit-detail'><summary>Расчёт по датам платежей</summary>"]
    for row in base["rows"]:
        lines = []
        for lid, item in row["loans"].items():
            share = (f" ({item['share'] * 100:.0f} % графика)".replace(".", ",")
                     if item.get("share") else "")
            rate = _rate_words(base, lid, row["date"])
            lines.append(
                f"<li>{_esc(names[lid])}{rate}: основной долг {mln(item['principal'])}{share} + "
                f"проценты {mln(item['interest'])} + отложенные проценты "
                f"{mln(item['deferred'])} + проценты на них "
                f"{mln(item['interest_on_deferred'])} + комиссия за свободный лимит "
                f"{mln(item['fee'])} = {mln(item['total'])}; из раскрытия "
                f"{mln(item['disclosed_used'])}, из других источников "
                f"{mln(item['other_used'])}, дефицит {mln(item['deficit'])}.</li>")
        cover = (f"Покрытие: из раскрытия {mln(row['disclosed_used'])} (было доступно "
                 f"{mln(row['disclosed_available'])}), нужно вне эскроу "
                 f"{mln(row['need_outside'])}, свободные деньги {mln(row['free_used'])}, "
                 f"подтверждённое финансирование {mln(row['extra_used'])}, дефицит "
                 f"{mln(row['deficit'])}.")
        out.append(f"<div class='keep'><b>{ddmmyyyy(row['date'])}</b>: всего к оплате "
                   f"{mln(row['total'])} млн ₽.<ul>{''.join(lines)}</ul>"
                   f"<p class='note'>{cover}</p></div>")
    out.append("</details>")
    return "".join(out)


def _rate_words(base: dict[str, Any], lid: str, day: str) -> str:
    """Ставка последнего расчётного периода, закрытого к этой дате."""
    loan = next(l for l in base["loans"] if l["id"] == lid)
    done = [x for x in loan.get("segments") or [] if x["end"] <= day]
    if not done:
        return ""
    seg = done[-1]
    if seg["rate"] is None:
        return f" (ставка за период — {NO_DATA})"
    cover = (f", эскроу покрывает {seg['cover'] * 100:.0f} % долга".replace(".", ",")
             if seg.get("cover") is not None else "")
    rate = f"{seg['rate']:.2f}".replace(".", ",")
    return (f" (ставка за {ddmmyyyy(seg['start'])}–{ddmmyyyy(seg['end'])} — "
            f"{rate} % годовых{cover})")


def _assumptions_html(result: dict[str, Any]) -> str:
    """Допущения, от которых зависят числа, — словами, без пунктов договоров."""
    base = result["base"]
    lines = list(base.get("assumptions") or [])
    loans = {loan["id"]: loan for loan in base["loans"]}
    if any(l["terms"]["rate"]["value"] == "analogy" for l in loans.values()) and not any(
            l["terms"]["rate"]["value"] == "model" for l in loans.values()):
        lines.append("Ставка по НКЛ 2026 посчитана по аналогии с НКЛ 2025: формулы банка для "
                     "неё (из Общих условий банка) в документах нет.")
    rules = {l["terms"]["escrow_in_rate"]["value"] for l in loans.values()
             if l["terms"]["rate"]["value"] != "model"}
    if rules == {"full", "share"}:
        lines.append("В ставке НКЛ 2025 эскроу учитывается целиком, в ставке НКЛ 2026 — долей "
                     "по договорам. Так одни и те же деньги снижают обе ставки; банк может "
                     "учесть и для НКЛ 2025 только долю — это нужно подтвердить с банком. В "
                     "прогнозе денег эскроу учтены один раз.")
    split = base["terms"]["disclosure_split"]
    if split["source"].startswith("нет данных"):
        lines.append("Как раскрытое эскроу делится между кредитами, в договорах не сказано: "
                     "принято, что сначала гасится НКЛ 2025. Правило нужно подтвердить с банком.")
    planned = base["terms"]["planned_disclosure"]
    if planned["source"].startswith("допущение"):
        lines.append(f"Плановой даты раскрытия эскроу в договорах нет: для проверки "
                     f"достаточности эскроу принято {ddmmyyyy(planned['value'])} (ввод около "
                     "конца сентября 2027).")
    if not lines:
        return ""
    return ("<div class='note warn credit-assumptions'><b>Допущения расчёта.</b> "
            + " ".join(_esc(line) for line in lines) + "</div>")


def _covenants_html(result: dict[str, Any]) -> str:
    words = {"ok": "выполняется", "breach": "НАРУШЕНИЕ", "no_data": NO_DATA}
    rows = []
    for check in result["base"]["covenants"]:
        detail = check.get("text") or "; ".join(
            f"{i['date'] if ' ' in i['date'] else ddmmyyyy(i['date'])}: план {mln(i['plan'])}, "
            f"{i['kind']} {mln(i['actual'])}"
            + (f", отставание {i['gap'] * 100:.0f} %".replace(".", ",") if i["gap"] is not None
               else "")
            for i in check["items"])
        tone = " class='neg'" if check["state"] == "breach" else ""
        rows.append(f"<tr><td>{_esc(check['name'])}</td><td>{_esc(check['clause'])}</td>"
                    f"<td{tone}>{words[check['state']]}</td><td>{_esc(check['rule'])}. "
                    f"{_esc(detail)}</td></tr>")
    return ("<h3>Проверки по кредитным договорам</h3><table class='credit-covenants'><tr>"
            "<th>Проверка</th><th>Договор</th><th>Результат</th><th>Пояснение</th></tr>"
            + "".join(rows) + "</table>")


def _months_html(result: dict[str, Any]) -> str:
    months = result["base"]["months"]
    if not months:
        return ""
    rows = "".join(
        "<tr>" + "".join(f"<td>{c}</td>" for c in [
            m["month"][5:] + "." + m["month"][:4], mln(m["inflow_contracts"]),
            mln(m["inflow_sales"]), mln(m["refunds"]), mln(m["disclosed"]),
            mln(m["blocked"]), mln(m["disclosed_to_repayment"]), mln(m["disclosed_free"])])
        + "</tr>" for m in months)
    return ("<details class='credit-months'><summary>Эскроу по месяцам</summary>"
            "<table><tr><th>Месяц</th><th>Поступления по ДДУ</th><th>Новые продажи</th>"
            "<th>Возвраты</th><th>Раскрыто за месяц</th><th>Заблокировано на конец</th>"
            "<th>Раскрыто на погашение, всего</th><th>Раскрыто и доступно</th></tr>"
            + rows + "</table><p class='note'>Суммы — млн ₽. Заблокированные деньги не "
            "оплачивают наступивший платёж: они становятся источником только после "
            "раскрытия.</p></details>")


def _datasets_html(result: dict[str, Any]) -> str:
    rows = "".join(
        f"<tr><td>{_esc(item['label'])}</td><td>{ddmmyyyy(item['as_of'])}</td>"
        f"<td>{_esc(item['source'] or NO_DATA)}</td></tr>"
        for item in result["base"]["datasets"])
    return ("<details class='credit-data'><summary>Исходные данные и их актуальность</summary>"
            "<table><tr><th>Данные</th><th>На дату</th><th>Источник</th></tr>" + rows
            + "</table></details>")


def _terms_html(result: dict[str, Any]) -> str:
    rows = []
    for loan in result["base"]["loans"]:
        for key, item in loan["terms"].items():
            rows.append(f"<tr><td>{_esc(loan['short'])}</td><td>{_esc(_TERM_WORDS[key])}</td>"
                        f"<td>{_esc(item['source'])}</td></tr>")
    for key, item in result["base"]["terms"].items():
        value = (f": {ddmmyyyy(item['value'])}" if key == "planned_disclosure" else "")
        rows.append(f"<tr><td>Проект</td><td>{_esc(_TERM_WORDS[key])}{value}</td>"
                    f"<td>{_esc(item['source'])}</td></tr>")
    return ("<details class='credit-terms'><summary>Условия расчёта и их источник"
            "</summary><table><tr><th>Кредит</th><th>Условие</th><th>Откуда</th></tr>"
            + "".join(rows) + "</table></details>")


_TERM_WORDS = {"rate": "Ставка", "day_basis": "Начисление процентов",
               "pay_dates": "Даты уплаты процентов и комиссии (28-го следующего месяца)",
               "deferred_rate": "Отсрочка: капитализация, проценты на капитализированные",
               "prepayment_order": "Досрочное погашение",
               "escrow_in_rate": "Эскроу в ставке",
               "disclosure_repays": "Раскрытие эскроу: долг к погашению в размере раскрытого",
               "fee": "Плата 0,7 % годовых за свободный лимит",
               "disclosure_split": "Раскрытое эскроу между кредитами",
               "planned_disclosure": "Плановая дата раскрытия эскроу"}


def _reference_html(preset: str) -> str:
    rows = reference(preset)
    body = "".join(
        f"<tr><td>{ddmmyyyy(r['date'])}</td>"
        + "".join(f"<td>{('остаток' if (r.get(l) or {}).get('share') is None and r.get(l) else (str(round(r[l]['share'] * 100)) + ' %') if r.get(l) else '—')}</td>"
                  for l in ("nkl2025", "nkl2026"))
        + f"<td>{mln(r['total'])}</td></tr>" for r in rows)
    total = sum(r["total"] for r in rows)
    return ("<details class='credit-reference'><summary>Справочно: график при полной выборке"
            "</summary><table><tr><th>Дата</th><th>НКЛ 2025, доля базы</th><th>НКЛ 2026, "
            "доля базы</th><th>Всего, млн ₽</th></tr>" + body
            + f"<tr><td><b>Итого</b></td><td></td><td></td><td><b>{mln(total)}</b></td></tr>"
            "</table><p class='note'>Без досрочных погашений, процентов и комиссий.</p>"
            "</details>")


def _stress_html(result: dict[str, Any]) -> str:
    p = result["stress_params"]
    base, hard = result["base"]["top"], result["stress"]["top"]
    rows = [("Дефицит за прогноз", base["deficit_total"]["value"], hard["deficit_total"]["value"]),
            ("Максимальный дефицит одной даты", base["max_deficit"]["value"],
             hard["max_deficit"]["value"]),
            ("Проценты и комиссии за прогноз", base["interest_cost"]["value"],
             hard["interest_cost"]["value"])]
    body = "".join(f"<tr><td>{label}</td><td>{mln(a)}</td><td>{mln(b)}</td></tr>"
                   for label, a, b in rows)
    first = (f"<tr><td>Первая дата дефицита</td><td>{ddmmyyyy(base['first_deficit']['date'])}"
             f"</td><td>{ddmmyyyy(hard['first_deficit']['date'])}</td></tr>")
    def num(value: float) -> str:
        return f"{float(value):g}".replace(".", ",")

    words = (f"поступления ниже на {num(p['inflow_cut_pct'])} %, раскрытие позже на "
             f"{int(p['disclosure_delay_months'])} мес., ключевая ставка выше на "
             f"{num(p['key_rate_pp'])} п. п.")
    return ("<h3>Базовый и стрессовый сценарии</h3>"
            f"<p class='note'>Стресс: {_esc(words)}</p>"
            "<table><tr><th>Показатель</th><th>Базовый, млн ₽</th><th>Стресс, млн ₽</th></tr>"
            + body + first + "</table>" + _status_html(result["stress_status"], "Статус в стрессе"))


def _gaps_html(result: dict[str, Any]) -> str:
    items = result["base"]["gaps"] + result["base"]["notes"]
    if not items:
        return ""
    return ("<p class='note warn'>Чего не хватает или что учтено не полностью: "
            + " ".join(_esc(g) for g in items) + "</p>")


def render_html(result: dict[str, Any], *, monitor: bool = False,
                changes: list[dict[str, str]] | None = None) -> str:
    """Раздел «Погашение кредитов»: в сводке и на странице Монитора одинаковый.

    Монитор дополнительно видит условия расчёта, отклонение от прошлого прогноза
    и стресс; в сводке руководству — без технических пояснений.
    """
    out = [_status_html(result["status"]), _assumptions_html(result), _top_html(result),
           _main_table(result),
           _detail_html(result), _months_html(result), _gaps_html(result)]
    if changes is not None:
        out.insert(1, "<h3>Что изменилось против прошлого прогноза</h3>" + (
            "<ul>" + "".join(f"<li class='{c['tone']}'>{_esc(c['text'])}</li>" for c in changes)
            + "</ul>" if changes else "<p class='note'>Прошлого прогноза с другими данными "
            "нет или существенных изменений не видно.</p>"))
    out.append(_stress_html(result))
    out.append(_datasets_html(result))
    if monitor:
        out.append(_covenants_html(result))
        out.append(_terms_html(result))
    out.append(_reference_html(result.get("preset_id") or "kutuzov_city"))
    return "<div class='credit'>" + "".join(out) + "</div>"


def text_line(result: dict[str, Any]) -> str:
    """Строка сообщения в Telegram."""
    top = result["base"]["top"]
    nxt = top.get("next")
    _, word, _ = COLORS[result["status"]["color"]]
    parts = [f"Кредиты: статус {word}"]
    if nxt:
        parts.append(f"ближайший платёж {ddmmyyyy(nxt['date'])} — {mln(nxt['value'], 1)} млн ₽, "
                     f"из раскрытия эскроу доступно {mln(top['disclosed_at_next']['value'], 1)}")
    total = top["deficit_total"]["value"]
    if total is None:
        parts.append("дефицит не определён: не хватает исходных данных")
    elif total > 0.5:
        parts.append(f"дефицит за прогноз {mln(total, 1)} млн ₽, первый — "
                     f"{ddmmyyyy(top['first_deficit']['date'])}, наибольший — "
                     f"{mln(top['max_deficit']['value'], 1)} млн ₽")
    else:
        parts.append("дефицита в прогнозе нет")
    return "; ".join(parts) + "."


def for_project(project: str, sales_project: str = "", sales_dir: Path | None = None,
                stress: dict[str, Any] | None = None, end: Any = None,
                commissioning: dict[str, str] | None = None,
                shift: dict[str, Any] | None = None,
                escrow_plan: dict[str, Any] | None = None) -> dict[str, Any]:
    """Прогноз проекта по уже загруженным данным; чего нет — названо с местом.

    ``commissioning`` — утверждённый срок ввода сводки (к нему раскрытие),
    ``shift`` — прогноз Монитора, если он позже: только строкой допущений,
    ``escrow_plan`` — эскроу по плану финмодели вместо темпа (`sources.collect`).
    """
    inputs = inputs_for(project, sales_project, sales_dir, end, commissioning, shift,
                        escrow_plan)
    # Договоры из отчёта о продажах есть у многих проектов; кредитным проект
    # делает только загрузка данных по кредитам.
    if not inputs.get("preset"):
        return {"state": "missing",
                "reason": f"Условия кредитов проекта «{project}» в системе не заведены: "
                          "разобранных кредитных договоров для него нет, поэтому платежи "
                          "банку не посчитать."}
    result = analyse(inputs, stress)
    result["base"]["gaps"] = [f"Не нашлось: {m}." for m in inputs["missing"]] + \
        result["base"]["gaps"]
    # Статус собран до «Не нашлось»: пустое «Чего нет: » — причина из полного списка.
    if (result.get("status") or {}).get("color") == "unknown":
        result["status"]["reasons"] = ["Чего нет: " + ("; ".join(result["base"]["gaps"][:3])
                                                       or "причина в расчёте не названа")]
    for run in (result["base"], result["stress"]):
        run["assumptions"] = list(inputs["notes"])
    result["preset_id"] = inputs.get("preset") or "kutuzov_city"
    # Отложенное до даты РСС (проценты и плата за отсрочку с первой выдачи):
    # сводке — чтобы отделить его от процентов, начисленных в прогнозе.
    result["opening_deferred"] = {
        key.split(".", 1)[1]: _sum(item["data"].get("deferred"),
                                   item["data"].get("interest_on_deferred"))
        for key, item in (inputs.get("datasets") or {}).items() if key.startswith("deferred.")}
    result["state"] = "ok"
    return result
