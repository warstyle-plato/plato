from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Iterable

from auction_search.models import AuctionLot


class AuctionPlatformAdapter(ABC):
    """Contract for primary-source electronic trading platforms only."""

    @abstractmethod
    def discover_moscow(self) -> Iterable[AuctionLot]:
        """Yield Moscow lots currently discoverable on the platform."""

    @abstractmethod
    def fetch_lot(self, lot_url: str) -> AuctionLot:
        """Fetch and normalize one lot from its official platform URL."""

    @property
    @abstractmethod
    def platform_name(self) -> str:
        raise NotImplementedError
