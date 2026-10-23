"""Кварталы участка, фронты застройки и расстановка корпусов по ним.

Решение владельца (23.10.2026, AskUserQuestion): корпуса стоят не одной сеткой
на весь участок, а по кварталам — секциями по периметру квартала вдоль границ,
замыкая двор, как на схемах города в документах КРТ. Полоса режется на
кварталы поперёк своей оси; у каждого квартала свои фронты (стороны, вдоль
которых встают секции глубиной 18 м), свой поворот и свой двор.

Здесь только геометрия, одна для обеих расстановок:
- `massing_blocks` — кварталы и фронты (их же получает Платон, когда предлагает
  план, `engine/site_massing_plan.py`);
- `massing_place_engine` — запасная расстановка движка: очереди подряд вдоль
  полосы, отдельные здания — в самых широких кварталах;
- `massing_place_plan` — корпуса по плану Платона, построенные движком;
- `massing_check` — проверка, общая для обеих: корпус внутри участка без
  отступов, не ближе разрыва к соседу, площадь та же, что в расчёте.

Не самостоятельный модуль: `main_legacy.py` выполняет файл в пространстве
имён движка (`_engine_part("site_massing_blocks")`).
"""
# ruff: noqa

import math as _math

# Длина квартала вдоль полосы и ширина проезда между кварталами, м.
LAYOUT_BLOCK_LENGTH_M = 250.0
LAYOUT_BLOCK_STREET_M = 20.0
# Фронт короче этого секцию не держит; точность упрощения контура, м.
LAYOUT_FRONT_MIN_M = 20.0
LAYOUT_FRONT_TOLERANCE_M = 2.5
# Шаг, с которым корпус ищет место вдоль фронта, м.
LAYOUT_FRONT_STEP_M = 3.0
# Участок длиннее ширины во столько раз — полоса: режется на кварталы и
# на схеме идёт слева направо.
LAYOUT_STRIP_ASPECT = 4.0
# Башня — корпус на углу квартала квадратного пятна, когда он заметно выше
# остальных корпусов проекта.
LAYOUT_TOWER_RATIO = 1.3
LAYOUT_TOWER_SIDE_MAX_M = 40.0


def _ring_moments(rings: list[list[list[float]]]) -> tuple[float, float, float, float]:
    """Центр и угол главной оси колец (по моментам площади) → (cx, cy, angle, area)."""
    area = sx = sy = 0.0
    for ring in rings:
        a = _ring_area(ring)
        sign = 1.0 if a >= 0 else -1.0
        for i in range(len(ring)):
            (x1, y1), (x2, y2) = ring[i], ring[(i + 1) % len(ring)]
            cross = (x1 * y2 - x2 * y1) * sign
            area += cross / 2.0
            sx += (x1 + x2) * cross / 6.0
            sy += (y1 + y2) * cross / 6.0
    if area <= 0:
        return 0.0, 0.0, 0.0, 0.0
    cx, cy = sx / area, sy / area
    ixx = iyy = ixy = 0.0
    for ring in rings:
        sign = 1.0 if _ring_area(ring) >= 0 else -1.0
        for i in range(len(ring)):
            x1, y1 = ring[i][0] - cx, ring[i][1] - cy
            x2, y2 = ring[(i + 1) % len(ring)][0] - cx, ring[(i + 1) % len(ring)][1] - cy
            cross = (x1 * y2 - x2 * y1) * sign
            ixx += (y1 * y1 + y1 * y2 + y2 * y2) * cross / 12.0
            iyy += (x1 * x1 + x1 * x2 + x2 * x2) * cross / 12.0
            ixy += (x1 * y2 + 2 * x1 * y1 + 2 * x2 * y2 + x2 * y1) * cross / 24.0
    # Главная ось — направление наибольшего разброса точек вдоль неё.
    angle = 0.5 * _math.atan2(2 * ixy, iyy - ixx)
    return cx, cy, angle, area


