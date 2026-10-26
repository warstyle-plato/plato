"""Погашение кредитов и покрытие обязательств эскроу (ТЗ владельца «Кутузов Сити»).

Отвечает на четыре вопроса сводки руководству и Монитора проекта: когда и
сколько платить банку, сколько к этим датам будет на эскроу, сколько из него
раскроется и пойдёт на погашение, сколько денег не хватит и когда. Отдельно
по каждой НКЛ и сводно.

Расчёт здесь один: сводка (`developaid_management_report`) и Монитор
(`/monitor/credit`) только читают `forecast` и рисуют его.

Устройство:

* условия кредитов — `PRESETS` (параметры ТЗ, п. 2–3). Что ТЗ не задаёт
  (порядок досрочного погашения, даты уплаты процентов, проценты на
  отложенные проценты, деление раскрытия между НКЛ), лежит в `TERMS` с
  происхождением «нет данных…» и заменяется выпиской договора (набор
  ``terms.<НКЛ>``) с её пунктом;
* исходные данные — наборы `DATASETS`, у каждого дата актуальности и
  источник. Нет набора — «нет данных», а не ноль: сумма с неизвестным слагаемым
  неизвестна;
* кредит считается по дням: проценты за день на остаток утра, в отсрочку —
  в отложенные, комиссия — на свободный лимит до конца доступности;
* график основного долга — доля расчётной базы. База НКЛ 2025 — долг на
  конец доступности, НКЛ 2026 — выбранный лимит на следующий день. До этой
  даты база прогнозная (факт + прогнозные выборки), после — фактическая.
  Досрочное погашение, уже уменьшившее базу, второй раз из графика не
  вычитается;
* эскроу — один на проект: начальный остаток + поступления по действующим
  ДДУ + новые продажи − возвраты − раскрытие, по датам оплаты. Заблокированный
  остаток платёж не покрывает;
* покрытие — по датам подряд: раскрытое, затем свободные деньги, затем
  подтверждённое дофинансирование. Потраченное второй раз не участвует,
  остаток переносится вперёд.
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

PRESETS: dict[str, dict[str, Any]] = {
    "kutuzov_city": {
        "title": "Кутузов Сити",
        "loans": [
            {"id": "nkl2025", "name": "НКЛ от 04.04.2025", "short": "НКЛ 2025",
             "number": "400F00ZDO-002", "limit": 5485.689 * M,
             "availability_end": "2027-06-30", "maturity": "2029-03-30",
             "margin_pp": 4.78, "fee_free_limit_pct": 0.70,
             "deferral_limit": "2027-09-30",
             # База — долг на дату окончания доступности (ТЗ, п. 3).
             "base": "debt_at_availability_end",
             "schedule": [("2027-09-30", 0.61), ("2027-12-30", 0.07),
                          ("2028-03-30", 0.07), ("2028-06-30", 0.07),
                          ("2028-09-30", 0.08), ("2028-12-30", 0.08),
                          ("2029-03-30", 0.02)],
             "source": f"{TZ}, п. 2–3"},
            {"id": "nkl2026", "name": "НКЛ от 26.06.2026", "short": "НКЛ 2026",
             "number": "400B01K4DMF", "limit": 1125.000 * M,
             "availability_end": "2027-09-30", "maturity": "2029-09-30",
             "margin_pp": 4.14, "fee_free_limit_pct": 0.70,
             "deferral_limit": "2029-03-30",
             # База — выбранный лимит на следующий день после доступности.
             "base": "drawn_day_after_availability_end",
             # Последний платёж — остаток (номинально 38 %).
             "schedule": [("2029-03-30", 0.23), ("2029-06-30", 0.39),
                          ("2029-09-30", None)],
             "source": f"{TZ}, п. 2–3"},
        ],
    },
}

_ASSUMED = "нет данных в предоставленных документах — до выписки договора принято"

# Что ТЗ не задаёт. Каждое правило — с происхождением; выписка договора
# (набор ``terms.<НКЛ>``) заменяет значение и источник.
TERMS: dict[str, dict[str, str]] = {
    "rate": {"value": "base",
             "source": f"{TZ}, п. 2: базовая ставка. Льготная ставка от покрытия "
                       "эскроу — нет данных, пока не получена формула из договора"},
    "day_basis": {"value": "actual",
                  "source": f"{_ASSUMED}: проценты за каждый день, в году — его "
                            "фактическое число дней"},
    "pay_dates": {"value": "quarterly",
                  "source": f"{_ASSUMED}: проценты и комиссия платятся 30.03, 30.06, "
                            "30.09, 30.12, в дату окончания отсрочки и в дату погашения"},
    "deferred_rate": {"value": "loan_rate",
                      "source": f"{_ASSUMED}: на отложенные проценты — ставка кредита, "
                                "без начисления процентов на проценты на них"},
    "prepayment_order": {"value": "from_last",
                         "source": f"{_ASSUMED}: досрочное погашение уменьшает платежи "
                                   "графика начиная с последнего"},
    "disclosure_split": {"value": "pro_rata",
                         "source": f"{TZ}, п. 5: правило подтвердить с банком — "
                                   "формулировки двух НКЛ различаются. До ответа банка "
                                   "раскрытое делится между НКЛ пропорционально платежам "
                                   "на дату"},
}
TERM_VALUES = {"rate": {"base"}, "day_basis": {"actual", "365"},
               "pay_dates": {"quarterly"}, "deferred_rate": {"loan_rate"},
               "prepayment_order": {"from_last", "nearest", "pro_rata"},
               "disclosure_split": {"pro_rata", "nkl2025_first", "nkl2026_first"}}

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
}
UNITS = {"млн ₽": M, "₽": 1.0}
# Наборы без денежных сумм — единица им не нужна.
_UNITLESS = {"key_rate", "terms.nkl2025", "terms.nkl2026"}

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
    elif name in {"contracts", "refunds"}:
        out = {"payments": _payments(data.get("payments"), scale, what)}
    elif name == "sales":
        out = {"payments": _payments(data.get("payments"), scale, what)
               + _expand_sales(data.get("sales"), scale)}
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
            if key not in TERMS:
                raise ValueError(f"{what}: неизвестное условие «{key}».")
            value = str((item or {}).get("value") or "")
            if value not in TERM_VALUES[key]:
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


def contracts_from_sales(sales_dir: Path | None, sales_project: str) -> dict[str, Any] | None:
    """Поступления по действующим ДДУ — из графиков договоров отчёта о продажах.

    Это тот же источник, что у поступлений на эскроу в блоке «Финансирование»
    (`contracting.escrow_actual`): второй выгрузки договоров нет. Набор
    ``contracts``, загруженный руками, важнее.
    """
    if not str(sales_project or "").strip():
        return None
    from market_search import sales_store

    kept = sales_store.load(sales_dir or sales_store.default_dir(), sales_project)
    part = (kept.get("sources") or {}).get("contracting") or {}
    rows = (part.get("data") or {}).get("rows") or []
    if not rows or not part.get("at"):
        return None
    payments = []
    for row in rows:
        for step in row.get("escrow_schedule") or []:
            if step.get("amount"):
                payments.append({"date": _month_end(step["month"]).isoformat(),
                                 "month_only": True, "amount": float(step["amount"]),
                                 **({"contract": row["contract"]} if row.get("contract") else {})})
    return {"name": "contracts", "as_of": str(part["at"])[:10],
            "source": f"графики платежей договоров из отчёта о продажах «{sales_project}»",
            "unit": "₽", "data": {"payments": payments}}


def inputs_for(project: str, sales_project: str = "",
               sales_dir: Path | None = None) -> dict[str, Any]:
    """Наборы для расчёта: сохранённые + договоры из отчёта о продажах."""
    kept = load(project)
    datasets = dict(kept.get("datasets") or {})
    if "contracts" not in datasets:
        derived = contracts_from_sales(sales_dir, sales_project)
        if derived:
            datasets["contracts"] = derived
    return {"preset": kept.get("preset"), "datasets": datasets}


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


def _quarter_dates(start: datetime.date, end: datetime.date) -> list[datetime.date]:
    out = []
    for year in range(start.year, end.year + 1):
        for month in (3, 6, 9, 12):
            day = datetime.date(year, month, 30)
            if start < day <= end:
                out.append(day)
    return out


def _terms(loan: dict[str, Any], datasets: dict[str, Any]) -> dict[str, dict[str, str]]:
    terms = copy.deepcopy(TERMS)
    override = (datasets.get(f"terms.{loan['id']}") or {}).get("data") or {}
    terms.update(override)
    return terms


def _run_loan(loan: dict[str, Any], datasets: dict[str, Any], scenario: dict[str, Any],
              deferral_end: datetime.date) -> dict[str, Any]:
    """Платежи одной НКЛ по датам. Неизвестное — None с причиной в ``gaps``."""
    terms = _terms(loan, datasets)
    facts = datasets.get(f"facts.{loan['id']}")
    plan = datasets.get(f"plan.{loan['id']}")
    deferred_set = datasets.get(f"deferred.{loan['id']}")
    key_rate = (datasets.get("key_rate") or {}).get("data", {}).get("path")
    out: dict[str, Any] = {"id": loan["id"], "name": loan["name"], "short": loan["short"],
                           "terms": terms, "gaps": [], "payments": {},
                           "deferral_end": deferral_end.isoformat()}
    if not facts:
        out["gaps"].append(f"{loan['name']}: {NO_DATA} о долге и выдачах — график не рассчитан.")
        return out
    if not plan:
        out["gaps"].append(f"{loan['name']}: {NO_DATA} о прогнозных выборках и досрочных "
                           "погашениях (набор можно загрузить пустым, если их не будет).")
        return out
    start = _day(facts["as_of"])
    f = facts["data"]
    principal, drawn = f["debt"], f["drawn"]
    accrued, fee_acc = f["accrued_interest"], f["accrued_fee"]
    if start < deferral_end:
        if not deferred_set:
            out["gaps"].append(f"{loan['name']}: {NO_DATA} об отложенных процентах — к дате "
                               "окончания отсрочки сумма не известна.")
            deferred = iod = None
        else:
            deferred = deferred_set["data"]["deferred"]
            iod = deferred_set["data"]["interest_on_deferred"]
    else:
        deferred = (deferred_set or {}).get("data", {}).get("deferred", 0.0)
        iod = (deferred_set or {}).get("data", {}).get("interest_on_deferred", 0.0)
    if not key_rate:
        out["gaps"].append(f"{NO_DATA} о прогнозе ключевой ставки — проценты не рассчитаны.")
    limit = loan["limit"]
    availability_end = _day(loan["availability_end"])
    maturity = _day(loan["maturity"])
    base_day = availability_end if loan["base"] == "debt_at_availability_end" \
        else availability_end + datetime.timedelta(days=1)
    reflected_before_base = loan["base"] == "debt_at_availability_end"
    order = terms["prepayment_order"]["value"]
    basis = terms["day_basis"]["value"]
    bump = float(scenario.get("key_rate_pp") or 0.0)

    installments: list[dict[str, Any]] | None = None
    pending = 0.0  # досрочные до базы, которые базу не уменьшили (НКЛ 2026)
    base_info: dict[str, Any] = {"day": base_day.isoformat()}
    if start >= base_day:
        base = f.get("schedule_base")
        if base is None:
            out["gaps"].append(f"{loan['name']}: {NO_DATA} о расчётной базе графика "
                               f"(факт на {ddmmyyyy(base_day)}) — платежи основного долга "
                               "не рассчитаны.")
        else:
            installments = _schedule(loan, base)
            base_info.update(amount=base, kind="факт", source=facts["source"],
                             as_of=facts["as_of"])
            for op in f.get("operations") or []:
                day = _day(op["date"])
                if op["kind"] == "prepay" and (not reflected_before_base or day > base_day):
                    _reduce(installments, op["amount"], day, order)
            installments = [item for item in installments if _day(item["date"]) > start]
    out["base"] = base_info

    events: dict[datetime.date, list[tuple[str, float]]] = {}
    ignored = 0.0
    for kind, items in (("draw", plan["data"]["draws"]),
                        ("prepay", plan["data"]["prepayments"])):
        for item in items:
            day = _day(item["date"])
            if day <= start or (kind == "draw" and day > availability_end):
                ignored += item["amount"]
                continue
            events.setdefault(day, []).append((kind, item["amount"]))
    if ignored:
        out["gaps"].append(f"{loan['name']}: {mln(ignored)} млн ₽ прогнозных операций "
                           f"не учтены — дата раньше фактов ({ddmmyyyy(start)}) или выборка "
                           "после окончания доступности.")

    rates_ok = bool(key_rate) and _rate_on(key_rate, start + datetime.timedelta(days=1)) is not None
    if key_rate and not rates_ok:
        out["gaps"].append(f"Прогноз ключевой ставки начинается позже {ddmmyyyy(start)} — "
                           "проценты не рассчитаны.")
    if not rates_ok:
        accrued = None
        if start < deferral_end:
            deferred = iod = None
    pay_days = set(_quarter_dates(start, maturity))
    pay_days.update(d for d in (deferral_end, maturity) if start < d <= maturity)
    pay_days.update(_day(date) for date, _ in loan["schedule"] if _day(date) > start)
    deferred_due_now = deferral_end <= start  # отсрочка уже кончилась — долг по ней к первой дате
    interest_total: float | None = 0.0 if rates_ok else None
    day = start
    while day < maturity:
        day += datetime.timedelta(days=1)
        # Проценты за день — на остаток утра, до операций дня.
        if rates_ok:
            rate = (_rate_on(key_rate, day) + bump + loan["margin_pp"]) / 100.0
            share = rate / _year_days(day, basis)
            if day <= deferral_end:
                if _known(deferred, iod):
                    iod += deferred * share
                    deferred += principal * share
            else:
                accrued += principal * share
            interest_total += principal * share
        if day <= availability_end:
            fee_acc += max(0.0, limit - drawn) * loan["fee_free_limit_pct"] / 100.0 \
                / _year_days(day, basis)
        for kind, amount in events.get(day, []):
            if kind == "draw":
                take = min(amount, max(0.0, limit - drawn))
                if amount - take > 1.0:
                    out["gaps"].append(f"{loan['name']}: выборка {mln(amount)} млн ₽ на "
                                       f"{ddmmyyyy(day)} выше свободного лимита — учтено "
                                       f"{mln(take)} млн ₽.")
                principal += take
                drawn += take
            else:
                paid = min(amount, principal)
                principal -= paid
                if installments is not None:
                    _reduce(installments, paid, day, order)
                elif not reflected_before_base:
                    pending += paid
        if day == base_day and installments is None and start < base_day:
            base = principal if loan["base"] == "debt_at_availability_end" else drawn
            installments = _schedule(loan, base)
            base_info.update(amount=base, kind="прогноз",
                             source="долг по фактам плюс прогнозные выборки и погашения",
                             as_of=facts["as_of"])
            if pending:
                _reduce(installments, pending, day, order)
        if day not in pay_days:
            continue
        if installments is not None:
            due_principal: float | None = principal if day == maturity else min(
                principal, sum(item["amount"] for item in installments
                               if _day(item["date"]) == day))
            principal -= due_principal
        elif day < base_day:
            due_principal = 0.0
        else:
            due_principal = None
        due_interest = accrued if day > deferral_end else 0.0
        if day > deferral_end and accrued is not None:
            accrued = 0.0
        due_deferred = due_iod = 0.0
        if day == deferral_end or deferred_due_now:
            due_deferred, due_iod = deferred, iod
            deferred = iod = 0.0
            deferred_due_now = False
        due_fee = fee_acc
        fee_acc = 0.0
        out["payments"][day.isoformat()] = {
            "principal": due_principal, "interest": due_interest,
            "deferred": due_deferred, "interest_on_deferred": due_iod, "fee": due_fee,
            "total": _sum(due_principal, due_interest, due_deferred, due_iod, due_fee),
            "debt_after": principal if installments is not None or day < base_day else None,
            "share": next((item["share"] for item in installments or []
                           if item["date"] == day.isoformat()), None),
        }
    out["installments"] = installments
    out["interest_total"] = interest_total
    out["start"] = start.isoformat()
    out["debt_now"] = f["debt"]
    out["facts_as_of"] = facts["as_of"]
    out["facts_source"] = facts["source"]
    return out


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
            shares = _split(row["disclosed_used"], totals, rule)
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
        row["late_disclosure"] = (bool(later) and bool(row.get("need_outside"))
                                  and bool(row.get("principal")))
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
    loans = []
    for loan in preset["loans"]:
        # Отсрочка кончается раньше, если все эскроу проекта закрыты (ТЗ, п. 2).
        limit = _day(loan["deferral_limit"])
        closed = _day(escrow["closed_on"]) if escrow.get("closed_on") else None
        end = min(limit, closed) if closed else limit
        run = _run_loan(loan, datasets, scenario, end)
        run["deferral_reason"] = (
            f"все эскроу закрываются {ddmmyyyy(closed)} — раньше предельной даты "
            f"{ddmmyyyy(limit)}" if closed and closed < limit
            else f"предельная дата отсрочки по договору ({TZ}, п. 2)")
        run["limit"] = loan["limit"]
        run["number"] = loan["number"]
        gaps += [g for g in run["gaps"] if g not in gaps]
        loans.append(run)
    rule = loans[0]["terms"]["disclosure_split"]["value"] if loans else "pro_rata"
    rows = _cover(loans, escrow, datasets, rule)
    out = {"scenario": scenario, "loans": loans, "escrow": escrow, "rows": rows,
           "gaps": gaps, "split_rule": loans[0]["terms"]["disclosure_split"] if loans else None,
           "months": _months(rows, escrow), "datasets": _dataset_dates(datasets),
           "notes": list(escrow.get("notes") or [])}
    out["top"] = _top(out, datasets)
    return out


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
                       + [f"deferred.{l['id']}" for l in loans] + ["key_rate"]]}
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
            "Статус не определён: не хватает исходных данных — " + "; ".join(base["gaps"][:3])]}
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
            lines.append(
                f"<li>{_esc(names[lid])}: основной долг {mln(item['principal'])}{share} + "
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
    return ("<details class='credit-terms'><summary>Условия расчёта и их источник"
            "</summary><table><tr><th>Кредит</th><th>Условие</th><th>Откуда</th></tr>"
            + "".join(rows) + "</table></details>")


_TERM_WORDS = {"rate": "Ставка", "day_basis": "Начисление процентов",
               "pay_dates": "Даты уплаты процентов и комиссии",
               "deferred_rate": "Проценты на отложенные проценты",
               "prepayment_order": "Досрочное погашение", "disclosure_split":
               "Раскрытое эскроу между кредитами"}


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
    out = [_status_html(result["status"]), _top_html(result), _main_table(result),
           _detail_html(result), _months_html(result), _gaps_html(result)]
    if changes is not None:
        out.insert(1, "<h3>Что изменилось против прошлого прогноза</h3>" + (
            "<ul>" + "".join(f"<li class='{c['tone']}'>{_esc(c['text'])}</li>" for c in changes)
            + "</ul>" if changes else "<p class='note'>Прошлого прогноза с другими данными "
            "нет или существенных изменений не видно.</p>"))
    out.append(_stress_html(result))
    out.append(_datasets_html(result))
    if monitor:
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
                stress: dict[str, Any] | None = None) -> dict[str, Any]:
    """Прогноз проекта по сохранённым данным; нет данных — причина."""
    inputs = inputs_for(project, sales_project, sales_dir)
    # Договоры из отчёта о продажах есть у многих проектов; кредитным проект
    # делает только загрузка данных по кредитам.
    if not inputs.get("preset"):
        return {"state": "missing",
                "reason": "Данные по кредитам не загружены: долг, выдачи, эскроу и прогноз "
                          "поступлений вносятся на странице Монитора, раздел «Погашение "
                          "кредитов»."}
    result = analyse(inputs, stress)
    result["preset_id"] = inputs.get("preset") or "kutuzov_city"
    result["state"] = "ok"
    return result
