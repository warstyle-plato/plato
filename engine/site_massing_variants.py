"""Посадка жилых домов из секций: разбор участка и варианты застройки.

Жалоба владельца (31.10.2026): «посадка на сложных контурах реализована плохо,
аналитики нет, квадраты какие-то вписанные куском, без анализа реальных
посадок». Прежняя расстановка (`massing_place_engine`) ставила плиты 18 × 100 м
подряд от одного края, пока все не встанут, — на Г-образном участке, на участке
с вырезами и на КРТ из нескольких участков дома собирались в одном углу, а
целый кусок участка оставался пустым.

Решение владельца (AskUserQuestion 31.10.2026): «бывают же сложные посадки;
странно, когда целый кусок сбоку пустой»; Платон выбирает из вариантов движка;
разрывы, пожарные проезды и инсоляция — допущения с подписью, а не норма.

Что делает этот кусок движка:
- `massing_site_analysis` — разбор участка: части (кварталы), их размеры и
  направление по сторонам света, какой тип застройки часть держит.
- `massing_variants` — варианты посадки одних и тех же домов (площадь пятна
  каждого дома та же, что в расчёте):
  - «квартальная» — дома вдоль сторон кварталов, на поворотах угловые
    секции (дом буквой Г), двор внутри — без машин;
  - «меридиональная» — дома рядами с севера на юг: обе длинные стороны
    получают солнце утром и вечером;
  - «комбинированная» — и то и другое: периметр и ряды внутри;
  - «рядами вдоль участка» — прежняя расстановка (`massing_place_engine`),
    она остаётся вариантом, чтобы участок, где встаёт только она, не потерял
    дома.
  Дома одного варианта расставляются так, чтобы закрыть участок равномерно:
  каждый следующий дом встаёт туда, где он больше всего сокращает расстояние
  от точек участка до ближайшего дома. Очередь держится своей полосы вдоль
  оси участка — очереди идут подряд.
- `massing_variant_pick` — выбор движка: все ли дома встали, нет ли пустого
  куска, сколько домов вытянуто с севера на юг. Платон (`site_massing_plan`)
  выбирает из тех же вариантов и объясняет выбор.
- `massing_fire_lanes` — где у дома место для пожарного проезда.
- `massing_plan_view` — вид сверху (север вверху) для страницы.

Допущения — не нормы: чисел СП 4.13130.2013 (разд. 8, проезды), СанПиН
1.2.3685-21 (инсоляция) и бытовых разрывов в библиотеке нормативов нет
(`data/normatives/registry.json`); подробно — `docs/site_massing_practice.md`.

Не самостоятельный модуль: `main_legacy.py` выполняет файл в пространстве
имён движка (`_engine_part("site_massing_variants")`).
"""
# ruff: noqa

import math as _math

import numpy as _np

# Типовая рядовая секция: глубина корпуса — `LAYOUT_CORPUS_DEPTH_M` (18 м),
# длина около 30 м (обычно 24–36 м: 4–8 квартир на этаже). Допущение.
LAYOUT_SECTION_LENGTH_M = 30.0
# Разрыв между длинными сторонами домов: не меньше 20 м и не меньше 0,8 высоты
# более высокого дома — ориентир бытового разрыва и инсоляции (допущение; было
# в СП 42.13330.2016, п. 7.1, в библиотеке нормативов его нет). Торцы и углы —
# прежние 12 м (`LAYOUT_GAP_IN_ROW_M`).
LAYOUT_GAP_LONG_MIN_M = 20.0
LAYOUT_GAP_HEIGHT_SHARE = 0.8
# Пожарный проезд (допущение по СП 4.13130.2013, разд. 8; текста в библиотеке
# нет): от стены до края проезда 5–8 м у домов до 28 м высотой и 8–10 м выше;
# ширина 3,5 м до 13 м высоты, 4,2 м — до 46 м, 6 м — выше. Дому выше 28 м —
# проезд с двух длинных сторон, ниже — с одной.
LAYOUT_FIRE_HIGH_M = 28.0
# Точка участка дальше от домов, чем это (и чем полтора «равномерных» шага
# между домами), — пустой кусок участка.
LAYOUT_EMPTY_REACH_M = 60.0
# Пустой кусок заметен, когда занимает больше этой доли участка.
LAYOUT_EMPTY_SHARE = 0.08
# Точек участка, по которым меряется равномерность, и шаг перебора мест.
LAYOUT_SAMPLE_POINTS = 500
LAYOUT_VARIANT_STEP_M = 6.0
# Дом вытянут с севера на юг, если его длинная ось отклонена от меридиана не
# больше чем на столько градусов; с запада на восток — если больше 60°.
LAYOUT_MERIDIONAL_DEG = 30.0

LAYOUT_VARIANTS = ("perimeter", "meridional", "mixed", "rows")
LAYOUT_VARIANT_NAMES = {
    "perimeter": "квартальная",
    "meridional": "меридиональная",
    "mixed": "комбинированная",
    "rows": "рядами вдоль участка",
}
LAYOUT_VARIANT_WHAT = {
    "perimeter": "дома стоят вдоль сторон кварталов, на поворотах — угловые секции, внутри — "
                 "двор без машин",
    "meridional": "дома стоят рядами с севера на юг, обе длинные стороны получают солнце "
                  "утром и вечером",
    "mixed": "дома стоят и вдоль сторон кварталов, и рядами внутри",
    "rows": "дома стоят подряд вдоль участка, начиная с одного края",
}
_COMPASS = ("востоке", "северо-востоке", "севере", "северо-западе", "западе", "юго-западе",
            "юге", "юго-востоке")


# --- Геометрия ---------------------------------------------------------------

def _mv_line_cross(p: list[float], u: list[float], q: list[float], v: list[float]):
    """Точка пересечения прямых p + t·u и q + s·v → (точка, t, s) или None."""
    den = u[0] * v[1] - u[1] * v[0]
    if abs(den) < 1e-9:
        return None
    dx, dy = q[0] - p[0], q[1] - p[1]
    t = (dx * v[1] - dy * v[0]) / den
    s = (dx * u[1] - dy * u[0]) / den
    return [p[0] + u[0] * t, p[1] + u[1] * t], t, s


def _mv_corner_ring(c: list[float], u1, n1, u2, n2, a: float, b: float, d: float):
    """Дом буквой Г на углу квартала: крыло вдоль первого фронта (к углу) длиной
    a, крыло вдоль второго (от угла) длиной b, глубина d."""
    inner = _mv_line_cross([c[0] + n1[0] * d, c[1] + n1[1] * d], u1,
                           [c[0] + n2[0] * d, c[1] + n2[1] * d], u2)
    if not inner:
        return None
    ic = inner[0]
    return [[c[0] - u1[0] * a, c[1] - u1[1] * a], [c[0], c[1]],
            [c[0] + u2[0] * b, c[1] + u2[1] * b],
            [c[0] + u2[0] * b + n2[0] * d, c[1] + u2[1] * b + n2[1] * d],
            [ic[0], ic[1]],
            [c[0] - u1[0] * a + n1[0] * d, c[1] - u1[1] * a + n1[1] * d]], ic


def _mv_rect(cx: float, cy: float, ux: float, uy: float, length: float, depth: float):
    """Прямоугольник с центром (cx, cy), длинной осью u."""
    nx, ny = -uy, ux
    hl, hd = length / 2.0, depth / 2.0
    return [[cx - ux * hl - nx * hd, cy - uy * hl - ny * hd],
            [cx + ux * hl - nx * hd, cy + uy * hl - ny * hd],
            [cx + ux * hl + nx * hd, cy + uy * hl + ny * hd],
            [cx - ux * hl + nx * hd, cy - uy * hl + ny * hd]]


def _mv_seg_dist(p, a, b) -> float:
    ex, ey = b[0] - a[0], b[1] - a[1]
    t = max(0.0, min(1.0, ((p[0] - a[0]) * ex + (p[1] - a[1]) * ey) / ((ex * ex + ey * ey) or 1e-9)))
    return _math.hypot(p[0] - a[0] - ex * t, p[1] - a[1] - ey * t)


def _mv_edges(ring: list[list[float]]):
    out = []
    for i in range(len(ring)):
        a, b = ring[i], ring[(i + 1) % len(ring)]
        length = _math.hypot(b[0] - a[0], b[1] - a[1])
        if length > 1e-6:
            out.append((a, b, length, ((b[0] - a[0]) / length, (b[1] - a[1]) / length)))
    return out


