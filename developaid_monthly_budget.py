"""Бюджет месяца: план из план-фактного БДДС, факт — из реестра платежей РСС.

План-фактный анализ БДДС приходит раз в месяц файлом («План-фактный
анализ_<проект>_<дата>»). В нём по месяцам колонки «ПЛАН» и «ФАКТ», статьи —
строками с иерархией группировкой. Кодов РСС у статей нет, поэтому статьи
берутся по точному имени строки, а факт за месяц считается по явной карте
кодов РСС (решение владельца 20.10.2026):

* стройка — глава 2 РСС без статьи 2.6; в бюджете ей отвечает «Стоимость
  строительства и проектирования» без «Содержания службы заказчика»;
* служба заказчика — статья 2.6 РСС; в ней же лежат зарплаты офиса и связь,
  которые бюджет относит к административным расходам, поэтому с планом её не
  сравниваем;
* коммерческие расходы — статьи 3.1, 3.2, 3.4, 3.7 РСС. Услуги банка (3.5 —
  проценты по кредиту) и налоги (3.3) бюджет держит вне коммерческих.
"""

from __future__ import annotations

import datetime
import io
import re
from pathlib import Path
from typing import Any

import developaid_actuals as actuals
import developaid_monitor as monitor

_MONTHS = {name: number for number, name in enumerate(
    ("январь", "февраль", "март", "апрель", "май", "июнь", "июль", "август",
     "сентябрь", "октябрь", "ноябрь", "декабрь"), 1)}
_MONTH_HEADER = re.compile(r"^\s*([А-Яа-яЁё]+)\s+(\d{4})\s*$")

# Строки бюджета по точному имени. Расходы в файле со знаком минус.
_BUDGET_ROWS = {
    "construction_with_service": "Стоимость строительства и проектирования",
    "service": "Содержание службы заказчика",
    "commercial": "Коммерческие расходы",
}

# Строки сводки: имя для человека, коды РСС факта, как строится план.
LINES = (
    {"key": "construction", "label": "Стройка и проектирование",
     "rss": "глава 2 без статьи 2.6"},
    {"key": "commercial", "label": "Коммерческие расходы",
     "rss": "статьи 3.1, 3.2, 3.4, 3.7"},
    {"key": "service", "label": "Служба заказчика, охрана и офис",
     "rss": "статья 2.6"},
)
_COMMERCIAL_CODES = ("3.1", "3.2", "3.4", "3.7")


