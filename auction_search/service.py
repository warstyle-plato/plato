from __future__ import annotations

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
        if lot.lot_kind == LotKind.KRT:
            return True
        if lot.lot_kind in {LotKind.PROPERTY_COMPLEX, LotKind.UNFINISHED}:
            return True
        use = (lot.permitted_use or "").lower()
        noise_markers = ("ижс", "индивидуальн", "личного подсобного", "садовод", "огород")
        if any(m in use for m in noise_markers):
            return False
        # Do not require 77:* cadastral prefix: New Moscow contains legacy 50:* parcels.
        if lot.land_area_sqm is not None and lot.land_area_sqm < 5_000:
            return False
        return lot.lot_kind in {LotKind.LAND_SALE, LotKind.LAND_LEASE}