def massing_strip_axis(rings: list[list[list[float]]]) -> dict[str, float] | None:
    """Ось участка: угол, длина вдоль неё и средняя ширина; полоса ли это."""
    cx, cy, angle, area = _ring_moments(rings)
    if area <= 0:
        return None
    ux, uy = _math.cos(angle), _math.sin(angle)
    proj = [(p[0] - cx) * ux + (p[1] - cy) * uy for ring in rings for p in ring]
    length = max(proj) - min(proj)
    width = area / length if length > 0 else 0.0
    return {"angle": angle, "length": length, "width": width, "cx": cx, "cy": cy,
            "strip": width > 0 and length / width >= LAYOUT_STRIP_ASPECT}


def _clip_half(ring: list[list[float]], ux: float, uy: float, c: float,
               keep_above: bool) -> list[list[float]]:
    """Часть кольца по одну сторону прямой u·p = c (Сазерленд — Ходжман)."""
    def side(p):
        v = p[0] * ux + p[1] * uy - c
        return v if keep_above else -v
    out: list[list[float]] = []
    count = len(ring)
    for i in range(count):
        a, b = ring[i], ring[(i + 1) % count]
        sa, sb = side(a), side(b)
        if sa >= 0:
            out.append([a[0], a[1]])
        if (sa >= 0) != (sb >= 0):
            t = sa / (sa - sb)
            out.append([a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t])
    return _clean_ring(out)


def _simplify(ring: list[list[float]], tol: float) -> list[int]:
    """Номера вершин кольца после упрощения (Дуглас — Пейкер по замкнутому кольцу)."""
    count = len(ring)
    if count <= 4:
        return list(range(count))
    # Две самые далёкие вершины делят кольцо на две ломаные.
    far = max(range(count), key=lambda i: _math.hypot(ring[i][0] - ring[0][0], ring[i][1] - ring[0][1]))

    def run(i0: int, i1: int) -> list[int]:
        idx = [(i0 + k) % count for k in range((i1 - i0) % count + 1)]
        keep = {0, len(idx) - 1}
        stack = [(0, len(idx) - 1)]
        while stack:
            a, b = stack.pop()
            (x1, y1), (x2, y2) = ring[idx[a]], ring[idx[b]]
            length = _math.hypot(x2 - x1, y2 - y1) or 1e-9
            best, at = 0.0, None
            for k in range(a + 1, b):
                px, py = ring[idx[k]]
                d = abs((x2 - x1) * (y1 - py) - (x1 - px) * (y2 - y1)) / length
                if d > best:
                    best, at = d, k
            if at is not None and best > tol:
                keep.add(at)
                stack.extend([(a, at), (at, b)])
        return [idx[k] for k in sorted(keep)]

    first, second = run(0, far), run(far, 0)
    return first[:-1] + second[:-1]


def _ray_room(rings: list[list[list[float]]], px: float, py: float, nx: float, ny: float) -> float:
    """Расстояние от точки по направлению (nx, ny) до ближайшей стороны колец."""
    best = _math.inf
    for ring in rings:
        for i in range(len(ring)):
            (x1, y1), (x2, y2) = ring[i], ring[(i + 1) % len(ring)]
            ex, ey = x2 - x1, y2 - y1
            den = nx * ey - ny * ex
            if abs(den) < 1e-12:
                continue
            t = ((x1 - px) * ey - (y1 - py) * ex) / den
            s = ((x1 - px) * ny - (y1 - py) * nx) / den
            if t > 0.05 and -1e-9 <= s <= 1 + 1e-9:
                best = min(best, t)
    return best


