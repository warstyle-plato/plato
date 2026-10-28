"""Контур КРТ, загруженный человеком: каталог координат МСК-77 или его фото.

Владелец (26.10.2026): когда полигона реестра и контура по решению нет или он
неверный, человек загружает контур сам. Форматы — решение владельца
(AskUserQuestion): каталог координат из приложения к решению о КРТ (МСК-77)
текстом и фото или скан страницы решения.

Что здесь честно, а что нет:
- площадь каталога считается в его же плоских координатах (МСК-77 — плоская
  система на Москву, масштаб 1): она точная, как в документе;
- на карту контур кладётся пересчётом МСК-77 → WGS 84 по опубликованным
  параметрам системы (`MSK77_*`, ±1–2 м): форма и положение — для схемы, а не
  для межевания. Не накрывает участки проекта — это сказано словами;
- фото таблицы «каталог координат» распознаётся (tesseract, тот же, что у
  сканов) в тот же каталог — точный контур. Фото одной схемы границ без
  координат к карте точно не привязать: площадь — из текста, форму обводит
  Платон, а движок ставит её на карту по участкам проекта с названной
  погрешностью (`krt_photo_outline`, владелец 27.10.2026); ответ говорит,
  что границы приблизительные (`approximate`, `origin: photo_outline`).
  Распознавание — фоном (`krt_project_site.start`).
"""

from __future__ import annotations

import math
import re
from typing import Any

# МСК-77 (местная система координат Москвы): поперечная Меркатора на эллипсоиде
# Бесселя, начало 55°40′ с. ш., 37°30′ в. д., масштаб 1, сдвиги начала и
# переход к WGS 84 (7 параметров, вектор положения, как `+towgs84` в PROJ) —
# опубликованные параметры системы (GIS-Lab, «МСК-77»), точность порядка метра.
MSK77_LAT0 = 55.0 + 40.0 / 60.0
MSK77_LON0 = 37.5
MSK77_FALSE_EASTING = 16.098
MSK77_FALSE_NORTHING = 14.512
BESSEL_A = 6377397.155
BESSEL_RF = 299.1528128
MSK77_TOWGS84 = (316.151, 78.924, 589.65, -1.57273, 2.69209, 2.34693, 8.4507)
WGS84_A = 6378137.0
WGS84_RF = 298.257223563

SOURCE_CATALOG = "контур загружен вручную: каталог координат МСК-77"
SOURCE_PHOTO = "контур загружен вручную: каталог координат МСК-77, распознан с фото"
SOURCE_PHOTO_AREA = ("площадь загружена вручную: из текста решения на фото; "
                     "форма участка приблизительная")

MAX_POINTS = 2000
# Территория КРТ меньше этого — не территория: такие «каталоги» собираются из
# случайных чисел (распознанные подписи, номера, доли гектара).
MIN_CATALOG_SQM = 100.0
# Каталог, распознанный с картинки, сверяется с площадью, названной в тексте
# решения: расходится больше этой доли — цифры прочитаны не те.
CATALOG_AREA_TOLERANCE = 0.25
# Координата каталога МСК-77 в пределах Москвы с Новой Москвой — десятки
# километров от начала: больше — это не МСК-77 (градусы, другая зона, номер).
MSK77_RANGE_M = 120_000.0


# --- разбор каталога ------------------------------------------------------------

_NUMBER = re.compile(r"[-−–]?\d{1,3}(?:[   ]\d{3})+(?:[.,]\d{1,3})|[-−–]?\d+[.,]\d{1,3}")


def _value(token: str) -> float:
    clean = re.sub(r"[   ]", "", token).replace(",", ".")
    return float(clean.replace("−", "-").replace("–", "-"))


def parse_catalog(text: str) -> dict[str, Any]:
    """Каталог «№ точки, X, Y» → кольца в МСК-77 (восток, север), м.

    X каталога — на север, Y — на восток (так их пишет решение). Строка
    без двух чисел с дробной частью — не точка (заголовок, номер, примечание).
    Кольцо замыкается повтором первой точки; следующая точка начинает новое.
    """
    rings: list[list[list[float]]] = []
    ring: list[list[float]] = []
    skipped = 0
    for line in str(text or "").splitlines():
        found = _NUMBER.findall(line)
        if len(found) < 2:
            continue
        try:
            north, east = _value(found[0]), _value(found[1])
        except ValueError:
            skipped += 1
            continue
        if abs(north) > MSK77_RANGE_M or abs(east) > MSK77_RANGE_M:
            skipped += 1
            continue
        point = [east, north]
        if ring and abs(point[0] - ring[0][0]) < 0.005 and abs(point[1] - ring[0][1]) < 0.005:
            if len(ring) >= 3:
                rings.append(ring)
            ring = []
            continue
        if ring and abs(point[0] - ring[-1][0]) < 0.005 and abs(point[1] - ring[-1][1]) < 0.005:
            continue
        ring.append(point)
        if sum(len(r) for r in rings) + len(ring) > MAX_POINTS:
            break
    if len(ring) >= 3:
        rings.append(ring)
    return {"rings_local": rings, "points": sum(len(r) for r in rings), "skipped": skipped}


