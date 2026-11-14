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
    budget = _CURRENT.get()
    return budget.remaining(cap) if budget is not None else cap


def deadline() -> float | None:
    budget = _CURRENT.get()
    if budget is None:
        return None
    budget.remaining()
    return budget.deadline


def check() -> None:
    remaining()


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