def _fronts_of(block_id: str, ring: list[list[float]], cut_sides: set[int]) -> list[dict[str, Any]]:
    """Фронты квартала: стороны упрощённого кольца, сдвинутые внутрь настолько,
    чтобы отрезок не выходил за настоящую границу (вогнутый край дуги)."""
    sign = 1.0 if _ring_area(ring) > 0 else -1.0
    keep = _simplify(ring, LAYOUT_FRONT_TOLERANCE_M)
    fronts: list[dict[str, Any]] = []
    for k in range(len(keep)):
        i0, i1 = keep[k], keep[(k + 1) % len(keep)]
        (x1, y1), (x2, y2) = ring[i0], ring[i1]
        length = _math.hypot(x2 - x1, y2 - y1)
        if length < LAYOUT_FRONT_MIN_M:
            continue
        ux, uy = (x2 - x1) / length, (y2 - y1) / length
        nx, ny = -uy * sign, ux * sign
        # Выброшенные вершины, зашедшие внутрь от хорды, сдвигают фронт.
        shift = 0.0
        j = i0
        while j != i1:
            j = (j + 1) % len(ring)
            shift = max(shift, (ring[j][0] - x1) * nx + (ring[j][1] - y1) * ny)
        # И ещё 5 см: корпус строго внутри, а не на самой границе.
        shift = max(shift, 0.0) + 0.05
        ax, ay = x1 + nx * shift, y1 + ny * shift
        mx, my = ax + ux * length / 2, ay + uy * length / 2
        side = "street" if any(((i0 + m) % len(ring)) in cut_sides
                               for m in range((i1 - i0) % len(ring))) else "boundary"
        fronts.append({"id": f"{block_id}-Ф{len(fronts) + 1}", "block": block_id,
                       "a": [round(ax, 2), round(ay, 2)], "u": [ux, uy], "n": [nx, ny],
                       "length_m": round(length, 1), "side": side,
                       "room_m": round(min(_ray_room([ring], mx, my, nx, ny), 1e6), 1)})
    return fronts


def massing_blocks(inner: list[list[list[float]]], axis: dict[str, float] | None) -> list[dict[str, Any]]:
    """Кварталы участка без отступов: каждое кольцо ЕГРН — свой квартал; длинное
    кольцо режется поперёк своей оси на кварталы до 250 м с проездом 20 м.
    Кварталы пронумерованы вдоль оси участка — по ним идут очереди."""
    pieces: list[tuple[list[list[float]], set[int]]] = []
    for ring in inner:
        own = massing_strip_axis([ring])
        if not own:
            continue
        ux, uy = _math.cos(own["angle"]), _math.sin(own["angle"])
        proj = [p[0] * ux + p[1] * uy for p in ring]
        low, high = min(proj), max(proj)
        count = max(1, int(_math.ceil((high - low) / LAYOUT_BLOCK_LENGTH_M - 1e-9)))
        step = (high - low) / count
        for j in range(count):
            piece = ring
            cuts: list[float] = []
            if j > 0:
                c = low + j * step + LAYOUT_BLOCK_STREET_M / 2
                piece = _clip_half(piece, ux, uy, c, True)
                cuts.append(c)
            if j < count - 1 and len(piece) >= 3:
                c = low + (j + 1) * step - LAYOUT_BLOCK_STREET_M / 2
                piece = _clip_half(piece, ux, uy, c, False)
                cuts.append(c)
            if len(piece) < 3 or abs(_ring_area(piece)) < 400:
                continue
            # Стороны по линии разреза — внутренний проезд, а не граница участка.
            cut_sides = {i for i in range(len(piece))
                         if any(abs(piece[i][0] * ux + piece[i][1] * uy - c) < 0.01 and
                                abs(piece[(i + 1) % len(piece)][0] * ux
                                    + piece[(i + 1) % len(piece)][1] * uy - c) < 0.01
                                for c in cuts)}
            pieces.append((piece, cut_sides))
    if axis:
        gx, gy = _math.cos(axis["angle"]), _math.sin(axis["angle"])
    else:
        gx, gy = 1.0, 0.0

    def along(piece):
        ring = piece[0]
        return sum(p[0] * gx + p[1] * gy for p in ring) / len(ring)

    pieces.sort(key=along)
    blocks: list[dict[str, Any]] = []
    for order, (ring, cut_sides) in enumerate(pieces, 1):
        block_id = f"К{order}"
        own = massing_strip_axis([ring]) or {"angle": 0.0, "length": 0.0, "width": 0.0}
        fronts = _fronts_of(block_id, ring, cut_sides)
        blocks.append({"id": block_id, "order": order, "ring": ring,
                       "area_sqm": round(abs(_ring_area(ring)), 1),
                       "length_m": round(own["length"], 1), "width_m": round(own["width"], 1),
                       "along": along((ring, cut_sides)), "fronts": fronts})
    return blocks


