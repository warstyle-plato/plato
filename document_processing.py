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
