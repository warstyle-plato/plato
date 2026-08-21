from __future__ import annotations

import re
from typing import Iterable

from auction_search.models import KrtObligation, KrtProgramItem, Provenance


CATEGORY_PATTERNS: dict[str, tuple[str, ...]] = {
    "social": ("школ", "образователь", "доу", "детск", "поликлиник", "здравоохран", "спорт"),
    "transport": ("дорог", "улично-дорож", "проезд", "транспорт"),
    "engineering": ("инженер", "сет", "коммуникац", "теплоснаб", "водоснаб", "канализац", "электроснаб"),
    "demolition": ("снос", "демонтаж"),
    "resettlement": ("переселен", "изъят", "выкуп", "компенсац", "освобожд"),
    "planning": ("дпт", "проект планировки", "проект межевания"),
    "landscaping": ("благоустрой", "озелен"),
    "security": ("банковск гарант", "обеспечен исполн", "задат"),
    "payment": ("плат", "цена права", "арендн плат"),
    "land": ("земельн", "участ"),
    "deadline": ("срок", "этап", "ввод в эксплуатац"),
}

PROGRAM_PATTERNS: dict[str, tuple[str, ...]] = {
    "housing": ("жилой застрой", "жилых помещений", "жилого назначения", "жиль"),
    "office": ("офис", "деловой", "административно-делов"),
    "retail": ("торгов", "общественно-торгов", "ритейл"),
    "public_business": ("общественно-делов", "многофункциональн", "общественных центров"),
    "industrial": ("производствен", "промышлен"),
    "social": ("школ", "образователь", "доу", "детск", "поликлиник", "здравоохран", "спорт"),
    "parking": ("паркинг", "машино-мест", "гараж"),
    "transport": ("дорог", "улично-дорож", "проезд", "транспорт"),
    "engineering": ("инженер", "сет", "коммуникац"),
}

_QUANTITY_RE = re.compile(r"(?P<qty>\d[\d\s.,]*)\s*(?P<unit>мест|кв\.?\s*м|м2|м²|га|км|млн\.?\s*руб|руб)", re.I)
_AREA_RE = re.compile(r"(?P<qty>\d[\d\s.,]*)\s*(?:кв\.?\s*м|м2|м²)", re.I)
_DATE_RE = re.compile(r"\b(?:0?[1-9]|[12]\d|3[01])[./-](?:0?[1-9]|1[0-2])[./-](?:20\d{2})\b")
_OBLIGATION_MARKERS = (
    "обязан", "обязуется", "обеспечить", "осуществить", "выполнить", "выполняет",
    "разработать", "построить", "создать", "передать", "подлежит", "за счет инвестора",
    "за счёт инвестора", "лицо, заключившее договор", "победитель торгов",
)


def _number(raw: str | None) -> float | None:
    if not raw:
        return None
    cleaned = raw.replace(" ", "").replace("\xa0", "").replace(",", ".")
    try:
        return float(cleaned)
    except ValueError:
        return None


def classify_obligation(text: str) -> str:
    low = text.lower()
    for category, markers in CATEGORY_PATTERNS.items():
        if any(m in low for m in markers):
            return category
    return "other"


def classify_program_item(text: str) -> str:
    low = text.lower()
    for category, markers in PROGRAM_PATTERNS.items():
        if any(m in low for m in markers):
            return category
    return "other"


def extract_krt_program(
    paragraphs: Iterable[str],
    *,
    source_url: str,
    source_document: str,
    fetched_at: str | None = None,
) -> list[KrtProgramItem]:
    """Extract the official development program without treating it as investor CAPEX.

    Program items answer "what is in the KRT perimeter". Contract obligations answer
    "what the investor must do/pay/transfer". They are intentionally separate.
    """
    result: list[KrtProgramItem] = []
    seen: set[str] = set()
    for paragraph in paragraphs:
        text = " ".join((paragraph or "").split())
        if len(text) < 12:
            continue
        category = classify_program_item(text)
        if category == "other":
            continue
        # Require a quantitative clue for a program item. This prevents every legal
        # mention of a school/road from becoming a duplicate program line.
        qmatch = _QUANTITY_RE.search(text)
        if not qmatch:
            continue
        key = text.lower()
        if key in seen:
            continue
        seen.add(key)
        qty = _number(qmatch.group("qty"))
        unit = qmatch.group("unit")
        area_match = _AREA_RE.search(text)
        area = _number(area_match.group("qty")) if area_match else None
        low = text.lower()
        disposition = "city_transfer" if ("передат" in low and ("москв" in low or "город" in low)) else "unknown"
        result.append(
            KrtProgramItem(
                category=category,
                title=text[:240],
                area_sqm=area,
                quantity=qty,
                unit=unit,
                disposition=disposition,
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


def extract_krt_obligations(
    paragraphs: Iterable[str],
    *,
    source_url: str,
    source_document: str,
    fetched_at: str | None = None,
) -> list[KrtObligation]:
    """Rule-based first pass over official KRT terms.

    It never estimates cost. It also requires obligation language, so a mere mention
    of a school, road or deadline in the development program is not silently converted
    into investor CAPEX.
    """
    result: list[KrtObligation] = []
    seen: set[str] = set()
    for paragraph in paragraphs:
        text = " ".join((paragraph or "").split())
        if len(text) < 12:
            continue
        low = text.lower()
        category = classify_obligation(text)
        if category == "other":
            continue
        has_obligation = any(marker in low for marker in _OBLIGATION_MARKERS)
        if not has_obligation and category not in {"payment", "security"}:
            continue
        key = text.lower()
        if key in seen:
            continue
        seen.add(key)
        qty = None
        unit = None
        match = _QUANTITY_RE.search(text)
        if match:
            qty = _number(match.group("qty"))
            unit = match.group("unit")
        transfer = "безвозмезд" in low or ("передат" in low and "безвозмезд" in low)
        recipient = "город Москва" if ("передат" in low and ("москв" in low or "городу" in low)) else None
        executor = "инвестор" if ("инвестор" in low or "лицо, заключившее договор" in low or "победитель торгов" in low) else None
        date_match = _DATE_RE.search(text)
        result.append(
            KrtObligation(
                category=category,
                title=text[:240],
                quantity=qty,
                unit=unit,
                due_date=date_match.group(0) if date_match else None,
                executor=executor,
                recipient=recipient,
                transfer_free_of_charge=True if transfer else None,
                source_text=text,
                provenance=Provenance(
                    source_url=source_url,
                    source_document=source_document,
                    fetched_at=fetched_at,
                    raw_value=text,
                ),
                confidence=0.7,
            )
        )
    return result


def obligation_cost_items(obligations: Iterable[KrtObligation]) -> list[dict]:
    """Convert explicit investor obligations into candidate model cost lines.

    Estimated cost remains None until DevelopAid cost norms price the obligation.
    Security/deadline lines stay outside CAPEX; they are model constraints.
    """
    out: list[dict] = []
    for item in obligations:
        if item.category in {"social", "transport", "engineering", "demolition", "resettlement", "planning", "landscaping", "payment", "land"}:
            out.append({
                "category": item.category,
                "name": item.title,
                "quantity": item.quantity,
                "unit": item.unit,
                "estimated_cost_rub": item.estimated_cost_rub,
                "transfer_free_of_charge": item.transfer_free_of_charge,
                "recipient": item.recipient,
                "due_date": item.due_date,
                "source": item.provenance.source_document if item.provenance else None,
            })
    return out
