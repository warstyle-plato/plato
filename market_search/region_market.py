"""Свод рынка региона из кабинета «Пульса» — раз в неделю, фоном.

Месячный отчёт-книга есть только по Москве, и только из него собирается
городской свод (`moscow-market-*.json`). По остальной России живые данные
идут из кабинета «вся Россия» поштучно: цена и её история, остатки, темп.
Здесь они складываются в свод той же формы, что московский, чтобы читатель
(`market_reference.MoscowMarket`) работал для региона без второго расчёта.
Источник подписан: свод региона — «кабинет», Москвы — «отчёт».

Правила:

* **Раз в неделю и не в запросе пользователя.** Сбор — это сотни проектов по
  три запроса, с паузой между проектами и лимитом на проход. Его ведёт
  фоновый поток (`run_due`) или ручной запуск под ключом кабинета; страница
  и бот только читают готовый файл.
* **Воркеров два.** Работу берёт тот, кто захватил замок-файл; прогресс лежит
  на диске, и оборванный сбор продолжается с места обрыва, а не заново.
* **Нет данных — не ноль.** Регион без свода называет причину; проект без
  ответа источника в медианы не входит, а считается в диагностике.
* **Регион — по номеру проекта.** Код региона читается только из номера вида
  `50-004184` (`pulse.pulse_region`); адрес даёт лишь муниципалитет для
  средней ступени свода.
"""

from __future__ import annotations

import datetime
import os
import re
import statistics
import time
import urllib.parse
from pathlib import Path
from typing import Any, Callable

from .http import load_json, save_json
from .pulse import RUSSIA_CLASSES, address_region, pulse_class, pulse_region
from .pulse_russia import listing_owner
from .pulse_report_import import _median, _round, _snapshot


SOURCE_NAME = "Пульс Продаж Новостроек"
# Раз в неделю: свод про медианы класса, а не про вчерашний прайс.
INTERVAL_SECONDS = 7 * 24 * 3600
# Глубина истории цены для помесячного ряда по классу.
HISTORY_MONTHS = 12
# Сколько проектов спрашивается одним запросом истории цены.
HISTORY_CHUNK = 25

REGIONS_ENV = "PULSE_REGIONS"
PAUSE_ENV = "PULSE_REGION_PAUSE_SECONDS"
LIMIT_ENV = "PULSE_REGION_MAX_PROJECTS"
SWITCH_ENV = "PULSE_REGION_MARKET"
DEFAULT_REGIONS = ("50",)
DEFAULT_PAUSE_SECONDS = 2.0
# Лимит проектов за один проход. Остальное — следующим проходом, с места.
DEFAULT_LIMIT = 250
# Неудачная попытка (нет проектов, сбой) повторяется через час. Это один
# запрос карты: сутки ожидания означали, что открытый Пульсом доступ или
# выкаченная починка входа доезжали до свода только на следующий день.
RETRY_SECONDS = 3600
# Начатый сбор старше этого начинается заново: ответы недельной давности
# в свод «на дату сбора» не годятся.
PROGRESS_MAX_AGE_SECONDS = 2 * INTERVAL_SECONDS
# Замок старше этого считается брошенным (воркер упал посреди прохода).
# Замок трогается после каждого проекта, поэтому живой сбор его обновляет
# каждые секунды. Выкатка убивает процесс посреди прохода, и замок остаётся
# на диске: при шести часах сбор после каждой выкатки стоял бы полдня.
LOCK_TTL_SECONDS = 15 * 60

RUSSIA_HOST_PREFIX = "russia."
RUSSIA_BASES_HINT = "PULSE_BASE_URL=https://russia.pulsprodaj.ru,https://pulsprodaj.ru"

# Подпись региона по коду номера проекта. Неизвестный код подписывается
# самим кодом — свод от этого не страдает, страдает только заголовок.
REGION_NAMES = {
    "02": "Республика Башкортостан",
    "16": "Республика Татарстан",
    "23": "Краснодарский край",
    "24": "Красноярский край",
    "36": "Воронежская область",
    "39": "Калининградская область",
    "47": "Ленинградская область",
    "50": "Московская область",
    "52": "Нижегородская область",
    "54": "Новосибирская область",
    "59": "Пермский край",
    "61": "Ростовская область",
    "63": "Самарская область",
    "66": "Свердловская область",
    "72": "Тюменская область",
    "74": "Челябинская область",
    "77": "Москва",
    "78": "Санкт-Петербург",
}


