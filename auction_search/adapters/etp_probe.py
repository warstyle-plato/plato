"""Площадки банкротства — проба перед разбором.

ЕФРСБ как агрегатор закрыт: простым запросом капча Qrator, живым браузером
403 без единого запроса за данными (ответы с ядра 25–26.08.2026). Обходить
защиту от роботов мы не будем — от этого она и поставлена.

Значит читаем сами площадки. По таблице владельца (372 лота с исходом,
25.08.2026) банкротные лоты сконцентрированы: из 81 лота на чужих площадках
пять адресов дают больше половины — Сбербанк-АСТ 17, ЭТП ГПБ 13, Фабрикант 9,
Альфалот 8, ЭТП РФ 7. Дороже в поддержке, чем один агрегатор, зато не зависит
ни от чьей капчи и ни от какого договора.

## Чего здесь нет и не будет, пока не увидим ответ

Разбора. Ни имён полей, ни кодов, ни оболочки. Проба ходит с ядра и ПОКАЗЫВАЕТ
ответ — код, тип содержимого, начало тела, верхние ключи, если это JSON.

Это не осторожность, а вывод из своей же ошибки: у ГИС Торгов разбор был
написан по догадке и включён, живой ответ опроверг почти каждое имя поля, а сам
источник оказался про другой рынок — и выяснилось это у владельца на экране,
тридцатью гаражами по 0,2 млн ₽.

Запуск с ядра:

    curl -s 'http://127.0.0.1:8080/auctions/etp/probe' | head -c 4000
"""

from __future__ import annotations

import json
import ssl
import urllib.error
import urllib.request
from typing import Any

from auction_search.adapters.browser_probe import probe_browser
from auction_search.adapters.torgi_gov import trust_context

USER_AGENT = "DevelopAid-AuctionCollector/0.1 (+https://developaid.ru)"
TIMEOUT_SECONDS = 12
_BODY_SHOWN = 700

# Адреса-кандидаты по площадкам. Ни один НЕ сверен ответом: это то, что проба
# спрашивает, а не то, что мы знаем. Каждый печатается вместе с кодом ответа —
# «спросили вот это, пришло вот такое».
PLATFORMS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("Сбербанк-АСТ", (
        "https://utp.sberbank-ast.ru/Bankruptcy/List/PurchaseList",
        "https://utp.sberbank-ast.ru/",
    )),
    ("ЭТП ГПБ", (
        "https://etpgpb.ru/procedures/",
        "https://etpgpb.ru/",
    )),
    ("Фабрикант", (
        "https://www.fabrikant.ru/trades/",
        "https://www.fabrikant.ru/",
    )),
    ("Альфалот", (
        "https://bankrupt.alfalot.ru/public/auctions/lots/",
        "https://bankrupt.alfalot.ru/",
    )),
    ("ЭТП РФ", (
        "https://sale.etprf.ru/",
    )),
)


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
            answer: dict[str, Any] = {
                "url": url,
                "http_status": int(getattr(response, "status", 0) or 0),
                "content_type": response.headers.get("Content-Type", ""),
                "bytes": len(raw),
                "body_head": body[:_BODY_SHOWN],
            }
    except urllib.error.HTTPError as exc:
        # Код ответа — это ответ, а не отказ: 404 отличает «не тот адрес» от
        # «сервис закрыт», и путать их нельзя.
        return {"url": url, "http_status": exc.code, "reason": str(exc),
                "body_head": exc.read(2000).decode("utf-8", "replace")[:_BODY_SHOWN]}
    except Exception as exc:  # noqa: BLE001
        return {"url": url, "reason": f"{type(exc).__name__}: {exc}"}
    # Разбираем ровно настолько, чтобы стала видна форма ответа. Имена полей не
    # угадываем: их покажет сам ответ.
    text = answer["body_head"].lstrip()
    if "json" in answer["content_type"].lower() or text[:1] in "{[":
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
    # Признаки защиты от роботов называем вслух: 200 со страницей проверки —
    # это отказ, а не данные, и считать его успехом значит выдать отказ за
    # пустой источник.
    lowered = answer["body_head"].lower()
    answer["challenge"] = any(mark in lowered for mark in (
        "__qrator", "qauth_show_captcha", "ddos-guard", "cf-browser-verification",
        "captcha", "проверка браузера"))
    return answer


def probe() -> dict[str, Any]:
    """Что отвечает каждая площадка. Разбора здесь нет намеренно."""
    context = trust_context()
    return {
        "parsing": "разбора нет: ни одно имя поля не сверено ответом площадки",
        "why": ("ЕФРСБ закрыт капчей и 403 даже браузером; пять площадок из "
                "таблицы владельца дают больше половины банкротных лотов"),
        "platforms": [
            {"name": name, "attempts": [_fetch(url, context) for url in urls]}
            for name, urls in PLATFORMS
        ],
    }


# Короткое имя площадки для адреса запроса. Проба браузером идёт по одной
# площадке за вызов: пять по сорок пять секунд не уложатся ни в один шлюз, а
# ответ, не дошедший до человека, — это ответ, которого нет.
SLUGS: dict[str, str] = {
    "sberbank-ast": "Сбербанк-АСТ",
    "etpgpb": "ЭТП ГПБ",
    "fabrikant": "Фабрикант",
    "alfalot": "Альфалот",
    "etprf": "ЭТП РФ",
}


def platform_urls(slug: str) -> tuple[str, ...]:
    name = SLUGS.get(str(slug or "").strip().lower())
    if not name:
        return ()
    for known, urls in PLATFORMS:
        if known == name:
            return urls
    return ()


def probe_browser_platform(slug: str, seconds: float = 40.0) -> dict[str, Any]:
    """Открыть каталог одной площадки браузером и показать, за чем она ходит.

    Простой запрос показывает только оболочку: у этих площадок каталог рисует
    приложение, а числа приезжают отдельными вызовами бэкенда. Их адреса и
    нужны, чтобы написать читателя — не угаданные, а увиденные.

    Разбора здесь по-прежнему нет и не будет, пока ответ не увиден: у ГИС
    Торгов он был написан по догадке, и это кончилось тридцатью гаражами на
    экране владельца.
    """
    name = SLUGS.get(str(slug or "").strip().lower())
    if not name:
        return {"ok": False, "reason": f"неизвестная площадка: {slug!r}",
                "known": sorted(SLUGS)}
    urls = platform_urls(slug)
    if not urls:
        return {"ok": False, "platform": name, "reason": "адрес каталога не задан"}
    got = probe_browser(urls[0], seconds=seconds)
    got["platform"] = name
    got["parsing"] = "разбора нет: ни одно имя поля не сверено ответом площадки"
    return got
