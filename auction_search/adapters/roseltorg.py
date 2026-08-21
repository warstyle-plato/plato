from __future__ import annotations

import re
from html.parser import HTMLParser
from urllib.parse import urljoin, urlparse
from urllib.request import Request, urlopen

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


class _RoseltorgHTML(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts: list[str] = []
        self.links: list[tuple[str, str]] = []
        self._href: str | None = None
        self._anchor: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag.lower() == "a":
            self._href = dict(attrs).get("href")
            self._anchor = []

    def handle_data(self, data):
        value = data.strip()
        if value:
            self.parts.append(value)
            if self._href is not None:
                self._anchor.append(value)

    def handle_endtag(self, tag):
        if tag.lower() == "a" and self._href is not None:
            self.links.append((self._href, normalize_space(" ".join(self._anchor))))
            self._href = None
            self._anchor = []

    @property
    def text(self) -> str:
        return normalize_space(" ".join(self.parts))


class RoseltorgAdapter(AuctionPlatformAdapter):
    """Official public Roseltorg procedure/lot-card adapter.

    Discovery remains disabled until the platform's official public search request
    is pinned. Direct official procedure URLs are already ingestible.
    """

    USER_AGENT = "DevelopAid-AuctionCollector/0.1 (+https://developaid.ru)"

    @property
    def platform_name(self) -> str:
        return "Roseltorg"

    def discover_moscow(self):
        return []

    def fetch_lot(self, lot_url: str) -> AuctionLot:
        host = urlparse(lot_url).hostname or ""
        if not host.endswith("roseltorg.ru"):
            raise ValueError("RoseltorgAdapter accepts only official Roseltorg URLs")
        if "/procedure/" not in urlparse(lot_url).path:
            raise ValueError("Roseltorg URL must point to a public /procedure/ card")

        req = Request(lot_url, headers={"User-Agent": self.USER_AGENT})
        with urlopen(req, timeout=20) as response:
            html = response.read().decode(response.headers.get_content_charset() or "utf-8", errors="replace")
        parser = _RoseltorgHTML()
        parser.feed(html)
        text = parser.text
        fetched_at = utc_now_iso()

        path_parts = [p for p in urlparse(lot_url).path.split("/") if p]
        proc_idx = path_parts.index("procedure")
        procedure_id = path_parts[proc_idx + 1] if len(path_parts) > proc_idx + 1 else lot_url
        lot_no = path_parts[proc_idx + 2] if len(path_parts) > proc_idx + 2 else "1"

        title = self._title(text, procedure_id, lot_no)
        procedure_method = self._value(text, "Способ проведения", ("Торговая секция", "Подробнее", "Запрос на разъяснение"))
        section = self._value(text, "Торговая секция", ("Подробнее", "Запрос на разъяснение", "Прием заявок"))
        start_price = self._money_near(text, "Начальная цена")
        deposit = self._money_near(text, "Обеспечение заявки")
        deadline = self._value(text, "Окончание приема заявок", ("Обеспечение заявки", "Обеспечение контракта", "Организатор торгов"))
        organizer = self._value(text, "Организатор торгов", ("Посмотреть объекты", "Перейти на площадку", "Документы", "Этапы"))
        seller = self._value(text, "Название организации", ("Юридический адрес продавца", "Почтовый адрес продавца", "Место поставки"))
        docs = self._documents(lot_url, parser.links, fetched_at)
        cad = cadastral_numbers(title + " " + text)
        area = self._area_from_text(title)
        lot_kind = classify_lot(title, procedure_method or "", [d.title for d in docs])

        source = AuctionSource(
            platform=SourceKind.ROSELTORG,
            lot_url=lot_url,
            external_lot_id=f"{procedure_id}/{lot_no}",
            fetched_at=fetched_at,
            source_name="Росэлторг",
        )
        lot = AuctionLot(
            source=source,
            lot_kind=lot_kind,
            title=title,
            cadastral_numbers=cad,
            land_area_sqm=area,
            seller=seller,
            organizer=organizer,
            procedure_type=procedure_method,
            start_price_rub=start_price,
            current_price_rub=start_price,
            deposit_rub=deposit,
            application_deadline=deadline,
            documents=docs,
            raw={"trading_section": section, "page_text": text},
        )
        for field, value in {
            "title": title,
            "cadastral_numbers": ", ".join(cad),
            "land_area_sqm": str(area) if area is not None else None,
            "seller": seller,
            "organizer": organizer,
            "procedure_type": procedure_method,
            "start_price_rub": str(start_price) if start_price is not None else None,
            "deposit_rub": str(deposit) if deposit is not None else None,
            "application_deadline": deadline,
        }.items():
            if value is not None:
                lot.provenance[field] = Provenance(source_url=lot_url, fetched_at=fetched_at, raw_value=value)
        return lot

    @staticmethod
    def _title(text: str, procedure_id: str, lot_no: str) -> str:
        candidates = (
            rf"Лот\s*№\s*{re.escape(lot_no)}\s*[-–—:]?\s*(.+?)(?=Информация по торгам|Этапы|Дополнительная информация|Прием заявок)",
            rf"Процедура:\s*{re.escape(procedure_id)}\s*(.+?)(?=Информация по торгам|Этапы|Дополнительная информация)",
        )
        for pattern in candidates:
            match = re.search(pattern, text, re.I)
            if match:
                return normalize_space(match.group(1))[:1500]
        return f"Росэлторг {procedure_id}, лот {lot_no}"

    @staticmethod
    def _value(text: str, label: str, stops: tuple[str, ...]):
        low = text.lower()
        idx = low.find(label.lower())
        if idx < 0:
            return None
        start = idx + len(label)
        end = len(text)
        tail = low[start:]
        for stop in stops:
            pos = tail.find(stop.lower())
            if pos >= 0:
                end = min(end, start + pos)
        value = normalize_space(text[start:end]).strip(" :-")
        return value[:2000] if value else None

    @staticmethod
    def _money_near(text: str, label: str):
        idx = text.lower().find(label.lower())
        if idx < 0:
            return None
        snippet = text[idx: idx + 250]
        match = re.search(r"([\d\s\u00a0]+(?:[.,]\d+)?)\s*₽", snippet)
        return parse_money(match.group(0)) if match else None

    @staticmethod
    def _area_from_text(text: str):
        match = re.search(r"(?:площад(?:ь|ью)\s*)?(\d[\d\s\u00a0]*(?:[.,]\d+)?)\s*(?:кв\.?\s*м|м2|м²)", text, re.I)
        return parse_decimal(match.group(1)) if match else None

    @staticmethod
    def _documents(base_url: str, links: list[tuple[str, str]], fetched_at: str) -> list[AuctionDocument]:
        out: list[AuctionDocument] = []
        seen: set[str] = set()
        markers = ("договор", "документац", "гпзу", "егрн", "выписк", "решение", "проект", "приложение", ".pdf", ".doc", ".zip")
        for href, title in links:
            absolute = urljoin(base_url, href)
            low = (title + " " + href).lower()
            if absolute in seen or not any(m in low for m in markers):
                continue
            seen.add(absolute)
            dtype = "other"
            if "гпзу" in low:
                dtype = "gpzu"
            elif "егрн" in low or "выписк" in low:
                dtype = "egrn"
            elif "договор" in low:
                dtype = "agreement"
            elif "решение" in low and "крт" in low:
                dtype = "krt_decision"
            out.append(AuctionDocument(title=title or href.rsplit("/", 1)[-1], url=absolute, document_type=dtype, fetched_at=fetched_at))
        return out