def _ring_area(ring: list[list[float]]) -> float:
    total = 0.0
    for i in range(len(ring)):
        x1, y1 = ring[i]
        x2, y2 = ring[(i + 1) % len(ring)]
        total += x1 * y2 - x2 * y1
    return total / 2.0


def _inside(point: list[float], ring: list[list[float]]) -> bool:
    x, y = point
    inside = False
    for i in range(len(ring)):
        x1, y1 = ring[i]
        x2, y2 = ring[i - 1]
        if (y1 > y) != (y2 > y) and x < (x2 - x1) * (y - y1) / (y2 - y1) + x1:
            inside = not inside
    return inside


def local_area_sqm(rings: list[list[list[float]]]) -> float:
    """Площадь каталога в его плоских координатах; кольцо внутри другого — дыра."""
    total = 0.0
    for i, ring in enumerate(rings):
        hole = sum(1 for j, other in enumerate(rings)
                   if j != i and _inside(ring[0], other)) % 2 == 1
        total += -abs(_ring_area(ring)) if hole else abs(_ring_area(ring))
    return total


# --- МСК-77 → веб-меркатор --------------------------------------------------------

def _meridian(phi: float, a: float, e2: float) -> float:
    e4, e6 = e2 * e2, e2 * e2 * e2
    return a * ((1 - e2 / 4 - 3 * e4 / 64 - 5 * e6 / 256) * phi
                - (3 * e2 / 8 + 3 * e4 / 32 + 45 * e6 / 1024) * math.sin(2 * phi)
                + (15 * e4 / 256 + 45 * e6 / 1024) * math.sin(4 * phi)
                - (35 * e6 / 3072) * math.sin(6 * phi))


def msk77_to_bessel(east: float, north: float) -> tuple[float, float]:
    """Обратная поперечная Меркатора (ряды USGS, Snyder 1987) → широта, долгота
    на эллипсоиде Бесселя, радианы. На десятки километров — доли миллиметра."""
    a = BESSEL_A
    f = 1.0 / BESSEL_RF
    e2 = f * (2 - f)
    ep2 = e2 / (1 - e2)
    m = _meridian(math.radians(MSK77_LAT0), a, e2) + (north - MSK77_FALSE_NORTHING)
    mu = m / (a * (1 - e2 / 4 - 3 * e2 ** 2 / 64 - 5 * e2 ** 3 / 256))
    e1 = (1 - math.sqrt(1 - e2)) / (1 + math.sqrt(1 - e2))
    phi1 = (mu + (3 * e1 / 2 - 27 * e1 ** 3 / 32) * math.sin(2 * mu)
            + (21 * e1 ** 2 / 16 - 55 * e1 ** 4 / 32) * math.sin(4 * mu)
            + (151 * e1 ** 3 / 96) * math.sin(6 * mu)
            + (1097 * e1 ** 4 / 512) * math.sin(8 * mu))
    s, c, t = math.sin(phi1), math.cos(phi1), math.tan(phi1)
    c1 = ep2 * c * c
    t1 = t * t
    n1 = a / math.sqrt(1 - e2 * s * s)
    r1 = a * (1 - e2) / (1 - e2 * s * s) ** 1.5
    d = (east - MSK77_FALSE_EASTING) / n1
    lat = phi1 - (n1 * t / r1) * (d ** 2 / 2
                                  - (5 + 3 * t1 + 10 * c1 - 4 * c1 ** 2 - 9 * ep2) * d ** 4 / 24
                                  + (61 + 90 * t1 + 298 * c1 + 45 * t1 ** 2 - 252 * ep2
                                     - 3 * c1 ** 2) * d ** 6 / 720)
    lon = math.radians(MSK77_LON0) + (d - (1 + 2 * t1 + c1) * d ** 3 / 6
                                      + (5 - 2 * c1 + 28 * t1 - 3 * c1 ** 2 + 8 * ep2
                                         + 24 * t1 ** 2) * d ** 5 / 120) / c
    return lat, lon


