"""Read a public teaser URL into the same document intake as uploaded files.

The downloader owns the network boundary: DNS is checked once per hop, the
socket connects to that checked address, and TLS still verifies the original
hostname. A redirect is another untrusted URL, never an automatic urllib hop.
No ambient proxy credentials, cookies or application authorization are sent.
"""

from __future__ import annotations

import hashlib
import http.client
import ipaddress
import io
import re
import socket
import threading
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import PurePosixPath
from typing import Any
from urllib.parse import quote, unquote, urljoin, urlsplit, urlunsplit

from trusted_roots import trust_context

MAX_BYTES = 20 * 1024 * 1024
MAX_REDIRECTS = 5
_DNS = ThreadPoolExecutor(max_workers=4, thread_name_prefix="document-dns")
_DNS_SLOTS = threading.BoundedSemaphore(8)
_REDIRECTS = {301, 302, 303, 307, 308}
_MIME_EXTENSIONS = {
    "application/pdf": ".pdf", "image/png": ".png", "image/jpeg": ".jpg",
    "text/html": ".html", "application/xhtml+xml": ".html",
}


class DocumentSourceError(ValueError):
    """A public explanation for an unreadable or unsupported source."""

    def __init__(self, message: str, *, code: str = "source_unavailable",
                 status_code: int = 422) -> None:
        super().__init__(message)
        self.code = code
        self.status_code = status_code


def _remaining(deadline: float) -> float:
    left = deadline - time.monotonic()
    if left <= 0:
        raise DocumentSourceError(
            "Время загрузки документа по ссылке истекло. Попробуйте скачать файл и приложить его.",
            code="source_timeout", status_code=504)
    return left


def _is_public(address: str) -> bool:
    try:
        parsed = ipaddress.ip_address(address.split("%", 1)[0])
    except ValueError:
        return False
    if not parsed.is_global or parsed.is_multicast:
        return False
    # Transition addresses must not smuggle an embedded private IPv4 target.
    if isinstance(parsed, ipaddress.IPv6Address):
        embedded = parsed.ipv4_mapped or parsed.sixtofour
        if embedded and (not embedded.is_global or embedded.is_multicast):
            return False
        if parsed.teredo and any(not ip.is_global or ip.is_multicast for ip in parsed.teredo):
            return False
    return True


def _resolve(host: str, deadline: float) -> list[tuple[Any, ...]]:
    # System getaddrinfo has no per-call timeout. Bound the caller's wait and
    # the number of pending resolver jobs, rather than opening unbounded threads.
    if not _DNS_SLOTS.acquire(blocking=False):
        raise DocumentSourceError("Загрузка ссылок занята. Повторите позже или приложите файл.",
                                  code="source_busy", status_code=503)
    try:
        future = _DNS.submit(socket.getaddrinfo, host, 443, type=socket.SOCK_STREAM,
                             proto=socket.IPPROTO_TCP)
    except BaseException:
        _DNS_SLOTS.release()
        raise
    future.add_done_callback(lambda _done: _DNS_SLOTS.release())
    try:
        return future.result(timeout=_remaining(deadline))
    except DocumentSourceError:
        future.cancel()
        raise
    except FutureTimeout as exc:
        future.cancel()
        raise DocumentSourceError("Истекло время поиска сервера документа по ссылке.",
                                  code="source_timeout", status_code=504) from exc
    except OSError as exc:
        raise DocumentSourceError("Не удалось найти сервер по ссылке.",
                                  code="source_dns", status_code=502) from exc


