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
import statistics
from pathlib import Path
from typing import Any

from .candidates_v6 import extract_candidates, registry_candidate
from .documents import classify_document
from .entities import ProjectEntity, merge_geographic_duplicates, resolve_entities
from .geo_resolution import RESOLVED, ProjectGeoResolver, address_signature
from .geocoder import GeoPoint
from .http import RemoteServiceError
from .dynamics import SalesDynamics
from .market_reference import MoscowMarket
from .metrics import build_blocks
from .verdict import build_notes, positioning, premium_series, price_of_premium
from .page_price import PageFetcher
from .price_hint import price_hint
from .pulse import PulseClient
from .price_evidence import VerifiedPriceEnricher
from .recommendation import market_recommendation, official_recommendation
from .registry import ProjectRegistry
from .subject import Subject, resolve_subject
from .segments import SegmentResolver, detect_district, districts_match, segments_comparable
from .service import MarketDiscoveryService as LegacyMarketDiscoveryService, haversine_km
from .yandex_search import official_cards_from_docs


def _fresh_price_since(today) -> str:
    """С какой даты прайс считается действующим.

    Полгода — не догадка: на живом стенде прайсы делятся на свежие, где дата
    этого месяца, и мёртвые, где 2020–2023 год у сданных домов. Промежутка
    между ними почти нет.
    """
    year, month = today.year, today.month - 6
    while month <= 0:
        month += 12
        year -= 1
    return f"{year:04d}-{month:02d}-01"


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
        self.pages = PageFetcher(Path(data_dir) / "pages")
        self.verified_prices = VerifiedPriceEnricher(self.search, pages=self.pages)
        # Справочника может не быть — тогда конвейер работает как прежде, только
        # без якоря. Пустой реестр не ошибка, а отсутствие выгрузки.
        self.registry = ProjectRegistry.load(
            ProjectRegistry.bundled_directory(), Path(data_dir) / "registry"
        )
        # Платный источник и городской свод. Нет доступов — оба выключены, и
        # модуль работает как прежде.
        self.pulse = PulseClient(Path(data_dir) / "pulse")
        self.city = MoscowMarket.bundled()
        # История продаж и остатка: живой источник её не отдаёт, она вынута из
        # помесячного отчёта и едет с кодом.
        self.dynamics = SalesDynamics.bundled()
        # Разбор кадастрового номера живёт в движке: там НСПД, там же его
        # используют ТЭП и анализ территории. Второй такой путь заводить нельзя,
        # иначе один и тот же номер даст в двух местах разные точки.
        self.cadastre_lookup: Any = None
        # Платон живёт в движке; модуль рынка знает о нём только через этот
        # крючок. Нет движка — нет и вопроса, и это говорится вслух.
        self.plato_ask: Any = None
        # Адресные подсказки — тот же DaData, что у адресного поиска движка.
        # Свой геокодер здесь не заводится: две реализации разошлись бы на
        # нормализации, и одна строка приводила бы к разным точкам.
        self.address_suggest: Any = None

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
            # Реестр ЕИСЖС — единственный полный список строек района, и в нём
            # у каждой есть адрес. Без него проект, не попавший в каталоги
            # агрегаторов, не находился вовсе.
            f'site:наш.дом.рф жилой комплекс "{area}" {locality}',
            f'site:наш.дом.рф строящиеся дома "{area}" {locality}',
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
        # Проекты района из справочника подмешиваются к найденным поиском: то,
        # что числится в реестре, существует наверняка, и угадывать его имя не
        # нужно. Сущности сольются по ключу, если поиск их уже принёс.
        registry_seeded = [
            registry_candidate(project) for project in self.registry.by_district(subject_district)
        ]
        candidates = candidates + registry_seeded
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
            if self._is_subject_itself(entity, address, subject.display_name):
                quarantine.append(
                    self._quarantined(
                        entity,
                        "subject_itself",
                        "Это сам объект оценки, а не соседний проект",
                    )
                )
                continue
            if self.registry.is_developer_name(entity.canonical_name):
                quarantine.append(
                    self._quarantined(
                        entity,
                        "developer_not_project",
                        f"{entity.canonical_name} — застройщик из справочника, а не проект",
                    )
                )
                continue
            geo = resolver.resolve(entity)
            if geo.status != RESOLVED or geo.point is None:
                quarantine.append(self._quarantined(entity, geo.status, geo.reason))
                continue

            # Совпал адрес — значит это стройка на самом участке, а не сосед.
            # Имя тут ни при чём: на Гродненской, 18 объект оценки нашёл сам
            # себя дважды, «Кутузов Сити» и «Клубный проект Кутузов Сити», оба
            # в нуле километров. Проверка по имени такое не ловит — вывеска
            # адреса не содержит, поэтому адрес сверяется после разрешения.
            if subject_signature and address_signature(geo.address) == subject_signature:
                quarantine.append(
                    self._quarantined(
                        entity,
                        "subject_itself",
                        f"Адрес проекта {geo.address} — это сам объект оценки",
                        distance_km=0.0,
                    )
                )
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

        # Справочник — источник истины о девелопере, районе и темпе продаж.
        for row in rows:
            known = self.registry.find(row["name"])
            if known is None:
                row["sales"] = {"units_per_month": None, "quality": "unknown"}
                continue
            row["developer"] = row.get("developer") or known.developer
            row["district"] = known.district or row.get("district")
            row["sales"] = known.velocity()
            row["in_registry"] = True

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

        self._reject_price_outliers(rows)
        self._reject_prices_far_from_official(rows, locality)

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
        # Запасной ориентир считается только при пустом основном: две базы рядом
        # соблазняют сравнить их между собой, а сравнивать нечего — предложение и
        # зарегистрированная сделка расходятся закономерно, а не ошибочно.
        official_summary = None if price_summary else official_recommendation(rows)
        # Считается то же, что идёт в ориентир. Официальная средняя ЕИСЖС в него
        # не идёт, поэтому и «проверенной ценой» она быть не может: на
        # Гродненской улице счётчик показывал 3 из 4 при трёх карточках со
        # строкой «цена предложения не найдена» — и рядом со своим же
        # заголовком «ни одно ценовое наблюдение не привязано доказанно».
        priced = sum(
            1
            for row in self._offer_priced(rows)
            if row.get("eligible_analogue")
        )
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
            "official_price_summary": official_summary,
            "warning": self._warning(rows, quarantine, price_summary, search_errors),
            "diagnostics": {
                "search_queries": queries,
                "search_errors": search_errors[:5],
                "raw_search_documents": len(docs),
                "documents_by_kind": self._documents_by_kind(docs),
                "pages": self.pages.diagnostics(),
                "registry_projects": len(self.registry),
                "registry_seeded": len(registry_seeded),
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
    def _is_subject_itself(entity: ProjectEntity, address: str | None, display_name: str) -> bool:
        """Участок сам стал кандидатом.

        На Мишина, 46 каталог назвал адрес объекта оценки, и он приехал в
        карантин как жилой комплекс «Мишина 46» с причиной «адрес совпал с
        адресом объекта оценки». Причина верная, но объект здесь вообще не
        кандидат: сравнивать площадку саму с собой бессмысленно.
        """
        subject = address_signature(address or display_name)
        if not subject:
            return False
        names = [entity.canonical_name, *entity.aliases]
        return any(address_signature(name) == subject for name in names if name)

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
            # Район справочника надёжнее строки геокодера и не зависит от того,
            # печатает её провайдер или нет.
            row_district = row.get("district") or detect_district(
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

    # Округ в своде записан коротким именем: «Западный», «Центральный».
    # Геокодер пишет его полностью, поэтому берём первое слово.
    _OKRUG_RE = re.compile(
        r"\b(Центральный|Северный|Северо-Восточный|Восточный|Юго-Восточный|Южный|"
        r"Юго-Западный|Западный|Северо-Западный|Зеленоградский|Троицкий|Новомосковский)\b"
    )

    def resolve_subject(self, query: str) -> Subject:
        """Опознать объект отчёта тем же вводом, что и в основном сервисе."""
        return resolve_subject(
            query,
            geocode=self.geocoder.geocode,
            cadastre=self.cadastre_lookup,
            find_project=self.pulse.find_project if self.pulse.available else None,
        )

    def peer_row(
        self, complex_id: int, *, latitude: float | None = None, longitude: float | None = None
    ) -> dict[str, Any]:
        """Проект в той же форме, в какой он попадает в отчёт соседом.

        Форма именно та же нарочно: строка, добавленная руками, должна вести
        себя в таблицах и на графиках как любая другая, иначе половина
        разделов её тихо пропустит.
        """
        project = self.pulse.project(int(complex_id))
        if project is None:
            raise LookupError(f"Проект {complex_id} не найден в справочнике источника")
        row: dict[str, Any] = {
            "name": project.name,
            "developer": project.developer,
            "address": project.address,
            "segment": self.pulse.segments().get(project.complex_id),
            "latitude": project.latitude,
            "longitude": project.longitude,
            "added_by_hand": True,
            **self.pulse.metrics(project.complex_id),
            **self.pulse.project_totals(project.complex_id),
            **self.pulse.remaining(project.complex_id),
        }
        if latitude is not None and longitude is not None:
            row["distance_km"] = round(
                haversine_km(latitude, longitude, project.latitude, project.longitude), 3
            )
        history = self.pulse.price_history([project.complex_id])
        row["price_series"] = history.get(project.complex_id) or []
        row["sales_series"] = self.dynamics.series(project.complex_id)
        return row

    def build_report(
        self,
        query: str,
        *,
        codes: list[str] | None = None,
        radius_km: float = 3.0,
        peers_limit: int = 12,
        segment_override: str | None = None,
    ) -> dict[str, Any]:
        """Конструктор: объект, сопоставимые соседи и выбранные разделы.

        Соседи ограничены числом нарочно: каждый стоит двух обращений к
        источнику, и отчёт по сорока пяти проектам собирался бы минуту. Берутся
        ближние — те, кто дальше, влияют на медиану слабее, а на ожидание
        сильнее. Сколько отброшено, написано в ответе.
        """
        subject = self.resolve_subject(query)
        if not self.pulse.available:
            raise RemoteServiceError(
                "Источник рыночных данных выключен: не заданы PULSE_LOGIN и PULSE_PASSWORD"
            )

        classes = self.pulse.segments()
        near = self.pulse.near(subject.latitude, subject.longitude, radius_km)

        own = None
        # Адрес нужен не для показа, а чтобы понять, покрывает ли объект свод
        # рынка. У ввода координатами и кадастром своего адреса может не быть —
        # тогда берётся адрес совпавшего проекта. Без этого отчёт по Кутузов
        # Сити, вызванный координатами, молча терял сравнение с городом.
        subject_address = subject.address
        if subject.project_id is None:
            # Площадка может совпасть с известным проектом — тогда отчёт о нём,
            # а не о безымянной точке. Ноль километров это и означает.
            for distance, project in near:
                if distance <= 0.05:
                    subject.project_id = project.complex_id
                    subject.project_name = project.name
                    subject.segment = classes.get(project.complex_id)
                    subject_address = subject_address or getattr(project, "address", None)
                    break
        if subject.project_id is not None and not subject_address:
            known = self.pulse.project(subject.project_id)
            subject_address = getattr(known, "address", None)
        if subject.project_id is not None:
            own = {
                "name": subject.project_name,
                "segment": subject.segment or classes.get(subject.project_id),
                **self.pulse.metrics(subject.project_id),
                **self.pulse.project_totals(subject.project_id),
                **self.pulse.remaining(subject.project_id),
            }

        # Класс ставит «Пульс» — решение владельца от 18.08.2026, ручной подмены
        # в конструкторе нет. Но у голого участка проекта в источнике нет, и
        # тогда класс приходится брать у окружения. Догадка и метка источника в
        # ответе выглядят одинаково, поэтому происхождение называется отдельным
        # полем: без него отчёт по пустырю неотличим от отчёта по проекту.
        segment = (own or {}).get("segment") or subject.segment
        segment_source = "pulse" if segment else None
        source_segment: str | None = None
        if segment_override:
            # Класс по умолчанию ставит «Пульс» — решение владельца от
            # 18.08.2026. Ручной выбор в кабинете его не отменяет: он
            # называется отдельным источником и виден в отчёте строкой, иначе
            # два мнения об одном классе разошлись бы незаметно.
            source_segment, segment = segment, segment_override
            segment_source = "manual"
        if not segment:
            votes: dict[str, int] = {}
            for _, project in near[:20]:
                found = classes.get(project.complex_id)
                if found:
                    votes[found] = votes.get(found, 0) + 1
            segment = max(votes, key=lambda key: votes[key]) if votes else None
            if segment:
                segment_source = "neighbours"

        comparable = [
            (distance, project)
            for distance, project in near
            if project.complex_id != subject.project_id
            and segments_comparable(segment, classes.get(project.complex_id))
        ]
        # Прайс старше полугода — это не цена рынка, а след того, что проект
        # давно распродан: у сданных домов он бывает 2020 года. Такой сосед
        # тянет медиану вниз и делает отчёт достоверным на вид.
        fresh_since = _fresh_price_since(self.verified_prices.today)
        peers: list[dict[str, Any]] = []
        stale = 0
        priceless = 0
        for distance, project in comparable:
            if len(peers) >= peers_limit:
                break
            metrics = self.pulse.metrics(project.complex_id)
            observed = str(metrics.get("observed_at") or "")
            # «Цены нет» и «цена устарела» — разные ответы. В Мытищах источник
            # знает проекты и их координаты, но чисел по ним у подписки нет
            # вовсе, а счётчик показывал «прайс устарел» и уводил искать
            # несуществующий старый прайс.
            if not metrics.get("price_per_sqm"):
                priceless += 1
                continue
            if observed < fresh_since:
                stale += 1
                continue
            peers.append(
                {
                    "name": project.name,
                    "developer": project.developer,
                    "distance_km": distance,
                    "segment": classes.get(project.complex_id),
                    **metrics,
                }
            )

        # История цены — одним запросом на весь набор: источник умеет отдавать
        # сразу несколько проектов, а поштучный опрос стоил бы ожидания на
        # каждого соседа.
        history = self.pulse.price_history(
            [subject.project_id] + [row["complex_id"] for row in peers if row.get("complex_id")]
        )
        for row in peers:
            row["price_series"] = history.get(row.get("complex_id")) or []
            row["sales_series"] = self.dynamics.series(row.get("complex_id"))
            # Остаток у соседа не спрашиваем поштучно — это ещё один запрос на
            # каждого. Он есть в помесячном отчёте: берётся последняя точка и
            # помечается своим источником, потому что она месячной давности.
            last = next((p for p in reversed(row["sales_series"]) if p.get("rem") is not None), None)
            if last and row.get("remaining_units") is None:
                row["remaining_units"] = last["rem"]
                row["remaining_as_of"] = last["month"]
                row["remaining_source"] = "отчёт за месяц"

        subject_metrics = own or {"name": subject.project_name or query, "segment": segment}
        subject_series = history.get(subject.project_id) or []
        subject_sales = self.dynamics.series(subject.project_id)
        # Свод собран по одному отчёту, «Москва старая». Вне его покрытия
        # городская база не подставляется вовсе: медианы чужого города,
        # выданные молча, выглядят исправным сравнением.
        where = " ".join(filter(None, [subject_address, subject.query]))
        city_scope = self.city.scope(where)
        reference = self.city if city_scope["covered"] else MoscowMarket({})
        blocks = build_blocks(subject_metrics, peers, reference, codes)
        notes = build_notes(blocks, subject_series)
        notes["premium_series"] = premium_series(subject_series, peers)
        notes["price_of_premium"] = price_of_premium(subject_metrics, peers)
        notes["positioning"] = positioning(subject_metrics, peers, reference)
        # Ориентир цены для площадки без своего прайса считается по той же
        # выборке, что и отчёт. Кнопка ходила своим путём — радиус 2,5 км и
        # двадцать ближайших, — и на участке в Новогирееве отвечала «по классу
        # в Москве» при пятнадцати сопоставимых соседях на экране: ориентир
        # будущего проекта строился по городу, а конкуренты его стояли рядом.
        # Правило одно и то же (`price_hint`), меняется только набор соседей.
        okrug_match = self._OKRUG_RE.search(f"{subject_address or ''} {subject.query or ''}")
        hint = price_hint(
            peers=[
                {
                    "price_per_sqm": row.get("price_per_sqm"),
                    "observed_at": row.get("observed_at"),
                    "segment": row.get("segment"),
                }
                for row in peers
            ],
            segment=segment,
            okrug=okrug_match.group(1) if okrug_match else None,
            city=reference,
            fresh_since=fresh_since,
        )
        return {
            "price_hint": hint,
            "subject": {
                **subject.to_dict(),
                "segment": segment,
                "segment_source": segment_source,
                "segment_by_source": source_segment,
                "metrics": subject_metrics,
            },
            "blocks": blocks,
            "analysis": notes,
            "price_series": subject_series,
            "sales_series": subject_sales,
            "dynamics": {
                "source": self.dynamics.source,
                "last_month": self.dynamics.last_month,
                "covered": self.dynamics.coverage(subject.project_id),
            },
            "peers": peers,
            "comparison": {
                "radius_km": radius_km,
                "segment": segment,
                "segment_source": segment_source,
                "found": len(near),
                "comparable": len(comparable),
                "used": len(peers),
                "stale_price": stale,
                "no_price": priceless,
                "fresh_since": fresh_since,
                "dropped": max(len(comparable) - len(peers) - stale - priceless, 0),
            },
            "city": {
                "source": self.city.source,
                "observed_at": self.city.observed_at,
                "scope": city_scope,
            },
            "retrieved_at": self.verified_prices.today.isoformat(),
        }

    def price_hint(
        self,
        *,
        address: str | None,
        latitude: float | None = None,
        longitude: float | None = None,
        segment: str | None = None,
        radius_km: float = 2.5,
        budget: int = 20,
    ) -> dict[str, Any]:
        """Ориентир цены для поля модели: одно число, без списка проектов.

        Это не отчёт. Отчёт объясняет и показывает, на чём построен; здесь
        нужно подставить цифру в «Цена квартир», когда своей ещё нет. Наружу
        уходит значение, дата и число наблюдений — перечень проектов остаётся
        в аналитике, где его можно проверить.
        """
        # Ввод разбирается тем же правилом, что и объект отчёта. Здесь стоял
        # свой разбор — только адресный, — и кадастровый номер уходил в
        # геокодер строкой. С поля «Участок» приходит не один номер, а весь
        # список через запятую, и Nominatim отвечал на него 400 Bad Request:
        # кнопка ломалась ровно на том вводе, ради которого её сделали.
        # Одно правило на приложение — иначе один ввод даёт в двух местах
        # разные точки, и это уже было с версией и со списком полей.
        if latitude is not None and longitude is not None:
            point = self._subject_point(address, latitude, longitude)
            where = point.display_name or (address or "")
            subject_latitude, subject_longitude = point.latitude, point.longitude
        else:
            found = self.resolve_subject(str(address or ""))
            where = found.address or found.query
            subject_latitude, subject_longitude = found.latitude, found.longitude
        okrug_match = self._OKRUG_RE.search(where or "")
        okrug = okrug_match.group(1) if okrug_match else None

        peers: list[dict[str, Any]] = []
        if self.pulse.available:
            classes = self.pulse.segments()
            near = self.pulse.near(subject_latitude, subject_longitude, radius_km)
            for _, project in near[:budget]:
                price = self.pulse.price(project.complex_id)
                if not price:
                    continue
                peers.append(
                    {
                        "price_per_sqm": price["price_per_sqm"],
                        "observed_at": price.get("observed_at"),
                        "segment": classes.get(project.complex_id),
                    }
                )
            if segment is None:
                votes: dict[str, int] = {}
                for _, project in near[:budget]:
                    found = classes.get(project.complex_id)
                    if found:
                        votes[found] = votes.get(found, 0) + 1
                segment = max(votes, key=lambda key: votes[key]) if votes else None

        # Городская база подставляется только внутри своего покрытия. Иначе
        # для Мытищ кнопка отвечала «по классу в Москве» и выдавала московскую
        # медиану за ориентир подмосковного участка — число выглядело ответом,
        # а было ответом про другой город.
        scope = self.city.scope(where)
        hint = price_hint(
            peers=peers,
            segment=segment,
            okrug=okrug,
            city=self.city if scope["covered"] else MoscowMarket({}),
            fresh_since=_fresh_price_since(self.verified_prices.today),
        )
        if not scope["covered"] and not hint.get("available"):
            hint["reason"] = (
                f"{hint.get('reason') or 'Ориентир не рассчитан'}. "
                f"Свод рынка собран по отчёту «{scope['label']}» и для этого адреса не применяется"
            )
        hint["location"] = {
            "display_name": where,
            "okrug": okrug,
            "radius_km": radius_km,
            "city_reference": scope["covered"],
        }
        return hint

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

    # Во сколько раз цена проекта может отличаться от медианы соседей того же
    # класса и района, оставаясь его ценой.
    _PEER_SPREAD = 3.0
    # Насколько цена предложения может уйти от официальной средней ЕИСЖС по
    # карточке того же проекта. Вверх — далеко: средняя считается по сделкам,
    # зарегистрированным в том числе на старте продаж, и отстаёт от текущего
    # прайса кратно. Вниз — почти никуда: предложение ниже уже случившихся
    # сделок означало бы обвал рынка вдвое.
    _OFFICIAL_SPREAD_HIGH = 6.0
    _OFFICIAL_SPREAD_LOW = 2.0

    @staticmethod
    def _offer_priced(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Строки с ценой предложения — без официальных средних.

        Смешивать их нельзя. Официальная средняя ЕИСЖС — среднее по
        зарегистрированным сделкам, она отстаёт от прайса в разы, и в ориентир
        по аналогам не идёт именно поэтому. На Гродненской улице медиана
        «соседей» набралась из двух таких средних, 143 493 и 404 524, и убила
        верную цену Кунцево 496 311 ₽/м² как невозможную.
        """
        return [
            row
            for row in rows
            if row.get("price_verified")
            and (row.get("market_price") or {}).get("basis") != "official_domrf_fallback"
        ]

    def _reject_prices_far_from_official(
        self, rows: list[dict[str, Any]], locality: str
    ) -> None:
        """Проверить цену по официальной средней самого проекта.

        Нужно там, где сравнивать не с кем: на улице Мишина цен в выборке было
        две, «Клубный дом Юннаты» 4 566 681 ₽/м² и «Симфония 34» 431 753, и
        по двум числам, расходящимся в десять раз, большинством не решить,
        какое ложное. Якорь берётся вне выборки — из карточки ЕИСЖС этого же
        проекта, привязка которой уже доказана адресом и названием.

        Запрос стоит обращения к поиску, поэтому делается только на короткой
        выборке: там, где соседей хватает, решение принимает проверка по ним.
        """
        priced = self._offer_priced(rows)
        if len(priced) >= 3:
            return
        for row in priced:
            cards = row.get("official_cards") or []
            if not cards or not row.get("name"):
                continue
            try:
                official = self.official_prices.project_price(row["name"], locality, cards)
            except RemoteServiceError:
                continue
            anchor = official.get("price_per_sqm") if official.get("available") else None
            if not anchor:
                continue
            value = int(row["market_price"]["price_per_sqm"])
            if (
                value <= anchor * self._OFFICIAL_SPREAD_HIGH
                and value >= anchor / self._OFFICIAL_SPREAD_LOW
            ):
                row["market_price"]["official"] = official
                continue
            self._drop_price(
                row,
                value,
                reason=(
                    f"{value:,} ₽/м² против официальной средней ЕИСЖС {int(anchor):,} ₽/м² "
                    "по карточке этого же проекта — это не его цена"
                ).replace(",", " "),
                marker="price_far_from_official_average",
                peer=int(anchor),
            )

    @staticmethod
    def _drop_price(
        row: dict[str, Any], value: int, *, reason: str, marker: str, peer: int
    ) -> None:
        """Снять цену, оставив её видимой в отбракованных."""
        price = row.get("market_price") or {}
        row["rejected_price_observations"] = [
            *row.get("rejected_price_observations", []),
            {
                "url": (price.get("observations") or [{}])[0].get("url", ""),
                "reason": marker,
                "price_per_sqm": value,
                "peer_median": peer,
            },
        ]
        row["market_price"] = {
            "available": False,
            "verified": False,
            "basis": "rejected_outlier",
            "reason": reason,
            "rejected_count": 1,
        }
        row["price_verified"] = False
        row["eligible_analogue"] = False
        row["evidence"] = MarketDiscoveryService._evidence_label(row)

    @staticmethod
    def _reject_price_outliers(rows: list[dict[str, Any]]) -> None:
        """Снять цену, невозможную рядом с соседями по классу и району.

        Диапазон правдоподобия 80 тыс — 5 млн ₽/м² задан на всю Москву и потому
        пропускает то, что видно с одного взгляда: на Саввинской набережной
        River House получил 158 850 ₽/м², а Фрунзенский 175 000 — при соседях
        по 2,5–3,5 млн. Элитные Хамовники столько не стоят, и ориентир по
        аналогам эти два числа занижали.

        Мерой служит сама выборка: после отбора по сопоставимости в ней уже
        только один класс и один район. Медиана считается без самого проверяемого
        проекта, иначе он подпирает собственную оценку. Меньше трёх цен — сравнивать
        не с чем, и тогда не трогаем ничего.
        """
        priced = MarketDiscoveryService._offer_priced(rows)
        if len(priced) < 3:
            return
        values = [int(row["market_price"]["price_per_sqm"]) for row in priced]
        for index, (row, value) in enumerate(zip(priced, values)):
            others = [other for position, other in enumerate(values) if position != index]
            peer = statistics.median(others)
            if not peer:
                continue
            ratio = value / peer if value > peer else peer / value
            if ratio <= MarketDiscoveryService._PEER_SPREAD:
                continue
            MarketDiscoveryService._drop_price(
                row,
                value,
                reason=(
                    f"{value:,} ₽/м² против {int(round(peer)):,} ₽/м² у соседей "
                    "того же класса и района — это не цена этого проекта"
                ).replace(",", " "),
                marker="price_far_from_peers",
                peer=int(round(peer)),
            )

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
