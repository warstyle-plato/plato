"""Факт действующего проекта: РСС, реестр договоров и сводка одного с другим.

Инвестиционный анализ считает проект с нуля. Действующий проект такого не
позволяет: полтора года уже случились, и модель обязана начинать не с нулевых
остатков, а с того, что произошло. Здесь живёт чтение этого «произошло».

Источников два, и они разные по природе.

**РСС** — банковская форма по 214-ФЗ (п. 3.3.8 НКЛ). Даёт четыре колонки на
каждую статью: смета, заключено договоров, оплачено, выполнено по принятым
КС. Это единственное место, где видно физическое выполнение.

**Реестр договоров** финансовой модели — построчный факт: договор, платёж,
акт, и при каждой строке **обе** кодировки сразу, «Код банк» (код РСС) и код
БДДС. Перекодировка между РСС и ДДС уже существует внутри этого листа, и
изобретать её не надо: 3 760 строк дают 97 связок.

Из чего собраны правила ниже.

- **Код РСС — ключ сшивки, и он пишется с точкой на конце.** «1.1.» и «1.1» —
  один и тот же код; сравнивать надо нормализованные.

- **Иерархия из кода не выводится.** В РСС Гродненской подстроки внутренних
  инженерных систем пронумерованы `2.2.3.1`…`2.2.3.5` под заголовком `2.3.`
  (суммы при этом сходятся — описка в кодах, не в деньгах). Обход «по префиксу
  кода» отнесёт их к главе 2.2 и получит двойной счёт, а `2.3` объявит листом.
  Дерево поэтому строится по порядку строк и глубине кода: родитель — ближайшая
  строка выше с меньшим числом сегментов. Итог берётся из объявленной строки
  «Всего инвестиционные расходы», а не суммированием листа.

- **Сравнивать уровень с уровнем.** Строка РСС уже агрегат, а реестр разносит
  платёж по листьям — и прямое сличение кода с кодом показывает главу 2 как
  расхождение на 1,9 млрд ₽ там, где расхождения нет вовсе. Платежи реестра
  поднимаются по дереву, и на каждом уровне сравниваются сопоставимые суммы.

- **Число в выгрузке бывает текстом.** «43 212,18» с неразрывным пробелом и
  запятой — обычное дело для 1С. `float()` на таком падает, и падает он не при
  разборе, а посреди свода.

- **Дата акта живёт не в колонке даты.** «Отчетный период» реестра выполненных
  работ заполнен у 47 строк из 1451; настоящая дата — внутри «№ и дата»,
  строкой вида «516 от 19.10.2024». Разбирать её надо от слова «от», а не
  первым похожим на дату куском: номер акта сам полон цифр с точками, и
  наивный поиск даёт «от 45485» и год 204.

- **Не всё, что названо выполнением, является актом КС.** Из 3 432,5 млн ₽
  «выполнено» 881,2 млн — платежи в ДГИ за ВРИ, комиссии банка и ФОТ, у них
  дат актов нет и быть не может. Физическое выполнение считается по датируемой
  части, а недатируемая уходит в деньги; смешивать их — значит показать
  строительную готовность там, где её нет.

- **Расхождение источников — результат, а не помеха.** Сводка ничего не
  подгоняет и не выбирает «более правильный» файл. Она печатает обе цифры и
  разницу: на Гродненской это 2,27 млрд ₽ по смете и 454,9 млн ₽ по оплате, и
  ровно это надо увидеть, а не спрятать.
"""

from __future__ import annotations

import datetime
import re
from pathlib import Path
from typing import Any

# Лист РСС и его колонки. Заголовок стоит на девятой строке, данные ниже;
# первый столбец несёт код, четвёртый — статью затрат.
_ESTIMATE_SHEET = "Расчет стоимости строительства"
_ESTIMATE_TOTAL_LABEL = "всего инвестиционные расходы"
_ESTIMATE_COLUMNS = {
    "code": 0,
    "article": 3,
    "estimate": 4,
    "contracted": 5,
    "paid": 6,
    "completed": 10,  # блок «по объекту»: выполнено по принятым КС
}

