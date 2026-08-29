from __future__ import annotations

import re
from datetime import datetime
from html.parser import HTMLParser
from typing import Any
from urllib.parse import urlencode, urlparse
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

from auction_search import deadline as clock
from auction_search.adapters.base import AuctionPlatformAdapter
from auction_search.classifier import classify_lot, origin_from_evidence
from auction_search.models import AuctionLot, AuctionSource, LotKind, Provenance, SourceKind, utc_now_iso
from auction_search.parsing import cadastral_numbers, normalize_space, parse_area_sqm, parse_money


_MOSCOW = ZoneInfo("Europe/Moscow")
_MOSCOW_RE = re.compile(r"(?:^|[,;\s])(?:г\.?\s*)?москв(?:а|ы|е|у|ой)(?:$|[,;\s])", re.I)
_MOSCOW_REGION_RE = re.compile(r"московск\w*\s+област", re.I)
_DEVELOPMENT_RE = re.compile(
    r"(?:земельн\w*\s+участ\w*|имущественн\w*\s+комплекс\w*|"
    r"объект\w*\s+незавершенн\w*|\bкрт\b|нежил\w*|недвижим\w*|здани\w*)", re.I)
_LOT_LINK_RE = re.compile(r"/bankrot/trade_view\.php\?trade_nid=(\d+)#lot(\d+)", re.I)
_DATE_RE = re.compile(r"\b\d{2}\.\d{2}\.\d{4}(?:\s+\d{2}:\d{2})?\b")


class _RowsParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.rows: list[dict[str, Any]] = []
        self._row: dict[str, Any] | None = None
        self._cell: list[str] | None = None
        self._links: list[tuple[str, str]] = []
        self._anchor_href: str | None = None
        self._anchor_text: list[str] = []

    def handle_starttag(self, tag: str, attrs) -> None:
        tag = tag.lower()
        if tag == "tr":
            self._row = {"cells": [], "links": []}
        elif tag in {"td", "th"} and self._row is not None:
            self._cell = []
            self._links = []
        elif tag == "a" and self._cell is not None:
            self._anchor_href = dict(attrs).get("href")
            self._anchor_text = []

    def handle_data(self, data: str) -> None:
        if self._cell is not None and data.strip():
            self._cell.append(data.strip())
        if self._anchor_href and data.strip():
            self._anchor_text.append(data.strip())

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag == "a" and self._anchor_href:
            self._links.append((self._anchor_href, normalize_space(" ".join(self._anchor_text))))
            self._anchor_href = None
            self._anchor_text = []
        elif tag in {"td", "th"} and self._cell is not None and self._row is not None:
            self._row["cells"].append(normalize_space(" ".join(self._cell)))
            self._row["links"].extend(self._links)
            self._cell = None
            self._links = []
        elif tag == "tr" and self._row is not None:
            if self._row["cells"]:
                self.rows.append(self._row)
            self._row = None


