"""ЕФРСБ (fedresurs.ru) — торги по банкротству одним реестром.

## Почему источник нужен

Владелец не нашёл в «Торгах» лот из сообщения № 25074336 (ООО «Инжтехсвязь»,
публичное предложение на площадке «Вердиктъ», 19.10.2026). «Вердиктъ» мы не
читаем, а банкротных площадок десятки. ЕФРСБ — официальный реестр, куда
арбитражный управляющий обязан выложить сообщение о торгах на любой из них:
один источник вместо двух десятков. Подробнее о рынке — в `fedresurs.py`.

## Что сверено живым ответом (19.10.2026, с ядра и из песочницы)

Каждое имя поля ниже пришло в ответе сервиса; образцы лежат в
`tests/fixtures/efrsb/`. Имена параметров поиска взяты из кода самой страницы
поиска торгов (`convertDataForSend` в чанке `BiddingSearchModule`), а их
действие измерено ответом:

- `GET /backend/biddings?limit=15&offset=0&regionCode=77&…` →
  `{"pageData": [{guid, number, type, status{code,name}, priceForm,
  bankrupt{guid,name,type,inn}, tradePlace{guid,name}, dateStart, dateFinish,
  dateCreate}], "found": N}`. `regionCode` — регион ДОЛЖНИКА: торги
  московского ООО «Инжтехсвязь» находятся с 77 и не находятся с 50, а у
  московских должников бывают участки в Туле и Кемерове. Поэтому Москва
  ИМУЩЕСТВА проверяется отдельно, по тексту лота и кадастровому номеру.
  `found` упирается в 10 000 — это потолок счётчика, а не число торгов.
- `onlyAvailableToParticipate=true` пропускает и просроченные торги (срок
  приёма заявок 28.04.2025 при статусе «Открыт приём заявок»), поэтому живость
  решает срок, а не статус.
- `tradeStartDate`/`tradeEndDate` отбирают по дате начала торгов.
- `GET /backend/biddings/<guid>` → `message{guid,number}`,
  `applicationPeriod{startDate,endDate}`, `tradePlace{name,url}`,
  `organizer{name}`, `debtor{name,inn}`, `legalCase{number}`.
- `GET /backend/biddings/<guid>/lots?limit=15&offset=0` →
  `pageData[{number, status{code,name}, startPrice, classifiers, tradeObject}]`;
  у завершённых ещё `currentPrice`, `winner{name}`, `decisionProof`.
- `GET /backend/bankruptcy-messages/<guid>` — само сообщение о торгах.

## Почему сбор идёт фоном

В Москве при начальной цене от 20 млн ₽ — около 1 800 живых торгов (19.10.2026),
и чтобы прочитать лот, нужен отдельный запрос на каждые торги. Восемь
одновременных запросов сервис оборвал ответом 429, следующие — 451. Поэтому
сбор идёт в фоне, по одному запросу с паузой, и складывается на диск: лоты
однажды прочитанных торгов не меняются, и второй раз за ними не ходим. Выдача
читает готовое и в срок ответа укладывается всегда; пока первый сбор не
закончен, строка охвата так и говорит.
"""

from __future__ import annotations

import json
import os
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime
from typing import Any, Callable, Iterable
from zoneinfo import ZoneInfo

from auction_search.adapters.base import AuctionPlatformAdapter
from auction_search.adapters.torgi_gov import trust_context
from auction_search.classifier import classify_lot, origin_from_evidence
from auction_search.models import (
    AuctionDocument, AuctionLot, AuctionSource, LotKind, Provenance, SourceKind,
    utc_now_iso)
from auction_search.parsing import cadastral_numbers, normalize_space, parse_area_sqm

HOST = "fedresurs.ru"
SITE = "https://fedresurs.ru"
BACKEND = "https://fedresurs.ru/backend"
BROWSER_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/130.0 Safari/537.36")
_MOSCOW = ZoneInfo("Europe/Moscow")

# Регион должника в поиске торгов. Код 77 сверен ответом: московский должник
# находится с ним и не находится с 50.
MOSCOW_REGION_CODE = "77"
# Кадастровый округ имущества — явная карта, а не догадка по адресу: номер
# 77:… выдаёт Росреестр участкам и зданиям Москвы.
CADASTRAL_REGION = {"77": "Москва"}

