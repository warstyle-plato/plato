"""ЕФРСБ (bankrot.fedresurs.ru) — торги по банкротству.

## Зачем понадобился, когда есть ГИС Торги

ГИС Торги оказались не тем рынком. Живой ответ 24.08.2026 подтвердил в поле
вида торгов ровно один код — `178FZ`, приватизация государственного и
муниципального имущества, — и выдача это подтверждает содержанием: тридцать
гаражей в Шеметове по 0,2 млн ₽, россыпь земельных участков без опубликованной
площади, мелкие нежилые помещения по 12–195 м². Это городское имущество, а не
рынок, ради которого модуль писался.

Насколько не тот, показала таблица владельца (372 лота 2017–2025 годов с
исходом по каждому, 25.08.2026):

- **44% выборки — реализация имущества в рамках процедуры банкротства**
  (163 лота), и продаётся оно лучше всего: 55% против 5% у ареста и нуля у
  исполнительного производства;
- из 130 лотов с указанной площадкой на НАШИХ (Росэлторг и РАД/Lot-online)
  стоят 49, а 81 — на площадках банкротства: Сбербанк-АСТ, ЭТП ГПБ, Фабрикант,
  Альфалот, ЭТП РФ, М-ЭТС, ЦДТ, Центр реализации, НИСТП, Вертрейдс, РТС-тендер,
  Тектор. Прямо мы не читаем ни одну.

Отсюда и решение владельца: «заменяй значит источник» (25.08.2026).

## Почему агрегатор, а не два десятка площадок

Ровно по той же причине, по которой был выбран ГИС Торги: площадок банкротства
десятки, один и тот же лот лежит на нескольких сразу, и склеивать дубли
пришлось бы нам. ЕФРСБ — официальный реестр сведений о банкротстве, сообщение о
торгах там одно на процедуру.

## Чего этот файл НЕ знает и не делает вид, что знает

Из песочницы bankrot.fedresurs.ru закрыт сетевой политикой — соединение не
устанавливается вовсе (403 на CONNECT), как у torgi.gov.ru и НСПД. Значит
**разбора здесь нет**: ни имён полей, ни кодов, ни оболочки ответа. Есть
только проба, которая ходит с ядра и ПОКАЗЫВАЕТ сырой ответ.

Это не осторожность, а вывод из своей же ошибки. С ГИС Торгами разбор был
написан по догадке и «уверенности модели»: живой ответ опроверг почти каждое
имя поля, а сам источник оказался про другой рынок — и всё это выяснилось уже
на проде, у владельца на экране. Второй раз так не делаем: сначала ответ,
потом код.

Поэтому адаптер намеренно **не реализует** `discover_moscow` и `fetch_lot` —
пустой список читался бы как «лотов нет», а выдуманный разбор как найденные
лоты. Пока не сверено, источник не включён.

Запуск пробы с ядра:

    curl -s 'http://127.0.0.1:8080/auctions/fedresurs/probe' | head -c 4000

## Что уже сверено живым ответом (19.10.2026, из песочницы, с перебоями)

`bankrot.fedresurs.ru/TradeList.aspx` — оболочка Angular, данных в ней нет.
Данные отдаёт JSON-бэкенд `fedresurs.ru/backend/…` с заголовком `Referer`:

- `GET /backend/companies?limit=15&offset=0&searchString=<ИНН>` →
  `{"pageData": [{"guid", "ogrn", "inn", "name", "egrulAddress", "status",
  "okvedName", "isActive"}], "found": N}`. Параметр `code` сервис молча
  игнорирует и отдаёт случайных должников — искать только `searchString`.
- `GET /backend/companies/<guid>` → карточка с `addressEgrul`.
- `GET /backend/companies/<guid>/bankruptcy` → `{"intentionMessages": […],
  "legalCases": [{"guid", "number", "status", "lastPublications": [{"guid",
  "number", "datePublish", "typeName"}]}]}`. Сообщение 25074336 пришло здесь
  с `typeName` «Объявление о проведении торгов».

Адрес карточки самого сообщения и список сообщений о торгах по региону НЕ
сверены: `/backend/bankruptmessages/<guid>` и соседние догадки ответили 404,
а бандл SPA через прокси песочницы не докачивается. Их ищет `probe_api` — с
ядра, по бандлу страницы, а не по догадке.

    curl -s 'http://127.0.0.1:8080/auctions/fedresurs/api' | head -c 20000
"""

