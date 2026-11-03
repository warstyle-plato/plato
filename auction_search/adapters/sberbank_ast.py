from __future__ import annotations

import re
from datetime import datetime
from html.parser import HTMLParser
from typing import Any
from urllib.parse import urlencode, urljoin, urlparse
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

from auction_search import deadline as clock
from auction_search.adapters.base import AuctionPlatformAdapter
from auction_search.classifier import classify_lot, origin_from_evidence
from auction_search.models import AuctionLot, AuctionSource, LotKind, Provenance, SourceKind, utc_now_iso
from auction_search.parsing import cadastral_numbers, normalize_space, parse_area_sqm, parse_decimal, parse_money


_MOSCOW = ZoneInfo("Europe/Moscow")
_MOSCOW_RE = re.compile(r"(?:^|[,;\s])(?:г\.?\s*)?москв(?:а|ы|е|у|ой)(?:$|[,;\s])", re.I)
_MOSCOW_REGION_RE = re.compile(r"московск\w*\s+област", re.I)
_DEVELOPMENT_RE = re.compile(
    r"(?:земельн\w*\s+участ\w*|имущественн\w*\s+комплекс\w*|"
    r"объект\w*\s+незавершенн\w*|\bкрт\b|недвижим\w*|здани\w*)",
    re.I,
)
_DATE_RE = re.compile(r"\b\d{2}\.\d{2}\.\d{2,4}(?:\s+\d{2}:\d{2}(?::\d{2})?)?\b")
_PURCHASE_VIEW_RE = re.compile(r"(?:https?:)?//[^\s\"']*?/[^\s\"']*PurchaseView[^\s\"']*|/[^\s\"']*PurchaseView[^\s\"']*", re.I)


class _RowsParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.rows: list[dict[str, Any]] = []
        self._row: dict[str, Any] | None = None
        self._cell: list[str] | None = None
        self._cell_links: list[str] = []

    def handle_starttag(self, tag: str, attrs) -> None:
        tag = tag.lower()
        if tag == "tr":
            self._row = {"cells": [], "links": []}
        elif tag in {"td", "th"} and self._row is not None:
            self._cell = []
            self._cell_links = []
        elif tag == "a" and self._row is not None:
            href = dict(attrs).get("href")
            if href:
                self._cell_links.append(href)

    def handle_data(self, data: str) -> None:
        if self._cell is not None and data.strip():
            self._cell.append(data.strip())

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag in {"td", "th"} and self._cell is not None and self._row is not None:
            self._row["cells"].append(normalize_space(" ".join(self._cell)))
            self._row["links"].extend(self._cell_links)
            self._cell = None
            self._cell_links = []
        elif tag == "tr" and self._row is not None:
            if self._row["cells"]:
                self.rows.append(self._row)
            self._row = None