class NistpAdapter(AuctionPlatformAdapter):
    """Публичный поиск банкротных лотов ЭТП «Новые информационные сервисы»."""

    HOST = "nistp.ru"
    LIST_URL = "https://nistp.ru/bankrot/trade_list.php"
    USER_AGENT = "DevelopAid-AuctionCollector/0.1 (+https://developaid.ru)"
    REQUEST_TIMEOUT_SECONDS = 8
    deep_parse_unavailable = "НИС подключён к поиску; детальный разбор документов пока недоступен."

    def __init__(self) -> None:
        self.last_report = self._empty_report()

    @property
    def platform_name(self) -> str:
        return "НИС"

    def _empty_report(self) -> dict[str, Any]:
        return {"source": self.platform_name, "pages": 0, "cards": 0, "kept": 0,
                "skipped": 0, "reason": ""}

    @classmethod
    def _search_url(cls) -> str:
        return cls.LIST_URL + "?" + urlencode({"lot_description": "Москва", "view_type": "lot"})

    @classmethod
    def _read(cls, url: str, deadline: float | None = None) -> str:
        request = Request(url, headers={"User-Agent": cls.USER_AGENT, "Accept-Language": "ru-RU,ru;q=0.9"})
        with urlopen(request, timeout=clock.timeout(deadline, cls.REQUEST_TIMEOUT_SECONDS)) as response:
            encoding = response.headers.get_content_charset() or "utf-8"
            return response.read().decode(encoding, errors="replace")

    @classmethod
    def _rows(cls, html: str) -> list[dict[str, Any]]:
        parser = _RowsParser()
        parser.feed(html)
        out = []
        for row in parser.rows:
            lot_link = next(((href, text) for href, text in row["links"] if _LOT_LINK_RE.search(href)), None)
            if lot_link:
                out.append({"cells": row["cells"], "url": lot_link[0], "lot_text": lot_link[1]})
        return out

    @staticmethod
    def _is_moscow(text: str) -> bool:
        return bool(_MOSCOW_RE.search(_MOSCOW_REGION_RE.sub("", text)))

    @staticmethod
    def _deadline(value: str) -> str | None:
        token = next(iter(_DATE_RE.findall(value)), "")
        for fmt in ("%d.%m.%Y %H:%M", "%d.%m.%Y"):
            try:
                date = datetime.strptime(token, fmt).replace(tzinfo=_MOSCOW)
                return date.isoformat() if date >= datetime.now(_MOSCOW) else None
            except ValueError:
                continue
        return None

    @classmethod
    def _to_lot(cls, row: dict[str, Any], fetched_at: str) -> AuctionLot | None:
        cells = [normalize_space(value) for value in row.get("cells") or []]
        title = normalize_space(row.get("lot_text") or (cells[2] if len(cells) > 2 else ""))
        if not cls._is_moscow(title) or not _DEVELOPMENT_RE.search(title):
            return None
        deadline = cls._deadline(cells[5] if len(cells) > 5 else "")
        if not deadline:
            return None
        kind = classify_lot(title, "банкротство")
        if kind is LotKind.OTHER:
            return None
        cad = cadastral_numbers(title)
        area = parse_area_sqm(title)
        price = parse_money(cells[3]) if len(cells) > 3 else None
        url = row["url"]
        match = _LOT_LINK_RE.search(url)
        external_id = f"{match.group(1)}-{match.group(2)}" if match else url
        status = cells[6] if len(cells) > 6 else "Прием заявок"
        lot = AuctionLot(
            source=AuctionSource(SourceKind.NISTP, url, external_id, fetched_at, "НИС"),
            lot_kind=kind, title=title,
            origin=origin_from_evidence(procedure_type="банкротство", text=" ".join(cells)),
            address=title[:1000] if not cad else None, cadastral_numbers=cad,
            land_area_sqm=area if kind in {LotKind.LAND_SALE, LotKind.LAND_LEASE, LotKind.KRT} else None,
            building_area_sqm=area if kind in {LotKind.PROPERTY_COMPLEX, LotKind.UNFINISHED} else None,
            organizer=cells[1] if len(cells) > 1 else None, procedure_type="Банкротство",
            start_price_rub=price, current_price_rub=price,
            application_deadline=deadline, status=status, raw={"registry_row": row},
        )
        for field, value in {"title": title, "cadastral_numbers": ", ".join(cad),
                             "start_price_rub": str(price) if price else None,
                             "application_deadline": deadline, "status": status}.items():
            if value:
                lot.provenance[field] = Provenance(source_url=url, fetched_at=fetched_at, raw_value=value)
        return lot

    def discover_moscow(self, *, deadline: float | None = None) -> list[AuctionLot]:
        self.last_report = self._empty_report()
        try:
            html = self._read(self._search_url(), deadline)
        except Exception as exc:  # noqa: BLE001
            self.last_report["reason"] = f"официальный реестр не ответил: {type(exc).__name__}: {exc}"[:240]
            return []
        self.last_report["pages"] = 1
        rows = self._rows(html)
        self.last_report["cards"] = len(rows)
        fetched_at = utc_now_iso()
        lots = [lot for row in rows if (lot := self._to_lot(row, fetched_at)) is not None]
        self.last_report["kept"] = len(lots)
        self.last_report["skipped"] = len(rows) - len(lots)
        if not rows:
            self.last_report["reason"] = "официальный поиск ответил, но карточки не распознаны"
        return lots

    def fetch_lot(self, lot_url: str) -> AuctionLot:
        host = (urlparse(lot_url).hostname or "").lower()
        if not (host == self.HOST or host.endswith("." + self.HOST)):
            raise ValueError("NistpAdapter принимает только официальные адреса НИС")
        raise ValueError(self.deep_parse_unavailable)
