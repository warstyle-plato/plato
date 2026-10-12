"""Всероссийский кабинет «Пульса» (`russia.pulsprodaj.ru`) — своё API.

Кабинет — одностраничное приложение: страница `/map` в 850 байт и скрипт
`/assets/index-*.js`. Ни встроенного GeoJSON, ни московских адресов
(`/api/search/`, `/api/app/complex/price_stats/`) у него нет: они отвечают
404. Свои запросы скрипт шлёт на `/api/v1/…` с той же сессией и CSRF-кукой,
что выдаёт вход на `pulsprodaj.ru`. Разбор маршрутов — в
`docs/pulse_russia_api.md`.

Чем кабинет отличается от московского:

* **Единица — объект строительства** (`50-004184-1`, внутренний id 91019),
  а ЖК (`complex`, внутренний id 350624) объединяет объекты разных
  деклараций. Соседом и проектом свода здесь считается ЖК: иначе один ЖК из
  трёх корпусов был бы тремя соседями с одной и той же ценой агрегатора.
  Номер ЖК у нас — «50-c350624»: код региона и внутренний номер.
* **Регион — внутренний номер кабинета**, не код субъекта: «50» у него —
  Астраханская область, Московская — «9». Номер ищется по названию региона
  (`regions/search/`), а код берётся из нашего списка регионов. Справочник
  собирается по регионам `PULSE_REGIONS` (по умолчанию 50): одним запросом на
  регион, без обхода всей страны.
* **Класс лежит в объекте**, а не в фильтре. Карточку ЖК (класс, адрес,
  застройщик, его объекты, остаток) отдаёт `objects_grouped/` с
  `group_by: complex` — пачкой ЖК за запрос. Смешанный класс — «не знаем».
* **Цена — объявления агрегаторов** (ЦИАН, Яндекс, Домклик) из
  `aggregator-card-data/`, а не прайс-лист застройщика. Берётся последняя
  дата и площадка с наибольшим числом лотов: площадки показывают одни и те
  же квартиры, складывать их нельзя.
* **Темп** — `objects_sales_summary/` по объектам ЖК: средние продажи в
  месяц за период, который называет сам ответ.

Худший исход прежний: нет доступа или ответа — пустота и названная причина
в `errors`, а не исключение.
"""

from __future__ import annotations

import json
import time
import urllib.error
from typing import Any

from .http import fresh, load_json, save_json
from .pulse import (
    PulseClient,
    PulseProject,
    _as_int,
    _id_file,
    pulse_class,
    pulse_id,
    russia_complex,
)

API = "/api/v1/"
SOURCE = "Пульс Продаж Новостроек, кабинет «вся Россия»"
# Сколько ЖК спрашивается одним запросом карточек (~3 КБ на ЖК).
CARD_CHUNK = 50
# Пауза между запросами сборки справочника: кабинет чужой, нагрузка — наша.
CATALOG_PAUSE_SECONDS = 1.0


def _dropped(error: str) -> bool:
    """Обрыв связи, а не ответ сервера: такой запрос стоит повторить."""
    text = error.lower()
    return "http error" not in text and any(
        mark in text for mark in ("reset by peer", "timed out", "remote end closed", "connection aborted")
    )


def complex_id(region: str, internal: Any) -> str:
    return f"{region}-c{int(internal)}"


