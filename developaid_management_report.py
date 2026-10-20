"""Управленческая сводка по проекту: стройка, деньги стройки, продажи.

Сводка собирается здесь один раз и раздаётся всем поверхностям: сообщению
в Telegram, PDF и странице. Своих расчётов у неё нет — она читает тех,
кто уже отвечает за каждое число:

* физическое выполнение — проценты работ из еженедельного ГПР-факта и
  точечных фактов страницы (`manager._baseline_status`), план — по датам
  утверждённого ГПР (`monitor._plan_progress`);
* бюджет месяца — план из план-факта БДДС против реестра платежей РСС
  (`developaid_monthly_budget`);
* общая информация — записи, введённые руками на странице проекта
  (`developaid_project_notes`);
* продажи — договоры контрактации, план финмодели по месяцам
  (`contracting.fm_plan_by_month`) и квартальный план банка.

Чего нет, то названо причиной: пустой блок не равен нулю.
"""

from __future__ import annotations

import datetime
import html
from pathlib import Path
from typing import Any

import developaid_monitor as monitor
import developaid_monitor_manager as manager
import developaid_monthly_budget as monthly_budget
import developaid_project_notes as project_notes
from market_search import contracting, sales_store

PERIODS = {"week": "неделю", "month": "месяц"}

_MONTHS = ("январь", "февраль", "март", "апрель", "май", "июнь", "июль",
           "август", "сентябрь", "октябрь", "ноябрь", "декабрь")


def _date(value: Any) -> datetime.date:
    if isinstance(value, datetime.datetime):
        return value.date()
    if isinstance(value, datetime.date):
        return value
    return datetime.date.fromisoformat(str(value)[:10])


def period_bounds(kind: str, end: Any) -> dict[str, datetime.date]:
    """Границы периода, который заканчивается днём ``end`` включительно.

    Неделя — семь дней по ``end``; месяц — календарный месяц, в котором
    лежит ``end`` (месячная сводка уходит первого числа за прошлый месяц).
    """
    if kind not in PERIODS:
        raise ValueError(f"неизвестный период сводки: {kind!r}")
    last = _date(end)
    first = (last - datetime.timedelta(days=6) if kind == "week"
             else last.replace(day=1))
    return {"start": first, "end": last,
            "before": first - datetime.timedelta(days=1)}


def _missing(reason: str) -> dict[str, Any]:
    return {"state": "missing", "reason": reason}


# --------------------------------------------------------------------------
# Стройка: физическое выполнение по ГПР
# --------------------------------------------------------------------------

def _weighted(items: list[tuple[float, float]]) -> float | None:
    total = sum(weight for weight, _ in items)
    if total <= 0:
        return None
    return sum(weight * value for weight, value in items) / total


def _snapshot_day(project: str, upto: datetime.date) -> str:
    path = monitor._latest(project, "schedule_fact", ".xlsx", upto.isoformat())
    return path.stem if path is not None else ""


