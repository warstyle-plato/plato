"""Контур КРТ с картинки решения без координат: обводка Платона + привязка.

Владелец (27.10.2026, «Пролетарский пр-т, вл. 20»): загрузил Приложение 1 к
решению о КРТ — граница территории синей линией на спутниковом снимке, подпись
«площадью 0,77 га», таблицы координат нет. Получил квадрат. Решение владельца
(AskUserQuestion): «Форма с картинки + привязка».

Как это устроено:
- Платон (модель, единый маршрут `_openai_responses_request`, фоном) обводит
  линию границы на картинке — многоугольник в пикселях, цвет линии, направление
  на север, подписанные улицы. Ответ — строгий JSON;
- движок не верит обводке на слово: стороны многоугольника должны лежать на
  линии названного цвета (`check_outline`), иначе — отказ с причиной;
- масштаб — по площади из текста решения (форма подгоняется под неё, площадь
  точная, как в решении), поворот — по северу картинки (схемы решений Москвы
  ориентированы на север);
- положение — по участкам проекта (найденный контур площадки, участки ЕГРН):
  они должны лечь внутрь обводки. Мест, где они ложатся целиком, обычно
  много — выбирается середина, а размах называется погрешностью привязки.
  Улица из адреса участка, подписанная на снимке, сужает выбор: участок с
  адресом на улице стоит у неё;
- не привязалось — форма остаётся (схема по форме), карты нет, причина
  словами. Каталог координат (Приложение 2) сильнее: он точный.
"""

from __future__ import annotations

import base64
import io
import json
import math
import re
from typing import Any, Callable

import numpy as np

SOURCE_PHOTO_OUTLINE = ("контур снят с картинки решения: границы приблизительные, "
                        "размер — по площади из текста решения")

# Картинка уходит модели не больше этого по длинной стороне: координаты
# обводки — в пикселях той же картинки, по ней же движок проверяет линию.
MAX_SIDE_PX = 1600
# Сторона обводки считается лежащей на линии, если рядом (в этом радиусе)
# есть пиксель цвета линии; таких точек по периметру должно быть не меньше доли.
LINE_SEARCH_PX = 6
LINE_COLOUR_DISTANCE = 70.0
LINE_SHARE_MIN = 0.6
# Привязка: шаг перебора сдвигов, м; доля участков проекта внутри обводки,
# ниже которой привязка не удалась; допуск «почти лучшего» покрытия.
ANCHOR_STEP_M = 2.0
ANCHOR_COVER_MIN = 0.9
ANCHOR_COVER_SLACK = 0.02
# Нижняя граница погрешности: обводка по картинке сама неточна на пару
# пикселей, это метры на местности.
ANCHOR_ERROR_FLOOR_M = 10.0
# Участок с адресом на улице стоит у неё: из мест, где он ложится в обводку,
# берутся ближайшие к улице (в пределах этого допуска от самого близкого).
STREET_SLACK_M = 8.0

OUTLINE_INSTRUCTIONS = (
    "На картинке — страница решения о комплексном развитии территории (КРТ) Москвы: "
    "граница территории обведена линией на спутниковом снимке или карте. Найди эту "
    "линию границы (не рамку в легенде «Условные обозначения» и не рамку снимка) и "
    "обведи её многоугольником по углам линии, по порядку обхода, в пикселях этой "
    "картинки: x — вправо от левого края, y — вниз от верхнего. Ширина и высота "
    "картинки даны в сообщении. line_rgb — цвет линии границы. north_deg — угол "
    "стрелки севера по часовой от верха картинки; стрелки нет — 0. area_text — "
    "фраза с площадью территории, как она написана (например «площадью 0,77 га»), "
    "иначе пусто. streets — подписанные на снимке улицы: название как написано и две "
    "точки вдоль улицы в пикселях. Линии границы нет — found=false и причина в "
    "problem. Ничего не додумывай: обводи только то, что видно. Ответ — только JSON "
    "по схеме."
)

