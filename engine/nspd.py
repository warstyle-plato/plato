"""НСПД и зоны: поиск участка, ЗОУИТ и скрининг, карты, геокодеры.

Федеральный поиск участка: запросы к НСПД (ППК «Роскадастр») и разбор
объектов, геометрия, карта и подложка, слои и проба экрана, скрининг
участка по зонам (ЗОУИТ, покрытие, вердикт), геокодеры (Яндекс, DaData,
Nominatim), land_lookup, контекст лота, маршруты ТЭП от базы и по участку,
статус поставщиков.

Не самостоятельный модуль. `main_legacy.py` выполняет этот файл в своём
пространстве имён на том месте, где этот код стоял раньше
(`_engine_part("nspd")`), поэтому здесь видны все имена движка,
а подмены `core.<имя>` из `main.py` и тестов действуют и на этот код.
Отдельно не импортировать: второй импорт поднял бы вторую копию движка.
"""
# ruff: noqa

# ---------------------------------------------------------------------------
# Федеральный поиск участка: НСПД (ППК «Роскадастр») + геокодеры
#
# /cadastral/analyze работает только по Москве (калькулятор ГлавАПУ).
# Блок ниже даёт сведения ЕГРН по любому кадастровому номеру России,
# по адресу и по координатам, не затрагивая расчётное ядро модели.
# ---------------------------------------------------------------------------


def _env_str(name: str, default: str = "") -> str:
    return str(os.environ.get(name) or default).strip()


def _env_float(name: str, default: float) -> float:
    try:
        return float(_env_str(name) or default)
    except ValueError:
        return default


_NSPD_BASE_URL = (_env_str("NSPD_BASE_URL", "https://nspd.gov.ru")).rstrip("/")
_NSPD_TIMEOUT_SECONDS = _env_float("NSPD_TIMEOUT_SECONDS", 25.0)
_NSPD_LAND_THEMATIC_ID = 1
# Слой «Земельные участки из ЕГРН» на карте НСПД. Точечный поиск идёт через
# WMS GetFeatureInfo этого слоя — тем же запросом, что клик по карте на сайте.
_NSPD_LANDS_LAYER_ID = 36048

# Слои НСПД для градостроительного скрининга. Номера сверены пробой сети
# геопортала НСПД (17.08.2026): при включённых «ЗОУИТ объектов культурного
# наследия» и «Территориальные зоны» карта дёргала `/api/aeggis/v4/37577/wms`
# и `/api/aeggis/v4/875838/wms` — но это **GetMap** (тайлы), путь v4. А
# **GetFeatureInfo** (опрос атрибутов, чем и живёт скрининг) работает на **v3**:
# v4 на GetFeatureInfo отвечает 502, v3 — 200 (пусто там, где объекта нет).
# Первый пустой ответ v3 по 37577–81 был не «номер не тот», а «на московской
# автостоянке ЗОУИТ нет»; клик по участку в МО показал реальные ЗОУИТ. Имена
# ниже — по совпадению включённого слоя и запроса; финально подтвердит проба
# GetFeatureInfo по содержимому properties. 36048 (ЗУ ЕГРН) — тоже v3.
_NSPD_SCREEN_LAYER_CANDIDATES: dict[str, int] = {
    # Снято с карты НСПД включением слоя и чтением его wms-запроса (17.08.2026):
    # «Красные линии» → /api/aeggis/v4/879243/wms. GetMap идёт на v4, опрос
    # атрибутов — на v3, как у остальных.
    "red_lines_879243": 879243,
    "oopt_875845": 875845,
    "zouit_okn_37577": 37577,
    "zouit_37578": 37578,
    "zouit_37579": 37579,
    "zouit_37580": 37580,
    "zouit_37581": 37581,
    "terr_zones_875838": 875838,
}
_NOMINATIM_BASE_URL = (_env_str("NOMINATIM_BASE_URL", "https://nominatim.openstreetmap.org")).rstrip("/")
_LAND_LOOKUP_USER_AGENT = USER_AGENT
_LAND_LOOKUP_MAX_RESULTS = int(_env_float("LAND_LOOKUP_MAX_RESULTS", 30))
# Номера опрашиваются параллельно: 30 последовательных запросов к НСПД — это
# минуты ожидания. Больше трёх потоков портал начинает придерживать.
_LAND_LOOKUP_WORKERS = max(1, int(_env_float("LAND_LOOKUP_WORKERS", 3)))
_LAND_LOOKUP_CACHE_TTL_SECONDS = _env_float("LAND_LOOKUP_CACHE_TTL", 900.0)
_LAND_LOOKUP_CACHE_LIMIT = 256
_LAND_LOOKUP_RESPONSE_LIMIT = 4 * 1024 * 1024

_land_lookup_cache: dict[str, tuple[float, Any]] = {}
_land_lookup_cache_lock = threading.Lock()
_nominatim_lock = threading.Lock()
_nominatim_last_call = 0.0

# Разделитель «запятая/точка с запятой в пробелах ИЛИ одни пробелы» записан
# двумя непересекающимися ветками, а не `\s*[,;\s]\s*`: там пробелы делились
# между тремя кусками сколькими угодно способами, и длинная строка пробелов
# без второго числа стоила квадрата шагов. Принимаемые строки те же.
_COORDINATE_QUERY_RE = re.compile(
    r"^\s*(-?\d{1,3}(?:[.,]\d+)?)(?:\s*[,;]\s*|\s+)(-?\d{1,3}(?:[.,]\d+)?)\s*$"
)

# Кадастровые округа. Совпадают с кодами субъектов РФ; используются как
# офлайн-подсказка, если НСПД недоступен. Неизвестный код — пустая строка,
# регион в этом случае берётся из ответа ЕГРН.
_CADASTRAL_DISTRICTS = {
    "01": "Республика Адыгея", "02": "Республика Башкортостан", "03": "Республика Бурятия",
    "04": "Республика Алтай", "05": "Республика Дагестан", "06": "Республика Ингушетия",
    "07": "Кабардино-Балкарская Республика", "08": "Республика Калмыкия",
    "09": "Карачаево-Черкесская Республика", "10": "Республика Карелия", "11": "Республика Коми",
    "12": "Республика Марий Эл", "13": "Республика Мордовия", "14": "Республика Саха (Якутия)",
    "15": "Республика Северная Осетия — Алания", "16": "Республика Татарстан",
    "17": "Республика Тыва", "18": "Удмуртская Республика", "19": "Республика Хакасия",
    "20": "Чеченская Республика", "21": "Чувашская Республика", "22": "Алтайский край",
    "23": "Краснодарский край", "24": "Красноярский край", "25": "Приморский край",
    "26": "Ставропольский край", "27": "Хабаровский край", "28": "Амурская область",
    "29": "Архангельская область", "30": "Астраханская область", "31": "Белгородская область",
    "32": "Брянская область", "33": "Владимирская область", "34": "Волгоградская область",
    "35": "Вологодская область", "36": "Воронежская область", "37": "Ивановская область",
    "38": "Иркутская область", "39": "Калининградская область", "40": "Калужская область",
    "41": "Камчатский край", "42": "Кемеровская область", "43": "Кировская область",
    "44": "Костромская область", "45": "Курганская область", "46": "Курская область",
    "47": "Ленинградская область", "48": "Липецкая область", "49": "Магаданская область",
    "50": "Московская область", "51": "Мурманская область", "52": "Нижегородская область",
    "53": "Новгородская область", "54": "Новосибирская область", "55": "Омская область",
    "56": "Оренбургская область", "57": "Орловская область", "58": "Пензенская область",
    "59": "Пермский край", "60": "Псковская область", "61": "Ростовская область",
    "62": "Рязанская область", "63": "Самарская область", "64": "Саратовская область",
    "65": "Сахалинская область", "66": "Свердловская область", "67": "Смоленская область",
    "68": "Тамбовская область", "69": "Тверская область", "70": "Томская область",
    "71": "Тульская область", "72": "Тюменская область", "73": "Ульяновская область",
    "74": "Челябинская область", "75": "Забайкальский край", "76": "Ярославская область",
    "77": "Москва", "78": "Санкт-Петербург", "79": "Еврейская автономная область",
    "83": "Ненецкий автономный округ", "86": "Ханты-Мансийский автономный округ — Югра",
    "87": "Чукотский автономный округ", "89": "Ямало-Ненецкий автономный округ",
    "91": "Республика Крым", "92": "Севастополь",
}

# Названия полей ЕГРН в ответе НСПД менялись между версиями геопортала,
# поэтому каждое значение ищется по списку синонимов.
_NSPD_FIELD_ALIASES: dict[str, tuple[str, ...]] = {
    "cadastral_number": ("cad_num", "cadNum", "cadastral_number", "cadastralNumber"),
    "address": ("readable_address", "address", "adress", "readableAddress", "location"),
    "area_sqm": (
        "land_record_area", "specified_area", "declared_area", "area",
        "build_record_area", "area_value",
        # Портал периодически меняет написание ключей, не предупреждая.
        "area_value_m2", "area_sqm", "square", "params_area", "areaValue",
    ),
    "category": ("land_record_category_type", "category_type", "land_category", "category"),
    "permitted_use": (
        "permitted_use_established_by_document", "permitted_use_by_doc",
        "permitted_use", "utilization_by_doc", "utilization", "permittedUse",
    ),
    "cadastral_value": ("cost_value", "cadastral_cost", "cadastral_value", "cost"),
    "cadastral_value_date": (
        "cost_determination_date", "cost_application_date",
        "cost_registration_date", "cost_approvement_date",
    ),
    "status": ("status", "land_record_status", "record_status", "object_status"),
    "registration_date": (
        "land_record_reg_date", "build_record_registration_date",
        "registration_date", "reg_date",
    ),
    "quarter": ("quarter_cad_number", "cadastral_quarter", "quarter"),
    # Участок под зданием: в карточке ОКС портал иногда несёт номер своего
    # земельного участка. Когда несёт — это самый короткий путь от адреса к
    # участку, короче любого пространственного запроса.
    "land_parcel": (
        "land_cad_number", "land_cadastral_number", "cad_num_land",
        "parent_cad_number", "parent_cadastral_number", "landCadNum",
    ),
    "ownership": ("ownership_type", "right_type", "form_of_ownership"),
    "region": ("subject_rf", "subject", "region"),
    "purpose": ("purpose", "assignation_name", "build_record_type_value", "object_type"),
    "floors": ("floors", "floor_count"),
    "year_built": ("year_built", "year_of_construction", "year_used"),
}

_LAND_KIND_LABELS = {
    "land": "Земельный участок",
    "building": "Объект капитального строительства",
    "premise": "Помещение",
    "other": "Объект ЕГРН",
}

# Что такое земельный участок — определяем положительно, по названию
# категории. Перечислять всё, чем объект не является, бесполезно: ЕГРН
# заводит десятки видов помещений и сооружений, и любой невнесённый в список
# просочится в выдачу. Поиск по адресу оставляет только участки.
_NSPD_LAND_WORDS = ("участ", "земел", "зу ")
_NSPD_PREMISE_WORDS = (
    "помещ", "квартир", "машино-мест", "машиномест", "комнат", "доля в праве",
)
_NSPD_BUILDING_WORDS = (
    "здан", "сооруж", "строен", "окс", "объект недвиж", "незаверш", "комплекс",
)


def _land_cache_get(key: str) -> Any:
    now = time.time()
    with _land_lookup_cache_lock:
        item = _land_lookup_cache.get(key)
        if not item:
            return None
        stored_at, value = item
        if now - stored_at > _LAND_LOOKUP_CACHE_TTL_SECONDS:
            _land_lookup_cache.pop(key, None)
            return None
        return value


def _land_cache_put(key: str, value: Any) -> None:
    with _land_lookup_cache_lock:
        if len(_land_lookup_cache) >= _LAND_LOOKUP_CACHE_LIMIT:
            oldest = sorted(_land_lookup_cache.items(), key=lambda item: item[1][0])
            for stale_key, _ in oldest[: len(oldest) // 2 or 1]:
                _land_lookup_cache.pop(stale_key, None)
        _land_lookup_cache[key] = (time.time(), value)


# НСПД отвечает не всякому клиенту: без браузерных заголовков портал молча
# отдаёт пустой результат, а его сертификат выпущен национальным УЦ, которого
# нет в стандартном хранилище доверия большинства хостов.
_NSPD_BROWSER_HEADERS = {
    "Accept": "*/*",
    "Accept-Language": "ru-RU,ru;q=0.9,en;q=0.7",
    "Cache-Control": "no-cache",
    "Pragma": "no-cache",
    "Referer": "https://nspd.gov.ru/map?thematic=PKK",
    "Origin": "https://nspd.gov.ru",
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/144.0.0.0 Safari/537.36"
    ),
}

# Пускать ли запрос повторно без проверки сертификата, если цепочка не
# проверилась. Выключается через NSPD_TLS_FALLBACK=0, если на хосте установлен
# корневой сертификат Минцифры и проверка обязана проходить честно.
_NSPD_TLS_FALLBACK = _env_str("NSPD_TLS_FALLBACK", "1") not in {"0", "false", "нет", "off"}
_nspd_tls_insecure = False


def _land_fetch_json(
    url: str,
    *,
    service: str,
    data: bytes | None = None,
    headers: dict[str, str] | None = None,
    timeout: float | None = None,
) -> Any:
    """GET/POST внешнего JSON с единообразными русскими ошибками."""
    request_headers = {
        "Accept": "application/json",
        "Accept-Language": "ru-RU,ru;q=0.9",
        "User-Agent": _LAND_LOOKUP_USER_AGENT,
    }
    if url.startswith(_NSPD_BASE_URL):
        request_headers.update(_NSPD_BROWSER_HEADERS)
    if data is not None:
        request_headers["Content-Type"] = "application/json; charset=utf-8"
    request_headers.update(headers or {})
    external_request = urllib.request.Request(
        url,
        data=data,
        method="POST" if data is not None else "GET",
        headers=request_headers,
    )
    global _nspd_tls_insecure
    context = None
    if url.startswith(_NSPD_BASE_URL) and _nspd_tls_insecure:
        context = ssl._create_unverified_context()
    try:
        try:
            with urllib.request.urlopen(
                external_request, timeout=timeout or _NSPD_TIMEOUT_SECONDS, context=context
            ) as response:
                raw = response.read(_LAND_LOOKUP_RESPONSE_LIMIT + 1)
        except urllib.error.URLError as exc:
            # Сертификат НСПД не проверился: повторяем без проверки, но только
            # для этого хоста и с явной отметкой в /land/providers.
            if not (
                _NSPD_TLS_FALLBACK
                and url.startswith(_NSPD_BASE_URL)
                and not _nspd_tls_insecure
                and isinstance(getattr(exc, "reason", None), ssl.SSLError)
            ):
                raise
            _nspd_tls_insecure = True
            with urllib.request.urlopen(
                external_request,
                timeout=timeout or _NSPD_TIMEOUT_SECONDS,
                context=ssl._create_unverified_context(),
            ) as response:
                raw = response.read(_LAND_LOOKUP_RESPONSE_LIMIT + 1)
    except urllib.error.HTTPError as exc:
        # 404 молча превращался в «ничего не найдено», и это была наша половина
        # тёмного НСПД: 06.09.2026 портал отвечал 404 по ВСЕМ своим адресам —
        # поиск, слои карты, GetFeatureInfo, — а продукт на всех поверхностях
        # писал «участок не найден», и выглядело это как плохо введённый адрес
        # (экран владельца). Ни один из вызовов здесь не адресует объект по
        # идентификатору: это поиск, WMS и геокодеры, и у них 404 означает, что
        # адреса нет у СЕРВИСА, а не что по запросу нет результатов. Отсутствие
        # ответа внешнего источника нельзя показывать как его отрицательный
        # ответ — правило старое, а эта ветка его обходила.
        # 5xx — сбой самого сервиса, а не нашего запроса. Его сообщение вида
        # «registers: post-objdoc-by-external_key (код=1024)» (НСПД 11–12.10.2026,
        # тот же запрос на том же выпуске через несколько часов нашёл 20 из 20)
        # без кода HTTP читалось как наша ошибка; называем сторону и код.
        if exc.code == 404:
            detail = (f"{service}: адрес сервиса ответил 404 — сервис не отдал данные. "
                      "Это не ответ «объекта нет». О своём состоянии портал "
                      "сообщает у себя на странице.")
        elif exc.code >= 500:
            detail = (f"{service}: внутренняя ошибка сервиса (HTTP {exc.code}) — сбой на "
                      "стороне портала, не в запросе; данные не получены, повторите "
                      f"позже. Ответ сервиса: «{_external_error_message(exc)}».")
        else:
            detail = f"{service}: HTTP {exc.code} — {_external_error_message(exc)}"
        raise HTTPException(
            status_code=400 if 400 <= exc.code < 500 else 502,
            detail=detail,
        ) from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise HTTPException(
            status_code=502,
            detail=f"{service} временно недоступен. Повторите попытку позже.",
        ) from exc
    if len(raw) > _LAND_LOOKUP_RESPONSE_LIMIT:
        raise HTTPException(status_code=502, detail=f"{service} вернул слишком большой ответ.")
    if not raw.strip():
        return None
    try:
        return json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=502, detail=f"{service} вернул некорректный ответ.") from exc


