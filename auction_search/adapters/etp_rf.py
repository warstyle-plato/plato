from __future__ import annotations

import re
from datetime import datetime
from html.parser import HTMLParser
from typing import Any
from urllib.parse import urljoin, urlparse
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

from auction_search import deadline as clock
from auction_search.adapters.base import AuctionPlatformAdapter
from auction_search.classifier import classify_lot, origin_from_evidence
from auction_search.models import AuctionLot, AuctionSource, LotKind, Provenance, SourceKind, utc_now_iso
from auction_search.parsing import cadastral_numbers, normalize_space, parse_area_sqm, parse_money


_MOSCOW = ZoneInfo("Europe/Moscow")
_MOSCOW_REGION_RE = re.compile(r"московск\w*\s+област", re.I)
_MOSCOW_CITY_RE = re.compile(r"(?:^|[,;\s])(?:г\.?\s*)?москв(?:а|ы|е|у|ой)(?:$|[,;\s])", re.I)
_DEVELOPMENT_RE = re.compile(
    r"(?:земельн\w*\s+участ\w*|имущественн\w*\s+комплекс\w*|"
    r"объект\w*\s+незавершенн\w*|\bкрт\b|"
    r"комплексн\w*\s+развити\w*\s+территор\w*|здани\w*)",
    re.I,
)


class _TableParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.rows: list[list[dict[str, Any]]] = []
        self._row: list[dict[str, Any]] | None = None
        self._cell: dict[str, Any] | None = None

    def handle_starttag(self, tag: str, attrs) -> None:
        tag = tag.lower()
        if tag == "tr":
            self._row = []
        elif tag in {"td", "th"} and self._row is not None:
            self._cell = {"text": [], "links": [], "header": tag == "th"}
        elif tag == "a" and self._cell is not None:
            href = dict(attrs).get("href")
            if href:
                self._cell["links"].append(href)

    def handle_data(self, data: str) -> None:
        if self._cell is not None and data.strip():
            self._cell["text"].append(data.strip())

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag in {"td", "th"} and self._cell is not None and self._row is not None:
            self._cell["text"] = normalize_space(" ".join(self._cell["text"]))
            self._row.append(self._cell)
            self._cell = None
        elif tag == "tr" and self._row is not None:
            if self._row:
                self.rows.append(self._row)
            self._row = None


