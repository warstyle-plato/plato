"""«Пульс Продаж Новостроек» — источник, знающий то, что мы добывали угадыванием.

Весь прежний конвейер рынка отвечал на вопросы, которые здесь просто даны:
как называется проект, где он стоит, какого он класса, сколько стоит метр и
сколько лотов осталось. Мы вытаскивали это из поисковых сниппетов — по
заголовку, по обрывку текста, по совпадению названия, — и каждая сборка
приносила новый вид мусора: чужой адрес, цену соседа, статью вместо проекта.

Здесь у каждого проекта есть числовой идентификатор, координаты, строительный
адрес, девелопер и класс, а цена приходит с датой прайса и числом лотов, из
которых она посчитана. Угадывать больше нечего.

Правила, которым модуль обязан подчиняться:

* **Худший исход совпадает с прежним поведением.** Не заданы доступы, не
  открылся сайт, истекла сессия — методы возвращают пустоту, а не исключение.
  Источник дополняет конвейер, а не заменяет его собой на живом стенде.
* **Доступ живёт в окружении.** `PULSE_LOGIN` и `PULSE_PASSWORD` читаются из
  среды; в репозитории их нет и быть не может.
* **Воркеров два, память у них раздельная.** Куки и справочник лежат на диске,
  иначе каждый запрос заходил бы на сайт заново.
"""

from __future__ import annotations

import http.cookiejar
import json
import math
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .http import fresh, load_json, save_json


PULSE_BASE = "https://pulsprodaj.ru"

_LOGIN_PATH = "/accounts/login/"
_MAP_PATH = "/map/"
_SEARCH_PATH = "/api/search/"

# Класс проекта не лежит ни в точке карты, ни в карточке: он живёт фильтром.
# Спрашиваем выборку по каждому классу и получаем принадлежность из того, что
# в неё попало. Пять запросов в сутки против справочника, который пришлось бы
# обновлять руками вместе с книгой.
_CLASS_FILTERS = {
    1: "Стандарт/Эконом",
    2: "Комфорт",
    3: "Бизнес",
    4: "Премиум",
    5: "Элит/De Luxe",
}

_LZ_KEY64 = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/="
_CSRF_RE = re.compile(r"csrfmiddlewaretoken['\"]?\s+value=['\"]([^'\"]+)")
_GEOJSON_MARK = '{"type":"FeatureCollection"'


@dataclass(frozen=True)
class PulseProject:
    """Проект справочника: идентификатор, место и вывеска."""

    complex_id: int
    name: str
    latitude: float
    longitude: float
    developer: str | None = None
    builder: str | None = None
    address: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "complex_id": self.complex_id,
            "name": self.name,
            "latitude": self.latitude,
            "longitude": self.longitude,
            "developer": self.developer,
            "builder": self.builder,
            "address": self.address,
            "url": f"{PULSE_BASE}/complex/{self.complex_id}/",
        }


def _distance_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    radius = 6371.0088
    rad = math.radians
    return 2 * radius * math.asin(
        math.sqrt(
            math.sin(rad(lat2 - lat1) / 2) ** 2
            + math.cos(rad(lat1)) * math.cos(rad(lat2)) * math.sin(rad(lon2 - lon1) / 2) ** 2
        )
    )


def _balanced_json(text: str, start: int) -> str:
    """Вырезать JSON-объект от `{` до его пары.

    Регулярным выражением это не берётся: внутри вложенные скобки и кавычки, а
    объект тянется на два мегабайта. Считать одни скобки тоже мало — скобка
    может стоять внутри строки, и тогда разбор оборвётся на середине данных.
    """
    depth = 0
    in_string = False
    escaped = False
    for index in range(start, len(text)):
        char = text[index]
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return text[start : index + 1]
    raise ValueError("незакрытый JSON в странице карты")


def lz_decompress_base64(text: str) -> str | None:
    """Разжать ответ карты: он приходит сжатым LZ-string в base64.

    Библиотеку для этого ставить незачем — алгоритм короткий и неизменный, а
    лишняя зависимость в образе живёт дольше, чем причина, по которой её взяли.
    """
    if not text:
        return "" if text == "" else None
    lookup = {char: index for index, char in enumerate(_LZ_KEY64)}
    try:
        return _lz_decompress(len(text), 32, lambda i: lookup[text[i]])
    except (KeyError, IndexError, ValueError):
        return None


