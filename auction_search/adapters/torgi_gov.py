"""ГИС Торги (torgi.gov.ru) — банкротные лоты и прочее имущество должников.

Наши три источника продают ГОРОДСКОЕ имущество. Реестры, которые смотрит
девелопер, наполовину состоят из другого: имущественные комплексы, нежилые
здания и незавершёнка от арбитражных управляющих, залоговых кредиторов и
госкорпораций. Ни один из них через РАД, Росэлторг и «Торги Москвы» не виден —
разница не в фильтре, а в источнике (владелец, 24.08.2026).

Почему ГИС Торги, а не площадки банкротства напрямую: их десятки — Сбербанк-АСТ,
Фабрикант, Ютендер, Центр реализации, — один и тот же лот лежит на нескольких
сразу, и склеивать дубли пришлось бы нам. ГИС Торги — официальный агрегатор с
машинным ответом, и извещение там одно на лот.

## Чего этот файл НЕ знает

Живой пробы отсюда сделать нельзя: torgi.gov.ru закрыт сетевой политикой
песочницы, как НСПД. Поэтому коды видов торгов и имена полей взяты из открытого
описания и НЕ сверены ответом сервиса. Пока не сверены — адаптер выключен и
включается переменной `TORGI_GOV_DISCOVERY=1`, а разбор поля, которого нет в
ответе, даёт пропуск с причиной, а не выдуманное значение.

Проверять это надо с ядра — тем же способом, что и слои НСПД: `probe()` печатает
сырой ответ и разобранный лот рядом, чтобы расхождение было видно глазами, а не
вылезло числом в отчёте.
"""

from __future__ import annotations

import json
import os
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from typing import Any, Iterable

from auction_search.adapters.base import AuctionPlatformAdapter
from auction_search.models import (
    AuctionLot, AuctionSource, LotKind, LotOrigin, SourceKind,
)


FLAG = "TORGI_GOV_DISCOVERY"
HOST = "torgi.gov.ru"
SEARCH_PATH = "/new/api/public/lotcards/search"
LOT_URL = "https://torgi.gov.ru/new/public/lots/lot/{id}"
USER_AGENT = "DevelopAid-AuctionCollector/0.1 (+https://developaid.ru)"
TIMEOUT_SECONDS = 8
PAGE_SIZE = 50
MAX_PAGES = 4

# Субъекты, которые нас интересуют: Москва и область. Коды ОКАТО/справочника
# ГИС Торги; регион приходит и текстом, поэтому проверяется и он.
SUBJECT_CODES = ("77", "50")
SUBJECT_WORDS = ("москва", "московская")

# Виды торгов, относящиеся к имуществу должников. Список НЕ сверен ответом
# сервиса — см. оговорку в шапке. Поэтому классификация идёт и по коду, и по
# тексту названия: код может оказаться другим, слово «банкрот» — вряд ли.
BANKRUPTCY_CODES = ("178FZ", "127FZ", "BANKRUPTCY")
BANKRUPTCY_WORDS = ("банкрот", "должник", "конкурсн")

# Что считаем интересным для девелопмента. Слова из названия и назначения лота:
# у ГИС Торгов своей рубрики «под редевелопмент» нет и быть не может.
LAND_WORDS = ("земельн", "участок", "зу ")
BUILDING_WORDS = ("здание", "помещен", "комплекс", "незавершен", "незавершён", "сооружен")


def _text(value: Any) -> str:
    return " ".join(str(value or "").split())


def _number(value: Any) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if result == result and abs(result) != float("inf") else None


def _moment(value: Any) -> str | None:
    text = _text(value)
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).isoformat()
    except ValueError:
        return None


def classify(card: dict[str, Any]) -> tuple[LotKind, LotOrigin]:
    """Вид и происхождение лота по тому, что написано в извещении.

    Ни то ни другое не выдумывается: не опознали — `OTHER`, и лот виден в
    списке как «другое», а не подогнан под ближайшую рубрику.
    """
    blob = " ".join(_text(card.get(key)).lower() for key in (
        "lotName", "lotDescription", "category", "biddType", "characteristics"))
    bidd = card.get("biddType") or {}
    code = _text(bidd.get("code") if isinstance(bidd, dict) else bidd).upper()
    name = _text(bidd.get("name") if isinstance(bidd, dict) else "").lower()
    origin = LotOrigin.OTHER
    if code in BANKRUPTCY_CODES or any(word in name for word in BANKRUPTCY_WORDS) \
            or any(word in blob for word in BANKRUPTCY_WORDS):
        origin = LotOrigin.BANKRUPTCY
    kind = LotKind.OTHER
    if any(word in blob for word in ("незавершен", "незавершён")):
        kind = LotKind.UNFINISHED
    elif "комплекс" in blob:
        kind = LotKind.PROPERTY_COMPLEX
    elif any(word in blob for word in LAND_WORDS):
        kind = LotKind.LAND_SALE
    elif any(word in blob for word in BUILDING_WORDS):
        kind = LotKind.PROPERTY_COMPLEX
    return kind, origin