class ETPRFAdapter(AuctionPlatformAdapter):
    """Публичный реестр торгов ЭТП РФ (банкротное имущество)."""

    HOST = "sale.etprf.ru"
    LIST_URL = "https://sale.etprf.ru/Notification/Auction?IsPartialView=1&IsTableContentOnlyRequest=1"
    USER_AGENT = "DevelopAid-AuctionCollector/0.1 (+https://developaid.ru)"
    deep_parse_unavailable = (
        "ЭТП РФ подключена к поиску, но детальный разбор документов площадки "
        "пока недоступен; исходная карточка открывается по ссылке"
    )

    def __init__(self) -> None:
        self.last_report = self._empty_report()

    @property
    def platform_name(self) -> str:
        return "ЭТП РФ"

    def _empty_report(self) -> dict[str, Any]:
        return {"source": self.platform_name, "pages": 0, "cards": 0, "kept": 0, "skipped": 0, "reason": ""}

    @classmethod
    def _read_html(cls, url: str, deadline: float | None = None) -> str:
        req = Request(url, headers={
            "User-Agent": cls.USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,*/*;q=0.8",
            "Accept-Language": "ru-RU,ru;q=0.9",
            "X-Requested-With": "XMLHttpRequest",
        })
        with urlopen(req, timeout=clock.timeout(deadline, 12)) as response:
            encoding = response.headers.get_content_charset() or "utf-8"
            return response.read().decode(encoding, errors="replace")

    @staticmethod
    def _is_moscow(text: str) -> bool:
        without_region = _MOSCOW_REGION_RE.sub("", normalize_space(text))
        return bool(_MOSCOW_CITY_RE.search(without_region))

    @staticmethod
    def _moment(value: str) -> str | None:
        raw = normalize_space(value)
        for fmt in ("%d.%m.%Y %H:%M", "%d.%m.%Y %H:%M:%S", "%d.%m.%Y"):
            try:
                return datetime.strptime(raw, fmt).replace(tzinfo=_MOSCOW).isoformat()
            except ValueError:
                continue
        return None

    @staticmethod
    def _future(value: str | None) -> bool:
        if not value:
            return False
        try:
            return datetime.fromisoformat(value).astimezone(_MOSCOW) >= datetime.now(_MOSCOW)
        except ValueError:
            return False

    @staticmethod
    def _row_values(row: list[dict[str, Any]]) -> list[str]:
        return [normalize_space(str(cell.get("text") or "")) for cell in row]

    @classmethod
    def _rows(cls, html: str) -> list[dict[str, str]]:
        parser = _TableParser()
        parser.feed(html)
        headers: list[str] = []
        out: list[dict[str, str]] = []
        for row in parser.rows:
            values = cls._row_values(row)
            if any(bool(cell.get("header")) for cell in row):
                headers = values
                continue
            if len(values) < 8:
                continue
            links = [href for cell in row for href in cell.get("links") or []]
            detail = next((urljoin(cls.LIST_URL, href) for href in links
                           if "/notification/" in href.lower()), "")
            if headers and len(headers) == len(values):
                record = {normalize_space(key).lower(): value for key, value in zip(headers, values)}
                get = lambda *names: next((record[name] for name in names if record.get(name)), "")
                out.append({
                    "number": get("номер", "№"),
                    "notice": get("номер извещения"),
                    "title": get("предмет извещения", "предмет торгов"),
                    "price": get("начальная цена", "начальная цена, руб."),
                    "organizer": get("организатор"),
                    "published": get("дата публикации"),
                    "deadline": get("дата завершения приема заявок", "дата завершения приёма заявок"),
                    "notice_status": get("статус извещения"),
                    "auction_status": get("статус торгов"),
                    "procedure": get("тип извещения"),
                    "url": detail,
                })
            else:
                # Публичный partial-view иногда не повторяет заголовок. Порядок
                # столбцов фиксирован самой таблицей и опубликован над ней.
                out.append({
                    "number": values[0], "notice": values[1], "title": values[2],
                    "price": values[3], "organizer": values[4], "published": values[5],
                    "deadline": values[7], "notice_status": values[9] if len(values) > 9 else "",
                    "auction_status": values[10] if len(values) > 10 else "",
                    "procedure": values[11] if len(values) > 11 else "", "url": detail,
                })
        return out

    @classmethod
    def _to_lot(cls, row: dict[str, str], fetched_at: str) -> AuctionLot | None:
        title = normalize_space(row.get("title"))
        if not title or not _DEVELOPMENT_RE.search(title) or not cls._is_moscow(title):
            return None
        deadline = cls._moment(row.get("deadline") or "")
        status_blob = normalize_space(" ".join((row.get("notice_status") or "", row.get("auction_status") or "")))
        current_words = ("ожидает подачи", "прием заявок", "приём заявок", "опубликован")
        if not cls._future(deadline) or (status_blob and not any(word in status_blob.lower() for word in current_words)):
            return None
        procedure = normalize_space(row.get("procedure")) or None
        kind = classify_lot(title, procedure or "")
        if kind is LotKind.OTHER:
            return None
        area = parse_area_sqm(title)
        price = parse_money(row.get("price"))
        if price is not None and price <= 0:
            price = None
        lot_url = row.get("url") or cls.LIST_URL
        external_id = normalize_space(row.get("notice") or row.get("number") or lot_url)
        cad = cadastral_numbers(title)
        lot = AuctionLot(
            source=AuctionSource(SourceKind.ETP_RF, lot_url, external_id, fetched_at, "ЭТП РФ"),
            lot_kind=kind,
            title=title,
            origin=origin_from_evidence(
                organizer=row.get("organizer"), procedure_type=procedure,
                text=" ".join((title, procedure or ""))),
            address=title[:1000] if not cad else None,
            cadastral_numbers=cad,
            land_area_sqm=area if kind in {LotKind.LAND_SALE, LotKind.LAND_LEASE, LotKind.KRT} else None,
            building_area_sqm=area if kind in {LotKind.PROPERTY_COMPLEX, LotKind.UNFINISHED} else None,
            organizer=normalize_space(row.get("organizer")) or None,
            procedure_type=procedure,
            start_price_rub=price,
            current_price_rub=price,
            application_deadline=deadline,
            status=status_blob or "Приём заявок",
            raw={"published_at": cls._moment(row.get("published") or ""), "registry_row": row},
        )
        for field, value in {
            "title": title, "cadastral_numbers": ", ".join(cad),
            "land_area_sqm": str(lot.land_area_sqm) if lot.land_area_sqm else None,
            "building_area_sqm": str(lot.building_area_sqm) if lot.building_area_sqm else None,
            "start_price_rub": str(price) if price is not None else None,
            "application_deadline": deadline, "status": lot.status,
        }.items():
            if value:
                lot.provenance[field] = Provenance(source_url=lot_url, fetched_at=fetched_at, raw_value=value)
        return lot

    def discover_moscow(self, *, deadline: float | None = None) -> list[AuctionLot]:
        self.last_report = self._empty_report()
        html = self._read_html(self.LIST_URL, deadline)
        self.last_report["pages"] = 1
        rows = self._rows(html)
        self.last_report["cards"] = len(rows)
        fetched_at = utc_now_iso()
        lots = [lot for row in rows if (lot := self._to_lot(row, fetched_at)) is not None]
        self.last_report["kept"] = len(lots)
        self.last_report["skipped"] = len(rows) - len(lots)
        if not rows:
            self.last_report["reason"] = "официальный реестр ответил, но строки торгов не распознаны"
        return lots

    def fetch_lot(self, lot_url: str) -> AuctionLot:
        host = (urlparse(lot_url).hostname or "").lower()
        if host != self.HOST and not host.endswith("." + self.HOST):
            raise ValueError("ETPRFAdapter принимает только официальные адреса ЭТП РФ")
        raise ValueError(self.deep_parse_unavailable)
