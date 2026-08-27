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
import os
import ssl
import urllib.error
import urllib.request
from typing import Any

from auction_search.adapters.browser_probe import probe_browser
from auction_search.adapters.torgi_gov import EXTRA_CA_DIR, trust_context

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
        # «сервис закрыт», и путать их нельзя. Чем мы представились — часть
        # ответа: половина защит режет незнакомый User-Agent, и 403 роботу
        # неотличим от 403 всем, пока имя клиента не названо рядом.
        return {"url": url, "http_status": exc.code, "reason": str(exc),
                "user_agent": USER_AGENT,
                "hint": _refusal_hint(exc.code),
                "body_head": exc.read(2000).decode("utf-8", "replace")[:_BODY_SHOWN]}
    except Exception as exc:  # noqa: BLE001
        answer = {"url": url, "user_agent": USER_AGENT,
                  "reason": f"{type(exc).__name__}: {exc}"}
        if "CERTIFICATE_VERIFY_FAILED" in str(exc):
            # Проверку не выключаем — от неё и толк. Издателя спрашивают у
            # самого сертификата (поле Authority Information Access) и кладут
            # в каталог корней; так уже чинилась ГИС Торги. Сервер часто
            # присылает только свой лист, а промежуточный по ссылке AIA
            # Python сам не забирает — в отличие от браузера.
            answer["hint"] = (
                "цепочка не проверилась: положите издателя в каталог корней "
                f"({EXTRA_CA_DIR}) — адрес издателя стоит в самом сертификате, "
                "поле Authority Information Access. Проверку не отключаем.")
        return answer
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


def _refusal_hint(status: int) -> str:
    """Отказ роботу и отказ вообще выглядят одинаково — пока не назвать разницу."""
    if status == 403:
        return ("отказ может быть нам как роботу: мы стучимся своим User-Agent. "
                "Различит браузерная проба — она идёт настоящим Chromium.")
    if status == 429:
        return ("лимит запросов — на первом же обращении. Либо жёсткий лимит по "
                "адресу, либо тот же отказ роботу, только другим кодом.")
    if status == 404:
        return "адрес не тот; сам сервис при этом отвечает"
    return ""


def summary(report: dict[str, Any]) -> list[dict[str, Any]]:
    """Строка на площадку — чтобы ответ помещался на экран.

    Подробности каждой попытки занимают по семьсот знаков каркаса, и вывод,
    обрезанный на второй площадке из пяти, — это ответ, которого нет: так уже
    вышло 27.08.2026.
    """
    out: list[dict[str, Any]] = []
    for platform in report.get("platforms") or []:
        best: dict[str, Any] = {}
        for attempt in platform.get("attempts") or []:
            if attempt.get("http_status") == 200:
                best = attempt
                break
            best = best or attempt
        out.append({
            "platform": platform.get("name"),
            "url": best.get("url"),
            "http_status": best.get("http_status"),
            "content_type": str(best.get("content_type") or "")[:40],
            "challenge": best.get("challenge"),
            "reason": str(best.get("reason") or "")[:120],
            "hint": best.get("hint") or "",
        })
    return out


def probe() -> dict[str, Any]:
    """Что отвечает каждая площадка. Разбора здесь нет намеренно."""
    context = trust_context()
    report: dict[str, Any] = {
        "parsing": "разбора нет: ни одно имя поля не сверено ответом площадки",
        "why": ("ЕФРСБ закрыт капчей и 403 даже браузером; пять площадок из "
                "таблицы владельца дают больше половины банкротных лотов"),
        "platforms": [
            {"name": name, "attempts": [_fetch(url, context) for url in urls]}
            for name, urls in PLATFORMS
        ],
    }
    # Сводка стоит ПЕРВОЙ: за ней и приходят, а подробности читают следом.
    return {"summary": summary(report), **report}


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


PAGES_DIR = os.environ.get("DEVELOPAID_ETP_PAGES_DIR", "data/etp_pages")


def probe_browser_platform(slug: str, seconds: float = 40.0, save: bool = False,
                           url: str = "") -> dict[str, Any]:
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
    # Адрес можно задать руками: наш сохранённый ведёт куда придётся, и это
    # видно только по ответу. У Сбербанк-АСТ 27.08.2026 каталог банкротства
    # увёл редиректом на главную, и все вызовы оказались вызовами главной.
    target = str(url or "").strip()
    if target and not target.lower().startswith("https://"):
        return {"ok": False, "platform": name,
                "reason": "адрес должен начинаться с https://"}
    if not target:
        urls = platform_urls(slug)
        if not urls:
            return {"ok": False, "platform": name, "reason": "адрес каталога не задан"}
        target = urls[0]
    got = probe_browser(
        target, seconds=seconds,
        save_to=os.path.join(PAGES_DIR, f"{slug}.html") if save else "")
    got["platform"] = name
    got["asked"] = target
    got["parsing"] = "разбора нет: ни одно имя поля не сверено ответом площадки"
    return got
