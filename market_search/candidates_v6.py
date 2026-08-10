"""Извлечение кандидатов: только оттуда, где название проекта опознаётся структурно.

Правило, которого не было в v5: **свободная проза названий не даёт**. Кандидат
рождается либо на карточке проекта у известного агрегатора (тогда у него есть
внешний идентификатор), либо из названия в кавычках, либо из конструкции
«ЖК X — ...» в заголовке. Обзор, каталог и объявление проектом стать не могут.

v5 шёл от текста: искал в склейке title+snippet слова «клубный дом» и забирал
следующие 60 символов до запятой. Класс символов допускал точку, поэтому захват
перескакивал границу предложения — так «клубный дом в центре Москвы. Рейтинг
застройщиков Дубая. Адрес офиса» стал жилым комплексом.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from .documents import (
    ARTICLE,
    CATALOG,
    DEVELOPER_PAGE,
    LISTING,
    OFFICIAL_CARD,
    PROJECT_PAGE,
    SourceRef,
    classify_document,
)
from .normalize import (
    canonical_key,
    name_tokens,
    clean_display_name,
    cut_at_separator,
    looks_like_project_name,
    quoted_names,
    strip_marketing_tail,
)
from .yandex_search import SearchDoc


# Пометки, по которым документ исключается целиком: офис, апартаменты без
# квартир, вторичка. Живут здесь, а не в извлечении имени: это свойство
# документа, а не строки.
_COMMERCIAL_RE = re.compile(
    r"\b(?:бизнес[-\s]?центр|бц\s|деловой\s+центр|офисн(?:ый|ое|ого|ые|ых)\s+(?:центр|здание|комплекс)|"
    r"office\s+centre?|business\s+cent(?:er|re)|коммерческая\s+недвижимость)\b",
    flags=re.I,
)
_APART_ONLY_RE = re.compile(r"\bапарт[-\s]?(?:отель|комплекс)\b|\bкомплекс\s+апартаментов\b", flags=re.I)
_SECONDARY_RE = re.compile(r"\bвторичн(?:ая|ое|ый|ого|ые|ых)\b|\bвторичный\s+рынок\b|\bперепродаж[аи]\b", flags=re.I)
_RESIDENTIAL_RE = re.compile(r"\bквартир[а-я]*\b|\bжил(?:ой|ая|ые|ого)\b", flags=re.I)

_TITLE_PROJECT_RE = re.compile(
    r"\b(?:ЖК|жил(?:ой|ого)\s+комплекс(?:а)?|клубн(?:ый|ого)\s+(?:дом|квартал)а?|жил(?:ой|ого)\s+квартал(?:а)?)\s+"
    r"(?P<name>[^«»\"'|\n]{2,60}?)"
    # Терминаторы перечисляются полностью: без «·» шаблон захватывал три проекта
    # каталожного списка в одно имя — та же ошибка, что прежде с ASCII-дефисом.
    r"(?=\s*[—–|,:·•;]|\s+в\s+(?:Москве|Московской)|\s+от\s+застройщика|\s*[-−]\s|$)",
    flags=re.I,
)

# Каталожный сниппет перечисляет проекты через настоящие разделители списка.
# Запятую сюда не берём: в прозе она стоит на каждом шагу, и v5 именно так
# набрал мусора. Точка с запятой, средняя точка и вертикальная черта в связном
# тексте почти не встречаются.
_LIST_SPLIT_RE = re.compile(r"\s*[·•|;]\s*|\s+—\s+|\n")

# Мусор, который каталожный список подсовывает наравне с проектами: строка о
# ходе стройки, число корпусов, имя застройщика и голая улица. На карточке
# проекта заголовок авторитетен — там эти правила не применяются: ЖК
# «Фрунзенская набережная» существует, а «Мичуринский проспект» из каталожного
# перечисления — это улица.
_LIST_JUNK_RE = re.compile(
    r"^\d+\s+(?:корпус[а-я]*|очеред[ьи]|секци[яи]|этаж[а-я]*)$"
    r"|^(?:ход\s+строительства|о\s+проекте|подробнее|все\s+объекты)\b"
    # Срок сдачи — не проект: «2 квартал 2026 года» приехал в карантин как ЖК.
    r"|\b[1-4]\s*кв(?:артал)?\.?\s+\d{4}"
    r"|\b(?:в|до)\s+\d{4}\s*(?:году|г\.?)\b"
    # Обрывки прозы из описания расположения: «Прямо напротив»,
    # «Новодевичий монастырь, по соседству».
    r"|\b(?:по\s+соседству|напротив|неподал[её]ку|поблизости|в\s+шаговой)\b"
    r"|^(?:прямо|совсем|буквально)\b",
    flags=re.I,
)
_DEVELOPER_SUFFIX_RE = re.compile(
    r"^\S+(?:строй|девелопмент|инвест|development)$|^(?:ук|ооо|ао|гк)\s|\bгрупп$|\bgroup$",
    flags=re.I,
)
_STREET_TAIL_RE = re.compile(
    r"\b(?:проспект|улица|набережная|шоссе|переулок|бульвар|проезд|аллея)$", flags=re.I
)


def _looks_like_list_junk(value: str) -> bool:
    text = " ".join(str(value or "").split())
    if _LIST_JUNK_RE.search(text):
        return True
    if _DEVELOPER_SUFFIX_RE.match(text):
        return True
    return bool(_STREET_TAIL_RE.search(text))


_DEVELOPER_RE = re.compile(
    r"(?:застройщик|девелопер)[:\s]+[«\"']?([A-Za-zА-ЯЁа-яё0-9 .\-&]{2,40}?)[»\"']?(?=[,.;)]|\s+в\s|$)",
    flags=re.I,
)


@dataclass
class Candidate:
    """Кандидат в аналоги — до разрешения сущности и до геокодирования."""

    raw_name: str
    canonical_name: str
    key: str
    source_url: str
    source_domain: str
    source_title: str
    source_snippet: str
    source_kind: str
    site: str
    external_id: str | None
    search_rank: int
    extraction_evidence: str
    extraction_confidence: float
    developer: str | None = None
    # Сниппет каталога перечисляет несколько проектов сразу, поэтому адрес из
    # него ни одному из них не принадлежит. Признак несёт кандидат, чтобы
    # разрешение адреса не гадало по домену.
    address_attributable: bool = True
    discovery_sources: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "raw_name": self.raw_name,
            "canonical_name": self.canonical_name,
            "key": self.key,
            "source_url": self.source_url,
            "source_domain": self.source_domain,
            "source_title": self.source_title,
            "source_kind": self.source_kind,
            "site": self.site,
            "external_id": self.external_id,
            "search_rank": self.search_rank,
            "extraction_evidence": self.extraction_evidence,
            "extraction_confidence": self.extraction_confidence,
            "developer": self.developer,
            "address_attributable": self.address_attributable,
        }


def document_is_residential(doc: SearchDoc) -> bool:
    title = " ".join(str(doc.title or "").split())
    text = " ".join(part for part in (doc.title, doc.snippet) if part)
    if _COMMERCIAL_RE.search(title):
        return False
    if _COMMERCIAL_RE.search(text) and not _RESIDENTIAL_RE.search(text):
        return False
    if _APART_ONLY_RE.search(title):
        return False
    if _APART_ONLY_RE.search(text) and not re.search(r"\bквартир[а-я]*\b", text, flags=re.I):
        return False
    if _SECONDARY_RE.search(text):
        return False
    return True


def _developer(text: str) -> str | None:
    match = _DEVELOPER_RE.search(str(text or ""))
    if not match:
        return None
    value = " ".join(match.group(1).split()).strip(" .,-")
    return value if 2 <= len(value) <= 40 else None


def _accept(name: str) -> str | None:
    trimmed = cut_at_separator(name)
    if not looks_like_project_name(trimmed):
        return None
    display = clean_display_name(strip_marketing_tail(trimmed))
    return display or None


def extract_candidates(docs: list[SearchDoc]) -> list[Candidate]:
    result: list[Candidate] = []
    for doc in docs:
        ref = classify_document(doc.url, doc.title, doc.snippet)
        if ref.kind in {ARTICLE, LISTING, OFFICIAL_CARD}:
            # Статья, объявление и официальная карточка сущностью проекта не
            # становятся. Карточка Наш.Дом.РФ подтверждает уже найденный проект,
            # но сама его не создаёт.
            continue
        if not document_is_residential(doc):
            continue
        result.extend(_candidates_from_doc(doc, ref))
    return sorted(result, key=lambda item: (item.search_rank, -item.extraction_confidence, item.canonical_name.lower()))


def _candidates_from_doc(doc: SearchDoc, ref: SourceRef) -> list[Candidate]:
    text = " ".join(part for part in (doc.title, doc.snippet) if part)
    developer = _developer(text)
    out: list[Candidate] = []

    def emit(name: str, evidence: str, confidence: float, attributable: bool) -> None:
        display = _accept(name)
        if not display:
            return
        # Проверка мусора применяется ко всему, что не является карточкой
        # проекта. На карточке заголовок авторитетен: ЖК «Фрунзенская
        # набережная» существует. А «Мичуринский проспект», «Донстрой» и «УК АСК
        # ГРУПП», пришедшие из каталога, — это улица и две компании; на живом
        # стенде они дошли до геокодера и получили координаты.
        if ref.kind != PROJECT_PAGE and _looks_like_list_junk(display):
            return
        key = canonical_key(display)
        if len(key) < 3:
            return
        out.append(
            Candidate(
                raw_name=" ".join(str(name).split()),
                canonical_name=display,
                key=key,
                source_url=doc.url,
                source_domain=doc.domain or ref.site,
                source_title=doc.title,
                source_snippet=doc.snippet,
                source_kind=ref.kind,
                site=ref.site,
                external_id=ref.external_id,
                search_rank=doc.rank,
                extraction_evidence=evidence,
                extraction_confidence=confidence,
                developer=developer,
                address_attributable=attributable,
                discovery_sources=[doc.domain] if doc.domain else [],
            )
        )

    if ref.kind == PROJECT_PAGE:
        # Единственный случай, когда заголовку страницы можно верить как названию:
        # адрес страницы уже доказал, что это карточка одного проекта.
        emit(doc.title, "aggregator_project_page", 0.95, True)
        if not out:
            for name in quoted_names(doc.title) or quoted_names(doc.snippet):
                emit(name, "aggregator_project_page_quoted", 0.9, True)
        return out

    # Каталог и страница застройщика перечисляют несколько проектов. Названия
    # берём только там, где они выделены явно, а адрес из такого сниппета никому
    # не приписываем.
    attributable = ref.kind == DEVELOPER_PAGE
    evidence_prefix = "catalog_child" if ref.kind == CATALOG else "page_project_mention"
    seen: set[str] = set()
    for name in quoted_names(text):
        if name.lower() in seen:
            continue
        seen.add(name.lower())
        emit(name, f"{evidence_prefix}_quoted", 0.75 if attributable else 0.6, attributable)
    for match in _TITLE_PROJECT_RE.finditer(text):
        name = match.group("name")
        if name.lower() in seen:
            continue
        seen.add(name.lower())
        emit(name, f"{evidence_prefix}_typed", 0.7 if attributable else 0.55, attributable)

    if ref.kind == CATALOG:
        # Каталог перечисляет проекты списком, и кавычек в сниппете обычно нет.
        # Такой кандидат — лишь наводка: адреса он не даёт и обязан подтвердить
        # собственный адрес, иначе уйдёт в карантин. Поэтому планку узнавания
        # здесь можно опустить, не возвращая мусор в выдачу.
        for fragment in _LIST_SPLIT_RE.split(str(doc.snippet or "")):
            fragment = fragment.strip(" .,:;")
            if not fragment or fragment.lower() in seen:
                continue
            if len(name_tokens(fragment)) > 4:
                continue
            seen.add(fragment.lower())
            emit(fragment, "catalog_child_listed", 0.45, False)
    return out