from __future__ import annotations

import json
import re
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from auction_search.adapters.browser_probe import probe_browser as browser_probe
from auction_search.adapters.torgi_gov import trust_context, trust_report

HOST = "bankrot.fedresurs.ru"
USER_AGENT = "DevelopAid-AuctionCollector/0.1 (+https://developaid.ru)"
TIMEOUT_SECONDS = 12
# Бэкенд fedresurs.ru отдаёт JSON обычному браузерному запросу с Referer.
# Это не подмена себя за человека и не обход капчи: тот же GET, что делает
# страница, а на капчу проба по-прежнему отвечает отказом с причиной.
BROWSER_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/130.0 Safari/537.36")

# Адреса-кандидаты. Ни один НЕ сверен ответом: это то, что проба будет
# спрашивать, а не то, что мы знаем. Каждый печатается вместе с кодом ответа и
# началом тела — «спросили вот это, пришло вот такое».
CANDIDATES: tuple[tuple[str, str], ...] = (
    ("публичный поиск торгов", "https://bankrot.fedresurs.ru/TradeList.aspx"),
    ("карточка API v1", "https://bankrot.fedresurs.ru/backend/tradelist"),
    ("карточка API v2", "https://bankrot.fedresurs.ru/api/tradelist"),
    ("сообщения о торгах", "https://bankrot.fedresurs.ru/backend/messages"),
    ("корень", "https://bankrot.fedresurs.ru/"),
)

_BODY_SHOWN = 1200


def _fetch(url: str, context: ssl.SSLContext) -> dict[str, Any]:
    request = urllib.request.Request(url, headers={
        "User-Agent": USER_AGENT,
        "Accept": "application/json, text/html;q=0.8",
    })
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS,
                                    context=context) as response:
            raw = response.read(200_000)
            body = raw.decode("utf-8", "replace")
            status = int(getattr(response, "status", 0) or 0)
            ctype = response.headers.get("Content-Type", "")
    except urllib.error.HTTPError as exc:
        # Код ответа — это ответ, а не отказ: 404 отличает «не тот адрес» от
        # «сервис закрыт», и путать их нельзя.
        return {"url": url, "http_status": exc.code, "reason": str(exc),
                "body_head": exc.read(2000).decode("utf-8", "replace")[:_BODY_SHOWN]}
    except Exception as exc:  # noqa: BLE001
        return {"url": url, "reason": f"{type(exc).__name__}: {exc}"}
    answer: dict[str, Any] = {
        "url": url, "http_status": status, "content_type": ctype,
        "bytes": len(raw), "body_head": body[:_BODY_SHOWN],
    }
    # Разбираем ровно настолько, чтобы стало видно форму ответа. Имена полей не
    # угадываем: их покажет сам ответ.
    if "json" in ctype.lower() or body.lstrip()[:1] in "{[":
        try:
            payload = json.loads(body)
        except ValueError as exc:
            answer["json"] = f"не разобрался: {exc}"
        else:
            answer["json_type"] = type(payload).__name__
            if isinstance(payload, dict):
                answer["top_keys"] = sorted(payload)[:30]
            elif isinstance(payload, list):
                answer["items"] = len(payload)
                if payload and isinstance(payload[0], dict):
                    answer["first_item_keys"] = sorted(payload[0])[:30]
    return answer


# Страница поиска торгов. Данных в её HTML нет — это оболочка SPA; числа
# подтягивает браузер отдельными запросами к бэкенду. Их-то и надо увидеть.
SEARCH_PAGE = "https://bankrot.fedresurs.ru/TradeList.aspx"

# Признаки капчи Qrator в теле ответа. Живой ответ с ядра 26.08.2026: корень
# отдал 401 со скриптом `/__qrator/qauth_utm_v2d_v9118.js` и функцией
# `qauth_show_captcha`. Это защита от роботов, и обходить её мы не будем —
# ровно от этого она поставлена. Проба обязана СКАЗАТЬ, что упёрлась в капчу,
# а не делать вид, что источник пуст.


def probe_browser(url: str = SEARCH_PAGE, seconds: float = 45.0) -> dict[str, Any]:
    """Открыть страницу ЕФРСБ настоящим браузером и показать, что она загрузила.

    Своей реализации здесь нет: проба заведена один раз в `browser_probe` и
    служит всем источникам. Две копии разошлись бы на признаках отказа, и одна
    из них считала бы страницу «403 Forbidden» удачей — а живой ответ с ядра
    26.08.2026 был именно ею, без капчи и без единого запроса за данными.
    """
    return browser_probe(url, seconds=seconds)


