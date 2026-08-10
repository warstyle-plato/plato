"""Market discovery v6: сущность прежде географии, география прежде цены.

Порядок шагов — не стиль, а способ сделать прошлые ошибки невозможными:

    документы -> тип документа -> кандидаты -> сущности ЖК
              -> адрес с доказательством -> координаты -> расстояние
              -> цена при доказанной привязке -> рекомендация -> ответ

Сущность, не прошедшая шаг, не исчезает молча: она уходит в `quarantine` со
статусом и причиной. Скрытая потеря кандидата раньше выглядела как хороший
результат, а видимой была только та часть мусора, что прошла до конца.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from .candidates_v6 import extract_candidates
from .documents import classify_document
from .entities import ProjectEntity, merge_geographic_duplicates, resolve_entities
from .geo_resolution import RESOLVED, ProjectGeoResolver, address_signature
from .geocoder import GeoPoint
from .http import RemoteServiceError
from .price_evidence import VerifiedPriceEnricher
from .recommendation import market_recommendation
from .segments import SegmentResolver, detect_district, districts_match, segments_comparable
from .service import MarketDiscoveryService as LegacyMarketDiscoveryService, haversine_km
from .yandex_search import official_cards_from_docs


def _count_by_status(rows: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in rows:
        key = str(row.get("status") or "unknown")
        counts[key] = counts.get(key, 0) + 1
    return dict(sorted(counts.items(), key=lambda item: (-item[1], item[0])))


class MarketDiscoveryService(LegacyMarketDiscoveryService):
    """Ревизованный конвейер.

    Наследуется от v4 намеренно, минуя v5/v5.1: от базы нужны только клиенты и
    разбор локальности, а промежуточные версии несли `_geocode_project`, который
    и подставлял кандидатам адрес объекта оценки. Оставить его достижимым по
    цепочке наследования значило бы сохранить главную ошибку живой.
    """

    def __init__(self, data_dir: Path):
        super().__init__(data_dir)
        self.verified_prices = VerifiedPriceEnricher(self.search)

    def _geocode_project(self, candidate: dict[str, Any], locality: str):
        raise NotImplementedError(
            "v6 разрешает географию через ProjectGeoResolver: адрес нужен с доказательством "
            "принадлежности проекту, иначе кандидат уходит в geo_unresolved"
        )

    @staticmethod
    def _district_label(district: str | None) -> str | None:
        if not district:
            return None
        value = re.sub(r"\s+район$", "", " ".join(district.split()), flags=re.I).strip()
        return value or None

    @classmethod
    def _discovery_queries(cls, address: str, locality: str, district: str | None) -> list[str]:
        """Каталог-первым — рабочая находка v5.1, она сохранена.

        Районные страницы агрегаторов перечисляют много проектов сразу и дают
        recall, которого не даёт поштучный поиск. Опасен был не этот приём, а то,
        что из каталожного сниппета брался адрес; теперь такой кандидат помечен
        неатрибутируемым и адрес ищется отдельно.
        """
        clean = " ".join(address.split())
        area = cls._district_label(district) or clean
        queries = [
            f'site:cian.ru "Новостройки (ЖК)" "{area}" {locality} от застройщиков',
            f'site:cian.ru "{area}" {locality} "Контакты застройщика" новостройки',
            f'site:realty.yandex.ru "Новостройки (ЖК)" "{area}" {locality}',
            f'site:realty.yandex.ru "{area}" {locality} новостройки от застройщика',
            f'site:novostroy.ru/buildings "{area}" {locality}',
            f'site:domclick.ru новостройки "{area}" {locality}',
            f'новостройки "{area}" {locality} квартиры от застройщика',
            f'клубные дома "{area}" {locality} квартиры в продаже',
            f'элитные новостройки "{area}" {locality}',
            f'премиальные новостройки "{area}" {locality}',
            f'новостройки рядом с "{clean}" {locality}',
        ]
        if district:
            queries.extend(
                [
                    f'строящиеся жилые комплексы "{area}" {locality}',
                    f'сданные новостройки "{area}" {locality} от застройщика',
                ]
            )
        return list(dict.fromkeys(queries))

    def discover(
        self,
        *,
        address: str | None,
        latitude: float | None,
        longitude: float | None,
        radius_km: float,
        limit: int,
        segment: str | None = None,
    ) -> dict[str, Any]:
        subject = self._subject_point(address, latitude, longitude)
        locality = self._locality_hint(f"{address or ''} {subject.display_name}")
        district = self._district_hint(subject.display_name)
        subject_signature = address_signature(address or subject.display_name)
        subject_district = detect_district(subject.display_name)

        queries = self._discovery_queries(address or subject.display_name, locality, district)
        docs = []
        seen_urls: set[str] = set()
        search_errors: list[str] = []
        for query in queries:
            try:
                found = self.search.search(query, groups_on_page=15)
            except RemoteServiceError as exc:
                search_errors.append(f"{query}: {exc}")
                continue
            for doc in found:
                if doc.url in seen_urls:
                    continue
                seen_urls.add(doc.url)
                docs.append(doc)

        candidates = extract_candidates(docs)
        entities = resolve_entities(candidates)

        budget = min(max(limit * 4, 20), 40)
        resolver = ProjectGeoResolver(
            self.geocoder,
            self.search,
            locality=locality,
            subject_signature=subject_signature,
            locality_matches=self._locality_matches,
            search_budget=budget,
        )

        rows: list[dict[str, Any]] = []
        quarantine: list[dict[str, Any]] = []

        # Бюджет разбора тратится сначала на то, у чего есть карточка проекта, и
        # только потом на наводки из каталожных списков. Иначе мусор из списка
        # съедает целевые поиски адреса, и настоящие проекты остаются без него.
        ordered = sorted(
            entities,
            key=lambda item: (not item.project_pages, -item.extraction_confidence, item.search_rank),
        )
        for entity in ordered[:budget]:
            geo = resolver.resolve(entity)
            if geo.status != RESOLVED or geo.point is None:
                quarantine.append(self._quarantined(entity, geo.status, geo.reason))
                continue

            distance = round(
                haversine_km(
                    subject.latitude, subject.longitude, geo.point.latitude, geo.point.longitude
                ),
                3,
            )
            if distance > radius_km:
                quarantine.append(
                    self._quarantined(
                        entity,
                        "outside_radius",
                        f"Расстояние {distance} км превышает радиус {radius_km} км",
                        distance_km=distance,
                    )
                )
                continue

            rows.append(self._row(entity, geo, distance))

        # Класс дознаётся отдельно у тех, кому его не назвали каталожные
        # сниппеты: иначе жёсткий отбор выкидывает соседей в шестистах метрах.
        segments = SegmentResolver(self.search, locality=locality)
        for row in rows:
            if not row.get("segment"):
                found = segments.resolve(row["_entity"])
                if found:
                    row["segment"] = found
                    row["segment_source"] = "targeted_class_search"

        rows, class_filter = self._apply_comparability(
            rows, quarantine, subject_district=subject_district, requested=segment
        )

        # Хвост, до которого не дошёл бюджет разбора, тоже виден: молчаливое
        # отбрасывание кандидата — это потеря recall, которую не с чем сравнить.
        for entity in ordered[budget:]:
            quarantine.append(
                self._quarantined(
                    entity,
                    "not_evaluated",
                    f"Бюджет разбора {budget} сущностей исчерпан; кандидат не проверялся",
                )
            )

        rows = merge_geographic_duplicates(rows)

        for row in rows:
            entity = row.pop("_entity")
            evidence = self.verified_prices.collect(entity, locality)
            official = self._official_cards(entity, row.get("address"), locality)
            row["market_price"] = self._with_official_fallback(
                evidence["price"], entity, official, locality
            )
            row["inventory"] = evidence["inventory"]
            row["rejected_price_observations"] = evidence["rejected_observations"]
            row["official_cards"] = official
            row["confirmed"] = bool(official)
            row["price_verified"] = bool(row["market_price"].get("verified"))
            row["eligible_analogue"] = bool(
                row["price_verified"] and row.get("geo_status") == RESOLVED
            )
            row["evidence"] = self._evidence_label(row)

        rows.sort(
            key=lambda item: (
                not item.get("eligible_analogue", False),
                item.get("distance_km", 99.0),
                not item.get("confirmed", False),
            )
        )
        overflow = rows[limit:]
        rows = rows[:limit]
        for row in overflow:
            quarantine.append(
                self._quarantined_row(row, "over_limit", "Не вошёл в запрошенный лимит выдачи")
            )

        price_summary = market_recommendation(rows)
        priced = sum(1 for row in rows if row.get("eligible_analogue"))
        confirmed = sum(1 for row in rows if row.get("confirmed"))

        return {
            "query": {
                "address": address,
                "radius_km": radius_km,
                "limit": limit,
                "district": district,
                "subject_district": subject_district,
                "segment": class_filter.get("reference_segment"),
                "segment_source": class_filter.get("source"),
                "comparability": class_filter,
            },
            "location": subject.to_dict(),
            "source": {
                "discovery": "Yandex Search API; кандидат создаётся только карточкой проекта, каталогом или явно названным ЖК",
                "confirmation": "Наш.Дом.РФ / ЕИСЖС через поисковый индекс — подтверждение, не условие попадания",
                "pricing": "Цена берётся только с карточки проекта, доказанной по идентификатору или заголовку",
                "mode": "forensic_entity_pipeline_v6",
            },
            "projects": rows,
            "count": len(rows),
            "confirmed_count": confirmed,
            "priced_count": priced,
            "eligible_count": priced,
            "quarantine": quarantine,
            "quarantine_count": len(quarantine),
            "price_summary": price_summary,
            "warning": self._warning(rows, quarantine, price_summary, search_errors),
            "diagnostics": {
                "search_queries": queries,
                "search_errors": search_errors[:5],
                "raw_search_documents": len(docs),
                "documents_by_kind": self._documents_by_kind(docs),
                "candidates_extracted": len(candidates),
                "project_names_extracted": len(entities),
                "entities_resolved": len(entities),
                "candidates_geofiltered": len(rows),
                "geo_unresolved": sum(1 for item in quarantine if item["status"] == "geo_unresolved"),
                "quarantine_by_status": _count_by_status(quarantine),
                "outside_radius": sum(1 for item in quarantine if item["status"] == "outside_radius"),
            },
        }

    @staticmethod
    def _reference_segment(rows: list[dict[str, Any]]) -> str | None:
        """Класс, к которому приравнивается участок.

        Своего класса у площадки нет — она ещё не построена. Ориентиром служит
        то, чем торгуют ближайшие соседи: голос каждого весит обратно
        расстоянию, поэтому дом через дорогу значит больше, чем проект на краю
        радиуса.
        """
        votes: dict[str, float] = {}
        for row in rows:
            value = row.get("segment")
            if not value:
                continue
            distance = max(float(row.get("distance_km") or 0.25), 0.25)
            votes[value] = votes.get(value, 0.0) + 1.0 / distance
        if not votes:
            return None
        return max(votes.items(), key=lambda item: item[1])[0]

    def _apply_comparability(
        self,
        rows: list[dict[str, Any]],
        quarantine: list[dict[str, Any]],
        *,
        subject_district: str | None,
        requested: str | None,
    ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        """Жёсткий отбор по сопоставимости: класс и район.

        Радиус — геометрия, а не сравнимость. На Саввинской набережной он честно
        приводил Дом Дау: 2,2 км по прямой через реку, но небоскрёб в ММДЦ и
        клубные дома Хамовников — разный продукт. Класс один его не отсекает, он
        тоже элитный; отсекает пара «класс и район».

        Фильтр по классу включается, только когда класс известен хотя бы у двух
        проектов: иначе отбор шёл бы по одному наблюдению и выкосил бы выдачу
        целиком. По району не фильтруем там, где геокодер района не назвал.
        """
        reference = requested or self._reference_segment(rows)
        known = sum(1 for row in rows if row.get("segment"))
        class_active = bool(reference) and (bool(requested) or known >= 2)

        kept: list[dict[str, Any]] = []
        for row in rows:
            row_district = detect_district(
                str((row.get("coordinates") or {}).get("display_name") or "")
            )
            row["district"] = row_district
            if not districts_match(subject_district, row_district):
                quarantine.append(
                    self._quarantined_row(
                        row,
                        "district_mismatch",
                        f"Другой район: {row_district} против {subject_district}",
                    )
                )
                continue
            if class_active:
                if not row.get("segment"):
                    quarantine.append(
                        self._quarantined_row(
                            row,
                            "class_unknown",
                            f"Класс проекта не назван ни одним источником; ориентир — {reference}",
                        )
                    )
                    continue
                if not segments_comparable(row["segment"], reference):
                    quarantine.append(
                        self._quarantined_row(
                            row,
                            "class_mismatch",
                            f"Класс {row['segment']} против {reference}: не соседний уровень",
                        )
                    )
                    continue
            kept.append(row)

        return kept, {
            "reference_segment": reference,
            "source": "запрошен" if requested else "по ближайшим соседям" if reference else "не определён",
            "class_filter_active": class_active,
            "subject_district": subject_district,
            "known_segment_count": known,
        }

    def _subject_point(
        self, address: str | None, latitude: float | None, longitude: float | None
    ) -> GeoPoint:
        if latitude is not None and longitude is not None:
            return GeoPoint(
                latitude=latitude,
                longitude=longitude,
                display_name=address or f"{latitude:.6f}, {longitude:.6f}",
                provider="manual_coordinates",
                precision="exact",
            )
        return self.geocoder.geocode(address or "")

    @staticmethod
    def _row(entity: ProjectEntity, geo, distance: float) -> dict[str, Any]:
        base = entity.to_dict()
        primary = entity.primary_candidate
        base.update(
            {
                "distance_km": distance,
                "within_radius": True,
                "geo_status": geo.status,
                "address": geo.address,
                "address_source": geo.address_source,
                "coordinates": {
                    "latitude": geo.point.latitude,
                    "longitude": geo.point.longitude,
                    "display_name": geo.point.display_name,
                    "provider": geo.point.provider,
                    "precision": geo.point.precision,
                },
                "market_source": {
                    "url": primary.source_url,
                    "domain": primary.source_domain,
                    "title": primary.source_title,
                    "kind": primary.source_kind,
                },
                "market_source_count": max(len(entity.source_domains), 1),
                "extraction_evidence": primary.extraction_evidence,
                "_entity": entity,
            }
        )
        return base

    @staticmethod
    def _quarantined(
        entity: ProjectEntity, status: str, reason: str | None, **extra: Any
    ) -> dict[str, Any]:
        row = entity.to_dict()
        row.update({"status": status, "reason": reason, **extra})
        return row

    @staticmethod
    def _quarantined_row(row: dict[str, Any], status: str, reason: str) -> dict[str, Any]:
        return {
            "key": row.get("key"),
            "name": row.get("name"),
            "status": status,
            "reason": reason,
            "distance_km": row.get("distance_km"),
            "segment": row.get("segment"),
            "district": row.get("district"),
        }

    def _with_official_fallback(
        self,
        price: dict[str, Any],
        entity: ProjectEntity,
        cards: list[dict[str, Any]],
        locality: str,
    ) -> dict[str, Any]:
        """Официальная средняя — запасной источник, но не догадка.

        Карточка Наш.Дом.РФ попадает сюда только после `_official_card_matches`,
        то есть привязка к сущности уже доказана адресом и названием. Поэтому
        такая цена считается проверенной, но помечается низким качеством:
        средняя ЕИСЖС отражает зарегистрированные сделки и отстаёт от текущего
        предложения, и подменять им рынок нельзя.
        """
        if price.get("available") or not cards:
            return price
        try:
            official = self.official_prices.project_price(entity.canonical_name, locality, cards)
        except RemoteServiceError as exc:
            return {**price, "official_error": str(exc)}
        if not official.get("available") or not official.get("price_per_sqm"):
            return {**price, "official": official}
        return {
            "available": True,
            "verified": True,
            "basis": "official_domrf_fallback",
            "price_per_sqm": int(official["price_per_sqm"]),
            "price_per_sqm_min": official.get("min_price_per_sqm"),
            "price_per_sqm_max": official.get("max_price_per_sqm"),
            "price_per_sqm_median": int(official["price_per_sqm"]),
            "sample_count": int(official.get("observation_count") or 1),
            "sources": ["Наш.Дом.РФ"],
            "observed_at": None,
            "retrieved_at": self.verified_prices.today.isoformat(),
            "quality": "low",
            "official": official,
            "note": (
                "Цены предложения не найдены; использована официальная средняя ЕИСЖС "
                "по сопоставленной карточке — она отражает сделки и отстаёт от рынка"
            ),
        }

    def _official_cards(
        self, entity: ProjectEntity, address: str | None, locality: str
    ) -> list[dict[str, Any]]:
        query = f'site:наш.дом.рф "{entity.canonical_name}" {address or locality}'
        try:
            docs = self.search.search(query, groups_on_page=8)
        except RemoteServiceError:
            return []
        return [
            card
            for card in official_cards_from_docs(docs)
            if self._official_card_matches(
                entity.canonical_name, address, card, locality=locality
            )
        ]

    @staticmethod
    def _evidence_label(row: dict[str, Any]) -> str:
        if row.get("confirmed") and row.get("price_verified"):
            return "official_and_verified_market"
        if row.get("confirmed"):
            return "official_only"
        if row.get("price_verified"):
            return "verified_market_only"
        return "geo_only"

    @staticmethod
    def _documents_by_kind(docs) -> dict[str, int]:
        counts: dict[str, int] = {}
        for doc in docs:
            ref = classify_document(doc.url, doc.title, doc.snippet)
            counts[ref.kind] = counts.get(ref.kind, 0) + 1
        return dict(sorted(counts.items()))

    @staticmethod
    def _warning(
        rows: list[dict[str, Any]],
        quarantine: list[dict[str, Any]],
        price_summary: dict[str, Any] | None,
        search_errors: list[str],
    ) -> str | None:
        if search_errors and not rows:
            return f"Поиск не отвечает: {search_errors[0]}"
        unresolved = sum(1 for item in quarantine if item["status"] == "geo_unresolved")
        if not rows:
            if unresolved:
                return (
                    f"Проекты найдены ({unresolved}), но собственный адрес ни у одного "
                    "не подтверждён; в радиус без адреса они не ставятся"
                )
            return "В заданном радиусе не найдено проектов с подтверждённой географией"
        if price_summary is None:
            return "География подтверждена, но ни одно ценовое наблюдение не привязано к проекту доказанно"
        if unresolved:
            return (
                f"Учтено аналогов: {len(rows)}; ещё {unresolved} проектов не имеют "
                "подтверждённого адреса и вынесены в карантин"
            )
        return None
