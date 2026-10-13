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


# Уровни по возрастанию доступности. Соседние считаются сопоставимыми: элитный и
# премиум в одном районе конкурируют за одного покупателя, а бизнес-класс — уже
# нет. Решение владельца от 10.08.2026 по живому случаю: Savvin River Residence
# определился как премиум в 748 метрах при ориентире «элитный» и вылетал из
# выборки, будучи прямым соседом.
_LADDER = (ELITE, PREMIUM, BUSINESS, COMFORT, ECONOMY)

# Метка класса приходит из двух разных миров. Со страницы — прозой, и её
# разбирает `detect_segment`, нарочно строгий: голое «бизнес» в тексте значит
# что угодно. Из «Пульса» — значением фильтра: «Бизнес», «Элит/De Luxe»,
# «Стандарт/Эконом». Это перечисление, а не проза, и читать его надо картой.
#
# Пока карты не было, лестница получала метку как есть, `_LADDER.index("Бизнес")`
# бросал ValueError, и вызывающий код читал отказ как «классы несопоставимы».
# Правило о соседнем уровне при этом молчало везде, где метки берутся из
# «Пульса»: у Кутузов Сити (Бизнес) из выборки выпадал Родина Парк — премиум в
# 690 метрах, в том же Можайском районе, по 780 тыс ₽/м² против его 708 тыс.
# Выпадал не по решению, а по регистру первой буквы, и отчёт этого не показывал.
_LABELS = {
    "эконом": ECONOMY,
    "стандарт": ECONOMY,
    "стандартэконом": ECONOMY,
    "экономкласс": ECONOMY,
    "комфорт": COMFORT,
    "комфортплюс": COMFORT,
    "комфорткласс": COMFORT,
    "бизнес": BUSINESS,
    "бизнескласс": BUSINESS,
    "премиум": PREMIUM,
    "премиумкласс": PREMIUM,
    "элит": ELITE,
    "элитный": ELITE,
    "элитdeluxe": ELITE,
    "deluxe": ELITE,
    "делюкс": ELITE,
}


def normalize_segment(value: str | None) -> str | None:
    """Привести метку класса к уровню лестницы.

    Сначала точная карта меток, потом разбор прозы. Не опознали — None, а не
    догадка: неизвестный уровень должен вести к «сравнить не с чем», а не к
    случайной ступени.
    """
    if not value:
        return None
    known = _LABELS.get(_fold(value))
    if known:
        return known
    return detect_segment(value)


def segments_comparable(left: str | None, right: str | None) -> bool:
    """Сопоставимы ли классы вообще: тот же уровень или соседний.

    Берётся ли соседний на деле, решает `class_scope`: только при нехватке
    своего.
    """
    return class_step(left, right) is not None


# Соседний уровень — только при нехватке своего (решение владельца 13.10.2026,
# меняет решение 10.08). Пока соседний класс входил в выборку всегда,
# «Стандарт» в Мытищах собирал дорогой «Комфорт» и выходил дороже «Бизнеса»,
# а «Комфорт» и «Бизнес» — одну и ту же выборку. Порог — тот же, что у
# медианы ориентира: меньше трёх наблюдений — не медиана.
OWN_CLASS_ENOUGH = 3

SCOPE_SAME = "same"
SCOPE_ADJACENT = "adjacent"


def class_step(left: str | None, right: str | None) -> int | None:
    """Расстояние между уровнями: 0 — тот же, 1 — соседний; иначе `None`."""
    if not left or not right:
        return None
    if left == right:
        return 0
    first, second = normalize_segment(left), normalize_segment(right)
    if not first or not second:
        return None
    step = abs(_LADDER.index(first) - _LADDER.index(second))
    return step if step <= 1 else None


def class_scope(own_count: int) -> str:
    """Брать ли соседний уровень: только когда своих меньше `OWN_CLASS_ENOUGH`.

    Один владелец правила для всех читателей — ориентира цены, отчёта и
    отбора аналогов. Что считать «своими» (с ценой, с известным классом),
    решает читатель; порог и порядок — здесь.
    """
    return SCOPE_SAME if own_count >= OWN_CLASS_ENOUGH else SCOPE_ADJACENT


def in_class_scope(reference: str | None, other: str | None, scope: str) -> bool:
    """Входит ли класс `other` в выборку класса `reference` при этом охвате."""
    step = class_step(reference, other)
    if step is None:
        return False
    return step == 0 or scope == SCOPE_ADJACENT


def districts_match(left: str | None, right: str | None) -> bool:
    """Район сравним, только когда известен у обоих."""
    if not left or not right:
        return True
    return _fold(left) == _fold(right)


def _fold(value: str) -> str:
    return re.sub(r"[^а-яa-z]+", "", str(value or "").lower().replace("ё", "е"))


class SegmentResolver:
    """Дознание о классе для проектов, у которых его никто не назвал.

    На живом стенде «Японский дом» в 630 метрах и «Fusion Park» в километре
    вылетели из выборки со статусом «класс не определён». Это не повод ослаблять
    отбор: класс у них есть, просто его не было в тех сниппетах, которые пришли
    с каталожных запросов. Один целевой запрос на проект возвращает их обратно.

    Принимается только документ, доказанно говорящий об этом проекте, — то же
    правило, что и для адреса. Иначе класс соседа станет твоим.
    """

    def __init__(self, search, *, locality: str, budget: int = 12):
        self.search = search
        self.locality = locality
        self._budget = max(int(budget), 0)

    def resolve(self, entity) -> str | None:
        from .http import RemoteServiceError
        from .normalize import cut_at_separator, labels_match, search_name

        name = search_name(entity.canonical_name)
        if not name or self._budget <= 0:
            return None
        self._budget -= 1
        try:
            docs = self.search.search(
                f"ЖК {name} {self.locality} класс жилья элитный премиум бизнес комфорт",
                groups_on_page=10,
            )
        except RemoteServiceError:
            return None

        names = [entity.canonical_name, *entity.aliases]
        texts = []
        for doc in docs:
            title = cut_at_separator(doc.title)
            if not title or not labels_match(title, names):
                continue
            texts.append(" ".join(part for part in (doc.title, doc.snippet) if part))
        return dominant_segment(segment_votes(texts))
