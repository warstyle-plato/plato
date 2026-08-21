from __future__ import annotations

import re
from html.parser import HTMLParser
from urllib.request import Request, urlopen
from urllib.parse import urljoin, urlparse, parse_qs

from auction_search.adapters.base import AuctionPlatformAdapter
from auction_search.classifier import classify_lot
from auction_search.models import (
    AuctionDocument,
    AuctionLot,
    AuctionSource,
    Provenance,
    SourceKind,
    utc_now_iso,
)
from auction_search.parsing import cadastral_numbers, normalize_space, parse_decimal, parse_money


class _TextLinksParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts: list[str] = []
        self.links: list[tuple[str, str]] = []
        self._href: str | None = None
        self._anchor_parts: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag.lower() == "a":
            self._href = dict(attrs).get("href")
            self._anchor_parts = []

    def handle_data(self, data):
        value = data.strip()
        if value:
            self.parts.append(value)
            if self._href is not None:
                self._anchor_parts.append(value)

    def handle_endtag(self, tag):
        if tag.lower() == "a" and self._href is not None:
            self.links.append((self._href, normalize_space(" ".join(self._anchor_parts))))
            self._href = None
            self._anchor_parts = []

    @property
    def text(self) -> str:
        return normalize_space(" ".join(self.parts))


class LotOnlineAdapter(AuctionPlatformAdapter):
    """Official RAD / Lot-online adapter.

    `fetch_lot` is production-oriented and uses only the official ETP card.
    Discovery is intentionally not guessed until a stable official search endpoint is pinned.
    """

    USER_AGENT = "DevelopAid-AuctionCollector/0.1 (+https://developaid.ru)"

    @property
    def platform_name(self) -> str:
        return "RAD / Lot-online"

    def discover_moscow(self):
        # Explicitly fail rather than silently scrape an unstable catalogue/search UI.
        # The discovery endpoint will be enabled after its official request contract is fixed in tests.
        return []

    def fetch_lot(self, lot_url: str) -> AuctionLot:
        if "lot-online.ru" not in (urlparse(lot_url).hostname or ""):
            raise ValueError("LotOnlineAdapter accepts only official lot-online.ru URLs")
        req = Request(lot_url, headers={"User-Agent": self.USER_AGENT})
        with urlopen(req, timeout=20) as response:
            html = response.read().decode(response.headers.get_content_charset() or "utf-8", errors="replace")
        parser = _TextLinksParser()
        parser.feed(html)
        text = parser.text
        fetched_at = utc_now_iso()

        product_id = parse_qs(urlparse(lot_url).query).get("product_id", [""])[0]
        title = self._extract_title(text)
        start_price = self._money_after(text, "Начальная цена")
        min_price = self._money_after(text, "Минимальная цена")
        address = self._short_value(text, "Адрес", ("Земельный участок", "Субъект Федерации", "Категория земель"))
        region = self._short_value(text, "Регион", ("Адрес", "Земельный участок"))
        area = self._numeric_after(text, "Площадь")
        permitted_use = self._short_value(text, "Разрешенное использование", ("Кадастровый номер", "Коммуникации", "Порядок ознакомления"))
        seller = self._short_value(text, "Наименование ФО", ("Является залогом", "Ограничения и обременения"))
        procedure = self._short_value(text, "Вид процедуры", ("Код лота", "Код процедуры"))
        status = self._short_value(text, "Доступность", ("Направление продаж", "Вид процедуры"))
        cad = cadastral_numbers(text)

        docs = self._documents(lot_url, parser.links, fetched_at)
        lot_kind = classify_lot(title, procedure or "", [d.title for d in docs])
        source = AuctionSource(
            platform=SourceKind.LOT_ONLINE,
            lot_url=lot_url,
            external_lot_id=product_id or self._short_value(text, "Код лота", ("Код процедуры", "Регион")) or lot_url,
            fetched_at=fetched_at,
            source_name="Российский аукционный дом / Lot-online",
        )
        lot = AuctionLot(
            source=source,
            lot_kind=lot_kind,
            title=title,
            address=address,
            cadastral_numbers=cad,
            land_area_sqm=area,
            permitted_use=permitted_use,
            seller=seller,
            organizer="Российский аукционный дом",
            procedure_type=procedure,
            start_price_rub=start_price,
            current_price_rub=start_price,
            min_price_rub=min_price,
            status=status,
            documents=docs,
            raw={"region": region, "page_text": text},
        )
        for field, value in {
            "title": title,
            "address": address,
            "cadastral_numbers": ", ".join(cad),
            "land_area_sqm": str(area) if area is not None else None,
            "permitted_use": permitted_use,
            "seller": seller,
            "procedure_type": procedure,
            "start_price_rub": str(start_price) if start_price is not None else None,
            "min_price_rub": str(min_price) if min_price is not None else None,
            "status": status,
        }.items():
            if value is not None:
                lot.provenance[field] = Provenance(source_url=lot_url, fetched_at=fetched_at, raw_value=value)
        return lot

    @staticmethod
    def _extract_title(text: str) -> str:
        # On Lot-online the lot heading precedes the first price label.
        idx = text.find("Начальная цена")
        head = text[:idx] if idx > 0 else text
        # Prefer the last substantial segment after catalogue/search chrome.
        candidates = re.findall(r"(?:Земельный участок|Право[^.]{10,}|Объект[^.]{10,})[^#]{20,}", head, re.I)
        if candidates:
            return normalize_space(candidates[-1])[:1500]
        return normalize_space(head[-1500:])

    @staticmethod
    def _money_after(text: str, label: str):
        match = re.search(re.escape(label) + r"\s+([\d\s\u00a0]+(?:[.,]\d+)?)\s*₽", text, re.I)
        return parse_money(match.group(1) + " ₽") if match else None

    @staticmethod
    def _numeric_after(text: str, label: str):
        match = re.search(re.escape(label) + r"\s+([\d\s\u00a0]+(?:[.,]\d+)?)", text, re.I)
        return parse_decimal(match.group(1)) if match else None

    @staticmethod
    def _short_value(text: str, label: str, stop_labels: tuple[str, ...]):
        low = text.lower()
        start = low.find(label.lower())
        if start < 0:
            return None
        start += len(label)
        end = len(text)
        tail = low[start:]
        for stop in stop_labels:
            pos = tail.find(stop.lower())
            if pos >= 0:
                end = min(end, start + pos)
        value = normalize_space(text[start:end]).strip(" :-")
        return value[:2000] if value else None

    @staticmethod
    def _documents(base_url: str, links: list[tuple[str, str]], fetched_at: str) -> list[AuctionDocument]:
        out: list[AuctionDocument] = []
        seen: set[str] = set()
        markers = ("договор", "выписк", "егрн", "положение", "сообщение", "документ", "решение", "проект", "приложение")
        for href, title in links:
            absolute = urljoin(base_url, href)
            low = (title + " " + href).lower()
            if absolute in seen or not any(m in low for m in markers):
                continue
            seen.add(absolute)
            dtype = "other"
            if "егрн" in low or "выписк" in low:
                dtype = "egrn"
            elif "договор" in low:
                dtype = "agreement"
            elif "решение" in low and "крт" in low:
                dtype = "krt_decision"
            out.append(AuctionDocument(title=title or href.rsplit("/", 1)[-1], url=absolute, document_type=dtype, fetched_at=fetched_at))
        return out