def region_name(code: str) -> str:
    return REGION_NAMES.get(str(code), f"регион {code}")


_CADASTRE_RE = re.compile(r"\b(\d{2}):(\d{2}):\d{6,7}:\d{1,7}\b")
# Кадастровые районы, отошедшие Новой Москве, сохранили номера области:
# 50:21 (Ленинский), 50:26 (Наро-Фоминский), 50:27 (Подольский). Участок с
# таким префиксом лежит и в Москве, и в области — регион по нему не решается.
_SHARED_CADASTRAL_DISTRICTS = frozenset({"50:21", "50:26", "50:27"})

SITE_REGION_CADASTRE = "cadastre"
SITE_REGION_POINT = "point"
SITE_REGION_ADDRESS = "address"


def cadastre_region(number: str | None) -> str | None:
    """Код региона из кадастрового номера: «50:12:…» → «50»."""
    found = _CADASTRE_RE.search(str(number or ""))
    if not found:
        return None
    if f"{found.group(1)}:{found.group(2)}" in _SHARED_CADASTRAL_DISTRICTS:
        return None
    return found.group(1)


def _code_of_name(name: str | None) -> str | None:
    wanted = str(name or "").casefold()
    return next((code for code, title in REGION_NAMES.items() if title.casefold() == wanted), None)


def _project_region(project: Any) -> str | None:
    """Регион проекта «Пульса»: код номера, иначе область из его адреса."""
    code = pulse_region(getattr(project, "complex_id", None))
    return code or _code_of_name(address_region(getattr(project, "address", None)))


def site_region(
    *,
    cadastre: str | None = None,
    neighbours: Any = (),
    address: str | None = None,
) -> dict[str, Any] | None:
    """Регион участка — один владелец ответа для свода и подписи.

    Порядок доказательств: кадастровый номер участка, затем точка участка
    (регион проектов «Пульса» вокруг неё: код номера или область их
    строительного адреса; большинство, при равенстве — ближний), и лишь
    затем адрес, который пользователь не обязан писать с областью.
    `neighbours` — пары (расстояние, проект), как их отдаёт `near`.
    """
    code = cadastre_region(cadastre)
    if code:
        return {"code": code, "name": region_name(code), "source": SITE_REGION_CADASTRE,
                "evidence": _CADASTRE_RE.search(str(cadastre)).group(0)}
    votes: dict[str, list[float]] = {}
    for distance, project in neighbours or ():
        found = _project_region(project)
        if found:
            votes.setdefault(found, []).append(float(distance))
    if votes:
        code = max(votes, key=lambda key: (len(votes[key]), -min(votes[key])))
        return {"code": code, "name": region_name(code), "source": SITE_REGION_POINT,
                "evidence": f"проектов «Пульса» у точки участка: {len(votes[code])}"}
    from .market_reference import RegionMarket

    name = RegionMarket.region_of(address)
    if name:
        return {"code": _code_of_name(name), "name": name, "source": SITE_REGION_ADDRESS,
                "evidence": address}
    return None


def configured_regions(value: str | None = None) -> list[str]:
    """Коды регионов из `PULSE_REGIONS` (через запятую); по умолчанию — 50."""
    raw = os.getenv(REGIONS_ENV) if value is None else value
    out: list[str] = []
    for item in str(raw or "").replace(";", ",").split(","):
        code = item.strip()
        if re.fullmatch(r"\d{2,3}", code) and code not in out:
            out.append(code)
    return out or list(DEFAULT_REGIONS)


def _env_float(name: str, default: float) -> float:
    try:
        return max(0.0, float(os.getenv(name, "") or default))
    except ValueError:
        return default


def _env_int(name: str, default: int) -> int:
    try:
        return max(1, int(os.getenv(name, "") or default))
    except ValueError:
        return default


# --- муниципалитет из адреса ---------------------------------------------------

_MUNICIPAL_MARKS = re.compile(
    r"^(?:г\.?\s*о\.?|городской\s+округ|м\.?\s*о\.?|муниципальный\s+округ|"
    r"р-н|район|г\.|город|гп|городское\s+поселение)\s+|"
    r"\s+(?:г\.?\s*о\.?|городской\s+округ|м\.?\s*о\.?|муниципальный\s+округ|р-н|район)$",
    re.IGNORECASE,
)


