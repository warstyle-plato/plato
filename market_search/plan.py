"""План продаж из книги ПЛАТО: помесячно, отдельно факт и отдельно план.

Отчёт о рынке отвечает на вопрос «как у соседей». Второй вопрос, ради которого
его читают, — «а как у нас против того, что обещали». Ответ на него лежит не в
источнике, а в собственной финансовой модели проекта, на листе «План продаж_утв»:
там помесячно и штуки, и метры, и цена, а строки помечены «факт», «оперфакт»
или ничем — последнее и означает план.

Разбор нарочно терпимый к форме. Книга живая, её правят руками: лист могут
переименовать, столбцы сдвинуть, шапку поставить на другую строку. Поэтому
столбцы ищутся по подписям, а не по номерам, и любая непонятая строка
пропускается молча — но если не нашлось ни одной, разбор говорит об этом вслух,
а не возвращает пустой график.

Факт из книги и факт из «Пульса» — разные числа, и это нормально: банк считает
ДДУ по дате регистрации, книга — по дате сделки, между ними недели. Показывать
их надо рядом, а не выбирать одно.
"""

from __future__ import annotations

import io
import re
from typing import Any


SHEET_HINTS = ("план продаж_утв", "план продаж утв", "план продаж")
FACT_MARKS = ("факт", "оперфакт")


class PlanNotFound(ValueError):
    """Книга разобрана, но плана продаж в ней не нашлось."""


def _norm(value: Any) -> str:
    return " ".join(str(value or "").split()).casefold()


def _month(value: Any) -> str | None:
    if hasattr(value, "year") and hasattr(value, "month"):
        return f"{value.year:04d}-{value.month:02d}"
    text = str(value or "").strip()
    match = re.match(r"^(\d{4})-(\d{2})", text)
    if match:
        return f"{match.group(1)}-{match.group(2)}"
    match = re.match(r"^(\d{2})\.(\d{2})\.(\d{4})", text)
    if match:
        return f"{match.group(3)}-{match.group(2)}"
    return None


def _number(value: Any) -> float | None:
    if value in (None, "", "-"):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).replace("\xa0", "").replace(" ", "").replace(",", ".")
    try:
        return float(text)
    except ValueError:
        return None


def _pick_sheet(book: Any) -> Any:
    for hint in SHEET_HINTS:
        for name in book.sheetnames:
            if _norm(name) == hint:
                return book[name]
    for name in book.sheetnames:
        if "план" in _norm(name) and "прод" in _norm(name):
            return book[name]
    raise PlanNotFound("В книге нет листа с планом продаж")


def _columns(rows: list[tuple]) -> tuple[int, dict[str, int]]:
    """Найти строку шапки и колонки по подписям, а не по номерам."""
    for index, row in enumerate(rows[:12]):
        # Подписи повторяются: сначала блок «ВСЕГО», за ним такие же колонки по
        # каждому корпусу. Нужен первый набор, поэтому запоминается первое
        # вхождение, а не последнее — иначе отчёт показывал бы один корпус
        # вместо всего проекта, и разница не бросалась бы в глаза.
        marks: dict[str, int] = {}
        for position, cell in enumerate(row):
            label = _norm(cell)
            if label and label not in marks:
                marks[label] = position
        units = next((p for label, p in marks.items() if label == "шт"), None)
        area = next((p for label, p in marks.items() if label in ("кв.м.", "кв.м", "м2", "м²")), None)
        price = next((p for label, p in marks.items() if label.startswith("руб/кв")), None)
        if units is not None and area is not None:
            return index, {"units": units, "area": area, "price": price if price is not None else -1}
    raise PlanNotFound("В листе плана не найдены колонки «шт» и «кв.м.»")


def parse_plan(data: bytes) -> dict[str, Any]:
    """Помесячный план и факт из книги ПЛАТО."""
    try:
        import openpyxl
    except ImportError as exc:  # pragma: no cover
        raise PlanNotFound("Не установлен openpyxl — книга не читается") from exc

    try:
        book = openpyxl.load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    except Exception as exc:
        raise PlanNotFound(f"Файл не читается как книга Excel: {exc}") from exc

    sheet = _pick_sheet(book)
    rows = [row for row in sheet.iter_rows(values_only=True)]
    header, columns = _columns(rows)

    months: list[dict[str, Any]] = []
    project = None
    for row in rows[header + 1:]:
        if not row:
            continue
        month = _month(row[0])
        if not month:
            # Строка «ИТОГО» и прочие сводки датой не помечены — они не месяц.
            continue
        kind = _norm(row[1] if len(row) > 1 else "")
        units = _number(row[columns["units"]]) if columns["units"] < len(row) else None
        area = _number(row[columns["area"]]) if columns["area"] < len(row) else None
        price = None
        if 0 <= columns["price"] < len(row):
            price = _number(row[columns["price"]])
        if units is None and area is None:
            continue
        months.append({
            "month": month,
            "kind": "fact" if any(mark in kind for mark in FACT_MARKS) else "plan",
            "units": None if units is None else round(units, 1),
            "area": None if area is None else round(area, 1),
            "price": None if not price else int(round(price)),
        })

    if not months:
        raise PlanNotFound("В листе плана нет ни одной строки с датой и количеством")

    for name in book.sheetnames:
        if _norm(name) == "отчет":
            for row in book[name].iter_rows(min_row=1, max_row=4, values_only=True):
                for position, cell in enumerate(row or ()):
                    if _norm(cell) == "проект:" and position + 1 < len(row):
                        project = str(row[position + 1] or "").strip() or None
            break

    facts = [m for m in months if m["kind"] == "fact"]
    plans = [m for m in months if m["kind"] == "plan"]
    return {
        "project": project,
        "months": months,
        "fact_until": facts[-1]["month"] if facts else None,
        "plan_from": plans[0]["month"] if plans else None,
        "sheet": sheet.title,
    }


def compare(plan: dict[str, Any], market: list[dict[str, Any]]) -> dict[str, Any]:
    """Сопоставить план, свой факт и факт источника по общим месяцам.

    Факт книги и факт «Пульса» расходятся на срок регистрации ДДУ, поэтому
    сравниваются не они между собой, а каждый — с планом.
    """
    by_month = {row["month"]: row for row in plan.get("months") or []}
    source = {row["month"]: row for row in market or []}
    months = sorted(set(by_month) | set(source))
    rows = []
    for month in months:
        own = by_month.get(month) or {}
        rows.append({
            "month": month,
            "kind": own.get("kind"),
            "plan_units": own.get("units") if own.get("kind") == "plan" else None,
            "fact_units": own.get("units") if own.get("kind") == "fact" else None,
            "source_units": (source.get(month) or {}).get("sold"),
            "plan_price": own.get("price"),
        })
    done = [r for r in rows if r["fact_units"] is not None]
    ahead = [r for r in rows if r["plan_units"] is not None]
    return {
        "rows": rows,
        "fact_months": len(done),
        "plan_months": len(ahead),
        "fact_total": round(sum(r["fact_units"] or 0 for r in done), 1),
        "plan_total": round(sum(r["plan_units"] or 0 for r in ahead), 1),
    }
