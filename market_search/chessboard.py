"""Шахматки: отдельный источник цен и остатка, общий для бота и отчётов."""
from __future__ import annotations

import datetime as dt
import html
import io
import math
import re
from collections import Counter
from typing import Any

PRICE_GAP = 0.15
_BUILDING = re.compile(r"(?:корп(?:ус)?\.?\s*(\d+)|(\d+)\s*корпус)", re.I)
_UNIT = re.compile(r"кв(?:артира)?\.?\s*№?\s*(\d+)", re.I)
_STATUSES = {"продано": "sold", "свободно": "available",
             "не для продажи": "unavailable", "проектирование": "regrouping"}


def number(value: Any) -> float | None:
    try:
        result = float(str(value).replace(" ", "").replace("\xa0", "").replace(",", "."))
        return result if math.isfinite(result) else None
    except (ValueError, TypeError):
        return None


def ru(value: float, digits: int = 0) -> str:
    return f"{value:,.{digits}f}".replace(",", " ").replace(".", ",")


def day(value: Any) -> dt.date | None:
    try:
        return dt.date.fromisoformat(str(value or "")[:10])
    except ValueError:
        return None


def building(value: Any) -> str:
    hit = _BUILDING.search(str(value or ""))
    return str(int(hit.group(1) or hit.group(2))) if hit else ""


def read(data: bytes) -> dict[str, Any]:
    from openpyxl import load_workbook

    book = load_workbook(io.BytesIO(data), data_only=True)
    buildings = {}
    try:
        for sheet in book:
            corpus = building(sheet["A2"].value)
            if not corpus:
                continue
            lots = []
            seen = set()
            for row in sheet:
                for cell in row:
                    if str(cell.value or "").strip().lower() not in ("м2", "м²"):
                        continue
                    r, c = cell.row, cell.column - 3
                    if c < 1:
                        continue
                    unit = sheet.cell(r, c).value
                    area = number(sheet.cell(r, c + 2).value)
                    floor = number(sheet.cell(r, 2).value)
                    if unit is None or area is None or area <= 0 or floor is None:
                        continue
                    uid = str(unit).strip()
                    # Студии тоже квартиры: «0к» не отличает их от подземных лотов.
                    apartment = floor > 0 and re.fullmatch(r"\d+", uid) is not None
                    product = "apartment" if apartment else "other"
                    key = f"{corpus}:{product}:{uid}"
                    if key in seen:
                        raise ValueError(f"Повтор лота в корпусе {corpus}: {uid}")
                    seen.add(key)
                    raw = str(sheet.cell(r + 3, c).value or "").strip()
                    state = "booked" if raw.lower().startswith("бронь") else _STATUSES.get(raw.lower(), "unknown")
                    price = number(sheet.cell(r + 2, c).value)
                    amount = number(sheet.cell(r + 2, c + 2).value)
                    consistent = bool(price and price > 0 and amount and amount > 0
                                      and math.isclose(price * area, amount, rel_tol=.01, abs_tol=1))
                    lots.append({"key": key, "building": corpus, "unit": uid,
                                 "product": product, "floor": floor, "area": area,
                                 "price_per_sqm": price, "amount": amount,
                                 "price_consistent": consistent,
                                 "status": state, "status_raw": raw,
                                 "sheet": sheet.title, "cell": sheet.cell(r, c).coordinate})
            if lots and any(x["status"] != "unknown" for x in lots):
                if corpus in buildings:
                    raise ValueError(f"Два листа шахматки одного корпуса: {corpus}")
                buildings[corpus] = {"lots": lots, "as_of": None}
    finally:
        book.close()
    if not buildings:
        raise ValueError("Шахматка не найдена: нужны корпус, номера, площади, цены и статусы лотов")
    return {"buildings": buildings}