def to_lot(card: dict[str, Any], fetched_at: str) -> AuctionLot | None:
    """Карточка ГИС Торгов в наш лот. Без обязательного — пропуск."""
    lot_id = _text(card.get("id") or card.get("lotId"))
    title = _text(card.get("lotName") or card.get("lotDescription"))
    if not lot_id or not title:
        return None
    kind, origin = classify(card)
    start = _number(card.get("estimatedPrice") or card.get("startPrice"))
    now = _number(card.get("priceFin") or card.get("currentPrice"))
    minimal = _number(card.get("priceMin"))
    source = AuctionSource(
        platform=SourceKind.TORGI_GOV,
        lot_url=LOT_URL.format(id=urllib.parse.quote(lot_id)),
        external_lot_id=lot_id,
        fetched_at=fetched_at,
        source_name="ГИС Торги (torgi.gov.ru)",
    )
    return AuctionLot(
        source=source,
        lot_kind=kind,
        title=title,
        origin=origin,
        address=_text(card.get("estateAddress") or card.get("lotAddress")) or None,
        cadastral_numbers=[
            _text(item) for item in (card.get("cadastralNumbers") or []) if _text(item)],
        land_area_sqm=_number(card.get("estateArea") or card.get("area")),
        permitted_use=_text(card.get("permittedUse")) or None,
        organizer=_text((card.get("seller") or {}).get("name")
                        if isinstance(card.get("seller"), dict) else card.get("seller")) or None,
        procedure_type=_text((card.get("biddType") or {}).get("name")
                             if isinstance(card.get("biddType"), dict) else card.get("biddType")) or None,
        start_price_rub=start,
        current_price_rub=now if now is not None else start,
        min_price_rub=minimal,
        application_deadline=_moment(card.get("biddEndTime")),
    )


class TorgiGovAdapter(AuctionPlatformAdapter):
    """Банкротные и прочие лоты имущества должников из ГИС Торгов."""

    def __init__(self, *, subject_codes: tuple[str, ...] = SUBJECT_CODES) -> None:
        self.subject_codes = subject_codes
        self.last_report: dict[str, Any] = {"pages": 0, "cards": 0, "kept": 0, "reason": ""}

    @property
    def platform_name(self) -> str:
        return "ГИС Торги (torgi.gov.ru)"

    @staticmethod
    def enabled() -> bool:
        """Пока коды видов торгов не сверены живым ответом — выключено.

        Включённый непроверенный источник хуже отсутствующего: он приносит
        лоты, и они выглядят так же, как проверенные.
        """
        return str(os.getenv(FLAG, "")).strip().lower() in ("1", "true", "yes", "on")

    def _fetch_page(self, page: int) -> dict[str, Any]:
        query = urllib.parse.urlencode({
            "dynSubjRF": ",".join(self.subject_codes),
            "page": page,
            "size": PAGE_SIZE,
            "sort": "firstVersionPublicationDate,desc",
        })
        url = f"https://{HOST}{SEARCH_PATH}?{query}"
        request = urllib.request.Request(url, headers={
            "User-Agent": USER_AGENT, "Accept": "application/json"})
        with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
            return json.loads(response.read().decode("utf-8"))

    def discover_moscow(self) -> Iterable[AuctionLot]:
        if not self.enabled():
            self.last_report = {"pages": 0, "cards": 0, "kept": 0,
                                "reason": f"источник выключен: нет {FLAG}=1"}
            return []
        fetched_at = datetime.now(timezone.utc).isoformat()
        lots: list[AuctionLot] = []
        cards = pages = 0
        reason = ""
        for page in range(MAX_PAGES):
            try:
                payload = self._fetch_page(page)
            except Exception as exc:  # noqa: BLE001
                # Молчаливый пустой список читался бы как «лотов нет».
                reason = f"страница {page}: {exc}"
                break
            pages += 1
            content = payload.get("content") or []
            cards += len(content)
            for card in content:
                lot = to_lot(card, fetched_at)
                if lot is not None:
                    lots.append(lot)
            if len(content) < PAGE_SIZE:
                break
        self.last_report = {"pages": pages, "cards": cards, "kept": len(lots), "reason": reason}
        return lots

    def fetch_lot(self, lot_url: str) -> AuctionLot:
        raise NotImplementedError(
            "Разбор одного лота ГИС Торгов пока не сделан: сначала надо сверить "
            "поля живым ответом с ядра")

    def probe(self, page: int = 0) -> dict[str, Any]:
        """Сырой ответ и разобранный лот рядом — для сверки с ядра.

        Коды видов торгов и имена полей взяты из описания и не сверены. Пока их
        не сверили глазами, любой лот отсюда — предположение.
        """
        try:
            payload = self._fetch_page(page)
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "reason": str(exc)}
        content = payload.get("content") or []
        first = content[0] if content else {}
        lot = to_lot(first, datetime.now(timezone.utc).isoformat()) if first else None
        return {
            "ok": True,
            "total": payload.get("totalElements"),
            "on_page": len(content),
            "raw_keys": sorted(first)[:40],
            "raw_first": {key: first.get(key) for key in list(sorted(first))[:20]},
            "parsed_first": lot.to_dict() if lot is not None else None,
        }