# Порог начальной цены лота. Эталон сделок владельца — 48…931 млн ₽; порог
# ниже эталона, чтобы публичное предложение со стартом ниже профиля не терялось,
# и выше мелочи физических лиц (машины, доли квартир), которой в реестре
# большинство. При 20 млн ₽ в Москве около 1 800 живых торгов (19.10.2026).
MIN_START_PRICE_RUB = 20_000_000

PAGE_SIZE = 15            # сверено; limit=100 сервис отверг ответом 451
MAX_LIVE_PAGES = 160      # 2 400 торгов — с запасом к 1 800
MAX_FINISHED_PAGES = 80
REQUEST_GAP_SECONDS = 2.0
REQUEST_TIMEOUT_SECONDS = 20
NETWORK_RETRIES = 2
RETRY_PAUSE_SECONDS = 5.0
CACHE_FRESH_SECONDS = 6 * 3600
REFUSAL_PAUSE_SECONDS = 30 * 60
HARVEST_LOCK_STALE_SECONDS = 2 * 3600

# Коды статусов, увиденные в ответах. Неизвестный код не угадывается: торги с
# ним в выдачу не идут и считаются в отчёте отдельно.
LIVE_STATUSES = {"BiddingDeclared", "ApplicationSessionStarted"}
FINISHED_STATUSES = {"Finished", "BiddingFail"}
RESULT_WORDS = {"Finished": "Торги завершены", "BiddingFail": "Торги не состоялись"}

# Площадка торгов → наш читатель той же площадки. По адресу сайта площадки из
# карточки торгов (`tradePlace.url`), а не по имени: имя пишется по-разному
# («Вердиктъ» в кавычках-ёлочках), а адрес один.
PLATFORM_BY_HOST = {
    "sberbank-ast.ru": SourceKind.SBERBANK_AST,
    "etpgpb.ru": SourceKind.ETP_GPB,
    "etprf.ru": SourceKind.ETP_RF,
    "nistp.ru": SourceKind.NISTP,
    "lot-online.ru": SourceKind.LOT_ONLINE,
    "roseltorg.ru": SourceKind.ROSELTORG,
}

_MOSCOW_CITY_RE = re.compile(r"(?:^|[,;\s])(?:г\.?\s*)?москв(?:а|ы|е|у|ой)(?:$|[,;.\s])", re.I)
_MOSCOW_REGION_RE = re.compile(r"московск\w*\s+област\w*", re.I)
_DEVELOPMENT_RE = re.compile(
    r"(?:земельн\w*\s+участ\w*|имущественн\w*\s+комплекс\w*|"
    r"объект\w*\s+незавершенн\w*|\bкрт\b|нежил\w*|недвижим\w*|здани\w*)", re.I)
_LAND_RE = re.compile(r"земельн\w*\s+участ", re.I)
_BUILDING_RE = re.compile(r"здани|строени|сооружени|помещени|объект\w*\s+незавершенн", re.I)
_OBJECT_SPLIT_RE = re.compile(
    r";\s*(?=(?:[-–—•]\s*)?(?:[А-ЯЁA-Z]|(?:жил|нежил|земельн|здани|помещени|сооружени|"
    r"объект\w*\s+незаверш|право\s+(?:аренды|собственност)|квартир|машино|гараж)))")
_TAG_RE = re.compile(r"<[^>]+>")
_GUID_RE = re.compile(r"[0-9a-fA-F]{8}-?[0-9a-fA-F]{4}-?[0-9a-fA-F]{4}-?[0-9a-fA-F]{4}-?[0-9a-fA-F]{12}")


class SourceRefused(RuntimeError):
    """Сервис ответил отказом — с кодом и словами для строки охвата."""


def message_url(guid: str) -> str:
    """Адрес сообщения в том виде, в каком его открывает человек."""
    return f"{SITE}/bankruptmessages/{guid.replace('-', '').upper()}"


def bidding_url(guid: str) -> str:
    return f"{SITE}/biddings/{guid}"


def _guid_from(text: str) -> str:
    match = _GUID_RE.search(text or "")
    if not match:
        return ""
    raw = match.group(0).replace("-", "").lower()
    return f"{raw[:8]}-{raw[8:12]}-{raw[12:16]}-{raw[16:20]}-{raw[20:]}"


