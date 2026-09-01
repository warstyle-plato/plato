from __future__ import annotations

import re
from typing import Optional


_CAD_RE = re.compile(r"\b\d{2}:\d{2}:\d{6,7}:\d+\b")
_MONEY_RE = re.compile(r"([\d\s\u00a0]+(?:[.,]\d+)?)\s*(?:₽|руб(?:\.|лей)?)", re.I)
_AREA_RE = re.compile(r"([\d\s\u00a0]+(?:[.,]\d+)?)\s*(?:кв\.?\s*м|м2|м²)", re.I)
# Гектары в извещениях города — обычная мера: «площадью 14,62 га». Пока их не
# читали, у площадки метров не было вовсе, а «метров нет» и «метров мало» —
# разные ответы: допуск подборки требует площадь, и лот выпадал молча.
_HECTARE_RE = re.compile(r"(?<![\d.,])(\d[\d\s\u00a0]*(?:[.,]\d+)?)\s*(?:га\b|гектар\w*)", re.I)

# Москва склоняется, и наш отбор об этом не знал. «города Москвы» в заголовке
# аукциона КРТ не проходило ни одну из проверок: `\bмосква\b` требует
# именительного падежа, а `город\s*москва` — пробела там, где стоит «города».
# Живой лот владельца (01.09.2026) — «...нежилой застройки города Москвы,
# площадью 14,62 га» — по этой причине выбрасывался как немосковский.
#
# Область вычитается ДО поиска города: «Московская область» содержит корень,
# но городом не является. Слово ищется целиком (`\b`), иначе Новомосковск
# станет Москвой.
_MOSCOW_OBLAST_RE = re.compile(r"московск\w*\s+обл\w*", re.I)
_MOSCOW_RE = re.compile(r"\bмоскв(?:а|ы|е|у|ой|ою)\b", re.I)


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


def parse_hectares_sqm(value: str | None) -> Optional[float]:
    """Площадь, названная в гектарах, — в квадратных метрах. Нет гектаров — None."""
    if not value:
        return None
    match = _HECTARE_RE.search(value)
    if not match:
        return None
    hectares = parse_decimal(match.group(1))
    return None if hectares is None else hectares * 10_000


def mentions_moscow(*values: str | None) -> bool:
    """Сказано ли здесь про Москву — в любом падеже и не про область.

    Объявлено один раз: тремя копиями в читателях площадок это правило
    расходилось молча, и две из трёх искали подстроку «москва», то есть
    «Москвы» и «Москве» не узнавали тоже.

    Какие поля сюда подать, решает читатель: на странице площадки в подвале
    стоит её собственный московский адрес, и вся страница целиком ответила бы
    «Москва» про любой лот.
    """
    text = " ".join(str(value or "") for value in values).lower()
    return bool(_MOSCOW_RE.search(_MOSCOW_OBLAST_RE.sub(" ", text)))


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
