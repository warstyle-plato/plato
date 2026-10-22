"""Объёмная схема застройки: корпуса на участке и их аксонометрия.

Решение владельца (22.10.2026, AskUserQuestion): корпуса раскладываются по
очередям, пятно очереди пропорционально её наземной ГНС; очередь выше предела
этажности участка (`max_storeys_allowed`, без него — 25 этажей) делится на
несколько корпусов. Корпуса ложатся рядами в прямоугольник внутри участка без
отступов; реальный генплан расчёт не угадывает.

Один источник для страницы и PDF: `site_massing_layout` даёт корпуса (очередь,
площадь, этажность, прямоугольник в метрах, у каждого значения — происхождение),
`site_massing_axonometry` — те же корпуса готовыми многоугольниками картинки.
Страница и PDF только рисуют многоугольники, сами ничего не раскладывают.

Не самостоятельный модуль: `main_legacy.py` выполняет файл в пространстве
имён движка (`_engine_part("site_massing_layout")`).
"""
# ruff: noqa

import math as _math

# Порог этажности корпуса, когда предел участка не задан (владелец 22.10.2026),
# — тот же, что у пятна застройки (`STOREYS_LIMIT_DEFAULT`).
LAYOUT_STOREYS_LIMIT_DEFAULT = STOREYS_LIMIT_DEFAULT
# Ширина корпуса, к которой тянется раскладка (типовая жилая секция), и разрывы
# между корпусами в ряду и между рядами (проезд и пожарный разрыв), м.
LAYOUT_CORPUS_DEPTH_M = 18.0
LAYOUT_GAP_IN_ROW_M = 12.0
LAYOUT_GAP_BETWEEN_ROWS_M = 15.0
# Самый длинный корпус; длиннее — очередь делится на корпуса по длине.
LAYOUT_CORPUS_MAX_LENGTH_M = 100.0
# Высота этажа только для картинки: этажность считает ТЭП, не она.
LAYOUT_STOREY_HEIGHT_M = 3.0
# Цвета очередей: одна палитра для страницы и PDF.
LAYOUT_PHASE_COLORS = ("#2f6fb3", "#d9822b", "#3f9a5b", "#9b59b6", "#c0392b", "#16a2a2")


def _ring_area(ring: list[list[float]]) -> float:
    """Площадь кольца со знаком: плюс — против часовой стрелки."""
    total = 0.0
    for i in range(len(ring)):
        x1, y1 = ring[i]
        x2, y2 = ring[(i + 1) % len(ring)]
        total += x1 * y2 - x2 * y1
    return total / 2.0


def _clean_ring(ring: list[list[float]], tol: float = 0.3) -> list[list[float]]:
    """Без повтора первой точки и без точек ближе `tol` к предыдущей."""
    out: list[list[float]] = []
    for p in ring:
        if out and _math.hypot(p[0] - out[-1][0], p[1] - out[-1][1]) < tol:
            continue
        out.append([float(p[0]), float(p[1])])
    while len(out) > 2 and _math.hypot(out[0][0] - out[-1][0], out[0][1] - out[-1][1]) < tol:
        out.pop()
    return out


def _inside(point: tuple[float, float], rings: list[list[list[float]]]) -> bool:
    """Точка внутри хотя бы одного кольца (правило чётности)."""
    px, py = point
    for ring in rings:
        hit = False
        j = len(ring) - 1
        for i in range(len(ring)):
            xi, yi = ring[i]
            xj, yj = ring[j]
            if (yi > py) != (yj > py) and px < (xj - xi) * (py - yi) / (yj - yi) + xi:
                hit = not hit
            j = i
        if hit:
            return True
    return False