# --- чтение сервиса ----------------------------------------------------------

class Client:
    """GET к бэкенду ЕФРСБ: по одному запросу, с паузой, отказ — с причиной."""

    def __init__(self, gap_seconds: float = REQUEST_GAP_SECONDS,
                 opener: Callable[..., Any] | None = None) -> None:
        self.gap_seconds = gap_seconds
        self._opener = opener or urllib.request.urlopen
        self._last = 0.0
        self.requests = 0

    def get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        wait = self._last + self.gap_seconds - time.monotonic()
        if wait > 0:
            time.sleep(wait)
        query = urllib.parse.urlencode({k: v for k, v in (params or {}).items()
                                        if v not in (None, "")})
        url = f"{BACKEND}/{path}" + (f"?{query}" if query else "")
        request = urllib.request.Request(url, headers={
            "User-Agent": BROWSER_UA, "Referer": SITE + "/",
            "Accept": "application/json, text/plain, */*",
        })
        for attempt in range(NETWORK_RETRIES + 1):
            self.requests += 1
            try:
                with self._opener(request, timeout=REQUEST_TIMEOUT_SECONDS,
                                  context=trust_context()) as response:
                    body = response.read()
                break
            except urllib.error.HTTPError as exc:
                if exc.code in (403, 429, 451):
                    raise SourceRefused(
                        f"ЕФРСБ отказал в запросе (код {exc.code}): сервис ограничивает "
                        "частоту обращений, сбор продолжится позже") from exc
                raise
            except (urllib.error.URLError, ConnectionError, TimeoutError):
                # Обрыв соединения — не отказ сервиса: повторяем, но не долбим.
                if attempt == NETWORK_RETRIES:
                    raise
                time.sleep(RETRY_PAUSE_SECONDS * (attempt + 1))
            finally:
                self._last = time.monotonic()
        return json.loads(body.decode("utf-8"))


# --- склад -------------------------------------------------------------------

def _store_path() -> str:
    return os.path.join(os.getenv("DATA_DIR", "data"), "market", "auctions", "efrsb.json")


def load_store(path: str | None = None) -> dict[str, Any]:
    try:
        with open(path or _store_path(), encoding="utf-8") as handle:
            data = json.load(handle)
        if isinstance(data, dict):
            data.setdefault("biddings", {})
            data.setdefault("runs", {})
            return data
    except (OSError, ValueError):
        pass
    return {"biddings": {}, "runs": {}}


def save_store(store: dict[str, Any], path: str | None = None) -> None:
    path = path or _store_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    temp = f"{path}.{os.getpid()}.{threading.get_ident()}.tmp"
    with open(temp, "w", encoding="utf-8") as handle:
        json.dump(store, handle, ensure_ascii=False)
    os.replace(temp, path)


def _take_lock(path: str) -> bool:
    """Один сбор на оба воркера: память у них раздельная, склад общий."""
    lock = path + ".lock"
    try:
        if time.time() - os.path.getmtime(lock) > HARVEST_LOCK_STALE_SECONDS:
            os.remove(lock)
    except OSError:
        pass
    try:
        os.makedirs(os.path.dirname(lock), exist_ok=True)
        handle = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except OSError:
        return False
    os.write(handle, str(os.getpid()).encode())
    os.close(handle)
    return True


def _drop_lock(path: str) -> None:
    try:
        os.remove(path + ".lock")
    except OSError:
        pass


# --- сбор --------------------------------------------------------------------

def _search_params(kind: str, since: date | None, until: date | None, offset: int) -> dict[str, Any]:
    params: dict[str, Any] = {"limit": PAGE_SIZE, "offset": offset,
                              "regionCode": MOSCOW_REGION_CODE,
                              "lotStartPrice": MIN_START_PRICE_RUB}
    if kind == "live":
        params["onlyAvailableToParticipate"] = "true"
    else:
        params["tradeStartDate"] = f"{since.isoformat()}T00:00:00"
        params["tradeEndDate"] = f"{until.isoformat()}T23:59:59"
    return params