def _norm(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip().lower()


def _under(code: str, root: str) -> bool:
    return code == root or code.startswith(root + ".")


def line_of(code: str) -> str | None:
    """Строка сводки для кода РСС платежа; None — платёж вне трёх строк."""
    code = str(code or "").strip().rstrip(".")
    if _under(code, "2.6"):
        return "service"
    if code.startswith("2."):
        return "construction"
    if any(_under(code, root) for root in _COMMERCIAL_CODES):
        return "commercial"
    return None


def _amount(value: Any) -> float | None:
    if value is None or str(value).strip() == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def read_budget(data: bytes) -> dict[str, Any]:
    """Разобрать план-факт БДДС: план и факт нужных строк по месяцам.

    Чего не нашлось — ошибка с названием: молча пропущенная строка выглядела
    бы как нулевой план.
    """
    from openpyxl import load_workbook

    book = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    try:
        rows = [list(row) for row in book.worksheets[0].iter_rows(values_only=True)]
    finally:
        book.close()
    title = next((str(cell) for row in rows[:4] for cell in row if cell), "")

    header = None
    months: list[tuple[int, str]] = []
    for index, row in enumerate(rows[:20]):
        found = []
        for column, cell in enumerate(row):
            match = _MONTH_HEADER.match(str(cell or ""))
            if match and match.group(1).lower() in _MONTHS:
                month = datetime.date(int(match.group(2)),
                                      _MONTHS[match.group(1).lower()], 1)
                found.append((column, month.isoformat()))
        if found:
            header, months = index, found
            break
    if header is None or header + 1 >= len(rows):
        raise ValueError("в файле не нашлось шапки с месяцами («Сентябрь 2026»)")
    sub = rows[header + 1]
    # Блок месяца — от его подписи до подписи следующего; последний кончается
    # на «Итого», иначе план за все месяцы сошёл бы за план последнего.
    ends = [column for column, cell in enumerate(rows[header])
            if _norm(cell) == "итого" and column > months[-1][0]]
    bounds = [column for column, _ in months] + [ends[0] if ends else len(sub)]
    columns: dict[str, dict[str, int]] = {}
    for place, (start, month) in enumerate(months):
        block = {}
        for column in range(start, bounds[place + 1]):
            name = _norm(sub[column] if column < len(sub) else "")
            if name.startswith("план") and "plan" not in block:
                block["plan"] = column
            elif name == "факт" and "fact" not in block:
                block["fact"] = column
        if set(block) != {"plan", "fact"}:
            raise ValueError(f"у месяца {month[:7]} нет колонок «ПЛАН» и «ФАКТ»")
        columns[month] = block

    wanted = {_norm(label): key for key, label in _BUDGET_ROWS.items()}
    found_rows: dict[str, list[Any]] = {}
    for row in rows[header + 2:]:
        key = wanted.get(_norm(row[0] if row else ""))
        if key is None:
            continue
        if key in found_rows:
            raise ValueError(f"строка «{_BUDGET_ROWS[key]}» встречается дважды")
        found_rows[key] = row
    lost = [label for key, label in _BUDGET_ROWS.items() if key not in found_rows]
    if lost:
        raise ValueError("в бюджете нет строк: " + ", ".join(f"«{x}»" for x in lost))

    out: dict[str, dict[str, dict[str, float | None]]] = {}
    for month, block in columns.items():
        values = {}
        for key, row in found_rows.items():
            pair = {}
            for kind, column in block.items():
                value = _amount(row[column] if column < len(row) else None)
                # Расход в файле со знаком минус; наружу — сколько потрачено.
                pair[kind] = -value if value is not None else None
            values[key] = pair
        out[month] = values
    return {"title": title, "months": out}


def store_budget(project: str, data: bytes, taken_at: Any,
                 filename: str = "") -> dict[str, Any]:
    """Положить план-факт БДДС снимком на дату загрузки."""
    day = monitor._iso(taken_at)
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", day):
        raise ValueError("дата бюджета нужна в виде ГГГГ-ММ-ДД")
    parsed = read_budget(data)
    folder = monitor._project_dir(project) / "budget"
    folder.mkdir(parents=True, exist_ok=True)
    path = monitor._inside(folder, f"{day}.xlsx")
    if path.exists():
        raise FileExistsError(f"бюджет на {day} уже загружен")
    path.write_bytes(data)
    return {"taken_at": day, "title": parsed["title"], "filename": filename,
            "months": sorted(month[:7] for month in parsed["months"])}


def _plan(project: str, month: str, upto: str) -> dict[str, Any] | None:
    """План месяца из свежайшего бюджета, в котором этот месяц есть."""
    folder = monitor._project_dir(project) / "budget"
    if not folder.exists():
        return None
    for path in sorted(folder.glob("*.xlsx"), reverse=True):
        if path.stem > upto:
            continue
        parsed = read_budget(path.read_bytes())
        values = parsed["months"].get(month)
        if values is None:
            continue
        with_service = values["construction_with_service"]["plan"]
        service = values["service"]["plan"]
        construction = (None if with_service is None
                        else with_service - (service or 0.0))
        return {"file": path.stem, "title": parsed["title"],
                "plan": {"construction": construction,
                         "commercial": values["commercial"]["plan"]}}
    return None


def month_fact(rss: Path, month: str) -> dict[str, Any]:
    """Оплачено за месяц по строкам сводки — из реестра платежей РСС."""
    payments = actuals.read_payments(rss)
    first = datetime.date.fromisoformat(month)
    sums = {line["key"]: 0.0 for line in LINES}
    for row in payments["rows"]:
        day = row.get("date")
        if not day or (day.year, day.month) != (first.year, first.month):
            continue
        key = line_of(row.get("estimate_code") or "")
        if key:
            sums[key] += float(row.get("amount") or 0.0)
    return {"fact": sums, "last_payment": monitor._iso(payments.get("last")) or None,
            "undated": float(payments.get("undated") or 0.0)}


def month_budget(project: str, end: datetime.date) -> dict[str, Any]:
    """Строки бюджета месяца, в котором лежит ``end``: план, оплачено, остаток."""
    month = end.replace(day=1).isoformat()
    rss = monitor._latest(project, "estimate", ".xlsx", end.isoformat())
    if rss is None:
        return {"state": "missing",
                "reason": "Не загружен ни один отчёт РСС с реестром платежей "
                          f"на {end:%d.%m.%Y}."}
    fact = month_fact(rss, month)
    plan = _plan(project, month, end.isoformat())
    lines = []
    for line in LINES:
        spent = fact["fact"][line["key"]]
        planned = (plan or {}).get("plan", {}).get(line["key"])
        lines.append({**line, "plan": planned, "fact": spent,
                      "remaining": planned - spent if planned is not None else None})
    out = {"state": "ok" if plan else "partial", "month": month, "rss": rss.stem,
           "budget_file": (plan or {}).get("file"), "lines": lines,
           "last_payment": fact["last_payment"],
           "trend": _trend(project, rss, end),
           "by_article": _by_article(rss, month, end),
           "recipients": _recipients(rss, month, end),
           "articles": _articles(project, end)}
    if not plan:
        out["reason"] = (f"Не загружен бюджет (план-факт БДДС), в котором есть "
                         f"{datetime.date.fromisoformat(month):%m.%Y} — плана на месяц нет.")
    return out


def _month_shift(month: datetime.date, back: int) -> datetime.date:
    index = month.year * 12 + month.month - 1 - back
    return datetime.date(index // 12, index % 12 + 1, 1)


def _trend(project: str, rss: Path, end: datetime.date, months: int = 6) -> list[dict[str, Any]]:
    """План и оплачено по строкам сводки за последние месяцы (столбцы тренда).

    План месяца — из свежайшего бюджета, где этот месяц есть; факт — из того же
    РСС на конец периода. Нет бюджета на месяц — план None, а не ноль.
    """
    current = end.replace(day=1)
    out = []
    for back in range(months - 1, -1, -1):
        month = _month_shift(current, back).isoformat()
        plan = _plan(project, month, end.isoformat())
        fact = month_fact(rss, month)["fact"]
        out.append({"month": month,
                    "plan": {key: (plan or {}).get("plan", {}).get(key)
                             for key in ("construction", "commercial")},
                    "fact": {key: fact[key] for key in ("construction", "commercial")}})
    return out


def _month_rows(rss: Path, month: str, end: datetime.date) -> list[dict[str, Any]]:
    first = datetime.date.fromisoformat(month)
    return [row for row in actuals.read_payments(rss)["rows"]
            if row.get("date") and first <= row["date"] <= end
            and line_of(row.get("estimate_code") or "")]


def _by_article(rss: Path, month: str, end: datetime.date) -> list[dict[str, Any]]:
    """Оплачено с начала месяца по статьям РСС внутри строк сводки."""
    sums: dict[tuple[str, str], dict[str, Any]] = {}
    for row in _month_rows(rss, month, end):
        code = str(row.get("estimate_code") or "").rstrip(".")
        key = (line_of(code) or "", code)
        item = sums.setdefault(key, {"line": key[0], "code": code,
                                     "name": row.get("article_name") or "", "amount": 0.0})
        item["amount"] += float(row.get("amount") or 0.0)
    return sorted(sums.values(), key=lambda item: -item["amount"])


def _recipients(rss: Path, month: str, end: datetime.date, top: int = 8) -> list[dict[str, Any]]:
    """Крупнейшие получатели оплат с начала месяца (контрагенты реестра РСС)."""
    sums: dict[str, dict[str, Any]] = {}
    for row in _month_rows(rss, month, end):
        name = str(row.get("contractor") or "").strip() or "не указан"
        item = sums.setdefault(name, {"name": name, "amount": 0.0, "lines": set()})
        item["amount"] += float(row.get("amount") or 0.0)
        item["lines"].add(line_of(row.get("estimate_code") or ""))
    out = sorted(sums.values(), key=lambda item: -item["amount"])[:top]
    for item in out:
        item["lines"] = sorted(item["lines"])
    return out


def read_articles(data: bytes) -> dict[str, Any]:
    """Статьи БДДС третьего уровня под стройкой и коммерцией: план и факт по месяцам.

    Уровень берётся из группировки строк (outline) — по ней бюджет и собран.
    Без группировки статьи не выделить, и это сказано, а не угадано по отступам.
    """
    from openpyxl import load_workbook

    book = load_workbook(io.BytesIO(data), data_only=True)
    sheet = book.worksheets[0]
    parsed = read_budget(data)
    header = None
    for index in range(1, 21):
        if any(_MONTH_HEADER.match(str(sheet.cell(index, c).value or ""))
               for c in range(1, sheet.max_column + 1)):
            header = index
            break
    levels = [sheet.row_dimensions[r].outline_level for r in range(1, sheet.max_row + 1)]
    if header is None or not any(levels):
        return {"known": False, "reason": "в файле бюджета нет группировки строк по уровням"}
    columns = {}
    for column in range(1, sheet.max_column + 1):
        match = _MONTH_HEADER.match(str(sheet.cell(header, column).value or ""))
        if match and match.group(1).lower() in _MONTHS:
            month = datetime.date(int(match.group(2)), _MONTHS[match.group(1).lower()], 1)
            columns[month.isoformat()] = column
    groups = {_norm(_BUDGET_ROWS["construction_with_service"]): "construction",
              _norm(_BUDGET_ROWS["commercial"]): "commercial"}
    current, group_level = None, None
    out: dict[str, list[dict[str, Any]]] = {month: [] for month in columns}
    for r in range(header + 2, sheet.max_row + 1):
        name = _norm(sheet.cell(r, 1).value)
        level = sheet.row_dimensions[r].outline_level
        if name in groups:
            current, group_level = groups[name], level
            continue
        if current is None:
            continue
        if level <= group_level:
            current = None
            continue
        if level != group_level + 1 or not name:
            continue
        for month, column in columns.items():
            # Подписи «ПЛАН»/«ФАКТ» стоят в той же раскладке, что у read_budget.
            plan = _amount(sheet.cell(r, column).value)
            fact = _amount(sheet.cell(r, column + 1).value)
            if plan is None and fact is None:
                continue
            out[month].append({"line": current, "article": str(sheet.cell(r, 1).value).strip(),
                               "plan": -plan if plan is not None else None,
                               "fact": -fact if fact is not None else None})
    return {"known": True, "title": parsed["title"], "months": out}


def _articles(project: str, end: datetime.date) -> dict[str, Any]:
    """Отклонения по статьям БДДС в последнем месяце, где бюджет уже несёт факт."""
    folder = monitor._project_dir(project) / "budget"
    files = sorted((p for p in folder.glob("*.xlsx") if p.stem <= end.isoformat()),
                   reverse=True) if folder.exists() else []
    if not files:
        return {"known": False, "reason": "бюджет не загружен"}
    got = read_articles(files[0].read_bytes())
    if not got.get("known"):
        return got
    for month in sorted(got["months"], reverse=True):
        rows = got["months"][month]
        if any(row.get("fact") is not None for row in rows):
            # Месяц закрыт: у части статей факт есть. Пустая ячейка факта в
            # закрытом месяце бюджета значит «не платили», и это помечено.
            for row in rows:
                row["article"] = re.sub(r"\s*-\s*Группа$", "", row["article"])
                row["fact_blank"] = row.get("fact") is None
                fact = row.get("fact") or 0.0
                row["delta"] = (fact - row["plan"]) if row.get("plan") is not None else None
            rows.sort(key=lambda row: -abs(row.get("delta") or 0.0))
            return {"known": True, "month": month, "file": files[0].stem, "rows": rows}
    return {"known": False, "reason": "в бюджете ещё нет месяца с фактом"}
