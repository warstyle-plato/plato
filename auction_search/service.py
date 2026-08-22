from __future__ import annotations

import re
from collections import OrderedDict
from datetime import date
from typing import Iterable

from auction_search.adapters.base import AuctionPlatformAdapter
from auction_search.models import AuctionLot, LotKind


class AuctionSearchService:
    """Primary-source-only auction orchestration.

    Adapters must represent the official ETP on which the procedure is conducted.
    Aggregators are deliberately unsupported.
    """

    def __init__(self, adapters: Iterable[AuctionPlatformAdapter]):
        self.adapters = list(adapters)

    def discover_moscow(self, *, include_noise: bool = False) -> list[AuctionLot]:
        lots: list[AuctionLot] = []
        for adapter in self.adapters:
            lots.extend(adapter.discover_moscow())
        lots = self._deduplicate(lots)
        for lot in lots:
            self.screen_lot(lot)
        if include_noise:
            return lots
        return [lot for lot in lots if self.is_development_relevant(lot)]

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
        small = lot.land_area_sqm is not None and lot.land_area_sqm < 5_000
        if residential_house:
            flags.append("existing_residential_house")
        if small:
            excluded.append("участок меньше 5 000 м²")
            flags.append("small_site")
        if residential_house and small:
            excluded.append("малый участок с жилым домом")

        if explicit_test_lot:
            relevant = False
        elif lot.lot_kind == LotKind.KRT:
            relevant = True
        elif lot.lot_kind in {LotKind.PROPERTY_COMPLEX, LotKind.UNFINISHED}:
            relevant = not (residential_house and small)
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
