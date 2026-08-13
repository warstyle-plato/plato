"""Цена и экспозиция — только при доказанной привязке к сущности.

v5 брал любое число «₽/м²» из любого документа, где встретилось название, и это
включало районные каталоги, где в одном сниппете идут цены пяти разных ЖК. Так
цена одного проекта уезжала другому, а «экспозиция» вообще собиралась как
максимум любого «N квартир» по всем документам подряд.

Здесь наблюдение принимается, если документ — карточка проекта у известного
агрегатора и он опознан как карточка *этого* проекта: совпал внешний
идентификатор либо название в заголовке. Всё остальное уходит в отбракованные с
причиной, а не в медиану.

Экспозиция считается отдельно и честно: если точного числа нет, возвращается
`units=None, quality="unknown"`, а не переиспользованное число из чужого сниппета.
"""

from __future__ import annotations

import re
import statistics
from dataclasses import dataclass
from datetime import date
from typing import Any

from .documents import DEVELOPER_PAGE, PROJECT_PAGE, classify_document, is_pricing_source
from .http import RemoteServiceError
from .normalize import cut_at_separator, labels_match, search_name
from .page_price import PageFetcher, fetchable
from .price import _PRICE_M2_RE, _PRICE_M2_REVERSED_RE, MarketPriceEnricher
from .yandex_search import SearchDoc, YandexSearchClient


_MIN_PRICE = 80_000
_MAX_PRICE = 5_000_000

_INVENTORY_RE = re.compile(
    r"(?:в\s+продаже\s+)?(?<!\d)(\d{1,4})\s+(?:квартир[а-я]*|лот[а-ов]*|предложени[йея])\b"
    r"|\b(?:квартир|лотов|предложений)\s*[:—-]?\s*(\d{1,4})\b",
    flags=re.I,
)
_SECONDARY_RE = re.compile(r"\bвторичн[а-я]*\b|\bвторичк[а-я]*\b|\bперепродаж[а-я]*\b|\bпереуступк[а-я]*\b", flags=re.I)
# У сданного дома остатки застройщика продаются объявлениями и попадают под
# метку «вторичный рынок». Для элитных Хамовников это и есть цена предложения:
# Хамовники 12, Саввинская 27, Brodsky — все сданы, и запрет на вторичку отрезал
# нас ровно от того места, где их цена лежит.
_DEVELOPER_STOCK_RE = re.compile(
    r"\bот\s+застройщика\b|\bот\s+девелопера\b|\bостатки\s+застройщика\b"
    r"|\bпоследние\s+лоты\b|\bпрямые\s+продажи\b",
    flags=re.I,
)
_PRIVATE_RESALE_RE = re.compile(
    r"\bсобственник\b|\bот\s+собственника\b|\bчастно(?:е|го)\s+лиц|\bагентств[оа]\b"
    r"|\bпереуступк[аи]\s+от\s+физ",
    flags=re.I,
)

MARKET_PRIMARY = "primary"
MARKET_DEVELOPER_STOCK = "developer_stock"
MARKET_RESALE = "resale"


def offer_market(text: str) -> str:
    """Чей это лот: застройщика или частника.

    Различать обязательно. Запретить всё, где встретилось слово «вторичный», —
    значит выбросить цену сданных элитных домов целиком; разрешить всё — значит
    смешать первичный рынок с перепродажей.
    """
    value = str(text or "")
    if not _SECONDARY_RE.search(value):
        return MARKET_PRIMARY
    if _DEVELOPER_STOCK_RE.search(value) and not _PRIVATE_RESALE_RE.search(value):
        return MARKET_DEVELOPER_STOCK
    return MARKET_RESALE
_DATE_RE = re.compile(
    r"\b(\d{1,2})\s+(январ|феврал|март|апрел|ма[йя]|июн|июл|август|сентябр|октябр|ноябр|декабр)[а-я]*\s+(\d{4})",
    flags=re.I,
)
_MONTHS = {
    "январ": 1, "феврал": 2, "март": 3, "апрел": 4, "ма": 5, "май": 5, "июн": 6,
    "июл": 7, "август": 8, "сентябр": 9, "октябр": 10, "ноябр": 11, "декабр": 12,
}

MATCH_EXTERNAL_ID = "external_id"
MATCH_TITLE = "project_page_title"
MATCH_NONE = "unverified"