# --- Проверка ---------------------------------------------------------------

def _rect_ring(a: list[float], u: list[float], n: list[float], offset: float,
               length: float, depth: float) -> list[list[float]]:
    """Прямоугольник на фронте: от точки a + u·offset вдоль u на length, внутрь на depth."""
    x0, y0 = a[0] + u[0] * offset, a[1] + u[1] * offset
    return [[x0, y0], [x0 + u[0] * length, y0 + u[1] * length],
            [x0 + u[0] * length + n[0] * depth, y0 + u[1] * length + n[1] * depth],
            [x0 + n[0] * depth, y0 + n[1] * depth]]


def _segments_cross(p1, p2, q1, q2) -> bool:
    def orient(a, b, c):
        return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])
    d1, d2 = orient(q1, q2, p1), orient(q1, q2, p2)
    d3, d4 = orient(p1, p2, q1), orient(p1, p2, q2)
    return ((d1 > 1e-9 and d2 < -1e-9) or (d1 < -1e-9 and d2 > 1e-9)) and \
        ((d3 > 1e-9 and d4 < -1e-9) or (d3 < -1e-9 and d4 > 1e-9))


def _poly_inside(poly: list[list[float]], ring: list[list[float]]) -> bool:
    """Выпуклый многоугольник целиком внутри кольца (кольцо может быть вогнутым)."""
    cx = sum(p[0] for p in poly) / len(poly)
    cy = sum(p[1] for p in poly) / len(poly)
    # Углы чуть стянуты к центру: корпус, стоящий ровно на границе, — внутри.
    probe = [[cx + (p[0] - cx) * 0.999, cy + (p[1] - cy) * 0.999] for p in poly]
    if not all(_inside((p[0], p[1]), [ring]) for p in probe):
        return False
    bx0, bx1 = min(p[0] for p in probe), max(p[0] for p in probe)
    by0, by1 = min(p[1] for p in probe), max(p[1] for p in probe)
    count = len(ring)
    for i in range(count):
        a, b = ring[i], ring[(i + 1) % count]
        if max(a[0], b[0]) < bx0 or min(a[0], b[0]) > bx1 or max(a[1], b[1]) < by0 \
                or min(a[1], b[1]) > by1:
            continue
        for j in range(len(probe)):
            if _segments_cross(a, b, probe[j], probe[(j + 1) % len(probe)]):
                return False
        if _convex_contains(probe, a):
            return False
    return True


def _convex_contains(poly: list[list[float]], p: list[float]) -> bool:
    sign = 0.0
    for i in range(len(poly)):
        a, b = poly[i], poly[(i + 1) % len(poly)]
        cross = (b[0] - a[0]) * (p[1] - a[1]) - (b[1] - a[1]) * (p[0] - a[0])
        if abs(cross) < 1e-9:
            return False
        if sign == 0.0:
            sign = cross
        elif (cross > 0) != (sign > 0):
            return False
    return True