def harvest(kind: str, *, client: Client | None = None, store_path: str | None = None,
            since: date | None = None, until: date | None = None,
            max_pages: int | None = None) -> dict[str, Any]:
    """Пройти выдачу торгов и дочитать лоты новых торгов. Пишет склад по ходу.

    `kind` — «live» (идёт приём заявок) или «finished» (окно дат начала
    торгов). Лоты торгов читаются один раз; карточка торгов (ссылка на
    сообщение, срок, площадка) — только у тех, где нашёлся московский лот под
    девелопмент: остальным она не нужна, а запрос стоит паузы.
    """
    client = client or Client()
    path = store_path or _store_path()
    store = load_store(path)
    run: dict[str, Any] = {"kind": kind, "started_at": time.time(), "pages": 0,
                           "rows": 0, "lots_read": 0, "cards_read": 0, "reason": ""}
    if kind == "finished":
        run["window"] = {"since": since.isoformat(), "until": until.isoformat()}
    store["runs"][kind] = {**store["runs"].get(kind, {}), "running": True,
                           "started_at": run["started_at"]}
    save_store(store, path)
    seen: list[str] = []
    try:
        limit = max_pages or (MAX_LIVE_PAGES if kind == "live" else MAX_FINISHED_PAGES)
        for page in range(limit):
            answer = client.get("biddings", _search_params(kind, since, until, page * PAGE_SIZE))
            rows = answer.get("pageData") or []
            run["pages"] += 1
            run["rows"] += len(rows)
            for row in rows:
                guid = str(row.get("guid") or "")
                if not guid:
                    continue
                seen.append(guid)
                entry = store["biddings"].setdefault(guid, {})
                entry["row"] = row
                entry["seen_at"] = time.time()
            if len(rows) < PAGE_SIZE:
                break
        for guid in seen:
            entry = store["biddings"][guid]
            finished = str((entry["row"].get("status") or {}).get("code") or "") in FINISHED_STATUSES
            if kind == "finished" and not finished:
                continue
            # Лоты живых торгов не меняются, у завершённых появляется итог —
            # их дочитываем, когда торги перешли в завершённые.
            if "lots" not in entry or (finished and not entry.get("lots_final")):
                answer = client.get(f"biddings/{guid}/lots", {"limit": PAGE_SIZE, "offset": 0})
                entry["lots"] = [_slim_lot(lot) for lot in answer.get("pageData") or []]
                entry["lots_final"] = finished
                run["lots_read"] += 1
            if "card" not in entry and any(_lot_is_candidate(lot) for lot in entry["lots"]):
                entry["card"] = client.get(f"biddings/{guid}")
                run["cards_read"] += 1
            if (run["lots_read"] + run["cards_read"]) % 25 == 0:
                save_store(store, path)
    except SourceRefused as exc:
        run["reason"] = str(exc)
    except Exception as exc:  # noqa: BLE001 — недособранное сохраняется, причина видна
        run["reason"] = f"ЕФРСБ не ответил: {type(exc).__name__}: {exc}"[:300]
    run["finished_at"] = time.time()
    run["complete"] = not run["reason"]
    run["running"] = False
    run["requests"] = client.requests
    if kind == "live":
        run["seen"] = seen
    store["runs"][kind] = run
    save_store(store, path)
    return run


_STARTED: dict[str, float] = {}

# Выключатель фонового сбора. В прогоне тестов он взведён в `conftest.py`:
# фоновая работа приложения — не часть теста, и сеть из нити туда не ходит.
HARVEST_FLAG = "AUCTION_EFRSB_HARVEST"


def harvest_enabled() -> bool:
    return os.getenv(HARVEST_FLAG, "1").strip().lower() not in {"0", "false", "no", "off"}