def _to_ecef(lat: float, lon: float, a: float, rf: float) -> tuple[float, float, float]:
    f = 1.0 / rf
    e2 = f * (2 - f)
    n = a / math.sqrt(1 - e2 * math.sin(lat) ** 2)
    return (n * math.cos(lat) * math.cos(lon), n * math.cos(lat) * math.sin(lon),
            n * (1 - e2) * math.sin(lat))


def _from_ecef(x: float, y: float, z: float, a: float, rf: float) -> tuple[float, float]:
    f = 1.0 / rf
    e2 = f * (2 - f)
    lon = math.atan2(y, x)
    p = math.hypot(x, y)
    lat = math.atan2(z, p * (1 - e2))
    for _ in range(8):
        n = a / math.sqrt(1 - e2 * math.sin(lat) ** 2)
        h = p / math.cos(lat) - n
        lat = math.atan2(z, p * (1 - e2 * n / (n + h)))
    return lat, lon


def msk77_to_wgs84(east: float, north: float) -> tuple[float, float]:
    """МСК-77 → широта, долгота WGS 84, градусы (Гельмерт, вектор положения)."""
    lat, lon = msk77_to_bessel(east, north)
    x, y, z = _to_ecef(lat, lon, BESSEL_A, BESSEL_RF)
    tx, ty, tz, rx, ry, rz, ppm = MSK77_TOWGS84
    sec = math.pi / (180 * 3600)
    rx, ry, rz, k = rx * sec, ry * sec, rz * sec, 1 + ppm * 1e-6
    x2 = tx + k * (x - rz * y + ry * z)
    y2 = ty + k * (rz * x + y - rx * z)
    z2 = tz + k * (-ry * x + rx * y + z)
    lat2, lon2 = _from_ecef(x2, y2, z2, WGS84_A, WGS84_RF)
    return math.degrees(lat2), math.degrees(lon2)


def wgs84_to_merc(lat: float, lon: float) -> list[float]:
    return [math.radians(lon) * WGS84_A,
            math.log(math.tan(math.pi / 4 + math.radians(lat) / 2)) * WGS84_A]


def rings_to_merc(rings_local: list[list[list[float]]]) -> list[list[list[float]]]:
    return [[wgs84_to_merc(*msk77_to_wgs84(east, north)) for east, north in ring]
            for ring in rings_local]


# --- контур из каталога -------------------------------------------------------------

def _covers(rings: list[list[list[float]]], point: list[float]) -> bool:
    return sum(1 for ring in rings if _inside(point, ring)) % 2 == 1


def from_catalog(text: str, *, points_merc: list[list[float]] | None = None,
                 source: str = SOURCE_CATALOG) -> dict[str, Any]:
    """Каталог → контур на карте и площадь, либо причина словами.

    Участки проекта (`points_merc`) сверяются с контуром: X и Y в каталогах
    путают, и если накрывает только перевёрнутый каталог — берётся он, и это
    сказано. Не накрывает ни один — контур остаётся, но с предупреждением.
    """
    parsed = parse_catalog(text)
    rings = parsed["rings_local"]
    if not rings:
        return {"status": "failed", "rings_merc": [], "area_sqm": None, "approximate": False,
                "problem": "в тексте не нашлось трёх точек с координатами X и Y — "
                           "вставьте таблицу «каталог координат» из приложения к решению"}
    area = local_area_sqm(rings)
    if area <= 0:
        return {"status": "failed", "rings_merc": [], "area_sqm": None, "approximate": False,
                "problem": "точки каталога не образуют площади — проверьте порядок точек"}
    if area < MIN_CATALOG_SQM:
        return {"status": "failed", "rings_merc": [], "area_sqm": None, "approximate": False,
                "problem": (f"точки каталога образуют фигуру площадью {area:.1f} м² — это не "
                            "территория; похоже, в тексте не таблица координат, а другие числа")}
    merc = rings_to_merc(rings)
    notes: list[str] = []
    points = [p for p in (points_merc or []) if isinstance(p, list) and len(p) >= 2]
    if points and not any(_covers(merc, p) for p in points):
        swapped = [[[north, east] for east, north in ring] for ring in rings]
        swapped_merc = rings_to_merc(swapped)
        if any(_covers(swapped_merc, p) for p in points):
            merc = swapped_merc
            notes.append("в каталоге X и Y стояли в обратном порядке — контур построен "
                         "с перестановкой, так он накрывает участки проекта")
        else:
            notes.append("контур не накрывает участки проекта из госреестра — проверьте, "
                         "что каталог тот и что координаты в МСК-77")
    return {"status": "ready", "rings_merc": merc, "area_sqm": round(area, 1),
            "approximate": False, "source": source, "points": parsed["points"],
            "problem": "", "source_note": "; ".join(notes)}