def _gap_between(p: list[list[float]], q: list[list[float]]) -> float:
    """Расстояние между выпуклыми многоугольниками; наложение — отрицательное
    (глубина по лучшей оси разделения)."""
    best = -_math.inf
    for poly in (p, q):
        for i in range(len(poly)):
            a, b = poly[i], poly[(i + 1) % len(poly)]
            ex, ey = b[0] - a[0], b[1] - a[1]
            length = _math.hypot(ex, ey) or 1e-9
            nx, ny = -ey / length, ex / length
            pa = [v[0] * nx + v[1] * ny for v in p]
            qa = [v[0] * nx + v[1] * ny for v in q]
            best = max(best, max(min(qa) - max(pa), min(pa) - max(qa)))
    if best < 0:
        return best
    # Разделены — точное расстояние: от вершин до сторон.
    def seg_dist(v, a, b):
        ex, ey = b[0] - a[0], b[1] - a[1]
        t = max(0.0, min(1.0, ((v[0] - a[0]) * ex + (v[1] - a[1]) * ey) / ((ex * ex + ey * ey) or 1e-9)))
        return _math.hypot(v[0] - a[0] - ex * t, v[1] - a[1] - ey * t)
    return min(min(seg_dist(v, poly[i], poly[(i + 1) % len(poly)]) for v in other
                   for i in range(len(poly))) for poly, other in ((p, q), (q, p)))


def massing_check(buildings: list[dict[str, Any]], inner: list[list[list[float]]]) -> str | None:
    """Проверка расстановки → None или причина простыми словами.

    Корпус внутри участка без отступов (целиком в одном кольце), не ближе
    разрыва 12 м к соседу и не наезжает на него, площадь пятна — та же, что в
    расчёте (±1 %)."""
    for b in buildings:
        ring = b.get("ring_m") or []
        name = b.get("label") or b.get("id")
        if len(ring) < 3:
            return f"У корпуса «{name}» нет места на плане."
        area = abs(_ring_area(ring))
        if abs(area - float(b["area_sqm"])) > 0.01 * float(b["area_sqm"]) + 1.0:
            return (f"Пятно корпуса «{name}» на плане — {_fmt_ru(area)} м², а в расчёте — "
                    f"{_fmt_ru(b['area_sqm'])} м².")
        if not any(_poly_inside(ring, r) for r in inner):
            return f"Корпус «{name}» выходит за границу участка без отступов."
    for i in range(len(buildings)):
        for j in range(i + 1, len(buildings)):
            gap = _gap_between(buildings[i]["ring_m"], buildings[j]["ring_m"])
            if gap < LAYOUT_GAP_IN_ROW_M - 0.5:
                a = buildings[i].get("label") or buildings[i].get("id")
                b = buildings[j].get("label") or buildings[j].get("id")
                what = "наезжают друг на друга" if gap < 0 else \
                    f"стоят ближе {_fmt_ru(LAYOUT_GAP_IN_ROW_M)} м друг к другу"
                return f"Корпуса «{a}» и «{b}» {what}."
    return None


# --- Расстановка движка -----------------------------------------------------

def _shapes_for(c: dict[str, Any], tower: bool) -> list[tuple[float, float]]:
    """Варианты пятна корпуса (длина, глубина) той же площади: секция 18 м,
    затем глубже — до квадрата; башня — сначала квадрат."""
    area = float(c["area_sqm"])
    side = _math.sqrt(area)
    depths = [LAYOUT_CORPUS_DEPTH_M]
    d = LAYOUT_CORPUS_DEPTH_M
    while d + 6.0 < side:
        d += 6.0
        depths.append(d)
    depths.append(side)
    shapes = [(area / d, d) for d in depths if area / d >= d - 1e-6]
    if tower and side <= LAYOUT_TOWER_SIDE_MAX_M:
        shapes = [(side, side)] + [s for s in shapes if abs(s[1] - side) > 1e-6]
    return shapes


