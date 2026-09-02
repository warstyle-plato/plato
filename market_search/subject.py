"""Кто объект отчёта: кадастровый номер, адрес или название проекта.

Ввод берётся тот же, что в основном сервисе, — поле «Участок», где человек
пишет кадастровый номер, адрес или координаты. Второго разбора для рынка не
завожу: одно правило на приложение, иначе они разойдутся, и один и тот же ввод
даст в двух местах разные точки. Это уже было с версией и со списком полей.

Порядок распознавания — от однозначного к приблизительному:

1. **кадастровый номер** — точная запись участка, координаты берутся из ЕГРН
   через НСПД, тем же путём, что и ТЭП;
2. **координаты** — если человек вставил «широта, долгота»;
3. **название проекта** — «Пульс» отдаёт по строке идентификатор, а с ним
   приходят и координаты, и класс, и собственные числа проекта;
4. **адрес** — геокодер, последний по надёжности: он ставит точку по улице.

Не распознали — отказ с причиной. Подставлять центр города, чтобы «хоть
что-то посчиталось», нельзя: район на Саввинской набережной уже показал, чем
это кончается.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Callable


CADASTRE_RE = re.compile(r"\b\d{2}:\d{2}:\d{6,7}:\d{1,7}\b")
COORDS_RE = re.compile(
    r"^\s*(-?\d{1,2}[.,]\d{3,})\s*[,; ]\s*(-?\d{1,3}[.,]\d{3,})\s*$"
)

SOURCE_CADASTRE = "cadastre"
SOURCE_COORDS = "coordinates"
SOURCE_PROJECT = "project"
SOURCE_ADDRESS = "address"
SOURCE_KRT = "krt"


_STREET_MARKER = (
    r"(?:ул(?:ица)?\.?|пер(?:еулок)?\.?|проспект|пр-т\.?|шоссе|ш\.?|"
    r"наб(?:ережная)?\.?|бульвар|б-?р\.?|проезд|площадь|пл\.?)"
)
_NEXT_ADDRESS = re.compile(
    rf"[,;]\s*(?=[^,;]{{0,80}}\b{_STREET_MARKER}(?=\s|,|;|$))",
    re.IGNORECASE,
)
_HAS_STREET = re.compile(rf"\b{_STREET_MARKER}(?=\s|,|;|$)", re.IGNORECASE)


# Владение геокодеру не понятно, а улица — понятна, и это хуже пустого ответа.
# Живая проба (02.09.2026): «Москва, Варшавское шоссе, вл. 37» Nominatim
# отвечает типом `road` и точкой в Южном Бутове — в четырнадцати километрах от
# самой площадки; «Москва, Варшавское шоссе, 37» отвечает точкой в
# Нагатино-Садовниках, то есть верной. Совпала УЛИЦА, а не адрес, и на карте
# это выглядело как уверенно поставленная метка (владелец, 02.09.2026: «там не
# то на карте место указано»).
_HOUSE_PREFIX = re.compile(r"(?iu)\b(?:влд|вл|дом|д|уч)\.?\s*(?=\d)")
_HOUSE_NUMBER = re.compile(r"(?iu)(\d+[а-я]?)")
# Тип ответа — часть ответа. У Nominatim это `addresstype`, у Яндекса —
# `precision`; названия разные, смысл один: дом, точка или улица.
_HOUSE_KINDS = {"building", "house", "house_number", "residential", "exact", "number"}
_STREET_KINDS = {"road", "highway", "street", "footway", "path"}
_AREA_KINDS = {"suburb", "city_district", "district", "quarter", "neighbourhood",
               "city", "town", "administrative", "other", "locality"}


def _house_variants(part: str) -> list[str]:
    """Адрес в формах, которые геокодер понимает: «вл. 3А/6» → «3А» и «3А/6»."""
    plain = _HOUSE_PREFIX.sub("", str(part or "")).strip(" ,;")
    variants = [plain]
    if "/" in plain:
        variants.append(plain.split("/")[0].strip())
    return [item for index, item in enumerate(variants) if item and item not in variants[:index]]


def geocode_rank(point: Any, query: str) -> int:
    """Насколько точен ответ: 3 — дом, 2 — точка, 1 — улица, 0 — район.

    Провайдер называет тип по-своему и иногда молчит. Тогда спрашиваем сам
    ответ: есть в нём номер дома из запроса — это дом, нет — доверять нечему.
    """
    kind = str(getattr(point, "precision", "") or "").casefold()
    if kind in _HOUSE_KINDS:
        return 3
    if kind in _STREET_KINDS:
        return 1
    if kind in _AREA_KINDS:
        return 0
    shown = str(getattr(point, "display_name", "") or "").casefold()
    number = _HOUSE_NUMBER.search(str(query or ""))
    if number and number.group(1).casefold() in shown:
        return 3
    return 2


def _krt_geocode_candidates(
    territory: dict[str, Any], fallback: str
) -> list[tuple[str, str]]:
    """Return safe approximate points without joining several holdings."""
    name = " ".join(str(territory.get("name") or "").split())
    parts = [part.strip(" ,;") for part in _NEXT_ADDRESS.split(name)] if name else []
    address_parts = [part for part in parts if _HAS_STREET.search(part)]
    multiple_addresses = len(address_parts) > 1

    candidates: list[tuple[str, str]] = []
    for part in address_parts:
        candidates.extend((f"Москва, {variant}", "address_fragment")
                          for variant in _house_variants(part))

    combined = " ".join(
        str(territory.get("geocode_query") or name or fallback).split()
    )
    if combined and not multiple_addresses:
        candidates.append((combined, "catalogue_query"))

    district = " ".join(str(territory.get("district") or "").split())
    if district:
        candidates.append((f"Москва, район {district}", "district"))

    # Preserve order because the first successful address is the most precise
    # approximation available without the official KRT boundary geometry.
    unique: list[tuple[str, str]] = []
    seen: set[str] = set()
    for candidate, precision in candidates:
        key = candidate.casefold()
        if key not in seen:
            unique.append((candidate, precision))
            seen.add(key)
    return unique


@dataclass
class Subject:
    """Точка отчёта и то, чем она опознана."""

    latitude: float
    longitude: float
    source: str
    query: str
    address: str | None = None
    cadastre: str | None = None
    project_id: int | None = None
    project_name: str | None = None
    segment: str | None = None
    notes: list[str] = field(default_factory=list)
    subject_type: str = "site"
    source_data: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "latitude": self.latitude,
            "longitude": self.longitude,
            "source": self.source,
            "query": self.query,
            "address": self.address,
            "cadastre": self.cadastre,
            "project_id": self.project_id,
            "project_name": self.project_name,
            "segment": self.segment,
            "notes": self.notes,
            "subject_type": self.subject_type,
            "source_data": self.source_data,
        }


class SubjectNotFound(RuntimeError):
    """Ввод не опознан. Это ответ, а не повод подставить что-нибудь."""


def resolve_subject(
    query: str,
    *,
    geocode: Callable[[str], Any] | None = None,
    cadastre: Callable[[str], dict[str, Any] | None] | None = None,
    find_project: Callable[[str], dict[str, Any] | None] | None = None,
    find_krt: Callable[[str], dict[str, Any] | None] | None = None,
) -> Subject:
    """Разобрать ввод в точку. Каждый способ пробуется в порядке надёжности."""
    text = " ".join(str(query or "").split())
    if not text:
        raise SubjectNotFound("Пусто: нужен кадастровый номер, адрес или название проекта")

    number = CADASTRE_RE.search(text)
    if number and not cadastre:
        # Номер опознан — значит человек имел в виду участок, а не строку.
        # Отправлять его в геокодер как адрес нельзя: тот поставит точку куда
        # угодно, и отчёт выйдет достоверным на вид и не о том месте.
        raise SubjectNotFound(
            f"Кадастровый номер {number.group(0)} распознан, но справочник ЕГРН недоступен"
        )
    if number and cadastre:
        parcel = cadastre(number.group(0))
        center = (parcel or {}).get("center") or {}
        if center.get("lat") is not None and center.get("lng") is not None:
            return Subject(
                latitude=float(center["lat"]),
                longitude=float(center["lng"]),
                source=SOURCE_CADASTRE,
                query=text,
                address=(parcel or {}).get("address") or None,
                cadastre=number.group(0),
            )
        # Номер разобран, но участка нет — это осмысленный ответ, и он не должен
        # молча превращаться в поиск по строке номера как по адресу.
        raise SubjectNotFound(
            f"Участок {number.group(0)} не найден в ЕГРН — координаты определить нечем"
        )

    coords = COORDS_RE.match(text)
    if coords:
        return Subject(
            latitude=float(coords.group(1).replace(",", ".")),
            longitude=float(coords.group(2).replace(",", ".")),
            source=SOURCE_COORDS,
            query=text,
        )

    if find_krt:
        territory = find_krt(text)
        if territory:
            if not geocode:
                raise SubjectNotFound("КРТ найдена, но геокодер не подключён")
            # Берётся лучший ответ, а не первый: улица длиной в пятнадцать
            # километров отвечает на запрос дома охотно, и первый ответ бывает
            # хуже второго. Дом нашёлся — дальше не спрашиваем.
            point = None
            used_query = ""
            used_precision = ""
            used_rank = -1
            last_error: RuntimeError | None = None
            for candidate, precision in _krt_geocode_candidates(territory, text):
                try:
                    answer = geocode(candidate)
                except RuntimeError as exc:
                    last_error = exc
                    continue
                rank = geocode_rank(answer, candidate)
                if rank > used_rank:
                    point, used_query, used_precision, used_rank = (
                        answer, candidate, precision, rank)
                if used_rank >= 3:
                    break
            if point is None:
                if last_error:
                    raise last_error
                raise SubjectNotFound("У КРТ нет адреса или района для поиска")

            notes = [
                "КРТ взята из krt.mos.ru; официальная геометрия границ не получена."
            ]
            if used_rank <= 1 and used_precision != "district":
                # Совпала улица, а не адрес: на карте такая метка выглядит
                # уверенно и стоит где угодно вдоль неё.
                notes.append(
                    f"Геокодер нашёл по запросу «{used_query}» только улицу, а не дом: "
                    "точка стоит где-то вдоль неё и площадку не показывает."
                )
            elif used_precision == "address_fragment":
                notes.append(
                    f"Точка поставлена по отдельному адресу «{used_query}»; "
                    "остальные владения проекта не объединялись в один поисковый запрос."
                )
            elif used_precision == "district":
                notes.append(
                    f"Адрес проекта не найден; для предварительного анализа точка "
                    f"поставлена по району: {used_query}."
                )
            else:
                notes.append(f"Точка поставлена геокодером по запросу: {used_query}.")
            return Subject(
                latitude=float(point.latitude), longitude=float(point.longitude),
                source=SOURCE_KRT, query=str(territory.get("query") or text),
                address=getattr(point, "display_name", None), project_name=territory.get("name"),
                subject_type="krt", source_data=territory,
                notes=notes,
            )

    if find_project:
        project = find_project(text)
        if project and project.get("latitude") is not None:
            return Subject(
                latitude=float(project["latitude"]),
                longitude=float(project["longitude"]),
                source=SOURCE_PROJECT,
                query=text,
                address=project.get("address"),
                project_id=project.get("complex_id"),
                project_name=project.get("name"),
                segment=project.get("segment"),
            )

    if geocode:
        point = geocode(text)
        return Subject(
            latitude=float(point.latitude),
            longitude=float(point.longitude),
            source=SOURCE_ADDRESS,
            query=text,
            address=getattr(point, "display_name", None),
            notes=["Точка поставлена геокодером по адресу, а не по границам участка"],
        )

    raise SubjectNotFound(
        "Ввод не опознан: ожидается кадастровый номер, координаты, "
        "название проекта или адрес"
    )