def lots(snapshot: dict | None, today: str = "") -> list[dict]:
    result = []
    for corpus in ((snapshot or {}).get("buildings") or {}).values():
        dated = day(corpus.get("as_of"))
        # Источник без бизнес-даты и снимок из будущего не доказывают состояние.
        if dated is None or (today and dated > day(today)):
            continue
        result.extend(dict(lot, as_of=dated.isoformat(), source_file=corpus.get("file", ""))
                      for lot in corpus.get("lots") or [])
    return result


def merge(previous: dict | None, incoming: dict, filename: str) -> dict:
    """Загрузка корпуса обновляет только его; старый снимок не затирает новый."""
    buildings = dict((previous or {}).get("buildings") or {})
    for corpus, data in incoming["buildings"].items():
        if not day(data.get("as_of")):
            raise ValueError("У шахматки не указана дата состояния.")
        old = buildings.get(corpus) or {}
        if day(old.get("as_of")) and day(data["as_of"]) < day(old["as_of"]):
            raise ValueError(f"Шахматка корпуса {corpus} старше уже загруженной; обновление отменено.")
        buildings[corpus] = dict(data, file=filename)
    return {"buildings": buildings}


def match(inventory: list[dict], unit: str, corpus: str = "", area: Any = None) -> dict | None:
    candidates = [x for x in inventory if x["product"] == "apartment" and x["unit"] == str(unit)
                  and (not corpus or x["building"] == corpus)]
    # Название башни не угадывается по корпусу. Без корпуса — только уникальный номер.
    if len(candidates) != 1:
        return None
    lot = candidates[0]
    if number(area) is not None and abs(number(area) - lot["area"]) > 1:
        return None
    return lot


def questions(snapshot: dict | None, contracts: list[dict], report_text: str, today: str) -> list[dict]:
    from . import salesroom

    inventory = lots(snapshot, today)
    found = []
    for row in contracts:
        if row.get("product") not in ("Квартира", "Квартиры"):
            continue
        hit = _UNIT.search(str(row.get("unit") or ""))
        if not hit or not day(row.get("signed")):
            continue
        lot = match(inventory, hit.group(1), building(row.get("unit")), row.get("area"))
        # Текущий прайс не превращается в исторический: сверяем сделки после снимка.
        if not lot or day(row["signed"]) < day(lot["as_of"]) or day(row["signed"]) > day(today):
            continue
        if not lot["price_consistent"] or lot["status"] == "regrouping":
            continue
        area, amount = number(row.get("area")), number(row.get("amount"))
        if not area or not amount:
            continue
        actual = number(row.get("contract_price_per_sqm"))
        if actual is None:
            actual = amount / area
        if actual <= 0:
            continue
        expected = lot["price_per_sqm"]
        gap = actual / expected - 1
        if gap < -PRICE_GAP - 1e-10:
            identity = row.get("contract") or f"{lot['building']}:{lot['unit']}:{row['signed']}"
            found.append({"key": f"chess-price:{identity}", "kind": "chess_price",
                          "text": f"Корпус {lot['building']}, квартира № {lot['unit']}: цена договора "
                          f"{ru(actual)} ₽/м² ниже цены шахматки на {lot['as_of']} "
                          f"({ru(expected)} ₽/м²) на {ru(-gap*100, 1)}%. Подскажите, почему?"})
    for booking in salesroom.booked_lots(report_text) or []:
        lot = match(inventory, booking["apartment"], area=booking.get("area"))
        if lot and lot["status"] in ("sold", "unavailable", "regrouping"):
            found.append({"key": f"chess-status:{lot['key']}", "kind": "chess_status",
                          "text": f"Корпус {lot['building']}, квартира № {lot['unit']}: в отчёте она "
                          f"в бронях, а в шахматке на {lot['as_of']} — «{lot['status_raw']}». "
                          "Подскажите, почему статусы различаются?"})
    return found


