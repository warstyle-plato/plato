from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse


_AREA = re.compile(
    r"(?P<number>\d[\d\s\u00a0]*(?:[.,]\d+)?)"
    r"(?:\s*\+\s*/\s*-\s*\d[\d\s\u00a0]*(?:[.,]\d+)?)?"
    r"\s*(?:кв\.?\s*(?:м(?:етр(?:а|ов)?)?\.?)|м[²2])",
    re.IGNORECASE,
)

_LAND = re.compile(r"(?:земельн\w*\s+участ\w*|(?<![а-яё])зу(?![а-яё]))", re.IGNORECASE)
_BUILDING = re.compile(
    r"(?:нежил\w*\s+здани\w*|здани\w*|строени\w*|помещени\w*|"
    r"сооружени\w*|объект\w*\s+недвижим\w*\s+имуществ\w*|"
    r"(?<![а-яё])окс(?![а-яё])|проходн\w*)",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class ExportAreas:
    land_area_sqm: float | None
    building_area_sqm: float | None


def _number(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(str(value).replace("\u00a0", "").replace(" ", "").replace(",", "."))
    except (TypeError, ValueError):
        return None


def _explicit_areas(title: str) -> ExportAreas:
    land: list[float] = []
    building: list[float] = []
    previous_end = 0

    for match in _AREA.finditer(title):
        # Берём только текущую смысловую часть заголовка. Иначе слово
        # «здание» из начала длинного лота классифицирует площадь следующего
        # земельного участка как ещё одно здание.
        context = title[max(previous_end, match.start() - 220):match.start()]
        land_markers = list(_LAND.finditer(context))
        building_markers = list(_BUILDING.finditer(context))
        land_at = land_markers[-1].start() if land_markers else -1
        building_at = building_markers[-1].start() if building_markers else -1
        value = _number(match.group("number"))
        if value is not None and value > 0:
            if land_at > building_at:
                land.append(value)
            elif building_at > land_at:
                building.append(value)
        previous_end = match.end()

    return ExportAreas(
        land_area_sqm=sum(land) if land else None,
        building_area_sqm=sum(building) if building else None,
    )


def export_areas(row: dict[str, Any]) -> ExportAreas:
    """Разделяет площади для Excel, не меняя сам лот и его оценку.

    ГИС Торги иногда кладёт в `totalAreaRealty` площадь здания, а иногда сумму
    участка и зданий. Для строк этого источника явно подписанные площади из
    названия надёжнее общего поля. У остальных источников текст используется
    только для заполнения отсутствующего значения.
    """
    current = ExportAreas(
        land_area_sqm=_number(row.get("land_area_sqm")),
        building_area_sqm=_number(row.get("building_area_sqm")),
    )
    title = str(row.get("name") or "")
    if not title:
        return current

    explicit = _explicit_areas(title)
    host = urlparse(str(row.get("url") or "")).hostname or ""
    is_torgi_gov = host == "torgi.gov.ru" or host.endswith(".torgi.gov.ru")
    if is_torgi_gov:
        return ExportAreas(
            land_area_sqm=explicit.land_area_sqm or current.land_area_sqm,
            building_area_sqm=explicit.building_area_sqm or current.building_area_sqm,
        )
    return ExportAreas(
        land_area_sqm=current.land_area_sqm or explicit.land_area_sqm,
        building_area_sqm=current.building_area_sqm or explicit.building_area_sqm,
    )
