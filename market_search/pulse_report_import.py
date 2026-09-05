"""Импорт месячного отчёта «Пульс Продаж Новостроек» в справочники рынка.

Отчёт приходит книгой Excel на 177 МБ: шесть листов, из них «Готовый отчёт»
разворачивается в 520 МБ разметки, а лист выписок — в гигабайт. Открывать это
целиком нельзя, поэтому книга читается потоком средствами стандартной
библиотеки: zip-запись листа разбирается по строкам, строка отдаётся наружу и
забывается. Тянуть в образ ещё один разбор xlsx ради выгрузки раз в месяц
незачем — по той же причине, по которой разбор PDF в `registry_import` написан
руками.

Из книги собираются три файла, которые уезжают вместе с кодом:

* `moscow-<месяц>.json` — справочник проектов: район, девелопер, продажи
  последних месяцев. Его читает `ProjectRegistry`.
* `moscow-dynamics-<месяц>.json` — помесячные ряды по проекту. Кабинет отдаёт
  темп ЧИСЛОМ (среднее и среднее за три месяца), ряда по месяцам у него нет —
  он есть только здесь.
* `moscow-market-<месяц>.json` — городской свод по классам и округам.

Что здесь важно и чего не было в прежнем разовом импорте:

* **Витрина и сделка — разные величины, и обе есть в отчёте.** Цена прайса
  (`price`), средняя цена продажи по ДДУ (`ddu`) и скидка между ними (`disc`)
  идут рядом и никогда не подменяют друг друга: сравнивать надо одинаковое.
* **«Нельзя измерить» — это не «не продавал».** У отчёта есть свой лист с
  причиной по каждому такому проекту, и он переносится целиком: проект, которого
  нет в справочнике, иначе читается как проект без продаж.
* **Месяц лежит числом Excel.** `46235` — это 01.08.2026, а не количество.
  Прочитанный как число, он молча станет каким-нибудь объёмом.

Запуск:

    python3 -m market_search.pulse_report_import отчёт.xlsx \\
        --out market_search/registry_data --months 36
"""

from __future__ import annotations

import argparse
import datetime
import json
import re
import zipfile
from pathlib import Path
from typing import Any, Iterator
from xml.etree.ElementTree import iterparse

from .registry import OKRUGS


NS = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
EPOCH = datetime.date(1899, 12, 30)

SHEET_REPORT = "Готовый отчёт"
SHEET_PROJECTS = "Справочник по ЖК"
SHEET_UNMEASURED = "Нельзя измерить"

# Строка «Готового отчёта» приходит и по корпусам, и итогом по проекту. Итог
# помечен словом в колонке «Корпус»; складывать корпуса самим значило бы завести
# второй счёт той же величины.
WHOLE_PROJECT = "все"

_COLUMN = re.compile(r"[A-Z]+")


def _column(ref: str) -> str:
    found = _COLUMN.match(ref or "")
    return found.group(0) if found else ""


def _shared_strings(book: zipfile.ZipFile) -> list[str]:
    if "xl/sharedStrings.xml" not in book.namelist():
        return []
    out: list[str] = []
    with book.open("xl/sharedStrings.xml") as stream:
        for _, element in iterparse(stream, ("end",)):
            if element.tag != NS + "si":
                continue
            out.append("".join(node.text or "" for node in element.iter(NS + "t")))
            element.clear()
    return out


def _sheet_paths(book: zipfile.ZipFile) -> dict[str, str]:
    workbook = book.read("xl/workbook.xml").decode("utf-8")
    rels = book.read("xl/_rels/workbook.xml.rels").decode("utf-8")
    target: dict[str, str] = {}
    for found in re.finditer(r'Id="([^"]+)"[^>]*Target="([^"]+)"', rels):
        target[found.group(1)] = found.group(2)
    out: dict[str, str] = {}
    for found in re.finditer(r'<sheet[^>]*name="([^"]+)"[^>]*r:id="([^"]+)"', workbook):
        path = target.get(found.group(2), "")
        if path:
            out[found.group(1)] = "xl/" + path.lstrip("/").removeprefix("xl/")
    return out


