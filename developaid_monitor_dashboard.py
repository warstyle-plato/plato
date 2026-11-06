"""Management KPI, funding-risk and recurring-input layer for Project Monitor.

Funding is calculated article-by-article. A free balance in one RSS article is
not silently allowed to finance another article. Once an article's own balance
is exhausted, that month's need consumes the explicit 2.8/2.9 reserve; only
after the reserve is exhausted does the model report uncovered financing.
"""
from __future__ import annotations

import datetime
import io
import json
import re
from pathlib import Path
from typing import Any

import developaid_actuals as actuals
import developaid_monitor as monitor
import developaid_monitor_schedule_graph as schedule_graph

_INSTALLED = False
_ORIGINAL_BUILD = None
_ORIGINAL_STORE_SALES_FILE = None
_ORIGINAL_STORE_PROPOSAL = None


# Резерв 2.8/2.9 — не статья: у него нет ни договоров, ни программы, он гасит
# нехватку других статей. В список статей он не попадает ни как потребность,
# ни как источник перераспределения.
_RESERVE_CODES = frozenset({"2.8", "2.9"})


def _norm(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip().lower().replace("ё", "е"))


def _finance_file(project: str) -> Path:
    return monitor._project_dir(project) / "baseline" / "finance.xlsx"


def _source_day(value: Any) -> str | None:
    day = monitor._day(value)
    return day.isoformat() if day else None