def overlay(snapshot: dict | None, contracts: list[dict], today: str) -> dict | None:
    if not snapshot:
        return None
    inventory = [x for x in lots(snapshot, today) if x["product"] == "apartment"]
    if not inventory:
        return {"state": "missing", "reason": "Нет шахматки с подтверждённой датой на этот срез."}
    counts = Counter(x["status"] for x in inventory)
    available = [x for x in inventory if x["status"] == "available"]
    # Подписанный после снимка договор уменьшает остаток, но не становится
    # второй продажей и не меняет сам источник.
    signed = set()
    for row in contracts:
        if row.get("product") not in ("Квартира", "Квартиры"):
            continue
        hit = _UNIT.search(str(row.get("unit") or ""))
        if not hit or not day(row.get("signed")) or day(row["signed"]) > day(today):
            continue
        lot = match(inventory, hit.group(1), building(row.get("unit")), row.get("area"))
        if lot and day(row["signed"]) >= day(lot["as_of"]):
            signed.add(lot["key"])
    available = [x for x in available if x["key"] not in signed]
    known = [x for x in available if x["price_consistent"]]
    # Три полностью завершённых месяца: текущий неполный месяц не раздувает темп.
    cut = day(today).replace(day=1)
    months = []
    for _ in range(3):
        cut = (cut - dt.timedelta(days=1)).replace(day=1)
        months.append(cut.strftime("%Y-%m"))
    corps = {x["building"] for x in inventory}
    area_sold = sum(number(x.get("area")) or 0 for x in contracts
                    if day(x.get("signed")) and str(x["signed"])[:7] in months
                    and x.get("product") in ("Квартира", "Квартиры")
                    and building(x.get("unit")) in corps)
    pace = area_sold / 3
    area_left = sum(x["area"] for x in available)
    return {"state": "ok", "as_of": sorted({x["as_of"] for x in inventory}),
            "buildings": sorted(corps),
            "counts": dict(counts), "available": len(available), "available_area": area_left,
            "valuation": sum(x["amount"] for x in known) if len(known) == len(available) else None,
            "price_unconfirmed": len(available) - len(known), "pace_months": sorted(months),
            "pace_area": pace, "months_to_sell": area_left / pace if pace > 0 else None,
            "booked": counts["booked"], "regrouping_units": counts["regrouping"],
            "regrouping_lots": None, "regrouping_value": None,
            "unknown_status": counts["unknown"],
            "adjusted_signed": len(signed & {x["key"] for x in inventory if x["status"] == "available"})}


def render(block: dict | None) -> str:
    if not block:
        return ""
    if block.get("state") != "ok":
        return "<p>" + html.escape(block.get("reason") or "Шахматка не подтверждена.") + "</p>"
    value = (f"{ru(block['valuation']/1e6, 1)} млн ₽" if block["valuation"] is not None
             else "не подтверждена: есть несогласованные цены")
    text = (f"По загруженным корпусам {', '.join(block['buildings'])}, по шахматке на "
            f"{', '.join(block['as_of'])}, свободно квартир — {block['available']}, "
            f"площадь — {ru(block['available_area'], 1)} м². Стоимость остатка — {value}. "
            f"В бронях — {block['booked']}; бронь не считается продажей. ")
    if block["months_to_sell"] is not None:
        text += (f"При среднем темпе {ru(block['pace_area'], 1)} м² в месяц за три завершённых месяца "
                 f"остаток соответствует {ru(block['months_to_sell'], 1)} месяца продаж. ")
    else:
        text += "Для срока распродажи нет положительного темпа за три завершённых месяца. "
    text += (f"Для объединения выделено квартир — {block['regrouping_units']}. Состав новых лотов, "
             "их цены и сроки выхода пока не заданы: в обычный прогноз они не включены. "
             "Это оценка свободного остатка по текущим ценам, а не график поступлений на эскроу.")
    if block["unknown_status"]:
        text += f" Не распознаны статусы {block['unknown_status']} квартир; они исключены из остатка."
    return "<section class='chessboard-overlay'><h3>Остаток по шахматке и темп продаж</h3><p>" + html.escape(text) + "</p></section>"