def _lz_decompress(length: int, reset: int, get) -> str | None:
    dictionary: dict[int, str | int] = {index: index for index in range(3)}
    enlarge, size, bits_n = 4, 4, 3
    out: list[str] = []
    state = {"val": get(0), "pos": reset, "index": 1}

    def read(count: int) -> int:
        bits, power, maxpower = 0, 1, 1 << count
        while power != maxpower:
            resb = state["val"] & state["pos"]
            state["pos"] >>= 1
            if state["pos"] == 0:
                state["pos"] = reset
                state["val"] = get(state["index"])
                state["index"] += 1
            bits |= (1 if resb > 0 else 0) * power
            power <<= 1
        return bits

    first = read(2)
    if first == 2:
        return ""
    current = chr(read(8 if first == 0 else 16))
    dictionary[3] = current
    word = current
    out.append(current)

    while True:
        if state["index"] > length:
            return ""
        code = read(bits_n)
        if code in (0, 1):
            dictionary[size] = chr(read(8 if code == 0 else 16))
            size += 1
            code = size - 1
            enlarge -= 1
        elif code == 2:
            return "".join(out)

        if enlarge == 0:
            enlarge = 1 << bits_n
            bits_n += 1

        if code in dictionary:
            entry = dictionary[code]
        elif code == size:
            entry = word + word[0]
        else:
            return None

        out.append(str(entry))
        dictionary[size] = word + str(entry)[0]
        size += 1
        enlarge -= 1
        word = str(entry)
        if enlarge == 0:
            enlarge = 1 << bits_n
            bits_n += 1