def _mv_long_axis(ring: list[list[float]]) -> tuple[float, float]:
    """Направление самой длинной стороны дома (единичный вектор)."""
    a, b, length, u = max(_mv_edges(ring), key=lambda e: e[2])
    return u


def _mv_height(c: dict[str, Any]) -> float:
    return float(c.get("storeys_shown") or 1) * LAYOUT_STOREY_HEIGHT_M


def massing_required_gap(p: dict[str, Any], q: dict[str, Any]) -> tuple[float, str, float]:
    """Нужный разрыв между двумя домами → (нужно, вид, есть), метры.

    Длинные стороны (не короче двух глубин корпуса) почти параллельны и стоят
    друг против друга на заметной длине (больше глубины корпуса) — между ними
    не меньше 20 м и 0,8 высоты более высокого дома; в остальном (торец, угол)
    — 12 м. Возвращается самое строгое из нарушенных условий, а без нарушений
    — то, что ближе всего к нарушению. Допущение, не норма."""
    dp = float(p.get("depth_m") or LAYOUT_CORPUS_DEPTH_M)
    dq = float(q.get("depth_m") or LAYOUT_CORPUS_DEPTH_M)
    overall = _mv_poly_dist(p["ring_m"], q["ring_m"])
    long_need = max(LAYOUT_GAP_LONG_MIN_M,
                    LAYOUT_GAP_HEIGHT_SHARE * max(_mv_height(p), _mv_height(q)))
    best = (LAYOUT_GAP_IN_ROW_M, "торец", overall)
    for a1, b1, l1, u1 in _mv_edges(p["ring_m"]):
        if l1 < 2 * dp - 1e-6:
            continue
        for a2, b2, l2, u2 in _mv_edges(q["ring_m"]):
            if l2 < 2 * dq - 1e-6 or abs(u1[0] * u2[1] - u1[1] * u2[0]) >= 0.5:
                continue
            s1 = sorted((a1[0] * u1[0] + a1[1] * u1[1], b1[0] * u1[0] + b1[1] * u1[1]))
            s2 = sorted((a2[0] * u1[0] + a2[1] * u1[1], b2[0] * u1[0] + b2[1] * u1[1]))
            if min(s1[1], s2[1]) - max(s1[0], s2[0]) <= min(dp, dq):
                continue
            # Расстояние между прямыми сторон (по нормали первой).
            nx, ny = -u1[1], u1[0]
            dist = abs((a2[0] - a1[0]) * nx + (a2[1] - a1[1]) * ny)
            if dist - long_need < best[2] - best[0]:
                best = (long_need, "длинные стороны", dist)
    return best


def _mv_poly_dist(p: list[list[float]], q: list[list[float]]) -> float:
    """Расстояние между непересекающимися многоугольниками (любой формы)."""
    return min(_mv_seg_dist(v, a, b) for poly, oth in ((p, q), (q, p))
               for v in poly for a, b, _, _ in _mv_edges(oth))


# --- Части участка: крылья по внутренним углам контура ----------------------------

# Внутренний угол, по которому участок делится на части, — поворот контура
# внутрь больше этого; часть не уже этой ширины (меньше — не делим).
LAYOUT_SPLIT_TURN_DEG = 35.0
LAYOUT_SPLIT_MIN_WIDTH_M = 30.0


def _mv_ray_hit(ring: list[list[float]], v: int, d: tuple[float, float]):
    """Первое пересечение луча из вершины v по направлению d с контуром →
    (точка, номер стороны, длина) или None."""
    px, py = ring[v]
    best = None
    n = len(ring)
    for i in range(n):
        if i == v or (i + 1) % n == v:
            continue
        a, b = ring[i], ring[(i + 1) % n]
        hit = _mv_line_cross([px, py], list(d), a, [b[0] - a[0], b[1] - a[1]])
        if not hit:
            continue
        point, t, s = hit
        if t > 0.5 and -1e-9 <= s <= 1 + 1e-9 and (best is None or t < best[2]):
            best = (point, i, t)
    return best


def _mv_split_ring(ring: list[list[float]], depth: int = 0) -> list[list[list[float]]]:
    """Кольцо → части: по внутреннему углу контура короткой линией-продолжением
    стороны до другой стороны (Г-образный участок — два крыла, П-образный — три
    части). Углы ищутся на упрощённом контуре (мелкие изломы границы — не угол),
    а режется настоящий контур: части не выходят за границу. Части не уже
    `LAYOUT_SPLIT_MIN_WIDTH_M`; иначе кольцо целиком."""
    if depth > 4 or len(ring) < 5:
        return [ring]
    if _ring_area(ring) < 0:
        ring = ring[::-1]
    keep = _simplify(ring, LAYOUT_FRONT_TOLERANCE_M)
    m = len(keep)
    n = len(ring)
    if m < 5:
        return [ring]
    best = None
    for j in range(m):
        a, b, c = ring[keep[j - 1]], ring[keep[j]], ring[keep[(j + 1) % m]]
        v = keep[j]
        e1 = (b[0] - a[0], b[1] - a[1])
        e2 = (c[0] - b[0], c[1] - b[1])
        l1, l2 = _math.hypot(*e1), _math.hypot(*e2)
        if l1 < 1e-6 or l2 < 1e-6:
            continue
        cross = e1[0] * e2[1] - e1[1] * e2[0]
        turn = _math.degrees(_math.asin(max(-1.0, min(1.0, cross / (l1 * l2)))))
        if cross >= 0 or -turn < LAYOUT_SPLIT_TURN_DEG and (e1[0] * e2[0] + e1[1] * e2[1]) > 0:
            continue
        for d in ((e1[0] / l1, e1[1] / l1), (-e2[0] / l2, -e2[1] / l2)):
            hit = _mv_ray_hit(ring, v, d)
            if not hit:
                continue
            point, i, length = hit
            # Две части: v → … → i, точка; точка → i+1 → … → v.
            one = [ring[v]]
            k = v
            while k != i:
                k = (k + 1) % n
                one.append(ring[k])
            one.append(point)
            two = [point]
            k = i
            while k != v:
                k = (k + 1) % n
                two.append(ring[k])
            one, two = _clean_ring(one), _clean_ring(two)
            if len(one) < 3 or len(two) < 3:
                continue
            ok = True
            for part in (one, two):
                ax = massing_strip_axis([part])
                if not ax or ax["width"] < LAYOUT_SPLIT_MIN_WIDTH_M or abs(_ring_area(part)) < 1500:
                    ok = False
            if ok and (best is None or length < best[0]):
                best = (length, one, two)
    if not best:
        return [ring]
    return _mv_split_ring(best[1], depth + 1) + _mv_split_ring(best[2], depth + 1)


def massing_parts(site: list[list[list[float]]], axis: dict[str, float] | None
                  ) -> list[dict[str, Any]]:
    """Кварталы для вариантов посадки: каждое кольцо делится на крылья по
    внутренним углам, длинное крыло — на кварталы до 250 м с проездом
    (`massing_blocks`)."""
    rings = [part for ring in site for part in _mv_split_ring([list(p) for p in ring])]
    return massing_blocks(rings, axis)


# --- Разбор участка ------------------------------------------------------------

def _mv_azimuth_word(u: tuple[float, float], north: list[float] | None) -> str:
    """Направление оси словами: «с севера на юг», «с запада на восток», …"""
    if not north:
        return ""
    nx, ny = north
    ex, ey = ny, -nx  # восток — по часовой от севера
    along_n = u[0] * nx + u[1] * ny
    along_e = u[0] * ex + u[1] * ey
    deg = _math.degrees(_math.atan2(abs(along_e), abs(along_n)))
    if deg <= 22.5:
        return "с севера на юг"
    if deg >= 67.5:
        return "с запада на восток"
    return ("с северо-запада на юго-восток" if along_n * along_e < 0
            else "с северо-востока на юго-запад")


def _mv_meridian_deg(u: tuple[float, float], north: list[float]) -> float:
    """Отклонение оси от меридиана, градусы 0…90."""
    cos = abs(u[0] * north[0] + u[1] * north[1])
    return _math.degrees(_math.acos(max(-1.0, min(1.0, cos))))