def inset_ring(ring: list[list[float]], distance: float) -> list[list[float]]:
    """Кольцо, сдвинутое внутрь на `distance` м (отступ от границ).

    Каждая сторона сдвигается параллельно себе, вершина — пересечение соседних
    сдвинутых сторон; на остром углу вершина не уходит дальше трёх отступов.
    Слишком узкий участок (кольцо вывернулось) — пустой список.
    """
    ring = _clean_ring(ring)
    if len(ring) < 3 or distance <= 0:
        return [list(p) for p in ring]
    sign = 1.0 if _ring_area(ring) > 0 else -1.0
    count = len(ring)
    lines = []
    for i in range(count):
        (x1, y1), (x2, y2) = ring[i], ring[(i + 1) % count]
        length = _math.hypot(x2 - x1, y2 - y1) or 1.0
        nx, ny = -(y2 - y1) / length * sign, (x2 - x1) / length * sign
        lines.append(((x1 + nx * distance, y1 + ny * distance),
                      (x2 + nx * distance, y2 + ny * distance)))
    out: list[list[float]] = []
    for i in range(count):
        (a1, a2), (b1, b2) = lines[i - 1], lines[i]
        dax, day = a2[0] - a1[0], a2[1] - a1[1]
        dbx, dby = b2[0] - b1[0], b2[1] - b1[1]
        den = dax * dby - day * dbx
        if abs(den) < 1e-9:
            point = [b1[0], b1[1]]
        else:
            t = ((b1[0] - a1[0]) * dby - (b1[1] - a1[1]) * dbx) / den
            point = [a1[0] + t * dax, a1[1] + t * day]
        vx, vy = ring[i]
        far = _math.hypot(point[0] - vx, point[1] - vy)
        if far > 3 * distance:
            k = 3 * distance / far
            point = [vx + (point[0] - vx) * k, vy + (point[1] - vy) * k]
        out.append(point)
    if _ring_area(out) * sign <= 0:
        return []
    return out


def _largest_rectangle(rings: list[list[list[float]]]) -> tuple[float, float, float, float] | None:
    """Наибольший прямоугольник по осям внутри колец → (x0, y0, x1, y1).

    Участок растрируется сеткой ~80 клеток по большей стороне; наибольший
    прямоугольник из клеток внутри — по гистограмме строк.
    """
    points = [p for ring in rings for p in ring]
    if not points:
        return None
    min_x, max_x = min(p[0] for p in points), max(p[0] for p in points)
    min_y, max_y = min(p[1] for p in points), max(p[1] for p in points)
    step = max(max_x - min_x, max_y - min_y) / 80.0
    if step <= 0:
        return None
    cols = max(1, int(_math.ceil((max_x - min_x) / step)))
    rows = max(1, int(_math.ceil((max_y - min_y) / step)))
    heights = [0] * cols
    best = (0.0, None)
    for r in range(rows):
        cy = min_y + (r + 0.5) * step
        for c in range(cols):
            inside = _inside((min_x + (c + 0.5) * step, cy), rings)
            heights[c] = heights[c] + 1 if inside else 0
        stack: list[int] = []
        for c in range(cols + 1):
            h = heights[c] if c < cols else 0
            while stack and heights[stack[-1]] >= h:
                top = stack.pop()
                left = stack[-1] + 1 if stack else 0
                area = heights[top] * (c - left)
                if area > best[0]:
                    best = (area, (left, r - heights[top] + 1, c, r + 1))
            stack.append(c)
    if best[1] is None:
        return None
    c0, r0, c1, r1 = best[1]
    return (min_x + c0 * step, min_y + r0 * step, min_x + c1 * step, min_y + r1 * step)


def _site_rings_m(x: dict[str, Any]) -> tuple[list[list[list[float]]], dict[str, float]]:
    """Контур участка из ЕГРН (`_land_lookup`) в метрах от его центра → (кольца, рамка).

    Кольца приходят в веб-меркаторе: метр в нём растянут на 1/cos(широты),
    поэтому координаты умножаются на cos(широты центра). Рамка — центр и
    множитель: по ней корпуса возвращаются в меркатор для карты участка.
    """
    lookup = x.get("_land_lookup") or {}
    items = lookup.get("results") if isinstance(lookup, dict) else None
    if not isinstance(items, list):
        items = [lookup] if isinstance(lookup, dict) else []
    rings = [ring for item in items
             if isinstance(item, dict) and item.get("found", True)
             for ring in (item.get("contour_merc") or [])
             if isinstance(ring, list) and len(ring) >= 3]
    if not rings:
        return [], {}
    xs = [p[0] for ring in rings for p in ring]
    ys = [p[1] for ring in rings for p in ring]
    cx, cy = (min(xs) + max(xs)) / 2.0, (min(ys) + max(ys)) / 2.0
    lat = _math.degrees(2 * _math.atan(_math.exp(cy / 6378137.0)) - _math.pi / 2)
    k = _math.cos(_math.radians(lat))
    out = [_clean_ring([[(p[0] - cx) * k, (p[1] - cy) * k] for p in ring]) for ring in rings]
    return [ring for ring in out if len(ring) >= 3], {"cx": cx, "cy": cy, "k": k}


