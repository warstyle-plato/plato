from __future__ import annotations

from dataclasses import dataclass, field, asdict
from datetime import datetime
from enum import Enum
from typing import Any, Optional


class LotKind(str, Enum):
    LAND_SALE = "land_sale"
    LAND_LEASE = "land_lease"
    KRT = "krt"
    PROPERTY_COMPLEX = "property_complex"
    UNFINISHED = "unfinished"
    OTHER = "other"


class SourceKind(str, Enum):
    ROSELTORG = "roseltorg"
    LOT_ONLINE = "lot_online"
    OTHER_ETP = "other_etp"


@dataclass(frozen=True)
class AuctionSource:
    platform: SourceKind
    lot_url: str
    external_lot_id: str
    fetched_at: str
    source_name: str = ""


@dataclass(frozen=True)
class Provenance:
    source_url: str
    source_document: Optional[str] = None
    source_section: Optional[str] = None
    fetched_at: Optional[str] = None
    raw_value: Optional[str] = None


@dataclass
class KrtObligation:
    category: str
    title: str
    quantity: Optional[float] = None
    unit: Optional[str] = None
    due_date: Optional[str] = None
    executor: Optional[str] = None
    recipient: Optional[str] = None
    transfer_free_of_charge: Optional[bool] = None
    estimated_cost_rub: Optional[float] = None
    source_text: Optional[str] = None
    provenance: Optional[Provenance] = None
    confidence: float = 1.0


@dataclass
class AuctionDocument:
    title: str
    url: str
    document_type: str = "other"
    fetched_at: Optional[str] = None


@dataclass
class AuctionLot:
    source: AuctionSource
    lot_kind: LotKind
    title: str
    address: Optional[str] = None
    cadastral_numbers: list[str] = field(default_factory=list)
    land_area_sqm: Optional[float] = None
    permitted_use: Optional[str] = None
    seller: Optional[str] = None
    organizer: Optional[str] = None
    procedure_type: Optional[str] = None
    start_price_rub: Optional[float] = None
    current_price_rub: Optional[float] = None
    min_price_rub: Optional[float] = None
    bid_step_rub: Optional[float] = None
    deposit_rub: Optional[float] = None
    application_deadline: Optional[str] = None
    auction_date: Optional[str] = None
    status: Optional[str] = None
    documents: list[AuctionDocument] = field(default_factory=list)
    obligations: list[KrtObligation] = field(default_factory=list)
    provenance: dict[str, Provenance] = field(default_factory=dict)
    raw: dict[str, Any] = field(default_factory=dict, repr=False)

    @property
    def canonical_key(self) -> str:
        """Stable deduplication key inside DevelopAid.

        Prefer cadastral identity; fall back to platform + external lot id.
        """
        if self.cadastral_numbers:
            return "cad:" + ",".join(sorted(set(self.cadastral_numbers)))
        return f"src:{self.source.platform.value}:{self.source.external_lot_id}"

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["lot_kind"] = self.lot_kind.value
        value["source"]["platform"] = self.source.platform.value
        return value


def utc_now_iso() -> str:
    return datetime.utcnow().replace(microsecond=0).isoformat() + "Z"