def ensure_fresh(kind: str, *, since: date | None = None, until: date | None = None,
                 store: dict[str, Any] | None = None, store_path: str | None = None,
                 starter: Callable[[Callable[[], Any]], Any] | None = None) -> str:
    """Запустить фоновый сбор, если склад устарел. Не ждёт его.

    Отвечает словами, что происходит: строка охвата повторяет их человеку.
    """
    path = store_path or _store_path()
    store = store if store is not None else load_store(path)
    run = store["runs"].get(kind) or {}
    now = time.time()
    same_window = kind == "live" or (run.get("window") == {
        "since": since.isoformat(), "until": until.isoformat()})
    if run.get("running") and now - float(run.get("started_at") or 0) < HARVEST_LOCK_STALE_SECONDS:
        return "running"
    if same_window and run.get("complete") and now - float(run.get("finished_at") or 0) < CACHE_FRESH_SECONDS:
        return "fresh"
    if run.get("reason") and now - float(run.get("finished_at") or 0) < REFUSAL_PAUSE_SECONDS:
        return "paused"
    if starter is None and not harvest_enabled():
        return "disabled"
    if now - _STARTED.get(kind, 0) < 60:
        return "running"
    if not _take_lock(path):
        return "running"
    _STARTED[kind] = now

    def work() -> None:
        try:
            harvest(kind, store_path=path, since=since, until=until)
        finally:
            _drop_lock(path)

    (starter or (lambda job: threading.Thread(target=job, daemon=True,
                                              name=f"efrsb-{kind}").start()))(work)
    return "started"


# Поля лота, которые читает разбор. Остальное (условия договора, реквизиты
# оплаты) на складе не держим: на 2 500 торгах это десятки мегабайт, а склад
# читается каждой выдачей.
_LOT_FIELDS = ("number", "status", "startPrice", "currentPrice", "winner",
               "classifiers", "tradeObject", "decisionProof")


def _slim_lot(lot: dict[str, Any]) -> dict[str, Any]:
    slim = {key: lot[key] for key in _LOT_FIELDS if key in lot}
    if isinstance(slim.get("tradeObject"), str):
        slim["tradeObject"] = slim["tradeObject"][:8000]
    return slim


# --- разбор ------------------------------------------------------------------

def _plain(text: Any) -> str:
    return normalize_space(_TAG_RE.sub(" ", str(text or "")))


def _is_moscow_property(text: str, cad: list[str]) -> bool:
    """Имущество в Москве: по кадастровому округу, а без номера — по адресу."""
    if any(CADASTRAL_REGION.get(number.split(":", 1)[0]) == "Москва" for number in cad):
        return True
    if cad:
        return False
    return bool(_MOSCOW_CITY_RE.search(_MOSCOW_REGION_RE.sub(" ", text)))


def _lot_is_candidate(lot: dict[str, Any]) -> bool:
    text = _plain(lot.get("tradeObject"))
    return (bool(text) and bool(_DEVELOPMENT_RE.search(text))
            and _is_moscow_property(text, cadastral_numbers(text))
            and classify_lot(text, "банкротство") is not LotKind.OTHER)


def _areas(text: str) -> tuple[float | None, float | None, int]:
    """Площадь участков и строений — суммой по объектам лота.

    Лот банкрота — часто перечень: двадцать зданий и помещений и право аренды
    участка. Первая площадь в тексте (151 м² у Инжтехсвязи) — это одно здание
    из двадцати, и сравнивать с ценой лота её нельзя.
    """
    land = building = 0.0
    counted = 0
    # Объекты лота разделены «;» перед новым объектом: «…аренда; Здание, …» у
    # Инжтехсвязи, «…квартира 3; - земельный участок, …» у физического лица.
    # Внутри описания участка «;» стоит и между видами разрешённого
    # использования, а площадь — уже после неё, поэтому делим не по каждой «;».
    for part in _OBJECT_SPLIT_RE.split(text):
        area = parse_area_sqm(part)
        if not area:
            continue
        if _LAND_RE.search(part):
            land += area
            counted += 1
        elif _BUILDING_RE.search(part):
            building += area
            counted += 1
    return (round(land, 1) or None), (round(building, 1) or None), counted


def _moment(value: Any) -> str | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        moment = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=_MOSCOW)
    return moment.isoformat()


def _future(moment: str | None, now: datetime | None = None) -> bool:
    if not moment:
        return False
    return datetime.fromisoformat(moment) >= (now or datetime.now(_MOSCOW))