class SberbankASTAdapter(AuctionPlatformAdapter):
    """Публичный реестр банкротных торгов Сбербанк-АСТ.

    Старый раздел ``utp.sberbank-ast.ru/Bankruptcy`` использует HTML-таблицу
    и form-urlencoded XML-фильтр. Это отдельный источник, не агрегатор: если
    площадка вернула страницу защиты, она попадёт в отчёт источника и не будет
    выдана за пустой результат.
    """

    HOST = "sberbank-ast.ru"
    # У Сбербанк-АСТ несколько публичных витрин одного реестра. Общий список
    # банкротств исторически был единственной точкой интеграции, но земельные
    # и имущественные лоты вынесены также в BidListProperty, а раздел АП
    # публикует отдельный список по коду 309. Опрос всех трёх не смешивает
    # источники: карточка всё равно ведёт на официальную PurchaseView.
    LIST_URL = "https://utp.sberbank-ast.ru/Bankruptcy/List/BidList"
    LIST_URLS = (
        LIST_URL,
        "https://utp.sberbank-ast.ru/Bankruptcy/List/BidListProperty",
        "https://utp.sberbank-ast.ru/AP/List/BidList/309",
    )
    CONTROL_URL = "https://utp.sberbank-ast.ru/"
    USER_AGENT = "DevelopAid-AuctionCollector/0.1 (+https://developaid.ru)"
    MAX_PAGES = 2
    REQUEST_TIMEOUT_SECONDS = 8

    def __init__(self) -> None:
        self.last_report = self._empty_report()

    @property
    def platform_name(self) -> str:
        return "Сбербанк-АСТ"

    def _empty_report(self) -> dict[str, Any]:
        return {
            "source": self.platform_name,
            "pages": 0,
            "cards": 0,
            "kept": 0,
            "skipped": 0,
            "endpoints": [],
            "endpoint_errors": [],
            "reason": "",
        }

    @classmethod
    def _form_body(cls, page: int) -> bytes:
        # Поля формы — публичный контракт реестра: фильтр приходит как XML,
        # номер страницы — отдельным hdnPageNum. Пустые значения оставляют
        # площадке полный текущий список, Москва проверяется ниже по строке.
        xml = (
            "<query><purchcode></purchcode><purchname></purchname>"
            "<amountstart>0</amountstart><amountend>1000000000000</amountend>"
            "<publicdatestart></publicdatestart><publicdateend></publicdateend>"
            "<auctionupdatedatestart></auctionupdatedatestart><auctionupdatedateend></auctionupdatedateend>"
            "<requeststartdatestart></requeststartdatestart><requeststartdateend></requeststartdateend>"
            "<requestdatestart></requestdatestart><requestdateend></requestdateend>"
            "<auctionstartdatestart></auctionstartdatestart><auctionstartdateend></auctionstartdateend>"
            "<typeid></typeid><typename></typename><orgid></orgid><orgname></orgname>"
            "<purchasegroupid></purchasegroupid><purchasegroupname></purchasegroupname>"
            "<regionid></regionid><regionname></regionname><statusid></statusid></query>"
        )
        return urlencode({
            "xmlFilter": xml,
            "publicDateStart": "", "publicDateEnd": "",
            "auctionUpdateDateStart": "", "auctionUpdateDateEnd": "",
            "RequestStartDateStart": "", "RequestStartDateEnd": "",
            "requestDateStart": "", "requestDateEnd": "",
            "AuctionStartDateStart": "", "AuctionStartDateEnd": "",
            "hdnPageNum": str(page),
        }).encode("cp1251", errors="replace")

    @classmethod
    def _read(
        cls,
        url: str,
        deadline: float | None = None,
        *,
        page: int | None = None,
        referer: str | None = None,
    ) -> str:
        if page is None:
            request = Request(url, headers={
                "User-Agent": cls.USER_AGENT,
                "Accept": "text/html,application/xhtml+xml,*/*;q=0.8",
                "Accept-Language": "ru-RU,ru;q=0.9",
            })
        else:
            request = Request(url, data=cls._form_body(page), headers={
                "User-Agent": cls.USER_AGENT,
                "Accept": "text/html,application/xhtml+xml,*/*;q=0.8",
                "Accept-Language": "ru-RU,ru;q=0.9",
                "Content-Type": "application/x-www-form-urlencoded",
                "Referer": referer or cls.LIST_URL,
            })
        with urlopen(request, timeout=clock.timeout(deadline, cls.REQUEST_TIMEOUT_SECONDS)) as response:
            encoding = response.headers.get_content_charset() or "utf-8"
            return response.read().decode(encoding, errors="replace")

    @classmethod
    def _rows(cls, html: str, *, base_url: str | None = None) -> list[dict[str, Any]]:
        parser = _RowsParser()
        parser.feed(html)
        out: list[dict[str, Any]] = []
        base = base_url or cls.LIST_URL
        for row in parser.rows:
            links = [urljoin(base, link) for link in row["links"]]
            detail = next((link for link in links if _PURCHASE_VIEW_RE.search(link)), "")
            if detail:
                out.append({"cells": row["cells"], "url": detail})
        return out

    @staticmethod
    def _text(row: dict[str, Any]) -> str:
        return normalize_space(" ".join(row.get("cells") or []))

    @staticmethod
    def _is_moscow(text: str) -> bool:
        return bool(_MOSCOW_RE.search(_MOSCOW_REGION_RE.sub("", text)))

    @staticmethod
    def _date_values(text: str) -> list[datetime]:
        found: list[datetime] = []
        for token in _DATE_RE.findall(text):
            for fmt in ("%d.%m.%Y %H:%M:%S", "%d.%m.%Y %H:%M", "%d.%m.%Y", "%d.%m.%y %H:%M:%S", "%d.%m.%y %H:%M", "%d.%m.%y"):
                try:
                    found.append(datetime.strptime(token, fmt).replace(tzinfo=_MOSCOW))
                    break
                except ValueError:
                    continue
        return found

    @classmethod
    def _deadline(cls, text: str) -> str | None:
        future = [item for item in cls._date_values(text) if item >= datetime.now(_MOSCOW)]
        return max(future).isoformat() if future else None

    @staticmethod
    def _price(cells: list[str]) -> float | None:
        # Сначала берём только явно денежные значения. `parse_money` умеет
        # разбирать и просто число, но в строке карточки рядом встречаются
        # площадь и кадастровый номер — принимать их за цену нельзя.
        for value in cells:
            if not re.search(r"(?:₽|руб(?:\.|лей)?)", value, re.I):
                continue
            parsed = parse_money(value)
            if parsed is not None and parsed > 0:
                return parsed
        # Некоторые таблицы выводят цену без валютного суффикса. В таком
        # случае разрешаем числовую ячейку, но исключаем даты, площади и
        # кадастровые номера; заголовок лота поэтому не становится ценой.
        for value in cells:
            if (_DATE_RE.search(value) or cadastral_numbers(value)
                    or re.search(r"(?:кв\.?\s*м|м2|м²)", value, re.I)):
                continue
            parsed = parse_decimal(value)
            if parsed is not None and parsed >= 1000:
                return parsed
        return None

    @classmethod
    def _to_lot(cls, row: dict[str, Any], fetched_at: str) -> AuctionLot | None:
        cells = [normalize_space(value) for value in row.get("cells") or []]
        text = normalize_space(" ".join(cells))
        if not text or not cls._is_moscow(text) or not _DEVELOPMENT_RE.search(text):
            return None
        deadline = cls._deadline(text)
        if not deadline:
            return None
        title_candidates = [
            value for value in cells
            if len(value) >= 15 and not _DATE_RE.fullmatch(value) and _DEVELOPMENT_RE.search(value)
        ]
        if not title_candidates:
            title_candidates = [value for value in cells if len(value) >= 15 and not _DATE_RE.fullmatch(value)]
        title = max(title_candidates, key=len, default=text)[:1500]
        kind = classify_lot(title, "банкротство")
        if kind is LotKind.OTHER:
            return None
        area = parse_area_sqm(title)
        cad = cadastral_numbers(title)
        lot_url = row.get("url") or cls.LIST_URL
        external = next((value for value in cells if re.search(r"SBR\d{3}[-\w]+", value, re.I)), "")
        external = external or next((value for value in cells if re.fullmatch(r"\d{4,}", value)), lot_url)
        price = cls._price(cells)
        lot = AuctionLot(
            source=AuctionSource(SourceKind.SBERBANK_AST, lot_url, external, fetched_at, "Сбербанк-АСТ"),
            lot_kind=kind,
            title=title,
            origin=origin_from_evidence(procedure_type="банкротство", text=text),
            address=title[:1000] if not cad else None,
            cadastral_numbers=cad,
            land_area_sqm=area if kind in {LotKind.LAND_SALE, LotKind.LAND_LEASE, LotKind.KRT} else None,
            building_area_sqm=area if kind in {LotKind.PROPERTY_COMPLEX, LotKind.UNFINISHED} else None,
            procedure_type="Банкротство",
            start_price_rub=price,
            current_price_rub=price,
            application_deadline=deadline,
            status="Приём заявок",
            raw={"registry_row": row, "page_text": text},
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
        fetched_at = utc_now_iso()
        lots: list[AuctionLot] = []
        seen: set[str] = set()
        for list_url in self.LIST_URLS:
            if clock.expired(deadline):
                break
            endpoint_name = urlparse(list_url).path
            endpoint_pages = 0
            endpoint_cards = 0
            for page in range(1, self.MAX_PAGES + 1):
                if clock.expired(deadline):
                    break
                try:
                    html = self._read(list_url, deadline, page=page, referer=list_url)
                except Exception as exc:  # noqa: BLE001 — одна витрина не отменяет остальные
                    self.last_report["endpoint_errors"].append(
                        f"{endpoint_name}: {type(exc).__name__}: {exc}"[:240])
                    break
                self.last_report["pages"] += 1
                endpoint_pages += 1
                rows = self._rows(html, base_url=list_url)
                if not rows:
                    break
                self.last_report["cards"] += len(rows)
                endpoint_cards += len(rows)
                for row in rows:
                    lot = self._to_lot(row, fetched_at)
                    if lot is None:
                        self.last_report["skipped"] += 1
                        continue
                    if lot.source.external_lot_id in seen:
                        continue
                    seen.add(lot.source.external_lot_id)
                    lots.append(lot)
            self.last_report["endpoints"].append({
                "url": list_url,
                "pages": endpoint_pages,
                "cards": endpoint_cards,
            })
        self.last_report["kept"] = len(lots)
        if not self.last_report["pages"]:
            self.last_report["reason"] = "официальный реестр не ответил"
        elif not self.last_report["cards"]:
            self.last_report["reason"] = "официальный реестр ответил, но карточки не распознаны"
        elif self.last_report["endpoint_errors"]:
            self.last_report["reason"] = "часть витрин Сбербанк-АСТ недоступна; результат собран с доступных"
        return lots

    def fetch_lot(self, lot_url: str) -> AuctionLot:
        host = (urlparse(lot_url).hostname or "").lower()
        if not (host == self.HOST or host.endswith("." + self.HOST)):
            raise ValueError("SberbankASTAdapter принимает только официальные адреса Сбербанк-АСТ")
        html = self._read(lot_url)
        rows = self._rows(html)
        row = rows[0] if rows else {"cells": [normalize_space(re.sub(r"<[^>]+>", " ", html))], "url": lot_url}
        lot = self._to_lot(row, utc_now_iso())
        if lot is None:
            raise ValueError("Официальная карточка Сбербанк-АСТ не содержит измеримых московских данных")
        return lot
