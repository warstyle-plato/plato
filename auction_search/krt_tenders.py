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


def match(lots: Iterable[dict[str, Any]], sites: Iterable[dict[str, Any]]) -> dict[str, Any]:
    """Разложить лоты по площадкам. Не сопоставленный лот не пропадает."""
    site_rows = [
        {"slug": str(site.get("slug") or ""), "name": str(site.get("name") or ""),
         "okrug": str(site.get("okrug") or ""),
         "cadastres": {number for number in
                       _CADASTRAL.findall(" ".join(str(site.get(key) or "")
                                                   for key in ("name", "cadastral_numbers")))}}
        for site in sites or []
    ]
    by_site: dict[str, list[dict[str, Any]]] = {}
    orphans: list[dict[str, Any]] = []
    checked = 0
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
    return {"by_site": by_site, "unmatched": orphans, "krt_lots": checked}
