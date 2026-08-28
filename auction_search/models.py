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


class LotOrigin(str, Enum):
    """Кто продаёт. Не то же самое, что ЧТО продаётся.

    Городские торги и банкротные — разные рынки с разной механикой. У города
    цена не снижается; у банкротного лота публичное предложение идёт по
    графику, и цена ползёт от начальной к минимальной. Смешать их в одном
    списке значит сравнивать несравнимое: «дешевле» у банкротного лота часто
    значит «дошло до последнего шага», а не «выгодно».
    """
    CITY = "city"
    BANKRUPTCY = "bankruptcy"
    # Арест и исполнительное производство. Заведены отдельно не ради полноты
    # перечня, а потому что это единственное, что реестр владельца показывает
    # уверенно: из пятнадцати таких лотов с прошедшими торгами до сделки дошёл
    # один. Раньше они лежали в OTHER, то есть выглядели как «мы не знаем», —
    # а мы знаем.
    SEIZED = "seized"
    OTHER = "other"


# Что продаётся, крупными долями. Виды лотов подробнее (LotKind), но человеку с
# порога нужен ответ «земля или уже построенное»: под редевелопмент это разные
# сделки, разные сроки и разные риски.
LAND_KINDS = (LotKind.LAND_SALE, LotKind.LAND_LEASE, LotKind.KRT)
BUILDING_KINDS = (LotKind.PROPERTY_COMPLEX, LotKind.UNFINISHED)


def lot_subject(kind: "LotKind | str") -> str:
    """«land» / «building» / «other» по виду лота.

    Отдельного поля не заводим: оно было бы вторым источником правды о том же
    самом, и однажды разошлось бы с `lot_kind`.
    """
    value = kind.value if isinstance(kind, LotKind) else str(kind or "")
    if value in {item.value for item in LAND_KINDS}:
        return "land"
    if value in {item.value for item in BUILDING_KINDS}:
        return "building"
    return "other"


class SourceKind(str, Enum):
    ROSELTORG = "roseltorg"
    LOT_ONLINE = "lot_online"
    ETP_GPB = "etp_gpb"
    ETP_RF = "etp_rf"
    OTHER_ETP = "other_etp"
    TORGI_GOV = "torgi_gov"


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
class AuctionPricePeriod:
    """One official public-offer price period, in the platform's Moscow time."""

    starts_at: str
    application_deadline: str
    ends_at: str
    price_rub: float
    deposit_rub: Optional[float] = None
    change_rub: Optional[float] = None
    provenance: Optional[Provenance] = None


@dataclass
class KrtProgramItem:
    """One item of the official KRT development program.

    This describes what the KRT documents allow/require to be built. It is not
    automatically a cost: commercial area can generate revenue, while social or
    infrastructure items can become investor obligations depending on the contract.
    """

    category: str
    title: str
    area_sqm: Optional[float] = None
    quantity: Optional[float] = None
    unit: Optional[str] = None
    disposition: Optional[str] = None  # commercial / city_transfer / infrastructure / unknown
    source_text: Optional[str] = None
    provenance: Optional[Provenance] = None
    confidence: float = 1.0


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
    # public = fetched without credentials; authenticated = fetched using an
    # externally supplied service-account session; auth_required = platform
    # refused the public request. We never store credentials in this object.
    access_status: str = "unknown"
    auth_required: bool = False


@dataclass
class AuctionLot:
    source: AuctionSource
    lot_kind: LotKind
    title: str
    # Происхождение лота. Умолчание — «другое», то есть «не опознано».
    # Прежде здесь стояли городские торги: три наших источника заводились под
    # городское имущество, и другого значения быть не могло. Оказалось, могло —
    # РАД продаёт и то и другое, и лот с продавцом-банком приезжал в список
    # городским. Умолчание, которое УТВЕРЖДАЕТ, на экране неотличимо от
    # опознанного: неопознанное обязано выглядеть неопознанным.
    # Опознаёт `classifier.origin_from_evidence` — по продавцу и словам
    # процедуры, одним правилом на все источники.
    origin: LotOrigin = LotOrigin.OTHER
    address: Optional[str] = None
    cadastral_numbers: list[str] = field(default_factory=list)
    land_area_sqm: Optional[float] = None
    # Площадь здания — отдельным полем, а не в площади участка. У ГИС Торгов
    # структурирована площадь объекта («Общая площадь»), а метры участка часто
    # стоят только в тексте описания. Сложить их в одно поле значит подписать
    # два разных числа одним именем — потом никто не разберёт, что именно
    # сравнивается с ценой.
    building_area_sqm: Optional[float] = None
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
    price_schedule: list[AuctionPricePeriod] = field(default_factory=list)
    documents: list[AuctionDocument] = field(default_factory=list)
    krt_program: list[KrtProgramItem] = field(default_factory=list)
    obligations: list[KrtObligation] = field(default_factory=list)
    selection_reasons: list[str] = field(default_factory=list)
    exclusion_reasons: list[str] = field(default_factory=list)
    relevance_flags: list[str] = field(default_factory=list)
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
        value["origin"] = self.origin.value if isinstance(self.origin, LotOrigin) else str(self.origin)
        value["subject"] = lot_subject(self.lot_kind)
        value["source"]["platform"] = self.source.platform.value
        return value


def utc_now_iso() -> str:
    return datetime.utcnow().replace(microsecond=0).isoformat() + "Z"
