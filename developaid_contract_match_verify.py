"""Same-call verification of every memoized pure matching return.

This observer never creates a cache or records keys, values or arguments.
Only the existing synchronous worker interval is covered by its proof.
"""
from __future__ import annotations

import contextlib
import contextvars
import threading

PURPOSE = 'contract-pure-matching-hit-verify-v1'
KINDS = ('party', 'reference', 'scope')
MAX_COUNT = 2**53 - 1
_VERIFY = contextvars.ContextVar('contract_pure_match_verification', default=None)


class VerificationProblem(RuntimeError):
    def __init__(self):
        super().__init__('Pure matching verification did not complete.')


class Verification:
    def __init__(self):
        self.owner = threading.current_thread()
        self.active = True
        self.proved = False
        self.failure = ''
        self.lock = threading.RLock()
        self.attempted = dict.fromkeys(KINDS, 0)
        self.verified = dict.fromkeys(KINDS, 0)
        self.entered = 0
        self.exited = 0
        self.open_scopes = 0
        self.checking = 0

    def fail(self, code):
        with self.lock:
            if not self.failure:
                self.failure = code

    def require_owner(self, *, allow_proved=False):
        with self.lock:
            if not self.active or self.owner is not threading.current_thread():
                self.fail('inactive_or_foreign_context')
                raise VerificationProblem()
            if self.proved and not allow_proved:
                self.fail('activity_after_proof')
            if self.failure:
                raise VerificationProblem()

    def increment(self, value):
        if type(value) is not int or not 0 <= value < MAX_COUNT:
            self.fail('counter_overflow')
            raise VerificationProblem()
        return value+1

    def proof(self):
        with self.lock:
            self.require_owner(allow_proved=True)
            counts = [self.entered, self.exited, self.open_scopes, self.checking,
                      *self.attempted.values(), *self.verified.values()]
            if (set(self.attempted) != set(KINDS) or set(self.verified) != set(KINDS)
                    or any(type(value) is not int or not 0 <= value <= MAX_COUNT for value in counts)):
                self.fail('counter_overflow_or_invalid')
                raise VerificationProblem()
            if (_VERIFY.get() is not self or self.open_scopes or self.checking or self.entered != self.exited
                    or self.attempted != self.verified or not any(self.attempted.values())):
                self.fail('incomplete_verification')
                raise VerificationProblem()
            self.proved = True
            return {'purpose': PURPOSE, 'state': 'all_observed_hits_verified',
                    'entered_scopes': self.entered, 'exited_scopes': self.exited,
                    'hits': {kind: {'attempted': self.attempted[kind], 'verified': self.verified[kind]} for kind in KINDS},
                    'unexercised_kinds': [kind for kind in KINDS if self.attempted[kind] == 0],
                    'scope': 'current_synchronous_worker_cache_hit_returns', 'timing': 'verification_overhead_included'}


@contextlib.contextmanager
def collect():
    existing = _VERIFY.get()
    if existing is not None:
        existing.require_owner()
        yield existing
        return
    state = Verification()
    token = _VERIFY.set(state)
    try:
        yield state
    finally:
        try:
            with state.lock:
                try:
                    if state.proved:
                        state.proof()  # Also reject a sticky failure between export and worker exit.
                finally:
                    state.active = False
        finally:
            _VERIFY.reset(token)


def enter_scope():
    state = _VERIFY.get()
    if state is None:
        return None
    state.require_owner()
    if state.checking:
        return None  # A verification recomputation is already fully uncached.
    state.entered = state.increment(state.entered)
    state.open_scopes = state.increment(state.open_scopes)
    return state


def observe_call():
    state = _VERIFY.get()
    if state is not None:
        state.require_owner()  # Even an uncached foreign call cannot silently extend this worker interval.


def exit_scope(state):
    if state is not None:
        # Close the observation even when a sticky failure was caught by business code.
        if state.owner is not threading.current_thread() or _VERIFY.get() is not state or not state.active:
            state.fail('inactive_or_foreign_context')
            raise VerificationProblem()
        if state.open_scopes <= 0:
            state.fail('incomplete_verification')
            raise VerificationProblem()
        state.open_scopes -= 1
        state.exited = state.increment(state.exited)


def _strict_equal(first, second):
    kind = type(first)
    if kind is not type(second):
        return False
    if kind in (str, bool, type(None)):
        return first == second
    if kind is tuple:
        return len(first) == len(second) and all(_strict_equal(a, b) for a, b in zip(first, second))
    if kind is frozenset:
        return len(first) == len(second) and all(any(_strict_equal(a, b) for b in second) for a in first)
    return False


def hit(kind, cached, compute):
    state = _VERIFY.get()
    if state is None:
        return
    state.require_owner()
    if kind not in KINDS:
        state.fail('unknown_cache_kind')
        raise VerificationProblem()
    state.attempted[kind] = state.increment(state.attempted[kind])
    state.checking = state.increment(state.checking)
    try:
        from developaid_contract_match_cache import disabled_scope
        with disabled_scope():
            recomputed = compute()
        if not _strict_equal(cached, recomputed):
            state.fail('value_or_type_mismatch')
            raise VerificationProblem()
        state.verified[kind] = state.increment(state.verified[kind])
    except BaseException:
        state.fail('recompute_or_comparison_error')
        raise VerificationProblem() from None
    finally:
        state.checking -= 1