# Реестр договоров финансовой модели. Заголовок на двенадцатой строке.
_REGISTER_SHEET = "факт"
_REGISTER_HEADER_ROW = 12
_REGISTER_COLUMNS = {
    "project": 1,
    "company": 2,
    "kind": 3,
    "counterparty": 4,
    "contract": 5,
    "estimate_code": 10,   # «Код банк» — код РСС
    "bdds_code": 12,
    "article": 13,
    "contract_amount": 15,
    "plan_or_fact": 17,
    "paid_date": 18,
    "paid_amount": 19,
    "act_date": 20,
    "act_amount": 21,
    "object": 22,
    "limit": 23,
}

# Реестр актов РСС. Заголовок на шестой строке, данные с девятой.
_WORKS_SHEET = "Реестр выполненных работ"
_WORKS_FIRST_ROW = 9
_WORKS_COLUMNS = {
    "document": 1,
    "number_and_date": 2,
    "period": 3,
    "object": 4,
    "estimate_code": 6,
    "amount": 8,
    "contractor": 10,
}

# Строка «выполнено», у которой нет и не может быть акта КС: плата городу,
# комиссии банка, фонд оплаты труда. В физическое выполнение они не идут.
_NON_CONSTRUCTION_MARKERS = ("уфк", "дги", "сбербанк", "фот")

_EXCEL_EPOCH = datetime.datetime(1899, 12, 30)


def _money(value: Any) -> float:
    """Число из выгрузки. 1С отдаёт «43 212,18» строкой — это тоже число."""
    if value is None:
        return 0.0
    if isinstance(value, bool):
        return 0.0
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).replace("\xa0", "").replace(" ", "").replace(",", ".")
    try:
        return float(text)
    except ValueError:
        return 0.0


def _code(value: Any) -> str:
    """Код РСС без хвостовой точки: «1.1.» и «1.1» — один код."""
    if value is None:
        return ""
    text = str(value).strip()
    if not text or text.startswith("#"):
        return ""
    text = re.sub(r"\.+$", "", text)
    return text if re.fullmatch(r"\d+(\.\d+)*", text) else ""


def _date(value: Any) -> datetime.date | None:
    """Дата из ячейки, серийного номера или строки «№ … от 19.10.2024».

    Разбор идёт от слова «от»: номер акта сам полон цифр с точками, и поиск
    первого похожего на дату куска находит номер, а не дату.
    """
    if isinstance(value, datetime.datetime):
        return value.date()
    if isinstance(value, datetime.date):
        return value
    if isinstance(value, (int, float)) and 10_000 < float(value) < 80_000:
        return (_EXCEL_EPOCH + datetime.timedelta(days=int(value))).date()
    if not isinstance(value, str):
        return None
    tail = re.split(r"\bот\b", value)[-1].strip()
    match = re.match(r"(\d{1,2})[.\-/](\d{1,2})[.\-/](\d{2,4})", tail)
    if match:
        day, month, year = (int(part) for part in match.groups())
        if year < 100:
            year += 2000
        # Год «204» — описка источника, а не 204-й год: такую дату честнее
        # не признать, чем поставить месяц в 204-12 и увести его из свода.
        if not 2000 <= year <= 2100:
            return None
        try:
            return datetime.date(year, month, day)
        except ValueError:
            return None
    if re.fullmatch(r"\d{5}", tail):
        return (_EXCEL_EPOCH + datetime.timedelta(days=int(tail))).date()
    return None


def _month(value: datetime.date | None) -> str:
    return value.strftime("%Y-%m") if value else ""


def _normalized(text: Any) -> str:
    return re.sub(r"\s+", " ", str(text or "").replace("ё", "е")).strip().lower()


def _sheet(path: str | Path, name: str) -> Any:
    from openpyxl import load_workbook

    workbook = load_workbook(Path(path), read_only=True, data_only=True)
    try:
        if name not in workbook.sheetnames:
            raise KeyError(f"в книге нет листа «{name}»: {workbook.sheetnames}")
        for row in workbook[name].iter_rows(values_only=True):
            yield row
    finally:
        workbook.close()


