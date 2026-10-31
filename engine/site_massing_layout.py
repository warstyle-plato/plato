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
# Глубина корпуса офиса и других отдельных нежилых зданий (не школы и не сада) —
# обычная глубина офисного здания (владелец 23.10.2026); корпус длиной до 100 м —
# до 2 400 м² пятна. Это умолчание схемы, а не норматив.
LAYOUT_OTHER_DEPTH_M = 24.0
LAYOUT_GAP_IN_ROW_M = 12.0
LAYOUT_GAP_BETWEEN_ROWS_M = 15.0
# Самый длинный корпус; длиннее — очередь делится на корпуса по длине.
LAYOUT_CORPUS_MAX_LENGTH_M = 100.0
# Больше корпусов схема не рисует (владелец 23.10.2026: «в таких масштабных
# случаях лучше и не рисовать»); до этого корпуса расставлены сеткой по всему
# участку, а номера и легенда — по группам (очередь, отдельное здание).
LAYOUT_MAX_DRAWN_CORPORA = 40
# Высота этажа только для картинки: этажность считает ТЭП, не она.
LAYOUT_STOREY_HEIGHT_M = 3.0
# Полоса на картинке: ось участка поворачивается на −30° от оси x схемы, и в
# изометрии полоса идёт слева направо с лёгким подъёмом.
LAYOUT_STRIP_SCREEN_TURN_DEG = 30.0
# Цвета очередей: одна палитра для страницы и PDF.
LAYOUT_PHASE_COLORS = ("#2f6fb3", "#d9822b", "#3f9a5b", "#9b59b6", "#c0392b", "#16a2a2")
# Отдельные здания на своих участках: соцобъекты и прочие — свои цвета.
LAYOUT_OBJECT_COLORS = {"social": "#a1745a", "other": "#6f7f8c"}


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


# Объекты ЕГРН, контур которых — не земля участка: здание и помещение. Тип —
# из ответа поиска (`kind`, `_normalize_nspd_feature`), а не по номеру.
SITE_NOT_LAND_KINDS = ("building", "premise")


def _site_lookup_items(x: dict[str, Any]) -> list[dict[str, Any]]:
    lookup = x.get("_land_lookup") or {}
    items = lookup.get("results") if isinstance(lookup, dict) else None
    if not isinstance(items, list):
        items = [lookup] if isinstance(lookup, dict) else []
    return [item for item in items if isinstance(item, dict)]


def _item_rings(item: dict[str, Any]) -> list[list[list[float]]]:
    return [ring for ring in (item.get("contour_merc") or [])
            if isinstance(ring, list) and len(ring) >= 3]


def _site_rings_m(x: dict[str, Any]
                  ) -> tuple[list[list[list[float]]], dict[str, float], dict[str, Any]]:
    """Контур территории из ЕГРН (`_land_lookup`) в метрах от её центра →
    (кольца, рамка, состав).

    Контур — объединение колец ВСЕХ найденных земельных участков поиска;
    здания и помещения (`SITE_NOT_LAND_KINDS`) — не земля, их пятно в контур
    не идёт. Состав — что вошло, что нет и почему: `parcels` (номер и площадь
    контура, м²), `not_land`, `missing` (не найден или без границ),
    `repeated` (номер повторён — земля одна), `inside` (участок целиком внутри
    другого, например часть единого землепользования) и `overlap` (частичное
    наложение — сумма площадей считает общую часть дважды).

    Кольца приходят в веб-меркаторе: метр в нём растянут на 1/cos(широты),
    поэтому координаты умножаются на cos(широты центра). Рамка — центр и
    множитель: по ней корпуса возвращаются в меркатор для карты участка.
    """
    items = _site_lookup_items(x)
    land = []
    seen: set[str] = set()
    repeated: list[str] = []
    for item in items:
        if not (item.get("found", True) and _item_rings(item)
                and str(item.get("kind") or "land") not in SITE_NOT_LAND_KINDS):
            continue
        # Один участок, переданный дважды, — одна земля: номер сверяется без
        # ведущих нулей (`_cadastral_key`), как у карты территории в боте.
        key = _cadastral_key(item.get("cadastral_number")) if item.get("cadastral_number") else ""
        if key and key in seen:
            repeated.append(str(item.get("cadastral_number")))
            continue
        seen.add(key)
        land.append(item)
    parts: dict[str, Any] = {
        "parcels": [], "missing": [], "repeated": repeated, "inside": [], "overlap": [],
        "not_land": [str(item.get("cadastral_number") or "") for item in items
                     if item.get("found", True)
                     and str(item.get("kind") or "land") in SITE_NOT_LAND_KINDS]}
    parts["missing"] = [str(item.get("cadastral_number") or "") for item in items
                        if (not item.get("found", True)
                            or (str(item.get("kind") or "land") not in SITE_NOT_LAND_KINDS
                                and not _item_rings(item)))
                        and item.get("cadastral_number")]
    rings = [ring for item in land for ring in _item_rings(item)]
    if not rings:
        return [], {}, parts
    xs = [p[0] for ring in rings for p in ring]
    ys = [p[1] for ring in rings for p in ring]
    cx, cy = (min(xs) + max(xs)) / 2.0, (min(ys) + max(ys)) / 2.0
    lat = _math.degrees(2 * _math.atan(_math.exp(cy / 6378137.0)) - _math.pi / 2)
    k = _math.cos(_math.radians(lat))
    own_rings = []
    for item in land:
        own = [_clean_ring([[(p[0] - cx) * k, (p[1] - cy) * k] for p in ring])
               for ring in _item_rings(item)]
        own_rings.append((str(item.get("cadastral_number") or ""),
                          [ring for ring in own if len(ring) >= 3]))
    # Наложения. Участок целиком внутри другого (часть единого землепользования
    # и оно само) — его земля уже в контуре большего: в контур он не идёт.
    # Частичное наложение геометрией не вычитается (объединения многоугольников
    # здесь нет) — сумма площадей считает общую часть дважды, и это названо.
    kept: list[tuple[str, list[list[list[float]]]]] = []
    area = [sum(abs(_ring_area(r)) for r in own) for _, own in own_rings]
    for i, (number, own) in enumerate(own_rings):
        # Внешний — больший участок; у равных (один контур под двумя номерами)
        # внешним считается тот, что раньше в списке поиска.
        host = next((own_rings[j][0] for j in range(len(own_rings))
                     if j != i and own and own_rings[j][1]
                     and (area[j] > area[i] or (area[j] == area[i] and j < i))
                     and all(any(_poly_inside(r, outer) for outer in own_rings[j][1])
                             for r in own)), None)
        if host is not None:
            parts["inside"].append((number, host))
            continue
        kept.append((number, own))
    for i, (a, rings_a) in enumerate(kept):
        for b, rings_b in kept[i + 1:]:
            if any(_rings_overlap(ra, rb) for ra in rings_a for rb in rings_b):
                parts["overlap"].append((a, b))
    out: list[list[list[float]]] = []
    for number, own in kept:
        out.extend(own)
        parts["parcels"].append({"number": number,
                                 "area_sqm": sum(abs(_ring_area(r)) for r in own)})
    return out, {"cx": cx, "cy": cy, "k": k}, parts


def _rings_overlap(a: list[list[float]], b: list[list[float]]) -> bool:
    """Два кольца накладываются площадью: стороны пересекаются или одно внутри
    другого. Касание по общей границе — не наложение (соседние участки)."""
    def shrink(ring):
        cx = sum(p[0] for p in ring) / len(ring)
        cy = sum(p[1] for p in ring) / len(ring)
        return [[cx + (p[0] - cx) * 0.999, cy + (p[1] - cy) * 0.999] for p in ring]
    sa, sb = shrink(a), shrink(b)
    for i in range(len(sa)):
        for j in range(len(sb)):
            if _segments_cross(sa[i], sa[(i + 1) % len(sa)], sb[j], sb[(j + 1) % len(sb)]):
                return True
    return _inside(tuple(sa[0]), [sb]) or _inside(tuple(sb[0]), [sa])