def _rotate(rings: list[list[list[float]]], angle: float) -> list[list[list[float]]]:
    c, s = _math.cos(angle), _math.sin(angle)
    return [[[p[0] * c - p[1] * s, p[0] * s + p[1] * c] for p in ring] for ring in rings]


def _main_direction(rings: list[list[list[float]]]) -> float:
    """Угол самой длинной стороны большого кольца: корпуса ставятся вдоль неё."""
    ring = max(rings, key=lambda r: abs(_ring_area(r)))
    best, angle = 0.0, 0.0
    for i in range(len(ring)):
        (x1, y1), (x2, y2) = ring[i], ring[(i + 1) % len(ring)]
        length = _math.hypot(x2 - x1, y2 - y1)
        if length > best:
            best, angle = length, _math.atan2(y2 - y1, x2 - x1)
    return angle


def _phase_corpora(phases: list[dict[str, Any]], footprint: float, limit: float,
                   footprint_origin: str) -> list[dict[str, Any]]:
    """Корпуса очередей: пятно ∝ наземной ГНС, этажность ≤ предела, длина ≤ 100 м."""
    total = sum(max(0.0, float(p.get("above_gns_sqm") or 0.0)) for p in phases)
    if total <= 0 or footprint <= 0:
        return []
    out: list[dict[str, Any]] = []
    for p in phases:
        gns = max(0.0, float(p.get("above_gns_sqm") or 0.0))
        if gns <= 0:
            continue
        spot = footprint * gns / total
        storeys = gns / spot
        split_by_height = storeys > limit + 1e-9
        if split_by_height:
            # Выше предела: корпуса по пределу, пятно очереди растёт до ГНС ÷ предел,
            # и корпусов у очереди не меньше двух.
            parts = 2
            spot, storeys = gns / limit, limit
        else:
            parts = 1
        longest = LAYOUT_CORPUS_DEPTH_M * LAYOUT_CORPUS_MAX_LENGTH_M
        parts = max(parts, int(_math.ceil(spot / longest - 1e-9)))
        for j in range(parts):
            out.append({
                "phase": int(p.get("phase") or 1), "phase_name": str(p.get("name") or ""),
                "corpus": j + 1, "corpora_in_phase": parts,
                "area_sqm": spot / parts,
                "area_origin": "manual" if footprint_origin == "manual" and not split_by_height
                else "estimate",
                "storeys": storeys, "storeys_shown": int(_math.floor(storeys + 0.5)),
                "storeys_origin": "limit" if split_by_height else "estimate",
                "above_gns_sqm": gns / parts,
            })
    return out