def to_lots(entry: dict[str, Any], fetched_at: str, *, finished: bool = False,
            now: datetime | None = None) -> tuple[list[AuctionLot], dict[str, int]]:
    """Лоты одних торгов → наши лоты. Второе значение — почему отсеяны прочие."""
    skipped = {"not_moscow": 0, "not_development": 0, "not_live": 0, "status_unknown": 0}
    row = entry.get("row") or {}
    card = entry.get("card") or {}
    status_code = str((row.get("status") or {}).get("code") or "")
    wanted = FINISHED_STATUSES if finished else LIVE_STATUSES
    lots_raw = entry.get("lots") or []
    if status_code not in wanted:
        skipped["status_unknown" if status_code not in LIVE_STATUSES | FINISHED_STATUSES
                else "not_live"] += len(lots_raw) or 1
        return [], skipped
    period = card.get("applicationPeriod") or {}
    deadline = _moment(period.get("endDate")) or _moment(row.get("dateFinish"))
    start = _moment(period.get("startDate")) or _moment(row.get("dateStart"))
    if not finished and not _future(deadline, now):
        # Статус «Открыт приём заявок» у торгов, срок которых давно прошёл,
        # сервис отдаёт и с `onlyAvailableToParticipate`. Живость решает срок.
        skipped["not_live"] += len(lots_raw) or 1
        return [], skipped
    message = card.get("message") or {}
    message_guid = str(message.get("guid") or "")
    guid = str(row.get("guid") or "")
    url = message_url(message_guid) if message_guid else bidding_url(guid)
    place = card.get("tradePlace") or row.get("tradePlace") or {}
    place_host = (urllib.parse.urlparse("//" + str(place.get("url") or "").split("//")[-1])
                  .hostname or "").lower().removeprefix("www.")
    trade_type = str((card.get("type") or {}).get("name") or row.get("type") or "")
    debtor = (card.get("debtor") or {}).get("name") or (row.get("bankrupt") or {}).get("name")
    out: list[AuctionLot] = []
    for raw_lot in lots_raw:
        text = _plain(raw_lot.get("tradeObject"))
        cad = cadastral_numbers(text)
        if not _is_moscow_property(text, cad):
            skipped["not_moscow"] += 1
            continue
        kind = classify_lot(text, "банкротство")
        if kind is LotKind.OTHER or not _DEVELOPMENT_RE.search(text):
            skipped["not_development"] += 1
            continue
        lot_status = raw_lot.get("status") or {}
        land, building, objects = _areas(text)
        price = raw_lot.get("startPrice")
        price = float(price) if isinstance(price, (int, float)) and price > 0 else None
        result = None
        if finished and status_code == "Finished" and raw_lot.get("winner"):
            value = raw_lot.get("currentPrice")
            result = float(value) if isinstance(value, (int, float)) and value > 0 else None
        number = str(raw_lot.get("number") or "1")
        lot = AuctionLot(
            source=AuctionSource(SourceKind.EFRSB, url, f"{row.get('number') or guid}#{number}",
                                 fetched_at, "ЕФРСБ"),
            lot_kind=kind,
            title=text[:1500],
            origin=origin_from_evidence(procedure_type="банкротство", text=text),
            address=None if cad else text[:1000],
            cadastral_numbers=cad,
            land_area_sqm=land,
            building_area_sqm=building,
            seller=debtor,
            organizer=(card.get("organizer") or {}).get("name"),
            procedure_type=f"Банкротство, {trade_type.lower()}" if trade_type else "Банкротство",
            start_price_rub=price,
            application_start=start,
            application_deadline=deadline,
            status=str(lot_status.get("name") or (row.get("status") or {}).get("name") or "") or None,
            status_code=str(lot_status.get("code") or status_code) or None,
            result_price_rub=result,
            documents=[AuctionDocument("Сообщение о торгах в ЕФРСБ", url, "notice",
                                       fetched_at, access_status="public")]
            + ([AuctionDocument("Торги в ЕФРСБ", bidding_url(guid), "registry",
                                fetched_at, access_status="public")] if guid else []),
            raw={"efrsb_bidding_guid": guid, "efrsb_message_guid": message_guid,
                 "efrsb_trade_number": row.get("number"),
                 "efrsb_trade_place": place.get("name"), "efrsb_trade_place_host": place_host,
                 "efrsb_lot_number": number, "classifiers": raw_lot.get("classifiers") or [],
                 "region_basis": ("кадастровый округ 77" if cad else "адрес в тексте лота"),
                 "area_objects": objects},
        )
        prov = {"title": text[:300], "start_price_rub": str(price) if price else None,
                "application_deadline": deadline, "status": lot.status,
                "cadastral_numbers": ", ".join(cad) or None,
                "land_area_sqm": f"{land} — сумма по участкам лота" if land else None,
                "building_area_sqm": f"{building} — сумма по зданиям и помещениям лота"
                if building else None,
                "result_price_rub": str(result) if result else None}
        for field, value in prov.items():
            if value:
                lot.provenance[field] = Provenance(source_url=url, fetched_at=fetched_at,
                                                   source_section="ЕФРСБ", raw_value=value)
        out.append(lot)
    return out, skipped


