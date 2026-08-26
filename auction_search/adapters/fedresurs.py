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
"""

from __future__ import annotations

import json
import ssl
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

from auction_search.adapters.torgi_gov import trust_context, trust_report

HOST = "bankrot.fedresurs.ru"
USER_AGENT = "DevelopAid-AuctionCollector/0.1 (+https://developaid.ru)"
TIMEOUT_SECONDS = 12

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
QRATOR_MARKERS = ("__qrator", "qauth_show_captcha", "qauth_utm")


def probe_browser(url: str = SEARCH_PAGE, seconds: float = 45.0) -> dict[str, Any]:
    """Открывает страницу настоящим браузером и показывает, что она загрузила.

    Это не обход защиты: мы действительно открываем страницу браузером, тем же
    Chromium, которым считается калькулятор ГлавАПУ. Капчу, если она появится,
    проба назовёт вслух — решать её за человека мы не станем.

    Главное здесь — не текст страницы, а СПИСОК ЗАПРОСОВ, которые она сделала:
    у SPA данные приезжают отдельными вызовами бэкенда, и именно их адреса нам
    и нужны. Гадать имена путей мы уже пробовали — вышли гаражи.
    """
    try:
        from playwright.sync_api import sync_playwright
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "url": url, "reason": f"Playwright недоступен: {exc}"}
    import browser_launch

    calls: list[dict[str, Any]] = []
    report: dict[str, Any] = {"ok": False, "url": url, "how": "", "calls": calls}

    def remember(response: Any) -> None:
        try:
            request = response.request
            if request.resource_type not in ("xhr", "fetch"):
                return
            calls.append({
                "method": request.method,
                "url": request.url[:400],
                "status": response.status,
                "content_type": (response.header_value("content-type") or "")[:80],
            })
        except Exception:  # noqa: BLE001
            # Один непрочитанный ответ не отменяет пробу.
            pass

    try:
        with sync_playwright() as playwright:
            browser = browser_launch.launch(playwright)
            report["how"] = str(browser_launch.LAST_LAUNCH.get("how") or "")
            try:
                page = browser.new_page()
                page.set_default_timeout(int(seconds * 1000))
                page.on("response", remember)
                page.goto(url, wait_until="networkidle", timeout=int(seconds * 1000))
                body = page.content()
                # Отказ приходит и в виде страницы: заголовок «403 Forbidden»
                # при `ok: true` — это не загрузившееся приложение, а страница
                # ошибки. Живой ответ с ядра 26.08.2026: браузер получил именно
                # её, без капчи и без единого запроса за данными. Считать это
                # успехом значит выдать отказ за пустой источник.
                title = page.title()
                blocked = any(mark in title for mark in ("403", "401", "Forbidden", "Access denied"))
                report.update({
                    "ok": True,
                    "blocked": blocked,
                    "final_url": page.url,
                    "title": title,
                    "captcha": any(mark in body for mark in QRATOR_MARKERS),
                    "text_head": " ".join(page.inner_text("body").split())[:800],
                })
            finally:
                browser.close()
    except Exception as exc:  # noqa: BLE001
        report["reason"] = f"{type(exc).__name__}: {exc}"
    # Ответы, похожие на данные, — первыми: ради них проба и заводилась.
    report["data_calls"] = [c for c in calls if "json" in c["content_type"].lower()]
    return report


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