# Регион, склеенный с городом без запятой: «Московская область г. Мытищи» —
# так пишет адреса всероссийский кабинет.
_REGION_PREFIX = re.compile(
    r"^(?:[а-яё-]+\s+(?:область|обл\.?|край)|республика\s+[а-яё-]+)\s+(.+)$",
    re.IGNORECASE,
)


def municipality_of(address: str | None) -> str | None:
    """Городской округ/город из строительного адреса: «г.о. Мытищи» → «Мытищи».

    Берётся первая часть адреса после региона, у которой есть явная пометка
    округа, района или города. Без пометки — `None`: улица или посёлок за
    муниципалитет не выдаются.
    """
    parts = [part.strip() for part in str(address or "").split(",") if part.strip()]
    for part in parts:
        if address_region(part):
            continue
        glued = _REGION_PREFIX.match(part)
        if glued:
            part = glued.group(1).strip()
        name = _MUNICIPAL_MARKS.sub("", part).strip()
        if name and name != part:
            name = name.strip(" .")
            return name[:1].upper() + name[1:] if name else None
    return None


def _segment_raw(pulse: Any, complex_id: str) -> str | None:
    """Слово класса из карточки кабинета, если клиент его знает (для диагностики)."""
    reader = getattr(pulse, "segment_raw", None)
    return reader(complex_id) if callable(reader) else None


# --- свод -------------------------------------------------------------------------


def _point(record: dict[str, Any]) -> dict[str, Any]:
    """Строка проекта в форме, которую понимает `_snapshot` отчёта."""
    return {
        "price": record.get("price_per_sqm"),
        # Темп источника — штук в месяц, средний; это не продажи последнего
        # месяца, как в отчёте, и в своде так и подписано (`basis`).
        "sold": record.get("units_per_month"),
        "rem": record.get("remaining_units"),
        "area": record.get("area_per_month"),
    }


