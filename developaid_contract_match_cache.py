"""Bounded, call-local memoization of pure contract text projections.

No source, cut, ownership decision, payment allocation or result is cached.
Only exact string/None inputs and immutable derived values enter the cache.
Nested history shares the call; another call/thread gets another context.
"""
from __future__ import annotations

import contextlib
import contextvars
import functools
import sys
import threading

MAX_BYTES = 2 * 1024 * 1024
MAX_ENTRIES = 4096
_KINDS = frozenset({'party', 'reference', 'scope'})
_MISSING = object()
_ACTIVE = contextvars.ContextVar('contract_pure_match_cache', default=None)


class _Cache:
    __slots__ = ('owner', 'entries', 'bytes')

    def __init__(self):
        self.owner = threading.current_thread()
        self.entries = {}
        self.bytes = 0


def _current():
    cache = _ACTIVE.get()
    return cache if cache is not None and cache.owner is threading.current_thread() else None


@contextlib.contextmanager
def scope():
    current = _current()
    if current is not None:
        yield current
        return
    cache = _Cache()
    token = _ACTIVE.set(cache)
    try:
        yield cache
    finally:
        _ACTIVE.reset(token)


def scoped(function):
    @functools.wraps(function)
    def run(*args, **kwargs):
        with scope():
            return function(*args, **kwargs)
    return run


def strings(values):
    return all(type(value) is str or value is None for value in values)


def _weight(value, remaining):
    """Conservatively charge every immutable occurrence, including aliases."""
    size = sys.getsizeof(value)
    if size > remaining:
        return None
    if type(value) in (tuple, frozenset):
        for child in value:
            cost = _weight(child, remaining-size)
            if cost is None:
                return None
            size += cost
    elif type(value) not in (str, bool, type(None)):
        return None
    return size


def remember(kind, key, compute):
    """Memoize only explicitly admitted pure inputs; a full cache falls back."""
    if kind not in _KINDS:
        raise ValueError('unknown pure contract projection')
    cache = _current()
    if cache is None or type(key) is not tuple or not strings(key):
        return compute()
    identity = kind, key
    found = cache.entries.get(identity, _MISSING)
    if found is not _MISSING:
        return found
    result = compute()
    if len(cache.entries) < MAX_ENTRIES:
        # The fixed allowance covers the dict slot/index as well as the
        # complete recursively charged key and value. Nested computations may
        # have added entries, so admission uses the remaining budget now.
        size = _weight((identity, result), MAX_BYTES-cache.bytes-128)
        if size is not None:
            cache.entries[identity] = result
            cache.bytes += size+128
    return result


def scalar(kind):
    """Keep the original single-value function, grammar and metadata intact."""
    def decorate(function):
        @functools.wraps(function)
        def run(value):
            return remember(kind, (value,), lambda: function(value))
        return run
    return decorate
