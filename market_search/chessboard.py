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


def reconciled_contracts(rows: list[dict]) -> tuple[list[dict], int, list[dict]]:
    """Повтор источника — один договор; противоречивые цены/площади не выбираем."""
    kept, fingerprints, conflicts, duplicates = {}, {}, set(), 0
    for row in rows:
        product = "apartment" if row.get("product") in ("Квартира", "Квартиры") else str(row.get("product") or "")
        corpus = building(row.get("unit"))
        unit = _UNIT.search(str(row.get("unit") or ""))
        name = (str(int(unit.group(1))) if corpus and unit
                else " ".join(str(row.get("unit") or "").casefold().split()))
        identity = (product, corpus, name, str(row.get("signed") or ""),
                    " ".join(str(row.get("contract") or "").casefold().split()))
        fingerprint = (number(row.get("area")), number(row.get("amount")),
                       number(row.get("contract_price_per_sqm")))
        if identity in kept:
            duplicates += 1
            if fingerprint != fingerprints[identity]:
                conflicts.add(identity)
        else:
            kept[identity], fingerprints[identity] = row, fingerprint
    return ([row for key, row in kept.items() if key not in conflicts], duplicates,
            [row for key, row in kept.items() if key in conflicts])


def questions(snapshot: dict | None, contracts: list[dict], report_text: str, today: str) -> list[dict]:
    from . import salesroom

    inventory = lots(snapshot, today)
    found = []
    for row in reconciled_contracts(contracts)[0]:
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


def _pace(contracts: list[dict] | None, corps: set[str], today: str,
          coverage: dict | None) -> dict:
    """Темп известных договоров отдельно от подтверждённого полного периода."""
    end = day(today).replace(day=1) - dt.timedelta(days=1)
    cut = end.replace(day=1)
    months = []
    for _ in range(3):
        months.append(cut.strftime("%Y-%m"))
        cut = (cut - dt.timedelta(days=1)).replace(day=1)
    start = dt.date.fromisoformat(min(months) + "-01")
    state, reason, total, duplicates = "partial", "", 0.0, 0
    observed = None
    if contracts is None:
        state, reason = "missing", "Контрактация не загружена; темп продаж неизвестен."
    else:
        unique, duplicates, conflicts = reconciled_contracts(contracts)
        ambiguous = any(day(row.get("signed")) and str(row["signed"])[:7] in months
                        and row.get("product") in ("Квартира", "Квартиры")
                        and (not building(row.get("unit")) or building(row.get("unit")) in corps)
                        for row in conflicts)
        for row in unique:
            signed = day(row.get("signed"))
            if not signed or signed.strftime("%Y-%m") not in months or row.get("product") not in ("Квартира", "Квартиры"):
                continue
            corpus = building(row.get("unit"))
            # Без явного корпуса не угадываем принадлежность продаж этому остатку.
            if not corpus:
                ambiguous = True
                continue
            if corpus not in corps:
                continue
            unit = _UNIT.search(str(row.get("unit") or ""))
            area = number(row.get("area"))
            if not unit or area is None or area <= 0:
                ambiguous = True
                continue
            total += area
        if ambiguous:
            state, reason = "unknown", "Есть договоры без однозначного корпуса, квартиры или площади либо с противоречивой площадью или ценой одного договора; темп не подтверждён."
        else:
            observed = total / 3
            meta = coverage if isinstance(coverage, dict) else {}
            first, last = day(meta.get("from")), day(meta.get("through"))
            if first and last and first <= start and end <= last <= day(today):
                state = "ok"
            else:
                reason = ("Полнота контрактации за три завершённых месяца не подтверждена "
                          "датами покрытия источника; подтверждённый прогноз срока распродажи не рассчитан.")
    return {"pace_months": sorted(months), "pace_state": state, "pace_reason": reason,
            "pace_area": observed if state == "ok" else None,
            "pace_observed_area": observed, "pace_duplicate_rows": duplicates}


def overlay(snapshot: dict | None, contracts: list[dict] | None, today: str,
            coverage: dict | None = None) -> dict | None:
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
    for row in contracts or []:
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
    corps = {x["building"] for x in inventory}
    pace = _pace(contracts, corps, today, coverage)
    area_left = sum(x["area"] for x in available)
    confirmed = (area_left / pace["pace_area"]
                 if pace["pace_area"] is not None and pace["pace_area"] > 0 else None)
    conditional = (area_left / pace["pace_observed_area"]
                   if pace["pace_state"] == "partial" and pace["pace_observed_area"]
                   and pace["pace_observed_area"] > 0 else None)
    return {"state": "ok", "as_of": sorted({x["as_of"] for x in inventory}),
            "buildings": sorted(corps),
            "counts": dict(counts), "available": len(available), "available_area": area_left,
            "valuation": sum(x["amount"] for x in known) if len(known) == len(available) else None,
            "price_unconfirmed": len(available) - len(known), **pace,
            "months_to_sell": confirmed, "confirmed_months_to_sell": confirmed,
            "conditional_months_to_sell": conditional,
            "forecast_state": ("confirmed" if confirmed is not None else
                               "conditional" if conditional is not None else "unknown"),
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
    elif block.get("pace_state") == "ok":
        text += "За три завершённых месяца с подтверждённым покрытием источника нет положительного темпа продаж; срок распродажи не рассчитан. "
    else:
        text += (block.get("pace_reason") or "Темп продаж не подтверждён; срок распродажи не рассчитан.") + " "
        if block.get("pace_observed_area") is not None:
            text += (f"Только по найденным договорам — {ru(block['pace_observed_area'], 1)} м² в месяц; "
                     "это частичное наблюдение, не подтверждённый темп всего периода. ")
        if block.get("conditional_months_to_sell") is not None:
            text += (f"Условная оценка — {ru(block['conditional_months_to_sell'], 1)} месяца "
                     "при сохранении темпа по загруженным договорам; полнота периода не подтверждена. ")
    text += (f"Для объединения выделено квартир — {block['regrouping_units']}. Состав новых лотов, "
             "их цены и сроки выхода пока не заданы: в обычный прогноз они не включены. "
             "Это оценка свободного остатка по текущим ценам, а не график поступлений на эскроу.")
    if block["unknown_status"]:
        text += f" Не распознаны статусы {block['unknown_status']} квартир; они исключены из остатка."
    return "<section class='chessboard-overlay'><h3>Остаток по шахматке и темп продаж</h3><p>" + html.escape(text) + "</p></section>"
