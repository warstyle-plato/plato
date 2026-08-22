from __future__ import annotations

from datetime import datetime
from html.parser import HTMLParser
from urllib.parse import parse_qs, urlencode, urljoin, urlparse, urlunparse
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

from auction_search.adapters.base import AuctionPlatformAdapter
from auction_search.adapters.lot_online import LotOnlineAdapter
from auction_search.adapters.roseltorg_public import RoseltorgAdapter
from auction_search.models import AuctionLot


_MOSCOW = ZoneInfo("Europe/Moscow")


class _LinksParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.links: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag.lower() != "a":
            return
        href = dict(attrs).get("href")
        if href:
            self.links.append(href.strip())


class InvestMoscowDiscoveryAdapter(AuctionPlatformAdapter):
    """Official Moscow catalogue used only to discover the conducting ETP.

    No auction fact is populated from Investmoscow. Every returned ``AuctionLot``
    is fetched again from the official electronic platform linked by the city card.
    """

    USER_AGENT = "DevelopAid-AuctionCollector/0.1 (+https://developaid.ru)"
    HOST = "investmoscow.ru"
    DISCOVERY_MAX_PAGES = 2
    DISCOVERY_PAGE_SIZE = 100
    DISCOVERY_MAX_CARDS = 60
    REQUEST_TIMEOUT_SECONDS = 3
    LAND_OBJECT_TYPE = "nsi:41:30011569"
    SEARCH_TERMS = ("комплексное развитие территории",)
    ETP_HOST_SUFFIXES = (
        "roseltorg.ru",
        "lot-online.ru",
        "sberbank-ast.ru",
        "rts-tender.ru",
        "etpgpb.ru",
        "fabrikant.ru",
    )

    def __init__(self):
        self.last_report = self._empty_report()

    @property
    def platform_name(self) -> str:
        return "Торги Москвы → официальная ЭТП"

    @staticmethod
    def _empty_report() -> dict:
        return {
            "catalogue": "investmoscow",
            "catalogue_pages": 0,
            "city_cards": 0,
            "official_etp_links": 0,
            "verified_lots": 0,
            "unsupported_etp_hosts": [],
            "unresolved_city_cards": 0,
            "errors": [],
        }

    @classmethod
    def _search_urls(cls) -> list[str]:
        urls: list[str] = []
        base = "https://investmoscow.ru/tenders/"
        for page in range(1, cls.DISCOVERY_MAX_PAGES + 1):
            common = {
                "tenderStatus": "nsi:tender_status_tender_filter:1",
                "orderBy": "RequestEndDate",
                "orderAsc": "true",
                "pageNumber": str(page),
                "pageSize": str(cls.DISCOVERY_PAGE_SIZE),
            }
            urls.append(base + "?" + urlencode({**common, "objectTypes": cls.LAND_OBJECT_TYPE}))
            for term in cls.SEARCH_TERMS:
                urls.append(base + "?" + urlencode({**common, "searchText": term}))
        # The official city catalogue has a separate stable landing page for
        # company shares; development project companies are screened later.
        urls.append("https://investmoscow.ru/tenders/prodazha-dlya-biznesa-akcii-doli")
        return urls

    @staticmethod
    def _canonical_url(url: str) -> str:
        parsed = urlparse(url)
        return urlunparse((parsed.scheme, parsed.netloc.lower(), parsed.path.rstrip("/"), "", parsed.query, ""))

    @classmethod
    def _city_card_urls(cls, base_url: str, html: str) -> list[str]:
        parser = _LinksParser()
        parser.feed(html)
        out: list[str] = []
        seen: set[str] = set()
        for href in parser.links:
            absolute = cls._canonical_url(urljoin(base_url, href))
            parsed = urlparse(absolute)
            host = (parsed.hostname or "").lower()
            path = parsed.path.lower()
            is_card = path.startswith("/tenders/tender/") or path.startswith("/tenders/tendercard")
            if host not in {cls.HOST, f"www.{cls.HOST}"} or not is_card:
                continue
            query = parse_qs(parsed.query)
            if path.startswith("/tenders/tendercard") and not query.get("TenderId") and not query.get("tenderid"):
                continue
            if absolute not in seen:
                seen.add(absolute)
                out.append(absolute)
        return out

    @classmethod
    def _official_etp_urls(cls, city_card_url: str, html: str) -> list[str]:
        parser = _LinksParser()
        parser.feed(html)
        out: list[str] = []
        seen: set[str] = set()
        for href in parser.links:
            absolute = cls._canonical_url(urljoin(city_card_url, href))
            host = (urlparse(absolute).hostname or "").lower()
            if not any(host == suffix or host.endswith("." + suffix) for suffix in cls.ETP_HOST_SUFFIXES):
                continue
            if absolute not in seen:
                seen.add(absolute)
                out.append(absolute)
        return out

    @staticmethod
    def _adapter_for_etp(url: str) -> AuctionPlatformAdapter | None:
        host = (urlparse(url).hostname or "").lower()
        if host == "roseltorg.ru" or host.endswith(".roseltorg.ru"):
            return RoseltorgAdapter()
        if host == "lot-online.ru" or host.endswith(".lot-online.ru"):
            return LotOnlineAdapter()
        return None

    @staticmethod
    def _confirmed_moscow(lot: AuctionLot) -> bool:
        text = " ".join((lot.address or "", lot.title or "", str(lot.raw.get("region") or ""))).lower()
        return "москва" in text or "г. москва" in text

    @staticmethod
    def _has_current_deadline(deadline: str | None) -> bool:
        if not deadline:
            return False
        raw = deadline.strip()
        try:
            parsed = datetime.fromisoformat(raw)
        except ValueError:
            parsed = None
            for fmt in ("%d.%m.%Y %H:%M:%S", "%d.%m.%Y %H:%M", "%d.%m.%y %H:%M:%S", "%d.%m.%y %H:%M"):
                try:
                    parsed = datetime.strptime(raw, fmt)
                    break
                except ValueError:
                    continue
            if parsed is None:
                return False
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=_MOSCOW)
        return parsed.astimezone(_MOSCOW) >= datetime.now(_MOSCOW)

    def _read_html(self, url: str) -> str:
        req = Request(url, headers={"User-Agent": self.USER_AGENT})
        with urlopen(req, timeout=self.REQUEST_TIMEOUT_SECONDS) as response:
            return response.read().decode(response.headers.get_content_charset() or "utf-8", errors="replace")

    def fetch_lot(self, lot_url: str) -> AuctionLot:
        host = (urlparse(lot_url).hostname or "").lower()
        if host not in {self.HOST, f"www.{self.HOST}"}:
            raise ValueError("InvestMoscow discovery accepts only official investmoscow.ru cards")
        html = self._read_html(lot_url)
        etp_urls = self._official_etp_urls(lot_url, html)
        if not etp_urls:
            raise ValueError("В карточке Торгов Москвы не найдена ссылка на фактическую ЭТП")
        unsupported: set[str] = set()
        for etp_url in etp_urls:
            adapter = self._adapter_for_etp(etp_url)
            if adapter is None:
                unsupported.add((urlparse(etp_url).hostname or "").lower())
                continue
            lot = adapter.fetch_lot(etp_url)
            lot.raw["discovered_via"] = "Официальный портал Торги Москвы"
            lot.raw["discovery_url"] = lot_url
            return lot
        if unsupported:
            raise ValueError("Нужен адаптер ЭТП: " + ", ".join(sorted(unsupported)))
        raise ValueError("В карточке Торгов Москвы нет поддерживаемой фактической ЭТП")

    def discover_moscow(self) -> list[AuctionLot]:
        self.last_report = self._empty_report()
        city_cards: list[str] = []
        seen_cards: set[str] = set()
        catalogue_reachable = False
        for search_url in self._search_urls():
            try:
                html = self._read_html(search_url)
            except Exception as exc:
                self.last_report["errors"].append(f"{urlparse(search_url).path}: {type(exc).__name__}")
                if not catalogue_reachable:
                    break
                continue
            catalogue_reachable = True
            self.last_report["catalogue_pages"] += 1
            found = self._city_card_urls(search_url, html)
            new_cards = [url for url in found if url not in seen_cards]
            city_cards.extend(new_cards)
            seen_cards.update(new_cards)
        city_cards = city_cards[: self.DISCOVERY_MAX_CARDS]
        self.last_report["city_cards"] = len(city_cards)

        lots: list[AuctionLot] = []
        unsupported: set[str] = set()
        for city_card_url in city_cards:
            try:
                html = self._read_html(city_card_url)
            except Exception as exc:
                self.last_report["errors"].append(f"{city_card_url}: {type(exc).__name__}")
                continue
            etp_urls = self._official_etp_urls(city_card_url, html)
            if not etp_urls:
                self.last_report["unresolved_city_cards"] += 1
                continue
            self.last_report["official_etp_links"] += len(etp_urls)
            resolved = False
            for etp_url in etp_urls:
                adapter = self._adapter_for_etp(etp_url)
                if adapter is None:
                    unsupported.add((urlparse(etp_url).hostname or "").lower())
                    continue
                try:
                    lot = adapter.fetch_lot(etp_url)
                except Exception as exc:
                    self.last_report["errors"].append(f"{etp_url}: {type(exc).__name__}")
                    continue
                if not self._confirmed_moscow(lot) or not self._has_current_deadline(lot.application_deadline):
                    continue
                lot.raw["discovered_via"] = "Официальный портал Торги Москвы"
                lot.raw["discovery_url"] = city_card_url
                lots.append(lot)
                resolved = True
                break
            if not resolved:
                self.last_report["unresolved_city_cards"] += 1
        self.last_report["unsupported_etp_hosts"] = sorted(unsupported)
        self.last_report["verified_lots"] = len(lots)
        return lots
