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
# Строки, которых может не быть в старых выгрузках: их отсутствие — «нет в
# бюджете», а не ошибка. «РАСХОДЫ» — итог бюджета месяца целиком; без главы 1
# и АХР сводка показывала 419 млн вместо 505 млн плана октября (владелец,
# 22.10.2026).
_EXTRA_ROWS = {
    "land": "Стоимость приобретения проекта",
    "admin": "Административно-хозяйственные расходы",
    "expenses": "РАСХОДЫ",
}

# Строки сводки: имя для человека, коды РСС факта, как строится план.
LINES = (
    {"key": "construction", "label": "Стройка и проектирование",
     "rss": "глава 2 без статьи 2.6"},
    {"key": "commercial", "label": "Коммерческие расходы",
     "rss": "статьи 3.1, 3.2, 3.4, 3.7"},
    {"key": "service", "label": "Служба заказчика, охрана и офис",
     "rss": "статья 2.6",
     "note": "в статье 2.6 РСС кроме службы заказчика и охраны оплачиваются зарплаты "
             "офиса и связь, которые бюджет относит к административно-хозяйственным "
             "расходам, поэтому оплачено здесь больше плана службы заказчика"},
)
_COMMERCIAL_CODES = ("3.1", "3.2", "3.4", "3.7")

# Статьи бюджета ↔ коды РСС (карта принята владельцем 20.10.2026 по сверке
# сентября). Статья бюджета ищется по точному имени строки внутри своей главы;
# «- Группа» в конце имени выгрузка дописывает сама. Код РСС относится к
# статье по самому длинному совпавшему коду: «Содержание стройплощадки»
# (2.2.1.10, 2.2.2.8) — в «Прочих работах», хотя лежит внутри 2.2.
ARTICLES = (
    {"key": "design", "label": "Проектные и изыскательские работы, авторский надзор",
     "line": "construction", "budget": ("Проектные и изыскательские работы, авторский надзор",),
     "rss": ("2.7",)},
    {"key": "objects", "label": "Основные объекты строительства", "line": "construction",
     "budget": ("Основные объекты строительства",), "rss": ("2.2", "2.3", "2.5")},
    {"key": "upkeep", "label": "Прочие работы и затраты (содержание стройплощадки)",
     "line": "construction", "budget": ("Прочие работы и затраты",),
     "rss": ("2.2.1.10", "2.2.2.8")},
    {"key": "networks", "label": "Наружные сети и сооружения", "line": "construction",
     "budget": ("Наружные сети и сооружения",), "rss": ("2.4",)},
    {"key": "temporary", "label": "Временные здания и сооружения", "line": "construction",
     "budget": ("Временные здания и сооружения",), "rss": ("2.1",)},
    {"key": "ads", "label": "Реклама и PR", "line": "commercial",
     "budget": ("Реклама и PR (КС)",), "rss": ("3.1",)},
    {"key": "selling", "label": "Расходы на продажу", "line": "commercial",
     "budget": ("Расходы на продажу (КС)",), "rss": ("3.2", "3.4")},
    {"key": "sales_staff", "label": "Персонал и офис отдела продаж", "line": "commercial",
     "budget": ("Расходы на персонал отдела продаж (КС)",
                "Расходы отдела продаж на содержание офиса (КС)"), "rss": ("3.7",)},
    {"key": "service", "label": "Служба заказчика, охрана и офис", "line": "service",
     "budget": ("Содержание службы заказчика",), "rss": ("2.6",)},
)
_ARTICLE = {article["key"]: article for article in ARTICLES}
# Глава бюджета, внутри которой ищется статья строки сводки.
_CHAPTER = {"construction": "construction_with_service",
            "service": "construction_with_service", "commercial": "commercial"}


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


def article_of(code: str) -> str | None:
    """Статья бюджета для кода РСС; None — платёж вне строк сводки или без статьи.

    Код внутри строки сводки, но не из карты (например, новая статья 2.8 РСС), —
    тоже None: такой платёж идёт строкой «без плана», а не в чужую статью.
    """
    code = str(code or "").strip().rstrip(".")
    if line_of(code) is None:
        return None
    best, size = None, -1
    for article in ARTICLES:
        for root in article["rss"]:
            if _under(code, root) and len(root) > size:
                best, size = article["key"], len(root)
    return best


