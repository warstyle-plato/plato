from __future__ import annotations

import re

from auction_search.models import LotKind


_KRT_MARKERS = (
    "комплексн", "крт", "договор о комплексном развитии", "право на заключение договора",
)
_LEASE_MARKERS = ("аренда", "право аренды", "договор аренды")
_PROPERTY_MARKERS = ("имущественный комплекс", "зик", "здание и земельный участок")
_UNFINISHED_MARKERS = ("объект незавершенного строительства", "незавершенн")


def classify_lot(title: str, procedure_text: str = "", document_titles: list[str] | None = None) -> LotKind:
    """Classify the legal/economic nature of a lot before any financial modeling.

    This intentionally runs before cadastral enrichment. KRT terms override generic land wording.
    """
    haystack = " ".join([title or "", procedure_text or "", " ".join(document_titles or [])]).lower()
    compact = re.sub(r"\s+", " ", haystack)
    if any(marker in compact for marker in _KRT_MARKERS):
        return LotKind.KRT
    if any(marker in compact for marker in _UNFINISHED_MARKERS):
        return LotKind.UNFINISHED
    if any(marker in compact for marker in _PROPERTY_MARKERS):
        return LotKind.PROPERTY_COMPLEX
    if any(marker in compact for marker in _LEASE_MARKERS):
        return LotKind.LAND_LEASE
    if "земельн" in compact or "участ" in compact:
        return LotKind.LAND_SALE
    return LotKind.OTHER
