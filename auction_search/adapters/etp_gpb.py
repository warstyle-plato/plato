from __future__ import annotations

import json
import re
from datetime import datetime
from typing import Any
from urllib.parse import urlencode, urljoin, urlparse
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

from auction_search import deadline as clock
from auction_search.adapters.base import AuctionPlatformAdapter
from auction_search.classifier import classify_lot, origin_from_evidence
from auction_search.models import (
    AuctionLot,
    AuctionSource,
    LotKind,
    Provenance,
    SourceKind,
    utc_now_iso,
)
from auction_search.parsing import cadastral_numbers, normalize_space, parse_area_sqm, parse_decimal


_MOSCOW = ZoneInfo("Europe/Moscow")
_MOSCOW_REGION_RE = re.compile(r"московск\w*\s+област", re.I)
_MOSCOW_CITY_RE = re.compile(r"(?:^|[,;\s])(?:г\.?\s*)?москв(?:а|ы|е|у|ой)(?:$|[,;\s])", re.I)
_ASSET_RE = re.compile(
    r"(?:земельн\w*\s+участ\w*|недвижим\w*|здани\w*|"
    r"имущественн\w*\s+комплекс\w*|незавершенн\w*|\bкрт\b|"
    r"комплексн\w*\s+развити\w*\s+территор\w*)",
    re.I,
)
_PROCUREMENT_RE = re.compile(
    r"(?:закупк\w*|поставк\w*|выполнени\w*\s+работ\w*|оказани\w*\s+услуг\w*|"
    r"ценов\w*\s+запрос\w*|запрос\w*\s+(?:котиров\w*|предложени\w*))",
    re.I,
)
_PROCUREMENT_KINDS = {"fz44", "fz223", "price_request", "purchase", "procurement"}


