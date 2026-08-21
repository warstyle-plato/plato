from __future__ import annotations

import re
from datetime import datetime
from html.parser import HTMLParser
from urllib.request import Request, urlopen
from urllib.parse import urljoin, urlparse, parse_qs, urlencode
from zoneinfo import ZoneInfo

from auction_search.adapters.base import AuctionPlatformAdapter
from auction_search.classifier import classify_lot
from auction_search.models import (
    AuctionDocument,
    AuctionLot,
    AuctionPricePeriod,
    AuctionSource,
    Provenance,
    SourceKind,
    utc_now_iso,
)
from auction_search.parsing import cadastral_numbers, normalize_space, parse_decimal, parse_money


_MOSCOW = ZoneInfo("Europe/Moscow")
_DT_TOKEN = r"\d{2}\.\d{2}\.\d{4}\s+\d{2}:\d{2}"
_NUM_TOKEN = r"[\d\s\u00a0]+(?:[.,]\d+)?"
_PRICE_ROW_RE = re.compile(
    rf"(?P<start>{_DT_TOKEN})\s+"
    rf"(?P<deadline>{_DT_TOKEN})\s+"
    rf"(?P<end>{_DT_TOKEN})\s+"
    rf"(?P<change>{_NUM_TOKEN})\s+"
    rf"(?P<price>{_NUM_TOKEN})\s+"
    rf"(?P<deposit>{_NUM_TOKEN})\s+"
    rf"(?P<deposit_deadline>{_DT_TOKEN})",
    re.I,
)


class _TextLinksParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts: list[str] = []
        self.links: list[tuple[str, str]] = []
        self._href: str | None = None
        self._anchor_parts: list[str] = []
        self._anchor_context: str = ""

    def handle_starttag(self, tag, attrs):
        if tag.lower() == "a":
            self._href = dict(attrs).get("href")
            self._anchor_parts = []
            self._anchor_context = self.parts[-1] if self.parts else ""

    def handle_data(self, data):
        value = data.strip()
        if value:
            self.parts.append(value)
            if self._href is not None:
                self._anchor_parts.append(value)

    def handle_endtag(self, tag):
        if tag.lower() == "a" and self._href is not None:
            label = normalize_space(" ".join(self._anchor_parts))
            if label.lower() in {"скачать", "download", "файл"} and self._anchor_context:
                label = normalize_space(self._anchor_context)
            self.links.append((self._href, label))
            self._href = None
            self._anchor_parts = []
            self._anchor_context = ""

    @property
    def text(self) -> str:
        return normalize_space(" ".join(self.parts))


