"""Что это за страница: карточка проекта, каталог, объявление или статья.

До v6 тип страницы не моделировался вообще. Извлечение работало по тексту, и
поэтому обзорная статья и районный каталог давали такие же «проекты», как
карточка ЖК. Отсюда «Рейтинг застройщиков Дубая» в списке аналогов.

Разбор идёт по URL и только потом по тексту: адрес страницы у агрегаторов
детерминирован, а заголовок — нет. Из адреса же берётся внешний идентификатор
проекта — единственный жёсткий якорь тождества, который есть в выдаче.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import unquote, urlsplit


PROJECT_PAGE = "project_page"
CATALOG = "catalog"
LISTING = "listing"
ARTICLE = "article"
DEVELOPER_PAGE = "developer_page"
OFFICIAL_CARD = "official_card"
UNKNOWN = "unknown"

_OFFICIAL_HOST = "xn--80az8a.xn--d1aqf.xn--p1ai"

_ARTICLE_PATH_RE = re.compile(
    r"/(?:stati|statya|blog|blogs|news|novosti|articles|article|journal|magazine|"
    r"media|reviews|review|rating|reyting|analytics|analitika|guide|wiki|help|about|contacts?)(?:/|$)"
)


@dataclass(frozen=True)
class SourceRef:
    """Разбор адреса документа."""

    site: str
    kind: str
    external_id: str | None = None
    slug: str | None = None

    @property
    def is_project_page(self) -> bool:
        return self.kind == PROJECT_PAGE


def _cian(host: str, path: str) -> SourceRef:
    # Поддомен вида zhk-hamovniki-12-i.cian.ru — отдельная страница ЖК.
    subdomain = host.split(".")[0]
    if subdomain.startswith("zhk-"):
        slug = re.sub(r"-i$", "", subdomain[4:])
        return SourceRef("cian", PROJECT_PAGE, f"cian:zhk:{slug}", slug)
    match = re.search(r"zhiloy-kompleks-([a-z0-9-]+?)-(\d{4,10})/?$", path)
    if match:
        return SourceRef("cian", PROJECT_PAGE, f"cian:{match.group(2)}", match.group(1))
    if _ARTICLE_PATH_RE.search(path):
        return SourceRef("cian", ARTICLE)
    if re.search(r"/(?:novostrojki|novostroyki|zhiloy-kompleks)(?:-|/)", path):
        return SourceRef("cian", CATALOG)
    if (
        re.search(r"/(?:kupit|snyat|arenda|sale|rent)-", path)
        or re.search(r"/(?:sale|rent|flat|suburban|commercial)/", path)
        or "/cat.php" in path
    ):
        return SourceRef("cian", LISTING)
    return SourceRef("cian", UNKNOWN)


def _yandex_realty(host: str, path: str) -> SourceRef:
    match = re.search(r"/novostrojka/([a-z0-9-]+?)-(\d{4,10})/?$", path)
    if match:
        return SourceRef("yandex_realty", PROJECT_PAGE, f"yandex:{match.group(2)}", match.group(1))
    if "/journal/" in path or _ARTICLE_PATH_RE.search(path):
        return SourceRef("yandex_realty", ARTICLE)
    if "/offer/" in path:
        return SourceRef("yandex_realty", LISTING)
    if "/novostrojka" in path or "/kupit/" in path:
        return SourceRef("yandex_realty", CATALOG)
    return SourceRef("yandex_realty", UNKNOWN)


def _domclick(host: str, path: str) -> SourceRef:
    match = re.search(r"/(?:complex|complexes)/([a-z0-9-]+?)(?:-(\d{4,10}))?/?$", path)
    if match:
        external = f"domclick:{match.group(2)}" if match.group(2) else f"domclick:{match.group(1)}"
        return SourceRef("domclick", PROJECT_PAGE, external, match.group(1))
    if _ARTICLE_PATH_RE.search(path):
        return SourceRef("domclick", ARTICLE)
    if re.search(r"/(?:card|offer|sale)/", path):
        return SourceRef("domclick", LISTING)
    if re.search(r"/(?:search|novostrojki|novostroyki)", path):
        return SourceRef("domclick", CATALOG)
    return SourceRef("domclick", UNKNOWN)


def _novostroy(host: str, path: str) -> SourceRef:
    match = re.search(r"/buildings/([a-z0-9-]+)/?$", path)
    if match:
        return SourceRef("novostroy", PROJECT_PAGE, f"novostroy:{match.group(1)}", match.group(1))
    if _ARTICLE_PATH_RE.search(path):
        return SourceRef("novostroy", ARTICLE)
    if "/buildings" in path or "/novostroyki" in path:
        return SourceRef("novostroy", CATALOG)
    return SourceRef("novostroy", UNKNOWN)


_SITES = (
    ("cian.ru", _cian),
    ("realty.yandex.ru", _yandex_realty),
    ("realty.ya.ru", _yandex_realty),
    ("domclick.ru", _domclick),
    ("novostroy.ru", _novostroy),
    ("novostroy-m.ru", _novostroy),
)


def classify_document(url: str, title: str = "", snippet: str = "") -> SourceRef:
    try:
        split = urlsplit(str(url or ""))
        host = (split.hostname or "").lower()
        path = unquote(split.path or "").lower()
    except (ValueError, UnicodeError):
        return SourceRef("other", UNKNOWN)

    if not host:
        return SourceRef("other", UNKNOWN)

    try:
        if host.encode("idna").decode("ascii").lower() == _OFFICIAL_HOST:
            match = re.search(r"/(\d{4,12})/?$", path)
            return SourceRef("domrf", OFFICIAL_CARD, f"domrf:{match.group(1)}" if match else None)
    except (UnicodeError, ValueError):
        pass

    for suffix, parser in _SITES:
        if host == suffix or host.endswith("." + suffix):
            return parser(host, path)

    if _ARTICLE_PATH_RE.search(path):
        return SourceRef("other", ARTICLE)

    text = " ".join(part for part in (title, snippet) if part)
    if _looks_like_editorial(text):
        return SourceRef("other", ARTICLE)
    if re.search(r"/(?:proekty|projects|complex|zhk|novostrojka)/[a-z0-9-]{3,}", path):
        return SourceRef("other", DEVELOPER_PAGE)
    return SourceRef("other", UNKNOWN)


_EDITORIAL_RE = re.compile(
    r"\b(?:рейтинг|топ[-\s]?\d+|обзор|подборка|как\s+выбрать|что\s+нужно\s+знать|"
    r"новости\s+рынка|аналитик[аи]|интервью|колонка|дайджест)\b",
    flags=re.I,
)


def _looks_like_editorial(text: str) -> bool:
    return bool(_EDITORIAL_RE.search(text))


def is_pricing_source(ref: SourceRef) -> bool:
    """Цену можно брать только со страницы конкретного проекта.

    Каталог, объявление и статья содержат цены нескольких разных проектов в одном
    сниппете, и привязать число к сущности там нечем.

    Собственная страница проекта у застройщика — тоже источник, причём самый
    авторитетный: это его собственная цена предложения. Требование доказанной
    привязки к сущности при этом не ослабевает.
    """
    return ref.kind in {PROJECT_PAGE, DEVELOPER_PAGE}
