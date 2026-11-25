"""One bounded synchronous document operation, inside existing native workers.

Checks surround native IO/parser stages; they do not preempt library CPU calls.
No worker, timer, scheduler or second queue is created here.
"""
from __future__ import annotations

import contextlib
import contextvars
import time
from dataclasses import dataclass
from typing import Callable

DEFAULT_SECONDS = 240.0
_CURRENT = contextvars.ContextVar('document_processing_budget', default=None)
_NOTIFICATION = contextvars.ContextVar('document_failure_notification',default=None)
_SHORT_PUBLICATION = contextvars.ContextVar('document_short_publication',default=False)


class Cancelled(RuntimeError):
    """A newer source or cancellation owns the chat; publish nothing."""


class Expired(RuntimeError):
    public_message = ('Время чтения документа истекло. Разбор не завершён и не принят '
                      'в расчёт. Пришлите PDF с текстовым слоем или нужные страницы отдельно.')

    def __init__(self):
        super().__init__(self.public_message)


@dataclass(frozen=True)
class Budget:
    deadline: float
    current: Callable[[], bool] | None = None

    def remaining(self, cap: float | None = None) -> float:
        if self.current is not None and not self.current():
            raise Cancelled('Document operation is no longer current')
        left = self.deadline - time.monotonic()
        if left <= 0:
            raise Expired()
        return min(left, cap) if cap is not None else left


def remaining(cap: float | None = None) -> float | None:
    notice = _NOTIFICATION.get()
    if notice is not None:
        return notice.remaining(cap)
    budget = _CURRENT.get()
    return budget.remaining(cap) if budget is not None else cap


def deadline() -> float | None:
    budget = _CURRENT.get()
    if budget is None:
        return None
    budget.remaining()
    return budget.deadline


def check() -> None:
    if _NOTIFICATION.get() is not None:
        raise Cancelled('A closed-source notification cannot start source processing')
    remaining()


def post_bytes(request, timeout: float, max_bytes: int = 5*1024*1024) -> bytes:
    """POST to a configured service within the active document's deadline.

    Reuse the source reader's bounded DNS pool, pinned sockets and total header
    deadline. This path never follows redirects or accepts URL credentials.
    Public source URLs still use document_source.read_url and its public-IP gate.
    """
    import http.client
    import io
    import socket
    import urllib.error
    import urllib.parse
    import document_source

    until = deadline()
    if until is None:
        raise RuntimeError('Bounded document transport requires an active operation')
    until = min(until,time.monotonic()+remaining(timeout))
    target = urllib.parse.urlsplit(request.full_url)
    if (target.scheme not in {'http','https'} or not target.hostname
            or target.username is not None or target.password is not None
            or target.fragment or any(c in request.full_url for c in '\r\n\\')):
        raise ValueError('Адрес сервиса проверки территории настроен некорректно.')
    port = target.port or (443 if target.scheme == 'https' else 80)
    response = connection = None
    try:
        endpoints = tuple((*row[:4],(row[4][0],port,*row[4][2:]))
                          for row in document_source._resolve(target.hostname,until))
        check()
        left = document_source._remaining(until)
        if target.scheme == 'https':
            connection = document_source._PinnedHTTPS(target.hostname,endpoints,left)
            connection.port = port
        else:
            # Configured core URLs can be private HTTP endpoints. DNS is already
            # bounded above; connect directly to those resolved socket addresses.
            class PinnedHTTP(http.client.HTTPConnection):
                def connect(self):
                    last = None
                    for family,kind,proto,_,address in endpoints:
                        sock = socket.socket(family,kind,proto)
                        try:
                            check()
                            sock.settimeout(document_source._remaining(until))
                            sock.connect(address)
                            self.sock = sock
                            return
                        except BaseException as exc:
                            sock.close()
                            if not isinstance(exc,OSError):
                                raise
                            last = exc
                    raise last or OSError('No configured service endpoint')
            connection = PinnedHTTP(target.hostname,port,timeout=left)
            connection.response_class = lambda sock,*a,**kw:document_source._DeadlineResponse(
                sock,*a,deadline=until,**kw)
        headers = dict(request.header_items())
        headers['Accept-Encoding'] = 'identity'
        path = urllib.parse.urlunsplit(('','',target.path or '/',target.query,''))
        connection.request(request.get_method(),path,body=request.data,headers=headers)
        check()
        response = connection.getresponse()
        check()
        declared = response.getheader('Content-Length')
        if declared is not None:
            try:
                declared = int(declared)
            except (ValueError,TypeError):
                raise ValueError('Сервис проверки территории передал некорректный размер ответа.') from None
            if not 0 <= declared <= max_bytes:
                raise ValueError('Ответ сервиса проверки территории превышает допустимый размер.')
        chunks,size = [],0
        while True:
            check()
            chunk = response.read1(min(64*1024,max_bytes+1-size))
            check()
            document_source._remaining(until)
            if not chunk:
                break
            size += len(chunk)
            if size > max_bytes:
                raise ValueError('Ответ сервиса проверки территории превышает допустимый размер.')
            chunks.append(chunk)
        if declared is not None and size != declared:
            raise ValueError('Ответ сервиса проверки территории пришёл не полностью.')
        raw = b''.join(chunks)
        if not 200 <= response.status < 300:
            raise urllib.error.HTTPError(request.full_url,response.status,response.reason,
                                         response.headers,io.BytesIO(raw))
        return raw
    except document_source.DocumentSourceError as exc:
        check()
        if exc.code == 'source_timeout':
            raise TimeoutError('Configured document service deadline') from None
        raise RuntimeError('Сервер проверки территории не найден или занят.') from None
    finally:
        try:
            if response is not None:
                response.close()
        finally:
            if connection is not None:
                connection.close()


def delivery_check() -> None:
    delivery_remaining()


def delivery_remaining(cap: float | None = None) -> float | None:
    notice = _NOTIFICATION.get()
    return notice.remaining(cap) if notice is not None else remaining(cap)


def delivery_deadline() -> float | None:
    notice = _NOTIFICATION.get()
    if notice is not None:
        notice.remaining()
        return notice.deadline
    return deadline()


def notification_active() -> bool:
    return _NOTIFICATION.get() is not None


@contextlib.contextmanager
def notification(*, current: Callable[[],bool]):
    """Only delivery can use this15s context; the source budget stays closed."""
    notice = Budget(time.monotonic()+15,current)
    token = _NOTIFICATION.set(notice)
    try:
        notice.remaining()
        yield
    finally:
        _NOTIFICATION.reset(token)


def short_publication() -> bool:
    return _SHORT_PUBLICATION.get()


@contextlib.contextmanager
def publication(*, short: bool = False):
    token = _SHORT_PUBLICATION.set(short)
    try:
        yield
    finally:
        _SHORT_PUBLICATION.reset(token)


@contextlib.contextmanager
def operation(*, current: Callable[[], bool] | None = None, seconds: float = DEFAULT_SECONDS,
              deadline: float | None = None):
    existing = _CURRENT.get()
    if existing is not None:
        existing.remaining()
        yield existing
        return
    until = time.monotonic()+min(float(seconds),DEFAULT_SECONDS)
    budget = Budget(min(until,deadline) if deadline is not None else until,current)
    token = _CURRENT.set(budget)
    try:
        budget.remaining()
        yield budget
    finally:
        _CURRENT.reset(token)
