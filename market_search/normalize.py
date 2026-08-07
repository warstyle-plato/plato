"""Название проекта: очистка, канонический ключ, сравнение.

Отдельный модуль, потому что до v6 нормализация была размазана по трём файлам и в
каждом своя. Из-за этого один и тот же ЖК жил под несколькими ключами: латиница и
кириллица не сходились, а маркетинговый хвост («- купить квартиру») входил в ключ и
делал из одной страницы две сущности.
"""

from __future__ import annotations

import html
import re
from difflib import SequenceMatcher


_TRANSLIT = {
    "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ё": "e",
    "ж": "zh", "з": "z", "и": "i", "й": "i", "к": "k", "л": "l", "м": "m",
    "н": "n", "о": "o", "п": "p", "р": "r", "с": "s", "т": "t", "у": "u",
    "ф": "f", "х": "h", "ц": "c", "ч": "ch", "ш": "sh", "щ": "sh", "ъ": "",
    "ы": "y", "ь": "", "э": "e", "ю": "yu", "я": "ya",
}

# Голый тип объекта, не несущий бренда. Срезается и в показе, и в ключе.
_BARE_TYPE_PREFIX_RE = re.compile(r"^(?:жк|жилой\s+комплекс|residential\s+complex)\s+", flags=re.I)

# Родовая часть маркетингового названия. В показе остаётся («Клубный квартал
# Фрунзенский» — так проект и продаётся), в ключе снимается, иначе один проект
# живёт как «Фрунзенский» и как «Клубный квартал Фрунзенский».
_TYPE_PREFIX_RE = re.compile(
    r"^(?:жк|жилой\s+комплекс|жилой\s+квартал|клубный\s+дом|клубный\s+квартал|"
    r"клубный\s+городок|квартал|апарт[-\s]?комплекс|мфк|residential\s+complex)\s+",
    flags=re.I,
)

# Номер очереди пишут и римскими, и арабскими: «ДОМ XXII» = «Дом 22»,
# «Хамовники 12» = «Хамовники XII». Список закрытый: свободный разбор римских
# чисел съел бы латинские бренды вроде MIX или DIV.
_ROMAN_PHASE = {
    "i": 1, "ii": 2, "iii": 3, "iv": 4, "v": 5, "vi": 6, "vii": 7, "viii": 8,
    "ix": 9, "x": 10, "xi": 11, "xii": 12, "xiii": 13, "xiv": 14, "xv": 15,
    "xx": 20, "xxi": 21, "xxii": 22, "xxiii": 23, "xxiv": 24, "xxv": 25,
}

# Хвосты, которые агрегаторы приклеивают к названию в <title>. Срезаются
# итеративно с конца, иначе «ЖК Cult (Культ) - купить квартиру, цены» становится
# самостоятельной сущностью рядом с «Cult».
_TAIL_PHRASES = (
    "купить квартиру", "купить квартиры", "купить апартаменты", "купить",
    "цены и планировки", "цены от застройщика", "цены", "цена",
    "официальный сайт застройщика", "официальный сайт", "оф сайт",
    "от застройщика", "застройщик", "застройщика",
    "планировки", "отзывы", "отзыв", "фото", "на карте", "ход строительства",
    "новостройка", "новостройки", "квартиры", "квартира", "апартаменты",
    "ипотека", "акции", "скидки", "каталог", "подборка", "обзор",
    "в москве", "москва", "москве", "москвы",
    "в московской области", "московская область",
    "цианом", "циан", "домклик", "яндекс недвижимость", "новострой ру",
)

_STOPWORDS = frozenset(
    """
    рейтинг рейтинги топ обзор обзоры статья статьи новость новости каталог
    каталоги подборка подборки отзыв отзывы офис офиса офисы агентство агентства
    купить продажа продать продается продаётся снять аренда арендовать скидка
    скидки ипотека ипотеку акция акции консультация консультации звонить звоните
    телефон телефоны почта email контакты цены цена стоимость планировки
    застройщик застройщика застройщики застройщиков девелоперов риелтор риэлтор
    дубай дубая дубае эмираты оаэ турция таиланд бали сочи анапа краснодар
    хабаровск владивосток казань екатеринбург новосибирск
    недвижимость недвижимости лучших лучшие сравнение почему зачем какие
    вторичка вторичный вторичное посуточно посуточная бизнес-центр бц
    """.split()
)

