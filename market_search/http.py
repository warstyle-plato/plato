from __future__ import annotations

import ipaddress
import json
import os
import socket
import tempfile
import time
import hashlib
import stat
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode, urlsplit, urlunsplit
from urllib.request import Request, urlopen
from . import krt_catalogue_observation as _krt_observation

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
    try:
        observer = _krt_observation.current_fetch()
    except Exception:
        observer = None
    if observer is not None:
        return _request_bytes_observed(observer, url, params=params, data=data, method=method,
            timeout=timeout, retries=retries, headers=headers)
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


def _request_bytes_observed(observer, url, *, params, data, method, timeout, retries, headers):
    """The same urllib calls/policy, with best-effort passive metadata only."""
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
    _krt_observation.note(observer, 'context_start')
    try:
        context = _trust_context() if _trust_context is not None else None
    except Exception as exc:
        _krt_observation.note(observer, 'failure', exc, 'tls_context_setup')
        raise
    last_error: Exception | None = None
    for attempt in range(retries + 1):
        boundary = 'open_response'
        _krt_observation.note(observer, 'attempt_start', attempt + 1)
        try:
            req = Request(url, data=data, headers=request_headers, method=method)
            with urlopen(req, timeout=timeout, context=context) as response:
                _krt_observation.note(observer, 'response', response)
                boundary = 'body'
                body = response.read()
                _krt_observation.note(observer, 'body', body)
                return body
        except (HTTPError, URLError, TimeoutError, socket.timeout) as exc:
            _krt_observation.note(observer, 'failure', exc, boundary)
            last_error = exc
            if attempt < retries:
                time.sleep(min(2.0 ** attempt, 4.0))
        except Exception as exc:
            _krt_observation.note(observer, 'failure', exc, boundary)
            raise
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


def save_json(path: Path, payload: Any, *, _saved_receipt: dict | None = None) -> None:
    if type(_saved_receipt) is dict:
        return _save_json_observed(path, payload, _saved_receipt)
    path.parent.mkdir(parents=True, exist_ok=True)
    # Два воркера могут одновременно обновлять один каталог. Общий .tmp
    # позволял одному переименовать файл, в который другой ещё пишет.
    tmp: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=path.parent,
            prefix=f".{path.name}.", suffix=".tmp", delete=False,
        ) as fh:
            tmp = Path(fh.name)
            json.dump(payload, fh, ensure_ascii=False, separators=(",", ":"))
        tmp.replace(path)
    finally:
        if tmp is not None:
            tmp.unlink(missing_ok=True)


class _HashingJSONWriter:
    def __init__(self, stream):
        self.stream = stream
        self.digest = hashlib.sha256()
        self.count = 0
        self.valid = True

    def write(self, text):
        result = self.stream.write(text)
        try:
            if type(result) is not int or result != len(text):
                self.valid = False
            raw = text.encode('utf-8')
            self.digest.update(raw)
            self.count += len(raw)
        except Exception:
            self.valid = False
        return result


def _save_json_observed(path, payload, receipt):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp: Path | None = None
    writer = initial = saved = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=path.parent,
            prefix=f".{path.name}.", suffix=".tmp", delete=False,
        ) as fh:
            tmp = Path(fh.name)
            try: initial = os.fstat(fh.fileno())
            except Exception: pass
            try: writer = _HashingJSONWriter(fh)
            except Exception: pass
            json.dump(payload, writer if writer is not None else fh, ensure_ascii=False, separators=(",", ":"))
        try:
            saved = tmp.stat(follow_symlinks=False)
        except Exception:
            pass
        tmp.replace(path)
        try: receipt['_replaced'] = True
        except Exception: pass
        try:
            final = path.stat(follow_symlinks=False)
            if (writer is not None and writer.valid and initial is not None and saved is not None
                    and stat.S_ISREG(saved.st_mode) and saved.st_nlink == 1
                    and (initial.st_dev, initial.st_ino) == (saved.st_dev, saved.st_ino)
                    and (saved.st_dev, saved.st_ino, saved.st_size, saved.st_mtime_ns)
                    == (final.st_dev, final.st_ino, final.st_size, final.st_mtime_ns)
                    and saved.st_size == writer.count):
                receipt.update(written_payload_sha256=writer.digest.hexdigest(), written_bytes=writer.count,
                    inode=saved.st_ino, mtime_ns=saved.st_mtime_ns)
        except Exception:
            pass
    finally:
        if tmp is not None:
            tmp.unlink(missing_ok=True)


def fresh(path: Path, ttl_seconds: int) -> bool:
    try:
        return time.time() - path.stat().st_mtime <= ttl_seconds
    except OSError:
        return False


def public_url_problem(url: str) -> str:
    """Почему по этому адресу пробе ходить нельзя; пусто — можно.

    Пробы открывают адрес, присланный в запросе, и показывают ответ. Без этой
    проверки они читали бы то, что видно только изнутри сервера: служебные
    маршруты на localhost, метаданные облака (169.254.169.254), соседние машины
    сети. Пускаем только https на публичный адрес, без логина в адресе.
    """
    try:
        parts = urlsplit(str(url or "").strip())
        port = parts.port
    except ValueError:
        return "адрес не разбирается"
    if parts.scheme != "https":
        return "проба открывает только адреса https://"
    if parts.username or parts.password:
        return "в адресе не должно быть логина и пароля"
    host = parts.hostname or ""
    if not host:
        return "в адресе нет имени сервера"
    try:
        infos = socket.getaddrinfo(host, port or 443, proto=socket.IPPROTO_TCP)
    except OSError:
        return f"имя сервера {host} не разрешается"
    for info in infos:
        address = ipaddress.ip_address(info[4][0].split("%", 1)[0])
        if not address.is_global:
            return f"{host} ведёт во внутреннюю сеть ({address}) — туда проба не ходит"
    return ""