class PulseRussiaClient(PulseClient):
    """Клиент всероссийского кабинета: справочник ЖК, класс, цена, темп."""

    def __init__(self, *args: Any, **kwargs: Any):
        super().__init__(*args, **kwargs)
        self.pause_seconds = CATALOG_PAUSE_SECONDS
        self.sleep = time.sleep
        # Что ответил кабинет при сборке справочника — для отчёта справочника.
        self.map_path = API + "search/"
        self.regions_probe: list[dict[str, Any]] = []

    # --- сеть -------------------------------------------------------------------

    def _api(self, path: str, payload: dict[str, Any] | None = None) -> Any:
        """POST (или GET без тела) в `/api/v1/`; ошибка — в `errors`, ответ — `None`.

        Оборванное соединение (не ответ сервера) повторяется один раз: сбор
        региона — сотни запросов, и один сброс связи не должен оставлять ЖК
        без цены на полсуток.
        """
        if payload is not None:
            seen = len(self.errors)
            answer = self._post_json(API + path, payload)
            if answer is None and any(_dropped(text) for text in self.errors[seen:]):
                del self.errors[seen:]
                self.sleep(self.pause_seconds * 2)
                answer = self._post_json(API + path, payload)
            return answer
        if not self._cookie("sessionid") and not self.sign_in():
            return None
        for attempt in (1, 2):
            try:
                body = self._open(
                    API + path,
                    headers={"Content-Type": "application/json", "Referer": f"{self.base}/map"},
                )
            except urllib.error.HTTPError as exc:
                closed = self._closed(exc)
                if closed:
                    self.errors.append(f"{API}{path}: {closed}")
                    return None
                if exc.code in (401, 403) and attempt == 1 and self.sign_in():
                    continue
                self.errors.append(f"{API}{path}: {exc}")
                return None
            except (urllib.error.URLError, OSError) as exc:
                self.errors.append(f"{API}{path}: {exc}")
                return None
            try:
                return json.loads(body.decode("utf-8", errors="ignore"))
            except ValueError:
                if attempt == 1 and self.sign_in():
                    continue
                self.errors.append(f"{API}{path}: ответ не JSON")
                return None
        return None

    def _cached(self, name: str, complex_id: Any, build) -> Any:
        """Как у базового клиента, но пустой ответ не запоминается: это сбой, а не данные."""
        path = self.dir / "cache" / f"{name}-{_id_file(complex_id)}.json"
        if fresh(path, self.detail_ttl_seconds):
            cached = load_json(path)
            if isinstance(cached, dict) and cached.get("value") is not None:
                return cached["value"]
        value = build()
        if value is not None:
            path.parent.mkdir(parents=True, exist_ok=True)
            save_json(path, {"value": value})
        return value

    # --- регионы ----------------------------------------------------------------

    def _region_id(self, code: str) -> int | None:
        """Внутренний номер региона кабинета по коду субъекта — через название."""
        from .region_market import REGION_NAMES

        path = self.dir / "regions.json"
        known = load_json(path)
        known = known if isinstance(known, dict) else {}
        if isinstance(known.get(code), int):
            return known[code]
        name = REGION_NAMES.get(code)
        if not name:
            self.errors.append(
                f"регион {code}: названия нет в списке регионов, номер кабинета не найти"
            )
            return None
        answer = self._api("regions/search/", {"query": name, "excludeIds": [], "limit": 20})
        found = _find_region(answer, name)
        if found is None:
            if answer is not None:
                self.errors.append(f"регион {code}: кабинет не знает региона «{name}»")
            return None
        known[code] = found
        save_json(path, known)
        return found

    # --- справочник ---------------------------------------------------------------

    def _fetch_projects(self) -> list[dict[str, Any]] | None:
        """ЖК регионов `PULSE_REGIONS`: один запрос `search/` на регион.

        Карточки (адрес, застройщик, класс, объекты) — следом, пачками по
        `CARD_CHUNK` ЖК: на Московскую область это десяток запросов.
        """
        from .region_market import configured_regions

        if not self.available and not self._cookie("sessionid"):
            return None
        rows: list[dict[str, Any]] = []
        self.regions_probe = []
        listed: list[str] = []
        for code in configured_regions():
            region = self._region_id(code)
            if region is None:
                self.regions_probe.append({"region": code, "error": "номер региона не найден"})
                continue
            answer = self._api(
                "search/", {"regionsIds": [region], "filters": [{}], "entityType": "complex"}
            )
            content = answer.get("content") if isinstance(answer, dict) else None
            if not isinstance(content, dict):
                self.regions_probe.append({"region": code, "region_id": region, "error": "нет content"})
                continue
            self.regions_probe.append({"region": code, "region_id": region, "complexes": len(content)})
            for key, item in content.items():
                if not isinstance(item, dict) or item.get("lat") is None or item.get("lon") is None:
                    continue
                cid = complex_id(code, key)
                rows.append({
                    "complex_id": cid,
                    "name": str(item.get("name") or "").strip(),
                    "latitude": float(item["lat"]),
                    "longitude": float(item["lon"]),
                    "object_count": _as_int(item.get("object_count")),
                    "map_status": item.get("map_status"),
                })
                listed.append(cid)
            self.sleep(self.pause_seconds)
        if not rows:
            return None
        cards = self._cards(listed, fetch_missing=True)
        for row in rows:
            card = cards.get(row["complex_id"]) or {}
            row.update({
                "developer": card.get("developer"),
                "builder": card.get("builder"),
                "address": card.get("address"),
            })
        return rows

    def projects(self, *, refresh: bool = False, fetch: bool = True) -> list[PulseProject]:
        """Справочник как у базового клиента; адрес — из карточки, если она уже есть."""
        items = super().projects(refresh=refresh, fetch=fetch)
        if not items:
            return items
        cards = self._load_cards()
        out = []
        for item in items:
            card = cards.get(item.complex_id)
            if card and not item.address:
                item = PulseProject(**{
                    **item.__dict__,
                    "address": card.get("address"),
                    "developer": item.developer or card.get("developer"),
                    "builder": item.builder or card.get("builder"),
                })
            out.append(item)
        self._projects = out
        return out

    # --- карточки ЖК ------------------------------------------------------------

    @property
    def _cards_path(self):
        return self.dir / "cards.json"

    def _load_cards(self) -> dict[str, dict[str, Any]]:
        cards = load_json(self._cards_path)
        return cards if isinstance(cards, dict) else {}

    def _cards(self, ids: list[str], *, fetch_missing: bool = True) -> dict[str, dict[str, Any]]:
        """Карточки ЖК из `objects_grouped/` (по `complex_ids`), с кэшем на сутки."""
        cards = self._load_cards()
        stale = not fresh(self._cards_path, self.ttl_seconds)
        wanted = [
            cid for cid in dict.fromkeys(ids)
            if russia_complex(cid) is not None and (stale or cid not in cards)
        ]
        if fetch_missing and wanted:
            for start in range(0, len(wanted), CARD_CHUNK):
                chunk = wanted[start:start + CARD_CHUNK]
                answer = self._api(
                    "objects_grouped/",
                    {
                        "ids": [],
                        "group_by": "complex",
                        "complex_ids": [russia_complex(cid) for cid in chunk],
                    },
                )
                if not isinstance(answer, list):
                    # Пачка не пришла — прочие пачки всё равно спрашиваются:
                    # одна оборванная связь не должна оставлять область без классов.
                    continue
                by_internal = {russia_complex(cid): cid for cid in chunk}
                for cid in chunk:
                    cards.pop(cid, None)
                # Номер ЖК — в самой строке (`complex_id`), а не по порядку.
                for group in answer:
                    cid = by_internal.get(_as_int((group or {}).get("complex_id")))
                    if cid:
                        cards[cid] = _card(group)
                if start + CARD_CHUNK < len(wanted):
                    self.sleep(self.pause_seconds)
            save_json(self._cards_path, cards)
        return cards

    def card(self, complex_id: Any) -> dict[str, Any]:
        cid = pulse_id(complex_id) or ""
        return self._cards([cid]).get(cid) or {}

    def segments(self, *, refresh: bool = False, fetch: bool = True) -> dict[str, str]:
        """Класс ЖК — из карточек, что уже собраны; по сети отдельно не ходит.

        Карточки собираются вместе со справочником. Класса у ЖК без карточки,
        со смешанным или незнакомым классом нет — это «не знаем», а не
        «эконом». Слово кабинета переводится картой `pulse_class` при чтении:
        карточка из кэша могла быть записана до карты.
        """
        if fetch:
            # Недостающие карточки (пачка оборвалась при сборке справочника)
            # добираются здесь же: только их, а не весь регион заново.
            cards = self._cards([item.complex_id for item in self.projects(refresh=refresh)])
        else:
            cards = self._load_cards()
        out = {}
        for cid, card in cards.items():
            segment = pulse_class(card.get("segment_raw") or card.get("segment"))
            if segment:
                out[cid] = segment
        return out

    def segment_raw(self, complex_id: Any) -> str | None:
        """Слово класса, как его пишет кабинет, — для диагностики, без сети."""
        card = self._load_cards().get(pulse_id(complex_id) or "") or {}
        return card.get("segment_raw") or None

    # --- данные ЖК ----------------------------------------------------------------

    def _aggregator(self, complex_id: Any) -> dict[str, Any] | None:
        internal = russia_complex(complex_id)
        if internal is None:
            return None
        data = self._cached(
            "aggregator",
            complex_id,
            lambda: self._api(
                "aggregator-card-data/",
                {"ids": [], "complex_ids": [internal], "object_type": "living"},
            ),
        )
        if isinstance(data, dict) and data.get("subscription_required"):
            self.errors.append(
                f"{API}aggregator-card-data/: цены объявлений закрыты подпиской "
                f"кабинета (subscription_required) — ЖК {complex_id}"
            )
            return None
        return data if isinstance(data, dict) else None

    def price(self, complex_id: Any) -> dict[str, Any] | None:
        """Цена метра по объявлениям агрегаторов на последнюю дату."""
        data = self._aggregator(complex_id)
        if not data:
            return None
        return aggregator_price(data.get("table"))

    def price_history(self, complex_ids: list[Any], months: int = 12) -> dict[str, list[dict[str, Any]]]:
        """Помесячная цена метра по объявлениям: ряд `aggregator_sqm_price`.

        Кабинет складывает в ряд все ЖК запроса, поэтому — по запросу на ЖК
        (ответ общий с ценой и лежит в кэше).
        """
        out: dict[str, list[dict[str, Any]]] = {}
        for value in complex_ids:
            cid = pulse_id(value)
            if russia_complex(cid) is None:
                continue
            data = self._aggregator(cid)
            out[cid] = aggregator_series((data or {}).get("history"))[-months:]
        return out

    def _sales_summary(self, complex_id: Any) -> dict[str, Any] | None:
        objects = self.card(complex_id).get("objects") or []
        if not objects:
            return None
        data = self._cached(
            "sales_summary",
            complex_id,
            lambda: self._api("objects_sales_summary/", {"ids": objects}),
        )
        if isinstance(data, dict) and data.get("access_restricted"):
            self.errors.append(
                f"{API}objects_sales_summary/: продажи ЖК {complex_id} закрыты "
                "подпиской кабинета (access_restricted)"
            )
            return None
        if not isinstance(data, dict):
            return None
        living = next(
            (col for col in data.get("cols") or [] if isinstance(col, dict) and col.get("key") == "living"),
            None,
        )
        return {**data, "living": living} if living else None

    def sales(self, complex_id: Any) -> dict[str, Any] | None:
        data = self._sales_summary(complex_id)
        if not data:
            return None
        living = data["living"]
        if living.get("avg_units") is None:
            return None
        period = " — ".join(
            str(data.get(key) or "")[:7] for key in ("period_start", "period_end") if data.get(key)
        )
        return {
            "units_per_month": round(float(living["avg_units"]), 1),
            # Трёхмесячного темпа кабинет не отдаёт: «не знаем», а не ноль.
            "units_per_month_3m": None,
            "area_per_month": (
                round(float(living["avg_area"]), 1) if living.get("avg_area") is not None else None
            ),
            "sales_end_forecast": None,
            "known_sales_for": period or None,
            "source": SOURCE,
            "quality": "provider",
        }

    def remaining(self, complex_id: Any) -> dict[str, Any]:
        """Остаток квартир — из карточки ЖК (`actual_living_remaining`)."""
        card = self.card(complex_id)
        if card.get("remaining_units") is None and card.get("remaining_area") is None:
            return {}
        return {
            "remaining_units": card.get("remaining_units"),
            "remaining_area": card.get("remaining_area"),
        }

    def project_totals(self, complex_id: Any) -> dict[str, Any]:
        card = self.card(complex_id)
        if not card:
            return {}
        units, area = card.get("living_units"), card.get("living_area")
        return {
            "living_units": units,
            "living_area": area,
            "buildings": len(card.get("objects") or []) or None,
            "lot_area_avg": round(area / units, 1) if units and area else None,
        }

    # --- то, чего у этого кабинета нет московскими адресами ------------------------
    # Страница проекта, сроки, рассрочки разбираются с московской страницы
    # проекта; у всероссийского кабинета её нет. Спрашивать московские
    # адреса значило бы копить 404 в `errors` и заслонять ими настоящую причину.

    def project_page(self, complex_id: Any, *, refresh: bool = False) -> dict[str, Any]:
        return {}

    def project_dates(self, complex_id: Any) -> dict[str, Any]:
        return {}

    def project_stage(self, complex_id: Any) -> dict[str, Any]:
        return {}

    def project_facts(self, complex_id: Any) -> dict[str, Any]:
        return {}

    def exposure(self, complex_id: Any) -> list[dict[str, Any]]:
        return []

    def find_project(self, query: str) -> dict[str, Any] | None:
        found = self.suggest(query, limit=1)
        return {**found[0], "matched_by": "name"} if found else None

    def probe_fields(self) -> dict[str, Any]:
        return {"base": self.base, "api": API, "regions": self.regions_probe}

    def probe_object_types(self, complex_id: Any) -> dict[str, Any]:
        return {"complex_id": pulse_id(complex_id), "by_object_type": {}}

    def catalog_report(self, *, refresh: bool = False) -> dict[str, Any]:
        report = super().catalog_report(refresh=refresh)
        report["map_probe"] = self.regions_probe
        report["unit"] = "ЖК (complex) кабинета; объекты ЖК — в карточке"
        report["cards"] = len(self._load_cards())
        return report


