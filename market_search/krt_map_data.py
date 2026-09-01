"""Реестр КРТ картой: `api.krt.mos.ru/map2025.json`.

Найдено живым разбором портала (31.08.2026). Сайт КРТ — Bitrix, список
рендерится сервером и постранично; JSON-эндпоинтов `/api/*` нет вовсе, все
кандидаты отвечают 404. Зато карта портала берёт данные одним статическим
файлом, и в нём лежит ВЕСЬ реестр: 263 площадки против 136 в постраничном
списке и 124 в нашем прежнем снимке — то есть половина каталога до нас не
доезжала.

У каждой записи есть полигон официальных границ и точка центра. Это снимает
оговорку карточки «официальный полигон границ пока не получен»: доли зон НСПД
можно считать по настоящему контуру, а не по геокодированной точке.

Запись — массив без имён полей, поэтому имена сверены с числами HTML-карточек
на нескольких площадках и совпали в поле в поле. Колонка 10 не опознана и
оставлена под своим номером: подписать её догадкой значит завести число, за
которое никто не отвечает.

И отрицательный ответ, важный не меньше: статусов в данных ДВА — «Планируемый»
и «В реализации». «Проекты на торгах» есть только легендой карты, ни одной
такой записи сегодня нет. Значит будущие торги из каталога не выделить, и
ранний сигнал остаётся за решениями mos.ru и публикациями.
"""

from __future__ import annotations

import json
import math
from typing import Any

DATASET_URL = "https://api.krt.mos.ru/map2025.json"

# Порядок полей записи. Проверен сверкой с карточками списка; неопознанное
# названо неопознанным.
NAME, STATUS, OKRUG, DISTRICT = 0, 1, 2, 3
JOBS, TOTAL_GFA, NONRESIDENTIAL, BUSINESS, HOUSING = 5, 6, 7, 8, 9
UNKNOWN_10, AREA_HA = 10, 11
GEOMETRY, PHOTO, POINT, LINK = 14, 15, 16, 17

_EARTH = 6378137.0
_LIMIT = 20037508.342789244


def merc(lon: float, lat: float) -> tuple[float, float]:
    """Веб-меркатор в метрах — тот же, в котором считает карта участка."""
    lat = max(-85.05112878, min(85.05112878, float(lat)))
    x = math.radians(float(lon)) * _EARTH
    y = math.log(math.tan(math.pi / 4 + math.radians(lat) / 2)) * _EARTH
    return x, y


def _number(value: Any) -> float | None:
    try:
        text = str(value).replace(" ", "").replace(",", ".").strip()
        return float(text) if text not in ("", "-") else None
    except (TypeError, ValueError):
        return None


def _rings(geometry: Any) -> list[list[list[float]]]:
    """Кольца полигона в парах «долгота, широта» — как их отдаёт источник."""
    if not isinstance(geometry, dict):
        return []
    kind = str(geometry.get("type") or "")
    coordinates = geometry.get("coordinates") or []
    if kind == "Polygon":
        return [ring for ring in coordinates if isinstance(ring, list) and len(ring) >= 3]
    if kind == "MultiPolygon":
        out: list[list[list[float]]] = []
        for polygon in coordinates:
            for ring in polygon or []:
                if isinstance(ring, list) and len(ring) >= 3:
                    out.append(ring)
        return out
    return []


def simplify(ring: list[list[float]], step_m: float = 12.0) -> list[list[float]]:
    """Проредить кольцо по расстоянию: у площадки бывает под тысячу вершин.

    Точность в десяток метров на обзорной карте не видна вовсе, а вес ответа
    падает в разы. Первая и последняя точки остаются на месте — иначе полигон
    перестанет замыкаться.
    """
    if len(ring) <= 4:
        return [list(point) for point in ring]
    # Метр — предел любой нашей карты: на обзорной в пикселе десятки метров, на
    # карточке участка меньше метра всё равно не видно. Дробная часть при этом
    # утраивает вес ответа.
    def whole(point: list[float]) -> list[int]:
        return [int(round(point[0])), int(round(point[1]))]

    out = [whole(ring[0])]
    for point in ring[1:-1]:
        last = out[-1]
        if math.hypot(point[0] - last[0], point[1] - last[1]) >= step_m:
            out.append(whole(point))
    out.append(whole(ring[-1]))
    return out if len(out) >= 4 else [whole(point) for point in ring]


def parse(payload: Any, step_m: float = 40.0) -> list[dict[str, Any]]:
    """Разобрать файл карты. Запись без слага и без имени — не запись."""
    rows = payload if isinstance(payload, list) else []
    out: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, list) or len(row) <= LINK:
            continue
        link = str(row[LINK] or "")
        name = str(row[NAME] or "").strip()
        if not name or "/projects/" not in link:
            continue
        rings: list[list[list[float]]] = []
        for ring in _rings(row[GEOMETRY]):
            merc_ring = [list(merc(point[0], point[1])) for point in ring
                         if isinstance(point, list) and len(point) >= 2]
            if len(merc_ring) >= 3:
                rings.append(simplify(merc_ring, step_m))
        point = row[POINT] if isinstance(row[POINT], list) and len(row[POINT]) >= 2 else None
        centre = ([int(round(v)) for v in merc(point[0], point[1])]
                  if point else None)
        out.append({
            "slug": link.rsplit("/", 1)[-1],
            "url": "https://krt.mos.ru" + link if link.startswith("/") else link,
            "name": name,
            "status": str(row[STATUS] or "").strip(),
            "okrug": str(row[OKRUG] or "").strip(),
            "district": str(row[DISTRICT] or "").strip(),
            "area_ha": _number(row[AREA_HA]),
            "total_gfa_sqm": _number(row[TOTAL_GFA]),
            "housing_gfa_sqm": _number(row[HOUSING]),
            "nonresidential_gfa_sqm": _number(row[NONRESIDENTIAL]),
            "business_gfa_sqm": _number(row[BUSINESS]),
            "jobs": _number(row[JOBS]),
            # Колонка без имени: у источника подписи нет, а придуманная подпись
            # завела бы число, за которое никто не отвечает.
            "unnamed_10": str(row[UNKNOWN_10] or "").strip(),
            "rings_merc": rings,
            "centre_merc": centre,
        })
    return out


def bbox(sites: list[dict[str, Any]]) -> list[float] | None:
    """Общая рамка всех площадок в метрах меркатора."""
    points = [point for site in sites for ring in site.get("rings_merc") or []
              for point in ring]
    points += [site["centre_merc"] for site in sites if site.get("centre_merc")]
    if not points:
        return None
    xs = [point[0] for point in points]
    ys = [point[1] for point in points]
    return [min(xs), min(ys), max(xs), max(ys)]


def read(fetch, step_m: float = 40.0) -> list[dict[str, Any]]:
    """Прочитать файл карты общим крючком сервиса.

    Шаг прореживания — по тому, что видно: на обзорной карте Москвы в пикселе
    десятки метров, и сорок метров там не различить вовсе, а вес ответа падает
    втрое. Карточке одной площадки нужен шаг мельче, и она его просит.
    """
    return parse(json.loads(fetch(DATASET_URL).decode("utf-8")), step_m)