def rows(path: Path, sheet: str) -> Iterator[dict[str, Any]]:
    """Строки листа словарём по букве колонки. Пустая ячейка не приходит вовсе."""
    book = zipfile.ZipFile(path)
    paths = _sheet_paths(book)
    if sheet not in paths:
        raise KeyError(f"в книге нет листа «{sheet}»: есть {', '.join(paths)}")
    strings = _shared_strings(book)
    with book.open(paths[sheet]) as stream:
        for _, element in iterparse(stream, ("end",)):
            if element.tag != NS + "row":
                continue
            row: dict[str, Any] = {}
            for cell in element.iter(NS + "c"):
                letter = _column(cell.get("r") or "")
                if not letter:
                    continue
                kind = cell.get("t")
                if kind == "inlineStr":
                    inline = cell.find(NS + "is")
                    value: Any = (
                        "".join(node.text or "" for node in inline.iter(NS + "t"))
                        if inline is not None
                        else None
                    )
                else:
                    node = cell.find(NS + "v")
                    if node is None:
                        continue
                    raw = node.text
                    if kind == "s":
                        try:
                            value = strings[int(raw)]
                        except (TypeError, ValueError, IndexError):
                            value = None
                    else:
                        value = raw
                if value not in (None, ""):
                    row[letter] = value
            element.clear()
            if row:
                yield row


def month_of(value: Any) -> str | None:
    """Месяц отчёта из числа Excel. `46235` — это 2026-08, а не количество."""
    try:
        day = EPOCH + datetime.timedelta(days=int(float(value)))
    except (TypeError, ValueError):
        text = str(value or "").strip()
        return text[:7] if re.fullmatch(r"\d{4}-\d{2}(-\d{2})?", text) else None
    return f"{day.year:04d}-{day.month:02d}"


def date_of(value: Any) -> str | None:
    try:
        return (EPOCH + datetime.timedelta(days=int(float(value)))).isoformat()
    except (TypeError, ValueError):
        return None