def _pack_rows(corpora: list[dict[str, Any]], width: float, height: float) -> float:
    """Раскладка рядами в прямоугольник W×H; → во сколько раз корпуса пришлось уменьшить.

    Число рядов — то, при котором корпуса помещаются и ширина ряда ближе всего
    к ширине секции. Не помещаются ни при каком числе — уменьшаются все поровну,
    и схема об этом говорит.
    """
    count = len(corpora)
    best = None
    for rows in range(1, count + 1):
        slot = (height - (rows - 1) * LAYOUT_GAP_BETWEEN_ROWS_M) / rows
        if slot <= 1:
            break
        groups = [corpora[round(i * count / rows):round((i + 1) * count / rows)] for i in range(rows)]
        overflow, depths = 1.0, []
        for group in groups:
            room = width - (len(group) - 1) * LAYOUT_GAP_IN_ROW_M
            area = sum(c["area_sqm"] for c in group)
            depth = min(slot, max(LAYOUT_CORPUS_DEPTH_M, area / room if room > 0 else slot))
            depths.append(depth)
            need = area / depth
            if room <= 0:
                overflow = max(overflow, 10.0)
            else:
                overflow = max(overflow, need / room, area / (slot * room))
        score = (round(overflow, 3) if overflow > 1.0 else 1.0,
                 sum(abs(d - LAYOUT_CORPUS_DEPTH_M) for d in depths))
        if best is None or score < best[0]:
            best = (score, rows, slot, groups)
    if best is None:
        return 1.0
    (overflow, _), rows, slot, groups = best
    shrink = _math.sqrt(overflow) if overflow > 1.0 else 1.0
    for r, group in enumerate(groups):
        room = width - (len(group) - 1) * LAYOUT_GAP_IN_ROW_M
        area = sum(c["area_sqm"] for c in group) / shrink ** 2
        depth = min(slot, max(LAYOUT_CORPUS_DEPTH_M, area / room if room > 0 else slot))
        lengths = [c["area_sqm"] / shrink ** 2 / depth for c in group]
        used = sum(lengths) + (len(group) - 1) * LAYOUT_GAP_IN_ROW_M
        x0 = (width - used) / 2.0
        y0 = r * (slot + LAYOUT_GAP_BETWEEN_ROWS_M) + (slot - depth) / 2.0
        for c, length in zip(group, lengths):
            c["rect_m"] = [round(x0, 2), round(y0, 2), round(x0 + length, 2), round(y0 + depth, 2)]
            x0 += length + LAYOUT_GAP_IN_ROW_M
    return shrink


def site_massing_layout(x: dict[str, Any], massing: dict[str, Any],
                        phases: list[dict[str, Any]]) -> dict[str, Any]:
    """Корпуса на участке → {site, buildings, …}; координаты — метры схемы.

    `phases` — [{"phase": 1, "name": "…", "above_gns_sqm": …}]; проект без
    очередей — одна запись. Схема повёрнута так, что самая длинная сторона
    участка идёт вдоль оси x.
    """
    site_sqm = float(massing.get("site_sqm") or 0.0)
    footprint = float(massing.get("footprint_sqm") or 0.0)
    setback = float(massing.get("setback_m") or 0.0)
    given_limit = float(massing.get("max_storeys_allowed") or 0.0)
    limit = given_limit if given_limit > 0 else float(LAYOUT_STOREYS_LIMIT_DEFAULT)
    notes: list[str] = []

    rings, frame = _site_rings_m(x)
    if rings:
        shape_origin = "contour"
        frame["angle"] = _main_direction(rings)
        rings = _rotate(rings, -frame["angle"])
        contour_sqm = sum(abs(_ring_area(r)) for r in rings)
        if site_sqm > 0 and abs(contour_sqm - site_sqm) > 0.25 * site_sqm:
            notes.append(f"Площадь контура из ЕГРН ({_fmt_ru(contour_sqm)} м²) заметно отличается "
                         f"от площади участка в расчёте ({_fmt_ru(site_sqm)} м²). Схема нарисована "
                         "по контуру, а числа взяты из расчёта.")
    elif site_sqm > 0:
        shape_origin = "square"
        half = _math.sqrt(site_sqm) / 2.0
        rings = [[[-half, -half], [half, -half], [half, half], [-half, half]]]
        notes.append("Контура участка из ЕГРН нет, поэтому участок показан квадратом той же площади.")
    else:
        return {"buildings": [], "site_rings": [], "notes": [], "storeys_limit": limit}

    inner = [r for r in (inset_ring(ring, setback) for ring in rings) if len(r) >= 3]
    rect = _largest_rectangle(inner or rings)
    corpora = _phase_corpora(phases, footprint, limit,
                             str(massing.get("footprint_origin") or "estimate"))
    shrink = 1.0
    if rect and corpora:
        x0, y0, x1, y1 = rect
        shrink = _pack_rows(corpora, x1 - x0, y1 - y0)
        for c in corpora:
            r = c["rect_m"]
            c["rect_m"] = [round(r[0] + x0, 2), round(r[1] + y0, 2),
                           round(r[2] + x0, 2), round(r[3] + y0, 2)]
            c["rect_origin"] = "schema"
            if frame:
                c["ring_merc"] = _to_merc(c["rect_m"], frame)
    if shrink > 1.0001:
        notes.append("Корпуса такой площади не помещаются на участке рядами, поэтому на схеме "
                     f"они уменьшены в {_fmt_ru(shrink ** 2, 1)} раза. Площади и этажность "
                     "в подписях — настоящие.")
    if any(c["storeys_origin"] == "limit" for c in corpora):
        spot = sum(c["area_sqm"] for c in corpora)
        notes.append(f"Этажность выше предела ({_fmt_ru(limit)} этажей"
                     f"{'' if given_limit > 0 else ', предел участка не задан, взят порог'}), "
                     f"поэтому очереди разделены на корпуса не выше предела. Пятно корпусов — "
                     f"{_fmt_ru(spot)} м², это больше пятна застройки в расчёте ({_fmt_ru(footprint)} м²).")
    for c in corpora:
        name = f"Очередь {c['phase']}" if len(phases) > 1 else "Здание"
        corpus = f", корпус {c['corpus']}" if c["corpora_in_phase"] > 1 else ""
        c["label"] = f"{name}{corpus}, {_storeys_word(c['storeys_shown'])}"
    return {
        "site_rings": [[[round(p[0], 2), round(p[1], 2)] for p in r] for r in rings],
        "site_shape_origin": shape_origin,
        "underground_rings": [[[round(p[0], 2), round(p[1], 2)] for p in r] for r in inner],
        "setback_m": setback,
        "storeys_limit": limit,
        "storeys_limit_origin": "manual" if given_limit > 0 else "default",
        "schema_shrink": shrink,
        "underground_levels": int(massing.get("underground_levels") or 0),
        # Уровни под землёй — те же, по которым взята ставка: площадь уровня и
        # полезная площадь одного уровня в контуре.
        "underground_level_rows": [{"level": int(r.get("level") or 0),
                                    "area_sqm": float(r.get("area_sqm") or 0.0)}
                                   for r in massing.get("underground_level_rows") or []],
        "underground_level_capacity_sqm": float(massing.get("underground_contour_sqm") or 0.0)
        * float(massing.get("underground_use_factor") or 0.0),
        "buildings": corpora,
        "notes": notes,
    }


