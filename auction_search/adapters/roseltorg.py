from __future__ import annotations

from urllib.parse import urlparse

from auction_search.adapters.base import AuctionPlatformAdapter
from auction_search.models import AuctionLot


class RoseltorgAdapter(AuctionPlatformAdapter):
    """Roseltorg adapter boundary.

    We intentionally do not guess private/unstable endpoints. `fetch_lot` will be enabled
    once the official public lot-card/search request contract is captured in fixtures.
    """

    @property
    def platform_name(self) -> str:
        return "Roseltorg"

    def discover_moscow(self):
        return []

    def fetch_lot(self, lot_url: str) -> AuctionLot:
        host = urlparse(lot_url).hostname or ""
        if not (host.endswith("roseltorg.ru") or host.endswith("roseltorg.ru")):
            raise ValueError("RoseltorgAdapter accepts only official Roseltorg URLs")
        raise NotImplementedError("Pin Roseltorg public lot-card contract before enabling ingestion")