@dataclass(frozen=True)
class PriceObservation:
    price_per_sqm: int
    source: str
    url: str
    title: str
    method: str
    match: str
    observed_at: str | None
    market: str = MARKET_PRIMARY

    @property
    def quality(self) -> str:
        if self.method.endswith("_from_page"):
            # Со страницы обычно снимается «от N ₽/м²» — нижняя граница прайса,
            # а не средняя по проекту. Как ориентир годится, как котировка нет.
            return "low"
        if self.market == MARKET_DEVELOPER_STOCK:
            # Остатки в сданном доме — законная цена предложения, но лотов мало
            # и выбор смещён, поэтому качество ниже котировки первичного рынка.
            return "low"
        if self.method == "derived_total_div_area":
            # Цена метра, посчитанная из цены лота и его площади, зависит от
            # того, какой именно лот попал в сниппет. Это ориентир, не котировка.
            return "low"
        return "high" if self.match == MATCH_EXTERNAL_ID else "medium"

    def to_dict(self) -> dict[str, Any]:
        return {
            "price_per_sqm": self.price_per_sqm,
            "source": self.source,
            "url": self.url,
            "method": self.method,
            "match": self.match,
            "observed_at": self.observed_at,
            "quality": self.quality,
            "market": self.market,
        }


def observed_date(text: str) -> str | None:
    match = _DATE_RE.search(str(text or ""))
    if not match:
        return None
    month = _MONTHS.get(match.group(2).lower())
    if not month:
        return None
    try:
        return date(int(match.group(3)), month, int(match.group(1))).isoformat()
    except ValueError:
        return None


def document_matches_entity(entity, doc: SearchDoc) -> str:
    """Как именно документ доказан принадлежащим сущности."""
    ref = classify_document(doc.url, doc.title, doc.snippet)
    if not is_pricing_source(ref):
        return MATCH_NONE
    if ref.external_id and ref.external_id in entity.external_ids:
        return MATCH_EXTERNAL_ID
    title_name = cut_at_separator(doc.title)
    if not title_name:
        return MATCH_NONE
    if labels_match(title_name, [entity.canonical_name, *entity.aliases]):
        return MATCH_TITLE
    return MATCH_NONE


