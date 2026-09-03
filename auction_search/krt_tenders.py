"""Торги по КРТ: связать лот с площадкой каталога.

«У нас не отработана система поиска информации о торгах по КРТ» (владелец,
31.08.2026). Два модуля жили рядом и не разговаривали: торги знали про лоты,
каталог — про площадки, а вопрос «эту площадку уже выставили?» не задавался
нигде, хотя ИнвестМосква ищется в том числе по словам «комплексное развитие
территории» — то есть лоты КРТ в выдаче есть с самого начала.

Что ещё удалось измерить (31.08.2026, живые ответы mos.ru): город объявляет
такие торги распоряжением ДГП — «О проведении торгов в форме аукциона на право
заключения договора о комплексном развитии территории», их 53 штуки. Но АДРЕСА
в них нет: ни в заголовке, ни в карточке документа, а сам PDF — скан, из
которого извлекается только регистрационный штамп. Поэтому распоряжение
показывается фактом со ссылкой и датой, а к площадке не привязывается: привязка
по номеру распоряжения была бы выдумкой.

Привязывается лот — у него есть адрес и кадастровые номера. Правило совпадения
берётся то же, что у решений: улица держится за своим владением, иначе ложная
привязка объявит площадку проданной.
"""

from __future__ import annotations

import re
from typing import Any, Iterable

from market_search.krt_decisions import same_place

_CADASTRAL = re.compile(r"\b\d{2}:\d{2}:\d{5,8}:\d+\b")
# Площадь в заголовке лота: «площадью 14,62 га», «площадью 16,9 га».
_HECTARES = re.compile(r"(?iu)площад\w*\s+(\d{1,4}(?:[.,]\d{1,3})?)\s*га\b")
# Слова, по которым лот вообще считается КРТ-лотом. Без них в связку попадёт
# любой участок на той же улице: город продаёт их сотнями, и «право на КРТ» от
# «продажи участка» отличается только этими словами.
_KRT_WORDS = ("комплексн", "крт")


def looks_like_krt(lot: dict[str, Any]) -> bool:
    """Лот про КРТ — по словам самого лота, а не по нашему предположению."""
    text = " ".join(str(lot.get(key) or "") for key in
                    ("title", "procedure_type", "permitted_use", "lot_kind")).lower()
    return any(word in text for word in _KRT_WORDS)


def _where(lot: dict[str, Any]) -> str:
    return " ".join(str(lot.get(key) or "") for key in ("address", "title")).strip()


def lot_hectares(lot: dict[str, Any]) -> float | None:
    """Площадь территории лота в гектарах: из поля, иначе из заголовка.

    Город пишет её прямо в имени процедуры, и это второй якорь тождества —
    жёстче адреса там, где адреса у площадки по сути нет («МКАД 41 км»,
    «производственная зона № 54 „Прожектор“»). Именно на таких трёх лотах из
    шести привязка и отказывала (03.09.2026).
    """
    metres = lot.get("land_area_sqm")
    try:
        value = float(metres)
    except (TypeError, ValueError):
        value = 0.0
    if value > 0:
        return round(value / 10_000.0, 2)
    found = _HECTARES.search(" ".join(str(lot.get(key) or "")
                                      for key in ("title", "address")))
    if not found:
        return None
    try:
        return round(float(found.group(1).replace(",", ".")), 2)
    except ValueError:
        return None


def _site_hectares(site: dict[str, Any]) -> float | None:
    try:
        value = float(site.get("area_ha"))
    except (TypeError, ValueError):
        return None
    return round(value, 2) if value > 0 else None


def match(lots: Iterable[dict[str, Any]], sites: Iterable[dict[str, Any]]) -> dict[str, Any]:
    """Разложить лоты по площадкам. Не сопоставленный лот не пропадает."""
    site_rows = [
        {"slug": str(site.get("slug") or ""), "name": str(site.get("name") or ""),
         "okrug": str(site.get("okrug") or ""),
         "cadastres": {number for number in
                       _CADASTRAL.findall(" ".join(str(site.get(key) or "")
                                                   for key in ("name", "cadastral_numbers")))},
         "hectares": _site_hectares(site)}
        for site in sites or []
    ]
    # Площадь годится в якорь только там, где она в каталоге ЕДИНСТВЕННАЯ: на
    # 280 площадок приходится 250 разных значений, и совпавшая дважды не
    # опознаёт ничего. Считается один раз на весь разбор.
    counts: dict[float, int] = {}
    for site in site_rows:
        if site["hectares"] is not None:
            counts[site["hectares"]] = counts.get(site["hectares"], 0) + 1
    unique_area = {value: site for value, count in counts.items() if count == 1
                   for site in site_rows if site["hectares"] == value}
    by_site: dict[str, list[dict[str, Any]]] = {}
    orphans: list[dict[str, Any]] = []
    checked = 0
    matched_by_area = 0
    for lot in lots or []:
        if not looks_like_krt(lot):
            continue
        checked += 1
        where = _where(lot)
        cadastres = set(lot.get("cadastral_numbers") or [])
        hit = None
        for site in site_rows:
            # Кадастровый номер — жёсткое тождество, и он сильнее адреса.
            if cadastres and site["cadastres"] & cadastres:
                hit = site
                break
            if lot.get("okrug") and site["okrug"] and lot["okrug"] != site["okrug"]:
                continue
            if where and site["name"] and same_place(where, site["name"]):
                hit = site
                break
        if hit is None:
            # Адрес не опознал — пробуем площадь. Она слабее кадастра и адреса
            # и потому идёт последней, но сильнее молчания: «площадка не
            # опознана» читается как её отсутствие в каталоге, а все три
            # неопознанные 03.09.2026 в каталоге были.
            hectares = lot_hectares(lot)
            by_area = unique_area.get(hectares) if hectares is not None else None
            if by_area is not None and (
                    not lot.get("okrug") or not by_area["okrug"]
                    or lot["okrug"] == by_area["okrug"]):
                hit = by_area
                matched_by_area += 1
        summary = {
            "title": str(lot.get("title") or ""),
            "url": str((lot.get("source") or {}).get("lot_url") or lot.get("url") or ""),
            "address": str(lot.get("address") or ""),
            "price_rub": lot.get("current_price_rub") or lot.get("start_price_rub"),
            "deadline": lot.get("application_deadline"),
            "auction_date": lot.get("auction_date"),
            "source": str((lot.get("source") or {}).get("catalogue")
                          or (lot.get("source") or {}).get("name") or ""),
        }
        if hit:
            by_site.setdefault(hit["slug"], []).append(summary)
        else:
            # Лот про КРТ, площадку которого мы не опознали, — это находка, а
            # не мусор: возможно, каталог её ещё не показывает.
            orphans.append(summary)
    return {"by_site": by_site, "unmatched": orphans, "krt_lots": checked,
            "matched_by_area": matched_by_area}
