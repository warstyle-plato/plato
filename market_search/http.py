from __future__ import annotations

import json
import os
import socket
import time
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode, urlsplit, urlunsplit
from urllib.request import Request, urlopen

# Наши добавочные корни. Объявлены один раз (`trusted_roots`) и общие с
# адаптером ГИС Торгов: без них прямое чтение krt.mos.ru падает на проверке
# сертификата ВСЕГДА, и каталог города целиком приезжает запасным путём — а у
# того от разметки карточки не остаётся структуры. Проверка при этом остаётся
# включённой: выключенная молча принимает любой сертификат.
try:  # модуль рынка поднимается и отдельно от движка
    from trusted_roots import trust_context as _trust_context
except ImportError:  # pragma: no cover - вне сборки движка
    _trust_context = None


class RemoteServiceError(RuntimeError):
    pass


_USER_AGENT = os.getenv(
    "MARKET_HTTP_USER_AGENT",
    "DevelopAid-Market-Discovery/0.2 (+https://developaid.ru)",
)


def _ascii_url(url: str) -> str:
    parts = urlsplit(url)
    host = parts.hostname.encode("idna").decode("ascii") if parts.hostname else ""
    netloc = host
    if parts.port:
        netloc += f":{parts.port}"
    path = quote(parts.path, safe="/%:@")
    return urlunsplit((parts.scheme, netloc, path, parts.query, parts.fragment))


def request_bytes(
    url: str,
    *,
    params: dict[str, Any] | None = None,
    data: bytes | None = None,
    method: str | None = None,
    timeout: float = 30.0,
    retries: int = 2,
    headers: dict[str, str] | None = None,
) -> bytes:
    if params:
        query = urlencode({k: v for k, v in params.items() if v is not None})
        url = f"{url}{'&' if '?' in url else '?'}{query}"
    url = _ascii_url(url)
    request_headers = {
        "User-Agent": _USER_AGENT,
        "Accept-Language": "ru-RU,ru;q=0.9",
    }
    if headers:
        request_headers.update(headers)

    # Контекст собирается на каждый запрос: положенный на машину корень
    # начинает работать без выкатки — так же, как у адаптера торгов.
    context = _trust_context() if _trust_context is not None else None

    last_error: Exception | None = None
    for attempt in range(retries + 1):
        try:
            req = Request(url, data=data, headers=request_headers, method=method)
            with urlopen(req, timeout=timeout, context=context) as response:
                return response.read()
        except (HTTPError, URLError, TimeoutError, socket.timeout) as exc:
            last_error = exc
            if attempt < retries:
                time.sleep(min(2.0 ** attempt, 4.0))
    raise RemoteServiceError(f"Не удалось получить ответ от {url}: {last_error}") from last_error


def get_json(
    url: str,
    *,
    params: dict[str, Any] | None = None,
    timeout: float = 30.0,
    retries: int = 2,
    headers: dict[str, str] | None = None,
) -> Any:
    body = request_bytes(
        url,
        params=params,
        timeout=timeout,
        retries=retries,
        headers={"Accept": "application/json, text/plain, */*", **(headers or {})},
    )
    try:
        return json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RemoteServiceError(f"Сервис вернул не JSON: {url}") from exc


def load_json(path: Path) -> Any | None:
    try:
        with path.open("r", encoding="utf-8") as fh:
            return json.load(fh)
    except (FileNotFoundError, OSError, json.JSONDecodeError):
        return None


def save_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, separators=(",", ":"))
    tmp.replace(path)


def fresh(path: Path, ttl_seconds: int) -> bool:
    try:
        return time.time() - path.stat().st_mtime <= ttl_seconds
    except OSError:
        return False