class ETPGPBAdapter(AuctionPlatformAdapter):
    """Официальный публичный каталог ЭТП ГПБ.

    Площадка сама публикует JSON API для программной интеграции. Мы ищем
    несколькими предметными фразами, затем повторно проверяем Москву и
    девелоперский предмет по полям самой площадки. Закупки стройматериалов и
    Московская область поэтому не попадают в каталог московских объектов.
    """

    HOST = "etpgpb.ru"
    API_URL = "https://etpgpb.ru/api/v2/procedures/"
    USER_AGENT = "DevelopAid-AuctionCollector/0.1 (+https://developaid.ru)"
    SEARCH_TERMS = (
        "продажа земельного участка",
        "продажа недвижимого имущества",
        "имущественный комплекс",
        "объект незавершенного строительства",
        "комплексное развитие территории",
    )
    PAGE_SIZE = 100

    def __init__(self) -> None:
        self.last_report = self._empty_report()

    @property
    def platform_name(self) -> str:
        return "ЭТП ГПБ"

    def _empty_report(self) -> dict[str, Any]:
        return {
            "source": self.platform_name,
            "queries": 0,
            "cards": 0,
            "kept": 0,
            "skipped": 0,
            "reason": "",
        }

    @classmethod
    def _search_url(cls, term: str) -> str:
        return cls.API_URL + "?" + urlencode({
            "page": "1",
            "per": str(cls.PAGE_SIZE),
            "sort": "by_relevance",
            "procedure[stage][0]": "accepting",
            "search": term,
        })

    @classmethod
    def _read_json(cls, url: str, deadline: float | None = None) -> dict[str, Any]:
        req = Request(url, headers={
            "User-Agent": cls.USER_AGENT,
            "Accept": "application/json",
            "Accept-Language": "ru-RU,ru;q=0.9",
        })
        with urlopen(req, timeout=clock.timeout(deadline, 12)) as response:
            payload = json.loads(response.read().decode("utf-8", errors="replace"))
        if not isinstance(payload, dict):
            raise ValueError("официальный API ЭТП ГПБ вернул не объект JSON")
        return payload

    @staticmethod
    def _attrs(item: dict[str, Any]) -> dict[str, Any]:
        attrs = item.get("attributes")
        return attrs if isinstance(attrs, dict) else {}

    @staticmethod
    def _is_moscow(attrs: dict[str, Any]) -> bool:
        regions = attrs.get("lot_regions") or []
        if isinstance(regions, str):
            regions = [regions]
        for region in regions:
            value = normalize_space(str(region)).lower().replace("ё", "е")
            if _MOSCOW_REGION_RE.search(value):
                continue
            if value in {"москва", "г. москва", "г москва", "город москва"} or _MOSCOW_CITY_RE.search(value):
                return True
        text = normalize_space(str(attrs.get("title") or ""))
        without_region = _MOSCOW_REGION_RE.sub("", text)
        return bool(_MOSCOW_CITY_RE.search(without_region))

    @staticmethod
    def _is_development(attrs: dict[str, Any]) -> bool:
        title = normalize_space(str(attrs.get("title") or ""))
        procedure = normalize_space(str(attrs.get("procedure_type_name") or ""))
        kind = normalize_space(str(attrs.get("kind") or "")).lower()
        if not _ASSET_RE.search(title):
            return False
        if kind in _PROCUREMENT_KINDS or _PROCUREMENT_RE.search(" ".join((title, procedure))):
            return False
        return True

    @staticmethod
    def _moment(value: Any) -> str | None:
        raw = normalize_space(str(value or ""))
        if not raw:
            return None
        try:
            parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError:
            return None
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=_MOSCOW)
        return parsed.isoformat()

    @staticmethod
    def _future(value: str | None) -> bool:
        if not value:
            return False
        try:
            parsed = datetime.fromisoformat(value)
        except ValueError:
            return False
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=_MOSCOW)
        return parsed.astimezone(_MOSCOW) >= datetime.now(_MOSCOW)

    @classmethod
    def _lot_url(cls, item: dict[str, Any], attrs: dict[str, Any]) -> str:
        path = normalize_space(str(attrs.get("rebranding_truncated_path") or ""))
        if path:
            return urljoin("https://etpgpb.ru", path)
        platform = normalize_space(str(attrs.get("platform_url") or ""))
        if platform:
            return platform
        return f"https://etpgpb.ru/procedures/{item.get('id') or attrs.get('registry_number') or ''}"

    @classmethod
    def _to_lot(cls, item: dict[str, Any], fetched_at: str) -> AuctionLot | None:
        attrs = cls._attrs(item)
        title = normalize_space(str(attrs.get("title") or ""))
        if not title or not cls._is_moscow(attrs) or not cls._is_development(attrs):
            return None
        deadline = cls._moment(attrs.get("end_registration"))
        if str(attrs.get("stage") or "").lower() != "accepting" or not cls._future(deadline):
            return None
        procedure = normalize_space(str(attrs.get("procedure_type_name") or attrs.get("kind") or "")) or None
        lot_kind = classify_lot(title, procedure or "")
        if lot_kind is LotKind.OTHER:
            return None
        area = parse_area_sqm(title)
        price = parse_decimal(str(attrs.get("amount") or ""))
        if price is not None and price <= 0:
            price = None
        lot_url = cls._lot_url(item, attrs)
        external_id = normalize_space(str(attrs.get("registry_number") or item.get("id") or lot_url))
        cad = cadastral_numbers(title)
        source = AuctionSource(
            platform=SourceKind.ETP_GPB,
            lot_url=lot_url,
            external_lot_id=external_id,
            fetched_at=fetched_at,
            source_name="ЭТП ГПБ",
        )
        lot = AuctionLot(
            source=source,
            lot_kind=lot_kind,
            title=title,
            origin=origin_from_evidence(procedure_type=procedure, text=title),
            address=title[:1000] if not cad else None,
            cadastral_numbers=cad,
            land_area_sqm=area if lot_kind in {LotKind.LAND_SALE, LotKind.LAND_LEASE, LotKind.KRT} else None,
            building_area_sqm=area if lot_kind in {LotKind.PROPERTY_COMPLEX, LotKind.UNFINISHED} else None,
            procedure_type=procedure,
            start_price_rub=price,
            current_price_rub=price,
            application_deadline=deadline,
            status="Приём заявок",
            raw={
                "api_item_id": str(item.get("id") or ""),
                "regions": attrs.get("lot_regions") or [],
                "published_at": cls._moment(attrs.get("date_published")),
                "api_attributes": attrs,
            },
        )
        for field, value in {
            "title": title,
            "cadastral_numbers": ", ".join(cad),
            "land_area_sqm": str(lot.land_area_sqm) if lot.land_area_sqm else None,
            "building_area_sqm": str(lot.building_area_sqm) if lot.building_area_sqm else None,
            "start_price_rub": str(price) if price is not None else None,
            "application_deadline": deadline,
            "procedure_type": procedure,
            "status": lot.status,
        }.items():
            if value:
                lot.provenance[field] = Provenance(
                    source_url=lot_url, fetched_at=fetched_at, raw_value=value)
        return lot

    def discover_moscow(self, *, deadline: float | None = None) -> list[AuctionLot]:
        self.last_report = self._empty_report()
        found: list[AuctionLot] = []
        seen: set[str] = set()
        errors: list[str] = []
        fetched_at = utc_now_iso()
        for term in self.SEARCH_TERMS:
            if clock.expired(deadline):
                break
            try:
                payload = self._read_json(self._search_url(term), deadline)
            except Exception as exc:  # noqa: BLE001
                errors.append(f"{term}: {type(exc).__name__}")
                continue
            self.last_report["queries"] += 1
            items = payload.get("data") or []
            if not isinstance(items, list):
                errors.append(f"{term}: data не является списком")
                continue
            self.last_report["cards"] += len(items)
            for item in items:
                if not isinstance(item, dict):
                    self.last_report["skipped"] += 1
                    continue
                lot = self._to_lot(item, fetched_at)
                if lot is None:
                    self.last_report["skipped"] += 1
                    continue
                if lot.source.external_lot_id in seen:
                    continue
                seen.add(lot.source.external_lot_id)
                found.append(lot)
        self.last_report["kept"] = len(found)
        if errors:
            self.last_report["reason"] = "не выполнены запросы: " + "; ".join(errors[:3])
        elif clock.expired(deadline) and self.last_report["queries"] < len(self.SEARCH_TERMS):
            self.last_report["reason"] = "частичный охват: общий срок каталога закончился"
        return found

    def fetch_lot(self, lot_url: str) -> AuctionLot:
        host = (urlparse(lot_url).hostname or "").lower()
        if not (host == self.HOST or host.endswith("." + self.HOST) or host == "gpb.ru" or host.endswith(".gpb.ru")):
            raise ValueError("ETPGPBAdapter принимает только официальные адреса ЭТП ГПБ")
        # У публичного API нет стабильной связи между всеми историческими URL
        # и id записи. Ищем точный видимый номер/последний сегмент и принимаем
        # только карточку, URL или номер которой совпали.
        token = next((part for part in reversed(urlparse(lot_url).path.split("/")) if part), "")
        payload = self._read_json(self._search_url(token or lot_url))
        fetched_at = utc_now_iso()
        for item in payload.get("data") or []:
            if not isinstance(item, dict):
                continue
            attrs = self._attrs(item)
            candidate = self._lot_url(item, attrs)
            if candidate.rstrip("/") != lot_url.rstrip("/") and token not in {
                str(item.get("id") or ""), str(attrs.get("registry_number") or "")
            }:
                continue
            lot = self._to_lot(item, fetched_at)
            if lot is not None:
                return lot
        raise ValueError("Официальный API ЭТП ГПБ не вернул эту карточку")