def _target(url: str, deadline: float) -> tuple[str, str, str, tuple[Any, ...]]:
    """Return canonical URL, hostname, request target and checked endpoints."""
    raw = str(url or "").strip()
    if len(raw) > 8192 or any(ord(char) < 32 or ord(char) == 127 for char in raw):
        raise DocumentSourceError("Ссылка слишком длинная или содержит недопустимые символы.",
                                  code="invalid_url", status_code=400)
    try:
        parts = urlsplit(raw)
        port = parts.port
        host = (parts.hostname or "").encode("idna").decode("ascii").lower()
    except (ValueError, UnicodeError) as exc:
        raise DocumentSourceError("Ссылка не разбирается. Укажите полный адрес https://.",
                                  code="invalid_url", status_code=400) from exc
    if (parts.scheme != "https" or not host or parts.username is not None
            or parts.password is not None or port not in (None, 443) or "%" in host
            or "\\" in raw):
        raise DocumentSourceError(
            "Для документа нужна публичная ссылка https:// без логина, пароля и нестандартного порта.",
            code="invalid_url", status_code=400)
    _remaining(deadline)
    endpoints = _resolve(host, deadline)
    _remaining(deadline)
    if not endpoints or any(not _is_public(info[4][0]) for info in endpoints):
        raise DocumentSourceError(
            "Ссылка ведёт во внутреннюю или служебную сеть. Пришлите публичный адрес документа.",
            code="source_private", status_code=400)
    request_target = quote(parts.path or "/", safe="/%:@!$&'()*+,;=-._~")
    if parts.query:
        request_target += "?" + quote(parts.query, safe="/%:@!$&'()*+,;=?-._~")
    authority = f"[{host}]" if ":" in host else host
    canonical = urlunsplit(("https", authority, request_target.split("?", 1)[0],
                           request_target.split("?", 1)[1] if "?" in request_target else "", ""))
    # Prefer IPv4 where both families exist; not all service hosts have IPv6
    # egress. Every returned endpoint has passed the same public-IP check.
    endpoints.sort(key=lambda info: info[0] != socket.AF_INET)
    return canonical, host, request_target, tuple(endpoints)


class _DeadlineRaw(io.RawIOBase):
    """Check the total budget between raw reads, including header/framing reads."""

    def __init__(self, reader: Any, sock: Any, deadline: float) -> None:
        super().__init__()
        self._reader, self._sock, self._deadline = reader, sock, deadline

    def readable(self) -> bool:
        return True

    def readinto(self, buffer: Any) -> int:
        self._sock.settimeout(_remaining(self._deadline))
        data = self._reader.read1(len(buffer))
        _remaining(self._deadline)
        buffer[:len(data)] = data
        return len(data)

    def close(self) -> None:
        try:
            self._reader.close()
        finally:
            super().close()


class _DeadlineResponse(http.client.HTTPResponse):
    def __init__(self, sock: Any, *args: Any, deadline: float, **kwargs: Any) -> None:
        super().__init__(sock, *args, **kwargs)
        # HTTPResponse reads status/header/chunk lines with readline(). Wrapping
        # the stream below its buffering means even one slow line cannot keep
        # resetting a per-recv timeout beyond the request's total deadline.
        self.fp = io.BufferedReader(_DeadlineRaw(self.fp, sock, deadline))


class _PinnedHTTPS(http.client.HTTPSConnection):
    def __init__(self, host: str, endpoints: tuple[Any, ...], timeout: float) -> None:
        super().__init__(host, port=443, timeout=timeout, context=trust_context())
        self._endpoints = endpoints
        self._deadline = time.monotonic() + timeout
        self.response_class = lambda sock, *args, **kwargs: _DeadlineResponse(
            sock, *args, deadline=self._deadline, **kwargs)

    def connect(self) -> None:
        last_error: OSError | None = None
        for family, socktype, proto, _, address in self._endpoints:
            raw = socket.socket(family, socktype, proto)
            try:
                raw.settimeout(_remaining(self._deadline))
                raw.connect(address)
                self.sock = self._context.wrap_socket(raw, server_hostname=self.host)
                return
            except OSError as exc:
                raw.close()
                last_error = exc
            except BaseException:
                raw.close()
                raise
        raise last_error or OSError("No checked endpoint")


