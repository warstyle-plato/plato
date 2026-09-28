"""Страница площадки целиком — образец для разбора, снятый с ядра.

Разбор даты торгов у Росэлторга, lot-online и ГПБ пишется по живой странице,
а не по догадке о ней, и проверяется ею же как фикстурой. Из песочницы эти
площадки закрыты (соединение рвётся на их стороне), а проба Росэлторга отдаёт
только первые `_TEXT_SHOWN` символов текста — подпись даты торгов в карточке
стоит дальше. Здесь та же проба без обрезки текста: ответ площадки как есть.

Ограничения те же, что у пробы: только официальные хосты площадок
(`ALLOWED_HOSTS`), никакого разбора, размер ответа ограничен `MAX_BYTES`, и
обрезка называется в ответе (`truncated`), а не проходит молча.
"""

from __future__ import annotations

import urllib.error
import urllib.request
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlparse

from trusted_roots import trust_context

USER_AGENT = "DevelopAid-AuctionCollector/0.1 (+https://developaid.ru)"
TIMEOUT_SECONDS = 25
MAX_BYTES = 3_000_000

# Площадки, чьи страницы нужны разбору даты торгов (вариант Б). Хост сверяется
# целиком или как поддомен: `evil-roseltorg.ru` сюда не проходит.
ALLOWED_HOSTS = ("roseltorg.ru", "lot-online.ru", "etpgpb.ru")


def allowed(url: str) -> bool:
    """Официальный ли это хост площадки и обычный ли протокол."""
    parsed = urlparse(url or "")
    if parsed.scheme not in {"http", "https"}:
        return False
    host = (parsed.hostname or "").lower()
    return any(host == name or host.endswith("." + name) for name in ALLOWED_HOSTS)


class _StayOnPlatform(urllib.request.HTTPRedirectHandler):
    """Редирект только на тот же круг хостов: иначе разрешённый адрес мог бы
    увести запрос ядра куда угодно, включая его собственную сеть."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: D102
        if not allowed(newurl):
            raise urllib.error.HTTPError(
                newurl, code, f"редирект с площадки на чужой адрес: {newurl}",
                headers, fp)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def fetch(url: str, directory: str = "") -> dict[str, Any]:
    """Ответ площадки целиком: статус, тип, тело и момент снятия."""
    url = (url or "").strip()
    if not allowed(url):
        return {"url": url, "reason": ("адрес не с официального хоста площадки: "
                                       + ", ".join(ALLOWED_HOSTS))}
    request = urllib.request.Request(url, headers={
        "User-Agent": USER_AGENT,
        "Accept": "text/html,application/xhtml+xml,application/json;q=0.8",
        "Accept-Language": "ru-RU,ru;q=0.9",
    })
    fetched_at = datetime.now(timezone.utc).isoformat()
    try:
        opener = urllib.request.build_opener(
            urllib.request.HTTPSHandler(context=trust_context(directory)),
            _StayOnPlatform())
        with opener.open(request, timeout=TIMEOUT_SECONDS) as response:
            raw = response.read(MAX_BYTES + 1)
            charset = response.headers.get_content_charset() or "utf-8"
            status = response.status
            content_type = response.headers.get("Content-Type", "")
            final_url = response.geturl()
    except urllib.error.HTTPError as exc:
        raw = exc.read(MAX_BYTES + 1)
        charset = "utf-8"
        status = exc.code
        content_type = exc.headers.get("Content-Type", "") if exc.headers else ""
        final_url = url
    except Exception as exc:  # noqa: BLE001
        # Причина целиком: «сертификат не проверился» и «хост закрыт» лечатся
        # по-разному, а «не получилось» не лечится никак.
        return {"url": url, "fetched_at": fetched_at,
                "reason": f"{type(exc).__name__}: {exc}"}
    truncated = len(raw) > MAX_BYTES
    raw = raw[:MAX_BYTES]
    return {
        "url": url,
        "final_url": final_url,
        "fetched_at": fetched_at,
        "http_status": status,
        "content_type": content_type,
        "bytes": len(raw),
        "truncated": truncated,
        "body": raw.decode(charset, errors="replace"),
    }
