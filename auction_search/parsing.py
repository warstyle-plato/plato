from __future__ import annotations

import re
from typing import Optional


_CAD_RE = re.compile(r"\b\d{2}:\d{2}:\d{6,7}:\d+\b")
_MONEY_RE = re.compile(r"([\d\s\u00a0]+(?:[.,]\d+)?)\s*(?:₽|руб(?:\.|лей)?)", re.I)
_AREA_RE = re.compile(r"([\d\s\u00a0]+(?:[.,]\d+)?)\s*(?:кв\.?\s*м|м2|м²)", re.I)


def normalize_space(value: str | None) -> str:
    return " ".join((value or "").replace("\xa0", " ").split())


def parse_decimal(value: str | None) -> Optional[float]:
    if not value:
        return None
    cleaned = normalize_space(value).replace(" ", "").replace(",", ".")
    cleaned = re.sub(r"[^0-9.\-]", "", cleaned)
    try:
        return float(cleaned)
    except (TypeError, ValueError):
        return None


def parse_money(value: str | None) -> Optional[float]:
    if not value:
        return None
    match = _MONEY_RE.search(value)
    return parse_decimal(match.group(1)) if match else parse_decimal(value)


def parse_area_sqm(value: str | None) -> Optional[float]:
    if not value:
        return None
    match = _AREA_RE.search(value)
    return parse_decimal(match.group(1)) if match else parse_decimal(value)


def cadastral_numbers(value: str | None) -> list[str]:
    if not value:
        return []
    return sorted(set(_CAD_RE.findall(value)))


def value_after_label(text: str, label: str, *, stop_labels: tuple[str, ...] = ()) -> Optional[str]:
    """Extract text following a visible platform label from normalized page text."""
    normalized = normalize_space(text)
    low = normalized.lower()
    marker = label.lower()
    idx = low.find(marker)
    if idx < 0:
        return None
    start = idx + len(marker)
    end = len(normalized)
    tail_low = low[start:]
    for stop in stop_labels:
        stop_idx = tail_low.find(stop.lower())
        if stop_idx >= 0:
            end = min(end, start + stop_idx)
    return normalized[start:end].strip(" :-") or None