class VerifiedPriceEnricher:
    def __init__(
        self,
        search: YandexSearchClient,
        *,
        today: date | None = None,
        pages: PageFetcher | None = None,
    ):
        self.search = search
        self.today = today or date.today()
        # Дозагрузка страниц необязательна: без неё поведение прежнее.
        self.pages = pages

    def collect(self, entity, locality: str) -> dict[str, Any]:
        # В запрос идёт имя без кавычек и скобок: Search API внутри кавычек ищет
        # точную фразу, и «Клубный дом «Саввинская 17»» не находил ничего.
        name = search_name(entity.canonical_name)
        short = min(
            (search_name(alias) for alias in entity.aliases if search_name(alias)),
            key=len,
            default=name,
        )
        # Кавычки в запросе требуют точной фразы. Вместе с оператором site: это
        # почти всегда пустая выдача: на живом стенде цену не нашёл ни один
        # проект. Отбор всё равно делает не запрос, а доказательство привязки
        # документа к сущности, поэтому кавычки здесь только вредят.
        # Слова «цена за м²» в запросе нужны, чтобы поисковик собрал сниппет с
        # ценой: разбираем мы именно сниппет, а не саму страницу.
        queries = [
            f"site:cian.ru {name} ЖК {locality} цена за м²",
            f"site:realty.yandex.ru {name} {locality} новостройка цена за м²",
            f"site:domclick.ru {name} {locality} ЖК стоимость квадратного метра",
            f"site:novostroy.ru {name} {locality} цены за м²",
            f"{name} {locality} ЖК официальный сайт цена за м²",
        ]
        if short and short != name:
            queries.append(f"{short} {locality} ЖК цена за м²")
        docs: list[SearchDoc] = []
        seen: set[str] = set()
        errors: list[str] = []
        for query in queries:
            try:
                found = self.search.search(query, groups_on_page=10)
            except RemoteServiceError as exc:
                errors.append(str(exc))
                continue
            for doc in found:
                if doc.url in seen:
                    continue
                seen.add(doc.url)
                docs.append(doc)

        # Карточки самой сущности уже есть в выдаче discovery — их тоже
        # используем, повторный запрос за ними не нужен.
        for candidate in entity.candidates:
            if candidate.source_kind not in {PROJECT_PAGE, DEVELOPER_PAGE} or candidate.source_url in seen:
                continue
            seen.add(candidate.source_url)
            docs.append(
                SearchDoc(
                    title=candidate.source_title,
                    url=candidate.source_url,
                    domain=candidate.source_domain,
                    snippet=candidate.source_snippet,
                    rank=candidate.search_rank,
                )
            )

        observations: list[PriceObservation] = []
        rejected: list[dict[str, Any]] = []
        inventory: dict[str, Any] | None = None

        for doc in docs:
            text = " ".join(part for part in (doc.title, doc.snippet) if part)
            match = document_matches_entity(entity, doc)
            if match == MATCH_NONE:
                if _PRICE_M2_RE.search(text):
                    rejected.append({"url": doc.url, "reason": "entity_match_not_proven"})
                continue
            market = offer_market(text)
            if market == MARKET_RESALE:
                rejected.append({"url": doc.url, "reason": "private_resale"})
                continue

            source = MarketPriceEnricher._source_name(doc)
            when = observed_date(text)
            for value, method in self._priced(text):
                observations.append(
                    PriceObservation(
                        price_per_sqm=value,
                        source=source,
                        url=doc.url,
                        title=doc.title,
                        method=method,
                        match=match,
                        observed_at=when,
                        market=market,
                    )
                )
            if inventory is None:
                inventory = self._inventory(text, source, doc.url, match, when)

        if not observations and self.pages is not None:
            # Сниппет цены не дал — открываем страницу. Только ту, что уже
            # доказана принадлежащей проекту: искать цену «где-нибудь» нельзя.
            observations = self._prices_from_pages(entity, docs, rejected)

        observations = self._dedupe(observations)
        price = self._summarize(observations, queries, errors, rejected)
        return {
            "price": price,
            "inventory": inventory or self._unknown_inventory(),
            "rejected_observations": rejected[:10],
        }

    def _prices_from_pages(
        self, entity, docs: list[SearchDoc], rejected: list[dict[str, Any]]
    ) -> list[PriceObservation]:
        """Одна страница — не больше одной цены.

        Сниппет говорит о проекте одним-двумя числами, страница — десятками:
        лоты, соседние корпуса, а на сайте агентства и вовсе чужие проекты.
        Правило сниппета «взять все числа и посчитать медиану» на странице
        даёт число, не принадлежащее никому: на Гродненской у «Кунцево»
        вышло 1 473 851 ₽/м² при пяти наблюдениях от 251 212 до 1 586 948 —
        разброс в шесть раз, невозможный внутри одного проекта.
        """
        out: list[PriceObservation] = []
        for doc in docs:
            if not fetchable(doc.url):
                continue
            match = document_matches_entity(entity, doc)
            if match == MATCH_NONE:
                continue
            page = self.pages.get(doc.url)
            if page is None:
                continue
            # Заголовок страницы — второе доказательство, что открылось то самое:
            # адрес мог увести на общий раздел сайта застройщика.
            if page.title and not labels_match(
                cut_at_separator(page.title), [entity.canonical_name, *entity.aliases]
            ):
                continue
            market = offer_market(page.text)
            if market == MARKET_RESALE:
                continue
            source = MarketPriceEnricher._source_name(doc)
            when = observed_date(page.text)
            value, method = self._page_price(page.text)
            if value is None:
                rejected.append({"url": doc.url, "reason": method})
                continue
            out.append(
                PriceObservation(
                    price_per_sqm=value,
                    source=source,
                    url=doc.url,
                    title=page.title or doc.title,
                    method=method,
                    match=match,
                    observed_at=when,
                    market=market,
                )
            )
            break
        return out

    # Во сколько раз цены метра на одной странице могут разойтись, оставаясь
    # ценами одного проекта. Пентхаус дороже студии, но не втрое.
    _PAGE_SPREAD = 2.5

    @staticmethod
    def _page_price(text: str) -> tuple[int, str] | tuple[None, str]:
        """Цена проекта со страницы — или отказ с причиной.

        Порядок предпочтения не случаен. «от N ₽/м²» — это цена входа, которую
        страница называет о проекте целиком; всё остальное на ней относится к
        отдельным лотам. Если такой формулировки нет, годится середина — но
        только когда числа страницы вообще похожи на один прайс.
        """
        entries: list[tuple[int, bool]] = []
        seen: set[tuple[int, int]] = set()
        for pattern in (_PRICE_M2_RE, _PRICE_M2_REVERSED_RE):
            for found in pattern.finditer(text):
                span = found.span("value")
                if span in seen:
                    continue
                seen.add(span)
                value = MarketPriceEnricher._price_m2_match_to_int(found)
                if not _MIN_PRICE <= value <= _MAX_PRICE:
                    continue
                prefix = text[max(0, found.start() - 12) : found.start()].lower()
                entries.append((value, bool(re.search(r"\bот\s*$", prefix))))

        entry_prices = sorted({value for value, is_entry in entries if is_entry})
        if entry_prices:
            return entry_prices[0], "entry_price_from_page"

        values = sorted({value for value, _ in entries})
        if not values:
            derived = [
                value
                for value in MarketPriceEnricher._derived_prices_from_area_and_total(text)
                if _MIN_PRICE <= value <= _MAX_PRICE
            ]
            values = sorted(set(derived))
            if not values:
                return None, "page_without_price"
            method = "derived_total_div_area_from_page"
        else:
            method = "median_from_page"

        if values[-1] > values[0] * VerifiedPriceEnricher._PAGE_SPREAD:
            return None, "page_lists_unrelated_prices"
        return int(round(statistics.median(values))), method

    @staticmethod
    def _prices(text: str) -> list[int]:
        return [value for value, _ in VerifiedPriceEnricher._priced(text)]

    @staticmethod
    def _priced(text: str) -> list[tuple[int, str]]:
        """Цена метра и то, как она получена.

        Прямая котировка надёжнее производной, поэтому способ едет вместе с
        числом: по нему потом ставится качество наблюдения.
        """
        out: list[tuple[int, str]] = []
        seen: set[tuple[int, int]] = set()
        for pattern in (_PRICE_M2_RE, _PRICE_M2_REVERSED_RE):
            for match in pattern.finditer(text):
                span = match.span("value")
                if span in seen:
                    continue
                seen.add(span)
                value = MarketPriceEnricher._price_m2_match_to_int(match)
                if _MIN_PRICE <= value <= _MAX_PRICE:
                    out.append((value, "explicit_per_sqm"))
        if out:
            return out
        # Второй путь, потерянный при переписывании: страница называет цену лота
        # и его площадь, но не цену метра. У v4 он был, у v6 пропал, и элитные
        # карточки, где пишут «квартира 120 м² — 250 млн ₽», остались без цены.
        for value in MarketPriceEnricher._derived_prices_from_area_and_total(text):
            if _MIN_PRICE <= value <= _MAX_PRICE:
                out.append((value, "derived_total_div_area"))
        return out

    @staticmethod
    def _dedupe(items: list[PriceObservation]) -> list[PriceObservation]:
        seen: set[tuple[int, str]] = set()
        out: list[PriceObservation] = []
        for item in items:
            key = (item.price_per_sqm, item.url)
            if key in seen:
                continue
            seen.add(key)
            out.append(item)
        return out

    def _summarize(
        self,
        observations: list[PriceObservation],
        queries: list[str],
        errors: list[str],
        rejected: list[dict[str, Any]],
    ) -> dict[str, Any]:
        if not observations:
            return {
                "available": False,
                "verified": False,
                "basis": "none",
                "reason": (
                    "Ни одно ценовое наблюдение не подтверждено принадлежностью проекту"
                    if rejected
                    else "Цена предложения не найдена в проиндексированных карточках проекта"
                ),
                "rejected_count": len(rejected),
                "queries": queries,
                "errors": errors[:3],
            }
        values = [item.price_per_sqm for item in observations]
        dates = sorted(item.observed_at for item in observations if item.observed_at)
        order = {"high": 3, "medium": 2, "low": 1}
        best = max((item.quality for item in observations), key=lambda value: order[value])
        return {
            "available": True,
            "verified": True,
            "basis": "verified_project_page_asking",
            "price_per_sqm": int(round(statistics.median(values))),
            "price_per_sqm_min": min(values),
            "price_per_sqm_max": max(values),
            "price_per_sqm_avg": int(round(statistics.fmean(values))),
            "price_per_sqm_median": int(round(statistics.median(values))),
            "sample_count": len(values),
            "sources": sorted({item.source for item in observations}),
            "observed_at": dates[-1] if dates else None,
            "retrieved_at": self.today.isoformat(),
            "quality": best,
            "markets": sorted({item.market for item in observations}),
            "observations": [item.to_dict() for item in observations[:20]],
            "note": "Цены предложения с карточек проекта; не цены сделок",
        }

    @staticmethod
    def _unknown_inventory() -> dict[str, Any]:
        return {
            "units": None,
            "source": None,
            "observed_at": None,
            "quality": "unknown",
            "note": "Экспозиция не извлекается достоверно из поискового индекса",
        }

    def _inventory(
        self, text: str, source: str, url: str, match: str, when: str | None
    ) -> dict[str, Any] | None:
        found = _INVENTORY_RE.search(text)
        if not found:
            return None
        raw = found.group(1) or found.group(2)
        try:
            units = int(raw)
        except (TypeError, ValueError):
            return None
        if not 0 < units <= 5000:
            return None
        return {
            "units": units,
            "source": source,
            "url": url,
            "observed_at": when,
            "retrieved_at": self.today.isoformat(),
            "quality": "reported" if match == MATCH_EXTERNAL_ID else "low",
            "note": "Число лотов из сниппета карточки проекта; требует проверки на сайте источника",
        }