# Стоп-слова ловят точную форму, а русский язык склоняет: «Хабаровск» в списке
# есть, а «Хабаровска» уже нет. Поэтому рядом живут префиксы.
_STOP_PREFIXES = (
    "новостройк", "рейтинг", "застройщик", "девелопер", "каталог", "подборк",
    "обзор", "отзыв", "вторичк", "ипотек", "недвижимост", "агентств",
    "дуба", "хабаровск", "владивосток", "краснодар", "екатеринбург",
    "новосибирск", "казан", "сочи",
)

_PREPOSITIONS = frozenset(
    "в во на от до для по с со из у к ко при за под над о об про и а но или".split()
)

_SEPARATOR_RE = re.compile(r"\s+[—–|]\s+|\s+[-−]\s+|\s*[»«]\s*\|")
_QUOTED_RE = re.compile(r"[«\"'“„]([^«»\"'“”„\n]{2,60})[»\"'”“]")


def clean_display_name(value: str) -> str:
    """Читаемое имя без кавычек, голого «ЖК» и хвостовой пунктуации.

    Скобки не трогаются: «Сидней Сити (Sidney City)» — законная форма вывески, а
    односторонняя обрезка скобки прежде превращала обрезанный захват
    («Cult (Культ») в отдельную сущность рядом с целой.
    """
    text = html.unescape(str(value or ""))
    text = re.sub(r"\s+", " ", text).strip(" \t\r\n«»\"'“”„")
    text = _BARE_TYPE_PREFIX_RE.sub("", text)
    return text.strip(" ,.;:—–-«»\"'“”„")


def cut_at_separator(value: str) -> str:
    """Оставить часть заголовка до первого разделителя.

    ASCII-дефис здесь обязателен: агрегаторы пишут «ЖК Cult (Культ) - купить
    квартиру», а прежний набор терминаторов знал только длинное тире, поэтому
    маркетинговый хвост приклеивался к имени.
    """
    text = " ".join(str(value or "").split())
    return _SEPARATOR_RE.split(text, maxsplit=1)[0].strip()


def strip_marketing_tail(value: str) -> str:
    text = clean_display_name(value)
    changed = True
    while changed and text:
        changed = False
        low = text.lower()
        for phrase in _TAIL_PHRASES:
            if low.endswith(" " + phrase) or low == phrase:
                text = text[: len(text) - len(phrase)].strip(" ,.;:—–-")
                changed = True
                break
        if not changed:
            trimmed = re.sub(r"[\s,;:—–-]+$", "", text)
            if trimmed != text:
                text = trimmed
                changed = True
    return text.strip(" ,.;:—–-")


def transliterate(value: str) -> str:
    out = []
    for char in str(value or "").lower():
        out.append(_TRANSLIT.get(char, char))
    return "".join(out)


def _fold(value: str) -> str:
    """Свести латиницу и транслит к одной форме.

    «Savvin River Residence» и «Саввин Ривер Резиденс» — одна вывеска, набранная
    в двух алфавитах. Без свёртки они дают разные ключи и превращаются в дубли.
    """
    folded = transliterate(value)
    folded = re.sub(r"[^a-z0-9]+", "", folded)
    folded = re.sub(r"(.)\1+", r"\1", folded)
    folded = folded.replace("ck", "k").replace("ph", "f").replace("z", "s")
    folded = re.sub(r"(?<=.)e$", "", folded)
    return folded


def _normalize_phase_numeral(value: str) -> str:
    tokens = str(value or "").split()
    if len(tokens) < 2:
        return value
    last = tokens[-1].strip(".,").lower()
    phase = _ROMAN_PHASE.get(last)
    if phase is None:
        return value
    return " ".join(tokens[:-1] + [str(phase)])


