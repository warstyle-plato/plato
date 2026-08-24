"""Отчёт правлению: что продано, что оплачено, что построено.

Такие сводки в книге собирают руками на формулах — вафельные диаграммы по
площадям, бублик «продано / оплачено», полосы освоения бюджета по этапам. Числа
там уже посчитаны; наш отчёт о рынке их не знает и показывает только продажи по
ДДУ.

Разница между «продано» и «оплачено» — не подробность, а главное в этой сводке.
На книге владельца законтрактовано 1 728,6 млн ₽, а на эскроу пришло 943,5:
13% против 7% бюджета продаж, дебиторка 785 млн. Банк смотрит на второе. Тот же
класс различия, что «факт по книге против факта по Пульсу»: показывать надо
рядом, а не выбирать одно.

Здесь только ЧТЕНИЕ. Ни одна величина не пересчитывается: доли, цены и остатки
берутся из книги как есть. Второй счёт того же числа однажды разошёлся бы с
первым, и оба выглядели бы верными.
"""

from __future__ import annotations

import re
from typing import Any

from .plan import PlanNotFound, _norm, _number, _sheet_rows


SALES_SHEET_HINTS = ("график продажи_1", "график продаж_1", "график продажи")
STATUS_SHEET_HINTS = ("гр.статус", "гр статус", "статус")

# Ключ — наш, подпись — из книги. Подписи правят руками, ключи нет.
BOARD_PRODUCTS = (
    ("apartments", ("кв", "квартиры")),
    ("commercial", ("псн", "коммерция")),
    ("parking", ("м/м", "мм", "машиноместа")),
    ("storage", ("клд", "кладовые")),
)
_TOTAL_LABELS = ("всего", "итого")
# Заголовок тройки колонок. Их в листе две — физические объёмы и деньги, — и
# отличаются они только тем, что написано над ними.
_TRIPLE = ("продано", "оплачено", "всего")
_MONEY_SECTION = "мониторинг денежных средств"
_VOLUME_SECTION = "все объекты"
# Диапазон площадей квартирографии: «28,3 - 40», «85 - 168,6».
_BRACKET_RE = re.compile(r"^\d+(?:[.,]\d+)?\s*[-–]\s*\d+(?:[.,]\d+)?$")


def _triples(rows: list[tuple]) -> list[tuple[int, int, str]]:
    """Где стоят тройки «Продано / Оплачено / ВСЕГО» и что они означают.

    Секция определяется ближайшим заголовком выше: «Все объекты» — это штуки и
    метры, «Мониторинг денежных средств» — рубли. Перепутать их значит показать
    метры как миллионы, и на экране это не бросится в глаза.
    """
    found: list[tuple[int, int, str]] = []
    section = ""
    for index, row in enumerate(rows):
        for cell in row:
            label = _norm(cell)
            if label.startswith(_VOLUME_SECTION):
                section = "volume"
            elif label.startswith(_MONEY_SECTION):
                section = "money"
        for position in range(len(row) - 2):
            window = tuple(_norm(cell) for cell in row[position:position + 3])
            if window == _TRIPLE:
                found.append((index, position, section))
                break
    return found


def parse_board_sales(data: bytes) -> dict[str, Any]:
    """Продано / оплачено / всего по продуктам и квартирография по площадям."""
    rows, sheet_name = _sheet_rows(data, hints=SALES_SHEET_HINTS)
    blocks: dict[str, dict[str, Any]] = {}
    headers = _triples(rows)
    for order, (header, position, section) in enumerate(headers):
        if not section or section in blocks:
            continue
        # Блок кончается там, где начинается следующий. Без этой границы
        # физические объёмы дочитывались до денежного блока и молча
        # перезаписывались рублями: подписи продуктов в обоих одинаковые, и на
        # экране метры выглядели бы миллионами.
        stop = headers[order + 1][0] if order + 1 < len(headers) else len(rows)
        stop = min(stop, header + 12)
        products: dict[str, dict[str, Any]] = {}
        totals: dict[str, float] = {}
        for row in rows[header + 1:stop]:
            label = _norm(row[position - 1] if position else "")
            if not label:
                continue
            values = [_number(row[position + offset]) if position + offset < len(row) else None
                      for offset in range(3)]
            if all(value is None for value in values):
                continue
            record = {"sold": values[0], "paid": values[1], "total": values[2]}
            if label in _TOTAL_LABELS:
                totals = record
                break
            key = next((name for name, aliases in BOARD_PRODUCTS if label in aliases), None)
            if key:
                products[key] = {"label": str(row[position - 1]).strip(), **record}
        if products:
            blocks[section] = {"products": products, "totals": totals}

    brackets = _apartment_brackets(rows)
    if not blocks and not brackets:
        raise PlanNotFound("В листе продаж не нашлось ни продуктов, ни квартирографии")
    return {"sheet": sheet_name, "volume": blocks.get("volume") or {},
            "money": blocks.get("money") or {}, "brackets": brackets}