def _to_merc(rect: list[float], frame: dict[str, float]) -> list[list[float]]:
    """Прямоугольник схемы → кольцо в метрах веб-меркатора (карта участка).

    Обратное к `_site_rings_m` и повороту схемы: поворот назад, деление на
    cos(широты), сдвиг к центру контура.
    """
    x0, y0, x1, y1 = rect
    c, s = _math.cos(frame["angle"]), _math.sin(frame["angle"])
    out = []
    for px, py in ((x0, y0), (x1, y0), (x1, y1), (x0, y1)):
        rx, ry = px * c - py * s, px * s + py * c
        out.append([round(frame["cx"] + rx / frame["k"], 2), round(frame["cy"] + ry / frame["k"], 2)])
    return out


def _storeys_word(count: int) -> str:
    tail = count % 100
    if 11 <= tail <= 14:
        word = "этажей"
    elif count % 10 == 1:
        word = "этаж"
    elif 2 <= count % 10 <= 4:
        word = "этажа"
    else:
        word = "этажей"
    return f"{count} {word}"


def _levels_word(count: int) -> str:
    words = {1: "один подземный уровень", 2: "два подземных уровня", 3: "три подземных уровня",
             4: "четыре подземных уровня"}
    return words.get(count, f"{count} подземных уровней")


def _shade(color: str, factor: float) -> str:
    r, g, b = (int(color[i:i + 2], 16) for i in (1, 3, 5))
    if factor >= 1:
        r, g, b = (int(v + (255 - v) * (factor - 1)) for v in (r, g, b))
    else:
        r, g, b = (int(v * factor) for v in (r, g, b))
    return f"#{max(0, min(255, r)):02x}{max(0, min(255, g)):02x}{max(0, min(255, b)):02x}"