def _candidates(blocks: list[dict[str, Any]], length: float, depth: float,
                interior: bool, gx: float, gy: float):
    """Места корпуса на фронтах кварталов в порядке обхода: квартал за
    кварталом вдоль оси участка, внутри квартала — вдоль оси, сначала периметр."""
    for block in blocks:
        spots = []
        for f in block["fronts"]:
            if f["length_m"] + 1e-6 < length:
                continue
            levels = [0.0]
            if interior:
                k = 1
                row = depth + LAYOUT_GAP_BETWEEN_ROWS_M
                while k * row + depth <= f["room_m"] - depth - LAYOUT_GAP_BETWEEN_ROWS_M + 1e-6:
                    levels.append(k * row)
                    k += 1
            top = f["length_m"] - length
            steps = max(1, int(top // LAYOUT_FRONT_STEP_M) + 1)
            offsets = [min(top, s * LAYOUT_FRONT_STEP_M) for s in range(steps)]
            if offsets[-1] < top - 1e-6:
                offsets.append(top)
            ux, uy = f["u"]
            nx, ny = f["n"]
            for level, shift in enumerate(levels):
                a = [f["a"][0] + nx * shift, f["a"][1] + ny * shift]
                for t in offsets:
                    mx = a[0] + ux * (t + length / 2) + nx * depth / 2
                    my = a[1] + uy * (t + length / 2) + ny * depth / 2
                    spots.append((level, mx * gx + my * gy, f, a, t, shift))
        spots.sort(key=lambda s: (s[0], s[1]))
        for level, _, f, a, t, shift in spots:
            yield block, f, a, t, shift


def _try_place(c: dict[str, Any], blocks: list[dict[str, Any]], placed: list[dict[str, Any]],
               interior: bool, gx: float, gy: float, tower: bool) -> bool:
    for length, depth in _shapes_for(c, tower):
        for block, f, a, t, shift in _candidates(blocks, length, depth, interior, gx, gy):
            ring = _rect_ring(a, f["u"], f["n"], t, length, depth)
            bx0, bx1 = min(p[0] for p in ring), max(p[0] for p in ring)
            by0, by1 = min(p[1] for p in ring), max(p[1] for p in ring)
            clash = False
            for other in placed:
                ob = other["_bbox"]
                if ob[0] > bx1 + LAYOUT_GAP_IN_ROW_M or ob[2] < bx0 - LAYOUT_GAP_IN_ROW_M or \
                        ob[1] > by1 + LAYOUT_GAP_IN_ROW_M or ob[3] < by0 - LAYOUT_GAP_IN_ROW_M:
                    continue
                if _gap_between(ring, other["ring_m"]) < LAYOUT_GAP_IN_ROW_M:
                    clash = True
                    break
            if clash or not _poly_inside(ring, block["ring"]):
                continue
            c["ring_m"] = [[round(p[0], 2), round(p[1], 2)] for p in ring]
            c["_bbox"] = (bx0, by0, bx1, by1)
            c["block"] = block["id"]
            c["front"] = f["id"]
            c["shape"] = "tower" if tower and abs(length - depth) < 1e-6 else "section"
            c["place"] = {"corpus": c["id"], "front": f["id"], "offset_m": round(t, 2),
                          "inset_m": round(shift, 2), "length_m": round(length, 2),
                          "depth_m": round(depth, 2)}
            placed.append(c)
            return True
    return False


def massing_place_engine(corpora: list[dict[str, Any]], blocks: list[dict[str, Any]],
                         axis: dict[str, float] | None) -> bool:
    """Запасная расстановка движка по кварталам → True, если встали все корпуса.

    Отдельные здания (школа, сад, офисы) — в самых широких кварталах, все
    корпуса одного здания рядом; очереди — подряд вдоль оси участка в
    оставшихся кварталах: первая с одного конца, следующие дальше. Корпус
    сначала ищет место на периметре квартала (секции вдоль сторон замыкают
    двор), затем во внутренних рядах. Башня — корпус заметно выше остальных:
    квадратное пятно, сначала на углу. Площадь корпуса не меняется."""
    if not corpora or not blocks:
        return False
    gx, gy = (_math.cos(axis["angle"]), _math.sin(axis["angle"])) if axis else (1.0, 0.0)
    typical = sorted(c["storeys_shown"] for c in corpora if c["phase"] > 0) or [0]
    median = typical[len(typical) // 2]
    wide = sorted(blocks, key=lambda b: (-b["width_m"], b["order"]))
    for interior in (False, True):
        placed: list[dict[str, Any]] = []
        ok = True
        objects = [c for c in corpora if c["phase"] == 0]
        for key in dict.fromkeys(c.get("object") for c in objects):
            own = [c for c in objects if c.get("object") == key]
            # Здание целиком — в первый из широких кварталов, где встаёт всё.
            done = False
            for block in wide:
                trial = list(placed)
                if all(_try_place(c, [block], trial, interior, gx, gy, False) for c in own):
                    placed[:] = trial
                    done = True
                    break
            if not done and not all(_try_place(c, wide, placed, interior, gx, gy, False) for c in own):
                ok = False
                break
        if ok:
            # Очереди — подряд: корпус не уходит в квартал раньше того, где
            # встал предыдущий; кварталы отдельных зданий — только если в
            # остальных места нет.
            taken = {c.get("block") for c in placed}
            homes = [b for b in blocks if b["id"] not in taken]
            order = {b["id"]: b["order"] for b in blocks}
            cursor = 0
            for c in [c for c in corpora if c["phase"] > 0]:
                tower = median > 0 and c["storeys_shown"] >= LAYOUT_TOWER_RATIO * median
                tiers = ([b for b in homes if b["order"] >= cursor],
                         [b for b in blocks if b["order"] >= cursor], blocks)
                if not any(tier and _try_place(c, tier, placed, interior, gx, gy, tower)
                           for tier in tiers):
                    ok = False
                    break
                cursor = order[c["block"]]
        if ok:
            for c in corpora:
                c.pop("_bbox", None)
            return True
    for c in corpora:
        for key in ("_bbox", "ring_m", "block", "front", "shape", "place"):
            c.pop(key, None)
    return False


def massing_place_plan(corpora: list[dict[str, Any]], blocks: list[dict[str, Any]],
                       placements: Any) -> str | None:
    """Корпуса по плану Платона: фронт, отступ от начала фронта вдоль него,
    сдвиг внутрь квартала от линии фронта, длина и глубина пятна. Движок сам строит прямоугольники и не правит план: что не
    так — причина, и план не принимается."""
    if not isinstance(placements, list):
        return "В ответе Платона нет списка корпусов."
    fronts = {f["id"]: f for b in blocks for f in b["fronts"]}
    by_id = {c["id"]: c for c in corpora}
    seen: set[str] = set()
    for item in placements:
        if not isinstance(item, dict):
            return "Ответ Платона не по схеме: строка плана — не запись."
        cid, fid = str(item.get("corpus") or ""), str(item.get("front") or "")
        if cid not in by_id:
            return f"Платон поставил корпус «{cid}», которого нет в расчёте."
        if cid in seen:
            return f"Платон поставил корпус «{by_id[cid]['label']}» дважды."
        if fid not in fronts:
            return f"Платон поставил корпус «{by_id[cid]['label']}» на фронт «{fid}», которого нет."
        try:
            offset, inset, length, depth = (float(item.get(k) or 0.0) if k == "inset_m" else float(item.get(k))
                                            for k in ("offset_m", "inset_m", "length_m", "depth_m"))
        except (TypeError, ValueError):
            return f"У корпуса «{by_id[cid]['label']}» в плане Платона нет размеров."
        if min(length, depth) < 10.0 or offset < -0.5 or inset < -0.5:
            return f"У корпуса «{by_id[cid]['label']}» в плане Платона негодные размеры."
        seen.add(cid)
        f = fronts[fid]
        c = by_id[cid]
        a = [f["a"][0] + f["n"][0] * inset, f["a"][1] + f["n"][1] * inset]
        c["ring_m"] = [[round(p[0], 2), round(p[1], 2)]
                       for p in _rect_ring(a, f["u"], f["n"], offset, length, depth)]
        c["place"] = {"corpus": cid, "front": fid, "offset_m": offset, "inset_m": inset,
                      "length_m": length, "depth_m": depth}
        c["block"], c["front"] = f["block"], fid
        c["shape"] = "tower" if abs(length - depth) < 0.15 * max(length, depth) else "section"
    missing = [c["label"] for c in corpora if c["id"] not in seen]
    if missing:
        return f"В плане Платона нет корпуса «{missing[0]}»."
    return None