_POINT = {"type": "array", "items": {"type": "number"}}
OUTLINE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["found", "problem", "outline_px", "line_rgb", "north_deg", "area_text",
                 "streets"],
    "properties": {
        "found": {"type": "boolean"},
        "problem": {"type": "string"},
        "outline_px": {"type": "array", "items": _POINT},
        "line_rgb": {"type": "array", "items": {"type": "number"}},
        "north_deg": {"type": "number"},
        "area_text": {"type": "string"},
        "streets": {"type": "array", "items": {
            "type": "object", "additionalProperties": False,
            "required": ["name", "points_px"],
            "properties": {"name": {"type": "string"},
                           "points_px": {"type": "array", "items": _POINT}}}},
    },
}


# --- картинка -----------------------------------------------------------------------

def prepare_image(data: bytes) -> tuple[bytes, np.ndarray]:
    """Фото → JPEG для модели (не больше MAX_SIDE_PX) и те же пиксели массивом."""
    from PIL import Image, ImageOps

    image = ImageOps.exif_transpose(Image.open(io.BytesIO(data))).convert("RGB")
    scale = MAX_SIDE_PX / max(image.size)
    if scale < 1:
        image = image.resize((max(1, round(image.width * scale)),
                              max(1, round(image.height * scale))), Image.LANCZOS)
    out = io.BytesIO()
    image.save(out, format="JPEG", quality=88)
    return out.getvalue(), np.asarray(image, dtype=np.int16)


def outline_request(jpeg: bytes, width: int, height: int, model: str) -> dict[str, Any]:
    """Запрос модели: картинка и размер, ответ — строгий JSON по `OUTLINE_SCHEMA`."""
    url = "data:image/jpeg;base64," + base64.b64encode(jpeg).decode("ascii")
    return {"model": model, "instructions": OUTLINE_INSTRUCTIONS,
            "input": [{"role": "user", "content": [
                {"type": "input_text",
                 "text": f"Картинка {width} × {height} пикселей. Обведи границу территории КРТ."},
                {"type": "input_image", "image_url": url}]}],
            "text": {"format": {"type": "json_schema", "name": "krt_photo_outline",
                                "strict": True, "schema": OUTLINE_SCHEMA}},
            "max_output_tokens": 6000, "store": False}


def _points(raw: Any) -> list[list[float]]:
    out = []
    for p in raw or []:
        try:
            x, y = float(p[0]), float(p[1])
        except (TypeError, ValueError, IndexError):
            continue
        if math.isfinite(x) and math.isfinite(y):
            out.append([x, y])
    return out


def _ring_area(ring: list[list[float]]) -> float:
    return sum(ring[i][0] * ring[(i + 1) % len(ring)][1] - ring[(i + 1) % len(ring)][0] * ring[i][1]
               for i in range(len(ring))) / 2.0


def _segments_cross(a, b, c, d) -> bool:
    def side(p, q, r):
        return (q[0] - p[0]) * (r[1] - p[1]) - (q[1] - p[1]) * (r[0] - p[0])
    return (side(a, b, c) * side(a, b, d) < 0) and (side(c, d, a) * side(c, d, b) < 0)