def read_estimate(path: str | Path) -> dict[str, Any]:
    """РСС: статьи с кодами и четыре колонки факта по каждой.

    Итог не суммируется — он объявлен строкой «Всего инвестиционные расходы».
    Суммировать лист нельзя: в нём и главы, и подстроки глав.
    """
    rows: list[dict[str, Any]] = []
    total: dict[str, float] = {}
    for row in _sheet(path, _ESTIMATE_SHEET):
        def cell(field: str) -> Any:
            index = _ESTIMATE_COLUMNS[field]
            return row[index] if index < len(row) else None

        article = cell("article")
        if total == {} and _normalized(article).startswith(_ESTIMATE_TOTAL_LABEL):
            total = {
                field: _money(cell(field))
                for field in ("estimate", "contracted", "paid", "completed")
            }
            continue
        code = _code(cell("code"))
        if not code:
            continue
        rows.append({
            "code": code,
            "article": str(article or "").strip(),
            "depth": code.count(".") + 1,
            **{field: _money(cell(field))
               for field in ("estimate", "contracted", "paid", "completed")},
        })
    _link_parents(rows)
    return {"rows": rows, "total": total,
            "by_code": {row["code"]: row for row in rows}}


def _link_parents(rows: list[dict[str, Any]]) -> None:
    """Родитель — ближайшая строка выше с меньшим числом сегментов кода.

    Порядок строк здесь надёжнее самого кода: в РСС Гродненской подстроки
    внутренних инженерных систем пронумерованы `2.2.3.x` под заголовком `2.3.`,
    и по префиксу они уехали бы в другую главу, а `2.3` осталось бы листом.
    """
    stack: list[dict[str, Any]] = []
    for row in rows:
        while stack and stack[-1]["depth"] >= row["depth"]:
            stack.pop()
        row["parent"] = stack[-1]["code"] if stack else ""
        stack.append(row)
    parents = {row["parent"] for row in rows if row["parent"]}
    for row in rows:
        row["is_leaf"] = row["code"] not in parents


def _rolled_up(rows: list[dict[str, Any]], amounts: dict[str, float]) -> dict[str, float]:
    """Поднять суммы реестра по дереву РСС: лист даёт вклад всем родителям."""
    parent_of = {row["code"]: row["parent"] for row in rows}
    rolled = {row["code"]: 0.0 for row in rows}
    for code, amount in amounts.items():
        cursor = code
        seen: set[str] = set()
        while cursor and cursor not in seen:
            seen.add(cursor)
            if cursor in rolled:
                rolled[cursor] += amount
            cursor = parent_of.get(cursor, "")
    return rolled


def read_register(path: str | Path) -> dict[str, Any]:
    """Реестр договоров финансовой модели: платежи, акты и обе кодировки."""
    rows: list[dict[str, Any]] = []
    unmapped_paid = 0.0
    for index, row in enumerate(_sheet(path, _REGISTER_SHEET), 1):
        if index <= _REGISTER_HEADER_ROW:
            continue

        def cell(field: str) -> Any:
            position = _REGISTER_COLUMNS[field]
            return row[position] if position < len(row) else None

        raw_code = cell("estimate_code")
        if raw_code is None and cell("bdds_code") is None:
            continue
        code = _code(raw_code)
        paid = _money(cell("paid_amount"))
        if not code:
            unmapped_paid += paid
        rows.append({
            "estimate_code": code,
            "raw_estimate_code": str(raw_code or "").strip(),
            "bdds_code": str(cell("bdds_code") or "").strip(),
            "article": str(cell("article") or "").strip(),
            "counterparty": str(cell("counterparty") or "").strip(),
            "kind": str(cell("kind") or "").strip(),
            "object": str(cell("object") or "").strip(),
            "plan_or_fact": _normalized(cell("plan_or_fact")),
            "contract_amount": _money(cell("contract_amount")),
            "limit": _money(cell("limit")),
            "paid_amount": paid,
            "paid_date": _date(cell("paid_date")),
            "act_amount": _money(cell("act_amount")),
            "act_date": _date(cell("act_date")),
        })
    crosswalk: dict[str, set[str]] = {}
    for item in rows:
        if item["estimate_code"] and item["bdds_code"]:
            crosswalk.setdefault(item["estimate_code"], set()).add(item["bdds_code"])
    return {
        "rows": rows,
        "crosswalk": {code: sorted(codes) for code, codes in crosswalk.items()},
        "unmapped_paid": unmapped_paid,
        "paid": sum(item["paid_amount"] for item in rows),
        "accepted": sum(item["act_amount"] for item in rows),
    }