# --- фото и скан ------------------------------------------------------------------

_AREA = re.compile(
    r"пло[щш]ад\w*[^0-9\n]{0,80}?(\d{1,3}(?:[  ]\d{3})*(?:[.,]\d+)?|\d+(?:[.,]\d+)?)\s*"
    r"(га|кв\.?\s*м|м2|м²)", re.I)


def area_from_text(text: str) -> float | None:
    """Площадь территории, названная в тексте решения, м² (га переводятся).
    Распознаватель читает «щ» как «ш» («плошадью») — это тоже площадь."""
    best: float | None = None
    for number, unit in _AREA.findall(str(text or "")):
        try:
            value = _value(number)
        except ValueError:
            continue
        sqm = value * 10000.0 if unit.lower().startswith("га") else value
        if sqm > 0 and (best is None or sqm > best):
            best = sqm
    return best


def _sqm(value: float) -> str:
    return f"{value:,.0f}".replace(",", " ")


def _titled_catalog(text: str) -> bool:
    """Таблица координат в решении названа («каталог координат», «координаты
    характерных точек») или у неё шапка «X … Y»: без этого числа на картинке —
    подписи, номера и доли гектара, а не точки границы."""
    text = str(text or "")
    return bool(re.search(r"координат|каталог", text, re.I)
                or re.search(r"(?:^|\s)[XХ](?:\s[^\n]{0,40})?\s[YУ](?:\s|$)", text, re.M))


def recognised_catalog(text: str, area_in_text: float | None, *,
                       points_merc: list[list[float]] | None = None) -> dict[str, Any]:
    """Каталог, распознанный с картинки или скана, — только если он похож на
    каталог: таблица названа, а площадь по точкам сходится с площадью из
    текста решения (если она там есть). Иначе — `failed` с причиной, и
    страница идёт дальше (площадь из текста и форма с картинки).

    Владелец 28.10.2026 («Пролетарский пр-т, вл. 20»): с картинки схемы без
    таблицы распознаватель собрал «каталог» из случайных чисел — 0,8 м²,
    и он перебил и площадь 0,77 га, и форму.
    """
    if not _titled_catalog(text):
        return {"status": "failed", "problem": "на картинке нет таблицы «каталог координат»"}
    catalog = from_catalog(text, points_merc=points_merc, source=SOURCE_PHOTO)
    if catalog["status"] != "ready":
        return catalog
    got = float(catalog["area_sqm"])
    if area_in_text and abs(got - area_in_text) > CATALOG_AREA_TOLERANCE * area_in_text:
        return {"status": "failed", "problem": (
            f"площадь по распознанным точкам — {_sqm(got)} м², а в тексте решения — "
            f"{_sqm(area_in_text)} м²: цифры координат прочитаны не те")}
    catalog["source_note"] = "; ".join(part for part in (
        catalog.get("source_note"),
        "цифры распознаны с картинки — сверьте площадь с решением") if part)
    return catalog


def scheme_page_image(data: bytes) -> tuple[bytes, str]:
    """PDF решения → картинка страницы со схемой границ (PNG) или причина.

    Страница со схемой — та, где есть картинка и слова «графическое описание»,
    «схема» или «границ»; таких нет — страница с самой большой картинкой.
    """
    try:
        import pymupdf
    except Exception:  # noqa: BLE001 — нечем — это причина, а не тишина
        return b"", "PDF нечем превратить в картинку: на сервере нет pymupdf"
    try:
        document = pymupdf.open(stream=data, filetype="pdf")
    except Exception as exc:  # noqa: BLE001
        return b"", f"PDF не открылся: {type(exc).__name__}"
    best, best_score = None, -1.0
    for index in range(min(document.page_count, 12)):
        page = document[index]
        images = page.get_image_info()
        if not images:
            continue
        boxes = [i.get("bbox") or (0, 0, 0, 0) for i in images]
        cover = max(abs(x1 - x0) * abs(y1 - y0) for x0, y0, x1, y1 in boxes) \
            / max(1.0, page.rect.width * page.rect.height)
        words = page.get_text().lower()
        titled = bool(re.search(r"графическ|схем|границ", words))
        score = cover + (1.0 if titled else 0.0)
        if score > best_score:
            best, best_score = index, score
    if best is None:
        return b"", "в PDF нет страницы с картинкой схемы границ"
    return document[best].get_pixmap(dpi=150).tobytes("png"), ""