def check_outline(answer: dict[str, Any], pixels: np.ndarray) -> tuple[list[list[float]], str]:
    """Обводка модели → многоугольник в пикселях или причина, почему не принят.

    Проверка движком: многоугольник внутри картинки, без самопересечений, не
    крошечный, и его стороны лежат на линии того цвета, что назвала модель.
    """
    height, width = pixels.shape[:2]
    if not answer.get("found"):
        why = str(answer.get("problem") or "").strip()
        return [], "Платон не нашёл на картинке линию границы" + (f": {why}" if why else "")
    ring = _points(answer.get("outline_px"))
    if len(ring) >= 2 and abs(ring[0][0] - ring[-1][0]) < 0.5 and abs(ring[0][1] - ring[-1][1]) < 0.5:
        ring = ring[:-1]
    if len(ring) < 3:
        return [], "обводка Платона — меньше трёх углов"
    if any(not (-2 <= x <= width + 2 and -2 <= y <= height + 2) for x, y in ring):
        return [], "обводка Платона выходит за края картинки"
    n = len(ring)
    for i in range(n):
        for j in range(i + 2, n):
            if i == 0 and j == n - 1:
                continue
            if _segments_cross(ring[i], ring[(i + 1) % n], ring[j], ring[(j + 1) % n]):
                return [], "обводка Платона пересекает сама себя"
    if abs(_ring_area(ring)) < 0.0005 * width * height:
        return [], "обводка Платона слишком мала, чтобы снять с неё форму"
    try:
        rgb = [float(v) for v in (answer.get("line_rgb") or [])[:3]]
    except (TypeError, ValueError):
        rgb = []
    if len(rgb) < 3:
        return [], "Платон не назвал цвет линии границы — обводку нечем проверить"
    near = np.sqrt(((pixels.astype(np.float32) - np.array(rgb, dtype=np.float32)) ** 2).sum(axis=2)) \
        <= LINE_COLOUR_DISTANCE
    hits = total = 0
    r = LINE_SEARCH_PX
    for i in range(n):
        (x1, y1), (x2, y2) = ring[i], ring[(i + 1) % n]
        steps = max(1, int(math.hypot(x2 - x1, y2 - y1) / 3))
        for k in range(steps):
            x = x1 + (x2 - x1) * k / steps
            y = y1 + (y2 - y1) * k / steps
            xi, yi = int(round(x)), int(round(y))
            window = near[max(0, yi - r):min(height, yi + r + 1), max(0, xi - r):min(width, xi + r + 1)]
            total += 1
            hits += bool(window.any())
    share = hits / total if total else 0.0
    if share < LINE_SHARE_MIN:
        return [], (f"обводка Платона не совпала с линией границы на картинке: на линии "
                    f"лежит {round(share * 100)}% её периметра")
    return ring, ""


# --- форма в метрах -------------------------------------------------------------------

def _rotate(points: list[list[float]], angle: float) -> list[list[float]]:
    c, s = math.cos(angle), math.sin(angle)
    return [[x * c - y * s, x * s + y * c] for x, y in points]


def shape_metres(ring_px: list[list[float]], area_sqm: float, north_deg: float = 0.0
                 ) -> tuple[list[list[float]], float, tuple[float, float]]:
    """Обводка в пикселях → кольцо на местности (м, x — восток, y — север) с
    центром в нуле, метров на пиксель и центр в пикселях. Масштаб — по площади
    из текста решения: площадь кольца ровно она."""
    pixel_area = abs(_ring_area(ring_px))
    k = math.sqrt(area_sqm / pixel_area)
    cx = sum(p[0] for p in ring_px) / len(ring_px)
    cy = sum(p[1] for p in ring_px) / len(ring_px)
    return (_to_ground(ring_px, k, (cx, cy), north_deg), k, (cx, cy))


def _to_ground(points: list[list[float]], k: float, centre: tuple[float, float],
               north_deg: float) -> list[list[float]]:
    # y картинки — вниз, север — вверх; стрелка севера под углом θ по часовой —
    # картинка поворачивается на θ против часовой.
    flat = [[(x - centre[0]) * k, (centre[1] - y) * k] for x, y in points]
    return _rotate(flat, math.radians(float(north_deg or 0.0)))


# --- привязка ----------------------------------------------------------------------

def _inside_many(px: np.ndarray, py: np.ndarray, ring: list[list[float]]) -> np.ndarray:
    inside = np.zeros(px.shape, dtype=bool)
    n = len(ring)
    for i in range(n):
        x1, y1 = ring[i]
        x2, y2 = ring[i - 1]
        if y1 == y2:
            continue
        cross = ((y1 > py) != (y2 > py)) & (px < (x2 - x1) * (py - y1) / (y2 - y1) + x1)
        inside ^= cross
    return inside


def _samples(ring: list[list[float]], step: float = 4.0) -> list[list[float]]:
    """Точки кольца участка: углы, точки по сторонам и середина."""
    out = []
    n = len(ring)
    for i in range(n):
        (x1, y1), (x2, y2) = ring[i], ring[(i + 1) % n]
        steps = max(1, int(math.hypot(x2 - x1, y2 - y1) / step))
        out += [[x1 + (x2 - x1) * j / steps, y1 + (y2 - y1) * j / steps] for j in range(steps)]
    # Точки чуть внутрь от углов: участок, касающийся границы обводки, всё
    # равно должен считаться внутри, а точка ровно на линии — лотерея.
    cx = sum(p[0] for p in ring) / n
    cy = sum(p[1] for p in ring) / n
    return [[x + (cx - x) * 0.04, y + (cy - y) * 0.04] for x, y in out] + [[cx, cy]]


