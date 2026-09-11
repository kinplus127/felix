"""Serialize all access to one tidalapi Session.

tidalapi mutates session state for audio quality and OAuth refresh. Catalog,
resolve, and prefetch may run on different threads, so they share one RLock.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from typing import TypeVar
from weakref import WeakKeyDictionary

import tidalapi

T = TypeVar("T")

_gates: WeakKeyDictionary[object, SessionGate] = WeakKeyDictionary()
_gates_guard = threading.Lock()


class SessionGate:
    """One lock per Session. Prefer gate_for() so callers share the same gate."""

    def __init__(self, session: tidalapi.Session) -> None:
        self.session = session
        self._lock = threading.RLock()

    def __enter__(self) -> SessionGate:
        self._lock.acquire()
        return self

    def __exit__(self, *_exc: object) -> None:
        self._lock.release()

    def run(self, fn: Callable[[], T]) -> T:
        with self:
            return fn()


def gate_for(session: tidalapi.Session | SessionGate) -> SessionGate:
    """Return the shared gate for this session (idempotent)."""
    if isinstance(session, SessionGate):
        return session
    with _gates_guard:
        gate = _gates.get(session)
        if gate is None:
            gate = SessionGate(session)
            _gates[session] = gate
        return gate
