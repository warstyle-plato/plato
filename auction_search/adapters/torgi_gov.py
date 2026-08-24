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

Сверка по памяти модели уже пробована (24.08.2026) и не подтвердила НИ ОДНОГО
имени поля: без спецификации или живого ответа контракт API не восстанавливается,
и добросовестный ответ на такой вопрос — «не знаю». Один результат она всё же
дала, и он из права, а не из API: 178-ФЗ — это приватизация государственного и
муниципального имущества, то есть городской рынок; банкротство — 127-ФЗ. Отсюда
общее правило: **чужая уверенность — не проба.** Пока `probe()` не сходил с ядра,
имена полей остаются догадкой, как бы уверенно они ни выглядели.
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

# Виды торгов. Сами КОДЫ не сверены ответом сервиса — см. оговорку в шапке;
# сверено другое, и это не про API, а про право: 178-ФЗ — приватизация
# государственного и муниципального имущества, то есть ровно городской рынок,
# а не банкротный. Продавец там город, и в наш список он попадает как CITY.
# Банкротство — 127-ФЗ «О несостоятельности (банкротстве)».
PRIVATIZATION_CODES = ("178FZ",)
BANKRUPTCY_CODES = ("127FZ", "BANKRUPTCY")

# Слова, по которым происхождение опознаётся, когда код не опознан. Здесь
# только ДОКАЗАТЕЛЬНЫЕ: «конкурсное производство» — процедура банкротства,
# а голое «конкурсн» ловит «конкурсную документацию» и «конкурсную комиссию»
# обычных городских торгов. «Должник» тоже убран: имущество должника продают
# и приставы вне дела о банкротстве, а третьего значения у нас нет — лучше
# OTHER, чем уверенно неверная метка.
BANKRUPTCY_WORDS = (
    "банкрот", "несостоятельн", "конкурсное производство", "конкурсный управляющий",
)

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
    # Порядок здесь не косметический. Слова процедуры — знание о праве и верны
    # сами по себе; коды — наша догадка о справочнике сервиса, не сверенная
    # живым ответом. Поэтому догадка не отменяет доказательства: карточка,
    # прямо называющая конкурсное производство, банкротная при любом коде.
    origin = LotOrigin.OTHER
    if any(word in name for word in BANKRUPTCY_WORDS) \
            or any(word in blob for word in BANKRUPTCY_WORDS):
        origin = LotOrigin.BANKRUPTCY
    elif code in BANKRUPTCY_CODES:
        origin = LotOrigin.BANKRUPTCY
    elif code in PRIVATIZATION_CODES:
        origin = LotOrigin.CITY
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
        """Разобранная страница. Адрес собирается там же, где для пробы.

        Второй сборки адреса не заводим: проба и рабочий сбор обязаны ходить
        по одному и тому же URL, иначе сверенное пробой относится не к тому
        запросу, который потом пойдёт в дело.
        """
        _status, _ctype, body = self._fetch_raw(self._search_url(page))
        return json.loads(body)

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

        Проба существует, чтобы ПОКАЗАТЬ ответ, поэтому она ничего не
        обрезает по ключам: поле, которого мы не ждём, — как раз то, ради
        чего сюда идут, и урезанный список выглядел бы полным. Обрезаются
        только длинные значения, имена ключей остаются целиком.

        И она не верит собственным догадкам. Адрес, код ответа и тип
        содержимого печатаются; не-JSON показывается началом тела, а не
        падает невнятной ошибкой разбора; массив лотов ищется по нашему
        предполагаемому ключу, а не нашёлся — берётся первый список словарей,
        и это говорится вслух. Иначе неверная догадка об оболочке читалась бы
        как «лотов нет».
        """
        url = self._search_url(page)
        try:
            status, ctype, body = self._fetch_raw(url)
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "url": url, "reason": str(exc)}
        try:
            payload = json.loads(body)
        except ValueError as exc:
            return {"ok": False, "url": url, "http_status": status,
                    "content_type": ctype,
                    "reason": f"ответ не JSON: {exc}",
                    "body_head": body[:600]}
        if not isinstance(payload, dict):
            return {"ok": False, "url": url, "http_status": status,
                    "reason": f"ответ не объект, а {type(payload).__name__}",
                    "body_head": body[:600]}

        cards, array_key, envelope_note = _find_cards(payload)
        first = cards[0] if cards else {}
        lot = to_lot(first, datetime.now(timezone.utc).isoformat()) if first else None
        return {
            "ok": True,
            "url": url,
            "http_status": status,
            "content_type": ctype,
            "envelope_keys": sorted(payload),
            "array_key": array_key,
            "envelope_note": envelope_note,
            "on_page": len(cards),
            "field_counts": _field_counts(cards),
            "raw_first": {key: _short(value) for key, value in sorted(first.items())},
            "parsed_first": lot.to_dict() if lot is not None else None,
            "parsed_note": None if lot is not None else
                "лот не собрался: обязательного поля нет или оно названо иначе",
        }

    def _search_url(self, page: int) -> str:
        query = urllib.parse.urlencode({
            "dynSubjRF": ",".join(self.subject_codes),
            "page": page,
            "size": PAGE_SIZE,
            "sort": "firstVersionPublicationDate,desc",
        })
        return f"https://{HOST}{SEARCH_PATH}?{query}"

    def _fetch_raw(self, url: str) -> tuple[int, str, str]:
        request = urllib.request.Request(url, headers={
            "User-Agent": USER_AGENT, "Accept": "application/json"})
        with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
            body = response.read().decode("utf-8", "replace")
            ctype = response.headers.get("Content-Type", "")
            return int(getattr(response, "status", 0) or 0), ctype, body


def _short(value: Any, limit: int = 300) -> Any:
    """Длинное значение — обрезком, но с пометкой. Ключ не трогаем никогда."""
    if isinstance(value, str) and len(value) > limit:
        return value[:limit] + f"… (ещё {len(value) - limit} симв.)"
    if isinstance(value, list) and len(value) > 5:
        return value[:5] + [f"… (ещё {len(value) - 5} элем.)"]
    return value


def _find_cards(payload: dict[str, Any]) -> tuple[list[dict[str, Any]], str | None, str | None]:
    """Массив лотов в ответе: по нашему ключу, а не нашёлся — по форме.

    Возвращает и то, каким путём он найден. Догадка, сработавшая случайно,
    и догадка, подтверждённая ответом, для читателя пробы — разные вещи.
    """
    guess = payload.get("content")
    if isinstance(guess, list) and (not guess or isinstance(guess[0], dict)):
        return [item for item in guess if isinstance(item, dict)], "content", None
    for key, value in payload.items():
        if isinstance(value, list) and value and isinstance(value[0], dict):
            return ([item for item in value if isinstance(item, dict)], key,
                    f"ключа «content» в ответе нет — массив взят из «{key}»")
    return [], None, "массива словарей в ответе не нашлось: оболочка другая"


def _field_counts(cards: list[dict[str, Any]]) -> dict[str, int]:
    """Сколько карточек на странице несут каждый ключ.

    По одной карточке необязательное поле неотличимо от отсутствующего:
    ключ, стоящий у трёх лотов из пятидесяти, надо увидеть до того, как
    разбор начнёт считать его обязательным.
    """
    counts: dict[str, int] = {}
    for card in cards:
        for key in card:
            counts[key] = counts.get(key, 0) + 1
    return dict(sorted(counts.items()))
