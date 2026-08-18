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
    ):
        self.base = (base or os.getenv("PULSE_BASE_URL") or PULSE_BASE).rstrip("/")
        self.login = login if login is not None else os.getenv("PULSE_LOGIN", "")
        self.password = password if password is not None else os.getenv("PULSE_PASSWORD", "")
        self.timeout = timeout
        self.ttl_seconds = ttl_seconds
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

    # --- данные проекта --------------------------------------------------------

    def price(self, complex_id: int) -> dict[str, Any] | None:
        """Цена прайс-листа: средняя, границы, число лотов и дата среза."""
        data = self._post_json("/api/app/complex/price_stats/", {"complex_id": int(complex_id)})
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
        data = self._post_json("/api/app/complex/sales/", {"complex_id": int(complex_id)})
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
