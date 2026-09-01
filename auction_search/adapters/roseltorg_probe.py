"""Раздел «Развитие территории» Росэлторга — проба перед разбором.

Владелец прислал адрес каталога (01.09.2026):

    https://www.roseltorg.ru/imuschestvo/prochee/razvitie-territorii
        ?sale=5&okato[]=45000000000&status[]=5&status[]=0&status[]=1

и один живой лот на экране: аукцион на право заключения договора о КРТ
нежилой застройки города Москвы, 14,62 га, 2 403 657 113,51 ₽, заявки до
21.09.26, организатор — Департамент города Москвы по конкурентной политике.

Наш читатель этот раздел не спрашивает вовсе. Разведка Росэлторга ходит
только в поиск процедур по тегам (`/procedures/search?tags[]=…`,
`RoseltorgAdapter.DISCOVERY_TAGS`) — это утверждение о НАШЕМ коде, и его
видно в нём самом. Чем отвечает раздел имущества, мы не знаем, и пока не
увидим ответ, разбора здесь не будет.

## Почему не «просто написать парсер»

У ГИС Торгов разбор был написан по догадке и включён: живой ответ опроверг
почти каждое имя поля, а сам источник оказался про другой рынок — выяснилось
это у владельца на экране, тридцатью гаражами по 0,2 млн ₽.

## Контрольный запрос обязателен

Рядом с новым адресом проба спрашивает НЫНЕШНИЙ путь разведки. «Раздел
отвечает» и «раздел отвечает лучше нынешнего» — разные утверждения, и второе
без контрольного запроса не проверяется: у ГИС Торгов параметр региона не
фильтровал, а выдачу МЕНЯЛ, и понять это можно было только сравнением с
запросом без него.

## Запуск с ядра

Из песочницы roseltorg.ru закрыт (403 на CONNECT у шлюза, 01.09.2026), как
НСПД и torgi.gov.ru, поэтому проба ходит только с ядра:

    curl -s 'http://127.0.0.1:8080/auctions/roseltorg/probe' | head -c 6000

Если раздел окажется SPA — данные приезжают отдельными вызовами, и адреса
этих вызовов покажет браузерная проба:

    curl -s 'http://127.0.0.1:8080/auctions/roseltorg/browser' | head -c 6000
"""

from __future__ import annotations

import re
import ssl
import urllib.error
import urllib.request
from html.parser import HTMLParser
from typing import Any
from urllib.parse import urljoin, urlparse

from auction_search.adapters.browser_probe import (
    CHALLENGE_MARKERS,
    probe_browser,
)
from auction_search.adapters.roseltorg import RoseltorgAdapter
from trusted_roots import trust_context

USER_AGENT = "DevelopAid-AuctionCollector/0.1 (+https://developaid.ru)"
TIMEOUT_SECONDS = 25
_TEXT_SHOWN = 900
_LINKS_SHOWN = 12

# Адрес владельца целиком, вместе с его фильтрами. Разбирать их со слов мы не
# будем: что значит `sale=5` и что значат статусы, скажет сравнение выдач, а
# не наша догадка о смысле чужого параметра.
OWNER_URL = (
    "https://www.roseltorg.ru/imuschestvo/prochee/razvitie-territorii"
    "?sale=5&okato%5B%5D=45000000000&status%5B%5D=5&status%5B%5D=0&status%5B%5D=1&page=1"
)

# Что спрашиваем и зачем. Подпись — часть ответа: без неё в отчёте окажутся
# шесть адресов, и чем они отличаются, придётся вспоминать.
SECTIONS: tuple[tuple[str, str], ...] = (
    ("Адрес владельца целиком", OWNER_URL),
    ("Тот же раздел без фильтров — сколько там всего",
     "https://www.roseltorg.ru/imuschestvo/prochee/razvitie-territorii"),
    ("Раздел без фильтра Москвы — влияет ли okato вообще",
     "https://www.roseltorg.ru/imuschestvo/prochee/razvitie-territorii?sale=5"),
    ("Родительский раздел имущества — что ещё рядом",
     "https://www.roseltorg.ru/imuschestvo/prochee"),
    # Контроль: наш нынешний путь разведки. Без него «раздел работает» нечем
    # сравнить с «а как сейчас».
    ("КОНТРОЛЬ: нынешняя разведка, поиск по тегу «комплексное развитие»",
     RoseltorgAdapter._discovery_url("комплексное развитие")),
    ("КОНТРОЛЬ: нынешняя разведка, поиск по тегу «земельный участок»",
     RoseltorgAdapter._discovery_url("земельный участок")),
)


class _Page(HTMLParser):
    """Что на странице есть: видимый текст, ссылки, заголовок, счётчик скриптов."""

    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []
        self.links: list[tuple[str, str]] = []
        self.title = ""
        self.scripts = 0
        self._href: str | None = None
        self._anchor: list[str] = []
        self._in_title = False
        self._skip = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        low = tag.lower()
        if low == "a":
            self._href = dict(attrs).get("href")
            self._anchor = []
        elif low == "title":
            self._in_title = True
        elif low == "script":
            self.scripts += 1
            self._skip += 1
        elif low == "style":
            self._skip += 1

    def handle_data(self, data: str) -> None:
        if self._in_title:
            self.title += data
            return
        if self._skip:
            return
        value = data.strip()
        if not value:
            return
        self.parts.append(value)
        if self._href is not None:
            self._anchor.append(value)

    def handle_endtag(self, tag: str) -> None:
        low = tag.lower()
        if low == "a" and self._href is not None:
            self.links.append((self._href, " ".join(" ".join(self._anchor).split())))
            self._href = None
            self._anchor = []
        elif low == "title":
            self._in_title = False
        elif low in ("script", "style") and self._skip:
            self._skip -= 1

    @property
    def text(self) -> str:
        return " ".join(" ".join(self.parts).split())