def recognise(data: bytes, filename: str, *,
              points_merc: list[list[float]] | None = None,
              anchor_rings_merc: list[list[list[float]]] | None = None,
              addresses: list[str] | None = None,
              ask: Any = None, model: str = "") -> dict[str, Any]:
    """Фото или скан страницы решения → контур или площадь. Долго — только фоном.

    Таблица координат на фото — точный контур (каталог сильнее всего). Её нет —
    площадь из текста и форма с картинки: Платон (`ask`, единый маршрут модели)
    обводит границу, движок проверяет обводку, масштабирует её до площади и
    привязывает к участкам проекта (`krt_photo_outline`). Обводка не вышла —
    только площадь, и причина названа.
    """
    name = str(filename or "").lower()
    pdf = name.endswith(".pdf") or data[:4] == b"%PDF"
    ocr_problem = ""
    if pdf:
        import document_intake

        text = str((document_intake.extract_text(data, filename) or {}).get("text") or "")
    else:
        from developaid_v2_upgrade import _ocr_image

        try:
            text = _ocr_image(data)
        except Exception as exc:  # noqa: BLE001 — отказ распознавания называется
            detail = getattr(exc, "detail", None) or f"{type(exc).__name__}: {exc}"
            ocr_problem = f"фото не распознано: {detail}"[:300]
            text = ""
    area = area_from_text(text)
    catalog_problem = ""
    if text:
        catalog = recognised_catalog(text, area, points_merc=points_merc)
        if catalog["status"] == "ready":
            return catalog
        catalog_problem = catalog.get("problem") or ""
    outline: dict[str, Any] = {}
    picture = data
    if pdf and ask is not None:
        picture, picture_problem = scheme_page_image(data)
        if not picture:
            outline = {"status": "failed", "problem": picture_problem}
    if picture and ask is not None:
        from auction_search import krt_photo_outline

        outline = krt_photo_outline.from_photo(
            picture, area, ask, model=model, read_area=area_from_text,
            rings_merc=anchor_rings_merc, points_merc=points_merc, addresses=addresses)
        area = area or area_from_text(outline.get("area_text") or "")
    if outline.get("status") == "ready" and area:
        placed = bool(outline.get("rings_merc"))
        where = (f"на карту поставлена {outline['anchored_by']}, погрешность — около "
                 f"{outline['anchor_error_m']} м" if placed else
                 f"на карту не поставлена: {outline.get('map_problem') or 'причина не названа'}")
        return {"status": "ready", "origin": "photo_outline", "approximate": True,
                "area_sqm": round(area, 1), "rings_merc": outline.get("rings_merc") or [],
                "shape_m": outline["shape_m"], "anchor_error_m": outline.get("anchor_error_m"),
                "anchored_by": outline.get("anchored_by") or "",
                "map_problem": outline.get("map_problem") or "",
                "source": krt_photo_outline.SOURCE_PHOTO_OUTLINE, "problem": "",
                "source_note": ("на картинке нет таблицы координат, поэтому форма снята с "
                                "картинки: Платон обвёл границу, размер подогнан под площадь "
                                f"из текста решения; {where}"
                                + (f"; числа с картинки за каталог не приняты: {catalog_problem}"
                                   if catalog_problem and _titled_catalog(text) else ""))}
    if area:
        shape_problem = (outline.get("problem") or "") if ask is not None else "Платон не подключён"
        return {"status": "ready", "rings_merc": [], "area_sqm": round(area, 1),
                "approximate": True, "source": SOURCE_PHOTO_AREA, "problem": "",
                "shape_problem": shape_problem,
                "source_note": "на фото нет таблицы координат — к карте его точно не "
                               "привязать, поэтому взята только площадь из текста, а форма "
                               "участка на схеме приблизительная"
                               + (f"; форму с картинки снять не вышло: {shape_problem}"
                                  if shape_problem else "")
                               + (f"; числа с картинки за каталог не приняты: {catalog_problem}"
                                  if catalog_problem and _titled_catalog(text) else "")}
    if ocr_problem and ask is None:
        return {"status": "failed", "rings_merc": [], "area_sqm": None, "approximate": False,
                "problem": ocr_problem}
    reasons = "; ".join(r for r in (ocr_problem, outline.get("problem")) if r)
    return {"status": "failed", "rings_merc": [], "area_sqm": None, "approximate": False,
            "problem": "на фото не нашлось ни таблицы координат, ни площади территории — "
                       "снимите страницу с каталогом координат крупнее и ровнее"
                       + (f" ({reasons})" if reasons else "")}