def _street_key(name: str) -> str:
    """«Пролетарский пр-т» → «пролетарск»: первое слово без окончания."""
    words = re.findall(r"[а-яёa-z0-9]+", str(name or "").lower())
    skip = {"улица", "ул", "проспект", "пр", "т", "бульвар", "б", "р", "шоссе", "ш",
            "переулок", "пер", "проезд", "пр-д", "площадь", "пл", "набережная", "наб", "г",
            "москва", "вл", "влд", "д", "дом", "владение"}
    for word in words:
        if word in skip or word.isdigit() or len(word) < 4:
            continue
        return word[:-2] if len(word) > 6 else word
    return ""


def _distance_to_segment(px: np.ndarray, py: np.ndarray, a, b) -> np.ndarray:
    ax, ay = a
    bx, by = b
    dx, dy = bx - ax, by - ay
    length2 = dx * dx + dy * dy or 1e-9
    t = np.clip(((px - ax) * dx + (py - ay) * dy) / length2, 0.0, 1.0)
    return np.hypot(px - (ax + t * dx), py - (ay + t * dy))


def anchor(shape: list[list[float]], *, rings_merc: list[list[list[float]]] | None = None,
           points_merc: list[list[float]] | None = None,
           streets: list[dict[str, Any]] | None = None,
           addresses: list[str] | None = None) -> dict[str, Any]:
    """Форма на местности (м, центр — ноль) → кольцо в меркаторе по участкам
    проекта, погрешность и чем привязано; не вышло — причина.

    `rings_merc` — контуры участков проекта (найденная площадка, ЕГРН),
    `points_merc` — их точки, когда контуров нет. `streets` — улицы снимка уже
    в метрах формы (`name`, `line_m`), `addresses` — адреса участков.
    """
    rings = [r for r in (rings_merc or []) if isinstance(r, list) and len(r) >= 3]
    points = [p for p in (points_merc or []) if isinstance(p, list) and len(p) >= 2]
    if not rings and not points:
        return {"rings_merc": [], "error_m": None, "anchored_by": "",
                "problem": "участков проекта на карте нет — форму не к чему привязать"}
    every = [p for r in rings for p in r] + points
    cx = (min(p[0] for p in every) + max(p[0] for p in every)) / 2.0
    cy = (min(p[1] for p in every) + max(p[1] for p in every)) / 2.0
    lat = math.degrees(2 * math.atan(math.exp(cy / 6378137.0)) - math.pi / 2)
    k = math.cos(math.radians(lat))
    local_rings = [[[(p[0] - cx) * k, (p[1] - cy) * k] for p in r] for r in rings]
    samples = [s for r in local_rings for s in _samples(r)] \
        + [[(p[0] - cx) * k, (p[1] - cy) * k] for p in points]
    sx = np.array([s[0] for s in samples])
    sy = np.array([s[1] for s in samples])
    radius = max(math.hypot(*p) for p in shape) + max(float(np.hypot(sx, sy).max()), 1.0)
    grid = np.arange(-radius, radius + ANCHOR_STEP_M, ANCHOR_STEP_M)
    tx, ty = np.meshgrid(grid, grid)
    tx, ty = tx.ravel(), ty.ravel()
    # Форма, сдвинутая на t, накрывает точку s ⇔ s − t внутри формы.
    inside = _inside_many(sx[None, :] - tx[:, None], sy[None, :] - ty[:, None], shape)
    cover = inside.mean(axis=1)
    best = float(cover.max())
    if best < ANCHOR_COVER_MIN:
        return {"rings_merc": [], "error_m": None, "anchored_by": "",
                "problem": (f"участки проекта не ложатся внутрь обводки с картинки "
                            f"(внутри — не больше {round(best * 100)}% их площади): похоже, "
                            "картинка про другую территорию или участки найдены не те")}
    keep = cover >= best - ANCHOR_COVER_SLACK
    fx, fy = tx[keep], ty[keep]
    by = "по участкам проекта"
    keys = {_street_key(a) for a in addresses or [] if _street_key(a)}
    near_street = ""
    for street in streets or []:
        key = _street_key(street.get("name"))
        line = street.get("line_m") or []
        if not key or key not in keys or len(line) < 2:
            continue
        # Улица — в координатах формы; участок у улицы: расстояние от точек
        # участков до линии улицы при сдвиге t — от (s − t) до линии.
        dist = np.full(fx.shape, np.inf)
        for s0, s1 in zip(sx, sy):
            dist = np.minimum(dist, _distance_to_segment(s0 - fx, s1 - fy, line[0], line[1]))
        close = dist <= float(dist.min()) + STREET_SLACK_M
        fx, fy = fx[close], fy[close]
        near_street = str(street.get("name") or "").strip()
        by = f"по участкам проекта и улице «{near_street}» на снимке"
        break
    mx, my = float(fx.mean()), float(fy.mean())
    error = max(ANCHOR_ERROR_FLOOR_M, float(np.hypot(fx - mx, fy - my).max()) + ANCHOR_STEP_M)
    ring = [[cx + (x + mx) / k, cy + (y + my) / k] for x, y in shape]
    return {"rings_merc": [ring], "error_m": round(error / 5.0) * 5 or 5, "anchored_by": by,
            "problem": "", "cover": round(best, 3)}