def _lot_links(base_url: str, links: list[tuple[str, str]]) -> dict[str, Any]:
    """Ссылки, похожие на лот, и ссылки раздела — раздельно.

    Разделено намеренно: `/procedure/` — то, что наш читатель умеет открывать
    сегодня, а всё прочее — то, чего он не умеет. Одним списком это не видно.
    """
    procedures: list[dict[str, str]] = []
    others: list[dict[str, str]] = []
    seen: set[str] = set()
    for href, anchor in links:
        absolute = urljoin(base_url, href or "")
        parsed = urlparse(absolute)
        host = (parsed.hostname or "").lower()
        if not (host == "roseltorg.ru" or host.endswith(".roseltorg.ru")):
            continue
        if absolute in seen:
            continue
        seen.add(absolute)
        row = {"url": absolute, "anchor": anchor[:160]}
        if re.match(r"^/procedure/", parsed.path):
            procedures.append(row)
        elif re.search(r"/(?:lot|lots|imuschestvo|trade|auction)/", parsed.path):
            others.append(row)
    return {
        "procedure_links": len(procedures),
        "procedure_sample": procedures[:_LINKS_SHOWN],
        "other_lot_like_links": len(others),
        "other_sample": others[:_LINKS_SHOWN],
    }


def _challenge(body: str) -> list[str]:
    low = body.lower()
    return [mark for mark in CHALLENGE_MARKERS if mark.lower() in low]


def _fetch(url: str, context: ssl.SSLContext) -> dict[str, Any]:
    request = urllib.request.Request(url, headers={
        "User-Agent": USER_AGENT,
        "Accept": "text/html,application/xhtml+xml,application/json;q=0.8",
        "Accept-Language": "ru-RU,ru;q=0.9",
    })
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS,
                                    context=context) as response:
            raw = response.read()
            charset = response.headers.get_content_charset() or "utf-8"
            status = response.status
            content_type = response.headers.get("Content-Type", "")
    except urllib.error.HTTPError as exc:
        raw = exc.read()[:20_000]
        charset = "utf-8"
        status = exc.code
        content_type = exc.headers.get("Content-Type", "") if exc.headers else ""
    except Exception as exc:  # noqa: BLE001
        # Причина называется целиком: «сертификат не проверился» и «хост
        # закрыт» читаются одинаково, а лечатся по-разному.
        return {"reason": f"{type(exc).__name__}: {exc}"}

    body = raw.decode(charset, errors="replace")
    page = _Page()
    page.feed(body)
    text = page.text
    report: dict[str, Any] = {
        "http_status": status,
        "content_type": content_type,
        "bytes": len(raw),
        "title": " ".join(page.title.split())[:160],
        "scripts": page.scripts,
        "visible_text_chars": len(text),
        "text_head": text[:_TEXT_SHOWN],
    }
    report.update(_lot_links(url, page.links))
    challenge = _challenge(body)
    if challenge:
        # 200 со страницей проверки браузера — отказ, а не пустой раздел.
        report["challenge"] = challenge
    # Признак оболочки SPA: скриптов много, видимого текста почти нет. Это
    # подсказка для человека, а не вывод: решает браузерная проба.
    report["looks_like_spa"] = page.scripts >= 3 and len(text) < 400
    return report


def probe(directory: str = "") -> dict[str, Any]:
    """Чем отвечает раздел имущества и чем — нынешняя разведка. Разбора нет."""
    context = trust_context(directory)
    attempts = []
    for label, url in SECTIONS:
        attempts.append({"asked": label, "url": url, **_fetch(url, context)})
    return {
        "source": "Росэлторг",
        "parsing": ("разбора нет: сначала ответ источника, потом код. "
                    "Раздел «Развитие территории» наш читатель сегодня не "
                    "спрашивает вовсе — разведка ходит только в поиск по тегам."),
        "today_discovery": {
            "url_shape": RoseltorgAdapter.SEARCH_URL + "?tags[]=…",
            "tags": list(RoseltorgAdapter.DISCOVERY_TAGS),
            "max_pages": RoseltorgAdapter.DISCOVERY_MAX_PAGES,
        },
        "attempts": attempts,
    }


def probe_section_browser(url: str = "", seconds: float = 45.0,
                          save_to: str = "") -> dict[str, Any]:
    """Тот же раздел живым браузером — и адреса, по которым он берёт данные.

    Своей пробы здесь не заводим: она объявлена один раз в `browser_probe`, и
    вторая копия разошлась бы с первой на признаках отказа.
    """
    return probe_browser(url.strip() or OWNER_URL, seconds=seconds, save_to=save_to)