def _site_overlap_note(parts: dict[str, Any]) -> str:
    """Частичное наложение участков — простыми словами (одна фраза на схему и
    на причину, по которой корпусов нет на карте)."""
    pairs = "; ".join(f"{a} и {b}" for a, b in parts.get("overlap", [])[:3])
    return (f"Границы участков в госреестре накладываются друг на друга ({pairs}): общая "
            "часть в сумме их площадей посчитана дважды.")


def _merc_rings_m(rings: list[list[list[float]]]
                  ) -> tuple[list[list[list[float]]], dict[str, float]]:
    """Кольца контура КРТ (веб-меркатор) → кольца в метрах от их центра и рамка.

    Тот же перевод, что у `_site_rings_m`: метр меркатора растянут на
    1/cos(широты), координаты умножаются на cos(широты центра).
    """
    rings = [ring for ring in rings if isinstance(ring, list) and len(ring) >= 3]
    if not rings:
        return [], {}
    xs = [p[0] for ring in rings for p in ring]
    ys = [p[1] for ring in rings for p in ring]
    cx, cy = (min(xs) + max(xs)) / 2.0, (min(ys) + max(ys)) / 2.0
    lat = _math.degrees(2 * _math.atan(_math.exp(cy / 6378137.0)) - _math.pi / 2)
    k = _math.cos(_math.radians(lat))
    out = [_clean_ring([[(p[0] - cx) * k, (p[1] - cy) * k] for p in ring]) for ring in rings]
    return [ring for ring in out if len(ring) >= 3], {"cx": cx, "cy": cy, "k": k}


def _site_map_note(parts: dict[str, Any], site_sqm: float, contour_sqm: float) -> str:
    """Почему корпуса нельзя показать на карте участка — простыми словами:
    какие участки найдены, их сумма, площадь в расчёте и что не вошло."""
    parcels = parts.get("parcels") or []
    shown = "; ".join(f"{p['number'] or 'без номера'} — {_fmt_ru(p['area_sqm'])} м²"
                      for p in parcels[:6])
    if len(parcels) > 6:
        shown += f" и ещё {len(parcels) - 6}"
    if len(parcels) == 1:
        text = (f"Корпуса на карте участка не показаны: в госреестре найден один участок "
                f"({shown}), а площадь участка в расчёте — {_fmt_ru(site_sqm)} м². Похоже, "
                "найдена не вся территория проекта.")
    elif parcels:
        text = (f"Корпуса на карте участка не показаны: найденные в госреестре участки "
                f"({shown}) вместе дают {_fmt_ru(contour_sqm)} м², а площадь участка в "
                f"расчёте — {_fmt_ru(site_sqm)} м². Похоже, найдена не вся территория проекта.")
    else:
        text = "Корпуса на карте участка не показаны: границ участка из госреестра нет."
    names = lambda items: ", ".join(items[:5]) + (f" и ещё {len(items) - 5}" if len(items) > 5 else "")
    if parts.get("missing"):
        text += f" Не найдены в госреестре или без границ: {names(parts['missing'])}."
    if parts.get("overlap"):
        text += " " + _site_overlap_note(parts)
    if parts.get("not_land"):
        text += (f" Здания и помещения ({names(parts['not_land'])}) — не земля участка, "
                 "в его границы они не входят.")
    text += (" Поэтому участок на схеме показан квадратом той же площади, что в расчёте. "
             "Чтобы увидеть корпуса на карте, укажите кадастровые номера всех участков "
             "территории.")
    return text


def _inside_ring(point: list[float], ring: list[list[float]]) -> bool:
    """Точка внутри кольца (чётность пересечений луча)."""
    x, y = float(point[0]), float(point[1])
    inside = False
    for i in range(len(ring)):
        x1, y1 = float(ring[i][0]), float(ring[i][1])
        x2, y2 = float(ring[i - 1][0]), float(ring[i - 1][1])
        if (y1 > y) != (y2 > y) and x < (x2 - x1) * (y - y1) / (y2 - y1) + x1:
            inside = not inside
    return inside


def _holes(rings: list[list[list[float]]]) -> list[bool]:
    """Какие кольца — дыры. Файл карты реестра отдаёт кольца полигона плоским
    списком (`krt_map_data._rings`): внешнее и внутреннее там не размечены.
    Кольцо внутри нечётного числа других колец — дыра."""
    return [sum(1 for j, other in enumerate(rings)
                if j != i and _inside_ring(ring[0], other)) % 2 == 1
            for i, ring in enumerate(rings)]


# Территория КРТ меньше этого — не территория, а случайные числа, принятые за
# координаты (владелец 28.10.2026: «каталог» 0,8 м² с картинки схемы). Разбор
# такой каталог не принимает (`auction_search.krt_manual_contour.MIN_CATALOG_SQM`
# равен этому числу), а уже сохранённый не читает движок и снимает страница.
KRT_TERRITORY_MIN_SQM = 100.0


def krt_site_effective(x: dict[str, Any]) -> dict[str, Any] | None:
    """Чем меряется территория КРТ при стоящей галочке «Проект в КРТ»:
    загруженный человеком контур (`_krt_site.manual`) сильнее найденного
    автоматически, но автоматический остаётся рядом. Галочки нет — None."""
    site = x.get("_krt_site") if isinstance(x, dict) else None
    if not isinstance(site, dict) or site.get("on") is not True:
        return None
    manual = site.get("manual")
    # Загруженный «контур» меньше территории — случайные числа с картинки, а не
    # границы: его не читают ни схема, ни отчёты (страница снимает его сама).
    if isinstance(manual, dict) and float(manual.get("area_sqm") or 0) >= KRT_TERRITORY_MIN_SQM:
        return {"name": site.get("name"), "slug": site.get("slug"), **manual}
    return site


def krt_site_rings_merc(x: dict[str, Any]) -> list[list[list[float]]]:
    """Кольца контура территории КРТ (внешние и дыры — плоским списком, как
    их отдаёт источник), если галочка «Проект в КРТ» стоит и контур есть;
    иначе пусто — схема берёт ЕГРН."""
    site = krt_site_effective(x)
    if not site or (site.get("approximate") and site.get("origin") != "photo_outline"):
        return []
    return [ring for ring in (site.get("rings_merc") or [])
            if isinstance(ring, list) and len(ring) >= 3]


def krt_photo_outline_note(x: dict[str, Any]) -> str:
    """Пометка «границы приблизительные» у контура, снятого с картинки решения
    (`origin: photo_outline`, `auction_search/krt_photo_outline`). Один текст на
    все поверхности: пояснение схемы, карта участка (`layout.approximate_note`)
    и PDF (пояснения схемы). Не с картинки — пусто."""
    krt = krt_site_effective(x) or {}
    if krt.get("origin") != "photo_outline":
        return ""
    area = float(krt.get("area_sqm") or 0.0)
    if krt.get("rings_merc"):
        where = (f"На карту она поставлена {krt.get('anchored_by') or 'по участкам проекта'}, "
                 f"погрешность привязки — около {_fmt_ru(float(krt.get('anchor_error_m') or 0))} м.")
    else:
        where = "На карту её поставить не вышло."
    return ("Границы территории КРТ приблизительные: они сняты с картинки решения, а не с "
            "таблицы координат. Форма — по обводке границы на картинке, размер подогнан под "
            f"площадь из текста решения ({_fmt_ru(area)} м²). {where} Точные границы даст "
            "каталог координат из приложения к решению.")


