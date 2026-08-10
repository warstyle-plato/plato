"""Класс проекта и его район — признаки сопоставимости.

География и доказанная цена отвечают на вопрос «это правда», но не на вопрос
«это сравнимо». Радиус — чисто геометрический фильтр, и на Саввинской
набережной он честно приводил Дом Дау: 2,2 км по прямой через реку. Небоскрёб в
деловом квартале и клубные дома Хамовников — разный продукт, разный покупатель,
разное ценообразование.

Класс сам по себе такой проект не отсекает: Дом Дау тоже элитный. Отсекает пара
«класс + район», поэтому оба признака живут здесь вместе.

«Делюкс» и «элитный» — один уровень. Это не вкус: в контрольном наборе
Саввинская 27 продаётся как делюкс, Хамовники 12 — как элитный, и они прямые
конкуренты. Разведёшь их по уровням — потеряешь обязательный аналог.
"""

from __future__ import annotations

import re


ELITE = "элитный"
PREMIUM = "премиум"
BUSINESS = "бизнес"
COMFORT = "комфорт"
ECONOMY = "эконом"

_PATTERNS = (
    (ELITE, re.compile(r"\b(?:элитн[а-я]*|делюкс|de\s?luxe|luxury|премиальн[а-я]*\s+клубн[а-я]*)\b", re.I)),
    (PREMIUM, re.compile(r"\b(?:премиум[- ]?класс[а-я]*|премиум|premium)\b", re.I)),
    (BUSINESS, re.compile(r"\b(?:бизнес[- ]класс[а-я]*|business\s+class)\b", re.I)),
    (COMFORT, re.compile(r"\b(?:комфорт[- ]?класс[а-я]*|комфорт\+?)\b", re.I)),
    (ECONOMY, re.compile(r"\b(?:эконом[- ]?класс[а-я]*|стандарт[- ]?класс[а-я]*)\b", re.I)),
)

# «Премиальный» без слова «класс» — маркетинговое прилагательное, его лепят на
# что угодно. Как самостоятельный признак уровня оно не годится.
_WEAK = re.compile(r"\bпремиальн[а-я]*\b", re.I)


def detect_segment(text: str) -> str | None:
    """Класс, если он назван прямо. Догадок здесь нет."""
    value = str(text or "")
    for segment, pattern in _PATTERNS:
        if pattern.search(value):
            return segment
    return None


def segment_votes(texts) -> dict[str, int]:
    votes: dict[str, int] = {}
    for text in texts:
        segment = detect_segment(text)
        if segment:
            votes[segment] = votes.get(segment, 0) + 1
    return votes


def dominant_segment(votes: dict[str, int]) -> str | None:
    """Самый частый класс; при равенстве — верхний уровень.

    Маркетинг склонен завышать, поэтому решает частота, а не максимум. Равенство
    разрешается в пользу верхнего: пропустить сильного конкурента дороже, чем
    лишний раз показать его.
    """
    if not votes:
        return None
    order = [ELITE, PREMIUM, BUSINESS, COMFORT, ECONOMY]
    return max(votes.items(), key=lambda item: (item[1], -order.index(item[0])))[0]


_DISTRICT_RE = re.compile(r"(?:район\s+([А-ЯЁA-Z][А-Яа-яЁё\- ]{2,40})|([А-ЯЁA-Z][А-Яа-яЁё\- ]{2,40})\s+район)")


def detect_district(value: str) -> str | None:
    """Административный район из строки геокодера.

    Nominatim пишет его в display_name («район Хамовники»), Яндекс — не всегда.
    Отсутствие района не ошибка: тогда по району просто не фильтруем.
    """
    match = _DISTRICT_RE.search(str(value or ""))
    if not match:
        return None
    district = (match.group(1) or match.group(2) or "").strip(" -")
    district = re.sub(
        r"^(?:внутригородская\s+территория|муниципальный\s+округ)\s+", "", district, flags=re.I
    )
    district = " ".join(district.split())
    return district or None


def districts_match(left: str | None, right: str | None) -> bool:
    """Район сравним, только когда известен у обоих."""
    if not left or not right:
        return True
    return _fold(left) == _fold(right)


def _fold(value: str) -> str:
    return re.sub(r"[^а-яa-z]+", "", str(value or "").lower().replace("ё", "е"))