def _stored_funding_source(project: str, path: Path) -> dict[str, Any]:
    """Дата данных из метаданных или имени снимка в каноническом хранилище.

    Произвольное исходное имя файла и mtime не являются датой данных.
    """
    if path == _finance_file(project):
        meta = monitor.finance_baseline_meta(project)
    else:
        try:
            meta = json.loads(path.with_suffix(".json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            meta = {}
        if not isinstance(meta, dict):
            meta = {}
    day = _source_day(meta.get("taken_at"))
    root = monitor._project_dir(project)
    if day is None and path.parent in (root / "estimate", root / "funding_schedule"):
        day = _source_day(path.stem)
    return {"data_date": day, "uploaded_at": meta.get("uploaded_at") or meta.get("loaded_at"),
            "file": meta.get("file_name") or meta.get("filename") or path.name}


def _funding_source_dates(project: str, rss: Path, cut: datetime.date,
                          schedule: dict[str, Any] | None = None) -> dict[str, Any]:
    return {"report_date": cut.isoformat(),
            "budget": _stored_funding_source(project, _finance_file(project)),
            "rss": _stored_funding_source(project, rss), "schedule_used": schedule is not None,
            "schedule": ((schedule or {}).get("source_dates", {
                "data_date": _source_day((schedule or {}).get("day")),
                "file": (schedule or {}).get("file") or ""}) if schedule else {})}


def funding_source_notes(funding: dict[str, Any]) -> dict[str, str]:
    """Единые видимые даты карточек, Монитора, текста и печатной сводки."""
    dates = funding.get("source_dates") or {}
    meta = funding.get("baseline_file") or {}
    budget = dates.get("budget") or {
        "data_date": _source_day(meta.get("taken_at")), "uploaded_at": meta.get("uploaded_at"),
        "file": meta.get("file_name") or ""}
    rss = dates.get("rss") or {}
    schedule = dates.get("schedule") or {}

    def when(value: Any) -> str:
        day = monitor._day(value)
        return day.strftime("%d.%m.%Y") if day else "дата данных не указана"

    def version(source: dict[str, Any]) -> str:
        return "от " + when(source["data_date"]) if source.get("data_date") else "дата данных не указана"

    def file_note(source: dict[str, Any]) -> str:
        return f" Файл «{source['file']}»." if source.get("file") else ""

    report_day = dates.get("report_date")
    report_note = ("Расчёт на " + when(report_day) + "." if report_day
                   else "Дата расчётного среза не указана.")
    book_name = "Финмодель" if funding.get("need_basis") == "model" else "Финансовая книга"
    budget_note = (book_name + ": версия " + version(budget) + "." if budget.get("data_date")
                   else book_name + ": дата данных не указана.") + file_note(budget)
    uploaded = _source_day(budget.get("uploaded_at"))
    if uploaded:
        budget_note += " Загружена " + when(uploaded) + "."
    if budget.get("data_date") and report_day and budget["data_date"] > report_day:
        budget_note += " Версия финансовой базы позже даты расчётного среза."
    notes = {
        "budget": budget_note,
        "paid": "Оплаты учтены по РСС: " + version(rss) + ". " + report_note + file_note(rss),
        "limit": "Смета банка — РСС: " + version(rss) + "." + file_note(rss),
        "left": "Смета и оплаты для остатка лимита — РСС: " + version(rss) + ". " + report_note,
    }
    sources = [book_name.lower() + ": " + version(budget), "РСС: " + version(rss)]
    if dates.get("schedule_used"):
        notes["schedule"] = "График финансирования: " + version(schedule) + "." + file_note(schedule)
        sources.append("график финансирования: " + version(schedule))
    notes["need"] = report_note + " Источники расчёта: " + "; ".join(sources) + "."
    return notes


def funding_reconciliation_lines(funding: dict[str, Any], money: Any) -> list[str]:
    """Даты и существующая арифметическая сверка рядом с дофинансированием."""
    return (list(funding_source_notes(funding).values())
            + reconciliation_lines(funding.get("limit_reconciliation") or {}, money)
            + own_budget_reconciliation_lines(funding.get("own_money"), money))


def _sales_dir(project: str) -> Path:
    path = monitor._project_dir(project) / "sales"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _latest_sales(project: str, upto: datetime.date | None = None) -> Path | None:
    folder = monitor._project_dir(project) / "sales"
    if not folder.exists():
        return None
    rows = sorted(folder.glob("*.xlsx"))
    if upto:
        rows = [row for row in rows if row.stem[:10] <= upto.isoformat()]
    return rows[-1] if rows else None


def _find_header(ws: Any, needle: str, max_rows: int = 20) -> tuple[int, int] | None:
    wanted = _norm(needle)
    for r, row in enumerate(
        ws.iter_rows(min_row=1, max_row=min(ws.max_row, max_rows), values_only=True), 1
    ):
        for c, value in enumerate(row, 1):
            if wanted in _norm(value):
                return r, c
    return None


def _month_value(value: Any, year: int, previous_month: int) -> tuple[datetime.date | None, int, int]:
    if isinstance(value, datetime.datetime):
        day = value.date().replace(day=1)
        return day, day.year, day.month
    if isinstance(value, datetime.date):
        day = value.replace(day=1)
        return day, day.year, day.month
    ru_months = {
        "январь": 1, "февраль": 2, "март": 3, "апрель": 4,
        "май": 5, "июнь": 6, "июль": 7, "август": 8,
        "сентябрь": 9, "октябрь": 10, "ноябрь": 11, "декабрь": 12,
    }
    month = ru_months.get(_norm(value))
    if not month:
        return None, year, previous_month
    if previous_month and month < previous_month:
        year += 1
    return datetime.date(year, month, 1), year, month


_FINANCE_CACHE: dict[tuple, dict[str, Any]] = {}


def _finance_baseline(project: str) -> dict[str, Any]:
    """Финансовый baseline. Результат помнится по (путь, mtime, размер).

    Читается один раз одним проходом: на read-only книге каждый `ws.cell()`
    перечитывает XML листа целиком, и 904 обращения стоили 23 секунды на
    срез — при том что baseline по определению неизменен.
    """
    import copy as _copy
    import os as _os

    path = _finance_file(project)
    if not path.exists():
        return {"known": False, "reason": "не загружен финансовый baseline"}
    stat = _os.stat(path)
    key = (str(path), stat.st_mtime_ns, stat.st_size)
    if key in _FINANCE_CACHE:
        return _copy.deepcopy(_FINANCE_CACHE[key])
    result = _read_finance_baseline(path)
    if len(_FINANCE_CACHE) > 8:
        _FINANCE_CACHE.clear()
    _FINANCE_CACHE[key] = result
    return _copy.deepcopy(result)


class _Grid:
    """Лист, прочитанный одним проходом, с интерфейсом cell(row, col)."""

    def __init__(self, ws: Any) -> None:
        self.rows = list(ws.iter_rows(values_only=True))
        self.max_row = len(self.rows)
        self.max_column = max((len(row) for row in self.rows), default=0)

    class _Cell:
        __slots__ = ("value",)

        def __init__(self, value: Any) -> None:
            self.value = value

    def cell(self, row: int, column: int) -> "_Grid._Cell":
        values = self.rows[row - 1] if 0 < row <= len(self.rows) else ()
        return self._Cell(values[column - 1] if 0 < column <= len(values) else None)

    def iter_rows(self, min_row: int = 1, max_row: int | None = None,
                  values_only: bool = True) -> Any:
        stop = max_row if max_row is not None else len(self.rows)
        return iter(self.rows[min_row - 1:stop])


# Финансовый baseline приходит одной из двух книг: финкнигой банка (лист
# «Расчет стоимости строительства» с колонками утверждённой модели и средств
# на завершение) или нашей финмоделью (лист «cf_1_new»: колонки «ИТОГО»,
# «ФАКТ», «ПЛАН» и помесячный план; владелец, 23.10.2026: «бюджет достройки
# из вкладки cf_1_new», «загрузить финкнигу я не могу — он не распознаёт лист
# РСС, а его там и нет»). Листы — явным списком; нет ни одного — отказ
# называет оба.
FINANCE_BOOK_SHEET = "Расчет стоимости строительства"
FINANCE_MODEL_SHEET = "cf_1_new"
FINANCE_SHEETS = (FINANCE_BOOK_SHEET, FINANCE_MODEL_SHEET)
# Лист финмодели: коды статей в колонке C, названия в D, суммы в тысячах
# рублей; резерв — строка «2.2.11 Резервы».
_FM_CODE_COL, _FM_NAME_COL = 3, 4
_FM_THOUSANDS = 1000.0
_FM_RESERVE_CODE = "2.2.11"
# Раздел «Налоги» финмодели — почти целиком налог на прибыль, платится из
# продаж после раскрытия эскроу; это не затрата на стройку, и в утверждённый
# бюджет он не входит (решение владельца, 02.11.2026: «Налоги то зачем в
# бюджет включать»). Код — явный, имя строки сверяется.
_FM_TAX_CODE = "2.4.5"
# Раздел финмодели → глава сметы банка. Административные расходы (2.4) в
# смете банка своей главы не имеют.
_FM_SECTION_CHAPTER = {"2.1": "1", "2.2": "2", "2.3": "3"}
# Проценты по кредитам и займам финмодели («Выплаты %% по кредитам и
# займам») — вне бюджета, справкой. Код — явный: в имени строки слова
# «процент» может не быть.
_FM_INTEREST_CODE = "3.1.4"
# Статьи финмодели, чьи строки карты «статьи_БДДС» ведут в разные главы, а
# глава решена владельцем явно, а не большинством строк. 2.3.4 «Расходы на
# продажу»: пять строк карты ведут в 2.6, четыре — в 3.2/3.4, но деньги —
# комиссии риэлторов и брокеров, и это глава 3 (решение владельца, 03.11.2026).
_FM_CHAPTER_DECIDED = {"2.3.4": "3"}
# Комиссия банка за выдачу кредита сидит в финмодели внутри строки процентов
# (3.1.4), а в смете банка — статьёй 3.5 главы 3. Это не проценты, и в
# утверждённый бюджет она входит, по карте — в главу 3 (решение владельца,
# 02.11.2026). Код — явный, имя строки сверяется.
_FM_COMMISSION_CODE = "3.1.4.1.3"


def _fm_in_budget(code: str) -> bool:
    """Строка листа входит в утверждённый бюджет: расходы «2.…» и комиссия банка."""
    return code.startswith("2.") or code == _FM_COMMISSION_CODE


def _fm_names_interest(name: str) -> bool:
    low = name.lower()
    return "процент" in low or "%" in low


def _fm_section(code: str) -> str:
    """Раздел бюджета строки: «2.2» для «2.2.1.3»; комиссия банка — своей строкой."""
    return ".".join(code.split(".")[:2]) if code.startswith("2.") else code


def _fm_is_tax(code: str) -> bool:
    return code == _FM_TAX_CODE or code.startswith(_FM_TAX_CODE + ".")
# Сколько финмодель берёт у банка: строка выборки проектного финансирования.
# Остальные расходы модель закрывает продажами после раскрытия эскроу и
# своими деньгами, и у банка на них лимит не просят (владелец, 24.10.2026:
# «по финмодели посчитали, сколько надо денег, вычитаем всё, что может дать
# банк, — это и есть потребность в допфинансировании»).
_FM_CREDIT_LABEL = "Поступления кредитов (ПФ)"
# Разделы финмодели, которые банк финансирует по главам сметы (владелец,
# 24.10.2026: «сколько надо ещё денег в банке взять, чтобы достроить и продать
# (2–3 главы)»; «тогда по модели»). Явная карта: раздел → глава, подпись.
# АХР и налоги (2.4) банк не финансирует, земля (2.1) — глава 1, в вопрос
# владельца не входит.
# Подпись — именительный и винительный падеж («на стройку», «на коммерцию»).
_FM_SECTIONS = {"2.2": ("2", "стройка", "стройку"), "2.3": ("3", "коммерция", "коммерцию")}
# «Остаток к выполнению на 01.04.27» финкниги — для финмодели потребность с
# этого же месяца.
_TAIL_FROM = datetime.date(2027, 4, 1)


def finance_sheets_reason() -> str:
    return ("в книге нет ни листа «Расчет стоимости строительства» (финкнига), "
            "ни листа «cf_1_new» (финмодель)")


def _read_finance_baseline(path: Path) -> dict[str, Any]:
    from openpyxl import load_workbook

    wb = load_workbook(path, read_only=True, data_only=True)
    try:
        if FINANCE_BOOK_SHEET in wb.sheetnames:
            return _read_finance_book(wb, path)
        if FINANCE_MODEL_SHEET in wb.sheetnames:
            return _read_finance_model(wb, path)
        return {"known": False, "reason": finance_sheets_reason()}
    finally:
        wb.close()


def _budget_composition(rows: list[dict[str, Any]], money: Any, total_col: int,
                        fact_col: int, plan_col: int,
                        month_columns: list[tuple[int, datetime.date]] | None = None,
                        interest: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """Из чего состоит «Утверждённый бюджет» финмодели — по разделам листа.

    Владелец (02.11.2026) не понимал, откуда берётся утверждённый бюджет:
    плитка показывала только главы сметы по карте «статьи_БДДС». Бюджет —
    сумма «ИТОГО» листовых строк «2.…» без раздела «Налоги» (`_FM_TAX_CODE`),
    поэтому разделы второго уровня («2.1», «2.2», …) складываются в него без
    остатка. Налоги и проценты по кредиту (строки «3.…» с процентами) — в
    справке рядом, в сумму не входят.
    """
    leaves = [meta for meta in rows if not meta["has_children"]]
    counted = [meta for meta in leaves if not _fm_is_tax(meta["code"])]
    months = month_columns or []

    def sums(code: str, pool: list[dict[str, Any]]) -> dict[str, Any]:
        under = [meta for meta in pool
                 if meta["code"] == code or meta["code"].startswith(code + ".")]
        return {"total": sum(money(m["row"], total_col) for m in under),
                "fact": sum(money(m["row"], fact_col) for m in under),
                "plan": sum(money(m["row"], plan_col) for m in under),
                "monthly": {month.isoformat(): sum(max(0.0, money(m["row"], c)) for m in under)
                            for c, month in months}}

    # Раздел — первые два уровня номера листовой строки; строка без своей
    # строки раздела в книге всё равно попадает в раздел, а не теряется.
    names = {meta["code"]: meta["name"] for meta in rows if meta["depth"] == 2}
    names.update({meta["code"]: meta["name"] for meta in counted
                  if not meta["code"].startswith("2.")})
    codes = sorted({_fm_section(meta["code"]) for meta in counted},
                   key=lambda code: [int(part) if part.isdigit() else 0
                                     for part in code.split(".")])
    sections = [{"code": code, "name": names.get(code, ""),
                 "chapter": _FM_SECTION_CHAPTER.get(code, ""), **sums(code, counted)}
                for code in codes]
    tax_row = next((meta for meta in rows if meta["code"] == _FM_TAX_CODE), None)
    taxes = ([{"code": _FM_TAX_CODE, "name": tax_row["name"],
               "named_as_tax": "налог" in tax_row["name"].lower(),
               **{k: v for k, v in sums(_FM_TAX_CODE, leaves).items() if k != "monthly"}}]
             if tax_row else [])
    interest_inside = [meta["code"] for meta in counted if _fm_names_interest(meta["name"])]
    total = sum(item["total"] for item in sections)
    fact = sum(item["fact"] for item in sections)
    plan = sum(item["plan"] for item in sections)
    return {"sections": sections, "taxes": taxes, "interest_rows": interest_inside,
            "interest_outside": list(interest or []),
            "total": total, "fact": fact, "plan": plan,
            # «ИТОГО = ФАКТ + ПЛАН» у финмодели по построению; расхождение
            # называется, а не прячется.
            "difference": total - fact - plan}


def budget_hint_lines(funding: dict[str, Any], money: Any) -> list[str]:
    """Подсказка «i» к плитке «Утверждённый бюджет» — состав, сверка, источник.

    Одна для сводки и Монитора; деньги пишет `money`.
    """
    comp = funding.get("budget_composition") or {}
    out: list[str] = []
    if comp.get("sections"):
        parts = [(f"{item['code']} «{item['name']}»" if item.get("name")
                  else f"раздел {item['code']}") + f" — {money(item['total'])}"
                 for item in comp["sections"]]
        commission = any(item["code"] == _FM_COMMISSION_CODE for item in comp["sections"])
        out.append("Утверждённый бюджет — сумма строк «ИТОГО» листа «cf_1_new» финмодели без "
                   "налогов" + (" плюс комиссия банка" if commission else "")
                   + f", {money(comp['total'])}. По разделам: " + "; ".join(parts) + ".")
        aside = [f"налоги («{tax['name']}», {tax['code']}) — {money(tax['total'])}"
                 for tax in comp.get("taxes") or []]
        aside += [f"проценты по кредиту («{row['name']}», {row['code']}"
                  + (", без комиссии банка" if row.get("commission_excluded") else "")
                  + f") — {money(row['total'])}"
                  for row in comp.get("interest_outside") or []]
        if aside:
            out.append("Справочно: " + " и ".join(aside) + " в бюджет не входят. Налоги — это "
                       "в основном налог на прибыль, его платят из продаж; проценты — плата "
                       "банку за кредит, а не затраты на стройку.")
        if comp.get("interest_rows"):
            out.append("Внимание: внутри бюджета есть строки с процентами — "
                       + ", ".join(comp["interest_rows"]) + "; они в сумму вошли.")
        if any(not tax.get("named_as_tax", True) for tax in comp.get("taxes") or []):
            out.append(f"Строка {_FM_TAX_CODE} исключена из бюджета как налоги, но в книге она "
                       "называется иначе — проверьте финмодель.")
        line = (f"Из бюджета уже оплачено по финмодели (ФАКТ) {money(comp['fact'])}, осталось "
                f"оплатить (ПЛАН) {money(comp['plan'])}; вместе — {money(comp['fact'] + comp['plan'])}.")
        if abs(comp.get("difference") or 0.0) > 0.5:
            line += (f" С бюджетом это расходится на {money(comp['difference'])}: в книге "
                     "«ИТОГО» не равно «ФАКТ» плюс «ПЛАН».")
        out.append(line)
    source = funding.get("baseline_file") or {}
    day = monitor._day(str(source.get("uploaded_at") or "")[:10]) if source.get("uploaded_at") else None
    when = day.strftime("%d.%m.%Y") if day else ""
    if source.get("file_name") and when:
        out.append(f"Источник: файл «{source['file_name']}», загружен {when}.")
    elif when:
        out.append(f"Источник: финансовая база загружена {when}; исходное имя файла при "
                   "загрузке не передано.")
    else:
        out.append("Имя исходного файла и дата загрузки для этой финансовой базы не "
                   "сохранились: она загружена до того, как их стали записывать. Загрузите "
                   "книгу заново, и источник появится здесь.")
    return out


def _read_finance_model(wb: Any, path: Path) -> dict[str, Any]:
    """Финмодель как финансовый baseline: лист «cf_1_new» + карта «статьи_БДДС».

    Утверждённый бюджет — «ИТОГО», оплачено — «ФАКТ», средства на завершение —
    «ПЛАН», помесячная потребность — колонки плана. Статьи финмодели несут
    коды БДДС (2.2.2.3 «Подземная часть»), а лимиты, оплаты и плитки сводки
    живут по главам сметы РСС, поэтому глава статьи берётся из карты
    «статьи_БДДС» той же книги: по строкам карты под статьёй (2.2.2.3.x → код
    РСС → глава). Статья, чьи строки ведут в разные главы (2.3.4 «Расходы на
    продажу» — 3.2, 3.4 и 2.6), идёт в главу большинства строк, и это
    названо в причине; статья без строк в карте — тоже.
    """
    from collections import Counter

    ws = _Grid(wb[FINANCE_MODEL_SHEET])
    header = None
    for r, values in enumerate(ws.iter_rows(values_only=True), 1):
        labels = {_norm(v): c for c, v in enumerate(values, 1) if _norm(v)}
        if {"итого", "факт", "план"} <= set(labels):
            header = (r, labels["итого"], labels["факт"], labels["план"])
            break
    if header is None:
        return {"known": False,
                "reason": "в листе «cf_1_new» не найдена шапка «ИТОГО | ФАКТ | ПЛАН»"}
    header_row, total_col, fact_col, plan_col = header
    kind_row = header_row - 1
    month_columns: list[tuple[int, datetime.date]] = []
    for c in range(plan_col + 1, ws.max_column + 1):
        if _norm(ws.cell(kind_row, c).value) != "план":
            continue
        month, _, _ = _month_value(ws.cell(header_row, c).value, 0, 0)
        if month:
            month_columns.append((c, month))

    try:
        crosswalk = actuals.read_article_crosswalk(path)["rows"]
    except KeyError:
        return {"known": False,
                "reason": "в финмодели нет листа «статьи_БДДС» — статьи листа «cf_1_new» "
                          "нельзя разложить по главам сметы РСС"}

    rows: list[dict[str, Any]] = []
    stack: list[dict[str, Any]] = []
    interest: list[dict[str, Any]] = []
    credit_plan = None
    for r in range(header_row + 1, ws.max_row + 1):
        if _norm(ws.cell(r, _FM_NAME_COL).value) == _norm(_FM_CREDIT_LABEL) and credit_plan is None:
            credit_plan = {
                "label": _FM_CREDIT_LABEL,
                "total": actuals._money(ws.cell(r, total_col).value) * _FM_THOUSANDS,
                "drawn": actuals._money(ws.cell(r, fact_col).value) * _FM_THOUSANDS,
                "plan": actuals._money(ws.cell(r, plan_col).value) * _FM_THOUSANDS,
                "monthly": {month.isoformat(): max(0.0, actuals._money(ws.cell(r, c).value)
                                                  * _FM_THOUSANDS)
                            for c, month in month_columns},
            }
        code = actuals._code(ws.cell(r, _FM_CODE_COL).value)
        name = str(ws.cell(r, _FM_NAME_COL).value or "").strip()
        if code == _FM_INTEREST_CODE and not interest:
            interest.append({"code": code, "name": name,
                             "total": actuals._money(ws.cell(r, total_col).value) * _FM_THOUSANDS})
        if code == _FM_COMMISSION_CODE and interest:
            # Комиссия уходит в бюджет — из справки о процентах её вычитаем.
            interest[0]["total"] -= actuals._money(ws.cell(r, total_col).value) * _FM_THOUSANDS
            interest[0]["commission_excluded"] = True
        if not code or not _fm_in_budget(code):
            continue
        depth = code.count(".") + 1
        # Родитель — строка, чей код — начало этого кода, а не просто строка
        # выше и мельче: комиссия банка (3.1.4.1.3) стоит после строк «2.…» и
        # иначе стала бы «дочерней» у чужой статьи.
        while stack and not code.startswith(stack[-1]["code"] + "."):
            stack.pop()
        row = {"row": r, "code": code, "depth": depth, "has_children": False,
               "name": str(ws.cell(r, _FM_NAME_COL).value or "").strip()}
        if stack:
            stack[-1]["has_children"] = True
        rows.append(row)
        stack.append(row)
    if not rows:
        return {"known": False,
                "reason": "в листе «cf_1_new» нет строк расходов с кодами «2.…» в колонке C"}

    def money(r: int, c: int) -> float:
        return actuals._money(ws.cell(r, c).value) * _FM_THOUSANDS

    def chapter_of(code: str) -> tuple[str, bool]:
        """Глава статьи по карте и признак «строки карты ведут в разные главы»."""
        votes = Counter(
            item["estimate_code"].split(".")[0]
            for item in crosswalk
            if item["estimate_code"]
            and (item["bdds_code"] == code or item["bdds_code"].startswith(code + ".")))
        if code in _FM_CHAPTER_DECIDED:
            return _FM_CHAPTER_DECIDED[code], False
        if not votes:
            return "", False
        best = max(sorted(votes), key=lambda chapter: votes[chapter])
        return best, len(votes) > 1

    approved = completion_need = paid_at_baseline = 0.0
    approved_by_chapter: dict[str, float] = {}
    monthly_total: dict[str, float] = {}
    articles: dict[str, dict[str, Any]] = {}
    reserve = 0.0
    reserve_parts: dict[str, float] = {}
    reserve_names: dict[str, str] = {}
    mixed: list[str] = []
    unmapped: list[str] = []
    sections: dict[str, dict[str, Any]] = {}
    chapter_flow: dict[str, dict[str, Any]] = {}
    for meta in rows:
        if meta["code"] in _FM_SECTIONS:
            chapter, label, label_acc = _FM_SECTIONS[meta["code"]]
            r = meta["row"]
            sections[chapter] = {
                "code": meta["code"], "chapter": chapter, "label": label, "label_acc": label_acc,
                "name": meta["name"],
                "total": money(r, total_col), "paid": money(r, fact_col), "plan": money(r, plan_col),
                "monthly": {month.isoformat(): max(0.0, money(r, c)) for c, month in month_columns},
            }
        if meta["has_children"] or _fm_is_tax(meta["code"]):
            continue
        r, code = meta["row"], meta["code"]
        total, paid, need = money(r, total_col), money(r, fact_col), money(r, plan_col)
        chapter, is_mixed = chapter_of(code)
        if is_mixed:
            mixed.append(code)
        if not chapter:
            unmapped.append(code)
        approved += total
        completion_need += need
        paid_at_baseline += paid
        if chapter:
            approved_by_chapter[chapter] = approved_by_chapter.get(chapter, 0.0) + total
        # Деньги финмодели по главам сметы — по карте «статьи_БДДС», а не по
        # разделам: административные расходы (2.4) и часть коммерции лежат в
        # смете в главе 2 (владелец, 02.11.2026: «Административные расходы
        # сидят скорее всего в главе 2-3 тоже, 2.6 статья например»).
        flow = chapter_flow.setdefault(chapter, {"total": 0.0, "fact": 0.0, "plan": 0.0,
                                                 "monthly": {}, "sections": {}})
        flow["total"] += total
        flow["fact"] += paid
        flow["plan"] += need
        section_code = _fm_section(code)
        flow["sections"][section_code] = flow["sections"].get(section_code, 0.0) + total
        for c, month in month_columns:
            key = month.isoformat()
            flow["monthly"][key] = flow["monthly"].get(key, 0.0) + max(0.0, money(r, c))
        if code == _FM_RESERVE_CODE:
            reserve += max(0.0, need)
            reserve_parts[code] = max(0.0, need)
            reserve_names[code] = meta["name"]
            continue
        month_need = {month.isoformat(): max(0.0, money(r, c)) for c, month in month_columns}
        for month, amount in month_need.items():
            monthly_total[month] = monthly_total.get(month, 0.0) + amount
        if not any(month_need.values()) and total <= 0 and paid <= 0:
            continue
        articles[code] = {
            "code": code,
            "chapter": chapter,
            "name": meta["name"],
            # Лимит статьи — её бюджет по финмодели: отдельной сметной колонки
            # у финмодели нет, и ИТОГО = ФАКТ + ПЛАН по построению.
            "rss_limit": total,
            "paid_at_baseline": paid,
            "has_programme": any(month_need.values()),
            "monthly_need": month_need,
        }
    chapters = tuple(c for c in CHAPTERS if c in approved_by_chapter)
    composition = _budget_composition(rows, money, total_col, fact_col, plan_col,
                                      month_columns, interest)
    reasons = []
    if mixed:
        reasons.append("статьи " + ", ".join(mixed)
                       + " ведут по карте «статьи_БДДС» в разные главы и отнесены "
                         "к главе большинства строк")
    if unmapped:
        reasons.append("статьи " + ", ".join(unmapped)
                       + " в карте «статьи_БДДС» не найдены и в главы не вошли")
    return {
        "known": True,
        "kind": "finmodel",
        "source": path.name,
        "approved": approved,
        "completion_need_at_baseline": completion_need,
        "paid_at_baseline": paid_at_baseline,
        "reserve": reserve,
        "reserve_parts": reserve_parts,
        "reserve_names": reserve_names,
        "approved_by_chapter": approved_by_chapter,
        "monthly_need": monthly_total,
        "tail_after_apr": sum(v for m, v in monthly_total.items()
                              if monitor._day(m) and monitor._day(m) >= _TAIL_FROM),
        "articles": articles,
        "chapters": list(chapters),
        "chapters_reason": "; ".join(reasons),
        "credit_plan": credit_plan,
        "sections": sections,
        # Дата книги — первый месяц плана: с него «ПЛАН», до него «ФАКТ».
        "plan_from": min((month for _, month in month_columns), default=None),
        "chapter_flow": chapter_flow,
        "budget_composition": composition,
    }


def _read_finance_book(wb: Any, path: Path) -> dict[str, Any]:
    """Финкнига банка: лист «Расчет стоимости строительства»."""
    ws = _Grid(wb[FINANCE_BOOK_SHEET])
    approved_hdr = _find_header(ws, "Утвержденная фин.модель проекта")
    need_hdr = _find_header(ws, "Средства на завершение строительства") or _find_header(
        ws, "Средства на завершение согласно бюджету"
    )
    paid_hdr = _find_header(ws, "Оплачено по состояни")
    programme_hdr = _find_header(ws, "производств")
    tail_hdr = _find_header(ws, "Остаток к выполнению на 01.04.27")
    rss_limit_hdr = _find_header(ws, "Общая сметная стоимость")
    if not approved_hdr or not need_hdr:
        return {"known": False, "reason": "не найдены колонки утвержденной модели/остатка"}

    approved_col = approved_hdr[1]
    need_col = need_hdr[1]
    paid_col = paid_hdr[1] if paid_hdr else 8
    rss_limit_col = rss_limit_hdr[1] if rss_limit_hdr else 4
    programme_col = programme_hdr[1] if programme_hdr else 10
    tail_col = tail_hdr[1] if tail_hdr else 20

    total_row = None
    reserve_rows: list[int] = []
    source_rows: list[dict[str, Any]] = []
    stack: list[dict[str, Any]] = []
    for r, values in enumerate(ws.iter_rows(values_only=True), 1):
        code = _book_code(values[0] if values else None)
        article = _norm(values[1] if len(values) > 1 else None)
        if total_row is None and "всего инвестиционные расходы глава 2, 3" in article:
            total_row = r
        if code in _RESERVE_CODES:
            reserve_rows.append(r)
        if not code:
            continue
        depth = code.count(".") + 1
        while stack and stack[-1]["depth"] >= depth:
            stack.pop()
        row = {
            "row": r,
            "code": code,
            "depth": depth,
            "parent": stack[-1] if stack else None,
            "has_children": False,
        }
        if stack:
            stack[-1]["has_children"] = True
        source_rows.append(row)
        stack.append(row)

    if total_row is None:
        return {"known": False, "reason": "не найдена итоговая строка глав 2+3"}

    # Глава 1 РСС тоже деньги стройки (владелец, 21.10.2026: «она тоже
    # должна учитываться, в мониторе просто упор был на 2–3 главы»). Итог
    # книги — «глава 2, 3», и глава 1 прибавляется своей строкой «1». Нет
    # такой строки — главы остаются 2–3 и для РСС тоже: оплаченное по
    # главе 1 против бюджета без неё дало бы ложный дефицит.
    #
    # Строкой главы считаются её верхние строки: «1», а без неё — «1.1»,
    # «1.2»…, у которых нет старшей строки главы 1 в книге. Нет ни одной —
    # причина уходит на экран и в сводку, а не подпись «2–3» молча.
    chapter_one_codes = {meta["code"] for meta in source_rows
                         if meta["code"] == "1" or meta["code"].startswith("1.")}
    chapter_one = [meta["row"] for meta in source_rows
                   if meta["code"] in chapter_one_codes
                   and not any(meta["code"].startswith(other + ".")
                               for other in chapter_one_codes)]
    total_rows = [total_row] + chapter_one
    chapters = CHAPTERS if chapter_one else ("2", "3")
    chapters_reason = "" if chapter_one else (
        "без главы 1: в финансовой книге (лист «Расчет стоимости строительства») "
        "нет строки главы 1")

    def total(col: int) -> float:
        return sum(actuals._money(ws.cell(r, col).value) for r in total_rows)

    approved = total(approved_col)
    # Утверждённый бюджет по главам — для плиток сводки (владелец,
    # 22.10.2026: «лучше писать из них по 2 главе и по 3 главе столько-то»).
    # Глава 1 — её верхние строки, главы 2 и 3 — строки с кодом «2» и «3».
    approved_by_chapter: dict[str, float] = {}
    if chapter_one:
        approved_by_chapter["1"] = sum(actuals._money(ws.cell(r, approved_col).value)
                                       for r in chapter_one)
    for meta in source_rows:
        if meta["code"] in ("2", "3"):
            approved_by_chapter[meta["code"]] = actuals._money(
                ws.cell(meta["row"], approved_col).value)
    completion_need = total(need_col)
    paid_at_baseline = total(paid_col)
    tail_after_apr = total(tail_col)

    reserve = 0.0
    reserve_parts: dict[str, float] = {}
    reserve_names: dict[str, str] = {}
    # Резерв ищется по трём колонкам по убыванию доверия: «на завершение
    # согласно бюджету», «согласно лимитам», «Общая сметная стоимость
    # Увеличенная». Первоначальная смета — последней: на Кутузове бюджетная
    # колонка резервов пуста, и запасной ход на «первоначальную» терял
    # 2.8 целиком и показывал 209,7 млн вместо 306,1.
    limits_hdr = _find_header(ws, "Средства на завершение согласно лимитам")
    increased_hdr = _find_header(ws, "Увеличенная")
    for r in reserve_rows:
        code = actuals._code(ws.cell(r, 1).value)
        amount = 0.0
        for col in (need_col,
                    limits_hdr[1] if limits_hdr else None,
                    increased_hdr[1] if increased_hdr else None,
                    rss_limit_col):
            if col is None:
                continue
            amount = actuals._money(ws.cell(r, col).value)
            if amount > 0:
                break
        reserve += max(0.0, amount)
        reserve_parts[code] = max(0.0, amount)
        reserve_names[code] = str(ws.cell(r, 2).value or "").strip()

    month_row = (programme_hdr[0] + 1) if programme_hdr else 9
    month_columns: list[tuple[int, datetime.date]] = []
    year = 2026
    previous_month = 0
    for c in range(programme_col, min(ws.max_column, programme_col + 18) + 1):
        month, year, previous_month = _month_value(
            ws.cell(month_row, c).value, year, previous_month
        )
        if month:
            month_columns.append((c, month))

    monthly_total: dict[str, float] = {}
    for c, month in month_columns:
        monthly_total[month.isoformat()] = total(c)

    # Only terminal rows are financing buckets. Parent rows (2.2, 2.2.2,
    # 2.3...) repeat the same programme and would double-count need.
    #
    # Статьи берутся по ОБЕИМ главам итоговой строки и независимо от того,
    # стоит ли у статьи производственная программа. Прежде сюда попадала
    # только глава 2 и только статьи с программой — а «Средства на
    # завершение», утверждённая модель и оплаченное считались по главам
    # 2–3. «Есть: остаток лимитов + резерв» выходило 1,46 млрд ₽ против
    # 1,66 у колонки банка, и 200 млн разницы были главой 3 и статьями без
    # программы, а не чьим-то счётом (владелец, 01.09.2026: «Это точно 2
    # глава? Или в разделе РСС 2, а в дефиците 2 и 3?»). У статьи без
    # программы потребность нулевая, а лимит — настоящий: это источник.
    articles: dict[str, dict[str, Any]] = {}
    for meta in source_rows:
        code = meta["code"]
        chapter = code.split(".")[0]
        if meta["has_children"] or chapter not in chapters or code in _RESERVE_CODES:
            continue
        r = meta["row"]
        month_need = {
            month.isoformat(): max(0.0, actuals._money(ws.cell(r, c).value))
            for c, month in month_columns
        }
        limit = actuals._money(ws.cell(r, rss_limit_col).value)
        paid_here = actuals._money(ws.cell(r, paid_col).value)
        if not any(month_need.values()) and limit <= 0 and paid_here <= 0:
            continue
        item = articles.setdefault(code, {
            "code": code,
            "chapter": chapter,
            "name": str(ws.cell(r, 2).value or "").strip(),
            "rss_limit": 0.0,
            "paid_at_baseline": 0.0,
            "has_programme": False,
            "monthly_need": {month.isoformat(): 0.0 for _, month in month_columns},
        })
        item["rss_limit"] += limit
        item["paid_at_baseline"] += paid_here
        item["has_programme"] = item["has_programme"] or any(month_need.values())
        for month, amount in month_need.items():
            item["monthly_need"][month] = item["monthly_need"].get(month, 0.0) + amount

    return {
        "known": True,
        "source": path.name,
        "approved": approved,
        "completion_need_at_baseline": completion_need,
        "paid_at_baseline": paid_at_baseline,
        "reserve": reserve,
        "reserve_parts": reserve_parts,
        "reserve_names": reserve_names,
        "approved_by_chapter": approved_by_chapter,
        "monthly_need": monthly_total,
        "tail_after_apr": tail_after_apr,
        "articles": articles,
        "chapters": list(chapters),
        "chapters_reason": chapters_reason,
    }


# Главы РСС, которые считаются деньгами стройки, — если финансовая книга
# несёт и главу 1 (`_read_finance_baseline`). Одно место для всех читателей.
CHAPTERS = ("1", "2", "3")


def _book_code(value: Any) -> str:
    """Код строки финкниги: число 1 или 1.0 в ячейке — тот же код «1»."""
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    return actuals._code(value)


def chapters_label(chapters: Any) -> str:
    """«1–3» или «2–3» — для подписей на экране и в сводке."""
    got = sorted(str(c) for c in (chapters or ("2", "3")))
    return f"{got[0]}–{got[-1]}" if len(got) > 1 else got[0]


def _rss_ch23(estimate: dict[str, Any], chapters: Any = ("2", "3")) -> dict[str, float]:
    rows = estimate.get("by_code") or {}
    return {
        "limit": sum(float((rows.get(code) or {}).get("estimate") or 0.0) for code in chapters),
        "by_chapter": {str(code): float((rows.get(code) or {}).get("estimate") or 0.0)
                       for code in chapters},
        "paid_bank_sheet": sum(float((rows.get(code) or {}).get("paid") or 0.0) for code in chapters),
        "contracted": sum(float((rows.get(code) or {}).get("contracted") or 0.0) for code in chapters),
    }


def payment_in_chapters(estimate: dict[str, Any], chapters: Any):
    """Признак «платёж РСС относится к этим главам» — один для Монитора и сводки."""
    parents = {row["code"]: row.get("parent") for row in estimate.get("rows") or []}
    wanted = {str(c) for c in chapters}

    def root(code: str) -> str:
        seen = set()
        while code and code not in seen:
            seen.add(code)
            parent = str(parents.get(code) or "")
            if not parent:
                return code.split(".")[0]
            code = parent
        return code.split(".")[0] if code else ""

    return lambda row: root(str(row.get("estimate_code") or "").rstrip(".")) in wanted


def _paid_in_chapters(rss: Path, estimate: dict[str, Any],
                      chapters: Any = ("2", "3")) -> dict[str, float]:
    """Оплачено по главам: всего и та часть, что заплачена кредитом."""
    keep = payment_in_chapters(estimate, chapters)
    rows = [row for row in actuals.read_payments(rss).get("rows") or [] if keep(row)]
    return {"total": sum(float(row.get("amount") or 0.0) for row in rows),
            "borrowed": sum(float(row.get("amount") or 0.0) for row in rows
                            if actuals.borrowed(row.get("source")))}


def _payment_by_code(rss: Path) -> dict[str, float]:
    result: dict[str, float] = {}
    for row in actuals.read_payments(rss).get("rows") or []:
        code = actuals._code(row.get("estimate_code"))
        if not code:
            continue
        result[code] = result.get(code, 0.0) + float(row.get("amount") or 0.0)
    return result


def _interpolated_crossing(
    month: datetime.date, month_amount: float, before: float, threshold: float
) -> datetime.date:
    if month_amount <= 0:
        return month
    ratio = max(0.0, min(1.0, (threshold - before) / month_amount))
    nxt = (
        datetime.date(month.year + 1, 1, 1)
        if month.month == 12
        else datetime.date(month.year, month.month + 1, 1)
    )
    days = max(1, (nxt - month).days)
    return month + datetime.timedelta(days=max(0, min(days - 1, round(ratio * days))))


def _article_waterfall(
    articles: dict[str, dict[str, Any]],
    reserve: float,
    cut: datetime.date,
    current_paid: dict[str, float] | None = None,
) -> dict[str, Any]:
    """Monthly article-limit -> reserve -> uncovered waterfall."""
    current_paid = current_paid or {}
    cut_month = cut.replace(day=1)
    months = sorted({
        monitor._day(month)
        for item in articles.values()
        for month in (item.get("monthly_need") or {})
        if monitor._day(month) is not None and monitor._day(month) >= cut_month
    })
    months = [month for month in months if month is not None]

    state: dict[str, float] = {}
    opening_raw: dict[str, float] = {}
    for code, item in articles.items():
        paid = current_paid.get(code)
        if paid is None:
            paid = float(item.get("paid_at_baseline") or 0.0)
        raw = float(item.get("rss_limit") or 0.0) - float(paid or 0.0)
        opening_raw[code] = raw
        state[code] = max(0.0, raw)

    reserve_balance = max(0.0, float(reserve or 0.0))
    reserve_start = None
    reserve_exhaustion = None
    cumulative_reserve_need = 0.0
    cumulative_unfunded = 0.0
    monthly_need: dict[str, float] = {}
    monthly_reserve_draw: dict[str, float] = {}
    monthly_unfunded: dict[str, float] = {}
    monthly_reserve_balance: dict[str, float] = {}
    article_rows: list[dict[str, Any]] = []

    first_shortfall: dict[str, datetime.date] = {}
    article_reserve_take: dict[str, float] = {}
    article_unfunded: dict[str, float] = {}
    article_own_take: dict[str, float] = {}
    article_need: dict[str, float] = {}
    first_unfunded: dict[str, datetime.date] = {}
    for month in months:
        month_key = month.isoformat()
        month_need_total = 0.0
        month_shortfall = 0.0
        month_shortages: dict[str, float] = {}
        for code, item in articles.items():
            need = max(0.0, float((item.get("monthly_need") or {}).get(month_key, 0.0) or 0.0))
            month_need_total += need
            available = state.get(code, 0.0)
            own_funding = min(available, need)
            shortage = max(0.0, need - own_funding)
            article_own_take[code] = article_own_take.get(code, 0.0) + own_funding
            article_need[code] = article_need.get(code, 0.0) + need
            state[code] = max(0.0, available - need)
            month_shortfall += shortage
            if shortage > 0:
                month_shortages[code] = shortage
                if code not in first_shortfall:
                    first_shortfall[code] = month

        monthly_need[month_key] = month_need_total
        before_need = cumulative_reserve_need
        cumulative_reserve_need += month_shortfall
        if month_shortfall > 0 and reserve_start is None:
            reserve_start = month

        draw = min(reserve_balance, month_shortfall)
        uncovered = max(0.0, month_shortfall - draw)
        reserve_balance -= draw
        cumulative_unfunded += uncovered
        monthly_reserve_draw[month_key] = draw
        monthly_unfunded[month_key] = uncovered
        monthly_reserve_balance[month_key] = reserve_balance

        # В месяц, когда резерва на всех не хватает, покрытая доля у всех
        # статей одна: резерв — общий, отдельной очереди статей внутри
        # месяца в ДДС нет.
        covered_share = draw / month_shortfall if month_shortfall > 0 else 0.0
        for code, shortage in month_shortages.items():
            covered = shortage * covered_share
            article_reserve_take[code] = article_reserve_take.get(code, 0.0) + covered
            article_unfunded[code] = article_unfunded.get(code, 0.0) + (shortage - covered)
            if shortage - covered > 0 and code not in first_unfunded:
                first_unfunded[code] = month

        if reserve_exhaustion is None and month_shortfall > 0 and cumulative_reserve_need > reserve:
            reserve_exhaustion = _interpolated_crossing(
                month, month_shortfall, before_need, reserve
            )

    for code, item in sorted(articles.items()):
        limit = float(item.get("rss_limit") or 0.0)
        # Потребность — те же месяцы, что и водопад: с месяца среза. Прежде
        # сюда входила вся программа, включая прошедшие месяцы, а свой лимит,
        # резерв и непокрытое считались только вперёд — и строка таблицы не
        # складывалась: 805,4 против 286,8 + 114,1 + 257,6 (владелец,
        # 02.09.2026: «Почему сумма потребности не равна сумме соседних
        # столбцов???»). Теперь по построению need_total = own_take +
        # reserve_take + unfunded_take, а прошедшее названо отдельно.
        need_total = article_need.get(code, 0.0)
        need_before_cut = sum(
            max(0.0, float(amount or 0.0))
            for month, amount in (item.get("monthly_need") or {}).items()
            if (monitor._day(month) or cut_month) < cut_month)
        first_month = first_shortfall.get(code)
        reserve_left_after_first = None
        if first_month is not None:
            reserve_left_after_first = monthly_reserve_balance.get(first_month.isoformat())
        article_rows.append({
            "code": code,
            "chapter": str(item.get("chapter") or code.split(".")[0]),
            "has_programme": bool(item.get("has_programme", need_total > 0)),
            "name": item.get("name", ""),
            "limit": limit,
            "need_total": need_total,
            "need_before_cut": need_before_cut,
            "own_take": article_own_take.get(code, 0.0),
            "opening_limit_raw": opening_raw.get(code, 0.0),
            "opening_limit": max(0.0, opening_raw.get(code, 0.0)),
            "remaining_limit": state.get(code, 0.0),
            "first_reserve_month": monitor._iso(first_shortfall.get(code)),
            "reserve_take": article_reserve_take.get(code, 0.0),
            "unfunded_take": article_unfunded.get(code, 0.0),
            "first_unfunded_month": monitor._iso(first_unfunded.get(code)),
            "reserve_left_after_first": reserve_left_after_first,
        })

    # Когда дофинансирование понадобится. Потребность без срока — половина
    # ответа: «нужно 3,6 млрд» и «нужно 3,6 млрд с марта» — разные новости
    # (владелец, 29.08.2026: «потребность в доп финансировании нужно выделить
    # по сумме и сроку»). Месяц выбирается, а не считается: это первый месяц с
    # непокрытой потребностью.
    unfunded_from = next((month for month in sorted(monthly_unfunded)
                          if monthly_unfunded[month] > 0), None)
    return {
        "opening_bank_remaining": sum(max(0.0, value) for value in opening_raw.values()),
        "opening_article_deficit": sum(max(0.0, -value) for value in opening_raw.values()),
        "additional_financing_from": unfunded_from,
        "remaining_article_limits": sum(state.values()),
        "reserve_start": reserve_start,
        "reserve_exhaustion": reserve_exhaustion,
        "reserve_balance": reserve_balance,
        "reserve_need": cumulative_reserve_need,
        "additional_financing": cumulative_unfunded,
        "additional_financing_by_chapter": _gap_by_chapter(article_rows),
        "additional_financing_note": _gap_scope_note(article_rows),
        "monthly_need": monthly_need,
        "monthly_reserve_draw": monthly_reserve_draw,
        "monthly_unfunded": monthly_unfunded,
        "monthly_reserve_balance": monthly_reserve_balance,
        "articles": article_rows,
    }


# Чем является глава сметы для посетителя: «глава 2 (стройка)».
_CHAPTER_WORDS = {"1": ("участок", "участок"),
                  **{ch: (word, acc) for ch, word, acc in _FM_SECTIONS.values()}}


def _gap_by_chapter(article_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Дофинансирование по главам — из тех же строк водопада, что и итог.

    Владелец (02.11.2026) о «нужно дофинансировать»: «А почему только? Это без
    учёта 3 главы?» — итог без разбивки не говорил, из чего он сложен. Сумма
    по главам равна итогу по построению: это те же непокрытые доли статей.
    Месяц у главы — первый месяц, когда непокрытая часть появилась у любой
    её статьи.
    """
    out: dict[str, dict[str, Any]] = {}
    for row in article_rows:
        amount = float(row.get("unfunded_take") or 0.0)
        if amount <= 0:
            continue
        chapter = str(row.get("chapter") or str(row.get("code") or "").split(".")[0])
        item = out.setdefault(chapter, {"chapter": chapter,
                                        "label": _CHAPTER_WORDS.get(chapter, ("", ""))[0],
                                        "label_acc": _CHAPTER_WORDS.get(chapter, ("", ""))[1],
                                        "amount": 0.0, "from": None})
        item["amount"] += amount
        month = row.get("first_unfunded_month")
        if month and (item["from"] is None or month < item["from"]):
            item["from"] = month
    return [out[ch] for ch in sorted(out)]


def _gap_scope_note(article_rows: list[dict[str, Any]]) -> str:
    """Что в сумму дофинансирования не входит — полной фразой.

    Водопад считает только статьи глав сметы, по которым он построен; проценты
    по кредиту в РСС не входят никогда, а участок (глава 1) — когда его
    статей в водопаде нет (финмодель: только стройка и коммерция).
    """
    chapters = {str(row.get("chapter") or str(row.get("code") or "").split(".")[0])
                for row in article_rows}
    if "1" in chapters:
        return ("В эту сумму не входят проценты по кредиту: здесь посчитаны только "
                "расходы по главам сметы.")
    return ("В эту сумму не входят покупка участка (глава 1 сметы) и проценты по "
            "кредиту: здесь посчитаны только стройка и коммерческие расходы.")


def _limit_reconciliation(waterfall: dict[str, Any], bank_limit: float,
                          bank_chapters: Any, *,
                          smeta_by_chapter: dict[str, float] | None = None,
                          paid_by_chapter: dict[str, dict[str, float]] | None = None,
                          approved_by_chapter: dict[str, float] | None = None,
                          remaining_outside: Any = ()) -> dict[str, Any]:
    """Как сходится дофинансирование и как сходятся плашки лимита.

    Владелец (02.11.2026): «У нас сейчас лимит … Надо добавить сколько на
    достройке. Просто как это сходится тогда» и, на плашках сводки, «Тут
    что-то не бьётся». Две цепочки, обе из строк водопада и оплат РСС, второй
    раз ничего не считается.

    1. Дофинансирование, по главам водопада. По каждой статье точно
       потребность = свой лимит + резерв + непокрытое, поэтому
       не хватает = осталось достроить − остаток лимита − резерв + лимит,
       что останется неизрасходованным (излишек одной статьи или главы на
       нехватку другой не переносится).
    2. Плашки. «Можно ещё выбрать у банка» = лимит − выбрано кредитом (все
       главы лимита), «осталось по смете после всех оплат» = Σ max(0, лимит −
       всё оплаченное) по главам остатка. Разница между ними раскладывается
       без остатка: главы вне остатка (их лимит минус выбранное), собственные
       деньги, уже заплаченные по главам остатка, перебор сверх сметы (в
       остатке он взят нулём) и расхождение лимитов статей с итогом сметы.
    """
    paid_by_chapter = paid_by_chapter or {}
    approved_by_chapter = approved_by_chapter or {}
    chapters: dict[str, dict[str, Any]] = {}

    def blank(chapter: str) -> dict[str, Any]:
        return {"chapter": chapter, "label": _CHAPTER_WORDS.get(chapter, ("", ""))[0],
                "budget": approved_by_chapter.get(chapter), "in_waterfall": False,
                "in_remaining": False, "limit": 0.0, "paid": 0.0, "borrowed": None,
                "overpaid": 0.0, "remaining": 0.0, "need": None, "reserve": None,
                "unused": None, "gap": None}

    for row in waterfall.get("articles") or []:
        chapter = str(row.get("chapter") or str(row.get("code") or "").split(".")[0])
        item = chapters.get(chapter)
        if item is None:
            item = chapters[chapter] = {**blank(chapter), "in_waterfall": True,
                                        "in_remaining": True, "need": 0.0, "reserve": 0.0,
                                        "unused": 0.0, "gap": 0.0}
        limit = float(row.get("limit") or 0.0)
        raw = float(row.get("opening_limit_raw") or 0.0)
        item["limit"] += limit
        item["paid"] += limit - raw
        item["overpaid"] += max(0.0, -raw)
        item["remaining"] += float(row.get("opening_limit") or 0.0)
        item["need"] += float(row.get("need_total") or 0.0)
        item["reserve"] += float(row.get("reserve_take") or 0.0)
        item["unused"] += float(row.get("remaining_limit") or 0.0)
        item["gap"] += float(row.get("unfunded_take") or 0.0)
    inside = sorted(chapters)
    if smeta_by_chapter is not None:
        for chapter in (str(ch) for ch in (bank_chapters or ())):
            if chapter in chapters:
                continue
            limit = float(smeta_by_chapter.get(chapter) or 0.0)
            paid = float((paid_by_chapter.get(chapter) or {}).get("total") or 0.0)
            chapters[chapter] = {**blank(chapter), "limit": limit, "paid": paid,
                                 "overpaid": max(0.0, paid - limit),
                                 "remaining": max(0.0, limit - paid),
                                 "in_remaining": chapter in {str(c) for c in remaining_outside}}
    for chapter, item in chapters.items():
        got = paid_by_chapter.get(chapter)
        if got is not None:
            item["borrowed"] = float(got.get("borrowed") or 0.0)
    rows = [chapters[ch] for ch in sorted(chapters)]
    flow = [chapters[ch] for ch in inside]
    total = {key: sum(row[key] for row in flow)
             for key in ("limit", "paid", "overpaid", "remaining", "need", "reserve",
                         "unused", "gap")}
    total["chapters"] = chapters_label(inside) if inside else ""
    total["plain"] = total["need"] - total["remaining"]
    outside = [str(ch) for ch in (bank_chapters or ()) if str(ch) not in inside]
    out: dict[str, Any] = {
        "chapters": rows,
        "total": total,
        "bank_limit": float(bank_limit or 0.0),
        "bank_chapters": chapters_label(bank_chapters) if bank_chapters else "",
        "outside_chapters": outside,
        "outside_limit": float(bank_limit or 0.0) - total["limit"],
        # Сходится по построению; признак — для проверки, а не для красоты.
        "matches": abs(total["plain"] - total["reserve"] + total["unused"] - total["gap"])
        <= 1e-6 * max(1.0, total["need"]),
        "tiles": None,
    }
    if paid_by_chapter and all(row["borrowed"] is not None for row in rows):
        borrowed = sum(row["borrowed"] for row in rows)
        remaining = sum(row["remaining"] for row in rows if row["in_remaining"])
        not_in_remaining = [{"chapter": row["chapter"], "label": row["label"],
                             "amount": row["limit"] - row["borrowed"]}
                            for row in rows if not row["in_remaining"]]
        own = sum(row["paid"] - row["borrowed"] for row in rows if row["in_remaining"])
        overpaid = [{"chapter": row["chapter"], "label": row["label"],
                     "amount": row["overpaid"]}
                    for row in rows if row["in_remaining"] and row["overpaid"] > 0]
        book_gap = float(bank_limit or 0.0) - sum(row["limit"] for row in rows)
        can_draw = float(bank_limit or 0.0) - borrowed
        explained = (sum(item["amount"] for item in not_in_remaining) + own
                     - sum(item["amount"] for item in overpaid) + book_gap)
        out["tiles"] = {
            "bank_limit": float(bank_limit or 0.0), "borrowed": borrowed,
            "can_draw": can_draw, "remaining": remaining,
            "remaining_chapters": chapters_label([row["chapter"] for row in rows
                                                  if row["in_remaining"]]),
            "difference": can_draw - remaining,
            "not_in_remaining": not_in_remaining, "own_money": own,
            "overpaid": overpaid, "book_gap": book_gap,
            "matches": abs(can_draw - remaining - explained)
            <= 1e-6 * max(1.0, float(bank_limit or 0.0)),
        }
    return out


def _chapter_title(row: dict[str, Any]) -> str:
    return f"глава {row['chapter']}" + (f" ({row['label']})" if row.get("label") else "")


def _own_money(comp: dict[str, Any] | None, smeta: dict[str, float],
               paid_by_chapter: dict[str, dict[str, float]], bank_chapters: Any,
               cut: datetime.date, plan_from: datetime.date | None = None,
               paid_since: dict[str, float] | None = None,
               chapter_flow: dict[str, dict[str, Any]] | None = None,
               schedule: dict[str, Any] | None = None) -> dict[str, Any] | None:
    """«Нужно своих денег сверх сметы банка» = утверждённый бюджет − лимит банка.

    Владелец (02.11.2026): «Лимит банка» в РСС — смета банка, в неё банк
    засчитывает все оплаты, и кредитом, и собственные. Поэтому на плашках
        лимит = оплачено + остаток лимита (по всем главам лимита),
        бюджет = лимит + нужно своих денег сверх сметы банка.
    Разложение без остатка — по главам сметы, а деньги финмодели разнесены по
    главам картой «статьи_БДДС» (`chapter_flow`): административные расходы и
    часть коммерции лежат в главе 2. По главе: «осталось оплатить» по
    финмодели минус остаток лимита главы; статьи вне глав — целиком; плюс
    расхождение «ФАКТ» финмодели (на дату книги) с оплаченным по реестру РСС
    (на дату отчёта) и расхождение «ИТОГО» книги с «ФАКТ» + «ПЛАН».
    Первый месяц нехватки — по водопаду глав.
    """
    if not comp or not comp.get("sections") or chapter_flow is None:
        return None
    chapters = [str(ch) for ch in (bank_chapters or ())]
    limit = sum(float(smeta.get(ch) or 0.0) for ch in chapters)
    paid = {ch: float((paid_by_chapter.get(ch) or {}).get("total") or 0.0) for ch in chapters}
    borrowed = sum(float((paid_by_chapter.get(ch) or {}).get("borrowed") or 0.0)
                   for ch in chapters)
    left = {ch: float(smeta.get(ch) or 0.0) - paid[ch] for ch in chapters}
    rows: list[dict[str, Any]] = []
    dates = book = 0.0
    articles: dict[str, dict[str, Any]] = {}
    for chapter in chapters:
        flow = chapter_flow.get(chapter) or {"total": 0.0, "fact": 0.0, "plan": 0.0,
                                             "monthly": {}, "sections": {}}
        # Дефицит главы — оплачено по реестру плюс то, что ещё предстоит
        # оплатить, минус лимит главы; для всех глав одинаково (решение
        # владельца, 03.11.2026). Предстоящее: по графику финансирования для
        # его главы, по финмодели — для остальных, за вычетом оплат по реестру
        # после даты книги (`_plan_still_owed`).
        by_schedule = schedule is not None and schedule["chapter"] == chapter
        monthly = (dict(schedule["monthly"]) if by_schedule else
                   _plan_still_owed(dict(flow["monthly"]), plan_from,
                                    (paid_since or {}).get(chapter, 0.0), cut))
        owed = sum(monthly.values())
        cost = paid[chapter] + owed
        rows.append({"chapter": chapter, "label": _CHAPTER_WORDS.get(chapter, ("", ""))[0],
                     "sections": dict(sorted(flow["sections"].items())),
                     "budget": cost, "model_budget": flow["total"],
                     "by_schedule": schedule if by_schedule else None,
                     "paid": paid[chapter], "limit": float(smeta.get(chapter) or 0.0),
                     "to_pay": owed, "left": left[chapter],
                     "amount": cost - float(smeta.get(chapter) or 0.0)})
        dates += flow["fact"] - paid[chapter]
        book += flow["total"] - flow["fact"] - flow["plan"]
        articles[chapter] = {
            "code": chapter, "chapter": chapter, "rss_limit": float(smeta.get(chapter) or 0.0),
            "paid_at_baseline": paid[chapter], "monthly_need": monthly}
    for chapter, flow in sorted(chapter_flow.items()):
        if chapter in chapters:
            continue
        rows.append({"chapter": "", "label": "", "sections": dict(sorted(flow["sections"].items())),
                     "budget": flow["total"], "limit": 0.0,
                     "to_pay": flow["plan"], "left": 0.0, "paid": flow["fact"],
                     "amount": flow["total"]})
        book += flow["total"] - flow["fact"] - flow["plan"]
        articles[f"вне глав {chapter}"] = {
            "code": f"вне глав {chapter}", "chapter": "", "rss_limit": 0.0,
            "paid_at_baseline": 0.0,
            "monthly_need": _plan_still_owed(dict(flow["monthly"]), plan_from, 0.0, cut)}
    budget = float(comp.get("total") or 0.0)
    # Чем «утверждённый бюджет − лимит» отличается от суммы глав, — названо:
    # по главе графика — на сколько финмодель закладывает больше графика; по
    # главам финмодели — расхождение учёта прошлых оплат финмодели и реестра.
    over = sum(row["model_budget"] - row["budget"] for row in rows
               if row.get("by_schedule"))
    accounting = sum(row["model_budget"] - row["budget"] for row in rows
                     if row["chapter"] and not row.get("by_schedule"))
    need = budget - limit - over - accounting
    waterfall = _article_waterfall(articles, 0.0, cut)
    explained = sum(row["amount"] for row in rows)
    return {
        "budget": budget, "limit": limit, "paid": sum(paid.values()), "borrowed": borrowed,
        "own_paid": sum(paid.values()) - borrowed,
        "left": sum(left.values()), "left_by_chapter": left,
        "need": need, "model_over_schedule": over, "accounting": accounting,
        "rows": rows, "dates": dates, "book": book,
        "from": waterfall["additional_financing_from"],
        "book_fact": float(comp.get("fact") or 0.0),
        # Из расхождения «ФАКТ» с реестром — оплаты после даты книги; остальное
        # — разница учёта прошлых оплат.
        "paid_since": sum(float((paid_since or {}).get(ch) or 0.0) for ch in chapters),
        "plan_from": plan_from.isoformat() if plan_from else None,
        "matches": abs(explained - need) <= 1e-6 * max(1.0, budget),
    }


def own_money_lines(own: dict[str, Any] | None, money: Any,
                    with_reconciliation: bool = True) -> list[str]:
    """«Нужно своих денег сверх сметы банка» словами — одна для сводки и Монитора."""
    if not own:
        return []
    out = [f"Нужно своих денег сверх сметы банка {money(own['need'])}"
           + (f", первый месяц нехватки — {_month_name(own['from'])}" if own.get("from") else "")
           + ": по каждой главе — оплачено по реестру плюс то, что осталось оплатить, минус "
           "лимит главы. Лимит банка — это смета: в неё банк засчитывает все оплаты, и "
           f"кредитом, и собственными деньгами. Оплачено с начала проекта {money(own['paid'])} "
           f"(из них кредитом {money(own['borrowed'])}, своими деньгами "
           f"{money(own['own_paid'])}), остаток лимита {money(own['left'])}."]
    parts = []
    for row in own["rows"]:
        made = " + ".join(f"{code} {money(amount)}" for code, amount in row["sections"].items())
        if row["chapter"]:
            name = f"глава {row['chapter']}" + (f" ({row['label']})" if row.get("label") else "")
            sch = row.get("by_schedule")
            if sch:
                # day у найденного внутри книги графика может быть датой загрузки.
                value = ((sch.get("source_dates") or {}).get("data_date")
                         if "source_dates" in sch else sch["day"])
                day = monitor._day(value)
                source = ("по графику финансирования от " + day.strftime("%d.%m.%Y") if day else
                          "по графику финансирования (дата данных не указана)")
            else:
                source = "по финмодели"
            parts.append(f"{name} — {money(row['amount'])}: оплачено {money(row['paid'])} плюс "
                         f"осталось оплатить {source} {money(row['to_pay'])} минус лимит главы "
                         f"{money(row['limit'])}")
        else:
            parts.append(f"статьи финмодели вне глав сметы ({made}) — {money(row['amount'])}: "
                         "в смете банка их нет, поэтому это свои деньги")
    out.append("По главам: " + "; ".join(parts) + ".")
    if with_reconciliation:
        out.extend(own_budget_reconciliation_lines(own, money))
    return out


def own_budget_reconciliation_lines(own: dict[str, Any] | None, money: Any) -> list[str]:
    """Прежняя сверка исходного бюджета и поправок, без нового расчёта денег."""
    if not own:
        return []
    out: list[str] = []
    over = float(own.get("model_over_schedule") or 0.0)
    accounting = float(own.get("accounting") or 0.0)
    gap = own["budget"] - own["limit"]
    # Арифметика словами: бюджет − лимит − (финмодель сверх графика) −
    # (расхождение учёта) = сумма по главам. Расхождение учёта меньше нуля,
    # когда реестр оплатил больше, чем записано в финмодели: тогда оно
    # прибавляется.
    steps = []
    if abs(over) > 0.5:
        steps.append(f"{'минус' if over > 0 else 'плюс'} {money(abs(over))} — на столько "
                     "финмодель по главе из графика финансирования закладывает "
                     + ("больше" if over > 0 else "меньше") + " графика")
    if abs(accounting) > 0.5:
        steps.append(f"{'плюс' if accounting < 0 else 'минус'} {money(abs(accounting))} — "
                     "на столько по прошлым оплатам "
                     + ("реестр РСС оплатил больше, чем записано в финмодели"
                        if accounting < 0 else "финмодель записала больше, чем реестр РСС"))
    if steps:
        out.append(f"Справочно, как это связано с утверждённым бюджетом: бюджет без налогов "
                   f"{money(own['budget'])} минус лимит банка {money(own['limit'])} — "
                   f"{money(gap)}; " + "; ".join(steps)
                   + f"; итого {money(own['need'])}.")
    if abs(own["book"]) > 0.5:
        out.append(f"В книге «ИТОГО» не равно «ФАКТ» плюс «ПЛАН» на {money(own['book'])}.")
    return out


def tiles_bridge_lines(rec: dict[str, Any], money: Any) -> list[str]:
    """«Лимит − выбрано» против «осталось по смете» — полными фразами."""
    tiles = (rec or {}).get("tiles")
    if not tiles:
        return []
    out = [f"Можно ещё выбрать у банка {money(tiles['can_draw'])}: это лимит "
           f"{money(tiles['bank_limit'])} минус {money(tiles['borrowed'])}, уже выбранные "
           f"кредитом. По смете после всех оплат по главам {tiles['remaining_chapters']} "
           f"осталось {money(tiles['remaining'])}: здесь вычтено всё оплаченное — и кредитом, "
           f"и собственными деньгами."]
    pieces = []
    for item in tiles["not_in_remaining"]:
        if abs(item["amount"]) > 0.5:
            pieces.append(f"{_chapter_title(item)} — {money(item['amount'])}: её лимит минус "
                          "выбранное по ней в остаток по смете не входит")
    if abs(tiles["own_money"]) > 0.5:
        pieces.append(f"собственные деньги, уже заплаченные по главам "
                      f"{tiles['remaining_chapters']}, — {money(tiles['own_money'])}")
    for item in tiles["overpaid"]:
        pieces.append(f"по {_chapter_title(item).replace('глава', 'главе', 1)} оплачено больше "
                      f"сметы на {money(item['amount'])} — в остатке такая глава стоит нулём, "
                      "поэтому этот перебор разницу уменьшает")
    if abs(tiles["book_gap"]) > 0.5:
        pieces.append(f"лимиты статей финансовой книги расходятся с итогом сметы на "
                      f"{money(tiles['book_gap'])}")
    if pieces and abs(tiles["difference"]) > 0.5:
        out.append(f"Разница {money(tiles['difference'])} складывается так: "
                   + "; ".join(pieces) + ".")
    return out


def reconciliation_lines(rec: dict[str, Any], money: Any) -> list[str]:
    """Сверка словами — одна для Монитора и сводки; деньги пишет `money`."""
    if not rec or not rec.get("chapters"):
        return []
    out: list[str] = tiles_bridge_lines(rec, money)
    total = rec["total"]
    outside = rec.get("outside_chapters") or []
    if outside and abs(rec.get("outside_limit") or 0.0) > 1e-6 * max(1.0, rec["bank_limit"]):
        names = ", ".join(_chapter_title({"chapter": ch, "label": _CHAPTER_WORDS.get(ch, ("",))[0]})
                          for ch in outside)
        out.append(f"Лимит банка по главам {rec['bank_chapters']} — {money(rec['bank_limit'])}. "
                   f"Сверка дофинансирования считает только главы {total['chapters']} — "
                   f"{money(total['limit'])}. Остальные {money(rec['outside_limit'])} "
                   f"приходятся на главы вне этой сверки: {names}. В дофинансирование "
                   "они не входят.")
    for row in rec["chapters"]:
        name = _chapter_title(row)
        name = name[:1].upper() + name[1:]
        borrowed = (f", из них кредитом {money(row['borrowed'])}"
                    if row.get("borrowed") is not None else "")
        budget = (f"бюджет {money(row['budget'])}, " if row.get("budget") is not None else "")
        text = (f"{name}: {budget}лимит {money(row['limit'])}, оплачено всего "
                f"{money(row['paid'])}{borrowed}, остаток по смете {money(row['remaining'])}")
        if row["in_waterfall"]:
            text += (f"; осталось достроить {money(row['need'])}; не хватает "
                     f"{money(row['gap'])}.")
        else:
            text += "; в расчёт дофинансирования эта глава не входит."
        if row["overpaid"] > 0:
            text += (f" Оплачено больше сметы на {money(row['overpaid'])} — этот перебор "
                     "показан здесь, а в остатке глава стоит нулём и остаток других глав "
                     "он не уменьшает.")
        if row["in_waterfall"] and row["unused"] > 0:
            text += (f" Лимита останется {money(row['unused'])}: он не переносится на "
                     "нехватку другой главы или статьи.")
        out.append(text)
    text = (f"Итого по главам {total['chapters']}: осталось достроить {money(total['need'])} "
            f"минус остаток по смете {money(total['remaining'])} — это {money(total['plain'])}.")
    if total["reserve"] > 0:
        text += f" Резерв закрывает из этого {money(total['reserve'])}."
    if total["unused"] > 0:
        text += (f" Но {money(total['unused'])} лимита останутся неизрасходованными: излишек "
                 "одной главы или статьи не покрывает нехватку другой. Поэтому "
                 f"дофинансировать нужно {money(total['gap'])}, а не меньше.")
    else:
        text += f" Дофинансировать нужно {money(total['gap'])}."
    out.append(text)
    return out


def _retention(project: str, horizon: Any) -> dict[str, Any] | None:
    """Гарантийные удержания против горизонта стройки.

    «В РСС банка сумма по договору берётся общая, но ГУ до момента погашения ПФ
    не заплатятся — по сути это скрытый резерв» (владелец, 29.08.2026). Горизонт
    — прогнозный ввод: за ним выплата ГУ стройку уже не касается.

    Реестра нет — это `None`, а не нулевой резерв: «не загружали» и «удержаний
    нет» на экране значат разное.
    """
    import developaid_monitor_retention as retention

    register = monitor.latest_retention(project)
    if not register:
        return None
    if register.get("known") is False:
        return register
    got = retention.summary(register, horizon=horizon)
    got["taken_at"] = register.get("taken_at", "")
    return got


def _programme_left(articles: dict[str, dict[str, Any]], cut: datetime.date) -> dict[str, float]:
    """Сколько статья ещё тратит по программе РСС начиная с месяца среза."""
    cut_month = cut.replace(day=1)
    left: dict[str, float] = {}
    for code, item in articles.items():
        total = 0.0
        for month, amount in (item.get("monthly_need") or {}).items():
            day = monitor._day(month)
            if day is not None and day >= cut_month:
                total += max(0.0, float(amount or 0.0))
        left[code] = total
    return left


def _unspent(project: str, rss: Path, estimate: dict[str, Any],
             horizon: Any, waterfall: dict[str, Any],
             baseline_articles: dict[str, dict[str, Any]] | None = None,
             cut: datetime.date | None = None,
             chapters: Any = ("2", "3")) -> dict[str, Any] | None:
    """Постатейно: откуда лимит можно просить и кому его не хватает.

    Реестра ГУ может не быть, реестра договоров в РСС может не быть — свободное
    от договоров считается и без них, а причина, по которой ГУ не разложены,
    называется вслух. Пусто здесь бывает только когда нечего показать вовсе.
    Потребность и нехватку считает водопад выше — сюда они приходят готовыми.
    """
    import developaid_monitor_unspent as unspent_mod

    register = monitor.latest_retention(project)
    if register and register.get("known") is False:
        register = None
    try:
        contracts = actuals.read_contracts(rss)
    except Exception:  # noqa: BLE001 — листа договоров в РСС может не быть
        contracts = None
    needy = [row for row in (waterfall.get("articles") or [])
             if float(row.get("unfunded_take") or 0.0) > 0]
    programme_left = (_programme_left(baseline_articles, cut)
                      if baseline_articles is not None and cut is not None else None)
    got = unspent_mod.unspent(estimate, contracts=contracts, retention=register,
                              horizon=horizon, needy=needy, roots=tuple(chapters),
                              programme_left=programme_left,
                              not_articles=_RESERVE_CODES)
    return got if (got["sources"] or got["excluded"] or got["needy"]
                   or got["retention"]["reason"]) else None


def _deficit_ladder(waterfall: dict[str, Any], reserve: float,
                    approved_remaining: float | None,
                    unspent: dict[str, Any] | None) -> dict[str, Any]:
    """Лестница от структурного дефицита к «не хватает на достройку».

    Структурный дефицит и «ДЕФИЦИТ» в шапке отвечают на разные вопросы, и
    складывать их нельзя — потребность модели уже включает программу РСС
    (владелец, 03.09.2026: «к нему же ещё надо добавлять дефицит с учётом
    потребности бюджета реального на достройку»). Связь такая: структурный
    (постатейно, без перебросок) → минус то, что закрывается
    перераспределением внутри глав по признаку «Откуда просить» → минус
    свободный лимит, который просить нельзя (у статьи ещё работы; шапка
    считает, что банк его отдаст) → дефицит по РСС при полном
    перераспределении → плюс превышение утверждённой модели над программой
    РСС → итого, и это то же число, что «ДЕФИЦИТ» в шапке.
    """
    rows = waterfall.get("articles") or []
    rss_need = sum(max(0.0, float(row.get("need_total") or 0.0)) for row in rows)
    fuel = float(waterfall.get("opening_bank_remaining") or 0.0) + float(reserve or 0.0)
    structural = float(waterfall.get("additional_financing") or 0.0)
    redistributable = 0.0
    for bucket in ((unspent or {}).get("by_chapter") or []):
        redistributable += min(float(bucket.get("shortage") or 0.0),
                               float(bucket.get("sources") or 0.0))
    redistributable = min(redistributable, structural)
    after_redistribution = structural - redistributable
    pooled_gap = max(0.0, rss_need - fuel)
    locked = max(0.0, after_redistribution - pooled_gap)
    rss_gap = after_redistribution - locked
    out: dict[str, Any] = {
        "rss_need_after_cut": rss_need,
        "fuel": fuel,
        "structural": structural,
        "redistributable": redistributable,
        "locked_limits": locked,
        "rss_gap": rss_gap,
        "model_excess": None,
        "total": None,
    }
    if approved_remaining is not None:
        model_excess = float(approved_remaining) - rss_need
        out["model_excess"] = model_excess
        out["total"] = max(0.0, rss_gap + model_excess)
    return out


def _remaining_check(limit: float, paid: float, waterfall: dict[str, Any],
                     reserve: float = 0.0) -> dict[str, float]:
    """Из чего складывается остаток лимита: лимит − оплачено + поправки.

    Плашки «лимит 4,64 · выбрано 4,80 · остаток 1,00» не сходились
    (владелец, 22.10.2026): остаток считается по статьям — лимит статьи минус
    всё оплаченное по ней (кредит и свои деньги), а статья с перерасходом
    идёт нулём. Здесь разница названа: перерасход статей и расхождение
    смет статей финкниги с итогом РСС — остаток, а не округление.

    Резерв (статьи 2.8/2.9) из статей вынут и стоит своей строкой, поэтому
    сумма статей меньше сметы РСС ровно на него; это не расхождение книги со
    сметой, а то же число второй раз (владелец, 22.10.2026, строка
    «−306,2 млн ₽»: «Зачем эта запись?»). Разница считается с его учётом.
    """
    remaining = float(waterfall.get("opening_bank_remaining") or 0.0)
    overpaid = float(waterfall.get("opening_article_deficit") or 0.0)
    plain = float(limit or 0.0) - float(paid or 0.0)
    return {"plain": plain, "overpaid": overpaid,
            "book_gap": remaining - plain - overpaid + float(reserve or 0.0),
            "remaining": remaining}


def _bank_need_check(remaining_need: float, reserve: float,
                     waterfall: dict[str, Any]) -> dict[str, Any]:
    """Сверка «Средств на завершение» банка с нашим остатком лимитов.

    Две суммы об одном остатке стояли рядом и расходились на 200 млн ₽, и
    откуда разница — было не видно (владелец, 01.09.2026: «Откуда ещё 200 млн
    взялось?»). Здесь она раскладывается: по главам, по резерву, по статьям с
    перерасходом (их отрицательный остаток мы берём нулём), и то, что не
    объяснилось, названо остатком, а не спрятано в округление.
    """
    rows = waterfall.get("articles") or []
    by_chapter: dict[str, float] = {}
    no_programme = 0.0
    raw_total = 0.0
    for row in rows:
        raw = float(row.get("opening_limit_raw") or 0.0)
        raw_total += raw
        chapter = str(row.get("chapter") or str(row.get("code") or "").split(".")[0])
        by_chapter[chapter] = by_chapter.get(chapter, 0.0) + max(0.0, raw)
        if not row.get("has_programme"):
            no_programme += max(0.0, raw)
    clipped = float(waterfall.get("opening_article_deficit") or 0.0)
    ours = float(waterfall.get("opening_bank_remaining") or 0.0) + float(reserve or 0.0)
    # Наш остаток без клипа: то, что банк увидел бы, складывая статьи со знаком.
    ours_raw = raw_total + float(reserve or 0.0)
    return {
        "bank_column": float(remaining_need or 0.0),
        "ours": ours,
        "by_chapter": dict(sorted(by_chapter.items())),
        "reserve": float(reserve or 0.0),
        "no_programme": no_programme,
        "overpaid_clipped": clipped,
        "residual": float(remaining_need or 0.0) - ours_raw,
    }


def _payment_total_ch23(rss: Path, estimate: dict[str, Any],
                        chapters: Any = ("2", "3")) -> float:
    return _paid_in_chapters(rss, estimate, chapters)["total"]


def _funding_risk(project: str, rss: Path, cut: datetime.date, view: dict[str, Any]) -> dict[str, Any]:
    def unavailable(reason: str, **extra: Any) -> dict[str, Any]:
        result = {"known": False, "reason": reason, **extra,
                  "source_dates": _funding_source_dates(project, rss, cut)}
        notes = funding_source_notes(result)
        result["limit_reconciliation_lines"] = [notes["paid"], notes["limit"]]
        return result

    baseline = _finance_baseline(project)
    if not baseline.get("known"):
        return unavailable(baseline.get("reason", "нет финансового baseline"))

    estimate = actuals.read_estimate(rss)
    chapters = tuple(baseline.get("chapters") or ("2", "3"))
    current = _rss_ch23(estimate, chapters)
    paid = _paid_in_chapters(rss, estimate, chapters)
    paid_actual = paid["total"]
    finmodel = baseline.get("kind") == "finmodel"
    sections = baseline.get("sections") if finmodel else None
    if finmodel and not all(ch in (sections or {}) for ch in _FM_BANK_CHAPTERS):
        wanted = ", ".join(f"«{code}»" for code in _FM_SECTIONS)
        return unavailable(f"в листе «cf_1_new» нет строк разделов {wanted} — потребность "
                           "на стройку и коммерцию не прочитать", source=baseline.get("source"))
    schedule_need = None
    if finmodel:
        # Сколько нужно на стройку и коммерцию — план разделов финмодели с
        # месяца среза; тот же ряд идёт в водопад против остатка лимита
        # глав 2–3 сметы.
        plan_from = monitor._day(baseline.get("plan_from"))
        schedule_need = _schedule_need(project, rss, estimate, cut)
        section_rows = _section_articles(sections, estimate, rss, cut, plan_from,
                                         baseline.get("chapter_flow"), schedule_need)
        remaining_need = sum(sum(item["monthly_need"].values())
                             for item in section_rows.values())
    else:
        paid_delta = max(0.0, paid_actual - float(baseline["paid_at_baseline"] or 0.0))
        remaining_need = max(0.0, float(baseline["completion_need_at_baseline"] or 0.0)
                             - paid_delta)

    articles = baseline.get("articles") or {}
    if not articles:
        return unavailable("в финансовом baseline не найдена постатейная программа потребности",
                           source=baseline.get("source"))

    # Для финмодели водопад — по главам 2–3 сметы: лимит главы минус всё
    # оплаченное по ней (резервы 2.8/2.9 уже внутри лимита главы 2) против
    # плана раздела финмодели по месяцам. Статьи финмодели на статьи сметы
    # один в один не ложатся, и постатейно здесь нечего считать.
    waterfall = _article_waterfall(
        section_rows if finmodel else articles,
        0.0 if finmodel else float(baseline.get("reserve") or 0.0),
        cut,
        {} if finmodel else _payment_by_code(rss),
    )
    # Остаток лимита для финмодели — только главы 2–3 (вопрос владельца про
    # стройку и продажи); лимит и оплаченное всех глав остаются в плашках
    # «Лимит банка» и «Выбрано у банка».
    scope = None
    if finmodel:
        scope_paid = _paid_in_chapters(rss, estimate, _FM_BANK_CHAPTERS)
        scope = {"chapters": chapters_label(_FM_BANK_CHAPTERS),
                 "limit": _rss_ch23(estimate, _FM_BANK_CHAPTERS)["limit"],
                 "paid": scope_paid["total"], "borrowed": scope_paid["borrowed"]}
    rnv = monitor._day(_current_forecast_end(view))
    if rnv is None:
        rnv = monitor._day((view.get("schedule") or {}).get("approved_end"))
    reserve_inside = _reserve_inside(rss, estimate) if finmodel else None

    reserve_start = waterfall["reserve_start"]
    reserve_exhaustion = waterfall["reserve_exhaustion"]
    unspent_view = _unspent(project, rss, estimate, rnv, waterfall,
                            None if finmodel else articles, cut, chapters)
    approved = float(baseline.get("approved") or 0.0)
    # Остаток утверждённого бюджета: у финмодели это её «ПЛАН» (ИТОГО − ФАКТ
    # по построению); вычитать оплаченное по РСС из бюджета финмодели — снова
    # смешивать две книги.
    if finmodel:
        book_remaining = remaining_need
    else:
        book_remaining = max(0.0, approved - paid_actual) if approved > 0 else None
    # Глава 1 есть в РСС, а в финансовой книге её строки нет — она всё равно
    # деньги проекта (владелец, 22.10.2026: «что за бред на плашках. Разве в
    # РСС нет 1 главы?»). Тогда лимит, оплачено и выбрано у банка берут главу
    # 1 из РСС, а её утверждённый бюджет — смета РСС; подпись это называет.
    # Постатейная программа и дефицит остаются по главам книги: у главы 1
    # утверждённое равно лимиту, своего дефицита она не добавляет.
    shown = chapters
    reason = baseline.get("chapters_reason") or ""
    waterfall_book = waterfall
    one = (estimate.get("by_code") or {}).get("1")
    chapter_one = None
    # У финмодели остаток и потребность считаются по главам 2–3; главу 1 сюда
    # не добавлять.
    if not finmodel and "1" not in chapters and one is not None:
        one_limit = float(one.get("estimate") or 0.0)
        one_paid = _paid_in_chapters(rss, estimate, ("1",))
        chapter_one = {"limit": one_limit, "paid": one_paid["total"],
                       "borrowed": one_paid["borrowed"]}
        shown = ("1",) + tuple(chapters)
        reason = ("глава 1 — по смете и оплатам РСС: в финансовой книге её строки нет")
        current = {**current, "limit": current["limit"] + one_limit}
        paid = {**paid, "borrowed": paid["borrowed"] + one_paid["borrowed"]}
        paid_actual += one_paid["total"]
        approved += one_limit
        waterfall = {**waterfall,
                     "opening_bank_remaining": float(waterfall["opening_bank_remaining"])
                     + max(0.0, one_limit - one_paid["total"]),
                     "opening_article_deficit": float(waterfall["opening_article_deficit"])
                     + max(0.0, one_paid["total"] - one_limit)}
    smeta = dict(current.get("by_chapter") or {})
    if chapter_one is not None:
        smeta["1"] = chapter_one["limit"]
    paid_by_chapter = {str(ch): _paid_in_chapters(rss, estimate, (ch,)) for ch in shown}
    own_money = None
    if finmodel:
        plan_from = monitor._day(baseline.get("plan_from"))
        own_money = _own_money(
            baseline.get("budget_composition"), smeta, paid_by_chapter, shown, cut, plan_from,
            {str(ch): _paid_since(rss, estimate, str(ch), plan_from) for ch in shown},
            baseline.get("chapter_flow"), schedule_need)
    reconciliation = _limit_reconciliation(
        waterfall_book, current["limit"], shown, smeta_by_chapter=smeta,
        paid_by_chapter=paid_by_chapter,
        approved_by_chapter=baseline.get("approved_by_chapter") or {},
        # Глава 1 из РСС при бюджетной книге входит в остаток плашки (см. выше).
        remaining_outside=("1",) if chapter_one is not None else ())
    result = {
        "known": True,
        "source": baseline["source"],
        "limit_reconciliation": reconciliation,
        "budget_composition": baseline.get("budget_composition"),
        "own_money": own_money,
        # Глава, потребность которой взята из графика финансирования, и его версия.
        "schedule_need": ({k: schedule_need[k] for k in ("chapter", "day", "file", "owed")}
                          if schedule_need else None),
        "own_money_lines": own_money_lines(own_money, _fmt_money),
        "baseline_file": monitor.finance_baseline_meta(project),
        "limit_reconciliation_lines": reconciliation_lines(reconciliation, _fmt_money),
        "chapters": list(shown),
        "chapters_label": chapters_label(shown),
        "chapters_reason": reason,
        "chapter_one_from_rss": chapter_one,
        "bank_limit": current["limit"],
        "paid_actual": paid_actual,
        # Выборка кредита по тем же главам, что лимит: «лимит − выбрано» и
        # «лимит − оплачено» читаются от одной базы.
        "paid_borrowed": paid["borrowed"],
        "remaining_check": (_remaining_check(scope["limit"], scope["paid"], waterfall, 0.0)
                            if finmodel else
                            _remaining_check(current["limit"], paid_actual, waterfall,
                                             float(baseline.get("reserve") or 0.0))),
        # Второй остаток потребности по тем же главам 2–3: утверждённый бюджет
        # минус оплаченное. С «средствами на завершение» они расходятся, и обе
        # величины считает сервер — экран их только показывает.
        "approved": approved,
        "approved_remaining": remaining_need if finmodel else max(0.0, approved - paid_actual),
        # Чем измерена потребность: разделами финмодели против глав 2–3 сметы
        # или бюджетом книги по статьям. Сводка подписывает плашки по этому
        # признаку; разбивка по главам — для плашки «Потребность в
        # допфинансировании банка».
        "need_basis": "model" if finmodel else "budget",
        "remaining_scope": scope if finmodel else None,
        "need_by_chapter": ({row["chapter"]: {
            "label": sections[row["chapter"]]["label"],
            "label_acc": sections[row["chapter"]].get("label_acc") or sections[row["chapter"]]["label"],
            "need": row["need_total"],
            "remaining": row["opening_limit"], "gap": row["unfunded_take"],
            "gap_from": row["first_unfunded_month"]}
            for row in waterfall["articles"]} if finmodel else None),
        "bank_remaining": waterfall["opening_bank_remaining"],
        "opening_article_deficit": waterfall["opening_article_deficit"],
        "remaining_need": remaining_need,
        "reserve": float(baseline.get("reserve") or 0.0),
        "reserve_parts": baseline.get("reserve_parts") or {},
        "reserve_names": baseline.get("reserve_names") or {},
        # Резервы 2.8/2.9 сметы РСС при финмодели: у финмодели своя строка
        # резерва (2.2.11), и она пустая, а резервы банка лежат внутри лимита
        # главы 2 и уже вошли в остаток. Их показывают отдельно — к остатку
        # второй раз не прибавляют (владелец, 24.10.2026: «Резерв разве 0»).
        "reserve_inside": reserve_inside,
        "limit_by_chapter": current.get("by_chapter") or {},
        "approved_by_chapter": baseline.get("approved_by_chapter") or {},
        "reserve_start": monitor._iso(reserve_start),
        "reserve_exhaustion": monitor._iso(reserve_exhaustion),
        # Backward-compatible field used by the red marker/card. It now means
        # the first uncovered need after article limits + explicit reserve.
        "bank_exhaustion": monitor._iso(reserve_exhaustion),
        "reserve_balance": waterfall["reserve_balance"],
        "reserve_need": waterfall["reserve_need"],
        "additional_financing": waterfall["additional_financing"],
        "additional_financing_from": waterfall["additional_financing_from"],
        "additional_financing_by_chapter": waterfall["additional_financing_by_chapter"],
        "additional_financing_note": waterfall["additional_financing_note"],
        "retention": _retention(project, rnv),
        # Что не будет выбрано до ввода: свободное от договоров считается точно,
        # ГУ раскладываются по статьям оценкой. Считает это отдельный модуль,
        # здесь только вход — лимиты и потребность живут выше и второй раз не
        # считаются.
        "unspent": unspent_view,
        # Колонка банка против нашего остатка — разложенная разница, а не две
        # цифры рядом.
        "bank_need_check": _bank_need_check(
            remaining_need, float(baseline.get("reserve") or 0.0), waterfall_book),
        # Лестница от структурного дефицита к «не хватает на достройку»:
        # считается здесь, экран только показывает.
        # Для финмодели водопад уже по главам 2–3: переброска свободного лимита
        # между статьями сметы внутри главы в нём учтена, и вычитать её второй
        # раз нельзя — иначе плашка потребности расходится с «не хватает»
        # (владелец, 24.10.2026: 2,27 на одной плашке и 2,39 на соседней).
        "deficit_ladder": _deficit_ladder(
            waterfall_book, 0.0 if finmodel else float(baseline.get("reserve") or 0.0),
            book_remaining, None if finmodel else unspent_view),
        "forecast_to": monitor._iso(rnv),
        "monthly_need": waterfall["monthly_need"],
        "monthly_reserve_draw": waterfall["monthly_reserve_draw"],
        "monthly_unfunded": waterfall["monthly_unfunded"],
        "monthly_reserve_balance": waterfall["monthly_reserve_balance"],
        "articles": waterfall["articles"],
        "tail_after_apr": max(0.0, float(baseline.get("tail_after_apr") or 0.0)),
        "method": (
            "по финмодели: план раздела за месяц → остаток лимита главы 2–3 сметы "
            "(лимит минус оплаченное, резервы внутри) → непокрытая потребность"
            if finmodel else
            "постатейный waterfall: потребность месяца → остаток лимита статьи RSS → "
            "резервы 2.8/2.9 → непокрытая потребность; свободные лимиты других статей "
            "автоматически не кросс-финансируют дефицит"
        ),
    }
    result["source_dates"] = _funding_source_dates(project, rss, cut, schedule_need)
    result["limit_reconciliation_lines"] = funding_reconciliation_lines(result, _fmt_money)
    return result


_FM_BANK_CHAPTERS = tuple(sorted({ch for ch, _, _ in _FM_SECTIONS.values()}))


def _reserve_inside(rss: Path, estimate: dict[str, Any]) -> dict[str, Any] | None:
    """Остаток резервов 2.8/2.9 сметы РСС: лимит строки минус оплаченное по ней."""
    by_code = estimate.get("by_code") or {}
    parts: dict[str, float] = {}
    names: dict[str, str] = {}
    for code in sorted(_RESERVE_CODES):
        row = by_code.get(code)
        if row is None:
            continue
        paid = float(_paid_in_chapters(rss, estimate, (code,))["total"])
        parts[code] = max(0.0, float(row.get("estimate") or 0.0) - paid)
        names[code] = str(row.get("article") or "").strip()
    if not parts:
        return None
    chapters = sorted({str((by_code.get(code) or {}).get("parent") or "") for code in parts} - {""})
    return {"total": sum(parts.values()), "parts": parts, "names": names,
            "chapters": chapters_label(chapters) if chapters else ""}


def _paid_since(rss: Path, estimate: dict[str, Any], chapter: str,
                since: datetime.date | None) -> float:
    """Оплачено по главе по реестру РСС начиная с `since` (дата книги)."""
    if since is None:
        return 0.0
    keep = payment_in_chapters(estimate, (chapter,))
    return sum(float(row.get("amount") or 0.0)
               for row in actuals.read_payments(rss).get("rows") or []
               if keep(row) and row.get("date") and row["date"] >= since)


def _plan_still_owed(monthly: dict[str, float], plan_from: datetime.date | None,
                     paid_since: float, cut: datetime.date) -> dict[str, float]:
    """План финмодели, который ещё предстоит оплатить, по месяцам.

    План книги начинается с её даты, а реестр РСС уже несёт оплаты после неё.
    Прежде потребность бралась «с месяца среза»: когда наступал новый месяц,
    план прошедшего месяца выпадал целиком, оплачен он или нет, и нехватка
    прыгала без единого платежа (владелец, 02.11.2026: 2,40 в октябре, 1,77 в
    ноябре). Теперь оплаты по реестру после даты книги гасят план с его
    начала, а неоплаченный остаток прошедших месяцев переносится на месяц
    среза: он всё ещё должен быть оплачен.
    """
    cut_month = cut.replace(day=1)
    start = plan_from.replace(day=1) if plan_from else cut_month
    left = max(0.0, float(paid_since or 0.0))
    out: dict[str, float] = {}
    for key in sorted(monthly):
        month = monitor._day(key)
        if month is None or month < start:
            continue
        amount = max(0.0, float(monthly[key] or 0.0))
        covered = min(left, amount)
        left -= covered
        amount -= covered
        target = max(month, cut_month).isoformat()
        out[target] = out.get(target, 0.0) + amount
    return out


# Глава, потребность которой берётся из графика финансирования, а не из
# финмодели (решение владельца, 03.11.2026: «Верно считает график» — график
# собран по договорам, финмодель закладывала по главе 2 на 0,7 млрд больше).
_SCHEDULE_CHAPTER = "2"


def _schedule_need(project: str, rss: Path, estimate: dict[str, Any],
                   cut: datetime.date, chapter: str = _SCHEDULE_CHAPTER) -> dict[str, Any] | None:
    """Что ещё предстоит оплатить по главе — по графику финансирования.

    Версия — последняя на дату среза. План графика берётся с месяца версии, а
    оплаты по реестру РСС с начала этого месяца гасят его с начала
    (`_plan_still_owed`): «Остаток к выплате» графика — на его дату, реестр
    идёт дальше. Нет графика — None, и глава считается по финмодели.
    """
    import developaid_funding_schedule as funding_schedule

    found = funding_schedule.sources(project, cut.isoformat())["versions"]
    if not found:
        return None
    day = list(found)[-1]
    try:
        schedule = funding_schedule.read_schedule(found[day]["path"])
    except funding_schedule.ScheduleUnreadable:
        return None
    monthly: dict[str, float] = {}
    rows = [row for row in schedule["rows"]
            if row["code"] == chapter or row["code"].startswith(chapter + ".")]
    for row in rows:
        for month, amount in (row.get("plan") or {}).items():
            if amount:
                key = f"{month}-01"
                monthly[key] = monthly.get(key, 0.0) + float(amount)
    start = datetime.date.fromisoformat(day[:7] + "-01")
    paid_since = _paid_since(rss, estimate, chapter, start)
    owed = _plan_still_owed(monthly, start, paid_since, cut)
    return {"day": day, "file": found[day].get("file") or "", "chapter": chapter,
            "source_dates": _stored_funding_source(project, Path(found[day]["path"])),
            "monthly": owed, "owed": sum(owed.values()), "paid_since": paid_since,
            "plan_from": start.isoformat()}


def _section_articles(sections: dict[str, dict[str, Any]], estimate: dict[str, Any],
                      rss: Path, cut: datetime.date | None = None,
                      plan_from: datetime.date | None = None,
                      chapter_flow: dict[str, dict[str, Any]] | None = None,
                      schedule: dict[str, Any] | None = None
                      ) -> dict[str, dict[str, Any]]:
    """Разделы финмодели как строки водопада — по главам 2–3 сметы.

    Лимит — «Общая сметная стоимость» строки главы РСС (резервы внутри),
    «оплачено» — всё оплаченное по главе по РСС, потребность по месяцам — план
    раздела финмодели с даты книги за вычетом оплаченного по реестру после неё
    (`_plan_still_owed`).
    """
    by_code = estimate.get("by_code") or {}
    out: dict[str, dict[str, Any]] = {}
    for chapter in _FM_BANK_CHAPTERS:
        section = sections[chapter]
        row = by_code.get(chapter) or {}
        # Потребность главы — статьи финмодели, которые карта относит к ней;
        # без карты (старая база) — раздел финмодели этой главы.
        flow = (chapter_flow or {}).get(chapter)
        monthly = dict((flow if flow is not None else section).get("monthly") or {})
        if schedule is not None and schedule["chapter"] == chapter:
            monthly = dict(schedule["monthly"])
        elif cut is not None:
            monthly = _plan_still_owed(monthly, plan_from,
                                       _paid_since(rss, estimate, chapter, plan_from), cut)
        out[chapter] = {
            "code": chapter, "chapter": chapter,
            "name": f"{section['label'].capitalize()} — {section['name']} (финмодель) "
                    f"против главы {chapter} сметы",
            "rss_limit": float(row.get("estimate") or 0.0),
            "paid_at_baseline": float(_paid_in_chapters(rss, estimate, (chapter,))["total"]),
            "has_programme": any((section.get("monthly") or {}).values()),
            "monthly_need": monthly,
        }
    return out


def _physical_smr(rss: Path, estimate: dict[str, Any], cut: datetime.date) -> float:
    works = actuals.read_completed_works(rss)
    return sum(
        float(row.get("amount") or 0.0)
        for row in works.get("rows") or []
        if row.get("construction")
        and row.get("date")
        and row["date"] <= cut
        and str(row.get("code") or "").startswith("2")
    )


def _latest_sales_rows(project: str, upto: datetime.date | None = None) -> Path | None:
    folder = monitor._project_dir(project) / "sales"
    if not folder.exists():
        return None
    rows = sorted(folder.glob("*.json"))
    if upto:
        rows = [row for row in rows if row.stem[:10] <= upto.isoformat()]
    return rows[-1] if rows else None


def _sales_snapshot(project: str, cut: datetime.date) -> dict[str, Any]:
    """Продажи: числа, а не факт наличия файла.

    Источника два, и они дополняют друг друга. Книга обновляется раз в месяц
    и несёт историю (лист «План продаж», строки ФАКТ); строки руками несут
    то, чего книга ещё не знает — «в августе продано 4 лота» приходит словами
    за месяц до выгрузки. Месяц из строк перекрывает тот же месяц книги.
    """
    import json as _json

    monthly: dict[str, dict[str, float]] = {}
    sources: list[str] = []

    book = _latest_sales(project, cut)
    if book is not None:
        try:
            parsed = actuals.read_sales(book)
        except Exception:
            parsed = None
        if parsed:
            for row in parsed["rows"]:
                if not row.get("fact") or not row.get("month"):
                    continue
                monthly[monitor._iso(row["month"])[:7]] = {
                    "units": float(row.get("units") or 0.0),
                    "area": float(row.get("area") or 0.0),
                    "revenue": float(row.get("revenue") or 0.0),
                }
            sources.append(book.name)
        else:
            sources.append(f"{book.name} (лист продаж не разобран)")

    manual = _latest_sales_rows(project, cut)
    if manual is not None:
        stored = _json.loads(manual.read_text(encoding="utf-8"))
        for row in stored.get("rows") or []:
            month = monitor._iso(actuals._as_month(row.get("month")))[:7]
            if not month:
                continue
            monthly[month] = {
                "units": float(row.get("units") or 0.0),
                "area": float(row.get("area") or 0.0),
                "revenue": float(row.get("revenue") or 0.0),
            }
        sources.append(f"строки на {stored.get('taken_at', manual.stem)}")

    if not monthly:
        return {"known": False, "reason": "не загружены ни книга, ни строки продаж"}
    months = sorted(monthly)
    recent = [{"month": month, **monthly[month]} for month in months[-3:]]
    return {
        "known": True,
        "source": " + ".join(sources),
        "last_fact": months[-1],
        "total_units": sum(row["units"] for row in monthly.values()),
        "total_area": sum(row["area"] for row in monthly.values()),
        "total_revenue": sum(row["revenue"] for row in monthly.values()),
        "recent": recent,
    }


def _fmt_money(value: Any) -> str:
    number = float(value or 0.0)
    if abs(number) >= 1e9:
        text = f"{number/1e9:,.2f}".replace(",", " ").replace(".", ",")
        return f"{text} млрд ₽"
    text = f"{number/1e6:,.1f}".replace(",", " ").replace(".", ",")
    return f"{text} млн ₽"


def _month_name(value: Any) -> str:
    day = monitor._day(value)
    if day is None:
        return str(value or "")
    names = ("январь", "февраль", "март", "апрель", "май", "июнь", "июль",
             "август", "сентябрь", "октябрь", "ноябрь", "декабрь")
    return f"{names[day.month - 1]} {day.year}"


def _gap_by_chapter_sentence(funding: dict[str, Any]) -> str:
    """«Из них по главе 2 (стройка) — …, первый месяц нехватки — …» и что не входит."""
    parts = []
    for row in funding.get("additional_financing_by_chapter") or []:
        name = f"по главе {row['chapter']}" + (f" ({row['label']})" if row.get("label") else "")
        since = (f", первый месяц нехватки — {_month_name(row['from'])}"
                 if row.get("from") else "")
        parts.append(f"{name} — {_fmt_money(row['amount'])}{since}")
    text = f" Из них {'; '.join(parts)}." if parts else ""
    note = funding.get("additional_financing_note")
    return text + (f" {note}" if note else "")


def _summary(view: dict[str, Any], funding: dict[str, Any],
             sales: dict[str, Any]) -> list[str]:
    """Управленческое резюме словами — из тех же чисел, что и графики.

    Лимит, утверждённая модель, дефицит и его дата не должны собираться в
    голове из столбиков: сервер, который их посчитал, обязан их и сказать.
    """
    out: list[str] = []
    schedule = (view.get("dashboard") or {}).get("schedule") or view.get("schedule") or {}
    approved = monitor._day(schedule.get("approved_finish") or schedule.get("approved_end"))
    forecast = monitor._day(schedule.get("forecast_finish"))
    delay = schedule.get("rnv_delay_days")
    if approved and forecast:
        drift = (f"на {delay} дней позже плана" if isinstance(delay, (int, float))
                 and delay and delay > 0 else "в срок")
        out.append(
            f"Срок. Утверждённый ввод — {approved.strftime('%d.%m.%Y')}; при "
            f"нынешнем темпе актов КС модель ждёт "
            f"{forecast.strftime('%d.%m.%Y')} — {drift}.")

    if not funding.get("known"):
        out.append("Деньги. Финансовая книга не загружена — потребность и "
                   "дефицит посчитать не из чего.")
        return out

    need = float(funding.get("remaining_need") or 0.0)
    bank = float(funding.get("bank_remaining") or 0.0)
    reserve = float(funding.get("reserve") or 0.0)
    fuel = bank + reserve
    # РСС — это то, что даёт банк; утверждённая модель — сколько надо реально,
    # чтобы построить (владелец, 30.08.2026). Значит потребность берётся из
    # модели, а лимиты банка с резервом — это источник, и главный дефицит есть
    # разница между ними. Прежде фраза брала потребностью банковскую колонку
    # «Средства на завершение» — то есть взгляд банка на остаток, — и дефицит
    # выходил вчетверо меньше настоящего.
    model_need = float(funding.get("approved_remaining") or 0.0)
    if model_need > 0:
        gap = max(0.0, model_need - fuel)
        inside = funding.get("reserve_inside") or {}
        kept = (f"{_fmt_money(bank)} остатка лимита, в нём уже "
                f"{_fmt_money(inside.get('total'))} резервов 2.8/2.9"
                if inside.get("total") else
                f"{_fmt_money(bank)} лимитов статей и "
                f"{_fmt_money(reserve)} резерва 2.8/2.9")
        money = (
            f"Деньги. По утверждённой модели достроить стоит "
            f"{_fmt_money(model_need)} (модель минус оплаченное). По РСС "
            f"осталось {_fmt_money(fuel)}: {kept} — оставшийся лимит и есть "
            f"то, что банк готов дать; сам РСС при этом бюджет всей стройки, а "
            f"не банковская доля. Дефицит {_fmt_money(gap)}.")
        if need > 0:
            money += (f" Справочно: сам банк считает остаток к завершению в "
                      f"{_fmt_money(need)} — это его взгляд по РСС, а не "
                      f"потребность стройки.")
    else:
        money = (
            f"Деньги. Утверждённая модель не прочитана — сколько реально надо "
            f"достроить, сказать нечем. Банк даёт {_fmt_money(fuel)}; его "
            f"остаток к завершению по РСС — {_fmt_money(need)}.")
    out.append(money)

    start = funding.get("reserve_start")
    exhaustion = funding.get("reserve_exhaustion")
    unfunded = funding.get("monthly_unfunded") or {}
    first_gap = next((month for month in sorted(unfunded)
                      if float(unfunded[month] or 0.0) > 1e6), None)
    gap_total = float(funding.get("additional_financing") or 0.0)
    if gap_total > 1e6:
        pieces = []
        if start:
            pieces.append(f"с {_month_name(start)} статьи начинают тратить резерв")
        if exhaustion:
            pieces.append(f"{monitor._day(exhaustion).strftime('%d.%m.%Y')} резерв "
                          f"кончается")
        if first_gap:
            pieces.append(f"с {_month_name(first_gap)} платить нечем — "
                          f"в этот месяц не хватает "
                          f"{_fmt_money(unfunded[first_gap])}")
        out.append("Когда возникает дыра. " + "; ".join(pieces) + ". "
                   f"Всего до конца не хватает {_fmt_money(gap_total)} — это и "
                   "есть потребность в дофинансировании."
                   + _gap_by_chapter_sentence(funding))
        deadline = exhaustion or first_gap
        if deadline:
            out.append(
                f"Решение. Дофинансирование или увеличение лимитов на "
                f"{_fmt_money(gap_total)} нужно согласовать до "
                f"{monitor._day(deadline).strftime('%d.%m.%Y')} — дальше стройка "
                "платит только тем, что осталось, и темп станет падать.")
    else:
        out.append("Дыры по РСС нет: лимиты статей и резерв "
                   "закрывают потребность до конца.")

    rows = funding.get("articles") or []
    short = sorted((row for row in rows
                    if float(row.get("need_total") or 0.0)
                    > float(row.get("opening_limit") or 0.0) + 1e6),
                   key=lambda row: float(row.get("need_total") or 0.0)
                   - float(row.get("opening_limit") or 0.0), reverse=True)[:3]
    if short:
        names = "; ".join(
            f"{row['code']} {str(row.get('name') or '').strip()} — не хватает "
            f"{_fmt_money(float(row.get('need_total') or 0.0) - float(row.get('opening_limit') or 0.0))}"
            for row in short)
        out.append(f"Где не хватает больше всего: {names}. Резерв общий и "
                   "закрывает их по очереди месяцев, пока не кончится.")

    if sales.get("known"):
        out.append(
            f"Продажи. Продано {sales.get('total_units', 0):.0f} лотов на "
            f"{_fmt_money(sales.get('total_revenue'))}; последний факт — "
            f"{sales.get('last_fact', '')}.")
    return out


def _dashboard(project: str, rss: Path, cut: datetime.date, view: dict[str, Any]) -> dict[str, Any]:
    estimate = actuals.read_estimate(rss)
    finance = _finance_baseline(project)
    current = _rss_ch23(estimate, tuple(finance.get("chapters") or ("2", "3")))
    physical = _physical_smr(rss, estimate, cut)
    approved = float(finance.get("approved") or 0.0)
    funding = _funding_risk(project, rss, cut, view)
    graph = (view.get("schedule") or {}).get("dependency_graph") or {}
    return {
        "physical": {
            "accepted": physical,
            "completion": physical / approved if approved > 0 else None,
        },
        "construction": {
            "approved": approved or None,
            "limit": current["limit"],
            "contracted": current["contracted"],
            "remaining_need": funding.get("remaining_need") if funding.get("known") else None,
        },
        "schedule": {
            "approved_finish": (view.get("schedule") or {}).get("approved_end"),
            "forecast_finish": _current_forecast_end(view),
            "forecast_known": graph.get("forecast_known", True),
            "forecast_source": graph.get("forecast_source", ""),
            "rnv_delay_days": graph.get("rnv_delay_days"),
        },
        "sales": _sales_snapshot(project, cut),
        "funding": funding,
        "summary": _summary(view, funding, _sales_snapshot(project, cut)),
        "sources": {
            "rss": rss.name,
            "physical_fact": "Реестр выполненных работ",
            "payment_fact": "Реестр платежей",
            "financial_baseline": finance.get("source"),
        },
    }


def _store_sales_file(project: str, data: bytes, taken_at: Any) -> dict[str, Any]:
    day = monitor._iso(taken_at)
    from openpyxl import load_workbook

    wb = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    try:
        known = ("Продажи П-Ф", "Продажи", "Дашборд", "План продаж")
        if not any(name in wb.sheetnames for name in known):
            raise ValueError(
                "в книге не найден лист продаж — жду «Продажи П-Ф», «Продажи», "
                "«Дашборд» или «План продаж»")
    finally:
        wb.close()
    path = _sales_dir(project) / f"{day}.xlsx"
    if path.exists():
        raise FileExistsError(f"отчет продаж на {day} уже загружен")
    path.write_bytes(data)
    return {"taken_at": day, "stored": True, "path": str(path), "bytes": len(data)}


def _store_proposal(
    project: str, data: bytes, sheet: str, start: Any, code: str, taken_at: Any
) -> dict[str, Any]:
    return schedule_graph.store_reference(project, data, sheet, start, code, taken_at)


def _current_forecast_end(view: dict[str, Any]) -> Any:
    """Текущий прогноз РНВ — сеть по темпу, а не плоский максимум по строкам.

    `schedule.forecast_end` — это `max(forecast_finish)` по WBS: он не знает
    PM-зависимостей и потому отвечает на другой вопрос. Pace считает сеть и
    кладёт ответ в `pace_forecast_end`, но дашборд собирался заново и брал
    плоский максимум — на Кутузов Сити шапка показывала 04.01.2029, а
    «Платон · управленческий прогноз» 11.02.2028 на том же срезе и том же
    снимке РСС. Подпись шапки при этом обещала «КС / EAC proxy + PM
    dependencies» — обещание, которого она не исполняла.

    Плоский максимум остаётся запасным ответом: без PM-графа сети нет, и
    честнее показать позднейшую строку, чем ничего.
    """
    schedule = view.get("schedule") or {}
    return schedule.get("pace_forecast_end") or schedule.get("forecast_end")


def _build(
    project: str, cut: Any, programme: dict[str, Any] | None = None, upto: str = ""
) -> dict[str, Any]:
    if _ORIGINAL_BUILD is None:
        raise RuntimeError("dashboard layer is not installed")
    view = _ORIGINAL_BUILD(project, cut, programme=programme, upto=upto)
    view = schedule_graph.apply(project, view)
    rss = monitor._latest(project, "estimate", ".xlsx", upto or monitor._iso(cut))
    cut_date = monitor._day(cut)
    if rss is not None and cut_date is not None:
        dashboard = _dashboard(project, rss, cut_date, view)
        view["dashboard"] = dashboard
        view["financing"] = dashboard["funding"]
    return view


def install() -> None:
    global _INSTALLED, _ORIGINAL_BUILD, _ORIGINAL_STORE_SALES_FILE, _ORIGINAL_STORE_PROPOSAL
    if _INSTALLED:
        return
    _ORIGINAL_BUILD = monitor.build
    _ORIGINAL_STORE_SALES_FILE = getattr(monitor, "store_sales_file", None)
    _ORIGINAL_STORE_PROPOSAL = getattr(monitor, "store_proposal", None)
    monitor.build = _build
    monitor.store_sales_file = _store_sales_file
    monitor.store_proposal = _store_proposal
    _INSTALLED = True