def _label(value: Any) -> str:
    return _norm(re.sub(r"\s*-\s*Группа\s*$", "", str(value or "")))


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

    # Статьи — по точному имени, первая строка с этим именем после строки
    # своей главы. Группировка строк (outline) не нужна: без неё статьи те же.
    starts = {}
    for index, row in enumerate(rows):
        key = wanted.get(_norm(row[0] if row else "")) if index > header + 1 else None
        if key and key not in starts:
            starts[key] = index
    article_rows: dict[str, list[list[Any]]] = {}
    for article in ARTICLES:
        start = starts[_CHAPTER[article["line"]]]
        for name in article["budget"]:
            found = next((row for row in rows[start + 1:]
                          if row and _label(row[0]) == _norm(name)), None)
            if found is not None:
                article_rows.setdefault(article["key"], []).append(found)

    extra_names = {_norm(label): key for key, label in _EXTRA_ROWS.items()}
    extra_rows: dict[str, list[Any]] = {}
    for row in rows[header + 2:]:
        key = extra_names.get(_norm(row[0] if row else ""))
        if key and key not in extra_rows:
            extra_rows[key] = row

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
        articles = {}
        for key, found in article_rows.items():
            pair = {}
            for kind, column in block.items():
                cells = [_amount(row[column] if column < len(row) else None) for row in found]
                known = [value for value in cells if value is not None]
                pair[kind] = -sum(known) if known else None
            articles[key] = pair
        values["articles"] = articles
        extra = {}
        for key, row in extra_rows.items():
            pair = {}
            for kind, column in block.items():
                value = _amount(row[column] if column < len(row) else None)
                pair[kind] = -value if value is not None else None
            extra[key] = pair
        values["extra"] = extra
        out[month] = values
    return {"title": title, "months": out,
            "articles_missing": [article["label"] for article in ARTICLES
                                 if article["key"] not in article_rows]}


def store_budget(project: str, data: bytes, taken_at: Any,
                 filename: str = "") -> dict[str, Any]:
    """Положить план-факт БДДС снимком на дату загрузки."""
    day = monitor._iso(taken_at)
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", day):
        raise ValueError("дата бюджета нужна в виде ГГГГ-ММ-ДД")
    parsed = read_budget(data)
    months = sorted(month[:7] for month in parsed["months"])
    folder = monitor._project_dir(project) / "budget"
    folder.mkdir(parents=True, exist_ok=True)
    # Файл БДДС покрывает два-три месяца, и за прошлые периоды их догружают
    # пачкой в один день (владелец, 21.10.2026: файлы за апрель—сентябрь «не
    # принял, сказал что октябрь уже загружен»). Имя — дата загрузки и месяцы
    # файла: разные периоды одного дня не спорят, а тот же период заменяется,
    # прежний файл уходит в архив `.replaced/`, а не стирается.
    path = monitor._inside(folder, f"{day}_{months[0]}_{months[-1]}.xlsx")
    replaced = path.exists()
    if replaced:
        archive = folder / ".replaced"
        archive.mkdir(exist_ok=True)
        stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%S")
        path.rename(monitor._inside(archive, f"{path.stem}-{stamp}.xlsx"))
    path.write_bytes(data)
    return {"taken_at": day, "title": parsed["title"], "filename": filename,
            "months": months, "replaced": replaced}


def _period_end(path: Path) -> str:
    """Последний месяц файла: из имени, у старых файлов (имя — дата) — из книги."""
    parts = path.stem.split("_")
    if len(parts) == 3:
        return parts[2]
    try:
        return max(read_budget(path.read_bytes())["months"])[:7]
    except (ValueError, OSError):
        return ""


def _known_by(path: Path, upto: str) -> bool:
    """Бюджет годится для сводки на ``upto``.

    Загружен к этой дате — годится. Загружен позже, но все его месяцы уже
    прошли к месяцу сводки — тоже: это догруженный прошлый период, а не
    пересмотр текущего плана (владелец, 21.10.2026: бюджеты апреля—августа,
    загруженные в октябре, не попадали в сводку на дату раньше дня загрузки).
    """
    if path.stem[:10] <= upto:
        return True
    parts = path.stem.split("_")
    return len(parts) == 3 and parts[2] < upto[:7]