def read_completed_works(path: str | Path) -> dict[str, Any]:
    """Реестр актов РСС: суммы, коды и дата, вынутая из «№ и дата».

    Строки без даты не выбрасываются: их сумма объявляется отдельно, иначе
    физическое выполнение молча недосчитается. Строки, которые актом КС не
    являются (плата городу, комиссии банка, ФОТ), помечаются здесь же.
    """
    rows: list[dict[str, Any]] = []
    for index, row in enumerate(_sheet(path, _WORKS_SHEET), 1):
        if index < _WORKS_FIRST_ROW:
            continue

        def cell(field: str) -> Any:
            position = _WORKS_COLUMNS[field]
            return row[position] if position < len(row) else None

        amount = _money(cell("amount"))
        if not amount and cell("document") is None:
            continue
        contractor = _normalized(cell("contractor"))
        rows.append({
            "code": _code(cell("estimate_code")),
            "document": str(cell("document") or "").strip(),
            "contractor": str(cell("contractor") or "").strip(),
            "object": str(cell("object") or "").strip(),
            "amount": amount,
            "date": _date(cell("number_and_date")) or _date(cell("period")),
            "construction": not any(mark in contractor
                                    for mark in _NON_CONSTRUCTION_MARKERS),
        })
    dated = [item for item in rows if item["date"]]
    return {
        "rows": rows,
        "total": sum(item["amount"] for item in rows),
        "dated": sum(item["amount"] for item in dated),
        "undated": sum(item["amount"] for item in rows if not item["date"]),
        "construction_dated": sum(item["amount"] for item in dated
                                  if item["construction"]),
    }


def monthly(register: dict[str, Any], works: dict[str, Any]) -> dict[str, Any]:
    """Помесячный факт: деньги из реестра договоров, объёмы из актов РСС.

    Две шкалы намеренно раздельны. Деньги и выполнение расходятся во времени —
    аванс уходит раньше акта, а удержание позже, — и слитая строка не покажет
    ни того ни другого.
    """
    paid: dict[str, float] = {}
    for item in register["rows"]:
        if item["paid_amount"] and item["paid_date"]:
            key = _month(item["paid_date"])
            paid[key] = paid.get(key, 0.0) + item["paid_amount"]
    accepted: dict[str, float] = {}
    for item in works["rows"]:
        if item["amount"] and item["date"] and item["construction"]:
            key = _month(item["date"])
            accepted[key] = accepted.get(key, 0.0) + item["amount"]
    months = sorted(set(paid) | set(accepted))
    running_paid = running_accepted = 0.0
    series = []
    for month in months:
        running_paid += paid.get(month, 0.0)
        running_accepted += accepted.get(month, 0.0)
        series.append({
            "month": month,
            "paid": paid.get(month, 0.0),
            "accepted": accepted.get(month, 0.0),
            "paid_cumulative": running_paid,
            "accepted_cumulative": running_accepted,
        })
    return {"series": series,
            "first": months[0] if months else "",
            "last": months[-1] if months else ""}