# --- проба JSON-бэкенда ------------------------------------------------------

BACKEND = "https://fedresurs.ru/backend"
SITE = "https://fedresurs.ru"
# Сообщение, которое владелец не нашёл в «Торгах» (№ 25074336, ООО
# «Инжтехсвязь», ИНН 7713210910). Проба спрашивает про него: найдётся ли оно —
# главный вопрос, а не любой ответ сервиса.
KNOWN_MESSAGE_GUID = "5ea9be17-d759-407d-9802-1644c8b27f76"
KNOWN_DEBTOR_INN = "7713210910"

_BACKEND_PATH = re.compile(r"""["'`](?:https://[a-z.]*fedresurs\.ru)?/?(?:backend|api)/[^"'`\s]{1,160}["'`]""")
# Базовый адрес бэкенда в бандле часто лежит переменной, а путь — отдельной
# строкой («/bankruptmessages/» + id). Такие строки ловятся по предмету.
_HINT_PATH = re.compile(
    r"""["'`]/?[a-zA-Z-]*(?:message|trade|bankrupt|lot|auction|publication|bidding)[a-zA-Z/${}.-]{0,120}["'`]""",
    re.I)
_CHUNK_MAP = re.compile(r'(\d+):"([0-9a-f]{16})"')
_SCRIPT_SRC = re.compile(r'src="((?:runtime|main|polyfills|common|scripts)[^"]*\.js)"')


def _get(url: str, context: ssl.SSLContext, *, referer: str = SITE + "/",
         limit: int = 200_000, timeout: float = TIMEOUT_SECONDS) -> tuple[int, str, str]:
    """Код, тип и тело ответа. Ошибка сети — исключением, код 4xx/5xx — ответом."""
    request = urllib.request.Request(url, headers={
        "User-Agent": BROWSER_UA, "Referer": referer,
        "Accept": "application/json, text/plain, */*",
    })
    try:
        with urllib.request.urlopen(request, timeout=timeout, context=context) as response:
            raw = response.read(limit)
            return (int(getattr(response, "status", 0) or 0),
                    response.headers.get("Content-Type", ""),
                    raw.decode("utf-8", "replace"))
    except urllib.error.HTTPError as exc:
        return exc.code, exc.headers.get("Content-Type", "") if exc.headers else "", \
            exc.read(2000).decode("utf-8", "replace")


def _ask(url: str, context: ssl.SSLContext, **kwargs: Any) -> dict[str, Any]:
    """Одна попытка «спросили — пришло», с началом тела и формой JSON."""
    try:
        status, ctype, body = _get(url, context, **kwargs)
    except Exception as exc:  # noqa: BLE001
        return {"url": url, "reason": f"{type(exc).__name__}: {exc}"}
    answer: dict[str, Any] = {"url": url, "http_status": status, "content_type": ctype,
                              "bytes": len(body), "body_head": body[:_BODY_SHOWN * 3]}
    if body.lstrip()[:1] in "{[":
        try:
            payload = json.loads(body)
        except ValueError:
            pass
        else:
            answer["json_type"] = type(payload).__name__
            if isinstance(payload, dict):
                answer["top_keys"] = sorted(payload)[:40]
    return answer


# Слова, вокруг которых проба показывает бандл: ответ 19.10.2026 нашёл пути
# `bidding-messages/${o}` и `bankruptcy-message-docs/${i}`, а сами вызовы
# собираются из базы-переменной — их видно только в окрестности.
SNIPPET_WORDS = ("bankruptcy-messages", "bidding-messages", "biddings", "/trades",
                 "BiddingSearch", "regionId", "tradePlace")

# Путь, который проба читает целиком. Только бэкенд fedresurs.ru и только
# безопасные символы: это окно в публичный JSON, а не прокси куда угодно.
_BACKEND_ASK = re.compile(r"^[A-Za-z0-9/_.\-]{1,120}(?:\?[A-Za-z0-9_.\-=&%:,+]{0,400})?$")
_FULL_BODY = 400_000