def lots_from_message(message: dict[str, Any], guid: str, fetched_at: str) -> list[AuctionLot]:
    """Сообщение о торгах → лоты: для разбора одного сообщения по ссылке."""
    content = (message.get("content") or {}).get("messageInfo", {}).get("messageContent") or {}
    application = content.get("application") or {}
    entry = {
        "row": {"guid": "", "number": message.get("number"),
                "status": {"code": "ApplicationSessionStarted", "name": "Объявлены торги"},
                "type": {"PublicOffer": "Публичное предложение"}.get(
                    str(content.get("tradeType") or ""), str(content.get("tradeType") or "")),
                "bankrupt": {"name": (message.get("bankrupt") or {}).get("name")},
                "tradePlace": {"name": content.get("tradeSite")}},
        "card": {"message": {"guid": guid},
                 "applicationPeriod": {
                     "startDate": (application.get("dateTimeBegin") or {}).get("dateTime"),
                     "endDate": (application.get("dateTimeEnd") or {}).get("dateTime")}},
        "lots": [{"number": item.get("order"), "startPrice": item.get("startPrice"),
                  "tradeObject": item.get("description"),
                  "classifiers": [c.get("name") for c in item.get("classifierCollection") or []]}
                 for item in content.get("lotTable") or []],
    }
    lots, _ = to_lots(entry, fetched_at, now=datetime.min.replace(tzinfo=_MOSCOW))
    return lots


# --- читатель для выдачи -----------------------------------------------------

