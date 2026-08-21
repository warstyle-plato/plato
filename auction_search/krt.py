from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable

from auction_search.models import KrtObligation, Provenance


CATEGORY_PATTERNS: dict[str, tuple[str, ...]] = {
    "social": ("школ", "образователь", "доу", "детск", "поликлиник", "здравоохран", "спорт"),
    "transport": ("дорог", "улично-дорож", "проезд", "транспорт", "уДС".lower()),
    "engineering": ("инженер", "сет", "коммуникац", "теплоснаб", "водоснаб", "канализац", "электроснаб"),
    "demolition": ("снос", "демонтаж"),
    "resettlement": ("переселен", "изъят", "выкуп", "компенсац", "освобожд"),
    "land": ("земельн", "участ"),
    "planning": ("дпт", "проект планировки", "проект межевания"),
    "landscaping": ("благоустрой", "озелен"),
    "transfer_to_city": ("передач", "безвозмезд", "собственност москв", "городу москв"),
    "security": ("банковск гарант", "обеспечен исполн", "задат"),
    "payment": ("плат", "цена права", "арендн плат"),
    "deadline": ("срок", "этап", "ввод в эксплуатац"),
}

_QUANTITY_RE = re.compile(r"(?P<qty>\d[\d\s.,]*)\s*(?P<unit>мест|кв\.?\s*м|м2|м²|га|км|млн\.?\s*руб|руб)", re.I)


def classify_obligation(text: str) -> str:
    low = text.lower()
    for category, markers in CATEGORY_PATTERNS.items():
        if any(m in low for m in markers):
            return category
    return "other"


def extract_krt_obligations(
    paragraphs: Iterable[str],
    *,
    source_url: str,
    source_document: str,
    fetched_at: str | None = None,
) -> list[KrtObligation]:
    """Rule-based first pass over text extracted from official KRT documents.

    It does not invent obligations or costs. Each result retains exact source text and provenance.
    A later semantic extractor may enrich fields, but source_text stays authoritative.
    """
    result: list[KrtObligation] = []
    seen: set[str] = set()
    for paragraph in paragraphs:
        text = " ".join((paragraph or "").split())
        if len(text) < 12:
            continue
        category = classify_obligation(text)
        if category == "other":
            continue
        key = text.lower()
        if key in seen:
            continue
        seen.add(key)
        qty = None
        unit = None
        match = _QUANTITY_RE.search(text)
        if match:
            raw_qty = match.group("qty").replace(" ", "").replace(",", ".")
            try:
                qty = float(raw_qty)
            except ValueError:
                qty = None
            unit = match.group("unit")
        result.append(
            KrtObligation(
                category=category,
                title=text[:240],
                quantity=qty,
                unit=unit,
                source_text=text,
                provenance=Provenance(
                    source_url=source_url,
                    source_document=source_document,
                    fetched_at=fetched_at,
                    raw_value=text,
                ),
                confidence=0.65,
            )
        )
    return result


def obligation_cost_items(obligations: Iterable[KrtObligation]) -> list[dict]:
    """Convert only explicit/estimated investor obligations into model cost candidates.

    Estimated cost remains None until DevelopAid cost norms price the physical obligation.
    """
    out: list[dict] = []
    for item in obligations:
        if item.category in {"social", "transport", "engineering", "demolition", "resettlement", "planning", "landscaping", "transfer_to_city", "payment"}:
            out.append({
                "category": item.category,
                "name": item.title,
                "quantity": item.quantity,
                "unit": item.unit,
                "estimated_cost_rub": item.estimated_cost_rub,
                "source": item.provenance.source_document if item.provenance else None,
            })
    return out
