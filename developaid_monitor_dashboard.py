"""Management KPI, funding-risk and recurring-input layer for Project Monitor.

Funding is calculated article-by-article. A free balance in one RSS article is
not silently allowed to finance another article. Once an article's own balance
is exhausted, that month's need consumes the explicit 2.8/2.9 reserve; only
after the reserve is exhausted does the model report uncovered financing.
"""
from __future__ import annotations

import datetime
import io
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
        if not code or not code.startswith("2."):
            continue
        depth = code.count(".") + 1
        while stack and stack[-1]["depth"] >= depth:
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
        if meta["has_children"]:
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
        "monthly_need": monthly_need,
        "monthly_reserve_draw": monthly_reserve_draw,
        "monthly_unfunded": monthly_unfunded,
        "monthly_reserve_balance": monthly_reserve_balance,
        "articles": article_rows,
    }


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
    baseline = _finance_baseline(project)
    if not baseline.get("known"):
        return {"known": False, "reason": baseline.get("reason", "нет финансового baseline")}

    estimate = actuals.read_estimate(rss)
    chapters = tuple(baseline.get("chapters") or ("2", "3"))
    current = _rss_ch23(estimate, chapters)
    paid = _paid_in_chapters(rss, estimate, chapters)
    paid_actual = paid["total"]
    finmodel = baseline.get("kind") == "finmodel"
    sections = baseline.get("sections") if finmodel else None
    if finmodel and not all(ch in (sections or {}) for ch in _FM_BANK_CHAPTERS):
        wanted = ", ".join(f"«{code}»" for code in _FM_SECTIONS)
        return {
            "known": False,
            "reason": f"в листе «cf_1_new» нет строк разделов {wanted} — потребность "
                      "на стройку и коммерцию не прочитать",
            "source": baseline.get("source"),
        }
    if finmodel:
        # Сколько нужно на стройку и коммерцию — план разделов финмодели с
        # месяца среза; тот же ряд идёт в водопад против остатка лимита
        # глав 2–3 сметы.
        cut_month = cut.replace(day=1)
        remaining_need = sum(
            float(amount or 0.0)
            for ch in _FM_BANK_CHAPTERS
            for month, amount in (sections[ch].get("monthly") or {}).items()
            if (monitor._day(month) or cut_month) >= cut_month)
    else:
        paid_delta = max(0.0, paid_actual - float(baseline["paid_at_baseline"] or 0.0))
        remaining_need = max(0.0, float(baseline["completion_need_at_baseline"] or 0.0)
                             - paid_delta)

    articles = baseline.get("articles") or {}
    if not articles:
        return {
            "known": False,
            "reason": "в финансовом baseline не найдена постатейная программа потребности",
            "source": baseline.get("source"),
        }

    # Для финмодели водопад — по главам 2–3 сметы: лимит главы минус всё
    # оплаченное по ней (резервы 2.8/2.9 уже внутри лимита главы 2) против
    # плана раздела финмодели по месяцам. Статьи финмодели на статьи сметы
    # один в один не ложатся, и постатейно здесь нечего считать.
    waterfall = _article_waterfall(
        _section_articles(sections, estimate, rss) if finmodel else articles,
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
    return {
        "known": True,
        "source": baseline["source"],
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
            "remaining": row["opening_limit"], "gap": row["unfunded_take"]}
            for row in waterfall["articles"]} if finmodel else None),
        "bank_remaining": waterfall["opening_bank_remaining"],
        "opening_article_deficit": waterfall["opening_article_deficit"],
        "remaining_need": remaining_need,
        "reserve": float(baseline.get("reserve") or 0.0),
        "reserve_parts": baseline.get("reserve_parts") or {},
        "reserve_names": baseline.get("reserve_names") or {},
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
        "deficit_ladder": _deficit_ladder(
            waterfall_book, float(baseline.get("reserve") or 0.0), book_remaining,
            unspent_view),
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


_FM_BANK_CHAPTERS = tuple(sorted({ch for ch, _, _ in _FM_SECTIONS.values()}))


def _section_articles(sections: dict[str, dict[str, Any]], estimate: dict[str, Any],
                      rss: Path) -> dict[str, dict[str, Any]]:
    """Разделы финмодели как строки водопада — по главам 2–3 сметы.

    Лимит — «Общая сметная стоимость» строки главы РСС (резервы внутри),
    «оплачено» — всё оплаченное по главе по РСС, потребность по месяцам — план
    раздела финмодели.
    """
    by_code = estimate.get("by_code") or {}
    out: dict[str, dict[str, Any]] = {}
    for chapter in _FM_BANK_CHAPTERS:
        section = sections[chapter]
        row = by_code.get(chapter) or {}
        out[chapter] = {
            "code": chapter, "chapter": chapter,
            "name": f"{section['label'].capitalize()} — {section['name']} (финмодель) "
                    f"против главы {chapter} сметы",
            "rss_limit": float(row.get("estimate") or 0.0),
            "paid_at_baseline": float(_paid_in_chapters(rss, estimate, (chapter,))["total"]),
            "has_programme": any((section.get("monthly") or {}).values()),
            "monthly_need": dict(section.get("monthly") or {}),
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
        money = (
            f"Деньги. По утверждённой модели достроить стоит "
            f"{_fmt_money(model_need)} (модель минус оплаченное). По РСС "
            f"осталось {_fmt_money(fuel)}: {_fmt_money(bank)} лимитов статей и "
            f"{_fmt_money(reserve)} резерва 2.8/2.9 — оставшийся лимит и есть "
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
                   "есть потребность в дофинансировании.")
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