# --- целиком --------------------------------------------------------------------------

def from_photo(data: bytes, area_sqm: float | None, ask: Callable[[dict[str, Any]], str] | None,
               *, model: str, read_area: Callable[[str], float | None] | None = None,
               rings_merc: list[list[list[float]]] | None = None,
               points_merc: list[list[float]] | None = None,
               addresses: list[str] | None = None) -> dict[str, Any]:
    """Картинка решения без координат → форма территории и, если вышло, место на карте.

    `ask(payload) -> текст ответа` — единый маршрут модели движка. Ответ:
    `status` ready/failed; `shape_m` — форма на местности; `rings_merc` —
    привязанное кольцо (пусто — не привязалось, причина в `map_problem`);
    `area_text` — фраза модели с площадью: по ней (`read_area`) берётся площадь,
    когда её не нашёл распознаватель текста.
    """
    if ask is None:
        return {"status": "failed", "problem": "Платон не подключён — обводить картинку некому"}
    try:
        jpeg, pixels = prepare_image(data)
    except Exception as exc:  # noqa: BLE001 — непрочитанная картинка называется
        return {"status": "failed", "problem": f"картинка не прочитана: {type(exc).__name__}"}
    height, width = pixels.shape[:2]
    try:
        text = ask(outline_request(jpeg, width, height, model))
        answer = json.loads(text)
    except ValueError:
        return {"status": "failed", "problem": "ответ Платона — не JSON по схеме"}
    except Exception as exc:  # noqa: BLE001 — отказ модели называется
        detail = getattr(exc, "detail", None) or f"{type(exc).__name__}: {exc}"
        return {"status": "failed", "problem": f"Платон недоступен: {detail}"[:300]}
    if not isinstance(answer, dict):
        return {"status": "failed", "problem": "ответ Платона — не JSON по схеме"}
    area_text = str(answer.get("area_text") or "")
    ring, problem = check_outline(answer, pixels)
    if problem:
        return {"status": "failed", "problem": problem, "area_text": area_text}
    if not area_sqm and read_area is not None:
        area_sqm = read_area(area_text)
    if not area_sqm:
        return {"status": "failed", "problem": "площадь территории не найдена в тексте решения",
                "area_text": area_text}
    north = float(answer.get("north_deg") or 0.0)
    shape, k, centre = shape_metres(ring, float(area_sqm), north)
    streets = []
    for street in answer.get("streets") or []:
        line = _points((street or {}).get("points_px"))
        if len(line) >= 2:
            streets.append({"name": str(street.get("name") or "")[:80],
                            "line_m": _to_ground(line[:2], k, centre, north)})
    placed = anchor(shape, rings_merc=rings_merc, points_merc=points_merc,
                    streets=streets, addresses=addresses)
    return {"status": "ready", "shape_m": [[[round(x, 2), round(y, 2)] for x, y in shape]],
            "rings_merc": placed["rings_merc"], "anchor_error_m": placed["error_m"],
            "anchored_by": placed["anchored_by"], "map_problem": placed["problem"],
            "corners": len(ring), "metres_per_px": round(k, 3), "area_text": area_text,
            "streets": [s["name"] for s in streets]}