def probe_backend(path: str, seconds: float = 30.0) -> dict[str, Any]:
    """Полный ответ одного пути `fedresurs.ru/backend/<path>`. Разбора нет.

    Начала тела в `probe_api` хватает, чтобы узнать, что адрес жив, но не
    хватает, чтобы сверить поля: карточка сообщения 25074336 отдала 200 и
    обрезалась на середине. Разбор пишется по целому ответу.
    """
    clean = path.strip().lstrip("/")
    if clean.startswith("backend/"):
        clean = clean[len("backend/"):]
    if not clean or ".." in clean or not _BACKEND_ASK.match(clean):
        return {"path": path, "reason": "путь не похож на адрес бэкенда ЕФРСБ"}
    url = f"{BACKEND}/{clean}"
    try:
        status, ctype, body = _get(url, trust_context(), limit=_FULL_BODY,
                                   timeout=max(3.0, min(float(seconds), 60.0)))
    except Exception as exc:  # noqa: BLE001
        return {"url": url, "reason": f"{type(exc).__name__}: {exc}"}
    answer: dict[str, Any] = {"url": url, "http_status": status, "content_type": ctype,
                              "bytes": len(body), "truncated": len(body) >= _FULL_BODY}
    try:
        answer["json"] = json.loads(body)
    except ValueError:
        answer["body_head"] = body[:_BODY_SHOWN * 3]
    return answer


def _left(until: float) -> float:
    """Таймаут одного запроса — не дольше, чем осталось пробе."""
    return max(1.0, min(TIMEOUT_SECONDS, until - time.monotonic()))


def _bundle_paths(context: ssl.SSLContext, page_url: str, until: float) -> dict[str, Any]:
    """Пути `/backend/…`, записанные в бандле SPA, — адреса, которые знает сама страница."""
    report: dict[str, Any] = {"page": page_url, "scripts": [], "paths": {}}
    try:
        status, _ctype, html = _get(page_url, context, limit=400_000, timeout=_left(until))
    except Exception as exc:  # noqa: BLE001
        report["reason"] = f"{type(exc).__name__}: {exc}"
        return report
    report["page_status"] = status
    base = page_url.split("/", 3)
    origin = "/".join(base[:3])
    names = list(dict.fromkeys(_SCRIPT_SRC.findall(html)))
    if not names:
        report["reason"] = "в странице нет ссылок на бандл"
        report["page_head"] = html[:_BODY_SHOWN]
        return report
    runtime = next((name for name in names if name.startswith("runtime")), "")
    chunks: list[str] = []
    if runtime:
        try:
            _s, _c, body = _get(f"{origin}/{runtime}", context, limit=400_000,
                                timeout=_left(until))
            # `f.u=e=>(8592===e?"common":e)+"."+{…}[e]+".js"` — номер чанка, у
            # одного из них вместо номера имя «common».
            common = re.search(r'(\d+)===e\?"common"', body)
            chunks = [f"{'common' if common and number == common.group(1) else number}.{digest}.js"
                      for number, digest in _CHUNK_MAP.findall(body)]
        except Exception as exc:  # noqa: BLE001
            report["runtime_reason"] = f"{type(exc).__name__}: {exc}"
    wanted = [name for name in names if not name.startswith(("runtime", "polyfills"))] + chunks

    def one(name: str) -> tuple[str, Any]:
        if time.monotonic() > until:
            return name, "не спрошен: кончилось время пробы"
        try:
            got_status, _c, body = _get(f"{origin}/{name}", context, limit=12_000_000,
                                        timeout=min(20.0, max(1.0, until - time.monotonic())))
        except Exception as exc:  # noqa: BLE001
            return name, f"{type(exc).__name__}: {exc}"
        found = sorted({match.strip("\"'`") for match in _BACKEND_PATH.findall(body)})
        hints = sorted({match.strip("\"'`") for match in _HINT_PATH.findall(body)
                        if "/" in match})[:200]
        # Базовый адрес лежит переменной, а запрос собирается рядом: имя
        # метода и параметры видны только в окрестности пути.
        snippets = [body[max(0, at.start() - 300):at.end() + 300]
                    for word in SNIPPET_WORDS
                    for at in list(re.finditer(re.escape(word), body))[:6]]
        return name, {"http_status": got_status, "bytes": len(body), "paths": found,
                      "hints": hints, "snippets": snippets}

    with ThreadPoolExecutor(max_workers=6) as pool:
        for name, got in pool.map(one, wanted):
            report["scripts"].append({"name": name, **(got if isinstance(got, dict)
                                                       else {"reason": got})})
            if isinstance(got, dict):
                for path in got["paths"]:
                    report["paths"].setdefault(path, name)
    report["paths"] = sorted(report["paths"])
    report["hints"] = sorted({hint for script in report["scripts"]
                              for hint in script.get("hints") or []})[:300]
    report["snippets"] = [{"script": script["name"], "text": text}
                          for script in report["scripts"]
                          for text in script.get("snippets") or []][:60]
    for script in report["scripts"]:
        script.pop("hints", None)
        script.pop("snippets", None)
    return report


