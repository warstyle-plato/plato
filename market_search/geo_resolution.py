"""Адрес проекта и его координаты — с доказательством принадлежности.

Здесь закрыт главный класс ошибок живого preview: несвязанные кандидаты получали
координаты искомого участка и показывали 0 км.

Механика была такая. Адрес брался регуляркой из склейки `title + snippet` того
документа, из которого извлекли имя. Поисковый сниппет почти всегда содержит
слова запроса, а запрос — это и есть адрес subject-объекта. Значит любой
кандидат, найденный запросом «новостройки рядом с "Москва, Саввинская
набережная, 25"», забирал себе адрес Саввинской 25 и вставал в ноль километров.
Каталожный сниппет добавлял второй путь к той же ошибке: он перечисляет несколько
проектов, и все извлечённые из него кандидаты получали один и тот же адрес.

Правила v6:

1. подсказка адреса, совпадающая с subject-адресом, отбрасывается (`subject_echo`);
2. подсказка берётся только из документа, приписанного этой сущности, — карточки
   проекта с совпавшим идентификатором или заголовком;
3. каталожный сниппет адресов не даёт вообще;
4. результат геокодера грубее уровня улицы не принимается: иначе бренд, которого
   геокодер не знает, возвращает центр города и попадает в радиус;
5. если ничего не вышло — `geo_unresolved` с причиной, а не молчаливый пропуск и
   не 0 км.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from .documents import ARTICLE, CATALOG, LISTING, PROJECT_PAGE, classify_document
from .geocoder import AddressGeocoder, GeocodingError, GeoPoint
from .http import RemoteServiceError
from .normalize import cut_at_separator, labels_match, search_name
from .yandex_search import SearchDoc, YandexSearchClient


RESOLVED = "resolved"
UNRESOLVED = "geo_unresolved"

_STREET = r"(?:ул\.?|улица|проспект|пр-т|просп\.?|проезд|шоссе|ш\.|наб\.?|набережная|переулок|пер\.?|бульвар|б-р|аллея|линия|тупик)"

_ADDRESS_PATTERNS = (
    re.compile(
        # Порядковый номер в начале — часть имени улицы: «1-й переулок Тружеников».
        # Без него адрес геокодируется в другой переулок того же названия.
        rf"((?:\d+-[йяе]\s+)?[А-ЯЁA-Z][А-Яа-яЁёA-Za-z0-9\- ]{{2,45}}\s+{_STREET}\s*,?\s*(?:д\.?\s*|вл\.?\s*|стр\.?\s*)?\d+[А-Яа-яA-Za-z0-9/\-]*)",
        flags=re.I,
    ),
    re.compile(
        rf"((?:\d+-[йяе]\s+)?{_STREET}\s+[А-ЯЁA-Z][А-Яа-яЁёA-Za-z0-9\- ]{{2,45}}\s*,?\s*(?:д\.?\s*|вл\.?\s*|стр\.?\s*)?\d+[А-Яа-яA-Za-z0-9/\-]*)",
        flags=re.I,
    ),
)

# Точность геокодера, при которой точка описывает дом или улицу, а не город.
_YANDEX_OK = {"exact", "number", "near", "range", "street"}
_NOMINATIM_BAD = {
    "city", "town", "village", "state", "region", "province", "country",
    "municipality", "administrative", "suburb", "city_district", "district",
    "county", "postcode",
}


@dataclass(frozen=True)
class GeoResolution:
    status: str
    point: GeoPoint | None = None
    address: str | None = None
    address_source: str | None = None
    reason: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "address": self.address,
            "address_source": self.address_source,
            "reason": self.reason,
            "coordinates": (
                {
                    "latitude": self.point.latitude,
                    "longitude": self.point.longitude,
                    "display_name": self.point.display_name,
                    "provider": self.point.provider,
                    "precision": self.point.precision,
                }
                if self.point
                else None
            ),
        }


def address_signature(value: str) -> str | None:
    """Улица + номер дома в сравнимой форме.

    По ней узнаётся эхо subject-адреса в сниппете. Тип улицы и город из подписи
    выброшены: «Саввинская наб., 25» и «Москва, Саввинская набережная, д. 25» —
    один адрес."""
    text = " ".join(str(value or "").split())
    if not text:
        return None
    number = None
    for match in re.finditer(r"(?:д\.?\s*|вл\.?\s*)?(\d+[А-Яа-яA-Za-z]?(?:\s*(?:к|корп\.?|с|стр\.?)\s*\d+[А-Яа-я]?)?)", text):
        number = match.group(1)
    if not number:
        return None
    words = [
        word
        for word in re.findall(r"[а-яёa-z]+", text.lower().replace("ё", "е"))
        if word
        not in {
            "москва", "москве", "московская", "область", "город", "г",
            "улица", "ул", "шоссе", "ш", "проспект", "пр", "прт", "просп",
            "проезд", "набережная", "наб", "переулок", "пер", "бульвар", "бр",
            "дом", "д", "корпус", "корп", "к", "строение", "стр", "с", "владение", "вл",
        }
        and len(word) >= 3
    ]
    if not words:
        return None
    digits = re.sub(r"[^0-9а-яa-z]+", "", number.lower())
    return "|".join(sorted(words)) + "#" + digits


def extract_address(text: str, locality: str) -> str | None:
    value = " ".join(str(text or "").split())
    for pattern in _ADDRESS_PATTERNS:
        match = pattern.search(value)
        if match:
            found = " ".join(match.group(1).split())
            if re.match(rf"^{locality}\b", found, flags=re.I):
                return found
            return f"{locality}, {found}"
    return None


def precision_is_usable(point: GeoPoint) -> bool:
    precision = str(point.precision or "").lower()
    if point.provider == "yandex":
        return precision in _YANDEX_OK
    if point.provider == "nominatim":
        return bool(precision) and precision not in _NOMINATIM_BAD
    return True


class ProjectGeoResolver:
    """Разрешение географии одной сущности.

    Геокодер и поисковый клиент приходят снаружи, чтобы тест мог подставить
    свои — иначе весь класс ошибок «0 км» проверялся бы только живым прогоном.
    """

    def __init__(
        self,
        geocoder: AddressGeocoder,
        search: YandexSearchClient,
        *,
        locality: str,
        subject_signature: str | None,
        locality_matches,
        search_budget: int = 20,
    ):
        self.geocoder = geocoder
        self.search = search
        self.locality = locality
        self.subject_signature = subject_signature
        self._locality_matches = locality_matches
        # Целевой поиск адреса — два вызова Search API на сущность. Без потолка
        # один запрос с широким каталогом растягивается на сотни вызовов, и окно
        # ответа перестаёт держаться.
        self._search_budget = max(int(search_budget), 0)

    def resolve(self, entity) -> GeoResolution:
        hints: list[tuple[str, str]] = []
        rejected_subject_echo = False

        for candidate in entity.candidates:
            if not candidate.address_attributable:
                continue
            text = " ".join(part for part in (candidate.source_title, candidate.source_snippet) if part)
            address = extract_address(text, self.locality)
            if not address:
                continue
            if self._is_subject_echo(address):
                rejected_subject_echo = True
                continue
            source = (
                "project_page_snippet"
                if candidate.source_kind == PROJECT_PAGE
                else "developer_page_snippet"
            )
            self._append(hints, address, source)

        if not hints:
            found, echo = self._search_address(entity)
            rejected_subject_echo = rejected_subject_echo or echo
            hints.extend(found)

        for address, source in hints:
            try:
                point = self.geocoder.geocode(address)
            except (GeocodingError, RemoteServiceError):
                continue
            if not self._locality_matches(self.locality, point.display_name):
                continue
            if not precision_is_usable(point):
                continue
            return GeoResolution(RESOLVED, point=point, address=address, address_source=source)

        # Последняя попытка — спросить геокодер о самом бренде. Принимается
        # только попадание в дом: precision exact/number значит, что объект у
        # геокодера есть. Уровень улицы и грубее сюда не проходят — именно так
        # прежде в радиус попадал центр Москвы.
        brand = self._geocode_brand(entity)
        if brand is not None:
            return brand

        reason = (
            "Единственный найденный адрес совпал с адресом объекта оценки и отброшен как эхо запроса"
            if rejected_subject_echo
            else "Собственный адрес проекта не найден ни в источниках, ни у геокодера"
            if hints
            else "Проект найден, но ни один источник не назвал его адрес"
        )
        return GeoResolution(UNRESOLVED, reason=reason)

    def _geocode_brand(self, entity) -> GeoResolution | None:
        name = search_name(entity.canonical_name)
        if not name:
            return None
        for query in (f"ЖК {name}, {self.locality}", f"{name}, {self.locality}"):
            try:
                point = self.geocoder.geocode(query)
            except (GeocodingError, RemoteServiceError):
                continue
            if not self._locality_matches(self.locality, point.display_name):
                continue
            if str(point.precision or "").lower() not in {"exact", "number"}:
                continue
            return GeoResolution(
                RESOLVED,
                point=point,
                address=point.display_name,
                address_source="geocoder_brand_exact",
            )
        return None

    def _append(self, hints: list[tuple[str, str]], address: str, source: str) -> None:
        if all(existing != address for existing, _ in hints):
            hints.append((address, source))

    def _is_subject_echo(self, address: str) -> bool:
        if not self.subject_signature:
            return False
        return address_signature(address) == self.subject_signature

    def _search_address(self, entity) -> tuple[list[tuple[str, str]], bool]:
        """Целевой поиск адреса проекта по его имени.

        Принимается только документ, который сам является карточкой этого
        проекта: совпал внешний идентификатор либо название в заголовке. Иначе
        сюда возвращается та же болезнь — адрес чужого объекта из общей выдачи.
        """
        hints: list[tuple[str, str]] = []
        echo = False
        name = search_name(entity.canonical_name)
        if not name or self._search_budget <= 0:
            return hints, echo
        self._search_budget -= 1
        queries = (
            f'"{name}" ЖК {self.locality} адрес',
            f'"{name}" {self.locality} новостройка официальный сайт застройщика',
            f'ЖК "{name}" {self.locality} строительный адрес улица дом',
        )
        for query in queries:
            try:
                docs = self.search.search(query, groups_on_page=10)
            except RemoteServiceError:
                continue
            for doc in docs:
                if not self._document_belongs(entity, doc):
                    continue
                text = " ".join(part for part in (doc.title, doc.snippet) if part)
                address = extract_address(text, self.locality)
                if not address:
                    continue
                if self._is_subject_echo(address):
                    echo = True
                    continue
                self._append(hints, address, "targeted_address_search")
            if hints:
                break
        return hints, echo

    @staticmethod
    def _document_belongs(entity, doc: SearchDoc) -> bool:
        """Документ говорит об этом проекте — чем бы он ни был.

        Прежде принималась только карточка агрегатора, и официальный сайт
        застройщика — лучший источник адреса — отвергался. На живом стенде это
        оставило без адреса двадцать один найденный проект: карточка не всегда
        попадает в первую десятку по запросу об адресе, а сайт девелопера
        попадает почти всегда.

        Каталог, объявление и статья по-прежнему не годятся: каталог перечисляет
        много проектов, у объявления адрес квартиры, а статья — чужой текст с
        произвольными адресами внутри.
        """
        ref = classify_document(doc.url, doc.title, doc.snippet)
        if ref.external_id and ref.external_id in entity.external_ids:
            return True
        if ref.kind in {CATALOG, ARTICLE, LISTING}:
            return False
        title_name = cut_at_separator(doc.title)
        if not title_name:
            return False
        return labels_match(title_name, [entity.canonical_name, *entity.aliases])
