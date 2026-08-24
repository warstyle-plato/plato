from __future__ import annotations

import re
from datetime import date, datetime
from html.parser import HTMLParser
from urllib.parse import urlencode, urljoin, urlparse
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

from auction_search.adapters.base import AuctionPlatformAdapter
from auction_search.classifier import classify_lot, origin_from_evidence
from auction_search.models import (
    AuctionDocument,
    AuctionLot,
    AuctionSource,
    LotKind,
    Provenance,
    SourceKind,
    utc_now_iso,
)
from auction_search.parsing import cadastral_numbers, normalize_space, parse_decimal, parse_money


_MOSCOW = ZoneInfo("Europe/Moscow")


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
    """Official public Roseltorg search + procedure-card adapter.

    Discovery uses the platform's public tag search (`tags[]`). It deliberately
    avoids participant-cabinet APIs. Search is only candidate discovery: every
    result is re-read from the official public `/procedure/` card and then checked
    for Moscow and the legal structure before it enters DevelopAid.
    """

    USER_AGENT = "DevelopAid-AuctionCollector/0.1 (+https://developaid.ru)"
    SEARCH_URL = "https://www.roseltorg.ru/procedures/search"
    DISCOVERY_TAGS = ("земельный участок", "комплексное развитие")
    DISCOVERY_MAX_PAGES = 3
    RELEVANT_KINDS = {
        LotKind.LAND_SALE,
        LotKind.LAND_LEASE,
        LotKind.KRT,
        LotKind.PROPERTY_COMPLEX,
        LotKind.UNFINISHED,
    }

    @property
    def platform_name(self) -> str:
        return "Roseltorg"

    @classmethod
    def _discovery_url(cls, tag: str, page: int = 1) -> str:
        params: list[tuple[str, str]] = [("tags[]", tag)]
        if page > 1:
            params.append(("page", str(page)))
        return cls.SEARCH_URL + "?" + urlencode(params)

    @staticmethod
    def _procedure_urls(base_url: str, links: list[tuple[str, str]]) -> list[str]:
        out: list[str] = []
        seen: set[str] = set()
        for href, _title in links:
            absolute = urljoin(base_url, href)
            parsed = urlparse(absolute)
            host = (parsed.hostname or "").lower()
            if not (host == "roseltorg.ru" or host.endswith(".roseltorg.ru")):
                continue
            if not re.match(r"^/procedure/[^/]+(?:/\d+)?/?$", parsed.path):
                continue
            canonical = f"https://www.roseltorg.ru{parsed.path.rstrip('/')}"
            if canonical in seen:
                continue
            seen.add(canonical)
            out.append(canonical)
        return out

    @staticmethod
    def _confirmed_moscow(lot: AuctionLot) -> bool:
        # Never inspect the whole page here: every Roseltorg page contains the
        # platform's own Moscow office address in the footer.
        if str(lot.raw.get("lot_region_code") or "") == "77":
            return True
        text = " ".join([lot.address or "", lot.title or ""]).lower()
        if re.search(r"\b(?:г\.?|город)\s*москва\b", text):
            return True
        without_oblast = re.sub(r"московск\w*\s+област\w*", "", text)
        return bool(re.search(r"\bмосква\b", without_oblast))

    @staticmethod
    def _is_actionable_status(status: str | None) -> bool:
        low = (status or "").lower()
        if not low:
            return True  # public search defaults to active; card markup varies by section
        if any(marker in low for marker in ("отмен", "заверш", "заключение договора", "архив")):
            return False
        return any(marker in low for marker in ("прием заяв", "приём заяв", "ожидани", "работа комиссии", "опублик"))

    @staticmethod
    def _is_asset_disposal(lot: AuctionLot) -> bool:
        """Reject procurement/services that merely mention land in their subject."""
        text = " ".join((lot.title or "", lot.procedure_type or "", str(lot.raw.get("trading_section") or ""))).lower()
        procurement = (
            "223-фз", "коммерческие закупки", "объекты закупки", "услуги по",
            "оказание услуг", "оценка (определение", "оспаривания кадастровой стоимости",
        )
        if any(marker in text for marker in procurement):
            return False
        disposal = (
            "продажа земельного участка", "продажа объекта", "продажа имущества",
            "право на заключение договора аренды", "комплексное развитие территории",
            "реализация имущества", "аукцион по продаже",
        )
        return lot.lot_kind == LotKind.KRT or any(marker in text for marker in disposal)

    @staticmethod
    def _has_current_deadline(deadline: str | None) -> bool:
        if not deadline:
            return False
        raw = deadline.strip()
        for fmt in ("%d.%m.%Y %H:%M:%S", "%d.%m.%Y %H:%M", "%d.%m.%y %H:%M:%S", "%d.%m.%y %H:%M"):
            try:
                return datetime.strptime(raw, fmt).replace(tzinfo=_MOSCOW) >= datetime.now(_MOSCOW)
            except ValueError:
                continue
        return False

    def discover_moscow(self) -> list[AuctionLot]:
        candidate_urls: list[str] = []
        seen_urls: set[str] = set()
        for tag in self.DISCOVERY_TAGS:
            for page in range(1, self.DISCOVERY_MAX_PAGES + 1):
                search_url = self._discovery_url(tag, page)
                req = Request(search_url, headers={"User-Agent": self.USER_AGENT})
                with urlopen(req, timeout=25) as response:
                    html = response.read().decode(response.headers.get_content_charset() or "utf-8", errors="replace")
                parser = _RoseltorgHTML()
                parser.feed(html)
                page_urls = self._procedure_urls(search_url, parser.links)
                new_urls = [url for url in page_urls if url not in seen_urls]
                if not new_urls:
                    break
                candidate_urls.extend(new_urls)
                seen_urls.update(new_urls)

        lots: list[AuctionLot] = []
        seen_lots: set[str] = set()
        for lot_url in candidate_urls:
            try:
                lot = self.fetch_lot(lot_url)
            except Exception:
                # One malformed/temporarily unavailable procedure must not drop the feed.
                continue
            if lot.lot_kind not in self.RELEVANT_KINDS:
                continue
            if not self._is_asset_disposal(lot):
                continue
            if not self._confirmed_moscow(lot):
                continue
            if not self._is_actionable_status(lot.status):
                continue
            if not self._has_current_deadline(lot.application_deadline):
                continue
            if lot.canonical_key in seen_lots:
                continue
            seen_lots.add(lot.canonical_key)
            lot.raw["discovered_via"] = "Roseltorg public tags[] search"
            lots.append(lot)
        return lots

    def discover_moscow_history(
        self,
        since: date,
        until: date,
        *,
        candidate_urls: tuple[str, ...] = (),
    ) -> list[AuctionLot]:
        """Replay known public procedure cards inside a bounded date window.

        Roseltorg exposes archive selection in its public UI, but its underlying
        request parameter is not a stable documented contract. History therefore
        accepts only explicit official procedure URLs instead of guessing a private
        endpoint or changing the production tag search.
        """
        if since > until:
            raise ValueError("history start date must not be after end date")
        lots: list[AuctionLot] = []
        seen_source_ids: set[str] = set()
        for lot_url in dict.fromkeys(candidate_urls):
            parsed = urlparse(lot_url)
            host = (parsed.hostname or "").lower()
            if not (host == "roseltorg.ru" or host.endswith(".roseltorg.ru")):
                continue
            if "/procedure/" not in parsed.path:
                continue
            # Explicit replay failures are surfaced to the caller. Silently
            # returning an empty historical result would be a false negative.
            lot = self.fetch_lot(lot_url)
            published_at = self._published_at(str(lot.raw.get("page_text") or ""))
            if published_at is None or not (since <= published_at.date() <= until):
                continue
            if lot.lot_kind not in self.RELEVANT_KINDS or not self._confirmed_moscow(lot):
                continue
            if lot.source.external_lot_id in seen_source_ids:
                continue
            seen_source_ids.add(lot.source.external_lot_id)
            lot.raw["published_at"] = published_at.isoformat()
            lot.raw["discovery_mode"] = "history"
            lot.raw["discovered_via"] = "Roseltorg public procedure-card replay"
            lots.append(lot)
        return lots

    def fetch_lot(self, lot_url: str) -> AuctionLot:
        host = (urlparse(lot_url).hostname or "").lower()
        if not (host == "roseltorg.ru" or host.endswith(".roseltorg.ru")):
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
        section = self._value(text, "Торговая секция", ("Подробнее", "Запрос на разъяснение", "Прием заявок", "Приём заявок"))
        start_price = self._money_near(text, "Начальная цена")
        if start_price is None:
            start_price = self._first_lot_money(text, lot_no)
        deposit = self._money_near(text, "Обеспечение заявки")
        deadline = self._deadline(text)
        organizer = self._value(text, "Организатор торгов", ("ФИО", "Телефон", "E-mail", "Способ проведения"))
        seller = self._value(text, "Название организации", ("Юридический адрес продавца", "Почтовый адрес продавца", "Место поставки"))
        status = self._status(text, lot_no)
        lot_region_code = self._lot_region_code(text, lot_no)
        docs = self._documents(lot_url, parser.links, fetched_at)
        cad = cadastral_numbers(title + " " + text)
        area = self._area_from_text(title)
        lot_kind = classify_lot(title, procedure_method or "", [d.title for d in docs])
        published_at = self._published_at(text)

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
            # Торговая секция — рубрика самой площадки, и она, а не наша
            # посылка «Росэлторг = городские торги», говорит, с какого рынка
            # лот. Не опознали — `OTHER`: неопознанное не выдаётся за городское.
            origin=origin_from_evidence(
                seller=seller, organizer=organizer,
                procedure_type=procedure_method, text=section,
            ),
            start_price_rub=start_price,
            current_price_rub=start_price,
            deposit_rub=deposit,
            application_deadline=deadline,
            status=status,
            documents=docs,
            raw={
                "trading_section": section,
                "lot_region_code": lot_region_code,
                "page_text": text,
                "published_at": published_at.isoformat() if published_at is not None else None,
            },
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
            "status": status,
        }.items():
            if value is not None:
                lot.provenance[field] = Provenance(source_url=lot_url, fetched_at=fetched_at, raw_value=value)
        return lot

    @staticmethod
    def _published_at(text: str) -> datetime | None:
        match = re.search(
            r"Публикация\s+извещения\s*(?:\|)?\s*"
            r"(\d{2}\.\d{2}\.\d{2,4})(?:\s+(\d{2}:\d{2}(?::\d{2})?))?",
            text,
            re.I,
        )
        if not match:
            return None
        raw_date = match.group(1)
        clock = match.group(2) or "00:00:00"
        if len(clock) == 5:
            clock += ":00"
        date_format = "%d.%m.%y" if len(raw_date.rsplit(".", 1)[-1]) == 2 else "%d.%m.%Y"
        return datetime.strptime(f"{raw_date} {clock}", f"{date_format} %H:%M:%S").replace(tzinfo=_MOSCOW)

    @staticmethod
    def _lot_snippet(text: str, lot_no: str, limit: int = 5000) -> str:
        match = re.search(rf"\bЛот\s*(?:№\s*)?{re.escape(lot_no)}\b", text, re.I)
        if not match:
            return text[:limit]
        return text[match.start(): match.start() + limit]

    @staticmethod
    def _lot_region_code(text: str, lot_no: str) -> str | None:
        snippet = RoseltorgAdapter._lot_snippet(text, lot_no, 3500)
        # Region labels on public cards are rendered as e.g. `77. г. Москва`.
        match = re.search(r"\b(\d{2})\.\s*(?:г\.?\s*)?[А-ЯЁ][А-ЯЁа-яё -]{2,60}", snippet)
        return match.group(1) if match else None

    @staticmethod
    def _title(text: str, procedure_id: str, lot_no: str) -> str:
        candidates = (
            rf"Лот\s*{re.escape(lot_no)}\s+(?:Прием заявок|Приём заявок|Опубликован|Ожидание приема заявок|Ожидание приёма заявок|Работа комиссии|Заключение договора|Отменен|Отменён)?\s*(.+?)(?=Теги бета|Обеспечение заявки|Плата за участие|Посмотреть детальную информацию|Показать полностью|Документы|Объекты закупки|Этапы)",
            rf"Лот\s*№\s*{re.escape(lot_no)}\s*[-–—:]?\s*(.+?)(?=Информация по торгам|Этапы|Дополнительная информация|Прием заявок|Приём заявок)",
            rf"Процедура:\s*{re.escape(procedure_id)}\s*(.+?)(?=Организатор торгов|Информация по торгам|Этапы|Дополнительная информация)",
        )
        for pattern in candidates:
            match = re.search(pattern, text, re.I)
            if match:
                value = RoseltorgAdapter._clean_title(match.group(1))
                if len(value) >= 8:
                    return value[:1500]
        procedure_name = RoseltorgAdapter._value(text, "Наименование процедуры", ("Организатор торгов", "ФИО", "Телефон"))
        if procedure_name:
            return procedure_name[:1500]
        return f"Росэлторг {procedure_id}, лот {lot_no}"

    @staticmethod
    def _clean_title(value: str) -> str:
        clean = normalize_space(value)
        clean = re.split(
            r"Показать\s+полностью|\bДокументы\b|Объекты\s+закупки|\bНМЦ\b|Место\s+поставки",
            clean,
            maxsplit=1,
            flags=re.I,
        )[0]
        return normalize_space(clean).strip(" :-")

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
    def _first_lot_money(text: str, lot_no: str = "1"):
        snippet = RoseltorgAdapter._lot_snippet(text, lot_no, 2500)
        matches = re.findall(r"(\d[\d\s\u00a0]*(?:[.,]\d+)?)\s*₽", snippet)
        for raw in matches:
            value = parse_money(raw + " ₽")
            if value is not None and value >= 1:
                return value
        return None

    @staticmethod
    def _deadline(text: str):
        patterns = (
            r"Дата и время окончания при[её]ма заявок\s*(?:\||до)?\s*(\d{2}\.\d{2}\.\d{2,4}\s+\d{2}:\d{2}(?::\d{2})?)",
            r"Окончание при[её]ма заявок\s*(\d{2}\.\d{2}\.\d{4})\s*(?:в|\s)\s*(\d{2}:\d{2}(?::\d{2})?)",
            r"При[её]м заявок\s*до\s*(\d{2}\.\d{2}\.\d{2,4}\s+\d{2}:\d{2}(?::\d{2})?)",
        )
        for pattern in patterns:
            match = re.search(pattern, text, re.I)
            if match:
                return " ".join(group for group in match.groups() if group)
        return RoseltorgAdapter._value(text, "Окончание приема заявок", ("Обеспечение заявки", "Обеспечение контракта", "Организатор торгов"))

    @staticmethod
    def _status(text: str, lot_no: str = "1"):
        snippet = RoseltorgAdapter._lot_snippet(text, lot_no, 650)
        markers = (
            "Ожидание приема заявок",
            "Ожидание приёма заявок",
            "Прием заявок",
            "Приём заявок",
            "Работа комиссии",
            "Опубликован",
            "Отменен",
            "Отменён",
            "Процедура завершена",
            "Заключение договора",
        )
        low = snippet.lower()
        for marker in markers:
            if marker.lower() in low:
                return marker
        return None

    @staticmethod
    def _area_from_text(text: str):
        match = re.search(r"(?:площад(?:ь|ью)\s*)?(\d[\d\s\u00a0]*(?:[.,]\d+)?)\s*(?:кв\.?\s*м|м2|м²)", text, re.I)
        return parse_decimal(match.group(1)) if match else None

    @staticmethod
    def _documents(base_url: str, links: list[tuple[str, str]], fetched_at: str) -> list[AuctionDocument]:
        out: list[AuctionDocument] = []
        seen: set[str] = set()
        markers = (
            "договор",
            "документац",
            "гпзу",
            "егрн",
            "выписк",
            "решение",
            "проект",
            "извещ",
            "приказ",
            "приложение",
            ".pdf",
            ".doc",
            ".zip",
        )
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
            elif "решение" in low and "крт" in low:
                dtype = "krt_decision"
            elif "извещ" in low:
                dtype = "notice"
            elif "прилож" in low:
                dtype = "annex"
            elif "договор" in low:
                dtype = "agreement"
            out.append(
                AuctionDocument(
                    title=title or href.rsplit("/", 1)[-1],
                    url=absolute,
                    document_type=dtype,
                    fetched_at=fetched_at,
                )
            )
        return out