def _budget_files(project: str, upto: str) -> list[Path]:
    """Бюджеты, загруженные до ``upto``: сначала с более поздним периодом.

    Порядок — по месяцам файла, а не по дню загрузки: догруженный в октябре
    файл за июль—август не должен перекрывать сентябрь из файла за
    сентябрь—октябрь. При равном периоде свежее тот, что загружен позже.
    """
    folder = monitor._project_dir(project) / "budget"
    if not folder.exists():
        return []
    found = [path for path in folder.glob("*.xlsx") if _known_by(path, upto)]
    return sorted(found, key=lambda path: (_period_end(path), path.stem[:10]), reverse=True)


def _plan(project: str, month: str, upto: str) -> dict[str, Any] | None:
    """План месяца из свежайшего бюджета, в котором этот месяц есть."""
    for path in _budget_files(project, upto):
        parsed = read_budget(path.read_bytes())
        values = parsed["months"].get(month)
        if values is None:
            continue
        with_service = values["construction_with_service"]["plan"]
        service = values["service"]["plan"]
        construction = (None if with_service is None
                        else with_service - (service or 0.0))
        return {"file": path.stem[:10], "title": parsed["title"],
                "plan": {"construction": construction,
                         "commercial": values["commercial"]["plan"]},
                "articles": {key: pair["plan"] for key, pair in values["articles"].items()},
                "extra": {key: pair["plan"] for key, pair in values.get("extra", {}).items()},
                "extra_fact": {key: pair["fact"]
                               for key, pair in values.get("extra", {}).items()},
                "service": service,
                "articles_missing": parsed["articles_missing"]}
    return None


def month_fact(rss: Path, month: str, upto: datetime.date | None = None) -> dict[str, Any]:
    """Оплачено за месяц по строкам сводки — из реестра платежей РСС.

    ``upto`` — дата сводки: оплата позже неё в сводку не входит, даже если
    реестр её уже несёт (те же границы, что у таблицы статей).
    """
    payments = actuals.read_payments(rss)
    first = datetime.date.fromisoformat(month)
    sums = {line["key"]: 0.0 for line in LINES}
    for row in payments["rows"]:
        day = row.get("date")
        if not day or (day.year, day.month) != (first.year, first.month):
            continue
        if upto is not None and day > upto:
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
    fact = month_fact(rss, month, end)
    plan = _plan(project, month, end.isoformat())
    lines = []
    for line in LINES:
        spent = fact["fact"][line["key"]]
        planned = (plan or {}).get("plan", {}).get(line["key"])
        if line["key"] == "service":
            # План службы заказчика — её строка в бюджете (владелец, 22.10.2026:
            # «в службе заказчика на октябрь стоит 6,4 млн»), а не пусто.
            planned = (plan or {}).get("service")
        lines.append({**line, "plan": planned, "fact": spent,
                      "remaining": planned - spent if planned is not None else None})
    out = {"state": "ok" if plan else "partial", "month": month, "rss": rss.stem,
           "budget_file": (plan or {}).get("file"), "lines": lines,
           "last_payment": fact["last_payment"],
           "by_budget_article": month_articles(rss, month, end, plan),
           "trend": _trend(project, rss, end),
           "by_article": _by_article(rss, month, end),
           "recipients": _recipients(rss, month, end),
           "articles": _articles(project, end)}
    if not plan:
        out["reason"] = (f"Не загружен бюджет (план-факт БДДС), в котором есть "
                         f"{datetime.date.fromisoformat(month):%m.%Y} — плана на месяц нет.")
    return out


def _names(rss: Path) -> dict[str, str]:
    """Имя статьи РСС по коду — из листа расчёта стоимости, он хранит имена."""
    return {row["code"]: row["article"] for row in actuals.read_estimate(rss)["rows"]
            if row.get("article")}


def _row(label: str, planned: float | None, paid: float) -> dict[str, Any]:
    remaining = planned - paid if planned is not None else None
    return {"label": label, "plan": planned, "fact": paid, "remaining": remaining,
            "share": paid / planned if planned else None,
            "over": planned is not None and paid > planned + 0.5}