# --- разбор ответов: без сети, проверяется на образцах -----------------------------


def _find_region(answer: Any, name: str) -> int | None:
    """Номер региона уровня «субъект» с точным названием в дереве `regions/search/`."""
    wanted = name.casefold()
    stack = list((answer or {}).get("results") or []) if isinstance(answer, dict) else []
    while stack:
        node = stack.pop()
        if not isinstance(node, dict):
            continue
        if node.get("level") == 1 and str(node.get("name") or "").casefold() == wanted:
            return _as_int(node.get("id"))
        stack.extend(node.get("children") or [])
    return None


def _card(group: dict[str, Any]) -> dict[str, Any]:
    """Карточка ЖК из строки `objects_grouped/` (`group_by: complex`).

    Поля группы, где объекты расходятся, кабинет склеивает через запятую
    («Сдан, Строится»). Класс «Бизнес, Комфорт» — не класс: у такого ЖК класса
    нет («не знаем»), а склейка остаётся в `segment_raw` для расшифровки.
    Слово класса переводит в наш класс карта `pulse_class` («Типовой» —
    «Стандарт/Эконом»); незнакомое слово тоже остаётся только в `segment_raw`.
    """
    raw = str(group.get("object_class") or "").strip()
    units = _as_int(group.get("living_count"))
    area = group.get("living_area")
    remaining_area = group.get("actual_living_remaining_area")
    return {
        "segment": pulse_class(raw),
        "segment_raw": raw or None,
        "name": group.get("name"),
        "address": group.get("address"),
        "developer": group.get("developer") or None,
        "builder": group.get("zastroychik") or None,
        "region": group.get("region"),
        "objects": [int(item) for item in group.get("object_ids") or [] if _as_int(item) is not None],
        "declarations": [
            part.strip() for part in str(group.get("pd_num") or "").split(",") if part.strip()
        ],
        "status": group.get("status"),
        "living_units": units or None,
        "living_area": round(float(area), 1) if area else None,
        "remaining_units": _as_int(group.get("actual_living_remaining")),
        "remaining_area": round(float(remaining_area)) if remaining_area is not None else None,
    }