def probe_api(message_guid: str = KNOWN_MESSAGE_GUID, inn: str = KNOWN_DEBTOR_INN,
              seconds: float = 40.0) -> dict[str, Any]:
    """Чем отвечает JSON-бэкенд ЕФРСБ. Разбора нет — проба ищет адреса.

    Три вопроса:
    1. сверенные маршруты по должнику (поиск по ИНН → карточка → дело и
       последние публикации) — живы ли они с ядра;
    2. какие пути `/backend/…` записаны в бандле страницы сообщения и страницы
       поиска торгов — так находится адрес карточки сообщения и списка торгов
       без догадки;
    3. кандидаты карточки сообщения — каждый с кодом ответа.
    """
    context = trust_context()
    until = time.monotonic() + max(5.0, float(seconds))
    debtor = _ask(f"{BACKEND}/companies?limit=15&offset=0&searchString={urllib.parse.quote(inn)}",
                  context, timeout=_left(until))
    guid = ""
    try:
        guid = json.loads(debtor.get("body_head") or "{}")["pageData"][0]["guid"]
    except (ValueError, KeyError, IndexError, TypeError):
        pass
    by_debtor: list[dict[str, Any]] = [{"name": "поиск должника по ИНН", **debtor}]
    if guid:
        by_debtor.append({"name": "дело и последние публикации",
                          **_ask(f"{BACKEND}/companies/{guid}/bankruptcy", context,
                                 timeout=_left(until))})
        by_debtor.append({"name": "публикации должника",
                          **_ask(f"{BACKEND}/companies/{guid}/publications?limit=15&offset=0",
                                 context, timeout=_left(until))})
    bare = message_guid.replace("-", "").upper()
    page = f"{SITE}/bankruptmessages/{bare}"
    candidates = [
        f"{BACKEND}/bankruptmessages/{message_guid}",
        f"{BACKEND}/bankrupt-messages/{message_guid}",
        f"{BACKEND}/bankruptcy-messages/{message_guid}",
        f"{BACKEND}/messages/{message_guid}",
        f"https://bankrot.fedresurs.ru/backend/messages/{message_guid}",
        f"https://bankrot.fedresurs.ru/MessageWindow.aspx?ID={bare}",
    ]
    with ThreadPoolExecutor(max_workers=6) as pool:
        message = list(pool.map(
            lambda url: _ask(url, context, referer=page, timeout=_left(until)), candidates))
        bundles = list(pool.map(lambda url: _bundle_paths(context, url, until),
                                (page, "https://bankrot.fedresurs.ru/")))
    return {
        "parsing": "разбора нет: проба ищет адреса карточки сообщения и списка торгов",
        "message_guid": message_guid,
        "message_page": page,
        "by_debtor": by_debtor,
        "message_candidates": message,
        "bundles": bundles,
    }


def probe() -> dict[str, Any]:
    """Что отвечает ЕФРСБ по каждому кандидату. Разбора здесь нет намеренно.

    Проба существует, чтобы ПОКАЗАТЬ ответ. Догадка, названная вслух и
    проверенная, — это работа; догадка, оформленная как разбор, — это то, из-за
    чего ГИС Торги приехали на прод с гаражами.
    """
    context = trust_context()
    return {
        "host": HOST,
        "extra_ca": trust_report(),
        "parsing": "разбора нет: ни одно имя поля не сверено ответом сервиса",
        "why": ("ГИС Торги отдают приватизацию госимущества (178-ФЗ); "
                "банкротные лоты — 44% рынка владельца — там не найдены"),
        "attempts": [{"name": name, **_fetch(url, context)} for name, url in CANDIDATES],
        "captcha_note": ("корень отдаёт 401 с капчей Qrator: машинному клиенту "
                         "закрыто. Обход капчи не делаем — от этого она и "
                         "поставлена; смотрим браузером через "
                         "/auctions/fedresurs/browser"),
    }