def krt_contour_area_sqm(rings_merc: list[list[list[float]]]) -> float:
    """Площадь контура КРТ на местности, м²: меркатор с поправкой cos широты
    (`_merc_rings_m`), дыры полигона вычитаются. Единственный счётчик этой
    площади: её читают поле «Площадь участка» и схема посадки."""
    rings = [ring for ring in (rings_merc or []) if isinstance(ring, list) and len(ring) >= 3]
    metres, _frame = _merc_rings_m(rings)
    if len(metres) != len(rings):
        # Выродившееся кольцо выпало при переводе: дыры по нему не размечаются.
        holes = [False] * len(metres)
    else:
        holes = _holes(rings)
    return sum(-abs(_ring_area(r)) if hole else abs(_ring_area(r))
               for r, hole in zip(metres, holes))


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
                   footprint_origin: str, one_building: bool = False) -> list[dict[str, Any]]:
    """Корпуса очередей: пятно ∝ наземной ГНС, этажность ≤ предела, длина ≤ 100 м.

    `one_building` — проект без жилья (`without_housing`): очередь — одно
    здание, а не жилые секции глубиной 18 м и длиной до 100 м (владелец
    25.10.2026: «одно здание и три корпуса — где тут?»). Его пятно ищет на
    участке форму от офисной глубины 24 м до квадрата (`_shapes_for`)."""
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
        if not one_building:
            longest = LAYOUT_CORPUS_DEPTH_M * LAYOUT_CORPUS_MAX_LENGTH_M
            parts = max(parts, int(_math.ceil(spot / longest - 1e-9)))
        for j in range(parts):
            out.append({
                **({"depth_m": LAYOUT_OTHER_DEPTH_M, "free_shape": True} if one_building else {}),
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


def _object_corpora(objects: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Школа, детский сад, офисы — корпусами схемы; длиннее 100 м — по длине.
    Глубина корпуса школы и сада — 18 м, офиса и прочих — 24 м."""
    out: list[dict[str, Any]] = []
    for obj in objects or []:
        spot = float(obj.get("footprint_sqm") or 0.0)
        if spot <= 0:
            continue
        depth = LAYOUT_OTHER_DEPTH_M if obj.get("kind") == "other" else LAYOUT_CORPUS_DEPTH_M
        longest = depth * LAYOUT_CORPUS_MAX_LENGTH_M
        parts = max(1, int(_math.ceil(spot / longest - 1e-9)))
        storeys = float(obj.get("storeys") or 1.0)
        shown = int(_math.floor(storeys + 0.5))
        for j in range(parts):
            corpus = f", корпус {j + 1}" if parts > 1 else ""
            out.append({
                "phase": 0, "object": obj.get("key"), "object_kind": obj.get("kind"),
                "corpus": j + 1, "corpora_in_phase": parts, "depth_m": depth,
                "area_sqm": spot / parts, "area_origin": "estimate",
                "storeys": storeys, "storeys_shown": shown, "storeys_origin": "default",
                "above_gns_sqm": float(obj.get("gns_sqm") or 0.0) / parts,
                "color": LAYOUT_OBJECT_COLORS.get(str(obj.get("kind")), LAYOUT_OBJECT_COLORS["other"]),
                "label": f"{obj.get('label')}{corpus}, {_storeys_word(shown)}",
            })
    return out


def _grid_place(corpora: list[dict[str, Any]], rings: list[list[list[float]]]) -> bool:
    """Корпуса — сеткой равномерно по всему участку без отступов (владелец 23.10.2026:
    «на больших участках распределять равномерно, а не в одну кучу»).

    Шаг сетки не меньше корпуса плюс разрыв (вдоль — 12 м, поперёк — 15 м или
    0,8 высоты, ориентир инсоляции) и растягивается, пока на участке есть место
    для всех корпусов; лишние места пропускаются равномерно. Корпуса идут
    группами (отдельные здания, затем очереди) по строкам. Не помещаются и при
    наименьшем шаге — False: на схеме остаются те корпуса, что встали по
    кварталам, остальные названы (`_unplaced_note`).
    """
    if not corpora or not rings:
        return False
    depths = [float(c.get("depth_m") or LAYOUT_CORPUS_DEPTH_M) for c in corpora]
    depth = max(depths)
    lengths = [c["area_sqm"] / d for c, d in zip(corpora, depths)]
    longest = max(lengths)
    tallest = max(c["storeys_shown"] for c in corpora) * LAYOUT_STOREY_HEIGHT_M
    px0 = longest + LAYOUT_GAP_IN_ROW_M
    py0 = depth + max(LAYOUT_GAP_BETWEEN_ROWS_M, 0.8 * tallest)
    points = [p for ring in rings for p in ring]
    min_x, max_x = min(p[0] for p in points), max(p[0] for p in points)
    min_y, max_y = min(p[1] for p in points), max(p[1] for p in points)

    def spots(scale: float) -> list[tuple[float, float]]:
        px, py = px0 * scale, py0 * scale
        cols, rows = int((max_x - min_x) // px), int((max_y - min_y) // py)
        if cols < 1 or rows < 1:
            return []
        ox = min_x + (max_x - min_x - cols * px) / 2.0 + px / 2.0
        oy = min_y + (max_y - min_y - rows * py) / 2.0 + py / 2.0
        found = []
        for j in range(rows):
            for i in range(cols):
                cx, cy = ox + i * px, oy + j * py
                hx, hy = longest / 2.0, depth / 2.0
                if all(_inside(corner, rings) for corner in
                       ((cx - hx, cy - hy), (cx + hx, cy - hy), (cx + hx, cy + hy),
                        (cx - hx, cy + hy), (cx, cy))):
                    found.append((cx, cy))
        return found

    count = len(corpora)
    if len(spots(1.0)) < count:
        return False
    low, high = 1.0, max(max_x - min_x, max_y - min_y) / min(px0, py0)
    for _ in range(30):
        mid = (low + high) / 2.0
        if len(spots(mid)) >= count:
            low = mid
        else:
            high = mid
    chosen = spots(low)
    if len(chosen) > count:
        step = (len(chosen) - 1) / (count - 1) if count > 1 else 0.0
        chosen = [chosen[int(round(k * step))] for k in range(count)] if count > 1 \
            else [chosen[len(chosen) // 2]]
    for c, length, d, (cx, cy) in zip(corpora, lengths, depths, chosen):
        c["rect_m"] = [round(cx - length / 2.0, 2), round(cy - d / 2.0, 2),
                       round(cx + length / 2.0, 2), round(cy + d / 2.0, 2)]
    return True


def _layout_corpora(x: dict[str, Any], massing: dict[str, Any], phases: list[dict[str, Any]],
                    footprint: float, limit: float) -> list[dict[str, Any]]:
    """Корпуса схемы: отдельные здания и очереди — с подписями и ключами."""
    objects = massing.get("objects") or []
    corpora = _object_corpora(objects) + _phase_corpora(
        phases, footprint, limit, str(massing.get("footprint_origin") or "estimate"),
        without_housing(x))
    for c in corpora:
        if c["phase"] == 0:
            continue
        name = (f"Очередь {c['phase']}" if len(phases) > 1 else
                "Жилой дом" if objects else "Здание")
        corpus = f", корпус {c['corpus']}" if c["corpora_in_phase"] > 1 else ""
        c["label"] = f"{name}{corpus}, {_storeys_word(c['storeys_shown'])}"
        c["id"] = f"p{c['phase']}-{c['corpus']}"
    for c in corpora:
        c.setdefault("id", f"o-{c.get('object')}-{c['corpus']}")
    return corpora


def _engine_places_all(corpora: list[dict[str, Any]], site: list[list[list[float]]]) -> bool:
    """Встают ли все корпуса расстановкой движка: по кварталам, иначе сеткой."""
    axis = massing_strip_axis(site)
    if _engine_layout_cached(corpora, site, massing_blocks(site, axis), axis):
        return True
    return _grid_place([dict(c) for c in corpora], site)


_FIT_CACHE: dict[str, float] = {}


def site_massing_fit_sqm(x: dict[str, Any], massing: dict[str, Any],
                         phases: list[dict[str, Any]]) -> float:
    """Наибольшее пятно, которое встаёт на участок (с отступами и разрывами)
    корпусами схемы, → м²; 0 — пятно расчёта встаёт как есть или подбирать
    нечего (пятно задано руками, участка нет, корпусов больше, чем схема рисует).

    Решение владельца (25.10.2026, AskUserQuestion): пятно, которое на участке
    не встаёт, расчёт сжимает до того, что встаёт, и поднимает этажность — до
    предела участка; не встаёт и на пределе — расчёт говорит, сколько не
    хватает (`site_massing`, `_massing_fit_sqm`). Схема и ТЭП читают одно пятно.
    Подбор — той же расстановкой движка, что рисует схему (`_engine_places_all`)."""
    footprint = float(massing.get("footprint_sqm") or 0.0)
    if footprint <= 0 or massing.get("footprint_origin") == "manual":
        return 0.0
    site = _layout_site(x, massing)
    if not site:
        return 0.0
    rings = site[0]
    setback = float(massing.get("setback_m") or 0.0)
    inner = [r for r in (inset_ring(ring, setback) for ring in rings) if len(r) >= 3]
    area = inner or rings
    key = hashlib.sha256(json.dumps(
        [[[round(p[0], 2), round(p[1], 2)] for p in r] for r in area]
        + [round(footprint, 1), without_housing(x),
           [[o.get("key"), round(float(o.get("footprint_sqm") or 0.0), 1), o.get("kind"),
             o.get("storeys")] for o in massing.get("objects") or []],
           [round(float(p.get("above_gns_sqm") or 0.0), 1) for p in phases]],
        separators=(",", ":"), default=str).encode("utf-8")).hexdigest()
    if key in _FIT_CACHE:
        return _FIT_CACHE[key]

    def fits(spot: float) -> bool:
        # Предел этажности здесь не режет: ищется само место на участке.
        corpora = _layout_corpora(x, massing, phases, spot, 1e9)
        if not corpora or len(corpora) > LAYOUT_MAX_DRAWN_CORPORA:
            return True
        return _engine_places_all(corpora, area)

    if fits(footprint):
        found = 0.0
    else:
        low, high = 0.0, footprint
        for _ in range(14):
            mid = (low + high) / 2.0
            if fits(mid):
                low = mid
            else:
                high = mid
        # Ноль — «встаёт как есть»; на участке совсем ничего не встаёт — 1 м².
        found = max(1.0, _math.floor(low))
    if len(_FIT_CACHE) > 256:
        _FIT_CACHE.clear()
    _FIT_CACHE[key] = found
    return found


def site_massing_fitted(x: dict[str, Any], tep: dict[str, Any],
                        phases: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """Пятно, этажность и уровни проекта, где пятно встаёт на участок схемы.

    Один источник для расчёта, книги и схемы: `site_massing`, а если его пятно
    на участке не встаёт — он же с наибольшим пятном, которое встаёт
    (`site_massing_fit_sqm`). Очередь берёт расчёт проекта как есть."""
    massing = site_massing(x, tep)
    if x.get("_site_massing_project"):
        return massing
    phases = phases or [{"phase": 1, "above_gns_sqm": massing["residential_gns_sqm"]}]
    fit = site_massing_fit_sqm(x, massing, phases)
    if fit <= 0:
        return massing
    # Прямоугольником не встаёт. Отдельное нежилое здание может встать формой
    # участка: её подбирает Платон (владелец 25.10.2026), движок проверяет.
    # Готовый проверенный план — пятно расчёта остаётся; план готовится — пока
    # пятно по прямоугольнику, страница пересчитает, когда план придёт.
    shape = _shape_plan(x, massing, phases)
    if shape.get("status") == "ready" and shape.get("fits"):
        return massing
    massing = site_massing({**x, "_massing_fit_sqm": fit,
                            "_massing_fit_pending": shape.get("status") == "pending"}, tep)
    if shape.get("status") == "pending":
        massing["shape_plan"] = {"key": shape.get("key"), "status": "pending"}
    return massing


def _shape_plan(x: dict[str, Any], massing: dict[str, Any],
                phases: list[dict[str, Any]]) -> dict[str, Any]:
    """План Платона для корпусов с пятном расчёта (не сжатым) → {status, key, fits}.

    Только у проекта без жилья (одно здание любой формы) и только по контуру
    ЕГРН. Ключ — тот же, что спросит схема для этих корпусов (`_place_corpora`)."""
    if not without_housing(x):
        return {}
    site = _layout_site(x, massing)
    if not site or site[2] != "contour":
        return {}
    rings = site[0]
    setback = float(massing.get("setback_m") or 0.0)
    inner = [r for r in (inset_ring(ring, setback) for ring in rings) if len(r) >= 3]
    area = inner or rings
    given_limit = float(massing.get("max_storeys_allowed") or 0.0)
    limit = given_limit if given_limit > 0 else float(LAYOUT_STOREYS_LIMIT_DEFAULT)
    corpora = _layout_corpora(x, massing, phases, float(massing.get("footprint_sqm") or 0.0), limit)
    if not corpora or len(corpora) > LAYOUT_MAX_DRAWN_CORPORA:
        return {}
    axis = massing_strip_axis(area)
    blocks = massing_blocks(area, axis)
    _engine_layout_cached(corpora, area, blocks, axis)
    plan = site_massing_plan_lookup(x, corpora, area, setback, blocks, "contour")
    if plan.get("status") == "ready":
        plan["fits"] = (massing_place_plan(corpora, blocks, plan.get("placements"))
                        or massing_check(corpora, area)) is None
    return plan


def _krt_area_mismatch_note(contour_sqm: float, site_sqm: float) -> str:
    return (f"Корпуса на карте участка не показаны: площадь контура территории КРТ "
            f"({_fmt_ru(contour_sqm)} м²) заметно отличается от площади участка в "
            f"расчёте ({_fmt_ru(site_sqm)} м²). Поэтому участок на схеме показан "
            "квадратом той же площади, что в расчёте.")


def _layout_site(x: dict[str, Any], massing: dict[str, Any]
                 ) -> tuple[list[list[list[float]]], dict[str, float], str, list[str], str,
                            list[float] | None] | None:
    """Участок схемы в метрах → (кольца, рамка, происхождение формы, пояснения,
    причина, по которой корпусов нет на карте участка, направление на север в
    координатах схемы или None, если стороны света неизвестны);
    участка нет — None. Схема повёрнута так, что самая длинная сторона участка
    идёт вдоль оси x; полоса — слева направо с лёгким подъёмом."""
    site_sqm = float(massing.get("site_sqm") or 0.0)
    notes: list[str] = []
    krt_rings = krt_site_rings_merc(x)
    krt = krt_site_effective(x) or {}
    map_note = ""
    krt_holes = any(_holes(krt_rings))
    photo = krt.get("origin") == "photo_outline"
    no_map = False
    if photo and not krt_rings:
        # Форма с картинки есть, а на карту не встала: схема — по форме, в
        # метрах на местности, корпусов на карте нет, причина названа.
        rings = [_clean_ring([[float(p[0]), float(p[1])] for p in ring])
                 for ring in krt.get("shape_m") or [] if isinstance(ring, list) and len(ring) >= 3]
        rings = [ring for ring in rings if len(ring) >= 3]
        frame, parts, no_map = {}, {}, True
        contour_sqm = sum(abs(_ring_area(r)) for r in rings)
        if rings:
            map_note = ("Корпуса на карте участка не показаны: форму территории КРТ с картинки "
                        "решения не удалось поставить на карту — "
                        f"{krt.get('map_problem') or 'причина не названа'}. Схема построена по "
                        "форме с картинки.")
    elif krt_rings or krt.get("approximate"):
        # Галочка «Проект в КРТ»: территория — контур КРТ, а не участки ЕГРН.
        # Раскладка дыр не обходит: в неё идут внешние кольца, а площадь
        # меряет тот же счётчик, что поле «Площадь участка» (дыры вычтены).
        outer = [ring for ring, hole in zip(krt_rings, _holes(krt_rings)) if not hole]
        rings, frame = _merc_rings_m(outer)
        parts: dict[str, Any] = {}
        contour_sqm = krt_contour_area_sqm(krt_rings)
    else:
        rings, frame, parts = _site_rings_m(x)
        contour_sqm = sum(abs(_ring_area(r)) for r in rings)
    if photo:
        # Пометка «приблизительно» — `krt_photo_outline_note`, её ставит
        # `site_massing_layout`; причина, когда формы нет на карте, — выше.
        if rings and site_sqm > 0 and abs(contour_sqm - site_sqm) > 0.25 * site_sqm:
            map_note = _krt_area_mismatch_note(contour_sqm, site_sqm)
            rings, frame = [], {}
    elif krt.get("approximate"):
        # Площадь есть, контура нет (фото схемы без координат, форму снять не
        # вышло): рисовать по участкам ЕГРН значит рисовать не то.
        why = str(krt.get("shape_problem") or "").strip()
        map_note = ("Форма участка на схеме приблизительная: площадь территории КРТ взята "
                    "из текста решения, а таблицы координат, по которой границы ложатся на "
                    "карту, нет"
                    + (f", и форму с картинки снять не вышло ({why})" if why else "")
                    + ". Участок показан квадратом той же площади.")
    elif krt_rings:
        title = krt.get("name") or krt.get("slug")
        notes.append(f"Участок на схеме — контур территории КРТ{f' «{title}»' if title else ''} "
                     f"({krt.get('source') or 'источник не назван'}), а не участки из госреестра: "
                     "в проекте стоит галочка «Проект в КРТ».")
        if krt_holes:
            # Корпуса по внешнему контуру могли бы встать в дыру — на землю,
            # исключённую из территории. Раскладка дыр не обходит, поэтому
            # участок — квадратом, а причина названа.
            map_note = ("Корпуса на карте участка не показаны: внутри территории КРТ есть "
                        "исключённые из неё участки, а схема пока не умеет их обходить и могла "
                        "бы поставить корпуса на чужую землю. Поэтому участок на схеме показан "
                        f"квадратом площади территории без исключённых участков — "
                        f"{_fmt_ru(contour_sqm)} м².")
            rings, frame = [], {}
        elif site_sqm > 0 and abs(contour_sqm - site_sqm) > 0.25 * site_sqm:
            map_note = _krt_area_mismatch_note(contour_sqm, site_sqm)
            rings, frame = [], {}
    elif rings and site_sqm > 0 and abs(contour_sqm - site_sqm) > 0.25 * site_sqm:
        # Контур другой площади — не вся территория проекта (часть участков
        # или чужой участок): рисовать по нему значит рисовать не то.
        map_note = _site_map_note(parts, site_sqm, contour_sqm)
        rings, frame = [], {}
    north: list[float] | None = None
    if rings:
        shape_origin = "contour"
        axis = massing_strip_axis(rings)
        if axis and axis["strip"]:
            # Полоса: её ось на картинке идёт слева направо с лёгким подъёмом
            # (в изометрии экранная горизонталь — направление (1, −1)).
            frame["angle"] = axis["angle"] + _math.radians(LAYOUT_STRIP_SCREEN_TURN_DEG)
        else:
            frame["angle"] = _main_direction(rings)
        rings = _rotate(rings, -frame["angle"])
        # Север (ось y карты) после поворота схемы. У формы с картинки, не
        # вставшей на карту, стороны света неизвестны.
        if not no_map:
            north = [_math.sin(frame["angle"]), _math.cos(frame["angle"])]
        if no_map:
            # Метры формы не на карте: перевода в меркатор у корпусов нет.
            frame = {}
    elif site_sqm > 0:
        shape_origin = "square"
        half = _math.sqrt(site_sqm) / 2.0
        rings = [[[-half, -half], [half, -half], [half, half], [-half, half]]]
        if not map_note and x.get("_land_contour_pending"):
            # Контур ещё в пути: страница пересчитает схему, когда он придёт.
            notes.append("Контур участка из госреестра ещё загружается, поэтому пока участок "
                         "показан квадратом той же площади. Когда контур придёт, схема "
                         "перерисуется сама.")
        elif not map_note:
            map_note = _site_map_note(parts, site_sqm, 0.0)
    else:
        return None
    # Причина, по которой корпусов нет на карте, — и пояснение схемы, и фраза
    # на месте кнопки карты (`layout.map_note`): одна строка на обе поверхности.
    if map_note:
        notes.append(map_note)
    elif shape_origin == "contour" and parts.get("overlap"):
        notes.append(_site_overlap_note(parts))
    return rings, frame, shape_origin, notes, map_note, north


def site_massing_layout(x: dict[str, Any], massing: dict[str, Any],
                        phases: list[dict[str, Any]]) -> dict[str, Any]:
    """Корпуса на участке → {site, buildings, …}; координаты — метры схемы.

    `phases` — [{"phase": 1, "name": "…", "above_gns_sqm": …}]; проект без
    очередей — одна запись. Схема повёрнута так, что самая длинная сторона
    участка идёт вдоль оси x.
    """
    footprint = float(massing.get("footprint_sqm") or 0.0)
    setback = float(massing.get("setback_m") or 0.0)
    given_limit = float(massing.get("max_storeys_allowed") or 0.0)
    limit = given_limit if given_limit > 0 else float(LAYOUT_STOREYS_LIMIT_DEFAULT)
    site = _layout_site(x, massing)
    if not site:
        return {"buildings": [], "site_rings": [], "notes": [], "storeys_limit": limit}
    rings, frame, shape_origin, notes, map_note, north = site
    approximate_note = krt_photo_outline_note(x)
    if approximate_note:
        notes.insert(0, approximate_note)

    inner = [r for r in (inset_ring(ring, setback) for ring in rings) if len(r) >= 3]
    objects = massing.get("objects") or []
    corpora = _layout_corpora(x, massing, phases, footprint, limit)
    plan: dict[str, Any] = {}
    if corpora and len(corpora) <= LAYOUT_MAX_DRAWN_CORPORA:
        plan = _place_corpora(x, corpora, rings, inner, setback, shape_origin,
                              massing.get("shape_plan"), north)
    for c in corpora:
        ring = c.get("ring_m")
        if not ring:
            continue
        c["rect_m"] = [round(min(p[0] for p in ring), 2), round(min(p[1] for p in ring), 2),
                       round(max(p[0] for p in ring), 2), round(max(p[1] for p in ring), 2)]
        c["rect_origin"] = "schema"
        if frame:
            c["ring_merc"] = _ring_to_merc(ring, frame)
    # Разбор участка и посадки жилья (`engine/site_massing_variants.py`): секции
    # домов, пожарные проезды, разрывы, вид сверху и фразы для посетителя.
    variants = plan.pop("_variants", None) if plan else None
    blocks = plan.pop("_blocks", None) if plan else None
    analysis_lines: list[str] = []
    plan_view: dict[str, Any] = {}
    land_balance: dict[str, Any] = {}
    denser: dict[str, Any] | None = None
    if variants and blocks is not None:
        for c in corpora:
            c["sections"] = massing_sections(c)
            c.pop("spines", None)
        lanes = massing_fire_lanes(corpora, rings)
        gaps = massing_min_gaps(corpora)
        analysis_lines = massing_analysis_lines(
            plan.pop("_analysis", {}), variants, plan.get("variant") or "rows", corpora, lanes,
            gaps, north, plan.get("chooser") or "engine")
        plan_view = massing_plan_view({"site_rings": rings, "underground_rings": inner,
                                       "buildings": corpora}, blocks, lanes, north)
        # Чем занята земля и, если свободной много, — вариант ниже и плотнее
        # (владелец 31.10.2026: «почему столько пустого пространства»).
        land_balance = massing_land_balance(massing)
        free_line = massing_free_land_line(massing, land_balance)
        if free_line:
            analysis_lines.insert(max(0, len(analysis_lines) - 1), free_line)
        offer = massing_denser_offer(x, massing, phases, inner or rings, north, land_balance,
                                     limit)
        if offer:
            alt_corpora = offer.pop("_corpora")
            alt_parts = offer.pop("_parts")
            offer["plan_view"] = massing_plan_view(
                {"site_rings": rings, "underground_rings": inner, "buildings": alt_corpora},
                alt_parts, [], north)
            offer["text"] = massing_denser_text(offer, float(massing.get("typical_storeys") or 0))
            denser = offer
    for c in corpora:
        c.pop("spines", None)
    unplaced = _unplaced_note(corpora, len(phases)) if plan else ""
    if unplaced:
        notes.append(unplaced)
    if any(c["storeys_origin"] == "limit" for c in corpora):
        spot = sum(c["area_sqm"] for c in corpora)
        notes.append(f"Этажность выше предела ({_fmt_ru(limit)} этажей"
                     f"{'' if given_limit > 0 else ', предел участка не задан, взят порог'}), "
                     f"поэтому очереди разделены на корпуса не выше предела. Пятно корпусов — "
                     f"{_fmt_ru(spot)} м², это больше пятна застройки в расчёте ({_fmt_ru(footprint)} м²).")
    if plan.get("note"):
        notes.append(plan["note"])
    # Уровней больше потолка (задано руками) — на схеме одна плита и причина,
    # а не колонка из сотен подписей.
    level_rows = massing.get("underground_level_rows") or []
    levels_total = int(massing.get("underground_levels") or 0)
    if len(level_rows) > UNDERGROUND_LEVELS_MAX:
        notes.append(
            f"Подземных уровней задано вручную {levels_total}, а схема рисует не больше "
            f"{UNDERGROUND_LEVELS_MAX}. Поэтому на схеме одна плита — верхний уровень. Проверьте "
            "число в поле «Подземных уровней»: так глубоко под землю обычно не строят.")
        level_rows = level_rows[:1]
    under_plan = massing_underground_plan(
        inner or rings, massing_strip_axis(inner or rings), corpora,
        level_rows,
        float(massing.get("underground_use_factor") or 0.0),
        {str(o.get("key")): float(o.get("plot_sqm") or 0.0) for o in objects})
    for row in under_plan:
        if row["contour_sqm"] < 0.99 * row["need_sqm"]:
            notes.append(
                f"Подземный уровень −{abs(row['level'])} ({_fmt_ru(row['area_sqm'])} м²) вместе со "
                f"стенами, колоннами и шахтами занимает {_fmt_ru(row['need_sqm'])} м², а на плане "
                f"участка под корпусами и двором для него есть {_fmt_ru(row['contour_sqm'])} м²: "
                "под участками школы и детского сада паркинг не строят. Плита на схеме показывает "
                "это место; возможно, понадобится ещё один уровень.")
    return {
        "site_rings": [[[round(p[0], 2), round(p[1], 2)] for p in r] for r in rings],
        "site_shape_origin": shape_origin,
        # Почему корпусов нет на карте участка (схема — квадратом): страница
        # ставит эту фразу на место кнопки карты.
        "map_note": map_note,
        # Границы сняты с картинки решения: пометка на схеме, на карте участка
        # и в PDF — этот текст (`krt_photo_outline_note`).
        "approximate_note": approximate_note,
        "underground_rings": [[[round(p[0], 2), round(p[1], 2)] for p in r] for r in inner],
        "setback_m": setback,
        "storeys_limit": limit,
        "storeys_limit_origin": "manual" if given_limit > 0 else "default",
        "unplaced_count": sum(1 for c in corpora if not c.get("ring_m")) if plan else 0,
        "underground_levels": levels_total,
        # Подземная часть под участком не помещается: плит нет, причина — в
        # предупреждении движка (`underground_levels_reason`).
        "underground_levels_unfit": bool(massing.get("underground_levels_unfit")),
        # Уровни под землёй — те же, по которым взята ставка: площадь уровня и
        # полезная площадь одного уровня в контуре (не больше потолка схемы).
        "underground_level_rows": [{"level": int(r.get("level") or 0),
                                    "area_sqm": float(r.get("area_sqm") or 0.0)}
                                   for r in level_rows],
        "underground_level_capacity_sqm": float(massing.get("underground_contour_sqm") or 0.0)
        * float(massing.get("underground_use_factor") or 0.0),
        # Где под участком лежит каждый уровень: контур под корпусами и двором.
        "underground_plan": under_plan,
        "buildings": corpora,
        "notes": notes,
        "plan": plan,
        # Север в координатах схемы (None — стороны света неизвестны), разбор
        # участка и посадки фразами и вид сверху — для страницы и PDF.
        "north": north,
        "analysis": analysis_lines,
        "plan_view": plan_view,
        # Баланс земли участка и предложение «ниже и плотнее» (None — не нужно).
        "land_balance": land_balance,
        "denser": denser,
    }


def _place_corpora(x: dict[str, Any], corpora: list[dict[str, Any]],
                   rings: list[list[list[float]]], inner: list[list[list[float]]],
                   setback: float, shape_origin: str,
                   shape_plan: dict[str, Any] | None = None,
                   north: list[float] | None = None) -> dict[str, Any]:
    """Корпуса на участке в настоящем размере → состояние плана.

    Порядок: план Платона, если он есть, свежий и прошёл проверку движка
    (`engine/site_massing_plan.py`); иначе расстановка движка по кварталам
    (`massing_place_engine`); не встали так — сетка по участку (`_grid_place`);
    не встали и сеткой — на схеме те корпуса, что встают по кварталам, у
    остальных места нет, и схема их называет. Корпус не уменьшается никогда:
    уменьшенная схема показывала бы застройку реже, чем она есть (владелец
    23.10.2026). У каждого корпуса — `placement_origin`: `plato` или `engine`.

    `shape_plan` — Платон подбирает форму здания для пятна расчёта, пока оно
    сжато до прямоугольника (`site_massing_fitted`): второго плана для сжатого
    пятна не просим, страница ждёт этот."""
    site = inner or rings
    axis = massing_strip_axis(site)
    blocks = massing_blocks(site, axis)
    # Расстановка движка нужна всегда: она запасная и она же — образец,
    # который получает Платон.
    engine_ok = _engine_layout_cached(corpora, site, blocks, axis)
    if any(c["phase"] > 0 for c in corpora) and not any(c.get("free_shape") for c in corpora):
        return _place_housing(x, corpora, site, setback, shape_origin, blocks, axis, north)
    plan = dict(shape_plan) if shape_plan else \
        site_massing_plan_lookup(x, corpora, site, setback, blocks, shape_origin)
    if plan.get("status") == "ready":
        reason = massing_place_plan(corpora, blocks, plan.get("placements")) \
            or massing_check(corpora, site)
        if reason is None:
            for c in corpora:
                c["placement_origin"] = "plato"
            return site_massing_plan_note(plan)
        plan = {**plan, "status": "rejected", "reason": reason}
        engine_ok = _engine_layout_cached(corpora, site, blocks, axis)
    grid = False
    if not engine_ok:
        trial = [dict(c) for c in corpora]
        if _grid_place(trial, site):
            grid = True
            for c, t in zip(corpora, trial):
                for key in ("ring_m", "block", "front", "shape", "place"):
                    c.pop(key, None)
                r = t["rect_m"]
                c["ring_m"] = [[r[0], r[1]], [r[2], r[1]], [r[2], r[3]], [r[0], r[3]]]
    for c in corpora:
        c["placement_origin"] = "engine"
    return site_massing_plan_note(plan, grid)


def _place_housing(x: dict[str, Any], corpora: list[dict[str, Any]],
                   site: list[list[list[float]]], setback: float, shape_origin: str,
                   blocks: list[dict[str, Any]], axis: dict[str, float] | None,
                   north: list[float] | None) -> dict[str, Any]:
    """Жилой проект: варианты посадки домами из секций (`massing_variants`),
    выбор движка или Платона (решение владельца 31.10.2026: «Платон выбирает
    из вариантов»). Не встало ни одним вариантом — сетка, как прежде."""
    # Части участка для вариантов: крылья по внутренним углам контура; прежние
    # кварталы остаются у варианта «рядами вдоль участка».
    parts = massing_parts(site, axis)
    # Прежняя расстановка уже сделана (`_engine_layout_cached`) — она и есть
    # вариант «рядами вдоль участка».
    variants = massing_variants_cached(corpora, site, blocks, axis, north, parts,
                                       [copy.deepcopy(c) for c in corpora])
    analysis = massing_site_analysis(parts, north)
    chosen = massing_variant_pick(variants)
    chooser = "engine"
    plan = site_massing_plan_lookup(x, corpora, site, setback, blocks, shape_origin,
                                    variants=variants, analysis=analysis)
    if plan.get("status") == "ready":
        reason = massing_variant_check(variants, plan.get("variant"))
        if reason is None:
            chosen, chooser = str(plan["variant"]), "plato"
        else:
            plan = {**plan, "status": "rejected", "reason": reason}
    massing_apply_variant(corpora, variants[chosen])
    grid = False
    if variants[chosen]["metrics"]["unplaced"] > 0:
        trial = [dict(c) for c in corpora]
        if _grid_place(trial, site):
            grid = True
            for c, t in zip(corpora, trial):
                for key in ("ring_m", "block", "front", "shape", "place", "spines"):
                    c.pop(key, None)
                r = t["rect_m"]
                c["ring_m"] = [[r[0], r[1]], [r[2], r[1]], [r[2], r[3]], [r[0], r[3]]]
    for c in corpora:
        c["placement_origin"] = "plato" if chooser == "plato" else "engine"
    out = site_massing_plan_note(plan, grid)
    out.update(variant=chosen, chooser=chooser,
               variants={k: v["metrics"] for k, v in variants.items()},
               _variants=variants, _blocks=parts, _analysis=analysis)
    return out


def _unplaced_note(corpora: list[dict[str, Any]], phases_count: int) -> str:
    """Что не встало на участок в настоящем размере — числом, простыми словами."""
    missing = [c for c in corpora if not c.get("ring_m")]
    if not missing:
        return ""
    parts = []
    for key in dict.fromkeys((c["phase"], c.get("object")) for c in missing):
        own = [c for c in missing if (c["phase"], c.get("object")) == key]
        name = own[0]["label"].split(",")[0] if own[0].get("label") else "Корпус"
        parts.append(f"{name} — {_corpora_word(len(own))}, пятно "
                     f"{_fmt_ru(sum(c['area_sqm'] for c in own))} м²")
    return (f"На участке встают {len(corpora) - len(missing)} из {len(corpora)} корпусов. "
            f"Для остальных места нет ({'; '.join(parts)}): с отступом от границ участка и "
            f"разрывом {_fmt_ru(LAYOUT_GAP_IN_ROW_M)} м между корпусами они не помещаются, хотя "
            "их площадь в расчёте есть. Уменьшите наземную площадь, поднимите предельную "
            "этажность или задайте пятно застройки в полях этой карточки.")


_ENGINE_LAYOUT_CACHE: dict[str, list[Any]] = {}


def _engine_layout_cached(corpora: list[dict[str, Any]], site: list[list[list[float]]],
                          blocks: list[dict[str, Any]], axis: dict[str, float] | None) -> bool:
    """Расстановка движка с памятью по входам: расчёт зовёт схему на каждом
    пересчёте (подбор цены — десятки раз), а входы схемы при этом те же."""
    key = hashlib.sha256(json.dumps(
        [[[round(p[0], 2), round(p[1], 2)] for p in r] for r in site]
        + [[c["id"], round(c["area_sqm"], 2), c["storeys_shown"]] for c in corpora],
        separators=(",", ":")).encode("utf-8")).hexdigest()
    hit = _ENGINE_LAYOUT_CACHE.get(key)
    if hit is None:
        ok = massing_place_engine(corpora, blocks, axis)
        hit = [ok, [{k: c.get(k) for k in ("ring_m", "block", "front", "shape", "place")}
                    for c in corpora]]
        if len(_ENGINE_LAYOUT_CACHE) > 64:
            _ENGINE_LAYOUT_CACHE.clear()
        _ENGINE_LAYOUT_CACHE[key] = hit
    ok, rows = hit
    # Не встали все — у вставших место то же, у остальных места нет.
    for c, row in zip(corpora, rows):
        for k, v in row.items():
            if v is None:
                c.pop(k, None)
            else:
                c[k] = copy.deepcopy(v)
    return ok


def _ring_to_merc(ring: list[list[float]], frame: dict[str, float]) -> list[list[float]]:
    """Многоугольник схемы → кольцо в метрах веб-меркатора (карта участка)."""
    c, s = _math.cos(frame["angle"]), _math.sin(frame["angle"])
    return [[round(frame["cx"] + (px * c - py * s) / frame["k"], 2),
             round(frame["cy"] + (px * s + py * c) / frame["k"], 2)] for px, py in ring]


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
    plan_rings = {int(r["level"]): [ring for ring in r.get("rings") or [] if len(ring) >= 3]
                  for r in layout.get("underground_plan") or []}
    h = LAYOUT_STOREY_HEIGHT_M
    # Подземные уровни — плиты под участком, раздвинутые по высоте, чтобы
    # каждая была видна: шаг — не меньше двух этажей и около пятой части
    # размера подземного контура. Плита неполного уровня сжата к центру по
    # своей площади. Земля над ними полупрозрачная.
    inner_pts = [p for ring in under for p in ring]
    extent = max((max(p[i] for p in inner_pts) - min(p[i] for p in inner_pts) for i in (0, 1)),
                 default=0.0)
    step = max(2 * h, min(0.2 * extent, 8 * h))
    for row in sorted(rows, key=lambda r: r["level"]):
        depth = abs(int(row["level"]))
        z_top = -depth * step + h
        z_bottom = z_top - h
        share = min(1.0, row["area_sqm"] / capacity) if capacity > 0 else 1.0
        k = _math.sqrt(share)
        fill = _shade("#a89f8f", 1.0 + 0.12 * (depth - 1))
        # Плита — там, где уровень лежит под участком (`massing_underground_plan`):
        # под корпусами и двором, без участков школы и сада. Плана нет —
        # контур, сжатый к центру по доле вместимости.
        placed = plan_rings.get(int(row["level"]))
        if placed:
            level_rings = placed
        else:
            level_rings = []
            for ring in under:
                cx = sum(p[0] for p in ring) / len(ring)
                cy = sum(p[1] for p in ring) / len(ring)
                level_rings.append([[cx + (p[0] - cx) * k, cy + (p[1] - cy) * k] for p in ring])
        for level_ring in level_rings:
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
    def centre(b: dict[str, Any]) -> tuple[float, float]:
        ring = b["ring_m"]
        return sum(p[0] for p in ring) / len(ring), sum(p[1] for p in ring) / len(ring)

    # Корпус без места на плане (не встал в настоящем размере) не рисуется,
    # но остаётся в списке: он есть в расчёте.
    order = sorted((i for i, b in enumerate(buildings) if b.get("ring_m")),
                   key=lambda i: -sum(centre(buildings[i])))
    # Номер — группы (отдельное здание или очередь), а не корпуса: двадцать
    # кружков с разными номерами на телефоне не читаются.
    groups: dict[Any, int] = {}
    for b in buildings:
        key = ("object", b.get("object")) if b["phase"] == 0 else ("phase", b["phase"])
        b["number"] = groups.setdefault(key, len(groups) + 1)
    roofs: dict[int, tuple[float, float]] = {}
    for i in order:
        b = buildings[i]
        ring = b["ring_m"]
        h = b["storeys_shown"] * LAYOUT_STOREY_HEIGHT_M
        color = b.get("color") or LAYOUT_PHASE_COLORS[(b["phase"] - 1) % len(LAYOUT_PHASE_COLORS)]
        sign = 1.0 if _ring_area(ring) > 0 else -1.0
        # Видны крыша и стены, обращённые к зрителю (наружная нормаль — к
        # малым x + y); корпус может стоять под любым углом к оси схемы.
        for k in range(len(ring)):
            (ax_, ay_), (bx_, by_) = ring[k], ring[(k + 1) % len(ring)]
            nx, ny = (by_ - ay_) * sign, -(bx_ - ax_) * sign
            if nx + ny >= 0:
                continue
            length = _math.hypot(nx, ny) or 1.0
            # Свет слева: стена, глядящая к малым x, темнее.
            factor = 0.62 + 0.16 * (1 + (ny - nx) / length / _math.sqrt(2)) / 2
            shapes.append({"kind": "wall",
                           "points": [project(ax_, ay_, 0), project(bx_, by_, 0),
                                      project(bx_, by_, h), project(ax_, ay_, h)],
                           "fill": _shade(color, round(factor, 3)), "stroke": _shade(color, 0.45),
                           "width": 0.6, "building": b["number"], "phase": b["phase"]})
        shapes.append({"kind": "roof", "points": [project(px, py, h) for px, py in ring],
                       "fill": _shade(color, 1.25), "stroke": _shade(color, 0.45), "width": 0.6,
                       "building": b["number"], "phase": b["phase"]})
        roofs[i] = tuple(project(*centre(b), h))
    xs = [p[0] for s in shapes for p in s["points"]]
    ys = [p[1] for s in shapes for p in s["points"]]
    size = max(max(xs) - min(xs), max(ys) - min(ys), 1.0)
    font = round(0.045 * size, 2)
    radius = round(0.032 * size, 2)
    labels = _group_labels(buildings, roofs, radius)
    for label in labels:
        xs.extend([label["x"] - radius, label["x"] + radius])
        ys.extend([label["y"] - radius, label["y"] + radius])
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
    legend = []
    for number in sorted({b["number"] for b in buildings}):
        own = [b for b in buildings if b["number"] == number]
        first = own[0]
        area = sum(b["area_sqm"] for b in own)
        if len(own) == 1:
            text = first["label"]
        else:
            name = first["label"].split(",")[0]
            text = f"{name}: {_corpora_word(len(own))} по {_storeys_word(first['storeys_shown'])}"
        missing = sum(1 for b in own if not b.get("ring_m"))
        tail = ""
        if missing:
            tail = ("; на участке не поместился" if missing == 1 and len(own) == 1
                    else f"; на участке не поместился 1 из {len(own)}"
                    if missing == 1 else
                    f"; на участке не поместились {missing} из {len(own)}")
        legend.append({"number": number, "phase": first["phase"], "text": text, "area_sqm": area,
                       "corpora": len(own), "unplaced": missing,
                       "line": f"{number} — {text}, пятно {_fmt_ru(area)} м²{tail}",
                       "color": first.get("color") or
                       LAYOUT_PHASE_COLORS[(first["phase"] - 1) % len(LAYOUT_PHASE_COLORS)]})
    levels = int(layout.get("underground_levels") or 0)
    placed_under = bool(layout.get("underground_plan"))
    social = any(b.get("object") in SOCIAL_PLOT_KEYS for b in buildings)
    caption = ("Зелёное — участок без отступов, светлая полоса вдоль границ до пунктира — отступ. "
               + (f"Под участком — {_levels_word(levels)} с площадью каждого; по высоте они "
                  "раздвинуты, чтобы был виден каждый"
                  + (", а по плану каждая плита лежит там, где этот уровень: под корпусами "
                     "и двором" + ("; под участками школы и детского сада паркинга нет"
                                   if social else "") if placed_under
                     else "") + ". " if texts else
                  "Подземная часть под участком не помещается, поэтому подземных уровней на "
                  "схеме нет: причина названа выше. " if layout.get("underground_levels_unfit")
                  else "")
               + "Корпуса окрашены по очередям, номер на крыше — номер строки в списке под схемой.")
    plan = layout.get("plan") or {}
    who = ("Вариант посадки выбрал помощник Платон, корпуса расставлены"
           if plan.get("origin") == "plato" and plan.get("mode") == "variants" else
           "Расстановку корпусов предложил помощник Платон" if plan.get("origin") == "plato"
           else "Корпуса расставлены")
    footer = (f"{who} для наглядности: это не генплан, а схема того, как корпуса могут встать "
              f"на участке. Высота на схеме — по {_fmt_ru(LAYOUT_STOREY_HEIGHT_M)} м на этаж.")
    return {"caption": caption, "footer": footer,
            "viewbox": [round(min(xs) - pad, 2), round(min(ys) - pad, 2),
                        round(max(xs) - min(xs) + 2 * pad, 2), round(max(ys) - min(ys) + 2 * pad, 2)],
            "shapes": shapes, "labels": labels, "legend": legend, "texts": texts,
            "font_size": font, "label_radius": radius}


def _group_labels(buildings: list[dict[str, Any]], roofs: dict[int, tuple[float, float]],
                  radius: float) -> list[dict[str, Any]]:
    """Один номер на группу — на крыше корпуса ближе всех к середине группы;
    кружки не налезают друг на друга: занятое место — следующий корпус группы,
    а если свободного нет, кружок поднимается над крышами."""
    placed: list[dict[str, Any]] = []
    for number in sorted({b["number"] for b in buildings}):
        own = [i for i, b in enumerate(buildings) if b["number"] == number and i in roofs]
        if not own:
            continue
        mx = sum(roofs[i][0] for i in own) / len(own)
        my = sum(roofs[i][1] for i in own) / len(own)
        spots = sorted((roofs[i] for i in own), key=lambda p: _math.hypot(p[0] - mx, p[1] - my))

        def free(p):
            return all(_math.hypot(p[0] - q["x"], p[1] - q["y"]) >= 2.2 * radius for q in placed)

        spot = next((p for p in spots if free(p)), None)
        if spot is None:
            spot = spots[0]
            while not free(spot):
                spot = (spot[0], spot[1] - radius)
        placed.append({"x": round(spot[0], 2), "y": round(spot[1], 2), "text": str(number),
                       "building": number})
    return placed


def _corpora_word(count: int) -> str:
    tail = count % 100
    if count % 10 == 1 and tail != 11:
        return f"{count} корпус"
    if 2 <= count % 10 <= 4 and not 12 <= tail <= 14:
        return f"{count} корпуса"
    return f"{count} корпусов"


def site_massing_phase_lines(layout: dict[str, Any], phases_count: int) -> list[str]:
    """Корпуса по очередям одной строкой на очередь — когда схему не рисуем."""
    lines: list[str] = []
    buildings = layout.get("buildings") or []
    has_objects = any(b["phase"] == 0 for b in buildings)
    for key in dict.fromkeys(b.get("object") for b in buildings if b["phase"] == 0):
        own = [b for b in buildings if b["phase"] == 0 and b.get("object") == key]
        label = own[0]["label"].split(",")[0]
        lines.append(f"{label}: {_corpora_word(len(own))} по {_storeys_word(own[0]['storeys_shown'])}, "
                     f"пятно {_fmt_ru(sum(b['area_sqm'] for b in own))} м²")
    for phase in sorted({b["phase"] for b in buildings if b["phase"] > 0}):
        own = [b for b in buildings if b["phase"] == phase]
        storeys = max(b["storeys_shown"] for b in own)
        name = (f"Очередь {phase}" if phases_count > 1 else
                "Жилой дом" if has_objects else "Здание")
        lines.append(f"{name}: {_corpora_word(len(own))} по {_storeys_word(storeys)}, пятно "
                     f"{_fmt_ru(sum(b['area_sqm'] for b in own))} м²")
    return lines


def site_massing_scheme(x: dict[str, Any], massing: dict[str, Any],
                        phases: list[dict[str, Any]]) -> dict[str, Any]:
    """Раскладка и картинка одним ответом: `tep.site_massing.scheme`.

    Корпусов больше `LAYOUT_MAX_DRAWN_CORPORA` — схему не рисуем (владелец
    23.10.2026: «в таких масштабных случаях лучше и не рисовать»): ряды из
    десятков корпусов нечитаемы и ничего не говорят. Тогда вместо картинки —
    причина и строка на очередь, а корпусов на карте участка нет.
    """
    layout = site_massing_layout(x, massing, phases)
    buildings = layout.get("buildings") or []
    if not buildings:
        return {"layout": layout, "axonometry": {}}
    if len(buildings) > LAYOUT_MAX_DRAWN_CORPORA:
        for b in buildings:
            b.pop("ring_merc", None)
        layout["skipped"] = (f"Схему не рисуем: корпусов получилось {len(buildings)}, и их "
                             "расстановка рядами на таком участке ничего не покажет. Корпуса по "
                             "очередям:")
        layout["phase_lines"] = site_massing_phase_lines(layout, len(phases))
        return {"layout": layout, "axonometry": {}}
    return {"layout": layout, "axonometry": site_massing_axonometry(layout)}