class PulseClient:
    """Клиент с сессией на диске и молчаливым отказом."""

    def __init__(
        self,
        data_dir: Path,
        *,
        login: str | None = None,
        password: str | None = None,
        base: str | None = None,
        timeout: float = 30.0,
        ttl_seconds: int = 86_400,
        detail_ttl_seconds: int = 43_200,
    ):
        self.base = (base or os.getenv("PULSE_BASE_URL") or PULSE_BASE).rstrip("/")
        self.login = login if login is not None else os.getenv("PULSE_LOGIN", "")
        self.password = password if password is not None else os.getenv("PULSE_PASSWORD", "")
        self.timeout = timeout
        self.ttl_seconds = ttl_seconds
        self.detail_ttl_seconds = detail_ttl_seconds
        self.dir = Path(data_dir)
        self.dir.mkdir(parents=True, exist_ok=True)
        self.errors: list[str] = []
        self._jar: http.cookiejar.MozillaCookieJar | None = None
        self._opener: urllib.request.OpenerDirector | None = None
        self._projects: list[PulseProject] | None = None

    @property
    def available(self) -> bool:
        """Заданы ли доступы. Их отсутствие — не поломка, а выключенный источник."""
        return bool(self.login and self.password)

    # --- сеть -----------------------------------------------------------------

    def _build_opener(self) -> urllib.request.OpenerDirector:
        if self._opener is not None:
            return self._opener
        jar = http.cookiejar.MozillaCookieJar(str(self.dir / "cookies.txt"))
        try:
            jar.load(ignore_discard=True, ignore_expires=True)
        except (OSError, http.cookiejar.LoadError):
            pass
        self._jar = jar
        self._opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
        self._opener.addheaders = [
            ("User-Agent", os.getenv("MARKET_HTTP_USER_AGENT", "DevelopAid/1.0")),
            ("Accept-Language", "ru-RU,ru;q=0.9"),
        ]
        return self._opener

    def _save_cookies(self) -> None:
        if self._jar is None:
            return
        try:
            self._jar.save(ignore_discard=True, ignore_expires=True)
        except OSError:
            pass

    def _cookie(self, name: str) -> str | None:
        for cookie in self._jar or []:
            if cookie.name == name:
                return cookie.value
        return None

    def _open(
        self,
        path: str,
        *,
        data: bytes | None = None,
        headers: dict[str, str] | None = None,
    ) -> bytes:
        url = path if path.startswith("http") else f"{self.base}{path}"
        request = urllib.request.Request(url, data=data, headers=headers or {})
        with self._build_opener().open(request, timeout=self.timeout) as response:
            body = response.read()
        self._save_cookies()
        return body

    def sign_in(self) -> bool:
        """Войти под доступами из окружения. Возвращает успех, не бросает."""
        if not self.available:
            return False
        try:
            page = self._open(_LOGIN_PATH).decode("utf-8", errors="ignore")
            match = _CSRF_RE.search(page)
            if not match:
                self.errors.append("на странице входа нет CSRF-токена")
                return False
            payload = urllib.parse.urlencode(
                {
                    "csrfmiddlewaretoken": match.group(1),
                    "username": self.login,
                    "password": self.password,
                }
            ).encode("utf-8")
            self._open(
                _LOGIN_PATH,
                data=payload,
                headers={
                    "Content-Type": "application/x-www-form-urlencoded",
                    "Referer": f"{self.base}{_LOGIN_PATH}",
                },
            )
        except (urllib.error.URLError, OSError, ValueError) as exc:
            self.errors.append(f"вход не удался: {exc}")
            return False
        # Признак входа — кука сессии. Страница после неудачи возвращается та же,
        # с кодом 200, поэтому по коду ответа судить нельзя.
        return bool(self._cookie("sessionid"))

    def _post_json(self, path: str, payload: dict[str, Any]) -> Any:
        """POST в API. Один повтор после повторного входа: сессия истекает."""
        for attempt in (1, 2):
            csrf = self._cookie("csrftoken")
            if not csrf and not self.sign_in():
                return None
            csrf = self._cookie("csrftoken") or ""
            try:
                body = self._open(
                    path,
                    data=json.dumps(payload).encode("utf-8"),
                    headers={
                        "Content-Type": "application/json",
                        "X-CSRFToken": csrf,
                        "Referer": f"{self.base}/",
                    },
                )
            except (urllib.error.URLError, OSError) as exc:
                self.errors.append(f"{path}: {exc}")
                return None
            try:
                return json.loads(body.decode("utf-8", errors="ignore"))
            except ValueError:
                # Пришла HTML-страница входа вместо JSON — сессия протухла.
                if attempt == 1 and self.sign_in():
                    continue
                self.errors.append(f"{path}: ответ не JSON")
                return None
        return None

    # --- справочник проектов ---------------------------------------------------

    def projects(self, *, refresh: bool = False) -> list[PulseProject]:
        """Все проекты с координатами. Страница карты несёт их одним GeoJSON."""
        if self._projects is not None and not refresh:
            return self._projects
        path = self.dir / "projects.json"
        cached = load_json(path) if (fresh(path, self.ttl_seconds) and not refresh) else None
        if not isinstance(cached, list):
            cached = self._fetch_projects()
            if cached is None:
                return []
            save_json(path, cached)
        self._projects = [
            PulseProject(
                complex_id=int(row["complex_id"]),
                name=str(row.get("name") or "").strip(),
                latitude=float(row["latitude"]),
                longitude=float(row["longitude"]),
                developer=(row.get("developer") or None),
                builder=(row.get("builder") or None),
                address=(row.get("address") or None),
            )
            for row in cached
            if row.get("complex_id") and row.get("latitude") is not None
        ]
        return self._projects

    def _fetch_projects(self) -> list[dict[str, Any]] | None:
        if not self.available and not self._cookie("sessionid"):
            return None
        try:
            page = self._open(_MAP_PATH).decode("utf-8", errors="ignore")
        except (urllib.error.URLError, OSError) as exc:
            self.errors.append(f"карта недоступна: {exc}")
            return None
        index = page.find(_GEOJSON_MARK)
        if index < 0:
            # Не вошли — карта отдаётся и гостю, но без данных.
            if self.sign_in():
                try:
                    page = self._open(_MAP_PATH).decode("utf-8", errors="ignore")
                except (urllib.error.URLError, OSError) as exc:
                    self.errors.append(f"карта недоступна: {exc}")
                    return None
                index = page.find(_GEOJSON_MARK)
            if index < 0:
                self.errors.append("на странице карты нет данных проектов")
                return None
        try:
            collection = json.loads(_balanced_json(page, page.index("{", index)))
        except ValueError as exc:
            self.errors.append(f"данные карты не разобрались: {exc}")
            return None

        out: list[dict[str, Any]] = []
        for feature in collection.get("features") or []:
            coords = (feature.get("geometry") or {}).get("coordinates") or []
            props = feature.get("properties") or {}
            if len(coords) != 2 or feature.get("id") is None:
                continue
            out.append(
                {
                    "complex_id": feature["id"],
                    "name": str(props.get("name") or "").strip(),
                    "latitude": coords[0],
                    "longitude": coords[1],
                    "developer": (props.get("developer") or "").strip() or None,
                    "builder": (props.get("zastroychik") or "").strip() or None,
                    "address": (props.get("construction_address") or "").strip() or None,
                }
            )
        return out

    def near(self, latitude: float, longitude: float, radius_km: float) -> list[tuple[float, PulseProject]]:
        """Проекты в радиусе, ближние первыми. Расстояние считаем сами."""
        found = [
            (round(_distance_km(latitude, longitude, item.latitude, item.longitude), 3), item)
            for item in self.projects()
        ]
        return sorted((row for row in found if row[0] <= radius_km), key=lambda row: row[0])

    def segments(self, *, refresh: bool = False) -> dict[int, str]:
        """Класс каждого проекта: идентификатор → «Бизнес», «Премиум»…

        Спрашивается пять раз, по разу на класс, и складывается на сутки.
        Класса нет ни в точке карты, ни в карточке проекта — он существует
        только как фильтр, поэтому принадлежность выводится из выборки.
        """
        path = self.dir / "segments.json"
        if not refresh and fresh(path, self.ttl_seconds):
            cached = load_json(path)
            if isinstance(cached, dict):
                return {int(k): str(v) for k, v in cached.items()}

        out: dict[int, str] = {}
        for code, title in _CLASS_FILTERS.items():
            payload = urllib.parse.urlencode(
                {"data": json.dumps({"classes_ppn_list": [code]})}
            ).encode("utf-8")
            csrf = self._cookie("csrftoken")
            if not csrf and not self.sign_in():
                return {}
            try:
                body = self._open(
                    _SEARCH_PATH,
                    data=payload,
                    headers={
                        "Content-Type": "application/x-www-form-urlencoded",
                        "X-CSRFToken": self._cookie("csrftoken") or "",
                        "Referer": f"{self.base}{_MAP_PATH}",
                    },
                )
            except (urllib.error.URLError, OSError) as exc:
                self.errors.append(f"класс «{title}»: {exc}")
                continue
            raw = lz_decompress_base64(body.decode("utf-8", errors="ignore"))
            if not raw:
                self.errors.append(f"класс «{title}»: ответ не разжался")
                continue
            try:
                collection = json.loads(raw)
            except ValueError:
                self.errors.append(f"класс «{title}»: ответ не разобрался")
                continue
            for feature in collection.get("features") or []:
                if feature.get("id") is not None:
                    out[int(feature["id"])] = title

        if out:
            save_json(path, {str(k): v for k, v in out.items()})
        return out

    def find_project(self, query: str) -> dict[str, Any] | None:
        """Проект по строке: название или застройщик.

        Поиск сервиса отдаёт обычный JSON, без сжатия, и возвращает
        идентификатор — с ним из справочника берутся координаты и адрес.
        """
        text = " ".join(str(query or "").split())
        if len(text) < 3:
            return None
        payload = urllib.parse.urlencode({"query": text, "only_owned": "false"}).encode("utf-8")
        csrf = self._cookie("csrftoken")
        if not csrf and not self.sign_in():
            return None
        try:
            body = self._open(
                "/api/searchbyquery/",
                data=payload,
                headers={
                    "Content-Type": "application/x-www-form-urlencoded",
                    "X-CSRFToken": self._cookie("csrftoken") or "",
                    "Referer": f"{self.base}{_MAP_PATH}",
                },
            )
            found = json.loads(body.decode("utf-8", errors="ignore"))
        except (urllib.error.URLError, OSError, ValueError) as exc:
            self.errors.append(f"поиск «{text}»: {exc}")
            return None
        if not isinstance(found, dict):
            return None
        # Совпадения приходят раздельно: по названию и по застройщику. Проект
        # надёжнее имени компании, поэтому имя спрашивается первым.
        for key in ("name", "developer"):
            for row in found.get(key) or []:
                if not isinstance(row, dict) or row.get("id") is None:
                    continue
                project = self.project(int(row["id"]))
                if project:
                    return {
                        **project.to_dict(),
                        "segment": self.segments().get(project.complex_id),
                        "matched_by": key,
                    }
        return None

    def suggest(self, query: str, limit: int = 10) -> list[dict[str, Any]]:
        """Подсказки по названию и адресу — из своего справочника, не по сети.

        Полный список проектов уже лежит рядом, поэтому подсказка не стоит ни
        запроса, ни ожидания: обращение к источнику на каждую букву заметно
        замедлило бы ввод и ничего не добавило.

        Порядок сортировки — не украшение. Совпадение с начала имени вернее
        совпадения в середине, а имя вернее адреса: человек, набравший «кутуз»,
        ищет «Кутузов Сити», а не десяток домов на Кутузовском проспекте.
        """
        text = " ".join(str(query or "").split()).casefold()
        if len(text) < 2:
            return []
        classes = self.segments()
        scored: list[tuple[int, int, dict[str, Any]]] = []
        for project in self.projects():
            name = (project.name or "").casefold()
            address = (project.address or "").casefold()
            if name.startswith(text):
                rank = 0
            elif text in name:
                rank = 1
            elif text in address:
                rank = 2
            else:
                continue
            scored.append((
                rank,
                len(project.name or ""),
                {
                    "complex_id": project.complex_id,
                    "name": project.name,
                    "developer": project.developer,
                    "address": project.address,
                    "segment": classes.get(project.complex_id),
                },
            ))
        scored.sort(key=lambda item: (item[0], item[1]))
        return [row for _, _, row in scored[:limit]]

    def project(self, complex_id: int) -> PulseProject | None:
        """Проект справочника по идентификатору."""
        for item in self.projects():
            if item.complex_id == int(complex_id):
                return item
        return None

    # --- данные проекта --------------------------------------------------------

    def _cached(self, name: str, complex_id: int, build) -> Any:
        """Ответ по проекту на диске: отчёт спрашивает одно и то же по кругу.

        Двадцать соседей — это сорок обращений к сервису; без кэша сборка
        отчёта ждала бы минуту, а повторная — столько же. Срок короче суток:
        прайс меняется чаще, чем справочник проектов.
        """
        path = self.dir / "cache" / f"{name}-{int(complex_id)}.json"
        if fresh(path, self.detail_ttl_seconds):
            cached = load_json(path)
            if cached is not None:
                return cached.get("value") if isinstance(cached, dict) else cached
        value = build()
        path.parent.mkdir(parents=True, exist_ok=True)
        save_json(path, {"value": value})
        return value

    def metrics(self, complex_id: int) -> dict[str, Any]:
        """Всё, что нужно блокам отчёта, одним словарём.

        Поглощение в метрах источник считает сам (`avg_sale_speed_living_area`),
        а средний проданный лот выводится из него и темпа в штуках: делить
        метры на штуки корректно, потому что оба числа посчитаны по одному и
        тому же периоду.
        """
        price = self.price(complex_id) or {}
        sales = self.sales(complex_id) or {}
        units = sales.get("units_per_month")
        area = sales.get("area_per_month")
        return {
            "complex_id": int(complex_id),
            "price_per_sqm": price.get("price_per_sqm"),
            "price_per_sqm_min": price.get("price_per_sqm_min"),
            "price_per_sqm_max": price.get("price_per_sqm_max"),
            "lot_count": price.get("lot_count"),
            "observed_at": price.get("observed_at"),
            "units_per_month": units,
            "units_per_month_3m": sales.get("units_per_month_3m"),
            "area_per_month": area,
            "sales_end_forecast": sales.get("sales_end_forecast"),
            "known_sales_for": sales.get("known_sales_for"),
            "sold_lot_avg": round(area / units, 1) if area and units else None,
        }

    def project_totals(self, complex_id: int) -> dict[str, Any]:
        """ТЭП проекта: сколько всего жилья и какого размера лоты."""
        data = self._cached(
            "table",
            complex_id,
            lambda: self._post_json("/api/app/complex/table/", {"complex_id": int(complex_id)}),
        )
        if not isinstance(data, dict):
            return {}
        return {
            "living_units": _as_int(data.get("living_count")),
            "living_area": data.get("living_area"),
            "buildings": _as_int(data.get("buildings_count")),
            "lot_area_avg": (
                round(float(data["living_lot_area_avg"]), 1)
                if data.get("living_lot_area_avg")
                else None
            ),
        }

    def remaining(self, complex_id: int) -> dict[str, Any]:
        """Непроданный остаток по корпусам, сложенный в проект."""
        columns = ["building", "living_remaining_predict", "living_remaining_area_predict"]
        data = self._cached(
            "remaining",
            complex_id,
            lambda: self._post_json(
                "/api/app/complex/buildings_summary_table/",
                {"complex_id": int(complex_id), "columns": columns},
            ),
        )
        rows = (data or {}).get("rows") if isinstance(data, dict) else None
        if not rows:
            return {}
        units = sum(int(row.get("living_remaining_predict") or 0) for row in rows)
        area = sum(float(row.get("living_remaining_area_predict") or 0) for row in rows)
        return {
            "remaining_units": units or None,
            "remaining_area": round(area) or None,
        }

    def price(self, complex_id: int) -> dict[str, Any] | None:
        """Цена прайс-листа: средняя, границы, число лотов и дата среза."""
        data = self._cached(
            "price",
            complex_id,
            lambda: self._post_json(
                "/api/app/complex/price_stats/", {"complex_id": int(complex_id)}
            ),
        )
        current = (data or {}).get("current_price") if isinstance(data, dict) else None
        if not isinstance(current, dict) or not current.get("flat_sqm_price"):
            return None
        return {
            "price_per_sqm": int(current["flat_sqm_price"]),
            "price_per_sqm_min": _as_int(current.get("flat_sqm_price_min")),
            "price_per_sqm_max": _as_int(current.get("flat_sqm_price_max")),
            "lot_count": _as_int(current.get("flat_lot_count")),
            "lot_area_avg": _as_int(current.get("flat_lot_area")),
            "observed_at": str(current.get("price_date") or "")[:10] or None,
            "source": "Пульс Продаж Новостроек",
            "basis": "pulse_price_list_average",
        }

    def sales(self, complex_id: int) -> dict[str, Any] | None:
        """Темп продаж и прогноз их окончания."""
        data = self._cached(
            "sales",
            complex_id,
            lambda: self._post_json("/api/app/complex/sales/", {"complex_id": int(complex_id)}),
        )
        if not isinstance(data, dict):
            return None
        speed = data.get("avg_sale_speed_living")
        if speed is None:
            return None
        return {
            "units_per_month": speed,
            "units_per_month_3m": data.get("avg_sale_speed_3_months_living"),
            "area_per_month": data.get("avg_sale_speed_living_area"),
            "sales_end_forecast": data.get("sales_end_predict_living"),
            "known_sales_for": data.get("known_sales_for"),
            "source": "Пульс Продаж Новостроек",
            "quality": "provider",
        }

    def exposure(self, complex_id: int) -> list[dict[str, Any]]:
        """Откуда взят прайс: площадка, дата среза, объём предложения."""
        data = self._post_json("/api/app/complex/price_exposure/", {"complex_id": int(complex_id)})
        if not isinstance(data, list):
            return []
        out: list[dict[str, Any]] = []
        for row in data:
            if not isinstance(row, dict) or not row.get("domain"):
                continue
            out.append(
                {
                    "domain": row.get("domain"),
                    "url": row.get("url"),
                    "primary": bool(row.get("primary")),
                    "observed_at": row.get("price_set_date"),
                    "lot_count": _as_int(row.get("living_count")),
                    "price_per_sqm": _as_int(row.get("living_sqm")),
                }
            )
        return out

    def diagnostics(self) -> dict[str, Any]:
        return {
            "available": self.available,
            "projects": len(self._projects or []),
            "errors": self.errors[:5],
        }


def _as_int(value: Any) -> int | None:
    try:
        return int(round(float(value)))
    except (TypeError, ValueError):
        return None