def _download(url: str, deadline: float, max_bytes: int) -> tuple[bytes, str, str]:
    current = url
    seen: set[str] = set()
    for hop in range(MAX_REDIRECTS + 1):
        canonical, host, path, endpoint = _target(current, deadline)
        if canonical in seen:
            raise DocumentSourceError("Ссылка зациклилась на перенаправлениях.", code="source_redirect")
        seen.add(canonical)
        connection = _PinnedHTTPS(host, endpoint, _remaining(deadline))
        try:
            connection.request("GET", path, headers={
                "User-Agent": "DevelopAid-Document-Intake/1.0",
                "Accept": "application/pdf,image/png,image/jpeg,text/html;q=0.8",
                "Accept-Encoding": "identity",
                "Connection": "close",
            })
            if connection.sock is not None:
                connection.sock.settimeout(_remaining(deadline))
            response = connection.getresponse()
            if response.status in _REDIRECTS:
                location = response.getheader("Location")
                if not location or hop == MAX_REDIRECTS:
                    raise DocumentSourceError("Слишком много перенаправлений или нет целевого адреса.",
                                              code="source_redirect")
                current = urljoin(canonical, location)
                # Validation happens at the top of the next iteration, before
                # constructing a connection or issuing a request to that host.
                continue
            if response.status in (401, 403):
                raise DocumentSourceError(
                    f"Сервер документа требует входа или запретил доступ (HTTP {response.status}). "
                    "Скачайте файл самостоятельно и приложите его.", code="source_access")
            if response.status != 200:
                raise DocumentSourceError(
                    f"Сервер по ссылке вернул HTTP {response.status}; документ не прочитан.",
                    code="source_http", status_code=502)
            encoding = str(response.getheader("Content-Encoding") or "identity").lower()
            if encoding not in ("identity", ""):
                raise DocumentSourceError("Сервер вернул сжатый ответ вместо файла. Приложите скачанный файл.",
                                          code="source_encoding")
            length = response.getheader("Content-Length")
            if length:
                try:
                    too_large = int(length) < 0 or int(length) > max_bytes
                except ValueError as exc:
                    raise DocumentSourceError("Сервер прислал некорректный размер документа.",
                                              code="source_length") from exc
                if too_large:
                    raise DocumentSourceError("Документ по ссылке больше допустимого размера.",
                                              code="source_size", status_code=413)
            chunks: list[bytes] = []
            size = 0
            while True:
                remaining = _remaining(deadline)
                if connection.sock is not None:
                    connection.sock.settimeout(remaining)
                # HTTPResponse.read(n) may keep receiving until n bytes have
                # accumulated: a trickle can reset the socket timeout many
                # times inside that single call. read1 returns after one
                # buffered/raw read so the total budget is checked again.
                part = response.read1(min(64 * 1024, max_bytes + 1 - size))
                _remaining(deadline)
                if not part:
                    break
                chunks.append(part)
                size += len(part)
                if size > max_bytes:
                    raise DocumentSourceError("Документ по ссылке больше допустимого размера.",
                                              code="source_size", status_code=413)
            if length and size != int(length):
                raise DocumentSourceError("Сервер передал документ не полностью. Приложите скачанный файл.",
                                          code="source_incomplete", status_code=502)
            _remaining(deadline)
            content_type = str(response.getheader("Content-Type") or "").lower()
            return b"".join(chunks), content_type, canonical
        except (TimeoutError, socket.timeout) as exc:
            raise DocumentSourceError(
                "Время загрузки документа по ссылке истекло. Приложите скачанный файл.",
                code="source_timeout", status_code=504) from exc
        except (OSError, http.client.HTTPException) as exc:
            raise DocumentSourceError(
                "Не удалось загрузить документ по ссылке: соединение или проверка сертификата не удались.",
                code="source_connection", status_code=502) from exc
        finally:
            connection.close()
    raise AssertionError("redirect limit handled above")


class _VisibleHTML(HTMLParser):
    _IGNORED = {"script", "style", "nav", "header", "footer", "noscript", "svg", "iframe", "template"}
    _BLOCKS = {"p", "div", "br", "tr", "li", "h1", "h2", "h3", "h4", "section", "article"}
    _VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.stack: list[tuple[str, bool]] = []
        self.hidden = 0
        self.password = False
        self.auth_form = False
        self.meta_redirect = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = dict(attrs)
        if tag == "input" and str(values.get("type") or "").lower() == "password":
            self.password = True
        if tag == "form" and re.search(r"(?:login|signin|sign-in|authorize|/auth(?:/|$))",
                                         str(values.get("action") or ""), re.I):
            self.auth_form = True
        if tag == "meta" and str(values.get("http-equiv") or "").lower() == "refresh":
            self.meta_redirect = True
        ignored = tag in self._IGNORED or "hidden" in values or values.get("aria-hidden") == "true"
        if tag not in self._VOID:
            self.stack.append((tag, ignored))
            if ignored:
                self.hidden += 1
        if not self.hidden and tag in self._BLOCKS:
            self.parts.append("\n")
        if not self.hidden and tag in {"td", "th"}:
            self.parts.append(" | ")

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.handle_starttag(tag, attrs)
        if tag not in self._VOID:
            self.handle_endtag(tag)

    def handle_endtag(self, tag: str) -> None:
        found = next((i for i in range(len(self.stack) - 1, -1, -1) if self.stack[i][0] == tag), None)
        if found is not None:
            self.hidden -= sum(1 for _, hidden in self.stack[found:] if hidden)
            del self.stack[found:]
        if not self.hidden and tag in self._BLOCKS:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if not self.hidden:
            self.parts.append(data)