def listing_owner(taken: dict[str, str], price: dict[str, Any] | None, owner: str) -> str | None:
    """Чей это ЖК по объявлениям: проект, уже взявший их, — или `None` (и берёт сам).

    Один владелец ответа для соседей участка, отчёта и свода региона.
    Кабинет делит один ЖК на несколько записей, и у них бывают одни и те же
    проекты площадок (`listings` цены). Первая запись (ближняя к участку, первая
    в своде) — проект, следующая — тот же ЖК второй раз, а не ещё одна цена.
    Цена без кодов (московский кабинет) ни с кем не совпадает.
    """
    listings = (price or {}).get("listings") or []
    for code in listings:
        if code in taken and taken[code] != owner:
            return taken[code]
    for code in listings:
        taken[code] = owner
    return None


def aggregator_price(table: Any) -> dict[str, Any] | None:
    """Цена метра из таблицы агрегаторов: последняя дата, самая полная площадка.

    Строка таблицы — проект на одной площадке. Площадки показывают одни и те
    же квартиры, поэтому лоты разных площадок не складываются: берётся та, где
    лотов больше. Проектов одной площадки у ЖК бывает несколько (очереди) —
    они складываются, цена взвешивается по лотам.
    """
    rows = [
        row for row in table or []
        if isinstance(row, dict) and row.get("sqm_price") and row.get("price_date")
    ]
    if not rows:
        return None
    latest = max(str(row["price_date"])[:10] for row in rows)
    current = [row for row in rows if str(row["price_date"])[:10] == latest]
    by_source: dict[str, list[dict[str, Any]]] = {}
    for row in current:
        by_source.setdefault(str(row.get("source") or ""), []).append(row)

    def lots(group: list[dict[str, Any]]) -> float:
        return sum(float(row.get("count_price") or 0) for row in group)

    source, group = max(by_source.items(), key=lambda item: lots(item[1]))
    total = lots(group)
    if total > 0:
        price = sum(float(row["sqm_price"]) * float(row.get("count_price") or 0) for row in group) / total
    else:
        price = sum(float(row["sqm_price"]) for row in group) / len(group)
    prices = [int(row["sqm_price"]) for row in current]
    # Коды проектов площадок: по ним видно, что два ЖК кабинета показывают
    # одни и те же объявления (кабинет иногда делит один ЖК на несколько).
    listings = sorted({str(row["code"]) for row in current if row.get("code")})
    return {
        "price_per_sqm": int(round(price)),
        "price_per_sqm_min": min(prices),
        "price_per_sqm_max": max(prices),
        "lot_count": _as_int(total) or None,
        "lot_area_avg": _as_int(group[0].get("avg_area_price")),
        "observed_at": latest,
        "source": f"{SOURCE}: объявления {group[0].get('source_label') or source}",
        "basis": "pulse_aggregator_listing_average",
        "sources": sorted(by_source),
        "listings": listings,
    }


def aggregator_series(history: Any) -> list[dict[str, Any]]:
    """Ряд `aggregator_sqm_price` истории агрегаторов: [{month, value}]."""
    if not isinstance(history, dict):
        return []
    months = history.get("months") or []
    series = next(
        (
            item for item in history.get("series") or []
            if isinstance(item, dict) and item.get("metric") == "aggregator_sqm_price"
        ),
        None,
    )
    if not series:
        return []
    out = []
    for month, value in zip(months, series.get("values") or []):
        if month and value:
            out.append({"month": str(month)[:7], "value": int(value)})
    return out