def _mv_where(point: tuple[float, float], centre: tuple[float, float],
              north: list[float] | None) -> str:
    """Где точка относительно центра участка: «на северо-востоке», …"""
    if not north:
        return ""
    dx, dy = point[0] - centre[0], point[1] - centre[1]
    nx, ny = north
    ex, ey = ny, -nx
    ang = _math.degrees(_math.atan2(dx * nx + dy * ny, dx * ex + dy * ey)) % 360.0
    return "на " + _COMPASS[int(((ang + 22.5) % 360.0) // 45.0)]


def massing_site_analysis(blocks: list[dict[str, Any]], north: list[float] | None
                          ) -> dict[str, Any]:
    """Части участка (кварталы) → размеры, направление и что часть держит.

    Квартал держит дома по периметру с двором, если он не уже двух глубин
    корпуса и двора между ними (18 + 20 + 18 ≈ 56 м); уже — только ряд домов
    или отдельные дома."""
    depth = LAYOUT_CORPUS_DEPTH_M
    parts = []
    for b in blocks:
        own = massing_strip_axis([b["ring"]]) or {"angle": 0.0, "length": 0.0, "width": 0.0}
        u = (_math.cos(own["angle"]), _math.sin(own["angle"]))
        width = float(own["width"])
        length = float(own["length"])
        if width >= 2 * depth + LAYOUT_GAP_LONG_MIN_M:
            holds = "perimeter"
        elif width >= depth + 4:
            holds = "row"
        else:
            holds = "narrow"
        parts.append({"id": b["id"], "area_sqm": round(b["area_sqm"]),
                      "length_m": round(length), "width_m": round(width),
                      "direction": _mv_azimuth_word(u, north), "holds": holds,
                      "fronts": len(b["fronts"])})
    return {"parts": parts, "north_known": bool(north)}


# --- Места домов ---------------------------------------------------------------

def _mv_candidates(c: dict[str, Any], blocks: list[dict[str, Any]], variant: str,
                   north: list[float] | None, tower: bool) -> list[dict[str, Any]]:
    """Места дома в варианте: прямой дом вдоль фронта, дом буквой Г на углу
    квартала, дом с севера на юг внутри квартала, башня."""
    area = float(c["area_sqm"])
    d = float(c.get("depth_m") or LAYOUT_CORPUS_DEPTH_M)
    length = area / d
    out: list[dict[str, Any]] = []
    step = LAYOUT_VARIANT_STEP_M
    side = _math.sqrt(area)
    if tower and side <= LAYOUT_TOWER_SIDE_MAX_M:
        shapes = [(side, side)]
    else:
        shapes = [(length, d)] if length >= d else [(side, side)]
    use_fronts = variant in ("perimeter", "mixed")
    use_rows = variant in ("meridional", "mixed")
    # Источник места (`kind`): section/corner — периметр квартала, row — внутри.
    for block in blocks:
        bid = block["id"]
        if use_fronts:
            for f in block["fronts"]:
                for L, D in shapes:
                    if f["length_m"] + 1e-6 < L:
                        continue
                    top = f["length_m"] - L
                    count = max(1, int(top // step) + 1)
                    offsets = sorted({min(top, k * step) for k in range(count)} | {top})
                    ux, uy = f["u"]
                    nx, ny = f["n"]
                    for t in offsets:
                        ring = _rect_ring(f["a"], f["u"], f["n"], t, L, D)
                        sx = f["a"][0] + ux * t + nx * D / 2
                        sy = f["a"][1] + uy * t + ny * D / 2
                        out.append({"ring": ring, "block": bid, "front": f["id"],
                                    "kind": "section" if L > D + 1e-6 else "tower",
                                    "spines": [[[sx, sy], [sx + ux * L, sy + uy * L]]],
                                    "place": {"front": f["id"], "offset_m": round(t, 2),
                                              "length_m": round(L, 2), "depth_m": round(D, 2)}})
            # Дом буквой Г на выпуклом углу квартала: угловая секция и два крыла.
            if not tower and length >= 2 * d + 6:
                fronts = block["fronts"]
                for i in range(len(fronts)):
                    f1, f2 = fronts[i], fronts[(i + 1) % len(fronts)]
                    if f1 is f2:
                        continue
                    cosang = f1["u"][0] * f2["u"][0] + f1["u"][1] * f2["u"][1]
                    turn = f1["u"][0] * f2["u"][1] - f1["u"][1] * f2["u"][0]
                    left = f1["n"][0] * f2["u"][0] + f1["n"][1] * f2["u"][1]
                    if abs(cosang) > 0.35 or left <= 0:
                        continue
                    hit = _mv_line_cross(f1["a"], f1["u"], f2["a"], f2["u"])
                    if not hit:
                        continue
                    corner, t1, s2 = hit
                    if abs(t1 - f1["length_m"]) > 10 or abs(s2) > 10:
                        continue
                    room1 = min(t1, f1["length_m"])
                    room2 = f2["length_m"] - max(0.0, s2)
                    for share in (0.5, 0.35, 0.65):
                        # Площадь Г ≈ d·(a + b) − d²: подбор длин крыльев.
                        total = area / d + d
                        a, b = total * share, total * (1 - share)
                        if min(a, b) < d + 6 or a > room1 + 1e-6 or b > room2 + 1e-6:
                            continue
                        built = _mv_corner_ring(corner, f1["u"], f1["n"], f2["u"], f2["n"], a, b, d)
                        if not built:
                            continue
                        ring, ic = built
                        # Площадь Г линейна по сумме крыльев: одна поправка точная.
                        real = abs(_ring_area(ring))
                        delta = (area - real) / d
                        a, b = a + delta * share, b + delta * (1 - share)
                        built = _mv_corner_ring(corner, f1["u"], f1["n"], f2["u"], f2["n"], a, b, d)
                        if not built:
                            continue
                        ring, ic = built
                        if a > room1 + 1e-6 or b > room2 + 1e-6:
                            continue
                        mid1 = [corner[0] + f1["n"][0] * d / 2, corner[1] + f1["n"][1] * d / 2]
                        mid = [(corner[0] + ic[0]) / 2, (corner[1] + ic[1]) / 2]
                        mid2 = [corner[0] + f2["n"][0] * d / 2, corner[1] + f2["n"][1] * d / 2]
                        out.append({"ring": ring, "block": bid, "front": f1["id"],
                                    "kind": "corner",
                                    "spines": [[[mid1[0] - f1["u"][0] * a, mid1[1] - f1["u"][1] * a], mid],
                                               [mid, [mid2[0] + f2["u"][0] * b, mid2[1] + f2["u"][1] * b]]],
                                    "corner": [round(corner[0], 2), round(corner[1], 2)],
                                    "place": {"front": f1["id"], "next_front": f2["id"],
                                              "arms_m": [round(a, 2), round(b, 2)], "depth_m": d}})
        if use_rows and north:
            ring_b = block["ring"]
            xs = [p[0] for p in ring_b]
            ys = [p[1] for p in ring_b]
            ux, uy = north
            grid = max(step, _math.sqrt(abs(_ring_area(ring_b))) / 30.0)
            for L, D in shapes:
                hl = max(L, D) / 2.0
                y = min(ys) + hl
                while y <= max(ys) - min(D, L) / 2 + 1e-6:
                    x = min(xs) + min(D, L) / 2
                    while x <= max(xs) - min(D, L) / 2 + 1e-6:
                        if _inside((x, y), [ring_b]):
                            ring = _mv_rect(x, y, ux, uy, L, D)
                            out.append({"ring": ring, "block": bid, "front": "",
                                        "kind": "row" if L > D + 1e-6 else "tower",
                                        "spines": [[[x - ux * L / 2, y - uy * L / 2],
                                                    [x + ux * L / 2, y + uy * L / 2]]],
                                        "place": {"centre_m": [round(x, 2), round(y, 2)],
                                                  "length_m": round(L, 2), "depth_m": round(D, 2)}})
                        x += grid
                    y += grid
    return out


def _mv_dist(points: "_np.ndarray", spines: list[list[list[float]]], half: float) -> "_np.ndarray":
    """Расстояние от точек до дома: до оси минус полглубины, не меньше нуля."""
    best = None
    for a, b in spines:
        ax, ay = a
        ex, ey = b[0] - ax, b[1] - ay
        ll = ex * ex + ey * ey or 1e-9
        t = _np.clip(((points[:, 0] - ax) * ex + (points[:, 1] - ay) * ey) / ll, 0.0, 1.0)
        d = _np.hypot(points[:, 0] - ax - ex * t, points[:, 1] - ay - ey * t)
        best = d if best is None else _np.minimum(best, d)
    return _np.maximum(best - half, 0.0)


def _mv_dist_many(points: "_np.ndarray", cands: list[dict[str, Any]], half: float) -> "_np.ndarray":
    """Расстояния от точек до многих домов сразу → матрица (дома × точки)."""
    out = _np.empty((len(cands), len(points)), dtype=_np.float32)
    seg_count = max(len(k["spines"]) for k in cands)
    px, py = points[:, 0][None, :], points[:, 1][None, :]
    for start in range(0, len(cands), 1500):
        chunk = cands[start:start + 1500]
        best = None
        for j in range(seg_count):
            segs = _np.array([k["spines"][min(j, len(k["spines"]) - 1)] for k in chunk], dtype=float)
            ax, ay = segs[:, 0, 0][:, None], segs[:, 0, 1][:, None]
            ex, ey = (segs[:, 1, 0] - segs[:, 0, 0])[:, None], (segs[:, 1, 1] - segs[:, 0, 1])[:, None]
            ll = ex * ex + ey * ey
            ll[ll == 0] = 1e-9
            t = _np.clip(((px - ax) * ex + (py - ay) * ey) / ll, 0.0, 1.0)
            d = _np.hypot(px - ax - ex * t, py - ay - ey * t)
            best = d if best is None else _np.minimum(best, d)
        out[start:start + len(chunk)] = _np.maximum(best - half, 0.0)
    return out


def _mv_samples(site: list[list[list[float]]]) -> "_np.ndarray":
    area = sum(abs(_ring_area(r)) for r in site)
    if area <= 0:
        return _np.zeros((0, 2))
    step = max(3.0, _math.sqrt(area / LAYOUT_SAMPLE_POINTS))
    pts = [p for r in site for p in r]
    x0, x1 = min(p[0] for p in pts), max(p[0] for p in pts)
    y0, y1 = min(p[1] for p in pts), max(p[1] for p in pts)
    out = []
    y = y0 + step / 2
    while y < y1:
        x = x0 + step / 2
        while x < x1:
            if _inside((x, y), site):
                out.append((x, y))
            x += step
        y += step
    return _np.array(out, dtype=float) if out else _np.zeros((0, 2))


def _mv_fits(cand: dict[str, Any], c: dict[str, Any], block_ring: list[list[float]],
             placed: list[dict[str, Any]], site: list[list[list[float]]] | None = None) -> bool:
    """Дом внутри квартала и настоящего участка без отступов (контур части
    упрощён и на дуге может выйти за границу), не наезжает на соседей и не
    ближе нужного разрыва."""
    ring = cand["ring"]
    if not _poly_inside(ring, block_ring):
        return False
    if site and not any(_poly_inside(ring, r) for r in site):
        return False
    probe = {"ring_m": ring, "depth_m": c.get("depth_m"), "storeys_shown": c["storeys_shown"]}
    bx0, bx1 = min(p[0] for p in ring), max(p[0] for p in ring)
    by0, by1 = min(p[1] for p in ring), max(p[1] for p in ring)
    for other in placed:
        ob = other["_bbox"]
        reach = max(LAYOUT_GAP_LONG_MIN_M, LAYOUT_GAP_HEIGHT_SHARE
                    * max(_mv_height(c), _mv_height(other))) + 1
        if ob[0] > bx1 + reach or ob[2] < bx0 - reach or ob[1] > by1 + reach or ob[3] < by0 - reach:
            continue
        if _mv_overlap(ring, other["ring_m"]):
            return False
        need, _, have = massing_required_gap(probe, other)
        if have < need - 1e-6:
            return False
    return True


def _mv_overlap(p: list[list[float]], q: list[list[float]]) -> bool:
    """Многоугольники пересекаются или один внутри другого."""
    for i in range(len(p)):
        for j in range(len(q)):
            if _segments_cross(p[i], p[(i + 1) % len(p)], q[j], q[(j + 1) % len(q)]):
                return True
    return _inside((p[0][0], p[0][1]), [q]) or _inside((q[0][0], q[0][1]), [p])


def _mv_place(corpora: list[dict[str, Any]], blocks: list[dict[str, Any]], variant: str,
              north: list[float] | None, axis: dict[str, float] | None,
              points: "_np.ndarray", made: dict[tuple, Any] | None = None,
              pack: bool = False,
              site: list[list[list[float]]] | None = None) -> list[dict[str, Any]]:
    """Дома варианта по одному: каждый — на место, которое сильнее всего
    приближает дома к точкам участка (своей полосы — для очереди). `pack` —
    плотный проход для тесного участка: место ближе к началу полосы очереди,
    дома встают подряд и не дробят землю."""
    by_block = {b["id"]: b for b in blocks}
    gx, gy = (_math.cos(axis["angle"]), _math.sin(axis["angle"])) if axis else (1.0, 0.0)
    along = points[:, 0] * gx + points[:, 1] * gy if len(points) else _np.zeros(0)
    typical = sorted(c["storeys_shown"] for c in corpora if c["phase"] > 0) or [0]
    median = typical[len(typical) // 2]
    # Полосы очередей вдоль оси участка — по доле пятна очереди.
    phase_area: dict[int, float] = {}
    for c in corpora:
        if c["phase"] > 0:
            phase_area[c["phase"]] = phase_area.get(c["phase"], 0.0) + float(c["area_sqm"])
    total = sum(phase_area.values()) or 1.0
    order = _np.sort(along) if len(along) else along
    bands: dict[int, tuple[float, float]] = {}
    acc = 0.0
    for ph in sorted(phase_area):
        lo_q, hi_q = acc / total, (acc + phase_area[ph]) / total
        acc += phase_area[ph]
        if len(order):
            lo = order[min(len(order) - 1, int(lo_q * (len(order) - 1)))]
            hi = order[min(len(order) - 1, int(hi_q * (len(order) - 1)))]
            bands[ph] = (float(lo), float(hi))
    cap = 400.0
    near = _np.full(len(points), cap)
    placed: list[dict[str, Any]] = []
    rows: list[dict[str, Any]] = []
    # Сначала отдельные здания (у них свои участки), затем очереди по порядку.
    queue = [c for c in corpora if c["phase"] == 0] + [c for c in corpora if c["phase"] > 0]
    made = {} if made is None else made
    for c in queue:
        tower = c["phase"] > 0 and median > 0 and c["storeys_shown"] >= LAYOUT_TOWER_RATIO * median
        shape_key = (round(float(c["area_sqm"]), 1), c.get("depth_m"), tower)
        half = float(c.get("depth_m") or LAYOUT_CORPUS_DEPTH_M) / 2.0
        if shape_key not in made:
            # Места всех видов считаются один раз на форму дома: варианты
            # берут из них свои (периметр, ряды или всё).
            found = _mv_candidates(c, blocks, "mixed", north, tower)
            centre = _np.array([sum(p[0] * gx + p[1] * gy for p in k["ring"]) / len(k["ring"])
                                for k in found]) if found else None
            made[shape_key] = (found, _mv_dist_many(points, found, half)
                               if found and len(points) else None, centre)
        cands, dist, centre = made[shape_key]
        row = {"id": c["id"]}
        if not cands:
            rows.append(row)
            continue
        own = list(range(len(cands)))
        if variant != "mixed":
            want = ("section", "corner", "tower") if variant == "perimeter" else ("row", "tower")
            own = [i for i, k in enumerate(cands)
                   if k["kind"] in want and (k["kind"] != "tower" or bool(k["front"]) == (variant == "perimeter"))]
        if pack and centre is not None:
            band = bands.get(c["phase"])
            start = band[0] if band else float(centre.min())
            ranked = sorted(own, key=lambda i: (abs(float(centre[i]) - start), i))
        elif len(points):
            weight = _np.ones(len(points))
            band = bands.get(c["phase"])
            if band:
                weight = _np.where((along >= band[0] - 1) & (along <= band[1] + 1), 1.0, 0.15)
            sub = _np.array(own, dtype=int)
            cost = (_np.minimum(dist[sub], near[None, :]) * weight[None, :]).sum(axis=1)
            if band:
                cen = centre[sub]
                outside = _np.maximum(0.0, _np.maximum(band[0] - cen, cen - band[1]))
                cost = cost + outside * weight.sum() * 0.5
            ranked = [own[int(i)] for i in _np.argsort(cost, kind="stable")]
        else:
            ranked = own
        # Периметр не вместил дом — дом встаёт рядом внутри квартала
        # (двор с домом внутри), а не теряется.
        if variant == "perimeter":
            mine = set(own)
            rest = [i for i in range(len(cands)) if i not in mine]
            ranked = list(ranked) + rest
        tries = 0
        for idx in ranked:
            k = cands[int(idx)]
            tries += 1
            if tries > (400 if pack else 300):
                break
            if _mv_fits(k, c, by_block[k["block"]]["ring"], placed, site):
                ring = [[round(p[0], 2), round(p[1], 2)] for p in k["ring"]]
                bbox = (min(p[0] for p in ring), min(p[1] for p in ring),
                        max(p[0] for p in ring), max(p[1] for p in ring))
                placed.append({"ring_m": ring, "_bbox": bbox, "depth_m": c.get("depth_m"),
                               "storeys_shown": c["storeys_shown"], "shape": k["kind"]})
                row.update(ring_m=ring, block=k["block"], front=k["front"] or None,
                           shape=k["kind"], spines=k["spines"],
                           place={"corpus": c["id"], **k["place"]})
                if len(points):
                    near = _np.minimum(near, _mv_dist(points, k["spines"], half))
                break
        rows.append(row)
    return rows


def _mv_metrics(corpora: list[dict[str, Any]], rows: list[dict[str, Any]],
                points: "_np.ndarray", site: list[list[list[float]]],
                north: list[float] | None) -> dict[str, Any]:
    """Как вариант закрывает участок: сколько домов встало, самая далёкая от
    домов точка, пустой кусок и где он, доля домов с севера на юг."""
    placed = [(c, r) for c, r in zip(corpora, rows) if r.get("ring_m")]
    out: dict[str, Any] = {"placed": len(placed), "unplaced": len(corpora) - len(placed)}
    area = sum(abs(_ring_area(r)) for r in site)
    if len(points) and placed:
        near = _np.full(len(points), 1e9)
        for c, r in placed:
            spines = r.get("spines") or [[r["ring_m"][0], r["ring_m"][1]]]
            half = float(c.get("depth_m") or LAYOUT_CORPUS_DEPTH_M) / 2.0
            if not r.get("spines"):
                # Дом прежней расстановки — ось по длинной стороне.
                ring = r["ring_m"]
                e = max(_mv_edges(ring), key=lambda e: e[2])
                cx = sum(p[0] for p in ring) / len(ring)
                cy = sum(p[1] for p in ring) / len(ring)
                ux, uy = e[3]
                hl = e[2] / 2
                spines = [[[cx - ux * hl, cy - uy * hl], [cx + ux * hl, cy + uy * hl]]]
                half = abs(_ring_area(ring)) / e[2] / 2
            near = _np.minimum(near, _mv_dist(points, spines, half))
        ideal = _math.sqrt(area / max(1, len(placed)) / _math.pi)
        limit = max(LAYOUT_EMPTY_REACH_M, 1.5 * ideal)
        far = near > limit
        out["reach_m"] = round(float(near.max()), 1)
        out["empty_limit_m"] = round(limit, 1)
        out["empty_share"] = round(float(far.mean()), 3)
        if far.mean() > LAYOUT_EMPTY_SHARE:
            fx, fy = float(points[far, 0].mean()), float(points[far, 1].mean())
            cx, cy = float(points[:, 0].mean()), float(points[:, 1].mean())
            out["empty_where"] = _mv_where((fx, fy), (cx, cy), north)
            out["empty_sqm"] = round(float(far.mean()) * area)
    elif not placed:
        out.update(reach_m=None, empty_share=1.0)
    if north and placed:
        meridional = sum(float(c["area_sqm"]) for c, r in placed
                         if _mv_meridian_deg(_mv_long_axis(r["ring_m"]), north) <= LAYOUT_MERIDIONAL_DEG)
        latitudinal = [c for c, r in placed
                       if _mv_meridian_deg(_mv_long_axis(r["ring_m"]), north) >= 60.0
                       and r.get("shape") != "tower"]
        out["meridional_share"] = round(meridional / sum(float(c["area_sqm"]) for c, _ in placed), 3)
        out["latitudinal_count"] = len(latitudinal)
    out["corner_count"] = sum(1 for _, r in placed if r.get("shape") == "corner")
    return out


def massing_variants(corpora: list[dict[str, Any]], site: list[list[list[float]]],
                     blocks: list[dict[str, Any]], axis: dict[str, float] | None,
                     north: list[float] | None,
                     parts: list[dict[str, Any]] | None = None,
                     legacy: list[dict[str, Any]] | None = None) -> dict[str, dict[str, Any]]:
    """Варианты посадки → {вариант: {rows, metrics}}. Корпуса не меняются:
    `rows` — место каждого дома (или его отсутствие). `legacy` — корпуса,
    уже расставленные прежней расстановкой (вариант «рядами вдоль участка»)."""
    points = _mv_samples(site)
    made: dict[tuple, Any] = {}
    out: dict[str, dict[str, Any]] = {}
    for variant in LAYOUT_VARIANTS:
        if variant == "meridional" and not north:
            continue
        if variant == "rows":
            trial = [dict(c) for c in legacy] if legacy is not None else [dict(c) for c in corpora]
            if legacy is None:
                massing_place_engine(trial, blocks, axis)
            rows = [{"id": c["id"], **({k: c.get(k) for k in ("ring_m", "block", "front", "shape")}
                                       if c.get("ring_m") else {}),
                     **({"place": c["place"]} if c.get("place") and c.get("ring_m") else {})}
                    for c in trial]
        else:
            rows = _mv_place(corpora, parts or blocks, variant, north, axis, points, made,
                             site=site)
            if variant != "meridional" and any(not r.get("ring_m") for r in rows):
                # Тесно: плотный проход; берётся тот, где встало больше домов.
                packed = _mv_place(corpora, parts or blocks, variant, north, axis, points, made,
                                   pack=True, site=site)
                if sum(1 for r in packed if r.get("ring_m")) > sum(1 for r in rows if r.get("ring_m")):
                    rows = packed
        out[variant] = {"rows": rows, "metrics": _mv_metrics(corpora, rows, points, site, north)}
    return out


def massing_variant_pick(variants: dict[str, dict[str, Any]]) -> str:
    """Выбор движка: больше домов встало; затем меньше пустого участка; затем
    ближе самая далёкая точка; затем больше домов с севера на юг."""
    def key(name):
        m = variants[name]["metrics"]
        return (m["unplaced"], round(float(m.get("empty_share") or 0.0) / 0.03),
                round(float(m.get("reach_m") or 1e9) / 10.0),
                -float(m.get("meridional_share") or 0.0), LAYOUT_VARIANTS.index(name))
    return min(variants, key=key)


_VARIANTS_CACHE: dict[str, Any] = {}


def massing_variants_cached(corpora: list[dict[str, Any]], site: list[list[list[float]]],
                            blocks: list[dict[str, Any]], axis: dict[str, float] | None,
                            north: list[float] | None,
                            parts: list[dict[str, Any]] | None = None,
                            legacy: list[dict[str, Any]] | None = None) -> dict[str, dict[str, Any]]:
    """Варианты с памятью по входам: расчёт зовёт схему на каждом пересчёте."""
    key = hashlib.sha256(json.dumps(
        [[[round(p[0], 2), round(p[1], 2)] for p in r] for r in site]
        + [[c["id"], round(c["area_sqm"], 2), c["storeys_shown"], c.get("depth_m")] for c in corpora]
        + [[round(v, 4) for v in north] if north else None],
        separators=(",", ":"), default=str).encode("utf-8")).hexdigest()
    hit = _VARIANTS_CACHE.get(key)
    if hit is None:
        hit = massing_variants(corpora, site, blocks, axis, north, parts, legacy)
        if len(_VARIANTS_CACHE) > 32:
            _VARIANTS_CACHE.clear()
        _VARIANTS_CACHE[key] = hit
    return copy.deepcopy(hit)


def massing_apply_variant(corpora: list[dict[str, Any]], variant: dict[str, Any]) -> None:
    """Места домов варианта → корпуса схемы (`ring_m`, квартал, фронт, форма)."""
    rows = {r["id"]: r for r in variant["rows"]}
    for c in corpora:
        for k in ("ring_m", "block", "front", "shape", "place", "spines", "_bbox"):
            c.pop(k, None)
        r = rows.get(c["id"]) or {}
        if r.get("ring_m"):
            for k in ("ring_m", "block", "front", "shape", "place", "spines"):
                if r.get(k) is not None:
                    c[k] = copy.deepcopy(r[k])


# --- Секции, пожарные проезды, вид сверху ---------------------------------------

def massing_sections(c: dict[str, Any]) -> dict[str, Any]:
    """Секции дома: число рядовых и угловых, линии между ними (для рисунка)."""
    ring = c.get("ring_m") or []
    if not ring:
        return {"count": 0, "corner": 0, "lines": []}
    d = float(c.get("depth_m") or LAYOUT_CORPUS_DEPTH_M)
    lines: list[list[list[float]]] = []
    if c.get("shape") == "corner" and len(ring) == 6:
        # Крылья: от угла (ring[1]) к концам ring[0] и ring[2]; угловая секция —
        # квадрат на углу и по 6 м крыльев.
        corner, inner = ring[1], ring[4]
        count = 1
        for end, end_in in ((ring[0], ring[5]), (ring[2], ring[3])):
            arm = _math.hypot(end[0] - corner[0], end[1] - corner[1])
            ux, uy = (end[0] - corner[0]) / arm, (end[1] - corner[1]) / arm
            start = d + 6.0
            rest = arm - start
            n = max(1, int(round(rest / LAYOUT_SECTION_LENGTH_M))) if rest > 6 else 0
            vx, vy = end_in[0] - end[0], end_in[1] - end[1]
            for k in range(n):
                t = start + rest * k / n
                p = [corner[0] + ux * t, corner[1] + uy * t]
                lines.append([[round(p[0], 2), round(p[1], 2)],
                              [round(p[0] + vx, 2), round(p[1] + vy, 2)]])
            count += n
        return {"count": count, "corner": 1, "lines": lines}
    e = max(_mv_edges(ring), key=lambda e: e[2])
    a, b, length, (ux, uy) = e
    if c.get("shape") == "tower" or length < LAYOUT_SECTION_LENGTH_M * 1.4:
        return {"count": 1, "corner": 0, "lines": []}
    n = max(1, int(round(length / LAYOUT_SECTION_LENGTH_M)))
    # Поперечник дома — от длинной стороны к противоположной.
    idx = next(i for i in range(len(ring)) if ring[i] == a)
    opp = ring[(idx + 2) % len(ring)] if len(ring) == 4 else ring[(idx + 2) % len(ring)]
    nx, ny = -uy, ux
    depth = (opp[0] - a[0]) * nx + (opp[1] - a[1]) * ny
    for k in range(1, n):
        t = length * k / n
        p = [a[0] + ux * t, a[1] + uy * t]
        lines.append([[round(p[0], 2), round(p[1], 2)],
                      [round(p[0] + nx * depth, 2), round(p[1] + ny * depth, 2)]])
    return {"count": n, "corner": 0, "lines": lines}


def _mv_fire_spec(height: float) -> tuple[float, float, int]:
    """(от стены до проезда, ширина проезда, сколько длинных сторон) — допущение."""
    offset = 5.0 if height <= LAYOUT_FIRE_HIGH_M else 8.0
    width = 3.5 if height <= 13.0 else (4.2 if height <= 46.0 else 6.0)
    sides = 1 if height <= LAYOUT_FIRE_HIGH_M else 2
    return offset, width, sides


def massing_fire_lanes(buildings: list[dict[str, Any]], site_rings: list[list[list[float]]]
                       ) -> list[dict[str, Any]]:
    """Где у каждого дома место для пожарного проезда: полоса вдоль длинной
    стороны, на расстоянии от стены, внутри участка и не по другим домам.
    → по дому: {id, lanes: [кольца], need, ok}."""
    out = []
    for b in buildings:
        ring = b.get("ring_m") or []
        if len(ring) < 3:
            continue
        height = _mv_height(b)
        offset, width, need = _mv_fire_spec(height)
        sign = 1.0 if _ring_area(ring) > 0 else -1.0
        d = float(b.get("depth_m") or LAYOUT_CORPUS_DEPTH_M)
        edges = [e for e in _mv_edges(ring) if e[2] >= max(2 * d, LAYOUT_SECTION_LENGTH_M) - 1e-6] \
            or [max(_mv_edges(ring), key=lambda e: e[2])]
        lanes = []
        street = 0
        for a, bb, length, (ux, uy) in edges:
            # Наружу — вправо от обхода против часовой стрелки.
            nx, ny = uy * sign, -ux * sign
            lane = [[a[0] + nx * offset, a[1] + ny * offset],
                    [bb[0] + nx * offset, bb[1] + ny * offset],
                    [bb[0] + nx * (offset + width), bb[1] + ny * (offset + width)],
                    [a[0] + nx * (offset + width), a[1] + ny * (offset + width)]]
            if any(o is not b and o.get("ring_m") and _mv_overlap(lane, o["ring_m"])
                   for o in buildings) or _mv_overlap(lane, ring):
                continue
            if not any(_poly_inside(lane, r) for r in site_rings):
                # Сторона смотрит на границу участка: проезд возможен по улице
                # за ней, если улица там есть — этого в данных нет.
                street += 1
                continue
            lanes.append([[round(p[0], 2), round(p[1], 2)] for p in lane])
        out.append({"id": b.get("id"), "lanes": lanes, "need": need,
                    "ok": len(lanes) >= need, "street_ok": len(lanes) + street >= need,
                    "offset_m": offset, "width_m": width, "height_m": height})
    return out


def massing_min_gaps(buildings: list[dict[str, Any]]) -> dict[str, Any]:
    """Наименьший разрыв на плане и разрыв, которого не хватает (если есть)."""
    placed = [b for b in buildings if b.get("ring_m")]
    least = None
    short = None
    for i in range(len(placed)):
        for j in range(i + 1, len(placed)):
            p, q = placed[i], placed[j]
            real = _mv_poly_dist(p["ring_m"], q["ring_m"])
            need, kind, have = massing_required_gap(p, q)
            if least is None or real < least["gap_m"]:
                least = {"gap_m": round(real, 1), "need_m": round(need, 1), "kind": kind}
            if have < need - 0.5 and (short is None or need - have > short["need_m"] - short["gap_m"]):
                short = {"gap_m": round(have, 1), "need_m": round(need, 1), "kind": kind,
                         "a": p.get("label"), "b": q.get("label")}
    return {"least": least, "short": short}


def massing_plan_view(layout: dict[str, Any], blocks: list[dict[str, Any]],
                      lanes: list[dict[str, Any]], north: list[float] | None
                      ) -> dict[str, Any]:
    """Вид сверху для страницы: север вверху (если стороны света известны),
    участок, граница отступа, кварталы, дома с секциями, пожарные проезды."""
    if north:
        # Поворот: север схемы → вверх.
        nx, ny = north
        def turn(p):
            return [round(p[0] * ny - p[1] * nx, 2), round(p[0] * nx + p[1] * ny, 2)]
    else:
        def turn(p):
            return [round(p[0], 2), round(p[1], 2)]

    def rings(rr):
        return [[turn(p) for p in r] for r in rr if len(r) >= 3]

    colors: dict[str, str] = {}
    for b in layout.get("buildings") or []:
        colors[b["id"]] = b.get("color") or LAYOUT_PHASE_COLORS[(max(1, b["phase"]) - 1)
                                                                 % len(LAYOUT_PHASE_COLORS)]
    lane_by = {r["id"]: r for r in lanes}
    return {
        "north_up": bool(north),
        "site": rings(layout.get("site_rings") or []),
        "inner": rings(layout.get("underground_rings") or []),
        "blocks": [{"id": b["id"], "ring": [turn(p) for p in b["ring"]]} for b in blocks],
        "buildings": [{"id": b["id"], "ring": [turn(p) for p in b["ring_m"]],
                       "color": colors.get(b["id"]), "storeys": b["storeys_shown"],
                       "shape": b.get("shape"),
                       "sections": [[turn(p) for p in line]
                                    for line in (b.get("sections") or {}).get("lines") or []]}
                      for b in layout.get("buildings") or [] if b.get("ring_m")],
        "lanes": [[turn(p) for p in lane] for r in lanes for lane in r["lanes"]],
        "lanes_missing": [r["id"] for r in lanes if not r["ok"]],
    }


def _mv_plural(n: int, one: str, few: str, many: str) -> str:
    n = abs(int(n))
    if n % 10 == 1 and n % 100 != 11:
        return one
    if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14:
        return few
    return many


def massing_analysis_lines(analysis: dict[str, Any], variants: dict[str, dict[str, Any]],
                           chosen: str, buildings: list[dict[str, Any]],
                           lanes: list[dict[str, Any]], gaps: dict[str, Any],
                           north: list[float] | None, chooser: str = "engine") -> list[str]:
    """Разбор участка и посадки простыми фразами — для карточки и PDF."""
    lines: list[str] = []
    parts = analysis.get("parts") or []
    if parts:
        words = []
        for p in parts:
            hold = {"perimeter": "держит дома по периметру с двором внутри",
                    "row": "держит один ряд домов",
                    "narrow": "уже одного дома"}[p["holds"]]
            direction = f", вытянута {p['direction']}" if p.get("direction") else ""
            words.append(f"часть {p['id'][1:]} — около {_fmt_ru(p['length_m'])} × "
                         f"{_fmt_ru(p['width_m'])} м{direction}, {hold}")
        count = len(parts)
        lines.append(f"Участок без отступов от границ делится на {count} "
                     f"{_mv_plural(count, 'часть', 'части', 'частей')}: " + "; ".join(words) + ".")
    if not north:
        lines.append("Стороны света на схеме неизвестны: у участка нет контура на карте, "
                     "поэтому ориентацию домов по солнцу мы не оценивали.")
    m = variants[chosen]["metrics"]
    who = ("Помощник Платон выбрал застройку" if chooser == "plato" else
           "Выбрана застройка")
    lines.append(f"{who} «{LAYOUT_VARIANT_NAMES[chosen]}»: {LAYOUT_VARIANT_WHAT[chosen]}.")
    others = []
    for name, v in variants.items():
        if name == chosen:
            continue
        om = v["metrics"]
        if om["unplaced"] > m["unplaced"]:
            others.append(f"«{LAYOUT_VARIANT_NAMES[name]}» — не встают "
                          f"{om['unplaced']} {_mv_plural(om['unplaced'], 'дом', 'дома', 'домов')}")
        elif om.get("empty_where") and om.get("empty_share", 0) > float(m.get("empty_share") or 0):
            others.append(f"«{LAYOUT_VARIANT_NAMES[name]}» — без домов остаётся кусок "
                          f"{om['empty_where']} участка, около {_fmt_ru(om.get('empty_sqm') or 0)} м²")
        elif (om.get("reach_m") or 0) > (m.get("reach_m") or 0) + 5:
            others.append(f"«{LAYOUT_VARIANT_NAMES[name]}» — дома дальше от края участка: "
                          f"самая далёкая точка в {_fmt_ru(om['reach_m'])} м от дома")
    if others:
        lines.append("Другие варианты: " + "; ".join(others) + ".")
    placed = [b for b in buildings if b.get("ring_m")]
    homes = [b for b in placed if b.get("phase", 0) > 0]
    sections = sum((b.get("sections") or {}).get("count", 0) for b in homes)
    corners = sum((b.get("sections") or {}).get("corner", 0) for b in homes)
    if homes:
        others_n = len(placed) - len(homes)
        text = (f"Жилых домов на схеме — {len(homes)}"
                + (f" (и {others_n} {_mv_plural(others_n, 'корпус', 'корпуса', 'корпусов')} "
                   "отдельных зданий)" if others_n else "")
                + f", в них около {sections} "
                f"{_mv_plural(sections, 'секции', 'секций', 'секций')} длиной около "
                f"{_fmt_ru(LAYOUT_SECTION_LENGTH_M)} м и глубиной "
                f"{_fmt_ru(LAYOUT_CORPUS_DEPTH_M)} м")
        text += (f", из них {corners} {_mv_plural(corners, 'угловая', 'угловые', 'угловых')}."
                 if corners else ".")
        lines.append(text)
    if m.get("empty_where"):
        lines.append(f"Кусок участка {m['empty_where']} (около {_fmt_ru(m.get('empty_sqm') or 0)} м²) "
                     f"остаётся без домов: дальше {_fmt_ru(m['empty_limit_m'])} м от ближайшего дома. "
                     "Так выходит, когда пятна застройки в расчёте мало для этой земли; там "
                     "можно разместить двор, сквер или отдельное здание.")
    elif m.get("reach_m") is not None:
        lines.append(f"Дома разнесены по всему участку, без пустого края: любая его точка не "
                     f"дальше {_fmt_ru(m['reach_m'])} м от ближайшего дома.")
    if north and placed:
        lat = int(m.get("latitudinal_count") or 0)
        share = float(m.get("meridional_share") or 0.0)
        text = (f"По солнцу: {round(share * 100)} % пятна домов вытянуты с севера на юг, их "
                "окна смотрят на восток и запад и получают солнце утром и вечером.")
        if lat:
            text += (f" {lat} {_mv_plural(lat, 'дом вытянут', 'дома вытянуты', 'домов вытянуты')} "
                     "с запада на восток: квартиры, у которых окна только на север, солнца не "
                     "получат, поэтому в таких домах нужны квартиры с окнами на обе стороны.")
        lines.append(text + " Это оценка по направлению домов, а не расчёт инсоляции.")
    least, short = gaps.get("least"), gaps.get("short")
    if least:
        text = (f"Разрывы между домами: между длинными сторонами — не меньше "
                f"{_fmt_ru(LAYOUT_GAP_LONG_MIN_M)} м и не меньше 0,8 высоты более высокого дома, "
                f"между торцами — {_fmt_ru(LAYOUT_GAP_IN_ROW_M)} м. Наименьший разрыв на схеме — "
                f"{_fmt_ru(least['gap_m'])} м.")
        if short:
            text += (f" Между домами «{short['a']}» и «{short['b']}» {_fmt_ru(short['gap_m'])} м, "
                     f"а нужно {_fmt_ru(short['need_m'])} м.")
        lines.append(text + " Это наше допущение, а не норма: чисел бытовых разрывов и "
                     "инсоляции в нашей библиотеке нормативов нет.")
    missing = [r for r in lanes if not r["street_ok"]]
    by_street = [r for r in lanes if r["street_ok"] and not r["ok"]]
    names = {b.get("id"): b.get("label") for b in buildings}

    def listed(rows):
        return ("; ".join(str(names.get(r["id"]) or r["id"]) for r in rows[:4])
                + (" и другие" if len(rows) > 4 else ""))
    if lanes:
        if missing or by_street:
            text = ("Пожарный проезд — вдоль длинной стороны дома в 5–8 м от стены (у домов "
                    "выше 28 м — в 8–10 м и с двух сторон).")
            if by_street:
                text += (f" У {len(by_street)} {_mv_plural(len(by_street), 'дома', 'домов', 'домов')} "
                         f"проезд на участке есть не со всех нужных сторон, недостающий возможен "
                         f"только по улице за границей участка — проверьте, что она там есть "
                         f"({listed(by_street)}).")
            if missing:
                text += (f" У {len(missing)} {_mv_plural(len(missing), 'дома', 'домов', 'домов')} "
                         f"места для проезда нет: мешают соседние дома ({listed(missing)}).")
            lines.append(text)
        else:
            lines.append("Пожарный проезд: у каждого дома вдоль длинной стороны есть место для "
                         "проезда — в 5–8 м от стены (у домов выше 28 м — в 8–10 м и с двух "
                         "сторон). Во дворе это проезд по укреплённому газону, машины во двор "
                         "не заезжают.")
        lines.append("Проезды — наше допущение по своду правил СП 4.13130.2013 (раздел 8); его "
                     "текста в нашей библиотеке нормативов нет.")
    lines.append("Не проверяли: красные линии и улицы вокруг участка (их нет в данных), "
                 "расчёт инсоляции по часам, сети и рельеф.")
    return lines


def massing_variants_brief(variants: dict[str, dict[str, Any]], analysis: dict[str, Any],
                           corpora: list[dict[str, Any]]) -> dict[str, Any]:
    """Что получает Платон, когда выбирает вариант посадки жилья."""
    names = {c["id"]: c.get("label") for c in corpora}
    out = []
    for name, v in variants.items():
        m = v["metrics"]
        out.append({"id": name, "name": LAYOUT_VARIANT_NAMES[name],
                    "idea": LAYOUT_VARIANT_WHAT[name],
                    "houses_placed": m["placed"], "houses_not_placed": m["unplaced"],
                    "farthest_point_from_houses_m": m.get("reach_m"),
                    "empty_part_share": m.get("empty_share"),
                    "empty_part_where": m.get("empty_where") or "",
                    "share_north_south": m.get("meridional_share"),
                    "houses_west_east": m.get("latitudinal_count"),
                    "corner_houses": m.get("corner_count"),
                    "houses": [{"house": names.get(r["id"]), "part": r.get("block"),
                                "shape": r.get("shape")} for r in v["rows"] if r.get("ring_m")]})
    return {"site": analysis, "variants": out, "engine_choice": massing_variant_pick(variants)}


# --- Баланс земли и предложение «ниже и плотнее» --------------------------------
#
# Владелец 31.10.2026: «почему столько пустого пространства остаётся». Ответ —
# решение (AskUserQuestion): подписать, чем занята земля между домами, и, когда
# свободной земли много, предложить вариант ниже и плотнее — те же метры, дома
# 8–12 этажей, кварталы замкнуты. Этажность в расчёте меняется только кнопкой.

# Свободная земля (сверх домов, двора по норме, проездов, стоянок и отступов)
# больше этой доли участка — посадка предлагает этажность ниже.
LAYOUT_FREE_SHARE_OFFER = 0.20
# После предложения свободной земли остаётся не больше этой доли.
LAYOUT_FREE_SHARE_TARGET = 0.10
# Этажность «ниже и плотнее» — из этих чисел, не выше типовой. Допущение:
# квартальная застройка 8–12 этажей — обычная практика Москвы и МО.
LAYOUT_DENSER_STOREYS = (12, 10, 9, 8)


def massing_land_balance(massing: dict[str, Any]) -> dict[str, Any]:
    """Чем занята земля участка → строки (подпись, м², доля) и свободный остаток.

    Те же числа, что баланс территории расчёта (`site_massing`): пятна зданий,
    двор по норме, проезды, открытые стоянки, отступы, участки школы и сада
    сверх их пятна. Остаток — земля, которую расчёт ничем не занял."""
    site = float(massing.get("site_sqm") or 0.0)
    if site <= 0:
        return {"rows": [], "free_sqm": 0.0, "free_share": 0.0}
    objects = massing.get("objects") or []
    plots_extra = max(0.0, float(massing.get("objects_plot_sqm") or 0.0)
                      - sum(float(o.get("footprint_sqm") or 0.0) for o in objects))
    rows = [
        ("Под домами и зданиями", float(massing.get("built_sqm") or 0.0)),
        ("Двор у домов по норме", float(massing.get("yard_sqm") or 0.0)),
        ("Проезды, тротуары, пожарные проезды", float(massing.get("driveways_sqm") or 0.0)),
        ("Открытые стоянки", float(massing.get("surface_parking_sqm") or 0.0)),
        ("Отступы от границ участка", float(massing.get("setbacks_sqm") or 0.0)),
        ("Участки школы и детского сада вокруг зданий", plots_extra),
    ]
    used = sum(v for _, v in rows)
    free = max(0.0, site - used)
    out = [{"label": label, "sqm": round(v), "share": round(v / site, 3)} for label, v in rows if v > 0.5]
    out.append({"label": "Свободно: сквер, запас под следующие очереди или здания",
                "sqm": round(free), "share": round(free / site, 3), "free": True})
    return {"rows": out, "free_sqm": round(free), "free_share": round(free / site, 3),
            "site_sqm": round(site), "over_sqm": round(max(0.0, used - site))}


def massing_denser_offer(x: dict[str, Any], massing: dict[str, Any],
                         phases: list[dict[str, Any]], site: list[list[list[float]]],
                         north: list[float] | None, balance: dict[str, Any],
                         limit: float) -> dict[str, Any] | None:
    """Свободной земли много — та же площадь домами ниже: этажность, пятно,
    сколько земли останется свободной, и вид сверху этой посадки. Нет — None.

    Пятно — жилая наземная площадь ÷ этажность, не больше процента застройки
    расчёта (`coverage_sqm`). Берётся самая высокая этажность из
    `LAYOUT_DENSER_STOREYS`, при которой свободной земли остаётся не больше
    10 % участка и все дома встают; такой нет — самая низкая, где все встают."""
    site_sqm = float(massing.get("site_sqm") or 0.0)
    gns = float(massing.get("residential_gns_sqm") or 0.0)
    fp_now = float(massing.get("footprint_sqm") or 0.0)
    typical = float(massing.get("typical_storeys") or 0.0)
    if (site_sqm <= 0 or gns <= 0 or fp_now <= 0 or not site
            or massing.get("footprint_origin") == "manual"
            or float(balance.get("free_share") or 0.0) < LAYOUT_FREE_SHARE_OFFER):
        return None
    cap = float(massing.get("coverage_sqm") or 0.0) or 1e18
    free_now = float(balance.get("free_sqm") or 0.0)
    axis = massing_strip_axis(site)
    blocks = massing_blocks(site, axis)
    parts = massing_parts(site, axis)
    fallback = None
    for storeys in LAYOUT_DENSER_STOREYS:
        if storeys >= typical - 1e-9:
            continue
        fp = min(gns / storeys, cap)
        if fp <= fp_now * 1.05:
            continue
        free_after = free_now - (fp - fp_now)
        if free_after < 0:
            continue
        trial = {**massing, "footprint_sqm": fp, "footprint_origin": "estimate"}
        corpora = _layout_corpora(x, trial, phases, fp, limit)
        if not corpora or len(corpora) > LAYOUT_MAX_DRAWN_CORPORA:
            continue
        legacy = [dict(c) for c in corpora]
        massing_place_engine(legacy, blocks, axis)
        variants = massing_variants_cached(corpora, site, blocks, axis, north, parts, legacy)
        chosen = massing_variant_pick(variants)
        if variants[chosen]["metrics"]["unplaced"] > 0:
            continue
        massing_apply_variant(corpora, variants[chosen])
        for c in corpora:
            c["sections"] = massing_sections(c)
        offer = {"storeys": int(storeys) if fp < cap else int(_math.ceil(gns / fp)),
                 "footprint_sqm": round(fp), "share": round(fp / site_sqm, 3),
                 "free_sqm_now": round(free_now), "free_sqm_after": round(free_after),
                 "variant": chosen, "_corpora": corpora, "_parts": parts}
        if free_after <= LAYOUT_FREE_SHARE_TARGET * site_sqm:
            return offer
        fallback = offer
    return fallback


def massing_denser_text(offer: dict[str, Any], typical: float) -> str:
    """Предложение «ниже и плотнее» простыми словами."""
    return (f"Свободной земли на участке много — около {_fmt_ru(offer['free_sqm_now'])} м². "
            f"Ту же площадь квартир можно поставить домами по {offer['storeys']} этажей вместо "
            f"{_fmt_ru(typical)}: пятно домов вырастет до {_fmt_ru(offer['footprint_sqm'])} м² "
            f"({round(offer['share'] * 100)} % участка), застройка станет "
            f"«{LAYOUT_VARIANT_NAMES[offer['variant']]}», а свободной земли останется около "
            f"{_fmt_ru(offer['free_sqm_after'])} м². Этажность в расчёте поменяется, только если "
            "нажать кнопку ниже; вместе с ней пересчитаются пятно, подземная часть и стоимость.")


def massing_free_land_line(massing: dict[str, Any], balance: dict[str, Any]) -> str:
    """Почему земля свободна — фраза разбора, когда свободного много."""
    share = float(balance.get("free_share") or 0.0)
    if share < LAYOUT_FREE_SHARE_OFFER:
        return ""
    site = float(massing.get("site_sqm") or 0.0)
    gns = float(massing.get("above_gns_sqm") or 0.0)
    typical = float(massing.get("typical_storeys") or 0.0)
    density = gns / (site / 10000.0) if site > 0 else 0.0
    return (f"Свободно около {_fmt_ru(balance['free_sqm'])} м² ({round(share * 100)} % участка): "
            f"дома, двор по норме, проезды, стоянки и отступы занимают остальное. Так выходит, "
            f"потому что наземной площади в расчёте около {_fmt_ru(density)} м² на гектар участка, "
            f"а дома — по {_fmt_ru(typical)} этажей. Землю займут дома ниже этажами "
            "(вариант ниже) или больше площади квартир; иначе свободная земля — это сквер "
            "или запас под следующие очереди.")