def _html_text(data: bytes, content_type: str, final_url: str) -> str:
    charset = re.search(r"charset\s*=\s*['\"]?([\w-]+)", content_type)
    try:
        html = data.decode(charset.group(1) if charset else "utf-8", errors="strict")
    except (UnicodeError, LookupError) as exc:
        raise DocumentSourceError("Не удалось прочитать кодировку страницы. Приложите документ файлом.",
                                  code="source_charset") from exc
    host = (urlsplit(final_url).hostname or "").lower()
    if host in {"accounts.google.com", "login.microsoftonline.com", "login.live.com", "id.yandex.ru"}:
        raise DocumentSourceError("Ссылка открыла страницу входа. Закрытый документ не прочитан; приложите файл.",
                                  code="source_access")
    if host in {"drive.google.com", "docs.google.com", "www.dropbox.com", "dropbox.com", "disk.yandex.ru", "disk.360.yandex.ru"}:
        raise DocumentSourceError(
            "Ссылка открыла страницу облачного хранилища, а не сам документ. "
            "Приложите файл или укажите прямую публичную ссылку для скачивания.", code="source_preview")
    parser = _VisibleHTML()
    parser.feed(html)
    if parser.password or parser.auth_form:
        raise DocumentSourceError("Страница по ссылке предлагает вход. Закрытый документ не прочитан; приложите файл.",
                                  code="source_access")
    if parser.meta_redirect:
        raise DocumentSourceError("Страница предлагает перенаправление вместо документа. Укажите прямую ссылку на файл.",
                                  code="source_redirect")
    lines = [re.sub(r"[\t\r\f\v ]+", " ", line).strip(" |")
             for line in "".join(parser.parts).splitlines()]
    text = "\n".join(line for line in lines if line)
    if len(re.sub(r"\s", "", text)) < 40:
        raise DocumentSourceError(
            "На странице недостаточно читаемого текста. Возможно, она требует JavaScript или входа. "
            "Приложите PDF или фото тизера.", code="source_no_text")
    return "[стр. 1]\n" + text


def read_url(url: str, *, timeout: float = 20.0, max_bytes: int = MAX_BYTES) -> dict[str, Any]:
    """Read one public resource; never follow links inside a downloaded page.

    Returns ``data`` for PDF/JPEG/PNG or ``text`` for static HTML, plus
    ``filename`` and ``source`` for both. Source metadata belongs to the private
    document state, not an application log. A URL may contain a signed query.
    """
    if not 0 < timeout <= 60 or not 0 < max_bytes <= MAX_BYTES:
        raise ValueError("invalid document download limits")
    raw = str(url or "").strip()
    data, header, final_url = _download(raw, time.monotonic() + timeout, max_bytes)
    if not data:
        raise DocumentSourceError("Сервер по ссылке вернул пустой документ.", code="source_empty")
    mime = header.split(";", 1)[0].strip()
    signatures = {
        "application/pdf": data.lstrip(b"\xef\xbb\xbf \t\r\n").startswith(b"%PDF-"),
        "image/png": data.startswith(b"\x89PNG\r\n\x1a\n"),
        "image/jpeg": data.startswith(b"\xff\xd8\xff"),
    }
    if mime in {"text/html", "application/xhtml+xml"} and any(signatures.values()):
        raise DocumentSourceError("Тип HTML-страницы не совпадает с содержимым файла.",
                                  code="source_type_mismatch")
    if mime in signatures and not signatures[mime]:
        raise DocumentSourceError(
            "Тип ответа по ссылке не совпадает с содержимым файла. Документ не прочитан.",
            code="source_type_mismatch")
    if mime in {"", "application/octet-stream", "binary/octet-stream"}:
        mime = next((kind for kind, matches in signatures.items() if matches), "")
    if mime not in _MIME_EXTENSIONS:
        raise DocumentSourceError(
            "По ссылке получен неподдерживаемый формат. Поддерживаются PDF, JPEG, PNG и открытая HTML-страница.",
            code="source_type")
    name = unquote(PurePosixPath(urlsplit(final_url).path).name or "document")
    name = re.sub(r"[\x00-\x1f\x7f/\\]", "_", name)[:160].strip() or "document"
    extension = _MIME_EXTENSIONS[mime]
    if not name.lower().endswith(extension) and not (mime == "image/jpeg" and name.lower().endswith(".jpeg")):
        name += extension
    source = {"kind": "url", "original_url": raw, "final_url": final_url,
              "fetched_at": datetime.now(timezone.utc).isoformat(),
              "sha256": hashlib.sha256(data).hexdigest(), "content_type": mime,
              "bytes": len(data)}
    if mime in {"text/html", "application/xhtml+xml"}:
        return {"text": _html_text(data, header, final_url), "filename": name, "source": source}
    return {"data": data, "filename": name, "source": source}