def _apartment_brackets(rows: list[tuple]) -> list[dict[str, Any]]:
    """Квартирография: сколько продано в каждой группе площадей.

    По одной средней цене видно «661 тыс ₽/м²», и не видно, что мелкий формат
    ушёл на 41%, а крупный стоит на 17%. Это разные решения по прайсу.
    """
    header, columns = None, {}
    for index, row in enumerate(rows[:30]):
        marks: dict[str, int] = {}
        for position, cell in enumerate(row):
            label = _norm(cell)
            if label and label not in marks:
                marks[label] = position
        wanted = {
            "sold_units": ("продано, шт",), "paid_units": ("оплачено, шт",),
            "share": ("продано, %",), "sold_area": ("продано, кв.м", "продано, м2"),
            "sold_th": ("продано, т.руб", "продано, тыс.руб"),
            "price": ("цена",), "paid_th": ("оплачено, руб", "оплачено, т.руб"),
        }
        got = {key: next((marks[name] for name in names if name in marks), None)
               for key, names in wanted.items()}
        if got["sold_units"] is not None and got["sold_area"] is not None:
            header, columns = index, got
            break
    if header is None:
        return []
    out: list[dict[str, Any]] = []
    for row in rows[header + 1:header + 12]:
        label = ""
        for cell in row[:6]:
            text = " ".join(str(cell or "").split())
            if _BRACKET_RE.match(text):
                label = text
                break
        if not label:
            continue
        item: dict[str, Any] = {"range": label}
        for key, position in columns.items():
            item[key] = _number(row[position]) if position is not None and position < len(row) else None
        out.append(item)
    return out


def parse_board_status(data: bytes) -> dict[str, Any]:
    """Освоение бюджета по этапам: сколько из скольки и на какую дату.

    Бюджет и освоенное лежат в РАЗНЫХ блоках листа, и связывает их только имя
    этапа. Брать их из подписи вида «(11 717,5 млн.р)» нельзя: это текст,
    собранный формулой для диаграммы, и он рассыплется от смены формата.
    """
    rows, sheet_name = _sheet_rows(data, hints=STATUS_SHEET_HINTS)
    as_of = ""
    budgets: dict[str, float] = {}
    order: list[tuple[str, str]] = []
    for row in rows[:40]:
        label = " ".join(str(row[1] or "").split()) if len(row) > 1 else ""
        if not label:
            continue
        if _norm(label) == "дата":
            for cell in row[2:8]:
                month = _plan_month(cell)
                if month:
                    as_of = month
                    break
            continue
        # Блок с бюджетами: имя, начало, конец, освоено на дату, бюджет.
        if len(row) > 5 and _number(row[5]) is not None and _number(row[4]) is not None:
            key = _norm(label)
            if key not in budgets:
                budgets[key] = _number(row[5]) or 0.0
                order.append((key, label))

    done: dict[str, float] = {}
    for row in rows:
        label = " ".join(str(row[1] or "").split()) if len(row) > 1 else ""
        if not label or len(row) < 5:
            continue
        state = str(row[3] or "")
        if "%" not in state:
            continue
        value = _number(row[4])
        if value is None:
            continue
        done.setdefault(_norm(label), value)

    stages = []
    for key, label in order:
        budget = budgets.get(key) or 0.0
        if budget <= 0:
            continue
        spent = done.get(key)
        stages.append({
            "stage": label, "budget_mln": round(budget, 1),
            "done_mln": None if spent is None else round(spent, 1),
            # Доля берётся из книги делением её же чисел — это не второй счёт,
            # а то же деление; но если освоенного нет, доли нет тоже.
            "share": None if spent is None or budget <= 0 else round(spent / budget, 4),
        })
    if not stages:
        raise PlanNotFound("В листе статуса не нашлось этапов с бюджетом")
    return {"sheet": sheet_name, "as_of": as_of, "stages": stages}


def _plan_month(value: Any) -> str | None:
    from .plan import _month
    return _month(value)