def physical(project: str, kind: str, end: Any) -> dict[str, Any]:
    """Физическое выполнение: факт ГПР на конец и начало периода против плана.

    Процент работы — тот, что прораб ставит в ГПР-факте (или точечный факт со
    страницы). Общий процент — среднее по работам, взвешенное длительностью
    работы по утверждённому ГПР: стоимости у работы в ГПР нет.
    """
    bounds = period_bounds(kind, end)
    try:
        baseline = monitor._read_baseline_gpr(project)
    except FileNotFoundError:
        return _missing("Не загружен утверждённый ГПР проекта.")
    now_day = _snapshot_day(project, bounds["end"])
    if not now_day:
        return _missing(
            "Не загружен ни один ГПР-факт с процентами выполнения "
            f"на {bounds['end']:%d.%m.%Y}.")
    before_day = _snapshot_day(project, bounds["before"])
    now = manager._baseline_status(project, bounds["end"].isoformat())
    before = (manager._baseline_status(project, bounds["before"].isoformat())
              if before_day else {})

    fact_now: list[tuple[float, float]] = []
    fact_before: list[tuple[float, float]] = []
    plan_now: list[tuple[float, float]] = []
    objects: dict[str, dict[str, list[tuple[float, float]]]] = {}
    unknown = 0
    for work in baseline.get("works") or []:
        start, finish = work.get("start"), work.get("finish")
        tid = str(work.get("id") or work.get("wbs") or "").strip()
        if not tid or not start or not finish:
            continue
        weight = float(max(1, (finish - start).days))
        plan = monitor._plan_progress(start, finish, bounds["end"])
        progress = (now.get(tid) or {}).get("progress")
        if progress is None:
            unknown += 1
            continue
        plan_now.append((weight, plan))
        fact_now.append((weight, progress))
        group = objects.setdefault(str(work.get("object") or "").strip()
                                   or "Без объекта", {"plan": [], "fact": []})
        group["plan"].append((weight, plan))
        group["fact"].append((weight, progress))
        if before_day:
            earlier = (before.get(tid) or {}).get("progress")
            fact_before.append((weight, earlier if earlier is not None else 0.0))
    if not fact_now:
        return _missing(f"В ГПР-факте от {now_day} нет процентов выполнения "
                        "ни у одной работы.")
    fact = _weighted(fact_now)
    earlier = _weighted(fact_before) if before_day else None
    return {
        "state": "ok",
        "snapshot": now_day,
        "snapshot_before": before_day or None,
        # Новый ГПР-факт за период не пришёл — прирост ноль не наблюдён,
        # а просто не измерен заново.
        "fresh": now_day >= bounds["start"].isoformat(),
        "plan": _weighted(plan_now),
        "fact": fact,
        "fact_before": earlier,
        "delta": (fact - earlier) if earlier is not None else None,
        "works": len(fact_now),
        "works_unknown": unknown,
        "objects": [
            {"object": name, "plan": _weighted(group["plan"]),
             "fact": _weighted(group["fact"])}
            for name, group in sorted(objects.items())],
    }


# --------------------------------------------------------------------------
# Деньги стройки: бюджет месяца
# --------------------------------------------------------------------------

def budget(project: str, kind: str, end: Any) -> dict[str, Any]:
    """План месяца из план-факта БДДС против оплат по РСС: стройка и коммерция.

    Месяц — тот, в котором кончается период. Карта строк и кодов РСС живёт в
    `developaid_monthly_budget`.
    """
    return monthly_budget.month_budget(project, period_bounds(kind, end)["end"])


# --------------------------------------------------------------------------
# Продажи
# --------------------------------------------------------------------------

def _signed(row: dict[str, Any]) -> datetime.date | None:
    try:
        return _date(row["signed"]) if row.get("signed") else None
    except ValueError:
        return None


def _fact(rows: list[dict[str, Any]]) -> dict[str, Any]:
    totals = contracting._totals(rows)
    flats = contracting._totals(
        [row for row in rows
         if contracting.product_name(row["product"]) == "Квартира"])
    return {"contracts": int(totals["contracts"]), "units": totals["units"],
            "area": totals["area"], "amount": totals["amount"],
            "area_unknown": int(totals["area_unknown"]),
            # Цена — по квартирам: банк и финмодель называют её так же, а
            # общая цена метра смешала бы паркинг с жильём.
            "price_flats": flats["price_per_sqm"] or None}