class EfrsbAdapter(AuctionPlatformAdapter):
    """Торги по банкротству из ЕФРСБ: Москва, недвижимость и земля."""

    HOST = HOST
    deep_parse_unavailable = ("Лот из ЕФРСБ: полный разбор документов недоступен, "
                              "сообщение о торгах открывается по ссылке.")

    def __init__(self, store_path: str | None = None,
                 starter: Callable[[Callable[[], Any]], Any] | None = None) -> None:
        self.store_path = store_path
        self.starter = starter
        # Момент «сейчас» для решения, идёт ли приём заявок; тесты его задают.
        self.now: datetime | None = None
        self.last_report: dict[str, Any] = {"source": self.platform_name}

    @property
    def platform_name(self) -> str:
        return "ЕФРСБ"

    def _collect(self, entries: Iterable[dict[str, Any]], *, finished: bool,
                 keep: Callable[[dict[str, Any]], bool] | None = None) -> tuple[list[AuctionLot], dict[str, int]]:
        fetched_at = utc_now_iso()
        lots: list[AuctionLot] = []
        totals: dict[str, int] = {}
        cards = 0
        for entry in entries:
            if "lots" not in entry or (keep is not None and not keep(entry)):
                continue
            cards += 1
            found, skipped = to_lots(entry, fetched_at, finished=finished, now=self.now)
            lots.extend(found)
            for key, value in skipped.items():
                totals[key] = totals.get(key, 0) + value
        totals["cards"] = cards
        return lots, totals

    def _report(self, run: dict[str, Any], state: str, lots: list[AuctionLot],
                totals: dict[str, int]) -> None:
        reason = ""
        if state in {"started", "running"} and not run.get("finished_at"):
            reason = ("ЕФРСБ: первый сбор торгов идёт в фоне, обычно он занимает около "
                      "часа. Лоты появятся в выдаче, когда он закончится.")
        elif state in {"started", "running"}:
            reason = "ЕФРСБ: показан прошлый сбор, новый идёт в фоне."
        elif state == "disabled":
            reason = (f"ЕФРСБ: фоновый сбор выключен ({HARVEST_FLAG}=0), показан "
                      "последний сохранённый.")
        elif run.get("reason"):
            reason = f"Сбор прерван: {run['reason']}. Показано то, что успели собрать."
        self.last_report = {
            "source": self.platform_name, "pages": int(run.get("pages") or 0),
            "cards": totals.get("cards", 0), "kept": len(lots),
            "skipped": sum(v for k, v in totals.items() if k != "cards"),
            "skipped_not_moscow": totals.get("not_moscow", 0),
            "skipped_not_development": totals.get("not_development", 0),
            "skipped_not_live": totals.get("not_live", 0),
            "skipped_status_unknown": totals.get("status_unknown", 0),
            "collected_at": run.get("finished_at"),
            "harvest": state,
            "region_note": ("Москва — по региону должника в ЕФРСБ и по адресу или "
                            "кадастровому номеру имущества в лоте"),
            "min_start_price_rub": MIN_START_PRICE_RUB,
            "reason": reason,
        }

    def discover_moscow(self, *, deadline: float | None = None) -> list[AuctionLot]:
        store = load_store(self.store_path)
        state = ensure_fresh("live", store=store, store_path=self.store_path,
                             starter=self.starter)
        run = store["runs"].get("live") or {}
        seen = set(run.get("seen") or [])
        entries = [store["biddings"][g] for g in seen if g in store["biddings"]] if seen else []
        lots, totals = self._collect(entries, finished=False)
        self._report(run, state, lots, totals)
        return lots

    def discover_moscow_finished(self, since: date, until: date, *,
                                 deadline: float | None = None) -> list[AuctionLot]:
        if since > until:
            raise ValueError("начало окна позже его конца")
        store = load_store(self.store_path)
        state = ensure_fresh("finished", since=since, until=until, store=store,
                             store_path=self.store_path, starter=self.starter)
        run = store["runs"].get("finished") or {}

        def in_window(entry: dict[str, Any]) -> bool:
            start = _moment((entry.get("row") or {}).get("dateStart"))
            return bool(start) and since <= datetime.fromisoformat(start).date() <= until

        lots, totals = self._collect(store["biddings"].values(), finished=True, keep=in_window)
        self._report(run, state, lots, totals)
        self.last_report["window"] = {"since": since.isoformat(), "until": until.isoformat(),
                                      "date_field": "dateStart — дата начала торгов"}
        return lots

    def fetch_lot(self, lot_url: str) -> AuctionLot:
        host = (urllib.parse.urlparse(lot_url).hostname or "").lower()
        if not (host == HOST or host.endswith("." + HOST)):
            raise ValueError("Читатель ЕФРСБ принимает только адреса fedresurs.ru")
        guid = _guid_from(lot_url)
        if not guid:
            raise ValueError("В адресе нет номера сообщения ЕФРСБ")
        lots = lots_from_message(Client(gap_seconds=0).get(f"bankruptcy-messages/{guid}"),
                                 guid, utc_now_iso())
        if not lots:
            raise ValueError("В сообщении ЕФРСБ нет московского лота с недвижимостью или землёй")
        return lots[0]


def same_trade(efrsb_lot: AuctionLot, other: AuctionLot) -> bool:
    """Лот ЕФРСБ — это тот же лот, что у нашего читателя площадки?

    Площадка — по адресу её сайта из карточки торгов, явной картой. Сам лот — по
    общему кадастровому номеру, а без номеров — по номеру торгов площадки,
    который ЕФРСБ печатает в карточке («37014-ОТПП» у НИС).
    """
    platform = PLATFORM_BY_HOST.get(str(efrsb_lot.raw.get("efrsb_trade_place_host") or ""))
    if platform is None or other.source.platform is not platform:
        return False
    if set(efrsb_lot.cadastral_numbers) & set(other.cadastral_numbers):
        return True
    number = str(efrsb_lot.raw.get("efrsb_trade_number") or "")
    digits = re.match(r"\d{3,}", number)
    if not digits:
        return False
    haystack = f"{other.source.external_lot_id} {other.source.lot_url}"
    return bool(re.search(rf"(?<!\d){digits.group(0)}(?!\d)", haystack))


__all__ = ["EfrsbAdapter", "harvest", "ensure_fresh", "to_lots", "lots_from_message",
           "same_trade", "message_url", "Client", "SourceRefused"]
