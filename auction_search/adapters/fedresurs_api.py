from __future__ import annotations

import html as html_lib
import json
import os
import re
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta
from typing import Any
from urllib.parse import urlencode, urlparse
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

from auction_search import deadline as clock
from auction_search.adapters.base import AuctionPlatformAdapter
from auction_search.classifier import classify_lot, origin_from_evidence
from auction_search.models import AuctionLot, AuctionSource, LotKind, Provenance, SourceKind, utc_now_iso
from auction_search.parsing import cadastral_numbers, normalize_space, parse_area_sqm, parse_decimal


_MOSCOW = ZoneInfo("Europe/Moscow")
_MOSCOW_RE = re.compile(r"(?:^|[,;\s])(?:г\.?\s*)?москв(?:а|ы|е|у|ой)(?:$|[,;\s])", re.I)
_MOSCOW_REGION_RE = re.compile(r"московск\w*\s+област", re.I)
_DEVELOPMENT_RE = re.compile(
    r"(?:земельн\w*\s+участ\w*|имущественн\w*\s+комплекс\w*|"
    r"объект\w*\s+незавершенн\w*|\bкрт\b|нежил\w*|недвижим\w*|здани\w*)", re.I)
_TAG_RE = re.compile(r"<[^>]+>")


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _child(root: ET.Element, name: str) -> ET.Element | None:
    return next((item for item in root.iter() if _local(item.tag) == name), None)


def _text(root: ET.Element, name: str) -> str:
    item = _child(root, name)
    return normalize_space(html_lib.unescape("".join(item.itertext()))) if item is not None else ""