def site_massing_axonometry(layout: dict[str, Any]) -> dict[str, Any]:
    """Корпуса раскладки → многоугольники изометрии для страницы и PDF.

    Экран: X = (x − y)·cos30°, Y = −(x + y)·sin30° − z (ось Y вниз, как в SVG).
    Ближние к зрителю корпуса рисуются последними. Номер в кружке на крыше —
    номер строки в легенде.
    """
    buildings = layout.get("buildings") or []
    site = layout.get("site_rings") or []
    if not site:
        return {}
    cos30, sin30 = _math.cos(_math.pi / 6), 0.5

    def project(px: float, py: float, pz: float = 0.0) -> list[float]:
        return [round((px - py) * cos30, 2), round(-(px + py) * sin30 - pz, 2)]

    shapes: list[dict[str, Any]] = []
    texts: list[dict[str, Any]] = []
    under = [r for r in layout.get("underground_rings") or [] if len(r) >= 3]
    rows = layout.get("underground_level_rows") or []
    capacity = float(layout.get("underground_level_capacity_sqm") or 0.0)
    h = LAYOUT_STOREY_HEIGHT_M
    # Подземные уровни — плиты под участком, раздвинутые по высоте, чтобы
    # каждая была видна: шаг — не меньше двух этажей и около пятой части
    # размера подземного контура. Плита неполного уровня сжата к центру по
    # своей площади. Земля над ними полупрозрачная.
    inner_pts = [p for ring in under for p in ring]
    extent = max((max(p[i] for p in inner_pts) - min(p[i] for p in inner_pts) for i in (0, 1)),
                 default=0.0)
    step = max(2 * h, 0.2 * extent)
    for row in sorted(rows, key=lambda r: r["level"]):
        depth = abs(int(row["level"]))
        z_top = -depth * step + h
        z_bottom = z_top - h
        share = min(1.0, row["area_sqm"] / capacity) if capacity > 0 else 1.0
        k = _math.sqrt(share)
        fill = _shade("#a89f8f", 1.0 + 0.12 * (depth - 1))
        for ring in under:
            cx = sum(p[0] for p in ring) / len(ring)
            cy = sum(p[1] for p in ring) / len(ring)
            level_ring = [[cx + (p[0] - cx) * k, cy + (p[1] - cy) * k] for p in ring]
            sign = 1.0 if _ring_area(level_ring) > 0 else -1.0
            for i in range(len(level_ring)):
                (ax, ay), (bx, by) = level_ring[i], level_ring[(i + 1) % len(level_ring)]
                # Наружная нормаль стороны смотрит к зрителю (к малым x + y).
                nx, ny = (by - ay) * sign, -(bx - ax) * sign
                if nx + ny >= 0:
                    continue
                shapes.append({"kind": "underground_wall", "level": row["level"],
                               "points": [project(ax, ay, z_top), project(bx, by, z_top),
                                          project(bx, by, z_bottom), project(ax, ay, z_bottom)],
                               "fill": _shade(fill, 0.8 if abs(nx) > abs(ny) else 0.66),
                               "stroke": "#6f6759", "width": 0.6})
            shapes.append({"kind": "underground_level", "level": row["level"],
                           "points": [project(px, py, z_top) for px, py in level_ring],
                           "fill": _shade(fill, 1.35), "stroke": "#6f6759", "width": 0.6})
        front = min(inner_pts, key=lambda p: p[0] - p[1], default=None)
        if front:
            tx, ty = project(front[0], front[1], z_top - h / 2)
            texts.append({"x": tx, "y": ty, "anchor": "end", "level": row["level"],
                          "text": f"−{depth}: {_fmt_ru(row['area_sqm'])} м²"})
    for ring in site:
        shapes.append({"kind": "site", "points": [project(*p) for p in ring],
                       "fill": "#f3f4ee", "stroke": "#6c8a52", "width": 1.2,
                       "opacity": 0.6 if texts else 1.0})
    for ring in under:
        shapes.append({"kind": "underground", "points": [project(*p) for p in ring],
                       "fill": "#dbe7cd", "stroke": "#55606b", "width": 1.0, "dash": [5, 4],
                       "opacity": 0.6 if texts else 1.0})
    labels: list[dict[str, Any]] = []
    order = sorted(range(len(buildings)),
                   key=lambda i: -((buildings[i]["rect_m"][0] + buildings[i]["rect_m"][2])
                                   + (buildings[i]["rect_m"][1] + buildings[i]["rect_m"][3])))
    for number, b in enumerate(buildings, 1):
        b["number"] = number
    for i in order:
        b = buildings[i]
        x0, y0, x1, y1 = b["rect_m"]
        h = b["storeys_shown"] * LAYOUT_STOREY_HEIGHT_M
        color = LAYOUT_PHASE_COLORS[(b["phase"] - 1) % len(LAYOUT_PHASE_COLORS)]
        # Видны крыша и две стены, обращённые к зрителю: у малого x и у малого y.
        faces = (
            ("wall", [project(x0, y0, 0), project(x1, y0, 0), project(x1, y0, h), project(x0, y0, h)], 0.78),
            ("wall", [project(x0, y0, 0), project(x0, y1, 0), project(x0, y1, h), project(x0, y0, h)], 0.62),
            ("roof", [project(x0, y0, h), project(x1, y0, h), project(x1, y1, h), project(x0, y1, h)], 1.25),
        )
        for kind, points, factor in faces:
            shapes.append({"kind": kind, "points": points, "fill": _shade(color, factor),
                           "stroke": _shade(color, 0.45), "width": 0.6,
                           "building": b["number"], "phase": b["phase"]})
        cx, cy = project((x0 + x1) / 2, (y0 + y1) / 2, h)
        labels.append({"x": cx, "y": cy, "text": str(b["number"]), "building": b["number"]})
    xs = [p[0] for s in shapes for p in s["points"]]
    ys = [p[1] for s in shapes for p in s["points"]]
    size = max(max(xs) - min(xs), max(ys) - min(ys), 1.0)
    font = round(0.045 * size, 2)
    last_y = None
    for t in sorted(texts, key=lambda t: -t["level"]):
        # Подпись уровня стоит левее стены, подписи не наезжают друг на друга;
        # место под них входит в рамку.
        t["x"] = round(t["x"] - 0.4 * font, 2)
        t["y"] = t["y"] + 0.35 * font
        if last_y is not None and t["y"] < last_y + 1.2 * font:
            t["y"] = last_y + 1.2 * font
        last_y = t["y"]
        t["y"] = round(t["y"], 2)
        xs.append(t["x"] - 0.56 * font * len(t["text"]))
        ys.extend([t["y"] - font, t["y"] + 0.3 * font])
    pad = 0.04 * size
    legend = [{"number": b["number"], "phase": b["phase"], "text": b["label"],
               "line": f"{b['number']} — {b['label']}, пятно {_fmt_ru(b['area_sqm'])} м²",
               "area_sqm": b["area_sqm"],
               "color": LAYOUT_PHASE_COLORS[(b["phase"] - 1) % len(LAYOUT_PHASE_COLORS)]}
              for b in buildings]
    levels = int(layout.get("underground_levels") or 0)
    caption = ("Зелёное — участок без отступов, светлая полоса вдоль границ — отступ, пунктир — "
               "граница подземной части. "
               + (f"Под участком — {_levels_word(levels)} с площадью каждого; по высоте они "
                  "раздвинуты, чтобы был виден каждый. " if texts else "")
               + "Корпуса окрашены по очередям, номер на крыше — номер строки в списке под схемой.")
    footer = ("Корпуса расставлены рядами для наглядности: реальный генплан расчёт не угадывает. "
              f"Высота на схеме — по {_fmt_ru(LAYOUT_STOREY_HEIGHT_M)} м на этаж.")
    return {"caption": caption, "footer": footer,
            "viewbox": [round(min(xs) - pad, 2), round(min(ys) - pad, 2),
                        round(max(xs) - min(xs) + 2 * pad, 2), round(max(ys) - min(ys) + 2 * pad, 2)],
            "shapes": shapes, "labels": labels, "legend": legend, "texts": texts,
            "font_size": font,
            "label_radius": round(0.032 * max(max(xs) - min(xs), max(ys) - min(ys)), 2)}


def site_massing_scheme(x: dict[str, Any], massing: dict[str, Any],
                        phases: list[dict[str, Any]]) -> dict[str, Any]:
    """Раскладка и картинка одним ответом: `tep.site_massing.scheme`."""
    layout = site_massing_layout(x, massing, phases)
    if not layout.get("buildings"):
        return {"layout": layout, "axonometry": {}}
    return {"layout": layout, "axonometry": site_massing_axonometry(layout)}