def month_articles(rss: Path, month: str, end: datetime.date,
                   plan: dict[str, Any] | None) -> dict[str, Any]:
    """Бюджет месяца по статьям: план БДДС, оплачено по РСС, остаток, процент.

    Оплаты кода РСС, которого нет в карте статей, — строкой «без плана» с кодом
    и именем статьи РСС: молча отнесённые в соседнюю статью, они исказили бы её
    процент. Статья, которой нет в бюджете, — план «нет в бюджете», не ноль.
    """
    names = _names(rss)
    paid: dict[str, float] = {article["key"]: 0.0 for article in ARTICLES}
    loose: dict[str, dict[str, Any]] = {}
    for row in _month_rows(rss, month, end):
        code = str(row.get("estimate_code") or "").strip().rstrip(".")
        amount = float(row.get("amount") or 0.0)
        key = article_of(code)
        if key:
            paid[key] += amount
            continue
        item = loose.setdefault(code, {
            "code": code, "line": line_of(code),
            "name": names.get(code) or row.get("article_name") or ""})
        item["amount"] = item.get("amount", 0.0) + amount
    planned = (plan or {}).get("articles") or {}
    missing = set((plan or {}).get("articles_missing") or [])
    chapters = []
    for line in LINES:
        rows = []
        for article in ARTICLES:
            if article["line"] != line["key"]:
                continue
            row = _row(article["label"], planned.get(article["key"]), paid[article["key"]])
            row.update({"key": article["key"], "rss": ", ".join(article["rss"]),
                        "in_budget": article["label"] not in missing})
            rows.append(row)
        for item in sorted(loose.values(), key=lambda x: -x["amount"]):
            if item["line"] == line["key"]:
                row = _row(f"Без плана: {item['code']} "
                           f"{item['name'] or 'статья без названия в РСС'}",
                           None, item["amount"])
                row.update({"key": "unplanned", "rss": item["code"], "in_budget": False})
                rows.append(row)
        # План главы — строка главы бюджета (тот же план, что у строк сводки),
        # а не сумма найденных статей: статья, которой нет в карте, не должна
        # молча уменьшать план главы. Расхождение — отдельной строкой.
        known = [row["plan"] for row in rows if row["plan"] is not None]
        chapter_plan = ((plan or {}).get("plan") or {}).get(line["key"])
        if chapter_plan is None and known:
            chapter_plan = sum(known)
        rest = chapter_plan - sum(known) if chapter_plan is not None else 0.0
        if abs(rest) > 0.5:
            row = _row("Прочие статьи бюджета главы (не разнесены по карте)", rest, 0.0)
            row.update({"key": "rest", "rss": "", "in_budget": True})
            rows.append(row)
        if not any(row["plan"] or row["fact"] for row in rows):
            continue
        total = _row(line["label"], chapter_plan, sum(row["fact"] for row in rows))
        chapters.append({"key": line["key"], "label": line["label"], "total": total,
                         "rows": rows})
    # Итог — стройка и коммерция: у службы заказчика факт РСС шире плана
    # (в 2.6 и офис), её процент с планом не сравним.
    comparable = [chapter["total"] for chapter in chapters
                  if chapter["key"] in {"construction", "commercial"}]
    known = [row["plan"] for row in comparable if row["plan"] is not None]
    total = _row("Итого стройка и коммерческие расходы", sum(known) if known else None,
                 sum(row["fact"] for row in comparable))
    # Остальной бюджет месяца: глава 1 (земля — глава 1 РСС) и АХР (в РСС их
    # нет: оплачено — «нет в РСС», а не ноль).
    extra = (plan or {}).get("extra") or {}
    # Оплачено по земле и АХР — факт самого БДДС, если он в файле есть: землю
    # платят мимо реестра РСС (владелец, 22.10.2026: «78,1 по факту оплачено,
    # а в бюджете стоит как не оплачено»). Без факта в файле земля — глава 1
    # РСС, АХР — «нет в РСС».
    booked = (plan or {}).get("extra_fact") or {}
    land_paid = sum(item["amount"] for code, item in loose.items()
                    if code == "1" or code.startswith("1."))
    for key, label, paid_here, source in (
            ("land", "Приобретение проекта (земля)",
             booked.get("land") if booked.get("land") is not None else land_paid,
             "факт БДДС" if booked.get("land") is not None else "глава 1"),
            ("admin", "Административно-хозяйственные расходы", booked.get("admin"),
             "факт БДДС" if booked.get("admin") is not None else "нет в РСС")):
        planned_here = extra.get(key)
        if planned_here is None and not paid_here:
            continue
        row = _row(label, planned_here, paid_here or 0.0)
        if paid_here is None:
            row.update({"fact": None, "remaining": None, "share": None, "over": False})
        row.update({"key": key, "rss": source, "in_budget": planned_here is not None})
        chapters.append({"key": key, "label": label, "total": row, "rows": [row]})
    # Всего — строка «РАСХОДЫ» бюджета (один источник с файлом), оплачено —
    # сумма строк: РСС по стройке, коммерции и службе заказчика, земля и АХР —
    # как выше.
    whole_plan = extra.get("expenses")
    if whole_plan is None:
        parts = [chapter["total"]["plan"] for chapter in chapters
                 if chapter["total"]["plan"] is not None]
        whole_plan = sum(parts) if parts else None
    whole_paid = sum(chapter["total"]["fact"] or 0.0 for chapter in chapters)
    whole = _row("Всего по бюджету месяца", whole_plan, whole_paid)
    rows = [row for chapter in chapters if chapter["key"] in {"construction", "commercial"}
            for row in chapter["rows"] if row["plan"] and row["key"] != "rest"]
    over = sorted((row for row in rows if row["over"]),
                  key=lambda row: row["remaining"])
    under = sorted((row for row in rows if not row["over"]),
                   key=lambda row: -row["remaining"])
    return {"month": month, "chapters": chapters, "total": total, "whole": whole,
            "overrun": [row["key"] for row in over],
            "largest_left": under[0]["key"] if under else None,
            "has_plan": bool(plan)}