def sales(sales_project: str, kind: str, end: Any,
          data_dir: Path | None = None) -> dict[str, Any]:
    """Продажи за период и с начала квартала против плана ФМ и банка."""
    if not str(sales_project or "").strip():
        return _missing("Проект не связан с отчётом о продажах.")
    bounds = period_bounds(kind, end)
    kept = sales_store.load(data_dir or sales_store.default_dir(), sales_project)
    sources = kept.get("sources") or {}

    def part(name: str) -> Any:
        return ((sources.get(name) or {}).get("data")) or None

    contracts = part("contracting")
    if not contracts:
        return _missing(f"В отчёте о продажах проекта «{sales_project}» "
                        "не загружена контрактация.")
    rows = contracts.get("rows") or []
    dated = [(row, _signed(row)) for row in rows]
    undated = sum(1 for _, day in dated if day is None)

    def between(first: datetime.date) -> list[dict[str, Any]]:
        return [row for row, day in dated
                if day is not None and first <= day <= bounds["end"]]

    month_start = bounds["end"].replace(day=1)
    quarter_start = month_start.replace(month=(month_start.month - 1) // 3 * 3 + 1)
    month_key = month_start.strftime("%Y-%m")
    quarter = contracting.quarter_of(month_key)

    fm = contracting.fm_plan_by_month(part("fm_plan"))
    fm_month = fm.get(month_key)
    fm_quarter_months = [values for month, values in fm.items()
                         if contracting.quarter_of(month) == quarter]
    fm_quarter = ({"amount": sum(v["amount"] for v in fm_quarter_months),
                   "area": sum(v["area"] for v in fm_quarter_months)}
                  if fm_quarter_months else None)

    bank = part("bank_plan") or {}
    bank_quarter = None
    bank_reason = ""
    if not bank:
        bank_reason = "План банка не загружен."
    elif quarter in (bank.get("gross_by_quarter") or {}):
        comparison = contracting.plan_comparison(
            dict(contracting.summarise(contracts, part("ledger") or {}),
                 fm_plan=part("fm_plan"), bank_plan=bank))
        opening = comparison.get("bank_opening") or {}
        if opening.get("quarter") == quarter:
            bank_reason = ("В первом квартале плана банка лежат продажи с начала "
                           "проекта — с кварталом его сравнивать нельзя.")
        else:
            bank_quarter = {
                "amount": float(bank["gross_by_quarter"][quarter]),
                "area": (bank.get("area_by_quarter") or {}).get(quarter),
                "price": (bank.get("price_by_quarter") or {}).get(quarter)}
    else:
        bank_reason = f"В плане банка нет квартала {quarter}."

    uploaded = (sources.get("contracting") or {}).get("at") or ""
    return {
        "state": "ok",
        "project": kept.get("project") or sales_project,
        "uploaded": uploaded or None,
        # Договоры, подписанные после загрузки контрактации, сводке не видны.
        "stale": bool(uploaded) and uploaded[:10] < bounds["end"].isoformat(),
        "undated": undated,
        "period": _fact(between(bounds["start"])),
        "month": {"key": month_key, "fact": _fact(between(month_start)),
                  "fm": fm_month},
        "quarter": {"key": quarter, "fact": _fact(between(quarter_start)),
                    "fm": fm_quarter, "bank": bank_quarter,
                    "bank_reason": bank_reason or None},
    }


# --------------------------------------------------------------------------
# Сводка целиком
# --------------------------------------------------------------------------

def build(project: str, kind: str, end: Any, sales_project: str = "",
          sales_dir: Path | None = None) -> dict[str, Any]:
    """Сводка за неделю или месяц по проекту мониторинга ``project``."""
    bounds = period_bounds(kind, end)
    blocks: dict[str, Any] = {}
    for name, collect in (
            ("physical", lambda: physical(project, kind, bounds["end"])),
            ("budget", lambda: budget(project, kind, bounds["end"])),
            ("sales", lambda: sales(sales_project, kind, bounds["end"], sales_dir)),
            ("notes", lambda: dict(project_notes.for_period(
                project, bounds["start"], bounds["end"]), state="ok"))):
        try:
            blocks[name] = collect()
        except Exception as exc:  # noqa: BLE001
            # Сломанный файл одного блока не должен гасить всю сводку, но
            # причина должна дойти до читателя, а не остаться в логе.
            blocks[name] = _missing(
                f"Блок не собран: {type(exc).__name__}: {exc}")
    return {"project": project, "kind": kind,
            "start": bounds["start"].isoformat(),
            "end": bounds["end"].isoformat(), **blocks}


# --------------------------------------------------------------------------
# Текст сообщения
# --------------------------------------------------------------------------

def _pct(value: float | None) -> str:
    return "—" if value is None else f"{value * 100:.1f}".replace(".", ",") + "%"


def _pp(value: float) -> str:
    sign = "+" if value >= 0 else "−"
    return f"{sign}{abs(value) * 100:.1f}".replace(".", ",") + " п. п."


def _rub(value: float | None) -> str:
    if value is None:
        return "—"
    sign = "−" if value < 0 else ""
    amount = abs(value)
    if amount >= 1e9:
        text = f"{amount / 1e9:.2f} млрд ₽"
    elif amount >= 1e6:
        text = f"{amount / 1e6:.1f} млн ₽"
    else:
        text = f"{amount:,.0f} ₽".replace(",", " ")
    return sign + text.replace(".", ",")


def _area(value: float | None) -> str:
    return "—" if value is None else f"{value:,.0f} м²".replace(",", " ")


def _day(value: str | None) -> str:
    return _date(value).strftime("%d.%m.%Y") if value else "—"


def _title(report: dict[str, Any]) -> str:
    start, end = _date(report["start"]), _date(report["end"])
    if report["kind"] == "month":
        return f"за {_MONTHS[end.month - 1]} {end.year}"
    return f"за неделю {start:%d.%m} — {end:%d.%m.%Y}"


def _sales_line(label: str, fact: dict[str, Any]) -> str:
    price = (f", квартиры в среднем по {_rub(fact['price_flats'])} за м²"
             if fact.get("price_flats") else "")
    return (f"{label}: {fact['contracts']} договоров на {_rub(fact['amount'])}, "
            f"{_area(fact['area'])}{price}.")


def render_text(report: dict[str, Any]) -> str:
    """Сообщение для Telegram (разметка HTML) — из той же сводки, что и PDF."""
    esc = html.escape
    lines = [f"<b>Сводка по проекту «{esc(report['project'])}» {_title(report)}</b>"]

    lines += ["", "<b>Стройка</b>"]
    block = report.get("physical") or {}
    if block.get("state") == "ok":
        lines.append(f"Выполнено по графику работ {_pct(block['fact'])}, "
                     f"по плану к этой дате должно быть {_pct(block['plan'])}.")
        if block.get("delta") is not None:
            lines.append(f"За {PERIODS[report['kind']]} выполнение выросло "
                         f"на {_pp(block['delta'])}.")
        else:
            lines.append("Прирост за период посчитать не из чего: на начало "
                         "периода не было ни одного графика с процентами выполнения.")
        if not block.get("fresh"):
            lines.append(f"Внимание: за этот период новый график с процентами "
                         f"не загружали, последний — от {_day(block['snapshot'])}.")
    else:
        lines.append(esc(block.get("reason") or "Данных нет."))

    lines += ["", "<b>Бюджет месяца</b>"]
    block = report.get("budget") or {}
    if block.get("state") in {"ok", "partial"}:
        month = _date(block["month"])
        name = f"{_MONTHS[month.month - 1]} {month.year}"
        for line in block["lines"]:
            if line.get("plan") is not None:
                lines.append(f"{line['label']} за {name}: план {_rub(line['plan'])}, "
                             f"оплачено {_rub(line['fact'])}, "
                             f"осталось {_rub(line['remaining'])}.")
            else:
                lines.append(f"{line['label']} за {name}: оплачено {_rub(line['fact'])}.")
        if block.get("reason"):
            lines.append(esc(block["reason"]))
        lines.append(f"Оплаты взяты из отчёта РСС от {_day(block['rss'])}.")
    else:
        lines.append(esc(block.get("reason") or "Данных нет."))

    lines += ["", "<b>Продажи</b>"]
    block = report.get("sales") or {}
    if block.get("state") == "ok":
        lines.append(_sales_line(f"За {PERIODS[report['kind']]}", block["period"]))
        month = block["month"]
        if month.get("fm"):
            lines.append(f"План финмодели на месяц: {_rub(month['fm']['amount'])}, "
                         f"{_area(month['fm']['area'])}; продано с начала месяца "
                         f"{_rub(month['fact']['amount'])}, {_area(month['fact']['area'])}.")
        quarter = block["quarter"]
        lines.append(_sales_line(f"С начала квартала {quarter['key']}", quarter["fact"]))
        if quarter.get("fm"):
            lines.append(f"План финмодели на квартал: {_rub(quarter['fm']['amount'])}, "
                         f"{_area(quarter['fm']['area'])}.")
        if quarter.get("bank"):
            lines.append(f"План банка на квартал: {_rub(quarter['bank']['amount'])}, "
                         f"{_area(quarter['bank'].get('area'))}.")
        elif quarter.get("bank_reason"):
            lines.append(esc(quarter["bank_reason"]))
        if block.get("stale"):
            lines.append(f"Внимание: договоры загружены {_day(block['uploaded'])}, "
                         "более поздние сделки в сводку не попали.")
    else:
        lines.append(esc(block.get("reason") or "Данных нет."))

    block = report.get("notes") or {}
    lines += ["", "<b>Общая информация</b>"]
    if block.get("state") != "ok":
        lines.append(esc(block.get("reason") or "Данных нет."))
    elif not block.get("open") and not block.get("closed"):
        lines.append("Открытых вопросов нет, за период записей не было.")
    else:
        for note in block.get("open") or []:
            mark = " (новое)" if note.get("changed") else ""
            lines.append(f"• <b>{esc(note['topic'])}</b>{mark}: {esc(note['text'])} "
                         f"— {_day(note['at'])}, {esc(note['author'])}.")
        for note in block.get("closed") or []:
            lines.append(f"• <b>{esc(note['topic'])}</b> — вопрос закрыт: "
                         f"{esc(note['text'])} — {_day(note['at'])}, {esc(note['author'])}.")
    return "\n".join(lines)


# --------------------------------------------------------------------------
# Документ для PDF и для просмотра на странице
# --------------------------------------------------------------------------

REPORT_STYLE = """
body{font-family:-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif;color:#17202a;font-size:12px;margin:0}
h1{font-size:18px;margin:0 0 2px}h2{font-size:14px;margin:18px 0 6px;border-bottom:1px solid #d6dde6;padding-bottom:3px}
.sub{color:#5b6b7d;font-size:11px;margin-bottom:8px}
table{border-collapse:collapse;width:100%;margin:4px 0}th,td{border:1px solid #d6dde6;padding:4px 6px;text-align:right}
th:first-child,td:first-child{text-align:left}th{background:#f2f5f8;font-weight:600}
.note{color:#5b6b7d;font-size:11px;margin:4px 0}.warn{color:#9a5b00}.missing{color:#9a5b00;font-style:italic}
.item{margin:4px 0}.item b{font-weight:600}
"""


def _month_name(key: str) -> str:
    """«2026-10» → «октябрь 2026»."""
    year, month = str(key).split("-")[:2]
    return f"{_MONTHS[int(month) - 1]} {year}"


def _quarter_name(key: str) -> str:
    """«2026 Q4» → «4 квартал 2026»."""
    year, number = str(key).split(" Q")
    return f"{number} квартал {year}"


def _row(cells: list[str], head: bool = False) -> str:
    tag = "th" if head else "td"
    return "<tr>" + "".join(f"<{tag}>{cell}</{tag}>" for cell in cells) + "</tr>"


def _table(head: list[str], rows: list[list[str]]) -> str:
    return "<table>" + _row(head, True) + "".join(_row(row) for row in rows) + "</table>"


def render_html(report: dict[str, Any]) -> str:
    """Тело документа сводки — те же числа, что в сообщении, таблицами."""
    esc = html.escape
    out = [f"<h1>Сводка по проекту «{esc(report['project'])}»</h1>",
           f"<div class='sub'>{esc(_title(report))}</div>"]

    def missing(block: dict[str, Any]) -> str:
        return f"<p class='missing'>{esc(block.get('reason') or 'Данных нет.')}</p>"

    out.append("<h2>Стройка</h2>")
    block = report.get("physical") or {}
    if block.get("state") == "ok":
        out.append(_table(["", "План к дате", "Выполнено", "Отставание"], [[
            "Весь проект", _pct(block["plan"]), _pct(block["fact"]),
            _pp(block["fact"] - block["plan"]) if block.get("plan") is not None else "—"]]
            + [[esc(item["object"]), _pct(item["plan"]), _pct(item["fact"]),
                _pp(item["fact"] - item["plan"]) if item.get("plan") is not None else "—"]
               for item in block.get("objects") or []]))
        if block.get("delta") is not None:
            out.append(f"<p class='note'>За {PERIODS[report['kind']]} выполнение выросло "
                       f"на {_pp(block['delta'])}. Проценты — из графика работ от "
                       f"{_day(block['snapshot'])}.</p>")
        else:
            out.append("<p class='note'>Прирост за период посчитать не из чего: на начало "
                       "периода не было графика с процентами выполнения.</p>")
        if not block.get("fresh"):
            out.append(f"<p class='note warn'>За этот период новый график с процентами "
                       f"не загружали, последний — от {_day(block['snapshot'])}.</p>")
    else:
        out.append(missing(block))

    out.append("<h2>Бюджет месяца</h2>")
    block = report.get("budget") or {}
    if block.get("state") in {"ok", "partial"}:
        month = _date(block["month"])
        out.append(f"<div class='sub'>{_MONTHS[month.month - 1]} {month.year}</div>")
        out.append(_table(["Статья", "План", "Оплачено", "Осталось"], [
            [esc(line["label"]), _rub(line.get("plan")), _rub(line["fact"]),
             _rub(line.get("remaining"))] for line in block["lines"]]))
        if block.get("reason"):
            out.append(f"<p class='note warn'>{esc(block['reason'])}</p>")
        out.append(f"<p class='note'>Оплаты — из отчёта РСС от {_day(block['rss'])}.</p>")
    else:
        out.append(missing(block))

    out.append("<h2>Продажи</h2>")
    block = report.get("sales") or {}
    if block.get("state") == "ok":
        def fact_cells(fact: dict[str, Any]) -> list[str]:
            return [str(fact["contracts"]), _rub(fact["amount"]), _area(fact["area"]),
                    _rub(fact.get("price_flats")) if fact.get("price_flats") else "—"]

        month, quarter = block["month"], block["quarter"]
        rows = [[f"За {PERIODS[report['kind']]}", *fact_cells(block["period"])]]
        if report["kind"] != "month":
            rows.append([f"С начала месяца ({_month_name(month['key'])})",
                         *fact_cells(month["fact"])])
        rows.append([f"С начала квартала ({_quarter_name(quarter['key'])})",
                     *fact_cells(quarter["fact"])])
        out.append(_table(["Факт", "Договоров", "Сумма", "Площадь", "Цена квартир, ₽/м²"], rows))
        plans = []
        if month.get("fm"):
            plans.append(["План финмодели на месяц", _rub(month["fm"]["amount"]),
                          _area(month["fm"]["area"])])
        if quarter.get("fm"):
            plans.append(["План финмодели на квартал", _rub(quarter["fm"]["amount"]),
                          _area(quarter["fm"]["area"])])
        if quarter.get("bank"):
            plans.append(["План банка на квартал", _rub(quarter["bank"]["amount"]),
                          _area(quarter["bank"].get("area"))])
        if plans:
            out.append(_table(["План", "Сумма", "Площадь"], plans))
        if quarter.get("bank_reason"):
            out.append(f"<p class='note'>{esc(quarter['bank_reason'])}</p>")
        if block.get("stale"):
            out.append(f"<p class='note warn'>Договоры загружены {_day(block['uploaded'])}, "
                       "более поздние сделки в сводку не попали.</p>")
    else:
        out.append(missing(block))

    out.append("<h2>Общая информация</h2>")
    block = report.get("notes") or {}
    if block.get("state") != "ok":
        out.append(missing(block))
    elif not block.get("open") and not block.get("closed"):
        out.append("<p class='note'>Открытых вопросов нет, за период записей не было.</p>")
    else:
        for note in block.get("open") or []:
            mark = " (новое)" if note.get("changed") else ""
            out.append(f"<div class='item'><b>{esc(note['topic'])}</b>{mark}: "
                       f"{esc(note['text'])} <span class='note'>— {_day(note['at'])}, "
                       f"{esc(note['author'])}</span></div>")
        for note in block.get("closed") or []:
            out.append(f"<div class='item'><b>{esc(note['topic'])}</b> — вопрос закрыт: "
                       f"{esc(note['text'])} <span class='note'>— {_day(note['at'])}, "
                       f"{esc(note['author'])}</span></div>")
    return "\n".join(out)
