from __future__ import annotations

import inspect
import re
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date
from typing import Iterable

from auction_search import deadline as clock
from auction_search.adapters.base import AuctionPlatformAdapter
from auction_search.catalogue_quality import catalogue_quality
from auction_search.models import AuctionLot, LotKind


class AuctionSearchService:
    """Primary-source-only auction orchestration.

    Adapters must represent the official ETP on which the procedure is conducted.
    Aggregators are deliberately unsupported.
    """

    def __init__(self, adapters: Iterable[AuctionPlatformAdapter]):
        self.adapters = list(adapters)
        self.last_quality_report: dict[str, int] = {
            "seen": 0,
            "accepted": 0,
            "incomplete": 0,
            "outside_profile": 0,
            "noise": 0,
        }

    def discover_moscow(
        self,
        *,
        include_noise: bool = False,
        budget_seconds: float | None = None,
    ) -> list[AuctionLot]:
        """Собрать каталог, уложившись в срок.

        Срок нужен не ради скорости, а ради того, чтобы ответ вообще дошёл:
        шлюз рвёт соединение раньше, чем кончается неограниченный сбор, и
        человек получает страницу ошибки вместо каталога. Источник, до
        которого не дошли, называется вслух — молча пропущенный читается как
        «лотов там нет».
        """
        until = clock.start(budget_seconds)
        lots: list[AuctionLot] = []
        if budget_seconds is not None and len(self.adapters) > 1:
            # Площадки независимы. Последовательный обход позволял первой
            # медленной ЭТП съесть все сорок секунд: следующие источники даже
            # не опрашивались, и общий поиск показывал ноль. У всех боевых
            # читателей один общий дедлайн, поэтому они безопасно работают
            # одновременно и весь каталог по-прежнему укладывается в срок.
            batches: list[list[AuctionLot] | None] = [None] * len(self.adapters)
            # Источников уже больше четырёх; искусственная очередь снова дала
            # бы первым медленным площадкам съесть общий срок до опроса новых.
            with ThreadPoolExecutor(max_workers=min(8, len(self.adapters))) as pool:
                pending = {
                    pool.submit(self._ask, adapter, until): (index, adapter)
                    for index, adapter in enumerate(self.adapters)
                }
                for future in as_completed(pending):
                    index, adapter = pending[future]
                    try:
                        batches[index] = list(future.result())
                    except Exception as exc:  # noqa: BLE001
                        self._failed(adapter, exc)
                        batches[index] = []
            for batch in batches:
                lots.extend(batch or [])
        else:
            for adapter in self.adapters:
                if clock.expired(until):
                    self._not_asked(adapter, budget_seconds)
                    continue
                try:
                    lots.extend(self._ask(adapter, until))
                except Exception as exc:  # noqa: BLE001
                    # Один недоступный источник не отменяет остальные. Прежде
                    # любое его исключение доходило до маршрута, тот отвечал
                    # 502, и каталог пропадал целиком — из-за одной площадки,
                    # у которой сеть моргнула.
                    self._failed(adapter, exc)
        lots = self._deduplicate(lots)
        assessed: list[tuple[AuctionLot, dict, dict]] = []
        for lot in lots:
            screening = self.screen_lot(lot)
            quality = catalogue_quality(lot)
            assessed.append((lot, screening, quality))
        self.last_quality_report = {
            "seen": len(assessed),
            "accepted": sum(1 for _, screen, quality in assessed
                            if screen["development_relevant"] and quality["accepted"]),
            "incomplete": sum(1 for _, screen, quality in assessed
                              if screen["development_relevant"]
                              and quality["state"] == "incomplete"),
            "outside_profile": sum(1 for _, screen, quality in assessed
                                   if screen["development_relevant"]
                                   and quality["state"] == "outside_profile"),
            "noise": sum(1 for _, screen, _ in assessed
                         if not screen["development_relevant"]),
        }
        if include_noise:
            return lots
        return [lot for lot, screen, quality in assessed
                if screen["development_relevant"] and quality["accepted"]]


    @staticmethod
    def _ask(adapter: AuctionPlatformAdapter, until: float | None) -> Iterable[AuctionLot]:
        """Позвать источник, отдав ему срок, если он умеет его читать.

        Адаптер без срока зовётся как раньше: заставлять все источники разом
        научиться сроку ради одного значило бы переписать четыре читателя
        вместо того, что нужно сейчас.
        """
        discover = adapter.discover_moscow
        try:
            takes_deadline = "deadline" in inspect.signature(discover).parameters
        except (TypeError, ValueError):  # noqa: BLE001 — встроенные и обёртки
            takes_deadline = False
        if takes_deadline:
            return discover(deadline=until)
        return discover()

    @staticmethod
    def _failed(adapter: AuctionPlatformAdapter, exc: Exception) -> None:
        """Источник ответил ошибкой — это его строка охвата, а не отказ всем."""
        said = f"источник не ответил: {type(exc).__name__}: {exc}"[:300]
        report = getattr(adapter, "last_report", None)
        if isinstance(report, dict):
            report.setdefault("pages", 0)
            report.setdefault("cards", 0)
            report.setdefault("kept", 0)
            report["reason"] = said
        else:
            adapter.last_report = {
                "source": getattr(adapter, "platform_name", adapter.__class__.__name__),
                "pages": 0, "cards": 0, "kept": 0, "reason": said,
            }

    @staticmethod
    def _not_asked(adapter: AuctionPlatformAdapter, budget_seconds: float | None) -> None:
        """Источник, до которого не дошли, обязан сказать это сам."""
        said = (
            f"источник не опрошен: на каталог отведено {budget_seconds:.0f} с, "
            "и они кончились на предыдущих"
            if budget_seconds is not None else
            "источник не опрошен"
        )
        report = getattr(adapter, "last_report", None)
        if isinstance(report, dict):
            report.update({"pages": 0, "cards": 0, "kept": 0, "reason": said})
        else:
            adapter.last_report = {
                "source": getattr(adapter, "platform_name", adapter.__class__.__name__),
                "pages": 0, "cards": 0, "kept": 0, "reason": said,
            }

    def discover_moscow_history(
        self,
        since: date,
        until: date,
        *,
        include_noise: bool = False,
        candidate_urls: Iterable[str] = (),
    ) -> list[AuctionLot]:
        """Opt-in historical discovery; never called by the production endpoint."""
        urls = tuple(candidate_urls)
        lots: list[AuctionLot] = []
        for adapter in self.adapters:
            discover = getattr(adapter, "discover_moscow_history", None)
            if discover is not None:
                lots.extend(discover(since, until, candidate_urls=urls))
        lots = self._deduplicate_history(lots)
        for lot in lots:
            self.screen_lot(lot)
        if include_noise:
            return lots
        return [lot for lot in lots if self.is_development_relevant(lot)]

    @staticmethod
    def _deduplicate_history(lots: Iterable[AuctionLot]) -> list[AuctionLot]:
        """Keep relistings: history identity is an official procedure, not a parcel."""
        by_source: OrderedDict[str, AuctionLot] = OrderedDict()
        for lot in lots:
            key = f"{lot.source.platform.value}:{lot.source.external_lot_id}"
            by_source.setdefault(key, lot)
        return list(by_source.values())

    @staticmethod
    def _deduplicate(lots: Iterable[AuctionLot]) -> list[AuctionLot]:
        by_key: OrderedDict[str, AuctionLot] = OrderedDict()
        for lot in lots:
            existing = by_key.get(lot.canonical_key)
            if existing is None:
                by_key[lot.canonical_key] = lot
                continue
            # Keep the richer official record; never merge conflicting facts silently.
            existing_score = len(existing.documents) + len(existing.provenance)
            new_score = len(lot.documents) + len(lot.provenance)
            if new_score > existing_score:
                by_key[lot.canonical_key] = lot
        return list(by_key.values())

    @staticmethod
    def is_development_relevant(lot: AuctionLot) -> bool:
        return AuctionSearchService.screen_lot(lot)["development_relevant"]

    @staticmethod
    def screen_lot(lot: AuctionLot) -> dict:
        selected: list[str] = []
        excluded: list[str] = []
        flags: list[str] = []
        location = " ".join((lot.address or "", str(lot.raw.get("region") or ""), lot.title or "")).lower()
        if "москва" in location:
            selected.append("Москва")
        kind_labels = {LotKind.KRT: "КРТ", LotKind.PROPERTY_COMPLEX: "имущественный комплекс", LotKind.UNFINISHED: "незавершённый объект", LotKind.LAND_SALE: "продажа земли", LotKind.LAND_LEASE: "аренда земли"}
        if lot.lot_kind in kind_labels:
            selected.append(kind_labels[lot.lot_kind])
        if lot.land_area_sqm is not None:
            if lot.land_area_sqm >= 10_000:
                selected.append(f"площадь {lot.land_area_sqm / 10_000:g} га")
                flags.append("large_site")
            else:
                selected.append(f"площадь {lot.land_area_sqm:g} м²")
        if lot.permitted_use:
            selected.append(lot.permitted_use)

        use = " ".join((lot.permitted_use or "", lot.title or "")).lower()
        explicit_test_lot = (
            bool(re.match(r"^\s*\[?\s*тест\s*\]?\b", lot.title or "", re.I))
            or "тестовый лот" in use
        )
        if explicit_test_lot:
            excluded.append("тестовая карточка ЭТП")
            flags.append("platform_test_lot")
        noise_markers = ("ижс", "индивидуальн", "личного подсобного", "садовод", "огород")
        if any(m in use for m in noise_markers):
            excluded.append("ИЖС или индивидуальное использование")
            flags.append("individual_housing")
        residential_house = any(m in use for m in ("жилой дом", "жилого дома", "жилым домом", "домовладение"))
        residential_unit = (
            "квартир" in use
            or (
                any(marker in use for marker in ("жилое помещение", "жилого помещения"))
                and not any(marker in use for marker in ("нежилое помещение", "нежилого помещения"))
            )
        )
        small = lot.land_area_sqm is not None and lot.land_area_sqm < 5_000
        if residential_house:
            flags.append("existing_residential_house")
        if small:
            # Сам по себе размер не исключает лот: в эталоне владельца есть
            # реальные сделки существенно меньше 5 000 м². Масштаб сравнивает
            # измеренный профиль, а здесь маленький участок лишь называется.
            flags.append("small_site")
        if residential_house and small:
            excluded.append("малый участок с жилым домом")
        if residential_unit and lot.lot_kind == LotKind.PROPERTY_COMPLEX:
            excluded.append("отдельная квартира, не объект девелопмента")
            flags.append("residential_unit")

        if explicit_test_lot:
            relevant = False
        elif lot.lot_kind == LotKind.KRT:
            relevant = True
        elif lot.lot_kind in {LotKind.PROPERTY_COMPLEX, LotKind.UNFINISHED}:
            relevant = not (residential_house and small) and not residential_unit
        else:
            relevant = lot.lot_kind in {LotKind.LAND_SALE, LotKind.LAND_LEASE} and not excluded
        lot.selection_reasons = selected
        lot.exclusion_reasons = excluded
        lot.relevance_flags = flags
        rating = "Высокая" if relevant and lot.lot_kind == LotKind.KRT else "Средняя" if relevant else "Шум"
        why_here = " · ".join(selected[:4])
        concerns = excluded or (["нужна проверка градостроительного потенциала"] if relevant else [])
        return {
            "development_relevant": relevant,
            "rating": rating,
            "selection_reasons": selected,
            "exclusion_reasons": excluded,
            "relevance_flags": flags,
            "why_here": why_here,
            "platon_explanation": {
                "rating": rating,
                "why_here": why_here,
                "concerns": concerns,
                "verify_before_calculation": ["официальные документы лота", "кадастр и градостроительные ограничения"],
                "grounding": "selection_reasons_and_official_lot_fields_only",
            },
        }