def canonical_key(value: str) -> str:
    """Ключ сущности: без типа объекта, без маркетингового хвоста, без алфавита."""
    name = _TYPE_PREFIX_RE.sub("", strip_marketing_tail(value)).strip()
    return _fold(_normalize_phase_numeral(name))


SAME_PROJECT_SIMILARITY = 0.92


def same_project(left: str, right: str) -> bool:
    """Одно ли это название проекта.

    Единственное определение тождества по имени на весь модуль: им пользуются и
    разрешение сущностей, и приёмка. Пока правило было в двух местах, приёмка
    считала «Savvin River Residence» и «Саввин Ривер Резиденс» разными и молча
    пропускала тот самый дубль, ради которого её и писали.
    """
    if not left or not right:
        return False
    if phase_number(left) != phase_number(right):
        return False
    return name_similarity(left, right) >= SAME_PROJECT_SIMILARITY


def phase_number(value: str) -> int | None:
    """Номер очереди, если он есть.

    Нужен там, где имена сравниваются на похожесть: «Петровский парк» и
    «Петровский парк II» отличаются на два символа и склеились бы в один
    аналог, хотя это разные проекты — активная первичка и старый комплекс.
    """
    name = _TYPE_PREFIX_RE.sub("", strip_marketing_tail(value)).strip()
    tokens = _normalize_phase_numeral(name).split()
    if len(tokens) < 2:
        return None
    last = tokens[-1].strip(".,")
    return int(last) if last.isdigit() else None


def name_tokens(value: str) -> list[str]:
    return re.findall(r"[a-zа-яё0-9]+", str(value or "").lower().replace("ё", "е"))


def name_similarity(left: str, right: str) -> float:
    a, b = canonical_key(left), canonical_key(right)
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    return SequenceMatcher(None, a, b).ratio()


def quoted_names(text: str) -> list[str]:
    """Названия в кавычках. Только они пригодны для извлечения из свободной прозы."""
    return [match.group(1).strip() for match in _QUOTED_RE.finditer(str(text or ""))]


def looks_like_project_name(value: str) -> bool:
    """Грамматика названия ЖК.

    Проверки идут не «на всякий случай»: каждая закрывает свой класс мусора,
    пойманный на живом preview — обрывок прозы через точку, редакционный
    заголовок, голый адрес, площадь в метрах.
    """
    name = strip_marketing_tail(value)
    if not name:
        return False
    if not 3 <= len(name) <= 60:
        return False

    low = name.lower().replace("ё", "е")

    # Обрывок прозы: захват перескочил границу предложения.
    if re.search(r"\.\s+\S", name) or name.count(".") > 1:
        return False
    if re.search(r"[;!?]", name):
        return False
    # Незакрытая скобка — признак обрезанного захвата («Cult (Культ»).
    if name.count("(") != name.count(")"):
        return False

    tokens = name_tokens(name)
    if not tokens or len(tokens) > 6:
        return False
    if any(token in _STOPWORDS for token in tokens):
        return False
    if any(token.startswith(prefix) for token in tokens for prefix in _STOP_PREFIXES):
        return False
    if tokens[0] in _PREPOSITIONS or tokens[-1] in _PREPOSITIONS:
        return False

    # Голый почтовый адрес — не проект.
    if re.search(r"\b(?:улица|ул|проспект|пр-т|проезд|шоссе|ш|набережная|наб|переулок|пер|бульвар)\b", low) and re.search(
        r"\b\d", low
    ):
        return False
    if re.search(r"\d+[,.]?\d*\s*(?:м[²2]|кв\.?\s*м)", low):
        return False
    # Родовое имя без бренда.
    if low in {"новостройки", "новостройка", "жилые комплексы", "жилой комплекс", "дом", "квартал"}:
        return False

    # Бренд опознаётся заглавной буквой, латиницей или номером очереди. Строка,
    # целиком набранная строчной кириллицей, — это проза, а не вывеска.
    has_brand_shape = bool(
        re.search(r"[A-ZА-ЯЁ]", name) or re.search(r"[a-z]", name) or re.search(r"\d", name)
    )
    return has_brand_shape
