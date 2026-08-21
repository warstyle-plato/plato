from __future__ import annotations

import re

from auction_search.models import LotKind


# Russian auction wording is highly inflected. Match stems, not a handful of
# nominative/genitive phrases: "о комплексном развитии территории" and
# "договора аренды" are the normal forms on ETP cards.
_KRT_RE = re.compile(r"(?:\bкрт\b|комплексн\w*\s+развити\w*\s+территор\w*)", re.I)
_LEASE_RE = re.compile(r"аренд\w*", re.I)
_PROPERTY_RE = re.compile(r"(?:имущественн\w*\s+комплекс\w*|\bзик\b|здани\w*\s+и\s+земельн\w*\s+участ\w*)", re.I)
_UNFINISHED_RE = re.compile(r"(?:объект\w*\s+незавершенн\w*\s+строительств\w*|незавершенн\w*)", re.I)
_LAND_RE = re.compile(r"(?:земельн\w*|участ\w*)", re.I)


def classify_lot(title: str, procedure_text: str = "", document_titles: list[str] | None = None) -> LotKind:
    """Classify the legal/economic nature of a lot before financial modeling.

    Priority is legal structure, not the presence of the word "land". Thus a
    KRT right containing cadastral parcels remains KRT, and a lease remains a
    lease even when the title says "земельный участок".
    """
    haystack = " ".join([title or "", procedure_text or "", " ".join(document_titles or [])]).lower()
    compact = re.sub(r"\s+", " ", haystack)
    if _KRT_RE.search(compact):
        return LotKind.KRT
    if _UNFINISHED_RE.search(compact):
        return LotKind.UNFINISHED
    if _PROPERTY_RE.search(compact):
        return LotKind.PROPERTY_COMPLEX
    if _LEASE_RE.search(compact):
        return LotKind.LAND_LEASE
    if _LAND_RE.search(compact):
        return LotKind.LAND_SALE
    return LotKind.OTHER