class LotOnlineAdapter(AuctionPlatformAdapter):
    """Official RAD / Lot-online adapter.

    Both discovery and lot ingestion use only public pages of the official ETP.
    Discovery searches the official land catalogue for active Moscow records, then
    verifies Moscow on each official lot card before returning it.
    """

    USER_AGENT = "DevelopAid-AuctionCollector/0.1 (+https://developaid.ru)"
    CATALOG_URL = "https://catalog.lot-online.ru/index.php"
    DISCOVERY_PAGE_SIZE = 96
    DISCOVERY_MAX_PAGES = 3

    @property
    def platform_name(self) -> str:
        return "RAD / Lot-online"

    @classmethod
    def _discovery_url(cls, page: int = 1) -> str:
        params = {
            "category_id": "2",
            "dispatch": "categories.view",
            "filter_fields[is_archive]": "false",
            "personal_area": "",
            "q": "москва",
            "items_per_page": str(cls.DISCOVERY_PAGE_SIZE),
        }
        if page > 1:
            params["page"] = str(page)
        return cls.CATALOG_URL + "?" + urlencode(params)

    @staticmethod
    def _catalog_lot_urls(base_url: str, links: list[tuple[str, str]]) -> list[str]:
        out: list[str] = []
        seen: set[str] = set()
        for href, _title in links:
            absolute = urljoin(base_url, href)
            parsed = urlparse(absolute)
            if not (parsed.hostname or "").endswith("lot-online.ru"):
                continue
            query = parse_qs(parsed.query)
            if query.get("dispatch", [""])[0] != "products.view":
                continue
            if not query.get("product_id", [""])[0]:
                continue
            if absolute in seen:
                continue
            seen.add(absolute)
            out.append(absolute)
        return out

    @staticmethod
    def _confirmed_moscow(lot: AuctionLot) -> bool:
        values = [
            lot.address or "",
            str(lot.raw.get("region") or ""),
            lot.title or "",
        ]
        haystack = " ".join(values).lower()
        return "москва" in haystack or "г. москва" in haystack

    def discover_moscow(self) -> list[AuctionLot]:
        """Enumerate active Moscow land lots from the official public RAD catalogue.

        The catalogue query is only discovery. Every candidate is re-read from its
        official lot card, and non-Moscow results are discarded there.
        """
        candidate_urls: list[str] = []
        seen: set[str] = set()
        for page in range(1, self.DISCOVERY_MAX_PAGES + 1):
            url = self._discovery_url(page)
            req = Request(url, headers={"User-Agent": self.USER_AGENT})
            with urlopen(req, timeout=25) as response:
                html = response.read().decode(response.headers.get_content_charset() or "utf-8", errors="replace")
            parser = _TextLinksParser()
            parser.feed(html)
            page_urls = self._catalog_lot_urls(url, parser.links)
            new_urls = [item for item in page_urls if item not in seen]
            if not new_urls:
                break
            candidate_urls.extend(new_urls)
            seen.update(new_urls)
            if len(page_urls) < self.DISCOVERY_PAGE_SIZE:
                break

        lots: list[AuctionLot] = []
        for lot_url in candidate_urls:
            lot = self.fetch_lot(lot_url)
            if self._confirmed_moscow(lot):
                lot.raw["discovered_via"] = self._discovery_url(1)
                lots.append(lot)
        return lots

    def fetch_lot(self, lot_url: str) -> AuctionLot:
        host = (urlparse(lot_url).hostname or "").lower()
        if not (host == "lot-online.ru" or host.endswith(".lot-online.ru")):
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
        schedule = self._price_schedule(text, lot_url=lot_url, fetched_at=fetched_at)
        current_period = self._current_actionable_period(schedule)

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
            current_price_rub=current_period.price_rub if current_period else None,
            min_price_rub=min_price,
            deposit_rub=current_period.deposit_rub if current_period else None,
            application_deadline=current_period.application_deadline if current_period else None,
            status=status,
            price_schedule=schedule,
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
            "current_price_rub": str(lot.current_price_rub) if lot.current_price_rub is not None else None,
            "min_price_rub": str(min_price) if min_price is not None else None,
            "deposit_rub": str(lot.deposit_rub) if lot.deposit_rub is not None else None,
            "application_deadline": lot.application_deadline,
            "status": status,
        }.items():
            if value is not None:
                lot.provenance[field] = Provenance(source_url=lot_url, fetched_at=fetched_at, raw_value=value)
        return lot

    @staticmethod
    def _extract_title(text: str) -> str:
        idx = text.find("Начальная цена")
        head = text[:idx] if idx > 0 else text
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
    def _parse_moscow_dt(value: str) -> datetime:
        return datetime.strptime(value, "%d.%m.%Y %H:%M").replace(tzinfo=_MOSCOW)

    @classmethod
    def _price_schedule(cls, text: str, *, lot_url: str, fetched_at: str) -> list[AuctionPricePeriod]:
        schedule: list[AuctionPricePeriod] = []
        for match in _PRICE_ROW_RE.finditer(text):
            start = cls._parse_moscow_dt(match.group("start"))
            deadline = cls._parse_moscow_dt(match.group("deadline"))
            end = cls._parse_moscow_dt(match.group("end"))
            change = parse_decimal(match.group("change"))
            price = parse_decimal(match.group("price"))
            deposit = parse_decimal(match.group("deposit"))
            if price is None:
                continue
            raw = normalize_space(match.group(0))
            schedule.append(
                AuctionPricePeriod(
                    starts_at=start.isoformat(),
                    application_deadline=deadline.isoformat(),
                    ends_at=end.isoformat(),
                    price_rub=price,
                    deposit_rub=deposit,
                    change_rub=change,
                    provenance=Provenance(
                        source_url=lot_url,
                        source_section="Снижение цены",
                        fetched_at=fetched_at,
                        raw_value=raw,
                    ),
                )
            )
        return schedule

    @staticmethod
    def _current_actionable_period(schedule: list[AuctionPricePeriod]) -> AuctionPricePeriod | None:
        now = datetime.now(_MOSCOW)
        for period in schedule:
            start = datetime.fromisoformat(period.starts_at)
            deadline = datetime.fromisoformat(period.application_deadline)
            if start <= now <= deadline:
                return period
        return None

    @staticmethod
    def _documents(base_url: str, links: list[tuple[str, str]], fetched_at: str) -> list[AuctionDocument]:
        out: list[AuctionDocument] = []
        seen: set[str] = set()
        markers = ("договор", "выписк", "егрн", "положение", "сообщение", "документ", "решение", "проект", "приложение", ".pdf", ".doc", ".zip")
        for href, title in links:
            absolute = urljoin(base_url, href)
            low = (title + " " + href).lower()
            is_attachment = "rad_attachment.getfile" in low or "attachment_id=" in low
            if absolute in seen or (not is_attachment and not any(m in low for m in markers)):
                continue
            seen.add(absolute)
            dtype = "other"
            if "егрн" in low or "выписк" in low:
                dtype = "egrn"
            elif "решение" in low and "крт" in low:
                dtype = "krt_decision"
            elif "извещ" in low or "сообщение" in low:
                dtype = "notice"
            elif "прилож" in low:
                dtype = "annex"
            elif "договор" in low:
                dtype = "agreement"
            out.append(AuctionDocument(title=title or href.rsplit("/", 1)[-1], url=absolute, document_type=dtype, fetched_at=fetched_at))
        return out