def build_region_market(
    code: str,
    records: dict[str, dict[str, Any]],
    *,
    collected_at: str,
    projects_total: int,
    failed: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Свод региона той же формы, что `moscow-market-*.json`."""
    from .service_v6 import _fresh_price_since

    name = region_name(code)
    # Цена объявлений бывает и у сданного в 2021 году дома — последний раз,
    # когда его квартиры висели на площадке. В медиану «на дату сбора» она не
    # входит: порог свежести тот же, что у соседей участка.
    fresh_since = _fresh_price_since(datetime.date.fromisoformat(collected_at[:10]))
    stale = {
        key for key, row in records.items()
        if row.get("price_per_sqm") and row.get("price_observed_at")
        and str(row["price_observed_at"]) < fresh_since
    }
    on_sale = {
        key: row for key, row in records.items()
        if row.get("price_per_sqm") and key not in stale
    }
    current: dict[str, list[dict[str, Any]]] = {}
    by_okrug: dict[str, dict[str, list[dict[str, Any]]]] = {}
    areas: dict[str, list[float]] = {}
    without_segment = 0
    without_municipality = 0
    # Слово класса, которого нет в карте `pulse_class`: ЖК в своде без класса,
    # а слово — здесь, чтобы его было видно, а не чтобы оно стало классом.
    unknown_classes: dict[str, int] = {}
    # Класс — через карту и в сохранённых сборах: запись могла попасть в
    # сбор словом кабинета («Типовой») до того, как карта его узнала.
    segment_of = {key: pulse_class(row.get("segment")) for key, row in on_sale.items()}
    for key, row in on_sale.items():
        segment = segment_of[key]
        if not segment:
            without_segment += 1
            word = str(row.get("segment_raw") or row.get("segment") or "").strip()
            if word and "," not in word:
                unknown_classes[word] = unknown_classes.get(word, 0) + 1
            continue
        point = _point(row)
        current.setdefault(segment, []).append(point)
        place = row.get("municipality")
        if place:
            by_okrug.setdefault(place, {}).setdefault(segment, []).append(point)
        else:
            without_municipality += 1
        area = row.get("area_per_month")
        try:
            area = float(area) if area is not None else None
        except (TypeError, ValueError):
            area = None
        # Ноль — «темпа нет», а не наблюдение темпа: как и в московском
        # эталоне, в медиану он не входит.
        if area and area > 0:
            areas.setdefault(segment, []).append(area)

    months = sorted({
        point["month"]
        for row in on_sale.values()
        for point in row.get("history") or []
        if point.get("month")
    })[-HISTORY_MONTHS:]
    by_class: dict[str, list[dict[str, Any]]] = {}
    for segment in sorted(current):
        series = []
        for month in months:
            prices = [
                float(point["value"])
                for key, row in on_sale.items()
                if segment_of[key] == segment
                for point in row.get("history") or []
                if point.get("month") == month and point.get("value")
            ]
            if not prices:
                continue
            # Продаж помесячно кабинет не отдаёт: поля есть, значений нет.
            # `None`, а не ноль — «не знаем», а не «не продавали».
            series.append({
                "m": month,
                "n": len(prices),
                "price": _round(_median(prices)),
                "ddu": None,
                "sold": None,
                "sold_sum": None,
                "m2_sum": None,
            })
        if series:
            by_class[segment] = series

    day = collected_at[:10]
    return {
        "source": f"{SOURCE_NAME}, кабинет «вся Россия», {name}, сбор {day}",
        "source_kind": "cabinet",
        "region": code,
        "region_name": name,
        "collected_at": collected_at,
        "last_month": collected_at[:7],
        "months": months,
        "okrug_kind": "municipality",
        "class_map": dict(RUSSIA_CLASSES),
        "basis": {
            "price": (
                "цена метра по объявлениям агрегаторов (ЦИАН, Яндекс, Домклик) — "
                f"площадка с наибольшим числом лотов; цены не старше {fresh_since}"
            ),
            "sold": "средний темп продаж источника, лотов в месяц",
            "area": "средний темп продаж источника, м² в месяц",
        },
        "current": {segment: _snapshot(points) for segment, points in current.items()},
        "by_class": by_class,
        "by_okrug": {
            place: {segment: _snapshot(points) for segment, points in segments.items()}
            for place, segments in by_okrug.items()
        },
        "area_median_by_segment": {
            segment: round(float(statistics.median(values)), 1)
            for segment, values in areas.items()
        },
        "area_median_projects": {segment: len(values) for segment, values in areas.items()},
        "coverage": {
            "projects_total": projects_total,
            "projects_answered": len(records),
            "projects_on_sale": len(on_sale),
            "stale_price": len(stale),
            "without_segment": without_segment,
            "unknown_classes": unknown_classes,
            "without_municipality": without_municipality,
            "failed": len(failed or {}),
        },
        "failed_sample": dict(list((failed or {}).items())[:10]),
    }


# --- сбор ---------------------------------------------------------------------------


def _iso(moment: float) -> str:
    return datetime.datetime.fromtimestamp(moment, tz=datetime.timezone.utc).isoformat(
        timespec="seconds"
    )


def _age_seconds(stamp: str | None, now: float) -> float | None:
    if not stamp:
        return None
    try:
        moment = datetime.datetime.fromisoformat(str(stamp))
    except ValueError:
        return None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=datetime.timezone.utc)
    return max(0.0, now - moment.timestamp())


def _bases(pulse: Any) -> list[str]:
    sites = getattr(pulse, "sites", None)
    if sites:
        return [str(site.base) for site in sites]
    return [str(getattr(pulse, "base", "") or "")]


def russia_connected(pulse: Any) -> bool:
    return any(
        (urllib.parse.urlparse(base).netloc or base).startswith(RUSSIA_HOST_PREFIX)
        for base in _bases(pulse)
    )


class RegionMarketCollector:
    """Недельный сбор свода по регионам. Один на процесс, замок — файлом."""

    def __init__(
        self,
        pulse: Any,
        directory: Path,
        *,
        regions: list[str] | None = None,
        pause_seconds: float | None = None,
        limit: int | None = None,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.time,
    ):
        self.pulse = pulse
        self.dir = Path(directory)
        self.regions = regions or configured_regions()
        self.pause_seconds = (
            _env_float(PAUSE_ENV, DEFAULT_PAUSE_SECONDS) if pause_seconds is None else pause_seconds
        )
        self.limit = _env_int(LIMIT_ENV, DEFAULT_LIMIT) if limit is None else limit
        self.sleep = sleep
        self.clock = clock

    # --- пути ---------------------------------------------------------------

    def summary_path(self, code: str) -> Path:
        return self.dir / f"region-market-{code}.json"

    def progress_path(self, code: str) -> Path:
        return self.dir / code / "progress.json"

    def status_path(self, code: str) -> Path:
        return self.dir / code / "status.json"

    @property
    def lock_path(self) -> Path:
        return self.dir / "collect.lock"

    # --- состояние ----------------------------------------------------------

    def blocker(self) -> str | None:
        """Почему сбор не может начаться вовсе — или `None`."""
        if not russia_connected(self.pulse):
            return (
                "Всероссийская база «Пульса» не подключена: в PULSE_BASE_URL нет "
                f"russia.pulsprodaj.ru (сейчас: {', '.join(_bases(self.pulse))}). "
                f"На ядре нужно {RUSSIA_BASES_HINT}"
            )
        if not getattr(self.pulse, "available", False):
            return "Источник выключен: не заданы PULSE_LOGIN и PULSE_PASSWORD"
        return None

    def due(self, code: str) -> bool:
        """Пора ли собирать: свода нет, он старше недели, сбор не дошёл
        или свод разложен по классам другой картой (`class_map`)."""
        if load_json(self.progress_path(code)):
            return True
        summary = load_json(self.summary_path(code)) or {}
        if summary and summary.get("class_map") != dict(RUSSIA_CLASSES):
            # Свод переживает релизы: собранный до карты (или по прежней)
            # держит класс «Типовой», которого не спросит ни один участок.
            return True
        age = _age_seconds(summary.get("collected_at"), self.clock())
        if age is None:
            # Свода нет. Но если прошлая попытка была меньше суток назад
            # и окончилась отказом — не долбим источник каждый час.
            status = load_json(self.status_path(code)) or {}
            tried = _age_seconds(status.get("finished_at"), self.clock())
            return tried is None or tried >= RETRY_SECONDS
        return age >= INTERVAL_SECONDS

    def status(self) -> dict[str, Any]:
        now = self.clock()
        regions = []
        for code in self.regions:
            summary = load_json(self.summary_path(code)) or {}
            progress = load_json(self.progress_path(code)) or {}
            last = load_json(self.status_path(code)) or {}
            age = _age_seconds(summary.get("collected_at"), now)
            row: dict[str, Any] = {
                "region": code,
                "region_name": region_name(code),
                "collected_at": summary.get("collected_at"),
                "age_days": None if age is None else round(age / 86400, 1),
                "coverage": summary.get("coverage"),
                "segments": sorted(summary.get("current") or {}),
                "municipalities": len(summary.get("by_okrug") or {}),
                "due": self.due(code),
                "last_run": last or None,
            }
            if progress:
                row["in_progress"] = {
                    "started_at": progress.get("started_at"),
                    "done": len(progress.get("records") or {}) + len(progress.get("failed") or {}),
                    "total": len(progress.get("ids") or []),
                }
            if not summary.get("current"):
                row["reason"] = (
                    self.blocker()
                    or last.get("reason")
                    or ("Сбор идёт, свод появится по его окончании" if progress else None)
                    or "Свод региона ещё не собирался"
                )
            regions.append(row)
        return {
            "interval_days": INTERVAL_SECONDS // 86400,
            "regions_setting": REGIONS_ENV,
            "regions": regions,
            "blocker": self.blocker(),
            "bases": _bases(self.pulse),
            "pause_seconds": self.pause_seconds,
            "limit_per_pass": self.limit,
            "busy": self.lock_path.exists(),
        }

    def explain(self, region: str | None) -> str:
        """Почему по региону адреса нет свода — для пользователя, а не для лога.

        Причина берётся из того же состояния, что `status()`: база не
        подключена, регион не в настройке, сбор идёт (сколько из скольких),
        прошлая попытка не удалась (чем) или сбора ещё не было.
        """
        if not region:
            return (
                "Регион участка не определён, поэтому свод региона не выбран: нет "
                "кадастрового номера, у точки участка нет проектов «Пульса» с "
                "регионом, а в адресе область не названа"
            )
        code = next(
            (key for key, name in REGION_NAMES.items() if name.casefold() == region.casefold()),
            None,
        )
        if code is None or code not in self.regions:
            return (
                f"Свода по региону «{region}» нет: регион не включён в сбор "
                f"({REGIONS_ENV}={','.join(self.regions)})"
            )
        blocker = self.blocker()
        if blocker:
            return f"Свода по региону «{region}» нет. {blocker}"
        progress = load_json(self.progress_path(code)) or {}
        if progress.get("ids"):
            done = len(progress.get("records") or {}) + len(progress.get("failed") or {})
            return (
                f"Свод по региону «{region}» ещё собирается: опрошено {done} из "
                f"{len(progress['ids'])} проектов кабинета; появится по окончании сбора"
            )
        last = load_json(self.status_path(code)) or {}
        if last.get("reason"):
            return f"Свода по региону «{region}» нет: {last['reason']}"
        if self.lock_path.exists():
            return f"Свод по региону «{region}» собирается прямо сейчас"
        return (
            f"Свод по региону «{region}» ещё не собирался: фоновый сбор раз в неделю "
            "стартует после запуска сервера; ручной запуск — POST /market/pulse/regions/run"
        )

    # --- запуск -------------------------------------------------------------

    def run_due(self, *, force: bool = False, only: str | None = None) -> dict[str, Any]:
        """Один проход по регионам, которым пора. Возвращает, что сделано."""
        from auction_search.krt_ranking import claim_file, release_file

        # Причина «база не подключена» не запоминается как попытка: как только
        # владелец задаст переменную, сбор должен пойти на ближайшем шаге.
        blocker = self.blocker()
        if blocker:
            return {"started": False, "reason": blocker}
        if not claim_file(self.lock_path, LOCK_TTL_SECONDS):
            return {"started": False, "reason": "Сбор уже идёт в другом воркере"}
        try:
            results = {}
            for code in self.regions:
                if only and code != only:
                    continue
                if force or self.due(code):
                    results[code] = self.collect(code, restart=force)
            return {"started": True, "regions": results}
        finally:
            release_file(self.lock_path)

    def _remember(self, code: str, payload: dict[str, Any]) -> None:
        save_json(self.status_path(code), {"finished_at": _iso(self.clock()), **payload})

    def _touch_lock(self) -> None:
        try:
            os.utime(self.lock_path)
        except OSError:
            pass

    def collect(self, code: str, *, restart: bool = False) -> dict[str, Any]:
        """Сбор региона: с места обрыва, не больше `limit` проектов за проход."""
        progress = None if restart else load_json(self.progress_path(code))
        if isinstance(progress, dict):
            age = _age_seconds(progress.get("started_at"), self.clock())
            if age is None or age > PROGRESS_MAX_AGE_SECONDS:
                progress = None
        if not isinstance(progress, dict) or not progress.get("ids"):
            projects = [
                item for item in self.pulse.projects() if pulse_region(item.complex_id) == code
            ]
            if not projects:
                errors = list(getattr(self.pulse, "errors", []) or [])[-3:]
                reason = (
                    f"В справочнике кабинета нет проектов региона {code} "
                    f"({region_name(code)}): номеров вида {code}-NNNN не пришло"
                    + (f"; ошибки источника: {'; '.join(errors)}" if errors else "")
                )
                self._remember(code, {"ok": False, "reason": reason})
                return {"ok": False, "reason": reason}
            classes = self.pulse.segments()
            progress = {
                "started_at": _iso(self.clock()),
                "ids": [item.complex_id for item in projects],
                "cards": {
                    item.complex_id: {
                        "name": item.name,
                        "address": item.address,
                        "developer": item.developer,
                        "segment": classes.get(item.complex_id),
                        "segment_raw": _segment_raw(self.pulse, item.complex_id),
                        "municipality": municipality_of(item.address),
                    }
                    for item in projects
                },
                "history": {},
                "records": {},
                "failed": {},
            }
            save_json(self.progress_path(code), progress)

        records: dict[str, Any] = progress["records"]
        failed: dict[str, str] = progress["failed"]
        history: dict[str, Any] = progress["history"]
        pending = [cid for cid in progress["ids"] if cid not in records and cid not in failed]
        batch = pending[: self.limit]

        # История цены — пачками: один запрос на двадцать пять проектов.
        wanted = [cid for cid in batch if cid not in history]
        for start in range(0, len(wanted), HISTORY_CHUNK):
            chunk = wanted[start:start + HISTORY_CHUNK]
            answer = self.pulse.price_history(chunk, HISTORY_MONTHS) or {}
            for cid in chunk:
                history[cid] = answer.get(cid) or []
            self._touch_lock()
            self.sleep(self.pause_seconds)

        # Объявления, уже взятые проектами свода (и прошлых проходов тоже).
        taken_listings: dict[str, str] = {}
        for owner, record in records.items():
            listing_owner(taken_listings, record, owner)
        for index, cid in enumerate(batch):
            seen = len(getattr(self.pulse, "errors", []) or [])
            price = self.pulse.price(cid) or {}
            remaining = self.pulse.remaining(cid) or {}
            # Темп нужен своду только у проекта с ценой: без неё проект в
            # медианы класса не входит. Лишний запрос — лишняя нагрузка на
            # чужой кабинет: в области сотни ЖК, и у половины цены нет.
            sales = (self.pulse.sales(cid) or {}) if price else {}
            fresh_errors = list(getattr(self.pulse, "errors", []) or [])[seen:]
            if not (price or remaining or sales):
                failed[cid] = "; ".join(fresh_errors[:2]) or "источник не вернул ни цены, ни остатков, ни темпа"
            else:
                card = progress["cards"].get(cid) or {}
                if not card.get("segment"):
                    # Класс всероссийского ЖК мог прийти только с его карточкой —
                    # уже после того, как сбор записал классы справочника.
                    card = {
                        **card,
                        "segment": self.pulse.segments(fetch=False).get(cid),
                        "segment_raw": _segment_raw(self.pulse, cid),
                    }
                shared = listing_owner(taken_listings, price, cid)
                if shared:
                    # Кабинет делит один ЖК на несколько записей; объявления у
                    # них одни. Вторая запись — тот же проект, а не ещё одна цена.
                    failed[cid] = f"те же объявления, что у проекта {shared}"
                else:
                    records[cid] = {
                        **card,
                        "listings": list(price.get("listings") or []),
                        "price_per_sqm": price.get("price_per_sqm"),
                        "price_observed_at": price.get("observed_at"),
                        "lot_count": price.get("lot_count"),
                        "remaining_units": remaining.get("remaining_units"),
                        "remaining_area": remaining.get("remaining_area"),
                        "units_per_month": sales.get("units_per_month"),
                        "units_per_month_3m": sales.get("units_per_month_3m"),
                        "area_per_month": sales.get("area_per_month"),
                        "known_sales_for": sales.get("known_sales_for"),
                        "history": history.get(cid) or [],
                    }
            if index % 10 == 9:
                save_json(self.progress_path(code), progress)
            self._touch_lock()
            if index + 1 < len(batch):
                self.sleep(self.pause_seconds)

        done = len(records) + len(failed)
        total = len(progress["ids"])
        if done < total:
            save_json(self.progress_path(code), progress)
            result = {"ok": True, "complete": False, "done": done, "total": total}
            self._remember(code, {**result, "reason": None})
            return result

        collected_at = _iso(self.clock())
        summary = build_region_market(
            code, records, collected_at=collected_at, projects_total=total, failed=failed
        )
        if not summary["current"]:
            reason = (
                f"Из {total} проектов региона ни один не дал цену с классом: "
                f"ответили {len(records)}, без ответа {len(failed)}"
            )
            self._remember(code, {"ok": False, "reason": reason, "done": done, "total": total})
            self.progress_path(code).unlink(missing_ok=True)
            return {"ok": False, "reason": reason}
        save_json(self.summary_path(code), summary)
        self.progress_path(code).unlink(missing_ok=True)
        result = {
            "ok": True,
            "complete": True,
            "done": done,
            "total": total,
            "answered": len(records),
            "failed": len(failed),
            "collected_at": collected_at,
        }
        self._remember(code, {**result, "reason": None})
        return result


def background_loop(collector: RegionMarketCollector, *, heartbeat_seconds: float = 3600.0) -> None:
    """Фоновый поток: раз в час смотрит, не пора ли; собирает — раз в неделю.

    Час — не период сбора, а шаг проверки: незаконченный проход (лимит,
    обрыв) продолжается на следующем шаге, а готовый свод ждёт недели.
    """
    time.sleep(120)
    while True:
        try:
            collector.run_due()
        except Exception as exc:  # noqa: BLE001 — поток не должен умереть
            for code in collector.regions:
                try:
                    collector._remember(code, {"ok": False, "reason": f"сбор упал: {exc!r}"[:300]})
                except OSError:
                    pass
        time.sleep(heartbeat_seconds)