def number(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def whole(value: Any) -> int | None:
    got = number(value)
    return int(round(got)) if got is not None else None


def money(value: Any) -> int | None:
    got = number(value)
    return int(round(got)) if got is not None else None


def percent(value: Any) -> float | None:
    """Доли в отчёте лежат частью единицы: 0,103 — это 10,3 %."""
    got = number(value)
    return round(got * 100, 1) if got is not None else None


# Округ в отчёте назван прилагательным («Восточный»), а справочник и вся
# остальная служба живут аббревиатурой. Аббревиатура лежит в самом адресе
# («Москва, ВАО, р-н Гольяново»), поэтому сначала спрашиваем адрес, и только
# если он молчит — переводим слово. Своей таблицы округов заводить не хочется
# вовсе, но слово без адреса иначе не опознать.
_OKRUG_BY_WORD = {
    "центральный": "ЦАО",
    "северный": "САО",
    "северо-восточный": "СВАО",
    "восточный": "ВАО",
    "юго-восточный": "ЮВАО",
    "южный": "ЮАО",
    "юго-западный": "ЮЗАО",
    "западный": "ЗАО",
    "северо-западный": "СЗАО",
    "зеленоградский": "ЗелАО",
    "троицкий": "ТАО",
    "новомосковский": "НАО",
}

# Список округов объявлен в справочнике — второй копии у него быть не может.
_OKRUG_IN_ADDRESS = re.compile(
    r"(?<![А-Яа-яЁё])("
    + "|".join(sorted(OKRUGS, key=len, reverse=True))
    + r")(?![А-Яа-яЁё])"
)


def okrug_of(address: Any, word: Any) -> str | None:
    found = _OKRUG_IN_ADDRESS.search(str(address or ""))
    if found:
        return found.group(1)
    return _OKRUG_BY_WORD.get(str(word or "").strip().lower())


# Комнатность идёт блоками по девять колонок подряд, в одном и том же порядке.
# Перечислять восемь букв на каждую комнатность значило бы завести список,
# который разъедется с книгой при первой же вставке колонки.
ROOM_BLOCKS = (
    ("studio", "AN"),
    ("r1", "AW"),
    ("r2", "BF"),
    ("r3", "BO"),
    ("r4", "BX"),
    ("r5", "CG"),
)
ROOM_FIELDS = (
    ("sold", 0, whole),
    ("area", 1, number),
    ("lot_avg", 2, number),
    ("price", 3, money),
    ("deal_price", 4, money),
    ("total", 5, whole),
    ("rem", 6, whole),
    ("rem_pct", 7, percent),
)


def _shift(letter: str, by: int) -> str:
    index = 0
    for char in letter:
        index = index * 26 + (ord(char) - 64)
    index += by
    out = ""
    while index:
        index, rest = divmod(index - 1, 26)
        out = chr(65 + rest) + out
    return out


def _rooms(row: dict[str, Any]) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for name, start in ROOM_BLOCKS:
        block = {}
        for field_name, offset, cast in ROOM_FIELDS:
            value = cast(row.get(_shift(start, offset)))
            if value is not None:
                block[field_name] = value
        if block.get("sold") or block.get("total"):
            out[name] = block
    return out


# Помесячная строка проекта. Витрина и сделка стоят рядом и никогда не
# подменяют друг друга: `price` — прайс-лист, `ddu` — средняя цена продажи по
# ДДУ, `disc` — скидка между ними. Подписать одно именем другого значит
# сравнить витрину с чужой сделкой и не заметить этого.
MONTH_FIELDS = (
    ("sold", "S", whole),
    ("area", "T", number),
    ("lot_avg", "U", number),
    ("legal", "Y", percent),
    ("mortgage", "AA", percent),
    ("resale", "AB", whole),
    ("price", "AD", money),
    ("disc", "AE", percent),
    ("deal", "AF", money),
    ("ddu", "AG", money),
    ("revenue", "AH", money),
    ("rem", "AK", whole),
    ("rem_pct", "AL", percent),
)

SERIES_KEYS = tuple(name for name, _, _ in MONTH_FIELDS)

# В ряд по месяцам уезжает не всё: `deal`, `lot_avg`, `rem_pct` и `revenue`
# выводятся из соседей той же строки, и хранить их рядом значит завести второй
# ответ на один вопрос — да ещё и умножить файл. В снимке последнего месяца они
# остаются: там их считает книга, а не мы.
DYNAMICS_KEYS = ("sold", "area", "price", "ddu", "disc", "rem", "mortgage", "legal")


def read_report(path: Path) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    """Итоговые строки проектов «Готового отчёта»: паспорт и месяцы.

    Строки по корпусам пропускаются: итог по проекту книга считает сама, и
    складывать корпуса значило бы завести второй счёт той же величины.
    """
    passport: dict[str, dict[str, Any]] = {}
    series: dict[str, dict[str, Any]] = {}
    for index, row in enumerate(rows(path, SHEET_REPORT)):
        if index < 2:  # две строки шапки: группы и подписи
            continue
        if str(row.get("J") or "").strip().lower() != WHOLE_PROJECT:
            continue
        key = str(row.get("CY") or "").strip()
        month = month_of(row.get("I"))
        if not key or not month:
            continue
        passport.setdefault(
            key,
            {
                "name": str(row.get("A") or "").strip(),
                "address": str(row.get("B") or "").strip() or None,
                "okrug": okrug_of(row.get("B"), row.get("C")),
                "district": str(row.get("D") or "").strip() or None,
                "developer": str(row.get("E") or "").strip() or None,
                "builder": str(row.get("F") or "").strip() or None,
                "segment": str(row.get("G") or "").strip() or None,
                "site": str(row.get("H") or "").strip() or None,
                "escrow_bank": str(row.get("L") or "").strip() or None,
            },
        )
        point: dict[str, Any] = {}
        for name, letter, cast in MONTH_FIELDS:
            value = cast(row.get(letter))
            if value is not None:
                point[name] = value
        rooms = _rooms(row)
        if rooms:
            # Имя `rooms` уже занято другим источником: у bnMAP это цена метра
            # по комнатности, число, а не состав. Под одним ключом две разные
            # величины — и разбор второй падает на первой.
            point["room_mix"] = rooms
        if point:
            series.setdefault(key, {})[month] = point
    return passport, series


def read_projects(path: Path) -> dict[str, dict[str, Any]]:
    """Справочник по ЖК: корпуса сложены в проект.

    Класс, координаты и адрес у корпусов одного проекта совпадают, а метры и
    штуки складываются. Средняя площадь лота по комнатности взвешивается
    штуками — простое среднее по корпусам дало бы среднее средних.
    """
    out: dict[str, dict[str, Any]] = {}
    for index, row in enumerate(rows(path, SHEET_PROJECTS)):
        if index < 1:
            continue
        key = str(row.get("A") or "").strip()
        if not key:
            continue
        item = out.setdefault(
            key,
            {
                "name": str(row.get("C") or "").strip(),
                "developer": str(row.get("D") or "").strip() or None,
                "builder": str(row.get("E") or "").strip() or None,
                "okrug": okrug_of(row.get("I"), row.get("H")),
                "district": str(row.get("J") or "").strip() or None,
                "address": str(row.get("I") or "").strip() or None,
                "segment": str(row.get("AP") or "").strip() or None,
                "latitude": number(row.get("AY")),
                "longitude": number(row.get("AZ")),
                "mkad_km": number(row.get("K")),
                "buildings": 0,
                "living_area": 0.0,
                "living_units": 0,
                "flats": 0,
                "apartments": 0,
                "parking": 0,
                "storage": 0,
                "rooms": {},
                "commissioning": None,
                "sales_start": None,
            },
        )
        item["buildings"] += 1
        for source, target in (("AC", "living_area"),):
            value = number(row.get(source))
            if value:
                item[target] += value
        for source, target in (
            ("AG", "living_units"),
            ("AN", "flats"),
            ("AO", "apartments"),
            ("AW", "parking"),
            ("AX", "storage"),
        ):
            value = whole(row.get(source))
            if value:
                item[target] += value
        # Состав по комнатности: штуки складываются, средняя площадь копится
        # взвешенно и делится в конце.
        for name, count_letter, area_letter in (
            ("studio", "AH", "BA"),
            ("r1", "AI", "BB"),
            ("r2", "AJ", "BC"),
            ("r3", "AK", "BD"),
            ("r4", "AL", "BE"),
            ("r5", "AM", "BF"),
        ):
            count = whole(row.get(count_letter)) or 0
            block = item["rooms"].setdefault(name, {"units": 0, "_area": 0.0})
            block["units"] += count
            area = number(row.get(area_letter))
            if area and count:
                block["_area"] += area * count
        planned = date_of(row.get("R")) or date_of(row.get("Q"))
        if planned and (item["commissioning"] is None or planned > item["commissioning"]):
            item["commissioning"] = planned
        started = date_of(row.get("P"))
        if started and (item["sales_start"] is None or started < item["sales_start"]):
            item["sales_start"] = started
    for item in out.values():
        item["living_area"] = round(item["living_area"], 1) or None
        for name, block in list(item["rooms"].items()):
            units = block.pop("_area"), block["units"]
            weighted, count = units
            block["lot_avg"] = round(weighted / count, 1) if weighted and count else None
            if not block["units"]:
                item["rooms"].pop(name)
    return out


def read_unmeasured(path: Path) -> list[dict[str, Any]]:
    """«Нельзя измерить» — это не «не продавал», и причина здесь названа."""
    out: list[dict[str, Any]] = []
    for index, row in enumerate(rows(path, SHEET_UNMEASURED)):
        if index < 1:
            continue
        name = str(row.get("A") or "").strip()
        reason = str(row.get("G") or "").strip()
        if not name:
            continue
        out.append(
            {
                "name": name,
                "okrug": okrug_of(row.get("B"), row.get("C")),
                "district": str(row.get("D") or "").strip() or None,
                "developer": str(row.get("E") or "").strip() or None,
                "reason": reason or None,
                "month": month_of(row.get("I")),
                "price": money(row.get("M")),
            }
        )
    return out


def _median(values: list[float]) -> float | None:
    if not values:
        return None
    values = sorted(values)
    middle = len(values) // 2
    if len(values) % 2:
        return values[middle]
    return (values[middle - 1] + values[middle]) / 2


def _round(value: float | None, digits: int = 0) -> float | int | None:
    if value is None:
        return None
    return int(round(value)) if digits == 0 else round(value, digits)


def build_dynamics(
    passport: dict[str, dict[str, Any]],
    series: dict[str, dict[str, Any]],
    *,
    months: list[str],
    source: str,
) -> dict[str, Any]:
    projects: dict[str, Any] = {}
    for key, by_month in series.items():
        card = passport.get(key) or {}
        row: dict[str, Any] = {
            "name": card.get("name"),
            "segment": card.get("segment"),
            "okrug": card.get("okrug"),
            "district": card.get("district"),
            "developer": card.get("developer"),
        }
        filled = False
        for name in DYNAMICS_KEYS:
            line = [by_month.get(month, {}).get(name) for month in months]
            if any(value is not None for value in line):
                row[name] = line
                filled = True
        last = by_month.get(months[-1]) if months else None
        if last and last.get("room_mix"):
            row["room_mix"] = last["room_mix"]
        if filled:
            projects[key] = row
    return {
        "source": source,
        "last_month": months[-1] if months else None,
        "months": months,
        "projects": projects,
    }


def build_registry(
    passport: dict[str, dict[str, Any]],
    series: dict[str, dict[str, Any]],
    *,
    months: list[str],
    source: str,
) -> dict[str, Any]:
    """Справочник в форме, которую читает `ProjectRegistry`."""
    projects = []
    for key, by_month in series.items():
        card = passport.get(key) or {}
        sales = {
            month: by_month[month]["sold"]
            for month in months
            if by_month.get(month, {}).get("sold") is not None
        }
        if not card.get("name"):
            continue
        projects.append(
            {
                "name": card["name"],
                "developer": card.get("developer"),
                "okrug": card.get("okrug"),
                "district": card.get("district"),
                "sales": sales,
                "source": source,
            }
        )
    return {"source": source, "months": months, "projects": projects}


def _snapshot(points: list[dict[str, Any]]) -> dict[str, Any]:
    prices = [float(p["price"]) for p in points if p.get("price")]
    ddu = [float(p["ddu"]) for p in points if p.get("ddu")]
    sold = [float(p["sold"]) for p in points if p.get("sold") is not None]
    discounts = [float(p["disc"]) for p in points if p.get("disc") is not None]
    mortgage = [float(p["mortgage"]) for p in points if p.get("mortgage") is not None]
    remains = [float(p["rem"]) for p in points if p.get("rem") is not None]
    quarters = sorted(prices)
    out: dict[str, Any] = {
        "projects": len(points),
        "price_median": _round(_median(prices)),
        "price_p25": _round(_median(quarters[: len(quarters) // 2])) if len(quarters) > 3 else None,
        "price_p75": (
            _round(_median(quarters[(len(quarters) + 1) // 2 :])) if len(quarters) > 3 else None
        ),
        # Сделка идёт рядом с витриной, а не вместо неё: разница между ними и
        # есть скидка, и подменять одно другим нельзя.
        "ddu_median": _round(_median(ddu)),
        "ddu_projects": len(ddu),
        "sold_median": _round(_median(sold)),
        "sold_total": _round(sum(sold)),
        "rem_total": _round(sum(remains)),
        "disc_median": _round(_median(discounts), 1),
        "mortgage_median": _round(_median(mortgage), 1),
    }
    return out


def build_market(
    passport: dict[str, dict[str, Any]],
    series: dict[str, dict[str, Any]],
    *,
    months: list[str],
    source: str,
) -> dict[str, Any]:
    last = months[-1]
    by_class: dict[str, list[dict[str, Any]]] = {}
    by_okrug: dict[str, dict[str, Any]] = {}
    current: dict[str, list[dict[str, Any]]] = {}
    for key, by_month in series.items():
        card = passport.get(key) or {}
        segment = card.get("segment")
        if not segment:
            continue
        point = by_month.get(last)
        if point:
            current.setdefault(segment, []).append(point)
            okrug = card.get("okrug")
            if okrug:
                by_okrug.setdefault(okrug, {}).setdefault(segment, []).append(point)
    rows_by_class: dict[str, list[dict[str, Any]]] = {}
    for month in months:
        buckets: dict[str, list[dict[str, Any]]] = {}
        for key, by_month in series.items():
            segment = (passport.get(key) or {}).get("segment")
            point = by_month.get(month)
            if segment and point:
                buckets.setdefault(segment, []).append(point)
        for segment, points in buckets.items():
            prices = [float(p["price"]) for p in points if p.get("price")]
            ddu = [float(p["ddu"]) for p in points if p.get("ddu")]
            rows_by_class.setdefault(segment, []).append(
                {
                    "m": month,
                    "n": len(points),
                    "price": _round(_median(prices)),
                    "ddu": _round(_median(ddu)),
                    "sold": _round(_median([float(p.get("sold") or 0) for p in points])),
                    "sold_sum": _round(sum(float(p.get("sold") or 0) for p in points)),
                    "m2_sum": _round(sum(float(p.get("area") or 0) for p in points)),
                }
            )
    by_class = rows_by_class
    return {
        "source": source,
        "last_month": last,
        "months": months,
        "current": {segment: _snapshot(points) for segment, points in current.items()},
        "by_class": by_class,
        "by_okrug": {
            okrug: {segment: _snapshot(points) for segment, points in segments.items()}
            for okrug, segments in by_okrug.items()
        },
    }


def build_deals(
    deals: dict[str, dict[str, Any]],
    series: dict[str, dict[str, Any]],
    *,
    months: list[str],
) -> dict[str, Any]:
    """Свод выписок: то, чего нет в «Готовом отчёте», и сверка с ним.

    Отчёт даёт комнатность и долю ипотеки сам — второго счёта тех же величин
    здесь нет намеренно. Из выписок берутся полосы площади (комнатность на
    вопрос «что вымывается» не отвечает: двушка бывает и 44 м², и 84) и банки,
    которыми платят.

    Число сделок при этом сверяется с числом продаж отчёта: свод, посчитанный
    по другой дате или по другому типу объекта, выглядел бы так же уверенно.
    """
    window = set(months)
    projects: dict[str, Any] = {}
    checked = matched = 0
    for row in deals.values():
        if row["month"] not in window:
            continue
        item = projects.setdefault(
            row["complex_id"], {"bands": {}, "banks": {}, "deals": 0, "months": {}}
        )
        item["deals"] += row["deals"]
        for band, count in row["bands"].items():
            item["bands"][band] = item["bands"].get(band, 0) + count
        for bank, count in row["banks"].items():
            item["banks"][bank] = item["banks"].get(bank, 0) + count
        item["months"][row["month"]] = row["deals"]
        told = (series.get(row["complex_id"], {}).get(row["month"], {}) or {}).get("sold")
        if told is not None:
            checked += 1
            matched += int(told == row["deals"])
    for item in projects.values():
        item["banks"] = dict(sorted(item["banks"].items(), key=lambda pair: -pair[1])[:5])
    return {
        "months": months,
        "projects": projects,
        "check": {"compared": checked, "matched": matched},
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("book", type=Path, help="месячный отчёт .xlsx")
    parser.add_argument("--out", type=Path, default=Path("market_search/registry_data"))
    parser.add_argument("--months", type=int, default=24, help="глубина ряда, месяцев")
    parser.add_argument("--label", default="", help="подпись источника")
    parser.add_argument("--deal-months", type=int, default=12, help="глубина свода выписок")
    parser.add_argument("--skip-deals", action="store_true", help="не читать лист выписок")
    args = parser.parse_args(argv)

    passport, series = read_report(args.book)
    seen = sorted({month for by_month in series.values() for month in by_month})
    if not seen:
        print("в «Готовом отчёте» не нашлось ни одного месяца — разбор не состоялся")
        return 1
    months = seen[-args.months :]
    last = months[-1]
    label = args.label or f"Пульс Продаж Новостроек, отчёт «Москва старая» за {last}"

    args.out.mkdir(parents=True, exist_ok=True)
    written: list[tuple[Path, Any]] = [
        (args.out / f"moscow-{last}.json", build_registry(passport, series, months=months, source=label)),
        (
            args.out / f"moscow-dynamics-{last}.json",
            build_dynamics(passport, series, months=months, source=label),
        ),
        (
            args.out / f"moscow-market-{last}.json",
            build_market(passport, series, months=months, source=label),
        ),
    ]
    cards = read_projects(args.book)
    written.append(
        (
            args.out / f"moscow-cards-{last}.json",
            {"source": label, "last_month": last, "cards": cards},
        )
    )
    # «Нельзя измерить» лист ведёт по месяцам, а ответ нужен на последний: за
    # два года там четыре с половиной тысячи строк об одних и тех же проектах.
    unmeasured = [item for item in read_unmeasured(args.book) if item.get("month") == last]
    written.append(
        (
            args.out / f"moscow-unmeasured-{last}.json",
            {"source": label, "last_month": last, "projects": unmeasured},
        )
    )
    if not args.skip_deals:
        window = months[-args.deal_months :]
        deals = read_deals(args.book, months=set(window))
        summary = build_deals(deals, series, months=window)
        written.append((args.out / f"moscow-deals-{last}.json", {"source": label, **summary}))
        check = summary["check"]
        print(
            f"сверка выписок с отчётом: сошлось {check['matched']} из {check['compared']} "
            f"пар «проект — месяц»"
        )

    for path, payload in written:
        path.write_text(
            json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8"
        )
        print(f"{path}  {path.stat().st_size / 1024:.0f} КБ")
    print(
        f"месяцев в отчёте {len(seen)} ({seen[0]}…{seen[-1]}), взято {len(months)}; "
        f"проектов {len(series)}, карточек {len(cards)}, нельзя измерить {len(unmeasured)}"
    )
    return 0



SHEET_DEALS = "Данные по лотам из выписок"

# Полосы площади объявлены здесь один раз. Границы полуоткрыты слева направо, а
# верхняя полоса не имеет потолка: самая большая квартира иначе выпала бы из
# счёта вместе со своим договором.
AREA_BANDS = ((0, 28), (28, 40), (40, 55), (55, 85), (85, 120), (120, None))


def band_of(area: float | None) -> str | None:
    if area is None or area <= 0:
        return None
    for low, high in AREA_BANDS:
        if area >= low and (high is None or area < high):
            return f"{low}-{high}" if high is not None else f"{low}+"
    return None


# Тип объекта решает, что попадает в цену и в комнатность. Без него кладовка за
# 879 тыс ₽ и машиноместо встают в один ряд с квартирами: у одного проекта из
# 295 сделок августа 130 оказались в полосе «до 28 м²», а 246 покупателей —
# юрлицами. Это не рынок жилья, это паркинг.
LIVING_TYPES = ("квартира", "апартамент")
OTHER_TYPES = {
    "машиноместо": "parking",
    "машино-место": "parking",
    "кладовка": "storage",
    "кладовая": "storage",
    "коммерческое помещение": "commercial",
    "нежилое помещение": "commercial",
}


def kind_of(value: Any) -> str:
    text = str(value or "").strip().lower()
    if not text:
        return "unknown"
    for word in LIVING_TYPES:
        if text.startswith(word):
            return "living"
    for word, name in OTHER_TYPES.items():
        if text.startswith(word):
            return name
    return "other"


def bank_of(value: Any) -> str | None:
    """Имя банка без формы собственности и регистра.

    Один Сбербанк приезжает тремя написаниями в одном месяце — заглавными,
    строчными и с ИНН. Считать их по строке значит показать три банка там, где
    один.
    """
    text = str(value or "").split(",")[0].strip()
    if not text:
        return None
    text = re.sub(r"\((?:[^()]*)\)", " ", text)
    text = re.sub(r"[«»\"']", " ", text)
    # Форма собственности приезжает и в косвенном падеже: «Акционерным
    # Обществом Всероссийский банк развития регионов». Снимаются основы, а не
    # словарные формы, иначе на экране остаётся имя с чужой грамматикой.
    text = re.sub(
        r"(?i)\b(публичн\w*|непубличн\w*|акционерн\w*|обществ\w*|коммерческ\w*|"
        r"ограниченн\w*|ответственност\w*|с\b|пао|ао|оао|зао|ооо)\b",
        " ",
        text,
    )
    # Слово «банк» снимается только с краю: внутри «Альфа-Банк» оно часть имени
    # (дефис для `\b` — такая же граница, как пробел), а внутри «Всероссийский
    # банк развития регионов» — часть названия, и без него остаётся бессмыслица.
    # Границей служит пробел, а не `\b`: после дефиса «банк» — часть имени
    # («Альфа-Банк»), и `\bбанк$` отрезал бы от него половину.
    text = re.sub(r"(?i)^\s*банк(\s|$)", " ", text)
    text = re.sub(r"(?i)(^|\s)банк\s*$", " ", text)
    words = text.split()
    if not words:
        return None
    # Регистр приводится всегда и одинаково: «СБЕРБАНК РОССИИ» и «Сбербанк
    # России» обязаны сойтись в одно имя, иначе один банк считается двумя.
    # Короткое слово из заглавных — аббревиатура, её `.capitalize()` испортит.
    return " ".join(
        word if word.isupper() and len(word) <= 4 else word.capitalize() for word in words
    )


def read_deals(path: Path, *, months: set[str] | None = None) -> dict[str, dict[str, Any]]:
    """Сделки из выписок, сложенные по проекту и месяцу.

    Лист выписок разворачивается в гигабайт, поэтому наружу отдаётся только
    свод. И одно измерение, ради которого он и читался: **цены сделки в этом
    источнике нет вовсе.** Колонка «Стоимость по ДДУ» пуста во всех 83 833
    договорах, а в «Готовом отчёте» средняя цена по ДДУ заполнена в 552 строках
    из 17 586 и ни в одной августовской. Что здесь ЕСТЬ — прайс проданного лота
    на момент продажи: цена не витрины вообще, а того, что купили. Разница
    между ней и средней ценой экспозиции и есть ответ на «берут дешёвое или
    дорогое», и подписывать её словом «сделка» нельзя.

    Месяц берётся по дате РЕГИСТРАЦИИ договора: по ней считает сам отчёт.
    """
    out: dict[str, dict[str, Any]] = {}
    for index, row in enumerate(rows(path, SHEET_DEALS)):
        if index < 1:
            continue
        key = str(row.get("A") or "").strip()
        month = month_of(row.get("J")) or month_of(row.get("I"))
        if not key or not month or (months is not None and month not in months):
            continue
        item = out.setdefault(
            f"{key}|{month}",
            {
                "complex_id": key,
                "month": month,
                "deals": 0,
                "area": 0.0,
                "list_sum": 0.0,
                "list_area": 0.0,
                "ddu_sum": 0.0,
                "ddu_deals": 0,
                "mortgage": 0,
                "banks": {},
                "person": 0,
                "company": 0,
                "resale": 0,
                "from_developer": 0,
                "secondary": 0,
                "rooms": {},
                "bands": {},
                "parking": 0,
                "storage": 0,
                "commercial": 0,
            },
        )
        kind = kind_of(row.get("P"))
        if kind in ("parking", "storage", "commercial"):
            item[kind] += 1
            continue
        if kind != "living":
            continue
        # Отчёт считает «продано ЗАСТРОЙЩИКОМ», и переуступка в это число не
        # входит. Пока в свод шли все жилые сделки подряд, он сходился с
        # отчётом ровно в 84 парах «проект — месяц» из 189, и всегда в одну
        # сторону — у нас больше. Переуступка остаётся отдельной строкой: она
        # про вторичный оборот, а не про продажи застройщика.
        primary = str(row.get("AL") or "").strip() in ("1", "1.0", "ДА")
        if row.get("AA"):
            item["resale"] += 1
        if not primary:
            item["secondary"] += 1
            continue
        item["from_developer"] += 1
        item["deals"] += 1
        area = number(row.get("V")) or 0.0
        item["area"] += area
        cost = number(row.get("K"))
        if cost:
            item["ddu_sum"] += cost
            item["ddu_deals"] += 1
        listed = number(row.get("Y"))
        if listed and area:
            item["list_sum"] += listed
            item["list_area"] += area
        if str(row.get("L") or "").strip().upper() == "ДА":
            item["mortgage"] += 1
            bank = bank_of(row.get("O"))
            if bank:
                item["banks"][bank] = item["banks"].get(bank, 0) + 1
        buyer = str(row.get("AC") or "").strip().upper()
        if buyer == "ФЛ":
            item["person"] += 1
        elif buyer == "ЮЛ":
            item["company"] += 1
        rooms = whole(row.get("W"))
        if rooms is not None:
            name = "studio" if rooms == 0 else f"r{min(rooms, 5)}"
            item["rooms"][name] = item["rooms"].get(name, 0) + 1
        band = band_of(area)
        if band:
            item["bands"][band] = item["bands"].get(band, 0) + 1
    return out


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