def _month_shift(month: datetime.date, back: int) -> datetime.date:
    index = month.year * 12 + month.month - 1 - back
    return datetime.date(index // 12, index % 12 + 1, 1)


def _trend(project: str, rss: Path, end: datetime.date, months: int = 12) -> list[dict[str, Any]]:
    """План и оплачено по строкам сводки за последние месяцы (столбцы тренда).

    Окно — год: бюджеты с апреля должны быть видны и в октябрьской сводке.

    План месяца — из свежайшего бюджета, где этот месяц есть; факт — из того же
    РСС на конец периода. Нет бюджета на месяц — план None, а не ноль. Месяц до
    первой оплаты в реестре — факт None: реестр его не покрывает, это «нет
    данных», а не «ничего не платили». Месяцы без плана и без факта в начале
    ряда не показываются.
    """
    dated = [row["date"] for row in actuals.read_payments(rss)["rows"] if row.get("date")]
    first = min(dated).replace(day=1) if dated else None
    current = end.replace(day=1)
    out = []
    for back in range(months - 1, -1, -1):
        start = _month_shift(current, back)
        month = start.isoformat()
        plan = _plan(project, month, end.isoformat())
        covered = first is not None and start >= first
        fact = month_fact(rss, month, end)["fact"] if covered else {}
        point = {"month": month,
                 "plan": {key: (plan or {}).get("plan", {}).get(key)
                          for key in ("construction", "commercial")},
                 "fact": {key: fact.get(key) for key in ("construction", "commercial")}}
        if not out and all(value is None for part in ("plan", "fact")
                           for value in point[part].values()):
            continue
        out.append(point)
    return out


def _month_rows(rss: Path, month: str, end: datetime.date) -> list[dict[str, Any]]:
    first = datetime.date.fromisoformat(month)
    return [row for row in actuals.read_payments(rss)["rows"]
            if row.get("date") and first <= row["date"] <= end
            and line_of(row.get("estimate_code") or "")]


def _by_article(rss: Path, month: str, end: datetime.date) -> list[dict[str, Any]]:
    """Оплачено с начала месяца по статьям РСС внутри строк сводки.

    Имя статьи — из листа расчёта стоимости РСС: в реестре платежей колонка
    имени бывает пустой.
    """
    names = _names(rss)
    sums: dict[tuple[str, str], dict[str, Any]] = {}
    for row in _month_rows(rss, month, end):
        code = str(row.get("estimate_code") or "").rstrip(".")
        key = (line_of(code) or "", code)
        item = sums.setdefault(key, {
            "line": key[0], "code": code,
            "name": names.get(code) or row.get("article_name") or "статья без названия в РСС",
            "amount": 0.0})
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


# Главы бюджета месяца в порядке строк БДДС; итог — строка «РАСХОДЫ».
_MONTH_CHAPTERS = (
    ("land", "Глава 1 — приобретение проекта (земля)"),
    ("construction_with_service", "Глава 2 — стройка и проектирование, со службой заказчика"),
    ("commercial", "Глава 3 — коммерческие расходы"),
    ("admin", "Административно-хозяйственные расходы"),
)


def _month_chapters(values: dict[str, Any]) -> list[dict[str, Any]]:
    """План и факт закрытого месяца по главам БДДС и всего — как в самом файле.

    Владелец (22.10.2026) сверяет сентябрь по файлу: «расходы 221, из них
    2 глава 191, 1 глава 0,285, коммерческие 13,93, АХР 15,478».
    """
    extra = values.get("extra") or {}
    out = []
    for key, label in _MONTH_CHAPTERS + (("expenses", "Всего расходов по бюджету"),):
        pair = values.get(key) if key in _BUDGET_ROWS else extra.get(key)
        if not pair or (pair.get("plan") is None and pair.get("fact") is None):
            continue
        out.append({"key": key, "label": label, "plan": pair.get("plan"),
                    "fact": pair.get("fact")})
    return out


def _articles(project: str, end: datetime.date) -> dict[str, Any]:
    """Отклонения по статьям БДДС за прошлый месяц — последний закрытый.

    Статьи — те же, что у бюджета месяца (`ARTICLES`, по точному имени строки).
    Месяц — тот, что перед месяцем сводки, а не «последний, где в файле есть
    факт»: в октябрьской сводке стояла таблица за апрель, и её план читался как
    октябрьский (финансист, 21.10.2026: «неверный план апреля, не могу понять,
    откуда он подтянут»). Факта за прошлый месяц в файле нет — так и сказано.
    """
    files = _budget_files(project, end.isoformat())
    if not files:
        return {"known": False, "reason": "бюджет не загружен"}
    month = (end.replace(day=1) - datetime.timedelta(days=1)).replace(day=1).isoformat()
    label = f"{datetime.date.fromisoformat(month):%m.%Y}"
    # Свежайший бюджет, где этот месяц есть, — как у плана месяца (`_plan`).
    files = [path for path in files if month in read_budget(path.read_bytes())["months"]] or files
    parsed = read_budget(files[0].read_bytes())
    if month not in parsed["months"]:
        return {"known": False, "reason": f"в бюджете от {files[0].stem[:10]} нет месяца {label}"}
    for month in (month,):
        found = parsed["months"][month]["articles"]
        if not any(pair.get("fact") is not None for pair in found.values()):
            return {"known": False,
                    "reason": f"в бюджете от {files[0].stem[:10]} не заполнен факт за {label}"}
        rows = []
        # Месяц закрыт: у части статей факт есть. Пустая ячейка факта в
        # закрытом месяце бюджета значит «не платили», и это помечено.
        for key, pair in found.items():
            if pair.get("plan") is None and pair.get("fact") is None:
                continue
            fact = pair.get("fact") or 0.0
            rows.append({"article": _ARTICLE[key]["label"], "plan": pair.get("plan"),
                         "fact": pair.get("fact"), "fact_blank": pair.get("fact") is None,
                         "delta": fact - pair["plan"] if pair.get("plan") is not None else None})
        rows.sort(key=lambda row: -abs(row.get("delta") or 0.0))
        return {"known": True, "month": month, "file": files[0].stem[:10], "rows": rows,
                "chapters": _month_chapters(parsed["months"][month])}
    return {"known": False, "reason": "в бюджете нет месяца с фактом"}
