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
        }


class SubjectNotFound(RuntimeError):
    """Ввод не опознан. Это ответ, а не повод подставить что-нибудь."""


def resolve_subject(
    query: str,
    *,
    geocode: Callable[[str], Any] | None = None,
    cadastre: Callable[[str], dict[str, Any] | None] | None = None,
    find_project: Callable[[str], dict[str, Any] | None] | None = None,
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