def reconcile(
    estimate: dict[str, Any],
    register: dict[str, Any],
    works: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Свести РСС с реестром договоров по коду. Ничего не подгонять.

    Расхождение — это результат: обе цифры и разница печатаются рядом, а
    выбирать «более правильный» источник сводка не вправе.
    """
    register_paid: dict[str, float] = {}
    register_acts: dict[str, float] = {}
    for item in register["rows"]:
        code = item["estimate_code"]
        if not code:
            continue
        register_paid[code] = register_paid.get(code, 0.0) + item["paid_amount"]
        register_acts[code] = register_acts.get(code, 0.0) + item["act_amount"]

    # Реестр разносит платёж по листьям, строка РСС — уже агрегат. Поднимаем
    # реестр по дереву, иначе глава сравнивается с нулём и «расходится» на всю
    # свою сумму.
    rolled_paid = _rolled_up(estimate["rows"], register_paid)
    rolled_acts = _rolled_up(estimate["rows"], register_acts)
    outside = sorted(set(register_paid) - set(estimate["by_code"]),
                     key=lambda value: [int(part) for part in value.split(".")])

    by_code = []
    for row in estimate["rows"]:
        code = row["code"]
        paid_estimate = float(row.get("paid", 0.0))
        paid_register = rolled_paid.get(code, 0.0)
        by_code.append({
            "code": code,
            "article": row.get("article", ""),
            "depth": row.get("depth", 1),
            "is_leaf": bool(row.get("is_leaf")),
            "estimate": float(row.get("estimate", 0.0)),
            "contracted": float(row.get("contracted", 0.0)),
            "completed": float(row.get("completed", 0.0)),
            "paid_estimate": paid_estimate,
            "paid_register": paid_register,
            "paid_delta": paid_register - paid_estimate,
            "acts_register": rolled_acts.get(code, 0.0),
        })

    warnings: list[str] = []
    orphans = outside
    if orphans:
        warnings.append(
            "кодов реестра нет в РСС: " + ", ".join(orphans[:8]))
    if register["unmapped_paid"]:
        warnings.append(
            f"оплата без кода РСС: {register['unmapped_paid'] / 1e6:,.1f} млн ₽")
    total = estimate.get("total") or {}
    paid_estimate_total = float(total.get("paid", 0.0))
    paid_gap = register["paid"] - paid_estimate_total
    # Порог относительный. Зашитый «миллион рублей» молчал бы на любой книге,
    # где суммы ведутся не в рублях, а расхождение там такое же настоящее.
    if abs(paid_gap) > max(1.0, 0.0001 * abs(paid_estimate_total)):
        warnings.append(
            f"оплачено: РСС {paid_estimate_total / 1e6:,.1f} против реестра "
            f"{register['paid'] / 1e6:,.1f} млн ₽, разрыв {paid_gap / 1e6:,.1f}")
    if works and works["undated"]:
        warnings.append(
            f"выполнение без даты: {works['undated'] / 1e6:,.1f} млн ₽ "
            "(плата городу, комиссии банка, ФОТ — не акты КС)")

    return {
        "by_code": by_code,
        "total": {
            "estimate": float(total.get("estimate", 0.0)),
            "contracted": float(total.get("contracted", 0.0)),
            "paid_estimate": float(total.get("paid", 0.0)),
            "paid_register": register["paid"],
            "completed": float(total.get("completed", 0.0)),
            "acts_register": register["accepted"],
        },
        "crosswalk": register["crosswalk"],
        "warnings": warnings,
    }


def _report(estimate_path: str, register_path: str) -> str:
    """Свод в текст: чтобы прогнать очередную выгрузку, не написав ни строки."""
    estimate = read_estimate(estimate_path)
    register = read_register(register_path)
    works = read_completed_works(estimate_path)
    report = reconcile(estimate, register, works)
    lines = [
        f'{"":<34}{"смета":>10}{"договоры":>10}{"опл.РСС":>10}'
        f'{"опл.реестр":>11}{"Δ":>9}{"КС":>10}{"%вып":>7}',
    ]

    def line(label: str, row: dict[str, Any], delta: float) -> str:
        done = row["completed"] / row["estimate"] * 100 if row["estimate"] else 0.0
        return (f'{label[:32]:<34}{row["estimate"] / 1e6:>10,.1f}'
                f'{row["contracted"] / 1e6:>10,.1f}{row["paid_estimate"] / 1e6:>10,.1f}'
                f'{row["paid_register"] / 1e6:>11,.1f}{delta / 1e6:>9,.1f}'
                f'{row["completed"] / 1e6:>10,.1f}{done:>6,.1f}%')

    for row in report["by_code"]:
        if row["depth"] == 1:
            lines.append(line(row["article"], row, row["paid_delta"]))
    total = report["total"]
    lines.append(line("ИТОГО", {**total, "paid_estimate": total["paid_estimate"],
                                "paid_register": total["paid_register"]},
                      total["paid_register"] - total["paid_estimate"]))
    series = monthly(register, works)["series"]
    lines.append("")
    lines.append(f"помесячно: {len(series)} мес., "
                 f"{series[0]['month'] if series else '—'} … "
                 f"{series[-1]['month'] if series else '—'}")
    lines.append(f"связок код РСС ↔ код БДДС: {len(report['crosswalk'])}")
    for warning in report["warnings"]:
        lines.append(f"  • {warning}")
    return "\n".join(lines)


if __name__ == "__main__":  # pragma: no cover
    import sys

    if len(sys.argv) != 3:
        print("использование: python3 developaid_actuals.py РСС.xlsx финмодель.xlsx")
        raise SystemExit(2)
    print(_report(sys.argv[1], sys.argv[2]))