def _land_float(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip().replace("\xa0", "").replace(" ", "")
    if not text:
        return None
    text = text.replace(",", ".")
    match = re.search(r"-?\d+(?:\.\d+)?", text)
    if not match:
        return None
    try:
        return float(match.group(0))
    except ValueError:
        return None


def _land_text(value: Any) -> str:
    if value is None or isinstance(value, bool):
        return ""
    text = str(value).strip()
    return "" if text.lower() in {"none", "null", "nan"} else text


def _cadastral_number_parts(number: str) -> dict[str, Any]:
    """Разбор кадастрового номера без обращения к внешним сервисам."""
    chunks = str(number or "").split(":")
    district = chunks[0] if chunks else ""
    quarter = ":".join(chunks[:3]) if len(chunks) >= 3 else ""
    return {
        "district_code": district,
        "region_hint": _CADASTRAL_DISTRICTS.get(district, ""),
        "quarter": quarter,
    }


def _mercator_to_wgs84(x: float, y: float) -> tuple[float, float]:
    """EPSG:3857 → широта/долгота. НСПД отдаёт геометрию в веб-меркаторе."""
    lng = x * 180.0 / 20037508.34
    lat = y * 180.0 / 20037508.34
    lat = 180.0 / math.pi * (2.0 * math.atan(math.exp(lat * math.pi / 180.0)) - math.pi / 2.0)
    return lat, lng


def _geometry_points(node: Any, out: list[tuple[float, float]]) -> None:
    if isinstance(node, (list, tuple)):
        if (
            len(node) >= 2
            and isinstance(node[0], (int, float))
            and isinstance(node[1], (int, float))
        ):
            out.append((float(node[0]), float(node[1])))
            return
        for child in node:
            _geometry_points(child, out)


def _geometry_bounds_wgs84(geometry: Any) -> tuple[float, float, float, float] | None:
    """Границы фигуры в градусах: запад, юг, восток, север.

    Геометрия НСПД приходит и в градусах, и в веб-меркаторе — различаем так
    же, как `_geometry_center`: координаты внутри ±180/±90 считаем градусами.
    """
    if not isinstance(geometry, dict):
        return None
    points: list[tuple[float, float]] = []
    _geometry_points(geometry.get("coordinates"), points)
    if not points:
        return None
    degrees = all(abs(x) <= 180.0 and abs(y) <= 90.0 for x, y in points)
    if not degrees:
        points = [tuple(reversed(_mercator_to_wgs84(x, y))) for x, y in points]
    west = min(p[0] for p in points)
    east = max(p[0] for p in points)
    south = min(p[1] for p in points)
    north = max(p[1] for p in points)
    if east <= west or north <= south:
        return None
    return west, south, east, north


def _wgs84_to_mercator(lat: float, lng: float) -> tuple[float, float]:
    """Широта и долгота → веб-меркатор. Обратное к `_mercator_to_wgs84`.

    Формула жила внутри `_geometry_center`, а нужна она и там, где точка
    приходит готовой парой координат — например, ссылкой на карту НСПД для
    территории КРТ. Второй такой пересчёт (тем более в браузере) разошёлся бы
    с этим молча, и ссылка вела бы рядом с участком.
    """
    merc_x = lng * 20037508.34 / 180.0
    merc_y = math.log(math.tan((90.0 + lat) * math.pi / 360.0)) / (math.pi / 180.0)
    return merc_x, merc_y * 20037508.34 / 180.0


def _geometry_center(geometry: Any) -> dict[str, Any] | None:
    if not isinstance(geometry, dict):
        return None
    points: list[tuple[float, float]] = []
    _geometry_points(geometry.get("coordinates"), points)
    if not points:
        return None
    x = (min(p[0] for p in points) + max(p[0] for p in points)) / 2.0
    y = (min(p[1] for p in points) + max(p[1] for p in points)) / 2.0
    if abs(x) <= 180.0 and abs(y) <= 90.0:
        # Уже WGS84 (GeoJSON порядок — долгота, широта).
        lat, lng = y, x
        merc_x, merc_y = _wgs84_to_mercator(lat, lng)
    else:
        lat, lng = _mercator_to_wgs84(x, y)
        merc_x, merc_y = x, y
    return {
        "lat": round(lat, 6),
        "lng": round(lng, 6),
        "merc_x": round(merc_x, 2),
        "merc_y": round(merc_y, 2),
    }


def _geometry_contours_merc(geometry: Any) -> list[list[list[float]]]:
    """Внешние кольца границ участка в метрах веб-меркатора — для миниатюры.

    НСПД отдаёт геометрию то в градусах (текстовый поиск, CRS=EPSG:4326), то
    в веб-меркаторе (WMS-точка); признак — величины координат, как в
    `_geometry_center`. Меркатор для SVG удобен как плоскость: на размере
    участка искажения формы нет. Внутренние кольца (дыры) миниатюре не нужны.
    """
    if not isinstance(geometry, dict):
        return []
    gtype = geometry.get("type")
    coords = geometry.get("coordinates")
    if gtype == "Polygon":
        polygons = [coords]
    elif gtype == "MultiPolygon":
        polygons = coords if isinstance(coords, list) else []
    else:
        return []
    rings: list[list[list[float]]] = []
    for polygon in polygons:
        if not (isinstance(polygon, list) and polygon and isinstance(polygon[0], list)):
            continue
        ring: list[list[float]] = []
        for point in polygon[0]:
            if not (isinstance(point, (list, tuple)) and len(point) >= 2):
                continue
            x, y = float(point[0]), float(point[1])
            if abs(x) <= 180.0 and abs(y) <= 90.0:
                merc_x = x * 20037508.34 / 180.0
                merc_y = math.log(math.tan((90.0 + y) * math.pi / 360.0)) / (math.pi / 180.0)
                merc_y = merc_y * 20037508.34 / 180.0
                ring.append([round(merc_x, 2), round(merc_y, 2)])
            else:
                ring.append([round(x, 2), round(y, 2)])
        if len(ring) >= 4:
            rings.append(ring)
    return rings


def _nspd_features(payload: Any) -> list[dict[str, Any]]:
    for container in (payload.get("data") if isinstance(payload, dict) else None, payload):
        if isinstance(container, dict):
            features = container.get("features")
            if isinstance(features, list):
                return [item for item in features if isinstance(item, dict)]
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    return []


def _nspd_options(feature: dict[str, Any]) -> dict[str, Any]:
    properties = feature.get("properties")
    properties = properties if isinstance(properties, dict) else {}
    merged: dict[str, Any] = {k: v for k, v in properties.items() if not isinstance(v, (dict, list))}
    options = properties.get("options")
    if isinstance(options, dict):
        merged.update(options)
    return merged


def _nspd_value(options: dict[str, Any], field: str) -> Any:
    for alias in _NSPD_FIELD_ALIASES.get(field, ()):
        if alias in options:
            value = options[alias]
            if value not in (None, "", []):
                return value
    return None


def _nspd_object_kind(feature: dict[str, Any], options: dict[str, Any]) -> str:
    properties = feature.get("properties")
    properties = properties if isinstance(properties, dict) else {}
    label = " ".join(
        _land_text(properties.get(key)) for key in ("categoryName", "category_name", "descr")
    ).strip().lower()
    if label:
        # Ярлык категории есть — доверяем ему и не додумываем по полям.
        if any(word in label for word in _NSPD_LAND_WORDS):
            return "land"
        # Помещение отличаем раньше здания: «помещение в здании» иначе уедет в ОКС.
        if any(word in label for word in _NSPD_PREMISE_WORDS):
            return "premise"
        if any(word in label for word in _NSPD_BUILDING_WORDS):
            return "building"
        # Категория названа, но нам незнакома. Записать её в участки нельзя:
        # объект попадёт в расчёт площади территории и исказит всё остальное.
        return "other"
    if "land_record_area" in options or _nspd_value(options, "category"):
        return "land"
    if "build_record_area" in options or _nspd_value(options, "year_built"):
        return "building"
    return "other"


def _nspd_card(feature: dict[str, Any]) -> tuple[str, str]:
    """(id объекта, номер слоя) для `selectedCard` — из ответа поиска НСПД.

    Ссылка «скопировать» самой НСПД открывает карточку объекта параметром
    `selectedCard=<id>,<слой>,<номер>` (владелец, 27.09.2026). Слой в ответе
    поиска — `properties.category`, id — `feature.id`. Чего нет или что не
    число — пусто: карточку не угадываем, ссылка остаётся по точке.
    """
    properties = feature.get("properties")
    properties = properties if isinstance(properties, dict) else {}
    ident, layer = str(feature.get("id") or "").strip(), str(properties.get("category") or "").strip()
    return (ident, layer) if ident.isdigit() and layer.isdigit() else ("", "")


def _nspd_map_url(center: dict[str, Any] | None, cadastral_number: str,
                  card: tuple[str, str] = ("", "")) -> str:
    if center and center.get("merc_x") is not None:
        ident, layer = card
        selected = ""
        if ident and layer and cadastral_number:
            selected = "&selectedCard=" + urllib.parse.quote(
                f"{ident},{layer},{cadastral_number}", safe="")
        # Порядок и набор параметров — как у ссылки «скопировать» самой НСПД
        # (`theme_id=1`, `is_copy_url=true`): номер из адреса карта не читает
        # (`?query=` открывала прежнее место, владелец 27.09.2026), точку — да.
        return (
            f"{_NSPD_BASE_URL}/map?thematic=PKK&theme_id=1&is_copy_url=true"
            f"&coordinate_x={center['merc_x']}&coordinate_y={center['merc_y']}&zoom=18"
            f"{selected}"
        )
    if cadastral_number:
        return f"{_NSPD_BASE_URL}/map?thematic=PKK&query={urllib.parse.quote(cadastral_number)}"
    return f"{_NSPD_BASE_URL}/map"


def _normalize_nspd_feature(feature: dict[str, Any], query_number: str = "") -> dict[str, Any]:
    options = _nspd_options(feature)
    properties = feature.get("properties")
    properties = properties if isinstance(properties, dict) else {}
    cadastral_number = _land_text(_nspd_value(options, "cadastral_number"))
    parts = _cadastral_number_parts(cadastral_number)
    area_sqm = _land_float(_nspd_value(options, "area_sqm"))
    cadastral_value = _land_float(_nspd_value(options, "cadastral_value"))
    kind = _nspd_object_kind(feature, options)
    center = _geometry_center(feature.get("geometry"))
    region = _land_text(_nspd_value(options, "region")) or parts["region_hint"]
    return {
        "found": True,
        "cadastral_number": cadastral_number,
        "kind": kind,
        "kind_label": _LAND_KIND_LABELS.get(kind, _LAND_KIND_LABELS["other"]),
        "address": _land_text(_nspd_value(options, "address")),
        "area_sqm": round(area_sqm, 2) if area_sqm is not None else None,
        "area_ha": round(area_sqm / 10000.0, 4) if area_sqm is not None else None,
        "category": _land_text(_nspd_value(options, "category")),
        "permitted_use": _land_text(_nspd_value(options, "permitted_use")),
        "cadastral_value_rub": round(cadastral_value, 2) if cadastral_value is not None else None,
        "cadastral_value_mln": round(cadastral_value / 1_000_000.0, 3) if cadastral_value else None,
        "cadastral_value_date": _land_text(_nspd_value(options, "cadastral_value_date")),
        "unit_value_rub_per_sqm": (
            round(cadastral_value / area_sqm, 2)
            if cadastral_value and area_sqm and area_sqm > 0
            else None
        ),
        "status": _land_text(_nspd_value(options, "status")),
        "registration_date": _land_text(_nspd_value(options, "registration_date")),
        "quarter": _land_text(_nspd_value(options, "quarter")) or parts["quarter"],
        "land_parcel": _land_text(_nspd_value(options, "land_parcel")),
        "ownership": _land_text(_nspd_value(options, "ownership")),
        "region": region,
        "purpose": _land_text(_nspd_value(options, "purpose")),
        "floors": _land_text(_nspd_value(options, "floors")),
        "year_built": _land_text(_nspd_value(options, "year_built")),
        "center": {"lat": center["lat"], "lng": center["lng"]} if center else None,
        # Границы для миниатюры на странице: контур рисуется своим SVG, без
        # внешних карт — работает и в телеграм-WebView, и при лежащей НСПД.
        "contour_merc": _geometry_contours_merc(feature.get("geometry")),
        # Номер для карточки — свой у объекта, иначе тот, по которому искали:
        # у помещений НСПД поле номера бывает пустым.
        "map_url": _nspd_map_url(center, cadastral_number or query_number, _nspd_card(feature)),
        "nspd_id": _nspd_card(feature)[0],
        "nspd_layer": _nspd_card(feature)[1],
        "category_name": _land_text(properties.get("categoryName")),
        "source": "НСПД / ЕГРН",
    }


def _nspd_search_features(query: str) -> list[dict[str, Any]]:
    cache_key = f"nspd:search:{query}"
    cached = _land_cache_get(cache_key)
    if cached is not None:
        return cached
    params = urllib.parse.urlencode({
        "query": query,
        "thematicSearchId": _NSPD_LAND_THEMATIC_ID,
        "CRS": "EPSG:4326",
    })
    payload = _land_fetch_json(
        f"{_NSPD_BASE_URL}/api/geoportal/v2/search/geoportal?{params}",
        service="Сервис НСПД",
    )
    features = _nspd_features(payload)
    # Пустой ответ не кэшируется: НСПД отвечает не на каждый запрос, и
    # прилипший в кэше промах 15 минут выдавал «участок не найден» на все
    # повторы — так из 22 участков Мытищ считались 20, а площадь территории
    # молча теряла восемь гектаров.
    if features:
        _land_cache_put(cache_key, features)
    return features


def _nspd_point_features(lat: float, lng: float) -> list[dict[str, Any]]:
    """Участки в точке: сначала поиск по координатам, затем WMS-запрос слоя ЗУ.

    Текстовый поиск «lat lng» и прежний GET /api/geoportal/v1/intersects на
    точках отвечают пустотой даже там, где участок точно есть. Рабочий путь —
    тот, которым сама карта НСПД отвечает на клик: WMS GetFeatureInfo слоя
    «Земельные участки из ЕГРН» по пикселю тайла (сверено с pynspd 1.1.13).
    """
    try:
        features = _nspd_search_features(f"{lat} {lng}")
    except HTTPException:
        features = []
    if features:
        return features
    # Тайл web-меркатора, в который попадает точка; zoom 24 — максимум точности.
    zoom = 24
    tiles = 1 << zoom
    tile_size = 512
    lat_rad = math.radians(lat)
    xtile = int((lng + 180.0) / 360.0 * tiles)
    ytile = int((1.0 - math.asinh(math.tan(lat_rad)) / math.pi) / 2.0 * tiles)
    west = xtile / tiles * 360.0 - 180.0
    east = (xtile + 1) / tiles * 360.0 - 180.0
    north = math.degrees(math.atan(math.sinh(math.pi * (1.0 - 2.0 * ytile / tiles))))
    south = math.degrees(math.atan(math.sinh(math.pi * (1.0 - 2.0 * (ytile + 1) / tiles))))
    i = int((lng - west) / (east - west) * tile_size)
    j = int((lat - south) / (north - south) * tile_size)
    params = urllib.parse.urlencode({
        "REQUEST": "GetFeatureInfo",
        "SERVICE": "WMS",
        "VERSION": "1.3.0",
        "INFO_FORMAT": "application/json",
        "FORMAT": "image/png",
        "STYLES": "",
        "TRANSPARENT": "true",
        "QUERY_LAYERS": _NSPD_LANDS_LAYER_ID,
        "LAYERS": _NSPD_LANDS_LAYER_ID,
        "WIDTH": tile_size,
        "HEIGHT": tile_size,
        "I": i,
        # Пиксели WMS отсчитываются от верхнего края, интерполяция — от южного.
        "J": tile_size - j,
        "CRS": "EPSG:4326",
        "BBOX": f"{west},{south},{east},{north}",
        # Без FEATURE_COUNT сервис отдаёт один объект даже на границе участков.
        "FEATURE_COUNT": "10",
    })
    try:
        payload = _land_fetch_json(
            f"{_NSPD_BASE_URL}/api/aeggis/v3/{_NSPD_LANDS_LAYER_ID}/wms?{params}",
            service="Сервис НСПД",
        )
    except HTTPException:
        return []
    return _nspd_features(payload)


# Подложка карты под контуром участка: WMS GetMap того же слоя ЗУ, которым
# работает точечный поиск. Кэш маленький и с TTL — карта не меняется от
# запроса к запросу, а НСПД не любит частых обращений.
_NSPD_MAP_CACHE: dict[str, tuple[float, bytes]] = {}
_NSPD_MAP_CACHE_TTL_SECONDS = 6 * 3600
_NSPD_MAP_CACHE_LIMIT = 64

# Обычная карта с улицами — под рыночную выборку, а не под карточку участка.
#
# Кадастровый слой НСПД верен на двухстах метрах участка: он рисует границы
# ЕГРН и ничего больше. На пяти километрах выборки соседей от него пользы нет —
# клубок границ без улиц, реки и названий, то есть шум без ориентира. Улицы,
# вода и подписи районов есть только у настоящей карты, поэтому подложка
# берётся тайлами OSM и склеивается **на сервере**: браузер получает одну
# картинку, ходить наружу ему не приходится, и в печать эта картинка уходит
# целиком. Адрес вынесен в переменную: свой тайловый сервер подставляется
# одной строкой, без правки кода.
_OSM_TILE_URL = _env_str("OSM_TILE_URL", "https://tile.openstreetmap.org/{z}/{x}/{y}.png")
_OSM_TILE_CACHE: dict[str, tuple[float, bytes]] = {}
_OSM_TILE_CACHE_TTL_SECONDS = 7 * 24 * 3600
_OSM_TILE_CACHE_LIMIT = 512
_BASEMAP_CACHE: dict[str, tuple[float, bytes]] = {}
_BASEMAP_CACHE_TTL_SECONDS = 24 * 3600
_BASEMAP_CACHE_LIMIT = 32
# Больше сорока тайлов на картинку — это уже не карта района, а выкачивание
# чужого сервиса: при перегрузе берётся масштаб крупнее, а не сотня запросов.
_BASEMAP_TILE_BUDGET = 40


@app.get("/land/map-probe", include_in_schema=False)
def land_map_probe(bbox: str = "") -> dict[str, Any]:
    """Диагностика формата WMS GetMap НСПД: кандидаты перебираются с ядра.

    Подложка отвечала 404, а проверить формат с телефона нельзя — WAF НСПД
    отдаёт Forbidden на прямые запросы без браузерной сессии карты. Ядро же
    НСПД пускает (точечный поиск живёт), поэтому кандидаты перебираются
    отсюда: версии пути v3/v4 и системы координат 3857/4326 в обоих порядках
    осей. Ответ говорит, какой формат отдал PNG, — по нему чинится
    /land/map-image. Только диагностика: ничего не кэширует и не меняет.
    """
    remote = _core_api_url("/land/map-probe")
    if remote:
        try:
            with urllib.request.urlopen(
                    urllib.request.Request(
                        remote + "?" + urllib.parse.urlencode({"bbox": bbox}),
                        headers={"Accept": "application/json"}),
                    timeout=90) as response:
                return json.loads(response.read().decode("utf-8"))
        except Exception as exc:
            raise HTTPException(status_code=502, detail=f"Ядро недоступно: {exc}")
    try:
        parts = [float(x) for x in str(bbox or "").split(",")]
    except ValueError:
        parts = []
    if len(parts) != 4:
        # Мишина 77:09:0004014:13 — участок, на котором 404 и был пойман.
        parts = [4181302.0, 7518174.0, 4181542.0, 7518414.0]
    min_x, min_y, max_x, max_y = parts
    south_lat, west_lng = _mercator_to_wgs84(min_x, min_y)
    north_lat, east_lng = _mercator_to_wgs84(max_x, max_y)

    def wms_url(api_version: str, crs: str, bbox_value: str) -> str:
        return (f"{_NSPD_BASE_URL}/api/aeggis/{api_version}/{_NSPD_LANDS_LAYER_ID}/wms?"
                + urllib.parse.urlencode({
                    "SERVICE": "WMS", "REQUEST": "GetMap", "VERSION": "1.3.0",
                    "FORMAT": "image/png", "STYLES": "", "TRANSPARENT": "true",
                    "LAYERS": _NSPD_LANDS_LAYER_ID, "WIDTH": 512, "HEIGHT": 512,
                    "CRS": crs, "BBOX": bbox_value,
                }))

    candidates = {
        "v3_3857_merc": wms_url("v3", "EPSG:3857", f"{min_x},{min_y},{max_x},{max_y}"),
        "v4_3857_merc": wms_url("v4", "EPSG:3857", f"{min_x},{min_y},{max_x},{max_y}"),
        # WMS 1.3.0 для EPSG:4326 требует порядок осей lat,lon; текущий
        # /land/map-image шлёт lon,lat — оба варианта в переборе.
        "v3_4326_latlon": wms_url("v3", "EPSG:4326",
                                  f"{south_lat},{west_lng},{north_lat},{east_lng}"),
        "v3_4326_lonlat": wms_url("v3", "EPSG:4326",
                                  f"{west_lng},{south_lat},{east_lng},{north_lat}"),
    }
    request_headers = {
        "Accept": "image/png,image/*;q=0.9,*/*;q=0.5",
        "User-Agent": _LAND_LOOKUP_USER_AGENT,
    }
    request_headers.update(_NSPD_BROWSER_HEADERS)
    results: dict[str, Any] = {}
    for name, url in candidates.items():
        request = urllib.request.Request(url, headers=request_headers)
        context = ssl._create_unverified_context() if _nspd_tls_insecure else None
        try:
            try:
                with urllib.request.urlopen(request, timeout=20, context=context) as response:
                    raw = response.read(200_000)
            except urllib.error.URLError as exc:
                if not isinstance(getattr(exc, "reason", None), ssl.SSLError):
                    raise
                with urllib.request.urlopen(
                        request, timeout=20,
                        context=ssl._create_unverified_context()) as response:
                    raw = response.read(200_000)
            results[name] = {
                "ok": raw[:4] == b"\x89PNG", "bytes": len(raw),
                "head": "PNG" if raw[:4] == b"\x89PNG"
                        else raw[:60].decode("latin-1", "replace"),
            }
        except urllib.error.HTTPError as exc:
            results[name] = {"ok": False, "http": exc.code}
        except Exception as exc:
            results[name] = {"ok": False, "error": str(exc)[:160]}
    return {"bbox_merc": parts, "probe": results}


def _nspd_getfeatureinfo(lat: float, lng: float, layer_id: int,
                         api_version: str = "v3",
                         bounds: tuple[float, float, float, float] | None = None) -> Any:
    """WMS GetFeatureInfo произвольного слоя НСПД в точке — как клик по карте.

    Тот же запрос, что `_nspd_point_features` шлёт на слой ЗУ (36048), но с
    любым номером слоя: так проверяется, какие слои скрининга (ЗОУИТ, терр.
    зоны, красные линии) отвечают в точке и какие атрибуты несут. Тайл
    web-меркатора zoom 24, пиксель точки, INFO_FORMAT=application/json.
    Версия пути: **GetFeatureInfo живёт на v3** — проба 17.08.2026 показала,
    что v4 на GetFeatureInfo отвечает 502, тогда как v3 отдаёт 200 (пусто там,
    где объекта нет). На v4 карта дёргает только GetMap (тайлы) — разные
    операции, разные версии. Бросает HTTPException — обработку оставляем
    вызывающему.
    """
    if bounds is not None:
        # Опрос контура, а не точки. Пиксель запроса растягивается на весь
        # участок: WMS ищет объекты под пикселем, и пиксель размером с участок
        # спрашивает «что пересекает этот участок» вместо «что лежит вот в этой
        # точке». Охранная зона ЛЭП идёт полосой вдоль границы — в центр она не
        # попадает, и слой отвечал пусто (участок 50:21:0120316:1221, владелец
        # 23.08.2026). Ответ выходит с запасом: зона, задевшая рамку, но не сам
        # участок, отсеется долей накрытия — её считает `_land_coverage_shares`
        # по настоящему контуру, а не по рамке.
        west, south, east, north = bounds
        params = urllib.parse.urlencode({
            "REQUEST": "GetFeatureInfo", "SERVICE": "WMS", "VERSION": "1.3.0",
            "INFO_FORMAT": "application/json", "FORMAT": "image/png", "STYLES": "",
            "TRANSPARENT": "true", "QUERY_LAYERS": layer_id, "LAYERS": layer_id,
            "WIDTH": 1, "HEIGHT": 1, "I": 0, "J": 0,
            "CRS": "EPSG:4326", "BBOX": f"{west},{south},{east},{north}",
            "FEATURE_COUNT": "50",
        })
        return _nspd_getfeatureinfo_request(params, layer_id, api_version)

    zoom = 24
    tiles = 1 << zoom
    tile_size = 512
    lat_rad = math.radians(lat)
    xtile = int((lng + 180.0) / 360.0 * tiles)
    ytile = int((1.0 - math.asinh(math.tan(lat_rad)) / math.pi) / 2.0 * tiles)
    west = xtile / tiles * 360.0 - 180.0
    east = (xtile + 1) / tiles * 360.0 - 180.0
    north = math.degrees(math.atan(math.sinh(math.pi * (1.0 - 2.0 * ytile / tiles))))
    south = math.degrees(math.atan(math.sinh(math.pi * (1.0 - 2.0 * (ytile + 1) / tiles))))
    i = int((lng - west) / (east - west) * tile_size)
    j = int((lat - south) / (north - south) * tile_size)
    params = urllib.parse.urlencode({
        "REQUEST": "GetFeatureInfo", "SERVICE": "WMS", "VERSION": "1.3.0",
        "INFO_FORMAT": "application/json", "FORMAT": "image/png", "STYLES": "",
        "TRANSPARENT": "true", "QUERY_LAYERS": layer_id, "LAYERS": layer_id,
        "WIDTH": tile_size, "HEIGHT": tile_size, "I": i, "J": tile_size - j,
        "CRS": "EPSG:4326", "BBOX": f"{west},{south},{east},{north}",
        "FEATURE_COUNT": "10",
    })
    return _nspd_getfeatureinfo_request(params, layer_id, api_version)


def _nspd_getfeatureinfo_request(params: str, layer_id: int, api_version: str) -> Any:
    """Сам запрос GetFeatureInfo: заголовки, предохранитель, разбор ответа.

    Вынесено из `_nspd_getfeatureinfo`, потому что спрашивать можно двумя
    способами — точкой и контуром, — а отвечает на них один и тот же портал с
    одним и тем же WAF и одним предохранителем. Второй экземпляр этой обвязки
    разошёлся бы с первым: паузу считали бы порознь.
    """
    version = api_version if api_version in {"v3", "v4"} else "v3"
    # Referer под конкретный слой: WAF НСПД отдал Forbidden на тематические
    # слои, пока мы слали общий `thematic=PKK` (кадастровая карта). В браузере
    # у этих запросов Referer вида `map?thematic=Default…&active_layers=<слой>`
    # (заголовки сняты владельцем 17.08.2026) — повторяем его дословно.
    layer_headers = {
        "Referer": (f"{_NSPD_BASE_URL}/map?thematic=Default&zoom=17"
                    f"&baselayerid=235&active_layers={layer_id}"),
    }
    # Предохранитель: НСПД придушивает за частые запросы (17.08.2026 — серия
    # 400 по всем слоям). Скрининг — не главная функция, а вот поиск участка
    # у пользователей живёт на той же НСПД: разведка не имеет права довести
    # портал до жёсткой блокировки. Серия отказов закрывает скрининг на паузу,
    # поиск ЕГРН при этом продолжает работать своим путём.
    global _nspd_screen_failures, _nspd_screen_blocked_until
    if time.time() < _nspd_screen_blocked_until:
        left = int(_nspd_screen_blocked_until - time.time())
        raise HTTPException(
            status_code=503,
            detail=f"Скрининг на паузе: НСПД ограничила запросы, осталось {left} с.")
    try:
        payload = _land_fetch_json(
            f"{_NSPD_BASE_URL}/api/aeggis/{version}/{layer_id}/wms?{params}",
            service="Сервис НСПД", headers=layer_headers,
        )
    except HTTPException as exc:
        # Предохранитель взводит только отказ портала (Forbidden). Несуществующий
        # номер слоя НСПД отдаёт как Internal Server Error — это нормальный ответ
        # «такого слоя нет», и при разведке их много: считая их отказами,
        # предохранитель убивал перебор после пятого номера (17.08.2026).
        if "forbidden" in str(getattr(exc, "detail", "")).lower():
            _nspd_screen_failures += 1
            if _nspd_screen_failures >= _NSPD_SCREEN_FAILURES_LIMIT:
                _nspd_screen_blocked_until = time.time() + _NSPD_SCREEN_COOLDOWN_SECONDS
                _nspd_screen_failures = 0
        raise
    _nspd_screen_failures = 0
    return payload


@app.get("/land/screen-probe", include_in_schema=False)
def land_screen_probe(lat: float = 0.0, lng: float = 0.0, layers: str = "",
                      ver: str = "v3", cad: str = "", reset: int = 0) -> dict[str, Any]:
    """Диагностика слоёв НСПД для скрининга: что отвечает GetFeatureInfo в точке.

    Первый тест архитектуры скрининга (docs/land_screening_architecture.md):
    несёт ли слой «Территориальные зоны» параметры застройки атрибутами или
    только индекс зоны, какие номера слоёв ЗОУИТ реальны. С телефона и Render
    НСПД закрыт WAF — перебор идёт с ядра, поэтому запрос форвардится туда, как
    /land/map-probe. Только диагностика: не кэширует, ничего не меняет.

    Параметры: lat/lng — точка (по умолчанию центр Москвы); cad — кадастровый
    номер: если задан, точка берётся из центра участка (удобно бить по знакомому
    участку с ЗОУИТ); layers — список «имя=номер» через запятую (по умолчанию
    `_NSPD_SCREEN_LAYER_CANDIDATES`); ver — версия пути aeggis для
    GetFeatureInfo: `v3` (дефолт; v4 на GetFeatureInfo отвечает 502 — v4 только
    для GetMap-тайлов, проба 17.08.2026). Ответ по каждому слою: http/число
    объектов/ключи и образец properties первого объекта — по ним видно, какой
    номер какому слою отвечает.
    """
    remote = _core_api_url("/land/screen-probe")
    if remote:
        query = urllib.parse.urlencode(
            {"lat": lat, "lng": lng, "layers": layers, "ver": ver, "cad": cad,
             "reset": reset})
        try:
            with urllib.request.urlopen(
                    urllib.request.Request(
                        remote + "?" + query, headers={"Accept": "application/json"}),
                    timeout=120) as response:
                return json.loads(response.read().decode("utf-8"))
        except Exception as exc:
            raise HTTPException(status_code=502, detail=f"Ядро недоступно: {exc}")

    global _nspd_screen_failures, _nspd_screen_blocked_until
    if reset:
        # Диагностике нужно снимать собственную паузу: иначе одна проба
        # закрывает следующую на 15 минут, и вместо ответа НСПД видно только
        # свой предохранитель (17.08.2026). Боевой путь этим не пользуется.
        _nspd_screen_failures = 0
        _nspd_screen_blocked_until = 0.0

    number = _land_text(cad).strip()
    if number:
        # Кадастр → центр участка: бить по знакомому участку удобнее, чем по
        # координатам. Тот же путь, что overlay-probe: поиск → геометрия → центр.
        for feature in _nspd_search_features(number):
            center = _geometry_center(feature.get("geometry"))
            if center:
                lat, lng = center["lat"], center["lng"]
                break

    if not lat and not lng:
        lat, lng = 55.751244, 37.618423  # центр Москвы — точка по умолчанию
    layer_map: dict[str, int] = {}
    for token in (layers or "").split(","):
        token = token.strip()
        if not token:
            continue
        name, _, number = token.partition("=")
        try:
            layer_map[name.strip() or number.strip()] = int(number.strip())
        except ValueError:
            continue
    if not layer_map:
        layer_map = dict(_NSPD_SCREEN_LAYER_CANDIDATES)

    results: dict[str, Any] = {}
    for name, layer_id in layer_map.items():
        try:
            payload = _nspd_getfeatureinfo(lat, lng, layer_id, ver)
        except HTTPException as exc:
            # Текст обязателен: _land_fetch_json сводит любой 4xx НСПД к нашему
            # 400, и подлинная причина (403 WAF, 429 лимит) видна только в нём.
            results[name] = {"layer_id": layer_id, "http": exc.status_code,
                             "detail": str(getattr(exc, "detail", ""))[:200]}
            continue
        except Exception as exc:
            results[name] = {"layer_id": layer_id, "error": str(exc)[:160]}
            continue
        features = _nspd_features(payload)
        entry: dict[str, Any] = {"layer_id": layer_id, "features": len(features)}
        if features:
            options = _nspd_options(features[0])
            entry["keys"] = sorted(options.keys())
            entry["sample"] = {
                key: (str(value)[:120] if value is not None else None)
                for key, value in list(options.items())[:20]
            }
        results[name] = entry
    paused = max(0, int(_nspd_screen_blocked_until - time.time()))
    return {"point": {"lat": lat, "lng": lng},
            "screen_paused_seconds": paused, "layers": results}


@app.get("/land/layer-sweep", include_in_schema=False)
def land_layer_sweep(lat: float = 0.0, lng: float = 0.0, cad: str = "",
                     start: int = 37570, end: int = 37600) -> dict[str, Any]:
    """Перебор номеров слоёв НСПД по точке: какой номер — какой слой.

    Каталога слоёв НСПД не публикует, а ловить каждый номер в браузере — долго
    (17 слоёв на карте). Но ответ слоя самоописателен: `categoryName` называет
    слой словами. Поэтому номера ищутся перебором с ядра по точке, где
    ограничения заведомо есть, и возвращаются только ответившие — с именем и
    образцом типа. Это разовая разведка, не рабочий путь: найденные номера
    заводятся в реестр и дальше опрашиваются адресно.

    Диапазон ограничен 200 номерами за вызов — чтобы не молотить НСПД.
    """
    remote = _core_api_url("/land/layer-sweep")
    if remote:
        query = urllib.parse.urlencode(
            {"lat": lat, "lng": lng, "cad": cad, "start": start, "end": end})
        try:
            with urllib.request.urlopen(
                    urllib.request.Request(
                        remote + "?" + query, headers={"Accept": "application/json"}),
                    timeout=300) as response:
                return json.loads(response.read().decode("utf-8"))
        except Exception as exc:
            raise HTTPException(status_code=502, detail=f"Ядро недоступно: {exc}")

    number = _land_text(cad).strip()
    if number:
        for feature in _nspd_search_features(number):
            center = _geometry_center(feature.get("geometry"))
            if center:
                lat, lng = center["lat"], center["lng"]
                break
    if not lat and not lng:
        raise HTTPException(status_code=400, detail="Нужна точка: cad или lat/lng.")
    span = int(end) - int(start) + 1
    # 60 номеров — предел, который укладывается в срок соединения: перебор в
    # 200 номеров с паузой рвал ответ («Empty reply from server», 17.08.2026),
    # а оборванный вызов выглядит как пустой улов.
    if span < 1 or span > 60:
        raise HTTPException(status_code=400, detail="Диапазон — до 60 номеров за вызов.")

    def probe(layer_id: int) -> tuple[int, dict[str, Any] | None, str]:
        """→ (номер, находка или None, причина отказа или '')."""
        try:
            payload = _nspd_getfeatureinfo(lat, lng, layer_id, "v3")
        except HTTPException as exc:
            reason = str(getattr(exc, "detail", ""))[:120] or f"http {exc.status_code}"
            # Цифры выкидываем: в причине бывает обратный отсчёт («осталось 899 с»),
            # и тогда каждая строка уникальна, а свод превращается в простыню.
            reason = re.sub(r"\d+", "N", reason)
            return layer_id, None, reason
        except Exception as exc:
            return layer_id, None, type(exc).__name__
        features = _nspd_features(payload)
        if not features:
            return layer_id, None, ""
        options = _nspd_options(features[0])
        return layer_id, {
            "features": len(features),
            "categoryName": _land_text(options.get("categoryName")),
            "type_zone": _land_text(options.get("type_zone")),
            "label": _land_text(options.get("label")),
        }, ""

    found: dict[str, Any] = {}
    empty = 0
    failures: dict[str, int] = {}
    # Перебор идёт в один поток с паузой: 200 запросов очередью НСПД срезает,
    # и тогда «ничего не найдено» — на деле «всё отбито» (пустой улов на точке,
    # где ЗОУИТ заведомо есть, 17.08.2026). Отказы считаются и возвращаются:
    # молчащий перебор неотличим от честной пустоты, а это уже неверный вывод.
    for layer_id in range(int(start), int(end) + 1):
        _, entry, failure = probe(layer_id)
        if entry:
            found[str(layer_id)] = entry
        elif failure:
            failures[failure] = failures.get(failure, 0) + 1
        else:
            empty += 1
        time.sleep(_NSPD_SWEEP_PAUSE_SECONDS)
    return {"point": {"lat": lat, "lng": lng},
            "range": [int(start), int(end)],
            "stats": {"probed": span, "answered": len(found),
                      "empty": empty, "failed": sum(failures.values())},
            "failures": failures, "found": found}


# Подслои ЗОУИТ на геопортале НСПД (культурного наследия, энергетики/связи/
# транспорта, природных территорий, охраняемых объектов, иные). Опрашиваются
# через GetFeatureInfo на v3 — сверено пробой 17.08.2026 по участку
# 50:20:0070312:8320: слой 37581 вернул приаэродромную территорию Внуково
# со всеми атрибутами (тип, реестровый номер, ограничение, документ).
_NSPD_ZOUIT_LAYERS: tuple[int, ...] = (37577, 37578, 37579, 37580, 37581)

# Полный набор слоёв скрининга. Имён здесь НЕТ — и не нужно: слой называет себя
# сам (`categoryName`, `type_zone`), поэтому что именно нашлось, известно из
# ответа. Это снимает всю ручную разведку «какой номер чему соответствует»:
# каталог id снят с консоли карты 18.08.2026 (приложение печатает свой реестр),
# а смысл приходит в момент запроса. Неверный номер отвечает Internal Server
# Error и просто пропускается.
# Весь снятый каталог, а не выборка: угадывать «нужен ли номер» нельзя — так
# теряется слой, о котором мы не подумали (лес, вода, ОКН). Опрашиваем всё,
# показываем то, что вернулось; лишнее отсекает `_LAND_SCREEN_NOISE` по имени,
# несуществующее отвечает Internal Server Error и пропускается. Цена — около
# шестидесяти запросов на участок, поэтому результат живёт в кэше шесть часов.
_NSPD_SCREEN_LAYERS: tuple[int, ...] = _NSPD_ZOUIT_LAYERS + (
    # тематический кластер: ЗОУИТ-соседи, ООПТ, терр. зоны, красные линии
    875815, 875817, 875819, 875824, 875831, 875832, 875835, 875838, 875840,
    875845, 875846, 875847, 875848, 875865, 875866, 875874, 875882, 879243,
    # кластер 872 тыс.
    872153, 872155, 872164, 872182, 872183, 872202, 872203, 872205, 872206,
    872210, 872211, 872212, 872213, 872216, 872217, 872218, 872219, 872220,
    872221, 872222, 872224, 872262,
    # кластер 36–37 тыс. (без 36048 — это сам участок, он в карточке)
    36049, 36070, 36071, 36328, 36329, 36473, 36945,
    37236, 37294, 37295, 37298, 37299, 37313, 37430, 37433, 37434, 37768,
)

# Что в скрининг не идёт, даже если ответило: административная и справочная
# «обвязка» публичной кадастровой карты. Отбор по имени слоя, а не по номеру, —
# номера меняются, названия говорят сами за себя.
_LAND_SCREEN_NOISE: tuple[str, ...] = (
    "субъекты российской федерации", "муниципальные образования",
    "населённые пункты", "населенные пункты", "кадастровое деление",
    "кадастровые районы", "кадастровые кварталы", "охотничьи угодья",
    "земельные участки", "объекты капитального строительства",
    "комплексы объектов", "тепловая карта", "единицы кадастрового деления",
    "границы субъектов", "границы муниципальных", "границы населённых",
    # Боевой отчёт 18.08.2026 вывел их как «ограничение неизвестного типа»:
    # это справочные слои публичной карты, а не ограничения.
    "здания", "сооружения", "помещения", "кадастровые округа",
    "объекты незавершённого", "объекты незавершенного", "машино-места",
)

# Пауза между запросами разведки слоёв. Очередь без пауз НСПД срезает целиком.
_NSPD_SWEEP_PAUSE_SECONDS = _env_float("NSPD_SWEEP_PAUSE", 0.4)

# Предохранитель скрининга: столько отказов подряд — и запросы слоёв встают на
# паузу. Бережёт не скрининг, а поиск участка: он живёт на той же НСПД.
_NSPD_SCREEN_FAILURES_LIMIT = int(_env_float("NSPD_SCREEN_FAILURES_LIMIT", 5))
_NSPD_SCREEN_COOLDOWN_SECONDS = _env_float("NSPD_SCREEN_COOLDOWN", 900.0)
_nspd_screen_failures = 0
_nspd_screen_blocked_until = 0.0


# Классы флагов скрининга. `killer` — жильё в такой зоне запрещено, дальше
# считать экономику бессмысленно; `economic` — режет пятно или высоту, то есть
# бьёт по выручке; `info` — знать полезно, решения не меняет. Классифицируем
# по типу зоны словами, а не по номеру слоя: тип приходит в ответе, а номера
# у подслоёв меняются. Неопознанный тип — `info` с честной пометкой, а не
# молчаливое «ничего страшного»: неизвестное ограничение не равно отсутствию.
_LAND_SCREEN_CLASSES: tuple[tuple[str, tuple[str, ...], str], ...] = (
    ("killer", ("санитарно-защитн", "сзз"),
     "жилая застройка в СЗЗ запрещена"),
    ("killer", ("особо охраняем", "оопт", "заповедн", "заказник"),
     "застройка ООПТ запрещена"),
    ("killer", ("леснич", "лесопарк", "лесной фонд"),
     "земли лесного фонда — застройка запрещена"),
    ("economic", ("приаэродромн",),
     "ограничение высоты — влияет на этажность и выручку"),
    ("economic", ("культурног наследия", "культурного наследия", "окн", "объекта культурн"),
     "ограничения по высоте и облику"),
    ("economic", ("красн", "линии градостроительного регулирования"),
     "территория общего пользования не застраивается"),
    ("economic", ("водоохранн", "прибрежн", "береговая", "водного объекта"),
     "ограничения в водоохранной зоне"),
    ("economic", ("охранная зона", "охранн"),
     "в охранной зоне строить нельзя — режет пятно"),
    # Территориальная зона — не ограничение, а рамка: она задаёт, что здесь
    # вообще разрешено строить. В отчёте она шла «ограничением неизвестного
    # типа» (18.08.2026), хотя это самая нужная справка на участке.
    ("info", ("территориальн",),
     "территориальная зона по ПЗЗ — сверьте ВРИ с намеченной застройкой"),
)


def _land_screen_classify(finding: dict[str, Any]) -> dict[str, Any]:
    """Класс флага и его последствие по типу зоны — словами, не по номеру слоя."""
    haystack = " ".join([
        _land_text(finding.get("type_zone")), _land_text(finding.get("name")),
    ]).lower()
    for flag_class, needles, impact in _LAND_SCREEN_CLASSES:
        if any(needle in haystack for needle in needles):
            return {**finding, "flag_class": flag_class, "impact": impact}
    return {**finding, "flag_class": "info",
            "impact": "ограничение неизвестного типа — требует проверки вручную"}


# ---------------------------------------------------------------------------
# Наложение зон на участок: не «зона есть», а «сколько участка она съела».
#
# Скрининг спрашивает НСПД в одной точке — центре участка. Этого хватает на
# вопрос «есть ли зона», но не на вопрос сделки: зона, срезающая угол, в центр
# не попадает вовсе, а накрывшая центр выглядит одинаково и при пяти процентах,
# и при ста (замечание владельца, 18.08.2026). Геометрия зоны приходит тем же
# ответом GetFeatureInfo и до сих пор выбрасывалась — теперь она пересекается с
# контуром участка.
#
# Считаем долю сеткой, а не аналитическим пересечением полигонов: клиппинг
# вогнутых мультиполигонов с дырами — отдельная библиотека, которой в образе
# нет, а доля с точностью процента отвечает на вопрос «часть или целиком».
# Строки сетки обсчитываются построчно (пересечения рёбер с горизонталью), а
# не точка за точкой: у приаэродромной зоны десятки тысяч вершин, и наивный
# перебор занял бы минуты.

_LAND_COVERAGE_GRID = 48


def _geometry_polygons_mercator(geometry: Any) -> list[list[list[tuple[float, float]]]]:
    """Полигоны геометрии в метрах веб-меркатора: [полигон][кольцо][точка].

    НСПД отдаёт то меркатор, то WGS84 — различаем по величине, как это уже
    делает `_geometry_center`. Первое кольцо полигона — внешнее, остальные
    дыры; чётно-нечётное правило обрабатывает их само.
    """
    if not isinstance(geometry, dict):
        return []
    coordinates = geometry.get("coordinates")
    kind = str(geometry.get("type") or "").lower()
    if kind == "polygon":
        raw = [coordinates]
    elif kind == "multipolygon":
        raw = list(coordinates or [])
    else:
        return []
    polygons: list[list[list[tuple[float, float]]]] = []
    for polygon in raw:
        rings: list[list[tuple[float, float]]] = []
        for ring in polygon or []:
            points: list[tuple[float, float]] = []
            for point in ring or []:
                if not (isinstance(point, (list, tuple)) and len(point) >= 2):
                    continue
                x, y = float(point[0]), float(point[1])
                if abs(x) <= 180.0 and abs(y) <= 90.0:
                    merc_x = x * 20037508.34 / 180.0
                    merc_y = math.log(math.tan((90.0 + y) * math.pi / 360.0)) / (math.pi / 180.0)
                    points.append((merc_x, merc_y * 20037508.34 / 180.0))
                else:
                    points.append((x, y))
            if len(points) >= 3:
                rings.append(points)
        if rings:
            polygons.append(rings)
    return polygons


def _polygons_bbox(polygons: list[list[list[tuple[float, float]]]]) -> tuple[float, float, float, float] | None:
    xs = [p[0] for polygon in polygons for ring in polygon for p in ring]
    ys = [p[1] for polygon in polygons for ring in polygon for p in ring]
    if not xs or not ys:
        return None
    return min(xs), min(ys), max(xs), max(ys)


def _row_crossings(polygons: list[list[list[tuple[float, float]]]], y: float) -> list[float]:
    """Абсциссы пересечений всех рёбер с горизонталью `y`, по возрастанию."""
    crossings: list[float] = []
    for polygon in polygons:
        for ring in polygon:
            previous = ring[-1]
            for point in ring:
                y1, y2 = previous[1], point[1]
                # Строго один знак сравнения на конец ребра, иначе вершина,
                # лежащая ровно на строке, считается дважды и переворачивает
                # чётность на всю оставшуюся строку.
                if (y1 > y) != (y2 > y):
                    t = (y - y1) / (y2 - y1)
                    crossings.append(previous[0] + t * (point[0] - previous[0]))
                previous = point
    crossings.sort()
    return crossings


def _inside_by_crossings(crossings: list[float], x: float) -> bool:
    left = 0
    for value in crossings:
        if value > x:
            break
        left += 1
    return left % 2 == 1


def _land_coverage_shares(parcel: Any, zones: list[Any],
                          counted: list[bool] | None = None,
                          grid: int = _LAND_COVERAGE_GRID) -> dict[str, Any]:
    """Доли участка под каждой зоной и доля, свободная от всех считаемых.

    `shares` — по индексу зоны, 0..1; `None` там, где у зоны нет геометрии:
    «не проверяли» и «ноль процентов» — разные ответы, и путать их нельзя.
    `counted` отмечает зоны, которые режут строимое пятно (запреты и то, что
    влияет на посадку); справочные слои вроде территориальных зон накрывают
    участок целиком и свободного места не отнимают. Пустой ответ — считать
    было не из чего.
    """
    parcel_polygons = _geometry_polygons_mercator(parcel)
    bbox = _polygons_bbox(parcel_polygons)
    if not parcel_polygons or not bbox:
        return {}
    zone_polygons = [_geometry_polygons_mercator(zone) for zone in zones]
    counts = list(counted) if counted is not None else [True] * len(zone_polygons)
    counts += [True] * (len(zone_polygons) - len(counts))
    min_x, min_y, max_x, max_y = bbox
    if max_x <= min_x or max_y <= min_y:
        return {}
    step_x = (max_x - min_x) / grid
    step_y = (max_y - min_y) / grid
    inside_total = 0
    hits = [0] * len(zone_polygons)
    free = 0
    for row in range(grid):
        y = min_y + (row + 0.5) * step_y
        parcel_row = _row_crossings(parcel_polygons, y)
        if not parcel_row:
            continue
        zone_rows = [_row_crossings(polygons, y) if polygons else [] for polygons in zone_polygons]
        for column in range(grid):
            x = min_x + (column + 0.5) * step_x
            if not _inside_by_crossings(parcel_row, x):
                continue
            inside_total += 1
            covered = False
            for index, crossings in enumerate(zone_rows):
                if crossings and _inside_by_crossings(crossings, x):
                    hits[index] += 1
                    if counts[index]:
                        covered = True
            if not covered:
                free += 1
    if not inside_total:
        return {}
    return {
        "shares": [None if not polygons else hit / inside_total
                   for hit, polygons in zip(hits, zone_polygons)],
        "free": free / inside_total,
        "samples": inside_total,
    }


# Контуры зон для рисунка: полные кольца весят сотни килобайт, а на картинке
# размером с почтовую марку различима сотня точек. Отдаём только те кольца,
# что задевают окрестность участка, и прореживаем их до разумного числа вершин
# — рисунок отвечает на вопрос «где именно накрывает», а не заменяет карту.
_LAND_ZONE_RING_POINTS = 240


def _land_zone_outline(geometry: Any, bbox: tuple[float, float, float, float],
                       limit: int = _LAND_ZONE_RING_POINTS) -> list[list[list[float]]]:
    min_x, min_y, max_x, max_y = bbox
    pad_x = (max_x - min_x) * 1.5 + 50.0
    pad_y = (max_y - min_y) * 1.5 + 50.0
    west, south = min_x - pad_x, min_y - pad_y
    east, north = max_x + pad_x, max_y + pad_y
    out: list[list[list[float]]] = []
    for polygon in _geometry_polygons_mercator(geometry):
        for ring in polygon:
            xs = [p[0] for p in ring]
            ys = [p[1] for p in ring]
            # Кольцо, не задевающее окрестность, на рисунке не видно вовсе.
            if max(xs) < west or min(xs) > east or max(ys) < south or min(ys) > north:
                continue
            step = max(1, len(ring) // limit)
            thinned = ring[::step]
            if thinned[0] != ring[-1]:
                thinned.append(ring[0])
            out.append([[round(x, 1), round(y, 1)] for x, y in thinned])
    return out


def _land_screen_findings(lat: float, lng: float,
                          parcel_geometry: Any = None) -> list[dict[str, Any]]:
    """Все ограничения НСПД в точке — по всему набору слоёв, с классификацией.

    Имена слоёв заранее не нужны: что нашлось, говорит сам ответ
    (`categoryName`, `type_zone`). Административная обвязка ПКК (субъекты,
    муниципалитеты, населённые пункты, кадастровое деление, охотугодья)
    отсеивается по имени — это контекст, а не ограничение. Дубли по реестровому
    номеру убираются, сбойный слой пропускается. Пустой список — ограничений
    в точке не обнаружено (не «их нет вовсе»: НСПД видит внесённые в ЕГРН).
    """
    findings: list[dict[str, Any]] = []
    seen: set[str] = set()
    # Контур участка, а не его центр. Полоса вдоль границы — охранная зона ЛЭП,
    # газопровод, красная линия — в центр не попадает вовсе, слой отвечает
    # пусто, и вердикт говорит «критических ограничений не обнаружено» на
    # непроверенном (участок 50:21:0120316:1221, владелец 23.08.2026). Нет
    # геометрии — спрашиваем точкой, но это другой ответ, и он назван.
    bounds = _geometry_bounds_wgs84(parcel_geometry)

    def ask(layer_id: int) -> tuple[int, list[dict[str, Any]]]:
        try:
            # Контур передаётся, только когда он есть: без него это тот же
            # точечный запрос, что и раньше, и лишний аргумент у него ничего
            # не значит.
            answer = (_nspd_getfeatureinfo(lat, lng, layer_id, "v3", bounds) if bounds
                      else _nspd_getfeatureinfo(lat, lng, layer_id, "v3"))
            return layer_id, _nspd_features(answer)
        except Exception:
            return layer_id, []

    # Шесть десятков слоёв по очереди — это полминуты ожидания у человека.
    # Опрашиваем в несколько потоков, как поиск участков; порядок сохраняем
    # (pool.map отдаёт результаты в порядке входа), чтобы вывод был стабильным.
    with concurrent.futures.ThreadPoolExecutor(max_workers=_LAND_LOOKUP_WORKERS) as pool:
        answers = list(pool.map(ask, _NSPD_SCREEN_LAYERS))

    for layer_id, features in answers:
        for feature in features:
            options = _nspd_options(feature)
            title = " ".join([
                _land_text(options.get("categoryName")),
                _land_text(options.get("type_zone")),
            ]).lower()
            if any(noise in title for noise in _LAND_SCREEN_NOISE):
                continue
            reg_number = _land_text(options.get("reg_numb_border") or options.get("descr"))
            key = reg_number or _land_text(options.get("interactionId"))
            if not key or key in seen:
                continue
            seen.add(key)
            findings.append(_land_screen_classify({
                "type_zone": _land_text(options.get("type_zone")),
                "category": _land_text(options.get("categoryName")),
                "name": (_land_text(options.get("name_by_doc"))
                         or _land_text(options.get("type_zone"))
                         or _land_text(options.get("categoryName"))),
                "reg_number": reg_number,
                "restriction": _land_text(options.get("content_restrict_encumbrances")),
                "document": _land_text(options.get("legal_act_document_name")),
                "document_number": _land_text(options.get("legal_act_document_number")),
                "document_date": _land_text(options.get("legal_act_document_date")),
                "layer_id": layer_id,
                # Геометрия зоны приходит тем же ответом и до сих пор
                # выбрасывалась. Она нужна ровно на один вопрос: зона съела
                # угол участка или весь участок.
                "geometry": feature.get("geometry") if isinstance(feature, dict) else None,
            }))
    _land_apply_coverage(findings, parcel_geometry)
    grouped = _land_group_findings(findings)
    # Чем спрошено — часть ответа. «Опрошен контур» и «опрошена одна точка» —
    # это разница между «проверено» и «похоже, чисто», и читатель обязан её
    # видеть, а не выводить из пустого списка.
    for item in grouped:
        item["probe_method"] = "contour" if bounds else "point"
    return grouped


def _land_apply_coverage(findings: list[dict[str, Any]], parcel_geometry: Any) -> None:
    """Проставляет каждой находке долю участка под ней и общее свободное пятно.

    Справочные слои (`info` — территориальные зоны и подобное) накрывают
    участок целиком и строимого пятна не отнимают: в свободную долю они не
    входят, хотя своя доля у них считается.
    """
    if not findings or not parcel_geometry:
        return
    coverage = _land_coverage_shares(
        parcel_geometry,
        [item.get("geometry") for item in findings],
        counted=[item.get("flag_class") in {"killer", "economic"} for item in findings])
    if not coverage:
        return
    # Очертания для рисунка снимаются здесь же, пока геометрия под рукой:
    # второй раз просить её у НСПД значило бы платить за то же самое дважды.
    bbox = _polygons_bbox(_geometry_polygons_mercator(parcel_geometry))
    for item, share in zip(findings, coverage.get("shares") or []):
        geometry = item.pop("geometry", None)
        if share is not None:
            item["coverage_pct"] = round(share * 100.0, 1)
        # Рамка запроса шире участка намеренно — иначе полоса вдоль границы не
        # находится. Плата за это: в ответ попадают зоны, задевшие рамку, но не
        # сам участок. Измеренный ноль их и означает: ни одна из точек сетки
        # внутри контура в зону не попала. «Ноль» и «нет геометрии» — разные
        # ответы: у второго доля не измерена, и считать его отсутствующим на
        # участке нельзя. Тонкая полоса, реально пересекающая контур, ноль не
        # даёт — она ловится сеткой и показывается как «<0,1%».
        item["on_parcel"] = share is None or share > 0
        if bbox and share:
            outline = _land_zone_outline(geometry, bbox)
            if outline:
                item["outline_merc"] = outline
    for item in findings:
        item.pop("geometry", None)
        item["free_pct"] = round(float(coverage.get("free") or 0.0) * 100.0, 1)


def _land_group_findings(findings: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Одно ограничение — одна строка, даже если реестровых записей несколько.

    Приаэродромная территория приходит подзонами: на участке под Внуково их
    оказалось четыре, и в блоке было четыре почти одинаковых строки про один и
    тот же приказ (боевая проверка 18.08.2026). Человеку важно ограничение, а
    не число записей о нём: группируем по типу зоны и документу, реестровые
    номера собираем списком — они остаются в отчёте полностью.
    """
    grouped: dict[str, dict[str, Any]] = {}
    order: list[str] = []
    for finding in findings:
        # Группируем по типу зоны, а не по документу: на боевом участке вышло
        # три десятка записей «Зона с особыми условиями …» с разными приказами,
        # и блок превратился в стену (18.08.2026). Человеку нужен вид
        # ограничения; приказы и реестровые номера остаются внутри строки.
        key = (_land_text(finding.get("type_zone")).lower()
               or _land_text(finding.get("category")).lower()
               or _land_text(finding.get("name")).lower())
        current = grouped.get(key)
        if current is None:
            entry = dict(finding)
            entry["reg_numbers"] = [n for n in [finding.get("reg_number")] if n]
            entry["documents"] = [d for d in [_land_text(finding.get("document_number"))] if d]
            grouped[key] = entry
            order.append(key)
            continue
        number = _land_text(finding.get("reg_number"))
        if number and number not in current["reg_numbers"]:
            current["reg_numbers"].append(number)
        document = _land_text(finding.get("document_number"))
        if document and document not in current["documents"]:
            current["documents"].append(document)
        # Доля участка у группы — наибольшая среди подзон: подзоны
        # приаэродромной вложены друг в друга, и складывать их значило бы
        # насчитать двести процентов на одном участке.
        share = finding.get("coverage_pct")
        if share is not None and share > (current.get("coverage_pct") or 0.0):
            current["coverage_pct"] = share
        # Ограничение лежит на участке, если на нём лежит хоть одна его подзона.
        # Тридцать семь подзон СЗЗ, из которых ни одна участка не касается, —
        # это соседнее предприятие, попавшее в рамку запроса, а не запрет здесь.
        if finding.get("on_parcel"):
            current["on_parcel"] = True
        current.setdefault("on_parcel", False)
        # Рисунок показывает все подзоны разом: одна из них — не ограничение,
        # а его кусок.
        if finding.get("outline_merc"):
            current.setdefault("outline_merc", []).extend(finding["outline_merc"])
    result: list[dict[str, Any]] = []
    for key in order:
        entry = grouped[key]
        numbers = entry.get("reg_numbers") or []
        if len(numbers) > 1:
            # Имя одной записи теряет смысл, когда их несколько: называем зону.
            entry["name"] = (_land_text(entry.get("type_zone"))
                             or _land_text(entry.get("category")) or entry["name"])
            entry["zones_count"] = len(numbers)
            # Список номеров у трёх десятков записей нечитаем: показываем первые.
            entry["reg_numbers"] = numbers[:3]
            entry["reg_numbers_more"] = max(0, len(numbers) - 3)
        entry["reg_number"] = numbers[0] if numbers else entry.get("reg_number")
        documents = entry.get("documents") or []
        if len(documents) > 1:
            entry["document"] = "оснований"
            entry["document_number"] = f"{len(documents)} документов"
            entry["document_date"] = ""
        result.append(entry)
    return result


# Готовая оценка участка живёт шесть часов: ограничения меняются реже, а
# каждый скрининг — это два десятка запросов к НСПД.
_LAND_SCREENING_CACHE: dict[str, tuple[float, Any]] = {}
_LAND_SCREENING_TTL_SECONDS = _env_float("LAND_SCREENING_TTL", 21600.0)
# Мелкие участки посадку не определяют, а стоят те же шесть десятков запросов
# к НСПД: на площадке из двадцати двух половина — нарезка по три сотки
# (решение владельца, 19.08.2026). Порог в сотках, ноль — проверять всё.
_LAND_SCREENING_MIN_AREA_SQM = _env_float("LAND_SCREENING_MIN_AREA_SQM", 1000.0)
# Пауза перед повтором запроса в НСПД: сервис отвечает не на каждый запрос.
_LAND_RETRY_PAUSE_SECONDS = _env_float("LAND_RETRY_PAUSE_SECONDS", 0.6)

# Порядок вывода флагов: сперва то, что запрещает жильё, потом то, что режет
# экономику, потом справочное. Внутри класса — как пришло от НСПД.
_LAND_SCREEN_ORDER = {"killer": 0, "economic": 1, "info": 2}


def _land_screening_verdict(findings: list[dict[str, Any]],
                            probed: bool = True,
                            method: str = "") -> dict[str, Any]:
    """Свод по находкам. Никакого «участок подходит» — только факты и их вес.

    Запрещено выдавать разрешительный вывод (решение владельца, архитектура,
    раздел 8): максимум — «критических ограничений не обнаружено», и то с
    оговоркой, что видно лишь внесённое в ЕГРН.

    `method` — чем спрашивали: `contour` (по контуру участка) или `point` (в
    одной точке, когда границ нет). Полоса вдоль границы в центр не попадает,
    поэтому точечный опрос не доказывает чистоты участка — и оговорка обязана
    это говорить, а не оставлять читателя выводить из пустого списка.

    `probed` — спрашивали ли вообще НСПД. Без сведений ЕГРН у участка нет
    границ, спрашивать не о чем, и пустой список находок значит «не проверяли»,
    а не «чисто». Прежде эти два случая были неотличимы: на запросе, где не
    нашёлся ни один из трёх номеров, экран показывал зелёное «критических
    ограничений не обнаружено» — разрешающий вывод на пустоте (18.08.2026).
    """
    # Рамка запроса шире участка, поэтому в находки попадают и зоны по
    # соседству. Красный вердикт «жилая застройка запрещена» из-за СЗЗ, не
    # касающейся участка ни одним процентом, — ложная тревога худшего рода
    # (экран владельца, 23.08.2026). Вердикт считает то, что на участке;
    # соседнее остаётся в списке, но отдельно и без веса.
    here = [f for f in findings if f.get("on_parcel", True)]
    nearby = [f for f in findings if not f.get("on_parcel", True)]
    killers = [f for f in here if f.get("flag_class") == "killer"]
    economic = [f for f in here if f.get("flag_class") == "economic"]
    if not probed:
        status = "NOT_SCREENED"
        headline = "Скрининг не выполнен: сведений ЕГРН по участку нет"
    elif killers:
        status, headline = "CRITICAL", "Найдены ограничения, запрещающие жилую застройку"
    elif economic:
        status, headline = "WARNING", "Есть ограничения, влияющие на посадку и экономику"
    else:
        status, headline = "NO_CRITICAL_FLAGS", "Критических ограничений не обнаружено"
    # Свободное пятно — общий ответ по участку, у всех находок он один и тот
    # же; у нескольких участков берём худший: сводка не имеет права выглядеть
    # лучше самого стеснённого из них.
    free = [f.get("free_pct") for f in here if f.get("free_pct") is not None]
    return {
        "status": status,
        "headline": headline,
        "free_pct": min(free) if free else None,
        "killer_count": len(killers),
        "economic_count": len(economic),
        "total": len(here),
        # Соседнее считается отдельно и называется числом: молча выброшенное
        # ограничение читается как его отсутствие.
        "nearby_count": len(nearby),
        "probed": bool(probed),
        "probe_method": method or ("contour" if probed else ""),
        "disclaimer": (_land_screening_disclaimer(method) if probed else
                       ("Границы участка не получены, поэтому НСПД об ограничениях "
                        "не спрашивали. Проверьте кадастровый номер или запросите "
                        "выписку ЕГРН.")),
    }


def _land_screening_disclaimer(method: str) -> str:
    """Оговорка называет и границы метода, и то, чем спрошено."""
    base = ("Проверены ограничения, внесённые в ЕГРН и опубликованные в НСПД. "
            "Отсутствие записи не доказывает отсутствия ограничения: сервитуты, "
            "ГПЗУ и часть красных линий в реестре не отражаются.")
    if method == "point":
        return (base + " Слои опрошены в одной точке — центре участка: границ у "
                "него нет, наложить зоны не на что. Полоса вдоль края (охранная "
                "зона ЛЭП, газопровод) в центр не попадает, поэтому пустой "
                "результат проверкой участка не является.")
    return (base + " Слои опрошены по контуру участка целиком, а не в одной точке. "
            "Рамка запроса шире контура, поэтому зоны, задевшие её, но не сам "
            "участок, перечислены отдельно — «рядом с участком» — и на вывод "
            "не влияют.")


@app.get("/land/screening", include_in_schema=False)
def land_screening(cad: str = "", min_area_sqm: float | None = None,
                   limit: int = 30) -> dict[str, Any]:
    """Оценка участка до финмодели: что мешает строить, по кадастровому номеру.

    Самостоятельная ценность продукта: человек вводит номер и сразу видит
    ограничения — ЗОУИТ, ООПТ, красные линии, тип территориальной зоны — с
    реестровым номером и документом-основанием, без всякого расчёта экономики.
    Один участок — коротко, несколько — свод плюс разбивка (решение владельца).
    Числа и факты даёт НСПД, вывод не разрешительный.

    `limit` — сколько участков проверять; ноль и меньше — все. Окну и тизеру
    хватает тридцати, полный PDF проверяет каждый участок проекта (#655).
    """
    remote = _core_api_url("/land/screening")
    if remote:
        try:
            query = {"cad": cad, "limit": limit}
            if min_area_sqm is not None:
                query["min_area_sqm"] = min_area_sqm
            # Холодный участок — шесть десятков слоёв НСПД; на площадке из
            # двадцати участков трёх минут ядру не хватит.
            asked = len(re.findall(r"\d{2}:\d{2}:\d{6,8}:\d+", _land_text(cad)))
            with urllib.request.urlopen(
                    urllib.request.Request(
                        remote + "?" + urllib.parse.urlencode(query),
                        headers={"Accept": "application/json"}),
                    timeout=max(180, 15 * asked)) as response:
                return json.loads(response.read().decode("utf-8"))
        except Exception as exc:
            raise HTTPException(status_code=502, detail=f"Ядро недоступно: {exc}")

    numbers = [n for n in re.split(r"[\s,;]+", _land_text(cad)) if n.strip()]
    numbers = [n for n in numbers if re.match(r"^\d{2}:\d{2}:\d{6,8}:\d+$", n)]
    if not numbers:
        raise HTTPException(status_code=400, detail="cad: кадастровый номер участка.")
    # Предел тот же, что у поиска участков: тридцать. Десяти не хватало —
    # площадка из двадцати двух участков проверялась наполовину (замечание
    # владельца, 19.08.2026). Усечение всё равно называется вслух: молчаливое
    # читается как «проверено всё».
    requested = len(numbers)
    if limit and limit > 0:
        numbers = numbers[:int(limit)]
    threshold = (_LAND_SCREENING_MIN_AREA_SQM if min_area_sqm is None
                 else max(0.0, float(min_area_sqm)))

    parcels: list[dict[str, Any]] = []
    for number in numbers:
        cached = _LAND_SCREENING_CACHE.get(number)
        if cached and time.time() - cached[0] < _LAND_SCREENING_TTL_SECONDS:
            parcels.append(cached[1])
            continue
        try:
            features = _nspd_search_features(number)
            probe_error = ""
        except Exception as exc:
            features = []
            probe_error = _land_text(getattr(exc, "detail", "") or str(exc)) or "запрос не прошёл"
        # НСПД отвечает не на каждый запрос: на площадке из двадцати двух
        # номеров сведения пришли по десяти, и двенадцать участков выглядели
        # несуществующими (замечание владельца, 19.08.2026). Один повтор
        # возвращает большую часть — молчаливая потеря участка дороже запроса.
        if not features:
            time.sleep(_LAND_RETRY_PAUSE_SECONDS)
            try:
                features = _nspd_search_features(number)
                if features:
                    probe_error = ""
            except Exception as exc:
                probe_error = probe_error or _land_text(getattr(exc, "detail", "") or str(exc))
        matched = None
        for feature in features:
            options = _nspd_options(feature)
            if _land_text(_nspd_value(options, "cadastral_number")) == number:
                matched = feature
                break
        matched = matched or (features[0] if features else None)
        if matched is None:
            # Сорванный запрос и пустой ответ — разные вещи: первое говорит о
            # нас, второе об участке. Складывать их в одну строку значит
            # выдавать недоступность НСПД за отсутствие сведений.
            parcels.append({"cadastral_number": number, "found": False,
                            "probe_failed": bool(probe_error),
                            "note": (f"Запрос в НСПД не прошёл: {probe_error}" if probe_error
                                     else "Сведения ЕГРН по номеру не получены.")})
            continue
        options = _nspd_options(matched)
        center = _geometry_center(matched.get("geometry")) or {}
        findings: list[dict[str, Any]] = []
        # Мелкий участок в проверку не идёт: сведения ЕГРН по нему стоят один
        # запрос, а скрининг — шестьдесят два, и посадку он всё равно не
        # определяет. Пропуск не выдаётся за проверку: у участка стоит признак.
        parcel_area = _land_float(_nspd_value(options, "area_sqm")) or 0.0
        too_small = bool(threshold and parcel_area and parcel_area < threshold)
        probe_method = ""
        if center and not too_small:
            # Контур участка идёт в скрининг: зоны накладываются на него, и
            # видно, съели они угол или весь участок.
            findings = _land_screen_findings(center["lat"], center["lng"],
                                             matched.get("geometry"))
            findings.sort(key=lambda f: _LAND_SCREEN_ORDER.get(f.get("flag_class"), 3))
            probe_method = ("contour" if _geometry_bounds_wgs84(matched.get("geometry"))
                            else "point")
        area = _land_float(_nspd_value(options, "area_sqm"))
        contour = _geometry_contours_merc(matched.get("geometry"))
        parcel = {
            "cadastral_number": number,
            "found": True,
            # Рисунок пятна: контур участка и очертания зон в одной плоскости.
            "contour_merc": contour,
            "address": _land_text(_nspd_value(options, "address")),
            "area_sqm": area,
            "area_ha": round(area / 10000.0, 4) if area else None,
            "category": _land_text(_nspd_value(options, "category")),
            "permitted_use": _land_text(_nspd_value(options, "permitted_use")),
            "center": center or None,
            # Находки на участке и находки по соседству — разные ответы.
            # Соседнее не выбрасывается: рамка запроса его увидела, и молчать
            # об этом нельзя. Но и в один список с ограничениями участка оно не
            # идёт — иначе тридцать семь подзон чужой СЗЗ выглядят запретом
            # здесь.
            "findings": [f for f in findings if f.get("on_parcel", True)],
            "nearby": [f for f in findings if not f.get("on_parcel", True)],
            "too_small": too_small,
            "probe_method": probe_method,
            "verdict": _land_screening_verdict(findings,
                                               probed=bool(center) and not too_small,
                                               method=probe_method),
        }
        _LAND_SCREENING_CACHE[number] = (time.time(), parcel)
        parcels.append(parcel)

    everything = [f for p in parcels for f in p.get("findings", [])]
    nearby_total = sum(len(p.get("nearby") or []) for p in parcels)
    probed = any(p.get("found") and p.get("center") for p in parcels)
    return {
        "parcels": parcels,
        "requested_count": requested,
        "checked_count": len(numbers),
        "min_area_sqm": threshold,
        "small_count": sum(1 for p in parcels if p.get("too_small")),
        "nearby_count": nearby_total,
        "single": len(parcels) == 1,
        # У свода метод — худший из участков: один точечный опрос делает
        # оговоркой всю сводку, иначе она выглядит увереннее своей слабой части.
        "verdict": _land_screening_verdict(
            everything, probed=probed,
            method=("point" if any(p.get("probe_method") == "point" for p in parcels)
                    else ("contour" if probed else ""))),
        "calculated_at": datetime.now().strftime("%d.%m.%Y %H:%M"),
    }


def _land_zouit_findings(lat: float, lng: float) -> list[dict[str, Any]]:
    """Пересекающие точку ЗОУИТ из НСПД — структурировано, для скрининга.

    По каждому подслою ЗОУИТ шлёт GetFeatureInfo (v3) и собирает находки:
    тип зоны, наименование по документу, реестровый номер границы, текст
    ограничения и реквизиты устанавливающего документа. Дубли (один и тот же
    реестровый номер приходит из нескольких подслоёв) отбрасываются. Слой,
    ответивший ошибкой, пропускается — одна недоступная ветка не рушит скрининг.
    Возвращает список; пусто — ограничений в точке не обнаружено (не «нет
    ЗОУИТ вообще»: НСПД видит только внесённые в ЕГРН).
    """
    findings: list[dict[str, Any]] = []
    seen: set[str] = set()
    for layer_id in _NSPD_ZOUIT_LAYERS:
        try:
            payload = _nspd_getfeatureinfo(lat, lng, layer_id, "v3")
        except Exception:
            continue
        for feature in _nspd_features(payload):
            options = _nspd_options(feature)
            reg_number = _land_text(options.get("reg_numb_border") or options.get("descr"))
            key = reg_number or _land_text(options.get("interactionId"))
            if not key or key in seen:
                continue
            seen.add(key)
            findings.append({
                "type_zone": _land_text(options.get("type_zone")),
                "name": _land_text(options.get("name_by_doc")) or _land_text(options.get("type_zone")),
                "reg_number": reg_number,
                "restriction": _land_text(options.get("content_restrict_encumbrances")),
                "document": _land_text(options.get("legal_act_document_name")),
                "document_number": _land_text(options.get("legal_act_document_number")),
                "document_date": _land_text(options.get("legal_act_document_date")),
                "layer_id": layer_id,
            })
    return findings


def _nspd_wms_map_png(west: float, south: float, east: float, north: float,
                      width: int, height: int) -> bytes:
    """Картинка слоя «Земельные участки из ЕГРН» под меркаторный bbox.

    Формат сверен пробой /land/map-probe на проде (16.08.2026): НСПД отдаёт
    PNG только на EPSG:3857 с меркаторным bbox, EPSG:4326 в обоих порядках
    осей отвечает 404. Прозрачность true — как в пробе; фон выравнивает
    land_map_image.
    """
    params = urllib.parse.urlencode({
        "REQUEST": "GetMap",
        "SERVICE": "WMS",
        "VERSION": "1.3.0",
        "FORMAT": "image/png",
        "STYLES": "",
        "TRANSPARENT": "true",
        "LAYERS": _NSPD_LANDS_LAYER_ID,
        "WIDTH": int(width),
        "HEIGHT": int(height),
        "CRS": "EPSG:3857",
        "BBOX": f"{west},{south},{east},{north}",
    })
    request_headers = {
        "Accept": "image/png,image/*;q=0.9,*/*;q=0.5",
        "Accept-Language": "ru-RU,ru;q=0.9",
        "User-Agent": _LAND_LOOKUP_USER_AGENT,
    }
    request_headers.update(_NSPD_BROWSER_HEADERS)
    external_request = urllib.request.Request(
        f"{_NSPD_BASE_URL}/api/aeggis/v3/{_NSPD_LANDS_LAYER_ID}/wms?{params}",
        headers=request_headers,
    )
    # Тот же TLS-фолбэк, что у поиска (_land_fetch_json): сертификат НСПД —
    # российский УЦ, и без повтора без проверки карта падала с
    # CERTIFICATE_VERIFY_FAILED. Флаг — на процесс, а воркеров два: читать его
    # мало, надо уметь взводить и здесь, иначе карта живёт только в том
    # воркере, где до неё уже искали участок (скриншот владельца, 16.08.2026).
    global _nspd_tls_insecure
    context = ssl._create_unverified_context() if _nspd_tls_insecure else None
    try:
        with urllib.request.urlopen(
                external_request, timeout=_NSPD_TIMEOUT_SECONDS, context=context) as response:
            raw = response.read(4 * 1024 * 1024)
    except urllib.error.URLError as exc:
        if not (
            _NSPD_TLS_FALLBACK
            and not _nspd_tls_insecure
            and isinstance(getattr(exc, "reason", None), ssl.SSLError)
        ):
            raise
        _nspd_tls_insecure = True
        with urllib.request.urlopen(
                external_request, timeout=_NSPD_TIMEOUT_SECONDS,
                context=ssl._create_unverified_context()) as response:
            raw = response.read(4 * 1024 * 1024)
    if not raw.startswith(b"\x89PNG"):
        raise ValueError("НСПД ответила не картинкой")
    return raw


@app.get("/land/map-image", include_in_schema=False)
def land_map_image(bbox: str = "") -> Response:
    """Подложка кадастровой карты под меркаторный bbox контура.

    Страница передаёт ровно тот bbox (с полем), в котором рисует SVG-контур,
    а НСПД принимает его тем же меркатором (EPSG:3857, сверено пробой) —
    подложка и контур совпадают пиксель в пиксель без пересчётов. Любой
    сбой — 502, и страница просто остаётся с чистым контуром: подложка —
    украшение, а не данные.
    """
    remote = _core_api_url("/land/map-image")
    if remote:
        # Как /land/lookup: Render до НСПД не ходит — пересылает на ядро.
        try:
            with urllib.request.urlopen(
                    urllib.request.Request(
                        remote + "?" + urllib.parse.urlencode({"bbox": bbox}),
                        headers={"Accept": "image/png"}),
                    timeout=_NSPD_TIMEOUT_SECONDS) as response:
                raw = response.read(4 * 1024 * 1024)
        except Exception as exc:
            raise HTTPException(status_code=502, detail=f"Подложка карты недоступна: {exc}")
        return Response(raw, media_type="image/png",
                        headers={"Cache-Control": "public, max-age=3600"})
    try:
        parts = [float(x) for x in str(bbox or "").split(",")]
    except ValueError:
        parts = []
    if len(parts) != 4:
        raise HTTPException(status_code=400, detail="bbox: minX,minY,maxX,maxY в метрах веб-меркатора.")
    min_x, min_y, max_x, max_y = parts
    span_x, span_y = max_x - min_x, max_y - min_y
    if not (0 < span_x <= 20000 and 0 < span_y <= 20000):
        # Больше 20 км — это уже не карточка участка, а карта страны.
        raise HTTPException(status_code=400, detail="bbox вне разумного размера участка.")
    # Ширина до 640 px; высота — из меркаторных пропорций bbox, чтобы
    # совпасть с SVG-контуром страницы.
    width = 640
    height = max(64, min(1280, int(round(width * span_y / span_x))))
    cache_key = f"{round(min_x)}:{round(min_y)}:{round(max_x)}:{round(max_y)}"
    cached = _NSPD_MAP_CACHE.get(cache_key)
    if cached and time.time() - cached[0] < _NSPD_MAP_CACHE_TTL_SECONDS:
        return Response(cached[1], media_type="image/png",
                        headers={"Cache-Control": "public, max-age=3600"})
    try:
        raw = _nspd_wms_map_png(min_x, min_y, max_x, max_y, width, height)
        # НСПД отвечает прозрачным PNG (проба), а прозрачность дальше опасна:
        # фото бота при конвертации в RGB получило бы чёрный фон. Плоское
        # светлое основание кладётся один раз здесь.
        from PIL import Image
        layer = Image.open(io.BytesIO(raw)).convert("RGBA")
        base = Image.new("RGBA", layer.size, (245, 245, 243, 255))
        base.alpha_composite(layer)
        buffer = io.BytesIO()
        base.convert("RGB").save(buffer, format="PNG")
        raw = buffer.getvalue()
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Подложка карты недоступна: {exc}")
    if len(_NSPD_MAP_CACHE) >= _NSPD_MAP_CACHE_LIMIT:
        _NSPD_MAP_CACHE.pop(next(iter(_NSPD_MAP_CACHE)), None)
    _NSPD_MAP_CACHE[cache_key] = (time.time(), raw)
    return Response(raw, media_type="image/png",
                    headers={"Cache-Control": "public, max-age=3600"})


def _basemap_zoom(min_x: float, max_x: float, min_y: float, max_y: float, width: int) -> int:
    """Масштаб тайлов под ширину картинки — и под бюджет запросов.

    Сначала берётся тот масштаб, при котором тайл ложится пиксель в пиксель:
    крупнее — мыло, мельче — лишние запросы. Потом масштаб понижается, пока
    склейка не влезет в бюджет: чужой сервис не должен платить за нашу карту
    сотней обращений.
    """
    world = 2 * 20037508.342789244
    span_x = max(max_x - min_x, 1.0)
    zoom = int(round(math.log2(world / 256.0 / (span_x / max(width, 1)))))
    zoom = max(1, min(18, zoom))
    while zoom > 1:
        scale = world / (256.0 * (1 << zoom))
        tiles = (math.ceil(span_x / scale / 256.0) + 1) * (
            math.ceil(max(max_y - min_y, 1.0) / scale / 256.0) + 1
        )
        if tiles <= _BASEMAP_TILE_BUDGET:
            break
        zoom -= 1
    return zoom


def _osm_tile(zoom: int, x: int, y: int) -> bytes:
    """Один тайл, с кэшем на неделю: карта улиц за неделю не меняется."""
    key = f"{zoom}/{x}/{y}"
    cached = _OSM_TILE_CACHE.get(key)
    if cached and time.time() - cached[0] < _OSM_TILE_CACHE_TTL_SECONDS:
        return cached[1]
    url = _OSM_TILE_URL.format(z=zoom, x=x, y=y)
    request = urllib.request.Request(url, headers={
        # Тайловый сервис требует, чтобы клиент назывался: обезличенный запрос
        # он вправе отклонить, и правильно делает.
        "User-Agent": _LAND_LOOKUP_USER_AGENT,
        "Accept": "image/png,image/*;q=0.9",
    })
    with urllib.request.urlopen(request, timeout=_NSPD_TIMEOUT_SECONDS) as response:
        raw = response.read(1024 * 1024)
    if len(_OSM_TILE_CACHE) >= _OSM_TILE_CACHE_LIMIT:
        _OSM_TILE_CACHE.pop(next(iter(_OSM_TILE_CACHE)), None)
    _OSM_TILE_CACHE[key] = (time.time(), raw)
    return raw


def _basemap_png(min_x: float, min_y: float, max_x: float, max_y: float, width: int) -> bytes:
    """Склеенная карта улиц под меркаторный bbox.

    Тайлы приходят кусками, а странице нужна одна картинка под тот же bbox, в
    котором она рисует точки: иначе совмещать пришлось бы в браузере, и любое
    расхождение округлений уводило бы проект на соседнюю улицу.
    """
    from PIL import Image

    zoom = _basemap_zoom(min_x, max_x, min_y, max_y, width)
    world = 2 * 20037508.342789244
    origin = -20037508.342789244
    scale = world / (256.0 * (1 << zoom))  # метров на пиксель
    # Пиксель всей карты мира: y растёт вниз, поэтому север — это минус.
    def px(x: float) -> float:
        return (x - origin) / scale

    def py(y: float) -> float:
        return (-y - origin) / scale

    left, right = px(min_x), px(max_x)
    top, bottom = py(max_y), py(min_y)
    x0, x1 = int(math.floor(left / 256)), int(math.floor((right - 1e-6) / 256))
    y0, y1 = int(math.floor(top / 256)), int(math.floor((bottom - 1e-6) / 256))
    limit = 1 << zoom
    canvas = Image.new("RGB", ((x1 - x0 + 1) * 256, (y1 - y0 + 1) * 256), (238, 238, 233))
    got = 0
    for tx in range(x0, x1 + 1):
        for ty in range(y0, y1 + 1):
            if not (0 <= ty < limit):
                continue
            try:
                raw = _osm_tile(zoom, tx % limit, ty)
                tile = Image.open(io.BytesIO(raw)).convert("RGB")
            except Exception:
                # Один не пришедший тайл — дырка в карте, а не отказ от карты.
                continue
            canvas.paste(tile, ((tx - x0) * 256, (ty - y0) * 256))
            got += 1
    if not got:
        raise RuntimeError("ни один тайл не получен")
    crop = canvas.crop((
        int(round(left - x0 * 256)), int(round(top - y0 * 256)),
        int(round(right - x0 * 256)), int(round(bottom - y0 * 256)),
    ))
    # Выше натурального размера не растягиваем: тайл отдал столько пикселей,
    # сколько отдал, и растянутая вдвое подпись улицы читается хуже мелкой.
    # Ширину картинки на экране держит рамка, а не растр.
    width = min(width, crop.width)
    height = max(32, int(round(width * crop.height / max(crop.width, 1))))
    crop = crop.resize((width, height), Image.LANCZOS)
    buffer = io.BytesIO()
    crop.save(buffer, format="PNG")
    return buffer.getvalue()


# Гибрид Яндекса (снимок + улицы и подписи) — только в браузере, через
# JavaScript API 2.1 и только с ключом. Склеить его здесь, как OSM, нельзя по
# двум причинам сразу: серверные API Яндекса (Static API и Tiles API) отдают
# одну схему, а условия использования (п. 5.1.2 и 5.1.6) запрещают сохранять и
# видоизменять полученные картинки. Поэтому в PDF и в бот уходит схема OSM, а
# снимок живёт в живой карте страницы. Ключ — браузерный по природе: Яндекс
# грузит карту по нему в самом браузере, а защищается он ограничением по
# адресу сайта в кабинете разработчика. Значение ключа в журнал не пишется.
_YANDEX_MAPS_KEY_ENV = "YANDEX_MAPS_API_KEY"
_YANDEX_MAPS_SCRIPT = "https://api-maps.yandex.ru/2.1/?lang=ru_RU&coordorder=latlong&apikey="
BASEMAP_LAYERS = ("map", "hybrid")
_HYBRID_SERVER_REASON = (
    "Снимок со спутника Яндекс показывает только на живой карте страницы: "
    "картинкой на сервер он его не отдаёт, а сохранять его в файлы условия "
    "Яндекса запрещают. Поэтому в отчёт и в бот уходит карта улиц."
)
_HYBRID_NO_KEY_REASON = (
    "Вид со снимком со спутника пока не подключён: для карт Яндекса нужен "
    "ключ доступа, а его ещё не оформили. Карта улиц работает как обычно."
)


def _basemap_views_local() -> dict[str, Any]:
    key = _env_str(_YANDEX_MAPS_KEY_ENV, "").strip()
    hybrid: dict[str, Any] = {
        "available": bool(key),
        "provider": "Яндекс Карты",
        "reason": "" if key else _HYBRID_NO_KEY_REASON,
        "script": (_YANDEX_MAPS_SCRIPT + urllib.parse.quote(key, safe="")) if key else "",
        "print_reason": _HYBRID_SERVER_REASON,
    }
    return {
        "default": "map",
        "map": {"available": True, "provider": "OpenStreetMap", "reason": ""},
        "hybrid": hybrid,
    }


@app.get("/land/basemap-views", include_in_schema=False)
def land_basemap_views() -> dict[str, Any]:
    """Какие виды подложки есть у живой карты: «Схема» всегда, «Гибрид» — с ключом.

    Один ответ на вопрос «предлагать ли гибрид», и все карты страницы читают
    его, а не проверяют ключ сами. Нет ключа — гибрид не предлагается, и
    причина названа словами: молча подменить снимок схемой значило бы показать
    не то, что выбрали. Ключ лежит на ядре; Render спрашивает ядро.
    """
    views = _basemap_views_local()
    if views["hybrid"]["available"]:
        return views
    remote = _core_api_url("/land/basemap-views")
    if not remote:
        return views
    try:
        with urllib.request.urlopen(
                urllib.request.Request(remote, headers={"Accept": "application/json"}),
                timeout=_NSPD_TIMEOUT_SECONDS) as response:
            answer = json.loads(response.read(64 * 1024).decode("utf-8"))
        if isinstance(answer, dict) and isinstance(answer.get("hybrid"), dict):
            return answer
        raise ValueError("ответ без описания видов")
    except Exception as exc:
        views["hybrid"]["reason"] = (
            "Вид со снимком со спутника сейчас недоступен: сервер расчётов не "
            f"ответил, есть ли ключ Яндекс Карт ({type(exc).__name__}). "
            "Карта улиц работает как обычно."
        )
        return views


@app.get("/land/basemap", include_in_schema=False)
def land_basemap(bbox: str = "", width: int = 1024, layer: str = "map") -> Response:
    """Карта улиц под меркаторный bbox — одной картинкой.

    Тот же договор, что у /land/map-image: страница передаёт bbox, в котором
    сама рисует, и получает растр ровно под него. Отличается слой — не границы
    ЕГРН, а улицы, вода и названия: на пяти километрах рыночной выборки нужны
    они, а кадастровый слой даёт клубок без ориентиров.

    Любой сбой — 502, и карта на странице заменяется схемой с кольцами
    расстояний. Подложка — то, на чём рисуют, а не то, что считают: без неё
    ответ остаётся верным, просто читается хуже.

    `layer=hybrid` — отказ с названной причиной (422), а не 502 и не карта
    улиц вместо снимка: гибрид Яндекса картинкой на сервер не отдаётся.
    """
    layer = str(layer or "map").strip().lower()
    if layer not in BASEMAP_LAYERS:
        raise HTTPException(status_code=400, detail="layer: map или hybrid.")
    if layer == "hybrid":
        raise HTTPException(status_code=422, detail=_HYBRID_SERVER_REASON)
    remote = _core_api_url("/land/basemap")
    if remote:
        # Как /land/map-image: на Render внешние карты не ходят, пересылаем.
        try:
            with urllib.request.urlopen(
                    urllib.request.Request(
                        remote + "?" + urllib.parse.urlencode({"bbox": bbox, "width": width}),
                        headers={"Accept": "image/png"}),
                    timeout=_NSPD_TIMEOUT_SECONDS) as response:
                raw = response.read(8 * 1024 * 1024)
        except Exception as exc:
            raise HTTPException(status_code=502, detail=f"Карта недоступна: {exc}")
        return Response(raw, media_type="image/png",
                        headers={"Cache-Control": "public, max-age=86400"})
    try:
        parts = [float(value) for value in str(bbox or "").split(",")]
    except ValueError:
        parts = []
    if len(parts) != 4:
        raise HTTPException(status_code=400, detail="bbox: minX,minY,maxX,maxY в метрах веб-меркатора.")
    min_x, min_y, max_x, max_y = parts
    span_x, span_y = max_x - min_x, max_y - min_y
    if not (0 < span_x <= 200000 and 0 < span_y <= 200000):
        raise HTTPException(status_code=400, detail="bbox вне разумного размера выборки.")
    width = max(256, min(1536, int(width)))
    cache_key = f"{round(min_x)}:{round(min_y)}:{round(max_x)}:{round(max_y)}:{width}"
    cached = _BASEMAP_CACHE.get(cache_key)
    if cached and time.time() - cached[0] < _BASEMAP_CACHE_TTL_SECONDS:
        return Response(cached[1], media_type="image/png",
                        headers={"Cache-Control": "public, max-age=86400"})
    try:
        raw = _basemap_png(min_x, min_y, max_x, max_y, width)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Карта недоступна: {exc}")
    if len(_BASEMAP_CACHE) >= _BASEMAP_CACHE_LIMIT:
        _BASEMAP_CACHE.pop(next(iter(_BASEMAP_CACHE)), None)
    _BASEMAP_CACHE[cache_key] = (time.time(), raw)
    return Response(raw, media_type="image/png",
                    headers={"Cache-Control": "public, max-age=86400"})


@app.get("/land/tiles/{zoom}/{x}/{y}.png", include_in_schema=False)
def land_tile(zoom: int, x: int, y: int) -> Response:
    """Один тайл подложки — для карты, которую крутят.

    Склеенная картинка (/land/basemap) отвечает на вопрос «как это выглядит» и
    уходит в печать целиком, но подвинуть её нельзя: сервер отдал ровно тот
    bbox, о котором его попросили. Чтобы окружение можно было посмотреть, тайлы
    нужны поштучно — этот маршрут их и отдаёт.

    Три вещи держат нагрузку на источнике в рамках. Тайл кэшируется у нас на
    неделю (`_osm_tile`), браузеру он отдаётся с тем же сроком — повторный
    просмотр того же места до нас не доходит вовсе, — а сам источник задан
    переменной `OSM_TILE_URL`: публичный сервер OSM годится, чтобы посмотреть,
    но под поток живой карты полагается свой или платный, и подставляется он
    одной строкой. Здесь это сказано вслух, потому что молчаливое выкачивание
    чужого сервиса выглядит на нашей стороне точно так же, как своё.

    На Render внешние карты не ходят — как /land/basemap, пересылаем на ядро.
    """
    if not (0 <= zoom <= 19):
        raise HTTPException(status_code=400, detail="Масштаб вне диапазона 0–19.")
    limit = 1 << zoom
    if not (0 <= x < limit and 0 <= y < limit):
        raise HTTPException(status_code=400, detail="Тайл вне карты мира.")
    remote = _core_api_url(f"/land/tiles/{zoom}/{x}/{y}.png")
    if remote:
        try:
            with urllib.request.urlopen(
                    urllib.request.Request(remote, headers={"Accept": "image/png"}),
                    timeout=_NSPD_TIMEOUT_SECONDS) as response:
                raw = response.read(1024 * 1024)
        except Exception as exc:
            raise HTTPException(status_code=502, detail=f"Тайл недоступен: {exc}")
        return Response(raw, media_type="image/png",
                        headers={"Cache-Control": "public, max-age=604800"})
    try:
        raw = _osm_tile(zoom, x, y)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Тайл недоступен: {exc}")
    return Response(raw, media_type="image/png",
                    headers={"Cache-Control": "public, max-age=604800"})


@app.get("/land/overlay-probe", include_in_schema=False)
def land_overlay_probe(cad: str = "") -> Response:
    """Диагностика совмещения контура и подложки по кадастровому номеру.

    Рисует контур участка на растре НСПД ТОЙ ЖЕ bbox→пиксель математикой, что
    SVG карточки. Ляжет контур на границы подложки — сдвиг был в восприятии
    или обобщении растра, наш контур точнее; уедет и здесь — сдвиг в данных, и
    виден его знак. Отделяет браузер от данных: сервер рисует по той же
    формуле, что страница, поэтому расхождение с браузером указало бы на CSS.
    С Render НСПД закрыт WAF — форвард на ядро. Только диагностика, не кэширует.
    """
    remote = _core_api_url("/land/overlay-probe")
    if remote:
        try:
            with urllib.request.urlopen(
                    urllib.request.Request(
                        remote + "?" + urllib.parse.urlencode({"cad": cad}),
                        headers={"Accept": "image/png"}),
                    timeout=_NSPD_TIMEOUT_SECONDS + 15) as response:
                raw = response.read(4 * 1024 * 1024)
        except Exception as exc:
            raise HTTPException(status_code=502, detail=f"Ядро недоступно: {exc}")
        return Response(raw, media_type="image/png", headers={"Cache-Control": "no-store"})

    number = _land_text(cad).strip()
    if not number:
        raise HTTPException(status_code=400, detail="cad: кадастровый номер участка.")
    features = _nspd_search_features(number)
    geometry = None
    for feature in features:
        options = _nspd_options(feature)
        if _land_text(_nspd_value(options, "cadastral_number")) == number:
            geometry = feature.get("geometry")
            break
    if geometry is None and features:
        geometry = features[0].get("geometry")
    rings = _geometry_contours_merc(geometry) if geometry else []
    if not rings:
        raise HTTPException(status_code=404, detail="Контур участка не получен из ЕГРН.")

    xs = [p[0] for ring in rings for p in ring]
    ys = [p[1] for ring in rings for p in ring]
    min_x, max_x, min_y, max_y = min(xs), max(xs), min(ys), max(ys)
    span_x, span_y = max_x - min_x, max_y - min_y
    if not (span_x > 0 and span_y > 0):
        raise HTTPException(status_code=404, detail="Вырожденный контур участка.")
    # Тот же pad и аспект, что landContourSvg + land_map_image: pixel-в-pixel.
    pad = max(span_x, span_y) * 0.06
    w, h = span_x + 2 * pad, span_y + 2 * pad
    width = 640
    height = max(64, min(1280, int(round(width * h / w))))

    from PIL import Image, ImageDraw
    raw = _nspd_wms_map_png(min_x - pad, min_y - pad, max_x + pad, max_y + pad, width, height)
    layer = Image.open(io.BytesIO(raw)).convert("RGBA")
    base = Image.new("RGBA", layer.size, (245, 245, 243, 255))
    base.alpha_composite(layer)
    draw = ImageDraw.Draw(base)
    for ring in rings:
        # Отображение точки в пиксель совпадает с SVG страницы:
        # x=(X-(minX-pad))/w, y=((maxY+pad)-Y)/h — та же формула, что в path.
        pts = [((p[0] - (min_x - pad)) / w * width,
                ((max_y + pad) - p[1]) / h * height) for p in ring]
        if len(pts) >= 2:
            draw.line(pts + [pts[0]], fill=(0, 90, 255, 255), width=3)
    buffer = io.BytesIO()
    base.convert("RGB").save(buffer, format="PNG")
    return Response(buffer.getvalue(), media_type="image/png",
                    headers={"Cache-Control": "no-store"})


def _geocode_yandex(address: str, limit: int) -> list[dict[str, Any]]:
    api_key = _env_str("YANDEX_GEOCODER_API_KEY")
    if not api_key:
        return []
    params = urllib.parse.urlencode({
        "apikey": api_key,
        "format": "json",
        "lang": "ru_RU",
        "results": limit,
        "geocode": address,
    })
    payload = _land_fetch_json(
        f"https://geocode-maps.yandex.ru/1.x/?{params}",
        service="Геокодер Яндекса",
    )
    members = (
        ((payload or {}).get("response") or {}).get("GeoObjectCollection") or {}
    ).get("featureMember") or []
    results: list[dict[str, Any]] = []
    for member in members[:limit]:
        geo_object = (member or {}).get("GeoObject") or {}
        point = _land_text((geo_object.get("Point") or {}).get("pos"))
        chunks = point.split()
        if len(chunks) != 2:
            continue
        lng, lat = _land_float(chunks[0]), _land_float(chunks[1])
        if lat is None or lng is None:
            continue
        meta = (
            (geo_object.get("metaDataProperty") or {}).get("GeocoderMetaData") or {}
        )
        results.append({
            "lat": lat,
            "lng": lng,
            "label": _land_text(meta.get("text")) or _land_text(geo_object.get("name")),
            "provider": "Яндекс",
        })
    return results


def _dadata_suggest(address: str, limit: int) -> list[dict[str, Any]]:
    """Подсказки адресов DaData как есть: с точкой, если она у объекта есть.

    Точка — не признак существования адреса. У владения («влд 12») координат
    в базе часто нет вовсе: DaData ставит точку дому, а владение остаётся
    объектом ФИАС без неё. Пока подсказки собирал геокодер, такие адреса
    выбрасывались молча — на «ул Маршала Воробьёва, влд 12» человек видел
    список домов и ни одного владения, и выглядело это как «в базе такого
    нет». Отсюда деление: подсказка отвечает за адрес, геокодер — за точку,
    и запрос у них общий, чтобы реализация осталась одна.
    """
    api_key = _env_str("DADATA_API_KEY")
    if not api_key:
        return []
    payload = _land_fetch_json(
        "https://suggestions.dadata.ru/suggestions/api/4_1/rs/suggest/address",
        service="DaData",
        data=json.dumps({"query": address, "count": limit}, ensure_ascii=False).encode("utf-8"),
        headers={"Authorization": f"Token {api_key}"},
    )
    results: list[dict[str, Any]] = []
    for suggestion in ((payload or {}).get("suggestions") or [])[:limit]:
        data = (suggestion or {}).get("data") or {}
        results.append({
            "lat": _land_float(data.get("geo_lat")),
            "lng": _land_float(data.get("geo_lon")),
            "label": _land_text(suggestion.get("value")),
            "cadastral_number": _land_text(data.get("cadastral_number") or data.get("house_cadnum")),
            # Регион подсказки DaData объявляет сама — «г Москва», «Московская
            # обл». Он нужен отсеву наравне с ответом Nominatim: DaData стоит в
            # лесенке РАНЬШЕ, и проверка только у последней ступени не работает.
            "region": _land_text(data.get("region_with_type") or data.get("region")),
            # Станции метро приезжали тем же ответом и выбрасывались. Между тем
            # К1 приложения 6 — это ступень по расстоянию до станции, и без
            # него норма брала верхний край 1,0: на Хамовниках это 256 мест
            # вместо 39. Берётся БЛИЖАЙШАЯ и только она: остальные подсказка
            # даёт справочно, а ступень считается по ближайшему входу.
            #
            # Расстояние у DaData — по прямой, а норматив меряет по пешеходным
            # путям. Пеший путь ДЛИННЕЕ прямой, значит настоящий К1 не меньше
            # посчитанного, а К1 только снижает потребность: ошибка идёт в
            # сторону меньшего числа мест, и она названа, а не спрятана.
            "metro": _dadata_nearest_metro(data.get("metro")),
            "provider": "DaData",
        })
    return results


def _dadata_nearest_metro(rows: Any) -> dict[str, Any] | None:
    """Ближайшая станция из подсказки: имя, линия и расстояние в МЕТРАХ.

    DaData даёт расстояние в километрах и с точкой; норматив считает метрами,
    и оставить километры значило бы получить ступень «менее 1200 м» на любом
    адресе. Пустой список — это `None`, а не нулевое расстояние: ноль читался
    бы как «станция под окном».
    """
    best: dict[str, Any] | None = None
    for row in (rows or []):
        distance_km = _land_float((row or {}).get("distance"))
        if distance_km is None or distance_km < 0:
            continue
        if best is None or distance_km < best["distance_km"]:
            best = {
                "name": _land_text((row or {}).get("name")),
                "line": _land_text((row or {}).get("line")),
                "distance_km": distance_km,
                "distance_m": round(distance_km * 1000.0),
            }
    return best


def _geocode_dadata(address: str, limit: int) -> list[dict[str, Any]]:
    """Геокодер: та же выдача, но только то, у чего есть координаты.

    Здесь отсев по точке на месте — геокодеру без неё отвечать нечем.
    """
    return [item for item in _dadata_suggest(address, limit)
            if item.get("lat") is not None and item.get("lng") is not None]


def _geocode_nominatim(address: str, limit: int) -> list[dict[str, Any]]:
    global _nominatim_last_call
    with _nominatim_lock:
        # Условия OSM: не чаще одного запроса в секунду.
        wait = 1.0 - (time.time() - _nominatim_last_call)
        if wait > 0:
            time.sleep(min(wait, 1.0))
        _nominatim_last_call = time.time()
    region = _query_region(address)
    # `state` рядом с `q` слать нельзя: структурный запрос Nominatim с
    # свободным не совмещается, и сервер отвечает 400. Первая версия сужения
    # добавляла его — и запасной геокодер начал падать ровно на тех запросах,
    # которые сужение и затевалось ради: где названа Москва или область
    # (живой ответ портала, 31.08.2026). Регион остаётся условием, но
    # проверяется по ОТВЕТУ, а не по запросу.
    params = urllib.parse.urlencode({
        "q": address,
        "format": "jsonv2",
        "limit": limit,
        "accept-language": "ru",
        "countrycodes": "ru",
        "addressdetails": 1,
    })
    payload = _land_fetch_json(
        f"{_NOMINATIM_BASE_URL}/search?{params}",
        service="Геокодер OpenStreetMap",
    )
    results: list[dict[str, Any]] = []
    for item in (payload or [])[:limit]:
        lat, lng = _land_float((item or {}).get("lat")), _land_float((item or {}).get("lon"))
        if lat is None or lng is None:
            continue
        label = _land_text(item.get("display_name"))
        results.append({
            "lat": lat,
            "lng": lng,
            "label": label,
            # По России Nominatim несёт регион полем `state`: «Москва»,
            # «Московская область», «Тульская область».
            "region": _land_text(((item or {}).get("address") or {}).get("state")),
            "provider": "OpenStreetMap",
        })
    return results


# Регион, названный в самом запросе. Города в запросе к геокодеру не было
# вовсе — стоял только `countrycodes=ru`, — поэтому «Москва Мишина 46» искалось
# по всей стране: «находил везде, не только в Москве» (владелец, 30.08.2026).
#
# Двух регионов достаточно: мы работаем по Москве и области, а у участка регион
# написан первыми цифрами кадастрового номера, и сверка выходит дармовой.
# Регион, которого тут нет, ничего не отсекает — лучше не проверять, чем
# отсеять верное по неполному справочнику.
# Имя региона — то, как его называет ОТВЕТ геокодера (поле `address.state`),
# а не то, как его пишут в запросе. Прежде именем становилась первая поисковая
# метка, и у области выходило «Москва» — строка, которой в ответах нет вовсе.
# Метки ищутся по границе слова, а не подстрокой: «мо,» с запятой не опознавало
# «Химки, МО» в конце строки, а «москва» подстрокой ловится внутри «московская».
_QUERY_REGIONS: tuple[tuple[str, re.Pattern[str], tuple[str, ...]], ...] = (
    ("Московская область",
     re.compile(r"московск\w*\s+обл|подмосков\w*|\bмо\b", re.IGNORECASE), ("50",)),
    ("Москва", re.compile(r"\bмоскв\w*\b", re.IGNORECASE), ("77",)),
)


def _query_region(address: str) -> tuple[str, re.Pattern[str], tuple[str, ...]] | None:
    """Какой регион назван в запросе: его имя для геокодера и коды кадастра.

    Область проверяется раньше города: «Московская область» содержит в себе
    слово «Москва», и порядок наоборот отдал бы области московский код.
    """
    text = re.sub(r"\s+", " ", str(address or "")).strip()
    for name, marks, codes in _QUERY_REGIONS:
        if marks.search(text):
            return (name, marks, codes)
    return None


def _in_region(candidate: dict[str, Any], marks: re.Pattern[str]) -> bool:
    """Находка из названного региона — по её собственному признаку.

    Судим тем же выражением, что опознаёт регион в запросе: две проверки на
    одно правило однажды разошлись бы. Свой регион кандидат объявляет сам
    (DaData — «г Москва», Nominatim — `address.state`); объявленный и не
    совпавший отбрасывается. Не объявлен — судим по подписи, и только по
    границе слова: подстрокой «москва» входит в «московская», и Подмосковье
    проходило московский отсев целиком.
    """
    region = str(candidate.get("region") or "").strip()
    if region:
        return bool(marks.search(region))
    return bool(marks.search(str(candidate.get("label") or "")))


def _same_region(number: str, codes: tuple[str, ...]) -> bool:
    """Первые цифры кадастрового номера — это регион, и сверка тут дармовая."""
    head = str(number or "").split(":", 1)[0].strip()
    return not head or not codes or head in codes


_GEOCODERS = (
    ("yandex", _geocode_yandex),
    ("dadata", _geocode_dadata),
    ("nominatim", _geocode_nominatim),
)


def _geocode_address(address: str, limit: int) -> tuple[list[dict[str, Any]], list[str]]:
    """Точка по адресу и то, чем именно она найдена.

    Спуск по лесенке говорится вслух: провайдер без ключа возвращает пустоту,
    а не ошибку, поэтому падение на запасной геокодер было неотличимо от
    плохого адреса. А запасной ищет по всей стране, и «Москва Мишина 46»
    находилось где угодно.
    """
    forced = _env_str("LAND_LOOKUP_GEOCODER").lower()
    warnings: list[str] = []
    silent: list[str] = []
    region = _query_region(address)
    named = {"yandex": "Яндекс", "dadata": "DaData", "nominatim": "OpenStreetMap"}
    for name, provider in _GEOCODERS:
        if forced and forced != name:
            continue
        try:
            candidates = provider(address, limit)
        except HTTPException as exc:
            warnings.append(str(exc.detail))
            silent.append(named.get(name, name))
            continue
        if region and candidates:
            # Названный в запросе регион — условие для ЛЮБОЙ ступени лесенки, а
            # не только для последней. Проверка стояла внутри Nominatim, а
            # DaData отвечает раньше него: «находил везде, не только в Москве»
            # осталось бы верным ровно там, где до Nominatim не доходит.
            outside = [item for item in candidates if not _in_region(item, region[1])]
            candidates = [item for item in candidates if item not in outside]
            if outside and not candidates:
                warnings.append(
                    f"{named.get(name, name)} нашёл адрес вне «{region[0]}»: "
                    + "; ".join(dict.fromkeys(
                        str(item.get("label") or "—") for item in outside[:3]))
                    + ". Уточните запрос или введите кадастровый номер.")
        if candidates:
            if silent:
                warnings.append(
                    "Адрес разобрал " + named.get(name, name) + ": "
                    + ", ".join(silent) + " не ответил" + ("и" if len(silent) > 1 else "")
                    + ". Запасной геокодер ищет грубее.")
            return candidates, warnings
        silent.append(named.get(name, name))
    return [], warnings


def _land_lookup_by_numbers(numbers: list[str]) -> list[dict[str, Any]]:
    if len(numbers) > 1 and _LAND_LOOKUP_WORKERS > 1:
        workers = min(_LAND_LOOKUP_WORKERS, len(numbers))
        with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
            batches = list(pool.map(lambda number: _land_lookup_by_numbers([number]), numbers))
        results = [item for batch in batches for item in batch]
        # Второй заход по промахам — последовательный, чтобы не давить на
        # портал: при параллельном опросе НСПД часть номеров отвечает пусто,
        # и без повтора участок выпадал из расчёта вместе со своей площадью.
        misses = [item["cadastral_number"] for item in results if not item.get("found")]
        if misses:
            retried = {number: _land_lookup_by_numbers([number])[0] for number in misses}
            results = [
                retried.get(item["cadastral_number"], item)
                if not item.get("found") and retried.get(item["cadastral_number"], {}).get("found")
                else item
                for item in results
            ]
        return results
    results: list[dict[str, Any]] = []
    for number in numbers:
        parts = _cadastral_number_parts(number)
        try:
            features = _nspd_search_features(number)
        except HTTPException as exc:
            results.append({
                "found": False,
                # НСПД не ответил (503/429/таймаут) — это не «объекта нет».
                # Читатели, которые кэшируют ответ, обязаны переспросить.
                "lookup_failed": True,
                "cadastral_number": number,
                "region": parts["region_hint"],
                "quarter": parts["quarter"],
                "map_url": _nspd_map_url(None, number),
                "note": str(exc.detail),
            })
            continue
        matched = [
            item for item in features
            if _land_text(_nspd_value(_nspd_options(item), "cadastral_number")) == number
        ] or features[:1]
        if not matched:
            results.append({
                "found": False,
                "cadastral_number": number,
                "region": parts["region_hint"],
                "quarter": parts["quarter"],
                "map_url": _nspd_map_url(None, number),
                "note": "В ЕГРН по этому номеру сведений не найдено.",
            })
            continue
        results.append(_normalize_nspd_feature(matched[0], number))
    return results


def _land_lookup_features_to_results(
    features: list[dict[str, Any]], limit: int, *, only_land: bool = False
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    """Нормализованные объекты ЕГРН и счётчик скрытого по видам."""
    normalized = [_normalize_nspd_feature(item) for item in features]
    hidden: dict[str, int] = {}
    if only_land:
        for item in normalized:
            if item["kind"] != "land":
                hidden[item["kind"]] = hidden.get(item["kind"], 0) + 1
        normalized = [item for item in normalized if item["kind"] == "land"]
    lands = [item for item in normalized if item["kind"] == "land"]
    ordered = lands + [item for item in normalized if item["kind"] != "land"]
    unique: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in ordered:
        key = item["cadastral_number"] or json.dumps(item.get("center") or {}, sort_keys=True)
        if key in seen:
            continue
        seen.add(key)
        unique.append(item)
        if len(unique) >= limit:
            break
    return unique, hidden


class LandLookupRequest(BaseModel):
    # Поиск по адресу отдаёт только земельные участки. Флаг снимает фильтр,
    # если по адресу нужны все объекты ЕГРН.
    include_premises: bool = False
    query: str = ""
    limit: int = 30
    # Только для учёта: кто искал участок. На поиск не влияет.
    session: str = ""


class LandLotContextRequest(BaseModel):
    """Кадастровый контекст лота: объект торгов и земля под ним."""
    cadastral_numbers: list[str] = []
    # Только для учёта: кто открыл карточку лота. На поиск не влияет.
    session: str = ""


class VriManualRequest(BaseModel):
    """Свой расчёт платы за ВРИ: метры и основания задаёт человек."""
    rows: list[dict[str, Any]] = []
    rent_coeff: float = 0.0
    index: float | None = None
    land_right: str = "ownership"


@app.post("/vri/manual")
def vri_manual(req: VriManualRequest) -> dict[str, Any]:
    """Плата за смену ВРИ по своим метрам.

    Калькулятор ГлавАПУ считает по нормативному ТЭП — плотность на площадь
    участка. Когда ТЭП утверждён решением ГЗК и метров в разы меньше, ответ
    калькулятора для этого проекта неверен, а подменять его молча нельзя.
    Поэтому свой расчёт стоит рядом и подписан своим.
    """
    return vri_manual_payment(req.rows, req.rent_coeff, req.index,
                              land_right=req.land_right)


class BaselineRecalcRequest(BaseModel):
    """Пересчёт по параметрам исходного расчёта ГлавАПУ."""
    baseline: dict[str, Any] = {}
    areas: dict[str, Any] = {}


@app.post("/tep/recalc-from-baseline")
def tep_recalc_from_baseline(req: BaselineRecalcRequest) -> dict[str, Any]:
    """Новые метры на ставках территории из исходного расчёта.

    Второй калькулятор не строим: территория уже посчитана городом, ставки
    снимаются с его же выгрузки и потому не стареют. Метод проверяет себя
    обратным ходом — на исходном ТЭП обязан воспроизвести исходные числа.
    """
    return recalculate_from_glavapu_baseline(req.baseline, req.areas)


class TepDerivedRequest(BaseModel):
    """Что следует из введённого руками ТЭП: соцпотребность, м/м, МПТ."""
    apartment_area_sqm: float = 0.0
    residential_living_spp_sqm: float = 0.0
    nonresidential_np_sqm: float = 0.0
    k1: float = 1.0
    k2: float = 1.0
    zone_two: bool = False
    upks_rub: float = 0.0
    sqm_per_job: float = 32.0
    parking_norm_regime: str = "2118_2026"
    # Число квартир: задано — постоянные места пунктом 2 по средней квартире.
    apartment_count: float = 0.0
    # Население соцобъектов: норма РНГП или «квартиры × 2,1» (требование органа).
    social_population_method: str = "rngp_area"


@app.post("/tep/derived")
def tep_derived(req: TepDerivedRequest) -> dict[str, Any]:
    """Пересчёт производных под фактический ТЭП: население, места, компенсация,
    машино-места, МПТ. Формулы городские; ответ подписан как наш расчёт."""
    return tep_derived_norms(
        apartment_area_sqm=req.apartment_area_sqm,
        residential_living_spp_sqm=req.residential_living_spp_sqm,
        nonresidential_np_sqm=req.nonresidential_np_sqm,
        k1=req.k1, k2=req.k2, zone_two=req.zone_two,
        upks_rub=req.upks_rub, sqm_per_job=req.sqm_per_job,
        parking_norm_regime=req.parking_norm_regime,
        apartment_count=req.apartment_count,
        social_population_method=req.social_population_method)


class TepRescaleRequest(BaseModel):
    """Пересчёт соцнагрузки пропорцией, когда норматив считать не от чего.

    Места зависят от населения, население — от площади квартир; ставка за место
    у нас задана экспертно и от метража не зависит. Значит при правке ТЭП
    соцнагрузка масштабируется, а не считается заново, — и это верно в любом
    регионе, потому что норматив здесь не применяется вовсе: масштабируется то,
    что УЖЕ посчитано городом или введено человеком.
    """
    apartment_area_before_sqm: float = 0.0
    apartment_area_after_sqm: float = 0.0
    nonresidential_before_sqm: float = 0.0
    nonresidential_after_sqm: float = 0.0
    kindergarten_places: float = 0.0
    school_places: float = 0.0
    clinic_capacity: float = 0.0
    social_compensation_mln: float = 0.0
    underground_manual_spaces: float = 0.0
    basis: str = ""


@app.post("/tep/rescale-social")
def tep_rescale_social(req: TepRescaleRequest) -> dict[str, Any]:
    """Соцнагрузка и машино-места под новый ТЭП — пропорцией от прежних.

    «Почему нельзя брать пропорцию? Количество мест зависит от количества
    людей, а количество людей — от количества жилых площадей. Себестоимости
    места у нас вбиты экспертно» (владелец, 30.08.2026). Верно: норматив линеен
    по населению, а население линейно по площади квартир, и в Подмосковье это
    работает так же, как в Москве, — потому что норматив здесь не применяется
    вовсе.

    Отсюда и граница ответа: пропорция масштабирует то, что УЖЕ стоит в модели.
    Нечего масштабировать — это отказ, а не ноль: пустая соцнагрузка и
    соцнагрузка, уменьшенная до нуля, значат разное.
    """
    before = max(0.0, float(req.apartment_area_before_sqm or 0.0))
    after = max(0.0, float(req.apartment_area_after_sqm or 0.0))
    if before <= 0:
        raise HTTPException(
            status_code=422,
            detail=("Не от чего считать пропорцию: неизвестна площадь квартир, "
                    "под которую посчитана нынешняя соцнагрузка."))
    known = [value for value in (req.kindergarten_places, req.school_places,
                                 req.clinic_capacity, req.social_compensation_mln,
                                 req.underground_manual_spaces)
             if float(value or 0.0) > 0]
    if not known:
        raise HTTPException(
            status_code=422,
            detail=("Масштабировать нечего: соцнагрузка и машино-места в модели "
                    "не заданы. Пустая нагрузка и уменьшенная до нуля — разное."))
    factor = after / before
    # Места целые и всегда вверх: половина места не строится, а норматив
    # округляется в большую сторону.
    def places(value: Any) -> int:
        return int(math.ceil(float(value or 0.0) * factor - 1e-9))

    nonres_before = max(0.0, float(req.nonresidential_before_sqm or 0.0))
    nonres_after = max(0.0, float(req.nonresidential_after_sqm or 0.0))
    warnings: list[str] = []
    if nonres_before > 0 and abs(nonres_after - nonres_before) > 1.0:
        warnings.append(
            "Нежилая площадь тоже изменилась, а приобъектные машино-места "
            "считаются от неё своим коэффициентом района — их пропорция не "
            "трогает.")
    return {
        "factor": round(factor, 6),
        "places": {
            "kindergarten": places(req.kindergarten_places),
            "school": places(req.school_places),
            "clinic": places(req.clinic_capacity),
        },
        # Компенсация — ставка за место × места: ставка задана экспертно и от
        # метража не зависит, поэтому компенсация идёт тем же коэффициентом.
        "compensation_mln": round(float(req.social_compensation_mln or 0.0) * factor, 3),
        "underground_manual_spaces": places(req.underground_manual_spaces),
        "basis": [
            f"пропорция по населению: площадь квартир {_telegram_number(before, 0)} → "
            f"{_telegram_number(after, 0)} м², коэффициент "
            + f"{factor:.4f}".replace(".", ","),
            "население — 33 м² квартир на человека, места — линейно от населения",
            "компенсация — ставка за место задана экспертно и от метража не зависит",
            ("прежние значения: " + (req.basis or "введены в модель")),
        ],
        "warnings": warnings,
    }


class TepBySiteRequest(BaseModel):
    """Пересчёт под фактический ТЭП, когда выгрузки ГлавАПУ нет.

    Район и признак Москвы приходят из разбора участка (`/cadastral/analyze`) —
    своего справочника территорий здесь не заводится.
    """
    apartment_area_sqm: float = 0.0
    residential_living_spp_sqm: float = 0.0
    nonresidential_np_sqm: float = 0.0
    district: str = ""
    inside_moscow: bool = True
    sqm_per_job: float = 32.0
    parking_norm_regime: str = "2118_2026"
    apartment_count: float = 0.0
    social_population_method: str = "rngp_area"


@app.post("/tep/derived-by-site")
def tep_derived_by_site(req: TepBySiteRequest) -> dict[str, Any]:
    """Что следует из ТЭП, когда исходного расчёта ГлавАПУ нет.

    Правка ТЭП не пересчитывала ничего без выгрузки: «пишется ошибка и
    упоминание про отсутствие расчёта ГлавАПУ» (владелец, 29.08.2026). При этом
    расчёт своими формулами был написан и не звался никем.

    Считается то, для чего у нас есть все основания, и НЕ считается то, для чего
    их нет. Каждый ответ подписан своим основанием, каждый отказ — своей
    причиной: молча выданный ноль неотличим от посчитанного нуля.

    Чего здесь нет намеренно:
    * **машино-места** — нужен К2 по району (приложение 3 к 945-ПП, 132 строки).
      Своего справочника районов не заводим (решение владельца, 24.08.2026):
      К1 и К2 только СНИЖАЮТ потребность, и единица «пока не знаем» отдала бы
      максимум, выданный за норматив;
    * **денежная соцкомпенсация** — нужен УПКС кадастрового квартала. Наш
      справочник кварталов областной (50:*), по Москве в нём семнадцать строк из
      тридцати тысяч — то есть его нет;
    * **плата за ВРИ** — считается своей кнопкой (`/vri/manual`) по базовым
      стоимостям типов использования.
    """
    if not req.inside_moscow:
        raise HTTPException(
            status_code=422,
            detail=("Участок вне Москвы: московские нормативы соцобеспеченности "
                    "к нему не применяются, а нормативы области у нас не сведены "
                    "(открытые вопросы G7 и G8 в справочнике РНГП). Считать "
                    "по московским значило бы выдать чужой норматив за областной."))
    district = str(req.district or "").strip()
    zone_two = district_zone_two(district)
    # Арифметика одна на оба пути: пересчёт по выгрузке и этот зовут одну и ту
    # же функцию. Второй счёт тех же метров однажды разошёлся бы с первым.
    got = tep_derived_norms(
        apartment_area_sqm=req.apartment_area_sqm,
        residential_living_spp_sqm=req.residential_living_spp_sqm,
        nonresidential_np_sqm=req.nonresidential_np_sqm,
        k1=1.0, k2=1.0, zone_two=zone_two, upks_rub=0.0,
        sqm_per_job=req.sqm_per_job,
        parking_norm_regime=req.parking_norm_regime,
        apartment_count=req.apartment_count,
        social_population_method=req.social_population_method)
    basis = [
        "население соцобъектов — " + str(got.get("social_population_basis") or ""),
        f"нормативы мест — зона {'2' if zone_two else '1'}"
        + (f" по району «{district}»" if district else " (район не назван)"),
        str(got.get("parking_basis") or ""),
        "гостевые машино-места — десятая часть постоянных",
        "места приложения труда — нежилая наземная площадь на "
        f"{_telegram_number(req.sqm_per_job, 0)} м² на место",
    ]
    warnings = list(got.get("missing") or [])
    if not district:
        warnings.append(
            "Район участка не определён — нормативы взяты по первой зоне. "
            "Во второй зоне ДОО 63 и школа 124 места на тысячу вместо 44 и 90.")
    return {
        "source": "формулы DevelopAid по нормативам Москвы, без выгрузки ГлавАПУ",
        "district": district,
        "zone_two": zone_two,
        "population": got.get("population"),
        "social_population": got.get("social_population"),
        "social_population_basis": got.get("social_population_basis"),
        # Жители по каждому способу на тех же метрах: переключатель способа
        # ведёт за ними компенсацию, когда ставки за место у этого пути нет.
        "social_population_by_method": {
            method: moscow_social_population(req.apartment_area_sqm, req.apartment_count,
                                             method)[0]
            for method in SOCIAL_POPULATION_METHODS},
        "apartment_units": got.get("apartment_units"),
        "places": {
            "kindergarten": got.get("kindergarten_places"),
            "school": got.get("school_places"),
            "clinic": got.get("clinic_capacity"),
        },
        # Постоянные и гостевые места коэффициентов района не требуют:
        # постоянные считаются от площади квартир (п. 1 приложения 5 к 945-ПП),
        # гостевые — десятая часть постоянных. Приобъектные требуют К1 и К2, и
        # они — единственное, чего здесь нет.
        "parking": {
            "permanent": got.get("parking_permanent"),
            "guest": got.get("parking_guest"),
            "underground": int(got.get("parking_permanent") or 0)
            + int(got.get("parking_guest") or 0),
        },
        "jobs": got.get("jobs"),
        "basis": [line for line in basis if line],
        "warnings": warnings,
        "refused": [
            {"name": "Приобъектные машино-места",
             "reason": "нужны К1 и К2 по району (приложение 3 к 945-ПП) — своего "
                       "справочника районов не заводим: коэффициенты только снижают "
                       "потребность, и единица отдала бы максимум за норматив"},
            {"name": "Денежная соцкомпенсация",
             "reason": "нужен УПКС кадастрового квартала: наш справочник кварталов "
                       "областной, по Москве в нём почти ничего"},
            {"name": "Плата за смену ВРИ",
             "reason": "считается своей кнопкой «Плата за ВРИ — свой расчёт»"},
        ],
    }


# Приписки, которые стоят под ЛЮБЫМ ответом поиска: они про источник данных, а
# не про эту находку. Отделены затем, чтобы «почему не нашлось» бралось из
# названной причины, а не из первой строки списка.
_LAND_LOOKUP_STANDING_NOTES = (
    "Сведения справочные, из открытых данных ЕГРН. "
    "Для сделки нужна актуальная выписка Росреестра.",
    "На внешние сервисы передаётся только строка поиска; финансовая модель не передаётся.",
)


class LandContourObjectsRequest(BaseModel):
    # Контур площадки КРТ — кольца в веб-меркаторе, как их отдаёт
    # `_krt_site_finder` (файл карты реестра или участки перечня решения).
    rings_merc: list[list[list[float]]] = []


def _nspd_layer_in_bounds(layer_id: int,
                          bounds: tuple[float, float, float, float]) -> list[dict[str, Any]]:
    """Объекты слоя НСПД, задевающие рамку, — нормализованные, как карточка ЕГРН.

    Тот же GetFeatureInfo рамкой, которым скрининг спрашивает зоны по контуру
    участка (`_nspd_getfeatureinfo(bounds=...)`), с тем же предохранителем.
    Бросает HTTPException: неответ портала — не пустая рамка.
    """
    payload = _nspd_getfeatureinfo(0.0, 0.0, int(layer_id), bounds=tuple(bounds))
    return [_normalize_nspd_feature(feature) for feature in _nspd_features(payload)]


def _land_contour_objects(rings_merc: list[list[list[float]]]) -> dict[str, Any]:
    """ОКС и ЗУ в контуре КРТ по карте НСПД. С Render — на ядро, как `/land/lookup`.

    Сетку рамок, дробление упёршихся в потолок ответа и долю в контуре держит
    `auction_search.krt_contour_objects.collect`; здесь только доступ к НСПД.
    """
    url = _core_api_url("/land/contour-objects")
    if url:
        return _core_post(url, {"rings_merc": rings_merc}, _MO_CALC_TIMEOUT_SECONDS)
    from auction_search import krt_contour_objects

    return krt_contour_objects.collect(rings_merc, _nspd_layer_in_bounds)


@app.post("/land/contour-objects", include_in_schema=False)
def land_contour_objects(req: LandContourObjectsRequest) -> dict[str, Any]:
    """Объекты в контуре площадки — ответ ядра для Render. Долго: зовётся фоном."""
    return _land_contour_objects(list(req.rings_merc or []))


@app.post("/land/lookup")
def land_lookup(req: LandLookupRequest) -> dict[str, Any]:
    """Сведения ЕГРН по кадастровому номеру, адресу или координатам — по всей России."""
    usage_track("land", surface="site", text=str(getattr(req, "query", "") or "")[:120],
                chat_id=_web_identity_chat_id(str(getattr(req, "session", "") or "")))
    # Интерфейс модели открыт браузером у этого же сервера и зовёт этот метод
    # относительной ссылкой. Если до НСПД отсюда не достучаться, отвечать надо
    # не ошибкой, а запросом к серверу, который достучаться может.
    if _core_api_url("/land/lookup"):
        return _core_post(
            _core_api_url("/land/lookup"),
            _core_forward_payload(req),
            _MO_CALC_TIMEOUT_SECONDS,
        )
    query = _land_text(req.query)
    if not query:
        raise HTTPException(status_code=400, detail="Введите кадастровый номер или адрес участка.")
    if len(query) > 500:
        raise HTTPException(status_code=400, detail="Слишком длинный запрос: не более 500 символов.")
    try:
        limit = int(req.limit or 30)
    except (TypeError, ValueError):
        limit = 30
    limit = max(1, min(limit, _LAND_LOOKUP_MAX_RESULTS))

    warnings: list[str] = []
    hidden: dict[str, int] = {}
    # По кадастровому номеру отдаём ровно то, что спросили: если запрошена
    # квартира, прятать её нельзя. По адресу и точке оставляем только
    # земельные участки — всё остальное по адресу это сотни записей.
    only_land = not bool(getattr(req, "include_premises", False))
    numbers: list[str] = []
    seen: set[str] = set()
    for number in _CADASTRAL_NUMBER_RE.findall(query.replace("：", ":")):
        if number not in seen:
            seen.add(number)
            numbers.append(number)

    if numbers:
        mode = "cadastral"
        if len(numbers) > limit:
            warnings.append(
                f"В запросе {len(numbers)} номеров, показаны первые {limit}. "
                "Увеличьте лимит или ищите частями."
            )
        results = _land_lookup_by_numbers(numbers[:limit])
        only_land = False
    else:
        coordinates = _COORDINATE_QUERY_RE.match(query)
        if coordinates:
            mode = "point"
            lat = _land_float(coordinates.group(1))
            lng = _land_float(coordinates.group(2))
            if lat is None or lng is None or abs(lat) > 90 or abs(lng) > 180:
                raise HTTPException(status_code=400, detail="Некорректные координаты: ожидается «широта, долгота».")
            results, hidden_here = _land_lookup_features_to_results(
                _nspd_point_features(lat, lng), limit, only_land=only_land
            )
            for kind, count in hidden_here.items():
                hidden[kind] = hidden.get(kind, 0) + count
            if not results:
                warnings.append("В указанной точке участок ЕГРН не найден.")
        else:
            mode = "address"
            try:
                features = _nspd_search_features(query)
            except HTTPException as exc:
                features = []
                warnings.append(str(exc.detail))
            results, hidden_here = _land_lookup_features_to_results(
                features, limit, only_land=only_land
            )
            for kind, count in hidden_here.items():
                hidden[kind] = hidden.get(kind, 0) + count
            # По городскому адресу портал отдаёт дом и его квартиры, а участка
            # среди них нет: всё скрывалось фильтром, и человек видел «ничего не
            # найдено» при двух десятках найденных объектов. Найденное — само по
            # себе дорога к участку, и выбрасывать его, чтобы начать заново с
            # внешнего геокодера, незачем.
            neighbours: list[dict[str, Any]] = []
            if not results and features:
                neighbours, _ = _land_lookup_features_to_results(features, limit, only_land=False)
                # Короткий путь: карточка ОКС иногда несёт номер своего участка.
                parcels_by_card: list[str] = []
                for item in neighbours:
                    number = _land_text(item.get("land_parcel"))
                    if number and number not in parcels_by_card:
                        parcels_by_card.append(number)
                if parcels_by_card:
                    results = [item for item in _land_lookup_by_numbers(parcels_by_card[:limit])
                               if item.get("found")]
                # Иначе — участок под найденным домом, по его собственным
                # координатам: они точнее любого геокодера, дом уже найден.
                if not results:
                    for item in neighbours:
                        center = item.get("center") or {}
                        if not center.get("lat"):
                            continue
                        under, hidden_under = _land_lookup_features_to_results(
                            _nspd_point_features(center["lat"], center["lng"]), limit,
                            only_land=True,
                        )
                        for kind, count in hidden_under.items():
                            hidden[kind] = hidden.get(kind, 0) + count
                        if under:
                            for found_item in under:
                                found_item["matched_address"] = item.get("address", "")
                                found_item["found_under"] = item.get("cadastral_number", "")
                            results = under
                            break
            if not results:
                candidates, geocoder_warnings = _geocode_address(query, 3)
                warnings.extend(geocoder_warnings)
                named = _query_region(query)
                region_codes = named[2] if named else ()
                strangers: list[str] = []
                # «Адрес не распознан» рядом с двумя десятками найденных по
                # нему объектов — противоречие: не распознан не адрес, а участок.
                if not candidates and not neighbours:
                    warnings.append(
                        "Адрес не распознан. Уточните формулировку или введите кадастровый номер."
                    )
                for candidate in candidates:
                    if candidate.get("cadastral_number"):
                        found = _land_lookup_by_numbers([candidate["cadastral_number"]])
                    else:
                        found, hidden_here = _land_lookup_features_to_results(
                            _nspd_point_features(candidate["lat"], candidate["lng"]), limit,
                            only_land=only_land,
                        )
                        for kind, count in hidden_here.items():
                            hidden[kind] = hidden.get(kind, 0) + count
                    for item in found:
                        item["matched_address"] = candidate.get("label", "")
                        item["geocoder"] = candidate.get("provider", "")
                        # Ближайшая станция едет с находкой: из неё считается К1
                        # приложения 6, а без него норма берёт верхний край.
                        # Ставит её только подсказка адреса — по кадастровому
                        # номеру этого пути нет, и делать вид, что есть, нельзя.
                        if candidate.get("metro"):
                            item["metro"] = candidate["metro"]
                    # Регион участка написан первыми цифрами его номера. Запрос
                    # назвал регион — значит участок из другого не он, а на
                    # экране он выглядел бы обычной находкой.
                    if region_codes:
                        kept = [item for item in found
                                if _same_region(item.get("cadastral_number"), region_codes)]
                        strangers.extend(str(item.get("cadastral_number") or "—")
                                         for item in found if item not in kept)
                        found = kept
                    results.extend(found)
                    if len(results) >= limit:
                        break
                results = results[:limit]
                if strangers:
                    # Отсечённое называется: молча выброшенная находка читается
                    # как её отсутствие.
                    warnings.append(
                        "Не показаны участки другого региона: "
                        + ", ".join(dict.fromkeys(strangers))
                        + ". В запросе назван "
                        + (named[0] if named else "регион") + ".")
                if candidates and not results:
                    warnings.append(
                        "Адрес найден, но участок ЕГРН в этой точке не определён — "
                        "проверьте объект на публичной карте."
                    )
                # Участок не дался ни одним путём — но объекты по адресу есть.
                # «Ничего не найдено» при двух десятках найденных объектов —
                # неправда, из которой не видно следующего шага. Отдаём их и
                # называем вещи своими именами.
                if not results and neighbours:
                    results = neighbours[:limit]
                    hidden = {}
                    warnings.append(
                        "Земельный участок по этому адресу ЕГРН не отдал. Показаны найденные "
                        "объекты — дом и помещения: посмотрите участок под нужным на публичной "
                        "карте и введите его кадастровый номер."
                    )

    hidden_total = sum(hidden.values())
    if hidden_total:
        parts = ", ".join(
            f"{_LAND_KIND_LABELS.get(kind, kind).lower()} — {count}"
            for kind, count in sorted(hidden.items(), key=lambda pair: -pair[1])
        )
        warnings.append(
            f"Показаны только земельные участки. Скрыто объектов: {hidden_total} ({parts}). "
            "Для расчёта проекта нужен участок; чтобы увидеть конкретный объект, "
            "введите его кадастровый номер."
        )
    warnings.extend(_LAND_LOOKUP_STANDING_NOTES)
    # Почему не нашлось. По адресу причина попадает в предупреждения, по
    # кадастровому номеру — в примечание самой строки: у номера свой ответ на
    # каждый, и один общий список их бы слил. Читателю нужна одна фраза, и
    # берётся она оттуда, где лежит, а не выбирается по подстроке.
    reason = next((note for note in warnings if note not in _LAND_LOOKUP_STANDING_NOTES), "")
    if not reason:
        reason = next((str(item.get("note") or "") for item in results
                       if not item.get("found") and item.get("note")), "")
    return {
        "mode": mode,
        "query": query,
        "hidden": hidden,
        "hidden_count": hidden_total,
        "results": results,
        "found_count": len([item for item in results if item.get("found")]),
        "warnings": warnings,
        "reason": reason,
        # Основание платы за смену ВРИ, если участок уже 2.6, — готовой
        # строкой: страница её показывает, а не решает сама.
        "vri_fee_basis": vri_fee_basis_text(
            [str(item.get("permitted_use") or "") for item in results
             if item.get("found") and item.get("kind") == "land"]),
        "source": {
            "service": "nspd.gov.ru (НСПД, ППК «Роскадастр»)",
            "requested_at": date.today().isoformat(),
        },
    }


def _land_lot_context(numbers: list[str], session: str = "") -> dict[str, Any]:
    """Разделяет КН объекта торгов и участок под ОКС.

    Это не второй поиск Росреестра: все сведения берутся через `land_lookup`.
    Поэтому край приложения автоматически пользуется тем же удалённым ядром,
    кэшем и нормализацией НСПД, что кабинет и расчёт территории.
    """
    requested = _parse_cadastral_numbers(numbers)

    def lookup(query: str, *, include_premises: bool) -> list[dict[str, Any]]:
        payload = land_lookup(LandLookupRequest(
            query=query,
            limit=30,
            include_premises=include_premises,
            session=session,
        ))
        return [dict(item) for item in payload.get("results", []) if isinstance(item, dict)]

    objects = lookup("\n".join(requested), include_premises=True)
    buildings = [dict(item) for item in objects if item.get("found") and item.get("kind") == "building"]
    other_objects = [
        dict(item) for item in objects
        if item.get("kind") not in ("land", "building") or not item.get("found")
    ]
    parcels: dict[str, dict[str, Any]] = {}

    def add_parcel(item: dict[str, Any], method: str, building_number: str = "") -> None:
        if not item.get("found") or item.get("kind") != "land":
            return
        number = _land_text(item.get("cadastral_number"))
        if not number:
            return
        current = parcels.get(number)
        if current is None:
            current = dict(item)
            current["lookup_methods"] = []
            current["related_buildings"] = []
            parcels[number] = current
        if method not in current["lookup_methods"]:
            current["lookup_methods"].append(method)
        if building_number and building_number not in current["related_buildings"]:
            current["related_buildings"].append(building_number)

    # Если КН лота уже является участком, его площадь подтверждается напрямую.
    for item in objects:
        add_parcel(item, "requested")

    relation_numbers: list[str] = []
    relations_by_building: dict[str, list[str]] = {}
    for building in buildings:
        building_number = _land_text(building.get("cadastral_number"))
        relation = _land_text(building.get("land_parcel"))
        found_numbers = [] if not relation else _CADASTRAL_NUMBER_RE.findall(relation.replace("：", ":"))
        found_numbers = list(dict.fromkeys(found_numbers))
        relations_by_building[building_number] = found_numbers
        for number in found_numbers:
            if number not in relation_numbers:
                relation_numbers.append(number)

    relation_results: dict[str, dict[str, Any]] = {}
    if relation_numbers:
        for item in lookup("\n".join(relation_numbers), include_premises=False):
            number = _land_text(item.get("cadastral_number"))
            if number:
                relation_results[number] = item

    warnings: list[str] = []
    for building in buildings:
        building_number = _land_text(building.get("cadastral_number"))
        site_numbers: list[str] = []
        for number in relations_by_building.get(building_number, []):
            parcel = relation_results.get(number)
            if parcel and parcel.get("kind") == "land" and parcel.get("found"):
                add_parcel(parcel, "egrn_relation", building_number)
                site_numbers.append(number)

        method = "egrn_relation" if site_numbers else ""
        # Не у каждого ОКС в публичной карточке есть ссылка на землю. Тогда
        # проверяем земельный слой в центре контура здания. Это полезная
        # пространственная проверка, но не замена выписке и межевому плану.
        if not site_numbers:
            center = building.get("center") or {}
            lat, lng = _land_float(center.get("lat")), _land_float(center.get("lng"))
            if lat is not None and lng is not None:
                try:
                    under = lookup(f"{lat}, {lng}", include_premises=False)
                except HTTPException as exc:
                    under = []
                    warnings.append(
                        f"Участок под ОКС {building_number} не проверен: {exc.detail}"
                    )
                for parcel in under:
                    if parcel.get("found") and parcel.get("kind") == "land":
                        add_parcel(parcel, "building_center", building_number)
                        number = _land_text(parcel.get("cadastral_number"))
                        if number and number not in site_numbers:
                            site_numbers.append(number)
                if site_numbers:
                    method = "building_center"
            if not site_numbers:
                warnings.append(
                    f"НСПД не определила земельный участок под ОКС {building_number}."
                )
        building["site_lookup_method"] = method or "not_found"
        building["site_cadastral_numbers"] = site_numbers

    for item in other_objects:
        number = _land_text(item.get("cadastral_number"))
        if not item.get("found"):
            warnings.append(
                f"Кадастровый номер {number or 'из карточки'} не найден в открытых сведениях ЕГРН."
            )
        elif item.get("kind") == "premise":
            warnings.append(
                f"{number} — помещение, а не ОСЗ; по одному КН помещения участок под домом не определяется."
            )

    if any("building_center" in item.get("lookup_methods", []) for item in parcels.values()):
        warnings.append(
            "Участок под ОКС найден по центральной точке здания. Для сделки проверьте связь объектов по выпискам ЕГРН."
        )
    warnings.append(
        "Площади справочные, из открытых данных ЕГРН; для сделки нужна актуальная выписка Росреестра."
    )
    return {
        "requested": requested,
        "objects": objects,
        "buildings": buildings,
        "land_parcels": list(parcels.values()),
        "other_objects": other_objects,
        "warnings": list(dict.fromkeys(warnings)),
        "source": {
            "service": "nspd.gov.ru (НСПД, ППК «Роскадастр»)",
            "requested_at": date.today().isoformat(),
        },
    }


@app.post("/land/lot-context")
def land_lot_context(req: LandLotContextRequest) -> dict[str, Any]:
    """Площадь участка лота и, для ОКС, участка под зданием."""
    usage_track(
        "land_lot_context",
        surface="auctions",
        text=" ".join(str(item) for item in req.cadastral_numbers)[:120],
        chat_id=_web_identity_chat_id(str(getattr(req, "session", "") or "")),
    )
    return _land_lot_context(req.cadastral_numbers, req.session)


@app.get("/land/providers")
def land_lookup_providers() -> dict[str, Any]:
    """Диагностика: какие внешние источники подключены на этом стенде."""
    return {
        "nspd_base_url": _NSPD_BASE_URL,
        "geocoders": {
            "yandex": bool(_env_str("YANDEX_GEOCODER_API_KEY")),
            "dadata": bool(_env_str("DADATA_API_KEY")),
            "nominatim": True,
        },
        "forced_geocoder": _env_str("LAND_LOOKUP_GEOCODER") or None,
        "cache_ttl_seconds": _LAND_LOOKUP_CACHE_TTL_SECONDS,
        "nspd_tls": {
            "fallback_allowed": _NSPD_TLS_FALLBACK,
            # true — цепочка сертификатов НСПД на этом хосте не проверилась и
            # запросы идут без проверки. Лечится установкой корневого
            # сертификата Минцифры.
            "verification_disabled": _nspd_tls_insecure,
        },
    }