class FedresursApiAdapter(AuctionPlatformAdapter):
    """Официальный договорный REST API ЕФРСБ.

    Продуктивный сервис не является открытым API: логин и пароль выдаёт
    оператор Федресурса при подключении. Реквизиты берутся только из окружения,
    не сохраняются в лотах и не попадают в отчёт источника.
    """

    HOST = "fedresurs.ru"
    DEFAULT_BASE_URL = "https://bank-publications-prod.fedresurs.ru"
    LOGIN_ENV = "FEDRESURS_API_LOGIN"
    PASSWORD_ENV = "FEDRESURS_API_PASSWORD"
    BASE_URL_ENV = "FEDRESURS_API_BASE_URL"
    REQUEST_TIMEOUT_SECONDS = 12
    DAYS_BACK = 31
    LIMIT = 500
    deep_parse_unavailable = "Федресурс подключён к поиску через официальный API; отдельный разбор карточки не требуется."

    def __init__(self) -> None:
        self.last_report = self._empty_report()

    @property
    def platform_name(self) -> str:
        return "Федресурс / ЕФРСБ"

    def _empty_report(self) -> dict[str, Any]:
        return {"source": self.platform_name, "configured": self.configured(), "pages": 0,
                "cards": 0, "kept": 0, "skipped": 0, "reason": ""}

    @classmethod
    def configured(cls) -> bool:
        return bool(os.getenv(cls.LOGIN_ENV, "").strip() and os.getenv(cls.PASSWORD_ENV, "").strip())

    @classmethod
    def _base_url(cls) -> str:
        return os.getenv(cls.BASE_URL_ENV, cls.DEFAULT_BASE_URL).strip().rstrip("/")

    @classmethod
    def _json_request(cls, path: str, *, payload: dict[str, Any] | None = None,
                      token: str | None = None, deadline: float | None = None) -> Any:
        data = json.dumps(payload).encode("utf-8") if payload is not None else None
        headers = {"Accept": "application/json", "User-Agent": "DevelopAid-AuctionCollector/0.1"}
        if data is not None:
            headers["Content-Type"] = "application/json"
        if token:
            headers["Authorization"] = f"Bearer {token}"
        request = Request(cls._base_url() + path, data=data, headers=headers)
        with urlopen(request, timeout=clock.timeout(deadline, cls.REQUEST_TIMEOUT_SECONDS)) as response:
            return json.loads(response.read().decode("utf-8"))

    @classmethod
    def _token(cls, deadline: float | None) -> str:
        payload = cls._json_request("/v1/auth", payload={
            "login": os.environ[cls.LOGIN_ENV], "password": os.environ[cls.PASSWORD_ENV]}, deadline=deadline)
        token = str(payload.get("jwt") or "") if isinstance(payload, dict) else ""
        if not token:
            raise ValueError("Федресурс не вернул JWT")
        return token

    @classmethod
    def _messages(cls, token: str, deadline: float | None) -> dict[str, Any]:
        end = datetime.now(_MOSCOW)
        begin = end - timedelta(days=cls.DAYS_BACK)
        query = urlencode({
            "DatePublishBegin": "gte:" + begin.strftime("%Y-%m-%dT%H:%M:%S"),
            "DatePublishEnd": "lte:" + end.strftime("%Y-%m-%dT%H:%M:%S"),
            "Type": "BiddingInvitation", "IsAnnulled": "false", "IsLocked": "false",
            "IncludeContent": "true", "Sort": "DatePublish:desc", "Offset": 0, "Limit": cls.LIMIT,
        })
        payload = cls._json_request("/v1/trade-messages?" + query, token=token, deadline=deadline)
        return payload if isinstance(payload, dict) else {}

    @staticmethod
    def _message_url(guid: str) -> str:
        return "https://fedresurs.ru/bankruptmessage/" + guid.replace("-", "").upper()

    @classmethod
    def _lots_from_message(cls, message: dict[str, Any], fetched_at: str) -> list[AuctionLot]:
        content = str(message.get("content") or "")
        if not content:
            return []
        try:
            root = ET.fromstring(content)
        except ET.ParseError:
            return []
        application = _child(root, "Application")
        deadline = (application.attrib.get("TimeEnd") if application is not None else None)
        if not deadline:
            return []
        try:
            if datetime.fromisoformat(deadline).astimezone(_MOSCOW) < datetime.now(_MOSCOW):
                return []
        except ValueError:
            return []
        invitation = _child(root, "BiddingInvitation")
        trade_info = _child(root, "TradeInfo")
        organizer = _child(root, "TradeOrganizerCompany")
        if organizer is None:
            organizer = _child(root, "TradeOrganizerPerson")
        organizer_name = ""
        if organizer is not None:
            organizer_name = organizer.attrib.get("FullName") or " ".join(
                organizer.attrib.get(key, "") for key in ("LastName", "FirstName", "MiddleName"))
        message_guid = str(message.get("guid") or "")
        source_url = cls._message_url(message_guid)
        out: list[AuctionLot] = []
        for item in root.iter():
            if _local(item.tag) != "Lot":
                continue
            raw_title = _text(item, "TradeObjectHtml")
            title = normalize_space(_TAG_RE.sub(" ", html_lib.unescape(raw_title)))
            if not cls._is_moscow(title) or not _DEVELOPMENT_RE.search(title):
                continue
            kind = classify_lot(title, "банкротство")
            if kind is LotKind.OTHER:
                continue
            price = parse_decimal(_text(item, "StartPrice"))
            area = parse_area_sqm(title)
            cad = cadastral_numbers(title)
            lot_number = item.attrib.get("LotNumber") or "1"
            trade_number = ""
            trade = message.get("trade")
            if isinstance(trade, dict):
                trade_number = str(trade.get("number") or "")
            external_id = f"{message_guid}:{lot_number}"
            procedure = trade_info.attrib.get("AuctionType", "Банкротство") if trade_info is not None else "Банкротство"
            lot = AuctionLot(
                source=AuctionSource(SourceKind.FEDRESURS, source_url, external_id, fetched_at, "Федресурс / ЕФРСБ"),
                lot_kind=kind, title=title,
                origin=origin_from_evidence(procedure_type="банкротство", text=content),
                address=title[:1000] if not cad else None, cadastral_numbers=cad,
                land_area_sqm=area if kind in {LotKind.LAND_SALE, LotKind.LAND_LEASE, LotKind.KRT} else None,
                building_area_sqm=area if kind in {LotKind.PROPERTY_COMPLEX, LotKind.UNFINISHED} else None,
                organizer=normalize_space(organizer_name) or None,
                procedure_type=procedure, start_price_rub=price, current_price_rub=price,
                application_deadline=deadline, status="Приём заявок",
                raw={"message_guid": message_guid, "message_number": message.get("number"),
                     "trade_number": trade_number, "lot_number": lot_number},
            )
            for field, value in {"title": title, "cadastral_numbers": ", ".join(cad),
                                 "start_price_rub": str(price) if price else None,
                                 "application_deadline": deadline, "status": lot.status}.items():
                if value:
                    lot.provenance[field] = Provenance(source_url=source_url, fetched_at=fetched_at, raw_value=value)
            out.append(lot)
        return out

    @staticmethod
    def _is_moscow(text: str) -> bool:
        return bool(_MOSCOW_RE.search(_MOSCOW_REGION_RE.sub("", text)))

    def discover_moscow(self, *, deadline: float | None = None) -> list[AuctionLot]:
        self.last_report = self._empty_report()
        if not self.configured():
            self.last_report["reason"] = (
                f"нужны договорные реквизиты: {self.LOGIN_ENV} и {self.PASSWORD_ENV}")
            return []
        try:
            payload = self._messages(self._token(deadline), deadline)
        except Exception as exc:  # noqa: BLE001
            self.last_report["reason"] = f"официальный API не ответил: {type(exc).__name__}: {exc}"[:240]
            return []
        messages = payload.get("pageData") or []
        self.last_report["pages"] = 1
        self.last_report["cards"] = len(messages)
        fetched_at = utc_now_iso()
        parsed = [self._lots_from_message(message, fetched_at) for message in messages]
        lots = [lot for message_lots in parsed for lot in message_lots]
        self.last_report["kept"] = len(lots)
        self.last_report["skipped"] = len(messages) - sum(bool(message_lots) for message_lots in parsed)
        return lots

    def fetch_lot(self, lot_url: str) -> AuctionLot:
        host = (urlparse(lot_url).hostname or "").lower()
        if not (host == self.HOST or host.endswith("." + self.HOST)):
            raise ValueError("FedresursApiAdapter принимает только официальные адреса Федресурса")
        raise ValueError(self.deep_parse_unavailable)
